import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xiyu-agency-cycle-'));
process.env.DB_PATH = path.join(root, 'bot.db');
const { getDb, listAgencyIntentions, listAgencyFeedback, updateAgencyAction, commitAgencyReceipt, getAgencyAction } = await import('../src/db.mjs');
const { runAgencyCycle } = await import('../src/proactive.mjs');

const db = getDb();
const row = db.prepare('INSERT INTO companions (user_id, bot_id, name) VALUES (NULL, ?, ?)').run('cycle-bot', '循环角色');
const companionId = Number(row.lastInsertRowid);
const responses = [
  { shouldAct: true, domain: 'work', desiredChange: '确认东大店销售与客流口径并推进判断', appraisalSummary: '已有销售和客流事实，但统计范围影响结论', basisRefs: ['sales:2026-09-02', 'traffic:2026-09-02'], priorityClass: 'high', confidence: 0.9, needsUserInput: true, reconsiderAfterMinutes: 30 },
  { actionType: 'contact_text', strategySummary: '先交付已发现的事实，再只问客流统计范围', inputRefs: ['traffic:2026-09-02'], expectedEffect: '口径确认后继续计算转化', needsUserInput: true, completionCriteria: ['问题送达', '用户回答后给出改变了什么判断'], nextIfAnswered: 'continue_intention', nextIfUnanswered: 'wait_for_new_evidence', notBeforeMinutes: 0, expiresAfterMinutes: 120, dedupKey: 'dongda-traffic-scope-v1', shouldContact: true },
];
let calls = 0;
const fakeExtract = async (_system, userContent) => ({ ok: true, text: JSON.stringify(responses[calls++ % 2]), usage: { prompt_tokens: 1, completion_tokens: 1 }, provider: 'fake', model: 'fixture', requestId: `fixture-${calls}`, attempts: 1, fallback: false, error: null, latencyMs: 1 });

const legacy = await runAgencyCycle({ accountId: 1, companionId, mode: 'legacy', deps: { extractStructuredInfoDetailed: fakeExtract } });
assert.equal(legacy.status, 'legacy');
assert.equal(calls, 0);

const shadow = await runAgencyCycle({ accountId: 1, companionId, mode: 'shadow', trigger: 'business_event', decision: { selectedCandidateType: 'business_delivery', action: 'deliver_grounded_next_step' }, snapshot: { evidence: ['sales:2026-09-02', 'traffic:2026-09-02'] }, deps: { extractStructuredInfoDetailed: fakeExtract, now: '2026-09-07T10:00:00.000Z' } });
assert.equal(shadow.status, 'prepared');
assert.equal(shadow.calls, 2);
assert.equal(shadow.action.actionType, 'contact_text');
assert.equal(shadow.intention.state, 'ready');

let executed = 0;
const enabled = await runAgencyCycle({ accountId: 1, companionId, mode: 'enabled', allowContact: true, decision: { selectedCandidateType: 'business_delivery', action: 'deliver_grounded_next_step' }, snapshot: { evidence: ['sales:2026-09-02', 'traffic:2026-09-02'] }, deps: { extractStructuredInfoDetailed: fakeExtract, now: '2026-09-07T10:01:00.000Z', executeContactAction: async () => { executed += 1; } } });
assert.equal(enabled.status, 'contact_ready');
assert.equal(executed, 1);
assert.equal(enabled.intention.state, 'ready');
const sending = updateAgencyAction(enabled.action.id, { accountId: 1, companionId, expectedVersion: enabled.action.version, state: 'sending' });
assert.ok(sending);
const receipt = commitAgencyReceipt({
  accountId: 1,
  companionId,
  intentionId: enabled.intention.id,
  actionId: enabled.action.id,
  intentionVersion: enabled.intention.version,
  actionVersion: sending.version,
  receipt: { state: 'delivered', providerMessageIds: ['fixture-contact-1'], resultRefs: [{ kind: 'text', delivered: true }] },
});
assert.equal(receipt.status, 'committed');
assert.equal(receipt.intention.state, 'waiting_user');
assert.equal(getAgencyAction(enabled.action.id, { accountId: 1, companionId }).state, 'delivered');
assert.equal(listAgencyIntentions({ accountId: 1, companionId }).length, 1);
assert.equal(listAgencyFeedback({ accountId: 1, companionId }).length, 0);

