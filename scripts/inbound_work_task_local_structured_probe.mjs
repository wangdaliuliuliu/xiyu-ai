import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const OLD_ROOT = 'E:\\Yuanqu-Operations-Workbench\\weekly-ops-entry';
const OLD_ENV_PATH = path.join(OLD_ROOT, 'backend', '.env');
const TARGET_PATH = path.join(OLD_ROOT, 'data', 'feishu-target.json');
const PROFILE_PATH = path.join(OLD_ROOT, 'data', 'strategy-project-profile.json');
const ACCESS_PATH = fs.existsSync(path.join(OLD_ROOT, 'data', 'xiyu-enterprise-access.json'))
  ? path.join(OLD_ROOT, 'data', 'xiyu-enterprise-access.json')
  : path.join(OLD_ROOT, 'data', 'xiyu-enterprise-access.example.json');
const SERVER_PATH = path.join(REPO_ROOT, 'workbench', 'backend', 'feishu-sync-server.mjs');
const READ_ENV_KEYS = ['FEISHU_APP_ID', 'FEISHU_APP_SECRET', 'FEISHU_SPREADSHEET_TOKEN', 'FEISHU_SOURCE_SPREADSHEET_TOKEN', 'FEISHU_API_BASE'];
const TEST_ACTOR = 'replace-with-xiyu-account-id';

function parseEnvFile(filePath) {
  const values = {};
  for (const line of fs.readFileSync(filePath, 'utf8').split(/\r?\n/)) {
    const match = line.match(/^\s*(?:export\s+)?([A-Z0-9_]+)\s*=\s*(.*?)\s*$/);
    if (!match) continue;
    values[match[1]] = match[2].replace(/^['"]|['"]$/g, '');
  }
  return values;
}

function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }

async function freePort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  return port;
}

async function requestJson(baseUrl, pathname, options = {}) {
  const response = await fetch(`${baseUrl}${pathname}`, { ...options, headers: { ...(options.headers || {}), ...(options.body ? { 'content-type': 'application/json' } : {}) } });
  const text = await response.text();
  const data = (() => { try { return JSON.parse(text); } catch { return { raw: text.slice(0, 500) }; } })();
  return { status: response.status, data };
}

async function runM3Probe(baseUrl) {
  const scriptPath = path.join(REPO_ROOT, 'scripts', 'inbound_work_task_m3_live.mjs');
  return await new Promise(resolve => {
    const child = spawn(process.execPath, [scriptPath], {
      cwd: REPO_ROOT,
      env: { ...process.env, XIYU_WORKBENCH_CONTEXT_URL: baseUrl, XIYU_WORKBENCH_CONTEXT_TOKEN: '', XIYU_M3_ACTOR_ID: TEST_ACTOR, PROVIDER_RETRY_MAX: '0' },
      stdio: ['ignore', 'pipe', 'ignore'],
      windowsHide: true,
    });
    let stdout = '';
    child.stdout.on('data', chunk => { stdout += String(chunk); });
    child.once('error', error => resolve({ status: 'blocked', reason: `M3 probe process error: ${error.message}`, providerCalls: 0 }));
    child.once('exit', code => {
      const lines = stdout.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
      for (let index = lines.length - 1; index >= 0; index -= 1) {
        try { return resolve(JSON.parse(lines[index])); } catch { /* ignore non-JSON provider logs */ }
      }
      resolve({ status: 'blocked', reason: `M3 probe returned no JSON result (exit ${code})`, providerCalls: 0 });
    });
  });
}

function recentCompleteDates(now = new Date(), count = 3) {
  const shanghaiToday = new Date(now.getTime() + 8 * 3600000).toISOString().slice(0, 10);
  return Array.from({ length: count }, (_, index) => new Date(Date.parse(`${shanghaiToday}T00:00:00Z`) - (count - index) * 86400000).toISOString().slice(0, 10));
}

