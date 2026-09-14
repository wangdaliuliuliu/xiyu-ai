/* M2 真实工作台 structured 只读 probe。
 * 只访问现有 4174，不启动副本、不调用写接口；legacy compatibility
 * 只保留在历史证据中，不能作为本入口的新协议通过条件。
 */
import 'dotenv/config';

const base = String(process.env.XIYU_WORKBENCH_CONTEXT_URL || 'http://127.0.0.1:4174').replace(/\/$/, '');
const token = process.env.XIYU_WORKBENCH_CONTEXT_TOKEN || '';
const headers = token ? { 'x-xiyu-bridge-token': token } : {};

async function request(pathname, init = {}) {
  const response = await fetch(`${base}${pathname}`, { ...init, headers: { ...headers, ...(init.headers || {}) } });
  const text = await response.text();
  let body = null;
  try { body = JSON.parse(text); } catch {}
  if (!response.ok) throw new Error(`${response.status} ${text.slice(0, 300)}`);
  return body;
}

function isoDateOffset(date, offset) {
  return new Date(Date.parse(`${date}T00:00:00Z`) + offset * 86400000).toISOString().slice(0, 10);
}

function summarizeLookup(body) {
  const lookup = body?.context?.sourceLookup || null;
  const items = (body?.context?.items || []).filter(item => String(item.id || '').startsWith('source:')).map(item => {
    let summary = {};
    try { summary = JSON.parse(item.summary || '{}'); } catch {}
    return { id: item.id, title: item.title, periodStart: summary.periodStart || null, core: summary.core || null, refs: item.refs || [] };
  });
  return {
    status: lookup?.status || null,
    dates: lookup?.dates || (lookup?.date ? [lookup.date] : []),
    venue: lookup?.venue || null,
    core: lookup?.core || null,
    sourceStatus: lookup?.status || null,
    sourceTitle: lookup?.sourceTitle || '',
    sourceUrl: lookup?.sourceUrl || [],
    missingInformation: body?.context?.missingInformation || [],
    items,
  };
}

try {
  const health = await request('/health');
  const catalogResponse = await request('/api/knowledge/catalog');
  const catalog = catalogResponse?.catalog;
  const venue = (catalog?.venues || []).find(item => item.name === '中影');
  if (!catalog?.project?.id || !venue?.id) throw new Error('catalog 中没有找到授权项目或“中影”实体');
  const today = new Date(Date.now() + 8 * 3600000).toISOString().slice(0, 10);
  const requestedDates = [isoDateOffset(today, -3), isoDateOffset(today, -2), isoDateOffset(today, -1)];
  const metricIds = ['box_office_total', 'sales_order_count', 'venue_traffic', 'reach_count', 'conversion_count'];
  const task = {
    goal: '判断中影近期经营表现',
    completeQuestion: `请结合中影最近三个完整自然日（${requestedDates.join('、')}）的真实资料说明经营表现`,
    scope: { projectId: catalog.project.id, venueIds: [venue.id] },
    timeSpec: { kind: 'recent_complete_days', count: 3 },
    requestedOutcome: { kind: 'performance_summary', businessMeaning: '判断近期经营表现', metricIds },
    businessMeaning: '判断近期经营表现', metricIds, missingSlots: [],
  };
  const structuredBody = { actorId: 'readonly-m2-probe', projectId: catalog.project.id, scope: task.scope, task, query: { interactionIntent: 'lookup' }, limits: { maxItems: 20, maxCharacters: 16000 } };
  const structured = summarizeLookup(await request('/api/knowledge/retrieve', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(structuredBody) }));
  const grounded = Boolean(structured.sourceStatus && ['complete', 'partial'].includes(structured.sourceStatus) && structured.venue === venue.name && structured.dates.length >= 3 && structured.items.length >= 3 && structured.items.every(item => item.refs?.length));
  console.log(JSON.stringify({ ok: grounded, milestone: 'M2', status: grounded ? 'passed' : 'blocked', mode: 'structured', structuredResponseObserved: grounded, endpoint: base, health: { configured: health?.configured, sourceConfigured: health?.sourceConfigured, workbook: health?.workbook }, catalog: { projectId: catalog.project.id, venueId: venue.id, venueName: venue.name }, requestedDates, structured, groundedItems: structured.items.length, writeCalls: 0, legacyCompatibilityAvailable: true, note: grounded ? '' : '当前 4174 返回旧 context 协议；legacy compatibility 旁证不计入本入口通过。' }));
} catch (error) {
  console.log(JSON.stringify({ ok: false, milestone: 'M2', status: 'blocked', reason: 'workbench_network_or_protocol_error', endpoint: base, error: String(error?.message || error), writeCalls: 0 }));
}
