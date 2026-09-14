/* Build a release manifest without reading or writing credentials.
 * Usage: node scripts/agency_release_manifest.mjs [--out path]
 */
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { getAgencyPromptBinding } from '../src/agency_protocol.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
const outIndex = args.indexOf('--out');
const outputPath = outIndex >= 0 && args[outIndex + 1] ? path.resolve(args[outIndex + 1]) : '';
const files = [
  'package.json', 'package-lock.json',
  'src/agency_protocol.mjs', 'src/db.mjs', 'src/enterprise_context.mjs',
  'src/initiative.mjs', 'src/proactive.mjs', 'src/bot.mjs',
  'config/agency-prompts.v1.json', 'config/prompts/work-context-router-v1.json',
  'workbench/backend/cognition/source-router.mjs', 'workbench/backend/feishu-sync-server.mjs',
  'deploy/xiyu-ai.service',
];
const hashFile = (relative) => {
  const absolute = path.join(root, relative);
  if (!fs.existsSync(absolute)) return { status: 'missing' };
  return { status: 'present', sha256: crypto.createHash('sha256').update(fs.readFileSync(absolute)).digest('hex'), bytes: fs.statSync(absolute).size };
};
const git = (gitArgs) => { try { return execFileSync('git', gitArgs, { cwd: root, encoding: 'utf8' }).trim(); } catch { return ''; } };
const manifest = {
  schemaVersion: 'xiyu-agency-production-release-manifest',
  createdAt: new Date().toISOString(),
  repositoryRoot: root,
  git: { revision: git(['rev-parse', 'HEAD']), branch: git(['branch', '--show-current']), worktreeStatus: git(['status', '--short']) },
  runtime: { node: process.version, abi: process.versions.modules },
  featureFlag: { name: 'XIYU_AGENCY_MODE', releaseDefault: 'legacy', shadowBeforeEnabled: true },
  prompt: getAgencyPromptBinding(),
  files: Object.fromEntries(files.map(relative => [relative, hashFile(relative)])),
  safety: { credentialsIncluded: false, realBotDelivery: false, productionDatabaseMutation: false },
};
if (outputPath) {
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8');
}
console.log(JSON.stringify({ ...manifest, outputPath: outputPath || null }, null, 2));
