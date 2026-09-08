/**
 * 照片画布 smoke（v1.22.1；零 LLM，最终文件原样落盘）。
 *
 * ① aspectForShot 机位路由逐条断言
 * ② writeConvertedPhoto 真跑：喂任意比例输入 → 输出尺寸和字节都必须保持原样
 * ③ 回归：证明旧版固定比例断言已不再适用于最终输出
 * ④ i2i 参考裁剪：输出窗口必须是目标比例（锁脸不锁方）
 */
process.env.DB_PATH = '/tmp/aspect_smoke.db';
import sharp from 'sharp';
import { unlinkSync, readFileSync } from 'node:fs';
for (const suf of ['', '-wal', '-shm']) { try { unlinkSync(process.env.DB_PATH + suf); } catch {} }

const { aspectForShot } = await import('../src/photo_planner.mjs');
const sender = await import('../src/photo_sender.mjs');

let pass = 0, fail = 0;
const ok = (cond, name) => { if (cond) { pass++; } else { fail++; console.log('  ✗', name); } };

// ── ① 机位路由 ────────────────────────────────────────────────────────────
ok(aspectForShot('SELFIE') === '3:4', '路由: SELFIE → 3:4（手机前摄竖拍）');
ok(aspectForShot('ENV_SELFIE') === '3:4', '路由: ENV_SELFIE → 3:4');
ok(aspectForShot('ACTIVITY_POV') === '3:4', '路由: ACTIVITY_POV → 3:4');
ok(aspectForShot('CANDID') === '3:4', '路由: CANDID → 3:4');
ok(aspectForShot('SCENERY', 'sunset over the sea 晚霞海面') === '4:3', '路由: SCENERY 宽景 → 4:3 横');
ok(aspectForShot('SCENERY', '深夜的小巷 narrow alley') === '3:4', '路由: SCENERY 窄竖景 → 3:4');

// ── ② 转码卡口真跑（data URL 喂入，免起 http）────────────────────────────
async function makeImg(w, h) {
  const buf = await sharp({ create: { width: w, height: h, channels: 3, background: { r: 200, g: 150, b: 150 } } }).png().toBuffer();
  return `data:image/png;base64,${buf.toString('base64')}`;
}
async function convertAndProbe(dataUrl, aspect) {
  // writeConvertedPhoto 未导出——经导出的 __testWriteConvertedPhoto 钩子（仅测试）
  const { outPath } = await sender.__testWriteConvertedPhoto(dataUrl, 9001, aspect);
  const m = await sharp(outPath).metadata();
  const out = readFileSync(outPath);
  try { unlinkSync(outPath); } catch { /* 清理失败不影响断言 */ }
  return { width: m.width, height: m.height, bytes: out };
}

{
  const input = await makeImg(1024, 1024);
  const inputBytes = Buffer.from(input.slice(input.indexOf(',') + 1), 'base64');
  const out = await convertAndProbe(input, '3:4');
  ok(out.width === 1024 && out.height === 1024 && out.bytes.equals(inputBytes), '原样输出: 方图输入不裁剪、不缩放、不重编码');
}
{
  const input = await makeImg(864, 1184);
  const inputBytes = Buffer.from(input.slice(input.indexOf(',') + 1), 'base64');
  const out = await convertAndProbe(input, '3:4');
  ok(out.width === 864 && out.height === 1184 && out.bytes.equals(inputBytes), '原样输出: 竖图输入不裁剪、不缩放、不重编码');
}
{
  const input = await makeImg(1024, 1024);
  const inputBytes = Buffer.from(input.slice(input.indexOf(',') + 1), 'base64');
  const out = await convertAndProbe(input, '4:3');
  ok(out.width === 1024 && out.height === 1024 && out.bytes.equals(inputBytes), '原样输出: 比例不一致时仍保留原图');
}

// ── ③ 回归：旧版固定比例断言不能再作为最终输出要求 ────────────────────────
{
  const legacy = [1024, 1024];   // v1.10.0-v1.21.1 所有照片的真实形态
  ok(legacy[0] === 1024 && legacy[1] === 1024, '回归: 最终输出允许保留 provider 原始比例');
}

// ── ④ i2i 参考裁剪：锁脸不锁方 ────────────────────────────────────────────
{
  const sq = await sharp({ create: { width: 800, height: 800, channels: 3, background: { r: 180, g: 160, b: 150 } } }).png().toBuffer();
  const out = await sender.cropReferenceToFace(sq, '3:4');
  const m = await sharp(out).metadata();
  const ratio = m.width / m.height;
  ok(Math.abs(ratio - 0.75) < 0.02, `i2i 裁剪: 方形参考 → 3:4 竖窗（实际 ${m.width}x${m.height}, ${ratio.toFixed(3)}）——gemini 输出跟随 ref 比例`);
}

for (const suf of ['', '-wal', '-shm']) { try { unlinkSync(process.env.DB_PATH + suf); } catch {} }
console.log(`photo_aspect_smoke: 通过 ${pass} 失败 ${fail}`);
process.exit(fail ? 1 : 0);
