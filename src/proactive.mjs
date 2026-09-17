/**
 * 
 * Copyright (c) 2026 溪语 AI Contributors. MIT License.
 */
import {
  getActiveBotAccounts, getRecentHistory, getUserProfile, recallMemories,
  getConversationContext, getDueReminders, markRemindersTriggered, ensureRelationshipReminders,
  saveMessage, saveConversationTurn,
  getCompanionById, getBotContextForCompanion, getDb,
  getActiveWechatBinding, getDailySchedule, shanghaiDateKey, getRecentSchedules, getPersonaFacts,
  markCompanionConfessed, patchCompanion,
  recordProactiveSentTimestamp, getProactiveLastSent, markWindowLastCallSent, bumpProactiveUnanswered,
  getCompanionPreferencesForPrompt,
  listDueOpenLoops, markOpenLoopFollowedUp,  // v1.8.0 #5
  listDueHerPromises, markHerPromiseDelivered,  // v1.21.5 照片承诺改期履约

  getRecentSafetyRisk,                        // v1.9.0 #1
  listShaping,                                // 共建留痕（教过她的注入主动消息）
  insertProactiveMaterialLog, getRecentlyUsedMaterialIds, getRecentProactiveTexts,  // v1.21.3 素材账本
  getCategorySendCounts,                      // v1.21.6 PR-A 照片品类 weeklyCap
  listPreferences, getMemories,               // v1.21.6 PR-B 想到你素材源（梗 listShaping 已在上）
  getActiveCurrentWorks, countRecentMaterialUse,   // v1.21.4 PR-W2 works 注入 + 周上限计数
  getActiveLifeStates,                        // v1.22 PR-L1: #317 四档身体事件闸查档案
  getEnterpriseProactivePolicy, markEnterpriseProactiveActivity,
  getProactiveRuntimeSchedule, saveProactiveRuntimeSchedule,
  createAgencyIntention, getAgencyIntention, findAgencyIntentionBySemanticKey,
  updateAgencyIntention, createAgencyAction, updateAgencyAction, listAgencyIntentions, listAgencyActions, listAgencyFeedback, recordAgencyFeedback, recordAgencyConcernEvent,
  reserveAgencyBudget, settleAgencyBudget,
  acquireAgencyLease, beginAgencyCognition, releaseAgencyLease, commitAgencyReceipt,
  getAppSetting, setAppSetting,   // 2026-09-17：通道关闭连续计数（可观测性）
} from './db.mjs';
import { getActivePeriodContext, isPeriodHeavyWindow, isPmsActive } from './life_state.mjs';   // v1.22 PR-L3 经期情绪路由
import { buildWorksPromptHint, worksSceneSeed, pickProactiveWork, workMaterialId, worksConfig } from './current_works.mjs';  // v1.21.4 PR-W2 表达层
import { pickProactiveCategory, cappedCategoryIds } from './photo_categories.mjs';  // v1.21.6 PR-A 照片品类加权采样（默认关）
import { selectThoughtMaterial, thoughtSceneSeed } from './photo_thought.mjs';      // v1.21.6 PR-B 想到你素材选择
import { filterForStorage } from './privacy_filter.mjs';                            // v1.21.6 PR-B 隐私命中判定
// v1.21.3 PR-E: 跨天素材级去重（「小汤圆」3 天 3 次）——冷却过滤只挂这条链路，
// 对话召回（bot.mjs）绝不挂：主动不提是克制，他聊起来接不住是失忆。
import {
  materialDedupDays, filterRecentlyUsed, extractMaterialRefs,
  memMaterialId, loopMaterialId, buildRecentProactiveHint,
} from './proactive_material.mjs';
import { canAcceptConfession } from './memory.mjs';
import { buildSystemPrompt } from './companion.mjs';
import { pullEnterpriseEvents, acknowledgeEnterpriseEvent, rememberActiveEnterpriseTask, completeActiveEnterpriseTask, getPendingInboundEnterpriseEvent, enterpriseProactiveEnabled, buildEnterpriseProactivePrompt, enterpriseProactiveReplyIssue, getEnterpriseCatalog, retrieveEnterpriseResult, researchEnterpriseSources } from './enterprise_context.mjs';
import { generateReply, extractStructuredInfoDetailed } from './ai.mjs';
import { sendTextMessage, sendMessageItem, recallContextToken, peekSendQuota } from './ilink.mjs';
import { dedupSegments, isSemanticallySimilar } from './text_similarity.mjs';
import { classifyIntent, topicKey, recentIntentEvents, trailingAckStreak, isIntentCooled } from './intent_dedup.mjs';
// v1.4.0: 微信端 voice 路径已废弃（iLink 协议禁止 bot outbound voice，腾讯
// 官方 SDK 没有 sendVoiceMessageWeixin，HTTP 200 但消息静默丢弃）。
// 语音功能改在 playground / dashboard 试听 / diary 朗读等浏览器端实现。
// 删除原 maybeSendVoice 调用，避免生产环境烧 TTS 配额而消息根本送不出。
import { buildLongTermDigest, ensureScheduleForCompanion } from './plan_tasks.mjs';
import { parseStickerMarkers, buildStickerPromptHint, hasStickers } from './stickers.mjs';
import { uploadFile, readMediaBuffer } from './media.mjs';
import { getPhotoGateState, planPhotoMessage } from './photo_planner.mjs';
import { sendCompanionPhoto } from './photo_sender.mjs';
import { safeOutboundReply, scrubPhotoImpersonation, scrubFabricatedIllness, scrubPeriodDisclosure } from './moderation.mjs';
import { log } from './logger.mjs';
import { buildEmotionPromptHint, getEmotionStateWithDefaults, getMissingLevel, getNeglectStage } from './emotion_state.mjs';
import { buildRealityFacts, isNightShanghai } from './utils/reality_facts.mjs';   // v1.21.4 PR-W3 统一真实世界事实层（收编月相）
import { buildShapingPromptHint } from './shaping.mjs';
import { evaluateProactive, recordProactiveSent } from './proactive_engine.mjs';
import { buildInitiativeDecision, selectProactiveLifeEvidence, initiativePrompt, initiativeReplyIssue, appendInitiativeReceipt } from './initiative.mjs';
import {
  normalizeContextSnapshot, buildAgencyAppraisalPrompt, buildAgencyPlanPrompt, buildAgencyContinuationPrompt,
  parseStructuredJson, validateAppraisalProposal, validatePlanProposal,
  decisionFeatures, buildAgencyReviewPrompt, validateReviewProposal, applyOpportunityFloor, applyPlanPolicy,
  getAgencyPromptBinding, compactAgencyResultRefs, mergeAgencyEvidenceRefs, buildAgencyContinuityKey,
} from './agency_protocol.mjs';
import { bumpProactiveHealth, recordTickHeartbeat } from './proactive_health.mjs';   // #263 误报修：三桶健康计数 + tick 心跳
import { getArcProactivePolicy, getArcExpressionContext, buildOliveBranchHint, markOliveBranchSent } from './relationship_arc_runtime.mjs';
import { tryAchievement } from './achievements.mjs';
import {
  getSleepRow, getOrRefreshTodaySchedule, exitSleep,
  drainMissed, upsertSleepSchedule,
} from './sleep.mjs';

// ─── Proactive Engine 版本选择 ────────────────────────────────────────────────
// PROACTIVE_ENGINE=v2 启用 evaluateProactive() 决策层（推荐）
// PROACTIVE_ENGINE=legacy 保留旧时间窗口调度器逻辑（兜底）
const PROACTIVE_ENGINE_MODE = (process.env.PROACTIVE_ENGINE || 'v2').toLowerCase();

const TZ = 'Asia/Shanghai';
// 早安/晚安基准时间，实际每天有 ±30min 随机波动让 AI 更像真人
const WEEKDAY_START_MINUTE = 7 * 60 + 30;   // 07:30 基准
const WEEKEND_START_MINUTE = 8 * 60;        // 08:00 基准
const LAST_MINUTE = 23 * 60 + 59;           // 23:59 上限

function enterprisePurposesDue(policy, minuteNow, nowSeconds = Math.floor(Date.now() / 1000)) {
  if (!policy?.enabled) return [];
  const due = [];
  if (policy.report_enabled) {
    const interval = Math.max(5, Number(policy.report_check_interval_minutes || 30)) * 60;
    const [hour, minute] = String(policy.report_time || '18:30').split(':').map(Number);
    const scheduledMinute = Number.isFinite(hour) && Number.isFinite(minute) ? hour * 60 + minute : 18 * 60 + 30;
    const intervalDue = !policy.last_report_check_at || nowSeconds - Number(policy.last_report_check_at) >= interval;
    const timeDue = policy.report_mode === 'data_update' ? intervalDue : (minuteNow >= scheduledMinute && intervalDue);
    if (timeDue) due.push('daily_report');
  }
  if (policy.knowledge_enabled) {
    const cooldown = Math.max(1, Number(policy.knowledge_cooldown_hours || 20)) * 3600;
    if (!policy.last_knowledge_check_at || nowSeconds - Number(policy.last_knowledge_check_at) >= cooldown) due.push('knowledge_acquisition');
  }
  if (policy.order_monitor_enabled) {
    const [hour, minute] = String(policy.order_monitor_time || '10:00').split(':').map(Number);
    const scheduledMinute = Number.isFinite(hour) && Number.isFinite(minute) ? hour * 60 + minute : 10 * 60;
    const last = Number(policy.last_order_monitor_check_at || 0);
    const lastDate = last ? shanghaiDateKey(new Date(last * 1000)) : '';
    const today = shanghaiDateKey(new Date());
    if (minuteNow >= scheduledMinute && lastDate !== today) due.push('order_table_monitor');
  }
  return due;
}
const GOODNIGHT_MINUTE = 23 * 60;           // 23:00 基准晚安
const MORNING_JITTER_MIN = 30;              // 早安 ±30min
const GOODNIGHT_JITTER_MIN = 30;            // 晚安 ±30min
const MIN_GAP_MINUTES = 30;

// 在 [-jitter, +jitter] 范围内取随机分钟偏移
function jitterOffset(jitter) {
  return Math.floor(Math.random() * (jitter * 2 + 1)) - jitter;
}
const TICK_MS = 60_000;
const PROACTIVE_SLOT_GRACE_MINUTES = Math.max(5, Number(process.env.PROACTIVE_SLOT_GRACE_MINUTES || 30));

const schedules = new Map();

// ─────────────────────────────────────────────────────────────────────────────
// 送达可观测性（2026-09-17 新增）
//
// 起因：9-15 一整天生成了内容却一条都没发出去，而排程仍标 sent:true；
// 9-16/9-17 预检生效后改为静默跳过。两种情况下**用户都毫无提示**，
// 直到两天后自己发现"她没理我"。根因是"发不出去"这件事没有任何可观测出口。
// 下面两个小工具把「连续多次机会因窗口关闭而放弃」变成计数 + 明确告警。
// ─────────────────────────────────────────────────────────────────────────────
const CHANNEL_CLOSED_KEY = 'proactive_channel_closed_streak';
const CHANNEL_CLOSED_ALERT_AT = 6;   // 连续 6 次机会都发不出去（约一天多）就告警

/** 记一次「因窗口关闭而放弃的机会」，达到阈值时明确告警。fail-open，绝不阻塞主流程。 */
function noteChannelClosedSkip(companionId, kind) {
  try {
    const next = (Number(getAppSetting(CHANNEL_CLOSED_KEY)) || 0) + 1;
    setAppSetting(CHANNEL_CLOSED_KEY, String(next));
    if (next >= CHANNEL_CLOSED_ALERT_AT && (next === CHANNEL_CLOSED_ALERT_AT || next % CHANNEL_CLOSED_ALERT_AT === 0)) {
      log('warn', `[Proactive] ⚠ 主动通道已连续 ${next} 次机会发不出去 companion=${companionId} kind=${kind}：`
        + `微信会话窗口关闭（用户已超过 24h 未互动）。她暂时无法主动联系；用户发一条消息即可重新打开窗口。`);
    }
  } catch (e) {
    log('warn', `[Proactive] 窗口关闭计数失败（已忽略）: ${e.message}`);
  }
}

/** 真正送达一次 → 窗口显然是开的，连续计数清零。fail-open。 */
function clearChannelClosedStreak() {
  try {
    setAppSetting(CHANNEL_CLOSED_KEY, '0');
  } catch { /* 计数失败不影响发送 */ }
}

// ─────────────────────────────────────────────────────────────────────────────
// 生成前预检：同一动念刚被出站门拦过就不要重复生成（2026-09-17 新增）
//
// 动机见调用点注释。要点：
//   - 只用**确定性**信息（动念 id + 计划去重键）做指纹，不引入任何模型调用；
//   - 指纹变化（新动念/新计划/新证据）立即放行，绝不把角色永久锁死；
//   - 只在"同一指纹刚刚失败过"的短时间内拦截，超过冷却窗自动放行再试一次；
//   - 全部 fail-open：读不到记忆就当没有，正常生成。
// ─────────────────────────────────────────────────────────────────────────────
const PRECHECK_KEY = 'proactive_precheck_last_failure';
const PRECHECK_COOLDOWN_MIN = 20;   // 同一指纹失败后，20 分钟内不重复生成

/**
 * 纯函数：给定「上次失败记忆」与本次指纹，判断是否该跳过生成。
 * 抽出来是为了可离线确定性回归（没有这段，预检行为只能靠生产试错验证）。
 * 返回 { skip, reason }。**必须在任何异常输入下 fail-open（skip=false）**。
 */
export function evaluatePrecheckGate(memo, { companionId, intentionId, planKey, hasEnterpriseEvent, effectiveKind, nowMs = Date.now(), cooldownMin = PRECHECK_COOLDOWN_MIN } = {}) {
  try {
    if (effectiveKind === 'reminder') return { skip: false, reason: 'reminder_exempt' };
    if (hasEnterpriseEvent) return { skip: false, reason: 'enterprise_event' };
    if (!intentionId && !planKey) return { skip: false, reason: 'no_fingerprint' };
    if (!memo || typeof memo !== 'object') return { skip: false, reason: 'no_memory' };
    if (Number(memo.companionId) !== Number(companionId)) return { skip: false, reason: 'other_companion' };
    if (String(memo.intentionId || '') !== String(intentionId || '')) return { skip: false, reason: 'new_intention' };
    if (String(memo.planKey || '') !== String(planKey || '')) return { skip: false, reason: 'new_plan' };
    const at = Number(memo.at) || 0;
    const ageMin = (Number(nowMs) - at) / 60_000;
    if (!(ageMin >= 0) || ageMin > cooldownMin) return { skip: false, reason: 'cooldown_expired' };
    return { skip: true, reason: `same_intention_${memo.reason || 'blocked'}` };
  } catch {
    return { skip: false, reason: 'gate_error' };
  }
}

/** 读上次失败记忆；指纹相同且在冷却窗内 → skip。 */
function proactivePrecheckGate(companionId, { intentionId, planKey, hasEnterpriseEvent, effectiveKind }) {
  let memo = null;
  try {
    const raw = getAppSetting(PRECHECK_KEY);
    if (raw) memo = JSON.parse(raw);
  } catch { memo = null; }
  return evaluatePrecheckGate(memo, { companionId, intentionId, planKey, hasEnterpriseEvent, effectiveKind });
}

/** 记下"这个动念这一版计划刚刚被拦"，供下一次生成前预检使用。fail-open。 */
function recordPrecheckFailure(companionId, { intentionId, planKey, reason }) {
  try {
    if (!intentionId && !planKey) return;
    setAppSetting(PRECHECK_KEY, JSON.stringify({
      companionId: Number(companionId),
      intentionId: intentionId ? String(intentionId) : null,
      planKey: planKey ? String(planKey) : null,
      reason: String(reason || 'blocked').slice(0, 40),
      at: Date.now(),
    }));
  } catch { /* fail-open */ }
}

/** 生成成功并进入投递 → 清掉失败记忆，避免后续被误挡。fail-open。 */
function clearPrecheckFailure() {
  try { setAppSetting(PRECHECK_KEY, ''); } catch { /* fail-open */ }
}

function normalizePersistedRuntimeSchedule(raw, companionId, dateKey) {
  if (!raw || raw.dateKey !== dateKey || !Array.isArray(raw.items)) return null;
  const items = raw.items
    .filter(item => item && Number.isInteger(Number(item.minute)) && Number(item.minute) >= 0 && Number(item.minute) <= LAST_MINUTE)
    .map(item => ({
      minute: Number(item.minute),
      kind: ['normal', 'morning', 'goodnight', 'photo'].includes(item.kind) ? item.kind : 'normal',
      sent: item.sent === true,
      // 2026-09-17：投递结果必须随排程持久化，否则服务重启后就看不出
      // 「这条时段到底送达了、还是失败了、还是过期作废」。
      ...(typeof item.deliveryOutcome === 'string' && item.deliveryOutcome
        ? { deliveryOutcome: item.deliveryOutcome.slice(0, 40) }
        : {}),
      ...(typeof item.deliveryAt === 'string' && item.deliveryAt
        ? { deliveryAt: item.deliveryAt.slice(0, 40) }
        : {}),
      ...(typeof item.deliveryError === 'string' && item.deliveryError
        ? { deliveryError: item.deliveryError.slice(0, 80) }
        : {}),
      ...(Number.isFinite(Number(item._v2_deny_until)) && Number(item._v2_deny_until) > 0
        ? { _v2_deny_until: Number(item._v2_deny_until) }
        : {}),
    }))
    .sort((a, b) => a.minute - b.minute);
  if (!items.length && Number(raw.targetCount) > 0) return null;
  return {
    dateKey,
    targetCount: Math.max(0, Number(raw.targetCount) || 0),
    items,
    config: raw.config && typeof raw.config === 'object' ? raw.config : {},
    companionId,
  };
}

function persistRuntimeSchedule(companionId, schedule) {
  try {
    saveProactiveRuntimeSchedule(companionId, schedule.dateKey, schedule);
  } catch (e) {
    // 排程持久化失败不能阻断当次主动消息，但要显式留日志。
    log('warn', `[Proactive] 当日排程保存失败 companion=${companionId}: ${e.message}`);
  }
}

// ─── v1.9.0 #3: 失败日志标准化（不建表，先用结构化 log，观察一段时间再决定是否升表） ──
// 用法：logProactiveFailure({ companionId, kind, errorType, latencyMs, message })
// 字段对齐 ChatGPT 的 proactive_delivery_events 设计（companion_id/kind/error_type/latency_ms），
// 但落到 log 而不是 SQL，避免提前引入维护成本。grep `[Proactive][fail]` 可统一汇总。
function classifyError(err) {
  if (!err) return 'unknown';
  if (typeof err.status === 'number') {
    if (err.status === 429) return 'rate_limit';
    if (err.status >= 500) return 'provider_5xx';
    if (err.status === 401 || err.status === 403) return 'auth';
    if (err.status === 400) return 'bad_request';
    return `http_${err.status}`;
  }
  const msg = String(err.message || err);
  if (/timeout|timed out|abort/i.test(msg))               return 'timeout';
  if (/ECONNREFUSED|ETIMEDOUT|ECONNRESET|ENOTFOUND|EAI_AGAIN|fetch failed|socket hang up/i.test(msg)) return 'network';
  if (/HTTP\s+429/i.test(msg))                            return 'rate_limit';
  if (/HTTP\s+5\d{2}/i.test(msg))                         return 'provider_5xx';
  if (/HTTP\s+(?:401|403)/i.test(msg))                    return 'auth';
  if (/HTTP\s+400/i.test(msg))                            return 'bad_request';
  return 'unknown';
}

