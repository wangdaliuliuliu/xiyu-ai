"""Scoped tools over the frozen public replica/fixture."""
from __future__ import annotations

import hashlib
import json
import pathlib
import uuid
from copy import deepcopy
from typing import Any

from contracts.schemas import validate_tool_result
from runtime.store import EventStore, StoreError


class AdapterError(RuntimeError):
    pass


class LocalAdapters:
    def __init__(self, fixture_path: pathlib.Path | None = None, *, mode: str = "FROZEN",
                 snapshot_root: pathlib.Path | None = None, manifest_path: pathlib.Path | None = None,
                 store: EventStore | None = None, image_gateway: Any | None = None,
                 image_available: bool | None = None, concerns_enabled: bool = False):
        if fixture_path is not None and snapshot_root is not None:
            raise AdapterError("adapter source is ambiguous")
        source_path = (snapshot_root / "context.json") if snapshot_root else fixture_path
        if source_path is None:
            raise AdapterError("adapter source is required")
        self.fixture_path = fixture_path
        self.snapshot_root = snapshot_root.resolve() if snapshot_root else None
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path and manifest_path.exists() else None
        self.mode = mode
        self.fixture = json.loads(source_path.read_text(encoding="utf-8"))
        self.records_path = (self.snapshot_root / "workbench-data" / "runtime-state" / "records.json") if self.snapshot_root else None
        self.records_payload = None
        if self.records_path and self.records_path.exists():
            self.records_payload = json.loads(self.records_path.read_text(encoding="utf-8"))
        self.store = store
        self.image_gateway = image_gateway
        self.image_available = image_available
        self.concerns_enabled = bool(concerns_enabled)
        self.source_kind = "snapshot" if self.snapshot_root else "fixture"
        self.source_version = self.fixture.get("sourceVersion") or self.fixture.get("schemaVersion", "fixture")
        if self.snapshot_root and self.mode == "FROZEN":
            binding = (self.manifest or {}).get("snapshot_binding", {})
            if binding.get("snapshot_id") != self.fixture.get("snapshotId"):
                raise AdapterError("frozen snapshot binding mismatch")

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
        if self.store:
            self.store.seed_tasks(owner, data.get("tasks", []))
        if action_type == "catalog":
            catalog = deepcopy(data.get("catalog", []))
            if not catalog:
                catalog = [{"kind": "profile", "tool": "profile.read", "source_ref": f"{self.source_kind}://{owner}/profile"},
                           {"kind": "facts", "tool": "knowledge.search", "source_ref": f"{self.source_kind}://{owner}/facts"},
                           {"kind": "knowledge", "tool": "knowledge.search", "source_ref": f"{self.source_kind}://{owner}/knowledge"},
                           {"kind": "memory", "tool": "memory.search", "source_ref": f"{self.source_kind}://{owner}/memory"},
                           {"kind": "tasks", "tool": "tasks.read", "source_ref": f"{self.source_kind}://{owner}/tasks"},
                           {"kind": "research", "tool": "research", "source_ref": f"{self.source_kind}://{owner}/research"},
                           {"kind": "media", "tool": "media.prepare", "source_ref": f"{self.source_kind}://{owner}/media"}]
            if self.records_payload is not None:
                catalog.append({"kind": "workbench_records", "tool": "knowledge.search", "source_ref": f"snapshot://{owner}/workbench-data/runtime-state/records.json", "status": "frozen_snapshot", "read_scope": "owner"})
            return self._result("complete", {"resources": catalog}, [f"{self.source_kind}://{owner}/catalog"], owner, self.fixture.get("schemaVersion", "fixture"))
        if action_type == "concerns.read":
            if not self.concerns_enabled or self.store is None:
                return self._result("forbidden", {"reason": "concerns_arm_disabled"}, [f"store://{owner}/concerns"], owner, "concerns-v1", "none")
            ids = args.get("ids")
            if ids is not None and not isinstance(ids, list):
                return self._result("failed", {"reason": "ids_must_be_a_list"}, [], owner, "concerns-v1", "none")
            query = args.get("query", "")
            if not isinstance(query, str):
                return self._result("failed", {"reason": "query_must_be_a_string"}, [], owner, "concerns-v1", "none")
            try:
                rows = self.store.read_concerns(owner, ids=ids, query=query, limit=int(args.get("limit", 6)))
            except (StoreError, ValueError) as exc:
                return self._result("failed", {"reason": str(exc)}, [f"store://{owner}/concerns"], owner, "concerns-v1", "none")
            return self._result("complete", rows, [f"store://{owner}/concerns"], owner, "concerns-v1")
        if action_type == "profile.read":
            return self._result("complete", deepcopy(data.get("profile", {})), [data["profile"]["source_ref"]], owner, "profile-v1")
        if action_type == "research":
            archive = data.get("research_archive", [])
            if not archive:
                return self._result("unavailable", {"reason": "frozen_research_archive_missing"}, [f"{self.source_kind}://{owner}/research"], owner, "research-v1", "none")
            return self._search(owner, archive, args, "research")
        if action_type in {"knowledge.search", "knowledge.read"}:
            return self._search(owner, data.get("facts", []) + data.get("knowledge", []) + self._workbench_rows(), args, "knowledge")
        if action_type == "memory.search":
            term = str(args.get("query", "")).lower()
            rows = [row for row in data.get("memories", []) if not term or term in json.dumps(row, ensure_ascii=False).lower()]
            return self._result("complete", rows, [row["source_ref"] for row in rows], owner, "memory-v1")
        if action_type == "tasks.read":
            rows = self.store.read_tasks(owner, args.get("status")) if self.store else [row for row in data.get("tasks", []) if not args.get("status") or row.get("status") == args["status"]]
            return self._result("complete", rows, [row.get("source_ref", f"{self.source_kind}://{owner}/tasks") for row in rows], owner, "task-v2")
        if action_type == "tasks.update":
            task_id = args.get("task_id")
            if not task_id:
                return self._result("failed", {}, [], owner, "task-v1")
            if self.store:
                try:
                    with self.store.transaction():
                        updated = self.store.update_task(owner, str(task_id), state=str(args.get("status", args.get("state", "completed"))), expected_version=args.get("expected_version"), idempotency_key=args.get("idempotency_key"))
                except StoreError as exc:
                    status = "not_found" if str(exc) == "task_not_found" else "conflict"
                    return self._result(status, {"reason": str(exc)}, [], owner, "task-v2")
                return self._result("complete", {"task_id": task_id, "updated": not bool(updated.get("idempotent_replay")), "idempotent_replay": bool(updated.get("idempotent_replay")), "isolated": True, "task": updated}, [updated.get("source_ref", f"{self.source_kind}://{owner}/tasks")], owner, "task-v2")
            rows = [row for row in data.get("tasks", []) if row.get("id") == task_id]
            if not rows:
                return self._result("not_found", {}, [], owner, "task-v1")
            return self._result("complete", {"task_id": task_id, "updated": True, "isolated": True}, [rows[0]["source_ref"]], owner, "task-v1")
        if action_type == "knowledge.propose":
            source_ref = f"{self.source_kind}://{owner}/knowledge/candidate"
            if self.store:
                with self.store.transaction():
                    candidate = self.store.create_candidate(owner, {"value": args.get("candidate"), "scope": args.get("scope", owner)}, source_ref)
                return self._result("complete", candidate, [source_ref], owner, "knowledge-v2")
            return self._result("complete", {"status": "candidate", "candidate": args.get("candidate"), "confirmed": False}, [source_ref], owner, "knowledge-v1")
        if action_type == "knowledge.confirm":
            source_ref = f"{self.source_kind}://{owner}/knowledge"
            if self.store:
                try:
                    with self.store.transaction():
                        confirmed = self.store.confirm_candidate(owner, str(args.get("candidate_id", "")))
                except StoreError as exc:
                    status = "not_found" if str(exc) == "candidate_not_found" else "forbidden"
                    return self._result(status, {"reason": str(exc)}, [source_ref], owner, "knowledge-v2")
                return self._result("complete", confirmed, [source_ref], owner, "knowledge-v2")
            # A fixture-only deterministic adapter has no trusted user event;
            # the legacy path intentionally remains forbidden even if the model
            # supplies an ``authorized`` argument.
            return self._result("forbidden", {"reason": "trusted_user_confirmation_required"}, [source_ref], owner, "knowledge-v2")
        if action_type == "media.prepare":
            return self._media_prepare(owner, args)
        raise AdapterError(f"unavailable:{action_type}")

    def _workbench_rows(self) -> list[dict[str, Any]]:
        """Expose only normalized rows derived from the isolated workbench snapshot.

        This reuses the existing knowledge.search contract.  It does not add a
        new gateway or inject rows into the prompt; the worker must still
        choose a read action and the returned rows retain their source refs.
        """
        if not isinstance(self.records_payload, dict):
            return []
        rows: list[dict[str, Any]] = []
        for record in self.records_payload.get("data", []):
            if not isinstance(record, dict):
                continue
            venue = str(record.get("venue", ""))
            period = record.get("periodStart")
            period_end = record.get("periodEnd")
            source_revision = record.get("sourceRevision")
            source_ref = None
            for source in record.get("sourceRefs", []):
                if isinstance(source, dict) and source.get("sourceRef"):
                    source_ref = str(source["sourceRef"])
                    break
                if isinstance(source, dict) and source.get("spreadsheetToken") and source.get("revision") is not None:
                    sheet = source.get("sheet") or "workbench"
                    source_ref = f"feishu://{source['spreadsheetToken']}/revision/{source['revision']}/{sheet}"
                    break
            source_ref = source_ref or f"snapshot://workbench-record/{record.get('id', 'unknown')}"
            base = {
                "record_id": record.get("id"),
                "store": venue,
                "store_name": f"{venue}店" if venue and not venue.endswith("店") else venue,
                "period_start": period,
                "period_end": period_end,
                "source_revision": source_revision,
                "source_ref": source_ref,
                "record_status": record.get("status"),
                "notes": record.get("notes"),
            }
            metric_labels = {
                "target_amount": ["目标", "目标金额"],
                "platform_settlement": ["平台结算", "结算"],
                "box_office_total": ["票房"],
                "sales_order_count": ["销售订单", "订单数", "订单"],
                "reception_traffic": ["接待客流", "经营客流", "客流"],
                "online_sales_amount": ["线上销售", "线上销售额"],
                "offline_sales_amount": ["线下销售", "线下销售额"],
            }
            for metric, value in (record.get("core") or {}).items():
                rows.append({**base, "metric": metric, "metric_labels": metric_labels.get(metric, [metric]), "value": value})
            for daily in record.get("daily", []):
                if not isinstance(daily, dict):
                    continue
                day_base = {**base, "business_date": daily.get("date")}
                if "traffic" in daily:
                    rows.append({**day_base, "metric": "traffic", "metric_labels": ["日客流", "客流"], "value": daily.get("traffic")})
                if "boxOffice" in daily:
                    rows.append({**day_base, "metric": "box_office", "metric_labels": ["日票房", "票房"], "value": daily.get("boxOffice")})
        return rows

    def _search(self, owner: str, rows: list[dict[str, Any]], args: dict[str, Any], kind: str) -> dict[str, Any]:
        requested_store = args.get("store_name")
        requested_date = args.get("business_date")
        requested_metric = args.get("metric")
        if requested_store is None and requested_date is None and requested_metric is None and not args.get("query"):
            return self._result("failed", {}, [], owner, "source-v1", "partial")
        matched = []
        query = str(args.get("query", "")).lower()
        snapshot_metric_query = any(
            str(label).lower() in query
            for row in rows
            for label in (row.get("metric_labels") or [])
        ) if query else False
        for row in rows:
            if requested_store is not None and row.get("store") != requested_store:
                continue
            if requested_date is not None and row.get("business_date") != requested_date:
                continue
            if requested_metric is not None:
                metric_tokens = {str(row.get("metric", "")).lower(), *(str(label).lower() for label in (row.get("metric_labels") or []))}
                if str(requested_metric).lower() not in metric_tokens:
                    continue
            if query:
                row_text = json.dumps(row, ensure_ascii=False).lower()
                if row.get("metric_labels"):
                    metric_hit = any(str(label).lower() in query for label in row["metric_labels"])
                    identity_hit = any(str(term).lower() in query for term in (row.get("store"), row.get("store_name"), row.get("business_date"), row.get("period_start")))
                    if snapshot_metric_query and not (metric_hit and identity_hit):
                        continue
                    if not snapshot_metric_query and not identity_hit:
                        continue
                elif query not in row_text:
                    continue
            matched.append(deepcopy(row))
        if self.store and kind == "knowledge":
            # Static snapshot knowledge and confirmed isolated increments are
            # queried together; candidates are deliberately excluded from the
            # formal knowledge result until a trusted confirmation event exists.
            matched.extend(self.store.search_knowledge(owner, query))
        if not matched:
            return self._result("not_found", [], [f"{self.source_kind}://{owner}/search"], owner, "source-v1")
        source_refs = sorted({row["source_ref"] for row in matched if isinstance(row.get("source_ref"), str)})
        versions = sorted({str(row.get("source_revision") or row.get("version")) for row in matched if row.get("source_revision") is not None or row.get("version") is not None})
        if len(versions) == 1:
            result_version = versions[0]
        elif versions:
            result_version = "mixed:" + hashlib.sha256("|".join(versions).encode("utf-8")).hexdigest()[:16]
        else:
            result_version = "source-v1"
        return self._result("complete", matched, source_refs, owner, result_version)

    def _media_prepare(self, owner: str, args: dict[str, Any]) -> dict[str, Any]:
        asset_path = args.get("asset_path")
        if not asset_path:
            generation_prompt = args.get("prompt") or args.get("generation_prompt")
            if generation_prompt and self.image_gateway is not None:
                if self.image_available is False:
                    return self._result("unavailable", {"reason": "asset_condition_unavailable"}, [f"gateway://{owner}/media"], owner, "media-v2", "none")
                response = self.image_gateway.generate(
                    str(generation_prompt),
                    references=[str(item) for item in (args.get("references") or [])],
                )
                if response.error:
                    return self._result("unavailable", {"reason": response.error, "provider_request_id": response.request_id, "raw_response_ref": response.raw_response_ref}, [f"gateway://{owner}/media"], owner, "media-v2", "none")
                return self._result("complete", {
                    "asset_path": response.asset_path,
                    "asset_hash": response.asset_sha256,
                    "planner_id": str(uuid.uuid4()),
                    "provider_request_id": response.request_id,
                    "provider_model": response.model,
                    "raw_response_ref": response.raw_response_ref,
                }, [f"gateway://{owner}/media"], owner, "media-v2")
            return self._result("unavailable", {"reason": "image_provider_or_generation_prompt_missing"}, [], owner, "media-v2", "none")
        path = pathlib.Path(asset_path)
        if not path.exists() or not path.is_file():
            return self._result("failed", {"reason": "asset_missing", "asset_path": str(path)}, [f"fixture://{owner}/media"], owner, "media-v1")
        return self._result("complete", {"asset_path": str(path), "asset_hash": hashlib.sha256(path.read_bytes()).hexdigest(), "planner_id": str(uuid.uuid4())}, [f"fixture://{owner}/media"], owner, "media-v1")
