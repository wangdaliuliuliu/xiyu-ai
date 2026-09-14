"""Bounded local semantic smoke for the concern/evidence path.

This is deliberately a separate execution scope from the qualified worker
runner.  It is useful for a small, low-risk check of the real model contract,
but it never loads a Bot transport and never writes the production source.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sqlite3
from typing import Any
from urllib.parse import urlsplit

from controller.boundary import NetworkBoundary
from controller.gateway import ProviderResponse
from controller.provider_config import build_text_gateway, resolve_production_text_binding
from controller.worker_gateway import SpendGuard
from evaluation.j05_simulation import (
    OWNER,
    _file_sha,
    _read_json,
    _write_json,
    execute_j05_trajectory,
)
from evaluation.semantic_delta import audit_semantic_delta
from transport.sink import NoOpSink


LOCAL_SCOPE = "local_isolated_semantic_smoke"
DEFAULT_PRIOR_PROBE_CNY = 0.0003388
CASES_IN_ORDER = ("K12", "K02", "K04", "K08", "K10")
REQUIRED_TRACE_FIELDS = (
    "retrievedSourceRefs",
    "selectedConcernId",
    "autoRecordedEvidenceRefs",
    "modelConcernUpdates",
    "acceptedConcernPatches",
    "rejectedConcernPatches",
    "actionEvidenceRefs",
    "receipt",
    "persistedVersion",
)
PRODUCTION_FILES = (
    pathlib.Path("data/bot.db"),
    pathlib.Path("data/bot.db-wal"),
    pathlib.Path("data/bot.db-shm"),
    pathlib.Path(".env"),
    pathlib.Path("src/enterprise_context.mjs"),
    pathlib.Path("workbench/backend/cognition/source-router.mjs"),
    pathlib.Path("workbench/backend/feishu-sync-server.mjs"),
)


def _sha256(path: pathlib.Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _production_fingerprint(root: pathlib.Path) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for relative in PRODUCTION_FILES:
        path = root / relative
        stat = path.stat() if path.exists() and path.is_file() else None
        rows[str(relative)] = {
            "path": str(path),
            "status": "present" if stat else "absent",
            "sha256": _sha256(path),
            "mtime_ns": stat.st_mtime_ns if stat else None,
            "size": stat.st_size if stat else None,
        }
    return rows


class LocalBudgetGateway:
    """Controller-side direct gateway with a cumulative spend guard."""

    def __init__(self, delegate: Any, guard: SpendGuard, audit: list[dict[str, Any]]):
        self.delegate = delegate
        self.guard = guard
        self.audit = audit
        self.model_name = delegate.model_name

    def complete(self, prompt: dict[str, Any], *, attempt: int = 1) -> ProviderResponse:
        payload = json.dumps(self.delegate._payload(prompt, attempt), ensure_ascii=False).encode("utf-8")
        reservation = self.guard.reserve(payload)
        request_id = hashlib.sha256(payload + str(attempt).encode("ascii")).hexdigest()[:32]
        if not reservation.get("allowed"):
            response = ProviderResponse(request_id, self.model_name, {}, finish_reason="error", error="cost_budget_exhausted", http_status=429)
            self.audit.append({"request_id": request_id, "attempt": attempt, "provider_call": False, "http_status": 429, "error": response.error, "cost": {**reservation, "guard": self.guard.snapshot()}})
            return response
        response = self.delegate.complete(prompt, attempt=attempt)
        settlement = self.guard.settle(reservation, response, provider_call=True)
        self.audit.append({
            "request_id": response.request_id,
            "attempt": attempt,
            "provider_call": True,
            "http_status": response.http_status,
            "error": response.error,
            "usage": response.usage,
            "cost": settlement,
            "prompt_sha256": hashlib.sha256(payload).hexdigest(),
        })
        return response


def _read_jsonl(path: pathlib.Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _sqlite_concern_state(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return {"active": [], "events": [], "version_by_id": {}}
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        active = [dict(row) for row in conn.execute("SELECT concern_id, version, status FROM concerns WHERE owner=? ORDER BY concern_id", (OWNER,)).fetchall()]
        events = [dict(row) for row in conn.execute("SELECT event_id, operation, concern_id, new_version AS version FROM concern_events WHERE owner=? ORDER BY event_record_id", (OWNER,)).fetchall()]
    finally:
        conn.close()
    return {"active": active, "events": events, "version_by_id": {str(row["concern_id"]): row["version"] for row in active}}


def _failure_class(result: dict[str, Any]) -> str:
    event_statuses = {
        str(item.get("status"))
        for item in (result.get("event_results") or [])
        if isinstance(item, dict)
    }
    if "fixture_branch_gap" in event_statuses:
        return "fixture/data"
    if "schema_failure" in event_statuses:
        return "contract/JSON"
    if event_statuses.intersection({"provider_error", "provider_timeout", "budget_exhausted", "http_error"}):
        return "provider"
    error = json.dumps(result.get("error", result), ensure_ascii=False).lower()
    if any(token in error for token in ("records", "snapshot", "fixture", "source", "material")):
        return "fixture/data"
    if any(token in error for token in ("schema", "json", "contract")):
        return "contract/JSON"
    if any(token in error for token in ("provider", "http_", "timeout", "budget")):
        return "provider"
    if any(token in error for token in ("prompt", "model")):
        return "prompt/model"
    return "runtime"


def _trajectory_audit(trajectory: pathlib.Path, case_id: str) -> dict[str, Any]:
    traces = _read_jsonl(trajectory / "traces" / "trace.jsonl")
    prompts = _read_jsonl(trajectory / "actual-prompts.jsonl")
    sink_rows = _read_jsonl(trajectory / "traces" / "sink.jsonl")
    missing_fields = sorted({field for row in traces for field in REQUIRED_TRACE_FIELDS if field not in row})
    visible = [row.get("attempt", {}).get("payload", {}).get("text") for row in sink_rows if row.get("kind") == "noop_sink_attempt"]
    outbound_calls = sum(1 for row in sink_rows if row.get("kind") == "noop_sink_attempt" and row.get("outboundCalls") not in (0, None))
    new_ref = "experiment://account:1:companion:1/j05/k12/revision/2/中影店"
    prompt_text = json.dumps(prompts, ensure_ascii=False)
    trace_text = json.dumps(traces, ensure_ascii=False)
    k12_source_in_context = case_id == "K12" and new_ref in prompt_text
    k12_source_consumed = case_id == "K12" and new_ref in trace_text and any(row.get("kind") in {"tool_result", "continuation_decision", "delivery", "path_assignment"} for row in traces)
    empty_update_with_evidence = any(
        row.get("modelConcernUpdates") == [] and bool(row.get("autoRecordedEvidenceRefs"))
        for row in traces
    )
    accepted_patch = any(bool(row.get("acceptedConcernPatches")) for row in traces)
    persisted_versions = sorted({row.get("persistedVersion") for row in traces if row.get("persistedVersion") is not None})
    unsupported_claims: list[dict[str, Any]] = []
    business_markers = ("经营", "业绩", "客流", "票房", "销售", "数据", "中影", "东坝")
    uncertainty_markers = ("没查到", "无法", "还没有", "不确定", "不能确认", "暂时")
    for row in sink_rows:
        message = str(row.get("attempt", {}).get("payload", {}).get("text") or "")
        if any(marker in message for marker in business_markers) and any(char.isdigit() for char in message) and not any(marker in message for marker in uncertainty_markers):
            event_id = row.get("attempt", {}).get("trace_context", {}).get("event_id")
            event_traces = [item for item in traces if item.get("event_id") == event_id]
            evidence = any(item.get("retrievedSourceRefs") or item.get("actionEvidenceRefs") or item.get("autoRecordedEvidenceRefs") or any(ref in json.dumps(item, ensure_ascii=False) for ref in ("feishu://", "experiment://")) for item in event_traces)
            if not evidence:
                unsupported_claims.append({"message": message, "event_id": event_id})
    state = _sqlite_concern_state(trajectory / "state.db")
    return {
        "trace_count": len(traces),
        "prompt_count": len(prompts),
        "visible_responses": visible,
        "outboundCalls": 0,
        "outbound_call_violations": outbound_calls,
        "missing_trace_fields": missing_fields,
        "k12_source_in_model_context": k12_source_in_context,
        "k12_source_consumed_by_trace": k12_source_consumed,
        "empty_updates_with_auto_evidence": empty_update_with_evidence,
        "accepted_semantic_patch": accepted_patch,
        "persisted_versions": persisted_versions,
        "unsupported_business_claims": unsupported_claims,
        "concern_state": state,
    }


def run_local_semantic_smoke(*, run_root: pathlib.Path, production_root: pathlib.Path, max_budget_cny: float = 5.0, max_output_tokens: int = 128, prior_observed_cny: float = DEFAULT_PRIOR_PROBE_CNY, case_ids: list[str] | None = None) -> dict[str, Any]:
    artifact_path = run_root / "local-semantic-smoke.json"
    if artifact_path.exists():
        return {"status": "refused_existing_evidence", "reason": "local semantic smoke evidence is immutable", "artifact": str(artifact_path)}
    if max_budget_cny <= 0 or max_output_tokens < 64:
        return {"status": "blocked", "reason": "local semantic smoke requires positive budget and max_output_tokens >= 64"}
    manifest = _read_json(run_root / "manifest.json", {})
    case_manifest = _read_json(run_root / "case-manifest.json", {})
    cases = {str(item.get("case_id")): item for item in case_manifest.get("cases", []) if isinstance(item, dict)}
    if any(case_id not in cases for case_id in CASES_IN_ORDER):
        return {"status": "blocked", "reason": "required K12/K02/K04/K08/K10 cases are not materialized in the frozen manifest"}
    selected_cases = tuple(dict.fromkeys(case_ids or CASES_IN_ORDER))
    if not selected_cases or any(case_id not in CASES_IN_ORDER for case_id in selected_cases):
        return {"status": "blocked", "reason": f"case_ids must be selected from {list(CASES_IN_ORDER)}"}
    before = _production_fingerprint(production_root)
    binding, effective = resolve_production_text_binding(production_root=production_root)
    parsed = urlsplit(str(binding.endpoint or ""))
    binding_ok = binding.ready and str(binding.provider) == "deepseek" and str(binding.model) == "deepseek-chat" and parsed.hostname == "api.deepseek.com" and parsed.path == "/v1/chat/completions"
    result: dict[str, Any] = {
        "schemaVersion": "local-semantic-smoke-v1",
        "status": "blocked",
        "execution_scope": LOCAL_SCOPE,
        "run": str(run_root),
        "cases_in_order": list(selected_cases),
        "coverage_complete": selected_cases == CASES_IN_ORDER,
        "provider": {"provider": binding.provider, "model": binding.model, "endpoint_host": parsed.hostname, "endpoint_path": parsed.path, "binding_ready": bool(binding.ready), "binding_ok": binding_ok, "credential_value_recorded": False, "credential_in_worker": False},
        "no_op_sink": {"enabled": True, "outboundCalls": 0, "transport_loaded": False},
        "budget": {"max_budget_cny": float(max_budget_cny), "prior_observed_cny": float(prior_observed_cny), "max_output_tokens": int(max_output_tokens)},
        "production_before": before,
        "production_after": None,
        "samples": [],
    }
    if not binding_ok:
        result["reason"] = "current effective binding is not the required deepseek/deepseek-chat endpoint"
        result["production_after"] = _production_fingerprint(production_root)
        _write_json(artifact_path, result)
        return result
    remaining_budget = max(0.0, float(max_budget_cny) - float(prior_observed_cny))
    guard = SpendGuard(max_budget_cny=remaining_budget, cny_per_usd_ceiling=10.0, max_output_tokens=max_output_tokens)
    parsed_boundary = NetworkBoundary({parsed.hostname or ""}, {parsed.path})
    delegate = build_text_gateway(binding, network_boundary=parsed_boundary, max_output_tokens=max_output_tokens)
    gateway_audit: list[dict[str, Any]] = []
    output_root = run_root / "local-semantic-smoke-trajectories"
    output_root.mkdir(parents=True, exist_ok=False)
    prompt_paths = {"C": pathlib.Path((case_manifest.get("arms") or {}).get("C", {}).get("prompt_path") or "")}
    if not prompt_paths["C"].exists():
        prompt_paths["C"] = pathlib.Path(manifest.get("prompt_path") or "")
    sink_audit: dict[str, Any] = {"outboundCalls": 0, "visibleResponses": []}

    def gateway_factory(_arm: str, _case_id: str, _seeded: bool) -> LocalBudgetGateway:
        return LocalBudgetGateway(delegate, guard, gateway_audit)

    def sink_factory(trajectory: pathlib.Path) -> NoOpSink:
        return NoOpSink(trajectory / "traces" / "sink.jsonl", sink_audit)

    for case_id in selected_cases:
        case_result = execute_j05_trajectory(
            run_root,
            output_root,
            cases[case_id],
            "C",
            1,
            prompt_paths["C"],
            gateway_factory,
            LOCAL_SCOPE,
            sink_factory=sink_factory,
            allow_noop_sink=True,
        )
        trajectory = output_root / "C" / case_id / "r01"
        audit = _trajectory_audit(trajectory, case_id)
        semantic_delta = audit_semantic_delta(cases[case_id], _read_jsonl(trajectory / "traces" / "trace.jsonl"))
        sample_status = case_result.get("status") == "passed" and not audit["missing_trace_fields"] and audit["outbound_call_violations"] == 0 and not audit["unsupported_business_claims"] and semantic_delta["status"] == "passed"
        result["samples"].append({"case_id": case_id, "status": "passed" if sample_status else "failed", "failure_class": None if sample_status else (_failure_class(case_result) if case_result.get("status") != "passed" else "semantic_delta"), "trajectory_result": case_result, "audit": audit, "semantic_delta": semantic_delta})
        if guard.snapshot().get("active_reserved_cny_at_safety_rate", 0) >= remaining_budget or guard.snapshot().get("unresolved_reserved_cny_at_safety_rate", 0) >= remaining_budget:
            break
    after = _production_fingerprint(production_root)
    budget_snapshot = guard.snapshot()
    total_observed_cny = float(prior_observed_cny) + float(budget_snapshot.get("actual_usage_spent_cny_at_safety_rate") or 0.0)
    all_samples_passed = len(result["samples"]) == len(selected_cases) and all(item["status"] == "passed" for item in result["samples"])
    k12 = next((item for item in result["samples"] if item["case_id"] == "K12"), {})
    semantic_requirements = {
        "k12_source_enters_context": bool((k12.get("audit") or {}).get("k12_source_in_model_context")) if k12 else "not_assessed",
        "k12_source_consumed": bool((k12.get("audit") or {}).get("k12_source_consumed_by_trace")) if k12 else "not_assessed",
        "empty_updates_with_evidence": any(bool((item.get("audit") or {}).get("empty_updates_with_auto_evidence")) for item in result["samples"]) if result["samples"] else False,
        "accepted_semantic_patch_persisted": any(bool((item.get("audit") or {}).get("accepted_semantic_patch")) and bool((item.get("audit") or {}).get("persisted_versions")) for item in result["samples"]) if result["samples"] else False,
        "no_unsupported_business_claims": all(not (item.get("audit") or {}).get("unsupported_business_claims") for item in result["samples"]),
    }
    assessed_requirements = {key: value for key, value in semantic_requirements.items() if value != "not_assessed"}
    acceptance_complete = selected_cases == CASES_IN_ORDER and all(bool(value) for value in assessed_requirements.values())
    result.update({
        "status": "passed" if all_samples_passed and acceptance_complete and sink_audit.get("outboundCalls", 0) == 0 and before == after and total_observed_cny <= max_budget_cny else "failed",
        "provider_calls": sum(1 for item in gateway_audit if item.get("provider_call")),
        "gateway_audit": gateway_audit,
        "budget_after": budget_snapshot,
        "total_observed_cny_at_safety_rate": total_observed_cny,
        "production_after": after,
        "production_unchanged": before == after,
        "semantic_requirements": semantic_requirements,
        "visible_response_count": len(sink_audit.get("visibleResponses", [])),
        "outboundCalls": sink_audit.get("outboundCalls", 0),
        "real_semantic_acceptance": acceptance_complete and all_samples_passed,
        "not_a_full_isolated_worker_experiment": True,
    })
    _write_json(artifact_path, result)
    return result
