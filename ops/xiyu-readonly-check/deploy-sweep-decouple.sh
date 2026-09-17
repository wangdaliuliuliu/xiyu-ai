#!/bin/bash
# ============================================================
#  部署「收尾扫描面与候选条数解耦」（2026-09-18）
#
#  修什么：
#    收尾闸（retireExpiredIntentions）的**入参**原来直接复用了候选列表，
#    而候选列表是 `limit: 8`。池子涨到 9 条之后，第 9 条（恰好是那条
#    「订单系统汇总表 9-14 数据填了没」的动念）永远排在窗口外，
#    于是**永远不被判定、永远不过期**：
#      - 它派生的动作 9-15 13:10 就过期了
#      - 9-17 一天里它被重新选中并撞在同一条出站复核上 4 次（18:09/19:14/20:44/另有）
#      - 22:08 的晚安被它挤成 status=blocked，当晚没发出去
#
#  为什么不是"把 8 改成 10"：
#    那只是把窗口挪一格，池子再长一条就复发。这类"闸门看不见它该管的东西"
#    的错会随数据量反复出现。所以改成**按 owner 扫全部非终态动念**
#    （上限用 listAgencyIntentions 的硬顶 50），收尾面与候选面彻底解耦；
#    `limit: 8` 只留给真正要喂给模型的候选列表。
#
#  改动文件：src/proactive.mjs（仅此一个）
#  新增测试：无（新增断言见下方步骤5的只读判定）
#
#  回滚：见末尾
# ============================================================
set -u
ROOT=/opt/xiyu-ai
SERVICE=xiyu-ai
HEALTH=http://127.0.0.1:3000/api/health
STAGE=/tmp/xiyu-sweep-deploy
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP=/opt/xiyu-backups/sweep-decouple-$STAMP
FILES="src/proactive.mjs"

log(){ printf '[sweep] %s\n' "$*"; }
fail(){ log "FAILED: $*"; }

rollback(){
  log "回滚中 ..."
  for f in $FILES; do
    b="$BACKUP/$(basename $f)"
    if [ -f "$b" ]; then sudo -n cp -p "$b" "$ROOT/$f" && log "  已恢复 $f";
    else log "  备份缺失，无法恢复 $f"; fi
  done
  sudo -n systemctl restart $SERVICE
  sleep 5
  curl -s --max-time 5 -f "$HEALTH" | grep -q '"ok"[[:space:]]*:[[:space:]]*true' \
    && log "  回滚后健康通过" || log "  回滚后健康未通过，需人工介入"
}

echo "############ 部署收尾扫描面解耦 ############"
date
echo

log "步骤0：检查待部署文件与关键改动"
for f in $FILES; do [ -f "$STAGE/$(basename $f)" ] || { fail "缺少 $f"; exit 1; }; done
echo -n "  收尾扫描面 limit=50 : "; grep -c 'limit: 50' "$STAGE/proactive.mjs"
echo -n "  每 tick 独立扫描入口: "; grep -c 'sweepIntentionRetirement({' "$STAGE/proactive.mjs"
echo -n "  候选面 limit=8 保留 : "; grep -c 'limit: 8,' "$STAGE/proactive.mjs"
echo -n "  owner 与认知同源     : "; grep -c 'sweepBinding?.account_id || account?.account_id' "$STAGE/proactive.mjs"
echo

log "步骤1：备份"
sudo -n mkdir -p "$BACKUP" || { fail "建备份目录失败"; exit 1; }
for f in $FILES; do
  if sudo -n test -f "$ROOT/$f"; then sudo -n cp -p "$ROOT/$f" "$BACKUP/$(basename $f)" && log "  已备份 $f";
  else log "  $f 不存在（新增，回滚时删除）"; fi
done
echo

log "步骤2：替换并语法检查"
NODE=$(systemctl show $SERVICE -p ExecStart --value | sed -n 's/.*path=\([^ ;]*\).*/\1/p' | head -n1)
[ -x "$NODE" ] || NODE=$(command -v node)
target="$ROOT/src/proactive.mjs"; staged="$STAGE/proactive.mjs"
if [ -f "$target" ]; then OWNER=$(stat -c '%u:%g' "$target"); MODE=$(stat -c '%a' "$target"); else OWNER="0:0"; MODE="644"; fi
sudo -n install -m "$MODE" -o "${OWNER%%:*}" -g "${OWNER##*:}" "$staged" "$target" || { fail "替换失败"; rollback; exit 1; }
sudo -n -u xiyu "$NODE" --check "$target" || { fail "proactive.mjs 语法失败（很可能是中文编码被破坏）"; rollback; exit 1; }
log "  src/proactive.mjs OK sha256=$(sudo -n sha256sum "$target" | awk '{print $1}' | cut -c1-12)"
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

log "步骤4：跑不变量检查（应只剩 I6 那 3 条每日仪式）"
sudo -n -u xiyu env DB_PATH="$ROOT/data/bot.db" "$NODE" "$ROOT/check-invariants.mjs" 2>&1 | tail -18
echo

log "步骤5：启动日志（确认无异常）"
sudo -n journalctl -u $SERVICE --since "$(date -u -d '2 minutes ago' '+%Y-%m-%d %H:%M:%S')" --no-pager 2>&1 \
  | grep -viE 'getUpdates success' | tail -8
echo

echo "========== 结果 =========="
echo "status=DEPLOY_OK"
echo "service=$(systemctl is-active $SERVICE) mainPid=$NEW_PID"
for f in $FILES; do echo "  $f sha256=$(sudo -n sha256sum "$ROOT/$f" 2>/dev/null | awk '{print $1}' | cut -c1-12)"; done
echo "backup=$BACKUP"
echo "rollback=sudo cp -p $BACKUP/proactive.mjs $ROOT/src/; sudo systemctl restart $SERVICE"
echo "=========================="
