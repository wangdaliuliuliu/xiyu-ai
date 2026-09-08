/**
 * T01: read-only discovery and isolated snapshot for the ideal agency lab.
 * This script never writes the source database, source workbench state, or a
 * delivery credential. It creates a scrubbed, writable copy under --out.
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import Database from 'better-sqlite3';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const workbenchRoot = path.resolve(process.env.LAB_WORKBENCH_ROOT || 'E:/Yuanqu-Operations-Workbench/weekly-ops-entry');
const sourceDbPath = path.resolve(process.env.LAB_SOURCE_DB || path.join(repoRoot, 'data', 'bot.db'));
const args = process.argv.slice(2);
function arg(name, fallback = '') { const i = args.indexOf(name); return i >= 0 ? (args[i + 1] || fallback) : fallback; }
const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z');
const outRoot = path.resolve(arg('--out', path.join(repoRoot, 'experiments', 'ideal-agency-lab', 'runs', stamp)));
const snapshotRoot = path.join(outRoot, 'snapshot');
const snapshotDbPath = path.join(snapshotRoot, 'bot.db');
fs.mkdirSync(snapshotRoot, { recursive: true });

function sha256(file) {
  const hash = crypto.createHash('sha256');
  hash.update(fs.readFileSync(file));
  return hash.digest('hex');
}
function exists(file) { try { return fs.existsSync(file); } catch { return false; } }
function safeReadJson(file) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return null; }
}
function redacted(value, key = '') {
  if (/(token|secret|password|api.?key|authorization|cookie|session|private)/i.test(key)) return '[REDACTED]';
  if (Array.isArray(value)) return value.map(item => redacted(item, key));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, redacted(v, k)]));
  return value;
}
function copyJsonTree(sourceDir, destDir) {
  if (!exists(sourceDir)) return { copied: [], missing: [sourceDir] };
  const copied = [], missing = [];
  function visit(src, dst) {
    for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
      const source = path.join(src, entry.name);
      const target = path.join(dst, entry.name);
      if (entry.isDirectory()) { fs.mkdirSync(target, { recursive: true }); visit(source, target); continue; }
      if (!entry.name.endsWith('.json') && !entry.name.endsWith('.jsonl')) continue;
      if (/(\.env|credential|secret|password|token)/i.test(entry.name)) { missing.push({ file: source, reason: 'credential_named_file' }); continue; }
      fs.mkdirSync(path.dirname(target), { recursive: true });
      if (entry.name.endsWith('.json')) {
        const parsed = safeReadJson(source);
        if (parsed !== null) fs.writeFileSync(target, JSON.stringify(redacted(parsed), null, 2));
        else fs.copyFileSync(source, target);
      } else fs.copyFileSync(source, target);
      copied.push({ source, target, sha256: sha256(source), bytes: fs.statSync(source).size });
    }
  }
  visit(sourceDir, destDir);
  return { copied, missing };
}
function sourceSchema(db) {
  const tableRows = db.prepare("SELECT name, type, sql FROM sqlite_master WHERE type IN ('table','view') ORDER BY name").all();
  return tableRows.map(row => {
    let count = null;
    try { count = db.prepare(`SELECT count(*) AS count FROM "${String(row.name).replaceAll('"', '""')}"`).get().count; } catch { /* count stays null for an unreadable object */ }
    const columns = db.prepare(`PRAGMA table_info("${String(row.name).replaceAll('"', '""')}")`).all().map(c => ({ name: c.name, type: c.type, notnull: c.notnull, pk: c.pk }));
    return { name: row.name, type: row.type, count, columns, schemaSha256: crypto.createHash('sha256').update(String(row.sql || '')).digest('hex') };
  });
}
function settingInventory(db) {
  return db.prepare('SELECT key, value_type, secret, updated_at FROM app_settings ORDER BY key').all().map(row => ({
    key: row.key, valueType: row.value_type, secret: Boolean(row.secret), updatedAt: row.updated_at,
    configured: Boolean(db.prepare('SELECT 1 AS ok FROM app_settings WHERE key=? AND value IS NOT NULL AND length(value)>0').get(row.key)),
  }));
}
function rowInventory(db) {
  const tableNames = new Set(db.prepare("SELECT name FROM sqlite_master WHERE type='table'").all().map(x => x.name));
  const wanted = ['users', 'user_accounts', 'user_profiles', 'companions', 'companion_memories', 'companion_conversation_turns', 'companion_open_loops', 'companion_current_works', 'companion_daily_schedule', 'companion_daily_thoughts', 'companion_diary', 'companion_emotion_state', 'companion_life_state', 'companion_preferences', 'companion_photo_log', 'companion_proactive_material_log', 'companion_sleep_schedule', 'companion_relational_diary', 'companion_reminders', 'enterprise_proactive_policies', 'proactive_runtime_schedules', 'proactive_schedules', 'agency_intentions', 'agency_actions', 'agency_feedback', 'agency_runtime', 'wechat_messages', 'photo_request_audit'];
  const out = {};
  for (const table of wanted) if (tableNames.has(table)) {
    const count = db.prepare(`SELECT count(*) AS count FROM "${table}"`).get().count;
    out[table] = { count, nonEmpty: count > 0 };
  }
  const companion = tableNames.has('companions') ? db.prepare('SELECT id,name,age,role_title,relationship_stage,affection_level,proactive_enabled,proactive_frequency,proactive_time_window,proactive_intensity,proactive_daily_target,proactive_unanswered,current_scene,persona_prompt FROM companions ORDER BY id LIMIT 1').get() : null;
  if (companion) out.primaryCompanion = { ...companion, personaPromptSha256: crypto.createHash('sha256').update(String(companion.persona_prompt || '')).digest('hex'), persona_prompt: undefined };
  return out;
}
function gitRevision() {
  try { return execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repoRoot, encoding: 'utf8' }).trim(); } catch { return null; }
}

