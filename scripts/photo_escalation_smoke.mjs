import assert from 'node:assert/strict';
import { photoEscalationPolicy, escalationLevel } from '../src/escalation.mjs';

const repeated = [
  { direction: 'in', content: '发张照片' },
  { direction: 'out', content: '别急，等一下' },
  { direction: 'in', content: '再发一张' },
  { direction: 'out', content: '别催啦' },
  { direction: 'in', content: '拍个照给我看' },
];

const levelTwo = photoEscalationPolicy('再拍一张', repeated);
assert.ok(levelTwo.level >= 2);
assert.equal(levelTwo.hardBlock, false, 'level 2 只能改变语气，不能阻止照片');

const explicitRefusal = [
  ...repeated,
  { direction: 'in', content: '再拍一张' },
  { direction: 'out', content: '我现在不想拍，别再催我了' },
];
const levelThree = photoEscalationPolicy('再拍一张', explicitRefusal);
assert.equal(levelThree.level, 3);
assert.equal(levelThree.hardBlock, true, 'level 3 且刚明确拒拍才允许硬拒');

const retry = photoEscalationPolicy('照片怎么还没发出来', explicitRefusal, { hasOpenPromise: true });
assert.equal(retry.isRetry, true);
assert.equal(retry.effectiveLevel, 0);
assert.equal(retry.hardBlock, false, '未兑现照片的追问不能按催促拒绝');

// ── 2026-09-14 回归：亲昵话不得被判为「施压」 ──────────────────────────────
// 原 PUSHY_RE 含 `看看你`/`想看你`，导致生产上「我看看你的洗衣机」连续 4 条后
// 升到 L3，建成 pressure_spam severity 3 事件并把角色推入 hurt（压制主动联系）。
// 这两个词在 photo_intent 里本就是正常索图表达，不该触发情绪升级。
{
  // 单条亲昵话：不得判为施压
  assert.equal(escalationLevel('我现在单纯就是想看看你', []).pushy, false, '亲昵话「想看看你」不算施压');
  assert.equal(escalationLevel('我看看你的洗衣机', []).pushy, false, '玩笑话「看看你的X」不算施压');

  // 复现事故序列：即使连发、且她刚"说了"，也不得升到 L2（L2 才会建 pressure_spam）
  const incident = [
    { direction: 'in', content: '想看，主要是想看你那件粉色的情趣内衣' },
    { direction: 'in', content: '那你挑吧，我想看看你自己私人的东西' },
    { direction: 'out', content: '刚不都说了嘛，坐床上呢' },
    { direction: 'in', content: '现在可以发啦' },
    { direction: 'in', content: '我现在单纯就是想看看你' },
  ];
  const inc = escalationLevel('我看看你的洗衣机', incident);
  assert.ok(inc.level < 2, `事故序列不得升到 L2（实际 level=${inc.level}），否则会建 pressure_spam 事件`);

  // 真正的反复索要必须仍然升级 —— 修正不能把这条路径也放松
  const realPush = [
    { direction: 'in', content: '发张照片' },
    { direction: 'out', content: '别急，等一下' },
    { direction: 'in', content: '再发一张' },
    { direction: 'out', content: '别催啦' },
    { direction: 'in', content: '拍个照给我看' },
  ];
  assert.ok(escalationLevel('再拍一张', realPush).level >= 2, '真的反复索图仍应升级');
}

console.log('photo_escalation_smoke: passed');
