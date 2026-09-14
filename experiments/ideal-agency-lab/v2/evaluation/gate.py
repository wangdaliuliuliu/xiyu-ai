"""Evidence submission, validation and release gates for the formal lab.

This module deliberately separates three facts that are often conflated:

* a provider/deployment implementation exists in the repository;
* the formal experiment gateway is wired and has usable evidence; and
* a live provider probe has actually observed availability.

The local audit never calls a production service or provider.  A gate can be
released only by a submitted, hash-checked evidence package.  Human review is
kept out of the sample-generation scopes and is required only for the final
subjective conclusion.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
from typing import Any
from urllib.parse import urlparse


SCHEMA_VERSION = "ideal-agency-gate-evidence-v1"
AUDIT_SCHEMA_VERSION = "provider-deployment-audit-v1"
VALID_STATUSES = {"verified", "confirmed_unavailable", "not_integrated", "unverified", "not_started"}

CONDITION_FACTS: dict[str, tuple[str, ...]] = {
    "source_identity_authorization": ("instance_id", "runtime_path", "runtime_version", "account_binding", "export_scope"),
    "os_or_container_worker": ("worker_kind", "worker_id", "file_denial", "network_denial", "oracle_denial", "positive_gateway"),
    "primary_model_identity": ("provider", "model", "identity_source"),
    "second_model_identity": ("provider", "model", "identity_source"),
    "provider_credential": ("credential_scope", "credential_presence", "not_in_worker"),
    "image_provider": ("provider", "model", "identity_source", "reference_assets"),
    "research_archive": ("archive_id", "source_date", "source_refs", "applicability"),
    "cost_ceiling": ("currency", "max_budget", "price_source", "ceiling_scope"),
    "human_review": ("reviewer_ids", "review_materials", "review_scope"),
}

SAMPLE_REQUIREMENTS = (
    "source_identity_authorization",
    "os_or_container_worker",
    "primary_model_identity",
    "provider_credential",
    "cost_ceiling",
)
FULL_TEXT_REQUIREMENTS = SAMPLE_REQUIREMENTS + ("second_model_identity",)
IMAGE_REQUIREMENTS = SAMPLE_REQUIREMENTS + ("image_provider",)
RESEARCH_REQUIREMENTS = SAMPLE_REQUIREMENTS + ("research_archive",)

MATERIALS = (
    (".env", "production_runtime_config", "sensitive_values_redacted"),
    (".env.example", "configuration_template", "template_only"),
    ("docker-compose.yml", "deployment_template", "template_only"),
    ("deploy/xiyu-ai.service", "deployment_template", "systemd_template_only"),
    ("deploy/xiyu-ai-backup.service", "deployment_template", "systemd_template_only"),
    ("deploy/xiyu-ai-backup.timer", "deployment_template", "systemd_template_only"),
    ("deploy/nginx.conf.example", "deployment_template", "nginx_template_only"),
    ("deploy/README.md", "deployment_documentation", "documentation_only"),
    ("DEPLOYMENT_PRODUCTION_ALIYUN_XIYU.md", "deployment_documentation", "claimed_runtime_not_locally_observed"),
    ("src/providers/chat.mjs", "production_provider_implementation", "production_reference_only"),
    ("src/providers/image.mjs", "production_provider_implementation", "production_reference_only"),
    ("experiments/ideal-agency-lab/v2/controller/gateway.py", "formal_experiment_gateway", "experiment_implementation"),
    ("experiments/ideal-agency-lab/v2/controller/provider_config.py", "formal_experiment_provider_binding", "explicit_experiment_process_only"),
)

SECRET_FIELD_NAMES = {"api_key", "apikey", "access_token", "refresh_token", "authorization", "password", "secret_value", "credential_value"}
SECRET_PATH_PARTS = {".env", ".pem", ".key", "secret", "credential", "token"}
ENV_LABEL_KEYS = ("CHAT_PROVIDER", "CHAT_MODEL", "MODEL_NAME", "CHAT_MODEL_2", "MODEL_NAME_2", "SECOND_MODEL", "IMAGE_PROVIDER", "IMAGE_MODEL", "VISION_PROVIDER", "VISION_MODEL", "IDEAL_LAB_PROVIDER_NAME", "IDEAL_LAB_PROVIDER_MODEL", "IDEAL_LAB_IMAGE_PROVIDER_NAME", "IDEAL_LAB_IMAGE_MODEL")
ENV_ENDPOINT_KEYS = ("IDEAL_LAB_PROVIDER_ENDPOINT", "IDEAL_LAB_IMAGE_ENDPOINT", "CHAT_ENDPOINT", "MODEL_ENDPOINT", "IMAGE_ENDPOINT", "OPENAI_COMPATIBLE_BASE_URL", "OLLAMA_BASE_URL")
ENV_SECRET_KEYS = ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "MODEL_API_KEY", "IDEAL_LAB_PROVIDER_API_KEY", "IMAGE_API_KEY", "IDEAL_LAB_IMAGE_API_KEY", "VISION_API_KEY")
RESEARCH_SOURCE_FILES = (
    ("docs/agency-research-and-proposal-2026-09-07.md", "agency intent research and proposal"),
    ("docs/proactive-desire-research-2026-09-06.md", "proactive desire research"),
    ("docs/unified-agency-and-engagement-design-2026-09-06.md", "unified agency design reference"),
    ("docs/enterprise-knowledge-routing-2026-09-06.md", "enterprise knowledge routing reference"),
    ("docs/enterprise-continuity-2026-09-06.md", "enterprise continuity reference"),
)
INSTRUCTION_ONLY_FILES = (
    "docs/agency-ideal-lab-execution-plan-v2-2026-09-08.md",
    "docs/agency-ideal-lab-completion-addendum-2026-09-08.md",
)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _write_json_create(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")


def _read_json(path: pathlib.Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _parse_env_keys(path: pathlib.Path) -> dict[str, Any]:
    present: list[str] = []
    nonempty: list[str] = []
    if not path.exists() or not path.is_file():
        return {"status": "absent", "present_keys": [], "nonempty_keys": []}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if line.startswith("export "):
            line = line[7:].lstrip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, raw_value = line.partition("=")
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        present.append(key)
        if raw_value.strip().strip("'\"").strip():
            nonempty.append(key)
    return {"status": "present", "present_keys": sorted(set(present)), "nonempty_keys": sorted(set(nonempty))}


def _process_env_summary() -> dict[str, Any]:
    labels = {key: os.environ.get(key) or None for key in ENV_LABEL_KEYS}
    endpoints = {key: bool(os.environ.get(key)) for key in ENV_ENDPOINT_KEYS}
    secrets = {key: bool(os.environ.get(key)) for key in ENV_SECRET_KEYS}
    return {"labels": labels, "endpoint_presence": endpoints, "secret_presence": secrets}


def _material_record(repo_root: pathlib.Path, relative: str, kind: str, note: str) -> dict[str, Any]:
    path = (repo_root / relative).resolve()
    record: dict[str, Any] = {"path": str(path), "relative": relative, "kind": kind, "note": note}
    if path.exists() and path.is_file():
        record.update({"status": "present", "bytes": path.stat().st_size, "sha256": _sha256(path)})
    else:
        record.update({"status": "absent", "sha256": None})
    return record


def _run_observation(command: list[str], *, timeout: int = 15) -> dict[str, Any]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "error": type(exc).__name__}
    return {
        "available": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": (completed.stdout or "")[-2000:],
        "stderr": (completed.stderr or "")[-2000:],
    }


def investigate_isolation_environment() -> dict[str, Any]:
    """Inventory local isolation candidates without installing or starting one."""
    runtimes: dict[str, Any] = {}
    candidates: list[str] = []
    for name in ("docker", "podman", "wsl"):
        path = shutil.which(name)
        item: dict[str, Any] = {"path": path}
        if path:
            item["version"] = _run_observation([path, "--version"])
            if item["version"].get("available"):
                candidates.append(name)
            if name == "wsl":
                item["distributions"] = _run_observation([path, "--list", "--verbose"])
                item["status"] = _run_observation([path, "--status"])
        else:
            item["version"] = {"available": False, "reason": "command_not_found"}
        runtimes[name] = item
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    services: dict[str, Any] = {"status": "not_observed", "command": None}
    if powershell:
        command = "$ErrorActionPreference='SilentlyContinue'; Get-Service -Name vmcompute,hns | Select-Object Name,Status,StartType | ConvertTo-Json -Compress"
        services = {"status": "observed", "command": _run_observation([powershell, "-NoProfile", "-Command", command])}
    if any(runtimes[name].get("version", {}).get("available") for name in ("docker", "podman")):
        classification = "container_runtime_candidate_present"
    elif runtimes["wsl"].get("path"):
        classification = "wsl_present_unqualified"
    else:
        classification = "no_container_or_vm_runtime_observed"
    return {
        "schemaVersion": "isolation-environment-audit-v1",
        "status": "completed",
        "classification": classification,
        "qualification": "not_qualified_without_independent_worker_policy_and_process_audit",
        "runtimes": runtimes,
        "host_services": services,
        "available_candidates": candidates,
        "side_effects": {"installed": False, "started": False, "stopped": False, "network_probe": False},
        "interpretation": "命令存在只代表候选环境；未安装、未启动、未创建 worker，也没有把 WSL/容器本身当作隔离合格证据。",
    }


def build_local_research_archive(*, repo_root: pathlib.Path, run_root: pathlib.Path) -> dict[str, Any]:
    """Freeze dated local research references while excluding requirement docs."""
    destination = run_root / "research-archive.json"
    if destination.exists():
        existing = _read_json(destination, {})
        existing["reused_immutable_archive"] = True
        return existing
    sources: list[dict[str, Any]] = []
    for relative, applicability in RESEARCH_SOURCE_FILES:
        path = (repo_root / relative).resolve()
        if not path.exists() or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        heading = next((line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("#")), path.stem)
        date_match = re.search(r"20\d{2}-\d{2}-\d{2}", relative) or re.search(r"20\d{2}-\d{2}-\d{2}", text)
        source_refs = sorted(set(re.findall(r"https?://[^\s)]+", text)))
        source_refs.insert(0, relative)
        sources.append({
            "relative_path": relative,
            "path": str(path),
            "title": heading,
            "source_date": date_match.group(0) if date_match else None,
            "sha256": _sha256(path),
            "source_refs": source_refs,
            "applicability": applicability,
            "source_kind": "repository_reference_only",
        })
    archive = {
        "schemaVersion": "research-archive-v1",
        "status": "frozen" if sources else "unavailable",
        "archive_id": f"local-research-{run_root.name}",
        "frozen_at": _now(),
        "source_kind": "repository_reference_only",
        "evidence_level": "local_reference_archive; not an external research authorization",
        "sources": sources,
        "worker_visible": False,
        "applicability": "用于实验设计、验收标准和研究线索的冻结引用；不把需求说明书冒充为研究证据。",
        "excluded_instruction_docs": [{"path": path, "reason": "requirements/instructions, not research evidence"} for path in INSTRUCTION_ONLY_FILES],
    }
    _write_json_create(destination, archive)
    return archive


def materialize_research_archive_for_worker(*, run_root: pathlib.Path, archive: dict[str, Any]) -> dict[str, Any]:
    """Expose archive metadata through the frozen snapshot adapter, not files."""
    context_path = run_root / "snapshot" / "context.json"
    inventory_path = run_root / "inventory.json"
    context = _read_json(context_path, {})
    sources = archive.get("sources") if isinstance(archive.get("sources"), list) else []
    rows = [{
        "archive_id": archive.get("archive_id"),
        "title": source.get("title"),
        "business_date": _now()[:10],
        "source_date": source.get("source_date"),
        "source_ref": f"research://{archive.get('archive_id')}/{source.get('relative_path')}",
        "source_refs": source.get("source_refs", []),
        "applicability": f"{source.get('applicability')}; 当前经营建议仅作研究参考，不是源实例事实。",
        "sha256": source.get("sha256"),
        "status": "frozen_reference",
    } for source in sources]
    for owner_data in (context.get("owners") or {}).values():
        owner_data["research_archive"] = rows
        owner_data["research_status"] = "frozen_local_reference_archive"
        for resource in owner_data.get("catalog", []):
            if resource.get("tool") == "research":
                resource["status"] = "frozen_local_reference_archive"
    context["researchArchive"] = {
        "archive_id": archive.get("archive_id"),
        "status": archive.get("status"),
        "source_count": len(rows),
        "evidence_level": archive.get("evidence_level"),
    }
    context_path.write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    inventory = _read_json(inventory_path, {})
    if isinstance(inventory.get("context_dataset"), dict):
        inventory["context_dataset"]["content_hash"] = _sha256(context_path)
    inventory_path.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return inventory


def audit_source_runtime_readonly(*, run_root: pathlib.Path, url: str) -> dict[str, Any]:
    """GET one documented public health endpoint; never sends credentials."""
    destination = run_root / "source-runtime-readonly.json"
    if destination.exists():
        existing = _read_json(destination, {})
        existing["reused_immutable_observation"] = True
        return existing
    parsed = urlparse(url)
    result: dict[str, Any] = {
        "schemaVersion": "source-runtime-readonly-v1",
        "observedAt": _now(),
        "method": "GET",
        "url": url,
        "host": parsed.hostname,
        "path": parsed.path,
        "readOnly": True,
        "credentials_sent": False,
        "source_identity_authorization": "unverified_public_health_only",
        "provider_availability": "not_probed",
        "confirmed_unavailable_evidence": False,
    }
    if parsed.scheme != "https" or not parsed.hostname or not parsed.path:
        result.update({"status": "invalid_target", "error": "source audit requires an explicit HTTPS URL with a path"})
        _write_json_create(destination, result)
        return result
    import urllib.error
    import urllib.request

    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "ideal-agency-lab-readonly-audit/1"}, method="GET")
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    try:
        opener = urllib.request.build_opener(NoRedirect)
        with opener.open(request, timeout=20) as response:
            body = response.read(128 * 1024)
            status_code = int(response.status)
            content_type = response.headers.get("Content-Type")
        payload = json.loads(body.decode("utf-8"))
        providers = payload.get("providers") if isinstance(payload, dict) else {}
        safe_providers = {}
        for name, value in providers.items() if isinstance(providers, dict) else []:
            if isinstance(value, dict):
                safe_providers[str(name)] = {key: value.get(key) for key in ("id", "label", "model", "configured") if key in value}
        healthy = status_code == 200 and isinstance(payload, dict) and payload.get("ok") is True and payload.get("status") == "running"
        result.update({
            "status": "passed",
            "http_status": status_code,
            "content_type": content_type,
            "health": {"ok": payload.get("ok"), "status": payload.get("status"), "setup_required": payload.get("setup_required")},
            "providers": safe_providers,
            "runtime_availability": "public_health_running" if healthy else "public_health_nonhealthy",
            "interpretation": "HTTP health 只证明公开健康端点在本次 GET 中返回了服务状态；不证明 Aliyun 实例身份、运行目录、账户绑定、隔离 worker 或 provider API 可用。",
        })
    except urllib.error.HTTPError as exc:
        result.update({"status": "passed", "http_status": int(exc.code), "runtime_availability": "public_health_http_error_observed", "error_class": "HTTPError", "interpretation": "观察到健康端点 HTTP 错误，但不能据此把 provider 定性为确实不可用。"})
    except (OSError, ValueError, urllib.error.URLError) as exc:
        result.update({"status": "completed_with_error", "runtime_availability": "public_health_probe_failed", "error_class": type(exc).__name__, "interpretation": "本次只读健康探针未完成；这仍不足以证明 provider 确实不可用。"})
    _write_json_create(destination, result)
    return result


def audit_provider_deployment_materials(*, repo_root: pathlib.Path, run_root: pathlib.Path) -> dict[str, Any]:
    """Read local provider/deployment materials without starting anything."""
    destination = run_root / "provider-deployment-audit.json"
    if destination.exists():
        existing = _read_json(destination, {})
        existing.setdefault("status", "passed")
        existing["reused_immutable_audit"] = True
        return existing
    env_file = _parse_env_keys(repo_root / ".env")
    env_example = _parse_env_keys(repo_root / ".env.example")
    process = _process_env_summary()
    materials = [_material_record(repo_root, relative, kind, note) for relative, kind, note in MATERIALS]
    present = {item["relative"] for item in materials if item["status"] == "present"}
    production_provider_present = bool({"src/providers/chat.mjs", "src/providers/image.mjs"} & present)
    formal_gateway_present = {"experiments/ideal-agency-lab/v2/controller/gateway.py", "experiments/ideal-agency-lab/v2/controller/provider_config.py"}.issubset(present)
    formal_chat_configured = bool(process["labels"].get("IDEAL_LAB_PROVIDER_NAME") and process["labels"].get("IDEAL_LAB_PROVIDER_MODEL") and process["endpoint_presence"].get("IDEAL_LAB_PROVIDER_ENDPOINT") and process["secret_presence"].get("IDEAL_LAB_PROVIDER_API_KEY"))
    production_configured = bool(set(env_file["nonempty_keys"]) & set(ENV_LABEL_KEYS)) or env_file["status"] == "present"
    if formal_chat_configured:
        formal_status = "configured_not_probed"
    elif production_provider_present and formal_gateway_present and production_configured:
        formal_status = "implemented_not_bound"
    else:
        formal_status = "not_integrated"
    result = {
        "schemaVersion": AUDIT_SCHEMA_VERSION,
        "status": "passed",
        "auditedAt": _now(),
        "runId": run_root.name,
        "readOnly": True,
        "side_effects": {"provider_called": False, "production_started": False, "deployment_run": False, "secret_values_recorded": False},
        "materials": materials,
        "environment_files": {".env": env_file, ".env.example": env_example},
        "process_environment": process,
        "isolation_environment": investigate_isolation_environment(),
        "classifications": {
            "production_provider_implementation": "present" if production_provider_present else "absent",
            "production_configuration": "declared_in_local_materials" if production_configured else "not_declared",
            "formal_experiment_gateway": "present" if formal_gateway_present else "absent",
            "formal_experiment_provider_binding": formal_status,
            "runtime_availability": "not_observed",
            "confirmed_unavailable_evidence": False,
            "deployment_runtime": "documented_but_not_locally_observed",
        },
        "interpretation": {
            "implemented_not_bound": "实验 gateway 已实现显式 provider 适配；当前进程没有绑定 IDEAL_LAB_* endpoint/model/credential，因此不能把代码接线当作运行态可用。",
            "confirmed_unavailable": "本次只读资料中没有健康检查/授权探针失败证据，因此不能标记为确实不可用。",
            "next_safe_probe": "提交并校验外部只读身份、隔离 worker、provider/model、凭据范围与费用证据后，再由正式 gateway 做受控探针。",
        },
    }
    _write_json_create(destination, result)
    return result


def _secret_like_path(path: pathlib.Path) -> bool:
    name = path.name.lower()
    if name == ".env.example":
        return False
    if name == ".env" or name.endswith((".pem", ".key")):
        return True
    sensitive_directory_names = {"secret", "secrets", "credential", "credentials", "token", "tokens"}
    return any(part in sensitive_directory_names for part in path.parent.parts if part)


def _contains_secret_value(value: Any, key: str = "") -> bool:
    if isinstance(value, dict):
        return any(_contains_secret_value(item, str(name)) for name, item in value.items())
    if isinstance(value, list):
        return any(_contains_secret_value(item, key) for item in value)
    return key.lower() in SECRET_FIELD_NAMES and isinstance(value, str) and bool(value.strip())


def _facts_complete(condition: str, facts: dict[str, Any]) -> list[str]:
    return [name for name in CONDITION_FACTS.get(condition, ()) if name not in facts or facts.get(name) in (None, "", [], {})]


def _claim_fact_errors(condition: str, facts: dict[str, Any], conditions: dict[str, Any] | None = None) -> list[str]:
    """Reject claims whose values contradict the security/identity contract."""
    errors: list[str] = []
    if condition == "os_or_container_worker":
        for name in ("file_denial", "network_denial", "oracle_denial", "positive_gateway"):
            if facts.get(name) is not True:
                errors.append(f"{name}_must_be_true")
    if condition == "provider_credential":
        if facts.get("credential_scope") != "gateway_only":
            errors.append("credential_scope_must_be_gateway_only")
        if facts.get("credential_presence") is not True:
            errors.append("credential_presence_must_be_true")
        if facts.get("not_in_worker") is not True:
            errors.append("credential_must_not_enter_worker")
    if condition == "second_model_identity" and conditions:
        primary = conditions.get("primary_model_identity") or {}
        if facts.get("model") and facts.get("model") == primary.get("model"):
            errors.append("second_model_must_be_distinct")
        if facts.get("provider") and facts.get("provider") == primary.get("provider") and facts.get("model") == primary.get("model"):
            errors.append("second_provider_model_pair_must_be_distinct")
    if condition == "cost_ceiling":
        if not isinstance(facts.get("max_budget"), (int, float)) or facts.get("max_budget") <= 0:
            errors.append("max_budget_must_be_positive_number")
    if condition == "image_provider" and not isinstance(facts.get("reference_assets"), list):
        errors.append("reference_assets_must_be_list")
    return errors


def _claim_result(condition: str, claim: Any, artifacts: dict[str, dict[str, Any]], conditions: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(claim, dict):
        return {"status": "rejected", "qualifies": False, "reasons": ["claim_not_object"]}
    status = str(claim.get("status", "unverified"))
    reasons: list[str] = []
    if status not in VALID_STATUSES:
        reasons.append("unknown_status")
    facts = claim.get("facts") if isinstance(claim.get("facts"), dict) else {}
    artifact_ids = claim.get("artifact_ids") if isinstance(claim.get("artifact_ids"), list) else []
    if status == "verified":
        if not claim.get("observed_at"):
            reasons.append("observed_at_missing")
        if not claim.get("verification_method"):
            reasons.append("verification_method_missing")
        if not artifact_ids:
            reasons.append("artifact_ids_missing")
        if _facts_complete(condition, facts):
            reasons.append("required_facts_missing:" + ",".join(_facts_complete(condition, facts)))
        missing_artifacts = [str(item) for item in artifact_ids if str(item) not in artifacts]
        if missing_artifacts:
            reasons.append("artifact_not_declared:" + ",".join(missing_artifacts))
        reasons.extend(_claim_fact_errors(condition, facts, conditions))
        for artifact_id in artifact_ids:
            artifact = artifacts.get(str(artifact_id))
            if not artifact or artifact.get("status") != "passed":
                continue
            if artifact.get("condition") != condition:
                reasons.append(f"artifact_condition_mismatch:{artifact_id}")
            if artifact.get("payload_subject") != condition:
                reasons.append(f"artifact_subject_mismatch:{artifact_id}")
            payload_facts = artifact.get("_payload_facts") or {}
            for key in CONDITION_FACTS.get(condition, ()):
                if payload_facts.get(key) != facts.get(key):
                    reasons.append(f"artifact_fact_mismatch:{artifact_id}:{key}")
    elif status == "confirmed_unavailable":
        if not claim.get("observed_at"):
            reasons.append("observed_at_missing")
        if not claim.get("reason"):
            reasons.append("unavailable_reason_missing")
        if not artifact_ids:
            reasons.append("failure_artifact_ids_missing")
    elif status == "not_integrated":
        if not claim.get("reason"):
            reasons.append("not_integrated_reason_missing")
    return {"status": status, "qualifies": status == "verified" and not reasons, "reasons": reasons, "facts": facts, "artifact_ids": artifact_ids}


def validate_evidence_package(*, run_root: pathlib.Path, package: dict[str, Any], package_path: pathlib.Path | None = None) -> dict[str, Any]:
    """Validate schema, artifact hashes, claims and frozen model bindings."""
    reasons: list[str] = []
    if package.get("schemaVersion") != SCHEMA_VERSION:
        reasons.append("schema_version_mismatch")
    if package.get("runId") != run_root.name:
        reasons.append("run_id_mismatch")
    if not package.get("submissionId"):
        reasons.append("submission_id_missing")
    if not package.get("submittedAt"):
        reasons.append("submitted_at_missing")
    if not package.get("issuer"):
        reasons.append("issuer_missing")
    if _contains_secret_value(package):
        reasons.append("secret_value_field_present")
    raw_artifacts = package.get("artifacts") if isinstance(package.get("artifacts"), list) else []
    artifacts: dict[str, dict[str, Any]] = {}
    artifact_results: list[dict[str, Any]] = []
    for raw in raw_artifacts:
        if not isinstance(raw, dict) or not raw.get("id"):
            reasons.append("artifact_id_missing")
            continue
        artifact_id = str(raw["id"])
        if artifact_id in artifacts:
            reasons.append("duplicate_artifact_id:" + artifact_id)
            continue
        artifact_path = pathlib.Path(str(raw.get("path", ""))).expanduser()
        item = {"id": artifact_id, "path": str(artifact_path), "kind": raw.get("kind"), "condition": raw.get("condition"), "status": "rejected"}
        if not raw.get("condition"):
            item["reason"] = "artifact_condition_missing"
            reasons.append("artifact_condition_missing:" + artifact_id)
        elif _secret_like_path(artifact_path):
            item["reason"] = "secret_like_artifact_path"
            reasons.append("secret_like_artifact_path:" + artifact_id)
        elif not artifact_path.exists() or not artifact_path.is_file():
            item["reason"] = "artifact_missing"
            reasons.append("artifact_missing:" + artifact_id)
        elif not re.fullmatch(r"[0-9a-fA-F]{64}", str(raw.get("sha256", ""))):
            item["reason"] = "artifact_sha256_invalid"
            reasons.append("artifact_sha256_invalid:" + artifact_id)
        else:
            actual = _sha256(artifact_path)
            item.update({"expected_sha256": str(raw["sha256"]).lower(), "actual_sha256": actual, "status": "passed" if actual == str(raw["sha256"]).lower() else "rejected"})
            if actual != str(raw["sha256"]).lower():
                item["reason"] = "artifact_hash_mismatch"
                reasons.append("artifact_hash_mismatch:" + artifact_id)
            else:
                payload = _read_json(artifact_path, None)
                if isinstance(payload, dict) and isinstance(payload.get("facts"), dict):
                    item["payload_subject"] = payload.get("subject")
                    item["payload_fact_hash"] = _json_hash(payload.get("facts"))
                    item["_payload_facts"] = payload.get("facts")
                else:
                    item["status"] = "rejected"
                    item["structured_payload"] = False
                    item["reason"] = "structured_evidence_payload_missing"
                    reasons.append("structured_evidence_payload_missing:" + artifact_id)
        artifacts[artifact_id] = item
        artifact_results.append(item)
    claims = package.get("claims") if isinstance(package.get("claims"), dict) else {}
    conditions: dict[str, dict[str, Any]] = {}
    for condition in CONDITION_FACTS:
        conditions[condition] = _claim_result(condition, claims.get(condition, {"status": "not_started"}), artifacts, conditions)
    manifest = _read_json(run_root / "execution-manifest.json", {})
    frozen_models = [item for item in manifest.get("models", []) if isinstance(item, dict)]
    primary = conditions["primary_model_identity"].get("facts", {})
    second = conditions["second_model_identity"].get("facts", {})
    if conditions["primary_model_identity"].get("qualifies") and frozen_models and frozen_models[0].get("label") and frozen_models[0].get("label") != primary.get("model"):
        conditions["primary_model_identity"]["qualifies"] = False
        conditions["primary_model_identity"]["reasons"].append("frozen_primary_model_mismatch")
    if conditions["second_model_identity"].get("qualifies") and len(frozen_models) > 1 and frozen_models[1].get("label") and frozen_models[1].get("label") != second.get("model"):
        conditions["second_model_identity"]["qualifies"] = False
        conditions["second_model_identity"]["reasons"].append("frozen_second_model_mismatch")
    for condition, item in conditions.items():
        if item.get("status") == "verified" and not item.get("qualifies"):
            reasons.append(f"claim_rejected:{condition}")
    status = "passed" if not reasons and all(item.get("status") == "passed" for item in artifact_results) else "rejected"
    safe_artifacts = [{key: value for key, value in item.items() if not key.startswith("_")} for item in artifact_results]
    return {"status": status, "reasons": reasons, "package_path": str(package_path) if package_path else None, "submission_id": package.get("submissionId"), "conditions": conditions, "artifacts": safe_artifacts, "package_hash": _json_hash(package)}


def submit_evidence(*, run_root: pathlib.Path, evidence_path: pathlib.Path) -> dict[str, Any]:
    """Record an immutable evidence submission, including rejected packages."""
    package = _read_json(evidence_path, None)
    if not isinstance(package, dict):
        raise ValueError("evidence package must be a JSON object")
    submission_id = str(package.get("submissionId") or f"rejected-{hashlib.sha256(evidence_path.read_bytes()).hexdigest()[:12]}")
    destination = run_root / "evidence-submissions" / f"{submission_id}.json"
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite existing evidence submission: {destination}")
    validation = validate_evidence_package(run_root=run_root, package=package, package_path=evidence_path)
    record = {"schemaVersion": "evidence-submission-record-v1", "recordedAt": _now(), "source_package": str(evidence_path.resolve()), "package": package, "validation": validation}
    _write_json_create(destination, record)
    return {"status": "accepted" if validation["status"] == "passed" else "rejected", "submission_id": submission_id, "record": str(destination), "validation": validation}


def _scope_result(name: str, conditions: dict[str, dict[str, Any]], required: tuple[str, ...]) -> dict[str, Any]:
    blocked = []
    for condition in required:
        item = conditions.get(condition, {"status": "not_started", "qualifies": False, "reasons": ["claim_missing"]})
        if not item.get("qualifies"):
            blocked.append({"condition": condition, "status": item.get("status", "not_started"), "reasons": item.get("reasons", [])})
    return {"status": "passed" if not blocked else "blocked", "required": list(required), "blocked_by": blocked, "human_review_required": False}


def validate_submitted_evidence(run_root: pathlib.Path) -> dict[str, Any]:
    """Revalidate the latest immutable submission and derive release scopes."""
    paths = sorted((run_root / "evidence-submissions").glob("*.json")) if (run_root / "evidence-submissions").exists() else []
    records = [_read_json(path, {}) for path in paths]
    records = [record for record in records if isinstance(record, dict) and isinstance(record.get("package"), dict)]
    if not records:
        result = {"schemaVersion": "gate-validation-v1", "status": "blocked", "submission_status": "not_submitted", "scopes": {}, "reasons": ["no_evidence_submission"]}
        (run_root / "gate-validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result
    records.sort(key=lambda record: (str(record.get("package", {}).get("submittedAt", "")), str(record.get("package", {}).get("submissionId", ""))))
    latest = records[-1]
    package = latest["package"]
    validation = validate_evidence_package(run_root=run_root, package=package, package_path=pathlib.Path(str(latest.get("source_package", ""))))
    conditions = validation.get("conditions", {})
    sample = _scope_result("sample_generation", conditions, SAMPLE_REQUIREMENTS)
    full_text = _scope_result("full_text_matrix", conditions, FULL_TEXT_REQUIREMENTS)
    image = _scope_result("image_execution", conditions, IMAGE_REQUIREMENTS)
    research = _scope_result("research_execution", conditions, RESEARCH_REQUIREMENTS)
    human = conditions.get("human_review", {"status": "not_started", "qualifies": False, "reasons": ["claim_missing"]})
    final_requirements = list(set(FULL_TEXT_REQUIREMENTS + ("image_provider", "research_archive", "human_review")))
    final = _scope_result("final_subjective_conclusion", conditions, tuple(sorted(final_requirements)))
    final["human_review_required"] = True
    final["policy"] = "human review blocks only final subjective conclusion; it does not block sample generation"
    if validation["status"] != "passed":
        for scope in (sample, full_text, image, research, final):
            scope["status"] = "blocked"
            scope.setdefault("blocked_by", []).insert(0, {"condition": "evidence_submission", "status": validation["status"], "reasons": validation.get("reasons", []) or ["submission_rejected"]})
    models: list[dict[str, Any]] = []
    for role, condition in (("primary", "primary_model_identity"), ("second", "second_model_identity")):
        facts = conditions.get(condition, {}).get("facts", {})
        models.append({"role": role, "label": facts.get("model"), "provider": facts.get("provider"), "status": "evidence_verified" if conditions.get(condition, {}).get("qualifies") else "unverified"})
    image_facts = conditions.get("image_provider", {}).get("facts", {})
    result = {
        "schemaVersion": "gate-validation-v1",
        "validatedAt": _now(),
        "runId": run_root.name,
        "status": "passed" if sample["status"] == "passed" and validation["status"] == "passed" else "blocked",
        "submission_status": validation["status"],
        "submission_id": validation.get("submission_id"),
        "submission_package_hash": validation.get("package_hash"),
        "artifact_validation": validation.get("artifacts", []),
        "conditions": conditions,
        "scopes": {"sample_generation": sample, "full_text_matrix": full_text, "image_execution": image, "research_execution": research, "final_subjective_conclusion": final},
        "resolved_provider": {"models": models, "image": {"provider": image_facts.get("provider"), "model": image_facts.get("model"), "status": "evidence_verified" if conditions.get("image_provider", {}).get("qualifies") else "unverified"}},
        "human_review_policy": {"required_for_sample_generation": False, "required_for_final_subjective_conclusion": True, "current_status": human.get("status", "not_started")},
        "reasons": validation.get("reasons", []) + sample.get("blocked_by", []),
    }
    (run_root / "gate-validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def run_gate_selftest() -> dict[str, Any]:
    """Exercise rejected and accepted submission paths without provider calls."""
    with tempfile.TemporaryDirectory(prefix="ideal-lab-gate-") as temp:
        root = pathlib.Path(temp)
        run_root = root / "run"
        run_root.mkdir()
        (run_root / "execution-manifest.json").write_text(json.dumps({"models": [{"role": "primary", "label": None}, {"role": "second", "label": None}]}) + "\n", encoding="utf-8")
        facts = {
            "source_identity_authorization": {"instance_id": "ecs-test", "runtime_path": "/opt/xiyu-ai", "runtime_version": "test", "account_binding": "account-test", "export_scope": "read-only"},
            "os_or_container_worker": {"worker_kind": "container", "worker_id": "worker-test", "file_denial": True, "network_denial": True, "oracle_denial": True, "positive_gateway": True},
            "primary_model_identity": {"provider": "test-provider", "model": "test-primary", "identity_source": "authorized-test-record"},
            "second_model_identity": {"provider": "test-provider-2", "model": "test-second", "identity_source": "authorized-test-record"},
            "provider_credential": {"credential_scope": "gateway_only", "credential_presence": True, "not_in_worker": True},
            "image_provider": {"provider": "test-image", "model": "test-image-model", "identity_source": "authorized-test-record", "reference_assets": ["asset-test"]},
            "research_archive": {"archive_id": "research-test", "source_date": "2026-09-08", "source_refs": ["research-test-ref"], "applicability": "test"},
            "cost_ceiling": {"currency": "CNY", "max_budget": 1, "price_source": "test-price-sheet", "ceiling_scope": "all"},
        }
        artifacts: list[dict[str, Any]] = []
        for condition, value in facts.items():
            artifact = root / f"{condition}.json"
            artifact.write_text(json.dumps({"subject": condition, "facts": value, "observed_at": "2026-09-08T00:00:00Z"}, ensure_ascii=False) + "\n", encoding="utf-8")
            artifacts.append({"id": f"{condition}-proof", "kind": "gate-test", "condition": condition, "path": str(artifact), "sha256": _sha256(artifact)})
        valid_claims = {condition: {"status": "verified", "observed_at": "2026-09-08T00:00:00Z", "verification_method": "synthetic_gate_selftest", "artifact_ids": [f"{condition}-proof"], "facts": value} for condition, value in facts.items()}

        def package(submission_id: str, *, submitted_at: str = "2026-09-08T00:00:10Z", package_artifacts: list[dict[str, Any]] | None = None, package_claims: dict[str, Any] | None = None) -> dict[str, Any]:
            return {
                "schemaVersion": SCHEMA_VERSION,
                "runId": run_root.name,
                "submissionId": submission_id,
                "submittedAt": submitted_at,
                "issuer": "selftest",
                "artifacts": package_artifacts if package_artifacts is not None else artifacts,
                "claims": package_claims if package_claims is not None else {**valid_claims, "human_review": {"status": "not_started", "reason": "not required for samples"}},
            }

        invalid_cases: dict[str, dict[str, Any]] = {}
        invalid_hash_artifacts = [{**item, "sha256": "0" * 64} for item in artifacts]
        invalid_cases["invalid_hash"] = package("invalid-hash", submitted_at="2026-09-08T00:00:01Z", package_artifacts=invalid_hash_artifacts)

        unrelated_artifact = root / "unrelated-source-proof.json"
        source_payload = {"subject": "source_identity_authorization", "facts": facts["source_identity_authorization"], "observed_at": "2026-09-08T00:00:00Z"}
        unrelated_artifact.write_text(json.dumps(source_payload, ensure_ascii=False) + "\n", encoding="utf-8")
        unrelated_claims = {**valid_claims, "primary_model_identity": {**valid_claims["primary_model_identity"], "artifact_ids": ["unrelated-proof"]}, "human_review": {"status": "not_started", "reason": "not required for samples"}}
        unrelated_artifacts = [{**item} for item in artifacts if item["id"] != "primary_model_identity-proof"] + [{"id": "unrelated-proof", "kind": "gate-test", "condition": "primary_model_identity", "path": str(unrelated_artifact), "sha256": _sha256(unrelated_artifact)}]
        invalid_cases["unrelated_hash"] = package("unrelated-hash", submitted_at="2026-09-08T00:00:02Z", package_artifacts=unrelated_artifacts, package_claims=unrelated_claims)

        false_isolation_facts = {**facts["os_or_container_worker"], "file_denial": False}
        false_isolation_claims = {**valid_claims, "os_or_container_worker": {**valid_claims["os_or_container_worker"], "facts": false_isolation_facts}, "human_review": {"status": "not_started", "reason": "not required for samples"}}
        false_isolation_artifact = root / "false-isolation.json"
        false_isolation_artifact.write_text(json.dumps({"subject": "os_or_container_worker", "facts": false_isolation_facts, "observed_at": "2026-09-08T00:00:00Z"}, ensure_ascii=False) + "\n", encoding="utf-8")
        false_isolation_artifacts = [{**item} for item in artifacts if item["id"] != "os_or_container_worker-proof"] + [{"id": "os_or_container_worker-proof", "kind": "gate-test", "condition": "os_or_container_worker", "path": str(false_isolation_artifact), "sha256": _sha256(false_isolation_artifact)}]
        invalid_cases["isolation_false"] = package("isolation-false", submitted_at="2026-09-08T00:00:03Z", package_artifacts=false_isolation_artifacts, package_claims=false_isolation_claims)

        credential_worker_facts = {**facts["provider_credential"], "not_in_worker": False}
        credential_worker_claims = {**valid_claims, "provider_credential": {**valid_claims["provider_credential"], "facts": credential_worker_facts}, "human_review": {"status": "not_started", "reason": "not required for samples"}}
        credential_worker_artifact = root / "credential-in-worker.json"
        credential_worker_artifact.write_text(json.dumps({"subject": "provider_credential", "facts": credential_worker_facts, "observed_at": "2026-09-08T00:00:00Z"}, ensure_ascii=False) + "\n", encoding="utf-8")
        credential_worker_artifacts = [{**item} for item in artifacts if item["id"] != "provider_credential-proof"] + [{"id": "provider_credential-proof", "kind": "gate-test", "condition": "provider_credential", "path": str(credential_worker_artifact), "sha256": _sha256(credential_worker_artifact)}]
        invalid_cases["credential_in_worker"] = package("credential-in-worker", submitted_at="2026-09-08T00:00:04Z", package_artifacts=credential_worker_artifacts, package_claims=credential_worker_claims)

        rejected_cases: dict[str, dict[str, Any]] = {}
        for case_name, invalid in invalid_cases.items():
            evidence_path = root / f"{case_name}.json"
            evidence_path.write_text(json.dumps(invalid, ensure_ascii=False) + "\n", encoding="utf-8")
            rejected = submit_evidence(run_root=run_root, evidence_path=evidence_path)
            rejected_gate = validate_submitted_evidence(run_root)
            rejected_cases[case_name] = {"status": rejected["status"], "gate_status": rejected_gate["status"], "reasons": rejected_gate.get("reasons", [])}

        valid = package("valid", submitted_at="2026-09-08T00:00:05Z")
        (root / "valid.json").write_text(json.dumps(valid, ensure_ascii=False) + "\n", encoding="utf-8")
        accepted = submit_evidence(run_root=run_root, evidence_path=root / "valid.json")
        accepted_gate = validate_submitted_evidence(run_root)
        return {
            "schemaVersion": "gate-selftest-v1",
            "status": "passed" if all(item["status"] == "rejected" and item["gate_status"] == "blocked" for item in rejected_cases.values()) and accepted["status"] == "accepted" and accepted_gate["scopes"]["sample_generation"]["status"] == "passed" and accepted_gate["scopes"]["final_subjective_conclusion"]["status"] == "blocked" else "failed",
            "rejected_cases": rejected_cases,
            "accepted_submission": {"status": accepted["status"], "sample_generation": accepted_gate["scopes"]["sample_generation"]["status"], "final_subjective_conclusion": accepted_gate["scopes"]["final_subjective_conclusion"]["status"]},
            "human_review_policy_test": "sample_allowed_without_human_review; final_subjective_blocked",
            "provider_calls": 0,
        }
