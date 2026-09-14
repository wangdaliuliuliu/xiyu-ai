"""Small, source-aware guard for unsupported positive business claims.

This is deliberately a delivery guard, not a second answer generator.  It
looks only at the context that was actually assembled for the worker and the
actual tool result (if one exists).  In particular, a missing tool call is not
treated as proof of fabrication when the assembled context already contains a
relevant, source-backed value.
"""
from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any


_BUSINESS_MARKERS = (
    "经营", "客流", "销售", "票房", "订单", "营业", "门店", "数据", "指标",
    "本周", "本月", "每天", "趋势", "增长", "下降", "回升", "恢复", "提升", "下滑",
    "稳中", "补上", "转好", "表现", "收入", "金额", "数量",
)
_CONCLUSION_MARKERS = (
    "增长", "下降", "回升", "恢复", "提升", "下滑", "稳中", "补上", "转好",
    "稳定", "良好", "不错", "很好", "正常", "改善", "起色", "领先",
)
_UNCERTAINTY_MARKERS = (
    "没拿到", "没有拿到", "查不到", "未查到", "没有查到", "还没", "尚未", "无法",
    "不能", "不确定", "待核", "待确认", "需要先", "缺少", "没有返回", "仅能确认",
)
_NUMBER_RE = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?%?(?![A-Za-z])")
_TERM_ALIASES = {
    "客流": ("客流", "traffic"),
    "票房": ("票房", "boxoffice", "box_office"),
    "销售": ("销售", "sales", "amount"),
    "订单": ("订单", "orders", "order"),
    "经营": ("经营", "business_date", "weekly", "daily", "core"),
    "数据": ("数据", "data", "metric", "value"),
    "指标": ("指标", "metric"),
}


