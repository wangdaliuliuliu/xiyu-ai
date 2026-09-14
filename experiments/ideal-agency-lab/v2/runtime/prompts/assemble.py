"""Prompt assembly. The worker receives structured context and no oracle."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from contracts.schemas import ACTION_TYPES, OPERATIONS


def assemble(context: dict[str, Any], *, event: dict[str, Any], tool_result: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "prompt_version": context["stable"]["prompt_version"],
        "system": deepcopy(context["stable"]),
        "prompt_sections": deepcopy(context["stable"].get("prompt_sections", [])),
        "current": deepcopy(context["current"]),
        "catalog": deepcopy(context["catalog"]),
        "responsibilities": deepcopy(context.get("responsibilities", [])),
        "concerns": deepcopy(context.get("concerns", {"enabled": False, "selected": [], "catalog": None, "updates_since_last_event": []})),
        "event": deepcopy(event),
        "tool_result": deepcopy(tool_result),
        "output_contract": {
            "json_only": True,
            "fields": ["operation", "intention_ref", "desired_change", "basis_refs", "action", "strategy_reason", "expected_participation", "reconsider_condition", "messages", "concern_ref", "task_ref", "concern_updates"],
            "operation_values": sorted(OPERATIONS),
            "action_type_values": sorted(ACTION_TYPES),
            "action_required_fields": ["type", "args", "expected_result"],
            "messages_allowed_only_when_action_type": "deliver",
            "messages_type": "array_of_strings",
            "basis_refs_type": "array_of_source_ref_strings; use only the source_ref string, not the surrounding evidence object",
            "concern_update_basis_refs_type": "array_of_evidence_objects with source_ref, epistemic_status and optional kind/summary/impact",
            "deliver_action_args": "object; do not put messages inside action.args",
            "reference_rules": [
                "intention_ref must be null unless current.continuity.resumable_intention contains that exact intention_id",
                "concern_ref and task_ref must be null unless the exact reference is present in the supplied current context",
                "event_id is never an intention_ref, concern_ref, or task_ref",
            ],
            "concern_updates_max": 3,
            "additional_properties": False,
        },
    }


def assemble_compact_continuation(context: dict[str, Any]) -> dict[str, Any]:
    """Assemble the model-facing semantic proposal contract.

    Persistence-shaped fields are deliberately absent.  The loop compiles the
    returned proposal into the existing formal decision after deterministic
    owner/evidence/CAS checks.
    """
    semantic_delta = context["continuation"].get("semanticDelta") or {}
    allowed_targets = list(semantic_delta.get("allowed_targets") or [])
    if "none" not in allowed_targets:
        allowed_targets.append("none")
    return {
        "prompt_version": context["prompt_version"],
        "system": {
            "prompt_version": context["prompt_version"],
            "mode": "retrieved_continuation",
            "instruction": (
                "仅返回一个完整JSON对象，字段只能是 action、message、evidence_refs、semantic_delta。"
                "这是已完成资料读取后的续接；不要调用工具，不要输出 operation、concern_ref、expected_version、"
                "changes 或其他持久化字段。evidence_refs 只能引用 supplied evidence_delta 中已读取的 source_ref；"
                "message 只写本次证据支持的短句。semantic_delta.target=none 时不改持续状态；否则 target 只能使用"
                " output_contract.allowed_targets，且必须提供非空 value 只表达模型明确提出的单字段变化；"
                "target=none 时 value 只能省略或为 null，"
                "不要编造目录外实体或经营事实。"
            ),
        },
        "current": {
            "continuity": deepcopy(context["continuity"]),
            "boundaries": deepcopy(context["boundaries"]),
        },
        "catalog": deepcopy(context["catalog"]),
        "responsibilities": deepcopy(context["responsibilities"]),
        "concerns": deepcopy(context["concerns"]),
        "source_binding": deepcopy(context["source_binding"]),
        "continuation": deepcopy(context["continuation"]),
        "evidence_delta": deepcopy(context["evidence_delta"]),
        "event": deepcopy(context["event"]),
        "output_contract": {
            "json_only": True,
            "required_fields": ["action", "message", "evidence_refs", "semantic_delta"],
            "action_values": ["deliver", "hold"],
            "message": {"type": "string", "non_empty_when": "deliver", "empty_when": "hold"},
            "evidence_refs": {"type": "array_of_source_ref_strings", "must_use": "evidence_delta.source_ref"},
            "semantic_delta": {
                "required_fields": ["target", "reason"],
                "value_required_when_target_is_not_none": True,
                "target_values": allowed_targets,
                "target_value_rules": {
                    "status_transition": {
                        "type": "enum",
                        "values": ["keep_active", "park", "resolve", "dismiss"],
                    },
                    "desired_direction": {"type": "string", "max_length": 180},
                    "unknowns": {"type": "array_of_strings", "min_items": 1, "max_items": 3, "item_max_length": 120},
                    "next_review_condition": {"type": "string", "max_length": 180},
                    "none": {"type": "null_or_omitted"},
                },
                "target_guidance": deepcopy(semantic_delta.get("target_guidance") or {}),
                "single_target_only": True,
                "value_rule": "target-specific value only; no database wrapper",
            },
            "reference_rules": ["do not emit concern ids, versions, operation names, or changes objects"],
            "additional_properties": False,
        },
    }
