import Database from 'better-sqlite3';
const db = new Database(process.env.XIYU_TEST_DB);
const lib = await import('/opt/xiyu-ai/src/initiative.mjs');
console.log('INTENTION_LIFETIME 常量:', JSON.stringify(lib.INTENTION_LIFETIME));
console.log();
const rows = db.prepare("SELECT * FROM agency_intentions").all();
console.log('全部动念（含终态）分类：');
for (const r of rows) {
  const c = lib.classifyIntentionLifetime(r);
  console.log(`  ${String(r.id).padEnd(30)} ${String(r.state).padEnd(13)} ${c.type.padEnd(20)} ${c.reason}`);
  console.log(`      ${String(r.desired_change).slice(0, 60)}`);
}
db.close();
