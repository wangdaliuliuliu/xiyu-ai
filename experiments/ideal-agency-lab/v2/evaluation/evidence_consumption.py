"""Zero-cost tests for deterministic evidence consumption.

These tests exercise the same EventStore, LocalAdapters and AgencyLoop used by
the experiment.  They do not call a provider and do not touch a production
database or Bot.
"""
from __future__ import annotations

import json
import pathlib
import tempfile
from typing import Any, Callable

from adapters.local import LocalAdapters
from controller.gateway import ScriptedGateway
from evaluation.harness import _event
from runtime.context import ContextBuilder
from runtime.loop import AgencyLoop
from runtime.policy import Policy
from runtime.store import EventStore, StoreError
from transport.sink import RecordingSink


OWNER = "owner-a"


def _ref(path: str, *, status: str = "observed", **extra: str) -> dict[str, Any]:
    value: dict[str, Any] = {"source_ref": f"fixture://{OWNER}/{path}", "epistemic_status": status}
    value.update(extra)
    return value


def _create_update() -> dict[str, Any]:
    return {
        "operation": "create",
        "concern_ref": "local-evidence",
        "expected_version": None,
        "basis_refs": [_ref("profile")],
        "changes": {
            "title": "跟进门店经营证据",
            "desired_direction": "用新的经营来源核对中影门店的变化",
            "domain": "work",
            "origin": "observed_gap",
            "desire_refs": ["work_trust"],
            "known_summary": [_ref("profile", summary="已确认业务范围")],
            "unknowns": [_ref("profile", status="unknown", impact="缺少来源会影响经营判断")],
            "next_review_condition": {"type": "next_eligible_opportunity", "reason": "收到新经营来源"},
            "boundary_refs": [_ref("profile", summary="只读实验")],
        },
    }


def _decision(action: dict[str, Any], *, concern_ref: str | None = None, updates: list[dict[str, Any]] | None = None, messages: list[str] | None = None) -> dict[str, Any]:
    return {
        "operation": "new",
        "intention_ref": None,
        "desired_change": "完成当前查询并保留可核验依据",
        "basis_refs": [f"fixture://{OWNER}/profile"],
        "action": action,
        "strategy_reason": "当前输入需要读取来源后再交付",
        "expected_participation": None,
        "reconsider_condition": "收到新输入",
        "messages": messages or [],
        "concern_ref": concern_ref,
        "task_ref": None,
        "concern_updates": updates or [],
    }


def _run_case(name: str, fn: Callable[[], None], results: list[dict[str, Any]]) -> None:
    try:
        fn()
    except Exception as exc:  # retain the exact first failure as evidence
        results.append({"name": name, "status": "failed", "error": f"{type(exc).__name__}: {exc}"})
    else:
        results.append({"name": name, "status": "passed"})


def _tool_result(status: str = "complete", *, data: Any = None, refs: list[str] | None = None, version: str = "9754") -> dict[str, Any]:
    if data is None:
        data = [] if status == "complete" else {"reason": "upstream unavailable"}
    return {
        "status": status,
        "data": data,
        "source_refs": refs or ["feishu://sheet-token/revision/9754/中影店"],
        "scope": OWNER,
        "version": version,
        "trace_id": f"trace-{version}-{status}",
        "completeness": "complete" if status == "complete" else "none",
    }


