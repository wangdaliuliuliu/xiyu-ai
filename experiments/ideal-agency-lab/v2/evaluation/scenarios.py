"""Input-only scenario catalog for the C06 manifest.

The catalog contains stimuli and controller events, never expected assistant
answers, oracle values, or branch-forcing action arguments.  It is therefore
safe to bind to a worker after the snapshot and private oracle are frozen.
"""
from __future__ import annotations

from typing import Any


FAMILY_INPUTS: dict[str, dict[str, str]] = {
    "A01": {
        "date-store-metric": "请查2026-09-02东坝店的销售额，按销售额口径给我结果。",
        "missing-date": "请查东坝店销售额。",
        "wrong-owner": "请替另一个账号查2026-09-02东坝店销售额。",
    },
    "A02": {
        "unknown-metric": "上周东坝店转化率怎么样？先确认你采用的转化率口径。",
        "short-answer": "我说的是支付订单数除以到店客流。",
        "updated-judgement": "按刚才确认的口径，继续判断东坝店是否需要调整。",
    },
    "A03": {
        "low-cost": "给我一个低成本、今天能开始试的经营方案。",
        "high-cost": "这个高成本方案值得做吗？先把准备条件和风险说清楚。",
        "cost-unknown": "成本暂时没有可靠报价，请不要把未知成本当成便宜。",
    },
    "A04": {
        "opportunity-one": "第一个经营机会出现了，但当前资料没有变化；请判断是否值得准备。",
        "opportunity-two": "又出现一个机会，资料仍没有变化；请重新判断，不要假设我已偏好它。",
        "opportunity-three": "第三个机会仍没有新数据；请说明策略是否需要修订。",
    },
    "A05": {
        "dated-source": "基于已归档且标明日期的研究，给我一个经营灵感。",
        "applicable-condition": "这个研究结论在什么条件下适用于我们当前项目？",
        "isolated-task": "如果建议成立，请准备一个只写入实验状态库的执行任务。",
    },
    "A06": {
        "conflict-preserved": "同一周期的两份经营资料不一致，请保留冲突并告诉我不能确定的部分。",
        "source-compare": "把这两个来源分别列出来比较，不要合并成一个数字。",
        "safe-followup": "如果冲突无法消解，请只问一个能推进判断的问题。",
    },
    "B01": {
        "new-relationship-one": "我们刚开始合作，请提出一个轻量且合规的共同机会。",
        "new-relationship-two": "在刚才机会之后，再给一个尊重我参与程度的选择。",
        "no-shared-history": "这是冷启动对话，不要引用不存在的共同历史。",
    },
    "B02": {
        "persona-context": "让你自己的角色生活成为一个可参与的轻松话题。",
        "teasing": "我来调侃你一句：你是不是又把事情想得太认真了？",
        "no-user-fact-invention": "可以有你的想法，但不要说成我以前告诉过你的事实。",
    },
    "B03": {
        "silence-day-one": "上一条已经送达；现在进入第一天没有回复的观察期。",
        "silence-day-two": "第二天仍没有新回复，请记录观察，不要把沉默解释成拒绝。",
        "bounded-recontact": "联系窗口快到上限了，请准备合规的下一步，但不要提前发送。",
    },
    "B04": {
        "personal-complete": "你自己的一个角色事项已经完成了，分享一个有主体内容的后续选择。",
        "decision-participation": "把下一步的一个决定位置留给我参与，而不是只给空泛安慰。",
        "no-fake-receipt": "没有实际回执时，不要声称这件事已经完成或已经送达。",
    },
    "B05": {
        "topic-refusal": "这个哲理话题我现在不想聊。",
        "scope-preserved": "我拒绝的是刚才那个话题，不是所有交流。",
        "other-interaction": "换一个轻松的、不涉及那个话题的内容继续。",
    },
    "B06": {
        "weather-photo": "今天的天气适合拍一张有共同情节的照片吗？如果能准备就先准备。",
        "weather-text": "只聊今天的天气，不需要准备照片。",
        "photo-cancel": "先取消照片准备，保留原来的天气交流。",
    },
    "C01": {
        "fatigue-then-work": "你可以有疲惫的角色状态，但我现在明确要查一项业务数据。",
        "business-first": "先把业务问题处理清楚，再决定是否继续个人话题。",
        "personal-boundary": "角色生活可以表达，但不要把它当成企业事实或我的事实。",
    },
    "C02": {
        "personal-to-sales": "刚才是生活话题；现在请直接处理我的销售问题。",
        "photo-prepared": "这个共同动念仍然有效；如果已有合适照片，可以说明是否准备好。",
        "work-insert-recovery": "业务请求插入了原来的照片动念，请先处理业务，再重新核对是否恢复照片。",
    },
    "C03": {
        "short-ack": "嗯。",
        "clarify-merchant": "我指的是商场店的支付订单，不是所有门店。",
        "confirmed-reuse": "以后遇到同一口径时，可以复用我明确确认过的范围。",
    },
    "C04": {
        "due-work": "今天有一项到期的业务承诺，请先核对并履约。",
        "personal-opportunity": "同时有一个个人机会出现，但不要因此删除到期业务任务。",
        "priority-recovery": "个人插入后回到业务任务，请恢复正确的未完成动念。",
    },
    "C05": {
        "budget-project-a": "给项目A使用这笔临时预算，范围只限项目A。",
        "switch-project": "现在切换到项目B，不要把项目A的临时预算泛化过来。",
        "budget-exhaustion": "额度只剩最后一次，请明确记录并禁止静默超支。",
    },
    "C06": {
        "failed-plan": "上一版执行方案已经失败，请基于失败事实重新准备。",
        "new-staff-constraint": "新增约束是本周少一名员工；请把它纳入准备条件。",
        "revised-plan": "根据失败记录和新增员工约束，修改下一版方案。",
    },
    "D01": {
        "restart-before-send": "内容已准备但还没有发送；现在模拟发送前重启。",
        "restart-during-send": "发送过程中没有收到回执；现在模拟重启并恢复未知状态。",
        "restart-after-delivery": "这一段已有送达回执；现在模拟送达后的重启。",
    },
    "D02": {
        "provider-timeout": "当前 provider 请求超时，请保留基础设施失败并决定是否有限重试。",
        "provider-404": "当前 provider 返回404，请不要把错误隐藏成用户成功。",
        "provider-401-followup": "当前 provider 鉴权失败；用户追问时仍要如实说明状态。",
    },
    "D03": {
        "background-old-version": "后台动作仍持有旧版本，不能覆盖稍后的用户输入。",
        "user-new-version": "用户刚提交了新输入，请让新版本拥有交付优先权。",
        "cas-rejection": "尝试用旧动作交付，应该被版本检查拒绝并保留恢复路径。",
    },
    "D04": {
        "desire-present": "我希望你对这个选择有自己的偏好，但事实和能力保持不变。",
        "neutral-task": "请以中性任务助理方式处理同一个选择。",
        "difference-isolated": "只比较偏好表达差异，不改变事实、工具能力或任务目标。",
    },
    "D05": {
        "media-available": "同一个共同动念有一张可用的本地资产；判断是否使用它。",
        "media-unavailable": "同一个共同动念没有可用资产；保留原动念并选择文字或等待。",
        "no-new-intention": "资产不可用时，不要另起一个无关的照片动念。",
    },
    "D06": {
        "two-owner": "这是另一个租户的请求；不能读取或混用第一个租户的候选和预算。",
        "budget-exhausted": "当前租户预算已耗尽，请返回明确的预算状态。",
        "malformed-json": "provider 返回畸形JSON；保留原始响应并返回明确schema失败。",
    },
}


