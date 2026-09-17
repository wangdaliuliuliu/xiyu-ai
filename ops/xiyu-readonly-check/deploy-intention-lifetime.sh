#!/bin/bash
# ============================================================
#  部署「动念保质期与收尾」（2026-09-18）
#
#  修什么：一条动念可以无限期停在 ready 并反复重试，即使它问的事
#          早就过期、连它派生的动作都过期两天了。
#
#  三层机制：
#    ① 保质期  监控类 24h / 一次性事实 48h / 方法论 14 天
#              每日仪式（早安/晚安/低负担入口）**不适用**（防误杀）
#    ② 已消解  来源连续两次确认已消解 → completed（防一次查询失败误杀）
#    ③ 反复失败 同指纹连续被出站门拦 ≥3 次 → suspended
#
#  改动文件：
#    src/initiative.mjs   新增 classifyIntentionLifetime / intentionShelfDeadline /
#                         isIntentionExpired / judgeIntentionRetirement（纯函数）
#    src/db.mjs           新增 retireAgencyIntention（同一事务收尾动念 + 作废其未完成动作）
#    src/proactive.mjs    在选动念入口接入收尾闸（retireExpiredIntentions）
#  新增测试：
#    tests/agency/intention_lifetime.test.mjs（60 条）
#    tests/agency/state_budget.test.mjs     （+1 条收尾事务断言，共 8 条）
#
#  回滚：见末尾
# ============================================================
set -u
ROOT=/opt/xiyu-ai
SERVICE=xiyu-ai
HEALTH=http://127.0.0.1:3000/api/health
STAGE=/tmp/xiyu-life-deploy
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP=/opt/xiyu-backups/intention-lifetime-$STAMP
FILES="src/initiative.mjs src/db.mjs src/proactive.mjs tests/agency/intention_lifetime.test.mjs tests/agency/state_budget.test.mjs"

log(){ printf '[lifetime] %s\n' "$*"; }
fail(){ log "FAILED: $*"; }

rollback(){
  log "回滚中 ..."
  for f in $FILES; do
    b="$BACKUP/$(basename $f)"
    if [ -f "$b" ]; then sudo -n cp -p "$b" "$ROOT/$f" && log "  已恢复 $f";
    else sudo -n rm -f "$ROOT/$f" && log "  已删除新增文件 $f"; fi
  done
  sudo -n systemctl restart $SERVICE
  sleep 5
  curl -s --max-time 5 -f "$HEALTH" | grep -q '"ok"[[:space:]]*:[[:space:]]*true' \
    && log "  回滚后健康通过" || log "  回滚后健康未通过，需人工介入"
}

echo "############ 部署动念保质期与收尾 ############"
date
echo

log "步骤0：检查待部署文件与关键改动"
for f in $FILES; do [ -f "$STAGE/$(basename $f)" ] || { fail "缺少 $f"; exit 1; }; done
echo -n "  initiative 保质期常量: "; grep -c 'INTENTION_SHELF_LIFE_HOURS' "$STAGE/initiative.mjs"
echo -n "  每日仪式豁免(防误杀):  "; grep -c 'RECURRING_RITUAL' "$STAGE/initiative.mjs"
echo -n "  收尾判定函数:          "; grep -c 'export function judgeIntentionRetirement' "$STAGE/initiative.mjs"
echo -n "  db 收尾事务:           "; grep -c 'export function retireAgencyIntention' "$STAGE/db.mjs"
echo -n "  proactive 接入收尾闸:  "; grep -c 'retireExpiredIntentions(owner, fetchedIntentions)' "$STAGE/proactive.mjs"
echo

log "步骤1：备份"
sudo -n mkdir -p "$BACKUP" || { fail "建备份目录失败"; exit 1; }
for f in $FILES; do
  if sudo -n test -f "$ROOT/$f"; then sudo -n cp -p "$ROOT/$f" "$BACKUP/$(basename $f)" && log "  已备份 $f";
  else log "  $f 不存在（新增，回滚时删除）"; fi
done
echo

