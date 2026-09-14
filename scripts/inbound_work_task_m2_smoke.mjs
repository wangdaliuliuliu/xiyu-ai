/* M2 隔离来源执行回归：只使用内存来源 fixture，不读取生产表、不写生产状态。
 * 该脚本验证结构化 task -> source-router -> grounded context 的控制流；
 * 真实自然语言语义效果留给 M3 的 DeepSeek 测试。
 */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xiyu-inbound-m2-'));
process.env.XIYU_WORKBENCH_CONTEXT_URL = 'http://m2-workbench.invalid';
process.env.XIYU_WORKBENCH_CONTEXT_ENABLED = 'true';
process.env.XIYU_WORKBENCH_ACTIVE_TASKS_PATH = path.join(root, 'active-tasks.json');
process.env.XIYU_WORKBENCH_OUTBOX_PATH = path.join(root, 'outbox.json');

const { sourceCapabilities, planSourceLookup, executeSourceLookup } = await import('../workbench/backend/cognition/source-router.mjs');
const bridge = await import('../src/enterprise_context.mjs');
const profile = { venues: { 中影: { venueId: 'ZHONGYING' }, 东坝: { venueId: 'DONGBA' } } };
const catalog = { project: { id: 'xiyu-vr', name: '溪语经营项目' }, venues: [{ id: 'ZHONGYING', name: '中影' }, { id: 'DONGBA', name: '东坝' }], capabilities: sourceCapabilities, nodes: [] };
const now = new Date('2026-09-13T04:00:00.000Z');
const dates = ['2026-09-10', '2026-09-11', '2026-09-12'];

function sourceData({ trafficMissing = [] } = {}) {
  const rows = {};
  for (const date of dates) {
    rows[`channel:damai:${date}`] = { 日期: date, 今日销售额: date.endsWith('10') ? 100 : date.endsWith('11') ? 150 : 200, 今日票数: date.endsWith('10') ? 10 : date.endsWith('11') ? 15 : 20 };
    rows[`channel:mini:${date}`] = { 日期: date, 今日销售额: date.endsWith('10') ? 50 : date.endsWith('11') ? 60 : 70, 今日票数: date.endsWith('10') ? 5 : date.endsWith('11') ? 6 : 7, 今日非线下销售额: date.endsWith('10') ? 40 : date.endsWith('11') ? 48 : 56, 今日线下销售额: date.endsWith('10') ? 10 : date.endsWith('11') ? 12 : 14 };
    if (!trafficMissing.includes(date)) rows[`traffic:${date}`] = { 业务日期: date, 门店ID: 'ZHONGYING', venue_traffic: date.endsWith('10') ? 1000 : date.endsWith('11') ? 900 : 1200, reach_count: date.endsWith('10') ? 400 : date.endsWith('11') ? 360 : 500, conversion_count: date.endsWith('10') ? 100 : date.endsWith('11') ? 90 : 130 };
  }
  return rows;
}

function sourceConfig(rows, suffix = '') {
  const channelHeaders = ['日期', '今日销售额', '今日票数', '今日非线下销售额', '今日线下销售额'];
  const trafficHeaders = ['业务日期', '门店ID', 'venue_traffic', 'reach_count', 'conversion_count'];
  const getRows = key => Object.entries(rows).filter(([id]) => id.startsWith(`${key}:`)).map(([, row]) => Object.values(row));
  const readRange = async (token, range) => {
    const sheet = range.split('!')[0];
    const bare = range.slice(sheet.length + 1);
    if (bare === 'A1:Z1') return [sheet === 'traffic' ? trafficHeaders : channelHeaders];
    if (bare === 'A2:Z5001') {
      if (sheet === 'traffic') return getRows('traffic');
      return Object.entries(rows).filter(([id]) => id.startsWith(`channel:${sheet}:`)).map(([, row]) => channelHeaders.map(header => row[header] ?? ''));
    }
    throw new Error(`unexpected range ${token} ${range}`);
  };
  return {
    channel_daily: { token: `channel${suffix}`, title: '隔离渠道日销售来源', url: 'https://isolated.invalid/channel', dateHeader: '日期', sheets: () => [{ id: 'damai', channel: '大麦' }, { id: 'mini', channel: '小程序' }], value: (row, metric, channel) => metric === 'box_office_total' ? row['今日销售额'] : metric === 'sales_order_count' ? row['今日票数'] : metric === 'online_sales_amount' ? (channel === '小程序' ? row['今日非线下销售额'] : row['今日销售额']) : metric === 'offline_sales_amount' ? (channel === '小程序' ? row['今日线下销售额'] : 0) : null, boundary: '隔离 fixture，不代表生产口径' },
    daily_traffic: { token: `traffic${suffix}`, title: '隔离日客流来源', url: 'https://isolated.invalid/traffic', dateHeader: '业务日期', venueHeader: '门店ID', sheets: () => [{ id: 'traffic' }], value: (row, metric) => row[metric], boundary: '隔离 fixture，不代表生产口径' },
    readRange,
  };
}

