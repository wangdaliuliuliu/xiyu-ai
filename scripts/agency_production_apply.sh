#!/usr/bin/env bash
set -Eeuo pipefail

# One-command production release runner for the Xiyu inbound work-task chain.
# It is intentionally self-contained so it can be uploaded in the release ZIP
# and run from Aliyun Workbench. It never copies .env, a database, or credentials.

SERVICE="${XIYU_SERVICE_NAME:-xiyu-ai.service}"
EXPECTED_ROOT="${XIYU_PROJECT_ROOT:-/opt/xiyu-ai}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PAYLOAD_DIR="$SCRIPT_DIR/payload"
MANIFEST="$SCRIPT_DIR/manifest.json"
RELEASE_ID="concern-production-20260913"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_ROOT="${XIYU_RELEASE_BACKUP_ROOT:-$EXPECTED_ROOT/.release-backups}"
BACKUP_DIR="$BACKUP_ROOT/$RELEASE_ID-$STAMP"
DROPIN_DIR="/etc/systemd/system/$SERVICE.d"
DROPIN="$DROPIN_DIR/agency-concern-release.conf"
HEALTH_URL="${XIYU_HEALTH_URL:-http://127.0.0.1:3000/api/health}"
WORKBENCH_HEALTH_URL="${XIYU_WORKBENCH_HEALTH_URL:-http://127.0.0.1:4175/health}"
WAIT_SECONDS="${XIYU_RELEASE_WAIT_SECONDS:-90}"
COMPLETED=0
BACKUP_READY=0

# This list is the release boundary. Keep it explicit: no globbing, no .env,
# no DB, no experiments, no Bot credentials, and no unrelated workbench files.
RELEASE_FILES=(
  package.json
  src/agency_protocol.mjs
  src/db.mjs
  src/enterprise_context.mjs
  src/initiative.mjs
  src/proactive.mjs
  src/bot.mjs
  src/playground.mjs
  config/agency-prompts.v1.json
  config/prompts/work-context-router-v1.json
  config/prompts/work-response-v1.json
  scripts/agency_online_shadow_smoke.mjs
  scripts/agency_release_static_closure.mjs
)

log() { printf '[xiyu-release] %s\n' "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }
has() { command -v "$1" >/dev/null 2>&1; }

safe_abs_path() {
  case "$1" in
    /*) printf '%s' "$1" ;;
    *) printf '%s/%s' "$EXPECTED_ROOT" "$1" ;;
  esac
}

service_value() {
  systemctl show "$SERVICE" -p "$1" --value 2>/dev/null || true
}

service_node_bin() {
  local candidate
  candidate="$(service_value ExecStart | sed -n 's/.*path=\([^ ;]*\).*/\1/p' | head -n 1)"
  if [ -x "$candidate" ]; then
    printf '%s' "$candidate"
  else
    command -v node || true
  fi
}

service_env_files() {
  local value token file
  value="$(service_value EnvironmentFiles)"
  for token in $value; do
    file="${token#-}"
    [ -f "$file" ] && printf '%s\n' "$file"
  done
}

load_effective_env_for_probe() {
  # .env is only sourced on the remote host and never printed or copied.
  local file
  while IFS= read -r file; do
    set -a
    # shellcheck disable=SC1090
    . "$file"
    set +a
  done < <(service_env_files)
}

resolve_db_path() {
  local raw line file
  raw=""
  while IFS= read -r file; do
    line="$(sed -n 's/^[[:space:]]*DB_PATH[[:space:]]*=[[:space:]]*//p' "$file" | tail -n 1)"
    if [ -n "$line" ]; then raw="$line"; break; fi
  done < <(service_env_files)
  if [ -z "$raw" ]; then
    raw="$(service_value Environment | tr ' ' '\n' | sed -n 's/^DB_PATH=//p' | tail -n 1)"
  fi
  raw="${raw%$'\r'}"
  raw="${raw#\"}"; raw="${raw%\"}"
  raw="${raw#'}"; raw="${raw%'}"
  if [ -z "$raw" ]; then raw="$EXPECTED_ROOT/data/bot.db"; fi
  safe_abs_path "$raw"
}

resolve_root() {
  local working
  working="$(service_value WorkingDirectory)"
  if [ -z "${XIYU_PROJECT_ROOT:-}" ] && [ -n "$working" ] && [ -d "$working" ]; then
    EXPECTED_ROOT="$working"
  fi
  [ -d "$EXPECTED_ROOT" ] || die "project root missing: $EXPECTED_ROOT"
  [ "$EXPECTED_ROOT" != "/" ] || die 'refusing root directory'
  case "$EXPECTED_ROOT" in /opt|/home|/var|/etc) die "refusing broad project root: $EXPECTED_ROOT" ;; esac
  BACKUP_ROOT="${XIYU_RELEASE_BACKUP_ROOT:-$EXPECTED_ROOT/.release-backups}"
  BACKUP_DIR="$BACKUP_ROOT/$RELEASE_ID-$STAMP"
}

