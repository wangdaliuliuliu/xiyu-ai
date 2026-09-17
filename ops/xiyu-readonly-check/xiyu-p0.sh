#!/bin/bash
# ============================================================
#  溪语 P0 只读体检
#
#  用途：确认溪语线上真实基线与分区情况
#  安全：全部只读，不修改、不重启、不删除任何东西
#        绝不触碰 LIMI (/home/admin/LIMIbackend)
#        绝不触碰 capybara-game (/opt/capybara-game)
#
#  用法（可由 admin 账号远程执行）：
#      ssh -i ~/.ssh/xiyu-readonly-nopass admin@39.106.153.59 'bash -s' < xiyu-p0.sh
#
#  2026-09-14 修正：
#    a) agency_feedback 没有 next_state 列（原查询必然报错），改为真实列
#    b) 分区隔离检查改用 sudo -n 读 /proc/<pid>/cwd。admin 读不到
#       xiyu 属主进程的 cwd，原写法会静默漏掉 xiyu-ai 主进程 ——
#       也就是说这段“最关键”的检查以前从来没有真正验证过
#    c) 日志检查改用 sudo -n journalctl。普通用户看不到 journal，
#       原写法只会打印一行 "No entries"
#    d) 所有 sudo 均带 -n，避免在自动化执行时卡在密码提示
# ============================================================

echo "############ P0 溪语只读体检 ############"
date; hostname; whoami; uname -r

echo; echo "##### 1. 项目边界 #####"
echo "-- /opt 下目录（已排除 capybara-game）--"
ls -1 /opt 2>/dev/null | grep -vx -e 'capybara-game'
echo "-- LIMI 目录权限（只看权限，不进去）--"
stat -c '%A %U:%G %n' /home/admin/LIMIbackend 2>/dev/null || echo "(不存在)"
echo "-- 溪语与工作台目录权限 --"
stat -c '%A %U:%G %n' /opt/xiyu-ai /opt/yuanqu-workbench-api 2>/dev/null
echo "-- 溪语相关服务清单 --"
systemctl list-unit-files --type=service --no-pager 2>/dev/null | grep -E '^xiyu-ai|^yuanqu-workbench-api'

echo; echo "##### 2. 服务状态与启动方式 #####"
for s in xiyu-ai yuanqu-workbench-api; do
  echo "-- $s --"
  systemctl show $s -p ActiveState -p SubState -p MainPID -p User -p ExecStart -p EnvironmentFiles --no-pager
done
echo "-- 端口占用（按项目标注）--"
ss -ltnp 2>/dev/null | grep -E ':(3000|4175|8000|18001)\b'

echo; echo "##### 3. 溪语 node 进程（其他项目不显示）#####"
echo "-- 注意：读 /proc/<pid>/cwd 需要 sudo，否则 xiyu 属主进程会被漏掉 --"
for pid in $(pgrep -f 'xiyu-ai|yuanqu-workbench-api' 2>/dev/null); do
  cwd=$(sudo -n readlink /proc/$pid/cwd 2>/dev/null)
  user=$(ps -o user= -p $pid 2>/dev/null)
  case "$cwd" in
    /opt/xiyu-ai*|/opt/yuanqu-workbench-api*) echo "pid=$pid user=$user cwd=$cwd" ;;
    *) [ -n "$cwd" ] && echo "pid=$pid user=$user cwd=$cwd (out of scope)" ;;
  esac
done
echo "-- xiyu-ai 主进程属主（应为 xiyu，不是 admin/root）--"
XIYU_PID=$(systemctl show xiyu-ai -p MainPID --value 2>/dev/null)
echo "MainPID=$XIYU_PID user=$(ps -o user= -p $XIYU_PID 2>/dev/null) cwd=$(sudo -n readlink /proc/$XIYU_PID/cwd 2>/dev/null)"

