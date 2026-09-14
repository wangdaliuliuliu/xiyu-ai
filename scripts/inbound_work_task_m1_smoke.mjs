/* M1 状态机契约回归：使用结构化语义 fixture 检查状态合并和目录门禁。
 * 这不是 DeepSeek 效果验收；真实自然语言模型验收只在 M3 执行。
 */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xiyu-inbound-m1-'));
process.env.XIYU_WORKBENCH_CONTEXT_URL = 'http://m1-workbench.invalid';
process.env.XIYU_WORKBENCH_CONTEXT_ENABLED = 'true';
process.env.XIYU_WORKBENCH_ACTIVE_TASKS_PATH = path.join(root, 'active-tasks.json');
process.env.XIYU_WORKBENCH_OUTBOX_PATH = path.join(root, 'outbox.json');

const bridge = await import('../src/enterprise_context.mjs');
const catalog = {
  project: { id: 'xiyu-vr', name: '溪语经营项目' },
  venues: [{ id: 'ZHONGYING', name: '中影' }, { id: 'DONGBA', name: '东坝' }],
  capabilities: [
    { id: 'channel_daily', metrics: ['box_office_total', 'sales_order_count', 'platform_settlement'] },
    { id: 'daily_traffic', metrics: ['venue_traffic', 'reach_count', 'conversion_count'] },
  ],
  nodes: [],
};

const performance = { kind: 'performance_summary', businessMeaning: '判断近期经营表现', metricIds: ['box_office_total', 'sales_order_count', 'venue_traffic'] };
const exact = { kind: 'exact_date', start: '2026-09-08', end: '2026-09-08', count: null };
const recent = { kind: 'recent_complete_days', start: null, end: null, count: 3 };
const task = ({ venueIds = [], timeSpec = recent, requestedOutcome = performance, missingSlots = [], goal = '了解近期经营表现', completeQuestion = '请结合真实资料说明近期经营表现' } = {}) => ({ goal, completeQuestion, scope: { projectId: 'xiyu-vr', venueIds }, timeSpec, requestedOutcome, businessMeaning: requestedOutcome.businessMeaning, metricIds: requestedOutcome.metricIds, missingSlots });
const route = (taskTransition, nextTask, conversationType = 'work', extras = {}) => ({ conversationType, interactionIntent: 'lookup', taskTransition, task: nextTask, workSegments: extras.workSegments || ['工作请求'], retrievalNeeded: false, writebackPotential: false, confidence: 0.99, ...extras });
const retrieve = async () => ({ contextVersion: 'm1-fixture', items: [], missingInformation: ['M1 不读取资料'], boundaries: [] });

