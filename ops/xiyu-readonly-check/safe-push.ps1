# ============================================================
#  安全上传器（base64 传输）
#
#  为什么需要它：
#    直接用 `cmd /c ssh ... < 文件` 传含中文的 .mjs 时，
#    PowerShell 读文件默认按 GBK 解码，会把 UTF-8 中文改坏，
#    结果是源文件传上去语法就废了（Unexpected token '}'）。
#    base64 是纯 ASCII，传输过程不会被任何编码转换影响。
#
#  用法:
#    pwsh -File safe-push.ps1 -SftpLike SRC DST
#    pwsh -File safe-push.ps1 -PairsFile pairs.json
#
#  每个文件都会: 写临时 base64 文件 → 上传 → 服务端解码 → 校验 sha256。
#  任一环节不一致立即报错停止。
# ============================================================

param(
    [string]$SftpLike,
    [string]$PairsFile,
    [string]$KeyFile = "$env:USERPROFILE\.ssh\xiyu-readonly-nopass",
    [string]$Server  = "admin@39.106.153.59"
)

$ErrorActionPreference = 'Stop'
$SSH = 'ssh'
$OPTS = @('-i', $KeyFile, '-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','ConnectTimeout=25','-o','StrictHostKeyChecking=accept-new')

function Get-Sha256([string]$path) {
    (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLower()
}

function Push-One([string]$local, [string]$remote) {
    if (-not (Test-Path -LiteralPath $local)) { throw "本地文件不存在: $local" }
    $localHash = Get-Sha256 $local

    # 以字节读入再 base64，彻底避开文本编码转换
    $bytes = [System.IO.File]::ReadAllBytes($local)
    $b64   = [System.Convert]::ToBase64String($bytes)

    $tmp = Join-Path $env:TEMP ("push-{0}.b64" -f ([guid]::NewGuid().ToString('N')))
    [System.IO.File]::WriteAllText($tmp, $b64, (New-Object System.Text.ASCIIEncoding))

    try {
        # 把 base64 文本喂给远端 base64 -d，解码后写入目标
        $remoteCmd = "base64 -d > '$remote'"
        $line = "ssh $($OPTS -join ' ') $Server ""$remoteCmd"" < ""$tmp"""
        cmd /c $line
        if ($LASTEXITCODE -ne 0) { throw "上传失败($LASTEXITCODE): $remote" }

        $remoteHash = (& $SSH @OPTS $Server "sha256sum '$remote' | cut -d' ' -f1") 2>&1 | Out-String
        $remoteHash = $remoteHash.Trim().ToLower()
        if ($remoteHash -ne $localHash) {
            throw "哈希不一致 $remote`n  本地: $localHash`n  远端: $remoteHash"
        }
        Write-Host "  OK  $remote  $localHash" -ForegroundColor Green
    } finally {
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    }
}

if ($PairsFile) {
    $pairs = Get-Content -LiteralPath $PairsFile -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($p in $pairs) { Push-One $p.local $p.remote }
} elseif ($SftpLike) {
    # 形如: local1 remote1 local2 remote2 ...
    $parts = $SftpLike -split '\s+'
    for ($i = 0; $i -lt $parts.Count; $i += 2) { Push-One $parts[$i] $parts[$i+1] }
} else {
    throw "需要 -SftpLike 或 -PairsFile"
}

Write-Host "全部上传完成并校验通过" -ForegroundColor Green
