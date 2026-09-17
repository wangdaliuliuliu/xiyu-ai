#!/bin/bash
# 只读：拆解 9/15 每次模型调用的 token 构成
set -u
DB=/opt/xiyu-ai/data/bot.db
Q(){ sudo -n -u xiyu sqlite3 -readonly "$@"; }

echo "############ 9/15 成本拆解 ############"
date
echo

echo "##### 1. ai_usage_events 真实列名 #####"
Q "$DB" "PRAGMA table_info(ai_usage_events);"
echo

echo "##### 2. 逐次调用明细（近 5 天，按时间倒序）#####"
Q -header -column "$DB" "SELECT id, substr(created_at,1,19) t, provider, model, capability, prompt_tokens pt, completion_tokens ct, images, status, latency_ms FROM ai_usage_events WHERE created_at >= datetime('now','-5 days') ORDER BY id DESC LIMIT 40;"
echo

echo "##### 3. 按日 × 能力聚合 #####"
Q -header -column "$DB" "SELECT date(created_at) d, capability, COUNT(*) calls, SUM(prompt_tokens) pt, SUM(completion_tokens) ct, SUM(prompt_tokens+completion_tokens) total FROM ai_usage_events WHERE created_at >= datetime('now','-6 days') GROUP BY d, capability ORDER BY d DESC, total DESC;"
echo

echo "##### 4. 单次最贵的 10 条 #####"
Q -header -column "$DB" "SELECT substr(created_at,1,19) t, capability, prompt_tokens pt, completion_tokens ct, (prompt_tokens+completion_tokens) total, model FROM ai_usage_events WHERE created_at >= datetime('now','-6 days') ORDER BY total DESC LIMIT 10;"
echo

echo "##### 5. 9/15 单独看：哪几次调用、什么能力 #####"
Q -header -column "$DB" "SELECT substr(created_at,1,19) t, provider, model, capability, prompt_tokens pt, completion_tokens ct, (prompt_tokens+completion_tokens) total, status, latency_ms FROM ai_usage_events WHERE date(created_at)='2026-09-15' ORDER BY id;"
echo

echo "##### 6. 9/14 对照 #####"
Q -header -column "$DB" "SELECT substr(created_at,1,19) t, capability, prompt_tokens pt, completion_tokens ct, (prompt_tokens+completion_tokens) total FROM ai_usage_events WHERE date(created_at)='2026-09-14' ORDER BY id;" 2>&1 | head -30
echo

echo "############ 结束 ############"
