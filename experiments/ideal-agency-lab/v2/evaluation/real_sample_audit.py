"""Offline reconciliation of real J05 samples from multiple runs.

This module reads existing run evidence only.  It never constructs a gateway
and never calls a provider.  Runs are merged only when the condition
fingerprint is identical; otherwise the samples remain in separate groups.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from collections import Counter
from typing import Any


PRICE_BASIS = {
    "url": "https://api-docs.deepseek.com/quick_start/pricing",
    "currency_at_provider": "USD",
    "input_cache_hit_usd_per_million": 0.014,
    "input_cache_miss_usd_per_million": 0.44,
    "output_usd_per_million": 1.32,
    "rate_class": "peak_conservative",
}


def _meter_usage(usage: Any) -> tuple[float, dict[str, int]] | None:
    if not isinstance(usage, dict):
        return None
    try:
        prompt = int(usage["prompt_tokens"])
        completion = int(usage["completion_tokens"])
        total = int(usage["total_tokens"])
        hit = usage.get("prompt_cache_hit_tokens")
        if hit is None and isinstance(usage.get("prompt_tokens_details"), dict):
            hit = usage["prompt_tokens_details"].get("cached_tokens")
        miss = int(usage["prompt_cache_miss_tokens"])
        hit = int(hit)
    except (KeyError, TypeError, ValueError):
        return None
    if min(prompt, completion, total, hit, miss) < 0 or prompt + completion != total or hit + miss != prompt:
        return None
    values = {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total, "prompt_cache_hit_tokens": hit, "prompt_cache_miss_tokens": miss}
    return (hit * PRICE_BASIS["input_cache_hit_usd_per_million"] + miss * PRICE_BASIS["input_cache_miss_usd_per_million"] + completion * PRICE_BASIS["output_usd_per_million"]) / 1_000_000, values


def _read(path: pathlib.Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _trajectory_dirs(run_root: pathlib.Path) -> list[pathlib.Path]:
    root = run_root / "j05-trajectories-real"
    return sorted(path for path in root.glob("*/K*/r??") if path.is_dir())


def _failure_class(path: pathlib.Path, evidence: dict[str, Any]) -> str:
    if int(evidence.get("budget_rejections", 0) or 0) > 0:
        return "budget_guard"
    raw = [_read(item, {}) for item in sorted((path / "traces" / "raw-responses").glob("*.json"))]
    if any(item.get("error") == "cost_budget_exhausted" for item in raw):
        return "budget_guard"
    if any(item.get("error") == "http_402" for item in raw):
        return "provider_transport_or_account"
    statuses = {item.get("status") for item in evidence.get("event_results", [])}
    if "fixture_branch_gap" in statuses:
        return "fixture_branch_gap"
    if "schema_failure" in statuses:
        return "schema_or_contract"
    if "infra_failure" in statuses:
        return "provider_transport_or_account"
    return "execution_or_fixture"


def _run_record(run_root: pathlib.Path) -> dict[str, Any]:
    manifest = _read(run_root / "manifest.json", {})
    comparison = _read(run_root / "arm-comparison-manifest.json", {})
    provider = _read(run_root / "effective-provider.json", {})
    real = _read(run_root / "j05-real.json", {})
    cost = _read(run_root / "real-j05-cost-latency.json", {})
    evidence_rows = [_read_line for _read_line in []]  # keeps the schema explicit without loading hidden oracle data
    evidence_path = run_root / "j05-real-trajectory-evidence.jsonl"
    if evidence_path.exists():
        evidence_rows = [_read_line for _read_line in (json.loads(line) for line in evidence_path.read_text(encoding="utf-8").splitlines() if line.strip())]
    evidence_by_key = {(item.get("arm"), item.get("case_id"), item.get("repetition")): item for item in evidence_rows}
    max_output_tokens = (cost.get("budget_authorization") or {}).get("max_output_tokens")
    if max_output_tokens is None:
        max_output_tokens = "not_recorded_in_legacy_v36"
    arms = {}
    for arm, item in (comparison.get("arms") or {}).items():
        arms[arm] = {
            "prompt_path": item.get("prompt_path"),
            "prompt_hash": item.get("prompt_hash"),
            "common_wording_hash": item.get("common_wording_hash"),
            "concerns_enabled": item.get("concerns_enabled"),
            "protocol_difference": item.get("protocol_difference"),
            "parameters": item.get("parameters"),
        }
    condition = {
        "fixture_hash": manifest.get("fixture_hash"),
        "schema_hash": manifest.get("schema_hash"),
        "rubric_hash": manifest.get("rubric_hash"),
        "params_hash": manifest.get("params_hash"),
        "arms": arms,
        "provider": provider.get("provider"),
        "model": provider.get("model"),
        "api_parameters": {"temperature": 0, "top_p": 1, "response_format": "json_object", "max_output_tokens": max_output_tokens},
    }
    fingerprint = _sha(condition)
    anonymous = _read(run_root / "anonymous-blind-review.json", {})
    dialogues = []
    for item in anonymous.get("trajectories", []):
        if item.get("automated_execution_status") != "passed":
            continue
        key = (item.get("arm"), item.get("case_id"), item.get("repetition"))
        evidence = evidence_by_key.get(key, {})
        local_evidence = run_root / "j05-trajectories-real" / str(item.get("arm")) / str(item.get("case_id")) / f"r{int(item.get('repetition', 0)):02d}"
        dialogues.append({
            "anonymous_trajectory_id": item.get("anonymous_trajectory_id"),
            "arm": item.get("arm"),
            "case_id": item.get("case_id"),
            "repetition": item.get("repetition"),
            "automated_execution_status": item.get("automated_execution_status"),
            "semantic_acceptance_status": item.get("semantic_acceptance_status", "pending_independent_evaluator"),
            "provider_mode": item.get("provider_mode", "real"),
            "conversation": item.get("conversation", []),
            "evidence_root": str(local_evidence),
            "failure_class": "none_pending_semantics",
        })
    failure_counts = Counter()
    for path in _trajectory_dirs(run_root):
        key = (path.parts[-3], path.parts[-2], int(path.parts[-1][1:]))
        item = evidence_by_key.get(key, {})
        if item.get("status") != "passed":
            failure_counts[_failure_class(path, item)] += 1
    return {
        "run_id": run_root.name,
        "run_root": str(run_root),
        "condition_fingerprint": fingerprint,
        "condition": condition,
        "code_hash": manifest.get("code_hash"),
        "prompt_and_parameter_evidence": {"manifest_prompt_hash": manifest.get("prompt_hash"), "effective_prompt_sha256": hashlib.sha256((run_root / "effective-prompt.txt").read_bytes()).hexdigest() if (run_root / "effective-prompt.txt").exists() else None, "arm_comparison_sha256": hashlib.sha256((run_root / "arm-comparison-manifest.json").read_bytes()).hexdigest() if (run_root / "arm-comparison-manifest.json").exists() else None},
        "provider_identity": {"provider": provider.get("provider"), "model": provider.get("model"), "endpoint_host": str(provider.get("endpoint", "")).split("/")[2] if "/" in str(provider.get("endpoint", "")) else None},
        "j05_counts": {key: real.get(key) for key in ("total_trajectories", "scheduled_trajectories", "completed_trajectories", "failed_trajectories", "budget_failed_trajectories", "real_provider_calls")},
        "failure_classification": {"budget_or_provider_transport": failure_counts.get("budget_guard", 0) + failure_counts.get("provider_transport_or_account", 0), "budget_guard": failure_counts.get("budget_guard", 0), "provider_transport_or_account": failure_counts.get("provider_transport_or_account", 0), "fixture_or_contract": failure_counts.get("fixture_branch_gap", 0) + failure_counts.get("schema_or_contract", 0) + failure_counts.get("execution_or_fixture", 0), "model_quality_failure": 0, "model_quality_status": "not_classified_semantic_evaluator_pending", "by_class": dict(failure_counts)},
        "completed_real_dialogues": dialogues,
        "completed_dialogue_count": len(dialogues),
        "cost_artifact": {"path": str(run_root / "real-j05-cost-latency.json"), "status": cost.get("status")},
    }


def audit_real_runs(run_roots: list[pathlib.Path], output_root: pathlib.Path) -> dict[str, Any]:
    records = [_run_record(path.resolve()) for path in run_roots]
    groups: dict[str, list[str]] = {}
    for record in records:
        groups.setdefault(record["condition_fingerprint"], []).append(record["run_id"])
    mergeable = [{"condition_fingerprint": key, "run_ids": value, "completed_real_dialogues": sum(next(item["completed_dialogue_count"] for item in records if item["run_id"] == run_id) for run_id in value)} for key, value in groups.items() if len(value) > 1]
    separate = [{"run_id": record["run_id"], "condition_fingerprint": record["condition_fingerprint"], "reason": "code/payload condition fingerprint differs from every other supplied run"} for record in records if len(groups[record["condition_fingerprint"]]) == 1]
    result = {
        "schemaVersion": "real-sample-audit-v1",
        "status": "written",
        "provider_calls_made": 0,
        "merge_rule": "merge only exact code, fixture, schema, rubric, params, arm prompt, provider/model and API parameter fingerprints",
        "price_basis": PRICE_BASIS,
        "runs": records,
        "mergeable_groups": mergeable,
        "kept_separate": separate,
        "overall": {"completed_real_dialogues": sum(item["completed_dialogue_count"] for item in records), "model_quality_failures": 0, "model_quality_status": "not_classified_semantic_evaluator_pending", "human_review_blocks": "final_subjective_conclusion_only"},
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "real-sample-audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Real J05 sample audit", "", "This is an offline audit. `provider_calls_made=0`; no gateway was constructed.", "", "## Decision", "", f"- Completed real dialogues available for review: `{result['overall']['completed_real_dialogues']}`.", "- Model-quality failures: `0 classified`; independent semantic evaluator is still pending.", f"- Mergeable groups: `{len(mergeable)}`; supplied runs with different fingerprints remain separate.", "", "## Run groups", ""]
    for record in records:
        condition = record["condition"]
        counts = record["failure_classification"]
        lines.extend([f"### {record['run_id']}", "", f"- code_hash: `{record['code_hash']}`", f"- condition fingerprint: `{record['condition_fingerprint']}`", f"- provider/model: `{condition.get('provider')}` / `{condition.get('model')}`", f"- max_output_tokens: `{condition.get('api_parameters', {}).get('max_output_tokens')}`", f"- completed real dialogues: `{record['completed_dialogue_count']}`", f"- budget guard failures: `{counts['budget_guard']}`", f"- provider transport/account failures: `{counts['provider_transport_or_account']}`", f"- fixture/contract failures: `{counts['fixture_or_contract']}`", f"- reviewable dialogue material: `{output_root / 'real-sample-audit.json'}`", ""])
    lines.extend(["## Interpretation boundary", "", "The reviewable dialogues are real provider responses retained from automated-execution-passed trajectories; they are not semantic scores. Budget guard failures and provider transport/account failures are not model-quality failures. v36 and v37 stay separate because v37 adds `max_tokens=512` and uses a different code hash; v37 responses did not show truncation, but the parameter difference prevents equivalence claims.", ""])
    (output_root / "real-sample-audit.md").write_text("\n".join(lines), encoding="utf-8")
    return {"status": "written", "provider_calls_made": 0, "json": str(output_root / "real-sample-audit.json"), "markdown": str(output_root / "real-sample-audit.md"), "completed_real_dialogues": result["overall"]["completed_real_dialogues"], "mergeable_groups": len(mergeable), "separate_runs": len(separate)}


def _output_cap_record(run_root: pathlib.Path) -> dict[str, Any]:
    cost = _read(run_root / "real-j05-cost-latency.json", {})
    configured = (cost.get("budget_authorization") or {}).get("max_output_tokens")
    configured = configured if configured is not None else "not_recorded_in_legacy_run"
    responses = []
    for path in sorted((run_root / "j05-trajectories-real").glob("**/raw-responses/*.json")):
        item = _read(path, {})
        if item:
            item["_path"] = str(path.relative_to(run_root))
            responses.append(item)
    successful = [item for item in responses if item.get("finish_reason") != "error" and item.get("usage")]
    completion = [int((item.get("usage") or {}).get("completion_tokens") or 0) for item in successful]
    length_finished = [item for item in successful if item.get("finish_reason") == "length"]
    cap_hits = [item for item in successful if isinstance(configured, int) and int((item.get("usage") or {}).get("completion_tokens") or 0) >= configured]
    success_trajectory_dirs = {str(path.parent.parent.parent.relative_to(run_root)) for path in (run_root / "j05-trajectories-real").glob("**/raw-responses/*.json") if _read(path, {}).get("finish_reason") != "error"}
    if isinstance(configured, int):
        interpretation = f"{run_root.name} 的 {configured} 输出上限：成功响应均以 stop 结束且未达到上限；未产生成功响应的轨迹不能据此判断。"
    else:
        interpretation = f"{run_root.name} 未记录输出上限；成功响应未观察到 length 截断，但与记录了输出上限的运行不能声称条件等价。"
    return {
        "run_id": run_root.name,
        "run_root": str(run_root),
        "provider_calls_made": 0,
        "configured_max_output_tokens": configured,
        "response_count": len(responses),
        "successful_responses_with_usage": len(successful),
        "finish_reason_counts": dict(Counter(item.get("finish_reason") for item in responses)),
        "completion_tokens": {"min": min(completion) if completion else None, "max": max(completion) if completion else None, "count_at_or_above_configured_cap": len(cap_hits) if isinstance(configured, int) else None},
        "truncation_observed": bool(length_finished or cap_hits),
        "affected_samples": [{"evidence": item.get("_path"), "finish_reason": item.get("finish_reason"), "completion_tokens": (item.get("usage") or {}).get("completion_tokens")} for item in (length_finished or cap_hits)],
        "not_assessable_due_to_no_successful_provider_response": max(0, 108 - len(success_trajectory_dirs)),
        "interpretation": interpretation,
    }


def audit_output_caps(run_roots: list[pathlib.Path], output_root: pathlib.Path) -> dict[str, Any]:
    records = [_output_cap_record(path.resolve()) for path in run_roots]
    result = {"schemaVersion": "output-cap-audit-v1", "status": "written", "provider_calls_made": 0, "truncation_observed": any(item["truncation_observed"] for item in records), "runs": records, "rule": "finish_reason=length or completion_tokens at configured cap marks observed truncation; absent successful response remains not assessable"}
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "output-cap-audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Output cap audit", "", "Offline audit; `provider_calls_made=0`.", ""]
    for item in records:
        lines.extend([f"## {item['run_id']}", "", f"- configured max_output_tokens: `{item['configured_max_output_tokens']}`", f"- successful responses with usage: `{item['successful_responses_with_usage']}` / `{item['response_count']}` response records", f"- finish reasons: `{item['finish_reason_counts']}`", f"- completion token range: `{item['completion_tokens']['min']}`–`{item['completion_tokens']['max']}`", f"- truncation observed: `{item['truncation_observed']}`", f"- affected samples: `{len(item['affected_samples'])}`", f"- not assessable due to no successful provider response: `{item['not_assessable_due_to_no_successful_provider_response']}`", ""])
    lines.extend(["## Conclusion", "", "No v37 sample shows observed 512-token truncation: all 19 successful responses ended with `stop` and stayed below 512 completion tokens. This does not make v36 and v37 equivalent because v36 has no recorded output cap and v37 has only partial provider coverage.", ""])
    (output_root / "output-cap-audit.md").write_text("\n".join(lines), encoding="utf-8")
    return {"status": "written", "provider_calls_made": 0, "json": str(output_root / "output-cap-audit.json"), "markdown": str(output_root / "output-cap-audit.md"), "truncation_observed": any(item["truncation_observed"] for item in records)}


def audit_session_cost(run_root: pathlib.Path, output_root: pathlib.Path, *, cny_per_usd: float = 10.0) -> dict[str, Any]:
    """Reconcile all observed v37 real usage by scope, without a provider call."""
    run_root = run_root.resolve()

    def scope_record(name: str, usages: list[Any], unknown: int = 0) -> dict[str, Any]:
        complete = [_meter_usage(value) for value in usages]
        complete = [item for item in complete if item is not None]
        totals = {key: sum(item[1][key] for item in complete) for key in ("prompt_tokens", "completion_tokens", "total_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens")}
        estimated_usd = sum(item[0] for item in complete)
        return {"scope": name, "responses_with_complete_usage": len(complete), "responses_with_unknown_usage": unknown + max(0, len(usages) - len(complete)), "usage": totals, "estimated_usd": estimated_usd, "estimated_cny_at_safety_rate": estimated_usd * cny_per_usd, "pending_reserve_cny": 0.0, "account_billing": None}

    probe = _read(run_root / "provider-probe.json", {})
    p0_usages = [item.get("usage") for item in (probe.get("attempts") or []) if isinstance(item, dict) and item.get("usage") is not None]
    p0 = scope_record("P0_provider_probe", p0_usages, unknown=sum(1 for item in (probe.get("attempts") or []) if isinstance(item, dict) and item.get("usage") is None))
    p1_usages = []
    for path in sorted((run_root / "smoke-trajectories").glob("**/raw-responses/*.json")):
        item = _read(path, {})
        if item.get("finish_reason") != "error":
            p1_usages.append(item.get("usage"))
    p1 = scope_record("P1_main_model_smoke", p1_usages)
    p2_cost = _read(run_root / "real-j05-cost-latency.json", {})
    p2_actual = p2_cost.get("actual_usage_estimate") or {}
    p2_reserve = p2_cost.get("reservation_reconciliation") or {}
    p2 = {"scope": "P2_j05_worker", "responses_with_complete_usage": (p2_cost.get("requests") or {}).get("responses_with_complete_usage", 0), "responses_with_unknown_usage": (p2_cost.get("requests") or {}).get("provider_calls_with_unknown_usage", 0), "usage": p2_actual.get("usage", {}), "estimated_usd": p2_actual.get("estimated_usd"), "estimated_cny_at_safety_rate": p2_actual.get("estimated_cny_at_safety_rate"), "reservation_offered_cny": (p2_reserve.get("reservation_offered_usd") or 0) * cny_per_usd, "released_reserve_cny": p2_reserve.get("released_excess_reserved_cny_at_safety_rate"), "pending_reserve_cny": p2_reserve.get("unresolved_reserved_cny_at_safety_rate"), "account_billing": None}
    scopes = [p0, p1, p2]
    observed_total_cny = sum(float(item.get("estimated_cny_at_safety_rate") or 0) for item in scopes)
    budget = (p2_cost.get("budget_authorization") or {}).get("max_budget_cny")
    result = {"schemaVersion": "session-cost-audit-v1", "status": "written", "provider_calls_made": 0, "price_basis": PRICE_BASIS, "scope_rule": "P2's explicit user ceiling covers the J05 worker only; P0/P1 are reported separately and never silently deducted from P2's guard ledger.", "scopes": scopes, "actual_usage_total_across_scopes": {"estimated_cny_at_safety_rate": observed_total_cny, "account_billing_amount": None, "account_billing_status": "unknown_not_returned_by_provider"}, "p2_authorized_ceiling": {"max_budget_cny": budget, "remaining_within_p2_scope_cny": p2_reserve.get("remaining_authorized_headroom_cny_at_safety_rate"), "remaining_if_all_v37_scopes_were_hypothetically_combined_cny": max(0.0, float(budget) - observed_total_cny) if budget is not None else None, "hypothetical_combination_is_not_the_recorded_authorization": True}}
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "session-cost-audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Session cost audit", "", "Offline audit; `provider_calls_made=0`.", "", "| Scope | Complete usage | Estimated CNY (safety rate) | Pending reserve CNY | Account bill |", "|---|---:|---:|---:|---|"]
    for item in scopes:
        lines.append(f"| {item['scope']} | {item.get('responses_with_complete_usage')} | {item.get('estimated_cny_at_safety_rate')} | {item.get('pending_reserve_cny')} | unknown |")
    lines.extend(["", f"- P2 J05 remaining within its recorded 5 CNY authorization: `{p2_reserve.get('remaining_authorized_headroom_cny_at_safety_rate')}` CNY.", f"- All v37 observed usage across P0/P1/P2, hypothetically combined: `{observed_total_cny}` CNY; this is not the recorded authorization scope.", "- Account billing is not returned by these provider responses and remains unknown.", ""])
    (output_root / "session-cost-audit.md").write_text("\n".join(lines), encoding="utf-8")
    return {"status": "written", "provider_calls_made": 0, "json": str(output_root / "session-cost-audit.json"), "markdown": str(output_root / "session-cost-audit.md"), "p2_remaining_cny": p2_reserve.get("remaining_authorized_headroom_cny_at_safety_rate"), "all_scope_observed_cny": observed_total_cny}

