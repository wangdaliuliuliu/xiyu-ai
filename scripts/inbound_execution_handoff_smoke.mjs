/** No-provider regression for durable inbound work execution handoff. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xiyu-inbound-handoff-'));
const taskPath = path.join(root, 'active-tasks.json');
process.env.XIYU_WORKBENCH_CONTEXT_URL = 'http://handoff.invalid';
process.env.XIYU_WORKBENCH_CONTEXT_ENABLED = 'true';
process.env.XIYU_WORKBENCH_ACTIVE_TASKS_PATH = taskPath;
process.env.XIYU_WORKBENCH_OUTBOX_PATH = path.join(root, 'outbox.json');
process.env.XIYU_AGENCY_MODE = 'legacy';

const bridge = await import('../src/enterprise_context.mjs');
const catalog = {
  project: { id: 'xiyu-vr', name: '溪语经营项目' },
  venues: [{ id: 'ZHONGYING', name: '中影' }],
  capabilities: [{ id: 'channel_daily', metrics: ['box_office_total', 'sales_order_count'] }],
};
const task = {
  goal: '核对中影近期业绩',
  completeQuestion: '中影最近三个完整自然日的销售额和票数如何',
  scope: { projectId: 'xiyu-vr', venueIds: ['ZHONGYING'] },
  timeSpec: { kind: 'recent_complete_days', count: 3 },
  requestedOutcome: { kind: 'performance_summary', businessMeaning: '判断近期经营表现', metricIds: ['box_office_total', 'sales_order_count'] },
  metricIds: ['box_office_total', 'sales_order_count'],
  missingSlots: [],
};

let retrievals = 0;
const failed = await bridge.prepareEnterpriseContext({ message: '帮我看看中影最近三天业绩', accountId: '9001', companionId: '1' }, {
  catalog,
  route: async () => ({
    conversationType: 'work', interactionIntent: 'lookup', taskTransition: 'start', task,
    workSegments: ['帮我看看中影最近三天业绩'], retrievalNeeded: false, writebackPotential: false, confidence: 0.99,
    turnDecision: { userMove: 'fact_request', explicitAsk: 'fact_lookup', taskRelation: 'new_task', shouldRetrieve: false },
  }),
  retrieve: async () => { retrievals++; throw Object.assign(new Error('fixture source unavailable'), { status: 'unavailable', cause: 'fixture_503' }); },
});
assert.equal(retrievals, 1);
assert.equal(failed.enterpriseResult.status, 'unavailable');
assert.equal(failed.activeTask.status, 'ready');

const pending = bridge.getPendingInboundEnterpriseEvent({ accountId: '9001', companionId: '1' });
assert.equal(pending.origin, 'inbound');
assert.equal(pending.taskType, 'inbound_task_execution');
assert.equal(pending.freshnessPolicy, 'daily_sources_before_weekly_context');
assert.match(pending.sourceVersion, /^inbound-frame:/);

const personal = await bridge.prepareEnterpriseContext({ message: '先说点别的，我今天有点累', accountId: '9001', companionId: '1' }, {
  catalog,
  route: async () => ({ conversationType: 'personal', interactionIntent: 'support', taskTransition: 'none', task, workSegments: [], retrievalNeeded: false, writebackPotential: false, confidence: 0.99 }),
  retrieve: async () => { throw new Error('personal turn must not retrieve'); },
});
assert.equal(personal.route.conversationType, 'personal');
assert.equal(bridge.getPendingInboundEnterpriseEvent({ accountId: '9001', companionId: '1' }).id, pending.id);

const child = spawnSync(process.execPath, ['--input-type=module', '-e', `
  import { getPendingInboundEnterpriseEvent } from ${JSON.stringify(new URL('../src/enterprise_context.mjs', import.meta.url).href)};
  const event = getPendingInboundEnterpriseEvent({ accountId: '9001', companionId: '1' });
  process.stdout.write(JSON.stringify(event));
`], { encoding: 'utf8', env: { ...process.env, XIYU_WORKBENCH_ACTIVE_TASKS_PATH: taskPath } });
assert.equal(child.status, 0, child.stderr);
const restored = JSON.parse(child.stdout);
assert.equal(restored.id, pending.id);
assert.equal(restored.sourceVersion, pending.sourceVersion);

assert.equal(bridge.completeActiveEnterpriseTask({ accountId: '9001', companionId: '1', taskId: pending.id }), true);
assert.equal(bridge.getPendingInboundEnterpriseEvent({ accountId: '9001', companionId: '1' }), null);

console.log(JSON.stringify({
  status: 'passed',
  checks: ['forced lookup despite model suppression', 'failure receipt retained', 'cross-topic persistence', 'restart reconstruction', 'stable task event version', 'complete only after delivery'],
  providerCalls: 0,
  productionWrites: 0,
}));
