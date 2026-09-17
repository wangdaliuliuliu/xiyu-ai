import Database from "better-sqlite3";
const db = new Database("/opt/xiyu-ai/data/bot.db", { readonly: true });
console.log("== 用户最后一次发消息 ==");
const r = db.prepare("SELECT created_at FROM wechat_messages WHERE direction='in' ORDER BY created_at DESC LIMIT 3").all();
for (const x of r) console.log("   in:", x.created_at);
const last = r[0]?.created_at;
if (last) {
  const h = (Date.now() - Date.parse(last.replace(" ","T") + "Z")) / 3600000;
  console.log("   距今", h.toFixed(1), "小时  → 24h 微信窗口", h > 24 ? "【已关闭，无法主动发起】" : "仍开着");
}
console.log();
console.log("== 排程 JSON 结构 ==");
const s = db.prepare("SELECT date_key, schedule_json FROM proactive_runtime_schedules ORDER BY updated_at DESC LIMIT 1").get();
console.log("  date:", s.date_key);
console.log("  raw :", String(s.schedule_json).slice(0, 900));
db.close();