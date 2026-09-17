// ============================================================
//  只读验证：确认生产服务环境下的 ARC 开关状态
//
//  用服务相同的环境（ARC_ENABLED 从 drop-in 注入）加载生产代码，
//  检查 arcEnabled() 返回值与状态机行为。
//  只读：仅 select，不写库。
// ============================================================

import { arcEnabled, tickArcOnSignal, tickArcOnTime } from '/opt/xiyu-ai/src/relationship_arc.mjs';

console.log('ARC_ENABLED 环境值 =', JSON.stringify(process.env.ARC_ENABLED ?? null));
console.log('arcEnabled()      =', arcEnabled());

const N = new Date();
const base = {
  stateChangedAt: new Date(N.getTime() - 3600e3).toISOString(),
  style: 'secure', safeMode: false, openEvent: null, now: N,
};
const sig = (o) => tickArcOnSignal({ ...base, state: 'normal', todayEventCount: 0, recentArchivedType: null, rng: () => 0.99, signal: { kind: 'harsh_words', severity: 4 }, ...o });
const tim = (o) => tickArcOnTime({ ...base, state: 'normal', neglectStage: 'none', interactionsSinceEvent: 0, ...o });

const a = sig({});
console.log('重伤信号(sev4) →', a.state, '| reason =', a.reason, '| 建事件 =', a.eventOp ? 'YES' : 'NO');
const b = tim({ state: 'hurt', stateChangedAt: new Date(N.getTime() - 7200e3).toISOString() });
console.log('存量 hurt    →', b.state, '| reason =', b.reason);
const c = tim({ neglectStage: 'disappointed' });
console.log('neglect 信号  →', c.state, '| reason =', c.reason);

const disabled = arcEnabled() === false;
const neutralized = a.state === 'normal' && a.reason === 'arc_disabled' && !a.eventOp;
console.log('SWITCH_EFFECTIVE=' + (disabled && neutralized ? 'YES' : 'NO'));
process.exit(disabled && neutralized ? 0 : 1);
