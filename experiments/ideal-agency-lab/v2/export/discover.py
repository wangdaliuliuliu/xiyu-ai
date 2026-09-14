"""Read-only source inventory and precise replica creation for W00/W02.

The exporter never imports production application modules. It opens SQLite in
read-only mode and copies only explicitly supported data files. Secret fields
are transformed by an exact field list; business document identifiers and
references are retained.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import shutil
import sqlite3
import subprocess
from typing import Any


SECRET_FIELDS = {
    "api_key", "apikey", "authorization", "bot_token", "cookie", "context_token",
    "login_session_id", "password", "refresh_token", "session", "session_token",
    "secret", "access_token", "client_secret", "password_hash", "api_secret",
}
EXACT_SECRET_TABLE_FIELDS = {
    "wechat_accounts": {"bot_token", "login_session_id"},
}
SUPPORTED_DATA_SUFFIXES = {".json", ".jsonl", ".png", ".jpg", ".jpeg", ".webp", ".gif"}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_fingerprint(path: pathlib.Path) -> dict[str, Any]:
    return {
        "locator": str(path),
        "bytes": path.stat().st_size,
        "content_hash": sha256_file(path),
        "modified_at": dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc).isoformat(),
    }


def git_revision(repo: pathlib.Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo, text=True,
            stderr=subprocess.DEVNULL,
        ).strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def _scrub_json(value: Any, field_name: str | None = None) -> Any:
    if field_name and field_name.lower() in SECRET_FIELDS:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {key: _scrub_json(child, key) for key, child in value.items()}
    if isinstance(value, list):
        return [_scrub_json(child, field_name) for child in value]
    return value


def _table_columns(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    quoted = '"' + table.replace('"', '""') + '"'
    return [
        {"name": row[1], "type": row[2], "notnull": row[3], "default": row[4], "pk": row[5]}
        for row in conn.execute(f"PRAGMA table_info({quoted})")
    ]


def sqlite_inventory(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    for name, object_type, sql in conn.execute(
        "SELECT name, type, sql FROM sqlite_master WHERE type IN ('table','view') ORDER BY name"
    ):
        quoted = '"' + name.replace('"', '""') + '"'
        try:
            count = conn.execute(f"SELECT count(*) FROM {quoted}").fetchone()[0]
        except sqlite3.Error:
            count = None
        tables.append({
            "name": name,
            "type": object_type,
            "row_count": count,
            "columns": _table_columns(conn, name) if object_type == "table" else [],
            "schema_hash": sha256_bytes((sql or "").encode("utf-8")),
        })
    return tables


def _safe_settings(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "app_settings" not in tables:
        return []
    columns = {row[1] for row in conn.execute("PRAGMA table_info(app_settings)")}
    required = {"key", "value_type", "secret", "updated_at"}
    if not required.issubset(columns):
        return [{"status": "unavailable", "reason": "app_settings_schema_incomplete"}]
    rows = []
    for key, value_type, secret, updated_at in conn.execute(
        "SELECT key,value_type,secret,updated_at FROM app_settings ORDER BY key"
    ):
        rows.append({
            "key": key,
            "value_type": value_type,
            "secret": bool(secret),
            "configured": bool(conn.execute(
                "SELECT 1 FROM app_settings WHERE key=? AND value IS NOT NULL AND length(value)>0", (key,)
            ).fetchone()),
            "updated_at": updated_at,
        })
    return rows


def _identity_map(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Export ownership identifiers, never binding/session credentials."""
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"wechat_accounts", "companions"}.issubset(tables):
        return []
    rows = conn.execute(
        "SELECT wa.account_id, wa.user_id, wa.companion_id, wa.wechat_user_id, c.user_id AS companion_user_id, c.bot_id "
        "FROM wechat_accounts wa LEFT JOIN companions c ON c.id=wa.companion_id ORDER BY wa.account_id, wa.companion_id"
    ).fetchall()
    result = []
    seen = set()
    for row in rows:
        key = (row[0], row[2])
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "owner_key": f"account:{row[0]}:companion:{row[2]}",
            "account_id": row[0], "binding_user_id": row[1], "companion_id": row[2], "wechat_user_id": row[3],
            "companion_user_id": row[4], "bot_id": row[5], "source_ref": "sqlite://wechat_accounts+companions",
        })
    return result


