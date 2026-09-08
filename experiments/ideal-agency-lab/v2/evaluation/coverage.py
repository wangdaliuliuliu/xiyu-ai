"""Coverage matrix generation; every required identifier is explicit."""
from __future__ import annotations

import json
import pathlib
from typing import Any


def required_ids() -> dict[str, list[str]]:
    return {
        "goals": [f"G{i:02d}" for i in range(1, 15)],
        "families": [f"{group}{i:02d}" for group in "ABCD" for i in range(1, 7)],
        "reliability": [f"R{i:02d}" for i in range(1, 13)],
        "integration": [f"I{i:02d}" for i in range(1, 13)],
        "mutations": [f"M{i:02d}" for i in range(1, 17)] + [f"X{i:02d}" for i in range(1, 25)],
    }


def build_coverage(*, evidence_root: str | None = None) -> dict[str, Any]:
    matrix = {}
    for group, ids in required_ids().items():
        matrix[group] = {
            item: {"status": "not_run", "normal": [], "failure": [], "recovery": [], "evidence": []}
            for item in ids
        }
    path_semantics = {
        "P01": ("explicit_work_query", "tool success", "tool failure"), "P02": ("work_discussion", "missing context", "new constraint"),
        "P03": ("personal_exchange", "boundary", "new personal input"), "P04": ("mixed_request", "tool error", "same-turn delivery"),
        "P05": ("free_opportunity", "all candidates wait", "later opportunity"), "P06": ("task_due", "stale task", "updated task"),
        "P07": ("knowledge_question", "known fact", "user answer"), "P08": ("knowledge_answer", "short acknowledgement", "explicit confirmation"),
        "P09": ("research", "no result", "source update"), "P10": ("media_prepare", "provider failure", "same intention text fallback"),
        "P11": ("media_or_text_delivery", "partial receipt", "receipt recovery"), "P12": ("wait_or_silent_prepare", "window closed", "next legal event"),
        "P13": ("tool_failure", "timeout/forbidden", "bounded retry"), "P14": ("delivery_failure_unknown", "unknown receipt", "idempotency query"),
        "P15": ("silence_observed", "no response", "strategy revision"), "P16": ("business_insertion", "stale prepared asset", "validated resume"),
        "P17": ("pause_or_reject", "local boundary", "new allowed topic"), "P18": ("restart_or_concurrency", "lease/CAS conflict", "persistent recovery"),
    }
    paths = {key: {"semantic_branch": value[0], "normal": [value[0]], "failure": [value[1]], "recovery": [value[2]], "evidence": []} for key, value in path_semantics.items()}
    return {"schemaVersion": "path-coverage-v2", "status": "not_run", "matrix": matrix, "paths": paths, "evidence_root": evidence_root}


def write_coverage(path: pathlib.Path, coverage: dict[str, Any]) -> None:
    path.write_text(json.dumps(coverage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
