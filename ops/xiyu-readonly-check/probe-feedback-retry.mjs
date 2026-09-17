// 定位 commitAgencyFeedback 在重读重试后仍返回 invalid 的真实错误
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'xiyu-probe-'));
Object.assign(process.env, { DB_PATH: path.join(dir, 'db.sqlite'), DATA_DIR: dir, LOG_DIR: path.join(dir, 'logs') });

const db = await import('/tmp/xiyu-verify-all/src/db.mjs');
const store = db.getDb();
const companionId = Number(store.prepare('INSERT INTO companions(user_id,bot_id,name) VALUES(NULL,?,?)').run('probe-bot', '探针').lastInsertRowid);
const owner = { accountId: 7701, companionId };

const intention = db.createAgencyIntention({ ...owner, semanticKey: 'probe', desiredChange: 'probe', basisRefs: ['fixture'], state: 'candidate', domain: 'mixed' });
console.log('创建 intention version =', intention.version, 'state =', intention.state);

const preparing = db.updateAgencyIntention(intention.id, { ...owner, expectedVersion: intention.version, state: 'preparing' });
console.log('preparing 后 version =', preparing.version, 'state =', preparing.state);

const first = db.commitAgencyFeedback({
  ...owner, intentionId: intention.id, expectedVersion: intention.version,
  feedback: { sourceMessageId: 'probe-msg-1', kind: 'topic_shift', rawRef: 'x', interpretation: 'y', confidence: 1 },
  update: { state: 'active', lastFeedbackAt: new Date().toISOString() },
});
console.log('第一次(过期版本) →', JSON.stringify(first));

const fresh = db.getAgencyIntention(intention.id, owner);
console.log('重读 version =', fresh.version, 'state =', fresh.state);

const retried = db.commitAgencyFeedback({
  ...owner, intentionId: intention.id, expectedVersion: fresh.version,
  feedback: { sourceMessageId: 'probe-msg-1', kind: 'topic_shift', rawRef: 'x', interpretation: 'y', confidence: 1 },
  update: { state: 'active', lastFeedbackAt: new Date().toISOString() },
});
console.log('第二次(最新版本) →', JSON.stringify(retried));

// 换一个更保守的 nextState 再试，判断是不是状态机不接受 preparing→active
const fresh2 = db.getAgencyIntention(intention.id, owner);
const retried2 = db.commitAgencyFeedback({
  ...owner, intentionId: intention.id, expectedVersion: fresh2.version,
  feedback: { sourceMessageId: 'probe-msg-2', kind: 'topic_shift', rawRef: 'x2', interpretation: 'y2', confidence: 1 },
  update: { state: 'candidate', lastFeedbackAt: new Date().toISOString() },
});
console.log('第三次(改成 candidate) →', JSON.stringify(retried2));

store.close();