def test_multi_source_version_and_idempotence() -> None:
    root = pathlib.Path(tempfile.mkdtemp(prefix="evidence-store-"))
    store = EventStore(root / "state.db")
    try:
        with store.transaction():
            created = store.apply_concern_updates(OWNER, "event-create", [_create_update()])
        concern_id = created["accepted"][0]["concern_id"]
        refs = [
            "feishu://sheet-token/revision/9754/中影店",
            "feishu://sheet-token/revision/9754/中影店-日客流",
        ]
        result = _tool_result(
            data=[
                {"store_name": "中影店", "metric": "reception_traffic", "value": 201, "source_ref": refs[0], "source_revision": "9754"},
                {"store_name": "中影店", "metric": "box_office_total", "value": 15951.1, "source_ref": refs[1], "source_revision": "9754"},
            ],
            refs=refs,
        )
        with store.transaction():
            first_version = store.record_concern_tool_evidence(OWNER, concern_id, "event-read", "action-read", tool_type="knowledge.search", result=result)
        with store.transaction():
            replay_version = store.record_concern_tool_evidence(OWNER, concern_id, "event-read", "action-read", tool_type="knowledge.search", result=result)
        concern = store.get_concern(OWNER, concern_id)
        events = store.conn.execute("SELECT operation FROM concern_events WHERE concern_id=?", (concern_id,)).fetchall()
        assert first_version == replay_version == 1
        assert concern["version"] == 1
        assert {item["source_ref"] for item in concern["known_summary"]} >= set(refs)
        assert {item.get("version") for item in concern["known_summary"] if isinstance(item, dict)} >= {"9754"}
        assert [row[0] for row in events].count("tool_evidence") == 1
    finally:
        store.close()


def test_failure_is_observation_not_fact() -> None:
    root = pathlib.Path(tempfile.mkdtemp(prefix="evidence-failure-"))
    store = EventStore(root / "state.db")
    try:
        with store.transaction():
            created = store.apply_concern_updates(OWNER, "event-create", [_create_update()])
        concern_id = created["accepted"][0]["concern_id"]
        failure = _tool_result("unavailable", data={"reason": "HTTP 503"}, refs=["feishu://sheet-token/revision/9754/中影店"])
        with store.transaction():
            version = store.record_concern_tool_evidence(OWNER, concern_id, "event-failed", "action-failed", tool_type="knowledge.search", result=failure)
        concern = store.get_concern(OWNER, concern_id)
        event = store.conn.execute("SELECT operation,patch_json FROM concern_events WHERE event_id='event-failed'").fetchone()
        assert version == 0 and concern["version"] == 0
        assert concern["known_summary"]
        assert not any("HTTP 503" in json.dumps(item, ensure_ascii=False) for item in concern["known_summary"])
        assert event[0] == "tool_observation"
        assert json.loads(event[1])["fact_written"] is False
    finally:
        store.close()


def test_snapshot_materializes_9754_and_not_future_revision() -> None:
    root = pathlib.Path(tempfile.mkdtemp(prefix="evidence-snapshot-"))
    snapshot = root / "snapshot"
    records = snapshot / "workbench-data" / "runtime-state"
    records.mkdir(parents=True)
    context = {
        "schemaVersion": "evidence-fixture-v1",
        "snapshotId": "snapshot-evidence",
        "owners": {OWNER: {"profile": {"source_ref": f"fixture://{OWNER}/profile"}, "facts": [], "knowledge": [], "tasks": [], "memories": [], "schedule": [], "history": []}},
    }
    (snapshot / "context.json").write_text(json.dumps(context, ensure_ascii=False), encoding="utf-8")
    (root / "manifest.json").write_text(json.dumps({"mode": "FROZEN", "snapshot_binding": {"snapshot_id": "snapshot-evidence"}}), encoding="utf-8")
    (records / "records.json").write_text(json.dumps({"data": [{
        "id": "WR-ZHONGYING-20260815", "venue": "中影", "periodStart": "2026-08-15", "periodEnd": "2026-08-21", "sourceRevision": "9754",
        "sourceRefs": [{"sourceRef": "feishu://sheet-token/revision/9754/中影店"}], "core": {"reception_traffic": 201, "box_office_total": 15951.1}, "daily": [],
    }]}, ensure_ascii=False), encoding="utf-8")
    adapter = LocalAdapters(snapshot_root=snapshot, manifest_path=root / "manifest.json")
    result = adapter.execute(OWNER, "knowledge.search", {"store_name": "中影", "metric": "reception_traffic"})
    assert result["status"] == "complete"
    assert result["version"] == "9754"
    assert any(item.get("value") == 201 for item in result["data"])
    assert all("9753" not in ref and "9755" not in ref for ref in result["source_refs"])


