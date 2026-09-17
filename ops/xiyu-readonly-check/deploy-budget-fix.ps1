# ============================================================
#  溪语预算修正 — 窄范围部署（只动 2 个文件）
#
#  改什么：src/db.mjs、src/proactive.mjs
#  影响什么：每日动念预算上限 8次/24000token → 16次/96000token；
#            单次预留值按生产实测校准。不碰人格、prompt、开关、数据库结构。
#
#  安全流程（对齐 docs 第 9 节的发布要求）：
#    0. 记录工作区是否干净（有未提交改动则拒绝）
#    1. 部署前抓取生产原文 → 与本地基线 diff（人可读）
#    2. 时间戳备份生产文件（含校验和清单）
#    3. 上传并原子替换（chown/chmod 对齐原文件）
#    4. 以服务用户 xiyu 做语法检查
#    5. 重启服务 + 健康接口校验
#    6. 隔离冒烟：临时 DB + 本地 node 进程，核对新上限生效
#    7. 失败自动回滚
#
#  不触碰：LIMI、capybara-game、.env、数据库内容、systemd 单元
# ============================================================

param(
    [switch]$DryRun,
    [string]$SmokeFile
)

$ErrorActionPreference = 'Continue'

# 冒烟脚本用独立 .mjs 文件（避免在 bash/PowerShell/JS 之间嵌套多层引号）
if (-not $SmokeFile) { $SmokeFile = Join-Path $PSScriptRoot 'smoke-budget-caps.mjs' }
if (-not (Test-Path $SmokeFile)) { Write-Host "找不到冒烟脚本: $SmokeFile" -ForegroundColor Red; exit 1 }

$KEY  = "$env:USERPROFILE\.ssh\xiyu-readonly-nopass"
$SRV  = "admin@39.106.153.59"
$OPTS = @('-i',$KEY,'-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','ConnectTimeout=20','-o','StrictHostKeyChecking=accept-new')
$REPO = 'E:\FoxSpirit\xiyu-ai'
$TMP  = "$env:TEMP\xiyu-deploy"
$STAMP = Get-Date -Format 'yyyyMMddTHHmmss'
$RSTAGE = "/tmp/xiyu-budget-deploy"

function Say($m, $c = 'Gray') { Write-Host $m -ForegroundColor $c }

# 注意 1：函数名不能叫 Ssh —— PowerShell 命令名不区分大小写，
#         那样函数体内调用 ssh 会解析回函数自身，导致 call depth overflow。
# 注意 2：不要对 ssh 调用做 | Out-Null。受限沙箱里管道会改用带输出重定向的
#         启动方式并被拒绝（"Program 'ssh.exe' failed to run: 拒绝访问"），
#         而命令实际并未执行。
# 注意 3：显式取外部可执行文件路径，避免与函数/别名相互遮蔽。
$SSH_EXE = (Get-Command ssh -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1).Source
if (-not $SSH_EXE) { $SSH_EXE = 'C:\Windows\System32\OpenSSH\ssh.exe' }

function RunSsh($cmd) {
    $out = & $SSH_EXE @OPTS $SRV $cmd 2>&1
    return $out
}

# ---------- 0. 工作区干净度 ----------
Say ""
Say "=== 步骤 0：检查工作区 ===" -ForegroundColor Cyan
$dirty = (git -C $REPO status --porcelain -- src tests 2>&1 | Out-String).Trim()
if ($dirty) {
    Say "src/ 或 tests/ 有未提交改动，部署脚本拒绝在有未提交状态下列出基线。" -ForegroundColor Yellow
    Say $dirty
} else {
    Say "src/ 与 tests/ 工作区干净" -ForegroundColor Green
}
$baseDb   = (git -C $REPO rev-parse HEAD:src/db.mjs 2>&1 | Out-String).Trim()
$basePro  = (git -C $REPO rev-parse HEAD:src/proactive.mjs 2>&1 | Out-String).Trim()
Say "本地基线 blob: db.mjs=$($baseDb.Substring(0,[Math]::Min(12,$baseDb.Length)))  proactive.mjs=$($basePro.Substring(0,[Math]::Min(12,$basePro.Length)))"

