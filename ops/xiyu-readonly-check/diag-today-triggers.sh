#!/bin/bash
# 只读：今天 12:17 / 13:16 两次触发到底出了什么
set -u
echo "############ 今天两次触发的实际过程 ############"
date
echo

echo "##### 1. 12:00 - 13:20 全部日志（过滤轮询噪音）#####"
sudo -n journalctl -u xiyu-ai --since "2026-09-17 12:00" --until "2026-09-17 13:20" --no-pager 2>&1 \
  | grep -viE 'getUpdates success' | tail -50
echo

echo "##### 2. context_token 缓存状态（决定窗口预检是否放行）#####"
DB=/opt/xiyu-ai/data/bot.db
echo "-- ilink_context_tokens 表 --"
sudo -n -u xiyu sqlite3 -readonly -header -column "$DB" \
  "SELECT bot_id, substr(user_id,1,24) user_id, substr(token,1,16) token_head, updated_at,
          ROUND((julianday('now') - julianday(updated_at)) * 24, 2) AS age_hours
   FROM ilink_context_tokens;" 2>&1
echo

echo "##### 3. 该表结构与 24h TTL 判定 #####"
echo "  当前时间: $(date '+%Y-%m-%d %H:%M:%S') UTC"
echo "  用户最后回复: 2026-09-14T17:27:32Z"
python3 - <<'PY'
import datetime
last = datetime.datetime(2026,9,14,17,27,32, tzinfo=datetime.timezone.utc)
now  = datetime.datetime.now(datetime.timezone.utc)
print('  距用户最后回复: %.2f 小时' % ((now-last).total_seconds()/3600))
print('  recallContextToken 的 TTL = 24 小时 → %s' % ('应判定窗口已关闭' if (now-last).total_seconds()/3600 > 24 else '仍视为窗口开启'))
PY
echo

echo "##### 4. 今天 08:21 的 morning 为什么标记 sent:true 却没有投递结果 #####"
sudo -n journalctl -u xiyu-ai --since "2026-09-17 08:15" --until "2026-09-17 08:30" --no-pager 2>&1 \
  | grep -viE 'getUpdates success' | tail -20
echo

echo "##### 5. 检查是否有其它路径跳过预检（企业事件/reminder）#####"
sudo -n journalctl -u xiyu-ai --since "2026-09-17 12:00" --until "2026-09-17 13:20" --no-pager 2>&1 \
  | grep -iE 'Proactive|Agency|经营候选|reminder|lastcall' | tail -25
echo

echo "############ 结束 ############"
