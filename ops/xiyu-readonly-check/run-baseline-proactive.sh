#!/bin/bash
# 同条件基线对照：把暂存区的 proactive.mjs 换回生产原版，跑同一套测试
set -u
T=/tmp/xiyu-obs-verify
cd "$T"

echo "############ 基线（生产原版 proactive.mjs）############"
date
cp /opt/xiyu-ai/src/proactive.mjs "$T/src/proactive.mjs"
echo "已换回生产原版"
echo
PASS=0; FAIL=0; FAILLIST=""
for f in scripts/proactive_*.mjs scripts/p0_regression_check.mjs scripts/initiative_*.mjs scripts/agency_*.mjs; do
  [ -f "$f" ] || continue
  if node "$f" >/tmp/o 2>&1; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); FAILLIST="$FAILLIST $(basename "$f")"; fi
done
echo "通过=$PASS 失败=$FAIL"
echo "失败清单:$FAILLIST"
