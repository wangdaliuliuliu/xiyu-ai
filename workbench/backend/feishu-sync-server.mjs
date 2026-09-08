import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { createCognitionSourcePort } from './cognition/source-port.mjs';
import { compileEnterpriseContext } from './cognition/context-compiler.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TARGET_PATH = process.env.WEEKLY_OPS_TARGET_PATH || path.join(ROOT, 'data', 'feishu-target.json');
const TARGET_EXAMPLE_PATH = path.join(ROOT, 'data', 'feishu-target.example.json');
function readTargetConfig() {
  for (const candidate of [TARGET_PATH, TARGET_EXAMPLE_PATH]) {
    try {
      return JSON.parse(fs.readFileSync(candidate, 'utf8'));
    } catch {
      // Try the next candidate so a clean checkout can start without secrets.
    }
  }
  throw new Error(`工作台目标表配置不存在：${TARGET_PATH}`);
}
const TARGET = readTargetConfig();
const STRATEGY_PROMPT_PATH = path.join(ROOT, 'backend', 'strategy-workbench-prompts-v1.json');
const WEEKLY_PROMPT_PATH = path.join(ROOT, 'backend', 'weekly-review-prompts-v6.json');
const STRATEGY_SCHEMA_PATH = path.join(ROOT, 'backend', 'strategy-workbench-schema.json');
const STRATEGY_KNOWLEDGE_PATH = path.join(ROOT, 'backend', 'strategy-knowledge-v1.json');
const STRATEGY_PROFILE_PATH = process.env.STRATEGY_PROFILE_PATH || path.join(ROOT, 'data', 'strategy-project-profile.json');
const DAILY_PROMPT_PATH = path.join(ROOT, 'backend', 'daily-operating-prompts-v2.json');
const DAILY_SCHEMA_PATH = path.join(ROOT, 'backend', 'daily-operating-schema-v2.json');
const DAILY_LENSES_PATH = path.join(ROOT, 'data', 'idea-lenses-v1.json');
const KNOWLEDGE_GAP_PROMPT_PATH = path.join(ROOT, 'backend', 'knowledge-map-prompts-v2.json');
const DAILY_CONTEXT_VERSION = 'daily-context-v3';
const ENV_PATH = path.join(ROOT, 'backend', '.env');
if (fs.existsSync(ENV_PATH)) {
  for (const line of fs.readFileSync(ENV_PATH, 'utf8').split(/\r?\n/)) {
    const match = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/);
    if (match && !process.env[match[1]]) process.env[match[1]] = match[2].replace(/^['"]|['"]$/g, '');
  }
}
const SETTINGS_PATH = process.env.WEEKLY_OPS_SETTINGS_PATH || path.join(ROOT, 'data', 'weekly-ops-settings.json');
const RUNTIME_STATE_DIR = process.env.WEEKLY_OPS_RUNTIME_STATE_DIR || path.join(ROOT, 'data', 'runtime-state');
const RUNTIME_STATE_FILES = {
  records: path.join(RUNTIME_STATE_DIR, 'records.json'),
  reports: path.join(RUNTIME_STATE_DIR, 'reports.json'),
  workbench: path.join(RUNTIME_STATE_DIR, 'workbench.json'),
  experiences: path.join(RUNTIME_STATE_DIR, 'experiences.json'),
  daily: path.join(RUNTIME_STATE_DIR, 'daily.json'),
  ideas: path.join(RUNTIME_STATE_DIR, 'ideas.json'),
  interactions: path.join(RUNTIME_STATE_DIR, 'interactions.json'),
  intelligence: path.join(RUNTIME_STATE_DIR, 'intelligence.json'),
  knowledge: path.join(RUNTIME_STATE_DIR, 'knowledge.json'),
  events: path.join(RUNTIME_STATE_DIR, 'enterprise-events.json'),
  // 订单系统汇总表的检查结果只作为运行态审计，不改变周报/经营事实。
  order_monitor: path.join(RUNTIME_STATE_DIR, 'order-table-monitor.json')
};
const PORT = Number(process.env.WEEKLY_OPS_PORT || 4174);
const HOST = process.env.WEEKLY_OPS_HOST || '127.0.0.1';
// 溪语经营知识桥：本地开发可不设 token；线上建议设置后由服务端调用。
const XIYU_CONTEXT_TOKEN = process.env.XIYU_CONTEXT_TOKEN || '';
const XIYU_ACCESS_PATH = process.env.XIYU_ACCESS_PATH || path.join(ROOT, 'data', 'xiyu-enterprise-access.json');
const XIYU_AUDIT_PATH = process.env.XIYU_AUDIT_PATH || path.join(RUNTIME_STATE_DIR, 'xiyu-knowledge-audit.jsonl');
// Thinking models spend part of their completion budget on reasoning_content.
// Keep enough room for the user-visible JSON, but cap retries so one request
// cannot hang the local/serverless process indefinitely.
const MODEL_REQUEST_TIMEOUT_MS = Number(process.env.MODEL_REQUEST_TIMEOUT_MS || 90000);
const MODEL_TOTAL_TIMEOUT_MS = Number(process.env.MODEL_TOTAL_TIMEOUT_MS || 120000);
const MODEL_MAX_TOKENS = Number(process.env.MODEL_MAX_TOKENS || 12000);
const API_BASE = (process.env.FEISHU_API_BASE || 'https://open.feishu.cn/open-apis').replace(/\/$/, '');
const APP_ID = process.env.FEISHU_APP_ID || '';
const APP_SECRET = process.env.FEISHU_APP_SECRET || '';
const SPREADSHEET_TOKEN = process.env.FEISHU_SPREADSHEET_TOKEN || TARGET.workbook.token;
const SOURCE_SPREADSHEET_TOKEN = process.env.FEISHU_SOURCE_SPREADSHEET_TOKEN || '';
const SOURCE_WORKBOOK_URL = SOURCE_SPREADSHEET_TOKEN ? `https://my.feishu.cn/sheets/${SOURCE_SPREADSHEET_TOKEN}` : '';
const SOURCE_SHEETS = {
  东坝: { 大麦: 'blleCP', 开店宝: 'fxP3Ly', 抖音: '2qL092', 猫眼: 'N6Enef', 小程序: '0yiVWO' },
  中影: { 大麦: '6e8e61', 开店宝: 'nvRqzG', 抖音: 'DGhI6G', 猫眼: 'zOBuCl', 小程序: 'jqH72d' }
};
const VENUES = { 东坝: 'DONGBA', 中影: 'ZHONGYING' };
let tokenCache = null;

const DEFAULT_SETTINGS = {
  weekStart: 1,
  weekLength: 7,
  timezone: 'Asia/Shanghai',
  periodSeparator: '_',
  syncMode: 'api',
  reportProvider: 'local',
  reportApiEndpoint: process.env.MODEL_API_ENDPOINT || '',
  reportModel: process.env.MODEL_NAME || '',
  thinkingEnabled: true,
  thinkingTasks: ['weekly_signal', 'causal_dialogue', 'weekly_synthesis', 'strategy_node', 'tactic_plan']
};

const THINKING_TASK_KEYS = new Set(['weekly_report', 'weekly_signal', 'causal_dialogue', 'weekly_synthesis', 'strategy_node', 'tactic_plan', 'validation', 'daily_brief', 'idea_generation']);

function readSettings() {
  try {
    const stored = JSON.parse(fs.readFileSync(SETTINGS_PATH, 'utf8'));
    return { ...DEFAULT_SETTINGS, ...(stored && typeof stored === 'object' ? stored : {}) };
  } catch {
    return { ...DEFAULT_SETTINGS, reportApiKey: process.env.MODEL_API_KEY || '' };
  }
}

function writeSettings(next) {
  fs.mkdirSync(path.dirname(SETTINGS_PATH), { recursive: true });
  const tempPath = `${SETTINGS_PATH}.tmp`;
  fs.writeFileSync(tempPath, JSON.stringify(next, null, 2), 'utf8');
  fs.renameSync(tempPath, SETTINGS_PATH);
}

function publicSettings(settings = readSettings()) {
  const { reportApiKey, ...safe } = settings;
  return { ...safe, reportApiKeyConfigured: Boolean(reportApiKey) };
}

function runtimeStateKind(value) {
  const kind = String(value || '').trim();
  return Object.prototype.hasOwnProperty.call(RUNTIME_STATE_FILES, kind) ? kind : '';
}

function readRuntimeState(kind) {
  const file = RUNTIME_STATE_FILES[kind];
  try {
    const stat = fs.statSync(file);
    const parsed = JSON.parse(fs.readFileSync(file, 'utf8'));
    if (parsed && parsed.__runtimeState === 1) return { data: parsed.data, revision: Number(parsed.revision || 0), updatedAt: stat.mtime.toISOString() };
    return { data: parsed, revision: 0, updatedAt: stat.mtime.toISOString() };
  } catch {
    return { data: kind === 'records' ? [] : {}, revision: 0, updatedAt: '' };
  }
}

function writeRuntimeState(kind, data, expectedRevision = null) {
  const current = readRuntimeState(kind);
  if (expectedRevision !== null && Number(expectedRevision) !== current.revision) {
    const error = new Error('运行数据版本已变化，请刷新后再保存');
    error.code = 'RUNTIME_STATE_CONFLICT';
    error.current = current;
    throw error;
  }
  const payload = data && typeof data === 'object' ? structuredClone(data) : (kind === 'records' ? [] : {});
  const revision = current.revision + 1;
  fs.mkdirSync(RUNTIME_STATE_DIR, { recursive: true });
  const file = RUNTIME_STATE_FILES[kind];
  const tempPath = `${file}.tmp`;
  fs.writeFileSync(tempPath, JSON.stringify({ __runtimeState: 1, revision, data: payload }, null, 2), 'utf8');
  fs.renameSync(tempPath, file);
  return { data: payload, revision, updatedAt: new Date().toISOString() };
}

function readJsonFile(file, fallback) {
  try {
    const parsed = JSON.parse(fs.readFileSync(file, 'utf8'));
    return parsed && typeof parsed === 'object' ? parsed : fallback;
  } catch {
    return fallback;
  }
}

function dailyStateValue() {
  const state = readRuntimeState('daily').data;
  if (!state || typeof state !== 'object' || Array.isArray(state)) return { schemaVersion: 'daily-operating-v1', snapshots: {}, briefs: {}, updatedAt: '' };
  return {
    schemaVersion: 'daily-operating-v1',
    snapshots: state.snapshots && typeof state.snapshots === 'object' ? state.snapshots : {},
    briefs: state.briefs && typeof state.briefs === 'object' ? state.briefs : {},
    updatedAt: String(state.updatedAt || '')
  };
}

function ideaStateValue() {
  const state = readRuntimeState('ideas').data;
  if (!state || typeof state !== 'object' || Array.isArray(state)) return { schemaVersion: 'idea-feed-v1', items: [], updatedAt: '' };
  return { schemaVersion: 'idea-feed-v1', items: Array.isArray(state.items) ? state.items : [], updatedAt: String(state.updatedAt || '') };
}

function interactionStateValue() {
  const state = readRuntimeState('interactions').data;
  if (!state || typeof state !== 'object' || Array.isArray(state)) return { schemaVersion: 'idea-interactions-v1', items: [], updatedAt: '' };
  return { schemaVersion: 'idea-interactions-v1', items: Array.isArray(state.items) ? state.items : [], updatedAt: String(state.updatedAt || '') };
}

function dailyIsoNow() {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
}

function shanghaiDateKey(value) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '';
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(parsed);
}

function dailyVenueName(value) {
  const raw = String(value || '').trim();
  if (!raw || raw === 'all' || raw === 'project') return 'all';
  const profile = readStrategyProfile();
  const names = Object.keys(profile.venues || {});
  return names.includes(raw) ? raw : (Object.entries(VENUES).find(([, id]) => id === raw)?.[0] || raw);
}

function dailyVenueId(name) {
  if (name === 'all') return 'all';
  const profile = readStrategyProfile();
  return String(profile.venues?.[name]?.venueId || VENUES[name] || name).toUpperCase();
}

function dailyVenueNames(scope = 'all') {
  const profile = readStrategyProfile();
  const names = Object.keys(profile.venues || {});
  const available = names.length ? names : Object.keys(VENUES);
  const venue = dailyVenueName(scope);
  return venue === 'all' ? available : [venue];
}

function dailyNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function dailyChange(current, previous) {
  const c = dailyNumber(current), p = dailyNumber(previous);
  if (c === null || p === null || p === 0) return null;
  return (c - p) / Math.abs(p) * 100;
}

function dailyRecordRows(venue = 'all') {
  const rows = readRuntimeState('records').data;
  if (!Array.isArray(rows)) return [];
  return rows.filter(row => row && row.status !== 'deleted' && !/^2099-/.test(String(row.periodStart || '')) && (venue === 'all' || row.venue === venue))
    .sort((a, b) => String(b.periodStart || '').localeCompare(String(a.periodStart || '')));
}

function dailyFactsFromReports(venue = 'all') {
  const reports = readRuntimeState('reports').data;
  if (!reports || typeof reports !== 'object') return [];
  return Object.entries(reports).sort(([a], [b]) => b.localeCompare(a)).slice(0, 8).flatMap(([periodId, report]) => {
    const context = report?.context || {};
    const values = [context.events, context.execution, context.reasons, context.resultEvidence, context.nextValidation]
      .map(value => String(value || '').trim()).filter(Boolean);
    return values.filter(text => !/E2E测试|请勿用于正式经营分析|仅用于流程验证/.test(text))
      .map(text => ({ id: `fact:${periodId}:${text.slice(0, 30)}`, periodId, venue, text, sourceType: 'operating_fact' }));
  });
}

function dailyOpenIssues(venue = 'all') {
  const wb = readRuntimeState('workbench').data;
  const cache = wb?.analysisCache && typeof wb.analysisCache === 'object' ? wb.analysisCache : {};
  const issues = [];
  Object.entries(cache).forEach(([key, value]) => {
    if (!value || typeof value !== 'object') return;
    const keyVenue = key.split('|')[1] || 'all';
    if (venue !== 'all' && keyVenue !== 'all' && keyVenue !== venue) return;
    (value.expertSignals || value.signals || []).forEach(signal => {
      if (!signal || signal.include === false) return;
      issues.push({ id: signal.id || `signal:${key}:${signal.title || ''}`, title: String(signal.title || signal.observation || '待观察经营信号'), status: signal.status || 'observing', priority: signal.priority || 'medium', hypothesis: signal.hypothesis || '', evidenceRefs: Array.isArray(signal.evidenceRefs) ? signal.evidenceRefs : [], sourceKey: key });
    });
  });
  return issues.slice(0, 12);
}

function dailyActiveValidations(venue = 'all') {
  const wb = readRuntimeState('workbench').data;
  const plans = Array.isArray(wb?.tacticPlans) ? wb.tacticPlans : [];
  return plans.filter(plan => ['ready', '执行中', '待评估'].includes(plan.status) && (venue === 'all' || plan.venue === 'all' || plan.venue === venue)).slice(0, 8).map(plan => ({
    id: plan.id,
    title: String(plan.tacticTitle || plan.title || '未命名打法'),
    status: plan.status,
    progress: Number(plan.progress || 0),
    metric: String(plan.metric || plan.targetMetric || plan.generated?.measurableGoal?.metric || ''),
    startDate: plan.startDate || '',
    evaluationDate: plan.evaluationDate || '',
    nextAction: plan.nextAction || ''
  }));
}

function dailyPublishedExperiences(venue = 'all') {
  const state = readRuntimeState('experiences').data;
  const items = Array.isArray(state?.items) ? state.items : [];
  return items.filter(item => item?.retrievalEligible === true && item?.status === 'published' && (venue === 'all' || item.venue === 'all' || item.venue === venue)).slice(0, 12).map(item => ({
    id: item.id,
    title: String(item.title || ''),
    reusable: String(item.reusable || ''),
    applicability: String(item.applicability || ''),
    evidence: String(item.evidence || '')
  }));
}

function dailyContext({ date = dailyIsoNow(), venue = 'all' } = {}) {
  const venueName = dailyVenueName(venue);
  const profile = readStrategyProfile();
  const records = dailyRecordRows(venueName).slice(0, 8);
  const currentPeriodAvailable = records.some(row => String(row.periodStart || '') <= date && String(row.periodEnd || '') >= date);
  const snapshots = dailyStateValue().snapshots;
  const snapshotItems = Object.values(snapshots).filter(item => item?.date <= date && (venueName === 'all' || item.venue === venueName)).sort((a, b) => String(b.date).localeCompare(String(a.date))).slice(0, 14);
  const current = records.slice(0, 4).map(row => ({ periodId: row.periodId, venue: row.venue, periodStart: row.periodStart, periodEnd: row.periodEnd, core: row.core || {}, daily: row.daily || [], sourceRefs: row.sourceRefs || [] }));
  const facts = dailyFactsFromReports(venueName).slice(0, 16);
  const confirmedAssets = (readRuntimeState('workbench').data?.intelligenceAssets || []).filter(item => item.status === 'confirmed' && item.targetType !== 'experience' && normalizeScopeVenueNames(item.scope || {}, profile).some(name => venueName === 'all' || name === venueName)).slice(-20);
  const context = {
    schemaVersion: 'operating-context-v1',
    scope: { projectId: profile.project?.name || 'yuanqu-vr', venue: venueName, venueId: dailyVenueId(venueName), asOf: date },
    projectProfile: profile.project || {},
    venueProfile: venueName === 'all' ? profile.venues || {} : { [venueName]: profile.venues?.[venueName] || {} },
    currentMetrics: current,
    dailySnapshots: snapshotItems,
    operatingFacts: facts,
    confirmedConversationKnowledge: confirmedAssets.map(item => ({ ...item, epistemicStatus: item.targetType === 'operating_fact' ? 'confirmed_operating_fact' : 'confirmed_operator_claim', boundary: '已确认发生或由运营者确认的判断，不自动证明因果' })),
    openIssues: dailyOpenIssues(venueName),
    activeValidations: dailyActiveValidations(venueName),
    publishedExperiences: dailyPublishedExperiences(venueName),
    implicitKnowledge: knowledgeStateValue().implicitItems.filter(item => item.status === 'confirmed' && normalizeScopeVenueNames(item.scope || {}, profile).some(name => venueName === 'all' || name === venueName)).slice(-20),
    sourceRefs: current.flatMap(item => Array.isArray(item.sourceRefs) ? item.sourceRefs : []).slice(0, 20),
    missingInformation: [
      snapshotItems.some(item => item?.date === date) ? '' : '当前日期尚无来源表快照',
      currentPeriodAvailable ? '' : '当前日期尚无对应周记录，以下只作最近可用数据参考',
      current.length < 2 ? '可比周记录不足，趋势判断有限' : '',
      facts.length ? '' : '近期没有补充经营事实'
    ].filter(Boolean),
    contextFingerprint: [DAILY_CONTEXT_VERSION, date, venueName, readRuntimeState('records').revision, readRuntimeState('workbench').revision, readRuntimeState('experiences').revision, readRuntimeState('knowledge').revision, profile.updatedAt, snapshotItems.map(x => `${x.date}:${x.fetchedAt || ''}`).join(',')].join('|')
  };
  context.currentPeriodAvailable = currentPeriodAvailable;
  return context;
}

function dailyLocalBrief(context) {
  const rows = Array.isArray(context.currentMetrics) ? context.currentMetrics : [];
  if (context.currentPeriodAvailable === false) {
    const latest = rows[0];
    const periodLabel = latest?.periodStart && latest?.periodEnd ? `${latest.periodStart} 至 ${latest.periodEnd}` : '最近可用周期';
    return {
      schemaVersion: 'daily-brief-v1', status: 'no_data', briefType: 'data_gap', dataAvailable: false, actionable: false, canFeedback: false,
      headline: `${context.scope.asOf} 暂无可用的新经营数据`,
      summary: `当前没有覆盖 ${context.scope.asOf} 的周数据；页面保留最近可用周期（${periodLabel}）供参考。`, decisionImpact: '请先补齐或确认当天/本周数据，再决定是否需要经营动作。',
      evidenceRefs: latest ? [`record:${latest.periodId || periodLabel}`] : [], confirmedFacts: [], hypotheses: [], counterEvidence: [], unknowns: context.missingInformation,
      questionForOperator: '', venue: context.scope.venue, asOf: context.scope.asOf, generatedBy: 'local-fallback', contextFingerprint: context.contextFingerprint
    };
  }
  const candidates = [];
  rows.forEach(row => {
    const current = row.core || {};
    const previous = rows.find(item => item.venue === row.venue && item.periodEnd < row.periodStart)?.core || {};
    const metrics = [
      ['box_office_total', '票房总额', '元'],
      ['reception_traffic', '接待客流', '人'],
      ['sales_order_count', '销售票数', '张'],
      ['offline_sales_amount', '线下销售额', '元'],
      ['online_sales_amount', '线上销售额', '元']
    ];
    metrics.forEach(([key, label, unit]) => {
      const change = dailyChange(current[key], previous[key]);
      if (change !== null) candidates.push({ venue: row.venue, key, label, unit, current: dailyNumber(current[key]), previous: dailyNumber(previous[key]), change });
    });
  });
  candidates.sort((a, b) => Math.abs(b.change) - Math.abs(a.change));
  const top = candidates[0];
  const factText = context.operatingFacts?.[0]?.text || '';
  if (!top || Math.abs(top.change) < 8) {
    return {
      schemaVersion: 'daily-brief-v1', status: 'normal', briefType: 'monitor', dataAvailable: true, actionable: false, canFeedback: false,
      headline: '本周期暂未发现需要立即处理的明显变化',
      summary: '当前可计算指标没有出现需要立即升级处理的明显变化。', decisionImpact: '可以继续观察主要指标，并留意正在进行的验证是否按计划推进。',
      evidenceRefs: [], confirmedFacts: [], hypotheses: [], counterEvidence: [], unknowns: context.missingInformation,
      questionForOperator: '', venue: context.scope.venue, asOf: context.scope.asOf, generatedBy: 'local-fallback', contextFingerprint: context.contextFingerprint
    };
  }
  const direction = top.change < 0 ? '下降' : '上升';
  const issue = `${top.venue}的${top.label}${direction}${Math.abs(top.change).toFixed(1)}%，需要确认这是短期波动，还是经营链路中的结构性变化。`;
  const factHint = factText ? `近期经营事实“${factText.slice(0, 80)}”可能提供解释线索，但还不能直接视为因果证据。` : '当前尚缺少足够经营事实来解释变化来源。';
  return {
    schemaVersion: 'daily-brief-v1', status: 'attention', briefType: 'signal', dataAvailable: true, actionable: true, canFeedback: true, headline: issue,
    summary: `当前${top.label}${top.current ?? '—'}${top.unit}，可比值${top.previous ?? '—'}${top.unit}，环比${top.change > 0 ? '+' : ''}${top.change.toFixed(1)}%。`,
    decisionImpact: factHint, evidenceRefs: [`metric:${top.venue}:${top.key}`, 'comparison:previous'],
    confirmedFacts: [`${top.venue}${top.label}发生${direction}`], hypotheses: [], counterEvidence: [], unknowns: context.missingInformation,
    questionForOperator: `这次${top.label}${direction}，你认为最需要优先排查的是客源、承接、产品还是渠道？有什么现场事实可以支持？`,
    venue: context.scope.venue, asOf: context.scope.asOf, generatedBy: 'local-fallback', contextFingerprint: context.contextFingerprint
  };
}

function dailyIdeaLenses() {
  const data = readJsonFile(DAILY_LENSES_PATH, { version: 'idea-lenses-v1', items: [] });
  return Array.isArray(data.items) ? data.items : [];
}

function dailyLocalIdeas(context, brief, limit = 5) {
  const lenses = dailyIdeaLenses();
  const audience = Object.values(context.venueProfile || {}).flatMap(item => Array.isArray(item?.audience) ? item.audience : []).slice(0, 2).join('、');
  const issue = brief?.status === 'no_data' && context.currentPeriodAvailable === false
    ? '当前周数据尚未补齐，仍可从门店客群、场景与产能寻找可验证的增量机会'
    : (brief?.headline || '当前经营变化');
  return lenses.slice(0, Math.max(limit, 5)).map((lens, index) => ({
    ideaId: `idea-${context.scope.asOf.replaceAll('-', '')}-${context.scope.venue}-${index + 1}`,
    venue: context.scope.venue, asOf: context.scope.asOf,
    issueId: `brief-${context.scope.asOf}-${context.scope.venue}`,
    hook: [
      '我突然想到，问题也许不在“多卖一点”，而在于换一批人来玩。',
      '要不要反过来想：别把门店当终点，把它塞进用户原本就会走的行程里？',
      '有个挺有意思的玩法：先不添新资源，把手里这些东西重新拼一次。',
      '渠道不一定只能负责卖票，它也许能和我们一起把这件事做出来。',
      '这个想法稍微大胆一点：把没人来的时段，直接变成另一门生意。'
    ][index] || '这个方向值得换个角度想一想。',
    title: String(lens.title || '重新审视当前经营方式'),
    summary: String(lens.template || '').replaceAll('{issue}', issue).replaceAll('{audience}', audience || '当前主要客群').replace(/。+，/g, '，').replace(/，+/g, '，'),
    pitch: String(lens.template || '').replaceAll('{issue}', issue).replaceAll('{audience}', audience || '当前主要客群').replace(/。+，/g, '，').replace(/，+/g, '，'),
    planSteps: [
      `先确认一个前提：${String(lens.assumption || '门店具备必要的资源和执行条件')}`,
      `做一个最小版本：${String(lens.nextStep || '先用一次小范围观察或访谈验证反应')}`,
      `有反馈后再放大：围绕“${String(lens.mechanism || '新的经营路径')}”补成正式方案`
    ],
    ideaLevel: lens.level || 'adjacent', grounding: lens.level === 'reconstruction' ? 'speculative' : 'inferred',
    whyItMayFit: [issue, audience ? `涉及${audience}` : '门店客群仍需进一步确认'],
    evidenceRefs: Array.isArray(brief?.evidenceRefs) ? brief.evidenceRefs : [],
    keyAssumptions: [String(lens.assumption || '需要运营判断资源和执行条件是否成立')],
    potentialMechanism: String(lens.mechanism || '通过改变当前价值交换或承接方式寻找新的增量'),
    cheapestNextExploration: String(lens.nextStep || '先用一次小范围访谈、现场观察或手工试卖验证反应'),
    status: 'new', generatedAt: new Date().toISOString(), promptVersion: 'idea-generation-v2.2', contextFingerprint: context.contextFingerprint, generatedBy: 'local-fallback'
  })).slice(0, limit);
}