const failed = await runAgencyCycle({ accountId: 1, companionId, mode: 'shadow', deps: { extractStructuredInfoDetailed: async () => ({ ok: false, fallback: false, error: 'fixture_failure' }) } });
assert.equal(failed.status, 'inconclusive');
assert.equal(failed.error, 'appraisal_provider_failure');

const lookupCompanion = Number(db.prepare('INSERT INTO companions (user_id, bot_id, name) VALUES (NULL, ?, ?)').run('lookup-bot', '查询角色').lastInsertRowid);
let lookupCalls = 0;
const lookupResponses = [
  { shouldAct: true, domain: 'work', desiredChange: '读取东坝店最新可用经营事实', appraisalSummary: '需要先查资料再决定是否联系', basisRefs: ['source:event-9754'], priorityClass: 'high', confidence: 0.95, needsUserInput: false, reconsiderAfterMinutes: 5 },
  { actionType: 'lookup', strategySummary: '读取事件对应知识并保留来源与时间', inputRefs: ['source:event-9754'], expectedEffect: '下一轮能基于新证据交付判断', needsUserInput: false, completionCriteria: ['工具证据写回当前动念'], nextIfAnswered: 'continue_intention', nextIfUnanswered: 'wait_for_new_evidence', notBeforeMinutes: 0, expiresAfterMinutes: 120, dedupKey: 'lookup-event-9754', shouldContact: false },
  { actionType: 'contact_text', strategySummary: '交付刚查到的东坝店客流和销售事实，说明来源后给出一个可执行下一步', inputRefs: ['tool_result:lookup'], expectedEffect: '用户得到有来源的判断', needsUserInput: false, completionCriteria: ['事实和下一步送达'], nextIfAnswered: 'continue_intention', nextIfUnanswered: 'wait_for_new_evidence', notBeforeMinutes: 0, expiresAfterMinutes: 120, dedupKey: 'deliver-event-9754', shouldContact: true },
];
const lookupResult = await runAgencyCycle({
  accountId: 1,
  companionId: lookupCompanion,
  mode: 'shadow',
  decision: { selectedCandidateType: 'business_delivery', enterpriseEvent: { id: '9754' } },
  snapshot: { evidence: ['source:event-9754'] },
  deps: {
    extractStructuredInfoDetailed: async () => ({ ok: true, text: JSON.stringify(lookupResponses[lookupCalls++]), usage: {}, fallback: false }),
    executeLookup: async () => ({ status: 'complete', resultRefs: [{ kind: 'enterprise_knowledge', source: 'workbench', summary: { venue: '东坝店', reception_traffic: 201, box_office_total: 15951.1 } }] }),
  },
});
assert.equal(lookupResult.status, 'prepared');
assert.equal(lookupResult.calls, 3);
assert.equal(lookupResult.action.actionType, 'contact_text');
assert.equal(lookupResult.action.state, 'planned');
assert.ok(lookupResult.intention.basisRefs.some(ref => String(ref).includes('reception_traffic')));
assert.ok(lookupResult.intention.basisRefs.some(ref => String(ref).includes('box_office_total')));
assert.match(lookupResult.promptBinding.promptVersion, /^agency-production-/);

