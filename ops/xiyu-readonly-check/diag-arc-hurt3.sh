#!/bin/bash
# ============================================================
#  关系弧 hurt 卡死 — 诊断（第三版，字段名已核对）
# ============================================================
set -u
DB=/opt/xiyu-ai/data/bot.db
Q(){ sudo -n -u xiyu sqlite3 -readonly "$@"; }

echo "############ 关系弧 hurt 诊断（终版）############"
date
echo "UTC: $(date -u '+%Y-%m-%d %H:%M:%S')"
echo

echo "##### 1. 未结事件（resolved_at 为空 = open）#####"
Q -header -line "$DB" "SELECT id,companion_id,type,severity,repair_status,repair_warm,repair_from,reopened,created_at,resolved_at FROM companion_relationship_events WHERE resolved_at IS NULL OR resolved_at='' ORDER BY id DESC;" 2>&1

echo; echo "##### 2. 全部事件历史 #####"
Q -header -column "$DB" "SELECT id,type,severity,repair_status,repair_warm,created_at,resolved_at FROM companion_relationship_events ORDER BY id DESC LIMIT 10;" 2>&1

echo; echo "##### 3. 关键判定：三条恢复路径当前可达性 #####"
EV=$(Q "$DB" "SELECT created_at FROM companion_relationship_events WHERE (resolved_at IS NULL OR resolved_at='') ORDER BY id DESC LIMIT 1;" 2>/dev/null)
echo "未结事件创建时间: ${EV:-（无未结事件）}"
if [ -n "${EV:-}" ]; then
Q -header -column "$DB" "
SELECT
  ROUND((julianday('now')-julianday(created_at))*24,1) AS hours_since_event,
  repair_warm,
  (SELECT COUNT(*) FROM wechat_messages WHERE direction='in' AND datetime(created_at) > datetime('$EV')) AS interactions_since
FROM companion_relationship_events
WHERE (resolved_at IS NULL OR resolved_at='') ORDER BY id DESC LIMIT 1;" 2>&1
fi
echo
echo "阈值: faded = interactions>=5 且 hours>=72"
echo "      soothed = repair_warm>=3 且 hours>=12"
echo "      hurt_then_ignored = interactions==0 且 hours>=36 (secure)"
echo

echo; echo "##### 4. 事件后入站明细（interactions_since 的真实来源）#####"
if [ -n "${EV:-}" ]; then
Q -header -column "$DB" "SELECT id, substr(content,1,28) content, created_at FROM wechat_messages WHERE direction='in' AND datetime(created_at) > datetime('$EV') ORDER BY id;" 2>&1
fi
echo "-- 该 companion 的 wechat_user_id 与 bot_id（_countInboundSince 需要它们）--"
Q -header -column "$DB" "SELECT c.id, c.bot_id, b.wechat_user_id FROM companions c LEFT JOIN companion_bindings b ON b.companion_id=c.id LIMIT 5;" 2>&1 || \
Q -header -column "$DB" "SELECT id, bot_id FROM companions;" 2>&1
echo "-- 绑定表清单（找 wechat_user_id 在哪张表）--"
Q "$DB" "SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%bind%' OR name LIKE '%wechat%' OR name LIKE '%contact%');" 2>&1

echo; echo "############ 结束 ############"
