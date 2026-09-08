import assert from 'node:assert/strict';
import { buildEnterpriseFactReply, enterpriseResponseDirective, factReplyPreservesValues, isEnterpriseFactLookupRequest, isEnterpriseRefreshRequest } from '../src/enterprise_context.mjs';
import { activeDeferredWorkTaskCount, runDeferredWorkTask } from '../src/deferred_work_task.mjs';

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

assert.equal(isEnterpriseRefreshRequest('你再重新帮我查一下，上周的数据吧'), true);
assert.equal(isEnterpriseRefreshRequest('帮我刷新一下周报里的最新数据'), true);
assert.equal(isEnterpriseRefreshRequest('帮我看一下最新数据'), true);
assert.equal(isEnterpriseRefreshRequest('好呀，那我们先聊点别的'), false);
assert.equal(isEnterpriseRefreshRequest('你再看看这个电影'), false);
assert.equal(isEnterpriseRefreshRequest('帮我看看最新电影'), false);
assert.equal(isEnterpriseFactLookupRequest('帮我查一下中影上周销售额'), true);
assert.equal(isEnterpriseFactLookupRequest('中影上周销售额为什么下降'), false);
assert.equal(isEnterpriseFactLookupRequest('帮我查一下中影上周线上销售额'), true);
assert.equal(isEnterpriseFactLookupRequest('帮我找一下中影店的客流用户画像'), false);
assert.equal(isEnterpriseFactLookupRequest('帮我查一下中影接待客流多少人'), true);
assert.equal(isEnterpriseFactLookupRequest('帮我找一下中影店的客流用户画像', {
  interactionIntent: 'lookup', intent: { assetTypes: ['venue_profile'], metricIds: [] },
}), false);

const factReply = buildEnterpriseFactReply({
  message: '帮我查一下中影上周销售数据',
  route: { scope: { venueIds: ['ZHONGYING'] }, intent: { timeRange: '2026-08-15/2026-08-21' } },
  context: { items: [{
    id: 'record:2026-08-15_2026-08-21',
    summary: JSON.stringify({ venue: '中影', periodStart: '2026-08-15', periodEnd: '2026-08-21', core: {
      box_office_total: 15951.1, sales_order_count: 149, online_sales_amount: 4225.1, offline_sales_amount: 11726,
    }, sourceTitle: '中影周销售表' }),
  }] },
});
assert.equal(factReply.matched, true);
assert.match(factReply.reply, /销售额（票房合计）\s*15,951\.10 元/);
assert.match(factReply.reply, /销售票数\s*149 张/);
assert.equal(factReplyPreservesValues('嗯，我查到了～中影 2026-08-15 至 2026-08-21，销售额（票房合计）15,951.1 元，销售票数 149 张，线上销售额 4,225.10 元，线下销售额 11,726 元。来源：中影周销售表。', factReply), true);
assert.equal(factReplyPreservesValues('我先记下啦，等会儿再告诉你。', factReply), false);

const onlineFactReply = buildEnterpriseFactReply({
  message: '帮我查一下中影上周线上销售额',
  route: { scope: { venueIds: ['ZHONGYING'] }, intent: { timeRange: '2026-08-15/2026-08-21' } },
  context: factReply && { items: [{
    id: 'record:2026-08-15_2026-08-21',
    summary: JSON.stringify({ venue: '中影', periodStart: '2026-08-15', periodEnd: '2026-08-21', core: {
      box_office_total: 15951.1, online_sales_amount: 4225.1,
    }, sourceTitle: '中影周销售表' }),
  }] },
});
assert.equal(onlineFactReply.matched, true);
assert.match(onlineFactReply.reply, /线上销售额\s*4,225\.10 元/);
assert.doesNotMatch(onlineFactReply.reply, /票房合计/);

const refreshDirective = enterpriseResponseDirective({
  route: { conversationType: 'work' },
  refreshRequested: true,
  deferredAckSent: true,
  context: { items: [{ epistemicStatus: 'system_fact', summary: '本周票房 14635.51 元' }] },
});
assert.match(refreshDirective, /必须在这一轮直接给出结果/);
assert.match(refreshDirective, /禁止说“我再查一下/);

const profileDirective = enterpriseResponseDirective({
  route: { conversationType: 'work', interactionIntent: 'lookup', intent: { assetTypes: ['venue_profile'], metricIds: [] } },
  context: { items: [{ assetType: 'venue_profile', title: '中影', summary: '位置与客群资料' }] },
});
assert.match(profileDirective, /门店画像资料/);
assert.match(profileDirective, /不要声称需要权限/);

let fastAck = false;
const fast = await runDeferredWorkTask({
  key: 'check-fast',
  delayMs: 40,
  operation: async () => { await sleep(5); return { ok: true }; },
  onDeferred: async () => { fastAck = true; },
});
assert.deepEqual(fast.value, { ok: true });
assert.equal(fast.deferred, false);
assert.equal(fastAck, false);

const events = [];
const slow = await runDeferredWorkTask({
  key: 'check-slow',
  delayMs: 20,
  operation: async () => { await sleep(75); events.push('result'); return 'done'; },
  onDeferred: async () => { events.push('ack'); },
});
assert.equal(slow.value, 'done');
assert.equal(slow.deferred, true);
assert.deepEqual(events, ['ack', 'result']);
assert.equal(activeDeferredWorkTaskCount(), 0);

console.log('deferred work task checks passed');
