#!/bin/bash
# ============================================================
#  安装「主动通道不变量」定时检查（2026-09-18）
#
#  为什么：2026-09-14 ~ 09-18 主动通道卡过 5 次静默故障，
#          其中 3 次是**用户自己发现的**，不是系统报出来的。
#          单靠"修掉这个 bug"治不了这一族问题，得让下一个故障
#          自己冒出来。这个定时任务就是那个"自己冒出来"的机制。
#
#  跑什么：check-invariants.mjs（只读）
#          退出码 0 = 全通过；1 = 有违反；2 = 无法确证连对库
#  频率  ：每小时一次（判定纯本地，开销可忽略）
#  日志  ：/var/log/xiyu-invariants.log（追加，带时间戳）
#
#  注意：必须传绝对路径 DB_PATH。不传的话 db.mjs 会按 cwd 解析出
#        一个空库，六条不变量会**全部假通过**——这正是 2026-09-18
#        第一次跑检查器时踩到的坑。
# ============================================================
set -eu
ROOT=/opt/xiyu-ai
SERVICE=xiyu-ai
CHECKER=$ROOT/check-invariants.mjs
LOGFILE=/var/log/xiyu-invariants.log
UNIT=/etc/systemd/system/xiyu-invariants.service
TIMER=/etc/systemd/system/xiyu-invariants.timer

echo "############ 安装主动通道不变量定时检查 ############"
date; echo

[ -f "$CHECKER" ] || { echo "FAILED: 缺少 $CHECKER"; exit 1; }

echo "[1/4] 先手动跑一次，确认现在能给出真结论"
sudo -n -u xiyu env DB_PATH="$ROOT/data/bot.db" node "$CHECKER" 2>&1 | tail -14
echo

echo "[2/4] 写 systemd 单元"
sudo -n tee "$UNIT" > /dev/null <<EOF
[Unit]
Description=Xiyu proactive-channel invariant check
After=$SERVICE.service

[Service]
Type=oneshot
User=xiyu
WorkingDirectory=$ROOT
Environment=DB_PATH=$ROOT/data/bot.db
ExecStart=/usr/bin/node $CHECKER
StandardOutput=append:$LOGFILE
StandardError=append:$LOGFILE
# 0 = 通过，1 = 发现违反，2 = 无法确证连对库。
# 三种都不是"服务错误"，所以不设 SuccessExitStatus 之外的失败处理：
# 退出码本身就是结论，看日志即可。
SuccessExitStatus=0 1 2
EOF

sudo -n tee "$TIMER" > /dev/null <<EOF
[Unit]
Description=Run Xiyu proactive-channel invariant check hourly

[Timer]
OnCalendar=hourly
Persistent=true
AccuracySec=1min
Unit=xiyu-invariants.service

[Install]
WantedBy=timers.target
EOF
echo "  $UNIT"
echo "  $TIMER"
echo

echo "[3/4] 启用定时器"
sudo -n systemctl daemon-reload
sudo -n systemctl enable --now xiyu-invariants.timer
sudo -n systemctl list-timers xiyu-invariants.timer --no-pager | head -3
echo

echo "[4/4] 立即触发一次并看日志"
sudo -n systemctl start xiyu-invariants.service || true
sleep 3
echo "--- 最近日志 ---"
sudo -n tail -20 "$LOGFILE"
echo

echo "========== 结果 =========="
echo "timer=$(systemctl is-active xiyu-invariants.timer)"
echo "下一次=$(systemctl show xiyu-invariants.timer -p NextElapseUSecRealtime --value)"
echo "日志=$LOGFILE"
echo "查看： sudo journalctl -u xiyu-invariants 或 sudo tail -40 $LOGFILE"
echo "=========================="