verify_bundle() {
  [ -f "$MANIFEST" ] || die "release manifest missing: $MANIFEST"
  [ -d "$PAYLOAD_DIR" ] || die "release payload missing: $PAYLOAD_DIR"
  has sha256sum || die 'sha256sum is required'
  local rel source expected actual node_bin
  node_bin="$(service_node_bin)"
  [ -x "$node_bin" ] || node_bin="$(command -v node || true)"
  [ -x "$node_bin" ] || die 'Node runtime missing for manifest verification'
  for rel in "${RELEASE_FILES[@]}"; do
    source="$PAYLOAD_DIR/$rel"
    [ -f "$source" ] || die "payload file missing: $rel"
    # The bundle manifest stores files as { "relative/path": "sha256" }.
    # Keep the manifest filename and relative lookup key in separate variables:
    # the latter must never become the file passed to readFileSync.
    expected="$(MANIFEST_FILE="$MANIFEST" RELEASE_REL="$rel" "$node_bin" --input-type=module -e "import fs from 'node:fs'; const m=JSON.parse(fs.readFileSync(process.env.MANIFEST_FILE,'utf8')); const value=m.files?.[process.env.RELEASE_REL]; if(typeof value!=='string') process.exit(2); console.log(value)" 2>/dev/null || true)"
    [ -n "$expected" ] || die "manifest hash missing: $rel"
    actual="$(sha256sum "$source" | awk '{print $1}')"
    [ "$actual" = "$expected" ] || die "payload hash mismatch: $rel"
  done
}

backup_file_boundary() {
  local rel source target
  mkdir -p "$BACKUP_DIR/files"
  for rel in "${RELEASE_FILES[@]}"; do
    source="$PAYLOAD_DIR/$rel"
    target="$EXPECTED_ROOT/$rel"
    mkdir -p "$BACKUP_DIR/files/$(dirname "$rel")"
    if [ -e "$target" ]; then
      cp -p -- "$target" "$BACKUP_DIR/files/$rel"
    else
      : > "$BACKUP_DIR/files/$rel.missing"
    fi
  done
}

sqlite_integrity() {
  local db="$1" output status node_bin
  if has sqlite3; then
    output="$(sqlite3 "$db" 'PRAGMA integrity_check;' 2>/dev/null)" || return 2
    [ "$output" = 'ok' ] && return 0
    return 1
  fi
  node_bin="$(service_node_bin)"
  [ -x "$node_bin" ] || return 2
  output=''; status=0
  DB_MODULE_ROOT="$EXPECTED_ROOT" DB_FOR_CHECK="$db" "$node_bin" --input-type=module -e "import { createRequire } from 'node:module'; import { pathToFileURL } from 'node:url'; const require=createRequire(pathToFileURL(process.env.DB_MODULE_ROOT + '/package.json')); const Database=require('better-sqlite3'); const db=new Database(process.env.DB_FOR_CHECK,{readonly:true,fileMustExist:true}); const rows=db.pragma('integrity_check'); db.close(); if(rows.length!==1 || rows[0].integrity_check!=='ok') process.exit(10)" >/dev/null 2>&1 || status=$?
  if [ "$status" -eq 0 ]; then return 0; fi
  if [ "$status" -eq 10 ]; then return 1; fi
  log "SQLite integrity tool unavailable (node=$node_bin)"
  return 2
}

