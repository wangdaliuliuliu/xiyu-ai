import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import os from 'node:os';
import fs from 'node:fs';
import path from 'node:path';

const isolated = fs.mkdtempSync(path.join(os.tmpdir(), 'xiyu-result-contract-'));
Object.assign(process.env, { DB_PATH: path.join(isolated, 'db.sqlite'), DATA_DIR: isolated, LOG_DIR: path.join(isolated, 'logs'), XIYU_WORKBENCH_ACTIVE_TASKS_PATH: path.join(isolated, 'tasks.json'), XIYU_WORKBENCH_OUTBOX_PATH: path.join(isolated, 'outbox.json') });
let response = { status: 200, type: 'application/json', body: {} };
let hits = 0;
const server = http.createServer((req, res) => { hits++; res.writeHead(response.status, { 'content-type': response.type }); res.end(typeof response.body === 'string' ? response.body : JSON.stringify(response.body)); });
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
process.env.XIYU_WORKBENCH_CONTEXT_URL = `http://127.0.0.1:${server.address().port}`;
const mod = await import('../../src/enterprise_context.mjs');
const catalog = { project: { id: 'test' }, venues: [{ id: 'DONGDA', name: '东大店' }] };
const route = { conversationType: 'work', interactionIntent: 'lookup', retrievalNeeded: true, confidence: 1, scope: { projectId: 'test', venueIds: ['DONGDA'], venueNames: ['东大店'] }, intent: { metricIds: ['box_office_total'], timeRange: '2026-09-02' } };
const item = (value, source = '销售日报', date = '2026-09-02') => ({ id: source, title: source, summary: { venue: '东大店', periodStart: date, periodEnd: date, sourceTitle: source, metricLabels: { box_office_total: '销售额' }, core: { box_office_total: value } } });
test.after(() => { server.closeAllConnections(); server.close(); });

test('typed HTTP faults do not become missing records or resource denial', async () => {
  for (const [status, type, body, expected] of [
    [404, 'text/html', '<html>edge</html>', 'unavailable'],
    [200, 'text/html', '<html>login</html>', 'unavailable'],
    [200, 'application/json', {}, 'unavailable'],
    [401, 'application/json', { error: 'token expired' }, 'unavailable'],
    [403, 'application/json', { error: '当前用户无权读取该项目或门店资料' }, 'forbidden'],
    [200, 'application/json', { context: { items: [] } }, 'not_found'],
  ]) {
    response = { status, type, body };
    const result = await mod.retrieveEnterpriseResult(route, { accountId: 51, catalog });
    assert.equal(result.status, expected, JSON.stringify(response));
    assert.equal(result.stage, 'retrieve');
  }
});
test('scope and owner fail before network access', async () => {
  const before = hits;
  assert.equal((await mod.retrieveEnterpriseResult(route, { catalog })).status, 'forbidden');
  assert.equal((await mod.retrieveEnterpriseResult({ ...route, scope: { projectId: 'other' } }, { accountId: 51, catalog })).status, 'forbidden');
  assert.equal(hits, before);
});
test('complete answer preserves every field after final filters', () => {
  const fact = mod.buildEnterpriseFactReply({ message: '9月2号东大店销售额是多少？', route, context: { items: [item(12000)] } });
  assert.equal(fact.status, 'complete');
  assert.equal(mod.factReplyPreservesValues(fact.reply, fact), true);
  for (const [a, b] of [['东大店', '其他店'], ['2026-09-02', '2026-09-03'], ['12,000', '15,000'], ['销售额', '客流'], ['销售日报', '']]) {
    const broken = fact.reply.replaceAll(a, b);
    assert.equal(mod.factReplyPreservesValues(broken, fact), false, `${a}: ${broken}`);
    assert.equal(mod.finalizeEnterpriseReply({ enterpriseResult: fact, factResult: fact }, broken).outputOrigin, 'deterministic_result');
  }
});
test('conflicting sources stay conflicting through the final answer', async () => {
  const turn = await mod.prepareEnterpriseContext({ message: '9月2号东大店销售额是多少？', accountId: 51, companionId: 61 }, { catalog, route: async () => structuredClone(route), retrieve: async () => ({ items: [item(12000, '表A'), item(15000, '表B')] }) });
  assert.equal(turn.enterpriseResult.status, 'conflict');
  const final = mod.finalizeEnterpriseReply(turn, '销售额12000元');
  assert.match(final.reply, /12000.*表A.*15000.*表B/);
  assert.equal(final.outputOrigin, 'deterministic_result');
});
test('two days cannot silently use a weekly record or a different store', () => {
  const base = { message: '这两天销售额怎么样？', route: { ...route, intent: { metricIds: ['box_office_total'], timeRange: '' } }, context: { items: [item(12000)] } };
  assert.equal(mod.buildEnterpriseFactReply(base).status, 'clarification');
  assert.equal(mod.buildEnterpriseFactReply({ ...base, message: '9月2号西大店销售额是多少？', route: { ...route, scope: { venueNames: ['西大店'] } } }).status, 'not_found');
  assert.equal(mod.buildEnterpriseFactReply({ ...base, route: { ...route, intent: { ...route.intent, timeRange: '2026-09-01 至 2026-09-02' } } }).status, 'not_found');
});
