"""The one durable state store for a trajectory."""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import pathlib
import sqlite3
import uuid
from typing import Any, Iterator


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


class StoreError(RuntimeError):
    pass


class EventStore:
    def __init__(self, path: pathlib.Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS events(
              event_id TEXT PRIMARY KEY, owner TEXT NOT NULL, kind TEXT NOT NULL,
              virtual_time TEXT NOT NULL, payload_json TEXT NOT NULL,
              version INTEGER NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS threads(
              thread_id TEXT PRIMARY KEY, owner TEXT NOT NULL, version INTEGER NOT NULL,
              initial_state_hash TEXT NOT NULL, status TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS intentions(
              intention_id TEXT PRIMARY KEY, owner TEXT NOT NULL, thread_id TEXT NOT NULL,
              state TEXT NOT NULL, desired_change TEXT NOT NULL, version INTEGER NOT NULL,
              concern_id TEXT, task_id TEXT, concern_version INTEGER,
              needs_user_input INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              FOREIGN KEY(thread_id) REFERENCES threads(thread_id)
            );
            CREATE TABLE IF NOT EXISTS actions(
              action_id TEXT PRIMARY KEY, owner TEXT NOT NULL, intention_id TEXT NOT NULL,
              event_id TEXT NOT NULL, type TEXT NOT NULL, args_json TEXT NOT NULL,
              state TEXT NOT NULL, event_version INTEGER NOT NULL, idempotency_key TEXT,
              result_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              FOREIGN KEY(intention_id) REFERENCES intentions(intention_id)
            );
            CREATE TABLE IF NOT EXISTS tool_requests(
              request_id TEXT PRIMARY KEY, owner TEXT NOT NULL, action_id TEXT NOT NULL,
              original_args_json TEXT NOT NULL, normalized_args_json TEXT NOT NULL,
              diff_json TEXT NOT NULL, result_json TEXT, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sink_deliveries(
              segment_id TEXT PRIMARY KEY, owner TEXT NOT NULL, action_id TEXT NOT NULL,
              attempt_id TEXT NOT NULL, status TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
              receipt_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS feedback(
              feedback_id TEXT PRIMARY KEY, owner TEXT NOT NULL, action_id TEXT NOT NULL,
              source TEXT NOT NULL, strength TEXT NOT NULL, original_text TEXT,
              payload_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS leases(
              owner TEXT PRIMARY KEY, lease_id TEXT NOT NULL, expires_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS budgets(
              owner TEXT PRIMARY KEY, model_calls INTEGER NOT NULL DEFAULT 0,
              tool_rounds INTEGER NOT NULL DEFAULT 0, infra_retries INTEGER NOT NULL DEFAULT 0,
              max_model_calls INTEGER NOT NULL, max_tool_rounds INTEGER NOT NULL,
              max_infra_retries INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS traces(
              trace_id TEXT PRIMARY KEY, owner TEXT NOT NULL, event_id TEXT NOT NULL,
              step INTEGER NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS isolated_tasks(
              owner TEXT NOT NULL, task_id TEXT NOT NULL, payload_json TEXT NOT NULL,
              state TEXT NOT NULL, version INTEGER NOT NULL, source_ref TEXT,
              updated_at TEXT NOT NULL, PRIMARY KEY(owner, task_id)
            );
            CREATE TABLE IF NOT EXISTS task_updates(
              owner TEXT NOT NULL, task_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
              result_json TEXT NOT NULL, created_at TEXT NOT NULL,
              PRIMARY KEY(owner, idempotency_key)
            );
            CREATE TABLE IF NOT EXISTS knowledge_candidates(
              candidate_id TEXT PRIMARY KEY, owner TEXT NOT NULL, payload_json TEXT NOT NULL,
              status TEXT NOT NULL, source_ref TEXT NOT NULL, confirmed_by_event TEXT,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS user_confirmations(
              confirmation_id TEXT PRIMARY KEY, owner TEXT NOT NULL, candidate_id TEXT NOT NULL,
              event_id TEXT NOT NULL UNIQUE, accepted INTEGER NOT NULL, original_text TEXT,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS concerns(
              concern_id TEXT PRIMARY KEY, owner TEXT NOT NULL, version INTEGER NOT NULL,
              title TEXT NOT NULL, desired_direction TEXT NOT NULL, domain TEXT NOT NULL,
              origin TEXT NOT NULL, desire_refs_json TEXT NOT NULL, basis_refs_json TEXT NOT NULL,
              linked_task_ids_json TEXT NOT NULL, status TEXT NOT NULL, known_summary_json TEXT NOT NULL,
              unknowns_json TEXT NOT NULL, next_review_condition_json TEXT NOT NULL,
              last_progress_ref TEXT, last_contact_ref TEXT, boundary_refs_json TEXT NOT NULL,
              resolution_evidence_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              review_after TEXT
            );
            CREATE TABLE IF NOT EXISTS concern_events(
              event_record_id INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL,
              owner TEXT NOT NULL, concern_id TEXT, event_id TEXT NOT NULL, action_id TEXT,
              local_ref TEXT NOT NULL DEFAULT '', expected_version INTEGER, new_version INTEGER,
              operation TEXT NOT NULL, patch_json TEXT NOT NULL, refs_json TEXT NOT NULL,
              recorded_at TEXT NOT NULL,
              UNIQUE(owner,event_id,concern_id,local_ref,operation)
            );
            CREATE INDEX IF NOT EXISTS idx_concerns_owner_status_updated ON concerns(owner,status,updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_concern_events_owner_recorded ON concern_events(owner,recorded_at DESC);
            """
        )
        # The same store is also used to reopen trajectories created before the
        # concerns arm existed.  Additive migrations keep those trajectories
        # readable without creating a second state database.
        for column, definition in (
            ("concern_id", "TEXT"),
            ("task_id", "TEXT"),
            ("concern_version", "INTEGER"),
        ):
            if not any(row[1] == column for row in self.conn.execute("PRAGMA table_info(intentions)")):
                self.conn.execute(f"ALTER TABLE intentions ADD COLUMN {column} {definition}")

    @contextlib.contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    def close(self) -> None:
        self.conn.close()

    def has_event(self, event_id: str) -> bool:
        return self.conn.execute("SELECT 1 FROM events WHERE event_id=?", (event_id,)).fetchone() is not None

    def insert_event(self, event: dict[str, Any], version: int) -> bool:
        try:
            self.conn.execute(
                "INSERT INTO events(event_id,owner,kind,virtual_time,payload_json,version,created_at) VALUES(?,?,?,?,?,?,?)",
                (event["event_id"], event["owner"], event["kind"], event["virtual_time"], json.dumps(event["payload"], ensure_ascii=False), version, now_iso()),
            )
            return True
        except sqlite3.IntegrityError:
            return False

    def ensure_thread(self, owner: str, initial_state: dict[str, Any]) -> tuple[str, int]:
        state_hash = hashlib.sha256(json.dumps(initial_state, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        row = self.conn.execute("SELECT thread_id,version,initial_state_hash FROM threads WHERE owner=?", (owner,)).fetchone()
        if row:
            if row[2] != state_hash:
                raise StoreError("trajectory initial state changed")
            return row[0], row[1]
        thread_id = str(uuid.uuid4())
        self.conn.execute("INSERT INTO threads(thread_id,owner,version,initial_state_hash,status,updated_at) VALUES(?,?,?,?,?,?)", (thread_id, owner, 0, state_hash, "active", now_iso()))
        return thread_id, 0

    def bump_thread_version(self, owner: str, expected: int) -> int:
        updated = self.conn.execute("UPDATE threads SET version=version+1,updated_at=? WHERE owner=? AND version=? AND status='active'", (now_iso(), owner, expected)).rowcount
        if updated != 1:
            raise StoreError("version_conflict")
        return expected + 1

    def get_thread(self, owner: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM threads WHERE owner=?", (owner,)).fetchone()

    def create_intention(
        self,
        owner: str,
        thread_id: str,
        desired_change: str,
        needs_user_input: bool = False,
        *,
        concern_id: str | None = None,
        task_id: str | None = None,
        concern_version: int | None = None,
    ) -> str:
        intention_id = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO intentions(intention_id,owner,thread_id,state,desired_change,version,concern_id,task_id,concern_version,needs_user_input,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (intention_id, owner, thread_id, "active", desired_change, 0, concern_id, task_id, concern_version, int(needs_user_input), now_iso(), now_iso()),
        )
        return intention_id

    def get_intention(self, intention_id: str, owner: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM intentions WHERE intention_id=? AND owner=?", (intention_id, owner)).fetchone()

    def current_intention(self, owner: str) -> dict[str, Any] | None:
        """Return the durable resumable intention after a process restart.

        The loop is intentionally stateless between events.  A restarted
        worker must therefore be able to discover the active/awaiting intent
        from SQLite instead of relying on an in-memory intention reference.
        """
        row = self.conn.execute(
            "SELECT * FROM intentions WHERE owner=? AND state IN ('active','awaiting_user') ORDER BY updated_at DESC LIMIT 1",
            (owner,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def current_action(self, owner: str, intention_id: str | None = None) -> dict[str, Any] | None:
        query = "SELECT action_id,owner,intention_id,event_id,type,state,event_version,idempotency_key,created_at,updated_at FROM actions WHERE owner=?"
        params: list[Any] = [owner]
        if intention_id:
            query += " AND intention_id=?"
            params.append(intention_id)
        query += " ORDER BY created_at DESC LIMIT 1"
        row = self.conn.execute(query, params).fetchone()
        return dict(row) if row is not None else None

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    @classmethod
    def _concern_from_row(cls, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["id"] = item.pop("concern_id")
        for field in (
            "desire_refs_json", "basis_refs_json", "linked_task_ids_json", "known_summary_json",
            "unknowns_json", "next_review_condition_json", "boundary_refs_json", "resolution_evidence_json",
        ):
            target = field.removesuffix("_json")
            item[target] = json.loads(item.pop(field))
        return item

    def get_concern(self, owner: str, concern_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM concerns WHERE owner=? AND concern_id=?", (owner, concern_id)).fetchone()
        return self._concern_from_row(row)

    def read_concerns(
        self,
        owner: str,
        *,
        ids: list[str] | None = None,
        query: str = "",
        limit: int = 6,
        include_history: bool = False,
    ) -> list[dict[str, Any]]:
        if limit < 1 or limit > 6:
            raise StoreError("concerns_read_limit_exceeded")
        if ids is not None and any(not isinstance(item, str) or not item.strip() for item in ids):
            raise StoreError("concerns_read_ids_invalid")
        if ids:
            placeholders = ",".join("?" for _ in ids)
            rows = self.conn.execute(
                f"SELECT * FROM concerns WHERE owner=? AND concern_id IN ({placeholders}) ORDER BY updated_at DESC LIMIT ?",
                [owner, *ids, limit],
            ).fetchall()
        else:
            states = ("active", "parked", "resolved", "dismissed") if include_history else ("active", "parked")
            placeholders = ",".join("?" for _ in states)
            rows = self.conn.execute(
                f"SELECT * FROM concerns WHERE owner=? AND status IN ({placeholders}) ORDER BY updated_at DESC LIMIT ?",
                [owner, *states, limit],
            ).fetchall()
        result = []
        needle = query.strip().lower()
        for row in rows:
            item = self._concern_from_row(row)
            if item is None:
                continue
            if needle and needle not in json.dumps(item, ensure_ascii=False, sort_keys=True).lower():
                continue
            result.append(item)
        return result

    def concern_catalog(self, owner: str) -> dict[str, Any]:
        active = self.conn.execute("SELECT COUNT(*) FROM concerns WHERE owner=? AND status='active'", (owner,)).fetchone()[0]
        return {
            "owner": owner,
            "tool": "concerns.read",
            "source_ref": f"store://{owner}/concerns",
            "selected_limit": 6,
            "max_active": 12,
            "active_count": int(active),
            "query": "ids or query only; server injects owner",
        }

    def recent_concern_events(self, owner: str, limit: int = 12) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id,owner,concern_id,event_id,action_id,local_ref,expected_version,new_version,operation,patch_json,refs_json,recorded_at FROM concern_events WHERE owner=? ORDER BY event_record_id DESC LIMIT ?",
            (owner, limit),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["patch"] = json.loads(item.pop("patch_json"))
            item["refs"] = json.loads(item.pop("refs_json"))
            result.append(item)
        return result

    def recent_feedback(self, owner: str, limit: int = 6) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT feedback_id,action_id,source,strength,original_text,payload_json,created_at FROM feedback WHERE owner=? ORDER BY created_at DESC LIMIT ?",
            (owner, limit),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            result.append(item)
        return result

    def _record_concern_event(
        self,
        *,
        owner: str,
        event_id: str,
        action_id: str | None,
        concern_id: str | None,
        local_ref: str = "",
        expected_version: int | None,
        new_version: int | None,
        operation: str,
        patch: dict[str, Any],
        refs: list[dict[str, Any]],
    ) -> None:
        self.conn.execute(
            "INSERT INTO concern_events(id,owner,concern_id,event_id,action_id,local_ref,expected_version,new_version,operation,patch_json,refs_json,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), owner, concern_id, event_id, action_id, local_ref, expected_version, new_version, operation, self._json(patch), self._json(refs), now_iso()),
        )

    def _record_concern_rejection(
        self,
        *,
        owner: str,
        event_id: str,
        action_id: str | None,
        update: dict[str, Any],
        reason: str,
        refs: list[dict[str, Any]] | None = None,
    ) -> None:
        concern_ref = str(update.get("concern_ref", ""))
        existing = self.conn.execute(
            "SELECT 1 FROM concern_events WHERE owner=? AND event_id=? AND operation='rejected' AND local_ref=?",
            (owner, event_id, concern_ref),
        ).fetchone()
        if existing:
            return
        self._record_concern_event(
            owner=owner,
            event_id=event_id,
            action_id=action_id,
            concern_id=None,
            local_ref=concern_ref,
            expected_version=update.get("expected_version") if isinstance(update.get("expected_version"), int) else None,
            new_version=None,
            operation="rejected",
            patch={"reason": reason, "update": update},
            refs=refs or [],
        )

    def _existing_tool_observation(
        self,
        owner: str,
        event_id: str,
        concern_id: str,
        action_id: str | None,
    ) -> sqlite3.Row | None:
        """Return an already persisted observation for an event/action pair.

        Tool continuations can be replayed after a worker restart.  The event
        and action are the runtime-owned idempotency boundary; the model must
        never be able to make the same source result advance a concern twice.
        ``IS`` is intentional here because a read-only observation may be
        recorded before an action id exists in a recovery path.
        """
        return self.conn.execute(
            "SELECT new_version,operation,patch_json,refs_json FROM concern_events "
            "WHERE owner=? AND event_id=? AND concern_id=? AND action_id IS ? "
            "AND operation IN ('tool_evidence','tool_observation') "
            "ORDER BY event_record_id DESC LIMIT 1",
            (owner, event_id, concern_id, action_id),
        ).fetchone()

    @staticmethod
    def _tool_source_refs(result: dict[str, Any]) -> list[str]:
        refs: list[str] = []
        for ref in result.get("source_refs") or []:
            if isinstance(ref, str) and ref and ref not in refs:
                refs.append(ref)
        data = result.get("data")
        items = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            ref = item.get("source_ref")
            if isinstance(ref, str) and ref and ref not in refs:
                refs.append(ref)
        return refs

    @staticmethod
    def _scoped_source_ref(ref: str, owner: str) -> bool:
        """Reject explicit local-owner leaks while allowing external source IDs.

        Feishu and provider references commonly have a token, not the bot
        owner, as their first URI component.  Local store/fixture/snapshot
        references do carry an owner and must be checked deterministically.
        """
        if "://" not in ref:
            return False
        scheme, remainder = ref.split("://", 1)
        if scheme not in {"store", "fixture", "snapshot", "experiment", "tool"}:
            return True
        ref_owner = remainder.split("/", 1)[0]
        return ref_owner == owner

    def apply_concern_updates(
        self,
        owner: str,
        event_id: str,
        updates: list[dict[str, Any]],
        *,
        action_id: str | None = None,
        explicit_user_goal: bool = False,
        max_active: int = 12,
        allowed_source_refs: set[str] | None = None,
    ) -> dict[str, Any]:
        """Apply model deltas in the caller's transaction, with per-item evidence."""
        from contracts.schemas import ContractError, validate_concern_updates

        result: dict[str, Any] = {"accepted": [], "rejected": [], "ref_map": {}, "rejected_refs": []}
        try:
            validated = validate_concern_updates(updates, owner, explicit_user_goal=explicit_user_goal)
        except ContractError as exc:
            # Keep each submitted object visible as a rejection, rather than
            # silently dropping a malformed delta or aborting an independent
            # user delivery.
            for update in updates if isinstance(updates, list) else []:
                rejection = {"concern_ref": update.get("concern_ref"), "reason": str(exc), "operation": update.get("operation")}
                result["rejected"].append(rejection)
                result["rejected_refs"].append(str(update.get("concern_ref", "")))
                self._record_concern_rejection(owner=owner, event_id=event_id, action_id=action_id, update=update, reason=str(exc))
            if not updates:
                return result
            return result

        for update in validated:
            operation = update["operation"]
            concern_ref = update["concern_ref"]
            update_refs = []
            candidate_refs: list[Any] = list(update.get("basis_refs") or [])
            for field in ("known_summary", "unknowns", "boundary_refs", "resolution_evidence"):
                values = update.get("changes", {}).get(field)
                if isinstance(values, list):
                    candidate_refs.extend(values)
            for value in candidate_refs:
                if isinstance(value, dict) and isinstance(value.get("source_ref"), str):
                    update_refs.append(value["source_ref"])
            if allowed_source_refs is not None:
                unknown_refs = sorted({ref for ref in update_refs if ref not in allowed_source_refs})
                if unknown_refs:
                    reason = "evidence_ref_not_worker_visible:" + ",".join(unknown_refs)
                    result["rejected"].append({"concern_ref": concern_ref, "reason": reason, "operation": operation})
                    result["rejected_refs"].append(concern_ref)
                    self._record_concern_rejection(owner=owner, event_id=event_id, action_id=action_id, update=update, reason=reason, refs=update.get("basis_refs", []))
                    continue
            local_ref = concern_ref if operation == "create" else ""
            if operation == "create":
                existing_event = self.conn.execute(
                    "SELECT concern_id,new_version FROM concern_events WHERE owner=? AND event_id=? AND local_ref=? AND operation=?",
                    (owner, event_id, local_ref, operation),
                ).fetchone()
            else:
                existing_event = self.conn.execute(
                    "SELECT concern_id,new_version FROM concern_events WHERE owner=? AND event_id=? AND concern_id=? AND operation=?",
                    (owner, event_id, concern_ref, operation),
                ).fetchone()
            if existing_event:
                concern_id = existing_event[0]
                if concern_id:
                    result["ref_map"][concern_ref] = concern_id
                    current = self.get_concern(owner, concern_id)
                else:
                    current = None
                result["accepted"].append({"concern_ref": concern_ref, "concern_id": concern_id, "new_version": existing_event[1], "idempotent_replay": True})
                continue
            changes = update["changes"]
            try:
                linked_task_ids = changes.get("linked_task_ids", [])
                missing_task_ids = [
                    task_id for task_id in linked_task_ids
                    if self.conn.execute(
                        "SELECT 1 FROM isolated_tasks WHERE owner=? AND task_id=?",
                        (owner, task_id),
                    ).fetchone() is None
                ]
                if missing_task_ids:
                    raise StoreError("task_link_owner_scope_or_not_found:" + ",".join(missing_task_ids))
                if operation == "create":
                    active_count = int(self.conn.execute("SELECT COUNT(*) FROM concerns WHERE owner=? AND status='active'", (owner,)).fetchone()[0])
                    desired_status = changes.get("status", "active")
                    if desired_status == "active" and active_count >= max_active:
                        raise StoreError("concern_capacity_exceeded")
                    concern_id = str(uuid.uuid4())
                    created = now_iso()
                    condition = changes.get("next_review_condition", {"type": "next_eligible_opportunity", "reason": "new relevant event"})
                    record = {
                        "concern_id": concern_id, "owner": owner, "version": 0,
                        "title": changes["title"], "desired_direction": changes["desired_direction"],
                        "domain": changes["domain"], "origin": changes["origin"],
                        "desire_refs": changes["desire_refs"], "basis_refs": update["basis_refs"],
                        "linked_task_ids": changes.get("linked_task_ids", []), "status": desired_status,
                        "known_summary": changes.get("known_summary", []), "unknowns": changes.get("unknowns", []),
                        "next_review_condition": condition, "last_progress_ref": None,
                        "last_contact_ref": None, "boundary_refs": changes.get("boundary_refs", []),
                        "resolution_evidence": changes.get("resolution_evidence", []),
                        "created_at": created, "updated_at": created, "review_after": self._review_after(condition),
                    }
                    self.conn.execute(
                        "INSERT INTO concerns(concern_id,owner,version,title,desired_direction,domain,origin,desire_refs_json,basis_refs_json,linked_task_ids_json,status,known_summary_json,unknowns_json,next_review_condition_json,last_progress_ref,last_contact_ref,boundary_refs_json,resolution_evidence_json,created_at,updated_at,review_after) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (record["concern_id"], record["owner"], record["version"], record["title"], record["desired_direction"], record["domain"], record["origin"], self._json(record["desire_refs"]), self._json(record["basis_refs"]), self._json(record["linked_task_ids"]), record["status"], self._json(record["known_summary"]), self._json(record["unknowns"]), self._json(record["next_review_condition"]), record["last_progress_ref"], record["last_contact_ref"], self._json(record["boundary_refs"]), self._json(record["resolution_evidence"]), record["created_at"], record["updated_at"], record["review_after"]),
                    )
                    new_version = 0
                else:
                    concern_id = concern_ref
                    current = self.get_concern(owner, concern_id)
                    if current is None:
                        raise StoreError("concern_not_found_or_owner_scope")
                    if current["status"] in {"resolved", "dismissed"} and operation in {"update", "park", "resolve", "dismiss"}:
                        raise StoreError("terminal_concern_requires_new_concern")
                    expected = update["expected_version"]
                    if current["version"] != expected:
                        raise StoreError("concern_version_conflict")
                    if "desire_refs" in changes:
                        raise StoreError("desire_configuration_immutable")
                    status = current["status"]
                    if operation == "park":
                        status = "parked"
                    elif operation == "resolve":
                        status = "resolved"
                    elif operation == "dismiss":
                        status = "dismissed"
                    elif "status" in changes:
                        status = changes["status"]
                    values = {
                        field: changes[field] for field in (
                            "title", "desired_direction", "domain", "origin", "linked_task_ids",
                            "known_summary", "unknowns", "next_review_condition", "boundary_refs", "resolution_evidence",
                        ) if field in changes
                    }
                    values["status"] = status
                    new_version = expected + 1
                    now = now_iso()
                    assignments = ["version=?", "updated_at=?"]
                    params: list[Any] = [new_version, now]
                    for field, value in values.items():
                        column = {
                            "linked_task_ids": "linked_task_ids_json", "known_summary": "known_summary_json",
                            "unknowns": "unknowns_json", "next_review_condition": "next_review_condition_json",
                            "boundary_refs": "boundary_refs_json", "resolution_evidence": "resolution_evidence_json",
                        }.get(field, field)
                        assignments.append(f"{column}=?")
                        params.append(self._json(value) if column.endswith("_json") else value)
                    if "next_review_condition" in values:
                        assignments.append("review_after=?"); params.append(self._review_after(values["next_review_condition"]))
                    params.extend([concern_id, owner, expected])
                    changed = self.conn.execute(
                        f"UPDATE concerns SET {', '.join(assignments)} WHERE concern_id=? AND owner=? AND version=?",
                        params,
                    ).rowcount
                    if changed != 1:
                        raise StoreError("concern_version_conflict")
                self._record_concern_event(owner=owner, event_id=event_id, action_id=action_id, concern_id=concern_id, local_ref=local_ref, expected_version=update["expected_version"], new_version=new_version, operation=operation, patch=changes, refs=update["basis_refs"])
                result["ref_map"][concern_ref] = concern_id
                result["accepted"].append({"concern_ref": concern_ref, "concern_id": concern_id, "new_version": new_version, "idempotent_replay": False})
            except (StoreError, sqlite3.IntegrityError) as exc:
                reason = str(exc)
                result["rejected"].append({"concern_ref": concern_ref, "reason": reason, "operation": operation})
                result["rejected_refs"].append(concern_ref)
                self._record_concern_rejection(owner=owner, event_id=event_id, action_id=action_id, update=update, reason=reason, refs=update["basis_refs"])
        return result

    @staticmethod
    def _review_after(condition: dict[str, Any]) -> str | None:
        if isinstance(condition, dict) and condition.get("type") == "after_time":
            return condition.get("not_before")
        return None

    def _touch_concern(self, owner: str, concern_id: str, event_id: str, action_id: str | None, field: str, ref: str, operation: str) -> int:
        current = self.get_concern(owner, concern_id)
        if current is None:
            raise StoreError("concern_not_found_or_owner_scope")
        existing = self.conn.execute(
            "SELECT new_version FROM concern_events WHERE owner=? AND event_id=? AND concern_id=? "
            "AND action_id IS ? AND operation=? ORDER BY event_record_id DESC LIMIT 1",
            (owner, event_id, concern_id, action_id, operation),
        ).fetchone()
        if existing is not None:
            return int(existing[0] if existing[0] is not None else current["version"])
        new_version = int(current["version"]) + 1
        now = now_iso()
        changed = self.conn.execute(
            f"UPDATE concerns SET {field}=?,version=?,updated_at=? WHERE concern_id=? AND owner=? AND version=?",
            (ref, new_version, now, concern_id, owner, current["version"]),
        ).rowcount
        if changed != 1:
            raise StoreError("concern_version_conflict")
        self._record_concern_event(owner=owner, event_id=event_id, action_id=action_id, concern_id=concern_id, expected_version=current["version"], new_version=new_version, operation=operation, patch={field: ref}, refs=[])
        return new_version

    def record_concern_progress(self, owner: str, concern_id: str, event_id: str, action_id: str | None, ref: str) -> int:
        return self._touch_concern(owner, concern_id, event_id, action_id, "last_progress_ref", ref, "progress")

    def record_concern_tool_evidence(
        self,
        owner: str,
        concern_id: str,
        event_id: str,
        action_id: str | None,
        *,
        tool_type: str,
        result: dict[str, Any],
    ) -> int:
        """Persist a source-bound tool observation exactly once.

        This is intentionally controller-owned.  A successful read appends a
        compact evidence object containing the returned source and version;
        an error records only an observation of the failed read and never
        promotes its payload to ``known_summary``.  Replaying the same
        event/action pair returns the already persisted concern version.
        """
        if result.get("scope") != owner:
            raise StoreError("tool_result_owner_scope_mismatch")
        current = self.get_concern(owner, concern_id)
        if current is None:
            raise StoreError("unknown_concern_or_owner")
        existing = self._existing_tool_observation(owner, event_id, concern_id, action_id)
        if existing is not None:
            return int(existing[0] if existing[0] is not None else current["version"])

        source_refs = self._tool_source_refs(result)
        invalid_refs = [ref for ref in source_refs if not self._scoped_source_ref(ref, owner)]
        if invalid_refs:
            raise StoreError("tool_result_source_scope_mismatch:" + ",".join(invalid_refs))
        result_version = str(result.get("version") or "unknown")
        data = result.get("data")
        items = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
        facts: list[str] = []
        facts_by_source: dict[str, list[str]] = {}
        observed_source_refs = list(source_refs)
        item_versions: dict[str, str] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            source_ref = item.get("source_ref")
            if isinstance(source_ref, str) and source_ref and source_ref not in observed_source_refs:
                observed_source_refs.append(source_ref)
            if isinstance(source_ref, str) and source_ref:
                item_versions[source_ref] = str(item.get("version") or item.get("source_revision") or result_version)
            metric = item.get("metric")
            if metric is None or "value" not in item:
                continue
            prefix = str(item.get("store_name") or item.get("store") or item.get("record_id") or "record")
            period_start = item.get("period_start")
            period_end = item.get("period_end")
            period = f" {period_start}..{period_end}" if period_start or period_end else ""
            fact = f"{prefix}{period}: {metric}={item.get('value')}"
            if fact not in facts:
                facts.append(fact)
            fact_source = source_ref if isinstance(source_ref, str) and source_ref else progress_ref
            facts_by_source.setdefault(fact_source, []).append(fact)
            if len(facts) >= 6:
                break
        progress_ref = observed_source_refs[0] if observed_source_refs else f"tool://{owner}/{action_id or event_id}"
        evidence_refs = [
            {
                "source_ref": ref,
                "version": item_versions.get(ref, result_version),
                "epistemic_status": "observed",
                "tool": tool_type,
            }
            for ref in observed_source_refs
        ]
        if result.get("status") != "complete" or not observed_source_refs or data in (None, {}, [], ""):
            self._record_concern_event(
                owner=owner,
                event_id=event_id,
                action_id=action_id,
                concern_id=concern_id,
                expected_version=int(current["version"]),
                new_version=int(current["version"]),
                operation="tool_observation",
                patch={
                    "status": result.get("status"),
                    "tool": tool_type,
                    "version": result_version,
                    "source_refs": observed_source_refs,
                    "fact_written": False,
                },
                refs=evidence_refs,
            )
            return int(current["version"])
        evidence_items = []
        for ref in observed_source_refs:
            evidence_items.append({
                "epistemic_status": "observed",
                "kind": f"{tool_type}_result",
                "source_ref": ref,
                "summary": "; ".join(facts_by_source.get(ref, facts[:6])) or f"{tool_type} returned complete data",
                "version": item_versions.get(ref, result_version),
                "source_refs": observed_source_refs,
            })
        known = list(current.get("known_summary", []))
        known_keys = {
            (item.get("source_ref"), str(item.get("version") or ""))
            for item in known
            if isinstance(item, dict)
        }
        new_evidence = [item for item in evidence_items if (item["source_ref"], item["version"]) not in known_keys]
        if not new_evidence:
            self._record_concern_event(
                owner=owner,
                event_id=event_id,
                action_id=action_id,
                concern_id=concern_id,
                expected_version=int(current["version"]),
                new_version=int(current["version"]),
                operation="tool_observation",
                patch={"status": result.get("status"), "tool": tool_type, "version": result_version, "fact_written": False, "duplicate_source": True},
                refs=evidence_refs,
            )
            return int(current["version"])
        known.extend(new_evidence)
        basis = list(current.get("basis_refs", []))
        known_basis_keys = {
            (item.get("source_ref"), str(item.get("version") or ""))
            for item in basis
            if isinstance(item, dict)
        }
        for evidence in new_evidence:
            if (evidence["source_ref"], evidence["version"]) not in known_basis_keys:
                basis.append(evidence)
        new_version = int(current["version"]) + 1
        now = now_iso()
        changed = self.conn.execute(
            "UPDATE concerns SET version=?, known_summary_json=?, basis_refs_json=?, last_progress_ref=?, updated_at=? WHERE concern_id=? AND owner=? AND version=?",
            (new_version, self._json(known), self._json(basis), progress_ref, now, concern_id, owner, current["version"]),
        ).rowcount
        if changed != 1:
            raise StoreError("concern_version_conflict")
        self._record_concern_event(
            owner=owner,
            event_id=event_id,
            action_id=action_id,
            concern_id=concern_id,
            expected_version=current["version"],
            new_version=new_version,
            operation="tool_evidence",
            patch={"known_summary_append": new_evidence, "last_progress_ref": progress_ref, "version": result_version},
            refs=evidence_refs,
        )
        return new_version

    def record_concern_contact(self, owner: str, concern_id: str, event_id: str, action_id: str | None, ref: str) -> int:
        return self._touch_concern(owner, concern_id, event_id, action_id, "last_contact_ref", ref, "contact")

    def update_intention(self, intention_id: str, owner: str, expected_version: int, state: str | None = None, needs_user_input: bool | None = None) -> int:
        fields = ["version=version+1", "updated_at=?"]
        values: list[Any] = [now_iso()]
        if state is not None:
            fields.append("state=?"); values.append(state)
        if needs_user_input is not None:
            fields.append("needs_user_input=?"); values.append(int(needs_user_input))
        values.extend([intention_id, owner, expected_version])
        updated = self.conn.execute(f"UPDATE intentions SET {', '.join(fields)} WHERE intention_id=? AND owner=? AND version=? AND state NOT IN ('completed','abandoned')", values).rowcount
        if updated != 1:
            raise StoreError("intention_version_conflict_or_terminal")
        return expected_version + 1

    def create_action(self, owner: str, intention_id: str, event_id: str, action_type: str, args: dict[str, Any], event_version: int) -> str:
        action_id = str(uuid.uuid4())
        idem = f"{owner}:{action_id}"
        self.conn.execute("INSERT INTO actions(action_id,owner,intention_id,event_id,type,args_json,state,event_version,idempotency_key,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (action_id, owner, intention_id, event_id, action_type, json.dumps(args, ensure_ascii=False, sort_keys=True), "planned", event_version, idem, now_iso(), now_iso()))
        return action_id

    def action(self, action_id: str, owner: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM actions WHERE action_id=? AND owner=?", (action_id, owner)).fetchone()

    def latest_action(self, owner: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM actions WHERE owner=? ORDER BY created_at DESC LIMIT 1", (owner,)).fetchone()

    def delivered_segments(self, owner: str) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT segment_id,action_id,status,receipt_json,created_at FROM sink_deliveries WHERE owner=? ORDER BY created_at", (owner,)).fetchall()
        return [dict(row) for row in rows]

    def update_action(self, action_id: str, owner: str, state: str, result: dict[str, Any] | None = None) -> None:
        self.conn.execute("UPDATE actions SET state=?,result_json=?,updated_at=? WHERE action_id=? AND owner=?", (state, json.dumps(result, ensure_ascii=False) if result is not None else None, now_iso(), action_id, owner))

    def record_tool(self, owner: str, action_id: str, original: dict, normalized: dict, diff: dict, result: dict) -> str:
        request_id = str(uuid.uuid4())
        self.conn.execute("INSERT INTO tool_requests(request_id,owner,action_id,original_args_json,normalized_args_json,diff_json,result_json,created_at) VALUES(?,?,?,?,?,?,?,?)", (request_id, owner, action_id, json.dumps(original, ensure_ascii=False), json.dumps(normalized, ensure_ascii=False), json.dumps(diff, ensure_ascii=False), json.dumps(result, ensure_ascii=False), now_iso()))
        return request_id

    def record_receipt(self, owner: str, action_id: str, receipt: dict) -> None:
        try:
            self.conn.execute("INSERT INTO sink_deliveries(segment_id,owner,action_id,attempt_id,status,idempotency_key,receipt_json,created_at) VALUES(?,?,?,?,?,?,?,?)", (receipt["segment_id"], owner, action_id, receipt["attempt_id"], receipt["status"], receipt["idempotency_key"], json.dumps(receipt, ensure_ascii=False), now_iso()))
        except sqlite3.IntegrityError:
            existing = self.conn.execute("SELECT status FROM sink_deliveries WHERE idempotency_key=?", (receipt["idempotency_key"],)).fetchone()
            if not existing or existing[0] != receipt["status"]:
                raise StoreError("receipt_idempotency_conflict")

    def record_feedback(self, owner: str, action_id: str, source: str, strength: str, original_text: str, payload: dict[str, Any]) -> str:
        feedback_id = str(uuid.uuid4())
        self.conn.execute("INSERT INTO feedback(feedback_id,owner,action_id,source,strength,original_text,payload_json,created_at) VALUES(?,?,?,?,?,?,?,?)", (feedback_id, owner, action_id, source, strength, original_text, json.dumps(payload, ensure_ascii=False), now_iso()))
        return feedback_id

    def seed_tasks(self, owner: str, tasks: list[dict[str, Any]]) -> None:
        """Seed isolated task state once; never overwrite a later mutation."""
        for task in tasks:
            task_id = str(task.get("id", ""))
            if not task_id:
                continue
            self.conn.execute(
                "INSERT OR IGNORE INTO isolated_tasks(owner,task_id,payload_json,state,version,source_ref,updated_at) VALUES(?,?,?,?,?,?,?)",
                (owner, task_id, json.dumps(task, ensure_ascii=False, sort_keys=True), task.get("status", "open"), 0, task.get("source_ref"), now_iso()),
            )

    def read_tasks(self, owner: str, status: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT task_id,payload_json,state,version,source_ref,updated_at FROM isolated_tasks WHERE owner=?"
        args: list[Any] = [owner]
        if status:
            query += " AND state=?"; args.append(status)
        query += " ORDER BY task_id"
        rows = []
        for row in self.conn.execute(query, args):
            payload = json.loads(row[1]); payload.update({"id": row[0], "status": row[2], "version": row[3], "source_ref": row[4], "updated_at": row[5]})
            rows.append(payload)
        return rows

    def update_task(self, owner: str, task_id: str, *, state: str, expected_version: int | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
        if idempotency_key:
            replay = self.conn.execute(
                "SELECT task_id,result_json FROM task_updates WHERE owner=? AND idempotency_key=?",
                (owner, idempotency_key),
            ).fetchone()
            if replay and replay[0] != task_id:
                raise StoreError("task_idempotency_conflict")
            if replay:
                result = json.loads(replay[1])
                result["idempotent_replay"] = True
                return result
        row = self.conn.execute("SELECT version FROM isolated_tasks WHERE owner=? AND task_id=?", (owner, task_id)).fetchone()
        if not row:
            raise StoreError("task_not_found")
        if expected_version is not None and int(row[0]) != int(expected_version):
            raise StoreError("task_version_conflict")
        changed = self.conn.execute(
            "UPDATE isolated_tasks SET state=?,version=version+1,updated_at=? WHERE owner=? AND task_id=? AND version=?",
            (state, now_iso(), owner, task_id, row[0]),
        ).rowcount
        if changed != 1:
            raise StoreError("task_version_conflict")
        result = next((item for item in self.read_tasks(owner) if item["id"] == task_id), None)
        if result is None:
            raise StoreError("task_not_found")
        if idempotency_key:
            self.conn.execute(
                "INSERT INTO task_updates(owner,task_id,idempotency_key,result_json,created_at) VALUES(?,?,?,?,?)",
                (owner, task_id, idempotency_key, json.dumps(result, ensure_ascii=False, sort_keys=True), now_iso()),
            )
        return result

    def create_candidate(self, owner: str, payload: dict[str, Any], source_ref: str) -> dict[str, Any]:
        candidate_id = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO knowledge_candidates(candidate_id,owner,payload_json,status,source_ref,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (candidate_id, owner, json.dumps(payload, ensure_ascii=False, sort_keys=True), "candidate", source_ref, now_iso(), now_iso()),
        )
        return {"candidate_id": candidate_id, "status": "candidate", "candidate": payload, "confirmed": False, "source_ref": source_ref}

    def record_user_confirmation(self, owner: str, candidate_id: str, event_id: str, original_text: str, accepted: bool) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO user_confirmations(confirmation_id,owner,candidate_id,event_id,accepted,original_text,created_at) VALUES(?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), owner, candidate_id, event_id, int(bool(accepted)), original_text, now_iso()),
        )

    def confirm_candidate(self, owner: str, candidate_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM knowledge_candidates WHERE candidate_id=? AND owner=?", (candidate_id, owner)).fetchone()
        if not row:
            raise StoreError("candidate_not_found")
        confirmation = self.conn.execute(
            "SELECT event_id,accepted FROM user_confirmations WHERE owner=? AND candidate_id=? ORDER BY created_at DESC LIMIT 1",
            (owner, candidate_id),
        ).fetchone()
        if not confirmation or not confirmation[1]:
            raise StoreError("user_confirmation_required")
        self.conn.execute("UPDATE knowledge_candidates SET status='confirmed',confirmed_by_event=?,updated_at=? WHERE candidate_id=? AND owner=?", (confirmation[0], now_iso(), candidate_id, owner))
        return {"candidate_id": candidate_id, "status": "confirmed", "confirmed": True, "confirmed_by_event": confirmation[0], "source_ref": row[4]}

    def search_knowledge(self, owner: str, term: str = "", *, include_candidates: bool = False) -> list[dict[str, Any]]:
        states = ("confirmed", "candidate") if include_candidates else ("confirmed",)
        rows = self.conn.execute("SELECT candidate_id,payload_json,status,source_ref,updated_at FROM knowledge_candidates WHERE owner=? ORDER BY updated_at", (owner,)).fetchall()
        result = []
        for row in rows:
            if row[2] not in states:
                continue
            payload = json.loads(row[1])
            if term and term.lower() not in json.dumps(payload, ensure_ascii=False).lower():
                continue
            result.append({"id": row[0], "owner": owner, "kind": "knowledge_candidate" if row[2] == "candidate" else "knowledge", "value": payload, "status": row[2], "source_ref": row[3], "updated_at": row[4]})
        return result

    def configure_budget(self, owner: str, max_model_calls: int = 6, max_tool_rounds: int = 4, max_infra_retries: int = 2, *, reset: bool = False) -> None:
        if reset:
            self.conn.execute(
                """INSERT INTO budgets(owner,model_calls,tool_rounds,infra_retries,max_model_calls,max_tool_rounds,max_infra_retries)
                   VALUES(?,0,0,0,?,?,?)
                   ON CONFLICT(owner) DO UPDATE SET
                     model_calls=0,tool_rounds=0,infra_retries=0,
                     max_model_calls=excluded.max_model_calls,
                     max_tool_rounds=excluded.max_tool_rounds,
                     max_infra_retries=excluded.max_infra_retries""",
                (owner, max_model_calls, max_tool_rounds, max_infra_retries),
            )
            return
        self.conn.execute("INSERT OR IGNORE INTO budgets(owner,max_model_calls,max_tool_rounds,max_infra_retries) VALUES(?,?,?,?)", (owner, max_model_calls, max_tool_rounds, max_infra_retries))

    def consume_budget(self, owner: str, kind: str) -> tuple[bool, dict[str, int]]:
        field = {"model": "model_calls", "tool": "tool_rounds", "retry": "infra_retries"}.get(kind)
        if not field:
            raise ValueError(kind)
        row = self.conn.execute("SELECT * FROM budgets WHERE owner=?", (owner,)).fetchone()
        if not row:
            raise StoreError("budget_not_configured")
        current = row[field]; maximum = row["max_" + field.replace("_calls", "_calls").replace("_rounds", "_rounds").replace("_retries", "_retries")]
        if current >= maximum:
            return False, dict(row)
        self.conn.execute(f"UPDATE budgets SET {field}={field}+1 WHERE owner=?", (owner,))
        updated = self.conn.execute("SELECT * FROM budgets WHERE owner=?", (owner,)).fetchone()
        return True, dict(updated)

    def acquire_lease(self, owner: str, ttl_seconds: float = 30.0) -> str:
        import time
        lease_id = str(uuid.uuid4())
        now = time.time()
        with self.transaction():
            row = self.conn.execute("SELECT lease_id,expires_at FROM leases WHERE owner=?", (owner,)).fetchone()
            if row and row[1] > now:
                raise StoreError("lease_conflict")
            self.conn.execute("INSERT OR REPLACE INTO leases(owner,lease_id,expires_at) VALUES(?,?,?)", (owner, lease_id, now + ttl_seconds))
        return lease_id

    def release_lease(self, owner: str, lease_id: str | None = None) -> None:
        if lease_id is None:
            self.conn.execute("DELETE FROM leases WHERE owner=?", (owner,))
        else:
            self.conn.execute("DELETE FROM leases WHERE owner=? AND lease_id=?", (owner, lease_id))

    def trace(self, owner: str, event_id: str, step: int, payload: dict[str, Any]) -> str:
        trace_id = str(uuid.uuid4())
        self.conn.execute("INSERT INTO traces(trace_id,owner,event_id,step,payload_json,created_at) VALUES(?,?,?,?,?,?)", (trace_id, owner, event_id, step, json.dumps(payload, ensure_ascii=False), now_iso()))
        return trace_id
