/**
 * photo_planner_prompt_smoke —— 锁死 v1.21.6 P0 静默断图回归。
 *
 * 事故：d22bf73(v1.21.2) 把 buildPlannerPrompt 改成返回 {prompt, shotMode} 对象，
 * 但 planPhotoMessage 仍 `const prompt = buildPlannerPrompt(...)` 当字符串接收，
 * 把整个对象当 message content 传给 LLM →「content should be a string」400 →
 * 自 2026-06-11 起所有照片（user 索图 + proactive 场景照）静默失败 1.5 天，
 * 被 fail-open 吞成 WARN 日志。
 *
 * 红色验证（必须能抓住坏形态）：
 *   - planner 收到的 prompt 必须是 string，且不是 "[object Object]"
 *   - 通过的 plan 必须挂上 shotMode + aspect（比例路由的数据源，曾是死代码）
 *   - shotMode→aspect 路由正确（SELFIE→3:4，宽景 SCENERY→4:3，窄竖景→3:4）
 */
import { planPhotoMessage, aspectForShot, seasonalClothingHint } from '../src/photo_planner.mjs';

let pass = 0, fail = 0;
const ok = (cond, name) => { if (cond) { pass++; } else { fail++; console.log('  ✗', name); } };

const ALLOWED_GATE = { allowed: true, reasons: [], todayCount: 0, imageProviderAvailable: true, limits: { dailyLimitPerCompanion: 3 } };
const COMPANION = { id: 1, name: '小溪', current_scene: '在家', current_mood: 'happy', clothing_style: '甜美' };
const APPROVED_JSON = JSON.stringify({
  shouldSendPhoto: true, mode: 'send_photo', photoType: 'casual_daily',
  imagePrompt: 'realistic casual phone snapshot of a young woman, natural lighting, everyday environment, slightly imperfect framing, safe adult everyday content, soft warm smile',
  caption: '喏 刚拍的', delayImageMs: 1200, delayCaptionMs: 900,
});

async function planWith(userText) {
  let seenPrompt = null;
  const plan = await planPhotoMessage(
    { companion: COMPANION, userText, trigger: 'user_request', cooldownState: ALLOWED_GATE },
    { llm: async ({ prompt }) => { seenPrompt = prompt; return APPROVED_JSON; } },
  );
  return { plan, seenPrompt };
}

// ── 核心回归：planner 收到的必须是字符串 prompt ──
{
  const { plan, seenPrompt } = await planWith('发张自拍看看你');
  ok(typeof seenPrompt === 'string', `planner 收到 string prompt（实测 ${typeof seenPrompt}）`);
  ok(seenPrompt !== '[object Object]' && !String(seenPrompt).includes('[object Object]'),
    '红色验证：prompt 不是 "[object Object]"（坏形态会是它）');
  ok(/请判断是否适合发送一张生活感照片/.test(String(seenPrompt)), 'prompt 含 planner 正文（确是真 prompt 非空壳）');
  ok(/设计 3 个彼此不同但都真实可拍的候选画面/.test(String(seenPrompt)), '一次规划生成三个视觉候选');
  ok(/围绕一个统一的生活瞬间/.test(String(seenPrompt)), '人物、活动和环境围绕同一瞬间');
  ok(/不要逐个规定身体部位或每只手/.test(String(seenPrompt)), '内部调度不把肢体拆成硬清单');
  ok(/手机前置摄像头最终拍到的自拍成片/.test(String(seenPrompt)), '候选始终服从自拍机位');
  ok(/环境不能只是人物背后的布景/.test(String(seenPrompt)), '环境必须真正参与画面状态');
  ok(/道具也不能只是证明上下文的标签/.test(String(seenPrompt)), '道具不作为机械上下文标签');
  ok(/只有被选中候选的四个画面描述字段会进入生图提示词/.test(String(seenPrompt)), '内部字段不会全部污染最终提示词');
  ok(!/像摄影师一样点明与场景匹配的光位/.test(String(seenPrompt)), '不再要求摄影师式布光');
  ok(/忠实使用现场原有环境光和普通手机自动曝光/.test(String(seenPrompt)), '使用现场光与普通手机自动曝光');
  ok(/seasonal clothing baseline:/.test(String(seenPrompt)), 'planner 收到季节级穿衣基线');
  ok(/当前地点、室内外环境与正在进行的活动/.test(String(seenPrompt)), '服装同时服从地点、环境和活动');
  ok(/不把毛衣、开衫或厚外套当成默认单品/.test(String(seenPrompt)), '不再默认毛衣开衫');
  ok(plan.shouldSendPhoto === true, '通过的 plan shouldSendPhoto=true');
  ok(plan.shotMode === 'SELFIE', `自拍请求 → shotMode=SELFIE（实测 ${plan.shotMode}）`);
  ok(plan.aspect === '3:4', `SELFIE → aspect=3:4（实测 ${plan.aspect}）`);
}

// ── shotMode→aspect 路由（比例防回归，曾因 plan 不挂 shotMode 而全 3:4）──
{
  const { plan } = await planWith('给我看看外面的晚霞');
  ok(plan.shotMode === 'SCENERY', `晚霞请求 → shotMode=SCENERY（实测 ${plan.shotMode}）`);
  ok(plan.aspect === '4:3', `宽景 SCENERY → aspect=4:3（实测 ${plan.aspect}）`);
}
{
  const { plan } = await planWith('拍拍窗外那棵树');
  ok(plan.shotMode === 'SCENERY', `树景请求 → shotMode=SCENERY（实测 ${plan.shotMode}）`);
  ok(plan.aspect === '3:4', `窄竖景（树）→ aspect=3:4（实测 ${plan.aspect}）`);
}

// ── 纯函数 aspectForShot 直测 ──
ok(aspectForShot('SELFIE') === '3:4', 'aspectForShot SELFIE=3:4');
ok(aspectForShot('SCENERY', '海边') === '4:3', 'aspectForShot 宽景=4:3');
ok(aspectForShot('SCENERY', '高塔') === '3:4', 'aspectForShot 窄竖景=3:4');
ok(aspectForShot('') === '3:4', 'aspectForShot 空 shotMode 兜底 3:4');

// 季节基线不依赖系统当天日期，四季与 9 月初过渡期分别锁定。
ok(/winter seasonal baseline/.test(seasonalClothingHint(new Date('2026-01-15T04:00:00Z'))), '1月→冬季基线');
ok(/spring seasonal baseline/.test(seasonalClothingHint(new Date('2026-04-15T04:00:00Z'))), '4月→春季基线');
ok(/summer seasonal baseline/.test(seasonalClothingHint(new Date('2026-07-15T04:00:00Z'))), '7月→夏季基线');
ok(/early-autumn warm transition baseline/.test(seasonalClothingHint(new Date('2026-09-05T04:00:00Z'))), '9月初→轻薄夏秋过渡基线');

// ── 拒绝分支不挂 shotMode 也不炸 ──
{
  const plan = await planPhotoMessage(
    { companion: COMPANION, userText: '在吗', trigger: 'user_request', cooldownState: ALLOWED_GATE },
    { mockResponse: JSON.stringify({ shouldSendPhoto: false, mode: 'text_only', caption: '现在不太方便拍呢', canRetakeLater: true }) },
  );
  ok(plan.shouldSendPhoto === false && plan.mode === 'text_only', '拒绝分支正常返回 text_only');
  ok(plan.canRetakeLater === true, '拒绝分支保留 canRetakeLater');
}

console.log(`\nphoto_planner_prompt_smoke: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
