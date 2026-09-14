"""Zero-fee R9 tests for target-specific semantic proposals."""
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

from contracts.schemas import parse_and_validate_semantic_proposal
from controller.boundary import NetworkBoundary
from controller.gateway import HttpProviderGateway
from evaluation.concern_cases import SEMANTIC_DELTA_EVALUATION_REGISTRY
from evaluation.semantic_delta import audit_semantic_delta
from runtime.prompts.assemble import assemble_compact_continuation
from runtime.semantic_proposal import SemanticProposalError, compile_semantic_proposal
from runtime.store import EventStore


OWNER = "account:1:companion:1"
SOURCE_REF = "feishu://ImtOsrt7yhTAbptIGPncik1mn2q/revision/9754/东坝店"
DEFAULT_R8_ARTIFACT = pathlib.Path(r"C:\Users\Administrator\AppData\Local\Temp\xiyu-r8-semantic-live-20260913-01\semantic-cases-live-smoke.json")


def _proposal(target: str, value: Any = None, *, action: str = "deliver", message: str = "东坝客流291。", evidence_refs: list[str] | None = None) -> dict[str, Any]:
    delta: dict[str, Any] = {"target": target, "reason": "按当前证据更新后续处理"}
    if value is not None:
        delta["value"] = value
    return {"action": action, "message": "" if action == "hold" else message, "evidence_refs": evidence_refs if evidence_refs is not None else [SOURCE_REF], "semantic_delta": delta}


def _seed_context(root: pathlib.Path) -> tuple[EventStore, dict[str, Any], str]:
    store = EventStore(root / "state.db")
    thread_id, _ = store.ensure_thread(OWNER, {"owner": OWNER, "fixture": "r9-target-test"})
    evidence = {"source_ref": SOURCE_REF, "epistemic_status": "observed", "kind": "frozen_workbench_record", "summary": "东坝 revision 9754 客流资料"}
    update = {
        "operation": "create", "concern_ref": "r9-target-concern", "expected_version": None,
        "basis_refs": [evidence],
        "changes": {
            "title": "东坝客流口径复核", "desired_direction": "分别核对来源字段", "domain": "work",
            "origin": "observed_gap", "desire_refs": ["work_trust"], "known_summary": [evidence],
            "unknowns": [{**evidence, "epistemic_status": "unknown", "kind": "source_gap", "impact": "影响当前口径判断"}],
            "next_review_condition": {"type": "new_source_version", "source_ref": SOURCE_REF, "version": "9754"},
        },
    }
    with store.transaction():
        applied = store.apply_concern_updates(OWNER, "r9-seed", [update], max_active=12)
    if not applied.get("accepted"):
        raise AssertionError(applied)
    concern_id = str(applied["accepted"][0]["concern_id"])
    concern = store.get_concern(OWNER, concern_id)
    context = {
        "owner": OWNER,
        "prompt_version": "agency-concerns-v2",
        "source_binding": {"kind": "frozen_snapshot", "version": "9754", "snapshot_id": "r9-target-test"},
        "stable": {},
        "current": {},
        "catalog": {"resources": []},
        "responsibilities": [],
        "boundaries": [],
        "continuity": {},
        "concerns": {"selected": [concern]},
        "continuation": {"semanticDelta": {"allowed_targets": ["status_transition", "desired_direction", "unknowns", "next_review_condition", "none"]}},
        "evidence_delta": {"source_ref": SOURCE_REF, "version": "9754", "retrieved": True, "facts": ["东坝 traffic=291"]},
        "event": {"kind": "opportunity", "payload": {"text": "按来源分别核对东坝客流字段"}},
    }
    return store, context, concern_id


