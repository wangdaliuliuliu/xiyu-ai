/**
 * 机位硬路由回归：
 * 1. planner 只调用一次；
 * 2. planner 写成自拍时，ACTIVITY_POV 在本地纠正为物件 POV；
 * 3. sender 再兜底一次，且无脸机位不带参考图/前置摄像头规则；
 * 4. SELFIE 仍保留人物与前置摄像头分支。
 */
import assert from 'node:assert/strict';
import { buildFinalImagePrompt } from '../src/photo_sender.mjs';
import {
  normalizePhotoPromptForShot,
  planPhotoMessage,
} from '../src/photo_planner.mjs';

const GATE = {
  allowed: true,
  reasons: [],
  todayCount: 0,
  imageProviderAvailable: true,
  limits: { dailyLimitPerCompanion: 0 },
};
const COMPANION = {
  id: null,
  current_scene: '在家',
  current_mood: 'happy',
  clothing_style: '甜美',
};
const CONFLICTING_PLANNER_JSON = JSON.stringify({
  shouldSendPhoto: true,
  mode: 'send_photo',
  photoType: 'current_activity',
  imagePrompt: 'close chest-up phone selfie, in her bedroom, a young woman with long hair, wearing a cute outfit, a desk softly blurred behind her',
  caption: '喏，给你看看',
});

let plannerCalls = 0;
const plan = await planPhotoMessage(
  {
    companion: COMPANION,
    userText: '给我看看你的书桌',
    trigger: 'user_request',
    cooldownState: GATE,
  },
  {
    llm: async () => {
      plannerCalls += 1;
      return CONFLICTING_PLANNER_JSON;
    },
  },
);

assert.equal(plannerCalls, 1, '机位纠正不能增加 planner 调用次数');
assert.equal(plan.shouldSendPhoto, true, '冲突 prompt 仍可继续发送');
assert.equal(plan.shotMode, 'ACTIVITY_POV', '书桌请求应走 ACTIVITY_POV');
assert.equal(plan.routeCorrected, true, '应记录发生过机位纠正');
assert.match(plan.imagePrompt, /给我看看你的书桌/);
const planPositive = plan.imagePrompt.replace(/do NOT show.*?composition/gi, '');
assert.doesNotMatch(planPositive, /\b(?:front[- ]camera|chest[- ]?up|waist[- ]?up|young woman|wearing|outfit|clothing)\b/i);

const finalPov = buildFinalImagePrompt({
  identityPrompt: 'IDENTITYMARKER long black hair',
  scenePrompt: CONFLICTING_PLANNER_JSON,
  providerCapabilities: { referenceImage: true },
  referenceImagePath: 'reference.png',
  shotMode: 'ACTIVITY_POV',
  userText: '给我看看你的书桌',
  currentScene: '在家',
});
assert.match(finalPov, /给我看看你的书桌/);
assert.match(finalPov, /do NOT show (?:her )?(?:face|a person)/i);
assert.doesNotMatch(finalPov, /FACE IDENTITY|IDENTITYMARKER/i);
const finalPovPositive = finalPov.replace(/do NOT show.*?composition/gi, '');
assert.doesNotMatch(finalPovPositive, /\b(?:front[- ]camera|chest[- ]?up|waist[- ]?up|young woman|wearing|outfit|clothing)\b/i);

const finalSelfie = buildFinalImagePrompt({
  identityPrompt: 'IDENTITYMARKER stable adult identity',
  scenePrompt: 'casual smartphone front-camera selfie at home, she is holding her phone up for a selfie, one arm partially extended toward the camera holding the phone, face in focus, soft daylight',
  providerCapabilities: { referenceImage: true },
  referenceImagePath: 'reference.png',
  shotMode: 'SELFIE',
});
assert.match(finalSelfie, /FACE IDENTITY/i);
assert.match(finalSelfie, /IDENTITYMARKER/);
assert.match(finalSelfie, /front-camera/i);
assert.match(finalSelfie, /direct captured output from the smartphone front-facing lens/i);
assert.match(finalSelfie, /no visible phone/i);
assert.match(finalSelfie, /ordinary unfiltered phone rendering/i);
assert.match(finalSelfie, /scene-appropriate auto-exposure, white balance, focus softness and image noise/i);
assert.match(finalSelfie, /slight motion blur when she or the camera is moving/i);
assert.match(finalSelfie, /only where the current scene supports them/i);
assert.doesNotMatch(finalSelfie, /holding (?:her|a|the) (?:smart)?phone|phone held up in front of her/i);
assert.doesNotMatch(finalSelfie, /arm (?:is )?(?:partially )?(?:visible )?(?:extended|reaching).*holding.*phone/i);

const cleanedChestLevelSelfie = normalizePhotoPromptForShot({
  shotMode: 'SELFIE',
  imagePrompt: 'Walking outside, she turns her head toward the phone, front camera held at chest level, evening breeze in her hair',
});
assert.match(cleanedChestLevelSelfie.prompt, /toward the lens|front-camera viewpoint/i);
assert.doesNotMatch(cleanedChestLevelSelfie.prompt, /toward the phone|(?:phone|front camera) held at chest level/i);

const cleanedSelfie = normalizePhotoPromptForShot({
  shotMode: 'SELFIE',
  imagePrompt: 'She sits on the bed, phone held up in front of her, holding her phone up for a selfie from a slightly high angle, warm morning light',
});
assert.equal(cleanedSelfie.corrected, true, '自拍 prompt 描述可见手机时应本地纠正');
assert.equal(cleanedSelfie.reason, 'selfie_viewpoint_conflict');
assert.doesNotMatch(cleanedSelfie.prompt, /phone held up in front of her|holding (?:her|a|the) (?:smart)?phone/i);

const physicallyConflictingSelfie = normalizePhotoPromptForShot({
  shotMode: 'SELFIE',
  imagePrompt: 'casual front-camera selfie, sitting curled up on a sofa holding a tea mug with both hands, warm room light',
});
assert.equal(physicallyConflictingSelfie.corrected, true, '双手被占用的自拍 prompt 应本地纠正');
assert.equal(physicallyConflictingSelfie.reason, 'selfie_physical_conflict');
assert.doesNotMatch(physicallyConflictingSelfie.prompt, /with both hands/i);

const alreadySafe = normalizePhotoPromptForShot({
  shotMode: 'ACTIVITY_POV',
  imagePrompt: 'first-person POV of a notebook and pen on a desk, warm desk lamp, do NOT show her face',
});
assert.equal(alreadySafe.corrected, false, '已经是物件 POV 时不应重复纠正');

console.log('photo_shot_route_smoke: 通过');