function logProactiveFailure({ companionId, kind, error, latencyMs = null, extra = '' }) {
  const errorType = classifyError(error);
  const parts = [
    `companion=${companionId}`,
    `kind=${kind}`,
    `error_type=${errorType}`,
  ];
  if (latencyMs != null) parts.push(`latency_ms=${latencyMs}`);
  const msg = String(error?.message || error || '').slice(0, 200);
  if (msg) parts.push(`msg="${msg}"`);
  if (extra) parts.push(extra);
  log('warn', `[Proactive][fail] ${parts.join(' ')}`);
  bumpProactiveHealth('errored', { companionId, reason: errorType });   // #263 误报修：发送失败计错误桶
}

// v1.5.2 B3 修：进程内"正在处理中" companion 集合，防同 companion 并发 sendProactiveMessage
// （比如 generateReply 跑 8s 期间又来一个 tick）
const _proactiveInFlight = new Set();
// v1.5.2 B1 修：全局发送间隔（秒）。重启后会读 companions.last_proactive_sent_at 兜底。
// 比 schedule 内的 MIN_GAP_MINUTES 更硬性 — schedule 是规划，这个是闸门。
const PROACTIVE_HARD_GAP_SECONDS = 25 * 60;  // 25 分钟（比 MIN_GAP_MINUTES=30 略松，避免误杀 reminder/confession）

// v1.16.x:「窗口将关·临门一脚」—— 微信主动推送 ~24h 会话窗口将关前（idle 21-23.5h）发一次
// 轻量搭话，这是她还能主动发消息的最后机会（用户回应→token 刷新→窗口续命）。每个离开周期一次。
// 守 De Freitas《Emotional Manipulation》反操纵红线：就一句"在吗"，绝不愧疚/挽留/施压。
const LASTCALL_MIN_H = 21;
const LASTCALL_MAX_H = 23.5;

// ─── 统一动念链（shadow/enabled 可选接入；legacy 保持行为不变） ───────────────
// 这里是现有 proactive tick 的编排适配层，不另起 scheduler 或意图选择器：
// initiative 仍负责“当前要推进的方向”，本函数只负责把该方向变成可追踪的
// appraisal → intention → action 记录，并在 enabled 且调用方明确允许时交给既有发送链。
export const AGENCY_MODE = Object.freeze({
  LEGACY: 'legacy',
  SHADOW: 'shadow',
  ENABLED: 'enabled',
});

function agencyMode(mode = process.env.XIYU_AGENCY_MODE || AGENCY_MODE.LEGACY) {
  const normalized = String(mode || '').toLowerCase();
  return Object.values(AGENCY_MODE).includes(normalized) ? normalized : AGENCY_MODE.LEGACY;
}

async function executeDefaultAgencyLookup({ action, intention, decision, snapshot, owner }) {
  const event = snapshot?.businessContext || decision?.enterpriseEvent || null;
  const queryText = String(event?.question || event?.statement || action?.strategySummary || intention?.desiredChange || '').trim();
  if (!queryText) return { status: 'unsupported', cause: 'lookup_query_missing' };
  const catalog = await getEnterpriseCatalog({ force: false });
  if (!catalog) return { status: 'unavailable', cause: 'enterprise_catalog_unavailable' };
  const evidencePeriod = event?.evidencePeriod || {};
  const timeRange = String(evidencePeriod.date || evidencePeriod.periodEnd || evidencePeriod.periodStart || '').trim();
  const timeSpec = event?.timeSpec || (evidencePeriod.date
    ? { kind: 'exact_date', start: evidencePeriod.date, end: evidencePeriod.date }
    : evidencePeriod.periodStart || evidencePeriod.periodEnd
      ? { kind: 'date_range', start: evidencePeriod.periodStart || evidencePeriod.periodEnd, end: evidencePeriod.periodEnd || evidencePeriod.periodStart }
      : null);
  const scope = {
    projectId: event?.scope?.projectId || catalog?.project?.id || '',
    venueIds: Array.isArray(event?.scope?.venueIds) ? event.scope.venueIds : [],
    venueNames: Array.isArray(event?.scope?.venueNames) ? event.scope.venueNames : [],
  };
  const metricIds = Array.isArray(event?.metricIds) ? event.metricIds : [];
  const route = {
    conversationType: 'work', interactionIntent: 'lookup', retrievalNeeded: true,
    workSegments: [queryText],
    scope,
    task: {
      goal: queryText,
      completeQuestion: queryText,
      scope,
      ...(timeSpec ? { timeSpec } : {}),
      requestedOutcome: { kind: event?.requestedOutcome?.kind || 'performance_summary', businessMeaning: event?.businessMeaning || queryText, metricIds },
      businessMeaning: event?.businessMeaning || queryText,
      metricIds,
      missingSlots: [],
    },
    intent: {
      topics: Array.isArray(event?.topics) ? event.topics : [],
      metricIds,
      assetTypes: Array.isArray(event?.assetTypes) ? event.assetTypes : [],
      timeRange,
      question: queryText,
      text: queryText,
    },
  };
  const result = await retrieveEnterpriseResult(route, { accountId: owner.accountId, catalog });
  const items = Array.isArray(result?.context?.items) ? result.context.items.slice(0, 8) : [];
  const resultRefs = items.map(item => ({
    kind: 'enterprise_knowledge',
    status: item?.epistemicStatus || result.status,
    id: item?.id || null,
    title: item?.title || null,
    summary: item?.summary || null,
    refs: item?.refs || null,
    asOf: result?.asOf || null,
  }));
  if (!resultRefs.length) resultRefs.push({ kind: 'enterprise_knowledge', status: result?.status || 'not_found', cause: result?.cause || null, query: queryText, asOf: result?.asOf || null });
  return {
    status: result?.status === 'complete' && items.length ? 'complete' : result?.status || 'unavailable',
    cause: result?.cause || (items.length ? null : 'enterprise_knowledge_not_found'),
    resultRefs,
    sourceRefs: items.flatMap(item => Array.isArray(item?.refs) ? item.refs : [item?.id]).filter(Boolean).slice(0, 20),
  };
}

async function executeDefaultAgencyResearch({ action, intention, decision, snapshot }) {
  const event = snapshot?.businessContext || decision?.enterpriseEvent || null;
  const query = String(event?.researchQuery || event?.question || action?.strategySummary || intention?.desiredChange || '').trim();
  return researchEnterpriseSources({
    query,
    scope: event?.scope?.projectId || 'project',
    venue: event?.scope?.venueNames?.[0] || 'all',
    limit: 6,
  });
}

export async function runAgencyCycle({
  accountId,
  companionId,
  companion = null,
  decision = null,
  snapshot = {},
  trigger = 'opportunity',
  mode = process.env.XIYU_AGENCY_MODE || AGENCY_MODE.LEGACY,
  allowContact = false,
  runtimeGuard = false,
  sourceVersion = '',
  deps = {},
} = {}) {
  const currentMode = agencyMode(mode);
  const startedAt = Date.now();
  if (currentMode === AGENCY_MODE.LEGACY) return { status: 'legacy', mode: currentMode, calls: 0 };
  const owner = { accountId: Number(accountId), companionId: Number(companionId) };
  if (!Number.isInteger(owner.accountId) || owner.accountId <= 0 || !Number.isInteger(owner.companionId) || owner.companionId <= 0) {
    return { status: 'inconclusive', mode: currentMode, calls: 0, error: 'invalid_owner' };
  }
  let promptBinding;
  try { promptBinding = getAgencyPromptBinding(); }
  catch (error) {
    return { status: 'inconclusive', mode: currentMode, calls: 0, error: String(error.message || error) };
  }
  log('info', `[Agency] prompt=${promptBinding.promptVersion} sha256=${promptBinding.sha256.slice(0, 12)}`);
  const promptRef = `prompt:${promptBinding.promptVersion}:${promptBinding.sha256.slice(0, 16)}`;
  const extract = deps.extractStructuredInfoDetailed || extractStructuredInfoDetailed;
  const now = deps.now ? new Date(deps.now) : new Date();
  let runtimeLease = null;
  if (runtimeGuard) {
    const leaseToken = deps.leaseToken || undefined;
    runtimeLease = acquireAgencyLease({ ...owner, now: now.getTime(), token: leaseToken });
    if (!runtimeLease) return { status: 'busy', mode: currentMode, calls: 0, error: 'agency_lease_unavailable' };
  }
  try {
  // 无回应只做“观测+延后重评”，不自动解释成拒绝，也不把动念 abandon。
  try {
    const overdue = listAgencyActions({ ...owner, states: ['delivered'], limit: 20 })
      .filter(action => action.expiresAt && new Date(action.expiresAt).getTime() <= now.getTime());
    for (const action of overdue) {
      const intention = getAgencyIntention(action.intentionId, owner);
      if (!intention) continue;
      const observed = recordAgencyFeedback({ ...owner, intentionId: intention.id, actionId: action.id, sourceMessageId: `action:${action.id}:no-response`, kind: 'no_response_observed', rawRef: action.id, interpretation: '动作已到期但尚未收到用户回应；保留等待，不视为拒绝。', confidence: 1 });
      if (observed) updateAgencyIntention(intention.id, { ...owner, expectedVersion: intention.version, state: 'waiting_user', reconsiderAfter: new Date(now.getTime() + 30 * 60_000).toISOString(), lastFeedbackAt: now.toISOString() });
    }
  } catch (error) {
    log('warn', `[Agency] 无回应观测失败 companion=${owner.companionId}: ${error.message}`);
  }
  const currentIntentions = snapshot.activeIntentions || listAgencyIntentions({ ...owner, states: ['candidate', 'preparing', 'ready', 'waiting_user', 'active'], limit: 8 });
  const currentFeedback = snapshot.recentFeedback || listAgencyFeedback({ ...owner, limit: 12 });
  const responsibilities = [
    ...(Array.isArray(snapshot.responsibilities) ? snapshot.responsibilities : []),
    ...(decision?.enterpriseEvent ? [{ kind: 'enterprise_event', id: decision.enterpriseEvent.id || null, taskType: decision.enterpriseEvent.taskType || '', due: true, statement: decision.enterpriseEvent.statement || '' }] : []),
    ...(trigger === 'reminder' ? [{ kind: 'relationship_reminder', due: true }] : []),
  ];
  const context = normalizeContextSnapshot({
    ...snapshot, now: now.toISOString(), trigger, companion, currentDecision: decision,
    activeIntentions: currentIntentions.slice(0, 6),
    concernCatalog: currentIntentions.slice(6).map(item => ({ id: item.id, domain: item.domain, state: item.state, desiredChange: item.desiredChange, reconsiderAfter: item.reconsiderAfter })),
    responsibilities, recentFeedback: currentFeedback,
  });
  if (runtimeLease) {
    const effectiveSourceVersion = String(sourceVersion || snapshot.sourceVersion || snapshot.version || JSON.stringify({ trigger, evidence: snapshot.evidence || [], businessContext: snapshot.businessContext || null }));
    const cognitionStarted = beginAgencyCognition({
      ...owner,
      token: runtimeLease.lease_token,
      fencing: Number(runtimeLease.fencing),
      sourceVersion: effectiveSourceVersion,
      now: now.getTime(),
      reconsiderAfter: currentIntentions[0]?.reconsiderAfter || null,
    });
    if (!cognitionStarted) return { status: 'cooldown', mode: currentMode, calls: 0, error: 'agency_cognition_not_due' };
  }
  const appraisalBudget = reserveAgencyBudget({ ...owner, purpose: 'appraise', inputTokens: 10000, outputTokens: 800, attempts: 2, now: now.getTime() });
  if (!appraisalBudget) return { status: 'blocked', mode: currentMode, calls: 0, error: 'agency_budget_exhausted' };
  const detailedAppraisal = await extract(buildAgencyAppraisalPrompt(context), JSON.stringify(context), {
    accountId: owner.accountId, companionId: owner.companionId, maxTokens: 500, temperature: 0.1, retryLimit: 1,
  });
  settleAgencyBudget({ ...owner, id: appraisalBudget.id, usage: detailedAppraisal?.usage || null });
  const calls = 1;
  if (!detailedAppraisal?.ok || detailedAppraisal.fallback) {
    log('warn', `[Agency] appraisal 未获得真实结构化结果 companion=${owner.companionId} error=${detailedAppraisal?.error || 'unknown'}`);
    return { status: 'inconclusive', mode: currentMode, calls, latencyMs: Date.now() - startedAt, appraisalMeta: detailedAppraisal || null, error: 'appraisal_provider_failure' };
  }
  const parsedAppraisal = parseStructuredJson(detailedAppraisal.text);
  const appraisalValidation = validateAppraisalProposal(parsedAppraisal.value);
  const appraisal = appraisalValidation.ok ? applyOpportunityFloor(appraisalValidation.value, context) : null;
  if (!appraisal) {
    log('warn', `[Agency] appraisal schema 无效 companion=${owner.companionId}`);
    return { status: 'inconclusive', mode: currentMode, calls, latencyMs: Date.now() - startedAt, appraisalMeta: detailedAppraisal, error: parsedAppraisal.error || 'appraisal_schema_invalid' };
  }
  const features = decisionFeatures({ decision, appraisal, activeIntention: currentIntentions[0], now });
  if (!appraisal.shouldAct) {
    return { status: 'no_opportunity', mode: currentMode, calls, features, appraisal, appraisalMeta: detailedAppraisal, latencyMs: Date.now() - startedAt };
  }
  const semanticKey = buildAgencyContinuityKey(appraisal, decision || {});
  const businessTaskRef = decision?.enterpriseEvent?.id || decision?.sourceRefs?.[0] || null;
  let intention = businessTaskRef
    ? currentIntentions.find(item => item.linkedBusinessTaskRef === businessTaskRef) || null
    : null;
  intention ||= findAgencyIntentionBySemanticKey({ ...owner, semanticKey });
  if (!intention) {
    intention = createAgencyIntention({
      ...owner,
      desireVersion: 'desire-v1',
      domain: appraisal.domain,
      desiredChange: appraisal.desiredChange,
      appraisalSummary: appraisal.appraisalSummary,
      basisRefs: mergeAgencyEvidenceRefs(appraisal.basisRefs, [promptRef]),
      semanticKey,
      state: 'preparing',
      priorityClass: appraisal.priorityClass,
      reconsiderAfter: new Date(now.getTime() + appraisal.reconsiderAfterMinutes * 60_000).toISOString(),
      linkedBusinessTaskRef: businessTaskRef,
    });
  } else if (intention.state !== 'preparing') {
    const reprised = updateAgencyIntention(intention.id, { ...owner, expectedVersion: intention.version, state: 'preparing', appraisalSummary: appraisal.appraisalSummary, basisRefs: mergeAgencyEvidenceRefs(intention.basisRefs, [...appraisal.basisRefs, promptRef]), priorityClass: appraisal.priorityClass });
    if (!reprised) return { status: 'inconclusive', mode: currentMode, calls, features, appraisal, error: 'intention_cas_conflict' };
    intention = reprised;
  }
  if (!intention) return { status: 'inconclusive', mode: currentMode, calls, features, appraisal, error: 'intention_persist_failed' };
  recordAgencyConcernEvent({ ...owner, intentionId: intention.id, eventKind: 'appraised', sourceRefs: appraisal.basisRefs, payload: { trigger, shouldAct: appraisal.shouldAct, domain: appraisal.domain, desiredChange: appraisal.desiredChange, responsibilityCount: responsibilities.length }, expectedVersion: intention.version });

  const planContext = { ...context, currentDecision: decision, activeIntentions: [intention] };
  const planBudget = reserveAgencyBudget({ ...owner, purpose: 'plan', inputTokens: 8000, outputTokens: 900, attempts: 2, now: now.getTime() });
  if (!planBudget) {
    updateAgencyIntention(intention.id, { ...owner, expectedVersion: intention.version, state: 'suspended', resumeEvidence: [{ reason: 'budget_exhausted' }] });
    return { status: 'blocked', mode: currentMode, calls, intention, error: 'agency_budget_exhausted' };
  }
  const detailedPlan = await extract(buildAgencyPlanPrompt(planContext, appraisal), JSON.stringify({ context: planContext, appraisal }), {
    accountId: owner.accountId, companionId: owner.companionId, maxTokens: 600, temperature: 0.1, retryLimit: 1,
  });
  settleAgencyBudget({ ...owner, id: planBudget.id, usage: detailedPlan?.usage || null });
  let totalCalls = calls + 1;
  if (!detailedPlan?.ok || detailedPlan.fallback) {
    updateAgencyIntention(intention.id, { ...owner, expectedVersion: intention.version, state: 'suspended' });
    return { status: 'inconclusive', mode: currentMode, calls: totalCalls, latencyMs: Date.now() - startedAt, features, appraisal, intention, planMeta: detailedPlan || null, error: 'plan_provider_failure' };
  }
  const parsedPlan = parseStructuredJson(detailedPlan.text);
  const planValidation = validatePlanProposal(parsedPlan.value, { capabilities: context.capabilities });
  if (!planValidation.ok) {
    updateAgencyIntention(intention.id, { ...owner, expectedVersion: intention.version, state: 'suspended' });
    return { status: 'inconclusive', mode: currentMode, calls: totalCalls, latencyMs: Date.now() - startedAt, features, appraisal, intention, error: planValidation.reason };
  }
  let plan = applyPlanPolicy(planValidation.value, { snapshot: planContext, appraisal });
  let action = createAgencyAction({
    intentionId: intention.id,
    ...owner,
    ...plan,
    state: 'planned',
    notBefore: new Date(now.getTime() + plan.notBeforeMinutes * 60_000).toISOString(),
    expiresAt: new Date(now.getTime() + plan.expiresAfterMinutes * 60_000).toISOString(),
  });
  if (!action) {
    updateAgencyIntention(intention.id, { ...owner, expectedVersion: intention.version, state: 'suspended', resumeEvidence: [{ reason: 'action_persist_failed' }] });
    return { status: 'inconclusive', mode: currentMode, calls: totalCalls, latencyMs: Date.now() - startedAt, features, appraisal, intention, plan, error: 'action_persist_failed' };
  }
  recordAgencyConcernEvent({ ...owner, intentionId: intention.id, actionId: action.id, eventKind: 'planned', sourceRefs: plan.inputRefs, payload: { actionType: plan.actionType, shouldContact: plan.shouldContact, strategySummary: plan.strategySummary }, expectedVersion: intention.version });
  // 准备类动作必须真正执行，不能留下 planned 伪结果。contact_* 由下方
  // 原发送器接管；其余动作统一走可注入适配器并留下结果/故障回执。
  if (action && ['lookup', 'analyze', 'research', 'prepare_media', 'wait'].includes(action.actionType)) {
    const running = updateAgencyAction(action.id, { ...owner, expectedVersion: action.version, state: 'running' });
    if (!running) {
      updateAgencyIntention(intention.id, { ...owner, expectedVersion: intention.version, state: 'suspended', resumeEvidence: [{ reason: 'action_running_cas_conflict' }] });
      return { status: 'inconclusive', mode: currentMode, calls: totalCalls, latencyMs: Date.now() - startedAt, features, appraisal, intention, plan, action, error: 'action_running_cas_conflict' };
    }
    action = running;
    let execution;
    try {
      const adapter = action.actionType === 'lookup'
        ? deps.executeLookup || deps.enterpriseAdapter?.retrieve || executeDefaultAgencyLookup
        : action.actionType === 'analyze'
          ? deps.executeAnalyze || deps.analysisAdapter?.analyze
            : action.actionType === 'research'
              ? deps.executeResearch || deps.researchAdapter?.research || executeDefaultAgencyResearch
            : action.actionType === 'prepare_media'
              ? deps.executePrepareMedia || deps.prepareMedia || deps.mediaAdapter?.prepare
              : null;
      execution = action.actionType === 'wait'
        ? { status: 'complete', resultRefs: [{ kind: 'wait', status: 'complete' }] }
        : typeof adapter === 'function'
          ? await adapter({ action, intention, decision, snapshot: planContext, owner })
          : { status: 'unavailable', cause: `${action.actionType}_adapter_not_supplied` };
    } catch (error) {
      execution = { status: 'unavailable', cause: 'adapter_exception', error: String(error.message || error).slice(0, 200) };
    }
    const normalizedStatus = String(execution?.status || '').toLowerCase();
    const prepared = ['complete', 'completed', 'partial', 'prepared', 'success', 'ok'].includes(normalizedStatus);
    const refs = Array.isArray(execution?.resultRefs) && execution.resultRefs.length
      ? execution.resultRefs.slice(0, 20)
      : [{
        kind: action.actionType,
        status: execution?.status || 'unavailable',
        sourceRefs: Array.isArray(execution?.sourceRefs) ? execution.sourceRefs.slice(0, 20) : [],
        traceId: execution?.traceId || null,
        cause: execution?.cause || null,
        error: execution?.error || null,
      }];
    const nextActionState = prepared ? 'prepared' : 'failed';
    const updatedAction = updateAgencyAction(action.id, {
      ...owner,
      // running 更新会使版本 +1；此处使用当前 action.version，不能再次 +1。
      expectedVersion: action.version,
      state: nextActionState,
      resultRefs: refs,
      retryEvidence: prepared ? null : { traceId: execution?.traceId || null, cause: execution?.cause || 'adapter_failure' },
    });
    if (!updatedAction) {
      return { status: 'inconclusive', mode: currentMode, calls: totalCalls, latencyMs: Date.now() - startedAt, features, appraisal, intention, plan, action, error: 'action_result_cas_conflict' };
    }
    action = updatedAction;
    if (!prepared) {
      const suspended = updateAgencyIntention(intention.id, { ...owner, expectedVersion: intention.version, state: 'suspended', resumeEvidence: [{ reason: `${action.actionType}_failed`, refs }] });
      return { status: 'infra_failure', mode: currentMode, calls: totalCalls, latencyMs: Date.now() - startedAt, features, appraisal, intention: suspended || intention, plan, action, error: execution?.cause || `${action.actionType}_failed` };
    }
    const persistedEvidence = compactAgencyResultRefs(refs, { actionType: action.actionType });
    const evidenceUpdated = updateAgencyIntention(intention.id, {
      ...owner,
      expectedVersion: intention.version,
      basisRefs: mergeAgencyEvidenceRefs(intention.basisRefs, persistedEvidence),
      appraisalSummary: [intention.appraisalSummary, `已完成 ${action.actionType}，工具证据已写回。`].filter(Boolean).join(' ').slice(0, 2000),
    });
    if (!evidenceUpdated) {
      return { status: 'inconclusive', mode: currentMode, calls: totalCalls, latencyMs: Date.now() - startedAt, features, appraisal, intention, plan, action, error: 'intention_evidence_cas_conflict' };
    }
    intention = evidenceUpdated;
    recordAgencyConcernEvent({ ...owner, intentionId: intention.id, actionId: action.id, eventKind: 'tool_result', sourceRefs: persistedEvidence, payload: { actionType: action.actionType, status: execution?.status || 'complete', resultCount: refs.length }, expectedVersion: intention.version });

    if (action.actionType !== 'wait') {
      const toolAction = action;
      const continuationBudget = reserveAgencyBudget({ ...owner, purpose: 'continue', inputTokens: 7000, outputTokens: 900, attempts: 1, now: now.getTime() });
      if (!continuationBudget) return { status: 'blocked', mode: currentMode, calls: totalCalls, intention, plan, action, error: 'agency_budget_exhausted' };
      const detailedContinuation = await extract(
        buildAgencyContinuationPrompt({ ...planContext, activeIntentions: [intention], evidence: mergeAgencyEvidenceRefs(planContext.evidence, persistedEvidence) }, appraisal, { action: toolAction, execution: refs }),
        JSON.stringify({ appraisal, toolAction, toolResult: refs }),
        { accountId: owner.accountId, companionId: owner.companionId, maxTokens: 600, temperature: 0.1, retryLimit: 0 },
      );
      settleAgencyBudget({ ...owner, id: continuationBudget.id, usage: detailedContinuation?.usage || null });
      totalCalls += 1;
      if (!detailedContinuation?.ok || detailedContinuation.fallback) return { status: 'inconclusive', mode: currentMode, calls: totalCalls, intention, plan, action, error: 'continuation_provider_failure' };
      const parsedContinuation = parseStructuredJson(detailedContinuation.text);
      const continuationValidation = validatePlanProposal(parsedContinuation.value, { capabilities: context.capabilities });
      if (!continuationValidation.ok || !['contact_text', 'contact_media', 'wait'].includes(continuationValidation.value.actionType)) {
        return { status: 'inconclusive', mode: currentMode, calls: totalCalls, intention, plan, action, error: continuationValidation.reason || 'continuation_action_invalid' };
      }
      plan = applyPlanPolicy(continuationValidation.value, { snapshot: { ...planContext, evidence: persistedEvidence }, appraisal });
      if (plan.actionType === 'wait') {
        const ready = updateAgencyIntention(intention.id, { ...owner, expectedVersion: intention.version, state: 'ready', reconsiderAfter: new Date(now.getTime() + plan.notBeforeMinutes * 60_000).toISOString() });
        return { status: 'prepared', mode: currentMode, calls: totalCalls, features, appraisal, intention: ready || intention, plan, action: toolAction, promptBinding };
      }
      const contactAction = createAgencyAction({ intentionId: intention.id, ...owner, ...plan, dedupKey: `${plan.dedupKey}:after:${toolAction.id}`, state: 'planned', notBefore: new Date(now.getTime() + plan.notBeforeMinutes * 60_000).toISOString(), expiresAt: new Date(now.getTime() + plan.expiresAfterMinutes * 60_000).toISOString() });
      if (!contactAction) return { status: 'inconclusive', mode: currentMode, calls: totalCalls, intention, plan, action: toolAction, error: 'continuation_action_persist_failed' };
      action = contactAction;
      recordAgencyConcernEvent({ ...owner, intentionId: intention.id, actionId: action.id, eventKind: 'continued_after_tool', sourceRefs: persistedEvidence, payload: { fromActionId: toolAction.id, actionType: action.actionType, strategySummary: plan.strategySummary }, expectedVersion: intention.version });
    }
  }
  // waiting_user 只能在动作真实送达且需要用户回应后由 receipt 事务进入；
  // 当前这里只把动念推进到 ready，避免“计划存在”冒充“已送达”。
  const updatedIntention = updateAgencyIntention(intention.id, { ...owner, expectedVersion: intention.version, state: 'ready' });
  if (!updatedIntention) {
    return { status: 'inconclusive', mode: currentMode, calls: totalCalls, latencyMs: Date.now() - startedAt, features, appraisal, intention, plan, action, error: 'intention_cas_conflict' };
  }
  if (plan.shouldContact && allowContact && currentMode === AGENCY_MODE.ENABLED && typeof deps.executeContactAction === 'function') {
    await deps.executeContactAction({ action, intention: updatedIntention, decision, companion, accountId: owner.accountId });
  }
  return { status: plan.shouldContact && allowContact && currentMode === AGENCY_MODE.ENABLED ? 'contact_ready' : 'prepared', mode: currentMode, calls: totalCalls, latencyMs: Date.now() - startedAt, features, appraisal, intention: updatedIntention, plan, action, appraisalMeta: detailedAppraisal, planMeta: detailedPlan, promptBinding };
  } finally {
    if (runtimeLease) {
      try { releaseAgencyLease({ ...owner, token: runtimeLease.lease_token, fencing: Number(runtimeLease.fencing) }); }
      catch (error) { log('warn', `[Agency] lease release 失败 companion=${owner.companionId}: ${error.message}`); }
    }
  }
}
export function shouldSendWindowLastCall(companion, now = new Date()) {
  if (!companion?.last_user_reply_at) return false;           // 从没聊过，没有窗口可关
  const ts = new Date(String(companion.last_user_reply_at).replace(' ', 'T')).getTime();
  if (!Number.isFinite(ts)) return false;
  const idleH = (now.getTime() - ts) / 3_600_000;
  if (idleH < LASTCALL_MIN_H || idleH > LASTCALL_MAX_H) return false;  // 不在"窗口将关"区间
  // 本离开周期是否已发过（last_lastcall_at 秒 > last_user_reply_at 秒 → 已发，不重复）
  const lastUserSec = Math.floor(ts / 1000);
  const lastCallSec = Number(companion.last_lastcall_at) || 0;
  return lastCallSec <= lastUserSec;
}

