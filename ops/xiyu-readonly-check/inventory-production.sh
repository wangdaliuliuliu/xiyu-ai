#!/bin/bash
# ============================================================
#  只读：本地仓库 vs 生产 /opt/xiyu-ai 全量文件比对
#  目的：确认生产是否比本地新（避免改动覆盖未知功能）
# ============================================================
set -u
ROOT=/opt/xiyu-ai
echo "############ 生产文件清单与指纹 ############"
date
echo
echo "##### src/ 全部文件（名称 大小 修改时间 sha256前12位）#####"
sudo -n find "$ROOT/src" -type f -name '*.mjs' | sort | while read -r f; do
  printf '%-58s %8s  %s  %s\n' "${f#$ROOT/}" "$(stat -c %s "$f")" "$(stat -c %y "$f" | cut -c1-19)" "$(sha256sum "$f" | cut -c1-12)"
done
echo
echo "##### config/ 全部文件 #####"
sudo -n find "$ROOT/config" -type f | sort | while read -r f; do
  printf '%-58s %8s  %s  %s\n' "${f#$ROOT/}" "$(stat -c %s "$f")" "$(stat -c %y "$f" | cut -c1-19)" "$(sha256sum "$f" | cut -c1-12)"
done
echo
echo "##### scripts/ 全部文件（只看名称与修改时间）#####"
sudo -n find "$ROOT/scripts" -type f -name '*.mjs' | sort | while read -r f; do
  printf '%-58s %8s  %s\n' "${f#$ROOT/}" "$(stat -c %s "$f")" "$(stat -c %y "$f" | cut -c1-19)"
done
echo
echo "##### 生产 photo_sender.mjs 是否有 productionReferencePaths #####"
sudo -n grep -n 'productionReferencePaths\|soft warm pastel\|body posture grows naturally' "$ROOT/src/photo_sender.mjs" | head -10
echo
echo "############ 结束 ############"
