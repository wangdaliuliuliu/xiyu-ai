"""Single sink for text, media, typing, and delivery receipts."""
from __future__ import annotations

import pathlib
import uuid
from typing import Any

from contracts.schemas import validate_delivery_result


class RecordingSink:
    def __init__(self, trace_path: pathlib.Path, outcomes: dict[str, str] | None = None):
        self.trace_path = trace_path
        self.outcomes = outcomes or {}
        self.attempts: list[dict[str, Any]] = []
        self.receipts: list[dict[str, Any]] = []

    def _record(self, attempt: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
        self.attempts.append(attempt)
        self.receipts.append(receipt)
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        with self.trace_path.open("a", encoding="utf-8") as stream:
            import json
            stream.write(json.dumps({"kind": "sink_delivery", "attempt": attempt, "receipt": receipt}, ensure_ascii=False) + "\n")
        return receipt

    def deliver_text(self, *, owner: str, event_version: int, action_id: str, segment_id: str, text: str) -> dict[str, Any]:
        return self._deliver(owner=owner, event_version=event_version, action_id=action_id, segment_id=segment_id, kind="text", payload={"text": text})

    def deliver_media(self, *, owner: str, event_version: int, action_id: str, segment_id: str, asset_path: str, caption: str = "") -> dict[str, Any]:
        return self._deliver(owner=owner, event_version=event_version, action_id=action_id, segment_id=segment_id, kind="media", payload={"asset_path": asset_path, "caption": caption})

    def typing(self, *, owner: str, event_version: int, action_id: str, segment_id: str) -> dict[str, Any]:
        return self._deliver(owner=owner, event_version=event_version, action_id=action_id, segment_id=segment_id, kind="typing", payload={})

    def _deliver(self, *, owner: str, event_version: int, action_id: str, segment_id: str, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        attempt_id = str(uuid.uuid4())
        idempotency_key = f"ideal-lab:{owner}:{action_id}:{segment_id}"
        status = self.outcomes.get(segment_id, self.outcomes.get("*", "delivered"))
        receipt = validate_delivery_result({
            "status": status,
            "attempt_id": attempt_id,
            "segment_id": segment_id,
            "idempotency_key": idempotency_key,
            "provider_message_id": str(uuid.uuid4()) if status == "delivered" else None,
        })
        return self._record({"attempt_id": attempt_id, "owner": owner, "event_version": event_version, "action_id": action_id, "segment_id": segment_id, "kind": kind, "payload": payload}, receipt)
