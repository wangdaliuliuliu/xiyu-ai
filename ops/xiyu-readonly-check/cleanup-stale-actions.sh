#!/bin/bash
# ============================================================
#  清理积压的过期动作（可回滚）
#
#  背景：5 条 planned 动作最早过期 94 小时仍留在库里，导致：
#    - 派生它们的动念永远 ready → 每小时被重新选中、重新生成、
#      撞在同一条出站复核上（一天 3 次，纯浪费）
#    - 9-17 22:08 的晚安被这些旧动作拦掉（agency_blocked）
#
#  做法（最小、可回滚）：
#    1. 先做 sqlite 一致性备份
#    2. 把已过期且从未送出的 planned 动作标为 cancelled
#       （不改动念状态 —— 动念的收尾交给要实现的"保质期规则"，
#         这里只清掉已经没有意义的动作，避免今晚晚安再被拦）
#    3. 清掉预检失败记忆，避免它继续挡后续
#    4. 打印前后对照
#
#  回滚：用备份覆盖 bot.db 后重启服务
# ============================================================
set -u
DB=/opt/xiyu-ai/data/bot.db
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP=/opt/xiyu-backups/stale-cleanup-$STAMP
Q(){ sudo -n -u xiyu sqlite3 -readonly "$@"; }
W(){ sudo -n -u xiyu sqlite3 "$@"; }

echo "############ 清理积压过期动作 ############"
date
echo

echo "===== 1. 备份 ====="
sudo -n mkdir -p "$BACKUP" || { echo "建备份目录失败"; exit 1; }
sudo -n sqlite3 "$DB" ".timeout 15000" ".backup '$BACKUP/bot.db'" || { echo "备份失败"; exit 1; }
echo -n "  备份完整性: "
sudo -n sqlite3 "$BACKUP/bot.db" "PRAGMA integrity_check;" | head -1
echo "  备份路径: $BACKUP/bot.db"
echo

echo "===== 2. 清理前：待处理动作清单 ====="
Q -header -column "$DB" "SELECT substr(id,1,26) id, state, dedup_key, expires_at,
  ROUND((julianday('now')-julianday(expires_at))*24,1) AS 过期小时
  FROM agency_actions
  WHERE state IN ('planned','running','prepared')
    AND expires_at IS NOT NULL AND datetime(expires_at) < datetime('now')
  ORDER BY expires_at;"
echo

echo "===== 3. 执行清理 ====="
# 只清 planned 且已过期的。running/prepared 不动（可能在真实执行中）。
W "$DB" "UPDATE agency_actions
         SET state='cancelled', updated_at=CURRENT_TIMESTAMP
         WHERE state='planned'
           AND expires_at IS NOT NULL
           AND datetime(expires_at) < datetime('now');"
CLEANED=$?
echo "  UPDATE 退出码=$CLEANED"
echo

echo "===== 4. 清理后：剩余未完成动作 ====="
Q -header -column "$DB" "SELECT substr(id,1,26) id, state, dedup_key, expires_at
  FROM agency_actions WHERE state IN ('planned','running','sending','prepared')
  ORDER BY expires_at;"
echo "  （空 = 已无积压）"
echo

echo "===== 5. 清掉预检失败记忆 ====="
echo -n "  清理前: "
Q "$DB" "SELECT value FROM app_settings WHERE key='proactive_precheck_last_failure';"
W "$DB" "UPDATE app_settings SET value='', updated_at=CURRENT_TIMESTAMP WHERE key='proactive_precheck_last_failure';"
echo -n "  清理后: "
Q "$DB" "SELECT COALESCE(NULLIF(value,''),'(空)') FROM app_settings WHERE key='proactive_precheck_last_failure';"
echo

echo "===== 6. 动念状态未改动（对照）====="
Q -header -column "$DB" "SELECT substr(id,1,26) id, state, version, substr(desired_change,1,44) desired
  FROM agency_intentions WHERE state NOT IN ('completed','abandoned','expired')
  ORDER BY updated_at DESC;"
echo

echo "========== 结果 =========="
echo "backup=$BACKUP/bot.db"
echo "rollback=sudo systemctl stop xiyu-ai; sudo cp -p $BACKUP/bot.db $DB; sudo systemctl start xiyu-ai"
echo "=========================="
