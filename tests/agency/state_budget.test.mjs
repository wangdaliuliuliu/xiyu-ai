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

test('cognition cooldown reports WHICH gate blocked it', () => {
  // 2026-09-18 生产：日志只有 `status=cooldown`，看不出是三道否决里的哪一道，
  // 排查时只能猜。这里锁住"每道否决都必须给出可辨识原因"。
  //
  // 时间线设计（踩过三次坑后写清楚）：
  //   ① 租约只有 90 秒有效期，而本测试要跨越分钟级时间点。直接用几步之外的
  //      时间戳去调，会先撞 lease_invalid，走不到要验的那道闸。
  //   ② `acquireAgencyLease` 的守卫是 `lease_until <= now`。它比较的是库里存的
  //      **绝对**到期时间（上一次 acquire 时的 now + 90s），而不是"我们刚把
  //      时钟拨过去了"。所以时间旅行前必须**显式释放**上一份租约（把
  //      lease_until 置 0），否则第二次 acquire 直接返回 null。
  //   ③ 每次 acquire 都会把 last_cognition_at 写回该次的 now，步与步之间留
  //      31 分钟，既保证硬间隔越过，又不至于让上一步的语义被覆盖。
  const cooldownOwner = { accountId: 7002, companionId };
  const t0 = 5_000_000;
  const t1 = t0 + 60_000;          // 1 分钟后：仍受 30 分钟硬间隔约束
  const t2 = t0 + 31 * 60_000;     // 31 分钟后：硬间隔已过
  const t4 = t2 + 31 * 60_000;     // 再 31 分钟：用于验证来源变化

  let prevLease = null;
  const leaseAt = (nowMs, tag) => {
    if (prevLease) {
      db.releaseAgencyLease({ ...cooldownOwner, token: prevLease.lease_token, fencing: Number(prevLease.fencing) });
      prevLease = null;
    }
    const lease = db.acquireAgencyLease({ ...cooldownOwner, now: nowMs, token: `cog-${tag}` });
    assert.ok(lease, `应在 t=${nowMs} 取得租约`);
    prevLease = lease;
    return lease;
  };
  const call = (nowMs, lease, over = {}) => db.beginAgencyCognition({
    ...cooldownOwner, token: lease.lease_token, fencing: Number(lease.fencing), now: nowMs, ...over,
  });

  // 租约无效（不存在的 token）
  assert.equal(
    db.beginAgencyCognition({ ...cooldownOwner, token: 'bogus', fencing: 1, now: t0 }).reason,
    'lease_invalid'
  );

  // 首次可以开始 → 写回 last_cognition_at = t0
  const l0 = leaseAt(t0, 'first');
  assert.deepEqual(call(t0, l0, { sourceVersion: 'v1' }), { started: true, reason: 'started' });

  // 同来源、1 分钟后 → 撞 30 分钟硬间隔，原因要说明还剩多少分钟
  const l1 = leaseAt(t1, 'gap');
  const gap = call(t1, l1, { sourceVersion: 'v1' });
  assert.equal(gap.started, false);
  assert.match(gap.reason, /^cognition_gap_\d+min_left$/, `实际原因 ${gap.reason}`);

  // 同来源、31 分钟后（硬间隔已过），但 reconsiderAfter 未到 → 原因带出该时刻
  const l2 = leaseAt(t2, 'recons');
  const recons = call(t2, l2, {
    sourceVersion: 'v1',
    reconsiderAfter: new Date(t2 + 30 * 60_000).toISOString(),
  });
  assert.equal(recons.started, false);
  assert.match(recons.reason, /^reconsider_after_/, `实际原因 ${recons.reason}`);

  // 来源变了 → 可以提前触发（新事实不该被陪伴节流吞掉）
  const l4 = leaseAt(t4, 'changed');
  const changed = call(t4, l4, { sourceVersion: 'v2' });
  assert.equal(changed.started, true, `来源版本变化应能提前触发认知（实际 ${changed.reason}）`);

  if (prevLease) db.releaseAgencyLease({ ...cooldownOwner, token: prevLease.lease_token, fencing: Number(prevLease.fencing) });
});

