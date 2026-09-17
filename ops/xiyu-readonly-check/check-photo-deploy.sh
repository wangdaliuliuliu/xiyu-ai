#!/bin/bash
# 只读：部署后服务与照片链路状态核对
set -u
DB=/opt/xiyu-ai/data/bot.db
echo "############ 部署后核对 ############"
date
echo
echo "##### 1. 服务 #####"
echo "  状态: $(systemctl is-active xiyu-ai)"
PID=$(systemctl show xiyu-ai -p MainPID --value)
echo "  MainPID=$PID  启动于 $(ps -o lstart= -p $PID 2>/dev/null | xargs)"
echo "  健康: $(curl -s --max-time 5 -f http://127.0.0.1:3000/api/health | head -c 60)"
echo
echo "##### 2. 新进程启动后有无错误 #####"
sudo -n journalctl -u xiyu-ai --since "$(date -u -d '5 minutes ago' '+%Y-%m-%d %H:%M:%S')" --no-pager 2>&1 \
  | grep -viE 'getUpdates success' | grep -iE 'error|warn|fail|异常|失败' | head -10 || echo "  （无错误/警告）"
echo
echo "##### 3. 启动日志（过滤轮询）#####"
sudo -n journalctl -u xiyu-ai --since "$(date -u -d '5 minutes ago' '+%Y-%m-%d %H:%M:%S')" --no-pager 2>&1 \
  | grep -viE 'getUpdates success' | tail -8
echo
echo "##### 4. identity.json 生效值 #####"
sudo -n cat /opt/xiyu-ai/data/companion_visuals/1/identity.json | head -20
echo
echo "##### 5. 备份与回滚入口 #####"
ls -1dt /opt/xiyu-backups/photo-9block-* 2>/dev/null | head -1
echo
echo "############ 结束 ############"
