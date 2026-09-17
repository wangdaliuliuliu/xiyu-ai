// ============================================================
//  一次性运维：把生产 identity.json 里的"定形状"词清掉
//
//  背景（2026-09-15，用户决定）：
//    身份参考图由用户亲自锁定，脸型不再由文字承载。但线上 identity.json
//    是 2026-09-06 生成的，里面缓存着旧模板的完整拷贝：
//      face: "soft round full cheeks, large warm doe eyes, small delicate chin, ..."
//      body: "slim petite youthful frame, ..."
//    这些词会和参考图争抢身份定义。**只改代码不会生效**——运行时读的是这个文件。
//
//  做法：
//    1. 备份原文件（带时间戳）
//    2. 只替换 identitySpec 里的 face / body 两个字段
//    3. 保留：ageLook（成年标记，安全相关）、hair（角色设定）、
//             style（服装倾向）、vibe、avoid（禁用清单）、referenceImages
//
//  用法：sudo -u xiyu env DB_PATH=/opt/xiyu-ai/data/bot.db node sync-identity-spec.mjs
// ============================================================

import { readFileSync, writeFileSync, copyFileSync, existsSync } from 'node:fs';
import path from 'node:path';

const DIR = '/opt/xiyu-ai/data/companion_visuals/1';
const FILE = path.join(DIR, 'identity.json');

if (!existsSync(FILE)) {
  console.error('identity.json 不存在，无需处理:', FILE);
  process.exit(1);
}

const raw = readFileSync(FILE, 'utf8');
const original = JSON.parse(raw);

// 备份（同一目录，带时间戳，可回滚）
const stamp = new Date().toISOString().replace(/[:.]/g, '-');
const backup = `${FILE}.before-shapespec-${stamp}`;
copyFileSync(FILE, backup);
console.log('已备份:', backup);

const spec = original.identitySpec || {};
console.log('--- 原值 ---');
console.log('  face:', JSON.stringify(spec.face || ''));
console.log('  body:', JSON.stringify(spec.body || ''));

// 新值：只保留"真人质感"，删除一切决定脸型/五官形状/体型的词。
// ageLook 保留不动（成年标记 + "soft natural facial features" 本身不是形状规定）。
const NEW_FACE = 'natural skin texture, relaxed fresh makeup-free complexion';
const NEW_BODY = 'natural proportions, modest casual styling';

const updated = {
  ...original,
  updatedAt: new Date().toISOString(),
  identitySpec: {
    ...spec,
    face: NEW_FACE,
    body: NEW_BODY,
  },
};

writeFileSync(FILE, JSON.stringify(updated, null, 2) + '\n', 'utf8');

// 复核
const check = JSON.parse(readFileSync(FILE, 'utf8'));
console.log('--- 新值 ---');
console.log('  face:', JSON.stringify(check.identitySpec.face));
console.log('  body:', JSON.stringify(check.identitySpec.body));
console.log('  ageLook 保留:', JSON.stringify(check.identitySpec.ageLook));
console.log('  hair 保留:', JSON.stringify(check.identitySpec.hair));
console.log('  style 保留:', JSON.stringify(check.identitySpec.style));
console.log('  avoid 保留:', Array.isArray(check.identitySpec.avoid) ? check.identitySpec.avoid.length + ' 项' : '无');
console.log('  referenceImages 保留:', JSON.stringify(check.referenceImages));

const SHAPE_RE = /round|full cheeks|doe|large warm|delicate chin|petite|slim|symmetr/i;
const offending = ['face', 'body', 'ageLook', 'hair', 'style', 'vibe']
  .filter((k) => SHAPE_RE.test(String(check.identitySpec[k] || '')));
console.log('残留形状词的字段:', offending.length ? offending.join(',') : '无');
console.log('SYNC=' + (offending.length === 0 ? 'PASS' : 'FAIL'));
process.exit(offending.length === 0 ? 0 : 1);
