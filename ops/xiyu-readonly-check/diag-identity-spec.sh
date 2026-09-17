#!/bin/bash
# ============================================================
#  只读：查看线上实际生效的身份 spec（identity.json）
# ============================================================
set -u
echo "############ 身份 spec 核查 ############"
date
echo

D=/opt/xiyu-ai/data/companion_visuals/1
echo "##### 1. 目录结构 #####"
sudo -n ls -la "$D" 2>&1
echo "-- references --"
sudo -n ls -la "$D/references" 2>&1
echo

echo "##### 2. identity.json 全文（这是运行时真正读的）#####"
if sudo -n test -f "$D/identity.json"; then
  sudo -n cat "$D/identity.json"
else
  echo "  identity.json 不存在（则使用代码里的 buildVisualIdentitySpec 默认值）"
fi
echo

echo "##### 3. 参考图文件与 hash（核对是否文档确认的那张）#####"
for f in "$D"/references/*.png; do
  [ -f "$f" ] || continue
  echo "  $(sudo -n sha256sum "$f")"
  echo "    大小=$(sudo -n stat -c '%s' "$f") 修改时间=$(sudo -n stat -c '%y' "$f")"
done
echo "  文档确认值: 77ed460b177f17ca218ea44d245a10da748127ee8572a0b2270b1e4ed0b2518a"
echo

echo "##### 4. 是否存在多份参考图（文档要求只传 1 张）#####"
sudo -n find /opt/xiyu-ai/data/companion_visuals -name '*.png' -o -name '*.jpg' 2>/dev/null | head -20
echo

echo "##### 5. 代码里的默认身份模板（buildVisualIdentitySpec 的输出）#####"
cat > /tmp/probe-identity.mjs <<'EOF'
const m = await import('/opt/xiyu-ai/src/visual_identity.mjs');
const spec = m.buildVisualIdentitySpec({ companion: { id: 1, hair_color: '黑色', hair_style: '长发', clothing_style: '甜美', personality_tags: '["温柔","体贴"]' } });
console.log(JSON.stringify(spec, null, 2));
console.log('---- 逐字段检查是否含"定形状"词 ----');
const shape = /round|full cheeks|doe|large|small|petite|slim|thin|delicate|chin|nose|jaw|face shape|symmetr/i;
for (const [k, v] of Object.entries(spec)) {
  if (typeof v === 'string' && shape.test(v)) console.log('  [含形状词] ' + k + ' = ' + v);
}
EOF
sudo -n -u xiyu env DB_PATH=/opt/xiyu-ai/data/bot.db node /tmp/probe-identity.mjs 2>&1
echo

echo "############ 结束 ############"
