"""Zero-cost tests for provider decision parsing and semantic-delta gates."""
from __future__ import annotations

import json
from typing import Any

from contracts.schemas import parse_and_validate_decision
from evaluation.concern_cases import SEMANTIC_DELTA_EVALUATION_REGISTRY, SEMANTIC_DELTA_REGISTRY
from evaluation.semantic_delta import audit_semantic_delta


def _decision(**overrides: Any) -> dict[str, Any]:
    value = {
        "operation": "continue",
        "intention_ref": None,
        "desired_change": "保留当前方向",
        "basis_refs": [],
        "action": {"type": "wait", "args": {}, "expected_result": "等待新输入"},
        "strategy_reason": "当前没有需要发送的结果",
        "expected_participation": "none",
        "reconsider_condition": "收到新证据后再判断",
        "messages": [],
        "concern_updates": [],
    }
    value.update(overrides)
    return value


def run_parser_and_semantic_delta_selftest() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []

    def check(name: str, condition: bool, detail: dict[str, Any] | None = None) -> None:
        rows.append({"name": name, "status": "passed" if condition else "failed", "detail": detail or {}})

    strict = _decision()
    parsed, audit = parse_and_validate_decision(strict)
    check("strict provider object validates", parsed is not None and audit["repair_type"] == "none" and audit["validation_result"] == "passed", audit)

    fenced = "结果如下：\n```json\n" + json.dumps(strict, ensure_ascii=False) + "\n```\n以上。"
    parsed, audit = parse_and_validate_decision(fenced)
    check("one complete object can be extracted from fence and prose", parsed is not None and audit["repair_type"] == "extract_complete_json_object", audit)

    string_messages = json.dumps(_decision(action={"type": "deliver", "args": {}}, messages="已记录"), ensure_ascii=False)
    parsed, audit = parse_and_validate_decision(string_messages)
    check("known scalar message is wrapped without semantic invention", parsed is not None and parsed["messages"] == ["已记录"] and "messages_string_to_array" in audit["repair_type"], audit)

    defaults = {key: value for key, value in strict.items() if key not in {"messages", "basis_refs", "concern_updates"}}
    parsed, audit = parse_and_validate_decision(defaults)
    check("missing known arrays default to empty arrays", parsed is not None and parsed["messages"] == [] and parsed["basis_refs"] == [] and parsed["concern_updates"] == [], audit)

    truncated = json.dumps(strict, ensure_ascii=False)[:-8]
    parsed, audit = parse_and_validate_decision(truncated)
    check("truncated JSON is rejected rather than repaired by guessing", parsed is None and audit.get("error") == "no_single_complete_json_object", audit)

    ambiguous = json.dumps(strict, ensure_ascii=False) + "\n" + json.dumps(strict, ensure_ascii=False)
    parsed, audit = parse_and_validate_decision(ambiguous)
    check("multiple complete objects are rejected", parsed is None and audit.get("error") == "multiple_complete_json_objects", audit)

    invalid_extra = json.dumps({**strict, "invented_business_fact": 123}, ensure_ascii=False)
    parsed, audit = parse_and_validate_decision(invalid_extra)
    check("unknown fields remain a schema failure", parsed is None and audit.get("validation_result") == "failed", audit)

    for case_id in ("K12", "K04", "K08", "K10"):
        spec = SEMANTIC_DELTA_REGISTRY.get(case_id)
        check(f"{case_id} semantic delta is pre-registered", bool(spec and spec.get("exists") and spec.get("expected_fields") and spec.get("evidence")), spec or {})
    objective_k12 = SEMANTIC_DELTA_EVALUATION_REGISTRY.get("K12")
    objective_required = all(
        SEMANTIC_DELTA_EVALUATION_REGISTRY.get(case_id, {}).get("mode") == "required"
        and SEMANTIC_DELTA_EVALUATION_REGISTRY.get(case_id, {}).get("expected_fields")
        for case_id in ("K04", "K08", "K10")
    )
    check("objective registry permits justified none for evidence-only K12", bool(objective_k12 and objective_k12.get("mode") == "allow_none" and not objective_k12.get("expected_fields")), objective_k12 or {})
    check("objective registry requires semantic deltas for K04/K08/K10", objective_required, {case_id: SEMANTIC_DELTA_EVALUATION_REGISTRY.get(case_id) for case_id in ("K04", "K08", "K10")})
    check("evidence-only empty updates pass", audit_semantic_delta({"semantic_delta": {"exists": False}}, [{"modelConcernUpdates": [], "autoRecordedEvidenceRefs": ["feishu://r1"]}])["status"] == "passed")
    check("semantic delta needs a matching patch", audit_semantic_delta({"semantic_delta": {"exists": True, "expected_fields": ["desired_direction"]}}, [{"modelConcernUpdates": [], "autoRecordedEvidenceRefs": ["feishu://r2"]}])["status"] == "failed")
    check(
        "matching semantic patch passes",
        audit_semantic_delta(
            {"semantic_delta": {"exists": True, "expected_fields": ["desired_direction"], "expected_targets": ["desired_direction"], "allowed_targets": ["desired_direction"]}},
            [{
                "kind": "semantic_proposal_compiled",
                "validated_proposal": {"semantic_delta": {"target": "desired_direction", "value": "新方向", "reason": "用户已明确改变后续处理"}, "evidence_refs": ["feishu://r2"]},
                "acceptedConcernPatches": [{"changes": {"desired_direction": "新方向"}}],
                "retrievedSourceRefs": ["feishu://r2"],
            }],
        )["status"] == "passed",
    )
    check("unexpected patch fails evidence-only case", audit_semantic_delta({"semantic_delta": {"exists": False}}, [{"acceptedConcernPatches": [{"changes": {"desired_direction": "新方向"}}]}])["status"] == "failed")

    passed = sum(row["status"] == "passed" for row in rows)
    return {"schemaVersion": "decision-parser-semantic-delta-selftest-v1", "status": "passed" if passed == len(rows) else "failed", "passed": passed, "total": len(rows), "provider_calls": 0, "results": rows, "case_specs_present": sorted(set(SEMANTIC_DELTA_REGISTRY) & {"K12", "K04", "K08", "K10"})}


if __name__ == "__main__":
    result = run_parser_and_semantic_delta_selftest()
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["status"] == "passed" else 1)
