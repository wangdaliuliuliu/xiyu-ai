// Only metadata and selected facts cross the model boundary. Document contents stay here.
export const sourceCapabilities = [
  { id: 'channel_daily', title: '渠道日销售来源表', queries: '指定日期、门店的销售额、票数、实收额、线上线下销售额', grain: '日×门店×渠道', updateCadence: 'daily', freshnessRole: 'primary_for_recent_sales', metrics: ['box_office_total', 'sales_order_count', 'platform_settlement', 'online_sales_amount', 'offline_sales_amount'] },
  { id: 'daily_traffic', title: '周报辅助表·日客流', queries: '指定日期、门店的大盘客流、触达人数、转化人数', grain: '日×门店', updateCadence: 'daily', freshnessRole: 'primary_for_recent_traffic', metrics: ['venue_traffic', 'reach_count', 'conversion_count'] },
];

const PERFORMANCE_DEFAULT_METRICS = ['box_office_total', 'sales_order_count', 'venue_traffic', 'reach_count', 'conversion_count'];
const validDate = value => {
  const text = String(value || '').trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) return '';
  const date = new Date(`${text}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === text ? text : '';
};
const shanghaiDate = now => new Date(now.getTime() + 8 * 3600000).toISOString().slice(0, 10);
const dateSpan = (start, end, max = 31) => {
  const first = validDate(start), last = validDate(end);
  if (!first || !last || last < first) return [];
  const span = Math.floor((Date.parse(last) - Date.parse(first)) / 86400000);
  if (span > max) return [];
  return Array.from({ length: span + 1 }, (_, index) => new Date(Date.parse(first) + index * 86400000).toISOString().slice(0, 10));
};

function selectVenueFromScope(input, profile) {
  const venues = Object.entries(profile.venues || {});
  const lookup = new Map(venues.flatMap(([name, venue]) => [[name, [name, venue]], [String(venue?.venueId || name), [name, venue]]]));
  const scope = input.scope || input.task?.scope || input.query?.task?.scope || {};
  const raw = [...(scope.venueIds || []), ...(scope.venueNames || []), ...(scope.venues || [])].map(String).filter(Boolean);
  const selected = [...new Map(raw.map(value => lookup.get(value)).filter(Boolean).map(pair => [pair[0], pair])).values()];
  return selected;
}

function structuredPlan(input, profile, now) {
  const task = input.task || input.query?.task;
  if (!task || typeof task !== 'object') return null;
  const outcome = task.requestedOutcome && typeof task.requestedOutcome === 'object' ? task.requestedOutcome : {};
  const kind = String(outcome.kind || '').trim();
  const declaredMetrics = [...new Set([...(Array.isArray(task.metricIds) ? task.metricIds : []), ...(Array.isArray(outcome.metricIds) ? outcome.metricIds : [])].map(String).filter(Boolean))];
  const metrics = declaredMetrics.length ? declaredMetrics.filter(metric => sourceCapabilities.some(capability => capability.metrics.includes(metric))) : kind === 'performance_summary' ? PERFORMANCE_DEFAULT_METRICS : [];
  if (!metrics.length) return { status: 'clarification', reason: '还需要确认要核对的经营指标', metrics: [] };
  const selected = selectVenueFromScope(input, profile);
  if (selected.length !== 1) return { status: 'clarification', reason: '请指定目录中的一个门店', metrics };
  const [venue, venueProfile] = selected[0];
  const time = task.timeSpec && typeof task.timeSpec === 'object' ? task.timeSpec : {};
  const timeKind = { exact: 'exact_date', range: 'date_range', recent: 'recent_complete_days', current: 'current_period' }[String(time.kind || '')] || String(time.kind || 'unspecified');
  let dates = [];
  if (timeKind === 'exact_date') dates = [validDate(time.start || time.end)].filter(Boolean);
  else if (timeKind === 'date_range') dates = dateSpan(time.start, time.end);
  else if (timeKind === 'current_period') dates = [shanghaiDate(now)];
  else if (timeKind === 'unspecified' && kind === 'performance_summary') timeKind = 'recent_complete_days';
  if (timeKind === 'recent_complete_days') {
    const count = Math.max(1, Math.min(7, Number.isFinite(Number(time.count)) ? Math.trunc(Number(time.count)) : 3));
    return { status: 'ready', structured: true, capabilityIds: sourceCapabilities.filter(capability => metrics.some(metric => capability.metrics.includes(metric))).map(capability => capability.id), venue, venueId: venueProfile.venueId, metrics, timeSpec: { kind: timeKind, count }, dates: null, freshnessPolicy: 'daily_sources_before_weekly_context', requestedOutcome: { kind: kind || 'fact', businessMeaning: String(outcome.businessMeaning || task.businessMeaning || '') }, assumedYear: false };
  }
  if (!dates.length) return { status: 'clarification', reason: timeKind === 'date_range' ? '请确认有效的日期范围' : '请确认要查询的有效日期', metrics };
  const capabilityIds = sourceCapabilities.filter(capability => metrics.some(metric => capability.metrics.includes(metric))).map(capability => capability.id);
  return { status: 'ready', structured: true, capabilityIds, capabilityId: capabilityIds[0], venue, venueId: venueProfile.venueId, date: dates.length === 1 ? dates[0] : undefined, dates, timeSpec: { kind: timeKind, start: dates[0], end: dates[dates.length - 1], count: null }, metrics, freshnessPolicy: ['exact_date', 'date_range', 'current_period'].includes(timeKind) ? 'daily_sources_before_weekly_context' : 'declared_sources', requestedOutcome: { kind: kind || 'fact', businessMeaning: String(outcome.businessMeaning || task.businessMeaning || '') }, assumedYear: false };
}

function legacyPlan(input, profile, now) {
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
  const today = shanghaiDate(now);
  const dates = [...text.matchAll(/(?:(\d{4})年)?(\d{1,2})月(\d{1,2})[日号]?/g)].map(m => `${m[1] || today.slice(0,4)}-${m[2].padStart(2,'0')}-${m[3].padStart(2,'0')}`);
  dates.push(...(text.match(/\d{4}-\d{2}-\d{2}/g) || []));
  if (!dates.length && /昨天|昨日|今天|今日/.test(text)) dates.push(new Date(new Date(`${today}T00:00:00Z`).getTime() - (/昨天|昨日/.test(text) ? 86400000 : 0)).toISOString().slice(0,10));
  if (!dates.length) dates.push(...(String(query.timeRange || '').match(/\d{4}-\d{2}-\d{2}/g) || []));
  const unique = [...new Set(dates)];
  if (unique.length !== 1 || !validDate(unique[0])) return { status: 'clarification', reason: '当前日数据查询需要一个有效的明确日期；不以周汇总替代', metrics };
  const capabilityIds = sourceCapabilities.filter(capability => metrics.some(metric => capability.metrics.includes(metric))).map(capability => capability.id);
  if (!capabilityIds.length) return { status: 'clarification', reason: '当前没有覆盖所需指标的来源', metrics };
  return { status: 'ready', capabilityIds, capabilityId: capabilityIds[0], venue: selected[0][0], venueId: selected[0][1].venueId, date: unique[0], dates: unique, metrics, timeSpec: { kind: 'exact_date', start: unique[0], end: unique[0], count: null }, freshnessPolicy: 'daily_sources_before_weekly_context', requestedOutcome: { kind: 'fact', businessMeaning: '' }, assumedYear: !/\d{4}年|\d{4}-/.test(text) };
}

export function planSourceLookup(input, profile, now = new Date()) {
  return structuredPlan(input, profile, now) || legacyPlan(input, profile, now);
}

const column = index => { let n = index + 1, s = ''; while (n) { n--; s = String.fromCharCode(65+n%26)+s; n = Math.floor(n/26); } return s; };
const cache = new Map();

async function loadSheetIndex(source, sheet, read, parseDate, now) {
  const key = `${source.token}:${sheet.id}`;
  let index = cache.get(key);
  if (index && index.at > now - 300000 && Array.isArray(index.rows)) return index;
  const headers = (await read(sheet.id, 'A1:Z1'))[0] || [];
  const dateCol = headers.indexOf(source.dateHeader);
  if (dateCol < 0) throw new Error('所选来源没有配置的日期列');
  const rows = await read(sheet.id, 'A2:Z5001');
  if (rows.length >= 5000 && rows[4999]?.some(value => value !== '' && value != null)) throw new Error('日期索引超过5000行预算，需配置分区，不能报告无数据');
  index = { headers, rows: rows.map((values, index) => ({ date: parseDate(values[dateCol]), row: index + 2, values })), at: now };
  cache.set(key, index);
  return index;
}

function round(value) { return Math.round((value + Number.EPSILON) * 100) / 100; }

async function executeCapability(plan, capabilityId, source, { readRange, parseDate, parseNumber, now }) {
  if (!source?.token) throw new Error(`来源 ${capabilityId} 未配置`);
  const sheets = source.sheets(plan.venue);
  if (!sheets.length || sheets.length > 8) throw new Error('来源页签配置超出查询预算');
  let calls = 0;
  const read = async (sheet, range) => { if (++calls > 80) throw new Error('达到来源查询预算'); return readRange(source.token, `${sheet}!${range}`); };
  const indexes = [];
  for (const sheet of sheets) indexes.push({ sheet, index: await loadSheetIndex(source, sheet, read, parseDate, now) });
  const candidateDates = [...new Set(indexes.flatMap(({ index }) => index.rows.filter(row => row.date && (!source.venueHeader || row.values[index.headers.indexOf(source.venueHeader)] === undefined || [plan.venue, plan.venueId].includes(String(row.values[index.headers.indexOf(source.venueHeader)] || '')))).map(row => row.date)))].sort();
  const requestedDates = Array.isArray(plan.dates) && plan.dates.length ? plan.dates : candidateDates;
  const daily = {};
  for (const date of requestedDates) {
    const provenance = [];
    let complete = true;
    const totals = Object.fromEntries(plan.metrics.filter(metric => sourceCapabilities.find(capability => capability.id === capabilityId)?.metrics.includes(metric)).map(metric => [metric, 0]));
    for (const { sheet, index } of indexes) {
      const matches = index.rows.filter(row => row.date === date && (!source.venueHeader || [plan.venue, plan.venueId].includes(String(row.values[index.headers.indexOf(source.venueHeader)] || ''))));
      if (matches.length > 1) throw new Error('同日来源行过多，需要更精确分区');
      const hit = matches[0];
      if (!hit) { complete = false; continue; }
      const row = Object.fromEntries(index.headers.map((header, index) => [header, hit.values[index]]));
      const values = {};
      for (const metric of Object.keys(totals)) {
        values[metric] = parseNumber(source.value(row, metric, sheet.channel));
        if (values[metric] === null) complete = false;
        else totals[metric] = round(totals[metric] + values[metric]);
      }
      provenance.push({ sheet: sheet.id, channel: sheet.channel, row: hit.row, values });
    }
    daily[date] = { status: complete ? 'complete' : 'incomplete', core: complete ? totals : Object.fromEntries(Object.entries(totals).map(([metric, value]) => [metric, value || null])), date, venue: plan.venue, sourceTitle: source.title, sourceUrl: source.url, provenance };
  }
  return { capabilityId, title: source.title, url: source.url, boundary: source.boundary, daily, availableDates: candidateDates, budget: { documents: 1, sheets: sheets.length, calls } };
}

export async function executeSourceLookup(plan, { sources, readRange, parseDate, parseNumber, now = Date.now() }) {
  const capabilityIds = plan.capabilityIds || [plan.capabilityId];
  const sourceResults = [];
  const sourceFailures = [];
  for (const capabilityId of capabilityIds) {
    try {
      sourceResults.push(await executeCapability(plan, capabilityId, sources[capabilityId], { readRange, parseDate, parseNumber, now }));
    } catch (error) {
      const status = [401, 403].includes(Number(error?.httpStatus)) || /(?:HTTP|code)\s*(?:401|403)|权限|无权|拒绝访问/i.test(String(error?.message || '')) ? 'forbidden' : 'unavailable';
      sourceFailures.push({ capabilityId, title: sources[capabilityId]?.title || capabilityId, url: sources[capabilityId]?.url || '', status, reason: String(error?.message || error) });
    }
  }
  if (!sourceResults.length) {
    const status = sourceFailures.some(item => item.status === 'forbidden') ? 'forbidden' : 'unavailable';
    return { status, reason: sourceFailures.map(item => `${item.title}：${item.reason}`).join('；'), daily: [], missingDates: plan.dates || [], sourceResults: [], sourceFailures };
  }
  const sourceDates = sourceResults.flatMap(result => result.availableDates).filter(Boolean);
  const sourceCompleteDates = sourceResults.flatMap(result => Object.entries(result.daily || {})
    .filter(([date, row]) => date < shanghaiDate(new Date(now)) && row?.status === 'complete')
    .map(([date]) => date));
  let dates = Array.isArray(plan.dates) && plan.dates.length ? [...plan.dates] : [];
  if (plan.timeSpec?.kind === 'recent_complete_days') {
    // “完整自然日”约束日期本身已经结束；多来源不要求每个来源都齐全，
    // 否则一个客流来源缺行会把已有销售事实错误折叠成 not_found。
    // 每个来源的缺口在 daily.missingSources / status=partial 中保留。
    const completeDates = [...new Set(sourceCompleteDates)].sort().reverse();
    dates = completeDates.slice(0, Math.max(1, Math.min(7, Number(plan.timeSpec.count || 3)))).sort();
  } else if (!dates.length) dates = [...new Set(sourceDates)].sort();
  const daily = dates.map(date => {
    const results = sourceResults.map(result => result.daily[date]).filter(Boolean);
    const core = {};
    for (const result of results) for (const [metric, value] of Object.entries(result.core || {})) if (value !== null && value !== undefined) core[metric] = round((core[metric] || 0) + Number(value));
    const missingSources = [
      ...sourceResults.filter(result => result.daily[date]?.status !== 'complete').map(result => result.title),
      ...sourceFailures.map(result => result.title),
    ];
    return { date, venue: plan.venue, core, status: missingSources.length ? 'partial' : 'complete', missingSources, sources: results.map(result => ({ title: result.sourceTitle, url: result.sourceUrl, provenance: result.provenance })) };
  });
  const available = daily.filter(row => Object.keys(row.core).length);
  if (!available.length) {
    const status = sourceFailures.some(item => item.status === 'forbidden') ? 'forbidden' : sourceFailures.length ? 'unavailable' : 'not_found';
    const failureReason = sourceFailures.length ? `；部分来源读取失败：${sourceFailures.map(item => `${item.title}：${item.reason}`).join('；')}` : '';
    return { status, reason: `所选来源没有找到对应门店和日期的完整资料${failureReason}`, daily: [], missingDates: dates, sourceResults, sourceFailures };
  }
  const missingDates = daily.filter(row => row.status !== 'complete').map(row => row.date);
  const incompleteSourceTitles = [...new Set(daily.flatMap(row => row.missingSources || []))];
  const requestedRecentDays = plan.timeSpec?.kind === 'recent_complete_days' ? Number(plan.timeSpec.count || 3) : 0;
  const insufficientRecentDays = requestedRecentDays > 0 && daily.length < requestedRecentDays;
  const status = daily.length && daily.every(row => row.status === 'complete') && !insufficientRecentDays && !sourceFailures.length ? 'complete' : 'partial';
  const summary = plan.requestedOutcome?.kind === 'performance_summary' ? {
    kind: 'performance_summary',
    dates: available.map(row => row.date),
    first: available[0],
    last: available[available.length - 1],
    changes: Object.fromEntries([...new Set(available.flatMap(row => Object.keys(row.core)))].map(metric => {
      const first = Number(available[0].core[metric]);
      const last = Number(available[available.length - 1].core[metric]);
      return [metric, Number.isFinite(first) && Number.isFinite(last) ? { from: first, to: last, delta: round(last - first), direction: last > first ? 'up' : last < first ? 'down' : 'flat' } : null];
    }).filter(([, value]) => value))
  } : null;
  return {
    status, reason: [
      insufficientRecentDays ? `最近请求的 ${requestedRecentDays} 个完整自然日中只找到 ${daily.length} 个，未将不完整日期混入结论` : '',
      incompleteSourceTitles.length ? `部分来源资料缺失：${incompleteSourceTitles.join('、')}` : '',
      sourceFailures.length ? `部分来源读取失败：${sourceFailures.map(item => `${item.title}：${item.reason}`).join('；')}` : '',
    ].filter(Boolean).join('；'), date: dates.length === 1 ? dates[0] : undefined, dates, venue: plan.venue, venueId: plan.venueId,
    core: dates.length === 1 ? available.find(row => row.date === dates[0])?.core || {} : undefined,
    daily, missingDates, summary, sourceTitle: [...sourceResults.map(result => result.title), ...sourceFailures.map(result => result.title)].join('、'), sourceUrl: sourceResults.map(result => result.url).filter(Boolean),
    provenance: sourceResults, sourceFailures, fetchedAt: new Date(now).toISOString(), budget: { documents: sourceResults.length, sheets: sourceResults.reduce((sum, result) => sum + result.budget.sheets, 0), calls: sourceResults.reduce((sum, result) => sum + result.budget.calls, 0), modelReceivesRawRows: false },
    boundary: [...new Set(sourceResults.map(result => result.boundary).filter(Boolean))].join(' '), assumedYear: plan.assumedYear,
  };
}
