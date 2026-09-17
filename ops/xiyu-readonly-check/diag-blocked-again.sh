#!/bin/bash
# 只读：今天下午之后为什么没理我
set -u
DB=/opt/xiyu-ai/data/bot.db
Q(){ sudo -n -u xiyu sqlite3 -readonly "$@"; }

echo "############ 今天下午之后 ############"
date
echo "上海时间: $(TZ=Asia/Shanghai date '+%Y-%m-%d %H:%M:%S')"
echo

echo "##### 1. 今天的排程逐条（含投递结果）#####"
TODAY=$(TZ=Asia/Shanghai date '+%Y-%m-%d')
echo "  today = $TODAY"
Q "$DB" "SELECT schedule_json FROM proactive_runtime_schedules WHERE date_key='$TODAY' ORDER BY updated_at DESC LIMIT 1;" 2>/dev/null | python3 -c "
import sys, json, datetime, zoneinfo
raw = sys.stdin.read().strip()
if not raw:
    print('  （今天没有排程）'); raise SystemExit
d = json.loads(raw)
now = datetime.datetime.now(zoneinfo.ZoneInfo('Asia/Shanghai'))
cur = now.hour*60 + now.minute
print('  当前 %02d:%02d  |  targetCount=%s' % (now.hour, now.minute, d.get('targetCount')))
print()
print('  %-8s %-10s %-8s %-24s %s' % ('计划','类型','已处理','投递结果','说明'))
for it in (d.get('items') or []):
    m = int(it.get('minute', -1)); hh, mm = divmod(m, 60)
    sent = 'yes' if it.get('sent') else 'no'
    out  = it.get('deliveryOutcome') or '-'
    err  = it.get('deliveryError') or ''
    at   = (it.get('deliveryAt') or '')[:19].replace('T',' ')
    if not it.get('sent'):
        note = '待触发(%d分钟后)' % (m-cur) if m > cur else '已过点未处理'
    else:
        note = ('%s %s' % (at, err)).strip()
    print('  %02d:%02d    %-10s %-8s %-24s %s' % (hh, mm, it.get('kind',''), sent, out, note))
"
echo

echo "##### 2. 今天真实投递出去的出站消息（唯一可信依据）#####"
Q -header -column "$DB" "SELECT id, datetime(created_at) t, msg_type, substr(replace(content,char(10),' '),1,55) c FROM wechat_messages WHERE direction='out' AND created_at >= datetime('now','-1 day') ORDER BY id DESC LIMIT 25;" 2>&1
echo
echo "-- 今天出站条数 --"
Q -header -column "$DB" "SELECT COUNT(*) n, MAX(created_at) last_out FROM wechat_messages WHERE direction='out' AND date(created_at)='$TODAY';" 2>&1
echo "-- 今天入站条数（你说了话吗）--"
Q -header -column "$DB" "SELECT COUNT(*) n, MAX(created_at) last_in FROM wechat_messages WHERE direction='in' AND date(created_at)='$TODAY';" 2>&1
echo

echo "##### 3. 今天的对话轮次 #####"
Q -header -column "$DB" "SELECT id, datetime(created_at) t, role, substr(replace(content,char(10),' / '),1,70) c FROM companion_conversation_turns WHERE created_at >= datetime('now','-1 day') ORDER BY id DESC LIMIT 20;" 2>&1
echo

echo "##### 4. 通道状态与计数 #####"
Q -header -column "$DB" "SELECT key, value, updated_at FROM app_settings WHERE key LIKE 'proactive_%';" 2>&1
echo

echo "##### 5. 今天所有 Proactive 日志（过滤轮询）#####"
sudo -n journalctl -u xiyu-ai --since "2026-09-17 12:00" --no-pager 2>&1 \
  | grep -viE 'getUpdates success' | grep -iE 'Proactive|Deadman|iLink.*(send|fail)|photo|Photo' | tail -40
echo

echo "############ 结束 ############"
