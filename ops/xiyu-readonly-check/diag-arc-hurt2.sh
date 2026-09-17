#!/bin/bash
# ============================================================
#  关系弧 hurt 卡死 — 诊断（表名修正版）
# ============================================================
set -u
DB=/opt/xiyu-ai/data/bot.db
Q(){ sudo -n -u xiyu sqlite3 -readonly "$@"; }

echo "############ 关系弧 hurt 诊断（修正表名）############"
date
echo "服务器时间: $(date '+%Y-%m-%d %H:%M:%S %Z')  (UTC: $(date -u '+%Y-%m-%d %H:%M:%S'))"

echo; echo "##### 1. companion_relationship_events 表结构 #####"
Q "$DB" "PRAGMA table_info(companion_relationship_events);" 2>&1

echo; echo "##### 2. 未结事件（openEvent）#####"
Q -header -line "$DB" "SELECT * FROM companion_relationship_events WHERE status='open' ORDER BY id DESC LIMIT 2;" 2>&1 | head -50

echo; echo "##### 3. 全部事件历史 #####"
Q -header -column "$DB" "SELECT id,type,severity,status,repair_status,repair_warm,created_at,resolved_at FROM companion_relationship_events ORDER BY id DESC LIMIT 10;" 2>&1

echo; echo "##### 4. companions 表实际列（找 wechat 身份字段）#####"
Q -header -column "$DB" "PRAGMA table_info(companions);" 2>&1 | head -40

echo; echo "##### 5. 事件后的入站消息计数（自然消化判定核心）#####"
EV_AT=$(Q "$DB" "SELECT created_at FROM companion_relationship_events WHERE status='open' ORDER BY id DESC LIMIT 1;" 2>/dev/null)
echo "未结事件创建时间: ${EV_AT:-（无）}"
echo "-- 用 wechat_messages 全表统计入站总数 --"
Q -header -column "$DB" "SELECT COUNT(*) AS inbound_total, MIN(created_at) AS first_in, MAX(created_at) AS last_in FROM wechat_messages WHERE direction='in';" 2>&1
echo "-- 事件之后的入站条数（按时间筛）--"
Q -header -column "$DB" "SELECT COUNT(*) AS n_after FROM wechat_messages WHERE direction='in' AND datetime(created_at) > datetime('${EV_AT}');" 2>&1
echo "-- 事件之后的入站明细 --"
Q -header -column "$DB" "SELECT id, substr(content,1,25) content, created_at FROM wechat_messages WHERE direction='in' AND datetime(created_at) > datetime('${EV_AT}') ORDER BY id;" 2>&1

echo; echo "##### 6. 关键判定：三条恢复路径的可达性 #####"
Q -header -column "$DB" "SELECT
  ROUND((julianday('now')-julianday(created_at))*24,1) AS hours_since_event,
  (SELECT COUNT(*) FROM wechat_messages WHERE direction='in' AND datetime(created_at) > datetime(companion_relationship_events.created_at)) AS interactions_since,
  repair_warm
  FROM companion_relationship_events WHERE status='open' ORDER BY id DESC LIMIT 1;" 2>&1
echo
echo "判定阈值（默认值）:"
echo "  faded            需要: interactions >= 5  且 hours >= 72"
echo "  soothed(warm)    需要: repair_warm >= 3  且 hours >= 12"
echo "  hurt_then_ignored 需要: interactions == 0 且 hours >= 36(secure)"
echo

echo; echo "##### 7. 距状态变更已过多久 #####"
Q -header -column "$DB" "SELECT arc_state, arc_state_changed_at, ROUND((julianday('now')-julianday(arc_state_changed_at))*24,1) AS hours_in_state FROM companions;" 2>&1

echo; echo "############ 结束 ############"