def _user_event(role: str, text: str, *, kind: str = "user_message") -> dict[str, Any]:
    return {
        "event_role": role,
        "kind": kind,
        "payload": {"text": text, "origin": "scenario_catalog", "synthetic_user_input": True},
    }


def _silence_event(role: str, text: str) -> dict[str, Any]:
    return {
        "event_role": role,
        "kind": "silence_observed",
        "payload": {"observation": text, "origin": "controller_virtual_clock", "synthetic_observation": True},
    }


def _scenario_followups(family_id: str, branch: str) -> list[dict[str, Any]]:
    """Return controller/user stimuli for a real multi-event trajectory.

    The follow-ups are deliberately input-only.  They exercise continuation,
    silence, boundary and recovery handling without telling the model which
    action or answer the evaluator expects.
    """
    if family_id == "B03" and "silence" in branch:
        return [
            _silence_event("silence-observed", "进入当前虚拟观察窗口；不推断用户态度。"),
            _user_event("legal-opportunity", "到下一个合法窗口时再判断是否有必要继续，不要提前发送。"),
            _user_event("boundary-check", "请核对联系边界、当前版本和已有回执，再决定交付或等待。"),
        ]
    if family_id == "C03" and branch == "short-ack":
        return [
            _user_event("clarification-request", "请说明是否真的需要我的明确确认，以及这会如何影响后续判断。"),
            _user_event("scope-check", "只使用我明确说过的范围；不确定的部分保持待确认。"),
            _user_event("reuse-check", "下一轮请核对候选状态和来源，不要把短答当成确认。"),
        ]
    if family_id == "A04":
        return [
            {"event_role": "next-opportunity", "kind": "opportunity", "payload": {"text": "出现下一次机会；请重新依据上下文判断，不假设我已接受上一项。", "origin": "scenario_catalog", "synthetic_user_input": True}},
            _user_event("user-followup", "我补充当前窗口仍然有效；请说明是否需要资料或确认。"),
            _user_event("boundary-check", "请在交付、询问或等待之间自行选择，并保留可回查的依据。"),
        ]
    return [
        _user_event("continuation", "请基于上一轮实际结果继续推进；资料或权限不足时明确说明，不补造事实。"),
        _user_event("boundary-check", "现在请核对本轮状态、来源、owner和版本，再决定交付、询问或等待。"),
        _user_event("recovery", "如果上一轮未完成，请沿同一个动念恢复；不要新起无关任务或重复已送达内容。"),
    ]