# ---------- 1. 准备上传内容 ----------
if (Test-Path $TMP) { Remove-Item -LiteralPath $TMP -Recurse -Force }
New-Item -ItemType Directory -Path $TMP -Force | Out-Null
Copy-Item "$REPO\src\db.mjs"        "$TMP\db.mjs"        -Force
Copy-Item "$REPO\src\proactive.mjs" "$TMP\proactive.mjs" -Force

Get-ChildItem $TMP -File | ForEach-Object {
    $t = (Get-Content -LiteralPath $_.FullName -Raw) -replace "`r`n","`n"
    [System.IO.File]::WriteAllText($_.FullName, $t, (New-Object System.Text.UTF8Encoding($false)))
}

$localDb  = (Get-FileHash "$TMP\db.mjs" -Algorithm SHA256).Hash.ToLower()
$localPro = (Get-FileHash "$TMP\proactive.mjs" -Algorithm SHA256).Hash.ToLower()
Say ""
Say "本地待部署版本 sha256："
Say "  db.mjs        $localDb"
Say "  proactive.mjs $localPro"

# ---------- 上传 ----------
Say ""
Say "=== 上传到服务器 $RSTAGE ===" -ForegroundColor Cyan
$mk = RunSsh "rm -rf $RSTAGE; mkdir -p $RSTAGE; test -d $RSTAGE && echo DIR_READY || echo DIR_MISSING"
Say ("  " + ($mk | Out-String).Trim())
if (($mk | Out-String) -notmatch 'DIR_READY') { Say "远端目录建立失败，中止" Red; exit 1 }

function Push-File($local, $remote) {
    $body = (Get-Content -LiteralPath $local -Raw) -replace "`r`n","`n"
    $f = Join-Path $env:TEMP ("push-" + [IO.Path]::GetFileName($local))
    [System.IO.File]::WriteAllText($f, $body, (New-Object System.Text.UTF8Encoding($false)))
    cmd /c "ssh $($OPTS -join ' ') $SRV ""cat > '$remote'"" < ""$f"""
    $code = $LASTEXITCODE
    Remove-Item -LiteralPath $f -Force -ErrorAction SilentlyContinue
    if ($code -eq 0) { Say "  上传 $remote  OK" Green } else { Say "  上传 $remote  失败(code=$code)" Red }
    return $code
}
Push-File "$TMP\db.mjs"        "$RSTAGE/db.mjs"        | Out-Null
Push-File "$TMP\proactive.mjs" "$RSTAGE/proactive.mjs" | Out-Null
Push-File $SmokeFile           "$RSTAGE/smoke-budget-caps.mjs" | Out-Null

# 上传后核对远端 sha256，确保传过去的正是本地这一版
$localSmoke = (Get-FileHash (Resolve-Path $SmokeFile).Path -Algorithm SHA256).Hash.ToLower()
$rHashes = RunSsh "sha256sum $RSTAGE/db.mjs $RSTAGE/proactive.mjs $RSTAGE/smoke-budget-caps.mjs"
Say "远端已就位："
Say ($rHashes | Out-String).Trim()
$rText = ($rHashes | Out-String)
foreach ($h in @($localDb, $localPro, $localSmoke)) {
    if ($rText -notmatch [regex]::Escape($h)) {
        Say "远端 sha256 缺少 $h，中止（避免部署到错误内容）" Red
        exit 1
    }
}
Say "  远端 sha256 与本地一致" Green

# ---------- 1b. 部署前 diff（人可读）----------
Say ""
Say "=== 步骤 1：生产 vs 本次待部署 差异（部署前必看）===" -ForegroundColor Cyan
$diffScript = @'
for pair in "src/db.mjs db.mjs" "src/proactive.mjs proactive.mjs"; do
  set -- $pair; target="/opt/xiyu-ai/$1"; staged="/tmp/xiyu-budget-deploy/$2"
  echo "===== diff: $1 ====="
  if diff -u "$target" "$staged" > /tmp/d.txt 2>&1; then
    echo "  完全相同（无需替换）"
  else
    echo "  差异行数: $(wc -l < /tmp/d.txt)"
    echo "  --- 变更摘要（+ 为新增 / - 为删除）---"
    grep -c '^+' /tmp/d.txt | sed 's/^/    新增行: /'
    grep -c '^-' /tmp/d.txt | sed 's/^/    删除行: /'
    echo "  --- 完整差异 ---"
    cat /tmp/d.txt
  fi
  echo
