import Database from "better-sqlite3";
const db = new Database("/opt/xiyu-ai/data/bot.db", { readonly: true });
console.log("== 6 条每日仪式的动作明细 ==");
const intents = db.prepare(`SELECT id, state, last_contact_at, reconsider_after, expires_at, semantic_key,
  substr(desired_change,1,34) AS txt FROM agency_intentions
  WHERE state NOT IN ('completed','abandoned','expired') ORDER BY created_at`).all();
for (const it of intents) {
  const acts = db.prepare(`SELECT id, state, action_type, needs_user_input, not_before, expires_at,
    ROUND((julianday('now')-julianday(created_at))*24,1) AS age_h
    FROM agency_actions WHERE intention_id=? ORDER BY created_at`).all(it.id);
  console.log("---", it.id, "|", it.state, "| last_contact:", it.last_contact_at, "| reconsider:", it.reconsider_after);
  console.log("   ", it.txt);
  console.log("    semantic:", it.semantic_key);
  for (const a of acts) console.log(`    act ${a.id} ${String(a.state).padEnd(10)} ${String(a.action_type).padEnd(13)} needUser=${a.needs_user_input} age=${a.age_h}h expires=${a.expires_at}`);
  if (!acts.length) console.log("    (无动作)");
}
db.close();