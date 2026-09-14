/**
 * 线上 shadow 栅栏探针。
 *
 * 这个脚本只验证真实工作台 catalog/retrieve 和本地隔离的入站任务→concern
 * 编译链与主动闭环。不导入 bot，且发送器被 shadow/NoOp 双重锁死。发布脚本会把 DB_PATH、
 * ACTIVE_TASKS_PATH 指到临时目录，并以 XIYU_AGENCY_MODE=shadow 运行它。
 */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

assert.equal(String(process.env.XIYU_AGENCY_MODE || '').toLowerCase(), 'shadow', 'shadow mode required');
assert.equal(String(process.env.XIYU_SHADOW_NOOP_SENDER || ''), '1', 'NoOp sender guard required');
assert.equal(String(process.env.XIYU_RELEASE_SHADOW_NO_OUTBOUND || ''), '1', 'shadow outbound guard required');

const projectRoot = path.resolve(process.env.XIYU_SHADOW_PROJECT_ROOT || process.cwd());
assert.equal(fs.realpathSync(process.cwd()), fs.realpathSync(projectRoot), 'shadow cwd must be the installed project root');
const databasePath = path.resolve(String(process.env.DB_PATH || ''));
const dataRoot = path.resolve(String(process.env.DATA_DIR || ''));
const logRoot = path.resolve(String(process.env.LOG_DIR || ''));
const activeTaskPath = path.resolve(String(process.env.XIYU_WORKBENCH_ACTIVE_TASKS_PATH || ''));
const outboxPath = path.resolve(String(process.env.XIYU_WORKBENCH_OUTBOX_PATH || ''));
const localTempRoot = path.resolve(String(process.env.XIYU_SHADOW_TEMP_ROOT || path.dirname(databasePath)));
const projectDataRoot = path.resolve(projectRoot, 'data') + path.sep;
const temporaryPath = value => value === localTempRoot || value.startsWith(`${localTempRoot}${path.sep}`);
const posixTmp = databasePath.replaceAll('\\', '/').startsWith('/tmp/');
const localWindowsTmp = process.env.XIYU_SHADOW_TEST_ALLOW_WINDOWS_TMP === '1' && localTempRoot.startsWith(path.resolve(os.tmpdir()));
assert.ok(posixTmp || localWindowsTmp, 'shadow DB must be in an isolated temporary directory');
assert.ok(!databasePath.startsWith(projectDataRoot), 'shadow DB must not be under the installed project data directory');
for (const value of [databasePath, dataRoot, logRoot, activeTaskPath, outboxPath]) {
  assert.ok(temporaryPath(value), `shadow write path escaped isolated temp root: ${value}`);
}

const {
  getEnterpriseCatalog,
  prepareEnterpriseContext,
} = await import('../src/enterprise_context.mjs');
const {
  compileSemanticProposal,
} = await import('../src/agency_protocol.mjs');
const { runAgencyCycle } = await import('../src/proactive.mjs');
const {
  getDb,
  listAgencyIntentions,
  listAgencyConcernEvents,
} = await import('../src/db.mjs');

const ACCOUNT_ID = Number(process.env.XIYU_SHADOW_ACTOR_ID || 99091301);
const COMPANION_ID = Number(process.env.XIYU_SHADOW_COMPANION_ID || 99091302);
const firstMessage = '帮我看看最近业绩怎么样啊';
const secondMessage = '最近这几天中影的';

// The isolated database is intentionally empty. Seed the owner row required by
// agency_intentions' companion_id foreign key before exercising the real chain.
// This row lives only under XIYU_SHADOW_TEMP_ROOT and never touches production.
const shadowDb = getDb();
shadowDb.prepare(`
  INSERT INTO companions (id, user_id, bot_id, name)
  VALUES (?, NULL, ?, ?)
`).run(COMPANION_ID, `release-shadow-${ACCOUNT_ID}`, '溪语发布隔离验证');

const catalog = await getEnterpriseCatalog({ force: true });
if (!catalog?.project?.id || !Array.isArray(catalog.venues)) throw new Error('catalog_schema_invalid');
const venue = catalog.venues.find(item => String(item?.name || '') === '中影')
  || catalog.venues.find(item => String(item?.name || '').includes('中影'));
if (!venue?.id) throw new Error('catalog_missing_zhongying');

const metrics = ['box_office_total', 'sales_order_count', 'venue_traffic', 'reach_count', 'conversion_count']
  .filter(metric => (catalog.capabilities || []).some(capability => (capability.metrics || []).includes(metric)));
