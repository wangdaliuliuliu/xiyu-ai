#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const checks = [];
const pass = (name, ok, detail='') => { checks.push({ name, ok, detail }); console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? ` — ${detail}` : ''}`); };
const promptPath = path.join(root, 'backend', 'weekly-review-prompts-v6.json');
const strategyPromptPath = path.join(root, 'backend', 'strategy-workbench-prompts-v1.json');
const knowledgePath = path.join(root, 'backend', 'strategy-knowledge-v1.json');
for (const [name, file] of [['weekly prompt contract', promptPath], ['strategy prompt contract', strategyPromptPath], ['strategy knowledge contract', knowledgePath]]) {
  try { const parsed = JSON.parse(fs.readFileSync(file, 'utf8')); pass(name, Boolean(parsed && typeof parsed === 'object')); } catch (error) { pass(name, false, error.message); }
}
const weekly = JSON.parse(fs.readFileSync(promptPath, 'utf8'));
const synthesis = weekly.stages?.review_synthesis;
const experience = weekly.stages?.experience_candidates;
const action = weekly.stages?.next_action_candidates;
pass('prompt has synthesis stage', Boolean(synthesis?.system && synthesis?.outputSchema));
pass('prompt has experience gate', /候选|验证|审核/.test(experience?.system || ''));
pass('prompt has action stage', Boolean(action?.system && action?.outputSchema));
pass('channel/card semantic guard', /channels.*全部商品|渠道销售.*全部商品/.test(synthesis?.system || '') && /cards.*次卡|次卡.*cards/.test(synthesis?.system || ''));
pass('experience cannot auto-publish', /不能.*正式经验|人工.*审核|候选经验/.test(experience?.system || ''));
const profile = JSON.parse(fs.readFileSync(path.join(root, 'data', 'strategy-project-profile.json'), 'utf8'));
pass('venue registry has two defaults', ['东坝','中影'].every(name => profile.venues?.[name]?.venueId));
pass('venue source mappings are data-driven', ['东坝','中影'].every(name => Object.keys(profile.venues?.[name]?.sourceSheets || {}).length >= 5));
const config = fs.readFileSync(path.join(root, 'qa', 'promptfoo.yaml'), 'utf8');
pass('promptfoo config exists', /providers:/.test(config) && /tests:/.test(config));
const failed = checks.filter(x => !x.ok).length;
console.log(`\n${checks.length - failed}/${checks.length} checks passed`);
process.exitCode = failed ? 1 : 0;
