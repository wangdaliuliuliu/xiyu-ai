"""The single event-consumption and model/tool continuation loop."""
from __future__ import annotations

import json
import pathlib
import uuid
from typing import Any

from adapters.local import AdapterError, LocalAdapters
from contracts.schemas import ContractError, normalize_action_args, validate_decision, validate_event, validate_tool_result
from controller.gateway import ModelGateway, ProviderResponse
from runtime.context import ContextBuilder, ContextError
from runtime.policy import Policy, PolicyError
from runtime.prompts.assemble import assemble
from runtime.store import EventStore, StoreError
from transport.sink import RecordingSink


class AgencyLoop:
    def __init__(self, *, store: EventStore, context: ContextBuilder, adapters: LocalAdapters, policy: Policy, gateway: ModelGateway, sink: RecordingSink, trace_path: pathlib.Path):
        self.store = store
        self.context_builder = context
        self.adapters = adapters
        self.policy = policy
        self.gateway = gateway
        self.sink = sink
        self.trace_path = trace_path

    def _trace(self, owner: str, event_id: str, step: int, payload: dict[str, Any]) -> str:
        trace_id = self.store.trace(owner, event_id, step, payload)
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        with self.trace_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"trace_id": trace_id, "owner": owner, "event_id": event_id, "step": step, **payload}, ensure_ascii=False) + "\n")
        return trace_id

    def _provider_call(self, owner: str, event: dict[str, Any], prompt: dict[str, Any], step: int) -> ProviderResponse:
        self.policy.consume(owner, "model")
        response = self.gateway.complete(prompt, attempt=1)
        self._trace(owner, event["event_id"], step, {
            "kind": "provider_call",
            "model": response.model,
            "request_id": response.request_id,
            "prompt": prompt,
            "raw_response": response.content,
            "finish_reason": response.finish_reason,
            "usage": response.usage,
            "latency_ms": response.latency_ms,
            "error": response.error,
        })
        return response

    def process_event(self, raw_event: dict[str, Any]) -> dict[str, Any]:
        event = validate_event(raw_event)
        owner = event["owner"]
        if self.store.has_event(event["event_id"]):
            return {"status": "duplicate", "event_id": event["event_id"]}
        try:
            lease_id = self.store.acquire_lease(owner)
        except StoreError as exc:
            return {"status": "blocked", "reason": str(exc), "path_id": "P18"}
        thread = self.store.get_thread(owner)
        initial_state = {"owner": owner, "fixture": self.context_builder.fixture.get("schemaVersion")}
        if not thread:
            thread_id, current_version = self.store.ensure_thread(owner, initial_state)
        else:
            thread_id, current_version = thread["thread_id"], thread["version"]
        event_version = current_version
        if event["kind"] in {"user_message", "opportunity", "task_due", "silence_observed"}:
            event_version = self.store.bump_thread_version(owner, current_version)
        if not self.store.insert_event(event, event_version):
            return {"status": "duplicate", "event_id": event["event_id"]}
        self.store.configure_budget(owner)
        self._trace(owner, event["event_id"], 0, {"kind": "input", "input": event, "event_version": event_version})
        try:
            if event["kind"] == "silence_observed":
                latest = self.store.latest_action(owner)
                if latest:
                    self.store.record_feedback(owner, latest["action_id"], "silence_observed", "none", "", event["payload"])
                self._trace(owner, event["event_id"], 1, {"kind": "silence_observed", "action_id": latest["action_id"] if latest else None})
                return {"status": "observed", "event_id": event["event_id"], "path_id": "P15", "action_id": latest["action_id"] if latest else None}
            return self._decision_cycle(event, thread_id, event_version)
        except (ContractError, ContextError, PolicyError, AdapterError, StoreError) as exc:
            self._trace(owner, event["event_id"], 999, {"kind": "failure", "error": type(exc).__name__, "message": str(exc)})
            return {"status": "failed", "event_id": event["event_id"], "error": type(exc).__name__, "message": str(exc)}
        finally:
            self.store.release_lease(owner, lease_id)

    def _decision_cycle(self, event: dict[str, Any], thread_id: str, event_version: int) -> dict[str, Any]:
        owner = event["owner"]
        thread = self.store.get_thread(owner)
        thread_state = dict(thread) if thread else {}
        thread_state["delivered_segments"] = self.store.delivered_segments(owner)
        context = self.context_builder.build(event, thread_state=thread_state)
        prompt = assemble(context, event=event)
        first = self._provider_call(owner, event, prompt, 1)
        if first.error:
            return {"status": "infra_failure", "event_id": event["event_id"], "error": first.error, "path_id": "P13"}
        try:
            decision = validate_decision(first.content if isinstance(first.content, dict) else json.loads(first.content))
        except (ContractError, json.JSONDecodeError, TypeError) as exc:
            self._trace(owner, event["event_id"], 2, {"kind": "schema_failure", "raw_response": first.content, "error": str(exc)})
            return {"status": "schema_failure", "event_id": event["event_id"], "path_id": "P13", "error": str(exc)}
        intention = None
        if decision["intention_ref"]:
            intention = self.store.get_intention(decision["intention_ref"], owner)
            if not intention:
                raise PolicyError("unknown_intention_or_owner")
        if intention is None:
            intention_id = self.store.create_intention(owner, thread_id, decision["desired_change"], decision["action"]["type"] == "wait")
            intention_version = 0
        else:
            intention_id = intention["intention_id"]
            intention_version = intention["version"]
        action = decision["action"]
        action_type = action["type"]
        self.policy.check_action(owner, event, action, thread_version=event_version)
        action_args, arg_diff = normalize_action_args(action_type, action.get("args", {}))
        action_id = self.store.create_action(owner, intention_id, event["event_id"], action_type, action_args, event_version)
        self._trace(owner, event["event_id"], 3, {"kind": "decision", "decision": decision, "intention_id": intention_id, "action_id": action_id, "argument_diff": arg_diff})
        if action_type == "wait":
            self.policy.validate_wait(decision["reconsider_condition"])
            self.store.update_action(action_id, owner, "prepared", {"reconsider_condition": decision["reconsider_condition"]})
            self.store.update_intention(intention_id, owner, intention_version, "active", True)
            return {"status": "waiting", "event_id": event["event_id"], "path_id": "P12", "intention_id": intention_id, "action_id": action_id}
        if action_type == "none":
            self.store.update_action(action_id, owner, "prepared", {"operation": decision["operation"]})
            return {"status": "prepared", "event_id": event["event_id"], "path_id": "P03" if event["kind"] == "user_message" else "P05", "intention_id": intention_id, "action_id": action_id}
        if action_type == "deliver":
            return self._deliver(event, event_version, intention_id, intention_version, action_id, decision["messages"], needs_user_input=bool(decision.get("expected_participation")))
        return self._run_tool_then_continue(event, event_version, intention_id, intention_version, action_id, action_type, action.get("args", {}), action_args, arg_diff, context)

    def _run_tool_then_continue(self, event: dict[str, Any], event_version: int, intention_id: str, intention_version: int, action_id: str, action_type: str, original_args: dict[str, Any], args: dict[str, Any], arg_diff: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        owner = event["owner"]
        self.store.update_action(action_id, owner, "running")
        self.policy.consume(owner, "tool")
        try:
            result = validate_tool_result(self.adapters.execute(owner, action_type, args))
        except AdapterError as exc:
            result = validate_tool_result({"status": "unavailable", "data": {}, "source_refs": [], "scope": owner, "version": "adapter-v1", "trace_id": str(uuid.uuid4()), "completeness": "none"})
            self._trace(owner, event["event_id"], 4, {"kind": "tool_error", "error": str(exc)})
        self.store.record_tool(owner, action_id, original_args, args, arg_diff, result)
        self.store.update_action(action_id, owner, "prepared" if result["status"] == "complete" else "failed", result)
        self._trace(owner, event["event_id"], 4, {"kind": "tool_result", "action_id": action_id, "tool_type": action_type, "result": result})
        next_context = self.context_builder.build(event, thread_state={}, related_tool_result=result)
        second = self._provider_call(owner, event, assemble(next_context, event=event, tool_result=result), 5)
        if second.error:
            return {"status": "infra_failure", "event_id": event["event_id"], "path_id": "P13", "intention_id": intention_id, "action_id": action_id, "error": second.error}
        try:
            next_decision = validate_decision(second.content if isinstance(second.content, dict) else json.loads(second.content))
        except (ContractError, json.JSONDecodeError, TypeError) as exc:
            return {"status": "schema_failure", "event_id": event["event_id"], "path_id": "P13", "intention_id": intention_id, "action_id": action_id, "error": str(exc)}
        if next_decision["action"]["type"] != "deliver":
            if next_decision["action"]["type"] == "wait":
                self.store.update_intention(intention_id, owner, intention_version, "active", True)
                return {"status": "waiting", "event_id": event["event_id"], "path_id": "P12", "intention_id": intention_id, "action_id": action_id}
            return {"status": "prepared", "event_id": event["event_id"], "path_id": "P13" if result["status"] != "complete" else "P02", "intention_id": intention_id, "action_id": action_id, "tool_status": result["status"]}
        if next_decision.get("intention_ref") not in (None, intention_id):
            raise PolicyError("continuation_intention_mismatch")
        return self._deliver(event, event_version, intention_id, intention_version, action_id, next_decision["messages"], tool_status=result["status"], needs_user_input=bool(next_decision.get("expected_participation")))

    def _deliver(self, event: dict[str, Any], event_version: int, intention_id: str, intention_version: int, action_id: str, messages: list[str], *, tool_status: str | None = None, needs_user_input: bool = False) -> dict[str, Any]:
        owner = event["owner"]
        self.policy.can_deliver_current(owner, event_version, self.store.get_thread(owner)["version"])
        self.store.update_action(action_id, owner, "ready", {"tool_status": tool_status, "messages": messages})
        receipts = []
        for index, message in enumerate(messages, 1):
            segment_id = f"{action_id}:{index}"
            receipt = self.sink.deliver_text(owner=owner, event_version=event_version, action_id=action_id, segment_id=segment_id, text=message)
            self.store.record_receipt(owner, action_id, receipt)
            receipts.append(receipt)
        statuses = {receipt["status"] for receipt in receipts}
        if statuses == {"delivered"}:
            final_state = "delivered"
            intention_state = "awaiting_user" if needs_user_input else "completed"
            path_id = "P11" if tool_status is not None else "P03"
        elif "partial" in statuses:
            final_state = "partial"; intention_state = "active"; path_id = "P14"
        elif "unknown" in statuses:
            final_state = "unknown"; intention_state = "active"; path_id = "P14"
        else:
            final_state = "failed"; intention_state = "active"; path_id = "P14"
        self.store.update_action(action_id, owner, final_state, {"receipts": receipts})
        self.store.update_intention(intention_id, owner, intention_version, intention_state, intention_state == "awaiting_user")
        self._trace(owner, event["event_id"], 6, {"kind": "delivery", "action_id": action_id, "final_state": final_state, "receipts": receipts})
        return {"status": final_state, "event_id": event["event_id"], "path_id": path_id, "intention_id": intention_id, "action_id": action_id, "receipts": receipts}
