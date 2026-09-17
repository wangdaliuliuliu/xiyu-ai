#!/bin/bash
# ============================================================
#  部署「反馈落库失败」修复
#
#  症状：同一动念上用户消息的反馈反复 status=invalid（2026-09-14 出现 6+ 次），
#        表现为"她记不住用户的反应"。
#  真因（经探针实测确认）：动念处于 preparing 时模型给 nextState=active，
#        而转移表里 preparing 不含 active → updateAgencyIntention 返回 null →
#        事务抛 invalid_transition → 整条反馈被丢弃。重试无用。
#  修法：commitAgencyFeedback 写库前把 nextState 收敛到合法目标（clampAgencyNextState）；
#        另在 bot.mjs 为版本冲突增加「重读后重试」。
#
#  回滚：sudo cp -p <backup>/db.mjs <backup>/bot.mjs /opt/xiyu-ai/src/
#        && sudo systemctl restart xiyu-ai   （两个文件都要回滚）
# ============================================================
set -u
ROOT=/opt/xiyu-ai
SERVICE=xiyu-ai
HEALTH=http://127.0.0.1:3000/api/health
STAGE=/tmp/xiyu-feedback-fix
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP=/opt/xiyu-backups/feedback-fix-$STAMP
FILES="src/db.mjs src/bot.mjs"

log(){ printf '[fb-fix] %s\n' "$*"; }
fail(){ log "FAILED: $*"; }

rollback(){
  log "回滚中 ..."
  for f in $FILES; do
    b="$BACKUP/$(basename $f)"
    [ -f "$b" ] && sudo -n cp -p "$b" "$ROOT/$f" && log "  已恢复 $f"
  done
  sudo -n systemctl restart $SERVICE
  sleep 4
  curl -s --max-time 5 -f "$HEALTH" | grep -q '"ok"[[:space:]]*:[[:space:]]*true' \
    && log "  回滚后健康通过" || log "  回滚后健康未通过，需人工介入"
}

echo "############ 部署反馈修复 ############"
date
echo

log "步骤0：检查待部署文件"
for f in db.mjs bot.mjs; do
  [ -f "$STAGE/$f" ] || { fail "缺少 $STAGE/$f"; exit 1; }
done
echo "-- db.mjs 新逻辑 --"
grep -n "clampAgencyNextState" "$STAGE/db.mjs" | head -5
echo "-- bot.mjs 新逻辑 --"
grep -n "conflict_retry\|版本冲突重试" "$STAGE/bot.mjs" | head -5
echo

log "步骤1：备份到 $BACKUP"
sudo -n mkdir -p "$BACKUP" || { fail "建备份目录失败"; exit 1; }
for f in $FILES; do
  sudo -n cp -p "$ROOT/$f" "$BACKUP/$(basename $f)" || { fail "备份 $f 失败"; exit 1; }
  log "  已备份 $f sha256=$(sudo -n sha256sum "$ROOT/$f" | awk '{print $1}')"
done
echo

log "步骤2：替换并做语法检查"
NODE=$(systemctl show $SERVICE -p ExecStart --value | sed -n 's/.*path=\([^ ;]*\).*/\1/p' | head -n1)
[ -x "$NODE" ] || NODE=$(command -v node)
for pair in "src/db.mjs db.mjs" "src/bot.mjs bot.mjs"; do
  set -- $pair; target="$ROOT/$1"; staged="$STAGE/$2"
  OWNER=$(stat -c '%u:%g' "$target"); MODE=$(stat -c '%a' "$target")
  sudo -n install -m "$MODE" -o "${OWNER%%:*}" -g "${OWNER##*:}" "$staged" "$target" || { fail "替换 $1 失败"; rollback; exit 1; }
  sudo -n -u xiyu "$NODE" --check "$target" || { fail "$1 语法检查失败"; rollback; exit 1; }
  log "  $1 替换成功 权限=$MODE 属主=$OWNER 语法OK sha256=$(sudo -n sha256sum "$target" | awk '{print $1}')"
