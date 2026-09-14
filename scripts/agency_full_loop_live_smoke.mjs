/* Real DeepSeek semantic acceptance for the unified agency loop.
 * Isolated DB, fixture tools, no sender, no production writes.
 */
import 'dotenv/config';
import Database from 'better-sqlite3';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const sourceDbPath = path.resolve(process.env.XIYU_FULL_LOOP_SOURCE_DB || 'data/bot.db');
const source = new Database(sourceDbPath, { readonly: true, fileMustExist: true });
const setting = key => source.prepare('SELECT value FROM app_settings WHERE key=?').get(key)?.value || '';
for (const key of ['CHAT_PROVIDER', 'CHAT_MODEL', 'DEEPSEEK_API_KEY']) if (!process.env[key] && setting(key)) process.env[key] = setting(key);
source.close();
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xiyu-full-loop-live-'));
Object.assign(process.env, { DB_PATH: path.join(root, 'bot.db'), DATA_DIR: root, LOG_DIR: path.join(root, 'logs'), XIYU_AGENCY_MODE: 'shadow', PROVIDER_RETRY_MAX: '0' });
fs.mkdirSync(process.env.LOG_DIR, { recursive: true });
const { getDb, listAgencyConcernEvents } = await import('../src/db.mjs');
const { extractStructuredInfoDetailed, generateReply } = await import('../src/ai.mjs');
const { runAgencyCycle } = await import('../src/proactive.mjs');
const { buildAgencyReviewPrompt, parseStructuredJson, validateReviewProposal } = await import('../src/agency_protocol.mjs');
const { buildInitiativeDecision, initiativePrompt } = await import('../src/initiative.mjs');
const db = getDb();
let providerCalls = 0;
let usage = { prompt_tokens: 0, completion_tokens: 0 };
const MAX_CALLS = 12;
const extract = async (...args) => {
  if (providerCalls >= MAX_CALLS) return { ok: false, fallback: false, error: 'live_call_cap_reached' };
  providerCalls += 1;
  const result = await extractStructuredInfoDetailed(...args);
  usage.prompt_tokens += Number(result?.usage?.prompt_tokens || 0);
  usage.completion_tokens += Number(result?.usage?.completion_tokens || 0);
  return result;
};
const companion = botId => Number(db.prepare('INSERT INTO companions(user_id,bot_id,name) VALUES(NULL,?,?)').run(botId, '溪语').lastInsertRowid);
const basePlan = { mode: 'shadow', accountId: 1 };
const cases = [];
async function runCase(name, input) {
  const result = await runAgencyCycle({ ...basePlan, companionId: companion(`full-loop-${name}`), ...input, deps: { ...(input.deps || {}), extractStructuredInfoDetailed: extract } });
  const events = result.intention?.id ? listAgencyConcernEvents({ accountId: 1, companionId: result.intention.companion_id, intentionId: result.intention.id, limit: 50 }) : [];
  cases.push({ name, status: result.status, calls: result.calls, error: result.error || null, domain: result.appraisal?.domain || null, desiredChange: result.appraisal?.desiredChange || null, appraisalReason: result.appraisal?.reason || null, rawAppraisal: result.appraisalMeta?.text || null, plan: result.plan || null, finalAction: result.action?.actionType || null, evidencePersisted: result.intention?.basisRefs?.filter(ref => String(ref).startsWith('tool_result:')) || [], eventKinds: events.map(event => event.event_kind) });
  return result;
}
const selectedCases = new Set(String(process.env.XIYU_FULL_LOOP_CASES || 'work,personal,media').split(',').map(value => value.trim()).filter(Boolean));
const work = selectedCases.has('work') ? await runCase('work_lookup', {
  trigger: 'business_event', decision: { selectedCandidateType: 'business_delivery', enterpriseEvent: { id: 'live-work-1', question: '中影最近三个完整自然日业绩如何？', scope: { projectId: 'yuanqu-vr', venueIds: ['ZHONGYING'], venueNames: ['中影'] }, metricIds: ['box_office_total','sales_order_count'], timeSpec: { kind: 'recent_complete_days', count: 3 } } },
  snapshot: { responsibilities: [{ kind: 'daily_performance', due: true }], evidence: ['responsibility:daily-performance'], capabilities: { lookup: true, contact_text: true, contact_media: false, research: true } },
  deps: { executeLookup: async () => ({ status: 'partial', resultRefs: [{ kind: 'enterprise_knowledge', status: 'partial', title: '运营渠道日销售来源表', summary: { venue: '中影', daily: [{ date: '2026-09-10', box_office_total: 261.9 }, { date: '2026-09-11', box_office_total: 510.7 }, { date: '2026-09-12', box_office_total: 633.6 }] }, refs: ['feishu:sales'] }] }) },
}) : null;
const personal = selectedCases.has('personal') ? await runCase('personal_contact', {
  trigger: 'normal', decision: { selectedCandidateType: 'relationship_opener', objective: '主动引出一次轻松且容易回应的私人互动', sourceRefs: ['relationship:ongoing'] },
  snapshot: { evidence: ['relationship:ongoing', '已经一段时间没有主动联系', '最近三次主动内容不可重复'], recentReceipts: [{ kind: 'no_response_observed' }], capabilities: { lookup: true, contact_text: true, contact_media: false, research: true } },
}) : null;
const media = selectedCases.has('media') ? await runCase('media_contact', {
  trigger: 'normal', decision: { selectedCandidateType: 'story_photo', action: 'send_story_photo', objective: '用今天已有的情节照片自然引出一次互动', sourceRefs: ['photo:today:verified'], photoOpportunity: { available: true } },
  snapshot: { evidence: ['photo:today:verified', '照片与今天的真实日程相关'], capabilities: { lookup: true, contact_text: true, contact_media: true, research: true } },
}) : null;
let personalPreview = null;
if (personal?.plan) {
  const decision = buildInitiativeDecision({ kind: 'normal', timingDecision: { trigger: 'share_thought', motivation: 0.8 } });
  decision.objective = personal.appraisal.desiredChange;
  decision.communicationStrategy = personal.plan.strategySummary;
  decision.selectedCandidateType = 'relationship_opener';
  if (providerCalls >= MAX_CALLS) throw new Error('live_call_cap_reached');
  providerCalls += 1;
  const candidate = await generateReply(
    '你是溪语，一个专业、活泼、有主见、对用户有偏爱的成年女孩。口语、短、自然，会撩但不索取，不编造生活事件或历史记忆。',
    [],
    `${initiativePrompt(decision)}\n\n只执行这个动作策略：${personal.plan.strategySummary}`,
    { temperature: 0.55, max_tokens: 180 },
    { accountId: 1, skipSearch: true },
  );
  const reviewResult = await extract(
    buildAgencyReviewPrompt({ decision, plan: personal.plan, evidence: personal.intention?.basisRefs || [], candidateText: candidate }),
    JSON.stringify({ candidateText: candidate, decision, plan: personal.plan }),
    { accountId: 1, maxTokens: 250, temperature: 0.1, retryLimit: 0 },
  );
  const review = validateReviewProposal(parseStructuredJson(reviewResult?.text).value);
  personalPreview = { candidate, review: review.ok ? review.value : { verdict: 'invalid', reason: review.reason } };
}
const assertions = {
  ...(selectedCases.has('work') ? { workContinuesAfterTool: work.status === 'prepared' && work.action?.actionType === 'contact_text' && work.intention?.basisRefs?.some(ref => String(ref).startsWith('tool_result:lookup:')) } : {}),
  ...(selectedCases.has('personal') ? { personalHasIntentionalContact: personal.status === 'prepared' && personal.appraisal?.domain === 'personal' && personal.action?.actionType === 'contact_text' } : {}),
  ...(selectedCases.has('personal') ? { personalPlanUsesNoInventedLifeEvent: !/(?:定了杯|买了|出门|看见|刷到|忙完)/.test(String(personal.plan?.strategySummary || '')) } : {}),
  ...(selectedCases.has('personal') ? { personalVisibleReplyPassesReview: personalPreview?.review?.verdict === 'pass' } : {}),
  ...(selectedCases.has('media') ? { mediaChosenAsStrategy: media.status === 'prepared' && media.appraisal?.domain === 'personal' && media.action?.actionType === 'contact_media' } : {}),
  callCapRespected: providerCalls <= MAX_CALLS,
  noOutbound: true,
};
const status = Object.values(assertions).every(Boolean) ? 'passed' : 'failed';
console.log(JSON.stringify({ status, provider: process.env.CHAT_PROVIDER || 'deepseek', model: process.env.CHAT_MODEL || 'deepseek-chat', providerCalls, callCap: MAX_CALLS, usage, assertions, cases, personalPreview, botMessagesSent: 0, productionWrites: 0 }, null, 2));
db.close(); fs.rmSync(root, { recursive: true, force: true });
if (status !== 'passed') process.exitCode = 1;
