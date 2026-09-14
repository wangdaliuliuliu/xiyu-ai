#!/usr/bin/env bash
# Restore the exact files/database from an agency_release_backup directory.
# This is intentionally explicit and recoverable: require ROLLBACK_CONFIRM=YES,
# keep the current DB as .before-rollback, and refuse a running systemd service.
set -euo pipefail

ROOT="${RELEASE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BACKUP="${AGENCY_RELEASE_BACKUP_DIR:-}"
DB="${DB_PATH:-$ROOT/data/bot.db}"
SERVICE="${XIYU_SERVICE_NAME:-xiyu-ai.service}"
case "$ROOT" in /|/opt|/home) echo "refusing broad RELEASE_ROOT=$ROOT" >&2; exit 2;; esac
test -n "$BACKUP" || { echo "set AGENCY_RELEASE_BACKUP_DIR to an exact backup directory" >&2; exit 1; }
test -d "$BACKUP/files" || { echo "invalid backup: $BACKUP" >&2; exit 1; }
test -f "$BACKUP/database/bot.db" || { echo "backup database missing: $BACKUP/database/bot.db" >&2; exit 1; }
[ "${ROLLBACK_CONFIRM:-}" = YES ] || { echo "set ROLLBACK_CONFIRM=YES after stopping the service" >&2; exit 1; }
if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet "$SERVICE"; then
  echo "stop $SERVICE before rollback; current DB is not overwritten while service is running" >&2
  exit 1
fi
command -v sqlite3 >/dev/null 2>&1 || { echo "sqlite3 CLI is required" >&2; exit 1; }
test "$(sqlite3 "$BACKUP/database/bot.db" 'PRAGMA integrity_check;')" = ok || { echo "backup integrity failed" >&2; exit 1; }

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
if [ -f "$DB" ]; then
  cp -p -- "$DB" "$DB.before-rollback-$STAMP"
  [ -f "$DB-wal" ] && cp -p -- "$DB-wal" "$DB-wal.before-rollback-$STAMP" || true
  [ -f "$DB-shm" ] && cp -p -- "$DB-shm" "$DB-shm.before-rollback-$STAMP" || true
fi
cp -p -- "$BACKUP/database/bot.db" "$DB"
while IFS= read -r -d '' source; do
  relative="${source#"$BACKUP/files/"}"
  mkdir -p "$ROOT/$(dirname "$relative")"
  cp -p -- "$source" "$ROOT/$relative"
done < <(find "$BACKUP/files" -type f -print0)
printf 'status=passed\nrollback_source=%s\ncurrent_db_backup=%s.before-rollback-%s\n' "$BACKUP" "$DB" "$STAMP"
