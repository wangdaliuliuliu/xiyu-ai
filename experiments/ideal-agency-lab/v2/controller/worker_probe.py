"""Subprocess entry used by C04 mutation probes.

It is intentionally tiny: the parent starts a real worker subprocess and the
child exercises the same boundary object used by the runner.  This proves
process participation, while E1 still requires an OS/container qualification.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from boundary import BoundaryViolation, PathBoundary, NetworkBoundary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-root", required=True)
    parser.add_argument("--snapshot-root", required=True)
    parser.add_argument("--blocked-path", required=True)
    parser.add_argument("--readable-file", required=True)
    parser.add_argument("--url", default="https://blocked.invalid/")
    args = parser.parse_args()
    audit_path = pathlib.Path(args.worker_root) / "probe-audit.json"
    root = pathlib.Path(args.worker_root)
    root.mkdir(parents=True, exist_ok=True)
    paths = PathBoundary(root, [pathlib.Path(args.snapshot_root)], [pathlib.Path(args.blocked_path)])
    result = {"file_read_allowed": "not_run", "file_read": "not_run", "file_write": "not_run", "network": "not_run", "audit": str(audit_path)}
    try:
        paths.read_bytes(pathlib.Path(args.readable_file))
        result["file_read_allowed"] = {"status": "allowed"}
    except Exception as exc:
        result["file_read_allowed"] = {"status": "failed", "error": str(exc)}
    try:
        paths.read_bytes(pathlib.Path(args.blocked_path))
    except BoundaryViolation as exc:
        result["file_read"] = {"status": "blocked", "error": str(exc)}
    try:
        paths.write_bytes(pathlib.Path(args.blocked_path) / "probe.txt", b"blocked")
    except BoundaryViolation as exc:
        result["file_write"] = {"status": "blocked", "error": str(exc)}
    try:
        NetworkBoundary(set()).check(args.url)
    except BoundaryViolation as exc:
        result["network"] = {"status": "blocked", "error": str(exc)}
    audit_path.write_text(json.dumps({"result": result, "file_attempts": paths.audit.file_attempts, "network_attempts": paths.audit.network_attempts}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["file_read_allowed"]["status"] == "allowed" and all(item.get("status") == "blocked" for item in (result["file_read"], result["file_write"], result["network"])) else 1


if __name__ == "__main__":
    raise SystemExit(main())
