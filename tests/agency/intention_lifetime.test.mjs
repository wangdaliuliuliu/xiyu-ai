/**
 * 动念保质期分类 — 离线确定性回归（2026-09-18）。
 *
 * 真实事故（2026-09-15 ~ 09-17）：
 *   一条问「订单系统汇总表 2026-09-14 数据填了没」的动念停在 ready，
 *   它派生的动作 9-15 13:10 就过期了，但**动作过期不终结动念**，于是动念
 *   每小时被重新选中、重新生成、撞在同一条出站复核上；9-17 一天撞 3 次
 *   （18:09/19:14/20:45），还把当晚 22:08 的晚安拦掉（agency_blocked）。
 *
 * 本文件锁住两条同等重要的性质：
 *   ① 该过期的必须过期（监控类 24h / 一次性事实 48h / 方法论 14 天）
 *   ② **不该过期的绝不能过期** —— 早安/晚安是每日仪式，误杀会让角色
 *      每天发不出问候，比不修更糟。防误杀断言与防漏判断言一样重要。
 *
 * 零 IO、零模型、零数据库。
 * 注意：本文件用相对路径 ../../src/，与 tests/agency/ 下其它测试一致。
 */
import assert from 'node:assert/strict';
import {
  classifyIntentionLifetime,
  intentionShelfDeadline,
  isIntentionExpired,
  judgeIntentionRetirement,
  INTENTION_LIFETIME,
  INTENTION_BLOCK_SUSPEND_AT,
  RITUAL_SETTLED_HOURS,
} from '../../src/initiative.mjs';

let pass = 0, fail = 0;
const ok = (cond, name) => { if (cond) { pass++; } else { fail++; console.error('  [FAIL]', name); } };

const H = 3600e3;
const BASE = Date.parse('2026-09-15T10:10:36Z');   // 事故当天

// ═══ 1. 分类：文案取自线上 agency_intentions 真实记录 ═══════════════════════
const CASES = [
  {
    label: '订单表状态（事故那条）',
    text: '确认订单系统汇总表 2026-09-14 数据是尚未开始填写还是仍在路上，避免把未完成的来源表误当成完整日报',
    type: INTENTION_LIFETIME.TIME_BOUND_MONITOR, hours: 24,
  },
  {
    label: '晚安（每日仪式）',
    text: '在睡前用一句轻软的晚安收尾，让用户感到溪语今天一直惦记着他，不要求他回应，也不追问业绩结果',
    type: INTENTION_LIFETIME.RECURRING_RITUAL, hours: null,
  },
  {
    label: '早安（每日仪式）',
    text: '用轻松不打扰的早安承接新一天，让用户感到溪语在，把最近他关心的话题留一个自然接口',
    type: INTENTION_LIFETIME.RECURRING_RITUAL, hours: null,
  },
  {
    label: '低负担关系开场',
    // 用线上原文：以"留一个入口"收尾，属关系类短句，绑定每日节律
    text: '给用户留一个随时可以求助、汇报或喘口气的入口',
    type: INTENTION_LIFETIME.RECURRING_RITUAL, hours: null,
  },
  {
    label: '中影三天业绩（未绑具体日期，落兜底类）',
    text: '查询中影门店最近三天的销售业绩',
    // 注意：它不含具体日期/指标，因此走兜底（7 天）而非 48h 事实类。
    // 这是刻意的保守取舍：宁可给未归类动念多留几天，也不要 48h 就误收。
    type: INTENTION_LIFETIME.TIME_BOUND_FACT, hours: 7 * 24,
  },
  {
    label: '机会判断标准（方法论）',
    text: '拿到用户判断新机会的两三条标准（或一个实际例子），把东坝企业定位变成可执行的筛选规则',
    type: INTENTION_LIFETIME.NON_TIME_BOUND, hours: 14 * 24,
  },
  {
    label: '明确不做的事（边界）',
    text: '补齐企业定位与边界：明确不做的事',
    type: INTENTION_LIFETIME.NON_TIME_BOUND, hours: 14 * 24,
  },
];
for (const c of CASES) {
  const got = classifyIntentionLifetime({ desired_change: c.text });
  ok(got.type === c.type, `${c.label} → 类型应为 ${c.type}（实际 ${got.type} / ${got.reason}）`);
  ok(got.shelfLifeHours === c.hours, `${c.label} → 保质期应为 ${c.hours}h（实际 ${got.shelfLifeHours}）`);
}

