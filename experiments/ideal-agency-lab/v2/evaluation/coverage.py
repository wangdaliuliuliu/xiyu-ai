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
    paths = {f"P{i:02d}": {"normal": [], "failure": [], "recovery": [], "evidence": []} for i in range(1, 19)}
    return {"schemaVersion": "path-coverage-v2", "status": "not_run", "matrix": matrix, "paths": paths, "evidence_root": evidence_root}


def write_coverage(path: pathlib.Path, coverage: dict[str, Any]) -> None:
    path.write_text(json.dumps(coverage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

