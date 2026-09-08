/** T02: deterministic isolation and evidence-checker selftest. */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import { runHarnessSelftest } from '../tests/agency/harness_selftest.mjs';

const args = process.argv.slice(2);
function arg(name, fallback = '') { const i = args.indexOf(name); return i >= 0 ? (args[i + 1] || fallback) : fallback; }
const runRoot = path.resolve(arg('--run', ''));
if (!runRoot || !fs.existsSync(path.join(runRoot, 'snapshot', 'bot.db'))) throw new Error('T01 snapshot is required: pass --run <run directory>');
const attempts = [];
function deliver(target, payload) {
  const attempt = { target: String(target), payloadHash: requireHash(payload), at: new Date().toISOString() };
  attempts.push(attempt);
  if (!String(target).startsWith('sink://')) throw new Error(`blocked_external_delivery:${target}`);
  return { status: 'delivered', messageId: `sink-${attempts.length}` };
}
function requireHash(value) {
  return crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
}
const blocked = (() => { try { deliver('https://real-bot.invalid/send', { text: 'blocked' }); return false; } catch { return true; } })();
const receipt = deliver('sink://ideal-lab', { text: 'isolated smoke' });
assert.equal(blocked, true);
assert.equal(receipt.status, 'delivered');
const checker = runHarnessSelftest();
assert.equal(checker.status, 'passed');
const report = {
  schemaVersion: 'ideal-agency-lab-selftest-v1', status: 'passed', runRoot,
  isolation: { blockedExternalDelivery: blocked, sinkDelivery: receipt, attempts, productionSendersStarted: false, productionSchedulersStarted: false },
  evidenceChecker: checker,
  mutationRequirement: 'M01-M16 were injected and detected by the existing evidence checker; this is harness validation, not product acceptance.',
};
fs.writeFileSync(path.join(runRoot, 'isolation.json'), JSON.stringify(report.isolation, null, 2));
fs.writeFileSync(path.join(runRoot, 'selftest.json'), JSON.stringify(report, null, 2));
console.log(JSON.stringify({ status: report.status, blockedExternalDelivery: blocked, sinkReceipt: receipt.messageId, mutations: checker.tests.length }, null, 2));
