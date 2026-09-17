# ============================================================
#  溪语服务器 - 只读命令执行器
#
#  用法:
#    pwsh -File .\ssh-run.ps1 -Script .\xiyu-p4.sh
#    pwsh -File .\ssh-run.ps1 -Command "hostname; whoami"
#
#  安全:
#    - BatchMode=yes    绝不弹密码
#    - IdentitiesOnly   只用指定密钥
#    - 只读用途，不做任何写操作
#    - 不触碰 LIMI / capybara-game
# ============================================================

param(
    [string]$Script,
    [string]$Command,
    [string]$KeyFile = "$env:USERPROFILE\.ssh\xiyu-readonly-nopass",
    [string]$Server  = "admin@39.106.153.59"
)

$ErrorActionPreference = 'Continue'
$OPTS = @('-i', $KeyFile, '-o','BatchMode=yes', '-o','IdentitiesOnly=yes',
          '-o','ConnectTimeout=15', '-o','StrictHostKeyChecking=accept-new')

if ($Command) {
    & ssh @OPTS $Server $Command
    exit $LASTEXITCODE
}

if (-not $Script) { Write-Host "需要 -Script 或 -Command"; exit 2 }
if (-not (Test-Path $Script)) { Write-Host "找不到脚本: $Script"; exit 2 }

# 读入并把换行统一成 LF（远端 bash 不接受 CRLF）
$body = (Get-Content -LiteralPath $Script -Raw) -replace "`r`n", "`n"

# 通过本地临时文件把脚本喂给远端 bash -s（避免管道 EOL 问题）
$tmp = Join-Path $env:TEMP ("xiyu-upload-{0}.sh" -f (Get-Date -Format 'yyyyMMddHHmmss'))
[System.IO.File]::WriteAllText($tmp, $body, (New-Object System.Text.UTF8Encoding($false)))

try {
    cmd /c "ssh $($OPTS -join ' ') $Server ""bash -s"" < ""$tmp"""
    $code = $LASTEXITCODE
} finally {
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
}

exit $code
