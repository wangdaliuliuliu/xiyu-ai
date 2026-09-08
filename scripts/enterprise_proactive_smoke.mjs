/*
 * 企业主动协同最小回归：不访问真实微信、模型或工作台。
 * 覆盖“刷新业务事件 → 拉取待投递事件 → 保存活动任务 → 短回答回绑”。
 */
import assert from 'node:assert/strict';
import os from 'node:os';
import path from 'node:path';
import fs from 'node:fs';

const activeTasksPath = path.join(os.tmpdir(), `xiyu-enterprise-task-smoke-${process.pid}.json`);
process.env.XIYU_WORKBENCH_CONTEXT_URL = 'http://workbench.test';
process.env.XIYU_WORKBENCH_CONTEXT_ENABLED = 'true';
process.env.XIYU_ENTERPRISE_PROACTIVE_ENABLED = 'true';
process.env.XIYU_WORKBENCH_ACTIVE_TASKS_PATH = activeTasksPath;

const event = {
  id: 'event-smoke-1', eventType: 'knowledge_gap', taskType: 'knowledge_gap_followup', statement: '中影：科技馆客流回落，原因还需要现场事实确认。',
  question: '科技馆客流回落具体影响了哪些时段？', expectedAction: '告诉我最确定的一点就好。',
  sourceRefs: ['fact:tech-museum'], knowledgeGapId: 'gap-1',
  actorId: 'account-1', scope: { projectId: 'yuanqu-vr', venueIds: ['ZHONGYING'] }, status: 'pending'
};
const calls = [];
globalThis.fetch = async (url, options = {}) => {
  calls.push({ url: String(url), method: options.method || 'GET', body: options.body ? JSON.parse(options.body) : null });
  if (String(url).endsWith('/api/knowledge/catalog')) {
    return new Response(JSON.stringify({ ok: true, catalog: { project: { id: 'yuanqu-vr' }, venues: [{ id: 'ZHONGYING', name: '中影' }], nodes: [] } }), { status: 200 });
  }
  if (String(url).endsWith('/api/intelligence/events/refresh')) {
    return new Response(JSON.stringify({ ok: true, created: [event] }), { status: 200 });
  }
  if (String(url).includes('/api/intelligence/events?')) {
    return new Response(JSON.stringify({ ok: true, items: [event] }), { status: 200 });
  }
  if (String(url).includes('/api/intelligence/events/event-smoke-1')) {
    return new Response(JSON.stringify({ ok: true, event: { ...event, status: 'delivered' } }), { status: 200 });
  }
  if (String(url).endsWith('/api/knowledge/retrieve')) {
    return new Response(JSON.stringify({ ok: true, context: { contextVersion: 'enterprise-context-v1', items: [{ id: 'fact:tech-museum', assetType: 'operating_fact', epistemicStatus: 'confirmed_operating_fact', title: '科技馆客流', summary: '中影店科技馆客流回落。' }], boundaries: [], missingInformation: ['具体影响时段'], fingerprint: 'smoke' } }), { status: 200 });
  }
  return new Response(JSON.stringify({ ok: true }), { status: 200 });
};

const {
  pullEnterpriseEvents,
  acknowledgeEnterpriseEvent,
  rememberActiveEnterpriseTask,
  getActiveEnterpriseTask,
  completeActiveEnterpriseTask,
  markActiveEnterpriseTaskAnswerReceived,
  markActiveEnterpriseTaskFeedbackDelivered,
  enterpriseFeedbackSatisfiesTask,
  normalizeEnterpriseUserFacingText,
  prepareEnterpriseContext,
} = await import('../src/enterprise_context.mjs');

const events = await pullEnterpriseEvents({ accountId: 'account-1', limit: 1, purposes: ['knowledge_acquisition'] });
assert.equal(events.length, 1);
assert.equal(events[0].question, '科技馆客流回落具体影响了哪些时段？');
await acknowledgeEnterpriseEvent(events[0].id, { status: 'delivered', deliveryNote: 'companion:1' });
const task = rememberActiveEnterpriseTask({ accountId: 'account-1', companionId: 'companion-1', event: events[0] });
assert.equal(task.status, 'awaiting_answer');
const active = getActiveEnterpriseTask({ accountId: 'account-1', companionId: 'companion-1' });
assert.equal(active.taskId, 'conversation-task:event-smoke-1');
assert.equal(normalizeEnterpriseUserFacingText('日度traffic 和 daily_traffic'), '表里的每日客流数值 和 表里的每日客流数值');
const prepared = await prepareEnterpriseContext({ accountId: 'account-1', companionId: 'companion-1', message: '周末下午最明显，周一基本没有影响。' }, {
  route: () => ({ conversationType: 'personal', replyToActiveTask: true, workSegments: [], scope: {}, intent: {}, retrievalNeeded: false, writebackPotential: true, confidence: 0.8 }),
  retrieve: async () => ({ contextVersion: 'enterprise-context-v1', items: [{ id: 'fact:tech-museum', assetType: 'operating_fact', epistemicStatus: 'confirmed_operating_fact', title: '科技馆客流', summary: '中影店科技馆客流回落。' }], boundaries: [], missingInformation: [], fingerprint: 'smoke' })
});
assert.equal(prepared.route.conversationType, 'work');
assert.equal(prepared.route.reason, 'active_business_task_reply');
assert.equal(prepared.activeTask.taskId, task.taskId);
assert.match(prepared.promptBlock, /当前经营任务续接/);
assert.equal(markActiveEnterpriseTaskAnswerReceived({ accountId: 'account-1', companionId: 'companion-1', taskId: task.taskId, answer: '周末下午最明显' }), true);
assert.equal(enterpriseFeedbackSatisfiesTask(task, '所以我会把周末下午单独拆出来看，下一步先核对那个时段的来源。'), true);
assert.equal(markActiveEnterpriseTaskFeedbackDelivered({ accountId: 'account-1', companionId: 'companion-1', taskId: task.taskId, feedback: '所以我会把周末下午单独拆出来看，下一步先核对那个时段的来源。' }), true);
const personal = await prepareEnterpriseContext({ accountId: 'account-1', companionId: 'companion-1', message: '晚安，想你了' }, {
  route: () => ({ conversationType: 'personal', replyToActiveTask: false, confidence: 1 }),
});
assert.equal(personal.route.conversationType, 'personal');
const exit = await prepareEnterpriseContext({ accountId: 'account-1', companionId: 'companion-1', message: '先不聊工作了' });
assert.equal(exit.route.conversationType, 'personal');
assert.equal(completeActiveEnterpriseTask({ accountId: 'account-1', companionId: 'companion-1', taskId: task.taskId }), true);
assert.equal(getActiveEnterpriseTask({ accountId: 'account-1', companionId: 'companion-1' }), null);
fs.rmSync(activeTasksPath, { force: true });
console.log(JSON.stringify({ ok: true, eventRefresh: calls.some(call => call.url.endsWith('/api/intelligence/events/refresh')), eventPull: calls.some(call => call.url.includes('/api/intelligence/events?')), reboundRoute: prepared.route.reason }));
