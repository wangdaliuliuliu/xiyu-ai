#!/bin/bash
# ============================================================
#  导出最近 3 次自拍的完整提示词（只读）
# ============================================================
set -u
DB=/opt/xiyu-ai/data/bot.db
Q(){ sudo -n -u xiyu sqlite3 -readonly "$@"; }
OUT=/tmp/xiyu-photo-prompts.txt

{
echo "############ 最近 3 次自拍完整提示词导出 ############"
date
echo

Q -header -column "$DB" "SELECT id, substr(created_at,1,19) t, status, shot_mode, aspect, outbound_image_sent, outbound_caption_sent, substr(user_text,1,40) user_text FROM photo_request_audit ORDER BY id DESC LIMIT 6;"
echo

for ID in 17 18 19; do
  echo "================================================================"
  echo "########## 记录 id=$ID ##########"
  echo "================================================================"
  echo
  echo "----- 元信息 -----"
  Q -line "$DB" "SELECT id, request_id, substr(created_at,1,19) created, substr(completed_at,1,19) completed, status, error_code, provider, model, shot_mode, aspect, reference_image_path, reference_image_sha256, reference_image_used, output_file, caption, outbound_image_sent, outbound_caption_sent, substr(user_text,1,60) user_text, timings_json FROM photo_request_audit WHERE id=$ID;"
  echo
  echo "----- ① 送给规划模型的完整提示词 planner_prompt -----"
  Q "$DB" "SELECT planner_prompt FROM photo_request_audit WHERE id=$ID;"
  echo
  echo "----- ② 规划模型返回的原始 JSON planner_raw_json -----"
  Q "$DB" "SELECT planner_raw_json FROM photo_request_audit WHERE id=$ID;"
  echo
  echo "----- ③ 规范化后的计划 plan_json -----"
  Q "$DB" "SELECT plan_json FROM photo_request_audit WHERE id=$ID;"
  echo
  echo "----- ④ 最终送给图片 provider 的提示词 final_prompt -----"
  Q "$DB" "SELECT final_prompt FROM photo_request_audit WHERE id=$ID;"
  echo
  echo
done
} > "$OUT" 2>&1

echo "已写入 $OUT"
echo "字节数: $(wc -c < "$OUT")"
echo "行数: $(wc -l < "$OUT")"
echo
echo "-- 各段长度速览 --"
for ID in 17 18 19; do
  P=$(Q "$DB" "SELECT length(planner_prompt) FROM photo_request_audit WHERE id=$ID;")
  R=$(Q "$DB" "SELECT length(planner_raw_json) FROM photo_request_audit WHERE id=$ID;")
  J=$(Q "$DB" "SELECT length(plan_json) FROM photo_request_audit WHERE id=$ID;")
  F=$(Q "$DB" "SELECT length(final_prompt) FROM photo_request_audit WHERE id=$ID;")
  echo "  id=$ID  planner_prompt=$P  raw_json=$R  plan_json=$J  final_prompt=$F"
done
