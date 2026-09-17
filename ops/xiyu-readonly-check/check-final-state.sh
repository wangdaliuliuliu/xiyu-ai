#!/bin/bash
# 只读：部署后最终状态核对
set -u
DB=/opt/xiyu-ai/data/bot.db
echo "############ 最终状态 ############"
date
echo
echo -n "服务:   "; systemctl is-active xiyu-ai
PID=$(systemctl show xiyu-ai -p MainPID --value)
echo "PID:    $PID  启动于 $(ps -o lstart= -p $PID 2>/dev/null | xargs)"
echo -n "健康:   "; curl -s --max-time 5 -f http://127.0.0.1:3000/api/health | head -c 50; echo
echo
echo "--- 积压未完成动作（应为 0）---"
sudo -n -u xiyu sqlite3 -readonly "$DB" "SELECT COUNT(*) FROM agency_actions WHERE state IN ('planned','running','sending','prepared');"
echo
echo "--- 未完成动念分布 ---"
sudo -n -u xiyu sqlite3 -readonly -header -column "$DB" "SELECT state, COUNT(*) AS n FROM agency_intentions WHERE state NOT IN ('completed','abandoned','expired') GROUP BY state;"
echo
echo "--- 已被收尾的动念（本次机制的效果）---"
sudo -n -u xiyu sqlite3 -readonly -header -column "$DB" "SELECT substr(id,1,26) id, state, substr(next_review_condition,1,44) reason, updated_at FROM agency_intentions WHERE state IN ('expired','completed') ORDER BY updated_at DESC LIMIT 8;"
echo
echo "--- 近期相关日志 ---"
sudo -n journalctl -u xiyu-ai --since "-6 minutes" --no-pager 2>&1 | grep -viE 'getUpdates success' | grep -iE '动念收尾|expired|Proactive|Agency' | tail -12
echo
echo "############ 结束 ############"
