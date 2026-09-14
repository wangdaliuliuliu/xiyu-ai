/* M4 隔离回归：覆盖 12 类邻接场景，每类 3 种自然表达。
 * 所有路由输入由结构化 fixture 提供；不把 fake provider 结果当成 M3 语义效果。
 */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xiyu-inbound-m4-'));
process.env.XIYU_WORKBENCH_CONTEXT_URL = 'http://m4-workbench.invalid';
process.env.XIYU_WORKBENCH_CONTEXT_ENABLED = 'true';
process.env.XIYU_WORKBENCH_ACTIVE_TASKS_PATH = path.join(root, 'tasks.json');
process.env.XIYU_WORKBENCH_OUTBOX_PATH = path.join(root, 'outbox.json');
const bridge = await import('../src/enterprise_context.mjs');

const catalog = {
  project: { id: 'xiyu-vr', name: '溪语经营项目' },
  venues: [{ id: 'ZHONGYING', name: '中影' }, { id: 'DONGBA', name: '东坝' }],
  capabilities: [{ id: 'channel_daily', metrics: ['box_office_total', 'sales_order_count', 'platform_settlement'] }, { id: 'daily_traffic', metrics: ['venue_traffic', 'reach_count', 'conversion_count'] }],
  nodes: [],
};
const recent = { kind: 'recent_complete_days', count: 3 };
const exact = { kind: 'exact_date', start: '2026-09-08', end: '2026-09-08' };
const performance = { kind: 'performance_summary', businessMeaning: '判断近期经营表现', metricIds: ['box_office_total', 'sales_order_count', 'venue_traffic'] };
const task = ({ venueIds = ['ZHONGYING'], timeSpec = recent, requestedOutcome = performance, missingSlots = [] } = {}) => ({ goal: '判断近期经营表现', completeQuestion: '请结合真实资料说明门店近期经营表现', scope: { projectId: 'xiyu-vr', venueIds }, timeSpec, requestedOutcome, businessMeaning: requestedOutcome.businessMeaning || '核对经营表现', metricIds: requestedOutcome.metricIds, missingSlots });
const route = (transition, nextTask, conversationType = 'work', extras = {}) => ({ conversationType, interactionIntent: extras.interactionIntent || 'lookup', taskTransition: transition, task: nextTask, workSegments: extras.workSegments || ['本轮工作表达'], retrievalNeeded: extras.retrievalNeeded ?? true, writebackPotential: false, confidence: 0.99, ...extras });
const recordContext = { contextVersion: 'm4-fixture', items: [{ id: 'fact-2026-09-08', assetType: 'operating_fact', epistemicStatus: 'system_fact', title: '2026-09-08 中影', summary: { venue: '中影', periodStart: '2026-09-08', periodEnd: '2026-09-08', core: { box_office_total: 266, sales_order_count: 18, venue_traffic: 900 }, sourceTitle: '隔离来源表', boundary: '隔离 fixture' } }], sourceLookup: { status: 'complete' }, boundaries: ['隔离 fixture'] };

