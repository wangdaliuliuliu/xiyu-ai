#!/bin/bash
# 对照跑照片测试：基线 vs 改造后
set -u
T=/tmp/xiyu-photo-verify
cd "$T"

LABEL="${1:-baseline}"
echo "############ 照片测试对照：$LABEL ############"
date
echo

PASS=0; FAIL=0
FAILLIST=""
for f in scripts/photo_*.mjs scripts/*selfie*.mjs; do
  [ -f "$f" ] || continue
  if node "$f" >/tmp/pt.out 2>&1; then
    PASS=$((PASS+1))
  else
    FAIL=$((FAIL+1))
    FAILLIST="$FAILLIST $(basename "$f")"
  fi
done
echo "通过=$PASS 失败=$FAIL"
echo "失败清单:$FAILLIST"
echo
echo "--- 各失败文件的首个失败断言 ---"
for n in $FAILLIST; do
  echo "  [$n]"
  node "scripts/$n" 2>&1 | grep -E '✗|✘|Error|error:' | head -3 | sed 's/^/      /'
done
echo
echo "############ 结束 ############"
