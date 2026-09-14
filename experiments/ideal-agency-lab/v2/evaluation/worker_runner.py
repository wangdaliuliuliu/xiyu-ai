"""Run the existing J05 trajectory executor inside the qualified WSL worker.

The controller owns staging, the relay process and the network rule.  This
module is the worker-side entry used by ``cli.py worker-run``.  It intentionally
accepts a sanitized case manifest: evaluator response rules and assertions are
not part of the worker input.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import tarfile
import tempfile
import time
from copy import deepcopy
from typing import Any

from controller.provider_config import ProviderBinding, resolve_production_text_binding
from controller.worker_gateway import DEEPSEEK_PRICE_BASIS_URL, RelayGateway, RelayProcess, start_relay
from evaluation.j05_simulation import ARMS, OWNER, RECORDS_REL, _aggregate_j05, _read_json, _write_json, execute_j05_trajectory


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _path_probe(path: pathlib.Path, operation: str) -> dict[str, Any]:
    try:
        if operation == "read":
            path.read_bytes()
        else:
            path.write_bytes(b"worker-boundary-probe")
            path.unlink(missing_ok=True)
    except (OSError, PermissionError) as exc:
        return {"status": "passed", "operation": operation, "path": str(path), "observed": "blocked", "error_type": type(exc).__name__}
    return {"status": "failed", "operation": operation, "path": str(path), "observed": "allowed"}


def _write_real_cost_artifact(run_root: pathlib.Path, *, max_budget_cny: float | None, cny_per_usd_ceiling: float, max_output_tokens: int | None) -> dict[str, Any]:
    """Reconcile usage, reservations and billing status without exposing credentials.

    A provider response with complete usage is an actual usage estimate at the
    verified price.  A response without complete usage is never promoted to
    actual spend: its controller reservation remains an unresolved reserve.
    This function also understands the pre-v37 relay log, whose rows did not
    carry ``provider_call`` and whose cost field treated every reservation as
    charged.  That compatibility path is intentionally marked legacy rather
    than silently accepting the old accounting semantics.
    """
    log_path = run_root / "worker-gateway-relay.jsonl"
    rows = []
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    legacy_rows = [row for row in rows if "provider_call" not in row]
    provider_rows = [row for row in rows if row.get("provider_call") is True or ("provider_call" not in row and row.get("provider_request_id"))]
    budget_rows = [row for row in rows if row.get("provider_call") is False or row.get("error") == "cost_budget_exhausted"]
    usage_totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 0}

    def usage_cost(usage: Any) -> tuple[float, dict[str, int]] | None:
        if not isinstance(usage, dict):
            return None
        try:
            prompt = int(usage["prompt_tokens"])
            completion = int(usage["completion_tokens"])
            total = int(usage["total_tokens"])
            hit = usage.get("prompt_cache_hit_tokens")
            if hit is None and isinstance(usage.get("prompt_tokens_details"), dict):
                hit = usage["prompt_tokens_details"].get("cached_tokens")
            miss = usage.get("prompt_cache_miss_tokens")
            hit = int(hit)
            miss = int(miss)
        except (KeyError, TypeError, ValueError):
            return None
        if min(prompt, completion, total, hit, miss) < 0 or prompt + completion != total or hit + miss != prompt:
            return None
        values = {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total, "prompt_cache_hit_tokens": hit, "prompt_cache_miss_tokens": miss}
        cost = (hit * 0.014 + miss * 0.44 + completion * 1.32) / 1_000_000
        return cost, values

    complete_usage_rows: list[tuple[dict[str, Any], float, dict[str, int]]] = []
    unknown_usage_rows: list[dict[str, Any]] = []
    for row in provider_rows:
        settled = usage_cost(row.get("usage")) if row.get("http_status") == 200 else None
        if settled is None:
            unknown_usage_rows.append(row)
            continue
        cost, values = settled
        complete_usage_rows.append((row, cost, values))
        for key, value in values.items():
            usage_totals[key] += value
    actual_usage_usd = sum(item[1] for item in complete_usage_rows)
    reservation_offered_usd = sum(float((row.get("cost") or {}).get("reserved_usd", 0) or 0) for row in provider_rows)
    released_reserved_usd = sum(max(0.0, float((row.get("cost") or {}).get("reserved_usd", 0) or 0) - cost) for row, cost, _values in complete_usage_rows)
    unresolved_reserved_usd = sum(float((row.get("cost") or {}).get("reserved_usd", 0) or 0) for row in unknown_usage_rows)
    statuses = [row.get("http_status") for row in provider_rows]
    guard_enabled = max_budget_cny is not None or any(isinstance(row.get("budget"), dict) for row in rows)
    if budget_rows:
        status = "stopped_at_user_budget_guard"
    elif 402 in statuses:
        status = "provider_http_402_after_partial_success"
    else:
        status = "completed_under_budget"
    if not guard_enabled:
        unresolved_reserve_status = "not_recorded_for_legacy_run" if unknown_usage_rows else "not_applicable"
        unresolved_reserved_value: float | None = None
    else:
        unresolved_reserve_status = "pending_unknown_usage" if unresolved_reserved_usd else "none_after_usage_settlement"
        unresolved_reserved_value = unresolved_reserved_usd
    remaining_headroom_usd = None
    if max_budget_cny is not None:
        remaining_headroom_usd = max(0.0, float(max_budget_cny) / max(0.01, cny_per_usd_ceiling) - actual_usage_usd - (unresolved_reserved_value or 0.0))
    result = {
        "schemaVersion": "real-api-cost-latency-v3",
        "status": status,
        "scope": "real_j05_worker_only",
        "budget_authorization": {"max_budget_cny": max_budget_cny, "cny_per_usd_safety_ceiling": cny_per_usd_ceiling, "max_output_tokens": max_output_tokens, "user_authorized_scope": "this real API continuation only" if max_budget_cny is not None else "legacy_run_budget_not_recorded"},
        "price_basis": {"url": DEEPSEEK_PRICE_BASIS_URL, "rate_class": "peak_conservative", "currency_at_provider": "USD", "input_cache_hit_usd_per_million": 0.014, "input_cache_miss_usd_per_million": 0.44, "output_usd_per_million": 1.32},
        "requests": {"relay_attempts": len(rows), "provider_calls": len(provider_rows), "budget_rejections": len(budget_rows), "provider_http_200": sum(status == 200 for status in statuses), "provider_http_402": sum(status == 402 for status in statuses), "responses_with_complete_usage": len(complete_usage_rows), "provider_calls_with_unknown_usage": len(unknown_usage_rows)},
        "actual_usage_estimate": {"status": "complete" if not unknown_usage_rows else "partial", "usage": usage_totals, "estimated_usd": actual_usage_usd, "estimated_cny_at_safety_rate": actual_usage_usd * cny_per_usd_ceiling, "basis": "complete HTTP 200 usage only"},
        "reservation_reconciliation": {"guard_enabled_or_observed": guard_enabled, "reservation_offered_usd": reservation_offered_usd, "released_excess_reserved_usd": released_reserved_usd, "released_excess_reserved_cny_at_safety_rate": released_reserved_usd * cny_per_usd_ceiling, "unresolved_reserved_usd": unresolved_reserved_value, "unresolved_reserved_cny_at_safety_rate": unresolved_reserved_value * cny_per_usd_ceiling if unresolved_reserved_value is not None else None, "unresolved_status": unresolved_reserve_status, "remaining_authorized_headroom_usd": remaining_headroom_usd, "remaining_authorized_headroom_cny_at_safety_rate": remaining_headroom_usd * cny_per_usd_ceiling if remaining_headroom_usd is not None else None},
        "account_billing": {"status": "unknown_not_returned_by_provider", "amount": None, "currency": None, "not_invented": True},
        "legacy_compatibility": {"legacy_rows_without_provider_call_field": len(legacy_rows), "old_charged_field_is_not_used_as_actual_spend": True},
        "guard_evidence": {"log": str(log_path), "budget_stop_is_not_a_provider_call": True, "no_retry_after_budget_stop": True},
    }
    _write_json(run_root / "real-j05-cost-latency.json", result)
    return result


def _network_probe() -> dict[str, Any]:
    started = time.perf_counter()
    try:
        connection = socket.create_connection(("1.1.1.1", 443), timeout=3)
        connection.close()
    except OSError as exc:
        return {"status": "passed", "observed": "blocked", "target": "1.1.1.1:443", "error_type": type(exc).__name__, "elapsed_ms": int((time.perf_counter() - started) * 1000)}
    return {"status": "failed", "observed": "allowed", "target": "1.1.1.1:443", "elapsed_ms": int((time.perf_counter() - started) * 1000)}


def _snapshot_completeness(source: pathlib.Path, output_root: pathlib.Path) -> dict[str, Any]:
    expected = {str(item.relative_to(source)) for item in source.rglob("*") if item.is_file()}
    # K06 materializes this controller-declared paired condition inside the
    # isolated snapshot.  It is evidence of an executed intervention, not an
    # unregistered snapshot leak.  All other extra files remain failures.
    allowed_fixture_files = {"media-condition.json"}
    rows = []
    for isolated in output_root.rglob("isolated-snapshot"):
        actual = {str(item.relative_to(isolated)) for item in isolated.rglob("*") if item.is_file()}
        allowed = actual & allowed_fixture_files
        unexpected = actual - expected - allowed
        rows.append({"trajectory": str(isolated.parent), "expected_file_count": len(expected), "actual_file_count": len(actual), "missing": sorted(expected - actual), "unexpected": sorted(unexpected), "allowed_fixture_files": sorted(allowed)})
    return {"expected_file_count": len(expected), "allowed_fixture_files": sorted(allowed_fixture_files), "trajectory_count": len(rows), "all_complete": bool(rows) and all(not row["missing"] and not row["unexpected"] and row["actual_file_count"] == len(expected) + len(row["allowed_fixture_files"]) for row in rows), "trajectories": rows}


def _sanitized_case(case: dict[str, Any]) -> dict[str, Any]:
    """Keep scheduling/fixture inputs while excluding evaluator oracle fields."""
    value = deepcopy(case)
    for key in ("response_rules", "assertions", "deviations", "expected_behavior", "scoring"):
        value.pop(key, None)
    return value


def run_worker_from_config(config_path: pathlib.Path) -> dict[str, Any]:
    config = _read_json(config_path, {})
    input_root = pathlib.Path(str(config["input_root"])).resolve()
    stage_root = pathlib.Path(str(config["run_root"])).resolve()
    output_root = pathlib.Path(str(config["output_root"])).resolve()
    relay = RelayGateway(base_url=str(config["relay_url"]), token=str(config["relay_token"]), model_name=str(config["model"]))
    # The provider credential is never accepted in the worker config or env.
    credential_env_hits = [key for key in os.environ if key.startswith(("DEEPSEEK", "OPENAI", "IDEAL_LAB")) and ("API_KEY" in key or "TOKEN" in key)]
    path_probes = [
        _path_probe(pathlib.Path("/mnt/e/FoxSpirit/xiyu-ai/src/proactive.mjs"), "read"),
        _path_probe(pathlib.Path("/mnt/e/FoxSpirit/xiyu-ai/worker-write-probe.txt"), "write"),
        _path_probe(input_root / "oracle" / "hidden-evaluator.json", "read"),
    ]
    snapshot_context = stage_root / "snapshot" / "context.json"
    snapshot_read = {"status": "passed", "path": str(snapshot_context)} if snapshot_context.exists() and snapshot_context.read_bytes() else {"status": "failed", "path": str(snapshot_context)}
    network_probe = _network_probe()
    manifest = _read_json(stage_root / "case-manifest.json", {})
    cases = [_sanitized_case(item) for item in manifest.get("cases", [])]
    case_by_id = {item.get("case_id"): item for item in cases}
    selected_case_ids = config.get("selected_case_ids")
    if selected_case_ids:
        missing_case_ids = [case_id for case_id in selected_case_ids if case_id not in case_by_id]
        if missing_case_ids:
            raise ValueError(f"selected J05 case ids are not in the frozen manifest: {missing_case_ids}")
        cases = [case_by_id[case_id] for case_id in selected_case_ids]
    if config.get("probe_only"):
        cases = [case_by_id["K01"]]
        # Exercise the actual concerns prompt path during qualification.  The
        # previous A-only probe could pass while the B/C prompt path pointed
        # outside the staged worker and silently fell back to "missing".
        work_items = [("C", "K01", 1)]
    elif config.get("trajectory_order"):
        work_items = [(str(item["arm"]), str(item["case_id"]), int(item.get("repetition", 1))) for item in config["trajectory_order"]]
    else:
        cells = [(arm, repetition) for arm in ARMS for repetition in range(1, 4)]
        work_items = [(arm, case["case_id"], repetition) for arm, repetition in cells for case in cases]
    prompt_paths = {
        "A": pathlib.Path(str(config["prompt_paths"]["A"])),
        "B": pathlib.Path(str(config["prompt_paths"]["B"])),
        "C": pathlib.Path(str(config["prompt_paths"]["C"])),
    }
    selected_cases = {case["case_id"]: case for case in cases}
    planned_trajectories = int(config.get("planned_trajectories") or len(work_items) or 108)
    results: list[dict[str, Any]] = []
    scheduling_stop: dict[str, Any] = {"stopped": False}
    for arm, case_id, repetition in work_items:
        case = selected_cases[case_id]
        # The worker uses the same executor and event scheduler as fake/real;
        # only the gateway adapter differs.
        execution_mode = "control" if config.get("scripted_relay") else "real"
        result = execute_j05_trajectory(stage_root, output_root, case, arm, repetition, prompt_paths[arm], lambda _a, _c, _s: relay, execution_mode)
        results.append(result)
        if result.get("budget_stop"):
            scheduling_stop = {"stopped": True, "reason": "cost_budget_exhausted", "at": {"arm": arm, "case_id": case_id, "repetition": repetition, "event_index": result.get("budget_stop_event")}, "unscheduled_after_stop": planned_trajectories - len(results)}
            break
    execution_mode = "control" if config.get("scripted_relay") else "real"
    aggregate = _aggregate_j05(stage_root, results, provider_mode=execution_mode, output_root=output_root, sample_gate=str(config.get("sample_gate", "passed")), planned_trajectories=planned_trajectories, scheduling_stop=scheduling_stop)
    aggregate["execution_scope"] = config.get("execution_scope", "full_j05")
    aggregate["full_suite_planned_trajectories"] = 108
    snapshot_completeness = _snapshot_completeness(stage_root / "snapshot", output_root)
    actual_prompts = list(output_root.glob("**/actual-prompts.jsonl"))
    prompt_leaks = []
    prompt_binding_errors = []
    for prompt_file in actual_prompts:
        for line in prompt_file.read_text(encoding="utf-8").splitlines():
            if any(token in line for token in ("response_rules", "assertions", "acceptance requirement", "controlled_overlay")):
                prompt_leaks.append(str(prompt_file))
            try:
                prompt_row = json.loads(line)
            except json.JSONDecodeError:
                prompt_binding_errors.append({"file": str(prompt_file), "reason": "invalid_prompt_log_json"})
                continue
            arm = prompt_file.parents[2].name if len(prompt_file.parents) >= 3 else None
            observed_version = (((prompt_row.get("prompt") or {}).get("system") or {}).get("prompt_version"))
            expected_version = "agency-concerns-v1.0" if arm in {"B", "C"} else "ideal-agency-lab-p1.0"
            if observed_version != expected_version:
                prompt_binding_errors.append({
                    "file": str(prompt_file),
                    "arm": arm,
                    "expected": expected_version,
                    "observed": observed_version,
                })
    state_write = output_root.exists() and any(output_root.glob("**/state.db"))
    relay_calls = len(relay.calls)
    proof = {
        "schemaVersion": "worker-execution-v2",
        "status": "passed" if all(item.get("status") == "passed" for item in path_probes) and snapshot_read["status"] == "passed" and network_probe["status"] == "passed" and state_write and relay_calls > 0 and not credential_env_hits and not prompt_leaks and not prompt_binding_errors else "failed",
        "qualification": "os_qualified" if all(item.get("status") == "passed" for item in path_probes) and network_probe["status"] == "passed" else "not_os_qualified",
        "execution_function": "execute_j05_trajectory",
        "same_executor_claim": True,
        "worker_kind": "wsl2",
        "worker_id": f"debian:j05worker:{os.getpid()}",
        "worker_process": {"pid": os.getpid(), "runtime": "wsl2-ext4-user", "user": os.environ.get("USER") or os.environ.get("LOGNAME") or "unknown", "kernel": os.uname().release},
        "gateway": {"controller_gateway_process": True, "credential_scope": "gateway_only", "worker_receives_credential": False, "relay_calls": relay_calls, "relay_model": relay.model_name},
        "network_policy": {"per_worker_allowlist": True, "direct_external_probe": network_probe, "relay_endpoint": str(config.get("relay_url"))},
        "path_policy": {"production_read_denied": path_probes[0]["status"] == "passed", "production_write_denied": path_probes[1]["status"] == "passed", "oracle_read_denied": path_probes[2]["status"] == "passed", "snapshot_read": snapshot_read, "state_write": state_write},
        "oracle_policy": {"oracle_read_denied": path_probes[2]["status"] == "passed", "sanitized_case_manifest": True, "prompt_leaks": prompt_leaks},
        "prompt_binding": {"status": "passed" if not prompt_binding_errors else "failed", "errors": prompt_binding_errors},
        "trajectory_binding": {"run_id": config["run_id"], "code_hash": config.get("code_hash"), "execution_scope": "worker_control_probe" if config.get("probe_only") else "real_j05"},
        "provider_mode": "real" if not config.get("scripted_relay") else "controller_relay_control_probe",
        "trajectory_count": len(results),
        "aggregate_status": aggregate.get("status"),
        "snapshot_completeness": snapshot_completeness,
        "credential_env_hits": credential_env_hits,
        "evidence": {"output_root": str(output_root), "relay_calls": relay_calls, "path_probes": path_probes, "network_probe": network_probe},
    }
    _write_json(stage_root / "worker-execution.json", proof)
    _write_json(stage_root / "worker-control-result.json", {"aggregate": aggregate, "proof": proof})
    return {"status": proof["status"], "aggregate": aggregate, "proof": proof}


def _wsl(*args: str, input_text: str | None = None, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    safe_env = _safe_wsl_env()
    result = subprocess.run(["wsl.exe", *args], input=input_text.replace("\r\n", "\n").encode("utf-8") if input_text is not None else None, text=False, capture_output=True, timeout=timeout, check=False, env=safe_env)
    return subprocess.CompletedProcess(result.args, result.returncode, result.stdout.decode("utf-8", "replace"), result.stderr.decode("utf-8", "replace"))


def _safe_wsl_env() -> dict[str, str]:
    safe_env = {key: value for key, value in os.environ.items() if not (key.startswith(("DEEPSEEK", "OPENAI", "IDEAL_LAB")) and ("API_KEY" in key or "TOKEN" in key))}
    safe_env["PATH"] = ""
    safe_env["WSLENV"] = ""
    return safe_env


def _wsl_binary(*args: str, timeout: int = 120) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["wsl.exe", *args], capture_output=True, timeout=timeout, check=False, env=_safe_wsl_env())


def _wsl_gateway_ip() -> str:
    result = _wsl("--distribution", "Debian", "--", "ip", "route", "show", "default")
    match = re.search(r"default via\s+(\d+(?:\.\d+){3})", result.stdout)
    if result.returncode != 0 or not match:
        raise RuntimeError(f"WSL default gateway was not observable: {result.stderr.strip() or result.stdout.strip()}")
    return match.group(1)


def _ensure_worker_user() -> int:
    result = _wsl("--distribution", "Debian", "--", "id", "-u", "j05worker")
    if result.returncode != 0:
        create = _wsl("--distribution", "Debian", "--", "useradd", "--create-home", "--shell", "/bin/bash", "j05worker")
        if create.returncode != 0:
            raise RuntimeError(f"could not create WSL worker user: {create.stderr.strip() or create.stdout.strip()}")
        result = _wsl("--distribution", "Debian", "--", "id", "-u", "j05worker")
    try:
        return int(result.stdout.strip())
    except ValueError as exc:
        raise RuntimeError("WSL worker uid was not numeric") from exc


def _assert_wsl2_and_no_automount() -> dict[str, Any]:
    version = _wsl("--distribution", "Debian", "--", "uname", "-r")
    config = _wsl("--distribution", "Debian", "--", "cat", "/etc/wsl.conf")
    automount_disabled = bool(re.search(r"(?ms)^\s*\[automount\]\s*$.*?^\s*enabled\s*=\s*false\s*$", config.stdout))
    version_ok = "microsoft-standard-WSL2" in version.stdout
    if not version_ok or not automount_disabled:
        raise RuntimeError("WSL worker is not qualified: require WSL2 and /etc/wsl.conf [automount] enabled=false")
    mount_probe = _wsl("--distribution", "Debian", "--", "test", "!", "-e", "/mnt/e/FoxSpirit/xiyu-ai")
    if mount_probe.returncode != 0:
        raise RuntimeError("WSL worker still sees the production drive; automount isolation is not active")
    return {"runtime": version.stdout.strip(), "automount_disabled": True, "production_mount_absent": True}


def _worker_manifest(run_root: pathlib.Path) -> dict[str, Any]:
    source = json.loads((run_root / "case-manifest.json").read_text(encoding="utf-8"))
    cases = [_sanitized_case(item) for item in source.get("cases", [])]
    return {"schemaVersion": source.get("schemaVersion"), "total_trajectories": source.get("total_trajectories"), "cases": cases}


def _copytree_verified(source: pathlib.Path, destination: pathlib.Path) -> None:
    """Copy a snapshot and repair/verify transient UNC copy omissions.

    WSL's ``\\wsl$`` provider can occasionally return a successful tree copy
    while omitting a file that is still visible in the source tree.  Snapshot
    completeness is part of the worker boundary, so silently accepting that
    state would make the worker's input differ from the frozen run.  Repair
    missing or size-mismatched files and fail closed if the content still does
    not match.
    """
    def digest(path: pathlib.Path) -> str:
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    destination.mkdir(parents=True, exist_ok=False)
    for source_dir in (source, *[item for item in source.rglob("*") if item.is_dir()]):
        (destination / source_dir.relative_to(source)).mkdir(parents=True, exist_ok=True)
    source_files = [item for item in source.rglob("*") if item.is_file()]
    for source_file in source_files:
        if not source_file.is_file():
            continue
        target_file = destination / source_file.relative_to(source)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        last_error: OSError | None = None
        for _attempt in range(3):
            try:
                if not target_file.exists() or digest(target_file) != digest(source_file):
                    shutil.copy2(source_file, target_file)
                last_error = None
                break
            except (FileNotFoundError, PermissionError) as exc:
                # The WSL UNC provider can briefly lose a just-created file;
                # retry the individual copy before treating it as corruption.
                last_error = exc
                time.sleep(0.1)
        if last_error is not None:
            raise RuntimeError(f"worker snapshot copy failed after retries: {source_file}: {last_error}") from last_error
        if not target_file.exists() or digest(target_file) != digest(source_file):
            raise RuntimeError(f"worker snapshot copy verification failed: {source_file}")


def _copy_file_controller(source: pathlib.Path, destination: pathlib.Path) -> None:
    """Copy one controller-owned file, including Windows MAX_PATH fallback."""
    try:
        shutil.copy2(source, destination)
        return
    except FileNotFoundError as first_error:
        # A long output path can be readable by native Windows file tools while
        # Python's regular Win32 open returns WinError 3 at the 260-character
        # boundary. Robocopy copies one named file and returns 0-7 on success.
        robocopy = subprocess.run(
            ["robocopy", str(source.parent), str(destination.parent), source.name, "/COPY:DAT", "/R:1", "/W:0", "/NFL", "/NDL", "/NJH", "/NJS", "/NP"],
            capture_output=True,
            text=True,
            check=False,
        )
        if robocopy.returncode <= 7:
            return
        # Keep a PowerShell fallback for hosts without robocopy or where it
        # reports a retryable copy error.
        def quote(value: pathlib.Path) -> str:
            return "'" + str(value).replace("'", "''") + "'"

        command = f"Copy-Item -LiteralPath {quote(source)} -Destination {quote(destination)} -Force -ErrorAction Stop"
        result = subprocess.run(
            ["pwsh.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "no PowerShell diagnostic"
            raise RuntimeError(f"controller long-path copy failed: {source} -> {destination}: {detail}") from first_error
        return


def _controller_path_exists(path: pathlib.Path) -> bool:
    """Check a controller path with a long-path-capable Windows API tool."""
    if path.exists():
        return True
    def quote(value: pathlib.Path) -> str:
        return "'" + str(value).replace("'", "''") + "'"
    result = subprocess.run(
        ["pwsh.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", f"Test-Path -LiteralPath {quote(path)}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip().lower() == "true"


def _controller_sha256(path: pathlib.Path) -> str:
    """Hash a controller file, falling back for paths beyond MAX_PATH."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError as first_error:
        quoted = "'" + str(path).replace("'", "''") + "'"
        result = subprocess.run(
            ["pwsh.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", f"(Get-FileHash -LiteralPath {quoted} -Algorithm SHA256).Hash"],
            capture_output=True,
            text=True,
            check=False,
        )
        value = result.stdout.strip().lower()
        if result.returncode != 0 or not re.fullmatch(r"[0-9a-f]{64}", value):
            detail = result.stderr.strip() or result.stdout.strip() or "no hash diagnostic"
            raise RuntimeError(f"controller long-path hash failed: {path}: {detail}") from first_error
        return value


