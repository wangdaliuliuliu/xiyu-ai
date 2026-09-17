/**
 * 照片「画面方案」回归（2026-09-15 重写）。
 *
 * 原版测的是「多候选 + 本地选优」（selectVisualCandidate）。该机制已按用户决定
 * 移除，改为「规划模型一次给出一份九块方案」。本文件保留原有测试**意图**，
 * 改用新函数与新结构：
 *   - 一次只产出一份方案（不再有 index/score）
 *   - 九块各写各的，块内不重复
 *   - 反重复摘要仍能读到上一张的构图/动作/视线
 *   - 审计计划里落的是 visualPlan（原为 selectedVisualCandidate）
 * 另新增：九块拼装顺序、空方案被拒、framing 居中在 LIVED 下被改写。
 */
import {
  planPhotoMessage,
  normalizePhotoPromptForShot,
  extractRecentPhotoFeatures,
  selectFreshPhotoContext,
  normalizeVisualPlan,
  visualPlanPrompt,
} from '../src/photo_planner.mjs';

let failed = 0;
function ok(condition, label) {
  if (condition) console.log(`  ✓ ${label}`);
  else { console.error(`  ✗ ${label}`); failed += 1; }
}

const now = new Date('2026-09-06T12:00:00.000Z'); // 上海 20:00
const fresh = selectFreshPhotoContext([
  { direction: 'out', content: '我在操场散步', created_at: '2026-09-06 07:00:00' }, // 上海 15:00
  { direction: 'in', content: '我看看你', created_at: '2026-09-06 12:00:00' },
], { now, maxAgeMinutes: 90 });
ok(fresh.messages.length === 1 && fresh.staleCount === 1, '五小时前的场景消息从当前照片上下文剔除');

// ── 九块方案：结构与清洗 ────────────────────────────────────────────────────
const walkingPlan = {
  sceneMoment: 'Caught halfway through a walk along the track, her pace and conversation still shaping the moment.',
  framing: 'A loose off-axis selfie that lets the track and the nearby group share the frame.',
  action: 'Still mid-stride, one hand gesturing as she keeps talking.',
  expression: 'Amused half-smile, not a posed grin.',
  wardrobe: 'Lightweight breathable everyday top over loose trousers, suitable for walking.',
  environment: 'Evening track with a few passersby, low warm dusk light, a water bottle and towel on the bench behind her.',
  compositionFamily: 'moving off-axis',
  timelineRelation: 'current',
  variationTags: ['walking', 'off-axis', 'wind', 'split-attention'],
};

const normalized = normalizeVisualPlan(walkingPlan, { captureIntent: 'lived', shotMode: 'SELFIE' });
ok(normalized?.compositionFamily === 'moving off-axis', '九块方案可被规范化');
ok(normalized?.timelineRelation === 'current', 'timelineRelation 正常保留');
ok(normalized?.expression === 'Amused half-smile, not a posed grin.', '表情独立成块');

const assembled = visualPlanPrompt(walkingPlan, { captureIntent: 'lived', shotMode: 'SELFIE' });
ok(assembled.includes('Caught halfway through a walk'), '拼装包含场景瞬间');
ok(assembled.includes('Loose off-axis selfie') || assembled.includes('loose off-axis selfie'), '拼装包含取景');
ok(assembled.includes('Amused half-smile'), '拼装包含表情');
ok(assembled.includes('Lightweight breathable'), '拼装包含穿搭');
ok(assembled.includes('water bottle and towel'), '拼装包含环境生活物件');
// 顺序：场景 → 取景 → 动作 → 表情 → 穿搭 → 环境
const idx = {
  scene: assembled.indexOf('Caught halfway'),
  framing: assembled.toLowerCase().indexOf('loose off-axis selfie'),
  action: assembled.indexOf('mid-stride'),
  expression: assembled.indexOf('Amused half-smile'),
  wardrobe: assembled.indexOf('Lightweight breathable'),
  environment: assembled.indexOf('water bottle and towel'),
};
ok(idx.scene < idx.framing && idx.framing < idx.action && idx.action < idx.expression
  && idx.expression < idx.wardrobe && idx.wardrobe < idx.environment,
  '九块按固定顺序拼装（场景→取景→动作→表情→穿搭→环境）');