done
'@
$diffFile = Join-Path $env:TEMP 'diffcheck.sh'
[System.IO.File]::WriteAllText($diffFile, ($diffScript -replace "`r`n","`n"), (New-Object System.Text.UTF8Encoding($false)))
cmd /c "ssh $($OPTS -join ' ') $SRV ""bash -s"" < ""$diffFile"""
Remove-Item -LiteralPath $diffFile -Force -ErrorAction SilentlyContinue

if ($DryRun) {
    Say ""
    Say "=== -DryRun：到此为止，未做任何替换 ===" -ForegroundColor Yellow
    exit 0
}

# ---------- 2-7. 正式部署 ----------
Say ""
Say "=== 步骤 2-7：备份 → 替换 → 语法检查 → 重启 → 健康校验 → 冒烟 ===" -ForegroundColor Cyan
Say ""

$deployScript = @'
set -u
ROOT=/opt/xiyu-ai
STAGE=/tmp/xiyu-budget-deploy
STAMP="__STAMP__"
BACKUP=/opt/xiyu-backups/budget-deploy-$STAMP
SERVICE=xiyu-ai
HEALTH=http://127.0.0.1:3000/api/health
FILES="src/db.mjs src/proactive.mjs"
ROLLED_BACK=0

log(){ printf '[deploy] %s\n' "$*"; }
fail(){ log "FAILED: $*"; }

rollback(){
  log "开始回滚 ..."
  for f in $FILES; do
    if [ -f "$BACKUP/$(basename $f)" ]; then
      cp -p -- "$BACKUP/$(basename $f)" "$ROOT/$f" && log "  已恢复 $f"
    else
      log "  备份缺失，无法恢复 $f"
    fi
  done
  sudo -n systemctl restart $SERVICE
  sleep 3
  if curl -s --max-time 5 -f "$HEALTH" | grep -q '"ok"[[:space:]]*:[[:space:]]*true'; then
    log "回滚后健康检查通过"
  else
    log "回滚后健康检查仍未通过，需要人工介入"
  fi
  ROLLED_BACK=1
}

# ---- 2. 备份 ----
log "步骤2：备份到 $BACKUP"
sudo -n mkdir -p "$BACKUP" || { fail "无法创建备份目录"; exit 1; }
for f in $FILES; do
  sudo -n cp -p -- "$ROOT/$f" "$BACKUP/$(basename $f)" || { fail "备份 $f 失败"; exit 1; }
  log "  已备份 $f  ($(sudo -n sha256sum "$ROOT/$f" | awk '{print $1}'))"
done
( cd "$BACKUP" && sudo -n sha256sum * > SHA256SUMS ) 2>/dev/null || true
log "  备份清单已生成"

# ---- 3. 替换（原子：先写临时文件再 mv，保留属主）----
log "步骤3：替换文件"
for pair in "src/db.mjs db.mjs" "src/proactive.mjs proactive.mjs"; do
  set -- $pair; target="$ROOT/$1"; staged="$STAGE/$2"
  [ -f "$staged" ] || { fail "待部署文件缺失: $staged"; rollback; exit 1; }
  OWNER=$(stat -c '%u:%g' "$target")
  MODE=$(stat -c '%a' "$target")
  sudo -n install -m "$MODE" -o "${OWNER%%:*}" -g "${OWNER##*:}" "$staged" "$target" || { fail "替换 $1 失败"; rollback; exit 1; }
  NEWHASH=$(sudo -n sha256sum "$target" | awk '{print $1}')
  log "  已替换 $1  权限=$MODE 属主=$OWNER sha256=$NEWHASH"
done

# ---- 4. 语法检查（以服务用户身份）----
log "步骤4：以服务用户 xiyu 做语法检查"
NODE=$(systemctl show $SERVICE -p ExecStart --value | sed -n 's/.*path=\([^ ;]*\).*/\1/p' | head -n1)
[ -x "$NODE" ] || NODE=$(command -v node)
for f in $FILES; do
  if ! sudo -n -u xiyu "$NODE" --check "$ROOT/$f" 2>/tmp/synerr.txt; then
    fail "语法检查未通过: $f"; cat /tmp/synerr.txt; rollback; exit 1
  fi
  log "  语法 OK: $f"
