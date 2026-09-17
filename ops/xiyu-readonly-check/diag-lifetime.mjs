import Database from "better-sqlite3";
import * as lib from "/opt/xiyu-ai/src/initiative.mjs";

const db = new Database("/opt/xiyu-ai/data/bot.db", { readonly: true });
const now = Date.now();
const rows = db.prepare(
  "SELECT * FROM agency_intentions WHERE state NOT IN ('completed','abandoned','expired')"
).all();

for (const r of rows) {
  const cls = lib.classifyIntentionLifetime(r);
  const dl  = lib.intentionShelfDeadline(r);
  const ex  = lib.isIntentionExpired(r, { nowMs: now });
  const ageH = ((now - Date.parse(r.created_at)) / 3600000).toFixed(1);
  console.log("---");
  console.log("id      :", r.id);
  console.log("state   :", r.state, "| age", ageH + "h");
  console.log("text    :", String(r.desired_change).replace(/\s+/g, " ").slice(0, 90));
  console.log("class   :", JSON.stringify(cls));
  console.log("deadline:", dl, "=> expired?", ex);
}