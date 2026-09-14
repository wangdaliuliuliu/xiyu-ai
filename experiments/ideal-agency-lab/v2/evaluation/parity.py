"""Resource-manifest-driven E0 parity checks."""
from __future__ import annotations

import hashlib
import json
import pathlib
import sqlite3
from typing import Any


class ParityFailure(AssertionError):
    pass


def _json_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _tables(path: pathlib.Path) -> dict[str, list[dict[str, Any]]]:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        names = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        result = {}
        for name in names:
            columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{name}")')]
            result[name] = [dict(row) for row in conn.execute(f'SELECT * FROM "{name}" ORDER BY rowid')]
        return result
    finally:
        conn.close()


def sqlite_logical_snapshot(path: pathlib.Path) -> dict[str, Any]:
    return _tables(path)


def compare_sqlite(source_db: pathlib.Path, replica_db: pathlib.Path, *, transformations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    source = sqlite_logical_snapshot(source_db)
    replica = sqlite_logical_snapshot(replica_db)
    expected = json.loads(json.dumps(source, ensure_ascii=False, default=str))
    # Only exact transformations declared by the exporter are accepted.
    for transform in transformations or []:
        table = transform.get("table")
        if table not in expected:
            continue
        if transform.get("reason") == "explicit_secret_columns_removed":
            replacement = transform.get("replacement", {})
            for row in expected[table]:
                for field in transform.get("fields", []):
                    if field in row:
                        row[field] = replacement.get(field, "")
        elif table == "app_settings" and transform.get("where") == "secret=1":
            for row in expected[table]:
                if row.get("secret") in (1, True):
                    row["value"] = None
        elif table == "wechat_accounts" and transform.get("where") == "all rows":
            for row in expected[table]:
                for field in transform.get("fields", []):
                    if field in row:
                        row[field] = ""
        elif transform.get("reason") == "session_material_removed":
            expected[table] = []
    mismatches = []
    table_names = sorted(set(expected) | set(replica))
    for table in table_names:
        if expected.get(table) != replica.get(table):
            mismatches.append({"table": table, "expected_hash": _json_hash(expected.get(table)), "actual_hash": _json_hash(replica.get(table))})
    return {"status": "passed" if not mismatches else "failed", "tables_compared": len(table_names), "mismatches": mismatches}


def compare_resource_manifest(inventory: dict[str, Any], run_root: pathlib.Path) -> dict[str, Any]:
    failures = []
    for resource in inventory.get("resources", []):
        status = resource.get("status")
        if status != "present":
            continue
        replica_locator = resource.get("replica_locator")
        if not replica_locator:
            continue
        path = pathlib.Path(replica_locator)
        if not path.exists():
            failures.append({"resource_id": resource.get("resource_id"), "reason": "missing_replica"})
            continue
        if resource.get("replica_hash") and hashlib.sha256(path.read_bytes()).hexdigest() != resource["replica_hash"]:
            failures.append({"resource_id": resource.get("resource_id"), "reason": "content_hash_mismatch"})
    return {"status": "passed" if not failures else "failed", "resources_checked": len(inventory.get("resources", [])), "failures": failures}


def compare_json_resource(source: pathlib.Path, replica: pathlib.Path) -> dict[str, Any]:
    """Compare two JSON resources and preserve parse errors as failures.

    A pair of malformed inputs is not equivalent merely because both parsers
    fail; source availability is part of the resource contract.
    """
    try:
        source_value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {"status": "failed", "reason": "source_parse_error", "error": type(exc).__name__}
    try:
        replica_value = json.loads(replica.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {"status": "failed", "reason": "replica_parse_error", "error": type(exc).__name__}
    return {"status": "passed" if source_value == replica_value else "failed", "reason": "value_compare", "source_hash": _json_hash(source_value), "replica_hash": _json_hash(replica_value)}


def validate_oracle_binding(manifest: dict[str, Any], oracle_manifest: dict[str, Any]) -> bool:
    return manifest.get("code_hash") == oracle_manifest.get("code_hash") and manifest.get("fixture_hash") == oracle_manifest.get("fixture_hash") and manifest.get("model") == oracle_manifest.get("model")


def validate_fact_oracle(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    """Compare fact fields, including value and source, without a fixed answer."""
    return all(actual.get(key) == expected.get(key) for key in ("owner", "store", "business_date", "metric", "value", "unit", "source_ref"))
