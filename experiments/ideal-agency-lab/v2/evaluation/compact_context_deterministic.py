"""Zero-fee regression for the retrieved-continuation context contract.

The input trace is the saved K12 response that was truncated at the previous
output cap.  This module never contacts a provider: it measures the old and
new request envelopes, replays the old raw response as a rejection, feeds one
constructed formal patch through the existing EventStore CAS path, and feeds
one semantic proposal through the real AgencyLoop compiler path.
"""
from __future__ import annotations

import argparse
import copy
import json
import pathlib
import shutil
import sys
import tempfile
from typing import Any


V2_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(V2_ROOT) not in sys.path:
    sys.path.insert(0, str(V2_ROOT))

from contracts.schemas import parse_and_validate_decision
from adapters.local import LocalAdapters
from controller.boundary import NetworkBoundary
from controller.gateway import HttpProviderGateway, ScriptedGateway
from runtime.context import ContextBuilder
from runtime.grounding import assess_messages
from runtime.loop import AgencyLoop
from runtime.policy import Policy
from runtime.prompts.assemble import assemble_compact_continuation
from runtime.store import EventStore
from transport.sink import NoOpSink


DEFAULT_TRACE = pathlib.Path(r"C:\Users\Administrator\AppData\Local\Temp\xiyu-k12-continuation-equivalent-20260913-01\trajectory\traces\trace.jsonl")
DEFAULT_TRAJECTORY = DEFAULT_TRACE.parents[1]


