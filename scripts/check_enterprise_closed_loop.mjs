/** Real HTTP lifecycle checks in a disposable copy of the local enterprise data.
 * --live additionally calls configured models. Never sends WeChat or applies to source data.
 * Node 22: node scripts/check_enterprise_closed_loop.mjs [--live]
 */
import 'dotenv/config';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import Database from 'better-sqlite3';

const workbench = process.env.PROBE_WORKBENCH_ROOT || 'E:/Yuanqu-Operations-Workbench/weekly-ops-entry';
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'enterprise-closed-loop-'));
const runtime = path.join(root, 'runtime');
fs.mkdirSync(runtime);
for (const name of fs.readdirSync(path.join(workbench, 'data/runtime-state')).filter(name => name.endsWith('.json'))) {
  fs.copyFileSync(path.join(workbench, 'data/runtime-state', name), path.join(runtime, name));
}
const profileFile = path.join(root, 'profile.json');
fs.copyFileSync(path.join(workbench, 'data/strategy-project-profile.json'), profileFile);
process.env.WEEKLY_OPS_RUNTIME_STATE_DIR = runtime;
process.env.STRATEGY_PROFILE_PATH = profileFile;
process.env.WEEKLY_OPS_PORT = '0';
process.env.XIYU_WORKBENCH_ACTIVE_TASKS_PATH = path.join(root, 'active-tasks.json');
process.env.XIYU_WORKBENCH_OUTBOX_PATH = path.join(root, 'outbox.json');
process.env.XIYU_ENTERPRISE_PROACTIVE_ENABLED = 'true';
process.env.XIYU_WORKBENCH_TIMEOUT_MS = '5000';
const productionDb = new Database(process.env.DB_PATH || 'data/bot.db', { readonly: true });
await productionDb.backup(path.join(root, 'bot.db'));
productionDb.close();
process.env.DB_PATH = path.join(root, 'bot.db');

