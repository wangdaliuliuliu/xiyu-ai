#!/bin/bash
# ============================================================
#  溪语预算改动 - 隔离验证
#
#  前置：本脚本调用前，调用方已经把改动后的文件放到
#          /tmp/xiyu-budget-verify/src/db.mjs
#          /tmp/xiyu-budget-verify/tests/agency/state_budget.test.mjs
#
#  做法：在临时目录里，用符号链接只读引用生产的 node_modules，
#        跑 node --test。
#        **生产 /opt/xiyu-ai 一个字节都不动。**
# ============================================================
set -u

T=/tmp/xiyu-budget-verify

echo "############ 预算改动隔离验证 ############"
date
echo "node 版本: $(node --version)"
echo

# 依赖：只读引用
if [ ! -e "$T/node_modules" ]; then
  ln -s /opt/xiyu-ai/node_modules "$T/node_modules"
fi
cp /opt/xiyu-ai/package.json "$T/package.json" 2>/dev/null

echo "##### 1. 待验证文件是否就位 #####"
for f in "$T/src/db.mjs" "$T/tests/agency/state_budget.test.mjs"; do
  if [ -f "$f" ]; then
    echo "  OK   $f ($(wc -c < "$f") 字节)"
  else
    echo "  缺失 $f  —— 调用方需要先上传"
  fi
done
echo

echo "##### 2. 待验证文件里的新逻辑 #####"
echo "-- 新的可配置上限常量 --"
grep -n "AGENCY_DAILY_ATTEMPT_CAP\|AGENCY_DAILY_TOKEN_CAP\|getAgencyBudgetCaps" "$T/src/db.mjs" 2>/dev/null | head -12
echo "-- 确认旧的硬编码 24000 已消失 --"
if grep -q "tokens > 24000" "$T/src/db.mjs" 2>/dev/null; then
  echo "  警告：仍存在 24000 硬编码"
else
  echo "  已不存在 24000 硬编码"
fi
echo

echo "##### 3. 跑测试（隔离目录）#####"
cd "$T"
node --test tests/agency/state_budget.test.mjs 2>&1 | tail -35
echo

echo "##### 4. 生产现状对照（只读）#####"
DB=/opt/xiyu-ai/data/bot.db
echo "-- 生产文件当前是否已含改动 --"
if grep -q "AGENCY_DAILY_TOKEN_CAP" /opt/xiyu-ai/src/db.mjs 2>/dev/null; then
  echo "  生产已含改动"
else
  echo "  生产尚未包含改动（本次为隔离验证，未部署）"
fi
echo "-- 最近每天 token 用量（判断新上限能支撑几次）--"
sudo -n -u xiyu sqlite3 -readonly -header -column "$DB" \
 "SELECT day, SUM(attempts) attempts, SUM(tokens) tokens FROM agency_budget_reservations GROUP BY day ORDER BY day DESC LIMIT 6;" 2>&1
echo "-- 单次 appraise 实测 token --"
sudo -n -u xiyu sqlite3 -readonly -header -column "$DB" \
 "SELECT purpose, attempts, tokens, created_at FROM agency_budget_reservations WHERE purpose='appraise' ORDER BY created_at DESC LIMIT 6;" 2>&1

echo
echo "############ 验证结束 ############"
