import Database from "better-sqlite3";
const db = new Database("/opt/xiyu-ai/data/bot.db", { readonly: true });
console.log("wechat_messages 列:", db.prepare("PRAGMA table_info(wechat_messages)").all().map(c=>c.name).join(", "));
console.log("schedules 列    :", db.prepare("PRAGMA table_info(proactive_runtime_schedules)").all().map(c=>c.name).join(", "));
db.close();