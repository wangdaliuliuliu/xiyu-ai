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
    def __init__(self, fixture_path: pathlib.Path, prompt_path: pathlib.Path | None = None):
        self.fixture_path = fixture_path
        self.fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        self.prompt = json.loads(prompt_path.read_text(encoding="utf-8")) if prompt_path and prompt_path.exists() else {"promptVersion": "missing", "rules": []}

    def owner_data(self, owner: str) -> dict[str, Any]:
        data = self.fixture.get("owners", {}).get(owner)
        if not data:
            raise ContextError(f"owner not found: {owner}")
        return deepcopy(data)

    def build(self, event: dict[str, Any], *, thread_state: dict[str, Any] | None = None, related_tool_result: dict[str, Any] | None = None) -> dict[str, Any]:
        owner = event["owner"]
        data = self.owner_data(owner)
        history = [item for item in data.get("history", []) if item.get("owner") == owner]
        stable = {
            "prompt_version": self.prompt.get("promptVersion", "missing"),
            "prompt_rules": self.prompt.get("rules", []),
            "identity": {"adult": True, "relationship_boundary": "respect explicit work/personal boundaries"},
            "long_term_aim": "成为有依据、可执行且尊重边界的长期合作伙伴",
            "enterprise_profile_summary": data.get("profile", {}),
            "sources": [data.get("profile", {}).get("source_ref", f"fixture://{owner}/profile")],
        }
        current = {
            "event": deepcopy(event),
            "thread_state": deepcopy(thread_state or {}),
            "recent_delivered_history": history,
            "active_tasks": [task for task in data.get("tasks", []) if task.get("owner") == owner],
            "schedule": [item for item in data.get("schedule", []) if item.get("owner") == owner and item.get("status") != "completed" and self._is_visible_schedule(item, event["virtual_time"])],
        }
        catalog = {
            "owner": owner,
            "resources": [
                {"kind": "profile", "tool": "profile.read", "source_ref": data.get("profile", {}).get("source_ref")},
                {"kind": "daily_sales", "tool": "knowledge.search", "source_ref": "fixture://" + owner + "/sales"},
                {"kind": "knowledge", "tool": "knowledge.search", "source_ref": "fixture://" + owner + "/knowledge"},
                {"kind": "memory", "tool": "memory.search", "source_ref": "fixture://" + owner + "/memory"},
                {"kind": "tasks", "tool": "tasks.read", "source_ref": "fixture://" + owner + "/tasks"},
            ],
        }
        context = {
            "stable": stable,
            "current": current,
            "catalog": catalog,
            "tool_result": deepcopy(related_tool_result),
            "context_version": f"{self.fixture.get('schemaVersion', 'fixture')}:{_hash(data)[:16]}",
            "owner": owner,
        }
        return context

    @staticmethod
    def _is_visible_schedule(item: dict[str, Any], virtual_time: str) -> bool:
        starts_at = item.get("starts_at")
        if not starts_at:
            return True
        try:
            return datetime.fromisoformat(starts_at) <= datetime.fromisoformat(virtual_time)
        except ValueError:
            return False
