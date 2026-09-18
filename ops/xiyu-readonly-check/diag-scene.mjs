import Database from "better-sqlite3";
const db = new Database("/opt/xiyu-ai/data/bot.db", { readonly: true });
console.log("== companion_sleep_schedule（作息表）==");
for (const r of db.prepare("SELECT * FROM companion_sleep_schedule WHERE companion_id=1").all()) console.log(JSON.stringify(r, null, 1));
console.log();
console.log("== companion_daily_schedule 最近 3 天 ==");
for (const r of db.prepare("SELECT * FROM companion_daily_schedule WHERE companion_id=1 ORDER BY rowid DESC LIMIT 3").all()) {
  console.log("--- date:", r.date_key ?? r.schedule_date ?? "(?)");
  const raw = r.schedule_json ?? r.schedule ?? "";
  let j; try { j = JSON.parse(raw); } catch { console.log("   raw:", String(raw).slice(0,200)); continue; }
  const items = Array.isArray(j) ? j : (j.items || j.activities || []);
  for (const it of items) console.log("   ", JSON.stringify(it).slice(0, 120));
}
db.close();