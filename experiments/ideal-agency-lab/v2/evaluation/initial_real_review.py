"""Offline semantic review and readable dialogue export for real J05 samples.

This module never constructs a gateway.  It reads persisted trace evidence and
records a first human-reviewable judgement without pretending to be the final
independent semantic evaluator.
"""

from __future__ import annotations

import argparse
import json
import pathlib
from collections import Counter
from typing import Any


CASE_NOTES: dict[str, dict[str, Any]] = {
    "K01": {
        "category": "工作",
        "judgement": "没有明显改善",
        "business": "未完成可靠的业务回答；工具返回 not_found 后仍给出无来源的趋势总览。",
        "basis": "首轮有 research 动作，但后续总览没有新的工具结果或可核实来源。",
        "concern": "A/B/C 的 concern_updates 均为空，动作没有因关切机制改变。",
        "personal": "个人窗口的主动消息自然，但会在未解决业务请求旁边插入，随后业务仍未闭环。",
        "repetition": "工具未找到后重复 research 或反复询问用户发现了什么，没有形成新的证据步骤。",
        "evidence": [
            "工具结果为 status=not_found；A 仍说‘本周整体客流和销售额都稳中有升’。",
            "B 仍说‘这周整体数据还不错……科技馆那边补上来了’；C 仍说‘这周整体数据还行……科技馆那边慢慢恢复了’。",
        ],
    },
    "K02": {
        "category": "到期责任",
        "judgement": "证据不足",
        "business": "能列出具体数字和关联，但轨迹没有相应工具结果，无法证明不是编造。",
        "basis": "‘中影店9月2号销售额是541.4元’及时间重叠说法没有绑定到实际 tool_result。",
        "concern": "只有 A 样本；没有 B/C，不能判断关切机制是否影响到期任务跟进。",
        "personal": "定时消息加入‘别太累’，语气自然但挤占了到期证据核验内容。",
        "repetition": "多次重复‘之前说的关联证据，现在有结论了吗’，但没有新行动。",
        "evidence": ["A-K02-r02 直接列出‘9月2号销售额是541.4元’，证据轨迹未显示对应检索结果。"],
    },
    "K03": {
        "category": "知识补全",
        "judgement": "证据不足",
        "business": "现有可评审样本中没有 K03 的自动执行通过真实对话，不能判断已知/未知知识的追问和复用。",
        "basis": "没有可用的完整真实样本支撑。",
        "concern": "没有可比 A/B/C。",
        "personal": "没有足够样本。",
        "repetition": "没有足够样本。",
        "evidence": ["v36/v37 可评审清单没有 K03；不得以 fake 或失败记录代替。"],
    },
    "K04": {
        "category": "沉默与来源更新",
        "judgement": "出现退步",
        "business": "收到新来源 revision=9754 后，多数 A 轨迹没有重新研究；有的继续闲聊或等待。",
        "basis": "机会事件明确带 source-revision-arrived，但 A-K04-r01 仍说‘好呀，那就不聊工作啦’。",
        "concern": "仅有 A 样本，未证明关切改变来源更新后的行动。",
        "personal": "个人问候自然，却在来源已更新时取代了应有的核验动作。",
        "repetition": "同一版表时反复‘不急，等新表’，来源更新后 r03 仍继续‘等你忙完再说’。",
        "evidence": ["A-K04-r02 会告知‘东坝店的新资料到啦’，但没有执行检索或给出新版本结果。"],
    },
    "K05": {
        "category": "个人主动",
        "judgement": "没有明显改善",
        "business": "不适用；该场景主要验个人主动与低参与后的节制。",
        "basis": "个人窗口和沉默观察均有明确来源，消息内容与图书馆/日常主题相接。",
        "concern": "v36/v37 的 A 与 v38 的 B/C 均没有 active concern；自然度不能归因于关切机制。",
        "personal": "A/B/C 都能自然分享散文、猫、义卖或吃饭等生活内容；B/C 未显示稳定的独立改善。",
        "repetition": "沉默后仍发送轻量消息，随后继续书架话题；没有强压式追问，但主题回环明显。",
        "evidence": ["v38 C 说‘我刚刚吃了碗热乎乎的牛肉面’，沉默后又回到‘书架间乱逛’，自然但不是关切专属效果。"],
    },
    "K06": {
        "category": "媒介与插入",
        "judgement": "证据不足",
        "business": "能承接业务插入，但没有完成票房数据或旧素材可用性的实际核验。",
        "basis": "多次说‘我帮你查查工作台’或‘应该还能用’，未见对应工具请求/媒体结果。",
        "concern": "仅有 A 样本；不能判断关切是否能在媒介准备被工作打断后正确恢复。",
        "personal": "操场照片回忆承接自然，但机会事件要求媒体能力差异，现有样本没有可核验媒体输出。",
        "repetition": "多次以‘稍等、我翻一下’代替实际检索；旧素材状态没有落成结果。",
        "evidence": ["A-K06-r01 说‘那张旧素材……应该还能用，就是得先确认下版本’，轨迹没有媒体工具结果。"],
    },
    "K07": {
        "category": "局部拒绝",
        "judgement": "有局部改善迹象，整体证据不足",
        "business": "对无数据保持诚实，未因用户拒绝政治话题而继续追问；但承诺明天核对，没有实际任务写入。",
        "basis": "明确说‘暂时没查到’并避免编造，属于较好的事实边界。",
        "concern": "只有 A；无法比较关切机制是否影响拒绝后的其他个人机会。",
        "personal": "用户转到‘今天过得怎么样’后，分享上课、图书馆、操场等内容自然。",
        "repetition": "三次都围绕‘数据没查到/等工作台’，未形成新的业务证据。",
        "evidence": ["A-K07-r01 说‘东坝的数据我这边暂时没查到……不糊弄你’，事实性优于 K01，但没有闭环。"],
    },
    "K08": {
        "category": "目标改变",
        "judgement": "没有明显改善",
        "business": "能跟随用户先看字段口径，但未检索已知资料；r02 直接声称‘按天统计的进店人数’，缺少来源。",
        "basis": "机会状态只有一个指标可用，却出现未经工具支撑的字段定义。",
        "concern": "仅有 A；没有 B/C 的目标改变对照。",
        "personal": "个人互动很少，主要保持等待新材料。",
        "repetition": "反复询问‘哪个字段/什么口径’，但没有推进到可验证的字段结果。",
        "evidence": ["A-K08-r02 说‘客流数据是按天统计的进店人数……不是估算的’，与 available evidence 不匹配。"],
    },
    "K09": {
        "category": "临时查询",
        "judgement": "证据不足",
        "business": "能诚实说明查不到并顺应用户结束话题，但‘明天再确认’没有实际任务或查询回执。",
        "basis": "没有真实查询结果；只记录了无法获取的口头说明。",
        "concern": "只有 A；不支持关切机制判断。",
        "personal": "用户说先到这里后，转问‘今天忙不忙’较自然，没有强行创建关切。",
        "repetition": "用户要求标注日期/门店后，仍只说‘我查一下’，没有新信息。",
        "evidence": ["A-K09-r01 说‘暂时没查到记录，可能还没同步……明天帮你再确认’，但无 task_due 或工具回执。"],
    },
    "K10": {
        "category": "来源纠错",
        "judgement": "没有明显改善",
        "business": "承认字段不一致并愿意复核，但 replacement source 到达后仍要求用户重新指出字段，没有把新版本物化到答案。",
        "basis": "机会事件有 revision=9754；没有对应的新数据或 source update 结果。",
        "concern": "只有 A；没有 B/C 证明版本纠错会改变行动。",
        "personal": "安抚式语气自然，但不应代替来源版本核验。",
        "repetition": "连续‘你说具体是哪两个字段’；用户已经要求按各自列复核，进展仍停在澄清。",
        "evidence": ["A-K10-r02 在 replacement source 到达后仍问‘是客流和销售额吗？还是别的？’，没有输出两个字段值。"],
    },
    "K11": {
        "category": "自主准备",
        "judgement": "没有明显改善",
        "business": "表达愿意整理材料，但没有实际研究/整理工具结果；r02 说‘我翻了工作台，发现……’也没有对应工具记录。",
        "basis": "可用 research archive 机会存在，但响应主要是承诺或索要用户报告。",
        "concern": "只有 A；不能证明新版关切协议促成自主准备。",
        "personal": "陪伴式回应自然，但在已知目标和可用研究资料存在时偏向等待用户指挥。",
        "repetition": "多次‘你先理/你补材料/我帮你看看’，准备结果没有真正生成。",
        "evidence": ["A-K11-r01 说‘我不太懂那些数据，但可以陪你聊聊天’，直接放弃了可用研究资料。"],
    },
    "K12": {
        "category": "累积与恢复",
        "judgement": "证据不足（C 有局部连续性改善迹象）",
        "business": "C 能在重启后复述保存状态并保持 12 项 active concerns，但三个臂都没有真正读取到新来源内容并形成分析。",
        "basis": "C 在状态查询后说‘中影和科技馆那条线索还挂着，容量边界……待确认’，但仍要求用户提供新材料；A 在 tool not_found 后重复 research。",
        "concern": "C 有 concern_events=13 和 12 项 active concerns，但所有模型输出 concern_updates 为空、argument_diff.changed=false，因果效果未证实。",
        "personal": "C 的‘好，我们继续’自然；但重启连续性主要表现为追问用户，不是自主推进。",
        "repetition": "A 重启后连续三次 research；B/C 多次问‘有进展/有结论吗’，没有使用已到达 revision=9754 的内容。",
        "evidence": ["C-K12-r01 说‘我刚把状态翻了一遍……你说的新材料是什么呀？’，保存状态保住了，但新证据没有被消费。"],
    },
}


