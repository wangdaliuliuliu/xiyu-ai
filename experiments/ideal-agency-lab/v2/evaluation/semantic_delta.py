"""Audit pre-registered semantic deltas without inventing business facts."""
from __future__ import annotations

from copy import deepcopy
from typing import Any


def _patch_fields(value: Any) -> set[str]:
    fields: set[str] = set()
    if not isinstance(value, list):
        return fields
    for item in value:
        if not isinstance(item, dict):
            continue
        changes = item.get("changes")
        if isinstance(changes, dict):
            fields.update(str(key) for key in changes)
    return fields


def _semantic_proposal(traces: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Read the proposal from trace without repairing or inventing it."""
    for row in reversed(traces):
        if row.get("kind") == "semantic_proposal_compiled" and isinstance(row.get("validated_proposal"), dict):
            return deepcopy(row["validated_proposal"])
        if row.get("kind") == "semantic_proposal_parse" and isinstance(row.get("raw_response"), dict):
            return deepcopy(row["raw_response"])
    return None


def _proposal_target(proposal: dict[str, Any] | None) -> str | None:
    if not isinstance(proposal, dict):
        return None
    delta = proposal.get("semantic_delta")
    if not isinstance(delta, dict):
        return None
    target = delta.get("target")
    if isinstance(target, str):
        return target
    # Historical R6/R7 traces used kind/field.  Keep this read-only
    # compatibility for audit evidence; the new parser rejects that shape.
    if delta.get("kind") == "none":
        return "none"
    if delta.get("kind") == "update" and isinstance(delta.get("field"), str):
        return str(delta["field"])
    return None


def _trace_evidence_refs(traces: list[dict[str, Any]]) -> set[str]:
    refs: set[str] = set()
    for row in traces:
        for key in ("retrievedSourceRefs", "retrieved_source_refs", "autoRecordedEvidenceRefs", "auto_recorded_evidence_refs", "actionEvidenceRefs", "action_evidence_refs"):
            value = row.get(key)
            if isinstance(value, list):
                refs.update(str(item) for item in value if isinstance(item, str) and item)
    return refs


def audit_semantic_delta(case: dict[str, Any], traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Require a model patch or an explicit deterministic semantic rule.

    Auto-recorded source evidence is intentionally not sufficient: it changes
    what is known, not the user's standing direction.  Empty model updates are
    therefore valid for evidence-only cases and invalid for a case whose
    manifest explicitly declares a semantic delta.
    """
    spec = deepcopy(case.get("semantic_delta_evaluation") or case.get("semantic_delta") or {
        "exists": False,
        "mode": "allow_none",
        "event_indices": [],
        "expected_fields": [],
        "basis": "not_registered",
        "evidence": [],
    })
    expected = {str(item) for item in spec.get("expected_fields", [])}
    expected_targets = {str(item) for item in spec.get("expected_targets", [])}
    allowed_targets = {str(item) for item in spec.get("allowed_targets", [])}
    model_fields: set[str] = set()
    deterministic_fields: set[str] = set()
    model_updates = 0
    deterministic_updates = 0
    for row in traces:
        model_fields.update(_patch_fields(row.get("acceptedConcernPatches") or row.get("accepted_concern_patches")))
        model_fields.update(_patch_fields(row.get("modelConcernUpdates") or row.get("model_concern_updates")))
        if row.get("kind") == "semantic_delta_deterministic":
            deterministic_updates += 1
            deterministic_fields.update(str(key) for key in (row.get("changes") or {}))
        if row.get("modelConcernUpdates") or row.get("model_concern_updates"):
            model_updates += 1
    matched_model = sorted(model_fields & expected)
    matched_deterministic = sorted(deterministic_fields & expected)
    exists = bool(spec.get("exists")) or spec.get("mode") == "required"
    proposal = _semantic_proposal(traces)
    proposal_delta = proposal.get("semantic_delta") if isinstance(proposal, dict) else None
    proposal_target = _proposal_target(proposal)
    proposal_none = proposal_target == "none"
    proposal_none_reasoned = proposal_none and isinstance(proposal_delta.get("reason"), str) and bool(proposal_delta.get("reason", "").strip())
    proposal_evidence_refs = set(proposal.get("evidence_refs") or []) if isinstance(proposal, dict) else set()
    trace_evidence_refs = _trace_evidence_refs(traces)
    proposal_evidence_bound = bool(proposal_evidence_refs) and proposal_evidence_refs <= trace_evidence_refs
    proposal_target_allowed = proposal_target in allowed_targets if allowed_targets else proposal_target is not None
    target_matches_objective = proposal_target in expected_targets if expected_targets else bool(matched_model)
    proposal_grounded = True
    for row in traces:
        if row.get("kind") == "semantic_proposal_compiled":
            grounding = row.get("grounding") or {}
            if grounding.get("unsupported_positive_claim"):
                proposal_grounded = False
    none_acceptance = proposal_none and proposal_none_reasoned and proposal_evidence_bound and proposal_grounded
    if exists:
        status = "passed" if target_matches_objective and (matched_model or matched_deterministic) else "failed"
        if proposal_none:
            status = "failed"
            reason = "registered_semantic_delta_cannot_be_none"
        elif not proposal_target_allowed:
            status = "failed"
            reason = "semantic_target_not_allowed_for_fixture"
        elif not target_matches_objective:
            status = "failed"
            reason = "semantic_target_does_not_match_fixture_objective"
        else:
            reason = "model_patch_or_deterministic_rule_matched" if status == "passed" else "semantic_delta_requires_model_or_deterministic_change"
    else:
        status = "passed" if not model_fields and not deterministic_fields and (proposal is None or none_acceptance) else "failed"
        if status == "passed":
            reason = "evidence_only_none_with_reason_and_bound_evidence" if proposal is not None else "evidence_only_or_empty_updates"
        elif model_fields or deterministic_fields:
            reason = "unexpected_semantic_patch_for_evidence_only_case"
        else:
            reason = "semantic_none_requires_reason_bound_evidence_and_grounding"
    return {
        "status": status,
        "exists": exists,
        "event_indices": list(spec.get("event_indices", [])),
        "expected_fields": sorted(expected),
        "matched_model_fields": matched_model,
        "matched_deterministic_fields": matched_deterministic,
        "model_update_events": model_updates,
        "deterministic_update_events": deterministic_updates,
        "proposal_present": proposal is not None,
        "proposal_none": proposal_none,
        "proposal_none_reasoned": proposal_none_reasoned,
        "proposal_target": proposal_target,
        "proposal_target_allowed": proposal_target_allowed,
        "expected_targets": sorted(expected_targets),
        "allowed_targets": sorted(allowed_targets),
        "target_matches_objective": target_matches_objective,
        "proposal_evidence_refs": sorted(proposal_evidence_refs),
        "proposal_evidence_bound": proposal_evidence_bound,
        "proposal_grounded": proposal_grounded,
        "basis": spec.get("basis"),
        "evidence": list(spec.get("evidence", [])),
        "reason": reason,
    }
