#!/bin/bash
# ============================================================
#  只读：照片是否真的发出去（区分"说了要拍"与"实际投递"）
# ============================================================
set -u
DB=/opt/xiyu-ai/data/bot.db
Q(){ sudo -n -u xiyu sqlite3 -readonly "$@"; }

echo "############ 照片实际投递核查 ############"
date
echo

echo "##### 1. wechat_messages 里的图片消息（direction=out 且含图片标记）#####"
Q "$DB" "PRAGMA table_info(wechat_messages);" 2>&1 | head -20
echo "-- 最近 20 条出站内容与类型 --"
Q -header -column "$DB" "SELECT id, datetime(created_at) t, direction, substr(replace(content,char(10),' '),1,50) c FROM wechat_messages WHERE direction='out' ORDER BY id DESC LIMIT 20;" 2>&1
echo

echo "##### 2. photo_request_audit 全字段（看 decision 与结果列）#####"
Q "$DB" "PRAGMA table_info(photo_request_audit);" 2>&1
echo "-- 今天三条的完整记录 --"
Q -header -line "$DB" "SELECT * FROM photo_request_audit WHERE date(created_at)='2026-09-14' ORDER BY id;" 2>&1 | cut -c1-400
echo

echo "##### 3. 媒体/图片相关表清单 #####"
Q "$DB" "SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%photo%' OR name LIKE '%media%' OR name LIKE '%image%' OR name LIKE '%visual%');" 2>&1
echo

echo "##### 4. 日志里 photo/media 相关（近 12 小时，全部级别）#####"
sudo -n journalctl -u xiyu-ai --since "-12 hours" --no-pager 2>&1 \
  | grep -viE 'getUpdates success' \
  | grep -iE 'photo|image|media|media|上传|生成图|出图|图片' | tail -50
echo

echo "##### 5. 今天 03:40-06:45 的完整日志（照片请求时段）#####"
sudo -n journalctl -u xiyu-ai --since "2026-09-14 03:35" --until "2026-09-14 06:50" --no-pager 2>&1 \
  | grep -viE 'getUpdates success' | tail -60
echo

echo "############ 结束 ############"