function normalizeDailyBrief(raw, context) {
  const brief = raw && typeof raw === 'object' ? raw : {};
  const dataAvailable = context.currentPeriodAvailable !== false;
  const rawStatus = ['attention', 'normal', 'watch', 'no_data'].includes(brief.status) ? brief.status : 'watch';
  const status = dataAvailable ? rawStatus : 'no_data';
  return {
    schemaVersion: 'daily-brief-v1', status, briefType: status === 'attention' ? 'signal' : status === 'normal' ? 'monitor' : status === 'no_data' ? 'data_gap' : 'watch',
    dataAvailable, actionable: dataAvailable && status === 'attention', canFeedback: dataAvailable && status === 'attention',
    headline: String(brief.headline || (dataAvailable ? '今日经营简报' : `${context.scope.asOf} 暂无可用的新经营数据`)), summary: String(brief.summary || ''), decisionImpact: String(brief.decisionImpact || ''),
    evidenceRefs: Array.isArray(brief.evidenceRefs) ? brief.evidenceRefs.map(String).slice(0, 12) : [],
    confirmedFacts: Array.isArray(brief.confirmedFacts) ? brief.confirmedFacts.map(String).slice(0, 8) : [],
    hypotheses: Array.isArray(brief.hypotheses) ? brief.hypotheses.map(String).slice(0, 8) : [],
    counterEvidence: Array.isArray(brief.counterEvidence) ? brief.counterEvidence.map(String).slice(0, 8) : [],
    unknowns: [...new Set([...(Array.isArray(brief.unknowns) ? brief.unknowns.map(String) : []), ...(context.missingInformation || [])])].slice(0, 8),
    questionForOperator: dataAvailable ? String(brief.questionForOperator || '') : '', venue: context.scope.venue, asOf: context.scope.asOf,
    contextFingerprint: context.contextFingerprint, generatedAt: new Date().toISOString(), generatedBy: String(brief.generatedBy || 'external-model')
  };
}

function ideaSemanticKey({ venue = '', problemScope = '', causalHypothesis = '', solutionMechanism = '', targetAudience = '' } = {}) {
  return crypto.createHash('sha256').update([venue, problemScope, causalHypothesis, solutionMechanism, targetAudience].map(value => String(value || '').toLowerCase().replace(/[\s\p{P}\p{S}]/gu, '')).join('|')).digest('hex').slice(0, 24);
}

function normalizeDailyIdeas(raw, context, brief, limit = 5) {
  const items = Array.isArray(raw) ? raw : Array.isArray(raw?.ideas) ? raw.ideas : [];
  const idPrefix = `idea-${context.scope.asOf.replaceAll('-', '')}-${String(context.scope.venue || 'all').replace(/[^\u4e00-\u9fa5A-Za-z0-9_-]/g, '-')}-`;
  return items.slice(0, limit).map((item, index) => {
    const problemScope = String(item.problemScope || brief?.headline || item.issueId || '').trim();
    const causalHypothesis = String(item.causalHypothesis || item.keyAssumptions?.[0] || '').trim();
    const solutionMechanism = String(item.solutionMechanism || item.potentialMechanism || item.title || '').trim();
    const targetAudience = String(item.targetAudience || '').trim();
    const semanticKey = ideaSemanticKey({ venue: context.scope.venue, problemScope, causalHypothesis, solutionMechanism, targetAudience });
    return ({
    ideaId: (() => { const rawId = String(item.ideaId || '').trim(); return rawId.startsWith(idPrefix) ? rawId : `${idPrefix}${(rawId || `${Date.now().toString(36)}-${index}`).replace(/^idea-/, '')}`; })(), venue: context.scope.venue, asOf: context.scope.asOf,
    issueId: String(item.issueId || `brief-${context.scope.asOf}-${context.scope.venue}`), hook: String(item.hook || '这个方向值得换个角度想一想。'), title: String(item.title || '未命名经营想法'), summary: String(item.pitch || item.summary || item.oneSentence || ''), pitch: String(item.pitch || item.summary || item.oneSentence || ''),
    planSteps: Array.isArray(item.planSteps) ? item.planSteps.map(String).filter(Boolean).slice(0, 4) : [],
    ideaLevel: ['immediate', 'adjacent', 'reconstruction'].includes(item.ideaLevel) ? item.ideaLevel : 'adjacent', grounding: ['grounded', 'inferred', 'speculative'].includes(item.grounding) ? item.grounding : 'inferred',
    whyItMayFit: Array.isArray(item.whyItMayFit) ? item.whyItMayFit.map(String).slice(0, 5) : [], evidenceRefs: Array.isArray(item.evidenceRefs) ? item.evidenceRefs.map(String).slice(0, 12) : [],
    keyAssumptions: Array.isArray(item.keyAssumptions) ? item.keyAssumptions.map(String).slice(0, 6) : [], problemScope, causalHypothesis, solutionMechanism, targetAudience, substantiveDelta: String(item.substantiveDelta || ''), semanticKey, potentialMechanism: String(item.potentialMechanism || ''), cheapestNextExploration: String(item.cheapestNextExploration || ''),
    status: ['new', 'saved', 'exploring', 'dismissed', 'converted_to_tactic'].includes(item.status) ? item.status : 'new', generatedAt: new Date().toISOString(), promptVersion: 'idea-generation-v2.2', contextFingerprint: context.contextFingerprint, generatedBy: String(item.generatedBy || 'external-model')
    });
  });
}

function normalizeSettings(input, current = readSettings()) {
  const next = { ...DEFAULT_SETTINGS, ...current };
  if (Number.isInteger(Number(input?.weekStart))) next.weekStart = Number(input.weekStart) === 0 ? 0 : 1;
  if (Number.isFinite(Number(input?.weekLength))) next.weekLength = Math.max(1, Math.min(14, Number(input.weekLength)));
  for (const key of ['timezone', 'periodSeparator', 'syncMode', 'reportProvider', 'reportApiEndpoint', 'reportModel']) {
    if (typeof input?.[key] === 'string') next[key] = input[key].trim();
  }
  if (next.periodSeparator !== '_' && next.periodSeparator !== '~') next.periodSeparator = '_';
  if (next.syncMode !== 'outbox' && next.syncMode !== 'api') next.syncMode = 'api';
  if (next.reportProvider !== 'api' && next.reportProvider !== 'local') next.reportProvider = 'local';
  if (typeof input?.thinkingEnabled === 'boolean') next.thinkingEnabled = input.thinkingEnabled;
  if (Array.isArray(input?.thinkingTasks)) next.thinkingTasks = input.thinkingTasks.map(String).filter(key => THINKING_TASK_KEYS.has(key));
  next.thinkingEnabled = next.thinkingEnabled !== false;
  next.thinkingTasks = [...new Set((Array.isArray(next.thinkingTasks) ? next.thinkingTasks : []).filter(key => THINKING_TASK_KEYS.has(key)))];
  if (typeof input?.reportApiKey === 'string' && input.reportApiKey.trim()) next.reportApiKey = input.reportApiKey.trim();
  if (input?.clearReportApiKey === true) delete next.reportApiKey;
  if (next.reportProvider === 'api' && /deepseek\.com/i.test(next.reportApiEndpoint || '') && !/^deepseek-/i.test(next.reportModel || '')) {
    throw new Error('当前地址是 DeepSeek，模型名称必须使用 deepseek- 开头的模型');
  }
  return next;
}

const mime = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon'
};

function json(res, status, body) {
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type, X-Xiyu-Token, Authorization, Idempotency-Key',
    'Access-Control-Allow-Methods': 'GET,POST,PUT,OPTIONS'
  });
  res.end(JSON.stringify(body));
}

const DEFAULT_STRATEGY_PROFILE = {
  version: 'strategy-project-profile-v1',
  updatedAt: '',
  project: {
    name: 'VR大空间经营项目',
    businessType: '线下VR大空间付费体验',
    country: '中国',
    city: '北京',
    productOffering: 'VR大空间内容体验、单次票与次卡',
    coreAudience: ['亲子家庭', '场域自然客流'],
    decisionMakers: ['家长', '同行成年人'],
    naturalTrafficSources: ['场馆或商业体自然客流'],
    coreFunnel: ['客源触达', '到店/进店', '购票转化', '内容/体验', '客单/次卡', '用户资产', '复购/转介绍'],
    ipAssets: [],
    commonConstraints: [],
    goals: [],
    decisions: []
  },
  venues: {
    '东坝': { venueId: 'DONGBA', locationType: '科技馆或文旅场馆依附型门店', audience: ['亲子家庭', '科技馆到访客'], trafficSources: ['科技馆场域自然客流'], spaceEquipment: [], staffing: [], constraints: [], notes: '', sourceSheets: { 大麦: 'blleCP', 开店宝: 'fxP3Ly', 抖音: '2qL092', 猫眼: 'N6Enef', 小程序: '0yiVWO' } },
    '中影': { venueId: 'ZHONGYING', locationType: '影院或商业体自然客流型门店', audience: ['亲子家庭', '影院或商业体路过客'], trafficSources: ['影院或商业体自然客流'], spaceEquipment: [], staffing: [], constraints: [], notes: '', sourceSheets: { 大麦: '6e8e61', 开店宝: 'nvRqzG', 抖音: 'DGhI6G', 猫眼: 'zOBuCl', 小程序: 'jqH72d' } }
  }
};

function stringList(value, max = 30) {
  if (Array.isArray(value)) return value.map(item => String(item || '').trim()).filter(Boolean).slice(0, max);
  return String(value || '').split(/\r?\n|；|;/).map(item => item.trim()).filter(Boolean).slice(0, max);
}

function readStrategyProfile() {
  try {
    const stored = JSON.parse(fs.readFileSync(STRATEGY_PROFILE_PATH, 'utf8'));
    return normalizeStrategyProfile(stored);
  } catch {
    return normalizeStrategyProfile(DEFAULT_STRATEGY_PROFILE);
  }
}

function normalizeStrategyProfile(input) {
  const projectInput = input?.project && typeof input.project === 'object' ? input.project : {};
  const project = { ...DEFAULT_STRATEGY_PROFILE.project };
  for (const key of ['name', 'businessType', 'country', 'city', 'productOffering']) {
    if (typeof projectInput[key] === 'string') project[key] = projectInput[key].trim();
  }
  for (const key of ['coreAudience', 'decisionMakers', 'naturalTrafficSources', 'coreFunnel', 'ipAssets', 'commonConstraints']) {
    project[key] = stringList(projectInput[key] ?? project[key]);
  }
  const normalizeGovernanceItems = (value, type) => (Array.isArray(value) ? value : []).map((item, index) => {
    if (!item || typeof item !== 'object') return null;
    const id = String(item.id || `${type}:${index + 1}`).trim().slice(0, 180);
    const scope = item.scope && typeof item.scope === 'object' ? item.scope : {};
    return {
      ...item,
      id,
      type,
      title: String(item.title || item.name || item.statement || item.decision || id).trim().slice(0, 240),
      summary: String(item.summary || item.statement || item.decision || '').trim().slice(0, 1400),
      scope: {
        projectId: String(scope.projectId || '').trim(),
        venueNames: Array.isArray(scope.venueNames) ? scope.venueNames.map(String).filter(Boolean).slice(0, 20) : [],
      },
      sourceRefs: Array.isArray(item.sourceRefs || item.refs) ? (item.sourceRefs || item.refs).map(String).filter(Boolean).slice(0, 20) : [],
      updatedAt: String(item.updatedAt || '').trim(),
    };
  }).filter(Boolean).slice(0, 200);
  project.goals = normalizeGovernanceItems(projectInput.goals ?? project.goals, 'goal');
  project.decisions = normalizeGovernanceItems(projectInput.decisions ?? project.decisions, 'decision');
  const venues = {};
  const venueInput = input?.venues && typeof input.venues === 'object' ? input.venues : {};
  for (const venue of Object.keys({ ...DEFAULT_STRATEGY_PROFILE.venues, ...venueInput })) {
    const base = DEFAULT_STRATEGY_PROFILE.venues[venue] || {};
    const raw = venueInput[venue] && typeof venueInput[venue] === 'object' ? venueInput[venue] : {};
    venues[venue] = {
      venueId: String(raw.venueId ?? base.venueId ?? (venue === '东坝' ? 'DONGBA' : venue === '中影' ? 'ZHONGYING' : `VENUE_${Buffer.from(venue).toString('base64url').replace(/[^A-Za-z0-9_-]/g, '').toUpperCase()}`)).trim(),
      locationType: String(raw.locationType ?? base.locationType ?? '').trim(),
      audience: stringList(raw.audience ?? base.audience),
      trafficSources: stringList(raw.trafficSources ?? base.trafficSources),
      spaceEquipment: stringList(raw.spaceEquipment ?? base.spaceEquipment),
      staffing: stringList(raw.staffing ?? base.staffing),
      constraints: stringList(raw.constraints ?? base.constraints),
      notes: String(raw.notes ?? base.notes ?? '').trim(),
      sourceSheets: raw.sourceSheets && typeof raw.sourceSheets === 'object' ? Object.fromEntries(Object.entries(raw.sourceSheets).map(([key, value]) => [String(key).trim(), String(value || '').trim()]).filter(([, value]) => value)) : { ...(base.sourceSheets || {}) }
    };
  }
  return { version: 'strategy-project-profile-v1', updatedAt: String(input?.updatedAt || ''), project, venues };
}

function writeStrategyProfile(input) {
  const profile = normalizeStrategyProfile(input);
  profile.updatedAt = new Date().toISOString();
  fs.mkdirSync(path.dirname(STRATEGY_PROFILE_PATH), { recursive: true });
  const tempPath = `${STRATEGY_PROFILE_PATH}.tmp`;
  fs.writeFileSync(tempPath, JSON.stringify(profile, null, 2), 'utf8');
  fs.renameSync(tempPath, STRATEGY_PROFILE_PATH);
  return profile;
}

// ─── 溪语经营知识桥 ──────────────────────────────────────────────────────────
// 这里提供一个与“今日经营”无关的窄上下文接口：溪语只拿到被权限、状态和
// 门店范围过滤后的摘要；它不能直接读取 runtime-state 文件，也不能推动正式状态。
function xiyuBridgeAllowed(req) {
  if (!XIYU_CONTEXT_TOKEN) return true; // 本地开发默认开放；线上请设置 token
  const supplied = String(req.headers['x-xiyu-token'] || req.headers.authorization || '').replace(/^Bearer\s+/i, '').trim();
  return supplied && supplied === XIYU_CONTEXT_TOKEN;
}

function readXiyuAccessPolicy() {
  const value = readJsonFile(XIYU_ACCESS_PATH, null);
  if (!value || typeof value !== 'object' || Array.isArray(value)) return { configured: false, actors: {} };
  return { configured: true, defaultDeny: value.defaultDeny !== false, actors: value.actors && typeof value.actors === 'object' ? value.actors : {} };
}

function authorizeXiyuScope(input = {}) {
  const policy = readXiyuAccessPolicy();
  const actorId = String(input.actorId || '').trim();
  const requestedProjectId = String(input.projectId || input.scope?.projectId || '').trim();
  const profile = readStrategyProfile();
  const venueLookup = new Map(Object.entries(profile.venues || {}).flatMap(([name, venue]) => [[name, String(venue?.venueId || name)], [String(venue?.venueId || name), String(venue?.venueId || name)]]));
  const rawVenues = [...(Array.isArray(input.scope?.venueIds) ? input.scope.venueIds : []), ...(Array.isArray(input.scope?.venueNames) ? input.scope.venueNames : []), ...(Array.isArray(input.scope?.venues) ? input.scope.venues : [])].map(String).filter(Boolean);
  const requestedVenueIds = [...new Set(rawVenues.map(value => venueLookup.get(value) || value))];
  // 兼容既有本地安装：没有权限文件时维持原行为；一旦创建权限文件即切换到显式授权。
  if (!policy.configured) return { allowed: true, mode: 'legacy_local', actorId, projectId: requestedProjectId, venueIds: requestedVenueIds };
  const actor = policy.actors[actorId];
  if (!actor) return { allowed: !policy.defaultDeny, mode: 'configured', actorId, projectId: requestedProjectId, venueIds: requestedVenueIds, reason: 'actor_not_configured' };
  const projectIds = new Set((actor.projectIds || actor.projects || []).map(String));
  const venueIds = new Set((actor.venueIds || actor.venues || []).map(String).map(value => venueLookup.get(value) || value));
  if (projectIds.size && requestedProjectId && !projectIds.has(requestedProjectId)) return { allowed: false, mode: 'configured', actorId, projectId: requestedProjectId, venueIds: [], reason: 'project_denied' };
  const scopedVenues = requestedVenueIds.filter(value => !venueIds.size || venueIds.has(value));
  if (requestedVenueIds.length && scopedVenues.length !== requestedVenueIds.length) return { allowed: false, mode: 'configured', actorId, projectId: requestedProjectId, venueIds: scopedVenues, reason: 'venue_denied' };
  return { allowed: true, mode: 'configured', actorId, projectId: requestedProjectId, venueIds: scopedVenues };
}

function auditXiyuKnowledge(action, authorization, details = {}) {
  try {
    fs.mkdirSync(path.dirname(XIYU_AUDIT_PATH), { recursive: true });
    const actorHash = authorization?.actorId ? crypto.createHash('sha256').update(authorization.actorId).digest('hex').slice(0, 16) : '';
    const event = {
      at: new Date().toISOString(), action, actorHash,
      allowed: authorization?.allowed !== false, accessMode: authorization?.mode || 'unknown',
      projectId: authorization?.projectId || '', venueIds: authorization?.venueIds || [],
      reason: authorization?.reason || '', itemCount: Number(details.itemCount || 0)
    };
    fs.appendFileSync(XIYU_AUDIT_PATH, `${JSON.stringify(event)}\n`, 'utf8');
  } catch { /* 审计失败不阻断主业务，但不记录用户原文。 */ }
}

function normalizeScopeVenueNames(scope = {}, profile = readStrategyProfile()) {
  const raw = [];
  for (const value of (Array.isArray(scope.venueIds) ? scope.venueIds : [])) raw.push(String(value || '').trim());
  for (const value of (Array.isArray(scope.venueNames) ? scope.venueNames : [])) raw.push(String(value || '').trim());
  for (const value of (Array.isArray(scope.venues) ? scope.venues : [])) raw.push(String(value || '').trim());
  if (typeof scope.venue === 'string') raw.push(scope.venue.trim());
  if (raw.length === 0 || raw.some(value => !value || value === 'all' || value === 'project')) return Object.keys(profile.venues || {});
  return Object.entries(profile.venues || {})
    .filter(([name, venue]) => raw.includes(name) || raw.includes(String(venue?.venueId || '')))
    .map(([name]) => name);
}

