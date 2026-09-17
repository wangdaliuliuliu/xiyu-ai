#!/bin/bash
# 只读：确认 9/15-9/17 主动消息是否真的投递成功
set -u
DB=/opt/xiyu-ai/data/bot.db
Q(){ sudo -n -u xiyu sqlite3 -readonly "$@"; }

echo "############ 投递真相核对 ############"
date
echo

echo "##### 1. wechat_messages 近 4 天出站记录（真实投递才入库）#####"
Q -header -column "$DB" "SELECT id, datetime(created_at) t, msg_type, substr(replace(content,char(10),' '),1,40) c FROM wechat_messages WHERE direction='out' AND created_at > datetime('now','-4 days') ORDER BY id DESC LIMIT 30;"
echo
echo "-- 出站总数与最后一条 --"
Q -header -column "$DB" "SELECT COUNT(*) n, MIN(created_at) first, MAX(created_at) last FROM wechat_messages WHERE direction='out' AND created_at > datetime('now','-4 days');"
echo

echo "##### 2. 入站记录（用户最后一次说话）#####"
Q -header -column "$DB" "SELECT id, datetime(created_at) t, substr(replace(content,char(10),' '),1,30) c FROM wechat_messages WHERE direction='in' ORDER BY id DESC LIMIT 5;"
echo

echo "##### 3. iLink 发送结果（近 4 天）#####"
echo "-- sendMessage / sendImage 成功记录 --"
sudo -n journalctl -u xiyu-ai --since "-4 days" --no-pager 2>&1 | grep -iE 'iLink.*(send|success|fail|error|token)' | tail -25
echo
echo "-- context_token 相关 --"
sudo -n journalctl -u xiyu-ai --since "-4 days" --no-pager 2>&1 | grep -iE 'context_token|窗口' | tail -15
echo

echo "##### 4. 9/15 和 9/16 的排程标记 vs 实际投递 #####"
Q -header -column "$DB" "SELECT date_key, substr(schedule_json,1,600) s FROM proactive_runtime_schedules WHERE date_key IN ('2026-09-15','2026-09-16') ORDER BY date_key;"
echo

echo "##### 5. initiative-ledger 近 4 天（主动意图收据）#####"
sudo -n tail -40 /opt/xiyu-ai/data/initiative-ledger.jsonl 2>/dev/null | python3 -c "
import sys, json
for line in sys.stdin:
    try:
        d = json.loads(line)
        at = str(d.get('at',''))[:19]
        if at >= '2026-09-14':
            print(at, '|', str(d.get('action',''))[:24].ljust(24), '|', str(d.get('status',''))[:9].ljust(9), '|', str(d.get('reason',''))[:80])
    except Exception:
        pass
" 2>&1 | tail -25
echo

echo "############ 结束 ############"
