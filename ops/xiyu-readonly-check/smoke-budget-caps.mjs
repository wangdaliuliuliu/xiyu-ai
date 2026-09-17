// ============================================================
//  预算部署后隔离冒烟
//
//  在临时 DB 上验证部署后的 src/db.mjs 真的生效了新上限。
//  独立进程；DB_PATH/DATA_DIR/LOG_DIR 由调用方指向临时目录。
//  **不接触生产数据库。**
// ============================================================

// 注意：本文件可能被放到 /tmp 下执行，因此**不能用相对路径** import。
// 必须导入生产正在运行的模块，才能证明「部署后的代码真的生效了」。
const db = await import('/opt/xiyu-ai/src/db.mjs');
const caps = db.getAgencyBudgetCaps();
console.log('CAPS=' + JSON.stringify(caps));

const store = db.getDb();
const companionId = Number(
  store.prepare('INSERT INTO companions(user_id,bot_id,name) VALUES(NULL,?,?)')
       .run('smoke', '冒烟').lastInsertRowid
);
const owner = { accountId: 9001, companionId };

// 用极小的预留值，专门验证「次数上限」
let reserved = 0;
for (let i = 0; i < caps.attempts; i++) {
  if (db.reserveAgencyBudget({ ...owner, purpose: 'appraise', inputTokens: 100, outputTokens: 100, attempts: 1, now: 86400000 + i })) reserved++;
}
const overflow = db.reserveAgencyBudget({ ...owner, purpose: 'appraise', inputTokens: 100, outputTokens: 100, attempts: 1, now: 86400000 + caps.attempts });

console.log('RESERVED=' + reserved);
console.log('OVERFLOW_BLOCKED=' + (overflow === null ? 'yes' : 'no'));

// 顺带验证 token 上限也真的在挡
const store2 = db.getDb();
let tokenReserved = 0;
for (let i = 0; i < 20; i++) {
  if (db.reserveAgencyBudget({ ...owner, purpose: 'plan', inputTokens: 10000, outputTokens: 0, attempts: 1, now: 172800000 + i })) tokenReserved++;
}
console.log('TOKEN_RESERVED=' + tokenReserved);

store2.close();

const pass = caps.attempts === 16 && caps.tokens === 96000 && reserved === 16 && overflow === null && tokenReserved === 9;
console.log('SMOKE=' + (pass ? 'PASS' : 'FAIL'));
process.exit(pass ? 0 : 1);
