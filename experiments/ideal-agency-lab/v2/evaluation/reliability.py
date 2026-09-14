"""Formal offline controls for the R01-R12 reliability denominator.

These controls use the same experiment store, loop, adapters, context builder
and sink as the runtime.  They never replace semantic/API runs: the result is
labelled ``deterministic_formal_control`` and provider_calls remains zero.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import uuid
from copy import deepcopy
from typing import Any, Callable

from adapters.local import AdapterError, LocalAdapters
from controller.gateway import ProviderResponse, ScriptedGateway
from evaluation.harness import VALID_DECISION, _event
from runtime.context import ContextBuilder
from runtime.loop import AgencyLoop
from runtime.policy import Policy, PolicyError
from runtime.store import EventStore, StoreError
from transport.sink import RecordingSink


def _loop(case_root: pathlib.Path, run_root: pathlib.Path, owner: str, responses: list[Any], *, outcomes: dict[str, str] | None = None) -> tuple[AgencyLoop, EventStore, ScriptedGateway]:
    case_root.mkdir(parents=True, exist_ok=False)
    store = EventStore(case_root / "state.db")
    manifest_path = run_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    gateway = ScriptedGateway(responses)
    loop = AgencyLoop(
        store=store,
        context=ContextBuilder(snapshot_root=run_root / "snapshot", prompt_path=pathlib.Path(manifest["prompt_path"]), manifest_path=manifest_path),
        adapters=LocalAdapters(snapshot_root=run_root / "snapshot", manifest_path=manifest_path, store=store),
        policy=Policy(store, writable_root=case_root),
        gateway=gateway,
        sink=RecordingSink(case_root / "traces" / "sink.jsonl", outcomes),
        trace_path=case_root / "traces" / "trace.jsonl",
    )
    return loop, store, gateway


def _decision_with_basis(decision: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(decision)
    value["basis_refs"] = ["snapshot://owner/profile"]
    return value


def _tool_failure_decision() -> dict[str, Any]:
    decision = _decision_with_basis(VALID_DECISION)
    decision["action"] = {"type": "knowledge.search", "args": {"query": "__reliability_missing__"}, "expected_result": "明确的not_found结果"}
    decision["messages"] = []
    return decision


def _r01(case_root: pathlib.Path, run_root: pathlib.Path, owner: str) -> dict[str, Any]:
    loop, store, gateway = _loop(case_root, run_root, owner, [_decision_with_basis(VALID_DECISION)])
    event = _event(f"r01-{uuid.uuid4()}", owner=owner)
    first, second = loop.process_event(event), loop.process_event(event)
    assert first["status"] == "delivered" and second["status"] == "duplicate" and len(gateway.calls) == 1
    assert store.conn.execute("SELECT COUNT(*) FROM events WHERE event_id=?", (event["event_id"],)).fetchone()[0] == 1
    store.close()
    return {"normal": "first event delivered", "failure": "duplicate event rejected", "recovery": "original event remains single"}


def _r02(case_root: pathlib.Path, run_root: pathlib.Path, owner: str) -> dict[str, Any]:
    case_root.mkdir(parents=True, exist_ok=False)
    state_path = case_root / "state.db"
    first, second = EventStore(state_path), EventStore(state_path)
    first.acquire_lease(owner)
    try:
        second.acquire_lease(owner)
    except StoreError as exc:
        assert str(exc) == "lease_conflict"
    else:
        raise AssertionError("lease conflict was not rejected")
    first.release_lease(owner); first.close(); second.close()
    return {"normal": "first worker owns lease", "failure": "second worker rejected", "recovery": "lease can be released"}


def _r03(case_root: pathlib.Path, run_root: pathlib.Path, owner: str) -> dict[str, Any]:
    case_root.mkdir(parents=True, exist_ok=False)
    first, second = EventStore(case_root / "state.db"), EventStore(case_root / "state.db")
    first.ensure_thread(owner, {"initial": "r03"})
    assert first.bump_thread_version(owner, 0) == 1
    try:
        second.bump_thread_version(owner, 0)
    except StoreError as exc:
        assert str(exc) == "version_conflict"
    else:
        raise AssertionError("stale CAS update was accepted")
    first.close(); second.close()
    return {"normal": "version 0 advanced once", "failure": "stale version rejected", "recovery": "new version remains authoritative"}


def _r04(case_root: pathlib.Path, run_root: pathlib.Path, owner: str) -> dict[str, Any]:
    loop, store, _ = _loop(case_root, run_root, owner, [_tool_failure_decision(), _decision_with_basis(VALID_DECISION)])
    result = loop.process_event(_event(f"r04-{uuid.uuid4()}", owner=owner))
    row = store.conn.execute("SELECT result_json FROM tool_requests ORDER BY created_at DESC LIMIT 1").fetchone()
    assert row is not None and json.loads(row[0])["status"] == "not_found"
    assert result["status"] == "delivered"
    store.close()
    return {"normal": "formal tool request recorded", "failure": "not_found retained instead of fabricated data", "recovery": "same loop delivered an explicit continuation"}


def _delivery_control(case_root: pathlib.Path, run_root: pathlib.Path, owner: str, status: str, label: str) -> dict[str, Any]:
    loop, store, _ = _loop(case_root, run_root, owner, [_decision_with_basis(VALID_DECISION)], outcomes={"*": status})
    result = loop.process_event(_event(f"{label}-{uuid.uuid4()}", owner=owner))
    assert result["status"] == status
    assert store.conn.execute("SELECT state FROM actions ORDER BY created_at DESC LIMIT 1").fetchone()[0] == status
    store.close()
    return {"normal": "delivery attempted", "failure": f"{status} receipt preserved", "recovery": "state remains queryable after close"}


def _r05(case_root: pathlib.Path, run_root: pathlib.Path, owner: str) -> dict[str, Any]:
    return _delivery_control(case_root, run_root, owner, "partial", "r05")


def _r06(case_root: pathlib.Path, run_root: pathlib.Path, owner: str) -> dict[str, Any]:
    return _delivery_control(case_root, run_root, owner, "unknown", "r06")


def _r07(case_root: pathlib.Path, run_root: pathlib.Path, owner: str) -> dict[str, Any]:
    loop, store, _ = _loop(case_root, run_root, owner, [_decision_with_basis(VALID_DECISION)], outcomes={"*": "unknown"})
    result = loop.process_event(_event(f"r07-{uuid.uuid4()}", owner=owner))
    assert result["status"] == "unknown"
    store.close()
    reopened = EventStore(case_root / "state.db")
    assert reopened.conn.execute("SELECT state FROM actions ORDER BY created_at DESC LIMIT 1").fetchone()[0] == "unknown"
    reopened.close()
    return {"normal": "unknown delivery written", "failure": "restart does not erase it", "recovery": "durable state can be inspected"}


def _r08(case_root: pathlib.Path, run_root: pathlib.Path, owner: str) -> dict[str, Any]:
    manifest_path = run_root / "manifest.json"
    store = EventStore(case_root / "state.db")
    adapter = LocalAdapters(snapshot_root=run_root / "snapshot", manifest_path=manifest_path, store=store)
    proposal = adapter.execute(owner, "knowledge.propose", {"candidate": "R08 candidate", "scope": owner})
    candidate_id = proposal["data"]["candidate_id"]
    denied = adapter.execute(owner, "knowledge.confirm", {"candidate_id": candidate_id, "authorized": True})
    assert denied["status"] == "forbidden"
    store.record_user_confirmation(owner, candidate_id, f"r08-{uuid.uuid4()}", "嗯", False)
    rejected = adapter.execute(owner, "knowledge.confirm", {"candidate_id": candidate_id, "authorized": True})
    assert rejected["status"] == "forbidden"
    store.record_user_confirmation(owner, candidate_id, f"r08-{uuid.uuid4()}", "我明确确认", True)
    confirmed = adapter.execute(owner, "knowledge.confirm", {"candidate_id": candidate_id, "authorized": True})
    assert confirmed["status"] == "complete"
    store.close()
    return {"normal": "candidate proposed", "failure": "model authorized flag and rejected reply cannot confirm", "recovery": "trusted accepted event confirms"}


def _r09(case_root: pathlib.Path, run_root: pathlib.Path, owner: str) -> dict[str, Any]:
    case_root.mkdir(parents=True, exist_ok=False)
    manifest_path = run_root / "manifest.json"
    adapter = LocalAdapters(snapshot_root=run_root / "snapshot", manifest_path=manifest_path, store=EventStore(case_root / "state.db"))
    try:
        adapter.execute(owner, "profile.read", {"owner": "another-owner"})
    except AdapterError as exc:
        assert str(exc) == "forbidden:owner_scope"
    else:
        raise AssertionError("cross-owner read was accepted")
    adapter.store.close()
    return {"normal": "owner-bound read path", "failure": "cross-owner request rejected", "recovery": "no cross-owner result returned"}


def _r10(case_root: pathlib.Path, run_root: pathlib.Path, owner: str) -> dict[str, Any]:
    manifest_path = run_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    builder = ContextBuilder(snapshot_root=run_root / "snapshot", prompt_path=pathlib.Path(manifest["prompt_path"]), manifest_path=manifest_path)
    owner_data = builder.owner_data(owner)
    future = next((item for item in owner_data.get("schedule", []) if item.get("starts_at")), None)
    if not future:
        raise AssertionError("no dated schedule fixture available for R10")
    starts_at = future["starts_at"]
    start = dt.datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
    before = (start - dt.timedelta(minutes=1)).isoformat()
    event_before = _event(f"r10-before-{uuid.uuid4()}", owner=owner); event_before["virtual_time"] = before
    event_after = _event(f"r10-after-{uuid.uuid4()}", owner=owner); event_after["virtual_time"] = start.isoformat()
    visible_before = builder.build(event_before)["current"]["schedule"]
    visible_after = builder.build(event_after)["current"]["schedule"]
    assert all(item.get("starts_at") != starts_at for item in visible_before)
    assert any(item.get("starts_at") == starts_at for item in visible_after)
    return {"normal": "dated schedule fixture", "failure": "future row hidden before starts_at", "recovery": "row visible at valid virtual time"}


def _r11(case_root: pathlib.Path, run_root: pathlib.Path, owner: str) -> dict[str, Any]:
    loop, store, gateway = _loop(case_root, run_root, owner, [ProviderResponse("r11-timeout", "deterministic", {}, finish_reason="error", error="timeout"), _decision_with_basis(VALID_DECISION)])
    result = loop.process_event(_event(f"r11-{uuid.uuid4()}", owner=owner))
    assert result["status"] == "delivered" and len(gateway.calls) == 2
    budget = store.conn.execute("SELECT model_calls,infra_retries FROM budgets WHERE owner=?", (owner,)).fetchone()
    assert budget[1] == 1
    store.close()
    return {"normal": "provider call counted", "failure": "timeout consumes bounded retry budget", "recovery": "successful retry remains in same trace"}


def _r12(case_root: pathlib.Path, run_root: pathlib.Path, owner: str) -> dict[str, Any]:
    loop, store, gateway = _loop(case_root, run_root, owner, [ProviderResponse("r12-timeout", "deterministic", {}, finish_reason="error", error="timeout"), _decision_with_basis(VALID_DECISION)])
    result = loop.process_event(_event(f"r12-{uuid.uuid4()}", owner=owner))
    assert result["status"] == "delivered" and len(gateway.calls) == 2
    raw = sorted((case_root / "traces" / "raw-responses").glob("*.json"))
    assert len(raw) == 2 and raw[0].read_bytes() != raw[1].read_bytes()
    store.close()
    return {"normal": "two provider attempts have raw refs", "failure": "repeated response IDs cannot overwrite", "recovery": "trace and raw response files remain append-only"}


CONTROLS: dict[str, Callable[[pathlib.Path, pathlib.Path, str], dict[str, Any]]] = {
    "R01": _r01, "R02": _r02, "R03": _r03, "R04": _r04, "R05": _r05, "R06": _r06,
    "R07": _r07, "R08": _r08, "R09": _r09, "R10": _r10, "R11": _r11, "R12": _r12,
}


def run_reliability_controls(run_root: pathlib.Path, attempt_root: pathlib.Path, entries: list[dict[str, Any]], models: list[dict[str, Any]], owner: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    failures = 0
    for entry in entries:
        case_runs: list[dict[str, Any]] = []
        for model in models:
            for repetition in range(1, 6):
                case_root = attempt_root / "controls" / entry["reliability_id"] / str(model.get("role", "model")) / f"repeat-{repetition:02d}"
                try:
                    evidence = CONTROLS[entry["reliability_id"]](case_root, run_root, owner)
                    case_runs.append({"model_role": model.get("role"), "model_label": model.get("label"), "repetition": repetition, "status": "passed", "evidence": evidence, "path": str(case_root)})
                except Exception as exc:
                    failures += 1
                    case_runs.append({"model_role": model.get("role"), "model_label": model.get("label"), "repetition": repetition, "status": "failed", "error": f"{type(exc).__name__}: {exc}", "path": str(case_root)})
        rows.append({"case_id": entry["entry_id"], "reliability_id": entry["reliability_id"], "status": "passed" if case_runs and all(item["status"] == "passed" for item in case_runs) else "failed", "runs": case_runs})
    return {"status": "completed" if failures == 0 else "completed_with_failures", "execution": "completed", "mode": "deterministic_formal_control", "provider_calls": 0, "failures": failures, "rows": rows}