def _write_worker_manifest(run_root: pathlib.Path, stage_root: pathlib.Path) -> None:
    stage_root.joinpath("case-manifest.json").write_text(json.dumps(_worker_manifest(run_root), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _stage_worker_input(run_root: pathlib.Path, stage_root: pathlib.Path) -> None:
    stage_root.mkdir(parents=True, exist_ok=False)
    _copytree_verified(run_root / "snapshot", stage_root / "snapshot")
    shutil.copytree(run_root.parents[1] / "v2", stage_root / "v2", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "runs"))
    _write_worker_manifest(run_root, stage_root)
    manifest = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))
    manifest["prompt_path"] = "/opt/j05-worker/v2/runtime/prompts/p1.json"
    manifest["snapshot_binding"]["context_path"] = "/opt/j05-worker/snapshot/context.json"
    manifest["snapshot_binding"]["records_path"] = "/opt/j05-worker/snapshot/workbench-data/runtime-state/records.json"
    stage_root.joinpath("manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    worker_run = stage_root / "worker-run"
    worker_run.mkdir(parents=True, exist_ok=True)
    _copytree_verified(stage_root / "snapshot", worker_run / "snapshot")
    shutil.copy2(stage_root / "manifest.json", worker_run / "manifest.json")
    shutil.copy2(stage_root / "case-manifest.json", worker_run / "case-manifest.json")


def _install_worker_network_rule(table: str, uid: int, gateway_ip: str, gateway_port: int) -> dict[str, Any]:
    rules = f"""table inet {table} {{
  chain output {{
    type filter hook output priority 0; policy accept;
    meta skuid {uid} ip daddr {gateway_ip} tcp dport {gateway_port} accept
    meta skuid {uid} counter drop
  }}
}}
"""
    applied = _wsl("--distribution", "Debian", "--", "nft", "-f", "-", input_text=rules)
    if applied.returncode != 0:
        raise RuntimeError(f"could not install per-worker nftables rule: {applied.stderr.strip() or applied.stdout.strip()}")
    observed = _wsl("--distribution", "Debian", "--", "nft", "list", "table", "inet", table)
    if observed.returncode != 0 or f"meta skuid {uid}" not in observed.stdout or f"ip daddr {gateway_ip}" not in observed.stdout:
        raise RuntimeError("installed worker network rule could not be read back")
    return {"table": table, "uid": uid, "gateway_ip": gateway_ip, "gateway_port": gateway_port, "rules": rules, "observed": observed.stdout}


def _delete_worker_network_rule(table: str) -> dict[str, Any]:
    removed = _wsl("--distribution", "Debian", "--", "nft", "delete", "table", "inet", table)
    return {"table": table, "removed": removed.returncode == 0, "error": removed.stderr.strip() or None}


def _copy_worker_outputs(stage_root: pathlib.Path, run_root: pathlib.Path, output_name: str) -> None:
    worker_run = stage_root / "worker-run"
    # Do not use the Windows `\\wsl$` provider for the output tree.  It can
    # enumerate a Linux file and then fail to open that same file with
    # WinError 3.  Export the worker-owned tree through WSL's own tar stream,
    # which keeps the read on the Linux filesystem and preserves every file.
    stage_name = stage_root.name
    linux_base = f"/opt/j05-worker/runs/{stage_name}/worker-run"
    auxiliary_files = ("j05-real.json", "j05-real-trajectory-evidence.jsonl", "worker-execution.json", "worker-control-result.json")
    # Dereference hard links while exporting.  Some frozen runtime snapshots
    # contain hard-linked JSON artifacts; GNU tar otherwise emits a link entry
    # whose target can be lost when Python extracts the stream on Windows.
    archive = _wsl_binary(
        "--distribution", "Debian", "--", "tar", "--hard-dereference", "-C", linux_base,
        "-cf", "-", output_name, *auxiliary_files,
    )
    if archive.returncode != 0:
        error = archive.stderr.decode("utf-8", "replace").strip() or "worker output archive failed"
        raise RuntimeError(f"could not export worker output through WSL: {error}")
    temporary_root = pathlib.Path(tempfile.mkdtemp(prefix="j05-worker-export-"))
    transport_copy_errors: list[dict[str, str]] = []
    try:
        with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as bundle:
            members = bundle.getmembers()
            prefix = output_name.rstrip("/") + "/"
            allowed_top_level = {output_name, *auxiliary_files}
            output_file_members = 0
            for member in members:
                name = member.name.replace("\\", "/")
                top_level = name.split("/", 1)[0]
                if (top_level not in allowed_top_level) or (top_level == output_name and name != output_name and not name.startswith(prefix)) or ".." in pathlib.PurePosixPath(name).parts:
                    raise RuntimeError(f"unexpected worker output archive member: {member.name}")
                if top_level == output_name and member.isfile():
                    output_file_members += 1
            bundle.extractall(path=temporary_root)
        temporary_output = temporary_root / output_name
        if not temporary_output.exists() or output_file_members == 0:
            raise RuntimeError(f"worker output archive was empty: {output_name}")
        worker_proof = _read_json(temporary_root / "worker-execution.json", {})
        if (worker_proof.get("snapshot_completeness") or {}).get("all_complete") is not True:
            raise RuntimeError("worker did not prove complete frozen snapshot materialization")
        target_output = run_root / output_name
        # The archive is already local at this point.  Copy the worker result
        # tree as-is, then repair only transport omissions from the frozen
        # source after the worker-side completeness proof above.
        target_output.mkdir(parents=True, exist_ok=False)
        for source_dir in (temporary_output, *[item for item in temporary_output.rglob("*") if item.is_dir()]):
            (target_output / source_dir.relative_to(temporary_output)).mkdir(parents=True, exist_ok=True)
        for source_file in (item for item in temporary_output.rglob("*") if item.is_file()):
            target_file = target_output / source_file.relative_to(temporary_output)
            try:
                target_file.parent.mkdir(parents=True, exist_ok=True)
                _copy_file_controller(source_file, target_file)
            except OSError as exc:
                transport_copy_errors.append({"relative_path": str(source_file.relative_to(temporary_output)), "error": repr(exc)})
        for name in auxiliary_files:
            source = temporary_root / name
            if source.exists():
                target = run_root / name
                _copy_file_controller(source, target)
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)
    if output_name == "worker-control-trajectories":
        for name in ("j05-real.json", "j05-real-trajectory-evidence.jsonl"):
            source = run_root / name
            target = run_root / ("worker-control-" + name)
            if source.exists():
                source.replace(target)
    unrepairable_copy_errors = [
        item for item in transport_copy_errors
        if "isolated-snapshot" not in item.get("relative_path", "").replace("\\", "/").split("/")
    ]
    if unrepairable_copy_errors:
        raise RuntimeError(f"worker output transport lost non-snapshot evidence: {unrepairable_copy_errors[:3]}")
    transport = _repair_missing_snapshot_files(run_root, run_root / output_name)
    if transport_copy_errors:
        transport["copy_errors"] = transport_copy_errors
        transport["copy_errors_reconciled"] = True
    _write_json(run_root / "worker-output-transport.json", transport)


