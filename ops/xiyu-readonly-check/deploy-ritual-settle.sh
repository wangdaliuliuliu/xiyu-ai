#!/bin/bash
# ============================================================
#  部署「第四层：每日仪式已送出即完结」（2026-09-18）
#
#  修什么：
#    同一条仪式动念可以被反复复用投递。实测
#    `agi_mtsbnojz_029496dd1c567b` 身上挂着 3 条 delivered 动作，
#    时间 09-08 15:02 / 19:09 / 09-09 00:17 —— **同一天内送出 3 次**。
#
#    成因链：
#      ① 投递完成后动念永远停在 `active`（没有任何东西把它完结）
#      ② 下一次生成走 `findAgencyIntentionBySemanticKey`，而它只查
#         "非终态"，于是**复用了已经发过的那条**
#      ③ 于是同一条内容换着法儿再来一遍
#
#  为什么不能用"保质期"：
#    每日仪式（早安/晚安/低负担入口）必须每天都能发。给它加保质期会
#    让早安晚安发不出去——比不修还糟。
#
#  这次的做法：
#    第四层收尾——仪式**已真实送达**且已静置 RITUAL_SETTLED_HOURS(6h)
#    → `completed`。静置窗口取 6h 是因为实测那 3 次投递两两相隔 2~5h。
#    完结后同内容再来时，`findAgencyIntentionBySemanticKey` 查不到它
#    （已终态），于是建一条**新的**，所以"明天还能发早安"不受影响，
#    只是不会拿已经发过的那条再发一遍。
#
#  改动文件：
#    src/initiative.mjs   新增 RITUAL_SETTLED_HOURS 常量 +
#                         judgeIntentionRetirement 第四层
#    src/proactive.mjs     sweepIntentionRetirement 收集投递证据
#                         （listAgencyActions delivered，按 intentionId 归并）
#                         并传给判定
#    tests/agency/intention_lifetime.test.mjs   +11 条断言（70 → 81）
#
#  回滚：见末尾
# ============================================================
set -u
ROOT=/opt/xiyu-ai
SERVICE=xiyu-ai
HEALTH=http://127.0.0.1:3000/api/health
STAGE=/tmp/xiyu-sweep-deploy
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP=/opt/xiyu-backups/ritual-settle-$STAMP
NODE=$(systemctl show $SERVICE -p ExecStart --value | sed -n 's/.*path=\([^ ;]*\).*/\1/p' | head -n1)
[ -x "$NODE" ] || NODE=$(command -v node)

log(){ printf '[ritual] %s\n' "$*"; }
fail(){ log "FAILED: $*"; }

rollback(){
  log "回滚中 ..."
  sudo -n cp -p "$BACKUP/initiative.mjs" "$ROOT/src/initiative.mjs"
  sudo -n cp -p "$BACKUP/proactive.mjs"  "$ROOT/src/proactive.mjs"
  sudo -n cp -p "$BACKUP/intention_lifetime.test.mjs" "$ROOT/tests/agency/intention_lifetime.test.mjs"
  sudo -n systemctl restart $SERVICE
  sleep 5
  curl -s --max-time 5 -f "$HEALTH" | grep -q '"ok"[[:space:]]*:[[:space:]]*true' \
    && log "  回滚后健康通过" || log "  回滚后健康未通过，需人工介入"
}

echo "############ 部署第四层：仪式已送出即完结 ############"
date; echo

log "步骤0：检查待部署文件与关键改动"
for f in initiative.mjs proactive.mjs; do
  [ -f "$STAGE/$f" ] || { fail "缺少 $STAGE/$f"; exit 1; }
done
echo -n "  静置窗口常量      : "; grep -c 'RITUAL_SETTLED_HOURS = 6' "$STAGE/initiative.mjs"
echo -n "  第四层判定        : "; grep -c 'ritual_delivered_and_settled' "$STAGE/initiative.mjs"
echo -n "  扫描收集投递证据  : "; grep -c 'deliveredByIntention' "$STAGE/proactive.mjs"
echo -n "  候选面仍为 8      : "; grep -c 'limit: 8,' "$STAGE/proactive.mjs"
echo