// 空方案必须被拒，不能产出只有质感词的"空洞提示词"
ok(normalizeVisualPlan({}, {}) === null, '空方案被拒（无场景也无动作）');
ok(normalizeVisualPlan({ sceneMoment: 'x' }, {}) === null, '只有场景没有取景/环境时被拒');
ok(visualPlanPrompt({}, {}) === '', '空方案拼装结果为空串');

// LIVED 下"居中/对称"被改写为偏轴（保留旧候选逻辑的意图）
const centered = normalizeVisualPlan({
  sceneMoment: 'She sits on the sofa.',
  framing: 'Centered symmetrical selfie facing forward.',
  environment: 'Living room, warm lamp.',
}, { captureIntent: 'lived', shotMode: 'SELFIE' });
ok(!/\bsymmetrical\b/i.test(centered.framing), 'LIVED 下对称取景被改写');
ok(!/\bcentered\b/i.test(centered.framing), 'LIVED 下居中取景被改写');
const posedCentered = normalizeVisualPlan({
  sceneMoment: 'She sits on the sofa.',
  framing: 'Centered symmetrical selfie facing forward.',
  environment: 'Living room, warm lamp.',
}, { captureIntent: 'posed', shotMode: 'SELFIE' });
ok(/centered/i.test(posedCentered.framing), 'POSED 意图下允许保留居中（对方明确要端正照）');

// 自拍机位里不保留"越过肩膀"这种外部视角措辞
const overShoulder = normalizeVisualPlan({
  sceneMoment: 'She stands in the kitchen.',
  framing: 'Over-the-shoulder framing from behind.',
  environment: 'Kitchen with a kettle and a mug.',
}, { captureIntent: 'lived', shotMode: 'SELFIE' });
ok(!/over[- ]the[- ]shoulder|over[- ]her[- ]shoulder/i.test(overShoulder.framing), '自拍不保留越过肩膀措辞');

// ── 反重复摘要：新结构 + 旧记录兼容 ────────────────────────────────────────
const priorFeatures = extractRecentPhotoFeatures({
  shot_mode: 'SELFIE',
  final_prompt: 'direct front-camera phone selfie in a bedroom with slightly imperfect framing',
  plan_json: JSON.stringify({
    visualPlan: {
      compositionFamily: 'off-axis activity continuation',
      timelineRelation: 'current',
      variationTags: ['folding', 'moving sleeve', 'window backlight'],
      blocks: { action: 'attention split between folding laundry and the lens' },
    },
  }),
});
ok(priorFeatures.includes('non-frontal gaze'), '反重复摘要保留上一张的分心式注意力（新结构）');
ok(priorFeatures.includes('composition:off-axis activity continuation'), '反重复摘要保留上一张的实际构图');
ok(priorFeatures.includes('visual:folding'), '反重复摘要保留上一张的动作标签');

// 旧审计记录（selectedVisualCandidate）仍须能读出特征，否则改动前的照片突然"不算重复"
const legacyFeatures = extractRecentPhotoFeatures({
  shot_mode: 'SELFIE',
  final_prompt: 'front-camera phone selfie off-center in a bedroom',
  plan_json: JSON.stringify({
    selectedVisualCandidate: {
      attentionState: 'attention split between folding laundry and the lens',
      compositionFamily: 'off-axis activity continuation',
      variationTags: ['folding'],
    },
  }),
});
ok(legacyFeatures.includes('non-frontal gaze'), '兼容旧记录：selectedVisualCandidate 仍可读');
ok(legacyFeatures.includes('composition:off-axis activity continuation'), '兼容旧记录：构图仍可读');

