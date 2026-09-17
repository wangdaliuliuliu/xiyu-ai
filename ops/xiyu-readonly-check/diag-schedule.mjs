import Database from "better-sqlite3";
const db = new Database("/opt/xiyu-ai/data/bot.db", { readonly: true });
const s = db.prepare("SELECT date_key, schedule_json FROM proactive_runtime_schedules ORDER BY updated_at DESC LIMIT 1").get();
const j = JSON.parse(s.schedule_json);
console.log("date:", j.dateKey, "target:", j.targetCount);
const cst = (iso) => iso ? new Date(Date.parse(iso) + 8*3600000).toISOString().slice(11,16) : "-";
let ok=0, bad=0, none=0;
for (const it of j.items) {
  const o = it.deliveryOutcome ?? "(无记录)";
  if (o === "delivered") ok++; else if (o === "(无记录)") none++; else bad++;
  console.log(`  ${String(Math.floor(it.minute/60)).padStart(2,"0")}:${String(it.minute%60).padStart(2,"0")} CST  ${String(it.kind).padEnd(8)} sent=${String(it.sent).padEnd(5)} ${String(o).padEnd(14)} ${cst(it.deliveryAt)} ${it.deliveryError ?? ""}`);
}
console.log(`\n  合计: 送达 ${ok} / 尝试失败 ${bad} / 无记录 ${none}`);
db.close();