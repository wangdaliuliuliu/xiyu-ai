"""Small, strict, dependency-free contracts for the experiment wire format."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
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
    "concerns.read",
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

CONCERN_DOMAINS = {"work", "personal", "mixed"}
CONCERN_ORIGINS = {"user_goal", "task_link", "observed_gap", "role_interest"}
CONCERN_DESIRE_REFS = {"work_trust", "personal_affinity"}
CONCERN_STATUSES = {"active", "parked", "resolved", "dismissed"}
CONCERN_OPERATIONS = {"create", "update", "park", "resolve", "dismiss"}
CONCERN_CONDITION_TYPES = {
    "new_source_version",
    "user_reply_to",
    "task_event",
    "next_eligible_opportunity",
    "after_time",
}
SEMANTIC_PROPOSAL_ACTIONS = {"deliver", "hold"}
SEMANTIC_DELTA_KINDS = {"none", "update"}
SEMANTIC_DELTA_FIELDS = {"desired_direction", "known_summary", "unknowns", "next_review_condition", "status"}
SEMANTIC_DELTA_TARGETS = {"status_transition", "desired_direction", "unknowns", "next_review_condition", "none"}
SEMANTIC_STATUS_TRANSITIONS = {"keep_active", "park", "resolve", "dismiss"}
SEMANTIC_OPEN_STRING_MAX = 180
SEMANTIC_UNKNOWN_ITEM_MAX = 120
SEMANTIC_UNKNOWN_MAX_ITEMS = 3
CONCERN_CHANGE_FIELDS = {
    "title",
    "desired_direction",
    "domain",
    "origin",
    "desire_refs",
    "linked_task_ids",
    "known_summary",
    "unknowns",
    "next_review_condition",
    "boundary_refs",
    "resolution_evidence",
    "status",
}
EPISTEMIC_STATUSES = {"confirmed", "observed", "candidate", "inferred", "unknown", "unverified"}


class ContractError(ValueError):
    """Raised when an external or model-produced object violates a contract."""


def _require(obj: dict[str, Any], key: str, typ: type | tuple[type, ...]) -> Any:
    if key not in obj:
        raise ContractError(f"missing field: {key}")
    value = obj[key]
    if not isinstance(value, typ):
        raise ContractError(f"{key} must be {typ}, got {type(value).__name__}")
    return value


def _reject_extra(obj: dict[str, Any], allowed: set[str], label: str) -> None:
    extras = sorted(set(obj) - allowed)
    if extras:
        raise ContractError(f"{label} has unsupported fields: {', '.join(extras)}")


def _validate_owner_ref(ref: str, owner: str, label: str) -> str:
    if not isinstance(ref, str) or not ref.strip():
        raise ContractError(f"{label}.source_ref must be a non-empty string")
    value = ref.strip()
    if "://" not in value:
        raise ContractError(f"{label}.source_ref must be parseable")
    scheme, remainder = value.split("://", 1)
    # Local store/fixture/snapshot references encode the authenticated owner
    # and must be checked here.  External source IDs (for example Feishu
    # spreadsheet tokens) do not; their owner binding comes from the
    # owner-scoped tool result and the loop's worker-visible reference set.
    if scheme in {"store", "fixture", "snapshot", "experiment", "tool"}:
        ref_owner = remainder.split("/", 1)[0]
        if ref_owner != owner:
            raise ContractError(f"{label}.source_ref owner mismatch")
    return value


def _validate_evidence_ref(ref: dict[str, Any], owner: str, label: str) -> dict[str, Any]:
    if not isinstance(ref, dict):
        raise ContractError(f"{label} must be an object")
    _reject_extra(ref, {"source_ref", "epistemic_status", "kind", "summary", "impact"}, label)
    _require(ref, "source_ref", str)
    _require(ref, "epistemic_status", str)
    if ref["epistemic_status"] not in EPISTEMIC_STATUSES:
        raise ContractError(f"{label}.epistemic_status is unsupported")
    _validate_owner_ref(ref["source_ref"], owner, label)
    for field in ("kind", "summary", "impact"):
        if field in ref and not isinstance(ref[field], str):
            raise ContractError(f"{label}.{field} must be a string")
    return deepcopy(ref)


def _validate_condition(condition: dict[str, Any], owner: str, label: str = "next_review_condition") -> dict[str, Any]:
    if not isinstance(condition, dict):
        raise ContractError(f"{label} must be an object")
    if "any" in condition:
        _reject_extra(condition, {"any"}, label)
        values = _require(condition, "any", list)
        if not values:
            raise ContractError(f"{label}.any must not be empty")
        return {"any": [_validate_condition(item, owner, f"{label}.any[{index}]") for index, item in enumerate(values)]}
    _reject_extra(condition, {"type", "source_ref", "version", "event_id", "task_id", "event", "reason", "not_before", "basis_ref"}, label)
    condition_type = _require(condition, "type", str)
    if condition_type not in CONCERN_CONDITION_TYPES:
        raise ContractError(f"{label}.type is unsupported")
    if condition_type == "new_source_version":
        _validate_owner_ref(_require(condition, "source_ref", str), owner, label)
        _require(condition, "version", str)
    elif condition_type == "user_reply_to":
        _require(condition, "event_id", str)
    elif condition_type == "task_event":
        _require(condition, "task_id", str)
        _require(condition, "event", str)
    elif condition_type == "next_eligible_opportunity":
        _require(condition, "reason", str)
    elif condition_type == "after_time":
        _require(condition, "not_before", str)
        _validate_owner_ref(_require(condition, "basis_ref", str), owner, label)
    return deepcopy(condition)


def validate_concern_update(update: dict[str, Any], owner: str, *, explicit_user_goal: bool = False) -> dict[str, Any]:
    """Validate one model-proposed concern delta without accepting extensions."""
    if not isinstance(update, dict):
        raise ContractError("concern update must be an object")
    _reject_extra(update, {"operation", "concern_ref", "expected_version", "changes", "basis_refs"}, "concern_update")
    operation = _require(update, "operation", str)
    if operation not in CONCERN_OPERATIONS:
        raise ContractError(f"unsupported concern operation: {operation}")
    concern_ref = _require(update, "concern_ref", str)
    if not concern_ref.strip() or len(concern_ref) > 128:
        raise ContractError("concern_ref must be a short non-empty string")
    expected_version = update.get("expected_version")
    if operation == "create":
        if expected_version is not None:
            raise ContractError("create expected_version must be null")
    elif not isinstance(expected_version, int) or isinstance(expected_version, bool) or expected_version < 0:
        raise ContractError("non-create expected_version must be a non-negative integer")
    basis_refs = _require(update, "basis_refs", list)
    normalized_basis = [_validate_evidence_ref(ref, owner, f"concern_update.basis_refs[{index}]") for index, ref in enumerate(basis_refs)]
    if not normalized_basis:
        raise ContractError("concern_update.basis_refs must not be empty")
    changes = _require(update, "changes", dict)
    _reject_extra(changes, CONCERN_CHANGE_FIELDS, "concern_update.changes")
    if "title" in changes:
        title = _require(changes, "title", str)
        if not title.strip() or len(title) > 60:
            raise ContractError("concern title must be 1-60 characters")
    if "desired_direction" in changes:
        desired = _require(changes, "desired_direction", str)
        if not desired.strip() or len(desired) > 180:
            raise ContractError("concern desired_direction must be 1-180 characters")
    if "domain" in changes and changes["domain"] not in CONCERN_DOMAINS:
        raise ContractError("concern domain is unsupported")
    if "origin" in changes:
        if changes["origin"] not in CONCERN_ORIGINS:
            raise ContractError("concern origin is unsupported")
        if changes["origin"] == "user_goal" and not explicit_user_goal:
            raise ContractError("user_goal origin requires an explicit user goal event")
    if "desire_refs" in changes:
        refs = _require(changes, "desire_refs", list)
        if not refs or any(ref not in CONCERN_DESIRE_REFS for ref in refs) or not (set(refs) & CONCERN_DESIRE_REFS):
            raise ContractError("desire_refs must cite work_trust or personal_affinity")
    if "linked_task_ids" in changes:
        linked = _require(changes, "linked_task_ids", list)
        if any(not isinstance(item, str) or not item.strip() for item in linked):
            raise ContractError("linked_task_ids must contain non-empty strings")
    for field in ("known_summary", "boundary_refs", "resolution_evidence"):
        if field in changes:
            values = _require(changes, field, list)
            changes[field] = [_validate_evidence_ref(ref, owner, f"concern_update.changes.{field}[{index}]") for index, ref in enumerate(values)]
    if "unknowns" in changes:
        unknowns = _require(changes, "unknowns", list)
        normalized_unknowns = []
        for index, unknown in enumerate(unknowns):
            item = _validate_evidence_ref(unknown, owner, f"concern_update.changes.unknowns[{index}]")
            if not item.get("impact", "").strip():
                raise ContractError("each unknown must describe its impact")
            normalized_unknowns.append(item)
        changes["unknowns"] = normalized_unknowns
    if "next_review_condition" in changes:
        changes["next_review_condition"] = _validate_condition(changes["next_review_condition"], owner)
    if "status" in changes:
        status = changes["status"]
        if status not in CONCERN_STATUSES:
            raise ContractError("concern status is unsupported")
        if operation == "update":
            raise ContractError("update cannot change concern status; use park/resolve/dismiss")
        expected_status = {"park": "parked", "resolve": "resolved", "dismiss": "dismissed"}.get(operation)
        if expected_status and status != expected_status:
            raise ContractError(f"{operation} must set status={expected_status}")
    if operation == "create":
        required = {"title", "desired_direction", "domain", "origin", "desire_refs"}
        missing = sorted(required - set(changes))
        if missing:
            raise ContractError(f"create missing fields: {', '.join(missing)}")
    elif operation == "update" and not changes:
        raise ContractError("update must change at least one field")
    elif operation == "resolve" and not changes.get("resolution_evidence"):
        raise ContractError("resolve requires resolution_evidence")
    elif operation == "park" and not changes.get("next_review_condition"):
        raise ContractError("park requires next_review_condition")
    return {
        "operation": operation,
        "concern_ref": concern_ref,
        "expected_version": expected_version,
        "changes": deepcopy(changes),
        "basis_refs": normalized_basis,
    }


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
    _reject_extra(obj, {
        "operation", "intention_ref", "desired_change", "basis_refs", "action", "strategy_reason",
        "expected_participation", "reconsider_condition", "messages", "concern_ref", "task_ref", "concern_updates",
    }, "decision")
    operation = _require(obj, "operation", str)
    if operation not in OPERATIONS:
        raise ContractError(f"unsupported operation: {operation}")
    intention_ref = obj.get("intention_ref")
    if intention_ref is not None and not isinstance(intention_ref, str):
        raise ContractError("intention_ref must be a string or null")
    _require(obj, "desired_change", str)
    basis_refs = _require(obj, "basis_refs", list)
    normalized_basis_refs: list[str] = []
    for ref in basis_refs:
        if isinstance(ref, str):
            normalized_basis_refs.append(ref)
            continue
        # Concern context deliberately carries richer evidence objects.  Some
        # providers copy those objects into the decision-level citation list,
        # whose wire contract is strings.  Normalize only the supplied
        # source_ref instead of turning a harmless representation mismatch
        # into a failed user turn.
        if isinstance(ref, dict) and isinstance(ref.get("source_ref"), str) and "://" in ref["source_ref"]:
            normalized_basis_refs.append(ref["source_ref"])
            continue
        raise ContractError("basis_refs must contain source-ref strings or evidence objects with source_ref")
    obj["basis_refs"] = normalized_basis_refs
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
    concern_ref = obj.get("concern_ref")
    if concern_ref is not None and (not isinstance(concern_ref, str) or not concern_ref.strip()):
        raise ContractError("concern_ref must be a string or null")
    task_ref = obj.get("task_ref")
    if task_ref is not None and (not isinstance(task_ref, str) or not task_ref.strip()):
        raise ContractError("task_ref must be a string or null")
    updates = obj.get("concern_updates", [])
    if not isinstance(updates, list):
        raise ContractError("concern_updates must be a list")
    if len(updates) > 3:
        raise ContractError("at most 3 concern updates are allowed")
    obj["concern_ref"] = concern_ref
    obj["task_ref"] = task_ref
    obj["concern_updates"] = updates
    return obj


def _extract_one_complete_json_object(text: str) -> tuple[dict[str, Any] | None, str | None]:
    """Extract one complete object from harmless outer prose or a code fence.

    The decoder is deliberately used from every opening brace and then reduced
    to the outermost candidates.  Nested objects therefore do not look like
    multiple decisions, while two top-level JSON objects are rejected as
    ambiguous.  An incomplete object is never repaired by truncation.
    """
    decoder = json.JSONDecoder()
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    depth = 0
    index = 0
    while index < len(text):
        marker = text[index]
        if marker == "{" and depth == 0:
            try:
                value, end = decoder.raw_decode(text, index)
            except json.JSONDecodeError:
                # Once a root opening brace is incomplete, nested braces are
                # not eligible extraction candidates.  This is what prevents
                # a truncated decision from being mistaken for its inner
                # ``action`` object.
                depth = 1
                index += 1
                continue
            if isinstance(value, dict):
                candidates.append((index, end, value))
                index = end
                continue
            depth = 1
            index += 1
            continue
        if marker == "{" and depth:
            depth += 1
        elif marker == "}" and depth:
            depth -= 1
        index += 1
    if len(candidates) != 1:
        return None, "no_single_complete_json_object" if not candidates else "multiple_complete_json_objects"
    return deepcopy(candidates[0][2]), "extract_complete_json_object"


def _repair_known_decision_types(decision: dict[str, Any], *, allow_optional_defaults: bool = False) -> tuple[dict[str, Any], list[str]]:
    """Apply only lossless container/default repairs; never invent content."""
    obj = deepcopy(decision)
    repairs: list[str] = []
    if allow_optional_defaults:
        # These fields are optional in the formal decision schema and their
        # absence has the same meaning as null.  Materialize that neutral
        # shape only for the compact wire contract, where omission saves
        # output tokens without inventing business content.
        for field in ("intention_ref", "expected_participation", "concern_ref", "task_ref"):
            if field not in obj:
                obj[field] = None
                repairs.append(f"default_{field}_null")
    if "messages" not in obj:
        obj["messages"] = []
        repairs.append("default_messages_empty_array")
    elif isinstance(obj["messages"], str):
        obj["messages"] = [obj["messages"]]
        repairs.append("messages_string_to_array")
    if "basis_refs" not in obj:
        obj["basis_refs"] = []
        repairs.append("default_basis_refs_empty_array")
    elif isinstance(obj["basis_refs"], (str, dict)):
        obj["basis_refs"] = [obj["basis_refs"]]
        repairs.append("basis_refs_single_value_to_array")
    if "concern_updates" not in obj:
        obj["concern_updates"] = []
        repairs.append("default_concern_updates_empty_array")
    elif isinstance(obj["concern_updates"], dict):
        obj["concern_updates"] = [obj["concern_updates"]]
        repairs.append("concern_update_object_to_array")
    return obj, repairs


def parse_and_validate_decision(content: Any, *, allow_optional_defaults: bool = False) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Parse a provider decision with auditable, non-semantic recovery.

    Strict JSON is attempted first.  Recovery may only unwrap one complete
    JSON object and normalize known container shapes/default empty arrays.  It
    never fills a missing business value or creates a concern update.
    """
    audit: dict[str, Any] = {
        "input_type": type(content).__name__,
        "parse_mode": "strict_json",
        "repair_type": "none",
        "validation_result": "failed",
        "raw_response": content,
    }
    candidate: dict[str, Any] | None = None
    if isinstance(content, dict):
        candidate = deepcopy(content)
        audit["parse_mode"] = "provider_object"
    elif isinstance(content, str):
        text = content.strip()
        try:
            strict_value = json.loads(text)
        except json.JSONDecodeError as exc:
            audit["strict_error"] = str(exc)
            strict_value = None
        else:
            if not isinstance(strict_value, dict):
                audit["error"] = "JSON root must be an object"
                return None, audit
            candidate = strict_value
        if candidate is None:
            candidate, extraction = _extract_one_complete_json_object(text)
            if candidate is None:
                audit["error"] = extraction
                return None, audit
            audit["parse_mode"] = extraction
            audit["repair_type"] = extraction
    else:
        audit["error"] = "provider decision must be an object or JSON string"
        return None, audit
    candidate, repairs = _repair_known_decision_types(candidate, allow_optional_defaults=allow_optional_defaults)
    if repairs:
        audit["repair_type"] = ";".join(repairs) if audit["repair_type"] == "none" else audit["repair_type"] + ";" + ";".join(repairs)
    try:
        validated = validate_decision(candidate)
    except (ContractError, TypeError) as exc:
        audit["error"] = str(exc)
        return None, audit
    audit["validation_result"] = "passed"
    return validated, audit


