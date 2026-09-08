// Only metadata and selected facts cross the model boundary. Document contents stay here.
export const sourceCapabilities = [
  { id: 'channel_daily', title: '渠道日销售来源表', queries: '指定日期、门店的销售额、票数、实收额、线上线下销售额', grain: '日×门店×渠道', metrics: ['box_office_total', 'sales_order_count', 'platform_settlement', 'online_sales_amount', 'offline_sales_amount'] },
  { id: 'daily_traffic', title: '周报辅助表·日客流', queries: '指定日期、门店的大盘客流、触达人数、转化人数', grain: '日×门店', metrics: ['venue_traffic', 'reach_count', 'conversion_count'] },
];
export function planSourceLookup(input, profile, now = new Date()) {
  const query = input.query || {};
  const text = String(query.text || query.question || '');
  if (/上周|本周|这周|周报|上月|本月/.test(text) && !/\d{1,2}月\d{1,2}[日号]/.test(text)) return null;
  if ((!/(多少|查|核对|读取|销售数据|经营数据)/.test(text) && query.interactionIntent !== 'lookup') || /(为什么|原因|建议|怎么办)/.test(text)) return null;
  let metrics = [];
  if (/(销售额|票房)/.test(text)) metrics.push(/线上/.test(text) ? 'online_sales_amount' : /线下/.test(text) ? 'offline_sales_amount' : 'box_office_total');
  if (/票数|卖了几张/.test(text)) metrics.push('sales_order_count');
  if (/实收|结算/.test(text)) metrics.push('platform_settlement');
  for (const [word, key] of [['大盘客流','venue_traffic'],['触达人数','reach_count'],['转化人数','conversion_count']]) if (text.includes(word)) metrics.push(key);
  if (/销售数据|经营数据/.test(text)) metrics = ['box_office_total', 'sales_order_count'];
  if (!metrics.length && query.interactionIntent === 'lookup') metrics = (query.metricIds || []).filter(id => sourceCapabilities.some(c => c.metrics.includes(id)));
  if (!metrics.length) return null;
  const venues = Object.entries(profile.venues || {});
  const mentioned = venues.filter(([name, v]) => [name, ...(v.aliases || [])].some(alias => text.includes(alias)));
  // A phonetic guess is not authority to read a different store.
  if (/东大/.test(text) && !mentioned.length) return { status: 'clarification', reason: '“东大店”是否指目录中的“东坝店”？', metrics };
  const ids = [...(input.scope?.venueIds || []), ...(input.scope?.venueNames || [])];
  const selected = mentioned.length ? mentioned : venues.filter(([name,v]) => ids.includes(name) || ids.includes(v.venueId));
  if (selected.length !== 1) return { status: 'clarification', reason: '请指定要查询的一个门店', metrics };
  const today = new Date(now.getTime() + 8 * 3600000).toISOString().slice(0,10);
  const dates = [...text.matchAll(/(?:(\d{4})年)?(\d{1,2})月(\d{1,2})[日号]?/g)].map(m => `${m[1] || today.slice(0,4)}-${m[2].padStart(2,'0')}-${m[3].padStart(2,'0')}`);
  dates.push(...(text.match(/\d{4}-\d{2}-\d{2}/g) || []));
  if (!dates.length && /昨天|昨日|今天|今日/.test(text)) dates.push(new Date(new Date(`${today}T00:00:00Z`).getTime() - (/昨天|昨日/.test(text) ? 86400000 : 0)).toISOString().slice(0,10));
  if (!dates.length) dates.push(...(String(query.timeRange || '').match(/\d{4}-\d{2}-\d{2}/g) || []));
  const unique = [...new Set(dates)];
  if (unique.length !== 1 || !Number.isFinite(Date.parse(unique[0])) || new Date(unique[0]).toISOString().slice(0,10) !== unique[0]) return { status: 'clarification', reason: '当前日数据查询需要一个有效的明确日期；不以周汇总替代', metrics };
  const capability = sourceCapabilities.find(c => metrics.every(m => c.metrics.includes(m)));
  if (!capability) return { status: 'clarification', reason: '请分别查询销售数据和客流数据，以保留不同来源口径', metrics };
  return { status: 'ready', capabilityId: capability.id, venue: selected[0][0], venueId: selected[0][1].venueId, date: unique[0], metrics, assumedYear: !/\d{4}年|\d{4}-/.test(text) };
}

const column = index => { let n = index + 1, s = ''; while (n) { n--; s = String.fromCharCode(65+n%26)+s; n = Math.floor(n/26); } return s; };
const cache = new Map();
export async function executeSourceLookup(plan, { sources, readRange, parseDate, parseNumber, now = Date.now() }) {
  const source = sources[plan.capabilityId];
  if (!source?.token) throw new Error('所选来源未配置');
  const sheets = source.sheets(plan.venue);
  if (!sheets.length || sheets.length > 8) throw new Error('来源页签配置超出查询预算');
  let calls = 0;
  const read = async (sheet, range) => { if (++calls > 24) throw new Error('达到来源查询预算'); return readRange(source.token, `${sheet}!${range}`); };
  const results = [];
  for (const sheet of sheets) {
    const key = `${source.token}:${sheet.id}`;
    let index = cache.get(key);
    if (!index || now - index.at > 300000) {
      const headers = (await read(sheet.id, 'A1:Z1'))[0] || [];
      const dateCol = headers.indexOf(source.dateHeader);
      if (dateCol < 0) throw new Error('所选来源没有配置的日期列');
      const rows = await read(sheet.id, `${column(dateCol)}2:${column(dateCol)}5001`);
      if (rows.length >= 5000 && rows[4999]?.some(value => value !== '' && value != null)) throw new Error('日期索引超过5000行预算，需配置分区，不能报告无数据');
      index = { headers, dates: rows.map((row,i) => ({ date: parseDate(row[0]), row: i+2 })), at: now };
      cache.set(key,index);
    }
    const matches = index.dates.filter(row => row.date === plan.date);
    if (matches.length > 4) throw new Error('同日来源行过多，需要更精确分区');
    for (const hit of matches) {
      const values = (await read(sheet.id, `A${hit.row}:Z${hit.row}`))[0] || [];
      const row = Object.fromEntries(index.headers.map((h,i) => [h,values[i]]));
      if (parseDate(row[source.dateHeader]) !== plan.date) { cache.delete(key); throw new Error('来源行发生移动，请重试'); }
      if (source.venueHeader && ![plan.venue, plan.venueId].includes(String(row[source.venueHeader] || ''))) continue;
      results.push({ sheet: sheet.id, channel: sheet.channel, row: hit.row, values: Object.fromEntries(plan.metrics.map(metric => [metric, parseNumber(source.value(row,metric,sheet.channel))])) });
    }
  }
  const complete = results.length === sheets.length && new Set(results.map(r=>r.sheet)).size === sheets.length && results.every(r => plan.metrics.every(m => r.values[m] !== null));
  const core = Object.fromEntries(plan.metrics.map(metric => [metric, complete ? Math.round(results.reduce((sum,r) => sum+r.values[metric],0)*100)/100 : null]));
  return { status: complete ? 'complete' : 'incomplete', core, date: plan.date, venue: plan.venue, sourceTitle: source.title, sourceUrl: source.url, fetchedAt: new Date(now).toISOString(), provenance: results, budget: { documents: 1, sheets: sheets.length, calls, modelReceivesRawRows: false }, boundary: source.boundary, assumedYear: plan.assumedYear };
}
