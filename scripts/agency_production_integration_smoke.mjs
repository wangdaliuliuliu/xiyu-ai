/*
 * 生产动念链接入冒烟：隔离 DB、假工作台、假结构化模型、无 Bot/无真实 API。
 * 覆盖提示词真实绑定、默认知识查询、工具证据写回、查数锁定和生活事实边界。
 */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const isolated = fs.mkdtempSync(path.join(os.tmpdir(), 'xiyu-agency-production-'));
process.env.DB_PATH = path.join(isolated, 'bot.db');
process.env.LOG_DIR = path.join(isolated, 'logs');
process.env.XIYU_WORKBENCH_CONTEXT_URL = 'http://agency-workbench.test';
process.env.XIYU_WORKBENCH_CONTEXT_ENABLED = 'true';
process.env.XIYU_ENTERPRISE_PROACTIVE_ENABLED = 'true';
process.env.XIYU_WORKBENCH_OUTBOX_PATH = path.join(isolated, 'outbox.json');
process.env.XIYU_WORKBENCH_ACTIVE_TASKS_PATH = path.join(isolated, 'tasks.json');

const requests = [];
const jsonResponse = payload => new Response(JSON.stringify(payload), { status: 200, headers: { 'content-type': 'application/json' } });
globalThis.fetch = async (url, options = {}) => {
  const pathname = new URL(String(url)).pathname;
  const body = options.body ? JSON.parse(options.body) : null;
  requests.push({ pathname, method: options.method || 'GET', body });
  if (pathname === '/api/knowledge/catalog') return jsonResponse({ ok: true, catalog: { project: { id: 'xiyu-vr' }, venues: [{ id: 'DONGBA', name: '东坝店' }], nodes: [] } });
  if (pathname === '/api/knowledge/retrieve') return jsonResponse({ ok: true, context: {
    contextVersion: 'enterprise-context-v1',
    items: [{
      id: 'source:9754', assetType: 'metric_record', epistemicStatus: 'confirmed_operating_fact', title: '门店经营日报',
      summary: { venue: '东坝店', periodStart: '2026-09-02', periodEnd: '2026-09-02', sourceTitle: '门店经营日报', core: { box_office_total: 2730.3, reception_traffic: 201 } },
      refs: ['feishu:store-daily:2026-09-02'],
    }], boundaries: ['只代表表内已记录口径'], missingInformation: [], fingerprint: 'agency-production-smoke',
  } });
  throw new Error(`unexpected request ${pathname}`);
};

const { getDb } = await import('../src/db.mjs');
const { runAgencyCycle } = await import('../src/proactive.mjs');
const { getAgencyPromptBinding } = await import('../src/agency_protocol.mjs');
const { buildEnterpriseFactReply } = await import('../src/enterprise_context.mjs');
const { buildInitiativeDecision, initiativePrompt, initiativeReplyIssue } = await import('../src/initiative.mjs');

const db = getDb();
const companionId = Number(db.prepare('INSERT INTO companions (user_id, bot_id, name) VALUES (NULL, ?, ?)').run('production-smoke', '溪语').lastInsertRowid);
const modelOutputs = [
  { shouldAct: true, domain: 'work', desiredChange: '读取东坝店9月2日经营事实并准备准确答复', appraisalSummary: '来源事件已到达，需要读取权威资料', basisRefs: ['event:9754'], priorityClass: 'high', confidence: 0.96, needsUserInput: false, reconsiderAfterMinutes: 5 },
  { actionType: 'lookup', strategySummary: '按门店、日期和来源读取数据', inputRefs: ['event:9754'], expectedEffect: '下一轮能直接交付有来源的经营事实', needsUserInput: false, completionCriteria: ['工具证据写回当前动念'], nextIfAnswered: 'continue_intention', nextIfUnanswered: 'wait_for_new_evidence', notBeforeMinutes: 0, expiresAfterMinutes: 60, dedupKey: 'production-smoke-lookup-9754', shouldContact: false },
  { actionType: 'contact_text', strategySummary: '直接说清销售额、接待客流、日期和来源', inputRefs: ['tool_result:lookup'], expectedEffect: '用户得到可核对的经营事实', needsUserInput: false, completionCriteria: ['数值、日期与来源完整'], nextIfAnswered: 'continue_if_asked', nextIfUnanswered: 'complete_after_delivery', notBeforeMinutes: 0, expiresAfterMinutes: 60, dedupKey: 'production-smoke-deliver-after-lookup-9754', shouldContact: true },
];
let modelIndex = 0;
const cycle = await runAgencyCycle({
  accountId: 9001,
  companionId,
  mode: 'shadow',
  trigger: 'business_event',
  decision: { selectedCandidateType: 'business_delivery', enterpriseEvent: { id: '9754' } },
  snapshot: {
    evidence: ['event:9754'],
    businessContext: { id: '9754', statement: '核对东坝店9月2日经营数据', question: '东坝店9月2日销售额和接待客流是多少？', scope: { projectId: 'xiyu-vr', venueIds: ['DONGBA'] }, metricIds: ['box_office_total', 'reception_traffic'], evidencePeriod: { date: '2026-09-02' } },
  },
  deps: { extractStructuredInfoDetailed: async () => ({ ok: true, fallback: false, text: JSON.stringify(modelOutputs[modelIndex++]), usage: {}, provider: 'fixture', model: 'fixture' }) },
});