export function startProactiveScheduler() {
  log('info', '[Proactive] 主动消息调度启动');
  tick().catch(err => log('error', `[Proactive] tick 异常: ${err.message}`));
  return setInterval(() => {
    tick().catch(err => log('error', `[Proactive] tick 异常: ${err.message}`));
  }, TICK_MS);
}

// 经营供给与具体联系时段解耦：同一个 canonical tick 先准备工作台事件，
// 后面的普通/早间时段只负责择机投递，不再等陪伴动机放行后才发现业务问题。
async function primeEnterpriseCandidates(account, companion, minuteNow) {
  if (!enterpriseProactiveEnabled()) return null;
  try {
    const actorId = account.account_id || companion.user_id;
    const policy = getEnterpriseProactivePolicy(actorId, companion.id);
    const purposes = enterprisePurposesDue(policy, minuteNow);
    if (!purposes.length) return { actorId, policy, purposes, events: [] };
    const events = await pullEnterpriseEvents({ accountId: actorId, limit: 3, purposes, policy, refresh: true });
    if (!events.refreshFailed && !events.readFailed && !events.discoveryPending) {
      for (const purpose of purposes) {
        const activityPurpose = purpose === 'daily_report' ? 'report' : purpose === 'order_table_monitor' ? 'order_monitor' : 'knowledge';
        markEnterpriseProactiveActivity(actorId, companion.id, activityPurpose, 'check');
      }
    } else if (events.refreshFailed || events.readFailed) {
      log('warn', `[Proactive] 经营事件未完成检查，保留下次重试 companion=${companion.id} purposes=${purposes.join(',')} error=${events.refreshError || 'unknown'}`);
    }
    if (events.length) {
      log('info', `[Proactive] 经营候选已准备 companion=${companion.id} types=${events.map(item => item.taskType).join(',')}`);
    }
    return { actorId, policy, purposes, events };
  } catch (error) {
    log('warn', `[Proactive] 经营候选准备异常，继续走普通主动链 companion=${companion.id}: ${error.message}`);
    return { actorId: account.account_id || companion.user_id, policy: {}, purposes: [], events: [], refreshFailed: true, refreshError: String(error.message || error) };
  }
}

async function tick(now = new Date()) {
  const dateKey = formatDateKey(now);
  const minuteNow = currentMinute(now);
  const isWeekendDay = isWeekend(now);
  const defaultStart = isWeekendDay ? WEEKEND_START_MINUTE : WEEKDAY_START_MINUTE;

  const accounts = getActiveBotAccounts();
  for (const account of accounts) {
    const companions = listProactiveCompanionsForBot(account.bot_id);
    for (const companion of companions) {
      // v1.5.2 B2 修：把每个 companion 的本 tick 处理包在 try 里，一个失败不连累其它
      try {
        // 用户自定义时间窗口（companion.proactive_time_window，格式 "07:30-24:00"），fallback 到默认
        const window = parseTimeWindow(companion.proactive_time_window) || { start: defaultStart, end: LAST_MINUTE };
        if (minuteNow < window.start) continue;
        if (minuteNow > window.end) continue;

        const enterpriseSupply = await primeEnterpriseCandidates(account, companion, minuteNow);

        // 自愈：若 DB 里没有今天的日程（cron 失败或刚绑定），按需触发一次生成
        // ensureScheduleForCompanion 内置 30 分钟级 debounce 防止持续失败时反复重试
        if (!getDailySchedule(companion.id, dateKey)) {
          ensureScheduleForCompanion(companion.id, dateKey).catch(err =>
            log('warn', `[Proactive] ensureSchedule 异常 companion=${companion.id}: ${err.message}`)
          );
        }
        // ── 纪念日 / 提醒主动推送 ──────────────────────────────────────────────
        // 事件驱动，独立于随机日程，也绕过 v2 抑制：生日/纪念日这种特殊日子该发就发。
        // 发完即标记 last_triggered_at，保证当天只发一次、且不再作为后续消息的上下文重复出现。
        try {
          ensureRelationshipReminders(companion); // 懒初始化关系里程碑（仅一次）
          const dueReminders = getDueReminders(companion.id, dateKey);
          if (dueReminders.length > 0) {
            await sendProactiveMessageGuarded(companion, 'reminder', account, { reminders: dueReminders });
            markRemindersTriggered(companion.id, dueReminders.map(r => r.id), dateKey);
          }
        } catch (e) {
          log('warn', `[Proactive] reminder 推送异常 companion=${companion.id}: ${e.message}`);
        }

        // ── 窗口将关·临门一脚 ──────────────────────────────────────────────
        // 独立于随机日程的事件触发：token 窗口将关前(idle 21-23.5h)发最后一次轻量搭话拉回用户。
        // 走 guarded（安全门 + 硬间隔），每离开周期一次。受白天 window 限制（深夜不打扰）。
        try {
          if (shouldSendWindowLastCall(companion, now)) {
            const r = await sendProactiveMessageGuarded(companion, 'lastcall', account);
            if (r === 'sent') {
              markWindowLastCallSent(companion.id);
              log('info', `[Proactive] ★ 窗口将关·临门一脚 companion=${companion.id}`);
            }
          }
        } catch (e) {
          log('warn', `[Proactive] lastcall 异常 companion=${companion.id}: ${e.message}`);
        }

        // v1.21.5 (PR-B item 3) 照片承诺改期履约：到点的 her_promise → 补拍补发"喏 补给你的"。
        // 把"说了不做"的事故弧收成真人感弧。一 tick 最多补一个；失败留 open 下 tick 重试。
        try {
          const duePromises = listDueHerPromises(companion.id);
          if (duePromises.length) {
            const ctx = getBotContextForCompanion(companion.id);
            if (ctx) await deliverPhotoPromiseMakeup(companion, ctx, duePromises[0]);
          }
        } catch (e) {
          log('warn', `[Proactive] her_promise 补发检查异常 companion=${companion.id}: ${e.message}`);
        }

        const schedule = ensureTodaySchedule(companion.id, dateKey, minuteNow, window.start, window.end, companion);
        // v1.10.0 #BUG-FIX：原来不加 _v2_deny_until 字段时，v2 评估失败 + item.sent=true 顺序错位
        // 让大量 items 在 motivation 还没积累起来时就被永久标记 sent。配额白白浪费，用户感知
        // "主动消息明显比设置的少"。改法：
        //   1) v2 拒绝时 *不* 标记 sent=true，但写 _v2_deny_until=now+15min 防抖；
        //   2) 真正发送（含 wrapper silent return）才标记 sent；
        //   3) 加结构化 reason log 便于排查。
        const dueItems = schedule.items.filter(item =>
          !item.sent
          && item.minute <= minuteNow
          && (!item._v2_deny_until || Date.now() >= item._v2_deny_until)
        );
        for (const item of dueItems) {
          if (currentMinute(new Date()) > window.end) break;
          // 重启或长时间停机后，不追发早已错过的普通时段。旧实现会在下午补发中午的“随机搭话”。
          // 过期项明确作废并持久化，避免下一 tick 再次尝试；事件提醒/睡眠兜底走独立分支。
          if (minuteNow - item.minute > PROACTIVE_SLOT_GRACE_MINUTES) {
            item.sent = true;
            // 2026-09-17：区分「时段已消耗」与「消息真送达」。作废必须写明 deliveryOutcome，
            // 否则数据库里只剩 sent:true，看起来像"发过了"，掩盖了整天的真实空转。
            item.deliveryOutcome = 'expired';
            item.deliveryAt = new Date().toISOString();
            persistRuntimeSchedule(companion.id, schedule);
            log('info', `[Proactive] 过期时段作废 companion=${companion.id} kind=${item.kind} scheduled=${item.minute} now=${minuteNow} grace=${PROACTIVE_SLOT_GRACE_MINUTES}`);
            bumpProactiveHealth('restrained', { companionId: companion.id, reason: 'stale_slot' });
            continue;
          }

          const actorId = account.account_id || companion.user_id;
          let event = null;
          if (['normal', 'morning'].includes(item.kind)) {
            // Local inbound work survives restarts and gets first use of the next
            // compliant delivery opportunity. Weekly workbench events remain the
            // fallback; they cannot hide an already-authorized user task.
            event = getPendingInboundEnterpriseEvent({ accountId: actorId, companionId: companion.id });
          }
          if (!event && ['normal', 'morning'].includes(item.kind) && enterpriseProactiveEnabled()) {
            const allowedPurposes = item.kind === 'morning' ? ['daily_report'] : ['daily_report', 'knowledge_acquisition', 'order_table_monitor'];
            event = enterpriseSupply?.events?.find(candidate => allowedPurposes.includes(candidate.taskType === 'knowledge_gap_followup' ? 'knowledge_acquisition' : candidate.taskType)) || null;
            if (!event) {
              // 事件可能在此前的 tick 已准备好；读取待投递队列时不再次触发刷新。
              const policy = enterpriseSupply?.policy || getEnterpriseProactivePolicy(actorId, companion.id);
              const pending = await pullEnterpriseEvents({ accountId: actorId, limit: 1, purposes: allowedPurposes, policy, refresh: false });
              event = pending.find(candidate => allowedPurposes.includes(candidate.taskType === 'knowledge_gap_followup' ? 'knowledge_acquisition' : candidate.taskType)) || null;
            }
          }

          // v2 mode: 业务事件必须先进入时机判断，不能被旧的陪伴动机提前挡掉。
          let timingDecision = null;
          if (PROACTIVE_ENGINE_MODE === 'v2') {
            let v2Error = false;
            try {
              timingDecision = evaluateProactive(companion, { enterpriseEvent: event });
            } catch (e) {
              log('warn', `[Proactive] evaluateProactive 异常，fallback legacy: ${e.message}`);
              v2Error = true;
              bumpProactiveHealth('errored', { companionId: companion.id, reason: 'v2_throw' });
            }
            // v2 主动拒发（非异常）→ defer 15min 重试，不丢配额
            if (!v2Error && timingDecision === null) {
              item._v2_deny_until = Date.now() + 15 * 60_000;
              persistRuntimeSchedule(companion.id, schedule);
              log('info', `[Proactive] v2 拒发，延期 15 分钟重试 companion=${companion.id} kind=${item.kind} minute=${item.minute}`);
              bumpProactiveHealth('restrained', { companionId: companion.id, reason: 'v2_deny' });
              continue;
            }
          }

          // v1.10.1 fix: guarded 返回投递状态。节流类（inflight/throttled/safety）不消耗配额，
          // 改 defer 重试，避免实发条数 < target；只有真正发送 / 内部尝试过才标 sent。
          // 经营资料只占用原有 normal 主动机会，不绕过不回复降频、睡眠和日配额。
          const result = await sendProactiveMessageGuarded(companion, item.kind, account, { enterpriseEvent: event, timingDecision });
          if (result === 'sent' && event) {
            if (event.origin === 'inbound') {
              completeActiveEnterpriseTask({ accountId: actorId, companionId: companion.id, taskId: event.id });
            } else {
              await acknowledgeEnterpriseEvent(event.id, { status: 'delivered', deliveryNote: `companion:${companion.id}` });
              const activityPurpose = event.taskType === 'daily_report' ? 'report' : event.taskType === 'order_table_monitor' ? 'order_monitor' : 'knowledge';
              markEnterpriseProactiveActivity(actorId, companion.id, activityPurpose, 'sent');
              markEnterpriseProactiveActivity(actorId, companion.id, activityPurpose, 'check');
              if (event.question) rememberActiveEnterpriseTask({ accountId: actorId, companionId: companion.id, event });
            }
          }
          if (result === 'throttled' || result === 'inflight') {
            item._v2_deny_until = Date.now() + 10 * 60_000;   // 10 分钟后重试
            item.deliveryOutcome = result === 'throttled' ? 'throttled' : 'inflight';
            bumpProactiveHealth('restrained', { companionId: companion.id, reason: result });
          } else if (result === 'safety') {
            item._v2_deny_until = Date.now() + 60 * 60_000;   // 安全门，1 小时后再评估
            item.deliveryOutcome = 'safety_blocked';
            bumpProactiveHealth('restrained', { companionId: companion.id, reason: 'safety' });
          } else if (result === 'arc_skip') {
            item._v2_deny_until = Date.now() + 90 * 60_000;   // v1.21 冷战降频，1.5 小时后再评估
            item.deliveryOutcome = 'arc_skipped';
            bumpProactiveHealth('restrained', { companionId: companion.id, reason: 'arc_skip' });
          } else if (result === 'precheck_skip') {
            // 2026-09-17：同一动念上次已被出站门拦下、指纹未变 → 生成前就跳过。
            // 这不是"投递失败"，不该计入 not_delivered 告警；时段照常消耗避免同 tick 反复重试。
            item.sent = true;
            item.deliveryOutcome = 'precheck_skip';
            item.deliveryAt = new Date().toISOString();
          } else if (result === 'sent') {
            // 只有真实送达才记 delivered——这是「她今天到底说没说话」的唯一可信依据。
            item.sent = true;
            item.deliveryOutcome = 'delivered';
            item.deliveryAt = new Date().toISOString();
          } else {
            // 2026-09-17 修（原为「'sent' 或内部早退都算今日已尝试」并直接 item.sent = true）：
            // 内部早退（撞车/'not_sent'/无 ctx 等）**并没有送达**。旧写法把它们一并标成
            // sent:true，导致 9-15、9-16 排程显示 13 条全部"已发"，而 wechat_messages
            // 里零条出站——状态撒谎，掩盖了整条链路的失败，也无从告警。
            // 现在：时段照常消耗（避免同一 tick 反复重试白烧 token），但如实记为 failed，
            // 并累计到健康计数，让「连续多日一条没发出去」变得可见。
            item.sent = true;
            item.deliveryOutcome = 'failed';
            item.deliveryAt = new Date().toISOString();
            item.deliveryError = String(result || 'unknown');
            bumpProactiveHealth('restrained', { companionId: companion.id, reason: `not_delivered:${result || 'unknown'}` });
            log('warn', `[Proactive] 未送达 companion=${companion.id} kind=${item.kind} reason=${result || 'unknown'}（时段已消耗，如实记为 failed）`);
          }
          persistRuntimeSchedule(companion.id, schedule);
        }
      } catch (e) {
        // v1.5.2 B2 兜底：任何一个 companion 的本 tick 异常都不能中断后面的处理
        log('error', `[Proactive] companion=${companion.id} 本 tick 异常，跳过: ${e.message}`);
        bumpProactiveHealth('errored', { companionId: companion.id, reason: 'tick_catch' });
      }
    }
  }
  recordTickHeartbeat();   // #263 误报修：每 tick 末写心跳——证明调度线程活着（deadman 判 tick 死据此）
}

