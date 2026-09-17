# ============================================================
#  Xiyu server - read-only check / connection test / login doctor
#
#  Usage:
#    powershell -ExecutionPolicy Bypass -File xiyu-check.ps1 -Mode doctor
#    powershell -ExecutionPolicy Bypass -File xiyu-check.ps1 -Mode test
#    powershell -ExecutionPolicy Bypass -File xiyu-check.ps1 -Mode full
#
#  Console output is ASCII only on purpose, so it works on any
#  Windows codepage. Chinese text goes into the report file
#  (written as UTF-8 with BOM, so Notepad shows it correctly).
#
#  Safety:
#    1. Every remote command is read-only (query / list / hash).
#    2. Nothing is modified, restarted or deleted on the server.
#    3. No password or private key content is read or stored.
#    4. Never touches LIMI (/home/admin/LIMIbackend) or
#       capybara-game (/opt/capybara-game).
# ============================================================

param(
    [ValidateSet('doctor','test','full')]
    [string]$Mode = 'full'
)

$ErrorActionPreference = 'Continue'

# ---------------- settings ----------------
# Key resolution (changed 2026-09-14).
#
# The original "xiyu-readonly" key IS passphrase-protected and its
# passphrase was lost. With BatchMode=yes ssh cannot ask for it, so
# OpenSSH silently abandons public-key auth half way through and prints
#
#     admin@<host>: Permission denied (publickey,password)
#
# even though the server had ALREADY accepted the key:
#     debug1: Server accepts key: ... xiyu-readonly ...
#     debug2: we did not send a packet, disable method   <-- signature never sent
#
# That message previously sent the diagnosis down the wrong path ("the
# public key is not installed"). It was installed all along; the local
# private key simply could not be decrypted. A dedicated passphrase-free
# read-only key is used instead. See README step 1-1.
$KEY_CANDIDATES = @(
    "$env:USERPROFILE\.ssh\xiyu-readonly-nopass"
    "$env:USERPROFILE\.ssh\xiyu-readonly"
)
$KEY_FILE = $KEY_CANDIDATES | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $KEY_FILE) { $KEY_FILE = $KEY_CANDIDATES[0] }

# Guard against that class of failure ever being misread again.
# The cipher name is readable from the base64 header WITHOUT decrypting
# anything ("none" = unencrypted). Unlike "ssh-keygen -y -f <key>", this
# check can never block waiting for a passphrase prompt.
function Test-KeyNeedsPassphrase {
    param([string]$Path)
    try {
        $line2 = (Get-Content -LiteralPath $Path -TotalCount 2 -Encoding ASCII)[1]
        # openssh-key-v1 + ciphername "none" + kdfname "none"
        return -not $line2.StartsWith('b3BlbnNzaC1rZXktdjEAAAAABG5vbmU')
    } catch { return $false }
}

$SERVER   = "39.106.153.59"     # xiyu.myworlds.cn
$LOGIN    = "admin"             # daily login account
# Xiyu service runs as system user "xiyu"; database reads use
# "sudo -u xiyu", but the login account is always admin. No root.
#
# Other projects on the same host (NEVER touched by this tool):
#   LIMI           /home/admin/LIMIbackend   limi-backend.service   127.0.0.1:8000
#   capybara-game  /opt/capybara-game        PM2 limi-kid           127.0.0.1:18001
# ------------------------------------------

$SSH_OPTS = @('-o','BatchMode=yes','-o','ConnectTimeout=10','-o','StrictHostKeyChecking=accept-new')

Write-Host ""
Write-Host "======================================================"
Write-Host "  Xiyu read-only check   [mode: $Mode]"
Write-Host "======================================================"
Write-Host ""

# ---------------- key check ----------------
if (-not (Test-Path $KEY_FILE)) {
    Write-Host "[STOP] Private key not found:" -ForegroundColor Red
    Write-Host "  $KEY_FILE"
    Write-Host ""
    Write-Host "Existing keys on this PC:"
    Get-ChildItem "$env:USERPROFILE\.ssh" -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -notlike "*.pub" -and $_.Name -notlike "known_hosts*" -and $_.Name -ne "config" } |
        ForEach-Object { Write-Host "  - $($_.Name)" }
    Write-Host ""
    Read-Host "Press Enter to close"
    exit 1
}

