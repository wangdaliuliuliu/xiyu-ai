/** Real API diagnostic via the existing playgroundChat entry, not release acceptance.
 * Reads only provider configuration from the existing local database. All persona,
 * memory, facts, state, usage and enterprise HTTP traffic are synthetic/isolated.
 * No WeChat, writeback, or scheduler is started. Run explicitly with --live.
 */
import 'dotenv/config';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import Database from 'better-sqlite3';

if (!process.argv.includes('--live')) throw new Error('Use --live to authorize diagnostic API calls');
const root = process.cwd();
const originalDb = process.env.DB_PATH || path.join(root, 'data/bot.db');
// Provider config only; no production chat, persona, business data, or binding copy.
const source = new Database(originalDb, { readonly: true });
for (const key of ['CHAT_PROVIDER', 'CHAT_MODEL', 'DEEPSEEK_API_KEY', 'OPENAI_API_KEY', 'OPENAI_BASE_URL', 'CUSTOM_API_KEY', 'CUSTOM_BASE_URL', 'CUSTOM_MODEL']) {
  if (!process.env[key]) {
    const row = source.prepare('SELECT value FROM app_settings WHERE key = ?').get(key);
    if (row?.value) process.env[key] = row.value;
  }
}
source.close();
const isolated = fs.mkdtempSync(path.join(os.tmpdir(), 'xiyu-entry-audit-'));
Object.assign(process.env, {
  DB_PATH: path.join(isolated, 'bot.db'), DATA_DIR: isolated, LOG_DIR: path.join(isolated, 'logs'),
  XIYU_WORKBENCH_OUTBOX_PATH: path.join(isolated, 'outbox.json'),
  XIYU_WORKBENCH_ACTIVE_TASKS_PATH: path.join(isolated, 'tasks.json'),
  XIYU_WORKBENCH_CONTEXT_TOKEN: 'synthetic-test-only', XIYU_WORKBENCH_CONTEXT_ENABLED: 'true',
  XIYU_AGENCY_MODE: 'enabled',
});
let scenario;
const requests = [];
const record = (amount, id) => ({ id, assetType: 'metric_record', epistemicStatus: 'confirmed_operating_fact', title: '合成销售表', summary: { venue: '东大店', periodStart: '2026-09-02', periodEnd: '2026-09-02', sourceTitle: id, core: { box_office_total: amount } } });
const server = http.createServer(async (req, res) => {
  let body = ''; for await (const chunk of req) body += chunk;
  requests.push({ case: scenario?.id, method: req.method, path: req.url, body: body ? JSON.parse(body) : null });
  if (scenario?.mode === '404') { res.writeHead(404, { 'content-type': 'text/html' }); return res.end('<html>synthetic edge 404</html>'); }
  res.setHeader('content-type', 'application/json');
  if (req.url === '/api/knowledge/catalog') return res.end(JSON.stringify({ ok: true, catalog: { project: { id: 'audit-project', name: '合成企业' }, venues: [{ id: 'DONGDA', name: '东大店' }], capabilities: ['sales', 'traffic'], nodes: [] } }));
  if (req.url === '/api/knowledge/retrieve') return res.end(JSON.stringify({ ok: true, context: { items: scenario?.mode === 'conflict' ? [record(12000, '合成表A'), record(15000, '合成表B')] : [record(12000, '合成销售表')], boundaries: ['合成测试资料，不代表企业真实数据'], missingInformation: [] } }));
  res.writeHead(405); res.end(JSON.stringify({ error: 'No writeback allowed' }));
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
process.env.XIYU_WORKBENCH_CONTEXT_URL = `http://127.0.0.1:${server.address().port}`;
const { getDb, getCompanionById, patchCompanion, saveDailySchedule, shanghaiDateKey } = await import('../src/db.mjs');
const { playgroundChat } = await import('../src/playground.mjs');
const { withAiAudit } = await import('../src/ai.mjs');
const { __resetEnterpriseContextCacheForTest } = await import('../src/enterprise_context.mjs');
const { getActiveChatProvider } = await import('../src/providers/chat.mjs');
const db = getDb();
const cases = [1, 2, 3].map(n => ({ id: `catalog-404-${n}`, mode: '404', message: '这两天销售额怎么样？' })).concat([
  { id: 'known-fact', mode: 'fact', message: '9月2号东大店销售额是多少？' },
  { id: 'conflicting-fact', mode: 'conflict', message: '9月2号东大店销售额是多少？' },
  { id: 'personal', mode: 'fact', message: '今天有点累，先别聊工作，陪我说两句。' },
]);
const report = { at: new Date().toISOString(), kind: 'real-api-entry-diagnostic-not-release', provider: getActiveChatProvider(), isolation: { directory: isolated, entry: 'playgroundChat(probe=true)', wechatUsed: false, productionDataCopied: false }, cases: [], requests };
// getActiveChatProvider is public metadata; explicitly whitelist fields before persistence.
report.provider = { id: report.provider.id, model: report.provider.model, label: report.provider.label };
const out = path.join(root, 'docs/validation/2026-09-08/agency-v2', `${Date.now()}-entry-diagnostic`);
fs.mkdirSync(out, { recursive: true });
try {
  for (scenario of cases) {
    __resetEnterpriseContextCacheForTest();
    const id = Number(db.prepare('INSERT INTO companions (user_id, bot_id, name) VALUES (NULL, ?, ?)').run('entry-audit', '溪语').lastInsertRowid);
    patchCompanion(id, { age: 24, role_title: '研究生兼业务助理', current_scene: '教室', relationship_stage: '暧昧', affection_level: 60, memory_enabled: 0, max_tokens: 500, temperature: 0.2, persona_prompt: '你是一位专业又亲近的成年业务助理，有自己的研究生课程和生活。认真回应对方的请求。' });
    saveDailySchedule(id, shanghaiDateKey(), [{ time: '07:00', activity: '在教室上课' }, { time: '23:00', activity: '回宿舍休息' }], '平静');
    const t0 = Date.now();
    const beforeUsage = db.prepare('SELECT COALESCE(MAX(id),0) AS id FROM ai_usage_events').get().id;
    try {
      const aiTrace = [];
      const result = await withAiAudit(event => aiTrace.push(event), () => playgroundChat(getCompanionById(id), scenario.message, { probe: true, accountId: 9001 }));
      fs.writeFileSync(path.join(out, `${scenario.id}-api-trace.json`), JSON.stringify(aiTrace, null, 2));
      const usage = db.prepare('SELECT provider,model,capability,prompt_tokens,completion_tokens,latency_ms,status FROM ai_usage_events WHERE id > ?').all(beforeUsage);
      report.cases.push({ ...scenario, durationMs: Date.now() - t0, result, usage, assessment: 'requires-evidence-review; no-release-score' });
      console.log(JSON.stringify({ id: scenario.id, reply: result.reply, enterprise: result.enterprise, usage }));
    } catch (error) {
      report.cases.push({ ...scenario, durationMs: Date.now() - t0, error: String(error.message), assessment: 'inconclusive' });
      console.log(JSON.stringify({ id: scenario.id, error: String(error.message) }));
    }
    fs.writeFileSync(path.join(out, 'entry-api.json'), JSON.stringify(report, null, 2));
  }
} finally {
  report.limitations = ['Synthetic persona and tool facts; not a production-user replay', 'Probe skips sleep/memory writes/postProcess/delivery; no continuity acceptance claim', 'Provider trace captured through production ai.mjs; diagnostic still bypasses HTTP auth and delivery', 'No rubric/judge or pass-rate claims; hard failures already block release'];
  fs.writeFileSync(path.join(out, 'entry-api.json'), JSON.stringify(report, null, 2));
  server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); db.close();
}
