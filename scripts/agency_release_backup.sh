#!/usr/bin/env bash
# Create a recoverable release/code/config manifest and consistent SQLite backup.
# Credentials are never copied; .env is represented by a hash only.
# Usage: RELEASE_ROOT=/opt/xiyu-ai BACKUP_ROOT=/opt/xiyu-backups bash scripts/agency_release_backup.sh
set -euo pipefail

ROOT="${RELEASE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BACKUP_ROOT="${BACKUP_ROOT:-$ROOT/data/agency-release-backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$BACKUP_ROOT/$STAMP"
DB="${DB_PATH:-$ROOT/data/bot.db}"

case "$ROOT" in /|/opt|/home) echo "refusing broad RELEASE_ROOT=$ROOT" >&2; exit 2;; esac
test -d "$ROOT" || { echo "release root not found: $ROOT" >&2; exit 1; }
test -f "$DB" || { echo "database not found: $DB" >&2; exit 1; }
command -v sqlite3 >/dev/null 2>&1 || { echo "sqlite3 CLI is required for a consistent backup" >&2; exit 1; }
mkdir -p "$OUT/files" "$OUT/database"

sqlite3 "$DB" ".backup '$OUT/database/bot.db'"
test "$(sqlite3 "$OUT/database/bot.db" 'PRAGMA integrity_check;')" = ok

FILES=(
  package.json package-lock.json
  src/agency_protocol.mjs src/db.mjs src/enterprise_context.mjs src/initiative.mjs src/proactive.mjs src/bot.mjs
  config/agency-prompts.v1.json config/prompts/work-context-router-v1.json
  workbench/backend/cognition/source-router.mjs workbench/backend/feishu-sync-server.mjs
  deploy/xiyu-ai.service
)
for relative in "${FILES[@]}"; do
  test -f "$ROOT/$relative" || { echo "missing release file: $relative" >&2; exit 1; }
  mkdir -p "$OUT/files/$(dirname "$relative")"
  cp -p -- "$ROOT/$relative" "$OUT/files/$relative"
done

if [ -f "$ROOT/.env" ]; then
  sha256sum "$ROOT/.env" > "$OUT/env.sha256"
else
  echo "absent" > "$OUT/env.sha256"
fi
( cd "$ROOT" && git rev-parse HEAD && git branch --show-current && git status --short ) > "$OUT/git-state.txt"
find "$OUT/files" -type f -exec sha256sum {} + > "$OUT/SHA256SUMS"
printf 'status=passed\nbackup=%s\ndatabase=%s\n' "$OUT" "$OUT/database/bot.db"
