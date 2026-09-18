#!/bin/bash
# ============================================================
#  部署「被动回复也要有时间事实 + 对话上下文标注多久以前」
#  （2026-09-18）
#
#  用户报的现象（附截图）：
#    上午 10:06 他问"你在做什么"，她答
#      「刚跟你发完照片不就躺回去了嘛，灯还关着一半呢。」
#      「结果正经问题你还没答我呢，先说那两三条标准呗」
#    照片是 9-14 晚上的事（三天半前）；当天日程写着
#      08:00 上早课、10:00 课间和室友对海报。时间明显对不上。
#
#  查明的两个根因：
#    ① 时间事实约束只在主动模式构造
#       companion.mjs 里那套"不能在错误时段说刚放学/刚下班/刚到家"
#       整段包在 `if (promptMode === 'proactive')` 里。被动回复时
#       她手上只有一行钟表信息，没有任何一致性硬约束 → 上午十点说自己
#       刚躺下、灯关了一半，日程完全没起到约束作用。
#    ② 【最近对话上下文】每一条都没有时间
#       拼提示词时把 created_at 丢掉了（数据一直有：getConversationContext
#       返回 created_at）。所以 9-14 晚上的对话和一分钟前的对话长得一样，
#       她说"刚发完照片"、回头追 9-17 的问题，都因为看不出那是几天前。
#
#  改动文件：src/companion.mjs（仅此一个）
#    - 新增 buildTimeRealityConstraint(c)：时间事实约束抽成函数，两种模式共用，
#      并补上"白天不要说自己刚睡下/灯关了/准备睡了""说法要和今日安排一致"
#    - 新增 relativeTimeLabel(raw, now)：容错解析 ISO 与 SQLite 两种时间格式
#    - 【最近对话上下文】每行加 [多久以前]，并写明"几天前不能说成刚刚"
#    - 主动模式原有的 timeReality 由新函数提供（文案与约束不变）
#
#  新增测试：tests/agency/time_consistency.test.mjs（21 条）
#    反向验证：同一测试跑改动前版本 = 10 通过 / 11 失败，说明测试非空转。
#
#  回滚：见末尾
# ============================================================
set -u
ROOT=/opt/xiyu-ai
SERVICE=xiyu-ai
HEALTH=http://127.0.0.1:3000/api/health
STAGE=/tmp/xiyu-sweep-deploy
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP=/opt/xiyu-backups/time-consistency-$STAMP
NODE=$(systemctl show $SERVICE -p ExecStart --value | sed -n 's/.*path=\([^ ;]*\).*/\1/p' | head -n1)
[ -x "$NODE" ] || NODE=$(command -v node)

log(){ printf '[time] %s\n' "$*"; }
fail(){ log "FAILED: $*"; }

rollback(){
  log "回滚中 ..."
  sudo -n cp -p "$BACKUP/companion.mjs" "$ROOT/src/companion.mjs"
  sudo -n systemctl restart $SERVICE
  sleep 5
  curl -s --max-time 5 -f "$HEALTH" | grep -q '"ok"[[:space:]]*:[[:space:]]*true' \
    && log "  回滚后健康通过" || log "  回滚后健康未通过，需人工介入"
}

echo "############ 部署：时间一致性 ############"
date; echo

log "步骤0：检查待部署文件"
for f in companion.mjs time_consistency.test.mjs; do
  [ -f "$STAGE/$f" ] || { fail "缺少 $STAGE/$f"; exit 1; }
done
echo -n "  时间事实抽成函数 : "; grep -c 'function buildTimeRealityConstraint' "$STAGE/companion.mjs"
echo -n "  两种模式共用     : "; grep -c 'buildTimeRealityConstraint(c)' "$STAGE/companion.mjs"
echo -n "  上下文时间标注   : "; grep -c 'function relativeTimeLabel' "$STAGE/companion.mjs"
echo -n "  白天不装睡约束   : "; grep -c '白天不要说自己刚睡下' "$STAGE/companion.mjs"
echo

