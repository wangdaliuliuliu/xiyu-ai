#!/bin/bash
# ============================================================
#  关系弧 hurt 卡死 — 只读诊断
# ============================================================
set -u
DB=/opt/xiyu-ai/data/bot.db
Q(){ sudo -n -u xiyu sqlite3 -readonly "$@"; }

echo "############ 关系弧 hurt 诊断 ############"
date

echo; echo "##### 1. 当前弧状态与时间戳 #####"
Q -header -column "$DB" "SELECT id, arc_state, arc_state_changed_at, attachment_style, safe_mode, last_user_reply_at FROM companions;" 2>&1

echo; echo "##### 2. 未结关系事件（openEvent）关键字段 #####"
Q -header -line "$DB" "SELECT * FROM relationship_events WHERE status='open' ORDER BY id DESC LIMIT 2;" 2>&1 | head -60

echo; echo "##### 3. 全部事件（看历史） #####"
Q -header -column "$DB" "SELECT id,type,severity,category,status,repair_status,repair_warm,created_at,resolved_at FROM relationship_events ORDER BY id DESC LIMIT 10;" 2>&1

echo; echo "##### 4. wechat_messages 是否有入站记录（hurt 自然消化计数依赖它）#####"
echo "-- 总行数 --"
Q "$DB" "SELECT COUNT(*) FROM wechat_messages;" 2>&1
echo "-- 入站行数 --"
Q "$DB" "SELECT COUNT(*) FROM wechat_messages WHERE direction='in';" 2>&1
echo "-- 最近 10 条（看时间与方向）--"
Q -header -column "$DB" "SELECT id, from_user, direction, substr(content,1,30) content, created_at FROM wechat_messages ORDER BY id DESC LIMIT 10;" 2>&1

echo; echo "##### 5. 事件之后的入站计数（_countInboundSince 的等价查询）#####"
Q -header -column "$DB" "SELECT COUNT(*) AS n FROM wechat_messages WHERE from_user=(SELECT wechat_user_id FROM companions LIMIT 1) AND direction='in' AND datetime(created_at) > datetime((SELECT created_at FROM relationship_events WHERE status='open' ORDER BY id DESC LIMIT 1));" 2>&1
echo "-- companions 的 wechat_user_id / bot_id（若为空，计数会直接返回 1）--"
Q -header -column "$DB" "SELECT id, wechat_user_id, bot_id FROM companions;" 2>&1

echo; echo "##### 6. 对话表 vs wechat_messages 的活跃度对比 #####"
echo "-- companion_conversation_turns 最近时间 --"
Q -header -column "$DB" "SELECT MAX(created_at) AS last_turn, COUNT(*) AS total FROM companion_conversation_turns;" 2>&1
echo "-- wechat_messages 最近时间 --"
Q -header -column "$DB" "SELECT MAX(created_at) AS last_msg, COUNT(*) AS total FROM wechat_messages;" 2>&1

echo; echo "##### 7. 弧信号日志（最近 8 条）#####"
Q -header -column "$DB" "SELECT id,signal_kind,severity,state_before,state_after,reason,created_at FROM companion_arc_signal_log ORDER BY id DESC LIMIT 8;" 2>&1

echo; echo "##### 8. 距事件已过多少小时（判断是否达到恢复门槛）#####"
Q -header -column "$DB" "SELECT datetime('now') AS utc_now, created_at AS event_at, ROUND((julianday('now')-julianday(created_at))*24,2) AS hours_since FROM relationship_events WHERE status='open' ORDER BY id DESC LIMIT 1;" 2>&1

echo; echo "##### 9. 弧相关参数的环境覆盖 #####"
systemctl show xiyu-ai -p Environment --no-pager 2>/dev/null | tr ' ' '\n' | grep -E '^ARC_' || echo "  （无 ARC_ 环境变量覆盖，使用默认值）"

echo; echo "############ 诊断结束 ############"
