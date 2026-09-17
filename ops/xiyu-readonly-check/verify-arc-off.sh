#!/bin/bash
# 只读：确认 ARC_ENABLED 开关在服务进程中生效
set -u
SERVICE=xiyu-ai
echo "##### 1. drop-in 文件内容 #####"
DROPIN=/etc/systemd/system/$SERVICE.d/arc-disable.conf
sudo -n ls -la /etc/systemd/system/$SERVICE.d/ 2>&1
echo "-- 内容 --"
sudo -n cat "$DROPIN" 2>&1
echo

echo "##### 2. systemd 解析后的 Environment #####"
systemctl show $SERVICE -p Environment --no-pager 2>/dev/null | tr ' ' '\n' | grep -E 'ARC_|XIYU_AGENCY' || echo "  （主 Environment 无匹配；drop-in 生效即可）"
echo

echo "##### 3. 服务进程实际环境变量 #####"
PID=$(systemctl show $SERVICE -p MainPID --value)
echo "  MainPID=$PID  状态=$(systemctl is-active $SERVICE)"
echo "  启动时间: $(ps -o lstart= -p "$PID" 2>/dev/null | xargs)"
echo "  ARC_ 相关变量："
sudo -n cat /proc/$PID/environ 2>/dev/null | tr '\0' '\n' | grep -E '^ARC_' || echo "    未找到（可能被 systemd 的 Environment 合并方式影响）"
echo

echo "##### 4. 数据库弧状态 #####"
sudo -n -u xiyu sqlite3 -readonly /opt/xiyu-ai/data/bot.db -header -column \
  "SELECT id, arc_state, arc_state_changed_at FROM companions;" 2>&1
echo "-- 未结事件数 --"
sudo -n -u xiyu sqlite3 -readonly /opt/xiyu-ai/data/bot.db \
  "SELECT COUNT(*) FROM companion_relationship_events WHERE resolved_at IS NULL OR resolved_at='';" 2>&1
echo

echo "##### 5. 服务健康 #####"
curl -s --max-time 5 -f http://127.0.0.1:3000/api/health 2>&1 | head -c 120
echo
echo

echo "##### 6. 近期日志（过滤轮询）#####"
sudo -n journalctl -u $SERVICE --since "$(date -u -d '4 minutes ago' '+%Y-%m-%d %H:%M:%S')" --no-pager 2>&1 \
  | grep -viE 'getUpdates success' | tail -15