log "步骤1：上线前反向验证（同一测试必须能抓出旧版的问题）"
rm -rf /tmp/tc-old && mkdir -p /tmp/tc-old/src /tmp/tc-old/tests/agency
sudo -n cp -r "$ROOT/src/." /tmp/tc-old/src/
sudo -n ln -sf "$ROOT/node_modules" /tmp/tc-old/node_modules
sudo -n cp "$STAGE/time_consistency.test.mjs" /tmp/tc-old/tests/agency/
OLD_OUT=$(cd /tmp/tc-old && "$NODE" tests/agency/time_consistency.test.mjs 2>&1 | tail -1)
echo "  旧版结果: $OLD_OUT"
case "$OLD_OUT" in
  *"失败 0"*) fail "旧版居然全过 —— 测试可能是空转的，拒绝部署"; exit 1 ;;
  *) log "  ✓ 旧版确实失败，测试有效" ;;
esac
echo

log "步骤2：备份"
sudo -n mkdir -p "$BACKUP"
sudo -n cp -p "$ROOT/src/companion.mjs" "$BACKUP/companion.mjs"
log "  → $BACKUP"
echo

log "步骤3：替换 + 语法检查"
TARGET="$ROOT/src/companion.mjs"
OWNER=$(stat -c '%u:%g' "$TARGET"); MODE=$(stat -c '%a' "$TARGET")
sudo -n install -m "$MODE" -o "${OWNER%%:*}" -g "${OWNER##*:}" "$STAGE/companion.mjs" "$TARGET" || { fail "替换失败"; rollback; exit 1; }
sudo -n -u xiyu "$NODE" --check "$TARGET" || { fail "companion.mjs 语法失败（编码被破坏？）"; rollback; exit 1; }
log "  src/companion.mjs OK sha256=$(sudo -n sha256sum "$TARGET" | awk '{print $1}' | cut -c1-12)"
sudo -n install -m 644 -o "${OWNER%%:*}" -g "${OWNER##*:}" "$STAGE/time_consistency.test.mjs" "$ROOT/tests/agency/time_consistency.test.mjs"
log "  tests/agency/time_consistency.test.mjs 已上线"
echo

log "步骤4：重启 + 健康校验"
OLD_PID=$(systemctl show $SERVICE -p MainPID --value)
sudo -n systemctl restart $SERVICE || { fail "重启失败"; rollback; exit 1; }
OK=0
for i in $(seq 1 45); do
  if curl -s --max-time 5 -f "$HEALTH" | grep -q '"ok"[[:space:]]*:[[:space:]]*true'; then OK=1; break; fi
  sleep 2
done
[ "$OK" -eq 1 ] || { fail "健康检查未通过"; sudo -n journalctl -u $SERVICE -n 30 --no-pager | tail -30; rollback; exit 1; }
NEW_PID=$(systemctl show $SERVICE -p MainPID --value)
log "  健康通过 旧PID=$OLD_PID 新PID=$NEW_PID 状态=$(systemctl is-active $SERVICE)"
echo

log "步骤5：跑离线回归"
echo "--- time_consistency（应 21/21）---"
sudo -n -u xiyu "$NODE" "$ROOT/tests/agency/time_consistency.test.mjs" 2>&1 | tail -2
echo "--- intention_lifetime（应 81/81）---"
sudo -n -u xiyu "$NODE" "$ROOT/tests/agency/intention_lifetime.test.mjs" 2>&1 | tail -2
echo "--- state_budget（应 9/9）---"
sudo -n -u xiyu "$NODE" --test "$ROOT/tests/agency/state_budget.test.mjs" 2>&1 | grep -E '^# (tests|pass|fail)'
echo

log "步骤6：启动日志"
sudo -n journalctl -u $SERVICE --since "$(date -u -d '2 minutes ago' '+%Y-%m-%d %H:%M:%S')" --no-pager 2>&1 \
  | grep -viE 'getUpdates success' | tail -6
echo

echo "========== 结果 =========="
echo "service=$(systemctl is-active $SERVICE) mainPid=$NEW_PID"
echo "  src/companion.mjs sha256=$(sudo -n sha256sum "$ROOT/src/companion.mjs" | awk '{print $1}' | cut -c1-12)"
echo "backup=$BACKUP"
echo "rollback=sudo cp -p $BACKUP/companion.mjs $ROOT/src/companion.mjs && sudo systemctl restart $SERVICE"
echo "=========================="
