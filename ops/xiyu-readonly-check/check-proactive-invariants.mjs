// ============================================================
//  主动通道不变量检查器（只读）
//
//  为什么需要它：
//    2026-09-14 ~ 09-18，主动通道卡过 5 次互不相同的静默故障
//    （预算耗尽 / 弧误判 / 复核撞车 / 窗口关闭 / 过期动作死循环）。
//    共同特征是**失败不可见**：状态显示"已发"或干脆什么都不说，
//    用户只能自己发现"她不理我了"。
//
//    修单个症状治不了这一族问题。这里换一条路：把已知的失败模式写成
//    **不变量**，任何一条被违反就报出来。目标不是"不再有 bug"，
//    而是"下一个 bug 出现时能被发现，而不是等用户察觉"。
//
//  每条不变量都对应一个真实发生过的故障，注释里写明是哪一次。
//
//  用法：
//    sudo -u xiyu env DB_PATH=/opt/xiyu-ai/data/bot.db node check-proactive-invariants.mjs
//  必须传绝对路径 DB_PATH：不传、或库里没有预期表/零条记录，一律 exit 2，
//  绝不输出"全部通过"（见下面"自证闸"的说明）。
//  退出码：0 = 全部通过；1 = 有违反项；2 = 无法确证连对了库（结论无效）
// ============================================================

// ── 自证闸（必须最先跑）─────────────────────────────────────────────────────
//
// 事故：2026-09-18 本检查器第一次跑，从错误的工作目录启动，
//      `db.mjs` 里 `data/bot.db` 是相对 cwd 解析的，于是打开了一个
//      **新建的空库**——没有任何表、零条记录，六条不变量全部"PASS"。
//      也就是说：检查器自己犯了它要抓的那类错（报"正常"而实际没查）。
//
// 所以：跑不变量之前，先证明"我真的连到了那个有数据的库"。
// 证不出来就直接 exit 2（既不是通过 0，也不是发现违反 1），
// 避免任何人把一次空的检查当成"系统健康"。
{
  const DB = process.env.DB_PATH || '';
  if (!DB || !DB.startsWith('/')) {
    console.error('FATAL: 必须显式指定绝对路径 DB_PATH，例如');
    console.error('  sudo -u xiyu env DB_PATH=/opt/xiyu-ai/data/bot.db node check-proactive-invariants.mjs');
    console.error(`当前 DB_PATH=${DB || '(未设置)'} —— 拒绝在"可能是别的库"的情况下给结论。`);
    process.exit(2);
  }
  const fs = await import('node:fs');
  if (!fs.existsSync(DB)) {
    console.error(`FATAL: DB_PATH 指向的库不存在: ${DB}`);
    process.exit(2);
  }
}

const db = await import('/opt/xiyu-ai/src/db.mjs');
const lib = await import('/opt/xiyu-ai/src/initiative.mjs');
const dbx = db.getDb();
const now = Date.now();

{
  // 表在不在、有没有数据——这两条任一不成立，后面的 PASS 都没有意义。
  const tables = new Set(
    dbx.prepare("SELECT name FROM sqlite_master WHERE type='table'").all().map(r => r.name)
  );
  for (const t of ['agency_intentions', 'agency_actions', 'wechat_messages']) {
    if (!tables.has(t)) {
      console.error(`FATAL: 库里没有表 ${t} —— 连错库了（DB_PATH=${process.env.DB_PATH}）`);
      process.exit(2);
    }
  }
  const total = dbx.prepare('SELECT COUNT(*) AS n FROM agency_intentions').get().n;
  if (!total) {
    console.error('FATAL: agency_intentions 零条记录 —— 空库上的"全部通过"是假信号，拒绝输出。');
    process.exit(2);
  }
  // 报"总数"和"非终态数"两个口径，并注明数据快照时间。
  // 早先这里只报总数（如 9），而 I3/I6 报的是非终态数（如 0 / 8），
  // 两个数字在同一份输出里对不上，看起来像检查器在自相矛盾——
  // 一份会让人怀疑其自身数字的报告，没有资格被当作证据。
  const live = dbx.prepare(
    "SELECT COUNT(*) AS n FROM agency_intentions WHERE state NOT IN ('completed','abandoned','expired')"
  ).get().n;
  let mtime = '(未知)';
  try {
    const fs = await import('node:fs');
    const st = fs.statSync(process.env.DB_PATH);
    mtime = new Date(st.mtimeMs).toISOString();
    const wal = `${process.env.DB_PATH}-wal`;
    if (fs.existsSync(wal)) mtime += `（另有 WAL，${fs.statSync(wal).size} B）`;
  } catch { /* 取不到时间不影响检查 */ }
  console.log(`库: ${process.env.DB_PATH}`);
  console.log(`    动念 总 ${total} 条 / 非终态 ${live} 条（I3、I6 用非终态口径）`);
  console.log(`    库文件最后写入: ${mtime}`);
  console.log();
}

