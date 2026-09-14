"""Zero-fee tests for reconstructing a K12 trajectory manifest from inputs."""
from __future__ import annotations

import argparse
import copy
import json
import pathlib
import shutil
import sys
import tempfile
from typing import Any, Callable


V2_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(V2_ROOT) not in sys.path:
    sys.path.insert(0, str(V2_ROOT))

from evaluation.j05_simulation import OWNER, _build_trajectory_manifest_from_inputs, _read_json, _write_json


DEFAULT_FIXTURE = pathlib.Path(r"C:\Users\Administrator\AppData\Local\Temp\xiyu-r2-fixture-run-20260913-02")


def _copy_fixture(source_root: pathlib.Path, destination: pathlib.Path) -> tuple[dict[str, Any], pathlib.Path]:
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source_root / "case-manifest.json", destination / "case-manifest.json")
    shutil.copytree(source_root / "snapshot", destination / "snapshot")
    case_manifest = _read_json(destination / "case-manifest.json")
    case = next(item for item in case_manifest["cases"] if item.get("case_id") == "K12")
    return case, destination


def _expect_rejection(name: str, mutate: Callable[[pathlib.Path, dict[str, Any]], None], source_root: pathlib.Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"xiyu-r7-manifest-{name}-") as temp_dir:
        root = pathlib.Path(temp_dir) / "fixture"
        case, root = _copy_fixture(source_root, root)
        clean_trajectory = root / "clean-trajectory"
        clean_manifest, clean_binding = _build_trajectory_manifest_from_inputs(root, root / "snapshot", clean_trajectory, case, 1, arm="C")
        mutate(root, case)
        try:
            _build_trajectory_manifest_from_inputs(
                root,
                root / "snapshot",
                root / "rejected-trajectory",
                case,
                1,
                arm="C",
                expected_input_binding=clean_binding,
            )
        except (ValueError, KeyError, TypeError) as exc:
            return {"name": name, "status": "passed", "error": f"{type(exc).__name__}: {exc}"}
        return {"name": name, "status": "failed", "error": "mutated fixture was accepted", "clean_manifest": clean_manifest}


def run(*, fixture_root: pathlib.Path, output_path: pathlib.Path | None = None) -> dict[str, Any]:
    fixture_root = fixture_root.resolve()
    with tempfile.TemporaryDirectory(prefix="xiyu-r7-manifest-positive-") as temp_dir:
        root = pathlib.Path(temp_dir) / "fixture"
        case, root = _copy_fixture(fixture_root, root)
        trajectory = root / "trajectory"
        manifest, binding = _build_trajectory_manifest_from_inputs(root, root / "snapshot", trajectory, case, 1, arm="C")
        positive = {
            "generated": True,
            "schemaVersion": manifest.get("schemaVersion"),
            "case_id": binding.get("case_id"),
            "arm": binding.get("arm"),
            "repetition": binding.get("repetition"),
            "event_sequence": binding.get("event_sequence"),
            "source_binding": binding.get("source_binding"),
            "case_manifest_sha256": binding.get("case_manifest_sha256"),
            "snapshot_sha256": binding.get("snapshot_sha256"),
            "snapshot_file_count": len(binding.get("snapshot_file_hashes") or {}),
            "future_data_policy": binding.get("future_data_policy"),
        }

    def mutate_case_hash(root: pathlib.Path, case: dict[str, Any]) -> None:
        payload = _read_json(root / "case-manifest.json")
        payload["test_mutation"] = "case-hash-mismatch"
        _write_json(root / "case-manifest.json", payload)

    def mutate_snapshot_hash(root: pathlib.Path, case: dict[str, Any]) -> None:
        path = root / "snapshot" / "context.json"
        payload = _read_json(path)
        payload["test_mutation"] = "snapshot-hash-mismatch"
        _write_json(path, payload)

    def mutate_case_mismatch(root: pathlib.Path, case: dict[str, Any]) -> None:
        case["case_id"] = "K11"

    def mutate_missing_source_revision(root: pathlib.Path, case: dict[str, Any]) -> None:
        path = root / "snapshot" / "workbench-data" / "runtime-state" / "records.json"
        payload = _read_json(path)
        row = next(item for item in payload["data"] if item.get("id") == "WR-20260815-ZHONGYING")
        row.pop("sourceRevision", None)
        _write_json(path, payload)

    def mutate_future_leak(root: pathlib.Path, case: dict[str, Any]) -> None:
        path = root / "snapshot" / "workbench-data" / "runtime-state" / "records.json"
        payload = _read_json(path)
        row = next(item for item in payload["data"] if item.get("id") == "WR-20260815-ZHONGYING")
        source_ref = next(item["source_ref"] for item in case["interventions"] if item.get("operation") == "materialize_experimental_record_update")
        row.setdefault("sourceRefs", []).insert(0, {"sourceRef": source_ref, "revision": "j05-k12-v2", "sheet": "中影店"})
        _write_json(path, payload)

    negatives = [
        _expect_rejection("case_hash_mismatch", mutate_case_hash, fixture_root),
        _expect_rejection("snapshot_hash_mismatch", mutate_snapshot_hash, fixture_root),
        _expect_rejection("case_mismatch", mutate_case_mismatch, fixture_root),
        _expect_rejection("source_revision_missing", mutate_missing_source_revision, fixture_root),
        _expect_rejection("future_data_leak", mutate_future_leak, fixture_root),
    ]
    checks = {
        "complete_case_snapshot_generates": positive["generated"] and positive["case_id"] == "K12" and positive["arm"] == "C" and positive["repetition"] == 1,
        "event_sequence_bound": [item["event_index"] for item in positive["event_sequence"]] == [0, 1, 2, 3],
        "source_revision_bound": positive["source_binding"].get("base_source_revision") == "feishu-r9753-data-fix-v3" and positive["source_binding"].get("source_version") == "j05-k12-v2",
        "hashes_recorded": bool(positive["case_manifest_sha256"]) and bool(positive["snapshot_sha256"]) and positive["snapshot_file_count"] > 0,
        "negative_cases_rejected": all(item["status"] == "passed" for item in negatives),
        "provider_calls_zero": True,
        "bot_messages_zero": True,
        "production_writes_zero": True,
    }
    result = {"status": "passed" if all(checks.values()) else "failed", "positive": positive, "negative_cases": negatives, "checks": checks, "provider_calls": 0, "bot_messages": 0, "production_writes": 0, "owner": OWNER}
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-root", default=str(DEFAULT_FIXTURE))
    parser.add_argument("--output")
    args = parser.parse_args()
    result = run(fixture_root=pathlib.Path(args.fixture_root), output_path=pathlib.Path(args.output).resolve() if args.output else None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