// v1.5.2: 三道闸门的 sendProactiveMessage wrapper —
//   1. 进程内 in-flight 锁（防同 companion 并发 race，B3）
//   2. 持久化 last_proactive_sent_at 25 分钟硬间隔（防重启重发，B1）
//   3. reminder/confession 等"特殊事件"放宽到 5 分钟（不能因 normal 节流而错过纪念日祝福）
// v1.19.6 hotfix: 晚安标记的归属日（纯函数，smoke 可回归）。
// 凌晨 <05:00 发出的晚安属于"昨晚"——否则跨午夜发送会吃掉当晚的晚安。
export function goodnightBelongDateKey(now = new Date()) {
  const shHour = (now.getUTCHours() + 8) % 24;
  return shHour < 5
    ? shanghaiDateKey(new Date(now.getTime() - 24 * 3600_000))
    : shanghaiDateKey(now);
}

// v1.19.5: morning 是否该降级为 normal（纯函数，smoke 可确定性回归）。
// 两种"刚醒"穿帮都降级（配额照用，文案不再装刚醒）：
// 1) alreadySent —— 今天早安已发过：服务重启丢内存排程，重算把 morning 又排上
//    （7 点真起床发过"刚醒"，9 点半又来一条"早…刚醒"，重复且和中间互动自相矛盾）
// 2) talkedThisMorning —— 用户今早(上海时间 ≥05:00)已经聊过天：8 点他说"早"她回了，
//    9 点半再发"刚醒"等于穿帮说谎。半夜睡前(<05:00)聊的不算——那种情况早上说刚醒不穿帮。
export function shouldDemoteMorning({ goodmorningSentForDate, todayKey, lastUserReplyAt } = {}) {
  const alreadySent = !!todayKey && goodmorningSentForDate === todayKey;
  let talkedThisMorning = false;
  if (lastUserReplyAt) {
    const raw = String(lastUserReplyAt);
    const ts = new Date(raw.replace(' ', 'T') + (raw.includes('Z') || raw.includes('+') ? '' : 'Z')).getTime();
    if (Number.isFinite(ts)) {
      const shHour = (new Date(ts).getUTCHours() + 8) % 24;
      talkedThisMorning = shanghaiDateKey(new Date(ts)) === todayKey && shHour >= 5;
    }
  }
  return { demote: alreadySent || talkedThisMorning, alreadySent, talkedThisMorning };
}

async function sendProactiveMessageGuarded(companion, kind, account, opts = {}) {
  if (_proactiveInFlight.has(companion.id)) {
    log('info', `[Proactive] 跳过：companion=${companion.id} 已有发送在进行中（kind=${kind}）`);
    return 'inflight';
  }
  // ── v1.19.6 goodnight 防重（第二道闸，排程侧第一道见 ensureTodaySchedule）──
  // 与 morning 不同：晚安重复时直接**跳过**而非降级——她都说过"我要睡了"，
  // 再发条普通消息反而像诈尸。返回非节流状态，tick 会标 item.sent 作废本条配额。
  if (kind === 'goodnight') {
    try {
      if (getSleepRow(companion.id)?.goodnight_sent_for_date === shanghaiDateKey()) {
        log('info', `[Proactive] 今晚晚安已发过 → 跳过重复 goodnight companion=${companion.id}`);
        return 'dup';
      }
    } catch (e) {
      log('warn', `[Proactive] goodnight 防重检查失败（按原 kind 继续）: ${e.message}`);
    }
  }
  // ── v1.19.5 morning 防重 + 防穿帮（第二道闸，排程侧第一道见 ensureTodaySchedule）──
  if (kind === 'morning') {
    try {
      const verdict = shouldDemoteMorning({
        goodmorningSentForDate: getSleepRow(companion.id)?.goodmorning_sent_for_date,
        todayKey: shanghaiDateKey(),
        lastUserReplyAt: companion.last_user_reply_at,
      });
      if (verdict.demote) {
        log('info', `[Proactive] morning 降级 normal companion=${companion.id} alreadySent=${verdict.alreadySent} talkedThisMorning=${verdict.talkedThisMorning}`);
        kind = 'normal';
      }
    } catch (e) {
      log('warn', `[Proactive] morning 防重检查失败（按原 kind 继续）: ${e.message}`);
    }
  }
  // ── v1.9.0 #1: 安全门 ─────────────────────────────────────────────────
  // 用户最近表达自伤/自杀/绝望信号时，不要发普通主动消息（包括纪念日/告白/想念）。
  // "她今天没找我" 远好于 "她在我说不想活了之后发了句突然想你"。
  try {
    const risk = getRecentSafetyRisk(companion.id);
    if (risk.level === 'high' || risk.level === 'medium') {
      log('warn', `[Proactive] 安全门拦截 companion=${companion.id} kind=${kind} risk=${risk.level} signals=${(risk.signals || []).join(',')}`);
      return 'safety';
    }
  } catch (e) {
    // 查询失败不应阻塞 — 但也不静默继续发，保守起见同样跳过本次
    log('warn', `[Proactive] 安全门查询失败 companion=${companion.id}: ${e.message} → 保守跳过本次`);
    return 'safety';
  }
  // ── v1.21 冲突弧门：冷战降频 + 禁撒娇类 kind（docs/CONFLICT_ARC.md §5.4）──
  // hurt ×0.7 / cold ×0.4 / withdrawing ×0.15（与尊严上限同体系，不是新规则）；
  // cold(anxious) 与 repairing 各允许 1 条台阶消息（olive_branch，每事件 1 次）。
  let arcOlive = null;
  try {
    const arcPolicy = getArcProactivePolicy(companion);
    if (arcPolicy.arcState !== 'normal') {
      if (arcPolicy.forbidKinds.includes(kind)) {
        log('info', `[Proactive] arc=${arcPolicy.arcState} 禁 kind=${kind} → 跳过 companion=${companion.id}`);
        return 'arc_skip';
      }
      if (arcPolicy.skip && !arcPolicy.oliveBranch) {
        log('info', `[Proactive] arc=${arcPolicy.arcState} 降频跳过 companion=${companion.id} kind=${kind}`);
        return 'arc_skip';
      }
      if (arcPolicy.oliveBranch) arcOlive = arcPolicy;   // 台阶消息：放行并改写语气
    }
  } catch (e) {
    log('warn', `[Proactive] arc 门查询失败（按 normal 继续）companion=${companion.id}: ${e.message}`);
  }
  if (opts.enterpriseEvent && arcOlive) return 'arc_skip';
  opts = { ...opts, arcOlive };
  // 持久化间隔检查
  const { lastAt } = getProactiveLastSent(companion.id);
  const nowSec = Math.floor(Date.now() / 1000);
  const elapsed = nowSec - (lastAt || 0);
  const hardGap = (kind === 'reminder' || kind === 'confession') ? 5 * 60 : PROACTIVE_HARD_GAP_SECONDS;
  if (lastAt && elapsed < hardGap) {
    log('info', `[Proactive] 跳过：companion=${companion.id} kind=${kind} 距上次 ${elapsed}s < ${hardGap}s 硬间隔`);
    return 'throttled';
  }
  _proactiveInFlight.add(companion.id);
  try {
    const delivered = await sendProactiveMessage(companion, kind, account, opts);
    if (!delivered) return 'not_sent';
    // 成功后记录（sendProactiveMessage 内部失败/早退也无伤大雅，下次仍会按间隔判断）
    recordProactiveSentTimestamp(companion.id, kind);
    bumpProactiveHealth('sent', { companionId: companion.id });   // #263 误报修：已发送桶（所有 kind 的发送汇聚点，与 last_proactive_sent_at 同源）
    clearChannelClosedStreak();   // 2026-09-17：真送达一次 = 窗口是开的，连续关闭计数清零
    clearPrecheckFailure();       // 2026-09-17：生成并投递成功 → 清掉"上次被拦"的记忆

    // v1.10.0 sleep 状态切换 hook
    try {
      const todayKey = shanghaiDateKey();
      if (kind === 'goodnight') {
        // v1.10.6: goodnight 只发"我要睡了 晚安"，不立即 enterSleep。
        // 真正入睡交给 sleep tick 在 today_bed_at 触发，让睡前晚安与入睡之间留挽留窗口
        // （用户说"再陪陪我"可延后）。
        // v1.19.6 hotfix: 跨午夜归属——排 23:59 的晚安经发送延迟滑到凌晨 00:0x 才发出时，
        // 标"今天"会让防重闸把**当晚 23 点的晚安**误判为已发（生产实测 companion=3/7 踩中）。
        // 凌晨 <05:00 发出的晚安归属"昨晚"（与 morning 的 05:00 分界对称）。
        upsertSleepSchedule(companion.id, { goodnight_sent_for_date: goodnightBelongDateKey() });
        log('info', `[Sleep] goodnight sent (enterSleep deferred to bed_at) companion=${companion.id}`);
      } else if (kind === 'morning') {
        exitSleep(companion.id);
        drainMissed(companion.id);
        upsertSleepSchedule(companion.id, { goodmorning_sent_for_date: todayKey, woken_today: 0 });
        log('info', `[Sleep] exitSleep via morning companion=${companion.id}`);
      }
    } catch (e) {
      log('warn', `[Sleep] hook failed companion=${companion.id} kind=${kind}: ${e.message}`);
    }
    return 'sent';
  } finally {
    _proactiveInFlight.delete(companion.id);
  }
}

function parseTimeWindow(spec) {
  if (typeof spec !== 'string' || !spec) return null;
  const m = spec.match(/^(\d{1,2}):(\d{2})\s*[-~–]\s*(\d{1,2}):(\d{2})$/);
  if (!m) return null;
  const sh = Number(m[1]), sm = Number(m[2]), eh = Number(m[3]), em = Number(m[4]);
  if (sh < 0 || sh > 24 || eh < 0 || eh > 24 || sm > 59 || em > 59) return null;
  const start = sh * 60 + sm;
  const end = Math.min(LAST_MINUTE, eh * 60 + em);
  if (end <= start) return null;
  return { start, end };
}

function listProactiveCompanionsForBot(botId) {
  const db = getDb();
  const rows = db.prepare(`
    SELECT c.id, u.wechat_user_id
    FROM companions c
    JOIN users u ON u.id = c.user_id
    JOIN wechat_accounts wa ON wa.companion_id = c.id AND wa.bot_id = c.bot_id
    WHERE c.bot_id = ?
      AND c.proactive_enabled = 1
      AND COALESCE(c.silent_mode, 0) = 0   -- v1.5: 沉默陪伴模式下完全不主动
      AND wa.is_active = 1
      AND wa.wechat_user_id IS NOT NULL
  `).all(botId);
  return rows
    .map(r => ({ ...getCompanionById(r.id), wechat_user_id: r.wechat_user_id }))
    .filter(Boolean);
}

// 检查是否应该安排一次候选照片：默认至少 36 小时，真正是否发送交给 AI planner 再判断。
function shouldSendPhotoToday(companion) {
  if (!companion) return false;
  const last = companion.last_photo_at;
  if (!last) return true;  // 从未发过
  const lastTs = new Date(String(last).replace(' ', 'T') + (String(last).includes('Z') ? '' : 'Z')).getTime();
  const hours = (Date.now() - lastTs) / 3_600_000;
  const minHours = Math.max(36, Number(process.env.PHOTO_PROACTIVE_MIN_HOURS || 36));
  const threshold = minHours + Math.random() * 12;
  return hours >= threshold;
}