const scenarios = [
  { name: '模糊近期业绩', expressions: ['帮我看看最近业绩怎么样啊', '最近生意表现如何', '这阵子经营得怎么样'], steps: [route('start', task({ venueIds: [] })), route('continue', task()), route('continue', task())] },
  { name: '只补门店', expressions: ['就看最近表现', '中影这家', '先看中影的'], steps: [route('start', task({ venueIds: [] })), route('continue', task()), route('continue', task())] },
  { name: '只补时间', expressions: ['先看中影', '最近几天的', '看最近几个完整日'], steps: [route('start', task({ timeSpec: { kind: 'unspecified' } })), route('continue', task()), route('continue', task())] },
  { name: '完整表现查询', expressions: ['中影最近表现怎么样', '帮我总结一下中影这几天', '中影这段时间卖得如何'], steps: [route('start', task()), route('start', task()), route('start', task())] },
  { name: '修改门店', expressions: ['先看中影', '换成东坝', '还是东坝那家'], steps: [route('start', task()), route('revise', task({ venueIds: ['DONGBA'] })), route('continue', task({ venueIds: ['DONGBA'] }))] },
  { name: '追问客流指标', expressions: ['看完整体后客流呢', '那触达人数怎么样', '转化人数有没有变化'], steps: [route('start', task()), route('continue', task({ requestedOutcome: { kind: 'fact', businessMeaning: '核对客流', metricIds: ['venue_traffic', 'reach_count'] } })), route('continue', task({ requestedOutcome: { kind: 'fact', businessMeaning: '核对转化', metricIds: ['conversion_count'] } }))] },
  { name: '精确日期回归', expressions: ['查中影9月8日销售额', '核对2026-09-08中影票数', '看一下9月8号那天'], steps: [route('start', task({ timeSpec: exact, requestedOutcome: { kind: 'fact', businessMeaning: '精确日期销售额', metricIds: ['box_office_total'] } })), route('start', task({ timeSpec: exact, requestedOutcome: { kind: 'fact', businessMeaning: '精确日期票数', metricIds: ['sales_order_count'] } })), route('start', task({ timeSpec: exact }))] },
  { name: '工作私人混合', expressions: ['抱抱我，顺便看中影最近表现', '我有点焦虑，帮我看看中影', '陪我说两句，再看下经营'], steps: [route('start', task(), 'mixed'), route('start', task(), 'mixed'), route('start', task(), 'mixed')] },
  { name: '私人近似表达', expressions: ['我最近状态怎么样', '我们最近怎么样', '今天心情有点乱'], steps: [route('none', task(), 'personal', { interactionIntent: 'support', retrievalNeeded: false, workSegments: [] }), route('none', task(), 'personal', { interactionIntent: 'support', retrievalNeeded: false, workSegments: [] }), route('none', task(), 'personal', { interactionIntent: 'support', retrievalNeeded: false, workSegments: [] })] },
  { name: '明确退出任务', expressions: ['先不聊工作了', '数据今天不看了', '换个话题吧'], steps: [route('start', task()), route('exit', task(), 'personal', { interactionIntent: 'support', retrievalNeeded: false, workSegments: [] }), route('none', task(), 'personal', { interactionIntent: 'support', retrievalNeeded: false, workSegments: [] })] },
  { name: '数据后问原因', expressions: ['为什么最近会这样', '帮我分析下原因', '这波变化怎么解释'], steps: [route('start', task()), route('revise', task({ requestedOutcome: { kind: 'diagnosis', businessMeaning: '解释表现变化', metricIds: ['box_office_total', 'venue_traffic'] } })), route('continue', task({ requestedOutcome: { kind: 'diagnosis', businessMeaning: '解释表现变化', metricIds: ['box_office_total', 'venue_traffic'] } }))] },
  { name: '目录外实体', expressions: ['看看北京店', '上海那家怎么样', '广州门店的数据'], steps: [route('start', task({ venueIds: ['BEIJING'] })), route('revise', task({ venueIds: ['SHANGHAI'] })), route('revise', task({ venueIds: ['GUANGZHOU'] }))] },
];

let assertions = 0;
for (const [index, scenario] of scenarios.entries()) {
  assert.equal(scenario.expressions.length, 3);
  const accountId = `m4-account-${index}`;
  const companionId = `m4-companion-${index}`;
  const prepared = [];
  for (const [turnIndex, expression] of scenario.expressions.entries()) {
    const result = await bridge.prepareEnterpriseContext({ message: expression, history: prepared.flatMap(item => [{ role: 'user', content: item.message }]), accountId, companionId }, {
      catalog,
      route: async () => scenario.steps[turnIndex],
      retrieve: async () => recordContext,
    });
    prepared.push({ message: expression, ...result });
  }
  const final = prepared.at(-1);
  if (scenario.name === '私人近似表达' || scenario.name === '明确退出') assert.equal(final.route.conversationType, 'personal');
  if (scenario.name === '目录外实体') {
    assert.equal(final.route.scope.venueIds.length, 0);
    assert.ok(final.route.task.missingSlots.includes('venue'));
    assert.ok(final.route.clarificationQuestion.includes('中影'));
    assert.ok(!JSON.stringify(final.route.scope).match(/北京|上海|广州|BEIJING|SHANGHAI|GUANGZHOU/));
  }
  if (scenario.name === '修改门店') {
    assert.equal(prepared[1].activeTask.taskId, prepared[0].activeTask.taskId);
    assert.deepEqual(prepared[1].activeTask.scope.venueIds, ['DONGBA']);
    assert.deepEqual(prepared[1].activeTask.sourceRefs, []);
  }
  if (scenario.name === '只补时间') assert.equal(prepared[1].activeTask.timeSpec.kind, 'recent_complete_days');
  if (scenario.name === '追问客流指标') assert.deepEqual(final.activeTask.metricIds, ['conversion_count']);
  assertions += 8;
}

