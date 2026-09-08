/**
 * Read-only workbench event + isolated agency-chain probe.
 * It reads a pending event for a synthetic actor, then runs the deployed
 * appraisal/plan chain against an isolated SQLite database with fixture
 * structured responses. No production database or outbound sender is used.
 */
import 'dotenv/config';
import fs from 'node:fs';

process.env.XIYU_WORKBENCH_CONTEXT_URL = 'http://127.0.0.1:4175';
const token = process.env.XIYU_WORKBENCH_CONTEXT_TOKEN || '';
const eventResponse = await fetch('http://127.0.0.1:4175/api/intelligence/events?status=pending&actorId=9001', {
  headers: { 'x-xiyu-token': token, accept: 'application/json' },
});
const eventPayload = await eventResponse.json();
const event = (eventPayload.items || []).find(item => item.actorId === '9001');
if (!event) throw new Error('no isolated event');

const dbPath = '/tmp/xiyu-selection-probe-20260908.db';
for (const suffix of ['', '-wal', '-shm']) {
  try { fs.unlinkSync(dbPath + suffix); } catch {}
}
process.env.DB_PATH = dbPath;
const { getDb } = await import('../src/db.mjs');
const { runAgencyCycle } = await import('../src/proactive.mjs');
const db = getDb();
const companionId = Number(db.prepare('INSERT INTO companions (user_id, bot_id, name) VALUES (NULL, ?, ?)')
  .run('isolated-selection-probe', '溪语').lastInsertRowid);
const responses = [
  {
    shouldAct: true,
    domain: 'work',
    desiredChange: event.decisionImpact || event.statement,
    appraisalSummary: event.statement,
    basisRefs: [event.id, event.question],
    priorityClass: event.priority || 'high',
    confidence: 0.95,
    needsUserInput: true,
    reconsiderAfterMinutes: 30,
  },
  {
    actionType: 'contact_text',
    strategySummary: '先说清已确认的业务缺口，再只问一个最小问题',
    inputRefs: [event.id],
    expectedEffect: '用户回答后能推进下一步经营判断',
    needsUserInput: true,
    completionCriteria: ['问题送达', '用户回答后说明改变了什么判断'],
    nextIfAnswered: 'continue_intention',
    nextIfUnanswered: 'wait_for_new_evidence',
    notBeforeMinutes: 0,
    expiresAfterMinutes: 120,
    dedupKey: 'isolated-selection-probe-v1',
    shouldContact: true,
  },
];
let calls = 0;
const fakeExtract = async () => ({
  ok: true,
  text: JSON.stringify(responses[calls++]),
  usage: { prompt_tokens: 1, completion_tokens: 1 },
  provider: 'fixture', model: 'fixture', requestId: `isolated-selection-${calls}`,
  attempts: 1, fallback: false, error: null, latencyMs: 1,
});
const result = await runAgencyCycle({
  accountId: 9001,
  companionId,
  mode: 'shadow',
  trigger: 'business_event',
  decision: { selectedCandidateType: 'knowledge_or_work_question', action: 'ask_one_grounded_question', enterpriseEvent: event },
  snapshot: { evidence: [event.statement, event.question], businessContext: event },
  deps: { extractStructuredInfoDetailed: fakeExtract, now: '2026-09-08T05:42:00.000Z' },
});
console.log(JSON.stringify({
  event: {
    id: event.id,
    statement: event.statement,
    question: event.question,
    evidencePeriod: event.evidencePeriod,
    occurredAt: event.occurredAt,
    createdAt: event.createdAt,
    taskType: event.taskType,
    priority: event.priority,
  },
  chain: {
    status: result.status,
    mode: result.mode,
    calls: result.calls,
    appraisal: result.appraisal,
    plan: result.plan,
    intention: result.intention ? {
      state: result.intention.state,
      desiredChange: result.intention.desiredChange,
      basisRefs: result.intention.basisRefs,
    } : null,
    action: result.action ? {
      actionType: result.action.actionType,
      strategySummary: result.action.strategySummary,
      state: result.action.state,
    } : null,
  },
  isolatedDatabase: dbPath,
}, null, 2));
db.close();
