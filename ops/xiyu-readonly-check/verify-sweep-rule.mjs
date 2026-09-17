// 隔离验证：收尾扫描是否真的会收掉那条订单表动念？
// 只读副本库，不碰生产。
import Database from 'better-sqlite3';

const DB = process.env.XIYU_TEST_DB;
const db = new Database(DB);
const lib = await import('/opt/xiyu-ai/src/initiative.mjs');

const before = db.prepare(
  "SELECT id, state FROM agency_intentions WHERE state NOT IN ('completed','abandoned','expired')"
).all();
console.log('扫描前非终态动念:', before.length, '条');

const rows = db.prepare(
  "SELECT * FROM agency_intentions WHERE state NOT IN ('completed','abandoned','expired') ORDER BY updated_at DESC"
).all();
const now = Date.now();
let hit = 0;
for (const it of rows) {
  const v = lib.judgeIntentionRetirement(it, { nowMs: now });
  if (!v.retire) continue;
  hit++;
  console.log('  应收尾 →', it.id, it.state, '=>', v.retire, `(${v.reason})`);
  db.prepare(
    "UPDATE agency_intentions SET state = ?, version = version + 1, next_review_condition = ?, updated_at = ? WHERE id = ?"
  ).run(v.retire, v.reason, new Date(now).toISOString(), it.id);
  const cancelled = db.prepare(
    "UPDATE agency_actions SET state = 'cancelled', updated_at = ? WHERE intention_id = ? AND state IN ('planned','running','prepared','sending')"
  ).run(new Date(now).toISOString(), it.id).changes;
  console.log('     同时作废未完成动作', cancelled, '个');
}
console.log('命中收尾:', hit, '条');

// 注意：必须在全部 UPDATE 之后再查 `after`。
// 早先写成了先查 after 再 UPDATE，等于拿旧数据复核——脚本自己骗自己，
// 报出"每日仪式保留 0 条"的假警报（实际是被上一次运行改过的副本库）。
const after = db.prepare(
  "SELECT * FROM agency_intentions WHERE state NOT IN ('completed','abandoned','expired')"
).all();
console.log('扫描后非终态动念:', after.length, '条');

// 复核：不变量 I3 现在应为 0
const stillExpired = after.filter(r => lib.isIntentionExpired(r, { nowMs: now }));
console.log('I3 复核（残留过期动念）:', stillExpired.length, '条', stillExpired.length ? '❌ 未修好' : '✅ 已修好');
// 防误杀：每日仪式必须还在
const rituals = after.filter(r => lib.classifyIntentionLifetime(r).type === 'recurring_ritual');
console.log('每日仪式保留:', rituals.length, '条（应 > 0，证明没有误杀）');
for (const r of rituals) console.log('   保留:', r.id, r.state, String(r.desired_change).slice(0, 40));
db.close();
