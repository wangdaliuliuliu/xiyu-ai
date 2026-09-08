/** Diagnostic contract audit. Synthetic DB, injected model JSON, no outbound sender.
 * A failed assertion is evidence of nonconformance, not an acceptance pass.
 * node scripts/agency_conformance_audit.mjs
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';

const root = process.cwd();
const isolated = fs.mkdtempSync(path.join(os.tmpdir(), 'xiyu-conformance-'));
process.env.DB_PATH = path.join(isolated, 'bot.db');
process.env.LOG_DIR = path.join(isolated, 'logs');
process.env.XIYU_WORKBENCH_CONTEXT_URL = '';
process.env.XIYU_WORKBENCH_OUTBOX_PATH = path.join(isolated, 'outbox.json');
process.env.XIYU_WORKBENCH_ACTIVE_TASKS_PATH = path.join(isolated, 'tasks.json');
const store = await import('../src/db.mjs');
const protocol = await import('../src/agency_protocol.mjs');
const { runAgencyCycle } = await import('../src/proactive.mjs');
const { buildEnterpriseFactReply } = await import('../src/enterprise_context.mjs');
const db = store.getDb();
const companionId = Number(db.prepare('INSERT INTO companions (user_id, bot_id, name) VALUES (NULL, ?, ?)').run('audit', '合成成年角色').lastInsertRowid);
const owner = { accountId: 991, companionId };
const checks = [];
const check = (id, requirement, expected, actual) => checks.push({ id, requirement, status: JSON.stringify(expected) === JSON.stringify(actual) ? 'pass' : 'fail', expected, actual });
const make = (key, state = 'ready') => store.createAgencyIntention({ ...owner, semanticKey: key, state, desiredChange: key, basisRefs: ['fixture:1'] });
const appraisal = { shouldAct: true, domain: 'work', desiredChange: '查清合成门店当日销售额', basisRefs: ['fixture:1'], confidence: 0.9, priorityClass: 'normal', reconsiderAfterMinutes: 60 };
const plan = { actionType: 'contact_text', strategySummary: '交付已核对结果', inputRefs: ['fixture:1'], dedupKey: 'audit-contact', needsUserInput: false };

check('schema-empty', '空 JSON 必须是 schema failure', false, protocol.validateAppraisalProposal({}).ok);
const facts = [{ ref: 'fixture:1', status: 'verified', value: 12000 }];
check('snapshot-facts', '规范中的 facts 不能在组装时丢弃', facts, protocol.normalizeContextSnapshot({ facts }).facts ?? null);
check('unsupported-media', '无媒体能力不得接受 contact_media', false, protocol.validatePlanProposal({ ...plan, actionType: 'contact_media' }, { capabilities: { contact_media: false } }).ok);
const i = make('cas');
const next = store.updateAgencyIntention(i.id, { ...owner, expectedVersion: i.version, state: 'active' });
check('cas', '旧版本不得覆盖新版本', null, store.updateAgencyIntention(i.id, { ...owner, expectedVersion: i.version, state: 'ready' }));
check('owner-read', '显式异租户读取须拒绝', null, store.getAgencyIntention(i.id, { accountId: 992, companionId }));
const cross = store.recordAgencyFeedback({ accountId: 992, companionId, intentionId: i.id, sourceMessageId: 'cross-owner', kind: 'answer' });
check('cross-owner-feedback', '反馈关联的 intention 必须属于同一账号', false, Boolean(cross));
const terminal = make('terminal', 'completed');
check('terminal-transition', '终态不能被任意改回等待', false, Boolean(store.updateAgencyIntention(terminal.id, { ...owner, expectedVersion: terminal.version, state: 'waiting_user' })));
check('mandatory-cas', '更新动念必须携带 expectedVersion', false, Boolean(store.updateAgencyIntention(next.id, { ...owner, state: 'ready' })));

const fake = responsePlan => {
  let n = 0;
  return async () => ({ ok: true, fallback: false, text: JSON.stringify(n++ % 2 ? responsePlan : appraisal), provider: 'injected', model: 'diagnostic-only' });
};
const contact = await runAgencyCycle({ ...owner, mode: 'enabled', allowContact: true, snapshot: { evidence: ['fixture:1'] }, deps: { extractStructuredInfoDetailed: fake(plan) } });
check('before-delivery-state', '未送达且无需回应时不得 waiting_user', false, contact.intention?.state === 'waiting_user');
const lookup = await runAgencyCycle({ ...owner, mode: 'enabled', snapshot: { evidence: ['fixture:1'], capabilities: { lookup: true } }, deps: { extractStructuredInfoDetailed: fake({ ...plan, actionType: 'lookup', dedupKey: 'audit-lookup' }) } });
check('lookup-executed', '查询必须执行并留下结果或明确故障，不能只有 planned', false, lookup.action?.state === 'planned' && lookup.action?.resultRefs?.length === 0);

const finishedReady = make('already-done', 'ready');
const donePlanned = store.createAgencyAction({ ...owner, intentionId: finishedReady.id, dedupKey: 'done-action', actionType: 'contact_text', needsUserInput: false, state: 'planned', expiresAt: '2026-09-07T00:00:00Z' });
const doneSending = store.updateAgencyAction(donePlanned.id, { ...owner, expectedVersion: donePlanned.version, state: 'sending' });
const doneReceipt = store.commitAgencyReceipt({ ...owner, intentionId: finishedReady.id, actionId: donePlanned.id, intentionVersion: finishedReady.version, actionVersion: doneSending.version, receipt: { state: 'delivered', providerMessageIds: ['done-message'], resultRefs: [{ kind: 'text', delivered: true }] } });
const finished = store.updateAgencyIntention(finishedReady.id, { ...owner, expectedVersion: doneReceipt.intention.version, state: 'completed', completionEvidence: [{ actionId: donePlanned.id, providerMessageId: 'done-message' }] });
const delivered = doneReceipt.action;
await runAgencyCycle({ ...owner, mode: 'shadow', deps: { now: '2026-09-08T00:00:00Z', extractStructuredInfoDetailed: async () => ({ ok: true, text: JSON.stringify({ shouldAct: false }) }) } });
check('no-response-terminal', '无需回复的已完成交付不得被到期扫描复活', 'completed', store.getAgencyIntention(finished.id, owner).state);
check('no-response-observation', '无需回复的动作不应生成未回复事件', 0, store.listAgencyFeedback({ ...owner, intentionId: finished.id }).filter(x => x.action_id === delivered.id).length);

const summary = { venue: '东大店', periodStart: '2026-09-02', periodEnd: '2026-09-02', core: { box_office_total: 12000 }, sourceTitle: '合成销售表' };
const query = '查一下9月2日东大店销售额是多少';
const conflict = buildEnterpriseFactReply({ message: query, route: { intent: { timeRange: '2026-09-02' } }, context: { items: [{ id: 'a', summary }, { id: 'b', summary: { ...summary, core: { box_office_total: 15000 }, sourceTitle: '第二份合成销售表' } }] } });
check('conflicting-facts', '两个未定权威的来源冲突不能直接选第一份报数', false, conflict?.matched === true);
const fact = buildEnterpriseFactReply({ message: query, context: { items: [{ id: 'old', summary: { ...summary, periodStart: '2026-08-01', periodEnd: '2026-08-07' } }] } });
check('date-without-router', '路由时间丢失时不能用异日记录回答明确日期', false, fact?.matched === true);

const bot = fs.readFileSync(path.join(root, 'src/bot.mjs'), 'utf8');
const proactive = fs.readFileSync(path.join(root, 'src/proactive.mjs'), 'utf8');
const firstUse = proactive.indexOf('accountId: proactiveBinding?.account_id');
check('binding-declaration', '主动入口读取 binding 前必须已初始化（静态定位）', true, proactive.indexOf('const proactiveBinding =') < firstUse);
check('feedback-owner', '反馈不能用 companion.user_id 代替 binding.account_id（静态定位）', false, bot.includes('listAgencyIntentions({ accountId: companion.user_id'));

const files = ['src/bot.mjs', 'src/proactive.mjs', 'src/db.mjs', 'src/agency_protocol.mjs', 'src/enterprise_context.mjs', 'src/playground.mjs', 'scripts/agency_acceptance.mjs'];
const report = { at: new Date().toISOString(), kind: 'diagnostic-not-release', isolation: { directory: isolated, database: process.env.DB_PATH, model: 'injected', realOutboundUsed: false }, checks, sourceHashes: Object.fromEntries(files.map(f => [f, crypto.createHash('sha256').update(fs.readFileSync(path.join(root, f))).digest('hex')])) };
report.summary = { total: checks.length, passed: checks.filter(x => x.status === 'pass').length, failed: checks.filter(x => x.status === 'fail').length, releaseGate: 'blocked' };
const out = path.join(root, 'docs/validation/2026-09-08/conformance-audit');
fs.mkdirSync(out, { recursive: true });
fs.writeFileSync(path.join(out, 'deterministic.json'), JSON.stringify(report, null, 2));
console.log(JSON.stringify({ ...report.summary, checks }, null, 2));
db.close();
process.exitCode = report.summary.failed ? 1 : 0;