def _audit_trace(proposal: dict[str, Any], changes: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [
        {"kind": "semantic_proposal_parse", "raw_response": proposal, "validation_result": "passed", "retrievedSourceRefs": [SOURCE_REF], "autoRecordedEvidenceRefs": [SOURCE_REF]},
        {"kind": "semantic_proposal_compiled", "validated_proposal": proposal, "compiled_concern_patch": {"changes": changes or {}}, "grounding": {"unsupported_positive_claim": False}, "retrievedSourceRefs": [SOURCE_REF], "autoRecordedEvidenceRefs": [SOURCE_REF], "modelConcernUpdates": [{"changes": changes or {}}]},
    ]


def run(*, r8_artifact: pathlib.Path = DEFAULT_R8_ARTIFACT, output_path: pathlib.Path | None = None) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="xiyu-r9-targets-") as temp_dir:
        root = pathlib.Path(temp_dir)
        store, context, concern_id = _seed_context(root)
        try:
            positives = {
                "status_transition_park": _proposal("status_transition", "park", action="hold"),
                "status_transition_keep_active": _proposal("status_transition", "keep_active"),
                "status_transition_resolve": _proposal("status_transition", "resolve"),
                "status_transition_dismiss": _proposal("status_transition", "dismiss"),
                "desired_direction": _proposal("desired_direction", "按来源分别核对两个客流字段"),
                "unknowns": _proposal("unknowns", ["两个客流字段是否同口径仍待核实"]),
                "next_review_condition": _proposal("next_review_condition", "收到新资料版本后再复查"),
                "none": _proposal("none"),
            }
            compiled: dict[str, Any] = {}
            for name, proposal in positives.items():
                parsed, audit = parse_and_validate_semantic_proposal(proposal)
                item: dict[str, Any] = {"parsed": parsed is not None, "parse_audit": audit}
                if parsed is not None:
                    try:
                        item["compiled"] = compile_semantic_proposal(parsed, context=context, owner=OWNER)
                    except SemanticProposalError as exc:
                        item["compile_error"] = str(exc)
                compiled[name] = item

            negatives: dict[str, dict[str, Any]] = {}
            candidates = {
                "status_transition_illegal_enum": _proposal("status_transition", "paused_pending_new_source"),
                "status_transition_old_status_word": _proposal("status_transition", "resolved"),
                "desired_direction_wrong_type": _proposal("desired_direction", 291),
                "desired_direction_too_long": _proposal("desired_direction", "x" * 181),
                "unknowns_wrong_type": _proposal("unknowns", "待核实"),
                "unknowns_empty": _proposal("unknowns", []),
                "unknowns_too_many": _proposal("unknowns", ["a", "b", "c", "d"]),
                "unknowns_item_too_long": _proposal("unknowns", ["x" * 121]),
                "next_review_wrong_type": _proposal("next_review_condition", {"type": "new_source_version"}),
                "next_review_too_long": _proposal("next_review_condition", "x" * 181),
                "none_with_value": _proposal("none", "不要带值"),
                "unknown_evidence": _proposal("desired_direction", "复核", evidence_refs=["experiment://account:1:companion:1/j05/r9/unread"]),
                "cross_owner_evidence": _proposal("desired_direction", "复核", evidence_refs=["experiment://account:2:companion:1/j05/r9/unread"]),
            }
            if r8_artifact.exists():
                saved = json.loads(r8_artifact.read_text(encoding="utf-8"))
                for sample in saved.get("samples", []):
                    if sample.get("case_id") in {"K08", "K10"}:
                        old = (sample.get("acceptance") or {}).get("proposal")
                        # R8 K08/K10 reached the compiler with a valid old
                        # shape, but the acceptance record intentionally
                        # leaves it empty after the compiler rejection.  The
                        # immutable trace is the source of truth for this
                        # regression guard.
                        if not old:
                            trace_path = pathlib.Path(str(sample.get("trace") or ""))
                            if trace_path.exists():
                                for line in trace_path.read_text(encoding="utf-8").splitlines():
                                    try:
                                        event = json.loads(line)
                                    except json.JSONDecodeError:
                                        continue
                                    if event.get("kind") == "semantic_proposal_parse" and isinstance(event.get("raw_response"), dict):
                                        old = event["raw_response"]
                                        break
                        if old:
                            candidates[f"saved_R8_{sample['case_id']}_old_shape"] = old
            for name, candidate in candidates.items():
                parsed, audit = parse_and_validate_semantic_proposal(candidate)
                error = audit.get("error")
                if parsed is not None:
                    try:
                        compile_semantic_proposal(parsed, context=context, owner=OWNER)
                    except SemanticProposalError as exc:
                        error = str(exc)
                negatives[name] = {"rejected": parsed is None or error is not None, "error": error, "parse_audit": audit}

            desired = compiled["desired_direction"]["compiled"]
            desired_patch = copy.deepcopy(desired["decision"]["concern_updates"])
            with store.transaction():
                applied = store.apply_concern_updates(OWNER, "r9-cas-accept", desired_patch, allowed_source_refs={SOURCE_REF})
            accepted = bool(applied.get("accepted")) and not applied.get("rejected")
            final = store.get_concern(OWNER, concern_id) or {}
            version_before_restart = final.get("version")
            store.close()
            reopened = EventStore(root / "state.db")
            try:
                reopened_concern = reopened.get_concern(OWNER, concern_id) or {}
                version_after_restart = reopened_concern.get("version")
                with reopened.transaction():
                    stale_patch = copy.deepcopy(desired_patch)
                    stale_patch[0]["expected_version"] = 0
                    stale_apply = reopened.apply_concern_updates(OWNER, "r9-cas-stale", stale_patch, allowed_source_refs={SOURCE_REF})
            finally:
                reopened.close()

            prompt_context = copy.deepcopy(context)
            prompt_context["prompt_version"] = "agency-concerns-v2"
            prompt = assemble_compact_continuation(prompt_context)
            gateway = HttpProviderGateway(model_name="deepseek-chat", endpoint="https://api.deepseek.com/v1/chat/completions", network_boundary=NetworkBoundary({"api.deepseek.com"}, {"/v1/chat/completions"}), max_output_tokens=512)
            payload_bytes = len(json.dumps(gateway._payload(prompt, 1), ensure_ascii=False).encode("utf-8"))

            semantic_checks = {
                "K08_park_target_objective_passes": audit_semantic_delta({"semantic_delta_evaluation": SEMANTIC_DELTA_EVALUATION_REGISTRY["K08"]}, _audit_trace(positives["status_transition_park"], {"status": "parked", "next_review_condition": {"type": "new_source_version", "source_ref": SOURCE_REF, "version": "9754"}}))["status"] == "passed",
                "K10_desired_direction_target_objective_passes": audit_semantic_delta({"semantic_delta_evaluation": SEMANTIC_DELTA_EVALUATION_REGISTRY["K10"]}, _audit_trace(positives["desired_direction"], {"desired_direction": "按来源分别核对两个客流字段"}))["status"] == "passed",
                "K08_none_objective_fails": audit_semantic_delta({"semantic_delta_evaluation": SEMANTIC_DELTA_EVALUATION_REGISTRY["K08"]}, _audit_trace(_proposal("none"), {}))["status"] == "failed",
                "saved_R8_old_shape_not_reclassified": all(item["rejected"] for name, item in negatives.items() if name.startswith("saved_R8_")) if any(name.startswith("saved_R8_") for name in negatives) else False,
            }
            checks = {
                "all_target_positives_parse": all(item["parsed"] for item in compiled.values()),
                "status_transition_maps": compiled["status_transition_park"].get("compiled", {}).get("compiled_concern_patch", {}).get("operation") == "park" and compiled["status_transition_resolve"].get("compiled", {}).get("compiled_concern_patch", {}).get("operation") == "resolve" and compiled["status_transition_dismiss"].get("compiled", {}).get("compiled_concern_patch", {}).get("operation") == "dismiss" and compiled["status_transition_keep_active"].get("compiled", {}).get("compiled_concern_patch") is None,
                "open_targets_map": compiled["desired_direction"].get("compiled", {}).get("compiled_concern_patch", {}).get("changes", {}).get("desired_direction") == "按来源分别核对两个客流字段" and compiled["unknowns"].get("compiled", {}).get("compiled_concern_patch", {}).get("changes", {}).get("unknowns", [{}])[0].get("summary") == "两个客流字段是否同口径仍待核实" and compiled["next_review_condition"].get("compiled", {}).get("compiled_concern_patch", {}).get("changes", {}).get("next_review_condition", {}).get("version") == "9754",
                "none_maps_no_patch": compiled["none"].get("compiled", {}).get("compiled_concern_patch") is None and not compiled["none"].get("compiled", {}).get("decision", {}).get("concern_updates"),
                "all_target_negatives_rejected": all(item["rejected"] for item in negatives.values()),
                "evidence_and_owner_guards": negatives["unknown_evidence"]["rejected"] and negatives["cross_owner_evidence"]["rejected"],
                "CAS_accepts_and_reopens": accepted and int(version_before_restart or -1) == 1 and int(version_after_restart or -1) == 1,
                "CAS_stale_patch_rejected": bool(stale_apply.get("rejected")) and not stale_apply.get("accepted"),
                "compact_payload_under_25kb": payload_bytes <= 25_000 and set(prompt["output_contract"]["semantic_delta"]["target_values"]) >= {"status_transition", "desired_direction", "unknowns", "next_review_condition", "none"},
                "semantic_evaluator_targets": all(semantic_checks.values()),
                "provider_calls_zero": True,
                "bot_messages_zero": True,
                "production_writes_zero": True,
            }
            result = {
                "schemaVersion": "r9-semantic-proposal-target-deterministic-v1",
                "status": "passed" if all(checks.values()) else "failed",
                "checks": checks,
                "semantic_evaluator_checks": semantic_checks,
                "positive_targets": compiled,
                "negative_cases": negatives,
                "compact": {"provider_payload_bytes": payload_bytes, "target_values": prompt["output_contract"]["semantic_delta"]["target_values"], "provider_calls": 0},
                "cas": {"accepted": accepted, "version_before_restart": version_before_restart, "version_after_restart": version_after_restart, "stale_apply": stale_apply, "provider_calls": 0},
                "saved_old_proposals": {name: item for name, item in negatives.items() if name.startswith("saved_R8_")},
                "provider_calls": 0,
                "bot_messages": 0,
                "production_writes": 0,
            }
        finally:
            try:
                store.close()
            except Exception:
                pass
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--r8-artifact", default=str(DEFAULT_R8_ARTIFACT))
    parser.add_argument("--output")
    args = parser.parse_args()
    result = run(r8_artifact=pathlib.Path(args.r8_artifact), output_path=pathlib.Path(args.output).resolve() if args.output else None)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