backup_database() {
  local db="$1" out="$BACKUP_DIR/database.sqlite" node_bin status
  mkdir -p "$BACKUP_DIR"
  [ -f "$db" ] || die "database missing: $db"
  if has sqlite3; then
    sqlite3 "$db" ".timeout 15000" ".backup '$out'"
  else
    node_bin="$(service_node_bin)"
    [ -x "$node_bin" ] || die 'sqlite3 unavailable and service Node runtime missing'
    status=0
    DB_MODULE_ROOT="$EXPECTED_ROOT" DB_FOR_BACKUP="$db" OUT_FOR_BACKUP="$out" "$node_bin" --input-type=module -e "import { createRequire } from 'node:module'; import { pathToFileURL } from 'node:url'; const require=createRequire(pathToFileURL(process.env.DB_MODULE_ROOT + '/package.json')); const Database=require('better-sqlite3'); const db=new Database(process.env.DB_FOR_BACKUP,{readonly:true,fileMustExist:true}); await db.backup(process.env.OUT_FOR_BACKUP); db.close()" \
      >/dev/null 2>&1 || status=$?
    [ "$status" -eq 0 ] \
      || die 'sqlite3 unavailable and better-sqlite3 backup API failed'
  fi
  status=0
  sqlite_integrity "$out" || status=$?
  case "$status" in
    0) ;;
    1) die 'backup integrity_check reported corruption' ;;
    *) die 'backup integrity_check unavailable' ;;
  esac
  printf '%s\n' "$db" > "$BACKUP_DIR/database.path"
  stat -c '%u:%g' "$db" > "$BACKUP_DIR/database.owner"
}

backup_runtime_metadata() {
  local db="$1" envfile line
  service_value WorkingDirectory > "$BACKUP_DIR/service-working-directory"
  service_value User > "$BACKUP_DIR/service-user"
  service_value ExecStart > "$BACKUP_DIR/service-exec-start"
  service_value EnvironmentFiles > "$BACKUP_DIR/service-environment-files"
  service_value Environment | tr ' ' '\n' | sed -n '/^XIYU_/p;/^DB_PATH=/p;/^API_PORT=/p;/^API_HOST=/p' | sed 's/=.*/=<set>/' > "$BACKUP_DIR/effective-flags"
  while IFS= read -r envfile; do
    line="$(sha256sum "$envfile" | awk '{print $1}')"
    printf '%s  %s\n' "$line" "$envfile" >> "$BACKUP_DIR/env-hashes"
  done < <(service_env_files)
  if [ -e "$DROPIN" ]; then
    cp -p -- "$DROPIN" "$BACKUP_DIR/agency-concern-release.conf"
  else
    : > "$BACKUP_DIR/agency-concern-release.conf.missing"
  fi
  {
    printf 'service=%s\nroot=%s\ndb=%s\nbackup=%s\n' "$SERVICE" "$EXPECTED_ROOT" "$db" "$BACKUP_DIR"
    printf 'createdAt=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } > "$BACKUP_DIR/backup-record"
}

backup_all() {
  local db="$1"
  mkdir -p "$BACKUP_ROOT"
  case "$BACKUP_ROOT" in /|/opt|/home|/var|/etc) die "refusing broad backup root: $BACKUP_ROOT" ;; esac
  backup_file_boundary
  backup_database "$db"
  backup_runtime_metadata "$db"
  (cd "$BACKUP_DIR" && find . -type f -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
  BACKUP_READY=1
  log "backup ready: $BACKUP_DIR"
}

install_payload() {
  local rel source target mode owner
  for rel in "${RELEASE_FILES[@]}"; do
    source="$PAYLOAD_DIR/$rel"
    target="$EXPECTED_ROOT/$rel"
    mkdir -p "$(dirname "$target")"
    mode='0644'
    case "$rel" in *.mjs|*.json|package.json) mode='0644' ;; esac
    owner=''
    if [ -e "$target" ]; then owner="$(stat -c '%u:%g' "$target")"; fi
    install -m "$mode" "$source" "$target"
    if [ -n "$owner" ]; then chown "$owner" "$target"; fi
  done
}

