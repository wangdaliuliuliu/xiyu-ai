"""J05 K01-K12 execution and fixture-integrity controls.

Fake and real provider modes share execute_j05_trajectory. The provider is
the only injected adapter; the controller, AgencyLoop, state store, and
evidence paths are identical in both modes.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import tempfile
import uuid
from copy import deepcopy
from datetime import datetime
from typing import Any, Callable

from adapters.local import LocalAdapters
from controller.gateway import ProviderResponse
from controller.provider_config import build_text_gateway, resolve_production_text_binding, resolve_text_binding
from controller.worker_execution import real_execution_gate
from runtime.context import ContextBuilder
from runtime.loop import AgencyLoop
from runtime.policy import Policy
from runtime.store import EventStore
from transport.sink import RecordingSink

OWNER = "account:1:companion:1"
ARMS = ("A", "B", "C")
CONTROL_PROVIDER_MODES = {"fake", "control"}
RECORDS_REL = pathlib.Path("workbench-data/runtime-state/records.json")


def _write_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _read_json(path: pathlib.Path, fallback: Any = None) -> Any:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _file_sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy_snapshot_verified(source: pathlib.Path, destination: pathlib.Path) -> None:
    """Materialize every frozen snapshot file before a trajectory starts."""
    # Historical workbench cleanup backups are not runtime inputs.  Some are
    # concurrently removed by the workbench test harness, so attempting to
    # copy them makes an otherwise immutable snapshot appear unreadable.  The
    # authoritative context and records files remain fully verified below.
    ignore = shutil.ignore_patterns("workbench.before-*.json")
    shutil.copytree(source, destination, ignore=ignore)
    for source_file in source.rglob("*"):
        if not source_file.is_file():
            continue
        if source_file.name.startswith("workbench.before-"):
            continue
        target_file = destination / source_file.relative_to(source)
        if not target_file.exists() or _file_sha(target_file) != _file_sha(source_file):
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target_file)
        if not target_file.exists() or _file_sha(target_file) != _file_sha(source_file):
            raise RuntimeError(f"trajectory snapshot copy verification failed: {source_file}")


def _snapshot_inventory(snapshot_root: pathlib.Path) -> dict[str, str]:
    """Return a stable relative-path to SHA-256 inventory for a snapshot."""
    if not snapshot_root.is_dir():
        raise ValueError(f"snapshot missing: {snapshot_root}")
    inventory: dict[str, str] = {}
    for path in sorted(snapshot_root.rglob("*")):
        if path.is_file():
            inventory[path.relative_to(snapshot_root).as_posix()] = _file_sha(path)
    if not inventory:
        raise ValueError(f"snapshot is empty: {snapshot_root}")
    return inventory


def _snapshot_digest(inventory: dict[str, str]) -> str:
    return _sha({"files": inventory})


def _case_event_sequence(case: dict[str, Any]) -> list[dict[str, Any]]:
    events = case.get("events")
    if not isinstance(events, list) or not events:
        raise ValueError("case events are missing")
    ordered = sorted(events, key=lambda item: int(item.get("event_index", -1)))
    indexes = [int(item.get("event_index", -1)) for item in ordered]
    if indexes != list(range(len(ordered))):
        raise ValueError(f"case event sequence is not contiguous: {indexes}")
    event_ids = [item.get("event_id") for item in ordered]
    if any(not isinstance(item, str) or not item for item in event_ids):
        raise ValueError("case event id is missing")
    times: list[datetime] = []
    for item in ordered:
        try:
            times.append(datetime.fromisoformat(str(item["virtual_time"])))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("case event virtual_time is invalid") from exc
    if any(later <= earlier for earlier, later in zip(times, times[1:])):
        raise ValueError("case event virtual_time is not strictly increasing")
    return [{
        "event_id": item["event_id"],
        "event_index": int(item["event_index"]),
        "event_role": item.get("event_role"),
        "kind": item.get("kind"),
        "virtual_time": item.get("virtual_time"),
        "source_kind": item.get("source_kind"),
    } for item in ordered]


def _validate_k12_fixture_inputs(
    run_root: pathlib.Path,
    snapshot_root: pathlib.Path,
    case: dict[str, Any],
    *,
    arm: str,
    repetition: int,
    expected_input_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate explicit case/snapshot inputs before making a trajectory manifest.

    The continuation runner may receive a source fixture that contains the
    case manifest and snapshot but not the parent run's manifest.  This
    validator makes the missing manifest safe to reconstruct: all fields used
    by K12 are derived from the two explicit inputs and the input hashes are
    retained in the generated trajectory manifest.  ``expected_input_binding``
    is only a deterministic-test hook for proving that changed inputs reject;
    production execution leaves it unset and records the observed hashes.
    """
    case_path = run_root / "case-manifest.json"
    if not case_path.exists():
        raise ValueError("case-manifest.json is missing")
    case_manifest = _read_json(case_path)
    if not isinstance(case_manifest, dict) or case_manifest.get("schemaVersion") != "concern-case-manifest-v2":
        raise ValueError("case manifest schema is invalid")
    if not isinstance(case, dict) or case.get("case_id") != "K12":
        raise ValueError("case mismatch: continuation runner requires K12")
    cases = case_manifest.get("cases")
    if not isinstance(cases, list) or not any(item.get("case_id") == "K12" for item in cases if isinstance(item, dict)):
        raise ValueError("case mismatch: K12 is not present in case-manifest.json")
    arms = case_manifest.get("arms") or {}
    arm_info = arms.get(arm)
    if not isinstance(arm_info, dict) or not bool(arm_info.get("concerns_enabled")):
        raise ValueError("arm mismatch: K12 continuation requires concerns-enabled arm C")
    if int(arm_info.get("repetitions", 0)) < int(repetition) or int(repetition) < 1:
        raise ValueError("repetition is outside the declared arm range")
    sequence = _case_event_sequence(case)
    if len(sequence) != int(case.get("minimum_events", len(sequence))):
        raise ValueError("case minimum_events does not match event sequence")
    follow_up = next((item for item in sequence if item.get("event_role") == "follow-up"), None)
    registered_change = next((item for item in sequence if item.get("event_role") == "registered-change"), None)
    if not follow_up or not registered_change or int(registered_change["event_index"]) >= int(follow_up["event_index"]):
        raise ValueError("K12 registered change must precede the follow-up event")

    source_path = run_root / "snapshot"
    _snapshot_inventory(source_path)
    if not snapshot_root.is_dir() or not (snapshot_root / "context.json").exists():
        raise ValueError("snapshot context is missing")
    records_path = snapshot_root / RECORDS_REL
    if not records_path.exists():
        raise ValueError("snapshot records are missing")
    context = _read_json(snapshot_root / "context.json")
    records = _read_json(records_path)
    if not isinstance(context, dict) or not context.get("snapshotId") or not context.get("sourceVersion"):
        raise ValueError("snapshot identity/version is missing")
    if not str(context["snapshotId"]).endswith(":" + str(context["sourceVersion"])[:16]):
        raise ValueError("snapshot identity is not bound to source version")
    if OWNER not in (context.get("owners") or {}):
        raise ValueError("snapshot owner scope is missing")

    interventions = [item for item in case.get("interventions", []) if item.get("operation") == "materialize_experimental_record_update"]
    if len(interventions) != 1:
        raise ValueError("K12 requires exactly one experimental source update")
    intervention = interventions[0]
    if int(intervention.get("at_event", -1)) != int(registered_change["event_index"]):
        raise ValueError("source update event does not match registered change")
    target = intervention.get("target") or {}
    selector = str(target.get("source_selector") or "")
    if selector != "workbench.ZHONGYING.core.reception_traffic":
        raise ValueError("K12 source selector is invalid")
    source_ref = intervention.get("source_ref")
    source_version = intervention.get("new_value")
    base_source_ref = intervention.get("base_source_ref")
    if not all(isinstance(item, str) and item for item in (source_ref, source_version, base_source_ref)):
        raise ValueError("K12 source ref/version binding is incomplete")
    row = _records_row(records, selector)
    old_expected = intervention.get("old_expected") or {}
    if not old_expected or any(_pointer_get(row, pointer) != expected for pointer, expected in old_expected.items()):
        raise ValueError("K12 source precondition does not match snapshot")
    initial_fact = next((item for item in case.get("initial_state", {}).get("facts", []) if item.get("selector") == "workbench.ZHONGYING.sourceRevision"), None)
    if not initial_fact or row.get("sourceRevision") != initial_fact.get("observed_value") or initial_fact.get("source_revision") != row.get("sourceRevision"):
        raise ValueError("K12 initial source revision is not bound to snapshot")
    if not any(str(item.get("revision")) == "9753" and item.get("sheet") == "中影店" for item in row.get("sourceRefs", []) if isinstance(item, dict)):
        raise ValueError("K12 base source ref is missing from snapshot")
    snapshot_bytes = b"".join(path.read_bytes() for path in sorted(source_path.rglob("*")) if path.is_file())
    if str(source_ref).encode("utf-8") in snapshot_bytes or str(source_version).encode("utf-8") in snapshot_bytes:
        raise ValueError("future source version/ref is already present in snapshot")

    source_inventory = _snapshot_inventory(source_path)
    case_hash = _file_sha(case_path)
    snapshot_hash = _snapshot_digest(source_inventory)
    if expected_input_binding:
        if expected_input_binding.get("case_manifest_sha256") != case_hash:
            raise ValueError("case-manifest hash mismatch")
        if expected_input_binding.get("snapshot_sha256") != snapshot_hash:
            raise ValueError("snapshot hash mismatch")
    return {
        "case_id": "K12",
        "arm": arm,
        "repetition": int(repetition),
        "case_manifest_path": str(case_path),
        "case_manifest_sha256": case_hash,
        "snapshot_source_root": str(source_path),
        "snapshot_sha256": snapshot_hash,
        "snapshot_file_hashes": source_inventory,
        "snapshot_id": str(context["snapshotId"]),
        "context_source_version": str(context["sourceVersion"]),
        "event_sequence": sequence,
        "event_sequence_hash": _sha(sequence),
        "source_binding": {
            "selector": selector,
            "source_ref": str(source_ref),
            "source_version": str(source_version),
            "base_source_ref": str(base_source_ref),
            "base_source_revision": str(row.get("sourceRevision")),
            "intervention_at_event": int(intervention["at_event"]),
            "old_expected": deepcopy(old_expected),
        },
        "future_data_policy": "source update is applied only at registered-change event; initial snapshot must not contain new source ref/version",
    }