function knowledgeSnippet(value, max = 900) {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim();
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

// 真实经营上下文不得混入回归/演示数据。测试数据历史上曾以 confirmed
// 写入 records/reports，因此不能只依赖 status；用明确的测试标记做服务端硬过滤。
function isSyntheticKnowledgeText(...values) {
  const text = values.filter(value => value !== null && value !== undefined).map(value => {
    if (typeof value === 'object') {
      try { return JSON.stringify(value); } catch { return ''; }
    }
    return String(value);
  }).join(' ');
  return /E2E|请勿用于正式|测试记录|测试数据|API回归|流程验证|仅用于测试|test[-_ ]?(data|record)/i.test(text);
}

function isProductionOperatingRecord(row) {
  if (!row || row.status === 'deleted') return false;
  return !isSyntheticKnowledgeText(row.id, row.periodId, row.notes, row.source, row.sourceRefs, row.feishuSyncFingerprint);
}

function knowledgeSearchTerms(query = {}) {
  const text = [query.text, query.question, ...(Array.isArray(query.topics) ? query.topics : []), ...(Array.isArray(query.metricIds) ? query.metricIds : [])]
    .filter(Boolean).join(' ').toLowerCase();
  const terms = text.split(/[^\p{L}\p{N}_-]+/u).map(x => x.trim()).filter(x => x.length >= 2);
  for (const chunk of text.match(/[\p{Script=Han}]{2,}/gu) || []) {
    for (let index = 0; index < chunk.length - 1; index++) terms.push(chunk.slice(index, index + 2));
  }
  return [...new Set(terms)].slice(0, 80);
}

function knowledgeRelevance(text, terms = []) {
  const hay = String(text || '').toLowerCase();
  if (!terms.length) return 0.35;
  const hits = terms.reduce((n, term) => n + (hay.includes(term) ? 1 : 0), 0);
  return Math.min(0.98, 0.25 + hits / Math.max(terms.length, 1) * 0.7);
}

import { sourceCapabilities, planSourceLookup, executeSourceLookup } from './cognition/source-router.mjs';
import { dimensions, roles, buildKnowledgeMap, selectKnowledgeSlots } from './cognition/knowledge-map.mjs';

function buildKnowledgeCatalog() {
  const profile = readStrategyProfile();
  let knowledge = {};
  try { knowledge = readJsonFile(STRATEGY_KNOWLEDGE_PATH, {}); } catch {}
  const nodes = Array.isArray(knowledge.nodes) ? knowledge.nodes : [];
  return {
    schemaVersion: 'enterprise-knowledge-catalog-v1',
    capabilities: sourceCapabilities,
    knowledgeDimensions: dimensions.map(({ id, title }) => ({ id, title })),
    project: {
      id: String(profile.project?.id || 'yuanqu-vr'),
      name: String(profile.project?.name || '经营项目'),
      businessType: String(profile.project?.businessType || '')
    },
    venues: Object.entries(profile.venues || {}).map(([name, venue]) => ({
      id: String(venue?.venueId || name), name,
      locationType: String(venue?.locationType || ''),
      audience: stringList(venue?.audience),
      trafficSources: stringList(venue?.trafficSources)
    })),
    assetTypes: [
      'project_profile', 'venue_profile', 'operating_fact', 'opportunity',
      'implicit_knowledge', 'knowledge_gap', 'validation', 'experience', 'weekly_conclusion', 'goal', 'decision'
    ],
    nodes: nodes.map(node => ({ id: String(node.id || ''), title: String(node.title || node.name || ''), description: knowledgeSnippet(node.description || node.summary || '', 240) })).filter(node => node.id || node.title)
  };
}

function buildEnterpriseKnowledgeContext(input = {}) {
  const profile = readStrategyProfile();
  const catalog = buildKnowledgeCatalog();
  const scope = input.scope && typeof input.scope === 'object' ? input.scope : {};
  const venueNames = normalizeScopeVenueNames(scope, profile);
  const query = input.query && typeof input.query === 'object' ? input.query : { text: '' };
  const terms = knowledgeSearchTerms(query);
  // 模型有时会把“门店背景/经营资料”这类自然语言描述放进 assetTypes。
  // 只有目录声明的标准类型才参与过滤；全是未知描述时降级为不限制类型，
  // 避免工作语境已识别但上下文被错误过滤为空。
  const supportedAssetTypes = new Set(Array.isArray(catalog.assetTypes) ? catalog.assetTypes : []);
  const requestedTypeValues = Array.isArray(query.assetTypes) ? query.assetTypes.map(String).filter(Boolean) : [];
  const normalizedRequestedTypes = requestedTypeValues.filter(type => supportedAssetTypes.has(type));
  const requestedTypes = normalizedRequestedTypes.length ? new Set(normalizedRequestedTypes) : null;
  const items = [];
  const push = (item) => {
    if (!item || (requestedTypes && !requestedTypes.has(item.assetType))) return;
    if (['weekly_conclusion', 'opportunity'].includes(item.assetType) && venueNames.length) {
      const mentioned = Object.keys(profile.venues || {}).filter(name => `${item.title} ${item.summary}`.includes(name));
      if (mentioned.length && !mentioned.some(name => venueNames.includes(name))) return;
    }
    const searchable = `${item.title || ''} ${item.summary || ''} ${item.text || ''} ${item.assetType || ''}`;
    items.push({ ...item, relevance: knowledgeRelevance(searchable, terms) });
  };

  push({ id: `profile:project:${catalog.project.id}`, assetType: 'project_profile', epistemicStatus: 'confirmed_background', title: catalog.project.name, summary: JSON.stringify(profile.project), scope: { projectId: catalog.project.id } });
  for (const venueName of venueNames) {
    const venue = profile.venues?.[venueName];
    if (!venue) continue;
    push({ id: `profile:venue:${venue.venueId || venueName}`, assetType: 'venue_profile', epistemicStatus: 'confirmed_background', title: venueName, summary: JSON.stringify(venue), scope: { projectId: catalog.project.id, venue: venueName, venueId: venue.venueId || venueName } });
  }

  const records = Array.isArray(readRuntimeState('records').data) ? readRuntimeState('records').data : [];
  for (const row of records.filter(isProductionOperatingRecord)) {
    const rowVenue = String(row.venue || '');
    if (venueNames.length && rowVenue && !venueNames.includes(rowVenue) && !venueNames.some(name => String(profile.venues?.[name]?.venueId || '') === rowVenue)) continue;
    push({ id: `record:${row.periodId || row.periodStart || row.id || items.length}`, assetType: 'operating_fact', epistemicStatus: 'system_fact', title: `${row.periodStart || ''}~${row.periodEnd || ''} ${rowVenue}`.trim(), summary: JSON.stringify({ periodId: row.periodId, venue: row.venue, periodStart: row.periodStart, periodEnd: row.periodEnd, core: row.core, daily: row.daily }), scope: { projectId: catalog.project.id, venue: rowVenue } });
  }

  for (const snapshot of Object.values(dailyStateValue().snapshots).filter(item => item?.sourceStatus === 'feishu' && venueNames.includes(item.venue)).sort((a, b) => String(b.date).localeCompare(String(a.date))).slice(0, 14)) {
    if (isSyntheticKnowledgeText(snapshot.source)) continue;
    push({ id: `snapshot:${snapshot.venue}:${snapshot.date}`, assetType: 'operating_fact', epistemicStatus: 'system_fact', title: `${snapshot.date} ${snapshot.venue} 来源表日快照`, summary: JSON.stringify({ venue: snapshot.venue, periodStart: snapshot.date, periodEnd: snapshot.date, core: { box_office_total: snapshot.weekly?.sales ?? null, sales_order_count: snapshot.weekly?.tickets ?? null, online_sales_amount: snapshot.weekly?.onlineSales ?? null, offline_sales_amount: snapshot.weekly?.offlineSales ?? null }, fetchedAt: snapshot.fetchedAt }), scope: { projectId: catalog.project.id, venue: snapshot.venue } });
  }
  const reports = readRuntimeState('reports').data;
  if (reports && typeof reports === 'object') {
    for (const [periodId, report] of Object.entries(reports).slice(-12)) {
      // 报告缓存同样可能保留回归周；即使其内部字段没有 status，也不能进入溪语上下文。
      if (isSyntheticKnowledgeText(periodId, report)) continue;
      const pushReportContext = (context, venue = 'all', prefix = '') => {
        if (venueNames.length && venue !== 'all' && !venueNames.includes(venue)) return;
        for (const [field, value] of Object.entries(context || {})) {
          const text = String(value || '').trim();
          if (!text || ['periodStart', 'periodEnd', 'venue'].includes(field)) continue;
          const confirmedField = ['events', 'execution', 'resultEvidence'].includes(field);
          push({ id: `fact:${periodId}:${prefix}${field}`, assetType: 'operating_fact', epistemicStatus: confirmedField ? 'confirmed_operating_fact' : 'operator_record', title: `${periodId} ${venue} ${field}`, summary: text, scope: { projectId: catalog.project.id, venue } });
        }
      };
      pushReportContext(report?.context || {}, report?.context?.venue || 'all', 'legacy:');
      pushReportContext(report?.reportPackage?.commonContext || {}, 'all', 'common:');
      for (const [venue, venueReport] of Object.entries(report?.reportPackage?.venueReports || {})) pushReportContext(venueReport?.context || {}, venue, `${venue}:`);
    }
  }

  const wb = readRuntimeState('workbench').data || {};
  const cache = wb.analysisCache && typeof wb.analysisCache === 'object' ? wb.analysisCache : {};
  for (const [sourceKey, value] of Object.entries(cache)) {
    const keyVenue = sourceKey.split('|')[1] || 'all';
    if (venueNames.length && keyVenue !== 'all' && !venueNames.includes(keyVenue)) continue;
    for (const signal of (value?.expertSignals || value?.signals || [])) {
      if (!signal || signal.include === false) continue;
      push({ id: String(signal.id || `signal:${sourceKey}:${signal.title || ''}`), assetType: signal.kind === 'opportunity' ? 'opportunity' : 'weekly_conclusion', epistemicStatus: signal.status || 'observing', title: String(signal.title || '经营信号'), summary: knowledgeSnippet(signal.observation || signal.hypothesis || '', 900), scope: { projectId: catalog.project.id, venue: keyVenue }, refs: signal.evidenceRefs || [] });
    }
  }
  const plans = Array.isArray(wb.tacticPlans) ? wb.tacticPlans : [];
  for (const plan of plans) {
    if (!['ready', '执行中', '待评估', 'draft', 'designed'].includes(plan.status)) continue;
    if (venueNames.length && plan.venue && plan.venue !== 'all' && !venueNames.includes(plan.venue)) continue;
    push({ id: String(plan.id || `validation:${items.length}`), assetType: 'validation', epistemicStatus: String(plan.status || 'in_progress'), title: String(plan.tacticTitle || plan.title || '进行中验证'), summary: JSON.stringify({ status: plan.status, metric: plan.metric || plan.targetMetric, startDate: plan.startDate, evaluationDate: plan.evaluationDate, nextAction: plan.nextAction }), scope: { projectId: catalog.project.id, venue: plan.venue || 'all' } });
  }
  for (const item of (Array.isArray(wb.intelligenceAssets) ? wb.intelligenceAssets : [])) {
    if (item.targetType === 'experience' || !['confirmed', 'draft'].includes(item.status)) continue;
    if (venueNames.length && item.scope?.venueNames?.length && !item.scope.venueNames.some(name => venueNames.includes(name))) continue;
    push({ id: item.id, assetType: item.targetType || 'operating_fact', epistemicStatus: item.targetType === 'operating_fact' ? 'confirmed_operating_fact' : item.targetType === 'tactic' ? 'draft' : 'confirmed_operator_claim', title: '溪语对话确认信息', summary: knowledgeSnippet(item.statement || '', 1000), scope: item.scope || { projectId: catalog.project.id }, refs: [item.sourceCandidateId, ...(item.supportingEvidenceRefs || [])].filter(Boolean) });
  }
  const knowledge = knowledgeStateValue();
  for (const item of knowledge.implicitItems) {
    if (item.status !== 'confirmed') continue;
    if (venueNames.length && !normalizeScopeVenueNames(item.scope || {}, profile).some(name => venueNames.includes(name))) continue;
    push({ id: item.id, assetType: 'implicit_knowledge', epistemicStatus: 'confirmed_implicit_knowledge', title: item.title || '已确认隐性知识', summary: knowledgeSnippet(`${item.dimensionId ? `知识维度：${dimensions.find(d => d.id === item.dimensionId)?.title || item.dimensionId}；适用岗位：${roles[item.roleId] || '企业通用'}。` : ''}${item.statement || ''}`, 1000), scope: item.scope || { projectId: catalog.project.id }, refs: item.sourceRefs || [] });
  }
  let openGaps = knowledge.gaps.filter(item => ['open', 'asking', 'review_pending'].includes(item.status) && (!venueNames.length || !item.scope?.venueNames?.length || item.scope.venueNames.some(name => venueNames.includes(name)))).slice(-8);
  // 兼容旧数据：在首次生成正式 knowledge gaps 之前仍能看见原有待澄清项，
  // 但它们不会被误当成已确认隐性知识。
  if (!openGaps.length) {
    const intelligence = intelligenceStateValue();
    openGaps = intelligence.items.filter(item => ['pending', 'needs_clarification', 'conflicted'].includes(item.reviewStatus) && (!venueNames.length || !item.scope?.venueNames?.length || item.scope.venueNames.some(name => venueNames.includes(name)))).slice(-8);
  }
  for (const item of openGaps) {
    push({ id: `gap:${item.id}`, assetType: 'knowledge_gap', epistemicStatus: item.status || item.reviewStatus || 'open', title: item.statement || '待补充经营信息', summary: JSON.stringify({ question: item.question || '', whyNeeded: item.whyNeeded || '', missingInformation: item.missingInformation || [], conflicts: item.conflicts || [] }), scope: item.scope || { projectId: catalog.project.id }, refs: item.sourceRefs || item.relatedAssetRefs || [] });
  }
  const experienceState = readRuntimeState('experiences').data || {};
  for (const item of (Array.isArray(experienceState.items) ? experienceState.items : [])) {
    if (item?.status !== 'published' || item?.retrievalEligible !== true) continue;
    if (venueNames.length && item.venue && item.venue !== 'all' && !venueNames.includes(item.venue)) continue;
    push({ id: String(item.id || `experience:${items.length}`), assetType: 'experience', epistemicStatus: 'accepted_experience', title: String(item.title || ''), summary: knowledgeSnippet(item.reusable || item.background || '', 1000), scope: { projectId: catalog.project.id, venue: item.venue || 'all' }, refs: item.evidenceRefs || [] });
  }

  const maxItems = Math.max(1, Math.min(Number(input.limits?.maxItems) || 12, 40));
  const maxCharacters = Math.max(1000, Math.min(Number(input.limits?.maxCharacters) || 8000, 16000));
  const chosen = items.sort((a, b) => b.relevance - a.relevance).slice(0, maxItems);
  let used = 0;
  const bounded = chosen.filter(item => {
    const size = JSON.stringify(item).length;
    if (used + size > maxCharacters) return false;
    used += size;
    return true;
  });
  const source = createCognitionSourcePort({
    catalog,
    profile,
    readState: kind => readRuntimeState(kind),
    revisions: Object.fromEntries(Object.keys(RUNTIME_STATE_FILES).map(kind => [kind, readRuntimeState(kind).revision])),
  });
  return compileEnterpriseContext({
    source,
    input: { scope: { projectId: catalog.project.id, venueNames } },
    items: bounded,
    goals: profile.project?.goals || [],
    decisions: profile.project?.decisions || [],
    boundaries: [
      '项目档案和历史经验只能作为背景或候选机制，不能单独证明当前因果。',
      '进行中验证只能说明进度，不能当作已验证经验。',
      '未出现在 items 中的资产不可推断。'
    ],
    missingInformation: openGaps.flatMap(item => item.missingInformation || []).filter(Boolean).slice(0, 5).concat(bounded.length ? [] : ['没有找到与当前话题直接相关的已授权经营资产。']),
    fingerprint: [
      ...Object.entries(source.revisions).map(([kind, revision]) => `${kind}:${revision}`),
      profile.updatedAt,
      venueNames.join(','),
    ].join('|'),
  });
}

function intelligenceStateValue() {
  const state = readRuntimeState('intelligence').data;
  if (!state || typeof state !== 'object' || Array.isArray(state)) return { schemaVersion: 'work-intelligence-candidate-v1', items: [], updatedAt: '' };
  return { schemaVersion: 'work-intelligence-candidate-v1', items: Array.isArray(state.items) ? state.items : [], updatedAt: String(state.updatedAt || '') };
}

function knowledgeStateValue() {
  const state = readRuntimeState('knowledge').data;
  if (!state || typeof state !== 'object' || Array.isArray(state)) return { schemaVersion: 'enterprise-knowledge-state-v1', implicitItems: [], gaps: [], updatedAt: '' };
  return {
    schemaVersion: 'enterprise-knowledge-state-v1',
    implicitItems: Array.isArray(state.implicitItems) ? state.implicitItems : [],
    gaps: Array.isArray(state.gaps) ? state.gaps : [],
    discovery: state.discovery && typeof state.discovery === 'object' ? state.discovery : {},
    updatedAt: String(state.updatedAt || '')
  };
}

function normalizeKnowledgeGap(input = {}) {
  const now = new Date().toISOString();
  const scope = input.scope && typeof input.scope === 'object' ? input.scope : {};
  const statement = knowledgeSnippet(input.statement || input.question || '', 800);
  const venueNames = scope.venueNames?.length || scope.venueIds?.length ? normalizeScopeVenueNames(scope) : [];
  const idSeed = [scope.projectId, ...venueNames, input.dimensionId || '', input.facetId || '', input.dimensionId === 'role_goals' ? input.roleId : '', statement].join('|');
  const score = key => Math.max(1, Math.min(5, Number(input.assessment?.[key]) || 3));
  const assessment = { impact: score('impact'), urgency: score('urgency'), reuse: score('reuse'), answerCost: score('answerCost') };
  return {
    schemaVersion: 'knowledge-gap-v1',
    knowledgeTrack: dimensions.some(d => d.id === input.dimensionId) ? 'enterprise' : 'diagnostic',
    dimensionId: dimensions.some(d => d.id === input.dimensionId) ? input.dimensionId : '',
    facetId: dimensions.find(d => d.id === input.dimensionId)?.facets?.some(f => f.id === input.facetId) ? input.facetId : '',
    roleId: roles[input.roleId] ? input.roleId : 'owner',
    respondentRoles: Array.isArray(input.respondentRoles) ? input.respondentRoles.filter(r => roles[r]) : [],
    id: String(input.id || `kg_${crypto.createHash('sha256').update(idSeed).digest('hex').slice(0, 18)}`),
    statement,
    question: knowledgeSnippet(input.question || `关于“${statement}”，你能说一个最近实际发生的例子吗？`, 600),
    whyNeeded: knowledgeSnippet(input.whyNeeded || '', 600),
    decisionImpact: knowledgeSnippet(input.decisionImpact || input.whyNeeded || '', 600),
    expectedAnswer: knowledgeSnippet(input.expectedAnswer || '', 600).replace(/[，,；;]?(?:例如|比如).*$/, ''),
    acquisitionRoute: ['operator', 'source_lookup', 'internal_analysis', 'external_research'].includes(input.acquisitionRoute) ? input.acquisitionRoute : 'operator',
    assessment,
    valueScore: assessment.impact * 4 + assessment.urgency * 3 + assessment.reuse * 2 - assessment.answerCost * 2,
    scope: { projectId: String(scope.projectId || readStrategyProfile().project?.id || 'yuanqu-vr'), venueNames },
    priority: ['low', 'normal', 'high'].includes(input.priority) ? input.priority : 'normal',
    status: ['open', 'asking', 'review_pending', 'confirmed', 'dismissed'].includes(input.status) ? input.status : 'open',
    sourceRefs: Array.isArray(input.sourceRefs) ? input.sourceRefs.map(String).filter(Boolean).slice(0, 30) : [],
    createdAt: String(input.createdAt || now), updatedAt: now, resolvedAt: String(input.resolvedAt || '')
  };
}

function groundKnowledgeGapTime(gap, context, asOf = dailyIsoNow()) {
  const datedItems = context.items.filter(item => item.assetType === 'operating_fact');
  const referenced = datedItems.filter(item => gap.sourceRefs.includes(item.id));
  const periods = (referenced.length ? referenced : datedItems).flatMap(item => {
    try { const row = JSON.parse(item.summary); return row.periodStart && row.periodEnd ? [row] : []; } catch { return []; }
  }).sort((a, b) => b.periodEnd.localeCompare(a.periodEnd));
  const latest = periods[0];
  const monday = new Date(`${asOf}T12:00:00Z`);
  monday.setUTCDate(monday.getUTCDate() - (monday.getUTCDay() + 6) % 7);
  if (!latest || latest.periodEnd >= monday.toISOString().slice(0, 10)) return gap;
  const label = `最近记录期（${latest.periodStart} 至 ${latest.periodEnd}）`;
  for (const field of ['statement', 'question', 'whyNeeded', 'decisionImpact', 'expectedAnswer']) {
    gap[field] = String(gap[field] || '').replace(/(?:本周|这周|本期|这期|上周)(?:[（(]\d{4}-\d{2}-\d{2}(?:至|~)\d{4}-\d{2}-\d{2}[）)])?/g, label).replace(/下周/g, '下一轮');
  }
  gap.evidencePeriod = { start: latest.periodStart, end: latest.periodEnd, historical: true, asOf };
  return gap;
}

async function refreshKnowledgeGaps(input = {}, deps = {}) {
  const scope = input.scope && typeof input.scope === 'object' ? input.scope : {};
  const context = buildEnterpriseKnowledgeContext({ scope, query: { text: String(input.focus || '企业定位 目标 能力 岗位职责'), assetTypes: ['project_profile', 'venue_profile', 'implicit_knowledge', 'goal', 'decision'] }, limits: { maxItems: 12, maxCharacters: 6000 } });
  const existingKnowledge = knowledgeStateValue();
  const mapScope = { projectId: context.scope.projectId, venueNames: normalizeScopeVenueNames(scope) };
  const knowledgeMap = buildKnowledgeMap(existingKnowledge, mapScope, input.roleId);
  const plannedSlots = selectKnowledgeSlots(knowledgeMap, existingKnowledge, Math.max(1, Math.min(6, Number(input.limit || 4))));
  let proposals = [];
  let modelSucceeded = false;
  let generatedBy = 'enterprise-blueprint';
  let fallbackReason = '';
  if (plannedSlots.length && (deps.requestModel || dailyModelAvailable()) && input.useModel !== false) {
    try {
      const prompt = readJsonFile(KNOWLEDGE_GAP_PROMPT_PATH, {});
      const result = await (deps.requestModel || requestConfiguredModelJson)([
        { role: 'system', content: `${prompt.system || ''}\n本次必须以企业知识地图为主线，只为 plannedSlots 中的维度与切面提出自然问题，原样返回 dimensionId 和 facetId。历史周报异常不作为本次知识建设任务。已知背景不要重复索要，追问其中未明确的边界。问题必须通过答案摆动测试：至少两种合理答案会导致不同建议或执行边界，否则不要占用用户注意力。` },
        { role: 'user', content: JSON.stringify({ decisionFocus: String(input.focus || '').trim() || '建立可供后续经营分析复用的企业认知', knowledgeMap, plannedSlots }) },
        { role: 'user', content: JSON.stringify({ asOf: dailyIsoNow(), ownedVenues: buildKnowledgeCatalog().venues, context, existingGaps: existingKnowledge.gaps.filter(item => enterpriseEventScopeMatches(item, normalizeScopeVenueNames(scope))).slice(-60), confirmedKnowledge: existingKnowledge.implicitItems.filter(item => item.status === 'confirmed' && enterpriseEventScopeMatches(item, normalizeScopeVenueNames(scope))).slice(-40), outputSchema: prompt.outputSchema, maxGaps: Math.max(1, Math.min(6, Number(input.limit || 4))) }) }
      ], 0.1, { taskKey: 'knowledge_gap_discovery', max_tokens: 2200 });
      if (!Array.isArray(result?.result?.gaps)) throw new Error('缺口模型未返回 gaps 数组');
      proposals = result.result.gaps;
      modelSucceeded = true;
      generatedBy = 'external-model';
    } catch (error) { fallbackReason = error.message || String(error); }
  }
  const stateRef = readRuntimeState('knowledge');
  const state = knowledgeStateValue();
  // Model proposes phrasing; the explicit enterprise curriculum owns selection.
  proposals = plannedSlots.map(slot => {
    const phrased = proposals.find(p => p.dimensionId === slot.dimensionId && p.facetId === slot.facetId);
    return { ...slot, ...(phrased ? { question: phrased.question || slot.question, expectedAnswer: phrased.expectedAnswer || slot.expectedAnswer } : {}) };
  });
  const authorizedVenues = normalizeScopeVenueNames(scope);
  const validRefs = new Set(context.items.map(item => item.id));
  const normalized = proposals.map(normalizeKnowledgeGap).filter(item => item.statement && item.scope.projectId === context.scope.projectId && (!item.scope.venueNames.length || item.scope.venueNames.every(name => authorizedVenues.includes(name)))).map(item => groundKnowledgeGapTime({ ...item, sourceRefs: item.sourceRefs.filter(ref => validRefs.has(ref)) }, context)).sort((a, b) => b.valueScore - a.valueScore).slice(0, Math.max(1, Math.min(6, Number(input.limit || 4))));
  const created = [];
  for (const gap of normalized) {
    const existing = state.gaps.find(item => item.id === gap.id || (item.dimensionId === gap.dimensionId && item.facetId === gap.facetId && (gap.dimensionId !== 'role_goals' || item.roleId === gap.roleId) && JSON.stringify(item.scope) === JSON.stringify(gap.scope) && (intelligenceSimilarity(item.statement, gap.statement) >= 0.72 || intelligenceSimilarity(item.question, gap.question) >= 0.8)));
    if (!existing) { state.gaps.push(gap); created.push(gap); }
  }
  state.gaps = state.gaps.slice(-300); state.updatedAt = new Date().toISOString();
  state.discovery = { ...state.discovery, [authorizedVenues.slice().sort().join('|')]: { checkedAt: state.updatedAt, fingerprint: knowledgeDiscoveryFingerprint(), generatedBy, fallbackReason } };
  const saved = writeRuntimeState('knowledge', state, stateRef.revision);
  return { items: state.gaps, created, revision: saved.revision, generatedBy: modelSucceeded ? generatedBy : 'enterprise-blueprint', fallbackReason, knowledgeMap };
}

const gapDiscoveryInFlight = new Map();
function knowledgeDiscoveryFingerprint() {
  const knowledge = knowledgeStateValue();
  return crypto.createHash('sha256').update(JSON.stringify({
    revisions: ['records', 'reports', 'workbench', 'experiences', 'daily'].map(kind => readRuntimeState(kind).revision),
    profile: readStrategyProfile().updatedAt,
    confirmedKnowledge: knowledge.implicitItems.filter(item => item.status === 'confirmed').map(item => [item.id, item.statement]),
    resolved: knowledge.gaps.filter(item => ['confirmed', 'dismissed'].includes(item.status)).map(item => item.id).sort(),
  })).digest('hex').slice(0, 24);
}
function scheduleKnowledgeDiscovery(scope) {
  const key = normalizeScopeVenueNames(scope).sort().join('|');
  const last = knowledgeStateValue().discovery?.[key];
  const cooldown = last?.fallbackReason ? 15 * 60_000 : 24 * 3600_000;
  if (!gapDiscoveryInFlight.has(key) && (!last?.checkedAt || (!last.fallbackReason && last.fingerprint !== knowledgeDiscoveryFingerprint()) || Date.now() - Date.parse(last.checkedAt) >= cooldown)) {
    const job = refreshKnowledgeGaps({ scope, limit: 4 }).catch(error => console.error('knowledge discovery failed:', error.message)).finally(() => gapDiscoveryInFlight.delete(key));
    gapDiscoveryInFlight.set(key, job);
  }
  return gapDiscoveryInFlight.has(key);
}

function enterpriseEventStateValue() {
  const state = readRuntimeState('events').data;
  if (!state || typeof state !== 'object' || Array.isArray(state)) return { schemaVersion: 'enterprise-event-v1', items: [], updatedAt: '' };
  return { schemaVersion: 'enterprise-event-v1', items: Array.isArray(state.items) ? state.items : [], updatedAt: String(state.updatedAt || '') };
}

function normalizeEnterpriseEvent(input = {}) {
  const now = new Date().toISOString();
  const scope = input.scope && typeof input.scope === 'object' ? input.scope : {};
  const dedupeSeed = String(input.dedupeKey || [input.source, input.eventType, input.statement, scope.projectId, ...(scope.venueIds || [])].join('|'));
  return {
    schemaVersion: 'enterprise-event-v1',
    id: String(input.id || `wee_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`).replace(/[^A-Za-z0-9_-]/g, '_').slice(0, 120),
    dedupeKey: crypto.createHash('sha256').update(dedupeSeed).digest('hex').slice(0, 32),
    source: knowledgeSnippet(input.source || 'workbench', 40),
    eventType: knowledgeSnippet(input.eventType || 'knowledge_gap', 80),
    statement: knowledgeSnippet(input.statement || '', 1200),
    expectedAction: knowledgeSnippet(input.expectedAction || '', 600),
    question: knowledgeSnippet(input.question || input.expectedAction || '', 800),
    sourceRefs: Array.isArray(input.sourceRefs) ? input.sourceRefs.map(value => String(value || '').trim()).filter(Boolean).slice(0, 30) : [],
    knowledgeGapId: String(input.knowledgeGapId || '').slice(0, 180),
    decisionImpact: knowledgeSnippet(input.decisionImpact || '', 600),
    expectedAnswer: knowledgeSnippet(input.expectedAnswer || '', 600),
    evidencePeriod: input.evidencePeriod || null,
    // 运行态来源检查的结构化摘要。它只供展示/审计，事实仍以飞书来源表为准。
    monitor: input.monitor && typeof input.monitor === 'object' ? {
      kind: String(input.monitor.kind || '').slice(0, 80),
      status: ['complete', 'in_progress', 'not_started', 'unavailable'].includes(input.monitor.status) ? input.monitor.status : 'unavailable',
      totalSheets: Number(input.monitor.totalSheets || 0),
      readySheets: Number(input.monitor.readySheets || 0),
      dateRows: Number(input.monitor.dateRows || 0),
      missingSheets: Array.isArray(input.monitor.missingSheets) ? input.monitor.missingSheets.map(String).slice(0, 20) : [],
      incompleteSheets: Array.isArray(input.monitor.incompleteSheets) ? input.monitor.incompleteSheets.map(String).slice(0, 20) : [],
      checkedAt: String(input.monitor.checkedAt || '').slice(0, 64),
      sourceRevision: String(input.monitor.sourceRevision || '').slice(0, 120),
    } : null,
    valueScore: Number(input.valueScore) || 0,
    taskType: knowledgeSnippet(input.taskType || 'business_followup', 80),
    actorId: String(input.actorId || '').slice(0, 160),
    scope: {
      projectId: String(scope.projectId || readStrategyProfile().project?.id || 'yuanqu-vr'),
      venueIds: Array.isArray(scope.venueIds) ? scope.venueIds.map(String).slice(0, 20) : [],
      venueNames: Array.isArray(scope.venueNames) ? scope.venueNames.map(String).filter(Boolean).slice(0, 20) : []
    },
    priority: ['low', 'normal', 'high'].includes(input.priority) ? input.priority : 'normal',
    status: 'pending', occurredAt: String(input.occurredAt || now), createdAt: now, updatedAt: now,
    deliveredAt: '', acknowledgedAt: '', deliveryNote: '', expiresAt: String(input.expiresAt || '')
  };
}

function enterpriseEventVenueNames(input = {}, profile = readStrategyProfile()) {
  const raw = [
    ...(Array.isArray(input.venueIds) ? input.venueIds : []),
    ...(Array.isArray(input.venueNames) ? input.venueNames : []),
  ].map(value => String(value || '').trim()).filter(Boolean);
  const policyScope = String(input.policy?.knowledge_scope || '').trim();
  if (!raw.length && policyScope && policyScope !== 'all') raw.push(...policyScope.split(/[,，|]/).map(value => value.trim()).filter(Boolean));
  if (!raw.length || raw.includes('all')) return Object.keys(profile.venues || {});
  return Object.entries(profile.venues || {})
    .filter(([name, venue]) => raw.includes(name) || raw.includes(String(venue?.venueId || '')))
    .map(([name]) => name);
}

function enterpriseEventScopeMatches(item, venueNames) {
  if (!venueNames.length) return true;
  const names = [
    ...(item?.scope?.venueNames || []),
    ...(item?.scope?.venueIds || []),
    item?.venue,
  ].map(value => String(value || '').trim()).filter(Boolean);
  return !names.length || names.some(value => venueNames.includes(value) || venueNames.some(name => String(readStrategyProfile().venues?.[name]?.venueId || '') === value));
}

function eventForOperatingSignal({ sourceKey, signal, venueName, date }) {
  if (!signal || signal.include === false) return null;
  const signalId = String(signal.id || `${sourceKey}:${signal.title || signal.observation || 'signal'}`);
  const observation = knowledgeSnippet(signal.observation || signal.hypothesis || '', 520);
  const title = knowledgeSnippet(signal.title || '待确认经营信号', 180);
  const question = knowledgeSnippet(signal.question || signal.focusedQuestion || `这条变化在现场具体发生了什么？有没有一个可以核对的事实？`, 500);
  return normalizeEnterpriseEvent({
    source: 'workbench', eventType: 'operating_signal',
    dedupeKey: `operating_signal|${signalId}|${sourceKey}|${date}`,
    statement: `${venueName && venueName !== 'all' ? `${venueName}：` : ''}${title}${observation ? `。${observation}` : ''}`,
    expectedAction: question,
    question,
    sourceRefs: Array.isArray(signal.evidenceRefs) ? signal.evidenceRefs : [],
    scope: { projectId: readStrategyProfile().project?.id || 'yuanqu-vr', venueNames: venueName && venueName !== 'all' ? [venueName] : [] },
    priority: signal.priority || 'normal', actorId: '', taskType: 'signal_followup', occurredAt: new Date().toISOString(),
  });
}

function eventForKnowledgeGap({ gap, venueName, date }) {
  if (!gap || !['open', 'asking', 'pending', 'needs_clarification', 'conflicted'].includes(gap.status || gap.reviewStatus)) return null;
  if (gap.acquisitionRoute && gap.acquisitionRoute !== 'operator') return null;
  // 结构性企业知识优先；高价值的经营诊断缺口也可以进入主动协同，
  // 否则“客流口径冲突/下降原因”这类真正阻挡决策的问题永远只能留在周报里。
  const diagnosticEligible = gap.knowledgeTrack !== 'enterprise'
    && gap.priority === 'high'
    && Number(gap.valueScore || 0) >= 34
    && String(gap.decisionImpact || gap.whyNeeded || '').trim();
  if (gap.knowledgeTrack !== 'enterprise' && !diagnosticEligible) return null;
  const statement = knowledgeSnippet(gap.statement || '有一条经营信息还缺少确认', 720);
  const missing = Array.isArray(gap.missingInformation) ? gap.missingInformation.filter(Boolean).slice(0, 2).join('；') : '';
  const question = knowledgeSnippet(gap.question || (missing ? `这件事里，${missing}，你现在能确认哪一部分？` : '这件事在现场具体是怎么发生的？'), 500);
  return normalizeEnterpriseEvent({
    source: 'workbench', eventType: gap.knowledgeTrack === 'enterprise' ? 'knowledge_gap' : 'decision_blocking_diagnostic',
    dedupeKey: `knowledge_gap|${gap.id}|${date}`,
    statement: `${venueName && venueName !== 'all' ? `${venueName}：` : ''}${statement}`,
    expectedAction: question, question,
    knowledgeGapId: gap.id, sourceRefs: gap.sourceRefs || gap.relatedAssetRefs || [],
    decisionImpact: gap.decisionImpact || gap.whyNeeded, expectedAnswer: gap.expectedAnswer, valueScore: gap.valueScore,
    evidencePeriod: gap.evidencePeriod,
    expiresAt: new Date(Date.now() + 48 * 3600_000).toISOString(),
    scope: { projectId: gap.scope?.projectId || readStrategyProfile().project?.id || 'yuanqu-vr', venueNames: gap.scope?.venueNames || (venueName && venueName !== 'all' ? [venueName] : []) },
    priority: gap.priority || 'normal', actorId: gap.actorId || '', taskType: 'knowledge_gap_followup', occurredAt: new Date().toISOString(),
  });
}

async function eventForDailyReport({ date, venueName, actorId, policy = {} }) {
  const payload = await dailyPayload({ date, venue: venueName || 'all', refresh: true, force: false, includeIdeas: false });
  const brief = payload?.brief;
  const liveContext = dailyContext({ date, venue: venueName || 'all' });
  const exactSnapshots = (liveContext.dailySnapshots || []).filter(item => item?.date === date);
  // “每日经营汇报”必须有当天来源快照；周记录覆盖当天不等于当天数据已经产生。
  if (!exactSnapshots.length || !brief || brief.dataAvailable === false || payload?.context?.todayDataAvailable === false) return null;
  if (policy.report_require_complete && Array.isArray(payload?.context?.missingInformation) && payload.context.missingInformation.some(value => /数据|快照|记录/.test(String(value)))) return null;
  if (policy.report_mode === 'significant_only' && brief.actionable !== true) return null;
  const question = policy.report_include_question && brief.canFeedback !== false ? knowledgeSnippet(brief.questionForOperator || '', 500) : '';
  return normalizeEnterpriseEvent({
    source: 'workbench_daily', eventType: 'daily_report', taskType: 'daily_report', actorId,
    dedupeKey: `daily_report|${actorId}|${venueName || 'all'}|${brief.contextFingerprint || date}`,
    statement: knowledgeSnippet([brief.headline, brief.summary, brief.decisionImpact].filter(Boolean).join(' '), 1200),
    expectedAction: question, question,
    sourceRefs: brief.evidenceRefs || [],
    scope: { projectId: readStrategyProfile().project?.id || 'yuanqu-vr', venueNames: venueName && venueName !== 'all' ? [venueName] : [] },
    priority: brief.actionable ? 'high' : 'normal', occurredAt: new Date().toISOString(),
  });
}

function eventForValidation({ validation, venueName, date }) {
  if (!validation || !['ready', '执行中', '待评估'].includes(validation.status)) return null;
  const title = knowledgeSnippet(validation.tacticTitle || validation.title || '进行中的验证', 220);
  const question = knowledgeSnippet(validation.nextAction || `这项验证目前做到哪一步了？结果指标有没有新的记录？`, 500);
  return normalizeEnterpriseEvent({
    source: 'workbench', eventType: 'validation_followup',
    dedupeKey: `validation_followup|${validation.id}|${date}`,
    statement: `${venueName && venueName !== 'all' ? `${venueName}：` : ''}验证“${title}”正在进行中。`,
    expectedAction: question, question,
    knowledgeGapId: '', sourceRefs: validation.id ? [String(validation.id)] : [],
    scope: { projectId: readStrategyProfile().project?.id || 'yuanqu-vr', venueNames: validation.venue && validation.venue !== 'all' ? [validation.venue] : [] },
    priority: 'normal', actorId: '', taskType: 'validation_followup', occurredAt: new Date().toISOString(),
  });
}

/**
 * 根据当前工作台状态生成少量、可追问的企业事件。
 * 这是确定性的供给层：模型只负责把事件说得像溪语，不负责决定是否值得触达。
 */
async function refreshEnterpriseEvents(input = {}) {
  const profile = readStrategyProfile();
  const date = /^\d{4}-\d{2}-\d{2}$/.test(String(input.date || '')) ? String(input.date) : dailyIsoNow();
  const venueNames = enterpriseEventVenueNames(input, profile);
  const projectId = String(input.projectId || profile.project?.id || 'yuanqu-vr');
  const actorId = String(input.actorId || '');
  const state = enterpriseEventStateValue();
  const candidates = [];
  const purposes = new Set(Array.isArray(input.purposes) ? input.purposes : []);
  const legacyAll = purposes.size === 0;
  const policy = input.policy && typeof input.policy === 'object' ? input.policy : {};
  const discoveryPending = (legacyAll || purposes.has('knowledge_acquisition')) && input.discoverGaps !== false
    ? scheduleKnowledgeDiscovery({ projectId, venueNames }) : false;
  // 已有回答等待审核或已解决时，旧的待投递事件不能继续阻挡下一项。
  let retired = false;
  const gapState = knowledgeStateValue();
  for (const event of state.items) {
    const gap = gapState.gaps.find(item => item.id === event.knowledgeGapId);
    if (event.status === 'pending' && ((gap && (gap.knowledgeTrack !== 'enterprise' || ['review_pending', 'confirmed', 'dismissed'].includes(gap.status))) || (event.expiresAt && Date.parse(event.expiresAt) <= Date.now()))) {
      event.status = 'dismissed'; event.updatedAt = new Date().toISOString(); retired = true;
    }
  }
  if (retired) writeRuntimeState('events', state);
  if (legacyAll || purposes.has('daily_report')) {
    const reportVenue = dailyVenueName(policy.report_venue || (venueNames.length === 1 ? venueNames[0] : 'all'));
    const report = await eventForDailyReport({ date, venueName: reportVenue, actorId, policy });
    if (report) candidates.push(report);
  }
  if (purposes.has('order_table_monitor')) {
    // 订单表监控必须绑定具体 actorId；没有收件人时不生成可被他人捞走的事件。
    if (actorId) {
      const monitor = await checkOrderTableMonitor({ date, actorId, projectId });
      const event = eventForOrderTableMonitor({ monitor, projectId, actorId });
      if (event) candidates.push(event);
    }
  }
  const wb = readRuntimeState('workbench').data || {};
  const cache = wb.analysisCache && typeof wb.analysisCache === 'object' ? wb.analysisCache : {};
  for (const [sourceKey, value] of (legacyAll ? Object.entries(cache) : [])) {
    const keyVenue = sourceKey.split('|')[1] || 'all';
    if (venueNames.length && keyVenue !== 'all' && !venueNames.includes(keyVenue)) continue;
    for (const signal of (value?.expertSignals || value?.signals || [])) {
      const event = eventForOperatingSignal({ sourceKey, signal, venueName: keyVenue, date });
      if (event) candidates.push(event);
    }
  }
  const knowledge = knowledgeStateValue();
  const intelligence = intelligenceStateValue();
  const knowledgeGaps = knowledge.gaps.length ? knowledge.gaps : intelligence.items;
  const priorityRank = { high: 3, normal: 2, low: 1 };
  const minKnowledgePriority = ['low', 'normal', 'high'].includes(policy.knowledge_min_priority)
    ? policy.knowledge_min_priority : 'normal';
  const knowledgeMaxPerDay = Math.max(0, Math.min(5, Number(policy.knowledge_max_per_day ?? 1)));
  const knowledgeCreatedToday = state.items.filter(item => {
    if (['dismissed', 'failed'].includes(item.status)) return false;
    if (shanghaiDateKey(item.createdAt || item.occurredAt) !== date) return false;
    if (actorId && item.actorId && item.actorId !== actorId) return false;
    return item.taskType === 'knowledge_gap_followup';
  }).length;
  for (const gap of (legacyAll || purposes.has('knowledge_acquisition') ? knowledgeGaps.slice().reverse() : [])) {
    if (knowledgeMaxPerDay <= knowledgeCreatedToday) break;
    if ((priorityRank[gap.priority] || 0) < (priorityRank[minKnowledgePriority] || 2)) continue;
    const gapVenues = gap.scope?.venueNames || [];
    const venueName = gapVenues[0] || (venueNames.length === 1 ? venueNames[0] : 'all');
    if (gap.scope?.projectId && gap.scope.projectId !== projectId) continue;
    if (venueNames.length && gapVenues.length && !gapVenues.some(value => venueNames.includes(value))) continue;
    const event = eventForKnowledgeGap({ gap, venueName, date });
    if (event) candidates.push(event);
  }
  const plans = legacyAll && Array.isArray(wb.tacticPlans) ? wb.tacticPlans : [];
  for (const plan of plans) {
    if (venueNames.length && plan.venue && plan.venue !== 'all' && !venueNames.includes(plan.venue)) continue;
    const event = eventForValidation({ validation: plan, venueName: plan.venue || 'all', date });
    if (event) candidates.push(event);
  }
  // 没有缺口/信号时，不制造“今天一切正常”的打扰消息。
  // 日报与知识补全各自最多保留一个候选，避免一条业务类型占掉另一条类型的机会。
  const requestedTaskTypes = purposes.size ? purposes : new Set(['daily_report', 'knowledge_acquisition', 'signal_followup', 'validation_followup', 'knowledge_gap_followup']);
  const eventPurpose = item => item.taskType === 'daily_report' ? 'daily_report' : item.taskType === 'knowledge_gap_followup' ? 'knowledge_acquisition' : item.taskType;
  const pendingPurposes = new Set(state.items
    .filter(item => item.status === 'pending' && (!actorId || !item.actorId || item.actorId === actorId))
    .map(eventPurpose));
  const todayPurposes = new Set(state.items
    .filter(item => !['dismissed', 'failed'].includes(item.status)
      && shanghaiDateKey(item.createdAt || item.occurredAt) === date
      && (!actorId || !item.actorId || item.actorId === actorId))
    .map(eventPurpose));
  const created = [];
  candidates.sort((left, right) => (priorityRank[right.priority] || 0) - (priorityRank[left.priority] || 0) || (right.valueScore || 0) - (left.valueScore || 0));
  for (const candidate of candidates) {
    const purpose = eventPurpose(candidate);
    if (!requestedTaskTypes.has(purpose)) continue;
    if (pendingPurposes.has(purpose) || todayPurposes.has(purpose)) continue;
    if (purpose === 'knowledge_acquisition' && knowledgeCreatedToday + created.filter(item => eventPurpose(item) === purpose).length >= knowledgeMaxPerDay) continue;
    candidate.actorId = actorId;
    candidate.scope.projectId = projectId;
    const duplicate = state.items.find(item => item.dedupeKey === candidate.dedupeKey && !['dismissed', 'failed'].includes(item.status));
    if (duplicate) continue;
    state.items.push(candidate);
    created.push(candidate);
    pendingPurposes.add(purpose);
    todayPurposes.add(purpose);
  }
  state.items = state.items.slice(-1000);
  state.updatedAt = new Date().toISOString();
  const saved = created.length ? writeRuntimeState('events', state) : { revision: readRuntimeState('events').revision };
  return { date, projectId, venueNames, discoveryPending, created, revision: saved.revision, totalPending: state.items.filter(item => item.status === 'pending').length };
}

function normalizeIntelligenceCandidate(input = {}, req) {
  const now = new Date().toISOString();
  const source = input.source && typeof input.source === 'object' ? input.source : {};
  const scope = input.scope && typeof input.scope === 'object' ? input.scope : {};
  const suggestedTarget = input.suggestedTarget && typeof input.suggestedTarget === 'object'
    ? (input.suggestedTarget.label || input.suggestedTarget.type || JSON.stringify(input.suggestedTarget))
    : input.suggestedTarget;
  const id = String(input.id || `wic_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`).replace(/[^A-Za-z0-9_-]/g, '_').slice(0, 120);
  const allowedTypes = new Set(['operating_fact_candidate', 'profile_revision_candidate', 'operator_claim', 'opportunity_candidate', 'tactic_idea_candidate', 'validation_update_candidate', 'result_claim_candidate', 'experience_candidate']);
  const allowedStatus = new Set(['pending', 'needs_clarification', 'accepted', 'linked', 'rejected', 'duplicate', 'conflicted']);
  return {
    schemaVersion: 'work-intelligence-candidate-v1',
    id,
    source: {
      channel: 'xiyu_conversation',
      actorId: String(source.actorId || input.actorId || '').slice(0, 160),
      conversationId: String(source.conversationId || '').slice(0, 160),
      turnId: String(source.turnId || '').slice(0, 160),
      occurredAt: String(source.occurredAt || now),
      quote: knowledgeSnippet(source.quote || input.quote || '', 600)
    },
    scope: {
      projectId: String(scope.projectId || readStrategyProfile().project?.id || 'yuanqu-vr'),
      venueIds: Array.isArray(scope.venueIds) ? scope.venueIds.map(String).slice(0, 20) : [],
      venueNames: (scope.venueNames?.length || scope.venueIds?.length) ? normalizeScopeVenueNames(scope).slice(0, 20) : []
    },
    candidateType: allowedTypes.has(input.candidateType) ? input.candidateType : 'operator_claim',
    epistemicStatus: knowledgeSnippet(input.epistemicStatus || 'operator_claim', 80),
    statement: knowledgeSnippet(input.statement || '', 1200),
    businessTopics: Array.isArray(input.businessTopics) ? input.businessTopics.map(String).slice(0, 20) : [],
    metricIds: Array.isArray(input.metricIds) ? input.metricIds.map(String).slice(0, 20) : [],
    timeRange: input.timeRange && typeof input.timeRange === 'object' ? { start: input.timeRange.start || null, end: input.timeRange.end || null, precision: String(input.timeRange.precision || 'unknown') } : { start: null, end: null, precision: 'unknown' },
    suggestedTarget: knowledgeSnippet(suggestedTarget || '', 80),
    relatedAssetRefs: Array.isArray(input.relatedAssetRefs) ? input.relatedAssetRefs.map(String).slice(0, 30) : [],
    conversationTaskRef: String(input.conversationTaskRef || '').slice(0, 180),
    knowledgeGapId: String(input.knowledgeGapId || '').slice(0, 180),
    supportingEvidenceRefs: Array.isArray(input.supportingEvidenceRefs) ? input.supportingEvidenceRefs.map(String).slice(0, 30) : [],
    missingInformation: Array.isArray(input.missingInformation) ? input.missingInformation.map(String).slice(0, 20) : [],
    evidenceLimitations: Array.isArray(input.evidenceLimitations) ? input.evidenceLimitations.map(String).slice(0, 20) : [],
    conflicts: Array.isArray(input.conflicts) ? input.conflicts.map(String).slice(0, 20) : [],
    confidence: Number.isFinite(Number(input.confidence)) ? Math.max(0, Math.min(1, Number(input.confidence))) : 0,
    reviewStatus: allowedStatus.has(input.reviewStatus) ? input.reviewStatus : 'pending',
    createdAt: String(input.createdAt || now),
    updatedAt: now,
    promptVersion: String(input.promptVersion || 'work-intelligence-extractor-v1'),
    idempotencyKey: String(req?.headers?.['idempotency-key'] || input.idempotencyKey || '').slice(0, 180)
  };
}

function intelligenceTextTokens(value) {
  const compact = String(value || '').toLowerCase().replace(/[\s，。！？、；：,.!?;:'"“”‘’（）()\[\]{}-]+/g, '');
  const tokens = new Set((String(value || '').toLowerCase().match(/[a-z0-9_]{2,}/g) || []));
  for (const char of compact) if (/[^a-z0-9_]/.test(char)) tokens.add(`c:${char}`);
  for (let index = 0; index < compact.length - 1; index++) tokens.add(`b:${compact.slice(index, index + 2)}`);
  return tokens;
}

function intelligenceSimilarity(left, right) {
  const a = intelligenceTextTokens(left), b = intelligenceTextTokens(right);
  if (!a.size || !b.size) return 0;
  let shared = 0;
  for (const token of a) if (b.has(token)) shared++;
  return shared / Math.max(a.size, b.size);
}

function sameIntelligenceScope(left, right) {
  if (left?.scope?.projectId !== right?.scope?.projectId) return false;
  const a = new Set([...(left?.scope?.venueIds || []), ...(left?.scope?.venueNames || [])]);
  const b = new Set([...(right?.scope?.venueIds || []), ...(right?.scope?.venueNames || [])]);
  return !a.size || !b.size || [...a].some(value => b.has(value));
}

function intelligenceConflictReason(left, right) {
  if (!sameIntelligenceScope(left, right)) return '';
  const sharedTopics = (left.businessTopics || []).some(value => (right.businessTopics || []).includes(value));
  const sharedMetrics = (left.metricIds || []).some(value => (right.metricIds || []).includes(value));
  if (!sharedTopics && !sharedMetrics) return '';
  const a = String(left.statement || ''), b = String(right.statement || '');
  const opposites = [['增加','减少'],['上升','下降'],['上涨','下跌'],['开放','关闭'],['有效','无效'],['已完成','未完成']];
  const pair = opposites.find(([positive, negative]) => (a.includes(positive) && b.includes(negative)) || (a.includes(negative) && b.includes(positive)));
  if (pair) return `与候选 ${left.id} 在同一经营主题下出现相反表述（${pair.join(' / ')}）`;
  const sameRange = JSON.stringify(left.timeRange || {}) === JSON.stringify(right.timeRange || {});
  const aNumbers = a.match(/-?\d+(?:\.\d+)?%?/g) || [], bNumbers = b.match(/-?\d+(?:\.\d+)?%?/g) || [];
  if (sharedMetrics && sameRange && aNumbers.length && bNumbers.length && aNumbers.join('|') !== bNumbers.join('|')) return `与候选 ${left.id} 的同周期指标数值不一致`;
  return '';
}

function defaultIntelligenceTarget(type) {
  return ({ operating_fact_candidate: 'operating_fact', profile_revision_candidate: 'profile', operator_claim: 'implicit_knowledge', opportunity_candidate: 'opportunity', tactic_idea_candidate: 'tactic', validation_update_candidate: 'validation', experience_candidate: 'experience' })[type] || 'implicit_knowledge';
}

function reconcileCandidateGap(candidate, application = null) {
  if (!candidate.knowledgeGapId) return;
  const ref = readRuntimeState('knowledge');
  const knowledge = knowledgeStateValue();
  const gap = knowledge.gaps.find(item => item.id === candidate.knowledgeGapId);
  if (!gap || !sameIntelligenceScope(gap, candidate) || ['confirmed', 'dismissed'].includes(gap.status)) return;
  const now = new Date().toISOString();
  if (application?.status === 'confirmed' && !(candidate.missingInformation?.length || candidate.conflicts?.length)) {
    gap.status = 'confirmed'; gap.resolvedAt = now; gap.resolutionAssetRef = application.assetId;
    const events = enterpriseEventStateValue();
    for (const event of events.items.filter(item => item.knowledgeGapId === gap.id && !['dismissed', 'failed'].includes(item.status))) {
      event.status = 'acknowledged'; event.acknowledgedAt = now; event.updatedAt = now;
    }
    events.updatedAt = now; writeRuntimeState('events', events);
  } else {
    const pending = intelligenceStateValue().items.filter(item => item.knowledgeGapId === gap.id && ['pending', 'accepted'].includes(item.reviewStatus) && !(item.missingInformation?.length || item.conflicts?.length));
    gap.status = pending.length ? 'review_pending' : 'open';
    gap.pendingCandidateIds = pending.map(item => item.id);
  }
  gap.updatedAt = now; knowledge.updatedAt = now; writeRuntimeState('knowledge', knowledge, ref.revision);
}

function applyIntelligenceCandidate(candidate, requestedTarget = '') {
  if (['rejected', 'conflicted', 'duplicate'].includes(candidate.reviewStatus) || candidate.conflicts?.length) throw new Error('请先解决候选冲突或退回状态，再确认应用');
  const allowedTargets = new Set(['operating_fact', 'implicit_knowledge', 'profile', 'opportunity', 'tactic', 'validation', 'experience']);
  const enterpriseGap = knowledgeStateValue().gaps.find(g => g.id === candidate.knowledgeGapId && g.knowledgeTrack === 'enterprise');
  const target = enterpriseGap ? 'implicit_knowledge' : allowedTargets.has(requestedTarget) ? requestedTarget : defaultIntelligenceTarget(candidate.candidateType);
  const now = new Date().toISOString();
  if (target === 'implicit_knowledge') {
    const knowledgeState = readRuntimeState('knowledge');
    const knowledge = knowledgeStateValue();
    const assetId = `xiyu-implicit-${candidate.id}`;
    if (!knowledge.implicitItems.some(item => item.id === assetId)) {
      const gap = knowledge.gaps.find(g => g.id === candidate.knowledgeGapId);
      knowledge.implicitItems.push({ id: assetId, dimensionId: gap?.dimensionId || '', facetId: gap?.facetId || '', roleId: gap?.roleId || '', title: candidate.businessTopics?.[0] || '运营者隐性知识', statement: candidate.statement, scope: candidate.scope, timeRange: candidate.timeRange, sourceRefs: [...new Set([candidate.id, ...(candidate.supportingEvidenceRefs || [])])], sourceCandidateId: candidate.id, status: 'confirmed', confirmedAt: now, createdAt: now, updatedAt: now });
    }
    knowledge.updatedAt = now;
    writeRuntimeState('knowledge', knowledge, knowledgeState.revision);
    return { target, assetId, status: 'confirmed' };
  }
  const wbState = readRuntimeState('workbench');
  const wb = wbState.data && typeof wbState.data === 'object' ? wbState.data : {};
  wb.intelligenceAssets = Array.isArray(wb.intelligenceAssets) ? wb.intelligenceAssets : [];
  const assetId = `xiyu-${target}-${candidate.id}`;
  let asset = wb.intelligenceAssets.find(item => item.id === assetId);
  if (!asset) {
    asset = { id: assetId, sourceCandidateId: candidate.id, targetType: target, statement: candidate.statement, scope: candidate.scope, timeRange: candidate.timeRange, businessTopics: candidate.businessTopics, supportingEvidenceRefs: candidate.supportingEvidenceRefs, status: target === 'experience' ? 'draft' : 'confirmed', createdAt: now, updatedAt: now };
    wb.intelligenceAssets.push(asset);
  }
  if (target === 'tactic' && !(wb.tacticPlans || []).some(plan => plan.id === assetId)) {
    wb.tacticPlans = Array.isArray(wb.tacticPlans) ? wb.tacticPlans : [];
    wb.tacticPlans.push({ id: assetId, tacticTitle: candidate.statement, venue: candidate.scope?.venueNames?.[0] || 'all', status: 'draft', sourceCandidateId: candidate.id, createdAt: now, updatedAt: now });
  }
  if (target === 'validation') {
    const related = (wb.tacticPlans || []).find(plan => (candidate.relatedAssetRefs || []).includes(plan.id));
    if (related) {
      related.intelligenceUpdates = Array.isArray(related.intelligenceUpdates) ? related.intelligenceUpdates : [];
      related.intelligenceUpdates.push({ candidateId: candidate.id, statement: candidate.statement, createdAt: now });
      related.updatedAt = now; asset.relatedAssetRef = related.id;
    } else asset.status = 'needs_link';
  }
  writeRuntimeState('workbench', wb, wbState.revision);
  if (target === 'experience') {
    const expState = readRuntimeState('experiences');
    const exp = expState.data && typeof expState.data === 'object' ? expState.data : { schemaVersion: 'experience-library-v1', items: [] };
    exp.items = Array.isArray(exp.items) ? exp.items : [];
    if (!exp.items.some(item => item.id === assetId)) exp.items.push({ id: assetId, type: 'experience_candidate', title: candidate.statement, background: candidate.source?.quote || '', evidence: (candidate.supportingEvidenceRefs || []).join('；'), status: 'pending_review', retrievalEligible: false, retrievalReason: '溪语候选已确认，仍需完成验证和发布审核', sourceCandidateId: candidate.id, createdAt: now, updatedAt: now });
    exp.updatedAt = now;
    writeRuntimeState('experiences', exp, expState.revision);
  }
  return { target, assetId, status: asset.status };
}

async function searchGithubRepositories(query) {
  const headers = { 'Accept': 'application/vnd.github+json', 'User-Agent': 'yuanqu-operating-strategy-workbench' };
  if (process.env.GITHUB_TOKEN) headers.Authorization = `Bearer ${process.env.GITHUB_TOKEN}`;
  const response = await fetch(`https://api.github.com/search/repositories?q=${encodeURIComponent(query)}&sort=stars&order=desc&per_page=5`, { headers });
  if (!response.ok) throw new Error(`GitHub search HTTP ${response.status}`);
  const body = await response.json();
  return (body.items || []).map(item => ({
    id: item.id,
    name: item.full_name,
    url: item.html_url,
    description: item.description || '',
    stars: item.stargazers_count || 0,
    language: item.language || '',
    license: item.license?.spdx_id || '',
    updatedAt: item.updated_at || ''
  }));
}

function stripHtml(value = '') {
  return String(value || '').replace(/<script[\s\S]*?<\/script>/gi, ' ').replace(/<style[\s\S]*?<\/style>/gi, ' ').replace(/<[^>]+>/g, ' ').replace(/&nbsp;/gi, ' ').replace(/&amp;/gi, '&').replace(/&#39;/g, "'").replace(/&quot;/g, ' ').replace(/\s+/g, ' ').trim();
}

async function fetchExternal(url, options = {}, timeoutMs = 15000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try { return await fetch(url, { ...options, signal: controller.signal }); }
  catch (error) { if (error.name === 'AbortError') throw new Error(`外部请求超时（>${Math.round(timeoutMs / 1000)}s）`); throw error; }
  finally { clearTimeout(timer); }
}

function normalizeExternalResults(items = [], query = '') {
  const seen = new Set();
  return (Array.isArray(items) ? items : []).map((item, index) => {
    const url = String(item?.url || item?.link || '').trim();
    if (!url || seen.has(url)) return null;
    seen.add(url);
    return { id: String(item?.id || `external-${Date.now()}-${index}`), title: String(item?.title || item?.name || url).trim().slice(0, 240), url, snippet: stripHtml(item?.snippet || item?.description || '').slice(0, 600), sourceType: String(item?.sourceType || 'web'), query, fetchedAt: new Date().toISOString() };
  }).filter(Boolean).slice(0, 8);
}

async function searchExternalWeb(query, options = {}) {
  const cleanQuery = String(query || '').trim();
  if (!cleanQuery || cleanQuery.length > 240) throw new Error('外部检索关键词不能为空且不能超过240个字符');
  const provider = String(process.env.EXTERNAL_SEARCH_PROVIDER || 'manual').toLowerCase();
  if (provider === 'manual' || provider === 'disabled') return { provider, results: [], message: '当前仅允许手动添加来源链接。' };
  if (process.env.EXTERNAL_SEARCH_API_ENDPOINT) {
    const headers = { 'Content-Type': 'application/json' };
    if (process.env.EXTERNAL_SEARCH_API_KEY) headers.Authorization = `Bearer ${process.env.EXTERNAL_SEARCH_API_KEY}`;
    const response = await fetchExternal(process.env.EXTERNAL_SEARCH_API_ENDPOINT, { method: 'POST', headers, body: JSON.stringify({ query: cleanQuery, scope: options.scope || 'project', venue: options.venue || 'all', limit: 8 }) });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(`外部检索服务 HTTP ${response.status}`);
    return { provider: 'configured', results: normalizeExternalResults(body.results || body.items || body.data, cleanQuery), fetchedAt: new Date().toISOString() };
  }
  if (provider !== 'duckduckgo') return { provider: 'not-configured', results: [], message: '未配置可用的外部检索服务，请在服务端配置 EXTERNAL_SEARCH_API_ENDPOINT。' };
  const response = await fetchExternal(`https://html.duckduckgo.com/html/?q=${encodeURIComponent(cleanQuery)}`, { headers: { 'User-Agent': 'yuanqu-operating-strategy-workbench/1.0' } });
  const html = await response.text();
  if (!response.ok) throw new Error(`外部检索 HTTP ${response.status}`);
  const results = [];
  const blocks = html.match(/<div class="result results_links[^>]*>[\s\S]*?<\/div>\s*<\/div>/gi) || [];
  for (const block of blocks) {
    const link = block.match(/<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/i);
    if (!link) continue;
    const snippet = block.match(/class="result__snippet"[^>]*>([\s\S]*?)<\/a?>/i);
    results.push({ title: stripHtml(link[2]), url: link[1], snippet: stripHtml(snippet?.[1] || '') });
  }
  return { provider: 'duckduckgo', results: normalizeExternalResults(results, cleanQuery), fetchedAt: new Date().toISOString() };
}

async function readExternalSource(url) {
  const parsed = new URL(String(url || ''));
  if (!/^https?:$/.test(parsed.protocol)) throw new Error('来源链接必须是 http 或 https');
  const response = await fetchExternal(parsed, { headers: { 'User-Agent': 'yuanqu-operating-strategy-workbench/1.0' } });
  const html = await response.text();
  if (!response.ok) throw new Error(`来源读取 HTTP ${response.status}`);
  const title = stripHtml((html.match(/<title[^>]*>([\s\S]*?)<\/title>/i) || [,''])[1]) || parsed.hostname;
  return { id: `external-${Date.now().toString(36)}`, title: title.slice(0, 240), url: parsed.toString(), snippet: stripHtml(html).slice(0, 1000), sourceType: 'manual_url', fetchedAt: new Date().toISOString() };
}

function colLetter(n) {
  let out = '';
  for (let x = n; x > 0; x = Math.floor((x - 1) / 26)) out = String.fromCharCode(65 + ((x - 1) % 26)) + out;
  return out;
}

function cleanCell(cell) {
  if (!cell || typeof cell !== 'object' || !Object.prototype.hasOwnProperty.call(cell, 'value')) return '';
  return cell.value;
}

async function tenantAccessToken() {
  if (!APP_ID || !APP_SECRET) throw new Error('后端缺少 FEISHU_APP_ID 或 FEISHU_APP_SECRET');
  if (tokenCache && tokenCache.expiresAt > Date.now() + 60_000) return tokenCache.value;
  const response = await fetch(`${API_BASE}/auth/v3/tenant_access_token/internal`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ app_id: APP_ID, app_secret: APP_SECRET }) });
  const body = await response.json().catch(() => ({}));
  if (!response.ok || body.code !== 0 || !body.tenant_access_token) throw new Error(`获取飞书访问令牌失败：${body.msg || `HTTP ${response.status}`}`);
  tokenCache = { value: body.tenant_access_token, expiresAt: Date.now() + Number(body.expire || 7200) * 1000 };
  return tokenCache.value;
}

async function feishuRequest(method, endpoint, body) {
  const token = await tenantAccessToken();
  const response = await fetch(`${API_BASE}${endpoint}`, { method, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || (data.code !== undefined && data.code !== 0)) throw new Error(`飞书 API 失败：${data.msg || `HTTP ${response.status}`}（code ${data.code ?? response.status}）`);
  return data;
}

function excelSerialToIso(value) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 1) return value;
  const date = new Date(Date.UTC(1899, 11, 30) + Math.round(value) * 86400000);
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, '0')}-${String(date.getUTCDate()).padStart(2, '0')}`;
}

function isoToExcelSerial(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  return Math.round((Date.parse(`${value}T00:00:00Z`) - Date.parse('1899-12-30T00:00:00Z')) / 86400000);
}

function isDateHeader(header) { return /^(周开始|周结束|业务日期|快照日期)$/.test(String(header || '')); }

async function readSheet(sheetId, maxRows = 500) {
  return readSheetFromToken(SPREADSHEET_TOKEN, sheetId, maxRows);
}

async function readSheetFromToken(spreadsheetToken, sheetId, maxRows = 500, valueRenderOption = '') {
  if (!spreadsheetToken) throw new Error('未配置来源表格 token');
  const range = `${sheetId}!A1:Z${maxRows}`;
  const renderQuery = valueRenderOption ? `?valueRenderOption=${encodeURIComponent(valueRenderOption)}` : '';
  const data = await feishuRequest('GET', `/sheets/v2/spreadsheets/${encodeURIComponent(spreadsheetToken)}/values/${encodeURIComponent(range)}${renderQuery}`);
  const values = data?.data?.valueRange?.values || [];
  const headers = values[0] || [];
  const headerIndex = Object.fromEntries(headers.map((h, i) => [String(h || '').trim(), i]));
  const rows = values.slice(1).map((row, i) => ({ rowNumber: i + 2, values: headers.map((header, j) => isDateHeader(header) ? excelSerialToIso(row?.[j] ?? '') : (row?.[j] ?? '')) }));
  return { headers, headerIndex, rows, revision: data?.data?.revision || data?.data?.valueRange?.revision };
}

function sourceDate(value) {
  if (typeof value === 'number') return excelSerialToIso(value);
  const text = String(value ?? '').trim();
  if (!text) return '';
  const slash = text.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  if (slash) return `${slash[3]}-${String(slash[1]).padStart(2, '0')}-${String(slash[2]).padStart(2, '0')}`;
  const dash = text.match(/^(\d{4})[-\/]([01]?\d)[-\/]([0-3]?\d)$/);
  if (dash) return `${dash[1]}-${String(dash[2]).padStart(2, '0')}-${String(dash[3]).padStart(2, '0')}`;
  return text;
}

function sourceNumber(value) {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(String(value).replace(/,/g, '').replace(/%$/, ''));
  return Number.isFinite(n) ? Math.round((n + Number.EPSILON) * 100) / 100 : null;
}

function sumNumbers(values) {
  const present = values.filter(value => value !== null && value !== undefined && value !== '');
  return present.length ? Math.round((present.reduce((sum, value) => sum + Number(value || 0), 0) + Number.EPSILON) * 100) / 100 : null;
}

async function lookupSourceFact(plan) {
  const profile = readStrategyProfile();
  const metrics = { box_office_total: '今日销售额', sales_order_count: '今日票数', platform_settlement: '今日实收额' };
  return executeSourceLookup(plan, {
    parseDate: value => sourceDate(typeof value === 'number' ? excelSerialToIso(value) : value), parseNumber: sourceNumber,
    readRange: async (token, range) => {
      const data = await feishuRequest('GET', `/sheets/v2/spreadsheets/${encodeURIComponent(token)}/values/${encodeURIComponent(range)}?valueRenderOption=FormattedValue`);
      return data?.data?.valueRange?.values || [];
    },
    sources: {
      channel_daily: { token: SOURCE_SPREADSHEET_TOKEN, title: '运营渠道日销售来源表', url: SOURCE_WORKBOOK_URL, dateHeader: '日期',
        sheets: venue => Object.entries(profile.venues?.[venue]?.sourceSheets || SOURCE_SHEETS[venue] || {}).map(([channel,id]) => ({ channel,id })),
        value: (row,metric,channel) => metrics[metric] ? row[metrics[metric]] : metric === 'online_sales_amount' ? row[channel === '小程序' ? '今日非线下销售额' : '今日销售额'] : channel === '小程序' ? row['今日线下销售额'] : 0,
        boundary: '全部商品、已接入渠道的销售汇总；不等于利润、结算或来源表以外渠道的完整营收。' },
      daily_traffic: { token: SPREADSHEET_TOKEN, title: TARGET.workbook?.title || '周报辅助表', url: TARGET.workbook?.url || '', dateHeader: '业务日期', venueHeader: '门店ID',
        sheets: () => TARGET.sheets?.daily_traffic?.sheetId ? [{ id: TARGET.sheets.daily_traffic.sheetId }] : [],
        value: (row,metric) => row[TARGET.sheets.daily_traffic.columns[metric]],
        boundary: '来源为录入客流；大盘客流不自动等同商场自然客流，转化人数不等同销售票数。' },
    },
  });
}

async function sourcePreview(input = {}) {
  if (!SOURCE_SPREADSHEET_TOKEN) throw new Error('后端尚未配置来源表格 token');
  const venue = String(input.venue || '').trim();
  const periodStart = sourceDate(input.periodStart);
  const periodEnd = sourceDate(input.periodEnd);
  const profile = readStrategyProfile();
  const configuredSheets = profile.venues?.[venue]?.sourceSheets || SOURCE_SHEETS[venue] || {};
  if (!Object.keys(configuredSheets).length) throw new Error(`来源表暂不支持“${venue}”；请先在项目档案为该门店配置来源页签 ID`);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(periodStart) || !/^\d{4}-\d{2}-\d{2}$/.test(periodEnd) || periodEnd < periodStart) throw new Error('周期间必须是有效的真实日期');

  const dateList = [];
  for (let cursor = new Date(`${periodStart}T00:00:00Z`); cursor <= new Date(`${periodEnd}T00:00:00Z`); cursor.setUTCDate(cursor.getUTCDate() + 1)) dateList.push(cursor.toISOString().slice(0, 10));
  const daily = Object.fromEntries(dateList.map(date => [date, { sales: [], net: [], tickets: [], redeemed: [], onlineSales: [], offlineSales: [], onlineTickets: [], offlineTickets: [], sources: [] }]));
  const channelRows = {};
  let revision = null;
  for (const [channel, sheetId] of Object.entries(configuredSheets)) {
    const sheet = await readSheetFromToken(SOURCE_SPREADSHEET_TOKEN, sheetId, 260, 'FormattedValue');
    revision = sheet.revision || revision;
    const index = Object.fromEntries(sheet.headers.map((header, i) => [String(header || '').trim(), i]));
    const isMini = channel === '小程序';
    const metrics = { tickets: [], sales: [], net: [], redeemed: [], onlineSales: [], offlineSales: [], onlineTickets: [], offlineTickets: [] };
    for (const row of sheet.rows) {
      const rawDate = row.values[index['日期']];
      const date = sourceDate(rawDate);
      if (!daily[date]) continue;
      const tickets = sourceNumber(row.values[index['今日票数']]);
      const sales = sourceNumber(row.values[index['今日销售额']]);
      const net = sourceNumber(row.values[index[isMini ? '今日实收额' : '今日实收额']]);
      const redeemed = sourceNumber(row.values[index['今日核销人数']]);
      const onlineSales = isMini ? sourceNumber(row.values[index['今日非线下销售额']]) : sales;
      const offlineSales = isMini ? sourceNumber(row.values[index['今日线下销售额']]) : null;
      const onlineTickets = isMini ? sourceNumber(row.values[index['今日非线下销售数']]) : tickets;
      const offlineTickets = isMini ? sourceNumber(row.values[index['今日线下销售数']]) : null;
      daily[date].sales.push(sales); daily[date].net.push(net); daily[date].tickets.push(tickets); daily[date].redeemed.push(redeemed);
      daily[date].onlineSales.push(onlineSales); daily[date].offlineSales.push(offlineSales); daily[date].onlineTickets.push(onlineTickets); daily[date].offlineTickets.push(offlineTickets); daily[date].sources.push({ channel, sheet: sheet.headers.length ? sheetId : sheetId, row: row.rowNumber });
      metrics.tickets.push(tickets); metrics.sales.push(sales); metrics.net.push(net); metrics.redeemed.push(redeemed); metrics.onlineSales.push(onlineSales); metrics.offlineSales.push(offlineSales); metrics.onlineTickets.push(onlineTickets); metrics.offlineTickets.push(offlineTickets);
    }
    channelRows[channel] = {
      sheetId,
      sheetName: channel,
      sourceChannel: channel,
      targetChannel: channel === '开店宝' ? '大众' : channel === '小程序' ? '小程序其他 / 线下' : channel,
      datesFound: Object.keys(daily).filter(date => daily[date].sources.some(source => source.channel === channel)).length,
      tickets: sumNumbers(metrics.tickets),
      sales: sumNumbers(metrics.sales),
      net: sumNumbers(metrics.net),
      redeemed: sumNumbers(metrics.redeemed),
      onlineSales: sumNumbers(metrics.onlineSales),
      offlineSales: sumNumbers(metrics.offlineSales),
      onlineTickets: sumNumbers(metrics.onlineTickets),
      offlineTickets: sumNumbers(metrics.offlineTickets),
      applyAmount: isMini ? sumNumbers(metrics.onlineSales) : sumNumbers(metrics.sales)
    };
  }
  const dailyRows = dateList.map(date => ({
    date,
    sales: sumNumbers(daily[date].sales),
    net: sumNumbers(daily[date].net),
    tickets: sumNumbers(daily[date].tickets),
    redeemed: sumNumbers(daily[date].redeemed),
    onlineSales: sumNumbers(daily[date].onlineSales),
    offlineSales: sumNumbers(daily[date].offlineSales),
    sourceRows: daily[date].sources.length,
    missing: daily[date].sources.length === 0
  }));
  const weekly = {
    sales: sumNumbers(dailyRows.map(row => row.sales)),
    net: sumNumbers(dailyRows.map(row => row.net)),
    tickets: sumNumbers(dailyRows.map(row => row.tickets)),
    redeemed: sumNumbers(dailyRows.map(row => row.redeemed)),
    onlineSales: sumNumbers(dailyRows.map(row => row.onlineSales)),
    offlineSales: sumNumbers(dailyRows.map(row => row.offlineSales))
  };
  return {
    ok: true,
    source: { title: '运营渠道日销售来源表', url: SOURCE_WORKBOOK_URL, revision, periodStart, periodEnd, venue },
    channels: channelRows,
    daily: dailyRows,
    weekly,
    groups: [
      { id: 'channel_amounts', label: '各渠道销售额（全部商品）', status: '建议应用', canApply: true, defaultChecked: true, description: '按渠道写入全部商品销售额；开店宝写入“大众”，小程序按非线下/线下拆开。' },
      { id: 'channel_tickets', label: '各渠道销售票数（全部商品）', status: '建议应用', canApply: true, defaultChecked: true, description: '取各渠道“今日票数”；小程序按“今日非线下销售数/今日线下销售数”拆开。' },
      { id: 'daily_box_office', label: '日票房与周票房', status: '待确认口径', canApply: true, description: '按所有已接入渠道的“今日销售额”汇总；不代表来源表之外的渠道。' },
      { id: 'online_sales_amount', label: '线上销售额', status: '待确认口径', canApply: true, description: '普通渠道取销售额，小程序取“今日非线下销售额”。' },
      { id: 'offline_sales_amount', label: '线下销售额', status: '已确认来源', canApply: true, defaultChecked: true, description: '取小程序“今日线下销售额”；分销默认与它同源，不另行相加。' },
      { id: 'platform_settlement', label: '平台实收额', status: '待确认口径', canApply: true, description: '按“今日实收额”汇总，需确认与扣佣结算口径一致。' },
      { id: 'sales_tickets', label: '销售票数', status: '建议应用', canApply: true, defaultChecked: true, description: '按订单明细汇总表各渠道的“今日票数”逐日汇总。' },
      { id: 'channel_scope', label: '渠道与次卡口径', status: '说明', canApply: false, description: '渠道数据包含该渠道售出的全部商品，不等于次卡销售；次卡数据需在独立区块填写。' }
    ],
    warnings: [
      '来源表已覆盖大众（开店宝）及线下/分销（小程序线下）；大众、分销不得作为独立来源重复相加。',
      '渠道销售票数和销售额均为全部商品口径，不得当作次卡销售数据。',
      '来源表之外的渠道仍需人工填写。',
      '累计列未参与求和；系统只使用每日列。',
      ...dailyRows.filter(row => row.missing).map(row => `${row.date} 没有任何来源行，未按 0 处理。`)
    ]
  };
}

// ─── 订单系统汇总表监控（复用现有飞书来源适配器） ─────────────────────────
// 监控只回答“今天十个业务页签有没有完成更新”，不写周报、不改经营事实。
// 收件人由上游溪语账号的 actorId 决定；这里绝不广播给所有已绑定角色。
function orderMonitorSheets(profile = readStrategyProfile()) {
  const rows = [];
  for (const [venue, venueProfile] of Object.entries(profile.venues || {})) {
    const sheets = venueProfile?.sourceSheets || SOURCE_SHEETS[venue] || {};
    for (const [sheetName, sheetId] of Object.entries(sheets)) {
      const name = String(sheetName || '').trim();
      const id = String(sheetId || '').trim();
      if (!id || name === '猫眼项目店铺对照单') continue;
      rows.push({ venue, sheetName: name, sheetId: id });
    }
  }
  if (!rows.length) {
    for (const [venue, sheets] of Object.entries(SOURCE_SHEETS)) {
      for (const [sheetName, sheetId] of Object.entries(sheets)) rows.push({ venue, sheetName, sheetId });
    }
  }
  const seen = new Set();
  return rows.filter(row => {
    const key = `${row.venue}|${row.sheetId}`;
    if (seen.has(key)) return false;
    seen.add(key); return true;
  });
}

function rowValue(sheet, row, index) {
  if (!row || index < 0) return '';
  return row.values[index];
}

function orderMonitorRowForDate(sheet, date) {
  const dateIndex = sheet.headers.findIndex(header => ['日期', '业务日期', '快照日期'].includes(String(header || '').trim()));
  if (dateIndex < 0) return { dateRow: null, reason: 'missing_date_column' };
  const metricIndexes = ['今日销售额', '今日票数', '今日实收额', '今日核销人数']
    .map(header => sheet.headers.findIndex(item => String(item || '').trim() === header)).filter(index => index >= 0);
  const dateRow = sheet.rows.find(row => sourceDate(row.values[dateIndex]) === date);
  if (!dateRow) return { dateRow: null, reason: 'date_not_found' };
  // 0 是有效数据；只有整行关键指标均为空，才认为页签尚未填完。
  const hasMetric = metricIndexes.some(index => {
    const value = rowValue(sheet, dateRow, index);
    return value !== null && value !== undefined && String(value).trim() !== '';
  });
  return { dateRow, reason: hasMetric ? 'ready' : 'metrics_empty' };
}

function orderMonitorStateValue() {
  const state = readRuntimeState('order_monitor').data;
  if (!state || typeof state !== 'object' || Array.isArray(state)) return { schemaVersion: 'order-table-monitor-v1', checks: {}, updatedAt: '' };
  return { schemaVersion: 'order-table-monitor-v1', checks: state.checks && typeof state.checks === 'object' ? state.checks : {}, updatedAt: String(state.updatedAt || '') };
}

function orderMonitorStatusText(result) {
  const total = Number(result.totalSheets || 0), ready = Number(result.readySheets || 0);
  if (result.status === 'complete') return `订单系统汇总表已完成更新：${ready}/${total} 个业务页签均有 ${result.date} 数据。`;
  if (result.status === 'in_progress') return `订单系统汇总表还在更新：${ready}/${total} 个业务页签已出现 ${result.date} 数据，剩余页签尚未完成。`;
  if (result.status === 'not_started') return `订单系统汇总表尚未开始更新：${total} 个业务页签都没有出现 ${result.date} 数据。`;
  return `订单系统汇总表暂时无法检查：${result.error || '飞书来源不可用'}。`;
}

async function checkOrderTableMonitor({ date = dailyIsoNow(), actorId = '', projectId = '', force = false } = {}) {
  const profile = readStrategyProfile();
  const targetDate = /^\d{4}-\d{2}-\d{2}$/.test(String(date)) ? String(date) : dailyIsoNow();
  const sheets = orderMonitorSheets(profile);
  const checkedAt = new Date().toISOString();
  const key = `${String(actorId || 'unassigned')}|${String(projectId || profile.project?.id || 'yuanqu-vr')}|${targetDate}`;
  const result = {
    schemaVersion: 'order-table-monitor-v1', kind: 'order_table_update', date: targetDate,
    projectId: String(projectId || profile.project?.id || 'yuanqu-vr'), actorId: String(actorId || ''),
    totalSheets: sheets.length, readySheets: 0, dateRows: 0, status: 'not_started',
    missingSheets: [], incompleteSheets: [], errors: [], checkedAt, sourceRevision: '',
  };
  if (!SOURCE_SPREADSHEET_TOKEN) {
    result.status = 'unavailable'; result.error = '后端尚未配置来源表格 token';
  } else if (!sheets.length) {
    result.status = 'unavailable'; result.error = '未配置订单系统汇总表的业务页签';
  } else {
    const checks = await Promise.all(sheets.map(async spec => {
      try {
        const sheet = await readSheetFromToken(SOURCE_SPREADSHEET_TOKEN, spec.sheetId, 260, 'FormattedValue');
        const row = orderMonitorRowForDate(sheet, targetDate);
        return { ...spec, ...row, revision: sheet.revision || '' };
      } catch (error) {
        return { ...spec, dateRow: null, reason: 'read_error', error: String(error.message || error) };
      }
    }));
    result.sourceRevision = checks.map(item => item.revision).filter(Boolean).join('|').slice(0, 120);
    for (const item of checks) {
      const label = `${item.venue}·${item.sheetName}`;
      if (item.reason === 'ready') { result.readySheets++; result.dateRows++; }
      else if (item.reason === 'metrics_empty') { result.dateRows++; result.incompleteSheets.push(label); }
      else if (item.reason === 'read_error') result.errors.push(`${label}：${item.error}`);
      else result.missingSheets.push(label);
    }
    if (result.errors.length && result.readySheets === 0 && result.dateRows === 0) {
      result.status = 'unavailable'; result.error = result.errors.slice(0, 2).join('；');
    } else if (result.readySheets === result.totalSheets && result.totalSheets > 0) result.status = 'complete';
    else if (result.readySheets > 0 || result.dateRows > 0) result.status = 'in_progress';
    else result.status = 'not_started';
  }
  result.message = orderMonitorStatusText(result);
  const state = orderMonitorStateValue();
  state.checks[key] = { ...result };
  const keys = Object.keys(state.checks).sort((a, b) => String(state.checks[b]?.checkedAt || '').localeCompare(String(state.checks[a]?.checkedAt || ''))).slice(0, 120);
  state.checks = Object.fromEntries(keys.map(item => [item, state.checks[item]])); state.updatedAt = checkedAt;
  writeRuntimeState('order_monitor', state);
  return { ...result, force: Boolean(force) };
}

function eventForOrderTableMonitor({ monitor, projectId, actorId }) {
  if (!monitor || monitor.status === 'unavailable') return null;
  const question = monitor.status === 'complete' ? '' : monitor.status === 'in_progress'
    ? '等剩下的页签补齐后再看一眼，还是先告诉我是哪几页卡住了？'
    : '今天还没开始填吗，还是数据还在路上？';
  return normalizeEnterpriseEvent({
    source: 'feishu_order_monitor', eventType: 'order_table_update', taskType: 'order_table_monitor', actorId,
    dedupeKey: `order_table_monitor|${actorId}|${monitor.date}|${monitor.status}|${monitor.sourceRevision || monitor.checkedAt}`,
    statement: monitor.message, expectedAction: question, question,
    sourceRefs: orderMonitorSheets(readStrategyProfile()).map(item => `feishu:${item.sheetId}`),
    decisionImpact: monitor.status === 'complete' ? '十个业务页签已齐，可以基于今天的真实数据做日报。' : '避免把未完成的来源表误当成完整日报。',
    evidencePeriod: { start: monitor.date, end: monitor.date, source: 'feishu_order_table', historical: false },
    monitor, scope: { projectId: projectId || monitor.projectId, venueNames: [] },
    priority: monitor.status === 'complete' ? 'normal' : 'high', occurredAt: monitor.checkedAt,
  });
}

function asNumber(value) {
  if (value === null || value === undefined || value === '') return null;
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  const n = Number(String(value).replace(/,/g, '').replace(/%$/, ''));
  return Number.isFinite(n) ? Math.round((n + Number.EPSILON) * 100) / 100 : null;
}

function sourceLabel(payload) {
  const refs = payload?.source_refs || payload?.sourceRefs || [];
  if (!Array.isArray(refs) || !refs.length) return '运营填数台';
  return refs.map(x => `${x.sheet || x.document || '来源'}${x.range ? ` ${x.range}` : ''}`).join('；').slice(0, 200);
}

function venueId(venue) {
  return VENUES[venue] || String(venue || '').trim().toUpperCase().replace(/[^A-Z0-9]+/g, '_');
}

function mapRow(headers, row) {
  return headers.map(h => Object.prototype.hasOwnProperty.call(row, h) ? row[h] : null);
}

function mergeRowValues(headers, row, existingValues = []) {
  const mapped = mapRow(headers, row);
  return headers.map((header, i) => Object.prototype.hasOwnProperty.call(row, header) ? mapped[i] : (existingValues[i] ?? null));
}

function findExisting(sheet, keyFields, row) {
  return sheet.rows.find(r => keyFields.every(field => String(r.values[sheet.headerIndex[field]] ?? '') === String(row[field] ?? '')))?.rowNumber || null;
}

function firstBlankRow(sheet) {
  return sheet.rows.find(r => r.values.every(v => v === '' || v === null || v === undefined))?.rowNumber || Math.max(2, ...sheet.rows.map(r => r.rowNumber + 1));
}

function comparableValue(value, header) {
  if (value === null || value === undefined || value === '') return null;
  if (isDateHeader(header)) return String(value).trim();
  const numeric = asNumber(value);
  if (numeric !== null && (typeof value === 'number' || /^[-+]?\d[\d,]*(?:\.\d+)?%?$/.test(String(value).trim()))) return numeric;
  return String(value).trim();
}

function sameValue(left, right, header) {
  return comparableValue(left, header) === comparableValue(right, header);
}

async function setRow(sheetId, sheet, rowNumber, row, existingValues = []) {
  const values = mergeRowValues(sheet.headers, row, existingValues);
  const end = colLetter(Math.max(values.length, 1));
  const typedValues = values.map((value, i) => isDateHeader(sheet.headers[i]) ? isoToExcelSerial(value) : (value === undefined ? null : value));
  await feishuRequest('PUT', `/sheets/v2/spreadsheets/${encodeURIComponent(SPREADSHEET_TOKEN)}/values`, { valueRange: { range: `${sheetId}!A${rowNumber}:${end}${rowNumber}`, values: [typedValues] } });
  return { rowNumber, values };
}

async function upsertRows(section, sheetConfig, rows, warnings, dryRun = false) {
  if (!rows.length) return { written: 0, rows: [] };
  const sheet = await readSheet(sheetConfig.sheetId);
  const out = [];
  for (const row of rows) {
    const key = sheetConfig.rowKey || [];
    const missingKey = key.filter(field => row[field] === null || row[field] === undefined || row[field] === '').join('、');
    if (missingKey) {
      warnings.push(`${section} 跳过一行：缺少主键字段 ${missingKey}`);
      continue;
    }
    const existing = findExisting(sheet, key, row);
    const rowNumber = existing || firstBlankRow(sheet);
    const existingValues = sheet.rows.find(r => r.rowNumber === rowNumber)?.values || [];
    const result = dryRun ? { rowNumber, values: mergeRowValues(sheet.headers, row, existingValues) } : await setRow(sheetConfig.sheetId, sheet, rowNumber, row, existingValues);
    out.push({ section, rowNumber, key: key.map(field => row[field]) });
    const cached = sheet.rows.find(r => r.rowNumber === rowNumber);
    if (cached) cached.values = result.values;
    else sheet.rows.push({ rowNumber, values: result.values });
  }
  return { written: out.length, rows: out };
}

async function compareRows(section, sheetConfig, rows, warnings) {
  if (!rows.length) return { rows: [] };
  const sheet = await readSheet(sheetConfig.sheetId);
  const out = [];
  for (const row of rows) {
    const key = sheetConfig.rowKey || [];
    const missingKey = key.filter(field => row[field] === null || row[field] === undefined || row[field] === '').join('、');
    if (missingKey) {
      warnings.push(`${section} 跳过一行：缺少主键字段 ${missingKey}`);
      continue;
    }
    const rowNumber = findExisting(sheet, key, row);
    const keyValues = key.map(field => row[field]);
    if (!rowNumber) {
      out.push({ section, status: 'missing', rowNumber: null, key: keyValues, changes: [] });
      continue;
    }
    const remote = sheet.rows.find(item => item.rowNumber === rowNumber);
    const changes = [];
    for (const field of Object.keys(row)) {
      const index = sheet.headerIndex[field];
      if (index === undefined) {
        warnings.push(`${section} 对比跳过字段：目标表没有列“${field}”`);
        continue;
      }
      const localValue = row[field] ?? null;
      const feishuValue = remote?.values[index] ?? null;
      if (!sameValue(localValue, feishuValue, field)) changes.push({ field, local: localValue, feishu: feishuValue });
    }
    out.push({ section, status: changes.length ? 'different' : 'same', rowNumber, key: keyValues, changes });
  }
  return { rows: out };
}

function makeRows(payload) {
  const weekly = payload.weekly_core || {};
  const venue = weekly.venue || payload.venue || '';
  const id = venueId(venue);
  const source = sourceLabel(payload);
  const notes = weekly.notes || payload.notes || '';
  const out = { warnings: [], weekly: [], channels: [], traffic: [], boxOffice: [], cards: [], cumulative: [], playback: [] };
  const common = { period_id: weekly.period_id || payload.period_id, period_start: weekly.period_start, period_end: weekly.period_end, venue_id: weekly.venue_id || id, venue };

  const weeklyRow = {
    '周期ID': common.period_id, '周开始': common.period_start, '周结束': common.period_end, '门店ID': common.venue_id, '门店名称': venue,
    '目标金额': asNumber(weekly.target_amount), '扣佣结算预估': asNumber(weekly.platform_settlement), '销售票数': asNumber(weekly.sales_order_count),
    '接待客流': asNumber(weekly.reception_traffic), '线下销售额': asNumber(weekly.offline_sales_amount), '数据状态': '已确认', '来源': source, '备注': notes
  };
  out.weekly.push(weeklyRow);
  if (weekly.platform_settlement !== null && weekly.platform_settlement !== undefined && weekly.platform_settlement !== '') out.warnings.push('“平台加售结算额”当前按映射写入“扣佣结算预估”，两者口径仍需运营确认。');

  const channelItems = Array.isArray(payload.channel_metric) ? payload.channel_metric : [];
  const hasCanonicalOffline = channelItems.some(item => item.channel === '线下');
  const writtenChannels = new Set();
  for (const item of channelItems) {
    if (!item.channel) continue;
    const channel = item.channel === '分销' ? '线下' : item.channel;
    if (item.channel === '分销' && hasCanonicalOffline) continue;
    if (writtenChannels.has(channel)) continue;
    writtenChannels.add(channel);
    out.channels.push({
      '周期ID': item.period_id || common.period_id, '周开始': common.period_start, '周结束': common.period_end, '门店ID': item.venue_id || common.venue_id,
      '门店名称': item.venue || venue, '渠道ID': channel, '渠道名称': channel,
      '销售额': asNumber(item.amount), '销售票数': asNumber(item.orders), '来源': source, '备注': notes
    });
  }

  for (const item of Array.isArray(payload.daily_metric) ? payload.daily_metric : []) {
    const date = item.business_date || item.date;
    if (!date) { out.warnings.push('日明细跳过一行：缺少业务日期'); continue; }
    const day = new Date(`${date}T00:00:00`);
    const label = Number.isNaN(day.getTime()) ? '' : ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][day.getDay()];
    const base = { '周期ID': item.period_id || common.period_id, '日期标签': label, '业务日期': date, '门店ID': item.venue_id || common.venue_id, '门店名称': item.venue || venue, '来源': source, '备注': notes };
    if (item.venue_traffic !== null && item.venue_traffic !== undefined && item.venue_traffic !== '') { out.traffic.push({ ...base, '大盘客流': asNumber(item.venue_traffic), '触达人数': asNumber(item.reach_count), '转化人数': asNumber(item.conversion_count) }); out.warnings.push('页面“日场域客流”当前按映射写入“录入_客流·大盘客流”，两者是否同义仍需运营确认。'); }
    if (item.box_office !== null && item.box_office !== undefined && item.box_office !== '') out.boxOffice.push({ ...base, '票房预估': asNumber(item.box_office) });
  }

  const breakdown = payload.card_metric?.breakdown || {};
  const cards = [
    { id: 'CARD5', name: '5次卡', quota: 5, orders: breakdown.fiveOrders, amount: breakdown.fiveAmount },
    { id: 'CARD10', name: '10次卡', quota: 10, orders: breakdown.tenOrders, amount: breakdown.tenAmount }
  ];
  for (const card of cards) {
    if (card.orders === null || card.orders === undefined || card.orders === '') continue;
    out.cards.push({
      '周期ID': payload.card_metric?.period_id || common.period_id, '周开始': common.period_start, '周结束': common.period_end,
      '门店ID': payload.card_metric?.venue_id || common.venue_id, '门店名称': payload.card_metric?.venue || venue, '卡种ID': card.id, '卡种名称': card.name,
      '单卡额定次数': card.quota, '售出张数': asNumber(card.orders), '次卡金额': asNumber(card.amount),
      '本周新增权益数': asNumber(card.orders) === null ? null : asNumber(card.orders) * card.quota,
      '本周已核销票数': null, '来源': source, '备注': notes || '已核销次数为门店汇总，暂不拆分到卡种'
    });
  }
  const cumulative = payload.card_metric?.cumulative_snapshot || {};
  if (cumulative.asOfDate) out.cumulative.push({
    '快照日期': cumulative.asOfDate, '门店ID': payload.card_metric?.venue_id || common.venue_id, '门店名称': payload.card_metric?.venue || venue,
    '累计5次卡单数': asNumber(cumulative.fiveOrders), '累计5次卡金额': asNumber(cumulative.fiveAmount), '累计10次卡单数': asNumber(cumulative.tenOrders),
    '累计10次卡金额': asNumber(cumulative.tenAmount), '累计额定权益次数': asNumber(cumulative.quota), '累计销售金额': asNumber(cumulative.salesAmount),
    '累计已核销次数': asNumber(cumulative.redeemed), '源表累计核销率（%）': asNumber(cumulative.sourceRate), '来源': source, '备注': notes
  });
  for (const item of Array.isArray(payload.playback_metric) ? payload.playback_metric : []) {
    if (!item.project) continue;
    out.playback.push({ '周期ID': item.period_id || common.period_id, '周开始': common.period_start, '周结束': common.period_end, '门店ID': item.venue_id || common.venue_id, '门店名称': item.venue || venue, '项目': item.project, '播控次数': asNumber(item.count), '来源': source, '备注': notes });
  }
  if (payload.card_metric?.redeemed_count !== null && payload.card_metric?.redeemed_count !== undefined && out.cards.length) out.warnings.push('次卡已核销次数是门店汇总，未擅自拆分到 5 次卡/10 次卡行；请在飞书表中按实际卡种补录。');
  return out;
}

async function syncTask(task) {
  const payload = task.payload || {};
  const dryRun = task.dryRun === true;
  const rows = makeRows(payload);
  const written = [];
  const warnings = [...new Set(rows.warnings)];
  const configs = TARGET.sheets;
  const operations = [
    ['weekly_core', configs.weekly_core, rows.weekly],
    ['channel_metric', configs.channel_metric, rows.channels],
    ['daily_traffic', configs.daily_traffic, rows.traffic],
    ['daily_box_office', configs.daily_box_office, rows.boxOffice],
    ['card_metric', configs.card_metric, rows.cards],
    ['card_cumulative_snapshot', configs.card_cumulative_snapshot, rows.cumulative],
    ['playback_metric', configs.playback_metric, rows.playback]
  ];
  for (const [section, config, values] of operations) {
    if (!config || !values.length) continue;
    const result = await upsertRows(section, config, values, warnings, dryRun);
    written.push(...result.rows);
  }
  return { ok: true, dryRun, taskId: task.taskId, workbookRevisionBefore: TARGET.workbook.revision, written, warnings: [...new Set(warnings)], target: { title: TARGET.workbook.title, tokenLast4: SPREADSHEET_TOKEN.slice(-4) } };
}

async function compareTask(task) {
  const payload = task.payload || {};
  const rows = makeRows(payload);
  const warnings = [...new Set(rows.warnings)];
  const configs = TARGET.sheets;
  const operations = [
    ['weekly_core', configs.weekly_core, rows.weekly],
    ['channel_metric', configs.channel_metric, rows.channels],
    ['daily_traffic', configs.daily_traffic, rows.traffic],
    ['daily_box_office', configs.daily_box_office, rows.boxOffice],
    ['card_metric', configs.card_metric, rows.cards],
    ['card_cumulative_snapshot', configs.card_cumulative_snapshot, rows.cumulative],
    ['playback_metric', configs.playback_metric, rows.playback]
  ];
  const comparisons = [];
  for (const [section, config, values] of operations) {
    if (!config || !values.length) continue;
    const result = await compareRows(section, config, values, warnings);
    comparisons.push(...result.rows);
  }
  const summary = {
    totalRows: comparisons.length,
    sameRows: comparisons.filter(item => item.status === 'same').length,
    differentRows: comparisons.filter(item => item.status === 'different').length,
    missingRows: comparisons.filter(item => item.status === 'missing').length,
    changedFields: comparisons.reduce((count, item) => count + item.changes.length, 0)
  };
  return { ok: true, taskId: task.taskId, consistent: summary.differentRows === 0 && summary.missingRows === 0, workbookRevisionBefore: TARGET.workbook.revision, summary, rows: comparisons, warnings: [...new Set(warnings)], target: { title: TARGET.workbook.title, tokenLast4: SPREADSHEET_TOKEN.slice(-4) } };
}

function serveStatic(req, res) {
  let requestPath = decodeURIComponent(new URL(req.url, `http://${HOST}:${PORT}`).pathname);
  if (requestPath === '/') requestPath = '/index.html';
  if (/^\/(?:data|backend|docs)(?:\/|$)/i.test(requestPath)) return false;
  const full = path.resolve(ROOT, `.${requestPath}`);
  if (!full.startsWith(ROOT + path.sep) || !fs.existsSync(full) || !fs.statSync(full).isFile()) return false;
  res.writeHead(200, { 'Content-Type': mime[path.extname(full).toLowerCase()] || 'application/octet-stream' });
  fs.createReadStream(full).pipe(res);
  return true;
}

