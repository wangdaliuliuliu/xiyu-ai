#!/bin/bash
# 只读：找出"东坝/隐性知识"相关的真实对话，看她的实际措辞
set -u
DB=/opt/xiyu-ai/data/bot.db
Q(){ sudo -n -u xiyu sqlite3 -readonly "$@"; }

echo "############ 东坝/知识提问 真实对话 ############"
date
echo

echo "##### 1. 含"东坝"或"知识/机会/判断"关键词的对话（最近 40 条）#####"
Q -header -column "$DB" "SELECT id, datetime(created_at) t, role, substr(replace(content,char(10),' '),1,80) c FROM companion_conversation_turns WHERE content LIKE '%东坝%' OR content LIKE '%机会%' OR content LIKE '%判断%' OR content LIKE '%隐性%' ORDER BY id DESC LIMIT 40;" 2>&1
echo

echo "##### 2. 最近 25 轮完整对话（看工作与陪伴的语气差别）#####"
Q -header -column "$DB" "SELECT id, datetime(created_at) t, role, substr(replace(content,char(10),' / '),1,100) c FROM companion_conversation_turns ORDER BY id DESC LIMIT 25;" 2>&1
echo

echo "##### 3. 企业事件历史（含 knowledge_gap 提问）#####"
Q "$DB" "SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%enterprise%' OR name LIKE '%intelligence%');" 2>&1
echo "-- 经营主动事件收据 --"
sudo -n tail -30 /opt/xiyu-ai/data/initiative-ledger.jsonl 2>/dev/null | python3 -c "
import sys, json
for line in sys.stdin:
    try:
        d = json.loads(line)
        act = str(d.get('action',''))
        if 'question' in act or 'knowledge' in act or 'business' in act or 'deliver' in act:
            print(str(d.get('at',''))[:19], '|', act[:26].ljust(26), '|', str(d.get('status',''))[:9].ljust(9), '|', str(d.get('objective',''))[:60])
    except Exception:
        pass
" 2>&1 | tail -12
echo

echo "##### 4. 入站任务状态文件（东坝那条）#####"
sudo -n cat /opt/xiyu-ai/data/enterprise_context_active_tasks.json 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    for k, v in (d.items() if isinstance(d, dict) else enumerate(d)):
        print('---', k, '---')
        print(json.dumps(v, ensure_ascii=False)[:1200])
except Exception as e:
    print('解析失败:', e)
" 2>&1 | head -40
echo

echo "##### 5. 工作台知识缺口（当前 open 的）#####"
TOKEN=$(sudo -n grep -oP '^XIYU_WORKBENCH_CONTEXT_TOKEN=\K.*' /opt/xiyu-ai/.env 2>/dev/null | head -1)
curl -s --max-time 8 -H "x-xiyu-token: $TOKEN" -H 'accept: application/json' \
  http://127.0.0.1:4175/api/knowledge/gaps 2>&1 | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    items = d.get('items', [])
    print('缺口数:', len(items))
    for it in items[:8]:
        print(' -', it.get('id'), '|', it.get('status'), '|', it.get('knowledgeTrack'), '|', it.get('acquisitionRoute'), '|', str(it.get('statement'))[:70])
except Exception as e:
    print('读取失败:', e)
" 2>&1
echo

echo "############ 结束 ############"
