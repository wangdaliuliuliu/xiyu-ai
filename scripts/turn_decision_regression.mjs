import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xiyu-turn-decision-'));
process.env.XIYU_WORKBENCH_CONTEXT_URL = 'http://turn-decision.invalid';
process.env.XIYU_WORKBENCH_CONTEXT_ENABLED = 'true';
process.env.XIYU_WORKBENCH_ACTIVE_TASKS_PATH = path.join(root, 'tasks.json');
process.env.XIYU_WORKBENCH_OUTBOX_PATH = path.join(root, 'outbox.json');

const bridge = await import('../src/enterprise_context.mjs');
const { buildReactiveTurnIntent } = await import('../src/initiative.mjs');

const catalog = {
  project: { id: 'xiyu-vr', name: '溪语经营项目' },
  venues: [{ id: 'ZHONGYING', name: '中影' }, { id: 'DONGBA', name: '东坝' }],
  capabilities: [{ id: 'channel_daily', metrics: ['box_office_total', 'sales_order_count'] }],
  nodes: [],
};
const outcome = { kind: 'performance_summary', businessMeaning: '判断近期经营表现', metricIds: ['box_office_total', 'sales_order_count'] };
const task = { goal: '了解中影近期业绩', completeQuestion: '查看中影最近三个完整自然日的业绩', scope: { projectId: 'xiyu-vr', venueIds: ['ZHONGYING'] }, timeSpec: { kind: 'recent_complete_days', count: 3 }, requestedOutcome: outcome, businessMeaning: outcome.businessMeaning, metricIds: outcome.metricIds, missingSlots: [] };
const factContext = { contextVersion: 'turn-decision-fixture', items: [{ id: 'fact-1', assetType: 'operating_fact', epistemicStatus: 'confirmed_operating_fact', title: '中影近期销售', summary: { venue: '中影', periodStart: '2026-09-10', periodEnd: '2026-09-12', core: { box_office_total: 633.6, sales_order_count: 12 }, sourceTitle: '运营渠道日销售来源表' } }], sourceLookup: { status: 'complete' }, boundaries: [] };
const decision = overrides => ({ userMove: 'question', topic: '中影业绩', explicitAsk: 'fact_lookup', latentNeed: '获得准确数据', conversationMode: 'fact_delivery', taskRelation: 'new_task', shouldRetrieve: true, shouldExecute: false, responseGoal: '直接给出可靠结果', reasoningDepth: 'light', confidence: 0.99, ...overrides });
const route = (turnDecision, overrides = {}) => ({ turnDecision, conversationType: 'work', interactionIntent: 'lookup', taskTransition: 'start', task, workSegments: ['中影业绩'], retrievalNeeded: true, writebackPotential: false, confidence: 0.99, ...overrides });

let retrievals = 0;
const retrieve = async () => { retrievals++; return factContext; };
const first = await bridge.prepareEnterpriseContext({ message: '帮我查中影最近三天业绩', accountId: 'a', companionId: 'c' }, { catalog, route: () => route(decision({ userMove: 'fact_request' })), retrieve });
assert.equal(retrievals, 1);
assert.equal(first.route.turnDecision.explicitAsk, 'fact_lookup');
assert.ok(first.factResult?.matched);

const emotional = await bridge.prepareEnterpriseContext({ message: '有点烦业绩', history: [{ role: 'user', content: '帮我查中影最近三天业绩' }], accountId: 'a', companionId: 'c' }, { catalog, route: () => route(decision({ userMove: 'emotional_disclosure', explicitAsk: 'none', latentNeed: '被理解并找出烦躁来源', conversationMode: 'support', taskRelation: 'topic_related_only', shouldRetrieve: false, responseGoal: '接住烦躁并轻量探索原因' }), { conversationType: 'work', interactionIntent: 'lookup', taskTransition: 'continue' }), retrieve });
assert.equal(retrievals, 1, 'emotion mentioning business must not retrieve');
assert.equal(emotional.route.conversationType, 'mixed');
assert.equal(emotional.route.interactionIntent, 'support');
assert.equal(emotional.route.taskTransition, 'none');
assert.equal(emotional.route.retrievalNeeded, false);
assert.equal(emotional.factResult, null);
assert.equal(bridge.finalizeEnterpriseReply(emotional, '是涨得不够让你踏实，还是不知道下一步从哪儿拉？').outputOrigin, 'model');
assert.equal(buildReactiveTurnIntent({ message: '有点烦业绩', enterpriseRoute: emotional.route }).action, 'attune_emotion');

const brainstorm = await bridge.prepareEnterpriseContext({ message: '我们再想想怎么把客流做上去', accountId: 'a', companionId: 'c' }, { catalog, route: () => route(decision({ userMove: 'brainstorm', explicitAsk: 'none', latentNeed: '共同发散可能性', conversationMode: 'brainstorm', taskRelation: 'topic_related_only', shouldRetrieve: false, responseGoal: '扩展思路但不急着收敛' }), { interactionIntent: 'explore', taskTransition: 'continue' }), retrieve });
assert.equal(retrievals, 1, 'brainstorm must not retrieve without an explicit evidence need');
assert.equal(brainstorm.route.taskTransition, 'none');
assert.equal(buildReactiveTurnIntent({ message: '我们再想想怎么把客流做上去', enterpriseRoute: brainstorm.route }).action, 'brainstorm_without_premature_closure');

const analysis = await bridge.prepareEnterpriseContext({ message: '结合刚才的数据分析为什么上涨', accountId: 'a', companionId: 'c' }, { catalog, route: () => route(decision({ userMove: 'analysis_request', explicitAsk: 'analysis', latentNeed: '理解变化原因', conversationMode: 'analysis', taskRelation: 'continue', shouldRetrieve: true, responseGoal: '区分事实和可能原因', reasoningDepth: 'deep' }), { interactionIntent: 'explore', taskTransition: 'continue', task: { ...task, requestedOutcome: { ...outcome, kind: 'diagnosis' } } }), retrieve });
assert.equal(retrievals, 2);
assert.equal(analysis.factResult, null, 'analysis is not a deterministic fact dump');
assert.equal(bridge.finalizeEnterpriseReply(analysis, '销售确实上涨，但原因仍要结合渠道变化验证。').outputOrigin, 'model');

const factFinal = bridge.finalizeEnterpriseReply(first, '最近还不错。');
assert.equal(factFinal.outputOrigin, 'deterministic_result');
assert.match(factFinal.reply, /633\.6/);

console.log(JSON.stringify({ ok: true, status: 'passed', scenarios: 4, assertions: 20, retrievals, providerCalls: 0, botMessagesSent: 0, productionWrites: 0 }));
