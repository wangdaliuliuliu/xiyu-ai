#!/bin/bash
# 只读：9/15、9/16 到底花了多少 token / 调了几次模型
set -u
DB=/opt/xiyu-ai/data/bot.db
Q(){ sudo -n -u xiyu sqlite3 -readonly "$@"; }

echo "############ 用量核对 ############"
date
echo

echo "##### 1. ai_usage_daily 近 6 天（按日汇总）#####"
Q "$DB" "PRAGMA table_info(ai_usage_daily);" 2>&1 | head -12
echo "-- 近 6 天 --"
Q -header -column "$DB" "SELECT * FROM ai_usage_daily WHERE day >= date('now','-6 days') ORDER BY day DESC;" 2>&1 | head -20
echo

echo "##### 2. ai_usage_events 近 6 天（逐次调用）#####"
Q "$DB" "PRAGMA table_info(ai_usage_events);" 2>&1 | head -14
echo "-- 按日聚合调用次数与 token --"
Q -header -column "$DB" "SELECT date(created_at) d, COUNT(*) calls, SUM(COALESCE(prompt_tokens,0)) pt, SUM(COALESCE(completion_tokens,0)) ct, SUM(COALESCE(total_tokens,0)) tt FROM ai_usage_events WHERE created_at >= datetime('now','-7 days') GROUP BY date(created_at) ORDER BY d DESC;" 2>&1
echo
echo "-- 近 6 天逐条（最多 25 条）--"
Q -header -column "$DB" "SELECT id, substr(created_at,1,19) t, COALESCE(model,'?') m, COALESCE(prompt_tokens,0) pt, COALESCE(completion_tokens,0) ct, COALESCE(total_tokens,0) tt, substr(COALESCE(purpose,''),1,20) p FROM ai_usage_events WHERE created_at >= datetime('now','-7 days') ORDER BY id DESC LIMIT 25;" 2>&1
echo

echo "##### 3. 动念预算表（agency_budget_reservations）近 6 天 #####"
Q -header -column "$DB" "SELECT day, purpose, state, attempts, SUM(tokens) tokens, COUNT(*) n FROM agency_budget_reservations WHERE day >= date('now','-6 days') GROUP BY day,purpose,state ORDER BY day DESC;" 2>&1
echo
echo "-- 按日合计 --"
Q -header -column "$DB" "SELECT day, SUM(attempts) attempts, SUM(tokens) tokens, COUNT(*) rows FROM agency_budget_reservations WHERE day >= date('now','-6 days') GROUP BY day ORDER BY day DESC;" 2>&1
echo

echo "##### 4. 9/15 与 9/16 的模型调用日志 #####"
sudo -n journalctl -u xiyu-ai --since "2026-09-15 00:00" --until "2026-09-17 00:00" --no-pager 2>&1 \
  | grep -viE 'getUpdates success' \
  | grep -iE 'usage|token|tokens|DeepSeek|provider|\[Agency\]|extractStructured|llm' | tail -40
echo

echo "##### 5. 排程里 sent:true 的时段，逐条判断是真发还是被作废 #####"
sudo -n journalctl -u xiyu-ai --since "2026-09-15 00:00" --until "2026-09-17 00:00" --no-pager 2>&1 \
  | grep -viE 'getUpdates success' \
  | grep -iE 'Proactive' | tail -40
echo

echo "############ 结束 ############"
