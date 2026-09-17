#!/bin/bash
# ============================================================
#  部署前探测（只读）— 预算修正改动
# ============================================================
set -u
ROOT=/opt/xiyu-ai

echo "############ 部署前探测 ############"
date

echo; echo "##### 1. 待替换文件现状 #####"
for f in src/db.mjs src/proactive.mjs; do
  echo "-- $f --"
  stat -c '  权限=%A 属主=%U:%G 大小=%s 修改时间=%y' "$ROOT/$f" 2>&1
  echo "  sha256=$(sha256sum "$ROOT/$f" 2>/dev/null | awk '{print $1}')"
done

echo; echo "##### 2. 目录是否可写（部署需要）#####"
stat -c '  %A %U:%G %n' "$ROOT" "$ROOT/src" 2>&1
echo "  当前用户: $(whoami)  可免密sudo: $(sudo -n true 2>/dev/null && echo 是 || echo 否)"

echo; echo "##### 3. 服务与健康接口 #####"
systemctl is-active xiyu-ai 2>&1
echo "-- 健康接口（部署后要校验它返回 ok:true）--"
curl --silent --show-error --max-time 5 --fail http://127.0.0.1:3000/api/health 2>&1 | head -c 400 || echo "(健康接口不可达或非该路径)"
echo

echo; echo "##### 4. 服务运行时与语法检查能力 #####"
NODE=$(systemctl show xiyu-ai -p ExecStart --value 2>/dev/null | sed -n 's/.*path=\([^ ;]*\).*/\1/p' | head -n1)
echo "  服务 node: ${NODE:-未解析到}"
echo "  版本: $("$NODE" --version 2>&1)"
echo "-- 能否以服务用户 xiyu 对当前文件做语法检查 --"
sudo -n -u xiyu "$NODE" --check "$ROOT/src/db.mjs" 2>&1 && echo "  xiyu 可读且语法检查通过" || echo "  xiyu 语法检查失败"
sudo -n -u xiyu "$NODE" --check "$ROOT/src/proactive.mjs" 2>&1 && echo "  proactive 语法检查通过" || echo "  proactive 语法检查失败"
echo "-- 能否以 xiyu 解析 better-sqlite3（部署后冒烟要用）--"
sudo -n -u xiyu sh -c "cd $ROOT && $NODE --input-type=module -e \"import{createRequire}from'node:module';import{pathToFileURL}from'node:url';const r=createRequire(pathToFileURL('$ROOT/package.json'));console.log('resolved:',r.resolve('better-sqlite3'))\"" 2>&1 | tail -3

echo; echo "##### 5. 备份目录可用性 #####"
ls -ld /opt/xiyu-backups 2>&1 || echo "  /opt/xiyu-backups 不存在（备份时将创建）"
echo "  磁盘剩余: $(df -h /opt | tail -1 | awk '{print $4}')"

echo; echo "############ 探测结束 ############"