def _repair_missing_snapshot_files(run_root: pathlib.Path, output_root: pathlib.Path) -> dict[str, Any]:
    """Repair only transport omissions after a worker-side completeness proof."""
    source = run_root / "snapshot"
    expected = {str(item.relative_to(source)): item for item in source.rglob("*") if item.is_file()}
    # These files are deliberately mutated by registered fixture interventions
    # (cold-start/task/source updates).  Their post-event hashes are therefore
    # not expected to equal the frozen baseline, but absence is still fatal:
    # repairing a missing mutated file from the baseline would erase evidence.
    mutable_snapshot_files = {"context.json", str(pathlib.Path(RECORDS_REL))}
    before: list[dict[str, str]] = []
    repaired: list[dict[str, str]] = []
    allowed_mutations: list[dict[str, str]] = []
    for isolated in output_root.rglob("isolated-snapshot"):
        for relative, source_file in expected.items():
            target = isolated / relative
            if not _controller_path_exists(target):
                if relative in mutable_snapshot_files:
                    raise RuntimeError(f"worker output transport lost mutated snapshot file: {target}")
                before.append({"trajectory": str(isolated.parent), "relative_path": relative, "status": "missing"})
                target.parent.mkdir(parents=True, exist_ok=True)
                _copy_file_controller(source_file, target)
                repaired.append({"trajectory": str(isolated.parent), "relative_path": relative, "status": "copied_from_frozen_source"})
            elif relative in mutable_snapshot_files and _controller_sha256(target) != _controller_sha256(source_file):
                allowed_mutations.append({"trajectory": str(isolated.parent), "relative_path": relative, "status": "fixture_mutation_preserved"})
            elif _controller_sha256(target) != _controller_sha256(source_file):
                raise RuntimeError(f"worker output transport content mismatch: {target}")
    remaining = []
    for isolated in output_root.rglob("isolated-snapshot"):
        remaining.extend(
            {"trajectory": str(isolated.parent), "relative_path": relative, "status": "still_missing"}
            for relative in sorted(expected)
            if not _controller_path_exists(isolated / relative)
        )
    if remaining:
        raise RuntimeError(f"worker output transport repair incomplete: {remaining[:3]}")
    return {"status": "passed", "source": str(source), "output_root": str(output_root), "missing_before_count": len(before), "repaired_count": len(repaired), "missing_before": before, "repairs": repaired, "allowed_mutations": allowed_mutations}