function summarizeStructured(response, expectedDates, expectedVenueId) {
  const context = response?.data?.context || null;
  const lookup = context?.sourceLookup || null;
  const items = Array.isArray(context?.items) ? context.items : [];
  const daily = Array.isArray(lookup?.daily) ? lookup.daily : [];
  const dates = daily.map(row => row.date).filter(Boolean);
  const groundedDates = daily.filter(row => Object.values(row.core || {}).some(value => Number.isFinite(Number(value))) && (row.sources || []).some(source => source?.url)).map(row => row.date);
  const refs = items.flatMap(item => Array.isArray(item.refs) ? item.refs : []).filter(ref => ref && ref.url);
  const sourceUrls = [...new Set([
    ...(Array.isArray(lookup?.sourceUrl) ? lookup.sourceUrl : []),
    ...daily.flatMap(row => (row.sources || []).map(source => source.url).filter(Boolean)),
    ...refs.map(ref => ref.url),
  ])];
  const venue = lookup?.venue || items.find(item => item.scope?.venue)?.scope?.venue || '';
  const hasNumericFacts = daily.every(row => Object.values(row.core || {}).some(value => Number.isFinite(Number(value))));
  const structuredResponseObserved = Boolean(
    response?.status === 200 &&
    context?.schemaVersion === 'enterpriseContext-v3' &&
    lookup &&
    ['complete', 'partial'].includes(lookup.status) &&
    venue &&
    expectedVenueId &&
    daily.length === expectedDates.length &&
    expectedDates.every(date => dates.includes(date)) &&
    groundedDates.length === expectedDates.length &&
    hasNumericFacts &&
    items.length >= expectedDates.length &&
    items.every(item => Array.isArray(item.refs) && item.refs.some(ref => ref?.url)) &&
    sourceUrls.length > 0
  );
  return {
    structuredResponseObserved,
    httpStatus: response?.status || 0,
    schemaVersion: context?.schemaVersion || '',
    sourceStatus: lookup?.status || null,
    venue: venue || null,
    dates,
    completeNaturalDates: groundedDates,
    items: items.length,
    sourceUrls,
    daily: daily.map(row => ({ date: row.date, status: row.status, core: row.core || {}, sourceCount: (row.sources || []).length })),
    missingInformation: context?.missingInformation || [],
  };
}