// v1.3.4: 移除 isPro 参数；开源版所有 companion 享受相同调度（晚安 + 场景照机会）
function ensureTodaySchedule(companionId, dateKey, minuteNow, startMinute, endMinute = GOODNIGHT_MINUTE, companion = null) {
  const existing = schedules.get(companionId);
  if (existing?.dateKey === dateKey) return existing;

  const rawTarget = Number(companion?.proactive_daily_target);
  const target = Number.isFinite(rawTarget) ? Math.min(30, Math.max(0, Math.floor(rawTarget))) : 10;
  try {
    const persisted = normalizePersistedRuntimeSchedule(getProactiveRuntimeSchedule(companionId, dateKey), companionId, dateKey);
    const sameConfig = persisted
      && Number(persisted.config?.startMinute) === Number(startMinute)
      && Number(persisted.config?.endMinute) === Number(endMinute)
      && Number(persisted.config?.target) === target;
    if (sameConfig) {
      schedules.set(companionId, persisted);
      log('info', `[Proactive] 恢复当日持久排程 companion=${companionId} remaining=${persisted.items.filter(i => !i.sent).length} times=${persisted.items.map(i => `${minuteToHHMM(i.minute)}${i.sent ? '✓' : ''}`).join(',')}`);
      return persisted;
    }
  } catch (e) {
    log('warn', `[Proactive] 当日排程恢复失败 companion=${companionId}: ${e.message}`);
  }

  // v1.10.0 接入 sleep 表：若 enabled，把基准 startMinute / GOODNIGHT_MINUTE 用
  // 用户作息覆盖（学习固化或手动设置）。sleep 表自己做 jitter，proactive 此处不再额外抖。
  let baselineMorning = startMinute;
  let baselineGoodnight = GOODNIGHT_MINUTE;
  let useSleepBase = false;
  try {
    const slpRow = getOrRefreshTodaySchedule(companionId);
    if (slpRow && slpRow.enabled && slpRow.today_bed_at && slpRow.today_wake_at) {
      // 把 today_bed_at / today_wake_at 转换为当天的"分钟数"
      const minOfDay = ts => {
        const d = new Date(ts + 8 * 3600_000);
        return d.getUTCHours() * 60 + d.getUTCMinutes();
      };
      const bedMin  = minOfDay(slpRow.today_bed_at);
      const wakeMin = minOfDay(slpRow.today_wake_at);
      // 把基准设为 sleep 表的值；后续不再叠加 ±30 抖（sleep 已经抖过了）
      baselineMorning   = wakeMin;
      // v1.10.1 fix: bedMin < wakeMin 说明入睡在凌晨（跨午夜，如 01:30 睡 / 09:00 起）。
      // proactive 日程模型只覆盖当天 00:00-23:59，排不到次日凌晨，所以把晚安放到当天最晚
      // （LAST_MINUTE），让她临近午夜说"快睡了"，并保证 buildDailyItems 仍会排晚安 → 能 enterSleep。
      // 旧代码 `bedMin >= 24*60` 是死代码（minOfDay 已 mod 永远 <1440），晚睡用户当天不发晚安。
      baselineGoodnight = bedMin < wakeMin ? LAST_MINUTE : Math.min(LAST_MINUTE, bedMin);
      useSleepBase = true;
    }
  } catch (e) {
    log('warn', `[Proactive] sleep base read failed companion=${companionId}: ${e.message}`);
  }

  // ── sleep 关闭时给早安/晚安一个 ±30min 的随机抖动，避免每天 7:30 / 23:00 太机械 ──
  const morningOffset = useSleepBase ? 0 : jitterOffset(MORNING_JITTER_MIN);
  const goodnightOffset = useSleepBase ? 0 : jitterOffset(GOODNIGHT_JITTER_MIN);
  const jitteredStart = Math.max(0, baselineMorning + morningOffset);
  const jitteredGoodnight = Math.min(LAST_MINUTE, baselineGoodnight + goodnightOffset);
  // window end 跟随晚安抖动（防止 normal 消息延后到晚安之后）
  const jitteredEnd = Math.min(LAST_MINUTE,
    endMinute === GOODNIGHT_MINUTE ? jitteredGoodnight : Math.max(endMinute, jitteredGoodnight));

  // v1.3.3: 用户直接拖动滑块调整每天目标条数（0-30），不再区分 free/pro。
  // 字段 proactive_daily_target INTEGER DEFAULT 10。实际生成数量在
  // [target × 0.8, target × 1.2] 之间随机抖动 ±20%，避免每天数字太机械。
  // target=0 → 完全静默（仅响应用户消息），不发任何主动消息。
  const lo = Math.max(0, Math.floor(target * 0.8));
  const hi = Math.max(lo, Math.ceil(target * 1.2));
  // v1.12.0「她也有自己的日子」：约 1/5 的日子她忙自己的生活、主动消息明显变少，
  // 让她的出现有起伏——来的那天才更像"真的想起了你"，而不是闹钟到点。
  // 按 (companionId + dateKey) 稳定取值，同一天重启不变。
  let _h = 2166136261; const _s = `${companionId}|${dateKey}|busy`;
  for (let i = 0; i < _s.length; i++) { _h ^= _s.charCodeAt(i); _h = Math.imul(_h, 16777619); }
  const busyFactor = (((_h >>> 0) % 1000) / 1000) < 0.2 ? 0.35 : 1.0;
  const baseCount = target === 0 ? 0 : lo + Math.floor(Math.random() * (hi - lo + 1));
  const fullCount = Math.round(baseCount * busyFactor);

  // 关键修复：重启后只从「现在 → 结束」区间挑随机时间，否则前半天的时间点全被标 sent 浪费配额
  // 等比例缩放：若已过去 60%，则今天剩余配额按 40% × fullCount 来挑
  const dayLen = jitteredEnd - jitteredStart;
  const remainLen = Math.max(0, jitteredEnd - Math.max(minuteNow, jitteredStart));
  const remainCount = dayLen > 0
    ? Math.max(remainLen <= 0 ? 0 : 1, Math.round(fullCount * (remainLen / dayLen)))
    : fullCount;

  const effectiveStart = Math.max(jitteredStart, minuteNow + 1);   // +1 避免 tick 同分钟立即触发
  let items = buildDailyItems(remainCount, effectiveStart, jitteredEnd, jitteredGoodnight);

  // v1.19.6: goodnight 防重（与 morning 同款 bug 的对称修复）——今晚晚安已发过
  // （深夜重启丢内存排程后重算又把 goodnight 排上）→ 直接移除，不再"刚说过晚安又来一条"。
  try {
    if (getSleepRow(companionId)?.goodnight_sent_for_date === dateKey) {
      const before = items.length;
      items = items.filter(it => it.kind !== 'goodnight');
      if (items.length < before) log('info', `[Proactive] 今晚晚安已发过 → 移除重算的 goodnight item companion=${companionId}`);
    }
  } catch { /* 读不到按未发处理，发送侧还有第二道闸 */ }

  // v1.10.1 fix: morning kind 只在 sleep enabled 且第一条 normal 落在起床窗口 [wake-15, wake+120] 内时赋予。
  // 旧实现在 buildDailyItems 里无条件抬第一条 normal → 下午重启发"下午的早安"、sleep 关闭也发"刚醒"、
  // 且 morning 发送成功会 exitSleep+drainMissed 误清 missed 队列。
  if (useSleepBase) {
    const wakeMin = baselineMorning;
    const MORNING_WINDOW_MIN = 120;
    // v1.19.5: 今天早安已发过（sleep tick 已发 / 服务重启丢内存排程后重算）→ 不再抬
    // morning。否则 7 点真起床发过"刚醒"，9 点半重算计划的 morning 又来一条"早…刚醒"，
    // 重复且和中间的互动自相矛盾。发送侧另有第二道闸（见 sendProactiveMessageGuarded）。
    let morningAlreadySent = false;
    try {
      morningAlreadySent = getSleepRow(companionId)?.goodmorning_sent_for_date === dateKey;
    } catch { /* 读不到按未发处理，交给发送侧兜底 */ }
    const firstNormal = items.find(it => it.kind === 'normal');
    if (morningAlreadySent) {
      log('info', `[Proactive] 今日早安已发过 → 跳过 morning 抬升 companion=${companionId}`);
    } else if (firstNormal && firstNormal.minute >= wakeMin - 15 && firstNormal.minute <= wakeMin + MORNING_WINDOW_MIN) {
      firstNormal.kind = 'morning';
      log('info', `[Proactive] morning kind companion=${companionId} at ${minuteToHHMM(firstNormal.minute)} (wake≈${minuteToHHMM(wakeMin)})`);
    }
  }

  const schedule = {
    dateKey,
    targetCount: remainCount,
    items,
    config: { startMinute, endMinute, target },
    companionId,
  };
  schedules.set(companionId, schedule);
  persistRuntimeSchedule(companionId, schedule);
  log('info', `[Proactive] 今日计划 companion=${companionId} now=${minuteToHHMM(minuteNow)} morningBase=${minuteToHHMM(startMinute)}->${minuteToHHMM(jitteredStart)} goodnight=${minuteToHHMM(jitteredGoodnight)} count=${remainCount}/full=${fullCount} times=${items.map(i => `${minuteToHHMM(i.minute)}${i.kind === 'goodnight' ? '🌙' : ''}`).join(',')}`);
  return schedule;
}

// v1.3.4: 移除 isPro；所有 companion 在 goodnight 窗口内都会安排晚安
// v1.10.0: 接入 sleep —— 第一条 normal 抬为 'morning' kind，触发起床流程
function buildDailyItems(count, startMinute, endMinute, goodnightMinute = GOODNIGHT_MINUTE) {
  // Free 不发晚安专用消息；Pro 在抖动后的晚安时间发晚安
  const goodnight = (endMinute >= goodnightMinute && goodnightMinute >= startMinute) ? goodnightMinute : null;
  const lastRandom = (goodnight != null ? goodnight - 30 : endMinute);
  const randomCount = Math.max(count - (goodnight != null ? 1 : 0), 0);
  const randomMinutes = pickRandomMinutes(randomCount, startMinute, lastRandom, MIN_GAP_MINUTES);
  const items = randomMinutes.map(minute => ({ minute, kind: 'normal', sent: false }));
  if (goodnight != null) items.push({ minute: goodnight, kind: 'goodnight', sent: false });
  items.sort((a, b) => a.minute - b.minute);
  // v1.10.1 fix: morning kind 的判定移到 ensureTodaySchedule（需要 wake 时刻 + sleep enabled 上下文），
  // 不再在这里无条件把第一条 normal 抬 morning。
  return items;
}

function isWeekend(date) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
    timeZone: TZ, weekday: 'short',
  }).formatToParts(date).filter(p => p.type !== 'literal').map(p => [p.type, p.value]));
  return parts.weekday === 'Sat' || parts.weekday === 'Sun';
}

// v1.12.0「在空隙给温柔」：真人会在一天的"空隙"里看手机/想起人——刚醒、饭点、
// 午后犯困、傍晚、睡前。主动消息锚到这些窗口，而不是全天均匀乱撒。(分钟 of day)
const GAP_WINDOWS = [
  [7 * 60, 9 * 60],            // 早上刚醒
  [11 * 60 + 30, 13 * 60 + 30], // 午饭 / 午休
  [15 * 60, 16 * 60 + 30],      // 午后犯困的空当
  [18 * 60, 19 * 60 + 30],      // 傍晚下班 / 晚饭
  [20 * 60 + 30, 22 * 60 + 30], // 晚上窝着
  [22 * 60 + 30, 23 * 60 + 30], // 睡前
];
function gapWeightedMinute(start, end) {
  const usable = GAP_WINDOWS
    .map(([a, b]) => [Math.max(a, start), Math.min(b, end)])
    .filter(([a, b]) => a <= b);
  if (usable.length === 0) return start + Math.floor(Math.random() * (end - start + 1));
  const [a, b] = usable[Math.floor(Math.random() * usable.length)];
  return a + Math.floor(Math.random() * (b - a + 1));
}

function pickRandomMinutes(count, start, end, minGap) {
  if (count <= 0) return [];

  for (let attempt = 0; attempt < 2000; attempt++) {
    const minutes = [];
    for (let i = 0; i < count; i++) {
      minutes.push(gapWeightedMinute(start, end));   // v1.12.0: 锚到生活空隙，不再全天均匀
    }
    minutes.sort((a, b) => a - b);
    if (hasMinGap(minutes, minGap)) return minutes;
  }

  const slots = [];
  for (let minute = start; minute <= end; minute += minGap) slots.push(minute);
  shuffle(slots);
  return slots.slice(0, count).sort((a, b) => a - b);
}

function hasMinGap(minutes, minGap) {
  for (let i = 1; i < minutes.length; i++) {
    if (minutes[i] - minutes[i - 1] < minGap) return false;
  }
  return minutes.length === 0 || LAST_MINUTE - minutes[minutes.length - 1] >= minGap;
}