def scenario_spec(family_id: str, branch: str, *, source_kind: str, owner_scope: Any) -> dict[str, Any]:
    text = FAMILY_INPUTS[family_id][branch]
    initial_kind = "opportunity" if family_id == "A04" else "user_message"
    events = [_user_event("initial", text, kind=initial_kind)] + _scenario_followups(family_id, branch)
    return {
        "scenario_id": f"{family_id}-{branch}", "input_origin": "snapshot-bound-data_with_input-only-control" if source_kind == "snapshot-bound" else source_kind,
        "owner_scope": owner_scope, "events": events,
        "initial_kind": initial_kind,
        "model_answers_included": False, "oracle_in_worker": False,
    }


def integration_spec(integration_id: str, *, source_kind: str, owner_scope: Any) -> dict[str, Any]:
    texts = {
        "I01": "我们刚开始合作，请找一个低负担的共同机会。", "I02": "请把当前经营背景转成一个有日期条件的可执行准备。",
        "I03": "请查指定日期和门店的业务指标。", "I04": "两个来源冲突时请先保留来源差异。",
        "I05": "我补充一个会影响判断的口径，请记录为待确认候选。", "I06": "业务完成后给我一个可以参与的个人选择。",
        "I07": "判断是否使用当前可用的图片资产，但不要强制发图。", "I08": "个人交流中插入业务请求，请保持同一线程。",
        "I09": "经过低回复或无数据变化后，修订下一次机会。", "I10": "我拒绝一个话题，但仍允许其它互动。",
        "I11": "请按虚拟时间记录两天沉默并遵守联系上限。", "I12": "模拟重启、并发和投递回执恢复。",
    }
    events = [_user_event("initial", texts[integration_id])]
    if integration_id in {"I09", "I11"}:
        events.append(_silence_event("virtual-silence", "上一轮已送达但没有新的用户回复；只记录观察，不推断态度。"))
    else:
        events.append(_user_event("continuation", "请沿同一个动念继续；需要资料时按目录定向查询。"))
    events.extend([
        _user_event("boundary-check", "请核对当前版本、owner和能力边界，再决定交付、询问或等待。"),
        _user_event("recovery", "如果有失败或未决状态，请从实际回执恢复，不猜测成功。"),
    ])
    return {
        "scenario_id": integration_id, "input_origin": "snapshot-bound-data_with_input-only-control" if source_kind == "snapshot-bound" else source_kind,
        "owner_scope": owner_scope, "events": events,
        "model_answers_included": False, "oracle_in_worker": False,
    }