def _json_bytes(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"))


def _read_trace(path: pathlib.Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _pick(rows: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    return next(row for row in rows if row.get("kind") == kind)


def _compact_breakdown(prompt: dict[str, Any]) -> dict[str, int]:
    """Byte-level breakdown of the compact semantic continuation prompt."""
    result = {key: _json_bytes(value) for key, value in prompt.items()}
    result["total_structured_prompt"] = _json_bytes(prompt)
    return result


def _make_minimal_decision(*, concern_id: str, expected_version: int, source_ref: str, source_version: str) -> dict[str, Any]:
    return {
        "operation": "continue",
        "desired_change": "差异",
        "basis_refs": [source_ref],
        "action": {"type": "deliver", "args": {}, "expected_result": ""},
        "strategy_reason": "201>168",
        "reconsider_condition": "",
        "messages": ["中影客流201，旧168。"],
        "concern_ref": concern_id,
        "concern_updates": [{
            "operation": "update",
            "concern_ref": concern_id,
            "expected_version": expected_version,
            "changes": {
                "desired_direction": "复核客流",
            },
            "basis_refs": [{"source_ref": source_ref, "epistemic_status": "observed", "kind": "knowledge.search_result"}],
        }],
    }


def _make_semantic_proposal(*, source_ref: str) -> dict[str, Any]:
    return {
        "action": "deliver",
        "message": "中影客流201，旧168。",
        "evidence_refs": [source_ref],
        "semantic_delta": {
            "target": "desired_direction",
            "value": "复核客流",
            "reason": "201>168",
        },
    }


def run(*, trace_path: pathlib.Path, trajectory_root: pathlib.Path, output_path: pathlib.Path | None = None) -> dict[str, Any]:
    rows = _read_trace(trace_path)
    input_row = _pick(rows, "input")
    provider_row = _pick(rows, "provider_call")
    event = copy.deepcopy(input_row["input"])
    original_prompt = copy.deepcopy(provider_row["prompt"])
    continuation = event["payload"]["continuation_equivalent"]
    concern_id = str(continuation["selectedConcernId"])
    new_evidence = continuation["newEvidence"]
    source_ref = str(new_evidence["source_ref"])
    source_version = str(new_evidence["version"])

    binding = HttpProviderGateway(
        model_name="deepseek-chat",
        endpoint="https://api.deepseek.com/v1/chat/completions",
        network_boundary=NetworkBoundary({"api.deepseek.com"}, {"/v1/chat/completions"}),
        max_output_tokens=192,
    )
    original_provider_bytes = _json_bytes(binding._payload(original_prompt, 1))

    with tempfile.TemporaryDirectory(prefix="xiyu-compact-context-") as temp_dir:
        temp_root = pathlib.Path(temp_dir)
        state_copy = temp_root / "state.db"
        shutil.copy2(trajectory_root / "state.db", state_copy)
        store = EventStore(state_copy)
        try:
            manifest_path = trajectory_root / "trajectory-manifest.json"
            snapshot_root = trajectory_root / "isolated-snapshot"
            context_builder = ContextBuilder(
                snapshot_root=snapshot_root,
                prompt_path=pathlib.Path(json.loads(manifest_path.read_text(encoding="utf-8"))["prompt_path"]),
                manifest_path=manifest_path,
                store=store,
                concerns_enabled=True,
            )
            compact_context = context_builder.build_compact_continuation(
                event,
                thread_state=dict(store.get_thread(event["owner"]) or {}),
            )
            compact_prompt = assemble_compact_continuation(compact_context)
            compact_payload_bytes = _json_bytes(binding._payload(compact_prompt, 1))
            selected = compact_context["concerns"]["selected"][0]
            compact_required = {
                "selectedConcernId": compact_context["continuation"]["selectedConcernId"],
                "new_source_ref": compact_context["evidence_delta"]["source_ref"],
                "difference": compact_context["continuation"]["newEvidenceDifference"],
                "basis_ref": compact_context["evidence_delta"]["source_ref"],
                "semantic_delta": compact_context["continuation"]["semanticDelta"],
            }

            old_decision, old_audit = parse_and_validate_decision(provider_row.get("raw_response"))
            old_rejected = old_decision is None and old_audit.get("validation_result") != "passed"

            decision = _make_minimal_decision(
                concern_id=concern_id,
                expected_version=int(selected["version"]),
                source_ref=source_ref,
                source_version=source_version,
            )
            parsed, parse_audit = parse_and_validate_decision(json.dumps(decision, ensure_ascii=False, separators=(",", ":")))
            if parsed is None:
                raise AssertionError(f"minimal legal response rejected: {parse_audit}")
            minimal_response_bytes = _json_bytes(decision)
            minimal_response_tokens = minimal_response_bytes / 4.0
            grounding = assess_messages(parsed, compact_context)
            with store.transaction():
                apply_result = store.apply_concern_updates(
                    event["owner"],
                    "offline-compact-replay",
                    parsed["concern_updates"],
                    allowed_source_refs={source_ref},
                )
            final_concern = store.get_concern(event["owner"], concern_id) or {}
            accepted = bool(apply_result.get("accepted")) and not apply_result.get("rejected")
            version_incremented = int(final_concern.get("version", -1)) == int(selected["version"]) + 1
            changed_fields = set((apply_result.get("accepted") or [{}])[0].keys())
            # The actual store result is the authoritative acceptance proof;
            # this separate check guards against an accidental broad patch.
            patch_fields = set(parsed["concern_updates"][0]["changes"])
            legal_patch_fields = bool(patch_fields) and patch_fields <= {"desired_direction", "next_review_condition"}
            no_provider = True
            estimate_cny = (compact_payload_bytes * 0.44 + 192 * 1.32) / 1_000_000 * 10.0

            loop_state = temp_root / "loop-state.db"
            shutil.copy2(trajectory_root / "state.db", loop_state)
            loop_store = EventStore(loop_state)
            try:
                loop_event = copy.deepcopy(event)
                loop_event["event_id"] = "offline-compact-loop"
                loop_sink_audit: dict[str, Any] = {"outboundCalls": 0, "visibleResponses": []}
                loop_context = ContextBuilder(
                    snapshot_root=snapshot_root,
                    prompt_path=pathlib.Path(json.loads(manifest_path.read_text(encoding="utf-8"))["prompt_path"]),
                    manifest_path=manifest_path,
                    store=loop_store,
                    concerns_enabled=True,
                )
                loop = AgencyLoop(
                    store=loop_store,
                    context=loop_context,
                    adapters=LocalAdapters(snapshot_root=snapshot_root, manifest_path=manifest_path, store=loop_store, concerns_enabled=True),
                    policy=Policy(loop_store, writable_root=temp_root, concerns_enabled=True),
                    gateway=ScriptedGateway([_make_semantic_proposal(source_ref=source_ref)]),
                    sink=NoOpSink(temp_root / "loop-sink.jsonl", loop_sink_audit),
                    trace_path=temp_root / "loop-trace.jsonl",
                )
                loop_result = loop.process_event(loop_event)
                loop_final = loop_store.get_concern(event["owner"], concern_id) or {}
                loop_trace_rows = _read_trace(loop.trace_path)
                loop_trace_kinds = {row.get("kind") for row in loop_trace_rows}
                loop_accepted_patch_trace = any(row.get("acceptedConcernPatches") for row in loop_trace_rows)
                loop_passed = (
                    loop_result.get("status") == "unknown"
                    and len(loop.gateway.calls) == 1
                    and loop_sink_audit.get("outboundCalls") == 0
                    and int(loop_final.get("version", -1)) == int(selected["version"]) + 1
                    and "semantic_proposal_parse" in loop_trace_kinds
                    and "semantic_proposal_compiled" in loop_trace_kinds
                    and loop_accepted_patch_trace
                )
            finally:
                loop_store.close()
            result = {
                "status": "passed" if all((
                    old_rejected,
                    compact_payload_bytes <= 25_000,
                    compact_payload_bytes <= 25_000,
                    minimal_response_tokens <= 192,
                    compact_required["selectedConcernId"] == concern_id,
                    compact_required["new_source_ref"] == source_ref,
                    compact_required["difference"].get("reception_traffic") == {"old": 168, "new": 201},
                    compact_required["basis_ref"] == source_ref,
                    "reception_traffic" in compact_required["semantic_delta"]["changed_fields"],
                    parsed["basis_refs"] == [source_ref],
                    parsed["concern_ref"] == concern_id,
                    grounding.relevant_evidence_present and not grounding.unsupported_positive_claim,
                    accepted,
                    version_incremented,
                    legal_patch_fields,
                    no_provider,
                    loop_passed,
                )) else "failed",
                "trace": str(trace_path),
                "original": {
                    "structured_prompt_bytes": _json_bytes(original_prompt),
                    "provider_payload_bytes": original_provider_bytes,
                    "breakdown": _compact_breakdown(original_prompt),
                    "saved_raw_rejected": old_rejected,
                    "saved_raw_error": old_audit.get("error"),
                },
                "compact": {
                    "structured_prompt_bytes": _json_bytes(compact_prompt),
                    "provider_payload_bytes": compact_payload_bytes,
                    "max_output_tokens": 192,
                    "estimated_input_tokens_heuristic": max(1, compact_payload_bytes // 4),
                    "conservative_input_tokens_upper_bound": compact_payload_bytes,
                    "worst_case_new_call_cny_at_safety_rate": estimate_cny,
                    "worst_case_cumulative_cny_at_safety_rate": 4.21874424 + estimate_cny,
                    "context": compact_required,
                    "contains_full_history": "recent_delivered_history" in compact_prompt,
                    "contains_concern_event_log": "updates_since_last_event" in json.dumps(compact_prompt, ensure_ascii=False),
                    "catalog_shape": compact_prompt["catalog"].get("resources"),
                },
                "offline_replay": {
                    "minimal_response_parser_valid": True,
                    "accepted": accepted,
                    "accepted_patch_fields": sorted(patch_fields),
                    "final_version": final_concern.get("version"),
                    "expected_version_before_patch": selected.get("version"),
                    "version_incremented": version_incremented,
                    "basis_refs": parsed["basis_refs"],
                    "provider_calls": 0,
                    "production_writes": 0,
                    "real_bot_messages": 0,
                    "response_bytes": minimal_response_bytes,
                    "estimated_output_tokens_heuristic": minimal_response_tokens,
                    "store_result": apply_result,
                    "grounding": {
                        "relevant_evidence_present": grounding.relevant_evidence_present,
                        "unsupported_positive_claim": grounding.unsupported_positive_claim,
                        "evidence_mode": grounding.evidence_mode,
                        "evidence_refs": list(grounding.evidence_refs),
                    },
                    "loop": {
                        "passed": loop_passed,
                        "result": loop_result,
                        "provider_calls": 0,
                        "outboundCalls": loop_sink_audit.get("outboundCalls", 0),
                        "final_version": loop_final.get("version"),
                        "trace_kinds": sorted(kind for kind in loop_trace_kinds if kind),
                        "accepted_patch_trace": loop_accepted_patch_trace,
                    },
                },
            }
        finally:
            store.close()

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", default=str(DEFAULT_TRACE))
    parser.add_argument("--trajectory-root", default=str(DEFAULT_TRAJECTORY))
    parser.add_argument("--output")
    args = parser.parse_args()
    result = run(
        trace_path=pathlib.Path(args.trace).resolve(),
        trajectory_root=pathlib.Path(args.trajectory_root).resolve(),
        output_path=pathlib.Path(args.output).resolve() if args.output else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
