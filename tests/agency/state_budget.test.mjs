import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'xiyu-agency-state-'));
Object.assign(process.env, { DB_PATH: path.join(dir, 'db.sqlite'), DATA_DIR: dir, LOG_DIR: path.join(dir, 'logs') });
const db = await import('../../src/db.mjs');
const store = db.getDb();
const companionId = Number(store.prepare('INSERT INTO companions(user_id,bot_id,name) VALUES(NULL,?,?,?)'.replace(',?,?,?', ',?,?')).run('state-test', '状态测试').lastInsertRowid);
const owner = { accountId: 7001, companionId };
const makeIntention = (key, state = 'candidate') => db.createAgencyIntention({ ...owner, semanticKey: key, desiredChange: key, basisRefs: ['fixture'], state, domain: 'mixed' });

test('owner-scoped lease fences concurrent cognition', () => {
  const first = db.acquireAgencyLease({ ...owner, now: 1000, token: 'first' });
  assert.ok(first);
  assert.equal(db.acquireAgencyLease({ ...owner, now: 1001, token: 'second' }), null);
  assert.equal(db.agencyLeaseValid({ ...owner, token: 'first', fencing: first.fencing, now: 1002 }), true);
  assert.equal(db.releaseAgencyLease({ ...owner, token: 'first', fencing: first.fencing }), true);
  const second = db.acquireAgencyLease({ ...owner, now: 1003, token: 'second' });
  assert.ok(second);
  assert.ok(second.fencing > first.fencing);
});

test('budget reserves attempts before provider work and stops at eight', () => {
  const reservations = Array.from({ length: 8 }, (_, i) => db.reserveAgencyBudget({ ...owner, purpose: 'appraise', inputTokens: 100, outputTokens: 100, attempts: 1, now: 86400000 + i }));
  assert.ok(reservations.every(Boolean));
  assert.equal(db.reserveAgencyBudget({ ...owner, purpose: 'appraise', inputTokens: 100, outputTokens: 100, attempts: 1, now: 86400000 + 9 }), null);
  const settled = db.settleAgencyBudget({ ...owner, id: reservations[0].id, usage: null });
  assert.equal(settled.usageKnown, false);
  assert.equal(settled.tokens, 200);
});

test('waiting_user needs delivered input and stale CAS cannot overwrite', () => {
  const intention = makeIntention('continuity');
  const preparing = db.updateAgencyIntention(intention.id, { ...owner, expectedVersion: intention.version, state: 'preparing' });
  const ready = db.updateAgencyIntention(intention.id, { ...owner, expectedVersion: preparing.version, state: 'ready' });
  const action = db.createAgencyAction({ ...owner, intentionId: intention.id, dedupKey: 'question', actionType: 'contact_text', needsUserInput: true });
  assert.equal(db.updateAgencyIntention(intention.id, { ...owner, expectedVersion: ready.version, state: 'waiting_user' }), null);
  const sending = db.updateAgencyAction(action.id, { ...owner, expectedVersion: action.version, state: 'sending' });
  const delivered = db.updateAgencyAction(action.id, { ...owner, expectedVersion: sending.version, state: 'delivered', providerMessageIds: ['msg-1'] });
  const waiting = db.updateAgencyIntention(intention.id, { ...owner, expectedVersion: ready.version, state: 'waiting_user' });
  assert.ok(waiting);
  assert.equal(db.updateAgencyIntention(intention.id, { ...owner, expectedVersion: ready.version, state: 'active' }), null);
  assert.equal(db.recordAgencyFeedback({ ...owner, intentionId: intention.id, actionId: action.id, sourceMessageId: 'msg-1', kind: 'no_response_observed' })?.kind, 'no_response_observed');
  assert.equal(db.recordAgencyFeedback({ ...owner, intentionId: intention.id, actionId: action.id, sourceMessageId: 'msg-1', kind: 'no_response_observed' })?.kind, 'no_response_observed');
});

test('feedback and intention transition commit together and deduplicate', () => {
  const intention = makeIntention('feedback-transaction');
  const preparing = db.updateAgencyIntention(intention.id, { ...owner, expectedVersion: intention.version, state: 'preparing' });
  const ready = db.updateAgencyIntention(intention.id, { ...owner, expectedVersion: preparing.version, state: 'ready' });
  const action = db.createAgencyAction({ ...owner, intentionId: intention.id, actionType: 'contact_text', strategySummary: '请求一个可验证回答', needsUserInput: true, dedupKey: 'feedback-action' });
  const sending = db.updateAgencyAction(action.id, { ...owner, expectedVersion: action.version, state: 'sending' });
  const delivered = db.commitAgencyReceipt({
    ...owner,
    intentionId: intention.id,
    actionId: action.id,
    intentionVersion: ready.version,
    actionVersion: sending.version,
    receipt: { state: 'delivered', providerMessageIds: ['feedback-msg'], resultRefs: [{ kind: 'text', delivered: true }] },
  });
  assert.equal(delivered.status, 'committed');
  const committed = db.commitAgencyFeedback({
    ...owner,
    intentionId: intention.id,
    expectedVersion: delivered.intention.version,
    feedback: { actionId: action.id, sourceMessageId: 'user-msg-1', kind: 'answer', rawRef: '已确认', interpretation: '用户给出了回答', confidence: 1 },
    update: { state: 'active', lastFeedbackAt: new Date().toISOString() },
  });
  assert.equal(committed.status, 'committed');
  assert.equal(committed.intention.state, 'active');
  const duplicate = db.commitAgencyFeedback({
    ...owner,
    intentionId: intention.id,
    expectedVersion: delivered.intention.version,
    feedback: { actionId: action.id, sourceMessageId: 'user-msg-1', kind: 'answer', rawRef: '已确认', interpretation: '用户给出了回答', confidence: 1 },
    update: { state: 'active', lastFeedbackAt: new Date().toISOString() },
  });
  assert.equal(duplicate.status, 'duplicate');
  const stale = db.commitAgencyFeedback({
    ...owner,
    intentionId: intention.id,
    expectedVersion: delivered.intention.version,
    feedback: { actionId: action.id, sourceMessageId: 'user-msg-2', kind: 'correction', rawRef: '改一下', interpretation: '修正', confidence: 1 },
    update: { state: 'active', lastFeedbackAt: new Date().toISOString() },
  });
  assert.equal(stale.status, 'conflict_retry');
});

test.after(() => store.close());
