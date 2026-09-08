"""唯一正式入口：W00 freeze, E0/E1/E2 checks, and evidence collection."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import sys
import uuid
from typing import Any

V2_ROOT = pathlib.Path(__file__).resolve().parent
LAB_ROOT = V2_ROOT.parent
REPO_ROOT = LAB_ROOT.parents[1]
FIXTURE = V2_ROOT / "fixtures" / "public_state.json"
PROMPT = V2_ROOT / "runtime" / "prompts" / "base.json"

if str(V2_ROOT) not in sys.path:
    sys.path.insert(0, str(V2_ROOT))

from controller.gateway import HttpProviderGateway  # noqa: E402
from controller.lifecycle import WorkerLifecycle  # noqa: E402
from evaluation.coverage import build_coverage, write_coverage  # noqa: E402
from evaluation.deterministic import DeterministicSuite  # noqa: E402
from evaluation.harness import HarnessSelftest  # noqa: E402
from evaluation.parity import compare_resource_manifest, compare_sqlite  # noqa: E402
from evaluation.isolation import run_isolation_probe  # noqa: E402
from evaluation.dependencies import check_dependencies  # noqa: E402
from export.discover import create_snapshot, sha256_file  # noqa: E402
from runtime.context import ContextBuilder  # noqa: E402
from runtime.loop import AgencyLoop  # noqa: E402
from runtime.policy import Policy  # noqa: E402
from runtime.store import EventStore  # noqa: E402
from transport.sink import RecordingSink  # noqa: E402


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def json_write(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def hash_paths(paths: list[pathlib.Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: str(item)):
        if not path.exists() or not path.is_file():
            continue
        digest.update(str(path).encode("utf-8")); digest.update(b"\0"); digest.update(path.read_bytes())
    return digest.hexdigest()


def production_hashes() -> dict[str, str | None]:
    paths = [REPO_ROOT / "index.mjs", REPO_ROOT / "package.json", REPO_ROOT / "package-lock.json"]
    paths.extend(path for root in (REPO_ROOT / "src", REPO_ROOT / "config") if root.exists() for path in root.rglob("*") if path.is_file())
    return {str(path.relative_to(REPO_ROOT)): sha256_file(path) if path.exists() else None for path in sorted(paths)}


def unique_run_path() -> pathlib.Path:
    LAB_ROOT.joinpath("runs").mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return LAB_ROOT / "runs" / f"{stamp}-{uuid.uuid4().hex[:8]}"


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
    goals = {
        "G01": "desire changes appraisal while facts remain stable", "G02": "model action parameters drive actual tools", "G03": "professional and personal expression coexist", "G04": "concrete initiative under low response", "G05": "persona fiction can support interaction", "G06": "scoped fresh business facts", "G07": "enterprise background affects analysis", "G08": "knowledge candidate to confirmed reuse", "G09": "understood goal leads to independent preparation", "G10": "research becomes executable task", "G11": "media is a strategy branch", "G12": "continuity survives delivery and restart", "G13": "feedback is evidence, not blind learning", "G14": "one maintainable and migratable path",
    }
    families = [f"{group}{i:02d}" for group in "ABCD" for i in range(1, 7)]
    return {
        "schemaVersion": "requirement-map-v2", "createdAt": utc_now(),
        "goals": {key: {"requirement": value, "status": "not_run", "fixture_branches": ["planned_branch:" + key], "evidence": []} for key, value in goals.items()},
        "families": {key: {"status": "not_run", "branches": ["normal", "failure", "recovery"], "evidence": []} for key in families},
        "reliability": {f"R{i:02d}": {"status": "not_run", "fixture_branches": ["normal", "failure", "recovery"], "evidence": []} for i in range(1, 13)},
        "integration": {f"I{i:02d}": {"status": "not_run", "fixture_branches": ["normal", "failure", "recovery"], "evidence": []} for i in range(1, 13)},
        "mutations": {key: {"status": "not_run", "normal_control": None, "failure_evidence": None} for key in [f"M{i:02d}" for i in range(1, 17)] + [f"X{i:02d}" for i in range(1, 25)]},
    }


def component_map() -> dict[str, Any]:
    return {
        "schemaVersion": "component-map-v2",
        "root": str(V2_ROOT) if "V2_ROOT" in globals() else "experiments/ideal-agency-lab/v2",
        "unique_cli": "cli.py",
        "components": {
            "controller": ["boundary.py", "gateway.py", "lifecycle.py"], "export": ["discover.py"],
            "contracts": ["schemas.py"], "runtime": ["context.py", "loop.py", "policy.py", "store.py", "prompts/assemble.py", "prompts/base.json"],
            "adapters": ["local.py"], "transport": ["sink.py"], "fixtures": ["public_state.json"],
            "evaluation": ["coverage.py", "deterministic.py", "evidence.py", "harness.py", "isolation.py", "parity.py"], "tests": ["__init__.py"],
        },
        "formal_path": "cli.py -> controller -> contracts -> runtime/context -> runtime/loop -> adapters/transport -> runtime/store -> evaluation",
        "production_reference_only": ["src/", "config/", "index.mjs", "scripts/lab_*.py", "scripts/lab_*.mjs"],
    }


def freeze(args: argparse.Namespace) -> pathlib.Path:
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
    v2_files = [path for path in V2_ROOT.rglob("*") if path.is_file() and "runs" not in path.parts]
    json_write(run_root / "manifest.json", {
        "schemaVersion": "ideal-agency-lab-manifest-v2", "createdAt": utc_now(), "runId": run_root.name,
        "mode": args.mode, "code_root": str(V2_ROOT), "code_hash": hash_paths(v2_files), "fixture_hash": sha256_file(FIXTURE),
        "prompt_hash": sha256_file(PROMPT), "model": None, "provider": None, "status": "frozen_before_behavior",
        "production_mutation_policy": {"src": "forbidden", "config": "forbidden", "index.mjs": "forbidden", "package": "forbidden", "delivery": "sink_only"},
    })
    json_write(run_root / "production-integrity-before.json", {"status": "captured", "files": production_hashes()})
    json_write(run_root / "requirement-map.json", requirement_map())
    json_write(run_root / "source-module-map.json", source_module_map())
    json_write(run_root / "component-map.json", component_map())
    config_path = REPO_ROOT / "config" / "agency-prompts.v1.json"
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    json_write(run_root / "config-synthesis.json", {"source": str(config_path), "sha256": sha256_file(config_path) if config_path.exists() else None, "blocks": [{"name": name, "type": type(value).__name__, "chars": len(json.dumps(value, ensure_ascii=False)), "value_hash": hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()} for name, value in config.items()]})
    json_write(run_root / "archive-index.json", {"schemaVersion": "legacy-archive-index-v2", "status": "reference_only", "legacy_runners": [str(path) for path in sorted((REPO_ROOT / "scripts").glob("lab_*"))], "legacy_runs": [str(path) for path in sorted((LAB_ROOT / "runs").glob("*"))], "formal_runner": str(V2_ROOT / "cli.py")})
    json_write(run_root / "environment.json", {"status": "pending", "mode": args.mode, "source_authorization": "not independently verified in this run", "e0": "pending", "e1": "pending", "e2": "pending", "e3": "not_started"})
    json_write(run_root / "isolation.json", {"status": "pending_boundary_probe", "worker_root": str(run_root / "worker"), "snapshot_readonly_intent": True, "oracle_readable_by_worker": False, "real_delivery_enabled": False, "network_allowlist": [], "production_write_attempts": []})
    json_write(run_root / "lifecycle.json", {"status": "created", "run_id": run_root.name, "started_at": utc_now(), "processes": [], "cleanup": "pending"})
    write_coverage(run_root / "coverage.json", build_coverage(evidence_root=str(run_root)))
    json_write(run_root / "cost-plan.json", {"status": "smoke_estimate_pending", "currency": "unknown", "fixed_suite": {"models": 2, "families": 24, "repetitions": 5}, "holdout": {"scenes_per_model": 12, "repetitions": 3}, "image_count_minimum": 6, "performance_requests_per_arm": 30})
    json_write(run_root / "cost-latency.json", {"status": "not_started", "attempts": []})
    json_write(run_root / "issues.json", [])
    json_write(run_root / "scores.jsonl", [])
    json_write(run_root / "human-review.json", {"status": "not_started", "required": 12})
    (run_root / "report.md").write_text("# Ideal Agency Lab v2\n\n状态：`inconclusive`（W00 冻结完成，行为与完整验收尚未完成）。\n\n- 不修改生产代码/配置。\n- 不发送真实 Bot。\n- 旧 lab runner 仅登记为历史参照。\n", encoding="utf-8")
    (run_root / "reproduce.md").write_text(f"# Reproduce\n\nRun: `{run_root}`\n\n```powershell\npython {V2_ROOT / 'cli.py'} selftest --run {run_root}\npython {V2_ROOT / 'cli.py'} e0 --run {run_root}\n```\n", encoding="utf-8")
    (run_root / "limitations.md").write_text("# Limitations\n\n本 run 还没有完成线上授权关系证明、完整复制对账、真实 provider 冒烟、24 族、留出、第二模型、真实图片审图、性能、人审或生产入口验收。\n", encoding="utf-8")
    print(json.dumps({"status": "frozen", "run": str(run_root), "resources": len(inventory.get("resources", [])), "mode": args.mode}, ensure_ascii=False))
    return run_root


def run_e0(run_root: pathlib.Path) -> dict[str, Any]:
    inventory = json.loads((run_root / "inventory.json").read_text(encoding="utf-8"))
    source_db = pathlib.Path(inventory["source"]["sourceDb"]["main"]["locator"])
    replica_db = pathlib.Path(inventory["replica"]["database"])
    sqlite_result = compare_sqlite(source_db, replica_db, transformations=inventory.get("transformations", []))
    manifest_result = compare_resource_manifest(inventory, run_root)
    result = {"status": "passed" if sqlite_result["status"] == "passed" and manifest_result["status"] == "passed" else "failed", "sqlite": sqlite_result, "manifest": manifest_result}
    result["source_locator"] = str(source_db); result["replica_locator"] = str(replica_db)
    json_write(run_root / "replica-parity.json", result)
    environment_path = run_root / "environment.json"; environment = json.loads(environment_path.read_text(encoding="utf-8")); environment["e0"] = result["status"] if inventory["source"].get("authorization_status") == "verified" else "inconclusive_source_identity_unverified"; json_write(environment_path, environment)
    refresh_integrity(run_root)
    refresh_report(run_root)
    return result


def run_e1(run_root: pathlib.Path) -> dict[str, Any]:
    result = run_isolation_probe(run_root, REPO_ROOT)
    environment_path = run_root / "environment.json"; environment = json.loads(environment_path.read_text(encoding="utf-8")) if environment_path.exists() else {}; environment["e1"] = result["status"]; json_write(environment_path, environment)
    refresh_integrity(run_root)
    refresh_report(run_root)
    return result


def run_dependency_check(run_root: pathlib.Path) -> dict[str, Any]:
    result = check_dependencies(V2_ROOT)
    json_write(run_root / "dependency-check.json", result)
    json_write(run_root / "component-map.json", component_map())
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
    environment = json.loads((run_root / "environment.json").read_text(encoding="utf-8")) if (run_root / "environment.json").exists() else {}
    selftest = json.loads((run_root / "selftest.json").read_text(encoding="utf-8")) if (run_root / "selftest.json").exists() else {}
    e2 = json.loads((run_root / "e2-deterministic.json").read_text(encoding="utf-8")) if (run_root / "e2-deterministic.json").exists() else {}
    parity = json.loads((run_root / "replica-parity.json").read_text(encoding="utf-8")) if (run_root / "replica-parity.json").exists() else {}
    integrity = json.loads((run_root / "production-integrity-after.json").read_text(encoding="utf-8")) if (run_root / "production-integrity-after.json").exists() else {}
    hard_failed = selftest.get("status") == "failed" or e2.get("status") == "failed" or parity.get("status") == "failed" or integrity.get("status") == "failed"
    overall = "failed" if hard_failed else "inconclusive"
    environment["status"] = overall
    json_write(run_root / "environment.json", environment)
    lines = ["# Ideal Agency Lab v2", "", f"总体状态：`{overall}`", "", "## 阶段", "", f"- W00 freeze：completed（run `{run_root.name}`）", f"- E0 replica parity：{parity.get('status', 'not_run')}；源身份：{environment.get('e0', 'not_run')}", f"- E1 isolation：{environment.get('e1', 'not_run')}（OS/container qualification required）", f"- E2 deterministic contracts：{environment.get('e2', 'not_run')}；selftest：{selftest.get('passed', 0)}/{selftest.get('total', 0)}", f"- Production integrity：{integrity.get('status', 'not_run')}", "- E3 real API smoke：not_started / gated", "", "## 明确未完成", "", "- 阿里云有效实例/授权关系链独立核验与线上只读导出。", "- 可验证的 OS/container worker 隔离与独立 provider gateway。", "- 真实 API E3、24 族固定套件、第二模型、留出、图片审图、7 日连续性、性能与人工盲评。", "- 生产入口、真实 Bot 投递、部署与线上观察（本轮不在授权范围）。", "", "生产代码、配置、依赖与真实 Bot 均未由本实验写入。"]
    (run_root / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_smoke(run_root: pathlib.Path, args: argparse.Namespace) -> dict[str, Any]:
    environment = json.loads((run_root / "environment.json").read_text(encoding="utf-8")) if (run_root / "environment.json").exists() else {}
    gate = {key: environment.get(key) for key in ("e0", "e1", "e2")}
    if gate != {"e0": "passed", "e1": "passed", "e2": "passed"}:
        result = {"status": "inconclusive", "reason": "E0/E1/E2 gate is not qualified; real provider call was blocked", "gate": gate}
        environment["e3"] = "gated"; json_write(run_root / "environment.json", environment); json_write(run_root / "smoke-result.json", result); refresh_integrity(run_root); refresh_report(run_root); return result
    if not args.endpoint:
        result = {"status": "inconclusive", "reason": "provider endpoint not supplied; no real API call made", "mode": "FROZEN"}
        environment["e3"] = "not_started_no_endpoint"; json_write(run_root / "environment.json", environment); json_write(run_root / "smoke-result.json", result); refresh_integrity(run_root); refresh_report(run_root); return result
    # Credentials are read only from the process environment and never emitted.
    import os
    endpoint = args.endpoint
    from controller.boundary import NetworkBoundary
    from urllib.parse import urlparse
    parsed_endpoint = urlparse(endpoint)
    network = NetworkBoundary({parsed_endpoint.hostname or ""}, {parsed_endpoint.path})
    gateway = HttpProviderGateway(model_name=args.model, endpoint=endpoint, network_boundary=network, api_key=os.environ.get("IDEAL_LAB_PROVIDER_API_KEY"))
    trajectory = run_root / "smoke-trajectories" / "provider"
    trajectory.mkdir(parents=True, exist_ok=True)
    from adapters.local import LocalAdapters
    store = EventStore(trajectory / "state.db"); sink = RecordingSink(trajectory / "traces" / "sink.jsonl"); loop = AgencyLoop(store=store, context=ContextBuilder(FIXTURE, PROMPT), adapters=LocalAdapters(FIXTURE), policy=Policy(store, writable_root=trajectory), gateway=gateway, sink=sink, trace_path=trajectory / "traces" / "trace.jsonl")
    event = {"event_id": "smoke-provider-001", "owner": "owner-a", "kind": "user_message", "virtual_time": "2026-09-08T10:00:00+08:00", "payload": {"text": "请直接处理当前问题并给出有依据的结果"}}
    result = loop.process_event(event); store.close(); environment["e3"] = "completed"; json_write(run_root / "environment.json", environment); json_write(run_root / "smoke-result.json", {"status": "completed", "result": result, "model": args.model, "endpoint_host": network.allowed_hosts}); refresh_integrity(run_root); refresh_report(run_root)
    return result


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Ideal Agency Lab v2 formal runner")
    sub = ap.add_subparsers(dest="command", required=True)
    freeze_cmd = sub.add_parser("freeze"); freeze_cmd.add_argument("--source-db", default=str(REPO_ROOT / "data" / "bot.db")); freeze_cmd.add_argument("--workbench", default=r"E:\Yuanqu-Operations-Workbench\weekly-ops-entry"); freeze_cmd.add_argument("--mode", choices=["EXPORT", "FROZEN", "LIVE-READONLY"], default="FROZEN"); freeze_cmd.add_argument("--run", default="")
    for name in ("e0", "e1", "selftest", "e2", "deps", "report"):
        cmd = sub.add_parser(name); cmd.add_argument("--run", required=True)
    smoke = sub.add_parser("smoke"); smoke.add_argument("--run", required=True); smoke.add_argument("--endpoint", default=""); smoke.add_argument("--model", default="configured-model")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "freeze": freeze(args); return 0
    run_root = pathlib.Path(args.run).resolve()
    if not run_root.exists(): raise SystemExit(f"run not found: {run_root}")
    if args.command == "e0": print(json.dumps(run_e0(run_root), ensure_ascii=False)); return 0
    if args.command == "e1": print(json.dumps(run_e1(run_root), ensure_ascii=False)); return 0
    if args.command == "selftest": print(json.dumps(run_selftest(run_root), ensure_ascii=False)); return 0
    if args.command == "e2": print(json.dumps(run_e2(run_root), ensure_ascii=False)); return 0
    if args.command == "deps": print(json.dumps(run_dependency_check(run_root), ensure_ascii=False)); return 0
    if args.command == "smoke": print(json.dumps(run_smoke(run_root, args), ensure_ascii=False)); return 0
    if args.command == "report":
        refresh_integrity(run_root); refresh_report(run_root)
        status = "inconclusive"; selftest = run_root / "selftest.json"; parity = run_root / "replica-parity.json"
        if selftest.exists() and json.loads(selftest.read_text(encoding="utf-8")).get("status") == "failed": status = "failed"
        if parity.exists() and json.loads(parity.read_text(encoding="utf-8")).get("status") == "failed": status = "failed"
        print(json.dumps({"status": status, "run": str(run_root), "evidence": [str(path) for path in (selftest, parity) if path.exists()]}, ensure_ascii=False)); return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