const violations = [];
const notes = [];
function invariant(id, ok, detail) {
  if (!ok) violations.push({ id, detail });
  console.log(`  ${ok ? 'PASS' : 'VIOLATION'}  [${id}] ${detail}`);
}

console.log('================ 主动通道不变量检查 ================');
console.log('时间:', new Date(now).toISOString());
console.log();

// ── I1：投递状态不得撒谎 ────────────────────────────────────────────────────
// 事故：2026-09-16/17 排程写 13 条 sent:true，wechat_messages 出站 0 条。
// 判据：最近一天里，标记 sent 却没有任何投递结果的时段数。
{
  const today = new Date(now + 8 * 3600e3).toISOString().slice(0, 10);
  const rows = dbx.prepare('SELECT schedule_json FROM proactive_runtime_schedules WHERE date_key = ?').all(today);
  let sentNoOutcome = 0;
  let sentTotal = 0;
  for (const r of rows) {
    let s = null;
    try { s = JSON.parse(r.schedule_json); } catch { continue; }
    for (const it of (s?.items || [])) {
      if (it?.sent !== true) continue;
      sentTotal++;
      if (!it.deliveryOutcome) sentNoOutcome++;
    }
  }
  invariant('I1-sent-must-carry-outcome', sentNoOutcome === 0,
    `今日标记 sent 的时段 ${sentTotal} 个，其中缺 deliveryOutcome 的 ${sentNoOutcome} 个（应为 0）`);
}

// ── I2：不得存在"已过期却仍未完成"的动作 ────────────────────────────────────
// 事故：2026-09-17，5 条 planned 动作过期 48.6~94.6 小时仍在库里，
//      其中一条导致动念每小时重试，并拦掉当晚晚安。
{
  const rows = dbx.prepare(`
    SELECT id, intention_id, state, expires_at,
           ROUND((julianday('now')-julianday(expires_at))*24,1) AS overdue_h
    FROM agency_actions
    WHERE state IN ('planned','running','prepared','sending')
      AND expires_at IS NOT NULL AND datetime(expires_at) < datetime('now')
    ORDER BY expires_at
  `).all();
  invariant('I2-no-expired-open-actions', rows.length === 0,
    `过期未完成动作 ${rows.length} 个` + (rows.length ? `（最久 ${rows[0].overdue_h}h：${rows[0].id}）` : ''));
  if (rows.length) notes.push('修复建议：这些动作应被 retireAgencyIntention 连带作废，或手动跑 cleanup-stale-actions.sh');
}

// ── I3：不得存在"知识已过期却仍在候选池"的动念 ──────────────────────────────
// 事故：同 I2 的动念侧。动念没有 expires_at，只有"知识寿命"能判它该不该留。
{
  const rows = dbx.prepare(`
    SELECT id, state, desired_change, created_at
    FROM agency_intentions
    WHERE state NOT IN ('completed','abandoned','expired')
  `).all();
  const expired = rows.filter(r => lib.isIntentionExpired(r, { nowMs: now }));
  invariant('I3-no-expired-intentions-in-pool', expired.length === 0,
    `非终态动念 ${rows.length} 条中，已过期仍留在池里的 ${expired.length} 条`
    + (expired.length ? `（如 ${expired[0].id}: ${String(expired[0].desired_change).slice(0, 30)}）` : ''));
  if (expired.length) notes.push('修复建议：每 tick 的 sweepIntentionRetirement 会自动收尾；若这条持续存在，说明扫描面又没覆盖到它（查 limit 是否又被候选条数绑住）');
}

