"""Static dependency-direction check for the formal runner."""
from __future__ import annotations

import ast
import pathlib


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def check_dependencies(v2_root: pathlib.Path) -> dict:
    rules = {
        "runtime_no_fixture_eval_export": (v2_root / "runtime", {"fixtures", "evaluation", "export"}),
        "adapters_no_controller": (v2_root / "adapters", {"controller"}),
    }
    violations = []
    checked = []
    for name, (root, forbidden) in rules.items():
        for path in sorted(root.rglob("*.py")):
            imported = _imports(path); checked.append(str(path))
            bad = sorted(imported & forbidden)
            if bad:
                violations.append({"rule": name, "file": str(path), "imports": bad})
    for path in sorted((v2_root / "evaluation").rglob("*.py")):
        checked.append(str(path))
    return {"schemaVersion": "dependency-check-v2", "status": "passed" if not violations else "failed", "checked_files": checked, "violations": violations}

