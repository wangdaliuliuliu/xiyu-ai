#!/usr/bin/env bash
set -Eeuo pipefail

# Isolated rollback simulation. No systemd, /opt, production DB, or network.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
XIYU_RELEASE_LIBRARY_ONLY=1 source "$SCRIPT_DIR/agency_production_apply.sh"

ROOT="$(mktemp -d /tmp/xiyu-release-rollback-smoke.XXXXXX)"
trap 'rm -rf -- "$ROOT"' EXIT
EXPECTED_ROOT="$ROOT/root"
BACKUP_DIR="$ROOT/backup"
BACKUP_READY=1
SERVICE='xiyu-release-smoke.service'
HEALTH_URL='http://rollback-smoke.invalid/health'
DROPIN="$ROOT/dropin/agency-concern-release.conf"
RELEASE_FILES=(
  src/old.mjs
  src/new.mjs
)
mkdir -p "$EXPECTED_ROOT/src" "$BACKUP_DIR/files/src" "$(dirname "$DROPIN")"
printf 'old-release\n' > "$EXPECTED_ROOT/src/old.mjs"
printf 'new-release\n' > "$EXPECTED_ROOT/src/new.mjs"
printf 'old-release\n' > "$BACKUP_DIR/files/src/old.mjs"
: > "$BACKUP_DIR/files/src/new.mjs.missing"
printf 'old-dropin\n' > "$BACKUP_DIR/agency-concern-release.conf"
printf 'old-dropin\n' > "$DROPIN"
printf '%s/data/bot.db\n' "$EXPECTED_ROOT" > "$BACKUP_DIR/database.path"
mkdir -p "$EXPECTED_ROOT/data"
printf 'old-db\n' > "$BACKUP_DIR/database.sqlite"
printf '0:0\n' > "$BACKUP_DIR/database.owner"
printf 'new-db\n' > "$EXPECTED_ROOT/data/bot.db"
: > "$ROOT/systemctl.log"

systemctl() {
  printf '%s\n' "$1" >> "$ROOT/systemctl.log"
}
wait_http() { return 0; }
sqlite_integrity() { return 2; }

rollback

grep -qx 'start' "$ROOT/systemctl.log"
grep -qx 'daemon-reload' "$ROOT/systemctl.log"
test "$(cat "$EXPECTED_ROOT/src/old.mjs")" = 'old-release'
test ! -e "$EXPECTED_ROOT/src/new.mjs"
test "$(cat "$EXPECTED_ROOT/data/bot.db")" = 'old-db'
printf '%s\n' '{"status":"passed","scenario":"rollback_db_check_unavailable_still_starts_service","productionWrites":0,"botMessagesSent":0}'