set_release_flag() {
  local mode="$1"
  mkdir -p "$DROPIN_DIR"
  cat > "$DROPIN" <<EOF
[Service]
Environment=XIYU_AGENCY_MODE=$mode
Environment=XIYU_SHADOW_NOOP_SENDER=0
EOF
  chmod 0644 "$DROPIN"
  systemctl daemon-reload
}

wait_http() {
  local url="$1" label="$2" deadline now body
  deadline=$((SECONDS + WAIT_SECONDS))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if body="$(curl --silent --show-error --max-time 5 --fail "$url" 2>/dev/null)" && printf '%s' "$body" | grep -q '"ok"[[:space:]]*:[[:space:]]*true'; then
      log "$label healthy"
      return 0
    fi
    sleep 2
  done
  log "$label health timeout after ${WAIT_SECONDS}s"
  return 1
}

restart_and_wait() {
  systemctl restart "$SERVICE"
  wait_http "$HEALTH_URL" 'xiyu'
  # The workbench may be managed by a separate process. A reachable health URL
  # is checked here when present; an absent local endpoint is not a reason to
  # claim workbench success, so shadow smoke will fail if catalog is unavailable.
  if curl --silent --show-error --max-time 3 --fail "$WORKBENCH_HEALTH_URL" >/dev/null 2>&1; then
    log 'workbench health reachable'
  else
    log 'workbench health endpoint not directly reachable; shadow smoke remains authoritative'
  fi
}

verify_runtime_only() {
  local db service_user node_bin probe_dir module_status health_status closure_status closure_count closure_file
  resolve_root
  systemctl cat "$SERVICE" >/dev/null 2>&1 || die "service not found: $SERVICE"
  db="$(resolve_db_path)"
  [ -f "$db" ] || die "database missing: $db"
  node_bin="$(service_node_bin)"
  [ -x "$node_bin" ] || die 'service Node runtime not found'
  service_user="$(service_value User)"; [ -n "$service_user" ] || service_user='root'
  module_status=0
  DB_MODULE_ROOT="$EXPECTED_ROOT" "$node_bin" --input-type=module -e "import { createRequire } from 'node:module'; import { pathToFileURL } from 'node:url'; const require=createRequire(pathToFileURL(process.env.DB_MODULE_ROOT + '/package.json')); process.stdout.write(require.resolve('better-sqlite3'))" >/dev/null 2>&1 || module_status=$?
  [ "$module_status" -eq 0 ] || die 'better-sqlite3 is not resolvable from project runtime'
  closure_status=0
  closure_file="$(mktemp /tmp/xiyu-release-closure.XXXXXX)"
  ENTRY_FILE="$PAYLOAD_DIR/scripts/agency_online_shadow_smoke.mjs" PROJECT_ROOT="$EXPECTED_ROOT" "$node_bin" "$PAYLOAD_DIR/scripts/agency_release_static_closure.mjs" >"$closure_file" 2>&1 || closure_status=$?
  closure_count="$(sed -n 's/^static_import_closure=//p' "$closure_file" | tail -n 1)"
  rm -f -- "$closure_file"
  [ "$closure_status" -eq 0 ] || die 'installed project static import closure is incomplete'
  [ -n "$closure_count" ] || die 'installed project static import closure was not checked'
  module_status=0
  sqlite_integrity "$db" || module_status=$?
  case "$module_status" in
    0) ;;
    1) die 'current database integrity_check reported corruption' ;;
    *) die 'current database integrity_check unavailable' ;;
  esac

  # Exercise the exact service-user traversal shape without touching /opt,
  # systemd, production DB, or the uploaded root-owned extraction directory.
  probe_dir="$(mktemp -d /tmp/xiyu-release-verify.XXXXXX)"
  mkdir -p "$probe_dir/payload"
  cp -a -- "$PAYLOAD_DIR" "$probe_dir/payload/release"
  if [ "$service_user" != root ]; then chown -R "$service_user" "$probe_dir"; fi
  if [ "$service_user" = root ] || [ "$(id -un)" = "$service_user" ]; then
    "$node_bin" --check "$probe_dir/payload/release/scripts/agency_online_shadow_smoke.mjs"
  else
    runuser -u "$service_user" -- test -r "$probe_dir/payload/release/scripts/agency_online_shadow_smoke.mjs" || die 'service user cannot read isolated shadow payload'
    runuser -u "$service_user" -- "$node_bin" --check "$probe_dir/payload/release/scripts/agency_online_shadow_smoke.mjs"
  fi
  rm -rf -- "$probe_dir"

  health_status=0
  curl --silent --show-error --max-time 5 --fail "$HEALTH_URL" >/dev/null 2>&1 || health_status=$?
  [ "$health_status" -eq 0 ] || die 'xiyu health preflight failed'
  printf 'verify_only=passed\nservice=%s\nroot=%s\ndb=%s\nnode=%s\nserviceUser=%s\ncurrentDbIntegrity=ok\nstaticImportClosure=%s\nserviceUserShadowPayload=readable\nhealth=ok\n' \
    "$SERVICE" "$EXPECTED_ROOT" "$db" "$node_bin" "$service_user" "$closure_count"
}

