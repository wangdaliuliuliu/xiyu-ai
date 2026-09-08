import 'dotenv/config';
import assert from 'node:assert/strict';
import { buildEnterpriseFactReply, enterpriseResponseDirective, extractWorkIntelligence } from '../src/enterprise_context.mjs';

const context = { items: [{ id: 'fixture', summary: { venue: '东坝', periodStart: '2026-08-15', periodEnd: '2026-08-21', core: { box_office_total: 123, reception_traffic: null } } }] };
assert.equal(buildEnterpriseFactReply({ message: '东坝昨天销售额多少', context, now: new Date('2026-08-22T12:00:00Z') }).matched, false);
assert.equal(buildEnterpriseFactReply({ message: '东坝接待客流多少', context }).matched, false);
assert.equal(buildEnterpriseFactReply({ message: '东坝销售额多少', context }).matched, true);
assert.ok(enterpriseResponseDirective({ route: { conversationType: 'work', interactionIntent: 'support' } }).includes('support'));
assert.ok(!enterpriseResponseDirective({ route: { conversationType: 'personal' } }));
assert.ok(enterpriseResponseDirective({ route: { conversationType: 'work' }, context: { items: [] } }).includes('检索成功'));
assert.ok(enterpriseResponseDirective({ route: { conversationType: 'work' } }).includes('连接不可用'));
if (process.env.XIYU_WORKBENCH_CONTEXT_URL) {
  const result = await extractWorkIntelligence({ route: { conversationType: 'work', writebackPotential: true, workSegments: ['另一件事情'], scope: {} }, message: '另一件事情', activeTask: { taskId: 'task-test', knowledgeGapId: 'gap-test' } }, {
    extract: async () => JSON.stringify({ candidates: [{ statement: '与原追问无关的信息', answersActiveTask: false }] }),
    write: async candidate => ({ candidate }),
  });
  assert.equal(result.candidates[0].knowledgeGapId, '');
  assert.equal(result.candidates[0].conversationTaskRef, '');
}
console.log('continuity deterministic checks passed');

// Explicit opt-in: use configured persona and external model; probe does not save conversation or candidates.
if (process.argv.includes('--live')) {
  const { getCompanionById } = await import('../src/db.mjs');
  const { playgroundChat } = await import('../src/playground.mjs');
  const companion = getCompanionById(Number(process.env.PROBE_COMPANION_ID || 1));
  assert.ok(companion, 'configured companion missing');
  for (const message of ['那你倒是告诉我，东坝昨天销售额多少', '今天工作累死了，先别分析，哄哄我', '先不聊工作了，想你了']) {
    const started = Date.now();
    const result = await playgroundChat(companion, message, { probe: true });
    console.log(JSON.stringify({ message, reply: result.reply, seconds: (Date.now() - started) / 1000 }));
  }
}
