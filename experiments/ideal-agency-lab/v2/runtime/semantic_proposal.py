"""Compile a compact semantic proposal into the existing formal decision.

The model-facing object is intentionally not persistence-shaped.  This module
is the only place that may add a selected concern id, CAS version, and formal
evidence objects before the unchanged EventStore path validates and commits
the resulting patch.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from contracts.schemas import (
    ContractError,
    SEMANTIC_DELTA_TARGETS,
    SEMANTIC_OPEN_STRING_MAX,
    SEMANTIC_STATUS_TRANSITIONS,
    SEMANTIC_UNKNOWN_ITEM_MAX,
    SEMANTIC_UNKNOWN_MAX_ITEMS,
    validate_concern_updates,
)
from runtime.grounding import assess_messages


class SemanticProposalError(ValueError):
    pass


_ALLOWED_COMPILED_TARGETS = {"status_transition", "desired_direction", "unknowns", "next_review_condition", "none"}
_CONCERN_STATUSES = {"active", "parked", "resolved", "dismissed"}


def _source_refs(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, dict):
        for key in ("source_ref", "source_refs"):
            current = value.get(key)
            if isinstance(current, str) and current.strip():
                refs.add(current.strip())
            elif isinstance(current, list):
                refs.update(str(item).strip() for item in current if isinstance(item, str) and item.strip())
        for item in value.values():
            refs.update(_source_refs(item))
    elif isinstance(value, list):
        for item in value:
            refs.update(_source_refs(item))
    return refs


def _available_evidence_refs(context: dict[str, Any]) -> set[str]:
    evidence = context.get("evidence_delta") or {}
    refs = _source_refs(evidence)
    # The compiler may only accept the one authoritative delta emitted by the
    # compact builder.  Selected concern history is intentionally not a new
    # read and therefore is not silently promoted to current evidence.
    return refs


def _validate_value(target: str, value: Any, allowed_refs: set[str]) -> Any:
    if target == "status_transition":
        if not isinstance(value, str) or value not in SEMANTIC_STATUS_TRANSITIONS:
            raise SemanticProposalError("status_transition value is unsupported")
    elif target == "desired_direction":
        if not isinstance(value, str) or not value.strip() or len(value) > SEMANTIC_OPEN_STRING_MAX:
            raise SemanticProposalError("desired_direction value must be a non-empty short string")
    elif target == "unknowns":
        if not isinstance(value, list) or not value or len(value) > SEMANTIC_UNKNOWN_MAX_ITEMS:
            raise SemanticProposalError(f"unknowns value must contain 1-{SEMANTIC_UNKNOWN_MAX_ITEMS} items")
        for index, item in enumerate(value):
            if not isinstance(item, str) or not item.strip() or len(item) > SEMANTIC_UNKNOWN_ITEM_MAX:
                raise SemanticProposalError(f"unknowns[{index}] must be a non-empty short string")
    elif target == "next_review_condition":
        if not isinstance(value, str) or not value.strip() or len(value) > SEMANTIC_OPEN_STRING_MAX:
            raise SemanticProposalError("next_review_condition value must be a non-empty short string")
    else:
        raise SemanticProposalError(f"semantic target is not compilable: {target}")
    return deepcopy(value)


def _allowed_targets(context: dict[str, Any]) -> set[str]:
    semantic = (context.get("continuation") or {}).get("semanticDelta") or {}
    values = semantic.get("allowed_targets") or semantic.get("allowedTargets")
    if isinstance(values, list):
        return {str(value) for value in values}
    # The previous compact contract exposed formal change fields.  Keep this
    # mapping only for offline history/replay; new prompts always expose
    # allowed target names explicitly.
    old_fields = semantic.get("expected_update_fields") or []
    mapping = {"status": "status_transition"}
    return {mapping.get(str(value), str(value)) for value in old_fields} | {"none"}


def _next_review_condition(value: str, *, context: dict[str, Any], source_ref: str) -> dict[str, Any]:
    evidence = context.get("evidence_delta") or {}
    version = evidence.get("version")
    if version is None:
        current = ((context.get("concerns") or {}).get("selected") or [{}])[0]
        version = (current.get("next_review_condition") or {}).get("version")
    if version is None:
        raise SemanticProposalError("next_review_condition requires a source version")
    # The user-facing value remains an open short description.  The only
    # persistence shape the compiler may construct is a source-bound review
    # condition tied to the evidence returned this turn.
    return {"type": "new_source_version", "source_ref": source_ref, "version": str(version)}


def _unknown_evidence(value: list[str], source_ref: str) -> list[dict[str, Any]]:
    return [
        {
            "source_ref": source_ref,
            "epistemic_status": "unknown",
            "kind": "semantic_proposal_unknown",
            "summary": item,
            "impact": "该未知项尚未核实，会影响当前判断。",
        }
        for item in value
    ]


def compile_semantic_proposal(proposal: dict[str, Any], *, context: dict[str, Any], owner: str) -> dict[str, Any]:
    """Return a formal internal decision or reject before persistence/send."""
    selected = (context.get("concerns") or {}).get("selected") or []
    if not selected:
        raise SemanticProposalError("no_selected_concern_for_semantic_proposal")
    concern = selected[0]
    concern_id = concern.get("id")
    if not isinstance(concern_id, str) or not concern_id:
        raise SemanticProposalError("selected_concern_id_missing")
    try:
        expected_version = int(concern["version"])
    except (KeyError, TypeError, ValueError):
        raise SemanticProposalError("selected_concern_version_missing")

    allowed_refs = _available_evidence_refs(context)
    evidence_refs = [str(ref).strip() for ref in proposal.get("evidence_refs", [])]
    unknown_refs = sorted(set(evidence_refs) - allowed_refs)
    if unknown_refs:
        raise SemanticProposalError("evidence_ref_not_retrieved:" + ",".join(unknown_refs))

    delta = proposal["semantic_delta"]
    target = delta["target"]
    if target not in SEMANTIC_DELTA_TARGETS or target not in _ALLOWED_COMPILED_TARGETS:
        raise SemanticProposalError("semantic_target_is_unsupported")
    allowed_targets = _allowed_targets(context)
    if target != "none" and target not in allowed_targets:
        raise SemanticProposalError("semantic_target_not_preregistered:" + target)
    patch: dict[str, Any] | None = None
    if target != "none":
        value = _validate_value(target, delta.get("value"), allowed_refs)
        operation = "update"
        if not evidence_refs:
            raise SemanticProposalError("semantic_update_requires_current_evidence")
        source_ref = evidence_refs[0]
        evidence_objects = [
            {"source_ref": ref, "epistemic_status": "observed"}
            for ref in evidence_refs
        ]
        if target == "status_transition":
            transition = value
            if transition == "keep_active":
                # Keeping an already active concern is a valid semantic
                # decision but does not need a persistence mutation.
                patch = None
            elif transition == "park":
                operation = "park"
                current_condition = concern.get("next_review_condition")
                if not isinstance(current_condition, dict):
                    raise SemanticProposalError("park_requires_existing_review_condition")
                changes = {"status": "parked", "next_review_condition": deepcopy(current_condition)}
            elif transition == "resolve":
                operation = "resolve"
                changes = {
                    "status": "resolved",
                    # The formal concern contract requires resolution evidence;
                    # the model only selects the transition, so bind the
                    # evidence already retrieved this turn here.
                    "resolution_evidence": deepcopy(evidence_objects),
                }
            elif transition == "dismiss":
                operation = "dismiss"
                changes = {"status": "dismissed"}
            else:
                raise SemanticProposalError("status_transition_value_is_unsupported")
        elif target == "desired_direction":
            changes = {"desired_direction": value}
        elif target == "unknowns":
            changes = {"unknowns": _unknown_evidence(value, source_ref)}
        elif target == "next_review_condition":
            changes = {"next_review_condition": _next_review_condition(value, context=context, source_ref=source_ref)}
        else:
            raise SemanticProposalError("semantic_target_is_unsupported")
        if patch is None and target == "status_transition" and value == "keep_active":
            pass
        elif patch is None:
            patch = {
                "operation": operation,
                "concern_ref": concern_id,
                "expected_version": expected_version,
                "changes": changes,
                "basis_refs": evidence_objects,
            }
            try:
                patch = validate_concern_updates([patch], owner)[0]
            except (ContractError, TypeError) as exc:
                raise SemanticProposalError("compiled_concern_update_invalid:" + str(exc))

    action = proposal["action"]
    is_delivery = action == "deliver"
    decision = {
        "operation": "continue",
        "intention_ref": None,
        "desired_change": str(delta.get("value") or "交付已读证据") if target != "none" else "交付已读证据",
        "basis_refs": evidence_refs,
        "action": {
            "type": "deliver" if is_delivery else "wait",
            "args": {},
            "expected_result": "交付语义提案结果" if is_delivery else "等待新的相关证据",
        },
        "strategy_reason": delta.get("reason", ""),
        "expected_participation": None,
        "reconsider_condition": "收到新的相关证据后再判断",
        "messages": [proposal["message"]] if is_delivery else [],
        "concern_ref": concern_id,
        "task_ref": None,
        "concern_updates": [patch] if patch else [],
    }
    grounding = assess_messages(decision, context)
    if grounding.unsupported_positive_claim:
        raise SemanticProposalError("message_business_fact_without_worker_visible_evidence")
    return {
        "proposal": deepcopy(proposal),
        "validated_proposal": deepcopy(proposal),
        "compiled_concern_patch": deepcopy(patch),
        "decision": decision,
        "allowed_evidence_refs": sorted(allowed_refs),
        "expected_version": expected_version,
        "grounding": {
            "relevant_evidence_present": grounding.relevant_evidence_present,
            "unsupported_positive_claim": grounding.unsupported_positive_claim,
            "evidence_mode": grounding.evidence_mode,
            "evidence_refs": list(grounding.evidence_refs),
        },
    }