run_shadow_smoke() {
  local node_bin service_user temp_dir smoke_status=0
  node_bin="$(service_node_bin)"
  [ -x "$node_bin" ] || die 'Node runtime not found for shadow smoke'
  service_user="$(service_value User)"
  [ -n "$service_user" ] || service_user='root'
  temp_dir="$(mktemp -d /tmp/xiyu-agency-shadow.XXXXXX)"
  mkdir -p "$temp_dir/logs"
  if [ "$service_user" != root ]; then chown -R "$service_user" "$temp_dir"; fi
  export DB_PATH="$temp_dir/bot.db"
  export DATA_DIR="$temp_dir"
  export LOG_DIR="$temp_dir/logs"
  export XIYU_WORKBENCH_ACTIVE_TASKS_PATH="$temp_dir/active-tasks.json"
  export XIYU_WORKBENCH_OUTBOX_PATH="$temp_dir/outbox.json"
  export XIYU_WORKBENCH_CONTEXT_ENABLED=true
  export XIYU_AGENCY_MODE=shadow
  export XIYU_SHADOW_NOOP_SENDER=1
  export XIYU_RELEASE_SHADOW_NO_OUTBOUND=1
  load_effective_env_for_probe
  # Reassert the safety flags after loading .env.
  export DB_PATH="$temp_dir/bot.db" DATA_DIR="$temp_dir" LOG_DIR="$temp_dir/logs"
  export XIYU_WORKBENCH_ACTIVE_TASKS_PATH="$temp_dir/active-tasks.json"
  export XIYU_WORKBENCH_OUTBOX_PATH="$temp_dir/outbox.json"
  export XIYU_WORKBENCH_CONTEXT_ENABLED=true XIYU_AGENCY_MODE=shadow XIYU_SHADOW_NOOP_SENDER=1 XIYU_RELEASE_SHADOW_NO_OUTBOUND=1 XIYU_SHADOW_PROJECT_ROOT="$EXPECTED_ROOT" XIYU_SHADOW_TEMP_ROOT="$temp_dir"
  log 'running isolated shadow smoke (providerCalls=0, botMessagesSent=0)'
  if [ "$service_user" = root ] || [ "$(id -un)" = "$service_user" ]; then
    if (cd "$EXPECTED_ROOT" && "$node_bin" scripts/agency_online_shadow_smoke.mjs); then smoke_status=0; else smoke_status=$?; fi
  else
    if runuser -u "$service_user" -- env \
      DB_PATH="$DB_PATH" DATA_DIR="$DATA_DIR" LOG_DIR="$LOG_DIR" \
      XIYU_WORKBENCH_ACTIVE_TASKS_PATH="$XIYU_WORKBENCH_ACTIVE_TASKS_PATH" \
      XIYU_WORKBENCH_OUTBOX_PATH="$XIYU_WORKBENCH_OUTBOX_PATH" \
      XIYU_WORKBENCH_CONTEXT_ENABLED=true XIYU_AGENCY_MODE=shadow XIYU_SHADOW_NOOP_SENDER=1 XIYU_RELEASE_SHADOW_NO_OUTBOUND=1 \
      XIYU_SHADOW_PROJECT_ROOT="$EXPECTED_ROOT" XIYU_SHADOW_TEMP_ROOT="$temp_dir" \
      XIYU_WORKBENCH_CONTEXT_URL="${XIYU_WORKBENCH_CONTEXT_URL:-http://127.0.0.1:4175}" \
      XIYU_WORKBENCH_CONTEXT_TOKEN="${XIYU_WORKBENCH_CONTEXT_TOKEN:-}" \
      sh -c 'cd "$1" && exec "$2" scripts/agency_online_shadow_smoke.mjs' _ "$EXPECTED_ROOT" "$node_bin"; then smoke_status=0; else smoke_status=$?; fi
  fi
  rm -rf -- "$temp_dir" || true
  return "$smoke_status"
}

