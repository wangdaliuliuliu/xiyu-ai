"""T01-T14 deterministic contracts for the concerns arm.

These tests use the formal loop and the same SQLite store as a trajectory.  A
scripted gateway is only a deterministic controller double; it never counts as
real provider evidence.
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
import uuid
from typing import Any

from adapters.local import LocalAdapters
from controller.gateway import ScriptedGateway
from evaluation.harness import _event
from runtime.context import ContextBuilder
from runtime.loop import AgencyLoop
from runtime.policy import Policy
from runtime.store import EventStore
from transport.sink import RecordingSink


def _ref(owner: str = "owner-a", path: str = "concerns/source", status: str = "observed", **extra: str) -> dict[str, Any]:
    value: dict[str, Any] = {"source_ref": f"fixture://{owner}/{path}", "epistemic_status": status}
    value.update(extra)
    return value


def _create(local_ref: str = "c1", *, owner: str = "owner-a", origin: str = "observed_gap", linked_task_ids: list[str] | None = None) -> dict[str, Any]:
    return {
        "operation": "create",
        "concern_ref": local_ref,
        "expected_version": None,
        "basis_refs": [_ref(owner, "profile")],
        "changes": {
            "title": "推进周末经营复盘",
            "desired_direction": "找到能改变周末排片判断的新增证据",
            "domain": "work",
            "origin": origin,
            "desire_refs": ["work_trust"],
            "linked_task_ids": linked_task_ids or [],
            "known_summary": [_ref(owner, "profile", "confirmed", summary="已有一份可核验事实")],
            "unknowns": [_ref(owner, "profile", "unknown", impact="若不补齐会改变下一步经营判断")],
            "next_review_condition": {"type": "next_eligible_opportunity", "reason": "收到相关资料或下一次合法机会"},
            "boundary_refs": [_ref(owner, "profile", "confirmed", summary="只读实验边界")],
        },
    }


def _update(local_ref: str = "c1", version: int = 0, **changes: Any) -> dict[str, Any]:
    return {
        "operation": "update",
        "concern_ref": local_ref,
        "expected_version": version,
        "basis_refs": [_ref("owner-a", "profile")],
        "changes": changes or {"title": "推进新的周末经营复盘"},
    }


def _decision(action: dict[str, Any], *, concern_ref: str | None = None, task_ref: str | None = None, updates: list[dict[str, Any]] | None = None, messages: list[str] | None = None) -> dict[str, Any]:
    return {
        "operation": "new",
        "intention_ref": None,
        "desired_change": "完成当前请求并保留可核验的持续依据",
        "basis_refs": ["fixture://owner-a/event/1"],
        "action": action,
        "strategy_reason": "当前输入与来源支持这一步",
        "expected_participation": None,
        "reconsider_condition": "收到新输入",
        "messages": messages or (["已完成当前处理"] if action["type"] == "deliver" else []),
        "concern_ref": concern_ref,
        "task_ref": task_ref,
        "concern_updates": updates or [],
    }


def _loop(root: pathlib.Path, responses: list[Any], *, outcomes: dict[str, str] | None = None, concerns_enabled: bool = True) -> tuple[AgencyLoop, EventStore, ScriptedGateway]:
    root.mkdir(parents=True, exist_ok=False)
    fixture = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "public_state.json"
    prompt = pathlib.Path(__file__).resolve().parents[1] / "runtime" / "prompts" / "concerns-v1.json"
    store = EventStore(root / "state.db")
    gateway = ScriptedGateway(responses)
    loop = AgencyLoop(
        store=store,
        context=ContextBuilder(fixture, prompt, store=store, concerns_enabled=concerns_enabled),
        adapters=LocalAdapters(fixture, store=store, concerns_enabled=concerns_enabled),
        policy=Policy(store, writable_root=root, concerns_enabled=concerns_enabled),
        gateway=gateway,
        sink=RecordingSink(root / "traces" / "sink.jsonl", outcomes),
        trace_path=root / "traces" / "trace.jsonl",
    )
    return loop, store, gateway


class ConcernDeterministicSuite:
    def __init__(self, run_root: pathlib.Path):
        self.run_root = run_root
        self.results: list[dict[str, Any]] = []

    def _case(self, name: str, fn) -> None:
        try:
            fn()
            self.results.append({"name": name, "status": "passed"})
        except Exception as exc:  # evidence must retain the earliest failure
            self.results.append({"name": name, "status": "failed", "error": f"{type(exc).__name__}: {exc}"})

    def run(self) -> dict[str, Any]:
        tests = [
            ("T01", "same-owner same-event create is idempotent", self.t01),
            ("T02", "cross-owner concern read and write are rejected", self.t02),
            ("T03", "CAS competition rejects stale concern version", self.t03),
            ("T04", "user_goal origin cannot be fabricated", self.t04),
            ("T05", "resolve without evidence is rejected", self.t05),
            ("T06", "false delivery receipt cannot update last_contact", self.t06),
            ("T07", "temporary query does not force concern creation", self.t07),
            ("T08", "concern cannot modify an existing responsibility", self.t08),
            ("T09", "unconfirmed knowledge remains outside formal knowledge", self.t09),
            ("T10", "capacity rejection does not lose a task", self.t10),
            ("T11", "no change produces zero concern patches", self.t11),
            ("T12", "restart preserves concern id and version", self.t12),
            ("T13", "disabled baseline does not read concerns", self.t13),
            ("T14", "rejected dependent patch prevents the action", self.t14),
        ]
        for name, description, fn in tests:
            self._case(f"{name}: {description}", fn)
        passed = sum(item["status"] == "passed" for item in self.results)
        return {
            "schemaVersion": "concern-deterministic-v1",
            "status": "passed" if passed == len(self.results) else "failed",
            "passed": passed,
            "total": len(self.results),
            "provider_calls": 0,
            "human_review_required_for_sample_generation": False,
            "human_review_required_for_final_subjective_conclusion": True,
            "results": self.results,
        }

    def _new_store(self, name: str) -> EventStore:
        return EventStore(self.run_root / "concern-contracts" / f"{name}-{uuid.uuid4().hex[:8]}.db")

    def t01(self):
        store = self._new_store("t01")
        try:
            update = _create()
            with store.transaction():
                first = store.apply_concern_updates("owner-a", "event-t01", [update])
            with store.transaction():
                second = store.apply_concern_updates("owner-a", "event-t01", [update])
            assert len(first["accepted"]) == 1 and second["accepted"][0]["idempotent_replay"] is True
            assert store.conn.execute("SELECT COUNT(*) FROM concerns").fetchone()[0] == 1
            assert store.conn.execute("SELECT COUNT(*) FROM concern_events WHERE operation='create'").fetchone()[0] == 1
        finally:
            store.close()

    def t02(self):
        store = self._new_store("t02")
        try:
            with store.transaction():
                store.apply_concern_updates("owner-a", "event-t02", [_create()])
            assert store.get_concern("owner-b", "missing") is None
            with store.transaction():
                update = _update()
                update["basis_refs"] = [_ref("owner-b", "event/update")]
                result = store.apply_concern_updates("owner-b", "event-t02-b", [update])
            assert result["rejected"] and "not_found" in result["rejected"][0]["reason"]
            fixture = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "public_state.json"
            adapter = LocalAdapters(fixture, store=store, concerns_enabled=True)
            try:
                adapter.execute("owner-a", "concerns.read", {"owner": "owner-b", "limit": 6})
            except Exception as exc:
                assert "owner_scope" in str(exc)
            else:
                raise AssertionError("cross-owner concern read was allowed")
        finally:
            store.close()

    def t03(self):
        store = self._new_store("t03")
        try:
            with store.transaction():
                first = store.apply_concern_updates("owner-a", "event-t03-create", [_create()])
            concern_id = first["accepted"][0]["concern_id"]
            with store.transaction():
                accepted = store.apply_concern_updates("owner-a", "event-t03-a", [_update(concern_id, 0)])
            with store.transaction():
                rejected = store.apply_concern_updates("owner-a", "event-t03-b", [_update(concern_id, 0)])
            assert accepted["accepted"] and rejected["rejected"]
            assert "version_conflict" in rejected["rejected"][0]["reason"]
            assert store.get_concern("owner-a", concern_id)["version"] == 1
        finally:
            store.close()

    def t04(self):
        store = self._new_store("t04")
        try:
            update = _create(origin="user_goal")
            with store.transaction():
                result = store.apply_concern_updates("owner-a", "event-t04", [update], explicit_user_goal=False)
            assert result["rejected"] and "explicit user goal" in result["rejected"][0]["reason"]
            assert store.conn.execute("SELECT COUNT(*) FROM concerns").fetchone()[0] == 0
        finally:
            store.close()

    def t05(self):
        store = self._new_store("t05")
        try:
            update = _create(); update["operation"] = "resolve"; update["expected_version"] = 0; update["changes"]["status"] = "resolved"; update["changes"].pop("resolution_evidence", None)
            with store.transaction():
                result = store.apply_concern_updates("owner-a", "event-t05", [update])
            assert result["rejected"] and "resolution_evidence" in result["rejected"][0]["reason"]
        finally:
            store.close()

    def t06(self):
        action = {"type": "deliver", "args": {}, "expected_result": "sink receipt"}
        loop, store, _ = _loop(self.run_root / "t06", [_decision(action, concern_ref="c1", updates=[_create()])], outcomes={"*": "unknown"})
        try:
            result = loop.process_event(_event("t06-event"))
            assert result["status"] == "unknown"
            concern = store.get_concern("owner-a", result["concern_id"])
            assert concern["last_contact_ref"] is None and concern["last_progress_ref"] is None
        finally:
            store.close()

    def t07(self):
        search = {"type": "knowledge.search", "args": {"store_name": "东坝店", "business_date": "2026-09-02", "metric": "销售额"}, "expected_result": "匹配事实"}
        deliver = {"type": "deliver", "args": {}, "expected_result": "交付"}
        loop, store, gateway = _loop(self.run_root / "t07", [_decision(search), _decision(deliver)], concerns_enabled=True)
        try:
            result = loop.process_event(_event("t07-event"))
            assert result["status"] == "delivered" and len(gateway.calls) == 2
            assert store.conn.execute("SELECT COUNT(*) FROM concerns").fetchone()[0] == 0
        finally:
            store.close()

    def t08(self):
        store = self._new_store("t08")
        try:
            fixture = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "public_state.json"
            store.seed_tasks("owner-a", json.loads(fixture.read_text(encoding="utf-8"))["owners"]["owner-a"]["tasks"])
            with store.transaction():
                result = store.apply_concern_updates("owner-a", "event-t08", [_create(linked_task_ids=["task-a-1"])])
            assert result["accepted"]
            task = next(item for item in store.read_tasks("owner-a") if item["id"] == "task-a-1")
            assert task["status"] == "open" and task["version"] == 0
            with store.transaction():
                rejected = store.apply_concern_updates("owner-a", "event-t08-missing", [_create(local_ref="c-missing", linked_task_ids=["task-not-owned-by-this-store"])])
            assert rejected["rejected"] and "task_link_owner_scope_or_not_found" in rejected["rejected"][0]["reason"]
        finally:
            store.close()

    def t09(self):
        store = self._new_store("t09")
        try:
            fixture = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "public_state.json"
            adapter = LocalAdapters(fixture, store=store, concerns_enabled=True)
            candidate = adapter.execute("owner-a", "knowledge.propose", {"candidate": "新客群"})
            assert candidate["data"]["confirmed"] is False
            assert store.search_knowledge("owner-a", "新客群") == []
            assert store.search_knowledge("owner-a", "新客群", include_candidates=True)
        finally:
            store.close()

    def t10(self):
        store = self._new_store("t10")
        try:
            store.seed_tasks("owner-a", [{"id": "task-capacity", "owner": "owner-a", "status": "open", "title": "不能丢失的责任", "source_ref": "fixture://owner-a/tasks/capacity"}])
            for index in range(12):
                with store.transaction():
                    result = store.apply_concern_updates("owner-a", f"event-t10-{index}", [_create(f"c{index}")])
                assert result["accepted"]
            with store.transaction():
                rejected = store.apply_concern_updates("owner-a", "event-t10-over", [_create("overflow")])
            assert rejected["rejected"][0]["reason"] == "concern_capacity_exceeded"
            assert store.read_tasks("owner-a")[0]["id"] == "task-capacity"
            assert store.conn.execute("SELECT COUNT(*) FROM concerns WHERE status='active'").fetchone()[0] == 12
        finally:
            store.close()

    def t11(self):
        store = self._new_store("t11")
        try:
            with store.transaction():
                result = store.apply_concern_updates("owner-a", "event-t11", [])
            assert result == {"accepted": [], "rejected": [], "ref_map": {}, "rejected_refs": []}
            assert store.conn.execute("SELECT COUNT(*) FROM concern_events").fetchone()[0] == 0
        finally:
            store.close()

    def t12(self):
        store = self._new_store("t12")
        db = store.path
        try:
            with store.transaction():
                created = store.apply_concern_updates("owner-a", "event-t12-create", [_create()])
            concern_id = created["accepted"][0]["concern_id"]
            with store.transaction():
                store.apply_concern_updates("owner-a", "event-t12-update", [_update(concern_id, 0)])
            with store.transaction():
                resolved = store.apply_concern_updates(
                    "owner-a",
                    "event-t12-resolve",
                    [{
                        "operation": "resolve",
                        "concern_ref": concern_id,
                        "expected_version": 1,
                        "basis_refs": [_ref("owner-a", "event/resolve")],
                        "changes": {"status": "resolved", "resolution_evidence": [_ref("owner-a", "resolution/1", "confirmed", summary="resolution evidence")]},
                    }],
                )
            assert resolved["accepted"] and resolved["accepted"][0]["new_version"] == 2
            with store.transaction():
                resurrected = store.apply_concern_updates("owner-a", "event-t12-resurrect", [_update(concern_id, 2)])
            assert resurrected["rejected"] and "terminal_concern_requires_new_concern" in resurrected["rejected"][0]["reason"]
        finally:
            store.close()
        reopened = EventStore(db)
        try:
            concern = reopened.get_concern("owner-a", concern_id)
            assert concern["id"] == concern_id and concern["version"] == 2 and concern["status"] == "resolved"
        finally:
            reopened.close()

    def t13(self):
        class NoReadStore:
            def recent_feedback(self, owner):
                raise AssertionError("baseline read feedback")
            def read_concerns(self, *args, **kwargs):
                raise AssertionError("baseline read concerns")

        fixture = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "public_state.json"
        prompt = pathlib.Path(__file__).resolve().parents[1] / "runtime" / "prompts" / "p1.json"
        context = ContextBuilder(fixture, prompt, store=NoReadStore(), concerns_enabled=False).build(_event("t13-event"))
        assert context["concerns"]["enabled"] is False and context["concerns"]["selected"] == []

    def t14(self):
        invalid = _create("c-bad")
        invalid["changes"].pop("title")
        action = {"type": "deliver", "args": {}, "expected_result": "must not run"}
        loop, store, _ = _loop(self.run_root / "t14", [_decision(action, concern_ref="c-bad", updates=[invalid])])
        try:
            result = loop.process_event(_event("t14-event"))
            assert result["status"] == "failed" and result["error"] == "PolicyError" and "concern_patch_rejected_dependency" in result["message"]
            assert store.conn.execute("SELECT COUNT(*) FROM sink_deliveries").fetchone()[0] == 0
            assert store.conn.execute("SELECT operation FROM concern_events").fetchone()[0] == "rejected"
        finally:
            store.close()


def run_concern_deterministic(run_root: pathlib.Path) -> dict[str, Any]:
    result = ConcernDeterministicSuite(run_root).run()
    path = run_root / "concern-deterministic.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    timeline: list[dict[str, Any]] = []
    db_paths = list((run_root / "concern-contracts").glob("*.db"))
    db_paths.extend(path for path in run_root.glob("t*/state.db") if path.is_file())
    for db_path in db_paths:
        connection = sqlite3.connect(db_path)
        try:
            rows = connection.execute("SELECT id,owner,concern_id,event_id,action_id,local_ref,expected_version,new_version,operation,patch_json,refs_json,recorded_at FROM concern_events ORDER BY event_record_id").fetchall()
            for row in rows:
                item = dict(zip(("id", "owner", "concern_id", "event_id", "action_id", "local_ref", "expected_version", "new_version", "operation", "patch_json", "refs_json", "recorded_at"), row))
                item["patch"] = json.loads(item.pop("patch_json"))
                item["refs"] = json.loads(item.pop("refs_json"))
                item["evidence_db"] = str(db_path)
                timeline.append(item)
        finally:
            connection.close()
    timeline_path = run_root / "concern-timeline.jsonl"
    timeline_path.write_text("".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in timeline), encoding="utf-8")
    failures_path = run_root / "failures.md"
    if failures_path.exists() and result["status"] == "failed":
        failures_path.write_text("# Concerns failures\n\n" + "\n".join(f"- {item['name']}: {item.get('error', 'failed')}" for item in result["results"] if item["status"] == "failed") + "\n", encoding="utf-8")
    return result
