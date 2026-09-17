# ============================================================
#  溪语预算改动 - 隔离验证执行器
#
#  做什么：
#    1. 把本地改动后的文件传到服务器 /tmp/xiyu-budget-verify/（临时目录）
#    2. 在那里跑 node --test（依赖只读引用生产 node_modules）
#    3. 回传验证结果
#
#  **不修改生产 /opt/xiyu-ai 的任何文件。**
# ============================================================

$ErrorActionPreference = 'Continue'

$KEY    = "$env:USERPROFILE\.ssh\xiyu-readonly-nopass"
$SRV    = "admin@39.106.153.59"
$OPTS   = @('-i',$KEY,'-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','ConnectTimeout=20','-o','StrictHostKeyChecking=accept-new')
$REPO   = 'E:\FoxSpirit\xiyu-ai'
$TMP    = "$env:TEMP\xiyu-verify"
$REMOTE = '/tmp/xiyu-budget-verify'

# ---- 1. 准备本地上传目录 ----
if (Test-Path $TMP) { Remove-Item -LiteralPath $TMP -Recurse -Force }
New-Item -ItemType Directory -Path "$TMP\src","$TMP\tests\agency","$TMP\ops" -Force | Out-Null

# 整个 src 都要传：db.mjs 会 import 同目录的其他模块（provider_costs.mjs 等），
# 只传改动文件会导致 ERR_MODULE_NOT_FOUND，验证跑不起来。
Copy-Item "$REPO\src\*" "$TMP\src\" -Recurse -Force
Copy-Item "$REPO\tests\agency\state_budget.test.mjs" "$TMP\tests\agency\state_budget.test.mjs" -Force
Copy-Item "$REPO\ops\xiyu-readonly-check\verify-budget-change.sh" "$TMP\ops\verify-budget-change.sh" -Force

# 统一 LF 换行（远端 bash 不接受 CRLF）
Get-ChildItem $TMP -Recurse -File | ForEach-Object {
    $t = (Get-Content -LiteralPath $_.FullName -Raw) -replace "`r`n","`n"
    [System.IO.File]::WriteAllText($_.FullName, $t, (New-Object System.Text.UTF8Encoding($false)))
}

Write-Host "待上传文件：" -ForegroundColor Cyan
Get-ChildItem $TMP -Recurse -File | ForEach-Object { Write-Host ("  " + $_.FullName.Replace($TMP,'')) }
Write-Host ""

# ---- 2. 在服务器建立临时目录 ----
Write-Host "在服务器建立临时目录 $REMOTE ..." -ForegroundColor Cyan
& ssh @OPTS $SRV "rm -rf $REMOTE; mkdir -p $REMOTE/src $REMOTE/tests/agency $REMOTE/ops; echo DIR_OK"
if ($LASTEXITCODE -ne 0) { Write-Host "建立目录失败" -ForegroundColor Red; exit 1 }

# ---- 3. 上传（走 stdin，避免管道 EOL 问题）----
function Push-File($local, $remote) {
    $body = (Get-Content -LiteralPath $local -Raw) -replace "`r`n","`n"
    $f = Join-Path $env:TEMP ("push-" + [IO.Path]::GetFileName($local))
    [System.IO.File]::WriteAllText($f, $body, (New-Object System.Text.UTF8Encoding($false)))
    cmd /c "ssh $($OPTS -join ' ') $SRV ""cat > '$remote'"" < ""$f"""
    $code = $LASTEXITCODE
    Remove-Item -LiteralPath $f -Force -ErrorAction SilentlyContinue
    if ($code -eq 0) { Write-Host "  上传成功 $remote" -ForegroundColor Green }
    else { Write-Host "  上传失败 $remote (code=$code)" -ForegroundColor Red }
    return $code
}

Push-File "$TMP\src\db.mjs"                          "$REMOTE/src/db.mjs"                          | Out-Null
Push-File "$TMP\src\proactive.mjs"                   "$REMOTE/src/proactive.mjs"                   | Out-Null
Push-File "$TMP\tests\agency\state_budget.test.mjs"  "$REMOTE/tests/agency/state_budget.test.mjs"  | Out-Null
Push-File "$TMP\ops\verify-budget-change.sh"         "$REMOTE/ops/verify-budget-change.sh"         | Out-Null

# db.mjs imports sibling modules, so sync the rest of src/ too.
# Only modules that are MISSING remotely are added; db.mjs/proactive.mjs above are
# the authoritative (modified) copies and are never overwritten here.
function Push-Missing($localDir, $remoteDir) {
    Get-ChildItem -LiteralPath $localDir -File -Filter *.mjs | ForEach-Object {
        $remote = "$remoteDir/" + $_.Name
        $exists = & ssh @OPTS $SRV "test -f '$remote' && echo YES || echo NO"
        if (($exists | Out-String).Trim() -ne 'YES') {
            Push-File $_.FullName $remote | Out-Null
        }
    }
}
Push-Missing "$TMP\src" "$REMOTE/src"

# ---- 4. 跑验证 ----
Write-Host ""
Write-Host "在服务器上运行隔离验证..." -ForegroundColor Cyan
Write-Host ""
& ssh @OPTS $SRV "bash $REMOTE/ops/verify-budget-change.sh 2>&1"

Write-Host ""
Write-Host "=== 退出码: $LASTEXITCODE ===" -ForegroundColor Cyan
