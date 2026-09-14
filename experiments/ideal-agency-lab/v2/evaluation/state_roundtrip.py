"""C03 durable task and knowledge state round-trip checks."""
from __future__ import annotations

import json
import pathlib
from typing import Any

from adapters.local import LocalAdapters
from runtime.store import EventStore


def run_state_roundtrip(run_root: pathlib.Path) -> dict[str, Any]:
    manifest_path = run_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    snapshot = run_root / "snapshot"
    context = json.loads((snapshot / "context.json").read_text(encoding="utf-8"))
    owners = sorted(context.get("owners", {}).keys())
    if not owners:
        result = {"schemaVersion": "state-roundtrip-v1", "status": "incomplete", "reason": "snapshot has no bound owner"}
        (run_root / "state-roundtrip.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result
    owner = owners[0]
    db = run_root / "state-roundtrip" / "state.db"
    store = EventStore(db)
    adapter = LocalAdapters(snapshot_root=snapshot, manifest_path=manifest_path, store=store)
    task_read = adapter.execute(owner, "tasks.read", {})
    task_rows = task_read.get("data") or []
    task_result: dict[str, Any] = {"status": "incomplete", "reason": "no task in bound snapshot"}
    if task_rows:
        task = task_rows[0]
        update_args = {"task_id": task["id"], "status": "completed", "expected_version": task.get("version", 0), "idempotency_key": f"state-roundtrip:{task['id']}:complete"}
        updated = adapter.execute(owner, "tasks.update", update_args)
        replay = adapter.execute(owner, "tasks.update", update_args)
        visible = adapter.execute(owner, "tasks.read", {"status": "completed"})
        task_result = {"status": "passed" if updated["status"] == "complete" and replay["status"] == "complete" and replay["data"].get("idempotent_replay") is True and any(item["id"] == task["id"] for item in visible.get("data", [])) else "failed", "before": task, "update": updated, "idempotent_replay": replay, "after": visible}
    proposed = adapter.execute(owner, "knowledge.propose", {"candidate": "隔离候选：该资料需要用户确认后才能作为正式知识", "scope": owner})
    candidate = proposed.get("data", {})
    candidate_id = candidate.get("candidate_id")
    denied = adapter.execute(owner, "knowledge.confirm", {"candidate_id": candidate_id, "authorized": True})
    rejected_proposal = adapter.execute(owner, "knowledge.propose", {"candidate": "拒绝候选：不能进入正式知识", "scope": owner})
    rejected_id = rejected_proposal.get("data", {}).get("candidate_id")
    store.record_user_confirmation(owner, rejected_id, "state-roundtrip-rejection", "这条不确认", False)
    rejected = adapter.execute(owner, "knowledge.confirm", {"candidate_id": rejected_id, "authorized": True})
    store.record_user_confirmation(owner, candidate_id, "state-roundtrip-confirmation", "我确认把这条信息作为正式知识", True)
    confirmed = adapter.execute(owner, "knowledge.confirm", {"candidate_id": candidate_id, "authorized": True})
    research = adapter.execute(owner, "research", {"query": "当前经营建议", "business_date": "2026-09-08"})
    media = adapter.execute(owner, "media.prepare", {"asset_path": str(run_root / "state-roundtrip" / "missing-image.png")})
    store.close()
    reopened = EventStore(db)
    reopened_adapter = LocalAdapters(snapshot_root=snapshot, manifest_path=manifest_path, store=reopened)
    reused = reopened_adapter.execute(owner, "knowledge.search", {"query": "隔离候选"})
    knowledge_status = "passed" if denied["status"] == "forbidden" and rejected["status"] == "forbidden" and confirmed["status"] == "complete" and any(item.get("status") == "confirmed" for item in reused.get("data", [])) else "failed"
    tables = [row[0] for row in reopened.conn.execute("select name from sqlite_master where type='table' and name in ('isolated_tasks','knowledge_candidates','user_confirmations') order by name")]
    reopened.close()
    offline_status = "passed" if task_result["status"] == "passed" and knowledge_status == "passed" else "failed"
    real_api_calls = 0
    capability_status = "passed" if research["status"] == "complete" and media["status"] in {"failed", "unavailable"} else "failed"
    result = {
        "schemaVersion": "state-roundtrip-v1", "status": "incomplete" if offline_status == "passed" and real_api_calls == 0 else offline_status,
        "offline_persistence_status": offline_status,
        "completion_blocker": "C03 additionally requires the real multi-turn API trajectory" if real_api_calls == 0 else None,
        "owner": owner, "task_roundtrip": task_result, "knowledge_roundtrip": {"proposal": proposed, "unauthorized_model_arg_attempt": denied, "rejected_confirmation": rejected, "confirmation": confirmed, "reopened_reuse": reused, "status": knowledge_status},
        "capability_roundtrip": {"research": research, "media": media, "status": capability_status, "note": "research uses the executor-frozen local reference archive; media missing-asset failure remains an explicit negative path"},
        "durable_tables": tables, "restart_verified": True, "single_store": str(db), "real_api_calls": real_api_calls,
        "note": "Model-supplied authorized=true is ignored; only the controller-recorded user confirmation can confirm the candidate.",
    }
    (run_root / "state-roundtrip.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return result


def merge_provider_evidence(run_root: pathlib.Path, trace_roots: list[pathlib.Path]) -> dict[str, Any]:
    """Promote C03 only after a real multi-event trace changes isolated state."""
    path = run_root / "state-roundtrip.json"
    result = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"offline_persistence_status": "failed"}
    provider_calls = 0
    event_ids: set[str] = set()
    trace_paths: list[str] = []
    confirmed_candidates = 0
    for root in trace_roots:
        for trace_path in sorted(root.rglob("trace.jsonl")):
            trace_paths.append(str(trace_path))
            for line in trace_path.read_text(encoding="utf-8").splitlines():
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if item.get("kind") == "provider_call":
                    provider_calls += 1
                if item.get("event_id"):
                    event_ids.add(str(item["event_id"]))
        for db_path in sorted(root.rglob("state.db")):
            try:
                store = EventStore(db_path)
                confirmed_candidates += int(store.conn.execute("SELECT COUNT(*) FROM knowledge_candidates WHERE status='confirmed'").fetchone()[0])
                store.close()
            except Exception:
                continue
    result["api_evidence"] = {"trace_paths": trace_paths, "provider_calls": provider_calls, "distinct_events": len(event_ids), "confirmed_candidates": confirmed_candidates}
    result["real_api_calls"] = provider_calls
    qualified = result.get("offline_persistence_status") == "passed" and provider_calls > 0 and len(event_ids) >= 3 and confirmed_candidates > 0
    result["status"] = "passed" if qualified else "incomplete"
    result["completion_blocker"] = None if qualified else "C03 requires a real multi-event API trajectory with confirmed isolated state and restart evidence"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return result
