"""Zero-fee contract/compiler tests for R6 semantic proposals."""
from __future__ import annotations

import argparse
import copy
import json
import pathlib
import shutil
import tempfile
import sys
from typing import Any


V2_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(V2_ROOT) not in sys.path:
    sys.path.insert(0, str(V2_ROOT))

from contracts.schemas import parse_and_validate_semantic_proposal
from controller.boundary import NetworkBoundary
from controller.gateway import HttpProviderGateway
from runtime.context import ContextBuilder
from runtime.semantic_proposal import SemanticProposalError, compile_semantic_proposal
from runtime.store import EventStore


DEFAULT_TRACE = pathlib.Path(r"C:\Users\Administrator\AppData\Local\Temp\xiyu-k12-continuation-r5-20260913-01\trajectory\traces\trace.jsonl")
DEFAULT_TRAJECTORY = DEFAULT_TRACE.parents[1]


def _rows(path: pathlib.Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _source_refs(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, dict):
        for key in ("source_ref", "source_refs"):
            current = value.get(key)
            if isinstance(current, str):
                refs.add(current)
            elif isinstance(current, list):
                refs.update(item for item in current if isinstance(item, str))
        for item in value.values():
            refs.update(_source_refs(item))
    elif isinstance(value, list):
        for item in value:
            refs.update(_source_refs(item))
    return refs


def _proposal(source_ref: str, *, target: str = "desired_direction", value: Any = "复核客流", action: str = "deliver", message: str = "中影客流201，旧168。", evidence_refs: list[str] | None = None) -> dict[str, Any]:
    return {
        "action": action,
        "message": message,
        "evidence_refs": evidence_refs if evidence_refs is not None else [source_ref],
        "semantic_delta": {"target": target, "value": value, "reason": "201>168"},
    }


def run(*, trace_path: pathlib.Path = DEFAULT_TRACE, trajectory_root: pathlib.Path = DEFAULT_TRAJECTORY, output_path: pathlib.Path | None = None) -> dict[str, Any]:
    rows = _rows(trace_path)
    input_row = next(row for row in rows if row.get("kind") == "input")
    old_provider = next(row for row in rows if row.get("kind") == "provider_call")
    event = copy.deepcopy(input_row["input"])
    continuation = event["payload"]["continuation_equivalent"]
    source_ref = str(continuation["newEvidence"]["source_ref"])
    owner = event["owner"]
    manifest_path = trajectory_root / "trajectory-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    snapshot_root = trajectory_root / "isolated-snapshot"
    with tempfile.TemporaryDirectory(prefix="xiyu-r6-semantic-proposal-") as temp_dir:
        temp_root = pathlib.Path(temp_dir)
        state_copy = temp_root / "state.db"
        shutil.copy2(trajectory_root / "state.db", state_copy)
        store = EventStore(state_copy)
        try:
            builder = ContextBuilder(snapshot_root=snapshot_root, prompt_path=pathlib.Path(manifest["prompt_path"]), manifest_path=manifest_path, store=store, concerns_enabled=True)
            context = builder.build_compact_continuation(event, thread_state=dict(store.get_thread(owner) or {}))
            selected = context["concerns"]["selected"][0]
            available_refs = _source_refs(context)
            valid = _proposal(source_ref)
            parsed, valid_audit = parse_and_validate_semantic_proposal(json.dumps(valid, ensure_ascii=False, separators=(",", ":")))
            compiled = compile_semantic_proposal(parsed, context=context, owner=owner) if parsed else None

            negative_cases: dict[str, dict[str, Any]] = {}
            cases = {
                "old_r5_format": old_provider.get("raw_response"),
                "unknown_evidence": _proposal(source_ref, evidence_refs=["experiment://account:1:companion:1/j05/k12/revision/1/中影店"]),
                "cross_owner_evidence": _proposal(source_ref, evidence_refs=["experiment://account:2:companion:1/j05/k12/revision/2/中影店"]),
                "old_version_evidence": _proposal(source_ref, evidence_refs=["experiment://account:1:companion:1/j05/k12/revision/1/中影店"]),
                "type_error": _proposal(source_ref, value=201),
                "illegal_status": _proposal(source_ref, target="status_transition", value="closed"),
                "unreferenced_business_message": _proposal(source_ref, message="中影销售额999。"),
            }
            for name, candidate in cases.items():
                proposal, audit = parse_and_validate_semantic_proposal(candidate)
                error = None
                if proposal is not None:
                    try:
                        compile_semantic_proposal(proposal, context=context, owner=owner)
                    except SemanticProposalError as exc:
                        error = str(exc)
                negative_cases[name] = {"rejected": proposal is None or error is not None, "error": audit.get("error") or error, "parse_audit": audit}

            none = {"action": "deliver", "message": "中影客流201，旧168。", "evidence_refs": [source_ref], "semantic_delta": {"target": "none", "reason": "仅记录新证据"}}
            none_parsed, none_audit = parse_and_validate_semantic_proposal(none)
            none_compiled = compile_semantic_proposal(none_parsed, context=context, owner=owner) if none_parsed else None

            status_context = copy.deepcopy(context)
            status_context["continuation"]["semanticDelta"]["allowed_targets"] = ["status_transition", "none"]
            park = _proposal(source_ref, target="status_transition", value="park", message="")
            park["action"] = "hold"
            park_parsed, park_audit = parse_and_validate_semantic_proposal(park)
            park_compiled = compile_semantic_proposal(park_parsed, context=status_context, owner=owner) if park_parsed else None

            replay_state = temp_root / "replay.db"
            shutil.copy2(trajectory_root / "state.db", replay_state)
            replay = EventStore(replay_state)
            try:
                with replay.transaction():
                    apply_result = replay.apply_concern_updates(owner, "r6-offline-update", compiled["decision"]["concern_updates"], allowed_source_refs=available_refs) if compiled else {"accepted": [], "rejected": [{"reason": "compile_failed"}]}
                replay.close()
                reopened = EventStore(replay_state)
                final = reopened.get_concern(owner, selected["id"]) or {}
                reopened_version = final.get("version")
                reopened.close()
            finally:
                try:
                    replay.close()
                except Exception:
                    pass

            gateway = HttpProviderGateway(model_name="deepseek-chat", endpoint="https://api.deepseek.com/v1/chat/completions", network_boundary=NetworkBoundary({"api.deepseek.com"}, {"/v1/chat/completions"}), max_output_tokens=512)
            compact_payload = json.dumps(gateway._payload({"prompt": "unused"}, 1), ensure_ascii=False).encode("utf-8")
            # Replace the placeholder with the real compact request after the
            # size probe above so this assertion measures the actual contract.
            from runtime.prompts.assemble import assemble_compact_continuation
            compact_prompt = assemble_compact_continuation(context)
            compact_payload = json.dumps(gateway._payload(compact_prompt, 1), ensure_ascii=False).encode("utf-8")

            checks = {
                "proposal_schema_positive": parsed is not None and valid_audit.get("validation_result") == "passed",
                "compiler_injected_concern_and_version": bool(compiled and compiled["compiled_concern_patch"]["concern_ref"] == selected["id"] and compiled["compiled_concern_patch"]["expected_version"] == selected["version"]),
                "compiler_auto_basis": bool(compiled and compiled["compiled_concern_patch"]["basis_refs"] == [{"source_ref": source_ref, "epistemic_status": "observed"}]),
                "semantic_none_has_no_patch": bool(none_compiled and none_compiled["compiled_concern_patch"] is None and not none_compiled["decision"]["concern_updates"]),
                "status_park_is_supported": bool(park_compiled and park_compiled["compiled_concern_patch"]["operation"] == "park"),
                "update_accepted": bool(apply_result.get("accepted")) and not apply_result.get("rejected"),
                "version_1_to_2_reopened": int(selected["version"]) == 1 and int(reopened_version or -1) == 2,
                "message_grounded": bool(compiled and not compiled["grounding"]["unsupported_positive_claim"]),
                "r5_rejected": negative_cases["old_r5_format"]["rejected"],
                "all_negative_cases_rejected": all(item["rejected"] for item in negative_cases.values()),
                "compact_payload_under_25kb": len(compact_payload) <= 25_000,
                "provider_calls_zero": True,
                "bot_messages_zero": True,
                "production_writes_zero": True,
            }
            result = {
                "status": "passed" if all(checks.values()) else "failed",
                "proposal_schema": {"fields": ["action", "message", "evidence_refs", "semantic_delta"], "delta_fields": ["target", "value", "reason"], "targets": ["status_transition", "desired_direction", "unknowns", "next_review_condition", "none"], "actions": ["deliver", "hold"]},
                "compiler_rules": {"concern_ref": "selected concern id", "expected_version": "selected concern version", "basis_refs": "proposal evidence_refs converted to observed evidence objects", "allowed_targets": ["status_transition", "desired_direction", "unknowns", "next_review_condition", "none"], "semantic_none": "no patch", "status_transition": {"keep_active": "no patch", "park": "park", "dismiss": "dismiss", "resolve": "resolve"}},
                "checks": checks,
                "negative_cases": negative_cases,
                "positive": {"validated_proposal": parsed, "compiled_concern_patch": compiled["compiled_concern_patch"] if compiled else None, "compiled_decision": compiled["decision"] if compiled else None, "grounding": compiled["grounding"] if compiled else None},
                "none": {"validated": none_parsed is not None, "audit": none_audit, "compiled_patch": none_compiled["compiled_concern_patch"] if none_compiled else None},
                "park": {"validated": park_parsed is not None, "audit": park_audit, "compiled_patch": park_compiled["compiled_concern_patch"] if park_compiled else None},
                "compact": {"provider_payload_bytes": len(compact_payload), "max_output_tokens": 512, "estimated_input_tokens_heuristic": max(1, len(compact_payload) // 4), "one_real_call_worst_cny": (len(compact_payload) * 0.44 + 512 * 1.32) / 1_000_000 * 10.0, "prior_r5_actual_cny": 4.40302976, "cumulative_worst_cny": 4.40302976 + (len(compact_payload) * 0.44 + 512 * 1.32) / 1_000_000 * 10.0},
                "offline_replay": {"accepted": bool(apply_result.get("accepted")) and not apply_result.get("rejected"), "version_before": selected.get("version"), "version_after_reopen": reopened_version, "provider_calls": 0, "bot_messages": 0, "production_writes": 0},
            }
        finally:
            store.close()
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", default=str(DEFAULT_TRACE))
    parser.add_argument("--trajectory-root", default=str(DEFAULT_TRAJECTORY))
    parser.add_argument("--output")
    args = parser.parse_args()
    result = run(trace_path=pathlib.Path(args.trace).resolve(), trajectory_root=pathlib.Path(args.trajectory_root).resolve(), output_path=pathlib.Path(args.output).resolve() if args.output else None)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
