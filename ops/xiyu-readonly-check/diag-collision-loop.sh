#!/bin/bash
# 只读：那个反复撞车的动念到底是什么状态
set -u
DB=/opt/xiyu-ai/data/bot.db
Q(){ sudo -n -u xiyu sqlite3 -readonly "$@"; }

echo "############ 撞车动念的真实状态 ############"
date
echo

echo "##### 1. 预检记的那个动念 #####"
Q -header -line "$DB" "SELECT id, state, domain, priority_class, substr(desired_change,1,70) desired, version, linked_business_task_ref, updated_at FROM agency_intentions WHERE id='agi_mu2igy2z_78b222d0c75665';" 2>&1
echo

echo "##### 2. 它的动作（planKey 对应的 action）#####"
Q -header -line "$DB" "SELECT id, intention_id, action_type, state, dedup_key, version, not_before, expires_at, updated_at FROM agency_actions WHERE intention_id='agi_mu2igy2z_78b222d0c75665';" 2>&1
echo

echo "##### 3. 今天所有动念 #####"
Q -header -column "$DB" "SELECT substr(id,1,28) id, state, domain, version, substr(desired_change,1,42) desired, updated_at FROM agency_intentions WHERE updated_at >= datetime('now','-1 day') ORDER BY updated_at DESC LIMIT 12;" 2>&1
echo

echo "##### 4. 今天所有动作（看 attempt 次数）#####"
Q -header -column "$DB" "SELECT substr(id,1,28) id, substr(intention_id,1,28) int_id, action_type, state, version, substr(dedup_key,1,36) dedup, updated_at FROM agency_actions WHERE updated_at >= datetime('now','-1 day') ORDER BY updated_at DESC LIMIT 15;" 2>&1
echo

echo "##### 5. 企业事件供给（订单表日报那条）#####"
echo "-- 入站任务状态 --"
sudo -n cat /opt/xiyu-ai/data/enterprise_context_active_tasks.json 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    for k, v in (d.items() if isinstance(d, dict) else enumerate(d)):
        print(' ', k, '|', str(v.get('statement') or v.get('goal'))[:70])
        print('     status =', v.get('status'), '| taskType =', v.get('taskType'), '| updated =', v.get('updatedAt'))
except Exception as e:
    print('  解析失败:', e)
"
echo "-- 待投递 outbox --"
sudo -n cat /opt/xiyu-ai/data/enterprise_context_outbox.json 2>/dev/null | head -c 800
echo
echo

echo "##### 6. 最近的企业事件收据（initiative-ledger 里的 work 类）#####"
sudo -n tail -60 /opt/xiyu-ai/data/initiative-ledger.jsonl 2>/dev/null | python3 -c "
import sys, json
for line in sys.stdin:
    try:
        d = json.loads(line)
        at = str(d.get('at',''))[:19]
        if at >= '2026-09-17':
            print(at, '|', str(d.get('action',''))[:26].ljust(26), '|', str(d.get('status',''))[:9].ljust(9), '|', str(d.get('reason',''))[:70])
    except Exception:
        pass
" 2>&1 | tail -20
echo

echo "##### 7. 复核校验的具体判定（撞车原因）#####"
echo "-- 最近对话里她关于'订单表'说过什么 --"
Q -header -column "$DB" "SELECT id, datetime(created_at) t, role, substr(replace(content,char(10),' / '),1,80) c FROM companion_conversation_turns WHERE content LIKE '%订单%' OR content LIKE '%日报%' OR content LIKE '%更新%' ORDER BY id DESC LIMIT 10;" 2>&1
echo

echo "############ 结束 ############"