function readJsonBody(req, maxBytes = 8 * 1024 * 1024) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', chunk => {
      body += chunk;
      if (body.length > maxBytes) {
        req.destroy();
        reject(new Error('请求体过大'));
      }
    });
    req.on('end', () => {
      try { resolve(JSON.parse(body || '{}')); }
      catch { reject(new Error('请求体不是合法 JSON')); }
    });
    req.on('error', reject);
  });
}

async function proxyWeeklyReport(req, res) {
  const settings = readSettings();
  const endpoint = String(settings.reportApiEndpoint || '').trim();
  const apiKey = String(settings.reportApiKey || '').trim();
  const model = String(settings.reportModel || '').trim();
  if (!endpoint || endpoint.startsWith('/')) return json(res, 400, { ok: false, error: '尚未配置有效的模型服务地址' });
  if (!apiKey || !model) return json(res, 400, { ok: false, error: '尚未配置模型 API Key 或模型名称' });
  let url;
  try { url = new URL(endpoint); }
  catch { return json(res, 400, { ok: false, error: '模型服务地址不是合法 URL' }); }
  if (!['http:', 'https:'].includes(url.protocol)) return json(res, 400, { ok: false, error: '模型服务地址必须使用 HTTP 或 HTTPS' });
  if (/deepseek\.com/i.test(url.hostname) && !/^deepseek-/i.test(model)) {
    return json(res, 400, { ok: false, error: '当前模型服务地址是 DeepSeek，但服务端模型名称不是 DeepSeek 模型；请在服务端设置中修正。' });
  }
  try {
    const payload = await readJsonBody(req);
    const taskKey = normalizeThinkingTask(payload.thinkingTask || payload.taskKey || payload.task || '');
    const guardedPayload = {
      ...payload,
      thinkingTask: taskKey,
      thinking: { type: thinkingAllowedForTask(taskKey, settings) ? 'enabled' : 'disabled' }
    };
    const result = await requestModelWithGuard({ endpoint: url, apiKey, model }, guardedPayload);
    const contentType = result.response.headers.get('content-type') || 'application/json; charset=utf-8';
    res.writeHead(result.response.status, {
      'Content-Type': contentType,
      'Access-Control-Allow-Origin': '*',
      // 便于排查“思考已启用但最终答案走了兜底”的情况，不暴露密钥。
      'X-Model-Thinking': result.mode,
      'X-Model-Attempts': String(result.attempts)
    });
    return res.end(result.text);
  } catch (error) {
    return json(res, 502, { ok: false, error: `模型服务请求失败：${error.message}` });
  }
}

