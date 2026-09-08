/**
 * 真实 API 验证：完整走一次「规划模型 → 本地机位路由 → 生图 API」，
 * 但不调用微信上传/发送，也不写入正式照片目录。
 */
import 'dotenv/config';
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import sharp from 'sharp';
import { imageGenerate, getImageProviderCapabilities } from '../src/providers/image.mjs';
import { buildFinalImagePrompt } from '../src/photo_sender.mjs';
import { planPhotoMessage } from '../src/photo_planner.mjs';

const gate = {
  allowed: true,
  reasons: [],
  todayCount: 0,
  imageProviderAvailable: true,
  limits: { dailyLimitPerCompanion: 0 },
};
const userText = '给我看看你的书桌';
const companion = {
  id: null,
  current_scene: '在家',
  current_mood: 'happy',
  clothing_style: '甜美',
};

const startedAt = Date.now();
const plan = await planPhotoMessage({
  companion,
  userText,
  recentMessages: [],
  trigger: 'user_request',
  cooldownState: gate,
  imageProviderAvailable: true,
  imageProviderCapabilities: getImageProviderCapabilities(),
});

if (!plan.shouldSendPhoto) {
  throw new Error(`planner 未批准出图：${plan.reason || 'unknown'}`);
}
if (plan.shotMode !== 'ACTIVITY_POV') {
  throw new Error(`机位路由错误：期望 ACTIVITY_POV，实际 ${plan.shotMode}`);
}

const finalPrompt = buildFinalImagePrompt({
  identityPrompt: '',
  scenePrompt: plan.imagePrompt,
  providerCapabilities: getImageProviderCapabilities(),
  referenceImagePath: null,
  shotMode: plan.shotMode,
  userText,
  currentScene: companion.current_scene,
});

const output = await imageGenerate(finalPrompt, { size: '768x1024' });
let buffer;
if (String(output).startsWith('data:image/')) {
  buffer = Buffer.from(String(output).split(',')[1], 'base64');
} else {
  const response = await fetch(output, { signal: AbortSignal.timeout(60_000) });
  if (!response.ok) throw new Error(`下载生图结果失败 HTTP ${response.status}`);
  buffer = Buffer.from(await response.arrayBuffer());
}

const outDir = path.resolve('scripts/_route_api_out');
mkdirSync(outDir, { recursive: true });
const outPath = path.join(outDir, `desk-route-${Date.now()}.png`);
writeFileSync(outPath, buffer);
const meta = await sharp(buffer).metadata();

console.log(JSON.stringify({
  ok: true,
  provider: process.env.IMAGE_PROVIDER || 'zhipu',
  model: process.env.IMAGE_MODEL || process.env.GROK_IMAGE_MODEL || '',
  shotMode: plan.shotMode,
  aspect: plan.aspect,
  routeCorrected: plan.routeCorrected,
  output: outPath,
  width: meta.width,
  height: meta.height,
  elapsedMs: Date.now() - startedAt,
  finalPrompt,
}, null, 2));
