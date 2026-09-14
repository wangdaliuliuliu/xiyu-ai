"""Machine-checkable C06 requirement and execution manifests.

The manifest describes the denominator and branch semantics.  It contains no
expected answers and is safe to hand to the worker.  ``status=not_run`` is an
honest execution state, not a placeholder branch.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import pathlib
from typing import Any

from evaluation.scenarios import (
    continuity_spec,
    holdout_spec,
    integration_spec,
    media_spec,
    performance_spec,
    reliability_spec,
    scenario_spec,
)


GOALS = {
    "G01": ("desire changes appraisal while facts remain stable", "stable-facts-desire-shift"),
    "G02": ("model-selected action parameters reach the actual tool", "model-selected-parameters"),
    "G03": ("professional and personal expression coexist", "work-personal-coexistence"),
    "G04": ("concrete initiative under low response", "low-response-concrete-initiative"),
    "G05": ("persona fiction supports interaction without becoming user fact", "persona-fiction-user-fact-firewall"),
    "G06": ("scoped fresh business facts are used", "scoped-fresh-business-fact"),
    "G07": ("enterprise background affects analysis", "enterprise-background-analysis"),
    "G08": ("knowledge moves candidate to confirmed only after consent", "knowledge-consent-roundtrip"),
    "G09": ("understood goal leads to independent preparation", "goal-to-independent-preparation"),
    "G10": ("dated research becomes an executable isolated task", "dated-research-to-task"),
    "G11": ("media is a strategy branch rather than an obligatory output", "media-as-strategy-branch"),
    "G12": ("continuity survives delivery and restart", "delivery-restart-continuity"),
    "G13": ("feedback is evidence, not blind learning", "feedback-source-trace"),
    "G14": ("one maintainable and migratable formal path", "single-maintainable-path"),
}


FAMILIES = {
    "A01": "dated-store-metric-routing",
    "A02": "unknown-metric-short-answer-update",
    "A03": "low-cost-high-cost-branches",
    "A04": "three-opportunities-without-data-change",
    "A05": "dated-research-to-execution",
    "A06": "same-period-conflicting-sources",
    "B01": "new-relationship-two-compliant-opportunities",
    "B02": "persona-baking-to-teasing-continuation",
    "B03": "two-day-silence-bounded-recontact",
    "B04": "completed-personal-matter-joins-decision",
    "B05": "topic-refusal-preserves-other-interaction",
    "B06": "weather-with-and-without-photo-context",
    "C01": "fatigue-but-explicit-business-query",
    "C02": "personal-to-sales-to-photo-recovery",
    "C03": "short-acknowledgement-to-merchant-clarification",
    "C04": "due-business-commitment-vs-personal-opportunity",
    "C05": "temporary-budget-scoped-to-project",
    "C06": "failed-plan-plus-new-staff-constraint",
    "D01": "restart-before-sending-after-sending-after-delivery",
    "D02": "timeout-404-401-and-follow-up",
    "D03": "v1-background-v2-user-version-conflict",
    "D04": "desire-vs-neutral-task-only-desire-differs",
    "D05": "same-intention-media-available-unavailable",
    "D06": "two-owner-budget-and-malformed-json",
}


FAMILY_BRANCHES = {
    "A01": [("date-store-metric", "date/store/metric supplied by user; exact query required"), ("missing-date", "date omitted; no runner default allowed"), ("wrong-owner", "same query under another owner; scope must reject")],
    "A02": [("unknown-metric", "metric definition unavailable; ask one targeted question"), ("short-answer", "user supplies the missing merchant meaning"), ("updated-judgement", "same intention is reevaluated using the answer")],
    "A03": [("low-cost", "low cost source is available"), ("high-cost", "high cost source requires bounded preparation"), ("cost-unknown", "cost cannot be inferred and remains explicit")],
    "A04": [("opportunity-one", "first opportunity has no data change"), ("opportunity-two", "second opportunity has no data change"), ("opportunity-three", "third opportunity revises strategy without claiming user preference")],
    "A05": [("dated-source", "FROZEN research result has source date"), ("applicable-condition", "recommendation retains applicability condition"), ("isolated-task", "execution task is written only to experiment store")],
    "A06": [("conflict-preserved", "two sources disagree and result is conflict"), ("source-compare", "source references remain separately addressable"), ("safe-followup", "unknown conflict resolution becomes a question")],
    "B01": [("new-relationship-one", "cold relationship receives first compliant opportunity"), ("new-relationship-two", "second opportunity respects participation"), ("no-shared-history", "shared history is absent from cold-start context")],
    "B02": [("persona-context", "P1 behavior example is in versioned prompt"), ("teasing", "teasing continues with personal choice"), ("no-user-fact-invention", "assistant fiction cannot enter user history")],
    "B03": [("silence-day-one", "delivery receipt then virtual day-one silence"), ("silence-day-two", "second silence records observation only"), ("bounded-recontact", "upper window prepares but does not send")],
    "B04": [("personal-complete", "own role matter reaches completed state"), ("decision-participation", "next interaction offers a decision"), ("no-fake-receipt", "completion is backed by sink receipt")],
    "B05": [("topic-refusal", "user explicitly refuses one philosophy topic"), ("scope-preserved", "refusal scope is local, not global"), ("other-interaction", "another allowed topic remains possible")],
    "B06": [("weather-photo", "weather context with available photo branch"), ("weather-text", "weather context without photo branch"), ("photo-cancel", "photo preparation cancellation resumes text intention")],
    "C01": [("fatigue-then-work", "fatigue persona state cannot block explicit work query"), ("business-first", "business answer is completed before personal continuation"), ("personal-boundary", "personal state remains fiction, not enterprise fact")],
    "C02": [("personal-to-sales", "personal exchange is followed by sales request"), ("photo-prepared", "photo is prepared for same intention"), ("work-insert-recovery", "work insertion invalidates stale personal asset and rechecks recovery")],
    "C03": [("short-ack", "short acknowledgement is not knowledge confirmation"), ("clarify-merchant", "merchant scope is clarified by explicit user text"), ("confirmed-reuse", "confirmed knowledge changes a later retrieval")],
    "C04": [("due-work", "due business commitment is visible"), ("personal-opportunity", "personal opportunity competes without deleting due work"), ("priority-recovery", "later event resumes the correct intention")],
    "C05": [("budget-project-a", "temporary budget is scoped to project A"), ("switch-project", "budget is not generalized to project B"), ("budget-exhaustion", "last quota is explicit and no silent overrun occurs")],
    "C06": [("failed-plan", "previous plan is recorded as failed"), ("new-staff-constraint", "new constraint changes preparation"), ("revised-plan", "new plan cites the new constraint")],
    "D01": [("restart-before-send", "prepared state survives restart without delivery"), ("restart-during-send", "sending without receipt restores unknown"), ("restart-after-delivery", "delivered segment is not resent")],
    "D02": [("provider-timeout", "timeout remains infra failure"), ("provider-404", "404 remains provider failure"), ("provider-401-followup", "auth failure is not hidden by a user-facing success")],
    "D03": [("background-old-version", "background action retains old version"), ("user-new-version", "user event increments version"), ("cas-rejection", "old action cannot deliver over new input")],
    "D04": [("desire-present", "P1 desire is the only changed block"), ("neutral-task", "neutral task keeps same facts and capability"), ("difference-isolated", "comparison attributes output difference only to desire block")],
    "D05": [("media-available", "same intention may use a prepared asset"), ("media-unavailable", "same intention falls back to text"), ("no-new-intention", "fallback retains original intention")],
    "D06": [("two-owner", "owner data and candidates stay isolated"), ("budget-exhausted", "budget refusal is recorded"), ("malformed-json", "schema failure preserves raw response")],
}


RELIABILITY = {
    f"R{i:02d}": description for i, description in enumerate([
        "duplicate event is idempotent", "lease conflict is rejected", "thread version CAS is enforced", "tool failure retains explicit status",
        "delivery partial state is preserved", "delivery unknown waits for receipt query", "restart reads durable state", "candidate is not confirmed by model args",
        "owner scope rejects cross-account access", "future schedule is not visible", "budget counts retries and calls", "trace and raw response are append-only",
    ], 1)
}


INTEGRATIONS = {
    f"I{i:02d}": description for i, description in enumerate([
        "cold-start relationship", "enterprise background discovery", "dated business query", "photo preparation and recovery",
        "knowledge candidate and confirmation", "personal continuation", "free media choice", "business insertion into personal thread",
        "silence and opportunity revision", "feedback and memory source", "seven-day virtual continuity", "restart/concurrency recovery",
    ], 1)
}


RELIABILITY_BRANCHES = {
    "R01": "duplicate-event-idempotency", "R02": "lease-conflict", "R03": "thread-version-cas",
    "R04": "tool-failure-state", "R05": "partial-delivery-state", "R06": "unknown-delivery-receipt",
    "R07": "restart-durable-read", "R08": "confirmation-permission", "R09": "owner-scope",
    "R10": "future-schedule-visibility", "R11": "budget-retry-accounting", "R12": "append-only-trace-response",
}


PATH_BRANCH_REFS = {
    "P01": ["A01-date-store-metric", "C01-fatigue-then-work"],
    "P02": ["A05-dated-source", "C06-revised-plan"],
    "P03": ["B01-new-relationship-one", "B02-persona-context", "C01-fatigue-then-work"],
    "P04": ["C02-personal-to-sales", "C04-due-work"],
    "P05": ["A04-opportunity-one", "B03-silence-day-one"],
    "P06": ["A01-missing-date", "C04-due-work"],
    "P07": ["A02-unknown-metric", "C03-short-ack"],
    "P08": ["A02-short-answer", "C03-confirmed-reuse"],
    "P09": ["A05-dated-source", "A06-conflict-preserved"],
    "P10": ["B06-weather-photo", "D05-media-available"],
    "P11": ["C02-photo-prepared", "D05-no-new-intention"],
    "P12": ["B03-bounded-recontact", "D01-restart-before-send"],
    "P13": ["D02-provider-timeout", "D02-provider-401-followup", "D06-malformed-json"],
    "P14": ["D01-restart-during-send", "D03-cas-rejection"],
    "P15": ["B03-silence-day-two", "A04-opportunity-three"],
    "P16": ["C02-work-insert-recovery", "C04-priority-recovery"],
    "P17": ["B05-topic-refusal", "B05-other-interaction"],
    "P18": ["D01-restart-after-delivery", "D03-background-old-version", "D06-two-owner"],
}

PATH_INTEGRATION_REFS = {
    "P01": ["I03-dated-business-query"], "P02": ["I02-enterprise-background-discovery"],
    "P03": ["I01-cold-start-relationship", "I06-personal-continuation"],
    "P04": ["I08-business-insertion"], "P05": ["I09-opportunity-revision"],
    "P06": ["I03-dated-business-query"], "P07": ["I05-knowledge-confirmation"],
    "P08": ["I05-knowledge-confirmation"], "P09": ["I02-enterprise-background-discovery"],
    "P10": ["I07-free-media-choice"], "P11": ["I07-free-media-choice"],
    "P12": ["I11-seven-day-continuity"], "P13": ["I03-dated-business-query"],
    "P14": ["I12-restart-concurrency"], "P15": ["I09-opportunity-revision"],
    "P16": ["I08-business-insertion"], "P17": ["I10-topic-boundary"],
    "P18": ["I12-restart-concurrency"],
}

PATH_RELIABILITY_REFS = {
    "P01": ["R09-owner-scope"], "P02": ["R04-tool-failure-state"],
    "P03": ["R09-owner-scope"], "P04": ["R03-thread-version-cas"],
    "P05": ["R01-duplicate-event-idempotency"], "P06": ["R07-restart-durable-read"],
    "P07": ["R08-confirmation-permission"], "P08": ["R08-confirmation-permission"],
    "P09": ["R04-tool-failure-state"], "P10": ["R04-tool-failure-state"],
    "P11": ["R05-partial-delivery-state"], "P12": ["R10-future-schedule-visibility"],
    "P13": ["R11-budget-retry-accounting"], "P14": ["R06-unknown-delivery-receipt"],
    "P15": ["R01-duplicate-event-idempotency"], "P16": ["R03-thread-version-cas"],
    "P17": ["R09-owner-scope"], "P18": ["R02-lease-conflict", "R03-thread-version-cas", "R07-restart-durable-read"],
}


def _model_slots(model_labels: list[str] | None) -> list[dict[str, Any]]:
    """Keep the second-model denominator even when its label is missing."""
    labels = list(model_labels or [])
    count = max(2, len(labels))
    models = []
    for index in range(count):
        role = "primary" if index == 0 else ("second" if index == 1 else f"additional-{index + 1}")
        label = labels[index] if index < len(labels) else None
        models.append({"role": role, "label": label, "status": "declared_unverified" if label else "unverified"})
    return models


def _manifest_requirements(run_root: str, source_kind: str, owner_scope: Any) -> dict[str, Any]:
    mutation_ids = [f"M{i:02d}" for i in range(1, 17)] + [f"X{i:02d}" for i in range(1, 25)]
    return {
        "goals": [{"id": key, "requirement": value, "branch_id": branch, "status": "not_run", "evidence_dir": f"{run_root}/goals/{key}"} for key, (value, branch) in GOALS.items()],
        "families": [{"id": key, "requirement": FAMILIES[key], "branch_id": f"{key}-{branch}", "meaning": meaning, "status": "not_run", "evidence_dir": f"{run_root}/trajectories/fixed/{key}/{branch}"} for key in FAMILIES for branch, meaning in FAMILY_BRANCHES[key]],
        "reliability": [{"id": key, "requirement": RELIABILITY[key], "branch_id": f"{key}-{RELIABILITY_BRANCHES[key]}", "status": "not_run", "formal_path": "runtime/store.py -> runtime/loop.py", "evidence_dir": f"{run_root}/trajectories/reliability/{key}"} for key in RELIABILITY],
        "integrations": [{"id": key, "requirement": INTEGRATIONS[key], "branch_id": f"{key}-integration-trajectory", "status": "not_run", "formal_path": "cli.py -> runtime/loop.py -> adapters -> sink", "evidence_dir": f"{run_root}/trajectories/integration/{key}"} for key in INTEGRATIONS],
        "mutations": [{"id": key, "branch_id": f"{key}-formal-mutation-control", "status": "not_run", "formal_path": "evaluation/mutation.py", "worker_visible": False, "evidence_dir": f"{run_root}/mutation-attempts"} for key in mutation_ids],
         "paths": [{"id": f"P{i:02d}", "family_branch_refs": PATH_BRANCH_REFS[f"P{i:02d}"], "integration_refs": PATH_INTEGRATION_REFS[f"P{i:02d}"], "reliability_refs": PATH_RELIABILITY_REFS[f"P{i:02d}"], "status": "not_run", "worker_visible": False, "evidence_dir": f"{run_root}/path-traces/P{i:02d}"} for i in range(1, 19)],
        "owner_scope": owner_scope,
        "oracle": {"worker_visible": False, "location": f"{run_root}/oracle-private", "status": "independent_oracle_required"},
        "source_kind": source_kind,
    }


def build_requirement_map(*, evidence_root: str | None = None) -> dict[str, Any]:
    return {
        "schemaVersion": "requirement-map-v3",
        "createdAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "goals": {key: {"requirement": value, "fixture_branches": [branch], "status": "not_run", "evidence": []} for key, (value, branch) in GOALS.items()},
        "families": {key: {"requirement": requirement, "branches": [{"branch_id": f"{key}-{branch}", "meaning": meaning, "status": "not_run", "evidence": []} for branch, meaning in FAMILY_BRANCHES[key]], "status": "not_run", "evidence": []} for key, requirement in FAMILIES.items()},
        "reliability": {key: {"requirement": value, "branch_id": f"{key}-{RELIABILITY_BRANCHES[key]}", "status": "not_run", "evidence": []} for key, value in RELIABILITY.items()},
        "integration": {key: {"requirement": value, "branch_id": f"{key}-integration-trajectory", "status": "not_run", "evidence": []} for key, value in INTEGRATIONS.items()},
        "mutations": {key: {"status": "not_run", "formal_path": "evaluation/mutation.py", "normal_control": None, "failure_evidence": None, "recovery_evidence": None} for key in [f"M{i:02d}" for i in range(1, 17)] + [f"X{i:02d}" for i in range(1, 25)]},
        "work_items": {key: {"status": "not_run", "evidence": [], "next": None} for key in ["C00", "C01", "C02", "C03", "C04", "C05", "C06"]},
        "evidence_root": evidence_root,
    }


def build_execution_manifest(*, run_root: str, source_kind: str, owner_scope: Any, model_labels: list[str] | None = None, arm: str = "A", prompt_path: str | None = None, concerns_enabled: bool = False) -> dict[str, Any]:
    selected_arm = arm
    selected_prompt_path = prompt_path
    models = _model_slots(model_labels)
    entries: list[dict[str, Any]] = []
    for family, requirement in FAMILIES.items():
        for branch, meaning in FAMILY_BRANCHES[family]:
            entries.append({
                "entry_id": f"fixed-{family}-{branch}", "suite": "fixed", "family_id": family, "branch_id": f"{family}-{branch}",
                "meaning": meaning, "input_source": source_kind, "owner_scope": owner_scope, "trajectory": {"min_events": 3, "typical_events": "4-6", "end_condition": "delivered_or_explicit_wait_or_terminal_failure"},
                "repetitions_per_model": 5, "models": models, "scenario": scenario_spec(family, branch, source_kind=source_kind, owner_scope=owner_scope), "expected_behavior_or_oracle": "independent oracle selected by evaluator; not available to worker", "evidence_dir": f"{run_root}/trajectories/fixed/{family}/{branch}", "status": "not_run",
            })
    for scenario, meaning in INTEGRATIONS.items():
        entries.append({
            "entry_id": f"integration-{scenario}", "suite": "integration", "scenario_id": scenario, "branch_id": f"{scenario}-integration-trajectory", "meaning": meaning,
            "input_source": source_kind, "owner_scope": owner_scope, "trajectory": {"min_events": 3, "typical_events": "4-6", "end_condition": "state_and_delivery_trace_complete"},
            "repetitions_per_model": 5, "models": models, "scenario": integration_spec(scenario, source_kind=source_kind, owner_scope=owner_scope), "expected_behavior_or_oracle": "independent oracle selected by evaluator; not available to worker", "evidence_dir": f"{run_root}/trajectories/integration/{scenario}", "status": "not_run",
        })
    smoke_families = ("A01", "A02", "B01", "B02", "C01", "D01")
    for family in smoke_families:
        for branch, meaning in FAMILY_BRANCHES[family]:
            entries.append({
                "entry_id": f"smoke-{family}-{branch}", "suite": "smoke", "family_id": family, "branch_id": f"{family}-{branch}",
                "meaning": meaning, "input_source": source_kind, "owner_scope": owner_scope,
                "trajectory": {"min_events": 3, "typical_events": "4-6", "end_condition": "diagnostic_trace_complete"},
                "repetitions_per_model": 3, "models": models, "scenario": scenario_spec(family, branch, source_kind=source_kind, owner_scope=owner_scope), "expected_behavior_or_oracle": "diagnostic oracle; not available to worker", "evidence_dir": f"{run_root}/trajectories/smoke/{family}/{branch}", "status": "not_run",
            })
    for index in range(1, 13):
        entries.append({
            "entry_id": f"holdout-scenario-{index:02d}", "suite": "holdout", "scenario_id": f"holdout-{index:02d}", "branch_id": f"holdout-{index:02d}-blind",
            "meaning": "frozen holdout scenario; answer remains oracle-private", "input_source": "independent-holdout", "owner_scope": owner_scope,
            "trajectory": {"min_events": 3, "typical_events": "4-6", "end_condition": "blind_score_recorded"}, "scenario": {**holdout_spec(index, owner_scope=owner_scope), "answer_access": "oracle-private", "events_frozen": True}, "repetitions_per_model": 3,
            "models": models, "freeze_before_run": True, "worker_cannot_read_answers": True, "status": "not_run", "evidence_dir": f"{run_root}/trajectories/holdout/{index:02d}",
        })
    for index in range(1, 4):
        entries.append({
            "entry_id": f"media-scenario-{index:02d}", "suite": "media", "scenario_id": f"media-{index:02d}", "branch_id": f"media-{index:02d}-available-unavailable",
            "meaning": "same intention with two asset conditions", "input_source": source_kind, "owner_scope": owner_scope,
            "trajectory": {"min_events": 3, "typical_events": "4-6", "end_condition": "asset_or_text_fallback_trace_complete"}, "asset_conditions": ["available", "unavailable"],
            "requires_human_review": True, "scenario": media_spec(index, owner_scope=owner_scope), "status": "not_run", "evidence_dir": f"{run_root}/trajectories/media/{index:02d}",
        })
    for index in range(1, 4):
        entries.append({
            "entry_id": f"continuity-trajectory-{index:02d}", "suite": "continuity", "scenario_id": f"continuity-{index:02d}", "branch_id": f"continuity-{index:02d}-seven-virtual-days",
            "meaning": "seven virtual days with durable state and delivery continuity", "input_source": source_kind, "owner_scope": owner_scope,
            "trajectory": {"virtual_days": 7, "events_per_day": "multiple", "end_condition": "cross_day_state_and_delivery_trace_complete"}, "scenario": continuity_spec(index, owner_scope=owner_scope), "status": "not_run", "evidence_dir": f"{run_root}/trajectories/continuity/{index:02d}",
        })
    for performance_arm in ("text", "tool", "image"):
        entries.append({
            "entry_id": f"performance-arm-{performance_arm}", "suite": "performance", "scenario_id": f"performance-{performance_arm}", "branch_id": f"performance-{performance_arm}-30-samples",
            "meaning": f"30 comparable samples for {performance_arm} arm", "input_source": source_kind, "minimum_samples": 30,
            "percentile_limit_seconds": {"text": 15, "tool": 60, "image": 180}[performance_arm], "scenario": performance_spec(performance_arm, owner_scope=owner_scope), "status": "not_run", "evidence_dir": f"{run_root}/performance/{performance_arm}",
        })
    for reliability, requirement in RELIABILITY.items():
        entries.append({
            "entry_id": f"reliability-{reliability}", "suite": "reliability", "reliability_id": reliability,
            "branch_id": f"{reliability}-{RELIABILITY_BRANCHES[reliability]}", "meaning": requirement,
            "input_source": "deterministic_control_or_snapshot", "owner_scope": owner_scope,
            "trajectory": {"min_events": 1, "typical_events": "1-4", "end_condition": "invariant_and_recovery_evidence_complete"},
            "repetitions_per_model": 5, "models": models, "scenario": reliability_spec(reliability, source_kind=source_kind, owner_scope=owner_scope), "expected_behavior_or_oracle": "invariant evaluator; no answer fixture", "evidence_dir": f"{run_root}/trajectories/reliability/{reliability}", "status": "not_run",
        })
    prompt_variants = []
    for prompt_version in ("P0", "P1"):
        for background_mode in ("resident", "retrievable"):
            variant_prompt_path = pathlib.Path(__file__).resolve().parents[1] / "runtime" / "prompts" / ("base.json" if prompt_version == "P0" else "p1.json")
            prompt_hash = hashlib.sha256(variant_prompt_path.read_bytes()).hexdigest()
            prompt_variants.append({
                "entry_id": f"prompt-pairing-{prompt_version.lower()}-{background_mode}",
                "suite": "prompt_pairing", "prompt_version": prompt_version, "background_mode": background_mode,
                "prompt_path": str(variant_prompt_path), "prompt_hash": prompt_hash,
                "repetitions": 3, "input_source": source_kind, "owner_scope": owner_scope,
                "scenario": {"input_origin": "snapshot-bound-prompt-pairing", "events": [
                    {"event_role": "initial", "kind": "user_message", "payload": {"text": "固定配对输入：请处理当前请求并说明依据。", "origin": "prompt_pairing_control", "synthetic_user_input": True}},
                    {"event_role": "continuation", "kind": "user_message", "payload": {"text": "请基于上一轮实际结果继续，不补造未提供的事实。", "origin": "prompt_pairing_control", "synthetic_user_input": True}},
                    {"event_role": "boundary-check", "kind": "user_message", "payload": {"text": "请核对当前来源、owner和版本后再决定交付或等待。", "origin": "prompt_pairing_control", "synthetic_user_input": True}},
                ], "model_answers_included": False, "oracle_in_worker": False},
                "expected_behavior_or_oracle": "paired evaluator comparison; no answer fixture in worker",
                "evidence_dir": f"{run_root}/prompt-pairing/{prompt_version}/{background_mode}", "status": "not_run",
            })
    requirements = _manifest_requirements(run_root, source_kind, owner_scope)
    denominators = {
        "fixed": {"cases": 24 * 3, "repetitions_per_model": 5, "models": len(models), "trajectories": 24 * 3 * 5 * len(models)},
        "reliability": {"cases": 12, "repetitions_per_model": 5, "models": len(models), "trajectories": 12 * 5 * len(models)},
        "integration": {"cases": 12, "repetitions_per_model": 5, "models": len(models), "trajectories": 12 * 5 * len(models)},
        "smoke": {"cases": 6 * 3 + 4, "repetitions_per_model": 3, "models": len(models), "trajectories": (6 * 3 + 4) * 3 * len(models)},
        "holdout": {"cases": 12, "repetitions_per_model": 3, "models": len(models), "trajectories": 12 * 3 * len(models)},
        "media": {"cases": 3, "asset_conditions": 2, "assets": 6},
        "continuity": {"trajectories": 3, "virtual_days": 7, "day_steps": 21},
        "performance": {"arms": 3, "minimum_samples_per_arm": 30, "samples": 90},
        "prompt_pairing": {"cells": 4, "repetitions_per_cell": 3, "samples": 12, "rule": "P0/P1 x resident/retrievable background"},
    }
    return {
        "schemaVersion": "execution-manifest-v2",
        "createdAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "runRoot": run_root,
        "source_kind": source_kind,
        "owner_scope": owner_scope,
        "models": models,
        "entries": entries,
        "prompt_variants": prompt_variants,
        "requirements": requirements,
        "denominators": denominators,
        "concern_arm": {"arm": selected_arm, "prompt_path": selected_prompt_path, "concerns_enabled": concerns_enabled, "max_active": 12, "selected_limit": 6, "max_patches": 3, "summary_token_budget": 1500},
        "status": "declared_not_run",
    }
