"""One-call K12 continuation-equivalent semantic smoke.

This runner prepares a real isolated continuation state from the frozen K12
fixture, reads the materialized experimental source through the normal local
adapter, persists that observation into the normal EventStore, reopens the
store, and gives the resulting state directly to one DeepSeek decision call.
It deliberately does not run the four-event trajectory and refuses a second
provider request.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import pathlib
import sys
import tempfile
import uuid
from typing import Any


V2_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(V2_ROOT) not in sys.path:
    sys.path.insert(0, str(V2_ROOT))

from adapters.local import LocalAdapters
from contracts.schemas import parse_and_validate_decision, validate_tool_result
from controller.boundary import NetworkBoundary
from controller.gateway import ProviderResponse
from controller.provider_config import build_text_gateway, resolve_production_text_binding
from controller.worker_gateway import SpendGuard
from evaluation.j05_simulation import (
    OWNER,
    _apply_intervention,
    _materialize_trajectory,
    _read_json,
    _refresh_trajectory_manifest,
    _seed_capacity,
    _file_sha,
    _write_json,
)
from evaluation.local_semantic_smoke import _production_fingerprint
from runtime.context import ContextBuilder
from runtime.loop import AgencyLoop
from runtime.policy import Policy
from runtime.prompts.assemble import assemble_compact_continuation
from runtime.store import EventStore
from transport.sink import NoOpSink


PRIOR_OBSERVED_CNY = 4.21874424
TOTAL_CNY_LIMIT = 4.95
# R4 is a single compact verification call.  Keep the preflight stricter than
# the task-wide one-yuan ceiling so an unexpectedly large envelope fails
# closed before any provider request.
NEW_CALL_CNY_LIMIT = 0.10
EXPECTED_FIELDS = {"desired_direction", "next_review_condition"}


def _jsonl_append(path: pathlib.Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _estimate_cny(payload: bytes, max_output_tokens: int) -> float:
    # Match SpendGuard's conservative byte-per-token input upper bound and
    # peak DeepSeek price basis exactly.
    usd = (len(payload) * 0.44 + max(1, int(max_output_tokens)) * 1.32) / 1_000_000
    return usd * 10.0


def _concern_snapshot(concern: dict[str, Any] | None) -> dict[str, Any]:
    if not concern:
        return {}
    return {
        "id": concern.get("id"),
        "version": concern.get("version"),
        "status": concern.get("status"),
        "desired_direction": concern.get("desired_direction"),
        "next_review_condition": concern.get("next_review_condition"),
        "known_summary": copy.deepcopy(concern.get("known_summary", [])),
        "unknowns": copy.deepcopy(concern.get("unknowns", [])),
    }


def _record_trace(path: pathlib.Path, *, event_id: str, kind: str, selected_id: str | None,
                  retrieved: list[str], auto_refs: list[str], updates: list[dict[str, Any]],
                  accepted: list[dict[str, Any]], rejected: list[dict[str, Any]],
                  action_refs: list[str], receipt: Any, persisted: int | None,
                  **payload: Any) -> None:
    row = {
        "owner": OWNER,
        "event_id": event_id,
        "step": payload.pop("step", 0),
        "selectedConcernId": selected_id,
        "retrievedSourceRefs": retrieved,
        "autoRecordedEvidenceRefs": auto_refs,
        "modelConcernUpdates": updates,
        "acceptedConcernPatches": accepted,
        "rejectedConcernPatches": rejected,
        "actionEvidenceRefs": action_refs,
        "receipt": receipt,
        "persistedVersion": persisted,
        "selected_concern_id": selected_id,
        "retrieved_source_refs": retrieved,
        "auto_recorded_evidence_refs": auto_refs,
        "model_concern_updates": updates,
        "accepted_concern_patches": accepted,
        "rejected_concern_patches": rejected,
        "action_evidence_refs": action_refs,
        "persisted_concern_version": persisted,
        "kind": kind,
        **payload,
    }
    _jsonl_append(path, row)


class OneProviderCallGateway:
    """Allow exactly one real request; later loop attempts are blocked locally."""

    def __init__(self, delegate: Any, http_gateway: Any, preflight_path: pathlib.Path, *, max_output_tokens: int):
        self.delegate = delegate
        self.http_gateway = http_gateway
        self.preflight_path = preflight_path
        self.max_output_tokens = int(max_output_tokens)
        self.model_name = delegate.model_name
        self.invocations = 0
        self.blocked_secondary = 0

    def complete(self, prompt: dict[str, Any], *, attempt: int = 1) -> ProviderResponse:
        self.invocations += 1
        if self.invocations > 1:
            self.blocked_secondary += 1
            return ProviderResponse(
                request_id=str(uuid.uuid4()),
                model=self.model_name,
                content={},
                finish_reason="error",
                usage=None,
                error="secondary_call_blocked",
                http_status=429,
            )
        payload = json.dumps(self.http_gateway._payload(prompt, attempt), ensure_ascii=False).encode("utf-8")
        worst_cny = _estimate_cny(payload, self.max_output_tokens)
        preflight = {
            "status": "passed" if worst_cny <= NEW_CALL_CNY_LIMIT and PRIOR_OBSERVED_CNY + worst_cny <= TOTAL_CNY_LIMIT else "blocked",
            "provider_calls_before": 0,
            "max_output_tokens": self.max_output_tokens,
            "payload_bytes": len(payload),
            "estimated_input_tokens_upper_bound": len(payload),
            "worst_case_new_call_cny_at_safety_rate": worst_cny,
            "prior_observed_cny": PRIOR_OBSERVED_CNY,
            "worst_case_cumulative_cny_at_safety_rate": PRIOR_OBSERVED_CNY + worst_cny,
            "limits": {"new_call_cny": NEW_CALL_CNY_LIMIT, "cumulative_cny": TOTAL_CNY_LIMIT},
            "model": self.model_name,
        }
        _write_json(self.preflight_path, preflight)
        if preflight["status"] != "passed":
            return ProviderResponse(
                request_id=str(uuid.uuid4()), model=self.model_name, content={},
                finish_reason="error", usage=None, error="preflight_cost_limit", http_status=429,
            )
        return self.delegate.complete(prompt, attempt=attempt)


def _new_source_result(raw: dict[str, Any], source_ref: str, items: list[dict[str, Any]], version: str) -> dict[str, Any]:
    """Keep only the runtime-returned rows bound to the new source."""
    result = dict(raw)
    result["data"] = copy.deepcopy(items)
    result["source_refs"] = [source_ref]
    result["version"] = version
    return validate_tool_result(result)


def _event_from_case(case: dict[str, Any], *, concern_id: str, continuation_meta: dict[str, Any]) -> dict[str, Any]:
    spec = next(item for item in case["events"] if item.get("event_role") == "follow-up")
    payload = copy.deepcopy(spec["payload"])
    payload["concern_ref"] = concern_id
    payload["continuation_equivalent"] = continuation_meta
    return {
        "event_id": "K12:continuation-equivalent-follow-up",
        "owner": OWNER,
        "kind": "user_message",
        "virtual_time": spec["virtual_time"],
        "payload": payload,
    }


def run(*, run_root: pathlib.Path, production_root: pathlib.Path, output_root: pathlib.Path | None,
        prior_observed_cny: float = PRIOR_OBSERVED_CNY) -> dict[str, Any]:
    if output_root is None:
        output_root = pathlib.Path(tempfile.mkdtemp(prefix="xiyu-k12-continuation-"))
    output_root = output_root.resolve()
    if output_root.exists():
        return {"status": "blocked", "reason": "refusing to overwrite existing output root", "output_root": str(output_root), "provider_calls": 0}
    output_root.mkdir(parents=True)
    trajectory = output_root / "trajectory"
    trajectory.mkdir()
    trace_path = trajectory / "traces" / "trace.jsonl"
    sink_path = trajectory / "traces" / "sink.jsonl"
    case_manifest = _read_json(run_root / "case-manifest.json", {})
    case = next((item for item in case_manifest.get("cases", []) if item.get("case_id") == "K12"), None)
    if not case:
        return {"status": "blocked", "reason": "K12 is not materialized in the frozen manifest", "provider_calls": 0}
    production_before = _production_fingerprint(production_root)
    snapshot_root, manifest_path, initial_interventions = _materialize_trajectory(run_root, trajectory, case, 1)
    records_path = snapshot_root / "workbench-data" / "runtime-state" / "records.json"
    records_before = _read_json(records_path, {})
    old_row = next(row for row in records_before.get("data", []) if row.get("id") == "WR-20260815-ZHONGYING")
    source_intervention = next(item for item in case["interventions"] if item.get("operation") == "materialize_experimental_record_update")
    materialized_intervention = _apply_intervention(snapshot_root, source_intervention, media_available=None)
    _refresh_trajectory_manifest(snapshot_root, manifest_path)
    trajectory_manifest = _read_json(manifest_path, {})
    fixture_input_binding = copy.deepcopy(trajectory_manifest.get("fixture_input_binding") or {})
    fixture_input_binding["trajectory_manifest_sha256"] = _file_sha(manifest_path)
    fixture_input_binding["trajectory_manifest_path"] = str(manifest_path)
    records_after = _read_json(records_path, {})
    new_row = next(row for row in records_after.get("data", []) if row.get("id") == old_row.get("id"))
    source_ref = str(source_intervention["source_ref"])
    new_version = str(new_row.get("sourceRevision") or source_intervention.get("new_value"))

    store = EventStore(trajectory / "state.db")
    retrieve_event_id = "K12:continuation-equivalent-retrieve"
    retrieval_action_id: str | None = None
    concern_id: str | None = None
    old_concern: dict[str, Any] | None = None
    retrieved_result: dict[str, Any] | None = None
    persisted_version: int | None = None
    try:
        store.configure_budget(OWNER, reset=True)
        store.seed_tasks(OWNER, _read_json(snapshot_root / "context.json", {}).get("owners", {}).get(OWNER, {}).get("tasks", []))
        _seed = _seed_capacity(store, "K12")
        seed_entry = next(item for item in _seed["accepted"] if item.get("concern_ref") == "capacity-seed-12")
        concern_id = str(seed_entry["concern_id"])
        old_concern = store.get_concern(OWNER, concern_id)
        if old_concern is None:
            raise RuntimeError("seeded K12 concern not found")

        adapter = LocalAdapters(snapshot_root=snapshot_root, manifest_path=manifest_path, store=store, concerns_enabled=True)
        raw_retrieval = validate_tool_result(adapter.execute(OWNER, "knowledge.search", {"store_name": new_row.get("venue"), "metric": "reception_traffic"}))
        new_items = [item for item in (raw_retrieval.get("data") or []) if isinstance(item, dict) and item.get("source_ref") == source_ref]
        if not new_items:
            raise RuntimeError("materialized new source was not returned by knowledge.search")
        retrieved_result = _new_source_result(raw_retrieval, source_ref, new_items, new_version)
        retrieval_intention_id = store.create_intention(OWNER, store.ensure_thread(OWNER, {"fixture": "K12-continuation-equivalent"})[0], "读取新版本中影经营证据", False, concern_id=concern_id, concern_version=old_concern["version"])
        retrieval_action_id = store.create_action(OWNER, retrieval_intention_id, retrieve_event_id, "knowledge.search", {"store_name": new_row.get("venue"), "metric": "reception_traffic"}, 0)
        store.record_tool(OWNER, retrieval_action_id, {"store_name": new_row.get("venue"), "metric": "reception_traffic"}, {"store_name": new_row.get("venue"), "metric": "reception_traffic"}, {"changed": False}, retrieved_result)
        with store.transaction():
            store.update_action(retrieval_action_id, OWNER, "prepared", retrieved_result)
            persisted_version = store.record_concern_tool_evidence(OWNER, concern_id, retrieve_event_id, retrieval_action_id, tool_type="knowledge.search", result=retrieved_result)
            store.update_intention(retrieval_intention_id, OWNER, 0, "completed", False)
        after_evidence = store.get_concern(OWNER, concern_id)
        if after_evidence is None or persisted_version is None or persisted_version <= int(old_concern["version"]):
            raise RuntimeError("new evidence did not persist a concern version")

        old_core = old_row.get("core") or {}
        new_core = new_row.get("core") or {}
        delta = {
            metric: {"old": old_core.get(metric), "new": new_core.get(metric)}
            for metric in ("reception_traffic", "box_office_total")
            if old_core.get(metric) != new_core.get(metric)
        }
        continuation_meta = {
            "mode": "evidence_already_retrieved",
            "single_provider_call": True,
            "selectedConcernId": concern_id,
            "newEvidence": {
                "source_ref": source_ref,
                "version": new_version,
                "retrieved": True,
                "facts": [
                    f"{item.get('store_name') or item.get('store') or new_row.get('venue')} {item.get('metric')}={item.get('value')}"
                    for item in new_items
                    if item.get("metric") in {"reception_traffic", "box_office_total"}
                ],
            },
            "oldJudgment": {"concern_version": old_concern["version"], "desired_direction": old_concern["desired_direction"], "next_review_condition": old_concern["next_review_condition"], "known_summary": old_concern.get("known_summary", [])},
            "newEvidenceDifference": delta,
            "outputRequirements": {
                "action": "deliver",
                "do_not_call_tools": True,
                "messages_max": 2,
                "messages_short": True,
                "must_consume_new_source": source_ref,
                "if_direction_changed_submit_one_update": sorted(EXPECTED_FIELDS),
                "update_basis_must_include": source_ref,
            },
        }
        continuation_event = _event_from_case(case, concern_id=concern_id, continuation_meta=continuation_meta)
        pre_model_state = _concern_snapshot(after_evidence)
        _record_trace(trace_path, event_id=retrieve_event_id, kind="tool_result", selected_id=concern_id, retrieved=[source_ref], auto_refs=[], updates=[], accepted=[], rejected=[], action_refs=[source_ref], receipt=None, persisted=persisted_version, step=4, result=retrieved_result, source_intervention=materialized_intervention, fixture_input_binding=fixture_input_binding)
        _record_trace(trace_path, event_id=retrieve_event_id, kind="auto_evidence_persisted", selected_id=concern_id, retrieved=[source_ref], auto_refs=[source_ref], updates=[], accepted=[], rejected=[], action_refs=[source_ref], receipt=None, persisted=persisted_version, evidence_version=new_version, fixture_input_binding=fixture_input_binding)
        store.close()
        store = EventStore(trajectory / "state.db")
        reopened_state = _concern_snapshot(store.get_concern(OWNER, concern_id))
        _record_trace(trace_path, event_id=retrieve_event_id, kind="restart_reopen", selected_id=concern_id, retrieved=[source_ref], auto_refs=[source_ref], updates=[], accepted=[], rejected=[], action_refs=[source_ref], receipt=None, persisted=reopened_state.get("version"), same_version=pre_model_state.get("version") == reopened_state.get("version"), fixture_input_binding=fixture_input_binding)

        binding, _effective = resolve_production_text_binding(production_root=production_root)
        endpoint = str(binding.endpoint or "")
        from urllib.parse import urlsplit
        parsed = urlsplit(endpoint)
        if not (binding.ready and str(binding.provider) == "deepseek" and str(binding.model) == "deepseek-chat" and parsed.hostname == "api.deepseek.com" and parsed.path == "/v1/chat/completions"):
            return {"status": "blocked", "reason": "effective binding is not deepseek/deepseek-chat", "provider_calls": 0, "output_root": str(output_root)}

        # Construct a prompt preview from the reopened state to price the
        # exact structured continuation input before the provider request.
        context_builder_preview = ContextBuilder(snapshot_root=snapshot_root, prompt_path=pathlib.Path(case_manifest.get("arms", {}).get("C", {}).get("prompt_path") or run_root / "missing-prompt.json"), manifest_path=manifest_path, store=store, concerns_enabled=True)
        preview_context = context_builder_preview.build_compact_continuation(continuation_event, thread_state=dict(store.get_thread(OWNER) or {}))
        prompt_path = pathlib.Path(case_manifest.get("arms", {}).get("C", {}).get("prompt_path") or "")
        if not prompt_path.exists():
            prompt_path = pathlib.Path(_read_json(run_root / "manifest.json", {}).get("prompt_path") or "")
        if not prompt_path.exists():
            raise RuntimeError("C prompt path is not materialized")
        prompt_preview = assemble_compact_continuation(preview_context)
        http_preview = build_text_gateway(binding, network_boundary=NetworkBoundary({parsed.hostname or ""}, {parsed.path}), max_output_tokens=256)
        estimates: list[dict[str, Any]] = []
        # R5 alternative A: keep the R4 compact prompt and formal contract,
        # changing only the response ceiling to leave room for a closed JSON.
        for candidate_tokens in (512,):
            candidate_gateway = build_text_gateway(binding, network_boundary=NetworkBoundary({parsed.hostname or ""}, {parsed.path}), max_output_tokens=candidate_tokens)
            candidate_payload = json.dumps(candidate_gateway._payload(prompt_preview, 1), ensure_ascii=False).encode("utf-8")
            candidate_cny = _estimate_cny(candidate_payload, candidate_tokens)
            estimates.append({"max_output_tokens": candidate_tokens, "payload_bytes": len(candidate_payload), "estimated_input_tokens_upper_bound": len(candidate_payload), "worst_case_new_call_cny_at_safety_rate": candidate_cny, "worst_case_cumulative_cny_at_safety_rate": prior_observed_cny + candidate_cny, "within_limits": candidate_cny <= NEW_CALL_CNY_LIMIT and prior_observed_cny + candidate_cny <= TOTAL_CNY_LIMIT})
        selected_tokens = next((item["max_output_tokens"] for item in estimates if item["within_limits"]), None)
        _write_json(output_root / "cost-preflight-candidates.json", {"status": "passed" if selected_tokens else "blocked", "candidates": estimates, "preferred": 512, "prior_observed_cny": prior_observed_cny})
        if selected_tokens is None:
            return {"status": "blocked", "reason": "512 token preflight exceeds limits", "provider_calls": 0, "output_root": str(output_root), "cost_candidates": estimates}

        http_gateway = build_text_gateway(binding, network_boundary=NetworkBoundary({parsed.hostname or ""}, {parsed.path}), max_output_tokens=selected_tokens)
        remaining = min(NEW_CALL_CNY_LIMIT, max(0.0, TOTAL_CNY_LIMIT - prior_observed_cny))
        spend_guard = SpendGuard(max_budget_cny=remaining, cny_per_usd_ceiling=10.0, max_output_tokens=selected_tokens)
        budget_gateway = type("BudgetGateway", (), {})()
        # Reuse the existing bounded gateway implementation without adding a
        # second transport.  Importing here keeps the preflight phase local.
        from evaluation.local_semantic_smoke import LocalBudgetGateway
        gateway_delegate = LocalBudgetGateway(http_gateway, spend_guard, [])
        one_shot = OneProviderCallGateway(gateway_delegate, http_gateway, output_root / "provider-preflight.json", max_output_tokens=selected_tokens)
        sink_audit: dict[str, Any] = {"outboundCalls": 0, "visibleResponses": []}
        sink = NoOpSink(sink_path, sink_audit)
        policy = Policy(store, writable_root=trajectory, concerns_enabled=True)
        context_builder = ContextBuilder(snapshot_root=snapshot_root, prompt_path=prompt_path, manifest_path=manifest_path, store=store, concerns_enabled=True)
        loop = AgencyLoop(store=store, context=context_builder, adapters=LocalAdapters(snapshot_root=snapshot_root, manifest_path=manifest_path, store=store, concerns_enabled=True), policy=policy, gateway=one_shot, sink=sink, trace_path=trace_path)
        result = loop.process_event(continuation_event)
        store.close()
        store = EventStore(trajectory / "state.db")
        final_concern = store.get_concern(OWNER, concern_id)
        traces = []
        if trace_path.exists():
            for line in trace_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        traces.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        accepted = [row.get("acceptedConcernPatches") or [] for row in traces]
        accepted_flat = [patch for group in accepted for patch in group if isinstance(patch, dict)]
        model_updates = [row.get("modelConcernUpdates") or [] for row in traces]
        updates_flat = [patch for group in model_updates for patch in group if isinstance(patch, dict)]
        accepted_fields = {field for patch in updates_flat for field in (patch.get("changes") or {})}
        semantic_parse_row = next((row for row in traces if row.get("kind") == "semantic_proposal_parse"), {})
        semantic_compiled_row = next((row for row in traces if row.get("kind") == "semantic_proposal_compiled"), {})
        semantic_proposal = semantic_compiled_row.get("validated_proposal") or {}
        semantic_delta = semantic_proposal.get("semantic_delta") if isinstance(semantic_proposal, dict) else {}
        semantic_evidence_refs = semantic_proposal.get("evidence_refs") if isinstance(semantic_proposal, dict) else []
        semantic_proposal_valid = semantic_parse_row.get("validation_result") == "passed" and bool(semantic_proposal)
        semantic_delta_valid = (
            isinstance(semantic_delta, dict)
            and semantic_delta.get("kind") == "update"
            and semantic_delta.get("field") in EXPECTED_FIELDS
        )
        semantic_evidence_exact = isinstance(semantic_evidence_refs, list) and set(semantic_evidence_refs) == {source_ref}
        compiled_patch = semantic_compiled_row.get("compiled_concern_patch")
        messages = [row.get("attempt", {}).get("payload", {}).get("text") for row in _read_jsonl(sink_path) if row.get("kind") == "noop_sink_attempt"]
        source_consumed = any(source_ref in json.dumps(item, ensure_ascii=False) for item in traces + [result])
        source_in_visible = any("201" in str(message) for message in messages)
        source_in_basis = any(source_ref in json.dumps(item, ensure_ascii=False) for item in updates_flat + [{"basis_refs": []}])
        status = "passed" if (
            result.get("status") in {"unknown", "delivered"}
            and one_shot.invocations == 1
            and one_shot.blocked_secondary == 0
            and sink_audit.get("outboundCalls") == 0
            and source_consumed
            and source_in_visible
            and source_in_basis
            and semantic_proposal_valid
            and semantic_delta_valid
            and semantic_evidence_exact
            and isinstance(compiled_patch, dict)
            and compiled_patch.get("concern_ref") == concern_id
            and int(compiled_patch.get("expected_version", -1)) == int(pre_model_state.get("version", -1))
            and bool(EXPECTED_FIELDS & accepted_fields)
            and bool(accepted_flat)
            and final_concern is not None
            and int(final_concern.get("version", 0)) > int(pre_model_state.get("version", 0))
        ) else "failed"
        after_production = _production_fingerprint(production_root)
        budget_snapshot = spend_guard.snapshot()
        actual_new_cny = float(budget_snapshot.get("actual_usage_spent_cny_at_safety_rate") or 0.0)
        total_actual_cny = prior_observed_cny + actual_new_cny
        artifact = {
            "schemaVersion": "k12-continuation-equivalent-smoke-v1",
            "status": status,
            "execution_scope": "continuation_equivalent_single_provider_call",
            "run_root": str(run_root),
            "output_root": str(output_root),
            "trajectory": str(trajectory),
            "case_id": "K12",
            "provider": {"provider": binding.provider, "model": binding.model, "endpoint_host": parsed.hostname, "endpoint_path": parsed.path, "credential_value_recorded": False},
            "provider_calls": int(budget_snapshot.get("provider_calls", 0)),
            "gateway_invocations": one_shot.invocations,
            "blocked_secondary_attempts": one_shot.blocked_secondary,
            "cost_preflight": {"selected_max_output_tokens": selected_tokens, "candidates": estimates, "actual_new_call_cny_at_safety_rate": actual_new_cny, "prior_observed_cny": prior_observed_cny, "total_actual_cny_at_safety_rate": total_actual_cny},
            "materialization": {"intervention": materialized_intervention, "old_row_core": old_core, "new_row_core": new_core, "source_ref": source_ref, "source_version": new_version},
            "state": {"selected_concern_id": concern_id, "old_concern": _concern_snapshot(old_concern), "after_evidence": pre_model_state, "reopened": reopened_state, "final": _concern_snapshot(final_concern), "persisted_evidence_version": persisted_version},
            "retrieval": {"raw_status": raw_retrieval.get("status") if retrieved_result else None, "filtered_status": retrieved_result.get("status") if retrieved_result else None, "source_refs": retrieved_result.get("source_refs", []) if retrieved_result else [], "rows": retrieved_result.get("data", []) if retrieved_result else []},
            "model": {"request_id": next((row.get("request_id") for row in traces if row.get("kind") == "provider_call"), None), "raw_response": next((row.get("raw_response") for row in traces if row.get("kind") == "provider_call"), None), "semantic_proposal": {"raw": semantic_parse_row.get("raw_response"), "validated": semantic_proposal, "parse_audit": semantic_parse_row.get("parse_audit"), "compiled_patch": compiled_patch, "compiled_decision": semantic_compiled_row.get("decision")}, "parse_audit": next((row.get("parse_audit") for row in traces if row.get("kind") == "decision_parse"), None)},
            "acceptance": {"strict_parser_valid": semantic_proposal_valid, "semantic_proposal_valid": semantic_proposal_valid, "semantic_delta_valid": semantic_delta_valid, "semantic_evidence_refs_exact": semantic_evidence_exact, "compiled_patch_injected": isinstance(compiled_patch, dict) and compiled_patch.get("concern_ref") == concern_id and int(compiled_patch.get("expected_version", -1)) == int(pre_model_state.get("version", -1)), "source_consumed_by_trace": source_consumed, "new_source_in_visible_response": source_in_visible, "new_source_in_patch_basis": source_in_basis, "accepted_patch_fields": sorted(accepted_fields), "expected_patch_fields": sorted(EXPECTED_FIELDS), "accepted_semantic_patch_persisted": bool(EXPECTED_FIELDS & accepted_fields) and bool(accepted_flat) and final_concern is not None and int(final_concern.get("version", 0)) > int(pre_model_state.get("version", 0)), "outboundCalls": sink_audit.get("outboundCalls", 0), "production_unchanged": production_before == after_production, "result": result, "visible_messages": messages},
            "trace": {"path": str(trace_path), "count": len(traces), "required_fields_present": all(all(field in row for field in ("selectedConcernId", "retrievedSourceRefs", "autoRecordedEvidenceRefs", "modelConcernUpdates", "acceptedConcernPatches", "rejectedConcernPatches", "actionEvidenceRefs", "receipt", "persistedVersion")) for row in traces)},
            "no_real_bot": True,
            "production_writes": 0,
        }
        _write_json(output_root / "continuation-equivalent-smoke.json", artifact)
        return artifact
    except Exception as exc:
        artifact = {"schemaVersion": "k12-continuation-equivalent-smoke-v1", "status": "failed", "execution_scope": "continuation_equivalent_single_provider_call", "output_root": str(output_root), "provider_calls": 0, "error": {"type": type(exc).__name__, "message": str(exc)}}
        _write_json(output_root / "continuation-equivalent-smoke.json", artifact)
        return artifact
    finally:
        try:
            store.close()
        except Exception:
            pass


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--production-root", default="E:/FoxSpirit/xiyu-ai")
    parser.add_argument("--output-root")
    parser.add_argument("--prior-observed-cny", type=float, default=PRIOR_OBSERVED_CNY)
    args = parser.parse_args()
    result = run(run_root=pathlib.Path(args.run_root).resolve(), production_root=pathlib.Path(args.production_root).resolve(), output_root=pathlib.Path(args.output_root).resolve() if args.output_root else None, prior_observed_cny=args.prior_observed_cny)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