function configuredModelSettings() {
  const settings = readSettings();
  const endpoint = String(settings.reportApiEndpoint || '').trim();
  const apiKey = String(settings.reportApiKey || '').trim();
  const model = String(settings.reportModel || '').trim();
  if (!endpoint || endpoint.startsWith('/')) throw new Error('尚未配置有效的模型服务地址');
  if (!apiKey || !model) throw new Error('尚未配置模型 API Key 或模型名称');
  let url;
  try { url = new URL(endpoint); }
  catch { throw new Error('模型服务地址不是合法 URL'); }
  if (!['http:', 'https:'].includes(url.protocol)) throw new Error('模型服务地址必须使用 HTTP 或 HTTPS');
  return { endpoint: url, apiKey, model };
}

function normalizeThinkingTask(task) {
  const value = String(task || '').trim();
  if (value.includes('initial_weekly_review') || value.includes('signal-hypothesis')) return 'weekly_signal';
  if (value.includes('review_operating_answer') || value.includes('answer_evidence')) return 'causal_dialogue';
  if (value.includes('review_synthesis') || value.includes('experience_candidates') || value.includes('next_action_candidates')) return 'weekly_synthesis';
  if (value.includes('analyze_operating_node') || value.includes('node_analysis')) return 'strategy_node';
  if (value.includes('tactic_plan') || value.includes('plan_design')) return 'tactic_plan';
  if (value.includes('validation')) return 'validation';
  if (value.includes('weekly_report')) return 'weekly_report';
  return value;
}

