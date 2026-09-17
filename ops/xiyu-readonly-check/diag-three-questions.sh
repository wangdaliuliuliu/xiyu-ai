#!/bin/bash
# 只读：三个问题的取证
set -u
DB=/opt/xiyu-ai/data/bot.db
Q(){ sudo -n -u xiyu sqlite3 -readonly "$@"; }

echo "############ 三问取证 ############"
date
echo "上海: $(TZ=Asia/Shanghai date '+%Y-%m-%d %H:%M:%S')"
echo

echo "===== 问题1：过期动作是否还在候选池里 ====="
echo "-- 该动念的完整字段 --"
Q -line "$DB" "SELECT * FROM agency_intentions WHERE id='agi_mu2igy2z_78b222d0c75665';" 2>&1
echo
echo "-- 该动作的完整字段 --"
Q -line "$DB" "SELECT * FROM agency_actions WHERE id='aga_mu2igzfi_448f47594dfeca';" 2>&1
echo
echo "-- 全部 planned / running / sending 状态的动作（这些是'未完成'的）--"
Q -header -column "$DB" "SELECT substr(id,1,26) id, substr(intention_id,1,26) int_id, state, version, substr(dedup_key,1,20) dedup, not_before, expires_at, updated_at FROM agency_actions WHERE state IN ('planned','running','sending','prepared') ORDER BY updated_at DESC;" 2>&1
echo
echo "-- 过期判定：expires_at 早于现在的未完成动作 --"
Q -header -column "$DB" "SELECT substr(id,1,26) id, state, expires_at, ROUND((julianday('now')-julianday(expires_at))*24,1) AS 过期小时 FROM agency_actions WHERE state IN ('planned','running','sending','prepared') AND expires_at IS NOT NULL AND datetime(expires_at) < datetime('now') ORDER BY expires_at;" 2>&1
echo
echo "-- 该动念在哪个排程/事件里被引用 --"
Q -header -column "$DB" "SELECT id, substr(intention_id,1,26) int_id, event_kind, created_at FROM agency_concern_events WHERE intention_id='agi_mu2igy2z_78b222d0c75665' ORDER BY created_at DESC LIMIT 10;" 2>&1
echo

echo "===== 问题2：预检为什么没拦住 ====="
echo "-- 预检记忆当前值 --"
Q -header -column "$DB" "SELECT value, updated_at FROM app_settings WHERE key='proactive_precheck_last_failure';" 2>&1
echo
echo "-- 该动念是否还挂在企业任务上（linked_business_task_ref）--"
Q -header -column "$DB" "SELECT id, linked_business_task_ref, state FROM agency_intentions WHERE linked_business_task_ref IS NOT NULL AND state NOT IN ('completed','abandoned','expired');" 2>&1
echo

echo "===== 问题3：晚安为什么 agency_blocked ====="
echo "-- 晚安动念状态 --"
Q -header -column "$DB" "SELECT substr(id,1,28) id, state, version, domain, priority_class, substr(desired_change,1,50) desired, updated_at FROM agency_intentions WHERE desired_change LIKE '%晚安%' OR desired_change LIKE '%睡前%' ORDER BY updated_at DESC LIMIT 5;" 2>&1
echo
echo "-- 晚安动念的动作 --"
Q -header -column "$DB" "SELECT substr(id,1,26) id, substr(intention_id,1,26) int_id, action_type, state, version, updated_at FROM agency_actions WHERE action_type='contact_text' AND intention_id IN (SELECT id FROM agency_intentions WHERE desired_change LIKE '%晚安%' OR desired_change LIKE '%睡前%') ORDER BY updated_at DESC LIMIT 8;" 2>&1
echo
echo "-- 预算余量（agency_blocked 可能因预算耗尽）--"
Q -header -column "$DB" "SELECT day, purpose, state, SUM(attempts) att, SUM(tokens) tk FROM agency_budget_reservations WHERE day >= date('now','-2 days') GROUP BY day,purpose,state ORDER BY day DESC;" 2>&1
echo
echo "-- agency_runtime 租约/冷却 --"
Q -header -line "$DB" "SELECT * FROM agency_runtime;" 2>&1
echo

echo "===== 附：企业事件是否还在供给这条旧任务 ====="
TOKEN=$(sudo -n grep -oP '^XIYU_WORKBENCH_CONTEXT_TOKEN=\K.*' /opt/xiyu-ai/.env 2>/dev/null | head -1)
echo "-- 待投递事件（purposes=knowledge_acquisition）--"
curl -s --max-time 8 -H "x-xiyu-token: $TOKEN" 'http://127.0.0.1:4175/api/intelligence/events?status=pending' 2>&1 | head -c 1200
echo
echo

echo "############ 结束 ############"
