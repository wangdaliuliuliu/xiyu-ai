"""Prompt assembly. The worker receives structured context and no oracle."""
from __future__ import annotations

from copy import deepcopy
from typing import Any


def assemble(context: dict[str, Any], *, event: dict[str, Any], tool_result: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "prompt_version": context["stable"]["prompt_version"],
        "system": deepcopy(context["stable"]),
        "current": deepcopy(context["current"]),
        "catalog": deepcopy(context["catalog"]),
        "event": deepcopy(event),
        "tool_result": deepcopy(tool_result),
        "output_contract": {
            "json_only": True,
            "fields": ["operation", "intention_ref", "desired_change", "basis_refs", "action", "strategy_reason", "expected_participation", "reconsider_condition", "messages"],
        },
    }

