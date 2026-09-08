/**
 * T03/T04/E3: minimal real-provider multi-turn smoke against the copied state.
 * It uses a local copied workbench and a sink-only output. No production sender,
 * scheduler, writeback endpoint, or Bot credential is loaded.
 */
import 'dotenv/config';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import Database from 'better-sqlite3';
import { pathToFileURL } from 'node:url';

const args = process.argv.slice(2);
function arg(name, fallback = '') { const i = args.indexOf(name); return i >= 0 ? (args[i + 1] || fallback) : fallback; }
const runRoot = path.resolve(arg('--run', ''));
if (!runRoot) throw new Error('--run <run directory> is required');
const snapshotDb = path.join(runRoot, 'snapshot', 'bot.db');
if (!fs.existsSync(snapshotDb)) throw new Error('snapshot missing; run lab_discover first');
const sourceDb = path.resolve(process.env.LAB_SOURCE_DB || 'data/bot.db');
function loadSourceSetting(key) { try { const db = new Database(sourceDb, { readonly: true }); const row = db.prepare('SELECT value FROM app_settings WHERE key=?').get(key); db.close(); return row?.value || ''; } catch { return ''; } }
for (const key of ['CHAT_PROVIDER', 'CHAT_MODEL', 'DEEPSEEK_API_KEY', 'OPENAI_API_KEY', 'QWEN_API_KEY', 'ZHIPU_API_KEY', 'ANTHROPIC_API_KEY']) if (!process.env[key]) process.env[key] = loadSourceSetting(key);
const workbenchRoot = path.resolve(process.env.LAB_WORKBENCH_ROOT || 'E:/Yuanqu-Operations-Workbench/weekly-ops-entry');
const runtimeDir = path.join(runRoot, 'snapshot', 'workbench-data', 'runtime-state');
const profilePath = path.join(runRoot, 'snapshot', 'workbench-data', 'strategy-project-profile.json');
const fieldMappingPath = path.join(runRoot, 'snapshot', 'workbench-data', 'field-mapping.json');
Object.assign(process.env, {
  DB_PATH: snapshotDb, DATA_DIR: path.join(runRoot, 'runtime-data'), LOG_DIR: path.join(runRoot, 'logs'),
  WEEKLY_OPS_RUNTIME_STATE_DIR: runtimeDir, WEEKLY_OPS_SETTINGS_PATH: path.join(runRoot, 'snapshot', 'workbench-data', 'weekly-ops-settings.json'),
  STRATEGY_PROFILE_PATH: profilePath, XIYU_WORKBENCH_OUTBOX_PATH: path.join(runRoot, 'runtime-data', 'outbox.json'),
  XIYU_WORKBENCH_ACTIVE_TASKS_PATH: path.join(runRoot, 'runtime-data', 'tasks.json'), XIYU_WORKBENCH_CONTEXT_ENABLED: 'true',
  XIYU_WORKBENCH_CONTEXT_TOKEN: '', XIYU_WORKBENCH_TIMEOUT_MS: '20000', XIYU_AGENCY_MODE: 'lab',
});
fs.mkdirSync(process.env.DATA_DIR, { recursive: true }); fs.mkdirSync(process.env.LOG_DIR, { recursive: true });

