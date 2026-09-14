/* P1 production-chain smoke: isolated SQLite, fixture catalog/retrieve, no Bot.
 * This is an acceptance test for persistence and compiler boundaries, not a
 * claim about live model quality or online deployment.
 */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xiyu-agency-p1-'));
process.env.DB_PATH = path.join(root, 'bot.db');
process.env.LOG_DIR = path.join(root, 'logs');
process.env.XIYU_AGENCY_MODE = 'shadow';
process.env.XIYU_WORKBENCH_CONTEXT_ENABLED = 'true';
process.env.XIYU_WORKBENCH_CONTEXT_URL = 'http://fixture-workbench.invalid';
process.env.XIYU_WORKBENCH_ACTIVE_TASKS_PATH = path.join(root, 'active-tasks.json');
process.env.XIYU_WORKBENCH_OUTBOX_PATH = path.join(root, 'outbox.json');

const store = await import('../src/db.mjs');
const protocol = await import('../src/agency_protocol.mjs');
const db = store.getDb();
const companionId = Number(db.prepare('INSERT INTO companions (user_id, bot_id, name) VALUES (NULL, ?, ?)').run('p1-fixture', '溪语').lastInsertRowid);
const owner = { accountId: 1, companionId };

const columns = db.prepare('PRAGMA table_info(agency_intentions)').all().map(row => row.name);
for (const column of ['desired_direction', 'unknowns_json', 'next_review_condition', 'last_contact_at']) assert.ok(columns.includes(column), `missing ${column}`);
assert.equal(db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name='agency_concern_events'").get()?.name, 'agency_concern_events');

const intention = store.createAgencyIntention({
  ...owner,
  domain: 'work',
  desiredChange: '核对中影最近完整自然日经营表现',
  desiredDirection: '先拿到可靠的近期表现，再决定是否分析原因',
  unknowns: ['time'],
  nextReviewCondition: '最近完整自然日资料返回后继续',
  appraisalSummary: '入站任务已确认，但仍缺少时间范围',
  basisRefs: ['task:fixture'],
  semanticKey: 'p1:fixture:concern',
  state: 'preparing',
  linkedBusinessTaskRef: 'inbound-task:fixture',
});
assert.ok(intention);
assert.equal(intention.desiredDirection, '先拿到可靠的近期表现，再决定是否分析原因');
assert.deepEqual(intention.unknowns, ['time']);

const event = store.recordAgencyConcernEvent({
  ...owner,
  intentionId: intention.id,
  eventKind: 'task_transition',
  sourceRefs: ['task:fixture'],
  payload: { transition: 'start' },
  expectedVersion: intention.version,
});
assert.ok(event);
assert.equal(store.listAgencyConcernEvents({ ...owner, intentionId: intention.id }).length, 1);
assert.equal(store.recordAgencyConcernEvent({ accountId: 2, companionId, intentionId: intention.id, eventKind: 'cross-owner' }), null);

const advanced = store.updateAgencyIntention(intention.id, { ...owner, expectedVersion: intention.version, state: 'ready', unknowns: [] });
assert.ok(advanced);
assert.equal(store.updateAgencyIntention(intention.id, { ...owner, expectedVersion: intention.version, state: 'active' }), null, 'stale CAS must not overwrite');
assert.equal(store.getAgencyIntention(intention.id, { accountId: 2, companionId }), null, 'cross-owner read must be empty');
assert.equal(store.updateAgencyIntention(intention.id, { accountId: 2, companionId, expectedVersion: advanced.version, state: 'active' }), null, 'cross-owner CAS must be empty');

const evidence = ['feishu:store-daily:2026-09-12', 'source:9754'];
const compiled = protocol.compileSemanticProposal({
  action: 'deliver', message: '中影最近完整自然日资料已核对。', evidence_refs: evidence,
  concern_ref: intention.id,
  semantic_delta: { target: 'none', status_transition: 'keep_active', desired_direction: '交付可靠资料', unknowns: [], next_review_condition: '等待用户追问原因' },
}, { ...owner, concern: advanced, currentEvidenceRefs: evidence, requiresEvidence: true });
assert.equal(compiled.ok, true);
assert.equal(compiled.concernUpdate.expectedVersion, advanced.version);
assert.equal(compiled.concernUpdate.state, 'ready', 'keep_active preserves current state');
assert.equal(protocol.compileSemanticProposal({ action: 'deliver', message: '无来源结论', evidence_refs: ['invented:source'], concern_ref: intention.id, semantic_delta: { target: 'none', status_transition: 'keep_active' } }, { ...owner, concern: advanced, currentEvidenceRefs: evidence, requiresEvidence: true }).reason, 'evidence_ref_not_current');
assert.equal(protocol.compileSemanticProposal({ action: 'deliver', message: '越权', evidence_refs: evidence, concern_ref: 'other-tenant', semantic_delta: { target: 'none', status_transition: 'keep_active' } }, { ...owner, concern: advanced, currentEvidenceRefs: evidence, requiresEvidence: true }).reason, 'concern_ref_invalid');
assert.equal(protocol.compileSemanticProposal({ action: 'hold', concern_ref: null, semantic_delta: { target: 'none', status_transition: 'keep_active' } }, { ...owner, currentEvidenceRefs: evidence }).ok, true, 'one-shot proposal may have null concern');
assert.equal(protocol.compileSemanticProposal({ action: 'deliver', message: '不能无证据完成', concern_ref: intention.id, semantic_delta: { target: 'none', status_transition: 'resolve' } }, { ...owner, concern: advanced, currentEvidenceRefs: evidence, requiresEvidence: true }).reason, 'resolve_requires_evidence');

const action = store.createAgencyAction({ ...owner, intentionId: intention.id, actionType: 'contact_text', strategySummary: '交付核对结果', dedupKey: 'p1:receipt:success', state: 'planned' });
const sending = store.updateAgencyAction(action.id, { ...owner, expectedVersion: action.version, state: 'sending' });
const receipt = store.commitAgencyReceipt({ ...owner, intentionId: intention.id, actionId: action.id, intentionVersion: advanced.version, actionVersion: sending.version, receipt: { state: 'delivered', providerMessageIds: ['fixture-provider-message'], resultRefs: evidence } });
assert.equal(receipt.status, 'committed');
assert.ok(receipt.intention.last_contact_at || receipt.intention.lastContactAt, 'successful delivery records last contact');
assert.equal(store.listAgencyConcernEvents({ ...owner, intentionId: intention.id }).some(item => item.event_kind === 'delivery_receipt'), true);

const budgetIds = [];
for (let i = 0; i < 4; i++) {
  const reservation = store.reserveAgencyBudget({ ...owner, purpose: 'appraise', inputTokens: 10, outputTokens: 10, attempts: 2 });
  assert.ok(reservation);
  budgetIds.push(reservation.id);
}
assert.equal(store.reserveAgencyBudget({ ...owner, purpose: 'appraise', inputTokens: 10, outputTokens: 10, attempts: 2 }), null, 'cognition capacity is bounded');
for (const id of budgetIds) store.settleAgencyBudget({ ...owner, id, usage: { prompt_tokens: 10, completion_tokens: 10 } });

// Two natural-language turns through the existing enterprise entry point:
// first creates a collecting task/concern; the short second turn fills venue
// and time, reuses the same task/concern, and compiles only current evidence.
const enterprise = await import(`../src/enterprise_context.mjs?p1=${Date.now()}`);
const catalog = {
  project: { id: 'xiyu-vr' },
  venues: [{ id: 'ZHONGYING', name: '中影' }], nodes: [], assetTypes: ['metric_record'],
  capabilities: [{ id: 'daily', metrics: ['box_office_total', 'sales_order_count'] }],
};
const route1 = {
  conversationType: 'work', interactionIntent: 'lookup', taskTransition: 'start', retrievalNeeded: true, writebackPotential: false, confidence: 0.98,
  task: { goal: '了解最近业绩', completeQuestion: '帮我看看最近业绩怎么样啊', scope: { projectId: 'xiyu-vr', venueIds: [] }, timeSpec: { kind: 'unspecified' }, requestedOutcome: { kind: 'performance_summary', businessMeaning: '判断近期经营表现', metricIds: ['box_office_total', 'sales_order_count'] }, metricIds: ['box_office_total', 'sales_order_count'], missingSlots: ['venue', 'time'] },
};
const first = await enterprise.prepareEnterpriseContext({ message: '帮我看看最近业绩怎么样啊', history: [], accountId: owner.accountId, companionId, deps: { catalog, route: async () => route1 } });
assert.equal(first.activeTask.origin, 'inbound');
assert.equal(first.activeTask.status, 'collecting');
assert.ok(first.agencyConcern?.id);
const concernId = first.agencyConcern.id;
const route2 = {
  conversationType: 'work', interactionIntent: 'lookup', taskTransition: 'continue', retrievalNeeded: true, writebackPotential: false, confidence: 0.99,
  task: { scope: { projectId: 'xiyu-vr', venueIds: ['ZHONGYING'] }, timeSpec: { kind: 'recent_complete_days', count: 3 }, requestedOutcome: { kind: 'performance_summary', metricIds: ['box_office_total', 'sales_order_count'] }, metricIds: ['box_office_total', 'sales_order_count'], missingSlots: [] },
  semanticProposal: { action: 'deliver', message: '中影最近三个完整自然日资料已读到。', evidence_refs: ['source:zhongying-20260912'], concern_ref: null, semantic_delta: { target: 'none', status_transition: 'keep_active', desired_direction: '先交付近期可靠表现', unknowns: [], next_review_condition: '等待原因追问' } },
};
const second = await enterprise.prepareEnterpriseContext({ message: '最近这几天中影的', history: [{ role: 'user', content: '帮我看看最近业绩怎么样啊' }], accountId: owner.accountId, companionId, deps: {
  catalog, route: async () => route2,
  retrieve: async () => ({ contextVersion: 'fixture-v1', sourceLookup: { status: 'complete' }, items: [{ id: 'source:zhongying-20260912', assetType: 'metric_record', epistemicStatus: 'confirmed_operating_fact', title: '中影日报', summary: { venue: '中影', periodStart: '2026-09-12', periodEnd: '2026-09-12', sourceTitle: '中影日报', core: { box_office_total: 100, sales_order_count: 10 } }, refs: ['feishu:zhongying:2026-09-12'] }], boundaries: [], missingInformation: [] }),
} });
assert.equal(second.activeTask.taskId, first.activeTask.taskId, 'second turn continues same inbound task');
assert.equal(second.agencyConcern.id, concernId, 'second turn continues same durable concern');
assert.equal(second.activeTask.scope.venueIds[0], 'ZHONGYING');
assert.equal(second.activeTask.timeSpec.kind, 'recent_complete_days');
assert.equal(second.semanticCompilation.ok, true, JSON.stringify({ compilation: second.semanticCompilation, current: store.getAgencyIntention(concernId, owner) }));
assert.equal(second.semanticCompilation.concernRef, concernId);
assert.equal(second.semanticCompilation.evidenceRefs.includes('source:zhongying-20260912'), true);

// Restart/idempotence check: close and re-open the same DB through a fresh
// module instance only after all modules using the original singleton finish.
db.close();
const restarted = await import(`../src/db.mjs?restart=${Date.now()}`);
const db2 = restarted.getDb();
assert.equal(db2.prepare("SELECT COUNT(*) AS count FROM agency_concern_events WHERE intention_id=?").get(intention.id).count >= 2, true);
assert.ok(new Set(db2.prepare('PRAGMA table_info(agency_intentions)').all().map(row => row.name)).has('last_contact_at'));

console.log(JSON.stringify({ status: 'passed', checks: 33, node: process.version, abi: process.versions.modules, isolated: root, concernId, taskId: second.activeTask.taskId }));
db2.close();
