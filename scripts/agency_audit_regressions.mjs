/** Re-run existing checks with isolated runtime paths; does not score acceptance. */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import Database from 'better-sqlite3';
const root = process.cwd();
const out = path.join(root, 'docs/validation/2026-09-08/conformance-audit/regressions');
fs.mkdirSync(out, { recursive: true });
const names = ['agency_state_smoke', 'agency_protocol_smoke', 'agency_cycle_smoke', 'agency_no_response_smoke', 'initiative_smoke', 'initiative_integration_smoke', 'enterprise_context_smoke', 'enterprise_proactive_smoke', 'check_enterprise_continuity', 'check_enterprise_routing', 'check_enterprise_closed_loop', 'check_deferred_work_task', 'proactive_deadman_smoke', 'proactive_heartbeat_smoke', 'proactive_dedup_smoke', 'conflict_redline_guard', 'life_state_smoke', 'inbound_dedup_smoke'];
const selected = process.argv.slice(2);
const indexPath = path.join(out, 'index.json');
const results = selected.length && fs.existsSync(indexPath) ? JSON.parse(fs.readFileSync(indexPath, 'utf8')).results : [];
for (const name of names.filter(x => !selected.length || selected.includes(x))) {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'xiyu-audit-regression-'));
  const seed = new Database(path.join(temp, 'bot.db'));
  seed.pragma('user_version = 1'); seed.close();
  const script = `scripts/${name}.mjs`;
  const start = Date.now();
  const result = await new Promise(resolve => {
    const child = spawn(process.execPath, [script], { cwd: root, env: { ...process.env,
      DB_PATH: path.join(temp, 'bot.db'), LOG_DIR: path.join(temp, 'logs'), DATA_DIR: temp,
      XIYU_WORKBENCH_CONTEXT_URL: '', XIYU_WORKBENCH_CONTEXT_ENABLED: 'true',
      XIYU_WORKBENCH_OUTBOX_PATH: path.join(temp, 'outbox.json'),
      XIYU_WORKBENCH_ACTIVE_TASKS_PATH: path.join(temp, 'tasks.json'),
    }, windowsHide: true });
    let output = ''; let timedOut = false;
    child.stdout.on('data', chunk => { output += chunk; });
    child.stderr.on('data', chunk => { output += chunk; });
    const timer = setTimeout(() => { timedOut = true; child.kill(); }, 60000);
    child.on('error', error => { clearTimeout(timer); resolve({ script, error: error.message }); });
    child.on('close', code => { clearTimeout(timer); const log = `${name}-${start}.log`; fs.writeFileSync(path.join(out, log), output); resolve({ script, code, timedOut, elapsedMs: Date.now() - start, log }); });
  });
  results.push(result); console.log(JSON.stringify(result));
  fs.writeFileSync(path.join(out, 'index.json'), JSON.stringify({ kind: 'existing-checks-not-release', at: new Date().toISOString(), results }, null, 2));
}
const latestResults = [...new Map(results.map(x => [x.script, x])).values()];
process.exitCode = latestResults.some(x => x.code !== 0) ? 1 : 0;
