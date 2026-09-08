import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'xiyu-agency-runtime-'));
Object.assign(process.env, { DB_PATH: path.join(dir, 'db.sqlite'), DATA_DIR: dir, LOG_DIR: path.join(dir, 'logs') });
const db = await import('../../src/db.mjs');
const { runAgencyCycle } = await import('../../src/proactive.mjs');
const store = db.getDb();
const companionId = Number(store.prepare('INSERT INTO companions(user_id,bot_id,name) VALUES(NULL,?,?,?)'.replace(',?,?,?', ',?,?')).run('runtime-test', '运行时测试').lastInsertRowid);
const owner = { accountId: 8801, companionId };

const appraisal = JSON.stringify({
  shouldAct: false,
  domain: 'personal',
  desiredChange: '保留这次低频思考机会',
  appraisalSummary: '没有新增证据',
  basisRefs: ['fixture:runtime'],
  priorityClass: 'normal',
  confidence: 0.8,
  needsUserInput: false,
  reconsiderAfterMinutes: 30,
  reason: 'cooldown fixture',
});

test('runtime lease fences concurrent agency cycles and releases after completion', async () => {
  let release;
  const firstProvider = () => new Promise(resolve => {
    release = () => resolve({ ok: true, text: appraisal, usage: null, provider: 'fixture', model: 'fixture', attempts: 1, fallback: false });
  });
  const first = runAgencyCycle({ ...owner, mode: 'shadow', runtimeGuard: true, sourceVersion: 'v1', deps: { now: 1_000_000, extractStructuredInfoDetailed: firstProvider } });
  await new Promise(resolve => setTimeout(resolve, 10));
  const second = await runAgencyCycle({ ...owner, mode: 'shadow', runtimeGuard: true, sourceVersion: 'v1', deps: { now: 1_000_001, extractStructuredInfoDetailed: async () => ({ ok: true, text: appraisal, usage: null, provider: 'fixture', model: 'fixture', attempts: 1, fallback: false }) } });
  assert.equal(second.status, 'busy');
  release();
  const firstResult = await first;
  assert.equal(firstResult.status, 'no_opportunity');
  const next = await runAgencyCycle({ ...owner, mode: 'shadow', runtimeGuard: true, sourceVersion: 'v2', deps: { now: 1_000_002, extractStructuredInfoDetailed: async () => ({ ok: true, text: appraisal, usage: null, provider: 'fixture', model: 'fixture', attempts: 1, fallback: false }) } });
  assert.equal(next.status, 'no_opportunity');
});

test.after(() => store.close());
