import Database from "better-sqlite3";
const db = new Database("/opt/xiyu-ai/data/bot.db", { readonly: true });
console.log(db.prepare("PRAGMA table_info(agency_actions)").all().map(c=>c.name).join(", "));
console.log("---intentions---");
console.log(db.prepare("PRAGMA table_info(agency_intentions)").all().map(c=>c.name).join(", "));