done
echo

log "步骤3：重启 + 健康校验"
OLD_PID=$(systemctl show $SERVICE -p MainPID --value)
sudo -n systemctl restart $SERVICE || { fail "重启失败"; rollback; exit 1; }
OK=0
for i in $(seq 1 45); do
  if curl -s --max-time 5 -f "$HEALTH" | grep -q '"ok"[[:space:]]*:[[:space:]]*true'; then OK=1; break; fi
  sleep 2
done
[ "$OK" -eq 1 ] || { fail "健康检查未通过"; sudo -n journalctl -u $SERVICE -n 30 --no-pager | tail -30; rollback; exit 1; }
NEW_PID=$(systemctl show $SERVICE -p MainPID --value)
log "  健康通过 旧PID=$OLD_PID 新PID=$NEW_PID 状态=$(systemctl is-active $SERVICE)"
echo

log "步骤4：用生产代码实测「非法状态不再丢反馈」"
cat > "$STAGE/proof.mjs" <<'EOF'
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'xiyu-fbproof-'));
Object.assign(process.env, { DB_PATH: path.join(dir, 'db.sqlite'), DATA_DIR: dir, LOG_DIR: path.join(dir, 'logs') });
const db = await import('/opt/xiyu-ai/src/db.mjs');
const store = db.getDb();
const cid = Number(store.prepare('INSERT INTO companions(user_id,bot_id,name) VALUES(NULL,?,?)').run('proof-bot','证明').lastInsertRowid);
const owner = { accountId: 8801, companionId: cid };
const it = db.createAgencyIntention({ ...owner, semanticKey:'proof', desiredChange:'proof', basisRefs:['f'], state:'candidate', domain:'mixed' });
db.updateAgencyIntention(it.id, { ...owner, expectedVersion: it.version, state:'preparing' });
const cur = db.getAgencyIntention(it.id, owner);
const r = db.commitAgencyFeedback({
  ...owner, intentionId: it.id, expectedVersion: cur.version,
  feedback: { sourceMessageId:'proof-msg', kind:'answer', rawRef:'x', interpretation:'y', confidence:1 },
  update: { state:'active', lastFeedbackAt: new Date().toISOString() },
});
console.log('状态 =', cur.state, '模型想要 = active（非法）');
console.log('提交结果 status =', r.status, '| 收敛后 state =', r.intention?.state);
const saved = db.listAgencyFeedback({ ...owner, intentionId: it.id, limit: 5 });
console.log('反馈已落库 =', saved.some(f => f.source_message_id === 'proof-msg') ? 'YES' : 'NO');
const ok = r.status === 'committed' && r.intention?.state !== 'active' && saved.some(f => f.source_message_id === 'proof-msg');
console.log('FIX_EFFECTIVE=' + (ok ? 'YES' : 'NO'));
store.close();
process.exit(ok ? 0 : 1);
EOF
sudo -n -u xiyu "$NODE" "$STAGE/proof.mjs"
PROOF_RC=$?
echo "  证明脚本退出码=$PROOF_RC"
echo

log "步骤5：确认线上不再出现 invalid_transition（近 2 分钟日志）"
sudo -n journalctl -u $SERVICE --since "$(date -u -d '2 minutes ago' '+%Y-%m-%d %H:%M:%S')" --no-pager 2>&1 | grep -viE 'getUpdates success' | tail -15
echo

echo "========== 结果 =========="
echo "status=$([ "$PROOF_RC" -eq 0 ] && echo DEPLOY_OK || echo NEEDS_REVIEW)"
echo "service=$(systemctl is-active $SERVICE) mainPid=$NEW_PID"
for f in $FILES; do echo "$f sha256=$(sudo -n sha256sum "$ROOT/$f" | awk '{print $1}')"; done
echo "backup=$BACKUP"
echo "rollback=sudo cp -p $BACKUP/db.mjs $BACKUP/bot.mjs $ROOT/src/ && sudo systemctl restart $SERVICE"
echo "=========================="