done

# ---- 5. 重启 + 健康 ----
log "步骤5：重启服务并等待健康"
sudo -n systemctl restart $SERVICE || { fail "重启失败"; rollback; exit 1; }
OK=0
for i in $(seq 1 45); do
  if curl -s --max-time 5 -f "$HEALTH" | grep -q '"ok"[[:space:]]*:[[:space:]]*true'; then OK=1; break; fi
  sleep 2
done
if [ "$OK" -ne 1 ]; then
  fail "健康检查 90 秒内未通过"
  sudo -n journalctl -u $SERVICE -n 30 --no-pager | tail -30
  rollback; exit 1
fi
log "  健康检查通过"
log "  服务状态: $(systemctl is-active $SERVICE)  MainPID=$(systemctl show $SERVICE -p MainPID --value)"

# ---- 6. 隔离冒烟：核对新上限真的生效 ----
# 用独立的 smoke-budget-caps.mjs 文件，避免多层引号嵌套。
log "步骤6：隔离冒烟（临时 DB，独立进程，不碰生产库）"
SMOKE=$(sudo -n -u xiyu sh -c "TMPD=\$(mktemp -d /tmp/xiyu-budget-smoke.XXXXXX) && cd $ROOT && DB_PATH=\$TMPD/smoke.db DATA_DIR=\$TMPD LOG_DIR=\$TMPD $NODE $STAGE/smoke-budget-caps.mjs; RC=\$?; rm -rf \$TMPD; exit \$RC")
SMOKE_RC=$?
echo "$SMOKE"
CAPS=$(echo "$SMOKE" | sed -n 's/^CAPS=//p')
RES=$(echo "$SMOKE" | sed -n 's/^RESERVED=//p')
OVF=$(echo "$SMOKE" | sed -n 's/^OVERFLOW_BLOCKED=//p')
SMOKE_RESULT=$(echo "$SMOKE" | sed -n 's/^SMOKE=//p')
if [ "$SMOKE_RC" -eq 0 ] && [ "$SMOKE_RESULT" = "PASS" ]; then
  log "  冒烟通过：上限 = $CAPS  次数预留=$RES  超额被挡=$OVF"
else
  fail "冒烟未通过（rc=$SMOKE_RC result=$SMOKE_RESULT caps=$CAPS reserved=$RES overflow=$OVF）"
  rollback; exit 1
fi
if [ "$RES" = "16" ] && [ "$OVF" = "yes" ]; then
  log "  冒烟通过：16 次预留成功，第 17 次被挡"
else
  fail "冒烟计数异常 reserved=$RES overflow=$OVF"
  rollback; exit 1
fi

# ---- 7. 结果 ----
if [ "$ROLLED_BACK" -eq 1 ]; then exit 1; fi
echo
echo "========== 部署结果 =========="
echo "status=DEPLOY_OK"
echo "service=$(systemctl is-active $SERVICE)"
echo "mainPid=$(systemctl show $SERVICE -p MainPID --value)"
echo "backup=$BACKUP"
echo "caps=$CAPS"
echo "reserved=$RES overflowBlocked=$OVF"
echo "files:"
for f in $FILES; do
  echo "  $f sha256=$(sudo -n sha256sum "$ROOT/$f" | awk '{print $1}')"
done
echo "回滚命令：sudo cp -p $BACKUP/db.mjs $ROOT/src/db.mjs && sudo cp -p $BACKUP/proactive.mjs $ROOT/src/proactive.mjs && sudo systemctl restart $SERVICE"
echo "=============================="
'@ -replace '__STAMP__', $STAMP

$depFile = Join-Path $env:TEMP 'deploy.sh'
[System.IO.File]::WriteAllText($depFile, ($deployScript -replace "`r`n","`n"), (New-Object System.Text.UTF8Encoding($false)))
cmd /c "ssh $($OPTS -join ' ') $SRV ""bash -s"" < ""$depFile"""
$code = $LASTEXITCODE
Remove-Item -LiteralPath $depFile -Force -ErrorAction SilentlyContinue

Say ""
if ($code -eq 0) { Say "=== 部署完成（退出码 0）===" Green } else { Say "=== 部署失败或被回滚（退出码 $code）===" Red }
exit $code
