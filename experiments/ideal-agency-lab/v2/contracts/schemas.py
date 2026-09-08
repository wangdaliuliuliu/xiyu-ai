"""Small, strict, dependency-free contracts for the experiment wire format."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


EVENT_KINDS = {
    "user_message",
    "opportunity",
    "task_due",
    "tool_result",
    "delivery_result",
    "silence_observed",
}
ACTION_TYPES = {
    "none",
    "catalog",
    "profile.read",
    "knowledge.search",
    "knowledge.read",
    "memory.search",
    "tasks.read",
    "tasks.update",
    "knowledge.propose",
    "knowledge.confirm",
    "research",
    "media.prepare",
    "deliver",
    "wait",
}
OPERATIONS = {"new", "continue", "revise", "suspend", "complete"}
INTENTION_STATES = {"active", "awaiting_user", "suspended", "completed", "abandoned"}
ACTION_STATES = {
    "planned", "running", "prepared", "ready", "sending", "delivered",
    "partial", "unknown", "failed", "superseded",
}
RESULT_STATUSES = {
    "complete", "not_found", "unavailable", "forbidden", "conflict", "partial",
    "failed", "infra_failure",
}
DELIVERY_STATUSES = {"delivered", "partial", "unknown", "failed"}


class ContractError(ValueError):
    """Raised when an external or model-produced object violates a contract."""


def _require(obj: dict[str, Any], key: str, typ: type | tuple[type, ...]) -> Any:
    if key not in obj:
        raise ContractError(f"missing field: {key}")
    value = obj[key]
    if not isinstance(value, typ):
        raise ContractError(f"{key} must be {typ}, got {type(value).__name__}")
    return value


def validate_event(event: dict[str, Any]) -> dict[str, Any]:
    obj = deepcopy(event)
    _require(obj, "event_id", str)
    _require(obj, "owner", str)
    kind = _require(obj, "kind", str)
    if kind not in EVENT_KINDS:
        raise ContractError(f"unsupported event kind: {kind}")
    _require(obj, "virtual_time", str)
    payload = _require(obj, "payload", dict)
    if not payload:
        raise ContractError("event payload must not be empty")
    return obj


def _validate_action(action: dict[str, Any]) -> dict[str, Any]:
    obj = deepcopy(action)
    action_type = _require(obj, "type", str)
    if action_type not in ACTION_TYPES:
        raise ContractError(f"unsupported action type: {action_type}")
    args = obj.get("args", {})
    if not isinstance(args, dict):
        raise ContractError("action.args must be an object")
    expected = obj.get("expected_result", "")
    if not isinstance(expected, str):
        raise ContractError("action.expected_result must be a string")
    return obj


def validate_decision(decision: dict[str, Any]) -> dict[str, Any]:
    obj = deepcopy(decision)
    operation = _require(obj, "operation", str)
    if operation not in OPERATIONS:
        raise ContractError(f"unsupported operation: {operation}")
    intention_ref = obj.get("intention_ref")
    if intention_ref is not None and not isinstance(intention_ref, str):
        raise ContractError("intention_ref must be a string or null")
    _require(obj, "desired_change", str)
    basis_refs = _require(obj, "basis_refs", list)
    if not all(isinstance(ref, str) for ref in basis_refs):
        raise ContractError("basis_refs must contain strings")
    action = _require(obj, "action", dict)
    _validate_action(action)
    _require(obj, "strategy_reason", str)
    if "expected_participation" in obj and obj["expected_participation"] is not None and not isinstance(obj["expected_participation"], str):
        raise ContractError("expected_participation must be a string or null")
    _require(obj, "reconsider_condition", str)
    messages = _require(obj, "messages", list)
    if not all(isinstance(message, str) for message in messages):
        raise ContractError("messages must contain strings")
    if action["type"] == "deliver" and not messages:
        raise ContractError("deliver requires at least one message")
    if action["type"] != "deliver" and messages:
        raise ContractError("messages are only allowed on a deliver decision")
    return obj


def validate_tool_result(result: dict[str, Any]) -> dict[str, Any]:
    obj = deepcopy(result)
    status = _require(obj, "status", str)
    if status not in RESULT_STATUSES:
        raise ContractError(f"unsupported tool result status: {status}")
    _require(obj, "data", (dict, list, str, int, float, bool, type(None)))
    source_refs = _require(obj, "source_refs", list)
    if not all(isinstance(ref, str) for ref in source_refs):
        raise ContractError("source_refs must contain strings")
    _require(obj, "scope", str)
    _require(obj, "version", str)
    _require(obj, "trace_id", str)
    completeness = obj.get("completeness")
    if completeness is not None and not isinstance(completeness, str):
        raise ContractError("completeness must be a string")
    return obj


def validate_delivery_result(result: dict[str, Any]) -> dict[str, Any]:
    obj = deepcopy(result)
    status = _require(obj, "status", str)
    if status not in DELIVERY_STATUSES:
        raise ContractError(f"unsupported delivery status: {status}")
    _require(obj, "attempt_id", str)
    _require(obj, "segment_id", str)
    _require(obj, "idempotency_key", str)
    if "provider_message_id" in obj and obj["provider_message_id"] is not None and not isinstance(obj["provider_message_id"], str):
        raise ContractError("provider_message_id must be a string or null")
    return obj


def normalize_action_args(action_type: str, args: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Normalize declared aliases only and return (normalized, diff).

    This function deliberately does not fill missing business parameters. That
    distinction is what prevents a runner from silently turning an unknown
    store/date/metric into a fixed test query.
    """
    if action_type not in ACTION_TYPES:
        raise ContractError(f"unsupported action type: {action_type}")
    original = deepcopy(args)
    normalized = deepcopy(args)
    aliases = {
        "store": "store_name",
        "metric_name": "metric",
        "date": "business_date",
    }
    for old, new in aliases.items():
        if old in normalized and new not in normalized:
            normalized[new] = normalized.pop(old)
    diff = {"changed": original != normalized, "before": original, "after": normalized}
    return normalized, diff


@dataclass(frozen=True)
class DecisionBudget:
    max_model_calls: int = 6
    max_tool_rounds: int = 4
    max_infra_retries: int = 2

