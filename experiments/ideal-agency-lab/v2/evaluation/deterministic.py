"""E2 deterministic contract suite over the same formal worker path."""
from __future__ import annotations

import json
import pathlib
import uuid
from typing import Any, Callable

from adapters.local import LocalAdapters
from controller.gateway import ScriptedGateway
from evaluation.harness import VALID_DECISION, _event
from runtime.context import ContextBuilder
from runtime.loop import AgencyLoop
from runtime.policy import Policy, PolicyError
from runtime.store import EventStore, StoreError
from transport.sink import RecordingSink


def _tool_decision() -> dict[str, Any]:
    return {
        "operation": "new", "intention_ref": None, "desired_change": "核验指定门店指定日期的指标",
        "basis_refs": ["fixture://owner-a/sales"], "action": {"type": "knowledge.search", "args": {"store": "南城店", "date": "2026-09-02", "metric_name": "销售额"}, "expected_result": "返回匹配事实"},
        "strategy_reason": "用户要求定向核验", "expected_participation": None, "reconsider_condition": "收到新输入", "messages": [],
    }


class DeterministicSuite:
    def __init__(self, run_root: pathlib.Path, fixture_path: pathlib.Path, prompt_path: pathlib.Path):
        self.run_root = run_root
        self.fixture_path = fixture_path
        self.prompt_path = prompt_path
        self.results: list[dict[str, Any]] = []

    def _run(self, name: str, fn: Callable[[], None]) -> None:
        try:
            fn(); self.results.append({"name": name, "status": "passed"})
        except Exception as exc:
            self.results.append({"name": name, "status": "failed", "error": f"{type(exc).__name__}: {exc}"})

    def _loop(self, responses: list[Any], *, outcomes: dict[str, str] | None = None, suffix: str = "case") -> tuple[AgencyLoop, EventStore, ScriptedGateway]:
        root = self.run_root / "e2-trajectories" / f"{suffix}-{uuid.uuid4().hex[:8]}"; root.mkdir(parents=True, exist_ok=False)
        store = EventStore(root / "state.db"); gateway = ScriptedGateway(responses); sink = RecordingSink(root / "traces" / "sink.jsonl", outcomes)
        loop = AgencyLoop(store=store, context=ContextBuilder(self.fixture_path, self.prompt_path), adapters=LocalAdapters(self.fixture_path), policy=Policy(store, writable_root=root), gateway=gateway, sink=sink, trace_path=root / "traces" / "trace.jsonl")
        return loop, store, gateway

    def run(self) -> dict[str, Any]:
        self._run("direct delivery uses one model call", self.direct_delivery)
        self._run("tool result resumes same loop and preserves args", self.tool_continuation)
        self._run("wait has no sink side effect", self.wait_no_side_effect)
        self._run("invalid JSON is retained as schema failure", self.invalid_json)
        self._run("partial receipt persists across restart", self.partial_restart)
        self._run("lease prevents concurrent processing", self.concurrent_lease)
        self._run("old version cannot deliver after new input", self.version_conflict)
        passed = sum(item["status"] == "passed" for item in self.results)
        return {"schemaVersion": "e2-deterministic-v2", "status": "passed" if passed == len(self.results) else "failed", "passed": passed, "total": len(self.results), "results": self.results}

    def direct_delivery(self):
        loop, store, gateway = self._loop([VALID_DECISION], suffix="direct")
        result = loop.process_event(_event("e2-direct")); assert result["status"] == "delivered" and len(gateway.calls) == 1
        assert store.conn.execute("SELECT state FROM actions").fetchone()[0] == "delivered"; store.close()

    def tool_continuation(self):
        loop, store, gateway = self._loop([_tool_decision(), VALID_DECISION], suffix="tool")
        result = loop.process_event(_event("e2-tool")); assert result["status"] == "delivered" and len(gateway.calls) == 2
        row = store.conn.execute("SELECT original_args_json,normalized_args_json,diff_json,result_json FROM tool_requests").fetchone(); assert row is not None
        assert json.loads(row[0])["store"] == "南城店" and json.loads(row[1])["business_date"] == "2026-09-02" and json.loads(row[1])["metric"] == "销售额"
        assert json.loads(row[3])["data"][0]["value"] == 150.0; store.close()

    def wait_no_side_effect(self):
        wait = dict(VALID_DECISION); wait["action"] = {"type": "wait", "args": {}, "expected_result": ""}; wait["messages"] = []
        loop, store, gateway = self._loop([wait], suffix="wait"); result = loop.process_event(_event("e2-wait")); assert result["status"] == "waiting" and not store.conn.execute("SELECT 1 FROM sink_deliveries").fetchone() and len(gateway.calls) == 1; store.close()

    def invalid_json(self):
        loop, store, gateway = self._loop(["not-json"], suffix="invalid"); result = loop.process_event(_event("e2-invalid")); assert result["status"] == "schema_failure" and not store.conn.execute("SELECT 1 FROM sink_deliveries").fetchone(); store.close()

    def partial_restart(self):
        loop, store, _ = self._loop([VALID_DECISION], outcomes={"*": "unknown"}, suffix="restart"); result = loop.process_event(_event("e2-restart")); assert result["status"] == "unknown"; store.close()
        db = next((self.run_root / "e2-trajectories").glob("restart-*/state.db")); reopened = EventStore(db); assert reopened.conn.execute("SELECT state FROM actions").fetchone()[0] == "unknown"; reopened.close()

    def concurrent_lease(self):
        db = self.run_root / "e2-lease.db"; first = EventStore(db); second = EventStore(db); first.acquire_lease("owner-a")
        try: second.acquire_lease("owner-a")
        except StoreError: first.release_lease("owner-a"); first.close(); second.close(); return
        first.close(); second.close(); raise AssertionError("concurrent lease was allowed")

    def version_conflict(self):
        loop, store, _ = self._loop([VALID_DECISION, VALID_DECISION], suffix="version"); assert loop.process_event(_event("e2-v1"))["status"] == "delivered"; assert loop.process_event(_event("e2-v2"))["status"] == "delivered"
        try: Policy(store).can_deliver_current("owner-a", 1, 2)
        except PolicyError: store.close(); return
        store.close(); raise AssertionError("stale action remained deliverable")

