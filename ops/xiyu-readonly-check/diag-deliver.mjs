import Database from "better-sqlite3";
const db = new Database("/opt/xiyu-ai/data/bot.db", { readonly: true });
const cst = (iso) => iso ? new Date(Date.parse(String(iso).replace(" ","T") + (String(iso).includes("Z")?"":"Z")) + 8*3600000).toISOString().replace("T"," ").slice(0,16) : "-";
console.log("== agi_mtsbnojz 的 3 条 delivered 动作，到底真发了几条？==");
for (const id of ["aga_mtsbnqhg_f64d464ad17cbb","aga_mtskhf2x_28012964e406cd","aga_mtsvhg2e_7db78a7ecebf3b"]) {
  const a = db.prepare("SELECT * FROM agency_actions WHERE id=?").get(id);
  const mids = JSON.parse(a.provider_message_ids_json || "[]");
  console.log("---", id);
  console.log("    state:", a.state, "| created", cst(a.created_at), "| updated", cst(a.updated_at));
  console.log("    providerMessageIds:", JSON.stringify(mids));
  for (const m of mids) {
    const row = db.prepare("SELECT created_at, direction, msg_type, substr(COALESCE(content,''),1,30) AS t FROM wechat_messages WHERE msg_id=?").get(m);
    console.log("      msg", m, row ? `→ ${cst(row.created_at)} ${row.direction} ${row.t}` : "→ 库里查不到");
  }
}
console.log();
console.log("== 最近 3 天所有真实出站，标注是否属于仪式 ==");
for (const r of db.prepare("SELECT created_at, msg_type, substr(COALESCE(content,''),1,40) AS t FROM wechat_messages WHERE direction='out' ORDER BY created_at DESC LIMIT 12").all()) {
  console.log("  ", cst(r.created_at), String(r.msg_type).padEnd(6), r.t);
}
db.close();