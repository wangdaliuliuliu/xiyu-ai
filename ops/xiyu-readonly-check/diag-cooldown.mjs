import Database from "better-sqlite3";
const db = new Database("/opt/xiyu-ai/data/bot.db", { readonly: true });
console.log("== agency_runtime 原始值 ==");
for (const r of db.prepare("SELECT * FROM agency_runtime").all()) console.log(JSON.stringify(r, null, 1));
console.log();
console.log("== 字段类型 ==");
console.log(db.prepare("PRAGMA table_info(agency_runtime)").all().map(c=>`${c.name}:${c.type}`).join(", "));
db.close();