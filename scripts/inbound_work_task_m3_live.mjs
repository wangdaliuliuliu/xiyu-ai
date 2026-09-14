/* M3 真实 DeepSeek + 完整网页入站回答链验收入口。
 * 先只读载入 data/bot.db 的 provider binding，再切换隔离 DB/state；
 * 只在真实 structured retrieve 已可用时发起一次两轮对话，避免旁接旧协议。
 * 不发送 Bot、不写生产，密钥不打印、不落盘。
 */
import 'dotenv/config';
import Database from 'better-sqlite3';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const sourceDbPath = path.resolve(process.env.XIYU_M3_SOURCE_DB || 'data/bot.db');
const m3ActorId = String(process.env.XIYU_M3_ACTOR_ID || 'm3-isolated-account');
const sourceDb = new Database(sourceDbPath, { readonly: true, fileMustExist: true });
const sourceSetting = key => sourceDb.prepare('SELECT value FROM app_settings WHERE key = ?').get(key)?.value || '';
for (const key of ['CHAT_PROVIDER', 'CHAT_MODEL', 'DEEPSEEK_API_KEY']) {
  if (!process.env[key]) {
    const value = sourceSetting(key);
    if (value) process.env[key] = value;
  }
}
const sourceBinding = {
  provider: String(process.env.CHAT_PROVIDER || '').toLowerCase() || 'deepseek',
  model: process.env.CHAT_MODEL || 'deepseek-chat',
  hasApiKey: Boolean(process.env.DEEPSEEK_API_KEY),
};
sourceDb.close();

const isolated = fs.mkdtempSync(path.join(os.tmpdir(), 'xiyu-inbound-m3-'));
Object.assign(process.env, {
  DB_PATH: path.join(isolated, 'bot.db'),
  DATA_DIR: isolated,
  LOG_DIR: path.join(isolated, 'logs'),
  XIYU_WORKBENCH_ACTIVE_TASKS_PATH: path.join(isolated, 'active-tasks.json'),
  XIYU_WORKBENCH_OUTBOX_PATH: path.join(isolated, 'outbox.json'),
  XIYU_WORKBENCH_CONTEXT_ENABLED: 'true',
  XIYU_WORK_CONTEXT_ROUTER_MAX_TOKENS: '900',
  PROVIDER_RETRY_MAX: '0',
});
fs.mkdirSync(process.env.LOG_DIR, { recursive: true });

function baseUrl() { return String(process.env.XIYU_WORKBENCH_CONTEXT_URL || 'http://127.0.0.1:4174').replace(/\/$/, ''); }

async function workbenchRequest(pathname, init = {}) {
  const token = process.env.XIYU_WORKBENCH_CONTEXT_TOKEN || '';
  const headers = { ...(token ? { 'x-xiyu-bridge-token': token } : {}), ...(init.headers || {}) };
  const response = await fetch(`${baseUrl()}${pathname}`, { ...init, headers });
  const text = await response.text();
  let body = null;
  try { body = JSON.parse(text); } catch {}
  if (!response.ok) throw new Error(`${response.status} ${text.slice(0, 300)}`);
  return body;
}

function isoDateOffset(date, offset) {
  return new Date(Date.parse(`${date}T00:00:00Z`) + offset * 86400000).toISOString().slice(0, 10);
}