// ═══ 2. 防误杀：每日仪式/陪伴/方法论，无论多久都不判过期 ═════════════════════
{
  const neverExpire = [
    ['晚安', '在睡前用一句轻软的晚安收尾，让用户感到溪语今天一直惦记着他，不要求他回应', '2026-09-01 16:00:00'],
    ['早安', '用轻松不打扰的早安承接新一天，让用户感到溪语在，把最近他关心的话题留一个自然接口', '2026-08-01 00:00:00'],
    ['低负担入口', '给用户留一个随时可以求助、汇报或喘口气的入口', '2026-06-01 00:00:00'],
    // 方法论 14 天保质期：建立时间落在 14 天内，测的是"正确分类"而非"超期"
    ['方法论', '拿到用户判断新机会的两三条标准，把东坝企业定位变成可执行的筛选规则', '2026-09-10 00:00:00'],
  ];
  for (const [label, text, created] of neverExpire) {
    const it = { desired_change: text, created_at: created };
    const got = classifyIntentionLifetime(it);
    ok(isIntentionExpired(it, { nowMs: BASE }) === false,
      `不得过期：${label}（判为 ${got.type}，建立于 ${created}）`);
  }
}

// ═══ 3. 该过期的必须过期（含精确边界：用 > 而非 >=）═════════════════════════
{
  const monitor = { desired_change: '确认订单系统汇总表 2026-09-14 数据是否还在路上', created_at: '2026-09-15 10:10:36' };
  const deadline = intentionShelfDeadline(monitor, { createdAtMs: BASE });
  ok(deadline === BASE + 24 * H, '监控类到期时刻 = 建立时间 + 24h');
  ok(isIntentionExpired(monitor, { nowMs: deadline - 1, createdAtMs: BASE }) === false, '未到期（早 1ms）不算过期');
  ok(isIntentionExpired(monitor, { nowMs: deadline, createdAtMs: BASE }) === false, '正好到期不算过期');
  ok(isIntentionExpired(monitor, { nowMs: deadline + 1, createdAtMs: BASE }) === true, '超过到期即过期');

  // 兜底类（7 天）边界
  const fallback = { desired_change: '查询中影门店最近三天的销售业绩', created_at: '2026-09-15 10:10:36' };
  ok(isIntentionExpired(fallback, { nowMs: BASE + 6 * 24 * H, createdAtMs: BASE }) === false, '兜底类 6 天未过期');
  ok(isIntentionExpired(fallback, { nowMs: BASE + 8 * 24 * H, createdAtMs: BASE }) === true, '兜底类 8 天已过期');

  // 显式带日期的监控类才是 24h（这是最短的一档）
  const monitor2 = { desired_change: '确认订单系统汇总表 2026-09-14 数据是否还在路上', created_at: '2026-09-15 10:10:36' };
  ok(isIntentionExpired(monitor2, { nowMs: BASE + 23 * H, createdAtMs: BASE }) === false, '监控类 23h 未过期');
  ok(isIntentionExpired(monitor2, { nowMs: BASE + 25 * H, createdAtMs: BASE }) === true, '监控类 25h 已过期');

  const method = { desired_change: '拿到用户判断新机会的两三条标准', created_at: '2026-09-15 10:10:36' };
  ok(isIntentionExpired(method, { nowMs: BASE + 13 * 24 * H, createdAtMs: BASE }) === false, '方法论 13 天未过期');
  ok(isIntentionExpired(method, { nowMs: BASE + 15 * 24 * H, createdAtMs: BASE }) === true, '方法论 15 天已过期');
}

