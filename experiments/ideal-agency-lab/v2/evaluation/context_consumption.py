"""C02 context binding and counterfactual checks."""
from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import shutil
from typing import Any

from runtime.context import ContextBuilder, ContextError
from runtime.prompts.assemble import assemble
from adapters.local import AdapterError, LocalAdapters
from runtime.store import EventStore


def _event(owner: str, event_id: str, business_date: str = "2026-09-08") -> dict[str, Any]:
    return {"event_id": event_id, "owner": owner, "kind": "user_message", "virtual_time": business_date + "T10:00:00+08:00", "payload": {"text": "请基于当前可核验资料给出下一步"}}


def run_context_consumption(run_root: pathlib.Path) -> dict[str, Any]:
    manifest = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))
    inventory = json.loads((run_root / "inventory.json").read_text(encoding="utf-8"))
    snapshot = run_root / "snapshot"
    manifest_path = run_root / "manifest.json"
    binding = manifest.get("snapshot_binding", {})
    builder = ContextBuilder(snapshot_root=snapshot, prompt_path=pathlib.Path(manifest["prompt_path"]), manifest_path=manifest_path)
    owner_keys = sorted(builder.fixture.get("owners", {}).keys())
    records: list[dict[str, Any]] = []
    for index, owner in enumerate(owner_keys):
        event = _event(owner, f"context-consumption-{index}")
        context = builder.build(event)
        prompt = assemble(context, event=event)
        prompt_hash = hashlib.sha256(json.dumps(prompt, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        records.append({
            "owner": owner, "input": event, "snapshot_id": context["source_binding"]["snapshot_id"], "snapshot_version": context["source_binding"]["version"],
            "context_version": context["context_version"], "stable_source_refs": context["stable"]["sources"], "catalog": context["catalog"],
            "actual_prompt_hash": prompt_hash, "actual_prompt_locator": str(run_root / "context-prompts" / f"{index:02d}.json"),
            "tool_source_policy": "owner-filtered snapshot adapters; no full-database prompt injection", "status": "prepared_not_called",
        })
        prompt_path = run_root / "context-prompts" / f"{index:02d}.json"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(json.dumps(prompt, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")

    counterfactual: dict[str, Any] = {"status": "not_run"}
    if owner_keys:
        source = builder.fixture
        baseline_owner = owner_keys[0]
        baseline = copy.deepcopy(source)
        changed = copy.deepcopy(source)
        changed["owners"][baseline_owner]["profile"]["role"] = "counterfactual-role"
        changed["owners"][baseline_owner].setdefault("stable", {}).setdefault("enterprise_profile", {})["role"] = "counterfactual-role"
        if changed["owners"][baseline_owner].get("facts"):
            changed["owners"][baseline_owner]["facts"][0]["value"] = "counterfactual-value"
        cf_dir = run_root / "context-counterfactual"
        if cf_dir.exists():
            shutil.rmtree(cf_dir)
        cf_dir.mkdir()
        baseline_path = cf_dir / "baseline.json"
        changed_path = cf_dir / "changed.json"
        baseline_path.write_text(json.dumps(baseline, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        changed_path.write_text(json.dumps(changed, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        base_builder = ContextBuilder(baseline_path, pathlib.Path(manifest["prompt_path"]))
        changed_builder = ContextBuilder(changed_path, pathlib.Path(manifest["prompt_path"]))
        base_context = base_builder.build(_event(baseline_owner, "counterfactual-baseline"))
        changed_context = changed_builder.build(_event(baseline_owner, "counterfactual-changed"))
        base_prompt = assemble(base_context, event=_event(baseline_owner, "counterfactual-baseline"))
        changed_prompt = assemble(changed_context, event=_event(baseline_owner, "counterfactual-changed"))
        counterfactual = {
            "status": "passed" if base_context["context_version"] != changed_context["context_version"] and base_context["stable"]["enterprise_profile_summary"].get("role") != changed_context["stable"]["enterprise_profile_summary"].get("role") else "failed",
            "changed_field": "owners[].profile.role and facts[0].value",
            "baseline_context_version": base_context["context_version"], "changed_context_version": changed_context["context_version"],
            "baseline_prompt_hash": hashlib.sha256(json.dumps(base_prompt, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest(),
            "changed_prompt_hash": hashlib.sha256(json.dumps(changed_prompt, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest(),
            "old_result_reuse": False, "independent_oracle_binding": "required; not available to worker",
        }

    scope_probe: dict[str, Any] = {"status": "not_run"}
    if owner_keys:
        db = run_root / "context-scope-probe.db"
        store = EventStore(db)
        adapter = LocalAdapters(snapshot_root=snapshot, manifest_path=manifest_path, store=store)
        other = "account:other:companion:other"
        try:
            adapter.execute(owner_keys[0], "profile.read", {"owner": other})
        except AdapterError as exc:
            scope_probe = {"status": "passed", "reason": str(exc)}
        finally:
            store.close()

    offline_status = "passed" if records and counterfactual.get("status") == "passed" and scope_probe.get("status") == "passed" else "failed"
    provider_calls = 0
    result = {
        "schemaVersion": "context-consumption-v1",
        "status": "incomplete" if offline_status == "passed" and provider_calls == 0 else offline_status,
        "offline_preparation_status": offline_status,
        "real_provider_calls": provider_calls,
        "completion_blocker": "real model request and tool-result binding are required by C02" if provider_calls == 0 else None,
        "manifest_binding": binding, "inventory_context_dataset": inventory.get("context_dataset"), "records": records,
        "counterfactual": counterfactual, "scope_probe": scope_probe,
        "note": "This artifact proves snapshot-to-prompt preparation and counterfactual binding; it is not a real API quality result.",
    }
    (run_root / "context-consumption.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return result


def merge_provider_evidence(run_root: pathlib.Path, trace_roots: list[pathlib.Path]) -> dict[str, Any]:
    """Attach observed provider prompts to the C02 artifact.

    A provider call counts only when its recorded prompt carries the frozen
    snapshot id.  The function never promotes an unbound or failed response to
    a pass, and it is a no-op for runs without provider traces.
    """
    path = run_root / "context-consumption.json"
    result = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"offline_preparation_status": "failed"}
    manifest = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))
    expected_snapshot = (manifest.get("snapshot_binding") or {}).get("snapshot_id")
    traces: list[str] = []
    calls: list[dict[str, Any]] = []
    tool_results = 0
    for root in trace_roots:
        for trace_path in sorted(root.rglob("trace.jsonl")):
            traces.append(str(trace_path))
            for line in trace_path.read_text(encoding="utf-8").splitlines():
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if item.get("kind") == "provider_call":
                    prompt = item.get("prompt") or {}
                    system = prompt.get("system") if isinstance(prompt, dict) else {}
                    calls.append({
                        "trace": str(trace_path), "request_id": item.get("request_id"),
                        "snapshot_id": system.get("snapshot_id") if isinstance(system, dict) else None,
                        "bound": isinstance(system, dict) and system.get("snapshot_id") == expected_snapshot,
                        "error": item.get("error"), "raw_response_ref": item.get("raw_response_ref"),
                    })
                elif item.get("kind") == "tool_result":
                    tool_results += 1
    bound_successes = [item for item in calls if item["bound"] and not item["error"]]
    result["provider_evidence"] = {"trace_paths": traces, "calls": calls, "bound_successful_calls": len(bound_successes), "tool_results": tool_results}
    result["real_provider_calls"] = len(calls)
    result["status"] = "passed" if result.get("offline_preparation_status") == "passed" and bound_successes else "incomplete"
    result["completion_blocker"] = None if result["status"] == "passed" else "real model prompt must be bound to the frozen snapshot and produce a usable response"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return result
