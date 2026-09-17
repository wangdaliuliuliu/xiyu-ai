#!/bin/bash
# 只读：为什么两天没主动联系
set -u
DB=/opt/xiyu-ai/data/bot.db
Q(){ sudo -n -u xiyu sqlite3 -readonly "$@"; }

echo "############ 两天没理会话诊断 ############"
date
echo

echo "##### 1. 最近对话（她说过话吗）#####"
Q -header -column "$DB" "SELECT id, datetime(created_at) t, role, substr(replace(content,char(10),' '),1,45) c FROM companion_conversation_turns ORDER BY id DESC LIMIT 15;"
echo

echo "##### 2. 最后一轮消息时间 #####"
Q -header -column "$DB" "SELECT MAX(created_at) AS 最后一条, COUNT(*) AS 总数 FROM companion_conversation_turns;"
Q -header -column "$DB" "SELECT MAX(created_at) AS 最后入站 FROM wechat_messages WHERE direction='in';"
Q -header -column "$DB" "SELECT MAX(created_at) AS 最后出站 FROM wechat_messages WHERE direction='out';"
echo

echo "##### 3. 弧状态（受伤机制不是关了吗）#####"
Q -header -column "$DB" "SELECT id, arc_state, arc_state_changed_at FROM companions;"
echo

echo "##### 4. 主动调度状态（关键）#####"
Q -header -column "$DB" "SELECT key, substr(value,1,300) v, updated_at FROM app_settings WHERE key LIKE '%proactive%';"
echo

echo "##### 5. 今天的排程与执行情况 #####"
Q -header -column "$DB" "SELECT companion_id, date_key, substr(schedule_json,1,400) s, updated_at FROM proactive_runtime_schedules ORDER BY updated_at DESC LIMIT 3;"
echo

echo "##### 6. 近两天的 Deadman 心跳（sent 是否>0）#####"
sudo -n journalctl -u xiyu-ai --since "-48 hours" --no-pager 2>&1 | grep -i 'Deadman' | tail -15
echo

echo "##### 7. 近两天的主动/错误日志（过滤轮询）#####"
sudo -n journalctl -u xiyu-ai --since "-48 hours" --no-pager 2>&1 \
  | grep -viE 'getUpdates success' \
  | grep -iE 'Proactive|Agency|arc=|过期|降频|跳过|error|warn' | tail -30
echo

echo "##### 8. 服务重启记录与当前状态 #####"
systemctl is-active xiyu-ai
PID=$(systemctl show xiyu-ai -p MainPID --value)
echo "  MainPID=$PID 启动于 $(ps -o lstart= -p $PID 2>/dev/null | xargs)"
sudo -n journalctl -u xiyu-ai --since "-48 hours" --no-pager 2>&1 | grep -iE 'Started|Stopped' | tail -10
echo

echo "##### 9. 记忆/情绪最近是否更新 #####"
Q -header -column "$DB" "SELECT id, arc_state FROM companions;"
Q -header -column "$DB" "SELECT COUNT(*) AS 近两天动念数 FROM agency_intentions WHERE updated_at > datetime('now','-2 days');" 2>&1
Q -header -column "$DB" "SELECT action_type, state, COUNT(*) n, MAX(updated_at) last FROM agency_actions GROUP BY action_type,state;" 2>&1
echo

echo "############ 结束 ############"
