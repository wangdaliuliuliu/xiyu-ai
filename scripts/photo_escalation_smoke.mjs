import assert from 'node:assert/strict';
import { photoEscalationPolicy } from '../src/escalation.mjs';

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

console.log('photo_escalation_smoke: passed');
