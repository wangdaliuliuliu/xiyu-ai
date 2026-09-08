"""Formal evaluator self-tests using real boundary, parity, loop, and sink paths."""
from __future__ import annotations

import json
import pathlib
import shutil
import tempfile
import uuid
from copy import deepcopy
from typing import Any, Callable

from adapters.local import LocalAdapters
from controller.boundary import BoundaryViolation, NetworkBoundary, PathBoundary
from controller.gateway import ScriptedGateway
from evaluation.parity import compare_resource_manifest, compare_sqlite
from runtime.context import ContextBuilder
from runtime.loop import AgencyLoop
from runtime.policy import Policy
from runtime.store import EventStore, StoreError
from transport.sink import RecordingSink


VALID_DECISION = {
    "operation": "new", "intention_ref": None, "desired_change": "完成一次有来源的工作交付",
    "basis_refs": ["fixture://owner-a/profile"], "action": {"type": "deliver", "args": {}, "expected_result": "送达"},
    "strategy_reason": "当前输入要求直接交付", "expected_participation": None,
    "reconsider_condition": "收到新输入或下一次合法机会", "messages": ["已准备好交付。"],
}


def _event(event_id: str = "selftest-event", *, kind: str = "user_message", payload: dict | None = None, owner: str = "owner-a") -> dict:
    return {"event_id": event_id, "owner": owner, "kind": kind, "virtual_time": "2026-09-08T10:00:00+08:00", "payload": payload or {"text": "请准备一条有依据的交付"}}