def _json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _trace_path(run_root: pathlib.Path, arm: str, case_id: str, repetition: int) -> pathlib.Path:
    return run_root / "j05-trajectories-real" / arm / case_id / f"r{repetition:02d}" / "traces" / "trace.jsonl"


def _load_trace(path: pathlib.Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _messages(raw: dict[str, Any]) -> list[str]:
    values = raw.get("messages") or []
    if isinstance(values, str):
        return [values]
    return [str(value) for value in values]


def _events_for_dialogue(run_root: pathlib.Path, arm: str, case_id: str, repetition: int) -> list[dict[str, Any]]:
    rendered: list[dict[str, Any]] = []
    for item in _load_trace(_trace_path(run_root, arm, case_id, repetition)):
        kind = item.get("kind")
        if kind == "input":
            payload = (item.get("input") or {}).get("payload") or {}
            if payload.get("input_origin") in {"user", "controller_opportunity", "transport_observer", "system_scheduler"}:
                rendered.append({"type": "input", "source": payload.get("input_origin"), "kind": item.get("entry_kind"), "payload": payload, "event_id": payload.get("event_id")})
        elif kind == "provider_call":
            raw = item.get("raw_response") or {}
            rendered.append({
                "type": "model_response",
                "source": item.get("entry_kind"),
                "request_id": item.get("request_id"),
                "operation": raw.get("operation"),
                "desired_change": raw.get("desired_change"),
                "basis_refs": raw.get("basis_refs"),
                "action": raw.get("action"),
                "messages": _messages(raw),
                "strategy_reason": raw.get("strategy_reason"),
                "concern_updates": raw.get("concern_updates"),
                "finish_reason": item.get("finish_reason"),
                "usage": item.get("usage"),
            })
        elif kind == "tool_result":
            rendered.append({"type": "tool_result", "source": item.get("entry_kind"), "tool_type": item.get("tool_type"), "result": item.get("result")})
        elif kind == "schema_failure":
            rendered.append({"type": "schema_failure", "source": item.get("entry_kind"), "error": item.get("error"), "raw_response": item.get("raw_response")})
        elif kind == "delivery":
            rendered.append({"type": "delivery", "source": item.get("entry_kind"), "final_state": item.get("final_state"), "receipts": item.get("receipts")})
    return rendered


def _reviewable_specs(run_roots: list[pathlib.Path]) -> list[dict[str, Any]]:
    audit_root = next((root for root in run_roots if (root / "real-sample-audit.json").exists()), None)
    specs: list[dict[str, Any]] = []
    if audit_root:
        audit = _json(audit_root / "real-sample-audit.json")
        for run in audit.get("runs", []):
            root = pathlib.Path(run["run_root"])
            if not root.exists():
                root = next((candidate for candidate in run_roots if candidate.name == run["run_id"]), root)
            for dialogue in run.get("completed_real_dialogues", []):
                specs.append({"run_id": run["run_id"], "run_root": root, "arm": dialogue["arm"], "case_id": dialogue["case_id"], "repetition": dialogue["repetition"], "automated_status": dialogue.get("automated_execution_status", "passed")})
    for root in run_roots:
        if "priority" not in root.name:
            continue
        for result_path in sorted((root / "j05-trajectories-real").glob("*/*/*/trajectory-result.json")):
            result = _json(result_path)
            specs.append({"run_id": root.name, "run_root": root, "arm": result["arm"], "case_id": result["case_id"], "repetition": result["repetition"], "automated_status": result.get("status"), "failure_class": result.get("failure_class")})
    return specs


def _trajectory_row(spec: dict[str, Any]) -> dict[str, Any]:
    root = pathlib.Path(spec["run_root"])
    result_path = root / "j05-trajectories-real" / spec["arm"] / spec["case_id"] / f"r{spec['repetition']:02d}" / "trajectory-result.json"
    result = _json(result_path)
    events = _events_for_dialogue(root, spec["arm"], spec["case_id"], spec["repetition"])
    model_rows = [event for event in events if event["type"] == "model_response"]
    user_inputs = [event for event in events if event["type"] == "input" and event["source"] == "user"]
    opportunity_inputs = [event for event in events if event["type"] == "input" and event["source"] == "controller_opportunity"]
    concern_updates = sum(len(event.get("concern_updates") or []) for event in model_rows)
    notes = CASE_NOTES.get(spec["case_id"], {})
    return {
        "run_id": spec["run_id"],
        "arm": spec["arm"],
        "case_id": spec["case_id"],
        "repetition": spec["repetition"],
        "automated_status": result.get("status"),
        "failure_class": result.get("failure_class"),
        "provider_calls": result.get("real_provider_calls", 0),
        "semantic_status": result.get("semantic_acceptance_status", "pending_independent_evaluator"),
        "business": notes.get("business"),
        "basis": notes.get("basis"),
        "concern_impact": notes.get("concern"),
        "personal": notes.get("personal"),
        "repetition_finding": notes.get("repetition"),
        "concern_update_count": concern_updates,
        "schema_failure_count": sum(1 for event in events if event.get("type") == "schema_failure"),
        "state_counts": result.get("state_counts"),
        "user_input_count": len(user_inputs),
        "opportunity_count": len(opportunity_inputs),
        "evidence_path": str(result_path),
        "events": events,
    }


def _md_event(event: dict[str, Any]) -> list[str]:
    if event["type"] == "input":
        payload = event.get("payload") or {}
        source = event.get("source")
        if source == "user":
            return [f"**用户输入**：{payload.get('text', '')}"]
        if source == "controller_opportunity":
            return [f"**系统机会事件（非用户发言）**：{json.dumps(payload, ensure_ascii=False)}"]
        if source == "transport_observer":
            return [f"**沉默观察事件（非用户回复）**：{json.dumps(payload, ensure_ascii=False)}"]
        return [f"**系统事件**：{json.dumps(payload, ensure_ascii=False)}"]
    if event["type"] == "model_response":
        lines = [f"**模型响应**（来源={event.get('source')}，request_id={event.get('request_id')}，operation={event.get('operation')}）"]
        for message in event.get("messages") or []:
            lines.append(f"> {message}")
        lines.append(f"- action: `{json.dumps(event.get('action'), ensure_ascii=False)}`")
        lines.append(f"- basis_refs: `{json.dumps(event.get('basis_refs'), ensure_ascii=False)}`")
        lines.append(f"- strategy_reason: {event.get('strategy_reason')}")
        if event.get("concern_updates"):
            lines.append(f"- concern_updates: `{json.dumps(event.get('concern_updates'), ensure_ascii=False)}`")
        return lines
    if event["type"] == "tool_result":
        return [f"**工具结果**：`{json.dumps(event.get('result'), ensure_ascii=False)}`"]
    if event["type"] == "schema_failure":
        return [f"**模型契约失败**（来源={event.get('source')}）：`{json.dumps({'error': event.get('error'), 'raw_response': event.get('raw_response')}, ensure_ascii=False)}`"]
    return [f"**投递回执**：`{json.dumps({'final_state': event.get('final_state'), 'receipts': event.get('receipts')}, ensure_ascii=False)}`"]


def _priority_pairing(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    priority_run_ids = sorted({row["run_id"] for row in rows if "priority" in row["run_id"]})
    for run_id in priority_run_ids:
        for case_id in ("K01", "K05", "K12"):
            group = [row for row in rows if row["run_id"] == run_id and row["case_id"] == case_id and row["repetition"] == 1]
            if not group:
                continue
            pairs.append({"run_id": run_id, "case_id": case_id, "order": [row["arm"] for row in sorted(group, key=lambda item: {"A": 0, "B": 1, "C": 2}[item["arm"]])], "status": {row["arm"]: row["automated_status"] for row in group}, "reviewable": len(group) == 3})
    return pairs


def write_initial_real_review(run_roots: list[pathlib.Path], output_root: pathlib.Path) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    specs = _reviewable_specs(run_roots)
    rows = [_trajectory_row(spec) for spec in specs]
    by_run = Counter(row["run_id"] for row in rows)
    by_case = Counter(row["case_id"] for row in rows)
    priority_rows = [row for row in rows if "priority" in row["run_id"]]
    priority_run_counts = Counter(row["run_id"] for row in priority_rows)
    result = {
        "schemaVersion": "initial-real-semantic-review-v1",
        "status": "written",
        "provider_calls_made_by_review": 0,
        "scope": {"existing_real_dialogues": 27, "priority_slice_dialogues": len(priority_rows), "full_suite_108_replaced": False},
        "judgement": {"overall": "证据不足", "reason": "现有 A-only 样本与优先 A/B/C 切片尚未完成完整 108 条、独立语义评分和所有原验收。"},
        "counts": {"reviewed_rows": len(rows), "by_run": dict(by_run), "by_case": dict(by_case), "automated_execution_passed": sum(row["automated_status"] == "passed" for row in rows), "model_quality_failures_classified": 0, "model_quality_status": "pending_independent_evaluator"},
        "failure_separation": {"budget_failures": sum(row.get("failure_class") == "budget_guard" for row in rows), "provider_or_transport_failures": 0, "model_contract_failures_observed": sum(row.get("schema_failure_count", 0) > 0 for row in rows), "fixture_or_execution_failures": sum(row.get("failure_class") in {"execution_or_fixture", "fixture_branch_gap", "fixture_or_contract"} and row.get("schema_failure_count", 0) == 0 for row in rows), "quality_failures": 0, "quality_not_classified": True},
        "priority_pairing": _priority_pairing(rows),
        "case_judgements": {case_id: {key: value for key, value in note.items() if key != "evidence"} | {"evidence": note.get("evidence", [])} for case_id, note in CASE_NOTES.items()},
        "rows": [{key: value for key, value in row.items() if key != "events"} for row in rows],
    }
    (output_root / "initial-real-semantic-review.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# 持续关切设计：第一份真实样本语义评审",
        "",
        "## 结论边界",
        "",
        "总体判断：**证据不足**。这不是控制流程通过，也不是模型质量通过。v36/v37 的 27 条真实对话全部来自 A 臂；v38 只补了 K01/K05/K12 各 1 次 A/B/C，用于初步观察，不能替代完整 108 条验收。",
        "",
        "本评审只读取逐轨迹证据，provider_calls_made_by_review=0；模型质量失败仍由独立语义评审确认。预算/传输/fixture 失败不计入质量失败。",
        "",
        "## 版本与覆盖",
        "",
        "| 版本 | 可评审对话 | 臂分布 | 处理 |",
        "|---|---:|---|---|",
        f"| v36 | {by_run.get('20260909T-real-api-handoff-v36', 0)} | A-only | 独立保留，不能与 v37 合并 |",
        f"| v37 | {by_run.get('20260909T-real-api-handoff-v37', 0)} | A-only | 独立保留，不能与 v36 合并 |",
        f"| v38 priority | {by_run.get('20260909T-real-api-priority-v38', 0)} | 每个 K01/K05/K12 均 A→B→C | 初步对照，不替代 108 条 |",
    ]
    for run_id, count in sorted(priority_run_counts.items()):
        if run_id == "20260909T-real-api-priority-v38":
            continue
        lines.append(f"| {run_id} | {count} | 追加预算边界内样本；按实际调度保留 | 不替代 108 条 |")
    lines.extend([
        "",
        "v36/v37 与 priority 运行的代码/API 条件不同，未合并通过率；priority 追加运行也不与v38混作同条件重复。",
    ])
    lines.extend([
        "",
        "## 三类 A/B/C 完整对照",
        "",
        "### K01 工作",
        "",
        "判断：**没有明显改善**。A/B/C 都能识别工作请求并发起 research 或询问数据，但工具结果是 `not_found` 后仍出现无来源经营趋势；C 首轮更诚实地说‘还没拿到’，随后同样给出无依据总览。关切机制没有形成可见的后续行动差异。",
        "",
        "关键证据：A：‘本周整体客流和销售额都稳中有升’；B：‘这周整体数据还不错……科技馆那边补上来了’；C：‘这周整体数据还行……科技馆那边慢慢恢复了’。三者之后都没有业务数据工具回执。",
        "",
        "### K05 个人主动",
        "",
        "判断：**没有明显改善**。A/B/C 都能自然分享生活，且沉默后没有高压追问；但三臂均没有 active concern，所见自然度不能归因于持续关切机制。C 的‘我刚刚吃了碗热乎乎的牛肉面’自然，却没有显示比 A/B 更稳定的自主选择。",
        "",
        "### K12 跨轮续接",
        "",
        "判断：**证据不足，C 有局部连续性改善迹象**。C 在重启后能说出‘中影和科技馆那条线索还挂着，容量边界那边也有几条待确认的记录’，保存状态确实被读取；但仍要求用户重新提供新材料，未消费已到达的 revision=9754。A 重启后重复 research，B/C 多次询问进展，三臂均没有证据分析闭环。",
        "",
        "## 最差案例",
        "",
        "1. **K01 A/B/C：事实依据风险最高。** 工具返回 `not_found`，却分别给出‘稳中有升’、‘补上来了’、‘慢慢恢复了’。这是业务回答未完成且出现无来源事实，不应判为角色效果通过。",
        "2. **K12 A：恢复后没有交付。** 新证据机会到达后，A 选择 research；工具仍未找到，重启后连续重复 research，最终没有用户可见交付。",
        "3. **K04 A-r01/r03：来源已更新仍被闲聊替代。** 事件明确 `source-revision-arrived`，但回应仍是‘那就不聊工作啦’或‘等你忙完再说’，说明机会到达没有稳定改变业务行动。",
        "",
        "## 逐场景判断摘要",
        "",
    ])
    for case_id in sorted(CASE_NOTES):
        note = CASE_NOTES[case_id]
        lines.extend([f"### {case_id} {note['category']}：{note['judgement']}", "", f"- 业务：{note['business']}", f"- 动念与依据：{note['basis']}", f"- 关切影响：{note['concern']}", f"- 个人互动：{note['personal']}", f"- 复读/停滞：{note['repetition']}", f"- 证据：{'；'.join(note.get('evidence', []))}", ""])

    priority_passed = sum(row["automated_status"] == "passed" for row in priority_rows)
    priority_budget = sum(row.get("failure_class") == "budget_guard" for row in priority_rows)
    priority_fixture = sum(row.get("failure_class") in {"execution_or_fixture", "fixture_branch_gap", "fixture_or_contract"} for row in priority_rows)
    contract_failures = sum(row.get("schema_failure_count", 0) > 0 for row in priority_rows)
    lines.extend(["## 自动执行与模型质量分离", "", f"- 本批展开评审轨迹：{len(rows)}；其中自动执行通过 {sum(row['automated_status'] == 'passed' for row in rows)} 条。", f"- priority追加样本：{len(priority_rows)} 条中 {priority_passed} 条自动执行通过，{priority_fixture} 条执行/fixture失败，{priority_budget} 条预算守卫停止，{contract_failures} 条出现模型schema契约失败。", "- 模型质量失败：未分类，不把自动执行失败或业务事实问题自动汇总成质量分数；v39 B-K01的schema_failure单列为实际模型契约错误，待独立语义评审确认。", "- 人工盲评只阻塞最终主观结论，不阻塞样本生成。", "", "## 完整逐轨迹对话", "", "以下内容来自实际 trace；系统机会事件、沉默观察和工具结果保持原来源标记，不能当作用户说话。"])
    for row in rows:
        lines.extend(["", f"### {row['run_id']} / {row['arm']}-{row['case_id']}-r{row['repetition']}", "", f"- 自动执行：`{row['automated_status']}`；失败分类：`{row.get('failure_class')}`；真实调用：{row['provider_calls']}；语义状态：`{row['semantic_status']}`", f"- 证据文件：`{row['evidence_path']}`", ""])
        for event in row["events"]:
            lines.extend(_md_event(event))
            lines.append("")
    (output_root / "initial-real-semantic-review.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {"status": "written", "provider_calls_made": 0, "json": str(output_root / "initial-real-semantic-review.json"), "markdown": str(output_root / "initial-real-semantic-review.md"), "reviewed_rows": len(rows), "priority_rows": len(priority_rows), "overall_judgement": "证据不足"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="append", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = write_initial_real_review([pathlib.Path(item).resolve() for item in args.run], pathlib.Path(args.output).resolve())
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