restore_files() {
  local rel target backup missing restore_status=0
  for rel in "${RELEASE_FILES[@]}"; do
    target="$EXPECTED_ROOT/$rel"
    backup="$BACKUP_DIR/files/$rel"
    missing="$BACKUP_DIR/files/$rel.missing"
    if [ -f "$missing" ]; then
      rm -f -- "$target" || restore_status=1
    elif [ -f "$backup" ]; then
      if ! install -m 0644 "$backup" "$target"; then
        restore_status=1
      else
        chown --reference="$backup" "$target" 2>/dev/null || true
      fi
    else
      log "rollback file backup missing: $rel"
      restore_status=1
    fi
  done
  return "$restore_status"
}

restore_dropin() {
  if [ -f "$BACKUP_DIR/agency-concern-release.conf.missing" ]; then
    rm -f -- "$DROPIN"
  elif [ -f "$BACKUP_DIR/agency-concern-release.conf" ]; then
    mkdir -p "$DROPIN_DIR"
    install -m 0644 "$BACKUP_DIR/agency-concern-release.conf" "$DROPIN"
  else
    log 'rollback dropin backup missing'
    return 1
  fi
  systemctl daemon-reload
}

restore_database() {
  local db backup current_wal current_shm stamp integrity_status
  db="$(cat "$BACKUP_DIR/database.path")"
  backup="$BACKUP_DIR/database.sqlite"
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  current_wal="${db}-wal"; current_shm="${db}-shm"
  if [ ! -f "$backup" ]; then
    log 'rollback DB backup missing'
    return 1
  fi
  if [ -e "$current_wal" ]; then mv -- "$current_wal" "$current_wal.before-rollback-$stamp"; fi
  if [ -e "$current_shm" ]; then mv -- "$current_shm" "$current_shm.before-rollback-$stamp"; fi
  if ! install -m 0640 "$backup" "$db"; then
    log 'rollback DB restore copy failed'
    return 1
  fi
  if [ -f "$BACKUP_DIR/database.owner" ]; then chown "$(cat "$BACKUP_DIR/database.owner")" "$db" || true; fi
  integrity_status=0
  sqlite_integrity "$db" || integrity_status=$?
  case "$integrity_status" in
    0) log 'rollback DB integrity_check=ok'; return 0 ;;
    1) log 'rollback DB integrity_check reported corruption'; return 1 ;;
    *) log 'rollback DB integrity_check unavailable; DB copy restored but not verified'; return 1 ;;
  esac
}

