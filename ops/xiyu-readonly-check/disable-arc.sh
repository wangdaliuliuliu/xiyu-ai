#!/bin/bash
# ============================================================
#  关闭冲突弧 + 复位卡住的 hurt 状态
#
#  做四件事：
#    1. 备份生产文件与数据库
#    2. 部署改动后的 src/relationship_arc.mjs
#    3. 写入 systemd drop-in：ARC_ENABLED=off；复位库里的 hurt
#    4. 重启并验证
#
#  回滚：
#    sudo cp -p <backup>/relationship_arc.mjs /opt/xiyu-ai/src/relationship_arc.mjs
#    sudo rm /etc/systemd/system/xiyu-ai.service.d/arc-disable.conf
#    sudo systemctl daemon-reload && sudo systemctl restart xiyu-ai
# ============================================================
set -u
ROOT=/opt/xiyu-ai
SERVICE=xiyu-ai
HEALTH=http://127.0.0.1:3000/api/health
STAGE=/tmp/xiyu-arc-off
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
DROPIN_DIR=/etc/systemd/system/$SERVICE.d
DROPIN=$DROPIN_DIR/arc-disable.conf
BACKUP=/opt/xiyu-backups/arc-disable-$STAMP

log(){ printf '[arc-off] %s\n' "$*"; }
fail(){ log "FAILED: $*"; }

echo "############ 关闭冲突弧 ############"
date
echo

# ---- 0. 待部署文件检查 ----
log "步骤0：检查待部署文件"
[ -f "$STAGE/relationship_arc.mjs" ] || { fail "缺少 $STAGE/relationship_arc.mjs"; exit 1; }
log "  新文件含开关：$(grep -c 'export function arcEnabled' "$STAGE/relationship_arc.mjs")"
echo "-- 相对生产的差异 --"
diff -u "$ROOT/src/relationship_arc.mjs" "$STAGE/relationship_arc.mjs" | head -60
echo

# ---- 1. 备份 ----
log "步骤1：备份到 $BACKUP"
sudo -n mkdir -p "$BACKUP" || { fail "建备份目录失败"; exit 1; }
sudo -n cp -p "$ROOT/src/relationship_arc.mjs" "$BACKUP/relationship_arc.mjs" || { fail "备份源码失败"; exit 1; }
log "  已备份 relationship_arc.mjs ($(sudo -n sha256sum "$ROOT/src/relationship_arc.mjs" | awk '{print $1}'))"
if command -v sqlite3 >/dev/null 2>&1; then
  sudo -n sqlite3 "$ROOT/data/bot.db" ".timeout 15000" ".backup '$BACKUP/bot.db'" && log "  已用 sqlite3 .backup 备份数据库（一致性快照）" || { fail "数据库备份失败"; exit 1; }
  echo -n "  备份完整性: "; sudo -n sqlite3 "$BACKUP/bot.db" "PRAGMA integrity_check;" | head -1
else
  sudo -n cp -p "$ROOT/data/bot.db" "$BACKUP/bot.db"; log "  （无 sqlite3，已 cp 备份）"
fi
echo

# ---- 2. 部署源码 ----
log "步骤2：部署 relationship_arc.mjs"
OWNER=$(stat -c '%u:%g' "$ROOT/src/relationship_arc.mjs")
MODE=$(stat -c '%a'  "$ROOT/src/relationship_arc.mjs")
sudo -n install -m "$MODE" -o "${OWNER%%:*}" -g "${OWNER##*:}" "$STAGE/relationship_arc.mjs" "$ROOT/src/relationship_arc.mjs" \
  || { fail "替换失败"; exit 1; }
log "  权限=$MODE 属主=$OWNER sha256=$(sudo -n sha256sum "$ROOT/src/relationship_arc.mjs" | awk '{print $1}')"
log "  语法检查："
NODE=$(systemctl show $SERVICE -p ExecStart --value | sed -n 's/.*path=\([^ ;]*\).*/\1/p' | head -n1)
[ -x "$NODE" ] || NODE=$(command -v node)
sudo -n -u xiyu "$NODE" --check "$ROOT/src/relationship_arc.mjs" && log "    语法 OK" || { fail "语法失败"; exit 1; }
echo