const cases = [
  { name: '模糊业绩续接门店', expressions: ['最近业绩怎么样', '这阵子生意还行吗', '帮我瞅瞅最近经营表现'], turns: [route('start', task()), route('continue', task({ venueIds: ['ZHONGYING'] })), route('complete', task({ venueIds: ['ZHONGYING'] }))] },
  { name: '只补充时间', expressions: ['先看中影的表现', '就看中影这家', '最近几天中影的'], turns: [route('start', task({ venueIds: ['ZHONGYING'], timeSpec: { kind: 'unspecified' }, missingSlots: ['time'] })), route('continue', task({ venueIds: ['ZHONGYING'], timeSpec: recent })), route('continue', task({ venueIds: ['ZHONGYING'], timeSpec: recent }))] },
  { name: '修改门店', expressions: ['先看中影', '换成东坝吧', '还是东坝那家'], turns: [route('start', task({ venueIds: ['ZHONGYING'] })), route('revise', task({ venueIds: ['DONGBA'] })), route('continue', task({ venueIds: ['DONGBA'] }))] },
  { name: '继续追问指标', expressions: ['中影最近表现如何', '客流呢', '那触达和转化怎么样'], turns: [route('start', task({ venueIds: ['ZHONGYING'] })), route('continue', task({ venueIds: [], requestedOutcome: { kind: 'fact', businessMeaning: '核对客流', metricIds: ['venue_traffic'] } })), route('continue', task({ venueIds: [], requestedOutcome: { kind: 'fact', businessMeaning: '核对触达和转化', metricIds: ['reach_count', 'conversion_count'] } }))] },
  { name: '数据后问原因', expressions: ['先给我中影最近数据', '为什么会这样', '帮我分析下原因'], turns: [route('start', task({ venueIds: ['ZHONGYING'] })), route('revise', task({ venueIds: [], requestedOutcome: { kind: 'diagnosis', businessMeaning: '解释近期表现变化', metricIds: ['box_office_total', 'venue_traffic'] } })), route('continue', task({ venueIds: [], requestedOutcome: { kind: 'diagnosis', businessMeaning: '解释近期表现变化', metricIds: ['box_office_total', 'venue_traffic'] } }))] },
  { name: '普通私人聊天', expressions: ['我最近状态怎么样', '今天有点累', '你想我了吗'], turns: [route('none', task(), 'personal', { interactionIntent: 'support', workSegments: [], confidence: 0.99 }), route('none', task(), 'personal', { interactionIntent: 'support', workSegments: [], confidence: 0.99 }), route('none', task(), 'personal', { interactionIntent: 'support', workSegments: [], confidence: 0.99 })] },
  { name: '工作私人混合', expressions: ['抱抱我，顺便看看中影最近表现', '我有点焦虑，帮我看下东坝', '先陪我说两句再看数据'], turns: [route('start', task({ venueIds: ['ZHONGYING'] }), 'mixed'), route('revise', task({ venueIds: ['DONGBA'] }), 'mixed'), route('continue', task({ venueIds: ['DONGBA'] }), 'mixed')] },
  { name: '明确退出', expressions: ['先不聊工作了', '今天不看数据了', '换个话题吧'], turns: [route('start', task({ venueIds: ['ZHONGYING'] })), route('exit', task({ venueIds: ['ZHONGYING'] }), 'personal', { workSegments: [], interactionIntent: 'support' }), route('none', task(), 'personal', { workSegments: [], interactionIntent: 'support', confidence: 0.99 })] },
  { name: '精确日期', expressions: ['查中影9月8日销售额', '核对2026-09-08中影的票数', '看一下9月8号那天'], turns: [route('start', task({ venueIds: ['ZHONGYING'], timeSpec: exact, requestedOutcome: { kind: 'fact', businessMeaning: '核对精确日期', metricIds: ['box_office_total'] } })), route('continue', task({ venueIds: ['ZHONGYING'], timeSpec: exact, requestedOutcome: { kind: 'fact', businessMeaning: '核对精确日期', metricIds: ['sales_order_count'] } })), route('continue', task({ venueIds: ['ZHONGYING'], timeSpec: exact }))] },
  { name: '目录外实体', expressions: ['看北京店的业绩', '北京那家最近怎么样', '查一下广州门店'], turns: [route('start', task({ venueIds: ['BEIJING'] })), route('continue', task({ venueIds: ['SHANGHAI'] })), route('revise', task({ venueIds: ['GUANGZHOU'] }))] },
  { name: '完成任务', expressions: ['就按这个结果来', '先这样就行', '这个任务完成了'], turns: [route('start', task({ venueIds: ['DONGBA'] })), route('complete', task({ venueIds: ['DONGBA'] })), route('complete', task({ venueIds: ['DONGBA'] }))] },
  { name: '重启恢复', expressions: ['中影最近数据', '进程重启后继续', '接着刚才的中影'], turns: [route('start', task({ venueIds: ['ZHONGYING'] })), route('continue', task({ venueIds: [] })), route('continue', task({ venueIds: ['ZHONGYING'] }))] },
];

let assertions = 0;
for (const [index, fixture] of cases.entries()) {
  assert.equal(fixture.expressions.length, 3);
  let cursor = 0;
  const prepared = [];
  for (const expression of fixture.expressions) {
    const spec = fixture.turns[cursor];
    const result = await bridge.prepareEnterpriseContext({ message: expression, history: [], accountId: `m1-account-${index}`, companionId: `m1-companion-${index}` }, {
      catalog,
      route: async () => spec,
      retrieve,
    });
    prepared.push(result);
    cursor++;
  }
  const final = prepared[prepared.length - 1];
  if (fixture.name === '普通私人聊天' || fixture.name === '明确退出') assert.equal(final.route.conversationType, 'personal');
  if (fixture.name === '目录外实体') {
    assert.equal(final.route.scope.venueIds.length, 0);
    assert.ok(final.route.task.missingSlots.includes('venue'));
    assert.ok(final.route.clarificationQuestion.includes('中影'));
    assert.ok(!JSON.stringify(final.route.scope).match(/北京|上海|广州/));
  }
  if (fixture.name === '修改门店') {
    assert.equal(prepared[1].activeTask.taskId, prepared[0].activeTask.taskId);
    assert.deepEqual(prepared[1].activeTask.scope.venueIds, ['DONGBA']);
    assert.deepEqual(prepared[1].activeTask.sourceRefs, []);
  }
  if (fixture.name === '模糊业绩续接门店' || fixture.name === '只补充时间') assert.equal(prepared[1].route.taskTransition, 'continue');
  if (fixture.name === '修改门店') assert.equal(prepared[1].route.taskTransition, 'revise');
  if (fixture.name === '重启恢复') {
    const restored = bridge.getActiveEnterpriseTask({ accountId: `m1-account-${index}`, companionId: `m1-companion-${index}` });
    assert.ok(restored?.taskId);
    assert.deepEqual(restored.scope.venueIds, ['ZHONGYING']);
  }
  assertions += 8;
}

console.log(JSON.stringify({ ok: true, milestone: 'M1', status: 'passed', scenarios: cases.length, naturalExpressions: cases.length * 3, assertions }));