def validate_semantic_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    """Validate the compact model-facing semantic proposal contract.

    This contract intentionally has no database identifiers, CAS versions, or
    persistence-shaped ``changes`` object.  Those values are injected only by
    the deterministic runtime compiler after owner/evidence checks.
    """
    obj = deepcopy(proposal)
    _reject_extra(obj, {"action", "message", "evidence_refs", "semantic_delta"}, "semantic_proposal")
    action = _require(obj, "action", str)
    if action not in SEMANTIC_PROPOSAL_ACTIONS:
        raise ContractError(f"unsupported semantic proposal action: {action}")
    message = _require(obj, "message", str)
    if action == "deliver" and not message.strip():
        raise ContractError("deliver semantic proposal requires a message")
    if action == "hold" and message.strip():
        raise ContractError("hold semantic proposal message must be empty")
    evidence_refs = _require(obj, "evidence_refs", list)
    if any(not isinstance(ref, str) or not ref.strip() for ref in evidence_refs):
        raise ContractError("semantic proposal evidence_refs must contain non-empty strings")
    semantic_delta = _require(obj, "semantic_delta", dict)
    _reject_extra(semantic_delta, {"target", "value", "reason"}, "semantic_delta")
    target = _require(semantic_delta, "target", str)
    if target not in SEMANTIC_DELTA_TARGETS:
        raise ContractError(f"unsupported semantic delta target: {target}")
    reason = _require(semantic_delta, "reason", str)
    if len(reason) > SEMANTIC_OPEN_STRING_MAX:
        raise ContractError("semantic delta reason is too long")
    if target == "none":
        if "value" in semantic_delta and semantic_delta["value"] is not None:
            raise ContractError("semantic delta none value must be null or omitted")
    elif target == "status_transition":
        value = _require(semantic_delta, "value", str)
        if value not in SEMANTIC_STATUS_TRANSITIONS:
            raise ContractError(f"unsupported status transition: {value}")
    elif target == "desired_direction" or target == "next_review_condition":
        value = _require(semantic_delta, "value", str)
        if not value.strip() or len(value) > SEMANTIC_OPEN_STRING_MAX:
            raise ContractError(f"{target} value must be a non-empty string of at most {SEMANTIC_OPEN_STRING_MAX} characters")
    elif target == "unknowns":
        values = _require(semantic_delta, "value", list)
        if not values or len(values) > SEMANTIC_UNKNOWN_MAX_ITEMS:
            raise ContractError(f"unknowns value must contain 1-{SEMANTIC_UNKNOWN_MAX_ITEMS} items")
        for index, value in enumerate(values):
            if not isinstance(value, str) or not value.strip() or len(value) > SEMANTIC_UNKNOWN_ITEM_MAX:
                raise ContractError(f"unknowns[{index}] must be a non-empty string of at most {SEMANTIC_UNKNOWN_ITEM_MAX} characters")
    return obj


