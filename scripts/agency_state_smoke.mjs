import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xiyu-agency-state-'));
process.env.DB_PATH = path.join(root, 'bot.db');

const {
  getDb,
  createAgencyIntention,
  getAgencyIntention,
  listAgencyIntentions,
  findAgencyIntentionBySemanticKey,
  updateAgencyIntention,
  createAgencyAction,
  getAgencyActionByDedup,
  updateAgencyAction,
  commitAgencyReceipt,
  recordAgencyFeedback,
  listAgencyFeedback,
} = await import('../src/db.mjs');

const db = getDb();
const companion = db.prepare('INSERT INTO companions (user_id, bot_id, name) VALUES (NULL, ?, ?)').run('smoke-bot', '验收角色');
const companionId = Number(companion.lastInsertRowid);

const intention = createAgencyIntention({
  accountId: 1,
  companionId,
  desireVersion: 'desire-v1',
  domain: 'work',
  desiredChange: '弄清东大店销售下降是否由客流口径混用造成，并给出下一步',
  appraisalSummary: '已有两个来源，统计范围仍不确定。',
  basisRefs: ['fixture:sales:2026-09-02', 'fixture:traffic:2026-09-02'],
  semanticKey: 'venue:dongda|decision:traffic-conversion:2026-09-02',
  state: 'candidate',
  priorityClass: 'high',
});
assert.ok(intention?.id);
assert.equal(intention.version, 1);
assert.equal(findAgencyIntentionBySemanticKey({ accountId: 1, companionId, semanticKey: intention.semanticKey })?.id, intention.id);
assert.equal(findAgencyIntentionBySemanticKey({ accountId: 2, companionId, semanticKey: intention.semanticKey }), null);

const ready = updateAgencyIntention(intention.id, { accountId: 1, companionId, expectedVersion: 1, state: 'ready', reconsiderAfter: '2026-09-07T12:00:00.000Z' });
assert.equal(ready.state, 'ready');
assert.equal(ready.version, 2);
assert.equal(updateAgencyIntention(intention.id, { accountId: 1, companionId, expectedVersion: 1, state: 'active' }), null, 'CAS must reject stale proposal');

const action = createAgencyAction({
  intentionId: intention.id,
  accountId: 1,
  companionId,
  actionType: 'contact_text',
  strategySummary: '先说明已发现的两个客流数值，再只问统计范围',
  inputRefs: ['fixture:traffic:2026-09-02'],
  expectedEffect: '用户给出口径后可以继续计算转化',
  needsUserInput: true,
  completionCriteria: ['问题已送达', '回答后交付改变了什么判断'],
  nextIfAnswered: 'continue_intention',
  nextIfUnanswered: 'wait_for_new_evidence',
  dedupKey: 'intention:contact:traffic-scope:v1',
  state: 'planned',
});
assert.ok(action?.id);
assert.equal(createAgencyAction({ intentionId: intention.id, accountId: 1, companionId, actionType: 'contact_text', dedupKey: action.dedupKey })?.id, action.id, 'duplicate action must be idempotent');
assert.equal(getAgencyActionByDedup({ accountId: 1, companionId, dedupKey: action.dedupKey }).id, action.id);
const sending = updateAgencyAction(action.id, { accountId: 1, companionId, expectedVersion: 1, state: 'sending' });
const receipt = commitAgencyReceipt({ accountId: 1, companionId, intentionId: intention.id, actionId: action.id, intentionVersion: ready.version, actionVersion: sending.version, receipt: { state: 'delivered', providerMessageIds: ['test-message-1'], resultRefs: [{ kind: 'text', delivered: true }] } });
assert.equal(receipt.status, 'committed');
assert.equal(receipt.action.state, 'delivered');
assert.equal(receipt.intention.state, 'waiting_user');

const feedback = recordAgencyFeedback({ accountId: 1, companionId, intentionId: intention.id, actionId: action.id, sourceMessageId: 'user-message-1', kind: 'answer', rawRef: '大盘客流是商场总客流', interpretation: '用户确认统计范围', confidence: 0.95 });
assert.ok(feedback?.id);
assert.equal(recordAgencyFeedback({ accountId: 1, companionId, intentionId: intention.id, actionId: action.id, sourceMessageId: 'user-message-1', kind: 'answer', rawRef: '重复', interpretation: '重复', confidence: 0.2 })?.id, feedback.id);
assert.equal(listAgencyFeedback({ accountId: 1, companionId, intentionId: intention.id }).length, 1);
assert.equal(listAgencyIntentions({ accountId: 1, companionId, states: ['waiting_user'] }).length, 1);
assert.equal(getAgencyIntention(intention.id, { accountId: 2, companionId }), null, 'cross-account read must fail closed');

console.log(JSON.stringify({ status: 'passed', companionId, intentionId: intention.id, actionId: action.id, feedbackId: feedback.id, root }));