async function runToolContinuationFixture({ botId, actionType, toolStatus = 'complete', capabilities = {}, toolResult }) {
  const fixtureCompanion = Number(db.prepare('INSERT INTO companions (user_id, bot_id, name) VALUES (NULL, ?, ?)').run(botId, botId).lastInsertRowid);
  let index = 0;
  const fixtureResponses = [
    { shouldAct: true, domain: 'work', desiredChange: `${actionType}后给出可执行的新判断`, appraisalSummary: '这是已到期的本职关切', basisRefs: [`responsibility:${actionType}`], priorityClass: 'normal', confidence: 0.9, needsUserInput: false, reconsiderAfterMinutes: 15 },
    { actionType, strategySummary: `先完成${actionType}并保留来源`, inputRefs: [`responsibility:${actionType}`], expectedEffect: '得到新证据', needsUserInput: false, completionCriteria: ['工具完成'], nextIfAnswered: 'continue', nextIfUnanswered: 'wait', notBeforeMinutes: 0, expiresAfterMinutes: 120, dedupKey: `${botId}-tool`, shouldContact: false },
    { actionType: 'contact_text', strategySummary: '交付新证据、边界和一个下一步', inputRefs: [`tool_result:${actionType}`], expectedEffect: '用户能直接采取行动', needsUserInput: false, completionCriteria: ['交付完成'], nextIfAnswered: 'continue', nextIfUnanswered: 'complete', notBeforeMinutes: 0, expiresAfterMinutes: 120, dedupKey: `${botId}-deliver`, shouldContact: true },
  ];
  return runAgencyCycle({
    accountId: 1, companionId: fixtureCompanion, mode: 'shadow',
    decision: { selectedCandidateType: actionType === 'research' ? 'external_research' : 'business_delivery' },
    snapshot: { responsibilities: [{ kind: actionType, due: true }], capabilities },
    deps: {
      extractStructuredInfoDetailed: async () => ({ ok: true, text: JSON.stringify(fixtureResponses[index++]), usage: {}, fallback: false }),
      ...(actionType === 'lookup' ? { executeLookup: async () => ({ status: toolStatus, resultRefs: toolResult }) } : {}),
      ...(actionType === 'research' ? { executeResearch: async () => ({ status: toolStatus, resultRefs: toolResult }) } : {}),
    },
  });
}

const partialResult = await runToolContinuationFixture({
  botId: 'partial-lookup-bot', actionType: 'lookup', toolStatus: 'partial', capabilities: { lookup: true, contact_text: true },
  toolResult: [{ kind: 'enterprise_knowledge', status: 'partial', summary: { venue: '中影', box_office_total: 633.6 }, refs: ['feishu:sales:2026-09-12'] }],
});
assert.equal(partialResult.status, 'prepared');
assert.equal(partialResult.action.actionType, 'contact_text');
assert.ok(partialResult.intention.basisRefs.some(ref => ref.includes('633.6')));

const researchResult = await runToolContinuationFixture({
  botId: 'research-bot', actionType: 'research', capabilities: { research: true, contact_text: true },
  toolResult: [{ kind: 'external_research', title: '行业新案例', url: 'https://example.test/case', publishedAt: '2026-09-13' }],
});
assert.equal(researchResult.status, 'prepared');
assert.equal(researchResult.action.actionType, 'contact_text');
assert.ok(researchResult.intention.basisRefs.some(ref => ref.includes('example.test')));

const mediaCompanion = Number(db.prepare('INSERT INTO companions (user_id, bot_id, name) VALUES (NULL, ?, ?)').run('media-bot', '图片角色').lastInsertRowid);
let mediaIndex = 0;
const mediaResponses = [
  { shouldAct: true, domain: 'personal', desiredChange: '用有情节的真实照片引出一次轻松互动', appraisalSummary: '已有当日照片素材，图片比文字更适合', basisRefs: ['photo:today:1'], priorityClass: 'normal', confidence: 0.88, needsUserInput: false, reconsiderAfterMinutes: 60 },
  { actionType: 'contact_media', strategySummary: '发一张已有的情节照片并留一个容易短答的话头', inputRefs: ['photo:today:1'], expectedEffect: '提高自然回复意愿', needsUserInput: false, completionCriteria: ['图文送达'], nextIfAnswered: 'continue', nextIfUnanswered: 'cool_down', notBeforeMinutes: 0, expiresAfterMinutes: 60, dedupKey: 'media-today-1', shouldContact: true },
];
const mediaResult = await runAgencyCycle({ accountId: 1, companionId: mediaCompanion, mode: 'shadow', decision: { selectedCandidateType: 'story_photo' }, snapshot: { capabilities: { contact_media: true }, evidence: ['photo:today:1'] }, deps: { extractStructuredInfoDetailed: async () => ({ ok: true, text: JSON.stringify(mediaResponses[mediaIndex++]), usage: {}, fallback: false }) } });
assert.equal(mediaResult.status, 'prepared');
assert.equal(mediaResult.action.actionType, 'contact_media');

console.log(JSON.stringify({ status: 'passed', calls, executed, intentionId: enabled.intention.id, lookupIntentionId: lookupResult.intention.id, partialIntentionId: partialResult.intention.id, researchIntentionId: researchResult.intention.id, mediaIntentionId: mediaResult.intention.id, root }));
