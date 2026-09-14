import assert from 'node:assert/strict';
import { buildEnterpriseFactReply, factReplyPreservesValues } from '../src/enterprise_context.mjs';

const dates = ['2026-09-09', '2026-09-10', '2026-09-11'];
const sales = [0, 261.9, 510.7];
const tickets = [0, 3, 4];
const context = {
  sourceLookup: { status: 'partial' },
  items: dates.map((date, index) => ({
    id: `source:${date}`,
    summary: JSON.stringify({
      venue: '中影', periodStart: date, periodEnd: date,
      core: { box_office_total: sales[index], sales_order_count: tickets[index] },
      sourceTitle: '运营渠道日销售来源表',
      boundary: '全部商品、已接入渠道的销售汇总；不等于利润。',
    }),
  })),
};
const route = {
  interactionIntent: 'lookup',
  scope: { venueIds: ['ZHONGYING'], venueNames: ['中影'] },
  task: {
    scope: { venueIds: ['ZHONGYING'], venueNames: ['中影'] },
    timeSpec: { kind: 'recent_complete_days', count: 3 },
    requestedOutcome: { kind: 'performance_summary' },
    metricIds: ['box_office_total', 'sales_order_count', 'venue_traffic', 'reach_count', 'conversion_count'],
  },
};

const result = buildEnterpriseFactReply({ message: '最近这几天中影的', route, context });
assert.equal(result.matched, true);
assert.ok(result.reply.length >= 220 && result.reply.length <= 380, `unexpected reply length: ${result.reply.length}`);
assert.equal((result.reply.match(/运营渠道日销售来源表/g) || []).length, 1);
assert.equal((result.reply.match(/资料未覆盖/g) || []).length, 1);
assert.doesNotMatch(result.reply, /来源为录入客流/);
assert.doesNotMatch(result.reply, /稳定增长|稳定趋势/);
for (const value of ['9/9', '9/10', '9/11', '0元', '261.9元', '510.7元', '0张', '3张', '4张']) assert.match(result.reply, new RegExp(value.replace('.', '\\.')));
assert.equal(factReplyPreservesValues(result.reply, result), true);

console.log(JSON.stringify({ ok: true, status: 'passed', length: result.reply.length, sourceMentions: 1, missingDataMentions: 1, factPreserved: true }));
