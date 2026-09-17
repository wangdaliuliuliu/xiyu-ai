#!/bin/bash
# 只读：导出最近 2 次照片请求的完整提示词
set -u
DB=/opt/xiyu-ai/data/bot.db
Q(){ sudo -n -u xiyu sqlite3 -readonly "$@"; }
OUT=/tmp/recent2-prompts.txt

{
echo "############ 最近 2 次照片请求 ############"
date
echo
Q -header -column "$DB" "SELECT id, substr(created_at,1,19) t, status, shot_mode, reference_image_sha256, outbound_image_sent, outbound_caption_sent, substr(user_text,1,30) user_text FROM photo_request_audit ORDER BY id DESC LIMIT 5;"
echo
for ID in $(Q "$DB" "SELECT id FROM photo_request_audit ORDER BY id DESC LIMIT 2;"); do
  echo "================================================================"
  echo "########## id=$ID ##########"
  echo "================================================================"
  Q -line "$DB" "SELECT id, substr(created_at,1,19) created, status, provider, model, shot_mode, aspect, reference_image_path, substr(reference_image_sha256,1,16) refsha, output_file, caption, outbound_image_sent, outbound_caption_sent, substr(user_text,1,50) user_text FROM photo_request_audit WHERE id=$ID;"
  echo
  echo "----- 最终送给图片模型的提示词 final_prompt -----"
  Q "$DB" "SELECT final_prompt FROM photo_request_audit WHERE id=$ID;"
  echo
  echo "----- 规划模型返回的 visualPlan（新结构才有）-----"
  Q "$DB" "SELECT plan_json FROM photo_request_audit WHERE id=$ID;" | head -c 2500
  echo
  echo
done
} > "$OUT" 2>&1

echo "写入 $OUT （$(wc -c < "$OUT") 字节）"
for ID in $(Q "$DB" "SELECT id FROM photo_request_audit ORDER BY id DESC LIMIT 2;"); do
  echo "  id=$ID final_prompt 长度=$(Q "$DB" "SELECT length(final_prompt) FROM photo_request_audit WHERE id=$ID;")"
done