log "步骤2：替换并语法检查"
NODE=$(systemctl show $SERVICE -p ExecStart --value | sed -n 's/.*path=\([^ ;]*\).*/\1/p' | head -n1)
[ -x "$NODE" ] || NODE=$(command -v node)
for pair in "src/initiative.mjs initiative.mjs" "src/db.mjs db.mjs" "src/proactive.mjs proactive.mjs" "tests/agency/intention_lifetime.test.mjs intention_lifetime.test.mjs" "tests/agency/state_budget.test.mjs state_budget.test.mjs"; do
  set -- $pair; target="$ROOT/$1"; staged="$STAGE/$2"
  if [ -f "$target" ]; then OWNER=$(stat -c '%u:%g' "$target"); MODE=$(stat -c '%a' "$target"); else OWNER="0:0"; MODE="644"; fi
  sudo -n install -m "$MODE" -o "${OWNER%%:*}" -g "${OWNER##*:}" "$staged" "$target" || { fail "替换 $1 失败"; rollback; exit 1; }
  sudo -n -u xiyu "$NODE" --check "$target" || { fail "$1 语法失败（很可能是中文编码被破坏）"; rollback; exit 1; }
  log "  $1 OK sha256=$(sudo -n sha256sum "$target" | awk '{print $1}' | cut -c1-12)"
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

log "步骤4：跑测试（生产环境）"
sudo -n -u xiyu "$NODE" --test "$ROOT/tests/agency/intention_lifetime.test.mjs" 2>&1 | grep -E 'intention_lifetime:'
sudo -n -u xiyu "$NODE" --test "$ROOT/tests/agency/state_budget.test.mjs" 2>&1 | grep -E '^# (tests|pass|fail)'

echo
log "步骤5：用真实积压动念验证规则（只读判定）"
cat > "$STAGE/verify-rule.mjs" <<'EOF'
const db = await import('/opt/xiyu-ai/src/db.mjs');
const lib = await import('/opt/xiyu-ai/src/initiative.mjs');
const dbx = db.getDb();
const rows = dbx.prepare(`SELECT id, state, desired_change, created_at FROM agency_intentions WHERE state NOT IN ('completed','abandoned','expired') ORDER BY updated_at DESC`).all();
const now = Date.now();
console.log('当前未完成动念经规则判定：');
let retireCount = 0;
for (const it of rows) {
  const c = lib.classifyIntentionLifetime(it);
  const v = lib.judgeIntentionRetirement(it, { nowMs: now });
  if (v.retire) retireCount++;
  console.log(`  ${String(it.id).slice(0,24).padEnd(26)} ${String(it.state).padEnd(13)} ${c.type.padEnd(19)} → ${v.retire ? v.retire + ' (' + v.reason + ')' : '保留'}`);
  console.log(`      ${String(it.desired_change).slice(0,56)}`);
}
console.log(`\n命中收尾: ${retireCount} / ${rows.length}`);
dbx.close();
EOF
sudo -n -u xiyu env DB_PATH="$ROOT/data/bot.db" "$NODE" "$STAGE/verify-rule.mjs" 2>&1 | tail -30
echo

log "步骤6：启动日志（确认无异常）"
sudo -n journalctl -u $SERVICE --since "$(date -u -d '2 minutes ago' '+%Y-%m-%d %H:%M:%S')" --no-pager 2>&1 \
  | grep -viE 'getUpdates success' | tail -8
echo

echo "========== 结果 =========="
echo "status=DEPLOY_OK"
echo "service=$(systemctl is-active $SERVICE) mainPid=$NEW_PID"
for f in $FILES; do echo "  $f sha256=$(sudo -n sha256sum "$ROOT/$f" 2>/dev/null | awk '{print $1}' | cut -c1-12)"; done
echo "backup=$BACKUP"
echo "rollback=sudo cp -p $BACKUP/initiative.mjs $BACKUP/db.mjs $BACKUP/proactive.mjs $ROOT/src/; sudo cp -p $BACKUP/state_budget.test.mjs $ROOT/tests/agency/; sudo rm -f $ROOT/tests/agency/intention_lifetime.test.mjs; sudo systemctl restart $SERVICE"
echo "=========================="
