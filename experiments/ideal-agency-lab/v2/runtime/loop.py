"""The single event-consumption and model/tool continuation loop."""
from __future__ import annotations

import json
import pathlib
import uuid
import hashlib
import inspect
from copy import deepcopy
from typing import Any

from adapters.local import AdapterError, LocalAdapters
from contracts.schemas import ContractError, normalize_action_args, parse_and_validate_decision, parse_and_validate_semantic_proposal, validate_event, validate_tool_result
from controller.gateway import ModelGateway, ProviderResponse
from runtime.context import ContextBuilder, ContextError
from runtime.grounding import repair_decision
from runtime.policy import Policy, PolicyError
from runtime.prompts.assemble import assemble, assemble_compact_continuation
from runtime.semantic_proposal import SemanticProposalError, compile_semantic_proposal
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
        # Trace context is worker-local and is never included in a model
        # prompt.  It makes the append-only evidence self-describing without
        # allowing the harness to choose a semantic route for the model.
        self._trace_context: dict[str, Any] = {}

    @staticmethod
    def _callsite(depth: int = 2) -> str:
        frame = inspect.currentframe()
        for _ in range(depth):
            if frame is None:
                return "runtime.loop:unknown"
            frame = frame.f_back
        if frame is None:
            return "runtime.loop:unknown"
        return f"{pathlib.Path(frame.f_code.co_filename).as_posix().split('/')[-2:][0]}:{frame.f_code.co_name}"

    def _trace(self, owner: str, event_id: str, step: int, payload: dict[str, Any]) -> str:
        selected_concern_id = self._trace_context.get("selected_concern_id") or self._trace_context.get("concern_id")
        retrieved_source_refs = list(self._trace_context.get("retrieved_source_refs") or [])
        auto_recorded_evidence_refs = list(self._trace_context.get("auto_recorded_evidence_refs") or [])
        model_concern_updates = deepcopy(self._trace_context.get("model_concern_updates") or [])
        accepted_patches = deepcopy(self._trace_context.get("accepted_concern_patches") or [])
        rejected_patches = deepcopy(self._trace_context.get("rejected_concern_patches") or [])
        action_evidence_refs = list(self._trace_context.get("action_evidence_refs") or [])
        receipt = deepcopy(self._trace_context.get("receipt"))
        persisted_version = self._trace_context.get("concern_version")
        trace_payload = {
            "entry_kind": self._trace_context.get("entry_kind"),
            "event_version": self._trace_context.get("event_version"),
            "intention_id": self._trace_context.get("intention_id"),
            "action_id": self._trace_context.get("action_id"),
            "concern_id": self._trace_context.get("concern_id"),
            "concern_version": self._trace_context.get("concern_version"),
            "selected_concern_id": selected_concern_id,
            "retrieved_source_refs": retrieved_source_refs,
            "auto_recorded_evidence_refs": auto_recorded_evidence_refs,
            "model_concern_updates": model_concern_updates,
            "accepted_concern_patches": accepted_patches,
            "rejected_concern_patches": rejected_patches,
            "action_evidence_refs": action_evidence_refs,
            "receipt": receipt,
            "persisted_concern_version": persisted_version,
            # Keep the audit contract readable by external evaluators that use
            # the camelCase names from the design doc.
            "selectedConcernId": selected_concern_id,
            "retrievedSourceRefs": retrieved_source_refs,
            "autoRecordedEvidenceRefs": auto_recorded_evidence_refs,
            "modelConcernUpdates": model_concern_updates,
            "acceptedConcernPatches": accepted_patches,
            "rejectedConcernPatches": rejected_patches,
            "actionEvidenceRefs": action_evidence_refs,
            "persistedVersion": persisted_version,
            "path_id": self._trace_context.get("path_id"),
            "branch_reason_ref": f"trace.{payload.get('kind', 'unknown')}",
            "callsite": self._callsite(),
            **payload,
        }
        trace_id = self.store.trace(owner, event_id, step, trace_payload)
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        with self.trace_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"trace_id": trace_id, "owner": owner, "event_id": event_id, "step": step, **trace_payload}, ensure_ascii=False) + "\n")
        return trace_id

    def _finish(self, event: dict[str, Any], result: dict[str, Any], *, branch_reason_ref: str) -> dict[str, Any]:
        """Bind the actual route to evidence after code has chosen it.

        The route is derived from the completed controller result and is
        written after the decision/tool/sink work.  It is therefore an audit
        fact, not a hidden scenario answer or a prompt instruction.
        """
        self._trace_context.update({
            "path_id": result.get("path_id"),
            "intention_id": result.get("intention_id", self._trace_context.get("intention_id")),
            "action_id": result.get("action_id", self._trace_context.get("action_id")),
            "concern_id": result.get("concern_id", self._trace_context.get("concern_id")),
            "concern_version": result.get("concern_version", self._trace_context.get("concern_version")),
        })
        self._trace(event["owner"], event["event_id"], 1000, {
            "kind": "path_assignment",
            "path_id": result.get("path_id"),
            "branch_reason_ref": branch_reason_ref,
            "status": result.get("status"),
            "callsite": self._callsite(),
        })
        return result

    @staticmethod
    def _retryable_provider_error(error: str | None) -> bool:
        if not error:
            return False
        value = error.lower()
        if any(token in value for token in ("timeout", "timedout", "connection", "urlerror", "temporar")):
            return True
        if value.startswith("http_"):
            try:
                code = int(value.split("_", 1)[1])
            except (IndexError, ValueError):
                return False
            return code == 408 or code == 429 or code >= 500
        return False

    @staticmethod
    def _source_refs(value: Any) -> set[str]:
        """Collect only explicit source references from worker-visible data."""
        refs: set[str] = set()
        if isinstance(value, dict):
            for key in ("source_ref", "source_refs", "backing_source"):
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    refs.add(candidate.strip())
                elif isinstance(candidate, list):
                    refs.update(str(item).strip() for item in candidate if isinstance(item, str) and item.strip())
            for item in value.values():
                refs.update(AgencyLoop._source_refs(item))
        elif isinstance(value, list):
            for item in value:
                refs.update(AgencyLoop._source_refs(item))
        return refs

    def _provider_call(self, owner: str, event: dict[str, Any], prompt: dict[str, Any], step: int) -> ProviderResponse:
        continuation_meta = (event.get("payload") or {}).get("continuation_equivalent")
        single_provider_call = isinstance(continuation_meta, dict) and continuation_meta.get("single_provider_call") is True
        for attempt in range(1, 4):
            self.policy.consume(owner, "model")
            response = self.gateway.complete(prompt, attempt=attempt)
            raw_dir = self.trace_path.parent / "raw-responses"
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_path = raw_dir / f"{response.request_id}.json"
            raw_payload = {
                "request_id": response.request_id, "model": response.model, "attempt": attempt,
                "content": response.content, "finish_reason": response.finish_reason, "usage": response.usage,
                "latency_ms": response.latency_ms, "error": response.error,
            }
            # Provider request ids are expected to be unique.  Exclusive create
            # keeps a repeated/buggy id from overwriting an earlier response.
            try:
                with raw_path.open("x", encoding="utf-8") as stream:
                    stream.write(json.dumps(raw_payload, ensure_ascii=False, indent=2, default=str) + "\n")
            except FileExistsError:
                raw_path = raw_dir / f"{response.request_id}-{uuid.uuid4().hex[:8]}.json"
                with raw_path.open("x", encoding="utf-8") as stream:
                    stream.write(json.dumps(raw_payload, ensure_ascii=False, indent=2, default=str) + "\n")
            self._trace(owner, event["event_id"], step, {
                "kind": "provider_call", "attempt": attempt,
                "model": response.model, "request_id": response.request_id, "prompt": prompt,
                "raw_response": response.content, "raw_response_ref": str(raw_path),
                "raw_response_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                "finish_reason": response.finish_reason, "usage": response.usage,
                "latency_ms": response.latency_ms, "error": response.error,
            })
            if response.error and single_provider_call and self._retryable_provider_error(response.error):
                self._trace(owner, event["event_id"], step, {"kind": "provider_retry_disabled", "attempt": attempt, "error": response.error, "reason": "single_provider_call"})
            if not response.error or attempt == 3 or single_provider_call or not self._retryable_provider_error(response.error):
                return response
            try:
                self.policy.consume(owner, "retry")
            except PolicyError as exc:
                self._trace(owner, event["event_id"], step, {"kind": "provider_retry_blocked", "attempt": attempt, "error": str(exc)})
                return response
        raise RuntimeError("provider_call_loop_unreachable")

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
        self._trace_context = {
            "entry_kind": event["kind"],
            "event_version": event_version,
            "intention_id": None,
            "action_id": None,
            "concern_id": None,
            "concern_version": None,
            "path_id": None,
            "selected_concern_id": None,
            "retrieved_source_refs": [],
            "auto_recorded_evidence_refs": [],
            "model_concern_updates": [],
            "accepted_concern_patches": [],
            "rejected_concern_patches": [],
            "action_evidence_refs": [],
            "receipt": None,
        }
        # Model/tool limits protect one decision cycle.  Keeping the counters
        # across unrelated later events made a valid four-turn conversation
        # fail merely because earlier turns used tools.
        self.store.configure_budget(owner, reset=True)
        self.store.seed_tasks(owner, self.context_builder.owner_data(owner).get("tasks", []))
        self._trace(owner, event["event_id"], 0, {"kind": "input", "input": event, "event_version": event_version})
        try:
            # A confirmation is a trusted controller-level event annotation,
            # never a model action argument.  The annotation is optional and
            # only records an explicit accepted/rejected user event.
            confirmation = event["payload"].get("user_confirmation")
            if isinstance(confirmation, dict) and confirmation.get("candidate_id") and isinstance(confirmation.get("accepted"), bool):
                self.store.record_user_confirmation(
                    owner,
                    str(confirmation["candidate_id"]),
                    event["event_id"],
                    str(event["payload"].get("text", "")),
                    bool(confirmation["accepted"]),
                )
                self._trace(owner, event["event_id"], 0, {"kind": "user_confirmation", "candidate_id": confirmation["candidate_id"], "accepted": confirmation["accepted"]})
            if event["kind"] == "silence_observed":
                latest = self.store.latest_action(owner)
                if latest:
                    self.store.record_feedback(owner, latest["action_id"], "silence_observed", "none", "", event["payload"])
                self._trace(owner, event["event_id"], 1, {"kind": "silence_observed", "action_id": latest["action_id"] if latest else None})
                return self._finish(event, {"status": "observed", "event_id": event["event_id"], "path_id": "P15", "action_id": latest["action_id"] if latest else None}, branch_reason_ref="silence_observed.feedback_recorded")
            return self._decision_cycle(event, thread_id, event_version)
        except (ContractError, ContextError, PolicyError, AdapterError, StoreError) as exc:
            self._trace(owner, event["event_id"], 999, {"kind": "failure", "error": type(exc).__name__, "message": str(exc)})
            return self._finish(event, {"status": "failed", "event_id": event["event_id"], "path_id": "P13", "error": type(exc).__name__, "message": str(exc)}, branch_reason_ref="loop.controller_exception")
        finally:
            self.store.release_lease(owner, lease_id)
            self._trace_context = {}

    def _apply_concern_delta(
        self,
        event: dict[str, Any],
        decision: dict[str, Any],
        *,
        action_id: str | None = None,
        context: dict[str, Any] | None = None,
        tool_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Apply the model delta and resolve only server-owned references."""
        owner = event["owner"]
        updates = decision.get("concern_updates", [])
        concern_ref = decision.get("concern_ref")
        task_ref = decision.get("task_ref")
        if updates and not self.policy.concerns_enabled:
            result = {
                "accepted": [],
                "rejected": [{"concern_ref": item.get("concern_ref"), "reason": "concerns_arm_disabled", "operation": item.get("operation")} for item in updates],
                "ref_map": {},
                "rejected_refs": [str(item.get("concern_ref", "")) for item in updates],
            }
        else:
            self.policy.check_concern_updates(updates)
            result = self.store.apply_concern_updates(
                owner,
                event["event_id"],
                updates,
                action_id=action_id,
                explicit_user_goal=bool((event.get("payload") or {}).get("explicit_goal")),
                max_active=12,
                allowed_source_refs=self._source_refs(context) | self._source_refs(tool_result),
            )
        resolved_concern_id = None
        concern_version = None
        if concern_ref:
            dependency_rejected = concern_ref in result.get("rejected_refs", [])
            resolved_concern_id = result.get("ref_map", {}).get(concern_ref, concern_ref)
            concern = self.store.get_concern(owner, resolved_concern_id) if not dependency_rejected else None
            if concern is None and not dependency_rejected:
                raise PolicyError("unknown_concern_or_owner")
            concern_version = concern["version"] if concern is not None else None
        task_id = None
        if task_ref:
            task_id = task_ref
            if not any(item.get("id") == task_ref for item in self.store.read_tasks(owner)):
                raise PolicyError("unknown_task_or_owner")
        if result.get("rejected"):
            self._trace(owner, event["event_id"], 3, {"kind": "concern_patch_rejected", "result": result})
        self._trace_context["model_concern_updates"] = deepcopy(updates)
        self._trace_context["accepted_concern_patches"] = deepcopy(result.get("accepted", []))
        self._trace_context["rejected_concern_patches"] = deepcopy(result.get("rejected", []))
        return {"result": result, "concern_id": resolved_concern_id, "concern_version": concern_version, "task_id": task_id, "dependency_rejected": bool(concern_ref and concern_ref in result.get("rejected_refs", []))}

    def _decision_cycle(self, event: dict[str, Any], thread_id: str, event_version: int) -> dict[str, Any]:
        owner = event["owner"]
        thread = self.store.get_thread(owner)
        thread_state = dict(thread) if thread else {}
        thread_state["delivered_segments"] = self.store.delivered_segments(owner)
        continuation_meta = (event.get("payload") or {}).get("continuation_equivalent")
        compact_continuation = isinstance(continuation_meta, dict) and continuation_meta.get("mode") == "evidence_already_retrieved"
        if compact_continuation:
            context = self.context_builder.build_compact_continuation(event, thread_state=thread_state)
        else:
            context = self.context_builder.build(event, thread_state=thread_state)
        selected_ids = [item.get("id") for item in (context.get("concerns", {}).get("selected", []) or []) if item.get("id")]
        self._trace_context["selected_concern_id"] = selected_ids[0] if selected_ids else None
        prompt = assemble_compact_continuation(context) if compact_continuation else assemble(context, event=event)
        first = self._provider_call(owner, event, prompt, 1)
        if first.error:
            return self._finish(event, {"status": "infra_failure", "event_id": event["event_id"], "error": first.error, "path_id": "P13"}, branch_reason_ref="provider.first_call_error")
        if compact_continuation:
            proposal, proposal_audit = parse_and_validate_semantic_proposal(first.content)
            self._trace(owner, event["event_id"], 2, {"kind": "semantic_proposal_parse", "raw_response": first.content, "repair_type": proposal_audit.get("repair_type"), "validation_result": proposal_audit.get("validation_result"), "parse_audit": proposal_audit})
            if proposal is None:
                error = str(proposal_audit.get("error") or "semantic_proposal_schema_invalid")
                self._trace(owner, event["event_id"], 2, {"kind": "semantic_proposal_rejected", "stage": "parse", "raw_response": first.content, "error": error, "proposal_audit": proposal_audit})
                return self._finish(event, {"status": "schema_failure", "event_id": event["event_id"], "path_id": "P13", "error": error}, branch_reason_ref="provider.semantic_proposal_schema_invalid")
            try:
                compiled = compile_semantic_proposal(proposal, context=context, owner=owner)
            except SemanticProposalError as exc:
                self._trace(owner, event["event_id"], 2, {"kind": "semantic_proposal_rejected", "stage": "compile", "validated_proposal": proposal, "error": str(exc), "compiled_concern_patch": None})
                return self._finish(event, {"status": "schema_failure", "event_id": event["event_id"], "path_id": "P13", "error": str(exc)}, branch_reason_ref="provider.semantic_proposal_compile_rejected")
            decision = compiled["decision"]
            parse_audit = {"proposal_audit": proposal_audit, "validation_result": "passed", "repair_type": "none", "semantic_proposal": True}
            self._trace(owner, event["event_id"], 2, {"kind": "semantic_proposal_compiled", "validated_proposal": compiled["validated_proposal"], "compiled_concern_patch": compiled["compiled_concern_patch"], "decision": decision, "allowed_evidence_refs": compiled["allowed_evidence_refs"], "expected_version": compiled["expected_version"], "grounding": compiled["grounding"]})
        else:
            decision, parse_audit = parse_and_validate_decision(first.content)
        self._trace(owner, event["event_id"], 2, {"kind": "decision_parse", "raw_response": first.content, "repair_type": parse_audit.get("repair_type"), "validation_result": parse_audit.get("validation_result"), "parse_audit": parse_audit})
        if decision is None:
            error = str(parse_audit.get("error") or "decision_schema_invalid")
            self._trace(owner, event["event_id"], 2, {"kind": "schema_failure", "raw_response": first.content, "error": error, "repair_type": parse_audit.get("repair_type"), "validation_result": parse_audit.get("validation_result")})
            return self._finish(event, {"status": "schema_failure", "event_id": event["event_id"], "path_id": "P13", "error": error}, branch_reason_ref="provider.first_response_schema_invalid")
        decision, grounding = repair_decision(decision, context=context)
        if grounding.get("repaired"):
            self._trace(owner, event["event_id"], 2, {"kind": "grounding_repair", "stage": "initial_decision", "assessment": grounding})
        action = decision["action"]
        action_type = action["type"]
        self.policy.check_action(owner, event, action, thread_version=event_version)
        action_args, arg_diff = normalize_action_args(action_type, action.get("args", {}))
        intention = None
        if decision["intention_ref"]:
            intention = self.store.get_intention(decision["intention_ref"], owner)
            if not intention:
                raise PolicyError("unknown_intention_or_owner")
        action_id = None
        with self.store.transaction():
            concern_info = self._apply_concern_delta(event, decision, context=context)
            concern_id, concern_version, task_id = concern_info["concern_id"], concern_info["concern_version"], concern_info["task_id"]
            if concern_info["dependency_rejected"]:
                intention_id = None
                intention_version = None
            elif intention is None:
                intention_id = self.store.create_intention(
                    owner,
                    thread_id,
                    decision["desired_change"],
                    action_type == "wait",
                    concern_id=concern_id,
                    task_id=task_id,
                    concern_version=concern_version,
                )
                intention_version = 0
            else:
                intention_id = intention["intention_id"]
                intention_version = intention["version"]
                if concern_id and intention["concern_id"] not in (None, concern_id):
                    raise PolicyError("intention_concern_mismatch")
                if task_id and intention["task_id"] not in (None, task_id):
                    raise PolicyError("intention_task_mismatch")
            if not concern_info["dependency_rejected"]:
                action_id = self.store.create_action(owner, intention_id, event["event_id"], action_type, action_args, event_version)
        if concern_info["dependency_rejected"]:
            raise PolicyError("concern_patch_rejected_dependency")
        self._trace_context.update({"intention_id": intention_id, "action_id": action_id})
        self._trace_context.update({"concern_id": concern_id, "concern_version": concern_version})
        if concern_id:
            self._trace_context["selected_concern_id"] = concern_id
        self._trace(owner, event["event_id"], 3, {"kind": "decision", "decision": decision, "intention_id": intention_id, "action_id": action_id, "concern_result": concern_info["result"], "argument_diff": arg_diff})
        if action_type == "wait":
            self.policy.validate_wait(decision["reconsider_condition"])
            self.store.update_action(action_id, owner, "prepared", {"reconsider_condition": decision["reconsider_condition"]})
            self.store.update_intention(intention_id, owner, intention_version, "active", True)
            return self._finish(event, {"status": "waiting", "event_id": event["event_id"], "path_id": "P12", "intention_id": intention_id, "action_id": action_id}, branch_reason_ref="decision.wait_with_valid_reconsider_condition")
        if action_type == "none":
            self.store.update_action(action_id, owner, "prepared", {"operation": decision["operation"]})
            path_id = "P03" if event["kind"] == "user_message" else "P05"
            return self._finish(event, {"status": "prepared", "event_id": event["event_id"], "path_id": path_id, "intention_id": intention_id, "action_id": action_id}, branch_reason_ref="decision.none_without_action")
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
        retrieved_refs = sorted(self._source_refs(result))
        self._trace_context["retrieved_source_refs"] = retrieved_refs
        evidence_available = result.get("status") == "complete" and result.get("data") not in (None, {}, [], "")
        self._trace_context["action_evidence_refs"] = retrieved_refs if evidence_available else []
        self._trace(owner, event["event_id"], 4, {"kind": "tool_result", "action_id": action_id, "tool_type": action_type, "result": result})
        concern_id = self._trace_context.get("concern_id")
        if concern_id:
            with self.store.transaction():
                self._trace_context["concern_version"] = self.store.record_concern_tool_evidence(
                    owner,
                    concern_id,
                    event["event_id"],
                    action_id,
                    tool_type=action_type,
                    result=result,
                )
                self._trace_context["auto_recorded_evidence_refs"] = list(self._trace_context["action_evidence_refs"])
        next_context = self.context_builder.build(event, thread_state={}, related_tool_result=result)
        second = self._provider_call(owner, event, assemble(next_context, event=event, tool_result=result), 5)
        if second.error:
            return self._finish(event, {"status": "infra_failure", "event_id": event["event_id"], "path_id": "P13", "intention_id": intention_id, "action_id": action_id, "error": second.error}, branch_reason_ref="provider.continuation_call_error")
        next_decision, parse_audit = parse_and_validate_decision(second.content)
        self._trace(owner, event["event_id"], 5, {"kind": "decision_parse", "raw_response": second.content, "repair_type": parse_audit.get("repair_type"), "validation_result": parse_audit.get("validation_result"), "parse_audit": parse_audit})
        if next_decision is None:
            error = str(parse_audit.get("error") or "decision_schema_invalid")
            return self._finish(event, {"status": "schema_failure", "event_id": event["event_id"], "path_id": "P13", "intention_id": intention_id, "action_id": action_id, "error": error, "repair_type": parse_audit.get("repair_type")}, branch_reason_ref="provider.continuation_response_schema_invalid")
        next_decision, grounding = repair_decision(next_decision, context=next_context, tool_result=result)
        if grounding.get("repaired"):
            self._trace(owner, event["event_id"], 5, {"kind": "grounding_repair", "stage": "tool_continuation", "assessment": grounding})
        with self.store.transaction():
            second_concern_info = self._apply_concern_delta(event, next_decision, action_id=action_id, context=next_context, tool_result=result)
            if second_concern_info["concern_id"] and second_concern_info["concern_id"] != self._trace_context.get("concern_id"):
                second_concern_info["mismatch"] = True
            if second_concern_info["concern_id"]:
                self._trace_context["concern_version"] = second_concern_info["concern_version"]
        if second_concern_info.get("dependency_rejected"):
            raise PolicyError("concern_patch_rejected_dependency")
        if second_concern_info.get("mismatch"):
            raise PolicyError("continuation_concern_mismatch")
        self._trace(owner, event["event_id"], 5, {"kind": "continuation_decision", "decision": next_decision, "concern_result": second_concern_info["result"]})
        if next_decision["action"]["type"] != "deliver":
            if next_decision["action"]["type"] == "wait":
                self.store.update_intention(intention_id, owner, intention_version, "active", True)
                return self._finish(event, {"status": "waiting", "event_id": event["event_id"], "path_id": "P12", "intention_id": intention_id, "action_id": action_id}, branch_reason_ref="continuation.wait_after_tool")
            path_id = "P13" if result["status"] != "complete" else "P02"
            reason = "continuation.no_delivery_after_incomplete_tool" if result["status"] != "complete" else "continuation.no_delivery_after_complete_tool"
            return self._finish(event, {"status": "prepared", "event_id": event["event_id"], "path_id": path_id, "intention_id": intention_id, "action_id": action_id, "tool_status": result["status"]}, branch_reason_ref=reason)
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
            receipt = self.sink.deliver_text(
                owner=owner,
                event_version=event_version,
                action_id=action_id,
                segment_id=segment_id,
                text=message,
                trace_context={
                    "entry_kind": self._trace_context.get("entry_kind"),
                    "event_id": event["event_id"],
                    "intention_id": intention_id,
                    "path_id": None,
                    "branch_reason_ref": "sink.delivery_attempt",
                },
            )
            with self.store.transaction():
                self.store.record_receipt(owner, action_id, receipt)
                if self._trace_context.get("concern_id") and receipt.get("status") == "delivered":
                    self._trace_context["concern_version"] = self.store.record_concern_contact(
                        owner,
                        self._trace_context["concern_id"],
                        event["event_id"],
                        action_id,
                        str(receipt.get("idempotency_key") or receipt.get("segment_id")),
                    )
            receipts.append(receipt)
        self._trace_context["receipt"] = deepcopy(receipts)
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
        self._trace_context.update({"intention_id": intention_id, "action_id": action_id})
        self._trace(owner, event["event_id"], 6, {"kind": "delivery", "action_id": action_id, "final_state": final_state, "receipts": receipts})
        result = {"status": final_state, "event_id": event["event_id"], "path_id": path_id, "intention_id": intention_id, "action_id": action_id, "concern_id": self._trace_context.get("concern_id"), "concern_version": self._trace_context.get("concern_version"), "receipts": receipts}
        reason = {
            "P03": "sink.all_segments_delivered",
            "P11": "sink.tool_continuation_all_segments_delivered",
            "P14": "sink.delivery_partial_unknown_or_failed",
        }[path_id]
        return self._finish(event, result, branch_reason_ref=reason)
