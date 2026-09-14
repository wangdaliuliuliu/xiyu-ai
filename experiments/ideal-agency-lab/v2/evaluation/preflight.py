"""C00 preflight evidence.

The preflight records facts that can be observed from the current machine.  It
does not infer cloud authorization, provider identity, or OS isolation from a
file path or an environment variable name.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
from typing import Any


def _run(command: list[str], cwd: pathlib.Path | None = None) -> dict[str, Any]:
    try:
        completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "error": type(exc).__name__}
    return {
        "available": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": (completed.stdout or "")[-2000:],
        "stderr": (completed.stderr or "")[-2000:],
    }


def _hash(path: pathlib.Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_fact(path: pathlib.Path) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.exists():
        return {"locator": str(resolved), "status": "absent"}
    return {"locator": str(resolved), "status": "present", "bytes": resolved.stat().st_size, "sha256": _hash(resolved)}


def _git_fact(repo: pathlib.Path) -> dict[str, Any]:
    return {
        "root": str(repo.resolve()),
        "status": _run(["git", "status", "--short"], repo),
        "branch": _run(["git", "branch", "--show-current"], repo),
        "head": _run(["git", "rev-parse", "HEAD"], repo),
        "worktrees": _run(["git", "worktree", "list"], repo),
    }


def _configured_names() -> dict[str, Any]:
    # Values are restricted to non-secret provider/model labels.  API keys and
    # tokens are represented only by a boolean presence flag.
    label_keys = ("CHAT_PROVIDER", "CHAT_MODEL", "MODEL_NAME", "MODEL_NAME_2", "CHAT_MODEL_2", "SECOND_MODEL", "IMAGE_PROVIDER", "IMAGE_MODEL", "VISION_PROVIDER", "VISION_MODEL", "RESEARCH_PROVIDER", "IDEAL_LAB_PROVIDER_NAME", "IDEAL_LAB_PROVIDER_MODEL", "IDEAL_LAB_IMAGE_PROVIDER_NAME", "IDEAL_LAB_IMAGE_MODEL")
    secret_keys = ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "MODEL_API_KEY", "IDEAL_LAB_PROVIDER_API_KEY", "IMAGE_API_KEY", "IDEAL_LAB_IMAGE_API_KEY", "VISION_API_KEY")
    labels = {key: os.environ.get(key) or None for key in label_keys}
    return {
        "labels": labels,
        "secret_presence": {key: bool(os.environ.get(key)) for key in secret_keys},
        "primary_model_declared": bool(labels.get("CHAT_MODEL") or labels.get("MODEL_NAME")),
        "second_model_declared": bool(labels.get("CHAT_MODEL_2") or labels.get("MODEL_NAME_2") or labels.get("SECOND_MODEL")),
    }


def collect_preflight(*, repo_root: pathlib.Path, run_root: pathlib.Path, source_db: pathlib.Path, workbench_root: pathlib.Path) -> dict[str, Any]:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    source_db = source_db.resolve()
    workbench_root = workbench_root.resolve()
    runtimes = {name: {"path": shutil.which(name), "version": _run([name, "--version"]) if shutil.which(name) else {"available": False}}
                for name in ("docker", "podman", "wsl")}
    source_evidence = {
        "source_db": _file_fact(source_db),
        "wal": _file_fact(pathlib.Path(str(source_db) + "-wal")),
        "shm": _file_fact(pathlib.Path(str(source_db) + "-shm")),
        "workbench_root": {"locator": str(workbench_root), "status": "present" if workbench_root.exists() else "absent"},
        "workbench_data": {"locator": str(workbench_root / "data"), "status": "present" if (workbench_root / "data").exists() else "absent"},
        "workbench_assets": {"locator": str(workbench_root / "assets"), "status": "present" if (workbench_root / "assets").exists() else "absent"},
        "source_authorization": {
            "status": "unverified_local_source",
            "evidence": "local path and read access only",
            "missing": ["authorized Aliyun instance identity", "runtime directory/version proof", "account binding authorization", "export scope approval chain"],
        },
    }
    model = _configured_names()
    missing: list[dict[str, Any]] = []
    if source_evidence["source_authorization"]["status"] != "verified":
        missing.append({"stage": "E0", "condition": "source_identity_authorization", "reason": "only local source path was observed"})
    if not (runtimes["docker"]["path"] or runtimes["podman"]["path"]):
        missing.append({"stage": "E1", "condition": "os_or_container_worker", "reason": "docker and podman are unavailable; WSL presence is not proof of a constrained worker"})
    if not model["primary_model_declared"]:
        missing.append({"stage": "E3+", "condition": "primary_model_identity", "reason": "no non-secret model label is declared in this process"})
    if not model["second_model_declared"]:
        missing.append({"stage": "E5", "condition": "second_model_identity", "reason": "no second model label is declared in this process"})
    if not model["secret_presence"].get("IDEAL_LAB_PROVIDER_API_KEY") and not any(model["secret_presence"].get(key) for key in ("OPENAI_API_KEY", "MODEL_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY")):
        missing.append({"stage": "E3", "condition": "provider_credential", "reason": "no provider credential presence is available to the isolated gateway"})
    if not model["labels"].get("IMAGE_PROVIDER") or not model["labels"].get("IMAGE_MODEL"):
        missing.append({"stage": "E6", "condition": "image_provider", "reason": "authorized image provider and model are not independently declared"})
    research_archive_path = run_root / "research-archive.json"
    research_archive = {}
    if research_archive_path.exists():
        try:
            research_archive = json.loads(research_archive_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            research_archive = {"status": "invalid"}
    if research_archive.get("status") != "frozen":
        missing.append({"stage": "E6", "condition": "research_archive", "reason": "no independently frozen dated research archive with source metadata is available"})
    missing.extend([
        {"stage": "E3+", "condition": "cost_ceiling", "reason": "official price/available budget ceiling is not verified in this run"},
        {"stage": "E7", "condition": "human_review", "reason": "P1 confirmation and required blind-review participants/materials are not supplied"},
    ])
    result = {
        "schemaVersion": "completion-preflight-v1",
        "recordedAt": now,
        "runId": run_root.name,
        "repository": _git_fact(repo_root),
        "source": source_evidence,
        "isolation": {"status": "inconclusive", "runtimes": runtimes, "worker_process_proof": False, "network_gateway_proof": False},
        "model": model,
        "image_and_research": {"status": "unverified", "image_provider_declared": bool(model["labels"].get("IMAGE_PROVIDER")), "research_archive": research_archive.get("status", "not independently frozen"), "research_archive_path": str(research_archive_path)},
        "cost": {"status": "unknown", "estimate": "not calculated from an authorized provider price sheet", "unlimited_calls": False},
        "review": {"status": "not_ready", "required_final_blind_review_items": 12, "blocks": "final_subjective_conclusion_only", "does_not_block": "sample_generation_or_automated_tests"},
        "missing_external_evidence": missing,
        "minimum_unblock_actions": [
            {"condition": "source_identity_authorization", "action": "provide read-only authorized instance/runtime/version, account binding, and export-scope evidence", "unblocks": ["E0"]},
            {"condition": "os_or_container_worker", "action": "provide an independently constrained worker/VM/container and gateway network policy with process audit", "unblocks": ["E1"]},
            {"condition": "provider_credential", "action": "make an authorized gateway credential available only to the gateway process and declare endpoint/model identities", "unblocks": ["E3"]},
            {"condition": "second_model_identity", "action": "declare and authorize a distinct second model/provider; do not substitute the primary", "unblocks": ["E5"]},
            {"condition": "image_provider", "action": "provide authorized image provider/model and identity-reference assets", "unblocks": ["E6"]},
            {"condition": "research_archive", "action": "provide a separately frozen dated research archive with source and applicability metadata", "unblocks": ["C03", "C06"]},
            {"condition": "cost_ceiling", "action": "provide official price sheet and an explicit maximum budget matching the frozen denominator", "unblocks": ["E3+", "E6"]},
            {"condition": "human_review", "action": "provide P1 confirmation and the required blind-review participants/materials", "unblocks": ["E7", "W10"]},
        ],
        "execution": {"offline_development_allowed": True, "real_api_main_group_allowed": False, "sample_generation_requires_human_review": False, "final_subjective_conclusion_requires_human_review": True, "deployment_allowed": False, "real_bot_delivery_allowed": False},
        "status": "completed_with_external_gates",
    }
    cost_plan_path = run_root / "cost-plan.json"
    if cost_plan_path.exists():
        try:
            cost_plan = json.loads(cost_plan_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cost_plan = {}
        if cost_plan.get("estimated_model_calls"):
            result["cost"].update({
                "status": "unknown_price_with_call_envelope",
                "plan_path": str(cost_plan_path),
                "estimated_model_calls": cost_plan["estimated_model_calls"],
            })
    (run_root / "completion-preflight.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = ["# C00 开工前置核验", "", f"状态：`{result['status']}`", "", "## 可继续的工作", "", "- 独立 v2 实验代码、快照上下文、状态回环、离线验收器和清单生成。", "- 真实 API 前置门禁以前置证据为准，不能手工改状态解锁。", "", "## 已查明缺项", ""]
    summary.extend(f"- `{item['stage']}` `{item['condition']}`：{item['reason']}" for item in missing)
    summary.extend(["", "## 最小解阻操作", ""])
    summary.extend(f"- `{item['condition']}`：{item['action']} → `{', '.join(item['unblocks'])}`" for item in result["minimum_unblock_actions"])
    if result["cost"].get("estimated_model_calls"):
        envelope = result["cost"]["estimated_model_calls"]
        summary.extend(["", "## 预估调用包络", "", f"- 模型调用下界 `{envelope['lower_bound']}`；重试前上界 `{envelope['upper_bound_before_retry']}`；含重试保守上界 `{envelope['provider_requests_upper_bound']}`。", "- 价格、额度和正式上限仍为 unknown；不得将此估算当作免费额度。"])
    summary.extend(["", "## 约束", "", "- 本轮不修改生产 src/config/index.mjs/package，不启动生产调度器，不部署，不投递真实 Bot。", "- 本地路径存在不等于阿里云源授权已证明；WSL 命令存在不等于 OS 隔离已合格。"])
    (run_root / "completion-preflight.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    return result
