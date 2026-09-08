"""W01 boundary probes and explicit qualification result."""
from __future__ import annotations

import json
import pathlib

from controller.lifecycle import WorkerLifecycle
from controller.boundary import BoundaryViolation


def run_isolation_probe(run_root: pathlib.Path, repo_root: pathlib.Path) -> dict:
    lifecycle = WorkerLifecycle.create(run_root, run_root / "snapshot", repo_root)
    probes = []
    readable = run_root / "snapshot" / "bot.db"
    try:
        lifecycle.paths.read_bytes(readable); probes.append({"name": "snapshot_read", "status": "passed"})
    except Exception as exc:
        probes.append({"name": "snapshot_read", "status": "failed", "error": str(exc)})
    try:
        lifecycle.paths.read_bytes(repo_root / "src" / "proactive.mjs")
    except BoundaryViolation:
        probes.append({"name": "production_read", "status": "passed", "observed": "blocked"})
    else:
        probes.append({"name": "production_read", "status": "failed", "observed": "allowed"})
    try:
        lifecycle.paths.write_bytes(repo_root / "production-write-probe.txt", b"blocked")
    except BoundaryViolation:
        probes.append({"name": "production_write", "status": "passed", "observed": "blocked"})
    else:
        probes.append({"name": "production_write", "status": "failed", "observed": "allowed"})
    try:
        lifecycle.network.check("https://blocked.invalid/provider")
    except BoundaryViolation:
        probes.append({"name": "network_not_allowlisted", "status": "passed", "observed": "blocked"})
    else:
        probes.append({"name": "network_not_allowlisted", "status": "failed", "observed": "allowed"})
    lifecycle.write_audit("inconclusive_local_guard_only")
    # The probes exercise the real worker-side interfaces, but this version
    # does not claim OS/container enforcement from a process-local guard.
    status = "inconclusive" if all(probe["status"] == "passed" for probe in probes) else "failed"
    result = {"schemaVersion": "isolation-probe-v2", "status": status, "qualification": "not_os_qualified", "probes": probes, "reason": "process-local boundary exercised; OS/container enforcement still requires an independently constrained worker"}
    (run_root / "isolation-probe.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
