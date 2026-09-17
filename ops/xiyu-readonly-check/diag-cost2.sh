#!/bin/bash
# 只读：拆解 9/15 成本（created_at 是整数时间戳，需转换）
set -u
DB=/opt/xiyu-ai/data/bot.db
Q(){ sudo -n -u xiyu sqlite3 -readonly "$@"; }

echo "############ 成本拆解（修正时间戳）############"
date
echo

echo "##### 1. 按日 × 能力聚合（近 6 天）#####"
Q -header -column "$DB" "SELECT date(created_at,'unixepoch','+8 hours') d, capability, COUNT(*) calls, SUM(prompt_tokens) pt, SUM(completion_tokens) ct, SUM(prompt_tokens+completion_tokens) total FROM ai_usage_events GROUP BY d, capability ORDER BY d DESC, total DESC LIMIT 40;"
echo

echo "##### 2. 按日合计 #####"
Q -header -column "$DB" "SELECT date(created_at,'unixepoch','+8 hours') d, COUNT(*) calls, SUM(prompt_tokens) pt, SUM(completion_tokens) ct, SUM(prompt_tokens+completion_tokens) total FROM ai_usage_events GROUP BY d ORDER BY d DESC LIMIT 10;"
echo

echo "##### 3. 单次最贵的 12 条 #####"
Q -header -column "$DB" "SELECT datetime(created_at,'unixepoch','+8 hours') t, capability, prompt_tokens pt, completion_tokens ct, (prompt_tokens+completion_tokens) total FROM ai_usage_events ORDER BY total DESC LIMIT 12;"
echo

echo "##### 4. 9/15 逐次调用 #####"
Q -header -column "$DB" "SELECT datetime(created_at,'unixepoch','+8 hours') t, provider, model, capability, prompt_tokens pt, completion_tokens ct, (prompt_tokens+completion_tokens) total, status, latency_ms FROM ai_usage_events WHERE date(created_at,'unixepoch','+8 hours')='2026-09-15' ORDER BY id;"
echo

echo "##### 5. 9/14 逐次调用（对照）#####"
Q -header -column "$DB" "SELECT datetime(created_at,'unixepoch','+8 hours') t, capability, prompt_tokens pt, completion_tokens ct, (prompt_tokens+completion_tokens) total FROM ai_usage_events WHERE date(created_at,'unixepoch','+8 hours')='2026-09-14' ORDER BY id;" 2>&1 | head -30
echo

echo "############ 结束 ############"
