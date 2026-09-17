#!/bin/bash
# ============================================================
#  部署照片链路改造（自拍九块结构 + 身份去形状词 + 服装护栏移除）
#
#  改什么：
#    src/visual_identity.mjs   删掉身份模板里的形状词
#    src/photo_sender.mjs      参考图锚定句提到最前面
#    src/photo_planner.mjs     3 候选 → 1 份九块方案；加表情/动作/环境块；删服装季节护栏
#    scripts/photo_planner_prompt_smoke.mjs  断言改为九块结构
#    scripts/photo_visual_direction_smoke.mjs 重写为测新函数
#  数据：data/companion_visuals/1/identity.json 去掉缓存的形状词（单独备份）
#
#  回滚：见脚本末尾输出的 rollback 行
# ============================================================
set -u
ROOT=/opt/xiyu-ai
SERVICE=xiyu-ai
HEALTH=http://127.0.0.1:3000/api/health
STAGE=/tmp/xiyu-photo-deploy
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP=/opt/xiyu-backups/photo-9block-$STAMP
FILES="src/visual_identity.mjs src/photo_sender.mjs src/photo_planner.mjs scripts/photo_planner_prompt_smoke.mjs scripts/photo_visual_direction_smoke.mjs"

log(){ printf '[photo-deploy] %s\n' "$*"; }
fail(){ log "FAILED: $*"; }

rollback(){
  log "回滚中 ..."
  for f in $FILES; do
    b="$BACKUP/$(basename $f)"
    [ -f "$b" ] && sudo -n cp -p "$b" "$ROOT/$f" && log "  已恢复 $f"
  done
  if [ -f "$BACKUP/identity.json" ]; then
    sudo -n cp -p "$BACKUP/identity.json" "$ROOT/data/companion_visuals/1/identity.json" && log "  已恢复 identity.json"
  fi
  sudo -n systemctl restart $SERVICE
  sleep 5
  curl -s --max-time 5 -f "$HEALTH" | grep -q '"ok"[[:space:]]*:[[:space:]]*true' \
    && log "  回滚后健康通过" || log "  回滚后健康未通过，需人工介入"
}

echo "############ 部署照片链路改造 ############"
date
echo

log "步骤0：检查待部署文件"
for f in $FILES; do
  [ -f "$STAGE/$(basename $f)" ] || { fail "缺少 $STAGE/$(basename $f)"; exit 1; }
done
[ -f "$STAGE/sync-identity-spec.mjs" ] || { fail "缺少 sync-identity-spec.mjs"; exit 1; }
echo "-- 关键改动自检 --"
echo -n "  visual_identity 残留形状词: "
grep -cE "round full cheeks|doe eyes|delicate chin|slim petite" "$STAGE/visual_identity.mjs" || true
echo -n "  photo_sender 锚定句在最前: "
grep -c "definitive identity anchor" "$STAGE/photo_sender.mjs"
echo -n "  photo_planner 新函数: "
grep -c "export function normalizeVisualPlan\|export function visualPlanPrompt" "$STAGE/photo_planner.mjs"
echo -n "  photo_planner 残留候选逻辑: "
grep -c "selectVisualCandidate\|visualCandidates" "$STAGE/photo_planner.mjs" || true
echo -n "  服装护栏替换句: "
grep -c "lightweight breathable casual clothes suited to the current place and activity" "$STAGE/photo_planner.mjs" || true
echo

log "步骤1：备份到 $BACKUP"
sudo -n mkdir -p "$BACKUP" || { fail "建备份目录失败"; exit 1; }
for f in $FILES; do
  sudo -n cp -p "$ROOT/$f" "$BACKUP/$(basename $f)" || { fail "备份 $f 失败"; exit 1; }
  log "  已备份 $f"
done
sudo -n cp -p "$ROOT/data/companion_visuals/1/identity.json" "$BACKUP/identity.json" && log "  已备份 identity.json"
echo

