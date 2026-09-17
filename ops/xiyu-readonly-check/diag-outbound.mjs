import Database from "better-sqlite3";
const db = new Database("/opt/xiyu-ai/data/bot.db", { readonly: true });
console.log("== 最近真实出站（direction=out）==");
for (const r of db.prepare("SELECT id, msg_type, substr(COALESCE(content,''),1,34) AS txt, created_at FROM wechat_messages WHERE direction='out' ORDER BY created_at DESC LIMIT 10").all()) {
  console.log("  ", r.created_at, "|", String(r.msg_type||'').padEnd(8), "|", r.txt);
}
console.log();
console.log("== 最近排程 JSON（看 deliveryOutcome 字段）==");
for (const r of db.prepare("SELECT date_key, schedule_json, updated_at FROM proactive_runtime_schedules ORDER BY updated_at DESC LIMIT 3").all()) {
  console.log("--- ", r.date_key, "updated", r.updated_at);
  let j = null; try { j = JSON.parse(r.schedule_json); } catch (e) { console.log("  解析失败:", e.message); continue; }
  const slots = Array.isArray(j) ? j : (j.slots || []);
  for (const s of slots.slice(0, 12)) {
    console.log("   slot", s.slot ?? s.minute ?? "?", "sent=" + s.sent, "outcome=" + (s.deliveryOutcome ?? "-"), "at=" + (s.deliveryAt ?? "-"), "err=" + (s.deliveryError ?? "-"), "kind=" + (s.kind ?? "-"));
  }
}
db.close();