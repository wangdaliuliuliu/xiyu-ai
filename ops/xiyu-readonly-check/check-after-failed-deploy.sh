#!/bin/bash
# 只读：核对部署失败后的真实状态
set -u
ROOT=/opt/xiyu-ai
BACKUP=$(ls -1dt /opt/xiyu-backups/budget-deploy-* 2>/dev/null | head -1)

echo "############ 部署后状态核对 ############"
date

echo; echo "##### 1. 当前生产文件 hash（判断替换是否还在）#####"
for f in src/db.mjs src/proactive.mjs; do
  echo "-- $f --"
  sudo -n sha256sum "$ROOT/$f" 2>&1
  stat -c '   权限=%A 属主=%U:%G 大小=%s 修改时间=%y' "$ROOT/$f" 2>&1
done
echo
echo "期望：本次部署版本 db.mjs=a5f9deab…  proactive.mjs=41b1b065…"
echo "回滚版本   db.mjs=64cc65ef…  proactive.mjs=d170621e…"
echo "-- 实际是否为部署版（含新常量）--"
if sudo -n grep -q "AGENCY_DAILY_TOKEN_CAP" "$ROOT/src/db.mjs" 2>/dev/null; then
  echo "  db.mjs 仍是【部署版】"
else
  echo "  db.mjs 已回到【回滚版】"
fi

echo; echo "##### 2. 备份目录内容 #####"
echo "备份目录: $BACKUP"
sudo -n ls -la "$BACKUP" 2>&1
echo "-- 备份文件 hash --"
sudo -n sha256sum "$BACKUP"/*.mjs 2>&1

echo; echo "##### 3. 服务状态与进程启动时间 #####"
systemctl is-active xiyu-ai 2>&1
PID=$(systemctl show xiyu-ai -p MainPID --value)
echo "MainPID=$PID"
echo "进程启动时间: $(ps -o lstart= -p "$PID" 2>/dev/null)"
echo "当前时间:     $(date)"
echo "服务 ActiveEnterTimestamp: $(systemctl show xiyu-ai -p ActiveEnterTimestamp --value)"

echo; echo "##### 4. 进程实际加载的是哪一版代码 #####"
echo "（已运行的 node 进程会缓存模块，即使文件改了也不会重新读取）"
echo "进程已运行时长: $(ps -o etime= -p "$PID" 2>/dev/null)"

echo; echo "##### 5. 健康接口 #####"
curl -s --max-time 5 -f http://127.0.0.1:3000/api/health 2>&1 | head -c 200
echo

echo; echo "##### 6. 当前用户能做哪些免密 sudo 操作 #####"
sudo -n -l 2>&1 | tail -20

echo; echo "##### 7. 最近服务日志（看是否有异常）#####"
sudo -n journalctl -u xiyu-ai -n 15 --no-pager 2>&1 | tail -15

echo; echo "############ 核对结束 ############"