def test_model_patch_must_reference_worker_visible_evidence() -> None:
    root = pathlib.Path(tempfile.mkdtemp(prefix="evidence-ref-gate-"))
    store = EventStore(root / "state.db")
    try:
        invalid = _create_update()
        invalid["basis_refs"] = [_ref("not-in-context")]
        with store.transaction():
            result = store.apply_concern_updates(OWNER, "event-ref-gate", [invalid], allowed_source_refs={f"fixture://{OWNER}/profile"})
        assert result["rejected"]
        assert "evidence_ref_not_worker_visible" in result["rejected"][0]["reason"]
        assert store.conn.execute("SELECT COUNT(*) FROM concerns").fetchone()[0] == 0
    finally:
        store.close()


def test_loop_trace_contains_evidence_consumption_fields() -> None:
    root = pathlib.Path(tempfile.mkdtemp(prefix="evidence-loop-"))
    fixture = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "public_state.json"
    prompt = pathlib.Path(__file__).resolve().parents[1] / "runtime" / "prompts" / "concerns-v1.json"
    store = EventStore(root / "state.db")
    first = _decision({"type": "knowledge.search", "args": {"store_name": "东坝店", "business_date": "2026-09-02", "metric": "销售额"}, "expected_result": "返回经营事实"}, concern_ref="local-evidence", updates=[_create_update()])
    second = _decision({"type": "deliver", "args": {}, "expected_result": "交付查询结果"}, messages=["东坝店 2026-09-02 销售额为 266 元。"])
    loop = AgencyLoop(
        store=store,
        context=ContextBuilder(fixture, prompt, store=store, concerns_enabled=True),
        adapters=LocalAdapters(fixture, store=store, concerns_enabled=True),
        policy=Policy(store, writable_root=root, concerns_enabled=True),
        gateway=ScriptedGateway([first, second]),
        sink=RecordingSink(root / "sink.jsonl"),
        trace_path=root / "trace.jsonl",
    )
    try:
        result = loop.process_event(_event("evidence-loop-event", payload={"text": "先查东坝店的销售额", "explicit_goal": True}))
        assert result["status"] == "delivered"
        traces = [json.loads(line) for line in (root / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
        assert any(item.get("retrievedSourceRefs") for item in traces)
        assert any(item.get("autoRecordedEvidenceRefs") for item in traces)
        assert any(item.get("modelConcernUpdates") for item in traces)
        assert any(item.get("actionEvidenceRefs") for item in traces)
        assert any(item.get("receipt") for item in traces if item.get("kind") == "delivery")
        assert all("9754" not in json.dumps(item, ensure_ascii=False) for item in traces)
    finally:
        store.close()


def run_evidence_consumption(run_root: pathlib.Path | None = None) -> dict[str, Any]:
    root = run_root or pathlib.Path(tempfile.mkdtemp(prefix="evidence-consumption-"))
    results: list[dict[str, Any]] = []
    tests = [
        ("E01", "multi-source 9754 evidence is idempotent", test_multi_source_version_and_idempotence),
        ("E02", "failure is observation, not fact", test_failure_is_observation_not_fact),
        ("E03", "snapshot consumes 9754 without future revision", test_snapshot_materializes_9754_and_not_future_revision),
        ("E04", "model patch needs worker-visible evidence", test_model_patch_must_reference_worker_visible_evidence),
        ("E05", "trace records evidence consumption and receipt", test_loop_trace_contains_evidence_consumption_fields),
    ]
    for name, description, fn in tests:
        _run_case(f"{name}: {description}", fn, results)
    passed = sum(item["status"] == "passed" for item in results)
    output = {"schemaVersion": "evidence-consumption-v1", "status": "passed" if passed == len(results) else "failed", "passed": passed, "total": len(results), "provider_calls": 0, "results": results}
    root.mkdir(parents=True, exist_ok=True)
    (root / "evidence-consumption.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


if __name__ == "__main__":
    print(json.dumps(run_evidence_consumption(), ensure_ascii=False, indent=2))