async function main() {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'xiyu-structured-'));
  const runtimeDir = path.join(tempRoot, 'runtime-state');
  fs.mkdirSync(runtimeDir, { recursive: true });
  const envValues = parseEnvFile(OLD_ENV_PATH);
  const missingBindings = READ_ENV_KEYS.filter(key => key !== 'FEISHU_API_BASE' && !envValues[key]);
  if (!fs.existsSync(TARGET_PATH) || !fs.existsSync(PROFILE_PATH) || !fs.existsSync(ACCESS_PATH) || missingBindings.length) {
    fs.rmSync(tempRoot, { recursive: true, force: true });
    console.log(JSON.stringify({ ok: false, milestone: 'M2', status: 'blocked', reason: 'required_readonly_binding_missing', missingBindings, targetExists: fs.existsSync(TARGET_PATH), profileExists: fs.existsSync(PROFILE_PATH), accessExists: fs.existsSync(ACCESS_PATH), codePath: SERVER_PATH }));
    return;
  }
  const port = await freePort();
  const childEnv = {
    PATH: process.env.PATH,
    SystemRoot: process.env.SystemRoot,
    ComSpec: process.env.ComSpec,
    WEEKLY_OPS_HOST: '127.0.0.1',
    WEEKLY_OPS_PORT: String(port),
    WEEKLY_OPS_TARGET_PATH: TARGET_PATH,
    STRATEGY_PROFILE_PATH: PROFILE_PATH,
    XIYU_ACCESS_PATH: ACCESS_PATH,
    WEEKLY_OPS_RUNTIME_STATE_DIR: runtimeDir,
    WEEKLY_OPS_SETTINGS_PATH: path.join(runtimeDir, 'settings.json'),
    XIYU_AUDIT_PATH: path.join(runtimeDir, 'xiyu-knowledge-audit.jsonl'),
    XIYU_CONTEXT_TOKEN: '',
  };
  for (const key of READ_ENV_KEYS) if (envValues[key]) childEnv[key] = envValues[key];
  const child = spawn(process.execPath, [SERVER_PATH], { cwd: REPO_ROOT, env: childEnv, stdio: ['ignore', 'pipe', 'ignore'], windowsHide: true });
  const baseUrl = `http://127.0.0.1:${port}`;
  let health = null;
  try {
    for (let attempt = 0; attempt < 40; attempt += 1) {
      try { health = await requestJson(baseUrl, '/health'); if (health.status === 200) break; } catch { /* wait for listen */ }
      await sleep(250);
    }
    if (health?.status !== 200) throw new Error('temporary structured workbench did not become healthy');
    const catalog = await requestJson(baseUrl, '/api/knowledge/catalog');
    const catalogData = catalog.data?.catalog || {};
    const venue = (catalogData.venues || []).find(item => item.name === '中影' || item.id === 'ZHONGYING');
    const projectId = catalogData.project?.id || 'yuanqu-vr';
    const venueId = venue?.id || 'ZHONGYING';
    const dates = recentCompleteDates();
    const task = {
      goal: '了解中影近期经营表现',
      completeQuestion: '请结合中影最近三个完整自然日的真实资料说明经营表现',
      scope: { projectId, venueIds: [venueId], venueNames: [venue?.name || '中影'] },
      timeSpec: { kind: 'recent_complete_days', count: 3 },
      requestedOutcome: { kind: 'performance_summary', businessMeaning: '判断近期经营表现' },
      metricIds: ['box_office_total', 'sales_order_count', 'venue_traffic', 'reach_count', 'conversion_count'],
      missingSlots: [],
    };
    const retrieve = await requestJson(baseUrl, '/api/knowledge/retrieve', { method: 'POST', body: JSON.stringify({ actorId: TEST_ACTOR, projectId, scope: task.scope, task, query: { interactionIntent: 'lookup', task }, limits: { maxItems: 12, maxCharacters: 8000 } }) });
    const structured = summarizeStructured(retrieve, dates, venueId);
    const result = { ok: structured.structuredResponseObserved, milestone: 'M2', status: structured.structuredResponseObserved ? 'passed' : 'blocked', mode: 'target_repo_temp_structured', serverCodePath: SERVER_PATH, port, pid: child.pid, boundResources: { targetPath: TARGET_PATH, strategyProfilePath: PROFILE_PATH, accessPath: ACCESS_PATH, accessUsesExample: ACCESS_PATH.endsWith('xiyu-enterprise-access.example.json') }, health: health.data, catalog: { status: catalog.status, projectId, venueId, venueName: venue?.name || null }, requestedDates: dates, structured, writeCalls: 0, productionWrites: 0, botMessagesSent: 0 };
    if (!structured.structuredResponseObserved) result.reason = 'structured_response_not_grounded_complete';
    console.log(JSON.stringify(result));
    if (structured.structuredResponseObserved && process.env.XIYU_RUN_M3 === 'true') {
      const m3 = await runM3Probe(baseUrl);
      console.log(JSON.stringify({
        ...m3,
        localStructuredService: { codePath: SERVER_PATH, port, pid: child.pid, endpoint: baseUrl, targetPath: TARGET_PATH, strategyProfilePath: PROFILE_PATH, accessPath: ACCESS_PATH },
        structuredResponseObserved: true,
        temporaryRuntimeOnly: true,
        productionWrites: 0,
        botMessagesSent: 0,
      }));
      process.exitCode = m3.status === 'passed' ? 0 : 2;
    } else process.exitCode = structured.structuredResponseObserved ? 0 : 2;
  } catch (error) {
    console.log(JSON.stringify({ ok: false, milestone: 'M2', status: 'blocked', reason: error.message, serverCodePath: SERVER_PATH, port, pid: child.pid, writeCalls: 0, productionWrites: 0, botMessagesSent: 0 }));
    process.exitCode = 2;
  } finally {
    if (!child.killed) child.kill('SIGTERM');
    await Promise.race([new Promise(resolve => child.once('exit', resolve)), sleep(3000)]);
    if (!child.killed) child.kill('SIGKILL');
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
}

await main();