# ---- 3. drop-in + 复位 ----
log "步骤3：写入 $DROPIN"
sudo -n mkdir -p "$DROPIN_DIR"
if sudo -n test -f "$DROPIN"; then
  sudo -n cp -p "$DROPIN" "$BACKUP/arc-disable.conf.existing"; log "  已备份原有 drop-in"
fi
printf '[Service]\nEnvironment=ARC_ENABLED=off\n' | sudo -n tee "$DROPIN" >/dev/null
sudo -n chmod 0644 "$DROPIN"
log "  已写入：ARC_ENABLED=off"
sudo -n systemctl daemon-reload
log "  已 daemon-reload"
echo

log "步骤3b：复位库里卡住的 hurt 状态"
[ -f "$STAGE/reset-arc-hurt.mjs" ] || { fail "缺少复位脚本"; exit 1; }
sudo -n -u xiyu "$NODE" "$STAGE/reset-arc-hurt.mjs"
RESET_RC=$?
if [ "$RESET_RC" -ne 0 ]; then
  fail "复位脚本退出码=$RESET_RC（状态可能已是 normal，继续验证）"
fi
echo

# ---- 4. 重启与验证 ----
log "步骤4：重启并验证"
OLD_PID=$(systemctl show $SERVICE -p MainPID --value)
sudo -n systemctl restart $SERVICE || { fail "重启失败"; exit 1; }
OK=0
for i in $(seq 1 45); do
  if curl -s --max-time 5 -f "$HEALTH" | grep -q '"ok"[[:space:]]*:[[:space:]]*true'; then OK=1; break; fi
  sleep 2
done
if [ "$OK" -ne 1 ]; then
  fail "健康检查未通过"
  sudo -n journalctl -u $SERVICE -n 30 --no-pager | tail -30
  log "回滚：sudo cp -p $BACKUP/relationship_arc.mjs $ROOT/src/relationship_arc.mjs && sudo rm $DROPIN && sudo systemctl daemon-reload && sudo systemctl restart $SERVICE"
  exit 1
fi
NEW_PID=$(systemctl show $SERVICE -p MainPID --value)
log "  健康检查通过  旧PID=$OLD_PID 新PID=$NEW_PID  状态=$(systemctl is-active $SERVICE)"
echo

log "步骤5：确认生效"
echo "-- 数据库弧状态（应为 normal，未结事件应为 0）--"
sudo -n -u xiyu sqlite3 -readonly "$ROOT/data/bot.db" -header -column "SELECT id, arc_state, arc_state_changed_at FROM companions;" 2>&1
sudo -n -u xiyu sqlite3 -readonly "$ROOT/data/bot.db" -header -column "SELECT COUNT(*) AS open_events FROM companion_relationship_events WHERE resolved_at IS NULL OR resolved_at='';" 2>&1
echo "-- 进程环境变量（ARC_ENABLED 应可见）--"
sudo -n tr '\0' '\n' < "/proc/$NEW_PID/environ" 2>/dev/null | grep -E '^ARC_ENABLED=' || echo "  未能从 /proc 读取"
echo "-- 启动日志（过滤轮询噪音）--"
sudo -n journalctl -u $SERVICE --since "$(date -u -d '2 minutes ago' '+%Y-%m-%d %H:%M:%S')" --no-pager 2>&1 | grep -viE 'getUpdates success' | tail -12
echo

echo "========== 结果 =========="
echo "status=ARC_DISABLE_DONE"
echo "backup=$BACKUP"
echo "rollback=sudo cp -p $BACKUP/relationship_arc.mjs $ROOT/src/relationship_arc.mjs && sudo rm $DROPIN && sudo systemctl daemon-reload && sudo systemctl restart $SERVICE"
echo "re-enable=把 $DROPIN 里的 ARC_ENABLED 改成 on 后 daemon-reload + restart"
echo "=========================="
