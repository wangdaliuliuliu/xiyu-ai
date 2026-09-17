#!/bin/bash
# ============================================================
#  只读：定位 photo gate 的 dailyLimit 为何是 0
# ============================================================
set -u
ROOT=/opt/xiyu-ai
echo "############ photo gate 诊断 ############"
date
echo

echo "##### 1. 环境变量与 .env 的真实值（用引号包住看不可见字符）#####"
echo "-- systemd Environment --"
systemctl show xiyu-ai -p Environment --no-pager 2>/dev/null | tr ' ' '\n' | grep -i 'PHOTO' || echo "  systemd 主 Environment 无 PHOTO_*"
echo "-- .env 中的行（只显示 PHOTO_*，值用 [ ] 包住以便发现空值/空格）--"
sudo -n grep -E '^\s*PHOTO' "$ROOT/.env" 2>/dev/null | sed -E 's/^([A-Z_]+)=(.*)$/\1=[\2]/' || echo "  .env 无 PHOTO_*"
echo "-- 服务进程实际环境（权威）--"
PID=$(systemctl show xiyu-ai -p MainPID --value)
sudo -n cat /proc/$PID/environ 2>/dev/null | tr '\0' '\n' | grep -iE 'PHOTO|IMAGE_' | sed -E 's/^([A-Z_]+)=(.*)$/\1=[\2]/' || echo "  读不到"
echo

echo "##### 2. 生产 photo_planner.mjs 的 numberEnv 实现 #####"
echo "  sha256=$(sha256sum "$ROOT/src/photo_planner.mjs" | awk '{print $1}')"
echo "  行数=$(wc -l < "$ROOT/src/photo_planner.mjs")"
echo "-- numberEnv 附近 --"
grep -n -A8 'function numberEnv' "$ROOT/src/photo_planner.mjs" | head -14
echo "-- dailyLimitPerCompanion 赋值行 --"
grep -n 'dailyLimitPerCompanion' "$ROOT/src/photo_planner.mjs" | head -5
echo "-- daily limit 判定行 --"
grep -n "daily limit" "$ROOT/src/photo_planner.mjs" | head -5
echo

echo "##### 3. 用生产代码实测 numberEnv 的行为 #####"
cat > /tmp/probe-photo-gate.mjs <<'EOF'
// 直接复现 photo_planner 里 numberEnv 的逻辑，验证空值/未设置两种输入
function numberEnv(name, fallback, min = 0) {
  const raw = process.env[name];
  if (raw == null || raw === '') return Math.max(min, fallback);
  const n = Number(raw);
  return Math.max(min, Number.isFinite(n) ? n : fallback);
}
delete process.env.PHOTO_DAILY_LIMIT_PER_COMPANION;
console.log('未设置            →', numberEnv('PHOTO_DAILY_LIMIT_PER_COMPANION', 3, 0));
process.env.PHOTO_DAILY_LIMIT_PER_COMPANION = '';
console.log('空字符串          →', numberEnv('PHOTO_DAILY_LIMIT_PER_COMPANION', 3, 0));
process.env.PHOTO_DAILY_LIMIT_PER_COMPANION = ' ';
console.log('单个空格          →', numberEnv('PHOTO_DAILY_LIMIT_PER_COMPANION', 3, 0));
process.env.PHOTO_DAILY_LIMIT_PER_COMPANION = '0';
console.log('"0"               →', numberEnv('PHOTO_DAILY_LIMIT_PER_COMPANION', 3, 0));
process.env.PHOTO_DAILY_LIMIT_PER_COMPANION = 'undefined';
console.log('"undefined"       →', numberEnv('PHOTO_DAILY_LIMIT_PER_COMPANION', 3, 0));
process.env.PHOTO_DAILY_LIMIT_PER_COMPANION = 'null';
console.log('"null"            →', numberEnv('PHOTO_DAILY_LIMIT_PER_COMPANION', 3, 0));
EOF
node /tmp/probe-photo-gate.mjs
echo

echo "##### 4. 实际用生产模块读 gate（只读，不生成图）#####"
cat > /tmp/probe-photo-module.mjs <<'EOF'
const mod = await import('/opt/xiyu-ai/src/photo_planner.mjs');
const names = Object.keys(mod);
console.log('photo_planner 导出:', names.join(', '));
EOF
node /tmp/probe-photo-module.mjs 2>&1 | head -5
echo

echo "##### 5. 今天实际发出照片了吗（photo audit 与对话）#####"
DB=$ROOT/data/bot.db
echo "-- photo_request_audit 今天 --"
sudo -n -u xiyu sqlite3 -readonly -header -column "$DB" "SELECT id, substr(created_at,1,19) t, substr(user_text,1,30) ut FROM photo_request_audit ORDER BY id DESC LIMIT 8;" 2>&1
echo "-- 今天她说过的与照片有关的话 --"
sudo -n -u xiyu sqlite3 -readonly -header -column "$DB" "SELECT datetime(created_at) t, role, substr(replace(content,char(10),' '),1,60) c FROM companion_conversation_turns WHERE date(created_at)>='2026-09-14' AND (content LIKE '%拍%' OR content LIKE '%照片%' OR content LIKE '%看%你%') ORDER BY id DESC LIMIT 12;" 2>&1
echo

echo "############ 结束 ############"