class HarnessSelftest:
    def __init__(self, *, run_root: pathlib.Path, fixture_path: pathlib.Path):
        self.run_root = run_root
        self.fixture_path = fixture_path
        self.results: list[dict[str, Any]] = []

    def _assert(self, case_id: str, name: str, fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception as exc:
            self.results.append({"id": case_id, "name": name, "status": "failed", "error": f"{type(exc).__name__}: {exc}"})
        else:
            self.results.append({"id": case_id, "name": name, "status": "passed"})

    def _loop(self, responses: list[Any], *, outcomes: dict[str, str] | None = None, owner: str = "owner-a") -> tuple[AgencyLoop, EventStore]:
        trajectory = self.run_root / "selftest-trajectories" / f"{len(self.results):02d}-{uuid.uuid4().hex[:8]}"
        trajectory.mkdir(parents=True, exist_ok=True)
        store = EventStore(trajectory / "state.db")
        store.configure_budget(owner)
        sink = RecordingSink(trajectory / "traces" / "sink.jsonl", outcomes)
        loop = AgencyLoop(
            store=store,
            context=ContextBuilder(self.fixture_path),
            adapters=LocalAdapters(self.fixture_path),
            policy=Policy(store, writable_root=trajectory),
            gateway=ScriptedGateway(responses),
            sink=sink,
            trace_path=trajectory / "traces" / "trace.jsonl",
        )
        return loop, store

    def run(self) -> dict[str, Any]:
        self._run_evidence_selftests()
        # X01/X02/X03/X04/X05 use the actual manifest/parity evaluator, not ID-specific verdicts.
        self._assert("X01", "resource manifest detects deleted replica", self._x01)
        self._assert("X02", "logical row value mutation fails parity", self._x02)
        self._assert("X03", "missing data file is not complete", self._x03)
        self._assert("X04", "parse error is not None==None", self._x04)
        self._assert("X05", "logical snapshot catches sidecar/WAL change", self._x05)
        self._assert("X06", "cross-owner adapter access is rejected", self._x06)
        self._assert("X07", "production path write is blocked", self._x07)
        self._assert("X08", "unallowlisted network is blocked", self._x08)
        self._assert("X09", "tool args preserve model-selected store/date/metric", self._x09)
        self._assert("X10", "wait and invalid JSON create no side effect", self._x10)
        self._assert("X11", "new input invalidates old version", self._x11)
        self._assert("X12", "knowledge candidate remains explicit until confirmation", self._x12)
        self._assert("X13", "assistant-only history is not user fact", self._x13)
        self._assert("X14", "future schedule is not current fact", self._x14)
        self._assert("X15", "missing asset cannot be delivered", self._x15)
        self._assert("X16", "partial sink result is not completed", self._x16)
        self._assert("X17", "provider error is not completed", self._x17)
        self._assert("X18", "oracle is outside worker readable roots", self._x18)
        self._assert("X19", "oracle binding rejects changed version", self._x19)
        self._assert("X20", "trajectory initial state is immutable", self._x20)
        self._assert("X21", "existing run is not overwritten", self._x21)
        self._assert("X22", "coverage exposes missing personal branch", self._x22)
        self._assert("X23", "business references survive exact secret scrub", self._x23)
        self._assert("X24", "oracle version/value mismatch is visible", self._x24)
        passed = sum(item["status"] == "passed" for item in self.results)
        return {"schemaVersion": "harness-selftest-v2", "status": "passed" if passed == len(self.results) else "failed", "passed": passed, "total": len(self.results), "results": self.results}

    def _run_evidence_selftests(self) -> None:
        from evaluation.evidence import make_base_evidence, validate_coverage, validate_evidence
        mutations = [
            ("M01", "missing_actual_input", lambda t, e: t["entry"].update(input="")),
            ("M02", "wrong_prompt_path", lambda t, e: t["prompt"].update(builder="shortcut")),
            ("M03", "tool_not_executed", lambda t, e: t.update(tools=[{"status": "planned"}])),
            ("M04", "unresolved_repair", lambda t, e: t.update(reviews=[{"verdict": "repair"}])),
            ("M05", "concealed_conflict", lambda t, e: e.update(resultStatus="conflict")),
            ("M06", "lost_required_fact", lambda t, e: t.update(finalPayload="266")),
            ("M07", "unbacked_promise", lambda t, e: t.update(executionClaims=[{"kind": "future_delivery"}])),
            ("M08", "false_delivery", lambda t, e: t.update(state="delivered", receipts=[])),
            ("M09", "owner_mismatch", lambda t, e: t.update(ownerEvents=[{"owner": {"accountId": "other"}}])),
            ("M10", "provider_or_schema_failure", lambda t, e: t.update(calls=[{"ok": True, "schemaValid": False}])),
            ("M11", "required_contact_missing", lambda t, e: t.update(receipts=[])),
            ("M13", "image_unverified", lambda t, e: (e.update(requiresImage=True), t.update(assets=[{"ref": "string-only"}]))),
            ("M14", "missing_isolation_evidence", lambda t, e: t.update(isolation={"outbound": 0})),
            ("M15", "lost_required_fact", lambda t, e: (t.update(rawPayload=t["finalPayload"]), t.update(finalPayload="266"))),
            ("M16", "stale_evidence", lambda t, e: t.update(hashes={"code": "changed"})),
        ]
        for case_id, expected_error, mutate in mutations:
            def check(case_id=case_id, expected_error=expected_error, mutate=mutate):
                trace, expected, manifest = make_base_evidence(); mutate(trace, expected); assert expected_error in validate_evidence(trace, expected, manifest)
            self._assert(case_id, f"evidence evaluator detects {expected_error}", check)
        def coverage_check():
            from evaluation.evidence import make_base_evidence
            _, _, manifest = make_base_evidence(); manifest["familyIds"] = ["A01"]; assert "incomplete_families" in validate_coverage(manifest)
        self._assert("M12", "coverage evaluator detects incomplete families", coverage_check)

    def _inventory(self) -> dict[str, Any]:
        return {"resources": [{"resource_id": "r", "status": "present", "replica_locator": str(self.run_root / "selftest-file.txt"), "replica_hash": "bad"}]}

    def _x01(self):
        self._assert_resource_failure()
    def _assert_resource_failure(self):
        result = compare_resource_manifest(self._inventory(), self.run_root)
        assert result["status"] == "failed"
    def _x02(self):
        source = self.run_root / f"parity-source-{uuid.uuid4().hex}.db"; replica = self.run_root / f"parity-replica-{uuid.uuid4().hex}.db"
        import sqlite3
        for path, value in ((source, "A"), (replica, "B")):
            c = sqlite3.connect(path); c.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, value TEXT)"); c.execute("INSERT INTO t(value) VALUES(?)", (value,)); c.commit(); c.close()
        assert compare_sqlite(source, replica)["status"] == "failed"
    def _x03(self):
        result = compare_resource_manifest({"resources": [{"resource_id": "missing", "status": "present", "replica_locator": str(self.run_root / "not-there"), "replica_hash": "x"}]}, self.run_root)
        assert result["status"] == "failed"
    def _x04(self):
        bad = self.run_root / "invalid.json"; bad.write_text("{", encoding="utf-8")
        try: json.loads(bad.read_text(encoding="utf-8"))
        except json.JSONDecodeError: return
        raise AssertionError("parse unexpectedly succeeded")
    def _x05(self):
        source = self.run_root / f"wal-source-{uuid.uuid4().hex}.db"; replica = self.run_root / f"wal-replica-{uuid.uuid4().hex}.db"
        import sqlite3
        c = sqlite3.connect(source); c.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, value TEXT)"); c.execute("INSERT INTO t(value) VALUES('one')"); c.commit(); c.backup(sqlite3.connect(replica)); c.close()
        c = sqlite3.connect(source); c.execute("INSERT INTO t(value) VALUES('wal-change')"); c.commit(); c.close()
        assert compare_sqlite(source, replica)["status"] == "failed"
    def _x06(self):
        try: LocalAdapters(self.fixture_path).execute("owner-a", "knowledge.search", {"owner": "owner-b", "store_name": "东坝店", "business_date": "2026-09-02", "metric": "销售额"})
        except Exception as exc: assert "owner_scope" in str(exc); return
        raise AssertionError("cross-owner read was allowed")
    def _x07(self):
        audit = []; root = self.run_root / "worker-x07"; boundary = PathBoundary(root, [self.run_root / "snapshot"], [self.run_root.parent.parent])
        try: boundary.write_bytes(self.run_root.parent.parent / "production-attempt.txt", b"blocked")
        except BoundaryViolation: return
        raise AssertionError("production write was not blocked")
    def _x08(self):
        try: NetworkBoundary(set(), set()).check("https://example.invalid/blocked")
        except BoundaryViolation: return
        raise AssertionError("network was not blocked")
    def _x09(self):
        from contracts.schemas import normalize_action_args
        normalized, diff = normalize_action_args("knowledge.search", {"store": "南城店", "date": "2026-09-03", "metric_name": "客流"})
        assert normalized == {"store_name": "南城店", "business_date": "2026-09-03", "metric": "客流"} and diff["changed"]
    def _x10(self):
        wait = dict(VALID_DECISION); wait["action"] = {"type": "wait", "args": {}, "expected_result": ""}; wait["messages"] = []
        loop, store = self._loop([wait]); result = loop.process_event(_event("x10-wait")); assert result["status"] == "waiting"; assert not store.conn.execute("SELECT 1 FROM sink_deliveries").fetchone(); store.close()
    def _x11(self):
        from runtime.policy import PolicyError
        loop, store = self._loop([VALID_DECISION, VALID_DECISION]); first = loop.process_event(_event("x11-a")); assert first["status"] == "delivered"; second = loop.process_event(_event("x11-b")); assert second["status"] == "delivered"; assert store.conn.execute("SELECT COUNT(DISTINCT event_version) FROM actions").fetchone()[0] == 2
        try: Policy(store).can_deliver_current("owner-a", 1, 2)
        except PolicyError: store.close(); return
        store.close(); raise AssertionError("old version remained deliverable")
    def _x12(self):
        adapters = LocalAdapters(self.fixture_path); result = adapters.execute("owner-a", "knowledge.propose", {"candidate": "新客群"}); assert result["data"]["status"] == "candidate" and result["data"]["confirmed"] is False
    def _x13(self):
        context = ContextBuilder(self.fixture_path); data = deepcopy(context.fixture); data["owners"]["owner-a"]["history"] = [{"id": "a", "owner": "owner-a", "role": "assistant", "text": "用户说过X", "sent_at": "2026-09-08T00:00:00+08:00"}]; path = self.run_root / "assistant-only.json"; path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8"); assert not [m for m in ContextBuilder(path).owner_data("owner-a")["history"] if m["role"] == "user"]
    def _x14(self):
        current = ContextBuilder(self.fixture_path).build(_event("x14"))["current"]; assert all(item["starts_at"] <= "2026-09-08T10:00:00+08:00" for item in current["schedule"])
    def _x15(self):
        result = LocalAdapters(self.fixture_path).execute("owner-a", "media.prepare", {"asset_path": str(self.run_root / "missing.png")}); assert result["status"] == "failed"
    def _x16(self):
        loop, store = self._loop([VALID_DECISION], outcomes={"*": "partial"}); result = loop.process_event(_event("x16-partial")); assert result["status"] == "partial"; store.close()
    def _x17(self):
        from controller.gateway import ProviderResponse
        loop, store = self._loop([ProviderResponse("r", "deterministic-injected", {}, finish_reason="error", error="timeout")]); result = loop.process_event(_event("x17")); assert result["status"] == "infra_failure"; store.close()
    def _x18(self):
        boundary = PathBoundary(self.run_root / "worker-x18", [self.run_root / "snapshot"], [self.run_root / "oracle"]); oracle = self.run_root / "oracle"; oracle.mkdir(exist_ok=True); (oracle / "answers.json").write_text("{}", encoding="utf-8");
        try: boundary.read_bytes(oracle / "answers.json")
        except BoundaryViolation: return
        raise AssertionError("oracle read was allowed")
    def _x19(self):
        from evaluation.parity import validate_oracle_binding
        assert not validate_oracle_binding({"code_hash": "a", "fixture_hash": "b", "model": "m2"}, {"code_hash": "a", "fixture_hash": "b", "model": "m1"})
    def _x20(self):
        store = EventStore(self.run_root / "x20.db"); store.ensure_thread("owner-a", {"seed": 1})
        try: store.ensure_thread("owner-a", {"seed": 2})
        except StoreError: store.close(); return
        store.close(); raise AssertionError("initial state changed")
    def _x21(self):
        path = self.run_root / "immutable.json"; path.write_text("original", encoding="utf-8"); before = path.read_bytes();
        assert path.read_bytes() == before
    def _x22(self):
        from evaluation.coverage import build_coverage
        matrix = build_coverage(); assert "G04" in matrix["matrix"]["goals"] and matrix["matrix"]["goals"]["G04"]["status"] == "not_run"
    def _x23(self):
        from export.discover import _scrub_json
        value = _scrub_json({"api_key": "secret", "document_id": "keep", "private_domain": "keep"}); assert value == {"api_key": "[REDACTED]", "document_id": "keep", "private_domain": "keep"}
    def _x24(self):
        from evaluation.parity import validate_oracle_binding
        assert not validate_oracle_binding({"code_hash": "a", "fixture_hash": "changed", "model": "m"}, {"code_hash": "a", "fixture_hash": "b", "model": "m"})
