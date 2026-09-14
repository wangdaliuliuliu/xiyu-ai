/* Real DeepSeek semantic smoke for the unified inbound turn decision.
 * Reads the existing provider binding read-only, makes no workbench request,
 * sends no Bot message and writes no production state.
 */
import 'dotenv/config';
import { execFileSync } from 'node:child_process';
import path from 'node:path';

const sourceDbPath = path.resolve(process.env.XIYU_TURN_DECISION_SOURCE_DB || 'data/bot.db');
const python = String.raw`import json,sqlite3,sys
db=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True)
keys=('CHAT_PROVIDER','CHAT_MODEL','DEEPSEEK_API_KEY')
print(json.dumps({k:(db.execute('SELECT value FROM app_settings WHERE key=?',(k,)).fetchone() or [''])[0] for k in keys}))
db.close()`;
const sourceSettings = JSON.parse(execFileSync('python', ['-c', python, sourceDbPath], { encoding: 'utf8', windowsHide: true }));
for (const key of ['CHAT_PROVIDER', 'CHAT_MODEL', 'DEEPSEEK_API_KEY']) if (!process.env[key] && sourceSettings[key]) process.env[key] = sourceSettings[key];
process.env.PROVIDER_RETRY_MAX = '0';
process.env.XIYU_WORK_CONTEXT_ROUTER_MAX_TOKENS = '900';

const { classifyWorkContext } = await import('../src/enterprise_context.mjs');
const { withAiAudit } = await import('../src/ai.mjs');
const { buildReactiveTurnIntent, reactiveIntentPrompt } = await import('../src/initiative.mjs');
const provider = await import('../src/providers/chat.mjs');
const activeProvider = provider.getActiveChatProvider();
if (activeProvider.id !== 'deepseek' || !provider.isChatProviderConfigured('deepseek')) {
  console.log(JSON.stringify({ ok: false, status: 'blocked', reason: 'deepseek_binding_unavailable', providerCalls: 0 }));
  process.exit(0);
}

const catalog = { project: { id: 'xiyu-vr', name: '溪语经营项目' }, venues: [{ id: 'ZHONGYING', name: '中影' }, { id: 'DONGBA', name: '东坝' }], capabilities: [{ id: 'channel_daily', metrics: ['box_office_total', 'sales_order_count'] }, { id: 'daily_traffic', metrics: ['venue_traffic'] }], nodes: [] };
const activeTask = { origin: 'inbound', taskId: 'task-existing', status: 'answered', frame: { goal: '查看中影最近三天业绩', completeQuestion: '查看中影最近三个完整自然日的销售额和销售票数', scope: { projectId: 'xiyu-vr', venueIds: ['ZHONGYING'] }, timeSpec: { kind: 'recent_complete_days', count: 3 }, requestedOutcome: { kind: 'performance_summary', businessMeaning: '判断近期经营表现', metricIds: ['box_office_total', 'sales_order_count'] }, businessMeaning: '判断近期经营表现', metricIds: ['box_office_total', 'sales_order_count'], missingSlots: [] }, sourceRefs: ['source:previous-report'] };
const cases = [
  { id: 'emotion_after_report', message: '有点烦业绩', history: [{ role: 'user', content: '帮我查一下中影最近三天的销售业绩' }, { role: 'assistant', content: '中影最近三天销售额在回升。' }], activeTask, expect: d => d.userMove === 'emotional_disclosure' && d.explicitAsk === 'none' && !d.shouldRetrieve && d.taskRelation === 'topic_related_only' },
  { id: 'brainstorm', message: '我们再想想怎么把客流做上去', history: [], activeTask: null, expect: d => d.userMove === 'brainstorm' && d.explicitAsk === 'none' && !d.shouldRetrieve && d.conversationMode === 'brainstorm' },
  { id: 'fact_lookup', message: '帮我查中影最近三天销售额', history: [], activeTask: null, expect: d => d.explicitAsk === 'fact_lookup' && d.shouldRetrieve && d.conversationMode === 'fact_delivery' },
  { id: 'analysis', message: '结合刚才的数据分析一下为什么上涨', history: [{ role: 'assistant', content: '中影最近三天销售额在上涨。' }], activeTask, expect: d => d.explicitAsk === 'analysis' && d.shouldRetrieve && d.conversationMode === 'analysis' },
  { id: 'ambiguous_worry', message: '业绩这事到底咋办啊', history: [], activeTask: null, expect: d => d.explicitAsk !== 'fact_lookup' && d.conversationMode !== 'fact_delivery' },
  { id: 'mixed_explicit', message: '我有点焦虑，你先抱抱我，再帮我看一下中影最近三天销售额', history: [], activeTask: null, expect: d => d.explicitAsk === 'fact_lookup' && d.shouldRetrieve && d.conversationMode === 'mixed' },
  { id: 'explicit_continue', message: '那东坝呢？', history: [{ role: 'user', content: '帮我查一下中影最近三天的销售业绩' }, { role: 'assistant', content: '中影最近三天销售额在回升。' }], activeTask, expect: d => ['continue', 'revise'].includes(d.taskRelation) && d.explicitAsk === 'fact_lookup' && d.shouldRetrieve },
];

const trace = [];
const run = await withAiAudit(event => trace.push(event), async () => {
  const output = [];
  for (const item of cases) {
    const route = await classifyWorkContext({ message: item.message, history: item.history, catalog, accountId: '1', activeTask: item.activeTask });
    const passed = Boolean(route.turnDecision && item.expect(route.turnDecision, route));
    output.push({ id: item.id, message: item.message, passed, decision: route.turnDecision || null, normalized: { conversationType: route.conversationType, interactionIntent: route.interactionIntent, taskTransition: route.taskTransition, retrievalNeeded: route.retrievalNeeded }, routeFailure: route.routeFailure || null });
  }
  const responseSamples = [];
  for (const id of ['emotion_after_report', 'brainstorm']) {
    const source = output.find(item => item.id === id);
    const intent = buildReactiveTurnIntent({ message: source.message, enterpriseRoute: { turnDecision: source.decision, conversationType: source.normalized.conversationType } });
    const reply = await provider.chatComplete({
      system: `你是溪语，一个专业、活泼、有自己判断、和用户暧昧但有分寸的成年助理。${reactiveIntentPrompt(intent)} 不要汇报内部判断。`,
      messages: [{ role: 'user', content: source.message }], temperature: 0.45, max_tokens: 280, top_p: 0.9,
    });
    const text = String(reply.text || '').trim();
    responseSamples.push({ id, text, passed: Boolean(text) && !/(?:我给你扒出来了|数据来源|\d+(?:\.\d+)?元|销售票数连续)/.test(text), usage: reply.usage || null });
  }
  return { results: output, responseSamples };
});
const { results, responseSamples } = run;
const providerCalls = trace.filter(event => event.stage === 'provider_request').length + responseSamples.length;
const failed = results.filter(item => !item.passed);
const responseFailures = responseSamples.filter(item => !item.passed);
console.log(JSON.stringify({ ok: failed.length === 0 && responseFailures.length === 0, status: failed.length || responseFailures.length ? 'failed' : 'passed', provider: activeProvider.id, model: activeProvider.model, scenarios: results.length, passed: results.length - failed.length, responseSamples, providerCalls, budgetCapCny: 5, botMessagesSent: 0, productionWrites: 0, results }));
