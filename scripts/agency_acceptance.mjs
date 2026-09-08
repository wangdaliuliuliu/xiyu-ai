/** v2 runner. Missing evidence cannot report release success. */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { runHarnessSelftest } from '../tests/agency/harness_selftest.mjs';
import { aggregateRelease } from '../tests/agency/acceptance_contract.mjs';
const opts = {};
for (let i = 2; i < process.argv.length; i++) {
  const m = process.argv[i].match(/^--([a-z-]+)(?:=(.*))?$/);
  if (!m) throw new Error('invalid argument');
  const value = m[2] ?? process.argv[++i];
  if (!value || value.startsWith('--')) throw new Error(`missing --${m[1]}`);
  opts[m[1]] = value;
}
const suites = ['harness-selftest', 'l0', 'smoke', 'fixed', 'regression', 'holdout', 'integration'];
if (!opts['release-manifest'] && !opts.replay && !suites.includes(opts.suite)) throw new Error('valid --suite is required');
const out = path.resolve(opts.out || `docs/validation/2026-09-08/agency-v2/${Date.now()}-${opts.suite || 'release'}`);
if (fs.existsSync(path.join(out, 'manifest.json'))) throw new Error('evidence already exists; use a new --out');
fs.mkdirSync(out, { recursive: true });
const hash = f => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');
const manifest = { version: 'agency-acceptance-v2', startedAt: new Date().toISOString(), command: process.argv.slice(2), suite: opts.suite, hashes: { developmentSpec: hash('docs/agency-development-plan-v2-2026-09-08.md'), acceptanceSpec: hash('docs/agency-validation-plan-v2-2026-09-08.md'), runner: hash('scripts/agency_acceptance.mjs') } };
let result;
if (opts.suite === 'harness-selftest') result = runHarnessSelftest();
else if (opts.suite === 'l0') {
  const node = process.execPath;
  const commands = [
    [node, ['--test', 'tests/agency/enterprise_result.test.mjs']],
    [node, ['--test', 'tests/agency/state_budget.test.mjs']],
    [node, ['--test', 'tests/agency/runtime_cycle.test.mjs']],
    [node, ['--test', 'tests/agency/action_execution.test.mjs']],
    [node, ['scripts/agency_cycle_smoke.mjs']],
    [node, ['scripts/agency_no_response_smoke.mjs']],
    [node, ['scripts/agency_state_smoke.mjs']],
    [node, ['scripts/import_smoke.mjs']],
    [node, ['scripts/check_deferred_work_task.mjs']],
    [node, ['scripts/photo_shot_route_smoke.mjs']],
    [node, ['scripts/agency_conformance_audit.mjs']],
    [node, ['node_modules/eslint/bin/eslint.js', 'src', 'scripts', 'index.mjs']],
  ];
  const runs = commands.map(([file, args]) => {
    const r = spawnSync(file, args, { cwd: process.cwd(), encoding: 'utf8', timeout: 120000, windowsHide: true });
    return { command: [file, ...args], status: r.status === 0 ? 'passed' : 'failed', exitCode: r.status, stdout: String(r.stdout || '').slice(-12000), stderr: String(r.stderr || '').slice(-12000) };
  });
  result = { status: runs.every(r => r.status === 'passed') ? 'passed' : 'failed', kind: 'l0-deterministic-and-static', runs, releaseGate: 'not-release-acceptance', limitations: ['No real model dialogue quality score', 'No 24-family multi-round suite, second model, media, human review, or production delivery'] };
}
else if (opts['release-manifest']) {
  const input = JSON.parse(fs.readFileSync(opts['release-manifest'], 'utf8'));
  result = { ...aggregateRelease(input.gates || {}), status: Object.values(input.gates || {}).some(g => g.status === 'failed') ? 'failed' : 'inconclusive', reason: 'referenced_run_verification_pending' };
} else result = { status: 'inconclusive', reason: 'suite_implementation_pending', suite: opts.suite, releaseGate: 'blocked' };
fs.writeFileSync(path.join(out, 'manifest.json'), JSON.stringify(manifest, null, 2));
fs.writeFileSync(path.join(out, 'issues.json'), JSON.stringify(result, null, 2));
fs.writeFileSync(path.join(out, 'report.md'), `# ${opts.suite || 'release'}\n\nStatus: ${result.status}\n\n${result.reason || result.kind}\n\nNot a full release acceptance.\n`);
console.log(JSON.stringify({ ...result, output: out }, null, 2));
process.exitCode = result.status === 'passed' ? 0 : 1;