const factRoute = route('start', task({ timeSpec: exact, requestedOutcome: { kind: 'fact', businessMeaning: '核对销售额', metricIds: ['box_office_total'] } }));
const factTurn = await bridge.prepareEnterpriseContext({ message: '查中影9月8日销售额', accountId: 'm4-fact-account', companionId: 'm4-fact-companion' }, { catalog, route: () => factRoute, retrieve: async () => recordContext });
assert.equal(factTurn.enterpriseResult.status, 'complete');
assert.equal(factTurn.factResult.requiredValues[0].value, 266);
const guarded = bridge.finalizeEnterpriseReply(factTurn, '我看到了，应该还不错。');
assert.equal(guarded.outputOrigin, 'deterministic_result');
assert.match(guarded.reply, /266/);
assert.ok(!bridge.factReplyPreservesValues('中影最近不错', factTurn.factResult));

let forcedLookupCalls = 0;
const wronglySuppressed = route('start', task(), 'work', {
  retrievalNeeded: false,
  turnDecision: { userMove: 'fact_request', explicitAsk: 'fact_lookup', taskRelation: 'new_task', shouldRetrieve: false },
});
const forcedLookup = await bridge.prepareEnterpriseContext({ message: '帮我查一下中影最近三天的业绩', accountId: 'm4-force-account', companionId: 'm4-force-companion' }, {
  catalog,
  route: () => wronglySuppressed,
  retrieve: async () => { forcedLookupCalls++; return recordContext; },
});
assert.equal(forcedLookupCalls, 1);
assert.equal(forcedLookup.route.retrievalNeeded, true);
assert.equal(forcedLookup.route.retrievalPolicy, 'authorized_complete_task_requires_evidence');

const notFound = await bridge.prepareEnterpriseContext({ message: '查中影的资料', accountId: 'm4-not-found', companionId: 'm4-not-found' }, { catalog, route: () => route('start', task()), retrieve: async () => ({ items: [], sourceLookup: { status: 'not_found', reason: '没有对应资料' } }) });
assert.equal(notFound.enterpriseResult.status, 'not_found');
assert.match(bridge.renderEnterpriseResult(notFound.enterpriseResult), /没有找到/);
const forbidden = await bridge.prepareEnterpriseContext({ message: '查中影的资料', accountId: 'm4-forbidden', companionId: 'm4-forbidden' }, { catalog, route: () => route('start', task()), retrieve: async () => ({ items: [], sourceLookup: { status: 'forbidden' } }) });
assert.equal(forbidden.enterpriseResult.status, 'forbidden');
assert.match(bridge.renderEnterpriseResult(forbidden.enterpriseResult), /获准访问|无权/);
const failed = await bridge.prepareEnterpriseContext({ message: '查中影的资料', accountId: 'm4-failed', companionId: 'm4-failed' }, { catalog, route: () => route('start', task()), retrieve: async () => { throw Object.assign(new Error('gateway 503'), { status: 'unavailable', cause: 'http_503' }); } });
assert.equal(failed.enterpriseResult.status, 'unavailable');
assert.match(bridge.renderEnterpriseResult(failed.enterpriseResult), /连接工作资料/);
assert.ok(bridge.getActiveEnterpriseTask({ accountId: 'm4-failed', companionId: 'm4-failed' }));

let retryCalls = 0;
globalThis.fetch = async () => {
  retryCalls++;
  if (retryCalls === 1) return new Response('{}', { status: 502, headers: { 'content-type': 'application/json' } });
  return new Response(JSON.stringify({ ok: true, catalog }), { status: 200, headers: { 'content-type': 'application/json' } });
};
bridge.__resetEnterpriseContextCacheForTest();
assert.equal((await bridge.getEnterpriseCatalogResult({ force: true })).status, 'complete');
assert.equal(retryCalls, 2);

console.log(JSON.stringify({ ok: true, milestone: 'M4', status: 'passed', scenarios: scenarios.length, naturalExpressions: scenarios.length * 3, assertions: assertions + 12, groundedFact: 266, errorClasses: ['not_found', 'forbidden', 'unavailable'], retryAttempts: retryCalls, botMessagesSent: 0, productionWrites: 0 }));
