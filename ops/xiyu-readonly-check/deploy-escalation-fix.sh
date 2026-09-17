#!/bin/bash
# ============================================================
#  部署 escalation.mjs 误判修复
#
#  改什么：PUSHY_RE 移除 `看看你` / `想看你`
#  为什么：这两句是正常亲昵话，却被判为「施压」。生产实测连续 4 条后升到 L3，
#          建成 pressure_spam severity 3 事件，把角色推入 hurt 并压制主动联系。
#  不放松：真的反复索要（发张照片/再发一张/给我看）仍会升级，已验证。
#
#  回滚：sudo cp -p <backup>/escalation.mjs /opt/xiyu-ai/src/escalation.mjs
#        && sudo systemctl restart xiyu-ai
# ============================================================
set -u
ROOT=/opt/xiyu-ai
SERVICE=xiyu-ai
HEALTH=http://127.0.0.1:3000/api/health
STAGE=/tmp/xiyu-esc-deploy
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP=/opt/xiyu-backups/escalation-fix-$STAMP

log(){ printf '[esc-fix] %s\n' "$*"; }
fail(){ log "FAILED: $*"; }

echo "############ 部署 escalation 误判修复 ############"
date
echo

log "步骤0：检查待部署文件"
[ -f "$STAGE/escalation.mjs" ] || { fail "缺少 $STAGE/escalation.mjs"; exit 1; }
echo "-- 相对生产的关键差异（正则行）--"
diff -u "$ROOT/src/escalation.mjs" "$STAGE/escalation.mjs" | grep -E '^[-+].*(PUSHY_RE|施压词表|修正)' | head -20
echo "-- 确认新表中已无 看看你/想看你 --"
if grep -E '^const PUSHY_RE' "$STAGE/escalation.mjs" | grep -qE '看看你|想看你'; then
  fail "新表里仍然有 看看你/想看你，停止部署"
  exit 1
fi
log "  新表已不含 看看你/想看你"
echo

log "步骤1：备份"
sudo -n mkdir -p "$BACKUP" || { fail "建备份目录失败"; exit 1; }
sudo -n cp -p "$ROOT/src/escalation.mjs" "$BACKUP/escalation.mjs" || { fail "备份失败"; exit 1; }
log "  已备份 sha256=$(sudo -n sha256sum "$ROOT/src/escalation.mjs" | awk '{print $1}')"
echo

log "步骤2：替换"
OWNER=$(stat -c '%u:%g' "$ROOT/src/escalation.mjs")
MODE=$(stat -c '%a'  "$ROOT/src/escalation.mjs")
sudo -n install -m "$MODE" -o "${OWNER%%:*}" -g "${OWNER##*:}" "$STAGE/escalation.mjs" "$ROOT/src/escalation.mjs" || { fail "替换失败"; exit 1; }
NEWHASH=$(sudo -n sha256sum "$ROOT/src/escalation.mjs" | awk '{print $1}')
log "  已替换 权限=$MODE 属主=$OWNER sha256=$NEWHASH"
NODE=$(systemctl show $SERVICE -p ExecStart --value | sed -n 's/.*path=\([^ ;]*\).*/\1/p' | head -n1)
[ -x "$NODE" ] || NODE=$(command -v node)
sudo -n -u xiyu "$NODE" --check "$ROOT/src/escalation.mjs" && log "  语法 OK" || { fail "语法检查失败"; sudo -n cp -p "$BACKUP/escalation.mjs" "$ROOT/src/escalation.mjs"; exit 1; }
echo

log "步骤3：重启并等待健康"
OLD_PID=$(systemctl show $SERVICE -p MainPID --value)
sudo -n systemctl restart $SERVICE || { fail "重启失败"; exit 1; }
OK=0
for i in $(seq 1 45); do
  if curl -s --max-time 5 -f "$HEALTH" | grep -q '"ok"[[:space:]]*:[[:space:]]*true'; then OK=1; break; fi
  sleep 2
done
if [ "$OK" -ne 1 ]; then
  fail "健康检查未通过，回滚"
  sudo -n cp -p "$BACKUP/escalation.mjs" "$ROOT/src/escalation.mjs"
  sudo -n systemctl restart $SERVICE
  sudo -n journalctl -u $SERVICE -n 30 --no-pager | tail -30
  exit 1
fi
NEW_PID=$(systemctl show $SERVICE -p MainPID --value)
log "  健康通过  旧PID=$OLD_PID 新PID=$NEW_PID  状态=$(systemctl is-active $SERVICE)"
echo

log "步骤4：用生产代码实测修复是否生效"
cat > /tmp/xiyu-esc-deploy/proof.mjs <<'EOF'
import { escalationLevel } from '/opt/xiyu-ai/src/escalation.mjs';
const incident = [
  { direction: 'in', content: '想看，主要是想看你那件粉色的情趣内衣' },
  { direction: 'in', content: '那你挑吧，我想看看你自己私人的东西' },
  { direction: 'out', content: '刚不都说了嘛，坐床上呢' },
  { direction: 'in', content: '现在可以发啦' },
  { direction: 'in', content: '我现在单纯就是想看看你' },
];
const a = escalationLevel('我现在单纯就是想看看你', []);
const b = escalationLevel('我看看你的洗衣机', incident);
console.log('亲昵话(单条)      pushy =', a.pushy, 'level =', a.level);
console.log('事故序列(连发)    level =', b.level, 'pushy =', b.pushy);
const real = [
  { direction: 'in', content: '发张照片' },
  { direction: 'out', content: '别急，等一下' },
  { direction: 'in', content: '再发一张' },
  { direction: 'out', content: '别催啦' },
  { direction: 'in', content: '拍个照给我看' },
];
const c = escalationLevel('再拍一张', real);
console.log('真的反复索图      level =', c.level, '(应 >= 2)');
const ok = a.pushy === false && b.level < 2 && c.level >= 2;
console.log('FIX_EFFECTIVE=' + (ok ? 'YES' : 'NO'));
process.exit(ok ? 0 : 1);
EOF
sudo -n -u xiyu env DB_PATH=$ROOT/data/bot.db "$NODE" /tmp/xiyu-esc-deploy/proof.mjs
PROOF_RC=$?
echo "  证明脚本退出码=$PROOF_RC"
echo

echo "========== 结果 =========="
echo "status=$([ "$PROOF_RC" -eq 0 ] && echo DEPLOY_OK || echo DEPLOY_NEEDS_REVIEW)"
echo "service=$(systemctl is-active $SERVICE)  mainPid=$NEW_PID"
echo "escalation.mjs sha256=$NEWHASH"
echo "backup=$BACKUP"
echo "rollback=sudo cp -p $BACKUP/escalation.mjs $ROOT/src/escalation.mjs && sudo systemctl restart $SERVICE"
echo "=========================="
