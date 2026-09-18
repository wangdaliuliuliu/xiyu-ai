#!/bin/bash
# ============================================================
#  部署「认知冷却被挡时说明原因」（2026-09-18）
#
#  修什么：
#    生产日志出现 `[Agency] cycle status=cooldown calls=0`，
#    但 `beginAgencyCognition` 的三道否决
#      （租约无效 / 30 分钟硬间隔 / reconsider_after 未到）
#    **全都只返回 false**，完全看不出是哪一道挡的。排查时只能猜。
#
#    "失败不可见"正是本项目主动通道反复栽的同一个坑，所以这一轮
#    不只是修某一次 cooldown，而是让每一次 cooldown 都自报原因。
#
#  改动文件：
#    src/db.mjs           beginAgencyCognition 返回 {started, reason}
#    src/proactive.mjs    把 reason 带进 cycle 结果与日志
#    tests/agency/state_budget.test.mjs  +1 条断言，锁住三态各自的原因
#    tests/agency/intention_lifetime.test.mjs  81 条（上一轮漏装，这次补上）
#
#  注意：`beginAgencyCognition` 全仓只有一个调用方（proactive.mjs:598），
#        已确认，故返回值从 boolean 改对象不会漏改别的调用点。
#
#  回滚：见末尾
# ============================================================
set -u
ROOT=/opt/xiyu-ai
SERVICE=xiyu-ai
HEALTH=http://127.0.0.1:3000/api/health
STAGE=/tmp/xiyu-sweep-deploy
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP=/opt/xiyu-backups/cooldown-reason-$STAMP
NODE=$(systemctl show $SERVICE -p ExecStart --value | sed -n 's/.*path=\([^ ;]*\).*/\1/p' | head -n1)
[ -x "$NODE" ] || NODE=$(command -v node)

log(){ printf '[cooldown] %s\n' "$*"; }
fail(){ log "FAILED: $*"; }

rollback(){
  log "回滚中 ..."
  sudo -n cp -p "$BACKUP/db.mjs" "$ROOT/src/db.mjs"
  sudo -n cp -p "$BACKUP/proactive.mjs" "$ROOT/src/proactive.mjs"
  sudo -n systemctl restart $SERVICE
  sleep 5
  curl -s --max-time 5 -f "$HEALTH" | grep -q '"ok"[[:space:]]*:[[:space:]]*true' \
    && log "  回滚后健康通过" || log "  回滚后健康未通过，需人工介入"
}

echo "############ 部署：认知冷却自报原因 ############"
date; echo

log "步骤0：检查待部署文件"
for f in db.mjs proactive.mjs state_budget.test.mjs intention_lifetime.test.mjs; do
  [ -f "$STAGE/$f" ] || { fail "缺少 $STAGE/$f"; exit 1; }
done
echo -n "  beginAgencyCognition 返回原因 : "; grep -c 'lease_invalid' "$STAGE/db.mjs"
echo -n "  三态原因齐全                  : "; grep -c 'cognition_gap_\|reconsider_after_' "$STAGE/db.mjs"
echo -n "  cycle 带出 reason             : "; grep -c 'agencyCycle.reason' "$STAGE/proactive.mjs"
echo -n "  第四层仍在                    : "; grep -c 'ritual_delivered_and_settled' "$STAGE/proactive.mjs" || true
echo

log "步骤1：备份"
sudo -n mkdir -p "$BACKUP"
sudo -n cp -p "$ROOT/src/db.mjs" "$BACKUP/db.mjs"
sudo -n cp -p "$ROOT/src/proactive.mjs" "$BACKUP/proactive.mjs"
log "  → $BACKUP"
echo

log "步骤2：替换 + 语法检查"
install_one(){
  local rel="$1" staged="$2" target="$ROOT/$1"
  local OWNER MODE
  if [ -f "$target" ]; then OWNER=$(stat -c '%u:%g' "$target"); MODE=$(stat -c '%a' "$target"); else OWNER="0:0"; MODE="644"; fi
  sudo -n install -m "$MODE" -o "${OWNER%%:*}" -g "${OWNER##*:}" "$staged" "$target" || { fail "替换 $rel 失败"; rollback; exit 1; }
  sudo -n -u xiyu "$NODE" --check "$target" || { fail "$rel 语法失败（编码被破坏？）"; rollback; exit 1; }
  log "  $rel OK sha256=$(sudo -n sha256sum "$target" | awk '{print $1}' | cut -c1-12)"
}
install_one src/db.mjs       "$STAGE/db.mjs"
install_one src/proactive.mjs "$STAGE/proactive.mjs"
# 测试文件上一轮漏装了（部署脚本只备份没替换），这里补上并校验条数
install_one tests/agency/state_budget.test.mjs        "$STAGE/state_budget.test.mjs"
install_one tests/agency/intention_lifetime.test.mjs  "$STAGE/intention_lifetime.test.mjs"
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

log "步骤4：跑离线测试（真实生产环境）"
echo "--- intention_lifetime（应 81）---"
sudo -n -u xiyu "$NODE" "$ROOT/tests/agency/intention_lifetime.test.mjs" 2>&1 | tail -2
echo "--- state_budget（含新增 cooldown 原因断言）---"
sudo -n -u xiyu "$NODE" --test "$ROOT/tests/agency/state_budget.test.mjs" 2>&1 | grep -E '^# (tests|pass|fail)|not ok' | head -20
echo

log "步骤5：等一个 tick 看 cooldown 是否带出原因"
sleep 70
sudo -n journalctl -u $SERVICE --since "$(date -u -d '3 minutes ago' '+%Y-%m-%d %H:%M:%S')" --no-pager 2>&1 \
  | grep -E 'Agency.*cycle|动念收尾' | tail -8
echo

log "步骤6：不变量检查"
sudo -n -u xiyu env DB_PATH="$ROOT/data/bot.db" "$NODE" "$ROOT/check-invariants.mjs" 2>&1 | tail -14
echo

echo "========== 结果 =========="
echo "service=$(systemctl is-active $SERVICE) mainPid=$NEW_PID"
for f in src/db.mjs src/proactive.mjs tests/agency/intention_lifetime.test.mjs; do
  echo "  $f sha256=$(sudo -n sha256sum "$ROOT/$f" | awk '{print $1}' | cut -c1-12)"
done
echo "backup=$BACKUP"
echo "rollback=sudo cp -p $BACKUP/db.mjs $ROOT/src/db.mjs && sudo cp -p $BACKUP/proactive.mjs $ROOT/src/proactive.mjs && sudo systemctl restart $SERVICE"
echo "=========================="