test('budget reserves attempts before provider work and stops at the daily cap', () => {
  // 2026-09-14：日上限由硬编码 8/24000 改为可配置的 16/96000。
  // 生产实测单次 appraise 就要 5242~10209 token，旧上限一天只够想一次。
  const caps = db.getAgencyBudgetCaps();
  assert.equal(caps.attempts, Number(process.env.XIYU_AGENCY_DAILY_ATTEMPT_CAP) || 16);
  assert.equal(caps.tokens, Number(process.env.XIYU_AGENCY_DAILY_TOKEN_CAP) || 96000);
  const cap = caps.attempts;
  const reservations = Array.from({ length: cap }, (_, i) => db.reserveAgencyBudget({ ...owner, purpose: 'appraise', inputTokens: 100, outputTokens: 100, attempts: 1, now: 86400000 + i }));
  assert.ok(reservations.every(Boolean), `前 ${cap} 次预留都应成功`);
  assert.equal(db.reserveAgencyBudget({ ...owner, purpose: 'appraise', inputTokens: 100, outputTokens: 100, attempts: 1, now: 86400000 + cap }), null);
  const settled = db.settleAgencyBudget({ ...owner, id: reservations[0].id, usage: null });
  assert.equal(settled.usageKnown, false);
  assert.equal(settled.tokens, 200);
});

