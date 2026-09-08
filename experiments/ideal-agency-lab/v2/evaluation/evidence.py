"""Model-independent evidence contract used by the harness self-test."""
from __future__ import annotations

from copy import deepcopy
from typing import Any


def validate_evidence(trace: dict[str, Any], expected: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not trace.get("entry", {}).get("input"):
        errors.append("missing_actual_input")
    prompt = trace.get("prompt", {})
    if prompt.get("builder") != manifest.get("promptBuilder") or prompt.get("hash") != manifest.get("promptHash"):
        errors.append("wrong_prompt_path")
    calls = trace.get("calls", [])
    if not calls or any(not call.get("ok") or not call.get("schemaValid") for call in calls):
        errors.append("provider_or_schema_failure")
    tools = trace.get("tools", [])
    if expected.get("requiresTool") and not any(tool.get("status") == "complete" and tool.get("result") is not None for tool in tools):
        errors.append("tool_not_executed")
    if any(review.get("verdict") == "repair" for review in trace.get("reviews", [])) and len(trace.get("reviews", [])) < 2:
        errors.append("unresolved_repair")
    if expected.get("resultStatus") == "conflict" and not any(tool.get("status") == "conflict" for tool in tools):
        errors.append("concealed_conflict")
    required = expected.get("mustMention", [])
    payload = str(trace.get("finalPayload", ""))
    if any(term not in payload for term in required):
        errors.append("lost_required_fact")
    if trace.get("executionClaims") and not all(claim.get("receipt") for claim in trace["executionClaims"]):
        errors.append("unbacked_promise")
    if expected.get("requiresContact") and not trace.get("receipts"):
        errors.append("required_contact_missing")
    if trace.get("state") == "delivered" and not trace.get("receipts"):
        errors.append("false_delivery")
    owners = [item.get("owner") for item in trace.get("ownerEvents", [])]
    if any(owner != expected.get("owner") for owner in owners):
        errors.append("owner_mismatch")
    if expected.get("requiresImage") and not all(asset.get("file_hash") for asset in trace.get("assets", [])):
        errors.append("image_unverified")
    isolation = trace.get("isolation", {})
    if not isolation.get("interceptorId") or isolation.get("attempts") is None:
        errors.append("missing_isolation_evidence")
    if trace.get("rawPayload") and trace.get("rawPayload") != trace.get("finalPayload") and any(term not in str(trace.get("rawPayload")) for term in required):
        errors.append("lost_required_fact")
    if trace.get("hashes") != manifest.get("hashes"):
        errors.append("stale_evidence")
    return sorted(set(errors))


def validate_coverage(manifest: dict[str, Any]) -> list[str]:
    errors = []
    families = set(manifest.get("familyIds", []))
    if families != {f"{group}{i:02d}" for group in "ABCD" for i in range(1, 7)}:
        errors.append("incomplete_families")
    if manifest.get("repeats") != 5:
        errors.append("wrong_repeats")
    return errors


def aggregate_release(result: dict[str, Any]) -> dict[str, str]:
    if result.get("l0", {}).get("status") == "failed" or result.get("selftest", {}).get("status") == "failed":
        return {"status": "failed"}
    if any(result.get(key, {}).get("status") != "passed" for key in ("l0", "selftest", "fixed", "holdout", "media", "human")):
        return {"status": "inconclusive"}
    return {"status": "passed_experiment"}


def make_base_evidence() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest = {"promptBuilder": "runtime.prompts.assemble", "promptHash": "frozen", "hashes": {"code": "frozen", "rubric": "frozen"}, "familyIds": [f"{group}{i:02d}" for group in "ABCD" for i in range(1, 7)], "repeats": 5}
    expected = {"owner": {"accountId": "a", "companionId": "c"}, "requiresTool": True, "requiresContact": True, "mustMention": ["2026-09-02", "东坝店", "266", "销售额"], "requiresImage": False, "resultStatus": "complete"}
    trace = {"entry": {"input": "请核验东坝店销售额", "inputId": "in-1"}, "prompt": {"builder": manifest["promptBuilder"], "hash": manifest["promptHash"]}, "calls": [{"ok": True, "schemaValid": True}], "tools": [{"status": "complete", "result": {"value": 266}}], "finalPayload": "2026-09-02 东坝店 销售额 266", "state": "delivered", "receipts": [{"messageId": "sink-1", "status": "delivered"}], "ownerEvents": [{"owner": expected["owner"]}], "isolation": {"interceptorId": "test-sink", "attempts": []}, "hashes": manifest["hashes"], "reviews": [{"verdict": "pass"}]}
    return trace, expected, manifest

