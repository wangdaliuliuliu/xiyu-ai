#!/bin/bash
# 主动/动念相关回归（隔离目录）
set -u
T=/tmp/xiyu-life-verify
cd "$T"
echo "############ 主动/动念回归 ############"
date
echo
PASS=0; FAIL=0; FAILED=""
for f in scripts/proactive_*.mjs scripts/agency_state_smoke.mjs scripts/agency_cycle_smoke.mjs scripts/agency_protocol_smoke.mjs scripts/agency_no_response_smoke.mjs scripts/initiative_*.mjs scripts/agency_acceptance.mjs; do
  [ -f "$f" ] || continue
  if node "$f" >/tmp/o 2>&1; then
    PASS=$((PASS+1)); echo "  OK   $(basename "$f")"
  else
    FAIL=$((FAIL+1)); FAILED="$FAILED $(basename "$f")"
    echo "  FAIL $(basename "$f")"
    grep -E 'Error|AssertionError|✗|Error:' /tmp/o | head -2 | sed 's/^/       /'
  fi
done
echo
echo "通过=$PASS 失败=$FAIL"
echo "失败清单:$FAILED"