# ---------------- reliable login test ----------------
# NOTE: an earlier version of this script matched on "LOGIN_OK" anywhere in
# the combined output and therefore reported success even when ssh failed.
# Now the exit code decides, and the marker must be on its own line.
function Test-Login {
    $raw  = & ssh -i $KEY_FILE @SSH_OPTS "$LOGIN@$SERVER" "printf 'MARKER:%s\n' LOGIN_OK" 2>&1
    $code = $LASTEXITCODE
    $text = ($raw | Out-String)
    $ok   = ($code -eq 0) -and ($text -match '(?m)^MARKER:LOGIN_OK\s*$')
    return [pscustomobject]@{ Ok = $ok; Code = $code; Text = $text.Trim() }
}

Write-Host "Key file : $KEY_FILE"
Write-Host "Server   : $SERVER"
Write-Host "Login    : $LOGIN"
Write-Host ""

Write-Host "Logging in ..." -NoNewline
$login = Test-Login

if (-not $login.Ok) {
    Write-Host " FAILED" -ForegroundColor Red
    Write-Host ""
    Write-Host "ssh exit code : $($login.Code)"
    Write-Host "ssh said      :" -ForegroundColor Red
    Write-Host $login.Text
    Write-Host ""
    # ---- local cause check, before blaming the server -------------------
    if (Test-KeyNeedsPassphrase $KEY_FILE) {
        Write-Host "LOCAL CAUSE FOUND: this private key is passphrase-protected." -ForegroundColor Red
        Write-Host "BatchMode=yes cannot ask for the passphrase, so ssh abandons" -ForegroundColor Yellow
        Write-Host "public-key auth mid-way and prints a misleading" -ForegroundColor Yellow
        Write-Host "'Permission denied (publickey,password)' - even when the server" -ForegroundColor Yellow
        Write-Host "has already accepted the key." -ForegroundColor Yellow
        Write-Host ""
        Write-Host "Fix: use the passphrase-free key, or load this one into the" -ForegroundColor Yellow
        Write-Host "agent first:  ssh-add `"$KEY_FILE`"" -ForegroundColor Yellow
        Write-Host ""
    }
    if ($Mode -eq 'doctor') {
        Write-Host "Running login doctor to find the cause ..." -ForegroundColor Yellow
        Write-Host ""
        $DOC = @'
echo "===== Doctor: why can this key not log in? ====="
echo
echo "-- D0. Where did our own request get to --"
echo "(compare with the local report: 'Server accepts key' means the"
echo " public key IS installed, so the fault is on the client side)"
echo
echo "-- D1. Who am I, where am I --"
whoami
echo "home: $HOME"
echo
echo "-- D2. Is the authorized_keys file there --"
if [ -f "$HOME/.ssh/authorized_keys" ]; then
  echo "$HOME/.ssh/authorized_keys EXISTS"
  echo "lines in file      : $(wc -l < $HOME/.ssh/authorized_keys)"
  echo "xiyu keys present  : $(grep -cE 'xiyu-readonly' $HOME/.ssh/authorized_keys)"
  echo "our key present    : $(grep -cE 'xiyu-readonly-nopass' $HOME/.ssh/authorized_keys)"
else
  echo "$HOME/.ssh/authorized_keys IS MISSING"
fi
echo
echo "-- D3. Permissions (sshd is strict about these) --"
ls -ld "$HOME" "$HOME/.ssh" 2>&1
ls -l  "$HOME/.ssh/authorized_keys" 2>&1
echo
echo "-- D4. sshd effective auth settings --"
sudo -n sshd -T 2>/dev/null | grep -Ei '^(pubkeyauthentication|passwordauthentication|authorizedkeysfile|strictmodes|permitrootlogin|allowusers|denyusers)' || echo "(cannot read sshd -T without sudo)"
echo
echo "-- D5. Recent sshd auth failures for this host --"
sudo -n journalctl -u ssh -n 40 --no-pager 2>/dev/null | tail -25 || sudo -n journalctl -u sshd -n 40 --no-pager 2>/dev/null | tail -25 || echo "(cannot read sshd journal without sudo)"
echo
echo "===== Doctor end ====="
'@
        $doc = & ssh -i $KEY_FILE @SSH_OPTS "$LOGIN@$SERVER" $DOC 2>&1 | Out-String
        Write-Host $doc
        Write-Host ""
        Write-Host "NOTE: the doctor cannot log in either, so the checks above" -ForegroundColor Yellow
        Write-Host "will only work if password login is still allowed." -ForegroundColor Yellow
    } else {
        Write-Host "Do NOT assume the public key is missing." -ForegroundColor Yellow
        Write-Host "On 2026-09-14 this exact message was caused by a passphrase-" -ForegroundColor Yellow
        Write-Host "protected private key, while the server had already accepted" -ForegroundColor Yellow
        Write-Host "the public key ('debug1: Server accepts key' in the verbose log)." -ForegroundColor Yellow
        Write-Host ""
        Write-Host "Run 0-doctor.bat for ssh's own verbose account, and see" -ForegroundColor Yellow
        Write-Host "README step 1-3 for how to tell an encrypted key from a plain one." -ForegroundColor Yellow
    }
    Write-Host ""
    Read-Host "Press Enter to close"
    exit 1
}

Write-Host " OK" -ForegroundColor Green
Write-Host ""

$IDENT = & ssh -i $KEY_FILE @SSH_OPTS "$LOGIN@$SERVER" "hostname; whoami; uname -r" 2>&1 | Out-String

# ---------------- test mode ----------------
if ($Mode -eq 'test') {
    Write-Host "Server info:"
    Write-Host $IDENT.Trim()
    Write-Host ""
    Write-Host "======================================================"
    Write-Host "  CONNECTION OK - login really works now" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Next: double-click  2-run-check.bat"
    Write-Host "======================================================"
    Write-Host ""
    Read-Host "Press Enter to close"
    exit 0
}

# ---------------- full check (all read-only, other projects excluded) ----------------
$REMOTE = @'
echo "===== A. Server identity ====="
hostname
whoami
uname -r

echo
echo "===== B. Xiyu and workbench services (read only) ====="
echo "-- xiyu-ai.service --"
systemctl is-active xiyu-ai.service 2>&1
systemctl show xiyu-ai.service -p MainPID -p ActiveState -p SubState -p User -p ExecStart --no-pager 2>&1
echo "-- yuanqu-workbench-api.service --"
systemctl is-active yuanqu-workbench-api.service 2>&1

echo
echo "===== C. Xiyu directories ====="
for d in /opt/xiyu-ai /opt/yuanqu-workbench-api; do
  if [ -d "$d" ]; then
    echo "$d exists, size: $(du -sh $d 2>/dev/null | cut -f1)"
  else
    echo "$d MISSING"
  fi
done

echo
echo "===== D. Directories under /opt (other projects excluded) ====="
ls -1 /opt 2>&1 | grep -vx -e 'capybara-game' -e 'LIMIbackend' -e 'limi'

echo
echo "===== E. Xiyu related service files ====="
systemctl list-unit-files --type=service --no-pager 2>/dev/null | grep -E '^(xiyu-ai|yuanqu-workbench-api)\.service' || echo "(none matched)"

echo
echo "===== F. Isolation check ====="
echo "-- F1. user running the Xiyu service --"
ps -o user= -p "$(systemctl show xiyu-ai.service -p MainPID --value 2>/dev/null)" 2>/dev/null || echo "unavailable"

echo "-- F2. Xiyu node processes only (other projects hidden) --"
for pid in $(pgrep -f node 2>/dev/null); do
  cwd=$(readlink /proc/$pid/cwd 2>/dev/null)
  case "$cwd" in
    /opt/xiyu-ai*|/opt/yuanqu-workbench-api*) echo "pid=$pid user=$(ps -o user= -p $pid 2>/dev/null) cwd=$cwd" ;;
  esac
done

echo "-- F3. Listening ports (labelled per project) --"
ss -ltnp 2>/dev/null | grep -E ':(3000|4175|8000|18001)\b' || echo "(no match)"

echo "-- F4. Xiyu database files --"
ls -la /opt/xiyu-ai/data/*.db 2>&1 || echo "not found"

echo "-- F5. Project boundaries --"
echo "Xiyu            /opt/xiyu-ai               xiyu-ai.service               :3000"
echo "Workbench       /opt/yuanqu-workbench-api  yuanqu-workbench-api.service  :4175"
echo "[OUT OF SCOPE]  LIMI           /home/admin/LIMIbackend  limi-backend.service  :8000"
echo "[OUT OF SCOPE]  capybara-game  /opt/capybara-game       PM2 limi-kid          :18001"

echo
echo "===== G. Xiyu database table names (names only) ====="
DB=/opt/xiyu-ai/data/bot.db
if [ -f "$DB" ]; then
  echo "(owner: $(stat -c '%U' "$DB" 2>/dev/null); opened read-only as user xiyu)"
  sudo -n -u xiyu sqlite3 -readonly "$DB" ".tables" 2>&1 | head -40 \
    || echo "READ FAILED (see README step 1-3; other sections are unaffected)"
else
  echo "database missing: $DB"
fi

echo
echo "===== H. Key switches (names only, values hidden) ====="
systemctl show xiyu-ai.service -p Environment --no-pager 2>&1 \
  | tr ' ' '\n' \
  | grep -E '^(XIYU_AGENCY_MODE|XIYU_ENTERPRISE_PROACTIVE_ENABLED|XIYU_ENTERPRISE_CONTEXT_ENABLED|XIYU_ENTERPRISE_CONTEXT_URL|DB_PATH|XIYU_DB_PATH)=' \
  | sed -E 's/=.*/=<hidden>/' \
  || echo "(no match)"

echo
echo "===== I. Production file fingerprints ====="
sha256sum /opt/xiyu-ai/config/agency-prompts.v1.json 2>&1
sha256sum /opt/xiyu-ai/src/initiative.mjs 2>&1

echo
echo "===== J. Recent Xiyu logs (last 30 lines) ====="
journalctl -u xiyu-ai.service -n 30 --no-pager 2>&1 | tail -30 || echo "log read failed (may need sudo)"

echo
echo "===== END ====="
'@

Write-Host "Running read-only check (15-30 seconds) ..."
Write-Host ""

$result = & ssh -i $KEY_FILE @SSH_OPTS "$LOGIN@$SERVER" $REMOTE 2>&1 | Out-String

# ---------- report file ----------
# Built with HERE-STRINGS AT COLUMN 0 and explicit values on purpose:
# an earlier version used an indented @" "@ block and PowerShell treated
# $( ) and $VAR inside it as live code, producing a broken header.
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$OUT   = Join-Path $PSScriptRoot "xiyu-check-result-$stamp.txt"
$now   = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$who   = "$LOGIN@$SERVER"

$head = @(
  '========================================================'
  '  Xiyu 服务器只读体检报告'
  '========================================================'
  "生成时间：$now"
  "登录账号：$who"
  ''
  '【怎么读这份报告】'
  '  A 服务器身份      B 溪语/工作台服务状态'
  '  C 溪语目录        D /opt 下的目录'
  '  E 相关服务        F 分区隔离检查   <-- 最关键'
  '  G 数据库表名      H 关键开关（值已隐藏）'
  '  I 生产文件指纹    J 最近日志'
  ''
  '【本次范围】'
  '  溪语          /opt/xiyu-ai               xiyu-ai.service               :3000'
  '  经营工作台    /opt/yuanqu-workbench-api  yuanqu-workbench-api.service  :4175'
  ''
  '【非本次范围 - 本工具未读取、未修改】'
  '  LIMI          /home/admin/LIMIbackend    limi-backend.service          :8000'
  '  capybara-game /opt/capybara-game         PM2 limi-kid                  :18001'
  ''
  '============================== 原始输出 =============================='
  ''
)

# UTF-8 WITH BOM so Windows PowerShell 5.1 / Notepad read Chinese correctly
$content = ($head -join "`r`n") + "`r`n" + $result
[System.IO.File]::WriteAllText($OUT, $content, (New-Object System.Text.UTF8Encoding($true)))

Write-Host "... done."
Write-Host ""
Write-Host "======================================================"
Write-Host "  REPORT SAVED" -ForegroundColor Green
Write-Host ""
Write-Host "  File : $OUT"
Write-Host ""
Write-Host "  Open it with Notepad, then send the content back."
Write-Host "  It contains no passwords and no private keys."
Write-Host "======================================================"
Write-Host ""
Write-Host "Last lines (quick reference):"
$tail = ($result -split "`n") | Where-Object { $_.Trim() -ne '' } | Select-Object -Last 12
$tail | ForEach-Object { Write-Host "  $_" }
Write-Host ""
Read-Host "Press Enter to close"