log "步骤1：备份"
sudo -n mkdir -p "$BACKUP" || { fail "建备份目录失败"; exit 1; }
sudo -n cp -p "$ROOT/src/initiative.mjs" "$BACKUP/initiative.mjs"
sudo -n cp -p "$ROOT/src/proactive.mjs"  "$BACKUP/proactive.mjs"
sudo -n cp -p "$ROOT/tests/agency/intention_lifetime.test.mjs" "$BACKUP/intention_lifetime.test.mjs"
log "  已备份 3 个文件 → $BACKUP"
echo

log "步骤2：替换并语法检查"
install_one(){
  local rel="$1" staged="$2" target="$ROOT/$1"
  local OWNER MODE
  if [ -f "$target" ]; then OWNER=$(stat -c '%u:%g' "$target"); MODE=$(stat -c '%a' "$target"); else OWNER="0:0"; MODE="644"; fi
  sudo -n install -m "$MODE" -o "${OWNER%%:*}" -g "${OWNER##*:}" "$staged" "$target" || { fail "替换 $rel 失败"; rollback; exit 1; }
  sudo -n -u xiyu "$NODE" --check "$target" || { fail "$rel 语法失败（很可能是中文编码被破坏）"; rollback; exit 1; }
  log "  $rel OK sha256=$(sudo -n sha256sum "$target" | awk '{print $1}' | cut -c1-12)"
}
install_one src/initiative.mjs "$STAGE/initiative.mjs"
install_one src/proactive.mjs  "$STAGE/proactive.mjs"
echo

log "步骤3：重启 + 健康校验"
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

log "步骤4：跑离线测试（81 条，含第四层 11 条）"
sudo -n -u xiyu "$NODE" "$ROOT/tests/agency/intention_lifetime.test.mjs" 2>&1 | tail -3
echo

log "步骤5：等一个 tick，让收尾扫描真跑一次（TICK_MS=60s）"
sleep 75
echo "--- 收尾日志 ---"
sudo -n journalctl -u $SERVICE --since "$(date -u -d '3 minutes ago' '+%Y-%m-%d %H:%M:%S')" --no-pager 2>&1 \
  | grep -E '动念收尾' | tail -12
echo

log "步骤6：不变量检查"
sudo -n -u xiyu env DB_PATH="$ROOT/data/bot.db" "$NODE" "$ROOT/check-invariants.mjs" 2>&1 | tail -16
echo

log "步骤7：启动日志（确认无异常）"
sudo -n journalctl -u $SERVICE --since "$(date -u -d '4 minutes ago' '+%Y-%m-%d %H:%M:%S')" --no-pager 2>&1 \
  | grep -viE 'getUpdates success' | grep -iE 'error|warn|异常' | tail -8
echo "(以上若为空即无异常)"
echo

echo "========== 结果 =========="
echo "service=$(systemctl is-active $SERVICE) mainPid=$NEW_PID"
echo "  src/initiative.mjs sha256=$(sudo -n sha256sum "$ROOT/src/initiative.mjs" | awk '{print $1}' | cut -c1-12)"
echo "  src/proactive.mjs  sha256=$(sudo -n sha256sum "$ROOT/src/proactive.mjs" | awk '{print $1}' | cut -c1-12)"
echo "backup=$BACKUP"
echo "rollback=sudo cp -p $BACKUP/initiative.mjs $ROOT/src/initiative.mjs && sudo cp -p $BACKUP/proactive.mjs $ROOT/src/proactive.mjs && sudo cp -p $BACKUP/intention_lifetime.test.mjs $ROOT/tests/agency/ && sudo systemctl restart $SERVICE"
echo "=========================="