function thinkingAllowedForTask(task, settings = readSettings()) {
  const key = normalizeThinkingTask(task);
  // Legacy callers without a task key can still explicitly request thinking;
  // all new UI calls carry a key and are governed by the selected checklist.
  if (!key) return settings.thinkingEnabled !== false;
  return settings.thinkingEnabled !== false && (settings.thinkingTasks || []).includes(key);
}

function extractModelContent(body) {
  let content = body?.choices?.[0]?.message?.content || body?.output_text || body?.content;
  if (Array.isArray(content)) content = content.map(item => item?.text || '').join('');
  return typeof content === 'string' ? content : '';
}

function cleanModelJsonText(content) {
  return String(content || '').replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/i, '').trim();
}

function parseModelJson(body) {
  const content = extractModelContent(body);
  if (!content.trim()) {
    const hasReasoning = Boolean(body?.choices?.[0]?.message?.reasoning_content);
    throw new Error(hasReasoning ? '模型只返回了 reasoning_content，最终答案为空' : '模型返回内容无法读取');
  }
  const clean = cleanModelJsonText(content);
  try { return JSON.parse(clean); }
  catch { throw new Error('模型未返回合法 JSON'); }
}

function modelRequestAttempts(payload = {}) {
  const requested = Number(payload.max_tokens || payload.maxTokens || 0);
  const primaryMax = Math.max(1024, Math.min(MODEL_MAX_TOKENS, requested || MODEL_MAX_TOKENS));
  const expandedMax = Math.max(primaryMax, Math.min(MODEL_MAX_TOKENS, Math.ceil(primaryMax * 1.5)));
  const requestedThinking = payload.thinking?.type === 'disabled' ? 'disabled' : 'enabled';
  const attempts = [{ mode: requestedThinking, max_tokens: primaryMax }];
  // A truncated JSON response gets one larger thinking budget. If the
  // provider rejects thinking or still omits content, retry without thinking
  // so the UI receives a usable structured answer instead of a blank card.
  if (requestedThinking === 'enabled' && expandedMax > primaryMax) attempts.push({ mode: 'enabled', max_tokens: expandedMax });
  if (requestedThinking === 'enabled') attempts.push({ mode: 'disabled', max_tokens: primaryMax });
  return attempts;
}

function modelBodyLooksUsable(body, expectJson) {
  const content = extractModelContent(body).trim();
  if (!content) return false;
  if (body?.choices?.[0]?.finish_reason === 'length') return false;
  if (!expectJson) return true;
  try { JSON.parse(cleanModelJsonText(content)); return true; } catch { return false; }
}

