#!/bin/bash
# ============================================================
#  溪语预算修正 — 完成重启与验证
#
#  背景：上一次部署已成功替换文件（db.mjs=a5f9deab…, proactive.mjs=41b1b065…），
#        但脚本遗漏了 systemctl 的 sudo，重启失败；运行中的进程仍是 16:31 启动的
#        旧代码（node 会缓存已加载模块），所以新上限尚未生效。
#        本脚本只做：核对文件 → 重启 → 健康校验 → 隔离冒烟 → 汇总。
#
#  不覆盖任何文件；如需回滚见文末命令。
# ============================================================
set -u
ROOT=/opt/xiyu-ai
STAGE=/tmp/xiyu-budget-deploy
SERVICE=xiyu-ai
HEALTH=http://127.0.0.1:3000/api/health
EXPECT_DB=a5f9deabbd7a110923431731e2f3f4e670c123a46c05d89e2c60cdb566e8aff1
EXPECT_PRO=41b1b065a268ecb4930a4e7fbc3e368f3696878b4b20524e864a76abff6cb51b
ORIG_DB=64cc65ef0366f637ac0c5da81f0af6f56a4fa82ff4ad206bbfde95e3ae7a0fbe
ORIG_PRO=d170621e2dbb566177bbe0a7a60ec4cd23bfb672efa83fc33eedec857c3ce3bc
BACKUP=$(ls -1dt /opt/xiyu-backups/budget-deploy-* 2>/dev/null | head -1)

log(){ printf '[restart] %s\n' "$*"; }
fail(){ log "FAILED: $*"; }

echo "############ 预算修正：完成重启与验证 ############"
date
echo

# ---- 1. 文件必须是预期的新版 ----
log "步骤1：核对生产文件是新版"
DB_HASH=$(sudo -n sha256sum "$ROOT/src/db.mjs" | awk '{print $1}')
PRO_HASH=$(sudo -n sha256sum "$ROOT/src/proactive.mjs" | awk '{print $1}')
log "  db.mjs        $DB_HASH"
log "  proactive.mjs $PRO_HASH"
if [ "$DB_HASH" != "$EXPECT_DB" ] || [ "$PRO_HASH" != "$EXPECT_PRO" ]; then
  fail "生产文件不是预期的新版，停止重启以免加载未知代码"
  echo "  期望 db=$EXPECT_DB"
  echo "  期望 pro=$EXPECT_PRO"
  exit 1
fi
log "  文件版本正确"
echo

# ---- 2. 重启前记录旧进程 ----
OLD_PID=$(systemctl show $SERVICE -p MainPID --value)
log "步骤2：重启服务（旧 MainPID=$OLD_PID，启动于 $(ps -o lstart= -p "$OLD_PID" 2>/dev/null | xargs)）"
if ! sudo -n systemctl restart $SERVICE; then
  fail "重启命令失败"
  exit 1
fi
log "  重启命令已执行"
echo

# ---- 3. 健康校验 ----
OK=0
for i in $(seq 1 45); do
  if curl -s --max-time 5 -f "$HEALTH" | grep -q '"ok"[[:space:]]*:[[:space:]]*true'; then OK=1; break; fi
  sleep 2
done
if [ "$OK" -ne 1 ]; then
  fail "健康检查 90 秒内未通过"
  sudo -n journalctl -u $SERVICE -n 40 --no-pager | tail -40
  log "回滚命令：sudo cp -p $BACKUP/db.mjs $ROOT/src/db.mjs && sudo cp -p $BACKUP/proactive.mjs $ROOT/src/proactive.mjs && sudo systemctl restart $SERVICE"
  exit 1
fi
NEW_PID=$(systemctl show $SERVICE -p MainPID --value)
log "步骤3：健康检查通过"
log "  新 MainPID=$NEW_PID  启动于 $(ps -o lstart= -p "$NEW_PID" 2>/dev/null | xargs)"
log "  服务状态=$(systemctl is-active $SERVICE)"
if [ "$NEW_PID" = "$OLD_PID" ]; then
  fail "MainPID 未变化，进程可能没有真正重启"
  exit 1
fi
echo

# ---- 4. 隔离冒烟：新上限是否真生效 ----
log "步骤4：隔离冒烟（临时 DB，独立进程，不碰生产库）"
NODE=$(systemctl show $SERVICE -p ExecStart --value | sed -n 's/.*path=\([^ ;]*\).*/\1/p' | head -n1)
[ -x "$NODE" ] || NODE=$(command -v node)
SMOKE=$(sudo -n -u xiyu sh -c "TMPD=\$(mktemp -d /tmp/xiyu-budget-smoke.XXXXXX) && cd $ROOT && DB_PATH=\$TMPD/smoke.db DATA_DIR=\$TMPD LOG_DIR=\$TMPD $NODE $STAGE/smoke-budget-caps.mjs; RC=\$?; rm -rf \$TMPD; exit \$RC")
SMOKE_RC=$?
echo "$SMOKE"
if [ "$SMOKE_RC" -ne 0 ]; then
  fail "冒烟失败（rc=$SMOKE_RC）"
  exit 1
fi
log "  冒烟通过"
echo

# ---- 5. 服务启动日志：确认新进程正常 ----
log "步骤5：新进程启动日志（过滤 iLink 轮询噪音）"
sudo -n journalctl -u $SERVICE --since "$(date -u -d '3 minutes ago' '+%Y-%m-%d %H:%M:%S')" --no-pager 2>&1 \
  | grep -viE 'getUpdates success' | tail -25
echo

# ---- 6. 汇总 ----
echo "========== 结果 =========="
echo "status=RESTART_OK"
echo "service=$(systemctl is-active $SERVICE)"
echo "mainPid=$NEW_PID"
echo "oldPid=$OLD_PID"
echo "backup=$BACKUP"
echo "files:"
echo "  src/db.mjs        $DB_HASH"
echo "  src/proactive.mjs $PRO_HASH"
echo "rollback=sudo cp -p $BACKUP/db.mjs $ROOT/src/db.mjs && sudo cp -p $BACKUP/proactive.mjs $ROOT/src/proactive.mjs && sudo systemctl restart $SERVICE"
echo "restore-original-hashes=$ORIG_DB / $ORIG_PRO"
echo "=========================="
