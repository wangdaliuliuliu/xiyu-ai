"""Deterministic hard gates: permissions, versions, timing, budget, idempotency."""
from __future__ import annotations

import datetime as dt
import pathlib
from typing import Any

from contracts.schemas import ContractError
from runtime.store import EventStore, StoreError


class PolicyError(RuntimeError):
    pass


class Policy:
    def __init__(self, store: EventStore, *, allowed_tools: set[str] | None = None, delivery_enabled: bool = True, writable_root: pathlib.Path | None = None, concerns_enabled: bool = False, max_concern_patches: int = 3):
        self.store = store
        self.concerns_enabled = bool(concerns_enabled)
        self.max_concern_patches = max_concern_patches
        self.allowed_tools = allowed_tools or {"catalog", "profile.read", "knowledge.search", "knowledge.read", "memory.search", "tasks.read", "tasks.update", "knowledge.propose", "knowledge.confirm", "research", "media.prepare"}
        if self.concerns_enabled:
            self.allowed_tools = set(self.allowed_tools) | {"concerns.read"}
        self.delivery_enabled = delivery_enabled
        self.writable_root = writable_root.resolve() if writable_root else None

    def check_action(self, owner: str, event: dict[str, Any], action: dict[str, Any], *, thread_version: int) -> None:
        action_type = action["type"]
        if action_type not in {"none", "deliver", "wait"} and action_type not in self.allowed_tools:
            raise PolicyError(f"capability_unavailable:{action_type}")
        if action_type == "deliver" and not self.delivery_enabled:
            raise PolicyError("delivery_disabled")
        expected_version = action.get("event_version", thread_version)
        if expected_version != thread_version:
            raise PolicyError("version_conflict")
        if action_type == "media.prepare":
            asset_path = action.get("args", {}).get("asset_path")
            if self.writable_root and asset_path and not self._inside(pathlib.Path(asset_path), self.writable_root):
                raise PolicyError("media_path_outside_worker")
        if action_type in {"knowledge.confirm", "tasks.update"} and action.get("args", {}).get("owner") not in (None, owner):
            raise PolicyError("owner_scope_violation")

    @staticmethod
    def _inside(path: pathlib.Path, root: pathlib.Path) -> bool:
        try:
            path.resolve().relative_to(root)
            return True
        except ValueError:
            return False

    def can_deliver_current(self, owner: str, event_version: int, current_version: int) -> None:
        if event_version != current_version:
            raise PolicyError("version_conflict_before_delivery")
        if not self.delivery_enabled:
            raise PolicyError("delivery_disabled")

    def consume(self, owner: str, kind: str) -> None:
        ok, budget = self.store.consume_budget(owner, kind)
        if not ok:
            raise PolicyError(f"budget_exhausted:{kind}:{budget}")

    def validate_wait(self, reconsider_condition: str) -> None:
        if not reconsider_condition.strip():
            raise ContractError("wait requires reconsider_condition")

    def check_concern_updates(self, updates: list[dict[str, Any]]) -> None:
        if not self.concerns_enabled and updates:
            raise PolicyError("concerns_arm_disabled")
        if len(updates) > self.max_concern_patches:
            raise PolicyError("concern_patch_limit_exceeded")