def _run_wsl_worker(run_root: pathlib.Path, *, model: str, binding: ProviderBinding | None, production_root: pathlib.Path | None, probe_only: bool, max_budget_cny: float | None = None, cny_per_usd_ceiling: float = 10.0, max_output_tokens: int = 512, selected_case_ids: list[str] | None = None, trajectory_order: list[dict[str, Any]] | None = None, execution_scope: str = "full_j05") -> dict[str, Any]:
    wsl_evidence = _assert_wsl2_and_no_automount()
    uid = _ensure_worker_user()
    stage_name = f"{run_root.name}-{'control' if probe_only else 'real'}"
    stage_root = pathlib.Path(r"\\wsl$\Debian\opt\j05-worker\runs") / stage_name
    if stage_root.exists():
        raise FileExistsError(f"refusing to reuse WSL worker stage: {stage_root}")
    _stage_worker_input(run_root, stage_root)
    gateway_ip = _wsl_gateway_ip()
    try:
        if probe_only:
            relay = start_relay(None, log_path=run_root / "worker-control-relay.jsonl", model="worker-control-probe", scripted=True, advertised_host=gateway_ip)
        else:
            if binding is None or not binding.ready:
                raise RuntimeError("real worker requires the already-bound provider")
            relay = start_relay(binding, log_path=run_root / "worker-gateway-relay.jsonl", model=model, advertised_host=gateway_ip, max_budget_cny=max_budget_cny, cny_per_usd_ceiling=cny_per_usd_ceiling, max_output_tokens=max_output_tokens)
    except Exception:
        # Do not strand a staged snapshot when relay startup fails before the
        # main network-rule/finally block is entered.
        try:
            shutil.rmtree(stage_root)
        except OSError:
            pass
        raise
    table = "j05_" + re.sub(r"[^a-zA-Z0-9_]", "_", stage_name)[:24]
    network_record: dict[str, Any] = {}
    output_name = "worker-control-trajectories" if probe_only else "j05-trajectories-real"
    output_copy_completed = False
    try:
        relay_port = int(relay.base_url.rsplit(":", 1)[1])
        network_record = _install_worker_network_rule(table, uid, gateway_ip, relay_port)
        config = {
            "run_id": run_root.name, "input_root": "/opt/j05-worker/runs/" + stage_name,
            "run_root": "/opt/j05-worker/runs/" + stage_name + "/worker-run",
            "output_root": "/opt/j05-worker/runs/" + stage_name + "/worker-run/" + output_name,
            "relay_url": relay.base_url.replace("127.0.0.1", gateway_ip), "relay_token": relay.token,
            "model": relay.model, "probe_only": probe_only, "scripted_relay": probe_only,
            "sample_gate": "passed", "code_hash": json.loads((run_root / "manifest.json").read_text(encoding="utf-8")).get("code_hash"),
            "spend_guard": {"enabled": max_budget_cny is not None, "max_budget_cny": max_budget_cny, "cny_per_usd_safety_ceiling": cny_per_usd_ceiling, "max_output_tokens": max_output_tokens},
            "prompt_paths": {
                "A": f"/opt/j05-worker/runs/{stage_name}/v2/runtime/prompts/p1.json",
                "B": f"/opt/j05-worker/runs/{stage_name}/v2/runtime/prompts/concerns-v1.json",
                "C": f"/opt/j05-worker/runs/{stage_name}/v2/runtime/prompts/concerns-v1.json",
            },
            "selected_case_ids": selected_case_ids,
            "trajectory_order": trajectory_order,
            "planned_trajectories": len(trajectory_order) if trajectory_order else None,
            "execution_scope": execution_scope,
        }
        chown = _wsl("--distribution", "Debian", "--", "chown", "-R", "j05worker:j05worker", f"/opt/j05-worker/runs/{stage_name}/worker-run")
        if chown.returncode != 0:
            raise RuntimeError(f"could not grant worker state directory ownership: {chown.stderr.strip() or chown.stdout.strip()}")
        config_path = stage_root / "worker-run-config.json"
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        command = ["--distribution", "Debian", "--cd", "/", "--user", "j05worker", "--", "python3", f"/opt/j05-worker/runs/{stage_name}/v2/cli.py", "worker-run", "--config", f"/opt/j05-worker/runs/{stage_name}/worker-run-config.json"]
        process = _wsl(*command, timeout=1800)
        worker_output = {"returncode": process.returncode, "stdout": process.stdout[-12000:], "stderr": process.stderr[-12000:]}
        _copy_worker_outputs(stage_root, run_root, output_name)
        output_copy_completed = True
        proof_path = run_root / "worker-execution.json"
        proof = json.loads(proof_path.read_text(encoding="utf-8")) if proof_path.exists() else {}
        cost = _write_real_cost_artifact(run_root, max_budget_cny=max_budget_cny, cny_per_usd_ceiling=cny_per_usd_ceiling, max_output_tokens=max_output_tokens) if not probe_only else None
        proof["controller_observation"] = {"wsl": wsl_evidence, "network_rule": network_record, "worker_command_returncode": process.returncode, "worker_stdout_tail": process.stdout[-2000:], "worker_stderr_tail": process.stderr[-2000:], "spend_guard": cost}
        proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"status": "passed" if process.returncode == 0 and proof.get("status") == "passed" else "failed", "worker": worker_output, "proof": proof, "network": network_record, "output_name": output_name}
    finally:
        _delete_worker_network_rule(table)
        relay.stop()
        try:
            (stage_root / "worker-run-config.json").unlink(missing_ok=True)
            if output_copy_completed:
                shutil.rmtree(stage_root)
            else:
                quarantine = stage_root.with_name(stage_root.name + "-failed-output-copy")
                suffix = 2
                while quarantine.exists():
                    quarantine = stage_root.with_name(stage_root.name + f"-failed-output-copy-{suffix}")
                    suffix += 1
                stage_root.rename(quarantine)
        except OSError:
            pass


