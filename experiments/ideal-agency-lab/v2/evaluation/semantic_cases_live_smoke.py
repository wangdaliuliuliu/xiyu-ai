"""Bounded live semantic checks for the R9 K08/K10 concern cases.

The runner deliberately exercises one compact DeepSeek decision for each of
K08 and K10.  Fixture materialization, local knowledge retrieval,
evidence persistence, CAS compilation and the no-op delivery sink all remain
the normal v2 runtime path.  The provider is the only live dependency.
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
from urllib.parse import urlsplit


V2_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(V2_ROOT) not in sys.path:
    sys.path.insert(0, str(V2_ROOT))

from adapters.local import LocalAdapters
from contracts.schemas import validate_tool_result
from controller.boundary import NetworkBoundary
from controller.gateway import ProviderResponse
from controller.provider_config import build_text_gateway, resolve_production_text_binding
from controller.worker_gateway import SpendGuard
from evaluation.concern_cases import SEMANTIC_DELTA_EVALUATION_REGISTRY
from evaluation.continuation_equivalent_smoke import (
    _concern_snapshot,
    _estimate_cny,
    _new_source_result,
    _record_trace,
)
from evaluation.j05_simulation import (
    OWNER,
    _apply_intervention,
    _file_sha,
    _materialize_trajectory,
    _read_json,
    _refresh_trajectory_manifest,
    _write_json,
)
from evaluation.local_semantic_smoke import _production_fingerprint
from evaluation.semantic_delta import audit_semantic_delta
from runtime.context import ContextBuilder
from runtime.loop import AgencyLoop
from runtime.policy import Policy
from runtime.prompts.assemble import assemble_compact_continuation
from runtime.store import EventStore
from transport.sink import NoOpSink


PRIOR_OBSERVED_CNY = 4.43681832
TOTAL_CNY_LIMIT = 4.95
R9_NEW_CALL_CNY_LIMIT = 0.20
MAX_OUTPUT_TOKENS = 512
CASE_ORDER = ("K08", "K10")


# The event text is copied from the frozen manifest.  The source reference is
# resolved from the local adapter result, so the provider can only see a
# source that the isolated knowledge path actually returned.
CASE_CONFIG: dict[str, dict[str, Any]] = {
    "K04": {
        "event_role": "boundary-or-result",
        "store_name": "东坝",
        "metric": "box_office",
        "revision": "9754",
        "initial_title": "东坝资料版本续接",
        "initial_direction": "资料有变化后继续核对东坝经营数据",
        "initial_summary": "旧版东坝资料等待新来源版本后再继续核对",
        "initial_unknown": "新来源版本是否已到达",
        "initial_condition": {"type": "new_source_version", "version": "9754"},
        "difference": {"source_revision": {"old": "9753", "new": "9754"}},
        "expected_message_markers": ("东坝", "9754"),
    },
    "K08": {
        "event_role": "boundary-or-result",
        "store_name": "中影",
        "metric": "reception_traffic",
        "revision": "9753",
        "initial_title": "中影与科技馆关联复核",
        "initial_direction": "核对中影与科技馆客流是否存在可验证关联",
        "initial_summary": "原有关联判断尚未完成，当前只有中影的一项客流资料",
        "initial_unknown": "科技馆对应的同口径资料尚未到达",
        "initial_condition": {"type": "new_source_version", "version": "after-9753"},
        "difference": {
            "goal_change": {"old": "关联判断", "new": "先核对客流口径"},
            "evidence_gap": {"old": "可继续探索", "new": "新材料到达前暂停旧关联判断"},
        },
        "expected_message_markers": ("中影",),
    },
    "K10": {
        "event_role": "follow-up",
        "store_name": "东坝",
        "metric": "traffic",
        "business_date": "2026-08-21",
        "revision": "9754",
        "initial_title": "东坝客流字段口径复核",
        "initial_direction": "按来源分别核对东坝两个客流字段",
        "initial_summary": "旧版表中两个客流字段的来源边界需要复核",
        "initial_unknown": "两个客流字段是否来自同一来源口径",
        "initial_condition": {"type": "new_source_version", "version": "9754"},
        "difference": {
            "source_revision": {"old": "9753", "new": "9754"},
            "field_boundary": {"old": "两个客流字段未区分", "new": "按各自列分开核对"},
        },
        "expected_message_markers": ("东坝",),
    },
}


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _jsonl(path: pathlib.Path) -> list[dict[str, Any]]:
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


def _record_source_ref(row: dict[str, Any], revision: str) -> str | None:
    refs = row.get("source_refs") or row.get("sourceRefs") or []
    candidates = [str(ref) for ref in refs if isinstance(ref, str) and f"/revision/{revision}/" in ref]
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        if ref.get("sourceRef") and f"/revision/{revision}/" in str(ref["sourceRef"]):
            candidates.append(str(ref["sourceRef"]))
        elif ref.get("spreadsheetToken") and ref.get("revision") is not None and str(ref.get("revision")) == str(revision):
            sheet = ref.get("sheet") or "workbench"
            candidates.append(f"feishu://{ref['spreadsheetToken']}/revision/{ref['revision']}/{sheet}")
    return candidates[0] if candidates else None


def _case_event(case: dict[str, Any], role: str) -> dict[str, Any]:
    spec = next(item for item in case["events"] if item.get("event_role") == role)
    return copy.deepcopy(spec)


def _source_version(ref: str, fallback: str) -> str:
    parts = ref.split("/revision/", 1)
    if len(parts) == 2:
        return parts[1].split("/", 1)[0] or fallback
    return fallback


def _make_initial_concern(store: EventStore, case_id: str, cfg: dict[str, Any], old_ref: str) -> tuple[str, dict[str, Any]]:
    evidence = {
        "source_ref": old_ref,
        "epistemic_status": "observed",
        "kind": "frozen_workbench_record",
        "summary": cfg["initial_summary"],
    }
    unknown = {
        "source_ref": old_ref,
        "epistemic_status": "unknown",
        "kind": "source_gap",
        "summary": cfg["initial_unknown"],
        "impact": "当前无法把旧判断作为已验证结论继续使用",
    }
    condition = copy.deepcopy(cfg["initial_condition"])
    condition["source_ref"] = old_ref
    update = {
        "operation": "create",
        "concern_ref": f"r8-{case_id.lower()}-concern",
        "expected_version": None,
        "basis_refs": [evidence],
        "changes": {
            "title": cfg["initial_title"],
            "desired_direction": cfg["initial_direction"],
            "domain": "work",
            "origin": "observed_gap",
            "desire_refs": ["work_trust"],
            "known_summary": [evidence],
            "unknowns": [unknown],
            "next_review_condition": condition,
        },
    }
    with store.transaction():
        result = store.apply_concern_updates(OWNER, f"fixture:r9:{case_id}:seed", [update], max_active=12)
    accepted = result.get("accepted") or []
    if not accepted:
        raise RuntimeError(f"initial concern seed rejected: {result}")
    concern_id = str(accepted[0]["concern_id"])
    concern = store.get_concern(OWNER, concern_id)
    if concern is None:
        raise RuntimeError("initial concern was not persisted")
    return concern_id, concern


def _facts(items: list[dict[str, Any]], label: str) -> list[str]:
    facts: list[str] = []
    for item in items:
        if item.get("metric") is None or "value" not in item:
            continue
        date = f" {item.get('business_date')}" if item.get("business_date") else ""
        value = f"{label}{date} {item.get('metric')}={item.get('value')}"
        if value not in facts:
            facts.append(value)
    return facts[:6]


def _initial_trace(trace_path: pathlib.Path, case_id: str, concern_id: str, source_ref: str, persisted: int, result: dict[str, Any], binding: dict[str, Any]) -> None:
    event_id = f"R9:{case_id}:retrieval"
    _record_trace(
        trace_path,
        event_id=event_id,
        kind="tool_result",
        selected_id=concern_id,
        retrieved=[source_ref],
        auto_refs=[],
        updates=[],
        accepted=[],
        rejected=[],
        action_refs=[source_ref],
        receipt=None,
        persisted=persisted,
        step=4,
        result=result,
        fixture_input_binding=binding,
    )
    _record_trace(
        trace_path,
        event_id=event_id,
        kind="auto_evidence_persisted",
        selected_id=concern_id,
        retrieved=[source_ref],
        auto_refs=[source_ref],
        updates=[],
        accepted=[],
        rejected=[],
        action_refs=[source_ref],
        receipt=None,
        persisted=persisted,
        evidence_version=result.get("version"),
        fixture_input_binding=binding,
    )


class SingleProviderCallGateway:
    """Fail closed if the loop tries to spend a second call for one case."""

    def __init__(self, delegate: Any):
        self.delegate = delegate
        self.model_name = delegate.model_name
        self.invocations = 0
        self.blocked_secondary = 0

    def complete(self, prompt: dict[str, Any], *, attempt: int = 1) -> ProviderResponse:
        self.invocations += 1
        if self.invocations > 1:
            self.blocked_secondary += 1
            return ProviderResponse(
                str(uuid.uuid4()), self.model_name, {}, finish_reason="error",
                usage=None, error="secondary_call_blocked", http_status=429,
            )
        return self.delegate.complete(prompt, attempt=attempt)


def _prepare_case(run_root: pathlib.Path, output_root: pathlib.Path, case: dict[str, Any], production_root: pathlib.Path) -> dict[str, Any]:
    case_id = str(case["case_id"])
    cfg = CASE_CONFIG[case_id]
    trajectory = output_root / "trajectories" / case_id
    trajectory.mkdir(parents=True, exist_ok=False)
    snapshot_root, manifest_path, initial_interventions = _materialize_trajectory(run_root, trajectory, case, 1, arm="C")
    for intervention in case.get("interventions", []):
        if int(intervention.get("at_event", -1)) == int(next(item for item in case["events"] if item.get("event_role") == cfg["event_role"])["event_index"]):
            _apply_intervention(snapshot_root, intervention)
            _refresh_trajectory_manifest(snapshot_root, manifest_path)

    records = _read_json(snapshot_root / "workbench-data" / "runtime-state" / "records.json", {})
    row = next((item for item in records.get("data", []) if item.get("venue") == cfg["store_name"] and item.get("sourceRefs") and (not cfg.get("business_date") or any(day.get("date") == cfg["business_date"] for day in item.get("daily", [])))), None)
    if row is None:
        raise RuntimeError(f"fixture record is missing for {case_id}")
    source_ref = _record_source_ref(row, cfg["revision"])
    if not source_ref:
        raise RuntimeError(f"fixture source revision {cfg['revision']} is missing for {case_id}")
    old_ref = source_ref.replace(f"/revision/{cfg['revision']}/", "/revision/9753/")

    store = EventStore(trajectory / "state.db")
    store.configure_budget(OWNER, reset=True)
    store.seed_tasks(OWNER, _read_json(snapshot_root / "context.json", {}).get("owners", {}).get(OWNER, {}).get("tasks", []))
    thread_id, _ = store.ensure_thread(OWNER, {"owner": OWNER, "fixture": _read_json(snapshot_root / "context.json", {}).get("schemaVersion")})
    concern_id, old_concern = _make_initial_concern(store, case_id, cfg, old_ref)
    adapter = LocalAdapters(snapshot_root=snapshot_root, manifest_path=manifest_path, store=store, concerns_enabled=True)
    args: dict[str, Any] = {"store_name": cfg["store_name"], "metric": cfg["metric"]}
    if cfg.get("business_date"):
        args["business_date"] = cfg["business_date"]
    raw_retrieval = validate_tool_result(adapter.execute(OWNER, "knowledge.search", args))
    items = [item for item in (raw_retrieval.get("data") or []) if isinstance(item, dict) and item.get("source_ref") == source_ref]
    if not items:
        raise RuntimeError(f"knowledge.search did not return source-bound rows for {case_id}: {source_ref}")
    version = _source_version(source_ref, cfg["revision"])
    retrieved = _new_source_result(raw_retrieval, source_ref, items, version)
    retrieve_event_id = f"R9:{case_id}:retrieval"
    intention_id = store.create_intention(OWNER, thread_id, f"读取{cfg['store_name']}经营证据", False, concern_id=concern_id, concern_version=old_concern["version"])
    action_id = store.create_action(OWNER, intention_id, retrieve_event_id, "knowledge.search", args, 0)
    store.record_tool(OWNER, action_id, args, args, {"changed": False}, retrieved)
    with store.transaction():
        store.update_action(action_id, OWNER, "prepared", retrieved)
        persisted_version = store.record_concern_tool_evidence(OWNER, concern_id, retrieve_event_id, action_id, tool_type="knowledge.search", result=retrieved)
        store.update_intention(intention_id, OWNER, 0, "completed", False)
    after_evidence = store.get_concern(OWNER, concern_id)
    if after_evidence is None or int(after_evidence["version"]) <= int(old_concern["version"]):
        raise RuntimeError(f"source evidence did not advance concern version for {case_id}")
    pre_model_state = _concern_snapshot(after_evidence)
    store.close()
    store = EventStore(trajectory / "state.db")
    reopened = store.get_concern(OWNER, concern_id)
    if reopened is None or reopened.get("version") != pre_model_state.get("version"):
        raise RuntimeError(f"reopen lost evidence version for {case_id}")

    case_manifest = _read_json(run_root / "case-manifest.json", {})
    prompt_path = pathlib.Path((case_manifest.get("arms") or {}).get("C", {}).get("prompt_path") or "")
    if not prompt_path.exists():
        raise RuntimeError("declared C prompt is missing")
    target_event = _case_event(case, cfg["event_role"])
    event_payload = copy.deepcopy(target_event.get("payload") or {})
    # K10's fixture opportunity uses a human sheet label while the normalized
    # adapter resolves the authoritative record to its first source ref.  The
    # worker event is bound to the returned ref, never to a guessed alias.
    if target_event.get("kind") == "opportunity":
        event_payload["source_refs"] = [source_ref]
    expected = copy.deepcopy(SEMANTIC_DELTA_EVALUATION_REGISTRY[case_id])
    continuation_meta = {
        "mode": "evidence_already_retrieved",
        "single_provider_call": True,
        "selectedConcernId": concern_id,
        "newEvidence": {"source_ref": source_ref, "version": version, "retrieved": True, "facts": _facts(items, cfg["store_name"])},
        "oldJudgment": {
            "concern_version": old_concern["version"],
            "desired_direction": old_concern["desired_direction"],
            "next_review_condition": old_concern["next_review_condition"],
            "known_summary": old_concern.get("known_summary", []),
        },
        "newEvidenceDifference": copy.deepcopy(cfg["difference"]),
        "outputRequirements": {
            "action": "deliver",
            "do_not_call_tools": True,
            "messages_max": 2,
            "messages_short": True,
            "must_consume_new_source": source_ref,
            "allowed_semantic_targets": list(expected.get("allowed_targets") or []),
            "target_guidance": copy.deepcopy(expected.get("target_guidance") or {}),
            "update_basis_must_include": source_ref,
        },
        "allowedSemanticTargets": list(expected.get("allowed_targets") or []),
        "targetGuidance": copy.deepcopy(expected.get("target_guidance") or {}),
    }
    event_payload["concern_ref"] = concern_id
    event_payload["continuation_equivalent"] = continuation_meta
    event = {
        "event_id": f"R9:{case_id}:semantic-continuation",
        "owner": OWNER,
        "kind": target_event["kind"],
        "virtual_time": target_event["virtual_time"],
        "payload": event_payload,
    }
    context_builder = ContextBuilder(snapshot_root=snapshot_root, prompt_path=prompt_path, manifest_path=manifest_path, store=store, concerns_enabled=True)
    context = context_builder.build_compact_continuation(event, thread_state=dict(store.get_thread(OWNER) or {}))
    prompt = assemble_compact_continuation(context)
    manifest = _read_json(manifest_path, {})
    fixture_binding = copy.deepcopy(manifest.get("fixture_input_binding") or {})
    fixture_binding["trajectory_manifest_sha256"] = _file_sha(manifest_path)
    fixture_binding["trajectory_manifest_path"] = str(manifest_path)
    trace_path = trajectory / "traces" / "trace.jsonl"
    _initial_trace(trace_path, case_id, concern_id, source_ref, int(persisted_version), retrieved, fixture_binding)
    _record_trace(
        trace_path,
        event_id=f"R9:{case_id}:retrieval",
        kind="restart_reopen",
        selected_id=concern_id,
        retrieved=[source_ref],
        auto_refs=[source_ref],
        updates=[],
        accepted=[],
        rejected=[],
        action_refs=[source_ref],
        receipt=None,
        persisted=int(reopened["version"]),
        same_version=True,
        fixture_input_binding=fixture_binding,
    )
    return {
        "case_id": case_id,
        "cfg": cfg,
        "case": case,
        "trajectory": trajectory,
        "snapshot_root": snapshot_root,
        "manifest_path": manifest_path,
        "prompt_path": prompt_path,
        "store": store,
        "concern_id": concern_id,
        "old_concern": old_concern,
        "pre_model_state": pre_model_state,
        "reopened_state": _concern_snapshot(reopened),
        "source_ref": source_ref,
        "old_ref": old_ref,
        "version": version,
        "retrieved": retrieved,
        "event": event,
        "context": context,
        "prompt": prompt,
        "fixture_input_binding": fixture_binding,
        "persisted_version": int(persisted_version),
        "initial_interventions": initial_interventions,
    }


def _trace_acceptance(prepared: dict[str, Any], result: dict[str, Any], gateway: SingleProviderCallGateway, sink_audit: dict[str, Any]) -> dict[str, Any]:
    trajectory = prepared["trajectory"]
    trace_path = trajectory / "traces" / "trace.jsonl"
    traces = _jsonl(trace_path)
    source_ref = prepared["source_ref"]
    case_id = prepared["case_id"]
    proposal_row = next((row for row in reversed(traces) if row.get("kind") == "semantic_proposal_parse"), {})
    compiled_row = next((row for row in reversed(traces) if row.get("kind") == "semantic_proposal_compiled"), {})
    proposal = compiled_row.get("validated_proposal") or {}
    delta = proposal.get("semantic_delta") if isinstance(proposal, dict) else {}
    evidence_refs = proposal.get("evidence_refs") if isinstance(proposal, dict) else []
    accepted = [patch for row in traces for patch in (row.get("acceptedConcernPatches") or []) if isinstance(patch, dict)]
    model_updates = [patch for row in traces for patch in (row.get("modelConcernUpdates") or []) if isinstance(patch, dict)]
    # The accepted record is an acknowledgement containing concern id/version;
    # the field-level changes live in modelConcernUpdates.  Audit both so a
    # valid CAS commit is not misreported as an empty semantic patch.
    accepted_fields = sorted({
        field
        for patch in [*accepted, *model_updates]
        for field in (patch.get("changes") or {})
    })
    compiled_patch = compiled_row.get("compiled_concern_patch")
    store: EventStore = prepared["store"]
    final_concern = store.get_concern(OWNER, prepared["concern_id"])
    objective_case = copy.deepcopy(prepared["case"])
    objective_case["semantic_delta_evaluation"] = copy.deepcopy(SEMANTIC_DELTA_EVALUATION_REGISTRY[case_id])
    semantic_delta = audit_semantic_delta(objective_case, traces)
    raw_messages = _jsonl(trajectory / "traces" / "sink.jsonl")
    messages = [row.get("attempt", {}).get("payload", {}).get("text") for row in raw_messages if row.get("kind") == "noop_sink_attempt"]
    source_in_trace = any(source_ref in json.dumps(row, ensure_ascii=False) for row in traces)
    source_in_visible = any(source_ref in json.dumps(message, ensure_ascii=False) or any(marker in str(message) for marker in prepared["cfg"].get("expected_message_markers", ())) for message in messages)
    objective = SEMANTIC_DELTA_EVALUATION_REGISTRY[case_id]
    expected_fields = set(objective.get("expected_fields") or [])
    expected_targets = set(objective.get("expected_targets") or [])
    allowed_targets = set(objective.get("allowed_targets") or [])
    proposal_target = delta.get("target") if isinstance(delta, dict) else None
    proposal_value = delta.get("value") if isinstance(delta, dict) else None
    target_allowed = proposal_target in allowed_targets
    target_matches_objective = proposal_target in expected_targets
    expected_transition_values = set(objective.get("status_transition_values") or [])
    transition_value_ok = (
        not expected_transition_values
        or proposal_target != "status_transition"
        or proposal_value in expected_transition_values
    )
    matched_fields = expected_fields & set(accepted_fields)
    all_trace_fields = (
        "selectedConcernId", "retrievedSourceRefs", "autoRecordedEvidenceRefs",
        "modelConcernUpdates", "acceptedConcernPatches", "rejectedConcernPatches",
        "actionEvidenceRefs", "receipt", "persistedVersion",
    )
    required_trace_fields = all(all(field in row for field in all_trace_fields) for row in traces)
    provider_result_status = result.get("status")
    patch_ok = isinstance(compiled_patch, dict) and compiled_patch.get("concern_ref") == prepared["concern_id"] and int(compiled_patch.get("expected_version", -1)) == int(prepared["pre_model_state"].get("version", -1))
    persisted_patch = (
        target_matches_objective
        and transition_value_ok
        and isinstance(compiled_patch, dict)
        and final_concern is not None
        and int(final_concern.get("version", 0)) > int(prepared["pre_model_state"].get("version", 0))
    )
    proposal_valid = proposal_row.get("validation_result") == "passed" and bool(proposal)
    evidence_exact = isinstance(evidence_refs, list) and set(evidence_refs) == {source_ref}
    markers_ok = any(marker in str(message) for message in messages for marker in prepared["cfg"].get("expected_message_markers", ()))
    action_type = proposal.get("action") if isinstance(proposal, dict) else None
    response_contract_ok = (
        (provider_result_status in {"unknown", "delivered"} and markers_ok)
        or (
            action_type == "hold"
            and provider_result_status == "waiting"
            and not messages
            and target_matches_objective
            and persisted_patch
        )
    )
    passed = (
        response_contract_ok
        and gateway.invocations == 1
        and gateway.blocked_secondary == 0
        and sink_audit.get("outboundCalls") == 0
        and proposal_valid
        and isinstance(delta, dict)
        and target_allowed
        and target_matches_objective
        and transition_value_ok
        and evidence_exact
        and patch_ok
        and bool(matched_fields)
        and persisted_patch
        and source_in_trace
        and required_trace_fields
        and semantic_delta.get("status") == "passed"
    )
    return {
        "status": "passed" if passed else "failed",
        "provider_result_status": provider_result_status,
        "proposal_valid": proposal_valid,
        "proposal": proposal,
        "semantic_delta": delta,
        "semantic_delta_audit": semantic_delta,
        "evidence_refs_exact": evidence_exact,
        "compiled_patch": compiled_patch,
        "compiled_patch_cas_ok": patch_ok,
        "accepted_fields": accepted_fields,
        "expected_fields": sorted(expected_fields),
        "allowed_targets": sorted(allowed_targets),
        "expected_targets": sorted(expected_targets),
        "proposal_target": proposal_target,
        "proposal_value": proposal_value,
        "proposal_target_allowed": target_allowed,
        "target_matches_objective": target_matches_objective,
        "transition_value_ok": transition_value_ok,
        "accepted_semantic_patch_persisted": persisted_patch,
        "source_consumed_by_trace": source_in_trace,
        "source_in_visible_response": source_in_visible,
        "message_markers_ok": markers_ok,
        "response_contract_ok": response_contract_ok,
        "visible_messages": messages,
        "required_trace_fields_present": required_trace_fields,
        "final_concern": _concern_snapshot(final_concern),
        "provider_invocations": gateway.invocations,
        "blocked_secondary_attempts": gateway.blocked_secondary,
        "outboundCalls": sink_audit.get("outboundCalls", 0),
        "result": result,
        "trace_count": len(traces),
    }


def run(*, run_root: pathlib.Path, production_root: pathlib.Path, output_root: pathlib.Path | None = None, prior_observed_cny: float = PRIOR_OBSERVED_CNY, case_order: tuple[str, ...] | None = None, new_call_cny_limit: float = R9_NEW_CALL_CNY_LIMIT) -> dict[str, Any]:
    selected_case_order = tuple(case_order or CASE_ORDER)
    if output_root is None:
        output_root = pathlib.Path(tempfile.mkdtemp(prefix="xiyu-r8-semantic-live-"))
    output_root = output_root.resolve()
    if output_root.exists():
        return {"status": "blocked", "reason": "refusing to overwrite existing output root", "output_root": str(output_root), "provider_calls": 0}
    output_root.mkdir(parents=True)
    production_before = _production_fingerprint(production_root)
    case_manifest = _read_json(run_root / "case-manifest.json", {})
    cases = {str(item.get("case_id")): item for item in case_manifest.get("cases", []) if isinstance(item, dict)}
    if any(case_id not in cases for case_id in selected_case_order):
        return {"status": "blocked", "reason": "requested cases are not present in the frozen case manifest", "provider_calls": 0, "output_root": str(output_root)}

    binding, _effective = resolve_production_text_binding(production_root=production_root)
    parsed = urlsplit(str(binding.endpoint or ""))
    binding_ok = bool(binding.ready and str(binding.provider) == "deepseek" and str(binding.model) == "deepseek-chat" and parsed.hostname == "api.deepseek.com" and parsed.path == "/v1/chat/completions")
    result: dict[str, Any] = {
        "schemaVersion": "r9-semantic-cases-live-smoke-v1",
        "status": "blocked",
        "execution_scope": "two_case_compact_single_provider_calls",
        "run_root": str(run_root),
        "output_root": str(output_root),
        "case_order": list(selected_case_order),
        "provider": {"provider": binding.provider, "model": binding.model, "endpoint_host": parsed.hostname, "endpoint_path": parsed.path, "binding_ok": binding_ok, "credential_value_recorded": False},
        "budget": {"prior_observed_cny": float(prior_observed_cny), "new_call_cny_limit": float(new_call_cny_limit), "total_cny_limit": TOTAL_CNY_LIMIT, "max_output_tokens": MAX_OUTPUT_TOKENS},
        "production_before": production_before,
        "production_after": None,
        "samples": [],
        "provider_calls": 0,
        "bot_messages": 0,
        "production_writes": 0,
    }
    if not binding_ok:
        result["reason"] = "effective binding is not deepseek/deepseek-chat"
        result["production_after"] = _production_fingerprint(production_root)
        _write_json(output_root / "semantic-cases-live-smoke.json", result)
        return result

    prepared: list[dict[str, Any]] = []
    gateway_audit: list[dict[str, Any]] = []
    try:
        for case_id in selected_case_order:
            prepared.append(_prepare_case(run_root, output_root, cases[case_id], production_root))
        boundary = NetworkBoundary({parsed.hostname or ""}, {parsed.path})
        http_gateway = build_text_gateway(binding, network_boundary=boundary, max_output_tokens=MAX_OUTPUT_TOKENS)
        preflight_cases = []
        for item in prepared:
            payload = json.dumps(http_gateway._payload(item["prompt"], 1), ensure_ascii=False).encode("utf-8")
            worst = _estimate_cny(payload, MAX_OUTPUT_TOKENS)
            preflight_cases.append({"case_id": item["case_id"], "payload_bytes": len(payload), "estimated_input_tokens_upper_bound": len(payload), "max_output_tokens": MAX_OUTPUT_TOKENS, "worst_case_new_call_cny_at_safety_rate": worst})
        worst_total = sum(item["worst_case_new_call_cny_at_safety_rate"] for item in preflight_cases)
        preflight = {
            "status": "passed" if worst_total <= new_call_cny_limit and prior_observed_cny + worst_total <= TOTAL_CNY_LIMIT else "blocked",
            "cases": preflight_cases,
            "worst_case_new_calls_cny_at_safety_rate": worst_total,
            "worst_case_cumulative_cny_at_safety_rate": prior_observed_cny + worst_total,
            "limits": {"new_calls_cny": new_call_cny_limit, "cumulative_cny": TOTAL_CNY_LIMIT},
            "provider_calls_before": 0,
        }
        _write_json(output_root / "cost-preflight.json", preflight)
        if preflight["status"] != "passed":
            result["reason"] = "combined R9 preflight exceeds the explicit cost ceiling"
            result["cost_preflight"] = preflight
            return result
        remaining_budget = min(new_call_cny_limit, max(0.0, TOTAL_CNY_LIMIT - prior_observed_cny))
        guard = SpendGuard(max_budget_cny=remaining_budget, cny_per_usd_ceiling=10.0, max_output_tokens=MAX_OUTPUT_TOKENS)
        delegate = __import__("evaluation.local_semantic_smoke", fromlist=["LocalBudgetGateway"]).LocalBudgetGateway(http_gateway, guard, gateway_audit)
        for item in prepared:
            sink_audit: dict[str, Any] = {"outboundCalls": 0, "visibleResponses": []}
            sink = NoOpSink(item["trajectory"] / "traces" / "sink.jsonl", sink_audit)
            gateway = SingleProviderCallGateway(delegate)
            loop = AgencyLoop(
                store=item["store"],
                context=ContextBuilder(snapshot_root=item["snapshot_root"], prompt_path=item["prompt_path"], manifest_path=item["manifest_path"], store=item["store"], concerns_enabled=True),
                adapters=LocalAdapters(snapshot_root=item["snapshot_root"], manifest_path=item["manifest_path"], store=item["store"], concerns_enabled=True),
                policy=Policy(item["store"], writable_root=item["trajectory"], concerns_enabled=True),
                gateway=gateway,
                sink=sink,
                trace_path=item["trajectory"] / "traces" / "trace.jsonl",
            )
            event_result = loop.process_event(item["event"])
            acceptance = _trace_acceptance(item, event_result, gateway, sink_audit)
            item["store"].close()
            result["samples"].append({
                "case_id": item["case_id"],
                "status": acceptance["status"],
                "source_ref": item["source_ref"],
                "source_version": item["version"],
                "retrieval": {"status": item["retrieved"].get("status"), "source_refs": item["retrieved"].get("source_refs"), "row_count": len(item["retrieved"].get("data") or [])},
                "state": {"selected_concern_id": item["concern_id"], "old": _concern_snapshot(item["old_concern"]), "after_evidence": item["pre_model_state"], "reopened": item["reopened_state"], "final": acceptance["final_concern"]},
                "provider": {"invocations": gateway.invocations, "blocked_secondary_attempts": gateway.blocked_secondary},
                "acceptance": acceptance,
                "fixture_input_binding": item["fixture_input_binding"],
                "trace": str(item["trajectory"] / "traces" / "trace.jsonl"),
                "sink": str(item["trajectory"] / "traces" / "sink.jsonl"),
            })
        budget = guard.snapshot()
        actual_new = float(budget.get("actual_usage_spent_cny_at_safety_rate") or 0.0)
        total_actual = float(prior_observed_cny) + actual_new
        production_after = _production_fingerprint(production_root)
        all_passed = len(result["samples"]) == len(selected_case_order) and all(item["status"] == "passed" for item in result["samples"])
        result.update({
            "status": "passed" if all_passed and production_before == production_after and budget.get("provider_calls") == len(selected_case_order) and total_actual <= TOTAL_CNY_LIMIT else "failed",
            "provider_calls": int(budget.get("provider_calls") or 0),
            "gateway_audit": gateway_audit,
            "budget_after": budget,
            "cost_preflight": preflight,
            "actual_new_call_cny_at_safety_rate": actual_new,
            "total_actual_cny_at_safety_rate": total_actual,
            "production_after": production_after,
            "production_unchanged": production_before == production_after,
            "no_op_sink_outboundCalls": 0,
            "no_real_bot": True,
        })
        _write_json(output_root / "semantic-cases-live-smoke.json", result)
        return result
    except Exception as exc:
        result.update({"status": "failed", "error": {"type": type(exc).__name__, "message": str(exc)}, "production_after": _production_fingerprint(production_root), "production_unchanged": production_before == _production_fingerprint(production_root)})
        _write_json(output_root / "semantic-cases-live-smoke.json", result)
        return result
    finally:
        for item in prepared:
            try:
                item["store"].close()
            except Exception:
                pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--production-root", default="E:/FoxSpirit/xiyu-ai")
    parser.add_argument("--output-root")
    parser.add_argument("--prior-observed-cny", type=float, default=PRIOR_OBSERVED_CNY)
    parser.add_argument("--new-call-cny-limit", type=float, default=R9_NEW_CALL_CNY_LIMIT)
    parser.add_argument("--cases", nargs="+", choices=sorted(CASE_CONFIG), default=list(CASE_ORDER))
    args = parser.parse_args()
    result = run(
        run_root=pathlib.Path(args.run_root).resolve(),
        production_root=pathlib.Path(args.production_root).resolve(),
        output_root=pathlib.Path(args.output_root).resolve() if args.output_root else None,
        prior_observed_cny=args.prior_observed_cny,
        case_order=tuple(args.cases),
        new_call_cny_limit=args.new_call_cny_limit,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