const data = sourceData();
const sources = sourceConfig(data);
const fullTask = { scope: { projectId: 'xiyu-vr', venueIds: ['ZHONGYING'] }, timeSpec: { kind: 'recent_complete_days', count: 3 }, requestedOutcome: { kind: 'performance_summary', businessMeaning: '判断近期经营表现', metricIds: ['box_office_total', 'sales_order_count', 'venue_traffic', 'reach_count', 'conversion_count'] }, metricIds: ['box_office_total', 'sales_order_count', 'venue_traffic', 'reach_count', 'conversion_count'] };
const input = { projectId: 'xiyu-vr', scope: fullTask.scope, task: fullTask };
const plan = planSourceLookup(input, profile, now);
assert.equal(plan.status, 'ready');
assert.deepEqual(plan.capabilityIds, ['channel_daily', 'daily_traffic']);
const full = await executeSourceLookup(plan, { sources: sourcesFor(sources), readRange: sources.readRange, parseDate: value => String(value), parseNumber: value => value === '' || value == null ? null : Number(value), now: now.getTime() });
assert.equal(full.status, 'complete');
assert.deepEqual(full.dates, dates);
assert.equal(full.daily.length, 3);
assert.equal(full.daily[0].core.box_office_total, 150);
assert.equal(full.daily[2].core.venue_traffic, 1200);
assert.equal(full.budget.documents, 2);
assert.equal(full.budget.modelReceivesRawRows, false);
assert.equal(full.summary.changes.box_office_total.direction, 'up');

const exactPlan = planSourceLookup({ projectId: 'xiyu-vr', scope: fullTask.scope, task: { ...fullTask, timeSpec: { kind: 'exact_date', start: '2026-09-11', end: '2026-09-11' }, requestedOutcome: { kind: 'fact', metricIds: ['box_office_total'] }, metricIds: ['box_office_total'] } }, profile, now);
assert.equal(exactPlan.status, 'ready');
assert.deepEqual(exactPlan.dates, ['2026-09-11']);
const exact = await executeSourceLookup(exactPlan, { sources: sourcesFor(sources), readRange: sources.readRange, parseDate: String, parseNumber: Number, now: now.getTime() });
assert.equal(exact.status, 'complete');
assert.equal(exact.core.box_office_total, 210);

const invalid = planSourceLookup({ projectId: 'xiyu-vr', scope: { projectId: 'xiyu-vr', venueIds: ['BEIJING'] }, task: fullTask }, profile, now);
assert.equal(invalid.status, 'clarification');
assert.ok(!JSON.stringify(invalid).match(/北京|BEIJING/));

const partialSources = sourceConfig(sourceData({ trafficMissing: ['2026-09-11'] }), '-partial');
const partialPlan = planSourceLookup(input, profile, now);
const partial = await executeSourceLookup(partialPlan, { sources: sourcesFor(partialSources), readRange: partialSources.readRange, parseDate: String, parseNumber: value => value === '' || value == null ? null : Number(value), now: now.getTime() });
assert.equal(partial.status, 'partial');
assert.equal(partial.daily.length, 3);
assert.equal(partial.daily.find(row => row.date === '2026-09-11').status, 'partial');
assert.match(partial.reason, /部分来源资料缺失/);
assert.ok(partial.daily.find(row => row.date === '2026-09-11').core.box_office_total > 0);

