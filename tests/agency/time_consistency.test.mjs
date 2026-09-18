/**
 * 时间一致性回归（2026-09-18）——零 IO、零模型、零数据库。
 *
 * 真实事故：9-18 上午 10:06 用户问"你在做什么"，她答
 *   「刚跟你发完照片不就躺回去了嘛，灯还关着一半呢。」
 *   「结果正经问题你还没答我呢，先说那两三条标准呗」
 * 两个毛病：
 *   ① 说"刚发完照片"——照片是 9-14 晚上的事，而她当天日程写着
 *      08:00 上早课、10:00 课间对海报。**被动回复时完全没有时间事实约束**：
 *      那套"不能在错误时段说刚放学/刚下班/刚到家"只在主动模式构造。
 *   ② 回头追 9-17 的问题像在追刚发生的事——因为【最近对话上下文】里
 *      **每一条都没有时间标注**，三天前和一分钟前长得一样。
 *
 * 本文件锁住这两条不再退回去。
 */
import assert from 'node:assert/strict';
import { buildSystemPrompt } from '../../src/companion.mjs';

let pass = 0, fail = 0;
const ok = (cond, name) => { if (cond) { pass++; } else { fail++; console.error('  [FAIL]', name); } };

const companion = { id: 1, name: '溪语', age: 22 };
const H = 3600e3;
const DAY = 24 * H;
const now = Date.now();

// ═══ 1. 被动回复也必须拿到时间事实约束 ═════════════════════════════════════
{
  const p = buildSystemPrompt(companion, { promptMode: 'reply' });
  ok(p.includes('【此刻的时间事实】'), '回复模式必须注入【此刻的时间事实】');
  ok(/上海时间 \d{2}:\d{2}/.test(p), '时间事实里要带当前时刻');
  ok(p.includes('★ 白天不要说自己刚睡下'), '回复模式必须含"白天别说自己刚睡下"约束');
  ok(p.includes('和【你今天的安排】'), '要明确要求说法与今日安排一致');

  // 主动模式同样要有（原来就有，防止抽函数时弄丢）
  const q = buildSystemPrompt(companion, { promptMode: 'proactive' });
  ok(q.includes('【此刻的时间事实】'), '主动模式仍要有时间事实约束');
  ok(q.includes('【主动消息模式】'), '主动模式块不能被抽函数弄丢');
  ok(!p.includes('【主动消息模式】'), '回复模式不应出现"主动消息模式"块');
}

// ═══ 2. 对话上下文必须标注"多久以前" ═══════════════════════════════════════
{
  const recentTurns = [
    { role: 'user', content: '在吗', created_at: new Date(now - 20 * 60_000).toISOString() },
    { role: 'assistant', content: '在呢', created_at: new Date(now - 19 * 60_000).toISOString() },
    { role: 'user', content: '看看你', created_at: new Date(now - 4 * DAY).toISOString() },
    { role: 'assistant', content: '行啦我拍给你', created_at: new Date(now - 4 * DAY + 60_000).toISOString() },
  ];
  const p = buildSystemPrompt(companion, { promptMode: 'reply', recentTurns });
  ok(p.includes('【最近对话上下文】'), '上下文块仍在');
  ok(p.includes('[20 分钟前]'), '近处对话要标成分钟前');
  ok(p.includes('[4 天前]'), '三天前的对话要标成"天前"，不能与"刚刚"混淆');
  ok(p.includes('绝不能对着几天前的内容说'), '必须显式禁止把几天前说成"刚刚"');
  ok(p.includes('前几天那事') || p.includes('前几天'), '要给出正确说法（当"前几天那事"来提）');
}

// ═══ 3. 时间标注的容错（认不出就不标，绝不乱标）═══════════════════════════
{
  // SQLite CURRENT_TIMESTAMP 风格（无 T 无 Z，按 UTC 解）
  const sqliteStyle = [{ role: 'user', content: '你好', created_at: '2026-09-14 15:39:22' }];
  const p1 = buildSystemPrompt(companion, { promptMode: 'reply', recentTurns: sqliteStyle });
  ok(/\[[\d]+ (小时|天|周|个月)前\]|\[刚刚\]/.test(p1), 'SQLite 时间格式也要能标注（实际未标注）');

  for (const bad of [null, undefined, '', 'not-a-date', 0]) {
    const p = buildSystemPrompt(companion, {
      promptMode: 'reply',
      recentTurns: [{ role: 'user', content: 'x', created_at: bad }],
    });
    ok(!/\[\]/.test(p) && !/\[NaN/.test(p), `时间不可解析时不得输出空/畸形标注（created_at=${JSON.stringify(bad)}）`);
  }

  // 未来时间（时钟漂移）不应出现负数
  const future = [{ role: 'user', content: 'x', created_at: new Date(now + 5 * 60_000).toISOString() }];
  const pf = buildSystemPrompt(companion, { promptMode: 'reply', recentTurns: future });
  ok(!/\[-/.test(pf), '未来时间不得出现负数标注');
  ok(pf.includes('[刚刚]'), '轻微时钟漂移应归为"刚刚"');
}

// ═══ 4. 没有上下文时不注入空块 ════════════════════════════════════════════
{
  const p = buildSystemPrompt(companion, { promptMode: 'reply', recentTurns: [] });
  ok(!p.includes('【最近对话上下文】'), '无对话时不应出现空的上下文块');
}

console.log(`time_consistency: 通过 ${pass} 失败 ${fail}`);
process.exit(fail ? 1 : 0);
