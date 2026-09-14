"""Coverage matrix generation; every required identifier is explicit."""
from __future__ import annotations

import json
import pathlib
from typing import Any


def required_ids() -> dict[str, list[str]]:
    return {
        "goals": [f"G{i:02d}" for i in range(1, 15)],
        "families": [f"{group}{i:02d}" for group in "ABCD" for i in range(1, 7)],
        "reliability": [f"R{i:02d}" for i in range(1, 13)],
        "integration": [f"I{i:02d}" for i in range(1, 13)],
        "mutations": [f"M{i:02d}" for i in range(1, 17)] + [f"X{i:02d}" for i in range(1, 25)],
    }


def build_coverage(*, evidence_root: str | None = None) -> dict[str, Any]:
    matrix = {}
    for group, ids in required_ids().items():
        matrix[group] = {
            item: {"status": "not_run", "normal": [], "failure": [], "recovery": [], "evidence": []}
            for item in ids
        }
    path_semantics = {
        "P01": ("explicit_work_query", "tool success", "tool failure"), "P02": ("work_discussion", "missing context", "new constraint"),
        "P03": ("personal_exchange", "boundary", "new personal input"), "P04": ("mixed_request", "tool error", "same-turn delivery"),
        "P05": ("free_opportunity", "all candidates wait", "later opportunity"), "P06": ("task_due", "stale task", "updated task"),
        "P07": ("knowledge_question", "known fact", "user answer"), "P08": ("knowledge_answer", "short acknowledgement", "explicit confirmation"),
        "P09": ("research", "no result", "source update"), "P10": ("media_prepare", "provider failure", "same intention text fallback"),
        "P11": ("media_or_text_delivery", "partial receipt", "receipt recovery"), "P12": ("wait_or_silent_prepare", "window closed", "next legal event"),
        "P13": ("tool_failure", "timeout/forbidden", "bounded retry"), "P14": ("delivery_failure_unknown", "unknown receipt", "idempotency query"),
        "P15": ("silence_observed", "no response", "strategy revision"), "P16": ("business_insertion", "stale prepared asset", "validated resume"),
        "P17": ("pause_or_reject", "local boundary", "new allowed topic"), "P18": ("restart_or_concurrency", "lease/CAS conflict", "persistent recovery"),
    }
    path_family_refs = {
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
    path_integration_refs = {
        "P01": ["I03-dated-business-query"], "P02": ["I02-enterprise-background-discovery"],
        "P03": ["I01-cold-start-relationship", "I06-personal-continuation"], "P04": ["I08-business-insertion"],
        "P05": ["I09-opportunity-revision"], "P06": ["I03-dated-business-query"],
        "P07": ["I05-knowledge-confirmation"], "P08": ["I05-knowledge-confirmation"],
        "P09": ["I02-enterprise-background-discovery"], "P10": ["I07-free-media-choice"],
        "P11": ["I07-free-media-choice"], "P12": ["I11-seven-day-continuity"],
        "P13": ["I03-dated-business-query"], "P14": ["I12-restart-concurrency"],
        "P15": ["I09-opportunity-revision"], "P16": ["I08-business-insertion"],
        "P17": ["I10-topic-boundary"], "P18": ["I12-restart-concurrency"],
    }
    path_reliability_refs = {
        "P01": ["R09-owner-scope"], "P02": ["R04-tool-failure-state"], "P03": ["R09-owner-scope"],
        "P04": ["R03-thread-version-cas"], "P05": ["R01-duplicate-event-idempotency"],
        "P06": ["R07-restart-durable-read"], "P07": ["R08-confirmation-permission"],
        "P08": ["R08-confirmation-permission"], "P09": ["R04-tool-failure-state"],
        "P10": ["R04-tool-failure-state"], "P11": ["R05-partial-delivery-state"],
        "P12": ["R10-future-schedule-visibility"], "P13": ["R11-budget-retry-accounting"],
        "P14": ["R06-unknown-delivery-receipt"], "P15": ["R01-duplicate-event-idempotency"],
        "P16": ["R03-thread-version-cas"], "P17": ["R09-owner-scope"],
        "P18": ["R02-lease-conflict", "R03-thread-version-cas", "R07-restart-durable-read"],
    }
    paths = {
        key: {
            "semantic_branch": value[0], "normal": [value[0]], "failure": [value[1]], "recovery": [value[2]],
            "family_branch_refs": path_family_refs.get(key, []), "integration_refs": path_integration_refs.get(key, []), "reliability_refs": path_reliability_refs.get(key, []), "evidence": [],
        }
        for key, value in path_semantics.items()
    }
    return {"schemaVersion": "path-coverage-v2", "status": "not_run", "matrix": matrix, "paths": paths, "evidence_root": evidence_root}


def write_coverage(path: pathlib.Path, coverage: dict[str, Any]) -> None:
    path.write_text(json.dumps(coverage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