if (!exists(sourceDbPath)) throw new Error(`source db not found: ${sourceDbPath}`);
if (!exists(workbenchRoot)) throw new Error(`workbench root not found: ${workbenchRoot}`);

const source = new Database(sourceDbPath, { readonly: true, fileMustExist: true });
const inventory = {
  schemaVersion: 'ideal-agency-lab-inventory-v1',
  createdAt: new Date().toISOString(),
  source: { repoRoot, sourceDbPath, sourceDbSha256: sha256(sourceDbPath), gitRevision: gitRevision(), timezone: 'Asia/Shanghai' },
  workbench: { root: workbenchRoot, profile: path.join(workbenchRoot, 'data', 'strategy-project-profile.json'), runtimeState: path.join(workbenchRoot, 'data', 'runtime-state') },
  tables: sourceSchema(source),
  settings: settingInventory(source),
  records: rowInventory(source),
  resources: [],
  exclusions: [
    { resource: 'chat/provider secrets', status: 'present_in_source_not_copied', reason: 'loaded only into process environment for the real API smoke; never placed in snapshot' },
    { resource: 'real Bot tokens and sessions', status: 'present_in_source_scrubbed_in_replica', reason: 'delivery is sink-only and must not be executable' },
  ],
};
const replicaConnection = new Database(snapshotDbPath);
source.backup(replicaConnection);
source.close();
replicaConnection.close();
const replica = new Database(snapshotDbPath);
for (const sql of [
  "DELETE FROM app_settings WHERE secret=1",
  "UPDATE wechat_accounts SET bot_token='', login_session_id=''",
  "DELETE FROM ilink_context_tokens",
  "DELETE FROM pending_bind_sessions",
]) { try { replica.exec(sql); } catch { /* table may be absent in a future schema */ } }
replica.pragma('journal_mode = DELETE');
replica.close();
inventory.replica = { path: snapshotDbPath, sha256: sha256(snapshotDbPath), scrubbed: true };

const workbenchData = path.join(workbenchRoot, 'data');
const copied = copyJsonTree(workbenchData, path.join(snapshotRoot, 'workbench-data'));
inventory.resources.push(...copied.copied.map(item => ({ type: 'workbench_json', ...item })));
inventory.exclusions.push(...copied.missing.map(item => ({ ...item, status: 'unavailable' })));
for (const relative of ['src/proactive.mjs', 'src/agency_protocol.mjs', 'src/enterprise_context.mjs', 'src/companion.mjs', 'src/db.mjs', 'src/photo_planner.mjs', 'config/agency-prompts.v1.json', 'docs/agency-ideal-lab-experiment-spec-2026-09-08.md']) {
  const file = path.join(repoRoot, relative);
  inventory.resources.push(exists(file) ? { type: 'source_file', file, relative, sha256: sha256(file), bytes: fs.statSync(file).size } : { type: 'source_file', file, relative, status: 'unavailable' });
}
fs.writeFileSync(path.join(outRoot, 'inventory.json'), JSON.stringify(inventory, null, 2));
fs.writeFileSync(path.join(outRoot, 'replica-safety.json'), JSON.stringify({
  schemaVersion: 'replica-safety-v1', snapshotDb: snapshotDbPath, productionWritable: false, realDeliveryEnabled: false,
  scrubbedTables: ['app_settings(secret=1)', 'wechat_accounts.bot_token', 'wechat_accounts.login_session_id', 'ilink_context_tokens', 'pending_bind_sessions'],
  allowedOutbound: ['configured model provider only'], blockedOutbound: ['WeChat/iLink', 'email', 'production workbench write APIs'],
}, null, 2));
console.log(JSON.stringify({ status: 'passed', outRoot, sourceDbSha256: inventory.source.sourceDbSha256, replicaDbSha256: inventory.replica.sha256, tables: inventory.tables.length, workbenchJsonFiles: copied.copied.length, missingResources: copied.missing.length }, null, 2));