def parse_and_validate_semantic_proposal(content: Any) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Strictly parse one complete semantic proposal without semantic repair."""
    audit: dict[str, Any] = {
        "input_type": type(content).__name__,
        "parse_mode": "strict_json",
        "repair_type": "none",
        "validation_result": "failed",
        "raw_response": content,
    }
    candidate: dict[str, Any] | None = None
    if isinstance(content, dict):
        candidate = deepcopy(content)
        audit["parse_mode"] = "provider_object"
    elif isinstance(content, str):
        text = content.strip()
        try:
            strict_value = json.loads(text)
        except json.JSONDecodeError as exc:
            audit["strict_error"] = str(exc)
            candidate, extraction = _extract_one_complete_json_object(text)
            if candidate is None:
                audit["error"] = extraction
                return None, audit
            audit["parse_mode"] = extraction
        else:
            if not isinstance(strict_value, dict):
                audit["error"] = "JSON root must be an object"
                return None, audit
            candidate = strict_value
    else:
        audit["error"] = "semantic proposal must be an object or JSON string"
        return None, audit
    try:
        validated = validate_semantic_proposal(candidate)
    except (ContractError, TypeError) as exc:
        audit["error"] = str(exc)
        return None, audit
    audit["validation_result"] = "passed"
    return validated, audit


def validate_concern_updates(updates: list[dict[str, Any]], owner: str, *, explicit_user_goal: bool = False) -> list[dict[str, Any]]:
    if not isinstance(updates, list):
        raise ContractError("concern_updates must be a list")
    if len(updates) > 3:
        raise ContractError("at most 3 concern updates are allowed")
    return [validate_concern_update(item, owner, explicit_user_goal=explicit_user_goal) for item in updates]


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
