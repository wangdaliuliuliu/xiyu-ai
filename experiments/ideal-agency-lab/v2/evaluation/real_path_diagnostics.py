"""Read-only diagnostics for source retrieval, concern persistence and grounding.

The module consumes existing trajectory evidence and uses one small offline
store probe for the positive concern path.  It never constructs a provider
request and never edits an existing trajectory.
"""
from __future__ import annotations

import json
import pathlib
import re
import sqlite3
import uuid
from copy import deepcopy
from typing import Any

from runtime.grounding import repair_decision
from runtime.context import ContextBuilder
from runtime.loop import AgencyLoop
from runtime.policy import Policy
from runtime.store import EventStore
from adapters.local import LocalAdapters
from controller.gateway import ScriptedGateway
from transport.sink import RecordingSink
from evaluation.j05_simulation import _resolve_event, _source_ref_materialized


RETRIEVAL_ACTIONS = {"catalog", "profile.read", "knowledge.search", "knowledge.read", "memory.search", "tasks.read", "research", "concerns.read"}


def _read_json(path: pathlib.Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: pathlib.Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _contains_exact_source(value: Any, source_ref: str, version: str = "") -> bool:
    if isinstance(value, dict):
        if any(_contains_exact_source(item, source_ref, version) for item in value.values()):
            return True
        return False
    if isinstance(value, list):
        return any(_contains_exact_source(item, source_ref, version) for item in value)
    if isinstance(value, str):
        if source_ref and source_ref in value:
            return True
        if version and value in {version, f"feishu-r{version}-data-fix-v3", f"feishu-r{version}"}:
            return True
    return False


def _records_row(records: dict[str, Any], venue: str = "ZHONGYING") -> dict[str, Any] | None:
    return next((item for item in records.get("data", []) if item.get("id") == f"WR-20260815-{venue}"), None)


def _trajectory_root(run_root: pathlib.Path, case_id: str, arm: str, repetition: int) -> pathlib.Path | None:
    for root_name in ("j05-trajectories-real", "worker-control-trajectories", "j05-trajectories"):
        candidate = run_root / root_name / arm / case_id / f"r{repetition:02d}"
        if (candidate / "state.db").exists():
            return candidate
    return None


def _db_snapshot(path: pathlib.Path) -> dict[str, Any]:
    db = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        traces = []
        for row in db.execute("SELECT event_id,step,payload_json,created_at FROM traces ORDER BY rowid"):
            payload = json.loads(row["payload_json"])
            traces.append({"event_id": row["event_id"], "step": row["step"], "created_at": row["created_at"], **payload})
        decisions = [row for row in traces if row.get("kind") in {"decision", "continuation_decision"}]
        provider_calls = [row for row in traces if row.get("kind") == "provider_call"]
        tool_results = [row for row in traces if row.get("kind") == "tool_result"]
        requests = []
        for row in db.execute("SELECT request_id,action_id,original_args_json,normalized_args_json,diff_json,result_json,created_at FROM tool_requests ORDER BY rowid"):
            item = dict(row)
            for key in ("original_args_json", "normalized_args_json", "diff_json", "result_json"):
                item[key[:-5]] = json.loads(item.pop(key))
            requests.append(item)
        concern_events = []
        for row in db.execute("SELECT id,concern_id,event_id,action_id,local_ref,expected_version,new_version,operation,patch_json,refs_json,recorded_at FROM concern_events ORDER BY event_record_id"):
            item = dict(row)
            item["patch"] = json.loads(item.pop("patch_json"))
            item["refs"] = json.loads(item.pop("refs_json"))
            concern_events.append(item)
        counts = {
            "concerns": int(db.execute("SELECT COUNT(*) FROM concerns WHERE status='active'").fetchone()[0]),
            "concern_events": len(concern_events),
            "tool_requests": len(requests),
            "provider_calls": len(provider_calls),
        }
        return {"traces": traces, "decisions": decisions, "provider_calls": provider_calls, "tool_results": tool_results, "tool_requests": requests, "concern_events": concern_events, "counts": counts}
    finally:
        db.close()


def _source_diagnosis(trajectory: pathlib.Path, events: list[dict[str, Any]], prompts: list[dict[str, Any]], db: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    snapshot = trajectory / "isolated-snapshot"
    context = _read_json(snapshot / "context.json", {})
    records = _read_json(snapshot / "workbench-data" / "runtime-state" / "records.json", {})
    new_refs = []
    for item in events:
        event = item.get("actual_event", item)
        if event.get("kind") == "opportunity":
            new_refs.extend(str(ref) for ref in (event.get("payload", {}).get("source_refs") or []))
    new_refs = list(dict.fromkeys(new_refs))
    requested_ref = new_refs[0] if new_refs else ""
    version_match = re.search(r"revision/(\d+)", requested_ref)
    new_version = version_match.group(1) if version_match else ""
    initial_facts = [item for item in case.get("initial_state", {}).get("facts", []) if "ZHONGYING" in str(item.get("selector", "")).upper()]
    initial_row = _records_row(records)
    source_presence = {
        "requested_source_ref": requested_ref,
        "requested_version": new_version,
        "exact_ref_in_context_snapshot": _contains_exact_source(context, requested_ref),
        "exact_ref_in_records_snapshot": _contains_exact_source(records, requested_ref),
        "version_materialized_in_context": _contains_exact_source(context, "", new_version),
        "version_materialized_in_records": _contains_exact_source(records, "", new_version),
        "records_row_source_revision": (initial_row or {}).get("sourceRevision"),
        "initial_facts": initial_facts,
        "source_snapshot_files": [str(path.relative_to(snapshot)) for path in snapshot.rglob("*") if path.is_file() and path.name in {"context.json", "records.json"}],
    }
    catalog = []
    prompt_rows = []
    for row in prompts:
        prompt = row.get("prompt", row)
        catalog = prompt.get("catalog", {}).get("resources", []) or catalog
        current_event = prompt.get("current", {}).get("event", {})
        prompt_rows.append({
            "call_index": row.get("call_index"),
            "event_id": current_event.get("event_id"),
            "event_kind": current_event.get("kind"),
            "visible_event_source_refs": current_event.get("payload", {}).get("source_refs", []),
            "catalog_tools": [item.get("tool") for item in prompt.get("catalog", {}).get("resources", [])],
            "prompt_has_requested_source_ref": _contains_exact_source(prompt, requested_ref),
            "prompt_has_materialized_new_source_content": _contains_exact_source(prompt, "", new_version) and not _contains_exact_source(prompt.get("catalog", {}), "", new_version),
            "background_mode": prompt.get("current", {}).get("background_mode") or prompt.get("background_mode"),
            "tool_result_in_prompt": prompt.get("tool_result"),
        })
    action_rows = []
    for item in db["decisions"]:
        decision = item.get("decision", {})
        action = decision.get("action", {}) or {}
        action_rows.append({
            "event_id": item.get("event_id"),
            "trace_kind": item.get("kind"),
            "action_type": action.get("type"),
            "query_params": action.get("args", {}),
            "basis_refs": decision.get("basis_refs", []),
            "messages": decision.get("messages", []),
        })
    attempted = [item for item in db["tool_requests"] if item.get("normalized_args") is not None]
    results = [{"event_id": item.get("event_id"), "tool_type": item.get("tool_type"), "status": (item.get("result") or {}).get("status"), "source_refs": (item.get("result") or {}).get("source_refs", []), "data": (item.get("result") or {}).get("data")} for item in db["tool_results"]]
    selected_reads = [item for item in action_rows if item.get("action_type") in RETRIEVAL_ACTIONS]
    if not source_presence["exact_ref_in_context_snapshot"] and not source_presence["exact_ref_in_records_snapshot"] and not source_presence["version_materialized_in_records"]:
        materialization_class = "source_absent_from_isolated_snapshot"
    else:
        materialization_class = "source_present_or_version_marker_present"
    if attempted and all(item.get("status") in {"not_found", "unavailable", "failed", "forbidden"} for item in results):
        retrieval_class = "retrieval_attempted_but_not_found_or_unavailable"
    elif attempted:
        retrieval_class = "retrieval_attempted_with_complete_result"
    else:
        retrieval_class = "retrieval_not_attempted"
    if selected_reads:
        model_class = "model_selected_read_action"
    else:
        model_class = "model_did_not_select_read_action"
    return {
        "trajectory": str(trajectory),
        "source_presence": source_presence,
        "catalog": catalog,
        "actual_prompt_path": str(trajectory / "actual-prompts.jsonl"),
        "prompt_rows": prompt_rows,
        "model_actions": action_rows,
        "actual_tool_requests": attempted,
        "actual_tool_results": results,
        "classification": {
            "materialization": materialization_class,
            "retrieval": retrieval_class,
            "model_choice": model_class,
            "do_not_conflate": ["资料是否存在", "工具是否检索到", "模型是否选择读取"],
        },
        "events_received": [{"event_id": item.get("actual_event", item).get("event_id"), "kind": item.get("actual_event", item).get("kind"), "payload": item.get("actual_event", item).get("payload")} for item in events],
    }


def _concern_diagnosis(trajectory: pathlib.Path, prompts: list[dict[str, Any]], db: dict[str, Any]) -> dict[str, Any]:
    prompt_rows = []
    for row in prompts:
        prompt = row.get("prompt", row)
        concern = prompt.get("concerns", {}) or {}
        current = prompt.get("current", {}) or {}
        prompt_rows.append({
            "call_index": row.get("call_index"),
            "event_id": (current.get("event") or {}).get("event_id"),
            "event_kind": (current.get("event") or {}).get("kind"),
            "enabled": concern.get("enabled"),
            "active_count": (concern.get("catalog") or {}).get("active_count"),
            "max_active": (concern.get("catalog") or {}).get("max_active"),
            "selected_count": len(concern.get("selected") or []),
            "updates_visible_before_call": concern.get("updates_since_last_event", []),
            "output_contract": {"concern_updates_max": (prompt.get("output_contract") or {}).get("concern_updates_max"), "has_concern_updates_field": "concern_updates" in (prompt.get("output_contract") or {}).get("fields", [])},
        })
    decision_rows = []
    for item in db["decisions"]:
        decision = item.get("decision", {})
        decision_rows.append({"event_id": item.get("event_id"), "trace_kind": item.get("kind"), "concern_updates": decision.get("concern_updates", []), "concern_ref": decision.get("concern_ref"), "concern_result": item.get("concern_result", {})})
    model_updates = [item for item in decision_rows if item["concern_updates"]]
    accepted = [item for item in decision_rows for result in (item.get("concern_result") or {}).get("accepted", [])]
    rejected = [item for item in decision_rows for result in (item.get("concern_result") or {}).get("rejected", [])]
    persisted_events = [item for item in db["concern_events"] if not str(item.get("event_id", "")).startswith("fixture:")]
    if not model_updates:
        classification = "model_did_not_propose_update"
    elif accepted and persisted_events:
        classification = "accepted_and_persisted"
    elif rejected and persisted_events:
        classification = "program_recorded_rejection_not_dropped"
    elif model_updates:
        classification = "proposed_update_not_observed_in_persistence"
    else:
        classification = "no_concern_delta_observed"
    return {
        "trajectory": str(trajectory),
        "actual_prompts": prompt_rows,
        "actual_decisions": decision_rows,
        "model_update_count": len(model_updates),
        "accepted_update_count": len(accepted),
        "rejected_update_count": len(rejected),
        "persisted_non_fixture_events": persisted_events,
        "classification": classification,
        "existing_contract_evidence": "offline-concerns-regression-20260909/concern-deterministic.json (T01-T14 passed, provider_calls=0)",
    }


def _positive_concern_probe(output: pathlib.Path) -> dict[str, Any]:
    probe_root = output / "positive-concern-probe"
    probe_root.mkdir(parents=True, exist_ok=False)
    db_path = probe_root / "state.db"
    store = EventStore(db_path)
    owner = "owner-a"
    ref = lambda path, status="observed", **extra: {"source_ref": f"fixture://{owner}/{path}", "epistemic_status": status, **extra}
    create = {"operation": "create", "concern_ref": "follow-up-1", "expected_version": None, "basis_refs": [ref("event/1")], "changes": {"title": "跟进经营资料", "desired_direction": "收到新资料后复核经营判断", "domain": "work", "origin": "observed_gap", "desire_refs": ["work_trust"], "known_summary": [ref("facts/1", "confirmed", summary="已有初始资料")], "unknowns": [ref("unknown/1", "unknown", impact="缺少新资料会影响判断")], "next_review_condition": {"type": "next_eligible_opportunity", "reason": "收到相关资料"}}}
    fixture = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "public_state.json"
    prompt = pathlib.Path(__file__).resolve().parents[1] / "runtime" / "prompts" / "concerns-v1.json"

    def decision(updates: list[dict[str, Any]], *, concern_ref: str | None, intention_ref: str | None) -> dict[str, Any]:
        return {"operation": "continue", "intention_ref": intention_ref, "desired_change": "收到新资料后继续复核经营判断", "basis_refs": [f"fixture://{owner}/event/1"], "action": {"type": "deliver", "args": {}, "expected_result": "deliver"}, "strategy_reason": "当前事件有持续跟进价值", "expected_participation": None, "reconsider_condition": "收到下一份相关资料", "messages": ["我先把这条跟进保存下来。"], "concern_ref": concern_ref, "task_ref": None, "concern_updates": updates}

    first_event = {"event_id": "probe-event-1", "owner": owner, "kind": "user_message", "virtual_time": "2026-09-09T10:00:00+08:00", "payload": {"input_origin": "user", "text": "这份经营资料后面还要继续核对。"}}
    first_gateway = ScriptedGateway([decision([create], concern_ref="follow-up-1", intention_ref=None)])
    loop = AgencyLoop(store=store, context=ContextBuilder(fixture, prompt, store=store, concerns_enabled=True), adapters=LocalAdapters(fixture, store=store, concerns_enabled=True), policy=Policy(store, writable_root=probe_root, concerns_enabled=True), gateway=first_gateway, sink=RecordingSink(probe_root / "traces" / "sink.jsonl"), trace_path=probe_root / "traces" / "trace.jsonl")
    first_result = loop.process_event(first_event)
    concern_id = first_result.get("concern_id")
    intention_id = first_result.get("intention_id")
    version_after_contact = int((store.get_concern(owner, concern_id) or {}).get("version", -1))
    update = {"operation": "update", "concern_ref": concern_id, "expected_version": version_after_contact, "basis_refs": [ref("event/2")], "changes": {"known_summary": [ref("facts/2", "confirmed", summary="新资料已到达")], "next_review_condition": {"type": "new_source_version", "source_ref": f"fixture://{owner}/source", "version": "v2"}}}
    second_event = {"event_id": "probe-event-2", "owner": owner, "kind": "user_message", "virtual_time": "2026-09-09T11:00:00+08:00", "payload": {"input_origin": "user", "text": "新资料到了，沿着刚才那条继续核对。"}}
    # The first delivery completes its one-shot intention.  The second event
    # is intentionally a new action over the same concern; requiring the
    # completed intention to be reused would test an unrelated terminal-state
    # policy instead of concern continuity.
    second_gateway = ScriptedGateway([decision([update], concern_ref=concern_id, intention_ref=None)])
    loop.gateway = second_gateway
    second_result = loop.process_event(second_event)
    created = {"first_result": first_result}
    updated = {"second_result": second_result}
    final = store.get_concern(owner, concern_id)
    events = store.recent_concern_events(owner, limit=10)
    store.close()
    update_event_present = any(item.get("operation") == "update" and item.get("event_id") == "probe-event-2" for item in events)
    return {"status": "passed" if first_result.get("status") == "delivered" and second_result.get("status") == "delivered" and final and final["version"] == version_after_contact + 2 and update_event_present else "failed", "provider_calls": 0, "same_agency_loop_executor": True, "created": created, "updated": updated, "version_after_contact": version_after_contact, "final": final, "events": events, "state_db": str(db_path), "trace": str(probe_root / "traces" / "trace.jsonl")}


def _grounding_regression(output: pathlib.Path | None = None) -> dict[str, Any]:
    def decision(message: str) -> dict[str, Any]:
        return {"operation": "continue", "intention_ref": None, "desired_change": "回答经营问题", "basis_refs": ["snapshot://owner-a/facts"], "action": {"type": "deliver", "args": {}, "expected_result": "deliver"}, "strategy_reason": "answer", "expected_participation": None, "reconsider_condition": "new input", "messages": [message], "concern_ref": None, "task_ref": None, "concern_updates": []}
    no_evidence, no_evidence_meta = repair_decision(decision("这周东坝整体经营数据稳中有升。"), context={"stable": {}, "current": {"event": {"payload": {"text": "查看东坝数据"}}}})
    resident, resident_meta = repair_decision(decision("东坝本周客流是183。"), context={"stable": {"enterprise_profile_summary": {"东坝": {"traffic": 183}}}, "current": {}})
    tool, tool_meta = repair_decision(decision("东坝8月21日客流是291。"), context={"stable": {}, "current": {}}, tool_result={"status": "complete", "data": {"store": "东坝", "business_date": "2026-08-21", "traffic": 291}, "source_refs": ["fixture://owner-a/facts"], "scope": "owner-a", "version": "v1", "trace_id": "probe", "completeness": "complete"})
    honest, honest_meta = repair_decision(decision("这次还没查到东坝的经营明细，我先不下结论。"), context={"stable": {}, "current": {}})
    question, question_meta = repair_decision(decision("东坝这周经营数据怎么样？"), context={"stable": {}, "current": {}})
    cases = {"unsupported_positive_repaired": {"passed": no_evidence_meta.get("repaired") is True, "assessment": no_evidence_meta, "messages": no_evidence["messages"]}, "resident_context_allowed": {"passed": resident_meta.get("repaired") is False, "assessment": resident_meta}, "complete_tool_result_allowed": {"passed": tool_meta.get("repaired") is False, "assessment": tool_meta}, "honest_missing_evidence_allowed": {"passed": honest_meta.get("repaired") is False, "assessment": honest_meta}, "business_question_allowed": {"passed": question_meta.get("repaired") is False and question["messages"] == ["东坝这周经营数据怎么样？"], "assessment": question_meta, "messages": question["messages"]}}
    loop_probe = {"status": "not_run", "provider_calls": 0}
    if output is not None:
        probe_root = output / "grounding-loop-probe"
        probe_root.mkdir(parents=True, exist_ok=False)
        fixture = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "public_state.json"
        prompt = pathlib.Path(__file__).resolve().parents[1] / "runtime" / "prompts" / "concerns-v1.json"
        store = EventStore(probe_root / "state.db")
        sink = RecordingSink(probe_root / "traces" / "sink.jsonl")
        loop = AgencyLoop(
            store=store,
            context=ContextBuilder(fixture, prompt, store=store, concerns_enabled=False),
            adapters=LocalAdapters(fixture, store=store, concerns_enabled=False),
            policy=Policy(store, writable_root=probe_root, concerns_enabled=False),
            gateway=ScriptedGateway([decision("这周东坝整体经营数据稳中有升。")]),
            sink=sink,
            trace_path=probe_root / "traces" / "trace.jsonl",
        )
        event = {"event_id": "grounding-probe-event", "owner": "owner-a", "kind": "user_message", "virtual_time": "2026-09-09T12:00:00+08:00", "payload": {"input_origin": "user", "text": "帮我看看东坝这周的经营情况。"}}
        result = loop.process_event(event)
        traces = _read_jsonl(probe_root / "traces" / "trace.jsonl")
        delivered = _read_jsonl(probe_root / "traces" / "sink.jsonl")
        delivered_text = [item.get("attempt", {}).get("payload", {}).get("text") for item in delivered]
        repair_traces = [item for item in traces if item.get("kind") == "grounding_repair"]
        store.close()
        loop_probe = {
            "status": "passed" if result.get("status") == "delivered" and repair_traces and delivered_text == [no_evidence["messages"][0]] else "failed",
            "provider_calls": 0,
            "result": result,
            "delivered_text": delivered_text,
            "grounding_traces": repair_traces,
            "state_db": str(probe_root / "state.db"),
            "trace": str(probe_root / "traces" / "trace.jsonl"),
            "sink": str(probe_root / "traces" / "sink.jsonl"),
        }
    cases["agency_loop_applies_repair"] = loop_probe
    status = "passed" if all(item.get("passed", False) for name, item in cases.items() if name != "agency_loop_applies_repair") and loop_probe.get("status") == "passed" else "failed"
    return {"status": status, "provider_calls": 0, "cases": cases}


def _workbench_snapshot_query_probe(trajectory: pathlib.Path) -> dict[str, Any]:
    """Check the existing snapshot-backed read path without a model/provider call."""
    snapshot = trajectory / "isolated-snapshot"
    manifest_path = trajectory.parents[3] / "manifest.json"
    context = _read_json(snapshot / "context.json", {})
    owners = list((context.get("owners") or {}).keys())
    owner = owners[0] if owners else None
    if not owner:
        return {"status": "failed", "reason": "snapshot_owner_missing", "provider_calls": 0}
    try:
        adapter = LocalAdapters(snapshot_root=snapshot, manifest_path=manifest_path)
        result = adapter.execute(owner, "knowledge.search", {"query": "中影店客流"})
    except Exception as exc:  # preserve the exact local failure in the artifact
        return {"status": "failed", "reason": f"{type(exc).__name__}:{exc}", "provider_calls": 0}
    rows = result.get("data") if isinstance(result.get("data"), list) else []
    workbench_rows = [row for row in rows if isinstance(row, dict) and row.get("source_revision")]
    refs = [str(ref) for ref in result.get("source_refs", [])]
    revisions = sorted({str(row.get("source_revision")) for row in workbench_rows})
    passed = result.get("status") == "complete" and bool(workbench_rows) and any("/revision/9753/" in ref for ref in refs) and "9754" not in " ".join(refs)
    return {
        "status": "passed" if passed else "failed",
        "provider_calls": 0,
        "query": "中影店客流",
        "result_status": result.get("status"),
        "row_count": len(rows),
        "workbench_row_count": len(workbench_rows),
        "source_refs": refs,
        "source_revisions": revisions,
        "sample_rows": workbench_rows[:3],
        "interpretation": "existing frozen 9753 rows are retrievable through the declared knowledge.search path; this does not fabricate or stand in for the absent requested 9754 source",
    }


def _source_guard_probe(trajectory: pathlib.Path) -> dict[str, Any]:
    snapshot = trajectory / "isolated-snapshot"
    old_ref = "feishu://ImtOsrt7yhTAbptIGPncik1mn2q/revision/9753/中影店"
    requested_ref = "feishu://ImtOsrt7yhTAbptIGPncik1mn2q/revision/9754/中影店"
    event = {"event_id": "source-guard-probe", "owner": "account:1:companion:1", "kind": "opportunity", "virtual_time": "2026-09-09T11:00:00+08:00", "payload": {"source_refs": [requested_ref]}}
    _, resolution = _resolve_event(event, None, snapshot)
    passed = _source_ref_materialized(snapshot, old_ref) and not _source_ref_materialized(snapshot, requested_ref) and resolution.get("status") == "fixture_branch_gap" and resolution.get("reason") == "opportunity_source_not_materialized"
    return {"status": "passed" if passed else "failed", "provider_calls": 0, "known_materialized_ref": old_ref, "requested_ref": requested_ref, "known_materialized": _source_ref_materialized(snapshot, old_ref), "requested_materialized": _source_ref_materialized(snapshot, requested_ref), "resolution": resolution, "interpretation": "an opportunity cannot be treated as a source arrival until its referenced version is materialized in the isolated snapshot"}


def _render_markdown(result: dict[str, Any]) -> str:
    lines = ["# Real-path diagnostics (offline)", "", f"- status: `{result['status']}`", "- provider calls made: `0`", "- existing real trajectories were read-only; no old evidence was rewritten", "", "## K12 source path", ""]
    for row in result["source_diagnoses"]:
        c = row["classification"]
        s = row["source_presence"]
        lines.extend([f"### {row['arm']} / K12 / r{row['repetition']:02d}", "", f"- snapshot source revision: `{s.get('records_row_source_revision')}`; requested: `{s.get('requested_source_ref')}`", f"- exact new source in snapshot: `{s.get('exact_ref_in_records_snapshot')}`; version marker in records: `{s.get('version_materialized_in_records')}`", f"- catalog tools: `{', '.join(str(x.get('tool')) for x in row.get('catalog', []))}`", f"- retrieval: `{c['retrieval']}`; model choice: `{c['model_choice']}`; materialization: `{c['materialization']}`", f"- actual tool requests: `{len(row['actual_tool_requests'])}`; actual tool results: `{len(row['actual_tool_results'])}`", ""])
        for action in row["model_actions"]:
            lines.append(f"  - `{action['action_type']}` params `{json.dumps(action['query_params'], ensure_ascii=False)}`; messages `{json.dumps(action['messages'], ensure_ascii=False)}`")
        for tool in row["actual_tool_results"]:
            lines.append(f"  - tool result `{tool['tool_type']}`: status `{tool['status']}`, refs `{json.dumps(tool['source_refs'], ensure_ascii=False)}`")
        lines.append("")
    probe = result["workbench_snapshot_query_probe"]
    lines += ["## Existing snapshot read-path probe", "", f"- status: `{probe['status']}`; query `{probe.get('query')}`; returned rows `{probe.get('row_count', 0)}`; workbench rows `{probe.get('workbench_row_count', 0)}`; refs `{json.dumps(probe.get('source_refs', []), ensure_ascii=False)}`", f"- interpretation: {probe.get('interpretation', probe.get('reason', ''))}", ""]
    guard = result["source_guard_probe"]
    lines += ["## Source materialization guard", "", f"- status: `{guard.get('status', 'not_run')}`; known 9753 materialized `{guard.get('known_materialized', False)}`; requested 9754 materialized `{guard.get('requested_materialized', False)}`; resolution `{json.dumps(guard.get('resolution', {}), ensure_ascii=False)}`", f"- interpretation: {guard.get('interpretation', guard.get('reason', 'source guard was not run'))}", "", "## C concern path", ""]
    for row in result["concern_diagnoses"]:
        first_prompt = (row.get("actual_prompts") or [{}])[0]
        lines.extend([f"### {row['arm']} / K12 / r{row['repetition']:02d}", "", f"- classification: `{row['classification']}`; prompt update count: `{row['model_update_count']}`; accepted: `{row['accepted_update_count']}`; rejected: `{row['rejected_update_count']}`", f"- visible protocol: enabled `{first_prompt.get('enabled')}`; active `{first_prompt.get('active_count')}`/max `{first_prompt.get('max_active')}`; selected `{first_prompt.get('selected_count')}`; output field `{first_prompt.get('output_contract', {}).get('has_concern_updates_field')}`; max updates `{first_prompt.get('output_contract', {}).get('concern_updates_max')}`", f"- non-fixture persisted concern events: `{len(row['persisted_non_fixture_events'])}`", ""])
    lines += ["## Positive concern path", "", f"- offline create → update → persisted version: `{result['positive_concern_probe']['status']}`", f"- existing T01–T14 contract evidence: `{result['positive_concern_probe']['existing_contract_evidence']}`", "", "## Grounding repair", "", f"- regression status: `{result['grounding_regression']['status']}`", "- repairs only unsupported positive business deliveries; resident evidence, complete tool evidence and honest uncertainty remain deliverable.", ""]
    return "\n".join(lines)


def write_real_path_diagnostics(run_paths: list[pathlib.Path], output: pathlib.Path, *, case_id: str = "K12") -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False)
    case_manifest = _read_json(run_paths[0] / "case-manifest.json", {})
    case = next((item for item in case_manifest.get("cases", []) if item.get("case_id") == case_id), {})
    source_diagnoses = []
    concern_diagnoses = []
    missing = []
    for run_root in run_paths:
        for arm in ("A", "B", "C"):
            trajectory = _trajectory_root(run_root, case_id, arm, 1)
            if trajectory is None:
                missing.append({"run": str(run_root), "arm": arm, "case_id": case_id})
                continue
            events = _read_jsonl(trajectory / "input-events.jsonl")
            prompts = _read_jsonl(trajectory / "actual-prompts.jsonl")
            db = _db_snapshot(trajectory / "state.db")
            row = _source_diagnosis(trajectory, events, prompts, db, case)
            row.update({"run": str(run_root), "arm": arm, "case_id": case_id, "repetition": 1})
            source_diagnoses.append(row)
            concern = _concern_diagnosis(trajectory, prompts, db)
            concern.update({"run": str(run_root), "arm": arm, "case_id": case_id, "repetition": 1})
            concern_diagnoses.append(concern)
    positive = _positive_concern_probe(output)
    positive["existing_contract_evidence"] = str(run_paths[0].parent / "offline-concerns-regression-20260909" / "concern-deterministic.json")
    grounding = _grounding_regression(output)
    probe_trajectory = next((path for path in (run_paths[0] / "j05-trajectories-real" / "A" / case_id).glob("r01") if path.is_dir()), None) if run_paths else None
    snapshot_probe = _workbench_snapshot_query_probe(probe_trajectory) if probe_trajectory else {"status": "failed", "reason": "run_missing", "provider_calls": 0}
    guard_probe = _source_guard_probe(probe_trajectory) if probe_trajectory else {"status": "failed", "reason": "run_missing", "provider_calls": 0}
    result = {"schemaVersion": "real-path-diagnostics-v1", "status": "passed" if source_diagnoses and snapshot_probe["status"] == "passed" and guard_probe["status"] == "passed" and positive["status"] == "passed" and grounding["status"] == "passed" else "incomplete", "provider_calls": 0, "run_paths": [str(path) for path in run_paths], "source_diagnoses": source_diagnoses, "concern_diagnoses": concern_diagnoses, "missing_trajectories": missing, "workbench_snapshot_query_probe": snapshot_probe, "source_guard_probe": guard_probe, "positive_concern_probe": positive, "grounding_regression": grounding, "scope": "offline read-only diagnosis and targeted local contract probe; no real provider execution"}
    (output / "real-path-diagnostics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    (output / "real-path-diagnostics.md").write_text(_render_markdown(result), encoding="utf-8")
    return {"status": result["status"], "provider_calls_made": 0, "trajectories_read": len(source_diagnoses), "output": str(output)}
