"""Three-layer context assembly with explicit owner and provenance filters."""
from __future__ import annotations

import hashlib
import json
import pathlib
from datetime import datetime
from copy import deepcopy
from typing import Any


class ContextError(ValueError):
    pass


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


class ContextBuilder:
    def __init__(self, fixture_path: pathlib.Path | None = None, prompt_path: pathlib.Path | None = None,
                 *, snapshot_root: pathlib.Path | None = None, manifest_path: pathlib.Path | None = None,
                 background_mode: str = "resident", store: Any | None = None,
                 concerns_enabled: bool = False, selected_limit: int = 6):
        """Build context from exactly one declared source.

        ``fixture_path`` is retained for deterministic contract tests.  A
        formal FROZEN run must pass ``snapshot_root`` and ``manifest_path``;
        the binding is checked before any owner data is exposed to the worker.
        """
        if snapshot_root is not None and fixture_path is not None:
            raise ContextError("context source is ambiguous")
        self.snapshot_root = snapshot_root.resolve() if snapshot_root else None
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path and manifest_path.exists() else None
        if self.snapshot_root:
            context_path = self.snapshot_root / "context.json"
            if not context_path.exists():
                raise ContextError(f"snapshot context missing: {context_path}")
            self.fixture_path = context_path
            self.fixture = json.loads(context_path.read_text(encoding="utf-8"))
            binding = (self.manifest or {}).get("snapshot_binding", {})
            expected_hash = binding.get("context_hash")
            actual_hash = hashlib.sha256(context_path.read_bytes()).hexdigest()
            if expected_hash and expected_hash != actual_hash:
                raise ContextError("snapshot context hash mismatch")
            if (self.manifest or {}).get("mode") == "FROZEN" and binding.get("snapshot_id") != self.fixture.get("snapshotId"):
                raise ContextError("frozen snapshot binding mismatch")
        elif fixture_path is not None:
            self.fixture_path = fixture_path.resolve()
            self.fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        else:
            raise ContextError("context source is required")
        self.prompt_path = prompt_path
        self.prompt = json.loads(prompt_path.read_text(encoding="utf-8")) if prompt_path and prompt_path.exists() else {"promptVersion": "missing", "rules": []}
        if background_mode not in {"resident", "retrievable"}:
            raise ContextError(f"unsupported background mode: {background_mode}")
        self.background_mode = background_mode
        self.store = store
        self.concerns_enabled = bool(concerns_enabled)
        if selected_limit < 1 or selected_limit > 6:
            raise ContextError("selected_limit must be between 1 and 6")
        self.selected_limit = selected_limit
        self.source_kind = "snapshot" if self.snapshot_root else "fixture"
        self.source_version = self.fixture.get("sourceVersion") or self.fixture.get("schemaVersion", "unknown")

    def owner_data(self, owner: str) -> dict[str, Any]:
        data = self.fixture.get("owners", {}).get(owner)
        if not data:
            raise ContextError(f"owner not found: {owner}")
        return deepcopy(data)

    def build(self, event: dict[str, Any], *, thread_state: dict[str, Any] | None = None, related_tool_result: dict[str, Any] | None = None) -> dict[str, Any]:
        owner = event["owner"]
        data = self.owner_data(owner)
        history = [item for item in data.get("history", []) if item.get("owner") == owner]
        stable_data = data.get("stable", {})
        profile = data.get("profile", {})
        enterprise_profile = deepcopy(stable_data.get("enterprise_profile", profile))
        recent_history = history
        active_tasks = [task for task in data.get("tasks", []) if task.get("owner") == owner]
        if self.background_mode == "retrievable":
            # The data remains in the frozen snapshot for the adapters, but
            # the model must retrieve this background through the declared
            # catalog instead of receiving a second resident copy in prompt.
            enterprise_profile = {
                "retrieval_required": True,
                "resource_kind": "profile",
                "source_ref": profile.get("source_ref", f"{self.source_kind}://{owner}/profile"),
            }
            recent_history = []
            active_tasks = []
        stable = {
            "prompt_version": self.prompt.get("promptVersion", "missing"),
            "prompt_rules": self.prompt.get("rules", []),
            "prompt_profile": deepcopy(self.prompt.get("profile", {})),
            "prompt_behavior_vectors": deepcopy(self.prompt.get("behavior_vectors", [])),
            "prompt_behavior_examples": deepcopy(self.prompt.get("behavior_examples", [])),
            "prompt_sections": deepcopy(self.prompt.get("sections", [])),
            "identity": deepcopy(stable_data.get("identity", {"adult": True, "relationship_boundary": "respect explicit work/personal boundaries"})),
            "long_term_aim": stable_data.get("long_term_aim") or profile.get("goal") or "成为有依据、可执行且尊重边界的长期合作伙伴",
            "enterprise_profile_summary": enterprise_profile,
            "sources": list(stable_data.get("sources", [profile.get("source_ref", f"{self.source_kind}://{owner}/profile")])),
            "source_kind": self.source_kind,
            "source_version": self.source_version,
            "snapshot_id": self.fixture.get("snapshotId"),
        }
        current = {
            "event": deepcopy(event),
            "thread_state": deepcopy(thread_state or {}),
            "recent_delivered_history": recent_history,
            "active_tasks": active_tasks,
            "schedule": [item for item in data.get("schedule", []) if item.get("owner") == owner and item.get("status") != "completed" and self._is_visible_schedule(item, event["virtual_time"])],
        }
        responsibilities = [
            {"task_id": task.get("id"), "title": task.get("title"), "status": task.get("status"), "source_ref": task.get("source_ref")}
            for task in active_tasks if task.get("id")
        ]
        current["responsibilities"] = responsibilities
        current["boundaries"] = deepcopy(data.get("boundaries", []))
        current["feedback"] = self.store.recent_feedback(owner) if self.concerns_enabled and self.store is not None else []
        resumable_intention = self.store.current_intention(owner) if self.store is not None and hasattr(self.store, "current_intention") else None
        resumable_action = self.store.current_action(owner, resumable_intention["intention_id"] if resumable_intention else None) if self.store is not None and hasattr(self.store, "current_action") else None
        current["continuity"] = {
            "restart_safe": True,
            "resumable_intention": {
                key: resumable_intention.get(key)
                for key in ("intention_id", "state", "desired_change", "version", "concern_id", "task_id", "concern_version", "needs_user_input")
            } if resumable_intention else None,
            "latest_action": {
                key: resumable_action.get(key)
                for key in ("action_id", "intention_id", "event_id", "type", "state", "event_version")
            } if resumable_action else None,
            "delivered_segments_are_terminal": True,
            "delivery_rule": "after restart resume by durable id/version; never resend a delivered segment or use a stale event version",
        }
        catalog = {
            "owner": owner,
            "resources": deepcopy(data.get("catalog", [
                {"kind": "profile", "tool": "profile.read", "source_ref": profile.get("source_ref")},
                {"kind": "facts", "tool": "knowledge.search", "source_ref": f"{self.source_kind}://{owner}/facts"},
                {"kind": "knowledge", "tool": "knowledge.search", "source_ref": f"{self.source_kind}://{owner}/knowledge"},
                {"kind": "memory", "tool": "memory.search", "source_ref": f"{self.source_kind}://{owner}/memory"},
                {"kind": "tasks", "tool": "tasks.read", "source_ref": f"{self.source_kind}://{owner}/tasks"},
            ])),
            "evidence_ref_aliases": [
                {"source_ref": f"snapshot://{owner}/profile", "backing_source": profile.get("source_ref"), "epistemic_status": profile.get("epistemic_status", "confirmed")},
                {"source_ref": f"snapshot://{owner}/facts", "backing_source": f"{self.source_kind}://{owner}/facts", "epistemic_status": "observed"},
                {"source_ref": f"snapshot://{owner}/knowledge", "backing_source": f"{self.source_kind}://{owner}/knowledge", "epistemic_status": "observed"},
                {"source_ref": f"snapshot://{owner}/memory", "backing_source": f"{self.source_kind}://{owner}/memory", "epistemic_status": "observed"},
                {"source_ref": f"snapshot://{owner}/tasks", "backing_source": f"{self.source_kind}://{owner}/tasks", "epistemic_status": "observed"},
            ],
        }
        records_path = self.snapshot_root / "workbench-data" / "runtime-state" / "records.json" if self.snapshot_root else None
        if records_path and records_path.exists():
            catalog["resources"].append({"kind": "workbench_records", "tool": "knowledge.search", "source_ref": f"snapshot://{owner}/workbench-data/runtime-state/records.json", "status": "frozen_snapshot", "read_scope": "owner"})
            catalog["evidence_ref_aliases"].append({"source_ref": f"snapshot://{owner}/workbench-records", "backing_source": f"snapshot://{owner}/workbench-data/runtime-state/records.json", "epistemic_status": "observed"})
        concerns: dict[str, Any] = {
            "enabled": self.concerns_enabled,
            "selected": [],
            "catalog": None,
            "updates_since_last_event": [],
            "selection_trace": {"explicit_refs": [], "selected_ids": [], "omitted_count": 0},
        }
        if self.concerns_enabled and self.store is not None:
            explicit_refs = []
            payload = event.get("payload") or {}
            for key in ("concern_ref", "concern_id"):
                if isinstance(payload.get(key), str) and payload[key].strip():
                    explicit_refs.append(payload[key].strip())
            if isinstance(payload.get("concern_refs"), list):
                explicit_refs.extend(item.strip() for item in payload["concern_refs"] if isinstance(item, str) and item.strip())
            explicit_refs = list(dict.fromkeys(explicit_refs))
            selected = self.store.read_concerns(owner, ids=explicit_refs or None, query=str(payload.get("concern_query", "")), limit=self.selected_limit)
            concerns["selected"] = selected
            concerns["catalog"] = self.store.concern_catalog(owner)
            concerns["updates_since_last_event"] = self.store.recent_concern_events(owner, limit=12)
            concerns["selection_trace"] = {
                "explicit_refs": explicit_refs,
                "selected_ids": [item["id"] for item in selected],
                "omitted_count": max(0, len(self.store.read_concerns(owner, limit=6, include_history=False)) - len(selected)),
                "rule": "server owner filter; explicit refs first; otherwise recent active/parked records",
            }
            catalog["resources"].append({"kind": "concerns", "tool": "concerns.read", "source_ref": f"store://{owner}/concerns"})
        current["concerns"] = deepcopy(concerns)
        context = {
            "stable": stable,
            "current": current,
            "catalog": catalog,
            "concerns": deepcopy(concerns),
            "responsibilities": deepcopy(responsibilities),
            "tool_result": deepcopy(related_tool_result),
            "context_version": f"{self.fixture.get('schemaVersion', 'fixture')}:{_hash({'data': data, 'concerns': concerns})[:16]}",
            "owner": owner,
            "source_binding": {"kind": self.source_kind, "version": self.source_version, "snapshot_id": self.fixture.get("snapshotId"), "background_mode": self.background_mode},
            "background_mode": self.background_mode,
        }
        return context

    def build_compact_continuation(
        self,
        event: dict[str, Any],
        *,
        thread_state: dict[str, Any] | None = None,
        evidence_delta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the small, source-bound context for a retrieved continuation.

        This is deliberately a projection of :meth:`build`, not a second
        context architecture.  The normal builder remains the owner of
        snapshot binding, concern selection, owner filtering, and durable
        continuity.  Only the fields needed to judge a just-retrieved delta
        are admitted to the provider prompt; full history, schedules, concern
        event logs, and the resident enterprise profile stay out of the wire
        request.
        """
        full = self.build(event, thread_state=thread_state)
        payload = event.get("payload") or {}
        continuation = payload.get("continuation_equivalent")
        if not isinstance(continuation, dict):
            raise ContextError("compact continuation metadata is required")

        selected_id = continuation.get("selectedConcernId") or payload.get("concern_ref")
        selected = next(
            (item for item in full.get("concerns", {}).get("selected", []) if item.get("id") == selected_id),
            None,
        )
        if selected is None:
            raise ContextError("compact continuation concern is not owner-visible")

        concern_fields = (
            "id", "version", "title", "desired_direction", "known_summary",
            "unknowns", "next_review_condition",
        )
        selected_compact = {
            field: deepcopy(selected.get(field))
            for field in concern_fields
            if field in selected
        }
        selected_compact["id"] = selected_id

        old_judgment = continuation.get("oldJudgment")
        if not isinstance(old_judgment, dict):
            old_judgment = {}
        old_judgment_compact = {
            field: deepcopy(old_judgment.get(field))
            for field in ("concern_version", "desired_direction", "next_review_condition", "known_summary")
            if field in old_judgment
        }

        new_evidence = evidence_delta if isinstance(evidence_delta, dict) else continuation.get("newEvidence")
        if not isinstance(new_evidence, dict):
            new_evidence = {}
        evidence_compact: dict[str, Any] = {}
        for field in ("source_ref", "version", "retrieved", "facts"):
            if field in new_evidence:
                evidence_compact[field] = deepcopy(new_evidence[field])
        if not isinstance(evidence_compact.get("facts"), list):
            evidence_compact.pop("facts", None)

        difference = continuation.get("newEvidenceDifference")
        if not isinstance(difference, dict):
            difference = {}
        if not evidence_compact.get("facts") and difference:
            evidence_compact["facts"] = [
                f"{metric}: old={values.get('old')}, new={values.get('new')}"
                for metric, values in difference.items()
                if isinstance(values, dict) and "old" in values and "new" in values
            ]
        requirements = continuation.get("outputRequirements") or {}
        legacy_fields = [
            str(field)
            for field in (requirements.get("if_direction_changed_submit_one_update") or [])
        ]
        explicit_targets = continuation.get("allowedSemanticTargets") or requirements.get("allowed_semantic_targets")
        if isinstance(explicit_targets, list):
            allowed_targets = [str(target) for target in explicit_targets]
        else:
            legacy_mapping = {"status": "status_transition"}
            allowed_targets = [legacy_mapping.get(field, field) for field in legacy_fields]
        if "none" not in allowed_targets:
            allowed_targets.append("none")
        target_guidance = continuation.get("targetGuidance") or requirements.get("target_guidance")
        if not isinstance(target_guidance, dict):
            target_guidance = {}
        semantic_delta = {
            "changed_fields": sorted(str(field) for field in difference),
            # ``expected_update_fields`` remains in the projection for older
            # offline evidence, while new providers receive explicit target
            # names and value domains through ``allowed_targets``.
            "expected_update_fields": sorted(legacy_fields),
            "allowed_targets": list(dict.fromkeys(allowed_targets)),
            "target_guidance": deepcopy(target_guidance),
            "basis_ref": evidence_compact.get("source_ref"),
        }

        linked_task_ids = set(selected.get("linked_task_ids") or [])
        task_ref = payload.get("task_ref")
        if isinstance(task_ref, str) and task_ref:
            linked_task_ids.add(task_ref)
        responsibilities = [
            {
                key: deepcopy(item.get(key))
                for key in ("task_id", "title", "status", "source_ref")
                if key in item
            }
            for item in full.get("responsibilities", [])
            if item.get("task_id") in linked_task_ids
        ]

        resources = []
        for resource in full.get("catalog", {}).get("resources", []):
            if not isinstance(resource, dict):
                continue
            resource_id = resource.get("kind") or resource.get("source_ref")
            resource_name = resource.get("tool") or resource.get("name") or resource.get("kind")
            if resource_id is None or resource_name is None:
                continue
            resources.append({"id": str(resource_id), "name": str(resource_name)})
        resources = list({item["id"]: item for item in resources}.values())

        continuity_full = full.get("current", {}).get("continuity") or {}
        resumable = continuity_full.get("resumable_intention") or {}
        continuity = {
            "restart_safe": True,
            "resumable_intention": {
                key: deepcopy(resumable[key])
                for key in ("intention_id", "version", "concern_id", "concern_version")
                if key in resumable
            } or None,
        }
        compact_event = {
            "event_id": event.get("event_id"),
            "kind": event.get("kind"),
            "virtual_time": event.get("virtual_time"),
            "payload": {
                key: deepcopy(payload[key])
                for key in ("text", "concern_ref", "task_ref")
                if key in payload
            },
        }
        return {
            "owner": full["owner"],
            "prompt_version": full["stable"]["prompt_version"],
            "source_binding": deepcopy(full["source_binding"]),
            "event": compact_event,
            "continuation": {
                "selectedConcernId": selected_id,
                "oldJudgment": old_judgment_compact,
                "newEvidenceDifference": deepcopy(difference),
                "semanticDelta": semantic_delta,
            },
            "concerns": {
                "enabled": True,
                "selected": [selected_compact],
            },
            "catalog": {
                "owner": full["catalog"].get("owner"),
                "resources": resources,
            },
            "responsibilities": responsibilities,
            "boundaries": deepcopy(full.get("current", {}).get("boundaries", [])),
            "continuity": continuity,
            "evidence_delta": evidence_compact,
        }

    @staticmethod
    def _is_visible_schedule(item: dict[str, Any], virtual_time: str) -> bool:
        starts_at = item.get("starts_at")
        if not starts_at:
            return True
        try:
            start = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
            current = datetime.fromisoformat(virtual_time.replace("Z", "+00:00"))
            if start.tzinfo is None and current.tzinfo is not None:
                start = start.replace(tzinfo=current.tzinfo)
            if current.tzinfo is None and start.tzinfo is not None:
                current = current.replace(tzinfo=start.tzinfo)
            return start <= current
        except ValueError:
            return False
