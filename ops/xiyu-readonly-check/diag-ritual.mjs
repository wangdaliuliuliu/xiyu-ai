import Database from "better-sqlite3";
const db = new Database("/opt/xiyu-ai/data/bot.db", { readonly: true });
const rows = db.prepare(`
  SELECT id, state, semantic_key, last_contact_at, last_feedback_at,
         ROUND((julianday('now')-julianday(updated_at))*24,1) AS stale_h,
         substr(desired_change,1,38) AS txt
  FROM agency_intentions WHERE state IN ('preparing','ready','active')
  ORDER BY updated_at DESC
`).all();
console.log("== 非终态动念（收尾闸扫描面）==");
for (const r of rows) {
  const acts = db.prepare(`
    SELECT id, state, action_type, needs_user_input,
           ROUND((julianday('now')-julianday(created_at))*24,1) AS age_h
    FROM agency_actions WHERE intention_id = ? ORDER BY created_at DESC LIMIT 3
  `).all(r.id);
  console.log("---");
  console.log("id:", r.id, "| state", r.state, "| stale", r.stale_h + "h");
  console.log("   semantic:", String(r.semantic_key || "(none)").slice(0, 55));
  console.log("   lastContact:", r.last_contact_at, "| lastFeedback:", r.last_feedback_at);
  console.log("   text:", r.txt);
  for (const a of acts) console.log("   act:", a.id, a.state, a.action_type, "needsUserInput=" + a.needs_user_input, a.age_h + "h");
}