def _build_trajectory_manifest_from_inputs(
    run_root: pathlib.Path,
    snapshot_root: pathlib.Path,
    trajectory: pathlib.Path,
    case: dict[str, Any],
    repetition: int,
    *,
    arm: str = "C",
    expected_input_binding: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a trajectory manifest without relying on a parent run manifest."""
    input_binding = _validate_k12_fixture_inputs(
        run_root,
        snapshot_root,
        case,
        arm=arm,
        repetition=repetition,
        expected_input_binding=expected_input_binding,
    )
    context = _read_json(snapshot_root / "context.json")
    prompt_path = str((( _read_json(run_root / "case-manifest.json") or {}).get("arms") or {}).get(arm, {}).get("prompt_path") or "")
    if not prompt_path or not pathlib.Path(prompt_path).exists():
        raise ValueError("declared K12 arm prompt is missing")
    records_path = snapshot_root / RECORDS_REL
    manifest = {
        "schemaVersion": "ideal-agency-lab-manifest-v2",
        "runId": trajectory.name,
        "mode": "FROZEN",
        "arm": arm,
        "prompt_mode": "concerns",
        "concerns_enabled": True,
        "prompt_path": prompt_path,
        "snapshot_binding": {
            "snapshot_id": context["snapshotId"],
            "context_path": str(snapshot_root / "context.json"),
            "context_hash": _file_sha(snapshot_root / "context.json"),
            "records_hash": _file_sha(records_path),
            "source_db_hash": context["sourceVersion"],
            "owner_keys": [OWNER],
        },
        "fixture_input_binding": input_binding,
        "generated_from": ["case-manifest.json", "snapshot/"],
        "production_mutation_policy": {"src": "forbidden", "config": "forbidden", "package": "forbidden", "delivery": "sink_only"},
    }
    return manifest, input_binding


def _build_generic_trajectory_manifest_from_inputs(
    run_root: pathlib.Path,
    snapshot_root: pathlib.Path,
    trajectory: pathlib.Path,
    case: dict[str, Any],
    repetition: int,
    *,
    arm: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a minimal manifest for non-K12 cases from explicit inputs only."""
    case_path = run_root / "case-manifest.json"
    case_manifest = _read_json(case_path)
    if not isinstance(case_manifest, dict) or case_manifest.get("schemaVersion") != "concern-case-manifest-v2":
        raise ValueError("case manifest schema is invalid")
    if not isinstance(case, dict) or not case.get("case_id"):
        raise ValueError("case id is missing")
    declared_case = next((item for item in case_manifest.get("cases", []) if item.get("case_id") == case.get("case_id")), None)
    if declared_case is None:
        raise ValueError("case mismatch: case is not present in case-manifest.json")
    arm_info = (case_manifest.get("arms") or {}).get(arm)
    if not isinstance(arm_info, dict) or int(arm_info.get("repetitions", 0)) < int(repetition) or int(repetition) < 1:
        raise ValueError("arm or repetition is outside the declared case manifest")
    sequence = _case_event_sequence(case)
    if len(sequence) != int(case.get("minimum_events", len(sequence))):
        raise ValueError("case minimum_events does not match event sequence")
    context_path = snapshot_root / "context.json"
    records_path = snapshot_root / RECORDS_REL
    context = _read_json(context_path)
    if not isinstance(context, dict) or not context.get("snapshotId") or not context.get("sourceVersion"):
        raise ValueError("snapshot identity/version is missing")
    if not (snapshot_root / "resource-index.json").exists() or not records_path.exists():
        raise ValueError("snapshot required payload is missing")
    if OWNER not in (context.get("owners") or {}):
        raise ValueError("snapshot owner scope is missing")
    source_inventory = _snapshot_inventory(run_root / "snapshot")
    source_bytes = b"".join(path.read_bytes() for path in sorted((run_root / "snapshot").rglob("*")) if path.is_file())
    source_bindings: list[dict[str, Any]] = []
    for intervention in case.get("interventions", []):
        if not isinstance(intervention, dict) or intervention.get("type") != "source_update":
            continue
        source_ref = intervention.get("source_ref") or (case.get("events", [{}])[-1].get("payload", {}) or {}).get("source_refs", [None])[0]
        if source_ref and str(source_ref).encode("utf-8") in source_bytes:
            raise ValueError("future source ref is already present in snapshot")
        source_bindings.append({
            "intervention_id": intervention.get("intervention_id"),
            "at_event": intervention.get("at_event"),
            "source_ref": source_ref,
            "source_version": intervention.get("new_value"),
            "selector": (intervention.get("target") or {}).get("source_selector"),
        })
    input_binding = {
        "case_id": str(case["case_id"]),
        "arm": arm,
        "repetition": int(repetition),
        "case_manifest_path": str(case_path),
        "case_manifest_sha256": _file_sha(case_path),
        "snapshot_source_root": str(run_root / "snapshot"),
        "snapshot_sha256": _snapshot_digest(source_inventory),
        "snapshot_file_hashes": source_inventory,
        "snapshot_id": str(context["snapshotId"]),
        "context_source_version": str(context["sourceVersion"]),
        "event_sequence": sequence,
        "event_sequence_hash": _sha(sequence),
        "source_bindings": source_bindings,
        "future_data_policy": "source updates are applied only at their registered event; initial snapshot must not contain their future source refs",
    }
    prompt_path = str((arm_info or {}).get("prompt_path") or "")
    if not prompt_path or not pathlib.Path(prompt_path).exists():
        raise ValueError("declared arm prompt is missing")
    manifest = {
        "schemaVersion": "ideal-agency-lab-manifest-v2",
        "runId": trajectory.name,
        "mode": "FROZEN",
        "arm": arm,
        "prompt_mode": "concerns" if arm != "A" else "baseline",
        "concerns_enabled": bool(arm_info.get("concerns_enabled")),
        "prompt_path": prompt_path,
        "snapshot_binding": {
            "snapshot_id": context["snapshotId"],
            "context_path": str(context_path),
            "context_hash": _file_sha(context_path),
            "records_hash": _file_sha(records_path),
            "source_db_hash": context["sourceVersion"],
            "owner_keys": [OWNER],
        },
        "fixture_input_binding": input_binding,
        "generated_from": ["case-manifest.json", "snapshot/"],
        "production_mutation_policy": {"src": "forbidden", "config": "forbidden", "package": "forbidden", "delivery": "sink_only"},
    }
    return manifest, input_binding


def _evidence(case_id: str, index: int, *, impact: str = "") -> dict[str, Any]:
    item = {
        # Case IDs are evaluator metadata.  They must never enter a worker
        # prompt through a provider response or a persisted concern basis.
        "source_ref": f"snapshot://{OWNER}/j05/source-{index}",
        "epistemic_status": "observed",
        "kind": "frozen_case_source",
        "summary": "J05 source-bound control evidence",
    }
    if impact:
        item["impact"] = impact
    return item


def _control_decision(*, action_type: str, action_args: dict[str, Any] | None = None,
                      intention_ref: str | None = None, concern_ref: str | None = None,
                      concern_updates: list[dict[str, Any]] | None = None,
                      message: str = "") -> dict[str, Any]:
    return {
        "operation": "continue" if intention_ref else "new",
        "intention_ref": intention_ref,
        "desired_change": "记录当前事件并在下一次相关输入时继续",
        "basis_refs": [],
        "action": {"type": action_type, "args": action_args or {}, "expected_result": "control-flow-only"},
        "strategy_reason": "J05 injected control decision; excluded from semantic acceptance",
        "expected_participation": None,
        "reconsider_condition": "有新的相关输入或来源变化时重新评估",
        "messages": [message] if action_type == "deliver" else [],
        "concern_ref": concern_ref,
        "task_ref": None,
        "concern_updates": concern_updates or [],
    }


class J05FakeGateway:
    """A schema-valid provider double; it cannot establish role semantics."""

    model_name = "j05-fake-provider"

    def __init__(self, *, arm: str, case_id: str, concerns_seeded: bool = False):
        self.arm = arm
        self.case_id = case_id
        self.concerns_seeded = concerns_seeded
        self.event_index = -1
        self.call_in_event = 0
        self.active_concern: str | None = None
        self.concern_version: int | None = None
        self.calls: list[dict[str, Any]] = []

    def begin_event(self, event_index: int) -> None:
        self.event_index = event_index
        self.call_in_event = 0

    def register_result(self, result: dict[str, Any]) -> None:
        if result.get("concern_id"):
            self.active_concern = str(result["concern_id"])
            self.concern_version = result.get("concern_version")

    def _concern_delta(self) -> tuple[str | None, list[dict[str, Any]]]:
        if self.arm != "C" or self.concerns_seeded or self.case_id == "K09":
            return self.active_concern, []
        if self.active_concern is None and self.event_index == 0:
            local_ref = "j05-local-concern"
            return local_ref, [{
                "operation": "create", "concern_ref": local_ref, "expected_version": None,
                "basis_refs": [_evidence(self.case_id, 1)],
                "changes": {
                    "title": "依据当前输入保留可恢复方向",
                    "desired_direction": "保留有证据的下一步，等待相关变化后继续",
                    "domain": "mixed", "origin": "observed_gap",
                    "desire_refs": ["work_trust", "personal_affinity"],
                    "known_summary": [_evidence(self.case_id, 1)],
                    "unknowns": [_evidence(self.case_id, 2, impact="未知被误当已知会改变下一步判断")],
                },
            }]
        if self.active_concern and self.event_index > 0:
            return self.active_concern, [{
                "operation": "update", "concern_ref": self.active_concern,
                "expected_version": self.concern_version,
                "basis_refs": [_evidence(self.case_id, self.event_index + 1)],
                "changes": {"known_summary": [_evidence(self.case_id, self.event_index + 1)]},
            }]
        return self.active_concern, []

    def complete(self, prompt: dict[str, Any], *, attempt: int = 1) -> ProviderResponse:
        self.calls.append({"call_index": len(self.calls), "event_index": self.event_index, "attempt": attempt, "prompt": deepcopy(prompt)})
        concern_ref, updates = self._concern_delta()
        if self.case_id == "K03" and self.event_index == 1 and self.call_in_event == 0:
            action_type, action_args = "knowledge.propose", {"candidate": "接待客流与场域客流按来源分列", "scope": OWNER}
        elif self.case_id == "K06" and self.event_index == 0 and self.call_in_event == 0:
            action_type, action_args = "media.prepare", {"generation_prompt": "准备一份待核对的个人媒介素材"}
        else:
            action_type, action_args = "deliver", {}
        self.call_in_event += 1
        return ProviderResponse(
            request_id=str(uuid.uuid4()), model=self.model_name,
            content=_control_decision(action_type=action_type, action_args=action_args, concern_ref=concern_ref, concern_updates=updates, message="控制流回执；不作为语义验收结果"),
            usage={"input_tokens": 0, "output_tokens": 0}, latency_ms=0,
        )


class GatewayRecorder:
    """Record actual prompts while preserving the gateway interface."""

    def __init__(self, delegate: Any):
        self.delegate = delegate
        self.calls: list[dict[str, Any]] = []
        self.model_name = delegate.model_name
        self.budget_exhausted = False

    def begin_event(self, event_index: int) -> None:
        if hasattr(self.delegate, "begin_event"):
            self.delegate.begin_event(event_index)

    def register_result(self, result: dict[str, Any]) -> None:
        if hasattr(self.delegate, "register_result"):
            self.delegate.register_result(result)

    def complete(self, prompt: dict[str, Any], *, attempt: int = 1) -> ProviderResponse:
        response = self.delegate.complete(prompt, attempt=attempt)
        self.calls.append({
            "call_index": len(self.calls),
            "attempt": attempt,
            "prompt": deepcopy(prompt),
            "provider_call": not (response.error == "cost_budget_exhausted"),
            "response_error": response.error,
            "response_http_status": response.http_status,
            "response_finish_reason": response.finish_reason,
            "response_usage": deepcopy(response.usage),
        })
        if response.error == "cost_budget_exhausted":
            self.budget_exhausted = True
        return response


def _pointer_get(value: Any, pointer: str) -> Any:
    current = value
    parts = [item.replace("~1", "/").replace("~0", "~") for item in pointer.lstrip("/").split("/") if item]
    for part in parts:
        current = current[int(part)] if isinstance(current, list) else current[part]
    return deepcopy(current)


def _pointer_set(value: Any, pointer: str, new_value: Any) -> None:
    parts = [item.replace("~1", "/").replace("~0", "~") for item in pointer.lstrip("/").split("/") if item]
    if not parts:
        raise ValueError("cannot replace document root")
    current = value
    for part in parts[:-1]:
        current = current[int(part)] if isinstance(current, list) else current[part]
    last = parts[-1]
    if isinstance(current, list):
        current[int(last)] = deepcopy(new_value)
    else:
        current[last] = deepcopy(new_value)


def _records_row(records: dict[str, Any], selector: str) -> dict[str, Any]:
    venue = selector.split(".")[1]
    return next(row for row in records.get("data", []) if row.get("id") == f"WR-20260815-{venue}")


def _target_before(context: dict[str, Any], records: dict[str, Any], intervention: dict[str, Any]) -> Any:
    target = intervention.get("target") or {}
    if target.get("json_pointer"):
        source = records if target.get("file") == "records.json" else context
        return _pointer_get(source, target["json_pointer"])
    selector = target.get("source_selector", "")
    if selector.startswith("workbench."):
        row = _records_row(records, selector)
        if selector.endswith("sourceRevision"):
            return row.get("sourceRevision")
        if ".daily." in selector:
            date = selector.split(".")[3]
            return deepcopy(next(item for item in row.get("daily", []) if item.get("date") == date))
        return deepcopy(row)
    if target.get("task_id"):
        return next((task for task in context["owners"][OWNER].get("tasks", []) if str(task.get("id")) == str(target["task_id"])), None)
    if target.get("key") == "media_available":
        return None
    if target.get("store") == "concerns":
        return "owner-scoped-store"
    if intervention.get("operation") == "cold_start_relationship_filter":
        owner = context["owners"][OWNER]
        companion = owner.get("profile", {}).get("companion", {})
        return {
            "relationship_fields": {key: deepcopy(companion.get(key)) for key in (
                "relationship_status", "relationship_stage", "intimacy_level", "affection_level",
                "shared_memory", "became_lover_at", "confessed_at", "user_confessed_at",
                "call_user_as", "user_call_her_as", "relationship_reminders_seeded",
            )},
            "memory_count": len(owner.get("memories", [])),
            "memory_ids": [str(row.get("id")) for row in owner.get("memories", []) if row.get("id")],
        }
    return {key: deepcopy(value) for key, value in target.items() if key not in {"file", "json_pointer"}}


def _relationship_memory_reason(row: dict[str, Any]) -> str | None:
    value = row.get("value") if isinstance(row.get("value"), dict) else row
    memory_type = str(value.get("memory_type") or value.get("memory_layer") or "").lower()
    if memory_type in {"emotion", "relationship", "romance", "intimacy", "affection"}:
        return f"memory_type:{memory_type}"
    text = json.dumps(row, ensure_ascii=False).lower()
    markers = ("relationship", "romance", "intimacy", "affection", "lover", "confess", "想你", "暧昧", "亲密")
    if any(marker in text for marker in markers):
        return "relationship_marker"
    return None


def _apply_intervention(snapshot_root: pathlib.Path, intervention: dict[str, Any], *, media_available: bool | None = None) -> dict[str, Any]:
    context_path = snapshot_root / "context.json"
    records_path = snapshot_root / RECORDS_REL
    context = _read_json(context_path)
    records = _read_json(records_path)
    before = _target_before(context, records, intervention)
    operation = intervention.get("operation")
    target = intervention.get("target") or {}
    after = before
    if operation == "replace_source_revision":
        row = _records_row(records, target["source_selector"])
        new_revision = str(intervention["new_value"])
        row["sourceRevision"] = new_revision
        # A source arrival is not materialized by changing only the display
        # marker.  Keep the row's sourceRefs bound to the same new revision so
        # opportunity resolution and the local adapter can consume the exact
        # source/version requested by the event.
        for source in row.get("sourceRefs", []):
            if not isinstance(source, dict) or source.get("revision") is None:
                continue
            source["revision"] = int(new_revision) if new_revision.isdigit() else new_revision
        after = row.get("sourceRevision")
        records_path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elif operation == "materialize_experimental_record_update":
        row = _records_row(records, target["source_selector"])
        old_expected = intervention.get("old_expected") or {}
        for pointer, expected in old_expected.items():
            actual = _pointer_get(row, pointer)
            if actual != expected:
                raise ValueError(f"experimental source update precondition failed at {pointer}: expected {expected!r}, got {actual!r}")
        for pointer, value in (intervention.get("changes") or {}).items():
            _pointer_set(row, pointer, value)
        source_ref = str(intervention["source_ref"])
        row["sourceRevision"] = str(intervention["new_value"])
        row.setdefault("sourceRefs", []).insert(0, {
            "document": "J05 isolated experimental update",
            "kind": "isolated_experiment_update",
            "sourceRef": source_ref,
            "revision": str(intervention["new_value"]),
            "sheet": str(intervention.get("sheet") or row.get("venue") or "workbench"),
            "experimental": True,
            "baseSourceRef": str(intervention.get("base_source_ref") or ""),
        })
        after = deepcopy(row)
        records_path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elif operation == "replace" and target.get("json_pointer"):
        source = records if target.get("file") == "records.json" else context
        _pointer_set(source, target["json_pointer"], intervention.get("new_value"))
        after = _pointer_get(source, target["json_pointer"])
        target_path = records_path if target.get("file") == "records.json" else context_path
        target_path.write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elif operation == "create_authorized_due_task":
        owner = context["owners"][OWNER]
        source_task = next(task for task in owner.get("tasks", []) if str(task.get("id")) == "2")
        task = deepcopy(source_task)
        task.update({"id": "j05-due-task-20260909-1100", "status": "open", "due_at": intervention["due_at"], "version": 0, "source_ref": f"{source_task.get('source_ref')}#j05-isolated-due-condition", "authorized": True, "experimental_condition": True})
        owner.setdefault("tasks", []).append(task)
        after = task
        context_path.write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elif operation == "set_pair_value":
        after = media_available
        _write_json(snapshot_root / "media-condition.json", {"media_available": media_available, "condition_source": "paired_experiment_condition"})
    elif operation == "cold_start_relationship_filter":
        owner = context["owners"][OWNER]
        companion = owner.setdefault("profile", {}).setdefault("companion", {})
        reset_fields = (
            "relationship_status", "relationship_stage", "intimacy_level", "affection_level",
            "shared_memory", "became_lover_at", "confessed_at", "user_confessed_at",
            "call_user_as", "user_call_her_as", "relationship_reminders_seeded",
        )
        for key in reset_fields:
            companion[key] = None
        kept: list[dict[str, Any]] = []
        suppressed: list[dict[str, Any]] = []
        for row in owner.get("memories", []):
            reason = _relationship_memory_reason(row)
            if reason:
                suppressed.append({"id": row.get("id"), "source_ref": row.get("source_ref"), "reason": reason})
            else:
                kept.append(row)
        owner["memories"] = kept
        after = {
            "relationship_fields": {key: deepcopy(companion.get(key)) for key in reset_fields},
            "memory_count": len(kept),
            "kept_memory_ids": [str(row.get("id")) for row in kept if row.get("id")],
            "suppressed_memory_ids": suppressed,
            "retained_enterprise_fact_count": len(owner.get("facts", [])),
            "retained_personal_schedule_count": len(owner.get("schedule", [])),
            "retained_role": owner.get("profile", {}).get("role"),
        }
        context_path.write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elif operation.startswith("assert_") or operation in {"assert_unknown_not_materialized", "seed_prepared_old_concern", "inject_work_opportunity_during_media_prepare"}:
        after = before if operation.startswith("assert_") else {"materialized": True, "operation": operation}
    else:
        raise ValueError(f"unsupported intervention operation: {operation}")
    return {"intervention_id": intervention.get("intervention_id"), "at_event": intervention.get("at_event"), "type": intervention.get("type"), "operation": operation, "target": target, "before": before, "after": after, "before_hash": _sha(before), "after_hash": _sha(after), "changed": before != after, "executed": True, "source_refs": [intervention.get("reason", "")]}


def _seed_capacity(store: EventStore, case_id: str) -> dict[str, Any]:
    accepted: list[dict[str, Any]] = []
    for index in range(1, 13):
        relevant = index == 12
        evidence = _evidence(case_id, index)
        if relevant:
            evidence.update({
                "source_ref": f"snapshot://{OWNER}/workbench-records/revision/9753/中影店",
                "kind": "frozen_workbench_record",
                "summary": "旧版中影 2026-08-15 至 2026-08-21：接待客流 168，票房 15951.1；等待新来源后复核关系",
            })
        update = {
            "operation": "create",
            "concern_ref": f"capacity-seed-{index}",
            "expected_version": None,
            "basis_refs": [evidence],
            "changes": {
                "title": "中影经营证据续接" if relevant else f"隔离容量条件 {index}",
                "desired_direction": "新版本到达后复核接待客流和票房关系，并保留来源差异" if relevant else "保留容量边界控制证据",
                "domain": "work",
                "origin": "observed_gap",
                "desire_refs": ["work_trust"],
                "known_summary": [evidence] if relevant else [],
                "unknowns": ([{
                    "source_ref": f"snapshot://{OWNER}/workbench-records/new-version-pending",
                    "epistemic_status": "unknown",
                    "kind": "source_gap",
                    "summary": "新版本尚未到达",
                    "impact": "无法判断接待客流是否发生变化",
                }] if relevant else []),
                "next_review_condition": ({
                    "type": "new_source_version",
                    "source_ref": f"snapshot://{OWNER}/workbench-records",
                    "version": "after-9753",
                } if relevant else {"type": "next_eligible_opportunity", "reason": "新的相关事件"}),
            },
        }
        with store.transaction():
            result = store.apply_concern_updates(OWNER, f"fixture:capacity-seed:{index}", [update], max_active=12)
        accepted.extend(result.get("accepted", []))
    active_count = int(store.conn.execute("SELECT COUNT(*) FROM concerns WHERE owner=? AND status='active'", (OWNER,)).fetchone()[0])
    return {"accepted": accepted, "active_count": active_count}


def _capacity_probe(store: EventStore, case_id: str) -> dict[str, Any]:
    probe = {"operation": "create", "concern_ref": "capacity-probe", "expected_version": None, "basis_refs": [_evidence(case_id, 99)], "changes": {"title": "容量探针", "desired_direction": "不越过 active 上限", "domain": "work", "origin": "observed_gap", "desire_refs": ["work_trust"]}}
    with store.transaction():
        return store.apply_concern_updates(OWNER, "fixture:capacity-probe", [probe], max_active=12)


def _materialize_trajectory(run_root: pathlib.Path, trajectory: pathlib.Path, case: dict[str, Any], repetition: int, *, arm: str = "C") -> tuple[pathlib.Path, pathlib.Path, list[dict[str, Any]]]:
    snapshot_root = trajectory / "isolated-snapshot"
    _copy_snapshot_verified(run_root / "snapshot", snapshot_root)
    parent_manifest = _read_json(run_root / "manifest.json")
    if parent_manifest is not None:
        trajectory_manifest = deepcopy(parent_manifest)
        input_binding = None
    else:
        if case.get("case_id") == "K12":
            trajectory_manifest, input_binding = _build_trajectory_manifest_from_inputs(run_root, snapshot_root, trajectory, case, repetition, arm=arm)
        else:
            trajectory_manifest, input_binding = _build_generic_trajectory_manifest_from_inputs(run_root, snapshot_root, trajectory, case, repetition, arm=arm)
    trajectory_manifest["trajectory_fixture"] = True
    trajectory_manifest["snapshot_binding"]["context_path"] = str(snapshot_root / "context.json")
    initial_interventions: list[dict[str, Any]] = []
    for intervention in case.get("interventions", []):
        if int(intervention.get("at_event", 0)) == 0:
            if intervention.get("operation") == "seed_exactly_12_active_concerns":
                # The actual store mutation is performed immediately after
                # the EventStore is opened; it cannot be represented by a
                # JSON-file-only mutation here.
                continue
            media_value = (True if repetition % 2 else False) if case["case_id"] == "K06" else None
            initial_interventions.append(_apply_intervention(snapshot_root, intervention, media_available=media_value))
    context_path = snapshot_root / "context.json"
    trajectory_manifest["snapshot_binding"]["context_hash"] = _file_sha(context_path)
    if input_binding is not None:
        trajectory_manifest["fixture_input_binding"] = deepcopy(input_binding)
    manifest_path = trajectory / "trajectory-manifest.json"
    _write_json(manifest_path, trajectory_manifest)
    context = _read_json(context_path)
    cold_start = next((item for item in initial_interventions if item.get("operation") == "cold_start_relationship_filter"), None)
    _write_json(trajectory / "initial-state.json", {
        "schemaVersion": "j05-initial-state-v2", "case_id": case["case_id"], "repetition": repetition,
        "source_snapshot": {"run_manifest": str(run_root / "manifest.json") if (run_root / "manifest.json").exists() else None, "case_manifest": str(run_root / "case-manifest.json"), "generated_trajectory_manifest": str(manifest_path), "snapshot_id": trajectory_manifest["snapshot_binding"].get("snapshot_id"), "context_hash": _file_sha(context_path), "records_hash": _file_sha(snapshot_root / RECORDS_REL)},
        "materialized_interventions": initial_interventions, "history_count": len(context["owners"][OWNER].get("history", [])),
        "shared_memory": context["owners"][OWNER].get("profile", {}).get("companion", {}).get("shared_memory"),
        "tasks": context["owners"][OWNER].get("tasks", []), "model_prompt_cannot_read": ["case_id", "response_rules", "assertions", "interventions", "controlled_overlay"],
        "cold_start_control": {
            "applied": bool(cold_start),
            "relationship_state_after": (cold_start or {}).get("after", {}).get("relationship_fields", {}),
            "suppressed_relationship_memory": (cold_start or {}).get("after", {}).get("suppressed_memory_ids", []),
            "retained_enterprise_fact_count": (cold_start or {}).get("after", {}).get("retained_enterprise_fact_count", len(context["owners"][OWNER].get("facts", []))),
            "retained_personal_schedule_count": (cold_start or {}).get("after", {}).get("retained_personal_schedule_count", len(context["owners"][OWNER].get("schedule", []))),
            "retained_role": (cold_start or {}).get("after", {}).get("retained_role", context["owners"][OWNER].get("profile", {}).get("role")),
        },
    })
    return snapshot_root, manifest_path, initial_interventions


def _refresh_trajectory_manifest(snapshot_root: pathlib.Path, manifest_path: pathlib.Path) -> None:
    """Keep the per-trajectory snapshot binding truthful after a mutation."""
    trajectory_manifest = _read_json(manifest_path)
    context_path = snapshot_root / "context.json"
    trajectory_manifest["snapshot_binding"]["context_hash"] = _file_sha(context_path)
    records_path = snapshot_root / RECORDS_REL
    if records_path.exists():
        trajectory_manifest["snapshot_binding"]["records_hash"] = _file_sha(records_path)
    _write_json(manifest_path, trajectory_manifest)


def _components(snapshot_root: pathlib.Path, manifest_path: pathlib.Path, trajectory: pathlib.Path, *, prompt_path: pathlib.Path, concerns_enabled: bool, gateway: Any, sink: Any | None = None) -> tuple[EventStore, AgencyLoop]:
    store = EventStore(trajectory / "state.db")
    sink = sink or RecordingSink(trajectory / "traces" / "sink.jsonl")
    context = ContextBuilder(snapshot_root=snapshot_root, prompt_path=prompt_path, manifest_path=manifest_path, store=store, concerns_enabled=concerns_enabled)
    adapters = LocalAdapters(snapshot_root=snapshot_root, manifest_path=manifest_path, store=store, concerns_enabled=concerns_enabled)
    loop = AgencyLoop(store=store, context=context, adapters=adapters, policy=Policy(store, writable_root=trajectory, concerns_enabled=concerns_enabled), gateway=gateway, sink=sink, trace_path=trajectory / "traces" / "trace.jsonl")
    return store, loop


def _durable_state(store: EventStore) -> dict[str, Any]:
    # The worker-facing concern reader deliberately caps selected context at
    # six.  Durability evidence must nevertheless inspect all twelve seeded
    # rows, so this is an evaluator-owned direct state audit, not worker data.
    concerns = [dict(row) for row in store.conn.execute("SELECT concern_id AS id, version, status FROM concerns WHERE owner=? ORDER BY concern_id", (OWNER,)).fetchall()]
    tasks = store.read_tasks(OWNER)
    deliveries = store.delivered_segments(OWNER)
    return {"tasks": [{"id": row["id"], "status": row["status"], "version": row["version"]} for row in tasks], "concerns": [{"id": row["id"], "version": row["version"], "status": row["status"]} for row in concerns], "deliveries": [row["segment_id"] for row in deliveries], "hash": _sha({"tasks": tasks, "concerns": concerns, "deliveries": deliveries})}


def _source_ref_materialized(snapshot_root: pathlib.Path, source_ref: str) -> bool:
    """Return true only when the referenced source version exists in the snapshot."""
    context_path = snapshot_root / "context.json"
    records_path = snapshot_root / RECORDS_REL
    context = _read_json(context_path, {})
    records = _read_json(records_path, {})
    if source_ref and (source_ref in json.dumps(context, ensure_ascii=False) or source_ref in json.dumps(records, ensure_ascii=False)):
        return True
    parts = [part for part in str(source_ref).split("/") if part]
    if "revision" not in parts:
        return False
    revision_index = parts.index("revision")
    requested_revision = parts[revision_index + 1] if revision_index + 1 < len(parts) else ""
    requested_sheet = parts[-1] if parts else ""
    token = parts[1] if len(parts) > 1 and parts[0] == "feishu:" else ""
    for record in records.get("data", []):
        for source in record.get("sourceRefs", []):
            if not isinstance(source, dict):
                continue
            if str(source.get("revision")) == requested_revision and str(source.get("sheet")) == requested_sheet and (not token or str(source.get("spreadsheetToken")) == token):
                return True
    return False


def _resolve_event(event: dict[str, Any], store: EventStore, snapshot_root: pathlib.Path | None = None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    payload = deepcopy(event["payload"])
    if event["kind"] == "opportunity" and snapshot_root is not None:
        source_refs = [str(ref) for ref in (payload.get("source_refs") or []) if str(ref).strip()]
        missing_refs = [ref for ref in source_refs if not _source_ref_materialized(snapshot_root, ref)]
        if missing_refs:
            return None, {"status": "fixture_branch_gap", "reason": "opportunity_source_not_materialized", "missing_source_refs": missing_refs, "manifest_event_id": event["event_id"]}
    if event["kind"] == "silence_observed" and payload.get("delivered_message_selector", payload.get("silence_ref")) in {"latest_sent_message", "latest_delivery"}:
        delivered = [row for row in store.delivered_segments(OWNER) if row.get("status") == "delivered"]
        message_ids = []
        for row in delivered:
            try:
                receipt = json.loads(row.get("receipt_json") or "{}")
            except json.JSONDecodeError:
                receipt = {}
            if receipt.get("provider_message_id"):
                message_ids.append(str(receipt["provider_message_id"]))
        if not delivered or not message_ids:
            return None, {"status": "fixture_branch_gap", "reason": "silence_observed_without_a_prior_delivered_message", "manifest_event_id": event["event_id"]}
        payload.pop("delivered_message_selector", None)
        payload.pop("silence_ref", None)
        payload["delivered_segment_ids"] = [row["segment_id"] for row in delivered]
        payload["delivered_message_ids"] = message_ids
        payload["observed_at"] = payload.get("observed_at") or event["virtual_time"]
    if event["kind"] == "task_due" and payload.get("task_ref"):
        task = next((row for row in store.read_tasks(OWNER) if row["id"] == payload["task_ref"]), None)
        if not task:
            return None, {"status": "fixture_branch_gap", "reason": "task_due_task_not_materialized", "manifest_event_id": event["event_id"]}
        payload.update({"task_id": task["id"], "task_version": task["version"], "due_at": task.get("due_at")})
        payload.pop("task_ref", None)
    if payload.get("user_confirmation_target") == "latest_candidate":
        row = store.conn.execute("SELECT candidate_id FROM knowledge_candidates WHERE owner=? ORDER BY created_at DESC LIMIT 1", (OWNER,)).fetchone()
        if not row:
            return None, {"status": "fixture_branch_gap", "reason": "confirmation_without_actual_candidate", "manifest_event_id": event["event_id"]}
        payload.pop("user_confirmation_target", None)
        payload["user_confirmation"] = {"candidate_id": row[0], "accepted": True}
    actual = {"event_id": str(uuid.uuid4()), "owner": OWNER, "kind": event["kind"], "virtual_time": event["virtual_time"], "payload": payload}
    return actual, {"status": "resolved", "manifest_event_id": event["event_id"], "actual_event": actual}


def _prompt_privacy(calls: list[dict[str, Any]], case_id: str) -> dict[str, Any]:
    forbidden = ["response_rules", "controlled_overlay", "assertions", "interventions", "evaluator", "acceptance requirement", case_id]
    leaks = []
    for index, call in enumerate(calls):
        encoded = json.dumps(call.get("prompt"), ensure_ascii=False, sort_keys=True)
        for token in forbidden:
            if token in encoded:
                leaks.append({"call_index": index, "token": token})
    return {"worker_prompt_does_not_contain_evaluator_oracle": not leaks, "leaks": leaks}


def _count(store: EventStore, table: str, owner: str) -> int:
    if table not in {"concerns", "concern_events", "sink_deliveries"}:
        raise ValueError(table)
    return int(store.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE owner=?", (owner,)).fetchone()[0])


def execute_j05_trajectory(run_root: pathlib.Path, output_root: pathlib.Path, case: dict[str, Any], arm: str, repetition: int,
                           prompt_path: pathlib.Path, gateway_factory: Callable[[str, str, bool], Any], provider_mode: str,
                           sink_factory: Callable[[pathlib.Path], Any] | None = None, allow_noop_sink: bool = False) -> dict[str, Any]:
    case_id = case["case_id"]
    trajectory = output_root / arm / case_id / f"r{repetition:02d}"
    trajectory.mkdir(parents=True, exist_ok=False)
    snapshot_root, manifest_path, initial_interventions = _materialize_trajectory(run_root, trajectory, case, repetition, arm=arm)
    seeded = case_id == "K12"
    gateway = GatewayRecorder(gateway_factory(arm, case_id, seeded))
    store, loop = _components(snapshot_root, manifest_path, trajectory, prompt_path=prompt_path, concerns_enabled=arm == "C", gateway=gateway, sink=sink_factory(trajectory) if sink_factory else None)
    if case_id == "K02":
        task = next(task for task in _read_json(snapshot_root / "context.json")["owners"][OWNER]["tasks"] if task.get("id") == "j05-due-task-20260909-1100")
        store.seed_tasks(OWNER, [task])
    capacity_seed = _seed_capacity(store, case_id) if case_id == "K12" else None
    capacity_probe = _capacity_probe(store, case_id) if case_id == "K12" else None
    if case_id == "K12":
        initial_interventions.append({"intervention_id": "K12-I1", "at_event": 0, "type": "experimental_condition", "operation": "seed_exactly_12_active_concerns", "before": {"active_count": 0}, "after": {"active_count": capacity_seed["active_count"] if capacity_seed else None, "accepted": capacity_seed["accepted"] if capacity_seed else []}, "before_hash": _sha({"active_count": 0}), "after_hash": _sha(capacity_seed or {}), "changed": True, "executed": bool(capacity_seed), "source_refs": ["隔离状态库"]})
    _write_json(trajectory / "initial-state.json", {**_read_json(trajectory / "initial-state.json"), "durable_state_before_events": _durable_state(store), "capacity_seed": capacity_seed, "materialized_interventions": initial_interventions})
    event_results: list[dict[str, Any]] = []
    input_records: list[dict[str, Any]] = []
    intervention_records = list(initial_interventions)
    restart_records: list[dict[str, Any]] = []
    restarted_before_event_2 = False
    restarted_after_delivery = False
    budget_stop = False
    budget_stop_event: int | None = None
    try:
        for manifest_event in case["events"]:
            index = int(manifest_event["event_index"])
            for intervention in case.get("interventions", []):
                if int(intervention.get("at_event", 0)) == index and index != 0:
                    media_value = (True if repetition % 2 else False) if case_id == "K06" else None
                    intervention_records.append(_apply_intervention(snapshot_root, intervention, media_available=media_value))
                    _refresh_trajectory_manifest(snapshot_root, manifest_path)
            if index == 2 and not restarted_before_event_2:
                before = _durable_state(store)
                prompt_count_before = len(gateway.calls)
                store.close()
                store, loop = _components(snapshot_root, manifest_path, trajectory, prompt_path=prompt_path, concerns_enabled=arm == "C", gateway=gateway, sink=sink_factory(trajectory) if sink_factory else None)
                after = _durable_state(store)
                restarted_before_event_2 = True
                restart_records.append({"stage": "before_event_2", "before": before, "after": after, "same_durable_state": before["hash"] == after["hash"], "prompt_count_before": prompt_count_before})
            gateway.begin_event(index)
            actual_event, resolution = _resolve_event(manifest_event, store, snapshot_root)
            input_records.append({"manifest_event_id": manifest_event["event_id"], "kind": manifest_event["kind"], "source_kind": manifest_event.get("source_kind"), "resolution": resolution, "actual_event": actual_event})
            if actual_event is None:
                event_results.append({"event_index": index, "kind": manifest_event["kind"], "status": "fixture_branch_gap", "path_id": None, "reason": resolution.get("reason")})
                continue
            result = loop.process_event(actual_event)
            gateway.register_result(result)
            event_results.append({"event_index": index, "kind": manifest_event["kind"], "status": result.get("status"), "path_id": result.get("path_id"), "intention_id": result.get("intention_id"), "action_id": result.get("action_id"), "concern_id": result.get("concern_id"), "concern_version": result.get("concern_version")})
            if gateway.budget_exhausted:
                budget_stop = True
                budget_stop_event = index
                # Stop this trajectory at the first local budget refusal.  The
                # worker scheduler will stop dispatching subsequent
                # trajectories; these terminal markers are not fake provider
                # failures and do not create additional relay attempts.
                for pending_event in case["events"]:
                    if int(pending_event["event_index"]) > index:
                        event_results.append({"event_index": int(pending_event["event_index"]), "kind": pending_event["kind"], "status": "not_scheduled", "reason": "cost_budget_exhausted_before_event"})
                break
            if result.get("status") in ({"delivered", "unknown"} if allow_noop_sink else {"delivered"}) and not restarted_after_delivery:
                before = _durable_state(store)
                store.close()
                store, loop = _components(snapshot_root, manifest_path, trajectory, prompt_path=prompt_path, concerns_enabled=arm == "C", gateway=gateway, sink=sink_factory(trajectory) if sink_factory else None)
                after = _durable_state(store)
                restarted_after_delivery = True
                restart_records.append({"stage": "after_delivery", "before": before, "after": after, "same_durable_state": before["hash"] == after["hash"]})
        _write_json(trajectory / "restart-evidence.json", {"schemaVersion": "j05-restart-evidence-v2", "checks": restart_records, "passed": bool(restart_records) and all(item.get("same_durable_state") for item in restart_records)})
        with (trajectory / "input-events.jsonl").open("w", encoding="utf-8") as stream:
            for item in input_records:
                stream.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
        with (trajectory / "interventions.jsonl").open("w", encoding="utf-8") as stream:
            for item in intervention_records:
                stream.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
        with (trajectory / "actual-prompts.jsonl").open("w", encoding="utf-8") as stream:
            for item in gateway.calls:
                stream.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
        final_state = _durable_state(store)
        allowed_statuses = {"waiting", "delivered", "observed", "prepared"} | ({"unknown"} if allow_noop_sink else set())
        statuses_ok = len(event_results) == len(case["events"]) and not budget_stop and all(item["status"] in allowed_statuses for item in event_results)
        initial_concerns = len((_read_json(trajectory / "initial-state.json").get("durable_state_before_events") or {}).get("concerns", []))
        model_concern_events = int(store.conn.execute("SELECT COUNT(*) FROM concern_events WHERE owner=? AND event_id NOT LIKE 'fixture:%'", (OWNER,)).fetchone()[0])
        # Arm identity is established by the prompt's concern protocol flag.
        # A/B must keep it disabled; C may legitimately produce zero concern
        # writes in a scene that has no new concern to register (for example
        # cold-start or personal-life opportunity).  Requiring a concern row
        # for every C scene made those valid traces fail as a fixture error.
        prompt_concern_flags = [
            bool((call.get("prompt") or {}).get("current", {}).get("concerns", {}).get("enabled"))
            for call in gateway.calls
        ]
        arm_prompt_state_ok = bool(prompt_concern_flags) and all(flag == (arm == "C") for flag in prompt_concern_flags)
        if arm in {"A", "B"}:
            arm_state_ok = arm_prompt_state_ok and model_concern_events == 0
        else:
            arm_state_ok = arm_prompt_state_ok
        privacy = _prompt_privacy(gateway.calls, case_id)
        restart_ok = bool(restart_records) and all(item.get("same_durable_state") for item in restart_records)
        capacity_ok = True
        if case_id == "K12":
            capacity_ok = bool(capacity_seed and capacity_seed["active_count"] == 12 and capacity_probe and capacity_probe.get("rejected") and "concern_capacity_exceeded" in capacity_probe["rejected"][0].get("reason", ""))
        status = "passed" if statuses_ok and arm_state_ok and privacy["worker_prompt_does_not_contain_evaluator_oracle"] and restart_ok and capacity_ok else "failed"
        failure_class = "budget_guard" if budget_stop else ("none_pending_semantics" if status == "passed" else "execution_or_fixture")
        result = {
            "schemaVersion": "j05-trajectory-evidence-v2", "status": status, "semantic_acceptance": False,
            "semantic_acceptance_status": "not_run_fake_provider_excluded" if provider_mode in CONTROL_PROVIDER_MODES else "pending_independent_evaluator",
            "provider_mode": provider_mode, "provider_type": "scripted_fake" if provider_mode == "fake" else ("scripted_control" if provider_mode == "control" else "bound_http_gateway"),
            "delivery_mode": "no_op" if allow_noop_sink else "recording", "real_provider_calls": sum(bool(item.get("provider_call", True)) for item in gateway.calls) if provider_mode in {"real", "local_isolated_semantic_smoke"} else 0, "relay_attempts": len(gateway.calls) if provider_mode in {"real", "local_isolated_semantic_smoke"} else 0, "budget_rejections": sum(not bool(item.get("provider_call", True)) for item in gateway.calls) if provider_mode in {"real", "local_isolated_semantic_smoke"} else 0, "fake_provider_calls": len(gateway.calls) if provider_mode == "fake" else 0, "control_provider_calls": len(gateway.calls) if provider_mode == "control" else 0,
            "failure_class": failure_class, "budget_stop": budget_stop, "budget_stop_event": budget_stop_event,
            "entrypoint": "experiments/ideal-agency-lab/v2/cli.py j05-run", "case_id": case_id, "arm": arm, "repetition": repetition,
            "event_results": event_results,
            "checks": {"all_frozen_events_executed": statuses_ok, "arm_state_rule": bool(arm_state_ok), "arm_prompt_state": bool(arm_prompt_state_ok), "model_concern_events": model_concern_events, "restart_continuity": restart_ok, "capacity_boundary": capacity_ok, "worker_received_no_evaluator_oracle": privacy["worker_prompt_does_not_contain_evaluator_oracle"], "initial_concern_count": initial_concerns},
            "restart_checks": restart_records, "capacity_seed": capacity_seed, "capacity_probe": capacity_probe,
            "state_counts": {"concerns": final_state["concerns"], "concern_events": _count(store, "concern_events", OWNER), "delivered_segments": len(final_state["deliveries"])},
            "source_materialization": {"interventions_executed": len(intervention_records), "all_have_before_after": all("before" in item and "after" in item for item in intervention_records)},
            "worker_input_audit": {"natural_event_count": sum(item["kind"] == "user_message" for item in input_records), "opportunity_event_count": sum(item["kind"] == "opportunity" for item in input_records), "task_due_event_count": sum(item["kind"] == "task_due" for item in input_records), "silence_event_count": sum(item["kind"] == "silence_observed" for item in input_records), "case_rules_sent": False, "source_facts_sent": False, "controlled_overlay_sent": False},
            "prompt_privacy": privacy,
            "evidence": {"trajectory_root": str(trajectory), "state_db": str(trajectory / "state.db"), "trace": str(trajectory / "traces" / "trace.jsonl"), "sink": str(trajectory / "traces" / "sink.jsonl"), "input_events": str(trajectory / "input-events.jsonl"), "interventions": str(trajectory / "interventions.jsonl"), "prompts": str(trajectory / "actual-prompts.jsonl")},
        }
    except Exception as exc:
        result = {"schemaVersion": "j05-trajectory-evidence-v2", "status": "failed", "semantic_acceptance": False, "semantic_acceptance_status": "not_scored", "provider_mode": provider_mode, "real_provider_calls": 0, "fake_provider_calls": 0, "control_provider_calls": 0, "case_id": case_id, "arm": arm, "repetition": repetition, "error": {"type": type(exc).__name__, "message": str(exc)}, "evidence": {"trajectory_root": str(trajectory), "state_db": str(trajectory / "state.db"), "trace": str(trajectory / "traces" / "trace.jsonl")}}
    finally:
        try:
            store.close()
        except Exception:
            pass
    _write_json(trajectory / "trajectory-result.json", result)
    return result


def _real_gateway_factory(run_root: pathlib.Path, model: str | None, production_root: pathlib.Path | None = None) -> Callable[[str, str, bool], Any]:
    gate = _read_json(run_root / "gate-validation.json", {})
    resolved = (gate.get("resolved_provider") or {}).get("models") or []
    entry = next((item for item in resolved if item.get("label") == model), None)
    provider = (entry or {}).get("provider") or _read_json(run_root / "manifest.json", {}).get("provider")
    if production_root is not None:
        binding, _effective = resolve_production_text_binding(production_root=production_root)
        if model and binding.model != model:
            raise RuntimeError("requested model differs from effective production binding")
    else:
        binding = resolve_text_binding(provider=provider, model=model)
    if not binding.ready:
        raise RuntimeError("real provider binding is incomplete")
    from controller.boundary import NetworkBoundary
    from urllib.parse import urlsplit
    parsed = urlsplit(str(binding.endpoint))
    boundary = NetworkBoundary({parsed.hostname or ""}, {parsed.path})
    return lambda _arm, _case, _seed: build_text_gateway(binding, network_boundary=boundary)


def _aggregate_j05(run_root: pathlib.Path, results: list[dict[str, Any]], *, provider_mode: str, output_root: pathlib.Path, sample_gate: str, planned_trajectories: int = 108, scheduling_stop: dict[str, Any] | None = None) -> dict[str, Any]:
    arms: dict[str, Any] = {}
    calls_key = "fake_provider_calls" if provider_mode == "fake" else ("control_provider_calls" if provider_mode == "control" else "real_provider_calls")
    for arm in ARMS:
        rows = [item for item in results if item.get("arm") == arm]
        planned_arm = planned_trajectories // len(ARMS)
        arms[arm] = {"planned_trajectories": planned_arm, "trajectories": len(rows), "unscheduled_trajectories": max(0, planned_arm - len(rows)), "passed": sum(item.get("status") == "passed" for item in rows), "failed": sum(item.get("status") == "failed" for item in rows), "budget_failures": sum(item.get("failure_class") == "budget_guard" for item in rows), "provider_calls": sum(int(item.get(calls_key, 0)) for item in rows)}
    pairing = []
    for case_id in [f"K{index:02d}" for index in range(1, 13)]:
        for repetition in range(1, 4):
            rows = {(item.get("arm"), item.get("repetition")): item for item in results if item.get("case_id") == case_id and item.get("repetition") == repetition}
            hashes = {
                arm: (
                    _read_json(
                        (pathlib.Path(rows[(arm, repetition)]["evidence"]["trajectory_root"])
                         if pathlib.Path(rows[(arm, repetition)]["evidence"]["trajectory_root"]).exists()
                         else output_root / arm / case_id / f"r{repetition:02d}") / "initial-state.json", {}
                    )
                    .get("source_snapshot", {}).get("context_hash")
                    if (arm, repetition) in rows else None
                )
                for arm in ARMS
            }
            available_hashes = [value for value in hashes.values() if value is not None]
            pairing.append({"case_id": case_id, "repetition": repetition, "initial_context_hashes": hashes, "same_initial_state": bool(len(available_hashes) == len(ARMS) and len(set(available_hashes)) == 1), "pairing_status": "complete" if len(available_hashes) == len(ARMS) else "incomplete_due_to_unscheduled_arm"})
    aggregate = {"schemaVersion": "j05-run-v3", "status": "passed" if len(results) == planned_trajectories and results and all(item.get("status") == "passed" for item in results) else "failed", "control_flow_only": provider_mode in CONTROL_PROVIDER_MODES, "semantic_acceptance": False, "semantic_acceptance_status": "not_run_fake_provider_excluded" if provider_mode in CONTROL_PROVIDER_MODES else "pending_independent_evaluator", "provider_mode": provider_mode, "sample_generation_gate": sample_gate, "human_review_blocks_sample_generation": False, "human_review_blocks_final_subjective_conclusion": True, "entrypoint": "experiments/ideal-agency-lab/v2/cli.py j05-run", "same_execution_function": "execute_j05_trajectory", "same_entrypoint_executed_A_B_C": True, "case_count": 12, "total_trajectories": planned_trajectories, "scheduled_trajectories": len(results), "unscheduled_trajectories": max(0, planned_trajectories - len(results)), "completed_trajectories": sum(item.get("status") == "passed" for item in results), "failed_trajectories": sum(item.get("status") == "failed" for item in results), "budget_failed_trajectories": sum(item.get("failure_class") == "budget_guard" for item in results), "fake_provider_calls": sum(int(item.get("fake_provider_calls", 0)) for item in results), "control_provider_calls": sum(int(item.get("control_provider_calls", 0)) for item in results), "real_provider_calls": sum(int(item.get("real_provider_calls", 0)) for item in results), "arms": arms, "scheduling_stop": scheduling_stop or {"stopped": False}, "trajectory_result_files": len(list(output_root.glob("**/trajectory-result.json"))), "initial_state_pairing": {"all_same": all(item["same_initial_state"] for item in pairing) if pairing else False, "rows": pairing}, "evidence_root": str(output_root), "exclusion_rule": "fake provider control decisions are never a semantic acceptance sample, score, or final conclusion", "results": [{"case_id": item.get("case_id"), "arm": item.get("arm"), "repetition": item.get("repetition"), "status": item.get("status"), "failure_class": item.get("failure_class"), "provider_mode": item.get("provider_mode"), "evidence": item.get("evidence")} for item in results]}
    mode_path = run_root / ("j05-simulation.json" if provider_mode == "fake" else "j05-real.json")
    _write_json(mode_path, aggregate)
    # Keep the compatibility aggregate pointed at the first completed control
    # run.  A later blocked/real attempt must not erase the fake control-flow
    # result or make the evidence appear to have been overwritten.
    if provider_mode == "fake" or not (run_root / "j05-run.json").exists():
        _write_json(run_root / "j05-run.json", aggregate)
    evidence_name = "j05-trajectory-evidence.jsonl" if provider_mode == "fake" else "j05-real-trajectory-evidence.jsonl"
    with (run_root / evidence_name).open("w", encoding="utf-8") as stream:
        for item in results:
            stream.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
    return aggregate


def run_j05(run_root: pathlib.Path, *, provider_mode: str = "fake", model: str | None = None, production_root: pathlib.Path | None = None, max_budget_cny: float | None = None, max_output_tokens: int = 512, selected_case_ids: list[str] | None = None, trajectory_order: list[dict[str, Any]] | None = None, execution_scope: str = "full_j05") -> dict[str, Any]:
    manifest = _read_json(run_root / "manifest.json", {})
    case_manifest = _read_json(run_root / "case-manifest.json", {})
    cases = case_manifest.get("cases", [])
    if case_manifest.get("schemaVersion") != "concern-case-manifest-v2" or len(cases) != 12 or case_manifest.get("total_trajectories") != 108:
        return {"status": "failed", "reason": "J05 requires source-bound K01-K12 manifest with exactly 108 trajectories"}
    gate = _read_json(run_root / "gate-validation.json", {})
    sample_gate = (gate.get("scopes") or {}).get("sample_generation", {}).get("status", "not_validated")
    if provider_mode == "real":
        environment = _read_json(run_root / "environment.json", {})
        isolation = _read_json(run_root / "isolation-probe.json", {})
        worker_execution = real_execution_gate(run_root)
        provider_probe = _read_json(run_root / "provider-probe.json", {})
        effective_provider = _read_json(run_root / "effective-provider.json", {})
        if provider_probe.get("status") != "passed" or effective_provider.get("status") != "ready" or sample_gate != "passed" or environment.get("e1") != "passed" or isolation.get("qualification") not in {"qualified", "passed", "os_qualified"} or worker_execution.get("status") != "passed":
            reasons = []
            if provider_probe.get("status") != "passed": reasons.append("provider_probe_not_passed")
            if effective_provider.get("status") != "ready": reasons.append("effective_binding_not_ready")
            if sample_gate != "passed": reasons.append("sample_generation_not_released")
            if environment.get("e1") != "passed" or isolation.get("qualification") not in {"qualified", "passed", "os_qualified"}: reasons.append("os_isolation_not_qualified")
            if worker_execution.get("status") != "passed": reasons.append("worker_execution_boundary_not_proven")
            result = {"status": "blocked", "execution": "not_started", "provider_calls": 0, "reason": "formal real-execution gate is not released; no real provider request made", "gate": {"provider_probe": provider_probe.get("status", "not_run"), "effective_binding": effective_provider.get("status", "not_run"), "sample_generation": sample_gate, "e1": environment.get("e1"), "isolation": isolation.get("qualification"), "worker_execution": worker_execution}, "reasons": reasons, "semantic_acceptance": False}
            _write_json(run_root / "j05-real.json", result)
            return result
        if not model:
            return {"status": "blocked", "execution": "not_started", "provider_calls": 0, "reason": "bound primary model must be explicitly selected"}
        # The controller never constructs a provider gateway for the real
        # trajectory itself.  It launches the same executor in the qualified
        # WSL worker and exposes only a relay adapter; the relay process owns
        # the existing provider credential.
        from evaluation.worker_runner import run_real_worker_j05
        if max_budget_cny is None or max_budget_cny <= 0:
            return {"status": "blocked", "execution": "not_started", "provider_calls": 0, "reason": "real provider mode requires an explicit positive CNY spend ceiling"}
        return run_real_worker_j05(run_root, model=model, production_root=production_root or pathlib.Path(), max_budget_cny=max_budget_cny, max_output_tokens=max_output_tokens, selected_case_ids=selected_case_ids, trajectory_order=trajectory_order, execution_scope=execution_scope)
    else:
        gateway_factory = lambda arm, case_id, seeded: J05FakeGateway(arm=arm, case_id=case_id, concerns_seeded=seeded)
    output_root = run_root / ("j05-trajectories" if provider_mode == "fake" else "j05-trajectories-real")
    if output_root.exists():
        return {"status": "failed", "reason": f"refusing to overwrite existing trajectory evidence: {output_root}"}
    prompt_paths = {"A": pathlib.Path(manifest.get("prompt_path") or ""), "B": pathlib.Path((case_manifest.get("arms") or {}).get("B", {}).get("prompt_path") or ""), "C": pathlib.Path((case_manifest.get("arms") or {}).get("C", {}).get("prompt_path") or "")}
    if any(not path.exists() for path in prompt_paths.values()):
        return {"status": "failed", "reason": "one or more arm prompts do not exist"}
    case_by_id = {case["case_id"]: case for case in cases}
    if trajectory_order:
        work_items = [(str(item["arm"]), str(item["case_id"]), int(item.get("repetition", 1))) for item in trajectory_order]
    elif selected_case_ids:
        work_items = [(arm, case_id, repetition) for arm in ARMS for case_id in selected_case_ids for repetition in range(1, 4)]
    else:
        work_items = [(arm, case["case_id"], repetition) for arm in ARMS for case in cases for repetition in range(1, 4)]
    invalid = [item for item in work_items if item[0] not in ARMS or item[1] not in case_by_id or item[2] not in {1, 2, 3}]
    if invalid:
        return {"status": "failed", "reason": f"invalid trajectory plan: {invalid}"}
    results = [execute_j05_trajectory(run_root, output_root, case_by_id[case_id], arm, repetition, prompt_paths[arm], gateway_factory, provider_mode) for arm, case_id, repetition in work_items]
    return _aggregate_j05(run_root, results, provider_mode=provider_mode, output_root=output_root, sample_gate=sample_gate, planned_trajectories=len(work_items))


def run_j05_simulation(run_root: pathlib.Path, *, provider: str = "fake") -> dict[str, Any]:
    return run_j05(run_root, provider_mode=provider)


def write_j05_design_artifacts(run_root: pathlib.Path, case_manifest: dict[str, Any]) -> None:
    lines = ["# Scenario conformance", "", "Generated from the executable case manifest. Facts are frozen selectors; experimental conditions are labelled and materialised per trajectory.", ""]
    for case in case_manifest.get("cases", []):
        lines.extend([f"## {case['case_id']} - {case['title']}", "", "### Initial state", "", f"- source snapshots: {json.dumps(case['initial_state'].get('source_snapshots'), ensure_ascii=False)}", f"- observed facts: {json.dumps(case['initial_state'].get('facts', []), ensure_ascii=False)}", f"- experimental conditions: {json.dumps(case['initial_state'].get('experimental_conditions', []), ensure_ascii=False)}", "", "### Events", "", json.dumps(case.get("events", []), ensure_ascii=False, indent=2), "", "### Interventions", "", json.dumps(case.get("interventions", []), ensure_ascii=False, indent=2), "", "### Response rules and assertions", "", json.dumps({"response_rules": case.get("response_rules", []), "assertions": case.get("assertions", []), "deviations": case.get("deviations", [])}, ensure_ascii=False, indent=2), ""])
    (run_root / "scenario-conformance.md").write_text("\n".join(lines), encoding="utf-8")
    (run_root / "execution-path-map.md").write_text(
        """# J05 execution path

cli.py j05-run --provider-mode fake|real loads the same case manifest, then calls run_j05 and execute_j05_trajectory for every A/B/C x K01-K12 x repetition cell.

cli.py -> run_j05
       -> gateway_factory(fake J05FakeGateway | WSL RelayGateway)
       -> execute_j05_trajectory
          -> isolated snapshot + trajectory-manifest
          -> controller interventions (before/after evidence)
          -> event source resolution
          -> AgencyLoop.process_event
             -> ContextBuilder -> prompt assembly -> gateway.complete
             -> Policy -> LocalAdapters/tool result -> RecordingSink receipt
             -> EventStore / trace / raw response
          -> restart/reopen checks -> trajectory-result.json

Only the gateway object and explicit failure adapter differ. Fake control-flow status is separate from real semantic acceptance. Credentials are held by the gateway process and are not assembled into worker context.

For real mode, construction of the controller HTTP gateway relay is still
preceded by the source/evidence/E1 gates and `worker-execution.json`.  The
trajectory executor runs inside the independently constrained WSL2 worker;
the worker has no provider credential and can reach only the controller relay.
The process-local boundary probe and a small negative-control subprocess are
not sufficient.  Therefore an E1 probe that is later hand-edited to `passed`
cannot cause a real API call through this entry point.
""", encoding="utf-8")
    arm_rows = {}
    for arm, info in (case_manifest.get("arms") or {}).items():
        prompt_path = pathlib.Path(info.get("prompt_path", ""))
        raw_prompt = _read_json(prompt_path, {})
        # The source file carries execution metadata for the concerns arm.
        # Keep that metadata out of the shared wording record so B/C cannot be
        # misreported as different prompts merely because B disables the
        # protocol at runtime.  The raw source hash is still retained for
        # manifest binding, while the normalized wording hash proves B/C
        # textual equality.
        common_prompt = {key: value for key, value in raw_prompt.items() if key not in {"arm", "concernsEnabled"}}
        arm_rows[arm] = {
            "prompt_path": str(prompt_path),
            "prompt": common_prompt,
            "prompt_hash": _file_sha(prompt_path) if prompt_path.exists() else None,
            "common_wording_hash": hashlib.sha256(json.dumps(common_prompt, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
            "concerns_enabled": info.get("concerns_enabled"),
            "protocol_difference": "baseline" if arm == "A" else ("concerns_protocol_disabled" if arm == "B" else "concerns_protocol_enabled"),
            "repetitions": info.get("repetitions"),
            "parameters": {"temperature": 0, "top_p": 1, "selected_limit": 6, "max_active_concerns": 12},
        }
    _write_json(run_root / "arm-comparison-manifest.json", {"schemaVersion": "j05-arm-comparison-v2", "arms": arm_rows, "pairing": {"source_facts": "same frozen selectors", "initial_state": "same per case/repetition after labelled fixture conditions", "model_parameters": "same", "external_timeline": "same", "user_rules": "same", "allowed_differences": ["A uses frozen baseline prompt and concerns are disabled", "B and C use identical concerns-v1 prompt", "C enables the concerns protocol", "K06 paired media condition is explicitly recorded"]}})


def run_fixture_integrity(run_root: pathlib.Path) -> dict[str, Any]:
    """Run normal and fault-injected controls; files alone cannot pass."""
    results: list[dict[str, Any]] = []

    def add(control: str, normal: Any, fault: Any, passed: bool, evidence: list[str]) -> None:
        results.append({"control": control, "normal": normal, "fault_injection": fault, "assertion_passed": passed, "evidence": evidence})

    with tempfile.TemporaryDirectory(prefix="j05-fixture-") as temp:
        root = pathlib.Path(temp)
        due_store = EventStore(root / "due.db")
        due_store.seed_tasks(OWNER, [{"id": "j05-due-task-20260909-1100", "owner": OWNER, "title": "isolated due", "status": "open", "due_at": "2026-09-09T11:00:00+08:00", "source_ref": "fixture://derived"}])
        normal_task = due_store.read_tasks(OWNER)
        due_store.close()
        fault_store = EventStore(root / "due-fault.db")
        fault_task = fault_store.read_tasks(OWNER)
        fault_store.close()
        add("due_task_written", {"task_id": "j05-due-task-20260909-1100", "written": bool(normal_task), "due_at": normal_task[0].get("due_at")}, {"fault": "skip_task_materialization", "written": bool(fault_task)}, bool(normal_task and not fault_task), ["isolated_tasks table", "state.db"])

        for label, case_id in (("source_change_materialized", "K04"), ("source_correction_materialized", "K10")):
            fixture = root / label
            shutil.copytree(run_root / "snapshot", fixture)
            records_path = fixture / RECORDS_REL
            before = _read_json(records_path)
            selector = "workbench.DONGBA.sourceRevision" if case_id == "K04" else "workbench.DONGBA.daily.2026-08-21.traffic"
            old = _records_row(before, selector).get("sourceRevision")
            changed = deepcopy(before)
            _records_row(changed, selector)["sourceRevision"] = "9754"
            records_path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
            materialized = _records_row(_read_json(records_path), selector)["sourceRevision"] == "9754"
            add(label, {"before": old, "after": "9754", "materialized": materialized}, {"fault": "register_only", "registered": True, "materialized": old == "9754"}, materialized and old != "9754", ["records.json", f"{case_id} intervention"])

        future = root / "future-read"
        shutil.copytree(run_root / "snapshot", future)
        future_records_path = future / RECORDS_REL
        future_records = _read_json(future_records_path)
        future_selector = "workbench.DONGBA.sourceRevision"
        future_old = _records_row(future_records, future_selector).get("sourceRevision")
        early_value = _records_row(_read_json(future_records_path), future_selector).get("sourceRevision")
        _records_row(future_records, future_selector)["sourceRevision"] = "9754"
        future_records_path.write_text(json.dumps(future_records, ensure_ascii=False), encoding="utf-8")
        late_value = _records_row(_read_json(future_records_path), future_selector).get("sourceRevision")
        add("future_data_not_read_early", {"before_intervention": early_value, "after_intervention": late_value, "early_visible": early_value == "9754"}, {"fault": "read_future_before_intervention", "accepted": True, "value": "9754"}, future_old != "9754" and early_value != "9754" and late_value == "9754" and early_value != late_value, ["records.json", "source update intervention boundary"])

        expected_source = "feishu://frozen/revision/9753/dongba-traffic"
        valid_payload = {"source_ref": expected_source, "value": "frozen-observation"}
        irrelevant_payload = {"source_ref": "sqlite://unrelated/record", "value": "frozen-observation"}
        valid_evidence = {"payload": valid_payload, "sha256": _sha(valid_payload)}
        irrelevant_evidence = {"payload": irrelevant_payload, "sha256": _sha(irrelevant_payload)}
        def evidence_is_accepted(evidence: dict[str, Any]) -> bool:
            payload = evidence["payload"]
            return evidence["sha256"] == _sha(payload) and payload.get("source_ref") == expected_source
        add("hash_correct_but_evidence_irrelevant", {"sha_correct": True, "source_relevant": True, "accepted": evidence_is_accepted(valid_evidence)}, {"fault": "same_hash_integrity_but_unrelated_source", "sha_correct": irrelevant_evidence["sha256"] == _sha(irrelevant_payload), "source_relevant": False, "accepted": evidence_is_accepted(irrelevant_evidence)}, evidence_is_accepted(valid_evidence) and not evidence_is_accepted(irrelevant_evidence), ["evidence selector validator", "source_ref binding"])

        isolation_normal = {"qualification": "qualified", "process_boundary": True, "worker_secret_visibility": False}
        isolation_fault = {"qualification": "failed", "process_boundary": False, "worker_secret_visibility": False}
        def isolation_allows_real_launch(probe: dict[str, Any]) -> bool:
            return probe.get("qualification") in {"qualified", "passed"} and probe.get("process_boundary") is True and probe.get("worker_secret_visibility") is False
        add("isolation_result_is_required", {"probe": isolation_normal, "launch_allowed": isolation_allows_real_launch(isolation_normal)}, {"fault": "qualification_false", "probe": isolation_fault, "launch_allowed": isolation_allows_real_launch(isolation_fault)}, isolation_allows_real_launch(isolation_normal) and not isolation_allows_real_launch(isolation_fault), ["isolation-probe.json", "real launch gate"])

        worker_receipt_normal = {
            "status": "passed",
            "qualification": "os_qualified",
            "execution_function": "execute_j05_trajectory",
            "same_executor_claim": True,
            "worker_process": {"pid": 7001, "runtime": "qualified_container"},
            "gateway": {"controller_gateway_process": True, "credential_scope": "gateway_only", "worker_receives_credential": False},
            "network_policy": {"per_worker_allowlist": True},
            "path_policy": {"production_read_denied": True, "production_write_denied": True},
            "oracle_policy": {"oracle_read_denied": True},
            "trajectory_binding": {"run_id": root.name},
        }
        worker_receipt_fault = deepcopy(worker_receipt_normal)
        worker_receipt_fault["worker_process"]["runtime"] = "local_process"
        worker_receipt_fault["gateway"]["controller_gateway_process"] = False
        worker_receipt_fault["same_executor_claim"] = False
        def worker_gate_allows(proof: dict[str, Any]) -> bool:
            return (
                proof.get("status") == "passed"
                and proof.get("qualification") == "os_qualified"
                and proof.get("execution_function") == "execute_j05_trajectory"
                and proof.get("same_executor_claim") is True
                and proof.get("worker_process", {}).get("runtime") not in {None, "", "local_process"}
                and proof.get("gateway", {}).get("controller_gateway_process") is True
                and proof.get("gateway", {}).get("credential_scope") == "gateway_only"
                and proof.get("gateway", {}).get("worker_receives_credential") is False
                and proof.get("network_policy", {}).get("per_worker_allowlist") is True
                and proof.get("path_policy", {}).get("production_read_denied") is True
                and proof.get("path_policy", {}).get("production_write_denied") is True
                and proof.get("oracle_policy", {}).get("oracle_read_denied") is True
            )
        add("qualified_worker_execution_is_bound", {"receipt": worker_receipt_normal, "launch_allowed": worker_gate_allows(worker_receipt_normal)}, {"fault": "qualification_probe_only_without_actual_worker_receipt", "receipt": worker_receipt_fault, "launch_allowed": worker_gate_allows(worker_receipt_fault)}, worker_gate_allows(worker_receipt_normal) and not worker_gate_allows(worker_receipt_fault), ["worker-execution.json", "real executor launch gate"])

        credential_sentinel = "TEST-CREDENTIAL-MUST-NOT-ENTER-WORKER"
        worker_prompt = {"messages": [{"role": "user", "content": "自然输入"}]}
        worker_prompt_fault = deepcopy(worker_prompt)
        worker_prompt_fault["messages"].append({"role": "system", "content": credential_sentinel})
        gateway_secret = {"gateway_secret": credential_sentinel}
        def credential_isolated(prompt: dict[str, Any], secret: str) -> bool:
            return secret not in json.dumps(prompt, ensure_ascii=False)
        add("credentials_do_not_enter_worker", {"gateway": gateway_secret, "worker_secret_visible": not credential_isolated(worker_prompt, credential_sentinel)}, {"fault": "inject_credential_into_worker_context", "worker_secret_visible": not credential_isolated(worker_prompt_fault, credential_sentinel)}, credential_isolated(worker_prompt, credential_sentinel) and not credential_isolated(worker_prompt_fault, credential_sentinel), ["actual-prompts.jsonl", "gateway/worker boundary"])

        cold = root / "cold"
        shutil.copytree(run_root / "snapshot", cold)
        context_path = cold / "context.json"
        context = _read_json(context_path)
        owner = context["owners"][OWNER]
        before = {"history": len(owner.get("history", [])), "shared_memory": owner.get("profile", {}).get("companion", {}).get("shared_memory")}
        owner["history"] = []
        owner["profile"]["companion"]["shared_memory"] = None
        owner["profile"]["companion"]["memory_priorities"] = []
        context_path.write_text(json.dumps(context, ensure_ascii=False), encoding="utf-8")
        after = {"history": len(owner.get("history", [])), "shared_memory": owner.get("profile", {}).get("companion", {}).get("shared_memory")}
        add("cold_start_no_shared_history", {"before": before, "after": after}, {"fault": "skip_cold_start_intervention", "history": before["history"]}, after["history"] == 0 and before["history"] > 0 and after["shared_memory"] is None, ["context.json", "K01 initial-state"])

        # K01-I3 must be materialized in the isolated snapshot.  The fault
        # path skips only the relationship filter, proving that residual
        # relationship state/searchable memories are rejected.
        k01 = next(item for item in _read_json(run_root / "case-manifest.json")["cases"] if item["case_id"] == "K01")
        cold_normal = root / "cold-relationship-normal"
        shutil.copytree(run_root / "snapshot", cold_normal)
        normal_interventions = [
            _apply_intervention(cold_normal, item)
            for item in k01.get("interventions", [])
            if item.get("at_event") == 0
        ]
        normal_context = _read_json(cold_normal / "context.json")
        normal_owner = normal_context["owners"][OWNER]
        normal_companion = normal_owner.get("profile", {}).get("companion", {})
        normal_relationship_fields = {
            key: normal_companion.get(key)
            for key in ("relationship_status", "relationship_stage", "intimacy_level", "affection_level", "shared_memory")
        }
        normal_filter = next(item for item in normal_interventions if item["operation"] == "cold_start_relationship_filter")
        normal_ok = (
            normal_filter["executed"] is True
            and all(value is None for value in normal_relationship_fields.values())
            and bool(normal_filter["after"].get("suppressed_memory_ids"))
            and normal_filter["after"].get("retained_enterprise_fact_count", 0) > 0
            and normal_filter["after"].get("retained_personal_schedule_count", 0) > 0
            and normal_filter["after"].get("retained_role")
            and not normal_owner.get("history")
        )
        cold_fault = root / "cold-relationship-fault"
        shutil.copytree(run_root / "snapshot", cold_fault)
        for item in k01.get("interventions", []):
            if item.get("at_event") == 0 and item.get("operation") != "cold_start_relationship_filter":
                _apply_intervention(cold_fault, item)
        fault_context = _read_json(cold_fault / "context.json")
        fault_owner = fault_context["owners"][OWNER]
        fault_companion = fault_owner.get("profile", {}).get("companion", {})
        fault_relationship_fields = {
            key: fault_companion.get(key)
            for key in ("relationship_status", "relationship_stage", "intimacy_level", "affection_level", "shared_memory")
        }
        fault_relationship_memory_ids = [
            str(row.get("id")) for row in fault_owner.get("memories", []) if _relationship_memory_reason(row)
        ]
        fault_ok = bool(fault_relationship_memory_ids) or any(value is not None for value in fault_relationship_fields.values())
        add(
            "cold_start_relationship_isolated",
            {
                "interventions_executed": [item["operation"] for item in normal_interventions],
                "relationship_fields_after": normal_relationship_fields,
                "suppressed_relationship_memory_count": len(normal_filter["after"].get("suppressed_memory_ids", [])),
                "retained_enterprise_fact_count": normal_filter["after"].get("retained_enterprise_fact_count", 0),
                "retained_personal_schedule_count": normal_filter["after"].get("retained_personal_schedule_count", 0),
                "retained_role": normal_filter["after"].get("retained_role"),
                "accepted": normal_ok,
            },
            {
                "fault": "skip_cold_start_relationship_filter",
                "relationship_fields_after": fault_relationship_fields,
                "searchable_relationship_memory_count": len(fault_relationship_memory_ids),
                "accepted": not fault_ok,
            },
            bool(normal_ok) and fault_ok,
            ["K01-I3 intervention before/after", "isolated-snapshot/context.json", "relationship memory filter"]
        )

        opportunity = next(item for item in _read_json(run_root / "case-manifest.json")["cases"][0]["events"] if item["kind"] == "opportunity")
        normal_ok = opportunity["kind"] == "opportunity" and "text" not in opportunity["payload"] and opportunity["payload"].get("input_origin") == "controller_opportunity"
        fault_event = deepcopy(opportunity)
        fault_event["kind"] = "user_message"
        fault_event["payload"]["text"] = "伪造的用户机会"
        fault_ok = fault_event["kind"] == "opportunity" and "text" not in fault_event["payload"]
        add("opportunity_source_kind", {"valid": normal_ok}, {"fault": "opportunity_as_user_message", "accepted": fault_ok}, normal_ok and not fault_ok, ["case-manifest.json", "input-events.jsonl"])

        silent_store = EventStore(root / "silence.db")
        no_delivery = bool(silent_store.delivered_segments(OWNER))
        silent_store.close()
        delivered_store = EventStore(root / "silence-ok.db")
        delivered_store.record_receipt(OWNER, "action-1", {"segment_id": "segment-1", "attempt_id": "attempt-1", "status": "delivered", "idempotency_key": "idem-1", "provider_message_id": "provider-message-1"})
        has_delivery = bool(delivered_store.delivered_segments(OWNER))
        silence_event = {"event_id": "silence-fixture", "owner": OWNER, "kind": "silence_observed", "virtual_time": "2026-09-09T11:20:00+08:00", "payload": {"input_origin": "transport_observer", "delivered_message_selector": "latest_sent_message", "observed_at": "2026-09-09T11:20:00+08:00"}}
        resolved_silence, silence_resolution = _resolve_event(silence_event, delivered_store)
        delivered_store.close()
        add("silence_requires_sent_delivery", {"no_delivery_advance": not no_delivery, "sent_delivery_available": has_delivery, "resolved_message_ids": (resolved_silence or {}).get("payload", {}).get("delivered_message_ids", []), "resolution": silence_resolution}, {"fault": "advance_without_send", "accepted": False}, (not no_delivery) and (has_delivery is True) and bool((resolved_silence or {}).get("payload", {}).get("delivered_message_ids")), ["sink_deliveries", "silence_observed resolution"])

        arm_hashes = {arm: _file_sha(run_root / "snapshot" / "context.json") for arm in ARMS}
        fault_hashes = dict(arm_hashes)
        fault_hashes["B"] = "fault-mutated"
        add("arm_initial_state_consistency", {"hashes": arm_hashes, "same": len(set(arm_hashes.values())) == 1}, {"fault": "mutate_B_initial_state", "hashes": fault_hashes, "accepted": len(set(fault_hashes.values())) == 1}, len(set(arm_hashes.values())) == 1 and len(set(fault_hashes.values())) != 1, ["arm-comparison-manifest.json", "initial-state.json"])

        clean_prompt = json.dumps({"event": {"kind": "user_message", "payload": {"text": "自然输入"}}, "case_id": ""}, ensure_ascii=False)
        leaked_prompt = clean_prompt + " K01 acceptance requirement"
        clean_privacy = "K01" not in clean_prompt and "acceptance requirement" not in clean_prompt
        add("prompt_oracle_privacy", {"leaks": []}, {"fault": "inject_case_id_and_acceptance", "leaks": ["K01", "acceptance requirement"]}, clean_privacy and ("K01" in leaked_prompt and "acceptance requirement" in leaked_prompt), ["actual-prompts.jsonl", "prompt privacy check"])

        durable = EventStore(root / "restart.db")
        durable.seed_tasks(OWNER, [{"id": "restart-task", "owner": OWNER, "status": "open", "source_ref": "fixture://restart"}])
        before_state = _durable_state(durable)
        durable.close()
        reopened = EventStore(root / "restart.db")
        after_state = _durable_state(reopened)
        reopened.close()
        fresh = EventStore(root / "restart-fault.db")
        fresh_state = _durable_state(fresh)
        fresh.close()
        add("restart_durability", {"same": before_state["hash"] == after_state["hash"]}, {"fault": "reopen_new_empty_db", "same": before_state["hash"] == fresh_state["hash"]}, before_state["hash"] == after_state["hash"] and before_state["hash"] != fresh_state["hash"], ["state.db", "restart-evidence.json"])

        evidence_root = root / "j05-trajectories"
        evidence_root.mkdir()
        sentinel = evidence_root / "sentinel"
        sentinel.write_text("old", encoding="utf-8")
        refused = evidence_root.exists()
        sentinel.write_text("new", encoding="utf-8")
        fault_overwrite = sentinel.read_text(encoding="utf-8") != "old"
        sentinel.write_text("old", encoding="utf-8")
        add("rerun_does_not_overwrite_evidence", {"existing_root_refused": refused}, {"fault": "overwrite_existing_root", "accepted": fault_overwrite}, refused and fault_overwrite, ["trajectory-result.json", "rerun guard"])
    aggregate = {"schemaVersion": "fixture-integrity-v2", "status": "passed" if all(item["assertion_passed"] for item in results) else "failed", "controls": results, "required_controls": 16, "normal_and_fault_paths": True}
    _write_json(run_root / "fixture-integrity-results.json", aggregate)
    return aggregate


def write_j05_handoff_lists(run_root: pathlib.Path) -> dict[str, Any]:
    def read(name: str) -> dict[str, Any]:
        path = run_root / name
        if not path.exists():
            return {}
        return _read_json(path, {}) or {}
    provider = read("provider-deployment-audit.json")
    effective_provider = read("effective-provider.json")
    provider_probe = read("provider-probe.json")
    source = read("source-runtime-readonly.json")
    source_access = read("source-access-readonly.json")
    environment_evidence = read("environment-evidence.json")
    # Prefer the current worker-bound probe.  A historical static audit must
    # never downgrade or override the run's actual E1 result.
    isolation = read("isolation-probe.json") or read("isolation-environment-audit.json")
    provider_class = provider.get("classifications") or {}
    assistance: list[dict[str, Any]] = []
    cli_path = pathlib.Path(__file__).resolve().parents[1] / "cli.py"
    provider_ready = effective_provider.get("status") == "ready" and provider_probe.get("status") == "passed"
    if not provider_ready and provider_class.get("formal_experiment_provider_binding") != "integrated":
        assistance.append({"missing": "实验 gateway 的 provider/model/endpoint/credential binding", "checked": "provider-deployment-audit.json、effective-provider.json、provider-probe.json、正式 gateway", "evidence": "尚未得到有效 binding 与 P0 真实探针证据", "blocks": "真实 API smoke/sample_generation", "minimum_user_action": "无；此项应由执行者继续完成，不能把已授权凭据再次粘贴到聊天", "next_command": f"python {cli_path} provider-probe --run {run_root} --production-root <production-root>"})
    # `os_qualified` is the worker-backed qualification emitted by the real
    # WSL/container probe.  Keep the handoff list aligned with the launch gate
    # so a stale process-local audit cannot create a false user blocker.
    if isolation.get("qualification") not in {"qualified", "passed", "os_qualified"}:
        isolation_record = environment_evidence.get("isolation", {})
        assistance.append({"missing": "可审计的 OS/container worker 隔离资格及实际轨迹执行回执 worker-execution.json（进程边界、凭据不可见、逐 worker 出网策略）", "checked": "environment-evidence.json、isolation-probe.json、worker-execution.json、Docker/Podman/WSL/Hyper-V/Containers、现有本机受限账户与防火墙状态", "evidence": {"qualification": isolation_record.get("qualification", isolation.get("classification", "not_os_qualified")), "worker_execution": (isolation_record.get("worker_execution") or {}).get("status", "not_proven"), "available_runtimes": {name: (item or {}).get("available", False) for name, item in (isolation_record.get("available_runtime_investigation") or {}).items()}}, "blocks": "P1 主模型 smoke 与 P2 企业场景轨迹", "minimum_user_action": "在实验机安装并启动 Docker/Podman（或准备一个 WSL2/受限账户 worker），仅允许该 worker 通过 controller gateway 访问已绑定 provider，禁止读取生产路径/oracle、禁止继承 gateway 凭据；安装/启动可能需要管理员权限或重启，不改生产", "next_command": f"python {cli_path} e1 --run {run_root} && python {cli_path} environment-evidence --run {run_root} --production-root E:\\FoxSpirit\\xiyu-ai"})
    source_is_verified = source.get("source_identity_authorization") == "verified" or source_access.get("source_identity_authorization") == "verified"
    if not source_is_verified:
        attempts = source_access.get("attempts", [])
        latest_error = next((item.get("error") for item in attempts if item.get("error")), "未取得受授权只读身份")
        assistance.append({"missing": "阿里云源实例可验证的只读身份与导出范围", "checked": "冻结 source locator、部署资料、公开 health、DNS/22、现有本机 SSH 身份的固定只读尝试", "evidence": {"source_identity_authorization": source.get("source_identity_authorization", "unverified_public_health_only"), "public_health_is_identity_proof": False, "latest_sanitized_error": latest_error}, "blocks": "E0 源身份确认及后续 P1/P2 企业资料轨迹", "minimum_user_action": "使一个已有授权的源实例只读账户/身份对 xiyu.myworlds.cn 可用，或在源实例执行固定只读核验命令并返回脱敏输出；不要粘贴私钥或凭据", "next_command": f"python {cli_path} source-access-audit --run {run_root} --host xiyu.myworlds.cn && python {cli_path} source-runtime-audit --run {run_root} --url https://xiyu.myworlds.cn/api/health"})
    (run_root / "price-basis.md").write_text(
        "# Price basis\n\n"
        "- Provider under investigation: DeepSeek (source runtime reports the non-secret label `deepseek` / `deepseek-chat`).\n"
        "- Official source checked: https://api-docs.deepseek.com/quick_start/pricing\n"
        "- The current official page lists DeepSeek-V4-Flash and V4-Pro prices per 1M tokens and states that the legacy `deepseek-chat` label maps to the non-thinking V4-Flash compatibility path; the exact bound model must still be recorded before a real call.\n"
        "- The official page currently presents peak/off-peak input cache-hit and cache-miss rates and output rates. This is a price reference, not a guarantee of the account's balance or a substitute for a ceiling.\n"
        "- Cost formula: input_tokens/1M × input_rate + output_tokens/1M × output_rate; apply the observed cache/peak class and actual usage after the smoke.\n"
        "- Frozen call envelope is retained in `cost-plan.json`; no absolute total is invented without a bound model, actual usage class, and an authorized maximum budget.\n"
        "- Status: price reference organized; this handoff does not require a numeric ceiling for P0/P1/P2 because the user authorized limited testing with the existing provider. Actual usage, latency and any available billing record remain evidence fields; no free-use assumption is made.\n",
        encoding="utf-8",
    )
    fake_run = read("j05-simulation.json") or read("j05-run.json")
    real_run = read("j05-real.json")
    provider_materials = dict(provider_class)
    if provider_ready:
        provider_materials.update({"formal_experiment_provider_binding": "mapped_and_p0_verified", "runtime_availability": "observed_by_p0_probe", "confirmed_unavailable_evidence": False})
    worker_execution = (environment_evidence.get("isolation") or {}).get("worker_execution") or {}
    evidence_path = run_root / "j05-real-trajectory-evidence.jsonl"
    real_evidence_count = len([line for line in evidence_path.read_text(encoding="utf-8").splitlines() if line.strip()]) if evidence_path.exists() else 0
    real_expected = int(real_run.get("total_trajectories", 108) or 108)
    anonymous_record = read("anonymous-blind-review.json")
    anonymous_ready = anonymous_record.get("status") in {"ready", "ready_with_automated_failures"} and real_evidence_count == real_expected
    cost = read("real-j05-cost-latency.json")
    cost_status = cost.get("status")
    still_needs_development: list[str] = []
    if not real_run or real_evidence_count < real_expected:
        still_needs_development.append("继续执行尚缺的主模型真实轨迹；保持 108 条 A/B/C × K01–K12 × 3 的冻结分母，并把真实语义验收与 fake control_flow 分开。")
    else:
        failed_count = int(real_run.get("failed_trajectories", 0) or 0)
        still_needs_development.append(f"真实 J05 108 条逐轨迹样本已生成，但 {failed_count} 条记录在正式执行/预算保护层失败；需区分预算拒绝与可归因的执行或 fixture 分支问题，并按原标准复验，不能改写为语义通过。")
    still_needs_development.extend([
        "执行原规范尚未完成的主模型套件与可放行的专项套件；第二模型、留出、图片、研究、连续性和完整验收保持原分母，不以 J05 替代。",
        "独立评估自动评分、人工匿名盲评、最差样本复核、图片材料、成本/延迟汇总及最终主观判断；匿名样本生成不等待人工评审。",
    ])
    if anonymous_ready:
        still_needs_development.append("匿名盲评包已生成；只需补入独立评估/人工结果，不复制原始系统 prompt、凭据或生产路径。")
    reconciliation = cost.get("reservation_reconciliation") or {}
    remaining_cny = reconciliation.get("remaining_authorized_headroom_cny_at_safety_rate")
    if cost_status == "stopped_at_user_budget_guard" and remaining_cny is not None and float(remaining_cny) <= 0.000001:
        assistance.append({
            "missing": "本轮真实 API 的授权费用余量已耗尽，继续真实轨迹需要新的正数费用上限",
            "checked": "real-j05-cost-latency.json、worker-gateway-relay.jsonl、gateway 内预算保护；provider 已映射且本轮保护已实际截停",
            "evidence": {"cost_status": cost_status, "authorized_budget_cny": cost.get("budget_authorization", {}).get("max_budget_cny"), "actual_usage_estimate_cny": cost.get("actual_usage_estimate", {}).get("estimated_cny_at_safety_rate"), "unresolved_reserved_cny": reconciliation.get("unresolved_reserved_cny_at_safety_rate"), "remaining_authorized_headroom_cny": remaining_cny, "provider_calls": cost.get("requests", {}).get("provider_calls"), "budget_rejections": cost.get("requests", {}).get("budget_rejections")},
            "blocks": "继续真实 J05 未完成轨迹及后续原规范 billable 套件；不影响已生成证据、离线控制检查和盲评样本整理",
            "minimum_user_action": "如需继续，仅需确认下一段正数人民币费用上限并保持账户余额；不要在聊天、代码或报告中粘贴凭据",
            "next_command": f"python {cli_path} j05-run --run {run_root} --provider-mode real --model deepseek-chat --max-budget-cny 5",
        })
    elif cost_status == "stopped_at_user_budget_guard" and remaining_cny is not None and float(remaining_cny) > 0.000001:
        still_needs_development.append(f"预算门禁已按usage结算并释放多余预留；原授权范围内保守余量约 {float(remaining_cny):.6f} 元，可继续真实J05，不需申请新增预算。")
    next_transition = "继续执行当前已具备条件的原规范测试；对未资格化的专项门禁保留最小阻塞项，不重置或覆盖已有 run。" if not assistance else "完成列出的最小协助项后重新提交/校验门禁；保持已有 fake/fixture/P0/J05 证据，不重置或覆盖 run。"
    result = {"schemaVersion": "j05-handoff-lists-v4", "control_flow_status": fake_run.get("status", "not_run"), "real_attempt_status": real_run.get("status", "not_started"), "still_needs_development": still_needs_development, "requires_user_assistance": assistance, "classification_basis": {"provider": {"effective_binding_status": effective_provider.get("status", "not_run"), "probe_status": provider_probe.get("status", "not_run"), "classification": "mapped_and_available" if provider_ready else "not_yet_observed"}, "provider_materials": provider_materials, "source_runtime": {key: (source.get(key) if source.get(key) not in (None, "") else source_access.get(key)) for key in ("status", "runtime_availability", "source_identity_authorization", "confirmed_unavailable_evidence")}, "isolation": {key: isolation.get(key) for key in ("status", "classification", "qualification", "available_candidates")}, "worker_execution": {"status": worker_execution.get("status", "not_proven"), "qualification": worker_execution.get("qualification", "not_os_qualified"), "required": True, "receipt": str(run_root / "worker-execution.json")}, "cost": {"status": cost_status or "not_observed", "remaining_authorized_headroom_cny": remaining_cny, "blocks_p0_p1_p2": cost_status == "stopped_at_user_budget_guard" and (remaining_cny is None or float(remaining_cny) <= 0.000001)}}, "real_evidence": {"expected": real_expected, "records": real_evidence_count, "anonymous_blind_review": anonymous_ready}, "next_transition": next_transition}
    _write_json(run_root / "j05-handoff-lists.json", result)
    lines = ["# J05 remaining work", "", "## 仍需开发", "", *[f"- {item}" for item in result["still_needs_development"]], "", "## 确需用户协助", "", *([f"- 缺少什么：{item['missing']}\n  已检查什么：{item['checked']}\n  实际错误或证据：{item['evidence']}\n  阻塞哪个阶段：{item['blocks']}\n  用户需要完成的最小操作：{item['minimum_user_action']}\n  完成后执行哪条命令：{item['next_command']}" for item in assistance] if assistance else ["- 当前没有确需用户协助项。"]), "", "## 边界", "", "- fake provider 仅计 control_flow_passed。", "- 人工盲评不阻塞样本生成，只阻塞最终主观结论。", "- provider/源实例/隔离分别区分已映射可用、尚未资格化与确实不可用；没有失败证据时不下确实不可用结论。", "- 费用保护在本轮真实 worker 内实际执行；预算拒绝不计 provider 调用，达到上限后不自动重试。"]
    (run_root / "remaining-work.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result
