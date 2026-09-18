// 隔离验证：第四层（仪式已送出即完结）在生产库副本上的效果。
// 只读副本，不碰生产。
//
// 必须同时验证三件事：
//   1) 3 条卡住的每日仪式被收掉（它们已投递过、不会再推进）
//   2) **正在等用户回答的那条不能被收**（waiting_user，用户还没答）
//   3) 早安/晚安仍能发（收尾后同内容会建新动念，旧的不再被复用）
import Database from 'better-sqlite3';

const DB = process.env.XIYU_TEST_DB;
// 被验模块的来源必须可指定：隔离验证要验**待部署**的源码，
// 不能import生产正在跑的旧版本（否则验的是旧的、部署的是新的）。
const SRC = process.env.XIYU_SRC || '/opt/xiyu-ai/src';
const db = new Database(DB);
const lib = await import(`${SRC}/initiative.mjs`);
console.log('被验模块:', `${SRC}/initiative.mjs`);

const H = 3600e3;
const now = Date.now();

// 复刻生产侧的投递证据收集逻辑（listAgencyActions + updated_at）
const deliveredByIntention = new Map();
for (const a of db.prepare(
  "SELECT intention_id, state, updated_at, created_at FROM agency_actions WHERE state='delivered'"
).all()) {
  const raw = String(a.updated_at || a.created_at || '');
  const at = Date.parse(raw.replace(' ', 'T') + (raw.includes('Z') ? '' : 'Z'));
  if (!Number.isFinite(at)) continue;
  const k = String(a.intention_id);
  if (!deliveredByIntention.has(k) || deliveredByIntention.get(k) < at) deliveredByIntention.set(k, at);
}
console.log('投递证据条数:', deliveredByIntention.size);
console.log();

const rows = db.prepare(
  "SELECT * FROM agency_intentions WHERE state NOT IN ('completed','abandoned','expired') ORDER BY created_at"
).all();

console.log('== 逐条判定 ==');
let hit = 0;
for (const it of rows) {
  const c = lib.classifyIntentionLifetime(it);
  const v = lib.judgeIntentionRetirement(it, {
    nowMs: now,
    latestDeliveredAtMs: deliveredByIntention.get(String(it.id)) ?? null,
  });
  const dd = deliveredByIntention.get(String(it.id));
  const tag = v.retire ? '收尾 → ' + v.retire : '保留';
  console.log(`  ${String(it.state).padEnd(13)} ${c.type.padEnd(19)} ${tag.padEnd(22)} ${String(it.id).slice(0,26)}`);
  console.log(`      送出过: ${dd ? ((now - dd) / H).toFixed(1) + 'h 前' : '从未'}  | ${String(it.desired_change).slice(0, 40)}`);
  if (!v.retire) continue;
  hit++;
  db.prepare("UPDATE agency_intentions SET state=?, version=version+1, next_review_condition=?, updated_at=? WHERE id=?")
    .run(v.retire, v.reason, new Date(now).toISOString(), it.id);
  db.prepare("UPDATE agency_actions SET state='cancelled', updated_at=? WHERE intention_id=? AND state IN ('planned','running','prepared','sending')")
    .run(new Date(now).toISOString(), it.id);
}
console.log();
console.log('命中收尾:', hit, '条');

// ── 复核（必须在 UPDATE 之后）──────────────────────────────────────────────
const after = db.prepare(
  "SELECT * FROM agency_intentions WHERE state NOT IN ('completed','abandoned','expired')"
).all();
console.log('扫描后非终态动念:', after.length, '条');

const rituals = after.filter(r => lib.classifyIntentionLifetime(r).type === 'recurring_ritual');
console.log('剩余每日仪式:', rituals.length, '条');
for (const r of rituals) console.log('   ', r.id, r.state, String(r.desired_change).slice(0, 36));

// 关键安全断言：等用户回答的那条必须还在
const waiting = after.find(r => String(r.id) === 'agi_mu58m3qj_7eab10feed74ac');
console.log();
console.log('等待用户回答的那条仍在池中:', waiting ? '✅ 是（' + waiting.state + '）' : '❌ 被误杀！');

// 断言：过期的都不在了
const stillExpired = after.filter(r => lib.isIntentionExpired(r, { nowMs: now }));
console.log('残留过期动念:', stillExpired.length, stillExpired.length ? '❌' : '✅');

// 断言：已投递过的仪式都被收掉了
const settledLeft = after.filter(r =>
  lib.classifyIntentionLifetime(r).type === 'recurring_ritual' && deliveredByIntention.has(String(r.id))
);
console.log('残留"已投递过"的仪式:', settledLeft.length, settledLeft.length ? '❌' : '✅');

db.close();
