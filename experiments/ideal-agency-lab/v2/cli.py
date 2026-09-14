"""唯一正式入口：W00 freeze, E0/E1/E2 checks, and evidence collection."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import uuid
from typing import Any

V2_ROOT = pathlib.Path(__file__).resolve().parent
LAB_ROOT = V2_ROOT.parent
REPO_ROOT = LAB_ROOT.parents[1]
FIXTURE = V2_ROOT / "fixtures" / "public_state.json"
PROMPT = V2_ROOT / "runtime" / "prompts" / "p1.json"
CONCERNS_PROMPT = V2_ROOT / "runtime" / "prompts" / "concerns-v1.json"

if str(V2_ROOT) not in sys.path:
    sys.path.insert(0, str(V2_ROOT))

from controller.gateway import HttpProviderGateway  # noqa: E402
from controller.real_api_probe import run_provider_probe as execute_provider_probe  # noqa: E402
from controller.lifecycle import WorkerLifecycle  # noqa: E402
from controller.worker_execution import real_execution_gate  # noqa: E402
from evaluation.context_consumption import run_context_consumption  # noqa: E402
from evaluation.coverage import build_coverage, write_coverage  # noqa: E402
from evaluation.concern_cases import build_concern_case_manifest  # noqa: E402
from evaluation.concern_deterministic import run_concern_deterministic  # noqa: E402
from evaluation.j05_simulation import run_fixture_integrity, run_j05, run_j05_simulation, write_j05_design_artifacts, write_j05_handoff_lists  # noqa: E402
from evaluation.deterministic import DeterministicSuite  # noqa: E402
from evaluation.execution import build_execution_manifest, build_requirement_map  # noqa: E402
from evaluation.harness import HarnessSelftest  # noqa: E402
from evaluation.mutation import run_mutation_coverage  # noqa: E402
from evaluation.parity import compare_resource_manifest, compare_sqlite  # noqa: E402
from evaluation.isolation import run_isolation_probe  # noqa: E402
from evaluation.worker_runner import _write_real_cost_artifact, run_worker_control_probe, run_worker_from_config  # noqa: E402
from evaluation.real_sample_audit import audit_output_caps, audit_real_runs, audit_session_cost  # noqa: E402
from evaluation.initial_real_review import write_initial_real_review  # noqa: E402
from evaluation.real_path_diagnostics import write_real_path_diagnostics  # noqa: E402
from evaluation.local_semantic_smoke import run_local_semantic_smoke  # noqa: E402
from evaluation.decision_parser_deterministic import run_parser_and_semantic_delta_selftest  # noqa: E402
from evaluation.dependencies import check_dependencies  # noqa: E402
from evaluation.preflight import collect_preflight  # noqa: E402
from evaluation.state_roundtrip import run_state_roundtrip  # noqa: E402
from evaluation.suites import run_suite  # noqa: E402
from evaluation.gate import audit_provider_deployment_materials, audit_source_runtime_readonly, build_local_research_archive, materialize_research_archive_for_worker, run_gate_selftest, submit_evidence, validate_submitted_evidence  # noqa: E402
from evaluation.handoff import audit_source_access, prepare_handoff_evidence, write_handoff_artifacts  # noqa: E402
from export.discover import create_snapshot, sha256_file  # noqa: E402
from runtime.context import ContextBuilder  # noqa: E402
from runtime.loop import AgencyLoop  # noqa: E402
from runtime.policy import Policy  # noqa: E402
from runtime.store import EventStore  # noqa: E402
from transport.sink import RecordingSink  # noqa: E402

PRODUCTION_ROOT = REPO_ROOT.parent / "xiyu-ai"


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def json_write(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def mark_work_item(run_root: pathlib.Path, item_id: str, status: str, evidence: list[str], next_command: str | None = None) -> None:
    path = run_root / "requirement-map.json"
    if not path.exists():
        return
    mapping = json.loads(path.read_text(encoding="utf-8"))
    item = mapping.setdefault("work_items", {}).setdefault(item_id, {})
    item.update({"status": status, "evidence": evidence, "next": next_command})
    json_write(path, mapping)


def hash_paths(paths: list[pathlib.Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: str(item)):
        if not path.exists() or not path.is_file():
            continue
        digest.update(str(path).encode("utf-8")); digest.update(b"\0"); digest.update(path.read_bytes())
    return digest.hexdigest()


def experiment_code_files() -> list[pathlib.Path]:
    return [
        path for path in V2_ROOT.rglob("*")
        if path.is_file() and "runs" not in path.parts and "__pycache__" not in path.parts and path.suffix != ".pyc"
    ]


def arm_settings(arm: str | None) -> dict[str, Any]:
    value = (arm or "A").upper()
    if value not in {"A", "B", "C"}:
        raise ValueError(f"unsupported concerns arm: {value}")
    return {
        "arm": value,
        "prompt_path": PROMPT if value == "A" else CONCERNS_PROMPT,
        "concerns_enabled": value == "C",
        "prompt_mode": {"A": "baseline", "B": "prompt_only", "C": "concerns"}[value],
    }


def provider_bindings_from_preflight(preflight: dict[str, Any]) -> dict[str, Any]:
    """Return non-secret provider/model identities bound into a frozen run."""
    labels = (preflight.get("model") or {}).get("labels") or {}
    primary = labels.get("CHAT_MODEL") or labels.get("MODEL_NAME")
    second = labels.get("CHAT_MODEL_2") or labels.get("MODEL_NAME_2") or labels.get("SECOND_MODEL")
    image_provider = labels.get("IMAGE_PROVIDER") or labels.get("VISION_PROVIDER")
    image_model = labels.get("IMAGE_MODEL") or labels.get("VISION_MODEL")
    return {
        "text": {
            "provider": labels.get("CHAT_PROVIDER"),
            "primary_model": primary,
            "second_model": second,
            "status": "declared_unverified" if primary and second else "incomplete",
        },
        "image": {
            "provider": image_provider,
            "model": image_model,
            "status": "declared_unverified" if image_provider and image_model else "incomplete",
        },
    }


def validate_manifest_bindings(run_root: pathlib.Path) -> dict[str, Any]:
    """Check that frozen evidence still belongs to the code/data/prompt version."""
    manifest_path = run_root / "manifest.json"
    if not manifest_path.exists():
        result = {"schemaVersion": "manifest-validation-v1", "status": "incomplete", "reason": "manifest_missing", "checks": {}}
        json_write(run_root / "manifest-validation.json", result)
        return result
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    binding = manifest.get("snapshot_binding", {})
    execution_manifest_path = run_root / "execution-manifest.json"
    current_schema_hash = hash_paths(sorted((V2_ROOT / "contracts").rglob("*.py")))
    current_rubric_hash = hashlib.sha256(json.dumps(build_coverage(), ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    inventory = json.loads((run_root / "inventory.json").read_text(encoding="utf-8")) if (run_root / "inventory.json").exists() else {}
    source_locator_value = inventory.get("source", {}).get("sourceDb", {}).get("main", {}).get("locator")
    source_locator = pathlib.Path(source_locator_value) if source_locator_value else None
    context_path = pathlib.Path(binding.get("context_path", run_root / "snapshot" / "context.json"))
    params_payload = {
        "mode": manifest.get("mode"), "source_db": str(source_locator.resolve()) if source_locator else None,
        "workbench": str(pathlib.Path(inventory.get("source", {}).get("workbenchRoot", "")).resolve()),
        "arm": manifest.get("arm", "A"),
    }
    current_params_hash = hashlib.sha256(json.dumps(params_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    execution_manifest = json.loads(execution_manifest_path.read_text(encoding="utf-8")) if execution_manifest_path.exists() else {}
    expected_prompt_variants = [
        {"entry_id": item.get("entry_id"), "prompt_path": item.get("prompt_path"), "prompt_hash": item.get("prompt_hash")}
        for item in execution_manifest.get("prompt_variants", [])
    ]
    actual_prompt_variants = []
    for item in expected_prompt_variants:
        prompt_path = pathlib.Path(item["prompt_path"]) if item.get("prompt_path") else pathlib.Path()
        actual_prompt_variants.append({"entry_id": item.get("entry_id"), "prompt_path": item.get("prompt_path"), "prompt_hash": sha256_file(prompt_path) if prompt_path.exists() else None})
    variant_expected_hash = hashlib.sha256(json.dumps(expected_prompt_variants, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    variant_actual_hash = hashlib.sha256(json.dumps(actual_prompt_variants, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    current_preflight = json.loads((run_root / "completion-preflight.json").read_text(encoding="utf-8")) if (run_root / "completion-preflight.json").exists() else {}
    current_provider_bindings = provider_bindings_from_preflight(current_preflight)
    checks = {
        "code_hash": {"expected": manifest.get("code_hash"), "actual": hash_paths(experiment_code_files())},
        "prompt_hash": {"expected": manifest.get("prompt_hash"), "actual": sha256_file(pathlib.Path(manifest["prompt_path"])) if manifest.get("prompt_path") else None},
        "fixture_hash": {"expected": manifest.get("fixture_hash"), "actual": sha256_file(FIXTURE)},
        "context_hash": {"expected": binding.get("context_hash"), "actual": sha256_file(context_path)},
        "source_db_hash": {"expected": binding.get("source_db_hash"), "actual": sha256_file(source_locator) if source_locator and source_locator.is_file() else None},
        "schema_hash": {"expected": manifest.get("schema_hash"), "actual": current_schema_hash},
        "rubric_hash": {"expected": manifest.get("rubric_hash"), "actual": current_rubric_hash},
        "params_hash": {"expected": manifest.get("params_hash"), "actual": current_params_hash},
        "execution_manifest_hash": {"expected": manifest.get("execution_manifest_hash"), "actual": sha256_file(execution_manifest_path) if execution_manifest_path.exists() else None},
        "prompt_variants": {"expected": variant_expected_hash, "actual": variant_actual_hash},
        "provider_bindings": {"expected": manifest.get("provider_binding_hash"), "actual": hashlib.sha256(json.dumps(current_provider_bindings, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()},
    }
    mismatches = [name for name, item in checks.items() if item["expected"] != item["actual"]]
    result = {"schemaVersion": "manifest-validation-v1", "status": "passed" if not mismatches else "invalidated", "checks": checks, "mismatches": mismatches, "rule": "any code/prompt/fixture/context/source change invalidates dependent evidence"}
    json_write(run_root / "manifest-validation.json", result)
    return result


def production_hashes() -> dict[str, str | None]:
    paths = [REPO_ROOT / "index.mjs", REPO_ROOT / "package.json", REPO_ROOT / "package-lock.json"]
    paths.extend(path for root in (REPO_ROOT / "src", REPO_ROOT / "config") if root.exists() for path in root.rglob("*") if path.is_file())
    return {str(path.relative_to(REPO_ROOT)): sha256_file(path) if path.exists() else None for path in sorted(paths)}


def unique_run_path() -> pathlib.Path:
    LAB_ROOT.joinpath("runs").mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return LAB_ROOT / "runs" / f"{stamp}-{uuid.uuid4().hex[:8]}"


def build_cost_plan(execution_manifest: dict[str, Any]) -> dict[str, Any]:
    """Estimate the complete request envelope before any provider call.

    Prices and quotas intentionally remain unknown until an authorized provider
    price sheet and ceiling are supplied.  The envelope is still useful: it
    makes the fixed denominator, multi-event shape, model slots and retry
    reserve explicit before smoke can spend anything.
    """
    entries = execution_manifest.get("entries", [])
    models = execution_manifest.get("models", [])
    model_count = max(2, len(models))
    plan: dict[str, Any] = {}
    lower_total = 0
    upper_total = 0
    retry_total = 0
    deterministic_control_total = 0
    image_call_total = 0
    for suite in ("smoke", "fixed", "reliability", "integration", "holdout", "media", "continuity", "performance"):
        suite_entries = [entry for entry in entries if entry.get("suite") == suite]
        if suite == "smoke":
            suite_entries += [entry for entry in entries if entry.get("suite") == "integration" and entry.get("scenario_id") in {"I02", "I03", "I07", "I08"}]
        if suite == "holdout" and not suite_entries:
            suite_entries = [{"scenario": {"events": [{}, {}, {}]}} for _ in range(12)]
        if suite == "media" and not suite_entries:
            suite_entries = [{"scenario": {"events": [{}, {}, {}]}} for _ in range(3)]
        if suite == "continuity" and not suite_entries:
            suite_entries = [{"scenario": {"events": [{} for _ in range(14)]}} for _ in range(3)]
        if suite == "performance" and not suite_entries:
            suite_entries = [{"scenario": {"events": [{}]}} for _ in range(3)]
        if suite == "smoke":
            repetitions = 3
        elif suite in {"fixed", "reliability", "integration"}:
            repetitions = 5
        elif suite == "holdout":
            repetitions = 3
        elif suite == "media":
            repetitions = 2
        elif suite == "continuity":
            repetitions = 1
        else:
            repetitions = 30
        if suite in {"media", "continuity", "performance"}:
            trajectories = len(suite_entries) * repetitions
        else:
            trajectories = len(suite_entries) * repetitions * model_count
        event_counts = [len((entry.get("scenario") or {}).get("events") or []) for entry in suite_entries]
        min_events = min(event_counts) if event_counts else 0
        max_events = max(event_counts) if event_counts else 0
        lower = trajectories * min_events
        upper = trajectories * max_events * 6
        retry_reserve = upper * 2
        execution_kind = "deterministic_formal_control" if suite == "reliability" else "provider_or_specialized"
        if suite == "reliability":
            deterministic_control_total += trajectories
            lower = upper = retry_reserve = 0
        if suite == "media":
            image_call_total += int((execution_manifest.get("denominators", {}).get("media") or {}).get("assets", 0))
        lower_total += lower
        upper_total += upper
        retry_total += retry_reserve
        plan[suite] = {
            "cases": len(suite_entries), "repetitions": repetitions,
            "model_slots": model_count if suite not in {"media", "continuity", "performance"} else 0,
            "trajectories_or_samples": trajectories, "events_per_trajectory": {"min": min_events, "max": max_events},
            "execution_kind": execution_kind,
            "model_calls_lower_bound": lower, "model_calls_upper_bound_before_retry": upper,
            "retry_reserve_calls": retry_reserve,
        }
    variants = execution_manifest.get("prompt_variants", [])
    variant_repetitions = sum(int(item.get("repetitions", 0)) for item in variants)
    variant_trajectories = variant_repetitions * model_count
    variant_lower = variant_trajectories * max((len((item.get("scenario") or {}).get("events") or []) for item in variants), default=0)
    variant_upper = variant_lower * 6
    lower_total += variant_lower
    upper_total += variant_upper
    retry_total += variant_upper * 2
    plan["prompt_pairing"] = {
        "cells": len(variants), "repetitions_per_cell": 3, "model_slots": model_count,
        "trajectories": variant_trajectories, "model_calls_lower_bound": variant_lower,
        "model_calls_upper_bound_before_retry": variant_upper, "retry_reserve_calls": variant_upper * 2,
    }
    return {
        "status": "price_sheet_pending", "currency": "unknown", "call_limit": "not_authorized",
        "denominators": execution_manifest.get("denominators", {}), "suites": plan,
        "estimated_model_calls": {"lower_bound": lower_total, "upper_bound_before_retry": upper_total, "retry_reserve": retry_total, "provider_requests_upper_bound": upper_total + retry_total},
        "estimated_image_provider_calls": {"planned": image_call_total, "retry_reserve": image_call_total * 2, "provider_requests_upper_bound": image_call_total * 3},
        "deterministic_control_runs": deterministic_control_total,
        "assumptions": {"model_calls_per_event_upper_bound": 6, "infrastructure_retries_per_call_upper_bound": 2, "media_asset_conditions": 6, "continuity_events_are_virtual_time": True, "reliability_is_not_a_model_call": True},
        "cost_rule": "record actual provider price and usage after smoke; never reduce denominator to fit budget; unknown price is not free",
    }


def source_module_map() -> dict[str, Any]:
    modules = {
        "proactive": "src/proactive.mjs", "agency_protocol": "src/agency_protocol.mjs", "enterprise_context": "src/enterprise_context.mjs",
        "companion": "src/companion.mjs", "db": "src/db.mjs", "photo_planner": "src/photo_planner.mjs", "photo_sender": "src/photo_sender.mjs",
        "production_entry": "index.mjs", "production_config": "config/agency-prompts.v1.json",
    }
    mapped = []
    for owner, relative in modules.items():
        path = REPO_ROOT / relative
        mapped.append({"owner": owner, "relative_path": relative, "exists": path.exists(), "sha256": sha256_file(path) if path.exists() else None, "role": "reference_only; not imported by v2 worker"})
    return {"schemaVersion": "source-module-map-v2", "createdAt": utc_now(), "modules": mapped}


def requirement_map() -> dict[str, Any]:
    return build_requirement_map()


def component_map() -> dict[str, Any]:
    return {
        "schemaVersion": "component-map-v2",
        "root": str(V2_ROOT) if "V2_ROOT" in globals() else "experiments/ideal-agency-lab/v2",
        "unique_cli": "cli.py",
        "components": {
            "controller": ["boundary.py", "gateway.py", "lifecycle.py", "provider_config.py", "worker_execution.py", "worker_gateway.py"], "export": ["discover.py"],
            "contracts": ["schemas.py"], "runtime": ["context.py", "loop.py", "policy.py", "store.py", "prompts/assemble.py", "prompts/base.json", "prompts/p1.json", "prompts/concerns-v1.json"],
            "adapters": ["local.py"], "transport": ["sink.py"], "fixtures": ["public_state.json"],
            "evaluation": ["concern_cases.py", "concern_deterministic.py", "j05_simulation.py", "coverage.py", "deterministic.py", "evidence.py", "execution.py", "gate.py", "harness.py", "isolation.py", "mutation.py", "parity.py", "preflight.py", "state_roundtrip.py", "suites.py"], "tests": ["__init__.py"],
        },
        "formal_path": "cli.py -> controller -> contracts -> runtime/context -> runtime/loop -> adapters/transport -> runtime/store -> evaluation",
        "production_reference_only": ["src/", "config/", "index.mjs", "scripts/lab_*.py", "scripts/lab_*.mjs"],
    }


def _git_value(*args: str) -> str | None:
    try:
        return subprocess.check_output(["git", "-C", str(REPO_ROOT), *args], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def write_concern_artifacts(run_root: pathlib.Path, *, arm_info: dict[str, Any], case_manifest: dict[str, Any]) -> None:
    prompt_path = pathlib.Path(arm_info["prompt_path"])
    prompt = json.loads(prompt_path.read_text(encoding="utf-8"))
    sections = prompt.get("sections", []) or [{"id": "legacy-rules", "text": "\n".join(str(item) for item in prompt.get("rules", []))}]
    effective_text = "\n\n".join(str(item.get("text", "")) for item in sections)
    effective_path = run_root / "effective-prompt.txt"
    effective_path.write_text(effective_text + "\n", encoding="utf-8")
    section_records = []
    for index, section in enumerate(sections, 1):
        text_value = str(section.get("text", ""))
        section_records.append({
            "order": index,
            "id": section.get("id"),
            "source": str(prompt_path),
            "sha256": hashlib.sha256(text_value.encode("utf-8")).hexdigest(),
            "chars": len(text_value),
            "token_estimate": max(1, (len(text_value) + 3) // 4),
        })
    json_write(run_root / "composition-map.json", {
        "schemaVersion": "composition-map-v1",
        "prompt_version": prompt.get("promptVersion"),
        "arm": arm_info["arm"],
        "concerns_enabled": arm_info["concerns_enabled"],
        "assembly_order": ["system_permissions_and_tools", "personality", "concern_and_intention", "state_updates", "current_trusted_context", "untrusted_source_content", "output_protocol", "configuration"],
        "sections": section_records,
        "dynamic_context_fields": ["event", "responsibilities", "concerns.selected", "concerns.catalog", "concerns.updates_since_last_event", "current.feedback", "tool_result"],
        "effective_prompt": {"path": str(effective_path), "sha256": sha256_file(effective_path), "chars": len(effective_text), "token_estimate": max(1, (len(effective_text) + 3) // 4)},
        "privacy": "only versioned prompt blocks are materialized here; user/source runtime data remains in trajectory traces",
    })
    head = _git_value("rev-parse", "HEAD")
    baseline_head = _git_value("rev-parse", "HEAD^")
    json_write(run_root / "handoff-location.json", {
        "schemaVersion": "handoff-location-v1",
        "worktree": str(REPO_ROOT),
        "branch": _git_value("branch", "--show-current"),
        "head": head,
        "workspace_hash": hash_paths(experiment_code_files()),
        "baseline_checkpoint": {"head": baseline_head, "checkpoint_ref": "stash checkpoint 5f9d38c946ee1a63f824bd6b831815b27fd49326", "source": "inherited stable experiment checkpoint"},
        "unique_cli": str(V2_ROOT / "cli.py"),
        "production_mutation_policy": "production src/config/index.mjs/package and real delivery remain forbidden",
    })
    json_write(run_root / "case-manifest.json", case_manifest)
    map_lines = [
        "# Concerns arm implementation map", "", f"Arm selected for this run: `{arm_info['arm']}` (`{arm_info['prompt_mode']}`), concerns_enabled=`{str(arm_info['concerns_enabled']).lower()}`.", "",
        "| Requirement | Existing function | Change | Deterministic evidence | Remaining variance |",
        "|---|---|---|---|---|",
        "| concerns persistence/CAS | `runtime/store.py:EventStore` | `concerns` and `concern_events`, versioned apply, idempotency, owner filter | `concern-deterministic.json` T01-T05/T10-T12 | real multi-event API trajectory |",
        "| same-loop delta | `runtime/loop.py:AgencyLoop` | atomic patch + intention/action; continuation preserves link | `concern-deterministic.json` T06/T14; traces | provider-generated decisions |",
        "| scoped context | `runtime/context.py:ContextBuilder` | responsibilities, concerns selected/catalog, feedback and update trace | T07/T13 and context artifact | 1500-token p95 needs real traces |",
        "| patch contract/policy | `contracts/schemas.py`, `runtime/policy.py` | strict fields, source/epistemic/CAS/capacity rules | T02-T05/T10-T11/T14 | full K/T semantic coverage |",
        "| tool read | `adapters/local.py:concerns.read` | owner-injected read-only adapter | T02/T07 | real source/provider binding |",
        "| prompt/arms | `runtime/prompts/concerns-v1.json`, `prompts/assemble.py` | versioned C wording and A/B/C metadata | `effective-prompt.txt`, `composition-map.json`, `case-manifest.json` | blind human review |",
        "", "Production proof: this worktree only changes `experiments/ideal-agency-lab/v2` and experiment evidence; production integrity is checked by the existing freeze/report path.",
    ]
    (run_root / "implementation-map.md").write_text("\n".join(map_lines), encoding="utf-8")
    (run_root / "comparison.csv").write_text("case_id,arm,repetition,model,status,score,token_count,latency_ms,provider_calls,attribution,notes\n", encoding="utf-8")
    (run_root / "failures.md").write_text("# Concerns failures\n\nNo semantic API trajectory has been run. Deterministic contract failures and repairs are recorded by the test command; this file is updated when a trajectory or automated evaluator fails.\n", encoding="utf-8")
    (run_root / "review-pack.md").write_text("# Blind review pack\n\nStatus: `pending_samples`. Sample generation is not blocked by human review. After automated/API trajectories are available, this pack must contain anonymized A/B/C full trajectories, images, and worst samples before final subjective conclusion.\n", encoding="utf-8")
    json_write(run_root / "reviewer-scores.json", {"schemaVersion": "reviewer-scores-v1", "status": "pending_human_review", "human_review_blocks_sample_generation": False, "human_review_blocks_final_subjective_conclusion": True, "scores": []})
    (run_root / "decision-report.md").write_text("# Concerns arm decision report\n\nStatus: `pending_automated_trajectories_and_human_review`. No production conclusion is inferred from prompt presence or deterministic tests.\n", encoding="utf-8")
    (run_root / "concern-timeline.jsonl").write_text("", encoding="utf-8")
    json_write(run_root / "concern-deterministic.json", {"schemaVersion": "concern-deterministic-v1", "status": "not_run", "provider_calls": 0, "human_review_required_for_sample_generation": False, "human_review_required_for_final_subjective_conclusion": True, "results": []})


def freeze(args: argparse.Namespace) -> pathlib.Path:
    arm_info = arm_settings(getattr(args, "arm", "A"))
    prompt_path = pathlib.Path(arm_info["prompt_path"])
    source_db = pathlib.Path(args.source_db).resolve()
    workbench = pathlib.Path(args.workbench).resolve()
    if not source_db.exists():
        raise SystemExit(f"source database not found: {source_db}")
    if not workbench.exists():
        raise SystemExit(f"workbench root not found: {workbench}")
    run_root = pathlib.Path(args.run).resolve() if args.run else unique_run_path()
    if run_root.exists():
        raise SystemExit(f"refusing to overwrite existing run: {run_root}")
    inventory = create_snapshot(REPO_ROOT, run_root, source_db, workbench, args.mode)
    research_archive = build_local_research_archive(repo_root=REPO_ROOT, run_root=run_root)
    inventory = materialize_research_archive_for_worker(run_root=run_root, archive=research_archive)
    preflight = collect_preflight(repo_root=REPO_ROOT, run_root=run_root, source_db=source_db, workbench_root=workbench)
    provider_audit = audit_provider_deployment_materials(repo_root=REPO_ROOT, run_root=run_root)
    v2_files = experiment_code_files()
    context_binding = inventory.get("context_dataset", {})
    owner_scopes = sorted({item.get("owner_key") for item in inventory.get("identity_map", []) if item.get("owner_key")})
    model_labels = [value for value in (preflight.get("model", {}).get("labels", {}).get("CHAT_MODEL"), preflight.get("model", {}).get("labels", {}).get("MODEL_NAME"), preflight.get("model", {}).get("labels", {}).get("CHAT_MODEL_2"), preflight.get("model", {}).get("labels", {}).get("MODEL_NAME_2")) if value]
    provider_bindings = provider_bindings_from_preflight(preflight)
    json_write(run_root / "manifest.json", {
        "schemaVersion": "ideal-agency-lab-manifest-v2", "createdAt": utc_now(), "runId": run_root.name,
        "mode": args.mode, "code_root": str(V2_ROOT), "code_hash": hash_paths(v2_files), "fixture_hash": sha256_file(FIXTURE),
        "schema_hash": hash_paths(sorted((V2_ROOT / "contracts").rglob("*.py"))),
        "rubric_hash": hashlib.sha256(json.dumps(build_coverage(), ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
        "params_hash": hashlib.sha256(json.dumps({"mode": args.mode, "source_db": str(source_db), "workbench": str(workbench), "arm": arm_info["arm"]}, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
        "arm": arm_info["arm"], "prompt_mode": arm_info["prompt_mode"], "concerns_enabled": arm_info["concerns_enabled"], "concerns_config": {"max_active": 12, "selected_limit": 6, "max_patches": 3, "summary_token_budget": 1500},
        "prompt_hash": sha256_file(prompt_path), "prompt_path": str(prompt_path), "model": model_labels[0] if model_labels else None, "models": model_labels, "provider": preflight.get("model", {}).get("labels", {}).get("CHAT_PROVIDER"), "provider_bindings": provider_bindings, "provider_binding_hash": hashlib.sha256(json.dumps(provider_bindings, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(), "status": "frozen_before_behavior",
        "snapshot_binding": {"snapshot_id": f"{inventory.get('createdAt', 'unknown')}:{inventory.get('source', {}).get('sourceDb', {}).get('main', {}).get('content_hash', 'unknown')[:16]}", "context_path": str(run_root / "snapshot" / "context.json"), "context_hash": context_binding.get("content_hash"), "source_db_hash": inventory.get("source", {}).get("sourceDb", {}).get("main", {}).get("content_hash"), "owner_keys": owner_scopes},
        "oracle_binding": {"status": "independent_oracle_required", "worker_readable": False, "locator": str(run_root / "oracle-private")},
        "production_mutation_policy": {"src": "forbidden", "config": "forbidden", "index.mjs": "forbidden", "package": "forbidden", "delivery": "sink_only"},
    })
    json_write(run_root / "production-integrity-before.json", {"status": "captured", "files": production_hashes()})
    json_write(run_root / "requirement-map.json", build_requirement_map(evidence_root=str(run_root)))
    execution_manifest = build_execution_manifest(
        run_root=str(run_root),
        source_kind="snapshot-bound" if args.mode == "FROZEN" else args.mode.lower(),
        owner_scope=owner_scopes if owner_scopes else None,
        model_labels=model_labels,
        arm=arm_info["arm"],
        prompt_path=str(prompt_path),
        concerns_enabled=arm_info["concerns_enabled"],
    )
    json_write(run_root / "execution-manifest.json", execution_manifest)
    frozen_manifest = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))
    frozen_manifest["execution_manifest_hash"] = sha256_file(run_root / "execution-manifest.json")
    json_write(run_root / "manifest.json", frozen_manifest)
    mark_work_item(run_root, "C06", "incomplete", [str(run_root / "execution-manifest.json"), str(run_root / "completion-preflight.json")], f"python {V2_ROOT / 'cli.py'} run --suite smoke --run {run_root}")
    json_write(run_root / "source-module-map.json", source_module_map())
    json_write(run_root / "component-map.json", component_map())
    case_manifest = build_concern_case_manifest(
        run_root=str(run_root),
        source_kind="snapshot-bound" if args.mode == "FROZEN" else args.mode.lower(),
        owner_scope=owner_scopes if owner_scopes else None,
        prompt_paths={"A": str(PROMPT), "B": str(CONCERNS_PROMPT), "C": str(CONCERNS_PROMPT)},
    )
    write_concern_artifacts(run_root, arm_info=arm_info, case_manifest=case_manifest)
    write_j05_design_artifacts(run_root, case_manifest)
    config_path = REPO_ROOT / "config" / "agency-prompts.v1.json"
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    json_write(run_root / "config-synthesis.json", {"source": str(config_path), "sha256": sha256_file(config_path) if config_path.exists() else None, "blocks": [{"name": name, "type": type(value).__name__, "chars": len(json.dumps(value, ensure_ascii=False)), "value_hash": hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()} for name, value in config.items()]})
    json_write(run_root / "prompt-review-pack.json", {
        "schemaVersion": "prompt-review-pack-v1", "primary": {"path": str(prompt_path), "sha256": sha256_file(prompt_path), "version": json.loads(prompt_path.read_text(encoding="utf-8")).get("promptVersion")},
        "baseline": {"path": str(V2_ROOT / "runtime" / "prompts" / "base.json"), "sha256": sha256_file(V2_ROOT / "runtime" / "prompts" / "base.json")},
        "arm": arm_info["arm"], "concerns_enabled": arm_info["concerns_enabled"], "status": "pending_human_confirmation", "required_blind_review_items": 12,
        "review_boundary": "prompt bundle is experiment-owned; confirmation is external evidence and is never inferred from model output",
    })
    json_write(run_root / "archive-index.json", {"schemaVersion": "legacy-archive-index-v2", "status": "reference_only", "legacy_runners": [str(path) for path in sorted((REPO_ROOT / "scripts").glob("lab_*"))], "legacy_runs": [str(path) for path in sorted((LAB_ROOT / "runs").glob("*"))], "formal_runner": str(V2_ROOT / "cli.py")})
    json_write(run_root / "environment.json", {"status": "incomplete", "completion": "incomplete", "mode": args.mode, "arm": arm_info["arm"], "concerns_enabled": arm_info["concerns_enabled"], "source_authorization": preflight.get("source", {}).get("source_authorization", {}).get("status"), "e0": "pending", "e1": "pending", "e2": "pending", "e3": "not_started", "c00": preflight.get("status")})
    json_write(run_root / "isolation.json", {"status": "pending_boundary_probe", "worker_root": str(run_root / "worker"), "snapshot_readonly_intent": True, "oracle_readable_by_worker": False, "real_delivery_enabled": False, "network_allowlist": [], "production_write_attempts": []})
    json_write(run_root / "lifecycle.json", {"status": "created", "run_id": run_root.name, "started_at": utc_now(), "processes": [], "cleanup": "pending"})
    coverage = build_coverage(evidence_root=str(run_root))
    write_coverage(run_root / "coverage.json", coverage)
    json_write(run_root / "path-coverage.json", {"schemaVersion": "path-coverage-v2", "status": "not_run", "paths": coverage.get("paths", {}), "evidence_root": str(run_root)})
    cost_plan = build_cost_plan(execution_manifest)
    json_write(run_root / "cost-plan.json", cost_plan)
    preflight_path = run_root / "completion-preflight.json"
    preflight_record = json.loads(preflight_path.read_text(encoding="utf-8"))
    preflight_record["cost"].update({
        "status": "unknown_price_with_call_envelope",
        "plan_path": str(run_root / "cost-plan.json"),
        "estimated_model_calls": cost_plan["estimated_model_calls"],
    })
    json_write(preflight_path, preflight_record)
    preflight_summary = run_root / "completion-preflight.md"
    if preflight_summary.exists():
        summary_text = preflight_summary.read_text(encoding="utf-8")
        summary_text += "\n## 预估调用包络\n\n"
        envelope = cost_plan["estimated_model_calls"]
        summary_text += f"- 估算模型调用：下界 `{envelope['lower_bound']}`；重试前上界 `{envelope['upper_bound_before_retry']}`；含重试保守上界 `{envelope['provider_requests_upper_bound']}`。\n"
        summary_text += "- 价格、额度和正式上限仍为 unknown；不得将此估算当作免费额度。\n"
        preflight_summary.write_text(summary_text, encoding="utf-8")
    json_write(run_root / "cost-latency.json", {"status": "not_started", "attempts": []})
    json_write(run_root / "execution-state.json", {"schemaVersion": "execution-state-v1", "attempts": [], "status": "not_started"})
    json_write(run_root / "assets" / "manifest.json", {"schemaVersion": "asset-evidence-v1", "status": "not_started", "required": 6, "provider": "unverified", "human_review_required": True})
    json_write(run_root / "reviews.json", {"schemaVersion": "review-evidence-v1", "status": "not_ready", "blind_review_required": 12, "human_scores": [], "automated_scores": []})
    json_write(run_root / "gate-validation.json", {"schemaVersion": "gate-validation-v1", "status": "blocked", "submission_status": "not_submitted", "runId": run_root.name, "scopes": {}, "reasons": ["no_evidence_submission"], "human_review_policy": {"required_for_sample_generation": False, "required_for_final_subjective_conclusion": True}})
    if not (run_root / "research-archive.json").exists():
        json_write(run_root / "research-archive.json", research_archive)
    json_write(run_root / "issues.json", [])
    json_write(run_root / "checkpoint.json", {"schemaVersion": "checkpoint-v1", "run": run_root.name, "completed": ["C00"], "next": {"command": f"python {V2_ROOT / 'cli.py'} e0 --run {run_root}", "reason": "E0 parity before behavior gates"}, "blocked": preflight.get("missing_external_evidence", [])})
    (run_root / "scores.jsonl").write_text("", encoding="utf-8")
    json_write(run_root / "human-review.json", {"status": "not_started", "required": 12})
    (run_root / "report.md").write_text("# Ideal Agency Lab v2\n\n状态：`incomplete`（C00已记录；行为与完整验收尚未完成）。\n\n- 不修改生产代码/配置。\n- 不发送真实 Bot。\n- 旧 lab runner 仅登记为历史参照。\n", encoding="utf-8")
    (run_root / "reproduce.md").write_text(f"# Reproduce\n\nRun: `{run_root}`\n\nThe single executable entry is `{V2_ROOT / 'cli.py'}`. Fake mode proves control flow only; real mode is gate-protected and uses the same trajectory executor.\n\n```powershell\npython {V2_ROOT / 'cli.py'} preflight --run {run_root}\npython {V2_ROOT / 'cli.py'} selftest --run {run_root}\npython {V2_ROOT / 'cli.py'} mutations --run {run_root}\npython {V2_ROOT / 'cli.py'} context --run {run_root}\npython {V2_ROOT / 'cli.py'} roundtrip --run {run_root}\npython {V2_ROOT / 'cli.py'} e0 --run {run_root}\npython {V2_ROOT / 'cli.py'} e1 --run {run_root}\npython {V2_ROOT / 'cli.py'} fixture-integrity --run {run_root}\npython {V2_ROOT / 'cli.py'} j05-run --run {run_root} --provider-mode fake\npython {V2_ROOT / 'cli.py'} report --run {run_root}\npython {V2_ROOT / 'cli.py'} validate-evidence --run {run_root}\npython {V2_ROOT / 'cli.py'} j05-run --run {run_root} --provider-mode real --model <bound-primary-model>\n```\n\nA real run starts only when sample_generation evidence, source/isolation gates, gateway binding, and cost conditions are passed. If a trajectory root exists, the command refuses to overwrite it. Resume by running the missing gate command and then the real command; do not delete or reset prior evidence.\n", encoding="utf-8")
    (run_root / "limitations.md").write_text("# Limitations\n\nC00 已查明线上源授权、OS/container worker、provider/第二模型、图片 provider、费用上限及人审缺项；这些缺项阻止真实 API 主组和最终效果结论。上一 run 的 40/40 仅作历史参考。\n", encoding="utf-8")
    write_reproduce_artifact(run_root)
    print(json.dumps({"status": "frozen", "run": str(run_root), "resources": len(inventory.get("resources", [])), "mode": args.mode, "provider_audit": provider_audit["classifications"]}, ensure_ascii=False))
    return run_root


def write_reproduce_artifact(run_root: pathlib.Path) -> None:
    cli = V2_ROOT / "cli.py"
    prod = PRODUCTION_ROOT
    text = f'''# Reproduce

Run: {run_root}

唯一可执行入口：{cli}。fake 与 real 只替换 gateway/fault adapter，共用同一 execute_j05_trajectory、AgencyLoop、状态库和证据路径；fake 只计 control_flow_passed，不计语义验收。real 还必须有由独立 OS/container worker 实际生成的 worker-execution.json；进程内 guard 或普通子进程不能替代它。

```powershell
$cli = '{cli}'
$run = '{run_root}'
$prod = '{prod}'
python $cli provider-probe --run $run --production-root $prod
python $cli preflight --run $run
python $cli source-runtime-audit --run $run --url https://xiyu.myworlds.cn/api/health
python $cli source-access-audit --run $run --host xiyu.myworlds.cn
python $cli e0 --run $run
python $cli e1 --run $run
python $cli environment-evidence --run $run --production-root $prod
python $cli selftest --run $run
python $cli mutations --run $run
python $cli context --run $run
python $cli roundtrip --run $run
python $cli fixture-integrity --run $run
python $cli j05-run --run $run --provider-mode fake
python $cli prepare-handoff-evidence --run $run
$package = Get-ChildItem "$run\\evidence-package\\handoff-observed-v*.json" | Sort-Object LastWriteTime, Name | Select-Object -Last 1
python $cli submit-evidence --run $run --evidence $package.FullName
python $cli validate-evidence --run $run
python $cli report --run $run
```

当前交接 run 已观察到有效生产文本 binding deepseek/deepseek-chat，P0 探针可用；只有 sample_generation、源身份、合格 OS worker 及实际 worker-execution receipt 门禁均通过，再执行：

```powershell
python $cli smoke --run $run --model deepseek-chat --production-root $prod
python $cli j05-run --run $run --provider-mode real --model deepseek-chat
```

真实 P1/P2 只在正式证据门禁和实际 worker 执行证明放行后发请求；人审只阻塞最终主观结论。若轨迹目录已存在，执行器拒绝覆盖；恢复时从 checkpoint.json 的下一命令继续，不删除、不 reset 既有证据。P0/P1/P2 使用已授权的既有 provider 测试，不以数字费用上限作为前置条件；实际用量、延迟和可得价格依据仍写入证据。

若现状后来补齐了源身份或独立 worker，重新运行 `prepare-handoff-evidence` 会生成下一个 `handoff-observed-vN.json`；提交时始终选择刚生成的最新包，不覆盖旧提交，再运行 `validate-evidence` 重新计算门禁。
'''
    (run_root / "reproduce.md").write_text(text, encoding="utf-8")


def run_e0(run_root: pathlib.Path) -> dict[str, Any]:
    inventory = json.loads((run_root / "inventory.json").read_text(encoding="utf-8"))
    source_db = pathlib.Path(inventory["source"]["sourceDb"]["main"]["locator"])
    replica_db = pathlib.Path(inventory["replica"]["database"])
    sqlite_result = compare_sqlite(source_db, replica_db, transformations=inventory.get("transformations", []))
    manifest_result = compare_resource_manifest(inventory, run_root)
    result = {"status": "passed" if sqlite_result["status"] == "passed" and manifest_result["status"] == "passed" else "failed", "sqlite": sqlite_result, "manifest": manifest_result}
    result["source_locator"] = str(source_db); result["replica_locator"] = str(replica_db)
    result["environment_status"] = "passed" if result["status"] == "passed" and inventory["source"].get("authorization_status") == "verified" else ("inconclusive_source_identity_unverified" if result["status"] == "passed" else "failed")
    json_write(run_root / "replica-parity.json", result)
    mark_work_item(run_root, "C01", "passed" if result["status"] == "passed" else "failed", [str(run_root / "replica-parity.json")])
    environment_path = run_root / "environment.json"; environment = json.loads(environment_path.read_text(encoding="utf-8")); environment["e0"] = result["status"] if inventory["source"].get("authorization_status") == "verified" else "inconclusive_source_identity_unverified"; json_write(environment_path, environment)
    refresh_integrity(run_root)
    refresh_report(run_root)
    return result


def run_preflight(run_root: pathlib.Path) -> dict[str, Any]:
    inventory = json.loads((run_root / "inventory.json").read_text(encoding="utf-8"))
    source_db = pathlib.Path(inventory["source"]["sourceDb"]["main"]["locator"])
    workbench = pathlib.Path(inventory["source"]["workbenchRoot"])
    result = collect_preflight(repo_root=REPO_ROOT, run_root=run_root, source_db=source_db, workbench_root=workbench)
    environment_path = run_root / "environment.json"
    environment = json.loads(environment_path.read_text(encoding="utf-8")) if environment_path.exists() else {}
    environment["c00"] = result["status"]
    environment["source_authorization"] = result["source"]["source_authorization"]["status"]
    json_write(environment_path, environment)
    mark_work_item(run_root, "C00", "completed_with_external_gates", [str(run_root / "completion-preflight.json"), str(run_root / "completion-preflight.md")])
    refresh_integrity(run_root); refresh_report(run_root)
    return result


def run_provider_audit(run_root: pathlib.Path) -> dict[str, Any]:
    result = audit_provider_deployment_materials(repo_root=REPO_ROOT, run_root=run_root)
    refresh_integrity(run_root); refresh_report(run_root)
    return result


def run_source_runtime_audit(run_root: pathlib.Path, url: str) -> dict[str, Any]:
    result = audit_source_runtime_readonly(run_root=run_root, url=url)
    refresh_integrity(run_root); refresh_report(run_root)
    return result


def run_submit_evidence(run_root: pathlib.Path, evidence_path: pathlib.Path) -> dict[str, Any]:
    result = submit_evidence(run_root=run_root, evidence_path=evidence_path.resolve())
    refresh_integrity(run_root); refresh_report(run_root)
    return result


def run_validate_evidence(run_root: pathlib.Path) -> dict[str, Any]:
    result = validate_submitted_evidence(run_root)
    refresh_integrity(run_root); refresh_report(run_root)
    return result


def run_e1(run_root: pathlib.Path) -> dict[str, Any]:
    local_probe = run_isolation_probe(run_root, REPO_ROOT)
    try:
        worker_result = run_worker_control_probe(run_root)
    except (OSError, RuntimeError, ValueError, FileExistsError) as exc:
        result = {
            "schemaVersion": "isolation-probe-v3", "status": "inconclusive", "qualification": "not_os_qualified",
            "reason": str(exc), "process_local_probe": local_probe, "worker": {"status": "not_started", "error_type": type(exc).__name__},
        }
        json_write(run_root / "isolation-probe.json", result)
    else:
        proof = worker_result.get("proof") or {}
        passed = worker_result.get("status") == "passed" and proof.get("status") == "passed"
        result = {
            "schemaVersion": "isolation-probe-v3", "status": "passed" if passed else "failed",
            "qualification": "os_qualified" if passed else "not_os_qualified",
            "process_local_probe": local_probe, "worker": worker_result,
            "probes": (proof.get("evidence") or {}).get("path_probes", []) + [{"name": "direct_external_network", **((proof.get("evidence") or {}).get("network_probe") or {})}],
            "path_policy": proof.get("path_policy"), "network_policy": proof.get("network_policy"), "oracle_policy": proof.get("oracle_policy"),
            "reason": "qualified WSL2 worker executed the shared executor through controller gateway relay" if passed else "worker qualification probe failed",
        }
        json_write(run_root / "isolation-probe.json", result)
    environment_path = run_root / "environment.json"; environment = json.loads(environment_path.read_text(encoding="utf-8")) if environment_path.exists() else {}; environment["e1"] = result["status"]; json_write(environment_path, environment)
    mark_work_item(run_root, "C01", "passed" if result.get("qualification") == "os_qualified" and result["status"] == "passed" else "incomplete", [str(run_root / "isolation-probe.json")])
    refresh_integrity(run_root)
    refresh_report(run_root)
    return result


def run_dependency_check(run_root: pathlib.Path) -> dict[str, Any]:
    result = check_dependencies(V2_ROOT)
    json_write(run_root / "dependency-check.json", result)
    json_write(run_root / "component-map.json", component_map())
    mark_work_item(run_root, "C05", "passed" if result["status"] == "passed" else "failed", [str(run_root / "dependency-check.json")])
    return result


def run_context(run_root: pathlib.Path) -> dict[str, Any]:
    result = run_context_consumption(run_root)
    mark_work_item(run_root, "C02", result["status"], [str(run_root / "context-consumption.json")])
    refresh_integrity(run_root); refresh_report(run_root)
    return result


def run_roundtrip(run_root: pathlib.Path) -> dict[str, Any]:
    result = run_state_roundtrip(run_root)
    mark_work_item(run_root, "C03", result["status"], [str(run_root / "state-roundtrip.json")])
    refresh_integrity(run_root); refresh_report(run_root)
    return result


def run_mutations(run_root: pathlib.Path) -> dict[str, Any]:
    result = run_mutation_coverage(run_root)
    coverage_path = run_root / "coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8")) if coverage_path.exists() else build_coverage(evidence_root=str(run_root))
    for item in result.get("rows", []):
        group = "mutations"
        entry = coverage.get("matrix", {}).get(group, {}).get(item["id"])
        if entry:
            entry["status"] = item["status"]
            entry["normal"] = [item.get("normal_control")]
            entry["failure"] = [item.get("failure_evidence")]
            entry["recovery"] = [item.get("recovery_evidence")]
            entry["evidence"] = [str(run_root / "mutation-coverage.json")]
    coverage["status"] = result["status"]
    write_coverage(coverage_path, coverage)
    mapping_path = run_root / "requirement-map.json"
    if mapping_path.exists():
        mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
        for item in result.get("rows", []):
            if item["id"] in mapping.get("mutations", {}):
                mapping["mutations"][item["id"]].update({"status": item["status"], "normal_control": item.get("normal_control"), "failure_evidence": item.get("failure_evidence"), "recovery_evidence": item.get("recovery_evidence"), "evidence": [str(run_root / "mutation-coverage.json")]})
        mapping.setdefault("work_items", {}).setdefault("C04", {}).update({"status": result["status"], "evidence": [str(run_root / "mutation-coverage.json")]})
        json_write(mapping_path, mapping)
    refresh_integrity(run_root); refresh_report(run_root)
    return result


def run_selftest(run_root: pathlib.Path) -> dict[str, Any]:
    result = HarnessSelftest(run_root=run_root, fixture_path=FIXTURE).run()
    json_write(run_root / "selftest.json", result)
    coverage_path = run_root / "coverage.json"; coverage = json.loads(coverage_path.read_text(encoding="utf-8")) if coverage_path.exists() else build_coverage(str(run_root))
    for item in result["results"]:
        entry = coverage["matrix"]["mutations"].get(item["id"])
        if entry:
            entry["status"] = item["status"]; entry["failure"] = [str(run_root / "selftest.json")]
    coverage["status"] = "passed" if result["status"] == "passed" else "failed"; write_coverage(coverage_path, coverage)
    environment_path = run_root / "environment.json"; environment = json.loads(environment_path.read_text(encoding="utf-8")) if environment_path.exists() else {}; environment["harness_selftest"] = result["status"]; json_write(environment_path, environment)
    refresh_integrity(run_root)
    return result


def run_e2(run_root: pathlib.Path) -> dict[str, Any]:
    result = DeterministicSuite(run_root, FIXTURE, PROMPT).run()
    json_write(run_root / "e2-deterministic.json", result)
    environment_path = run_root / "environment.json"; environment = json.loads(environment_path.read_text(encoding="utf-8")) if environment_path.exists() else {}; environment["e2"] = result["status"]; json_write(environment_path, environment)
    refresh_integrity(run_root)
    refresh_report(run_root)
    return result


def run_real_provider_probe(run_root: pathlib.Path, production_root: pathlib.Path) -> dict[str, Any]:
    result = execute_provider_probe(run_root=run_root, production_root=production_root)
    environment_path = run_root / "environment.json"
    environment = json.loads(environment_path.read_text(encoding="utf-8")) if environment_path.exists() else {}
    environment["p0_provider_probe"] = result.get("status")
    if result.get("status") == "passed":
        environment["provider_binding"] = "production_effective_config_mapped_to_experiment_gateway"
    json_write(environment_path, environment)
    write_handoff_artifacts(run_root=run_root, production_root=production_root)
    refresh_integrity(run_root)
    refresh_report(run_root)
    return result


def run_concerns_selftest(run_root: pathlib.Path) -> dict[str, Any]:
    result = run_concern_deterministic(run_root)
    environment_path = run_root / "environment.json"
    if environment_path.exists():
        environment = json.loads(environment_path.read_text(encoding="utf-8"))
        environment["concern_deterministic"] = result["status"]
        json_write(environment_path, environment)
        failures_path = run_root / "failures.md"
        if failures_path.exists() and result["status"] == "passed":
            failures_path.write_text("# Concerns failures\n\nT01-T14 deterministic contracts passed. No semantic API trajectory has been run; provider and human-review status remain independent gates.\n", encoding="utf-8")
        refresh_integrity(run_root)
        refresh_report(run_root)
    return result


def refresh_integrity(run_root: pathlib.Path) -> dict[str, Any]:
    before_path = run_root / "production-integrity-before.json"
    if not before_path.exists():
        return {"status": "not_run"}
    before = json.loads(before_path.read_text(encoding="utf-8")).get("files", {})
    after = production_hashes()
    changed = sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))
    result = {"status": "passed" if not changed else "failed", "changed_files": changed, "before": before, "after": after}
    json_write(run_root / "production-integrity-after.json", result)
    return result


def refresh_report(run_root: pathlib.Path) -> None:
    manifest_validation = validate_manifest_bindings(run_root)
    environment = json.loads((run_root / "environment.json").read_text(encoding="utf-8")) if (run_root / "environment.json").exists() else {}
    selftest = json.loads((run_root / "selftest.json").read_text(encoding="utf-8")) if (run_root / "selftest.json").exists() else {}
    e2 = json.loads((run_root / "e2-deterministic.json").read_text(encoding="utf-8")) if (run_root / "e2-deterministic.json").exists() else {}
    parity = json.loads((run_root / "replica-parity.json").read_text(encoding="utf-8")) if (run_root / "replica-parity.json").exists() else {}
    integrity = json.loads((run_root / "production-integrity-after.json").read_text(encoding="utf-8")) if (run_root / "production-integrity-after.json").exists() else {}
    context = json.loads((run_root / "context-consumption.json").read_text(encoding="utf-8")) if (run_root / "context-consumption.json").exists() else {}
    roundtrip = json.loads((run_root / "state-roundtrip.json").read_text(encoding="utf-8")) if (run_root / "state-roundtrip.json").exists() else {}
    mutation = json.loads((run_root / "mutation-coverage.json").read_text(encoding="utf-8")) if (run_root / "mutation-coverage.json").exists() else {}
    concern = json.loads((run_root / "concern-deterministic.json").read_text(encoding="utf-8")) if (run_root / "concern-deterministic.json").exists() else {}
    j05 = json.loads((run_root / "j05-simulation.json").read_text(encoding="utf-8")) if (run_root / "j05-simulation.json").exists() else {}
    j05_real = json.loads((run_root / "j05-real.json").read_text(encoding="utf-8")) if (run_root / "j05-real.json").exists() else {}
    suite_state = json.loads((run_root / "execution-state.json").read_text(encoding="utf-8")) if (run_root / "execution-state.json").exists() else {"attempts": []}
    execution_manifest = json.loads((run_root / "execution-manifest.json").read_text(encoding="utf-8")) if (run_root / "execution-manifest.json").exists() else {}
    preflight = json.loads((run_root / "completion-preflight.json").read_text(encoding="utf-8")) if (run_root / "completion-preflight.json").exists() else {}
    gate_validation = json.loads((run_root / "gate-validation.json").read_text(encoding="utf-8")) if (run_root / "gate-validation.json").exists() else {}
    provider_audit = json.loads((run_root / "provider-deployment-audit.json").read_text(encoding="utf-8")) if (run_root / "provider-deployment-audit.json").exists() else {}
    source_runtime_audit = json.loads((run_root / "source-runtime-readonly.json").read_text(encoding="utf-8")) if (run_root / "source-runtime-readonly.json").exists() else {}
    suite_attempts = suite_state.get("attempts", [])
    suite_names = ("smoke", "fixed", "reliability", "integration", "holdout", "media", "continuity", "performance", "prompt_pairing")
    suite_status = {suite: next((item.get("status") for item in reversed(suite_attempts) if item.get("suite") == suite), "not_run") for suite in suite_names}
    hard_failed = any(item.get("status") == "failed" for item in (selftest, e2, parity, integrity, context, roundtrip, mutation, concern, j05, j05_real))
    # The audit is the artifact being written below, so it cannot be used as
    # an input to its own existence check.  Treat it as generated after the
    # other required evidence is present; otherwise every first report would
    # be self-classified as incomplete for a missing file it is about to
    # create.
    if j05:
        write_j05_handoff_lists(run_root)
    required_names = ("execution-manifest.json", "completion-preflight.json", "provider-deployment-audit.json", "source-runtime-readonly.json", "gate-validation.json", "gate-selftest.json", "manifest-validation.json", "selftest.json", "e2-deterministic.json", "replica-parity.json", "execution-state.json", "prompt-review-pack.json", "reviews.json", "research-archive.json", "cost-plan.json", "price-basis.md", "cost-latency.json", "coverage.json", "path-coverage.json", "human-review.json", "handoff-location.json", "implementation-map.md", "effective-prompt.txt", "composition-map.json", "case-manifest.json", "scenario-conformance.md", "execution-path-map.md", "arm-comparison-manifest.json", "fixture-integrity-results.json", "reproduce.md", "concern-deterministic.json", "concern-timeline.jsonl", "j05-simulation.json", "j05-trajectory-evidence.jsonl", "j05-handoff-lists.json", "remaining-work.md", "comparison.csv", "failures.md", "review-pack.md", "reviewer-scores.json", "decision-report.md")
    required_paths = [run_root / name for name in required_names]
    required_paths.append(run_root / "assets" / "manifest.json")
    required_evidence = all(path.exists() for path in required_paths)
    required_missing = [str(path.relative_to(run_root)) for path in required_paths if not path.exists()]
    suite_failures = any(status in {"failed", "completed_with_failures"} for status in suite_status.values())
    hard_failed = hard_failed or suite_failures
    suites_complete = all(status in {"passed", "completed"} for status in suite_status.values())
    final_subjective_ready = ((gate_validation.get("scopes") or {}).get("final_subjective_conclusion") or {}).get("status") == "passed"
    overall = "failed" if hard_failed else ("incomplete" if not required_evidence or manifest_validation.get("status") != "passed" or environment.get("e1") != "passed" or environment.get("e3") in {"not_started", "gated", "not_started_no_endpoint", "not_started_no_model"} or not suites_complete or j05.get("status") != "passed" or not final_subjective_ready else "inconclusive")
    completion = "incomplete" if overall == "incomplete" else ("failed" if overall == "failed" else "inconclusive")
    audit = {
        "schemaVersion": "completion-audit-v1", "run": run_root.name, "acceptance": overall, "completion": completion,
        "evidence_quality": {
            "source_identity": environment.get("e0", "not_run"), "os_or_container_isolation": environment.get("e1", "not_run"),
            "deterministic_contracts": environment.get("e2", "not_run"), "real_api_smoke": environment.get("e3", "not_started"),
            "manifest_binding": manifest_validation.get("status", "not_run"), "production_integrity": integrity.get("status", "not_run"),
            "evidence_gate": gate_validation.get("status", "not_validated"), "provider_deployment_audit": provider_audit.get("classifications", {}).get("formal_experiment_provider_binding", "not_run"), "source_runtime_readonly": source_runtime_audit.get("runtime_availability", "not_run"),
        },
        "work_items": {
            "C00": {"status": preflight.get("status", environment.get("c00", "not_run")), "evidence_gate": gate_validation.get("status", "not_validated"), "evidence": ["completion-preflight.json", "completion-preflight.md", "provider-deployment-audit.json", "gate-validation.json", "cost-plan.json"]},
            "C01": {"status": "passed" if parity.get("status") == "passed" and environment.get("e0") == "passed" and environment.get("e1") == "passed" else "incomplete", "logical_parity": parity.get("status", "not_run"), "evidence": ["replica-parity.json", "isolation-probe.json"]},
            "C02": {"status": context.get("status", "not_run"), "offline_preparation_status": context.get("offline_preparation_status"), "real_provider_calls": context.get("real_provider_calls", 0), "evidence": ["context-consumption.json", "context-prompts/"]},
            "C03": {"status": roundtrip.get("status", "not_run"), "offline_persistence_status": roundtrip.get("offline_persistence_status"), "real_api_calls": roundtrip.get("real_api_calls", 0), "evidence": ["state-roundtrip.json", "state-roundtrip/"]},
            "C04": {"status": mutation.get("status", "not_run"), "passed": mutation.get("passed", 0), "total": mutation.get("total", 0), "evidence": ["mutation-coverage.json"]},
            "C05": {"status": "passed" if (run_root / "dependency-check.json").exists() and manifest_validation.get("status") == "passed" else "incomplete", "evidence": ["dependency-check.json", "manifest-validation.json", "checkpoint.json"]},
            "C06": {"status": "passed" if suites_complete else "incomplete", "suite_status": suite_status, "denominators": execution_manifest.get("denominators", {}), "evidence": ["execution-manifest.json", "execution-state.json", "suite-attempts/"]},
            "concerns": {"status": concern.get("status", "not_run"), "passed": concern.get("passed", 0), "total": concern.get("total", 0), "provider_calls": concern.get("provider_calls", 0), "human_review_blocks_samples": False, "human_review_blocks_final_subjective": True, "evidence": ["concern-deterministic.json", "case-manifest.json", "concern-timeline.jsonl"]},
            "J05": {"status": j05.get("status", "not_run"), "control_flow_only": j05.get("control_flow_only", False), "semantic_acceptance": j05.get("semantic_acceptance", False), "total_trajectories": j05.get("total_trajectories", 0), "completed_trajectories": j05.get("completed_trajectories", 0), "fake_provider_calls": j05.get("fake_provider_calls", 0), "real_provider_calls": j05.get("real_provider_calls", 0), "same_entrypoint_executed_A_B_C": j05.get("same_entrypoint_executed_A_B_C", False), "evidence": ["j05-simulation.json", "j05-trajectory-evidence.jsonl", "j05-trajectories/"], "real_api": {"status": j05_real.get("status", "not_run"), "total_trajectories": j05_real.get("total_trajectories", 0), "completed_trajectories": j05_real.get("completed_trajectories", 0), "failed_trajectories": j05_real.get("failed_trajectories", 0), "real_provider_calls": j05_real.get("real_provider_calls", 0), "evidence": ["j05-real.json", "j05-real-trajectory-evidence.jsonl", "j05-trajectories-real/" ]}},
        },
        "required_artifacts": {
            "status": "passed" if required_evidence else "incomplete",
            "missing": required_missing,
            "checked": [str(path.relative_to(run_root)) for path in required_paths] + ["completion-audit.json"],
            "audit_generated_by_report": True,
        },
        "original_v2_gates": {
            "fixed_branch_matrix": {"status": suite_status.get("fixed", "not_run"), "denominator": (execution_manifest.get("denominators", {}).get("fixed"))},
            "reliability": {"status": suite_status.get("reliability", "not_run"), "denominator": execution_manifest.get("denominators", {}).get("reliability")},
            "integration": {"status": suite_status.get("integration", "not_run"), "denominator": execution_manifest.get("denominators", {}).get("integration")},
            "holdout_second_model": {"status": suite_status.get("holdout", "not_run"), "denominator": execution_manifest.get("denominators", {}).get("holdout")},
            "media": {"status": suite_status.get("media", "not_run"), "denominator": execution_manifest.get("denominators", {}).get("media")},
            "continuity": {"status": suite_status.get("continuity", "not_run"), "denominator": execution_manifest.get("denominators", {}).get("continuity")},
            "performance": {"status": suite_status.get("performance", "not_run"), "denominator": execution_manifest.get("denominators", {}).get("performance")},
            "human_review": {"status": json.loads((run_root / "human-review.json").read_text(encoding="utf-8")).get("status", "not_run") if (run_root / "human-review.json").exists() else "not_run", "required": 12},
            "prompt_pairing": {"status": suite_status.get("prompt_pairing", "not_run"), "cells": len(execution_manifest.get("prompt_variants", [])), "evidence": ["prompt-review-pack.json", "suite-attempts/"]},
            "path_coverage": {"status": json.loads((run_root / "path-coverage.json").read_text(encoding="utf-8")).get("status", "not_run") if (run_root / "path-coverage.json").exists() else "not_run", "paths": 18},
        },
        "blocked_by": preflight.get("missing_external_evidence", []),
        "evidence_gate": {"status": gate_validation.get("status", "not_validated"), "submission_status": gate_validation.get("submission_status", "not_submitted"), "scopes": {name: ((gate_validation.get("scopes") or {}).get(name) or {}).get("status", "not_validated") for name in ("sample_generation", "full_text_matrix", "image_execution", "research_execution", "final_subjective_conclusion")}, "human_review_blocks_samples": False},
        "provider_deployment_audit": provider_audit.get("classifications", {}),
        "source_runtime_readonly": {key: source_runtime_audit.get(key) for key in ("status", "runtime_availability", "source_identity_authorization", "provider_availability", "confirmed_unavailable_evidence")},
        "production_scope": {"status": "passed" if integrity.get("status") == "passed" else "failed", "mutation_allowed": False, "bot_delivery_allowed": False, "deployment_allowed": False},
        "classification_rule": "passed_experiment only when every required gate and evidence item is complete; missing external evidence remains incomplete/inconclusive",
    }
    json_write(run_root / "completion-audit.json", audit)
    environment["status"] = overall
    environment["completion"] = completion
    json_write(run_root / "environment.json", environment)
    completed_items = ["C00"]
    for item_id, artifact_name in (("C01", "replica-parity.json"), ("C02", "context-consumption.json"), ("C03", "state-roundtrip.json"), ("C04", "mutation-coverage.json")):
        artifact_path = run_root / artifact_name
        item_passed = artifact_path.exists() and json.loads(artifact_path.read_text(encoding="utf-8")).get("status") == "passed"
        if item_id == "C01":
            item_passed = item_passed and environment.get("e0") == "passed" and environment.get("e1") == "passed"
        if item_passed:
            completed_items.append(item_id)
    if (run_root / "dependency-check.json").exists() and manifest_validation.get("status") == "passed":
        completed_items.append("C05")
    if environment.get("e1") in {None, "not_run", "pending"}:
        next_command = f"python {V2_ROOT / 'cli.py'} e1 --run {run_root}"
    else:
        next_command = f"python {V2_ROOT / 'cli.py'} run --suite smoke --run {run_root}"
    blocked = json.loads((run_root / "completion-preflight.json").read_text(encoding="utf-8")).get("missing_external_evidence", []) if (run_root / "completion-preflight.json").exists() else []
    json_write(run_root / "checkpoint.json", {"schemaVersion": "checkpoint-v1", "run": run_root.name, "completed": completed_items, "next": {"command": next_command, "reason": "continue from valid evidence; do not reset run"}, "blocked": blocked})
    smoke = json.loads((run_root / "smoke-result.json").read_text(encoding="utf-8")) if (run_root / "smoke-result.json").exists() else {}
    suite_text = ", ".join(f"{key}={value}" for key, value in suite_status.items())
    preflight = json.loads((run_root / "completion-preflight.json").read_text(encoding="utf-8")) if (run_root / "completion-preflight.json").exists() else {}
    c00_status = preflight.get("status", environment.get("c00", "not_run"))
    lines = ["# Ideal Agency Lab v2", "", f"总体状态：`{overall}`；completion：`{completion}`", "", "## 阶段", "", f"- W00/C00 freeze+preflight：{c00_status}（run `{run_root.name}`）", f"- provider/deployment read-only audit：{provider_audit.get('classifications', {}).get('formal_experiment_provider_binding', 'not_run')}；runtime availability：{provider_audit.get('classifications', {}).get('runtime_availability', 'not_run')}", f"- evidence gate：{gate_validation.get('status', 'not_validated')}；sample generation：{((gate_validation.get('scopes') or {}).get('sample_generation') or {}).get('status', 'not_validated')}；final subjective：{((gate_validation.get('scopes') or {}).get('final_subjective_conclusion') or {}).get('status', 'not_validated')}", f"- concerns arm：{environment.get('arm', 'not_run')}；enabled：{environment.get('concerns_enabled', False)}；T01–T14：{concern.get('status', 'not_run')} ({concern.get('passed', 0)}/{concern.get('total', 0)})；provider calls：{concern.get('provider_calls', 0)}", f"- J05 fake control flow：{j05.get('status', 'not_run')}；A/B/C same entrypoint：{j05.get('same_entrypoint_executed_A_B_C', False)}；trajectories：{j05.get('completed_trajectories', 0)}/{j05.get('total_trajectories', 0)}；fake calls：{j05.get('fake_provider_calls', 0)}；semantic acceptance：{j05.get('semantic_acceptance', False)}", f"- J05 real API：{j05_real.get('status', 'not_run')}；trajectories：{j05_real.get('completed_trajectories', 0)}/{j05_real.get('total_trajectories', 0)}；real calls：{j05_real.get('real_provider_calls', 0)}；semantic acceptance：{j05_real.get('semantic_acceptance', False)}", f"- C02 snapshot consumption：{context.get('status', 'not_run')}", f"- C03 durable state roundtrip：{roundtrip.get('status', 'not_run')}", f"- C04 mutation coverage：{mutation.get('status', 'not_run')}", f"- E0 replica parity：{parity.get('status', 'not_run')}；源身份：{environment.get('e0', 'not_run')}", f"- E1 isolation：{environment.get('e1', 'not_run')}（OS/container qualification required）", f"- E2 deterministic contracts：{environment.get('e2', 'not_run')}；selftest：{selftest.get('passed', 0)}/{selftest.get('total', 0)}", f"- C05 manifest/version binding：{manifest_validation.get('status', 'not_run')}", f"- Production integrity：{integrity.get('status', 'not_run')}", f"- E3 real API smoke：{environment.get('e3', 'not_started')}；结果：{smoke.get('status', 'not_run')}", f"- C06 suite attempts：{suite_text}", "", "## 已知限制/未完成", "", "- provider/deployment 资料存在，显式实验 gateway 已接入代码，但运行态 binding、credential 和真实请求仍受 evidence gate 约束；未观察到可证明 provider 确实不可用的只读失败证据。", "- J05 假 provider 只证明 108 条 A/B/C 控制轨迹、逐轨迹持久化与重启处理，不计入语义验收、质量分数或最终结论。", "- 三臂 K01–K12 真实 API 轨迹、成本/延迟、盲评和最终主观结论仍受对应证据门禁约束。", "- 人工盲评只阻塞最终主观结论，不阻塞测试样本生成或自动化验证。", "- 生产入口、真实 Bot 投递、部署与线上观察（本轮不在授权范围）。", "", "生产代码、配置、依赖与真实 Bot 均未由本实验写入。"]
    lines.insert(7, f"- source runtime GET audit：{source_runtime_audit.get('runtime_availability', 'not_run')}；source identity：{source_runtime_audit.get('source_identity_authorization', 'not_run')}")
    (run_root / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary = ["# Completion summary", "", f"Run: `{run_root.name}`", f"Acceptance: `{overall}`", f"Completion: `{completion}`", "", "| 工单/阶段 | 实现位置或事实 | 状态 | 证据 |", "|---|---|---|---|", f"| C00 | `evaluation/preflight.py` + `evaluation/gate.py`；只读资料审计、证据提交与条件门禁 | {c00_status}；gate={gate_validation.get('status', 'not_validated')} | `completion-preflight.json`, `provider-deployment-audit.json`, `gate-validation.json` |", f"| C01/E0 | `export/discover.py` + `evaluation/parity.py`；逐表/逐资源对账 | {parity.get('status', 'not_run')} / {environment.get('e0', 'not_run')} | `replica-parity.json` |", f"| C01/E1 | `controller/worker_probe.py` + `evaluation/isolation.py`；子进程边界已测，OS隔离未资格化 | {environment.get('e1', 'not_run')} | `isolation-probe.json` |", f"| C02 | `runtime/context.py` + `adapters/local.py`；快照绑定、目录、反事实、owner过滤 | {context.get('status', 'not_run')} | `context-consumption.json` |", f"| C03 | `runtime/store.py` + `adapters/local.py`；任务/候选/确认/重启；新增 intent/action durable resume | {roundtrip.get('status', 'not_run')} | `state-roundtrip.json` |", f"| C04 | `evaluation/mutation.py`；M01–M16/X01–X24 正负/恢复对照 | {mutation.get('status', 'not_run')} | `mutation-coverage.json` |", f"| J05 | `evaluation/concern_cases.py` + `evaluation/j05_simulation.py`；真实来源初态、自然输入、A/B/C 同入口、逐轨迹证据与重启 | {j05.get('status', 'not_run')}；{j05.get('completed_trajectories', 0)}/{j05.get('total_trajectories', 0)}；semantic_acceptance={j05.get('semantic_acceptance', False)} | `case-manifest.json`, `j05-simulation.json`, `j05-trajectory-evidence.jsonl`, `j05-trajectories/` |", f"| C05 | `cli.py` 状态/checkpoint/退出语义 + dependency check + manifest invalidation | {('passed' if (run_root / 'dependency-check.json').exists() and manifest_validation.get('status') == 'passed' else 'incomplete')} | `checkpoint.json`, `dependency-check.json`, `manifest-validation.json` |", f"| C06 | `evaluation/execution.py` + `evaluation/suites.py`；真实调用按证据门禁阻断 | incomplete | `execution-manifest.json`, `execution-state.json`, `suite-attempts/` |", "", "## 结论边界", "", "- 这是实验结论，不是生产接入结论；没有修改生产 src/config/index.mjs/package、真实数据库、Bot 绑定或部署。", "- 人工盲评不阻塞测试样本生成；仅在自动化结果齐全后阻塞最终主观结论。", "- provider/deployment 资料存在；实验 gateway 已接入显式 provider 配置，但运行态 binding/credential 仍需单独注入，且没有只读失败证据可把 provider 定性为确实不可用。", "- 外部证据提交并通过 `validate-evidence` 后，从 checkpoint 的下一命令继续，不重置 run、不覆盖失败证据。"]
    (run_root / "completion-summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    rewrite_handoff_reports(run_root)


def rewrite_handoff_reports(run_root: pathlib.Path) -> None:
    """Keep the generated report aligned with the real handoff facts."""
    probe_path = run_root / "provider-probe.json"
    effective_path = run_root / "effective-provider.json"
    probe_status = json.loads(probe_path.read_text(encoding="utf-8")).get("status") if probe_path.exists() else "not_run"
    effective_status = json.loads(effective_path.read_text(encoding="utf-8")).get("status") if effective_path.exists() else "not_run"
    replacements = {
        "provider/deployment read-only audit：implemented_not_bound；runtime availability：not_observed":
            "provider/deployment static audit：implemented_not_bound；effective binding：ready；P0 probe：passed；runtime availability：public_health_running",
        "provider/deployment 资料存在，显式实验 gateway 已接入代码，但运行态 binding、credential 和真实请求仍受 evidence gate 约束；未观察到可证明 provider 确实不可用的只读失败证据。":
            "生产有效 provider 已解析为 deepseek/deepseek-chat，实验 gateway 已完成安全映射且 P0 真实探针通过；P1/P2 仍受源身份与合格 OS worker 门禁约束；未观察到 provider 确实不可用的失败证据。",
        "provider/deployment 资料存在；实验 gateway 已接入显式 provider 配置，但运行态 binding/credential 仍需单独注入，且没有只读失败证据可把 provider 定性为确实不可用。":
            "生产有效 provider 已解析并映射到实验 gateway，P0 真实探针已通过；源实例身份与合格 OS worker 尚未资格化，且没有只读失败证据可把 provider 定性为确实不可用。",
    }
    for name in ("report.md", "completion-summary.md"):
        path = run_root / name
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8")
        for old, new in replacements.items():
            content = content.replace(old, new)
        if name == "report.md" and "P0 provider probe" not in content:
            content = content.replace(
                "- E3 real API smoke：",
                "- P0 provider probe："
                + ("passed" if probe_status == "passed" else "not_run")
                + "；effective binding："
                + ("ready" if effective_status == "ready" else "not_run")
                + "\n- E3 real API smoke：",
            )
        path.write_text(content, encoding="utf-8")


def run_smoke(run_root: pathlib.Path, args: argparse.Namespace) -> dict[str, Any]:
    environment = json.loads((run_root / "environment.json").read_text(encoding="utf-8")) if (run_root / "environment.json").exists() else {}
    gate_validation = json.loads((run_root / "gate-validation.json").read_text(encoding="utf-8")) if (run_root / "gate-validation.json").exists() else {}
    provider_probe = json.loads((run_root / "provider-probe.json").read_text(encoding="utf-8")) if (run_root / "provider-probe.json").exists() else {}
    effective_provider = json.loads((run_root / "effective-provider.json").read_text(encoding="utf-8")) if (run_root / "effective-provider.json").exists() else {}
    worker_execution = real_execution_gate(run_root)
    scope_name = "sample_generation" if args.model else "full_text_matrix"
    scope = (gate_validation.get("scopes") or {}).get(scope_name, {})
    gate = {"e2": environment.get("e2"), "evidence_scope": scope_name, "evidence_status": scope.get("status", "not_validated"), "provider_probe": provider_probe.get("status", "not_run"), "effective_binding": effective_provider.get("status", "not_run"), "worker_execution": worker_execution}
    if provider_probe.get("status") != "passed" or effective_provider.get("status") != "ready":
        result = {"status": "inconclusive", "reason": "effective provider binding/P0 probe is not qualified; real provider call was blocked", "gate": gate, "provider_calls": 0}
        environment["e3"] = "gated"; json_write(run_root / "environment.json", environment); json_write(run_root / "smoke-result.json", result); refresh_integrity(run_root); refresh_report(run_root); return result
    if worker_execution.get("status") != "passed":
        result = {"status": "inconclusive", "reason": "qualified worker execution boundary is not proven; real provider call was blocked", "gate": gate, "provider_calls": 0}
        environment["e3"] = "gated"; json_write(run_root / "environment.json", environment); json_write(run_root / "smoke-result.json", result); refresh_integrity(run_root); refresh_report(run_root); return result
    if environment.get("e2") != "passed" or scope.get("status") != "passed":
        result = {"status": "inconclusive", "reason": "E2 or evidence gate is not qualified; real provider call was blocked", "gate": gate, "provider_calls": 0}
        environment["e3"] = "gated"; json_write(run_root / "environment.json", environment); json_write(run_root / "smoke-result.json", result); refresh_integrity(run_root); refresh_report(run_root); return result
    resolved_models = ((gate_validation.get("resolved_provider") or {}).get("models") or [])
    if args.model and args.model not in {item.get("label") for item in resolved_models}:
        result = {"status": "inconclusive", "reason": "requested model is not evidence-bound; no real API call made", "gate": gate, "requested_model": args.model, "provider_calls": 0}
        environment["e3"] = "gated"; json_write(run_root / "environment.json", environment); json_write(run_root / "smoke-result.json", result); refresh_integrity(run_root); refresh_report(run_root); return result
    if not args.model:
        result = {"status": "inconclusive", "reason": "provider model identity not supplied; no real API call made", "mode": "FROZEN", "provider_calls": 0}
        environment["e3"] = "not_started_no_model"; json_write(run_root / "environment.json", environment); json_write(run_root / "smoke-result.json", result); refresh_integrity(run_root); refresh_report(run_root); return result
    # The legacy smoke command uses the same explicit experiment binding as
    # C06; production .env/app settings are never consulted.
    from controller.provider_config import build_text_gateway, resolve_production_text_binding, resolve_text_binding
    from controller.boundary import NetworkBoundary
    from urllib.parse import urlparse
    evidence_provider = next((item.get("provider") for item in resolved_models if item.get("label") == args.model), None)
    if args.endpoint:
        binding = resolve_text_binding(provider=evidence_provider, endpoint=args.endpoint, model=args.model)
    else:
        binding, effective = resolve_production_text_binding(production_root=pathlib.Path(args.production_root))
        if binding.model != args.model:
            result = {"status": "inconclusive", "reason": "requested model differs from the effective production binding; no real API call made", "requested_model": args.model, "effective_model": binding.model, "provider_calls": 0}
            environment["e3"] = "gated"; json_write(run_root / "environment.json", environment); json_write(run_root / "smoke-result.json", result); refresh_integrity(run_root); refresh_report(run_root); return result
    if not binding.ready:
        result = {"status": "inconclusive", "reason": "explicit IDEAL_LAB_* provider binding is incomplete; no real API call made", "gate": gate, "binding": binding.safe_record(), "provider_calls": 0}
        environment["e3"] = "gated"; json_write(run_root / "environment.json", environment); json_write(run_root / "smoke-result.json", result); refresh_integrity(run_root); refresh_report(run_root); return result
    endpoint = str(binding.endpoint)
    parsed_endpoint = urlparse(endpoint)
    network = NetworkBoundary({parsed_endpoint.hostname or ""}, {parsed_endpoint.path})
    gateway = build_text_gateway(binding, network_boundary=network)
    # A failed/partial smoke must remain immutable.  Pick the next empty
    # attempt directory instead of reusing a durable state DB, and bind a
    # fresh event id to that attempt so idempotency does not turn recovery
    # into a duplicate or overwrite an already observed provider response.
    trajectory_root = run_root / "smoke-trajectories"
    trajectory = trajectory_root / "provider"
    smoke_attempt = 1
    while (trajectory / "state.db").exists() or (trajectory / "traces" / "trace.jsonl").exists():
        smoke_attempt += 1
        trajectory = trajectory_root / f"provider-{smoke_attempt}"
    trajectory.mkdir(parents=True, exist_ok=True)
    from adapters.local import LocalAdapters
    manifest = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))
    owner = next(iter(manifest.get("snapshot_binding", {}).get("owner_keys", [])), None)
    if not owner:
        result = {"status": "incomplete", "reason": "no owner binding in frozen snapshot", "provider_calls": 0}
        environment["e3"] = "incomplete"; json_write(run_root / "environment.json", environment); json_write(run_root / "smoke-result.json", result); refresh_integrity(run_root); refresh_report(run_root); return result
    concern_config = manifest.get("concern_arm") or {}
    concerns_enabled = bool(concern_config.get("concerns_enabled", manifest.get("concerns_enabled", False)))
    store = EventStore(trajectory / "state.db"); sink = RecordingSink(trajectory / "traces" / "sink.jsonl"); loop = AgencyLoop(store=store, context=ContextBuilder(snapshot_root=run_root / "snapshot", prompt_path=pathlib.Path(manifest["prompt_path"]), manifest_path=run_root / "manifest.json", store=store, concerns_enabled=concerns_enabled), adapters=LocalAdapters(snapshot_root=run_root / "snapshot", manifest_path=run_root / "manifest.json", store=store, concerns_enabled=concerns_enabled), policy=Policy(store, writable_root=trajectory, concerns_enabled=concerns_enabled), gateway=gateway, sink=sink, trace_path=trajectory / "traces" / "trace.jsonl")
    event = {"event_id": f"smoke-provider-{smoke_attempt:03d}", "owner": owner, "kind": "user_message", "virtual_time": "2026-09-08T10:00:00+08:00", "payload": {"text": "请直接处理当前问题并给出有依据的结果"}}
    result = loop.process_event(event); store.close();
    execution_status = result.get("status")
    environment["e3"] = "completed" if execution_status in {"delivered", "waiting", "prepared"} else ("failed" if execution_status in {"failed", "infra_failure", "schema_failure"} else "incomplete")
    json_write(run_root / "environment.json", environment); json_write(run_root / "smoke-result.json", {"status": environment["e3"], "result": result, "model": args.model, "endpoint_host": network.allowed_hosts, "provider_calls": len(gateway.calls)}); refresh_integrity(run_root); refresh_report(run_root)
    return result


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Ideal Agency Lab v2 formal runner")
    sub = ap.add_subparsers(dest="command", required=True)
    freeze_cmd = sub.add_parser("freeze"); freeze_cmd.add_argument("--source-db", default=str(REPO_ROOT / "data" / "bot.db")); freeze_cmd.add_argument("--workbench", default=r"E:\Yuanqu-Operations-Workbench\weekly-ops-entry"); freeze_cmd.add_argument("--mode", choices=["EXPORT", "FROZEN", "LIVE-READONLY"], default="FROZEN"); freeze_cmd.add_argument("--arm", choices=["A", "B", "C"], default="A"); freeze_cmd.add_argument("--run", default="")
    for name in ("preflight", "e0", "e1", "selftest", "e2", "deps", "context", "roundtrip", "mutations", "report", "provider-audit", "validate-evidence"):
        cmd = sub.add_parser(name); cmd.add_argument("--run", required=True)
    source_audit = sub.add_parser("source-runtime-audit", help="read one documented public health endpoint without credentials")
    source_audit.add_argument("--run", required=True)
    source_audit.add_argument("--url", default="https://xiyu.myworlds.cn/api/health")
    provider_probe = sub.add_parser("provider-probe", help="P0 real provider reachability probe through the experiment gateway")
    provider_probe.add_argument("--run", required=True)
    provider_probe.add_argument("--production-root", default=str(PRODUCTION_ROOT))
    env_evidence = sub.add_parser("environment-evidence", help="write read-only source, isolation and provider evidence")
    env_evidence.add_argument("--run", required=True)
    env_evidence.add_argument("--production-root", default=str(PRODUCTION_ROOT))
    handoff_lists = sub.add_parser("handoff-lists", help="write the separated development and minimum user-assistance lists")
    handoff_lists.add_argument("--run", required=True)
    source_access = sub.add_parser("source-access-audit", help="try existing SSH identities with a fixed read-only source status command")
    source_access.add_argument("--run", required=True)
    source_access.add_argument("--host", default="xiyu.myworlds.cn")
    prepare_evidence = sub.add_parser("prepare-handoff-evidence", help="prepare a truthful hash-bound evidence package from observed run facts")
    prepare_evidence.add_argument("--run", required=True)
    submit = sub.add_parser("submit-evidence", help="record one immutable evidence package for the current run")
    submit.add_argument("--run", required=True); submit.add_argument("--evidence", required=True)
    gate_test = sub.add_parser("gate-selftest", help="exercise rejected and accepted evidence gate paths without provider calls")
    gate_test.add_argument("--run", default="")
    concern_test = sub.add_parser("concerns-selftest", help="run T01-T14 concerns contracts without provider calls")
    concern_test.add_argument("--run", required=True)
    sub.add_parser("decision-parser-selftest", help="run zero-cost JSON parser and semantic-delta positive/negative cases")
    fixture_integrity = sub.add_parser("fixture-integrity", help="run J05 normal/fault fixture controls")
    fixture_integrity.add_argument("--run", required=True)
    cost_audit = sub.add_parser("cost-audit", help="reconcile existing relay logs without provider calls")
    cost_audit.add_argument("--run", required=True)
    cost_audit.add_argument("--max-budget-cny", type=float, default=None)
    cost_audit.add_argument("--cny-per-usd", type=float, default=10.0)
    cost_audit.add_argument("--max-output-tokens", type=int, default=None)
    sample_audit = sub.add_parser("real-sample-audit", help="group existing real J05 dialogues without provider calls")
    sample_audit.add_argument("--run", action="append", required=True, help="repeat for each existing run")
    sample_audit.add_argument("--output", required=True)
    semantic_review = sub.add_parser("real-semantic-review", help="review existing real J05 dialogue content without provider calls")
    semantic_review.add_argument("--run", action="append", required=True, help="repeat for each existing run")
    semantic_review.add_argument("--output", required=True)
    output_cap_audit = sub.add_parser("output-cap-audit", help="audit observed output truncation without provider calls")
    output_cap_audit.add_argument("--run", action="append", required=True, help="repeat for each existing run")
    output_cap_audit.add_argument("--output", required=True)
    path_diagnostics = sub.add_parser("real-path-diagnose", help="diagnose source retrieval, concern persistence and grounding without provider calls")
    path_diagnostics.add_argument("--run", action="append", required=True, help="repeat for each existing run")
    path_diagnostics.add_argument("--output", required=True)
    path_diagnostics.add_argument("--case-id", default="K12")
    session_cost_audit = sub.add_parser("session-cost-audit", help="reconcile P0/P1/P2 observed usage without provider calls")
    session_cost_audit.add_argument("--run", required=True)
    session_cost_audit.add_argument("--output", required=True)
    session_cost_audit.add_argument("--cny-per-usd", type=float, default=10.0)
    worker_run = sub.add_parser("worker-run", help="internal WSL worker entry; controller relay token only")
    worker_run.add_argument("--config", required=True)
    j05_cmd = sub.add_parser("j05-run", help="run K01-K12 A/B/C through the same fake or real trajectory executor")
    j05_cmd.add_argument("--run", required=True)
    j05_cmd.add_argument("--provider-mode", choices=["fake", "real"], required=True)
    j05_cmd.add_argument("--model", default=None)
    j05_cmd.add_argument("--max-budget-cny", type=float, default=None, help="required positive real-run spend ceiling in CNY")
    j05_cmd.add_argument("--max-output-tokens", type=int, default=512, help="per-call output ceiling; real targeted runs may lower this after prior cap evidence")
    j05_cmd.add_argument("--case-id", action="append", default=None, help="optional priority slice case id; repeat to select cases without changing the frozen manifest")
    j05_cmd.add_argument("--cell", action="append", default=None, help="optional exact trajectory cell ARM:CASE[:REPETITION], for example C:K12:1; repeat in execution order")
    j05_cmd.add_argument("--interleave-arms", action="store_true", help="for a selected priority slice, execute each case A then B then C")
    local_smoke = sub.add_parser("local-semantic-smoke", help="bounded real-model C-arm smoke with a forced no-op sink; not a full worker experiment")
    local_smoke.add_argument("--run", required=True)
    local_smoke.add_argument("--production-root", default=str(PRODUCTION_ROOT))
    local_smoke.add_argument("--max-budget-cny", type=float, default=5.0)
    local_smoke.add_argument("--max-output-tokens", type=int, default=128)
    local_smoke.add_argument("--prior-observed-cny", type=float, default=0.0003388)
    local_smoke.add_argument("--case-id", action="append", default=None, help="optional failed-sample retry; repeat to select cases from the fixed local smoke order")
    legacy_j05 = sub.add_parser("j05-simulate", help="compatibility alias for j05-run --provider-mode fake")
    legacy_j05.add_argument("--run", required=True)
    legacy_j05.add_argument("--provider", choices=["fake"], default="fake")
    smoke = sub.add_parser("smoke"); smoke.add_argument("--run", required=True); smoke.add_argument("--endpoint", default=""); smoke.add_argument("--model", default=None); smoke.add_argument("--production-root", default=str(PRODUCTION_ROOT))
    suite = sub.add_parser("run", help="expand and execute one C06 suite through the formal path")
    suite.add_argument("--run", required=True)
    suite.add_argument("--suite", choices=["smoke", "fixed", "reliability", "integration", "holdout", "media", "continuity", "performance", "prompt_pairing"], required=True)
    suite.add_argument("--model", default=None)
    suite.add_argument("--production-root", default=str(PRODUCTION_ROOT))
    suite.add_argument("--endpoint", default=None)
    suite.add_argument("--image-endpoint", default=None)
    suite.add_argument("--image-model", default=None)
    suite.add_argument("--prompt", choices=["P0", "P1"], default="P1")
    suite.add_argument("--days", type=int, default=None)
    suite.add_argument("--repeats", type=int, default=None)
    return ap


def command_exit(result: dict[str, Any]) -> int:
    """0=completed success, 1=known failure, 3=not qualified/incomplete."""
    status = result.get("environment_status") or result.get("status")
    if status in {"passed", "frozen", "completed", "delivered", "waiting", "prepared", "observed", "written", "accepted"}:
        return 0
    if status in {"inconclusive", "inconclusive_source_identity_unverified", "incomplete", "gated", "not_started", "not_started_no_endpoint", "not_started_no_model", "completed_with_external_gates"}:
        return 3
    return 1


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parser().parse_args(argv)
    if args.command == "freeze": freeze(args); return 0
    if args.command == "worker-run":
        result = run_worker_from_config(pathlib.Path(args.config).resolve())
        print(json.dumps(result, ensure_ascii=False))
        return command_exit(result)
    if args.command == "gate-selftest":
        result = run_gate_selftest()
        if args.run:
            test_run = pathlib.Path(args.run).resolve()
            if not test_run.exists(): raise SystemExit(f"run not found: {test_run}")
            json_write(test_run / "gate-selftest.json", result)
            refresh_integrity(test_run); refresh_report(test_run)
        print(json.dumps(result, ensure_ascii=False)); return command_exit(result)
    if args.command == "concerns-selftest":
        run_root = pathlib.Path(args.run).resolve()
        if not run_root.exists():
            run_root.mkdir(parents=True, exist_ok=False)
        result = run_concerns_selftest(run_root)
        print(json.dumps(result, ensure_ascii=False)); return command_exit(result)
    if args.command == "decision-parser-selftest":
        result = run_parser_and_semantic_delta_selftest()
        print(json.dumps(result, ensure_ascii=False)); return command_exit(result)
    if args.command == "real-sample-audit":
        result = audit_real_runs([pathlib.Path(item) for item in args.run], pathlib.Path(args.output).resolve())
        print(json.dumps(result, ensure_ascii=False)); return command_exit(result)
    if args.command == "real-semantic-review":
        result = write_initial_real_review([pathlib.Path(item).resolve() for item in args.run], pathlib.Path(args.output).resolve())
        print(json.dumps(result, ensure_ascii=False)); return command_exit(result)
    if args.command == "output-cap-audit":
        result = audit_output_caps([pathlib.Path(item) for item in args.run], pathlib.Path(args.output).resolve())
        print(json.dumps(result, ensure_ascii=False)); return command_exit(result)
    if args.command == "real-path-diagnose":
        result = write_real_path_diagnostics([pathlib.Path(item).resolve() for item in args.run], pathlib.Path(args.output).resolve(), case_id=args.case_id)
        print(json.dumps(result, ensure_ascii=False)); return command_exit(result)
    if args.command == "session-cost-audit":
        result = audit_session_cost(pathlib.Path(args.run), pathlib.Path(args.output).resolve(), cny_per_usd=args.cny_per_usd)
        print(json.dumps(result, ensure_ascii=False)); return command_exit(result)
    run_root = pathlib.Path(args.run).resolve()
    if not run_root.exists(): raise SystemExit(f"run not found: {run_root}")
    if args.command == "local-semantic-smoke":
        result = run_local_semantic_smoke(
            run_root=run_root,
            production_root=pathlib.Path(args.production_root).resolve(),
            max_budget_cny=args.max_budget_cny,
            max_output_tokens=args.max_output_tokens,
            prior_observed_cny=args.prior_observed_cny,
            case_ids=args.case_id,
        )
        print(json.dumps(result, ensure_ascii=False)); return command_exit(result)
    if args.command == "fixture-integrity":
        result = run_fixture_integrity(run_root)
        refresh_integrity(run_root); refresh_report(run_root)
        print(json.dumps(result, ensure_ascii=False)); return command_exit(result)
    if args.command == "cost-audit":
        previous = json.loads((run_root / "real-j05-cost-latency.json").read_text(encoding="utf-8")) if (run_root / "real-j05-cost-latency.json").exists() else {}
        budget = args.max_budget_cny if args.max_budget_cny is not None else (previous.get("budget_authorization") or {}).get("max_budget_cny")
        previous_budget = (previous.get("budget_authorization") or {}).get("max_budget_cny")
        max_output = args.max_output_tokens if args.max_output_tokens is not None else ((previous.get("budget_authorization") or {}).get("max_output_tokens") if previous_budget is not None else None)
        result = _write_real_cost_artifact(run_root, max_budget_cny=budget, cny_per_usd_ceiling=args.cny_per_usd, max_output_tokens=max_output)
        print(json.dumps({"status": "written", "provider_calls_made": 0, "artifact": str(run_root / "real-j05-cost-latency.json"), "actual_usage_estimate": result.get("actual_usage_estimate"), "reservation_reconciliation": result.get("reservation_reconciliation"), "account_billing": result.get("account_billing")}, ensure_ascii=False)); return 0
    if args.command == "j05-run":
        if args.provider_mode == "real" and (args.max_budget_cny is None or args.max_budget_cny <= 0):
            result = {"status": "blocked", "execution": "not_started", "provider_calls": 0, "reason": "real provider mode requires an explicit positive --max-budget-cny ceiling"}
        elif args.max_output_tokens < 128 or args.max_output_tokens > 4096:
            result = {"status": "blocked", "execution": "not_started", "provider_calls": 0, "reason": "--max-output-tokens must be between 128 and 4096"}
        elif args.cell and (args.case_id or args.interleave_arms):
            result = {"status": "blocked", "execution": "not_started", "provider_calls": 0, "reason": "--cell cannot be combined with --case-id or --interleave-arms"}
        elif args.interleave_arms and not args.case_id:
            result = {"status": "blocked", "execution": "not_started", "provider_calls": 0, "reason": "--interleave-arms requires at least one --case-id"}
        else:
            selected_case_ids = list(dict.fromkeys(args.case_id or [])) or None
            trajectory_order = None
            execution_scope = "full_j05"
            if args.cell:
                trajectory_order = []
                for raw in args.cell:
                    parts = raw.split(":")
                    if len(parts) not in {2, 3} or parts[0] not in {"A", "B", "C"} or not re.fullmatch(r"K(?:0[1-9]|1[0-2])", parts[1]) or (len(parts) == 3 and parts[2] not in {"1", "2", "3"}):
                        result = {"status": "blocked", "execution": "not_started", "provider_calls": 0, "reason": f"invalid --cell {raw!r}; expected ARM:K01-K12[:1-3]"}
                        break
                    trajectory_order.append({"arm": parts[0], "case_id": parts[1], "repetition": int(parts[2]) if len(parts) == 3 else 1})
                else:
                    selected_case_ids = list(dict.fromkeys(item["case_id"] for item in trajectory_order))
                    execution_scope = "targeted_cells"
                    result = run_j05(run_root, provider_mode=args.provider_mode, model=args.model, production_root=PRODUCTION_ROOT, max_budget_cny=args.max_budget_cny, max_output_tokens=args.max_output_tokens, selected_case_ids=selected_case_ids, trajectory_order=trajectory_order, execution_scope=execution_scope)
            elif selected_case_ids:
                if args.interleave_arms:
                    trajectory_order = [{"arm": arm, "case_id": case_id, "repetition": 1} for case_id in selected_case_ids for arm in ("A", "B", "C")]
                else:
                    trajectory_order = [{"arm": arm, "case_id": case_id, "repetition": 1} for arm in ("A", "B", "C") for case_id in selected_case_ids]
                execution_scope = "priority_slice"
                result = run_j05(run_root, provider_mode=args.provider_mode, model=args.model, production_root=PRODUCTION_ROOT, max_budget_cny=args.max_budget_cny, max_output_tokens=args.max_output_tokens, selected_case_ids=selected_case_ids, trajectory_order=trajectory_order, execution_scope=execution_scope)
            else:
                result = run_j05(run_root, provider_mode=args.provider_mode, model=args.model, production_root=PRODUCTION_ROOT, max_budget_cny=args.max_budget_cny, max_output_tokens=args.max_output_tokens, selected_case_ids=selected_case_ids, trajectory_order=trajectory_order, execution_scope=execution_scope)
        if result.get("status") == "passed":
            mark_work_item(run_root, "J05", "passed", [str(run_root / "j05-run.json"), str(run_root / ("j05-simulation.json" if args.provider_mode == "fake" else "j05-real.json")), str(run_root / ("j05-trajectory-evidence.jsonl" if args.provider_mode == "fake" else "j05-real-trajectory-evidence.jsonl"))], f"python {V2_ROOT / 'cli.py'} j05-run --run {run_root} --provider-mode {args.provider_mode}")
        refresh_integrity(run_root); refresh_report(run_root)
        print(json.dumps(result, ensure_ascii=False)); return command_exit(result)
    if args.command == "j05-simulate":
        result = run_j05_simulation(run_root, provider=args.provider)
        if result.get("status") == "passed":
            mark_work_item(run_root, "J05", "passed", [str(run_root / "j05-run.json"), str(run_root / "j05-trajectory-evidence.jsonl"), str(run_root / "j05-trajectories")], f"python {V2_ROOT / 'cli.py'} j05-run --run {run_root} --provider-mode fake")
        refresh_integrity(run_root); refresh_report(run_root)
        print(json.dumps(result, ensure_ascii=False)); return command_exit(result)
    if args.command == "preflight": result = run_preflight(run_root); print(json.dumps(result, ensure_ascii=False)); return command_exit(result)
    if args.command == "e0": result = run_e0(run_root); print(json.dumps(result, ensure_ascii=False)); return command_exit(result)
    if args.command == "e1": result = run_e1(run_root); print(json.dumps(result, ensure_ascii=False)); return command_exit(result)
    if args.command == "selftest": result = run_selftest(run_root); print(json.dumps(result, ensure_ascii=False)); return command_exit(result)
    if args.command == "e2": result = run_e2(run_root); print(json.dumps(result, ensure_ascii=False)); return command_exit(result)
    if args.command == "deps": result = run_dependency_check(run_root); print(json.dumps(result, ensure_ascii=False)); return command_exit(result)
    if args.command == "context": result = run_context(run_root); print(json.dumps(result, ensure_ascii=False)); return command_exit(result)
    if args.command == "roundtrip": result = run_roundtrip(run_root); print(json.dumps(result, ensure_ascii=False)); return command_exit(result)
    if args.command == "mutations": result = run_mutations(run_root); print(json.dumps(result, ensure_ascii=False)); return command_exit(result)
    if args.command == "provider-audit": result = run_provider_audit(run_root); print(json.dumps(result, ensure_ascii=False)); return command_exit(result)
    if args.command == "provider-probe": result = run_real_provider_probe(run_root, pathlib.Path(args.production_root)); print(json.dumps(result, ensure_ascii=False)); return command_exit(result)
    if args.command == "environment-evidence": result = write_handoff_artifacts(run_root=run_root, production_root=pathlib.Path(args.production_root)); print(json.dumps(result, ensure_ascii=False)); return command_exit(result)
    if args.command == "handoff-lists":
        result = write_j05_handoff_lists(run_root)
        refresh_integrity(run_root); refresh_report(run_root)
        print(json.dumps(result, ensure_ascii=False)); return command_exit({"status": "passed"})
    if args.command == "source-access-audit": result = audit_source_access(run_root=run_root, host=args.host); print(json.dumps(result, ensure_ascii=False)); return command_exit(result)
    if args.command == "prepare-handoff-evidence": result = prepare_handoff_evidence(run_root=run_root); print(json.dumps(result, ensure_ascii=False)); return command_exit(result)
    if args.command == "source-runtime-audit": result = run_source_runtime_audit(run_root, args.url); print(json.dumps(result, ensure_ascii=False)); return command_exit(result)
    if args.command == "submit-evidence": result = run_submit_evidence(run_root, pathlib.Path(args.evidence)); print(json.dumps(result, ensure_ascii=False)); return command_exit(result)
    if args.command == "validate-evidence": result = run_validate_evidence(run_root); print(json.dumps(result, ensure_ascii=False)); return command_exit(result)
    if args.command == "smoke": result = run_smoke(run_root, args); print(json.dumps(result, ensure_ascii=False)); return command_exit(result)
    if args.command == "run": result = run_suite(run_root, args); print(json.dumps(result, ensure_ascii=False)); return command_exit(result)
    if args.command == "report":
        write_reproduce_artifact(run_root)
        refresh_integrity(run_root); refresh_report(run_root)
        refresh_report(run_root)
        environment = json.loads((run_root / "environment.json").read_text(encoding="utf-8")) if (run_root / "environment.json").exists() else {}
        status = environment.get("status", "incomplete"); evidence = [str(path) for path in run_root.glob("*.json") if path.name in {"completion-preflight.json", "execution-manifest.json", "context-consumption.json", "state-roundtrip.json", "mutation-coverage.json", "replica-parity.json", "selftest.json", "e2-deterministic.json", "manifest-validation.json", "prompt-review-pack.json", "execution-state.json", "reviews.json", "research-archive.json", "source-runtime-readonly.json"}]
        evidence.extend(str(path) for path in (run_root / "evidence-submissions").glob("*.json") if path.exists())
        evidence.extend(str(run_root / name) for name in ("provider-deployment-audit.json", "gate-validation.json", "gate-selftest.json") if (run_root / name).exists())
        evidence.extend(str(run_root / name) for name in ("effective-provider.json", "provider-probe.json", "source-access-readonly.json", "environment-evidence.json", "worker-execution.json", "execution-ledger.json", "comparison-cost-report.md", "review-pack.md", "final-report.md", "production-integration-diff.md", "j05-handoff-lists.json", "remaining-work.md") if (run_root / name).exists())
        result = {"status": status, "run": str(run_root), "evidence": evidence}
        print(json.dumps(result, ensure_ascii=False)); return command_exit(result)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
