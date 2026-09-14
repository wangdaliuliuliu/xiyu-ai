"""C06 suite dispatcher.

Expand the frozen execution manifest into concrete denominators and record a
unique immutable attempt before a provider is ever contacted. Missing
authorization, isolation, model, or provider gates produce evidence of an
unstarted suite; they are never converted into a fake pass.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import time
import uuid
from copy import deepcopy
from typing import Any
from urllib.parse import urlparse


SUITES = ("smoke", "fixed", "reliability", "integration", "holdout", "media", "continuity", "performance", "prompt_pairing")
PROVIDER_SUITES = {"smoke", "fixed", "integration", "holdout", "media", "continuity", "performance", "prompt_pairing"}


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _write(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _read(path: pathlib.Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _short_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _models(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    models = manifest.get("models") or []
    return models if models else [
        {"role": "primary", "label": None, "status": "unverified"},
        {"role": "second", "label": None, "status": "unverified"},
    ]


def _gate(run_root: pathlib.Path, manifest: dict[str, Any], requested_model: str | None, endpoint: str | None, suite: str, image_endpoint: str | None = None, image_model: str | None = None) -> dict[str, Any]:
    environment = _read(run_root / "environment.json", {})
    preflight = _read(run_root / "completion-preflight.json", {})
    validation = _read(run_root / "manifest-validation.json", {})
    gate_validation = _read(run_root / "gate-validation.json", {})
    execution = preflight.get("execution", {})
    models = _models(manifest)
    resolved_models = (gate_validation.get("resolved_provider") or {}).get("models") or []
    if any(item.get("label") for item in resolved_models):
        models = _models({"models": resolved_models})
    provider_bindings = manifest.get("provider_bindings") or {}
    text_binding = provider_bindings.get("text") or {}
    image_binding = provider_bindings.get("image") or {}
    from controller.provider_config import resolve_image_binding, resolve_text_binding

    evidence_primary = (resolved_models[0] if resolved_models else (models[0] if models else {}))
    text_provider = evidence_primary.get("provider") or text_binding.get("provider")
    text_binding_runtime = resolve_text_binding(provider=text_provider, endpoint=endpoint, model=requested_model or evidence_primary.get("label"))
    image_binding_runtime = resolve_image_binding(provider=image_binding.get("provider"), endpoint=image_endpoint, model=image_model)
    reasons: list[str] = []
    if manifest.get("mode") != "FROZEN":
        reasons.append("formal C06 suites require a FROZEN manifest-bound snapshot")
    if validation.get("status") != "passed":
        reasons.append("manifest/version validation is not passed; refresh report before provider execution")
    if environment.get("e2") != "passed":
        reasons.append(f"E2 is not qualified: {environment.get('e2', 'not_run')}")
    scope_name = "sample_generation"
    if suite in {"fixed", "integration", "holdout"} or (suite == "smoke" and requested_model is None):
        scope_name = "full_text_matrix"
    if suite in {"media", "performance"}:
        scope_name = "image_execution"
    if suite == "reliability":
        scope_name = None
    if suite != "reliability":
        scope = (gate_validation.get("scopes") or {}).get(scope_name or "sample_generation")
        if not isinstance(scope, dict) or scope.get("status") != "passed":
            reasons.append(f"evidence gate {scope_name or 'sample_generation'} is not released")
            if isinstance(scope, dict):
                for item in scope.get("blocked_by", []):
                    reasons.append(f"{item.get('condition')}:{item.get('status')}")
            elif gate_validation.get("submission_status"):
                reasons.append(f"evidence_submission:{gate_validation.get('submission_status')}")
            else:
                reasons.append("no validated evidence submission")
    if requested_model and requested_model not in {item.get("label") for item in models}:
        reasons.append("requested model is not present in the frozen model list")
    if suite in PROVIDER_SUITES:
        if not text_binding_runtime.endpoint:
            reasons.append("provider endpoint is not supplied or not resolvable from the explicit experiment binding")
        else:
            parsed = urlparse(str(text_binding_runtime.endpoint))
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or not parsed.path:
                reasons.append("provider endpoint must be an explicit HTTP(S) URL with a path")
        if not text_binding_runtime.ready:
            reasons.append("experiment text gateway binding is incomplete; requires explicit IDEAL_LAB_PROVIDER_ENDPOINT, IDEAL_LAB_PROVIDER_MODEL and IDEAL_LAB_PROVIDER_API_KEY")
        if requested_model is None and suite not in {"media", "continuity", "performance", "prompt_pairing"} and not all(item.get("label") for item in models):
            reasons.append("full provider suite requires both frozen model identities; run a selected model only with --model")
    if suite in {"media", "performance"}:
        if not image_binding_runtime.endpoint:
            reasons.append("image provider endpoint is not supplied or not resolvable from the explicit experiment binding")
        else:
            image_parsed = urlparse(str(image_binding_runtime.endpoint))
            if image_parsed.scheme not in {"http", "https"} or not image_parsed.hostname or not image_parsed.path:
                reasons.append("image provider endpoint must be an explicit HTTP(S) URL with a path")
        if not image_model and not image_binding_runtime.model:
            reasons.append("image provider model identity is not supplied")
        if not image_binding_runtime.ready:
            reasons.append("experiment image gateway binding is incomplete; requires explicit IDEAL_LAB_IMAGE_ENDPOINT, IDEAL_LAB_IMAGE_MODEL and IDEAL_LAB_IMAGE_API_KEY")
        if image_binding.get("status") != "declared_unverified":
            # The evidence gate is authoritative once it has released the
            # image scope; old frozen manifests may have been created before
            # provider labels were supplied.
            if not ((gate_validation.get("resolved_provider") or {}).get("image") or {}).get("model"):
                reasons.append("frozen image provider/model binding is incomplete")
        resolved_image_model = ((gate_validation.get("resolved_provider") or {}).get("image") or {}).get("model")
        requested_image_model = image_model or image_binding_runtime.model
        if resolved_image_model and requested_image_model != resolved_image_model:
            reasons.append("requested image model is not the evidence-bound image model")
    return {
        "status": "passed" if not reasons else "blocked",
        "reasons": reasons,
        "environment": {key: environment.get(key) for key in ("e0", "e1", "e2", "e3")},
        "preflight_real_api_allowed": execution.get("real_api_main_group_allowed", False),
        "model_roles": [{"role": item.get("role"), "label": item.get("label"), "status": item.get("status")} for item in models],
        "endpoint_host": urlparse(str(text_binding_runtime.endpoint)).hostname if text_binding_runtime.endpoint else None,
        "endpoint_path": urlparse(str(text_binding_runtime.endpoint)).path if text_binding_runtime.endpoint else None,
        "image_endpoint_host": urlparse(str(image_binding_runtime.endpoint)).hostname if image_binding_runtime.endpoint else None,
        "image_endpoint_path": urlparse(str(image_binding_runtime.endpoint)).path if image_binding_runtime.endpoint else None,
        "image_model": image_model or image_binding_runtime.model,
        "evidence_gate": {"status": gate_validation.get("status", "not_validated"), "scope": scope_name, "submission_id": gate_validation.get("submission_id")},
        "resolved_models": models,
        "experiment_gateway_binding": {
            "text": text_binding_runtime.safe_record(),
            "image": image_binding_runtime.safe_record(),
        },
    }


def _fixed_rows(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [entry for entry in entries if entry.get("suite") == "fixed" and entry.get("family_id") and entry.get("branch_id")]


def _reliability_rows(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [entry for entry in entries if entry.get("suite") == "reliability" and entry.get("reliability_id") and entry.get("branch_id")]


def _integration_rows(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [entry for entry in entries if entry.get("suite") == "integration" and entry.get("scenario_id") and entry.get("branch_id")]


def _smoke_rows(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    declared = [entry for entry in entries if entry.get("suite") == "smoke" and entry.get("family_id") and entry.get("branch_id")]
    if declared:
        return declared + [entry for entry in entries if entry.get("suite") == "integration" and entry.get("scenario_id") in {"I02", "I03", "I07", "I08"}]
    families = {"A01", "A02", "B01", "B02", "C01", "D01"}
    rows = [entry for entry in _fixed_rows(entries) if entry.get("family_id") in families]
    rows.extend(entry for entry in entries if entry.get("suite") == "integration" and entry.get("scenario_id") in {"I02", "I03", "I07", "I08"})
    return rows


def _holdout_rows() -> list[dict[str, Any]]:
    return [{
        "entry_id": f"holdout-scenario-{index:02d}", "suite": "holdout", "scenario_id": f"holdout-{index:02d}",
        "branch_id": f"holdout-{index:02d}-blind", "meaning": "frozen holdout scenario; answer remains oracle-private",
        "repetitions_per_model": 3, "evidence_dir": "trajectories/holdout",
    } for index in range(1, 13)]


def _rows_for_suite(suite: str, entries: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, str]:
    if suite == "smoke":
        return _smoke_rows(entries), 3, "six families (all declared branches) plus I02/I03/I07/I08"
    if suite == "fixed":
        return _fixed_rows(entries), 5, "24 families x 3 concrete branches x 5 per model"
    if suite == "reliability":
        return _reliability_rows(entries), 5, "12 reliability cases x 5 per model"
    if suite == "integration":
        return _integration_rows(entries), 5, "12 integration trajectories x 5 per model"
    if suite == "holdout":
        declared = [entry for entry in entries if entry.get("suite") == "holdout" and entry.get("scenario_id") and entry.get("branch_id")]
        return (declared or _holdout_rows()), 3, "12 blind scenarios x 3 per model"
    if suite == "media":
        rows = [entry for entry in entries if entry.get("suite") == suite and entry.get("scenario_id") and entry.get("branch_id")]
        rows = rows or [{"entry_id": f"media-scenario-{index:02d}", "suite": suite, "scenario_id": f"media-{index:02d}", "branch_id": f"media-{index:02d}-available-unavailable", "meaning": "same intention with available and unavailable asset", "evidence_dir": "trajectories/media"} for index in range(1, 4)]
        return rows, 2, "3 scenarios x 2 asset conditions"
    if suite == "continuity":
        rows = [entry for entry in entries if entry.get("suite") == suite and entry.get("scenario_id") and entry.get("branch_id")]
        rows = rows or [{"entry_id": f"continuity-trajectory-{index:02d}", "suite": suite, "scenario_id": f"continuity-{index:02d}", "branch_id": f"continuity-{index:02d}-seven-virtual-days", "meaning": "seven virtual days with durable state and delivery continuity", "evidence_dir": "trajectories/continuity"} for index in range(1, 4)]
        return rows, 7, "3 independent trajectories x 7 virtual days"
    if suite == "performance":
        rows = [entry for entry in entries if entry.get("suite") == suite and entry.get("scenario_id") and entry.get("branch_id")]
        rows = rows or [{"entry_id": f"performance-arm-{arm}", "suite": suite, "scenario_id": f"performance-{arm}", "branch_id": f"performance-{arm}-30-samples", "meaning": f"30 samples for {arm} arm", "evidence_dir": "performance"} for arm in ("text", "tool", "image")]
        return rows, 30, "30 samples per text/tool/image arm"
    if suite == "prompt_pairing":
        rows = [entry for entry in entries if entry.get("suite") == suite and entry.get("entry_id")]
        return rows, 3, "P0/P1 x resident/retrievable background, 3 per cell"
    raise ValueError(f"unsupported suite: {suite}")


def _append_attempt(run_root: pathlib.Path, attempt: dict[str, Any]) -> None:
    path = run_root / "execution-state.json"
    state = _read(path, {"schemaVersion": "execution-state-v1", "attempts": []})
    state.setdefault("attempts", []).append({
        "attempt_id": attempt["attempt_id"], "suite": attempt["suite"], "status": attempt["status"],
        "execution": attempt["execution"], "provider_calls": attempt["provider_calls"], "denominator": attempt["denominator"], "result_path": attempt["result_path"], "recorded_at": attempt["recorded_at"],
    })
    state["status"] = "incomplete" if attempt["status"] not in {"passed", "completed"} else "passed"
    _write(path, state)


def _append_cost(run_root: pathlib.Path, attempt: dict[str, Any]) -> None:
    path = run_root / "cost-latency.json"
    value = _read(path, {"status": "not_started", "attempts": []})
    value.setdefault("attempts", []).append({
        "attempt_id": attempt["attempt_id"], "suite": attempt["suite"], "status": attempt["status"],
        "provider_calls": attempt["provider_calls"], "denominator": attempt["denominator"],
        "execution_mode": attempt.get("mode", "unknown"),
        "cost_status": "not_applicable_deterministic_control" if attempt.get("mode") == "deterministic_formal_control" else "not_priced",
        "latency_status": "not_measured", "recorded_at": attempt["recorded_at"],
    })
    if attempt.get("mode") == "deterministic_formal_control":
        value["status"] = "deterministic_controls_only" if all(item.get("execution_mode") == "deterministic_formal_control" for item in value["attempts"]) else "mixed"
    else:
        value["status"] = "blocked_before_provider" if attempt["provider_calls"] == 0 else "measured"
    _write(path, value)


def _safe_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)[:120] or "case"


def _record_path_evidence(run_root: pathlib.Path, result_path: pathlib.Path, rows: list[dict[str, Any]]) -> None:
    """Record observed path IDs only from actual trajectory results."""
    coverage_path = run_root / "path-coverage.json"
    coverage = _read(coverage_path, {"schemaVersion": "path-coverage-v2", "status": "not_run", "paths": {}})
    observed: dict[str, int] = {}
    for row in rows:
        for run in row.get("runs", []):
            for event_result in run.get("events", []):
                path_id = event_result.get("path_id") if isinstance(event_result, dict) else None
                if path_id in coverage.get("paths", {}):
                    observed[path_id] = observed.get(path_id, 0) + 1
    for path_id, count in observed.items():
        item = coverage["paths"][path_id]
        evidence = item.setdefault("evidence", [])
        ref = f"{result_path}#path={path_id}"
        if ref not in evidence:
            evidence.append(ref)
        item["status"] = "observed"
        item["observed_count"] = item.get("observed_count", 0) + count
    if observed:
        coverage["status"] = "observed_partial" if len(observed) < 18 else "observed_all"
    _write(coverage_path, coverage)


def _provider_models(models: list[dict[str, Any]], requested_model: str | None) -> list[dict[str, Any]]:
    if requested_model:
        return [item for item in models if item.get("label") == requested_model]
    return models


def _formal_runtime(
    run_root: pathlib.Path,
    trajectory: pathlib.Path,
    manifest: dict[str, Any],
    endpoint: str,
    model_label: str,
    owner: str,
    *,
    prompt_path_override: pathlib.Path | None = None,
    background_mode: str = "resident",
    image_endpoint: str | None = None,
    image_model: str | None = None,
    image_available: bool | None = None,
):
    """Construct one isolated formal runtime for any provider-backed suite."""
    from adapters.local import LocalAdapters
    from controller.boundary import NetworkBoundary
    from controller.provider_config import build_image_gateway, build_text_gateway, resolve_image_binding, resolve_text_binding
    from runtime.context import ContextBuilder
    from runtime.loop import AgencyLoop
    from runtime.policy import Policy
    from runtime.store import EventStore
    from transport.sink import RecordingSink

    text_binding = resolve_text_binding(provider=os.environ.get("IDEAL_LAB_PROVIDER_NAME") or "openai-compatible", endpoint=endpoint, model=model_label)
    if not text_binding.ready:
        raise ValueError("experiment text provider binding is incomplete")
    parsed = urlparse(str(text_binding.endpoint))
    network = NetworkBoundary({parsed.hostname or ""}, {parsed.path})
    store = EventStore(trajectory / "state.db")
    gateway = build_text_gateway(text_binding, network_boundary=network)
    trace_path = trajectory / "traces" / "trace.jsonl"
    image_gateway = None
    if image_endpoint and image_model:
        image_binding = resolve_image_binding(provider=os.environ.get("IDEAL_LAB_IMAGE_PROVIDER_NAME") or "openai-compatible", endpoint=image_endpoint, model=image_model)
        if not image_binding.ready:
            raise ValueError("experiment image provider binding is incomplete")
        image_parsed = urlparse(str(image_binding.endpoint))
        image_gateway = build_image_gateway(
            image_binding,
            network_boundary=NetworkBoundary({image_parsed.hostname or ""}, {image_parsed.path}),
            asset_root=trajectory / "assets",
            raw_root=trajectory / "traces" / "raw-responses",
        )
    loop = AgencyLoop(
        store=store,
        context=ContextBuilder(
            snapshot_root=run_root / "snapshot",
            prompt_path=prompt_path_override or pathlib.Path(manifest["prompt_path"]),
            manifest_path=run_root / "manifest.json",
            background_mode=background_mode,
        ),
        adapters=LocalAdapters(
            snapshot_root=run_root / "snapshot",
            manifest_path=run_root / "manifest.json",
            store=store,
            image_gateway=image_gateway,
            image_available=image_available,
        ),
        policy=Policy(store, writable_root=trajectory),
        gateway=gateway,
        sink=RecordingSink(trajectory / "traces" / "sink.jsonl"),
        trace_path=trace_path,
    )
    return store, loop, trace_path


def _execute_provider_rows(
    run_root: pathlib.Path,
    attempt_root: pathlib.Path,
    attempt_id: str,
    manifest: dict[str, Any],
    suite: str,
    entries: list[dict[str, Any]],
    repetitions: int,
    models: list[dict[str, Any]],
    endpoint: str,
    owner: str,
    *,
    min_events: int = 3,
    restart_after_event_numbers: set[int] | None = None,
    image_endpoint: str | None = None,
    image_model: str | None = None,
    image_available: bool | None = None,
) -> dict[str, Any]:
    """Run provider-backed suites through the same formal loop as E2.

    The same helper is also used by the virtual-time continuity runner.  It
    supports an explicit minimum trajectory length and controller restarts;
    neither option changes the input-only scenario or tells the model which
    semantic action to choose.
    """
    prompt_path = pathlib.Path(manifest["prompt_path"])
    manifest_path = run_root / "manifest.json"
    parsed = urlparse(endpoint)
    network_hosts = {parsed.hostname or ""}
    network_paths = {parsed.path}
    run_rows: list[dict[str, Any]] = []
    provider_calls = 0
    failures = 0
    missing_inputs = 0
    for entry in entries:
        scenario = entry.get("scenario") or {}
        scenario_events = scenario.get("events") or []
        if len(scenario_events) < min_events:
            missing_inputs += 1
            run_rows.append({"case_id": entry["entry_id"], "status": "incomplete", "reason": f"scenario must contain at least {min_events} input/controller events", "runs": []})
            continue
        case_runs = []
        case_image_available = entry.get("_image_available", image_available)
        case_prompt_path = pathlib.Path(entry["prompt_path"]) if entry.get("prompt_path") else None
        case_background_mode = str(entry.get("background_mode", "resident"))
        for model in models:
            model_label = model.get("label")
            if not model_label:
                failures += repetitions
                continue
            for repetition in range(1, repetitions + 1):
                trajectory = attempt_root / "trajectories" / _safe_component(entry["entry_id"]) / _safe_component(str(model.get("role", "model"))) / f"repeat-{repetition:02d}"
                trajectory.mkdir(parents=True, exist_ok=False)
                store, loop, trace_path = _formal_runtime(
                    run_root, trajectory, manifest, endpoint, model_label, owner,
                    prompt_path_override=case_prompt_path,
                    background_mode=case_background_mode,
                    image_endpoint=image_endpoint, image_model=image_model,
                    image_available=case_image_available,
                )
                # The v2 contract bounds cognition/tools per event.  The
                # durable store is scoped to this trajectory, so reserve the
                # per-event budget before the first event instead of allowing
                # event one to consume the entire multi-event trajectory.
                store.configure_budget(
                    owner,
                    max_model_calls=max(6, 6 * len(scenario_events)),
                    max_tool_rounds=max(4, 4 * len(scenario_events)),
                    max_infra_retries=max(2, 2 * len(scenario_events)),
                )
                event_results = []
                restart_count = 0
                started = time.perf_counter()
                elapsed_ms = 0
                try:
                    for event_index, spec in enumerate(scenario_events, 1):
                        if spec.get("virtual_time"):
                            virtual_time = str(spec["virtual_time"])
                        elif spec.get("virtual_day"):
                            virtual_time = (dt.datetime(2026, 9, 1, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=8))) + dt.timedelta(days=int(spec["virtual_day"]) - 1)).isoformat()
                        else:
                            virtual_time = f"2026-09-08T{9 + ((event_index - 1) % 10):02d}:00:00+08:00"
                        event = {
                            "event_id": f"{attempt_id}:{_safe_component(entry['entry_id'])}:{model.get('role')}:{repetition}:{event_index}",
                            "owner": owner, "kind": spec.get("kind", "user_message"),
                            "virtual_time": virtual_time,
                            "payload": spec.get("payload") or {"text": "scenario input missing", "origin": "scenario_catalog"},
                        }
                        event_results.append(loop.process_event(event))
                        if restart_after_event_numbers and event_index in restart_after_event_numbers and event_index < len(scenario_events):
                            store.close()
                            store, loop, trace_path = _formal_runtime(
                                run_root, trajectory, manifest, endpoint, model_label, owner,
                                prompt_path_override=case_prompt_path,
                                background_mode=case_background_mode,
                                image_endpoint=image_endpoint, image_model=image_model,
                                image_available=case_image_available,
                            )
                            restart_count += 1
                except Exception as exc:
                    event_results.append({"status": "runner_failure", "error": f"{type(exc).__name__}: {exc}"})
                finally:
                    elapsed_ms = int((time.perf_counter() - started) * 1000)
                    store.close()
                trace_count = 0
                latency_ms = 0
                if trace_path.exists():
                    for line in trace_path.read_text(encoding="utf-8").splitlines():
                        try:
                            trace_item = json.loads(line)
                            if trace_item.get("kind") == "provider_call":
                                trace_count += 1
                                latency_ms += int(trace_item.get("latency_ms") or 0)
                        except json.JSONDecodeError:
                            pass
                provider_calls += trace_count
                run_status = "passed" if event_results and all(item.get("status") in {"delivered", "waiting", "prepared", "observed", "duplicate"} for item in event_results) else "failed"
                if run_status == "failed":
                    failures += 1
                case_runs.append({"model": model_label, "model_role": model.get("role"), "repetition": repetition, "status": run_status, "events": event_results, "trajectory": str(trajectory), "provider_calls": trace_count, "latency_ms": latency_ms, "elapsed_ms": elapsed_ms, "controller_restarts": restart_count})
        case_status = "passed" if case_runs and all(item["status"] == "passed" for item in case_runs) else "failed"
        run_rows.append({"case_id": entry["entry_id"], "status": case_status, "runs": case_runs})
    return {"status": "completed_with_failures" if failures or missing_inputs else "completed", "provider_calls": provider_calls, "rows": run_rows, "failures": failures, "missing_inputs": missing_inputs}


def _single_special_model(models: list[dict[str, Any]], requested_model: str | None) -> list[dict[str, Any]]:
    """Use one declared model for suites whose denominator is not per-model."""
    candidates = _provider_models(models, requested_model)
    if requested_model:
        return candidates
    primary = next((item for item in candidates if item.get("role") == "primary" and item.get("label")), None)
    if primary:
        return [primary]
    first_declared = next((item for item in candidates if item.get("label")), None)
    return [first_declared] if first_declared else []


def _execute_continuity_rows(
    run_root: pathlib.Path,
    attempt_root: pathlib.Path,
    attempt_id: str,
    manifest: dict[str, Any],
    entries: list[dict[str, Any]],
    models: list[dict[str, Any]],
    endpoint: str,
    owner: str,
    requested_model: str | None,
) -> dict[str, Any]:
    """Run three cross-day trajectories, reopening the durable store mid-run."""
    selected = _single_special_model(models, requested_model)
    result = _execute_provider_rows(
        run_root,
        attempt_root,
        attempt_id,
        manifest,
        "continuity",
        entries,
        1,
        selected,
        endpoint,
        owner,
        min_events=3,
        restart_after_event_numbers={4, 8, 12},
    )
    result["virtual_days"] = 7
    result["logical_trajectories"] = len(entries)
    result["selected_model"] = selected[0].get("label") if selected else None
    return result


def _execute_media_rows(
    run_root: pathlib.Path,
    attempt_root: pathlib.Path,
    attempt_id: str,
    manifest: dict[str, Any],
    entries: list[dict[str, Any]],
    models: list[dict[str, Any]],
    endpoint: str,
    owner: str,
    requested_model: str | None,
    image_endpoint: str,
    image_model: str,
) -> dict[str, Any]:
    """Expand each media scenario into available and unavailable conditions."""
    selected = _single_special_model(models, requested_model)
    expanded: list[dict[str, Any]] = []
    for entry in entries:
        for condition, available in (("available", True), ("unavailable", False)):
            copy = deepcopy(entry)
            copy["entry_id"] = f"{entry['entry_id']}-{condition}"
            copy["branch_id"] = f"{entry.get('branch_id', entry['entry_id'])}-{condition}"
            copy["_image_available"] = available
            copy["scenario"] = deepcopy(entry.get("scenario") or {})
            for event in copy["scenario"].get("events", []):
                payload = dict(event.get("payload") or {})
                payload["media_condition"] = condition
                event["payload"] = payload
            expanded.append(copy)
    result = _execute_provider_rows(
        run_root,
        attempt_root,
        attempt_id,
        manifest,
        "media",
        expanded,
        1,
        selected,
        endpoint,
        owner,
        min_events=3,
        image_endpoint=image_endpoint,
        image_model=image_model,
    )
    result["asset_conditions"] = ["available", "unavailable"]
    result["scenario_count"] = len(entries)
    result["asset_case_count"] = len(expanded)
    result["selected_model"] = selected[0].get("label") if selected else None
    return result


def _execute_prompt_pairing_rows(
    run_root: pathlib.Path,
    attempt_root: pathlib.Path,
    attempt_id: str,
    manifest: dict[str, Any],
    entries: list[dict[str, Any]],
    models: list[dict[str, Any]],
    endpoint: str,
    owner: str,
    requested_model: str | None,
) -> dict[str, Any]:
    """Execute P0/P1 x resident/retrievable cells with one frozen model."""
    selected = _single_special_model(models, requested_model)
    result = _execute_provider_rows(
        run_root,
        attempt_root,
        attempt_id,
        manifest,
        "prompt_pairing",
        entries,
        3,
        selected,
        endpoint,
        owner,
        min_events=3,
    )
    result["cells"] = len(entries)
    result["repetitions_per_cell"] = 3
    result["selected_model"] = selected[0].get("label") if selected else None
    return result


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _execute_performance_rows(
    run_root: pathlib.Path,
    attempt_root: pathlib.Path,
    attempt_id: str,
    manifest: dict[str, Any],
    entries: list[dict[str, Any]],
    models: list[dict[str, Any]],
    endpoint: str,
    owner: str,
    requested_model: str | None,
    image_endpoint: str | None,
    image_model: str | None,
) -> dict[str, Any]:
    """Run the 30-sample text/tool/image arms and calculate p95 from traces."""
    selected = _single_special_model(models, requested_model)
    result = _execute_provider_rows(
        run_root,
        attempt_root,
        attempt_id,
        manifest,
        "performance",
        entries,
        30,
        selected,
        endpoint,
        owner,
        min_events=1,
        image_endpoint=image_endpoint,
        image_model=image_model,
    )
    limits = {"text": 15.0, "tool": 60.0, "image": 180.0}
    failures = int(result.get("failures", 0))
    for row in result.get("rows", []):
        arm = str(row.get("scenario_id", "")).removeprefix("performance-")
        samples = [item for run in row.get("runs", []) for item in [run.get("elapsed_ms")] if isinstance(item, (int, float))]
        p95_ms = _percentile([float(item) for item in samples], 0.95)
        row["performance"] = {
            "arm": arm,
            "sample_count": len(samples),
            "p95_ms": p95_ms,
            "p95_seconds": (p95_ms / 1000.0) if p95_ms is not None else None,
            "limit_seconds": limits.get(arm),
            "status": "passed" if len(samples) >= 30 and p95_ms is not None and p95_ms <= limits.get(arm, float("inf")) * 1000 else "incomplete",
        }
        if row["performance"]["status"] != "passed":
            failures += 1
    result["failures"] = failures
    result["status"] = "completed" if failures == 0 and len(result.get("rows", [])) == len(entries) else "completed_with_failures"
    result["selected_model"] = selected[0].get("label") if selected else None
    return result


def run_suite(run_root: pathlib.Path, args: Any) -> dict[str, Any]:
    suite = args.suite
    if suite not in SUITES:
        raise ValueError(f"unsupported suite: {suite}")
    manifest = _read(run_root / "manifest.json", {})
    execution_manifest = _read(run_root / "execution-manifest.json", {})
    source_entries = execution_manifest.get("prompt_variants", []) if suite == "prompt_pairing" else execution_manifest.get("entries", [])
    entries, repetitions, denominator_rule = _rows_for_suite(suite, source_entries)
    models = _models({"models": execution_manifest.get("models", manifest.get("models", []))})
    requested_model = getattr(args, "model", None)
    endpoint = getattr(args, "endpoint", None)
    image_endpoint = getattr(args, "image_endpoint", None)
    image_model = getattr(args, "image_model", None)
    from controller.provider_config import resolve_image_binding, resolve_text_binding
    text_process_binding = resolve_text_binding(endpoint=endpoint, model=requested_model)
    endpoint = endpoint or text_process_binding.endpoint
    image_process_binding = resolve_image_binding(endpoint=image_endpoint, model=image_model)
    image_endpoint = image_endpoint or image_process_binding.endpoint
    image_model = image_model or image_process_binding.model
    gate = _gate(run_root, {**manifest, "models": models}, requested_model, endpoint, suite, image_endpoint, image_model)
    if any(item.get("label") for item in gate.get("resolved_models", [])):
        models = _models({"models": gate["resolved_models"]})
    if suite != "prompt_pairing" and getattr(args, "prompt", "P1") != "P1":
        gate["status"] = "blocked"
        gate["reasons"].append("formal C06 main suite is frozen to P1; P0 is a separate baseline run")
    if suite == "continuity" and getattr(args, "days", None) not in (None, 7):
        gate["status"] = "blocked"
        gate["reasons"].append("continuity requires exactly 7 virtual days")
    if suite == "continuity" and getattr(args, "repeats", None) not in (None, 3):
        gate["status"] = "blocked"
        gate["reasons"].append("continuity requires exactly 3 independent trajectories")
    attempt_id = f"{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:10]}"
    attempt_root = run_root / "suite-attempts" / attempt_id
    attempt_root.mkdir(parents=True, exist_ok=False)
    models_for_run = _provider_models(models, requested_model)
    if suite in {"media", "continuity", "performance", "prompt_pairing"}:
        models_for_run = _single_special_model(models, requested_model)
        model_count = 1
    else:
        model_count = len(models_for_run) if requested_model else len(models)
    total = len(entries) * repetitions if suite in {"media", "continuity", "performance", "prompt_pairing"} else len(entries) * repetitions * model_count
    reason = "; ".join(gate["reasons"]) if gate["reasons"] else ""
    status = "incomplete" if gate["status"] != "passed" else "incomplete"
    execution_status = "not_started"
    provider_calls = 0
    rows = []
    for entry in entries:
        rows.append({
            "case_id": entry["entry_id"], "suite": suite, "family_id": entry.get("family_id"),
            "scenario_id": entry.get("scenario_id"), "branch_id": entry.get("branch_id"), "meaning": entry.get("meaning"),
            "repetitions": repetitions,
            "models": [{"role": model.get("role"), "label": model.get("label"), "status": model.get("status")} for model in models] if suite not in {"media", "continuity", "performance"} else [],
            "status": status, "provider_calls": 0, "reason": reason,
            "evidence_dir": str(run_root / entry.get("evidence_dir", f"trajectories/{suite}")),
        })
    if gate["status"] == "passed" and suite in PROVIDER_SUITES:
        owner_keys = ((manifest.get("snapshot_binding") or {}).get("owner_keys") or [])
        if not owner_keys:
            reason = "frozen manifest has no owner binding"
        else:
            if suite == "media":
                provider_result = _execute_media_rows(run_root, attempt_root, attempt_id, manifest, entries, models, endpoint, owner_keys[0], requested_model, image_endpoint, image_model)
            elif suite == "continuity":
                provider_result = _execute_continuity_rows(run_root, attempt_root, attempt_id, manifest, entries, models, endpoint, owner_keys[0], requested_model)
            elif suite == "performance":
                provider_result = _execute_performance_rows(run_root, attempt_root, attempt_id, manifest, entries, models, endpoint, owner_keys[0], requested_model, image_endpoint, image_model)
            elif suite == "prompt_pairing":
                provider_result = _execute_prompt_pairing_rows(run_root, attempt_root, attempt_id, manifest, entries, models, endpoint, owner_keys[0], requested_model)
            else:
                provider_result = _execute_provider_rows(run_root, attempt_root, attempt_id, manifest, suite, entries, repetitions, models_for_run, endpoint, owner_keys[0])
            status = provider_result["status"]
            execution_status = "completed"
            provider_calls = provider_result["provider_calls"]
            rows = provider_result["rows"]
            reason = "provider matrix completed" if status == "completed" else "provider matrix completed with one or more failed trajectories"
            _record_path_evidence(run_root, attempt_root / "result.json", rows)
            from evaluation.context_consumption import merge_provider_evidence as merge_context_evidence
            merge_context_evidence(run_root, [attempt_root])
            if suite == "integration":
                from evaluation.state_roundtrip import merge_provider_evidence as merge_state_evidence
                merge_state_evidence(run_root, [attempt_root])
            if suite == "smoke":
                environment = _read(run_root / "environment.json", {})
                environment["e3"] = "completed" if status == "completed" else "failed"
                _write(run_root / "environment.json", environment)
    elif gate["status"] == "passed" and suite == "reliability":
        owner_keys = ((manifest.get("snapshot_binding") or {}).get("owner_keys") or [])
        if not owner_keys:
            status = "incomplete"
            reason = "frozen manifest has no owner binding"
        else:
            from evaluation.reliability import run_reliability_controls
            reliability_result = run_reliability_controls(run_root, attempt_root, entries, models_for_run, owner_keys[0])
            status = reliability_result["status"]
            execution_status = reliability_result["execution"]
            provider_calls = reliability_result["provider_calls"]
            rows = reliability_result["rows"]
            reason = "formal deterministic reliability controls completed" if status == "completed" else "reliability controls completed with failures"
    else:
        provider_result = {"status": status, "provider_calls": 0, "rows": rows}
        provider_calls = 0
        if not reason:
            reason = "specialized suite adapter is not available in this local run"
    attempt = {
        "schemaVersion": "suite-attempt-v1", "attempt_id": attempt_id, "run": run_root.name, "suite": suite, "recorded_at": _now(),
        "manifest_hash": _short_hash(manifest), "execution_manifest_hash": _short_hash(execution_manifest), "gate": gate,
        "status": status, "execution": execution_status, "mode": "deterministic_formal_control" if suite == "reliability" else "provider_matrix", "provider_calls": provider_calls,
        "denominator": {"case_count": len(entries), "repetitions": repetitions, "model_count": model_count, "total_trajectories_or_samples": total, "rule": denominator_rule},
        "execution_parameters": {
            "actual_repetitions": 1 if suite in {"media", "continuity"} else (30 if suite == "performance" else repetitions),
            "selected_model": models_for_run[0].get("label") if suite in {"media", "continuity", "performance", "prompt_pairing"} and models_for_run else None,
            "virtual_days": 7 if suite == "continuity" else None,
            "min_events": 1 if suite == "performance" else 3,
        },
        "rows": rows, "raw_evidence": [str(attempt_root / "trajectories")] if provider_calls else [], "reason": reason, "result_path": str(attempt_root / "result.json"),
    }
    _write(attempt_root / "suite-attempt.json", attempt)
    _write(attempt_root / "result.json", attempt)
    _append_attempt(run_root, attempt)
    _append_cost(run_root, attempt)
    _write(run_root / "suite-results" / f"{suite}-latest.json", {"schemaVersion": "suite-latest-v1", "suite": suite, "attempt_id": attempt_id, "status": status, "result": str(attempt_root / "result.json"), "denominator": attempt["denominator"], "gate": gate, "updated_at": attempt["recorded_at"]})
    _write(run_root / "suite-results" / f"{suite}-{attempt_id}.json", attempt)

    requirement_map = _read(run_root / "requirement-map.json", {})
    requirement_map.setdefault("work_items", {}).setdefault("C06", {}).update({
        "status": "incomplete" if status != "passed" else "not_started",
        "evidence": [str(attempt_root / "result.json"), str(run_root / "execution-state.json")],
        "next": "provide verified C00/E0/E1/provider/model gates, then rerun the same suite command",
    })
    _write(run_root / "requirement-map.json", requirement_map)
    checkpoint = _read(run_root / "checkpoint.json", {})
    checkpoint["next"] = {"command": f"python {run_root.parent.parent / 'v2' / 'cli.py'} run --suite {suite} --run {run_root}", "reason": reason or "suite is ready for provider adapter"}
    checkpoint["blocked"] = gate["reasons"]
    _write(run_root / "checkpoint.json", checkpoint)
    return {"status": status, "suite": suite, "attempt_id": attempt_id, "execution": attempt["execution"], "provider_calls": provider_calls, "denominator": attempt["denominator"], "gate": gate, "result": str(attempt_root / "result.json"), "reason": reason}
