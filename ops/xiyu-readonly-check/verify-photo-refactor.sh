#!/bin/bash
# ============================================================
#  照片链路改造 — 隔离验证（不修改生产任何文件）
#
#  前置：调用方已把改动文件放到 /tmp/xiyu-photo-verify/
#  做法：临时目录 + 符号链接只读引用生产 node_modules，跑全部照片相关测试。
# ============================================================
set -u
T=/tmp/xiyu-photo-verify
ROOT=/opt/xiyu-ai

echo "############ 照片链路改造隔离验证 ############"
date
echo "node: $(node --version)"
echo

[ -e "$T/node_modules" ] || ln -s "$ROOT/node_modules" "$T/node_modules"
cp "$ROOT/package.json" "$T/package.json" 2>/dev/null

echo "##### 1. 改动文件是否就位 #####"
for f in src/photo_planner.mjs src/photo_sender.mjs src/visual_identity.mjs scripts/photo_visual_direction_smoke.mjs; do
  [ -f "$T/$f" ] && echo "  OK   $f ($(wc -c < "$T/$f") 字节)" || echo "  缺失 $f"
done
echo "-- 新函数是否存在 --"
grep -c "export function normalizeVisualPlan\|export function visualPlanPrompt" "$T/src/photo_planner.mjs"
echo "-- 旧函数是否已删 --"
grep -c "selectVisualCandidate\|visualCandidates" "$T/src/photo_planner.mjs" || true
echo "-- 形状词是否已清除 --"
if grep -qE "round full cheeks|doe eyes|delicate chin|slim petite" "$T/src/visual_identity.mjs"; then
  echo "  仍存在形状词！"
else
  echo "  形状词已清除"
fi
echo "-- 服装护栏是否已移除 --"
if grep -q "lightweight breathable casual clothes suited to the current place and activity" "$T/src/photo_planner.mjs"; then
  echo "  护栏替换句仍存在"
else
  echo "  护栏替换句已移除"
fi
echo "-- 参考图锚定句是否已在最前 --"
grep -c "definitive identity anchor" "$T/src/photo_sender.mjs"
echo

echo "##### 2. 逐个跑照片相关测试 #####"
cd "$T"
PASS=0; FAIL=0; FAILED_LIST=""
for f in scripts/photo_*.mjs scripts/*selfie*.mjs; do
  [ -f "$f" ] || continue
  OUT=$(node "$f" 2>&1)
  RC=$?
  if [ $RC -eq 0 ]; then
    PASS=$((PASS+1))
    echo "  ✓ $(basename $f)"
  else
    FAIL=$((FAIL+1))
    FAILED_LIST="$FAILED_LIST $(basename $f)"
    echo "  ✗ $(basename $f)  (rc=$RC)"
    echo "$OUT" | tail -12 | sed 's/^/      /'
  fi
done
echo
echo "通过=$PASS 失败=$FAIL"
[ -n "$FAILED_LIST" ] && echo "失败清单:$FAILED_LIST"
echo

echo "##### 3. 摄影/自拍相关的其他测试 #####"
for f in scripts/photo_shot_route_smoke.mjs scripts/photo_shot_route_api_smoke.mjs; do
  [ -f "$f" ] || continue
  if node "$f" >/dev/null 2>&1; then echo "  ✓ $(basename $f)"; else echo "  ✗ $(basename $f)"; node "$f" 2>&1 | tail -8 | sed 's/^/      /'; fi
done
echo

echo "############ 结束 ############"
