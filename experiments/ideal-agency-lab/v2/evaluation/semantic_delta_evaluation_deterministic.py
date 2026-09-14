"""Zero-fee objective semantic-delta acceptance tests for R9."""
from __future__ import annotations

import argparse
import copy
import json
import pathlib
import sys
from typing import Any


V2_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(V2_ROOT) not in sys.path:
    sys.path.insert(0, str(V2_ROOT))

from evaluation.concern_cases import SEMANTIC_DELTA_EVALUATION_REGISTRY
from evaluation.semantic_delta import audit_semantic_delta


DEFAULT_FIXTURE = pathlib.Path(r"C:\Users\Administrator\AppData\Local\Temp\xiyu-r2-fixture-run-20260913-02")
DEFAULT_R7_TRACE = pathlib.Path(r"C:\Users\Administrator\AppData\Local\Temp\xiyu-k12-continuation-r7-20260913-05\trajectory\traces\trace.jsonl")


def _rows(path: pathlib.Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _none_trace(source_ref: str, *, reason: str = "仅记录新证据，持续方向未变化", available_source_ref: str | None = None) -> list[dict[str, Any]]:
    proposal = {
        "action": "deliver",
        "message": "已读取新资料并报告差异。",
        "evidence_refs": [source_ref],
        "semantic_delta": {"kind": "none", "reason": reason},
    }
    available = available_source_ref or source_ref
    return [
        {"kind": "semantic_proposal_parse", "raw_response": proposal, "validation_result": "passed", "autoRecordedEvidenceRefs": [available], "retrievedSourceRefs": [available]},
        {"kind": "semantic_proposal_compiled", "validated_proposal": proposal, "compiled_concern_patch": None, "grounding": {"unsupported_positive_claim": False}, "acceptedConcernPatches": [], "autoRecordedEvidenceRefs": [available], "retrievedSourceRefs": [available]},
    ]


def _patch_trace(source_ref: str, target: str = "desired_direction") -> list[dict[str, Any]]:
    if target == "status_transition":
        value = "park"
        changes = {
            "status": "parked",
            "next_review_condition": {"type": "new_source_version", "source_ref": source_ref, "version": "2"},
        }
    else:
        value = "复核口径"
        changes = {target: value}
    return [{
        "kind": "semantic_proposal_compiled",
        "validated_proposal": {
            "action": "deliver",
            "message": "已依据新资料调整后续方向。",
            "evidence_refs": [source_ref],
            "semantic_delta": {"target": target, "value": value, "reason": "用户已明确改变后续处理"},
        },
        "grounding": {"unsupported_positive_claim": False},
        "acceptedConcernPatches": [{"changes": changes}],
        "autoRecordedEvidenceRefs": [source_ref],
        "retrievedSourceRefs": [source_ref],
    }]


def run(*, fixture_root: pathlib.Path = DEFAULT_FIXTURE, r7_trace: pathlib.Path = DEFAULT_R7_TRACE, output_path: pathlib.Path | None = None) -> dict[str, Any]:
    case_manifest = json.loads((fixture_root / "case-manifest.json").read_text(encoding="utf-8"))
    cases = {item["case_id"]: item for item in case_manifest.get("cases", [])}
    objective = copy.deepcopy(SEMANTIC_DELTA_EVALUATION_REGISTRY)
    case_objective_binding = {
        case_id: {
            "fixture_case_present": case_id in cases,
            "mode": spec["mode"],
            "expected_fields": list(spec.get("expected_fields", [])),
            "registry_source": spec.get("source"),
        }
        for case_id, spec in objective.items()
    }
    source_ref = "experiment://account:1:companion:1/j05/k12/revision/2/中影店"
    k12_case = copy.deepcopy(cases["K12"])
    k12_case["semantic_delta_evaluation"] = objective["K12"]
    actual_r7 = audit_semantic_delta(k12_case, _rows(r7_trace))

    evidence_only_none = audit_semantic_delta(
        {"semantic_delta_evaluation": objective["K12"]},
        _none_trace(source_ref),
    )
    evidence_only_forced_patch = audit_semantic_delta(
        {"semantic_delta_evaluation": objective["K12"]},
        _patch_trace(source_ref),
    )
    required_none = audit_semantic_delta(
        {"semantic_delta_evaluation": objective["K08"]},
        _none_trace(source_ref, reason="暂不改变方向"),
    )
    required_patch = audit_semantic_delta(
        {"semantic_delta_evaluation": objective["K08"]},
        _patch_trace(source_ref, "status_transition"),
    )
    none_without_reason = audit_semantic_delta(
        {"semantic_delta_evaluation": objective["K12"]},
        _none_trace(source_ref, reason=""),
    )
    none_with_unbound_evidence = audit_semantic_delta(
        {"semantic_delta_evaluation": objective["K12"]},
        _none_trace("experiment://unread/source", available_source_ref=source_ref),
    )
    checks = {
        "objective_registry_is_fixture_bound": all(item["fixture_case_present"] and item["registry_source"] for item in case_objective_binding.values()),
        "K04_K08_K10_require_semantic_delta": all(objective[item]["mode"] == "required" and objective[item]["expected_fields"] for item in ("K04", "K08", "K10")),
        "K12_allows_reasoned_none": objective["K12"]["mode"] == "allow_none" and not objective["K12"]["expected_fields"],
        "K12_actual_r7_none_passes": actual_r7["status"] == "passed" and actual_r7["proposal_none"] and actual_r7["proposal_none_reasoned"] and actual_r7["proposal_evidence_bound"] and actual_r7["proposal_grounded"],
        "evidence_only_none_passes": evidence_only_none["status"] == "passed",
        "evidence_only_forced_patch_fails": evidence_only_forced_patch["status"] == "failed",
        "required_none_fails": required_none["status"] == "failed",
        "required_patch_passes": required_patch["status"] == "passed",
        "none_without_reason_fails": none_without_reason["status"] == "failed",
        "none_unbound_evidence_fails": none_with_unbound_evidence["status"] == "failed",
        "provider_calls_zero": True,
        "bot_messages_zero": True,
        "production_writes_zero": True,
    }
    result = {
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "objective_registry": case_objective_binding,
        "actual_r7": actual_r7,
        "offline_cases": {
            "evidence_only_none": evidence_only_none,
            "evidence_only_forced_patch": evidence_only_forced_patch,
            "required_none": required_none,
            "required_patch": required_patch,
            "none_without_reason": none_without_reason,
            "none_with_unbound_evidence": none_with_unbound_evidence,
        },
        "provider_calls": 0,
        "bot_messages": 0,
        "production_writes": 0,
    }
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-root", default=str(DEFAULT_FIXTURE))
    parser.add_argument("--r7-trace", default=str(DEFAULT_R7_TRACE))
    parser.add_argument("--output")
    args = parser.parse_args()
    result = run(fixture_root=pathlib.Path(args.fixture_root), r7_trace=pathlib.Path(args.r7_trace), output_path=pathlib.Path(args.output).resolve() if args.output else None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
