#!/bin/bash
# 只读：今天（9-17）的下一次主动触发是什么时候
set -u
DB=/opt/xiyu-ai/data/bot.db
Q(){ sudo -n -u xiyu sqlite3 -readonly "$@"; }

echo "############ 下一次主动触发 ############"
date
echo "本地时间: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "上海时间: $(TZ=Asia/Shanghai date '+%Y-%m-%d %H:%M:%S')"
echo "UTC:      $(date -u '+%Y-%m-%d %H:%M:%S')"
echo

echo "##### 1. 今天的上海日期键 #####"
TODAY=$(TZ=Asia/Shanghai date '+%Y-%m-%d')
echo "  today = $TODAY"
echo

echo "##### 2. 今天的排程（原始 JSON）#####"
Q -header -line "$DB" "SELECT companion_id, date_key, schedule_json, updated_at FROM proactive_runtime_schedules ORDER BY updated_at DESC LIMIT 1;" 2>&1 | head -30
echo

echo "##### 3. 排程逐条解析（时间 / 类型 / 是否已处理 / 投递结果）#####"
Q "$DB" "SELECT schedule_json FROM proactive_runtime_schedules ORDER BY updated_at DESC LIMIT 1;" 2>/dev/null | python3 -c "
import sys, json
raw = sys.stdin.read().strip()
if not raw:
    print('  （没有排程记录）')
    raise SystemExit
try:
    d = json.loads(raw)
except Exception as e:
    print('  解析失败:', e); raise SystemExit
print('  date_key   =', d.get('dateKey'))
print('  targetCount=', d.get('targetCount'))
items = d.get('items') or []
print('  条目数     =', len(items))
print()
# 上海当前分钟
import datetime, zoneinfo
now = datetime.datetime.now(zoneinfo.ZoneInfo('Asia/Shanghai'))
cur = now.hour*60 + now.minute
print('  上海当前时间 %02d:%02d （第 %d 分钟）' % (now.hour, now.minute, cur))
print()
print('  %-14s %-10s %-8s %-22s %s' % ('计划时间','类型','已处理','投递结果','状态'))
for it in items:
    m = int(it.get('minute', -1))
    hh, mm = divmod(m, 60)
    sent = 'yes' if it.get('sent') else 'no'
    outcome = it.get('deliveryOutcome') or '-'
    if it.get('sent'):
        state = '已处理'
    elif m <= cur:
        state = '★ 已过点但未处理（可能下次 tick 处理）'
    else:
        state = '待触发 (%d 分钟后)' % (m - cur)
    print('  %02d:%02d          %-10s %-8s %-22s %s' % (hh, mm, it.get('kind',''), sent, outcome, state))
"
echo

echo "##### 4. 允许的主动时间窗与每日目标 #####"
Q -header -column "$DB" "SELECT id, proactive_enabled, proactive_frequency, proactive_time_window, last_user_reply_at FROM companions;" 2>&1
echo

echo "##### 5. 硬间隔与上次发送 #####"
Q -header -column "$DB" "SELECT key, value, updated_at FROM app_settings WHERE key LIKE '%proactive_last%' OR key LIKE '%last_proactive%';" 2>&1
echo

echo "##### 6. 主动通道状态（窗口是否开着）#####"
Q -header -column "$DB" "SELECT key, value, updated_at FROM app_settings WHERE key LIKE 'proactive_%';" 2>&1
echo

echo "##### 7. 服务与最近 tick #####"
echo "  服务: $(systemctl is-active xiyu-ai)"
echo "  tick 心跳: $(Q "$DB" "SELECT value FROM app_settings WHERE key='proactive_tick_last_run';")"
echo "  Deadman 最近心跳:"
sudo -n journalctl -u xiyu-ai --since "-40 minutes" --no-pager 2>&1 | grep -i 'Deadman' | tail -3
echo

echo "############ 结束 ############"