@dataclass(frozen=True)
class GroundingAssessment:
    checked: bool
    business_claim_candidate: bool
    explicit_uncertainty: bool
    relevant_evidence_present: bool
    evidence_mode: str
    evidence_refs: tuple[str, ...]
    unsupported_positive_claim: bool
    reason: str


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _source_refs(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key in ("source_ref", "source_refs"):
            current = value.get(key)
            if isinstance(current, str) and current.strip():
                found.add(current.strip())
            elif isinstance(current, list):
                found.update(str(item).strip() for item in current if str(item).strip())
        for item in value.values():
            found.update(_source_refs(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_source_refs(item))
    return found


def _domain_terms(text: str) -> set[str]:
    return {marker for marker in _BUSINESS_MARKERS if marker in text}


def _has_relevant_payload(text: str, message: str) -> bool:
    """Require both a business subject overlap and an actual value/detail.

    A source catalogue entry alone is not evidence.  A resident context with
    a structured source-backed record, or a complete tool result with data,
    is evidence when it shares a business subject with the message.  Numeric
    assertions additionally need the asserted number to occur in the payload.
    """
    terms = _domain_terms(message)
    if not terms:
        return False
    needles = {alias for term in terms for alias in _TERM_ALIASES.get(term, (term,))}
    if not any(needle.lower() in text.lower() for needle in needles):
        return False
    numbers = _NUMBER_RE.findall(message)
    if numbers and not any(number in text for number in numbers):
        return False
    # A positive trend claim needs more than a bare source_ref or catalogue
    # label.  Numeric data, a value field, or an explicit complete result is a
    # sufficient indication that the relevant payload reached the worker.
    return bool(numbers or re.search(r"\"(?:value|data|daily|core|metric|amount|count|traffic|boxOffice|sales)\"\s*:", text))


def assess_messages(decision: dict[str, Any], context: dict[str, Any], tool_result: dict[str, Any] | None = None) -> GroundingAssessment:
    messages = decision.get("messages") if isinstance(decision, dict) else None
    if not isinstance(messages, list) or not messages:
        return GroundingAssessment(False, False, False, False, "none", tuple(), False, "no_deliver_message")
    action_type = ((decision.get("action") or {}).get("type") if isinstance(decision, dict) else None)
    if action_type != "deliver":
        return GroundingAssessment(True, False, False, False, "none", tuple(), False, "non_delivery_action")
    message = " ".join(str(item) for item in messages)
    explicit_uncertainty = any(marker in message for marker in _UNCERTAINTY_MARKERS)
    business_candidate = (
        any(marker in message for marker in _BUSINESS_MARKERS)
        and (any(marker in message for marker in _CONCLUSION_MARKERS) or bool(_NUMBER_RE.search(message)) or explicit_uncertainty)
        and not any(marker in message for marker in ("？", "?", "吗", "怎么", "什么", "哪一", "哪些"))
    )
    if not business_candidate:
        return GroundingAssessment(True, False, False, False, "none", tuple(), False, "no_business_claim_marker")
    refs = tuple(sorted(_source_refs(context) | _source_refs(tool_result)))
    # Keep the real worker-visible context narrow.  The catalogue and source
    # aliases remain visible for diagnosis but do not count as materialized
    # evidence by themselves.
    resident = {
        "system": (context or {}).get("stable", {}),
        "current": (context or {}).get("current", {}),
        "event": (context or {}).get("event", {}),
        # Compact retrieved continuations keep the actual evidence delta at
        # the context root so it is not duplicated in event/current.  Include
        # that one authoritative copy in the grounding view as well.
        "evidence_delta": (context or {}).get("evidence_delta", {}),
    }
    resident_text = _json_text(resident)
    tool_complete = bool(
        isinstance(tool_result, dict)
        and tool_result.get("status") == "complete"
        and tool_result.get("data") not in (None, {}, [], "")
    )
    tool_text = _json_text(tool_result) if tool_complete else ""
    resident_hit = _has_relevant_payload(resident_text, message)
    tool_hit = tool_complete and _has_relevant_payload(tool_text, message)
    relevant = resident_hit or tool_hit
    mode = "resident_context" if resident_hit else ("complete_tool_result" if tool_hit else "none")
    unsupported = business_candidate and not explicit_uncertainty and not relevant
    if unsupported:
        reason = "positive_business_claim_without_relevant_worker_visible_evidence"
    elif relevant:
        reason = "relevant_worker_visible_evidence_present"
    elif explicit_uncertainty:
        reason = "message_explicitly_marks_missing_or_uncertain_evidence"
    else:
        reason = "no_positive_claim_detected"
    return GroundingAssessment(True, business_candidate, explicit_uncertainty, relevant, mode, refs, unsupported, reason)


def _repair_message(context: dict[str, Any], tool_result: dict[str, Any] | None) -> str:
    if isinstance(tool_result, dict) and tool_result.get("status") not in (None, "complete"):
        status = str(tool_result.get("status"))
        return f"这次查询没有返回可核对的经营明细（状态：{status}），我先不把趋势说成事实；等拿到对应来源和数值后，再按日期给你结论。"
    return "我这边这次还没有拿到可核对的经营明细，先不把趋势说成事实；等查询返回对应来源和数值后，再按日期给你结论。"


def repair_decision(decision: dict[str, Any], *, context: dict[str, Any], tool_result: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a minimally repaired decision and an auditable assessment.

    Only an unsupported positive business delivery is repaired.  Questions,
    uncertainty, personal conversation, tool actions, and grounded business
    answers remain untouched.
    """
    assessment = assess_messages(decision, context, tool_result)
    record = asdict(assessment)
    record["evidence_refs"] = list(assessment.evidence_refs)
    if not assessment.unsupported_positive_claim:
        record["repaired"] = False
        return deepcopy(decision), record
    repaired = deepcopy(decision)
    repaired["messages"] = [_repair_message(context, tool_result)]
    repaired["basis_refs"] = []
    repaired["strategy_reason"] = (
        str(repaired.get("strategy_reason", "")).rstrip()
        + "；已由证据门检查修正为不把未取得的经营趋势表述为事实"
    ).strip("；")
    record["repaired"] = True
    record["replacement_message"] = repaired["messages"][0]
    return repaired, record