async function structuredProbe() {
  const health = await workbenchRequest('/health');
  const catalogResponse = await workbenchRequest('/api/knowledge/catalog');
  const catalog = catalogResponse?.catalog;
  const venue = (catalog?.venues || []).find(item => item.name === '中影');
  if (!catalog?.project?.id || !venue?.id) throw new Error('structured probe catalog 缺少项目或中影实体');
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
  const body = { actorId: m3ActorId, projectId: catalog.project.id, scope: task.scope, task, query: { interactionIntent: 'lookup' }, limits: { maxItems: 20, maxCharacters: 16000 } };
  const retrieved = await workbenchRequest('/api/knowledge/retrieve', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  const lookup = retrieved?.context?.sourceLookup || null;
  const structuredResponseObserved = Boolean(lookup && ['complete', 'partial'].includes(lookup.status) && lookup.venue === venue.name && (lookup.dates || []).length >= 3 && (retrieved.context.items || []).some(item => item.refs?.length));
  return { health, catalog, venue, requestedDates, task, retrieved, lookup, structuredResponseObserved };
}

function summarizeDebug(result) {
  const debug = result?.enterpriseDebug || {};
  const route = debug.route || {};
  const task = route.task || {};
  const lookup = debug.context?.sourceLookup || debug.enterpriseResult?.context?.sourceLookup || null;
  return {
    reply: String(result?.reply || ''),
    enterprise: result?.enterprise || null,
    route: { conversationType: route.conversationType, taskTransition: route.taskTransition, confidence: route.confidence, retrievalNeeded: route.retrievalNeeded },
    task: { goal: task.goal, completeQuestion: task.completeQuestion, scope: task.scope, timeSpec: task.timeSpec, requestedOutcome: task.requestedOutcome, missingSlots: task.missingSlots },
    tool: { status: debug.enterpriseResult?.status || null, sourceStatus: lookup?.status || null, dates: lookup?.dates || [], venue: lookup?.venue || null, core: lookup?.core || null, daily: lookup?.daily || [], sourceTitle: lookup?.sourceTitle || '', sourceUrl: lookup?.sourceUrl || [], items: (debug.context?.items || []).map(item => ({ id: item.id, title: item.title, refs: item.refs || [] })) },
    factResult: debug.factResult ? { matched: debug.factResult.matched, status: debug.factResult.status, reply: debug.factResult.reply, requiredValues: debug.factResult.requiredValues || [], requiredTerms: debug.factResult.requiredTerms || [] } : null,
    outputOrigin: debug.finalResult?.outputOrigin || result?.enterprise?.outputOrigin || null,
  };
}

try {
  const provider = await import('../src/providers/chat.mjs');
  const active = provider.getActiveChatProvider();
  const configured = provider.isChatProviderConfigured(active.id);
  const preflight = { provider: active.id, model: active.model, endpointHost: provider.REGISTRY[active.id]?.baseURL ? new URL(provider.REGISTRY[active.id].baseURL).host : '', hasApiKey: configured, isolatedDb: process.env.DB_PATH, sourceDbBinding: sourceBinding, botMessagesSent: 0, productionWrites: 0 };
  if (active.id !== 'deepseek' || !configured) {
    console.log(JSON.stringify({ ok: false, milestone: 'M3', status: 'blocked', reason: active.id !== 'deepseek' ? '当前项目有效 provider 不是 DeepSeek，未擅自切换渠道' : '当前 DeepSeek API key 不可用，未发起计费请求', structuredResponseObserved: false, preflight, providerCalls: 0, budgetLimitCny: 1 }));
  } else {
    let probe;
    try { probe = await structuredProbe(); }
    catch (error) {
      console.log(JSON.stringify({ ok: false, milestone: 'M3', status: 'blocked', reason: 'structured_workbench_probe_error', structuredResponseObserved: false, error: String(error?.message || error), preflight, providerCalls: 0, budgetLimitCny: 1, botMessagesSent: 0, productionWrites: 0 }));
      process.exitCode = 0;
    }
    if (probe && !probe.structuredResponseObserved) {
      console.log(JSON.stringify({ ok: false, milestone: 'M3', status: 'blocked', reason: 'structured_live_workbench_not_ready', structuredResponseObserved: false, endpoint: baseUrl(), catalogVenue: probe.venue?.id || null, requestedDates: probe.requestedDates, preflight, providerCalls: 0, budgetLimitCny: 1, botMessagesSent: 0, productionWrites: 0 }));
    } else if (probe?.structuredResponseObserved) {
      const { getDb, getCompanionById, patchCompanion } = await import('../src/db.mjs');
      const { playgroundChat } = await import('../src/playground.mjs');
      const { withAiAudit } = await import('../src/ai.mjs');
      const db = getDb();
      const companionId = Number(db.prepare('INSERT INTO companions(user_id,bot_id,name) VALUES(NULL,?,?)').run('m3-inbound-probe', '溪语').lastInsertRowid);
      patchCompanion(companionId, { age: 24, role_title: '专业又亲近的经营助理', current_scene: '办公室', relationship_stage: '暧昧', affection_level: 60, memory_enabled: 0, max_tokens: 700, temperature: 0.25, persona_prompt: '你是一个专业、自然、对用户有偏爱的成年经营助理。明确工作问题要先认真交付，再保留自然的人格。' });
      const accountId = m3ActorId;
      const firstMessage = '帮我看看最近业绩怎么样啊';
      const secondMessage = '最近这几天中影的';
      const trace = [];
      const turns = await withAiAudit(event => trace.push(event), async () => {
        const first = await playgroundChat(getCompanionById(companionId), firstMessage, { probe: true, probeEnterprise: true, accountId });
        const second = await playgroundChat(getCompanionById(companionId), secondMessage, { probe: true, probeEnterprise: true, accountId });
        return { first, second };
      });
      db.close();
      const first = summarizeDebug(turns.first);
      const second = summarizeDebug(turns.second);
      const providerCalls = trace.filter(event => event.stage === 'provider_request').length;
      const secondFact = second.factResult;
      const secondReply = second.reply.trim();
      const noFalseAccessClaim = !/看不到|无法访问|没有工作台|看不到你的工作台/.test(secondReply);
      const visibleReply = secondReply.length > 0 && !/^(?:\{[\s\S]*\}|任务帧|taskTransition)/.test(secondReply);
      const compactSummary = secondReply.length >= 220 && secondReply.length <= 380;
      const sourceMentionCount = (secondReply.match(/运营渠道日销售来源表/g) || []).length;
      const missingDataMentionCount = (secondReply.match(/资料未覆盖/g) || []).length;
      const noMisleadingTrafficBoundary = !/来源为录入客流/.test(secondReply);
      const noStableTrendClaim = !/稳定增长|稳定趋势/.test(secondReply);
      const compactFactsPresent = ['9/9', '9/10', '9/11', '0元', '261.9元', '510.7元', '0张', '3张', '4张'].every(value => secondReply.includes(value));
      const grounded = Boolean(second.tool.sourceStatus && ['complete', 'partial'].includes(second.tool.sourceStatus) && second.tool.items.length > 0 && secondFact?.matched && secondFact.requiredValues.length > 0);
      const { factReplyPreservesValues } = await import('../src/enterprise_context.mjs');
      const factsPreserved = Boolean(secondFact?.matched && factReplyPreservesValues(secondReply, secondFact));
      const noInventedVenue = !/(?:北京|上海|广州)/.test(secondReply);
      const status = second.route.taskTransition === 'continue' && second.task.scope?.venueIds?.includes('ZHONGYING') && second.task.missingSlots?.length === 0 && first.reply.trim().length > 0 && visibleReply && compactSummary && sourceMentionCount === 1 && missingDataMentionCount === 1 && noMisleadingTrafficBoundary && noStableTrendClaim && compactFactsPresent && grounded && factsPreserved && noFalseAccessClaim && noInventedVenue ? 'passed' : 'failed';
      console.log(JSON.stringify({ ok: status === 'passed', milestone: 'M3', status, structuredResponseObserved: true, preflight, providerCalls, budgetLimitCny: 1, naturalLanguage: { first: firstMessage, second: secondMessage }, visibleReplies: { first: first.reply, second: second.reply }, first: { route: first.route, task: first.task, tool: first.tool, outputOrigin: first.outputOrigin }, second: { route: second.route, task: second.task, tool: second.tool, factResult: second.factResult, outputOrigin: second.outputOrigin }, assertions: { secondTaskContinued: second.route.taskTransition === 'continue', catalogVenueOnly: second.task.scope?.venueIds?.includes('ZHONGYING') === true, secondReplyNonEmpty: visibleReply, compactSummary, sourceMentionCount, missingDataMentionCount, noMisleadingTrafficBoundary, noStableTrendClaim, compactFactsPresent, groundedToolResult: grounded, factsPreserved, noFalseAccessClaim, noInventedVenue }, botMessagesSent: 0, productionWrites: 0 }));
    }
  }
} catch (error) {
  console.log(JSON.stringify({ ok: false, milestone: 'M3', status: 'blocked', reason: String(error?.message || error), structuredResponseObserved: false, sourceDbBinding: sourceBinding, providerCalls: 0, budgetLimitCny: 1, botMessagesSent: 0, productionWrites: 0 }));
} finally {
  try { const { getDb } = await import('../src/db.mjs'); getDb().close(); } catch {}
  try { fs.rmSync(isolated, { recursive: true, force: true }); } catch {}
}
