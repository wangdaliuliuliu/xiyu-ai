#!/bin/bash
# ============================================================
#  只读诊断：enterprise_context.mjs 生产版 vs git HEAD 版的差异规模
# ============================================================
set -u
ROOT=/opt/xiyu-ai
echo "############ enterprise_context.mjs 版本差异诊断 ############"
date
echo

echo "##### 1. 生产文件信息 #####"
stat -c '  大小=%s 修改时间=%y 属主=%U:%G' "$ROOT/src/enterprise_context.mjs"
echo "  sha256=$(sha256sum "$ROOT/src/enterprise_context.mjs" | awk '{print $1}')"
echo "  行数=$(wc -l < "$ROOT/src/enterprise_context.mjs")"
echo

echo "##### 2. 生产目录是否是 git 仓库 #####"
if [ -d "$ROOT/.git" ]; then
  echo "  是 git 仓库"
  cd "$ROOT"
  echo "  当前 HEAD: $(git rev-parse --short HEAD 2>&1)"
  echo "  分支: $(git branch --show-current 2>&1)"
  echo "  该文件的 git 状态:"
  git status --short src/enterprise_context.mjs 2>&1 | head -5
  echo "  git 里记录的版本 sha256:"
  git show HEAD:src/enterprise_context.mjs 2>/dev/null | sha256sum
  echo "  与工作区的差异行数:"
  git diff --stat HEAD -- src/enterprise_context.mjs 2>&1 | head -5
else
  echo "  不是 git 仓库（可能是发布包部署）"
fi
echo

echo "##### 3. 是否有备份能对照 #####"
ls -la /opt/xiyu-backups/ 2>/dev/null | tail -8
echo "-- 找历史版本 --"
find /opt/xiyu-backups -name 'enterprise_context.mjs' 2>/dev/null | tail -5
echo

echo "##### 4. 生产文件的关键函数/导出清单（用于判断版本特征）#####"
grep -nE '^export function|^export async function' "$ROOT/src/enterprise_context.mjs" | head -40
echo

echo "############ 结束 ############"
