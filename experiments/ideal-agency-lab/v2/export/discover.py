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
    "secret", "access_token", "client_secret",
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
    return [{
        "account_id": row[0], "binding_user_id": row[1], "companion_id": row[2], "wechat_user_id": row[3],
        "companion_user_id": row[4], "bot_id": row[5], "source_ref": "sqlite://wechat_accounts+companions",
    } for row in rows]


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
    (run_root / "inventory.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (run_root / "id-map.json").write_text(json.dumps({"schemaVersion": "id-map-v2", "mappings": inventory["identity_map"], "status": "local_source_mapping_only", "authorization_status": inventory["source"].get("authorization_status")}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (run_root / "replica-parity.json").write_text(json.dumps({"status": "pending", "reason": "E0 evaluator not yet run", "resource_count": len(resources)}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return inventory