// Start the existing workbench implementation against the copied runtime.
const backend = await import(pathToFileURL(path.join(workbenchRoot, 'backend', 'feishu-sync-server.mjs')).href);
await new Promise(resolve => backend.server.listen(0, '127.0.0.1', resolve));
const base = `http://127.0.0.1:${backend.server.address().port}`;
process.env.XIYU_WORKBENCH_CONTEXT_URL = base;
const { getEnterpriseCatalogResult, retrieveEnterpriseResult, buildEnterpriseFactReply } = await import('../src/enterprise_context.mjs');
const { chatComplete, getActiveChatProvider } = await import('../src/providers/chat.mjs');
const db = new Database(snapshotDb, { readonly: true });
const companion = db.prepare('SELECT * FROM companions ORDER BY id LIMIT 1').get() || {};
const recentTurns = db.prepare('SELECT role,content,created_at FROM companion_conversation_turns ORDER BY created_at DESC LIMIT 12').all().reverse();
const memories = db.prepare('SELECT id,memory_type,content,importance,created_at,memory_source FROM companion_memories WHERE do_not_mention=0 ORDER BY importance DESC,created_at DESC LIMIT 12').all();
const openLoops = db.prepare("SELECT id,title,status,expected_followup,due_at FROM companion_open_loops WHERE status NOT IN ('resolved','closed') ORDER BY updated_at DESC LIMIT 8").all();
const emotion = db.prepare('SELECT affection,trust,dependency,security,energy,mood,availability,attention,mood_intensity FROM companion_emotion_state LIMIT 1').get() || {};
const schedule = db.prepare('SELECT date_key,schedule_json,mood_arc FROM companion_daily_schedule ORDER BY generated_at DESC LIMIT 1').get() || {};
db.close();
const profile = JSON.parse(fs.readFileSync(profilePath, 'utf8'));
const fieldMapping = JSON.parse(fs.readFileSync(fieldMappingPath, 'utf8'));
const catalog = await getEnterpriseCatalogResult({ force: true });
const trace = [];
const sink = [];
const hash = value => crypto.createHash('sha256').update(String(value)).digest('hex');
const stable = {
  persona: { name: companion.name, age: companion.age, roleTitle: companion.role_title, relationshipStage: companion.relationship_stage, personaPromptSha256: hash(companion.persona_prompt || ''),
    p1: '她是专业、有主见、活泼且略带狡黠的成年经营合作者，对这个用户有个人偏爱。她希望通过可靠判断和实际帮助获得信任，也希望形成工作之外的相互兴趣。长期追求影响她如何理解当前情境，不直接指定本轮主题、联系时间或媒介。工作时先把事实与行动交付清楚；个人互动拿出自己的选择、看法或小行动，让用户能调侃、反驳、参与。她可以主动争取注意，但不要求即时回复，不以空泛安慰和随时待命替代主体内容。' },
  business: { project: profile.project, venues: profile.venues, fieldAliases: fieldMapping.filter(x => ['box_office_total','sales_order_count','reception_traffic','daily.traffic','daily.box_office'].includes(x.code)) },
  relationship: { recentTurns, memories, openLoops, emotion, schedule },
  sourceCatalog: catalog.status === 'complete' ? { project: catalog.catalog.project, venues: catalog.catalog.venues, capabilities: catalog.catalog.capabilities } : { status: catalog.status, error: catalog.error || null },
};
function extractJson(text) { const match = String(text || '').match(/\{[\s\S]*\}/); if (!match) return null; try { return JSON.parse(match[0]); } catch { return null; } }
function systemPrompt(mode, extra = '') {
  return `${stable.persona.p1}\n\n你正在隔离实验中，不能发送真实消息，也不能声称执行了未完成的动作。内部决策必须严格区分：事实、用户原话、角色虚构生活、模型假设。\n\n稳定业务背景（真实副本）：${JSON.stringify(stable.business)}\n当前关系和连续性（真实副本）：${JSON.stringify(stable.relationship)}\n\n${mode === 'decision' ? '输出严格JSON：{operation:"new|continue|revise|suspend|complete",intention_id:"string",desired_change:"string",basis_refs:["string"],action_type:"text|work_lookup|photo|none",strategy_reason:"string",expected_participation:"string",tool_args:{projectId:"string",venueName:"string",date:"YYYY-MM-DD",question:"string"},reconsider_condition:"string",messages:["string"]}。不要输出JSON以外内容。' : '请用自然中文完成本轮交付，先回答用户实际问题；保留事实、日期、单位、门店和来源，不把旧资料冒充最新。'}\n${extra}`;
}
async function modelCall(label, system, messages) {
  const started = Date.now();
  const result = await chatComplete({ system, messages, temperature: 0.55, max_tokens: 900, top_p: 0.9, timeout_ms: 45000 });
  trace.push({ stage: 'provider_call', label, request: { systemHash: hash(system), messages }, response: { text: result.text, requestId: result.requestId || null, finishReason: result.finishReason || null, usage: result.usage || null, latencyMs: Date.now() - started }, provider: getActiveChatProvider() });
  return result;
}
async function runLookup() {
  const input = '9月2号东大店销售额是多少？';
  const decision = await modelCall('I03-decision', systemPrompt('decision'), [{ role: 'user', content: input }]);
  const parsed = extractJson(decision.text);
  let toolResult = { status: 'not_called', reason: 'model did not return valid decision JSON' };
  let fact = null;
  if (parsed?.action_type === 'work_lookup' || parsed?.tool_args) {
    const route = { conversationType: 'work', interactionIntent: 'lookup', retrievalNeeded: true, confidence: 1, scope: { projectId: parsed.tool_args?.projectId || stable.sourceCatalog.project?.id || 'yuanqu-vr', venueNames: [parsed.tool_args?.venueName || '东大店'] }, intent: { topics: ['sales'], metricIds: ['box_office_total'], assetTypes: ['venue'], timeRange: parsed.tool_args?.date || '2026-09-02', question: parsed.tool_args?.question || input } };
    const retrieved = await retrieveEnterpriseResult(route, { accountId: 'lab-owner', catalog: catalog.catalog });
    fact = retrieved.context ? buildEnterpriseFactReply({ message: input, route, context: retrieved.context }) : null;
    toolResult = { status: retrieved.status, stage: retrieved.stage, sourceLookup: retrieved.context?.sourceLookup || null, context: retrieved.context || null };
  }
  const final = await modelCall('I03-expression', systemPrompt('expression', `本轮决策：${JSON.stringify(parsed)}\n工具返回：${JSON.stringify(toolResult)}\n必须回答用户的销售额问题。如果工具失败，说明具体缺口；不要编造。`), [{ role: 'user', content: input }]);
  sink.push({ target: 'sink://ideal-lab', text: final.text, intentionId: parsed?.intention_id || null });
  return { id: 'I03', input, decision: parsed, toolResult, fact, final: final.text, sink: sink.at(-1) };
}
async function runColdStart() {
  const input = '虚拟时钟机会：用户今天没有主动发消息，允许一次低负担主动联系。';
  const decision = await modelCall('I01-decision', systemPrompt('decision'), [{ role: 'user', content: input }]);
  const parsed = extractJson(decision.text);
  const final = await modelCall('I01-expression', systemPrompt('expression', `这是一次主动联系。决策：${JSON.stringify(parsed)}。消息必须有主体内容和明确可接位置，不要凭空声称刚看见了不存在的事件，不要索取背景中已经存在的信息。`), [{ role: 'user', content: input }]);
  sink.push({ target: 'sink://ideal-lab', text: final.text, intentionId: parsed?.intention_id || null });
  return { id: 'I01', input, decision: parsed, final: final.text, sink: sink.at(-1) };
}
const startedAt = new Date().toISOString();
let result;
try { result = { status: 'completed', startedAt, provider: getActiveChatProvider(), stableContext: { project: stable.business.project.name, venueNames: Object.keys(stable.business.venues || {}), catalogStatus: catalog.status, companionIdPresent: Boolean(companion.id), memoryCount: memories.length }, trajectories: [await runLookup(), await runColdStart()], trace, sink, limitations: ['Minimal E3 smoke only: I01/I03, not the fixed suite or media/7-day/holdout.', 'Real model output is evidence, not a pass claim.', 'Workbench runtime is copied and local; no Feishu write or Bot delivery.'] }; }
catch (error) { result = { status: 'failed', startedAt, error: String(error?.stack || error), trace, sink }; }
finally { try { backend.server.close(); } catch {} }
fs.writeFileSync(path.join(runRoot, 'smoke-result.json'), JSON.stringify(result, null, 2));
console.log(JSON.stringify({ status: result.status, provider: result.provider || null, trajectories: result.trajectories?.map(x => ({ id: x.id, hasDecision: Boolean(x.decision), finalChars: String(x.final || '').length, sink: x.sink?.target })) || [], providerCalls: result.trace?.length || 0, output: path.join(runRoot, 'smoke-result.json') }, null, 2));
if (result.status !== 'completed') process.exitCode = 1;