// ── I4：通道长期关闭必须有痕迹（不能静默）─────────────────────────────────
// 事故：2026-09-16/17 静默跳过，用户两天后才发现。
{
  const streak = Number(db.getAppSetting('proactive_channel_closed_streak') || 0) || 0;
  const alertAt = 6;
  const ok = streak === 0 || streak < alertAt;
  invariant('I4-closed-channel-must-alert', ok,
    `通道连续关闭计数 = ${streak}（阈值 ${alertAt}；达到即应在日志出现告警）`);
  if (!ok) notes.push('修复建议：这正是"她发不出话"的信号——检查用户是否已 >24h 未互动，并提示用户发一条消息重开窗口');
}

// ── I5：不得"长时间零投递却无告警" ─────────────────────────────────────────
// 事故：2026-09-15 全天 0 条出站，而排程看起来正常。
{
  const last = dbx.prepare("SELECT MAX(created_at) AS t FROM wechat_messages WHERE direction='out'").get();
  const lastMs = last?.t ? Date.parse(String(last.t).replace(' ', 'T') + (String(last.t).includes('Z') ? '' : 'Z')) : NaN;
  const hoursSince = Number.isFinite(lastMs) ? (now - lastMs) / 3600e3 : null;
  // 48h 是容忍上限：期间可能有合理沉默（用户未互动导致窗口关闭）。
  // 真正的判据是"零投递 + 通道其实开着"，这里先做粗筛并由 I4 区分原因。
  const ok = hoursSince == null || hoursSince < 48;
  invariant('I5-no-long-silent-outage', ok,
    hoursSince == null ? '无出站记录' : `距最后一次真实出站 ${hoursSince.toFixed(1)} 小时（容忍 48h）`);
  if (!ok) notes.push('修复建议：先看 I4——若通道关闭计数为 0 且仍零投递，说明是代码侧拦住了发送，需查出站门');
}

// ── I6：非终态动念不应长期无投递（"卡住"检测）──────────────────────────────
// 事故：preparing 状态的动念可长期滞留（2026-09-14 起就有一条）。
// 注意：`waiting_user` 是**正常等待用户回答**，`suspended` 是**主动暂停**
// （冲突弧/预算等原因），这两者长期不动不等于卡住，因此排除在外。
{
  const rows = dbx.prepare(`
    SELECT id, state, desired_change,
           ROUND((julianday('now')-julianday(updated_at))*24,1) AS stale_h
    FROM agency_intentions
    WHERE state IN ('preparing','ready','active')
      AND (julianday('now')-julianday(updated_at))*24 > 72
    ORDER BY stale_h DESC LIMIT 5
  `).all();
  invariant('I6-no-stuck-intentions', rows.length === 0,
    `超过 72h 未推进的活跃动念 ${rows.length} 个`
    + (rows.length ? `（最久 ${rows[0].stale_h}h，state=${rows[0].state}）` : '')
    + '（不含 waiting_user / suspended —— 那是正常等待或主动暂停）');
  if (rows.length) notes.push('修复建议：查这些动念是否既没送达也没推进；preparing 长期不动通常是工具链没回执');
}

// ── 汇总 ────────────────────────────────────────────────────────────────────
console.log();
console.log('================ 汇总 ================');
if (!violations.length) {
  console.log('全部不变量通过。');
} else {
  console.log(`违反 ${violations.length} 条：`);
  for (const v of violations) console.log(`  - [${v.id}] ${v.detail}`);
}
if (notes.length) {
  console.log();
  console.log('修复建议：');
  for (const n of notes) console.log('  ·', n);
}
dbx.close();
process.exit(violations.length ? 1 : 0);
