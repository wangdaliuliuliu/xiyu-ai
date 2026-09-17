// ============================================================
//  规则回溯验证（只读，不改任何东西）
//
//  目的：拿提议的"三问"规则，去跑当前库里 5 条积压动作，
//        看规则会不会刚好把它们判对、以及**本该在哪一刻**收掉。
//
//  规则（提议稿，尚未实现）：
//    第一层 保质期：判断动念是否"怕时间"，算出保质期，超期 → expired
//    第二层 已消解：链条挂的来源现在是否已经不需要问了 → completed
//    第三层 反复失败：同指纹是否已多次撞车 → suspended
//
//  用法：sudo -u xiyu env DB_PATH=... node precheck-shelf-life-probe.mjs
// ============================================================

const db = await import('/opt/xiyu-ai/src/db.mjs');

// ---------- 规则实现（提议稿；只用于验证，不影响生产逻辑）----------
const TIME_BOUND_PATTERNS = [
  [/(\d{1,2})[-/月](\d{1,2})日?/, '含具体日期'],
  [/20\d{2}-\d{2}-\d{2}/, '含 ISO 日期'],
  [/(今天|今日|昨天|昨日|当天|当日|最近\s*\d+\s*天|最近三天|近三日)/, '含相对时间词'],
  [/(尚未开始|仍在路上|还没填|未填|未更新|未出现|readySheets|missingSheets)/, '含"状态未定"描述'],
  [/(元|单量|销售额|客流|占比|票数)\s*[:：=]?\s*\d/, '含具体指标数'],
];
const TIMELESS_PATTERNS = [
  [/(标准|原则|通常|一般|偏好|习惯|边界|底线|为什么|怎么判断|如何看待)/, '含方法论/偏好词'],
  [/(核心服务对象|核心选择理由|明确不做|机会判断标准|取舍)/, '含定位/边界类切面'],
];
const MONITOR_RE = /(订单表|汇总表|日报|监控|检查表|来源表|页签|sheet)/i;

function classify(intention) {
  const text = `${intention.desired_change || ''} ${intention.appraisal_summary || ''} ${intention.basis_refs_json || ''}`;
  const timeHits = TIME_BOUND_PATTERNS.filter(([re]) => re.test(text)).map(([, why]) => why);
  const timelessHits = TIMELESS_PATTERNS.filter(([re]) => re.test(text)).map(([, why]) => why);
  const isMonitor = MONITOR_RE.test(text);
  // 两者都有 → 取时效性（保守）
  const timeBound = timeHits.length > 0;
  let shelfLifeHours;
  let kind;
  if (!timeBound) { kind = 'non_time_bound'; shelfLifeHours = 14 * 24; }
  else if (isMonitor) { kind = 'time_bound_monitor'; shelfLifeHours = 24; }
  else { kind = 'time_bound_fact'; shelfLifeHours = 48; }
  return { kind, shelfLifeHours, timeHits, timelessHits, both: timeBound && timelessHits.length > 0 };
}

function hoursBetween(a, b) { return (b - a) / 3600e3; }

// ---------- 读取真实数据 ----------
const dbx = db.getDb();
const intentions = dbx.prepare(`
  SELECT id, state, domain, version, desired_change, appraisal_summary, basis_refs_json,
         linked_business_task_ref, reconsider_after, expires_at, created_at, updated_at, priority_class
  FROM agency_intentions
  WHERE state NOT IN ('completed','abandoned','expired')
  ORDER BY updated_at DESC
`).all();

const openActions = dbx.prepare(`
  SELECT id, intention_id, action_type, state, dedup_key, not_before, expires_at, created_at, updated_at
  FROM agency_actions
  WHERE state IN ('planned','running','sending','prepared')
  ORDER BY expires_at
`).all();

const intendedById = new Map(intentions.map(i => [i.id, i]));
const now = Date.now();

console.log('================ 规则回溯验证（只读）================');
console.log('现在:', new Date(now).toISOString());
console.log();

