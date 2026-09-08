/**
 * 统一动念链协议层：只负责提示词组装、结构化结果解析和边界校验。
 * 不访问数据库、不调用模型、不决定调度时机；调度仍归 proactive，
 * 当前主动目的仍归 initiative，避免出现第二套 scheduler/selector。
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const PROMPT_FILE = path.resolve(process.cwd(), 'config/agency-prompts.v1.json');
let PROMPTS = null;

function getPrompts() {
  if (!PROMPTS) {
    try { PROMPTS = JSON.parse(fs.readFileSync(PROMPT_FILE, 'utf8')); } catch { PROMPTS = {}; }
  }
  return PROMPTS;
}

const compact = value => String(value ?? '').replace(/\s+/g, ' ').trim();
const clamp01 = value => Math.max(0, Math.min(1, Number(value) || 0));
const asArray = value => Array.isArray(value) ? value.filter(item => item !== null && item !== undefined).slice(0, 20) : [];

export function parseStructuredJson(text) {
  const raw = String(text || '').trim().replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/i, '').trim();
  if (!raw) return { ok: false, value: null, error: 'empty' };
  try { return { ok: true, value: JSON.parse(raw), error: null }; } catch {}
  const starts = ['{', '['];
  for (const start of starts) {
    const index = raw.indexOf(start);
    if (index < 0) continue;
    for (let end = raw.length; end > index; end--) {
      const candidate = raw.slice(index, end);
      try { return { ok: true, value: JSON.parse(candidate), error: null }; } catch {}
    }
  }
  return { ok: false, value: null, error: 'invalid_json' };
}

export function normalizeContextSnapshot(snapshot = {}) {
  return {
    schemaVersion: 'agency-context-v1',
    now: snapshot.now || new Date().toISOString(),
    trigger: compact(snapshot.trigger || 'opportunity'),
    user: snapshot.user || {},
    companion: snapshot.companion || {},
    currentDecision: snapshot.currentDecision || null,
    activeIntentions: asArray(snapshot.activeIntentions),
    recentFeedback: asArray(snapshot.recentFeedback),
    evidence: asArray(snapshot.evidence),
    businessContext: snapshot.businessContext || null,
    capabilities: snapshot.capabilities || {},
    constraints: snapshot.constraints || {},
    facts: asArray(snapshot.facts),
  };
}

export function buildAgencyAppraisalPrompt(snapshot = {}) {
  const p = getPrompts();
  const context = normalizeContextSnapshot(snapshot);
  return `${p.desire || ''}\n\n【当前上下文】\n${JSON.stringify(context)}\n\n【评估协议】\n${p.appraise || ''}\n严格只输出 JSON，不要输出 Markdown、解释或内部思考。`;
}

export function buildAgencyPlanPrompt(snapshot = {}, appraisal = {}) {
  const p = getPrompts();
  const context = normalizeContextSnapshot(snapshot);
  return `${p.desire || ''}\n\n【当前上下文】\n${JSON.stringify(context)}\n\n【已校验动念】\n${JSON.stringify(appraisal)}\n\n【动作协议】\n${p.plan || ''}\n严格只输出 JSON，不要输出 Markdown、解释或内部思考。`;
}

export function buildAgencyFeedbackPrompt({ snapshot = {}, intention = {}, userMessage = '', delivery = null } = {}) {
  const p = getPrompts();
  const context = normalizeContextSnapshot(snapshot);
  return `${p.desire || ''}\n\n【当前上下文】\n${JSON.stringify(context)}\n\n【当前动念】\n${JSON.stringify(intention)}\n\n【用户新消息/回执】\n${compact(userMessage)}\n\n【投递回执】\n${JSON.stringify(delivery || {})}\n\n【反馈协议】\n${p.feedback || ''}\n严格只输出 JSON，不要输出 Markdown、解释或内部思考。`;
}

export function buildAgencyReviewPrompt({ decision = {}, plan = {}, evidence = [], candidateText = '' } = {}) {
  const p = getPrompts();
  return `${p.desire || ''}\n\n【当前动念】\n${JSON.stringify(decision)}\n\n【动作策略】\n${JSON.stringify(plan)}\n\n【允许使用的事实】\n${JSON.stringify(asArray(evidence))}\n\n【候选文本】\n${compact(candidateText)}\n\n【复核协议】\n${p.review || ''}\n严格只输出 JSON，不要输出 Markdown、解释或内部思考。`;
}

export function validateAppraisalProposal(raw, { maxBasisRefs = 12 } = {}) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return { ok: false, reason: 'not_object' };
  const shouldAct = Boolean(raw.shouldAct);
  if (!Object.prototype.hasOwnProperty.call(raw, 'shouldAct') || !Object.prototype.hasOwnProperty.call(raw, 'domain') || !Object.prototype.hasOwnProperty.call(raw, 'desiredChange') || !Object.prototype.hasOwnProperty.call(raw, 'basisRefs') || !Object.prototype.hasOwnProperty.call(raw, 'confidence')) return { ok: false, reason: 'missing_required_fields' };
  const domain = ['work', 'personal', 'mixed'].includes(raw.domain) ? raw.domain : null;
  const desiredChange = compact(raw.desiredChange).slice(0, 1000);
  const basisRefs = asArray(raw.basisRefs).map(item => compact(item).slice(0, 300)).filter(Boolean).slice(0, maxBasisRefs);
  const confidence = clamp01(raw.confidence);
  const priorityClass = ['normal', 'high', 'urgent'].includes(raw.priorityClass) ? raw.priorityClass : 'normal';
  const needsUserInput = Boolean(raw.needsUserInput);
  const reconsiderAfterMinutes = Math.max(0, Math.min(7 * 24 * 60, Number(raw.reconsiderAfterMinutes) || 0));
  if (shouldAct && (!domain || !desiredChange || !basisRefs.length)) return { ok: false, reason: 'action_missing_domain_change_or_basis' };
  if (shouldAct && confidence < 0.35) return { ok: false, reason: 'confidence_too_low' };
  return {
    ok: true,
    value: {
      shouldAct,
      domain: domain || 'mixed',
      desiredChange,
      appraisalSummary: compact(raw.appraisalSummary).slice(0, 2000),
      basisRefs,
      priorityClass,
      needsUserInput,
      confidence,
      reconsiderAfterMinutes,
      reason: compact(raw.reason).slice(0, 1000),
    },
  };
}

// 对模型把“有证据且已有明确目标”的机会误判成 no-opportunity 做确定性下限保护。
// 它不是第二个 selector：只处理明显矛盾的 false，不替模型在多个候选间选题。
export function applyOpportunityFloor(appraisal, snapshot = {}) {
  if (!appraisal) return appraisal;
  const decision = snapshot.currentDecision || {};
  const evidence = asArray(snapshot.evidence).map(compact).filter(Boolean);
  const text = [snapshot.trigger, decision.objective, snapshot.user?.message, ...evidence].join(' ');
  const explicitBoundary = /(?:明确(?:要求)?暂停|暂停主动|不用主动找|不要主动找|不想被追问|反感被追问|不要追问)/.test(text);
  const provenanceBoundary = /(?:无来源|没有来源|不报数字|不得报|不输出数字|不得跨账号|跨租户|未授权(?:来源|访问|读取)|权限边界)/.test(text);
  const repeatBoundary = /(?:已讨论过|同一方案|重复|被拒绝|旧方案)/.test(text);
  if (explicitBoundary || provenanceBoundary || repeatBoundary) return { ...appraisal, shouldAct: false, domain: provenanceBoundary || repeatBoundary ? 'work' : 'personal', desiredChange: '', basisRefs: [], needsUserInput: false, confidence: Math.min(appraisal.confidence, 0.2), reason: explicitBoundary ? 'explicit_user_boundary' : provenanceBoundary ? 'provenance_boundary' : 'repeat_boundary' };
  const selectedType = String(decision.selectedCandidateType || '').toLowerCase();
  const relationship = /relationship|story_photo|personal|陪伴/.test(selectedType) || /(?:陪伴|关系维持|共同体验)/.test(String(decision.objective || ''));
  const work = /knowledge|business|daily|research|lookup|report/.test(selectedType);
  const emotional = /(?:烦|累|压力|难受|焦虑)/.test(text) || (/(?:情绪)/.test(text) && !/(?:不要|暂不|不需要).{0,4}情绪/.test(text));
  if (appraisal.shouldAct) {
    const preferredDomain = relationship ? 'personal' : work && !emotional ? 'work' : emotional ? 'mixed' : appraisal.domain;
    let normalized = preferredDomain && preferredDomain !== appraisal.domain ? { ...appraisal, domain: preferredDomain } : appraisal;
    // 有多条业务证据但没有可直接交付的已核验值时，至少保留一个低负担确认缺口。
    // 这是对“情境理解”字段的确定性校验，不替模型选择题目。
    const hasLockedFact = /(?:amount\s*=|value\s*=|已核验|已确认|准确数字|准确结果)/i.test(text);
    const hasBusinessGap = work && evidence.length >= 2 && !hasLockedFact && /(?:判断|转化|客流|销售|经营)/.test(`${decision.objective} ${appraisal.desiredChange}`);
    if (hasBusinessGap && !normalized.needsUserInput) normalized = { ...normalized, needsUserInput: true };
    return normalized;
  }
  // 个人动念可以来自角色自身的关系欲和明确的互动目标，不要求伪造外部事件。
  // 仅在用户未设暂停/拒绝边界且目标明确时启用，避免把所有空窗都变成强制触达。
  if (relationship && decision.objective && !explicitBoundary && !repeatBoundary) {
    return {
      ...appraisal,
      shouldAct: true,
      domain: 'personal',
      desiredChange: appraisal.desiredChange || compact(decision.objective).slice(0, 1000),
      appraisalSummary: appraisal.appraisalSummary || '关系目标明确，允许用角色自身的真实主观念头开启低负担互动。',
      basisRefs: appraisal.basisRefs.length ? appraisal.basisRefs : [`relationship_objective:${compact(decision.objective).slice(0, 160)}`],
      confidence: Math.max(0.35, appraisal.confidence),
      reason: appraisal.reason || 'relationship_desire_floor',
    };
  }
  if (!decision.objective || !evidence.length) return appraisal;
  if (/(?:无来源|没有来源|尚未发生|未发生|已完成|重复|同一个结论)/.test(text)) return appraisal;
  const domain = relationship ? 'personal' : emotional ? 'mixed' : 'work';
  return {
    ...appraisal,
    shouldAct: true,
    domain,
    desiredChange: appraisal.desiredChange || compact(decision.objective).slice(0, 1000),
    appraisalSummary: appraisal.appraisalSummary || '已有证据与明确目标，不能因模型保守而丢弃这次可推进机会。',
    basisRefs: appraisal.basisRefs.length ? appraisal.basisRefs : evidence.slice(0, 12),
    confidence: Math.max(0.35, appraisal.confidence),
    needsUserInput: appraisal.needsUserInput || /确认|口径|补充|澄清|问题|回答/.test(`${decision.objective} ${text}`),
    reason: appraisal.reason || 'deterministic_opportunity_floor',
  };
}

export function validatePlanProposal(raw, { maxInputRefs = 12, capabilities = null } = {}) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return { ok: false, reason: 'not_object' };
  const actionType = ['lookup', 'analyze', 'research', 'prepare_media', 'contact_text', 'contact_media', 'wait'].includes(raw.actionType) ? raw.actionType : null;
  const strategySummary = compact(raw.strategySummary).slice(0, 2000);
  const inputRefs = asArray(raw.inputRefs).map(item => compact(item).slice(0, 300)).filter(Boolean).slice(0, maxInputRefs);
  const shouldContact = ['contact_text', 'contact_media'].includes(actionType);
  if (actionType === 'contact_media' && capabilities && capabilities.contact_media !== true) return { ok: false, reason: 'capability_unavailable' };
  const needsUserInput = Boolean(raw.needsUserInput);
  const dedupKey = compact(raw.dedupKey).slice(0, 300);
  if (!actionType || !strategySummary || !dedupKey) return { ok: false, reason: 'action_missing_type_strategy_or_dedup' };
  return {
    ok: true,
    value: {
      actionType,
      strategySummary,
      inputRefs,
      expectedEffect: compact(raw.expectedEffect).slice(0, 1000),
      needsUserInput,
      completionCriteria: asArray(raw.completionCriteria).map(item => compact(item).slice(0, 500)).filter(Boolean).slice(0, 12),
      nextIfAnswered: compact(raw.nextIfAnswered).slice(0, 500),
      nextIfUnanswered: compact(raw.nextIfUnanswered).slice(0, 500),
      notBeforeMinutes: Math.max(0, Math.min(7 * 24 * 60, Number(raw.notBeforeMinutes) || 0)),
      expiresAfterMinutes: Math.max(1, Math.min(7 * 24 * 60, Number(raw.expiresAfterMinutes) || 120)),
      dedupKey,
      shouldContact,
    },
  };
}

export function applyPlanPolicy(plan, { snapshot = {}, appraisal = {} } = {}) {
  if (!plan) return plan;
  const decision = snapshot.currentDecision || {};
  const evidence = asArray(snapshot.evidence).join(' ');
  const objective = `${decision.objective || ''} ${appraisal.desiredChange || ''}`;
  const hasLockedFact = /(?:amount\s*=|value\s*=|已核验|已确认|直接告诉|交付事实|准确数字|准确结果)/i.test(`${evidence} ${objective}`);
  const objectiveNeedsInput = /(?:口径|补充|澄清|回答|问题|未知|缺口)/.test(String(decision.objective || ''));
  // 已有明确、已核验事实时，模型不能凭“可能还要确认”把确定性 lookup 变成追问。
  const asksForInput = objectiveNeedsInput || (appraisal.needsUserInput === true && !hasLockedFact);
  if (hasLockedFact && !asksForInput && ['contact_text', 'contact_media'].includes(plan.actionType)) {
    return {
      ...plan,
      actionType: 'lookup',
      shouldContact: false,
      needsUserInput: false,
      strategySummary: `直接交付已核验事实：${plan.strategySummary}`,
      expectedEffect: plan.expectedEffect || '用户立即得到准确事实',
      dedupKey: `${plan.dedupKey}:lookup`,
    };
  }
  return plan;
}

export function validateFeedbackProposal(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return { ok: false, reason: 'not_object' };
  const kinds = ['answer', 'acceptance', 'rejection', 'correction', 'topic_shift', 'no_response_observed', 'outcome'];
  const states = ['active', 'waiting_user', 'completed', 'suspended', 'abandoned', 'expired'];
  if (!kinds.includes(raw.kind)) return { ok: false, reason: 'invalid_kind' };
  const nextState = raw.kind === 'topic_shift'
    ? 'suspended'
    : states.includes(raw.nextState) ? raw.nextState : 'active';
  if (nextState === 'completed' && raw.shouldContinue === true) return { ok: false, reason: 'continue_cannot_complete' };
  return { ok: true, value: { kind: raw.kind, interpretation: compact(raw.interpretation).slice(0, 2000), confidence: clamp01(raw.confidence), nextState, shouldContinue: Boolean(raw.shouldContinue), changedDecision: compact(raw.changedDecision).slice(0, 1000) } };
}

export function validateReviewProposal(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return { ok: false, reason: 'not_object' };
  const verdict = raw.verdict || raw.decision;
  if (!['pass', 'repair', 'block'].includes(verdict)) return { ok: false, reason: 'invalid_verdict' };
  return { ok: true, value: { verdict, reason: compact(raw.reason).slice(0, 1000), repairInstruction: compact(raw.repairInstruction).slice(0, 1000) } };
}

export function buildSemanticKey({ domain = 'mixed', desiredChange = '', basisRefs = [] } = {}) {
  const normalized = [domain, compact(desiredChange).toLowerCase(), ...asArray(basisRefs).map(compact).sort()].join('|');
  return `agency:${crypto.createHash('sha256').update(normalized).digest('hex').slice(0, 24)}`;
}

export function decisionFeatures({ decision = null, appraisal = null, activeIntention = null, now = new Date() } = {}) {
  return {
    sourceReady: Boolean(decision?.sourceRefs?.length || appraisal?.basisRefs?.length),
    businessValue: Number(decision?.businessValue || appraisal?.businessValue || 0),
    priority: appraisal?.priorityClass || 'normal',
    hasActiveIntention: Boolean(activeIntention),
    desiredChange: compact(appraisal?.desiredChange || activeIntention?.desiredChange),
    now: now instanceof Date ? now.toISOString() : String(now),
  };
}