if (!metrics.length) throw new Error('catalog_missing_performance_metrics');

const route = ({ message }) => {
  const second = message === secondMessage;
  const task = {
    goal: '判断近期经营表现',
    completeQuestion: '请结合中影最近三个完整自然日的真实资料说明经营表现',
    scope: { projectId: catalog.project.id, venueIds: second ? [venue.id] : [] },
    timeSpec: { kind: 'recent_complete_days', count: 3 },
    requestedOutcome: { kind: 'performance_summary', businessMeaning: '判断近期经营表现', metricIds: metrics },
    businessMeaning: '判断近期经营表现',
    metricIds: metrics,
    missingSlots: second ? [] : ['venue'],
  };
  return {
    conversationType: 'work',
    interactionIntent: 'lookup',
    taskTransition: second ? 'continue' : 'start',
    task,
    workSegments: [message],
    retrievalNeeded: second,
    writebackPotential: false,
    confidence: 0.99,
    semanticProposal: {
      action: second ? 'lookup' : 'hold',
      messages: [],
      evidence_refs: [],
      concern_ref: null,
      semantic_delta: {
        target: 'none',
        status_transition: 'keep_active',
        desired_direction: '判断近期经营表现',
        unknowns: task.missingSlots,
        next_review_condition: second ? '等待用户继续追问或补充分析方向' : '补齐门店后继续执行',
      },
    },
  };
};

const deps = {
  catalog,
  route,
};
const first = await prepareEnterpriseContext({
  message: firstMessage,
  history: [],
  accountId: ACCOUNT_ID,
  companionId: COMPANION_ID,
  deps,
});
assert.equal(first.route?.taskTransition, 'start');
assert.equal(first.enterpriseResult?.status, 'clarification');
assert.deepEqual(first.activeTask?.missingSlots, ['venue']);

const second = await prepareEnterpriseContext({
  message: secondMessage,
  history: [{ role: 'user', content: firstMessage }],
  accountId: ACCOUNT_ID,
  companionId: COMPANION_ID,
  deps,
});
assert.equal(second.route?.taskTransition, 'continue');
assert.equal(second.activeTask?.taskId, first.activeTask?.taskId, 'second turn must reuse inbound task');
assert.deepEqual(second.activeTask?.scope?.venueIds, [venue.id]);
assert.equal(second.activeTask?.timeSpec?.kind, 'recent_complete_days');
assert.ok(['complete', 'partial'].includes(second.enterpriseResult?.status), `retrieve_not_grounded:${second.enterpriseResult?.status}`);
assert.equal(second.enterpriseResult?.context?.sourceLookup?.venue, venue.name);
assert.ok((second.enterpriseResult?.context?.sourceLookup?.dates || []).length >= 1, 'recent lookup returned no completed dates');

const concern = second.agencyConcern;
assert.ok(concern?.id, 'durable concern missing');
const evidenceRefs = [...new Set((second.context?.items || []).flatMap(item => [item?.id, ...(item?.refs || [])]).filter(Boolean))];
assert.ok(evidenceRefs.length, 'retrieve returned no evidence refs');
const grounded = compileSemanticProposal({
  ...second.route.semanticProposal,
  concern_ref: concern.id,
  evidence_refs: evidenceRefs.slice(0, 8),
}, {
  accountId: ACCOUNT_ID,
  companionId: COMPANION_ID,
  concern,
  currentEvidenceRefs: evidenceRefs,
  requiresEvidence: true,
});
assert.equal(grounded.ok, true, `semantic_compile_failed:${grounded.reason || 'unknown'}`);

const concerns = listAgencyIntentions({ accountId: ACCOUNT_ID, companionId: COMPANION_ID, limit: 20 });
const events = listAgencyConcernEvents({ accountId: ACCOUNT_ID, companionId: COMPANION_ID, limit: 50 });
assert.ok(concerns.some(item => item.id === concern.id), 'concern persistence missing');
assert.ok(events.some(item => item.event_kind === 'task_transition'), 'task transition event missing');