// ---------- Part A：积压动作 + 派生动念的规则判定 ----------
console.log('=== Part A：5 条积压动作，规则会怎么判 ===');
console.log();
for (const a of openActions) {
  const it = intendedById.get(a.intention_id);
  if (!it) {
    console.log(`[动作 ${a.id.slice(0,22)}] 找不到动念 ${a.intention_id}`);
    continue;
  }
  const cls = classify(it);
  const createdMs = Date.parse((it.created_at || '').replace(' ', 'T') + 'Z');
  const expiredAt = a.expires_at ? Date.parse(a.expires_at) : null;
  // 保质期从"动念建立"起算
  const shelfDeadline = createdMs + cls.shelfLifeHours * 3600e3;

  console.log(`动念 ${it.id}`);
  console.log(`  目标        : ${String(it.desired_change).slice(0, 56)}`);
  console.log(`  动念状态    : ${it.state}   version=${it.version}`);
  console.log(`  分类        : ${cls.kind}  保质期=${cls.shelfLifeHours}h`);
  console.log(`  命中时效特征: ${cls.timeHits.join('、') || '无'}`);
  console.log(`  命中非时效  : ${cls.timelessHits.join('、') || '无'}`);
  if (cls.both) console.log('  ⚠ 两类都命中 → 按规则取时效性（保守）');
  console.log(`  动念建立    : ${it.created_at}`);
  console.log(`  保质期到期  : ${new Date(shelfDeadline).toISOString()}  ${now > shelfDeadline ? '← 已超期 ' + hoursBetween(shelfDeadline, now).toFixed(1) + 'h' : '（未到期）'}`);
  console.log(`  动作过期    : ${a.expires_at}  ${expiredAt && now > expiredAt ? '← 已过期 ' + hoursBetween(expiredAt, now).toFixed(1) + 'h' : ''}`);
  console.log(`  动作状态    : ${a.state}   dedup=${String(a.dedup_key).slice(0,20)}`);
  console.log(`  → 规则判定  : ${now > shelfDeadline ? 'expired（超保质期，本该收掉）' : '仍有效'}`);
  console.log();
}

// ---------- Part B：非时效动念不该被误杀 ----------
console.log('=== Part B：当前所有未完成动念的分类（检查会不会误杀）===');
console.log();
for (const it of intentions) {
  const cls = classify(it);
  const createdMs = Date.parse((it.created_at || '').replace(' ', 'T') + 'Z');
  const deadline = createdMs + cls.shelfLifeHours * 3600e3;
  const overdue = now > deadline;
  const flag = cls.kind === 'non_time_bound' ? (overdue ? '⚠ 超期(14天)' : '✅ 有效') : (overdue ? '→ expired' : '✅ 有效');
  console.log(`  ${it.id.slice(0,24).padEnd(26)} ${String(it.state).padEnd(12)} ${cls.kind.padEnd(18)} ${flag}  ${String(it.desired_change).slice(0,40)}`);
}
console.log();

// ---------- Part C：第二层"已消解"的应用点 ----------
console.log('=== Part C：第二层「问题是否已消解」的适用面 ===');
console.log();
const linked = intentions.filter(i => i.linked_business_task_ref);
console.log(`  挂企业任务的未完成动念: ${linked.length} 条`);
for (const it of linked) {
  console.log(`  - ${it.id.slice(0,24)} | ref=${it.linked_business_task_ref} | state=${it.state}`);
  console.log(`      ${String(it.desired_change).slice(0,60)}`);
}
console.log();
console.log('  说明：第二层需要"重查来源"才能判，本探针只列出适用对象，不实际发起查询。');
console.log();

// ---------- Part D：第三层 失败指纹 ----------
console.log('=== Part D：第三层「反复失败」的现有证据 ===');
console.log();
const memo = db.getAppSetting('proactive_precheck_last_failure');
console.log('  预检记忆:', memo || '(空)');
try {
  const m = JSON.parse(memo || '{}');
  if (m.intentionId) {
    const it = intendedById.get(m.intentionId);
    console.log(`  该动念仍在未完成集合中: ${it ? '是（state=' + it.state + '）' : '否'}`);
  }
} catch { /* ignore */ }
const ledger = '/opt/xiyu-ai/data/initiative-ledger.jsonl';
try {
  const fs = await import('node:fs');
  const lines = fs.readFileSync(ledger, 'utf8').trim().split('\n').slice(-200);
  const blocked = lines.map(l => { try { return JSON.parse(l); } catch { return null; } })
    .filter(Boolean)
    .filter(d => String(d.reason || '').includes('订单表日报'));
  console.log(`  ledger 里"订单表日报"撞车次数: ${blocked.length}`);
  for (const b of blocked) console.log(`    ${String(b.at).slice(0,19)} | ${b.action} | ${b.reason}`);
} catch (e) {
  console.log('  ledger 读取失败:', e.message);
}
console.log();
console.log('================ 验证结束 ================');
dbx.close();