// ── 第二台手机语义清理（原有断言，逻辑未变）────────────────────────────────
const cleanedPhoneCue = normalizePhotoPromptForShot({
  shotMode: 'SELFIE',
  imagePrompt: 'Walking toward the cafeteria, she glances up from her phone mid-step, loose off-axis selfie framing.',
});
ok(cleanedPhoneCue.corrected && !/from her phone/i.test(cleanedPhoneCue.prompt), '自拍中的第二台手机语义会被清理');

// ── 端到端：新结构产出计划 ──────────────────────────────────────────────────
const gate = {
  allowed: true, reasons: [], todayCount: 0,
  limits: { dailyLimitPerCompanion: 0 },
};
const mockResponse = JSON.stringify({
  shouldSendPhoto: true, mode: 'send_photo', photoType: 'casual_daily',
  visualPlan: walkingPlan,
  caption: '走在路上呢，给你看看现在的我～',
  maintainIdentity: true, reason: 'user asked',
});
const plan = await planPhotoMessage({
  companion: {
    id: null, name: '溪语', current_scene: '操场', current_mood: '开心',
    hair_color: '黑色', hair_style: '长发', clothing_style: '清新',
  },
  userText: '我看看你',
  recentMessages: [
    { direction: 'out', content: '我在操场散步', created_at: '2026-09-06 07:00:00' },
    { direction: 'in', content: '我看看你', created_at: '2026-09-06 12:00:00' },
  ],
  trigger: 'user_request', cooldownState: gate, imageProviderAvailable: true,
}, { mockResponse, now });

ok(plan.shouldSendPhoto === true && plan.shotMode === 'SELFIE', '新结构可正常产出 SELFIE 计划');
ok(plan.visualPlan?.compositionFamily === 'moving off-axis', '单份方案元数据进入审计计划');
ok(plan.visualPlan?.blocks?.wardrobe?.includes('Lightweight breathable'), '审计计划逐块留存穿搭（可回看哪块写了什么）');
ok(plan.imagePrompt.includes('Caught halfway through a walk'), '最终 imagePrompt 含场景瞬间');
ok(!plan.plannerPrompt.includes('我在操场散步'), '旧消息正文不再进入照片规划 prompt');
ok(!plan.plannerPrompt.includes('persistent current scene: 操场'), '未被新鲜上下文确认的持久场景值不再暴露给规划器');
ok(plan.plannerPrompt.includes('5 个较早消息') === false && plan.plannerPrompt.includes('1 older messages excluded'), 'prompt 明确记录被排除的旧消息数量');
// 新提示词不应再要求多个候选
ok(!plan.plannerPrompt.includes('visualCandidates'), '规划提示词不再要求 visualCandidates 多候选');
ok(plan.plannerPrompt.includes('visualPlan'), '规划提示词改为要求 visualPlan 单方案');
ok(plan.plannerPrompt.includes('expression'), '规划提示词包含表情块要求');
ok(plan.plannerPrompt.includes('action'), '规划提示词包含瞬间动作块要求');

// 服装护栏已移除：模型给长袖/针织不应再被替换成通用句
const wardrobePlan = normalizeVisualPlan({
  sceneMoment: 'She is sitting on the bed after laundry.',
  framing: 'Close off-axis front-camera selfie.',
  wardrobe: 'Light cream knit cardigan over a long-sleeve tee.',
  environment: 'Bedroom with folded clothes and a bedside lamp.',
}, { captureIntent: 'lived', shotMode: 'SELFIE' });
ok(/knit cardigan/i.test(wardrobePlan.wardrobe), '长袖/针织不再被季节护栏替换（护栏已移除）');
ok(!/lightweight breathable casual clothes suited to the current place and activity/i.test(wardrobePlan.wardrobe),
  '不再出现被替换后的通用服装句');

if (failed) {
  console.error(`\nphoto_visual_direction_smoke: ${failed} failed`);
  process.exit(1);
}
console.log('\nphoto_visual_direction_smoke: all passed');