// 真实工作台 + 假模型：验证“动念→查询→证据写回→同动念交付计划”。
// 整条路径不调 provider，不执行联系动作。
let agencyModelCalls = 0;
const agencyModelOutputs = [
  { shouldAct: true, domain: 'work', desiredChange: '读取中影最近三个完整自然日业绩并交付判断', appraisalSummary: '日常经营核查已到期', basisRefs: ['responsibility:daily-performance'], priorityClass: 'high', confidence: 0.96, needsUserInput: false, reconsiderAfterMinutes: 15 },
  { actionType: 'lookup', strategySummary: '从工作台读取中影近三日销售与订单并保留来源', inputRefs: ['responsibility:daily-performance'], expectedEffect: '得到可核对的新证据', needsUserInput: false, completionCriteria: ['数据和来源返回'], nextIfAnswered: 'continue', nextIfUnanswered: 'wait', notBeforeMinutes: 0, expiresAfterMinutes: 60, dedupKey: 'release-shadow-lookup', shouldContact: false },
  { actionType: 'contact_text', strategySummary: '交付近三日数据、趋势、来源与边界', inputRefs: ['tool_result:lookup'], expectedEffect: '用户得到可采取行动的经营判断', needsUserInput: false, completionCriteria: ['事实与边界齐全'], nextIfAnswered: 'continue', nextIfUnanswered: 'complete', notBeforeMinutes: 0, expiresAfterMinutes: 60, dedupKey: 'release-shadow-deliver', shouldContact: true },
];
const agencyCycle = await runAgencyCycle({
  accountId: ACCOUNT_ID,
  companionId: COMPANION_ID,
  mode: 'shadow',
  trigger: 'business_event',
  decision: { selectedCandidateType: 'business_delivery', enterpriseEvent: { id: 'shadow-daily-performance', question: '中影最近三个完整自然日业绩', scope: { projectId: catalog.project.id, venueIds: [venue.id], venueNames: [venue.name] }, metricIds: metrics, timeSpec: { kind: 'recent_complete_days', count: 3 }, evidencePeriod: {} } },
  snapshot: { capabilities: { lookup: true, contact_text: true, contact_media: false, research: true }, responsibilities: [{ kind: 'daily_performance', due: true }], evidence: ['responsibility:daily-performance'] },
  deps: { extractStructuredInfoDetailed: async () => ({ ok: true, fallback: false, text: JSON.stringify(agencyModelOutputs[agencyModelCalls++]), usage: {}, provider: 'fixture', model: 'fixture' }) },
});
assert.equal(agencyCycle.status, 'prepared');
assert.equal(agencyCycle.calls, 3);
assert.equal(agencyCycle.action?.actionType, 'contact_text');
assert.equal(agencyCycle.action?.intentionId, agencyCycle.intention?.id);
assert.ok(agencyCycle.intention?.basisRefs?.some(ref => String(ref).startsWith('tool_result:lookup:')), 'tool evidence not persisted into intention');
const cycleEvents = listAgencyConcernEvents({ accountId: ACCOUNT_ID, companionId: COMPANION_ID, intentionId: agencyCycle.intention.id, limit: 50 });
assert.ok(cycleEvents.some(item => item.event_kind === 'tool_result'), 'tool result event missing');
assert.ok(cycleEvents.some(item => item.event_kind === 'continued_after_tool'), 'same-intention continuation event missing');

const providerCalls = 0;
const botMessagesSent = 0;
const productionWrites = 0;
assert.equal(providerCalls, 0);
assert.equal(botMessagesSent, 0);
assert.equal(productionWrites, 0);

console.log(JSON.stringify({
  ok: true,
  milestone: 'P4',
  status: 'passed',
  mode: 'shadow',
  noopSender: true,
  providerCalls,
  botMessagesSent,
  productionWrites,
  cwd: fs.realpathSync(process.cwd()),
  isolatedWriteRoot: localTempRoot,
  catalog: { projectId: catalog.project.id, venueId: venue.id, venueName: venue.name, metricCount: metrics.length },
  task: { reused: second.activeTask.taskId === first.activeTask.taskId, transition: second.route.taskTransition, timeSpec: second.activeTask.timeSpec.kind },
  retrieve: { status: second.enterpriseResult.status, dates: second.enterpriseResult.context.sourceLookup.dates || [], items: (second.context.items || []).length, evidenceRefs: evidenceRefs.length },
  concern: { id: concern.id, state: second.agencyConcern.state, eventCount: events.length },
  agencyLoop: { calls: agencyCycle.calls, intentionId: agencyCycle.intention.id, finalAction: agencyCycle.action.actionType, eventKinds: cycleEvents.map(item => item.event_kind) },
}, null, 2));