test('budget refuses a reservation that would exceed the token cap', () => {
  // 另一天，专门验证 token 上限（而不是次数上限）能挡住超额预留。
  // 旧实现的预留值远小于真实用量，上限形同虚设；本测试锁住「预留必须能挡住」。
  const caps = db.getAgencyBudgetCaps();
  const day = 2 * 86400000;
  const each = 10000;
  const maxReservations = Math.floor(caps.tokens / each);
  const ok = Array.from({ length: maxReservations }, (_, i) => db.reserveAgencyBudget({ ...owner, purpose: 'plan', inputTokens: each, outputTokens: 0, attempts: 1, now: day + i }));
  assert.ok(ok.every(Boolean), `前 ${maxReservations} 次预留都应成功`);
  assert.equal(db.reserveAgencyBudget({ ...owner, purpose: 'plan', inputTokens: each, outputTokens: 0, attempts: 1, now: day + maxReservations }), null);
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

// 2026-09-14 回归：反馈落库失败的两个真实成因，各自锁一条断言。
//
// 生产症状：同一动念上一条用户消息先 committed、紧接着连刷 status=invalid
// （2026-09-14 出现 6 次以上），表现为"她记不住用户的反应"。
// 排查出两个独立成因：
//   (1) 版本冲突：调用方读到的 version 到提交时已过期 → 可重试。
//   (2) 非法状态转移：动念处于 preparing（正在取数）时模型常给 nextState=active，
//       而 `preparing → active` 不在转移表内 → 重试无用，整条反馈被丢弃。
test('stale-version feedback succeeds after re-reading the intention', () => {
  const intention = makeIntention('retry-after-conflict');
  const preparing = db.updateAgencyIntention(intention.id, { ...owner, expectedVersion: intention.version, state: 'preparing' });
  // 第一次提交：用过期版本 → 应返回可重试的 conflict_retry
  const conflicted = db.commitAgencyFeedback({
    ...owner,
    intentionId: intention.id,
    expectedVersion: intention.version,      // 故意用过期的 version
    feedback: { sourceMessageId: 'retry-msg-1', kind: 'topic_shift', rawRef: '换个话题', interpretation: '话题转移', confidence: 1 },
    update: { state: 'ready', lastFeedbackAt: new Date().toISOString() },   // ready 是 preparing 的合法目标
  });
  assert.equal(conflicted.status, 'conflict_retry', '过期版本必须回 conflict_retry 而不是 invalid');

  // 模拟修复后的调用方：重读最新版本再试一次
  const fresh = db.getAgencyIntention(intention.id, owner);
  assert.ok(fresh, '动念仍应存在');
  assert.equal(fresh.version, preparing.version, '重读应拿到最新版本');
  const retried = db.commitAgencyFeedback({
    ...owner,
    intentionId: intention.id,
    expectedVersion: fresh.version,          // 用最新 version
    feedback: { sourceMessageId: 'retry-msg-1', kind: 'topic_shift', rawRef: '换个话题', interpretation: '话题转移', confidence: 1 },
    update: { state: 'ready', lastFeedbackAt: new Date().toISOString() },
  });
  assert.equal(retried.status, 'committed', '重读后重试应当成功');
  assert.equal(retried.intention.state, 'ready');
});

test('illegal nextState is clamped instead of losing the whole feedback', () => {
  // 复现生产场景：动念在 preparing，模型给 active（非法转移）。
  // 修复前：整条反馈被丢弃 → status=invalid。
  // 修复后：状态收敛到合法目标，反馈本身必须落库。
  const intention = makeIntention('clamp-illegal-transition');
  db.updateAgencyIntention(intention.id, { ...owner, expectedVersion: intention.version, state: 'preparing' });
  const current = db.getAgencyIntention(intention.id, owner);
  assert.equal(current.state, 'preparing');

  const committed = db.commitAgencyFeedback({
    ...owner,
    intentionId: intention.id,
    expectedVersion: current.version,
    feedback: { sourceMessageId: 'clamp-msg-1', kind: 'answer', rawRef: '回答了', interpretation: '用户给了回答', confidence: 1 },
    update: { state: 'active', lastFeedbackAt: new Date().toISOString() },   // preparing → active 非法
  });
  assert.equal(committed.status, 'committed', '非法 nextState 不应导致整条反馈丢失');
  assert.notEqual(committed.intention.state, 'active', '不得写入非法状态');
  assert.ok(['suspended', 'ready', 'preparing'].includes(committed.intention.state),
    `应收敛到合法目标，实际 ${committed.intention.state}`);
  // 反馈记录本身必须真的落库（这才是"她记住用户反应"的依据）
  // 注意：parseAgencyFeedback 返回原始行，字段名是 snake_case。
  const list = db.listAgencyFeedback({ ...owner, intentionId: intention.id, limit: 5 });
  assert.ok(list.some(f => f.source_message_id === 'clamp-msg-1'), '反馈记录必须已持久化');
  assert.ok(list.some(f => f.kind === 'answer'), '反馈类型应正确保存');
});

// 2026-09-18 回归：动念收尾必须**同时作废它的未完成动作**。
//
// 生产事故：一条动念停在 ready，它派生的动作 9-15 13:10 就过期了，但动作
// 过期不终结动念 → 动念每小时被重新选中、重新生成、撞在同一条出站复核上
// （9-17 一天撞 3 次），还把当晚 22:08 的晚安拦掉（agency_blocked）。
// 只收动念或只收动作都会留下这个缺口，所以这里锁住"两者一起"。
test('retiring an intention cancels its unfinished actions in one transaction', () => {
  const intention = makeIntention('retire-with-actions');
  const ready = db.updateAgencyIntention(intention.id, { ...owner, expectedVersion: intention.version, state: 'ready' });
  const planned = db.createAgencyAction({
    ...owner, intentionId: intention.id, actionType: 'contact_text',
    dedupKey: 'retire-action-planned', state: 'planned',
  });
  assert.ok(planned, '应能创建 planned 动作');

  const result = db.retireAgencyIntention(intention.id, {
    ...owner, state: 'expired', reason: 'test_shelf_life_expired',
  });
  assert.ok(result, '收尾应返回结果');
  assert.equal(result.alreadyTerminal, false);
  assert.equal(result.intention.state, 'expired', '动念应被收尾为 expired');
  assert.ok(result.cancelledActions.includes(planned.id), '其未完成动作应被一并作废');

  // 动作确实落到 cancelled，不再出现在"未完成"集合里
  const stillOpen = db.listAgencyActions({ ...owner, intentionId: intention.id, states: ['planned', 'running', 'prepared', 'sending'] });
  assert.equal(stillOpen.length, 0, '收尾后不该再有未完成动作（否则仍会卡住后续发送）');

  // 幂等：再收一次不报错、也不重复计
  const again = db.retireAgencyIntention(intention.id, { ...owner, state: 'expired', reason: 'again' });
  assert.equal(again.alreadyTerminal, true, '已终态的动念再收一次应标记 alreadyTerminal');
  assert.equal(again.cancelledActions.length, 0);

  // 只接受合法的收尾状态，非法状态不得写库
  const another = makeIntention('retire-invalid-state');
  assert.equal(db.retireAgencyIntention(another.id, { ...owner, state: 'ready' }), null, 'ready 不是合法收尾状态，应拒绝');
  assert.equal(db.getAgencyIntention(another.id, owner).state, 'candidate', '被拒绝后动念状态不得变化');
});

test.after(() => store.close());