const backend = await import(pathToFileURL(path.join(workbench, 'backend/feishu-sync-server.mjs')).href);
await new Promise(resolve => backend.server.listen(0, '127.0.0.1', resolve));
const base = `http://127.0.0.1:${backend.server.address().port}`;
process.env.XIYU_WORKBENCH_CONTEXT_URL = base;
process.env.XIYU_WORKBENCH_CONTEXT_TOKEN = process.env.XIYU_CONTEXT_TOKEN || '';
const bridge = await import('../src/enterprise_context.mjs');
const evidence = { root, live: process.argv.includes('--live'), startedAt: new Date().toISOString(), checks: [], samples: {} };
const record = (name, value = true) => { evidence.checks.push({ name, value }); console.log(name, JSON.stringify(value)); };
const persist = () => fs.writeFileSync(path.join(root, 'report.json'), JSON.stringify(evidence, null, 2));
const read = kind => { const raw = JSON.parse(fs.readFileSync(path.join(runtime, `${kind}.json`), 'utf8')); return raw.__runtimeState ? raw.data : raw; };
const write = (kind, data) => fs.writeFileSync(path.join(runtime, `${kind}.json`), JSON.stringify({ __runtimeState: 1, revision: 1, data }));
const request = async (route, method = 'GET', body) => {
  const response = await fetch(base + route, { method, headers: { 'content-type': 'application/json', 'x-xiyu-token': process.env.XIYU_CONTEXT_TOKEN || '' }, body: body === undefined ? undefined : JSON.stringify(body) });
  const result = await response.json();
  assert.ok(response.ok, `${route}: ${JSON.stringify(result)}`);
  return result;
};
const scope = { projectId: 'yuanqu-vr', venueNames: ['东坝'] };
const nowDay = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(new Date());
const eventRefresh = (extra = {}) => request('/api/intelligence/events/refresh', 'POST', { projectId: scope.projectId, venueNames: scope.venueNames, actorId: '', purposes: ['knowledge_acquisition'], discoverGaps: false, ...extra });
const retrieve = (venue, question) => request('/api/knowledge/retrieve', 'POST', { projectId: scope.projectId, scope: { projectId: scope.projectId, venueNames: [venue] }, query: { question }, limits: { maxItems: 40, maxCharacters: 16000 } });
try {
  write('knowledge', { gaps: [
    { id: 'critical-gap', knowledgeTrack: 'enterprise', dimensionId: 'capacity', statement: '接待产能限制', question: '周末最多能同时带几个人？', priority: 'high', valueScore: 35, scope, status: 'open', sourceRefs: ['capacity-source'], acquisitionRoute: 'operator' },
    { id: 'latest-news', statement: '行业近期新活动', question: '最新竞品活动', priority: 'high', valueScore: 50, scope, status: 'open', acquisitionRoute: 'external_research' },
    { id: 'minor-gap', knowledgeTrack: 'enterprise', dimensionId: 'identity', statement: '企业定位', question: '哪些业务明确不做？', priority: 'low', valueScore: 5, scope, status: 'open', acquisitionRoute: 'operator' },
  ], implicitItems: [] });
  write('intelligence', { items: [] }); write('events', {}); // file uses enterprise-events name below
  fs.renameSync(path.join(runtime, 'events.json'), path.join(runtime, 'enterprise-events.json'));
  const events = await eventRefresh();
  assert.equal(events.created[0].knowledgeGapId, 'critical-gap');
  assert.deepEqual(events.created[0].sourceRefs, ['capacity-source']);
  record('priority_and_acquisition_route');
  const event = events.created[0];
  await bridge.acknowledgeEnterpriseEvent(event.id);
  const activeTask = bridge.rememberActiveEnterpriseTask({ companionId: 'probe', event });
  const route = { conversationType: 'work', writebackPotential: true, workSegments: ['周末现场只有一名带场员，一场最多带六人。'], scope };
  const partial = await bridge.extractWorkIntelligence({ route, message: route.workSegments[0], activeTask, companionId: 'probe' }, {
    extract: async () => JSON.stringify({ candidates: [{ statement: '缺口只回答了一部分', answersActiveTask: true, satisfiesActiveTask: true, missingInformation: ['人数尚未核实'] }] }),
    write: async candidate => ({ candidate }),
  });
  assert.equal(partial.candidates[0].knowledgeGapId, '');
  assert.ok(bridge.getActiveEnterpriseTask({ companionId: 'probe' }));
  record('partial_answer_keeps_question_open');
  const result = await bridge.extractWorkIntelligence({ route, message: route.workSegments[0], activeTask, companionId: 'probe', conversationId: 'isolated-probe', turnId: 'capacity' }, {
    extract: async () => JSON.stringify({ candidates: [{ candidateType: 'operating_fact_candidate', scope: { venueNames: [], venueIds: [], projectId: '' }, statement: route.workSegments[0], answersActiveTask: true, satisfiesActiveTask: true, source: { quote: route.workSegments[0] } }] }),
  });
  assert.equal(result.savedCount, 1);
  const candidate = result.candidates[0];
  assert.deepEqual(candidate.scope.venueNames, ['东坝']);
  assert.equal(read('knowledge').gaps[0].status, 'review_pending');
  assert.equal(bridge.getActiveEnterpriseTask({ companionId: 'probe' }), null);
  assert.ok(!(await retrieve('东坝', '带场员六人')).context.items.some(item => item.summary?.includes('一名带场员')));
  record('pending_not_reused_and_scoped_answer');
  await request(`/api/intelligence/candidates/${candidate.id}`, 'PUT', { reviewStatus: 'rejected' });
  assert.equal(read('knowledge').gaps[0].status, 'open');
  const rejectedApply = await fetch(base + `/api/intelligence/candidates/${candidate.id}/apply`, { method: 'POST', headers: { 'content-type': 'application/json', 'x-xiyu-token': process.env.XIYU_CONTEXT_TOKEN || '' }, body: '{}' });
  assert.equal(rejectedApply.status, 400);
  record('rejection_reopens_gap_and_blocks_apply');
  await request(`/api/intelligence/candidates/${candidate.id}`, 'PUT', { reviewStatus: 'accepted' });
  const beforeDaily = backend.dailyContext({ date: nowDay, venue: '东坝' });
  const applied = await request(`/api/intelligence/candidates/${candidate.id}/apply`, 'POST', { target: 'operating_fact' });
  assert.equal(read('knowledge').gaps[0].status, 'confirmed');
  assert.equal((await request('/api/intelligence/events?status=acknowledged')).items[0].knowledgeGapId, 'critical-gap');
  const afterDaily = backend.dailyContext({ date: nowDay, venue: '东坝' });
  assert.notEqual(beforeDaily.contextFingerprint, afterDaily.contextFingerprint);
  assert.ok(afterDaily.implicitKnowledge.some(item => item.id === applied.application.assetId));
  assert.ok((await retrieve('东坝', '带场员六人')).context.items.some(item => item.id === applied.application.assetId && item.assetType === 'implicit_knowledge'));
  assert.ok(!(await retrieve('中影', '带场员六人')).context.items.some(item => item.id === applied.application.assetId));
  const again = await request(`/api/intelligence/candidates/${candidate.id}/apply`, 'POST', { target: 'operating_fact' });
  assert.equal(again.application.assetId, applied.application.assetId);
  assert.equal(read('knowledge').implicitItems.filter(item => item.id === applied.application.assetId).length, 1);
  record('fact_apply_closes_gap_and_reuses_without_cross_venue_leak');
  const duplicateGap = await backend.refreshKnowledgeGaps({ scope, limit: 4 }, { requestModel: async () => ({ result: { gaps: [{ statement: '同一产能问题的另一种说法', question: '周末最多能同时带几个人？', scope, priority: 'high' }] } }) });
  assert.ok(!duplicateGap.created.some(item => item.question === '周末最多能同时带几个人？'));
  assert.ok(duplicateGap.created.every(item => item.facetId));
  const empty = await backend.refreshKnowledgeGaps({ scope }, { requestModel: async () => ({ result: { gaps: [] } }) });
  assert.ok(['external-model', 'enterprise-blueprint'].includes(empty.generatedBy));
  assert.ok(!empty.created.some(item => item.question === '周末最多能同时带几个人？'));
  record('answered_question_dedup_and_facet_blueprint_fallback');
  assert.ok(bridge.enterpriseProactiveReplyIssue({ evidencePeriod: { historical: true } }, '这周客流下降了'));
  assert.ok(bridge.enterpriseProactiveReplyIssue({ taskType: 'knowledge_gap_followup' }, '我猜大概一半人只是看看'));
  record('historical_and_unsupported_ratio_guard');
  const nextDate = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(new Date(Date.now() + 86400000));
  const nextCreated = (await eventRefresh({ date: nextDate })).created[0];
  assert.notEqual(nextCreated.knowledgeGapId, 'critical-gap');
  assert.ok(read('knowledge').gaps.some(item => item.id === nextCreated.knowledgeGapId && item.status === 'open'));
  record('next_opportunity_skips_resolved_gap');
  if (evidence.live) {
    // Restore the enterprise snapshot before live checks; synthetic answers stay in this copy.
    for (const name of ['workbench', 'intelligence', 'enterprise-events']) {
      fs.copyFileSync(path.join(workbench, `data/runtime-state/${name}.json`), path.join(runtime, `${name}.json`));
    }
    write('knowledge', { gaps: [], implicitItems: [] });
    write('intelligence', { items: [] }); write('enterprise-events', { items: [] });
    const start = Date.now();
    const discovery = await eventRefresh({ discoverGaps: true });
    assert.equal(discovery.discoveryPending, true);
    assert.ok(Date.now() - start < 3000, 'discovery must not block the proactive scheduler');
    record('live_auto_discovery_started_without_blocking');
    let knowledge;
    for (let attempt = 0; attempt < 150; attempt++) {
      await new Promise(resolve => setTimeout(resolve, 1000));
      knowledge = read('knowledge');
      if (Object.keys(knowledge.discovery || {}).length) break;
    }
    assert.equal(Object.values(knowledge.discovery || {})[0]?.generatedBy, 'external-model');
    evidence.samples.gaps = knowledge.gaps;
    persist();
    record('live_gaps', knowledge.gaps.map(item => ({ question: item.question, route: item.acquisitionRoute, priority: item.priority, score: item.valueScore })));
    const generatedEvent = (await eventRefresh()).created[0];
    assert.ok(generatedEvent, 'no operator gap was produced; inspect source tasks in report');
    evidence.samples.event = generatedEvent;
    const { getCompanionById } = await import('../src/db.mjs');
    const companion = getCompanionById(Number(process.env.PROBE_COMPANION_ID || 1));
    assert.ok(companion);
    const { generateReply, extractStructuredInfo } = await import('../src/ai.mjs');
    const { buildSystemPrompt } = await import('../src/companion.mjs');
    const persona = buildSystemPrompt(companion, { promptMode: 'proactive' });
    let opening = await generateReply(persona, [], bridge.buildEnterpriseProactivePrompt(generatedEvent), { max_tokens: 600 }, { companionId: companion.id, skipSearch: true });
    const issue = bridge.enterpriseProactiveReplyIssue(generatedEvent, opening);
    if (issue) opening = await generateReply(persona, [], `${bridge.buildEnterpriseProactivePrompt(generatedEvent)}\n修正：${issue}`, { max_tokens: 600, temperature: 0.4 }, { companionId: companion.id, skipSearch: true });
    assert.equal(bridge.enterpriseProactiveReplyIssue(generatedEvent, opening), '');
    evidence.samples.opening = opening;
    console.log('live opening:', opening); persist();
    record('live_discovery_to_persona_opening');
    await bridge.acknowledgeEnterpriseEvent(generatedEvent.id);
    const liveTask = bridge.rememberActiveEnterpriseTask({ companionId: companion.id, event: generatedEvent });
    const { playgroundChat } = await import('../src/playground.mjs');
    const comfort = await playgroundChat(companion, '我今天累得不想动，先别分析也别问工作了，哄哄我。', { probe: true });
    evidence.samples.comfort = comfort.reply;
    assert.ok(bridge.getActiveEnterpriseTask({ companionId: companion.id }));
    const personal = await bridge.prepareEnterpriseContext({ companionId: companion.id, message: '先不聊工作了，想你了' });
    assert.equal(personal.route.conversationType, 'personal');
    record('live_emotional_turn_keeps_work_question_open', comfort.reply);
    // Clearly synthetic operator answer, only in the disposable clone. Real models process every following stage.
    const fixture = await extractStructuredInfo('你是离线集成测试的数据生成器，只返回 JSON {"answer":"..."}。根据问题生成一段明确、充分的模拟运营者回答，只用于隔离副本，不是实际企业事实。必须回应 expectedAnswer，最多180字。门店和日期必须严格使用 scope 和 evidencePeriod，不得另选年份日期。没有精确计数就给出最小边界允许的观察。', JSON.stringify({ question: generatedEvent.question, expectedAnswer: generatedEvent.expectedAnswer, scope: generatedEvent.scope, evidencePeriod: generatedEvent.evidencePeriod }), { maxTokens: 600, temperature: 0.1 });
    const answer = JSON.parse(fixture.replace(/^```(?:json)?\s*|\s*```$/g, '')).answer;
    evidence.samples.answer = { synthetic: true, text: answer };
    const history = [{ role: 'assistant', content: opening }];
    const prepared = await bridge.prepareEnterpriseContext({ companionId: companion.id, message: answer, history });
    evidence.samples.route = prepared.route; persist();
    assert.equal(prepared.route.replyToActiveTask, true);
    assert.equal(prepared.route.writebackPotential, true);
    const extracted = await bridge.extractWorkIntelligence({ ...prepared, message: answer, history, companionId: companion.id, conversationId: 'isolated-live', turnId: 'live-answer', activeTask: liveTask });
    evidence.samples.extraction = extracted; persist();
    assert.ok(extracted.savedCount > 0, 'live extractor did not save a candidate');
    const sufficient = extracted.candidates.find(item => item.knowledgeGapId === generatedEvent.knowledgeGapId);
    assert.ok(sufficient, 'live answer was not sufficient; inspect extraction');
    assert.deepEqual(sufficient.scope.venueNames, ['东坝']);
    assert.equal(read('knowledge').gaps.find(item => item.id === generatedEvent.knowledgeGapId).status, 'review_pending');
    const prior = backend.dailyContext({ date: nowDay, venue: '东坝' });
    const application = await request(`/api/intelligence/candidates/${sufficient.id}/apply`, 'POST', {});
    assert.equal(read('knowledge').gaps.find(item => item.id === generatedEvent.knowledgeGapId).status, 'confirmed');
    const context = (await retrieve('东坝', sufficient.statement)).context;
    assert.ok(context.items.some(item => item.id === application.application.assetId));
    assert.ok(!(await retrieve('中影', sufficient.statement)).context.items.some(item => item.id === application.application.assetId));
    const daily = backend.dailyContext({ date: nowDay, venue: '东坝' });
    assert.notEqual(daily.contextFingerprint, prior.contextFingerprint);
    const fresh = await request('/api/knowledge/gaps/refresh', 'POST', { scope, limit: 3 });
    evidence.samples.nextGaps = fresh.created;
    assert.equal(fresh.generatedBy, 'external-model');
    assert.ok(!fresh.created.some(item => item.question === generatedEvent.question), 'model recreated the answered question under a new ID');
    const next = await eventRefresh({ date: nextDate });
    assert.ok(!next.created.some(item => item.knowledgeGapId === generatedEvent.knowledgeGapId));
    evidence.samples.nextEvent = next.created;
    record('live_answer_review_apply_retrieval_and_next_discovery');
    const ideas = await backend.dailyModelIdeas(daily, { headline: '根据刚确认的信息修正下一步，历史数据只作背景', evidenceRefs: [application.application.assetId] }, [], 2);
    evidence.samples.ideas = ideas;
    assert.ok(ideas.length > 0);
    const workPrompt = buildSystemPrompt(companion, { promptMode: 'reply', enterpriseContext: bridge.formatEnterpriseContext(context) }) + bridge.enterpriseResponseDirective({ route: { conversationType: 'work', interactionIntent: 'delegate' }, context });
    const handoff = await generateReply(workPrompt, [{ role: 'user', content: answer }], '基于刚才的信息，给我一份可以直接交给另一个Agent执行的任务说明。先做最能改变经营判断的一件事，写清楚输入、步骤、交付物和验收，未确认的资源不要当成有。', { max_tokens: 2200 }, { companionId: companion.id, skipSearch: true });
    evidence.samples.handoff = handoff; persist();
    record('live_knowledge_reused_in_ideas_and_agent_handoff');
  }
  evidence.status = 'passed';
} catch (error) {
  evidence.status = 'failed'; evidence.error = error.stack; process.exitCode = 1; console.error(error);
} finally {
  evidence.finishedAt = new Date().toISOString(); persist();
  backend.server.closeAllConnections(); await new Promise(resolve => backend.server.close(resolve));
  console.log('EVIDENCE', path.join(root, 'report.json'));
}
