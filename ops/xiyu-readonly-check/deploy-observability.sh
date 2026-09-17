#!/bin/bash
# ============================================================
#  部署主动通道可观测性修复（2026-09-17）
#
#  改什么：src/proactive.mjs（唯一 owner）
#    ① sent 不再冒充"已送达"：内部早退记 deliveryOutcome='failed'
#       真实送达记 'delivered'；并持久化 deliveryOutcome/deliveryAt/deliveryError
#    ② 生成前预检：同一动念+同一计划刚被出站门拦过 → 直接跳过，不再重复调模型
#    ③ 通道关闭可观测：连续多次机会发不出 → 累计计数 + 超过阈值明确 warn 告警；
#       真实送达后清零
#  新增测试：scripts/proactive_delivery_observability_smoke.mjs
#
#  回滚：见脚本末尾 rollback 行
# ============================================================
set -u
ROOT=/opt/xiyu-ai
SERVICE=xiyu-ai
HEALTH=http://127.0.0.1:3000/api/health
STAGE=/tmp/xiyu-obs-deploy
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP=/opt/xiyu-backups/proactive-observability-$STAMP
FILES="src/proactive.mjs scripts/proactive_delivery_observability_smoke.mjs"

log(){ printf '[obs-deploy] %s\n' "$*"; }
fail(){ log "FAILED: $*"; }

rollback(){
  log "回滚中 ..."
  for f in $FILES; do
    b="$BACKUP/$(basename $f)"
    if [ -f "$b" ]; then sudo -n cp -p "$b" "$ROOT/$f" && log "  已恢复 $f";
    else sudo -n rm -f "$ROOT/$f" && log "  已删除新增文件 $f"; fi
  done
  sudo -n systemctl restart $SERVICE
  sleep 5
  curl -s --max-time 5 -f "$HEALTH" | grep -q '"ok"[[:space:]]*:[[:space:]]*true' \
    && log "  回滚后健康通过" || log "  回滚后健康未通过，需人工介入"
}

echo "############ 部署主动通道可观测性修复 ############"
date
echo

log "步骤0：检查待部署文件"
[ -f "$STAGE/proactive.mjs" ] || { fail "缺少 $STAGE/proactive.mjs"; exit 1; }
[ -f "$STAGE/proactive_delivery_observability_smoke.mjs" ] || { fail "缺少测试文件"; exit 1; }
echo "-- 关键改动自检（应全部 >0）--"
echo -n "  deliveryOutcome failed:      "; grep -c "item.deliveryOutcome = 'failed'" "$STAGE/proactive.mjs"
echo -n "  deliveryOutcome delivered:   "; grep -c "item.deliveryOutcome = 'delivered'" "$STAGE/proactive.mjs"
echo -n "  生成前预检调用:              "; grep -c 'proactivePrecheckGate(companion.id' "$STAGE/proactive.mjs"
echo -n "  通道关闭计数:                "; grep -c 'noteChannelClosedSkip(companion.id, kind)' "$STAGE/proactive.mjs"
echo -n "  告警阈值:                    "; grep -c 'CHANNEL_CLOSED_ALERT_AT = 6' "$STAGE/proactive.mjs"
echo -n "  旧「早退也算已发」注释残留:  "; grep -c "都算今日已尝试" "$STAGE/proactive.mjs" || true
echo

log "步骤1：备份"
sudo -n mkdir -p "$BACKUP" || { fail "建备份目录失败"; exit 1; }
for f in $FILES; do
  if sudo -n test -f "$ROOT/$f"; then
    sudo -n cp -p "$ROOT/$f" "$BACKUP/$(basename $f)" && log "  已备份 $f"
  else
    log "  $f 不存在（新增文件，回滚时删除）"
  fi
done
echo

log "步骤2：替换并语法检查"
NODE=$(systemctl show $SERVICE -p ExecStart --value | sed -n 's/.*path=\([^ ;]*\).*/\1/p' | head -n1)
[ -x "$NODE" ] || NODE=$(command -v node)
for pair in "src/proactive.mjs proactive.mjs" "scripts/proactive_delivery_observability_smoke.mjs proactive_delivery_observability_smoke.mjs"; do
  set -- $pair; target="$ROOT/$1"; staged="$STAGE/$2"
  if [ -f "$target" ]; then OWNER=$(stat -c '%u:%g' "$target"); MODE=$(stat -c '%a' "$target");
  else OWNER="0:0"; MODE="644"; fi
  sudo -n install -m "$MODE" -o "${OWNER%%:*}" -g "${OWNER##*:}" "$staged" "$target" || { fail "替换 $1 失败"; rollback; exit 1; }
  sudo -n -u xiyu "$NODE" --check "$target" || { fail "$1 语法检查失败（很可能是中文编码被破坏）"; rollback; exit 1; }
  log "  $1 OK sha256=$(sudo -n sha256sum "$target" | awk '{print $1}' | cut -c1-12)"
done
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

log "步骤4：跑新回归测试（生产环境）"
sudo -n -u xiyu env DB_PATH="$ROOT/data/bot.db" "$NODE" "$ROOT/scripts/proactive_delivery_observability_smoke.mjs" 2>&1 | tail -5

echo
log "步骤5：启动日志确认无异常"
sudo -n journalctl -u $SERVICE --since "$(date -u -d '2 minutes ago' '+%Y-%m-%d %H:%M:%S')" --no-pager 2>&1 \
  | grep -viE 'getUpdates success' | tail -8
echo

echo "========== 结果 =========="
echo "status=DEPLOY_OK"
echo "service=$(systemctl is-active $SERVICE) mainPid=$NEW_PID"
for f in $FILES; do echo "  $f sha256=$(sudo -n sha256sum "$ROOT/$f" 2>/dev/null | awk '{print $1}' | cut -c1-12)"; done
echo "backup=$BACKUP"
echo "rollback=sudo cp -p $BACKUP/proactive.mjs $ROOT/src/proactive.mjs; sudo rm -f $ROOT/scripts/proactive_delivery_observability_smoke.mjs; sudo systemctl restart $SERVICE"
echo "=========================="
