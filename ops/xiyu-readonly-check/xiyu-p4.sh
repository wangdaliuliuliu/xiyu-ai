#!/bin/bash
# ============================================================
#  溪语 P4 - 主动发送链路诊断（只读）
#  修正记录：
#   - 所有 sudo 带 -n（non-interactive，避免挂住）
#   - readlink 用 sudo -n（admin 读不到 xiyu 属主进程的 cwd）
#   - agency_feedback 真实列名（无 next_state）
#   - journalctl 带 sudo
# ============================================================
DB=/opt/xiyu-ai/data/bot.db
echo "############ P4 主动发送链路诊断 ############"
date

echo; echo "##### 1. app_settings 里所有 key（先看清结构）#####"
sudo -n -u xiyu sqlite3 -readonly -header -column "$DB" \
 "SELECT key, substr(value,1,300) val, updated_at FROM app_settings ORDER BY key;" 2>&1 | head -40

echo; echo "##### 2. 调度健康 / restrainedBy 全貌 #####"
sudo -n -u xiyu sqlite3 -readonly -header -column "$DB" \
 "SELECT key, substr(value,1,600) val FROM app_settings WHERE key LIKE '%health%' OR key LIKE '%deadman%' OR key LIKE '%proactive%';" 2>&1 | head -30

echo; echo "##### 3. 计划表结构 + 今天内容 #####"
sudo -n -u xiyu sqlite3 -readonly "$DB" "PRAGMA table_info(proactive_runtime_schedules);" 2>&1
echo "-- 全部行（看有几个角色、什么时候更新）--"
sudo -n -u xiyu sqlite3 -readonly -header -column "$DB" \
 "SELECT * FROM proactive_runtime_schedules ORDER BY updated_at DESC LIMIT 5;" 2>&1 | cut -c1-500

echo; echo "##### 4. 最近的 blocked/失败收据（完整 reason）#####"
sudo tail -30 /opt/xiyu-ai/data/initiative-ledger.jsonl 2>/dev/null | python3 -c "
import sys,json
for line in sys.stdin:
    try:
        d=json.loads(line)
        print(str(d.get('at',''))[:19], '|', str(d.get('action',''))[:28].ljust(28), '|', str(d.get('status',''))[:9].ljust(9), '|', str(d.get('reason',''))[:150])
    except Exception:
        pass
" 2>&1

echo; echo "##### 5. 全部意图状态 + 那条 planned 动作为何没发 #####"
sudo -n -u xiyu sqlite3 -readonly -header -column "$DB" \
 "SELECT id,state,domain,updated_at FROM agency_intentions ORDER BY updated_at DESC LIMIT 12;" 2>&1
echo "-- planned 动作完整字段 --"
sudo -n -u xiyu sqlite3 -readonly -header -line "$DB" \
 "SELECT * FROM agency_actions WHERE state='planned';" 2>&1 | cut -c1-300

echo; echo "##### 6. agency_feedback（真实列名）#####"
sudo -n -u xiyu sqlite3 -readonly -header -column "$DB" \
 "SELECT id,intention_id,kind,substr(interpretation,1,50) interp,confidence,created_at FROM agency_feedback ORDER BY created_at DESC LIMIT 15;" 2>&1

echo; echo "##### 7. 溪语主进程（sudo readlink 修正）#####"
for pid in $(pgrep -f 'node.*xiyu-ai|node.*index.mjs' 2>/dev/null); do
  echo "pid=$pid user=$(ps -o user= -p $pid 2>/dev/null | tr -d ' ') cwd=$(sudo -n readlink /proc/$pid/cwd 2>/dev/null)"
done
echo "-- 兜底：所有 node 进程 --"
for pid in $(pgrep -x node 2>/dev/null); do
  echo "pid=$pid user=$(ps -o user= -p $pid 2>/dev/null | tr -d ' ') cwd=$(sudo -n readlink /proc/$pid/cwd 2>/dev/null)"
done

echo; echo "##### 8. 日志：主动/动念/错误（过滤 iLink 轮询噪音）#####"
sudo journalctl -u xiyu-ai --since "2026-09-13 00:00" --no-pager 2>&1 \
 | grep -viE 'getUpdates success' \
 | grep -iE 'proactive|agency|deadman|restrain|error|warn|过期|stale|blocked|skip|动念' | tail -70

echo; echo "##### 9. 服务重启记录 #####"
sudo journalctl -u xiyu-ai --since "2026-09-12" --no-pager 2>&1 \
 | grep -iE 'Started|Stopped|Restarting|Failed|Main process|Scheduled restart' | tail -25

echo; echo "##### 10. 入站任务状态文件 #####"
sudo cat /opt/xiyu-ai/data/enterprise_context_active_tasks.json 2>/dev/null | head -70

echo; echo "############ 结束 ############"