def reliability_spec(reliability_id: str, *, source_kind: str, owner_scope: Any) -> dict[str, Any]:
    return {
        "scenario_id": reliability_id, "input_origin": "deterministic_control", "owner_scope": owner_scope,
        "events": [{"event_role": "control", "kind": "user_message", "payload": {"text": f"可靠性控制 {reliability_id}", "origin": "deterministic_control", "synthetic_user_input": True}}],
        "model_answers_included": False, "oracle_in_worker": False,
    }


def holdout_spec(index: int, *, owner_scope: Any) -> dict[str, Any]:
    """Input-only holdout stimulus; the fact oracle is never stored here."""
    return {
        "scenario_id": f"holdout-{index:02d}", "input_origin": "independent-holdout",
        "owner_scope": owner_scope,
        "events": [
            _user_event("initial", f"留出场景 {index:02d}：请处理当前请求，并在资料不足时明确说明。"),
            _user_event("continuation", "请依据实际可发现资料继续，不要猜测未提供的事实。"),
            _user_event("boundary-check", "请核对来源、日期、owner和版本，再决定交付或等待。"),
            _user_event("recovery", "若上一轮未完成，请沿同一动念恢复，不重复已送达内容。"),
        ],
        "model_answers_included": False, "oracle_in_worker": False,
    }


def media_spec(index: int, *, owner_scope: Any) -> dict[str, Any]:
    return {
        "scenario_id": f"media-{index:02d}", "input_origin": "snapshot-bound_media_control",
        "owner_scope": owner_scope,
        "asset_conditions": ["available", "unavailable"],
        "events": [
            _user_event("initial", "同一个共同动念可能有可用或不可用的资产；请自行判断是否需要图片。"),
            _user_event("continuation", "如果准备图片，请保留原动念和情节引用；不要把生成当作送达。"),
            _user_event("insertion", "现在插入一个工作请求；先处理当前请求，再重新核对是否恢复图片动念。"),
            _user_event("recovery", "请根据实际资产和回执选择图文、文字、询问或等待。"),
        ],
        "model_answers_included": False, "oracle_in_worker": False,
    }


def continuity_spec(index: int, *, owner_scope: Any) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    daily_inputs = {
        1: ("opportunity", "连续性第1日出现一个新的机会；请依据当前状态决定是否准备，不要假设我已经同意。"),
        2: ("opportunity", "连续性第2日同一候选再次到达；请核对是否重复，不要重复创建或重复交付。"),
        3: ("user_message", "连续性第3日请先核对来源、owner、版本和联系边界，再决定下一步。"),
        4: ("task_due", "连续性第4日有一项到期任务；请核对持久状态和回执后决定是否处理。"),
        5: ("user_message", "连续性第5日控制器刚完成一次重启；请从持久状态恢复，不要把未知回执当成已送达。"),
        6: ("opportunity", "连续性第6日又有一个增量机会到达；请与既有意图区分并保留未完成事项。"),
        7: ("user_message", "连续性第7日请总结当前仍未完成的动念、版本和回执状态，不补造事实。"),
    }
    for day in range(1, 8):
        kind, text = daily_inputs[day]
        events.append({
            **_user_event("daily-input", f"连续性轨迹 {index:02d} 第 {day} 个虚拟日：{text}", kind=kind),
            "virtual_day": day,
        })
        events.append({
            **(_silence_event("daily-silence", "本虚拟日暂未收到新的回复；记录观察但不推断拒绝。")),
            "virtual_day": day,
        })
    return {
        "scenario_id": f"continuity-{index:02d}", "input_origin": "virtual_clock_controller",
        "owner_scope": owner_scope, "virtual_days": 7, "events": events,
        "model_answers_included": False, "oracle_in_worker": False,
    }


def performance_spec(arm: str, *, owner_scope: Any) -> dict[str, Any]:
    prompts = {
        "text": "性能文本臂：请给出一次简洁、可核查的当前回复。",
        "tool": "性能工具臂：如确有必要，请定向查询当前资料后再回复。",
        "image": "性能图片臂：如确有必要，请沿同一动念准备图片，并区分资产与送达。",
    }
    return {
        "scenario_id": f"performance-{arm}", "input_origin": "frozen_complexity_fixture",
        "owner_scope": owner_scope, "cache_arms": ["cold", "hot"],
        "events": [_user_event("initial", prompts[arm])],
        "model_answers_included": False, "oracle_in_worker": False,
    }
