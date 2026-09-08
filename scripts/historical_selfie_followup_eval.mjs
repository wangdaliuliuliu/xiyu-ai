/**
 * Two-scene follow-up for the selective-concreteness selfie planner.
 * Runs planner -> final prompt -> configured image provider, but never sends to WeChat
 * and never writes production photo/audit rows.
 */
import 'dotenv/config';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import sharp from 'sharp';
import { getCompanionById } from '../src/db.mjs';
import { imageGenerate, getActiveImageProvider, getImageProviderCapabilities } from '../src/providers/image.mjs';
import { buildFinalImagePrompt, cropReferenceToFace } from '../src/photo_sender.mjs';
import { planPhotoMessage } from '../src/photo_planner.mjs';
import { buildIdentityPrompt, getVisualIdentity, selectReferenceImage, selectReferenceImages } from '../src/visual_identity.mjs';

const companion = getCompanionById(1);
if (!companion) throw new Error('companion 1 not found');

const identity = getVisualIdentity(companion.id);
const referencePath = selectReferenceImage(companion.id);
const referencePaths = selectReferenceImages(companion.id, 3);
if (!identity || !referencePath) throw new Error('visual identity/reference missing');

const capabilities = getImageProviderCapabilities();
const referenceImages = referencePaths.map((file) => {
  const cropAspect = capabilities.provider === 'iotwq' ? '1:1' : '3:4';
  return cropReferenceToFace(readFileSync(file), cropAspect);
});
const referenceImageBuffers = await Promise.all(referenceImages);
const referenceImageList = referenceImageBuffers.map((buffer) => `data:image/png;base64,${buffer.toString('base64')}`);
const referenceImage = capabilities.provider === 'iotwq' && referenceImageList.length > 1
  ? referenceImageList : referenceImageList[0];
const gate = { allowed: true, reasons: [], todayCount: 0, imageProviderAvailable: true, limits: { dailyLimitPerCompanion: 0 } };
const cases = [
  {
    id: 'after-class-walk-v2',
    hour: 11,
    currentScene: '刚下课，正往食堂走',
    userText: '我看看你，拍一张现在的样子',
    recentMessages: [
      { role: 'user', content: '你现在在干嘛？' },
      { role: 'assistant', content: '刚下课，正往食堂走呢' },
    ],
  },
  {
    id: 'sofa-tea-v2',
    hour: 17,
    currentScene: '客厅沙发，刚泡了茶窝着发呆',
    userText: '别发呆啦，我想看看你，给我发个照片吧',
    recentMessages: [
      { role: 'user', content: '哎，我可以看看你现在在哪儿吗' },
      { role: 'assistant', content: '客厅沙发，刚泡了茶窝着发呆呢' },
    ],
  },
];

const outDir = path.resolve('scripts/_historical_selfie_eval');
mkdirSync(outDir, { recursive: true });
const requestedCases = new Set(process.argv.slice(2));
const selectedCases = requestedCases.size ? cases.filter((test) => requestedCases.has(test.id)) : cases;
if (!selectedCases.length) throw new Error(`unknown case; available: ${cases.map((test) => test.id).join(', ')}`);
const results = [];

for (const test of selectedCases) {
  process.env.PHOTO_TEST_HOUR = String(test.hour);
  const plan = await planPhotoMessage({
    companion: { ...companion, current_scene: test.currentScene },
    userText: test.userText,
    recentMessages: test.recentMessages,
    trigger: 'user_request',
    cooldownState: gate,
    imageProviderAvailable: true,
    imageProviderCapabilities: capabilities,
  });
  if (!plan.shouldSendPhoto) throw new Error(`${test.id}: planner declined: ${plan.reason}`);
  if (plan.shotMode !== 'SELFIE') throw new Error(`${test.id}: expected SELFIE, got ${plan.shotMode}`);

  const finalPrompt = buildFinalImagePrompt({
    identityPrompt: buildIdentityPrompt(identity),
    scenePrompt: plan.imagePrompt,
    providerCapabilities: capabilities,
    referenceImagePath: referencePath,
    shotMode: plan.shotMode,
    userText: test.userText,
    currentScene: test.currentScene,
  });
  const started = Date.now();
  const generated = await imageGenerate(finalPrompt, { size: '768x1024', referenceImage });
  const buffer = String(generated).startsWith('data:image/')
    ? Buffer.from(String(generated).split(',')[1], 'base64')
    : Buffer.from(await (await fetch(generated, { signal: AbortSignal.timeout(60_000) })).arrayBuffer());
  const output = path.join(outDir, `${test.id}.png`);
  writeFileSync(output, buffer);
  const meta = await sharp(buffer).metadata();
  results.push({
    ...test,
    shotMode: plan.shotMode,
    aspect: plan.aspect,
    caption: plan.caption,
    selectedVisualCandidate: plan.selectedVisualCandidate,
    visualCandidates: plan.plannerRaw?.visualCandidates || [],
    photoContextFreshness: plan.photoContextFreshness,
    imagePrompt: plan.imagePrompt,
    finalPrompt,
    finalPromptLength: finalPrompt.length,
    output,
    width: meta.width,
    height: meta.height,
    generationMs: Date.now() - started,
  });
  console.log(`generated ${test.id}: ${meta.width}x${meta.height} ${results.at(-1).generationMs}ms`);
}

delete process.env.PHOTO_TEST_HOUR;
const report = path.join(outDir, 'followup-report.json');
writeFileSync(report, JSON.stringify({ generatedAt: new Date().toISOString(), ...getActiveImageProvider(), referencePath, referencePaths, results }, null, 2));
console.log(report);