log "步骤2：替换源码并做语法检查"
NODE=$(systemctl show $SERVICE -p ExecStart --value | sed -n 's/.*path=\([^ ;]*\).*/\1/p' | head -n1)
[ -x "$NODE" ] || NODE=$(command -v node)
for f in $FILES; do
  target="$ROOT/$f"; staged="$STAGE/$(basename $f)"
  OWNER=$(stat -c '%u:%g' "$target"); MODE=$(stat -c '%a' "$target")
  sudo -n install -m "$MODE" -o "${OWNER%%:*}" -g "${OWNER##*:}" "$staged" "$target" || { fail "替换 $f 失败"; rollback; exit 1; }
  sudo -n -u xiyu "$NODE" --check "$target" || { fail "$f 语法失败"; rollback; exit 1; }
  log "  $f OK sha256=$(sudo -n sha256sum "$target" | awk '{print $1}' | cut -c1-12)"
done
echo

log "步骤3：同步 identity.json（去掉缓存的形状词）"
sudo -n -u xiyu env DB_PATH="$ROOT/data/bot.db" "$NODE" "$STAGE/sync-identity-spec.mjs"
SYNC_RC=$?
if [ "$SYNC_RC" -ne 0 ]; then
  fail "identity.json 同步失败 (rc=$SYNC_RC)"
  rollback; exit 1
fi
echo

log "步骤4：重启并等待健康"
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

log "步骤5：用生产代码实测最终提示词"
cat > "$STAGE/proof.mjs" <<'EOF'
import { buildFinalImagePrompt } from '/opt/xiyu-ai/src/photo_sender.mjs';
EOF
# 直接调用 buildFinalImagePrompt 需要很多入参，改用更稳的方式：跑路由 smoke 的模式
sudo -n -u xiyu env DB_PATH="$ROOT/data/bot.db" "$NODE" --input-type=module -e "
const planner = await import('$ROOT/src/photo_planner.mjs');
const plan = planner.normalizeVisualPlan({
  sceneMoment: 'She is sitting on her bed just after finishing laundry, one knee drawn up, glancing at the lens mid-motion.',
  framing: 'Close off-axis front-camera selfie, face in the upper half, bed and room sharing the frame.',
  action: 'One hand still holding a folded shirt, the other steadying the phone.',
  expression: 'Soft half-smile, a little tired but warm.',
  wardrobe: 'Light cream knit cardigan over a long-sleeve tee.',
  environment: 'Bedroom with folded clothes on the duvet, a bedside lamp on, a charging cable on the floor.',
  compositionFamily: 'close_off_center_selfie',
  timelineRelation: 'current',
  variationTags: ['bedroom','laundry','off-axis'],
}, { captureIntent: 'lived', shotMode: 'SELFIE' });
const prompt = planner.visualPlanPrompt(plan, { captureIntent: 'lived', shotMode: 'SELFIE' });
console.log('ASSEMBLED_LEN=' + prompt.length);
console.log('HAS_EXPRESSION=' + (prompt.includes('half-smile') ? 'yes' : 'no'));
console.log('HAS_ACTION=' + (prompt.includes('folded shirt') ? 'yes' : 'no'));
console.log('HAS_WARDROBE_KNIT=' + (prompt.includes('knit cardigan') ? 'yes' : 'no'));
console.log('HAS_ENV_ANCHORS=' + (prompt.includes('charging cable') ? 'yes' : 'no'));
console.log('WARDROBE_NOT_GENERIC=' + (prompt.includes('lightweight breathable casual clothes suited to the current place and activity') ? 'no' : 'yes'));
" 2>&1 | tail -10
echo

echo "========== 结果 =========="
echo "status=DEPLOY_OK"
echo "service=$(systemctl is-active $SERVICE) mainPid=$NEW_PID"
for f in $FILES; do echo "  $f sha256=$(sudo -n sha256sum "$ROOT/$f" | awk '{print $1}' | cut -c1-12)"; done
echo "backup=$BACKUP"
echo "rollback=sudo cp -p $BACKUP/*.mjs $ROOT/src/ 2>/dev/null; sudo cp -p $BACKUP/visual_identity.mjs $BACKUP/photo_sender.mjs $BACKUP/photo_planner.mjs $ROOT/src/; sudo cp -p $BACKUP/photo_planner_prompt_smoke.mjs $BACKUP/photo_visual_direction_smoke.mjs $ROOT/scripts/; sudo cp -p $BACKUP/identity.json $ROOT/data/companion_visuals/1/identity.json; sudo systemctl restart $SERVICE"
echo "=========================="
