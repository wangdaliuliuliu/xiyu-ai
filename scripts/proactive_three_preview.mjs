/**
 * High-fidelity proactive preview.
 *
 * The caller must point DB_PATH at a disposable SQLite snapshot. This script
 * uses the configured production provider and the current workbench bridge,
 * but never imports or calls an outbound sender. Agency state and usage land
 * only in the disposable database.
 */
import 'dotenv/config';
import fs from 'node:fs';
import {
  getDb, getCompanionById, getConversationContext, getDailySchedule,
  getRecentSchedules, getPersonaFacts, getUserProfile, recallMemories,
  getCompanionPreferencesForPrompt, shanghaiDateKey,
} from '../src/db.mjs';
import { buildLongTermDigest } from '../src/plan_tasks.mjs';
import { buildSystemPrompt } from '../src/companion.mjs';
import { generateReply, withAiAudit } from '../src/ai.mjs';
import {
  buildInitiativeDecision, initiativePrompt, initiativeReplyIssue,
  selectProactiveLifeEvidence,
} from '../src/initiative.mjs';
import {
  buildEnterpriseProactivePrompt, enterpriseProactiveReplyIssue,
} from '../src/enterprise_context.mjs';
import { runAgencyCycle } from '../src/proactive.mjs';
import { safeOutboundReply } from '../src/moderation.mjs';
import {
  getEmotionStateWithDefaults, buildEmotionPromptHint, getMissingLevel,
} from '../src/emotion_state.mjs';

const companionId = Number(process.argv[2] || 1);
const accountId = Number(process.argv[3] || 1);
const companion = getCompanionById(companionId);
if (!companion) throw new Error(`companion ${companionId} not found`);
const db = getDb();
const dailyKey = shanghaiDateKey();
const dailyRaw = getDailySchedule(companionId, dailyKey);
const dailySchedule = dailyRaw ? { ...dailyRaw, date_key: dailyKey } : null;
const recentSchedules = getRecentSchedules(companionId, dailyKey, 3);
const recentTurns = getConversationContext(companionId, 10);
const memories = companion.memory_enabled
  ? recallMemories(companion.id, companion.user_id, '主动联系 工作 生活 想法', 7)
  : [];
const userProfile = getUserProfile(companion.user_id, companion.id);
const personaFacts = getPersonaFacts(companion.id);
const preferences = getCompanionPreferencesForPrompt(companion.id);
const longTermDigest = await buildLongTermDigest(companion.id, companion.user_id, { isPro: true });
const emotion = getEmotionStateWithDefaults(companion.id);
const emotionHint = Number(companion.safe_mode)
  ? ''
  : buildEmotionPromptHint(emotion, { missingLevel: getMissingLevel(emotion, companion.last_user_reply_at) });

process.env.XIYU_WORKBENCH_CONTEXT_URL = process.env.AGENCY_PREVIEW_WORKBENCH_URL || 'http://127.0.0.1:4175';
const token = process.env.XIYU_WORKBENCH_CONTEXT_TOKEN || '';
const gapResponse = await fetch(`${process.env.XIYU_WORKBENCH_CONTEXT_URL}/api/knowledge/gaps`, {
  headers: { 'x-xiyu-token': token, accept: 'application/json' },
});
const gapPayload = await gapResponse.json();
const gap = (gapPayload.items || []).find(item => item.status === 'open' && item.acquisitionRoute === 'operator');

// The current open operator gap is copied into the disposable preview as an
// event so the requested work-related candidate is based on live workbench
// state without creating a production event or consuming a daily slot.
const workEvent = gap ? {
  id: `preview:${gap.id}`,
  statement: `东坝：${gap.statement}`,
  question: gap.question,
  expectedAction: gap.question,
  decisionImpact: gap.decisionImpact || gap.whyNeeded,
  expectedAnswer: gap.expectedAnswer,
  evidencePeriod: gap.evidencePeriod || null,
  sourceRefs: gap.sourceRefs || [],
  knowledgeGapId: gap.id,
  valueScore: gap.valueScore,
  priority: gap.priority,
  taskType: 'knowledge_gap_followup',
  actorId: String(accountId),
  scope: gap.scope || {},
  previewInjected: true,
} : null;

const baseSystem = buildSystemPrompt(companion, {
  memories,
  userProfile,
  recentTurns,
  longTermDigest,
  promptMode: 'proactive',
  dailySchedule,
  recentSchedules,
  personaFacts,
  preferences,
});

const now = new Date();
const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
}).formatToParts(now).map(part => [part.type, part.value]));
const nowMinute = Number(parts.hour) * 60 + Number(parts.minute);
const lifeEvidence = selectProactiveLifeEvidence(dailySchedule, nowMinute);