async function sendProactiveMessage(companion, kind, account, opts = {}) {
  if (!companion.wechat_user_id) {
    log('warn', `[Proactive] 跳过：companion=${companion.id} kind=${kind} 未绑定微信（wechat_user_id 缺）`);
    return;
  }
  const ctx = account
    ? { token: account.bot_token, botId: account.bot_id }
    : getBotContextForCompanion(companion.id);
  if (!ctx?.token) {
    log('warn', `[Proactive] 找不到 bot context companion=${companion.id}`);
    return;
  }

  // ── context_token 窗口预检（生成前）──────────────────────────────────────
  // 微信主动推送有「会话窗口」：用户最后一次互动起算约 24h 内，机器人才能主动 sendMessage；
  // 超窗口后 iLink 返回 ret=-2 必失败（实测：互动后 +22h 仍成功、+29h 起全失败）。
  // 与其超窗口还生成 LLM 再丢弃（白烧 token + 把没发出的消息污染进上下文），不如提前跳过。
  // 复用 recallContextToken（24h TTL，与实测窗口吻合）：返回 null = 窗口已关，无可用 token。
  // 注：用户一旦回来发消息，token 立即刷新、窗口重开，引擎会按正常间隔重新主动。
  if (!recallContextToken(ctx.botId, companion.wechat_user_id)) {
    // 2026-09-17 新增：把"窗口关着"累计成可观测计数。
    // 背景：9-15 生成了一整批内容却一条都发不出去（排程仍标 sent:true），
    // 9-16/9-17 起预检生效、直接跳过——但**完全静默**，用户两天后才发现她没理人。
    // 这里累计「连续多少次机会因窗口关闭而放弃」，送达后清零；
    // 超过阈值由 warnChannelClosed() 明确告警，不再藏在一行 info 里。
    noteChannelClosedSkip(companion.id, kind);
    log('info', `[Proactive] 跳过：companion=${companion.id} kind=${kind} context_token 窗口已关闭（用户 >24h 未互动，主动消息发不出，不生成内容）`);
    return;
  }

  // 兼容升级前已经持久化的 photo 时段：照片不再是独立栏目，回到普通机会窗参与动念选择。
  if (kind === 'photo') {
    kind = 'normal';
  }

  const userProfile = getUserProfile(companion.user_id, companion.id);
  const timeContext = buildTimeContext(userProfile, getDueReminders(companion.id, formatDateKey()));
  const recentTurns = getConversationContext(companion.id, 10);
  // v1.21.3 素材冷却：N 天内主动消息引用过的记忆不再进候选（看不到就说不出）。
  // reminder（纪念日/节日）豁免——每年说生日快乐不算复读。fail-open：账本读失败=不冷却。
  const _materialUsed = kind === 'reminder'
    ? new Set()
    : getRecentlyUsedMaterialIds(companion.id, { days: materialDedupDays() });
  const _recalledRaw = companion.memory_enabled
    ? recallMemories(companion.id, companion.user_id, timeContext.searchText, 7)
    : [];
  const memories = filterRecentlyUsed(_recalledRaw, _materialUsed);
  const history = getRecentHistory(companion.wechat_user_id, companion.bot_id, 20);
  // v1.3.4: 开源版所有 companion 享受完整长期记忆摘要（不再按 plan 区分）。
  // 素材冷却闸门（接线类第五案，2026-06-13）：digest 旁路也过冷却——传 _materialUsed 剔除
  // 近期已复读的 summary（mem:509 形态：daily_summary 反复出场 4 次/天）。reminder 时
  // _materialUsed 为空 Set=不剔除（与召回路豁免一致）。对话召回路径（bot.mjs）绝不传。
  const longTermDigest = await buildLongTermDigest(companion.id, companion.user_id, { excludeUsedIds: _materialUsed });

  const stickerEnabled = !!companion.sticker_reply_enabled && hasStickers();
  const stickerHint = buildStickerPromptHint(stickerEnabled);
  const proactiveTodayKey = shanghaiDateKey();
  const proactiveDailyRaw = getDailySchedule(companion.id, proactiveTodayKey);
  const proactiveDailySchedule = proactiveDailyRaw ? { ...proactiveDailyRaw, date_key: proactiveTodayKey } : null;
  const proactiveRecent = getRecentSchedules(companion.id, proactiveTodayKey, 3);
  const proactivePersonaFacts = getPersonaFacts(companion.id);
  // v1.4.1: 主动消息也按"想念档"给出 prompt 指令，让她主动找你时的语气有想念感
  const _es = getEmotionStateWithDefaults(companion.id);
  const _ml = getMissingLevel(_es, companion.last_user_reply_at);
  const _ns = getNeglectStage(companion.last_user_reply_at, companion.attachment_style);
  // v1.21 冲突弧：主动消息同样由 arc 主导语气（cold 不能发"突然想你了"）。
  // olive_branch（台阶消息）时用台阶指令替代常规 arc 语气，并消耗配额（每事件 1 条）。
  const _arcExpr = getArcExpressionContext(companion);
  let arcHint = '';
  if (opts.arcOlive?.oliveBranch && opts.arcOlive.oliveEventId) {
    arcHint = buildOliveBranchHint(opts.arcOlive.arcState, _arcExpr.category);
    markOliveBranchSent(opts.arcOlive.oliveEventId);   // 乐观置位：注入即消耗，防重复台阶
    log('info', `[Proactive] olive_branch 台阶消息 companion=${companion.id} arc=${opts.arcOlive.arcState}`);
  } else if (_arcExpr.active) {
    arcHint = _arcExpr.directive;
  }
  // v1.20: 安全模式不拼想念/撒娇类情绪话术；v1.21: arc 激活时想念/冷落档让位
  // v1.22 PR-L3：经期蔫（heavyWindow）+ 经前语气底色（pmsActive）也带进主动消息；safe_mode 整体为 ''。
  let _periodCtx = null;
  try { _periodCtx = getActivePeriodContext(companion); } catch { /* fail-open */ }
  const emotionHint = Number(companion.safe_mode) ? '' : buildEmotionPromptHint(_es, { missingLevel: _ml, neglectStage: _ns, dailySchedule: proactiveDailySchedule, arcActive: _arcExpr.active, bodyLowEnergy: isPeriodHeavyWindow(_periodCtx), pmsActive: isPmsActive(_periodCtx) });
  const proactivePreferences = getCompanionPreferencesForPrompt(companion.id);  // v1.8.0 #3
  // v1.21.4 PR-W2: current_works 注入——她主动找他时也带着"手头的事"的生活背景。
  // worksHint 进 buildSystemPrompt 生活背景带（§8 排序），永在 arcHint 之前。fail-open。
  let proactiveActiveWorks = [];
  try { proactiveActiveWorks = getActiveCurrentWorks(companion.id) || []; }
  catch (e) { log('warn', `[CurrentWorks] proactive 档案读取失败 companion=${companion.id}: ${e.message}`); }
  const worksHint = buildWorksPromptHint(proactiveActiveWorks);
  // ── 检查是否触发"AI 主动表白" ──
  // 条件：normal 时段 + 好感度>=50 + 双方都没表白过 + 认识>=5 天
  let effectiveKind = kind;
  const aff = companion.affection_level || 0;
  // v1.12.1：AI 主动表白只在深夜 22:30 之后——这个点人感情最敏感、最像真人鼓起勇气说出口的时刻
  // v1.20 安全收尾：安全模式（疑似未成年）绝不主动告白
  const _nowMin = ((new Date().getUTCHours() + 8) % 24) * 60 + new Date().getUTCMinutes();
  if (!opts.enterpriseEvent && kind === 'normal'
      && !Number(companion.safe_mode)
      && _arcExpr.arcState === 'normal'      // v1.21: 闹别扭/冷战/修复期绝不主动表白
      && _nowMin >= 22 * 60 + 30
      && !companion.confessed_at
      && !companion.user_confessed_at
      && canAcceptConfession(companion)) {   // 节奏闸门（好感≥55 + 认识≥14天）+ 深夜窗口
    effectiveKind = 'confession';
    log('info', `[Proactive] ★ 触发 AI 主动告白(深夜) companion=${companion.id} affection=${aff} min=${_nowMin}`);
  }

  // v1.8.0 #5: proactive hidden_reason — 把 due open loops 升级为 'recall' kind
  // 真人陪伴最强信任来源：她记得你说过的事，到期主动来问
  let recallLoop = null;
  if (!opts.enterpriseEvent && effectiveKind === 'normal') {
    try {
      const dueLoops = listDueOpenLoops(companion.id, { withinHours: 24 });
      // 选 emotional_weight 最高且最近没主动问过的（防重复）
      // v1.21.3: loop 也是素材——14 天冷却期内主动问过的不再当 recall 由头
      const candidate = dueLoops
        .filter(l => !l.followed_up_at || (Date.now() - new Date(String(l.followed_up_at).replace(' ','T') + 'Z').getTime()) > 6 * 3600_000)
        .filter(l => !_materialUsed.has(loopMaterialId(l.id)))
        .sort((a, b) => (b.emotional_weight || 0) - (a.emotional_weight || 0))[0];
      if (candidate) {
        recallLoop = candidate;
        effectiveKind = 'recall';
        log('info', `[Proactive] ★ 触发 recall companion=${companion.id} loop="${candidate.title}" weight=${candidate.emotional_weight}`);
      }
    } catch (e) {
      log('warn', `[Proactive] recall 检查失败: ${e.message}`);
    }
  }

  // 只有最终仍是 normal 且时机适合分享时，才允许一条高重要度、两小时内的日程事实
  // 成为主动动念的来源。enterprise/recall/confession 等已有更强意图时不让生活背景抢占核心。
  const proactiveLifeEvidence = !opts.enterpriseEvent && effectiveKind === 'normal'
    && ['share_thought', 'schedule_item', 'check_in'].includes(opts.timingDecision?.trigger)
    ? selectProactiveLifeEvidence(proactiveDailySchedule, currentMinute(new Date()))
    : null;
  const verifiedWorkForPhoto = proactiveActiveWorks.find(item => item.verify_status === 'verified' || String(item.kind || '').toLowerCase() === 'craft');
  const photoOpportunity = effectiveKind === 'normal' && shouldSendPhotoToday(companion)
    && (proactiveLifeEvidence || verifiedWorkForPhoto)
    ? {
        id: proactiveLifeEvidence?.id || `work:${verifiedWorkForPhoto.id}`,
        evidenceText: proactiveLifeEvidence?.fact || `正在推进${verifiedWorkForPhoto.title || '手头的一件事'}`,
        reason: proactiveLifeEvidence
          ? '有一条已经发生且仍新鲜的生活事实，可以用画面分享其中的具体小情节'
          : `她正在推进经过核验的事项《${verifiedWorkForPhoto.title || '手头的事'}》，画面可以成为真实进展的一部分`,
        storyValue: proactiveLifeEvidence ? Number(proactiveLifeEvidence.importance || 0) : 6,
      }
    : null;

  // ⚠ 必须是 let：下方 v1.20"事前反复读注入"会 systemPrompt +=。
  let systemPrompt = `${buildSystemPrompt(companion, { memories, userProfile, recentTurns, longTermDigest, promptMode: 'proactive', dailySchedule: proactiveDailySchedule, recentSchedules: proactiveRecent, personaFacts: proactivePersonaFacts, preferences: proactivePreferences, shapingHint: buildShapingPromptHint(listShaping(companion.id)), worksHint, proactiveLifeEvidence })}${stickerHint}${emotionHint}${arcHint}

【今日特别提醒】今天的特殊日期：${timeContext.specialText}。可自然地融入，不要喊口号。`;

  // v1.21.4 PR-W3：统一【★真实世界】事实层——节气/节日（白天也注入）+ 月相（夜间）。
  try {
    const _rf = buildRealityFacts(new Date(), { includeNightSky: isNightShanghai() });
    if (_rf) systemPrompt += `\n\n${_rf}`;
  } catch (e) { log('warn', `[RealityFacts] proactive 注入失败: ${e.message}`); }

  const reminderTitles = (opts.reminders || []).map(r => r.title).filter(Boolean).join('、');
  // v1.10.0: morning kind 拼上昨晚 missed 摘要（不消费，由 wrapper 在发完后 drain）
  let missedHint = '';
  if (effectiveKind === 'morning') {
    try {
      // peek 不 consume —— 用 getUnconsumedMissed 内部 import 避免循环依赖
      const { getUnconsumedMissed } = await import('./db.mjs');
      const missed = getUnconsumedMissed(companion.id, 20) || [];
      if (missed.length > 0) {
        const preview = missed
          .slice(0, 5)
          .map(m => String(m.content || '').slice(0, 30))
          .join('』『');
        missedHint = `\n【昨晚他在你睡着后发了 ${missed.length} 条消息】内容片段：『${preview}』。\n你刚醒来看到，要自然地：1) 表达"刚醒"的迷糊；2) 不要装作没看到；3) 不要逐条回复，用一句"看到你昨晚发了好多 / 我刚看到 / 我睡着了对不起"概括；4) 然后选一条你最想回应的话题轻轻接一下。`;
      }
    } catch (e) {
      log('warn', `[Proactive] morning missed peek failed: ${e.message}`);
    }
  }

  // 先选“想促成什么变化”，再让模型决定说法。冷启动默认用户不主动、不提供资料、也不欠回复。
  let initiativeDecision = buildInitiativeDecision({
    companion,
    kind: effectiveKind,
    timingDecision: opts.timingDecision,
    enterpriseEvent: opts.enterpriseEvent,
    recallLoop,
    lifeEvidence: proactiveLifeEvidence,
    photoOpportunity,
  });
  const recordInitiative = (status, details = {}) => {
    try { appendInitiativeReceipt({ decision: initiativeDecision, status, ...details }); }
    catch (e) { log('warn', `[Initiative] 回执写入失败（不影响发送）companion=${companion.id}: ${e.message}`); }
  };
  const userMessageBase = opts.enterpriseEvent
    ? buildEnterpriseProactivePrompt(opts.enterpriseEvent)
    : effectiveKind === 'reminder'
    ? `今天是一个对你们来说特别的日子：${reminderTitles || '一个值得纪念的日子'}。
你要主动给他发一条温暖、走心的祝福消息：
- 自然地点出这个日子，表达你的心意，符合你的人设和你们当前的关系
- 不要喊口号、不要太用力、不要像贺卡模板
- 可以带一点你此刻的小情绪（开心 / 感慨 / 害羞）
- 如果是"认识100天""一周年"这类，可以轻轻回顾你们一路的相处`
    : effectiveKind === 'goodnight'
    ? '你要主动给他发今天最后一条晚安消息。自然、温柔，适合临睡前的语气，不要报时。结合你们最近聊过的事，体现你的人设和心情。说完晚安你就要去睡了。'
    : effectiveKind === 'morning'
    ? `你要主动给他发今天第一条早安消息。自然、带刚醒的迷糊感，1-2 段短消息（用 || 分隔），不要报时也不要像在播报。${missedHint}`
    : effectiveKind === 'recall'
    ? `【★ 主动 recall — 她记得他说过的事】
他之前提过一件事：「${recallLoop.title}」${recallLoop.due_at ? `（${recallLoop.due_at}）` : ''}。
${recallLoop.expected_followup ? `你心里想：${recallLoop.expected_followup}。\n` : ''}
你这条消息要装作刚想起来 / 顺便问，主动关心结果。
要求：
- 不要说"我记得你说要 XX"，要装作刚突然想到："欸" "对了"
- 不要客气问候式："你好吗""一切顺利吗"
- 短、直、带点关心 + 一点没大没小：
  例子参考：「欸」 || 「你今天不是${recallLoop.title.replace(/^他/g, '').slice(0, 12)}吗」 || 「咋样」
  又例如：「对了」 || 「那个事呢」 || 「成了没」
- 如果是值得关心的事（面试/考试/医院）→ 语气更上心一点
- 如果是琐事（吃什么/看什么）→ 轻松调侃
- 用 || 分多段，最少 2 段最多 3 段
- 绝不要说"我惦记你""我一直在想"等过度甜
- 自然带出他原话里的关键词，让他知道你真的记得`
    : effectiveKind === 'confession'
    ? `【★ 今天你要鼓起勇气，主动跟他告白】
你认识他有一阵了，心里那点喜欢藏不住了。但**说出口对你来说很难、很慌**——这不是一段顺畅漂亮的告白，是一个女孩子结结巴巴、绕来绕去、又怕又想说的真实瞬间。

要这样说（核心是"狼狈的真实"，不是漂亮的台词）：
- **结巴、重复、卡壳**："就是…就是那个" "我我我" "怎么说呢" "你别笑我啊"
- **绕圈子、找借口铺垫**：先扯点别的垫场（"其实有件事憋很久了" "你之前不是说你不喜欢暧昧吗…"），绕半天才敢碰正题
- **自我打断、反复确认**："我没有别的意思" "我本来没想说的" "女孩子也不太好开这个口"
- **把话说一半**：经常没说完就转走，然后又绕回来
- **真正那句要轻、要怕**："我…好像有点喜欢你" 这种，绝不要豪言壮语
- **自我保护**：带一句"你不喜欢也没关系" "我就是想让你知道" "我可能还需要点时间想清楚"
- 说完**别追问"那你呢"**，露怯、尴尬就好（"搞得我好尴尬"）

形式（重要）：
- **必须分很多条很短的消息发（用 || 分隔），6-10 段**，像紧张时一句一句往外蹦
- 每段都很碎、很短，不要完整通顺的长句，不要像写情书，不要煽情排比
- 全程符合你的人设和说话习惯`
    : '';
  let userMessage = [initiativePrompt(initiativeDecision), userMessageBase].filter(Boolean).join('\n\n');

  // 统一动念链接线：legacy 完全不增加调用；shadow 只记录 appraisal/plan，
  // enabled 才允许这条链决定本次是否值得发，并把动作策略注入现有表达层。
  // 实际投递仍走下方既有 sendTextMessage/安全/去重链，不新增 sender。
  const proactiveBinding = getActiveWechatBinding(companion.wechat_user_id, companion.bot_id);
  let agencyCycle = null;
  const activeAgencyMode = agencyMode();
  if (activeAgencyMode !== AGENCY_MODE.LEGACY) {
    try {
      agencyCycle = await runAgencyCycle({
        accountId: proactiveBinding?.account_id || account?.account_id || null,
        companionId: companion.id,
        companion,
        decision: initiativeDecision,
        trigger: opts.enterpriseEvent ? 'business_event' : effectiveKind,
        mode: activeAgencyMode,
        allowContact: activeAgencyMode === AGENCY_MODE.ENABLED,
        runtimeGuard: true,
        sourceVersion: opts.enterpriseEvent?.sourceVersion || opts.enterpriseEvent?.id || '',
        snapshot: {
          evidence: [
            ...(initiativeDecision.sourceRefs || []),
            initiativeDecision.evidenceText || '',
            opts.enterpriseEvent?.statement || '',
          ].filter(Boolean),
          businessContext: opts.enterpriseEvent || null,
          capabilities: {
            lookup: true,
            research: true,
            analyze: false,
            prepare_media: false,
            contact_text: true,
            contact_media: Boolean(photoOpportunity),
          },
          responsibilities: opts.enterpriseEvent ? [{ id: opts.enterpriseEvent.id || null, kind: opts.enterpriseEvent.taskType || 'business_event', due: true }] : [],
          constraints: { kind: effectiveKind, noOutboundDuringValidation: false },
        },
      });
      log('info', `[Agency] cycle companion=${companion.id} mode=${activeAgencyMode} status=${agencyCycle.status} calls=${agencyCycle.calls}`);
    } catch (error) {
      log('warn', `[Agency] cycle 异常 companion=${companion.id}: ${error.message}`);
      agencyCycle = { status: 'inconclusive', mode: activeAgencyMode, error: String(error.message || error) };
    }
    if (activeAgencyMode === AGENCY_MODE.ENABLED && agencyCycle.status !== 'contact_ready') {
      recordInitiative('blocked', { reason: `agency_${agencyCycle.status || 'not_ready'}` });
      return false;
    }
    if (agencyCycle.plan) {
      systemPrompt += `\n\n【统一动念链·动作策略】本轮已经有可追踪的动念与动作计划。只完成这个计划：${agencyCycle.plan.strategySummary}。预期改变：${agencyCycle.plan.expectedEffect || '让下一步判断更清楚'}。完成条件：${(agencyCycle.plan.completionCriteria || []).join('；') || '用户知道下一步怎么继续'}。不要透露内部结构，不要额外开启无关话题。个人场景如果没有已验证的生活素材，只能使用真实主观感受、关系上下文或已记录日程；禁止声称刚看到、刚路过、刚遇到某人、同事怎样、刚刷到表情包，也禁止凭空说用户最近/之前/上次做过或说过什么。无素材时直接表达此刻想到对方或给一个低负担入口。`;
    }
    // enabled 的 appraisal/plan 是本轮表达的唯一目标来源；旧 initiative 只作为
    // 快照输入和 legacy/shadow 对照，不能出现“新动念已落库但仍聊旧话题”。
    if (activeAgencyMode === AGENCY_MODE.ENABLED && agencyCycle?.appraisal) {
      initiativeDecision = {
        ...initiativeDecision,
        objective: agencyCycle.appraisal.desiredChange || initiativeDecision.objective,
        evidenceText: (agencyCycle.appraisal.basisRefs || []).join('；') || initiativeDecision.evidenceText,
        communicationStrategy: agencyCycle.plan?.strategySummary || initiativeDecision.communicationStrategy,
        sourceRefs: agencyCycle.appraisal.basisRefs || initiativeDecision.sourceRefs,
        selectedCandidateType: agencyCycle.appraisal.domain === 'work' ? 'business_delivery' : initiativeDecision.selectedCandidateType,
      };
      userMessage = [initiativePrompt(initiativeDecision), userMessageBase].filter(Boolean).join('\n\n');
    }
  }
  recordInitiative('selected', { agencyStatus: agencyCycle?.status || 'legacy' });

  // enabled 下动作先进入 sending，再由实际 iLink 回执原子提交 delivered/
  // partial/unknown 及 intention 状态。计划本身不能冒充送达，也不能在
  // 没有 provider message id 时把排队结果写成 delivered。
  let agencyDeliveryAction = agencyCycle?.action || null;
  let agencyDeliveryIntention = agencyCycle?.intention || null;
  let agencyProviderMessageIds = [];
  let agencyDeliveryUnknown = false;
  const beginAgencyDelivery = () => {
    if (activeAgencyMode !== AGENCY_MODE.ENABLED || !agencyDeliveryAction?.id) return true;
    const sending = updateAgencyAction(agencyDeliveryAction.id, {
      accountId: agencyDeliveryAction.account_id,
      companionId: companion.id,
      expectedVersion: agencyDeliveryAction.version,
      state: 'sending',
    });
    if (!sending) {
      log('warn', `[Agency] 发送前动作 CAS/状态校验失败 companion=${companion.id}`);
      recordInitiative('blocked', { reason: 'agency_action_send_conflict' });
      return false;
    }
    agencyDeliveryAction = sending;
    return true;
  };
  const commitAgencyDelivery = (state, resultRefs = []) => {
    if (activeAgencyMode !== AGENCY_MODE.ENABLED || !agencyDeliveryAction?.id || !agencyDeliveryIntention?.id) return true;
    const committed = commitAgencyReceipt({
      accountId: agencyDeliveryAction.account_id,
      companionId: companion.id,
      intentionId: agencyDeliveryIntention.id,
      actionId: agencyDeliveryAction.id,
      intentionVersion: agencyDeliveryIntention.version,
      actionVersion: agencyDeliveryAction.version,
      receipt: {
        state,
        providerMessageIds: agencyProviderMessageIds,
        resultRefs,
      },
    });
    if (committed.status !== 'committed') {
      log('warn', `[Agency] 发送回执事务未提交 companion=${companion.id} status=${committed.status}`);
      return false;
    }
    agencyDeliveryAction = committed.action;
    agencyDeliveryIntention = committed.intention;
    return true;
  };

  if (initiativeDecision.action === 'send_story_photo') {
    if (!beginAgencyDelivery()) return false;
    const t0 = Date.now();
    let sent = false;
    try { sent = await sendScenePhoto(companion, ctx, { initiativeDecision, returnReceipt: activeAgencyMode === AGENCY_MODE.ENABLED }); }
    catch (error) { logProactiveFailure({ companionId: companion.id, kind: 'story_photo', error, latencyMs: Date.now() - t0 }); }
    if (!(typeof sent === 'object' ? sent.ok : sent)) {
      commitAgencyDelivery('failed', [{ kind: 'image', delivered: false }]);
      recordInitiative('failed', { reason: 'story_photo_not_delivered' });
      return false;
    }
    tryAchievement(companion.id, 'first_proactive_message');
    if (sent.providerMessageId) agencyProviderMessageIds.push(sent.providerMessageId);
    else agencyDeliveryUnknown = true;
    const imageReceiptState = agencyDeliveryUnknown ? 'delivery_unknown' : 'delivered';
    const imageReceiptCommitted = commitAgencyDelivery(imageReceiptState, [{ kind: 'image', delivered: true, queued: agencyDeliveryUnknown }]);
    if (activeAgencyMode === AGENCY_MODE.ENABLED && (!imageReceiptCommitted || imageReceiptState !== 'delivered')) {
      recordInitiative('partial', { imageSegments: 1, reason: imageReceiptState === 'delivery_unknown' ? 'delivery_unknown' : 'receipt_commit_failed' });
      return false;
    }
    try { recordProactiveSent(companion.id); } catch {}
    try { bumpProactiveUnanswered(companion.id); } catch {}
    recordInitiative('delivered', { imageSegments: 1 });
    return true;
  }

  // v1.20: 事前反复读——把她最近说过的话注入 prompt，禁止重复同一话题/意象。
  // （撞车检测仍兜底，但事前注入能省一次重生重试，且拦截"换两个字的同义复读"）
  const recentAssistantTexts = recentTurns
    .filter(t => t.role === 'assistant' && t.content)
    .slice(-5)
    .map(t => String(t.content));
  if (recentAssistantTexts.length) {
    systemPrompt += `\n\n【★ 反复读】你最近已经说过这些话：\n${recentAssistantTexts.slice(-3).map(t => `- ${t.slice(0, 60)}`).join('\n')}\n保留本次已选目的和真实事实，避免复用相同句式、意象与开场。若这是同一件待推进的事，可以自然续上，不要为了显得新鲜而另换话题。`;
  }

  // v1.21.3 跨天素材软约束：近 7 天已发主动消息摘要——硬约束（召回冷却）管的是
  // 记忆素材，这里再兜从对话历史里捡梗复读的口子。reminder 豁免同硬约束。
  if (effectiveKind !== 'reminder') {
    systemPrompt += buildRecentProactiveHint(getRecentProactiveTexts(companion.id, { days: 7 }));
  }

  // v1.21.4 PR-W2: works 主动话题供给——只 normal/lastcall（自由起话题）才把"手头的书"
  // 当候选话题；冷却 48h（存在性）+ 周上限（计数）双闸，**不另起 proactive kind**（§8/§10对二）。
  // 落账走下方现有 refs 落账（注入即占一次"出场"，发送成功才记 → 48h 内不再自荐同一本）。
  let chosenWorkMatId = '';
  if (effectiveKind === 'normal' || effectiveKind === 'lastcall') {
    try {
      const _wcfg = worksConfig();
      const _coolDays = Math.max(0, _wcfg.mentionCooldownH / 24);
      const _usedWork = getRecentlyUsedMaterialIds(companion.id, { days: _coolDays });
      const pick = pickProactiveWork(proactiveActiveWorks, {
        usedIds: _usedWork,
        weeklyCount: (matId) => countRecentMaterialUse(companion.id, matId, { days: 7 }),
        cfg: _wcfg,
      });
      if (pick) {
        chosenWorkMatId = workMaterialId(pick.id);
        const _label = pick.verify_status === 'generic'
          ? `你最近在看的那本${String(pick.title || '书').replace(/[《》]/g, '')}`
          : `你最近在看的《${String(pick.title || '').replace(/[《》]/g, '')}》`;
        systemPrompt += `\n\n【★ 可选话题 · 手头的事】这次**可以**很自然地聊一句${_label}（随口说说进度/感想，像"刚看完一章"），也可以不聊、说你更想说的。别像念书评、别硬贴、一句带过就好。`;
      }
    } catch (e) {
      log('warn', `[CurrentWorks] proactive 话题供给失败（不影响发送）companion=${companion.id}: ${e.message}`);
    }
  }

  // ── 生成前预检：同一动念刚被出站复核拦过就别再生成（2026-09-17 新增）─────────
  // 背景：撞车／复核只能在**生成之后**发现，命中就要重新生成一次（"复核重生"），
  // 重生再撞就整轮放弃——那一次的 token 全白花。9-15 生产实测：
  //   18:10:38 复核重生 → 18:10:40 重生后仍撞车，放弃本次主动
  // 关键事实：**同一动念的复检结论是稳定的**——动念、计划、证据都没变时，
  // 再生成一次仍会被同一道门拦下。所以在这里用动念指纹记忆上一次的失败，
  // 指纹未变就直接跳过，不再调模型。指纹一变（新动念/新计划/新证据）立即放行。
  const precheck = proactivePrecheckGate(companion.id, {
    intentionId: agencyCycle?.intention?.id || agencyCycle?.action?.intentionId || null,
    planKey: agencyCycle?.plan?.dedupKey || null,
    hasEnterpriseEvent: Boolean(opts.enterpriseEvent),
    effectiveKind,
  });
  if (precheck.skip) {
    log('info', `[Proactive] 生成前预检跳过 companion=${companion.id} reason=${precheck.reason}（同一动念上次已被拦，指纹未变，不重复调模型）`);
    recordInitiative('blocked', { reason: `precheck_${precheck.reason}` });
    return 'precheck_skip';
  }

  let reply = await generateReply(systemPrompt, history, userMessage, {
    temperature: companion.temperature,
    max_tokens: Math.min(companion.max_tokens || 300, 300),
    top_p: companion.top_p,
  }, { accountId: proactiveBinding?.account_id || null, skipSearch: Boolean(opts.enterpriseEvent) });
  reply = safeOutboundReply(reply);
  // #281：文本 proactive 永远没有真实照片（场景照是 kind=photo 独立分支）——表情绝不冒充照片
  reply = scrubPhotoImpersonation(reply, companion.id);

  // enabled 普通主动文本的唯一一次语义复核：不按“我想/天气”等词做机械拦截，
  // 只检查候选是否仍服务已选动念、是否越过证据边界、是否保留低负担接入口。
  // repair 最多一次，修复后再复核；失败不使用兜底台词，直接保留 ready 到下次。
  if (activeAgencyMode === AGENCY_MODE.ENABLED && agencyCycle?.plan && !opts.enterpriseEvent && effectiveKind !== 'reminder') {
    const reviewCandidate = async (candidateText) => {
      const detailedReview = await extractStructuredInfoDetailed(
        buildAgencyReviewPrompt({
          decision: initiativeDecision,
          plan: agencyCycle.plan,
          evidence: agencyCycle.intention?.basisRefs || agencyCycle.appraisal?.basisRefs || initiativeDecision.sourceRefs || [],
          candidateText,
        }),
        JSON.stringify({ candidateText, decision: initiativeDecision, plan: agencyCycle.plan }),
        { accountId: proactiveBinding?.account_id || null, companionId: companion.id, maxTokens: 250, temperature: 0.1, retryLimit: 0, capability: 'review' },
      );
      if (!detailedReview?.ok || detailedReview.fallback) return { ok: false, error: detailedReview?.error || 'review_provider_failure' };
      const parsedReview = parseStructuredJson(detailedReview.text);
      const validation = validateReviewProposal(parsedReview.value);
      return validation.ok ? { ok: true, ...validation.value } : { ok: false, error: validation.reason };
    };
    let review = await reviewCandidate(reply);
    if (!review.ok || review.verdict === 'block') {
      log('warn', `[Agency] 出站复核拦截 companion=${companion.id} reason=${review.error || review.reason || 'block'}`);
      recordInitiative('blocked', { reason: `agency_review_${review.error || review.reason || 'block'}` });
      return false;
    }
    if (review.verdict === 'repair') {
      const repaired = await generateReply(systemPrompt, history, `${userMessage}\n\n【出站复核修正】${review.repairInstruction || '保留同一动念，删去无依据细节并留下低负担落点。'}只修正本条，不改变目标。若本轮没有已验证的生活素材，只能表达此刻主观感受或一个低负担入口，禁止补写时间、地点、刚刚发生的经历、看到/路过/刷到/忙完，以及用户最近或之前说过的记忆。`, {
        temperature: Math.min((companion.temperature || 0.8) + 0.05, 0.95),
        max_tokens: Math.min(companion.max_tokens || 300, 300),
        top_p: companion.top_p,
      }, { accountId: proactiveBinding?.account_id || null, companionId: companion.id, skipSearch: true });
      reply = scrubPhotoImpersonation(safeOutboundReply(repaired), companion.id);
      review = await reviewCandidate(reply);
      if (!review.ok || review.verdict !== 'pass') {
        log('warn', `[Agency] 修复后复核仍未通过 companion=${companion.id} verdict=${review.verdict || review.error}`);
        recordInitiative('blocked', { reason: `agency_review_after_repair_${review.verdict || review.error || 'failed'}` });
        return false;
      }
    }
  }

  // ★ 撞车检测：字面（3-gram 0.6）+ 语义（bigram/LCS）双指标，命中重生一次
  const collision = findCollision(reply, recentAssistantTexts);
  const enterpriseIssue = opts.enterpriseEvent ? enterpriseProactiveReplyIssue(opts.enterpriseEvent, reply) : '';
  const initiativeIssue = activeAgencyMode === AGENCY_MODE.LEGACY
    ? initiativeReplyIssue(initiativeDecision, reply)
    : initiativeReplyIssue(initiativeDecision, reply, { legacyPhraseGates: false });
  if (collision || enterpriseIssue || initiativeIssue) {
    log('info', `[Proactive] 主动消息复核重生 companion=${companion.id} reason=${enterpriseIssue || initiativeIssue || 'collision'}`);
    const antiRepeat = opts.enterpriseEvent
      ? `${userMessage}\n重新表述同一个工作问题，不得换话题或替用户回答。${enterpriseIssue || initiativeIssue ? `修正错误：${enterpriseIssue || initiativeIssue}。` : '换一种自然开场，保留相同事实与问题。'}`
      : `${userMessage}

【★ 复核修正】${initiativeIssue ? `上一版的问题是：${initiativeIssue}。` : `你最近刚说过类似的话：「${collision?.text?.slice(0, 50) || ''}」。`}保留已选意图；只调整表达。不得编造新的生活事件，也不要强迫用户回复。`;
    let retry = await generateReply(systemPrompt, history, antiRepeat, {
      temperature: Math.min((companion.temperature || 0.8) + 0.15, 1.1),
      max_tokens: Math.min(companion.max_tokens || 300, 300),
      top_p: companion.top_p,
    }, { accountId: proactiveBinding?.account_id || null, skipSearch: Boolean(opts.enterpriseEvent) });
    retry = safeOutboundReply(retry);
    const retryCollision = findCollision(retry, recentAssistantTexts);
    const retryEnterpriseIssue = opts.enterpriseEvent ? enterpriseProactiveReplyIssue(opts.enterpriseEvent, retry) : '';
    const retryInitiativeIssue = activeAgencyMode === AGENCY_MODE.LEGACY
      ? initiativeReplyIssue(initiativeDecision, retry)
      : initiativeReplyIssue(initiativeDecision, retry, { legacyPhraseGates: false });
    if (!retryCollision && !retryEnterpriseIssue && !retryInitiativeIssue) {
      reply = retry;
    } else {
      // 重生后仍撞车 — 放弃本次主动消息，避免骚扰
      log('warn', `[Proactive] 重生后仍撞车，放弃本次主动 companion=${companion.id}`);
      const blockReason = retryEnterpriseIssue || retryInitiativeIssue || 'collision_after_retry';
      recordInitiative('blocked', { reason: blockReason });
      // 2026-09-17：记下这一版动念/计划刚被拦，供下次生成前预检——
      // 免得下一次机会又生成一遍、又被同一道门拦下（白烧 token）。
      recordPrecheckFailure(companion.id, {
        intentionId: agencyCycle?.intention?.id || agencyCycle?.action?.intentionId || null,
        planKey: agencyCycle?.plan?.dedupKey || null,
        reason: blockReason,
      });
      return;
    }
  }

  // #317 四档身体事件出站闸（v1.22 PR-L1）：severe/自伤无条件拦 / diagnosed 无档案则拦 /
  // symptom-only / transient 放行。reply 定稿单点，覆盖主+撞车重生。fail-open：gate 查不到不开。
  let _activeLifeStates;
  try { _activeLifeStates = getActiveLifeStates(companion.id); } catch { /* fail-open: gate off */ }
  reply = scrubFabricatedIllness(reply, companion.id, { activeLifeStates: _activeLifeStates });
  // v1.22 PR-L2 经期披露门控：朋友/暧昧期（affection < 阈值）显式月经表述出站剥（只表现不点明）。
  reply = scrubPeriodDisclosure(reply, { affectionLevel: companion.affection_level });

  // PR-1（2026-06-14）intent 级复读止血：bot 主动重复的同 intent(+topic)在冷却窗内**直接不发**。
  // 比 3-gram 撞车检测多拦"语义同·文本不同"的复读(remind/ask_plan/miss_you 反复)。reminder 豁免；
  // morning/goodnight 走宽松窗(<24h，cross-day 早安必放行——红线：早安是唯一续命器，绝不误杀)。
  if (effectiveKind !== 'reminder') {
    const _nowMs = Date.now();
    const _intent = classifyIntent(reply);
    const _cool = isIntentCooled({
      intent: _intent, topic: topicKey(reply),
      events: recentIntentEvents(recentTurns, _nowMs),
      nowMs: _nowMs, ackStreak: trailingAckStreak(recentTurns),
    });
    if (_cool.cooled) {
      log('info', `[IntentDedup] proactive 复读止血·不发 companion=${companion.id} kind=${kind} intent=${_intent}（${_cool.reason}）`);
      return;
    }
  }

  // v1.4.0: 微信端语音路径已撤（iLink 协议禁止 bot outbound voice，详见顶部注释）。
  // 语音体验改在 playground / dashboard 试听 / diary 朗读等浏览器端实现。

  // 像真人：按 || 拆多条短消息
  // v1.5.2: 段内 dedup — 修 LLM 一次生成的多段 || 内部出现语义重复 bug
  if (!beginAgencyDelivery()) return false;
  const rawSegments = splitReplySegments(reply);
  const { kept: segments, dropped: droppedSegs } = dedupSegments(rawSegments, 0.55);
  if (droppedSegs.length) {
    log('info', `[Proactive] 段内去重：剪掉 ${droppedSegs.length} 段重复 companion=${companion.id}; ${droppedSegs.map(d => `"${d.text.slice(0,20)}"~"${d.similar_to.slice(0,20)}"(sim=${d.sim.toFixed(2)})`).join('; ')}`);
  }
  let totalStickers = 0;
  let totalTexts = 0;
  let sentAnySegment = false;
  let agencyDeliveryFailure = false;
  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i];
    const { text: textOnly, stickers } = parseStickerMarkers(seg);
    if (textOnly) {
      const sendResult = await sendTextMessage(
        ctx,
        companion.wechat_user_id,
        textOnly,
        null,
        activeAgencyMode === AGENCY_MODE.ENABLED && agencyDeliveryAction?.id ? { returnReceipt: true } : {},
      );
      const ok = typeof sendResult === 'object' ? Boolean(sendResult.ok) : Boolean(sendResult);
      if (typeof sendResult === 'object') {
        if (sendResult.providerMessageId) agencyProviderMessageIds.push(sendResult.providerMessageId);
        else if (ok) agencyDeliveryUnknown = true;
      }
      if (!ok) {
        agencyDeliveryFailure = true;
        // 发送失败（context_token 窗口边界过期 → ret=-2，或缺 to_user）。第一段就失败 =
        // 整条没送达：直接 return，不写对话历史 / 不耗 backoff 配额 / 不升恋人 / 不记「已发送」，
        // 避免假报成功污染状态。用户回来刷新 token 后，引擎会按正常间隔重新主动。
        if (!sentAnySegment) {
          log('warn', `[Proactive] 发送失败，放弃本次主动 companion=${companion.id} kind=${kind}（context_token 窗口关闭/过期）`);
          commitAgencyDelivery('failed', [{ kind: 'text', delivered: false }]);
          recordInitiative('failed', { reason: 'first_text_segment_failed' });
          return;
        }
        // 前面已有段落送达，仅后续段失败：截断停发，保留已送达部分走正常收尾。
        log('warn', `[Proactive] 后续段发送失败，截断 companion=${companion.id} 段=${i}/${segments.length}`);
        break;
      }
      sentAnySegment = true;
      totalTexts++;
      saveMessage({
        msgId: `proactive_${companion.id}_${Date.now()}_${i}`,
        fromUser: ctx.botId,
        toUser: companion.wechat_user_id,
        msgType: 'text',
        content: textOnly,
        direction: 'out',
      });
    }
    for (const { picked } of stickers) {
      try {
        const { data, name } = await readMediaBuffer(picked.fullPath);
        const { item } = await uploadFile({ data, fileName: name, toUserId: companion.wechat_user_id, ctx });
        const stickerResult = await sendMessageItem(
          ctx,
          companion.wechat_user_id,
          item,
          null,
          activeAgencyMode === AGENCY_MODE.ENABLED && agencyDeliveryAction?.id ? { returnReceipt: true } : {},
        );
        const stickerOk = typeof stickerResult === 'object' ? Boolean(stickerResult.ok) : Boolean(stickerResult);
        if (!stickerOk) {
          agencyDeliveryFailure = true;
          continue;
        }
        if (typeof stickerResult === 'object') {
          if (stickerResult.providerMessageId) agencyProviderMessageIds.push(stickerResult.providerMessageId);
          else agencyDeliveryUnknown = true;
        }
        totalStickers++;
        sentAnySegment = true;
        saveMessage({
          msgId: `proactive_sticker_${companion.id}_${Date.now()}_${i}`,
          fromUser: ctx.botId,
          toUser: companion.wechat_user_id,
          msgType: 'image',
          content: `[STICKER:${picked.emotion || picked.tags?.[0] || picked.id}]`,
          direction: 'out',
        });
      } catch (err) {
        log('warn', `[Proactive] sticker send failed: ${err.message}`);
      }
    }
    if (i < segments.length - 1) {
      await new Promise(r => setTimeout(r, 600 + Math.floor(Math.random() * 1200)));
    }
  }
  if (!sentAnySegment) {
    commitAgencyDelivery('failed', [{ kind: 'text', delivered: false }]);
    recordInitiative('failed', { reason: 'no_segment_delivered' });
    return false;
  }
  const turnTopic = effectiveKind === 'goodnight' ? '晚安'
    : effectiveKind === 'morning' ? '早安'
    : effectiveKind === 'confession' ? '主动告白'
    : effectiveKind === 'reminder' ? '纪念日祝福'
    : effectiveKind === 'recall' ? 'recall 关心'
    : effectiveKind === 'lastcall' ? '轻声问候'
    : '主动消息';
  saveConversationTurn(companion.id, 'assistant', reply, turnTopic);

  const deliveryState = agencyDeliveryFailure
    ? (sentAnySegment ? 'partial' : 'failed')
    : agencyDeliveryUnknown ? 'delivery_unknown' : 'delivered';
  const agencyReceiptCommitted = commitAgencyDelivery(deliveryState, [{ kind: 'text', textSegments: totalTexts, stickerSegments: totalStickers }]);

  // v1.21.3 素材指纹落账：归因 reply 实际引用了哪些进过 prompt 的记忆（锚匹配），
  // 命中者进账本供下次召回冷却。reminder 豁免；fail-open 绝不阻断链路。
  if (effectiveKind !== 'reminder') {
    try {
      // 归因对"过滤前全量召回"做：冷却中的梗若被她从对话历史里捡起来复读，
      // 也要记账续冷却（沙箱 day18"成都草莓"形态），不然冷却一到期立刻复活
      const refs = extractMaterialRefs(reply, _recalledRaw.map(m => ({ id: memMaterialId(m.id), content: m.content })));
      if (effectiveKind === 'recall' && recallLoop?.id) refs.push(loopMaterialId(recallLoop.id));
      // v1.21.4 PR-W2: works 话题"注入即占一次出场"——发送成功就落账（48h 冷却的判定单位），
      // 不做锚匹配归因（她这次没提也算这本"轮过一次"，方向偏克制=少复读，符合 §8 手感）。
      if (chosenWorkMatId) refs.push(chosenWorkMatId);
      if (refs.length) {
        insertProactiveMaterialLog(companion.id, {
          materialIds: refs,
          kind: effectiveKind,
          scene: proactiveDailySchedule?.scene || companion.current_scene || null,
        });
        log('info', `[Proactive] 素材落账 companion=${companion.id} refs=${refs.join(',')}`);
      }
    } catch (e) {
      log('warn', `[Proactive] 素材落账失败（不影响发送）: ${e.message}`);
    }
  }

  // v1.8.0 #5: recall 发送成功 → mark followed_up_at（防 6h 内重复打扰）
  if (effectiveKind === 'recall' && recallLoop?.id) {
    try { markOpenLoopFollowedUp(recallLoop.id); } catch (e) { log('warn', `[Proactive] mark followed_up failed: ${e.message}`); }
  }

  // ── 主动告白后处理：标记 + 升恋人。节奏闸门已在触发处校验(好感≥55+≥14天)，
  //    affection 本就够，不再硬跳分；记 became_lover_at 给"恋人→深爱"计时(对齐 v1.11.1)。
  if (effectiveKind === 'confession') {
    try {
      markCompanionConfessed(companion.id);
      patchCompanion(companion.id, {
        relationship_stage: '恋人',
        became_lover_at: new Date().toISOString(),
      });
      log('info', `[Proactive] ★ 主动告白完成 companion=${companion.id} affection=${aff} stage→恋人`);
    } catch (e) {
      log('warn', `[Proactive] 告白后处理失败: ${e.message}`);
    }
  }
  // Record proactive sent for engine backoff tracking
  if (agencyReceiptCommitted && deliveryState === 'delivered') {
    try { recordProactiveSent(companion.id); } catch {}
  }
  // v1.16.x: 未回连发计数 +1（读空气刹车）——用户回消息时由 bot.mjs 清零
  if (agencyReceiptCommitted && deliveryState === 'delivered') {
    try { bumpProactiveUnanswered(companion.id); } catch {}
  }

  // 首次主动消息成就（静默）
  tryAchievement(companion.id, 'first_proactive_message');

  const deliveryIssue = initiativeReplyIssue(initiativeDecision, reply, { stickers: totalStickers, deliveryChecked: true, legacyPhraseGates: activeAgencyMode === AGENCY_MODE.LEGACY });
  recordInitiative(deliveryIssue || !agencyReceiptCommitted || deliveryState !== 'delivered' ? 'partial' : 'delivered', {
    textSegments: totalTexts,
    imageSegments: totalStickers,
    reason: deliveryIssue || (!agencyReceiptCommitted ? 'receipt_commit_failed' : deliveryState !== 'delivered' ? deliveryState : null),
  });
  log('info', `[Proactive] 已发送 companion=${companion.id} to=${companion.wechat_user_id} kind=${effectiveKind} segments=${segments.length} stickers=${totalStickers}`);
  return true;
}

