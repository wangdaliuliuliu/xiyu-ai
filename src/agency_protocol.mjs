/**
 * 统一动念链协议层：只负责提示词组装、结构化结果解析和边界校验。
 * 不访问数据库、不调用模型、不决定调度时机；调度仍归 proactive，
 * 当前主动目的仍归 initiative，避免出现第二套 scheduler/selector。
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';

const MODULE_DIR = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_PROMPT_FILE = path.resolve(MODULE_DIR, '../config/agency-prompts.v1.json');
const REQUIRED_PROMPT_FIELDS = ['desire', 'appraise', 'plan', 'feedback', 'review', 'semanticProposal'];
let promptCache = null;

function resolvePromptFile() {
  return path.resolve(process.env.XIYU_AGENCY_PROMPT_PATH || DEFAULT_PROMPT_FILE);
}

function loadPrompts() {
  const file = resolvePromptFile();
  let raw;
  try { raw = fs.readFileSync(file, 'utf8'); }
  catch (error) { throw new Error(`agency_prompt_unavailable:${error.code || 'read_failed'}`, { cause: error }); }
  let prompts;
  try { prompts = JSON.parse(raw); }
  catch { throw new Error('agency_prompt_invalid_json'); }
  if (prompts?.schemaVersion !== 'agency-prompts-v1' || !prompts?.promptVersion) throw new Error('agency_prompt_version_invalid');
  const missing = REQUIRED_PROMPT_FIELDS.filter(key => !String(prompts?.[key] || '').trim());
  if (missing.length) throw new Error(`agency_prompt_missing_fields:${missing.join(',')}`);
  return {
    file,
    prompts,
    binding: {
      status: 'bound',
      schemaVersion: prompts.schemaVersion,
      promptVersion: prompts.promptVersion,
      sha256: crypto.createHash('sha256').update(raw).digest('hex'),
      file,
    },
  };
}

function getPromptPack() {
  const file = resolvePromptFile();
  if (!promptCache || promptCache.file !== file) promptCache = loadPrompts();
  return promptCache;
}

export function getAgencyPromptBinding() {
  return { ...getPromptPack().binding };
}

export function __resetAgencyPromptCacheForTest() {
  promptCache = null;
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
    responsibilities: asArray(snapshot.responsibilities),
    concernCatalog: asArray(snapshot.concernCatalog),
    recentFeedback: asArray(snapshot.recentFeedback),
    recentReceipts: asArray(snapshot.recentReceipts),
    evidence: asArray(snapshot.evidence),
    businessContext: snapshot.businessContext || null,
    capabilities: snapshot.capabilities || {},
    constraints: snapshot.constraints || {},
    facts: asArray(snapshot.facts),
  };
}

export function buildAgencyAppraisalPrompt(snapshot = {}) {
  const p = getPromptPack().prompts;
  const context = normalizeContextSnapshot(snapshot);
  return `${p.desire || ''}\n\n【当前上下文】\n${JSON.stringify(context)}\n\n【评估协议】\n${p.appraise || ''}\n严格只输出 JSON，不要输出 Markdown、解释或内部思考。`;
}

export function buildAgencyPlanPrompt(snapshot = {}, appraisal = {}) {
  const p = getPromptPack().prompts;
  const context = normalizeContextSnapshot(snapshot);
  return `${p.desire || ''}\n\n【当前上下文】\n${JSON.stringify(context)}\n\n【已校验动念】\n${JSON.stringify(appraisal)}\n\n【动作协议】\n${p.plan || ''}\n严格只输出 JSON，不要输出 Markdown、解释或内部思考。`;
}

export function buildAgencyContinuationPrompt(snapshot = {}, appraisal = {}, toolResult = {}) {
  const p = getPromptPack().prompts;
  const context = normalizeContextSnapshot(snapshot);
  return `${p.desire || ''}\n\n【当前上下文】\n${JSON.stringify(context)}\n\n【已校验动念】\n${JSON.stringify(appraisal)}\n\n【刚完成的工具结果】\n${JSON.stringify(toolResult)}\n\n【继续协议】\n这是同一个动念的工具续接，不得另起话题。结果有价值时，选 contact_text 或在原动念明确需要图片且能力可用时选 contact_media；结果不足或现在不宜联系时选 wait。不得再选 lookup/analyze/research/prepare_media。必须在 strategySummary 中说清交付什么、依据什么、留下什么低负担入口。\n\n${p.plan || ''}\n严格只输出 JSON，不要输出 Markdown、解释或内部思考。`;
}

export function buildAgencyFeedbackPrompt({ snapshot = {}, intention = {}, userMessage = '', delivery = null } = {}) {
  const p = getPromptPack().prompts;
  const context = normalizeContextSnapshot(snapshot);
  return `${p.desire || ''}\n\n【当前上下文】\n${JSON.stringify(context)}\n\n【当前动念】\n${JSON.stringify(intention)}\n\n【用户新消息/回执】\n${compact(userMessage)}\n\n【投递回执】\n${JSON.stringify(delivery || {})}\n\n【反馈协议】\n${p.feedback || ''}\n严格只输出 JSON，不要输出 Markdown、解释或内部思考。`;
}

export function buildAgencyReviewPrompt({ decision = {}, plan = {}, evidence = [], candidateText = '' } = {}) {
  const p = getPromptPack().prompts;
  return `${p.desire || ''}\n\n【当前动念】\n${JSON.stringify(decision)}\n\n【动作策略】\n${JSON.stringify(plan)}\n\n【允许使用的事实】\n${JSON.stringify(asArray(evidence))}\n\n【候选文本】\n${compact(candidateText)}\n\n【复核协议】\n${p.review || ''}\n严格只输出 JSON，不要输出 Markdown、解释或内部思考。`;
}

// 入站、主动和工具继续都共用这一窄协议。模型只能提出语义结果；
// concern 更新、owner/CAS、证据范围和发送能力由 compileSemanticProposal 负责。
const SEMANTIC_ACTIONS = new Set(['deliver', 'hold', 'lookup', 'analyze', 'research', 'prepare_media', 'wait']);
const SEMANTIC_STATUS_TRANSITIONS = new Set(['keep_active', 'park', 'resolve', 'dismiss']);

export function buildSemanticProposalPrompt(snapshot = {}) {
  const p = getPromptPack().prompts;
  const context = normalizeContextSnapshot(snapshot);
  return `${p.desire || ''}\n\n【当前上下文】\n${JSON.stringify(context)}\n\n【统一语义提案协议】\n${p.semanticProposal || ''}\n严格只输出 JSON，不要输出 Markdown、解释或内部思考。`;
}

function normalizeSemanticStatus(raw) {
  if (typeof raw === 'string') return raw;
  if (raw && typeof raw === 'object') return raw.value || raw.status || raw.transition || '';
  return '';
}

export function validateSemanticProposal(raw, { maxMessages = 8, maxEvidenceRefs = 24 } = {}) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return { ok: false, reason: 'not_object' };
  const action = compact(raw.action || raw.actionType).toLowerCase();
  if (!SEMANTIC_ACTIONS.has(action)) return { ok: false, reason: 'invalid_action' };
  const messages = asArray(raw.messages || (raw.message ? [raw.message] : []))
    .map(item => compact(item).slice(0, 2000)).filter(Boolean).slice(0, maxMessages);
  const evidenceRefs = asArray(raw.evidence_refs || raw.evidenceRefs)
    .map(item => compact(item).slice(0, 300)).filter(Boolean).slice(0, maxEvidenceRefs);
  const concernRefRaw = raw.concern_ref ?? raw.concernRef ?? null;
  const concernRef = concernRefRaw === null || concernRefRaw === undefined || concernRefRaw === '' ? null : compact(concernRefRaw).slice(0, 160);
  const delta = raw.semantic_delta || raw.semanticDelta || {};
  if (!delta || typeof delta !== 'object' || Array.isArray(delta)) return { ok: false, reason: 'invalid_semantic_delta' };
  const target = compact(delta.target || 'none').toLowerCase();
  const statusTransition = normalizeSemanticStatus(delta.status_transition ?? delta.statusTransition ?? 'keep_active');
  if (target !== 'none') return { ok: false, reason: 'semantic_delta_target_must_be_none' };
  if (!SEMANTIC_STATUS_TRANSITIONS.has(statusTransition)) return { ok: false, reason: 'invalid_status_transition' };
  const unknowns = asArray(delta.unknowns).map(item => compact(item).slice(0, 500)).filter(Boolean).slice(0, 12);
  if (action === 'deliver' && !messages.length) return { ok: false, reason: 'deliver_requires_message' };
  return {
    ok: true,
    value: {
      action,
      messages,
      message: messages[0] || '',
      evidenceRefs,
      concernRef,
      semanticDelta: {
        target: 'none',
        statusTransition,
        desiredDirection: compact(delta.desired_direction ?? delta.desiredDirection ?? '').slice(0, 1000),
        unknowns,
        nextReviewCondition: compact(delta.next_review_condition ?? delta.nextReviewCondition ?? '').slice(0, 1000),
      },
    },
  };
}

function ownerFromContext(context = {}) {
  const accountId = Number(context.accountId ?? context.owner?.accountId);
  const companionId = Number(context.companionId ?? context.owner?.companionId);
  return Number.isInteger(accountId) && accountId > 0 && Number.isInteger(companionId) && companionId > 0
    ? { accountId, companionId } : null;
}

// 纯确定性编译器：不调用模型、不写库、不把模型字段直接变成 SQL。
// currentEvidenceRefs 是本轮 catalog/retrieve 成功返回后整理的来源集合。
export function compileSemanticProposal(raw, context = {}) {
  const validation = raw?.action && raw?.semanticDelta ? { ok: true, value: raw } : validateSemanticProposal(raw);
  if (!validation.ok) return { ok: false, reason: validation.reason };
  const proposal = validation.value;
  const owner = ownerFromContext(context);
  if (!owner) return { ok: false, reason: 'invalid_owner' };
  const currentEvidenceRefs = new Set(asArray(context.currentEvidenceRefs || context.evidenceRefs).map(item => compact(item)).filter(Boolean));
  const missingEvidence = proposal.evidenceRefs.filter(ref => !currentEvidenceRefs.has(ref));
  if (missingEvidence.length) return { ok: false, reason: 'evidence_ref_not_current', missingEvidence };
  const concern = context.concern || null;
  if (proposal.concernRef && (!concern || String(concern.id) !== proposal.concernRef)) return { ok: false, reason: 'concern_ref_invalid' };
  if (proposal.semanticDelta.statusTransition === 'resolve' && !proposal.evidenceRefs.length) return { ok: false, reason: 'resolve_requires_evidence' };
  if (['deliver', 'analyze'].includes(proposal.action) && context.requiresEvidence === true && !proposal.evidenceRefs.length) return { ok: false, reason: 'grounding_required' };
  const transitionMap = { keep_active: 'active', park: 'suspended', resolve: 'completed', dismiss: 'abandoned' };
  const state = proposal.semanticDelta.statusTransition === 'keep_active'
    ? (concern?.state || 'active')
    : transitionMap[proposal.semanticDelta.statusTransition];
  const concernUpdate = proposal.concernRef && state
    ? {
      id: proposal.concernRef,
        accountId: owner.accountId,
        companionId: owner.companionId,
        owner,
        expectedVersion: Number(concern.version),
        state,
        basisRefs: proposal.evidenceRefs,
        desiredDirection: proposal.semanticDelta.desiredDirection,
        unknowns: proposal.semanticDelta.unknowns,
        nextReviewCondition: proposal.semanticDelta.nextReviewCondition,
        completionEvidence: state === 'completed' ? proposal.evidenceRefs : [],
        resumeEvidence: ['active'].includes(state) && concern.state === 'suspended' ? proposal.evidenceRefs : [],
      }
    : null;
  return {
    ok: true,
    owner,
    action: proposal.action,
    messages: proposal.messages,
    evidenceRefs: proposal.evidenceRefs,
    concernRef: proposal.concernRef,
    semanticDelta: proposal.semanticDelta,
    concernUpdate,
    basis: {
      source: 'semantic_proposal',
      owner,
      concernRef: proposal.concernRef,
      expectedVersion: concernUpdate?.expectedVersion ?? null,
      evidenceRefs: proposal.evidenceRefs,
    },
  };
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
  const constraints = snapshot.constraints && typeof snapshot.constraints === 'object' ? snapshot.constraints : {};
  const evidence = asArray(snapshot.evidence).map(compact).filter(Boolean);
  // 程序只执行上游已确认的结构化边界，不从自然语言里搜关键词
  // 反向覆盖模型的语义判断。
  const explicitBoundary = constraints.pauseProactive === true || constraints.userBoundary === 'pause' || decision.paused === true;
  const provenanceBoundary = constraints.sourceAuthorized === false || constraints.provenanceBlocked === true;
  const repeatBoundary = constraints.isDuplicate === true || Boolean(decision.duplicateOf);
  if (explicitBoundary || provenanceBoundary || repeatBoundary) return { ...appraisal, shouldAct: false, domain: provenanceBoundary || repeatBoundary ? 'work' : 'personal', desiredChange: '', basisRefs: [], needsUserInput: false, confidence: Math.min(appraisal.confidence, 0.2), reason: explicitBoundary ? 'explicit_user_boundary' : provenanceBoundary ? 'provenance_boundary' : 'repeat_boundary' };
  const selectedType = String(decision.selectedCandidateType || '').toLowerCase();
  const relationship = ['relationship_opener', 'story_photo', 'personal', 'relationship'].includes(selectedType);
  const work = /knowledge|business|daily|research|lookup|report/.test(selectedType);
  if (appraisal.shouldAct) {
    const preferredDomain = relationship ? 'personal' : work ? 'work' : appraisal.domain;
    return preferredDomain && preferredDomain !== appraisal.domain ? { ...appraisal, domain: preferredDomain } : appraisal;
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
  const domain = relationship ? 'personal' : work ? 'work' : appraisal.domain || 'mixed';
  return {
    ...appraisal,
    shouldAct: true,
    domain,
    desiredChange: appraisal.desiredChange || compact(decision.objective).slice(0, 1000),
    appraisalSummary: appraisal.appraisalSummary || '已有证据与明确目标，不能因模型保守而丢弃这次可推进机会。',
    basisRefs: appraisal.basisRefs.length ? appraisal.basisRefs : evidence.slice(0, 12),
    confidence: Math.max(0.35, appraisal.confidence),
    needsUserInput: appraisal.needsUserInput,
    reason: appraisal.reason || 'deterministic_opportunity_floor',
  };
}

export function validatePlanProposal(raw, { maxInputRefs = 12, capabilities = null } = {}) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return { ok: false, reason: 'not_object' };
  const actionType = ['lookup', 'analyze', 'research', 'prepare_media', 'contact_text', 'contact_media', 'wait'].includes(raw.actionType) ? raw.actionType : null;
  const strategySummary = compact(raw.strategySummary).slice(0, 2000);
  const inputRefs = asArray(raw.inputRefs).map(item => compact(item).slice(0, 300)).filter(Boolean).slice(0, maxInputRefs);
  const shouldContact = ['contact_text', 'contact_media'].includes(actionType);
  if (actionType && actionType !== 'wait' && capabilities
    && Object.prototype.hasOwnProperty.call(capabilities, actionType)
    && capabilities[actionType] !== true) return { ok: false, reason: `capability_unavailable:${actionType}` };
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
  // 计划的语义由模型与结构化能力校验共同决定。这里不用
  // “已确认/口径/缺口”等字样重写 actionType，避免自然语言误判。
  void snapshot;
  void appraisal;
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

// 连续性锚点不包含会随工具调用变化的证据列表。经营事件优先绑定事件来源，
// 关系主动绑定候选类型；这样补到新证据时会更新原 intention，而不是新建一条。
export function buildAgencyContinuityKey(appraisal = {}, decision = {}) {
  const sourceAnchor = asArray(decision?.sourceRefs)[0];
  const type = compact(decision?.selectedCandidateType);
  const anchor = sourceAnchor
    ? `${type || 'sourced'}:${compact(sourceAnchor)}`
    : type
      ? `candidate:${type}`
      : compact(appraisal?.desiredChange);
  return buildSemanticKey({ domain: appraisal?.domain || 'mixed', desiredChange: anchor, basisRefs: [] });
}

function stableEvidenceText(value) {
  if (typeof value === 'string') return compact(value).slice(0, 700);
  try {
    return JSON.stringify(value).slice(0, 700);
  } catch {
    return compact(value).slice(0, 700);
  }
}

// 工具结果由运行时写回既有 intention，模型只消费紧凑证据，不负责复制整份状态。
export function compactAgencyResultRefs(resultRefs = [], { actionType = 'tool' } = {}) {
  return asArray(resultRefs).map((ref, index) => {
    const body = stableEvidenceText(ref);
    return body ? `tool_result:${compact(actionType)}:${index + 1}:${body}` : '';
  }).filter(Boolean).slice(0, 12);
}

export function mergeAgencyEvidenceRefs(current = [], additions = [], maxItems = 16) {
  const output = [];
  for (const item of [...asArray(current), ...asArray(additions)]) {
    const text = stableEvidenceText(item);
    if (text && !output.includes(text)) output.push(text);
  }
  return output.slice(-Math.max(1, Math.min(20, Number(maxItems) || 16)));
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
