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

    def deliver_text(self, *, owner: str, event_version: int, action_id: str, segment_id: str, text: str, trace_context: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._deliver(owner=owner, event_version=event_version, action_id=action_id, segment_id=segment_id, kind="text", payload={"text": text}, trace_context=trace_context)

    def deliver_media(self, *, owner: str, event_version: int, action_id: str, segment_id: str, asset_path: str, caption: str = "", trace_context: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._deliver(owner=owner, event_version=event_version, action_id=action_id, segment_id=segment_id, kind="media", payload={"asset_path": asset_path, "caption": caption}, trace_context=trace_context)

    def typing(self, *, owner: str, event_version: int, action_id: str, segment_id: str, trace_context: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._deliver(owner=owner, event_version=event_version, action_id=action_id, segment_id=segment_id, kind="typing", payload={}, trace_context=trace_context)

    def _deliver(self, *, owner: str, event_version: int, action_id: str, segment_id: str, kind: str, payload: dict[str, Any], trace_context: dict[str, Any] | None = None) -> dict[str, Any]:
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
        return self._record({"attempt_id": attempt_id, "owner": owner, "event_version": event_version, "action_id": action_id, "segment_id": segment_id, "kind": kind, "payload": payload, "trace_context": trace_context or {}}, receipt)


class NoOpSink:
    """Local semantic-smoke sink that can never contact a Bot transport.

    It returns an ``unknown`` receipt deliberately: the loop can persist the
    attempted response and its evidence, but it must not mark a message as
    sent or advance concern contact state.  ``outboundCalls`` is kept as an
    explicit audit counter and is always zero.
    """

    def __init__(self, trace_path: pathlib.Path, audit: dict[str, Any] | None = None):
        self.trace_path = trace_path
        self.audit = audit if audit is not None else {}
        self.attempts: list[dict[str, Any]] = []
        self.receipts: list[dict[str, Any]] = []
        self.audit["outboundCalls"] = 0

    def _record(self, attempt: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
        self.attempts.append(attempt)
        self.receipts.append(receipt)
        self.audit["outboundCalls"] = 0
        self.audit.setdefault("visibleResponses", []).append(attempt.get("payload", {}).get("text"))
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        import json
        with self.trace_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"kind": "noop_sink_attempt", "attempt": attempt, "receipt": receipt, "outboundCalls": 0}, ensure_ascii=False) + "\n")
        return receipt

    def deliver_text(self, *, owner: str, event_version: int, action_id: str, segment_id: str, text: str, trace_context: dict[str, Any] | None = None) -> dict[str, Any]:
        attempt_id = str(uuid.uuid4())
        receipt = validate_delivery_result({
            "status": "unknown",
            "attempt_id": attempt_id,
            "segment_id": segment_id,
            "idempotency_key": f"ideal-lab-local-smoke:{owner}:{action_id}:{segment_id}",
            "provider_message_id": None,
        })
        return self._record({"attempt_id": attempt_id, "owner": owner, "event_version": event_version, "action_id": action_id, "segment_id": segment_id, "kind": "text", "payload": {"text": text}, "trace_context": trace_context or {}, "delivery_mode": "no_op"}, receipt)

    def deliver_media(self, **kwargs: Any) -> dict[str, Any]:
        return self.deliver_text(text=kwargs.get("caption", ""), **{key: kwargs[key] for key in ("owner", "event_version", "action_id", "segment_id")}, trace_context=kwargs.get("trace_context"))

    def typing(self, **kwargs: Any) -> dict[str, Any]:
        return self.deliver_text(text="", **{key: kwargs[key] for key in ("owner", "event_version", "action_id", "segment_id")}, trace_context=kwargs.get("trace_context"))
