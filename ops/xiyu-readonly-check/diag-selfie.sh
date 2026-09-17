#!/bin/bash
# ============================================================
#  只读诊断：自拍/照片链路当前是否有阻断
# ============================================================
set -u
DB=/opt/xiyu-ai/data/bot.db
Q(){ sudo -n -u xiyu sqlite3 -readonly "$@"; }

echo "############ 自拍链路诊断 ############"
date
echo

echo "##### 1. 照片请求审计（最近 15 条）#####"
Q "$DB" "PRAGMA table_info(photo_request_audit);" 2>&1 | head -20
echo "-- 最近记录 --"
Q -header -column "$DB" "SELECT * FROM photo_request_audit ORDER BY id DESC LIMIT 15;" 2>&1 | cut -c1-260
echo

echo "##### 2. initiative-ledger 里照片相关动作 #####"
sudo -n grep -i 'photo\|story_photo\|contact_media\|send_image' /opt/xiyu-ai/data/initiative-ledger.jsonl 2>/dev/null | tail -8 | cut -c1-400
echo "-- ledger 总条数 --"
sudo -n wc -l /opt/xiyu-ai/data/initiative-ledger.jsonl 2>&1
echo

echo "##### 3. agency_actions 里的媒体类动作 #####"
Q -header -column "$DB" "SELECT action_type, state, COUNT(*) n FROM agency_actions GROUP BY action_type, state;" 2>&1
echo "-- 任何 contact_media / prepare_media 明细 --"
Q -header -column "$DB" "SELECT substr(id,1,22) id, action_type, state, substr(strategy_summary,1,40) s, updated_at FROM agency_actions WHERE action_type LIKE '%media%' OR action_type LIKE '%photo%' ORDER BY updated_at DESC LIMIT 10;" 2>&1
echo

echo "##### 4. 最近对话里照片相关往返 #####"
Q -header -column "$DB" "SELECT id, datetime(created_at) t, role, substr(replace(content,char(10),' / '),1,90) c FROM companion_conversation_turns WHERE content LIKE '%拍%' OR content LIKE '%照片%' OR content LIKE '%自拍%' OR content LIKE '%看%你%' ORDER BY id DESC LIMIT 20;" 2>&1
echo

echo "##### 5. 日志里的照片/图片事件（近 6 小时，过滤轮询）#####"
sudo -n journalctl -u xiyu-ai --since "-6 hours" --no-pager 2>&1 \
  | grep -viE 'getUpdates success' \
  | grep -iE 'photo|image|媒体|自拍|拍照|photo_intent|photo_planner|photo_sender|gate|latch|门闩|阻断' | tail -40
echo

echo "##### 6. 图片 provider 配置与额度 #####"
systemctl show xiyu-ai -p Environment --no-pager 2>/dev/null | tr ' ' '\n' | grep -iE 'IMAGE|PHOTO|GROK|XAI' | sed -E 's/(KEY|TOKEN|SECRET)=.*/\1=<hidden>/I' || echo "  主 Environment 无匹配"
echo "-- .env 中的图片相关键名（不含值）--"
sudo -n grep -oE '^(IMAGE|PHOTO|GROK|XAI)[A-Z_]*=' /opt/xiyu-ai/.env 2>/dev/null | sort -u || echo "  （无）"
echo

echo "##### 7. 今天照片发送的配额使用 #####"
Q -header -column "$DB" "SELECT companion_id, COUNT(*) n, MIN(created_at) first, MAX(created_at) last FROM photo_request_audit GROUP BY companion_id;" 2>&1
echo

echo "############ 结束 ############"