const specs = [
  {
    label: '业务候选（当前工作台知识缺口）',
    kind: 'work',
    event: workEvent,
    decision: buildInitiativeDecision({
      companion,
      kind: 'normal',
      timingDecision: { trigger: 'share_thought', motivation: 0.75 },
      enterpriseEvent: workEvent,
      now,
    }),
  },
  {
    label: '陪伴候选（今日真实日程）',
    kind: 'personal',
    event: null,
    decision: buildInitiativeDecision({
      companion,
      kind: 'normal',
      timingDecision: { trigger: 'schedule_item', motivation: 0.58 },
      lifeEvidence,
      now,
    }),
  },
  {
    label: '陪伴候选（低负担关系开场）',
    kind: 'personal',
    event: null,
    decision: buildInitiativeDecision({
      companion,
      kind: 'normal',
      timingDecision: { trigger: 'check_in', motivation: 0.52 },
      now: new Date(now.getTime() + 90 * 60_000),
    }),
  },
];

const trace = [];
const results = [];
for (const spec of specs) {
  let decision = spec.decision;
  let agency = null;
  if (spec.event) {
    agency = await runAgencyCycle({
      accountId,
      companionId,
      companion,
      mode: 'shadow',
      allowContact: false,
      trigger: 'business_event',
      decision: { ...decision, enterpriseEvent: spec.event },
      snapshot: {
        evidence: [spec.event.statement, spec.event.question].filter(Boolean),
        businessContext: spec.event,
      },
      deps: { now: now.toISOString() },
    }).catch(error => ({ status: 'inconclusive', error: String(error.message || error) }));
    if (agency?.appraisal) {
      decision = {
        ...decision,
        objective: agency.appraisal.desiredChange || decision.objective,
        evidenceText: (agency.appraisal.basisRefs || []).join('；') || decision.evidenceText,
        communicationStrategy: agency.plan?.strategySummary || decision.communicationStrategy,
        sourceRefs: agency.appraisal.basisRefs || decision.sourceRefs,
      };
    }
  }

  let system = `${baseSystem}${emotionHint}`;
  const userPrompt = [
    initiativePrompt(decision),
    spec.event ? buildEnterpriseProactivePrompt(spec.event) : '',
  ].filter(Boolean).join('\n\n');
  const startedAt = Date.now();
  const raw = await withAiAudit(event => trace.push({ label: spec.label, ...event }), () => generateReply(
    system,
    [],
    userPrompt,
    {
      temperature: companion.temperature,
      max_tokens: companion.max_tokens,
      top_p: companion.top_p,
    },
    { accountId, skipSearch: Boolean(spec.event) },
  ));
  const reply = safeOutboundReply(raw);
  const issue = spec.event
    ? enterpriseProactiveReplyIssue(spec.event, reply)
    : initiativeReplyIssue(decision, reply);
  results.push({
    order: results.length + 1,
    label: spec.label,
    previewInjected: Boolean(spec.event?.previewInjected),
    basis: spec.event ? {
      statement: spec.event.statement,
      question: spec.event.question,
      evidencePeriod: spec.event.evidencePeriod,
      knowledgeGapId: spec.event.knowledgeGapId,
    } : {
      lifeEvidence: lifeEvidence?.fact || null,
      selectedCandidateType: decision.selectedCandidateType,
    },
    agency: agency ? {
      status: agency.status,
      appraisal: agency.appraisal || null,
      plan: agency.plan || null,
    } : null,
    selectedCandidateType: decision.selectedCandidateType,
    decisionObjective: decision.objective,
    latencyMs: Date.now() - startedAt,
    providerCalls: trace.filter(item => item.label === spec.label && item.stage === 'provider_request').length,
    issue,
    reply,
    segments: reply.split(/\s*(?:\|\||｜｜)\s*/g).map(text => text.trim()).filter(Boolean),
  });
}

const output = {
  kind: 'same-api-isolated-proactive-three-preview',
  generatedAt: new Date().toISOString(),
  provider: process.env.CHAT_PROVIDER || 'configured-provider',
  model: process.env.CHAT_MODEL || 'configured-model',
  companionId,
  accountId,
  dateKey: dailyKey,
  currentMinute: nowMinute,
  workCandidate: workEvent ? 'current-gap-copied-into-isolated-preview' : 'no-open-operator-gap',
  noOutboundSender: true,
  productionDatabaseUntouched: true,
  results,
  trace,
  limitations: [
    'three candidates are rendered sequentially in a disposable snapshot; real scheduler timing is not advanced',
    'the work candidate is copied from the current open workbench gap to satisfy the requested business branch without creating a production event',
    'model output remains stochastic and is a preview, not a guaranteed future transcript',
  ],
};
const out = process.env.AGENCY_PREVIEW_OUT || '/tmp/xiyu-proactive-three-preview.json';
fs.writeFileSync(out, JSON.stringify(output, null, 2));
console.log(JSON.stringify(output, null, 2));
db.close();