echo; echo "##### 4. 数据文件与完整性 #####"
ls -la /opt/xiyu-ai/data/ 2>/dev/null | head -40
echo "-- 数据库完整性（只读打开）--"
for db in /opt/xiyu-ai/data/*.db; do
  [ -f "$db" ] || continue
  echo "-- $db (属主 $(stat -c '%U' $db 2>/dev/null)) --"
  sudo -n -u xiyu sqlite3 -readonly "$db" "PRAGMA integrity_check;" 2>&1 | head -3
done

echo; echo "##### 5. agency 动念历史（P3 关键数据）#####"
DB=/opt/xiyu-ai/data/bot.db
if [ -f "$DB" ]; then
  echo "-- 表清单 --"
  sudo -n -u xiyu sqlite3 -readonly "$DB" ".tables" 2>&1 | tr -s ' ' '\n' | head -40
  echo
  echo "-- agency_intentions 最近 15 条 --"
  sudo -n -u xiyu sqlite3 -readonly -header -column "$DB" \
    "SELECT id,state,domain,priority_class,substr(desired_change,1,50) AS desired,updated_at FROM agency_intentions ORDER BY updated_at DESC LIMIT 15;" 2>&1 | head -25
  echo
  echo "-- agency_actions 最近 15 条 --"
  sudo -n -u xiyu sqlite3 -readonly -header -column "$DB" \
    "SELECT intention_id,action_type,state,substr(strategy_summary,1,40) AS strategy,updated_at FROM agency_actions ORDER BY updated_at DESC LIMIT 15;" 2>&1 | head -25
  echo
  echo "-- 动作类型统计（看个人动念占比）--"
  sudo -n -u xiyu sqlite3 -readonly -header -column "$DB" \
    "SELECT action_type,state,COUNT(*) AS n FROM agency_actions GROUP BY action_type,state ORDER BY n DESC;" 2>&1 | head -25
  echo
  echo "-- 动念状态分布（看有多少卡在非 delivered）--"
  sudo -n -u xiyu sqlite3 -readonly -header -column "$DB" \
    "SELECT state,domain,COUNT(*) AS n FROM agency_intentions GROUP BY state,domain ORDER BY n DESC;" 2>&1 | head -20
  echo
  echo "-- agency_feedback 最近 10 条（列名按真实 schema，无 next_state）--"
  sudo -n -u xiyu sqlite3 -readonly -header -column "$DB" \
    "SELECT intention_id,kind,confidence,substr(interpretation,1,40) AS interp,created_at FROM agency_feedback ORDER BY created_at DESC LIMIT 10;" 2>&1 | head -15
  echo
  echo "-- 经营主动角色策略（account_id + companion_id 两个字段）--"
  sudo -n -u xiyu sqlite3 -readonly -header -column "$DB" \
    "SELECT account_id,companion_id,enabled,report_enabled,knowledge_enabled,order_monitor_enabled,updated_at FROM enterprise_proactive_policies;" 2>&1 | head -20
else
  echo "找不到 $DB"
fi

echo; echo "##### 6. 关键开关（只看开关名，值已隐藏）#####"
echo "-- systemd Environment 中设置的（值隐藏）--"
systemctl show xiyu-ai -p Environment --no-pager 2>/dev/null | tr ' ' '\n' \
  | grep -E '^(XIYU_AGENCY_MODE|XIYU_ENTERPRISE_PROACTIVE_ENABLED|XIYU_ENTERPRISE_CONTEXT_ENABLED|DB_PATH|XIYU_DB_PATH)=' \
  | sed -E 's/=.*/=<hidden>/'
echo "-- 唯一非敏感、可安全显示的模式开关 --"
systemctl show xiyu-ai -p Environment --no-pager 2>/dev/null | tr ' ' '\n' \
  | grep -E '^XIYU_AGENCY_MODE='
echo "-- .env 里存在哪些键（只列键名，绝不列值）--"
sudo -n grep -oE '^[A-Z_]+=' /opt/xiyu-ai/.env 2>/dev/null | sort -u | head -60 || echo "(读不到 .env)"
echo "-- 注意：XIYU_ENTERPRISE_* 与 XIYU_WORKBENCH_* 只在 .env 里，"
echo "   不在 systemd Environment 中，需读 .env 的值才能确认生效状态 --"

echo; echo "##### 7. 生产文件指纹 #####"
for f in /opt/xiyu-ai/config/agency-prompts.v1.json \
         /opt/xiyu-ai/src/initiative.mjs \
         /opt/xiyu-ai/src/proactive.mjs \
         /opt/xiyu-ai/src/agency_protocol.mjs \
         /opt/xiyu-ai/src/enterprise_context.mjs; do
  [ -f "$f" ] && sha256sum "$f"
done
echo "-- agency-prompts 里的 promptVersion --"
sudo -n grep -o '"promptVersion"[^,}]*' /opt/xiyu-ai/config/agency-prompts.v1.json 2>/dev/null

echo; echo "##### 8. 最近日志 #####"
sudo -n journalctl -q -u xiyu-ai -n 40 --no-pager 2>&1 | tail -40

echo; echo "############ 体检结束 ############"
