import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xiyu-agency-cycle-'));
process.env.DB_PATH = path.join(root, 'bot.db');
const { getDb, listAgencyIntentions, listAgencyFeedback, updateAgencyAction, commitAgencyReceipt, getAgencyAction } = await import('../src/db.mjs');
const { runAgencyCycle } = await import('../src/proactive.mjs');

const db = getDb();
const row = db.prepare('INSERT INTO companions (user_id, bot_id, name) VALUES (NULL, ?, ?)').run('cycle-bot', '循环角色');
const companionId = Number(row.lastInsertRowid);
const responses = [
  { shouldAct: true, domain: 'work', desiredChange: '确认东大店销售与客流口径并推进判断', appraisalSummary: '已有销售和客流事实，但统计范围影响结论', basisRefs: ['sales:2026-09-02', 'traffic:2026-09-02'], priorityClass: 'high', confidence: 0.9, needsUserInput: true, reconsiderAfterMinutes: 30 },
  { actionType: 'contact_text', strategySummary: '先交付已发现的事实，再只问客流统计范围', inputRefs: ['traffic:2026-09-02'], expectedEffect: '口径确认后继续计算转化', needsUserInput: true, completionCriteria: ['问题送达', '用户回答后给出改变了什么判断'], nextIfAnswered: 'continue_intention', nextIfUnanswered: 'wait_for_new_evidence', notBeforeMinutes: 0, expiresAfterMinutes: 120, dedupKey: 'dongda-traffic-scope-v1', shouldContact: true },
];
let calls = 0;
const fakeExtract = async (_system, userContent) => ({ ok: true, text: JSON.stringify(responses[calls++ % 2]), usage: { prompt_tokens: 1, completion_tokens: 1 }, provider: 'fake', model: 'fixture', requestId: `fixture-${calls}`, attempts: 1, fallback: false, error: null, latencyMs: 1 });

const legacy = await runAgencyCycle({ accountId: 1, companionId, mode: 'legacy', deps: { extractStructuredInfoDetailed: fakeExtract } });
assert.equal(legacy.status, 'legacy');
assert.equal(calls, 0);

const shadow = await runAgencyCycle({ accountId: 1, companionId, mode: 'shadow', trigger: 'business_event', decision: { selectedCandidateType: 'business_delivery', action: 'deliver_grounded_next_step' }, snapshot: { evidence: ['sales:2026-09-02', 'traffic:2026-09-02'] }, deps: { extractStructuredInfoDetailed: fakeExtract, now: '2026-09-07T10:00:00.000Z' } });
assert.equal(shadow.status, 'prepared');
assert.equal(shadow.calls, 2);
assert.equal(shadow.action.actionType, 'contact_text');
assert.equal(shadow.intention.state, 'ready');

let executed = 0;
const enabled = await runAgencyCycle({ accountId: 1, companionId, mode: 'enabled', allowContact: true, decision: { selectedCandidateType: 'business_delivery', action: 'deliver_grounded_next_step' }, snapshot: { evidence: ['sales:2026-09-02', 'traffic:2026-09-02'] }, deps: { extractStructuredInfoDetailed: fakeExtract, now: '2026-09-07T10:01:00.000Z', executeContactAction: async () => { executed += 1; } } });
assert.equal(enabled.status, 'contact_ready');
assert.equal(executed, 1);
assert.equal(enabled.intention.state, 'ready');
const sending = updateAgencyAction(enabled.action.id, { accountId: 1, companionId, expectedVersion: enabled.action.version, state: 'sending' });
assert.ok(sending);
const receipt = commitAgencyReceipt({
  accountId: 1,
  companionId,
  intentionId: enabled.intention.id,
  actionId: enabled.action.id,
  intentionVersion: enabled.intention.version,
  actionVersion: sending.version,
  receipt: { state: 'delivered', providerMessageIds: ['fixture-contact-1'], resultRefs: [{ kind: 'text', delivered: true }] },
});
assert.equal(receipt.status, 'committed');
assert.equal(receipt.intention.state, 'waiting_user');
assert.equal(getAgencyAction(enabled.action.id, { accountId: 1, companionId }).state, 'delivered');
assert.equal(listAgencyIntentions({ accountId: 1, companionId }).length, 1);
assert.equal(listAgencyFeedback({ accountId: 1, companionId }).length, 0);

const failed = await runAgencyCycle({ accountId: 1, companionId, mode: 'shadow', deps: { extractStructuredInfoDetailed: async () => ({ ok: false, fallback: false, error: 'fixture_failure' }) } });
assert.equal(failed.status, 'inconclusive');
assert.equal(failed.error, 'appraisal_provider_failure');

console.log(JSON.stringify({ status: 'passed', calls, executed, intentionId: enabled.intention.id, root }));
