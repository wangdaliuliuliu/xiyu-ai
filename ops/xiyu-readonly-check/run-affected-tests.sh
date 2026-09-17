#!/bin/bash
# 只跑受本次改造影响的 4 个测试，并显示失败断言
set -u
T=/tmp/xiyu-photo-verify
cd "$T"
echo "############ 受影响测试 ############"
date
echo
for f in photo_noface_gate_smoke photo_shot_route_smoke photo_planner_prompt_smoke photo_visual_direction_smoke; do
  if node "scripts/$f.mjs" >/tmp/o 2>&1; then
    echo "  OK   $f"
  else
    echo "  FAIL $f"
    grep -E '✗|✘|Error' /tmp/o | head -5 | sed 's/^/       /'
  fi
done
echo
echo "############ 全部照片测试汇总 ############"
PASS=0; FAIL=0; FAILLIST=""
for f in scripts/photo_*.mjs scripts/*selfie*.mjs; do
  [ -f "$f" ] || continue
  if node "$f" >/tmp/o 2>&1; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); FAILLIST="$FAILLIST $(basename "$f")"; fi
done
echo "通过=$PASS 失败=$FAIL"
echo "失败清单:$FAILLIST"