def run_worker_control_probe(run_root: pathlib.Path) -> dict[str, Any]:
    return _run_wsl_worker(run_root, model="worker-control-probe", binding=None, production_root=None, probe_only=True)


def run_real_worker_j05(run_root: pathlib.Path, *, model: str, production_root: pathlib.Path, max_budget_cny: float, cny_per_usd_ceiling: float = 10.0, max_output_tokens: int = 512, selected_case_ids: list[str] | None = None, trajectory_order: list[dict[str, Any]] | None = None, execution_scope: str = "full_j05") -> dict[str, Any]:
    binding, _effective = resolve_production_text_binding(production_root=production_root)
    if binding.model != model:
        return {"status": "blocked", "execution": "not_started", "provider_calls": 0, "reason": "requested model differs from effective production binding"}
    if max_budget_cny <= 0:
        return {"status": "blocked", "execution": "not_started", "provider_calls": 0, "reason": "real worker requires a positive CNY spend ceiling"}
    return _run_wsl_worker(run_root, model=model, binding=binding, production_root=production_root, probe_only=False, max_budget_cny=max_budget_cny, cny_per_usd_ceiling=cny_per_usd_ceiling, max_output_tokens=max_output_tokens, selected_case_ids=selected_case_ids, trajectory_order=trajectory_order, execution_scope=execution_scope)

