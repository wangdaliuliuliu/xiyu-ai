/** Real provider + real same-host workbench bridge through an SSH tunnel.
 * Isolated SQLite, probe mode, no writeback and no outbound delivery.
 */
import 'dotenv/config';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import Database from 'better-sqlite3';
const sourcePath = process.env.DB_PATH || path.resolve('data/bot.db');
const source = new Database(sourcePath, { readonly: true });
for (const key of ['CHAT_PROVIDER', 'CHAT_MODEL', 'DEEPSEEK_API_KEY', 'OPENAI_API_KEY', 'OPENAI_BASE_URL', 'CUSTOM_API_KEY', 'CUSTOM_BASE_URL', 'CUSTOM_MODEL']) {
  if (!process.env[key]) { const row = source.prepare('SELECT value FROM app_settings WHERE key=?').get(key); if (row?.value) process.env[key] = row.value; }
}
source.close();
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'xiyu-live-entry-'));
// dotenv 可能带入本地 4174 旧端口；该探针验证的是生产同机桥接，默认固定 4175，
// 仍允许用 AGENCY_PROBE_WORKBENCH_URL 显式覆盖，避免把旧 .env 当成生产拓扑。
const probeWorkbenchUrl = process.env.AGENCY_PROBE_WORKBENCH_URL || 'http://127.0.0.1:4175';
Object.assign(process.env, { DB_PATH: path.join(dir, 'bot.db'), DATA_DIR: dir, LOG_DIR: path.join(dir, 'logs'), XIYU_WORKBENCH_CONTEXT_URL: probeWorkbenchUrl, XIYU_WORKBENCH_CONTEXT_TOKEN: process.env.XIYU_WORKBENCH_CONTEXT_TOKEN || 'synthetic-test-only', XIYU_WORKBENCH_CONTEXT_ENABLED: 'true', XIYU_AGENCY_MODE: 'legacy' });
const { getDb, getCompanionById, patchCompanion, saveDailySchedule, shanghaiDateKey } = await import('../src/db.mjs');
const { playgroundChat } = await import('../src/playground.mjs');
const { withAiAudit } = await import('../src/ai.mjs');
const { getActiveChatProvider } = await import('../src/providers/chat.mjs');
const db = getDb();
const id = Number(db.prepare('INSERT INTO companions(user_id,bot_id,name) VALUES(NULL,?,?)').run('live-entry-probe', '溪语').lastInsertRowid);
patchCompanion(id, { age: 24, role_title: '专业又亲近的经营助理', current_scene: '办公室', relationship_stage: '暧昧', affection_level: 60, memory_enabled: 0, max_tokens: 700, temperature: 0.25, persona_prompt: '你是一个专业、自然、对用户有偏爱的成年经营助理。明确工作问题要先认真交付，再保留自然的人格。' });
saveDailySchedule(id, shanghaiDateKey(), [{ time: '09:00', activity: '在办公室处理资料' }, { time: '23:00', activity: '回家休息' }], '平静');
const trace = [];
const result = await withAiAudit(event => trace.push(event), () => playgroundChat(getCompanionById(id), '9月2号东坝店销售额是多少？', { probe: true, accountId: 9001 }));
const out = path.resolve(`docs/validation/2026-09-08/agency-v2/${Date.now()}-live-entry`);
fs.mkdirSync(out, { recursive: true });
fs.writeFileSync(path.join(out, 'result.json'), JSON.stringify({ kind: 'real-provider-real-workbench-isolated-entry', provider: getActiveChatProvider(), result, trace, limitations: ['SSH tunnel to same-host 4175', 'isolated DB and probe mode', 'no writeback, web auth, WeChat, or delivery acceptance'] }, null, 2));
console.log(JSON.stringify({ output: out, reply: result.reply, enterprise: result.enterprise, provider: getActiveChatProvider(), providerCalls: trace.filter(x => x.stage === 'provider_request').length }, null, 2));
db.close();
