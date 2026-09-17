#!/bin/bash
# ============================================================
#  ARC_ENABLED 开关 — 隔离验证（不修改生产任何文件）
#
#  前置：调用方已把改动后的文件放到
#          /tmp/xiyu-arc-verify/src/relationship_arc.mjs
#          /tmp/xiyu-arc-verify/scripts/conflict_arc_smoke.mjs
#  做法：临时目录 + 符号链接只读引用生产 node_modules，跑纯函数 smoke。
# ============================================================
set -u
T=/tmp/xiyu-arc-verify
ROOT=/opt/xiyu-ai

echo "############ ARC 开关隔离验证 ############"
date
echo "node: $(node --version)"
echo

# 依赖：只读引用生产
[ -e "$T/node_modules" ] || ln -s "$ROOT/node_modules" "$T/node_modules"
cp "$ROOT/package.json" "$T/package.json" 2>/dev/null

# 补齐 src / scripts 下其他依赖模块（递归，含 providers/ 等子目录）。
# 注意：必须 -r，否则 ai.mjs 依赖的 src/providers/chat.mjs 会缺失导致 smoke 跑不起来。
for d in src scripts config; do
  [ -d "$ROOT/$d" ] || continue
  cp -r "$ROOT/$d/." "$T/$d/" 2>/dev/null
done

echo "##### 1. 待验证文件 #####"
for f in "$T/src/relationship_arc.mjs" "$T/scripts/conflict_arc_smoke.mjs"; do
  [ -f "$f" ] && echo "  OK   $f ($(wc -c < "$f") 字节)" || echo "  缺失 $f"
done
echo "-- 新开关是否在文件中 --"
grep -n "export function arcEnabled\|arc_disabled\|ARC_ENABLED" "$T/src/relationship_arc.mjs" | head -8
echo

echo "##### 2. 跑冲突弧 smoke（默认 ARC_ENABLED 未设置 = 开）#####"
cd "$T"
node scripts/conflict_arc_smoke.mjs
RC1=$?
echo "  退出码=$RC1"
echo

echo "##### 3. 再用 ARC_ENABLED=off 跑一遍（确认关闭态不炸）#####"
ARC_ENABLED=off node scripts/conflict_arc_smoke.mjs
RC2=$?
echo "  退出码=$RC2"
echo

echo "##### 4. 直接验证开关的语义 #####"
node --input-type=module -e "
import { arcEnabled, tickArcOnSignal, tickArcOnTime } from '$T/src/relationship_arc.mjs';
console.log('arcEnabled() 默认 =', arcEnabled());
process.env.ARC_ENABLED = 'off';
console.log('设 off 后 arcEnabled() =', arcEnabled());
const N = new Date();
const sig = (o) => tickArcOnSignal({ state:'normal', stateChangedAt:new Date(N-3600e3).toISOString(), style:'secure', safeMode:false, openEvent:null, todayEventCount:0, recentArchivedType:null, now:N, rng:()=>0.99, signal:{kind:'harsh_words',severity:4}, ...o });
const tim = (o) => tickArcOnTime({ state:'normal', stateChangedAt:new Date(N-3600e3).toISOString(), style:'secure', safeMode:false, openEvent:null, neglectStage:'none', interactionsSinceEvent:0, now:N, ...o });
const a = sig({});                       // env=off -> 应保持 normal
console.log('env=off  severity4 结果 =', a.state, '/ reason =', a.reason, '/ eventOp =', JSON.stringify(a.eventOp));
const b = sig({ arcEnabled:true });      // 显式开 -> cold
console.log('显式 on  severity4 结果 =', b.state);
const c = tim({ state:'hurt', stateChangedAt:new Date(N-7200e3).toISOString() });
console.log('env=off  存量 hurt 结果 =', c.state, '/ changed =', c.changed, '/ eventOp =', JSON.stringify(c.eventOp));
process.env.ARC_ENABLED = 'on';
const d = sig({});
console.log('env=on   severity4 结果 =', d.state);
"
RC3=$?
echo "  退出码=$RC3"
echo

echo "##### 5. 生产文件未被改动 #####"
if grep -q "export function arcEnabled" "$ROOT/src/relationship_arc.mjs" 2>/dev/null; then
  echo "  生产已含开关（说明已部署过）"
else
  echo "  生产尚未包含开关（本次为隔离验证，未部署）"
fi
echo

echo "############ 验证结束 ############"
echo "rc1=$RC1 rc2=$RC2 rc3=$RC3"