def _backup_readonly_db(source_db: pathlib.Path, replica_db: pathlib.Path) -> None:
    source_uri = f"file:{source_db.as_posix()}?mode=ro"
    source = sqlite3.connect(source_uri, uri=True)
    target = sqlite3.connect(replica_db)
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()


def _scrub_replica_db(replica_db: pathlib.Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(replica_db)
    transformations: list[dict[str, Any]] = []
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "app_settings" in tables:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(app_settings)")}
        if {"secret", "value"}.issubset(columns):
            conn.execute("UPDATE app_settings SET value=NULL WHERE secret=1")
            transformations.append({"table": "app_settings", "fields": ["value"], "where": "secret=1", "reason": "secret_value_removed"})
    for table, fields in EXACT_SECRET_TABLE_FIELDS.items():
        if table not in tables:
            continue
        columns = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
        existing = sorted(fields & columns)
        if existing:
            # Some source schemas require these credential columns to be NOT
            # NULL. Empty strings are the precise removal transform and keep
            # the replica schema valid without retaining a usable credential.
            assignments = ", ".join(f'"{field}"=\'\'' for field in existing)
            conn.execute(f'UPDATE "{table}" SET {assignments}')
            transformations.append({"table": table, "fields": existing, "where": "all rows", "reason": "delivery_credentials_removed"})
    for table in ("ilink_context_tokens", "pending_bind_sessions"):
        if table in tables:
            conn.execute(f'DELETE FROM "{table}"')
            transformations.append({"table": table, "fields": ["all rows"], "where": "all rows", "reason": "session_material_removed"})
    # Remove only columns whose names are explicitly classified as secrets.
    # Business identifiers such as document_id/private_domain are deliberately
    # untouched.  Empty strings are used where the source schema requires
    # NOT NULL; the transformation is recorded and replayed by E0.
    for table in sorted(tables):
        column_rows = list(conn.execute(f'PRAGMA table_info("{table.replace(chr(34), chr(34) * 2)}")'))
        columns = {row[1] for row in column_rows}
        not_null = {row[1] for row in column_rows if row[3]}
        secret_columns = sorted(columns & SECRET_FIELDS - {"secret"})
        if secret_columns:
            assignments = ", ".join(
                f'"{field.replace(chr(34), chr(34) * 2)}"=' + ("''" if field in not_null else "NULL")
                for field in secret_columns
            )
            conn.execute(f'UPDATE "{table.replace(chr(34), chr(34) * 2)}" SET {assignments}')
            transformations.append({"table": table, "fields": secret_columns, "where": "all rows", "reason": "explicit_secret_columns_removed", "replacement": {field: ("" if field in not_null else None) for field in secret_columns}})
    conn.commit()
    conn.close()
    return transformations


def _copy_data_tree(source_root: pathlib.Path, target_root: pathlib.Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    copied: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    if not source_root.exists():
        return [], [{"source_locator": str(source_root), "status": "absent_in_source", "reason": "root_missing"}]
    for source in sorted(source_root.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(source_root)
        suffix = source.suffix.lower()
        if source.name.startswith(".") or source.name.lower() in {".env", ".env.local"}:
            excluded.append({"source_locator": str(source), "status": "present_in_source", "exclusion_reason": "credential_file"})
            continue
        if suffix not in SUPPORTED_DATA_SUFFIXES:
            continue
        target = target_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if suffix in {".json", ".jsonl"}:
            try:
                if suffix == ".json":
                    value = json.loads(source.read_text(encoding="utf-8"))
                    target.write_text(json.dumps(_scrub_json(value), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                else:
                    lines = []
                    for line in source.read_text(encoding="utf-8").splitlines():
                        if not line.strip():
                            continue
                        lines.append(json.dumps(_scrub_json(json.loads(line)), ensure_ascii=False))
                    target.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                excluded.append({"source_locator": str(source), "status": "unavailable", "exclusion_reason": f"parse_error:{type(exc).__name__}"})
                continue
        else:
            shutil.copy2(source, target)
        copied.append({
            "resource_id": f"file:{relative.as_posix()}",
            "owner_scope": "workbench-data",
            "kind": "media" if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"} else "document",
            "source_locator": str(source),
            "source_version": file_fingerprint(source)["content_hash"],
            "replica_locator": str(target),
            "replica_hash": sha256_file(target),
            "status": "present",
        })
    return copied, excluded


def _source_file_resources(repo_root: pathlib.Path) -> list[dict[str, Any]]:
    relative_files = [
        "src/proactive.mjs", "src/agency_protocol.mjs", "src/enterprise_context.mjs",
        "src/companion.mjs", "src/db.mjs", "src/photo_planner.mjs", "src/photo_sender.mjs",
        "config/agency-prompts.v1.json", "docs/agency-ideal-lab-execution-plan-v2-2026-09-08.md",
        "docs/agency-ideal-lab-experiment-spec-2026-09-08.md", "docs/agency-validation-plan-v2-2026-09-08.md",
    ]
    resources = []
    for relative in relative_files:
        path = repo_root / relative
        if path.exists():
            resources.append({"resource_id": f"source:{relative}", "owner_scope": "repository", "kind": "source_file", "source_locator": str(path), "source_version": sha256_file(path), "status": "present"})
        else:
            resources.append({"resource_id": f"source:{relative}", "owner_scope": "repository", "kind": "source_file", "source_locator": str(path), "status": "absent_in_source"})
    return resources


def _quoted(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _table_rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if table not in tables:
        return []
    columns = [row[1] for row in conn.execute(f"PRAGMA table_info({_quoted(table)})")]
    rows = []
    for row in conn.execute(f"SELECT * FROM {_quoted(table)} ORDER BY rowid"):
        value = {column: row[index] for index, column in enumerate(columns)}
        rows.append(_scrub_json(value))
    return rows


def _row_ref(table: str, row: dict[str, Any], index: int) -> str:
    primary = row.get("id") or row.get("msg_id") or row.get("date_key") or row.get("date") or index
    return f"sqlite://{table}/{primary}"


def _as_fact(*, fact_id: str, owner: str, kind: str, value: Any, source_ref: str,
             version: str, observed_at: str | None = None, valid_period: dict[str, Any] | None = None,
             epistemic_status: str = "confirmed", **extra: Any) -> dict[str, Any]:
    result = {
        "id": fact_id, "owner": owner, "kind": kind, "value": value,
        "source_ref": source_ref, "version": version, "observed_at": observed_at,
        "valid_period": valid_period or {}, "epistemic_status": epistemic_status,
    }
    result.update(extra)
    return result


def build_snapshot_context(snapshot_root: pathlib.Path, inventory: dict[str, Any]) -> dict[str, Any]:
    """Materialize a normalized, discoverable dataset from one frozen DB.

    This is deliberately an export concern.  The worker receives the resulting
    context.json and never opens the source database.  Values retain a source
    reference, observed time, validity and epistemic status so the adapter can
    distinguish facts, candidates, history and persona fiction.
    """
    db_path = snapshot_root / "bot.db"
    source_version = inventory["source"]["sourceDb"]["main"].get("content_hash", "unknown")
    identities = inventory.get("identity_map", [])
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        companions = {row.get("id"): row for row in _table_rows(conn, "companions")}
        users = {row.get("id"): row for row in _table_rows(conn, "users")}
        accounts = {row.get("id"): row for row in _table_rows(conn, "user_accounts")}
        turns = _table_rows(conn, "companion_conversation_turns")
        memories = _table_rows(conn, "companion_memories")
        persona_facts = _table_rows(conn, "companion_persona_facts")
        current_works = _table_rows(conn, "companion_current_works")
        open_loops = _table_rows(conn, "companion_open_loops")
        reminders = _table_rows(conn, "companion_reminders")
        schedules = _table_rows(conn, "companion_daily_schedule")
        thoughts = _table_rows(conn, "companion_daily_thoughts")
        diaries = _table_rows(conn, "companion_diary")
        photo_log = _table_rows(conn, "companion_photo_log")
        enterprise_policies = _table_rows(conn, "enterprise_proactive_policies")
        messages = _table_rows(conn, "wechat_messages")
    finally:
        conn.close()

    owners: dict[str, dict[str, Any]] = {}
    for identity in identities:
        owner = identity["owner_key"]
        companion_id = identity.get("companion_id")
        user_id = identity.get("binding_user_id")
        companion = companions.get(companion_id, {})
        user = users.get(user_id, {})
        account = accounts.get(user_id, {})
        profile_ref = f"sqlite://companions/{companion_id}"
        profile = {
            "owner": owner,
            "account_id": identity.get("account_id"),
            "companion_id": companion_id,
            "user_id": user_id,
            "project": companion.get("role_title") or companion.get("name") or "",
            "role": companion.get("role_title") or "",
            "name": companion.get("name"),
            "goal": companion.get("role_title") or "依据可核验资料完成当前用户目标",
            "source_ref": profile_ref,
            "version": source_version,
            "observed_at": inventory.get("createdAt"),
            "epistemic_status": "confirmed",
            "companion": companion,
            "user": {key: value for key, value in user.items() if key not in SECRET_FIELDS},
            "account": {key: value for key, value in account.items() if key not in SECRET_FIELDS},
            "enterprise_policy": next((row for row in enterprise_policies if row.get("companion_id") == companion_id), {}),
        }
        scoped_turns = [row for row in turns if row.get("companion_id") == companion_id]
        scoped_memories = [row for row in memories if row.get("companion_id") == companion_id]
        scoped_persona = [row for row in persona_facts if row.get("companion_id") == companion_id]
        scoped_works = [row for row in current_works if row.get("companion_id") == companion_id]
        scoped_loops = [row for row in open_loops if row.get("companion_id") == companion_id]
        scoped_reminders = [row for row in reminders if row.get("companion_id") == companion_id]
        scoped_schedules = [row for row in schedules if row.get("companion_id") == companion_id]
        scoped_thoughts = [row for row in thoughts if row.get("companion_id") == companion_id]
        scoped_diaries = [row for row in diaries if row.get("companion_id") == companion_id]
        scoped_photos = [row for row in photo_log if row.get("companion_id") == companion_id]
        scoped_messages = [row for row in messages if row.get("companion_id") == companion_id]

        facts: list[dict[str, Any]] = []
        for index, row in enumerate(scoped_works):
            facts.append(_as_fact(fact_id=f"work-{companion_id}-{index}", owner=owner, kind="enterprise_project", value=row,
                                  source_ref=_row_ref("companion_current_works", row, index), version=source_version,
                                  observed_at=row.get("created_at"), epistemic_status=row.get("verify_status") or "confirmed"))
        for index, row in enumerate(scoped_schedules):
            facts.append(_as_fact(fact_id=f"schedule-{companion_id}-{index}", owner=owner, kind="schedule", value=row,
                                  source_ref=_row_ref("companion_daily_schedule", row, index), version=source_version,
                                  observed_at=row.get("generated_at"), valid_period={"date": row.get("date_key")},
                                  epistemic_status="persona_fiction"))
        for index, row in enumerate(scoped_thoughts + scoped_diaries):
            facts.append(_as_fact(fact_id=f"life-{companion_id}-{index}", owner=owner, kind="persona_life", value=row,
                                  source_ref=_row_ref("companion_daily_thoughts" if row in scoped_thoughts else "companion_diary", row, index),
                                  version=source_version, observed_at=row.get("generated_at") or row.get("created_at"),
                                  valid_period={"date": row.get("date_key")}, epistemic_status="persona_fiction"))
        for index, row in enumerate(scoped_memories):
            status = "candidate" if row.get("memory_type") in {"candidate", "inferred"} else "confirmed"
            facts.append(_as_fact(fact_id=f"memory-{companion_id}-{index}", owner=owner, kind="memory", value=row,
                                  source_ref=_row_ref("companion_memories", row, index), version=source_version,
                                  observed_at=row.get("created_at"), epistemic_status=status))
        for index, row in enumerate(scoped_persona):
            facts.append(_as_fact(fact_id=f"persona-fact-{companion_id}-{index}", owner=owner, kind="persona_fact", value=row,
                                  source_ref=_row_ref("companion_persona_facts", row, index), version=source_version,
                                  observed_at=row.get("created_at"), epistemic_status="confirmed"))
        for index, row in enumerate(scoped_messages):
            facts.append(_as_fact(fact_id=f"message-{companion_id}-{index}", owner=owner, kind="message_fact", value=row,
                                  source_ref=_row_ref("wechat_messages", row, index), version=source_version,
                                  observed_at=row.get("created_at"), epistemic_status="observed"))

        history = []
        for index, row in enumerate(scoped_turns):
            history.append({
                "id": f"turn-{companion_id}-{index}", "owner": owner, "role": row.get("role"),
                "text": row.get("content", ""), "sent_at": row.get("created_at"),
                "synthetic": bool(row.get("synthetic")),
                "source_ref": _row_ref("companion_conversation_turns", row, index),
                "version": source_version,
            })
        for index, row in enumerate(scoped_messages):
            role = "user" if row.get("direction") in {"in", "incoming", "received"} else "assistant"
            history.append({
                "id": f"wechat-{companion_id}-{index}", "owner": owner, "role": role,
                "text": row.get("content", ""), "sent_at": row.get("created_at"),
                "source_ref": _row_ref("wechat_messages", row, index), "version": source_version,
            })

        tasks = []
        for index, row in enumerate(scoped_loops + scoped_reminders):
            tasks.append({
                "id": str(row.get("id") or f"task-{companion_id}-{index}"), "owner": owner,
                "title": row.get("title") or row.get("message_template") or "",
                "status": row.get("status") or ("open" if row.get("enabled", 1) else "completed"),
                "due_at": row.get("due_at") or row.get("date"), "payload": row,
                "version": source_version,
                "source_ref": _row_ref("companion_open_loops" if row in scoped_loops else "companion_reminders", row, index),
            })
        schedule = []
        for index, row in enumerate(scoped_schedules):
            value = row.get("schedule_json")
            try:
                value = json.loads(value) if isinstance(value, str) else value
            except json.JSONDecodeError:
                value = {"raw": value, "parse_error": True}
            schedule.append({"id": str(row.get("date_key") or index), "owner": owner, "starts_at": row.get("date_key"),
                             "title": "persona daily schedule", "status": "planned", "schedule": value,
                             "source_ref": _row_ref("companion_daily_schedule", row, index), "valid_period": {"date": row.get("date_key")}})
        asset_refs = [{"kind": "photo_log", "value": row, "source_ref": _row_ref("companion_photo_log", row, index),
                       "status": "reference_only"} for index, row in enumerate(scoped_photos)]
        owners[owner] = {
            "profile": profile,
            "stable": {"identity": profile, "long_term_aim": profile.get("goal"), "enterprise_profile": profile,
                       "sources": [profile_ref]},
            "facts": facts,
            "knowledge": [fact for fact in facts if fact["kind"] in {"memory", "persona_fact", "enterprise_project"}],
            "memories": [fact for fact in facts if fact["kind"] in {"memory", "persona_fact"}],
            "tasks": tasks,
            "schedule": schedule,
            "history": sorted(history, key=lambda item: item.get("sent_at") or ""),
            "assets": asset_refs,
            "catalog": [{"kind": "profile", "tool": "profile.read", "source_ref": profile_ref},
                        {"kind": "facts", "tool": "knowledge.search", "source_ref": f"sqlite://companion:{companion_id}/facts"},
                        {"kind": "memory", "tool": "memory.search", "source_ref": f"sqlite://companion:{companion_id}/memory"},
                        {"kind": "tasks", "tool": "tasks.read", "source_ref": f"sqlite://companion:{companion_id}/tasks"},
                        {"kind": "research", "tool": "research", "source_ref": f"sqlite://companion:{companion_id}/research", "status": "unavailable_frozen_archive_missing"},
                        {"kind": "media", "tool": "media.prepare", "source_ref": f"sqlite://companion:{companion_id}/photo_log", "status": "reference_only"},
                        {"kind": "assets", "tool": "media.prepare", "source_ref": f"sqlite://companion:{companion_id}/photo_log"}],
            "research_archive": [], "research_status": "unavailable_frozen_archive_missing",
        }
    dataset = {
        "schemaVersion": "ideal-agency-lab-snapshot-context-v1",
        "snapshotId": inventory.get("createdAt", "unknown") + ":" + source_version[:16],
        "sourceVersion": source_version,
        "sourceLocator": inventory["source"]["sourceDb"]["main"].get("locator"),
        "timezone": inventory["source"].get("timezone", "Asia/Shanghai"),
        "authorizationStatus": inventory["source"].get("authorization_status"),
        "owners": owners,
        "resourceIndex": [{key: resource.get(key) for key in ("resource_id", "owner_scope", "kind", "source_locator", "source_version", "status")}
                          for resource in inventory.get("resources", [])],
    }
    destination = snapshot_root / "context.json"
    destination.write_text(json.dumps(dataset, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    (snapshot_root / "resource-index.json").write_text(json.dumps(dataset["resourceIndex"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return dataset


def create_snapshot(repo_root: pathlib.Path, run_root: pathlib.Path, source_db: pathlib.Path, workbench_root: pathlib.Path, mode: str = "FROZEN") -> dict[str, Any]:
    if mode not in {"EXPORT", "FROZEN", "LIVE-READONLY"}:
        raise ValueError(f"unsupported mode: {mode}")
    run_root.mkdir(parents=True, exist_ok=False)
    snapshot = run_root / "snapshot"
    snapshot.mkdir()
    db_target = snapshot / "bot.db"
    db_hashes = {"main": file_fingerprint(source_db)}
    for suffix in ("-wal", "-shm"):
        sidecar = pathlib.Path(str(source_db) + suffix)
        db_hashes[suffix[1:]] = file_fingerprint(sidecar) if sidecar.exists() else {"status": "absent_in_source", "locator": str(sidecar)}
    source = sqlite3.connect(f"file:{source_db.as_posix()}?mode=ro", uri=True)
    try:
        tables = sqlite_inventory(source)
        settings = _safe_settings(source)
        identity_map = _identity_map(source)
    finally:
        source.close()
    _backup_readonly_db(source_db, db_target)
    transformations = _scrub_replica_db(db_target)
    copied, excluded = _copy_data_tree(workbench_root / "data", snapshot / "workbench-data")
    asset_copied, asset_excluded = _copy_data_tree(workbench_root / "assets", snapshot / "workbench-assets")
    for resource in asset_copied:
        resource["resource_id"] = "asset:" + resource["resource_id"].removeprefix("file:")
        resource["owner_scope"] = "workbench-assets"
    copied.extend(asset_copied)
    excluded.extend(asset_excluded)
    resources = _source_file_resources(repo_root)
    resources.extend(copied)
    inventory = {
        "schemaVersion": "ideal-agency-lab-inventory-v2",
        "createdAt": utc_now(),
        "mode": mode,
        "source": {
            "repoRoot": str(repo_root),
            "sourceDb": db_hashes,
            "workbenchRoot": str(workbench_root),
            "gitRevision": git_revision(repo_root),
            "timezone": "Asia/Shanghai",
            "authorization_status": "unverified_local_source",
        },
        "tables": tables,
        "settings": settings,
        "identity_map": identity_map,
        "resources": resources,
        "excluded": excluded,
        "replica": {"database": str(db_target), "content_hash": sha256_file(db_target)},
        "transformations": transformations,
    }
    context_dataset = build_snapshot_context(snapshot, inventory)
    inventory["context_dataset"] = {
        "locator": str(snapshot / "context.json"),
        "content_hash": sha256_file(snapshot / "context.json"),
        "owner_count": len(context_dataset.get("owners", {})),
    }
    (run_root / "inventory.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (run_root / "id-map.json").write_text(json.dumps({"schemaVersion": "id-map-v2", "mappings": inventory["identity_map"], "status": "local_source_mapping_only", "authorization_status": inventory["source"].get("authorization_status")}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (run_root / "replica-parity.json").write_text(json.dumps({"status": "pending", "reason": "E0 evaluator not yet run", "resource_count": len(resources)}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return inventory
