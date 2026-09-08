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
            """
        )

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

    def create_intention(self, owner: str, thread_id: str, desired_change: str, needs_user_input: bool = False) -> str:
        intention_id = str(uuid.uuid4())
        self.conn.execute("INSERT INTO intentions(intention_id,owner,thread_id,state,desired_change,version,needs_user_input,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)", (intention_id, owner, thread_id, "active", desired_change, 0, int(needs_user_input), now_iso(), now_iso()))
        return intention_id

    def get_intention(self, intention_id: str, owner: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM intentions WHERE intention_id=? AND owner=?", (intention_id, owner)).fetchone()

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

    def configure_budget(self, owner: str, max_model_calls: int = 6, max_tool_rounds: int = 4, max_infra_retries: int = 2) -> None:
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
