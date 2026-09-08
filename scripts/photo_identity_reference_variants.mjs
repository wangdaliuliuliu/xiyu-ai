/** Build temporary expression/angle-diverse identity references. Never changes identity.json. */
import 'dotenv/config';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { imageGenerate } from '../src/providers/image.mjs';
import { cropReferenceToFace } from '../src/photo_sender.mjs';
import { selectReferenceImage } from '../src/visual_identity.mjs';

const referencePath = selectReferenceImage(1);
if (!referencePath) throw new Error('reference missing');
const cropped = await cropReferenceToFace(readFileSync(referencePath), '1:1');
const referenceImage = `data:image/png;base64,${cropped.toString('base64')}`;
const outDir = path.resolve('scripts/_historical_selfie_eval/identity-reference-candidates');
mkdirSync(outDir, { recursive: true });

const variants = [
  {
    id: 'neutral-three-quarter',
    prompt: 'Identity reference photo of exactly the same adult woman and same facial identity as the input. Relaxed closed mouth with no smile, head turned slightly three-quarter, gaze just beside the lens, long hair worn naturally down with a few loose strands. Plain neutral indoor background, ordinary flat window light, unretouched phone-camera skin texture. Tight head-and-shoulders identity study; change expression, gaze, head angle and hairstyle from the input while preserving facial identity.',
  },
  {
    id: 'relaxed-side-glance',
    prompt: 'Identity reference photo of exactly the same adult woman and same facial identity as the input. Quiet relaxed expression, subtle asymmetry, eyes glancing to one side, head gently tilted, long hair loosely tied low with flyaway strands. Plain neutral wall, uneven ordinary ambient light, raw unfiltered phone-camera texture. Tight head-and-shoulders identity study; change expression, gaze, head angle and hairstyle from the input while preserving facial identity.',
  },
];

for (const variant of variants) {
  const url = await imageGenerate(variant.prompt, { size: '1024x1024', referenceImage });
  const buffer = String(url).startsWith('data:image/')
    ? Buffer.from(String(url).split(',')[1], 'base64')
    : Buffer.from(await (await fetch(url, { signal: AbortSignal.timeout(60_000) })).arrayBuffer());
  const out = path.join(outDir, `${variant.id}.png`);
  writeFileSync(out, buffer);
  console.log(out);
}
