#!/bin/bash
# 只读：列出本轮所有生产改动的真实部署时间（按备份目录 = 改动时刻）
set -u
echo "############ 生产改动时间线（备份目录即改动时刻）############"
date
echo
echo "##### 所有备份目录（UTC 名 + 本地时间）#####"
ls -1dt /opt/xiyu-backups/*/ 2>/dev/null | while read -r d; do
  printf '%s\n    本地: %s  内容: %s\n' "$(basename "$d")" "$(stat -c %y "$d" | cut -c1-19)" "$(ls "$d" 2>/dev/null | tr '\n' ' ')"
done
echo
echo "##### 关键源文件的生产修改时间 #####"
for f in src/visual_identity.mjs src/photo_sender.mjs src/photo_planner.mjs src/proactive.mjs src/db.mjs src/bot.mjs src/escalation.mjs src/relationship_arc.mjs; do
  printf '  %-32s %s\n' "$f" "$(sudo -n stat -c %y /opt/xiyu-ai/$f 2>/dev/null | cut -c1-19)"
done
echo
echo "##### systemd 重启记录（近 5 天）#####"
sudo -n journalctl -u xiyu-ai --since "-5 days" --no-pager 2>&1 | grep -iE 'Started|Stopped' | tail -25