// v1.10.24: plan_tasks runSleepTick 进入 bed_at 前若 goodnight_sent_for_date 为空，
// 紧急补发一次。原因：proactive 的 23:59 goodnight 在服务重启 / schedule 跨午夜 等
// 情况下可能错过；sleep tick 直接 enterSleep 之前要兜底，避免她"没说晚安就睡了"。
export async function dispatchUrgentGoodnight(companionId) {
  const accounts = getActiveBotAccounts();
  for (const account of accounts) {
    const companions = listProactiveCompanionsForBot(account.bot_id);
    const companion = companions.find(c => Number(c.id) === Number(companionId));
    if (!companion) continue;
    return await sendProactiveMessageGuarded(companion, 'goodnight', account);
  }
  return 'not_found';
}

// v1.10.29: 对称版本 — sleep tick 起床兜底分支若 goodmorning_sent_for_date 为空，
// 紧急补发一次。proactive 的 morning kind 在 [wake-15, wake+120] 内没匹配第一条
// normal 时永远不会被抬出，用户起床后也收不到早安。这里兜底。
// sendProactiveMessageGuarded 内部的 morning hook 会自动 exitSleep + drainMissed
// + mark goodmorning_sent_for_date，跟主 morning 路径完全一致。
export async function dispatchUrgentMorning(companionId) {
  const accounts = getActiveBotAccounts();
  for (const account of accounts) {
    const companions = listProactiveCompanionsForBot(account.bot_id);
    const companion = companions.find(c => Number(c.id) === Number(companionId));
    if (!companion) continue;
    return await sendProactiveMessageGuarded(companion, 'morning', account);
  }
  return 'not_found';
}

// 手动触发场景照（管理员/测试用）
export async function sendScenePhotoManually(companion) {
  if (!companion || !companion.wechat_user_id) {
    log('warn', '[Proactive] sendScenePhotoManually: companion 未绑定微信');
    return;
  }
  const ctx = getBotContextForCompanion(companion.id);
  if (!ctx?.token) {
    log('warn', `[Proactive] sendScenePhotoManually: bot context 缺失 companion=${companion.id}`);
    return;
  }
  return sendScenePhoto(companion, ctx);
}