// ═══ 4. 核心机制：先剔除具体锚点，再判稳定意图 ═══════════════════════════════
{
  // 同一句晚安，带具体日期 → 绑在已过去的时间点上 → 时效性（那次晚安已无意义）
  const dated = { desired_change: '2026-09-14 的晚安：睡前用一句轻软的晚安收尾', created_at: '2026-09-13 16:00:00' };
  const c1 = classifyIntentionLifetime(dated);
  ok(c1.type === INTENTION_LIFETIME.TIME_BOUND_FACT, `带具体日期的仪式 → 时效性（实际 ${c1.type} / ${c1.reason}）`);
  // 建立于 9-13 16:00 + 48h = 9-15 16:00，而 BASE 是 9-15 10:10 → 还没到期，故用稍后时刻断言
  ok(isIntentionExpired(dated, { nowMs: BASE + 6 * H }) === true, '带过去日期的仪式，48h 后应过期');

  // 带具体指标 → 时效性（真实文案：在线渠道 112.7→73.6→153.9）
  const metric = { desired_change: '复查在线渠道从112.7掉到73.6又回到153.9这件事，看是不是定价问题', created_at: '2026-09-14 16:00:00' };
  ok(classifyIntentionLifetime(metric).type === INTENTION_LIFETIME.TIME_BOUND_FACT, '带具体指标 → 时效性');

  // 英文 camelCase 键名不得算"具体指标"（appraisal 里常见）
  const keyNames = {
    desired_change: '确认来源表状态，避免把未完成的来源表误当成完整日报',
    appraisal_summary: '事实：readySheets=0，missingSheets 若干，检查时间已记录。推断：可能尚未开始填。',
  };
  ok(classifyIntentionLifetime(keyNames).reason !== 'monitor_with_concrete_time',
    '纯 camelCase 键名不因"指标"被判成监控类（否则每天都会被误杀）');
}

// ═══ 5. 健壮性：畸形输入不抛错，且策略保守 ═══════════════════════════════════
{
  for (const bad of [null, undefined, {}, { desired_change: null }, { desired_change: '   ' }, 0, 'x']) {
    let got = null, threw = false;
    try { got = classifyIntentionLifetime(bad); } catch { threw = true; }
    const tag = JSON.stringify(bad);
    ok(!threw, `畸形输入不抛错：${tag}`);
    ok(got && typeof got.shelfLifeHours === 'number' && got.shelfLifeHours > 0,
      `畸形输入仍给有界保质期：${tag} → ${got && got.shelfLifeHours}`);
  }
  // 无建立时间 → 不判过期（fail-open：宁可留着，也不误杀）
  ok(isIntentionExpired({}, { nowMs: BASE, createdAtMs: NaN }) === false, '无建立时间时不判过期（fail-open）');
  ok(intentionShelfDeadline(null, { createdAtMs: NaN }) === null, '无到期时刻时返回 null 而非 NaN');
  // 文本无法分类 → 兜底 7 天有界寿命（不无限期重试，也不像 48h 那样易误杀）
  const unknown = classifyIntentionLifetime({ desired_change: '随便一句无法归类的话' });
  ok(unknown.type === INTENTION_LIFETIME.TIME_BOUND_FACT && unknown.shelfLifeHours === 7 * 24,
    `无法归类时兜底 7 天（实际 ${unknown.type} / ${unknown.shelfLifeHours}）`);
  ok(isIntentionExpired({ desired_change: '随便一句无法归类的话' }, { nowMs: BASE, createdAtMs: BASE - 8 * 24 * H }) === true,
    '无法归类的动念放置超过兜底期（7 天）→ 判过期（不得无限期重试）');
  ok(isIntentionExpired({ desired_change: '随便一句无法归类的话' }, { nowMs: BASE, createdAtMs: BASE - 6 * 24 * H }) === false,
    '无法归类的动念在兜底期内 → 保留');
}

// ═══ 5b. 真实数据误杀回归（2026-09-18 部署当天在生产上发现）═════════════════
{
  // 这条曾在生产库被判成 unclassified_default_fact → 48h 后误收。
  // 它是关系维护类短句，没有任何时间锚点，不该过期。
  const silence = {
    desired_change: '让用户感受到即使有沉默间隔，溪语的在意依然在，且不施加回复压力',
    created_at: '2026-09-08 16:17:17',
  };
  const c = classifyIntentionLifetime(silence);
  ok(c.type === INTENTION_LIFETIME.RECURRING_RITUAL, `沉默间隔类关系短句 → recurring_ritual（实际 ${c.type} / ${c.reason}）`);
  ok(isIntentionExpired(silence, { nowMs: BASE }) === false, '沉默间隔类关系短句不得过期（放置一周以上仍应可发）');
  ok(judgeIntentionRetirement(silence, { nowMs: BASE }).retire === false, '收尾判定也不得收掉它');

  // 同类：各种关系维护措辞都不该被判时效
  const siblings = [
    '让用户在新一天开始时感受到溪语的在意与陪伴，同时不施加任何回复压力',
    '让用户感受到溪语在睡前依然惦记着他，留下一点温柔的收尾，不施加任何回复压力',
  ];
  for (const text of siblings) {
    const it = { desired_change: text, created_at: '2026-09-01 00:00:00' };
    ok(classifyIntentionLifetime(it).type === INTENTION_LIFETIME.RECURRING_RITUAL,
      `关系维护短句应判 recurring_ritual：${text.slice(0, 22)}…`);
    ok(isIntentionExpired(it, { nowMs: BASE }) === false, `关系维护短句不得过期：${text.slice(0, 22)}…`);
  }
}

