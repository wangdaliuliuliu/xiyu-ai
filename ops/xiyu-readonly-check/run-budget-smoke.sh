#!/bin/bash
# ============================================================
#  预算修正 — 只跑隔离冒烟（不重启、不改任何文件）
#
#  前置：/tmp/xiyu-budget-deploy/smoke-budget-caps.mjs 已更新为
#        绝对路径导入 /opt/xiyu-ai/src/db.mjs
# ============================================================
set -u
ROOT=/opt/xiyu-ai
STAGE=/tmp/xiyu-budget-deploy
SMOKE_FILE=$STAGE/smoke-budget-caps.mjs

echo "############ 预算冒烟验证 ############"
date
echo

echo "##### 0. 冒烟脚本就位情况 #####"
if [ ! -f "$SMOKE_FILE" ]; then
  echo "  缺失: $SMOKE_FILE —— 需要先上传"
  exit 1
fi
echo "  sha256=$(sha256sum "$SMOKE_FILE" | awk '{print $1}')"
echo "  导入路径: $(grep -m1 "^const db = await import" "$SMOKE_FILE")"
echo

echo "##### 1. 生产文件版本 #####"
sudo -n sha256sum "$ROOT/src/db.mjs" "$ROOT/src/proactive.mjs"
echo

echo "##### 2. 运行中的服务（确认已是新进程）#####"
PID=$(systemctl show xiyu-ai -p MainPID --value)
echo "  MainPID=$PID  启动于 $(ps -o lstart= -p "$PID" 2>/dev/null | xargs)"
echo "  服务状态=$(systemctl is-active xiyu-ai)"
echo

echo "##### 3. 隔离冒烟（临时 DB，独立进程，不碰生产库）#####"
NODE=$(systemctl show xiyu-ai -p ExecStart --value | sed -n 's/.*path=\([^ ;]*\).*/\1/p' | head -n1)
[ -x "$NODE" ] || NODE=$(command -v node)
echo "  node=$NODE"
sudo -n -u xiyu sh -c "TMPD=\$(mktemp -d /tmp/xiyu-budget-smoke.XXXXXX) && cd $ROOT && DB_PATH=\$TMPD/smoke.db DATA_DIR=\$TMPD LOG_DIR=\$TMPD $NODE $SMOKE_FILE; RC=\$?; rm -rf \$TMPD; exit \$RC"
RC=$?
echo "  冒烟退出码=$RC"
echo

if [ "$RC" -ne 0 ]; then
  echo "status=SMOKE_FAILED"
  exit 1
fi

echo "##### 4. 运行中的服务日志（确认新进程正常且额度已放宽）#####"
sudo -n journalctl -u xiyu-ai --since "$(date -u -d '5 minutes ago' '+%Y-%m-%d %H:%M:%S')" --no-pager 2>&1 \
  | grep -viE 'getUpdates success' | tail -20
echo
echo "status=SMOKE_OK"
