"""Fail-closed proof that the real executor used a qualified worker.

The boundary probes in :mod:`evaluation.isolation` exercise the worker-side
interfaces, but they do not establish an OS/container boundary.  This module
keeps that distinction explicit.  A real provider run may proceed only when
an independently constrained worker has produced an execution receipt for the
same trajectory executor.  A hand-edited isolation probe, a process-local
guard, or a generic child process is not sufficient.
"""
from __future__ import annotations

import json
import pathlib
from typing import Any


PROOF_FILE = "worker-execution.json"


def _read(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def worker_execution_proof(run_root: pathlib.Path) -> dict[str, Any]:
    """Return the immutable-by-convention worker execution receipt, if any."""
    path = run_root / PROOF_FILE
    proof = _read(path)
    if not proof:
        return {
            "status": "not_proven",
            "qualification": "not_os_qualified",
            "reason": "no worker execution receipt was produced by an independently constrained worker",
            "path": str(path),
        }
    proof.setdefault("path", str(path))
    return proof


def validate_worker_execution_proof(run_root: pathlib.Path) -> dict[str, Any]:
    """Validate the binding between E1 evidence and the actual real runner.

    The positive shape is intentionally strict.  It must be emitted by the
    qualified worker/controller integration, not inferred from the existence
    of an isolation-probe file.
    """
    environment = _read(run_root / "environment-evidence.json")
    isolation = _read(run_root / "isolation-probe.json")
    proof = worker_execution_proof(run_root)
    reasons: list[str] = []
    environment_qualified = environment.get("isolation", {}).get("qualification") == "os_qualified"
    isolation_qualified = isolation.get("qualification") in {"qualified", "os_qualified", "passed"} and isolation.get("status") == "passed"
    if not (environment_qualified or isolation_qualified):
        reasons.append("environment_evidence_not_os_qualified")
    network_proven = environment.get("isolation", {}).get("worker_network_policy_proof") is True or (isolation.get("network_policy") or {}).get("per_worker_allowlist") is True
    if not network_proven:
        reasons.append("worker_network_policy_not_proven")
    if isolation.get("qualification") not in {"qualified", "os_qualified"} or isolation.get("status") != "passed":
        reasons.append("isolation_probe_not_qualified")
    if proof.get("status") != "passed":
        reasons.append("worker_execution_receipt_not_passed")
    if proof.get("qualification") != "os_qualified":
        reasons.append("worker_execution_receipt_not_os_qualified")
    if proof.get("execution_function") != "execute_j05_trajectory":
        reasons.append("worker_did_not_report_shared_trajectory_executor")
    if proof.get("same_executor_claim") is not True:
        reasons.append("shared_trajectory_executor_not_bound")
    if proof.get("worker_kind") in (None, ""):
        reasons.append("worker_kind_missing")
    if proof.get("worker_id") in (None, ""):
        reasons.append("worker_id_missing")
    if proof.get("worker_process", {}).get("pid") in (None, ""):
        reasons.append("worker_process_identity_missing")
    if proof.get("worker_process", {}).get("runtime") in {None, "", "local_process"}:
        reasons.append("independent_worker_runtime_missing")
    if proof.get("gateway", {}).get("credential_scope") != "gateway_only":
        reasons.append("gateway_credential_scope_not_gateway_only")
    if proof.get("gateway", {}).get("worker_receives_credential") is not False:
        reasons.append("worker_credential_visibility_not_proven")
    if proof.get("gateway", {}).get("controller_gateway_process") is not True:
        reasons.append("gateway_controller_process_not_proven")
    if proof.get("network_policy", {}).get("per_worker_allowlist") is not True:
        reasons.append("per_worker_network_policy_not_proven")
    if proof.get("path_policy", {}).get("production_read_denied") is not True:
        reasons.append("production_read_denial_not_proven_by_worker")
    if proof.get("path_policy", {}).get("production_write_denied") is not True:
        reasons.append("production_write_denial_not_proven_by_worker")
    if proof.get("oracle_policy", {}).get("oracle_read_denied") is not True:
        reasons.append("oracle_read_denial_not_proven_by_worker")
    if proof.get("trajectory_binding", {}).get("run_id") != run_root.name:
        reasons.append("worker_receipt_run_binding_mismatch")
    return {
        "status": "passed" if not reasons else "blocked",
        "qualification": "os_qualified" if not reasons else "not_os_qualified",
        "reasons": reasons,
        "proof": proof,
        "required_receipt": str(run_root / PROOF_FILE),
    }


def write_unqualified_worker_execution(run_root: pathlib.Path, *, reason: str) -> dict[str, Any]:
    """Record that the current run has no qualified worker execution proof."""
    path = run_root / PROOF_FILE
    value = {
        "schemaVersion": "worker-execution-v1",
        "status": "not_proven",
        "qualification": "not_os_qualified",
        "execution_function": "execute_j05_trajectory",
        "runtime": "process_local_guard_only",
        "reason": reason,
        "same_executor_claim": False,
        "gateway": {"controller_gateway_process": False, "credential_scope": "gateway_only", "worker_receives_credential": False},
        "network_policy": {"per_worker_allowlist": False},
        "path_policy": {"production_read_denied": False, "production_write_denied": False},
        "oracle_policy": {"oracle_read_denied": False},
        "evidence_boundary": "negative_controls_only",
    }
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return value


def real_execution_gate(run_root: pathlib.Path) -> dict[str, Any]:
    """Return the last gate before a real loop/gateway can be constructed."""
    validation = validate_worker_execution_proof(run_root)
    return {
        "status": "passed" if validation["status"] == "passed" else "blocked",
        "reason": None if validation["status"] == "passed" else "worker_execution_boundary_not_proven",
        "reasons": validation["reasons"],
        "proof": validation["proof"],
        "required_receipt": validation["required_receipt"],
    }

