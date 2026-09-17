// ============================================================
//  一次性运维：关闭冲突弧后复位卡住的 hurt 状态
//
//  背景：pressure_spam 误判把角色推入 hurt（2026-09-14T03:43:38Z），
//        三条恢复路径均不可达，需等到 72h 后自然消化。
//        关闭开关后状态机返回 normal，但库里的存量 hurt 需要显式复位。
//
//  本脚本：
//    1. 打印复位前状态
//    2. companions.arc_state → normal
//    3. 未结关系事件 → repair_status='stale', resolved_at=now
//       （note 写明是运维复位，不冒充她"自己消气"）
//    4. 打印复位后状态
//
//  用法：sudo -u xiyu node reset-arc-hurt.mjs
// ============================================================

import { getDb, getArcState, setArcState } from '/opt/xiyu-ai/src/db.mjs';

const db = getDb();
const COMPANION_ID = 1;

function snapshot(label) {
  const c = db.prepare('SELECT id, arc_state, arc_state_changed_at FROM companions WHERE id = ?').get(COMPANION_ID);
  const ev = db.prepare(
    "SELECT id, type, severity, repair_status, repair_warm, created_at FROM companion_relationship_events WHERE companion_id = ? AND (resolved_at IS NULL OR resolved_at = '') ORDER BY id DESC"
  ).all(COMPANION_ID);
  console.log(`--- ${label} ---`);
  console.log('companions:', JSON.stringify(c));
  console.log('open events:', JSON.stringify(ev));
  return { c, ev };
}

snapshot('复位前');

const before = getArcState(COMPANION_ID);
console.log('getArcState() 复位前 =', JSON.stringify(before));

// 1) 状态复位
setArcState(COMPANION_ID, 'normal');
console.log('已设置 arc_state = normal');

// 2) 结掉未结事件（标为 stale，不冒充自然消化）
const nowIso = new Date().toISOString();
const closed = db.prepare(
  "UPDATE companion_relationship_events SET repair_status = 'stale', resolved_at = ? WHERE companion_id = ? AND (resolved_at IS NULL OR resolved_at = '')"
).run(nowIso, COMPANION_ID);
console.log('已结掉未结事件数 =', closed.changes, ' resolved_at =', nowIso);

snapshot('复位后');
const after = getArcState(COMPANION_ID);
console.log('getArcState() 复位后 =', JSON.stringify(after));

const ok = after.arc_state === 'normal';
console.log('RESET=' + (ok ? 'PASS' : 'FAIL'));
process.exit(ok ? 0 : 1);
