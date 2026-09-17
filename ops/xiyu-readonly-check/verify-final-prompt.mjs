// ============================================================
//  只读验证：用生产代码拼出**真正的最终生图提示词**
//  （上一步只验证了 planner 那一段，未验证 photo_sender 的完整拼装）
// ============================================================

const planner = await import('/opt/xiyu-ai/src/photo_planner.mjs');
const sender = await import('/opt/xiyu-ai/src/photo_sender.mjs');
const vi = await import('/opt/xiyu-ai/src/visual_identity.mjs');

const plan = {
  sceneMoment: 'She is sitting on her bed just after finishing laundry, one knee drawn up, glancing at the lens mid-motion.',
  framing: 'Close off-axis front-camera selfie, face in the upper half, bed and room sharing the frame.',
  action: 'One hand still holding a folded shirt, the other steadying the phone.',
  expression: 'Soft half-smile, a little tired but warm.',
  wardrobe: 'Light cream knit cardigan over a long-sleeve tee.',
  environment: 'Bedroom with folded clothes on the duvet, a bedside lamp on, a charging cable on the floor.',
  compositionFamily: 'close_off_center_selfie',
  timelineRelation: 'current',
  variationTags: ['bedroom', 'laundry', 'off-axis'],
};

const scenePrompt = planner.visualPlanPrompt(plan, { captureIntent: 'lived', shotMode: 'SELFIE' });
const identity = vi.getVisualIdentity(1);
const identityPrompt = vi.buildIdentityPrompt(identity);

const finalPrompt = sender.buildFinalImagePrompt({
  identityPrompt,
  scenePrompt,
  providerCapabilities: { provider: 'iotwq', textToImage: true, imageToImage: true, referenceImage: true },
  referenceImagePath: '/opt/xiyu-ai/data/companion_visuals/1/references/ref_001.png',
  shotMode: 'SELFIE',
  userText: '我看看你',
});

console.log('=== 身份描述（应为：无形状词）===');
console.log(identityPrompt);
console.log();
console.log('=== 最终提示词长度 ===');
console.log('scenePrompt:', scenePrompt.length, '| identityPrompt:', identityPrompt.length, '| FINAL:', finalPrompt.length);
console.log();
console.log('=== 九块落地检查 ===');
const checks = [
  ['① 参考图锚定在最前', finalPrompt.trimStart().startsWith('Use the reference image for FACE IDENTITY ONLY')],
  ['   含"同一人物/气质一致"', /keep her facial features and overall temperament consistent/i.test(finalPrompt)],
  ['② 拍摄声明(前摄)', /DIRECT FRONT-CAMERA CAPTURE/.test(finalPrompt)],
  ['③ 人物真实感(反磨皮)', /unretouched real skin|visible pores/i.test(finalPrompt)],
  ['④ 瞬间动作块', /folded shirt/.test(finalPrompt)],
  ['⑤ 表情块', /half-smile/.test(finalPrompt)],
  ['⑥ 穿搭块(具体,未被护栏替换)', /knit cardigan/.test(finalPrompt) && !/lightweight breathable casual clothes suited to the current place and activity/.test(finalPrompt)],
  ['⑦ 环境锚点', /charging cable/.test(finalPrompt)],
  ['⑧ 缺陷块', /slight motion blur|focus softness|phone-camera noise/i.test(finalPrompt)],
  ['⑨ 负面约束', /no beauty filter|no third-person view/i.test(finalPrompt)],
];
let bad = 0;
for (const [name, okFlag] of checks) {
  console.log(`  ${okFlag ? '✓' : '✗'} ${name}`);
  if (!okFlag) bad += 1;
}
console.log();
console.log('=== 身份模板是否还含形状词 ===');
const SHAPE = /round full cheeks|doe eyes|delicate chin|slim petite/i;
console.log('  identityPrompt 含形状词:', SHAPE.test(identityPrompt) ? 'YES（问题！）' : 'NO');
console.log('  finalPrompt   含形状词:', SHAPE.test(finalPrompt) ? 'YES（问题！）' : 'NO');
console.log();
console.log('VERIFY=' + (bad === 0 && !SHAPE.test(finalPrompt) ? 'PASS' : 'FAIL'));
process.exit(bad === 0 && !SHAPE.test(finalPrompt) ? 0 : 1);
