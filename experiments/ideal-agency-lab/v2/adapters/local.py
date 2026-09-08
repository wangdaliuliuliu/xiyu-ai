"""Scoped tools over the frozen public replica/fixture."""
from __future__ import annotations

import hashlib
import json
import pathlib
import uuid
from copy import deepcopy
from typing import Any

from contracts.schemas import validate_tool_result


class AdapterError(RuntimeError):
    pass


class LocalAdapters:
    def __init__(self, fixture_path: pathlib.Path, *, mode: str = "FROZEN"):
        self.fixture_path = fixture_path
        self.mode = mode
        self.fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    def _data(self, owner: str) -> dict[str, Any]:
        try:
            return self.fixture["owners"][owner]
        except KeyError as exc:
            raise AdapterError("forbidden") from exc

    def _result(self, status: str, data: Any, source_refs: list[str], scope: str, version: str, completeness: str = "complete") -> dict[str, Any]:
        return validate_tool_result({"status": status, "data": data, "source_refs": source_refs, "scope": scope, "version": version, "trace_id": str(uuid.uuid4()), "completeness": completeness})

    def execute(self, owner: str, action_type: str, args: dict[str, Any]) -> dict[str, Any]:
        requested_owner = args.get("owner")
        if requested_owner not in (None, owner):
            raise AdapterError("forbidden:owner_scope")
        data = self._data(owner)
        if action_type == "catalog":
            return self._result("complete", {"resources": ["profile", "daily_sales", "knowledge", "memory", "tasks"]}, [f"fixture://{owner}/catalog"], owner, self.fixture.get("schemaVersion", "fixture"))
        if action_type == "profile.read":
            return self._result("complete", deepcopy(data.get("profile", {})), [data["profile"]["source_ref"]], owner, "profile-v1")
        if action_type in {"knowledge.search", "knowledge.read", "research"}:
            return self._search(owner, data.get("facts", []) + data.get("knowledge", []), args, "knowledge")
        if action_type == "memory.search":
            term = str(args.get("query", "")).lower()
            rows = [row for row in data.get("memories", []) if not term or term in json.dumps(row, ensure_ascii=False).lower()]
            return self._result("complete", rows, [row["source_ref"] for row in rows], owner, "memory-v1")
        if action_type == "tasks.read":
            rows = [row for row in data.get("tasks", []) if not args.get("status") or row.get("status") == args["status"]]
            return self._result("complete", rows, [row["source_ref"] for row in rows], owner, "task-v1")
        if action_type == "tasks.update":
            task_id = args.get("task_id")
            if not task_id:
                return self._result("failed", {}, [], owner, "task-v1")
            rows = [row for row in data.get("tasks", []) if row.get("id") == task_id]
            if not rows:
                return self._result("not_found", {}, [], owner, "task-v1")
            return self._result("complete", {"task_id": task_id, "updated": True, "isolated": True}, [rows[0]["source_ref"]], owner, "task-v1")
        if action_type == "knowledge.propose":
            return self._result("complete", {"status": "candidate", "candidate": args.get("candidate"), "confirmed": False}, [f"fixture://{owner}/knowledge/candidate"], owner, "knowledge-v1")
        if action_type == "knowledge.confirm":
            if args.get("authorized") is not True:
                return self._result("forbidden", {}, [f"fixture://{owner}/knowledge"], owner, "knowledge-v1")
            return self._result("complete", {"status": "confirmed", "candidate_id": args.get("candidate_id")}, [f"fixture://{owner}/knowledge"], owner, "knowledge-v1")
        if action_type == "media.prepare":
            return self._media_prepare(owner, args)
        raise AdapterError(f"unavailable:{action_type}")

    def _search(self, owner: str, rows: list[dict[str, Any]], args: dict[str, Any], kind: str) -> dict[str, Any]:
        requested_store = args.get("store_name")
        requested_date = args.get("business_date")
        requested_metric = args.get("metric")
        if requested_store is None and requested_date is None and requested_metric is None and not args.get("query"):
            return self._result("failed", {}, [], owner, "source-v1", "partial")
        matched = []
        query = str(args.get("query", "")).lower()
        for row in rows:
            if requested_store is not None and row.get("store") != requested_store:
                continue
            if requested_date is not None and row.get("business_date") != requested_date:
                continue
            if requested_metric is not None and row.get("metric") != requested_metric:
                continue
            if query and query not in json.dumps(row, ensure_ascii=False).lower():
                continue
            matched.append(deepcopy(row))
        if not matched:
            return self._result("not_found", [], [f"fixture://{owner}/search"], owner, "source-v1")
        return self._result("complete", matched, sorted({row["source_ref"] for row in matched}), owner, "source-v1")

    def _media_prepare(self, owner: str, args: dict[str, Any]) -> dict[str, Any]:
        asset_path = args.get("asset_path")
        if not asset_path:
            return self._result("failed", {"reason": "asset_path_required"}, [], owner, "media-v1")
        path = pathlib.Path(asset_path)
        if not path.exists() or not path.is_file():
            return self._result("failed", {"reason": "asset_missing", "asset_path": str(path)}, [f"fixture://{owner}/media"], owner, "media-v1")
        return self._result("complete", {"asset_path": str(path), "asset_hash": hashlib.sha256(path.read_bytes()).hexdigest(), "planner_id": str(uuid.uuid4())}, [f"fixture://{owner}/media"], owner, "media-v1")
