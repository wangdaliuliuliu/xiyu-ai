// Read-only diagnosis. Does not import db.mjs (which runs migrations), send, or update settings.
import 'dotenv/config';
import Database from 'better-sqlite3';
import fs from 'node:fs';
const db = new Database(process.env.DB_PATH || 'data/bot.db', { readonly: true });
try {
  const tableNames = db.prepare("SELECT name FROM sqlite_master WHERE type='table'").all().map(r=>r.name);
  const columns = db.prepare('PRAGMA table_info(companions)').all().map(r=>r.name);
  const selected = ['id','name','occupation','relationship_stage','proactive_enabled','proactive_intensity','proactive_unanswered','sticker_reply_enabled','photo_enabled','voice_enabled','personality','core_desire','motivation','last_user_reply_at','last_proactive_reply_at'].filter(c=>columns.includes(c));
  const report = {
    at: new Date().toISOString(),
    env: Object.fromEntries(['PROACTIVE_ENGINE','XIYU_ENTERPRISE_PROACTIVE_ENABLED','XIYU_WORKBENCH_CONTEXT_ENABLED','PROACTIVE_UNANSWERED_LIMIT'].map(k=>[k,process.env[k] || '(default)'])),
    effectiveProactiveEngine: process.env.PROACTIVE_ENGINE || 'v2',
    policies: db.prepare('SELECT account_id,companion_id,enabled,report_enabled,knowledge_enabled,report_mode,knowledge_cooldown_hours,last_report_check_at,last_knowledge_check_at,last_report_sent_at,last_knowledge_sent_at,updated_at FROM enterprise_proactive_policies').all(),
    companions: db.prepare(`SELECT ${selected.join(',')} FROM companions`).all(),
    tables: tableNames.filter(t=>/proactive|emotion|open_loop|schedule|intention|desire|goal/.test(t)),
    schema: Object.fromEntries(['companion_open_loops','proactive_schedules','daily_schedules','companion_daily_schedules'].filter(t=>tableNames.includes(t)).map(t=>[t,db.prepare(`PRAGMA table_info(${t})`).all().map(c=>c.name)])),
  };
  const logPath = 'E:/FoxSpirit/data/routing-20260906-xiyu.out.log';
  report.morningTrace = fs.existsSync(logPath) ? fs.readFileSync(logPath,'utf8').split(/\r?\n/).filter(line => /醒这么早干嘛|我同事真的好烦|刚看到个好好笑|Sticker manifest not found|2026-09-05T23:26.*(?:fallback exitSleep|urgent morning)/.test(line)) : [];
  console.log(JSON.stringify(report,null,2));
} finally { db.close(); }
