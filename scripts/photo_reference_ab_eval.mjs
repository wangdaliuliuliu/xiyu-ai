/** Same selected visual direction, with and without i2i reference. Never sends to WeChat. */
import 'dotenv/config';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import sharp from 'sharp';
import { imageGenerate, getImageProviderCapabilities } from '../src/providers/image.mjs';
import { buildFinalImagePrompt, cropReferenceToFace } from '../src/photo_sender.mjs';
import { buildIdentityPrompt, getVisualIdentity, selectReferenceImage } from '../src/visual_identity.mjs';

const reportPath = path.resolve('scripts/_historical_selfie_eval/followup-report.json');
const report = JSON.parse(readFileSync(reportPath, 'utf8'));
const source = report.results?.[0];
if (!source?.imagePrompt) throw new Error('missing source imagePrompt');

const identity = getVisualIdentity(1);
const referencePath = selectReferenceImage(1);
const capabilities = getImageProviderCapabilities();
const outDir = path.resolve('scripts/_historical_selfie_eval');
mkdirSync(outDir, { recursive: true });

const variants = [
  { id: 'same-direction-with-reference', useReference: true, referenceAspect: '3:4' },
  { id: 'same-direction-with-square-face-reference', useReference: true, referenceAspect: '1:1' },
  { id: 'same-direction-with-three-identity-references', useReference: true, referenceAspect: '1:1', multiReference: true },
  { id: 'same-direction-without-reference', useReference: false },
];
const requested = new Set(process.argv.slice(2));
const selectedVariants = requested.size ? variants.filter((variant) => requested.has(variant.id)) : variants;
if (!selectedVariants.length) throw new Error(`unknown variant; available: ${variants.map((variant) => variant.id).join(', ')}`);
for (const variant of selectedVariants) {
  const prompt = buildFinalImagePrompt({
    identityPrompt: buildIdentityPrompt(identity), scenePrompt: source.imagePrompt,
    providerCapabilities: capabilities,
    referenceImagePath: variant.useReference ? referencePath : null,
    shotMode: source.shotMode || 'SELFIE',
  });
  let referenceImage = null;
  if (variant.useReference) {
    const cropped = await cropReferenceToFace(readFileSync(referencePath), variant.referenceAspect || '3:4');
    referenceImage = `data:image/png;base64,${cropped.toString('base64')}`;
    if (variant.multiReference) {
      const candidateDir = path.join(outDir, 'identity-reference-candidates');
      const extraPaths = ['neutral-three-quarter.png', 'relaxed-side-glance.png']
        .map((name) => path.join(candidateDir, name)).filter(existsSync);
      referenceImage = [referenceImage, ...extraPaths.map((file) => `data:image/png;base64,${readFileSync(file).toString('base64')}`)];
    }
  }
  const started = Date.now();
  const url = await imageGenerate(prompt, { size: '768x1024', referenceImage });
  const buffer = String(url).startsWith('data:image/')
    ? Buffer.from(String(url).split(',')[1], 'base64')
    : Buffer.from(await (await fetch(url, { signal: AbortSignal.timeout(60_000) })).arrayBuffer());
  const out = path.join(outDir, `${variant.id}.png`);
  writeFileSync(out, buffer);
  const meta = await sharp(buffer).metadata();
  console.log(`${variant.id}: ${meta.width}x${meta.height}, ${Date.now() - started}ms, ${out}`);
}