async function fetchModelAttempt(config, payload, attempt, timeoutMs = MODEL_REQUEST_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const requestPayload = {
      ...payload,
      model: config.model,
      max_tokens: attempt.max_tokens,
      thinking: { type: attempt.mode }
    };
    const response = await fetch(config.endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${config.apiKey}` },
      body: JSON.stringify(requestPayload),
      signal: controller.signal
    });
    const text = await response.text();
    return { response, text };
  } finally {
    clearTimeout(timer);
  }
}

async function requestModelWithGuard(config, payload = {}) {
  const expectJson = payload.response_format?.type === 'json_object';
  let lastError = null;
  const attempts = modelRequestAttempts(payload);
  const deadline = Date.now() + MODEL_TOTAL_TIMEOUT_MS;
  for (let index = 0; index < attempts.length; index += 1) {
    const attempt = attempts[index];
    const remainingMs = deadline - Date.now();
    if (remainingMs <= 0) break;
    let result;
    try {
      result = await fetchModelAttempt(config, payload, attempt, Math.min(MODEL_REQUEST_TIMEOUT_MS, remainingMs));
    } catch (error) {
      lastError = error.name === 'AbortError' ? new Error(`模型请求超时（单次>${MODEL_REQUEST_TIMEOUT_MS / 1000}s或总计>${MODEL_TOTAL_TIMEOUT_MS / 1000}s，思考模式：${attempt.mode}）`) : error;
      continue;
    }
    if (result.response.ok && modelBodyLooksUsable(parseJsonSilently(result.text), expectJson)) {
      return { ...result, mode: attempt.mode, attempts: index + 1 };
    }
    let body = parseJsonSilently(result.text);
    if (!result.response.ok) {
      const detail = body?.error?.message || body?.error?.detail || body?.message || `HTTP ${result.response.status}`;
      lastError = new Error(`模型服务返回 HTTP ${result.response.status}：${String(detail).slice(0, 600)}`);
      // A provider rejecting the thinking parameter should immediately use
      // the following non-thinking attempt; do not surface a false failure.
      continue;
    }
    lastError = new Error(body?.choices?.[0]?.finish_reason === 'length' ? '模型输出达到 token 上限，JSON 被截断' : '模型未返回可用的最终答案');
  }
  throw lastError || new Error('模型未返回可用的最终答案');
}

function parseJsonSilently(text) {
  try { return JSON.parse(text); } catch { return null; }
}

async function requestConfiguredModelJson(messages, temperature = 0.1, options = {}) {
  const config = configuredModelSettings();
  const taskKey = options.taskKey || '';
  const result = await requestModelWithGuard(config, {
    messages,
    temperature,
    max_tokens: Number(options.max_tokens || 6000),
    thinkingTask: normalizeThinkingTask(taskKey),
    thinking: { type: thinkingAllowedForTask(taskKey) ? 'enabled' : 'disabled' },
    response_format: { type: 'json_object' }
  });
  const text = result.text;
  let body;
  try { body = JSON.parse(text); }
  catch { throw new Error('模型服务返回非 JSON 内容'); }
  return { result: parseModelJson(body), model: config.model, thinkingMode: result.mode, attempts: result.attempts };
}

function strategyPromptContract() {
  if (!fs.existsSync(STRATEGY_PROMPT_PATH)) throw new Error('策略提示词协议不存在');
  return JSON.parse(fs.readFileSync(STRATEGY_PROMPT_PATH, 'utf8'));
}

function strategySchemaContract() {
  if (!fs.existsSync(STRATEGY_SCHEMA_PATH)) throw new Error('策略输出协议不存在');
  return JSON.parse(fs.readFileSync(STRATEGY_SCHEMA_PATH, 'utf8'));
}

function allowedStrategyReferences(payload) {
  const evidence = new Set((payload?.evidenceRegistry || []).map(item => String(item?.id || '')).filter(Boolean));
  const contexts = new Set();
  const add = items => (items || []).forEach(item => {
    const id = item?.id || item?.contextId || item?.periodId || item?.signalId;
    if (id) contexts.add(String(id));
  });
  add(payload?.calendarContext);
  add(payload?.operatingContexts);
  add(payload?.implicitKnowledge);
  add(payload?.historicalExperiences);
  add(payload?.validationResults);
  add(payload?.dynamicSignals);
  add(payload?.longTermOpportunities);
  add(payload?.industryContext?.benchmarks);
  if (payload?.projectProfile?.id) contexts.add(String(payload.projectProfile.id));
  if (payload?.venueProfile?.id) contexts.add(String(payload.venueProfile.id));
  return { evidence, contexts };
}

function validateStrategyAnalysis(raw, payload) {
  const errors = [], result = raw?.analysis || raw?.data?.analysis || raw;
  if (!result || typeof result !== 'object') return { errors: ['缺少分析对象'], result: {} };
  if (typeof result.statusSummary !== 'string' || !result.statusSummary.trim()) errors.push('statusSummary 必须是非空字符串');
  if (!Array.isArray(result.expertSignals)) errors.push('expertSignals 必须是数组');
  if (Array.isArray(result.expertSignals) && result.expertSignals.length > 5) errors.push('expertSignals 最多返回 5 条');
  const { evidence, contexts } = allowedStrategyReferences(payload);
  const allowedKinds = new Set(['problem', 'opportunity', 'watch', 'normal', 'data_gap']);
  const allowedStatuses = new Set(['confirmed', 'needs_input', 'observing']);
  const allowedConfidence = new Set(['high', 'medium', 'low', 'insufficient']);
  (result.expertSignals || []).slice(0, 8).forEach((signal, index) => {
    const prefix = `expertSignals[${index}]`;
    if (!signal || typeof signal !== 'object') return errors.push(`${prefix} 必须是对象`);
    if (!String(signal.title || '').trim()) errors.push(`${prefix}.title 不能为空`);
    if (!allowedKinds.has(signal.kind)) errors.push(`${prefix}.kind 不合法`);
    if (!allowedStatuses.has(signal.status)) errors.push(`${prefix}.status 不合法`);
    if (!allowedConfidence.has(signal.confidence)) errors.push(`${prefix}.confidence 不合法`);
    if (!Array.isArray(signal.evidenceRefs) || (signal.include !== false && !signal.evidenceRefs.length)) errors.push(`${prefix}.evidenceRefs 缺失`);
    (signal.evidenceRefs || []).forEach(id => { if (!evidence.has(String(id))) errors.push(`${prefix}.evidenceRefs 引用了不存在的 ${id}`); });
    (signal.contextRefs || []).forEach(id => { if (!contexts.has(String(id))) errors.push(`${prefix}.contextRefs 引用了不存在的 ${id}`); });
    if (signal.status === 'needs_input' && !String(signal.question || '').trim()) errors.push(`${prefix} 需要补充 question`);
  });
  const allowedLevers = new Set((payload?.availableLevers || []).map(item => item.id));
  const allowedTactics = new Set((payload?.tacticCandidates || []).map(item => item.id));
  (result.recommendedLeverIds || []).forEach(id => { if (!allowedLevers.has(id)) errors.push(`recommendedLeverIds 包含未知值 ${id}`); });
  (result.recommendedTacticIds || []).forEach(id => { if (!allowedTactics.has(id)) errors.push(`recommendedTacticIds 包含未知值 ${id}`); });
  return { errors: [...new Set(errors)], result };
}

function normalizeStrategyAnalysis(raw, payload) {
  const { evidence, contexts } = allowedStrategyReferences(payload);
  const allowedLevers = new Set((payload?.availableLevers || []).map(item => item.id));
  const allowedTactics = new Set((payload?.tacticCandidates || []).map(item => item.id));
  const result = raw?.analysis || raw?.data?.analysis || raw || {};
  const expertSignals = (result.expertSignals || []).slice(0, 5).map((signal, index) => ({
    id: String(signal.id || `expert-${index + 1}`),
    include: signal.include !== false,
    kind: ['problem', 'opportunity', 'watch', 'normal', 'data_gap'].includes(signal.kind) ? signal.kind : 'watch',
    status: ['confirmed', 'needs_input', 'observing'].includes(signal.status) ? signal.status : 'observing',
    priority: ['high', 'medium', 'low'].includes(signal.priority) ? signal.priority : 'medium',
    title: String(signal.title || '待观察经营信号'),
    observation: String(signal.observation || ''),
    comparisonBasis: Array.isArray(signal.comparisonBasis) ? signal.comparisonBasis.slice(0, 4).map(String) : [],
    evidenceRefs: (signal.evidenceRefs || []).map(String).filter(id => evidence.has(id)).slice(0, 8),
    contextRefs: (signal.contextRefs || []).map(String).filter(id => contexts.has(id)).slice(0, 8),
    hypothesis: String(signal.hypothesis || ''),
    counterEvidence: String(signal.counterEvidence || ''),
    confidence: ['high', 'medium', 'low', 'insufficient'].includes(signal.confidence) ? signal.confidence : 'insufficient',
    missingFacts: Array.isArray(signal.missingFacts) ? signal.missingFacts.slice(0, 6).map(String) : [],
    question: signal.status === 'needs_input' ? String(signal.question || '') : '',
    leverIds: (signal.leverIds || []).filter(id => allowedLevers.has(id)).slice(0, 4)
  }));
  const tacticRationales = {};
  Object.entries(result.tacticRationales || {}).forEach(([id, value]) => { if (allowedTactics.has(id)) tacticRationales[id] = String(value || ''); });
  return {
    statusSummary: String(result.statusSummary || '本次分析未形成有效摘要。'),
    expertSignals,
    benchmarkAvailable: Boolean(result.benchmarkAvailable && payload?.industryContext?.benchmarks?.length),
    recommendedLeverIds: (result.recommendedLeverIds || []).filter(id => allowedLevers.has(id)).slice(0, 5),
    recommendedTacticIds: (result.recommendedTacticIds || []).filter(id => allowedTactics.has(id)).slice(0, 8),
    tacticRationales,
    analysisBoundary: String(result.analysisBoundary || '仅基于当前事实包和已检索知识。')
  };
}

async function analyzeStrategyNode(req, res) {
  try {
    const payload = await readJsonBody(req, 2 * 1024 * 1024);
    if (payload?.task !== 'analyze_operating_node_v5') return json(res, 400, { ok: false, error: '分析任务版本不匹配' });
    const selectedVenues = normalizeScopeVenueNames(typeof payload.scope === 'string' ? { venue: payload.scope } : payload.scope || {});
    payload.implicitKnowledge = knowledgeStateValue().implicitItems.filter(item => item.status === 'confirmed' && normalizeScopeVenueNames(item.scope || {}).some(name => selectedVenues.includes(name))).slice(-20).map(item => ({ ...item, epistemicStatus: 'confirmed_implicit_knowledge', boundary: '运营者确认的背景或判断，不等于因果验证或正式经验' }));
    payload.confirmedConversationKnowledge = (readRuntimeState('workbench').data?.intelligenceAssets || []).filter(item => item.status === 'confirmed' && item.targetType !== 'experience' && normalizeScopeVenueNames(item.scope || {}).some(name => selectedVenues.includes(name))).slice(-20).map(item => ({ ...item, epistemicStatus: item.targetType === 'operating_fact' ? 'confirmed_operating_fact' : 'confirmed_operator_claim' }));
    const contract = strategyPromptContract();
    const schema = strategySchemaContract();
    if (schema?.version !== 'operating-strategy-workbench-v5') return json(res, 500, { ok: false, error: '专家分析输出协议版本不匹配' });
    const prompt = contract?.prompts?.node_analysis;
    if (!prompt?.system || prompt.id !== 'operating-node-analysis-v5') return json(res, 500, { ok: false, error: '专家节点分析提示词版本不匹配' });
    const userMessage = JSON.stringify(payload);
    let call = await requestConfiguredModelJson([{ role: 'system', content: prompt.system }, { role: 'user', content: userMessage }], 0.1, { max_tokens: 6000, taskKey: 'strategy_node' });
    let checked = validateStrategyAnalysis(call.result, payload), repairCount = 0;
    if (checked.errors.length) {
      repairCount = 1;
      call = await requestConfiguredModelJson([
        { role: 'system', content: `${prompt.system}\n你正在修复上一份不符合协议的输出。必须逐项修复校验错误，不得改变输入事实。` },
        { role: 'user', content: JSON.stringify({ task: 'repair_operating_node_analysis_v5', validationErrors: checked.errors, originalOutput: call.result, sourcePayload: payload }) }
      ], 0, { max_tokens: 6000, taskKey: 'strategy_node' });
      checked = validateStrategyAnalysis(call.result, payload);
    }
    if (checked.errors.length) return json(res, 422, { ok: false, error: '模型输出未通过专家分析协议校验', validationErrors: checked.errors });
    return json(res, 200, {
      ok: true,
      analysis: normalizeStrategyAnalysis(checked.result, payload),
      trace: { promptVersion: prompt.id, promptContractVersion: contract.version, contractVersion: schema.version, knowledgeVersion: payload.knowledgeVersion || 'unknown', model: call.model, thinkingMode: call.thinkingMode || 'unknown', modelAttempts: call.attempts || 1, repairCount, validatedAt: new Date().toISOString() }
    });
  } catch (error) {
    return json(res, 502, { ok: false, error: `专家节点分析失败：${error.message}` });
  }
}

function dailyContracts() {
  return {
    prompts: readJsonFile(DAILY_PROMPT_PATH, { version: 'daily-operating-prompts-v2.2', prompts: {} }),
    schema: readJsonFile(DAILY_SCHEMA_PATH, { version: 'daily-operating-schema-v2' })
  };
}

function dailyModelAvailable() {
  const settings = readSettings();
  return settings.reportProvider === 'api' && Boolean(String(settings.reportApiEndpoint || '').trim() && String(settings.reportApiKey || '').trim() && String(settings.reportModel || '').trim());
}

async function dailyModelBrief(context) {
  const prompt = dailyContracts().prompts?.prompts?.daily_diagnosis;
  if (!prompt?.system) throw new Error('每日诊断提示词契约不存在');
  const call = await requestConfiguredModelJson([
    { role: 'system', content: prompt.system },
    { role: 'user', content: JSON.stringify({ task: 'daily_diagnosis', context, outputSchema: dailyContracts().schema.dailyBrief }) }
  ], 0.15, { max_tokens: 4500, taskKey: 'daily_brief' });
  return normalizeDailyBrief({ ...call.result, generatedBy: 'external-model', model: call.model, thinkingMode: call.thinkingMode }, context);
}

async function dailyModelIdeas(context, brief, lenses, limit = 5) {
  const prompt = dailyContracts().prompts?.prompts?.idea_generation;
  if (!prompt?.system) throw new Error('经营灵感提示词契约不存在');
  const priorIdeas = ideaStateValue().items.filter(item => item.venue === context.scope.venue || item.venue === 'all').slice(-40).map(item => {
    const shaped = { ideaId: item.ideaId, title: item.title || '', status: item.status, problemScope: item.problemScope || item.issueId || '', causalHypothesis: item.causalHypothesis || item.keyAssumptions?.[0] || '', solutionMechanism: item.solutionMechanism || item.potentialMechanism || item.title || '', targetAudience: item.targetAudience || '', substantiveDelta: item.substantiveDelta || '', evidenceRefs: item.evidenceRefs || [] };
    return { ...shaped, semanticKey: item.semanticKey || ideaSemanticKey({ venue: item.venue, ...shaped }) };
  });
  const call = await requestConfiguredModelJson([
    { role: 'system', content: prompt.system },
    { role: 'user', content: JSON.stringify({ task: 'idea_generation', context, brief, lenses, priorIdeas, limit, outputSchema: dailyContracts().schema.idea }) }
  ], 0.65, { max_tokens: 6500, taskKey: 'idea_generation' });
  const priorKeys = new Set(priorIdeas.map(item => item.semanticKey).filter(Boolean));
  return normalizeDailyIdeas(call.result, context, brief, limit)
    .filter(item => Boolean(item.substantiveDelta) || (!priorKeys.has(item.semanticKey) && !priorIdeas.some(prior =>
      intelligenceSimilarity(prior.problemScope, item.problemScope) >= 0.72
      && intelligenceSimilarity(prior.solutionMechanism, item.solutionMechanism) >= 0.72
      && (!prior.targetAudience || !item.targetAudience || intelligenceSimilarity(prior.targetAudience, item.targetAudience) >= 0.6)
    )))
    .map(item => ({ ...item, generatedBy: 'external-model', model: call.model, thinkingMode: call.thinkingMode }));
}

function dailyBriefKey(date, venue) {
  return `${date}|${venue || 'all'}`;
}

function dailyFallbackSnapshot(date, venue) {
  const rows = dailyRecordRows(venue).filter(row => String(row.periodStart || '') <= date && String(row.periodEnd || '') >= date);
  const row = rows[0];
  const daily = row?.daily?.find(item => item.date === date) || null;
  return {
    date, venue, venueId: dailyVenueId(venue), sourceStatus: row && daily ? 'record-derived' : 'missing',
    weekly: { sales: daily?.boxOffice ?? null, tickets: null, net: null, onlineSales: null, offlineSales: null },
    daily: daily ? [{ date, sales: daily.boxOffice ?? null, tickets: null, net: null, sourceRows: 0, missing: true }] : [],
    channels: {}, source: { title: '本地周记录（推导）', revision: row?.sourceRevision || null }, fetchedAt: new Date().toISOString()
  };
}

async function fetchDailySnapshot(date, venue) {
  try {
    if (!APP_ID || !APP_SECRET || !SOURCE_SPREADSHEET_TOKEN) throw new Error('来源表服务未配置');
    const preview = await sourcePreview({ periodStart: date, periodEnd: date, venue });
    const day = preview.daily?.[0] || {};
    return { date, venue, venueId: dailyVenueId(venue), sourceStatus: day.missing ? 'missing' : 'feishu', weekly: preview.weekly || {}, daily: preview.daily || [], channels: preview.channels || {}, source: preview.source || {}, warnings: preview.warnings || [], fetchedAt: new Date().toISOString() };
  } catch (error) {
    return { ...dailyFallbackSnapshot(date, venue), warnings: [`来源表快照未读取：${error.message}`] };
  }
}

async function ensureDailySnapshots(date, scope = 'all', force = false) {
  const state = dailyStateValue();
  const names = dailyVenueNames(scope);
  for (const venue of names) {
    const key = `${date}|${venue}`;
    if (!force && state.snapshots[key]?.date === date && state.snapshots[key]?.fetchedAt) continue;
    state.snapshots[key] = await fetchDailySnapshot(date, venue);
  }
  state.updatedAt = new Date().toISOString();
  writeRuntimeState('daily', state);
  return state;
}

function dailyIdeaPresentation(item) {
  const fallbackHook = item?.ideaLevel === 'reconstruction'
    ? '这个想法可以大胆一点：先别急着修补现在这条路。'
    : item?.ideaLevel === 'immediate'
      ? '这个也许不用大改，换一个动作就可能不一样。'
      : '要不要把视线往旁边挪一点？也许那里藏着一个新解法。';
  const planSteps = Array.isArray(item?.planSteps) && item.planSteps.length ? item.planSteps : [
    item?.keyAssumptions?.[0] ? `先确认：${item.keyAssumptions[0]}` : '',
    item?.cheapestNextExploration ? `先小范围试一次：${item.cheapestNextExploration}` : '',
    item?.potentialMechanism ? `如果有反馈，再围绕“${item.potentialMechanism}”补成完整方案` : ''
  ].filter(Boolean);
  return { ...item, hook: String(item?.hook || fallbackHook), pitch: String(item?.pitch || item?.summary || ''), summary: String(item?.pitch || item?.summary || ''), planSteps: planSteps.slice(0, 4) };
}

function dailyIdeasFor(date, venue) {
  const state = ideaStateValue();
  return state.items.filter(item => item?.asOf === date && (venue === 'all' || item.venue === venue) && item.status !== 'dismissed').sort((a, b) => String(b.generatedAt || '').localeCompare(String(a.generatedAt || ''))).slice(0, 30).map(dailyIdeaPresentation);
}

function dailySavedIdeas(venue = 'all') {
  const state = ideaStateValue();
  return state.items.filter(item => ['saved', 'exploring', 'converted_to_tactic'].includes(item?.status) && (venue === 'all' || item.venue === venue || item.venue === 'all'))
    .sort((a, b) => String(b.updatedAt || b.generatedAt || '').localeCompare(String(a.updatedAt || a.generatedAt || ''))).slice(0, 20).map(dailyIdeaPresentation);
}

function dailyPersistBrief(brief) {
  const state = dailyStateValue();
  state.briefs[dailyBriefKey(brief.asOf, brief.venue)] = brief;
  state.updatedAt = new Date().toISOString();
  writeRuntimeState('daily', state);
  return brief;
}

function dailyPersistIdeas(items) {
  items = items.map(item => ({
    ...item,
    problemScope: item.problemScope || item.issueId || '',
    causalHypothesis: item.causalHypothesis || item.keyAssumptions?.[0] || '',
    solutionMechanism: item.solutionMechanism || item.potentialMechanism || item.title || '',
    targetAudience: item.targetAudience || '',
    semanticKey: item.semanticKey || ideaSemanticKey({ venue: item.venue, problemScope: item.problemScope || item.issueId, causalHypothesis: item.causalHypothesis || item.keyAssumptions?.[0], solutionMechanism: item.solutionMechanism || item.potentialMechanism || item.title, targetAudience: item.targetAudience }),
  }));
  const state = ideaStateValue();
  const scopes = new Set(items.map(item => `${item.asOf || ''}|${item.venue || 'all'}`));
  const retained = state.items.filter(item => {
    const scope = `${item.asOf || ''}|${item.venue || 'all'}`;
    return !scopes.has(scope) || ['saved', 'exploring', 'converted_to_tactic'].includes(item.status);
  });
  const byId = new Map(retained.map(item => [item.ideaId, item]));
  const semanticOwners = new Map(retained.filter(item => item.semanticKey).map(item => [item.semanticKey, item]));
  items.forEach(item => {
    const semanticOwner = item.semanticKey ? semanticOwners.get(item.semanticKey) : null;
    if (semanticOwner && semanticOwner.ideaId !== item.ideaId && !item.substantiveDelta) return;
    const existing = byId.get(item.ideaId);
    const keepStatus = existing && ['saved', 'exploring', 'converted_to_tactic'].includes(existing.status) && item.status === 'new';
    byId.set(item.ideaId, { ...existing, ...item, ...(keepStatus ? { status: existing.status, deepening: existing.deepening, conversion: existing.conversion } : {}) });
    if (item.semanticKey) semanticOwners.set(item.semanticKey, item);
  });
  state.items = [...byId.values()].slice(-500);
  state.updatedAt = new Date().toISOString();
  writeRuntimeState('ideas', state);
  return items;
}

function dailyContextBrief(context) {
  const state = dailyStateValue();
  const key = dailyBriefKey(context.scope.asOf, context.scope.venue);
  return state.briefs[key] || null;
}

async function dailyPayload({ date = dailyIsoNow(), venue = 'all', refresh = false, force = false, includeIdeas = true } = {}) {
  const scope = dailyVenueName(venue);
  if (refresh) await ensureDailySnapshots(date, scope, force);
  const context = dailyContext({ date, venue: scope });
  let brief = dailyContextBrief(context);
  if (brief) {
    const normalized = normalizeDailyBrief(brief, context);
    if (normalized.status !== brief.status || normalized.briefType !== brief.briefType || normalized.dataAvailable !== brief.dataAvailable || normalized.canFeedback !== brief.canFeedback) dailyPersistBrief(normalized);
    brief = normalized;
  }
  let generated = false;
  if (!brief || force || brief.contextFingerprint !== context.contextFingerprint) {
    brief = dailyLocalBrief(context);
    dailyPersistBrief(brief);
    generated = true;
  }
  let ideas = includeIdeas ? dailyIdeasFor(date, scope) : [];
  // 已生成的灵感是用户可继续保存、深入和转化的内容资产。经营上下文的
  // 版本变化只意味着“可以刷新”，不应在普通打开页面时用本地模板静默覆盖；
  // 只有当前范围完全没有灵感时才生成兜底内容，主动换一批则走 refresh 接口。
  if (includeIdeas && !ideas.length) {
    ideas = dailyLocalIdeas(context, brief, 5);
    dailyPersistIdeas(ideas);
    ideas = dailyIdeasFor(date, scope);
  }
  return { ok: true, date, venue: scope, brief, ideas, savedIdeas: dailySavedIdeas(scope), context: { fingerprint: context.contextFingerprint, missingInformation: context.missingInformation, snapshotCount: context.dailySnapshots.length, todayDataAvailable: context.currentPeriodAvailable !== false, currentPeriodAvailable: context.currentPeriodAvailable !== false, openIssueCount: context.openIssues.length, activeValidationCount: context.activeValidations.length }, generated };
}

async function refreshDailyPayload(input = {}) {
  const date = /^\d{4}-\d{2}-\d{2}$/.test(String(input.date || '')) ? String(input.date) : dailyIsoNow();
  const venue = dailyVenueName(input.venue || input.venueId || 'all');
  const force = Boolean(input.force);
  await ensureDailySnapshots(date, venue, force);
  const context = dailyContext({ date, venue });
  let brief;
  let fallbackReason = '';
  if (dailyModelAvailable()) {
    try { brief = await dailyModelBrief(context); }
    catch (error) { fallbackReason = error.message || String(error); brief = dailyLocalBrief(context); }
  } else {
    fallbackReason = '当前未配置可用的外部模型服务';
    brief = dailyLocalBrief(context);
  }
  if (fallbackReason) brief.fallbackReason = fallbackReason;
  dailyPersistBrief(brief);
  const lensItems = dailyIdeaLenses().slice(0, 8);
  let ideas;
  if (dailyModelAvailable()) {
    try { ideas = await dailyModelIdeas(context, brief, lensItems, Number(input.limit || 5)); }
    catch (error) { fallbackReason = fallbackReason || error.message || String(error); ideas = dailyLocalIdeas(context, brief, Number(input.limit || 5)); }
  } else ideas = dailyLocalIdeas(context, brief, Number(input.limit || 5));
  if (fallbackReason) ideas = ideas.map(item => ({ ...item, fallbackReason }));
  dailyPersistIdeas(ideas);
  return dailyPayload({ date, venue, includeIdeas: true });
}

async function handleDailyRoute(req, res, pathname, searchParams) {
  if (req.method === 'GET' && pathname === '/api/today') {
    const date = /^\d{4}-\d{2}-\d{2}$/.test(searchParams.get('date') || '') ? searchParams.get('date') : dailyIsoNow();
    return json(res, 200, await dailyPayload({ date, venue: searchParams.get('venue') || 'all', includeIdeas: true }));
  }
  if (req.method === 'POST' && pathname === '/api/daily/snapshot') {
    const input = await readJsonBody(req, 64 * 1024);
    const state = await ensureDailySnapshots(input.date || dailyIsoNow(), input.venue || 'all', Boolean(input.force));
    return json(res, 200, { ok: true, date: input.date || dailyIsoNow(), snapshots: state.snapshots });
  }
  if (req.method === 'POST' && pathname === '/api/today/refresh') {
    return json(res, 200, await refreshDailyPayload(await readJsonBody(req, 256 * 1024)));
  }
  if (req.method === 'POST' && pathname === '/api/ideas/refresh') {
    const input = await readJsonBody(req, 256 * 1024);
    const date = /^\d{4}-\d{2}-\d{2}$/.test(String(input.date || '')) ? String(input.date) : dailyIsoNow();
    const venue = dailyVenueName(input.venue || 'all');
    await ensureDailySnapshots(date, venue, Boolean(input.force));
    const context = dailyContext({ date, venue });
    const brief = dailyContextBrief(context) || dailyLocalBrief(context);
    let ideas;
    if (dailyModelAvailable()) {
      try { ideas = await dailyModelIdeas(context, brief, dailyIdeaLenses(), Number(input.limit || 5)); }
      catch { ideas = dailyLocalIdeas(context, brief, Number(input.limit || 5)); }
    } else ideas = dailyLocalIdeas(context, brief, Number(input.limit || 5));
    dailyPersistIdeas(ideas);
    return json(res, 200, { ok: true, date, venue, ideas: dailyIdeasFor(date, venue) });
  }
  const ideaMatch = pathname.match(/^\/api\/ideas\/([^/]+)\/(reaction|deepen|convert)$/);
  if (req.method === 'POST' && ideaMatch) {
    const ideaId = decodeURIComponent(ideaMatch[1]);
    const action = ideaMatch[2];
    const input = await readJsonBody(req, 64 * 1024);
    const ideasState = ideaStateValue();
    const idea = ideasState.items.find(item => item.ideaId === ideaId);
    if (!idea && action === 'reaction' && ideaId.startsWith('brief-')) {
      const event = { id: `interaction-${Date.now().toString(36)}`, ideaId, subjectType: 'daily_brief', action: String(input.action || 'viewed'), venue: String(input.venue || 'all'), createdAt: new Date().toISOString() };
      const interactions = interactionStateValue(); interactions.items.push(event); interactions.items = interactions.items.slice(-1000); interactions.updatedAt = event.createdAt; writeRuntimeState('interactions', interactions);
      return json(res, 200, { ok: true, interaction: event });
    }
    if (!idea) return json(res, 404, { ok: false, error: '未找到该经营想法' });
    if (action === 'reaction') {
      const event = { id: `interaction-${Date.now().toString(36)}`, ideaId, action: String(input.action || 'viewed'), venue: idea.venue || 'all', createdAt: new Date().toISOString() };
      const interactions = interactionStateValue(); interactions.items.push(event); interactions.items = interactions.items.slice(-1000); interactions.updatedAt = event.createdAt; writeRuntimeState('interactions', interactions);
      if (event.action === 'saved') idea.status = 'saved';
      if (event.action === 'not_relevant' || event.action === 'dismissed') idea.status = 'dismissed';
      idea.updatedAt = event.createdAt; ideasState.updatedAt = event.createdAt; writeRuntimeState('ideas', ideasState);
      return json(res, 200, { ok: true, idea, interaction: event });
    }
    if (action === 'deepen') {
      idea.status = 'exploring'; idea.deepening = { question: '这个想法要成立，最需要先确认哪一个条件？', upside: '潜在收益需要结合门店容量、成本和可触达客群测算。', firstStep: idea.cheapestNextExploration || '先做一次小范围观察或访谈。', updatedAt: new Date().toISOString() }; idea.updatedAt = idea.deepening.updatedAt; ideasState.updatedAt = idea.deepening.updatedAt; writeRuntimeState('ideas', ideasState); return json(res, 200, { ok: true, idea });
    }
    idea.status = 'converted_to_tactic'; idea.conversion = { status: '已进入打法草稿', tacticPlanId: String(input.tacticPlanId || ''), createdAt: new Date().toISOString() }; idea.updatedAt = idea.conversion.createdAt; ideasState.updatedAt = idea.conversion.createdAt; writeRuntimeState('ideas', ideasState); return json(res, 200, { ok: true, idea });
  }
  return false;
}

const server = http.createServer(async (req, res) => {
  if (req.method === 'OPTIONS') return json(res, 204, {});
  if (req.method === 'GET' && req.url === '/health') return json(res, 200, { ok: true, service: 'weekly-ops-feishu-sync', provider: 'feishu-open-api', configured: Boolean(APP_ID && APP_SECRET), sourceConfigured: Boolean(SOURCE_SPREADSHEET_TOKEN), workbook: TARGET.workbook.title, revision: TARGET.workbook.revision });
  if (req.method === 'GET' && req.url === '/api/settings') return json(res, 200, { ok: true, settings: publicSettings() });
  if (req.method === 'PUT' && req.url === '/api/settings') {
    try {
      const input = await readJsonBody(req, 64 * 1024);
      const next = normalizeSettings(input);
      writeSettings(next);
      return json(res, 200, { ok: true, settings: publicSettings(next) });
    } catch (error) {
      return json(res, 400, { ok: false, error: error.message });
    }
  }
  const dailyUrl = new URL(req.url, `http://${HOST}:${PORT}`);
  if (dailyUrl.pathname === '/api/today' || dailyUrl.pathname === '/api/today/refresh' || dailyUrl.pathname === '/api/daily/snapshot' || dailyUrl.pathname === '/api/ideas/refresh' || dailyUrl.pathname.startsWith('/api/ideas/')) {
    try {
      const handled = await handleDailyRoute(req, res, dailyUrl.pathname, dailyUrl.searchParams);
      if (handled !== false) return handled;
    } catch (error) {
      return json(res, 502, { ok: false, error: `今日经营服务失败：${error.message}` });
    }
  }
  // ── 溪语经营知识桥 API ────────────────────────────────────────────────────
  // 该接口只服务于“按需读上下文 + 写候选”，不提供绕过工作台状态机的正式写入。
  if (String(req.url || '').split('?')[0] === '/api/knowledge/catalog' && req.method === 'GET') {
    if (!xiyuBridgeAllowed(req)) return json(res, 401, { ok: false, error: '溪语经营知识桥未授权' });
    return json(res, 200, { ok: true, catalog: buildKnowledgeCatalog() });
  }
  if (String(req.url || '').split('?')[0] === '/api/knowledge/retrieve' && req.method === 'POST') {
    if (!xiyuBridgeAllowed(req)) return json(res, 401, { ok: false, error: '溪语经营知识桥未授权' });
    try {
      const input = await readJsonBody(req, 256 * 1024);
      if (!input?.projectId && !input?.scope?.projectId) return json(res, 400, { ok: false, error: 'projectId 必填' });
      const authorization = authorizeXiyuScope(input);
      if (!authorization.allowed) {
        auditXiyuKnowledge('retrieve', authorization);
        return json(res, 403, { ok: false, error: '当前用户无权读取该项目或门店资料' });
      }
      const plan = planSourceLookup(input, readStrategyProfile());
      let context;
      if (plan) {
        if (plan.status === 'ready' && !normalizeScopeVenueNames(input.scope || {}).includes(plan.venue)) return json(res, 403, { ok: false, error: '查询门店不在本轮授权范围' });
        if (plan.status === 'ready' && !authorizeXiyuScope({ ...input, scope: { ...input.scope, venueIds: [plan.venueId], venueNames: [plan.venue] } }).allowed) return json(res, 403, { ok: false, error: '无权访问所选来源门店' });
        let result;
        try { result = plan.status === 'ready' ? await lookupSourceFact(plan) : plan; }
        catch (error) { result = { status: 'unavailable', reason: error.message }; }
        context = { schemaVersion: 'enterpriseContext-v3', scope: input.scope, items: [], sourceLookup: result, missingInformation: result.status === 'complete' ? [] : [result.reason || '来源行或指标不完整，不能将缺失当作零'], boundaries: [result.boundary || '只回答所选来源中已核对的精确日期和门店'] };
        if (result.status === 'complete') context.items.push({ id: `source:${plan.capabilityId}:${plan.venueId}:${plan.date}`, assetType: 'operating_fact', epistemicStatus: 'system_fact', title: `${plan.date} ${plan.venue}`, summary: JSON.stringify({ venue: plan.venue, periodStart: plan.date, periodEnd: plan.date, core: result.core, sourceTitle: result.sourceTitle, sourceUrl: result.sourceUrl, boundary: result.boundary }), scope: { projectId: input.projectId, venue: plan.venue }, refs: [{ url: result.sourceUrl }] });
      } else context = buildEnterpriseKnowledgeContext({ ...input, scope: { ...(input.scope || {}), projectId: input.projectId || input.scope?.projectId } });
      auditXiyuKnowledge('retrieve', authorization, { itemCount: context.items?.length || 0 });
      return json(res, 200, { ok: true, context });
    } catch (error) {
      return json(res, 400, { ok: false, error: `经营上下文检索失败：${error.message}` });
    }
  }
  if (String(req.url || '').split('?')[0] === '/api/knowledge/overview' && req.method === 'GET') {
    const knowledge = knowledgeStateValue();
    const experiences = readRuntimeState('experiences').data || {};
    return json(res, 200, { ok: true, implicitCount: knowledge.implicitItems.length, openGapCount: knowledge.gaps.filter(item => ['open', 'asking', 'review_pending'].includes(item.status)).length, formalExperienceCount: (experiences.items || []).filter(item => item.status === 'published' && item.retrievalEligible === true).length, knowledge });
  }
  if (String(req.url || '').split('?')[0] === '/api/knowledge/map' && req.method === 'GET') {
    if (!xiyuBridgeAllowed(req)) return json(res, 401, { ok: false });
    const url = new URL(req.url, 'http://localhost');
    const scope = { projectId: readStrategyProfile().project?.id || 'yuanqu-vr', venueNames: url.searchParams.get('venue') ? [url.searchParams.get('venue')] : Object.keys(readStrategyProfile().venues || {}) };
    const authorization = authorizeXiyuScope({ actorId: url.searchParams.get('actorId') || '', scope, projectId: scope.projectId });
    if (!authorization.allowed) return json(res, 403, { ok: false });
    return json(res, 200, { ok: true, map: buildKnowledgeMap(knowledgeStateValue(), scope, url.searchParams.get('role')) });
  }
  if (String(req.url || '').split('?')[0] === '/api/knowledge/gaps/refresh' && req.method === 'POST') {
    if (!xiyuBridgeAllowed(req)) return json(res, 401, { ok: false, error: '溪语经营知识桥未授权' });
    try {
      const input = await readJsonBody(req, 128 * 1024);
      if (!authorizeXiyuScope(input).allowed) return json(res, 403, { ok: false, error: '当前用户无权分析该范围的知识缺口' });
      return json(res, 200, { ok: true, ...(await refreshKnowledgeGaps(input)) });
    }
    catch (error) { return json(res, 400, { ok: false, error: `知识缺口分析失败：${error.message}` }); }
  }
  if (String(req.url || '').split('?')[0] === '/api/knowledge/gaps' && req.method === 'GET') {
    const state = knowledgeStateValue();
    return json(res, 200, { ok: true, items: state.gaps, updatedAt: state.updatedAt });
  }
  const knowledgeGapMatch = String(req.url || '').split('?')[0].match(/^\/api\/knowledge\/gaps\/([^/]+)$/);
  if (knowledgeGapMatch && req.method === 'PUT') {
    try {
      const stateRef = readRuntimeState('knowledge'); const state = knowledgeStateValue();
      const gap = state.gaps.find(item => item.id === decodeURIComponent(knowledgeGapMatch[1]));
      if (!gap) return json(res, 404, { ok: false, error: '知识缺口不存在' });
      const input = await readJsonBody(req, 64 * 1024);
      if (['open', 'asking', 'review_pending', 'confirmed', 'dismissed'].includes(input.status)) gap.status = input.status;
      if (input.question !== undefined) gap.question = knowledgeSnippet(input.question, 600);
      gap.updatedAt = new Date().toISOString(); if (['confirmed', 'dismissed'].includes(gap.status)) gap.resolvedAt = gap.updatedAt;
      state.updatedAt = gap.updatedAt; const saved = writeRuntimeState('knowledge', state, stateRef.revision);
      return json(res, 200, { ok: true, gap, revision: saved.revision });
    } catch (error) { return json(res, 400, { ok: false, error: `知识缺口更新失败：${error.message}` }); }
  }
  const intelligenceUrl = new URL(req.url, `http://${HOST}:${PORT}`);
  if (intelligenceUrl.pathname === '/api/intelligence/candidates') {
    if (!xiyuBridgeAllowed(req)) return json(res, 401, { ok: false, error: '溪语经营知识桥未授权' });
    const state = intelligenceStateValue();
    if (req.method === 'GET') {
      const status = String(intelligenceUrl.searchParams.get('status') || '').trim();
      const projectId = String(intelligenceUrl.searchParams.get('projectId') || '').trim();
      const venue = String(intelligenceUrl.searchParams.get('venue') || '').trim();
      const items = state.items.filter(item => (!status || item.reviewStatus === status) && (!projectId || item.scope?.projectId === projectId) && (!venue || item.scope?.venueNames?.includes(venue) || item.scope?.venueIds?.includes(venue))).slice(-200).reverse();
      return json(res, 200, { ok: true, schemaVersion: state.schemaVersion, items, total: items.length, updatedAt: state.updatedAt });
    }
    if (req.method === 'POST') {
      try {
        const input = await readJsonBody(req, 256 * 1024);
        const authorization = authorizeXiyuScope({ actorId: input.source?.actorId || input.actorId, projectId: input.scope?.projectId, scope: input.scope });
        if (!authorization.allowed) {
          auditXiyuKnowledge('candidate_create', authorization);
          return json(res, 403, { ok: false, error: '当前用户无权向该项目或门店写入候选信息' });
        }
        const candidate = normalizeIntelligenceCandidate(input, req);
        candidate.reviewStatus = 'pending';
        if (!candidate.statement) return json(res, 400, { ok: false, error: '候选信息 statement 必填' });
        const existing = state.items.find(item => (candidate.id && item.id === candidate.id) || (candidate.idempotencyKey && item.idempotencyKey === candidate.idempotencyKey));
        if (existing) return json(res, 200, { ok: true, duplicate: true, candidate: existing });
        // 先找“同义且不冲突”的历史项：这样既不会把上升/下降误合并，也能让后来重复的下降表述合并到下降候选。
        const semanticMatch = [...state.items].reverse().find(item => item.candidateType === candidate.candidateType && sameIntelligenceScope(item, candidate) && JSON.stringify(item.timeRange) === JSON.stringify(candidate.timeRange) && (!candidate.knowledgeGapId || item.knowledgeGapId === candidate.knowledgeGapId) && !intelligenceConflictReason(item, candidate) && intelligenceSimilarity(item.statement, candidate.statement) >= 0.72);
        if (semanticMatch) {
          semanticMatch.lastSeenAt = candidate.updatedAt;
          semanticMatch.occurrenceCount = Number(semanticMatch.occurrenceCount || 1) + 1;
          semanticMatch.sourceQuotes = [...new Set([...(semanticMatch.sourceQuotes || [semanticMatch.source?.quote]).filter(Boolean), candidate.source?.quote].filter(Boolean))].slice(-8);
          semanticMatch.updatedAt = candidate.updatedAt;
          state.updatedAt = candidate.updatedAt;
          writeRuntimeState('intelligence', state);
          return json(res, 200, { ok: true, duplicate: true, suppressed: semanticMatch.reviewStatus === 'rejected', candidate: semanticMatch });
        }
        const conflicting = [...state.items].reverse().map(item => ({ item, reason: intelligenceConflictReason(item, candidate) })).find(value => value.reason);
        if (conflicting) {
          candidate.conflicts = [...new Set([...(candidate.conflicts || []), conflicting.reason])];
          if (['pending', 'needs_clarification'].includes(conflicting.item.reviewStatus)) {
            conflicting.item.reviewStatus = 'conflicted';
            conflicting.item.conflicts = [...new Set([...(conflicting.item.conflicts || []), `与候选 ${candidate.id} 的表述冲突`])];
            conflicting.item.updatedAt = candidate.updatedAt;
          }
        }
        if (candidate.conflicts.length) candidate.reviewStatus = 'conflicted';
        state.items.push(candidate);
        state.items = state.items.slice(-1000);
        state.updatedAt = candidate.updatedAt;
        const saved = writeRuntimeState('intelligence', state);
        reconcileCandidateGap(candidate);
        auditXiyuKnowledge('candidate_create', authorization, { itemCount: 1 });
        return json(res, 201, { ok: true, duplicate: false, candidate, revision: saved.revision });
      } catch (error) {
        return json(res, 400, { ok: false, error: `候选信息保存失败：${error.message}` });
      }
    }
    return json(res, 405, { ok: false, error: '不支持的候选信息操作' });
  }
  const intelligenceItem = intelligenceUrl.pathname.match(/^\/api\/intelligence\/candidates\/([^/]+)$/);
  if (intelligenceItem && req.method === 'PUT') {
    if (!xiyuBridgeAllowed(req)) return json(res, 401, { ok: false, error: '溪语经营知识桥未授权' });
    try {
      const state = intelligenceStateValue();
      const item = state.items.find(row => row.id === decodeURIComponent(intelligenceItem[1]));
      if (!item) return json(res, 404, { ok: false, error: '候选信息不存在' });
      const input = await readJsonBody(req, 64 * 1024);
      const allowedStatus = new Set(['pending', 'needs_clarification', 'accepted', 'linked', 'rejected', 'duplicate', 'conflicted']);
      if (input.reviewStatus && allowedStatus.has(input.reviewStatus)) item.reviewStatus = input.reviewStatus;
      if (input.suggestedTarget !== undefined) item.suggestedTarget = knowledgeSnippet(input.suggestedTarget, 80);
      if (Array.isArray(input.relatedAssetRefs)) item.relatedAssetRefs = input.relatedAssetRefs.map(String).slice(0, 30);
      item.reviewNote = knowledgeSnippet(input.reviewNote || item.reviewNote || '', 1000);
      item.reviewedAt = new Date().toISOString(); item.updatedAt = item.reviewedAt;
      const saved = writeRuntimeState('intelligence', state);
      reconcileCandidateGap(item);
      return json(res, 200, { ok: true, candidate: item, revision: saved.revision });
    } catch (error) {
      return json(res, 400, { ok: false, error: `候选信息更新失败：${error.message}` });
    }
  }
  const intelligenceApply = intelligenceUrl.pathname.match(/^\/api\/intelligence\/candidates\/([^/]+)\/apply$/);
  if (intelligenceApply && req.method === 'POST') {
    if (!xiyuBridgeAllowed(req)) return json(res, 401, { ok: false, error: '溪语经营知识桥未授权' });
    try {
      const state = intelligenceStateValue();
      const item = state.items.find(row => row.id === decodeURIComponent(intelligenceApply[1]));
      if (!item) return json(res, 404, { ok: false, error: '候选信息不存在' });
      const input = await readJsonBody(req, 64 * 1024);
      if (input.resolveConflicts === true && item.reviewStatus === 'conflicted') {
        item.resolvedConflicts = item.conflicts || []; item.conflicts = []; item.reviewStatus = 'accepted';
        item.reviewNote = knowledgeSnippet(input.reviewNote || '运营者在候选箱明确确认冲突后应用', 1000);
      }
      const application = applyIntelligenceCandidate(item, String(input.target || ''));
      item.reviewStatus = 'linked'; item.appliedTarget = application.target; item.appliedAssetRef = application.assetId;
      item.reviewedAt = new Date().toISOString(); item.updatedAt = item.reviewedAt; state.updatedAt = item.updatedAt;
      const saved = writeRuntimeState('intelligence', state);
      reconcileCandidateGap(item, application);
      return json(res, 200, { ok: true, candidate: item, application, revision: saved.revision });
    } catch (error) {
      return json(res, 400, { ok: false, error: `候选应用失败：${error.message}` });
    }
  }
  if (intelligenceUrl.pathname === '/api/intelligence/events/refresh' && req.method === 'POST') {
    if (!xiyuBridgeAllowed(req)) return json(res, 401, { ok: false, error: '溪语经营事件桥未授权' });
    try {
      const input = await readJsonBody(req, 64 * 1024);
      const authorization = authorizeXiyuScope(input);
      if (!authorization.allowed) return json(res, 403, { ok: false, error: '当前用户无权刷新该项目或门店的经营事件' });
      const result = await refreshEnterpriseEvents({
        ...input,
        projectId: input.projectId || input.scope?.projectId,
        actorId: input.actorId || '',
        venueIds: authorization.venueIds.length ? authorization.venueIds : input.venueIds,
      });
      auditXiyuKnowledge('event_refresh', authorization, { itemCount: result.created.length });
      return json(res, 200, { ok: true, ...result });
    } catch (error) {
      return json(res, 400, { ok: false, error: `经营事件刷新失败：${error.message}` });
    }
  }
  if (intelligenceUrl.pathname === '/api/intelligence/events') {
    if (!xiyuBridgeAllowed(req)) return json(res, 401, { ok: false, error: '溪语经营事件桥未授权' });
    const state = enterpriseEventStateValue();
    if (req.method === 'GET') {
      const status = String(intelligenceUrl.searchParams.get('status') || 'pending').trim();
      const actorId = String(intelligenceUrl.searchParams.get('actorId') || '').trim();
      const items = state.items.filter(item => {
        if (item.taskType === 'order_table_monitor' && (!actorId || item.actorId !== actorId)) return false;
        return (!status || item.status === status) && (!actorId || !item.actorId || item.actorId === actorId);
      }).slice(-50).reverse();
      return json(res, 200, { ok: true, items, total: items.length, updatedAt: state.updatedAt });
    }
    if (req.method === 'POST') {
      try {
        const input = await readJsonBody(req, 128 * 1024);
        const authorization = authorizeXiyuScope(input);
        if (!authorization.allowed) return json(res, 403, { ok: false, error: '当前用户无权为该范围创建经营事件' });
        const event = normalizeEnterpriseEvent(input);
        if (!event.statement) return json(res, 400, { ok: false, error: '经营事件 statement 必填' });
        const duplicate = [...state.items].reverse().find(item => item.dedupeKey === event.dedupeKey && item.status !== 'dismissed');
        if (duplicate) return json(res, 200, { ok: true, duplicate: true, event: duplicate });
        state.items.push(event); state.items = state.items.slice(-1000); state.updatedAt = event.updatedAt;
        const saved = writeRuntimeState('events', state);
        return json(res, 201, { ok: true, duplicate: false, event, revision: saved.revision });
      } catch (error) {
        return json(res, 400, { ok: false, error: `经营事件保存失败：${error.message}` });
      }
    }
    return json(res, 405, { ok: false, error: '不支持的经营事件操作' });
  }
  const enterpriseEventItem = intelligenceUrl.pathname.match(/^\/api\/intelligence\/events\/([^/]+)$/);
  if (enterpriseEventItem && req.method === 'PUT') {
    if (!xiyuBridgeAllowed(req)) return json(res, 401, { ok: false, error: '溪语经营事件桥未授权' });
    try {
      const state = enterpriseEventStateValue();
      const event = state.items.find(item => item.id === decodeURIComponent(enterpriseEventItem[1]));
      if (!event) return json(res, 404, { ok: false, error: '经营事件不存在' });
      const input = await readJsonBody(req, 32 * 1024);
      const status = ['pending', 'delivered', 'acknowledged', 'dismissed', 'failed'].includes(input.status) ? input.status : event.status;
      event.status = status; event.deliveryNote = knowledgeSnippet(input.deliveryNote || event.deliveryNote || '', 500); event.updatedAt = new Date().toISOString();
      if (status === 'delivered') event.deliveredAt = event.updatedAt;
      if (status === 'acknowledged') event.acknowledgedAt = event.updatedAt;
      state.updatedAt = event.updatedAt;
      const saved = writeRuntimeState('events', state);
      return json(res, 200, { ok: true, event, revision: saved.revision });
    } catch (error) {
      return json(res, 400, { ok: false, error: `经营事件更新失败：${error.message}` });
    }
  }
  const runtimeStateMatch = String(req.url || '').match(/^\/api\/runtime-state\/([a-z]+)$/);
  if (runtimeStateMatch) {
    const kind = runtimeStateKind(runtimeStateMatch[1]);
    if (!kind) return json(res, 404, { ok: false, error: '未知运行数据类型' });
    if (req.method === 'GET') return json(res, 200, { ok: true, kind, ...readRuntimeState(kind) });
    if (req.method === 'PUT') {
      try {
        const input = await readJsonBody(req, 12 * 1024 * 1024);
        const result = writeRuntimeState(kind, input.data, input.expectedRevision === undefined ? null : input.expectedRevision);
        return json(res, 200, { ok: true, kind, ...result });
      } catch (error) {
        if (error.code === 'RUNTIME_STATE_CONFLICT') return json(res, 409, { ok: false, error: error.message, kind, ...error.current });
        return json(res, 400, { ok: false, error: `运行数据保存失败：${error.message}` });
      }
    }
    return json(res, 405, { ok: false, error: '不支持的运行数据操作' });
  }
  if (req.method === 'POST' && req.url === '/api/weekly-report') return proxyWeeklyReport(req, res);
  if (req.method === 'POST' && req.url === '/api/strategy/analyze-node') return analyzeStrategyNode(req, res);
  if (req.method === 'POST' && req.url === '/api/feishu/order-monitor/check') {
    if (!xiyuBridgeAllowed(req)) return json(res, 401, { ok: false, error: '溪语经营事件桥未授权' });
    try {
      const input = await readJsonBody(req, 32 * 1024);
      const authorization = authorizeXiyuScope(input);
      if (!authorization.allowed) return json(res, 403, { ok: false, error: '当前用户无权检查该项目的订单来源表' });
      const result = await checkOrderTableMonitor({ ...input, actorId: String(input.actorId || ''), projectId: input.projectId || authorization.projectId });
      auditXiyuKnowledge('order_monitor_check', authorization, { itemCount: result.totalSheets });
      return json(res, 200, { ok: true, monitor: result });
    } catch (error) {
      return json(res, 400, { ok: false, error: `订单来源表检查失败：${error.message}` });
    }
  }
  if (req.method === 'GET' && req.url.startsWith('/api/feishu/order-monitor')) {
    if (!xiyuBridgeAllowed(req)) return json(res, 401, { ok: false, error: '溪语经营事件桥未授权' });
    const url = new URL(req.url, `http://${HOST}:${PORT}`);
    const actorId = String(url.searchParams.get('actorId') || '').trim();
    const date = String(url.searchParams.get('date') || '').trim();
    const state = orderMonitorStateValue();
    const items = Object.values(state.checks).filter(item => (!actorId || item.actorId === actorId) && (!date || item.date === date)).slice(0, 30);
    return json(res, 200, { ok: true, items, updatedAt: state.updatedAt });
  }
  if (req.method === 'POST' && req.url === '/api/feishu/source-preview') {
    try {
      const input = await readJsonBody(req, 64 * 1024);
      return json(res, 200, await sourcePreview(input));
    } catch (error) {
      return json(res, 400, { ok: false, error: error.message });
    }
  }
  if (req.method === 'GET' && req.url === '/api/feishu/sources') {
    const sheets = Object.fromEntries(Object.entries(TARGET.sheets || {}).map(([id, sheet]) => [id, {
      sheetId: sheet.sheetId,
      sheetName: sheet.sheetName,
      grain: sheet.grain,
      url: `${TARGET.workbook.url}?sheet=${encodeURIComponent(sheet.sheetId)}`
    }]));
    return json(res, 200, { ok: true, workbook: { title: TARGET.workbook.title, url: TARGET.workbook.url, revision: TARGET.workbook.revision }, sheets });
  }
  if (req.method === 'GET' && req.url === '/api/strategy/prompts') {
    if (!fs.existsSync(STRATEGY_PROMPT_PATH) || !fs.existsSync(WEEKLY_PROMPT_PATH)) return json(res, 404, { ok: false, error: 'Prompt contract not found' });
    try { return json(res, 200, { ok: true, prompts: JSON.parse(fs.readFileSync(STRATEGY_PROMPT_PATH, 'utf8')), weeklyPrompts: JSON.parse(fs.readFileSync(WEEKLY_PROMPT_PATH, 'utf8')) }); }
    catch (error) { return json(res, 500, { ok: false, error: `Strategy prompt contract invalid: ${error.message}` }); }
  }
  if (req.method === 'GET' && req.url === '/api/strategy/knowledge') {
    if (!fs.existsSync(STRATEGY_KNOWLEDGE_PATH)) return json(res, 404, { ok: false, error: 'Strategy knowledge contract not found' });
    try { return json(res, 200, JSON.parse(fs.readFileSync(STRATEGY_KNOWLEDGE_PATH, 'utf8'))); }
    catch (error) { return json(res, 500, { ok: false, error: `Strategy knowledge contract invalid: ${error.message}` }); }
  }
  if (req.method === 'POST' && req.url === '/api/strategy/external-search') {
    try {
      const input = await readJsonBody(req, 128 * 1024);
      if (input?.sourceUrl) return json(res, 200, { ok: true, mode: 'source', result: await readExternalSource(input.sourceUrl) });
      const result = await searchExternalWeb(input?.query, input || {});
      return json(res, 200, { ok: true, mode: 'search', ...result });
    } catch (error) {
      return json(res, 502, { ok: false, error: `外部检索失败：${error.message}` });
    }
  }
  if (req.method === 'GET' && req.url === '/api/strategy/profile') {
    try { return json(res, 200, { ok: true, profile: readStrategyProfile() }); }
    catch (error) { return json(res, 500, { ok: false, error: `项目档案读取失败：${error.message}` }); }
  }
  if (req.method === 'PUT' && req.url === '/api/strategy/profile') {
    try {
      const input = await readJsonBody(req, 256 * 1024);
      return json(res, 200, { ok: true, profile: writeStrategyProfile(input?.profile || input) });
    } catch (error) {
      return json(res, 400, { ok: false, error: `项目档案保存失败：${error.message}` });
    }
  }
  const strategyUrl = new URL(req.url, `http://${HOST}:${PORT}`);
  if (req.method === 'GET' && strategyUrl.pathname === '/api/strategy/github-search') {
    const query = String(strategyUrl.searchParams.get('q') || '').trim();
    if (!query || query.length > 160) return json(res, 400, { ok: false, error: 'GitHub search query is required and must be 160 characters or fewer' });
    try { return json(res, 200, { ok: true, query, results: await searchGithubRepositories(query), fetchedAt: new Date().toISOString() }); }
    catch (error) { return json(res, 502, { ok: false, query, error: error.message }); }
  }
  if (req.method === 'GET' && serveStatic(req, res)) return;
  const pathname = new URL(req.url, `http://${HOST}:${PORT}`).pathname;
  if (req.method !== 'POST' || !['/api/feishu/sync', '/api/feishu/compare'].includes(pathname)) return json(res, 404, { ok: false, error: 'Not found' });
  let body = '';
  req.on('data', chunk => { body += chunk; if (body.length > 8 * 1024 * 1024) req.destroy(); });
  req.on('end', async () => {
    try {
      const task = JSON.parse(body || '{}');
      if (!task.taskId || !task.payload) return json(res, 400, { ok: false, error: 'taskId 和 payload 必填' });
      const result = pathname === '/api/feishu/compare' ? await compareTask(task) : await syncTask(task);
      return json(res, 200, result);
    } catch (error) {
      return json(res, 500, { ok: false, error: error.message, target: { title: TARGET.workbook.title, tokenLast4: SPREADSHEET_TOKEN.slice(-4) } });
    }
  });
});

export { server, dailyContext, dailyModelIdeas, refreshKnowledgeGaps, refreshEnterpriseEvents, ideaSemanticKey, normalizeDailyIdeas, orderMonitorSheets, orderMonitorRowForDate, orderMonitorStatusText, eventForOrderTableMonitor, checkOrderTableMonitor };
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  server.listen(PORT, HOST, () => console.log(`weekly-ops-feishu-sync listening on http://${HOST}:${PORT}`));
}
