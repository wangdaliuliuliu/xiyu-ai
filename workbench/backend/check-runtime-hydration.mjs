import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const html = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
for (const match of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)) new vm.Script(match[1]);
const start = html.indexOf('async function hydrateRuntimeState(){');
const end = html.indexOf('const SETTINGS_ENDPOINT=', start);
const code = html.slice(start, end);
for (const failed of [false, true]) {
  const cache = new Map([['records', JSON.stringify([{ id: 'old-browser-record', amount: 1 }])]]);
  const writes = [], localWrites = [];
  const fresh = [{ id: 'server-record', amount: 99 }];
  const sandbox = {
    Object, JSON, clearTimeout, console: { warn() {} },
    RUNTIME_STATE_KINDS: { records: 'records' }, runtimeStateReady: true, runtimeStateHydrating: false, runtimeStateTimers: {}, runtimeStateRevisions: {},
    KEY: 'records', REPORTS: 'reports', WORKBENCH_STATE_KEY: 'workbench', records: [], reports: {}, activePage: 'inbox',
    window: {}, localStorage: { getItem: key => cache.get(key), setItem: (key, value) => cache.set(key, value) },
    read: (key, fallback) => JSON.parse(cache.get(key) || 'null') || fallback,
    runtimeStateEmpty: () => [], runtimeStateUrl: kind => `/api/runtime-state/${kind}`,
    normalizeRecords: x => x, cleanDuplicateBlankDrafts: x => x,
    write: (key, value) => { localWrites.push(key); if (sandbox.runtimeStateReady) writes.push({ key, value }); },
    fetch: async () => ({ ok: !failed, json: async () => ({ ok: !failed, data: fresh, revision: 17 }) }),
  };
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);
  await sandbox.hydrateRuntimeState();
  assert.equal(writes.length, 0, 'page initialization must not send cached data back');
  assert.equal(sandbox.runtimeStateReady, !failed, 'incomplete hydration must not enable writes');
  if (!failed) {
    assert.deepEqual(sandbox.records, fresh);
    assert.ok(cache.has('records_before_server_hydration'), 'preserve old browser data for explicit recovery');
  }
}
for (const name of ['RUNTIME_STATE_ENDPOINT', 'FEISHU_SYNC_ENDPOINT', 'INTELLIGENCE_ENDPOINT']) {
  const declaration = html.split('\n').find(line => line.trimStart().startsWith(`const ${name}=`));
  const value = vm.runInNewContext(`${declaration}; ${name}`, { window: {}, location: { protocol: 'http:', hostname: '127.0.0.1', port: '4175' } });
  assert.ok(value.startsWith('/api/'), `${name} must use the current origin`);
}
console.log('runtime hydration checks passed: server authority, no read-side writes, failure gate, origin isolation, inline syntax');