// ═══ 6. 收尾判定：三种死法必须分开，且默认不误杀 ═══════════════════════════
{
  const fresh = { desired_change: '拿到用户判断新机会的两三条标准', created_at: '2026-09-14 10:10:36' };
  const stale = { desired_change: '确认订单系统汇总表 2026-09-14 数据是否还在路上', created_at: '2026-09-15 10:10:36' };

  // 默认：既没过期、也没证据 → 保留
  const r0 = judgeIntentionRetirement(fresh, { nowMs: BASE, createdAtMs: BASE - 24 * H });
  ok(r0.retire === false && r0.reason === 'still_valid', `新鲜动念保留（实际 ${r0.retire} / ${r0.reason}）`);

  // 第一层：超保质期 → expired
  const r1 = judgeIntentionRetirement(stale, { nowMs: BASE, createdAtMs: BASE - 30 * H });
  ok(r1.retire === 'expired', `超保质期 → expired（实际 ${r1.retire}）`);
  ok(String(r1.reason).startsWith('shelf_life_'), `expired 原因标明寿命类型（实际 ${r1.reason}）`);

  // 第二层：来源连续两次确认已消解 → completed
  const r2 = judgeIntentionRetirement(fresh, { nowMs: BASE, createdAtMs: BASE - 24 * H, resolvedStreak: 2 });
  ok(r2.retire === 'completed', `连续两次已消解 → completed（实际 ${r2.retire}）`);
  const r2a = judgeIntentionRetirement(fresh, { nowMs: BASE, createdAtMs: BASE - 24 * H, resolvedStreak: 1 });
  ok(r2a.retire === false, '只确认一次不收（避免一次查询失败就误杀正当跟进）');

  // 第三层：同指纹反复被拦 → suspended
  const r3 = judgeIntentionRetirement(fresh, { nowMs: BASE, createdAtMs: BASE - 24 * H, blockStreak: INTENTION_BLOCK_SUSPEND_AT });
  ok(r3.retire === 'suspended', `连续 ${INTENTION_BLOCK_SUSPEND_AT} 次被拦 → suspended（实际 ${r3.retire}）`);
  const r3a = judgeIntentionRetirement(fresh, { nowMs: BASE, createdAtMs: BASE - 24 * H, blockStreak: INTENTION_BLOCK_SUSPEND_AT - 1 });
  ok(r3a.retire === false, `未达阈值（${INTENTION_BLOCK_SUSPEND_AT - 1} 次）不收，继续尝试`);

  // 优先级：过期优先于其它两层（过期是最确定的）
  const r4 = judgeIntentionRetirement(stale, { nowMs: BASE, createdAtMs: BASE - 30 * H, resolvedStreak: 5, blockStreak: 9 });
  ok(r4.retire === 'expired', '同时满足多条时，保质期优先判 expired');

  // 误杀防线：每日仪式即使 blockStreak 很高也不因"过期"被收（但可因反复失败 suspended）
  const ritual = { desired_change: '在睡前用一句轻软的晚安收尾，让用户感到溪语今天一直惦记着他', created_at: '2026-09-01 16:00:00' };
  const r5 = judgeIntentionRetirement(ritual, { nowMs: BASE, createdAtMs: BASE - 40 * 24 * H });
  ok(r5.retire === false, `每日仪式永不过期（实际 ${r5.retire} / ${r5.reason}）`);

  // 健壮性：畸形输入不抛错
  for (const bad of [null, undefined, {}]) {
    let threw = false;
    try { judgeIntentionRetirement(bad, { nowMs: BASE, createdAtMs: NaN }); } catch { threw = true; }
    ok(!threw, `收尾判定畸形输入不抛错：${JSON.stringify(bad)}`);
  }
}