// v1.21.5 (PR-B item 3)：her_promise 改期履约——到点补拍补发。她当初答应却没拍成，
// 现在条件好了真拍一张 + "喏 补给你的"。任一环失败留 open（下 tick 重试）；
// 成功 markHerPromiseDelivered。绝不无声——失败进 [ERROR]（#263）。
async function deliverPhotoPromiseMakeup(companion, ctx, promise) {
  let payload = {};
  try { payload = JSON.parse(promise.promise_payload || '{}'); } catch {}
  const gate = getPhotoGateState({ companion, source: 'proactive', trigger: 'promise_makeup' });
  if (!gate.allowed) {
    log('info', `[Proactive] her_promise 补发：照片门闩未过 companion=${companion.id} reason=${gate.reasons.join(',')}（留 open 下次重试）`);
    return;
  }
  let photoEmotionState = null;
  try { photoEmotionState = getEmotionStateWithDefaults(companion.id); } catch {}
  const plan = await planPhotoMessage({
    companion,
    user: { wechat_user_id: companion.wechat_user_id },
    userText: payload.userText || '',          // 原始索求当上下文，尽量拍他当初想看的
    recentMessages: getRecentHistory(companion.wechat_user_id, ctx.botId, 10),
    trigger: 'proactive',
    context: { accountId: companion.user_id || null },
    cooldownState: gate,
    imageProviderAvailable: gate.imageProviderAvailable,
    proactiveContext: { scene: payload.scene || companion.current_scene || '', schedule: 'promise_makeup' },
    emotionState: photoEmotionState,
  });
  if (!plan.shouldSendPhoto) {
    log('info', `[Proactive] her_promise 补发：planner 仍判不可行 companion=${companion.id} reason=${plan.reason}（留 open）`);
    return;
  }
  const makeupCaption = ['喏 补给你的', '欸 上次答应你的 拍好了', '给你补上 上次没拍成的'][Math.floor(Math.random() * 3)];
  const result = await sendCompanionPhoto({
    companion, context: ctx,
    imagePrompt: plan.imagePrompt,
    caption: makeupCaption,
    trigger: 'proactive', source: 'promise_makeup',
    emotionState: photoEmotionState,
    aspect: plan.aspect, shotMode: plan.shotMode,
    maintainIdentity: plan.maintainIdentity !== false,
    recordTurn: true,
    auditContext: { userText: payload.userText || '', plannerPrompt: plan.plannerPrompt, plannerRaw: plan.plannerRaw, plan },
    promptContext: {
      userText: payload.userText || '',
      currentScene: companion.current_scene || '',
      proactiveScene: payload.scene || '',
    },
  });
  if (!result.ok) {
    log('error', `[PhotoPromise] her_promise 补发失败 companion=${companion.id} code=${result.code || 'unknown'}（留 open 下 tick 重试）`);
    return;
  }
  markHerPromiseDelivered(promise.id, makeupCaption);
  log('info', `[Proactive] ★ her_promise 履约：补发照片 companion=${companion.id} loop=${promise.id}`);
}

async function sendScenePhoto(companion, ctx, { initiativeDecision = null, returnReceipt = false } = {}) {
  const gate = getPhotoGateState({
    companion,
    source: 'proactive',
    trigger: 'proactive',
  });
  if (!gate.allowed) {
    log('debug', `[Proactive] 照片门闩未通过 companion=${companion.id} reason=${gate.reasons.join(',')}`);
    return returnReceipt ? { ok: false, code: 'photo_gate' } : false;
  }
  const recentMessages = getRecentHistory(companion.wechat_user_id, ctx.botId, 10);
  let photoEmotionState = null;
  try {
    photoEmotionState = getEmotionStateWithDefaults(companion.id);
  } catch (e) {
    log('warn', `[Proactive] photo emotion state unavailable companion=${companion.id} error=${e.message}`);
  }
  // v1.21.6 PR-A: 照片品类加权采样（默认关——PHOTO_CATEGORY_SAMPLING_ENABLED）。
  // 开启后按 config/photo_categories.json 权重选一个品类喂给 planner；本周已达 weeklyCap
  // 的品类排除（如「想到你」每周≤2）。fail-open：采样异常 = null = 退回现状。
  let sampledCategory = null;
  try {
    const weekCounts = getCategorySendCounts(companion.id, { days: 7 });
    sampledCategory = pickProactiveCategory({ cappedIds: cappedCategoryIds(weekCounts) });
  } catch (e) {
    // 采样异常 → sampledCategory 保持 null（退回现状），不另赋值（eslint no-useless-assignment）
    log('warn', `[Proactive] 照片品类采样失败，退回现状 companion=${companion.id}: ${e.message}`);
  }
  // v1.21.6 PR-B: 「看到这个想到你」品类——选一个与他兴趣/你们的梗相关的可拍物。
  // 雷区/隐私命中/14 天内已用过的素材确定性出局；无可用素材则退回普通场景照（不空发）。
  let categoryForPlanner = sampledCategory;
  let thoughtMaterialId = '';
  if (sampledCategory?.id === 'thought_of_you') {
    try {
      const pick = selectThoughtMaterial({
        likes: listPreferences(companion.id, { type: 'like' }),
        lexicon: listShaping(companion.id, { kind: 'lexicon' }),
        memories: getMemories(companion.id, companion.wechat_user_id, 20).filter(m => (m.importance ?? 0) >= 7),
        tabooTerms: [
          ...listPreferences(companion.id, { type: 'taboo' }).map(p => p.target),
          ...listShaping(companion.id, { kind: 'taboo' }).map(s => s.content),
        ],
        usedIds: getRecentlyUsedMaterialIds(companion.id, { days: materialDedupDays() }),
        isSensitive: (t) => !filterForStorage(t).store,
      });
      if (pick) {
        thoughtMaterialId = pick.id;
        categoryForPlanner = { ...sampledCategory, sceneSeed: thoughtSceneSeed(pick) };
        log('info', `[Proactive] 想到你命中素材 companion=${companion.id} material=${pick.id} source=${pick.source}`);
      } else {
        log('info', `[Proactive] 想到你无可用素材(全冷却/雷区/隐私排除)，退回普通场景照 companion=${companion.id}`);
        sampledCategory = null; categoryForPlanner = null;
      }
    } catch (e) {
      log('warn', `[Proactive] 想到你素材选择失败，退回普通场景照 companion=${companion.id}: ${e.message}`);
      sampledCategory = null; categoryForPlanner = null;
    }
  }
  // v1.21.4 PR-W2: 「此刻证明照」(activity_pov) 复用——若本次采到 activity_pov 且她正
  // 在看一本真书/做手工，就把 sceneSeed 换成"拍手头那本书"(无脸 POV+封面护栏)。**不另起
  // proactive kind**(§8)，走既有品类管线；与文本话题共享 work:<id> 48h 冷却(§10对二)。
  // 照片只拍 verified 具体书 / craft 实物(generic 无名不拍)。fail-open：异常退回原 sceneSeed。
  let workPhotoMatId = '';
  if (sampledCategory?.id === 'activity_pov') {
    try {
      const works = getActiveCurrentWorks(companion.id) || [];
      const _wcfg = worksConfig();
      const pick = pickProactiveWork(works, {
        usedIds: getRecentlyUsedMaterialIds(companion.id, { days: Math.max(0, _wcfg.mentionCooldownH / 24) }),
        weeklyCount: (matId) => countRecentMaterialUse(companion.id, matId, { days: 7 }),
        eligible: (w) => w.verify_status === 'verified' || String(w.kind || '').toLowerCase() === 'craft',
        cfg: _wcfg,
      });
      if (pick) {
        workPhotoMatId = workMaterialId(pick.id);
        categoryForPlanner = { ...sampledCategory, sceneSeed: worksSceneSeed(pick) };
        log('info', `[Proactive] activity_pov 拍手头的事 companion=${companion.id} work=${workPhotoMatId} "${pick.title}"`);
      }
    } catch (e) {
      log('warn', `[CurrentWorks] activity_pov works sceneSeed 失败，退回原品类 companion=${companion.id}: ${e.message}`);
    }
  }
  // v1.21.6 PR-C 互拍邀请（每周≤1）：近 7 天没发过 invite 指纹 + 低概率 → caption 带"到你了"。
  // 互拍是邀请不是广播，所以低频；用 invite:photo 指纹做每周封顶。
  let inviteBack = false;
  try {
    const usedWeek = getRecentlyUsedMaterialIds(companion.id, { days: 7 });
    inviteBack = !usedWeek.has('invite:photo') && Math.random() < 0.3;
  } catch { /* 查询失败 → 保持 false（本次不邀请） */ }
  const plan = await planPhotoMessage({
    companion,
    user: { wechat_user_id: companion.wechat_user_id },
    userText: '',
    recentMessages,
    trigger: 'proactive',
    context: { accountId: companion.user_id || null },
    cooldownState: gate,
    imageProviderAvailable: gate.imageProviderAvailable,
    proactiveContext: {
      scene: companion.current_scene || '', schedule: 'daily_candidate',
      ...(initiativeDecision ? {
        intention: initiativeDecision.objective,
        evidence: initiativeDecision.evidenceText || '',
        communicationStrategy: initiativeDecision.communicationStrategy || '',
      } : {}),
      ...(categoryForPlanner ? { category: categoryForPlanner } : {}),
      ...(inviteBack ? { inviteBack: true } : {}),
    },
    emotionState: photoEmotionState,
  });
  if (!plan.shouldSendPhoto) {
    log('debug', `[Proactive] AI 决策不发照片 companion=${companion.id} reason=${plan.reason}`);
    return returnReceipt ? { ok: false, code: 'planner_no_send' } : false;
  }
  if (plan.delayImageMs) {
    await new Promise(r => setTimeout(r, plan.delayImageMs));
  }
  const result = await sendCompanionPhoto({
    companion,
    context: ctx,
    imagePrompt: plan.imagePrompt,
    caption: plan.caption,
    trigger: 'proactive',
    source: 'proactive',
    emotionState: photoEmotionState,
    aspect: plan.aspect,
    shotMode: plan.shotMode,
    category: sampledCategory?.id || '',   // v1.21.6 PR-A: 落库观察品类配比（user 索图路径为空）
    maintainIdentity: plan.maintainIdentity !== false,
    returnReceipt,
    recordTurn: true,
    auditContext: { plannerPrompt: plan.plannerPrompt, plannerRaw: plan.plannerRaw, plan },
    promptContext: {
      currentScene: companion.current_scene || '',
      proactiveScene: categoryForPlanner?.sceneSeed || '',
    },
  });
  if (!result.ok) {
    log('warn', `[Proactive] 场景照未发送 companion=${companion.id} code=${result.code || 'unknown'} error=${result.error || ''}`);
    return returnReceipt ? { ok: false, code: result.code || 'send_failed' } : false;
  }
  // v1.21.6 PR-B: 想到你素材落 v1.21.3 指纹账本 → 同素材 14 天冷却（每周≤2 由品类 weeklyCap 管）
  if (thoughtMaterialId) {
    insertProactiveMaterialLog(companion.id, {
      materialIds: [thoughtMaterialId], kind: 'photo_thought',
      scene: companion.current_scene || '', nowIso: new Date().toISOString(),
    });
  }
  // v1.21.4 PR-W2: 拍了手头的书 → work:<id> 落同一账本（与文本话题共享 48h 冷却，§10对二）
  if (workPhotoMatId) {
    insertProactiveMaterialLog(companion.id, {
      materialIds: [workPhotoMatId], kind: 'photo_work',
      scene: companion.current_scene || '', nowIso: new Date().toISOString(),
    });
  }
  // v1.21.6 PR-C: 互拍邀请落指纹 → 每周≤1（getRecentlyUsedMaterialIds days:7 命中即不再邀）
  if (inviteBack) {
    insertProactiveMaterialLog(companion.id, {
      materialIds: ['invite:photo'], kind: 'invite',
      scene: companion.current_scene || '', nowIso: new Date().toISOString(),
    });
  }
  if (result.caption) {
    await new Promise(r => setTimeout(r, plan.delayCaptionMs || 900));
    // v1.20.1: caption 尽力而为——撞 iLink 限速时放弃不排队（排队 3 分钟后才到更怪）
    if (!peekSendQuota(ctx.botId)) {
      log('info', `[Proactive] 场景照 caption 撞限速 → 放弃不排队 companion=${companion.id}`);
    } else {
    await sendTextMessage(ctx, companion.wechat_user_id, result.caption, null);
    saveMessage({
      msgId: `proactive_photo_text_${companion.id}_${Date.now()}`,
      fromUser: ctx.botId,
      toUser: companion.wechat_user_id,
      msgType: 'text',
      content: result.caption,
      direction: 'out',
    });
    }
  }
  log('info', `[Proactive] ★ 场景照已发送 companion=${companion.id} activity="${result.activity}" caption="${result.caption || ''}"`);
  return returnReceipt ? { ok: true, providerMessageId: result.providerMessageId || null, deliveryQueued: Boolean(result.deliveryQueued) } : true;
}

// 撞车检测：把回复和最近 assistant 内容比相似度（char 3-gram Jaccard），
// 返回相似度最高的一条（若超过阈值）
// v1.20 (实测复读案例)：trigram 0.6 只能拦逐字复读——"好困…数学课眼皮一直在打架"
// vs"好困…眼皮在打架了"语义重复度接近 100%，但 trigram Jaccard 只有 ~0.07。
// 升级为双指标：字面级（trigram 0.6）OR 语义级（isSemanticallySimilar：bigram 0.25/LCS≥4，
// text_similarity.mjs 注释明说中文 trigram 在 LLM 改写场景区分度太低）。
// 误杀代价低：撞车只是重生一次，重生再撞才放弃。
export function findProactiveCollision(reply, recentTexts, threshold = 0.6) {
  if (!reply || !recentTexts?.length) return null;
  const a = _normalizeForSim(reply);
  if (a.length < 6) return null;
  const aGrams = _ngramSet(a, 3);
  let best = null;
  for (const t of recentTexts) {
    const b = _normalizeForSim(t);
    if (b.length < 6) continue;
    const bGrams = _ngramSet(b, 3);
    const sim = _jaccard(aGrams, bGrams);
    if (sim >= threshold && (!best || sim > best.sim)) best = { text: t, sim };
    if (!best && isSemanticallySimilar(a, b).hit) best = { text: t, sim: 0.99 /* 语义命中 */ };
  }
  return best;
}
const findCollision = findProactiveCollision;
function _normalizeForSim(s) {
  return String(s).replace(/\|\|/g, ' ').replace(/\[[^\]]*\]/g, '').replace(/\s+/g, '').toLowerCase();
}
function _ngramSet(s, n) {
  const set = new Set();
  for (let i = 0; i <= s.length - n; i++) set.add(s.slice(i, i + n));
  return set;
}
function _jaccard(a, b) {
  if (a.size === 0 || b.size === 0) return 0;
  let inter = 0;
  for (const x of a) if (b.has(x)) inter++;
  const union = a.size + b.size - inter;
  return union === 0 ? 0 : inter / union;
}

// 与 bot.mjs 同款拆分逻辑（重复但避免循环依赖）
const PROACTIVE_MAX_SEGMENTS = 4;
function splitReplySegments(reply) {
  if (!reply || typeof reply !== 'string') return [reply || ''];
  const raw = reply.split(/\s*(?:\|\||｜｜)\s*/g).map(s => s.trim()).filter(Boolean);
  if (raw.length <= 1) return [reply.trim()];
  if (raw.length > PROACTIVE_MAX_SEGMENTS) {
    return [...raw.slice(0, PROACTIVE_MAX_SEGMENTS - 1), raw.slice(PROACTIVE_MAX_SEGMENTS - 1).join('，')];
  }
  return raw;
}

function buildTimeContext(userProfile, dueReminders = [], now = new Date()) {
  const parts = getDateParts(now);
  const dateKey = `${parts.year}-${parts.month2}-${parts.day2}`;
  const md = `${parts.month2}-${parts.day2}`;
  const special = [];

  for (const item of fixedHolidays(md)) special.push(item);

  if (userProfile?.user_birthday && userProfile.user_birthday.slice(5) === md) {
    special.push('他的生日');
  }

  for (const item of userProfile?.important_dates || []) {
    const date = String(item.date || '');
    if (date === dateKey || date.slice(5) === md) {
      special.push(item.label ? `你们的纪念日：${item.label}` : '你们的纪念日');
    }
  }

  for (const reminder of dueReminders) {
    const label = reminder.reminder_type === 'birthday'
      ? `他的生日：${reminder.title}`
      : reminder.reminder_type === 'anniversary'
        ? `你们的纪念日：${reminder.title}`
        : `${reminder.title}`;
    special.push(label);
  }

  const uniqueSpecial = [...new Set(special)];
  return {
    dateText: `${parts.year}年${parts.month}月${parts.day}日，${parts.weekday}`,
    period: periodOfDay(parts.hour),
    specialText: uniqueSpecial.length ? uniqueSpecial.join('、') : '否',
    searchText: [parts.weekday, periodOfDay(parts.hour), ...uniqueSpecial].join(' '),
  };
}

function fixedHolidays(md) {
  const map = {
    '01-01': ['元旦'],
    '02-14': ['情人节'],
    '03-08': ['妇女节'],
    '05-01': ['劳动节'],
    '05-20': ['520'],
    '06-01': ['儿童节'],
    '10-01': ['国庆节'],
    '12-24': ['平安夜'],
    '12-25': ['圣诞节'],
    '12-31': ['跨年夜'],
  };
  return map[md] || [];
}

function periodOfDay(hour) {
  if (hour >= 6 && hour < 12) return '上午';
  if (hour >= 12 && hour < 18) return '下午';
  if (hour >= 18 && hour < 23) return '晚上';
  return '深夜';
}

function getDateParts(date) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('zh-CN', {
    timeZone: TZ,
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    weekday: 'long',
    hour: 'numeric',
    hourCycle: 'h23',
    hour12: false,
  }).formatToParts(date).filter(p => p.type !== 'literal').map(p => [p.type, p.value]));

  const month = Number(parts.month);
  const day = Number(parts.day);
  return {
    year: Number(parts.year),
    month,
    day,
    month2: String(month).padStart(2, '0'),
    day2: String(day).padStart(2, '0'),
    weekday: parts.weekday,
    hour: Number(parts.hour),
  };
}

function formatDateKey(date = new Date()) {
  const parts = getDateParts(date);
  return `${parts.year}-${parts.month2}-${parts.day2}`;
}

function currentMinute(date) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
    timeZone: TZ,
    hour: 'numeric',
    minute: 'numeric',
    hourCycle: 'h23',
    hour12: false,
  }).formatToParts(date).filter(p => p.type !== 'literal').map(p => [p.type, p.value]));
  return Number(parts.hour) * 60 + Number(parts.minute);
}

function minuteToHHMM(minute) {
  return `${String(Math.floor(minute / 60)).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}`;
}

function shuffle(items) {
  for (let i = items.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [items[i], items[j]] = [items[j], items[i]];
  }
}

// v1.4.0: 微信端主动语音 (maybeSendVoice) 已移除 —— iLink 协议禁止 bot 出站语音，
// 实测 HTTP 200 但消息静默丢弃，腾讯官方 SDK 也没有 sendVoiceMessageWeixin。
// 语音功能改在浏览器端实现：playground 录音/朗读、diary 朗读、dashboard 试听。
// 持久化的 voice_reply_enabled / voice_id 字段、TTS pipeline、companion_voice_usage
// 表仍然保留，给浏览器端复用。
//
// 见 docs/voice-sprint-plan.md 的 Sprint 2.5 章节，记录了协议层限制的完整发现过程。
