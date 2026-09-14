/**
 * 照片“视觉导演”回归：同一次规划多候选、本地选优、旧场景不冒充当前场景。
 */
import {
  planPhotoMessage,
  normalizePhotoPromptForShot,
  extractRecentPhotoFeatures,
  selectFreshPhotoContext,
  selectVisualCandidate,
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

const selection = selectVisualCandidate({
  visualCandidates: [
    {
      visualMoment: 'She stands at the track and looks into the camera with a gentle smile.',
      cameraRelationship: 'Centered portrait framing.',
      environmentalEffect: '', attentionState: 'direct eye contact',
      compositionFamily: 'centered portrait', activityVisible: false, posed: true,
      timelineRelation: 'paused', wardrobe: 'a lightweight everyday top',
      variationTags: ['smile', 'centered'],
    },
    {
      visualMoment: 'Caught halfway through a walk along the track, her pace and conversation still shaping the moment.',
      cameraRelationship: 'A loose off-axis selfie that lets the track and the nearby group share the frame.',
      environmentalEffect: 'The evening breeze shifts loose strands of hair and dusk auto-exposure leaves the moving edges slightly soft.',
      attentionState: 'attention split between the nearby conversation and the lens',
      compositionFamily: 'moving off-axis', activityVisible: true, posed: false,
      timelineRelation: 'current', wardrobe: 'a lightweight breathable everyday top suitable for walking',
      variationTags: ['walking', 'off-axis', 'wind', 'split-attention'],
    },
  ],
}, { captureIntent: 'lived', recentPhotoContext: 'repeat guard: smiling expression' });
ok(selection?.index === 1, '普通索图优先选择有活动、环境影响且非摆拍的候选');
ok((selection?.prompt.match(/realistic casual phone snapshot/gi) || []).length === 1, '通用质感词只在候选合并后追加一次');

const subtleDirectGaze = selectVisualCandidate({
  visualCandidates: [
    {
      visualMoment: 'Reclining on the sofa, she glances up toward the front camera with a gentle expression.',
      cameraRelationship: 'Loose phone selfie framing.',
      environmentalEffect: 'Even room light.', attentionState: 'attention on the front camera',
      compositionFamily: 'ordinary selfie', activityVisible: false, posed: false,
      timelineRelation: 'current', wardrobe: 'a casual tee', variationTags: ['sofa'],
    },
    {
      visualMoment: 'Still sorting the clean laundry beside her, she pauses with one sleeve half-folded and turns slightly as the shutter catches the movement.',
      cameraRelationship: 'A close off-axis front-camera angle with the laundry and bed edge sharing the frame.',
      environmentalEffect: 'Window backlight causes slight exposure unevenness and the moving sleeve edge is softly blurred.',
      attentionState: 'attention remains split between folding and the lens',
      compositionFamily: 'off-axis activity continuation', activityVisible: true, posed: false,
      timelineRelation: 'current', wardrobe: 'a casual home tee', variationTags: ['folding', 'off-axis', 'motion'],
    },
  ],
}, { captureIntent: 'lived' });
ok(subtleDirectGaze?.index === 1, 'toward front camera 等隐性正脸措辞不会再挤掉持续动作候选');

const priorFeatures = extractRecentPhotoFeatures({
  shot_mode: 'SELFIE',
  final_prompt: 'direct front-camera phone selfie in a bedroom with slightly imperfect framing',
  plan_json: JSON.stringify({
    selectedVisualCandidate: {
      attentionState: 'attention split between folding laundry and the lens',
      compositionFamily: 'off-axis activity continuation',
      variationTags: ['folding', 'moving sleeve', 'window backlight'],
    },
  }),
});
ok(priorFeatures.includes('non-frontal gaze'), '反重复摘要保留上一张的分心式注意力');
ok(priorFeatures.includes('composition:off-axis activity continuation'), '反重复摘要保留上一张的实际构图');
ok(priorFeatures.includes('visual:folding'), '反重复摘要保留上一张的动作标签');


const cleanedPhoneCue = normalizePhotoPromptForShot({
  shotMode: 'SELFIE',
  imagePrompt: 'Walking toward the cafeteria, she glances up from her phone mid-step, loose off-axis selfie framing.',
});
ok(cleanedPhoneCue.corrected && !/from her phone/i.test(cleanedPhoneCue.prompt), '自拍候选中的第二台手机语义会被清理');

const gate = {
  allowed: true, reasons: [], todayCount: 0,
  limits: { dailyLimitPerCompanion: 0 },
};
const mockResponse = JSON.stringify({
  shouldSendPhoto: true, mode: 'send_photo', photoType: 'casual_daily',
  visualCandidates: [selection.candidate], caption: '走在路上呢，给你看看现在的我～',
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
ok(plan.selectedVisualCandidate?.compositionFamily === 'moving off-axis', '选中候选元数据进入审计计划');
ok(!plan.plannerPrompt.includes('我在操场散步'), '旧消息正文不再进入照片规划 prompt');
ok(!plan.plannerPrompt.includes('persistent current scene: 操场'), '未被新鲜上下文确认的持久场景值不再暴露给规划器');
ok(plan.plannerPrompt.includes('5 个较早消息') === false && plan.plannerPrompt.includes('1 older messages excluded'), 'prompt 明确记录被排除的旧消息数量');

if (failed) {
  console.error(`\nphoto_visual_direction_smoke: ${failed} failed`);
  process.exit(1);
}
console.log('\nphoto_visual_direction_smoke: all passed');