// ═══ 7. 第四层：每日仪式"已送出即完结" ═══════════════════════════════════
//
// 真实事故（2026-09-08 ~ 09-09）：同一条仪式动念 agi_mtsbnojz_029496dd1c567b
// 身上挂着 3 条 delivered 动作，时间 09-08 15:02 / 19:09 / 09-09 00:17
// —— 同一条内容在一天内被送出去 3 次。
// 成因：投递完成后动念永远停在 active，下一次生成会复用同语义键的那条。
// 这一层让"送出去一次"就是"完成一次"，同时**不能**碰还没送过的仪式
// （否则会把当天要发的早安提前收掉）。
{
  const ritual = { desired_change: '在睡前用一句轻软的晚安收尾，让用户感到溪语今天一直惦记着他', created_at: '2026-09-08 16:00:00' };
  const H2 = H;

  // 已送出且已静置 → completed
  const d1 = judgeIntentionRetirement(ritual, {
    nowMs: BASE, createdAtMs: BASE - 10 * 24 * H2, latestDeliveredAtMs: BASE - (RITUAL_SETTLED_HOURS + 1) * H2,
  });
  ok(d1.retire === 'completed', `仪式送出并静置 ${RITUAL_SETTLED_HOURS}h 后 → completed（实际 ${d1.retire} / ${d1.reason}）`);
  ok(d1.reason === 'ritual_delivered_and_settled', `第四层原因可辨识（实际 ${d1.reason}）`);

  // 边界：刚好卡在阈值上 → 收（用 >=）
  const d2 = judgeIntentionRetirement(ritual, {
    nowMs: BASE, createdAtMs: BASE - 10 * 24 * H2, latestDeliveredAtMs: BASE - RITUAL_SETTLED_HOURS * H2,
  });
  ok(d2.retire === 'completed', `刚好 ${RITUAL_SETTLED_HOURS}h → 收（闭区间）`);

  // 刚送出不久 → 保留。这条防的是"投递完立刻收掉、当天想再补一句时已经没有动念"
  const d3 = judgeIntentionRetirement(ritual, {
    nowMs: BASE, createdAtMs: BASE - 10 * 24 * H2, latestDeliveredAtMs: BASE - (RITUAL_SETTLED_HOURS - 1) * H2,
  });
  ok(d3.retire === false, `送出不足 ${RITUAL_SETTLED_HOURS}h → 保留（实际 ${d3.retire} / ${d3.reason}）`);

  // 从未送出（无投递时间）→ 保留，且**不因**第四层被收
  for (const noEvidence of [null, undefined, 0, NaN, 'x']) {
    const r = judgeIntentionRetirement(ritual, {
      nowMs: BASE, createdAtMs: BASE - 10 * 24 * H2, latestDeliveredAtMs: noEvidence,
    });
    ok(r.retire === false, `无投递证据（${JSON.stringify(noEvidence)}）不因第四层收尾（实际 ${r.retire}）`);
  }

  // 第四层只对每日仪式生效：一次性事实动念"送出去过"不等于"事情办完了"
  // （例如"确认订单表填了没"送出后还要等用户回答，不能自动完结）
  const fact = { desired_change: '拿到用户判断新机会的两三条标准，把东坝企业定位变成可筛选规则', created_at: '2026-09-10 16:00:00' };
  const d4 = judgeIntentionRetirement(fact, {
    nowMs: BASE, createdAtMs: BASE - 5 * 24 * H2, latestDeliveredAtMs: BASE - (RITUAL_SETTLED_HOURS + 40) * H2,
  });
  ok(d4.retire === false, `非仪式动念不因第四层收尾（实际 ${d4.retire} / ${d4.reason}）`);

  // 优先级：保质期仍然最优先（过期比"已送出"更确定）
  const staleMonitor = { desired_change: '确认订单系统汇总表 2026-09-14 数据是否还在路上', created_at: '2026-09-15 10:10:36' };
  const d5 = judgeIntentionRetirement(staleMonitor, {
    nowMs: BASE, createdAtMs: BASE - 30 * H2, latestDeliveredAtMs: BASE - 1 * H2,
  });
  ok(d5.retire === 'expired', `保质期优先于第四层（实际 ${d5.retire}）`);
}

console.log(`intention_lifetime: 通过 ${pass} 失败 ${fail}`);
process.exit(fail ? 1 : 0);