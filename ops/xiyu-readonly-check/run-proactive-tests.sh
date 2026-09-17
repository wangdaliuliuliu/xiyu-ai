#!/bin/bash
# 跑主动链路相关回归（隔离目录）
set -u
T=/tmp/xiyu-obs-verify
cd "$T"
echo "############ 主动链路回归 ############"
date
echo
PASS=0; FAIL=0; FAILLIST=""
for f in scripts/proactive_*.mjs scripts/p0_regression_check.mjs scripts/initiative_*.mjs scripts/agency_*.mjs; do
  [ -f "$f" ] || continue
  if node "$f" >/tmp/o 2>&1; then
    PASS=$((PASS+1))
  else
    FAIL=$((FAIL+1))
    FAILLIST="$FAILLIST $(basename "$f")"
  fi
done
echo "通过=$PASS 失败=$FAIL"
echo "失败清单:$FAILLIST"
echo
echo "--- 失败详情（每文件前 4 行）---"
for n in $FAILLIST; do
  echo "  [$n]"
  node "scripts/$n" 2>&1 | grep -vE '^\s*$' | head -4 | sed 's/^/      /'
done