rollback() {
  local file_status=0 dropin_status=0 db_status=0 start_status=0 health_status=0
  [ "$BACKUP_READY" = 1 ] || return 0
  log 'failure detected; stopping service and restoring release boundary'
  systemctl stop "$SERVICE" || true
  if restore_files; then file_status=0; else file_status=$?; fi
  log "rollback file_restore_status=$file_status"
  if restore_dropin; then dropin_status=0; else dropin_status=$?; fi
  log "rollback dropin_restore_status=$dropin_status"
  if restore_database; then db_status=0; else db_status=$?; fi
  log "rollback db_restore_status=$db_status"
  if systemctl start "$SERVICE"; then start_status=0; else start_status=$?; fi
  log "rollback service_start_status=$start_status"
  if [ "$start_status" -eq 0 ] && wait_http "$HEALTH_URL" 'xiyu rollback'; then
    health_status=0
  else
    health_status=1
  fi
  log "rollback health_status=$health_status file_restore=$file_status dropin_restore=$dropin_status db_restore=$db_status service_start=$start_status backup=$BACKUP_DIR"
  if [ "$file_status" -eq 0 ] && [ "$dropin_status" -eq 0 ] && [ "$db_status" -eq 0 ] && [ "$start_status" -eq 0 ] && [ "$health_status" -eq 0 ]; then
    log 'rollback completed; backup retained'
  else
    log 'rollback incomplete; inspect service journal and retained backup'
  fi
}

on_exit() {
  local status=$?
  if [ "$status" -ne 0 ] && [ "$COMPLETED" -ne 1 ]; then rollback || true; fi
  exit "$status"
}
trap on_exit EXIT

# Test harness hook. It only exposes pure rollback helpers when this file is
# sourced by the isolated local smoke; executing the production script with
# this flag still exits without touching any service or filesystem target.
if [ "${XIYU_RELEASE_LIBRARY_ONLY:-0}" = 1 ]; then
  if [ "${BASH_SOURCE[0]}" != "$0" ]; then return 0; fi
  exit 0
fi

# Local packaging/acceptance hook: exercise the exact payload verifier from an
# unpacked bundle without touching systemd, /opt, a database, or any service.
if [ "${XIYU_RELEASE_VERIFY_ONLY:-0}" = 1 ]; then
  if [ "${XIYU_RELEASE_BUNDLE_ONLY:-0}" != 1 ]; then
    [ "$(id -u)" -eq 0 ] || die 'run verify-only as root via sudo from Aliyun Workbench'
    has systemctl || die 'systemd is required'
    has curl || die 'curl is required'
  fi
  verify_bundle
  if [ "${XIYU_RELEASE_BUNDLE_ONLY:-0}" = 1 ]; then
    log "bundle verification passed: ${#RELEASE_FILES[@]} payload files"
    COMPLETED=1
    exit 0
  fi
  verify_runtime_only
  COMPLETED=1
  exit 0
fi

[ "$(id -u)" -eq 0 ] || die 'run as root via sudo from Aliyun Workbench'
has systemctl || die 'systemd is required'
has curl || die 'curl is required'
resolve_root
verify_bundle
systemctl cat "$SERVICE" >/dev/null 2>&1 || die "service not found: $SERVICE"
DB_PATH_RESOLVED="$(resolve_db_path)"
log "preflight service=$SERVICE root=$EXPECTED_ROOT db=$DB_PATH_RESOLVED"
backup_all "$DB_PATH_RESOLVED"
install_payload

set_release_flag shadow
restart_and_wait
run_shadow_smoke
log 'shadow passed; switching release flag to enabled'
set_release_flag enabled
restart_and_wait

# Final read-only release evidence; no message is sent and no Bot API is called.
printf '\n--- enabled release evidence ---\n'
printf 'service=%s\nroot=%s\ndb=%s\nbackup=%s\n' "$SERVICE" "$EXPECTED_ROOT" "$DB_PATH_RESOLVED" "$BACKUP_DIR"
printf 'agencyMode=enabled\nbotMessagesSent=0\nproductionWrites=0\nrealModelCalls=0\n'
systemctl is-active "$SERVICE"
systemctl is-enabled "$SERVICE" 2>/dev/null || true
systemctl --no-pager --quiet status "$SERVICE" || true
printf '%s\n' '--- recent sanitized service log ---'
journalctl -u "$SERVICE" --since "$(date -u -d '10 minutes ago' '+%Y-%m-%d %H:%M:%S')" --no-pager -o cat \
  | sed -E 's/(api[_-]?key|token|authorization|password|secret)[=:][^ ]+/\1=<redacted>/Ig' \
  | tail -n 80

COMPLETED=1
log 'production release completed; backup retained for rollback'
