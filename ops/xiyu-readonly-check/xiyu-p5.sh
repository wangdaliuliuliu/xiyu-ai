#!/bin/bash
# ============================================================
#  溪语 P5 - 动念预算与阻断原因诊断（只读）
# ============================================================
DB=/opt/xiyu-ai/data/bot.db
echo "############ P5 预算与阻断诊断 ############"
date

echo; echo "##### 1. 今天的预算占用（关键！）#####"
sudo -n -u xiyu sqlite3 -readonly -header -column "$DB" \
 "SELECT day, purpose, state, attempts, SUM(tokens) tokens, COUNT(*) n
  FROM agency_budget_reservations GROUP BY day,purpose,state ORDER BY day DESC LIMIT 30;"

echo; echo "##### 2. 今天的预算合计 #####"
sudo -n -u xiyu sqlite3 -readonly -header -column "$DB" \
 "SELECT day, SUM(attempts) attempts_used, SUM(tokens) tokens_used, COUNT(*) rows_n
  FROM agency_budget_reservations GROUP BY day ORDER BY day DESC LIMIT 10;"
echo "-- 上限：calls<=8, tokens<=24000 --"

echo; echo "##### 3. 今天的每一条预算记录（看目的分布）#####"
sudo -n -u xiyu sqlite3 -readonly -header -column "$DB" \
 "SELECT substr(id,1,24) id, purpose, attempts, tokens, state, created_at
  FROM agency_budget_reservations WHERE day='2026-09-14' ORDER BY created_at;"

echo; echo "##### 4. agency_runtime（租约/冷却状态）#####"
sudo -n -u xiyu sqlite3 -readonly -header -line "$DB" "SELECT * FROM agency_runtime;" 2>&1 | cut -c1-200

echo; echo "##### 5. agency_concern_events（持续关切事件）#####"
sudo -n -u xiyu sqlite3 -readonly -header -column "$DB" \
 "SELECT * FROM agency_concern_events ORDER BY created_at DESC LIMIT 10;" 2>&1 | cut -c1-250

echo; echo "##### 6. 关系弧状态（arc=hurt 从哪来）#####"
sudo -n -u xiyu sqlite3 -readonly -header -column "$DB" \
 "SELECT * FROM companion_arc_signal_log ORDER BY id DESC LIMIT 15;" 2>&1 | cut -c1-220
echo "-- companions 表里的关系字段 --"
sudo -n -u xiyu sqlite3 -readonly -header -line "$DB" \
 "SELECT id,relationship_stage,affection_level,last_user_reply_at,proactive_enabled,proactive_daily_limit FROM companions;" 2>&1 | cut -c1-200

echo; echo "##### 7. 9-14 全天 agency 决策日志（看每次 cycle 结果）#####"
sudo journalctl -u xiyu-ai --since "2026-09-14 00:00" --no-pager 2>&1 \
 | grep -iE '\[Agency\]|\[Proactive\].*(arc|过期|skip|降频)' | tail -50

echo; echo "############ 结束 ############"