const sourceFailure = sourceConfig(data, '-source-failure');
sourceFailure.daily_traffic = { ...sourceFailure.daily_traffic, token: '' };
const partialBySource = await executeSourceLookup(planSourceLookup(input, profile, now), { sources: sourcesFor(sourceFailure), readRange: sourceFailure.readRange, parseDate: String, parseNumber: value => value === '' || value == null ? null : Number(value), now: now.getTime() });
assert.equal(partialBySource.status, 'partial');
assert.equal(partialBySource.daily.length, 3);
assert.ok(partialBySource.daily.every(row => row.status === 'partial'));
assert.ok(partialBySource.daily.every(row => row.missingSources.includes('隔离日客流来源')));
assert.match(partialBySource.reason, /部分来源读取失败/);

const rangePlan = planSourceLookup({ projectId: 'xiyu-vr', scope: fullTask.scope, task: { ...fullTask, timeSpec: { kind: 'date_range', start: '2026-09-10', end: '2026-09-12' } } }, profile, now);
const range = await executeSourceLookup(rangePlan, { sources: sourcesFor(partialSources), readRange: partialSources.readRange, parseDate: String, parseNumber: value => value === '' || value == null ? null : Number(value), now: now.getTime() });
assert.equal(range.status, 'partial');
assert.equal(range.daily.find(row => row.date === '2026-09-11').status, 'partial');
assert.equal(range.daily.find(row => row.date === '2026-09-11').core.box_office_total, 210);

const oldPlan = planSourceLookup({ projectId: 'xiyu-vr', scope: { projectId: 'xiyu-vr', venueNames: ['中影'] }, query: { text: '查一下9月11日中影销售额' } }, profile, now);
assert.equal(oldPlan.status, 'ready');
assert.equal(oldPlan.date, '2026-09-11');

function sourcesFor(config) {
  return { channel_daily: config.channel_daily, daily_traffic: config.daily_traffic };
}

let receivedBody = null;
const prepared = await bridge.prepareEnterpriseContext({ message: '最近这几天中影的', history: [{ role: 'user', content: '帮我看看最近业绩怎么样啊' }], accountId: 'm2-account', companionId: 'm2-companion' }, {
  catalog,
  route: () => ({ conversationType: 'work', interactionIntent: 'lookup', taskTransition: 'start', task: fullTask, workSegments: ['最近这几天中影的'], retrievalNeeded: true, writebackPotential: false, confidence: 0.99 }),
  retrieve: async body => { receivedBody = body; return { contextVersion: 'm2-fixture', items: full.daily.map(row => ({ id: `source:${row.date}`, assetType: 'operating_fact', epistemicStatus: 'system_fact', title: `${row.date} 中影`, summary: JSON.stringify({ venue: '中影', periodStart: row.date, periodEnd: row.date, core: row.core, sourceTitle: '隔离多来源结果' }) })), sourceLookup: full, boundaries: ['隔离 fixture'] }; },
});
assert.equal(receivedBody.task.timeSpec.kind, 'recent_complete_days');
assert.deepEqual(receivedBody.scope.venueIds, ['ZHONGYING']);
assert.equal(prepared.activeTask.status, 'ready');
assert.ok(prepared.promptBlock.includes('2026-09-10'));

const retryCalls = [];
globalThis.fetch = async () => {
  retryCalls.push('read');
  if (retryCalls.length === 1) return new Response(JSON.stringify({ error: 'gateway' }), { status: 503, headers: { 'content-type': 'application/json' } });
  return new Response(JSON.stringify({ ok: true, catalog }), { status: 200, headers: { 'content-type': 'application/json' } });
};
bridge.__resetEnterpriseContextCacheForTest();
const retried = await bridge.getEnterpriseCatalogResult({ force: true });
assert.equal(retried.status, 'complete');
assert.equal(retryCalls.length, 2);

console.log(JSON.stringify({ ok: true, milestone: 'M2', status: 'passed', checks: 15, recentCompleteDays: full.dates, sources: full.budget.documents, retryAttempts: retryCalls.length }));
