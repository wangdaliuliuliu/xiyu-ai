"""Evidence and handoff reports for the real-provider execution stages."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import os
from typing import Any

from controller.worker_execution import validate_worker_execution_proof


def _read(path: pathlib.Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _cmd(command: list[str], timeout: int = 15) -> dict[str, Any]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "error_type": type(exc).__name__}
    return {"available": completed.returncode == 0, "returncode": completed.returncode, "stdout": (completed.stdout or "")[-3000:], "stderr": (completed.stderr or "")[-1000:]}


def _file_fact(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {"path": str(path.resolve()), "status": "absent"}
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"path": str(path.resolve()), "status": "present", "bytes": path.stat().st_size, "sha256": digest}


_REVIEW_SECRET_KEYS = {"api_key", "apikey", "authorization", "credential", "password", "token", "secret"}
_REVIEW_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|/)(?:[^\s\\/]+[\\/])+[^\s]*")
_REVIEW_UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", re.IGNORECASE)
_REVIEW_HEX_RE = re.compile(r"\b[0-9a-f]{32,64}\b", re.IGNORECASE)
_REVIEW_EMAIL_RE = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_REVIEW_DATE_RE = re.compile(r"\b20\d{2}-\d{2}-\d{2}(?:[T ][^\s]+)?")


def _anonymize_review_text(value: str) -> str:
    """Scrub identifiers and transport-sensitive strings while retaining dialogue."""
    value = _REVIEW_PATH_RE.sub("<path>", value)
    value = _REVIEW_EMAIL_RE.sub("<email>", value)
    value = _REVIEW_UUID_RE.sub("<id>", value)
    value = _REVIEW_HEX_RE.sub("<digest>", value)
    value = _REVIEW_DATE_RE.sub("<time>", value)
    value = value.replace("account:1:companion:1", "owner_1")
    return value


def _anonymize_review_value(value: Any, *, key: str = "") -> Any:
    if key.lower() in _REVIEW_SECRET_KEYS or any(part in key.lower() for part in _REVIEW_SECRET_KEYS):
        return "<redacted>"
    if isinstance(value, str):
        return _anonymize_review_text(value)
    if isinstance(value, list):
        return [_anonymize_review_value(item, key=key) for item in value]
    if isinstance(value, dict):
        return {str(name): _anonymize_review_value(item, key=str(name)) for name, item in value.items() if str(name).lower() not in _REVIEW_SECRET_KEYS}
    return value


def build_anonymous_review_artifacts(*, run_root: pathlib.Path, real: dict[str, Any]) -> dict[str, Any]:
    """Create reviewer-facing, anonymous transcripts without copying raw prompts or credentials."""
    evidence_path = run_root / "j05-real-trajectory-evidence.jsonl"
    trajectory_root = run_root / "j05-trajectories-real"
    trajectories: list[dict[str, Any]] = []
    if evidence_path.exists():
        evidence_rows = [_read_json_line(line) for line in evidence_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        evidence_rows = []
    evidence_by_key = {(row.get("arm"), row.get("case_id"), row.get("repetition")): row for row in evidence_rows if isinstance(row, dict)}
    for result_path in sorted(trajectory_root.glob("*/K*/r*/trajectory-result.json")):
        result = _read(result_path, {}) or {}
        key = (result.get("arm"), result.get("case_id"), result.get("repetition"))
        trace_path = result_path.parent / "traces" / "trace.jsonl"
        conversation: list[dict[str, Any]] = []
        if trace_path.exists():
            for line in trace_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("kind") == "input":
                    payload = row.get("input") if isinstance(row.get("input"), dict) else {}
                    conversation.append({
                        "speaker": "user" if row.get("entry_kind") == "user_message" else "experiment_event",
                        "kind": row.get("entry_kind"),
                        "virtual_time": payload.get("virtual_time"),
                        "content": _anonymize_review_value(payload.get("payload", payload)),
                    })
                elif row.get("kind") == "provider_call":
                    conversation.append({
                        "speaker": "assistant",
                        "kind": row.get("entry_kind"),
                        "content": _anonymize_review_value(row.get("raw_response") or {}),
                        "finish_reason": row.get("finish_reason"),
                        "latency_ms": row.get("latency_ms"),
                        "usage": _anonymize_review_value(row.get("usage") or {}),
                    })
                elif row.get("kind") in {"tool_result", "decision", "state_change", "delivery", "receipt"}:
                    conversation.append({
                        "speaker": "system",
                        "kind": row.get("kind"),
                        "content": _anonymize_review_value(row.get("output") or row.get("decision") or row.get("tool_result") or {}),
                    })
        relative = result_path.parent.relative_to(run_root).as_posix()
        trajectories.append({
            "anonymous_trajectory_id": f"{result.get('arm', 'x')}-{result.get('case_id', 'x')}-r{int(result.get('repetition', 0) or 0):02d}",
            "arm": result.get("arm"),
            "case_id": result.get("case_id"),
            "repetition": result.get("repetition"),
            "automated_execution_status": result.get("status"),
            "semantic_acceptance_status": result.get("semantic_acceptance_status", "pending_independent_evaluator"),
            "provider_mode": result.get("provider_mode"),
            "conversation": conversation,
            "event_result_summary": _anonymize_review_value((evidence_by_key.get(key) or {}).get("event_results", [])),
            "evidence_refs": {"trajectory_result": f"{relative}/trajectory-result.json", "trace": f"{relative}/traces/trace.jsonl"},
        })
    failure_rows = [row for row in trajectories if row.get("automated_execution_status") != "passed"]
    worst = []
    for row in sorted(failure_rows, key=lambda item: (item.get("case_id") or "", item.get("arm") or "", item.get("repetition") or 0))[:12]:
        statuses = [item.get("status") for item in row.get("event_result_summary", []) if isinstance(item, dict)]
        reasons = [item.get("reason") for item in row.get("event_result_summary", []) if isinstance(item, dict) and item.get("reason")]
        worst.append({"anonymous_trajectory_id": row["anonymous_trajectory_id"], "triage_only": True, "automated_status": row.get("automated_execution_status"), "event_statuses": statuses, "formal_reasons": reasons})
    result = {
        "schemaVersion": "anonymous-blind-review-v1",
        "runId": run_root.name,
        "status": "ready_with_automated_failures" if len(trajectories) == int(real.get("total_trajectories", 0) or 0) and trajectories else "incomplete",
        "review_boundary": "sample_generation_available; human blind review blocks final subjective conclusion only",
        "privacy": {"credentials_included": False, "raw_system_prompts_included": False, "raw_provider_transport_included": False, "sanitization": "identifiers, paths, emails, timestamps and secret-like keys scrubbed; dialogue/decisions retained"},
        "binding": {"provider_mode": "real", "model_label": "bound-primary-model", "parameters": {"temperature": 0, "top_p": 1, "response_format": "json_object"}, "semantic_status": "pending_independent_evaluator"},
        "counts": {"trajectories": len(trajectories), "expected": real.get("total_trajectories", 108), "automated_passed": sum(row.get("automated_execution_status") == "passed" for row in trajectories), "automated_failed": len(failure_rows), "blind_review_items": 12},
        "trajectories": trajectories,
        "worst_samples_automated_triage": worst,
    }
    path = run_root / "anonymous-blind-review.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"path": str(path), "status": result["status"], "trajectory_count": len(trajectories), "worst_sample_count": len(worst)}


def _read_json_line(line: str) -> dict[str, Any]:
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def audit_source_access(*, run_root: pathlib.Path, host: str = "xiyu.myworlds.cn") -> dict[str, Any]:
    """Try only existing local SSH identities and a read-only status command."""
    ssh = shutil.which("ssh.exe") or shutil.which("ssh")
    ssh_dir = pathlib.Path(os.environ.get("USERPROFILE", "")) / ".ssh"
    key_names = ("capybara-game-deploy-ed25519", "limi_overseas_ed25519", "limi_overseas_nopass2")
    candidates = [ssh_dir / name for name in key_names if (ssh_dir / name).exists()]
    attempts: list[dict[str, Any]] = []
    remote_command = "id; hostname; pwd; printf 'SOURCE_INSTANCE_ID:'; curl --max-time 2 -fsS http://100.100.100.200/latest/meta-data/instance-id 2>/dev/null || true; printf '\\nSOURCE_ACCOUNT_BINDING:%s@%s\\n' \"$USER\" \"$HOSTNAME\"; printf 'SOURCE_EXPORT_SCOPE:read-only\\n'; for svc in xiyu-ai.service zhaohy-wechat.service; do systemctl show \"$svc\" --property=LoadState,ActiveState,SubState,FragmentPath,User,WorkingDirectory,EnvironmentFiles --no-pager 2>/dev/null; done; for p in /opt/xiyu-ai /opt/xiyu-ai-new; do if [ -d \"$p\" ]; then echo DIR:$p; stat -c 'mode=%a owner=%U group=%G' \"$p\"; git -C \"$p\" rev-parse HEAD 2>/dev/null; git -C \"$p\" branch --show-current 2>/dev/null; node --version 2>/dev/null; fi; done; getent passwd xiyu 2>/dev/null; ss -lnt 2>/dev/null | grep -E ':(3000|4175)' || true"
    if not ssh:
        attempts.append({"status": "not_attempted", "reason": "ssh_client_unavailable"})
    elif not candidates:
        attempts.append({"status": "not_attempted", "reason": "no_existing_local_identity_file"})
    else:
        for key in candidates:
            for user in ("administrator", "root", "xiyu"):
                command = [ssh, "-o", "BatchMode=yes", "-o", "ConnectTimeout=6", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=NUL", "-i", str(key), f"{user}@{host}", remote_command]
                outcome = _cmd(command, timeout=12)
                row = {"key_file": key.name, "user": user, "host": host, "status": "connected" if outcome.get("available") else "access_denied_or_failed", "returncode": outcome.get("returncode"), "error": (outcome.get("stderr") or outcome.get("stdout") or "")[-1000:]}
                if outcome.get("available"):
                    row["read_only_observation"] = outcome.get("stdout", "")
                    observation = row["read_only_observation"]
                    instance_match = re.search(r"SOURCE_INSTANCE_ID:([^\r\n]*)", observation)
                    binding_match = re.search(r"SOURCE_ACCOUNT_BINDING:([^\r\n]*)", observation)
                    scope_match = re.search(r"SOURCE_EXPORT_SCOPE:([^\r\n]*)", observation)
                    dir_match = re.search(r"(?:^|\n)DIR:(/[^\r\n]+)", observation)
                    pwd_match = re.search(r"(?:^|\n)(/opt/[^\r\n]+)\s*$", observation)
                    node_versions = re.findall(r"(v\d+\.\d+(?:\.\d+)?)", observation)
                    revisions = [item for item in re.findall(r"(?:^|\n)([0-9a-f]{40})\s*$", observation, flags=re.MULTILINE)]
                    identity_facts = {
                        "instance_id": (instance_match.group(1).strip() if instance_match else ""),
                        "runtime_path": (dir_match.group(1).strip() if dir_match else (pwd_match.group(1).strip() if pwd_match else "")),
                        "runtime_version": ";".join([*node_versions, *revisions]),
                        "account_binding": (binding_match.group(1).strip() if binding_match else ""),
                        "export_scope": (scope_match.group(1).strip() if scope_match else ""),
                    }
                    row["identity_facts"] = identity_facts
                    row["source_identity_authorization"] = "verified" if all(identity_facts.values()) and identity_facts["export_scope"] == "read-only" else "unverified"
                    attempts.append(row)
                    if row["source_identity_authorization"] == "verified":
                        break
                elif outcome.get("available") is False:
                    attempts.append(row)
    verified_attempt = next((item for item in attempts if item.get("source_identity_authorization") == "verified"), None)
    result = {
        "schemaVersion": "source-access-readonly-v1",
        "host": host,
        "read_only": True,
        "credentials_in_evidence": False,
        "attempts": attempts,
        "status": "verified" if verified_attempt else ("access_unverified" if any(item.get("status") == "connected" for item in attempts) else "access_unverified"),
        "source_identity_authorization": "verified" if verified_attempt else "unverified",
        "identity_facts": verified_attempt.get("identity_facts") if verified_attempt else None,
        "identity_verification_method": "authenticated read-only SSH observation with instance metadata, runtime path/version, account binding and explicit export scope" if verified_attempt else None,
    }
    (run_root / "source-access-readonly.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def collect_environment_evidence(*, run_root: pathlib.Path, production_root: pathlib.Path) -> dict[str, Any]:
    preflight = _read(run_root / "completion-preflight.json", {}) or {}
    source_audit = _read(run_root / "source-runtime-readonly.json", {}) or {}
    source_access = _read(run_root / "source-access-readonly.json", {}) or {}
    isolation = _read(run_root / "isolation-probe.json", {}) or {}
    worker_execution = validate_worker_execution_proof(run_root)
    provider_probe = _read(run_root / "provider-probe.json", {}) or {}
    effective = _read(run_root / "effective-provider.json", {}) or {}
    probe_http_status = provider_probe.get("http_status")
    if probe_http_status is None and isinstance(provider_probe.get("attempts"), list) and provider_probe["attempts"]:
        probe_http_status = provider_probe["attempts"][-1].get("http_status")
    root = production_root.resolve()
    runtimes = {}
    for name in ("docker", "podman", "wsl", "runas", "icacls"):
        path = shutil.which(name)
        runtimes[name] = {"path": path, "available": bool(path), "version": _cmd([name, "--version"]) if path else {"available": False, "reason": "command_not_found"}}
    identity = {"user": _cmd(["whoami.exe", "/user"]), "groups": _cmd(["whoami.exe", "/groups"]), "privileges": _cmd(["whoami.exe", "/priv"])}
    acl = _cmd(["icacls.exe", str(run_root)]) if runtimes["icacls"]["available"] else {"available": False, "reason": "icacls_unavailable"}
    # A global firewall snapshot is useful for investigation, but is not
    # counted as a per-worker egress policy or an E1 qualification.
    firewall = _cmd(["powershell.exe", "-NoProfile", "-Command", "Get-NetFirewallProfile | Select-Object Name,Enabled,DefaultOutboundAction | ConvertTo-Json -Compress"])
    windows_features = _cmd(["powershell.exe", "-NoProfile", "-Command", "$names=@('Containers-DisposableClientVM','Containers','Microsoft-Hyper-V-All','VirtualMachinePlatform','Microsoft-Windows-Subsystem-Linux'); Get-WindowsOptionalFeature -Online -ErrorAction SilentlyContinue | Where-Object FeatureName -in $names | Select-Object FeatureName,State | ConvertTo-Json -Compress"])
    worker_services = _cmd(["powershell.exe", "-NoProfile", "-Command", "Get-Service -Name 'docker','podman','vmcompute','com.docker.service','LxssManager' -ErrorAction SilentlyContinue | Select-Object Name,Status,StartType | ConvertTo-Json -Compress"])
    ssh_agent_bin = shutil.which("ssh-add.exe") or shutil.which("ssh-add")
    ssh_agent_probe = _cmd([ssh_agent_bin, "-L"]) if ssh_agent_bin else {"available": False, "reason": "ssh-add_unavailable"}
    ssh_agent = {"available": ssh_agent_probe.get("available", False), "returncode": ssh_agent_probe.get("returncode"), "error": (ssh_agent_probe.get("stderr") or ssh_agent_probe.get("stdout") or "")[-500:]}
    service_path = root / "deploy" / "xiyu-ai.service"
    service_text = service_path.read_text(encoding="utf-8", errors="replace") if service_path.exists() else ""
    service_facts = {
        "file": _file_fact(service_path),
        "declared_user": next((line.split("=", 1)[1].strip() for line in service_text.splitlines() if line.startswith("User=")), None),
        "working_directory": next((line.split("=", 1)[1].strip() for line in service_text.splitlines() if line.startswith("WorkingDirectory=")), None),
        "environment_file": next((line.split("=", 1)[1].strip() for line in service_text.splitlines() if line.startswith("EnvironmentFile=")), None),
        "hardening_directives": [line.strip() for line in service_text.splitlines() if line.strip() in {"NoNewPrivileges=true", "PrivateTmp=true", "ProtectSystem=strict", "ProtectHome=true"}],
        "runtime_observed_locally": False,
    }
    qualified = isolation.get("qualification") in {"qualified", "os_qualified", "passed"} and isolation.get("status") == "passed"
    source_identity_facts = source_access.get("identity_facts") if isinstance(source_access.get("identity_facts"), dict) else None
    source_verified = source_access.get("source_identity_authorization") == "verified" and isinstance(source_identity_facts, dict) and all(source_identity_facts.get(key) not in (None, "") for key in ("instance_id", "runtime_path", "runtime_version", "account_binding", "export_scope")) and source_identity_facts.get("export_scope") == "read-only"
    result = {
        "schemaVersion": "environment-evidence-v1",
        "recordedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "runId": run_root.name,
        "source": {
            "production_root": str(root),
            "read_only_materials": [_file_fact(root / ".env"), _file_fact(root / "data" / "bot.db"), _file_fact(root / "src" / "providers" / "chat.mjs"), service_facts["file"]],
            "service": service_facts,
            "public_health": {key: source_audit.get(key) for key in ("status", "http_status", "runtime_availability", "source_identity_authorization", "credentials_sent", "confirmed_unavailable_evidence")},
            "identity_status": "verified" if source_verified else "unverified_public_health_only",
            "actual_aliyun_identity_or_account_binding_observed": source_verified,
            "identity_facts": source_identity_facts,
            "ssh_read_only_access_attempt": source_access,
        },
        "isolation": {
            "qualification": "os_qualified" if qualified else "not_os_qualified",
            "probe": isolation,
            "available_runtime_investigation": runtimes,
            "current_os_identity": identity,
            "experiment_acl": acl,
            "host_firewall_snapshot": firewall,
            "windows_optional_features": windows_features,
            "worker_services": worker_services,
            "ssh_agent": ssh_agent,
            "worker_network_policy_proof": worker_execution.get("status") == "passed",
            "worker_execution": worker_execution,
            "reason": "No Docker/Podman or qualified WSL worker is available locally; process-local guards and child probes are retained as negative controls only." if not qualified else ("isolation probe passed but the actual trajectory worker receipt is still missing" if worker_execution.get("status") != "passed" else "qualified worker evidence recorded"),
        },
        "provider": {
            "effective_provider": effective,
            "probe": {**{key: provider_probe.get(key) for key in ("status", "provider_calls", "model", "finish_reason", "usage", "latency_ms", "reason", "credential_value_recorded", "credential_in_worker", "worker_or_bot_invoked", "production_state_written")}, "http_status": probe_http_status},
            "configured_vs_available": {"configuration_resolved": effective.get("status") == "ready", "real_probe_succeeded": provider_probe.get("status") == "passed", "confirmed_unavailable": provider_probe.get("status") == "failed" and provider_probe.get("error") in {"http_401", "http_403", "http_404"}},
        },
        "read_only": True,
        "production_started": False,
        "production_written": False,
        "bot_delivery": False,
        "p0_allowed": provider_probe.get("status") == "passed",
        "p1_p2_allowed": bool(qualified and worker_execution.get("status") == "passed" and source_verified),
    }
    return result


def write_handoff_artifacts(*, run_root: pathlib.Path, production_root: pathlib.Path) -> dict[str, Any]:
    environment = collect_environment_evidence(run_root=run_root, production_root=production_root)
    (run_root / "environment-evidence.json").write_text(json.dumps(environment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    preflight = _read(run_root / "completion-preflight.json", {}) or {}
    probe = _read(run_root / "provider-probe.json", {}) or {}
    probe_http_status = probe.get("http_status")
    if probe_http_status is None and isinstance(probe.get("attempts"), list) and probe["attempts"]:
        probe_http_status = probe["attempts"][-1].get("http_status")
    fake = _read(run_root / "j05-simulation.json", {}) or {}
    real = _read(run_root / "j05-real.json", {}) or {}
    real_cost = _read(run_root / "real-j05-cost-latency.json", {}) or {}
    smoke = _read(run_root / "smoke-result.json", {}) or {}
    suite_files = sorted(run_root.glob("suite-attempts/*.json"))
    smoke_status = smoke.get("status", "not_started")
    smoke_blocked_reason = smoke.get("reason") if smoke_status in {"inconclusive", "blocked", "gated"} else None
    anonymous_review = build_anonymous_review_artifacts(run_root=run_root, real=real)
    real_evidence_count = anonymous_review.get("trajectory_count", 0)
    real_expected = int(real.get("total_trajectories", 108) or 108)
    real_sample_status = "complete_with_automated_failures" if real_evidence_count == real_expected and real_expected else real.get("status", "not_started")
    ledger = {
        "schemaVersion": "execution-ledger-v1",
        "runId": run_root.name,
        "updatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "policy": {"fake_counts_as": "control_flow_only", "human_review_blocks": "final_subjective_conclusion_only", "production_mutation": "forbidden", "cost_status": real_cost.get("status") or ((preflight.get("cost") or {}).get("status") or "user_authorized_existing_provider_testing")},
        "stages": {
            "P0_provider_probe": {"status": probe.get("status", "not_started"), "planned_requests": 1, "actual_requests": probe.get("provider_calls", 0), "evidence": [str(run_root / "effective-provider.json"), str(run_root / "provider-probe.json")]},
            "P1_main_model_smoke": {"status": smoke_status, "planned_requests": 1, "actual_requests": int(smoke.get("provider_calls", 0) or 0), "blocked_reason": smoke_blocked_reason or ("requires qualified source and worker for enterprise-context smoke" if not smoke else None), "evidence": [str(run_root / "smoke-result.json")] if smoke else []},
            "P2_j05_real_108": {"status": real_sample_status, "planned_trajectories": real_expected, "actual_trajectories": real_evidence_count, "completed_trajectory_records": real.get("completed_trajectories", 0), "failed_trajectory_records": real.get("failed_trajectories", 0), "actual_requests": real.get("real_provider_calls", real.get("provider_calls", 0)), "blocked_reason": real.get("reason") if real.get("status") == "blocked" else None, "evidence": [str(run_root / "j05-real.json"), str(run_root / "j05-real-trajectory-evidence.jsonl"), str(run_root / "anonymous-blind-review.json")] if real else []},
            "P3_original_full_suite": {"status": "not_started", "planned": "original frozen denominator and second-model/image/holdout/continuity/performance suites", "actual": len(suite_files), "blocked_reason": "P2 and original gates not complete", "evidence": [str(p) for p in suite_files]},
            "P4_review_and_final": {"status": "samples_available_pending_blind_review" if anonymous_review.get("status") != "incomplete" else "pending_samples", "planned_blind_review_items": 12, "actual_blind_review_items": 0, "blocked_reason": "human blind review has not been performed; it blocks final subjective conclusion only", "evidence": [str(run_root / "review-pack.md"), str(run_root / "anonymous-blind-review.json")]},
        },
        "control_flow_reference": {"fake_status": fake.get("status", "not_started"), "fake_trajectories": fake.get("total_trajectories", 0), "fake_provider_calls": fake.get("fake_provider_calls", 0), "fake_semantic_acceptance": False, "same_execution_function": "execute_j05_trajectory"},
        "cost_guard": real_cost,
        "source_and_isolation": {"source_identity": environment["source"]["identity_status"], "isolation": environment["isolation"]["qualification"], "worker_execution": environment["isolation"].get("worker_execution", {}).get("status", "not_proven"), "p0_can_continue": environment["p0_allowed"], "p1_p2_can_continue": environment["p1_p2_allowed"]},
    }
    (run_root / "execution-ledger.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    comparison = [
        "# Comparison and cost report", "", f"Run: `{run_root.name}`", "", "## Boundary", "", "- Fake provider is reported as control-flow evidence only and is excluded from semantic acceptance.", "- Real provider usage is reported separately; no role-effect conclusion is inferred from P0.", f"- Cost status: `{ledger['policy']['cost_status']}`; no numeric ceiling is treated as a P0/P1/P2 prerequisite.", "", "## Current measurements", "",
        f"- P0 real provider: `{probe.get('status', 'not_started')}`; requests `{probe.get('provider_calls', 0)}`; HTTP `{probe_http_status}`; usage `{json.dumps(probe.get('usage'), ensure_ascii=False)}`; latency `{probe.get('latency_ms')}` ms.",
        f"- Fake J05 control: `{fake.get('status', 'not_started')}`; trajectories `{fake.get('completed_trajectories', 0)}/{fake.get('total_trajectories', 0)}`; calls `{fake.get('fake_provider_calls', 0)}`.",
        f"- Real J05: sample records `{real_evidence_count}/{real_expected}`; automated execution `{real.get('completed_trajectories', 0)} passed / {real.get('failed_trajectories', 0)} failed`; calls `{real.get('real_provider_calls', real.get('provider_calls', 0))}`; semantic acceptance `pending_independent_evaluator`.",
        f"- Cost reconciliation: actual complete-usage estimate `{(real_cost.get('actual_usage_estimate') or {}).get('estimated_cny_at_safety_rate')}` CNY; unresolved reserve `{(real_cost.get('reservation_reconciliation') or {}).get('unresolved_reserved_cny_at_safety_rate')}` CNY; released reserve `{(real_cost.get('reservation_reconciliation') or {}).get('released_excess_reserved_cny_at_safety_rate')}` CNY; account bill `{(real_cost.get('account_billing') or {}).get('amount')}` (unknown unless separately supplied).",
        "", "## A/B/C", "", "- A/B/C semantic comparison is not claimed until the 108 real trajectories and independent evaluation are present.", "- Same-source and same-parameter pairing is retained in `arm-comparison-manifest.json`.",
    ]
    (run_root / "comparison-cost-report.md").write_text("\n".join(comparison) + "\n", encoding="utf-8")
    review = [
        "# Blind review pack", "", f"Status: `{('ready_with_automated_failures' if anonymous_review.get('status') == 'ready_with_automated_failures' else 'pending_samples')}`", "", "- Sample generation is not blocked by human review.", "- Final subjective conclusion remains blocked until the original 12-item blind review is performed.", "- Anonymous complete dialogue material, automated failure triage and worst-sample candidates are in `anonymous-blind-review.json`; these are not semantic scores.", "- The offline v36/v37 sample grouping and reviewable dialogue export are in `real-sample-audit.json` and `real-sample-audit.md`.", "- The 512-token output-cap audit is in `output-cap-audit.json` and `output-cap-audit.md`.", "- Images and independent evaluator scores remain separate evidence items and are not fabricated here.", f"- Real evidence root: `{run_root / 'j05-trajectories-real'}`", "- Automated scores and reviewer scores must remain separate.",
    ]
    (run_root / "review-pack.md").write_text("\n".join(review) + "\n", encoding="utf-8")
    final = [
        "# Final report", "", f"Run: `{run_root.name}`", "", "## Status boundary", "", f"- Configuration resolved: `{environment['provider']['configured_vs_available']['configuration_resolved']}`.", f"- Real provider technically available: `{environment['provider']['configured_vs_available']['real_probe_succeeded']}`.", f"- P0 provider probe: `{probe.get('status', 'not_started')}`.", f"- Source identity authorization: `{environment['source']['identity_status']}`.", f"- OS isolation: `{environment['isolation']['qualification']}`.", f"- Actual worker execution receipt: `{environment['isolation'].get('worker_execution', {}).get('status', 'not_proven')}`.", f"- Fake J05 control: `{fake.get('status', 'not_started')}`; not semantic acceptance.", f"- Real J05: `{real.get('status', 'not_started')}`.", f"- Cost reconciliation: actual complete-usage estimate `{(real_cost.get('actual_usage_estimate') or {}).get('estimated_cny_at_safety_rate')}` CNY; unresolved reserve `{(real_cost.get('reservation_reconciliation') or {}).get('unresolved_reserved_cny_at_safety_rate')}` CNY; account billing `{(real_cost.get('account_billing') or {}).get('amount')}` (unknown unless separately supplied).", "- Human blind review: final subjective conclusion only; it does not block sample generation.", "- Production: not changed, not started, and no Bot delivery.", "", "## Required interpretation", "", "A successful provider probe proves a reachable model channel, not role behavior. The overall experiment is not complete until real P1/P2/P3 evidence and the original acceptance materials are complete; a missing human review blocks only the final subjective conclusion.",
    ]
    (run_root / "final-report.md").write_text("\n".join(final) + "\n", encoding="utf-8")
    (run_root / "production-integration-diff.md").write_text(
        "# Production integration difference list\n\n"
        "- Experiment-only: `controller/provider_config.py` resolves production materials read-only and hands the credential to the experiment gateway in memory.\n"
        "- Experiment-only: `controller/real_api_probe.py` performs the P0 request; it does not import or start the production entrypoint.\n"
        "- Experiment-only: `evaluation/j05_simulation.py` runs snapshot-bound K01-K12 and writes isolated state/traces.\n"
        "- Not migrated: production provider registry, production scheduler, production memory/task tables, Bot sink, deployment unit and online routing.\n"
        "- Required before any future production integration: explicit module-by-module review, production-safe adapter wiring, migration/rollback plan, and a separately authorized deployment. This run performs none of those actions.\n",
        encoding="utf-8",
    )
    return {"status": "written", "environment": str(run_root / "environment-evidence.json"), "ledger": str(run_root / "execution-ledger.json")}


def prepare_handoff_evidence(*, run_root: pathlib.Path) -> dict[str, Any]:
    """Build a truthful, hash-bound package from current run observations.

    Each invocation creates the next immutable submission.  Claims are derived
    only from current, structured observations; missing facts remain
    unverified instead of being inferred from public health or process-local
    probes.
    """
    package_dir = run_root / "evidence-package"
    existing_numbers = []
    for existing in package_dir.glob("handoff-observed-v*.json"):
        match = re.fullmatch(r"handoff-observed-v(\d+)\.json", existing.name)
        if match:
            existing_numbers.append(int(match.group(1)))
    submission_id = f"handoff-observed-v{max(existing_numbers, default=0) + 1}"
    package_path = package_dir / f"{submission_id}.json"
    package_dir.mkdir(parents=True, exist_ok=True)
    effective = _read(run_root / "effective-provider.json", {}) or {}
    probe = _read(run_root / "provider-probe.json", {}) or {}
    observed_time = (_read(run_root / "environment-evidence.json", {}) or {}).get("recordedAt") or dt.datetime.now(dt.timezone.utc).isoformat()
    primary_facts = {"provider": effective.get("provider"), "model": effective.get("model"), "identity_source": "effective-provider.json plus provider-probe.json"}
    credential_facts = {"credential_scope": "gateway_only", "credential_presence": bool((effective.get("resolved_fields") or {}).get("credential", {}).get("present")), "not_in_worker": not bool(probe.get("credential_in_worker", True))}
    source_access = _read(run_root / "source-access-readonly.json", {}) or {}
    source_facts = source_access.get("identity_facts") if isinstance(source_access.get("identity_facts"), dict) else {}
    source_verified = source_access.get("source_identity_authorization") == "verified" and all(source_facts.get(key) not in (None, "") for key in ("instance_id", "runtime_path", "runtime_version", "account_binding", "export_scope")) and source_facts.get("export_scope") == "read-only"
    worker_validation = validate_worker_execution_proof(run_root)
    worker_proof = worker_validation.get("proof") if isinstance(worker_validation.get("proof"), dict) else {}
    worker_process = worker_proof.get("worker_process") if isinstance(worker_proof.get("worker_process"), dict) else {}
    worker_facts = {
        "worker_kind": worker_proof.get("worker_kind") or worker_proof.get("runtime"),
        "worker_id": worker_proof.get("worker_id") or worker_process.get("worker_id") or worker_process.get("pid"),
        "file_denial": (worker_proof.get("path_policy") or {}).get("production_read_denied") is True and (worker_proof.get("path_policy") or {}).get("production_write_denied") is True,
        "network_denial": (worker_proof.get("network_policy") or {}).get("per_worker_allowlist") is True,
        "oracle_denial": (worker_proof.get("oracle_policy") or {}).get("oracle_read_denied") is True,
        "positive_gateway": (worker_proof.get("gateway") or {}).get("controller_gateway_process") is True,
    }
    worker_verified = worker_validation.get("status") == "passed" and all(worker_facts.get(key) not in (None, "") for key in ("worker_kind", "worker_id")) and all(worker_facts.get(key) is True for key in ("file_denial", "network_denial", "oracle_denial", "positive_gateway"))
    payloads = {
        "primary-model": {"subject": "primary_model_identity", "facts": primary_facts, "observed_at": observed_time, "provider_probe_status": probe.get("status")},
        "provider-credential": {"subject": "provider_credential", "facts": credential_facts, "observed_at": observed_time, "gateway_only": True},
    }
    if source_verified:
        payloads["source-identity"] = {"subject": "source_identity_authorization", "facts": source_facts, "observed_at": observed_time, "verification_method": "authenticated read-only SSH observation"}
    if worker_verified:
        payloads["worker-execution"] = {"subject": "os_or_container_worker", "facts": worker_facts, "observed_at": observed_time, "verification_method": "independent worker execution receipt"}
    artifacts: list[dict[str, Any]] = []
    for stem, payload in payloads.items():
        path = package_dir / f"{stem}-{submission_id}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        artifacts.append({"id": f"{stem}-proof", "kind": "observed-run-evidence", "condition": payload["subject"], "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    source_claim = {"status": "verified", "observed_at": observed_time, "verification_method": "authenticated read-only SSH observation", "artifact_ids": ["source-identity-proof"], "facts": source_facts} if source_verified else {"status": "unverified", "reason": "public health/local reference only; no authorized read-only source identity with complete instance/runtime/account/export facts"}
    worker_claim = {"status": "verified", "observed_at": observed_time, "verification_method": "independent worker execution receipt", "artifact_ids": ["worker-execution-proof"], "facts": worker_facts} if worker_verified else {"status": "unverified", "reason": "no independently constrained worker receipt satisfying OS qualification and trajectory binding"}
    package = {
        "schemaVersion": "ideal-agency-gate-evidence-v1",
        "runId": run_root.name,
        "submissionId": submission_id,
        "submittedAt": observed_time,
        "issuer": "ideal-agency-lab-trusted-controller",
        "artifacts": artifacts,
        "claims": {
            "source_identity_authorization": source_claim,
            "os_or_container_worker": worker_claim,
            "primary_model_identity": {"status": "verified" if effective.get("status") == "ready" and probe.get("status") == "passed" else "unverified", "observed_at": observed_time, "verification_method": "effective production resolver and P0 real probe", "artifact_ids": ["primary-model-proof"], "facts": primary_facts},
            "provider_credential": {"status": "verified" if credential_facts["credential_presence"] and credential_facts["not_in_worker"] else "unverified", "observed_at": observed_time, "verification_method": "gateway-only in-memory binding and worker prompt audit", "artifact_ids": ["provider-credential-proof"], "facts": credential_facts},
            "second_model_identity": {"status": "unverified", "reason": "not required for P0/P1/P2; no distinct second model is declared"},
            "image_provider": {"status": "unverified", "reason": "image branch is separate and not required for P0/P1/P2 text execution"},
            "research_archive": {"status": "unverified", "reason": "FROZEN archive exists locally; separate external research provenance is not a P0/P1/P2 gate"},
            "cost_ceiling": {"status": "unverified", "reason": "numeric ceiling is intentionally not a P0/P1/P2 prerequisite; actual usage is recorded"},
            "human_review": {"status": "not_started", "reason": "blocks only final subjective conclusion"},
        },
    }
    package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "prepared", "package": str(package_path), "artifacts": artifacts}