assert.equal(cycle.status, 'prepared');
assert.equal(cycle.calls, 3);
assert.equal(cycle.action.actionType, 'contact_text');
assert.equal(cycle.action.state, 'planned');
assert.ok(requests.some(request => request.pathname === '/api/knowledge/retrieve'));
const retrieveRequest = requests.find(request => request.pathname === '/api/knowledge/retrieve');
assert.equal(retrieveRequest.body?.task?.timeSpec?.kind, 'exact_date');
assert.equal(retrieveRequest.body?.task?.timeSpec?.start, '2026-09-02');
assert.equal(retrieveRequest.body?.task?.timeSpec?.end, '2026-09-02');
assert.ok(cycle.intention.basisRefs.some(ref => ref.includes('2730.3')));
assert.ok(cycle.intention.basisRefs.some(ref => ref.includes('reception_traffic')));
assert.ok(cycle.intention.basisRefs.some(ref => ref.startsWith('prompt:agency-production-')));
assert.equal(cycle.promptBinding.sha256, getAgencyPromptBinding().sha256);

// 查询与交付必须在同一次 cognition 和同一 intention 内完成，
// 不再依赖下一轮调度“碰巧想起”。
const toolAction = db.prepare("SELECT * FROM agency_actions WHERE intention_id=? AND action_type='lookup'").get(cycle.intention.id);
assert.ok(toolAction);
assert.equal(toolAction.state, 'prepared');
assert.equal(cycle.action.intentionId, cycle.intention.id);

const fact = buildEnterpriseFactReply({
  message: '9月2号东坝店销售额是多少？',
  route: { interactionIntent: 'lookup', scope: { venueIds: ['DONGBA'] }, intent: { metricIds: ['box_office_total'], timeRange: '2026-09-02' } },
  context: { items: [{ id: 'source:9754', title: '门店经营日报', summary: { venue: '东坝店', periodStart: '2026-09-02', periodEnd: '2026-09-02', sourceTitle: '门店经营日报', core: { box_office_total: 2730.3 } } }] },
});
assert.equal(fact.matched, true);
assert.match(fact.reply, /2,730\.30 元/);
assert.match(fact.reply, /门店经营日报/);

const personal = buildInitiativeDecision({
  companion: { id: 1, relationship_stage: '暧昧', affection_level: 60 },
  kind: 'normal',
  timingDecision: { trigger: 'share_thought', motivation: 0.8 },
});
assert.match(initiativePrompt(personal), /口语、活泼、有主见/);
const scheduled = { ...personal, selectedCandidateType: 'grounded_life_moment', sourceRefs: ['schedule:2026-09-12:09:00'], lifeEvidence: { fact: '09:00 去上课' } };
assert.match(initiativeReplyIssue(scheduled, '刚上完课，老师把我分去管收钱了。'), /工作分工|新增了细节/);
assert.equal(initiativeReplyIssue(personal, '我本来想等你来找我，后来觉得凭什么呀，先来招惹你一下。'), '');

console.log(JSON.stringify({
  status: 'passed', checks: 18, isolated,
  promptVersion: cycle.promptBinding.promptVersion,
  promptSha256: cycle.promptBinding.sha256,
  persistedEvidence: cycle.intention.basisRefs.filter(ref => ref.startsWith('tool_result:')),
  directFact: fact.reply,
  outboundCalls: 0,
}));
db.close();
