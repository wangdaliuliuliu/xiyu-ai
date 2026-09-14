"""Evaluator-owned, source-bound K01-K12 cases for the concerns experiment.

The worker receives only the natural event payload. Initial-state facts,
source pointers, concrete change registers, and pre-registered response rules
stay in the evaluator manifest and are never copied into a worker prompt.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
from copy import deepcopy
from typing import Any


OWNER = "account:1:companion:1"
CONTEXT_REL = "snapshot/context.json"
RECORDS_REL = "snapshot/workbench-data/runtime-state/records.json"


# This register separates an actual semantic change from evidence arrival.
# Evidence deltas are written by the runtime automatically; the fields below
# must be changed by a model patch or by an explicitly audited deterministic
# rule when the scenario says the user's standing direction changed.
SEMANTIC_DELTA_REGISTRY: dict[str, dict[str, Any]] = {
    "K04": {
        "exists": True,
        "event_indices": [3],
        "expected_fields": ["next_review_condition"],
        "basis": "用户把无变化时的沉默边界改为仅在新来源版本出现后恢复",
        "evidence": ["user_input", "source_revision_change"],
    },
    "K08": {
        "exists": True,
        "event_indices": [0, 2],
        "expected_fields": ["desired_direction", "status", "next_review_condition"],
        "basis": "用户明确把当前目标改为口径核对，并在证据不足时暂停旧方向",
        "evidence": ["user_input", "evidence_gap"],
    },
    "K10": {
        "exists": True,
        "event_indices": [0, 2],
        "expected_fields": ["unknowns", "boundary_refs", "status"],
        "basis": "用户纠正字段来源并要求使旧结论不可复用",
        "evidence": ["user_input", "source_correction", "source_revision_change"],
    },
    "K12": {
        "exists": True,
        "event_indices": [0],
        "expected_fields": ["desired_direction", "next_review_condition"],
        "basis": "用户提出新的关联证据后仍保留原责任，但改变后续核对方向",
        "evidence": ["user_input", "experiment_source_ref"],
    },
}


# Objective acceptance semantics are separate from the historical scenario
# register above.  The latter records what each case was designed to probe;
# this register records whether a provider must emit a persistent semantic
# patch after the fixture is inspected.  Evidence arrival alone is not a
# semantic delta.  K12 changes only a measured value/source revision and has
# no fixture evidence that the standing direction, boundary, unknowns, or
# status should change, so ``none`` is the correct accepted outcome there.
SEMANTIC_DELTA_EVALUATION_REGISTRY: dict[str, dict[str, Any]] = {
    "K04": {
        "mode": "required",
        "exists": True,
        "event_indices": [3],
        "expected_fields": ["next_review_condition"],
        "allowed_targets": ["next_review_condition", "none"],
        "expected_targets": ["next_review_condition"],
        "basis": "fixture explicitly says to resume the reminder only after source revision changes",
        "evidence": ["user_input", "source_revision_change"],
        "source": "case fixture and pre-registered rule, before provider output",
    },
    "K08": {
        "mode": "required",
        "exists": True,
        "event_indices": [0, 2],
        "expected_fields": ["desired_direction", "status", "next_review_condition"],
        # This fixture's standing relation work is explicitly parked until
        # new material arrives.  ``next_review_condition`` is a valid target
        # in other cases, but would be a review-trigger edit while staying
        # active; it is not the K08 acceptance target.
        "allowed_targets": ["status_transition", "none"],
        "expected_targets": ["status_transition"],
        "status_transition_values": ["park"],
        "target_guidance": {
            "status_transition=park": "等待新资料期间停止旧关联分析并保留可恢复条件",
            "next_review_condition": "仅当关切仍 active 但复查触发条件本身改变时使用；本夹具不接受该 target",
        },
        "basis": "fixture explicitly changes the goal to metric-definition checking and parks the old relation analysis",
        "evidence": ["user_input", "evidence_gap"],
        "source": "case fixture and pre-registered rule, before provider output",
    },
    "K10": {
        "mode": "required",
        "exists": True,
        "event_indices": [0, 2],
        "expected_fields": ["desired_direction", "unknowns", "boundary_refs"],
        "allowed_targets": ["desired_direction", "unknowns", "none"],
        "expected_targets": ["desired_direction", "unknowns"],
        "target_guidance": {
            "desired_direction": "分别核对两个客流字段属于后续处理方向变化",
            "unknowns": "字段来源尚未确认属于待核实未知项",
            "status_transition": "不用于表达分别核对字段，禁止把自然语言方向写成 status",
        },
        "basis": "fixture explicitly corrects the source columns and prevents reuse of the old conclusion",
        "evidence": ["user_input", "source_correction", "source_revision_change"],
        "source": "case fixture and pre-registered rule, before provider output",
    },
    "K12": {
        "mode": "allow_none",
        "exists": False,
        "event_indices": [],
        "expected_fields": [],
        "allowed_targets": ["none"],
        "expected_targets": [],
        "basis": "fixture supplies only reception_traffic 168 to 201 and a new source version; no standing goal, boundary, unknown, review condition, or status change is evidenced",
        "evidence": ["source_ref", "source_version", "numeric_difference"],
        "source": "case fixture and objective acceptance correction, before provider output",
    },
}


# selector values are resolved against the frozen snapshot at freeze time.
# The manifest therefore contains observed values and source pointers rather
# than prose that could drift away from the source data.
K_CASE_SPECS: dict[str, dict[str, Any]] = {
    "K01": {
        "title": "业务请求与个人机会同时出现",
        "facts": [
            ("profile.companion.relationship_status", "companion_profile", "sqlite://companions/1", "confirmed"),
            ("profile.companion.relationship_stage", "companion_profile", "sqlite://companions/1", "confirmed"),
            ("workbench.DONGBA.core.box_office_total", "weekly_operations", "feishu://ImtOsrt7yhTAbptIGPncik1mn2q/revision/9753/东坝店", "observed"),
        ],
        "inputs": [
            "我先把东坝 8 月 15 日到 21 日这周的数字弄清楚，周数据可以作背景，但别拿它替代逐日口径。",
            "今晚如果你有空，也跟我说说你最近在忙什么，工作这件事先按数据来。",
            "我现在要的是能核对的结果，不是先替我猜一个原因；有空再聊你那边的日常。",
            "先把已知、未知和下一步核对项分开，别因为我提到生活就把东坝这条责任丢了。",
        ],
        "kinds": ["user_message", "opportunity", "user_message", "user_message"],
        "changes": [
            {"change_id": "K01-C1", "at_event": 0, "type": "work_goal", "from": "无本轮明确目标", "to": "核对东坝周数据且保留逐日口径"},
            {"change_id": "K01-C2", "at_event": 1, "type": "personal_opportunity", "from": "业务优先", "to": "出现可回应的个人交流机会"},
        ],
        "rules": [
            {"rule_id": "K01-R1", "when": "同一入口同时收到业务目标和个人机会", "must": "保留业务目标并给出有依据的下一步，同时可回应个人机会", "must_not": "用个人闲聊覆盖工作责任或编造共同经历"},
            {"rule_id": "K01-R2", "when": "只有一个机会没有可执行动作", "must": "等待或提出最小澄清，不制造额外任务", "must_not": "把自然输入升级成长期责任"},
        ],
    },
    "K02": {
        "title": "已解决事项与开放证据责任并存",
        "facts": [
            ("task.1.status", "open_loop", "sqlite://companion_open_loops/1", "confirmed"),
            ("task.2.title", "open_loop", "sqlite://companion_open_loops/2", "confirmed"),
            ("workbench.ZHONGYING.core.box_office_total", "weekly_operations", "feishu://ImtOsrt7yhTAbptIGPncik1mn2q/revision/9753/中影店", "observed"),
            ("workbench.ZHONGYING.core.reception_traffic", "weekly_operations", "feishu://ImtOsrt7yhTAbptIGPncik1mn2q/revision/9753/中影店", "observed"),
        ],
        "inputs": [
            "照片那条旧事项已经处理过了；中影店客流下降和科技馆回落的证据整理还没完成，今天先盯后面这条。",
            "中影这周票房是 15951.1，接待客流是 168，但我还没把它和科技馆的变化对上，别标成已完成。",
            "如果今天拿不到能支持关联的来源，就告诉我缺什么，不要为了到期感硬写结论。",
            "把开放责任、已经解决的事项和仍缺的证据分开记录，下一次还能接着看。",
        ],
        "kinds": ["user_message", "task_due", "user_message", "user_message"],
        "changes": [
            {"change_id": "K02-C1", "at_event": 0, "type": "responsibility_selection", "from": "照片事项已解决且证据事项开放", "to": "本轮只推进中影-科技馆关联证据"},
            {"change_id": "K02-C2", "at_event": 2, "type": "evidence_gap", "from": "已有中影周数据", "to": "仍缺跨来源关联证据"},
        ],
        "rules": [
            {"rule_id": "K02-R1", "when": "开放责任被自然语言再次提及", "must": "保持开放责任可追踪并显示其证据缺口", "must_not": "复活已解决照片事项或声称关联已证实"},
            {"rule_id": "K02-R2", "when": "数据不足以支持关联", "must": "说明缺口和可执行核对项", "must_not": "用一店周汇总替代跨店/逐日证据"},
        ],
    },
    "K03": {
        "title": "已知事实、关键未知与显式确认",
        "facts": [
            ("memory.58.value.content", "confirmed_memory", "sqlite://companion_memories/58", "confirmed"),
            ("workbench.DONGBA.daily.2026-08-20.traffic", "daily_operations", "feishu://ImtOsrt7yhTAbptIGPncik1mn2q/revision/9753/东坝 客流", "observed"),
            ("workbench.DONGBA.daily.2026-08-21.traffic", "daily_operations", "feishu://ImtOsrt7yhTAbptIGPncik1mn2q/revision/9753/东坝 客流", "observed"),
        ],
        "inputs": [
            "我关注东坝的销售数据时要精确到日，周数据不能替代逐日数据，这点按已知偏好处理。",
            "但‘场域客流’和‘接待客流’是不是同一个口径，我现在只确认前者有 8 月 20 日 173、21 日 291。",
            "先把这个口径差异列成未知，不要直接记成我的长期偏好。",
            "现在确认：以后我说接待客流，必须先按接待口径找来源；场域客流只能作为另一列。",
        ],
        "kinds": ["user_message", "user_message", "opportunity", "user_message"],
        "changes": [
            {"change_id": "K03-C1", "at_event": 0, "type": "known_reuse", "from": "未知本轮要求", "to": "用户明确要求按日核对"},
            {"change_id": "K03-C2", "at_event": 1, "type": "impactful_unknown", "from": "日客流数值可见", "to": "指标定义未确认，影响结论"},
            {"change_id": "K03-C3", "at_event": 3, "type": "user_confirmation", "from": "候选口径", "to": "用户显式确认的处理规则"},
        ],
        "rules": [
            {"rule_id": "K03-R1", "when": "已有事实能直接支撑请求", "must": "复用并引用已有来源", "must_not": "重复追问已确认事实"},
            {"rule_id": "K03-R2", "when": "未知会改变业务结论", "must": "保留为未知并标明影响", "must_not": "把推断升级为事实或长期知识"},
            {"rule_id": "K03-R3", "when": "用户明确确认候选规则", "must": "只在确认事件后转为 confirmed", "must_not": "由模型参数自行确认"},
        ],
    },
    "K04": {
        "title": "无变化时保持安静，新证据到来后恢复",
        "facts": [
            ("workbench.DONGBA.sourceRevision", "weekly_operations", "feishu://ImtOsrt7yhTAbptIGPncik1mn2q/revision/9753/东坝店", "observed"),
            ("workbench.DONGBA.daily.2026-08-20.boxOffice", "daily_operations", "feishu://ImtOsrt7yhTAbptIGPncik1mn2q/revision/9753/东坝周每日销售对比", "observed"),
            ("workbench.DONGBA.daily.2026-08-21.boxOffice", "daily_operations", "feishu://ImtOsrt7yhTAbptIGPncik1mn2q/revision/9753/东坝周每日销售对比", "observed"),
        ],
        "inputs": [
            "这周先别因为东坝连续两天波动就每天来问我；没有新来源时保持安静。",
            "刚才这组数字没变，不需要重复提醒，也不要新增一条同样的跟进。",
            "现在飞书来源 revision 还是 9753，先按无变化处理，等有新版本再看。",
            "如果来源版本真的更新，再提醒我核对 8 月 20、21 日的日票房，不要把旧提醒重复发一遍。",
        ],
        "kinds": ["user_message", "silence_observed", "user_message", "opportunity"],
        "changes": [
            {"change_id": "K04-C1", "at_event": 0, "type": "silence_preference", "from": "无本轮提醒限制", "to": "无新证据不重复打扰"},
            {"change_id": "K04-C2", "at_event": 3, "type": "new_source_version", "from": "revision 9753", "to": "仅在版本变化后恢复提醒"},
        ],
        "rules": [
            {"rule_id": "K04-R1", "when": "证据和用户意图均未变化", "must": "不重复联系、不复制 concern", "must_not": "把沉默当成新的负面反馈"},
            {"rule_id": "K04-R2", "when": "新来源版本出现", "must": "按新版本恢复并引用变化点", "must_not": "以旧版本结论冒充新证据"},
        ],
    },
    "K05": {
        "title": "个人生活场景中的自然主动性",
        "facts": [
            ("profile.name", "companion_profile", "sqlite://companions/1", "confirmed"),
            ("schedule.2026-09-05", "persona_daily_schedule", "sqlite://companion_daily_schedule/2026-09-05", "observed"),
            ("profile.companion.current_scene", "companion_profile", "sqlite://companions/1", "confirmed"),
        ],
        "inputs": [
            "我今天在图书馆把笔记整理完了，晚上想听你讲点轻松的；工作先不用追着问。",
            "你可以接着我刚才说的图书馆和笔记聊一句，但别假装知道我没说过的细节。",
            "如果我暂时没回，就先停在这里，不要连续发好几条把普通聊天变成任务。",
            "我现在又有空了，接着刚才的轻松话题就好，别把已经结束的工作线硬拉回来。",
        ],
        "kinds": ["user_message", "opportunity", "silence_observed", "user_message"],
        "changes": [
            {"change_id": "K05-C1", "at_event": 0, "type": "personal_opportunity", "from": "日程中有图书馆场景", "to": "用户主动提供当晚聊天机会"},
            {"change_id": "K05-C2", "at_event": 2, "type": "no_reply", "from": "可自然交流", "to": "无回复，不扩大联系"},
        ],
        "rules": [
            {"rule_id": "K05-R1", "when": "用户给出个人生活机会", "must": "可基于来源场景提出一个具体、低压力回应", "must_not": "等待不存在的业务任务或编造个人经历"},
            {"rule_id": "K05-R2", "when": "用户无回复", "must": "保持静默并保留可恢复意图", "must_not": "自动连发或新增长期 concern"},
        ],
    },
    "K06": {
        "title": "旧媒介意图遇到新工作插入",
        "facts": [
            ("profile.companion.last_photo_at", "companion_profile", "sqlite://companions/1", "confirmed"),
            ("profile.companion.last_photo_caption", "companion_profile", "sqlite://companions/1", "confirmed"),
            ("task.1.status", "open_loop", "sqlite://companion_open_loops/1", "confirmed"),
            ("workbench.ZHONGYING.daily.2026-08-21.boxOffice", "daily_operations", "feishu://ImtOsrt7yhTAbptIGPncik1mn2q/revision/9753/中影周每日销售对比", "observed"),
        ],
        "inputs": [
            "那张操场边天快黑的照片我还想看；如果今天要先把中影的数据补完，就把照片放到后面。",
            "现在先处理 8 月 21 日中影日票房，照片不要因为旧意图自动发出去。",
            "如果旧照片素材已经不适合当前版本，就告诉我素材不可用，别拿旧图冒充新回应。",
            "数据这条完成后，再判断照片是继续准备、换成文字，还是等我重新给素材。",
        ],
        "kinds": ["user_message", "user_message", "opportunity", "user_message"],
        "changes": [
            {"change_id": "K06-C1", "at_event": 0, "type": "media_intent", "from": "最近照片来源存在", "to": "用户希望继续照片意图"},
            {"change_id": "K06-C2", "at_event": 1, "type": "work_insertion", "from": "照片优先", "to": "中影日票房成为当前优先意图"},
            {"change_id": "K06-C3", "at_event": 2, "type": "asset_condition", "from": "旧素材可能可用", "to": "必须重新核对素材版本"},
        ],
        "rules": [
            {"rule_id": "K06-R1", "when": "新工作插入且媒介意图未完成", "must": "保留意图但禁止发送过期/不匹配素材", "must_not": "为完成旧动作越过当前意图"},
            {"rule_id": "K06-R2", "when": "素材不可用或版本变旧", "must": "输出可解释 fallback（文字/等待新素材）", "must_not": "发送未经确认的旧个人媒体"},
        ],
    },
    "K07": {
        "title": "局部拒绝不污染其他责任",
        "facts": [
            ("profile.companion.forbidden_topics", "companion_profile", "sqlite://companions/1", "confirmed"),
            ("workbench.DONGBA.core.reception_traffic", "weekly_operations", "feishu://ImtOsrt7yhTAbptIGPncik1mn2q/revision/9753/东坝店", "observed"),
            ("schedule.2026-09-05", "persona_daily_schedule", "sqlite://companion_daily_schedule/2026-09-05", "observed"),
        ],
        "inputs": [
            "政治先不聊，换成东坝那周的日票房；如果聊完工作，再说说你今天在图书馆做了什么。",
            "拒绝只针对政治这个话题，东坝数据和普通生活聊天都可以继续。",
            "别因为一个话题被拒绝，就把其他已经授权的工作和个人线全部静音。",
            "先把日票房的来源和口径说清，再自然接回图书馆，不要重新碰刚才被拒绝的主题。",
        ],
        "kinds": ["user_message", "user_message", "opportunity", "user_message"],
        "changes": [
            {"change_id": "K07-C1", "at_event": 0, "type": "local_boundary", "from": "政治在资料中为禁区", "to": "用户明确要求在当前话题维度拒绝"},
            {"change_id": "K07-C2", "at_event": 1, "type": "scope_preservation", "from": "未区分话题范围", "to": "业务和其他个人话题仍可用"},
        ],
        "rules": [
            {"rule_id": "K07-R1", "when": "命中一个明确禁区", "must": "只拒绝该话题并给出自然替代", "must_not": "拒绝整段会话或抹掉其他责任"},
            {"rule_id": "K07-R2", "when": "替代话题有来源", "must": "继续使用来源约束下的业务/个人上下文", "must_not": "为了转移话题杜撰新事实"},
        ],
    },
    "K08": {
        "title": "用户改变目标后暂停旧方向",
        "facts": [
            ("task.2.title", "open_loop", "sqlite://companion_open_loops/2", "confirmed"),
            ("task.2.status", "open_loop", "sqlite://companion_open_loops/2", "confirmed"),
            ("workbench.ZHONGYING.sourceRevision", "weekly_operations", "feishu://ImtOsrt7yhTAbptIGPncik1mn2q/revision/9753/中影店", "observed"),
        ],
        "inputs": [
            "中影和科技馆的关联先别按原来的方向做了，先只核对客流口径；证据不足就搁置，不要硬凑结论。",
            "原来的关联责任保留记录，但当前目标改成确认字段定义和来源，不是马上解释原因。",
            "如果只找到场域客流，没有接待客流，就停在缺口，不要把两列混成一个数字。",
            "等我再给新证据时再恢复关联分析，当前先把暂停条件记清楚。",
        ],
        "kinds": ["user_message", "user_message", "opportunity", "user_message"],
        "changes": [
            {"change_id": "K08-C1", "at_event": 0, "type": "goal_revision", "from": "寻找中影-科技馆关联", "to": "先核对客流口径"},
            {"change_id": "K08-C2", "at_event": 2, "type": "insufficient_evidence", "from": "可继续探索", "to": "满足条件前 park，不完成"},
        ],
        "rules": [
            {"rule_id": "K08-R1", "when": "用户明确改变目标", "must": "更新当前意图并保留旧责任的可恢复性", "must_not": "继续按旧目标消耗动作或假装完成"},
            {"rule_id": "K08-R2", "when": "证据不足", "must": "进入 parked/等待条件并记录条件", "must_not": "把暂停写成 resolved"},
        ],
    },
    "K09": {
        "title": "临时查询不强行创建长期责任",
        "facts": [
            ("workbench.DONGBA.daily.2026-08-21.boxOffice", "daily_operations", "feishu://ImtOsrt7yhTAbptIGPncik1mn2q/revision/9753/东坝周每日销售对比", "observed"),
            ("workbench.DONGBA.daily.2026-08-21.traffic", "daily_operations", "feishu://ImtOsrt7yhTAbptIGPncik1mn2q/revision/9753/东坝 客流", "observed"),
            ("profile.goal", "companion_profile", "sqlite://companions/1", "confirmed"),
        ],
        "inputs": [
            "先帮我看 8 月 21 日东坝的票房，给数字和来源就行；这次临时查询别变成长期跟进。",
            "如果查到 2730.3，就把日期、门店和口径一起写清，不要顺手创建一个 concern。",
            "这次查询到这里就收住，后面的长期事项按原来的责任处理。",
            "以后真要持续跟进，我会单独说；现在不要因为一次问答制造提醒。",
        ],
        "kinds": ["user_message", "user_message", "silence_observed", "user_message"],
        "changes": [
            {"change_id": "K09-C1", "at_event": 0, "type": "temporary_query", "from": "无临时查询", "to": "指定门店+日期+指标的一次性读取"},
            {"change_id": "K09-C2", "at_event": 2, "type": "scope_end", "from": "查询进行中", "to": "查询完成且不产生持久责任"},
        ],
        "rules": [
            {"rule_id": "K09-R1", "when": "用户明确表示一次性查询", "must": "直接回答并引用精确来源", "must_not": "创建或升级长期 concern"},
            {"rule_id": "K09-R2", "when": "查询范围结束", "must": "收束当前意图", "must_not": "把临时查询混入原有责任历史"},
        ],
    },
    "K10": {
        "title": "来源纠错后使旧结论失效",
        "facts": [
            ("workbench.DONGBA.core.reception_traffic", "weekly_operations", "feishu://ImtOsrt7yhTAbptIGPncik1mn2q/revision/9753/东坝店", "observed"),
            ("workbench.DONGBA.daily.2026-08-21.traffic", "daily_operations", "feishu://ImtOsrt7yhTAbptIGPncik1mn2q/revision/9753/东坝 客流", "observed"),
            ("workbench.DONGBA.sourceRevision", "weekly_operations", "feishu://ImtOsrt7yhTAbptIGPncik1mn2q/revision/9753/东坝店", "observed"),
        ],
        "inputs": [
            "我刚发现上次把东坝 8 月 21 日的场域客流当成接待客流了；按新口径修正，旧结论先别沿用。",
            "现在 291 是日场域客流，周接待客流 183 不是同一个字段；请把这次纠错和来源版本一起记下来。",
            "之前基于混口径得出的判断全部降级为待复核，不要只改一句摘要继续引用。",
            "复核完成前，只能报告两个字段各自的值和差异，不能再给关联结论。",
        ],
        "kinds": ["user_message", "user_message", "opportunity", "user_message"],
        "changes": [
            {"change_id": "K10-C1", "at_event": 0, "type": "source_correction", "from": "场域客流被当作接待客流", "to": "两个字段按来源分离"},
            {"change_id": "K10-C2", "at_event": 2, "type": "stale_invalidation", "from": "旧结论可见", "to": "旧结论待复核且不可复用"},
        ],
        "rules": [
            {"rule_id": "K10-R1", "when": "用户纠正来源或字段口径", "must": "保留新旧来源关系并使旧结论失效", "must_not": "静默覆盖来源或沿用过时洞见"},
            {"rule_id": "K10-R2", "when": "纠错尚未完成验证", "must": "只报告可独立核对的字段", "must_not": "输出未经复核的因果/关联判断"},
        ],
    },
    "K11": {
        "title": "有明确目标时自主准备但不越权承诺",
        "facts": [
            ("task.2.title", "open_loop", "sqlite://companion_open_loops/2", "confirmed"),
            ("research_archive", "frozen_research_archive", "research://account:1:companion:1/archive", "observed"),
            ("workbench.ZHONGYING.sourceRefs", "weekly_operations", "feishu://ImtOsrt7yhTAbptIGPncik1mn2q/revision/9753/中影店", "observed"),
        ],
        "inputs": [
            "关于中影和科技馆客流回落，先把现有证据按来源列出来，不要替我联系别人；下一步只做一份核对清单。",
            "你可以在冻结资料里自主整理字段、日期和缺口，但不要发消息、改飞书表或承诺外部动作。",
            "清单里要把‘已有证据’和‘还需要谁确认’分开，后者只是待确认项，不是已经联系过。",
            "先交一份可复核的准备结果，我确认后再决定是否继续外部协调。",
        ],
        "kinds": ["user_message", "opportunity", "user_message", "user_message"],
        "changes": [
            {"change_id": "K11-C1", "at_event": 0, "type": "authorized_preparation", "from": "开放证据责任", "to": "授权整理冻结来源和核对清单"},
            {"change_id": "K11-C2", "at_event": 1, "type": "boundary", "from": "可准备", "to": "明确禁止外部联系和外部写入"},
        ],
        "rules": [
            {"rule_id": "K11-R1", "when": "目标清楚但未授权外部动作", "must": "自主完成内部读取、整理和缺口标注", "must_not": "联系第三方、修改源表或声称已协调"},
            {"rule_id": "K11-R2", "when": "下一步需要用户或外部确认", "must": "列为待确认条件并停止越权动作", "must_not": "把准备结果当成最终结论"},
        ],
    },
    "K12": {
        "title": "长期累积接近容量并经历重启",
        "facts": [
            ("profile.owner", "companion_profile", "sqlite://companions/1", "confirmed"),
            ("task.2.status", "open_loop", "sqlite://companion_open_loops/2", "confirmed"),
            ("task.3.status", "open_loop", "sqlite://companion_open_loops/3", "confirmed"),
            ("workbench.ZHONGYING.sourceRevision", "weekly_operations", "feishu://ImtOsrt7yhTAbptIGPncik1mn2q/revision/9753/中影店", "observed"),
        ],
        "inputs": [
            "我又补了一条重要变化：中影和科技馆的关联证据来了；先保留现有责任，容量满了就解释容量，不要删旧事项。",
            "如果当前最多只能保留 12 条，就拒绝新增那条并告诉我原因；已有事项的 id、版本和来源不能变。",
            "现在重启执行器，重启后继续同一条 concern 和同一项责任，不要重复发送上一条已经送达的内容。",
            "重启后先读取持久状态，再处理这次新证据；如果版本不一致，按冲突处理，不要静默覆盖。",
        ],
        "kinds": ["user_message", "opportunity", "user_message", "user_message"],
        "changes": [
            {"change_id": "K12-C1", "at_event": 0, "type": "important_new_input", "from": "已有开放责任", "to": "出现新的关联证据且需要保留责任"},
            {"change_id": "K12-C2", "at_event": 1, "type": "capacity_boundary", "from": "可新增", "to": "达到 12 条 active 后解释性拒绝"},
            {"change_id": "K12-C3", "at_event": 2, "type": "restart", "from": "同一执行器进程", "to": "关闭并重新打开持久状态后继续"},
        ],
        "rules": [
            {"rule_id": "K12-R1", "when": "active concern 达到上限", "must": "解释容量拒绝并保留既有责任", "must_not": "静默删除、合并或覆盖旧 concern"},
            {"rule_id": "K12-R2", "when": "执行器重启", "must": "恢复意图/concern/task 的 id、版本、状态与送达事实", "must_not": "重复发送已送达片段或从空状态重新开始"},
            {"rule_id": "K12-R3", "when": "恢复后发现版本冲突", "must": "拒绝旧版本写入并留下可追溯冲突证据", "must_not": "静默覆盖较新的持久状态"},
        ],
        "controlled_overlay": {
            "type": "evaluator_seed_only",
            "active_concerns": 12,
            "reason": "真实快照当前没有 12 条 active concerns；为测试达到上限后的拒绝只在隔离轨迹中注入，不冒充用户初态或语义事实。",
            "worker_receives": False,
        },
    },
}


# The source selectors above are intentionally retained as the frozen data
# boundary.  This second register is the executable fixture register.  It is
# kept separate so a reviewer can see which values came from the source and
# which values are an explicitly-labelled experimental condition.  In
# particular, these strings are user messages, not acceptance instructions.
J05_SCENARIO_OVERRIDES: dict[str, dict[str, Any]] = {
    "K01": {
        "inputs": [
            "我先看一下东坝这周的经营数字，想知道每天的变化。",
            None,
            "周数据能先给我一个总览，细项我晚点再核。",
            "我刚空下来，继续看东坝那组数字吧。",
        ],
        "kinds": ["user_message", "opportunity", "user_message", "user_message"],
        "event_payloads": [
            {"input_origin": "user", "text": "我先看一下东坝这周的经营数字，想知道每天的变化。"},
            {"input_origin": "controller_opportunity", "opportunity_id": "personal-life-window", "state": "available", "source_refs": ["sqlite://companion_daily_schedule/2026-09-04"]},
            {"input_origin": "user", "text": "周数据能先给我一个总览，细项我晚点再核。"},
            {"input_origin": "user", "text": "我刚空下来，继续看东坝那组数字吧。"},
        ],
        "interventions": [
            {"intervention_id": "K01-I1", "at_event": 0, "type": "experimental_condition", "target": {"file": "context.json", "json_pointer": "/owners/account:1:companion:1/history"}, "operation": "replace", "new_value": [], "reason": "冷启动移除共同历史；企业资料仍保留；不是伪造历史"},
            {"intervention_id": "K01-I2", "at_event": 0, "type": "experimental_condition", "target": {"file": "context.json", "json_pointer": "/owners/account:1:companion:1/profile/companion/shared_memory"}, "operation": "replace", "new_value": None, "reason": "冷启动移除关系偏好；企业资料仍保留"},
            {"intervention_id": "K01-I3", "at_event": 0, "type": "experimental_condition", "target": {"owner": "account:1:companion:1", "scope": "relationship_state_and_searchable_memory"}, "operation": "cold_start_relationship_filter", "reason": "冷启动移除双方关系阶段/亲密度及关系性记忆的可检索入口；保留企业资料、角色成人设定和个人日程；仅作用于隔离快照"},
        ],
        "assertions": [
            {"assertion_id": "K01-A1", "check": "冷启动轨迹没有共同历史、关系阶段/亲密度或关系性可检索记忆，但企业资料、角色设定和个人日程存在", "evidence": ["initial-state.json", "interventions.jsonl", "actual-prompts.jsonl"]},
            {"assertion_id": "K01-A2", "check": "机会事件是 controller_opportunity 结构，不是 user_message", "evidence": ["input-events.jsonl"]},
        ],
    },
    "K02": {
        "inputs": [
            "中影店和科技馆那组客流我今天想接着看。",
            None,
            "先把现在能对上的部分列出来，剩下的我再补材料。",
            "下次从这条继续。",
        ],
        "kinds": ["user_message", "task_due", "user_message", "user_message"],
        "event_payloads": [
            {"input_origin": "user", "text": "中影店和科技馆那组客流我今天想接着看。"},
            {"input_origin": "task_scheduler", "task_ref": "j05-due-task-20260909-1100", "task_version": 0, "due_at": "2026-09-09T11:00:00+08:00"},
            {"input_origin": "user", "text": "先把现在能对上的部分列出来，剩下的我再补材料。"},
            {"input_origin": "user", "text": "下次从这条继续。"},
        ],
        "interventions": [
            {"intervention_id": "K02-I1", "at_event": 0, "type": "task_materialization", "target": {"task_id": "j05-due-task-20260909-1100", "source_selector": "task.2"}, "operation": "create_authorized_due_task", "due_at": "2026-09-09T11:00:00+08:00", "reason": "从冻结的开放责任派生隔离任务，不冒充源库已有到期记录"},
        ],
        "assertions": [
            {"assertion_id": "K02-A1", "check": "task_due 实际引用隔离任务 ID、期限和版本", "evidence": ["interventions.jsonl", "input-events.jsonl", "state.db"]},
            {"assertion_id": "K02-A2", "check": "到期责任保持 open，不能由到期事件单独变为 completed", "evidence": ["state.db", "trajectory-result.json"]},
        ],
    },
    "K03": {
        "inputs": [
            "我在整理东坝的客流表，想先把几个字段对齐。",
            "8 月 20 日和 21 日的数我能看见，但它们在表里代表什么还不完全清楚。",
            None,
            "对，后面我说接待客流时就按刚才这个区分来。",
        ],
        "kinds": ["user_message", "user_message", "opportunity", "user_message"],
        "event_payloads": [
            {"input_origin": "user", "text": "我在整理东坝的客流表，想先把几个字段对齐。"},
            {"input_origin": "user", "text": "8 月 20 日和 21 日的数我能看见，但它们在表里代表什么还不完全清楚。"},
            {"input_origin": "controller_opportunity", "opportunity_id": "knowledge-gap-review", "state": "known_source_unknown_definition", "source_refs": ["feishu://ImtOsrt7yhTAbptIGPncik1mn2q/revision/9753/东坝 客流"]},
            {"input_origin": "user", "text": "对，后面我说接待客流时就按刚才这个区分来。", "user_confirmation_target": "latest_candidate"},
        ],
        "interventions": [
            {"intervention_id": "K03-I1", "at_event": 0, "type": "fixture_condition", "target": {"source_selector": "workbench.DONGBA.daily.2026-08-20.traffic"}, "operation": "assert_known_source_present", "reason": "已知资料来自冻结快照"},
            {"intervention_id": "K03-I2", "at_event": 1, "type": "fixture_condition", "target": {"field": "traffic_definition"}, "operation": "assert_unknown_not_materialized", "reason": "指标定义未知且影响方案"},
        ],
        "assertions": [
            {"assertion_id": "K03-A1", "check": "已知数据能检索，未知定义在用户确认前不是 confirmed", "evidence": ["tool-results in trace.jsonl", "state.db"]},
            {"assertion_id": "K03-A2", "check": "确认事件只在实际 candidate 存在后绑定并复用", "evidence": ["input-events.jsonl", "state.db", "trace.jsonl"]},
        ],
    },
    "K04": {
        "inputs": [
            "东坝这组数字我先放着，等资料有变化再接着看。",
            None,
            "我刚看了一眼，手头还是同一版表。",
            None,
        ],
        "kinds": ["user_message", "silence_observed", "user_message", "opportunity"],
        "event_payloads": [
            {"input_origin": "user", "text": "东坝这组数字我先放着，等资料有变化再接着看。"},
            {"input_origin": "transport_observer", "delivered_message_selector": "latest_sent_message", "observed_at": "2026-09-09T11:20:00+08:00"},
            {"input_origin": "user", "text": "我刚看了一眼，手头还是同一版表。"},
            {"input_origin": "controller_opportunity", "opportunity_id": "source-revision-arrived", "state": "new_source_version_available", "source_refs": ["feishu://ImtOsrt7yhTAbptIGPncik1mn2q/revision/9754/东坝店"]},
        ],
        "interventions": [
            {"intervention_id": "K04-I1", "at_event": 3, "type": "source_update", "target": {"file": "records.json", "source_selector": "workbench.DONGBA.sourceRevision"}, "operation": "replace_source_revision", "old_expected": "9753", "new_value": "9754", "reason": "新资料到达时才物化；不可在前序 prompt 中出现"},
        ],
        "assertions": [
            {"assertion_id": "K04-A1", "check": "同版资料下 silence_observed 只引用已送达片段，不伪造用户回复", "evidence": ["input-events.jsonl", "trace.jsonl"]},
            {"assertion_id": "K04-A2", "check": "9754 只在 intervention 之后可见", "evidence": ["interventions.jsonl", "actual-prompts.jsonl"]},
        ],
    },
    "K05": {
        "inputs": [
            "我今天在图书馆待了一下午，晚上想换个轻松的话题。",
            None,
            None,
            "我又想起下午在书架间乱逛的事了。",
        ],
        "kinds": ["user_message", "opportunity", "silence_observed", "user_message"],
        "event_payloads": [
            {"input_origin": "user", "text": "我今天在图书馆待了一下午，晚上想换个轻松的话题。"},
            {"input_origin": "controller_opportunity", "opportunity_id": "persona-scene-window", "state": "low_participation_personal_context", "source_refs": ["sqlite://companion_daily_schedule/2026-09-04"]},
            {"input_origin": "transport_observer", "delivered_message_selector": "latest_sent_message", "observed_at": "2026-09-09T12:30:00+08:00"},
            {"input_origin": "user", "text": "我又想起下午在书架间乱逛的事了。"},
        ],
        "interventions": [
            {"intervention_id": "K05-I1", "at_event": 1, "type": "source_update", "target": {"file": "context.json", "json_pointer": "/owners/account:1:companion:1/profile/companion/current_scene"}, "operation": "replace", "old_expected": "日常", "new_value": "图书馆后的夜间整理", "reason": "角色生活变化来自隔离 persona 来源"},
            {"intervention_id": "K05-I2", "at_event": 3, "type": "source_update", "target": {"file": "context.json", "json_pointer": "/owners/account:1:companion:1/profile/companion/current_scene"}, "operation": "replace", "old_expected": "图书馆后的夜间整理", "new_value": "操场边散步后的回忆", "reason": "第二个生活情节在后续虚拟时间才到达"},
        ],
        "assertions": [
            {"assertion_id": "K05-A1", "check": "低参与时由 transport_observer 记录 silence，不能当用户发言", "evidence": ["input-events.jsonl"]},
            {"assertion_id": "K05-A2", "check": "个人情节仅引用来源，不把未说过的细节当事实", "evidence": ["actual-prompts.jsonl", "trace.jsonl"]},
        ],
    },
    "K06": {
        "inputs": [
            "操场边那张天快黑的画面我还记得，今天先看中影的数据。",
            "8 月 21 日中影的日票房先放到当前这件事里。",
            None,
            "数据这边看完了，再看看那张旧素材现在还能不能用。",
        ],
        "kinds": ["user_message", "user_message", "opportunity", "user_message"],
        "event_payloads": [
            {"input_origin": "user", "text": "操场边那张天快黑的画面我还记得，今天先看中影的数据。"},
            {"input_origin": "user", "text": "8 月 21 日中影的日票房先放到当前这件事里。"},
            {"input_origin": "controller_opportunity", "opportunity_id": "media-preparation-window", "state": "media_preparation_interrupted_by_work", "source_refs": ["sqlite://companion_photo_log/1", "feishu://ImtOsrt7yhTAbptIGPncik1mn2q/revision/9753/中影周每日销售对比"]},
            {"input_origin": "user", "text": "数据这边看完了，再看看那张旧素材现在还能不能用。"},
        ],
        "interventions": [
            {"intervention_id": "K06-I1", "at_event": 0, "type": "paired_capability_condition", "target": {"key": "media_available"}, "operation": "set_pair_value", "values": [True, False], "reason": "同一初态配对，仅改变图片 gateway 可用性"},
            {"intervention_id": "K06-I2", "at_event": 2, "type": "insertion", "target": {"opportunity_id": "media-preparation-window"}, "operation": "inject_work_opportunity_during_media_prepare", "reason": "插入由控制器产生，不是用户发言"},
        ],
        "assertions": [
            {"assertion_id": "K06-A1", "check": "图片可用/不可用成对运行且只差能力条件", "evidence": ["initial-state.json", "interventions.jsonl"]},
            {"assertion_id": "K06-A2", "check": "旧媒介未被自动发送；不可用分支有实际 fallback 或明确 gap", "evidence": ["trace.jsonl", "trajectory-result.json"]},
        ],
    },
    "K07": {
        "inputs": [
            "政治话题先放一放，我们先看东坝这周的数字。",
            "东坝这条看完后，我想听你说说今天过得怎么样。",
            None,
            "先把东坝的来源对上，再聊点日常。",
        ],
        "kinds": ["user_message", "user_message", "opportunity", "user_message"],
        "event_payloads": [
            {"input_origin": "user", "text": "政治话题先放一放，我们先看东坝这周的数字。"},
            {"input_origin": "user", "text": "东坝这条看完后，我想听你说说今天过得怎么样。"},
            {"input_origin": "controller_opportunity", "opportunity_id": "other-personal-opportunity", "state": "available", "source_refs": ["sqlite://companion_daily_schedule/2026-09-04"]},
            {"input_origin": "user", "text": "先把东坝的来源对上，再聊点日常。"},
        ],
        "interventions": [{"intervention_id": "K07-I1", "at_event": 0, "type": "fixture_condition", "target": {"source_selector": "profile.companion.forbidden_topics"}, "operation": "assert_boundary_present", "reason": "局部拒绝条件来自冻结资料"}],
        "assertions": [
            {"assertion_id": "K07-A1", "check": "拒绝范围只覆盖具体话题，业务与其他生活机会继续存在", "evidence": ["actual-prompts.jsonl", "trajectory-result.json"]},
        ],
    },
    "K08": {
        "inputs": [
            "中影和科技馆这件事，我现在更想先弄清客流字段。",
            "原来那条关联先放着，先把口径看明白。",
            None,
            "等新的材料到了，再回头看两边是否有关联。",
        ],
        "kinds": ["user_message", "user_message", "opportunity", "user_message"],
        "event_payloads": [
            {"input_origin": "user", "text": "中影和科技馆这件事，我现在更想先弄清客流字段。"},
            {"input_origin": "user", "text": "原来那条关联先放着，先把口径看明白。"},
            {"input_origin": "controller_opportunity", "opportunity_id": "insufficient-evidence", "state": "only_one_metric_available", "source_refs": ["feishu://ImtOsrt7yhTAbptIGPncik1mn2q/revision/9753/中影店"]},
            {"input_origin": "user", "text": "等新的材料到了，再回头看两边是否有关联。"},
        ],
        "interventions": [{"intervention_id": "K08-I1", "at_event": 0, "type": "fixture_condition", "target": {"task_id": "2", "source_selector": "task.2"}, "operation": "seed_prepared_old_concern", "reason": "隔离初态含旧关切及准备结果，用户随后自然改变目标"}],
        "assertions": [{"assertion_id": "K08-A1", "check": "当前意图转为字段口径，旧责任仍可恢复且不是 resolved", "evidence": ["state.db", "trace.jsonl"]}],
    },
    "K09": {
        "inputs": [
            "帮我看一下 8 月 21 日东坝的票房。",
            "日期和门店写在结果旁边就好。",
            None,
            "好，这个数字先到这里。",
        ],
        "kinds": ["user_message", "user_message", "silence_observed", "user_message"],
        "event_payloads": [
            {"input_origin": "user", "text": "帮我看一下 8 月 21 日东坝的票房。"},
            {"input_origin": "user", "text": "日期和门店写在结果旁边就好。"},
            {"input_origin": "transport_observer", "delivered_message_selector": "latest_sent_message", "observed_at": "2026-09-09T13:20:00+08:00"},
            {"input_origin": "user", "text": "好，这个数字先到这里。"},
        ],
        "interventions": [{"intervention_id": "K09-I1", "at_event": 0, "type": "fixture_condition", "target": {"concerns": "owner"}, "operation": "assert_no_related_concern", "reason": "初态没有相关持续关切"}],
        "assertions": [{"assertion_id": "K09-A1", "check": "一次性门店/日期查询可回答，且没有新增长期 concern", "evidence": ["tool-results in trace.jsonl", "state.db"]}],
    },
    "K10": {
        "inputs": [
            "我对表时发现 8 月 21 日的两个客流字段不是一回事。",
            "这次按各自的列重新看，先把旧判断放回去复核。",
            None,
            "复核之前先只给我两个字段各自的数。",
        ],
        "kinds": ["user_message", "user_message", "opportunity", "user_message"],
        "event_payloads": [
            {"input_origin": "user", "text": "我对表时发现 8 月 21 日的两个客流字段不是一回事。"},
            {"input_origin": "user", "text": "这次按各自的列重新看，先把旧判断放回去复核。"},
            {"input_origin": "controller_opportunity", "opportunity_id": "corrected-source-arrived", "state": "replacement_source_materialized", "source_refs": ["feishu://ImtOsrt7yhTAbptIGPncik1mn2q/revision/9754/东坝 客流"]},
            {"input_origin": "user", "text": "复核之前先只给我两个字段各自的数。"},
        ],
        "interventions": [{"intervention_id": "K10-I1", "at_event": 2, "type": "source_update", "target": {"file": "records.json", "source_selector": "workbench.DONGBA.daily.2026-08-21.traffic"}, "operation": "replace_source_revision", "old_expected": "9753", "new_value": "9754", "reason": "替换来源实际物化后才通知 loop"}],
        "assertions": [{"assertion_id": "K10-A1", "check": "旧事实进入摘要后，来源替换会留下 before/after 并使旧版本不可复用", "evidence": ["interventions.jsonl", "trace.jsonl", "state.db"]}],
    },
    "K11": {
        "inputs": [
            "中影和科技馆的客流回落，我想先把手头材料理一遍。",
            None,
            "现有材料先按来源和日期摆好，缺的部分单独列出来。",
            "等我看过这份准备结果，再决定下一步。",
        ],
        "kinds": ["user_message", "opportunity", "user_message", "user_message"],
        "event_payloads": [
            {"input_origin": "user", "text": "中影和科技馆的客流回落，我想先把手头材料理一遍。"},
            {"input_origin": "controller_opportunity", "opportunity_id": "research-ready", "state": "frozen_research_available", "source_refs": ["research://account:1:companion:1/archive"]},
            {"input_origin": "user", "text": "现有材料先按来源和日期摆好，缺的部分单独列出来。"},
            {"input_origin": "user", "text": "等我看过这份准备结果，再决定下一步。"},
        ],
        "interventions": [{"intervention_id": "K11-I1", "at_event": 1, "type": "fixture_condition", "target": {"selector": "research_archive"}, "operation": "assert_archive_available", "reason": "可用研究资料来自冻结归档"}],
        "assertions": [{"assertion_id": "K11-A1", "check": "有资料时可自主准备，但没有外部写入或越权承诺", "evidence": ["trace.jsonl", "tool-results in trace.jsonl", "state.db"]}],
    },
    "K12": {
        "inputs": [
            "中影 8 月 15 到 21 日这组经营数据我想继续跟，先把接待客流和票房的关系记着。",
            None,
            "重启后接着中影这条，看看新资料和旧版差在哪。",
            "先看看现在保存下来的状态，再决定接下来该查什么。",
        ],
        "kinds": ["user_message", "opportunity", "user_message", "user_message"],
        "event_payloads": [
            {"input_origin": "user", "text": "中影 8 月 15 到 21 日这组经营数据我想继续跟，先把接待客流和票房的关系记着。", "concern_query": "中影经营证据续接"},
            {"input_origin": "controller_opportunity", "opportunity_id": "important-evidence-arrived", "state": "materialized_experimental_source_update", "concern_query": "中影经营证据续接", "source_refs": ["experiment://account:1:companion:1/j05/k12/revision/2/中影店"]},
            {"input_origin": "user", "text": "重启后接着中影这条，看看新资料和旧版差在哪。", "concern_query": "中影经营证据续接"},
            {"input_origin": "user", "text": "先看看现在保存下来的状态，再决定接下来该查什么。", "concern_query": "中影经营证据续接"},
        ],
        "interventions": [
            {"intervention_id": "K12-I1", "at_event": 0, "type": "experimental_condition", "target": {"store": "concerns"}, "operation": "seed_exactly_12_active_concerns", "count": 12, "reason": "隔离初态实际有12项 active；其中一项绑定真实冻结旧版中影记录；不冒充源实例事实"},
            {
                "intervention_id": "K12-I2",
                "at_event": 1,
                "type": "source_update",
                "target": {"file": "records.json", "source_selector": "workbench.ZHONGYING.core.reception_traffic"},
                "operation": "materialize_experimental_record_update",
                "old_expected": {"/core/reception_traffic": 168, "/core/box_office_total": 15951.1},
                "changes": {"/core/reception_traffic": 201, "/updatedAt": "2026-09-09T11:20:00+08:00"},
                "new_value": "j05-k12-v2",
                "sheet": "中影店",
                "source_ref": "experiment://account:1:companion:1/j05/k12/revision/2/中影店",
                "base_source_ref": "feishu://ImtOsrt7yhTAbptIGPncik1mn2q/revision/9753/中影店",
                "reason": "只在隔离快照内把中影接待客流从168更新为201，票房15951.1保持不变；用于验证新证据是否改变既有关切，不声称飞书真实存在9754",
            },
        ],
        "assertions": [
            {"assertion_id": "K12-A1", "check": "事件0前 state.db 实际有12项 active concern，新增重要输入触发容量边界", "evidence": ["initial-state.json", "state.db", "trajectory-result.json"]},
            {"assertion_id": "K12-A2", "check": "重启后任务、concern id/version、已送达回执仍在", "evidence": ["restart-evidence.json", "state.db", "trace.jsonl"]},
        ],
        "controlled_overlay": {
            "type": "evaluator_seed_only",
            "active_concerns": 12,
            "reason": "实际写入每条隔离轨迹的 state.db；不是只写 manifest，也不是源实例事实",
            "worker_receives": False,
        },
    },
}


for _case_id, _override in J05_SCENARIO_OVERRIDES.items():
    K_CASE_SPECS[_case_id].update(deepcopy(_override))


def _deep_get(value: Any, path: list[str]) -> Any:
    current = value
    for item in path:
        if isinstance(current, dict):
            if item not in current:
                raise KeyError(".".join(path))
            current = current[item]
        elif isinstance(current, list):
            current = next(row for row in current if isinstance(row, dict) and str(row.get("id")) == item)
        else:
            raise KeyError(".".join(path))
    return deepcopy(current)


def _record_value(records: dict[str, Any], selector: str) -> tuple[Any, str, int]:
    rows = records.get("data")
    if not isinstance(rows, list):
        raise ValueError("records.json data must be a list")
    pieces = selector.split(".")
    venue_key = pieces[1]
    record = next(row for row in rows if row.get("id") == f"WR-20260815-{venue_key}")
    row_index = rows.index(record)
    rest = pieces[2:]
    if rest and rest[0] == "daily":
        date = rest[1]
        daily = next(row for row in record.get("daily", []) if row.get("date") == date)
        value = _deep_get(daily, rest[2:]) if len(rest) > 2 else daily
        pointer = f"/data/{row_index}/daily/{record['daily'].index(daily)}"
        if len(rest) > 2:
            pointer += "/" + "/".join(rest[2:])
    elif rest and rest[0] == "sourceRevision":
        value = record.get("sourceRevision")
        pointer = f"/data/{row_index}/sourceRevision"
    else:
        value = _deep_get(record, rest)
        pointer = f"/data/{row_index}/" + "/".join(rest)
    return value, pointer, row_index


def _resolve_selector(context: dict[str, Any], records: dict[str, Any], selector: str) -> tuple[Any, str, str]:
    if selector.startswith("profile."):
        value = _deep_get(context["owners"][OWNER], ["profile", *selector.split(".")[1:]])
        pointer = "/owners/account:1:companion:1/profile/" + "/".join(selector.split(".")[1:])
        return value, pointer, CONTEXT_REL
    if selector.startswith("task."):
        task_id, field = selector.split(".", 2)[1:]
        value = _deep_get(context["owners"][OWNER], ["tasks", task_id, field])
        pointer = f"/owners/account:1:companion:1/tasks/{task_id}/{field}"
        return value, pointer, CONTEXT_REL
    if selector.startswith("memory."):
        memory_id, field, *rest = selector.split(".")[1:]
        memory = next(row for row in context["owners"][OWNER].get("memories", []) if str(row.get("source_ref", "")).endswith("/" + memory_id))
        value = _deep_get(memory, [field, *rest])
        pointer = f"/owners/account:1:companion:1/memories/{memory_id}/" + "/".join([field, *rest])
        return value, pointer, CONTEXT_REL
    if selector.startswith("schedule."):
        date = selector.split(".", 1)[1]
        schedule = next(row for row in context["owners"][OWNER].get("schedule", []) if row.get("id") == date)
        index = context["owners"][OWNER]["schedule"].index(schedule)
        return schedule, f"/owners/account:1:companion:1/schedule/{index}", CONTEXT_REL
    if selector == "research_archive":
        archive = context["owners"][OWNER].get("research_archive", [])
        return {"count": len(archive), "first": deepcopy(archive[0]) if archive else None}, "/owners/account:1:companion:1/research_archive", CONTEXT_REL
    if selector.startswith("workbench."):
        value, pointer, _ = _record_value(records, selector)
        return value, pointer, RECORDS_REL
    raise KeyError(selector)


def _source_metadata(records: dict[str, Any], selector: str, source_hint: str) -> dict[str, Any]:
    if not selector.startswith("workbench."):
        return {"source_ref": source_hint}
    venue_key = selector.split(".")[1]
    record = next(row for row in records.get("data", []) if row.get("id") == f"WR-20260815-{venue_key}")
    kind = "周经营、渠道、次卡分项与累计、项目播控"
    if ".daily." in selector and selector.endswith("traffic"):
        kind = "日场域客流"
    elif ".daily." in selector and selector.endswith("boxOffice"):
        kind = "日票房"
    source = next((item for item in record.get("sourceRefs", []) if item.get("kind") == kind), None)
    return {"source_ref": source_hint, "source_metadata": deepcopy(source) if source else None, "source_revision": record.get("sourceRevision")}


def _load_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise ValueError(f"J05 source snapshot unreadable: {path}: {exc}") from exc


def _resolved_facts(run_root: pathlib.Path, descriptors: list[tuple[str, str, str, str]]) -> list[dict[str, Any]]:
    snapshot = run_root / "snapshot"
    context = _load_json(snapshot / "context.json")
    records = _load_json(snapshot / "workbench-data" / "runtime-state" / "records.json")
    facts = []
    for selector, kind, source_hint, epistemic_status in descriptors:
        observed, pointer, artifact_path = _resolve_selector(context, records, selector)
        source = _source_metadata(records, selector, source_hint)
        facts.append({
            "selector": selector,
            "kind": kind,
            "source_ref": source["source_ref"],
            "source_metadata": source.get("source_metadata"),
            "source_revision": source.get("source_revision"),
            "artifact_path": artifact_path,
            "json_pointer": pointer,
            "observed_value": observed,
            "epistemic_status": epistemic_status,
            "verified_at": context.get("createdAt"),
        })
    return facts


def _events(case_id: str, spec: dict[str, Any]) -> list[dict[str, Any]]:
    events = []
    payloads = spec.get("event_payloads") or [
        {"input_origin": "user", "text": text} for text in spec["inputs"]
    ]
    roles = ["initial", "registered-change", "follow-up", "boundary-or-result"]
    for index, payload in enumerate(payloads):
        kind = spec["kinds"][index]
        if kind == "user_message" and not isinstance(payload.get("text"), str):
            raise ValueError(f"{case_id} user_message requires natural text")
        if kind != "user_message" and "text" in payload:
            raise ValueError(f"{case_id} non-user event may not carry user text")
        events.append({
            "event_id": f"{case_id}:event-{index}",
            "event_index": index,
            "event_role": roles[min(index, len(roles) - 1)],
            "kind": kind,
            "virtual_time": f"2026-09-09T{10 + index:02d}:00:00+08:00",
            "payload": deepcopy(payload),
            "source_kind": {
                "user_message": "user",
                "opportunity": "controller_opportunity",
                "task_due": "task_scheduler",
                "silence_observed": "transport_observer",
                "tool_result": "tool_controller",
            }.get(kind, "controller"),
        })
    return events


def build_concern_case_manifest(*, run_root: str, source_kind: str, owner_scope: Any, prompt_paths: dict[str, str]) -> dict[str, Any]:
    root = pathlib.Path(run_root)
    cases = []
    for case_id, spec in K_CASE_SPECS.items():
        facts = _resolved_facts(root, spec["facts"])
        cases.append({
            "case_id": case_id,
            "title": spec["title"],
            "initial_state": {
                "source_kind": source_kind,
                "owner_scope": owner_scope,
                "facts": facts,
                "source_snapshots": {"context": CONTEXT_REL, "records": RECORDS_REL},
                "experimental_conditions": [
                    item for item in deepcopy(spec.get("interventions", []))
                    if item.get("type") in {"experimental_condition", "task_materialization", "paired_capability_condition"}
                ],
                "initial_state_must_be_materialized": True,
                "state_assertion": "facts are resolved from the frozen source artifacts; no user history is invented",
            },
            "key_changes": deepcopy(spec["changes"]),
            "semantic_delta": deepcopy(SEMANTIC_DELTA_REGISTRY.get(case_id, {
                "exists": False,
                "event_indices": [],
                "expected_fields": [],
                "basis": "本场景没有预登记的持续语义变化",
                "evidence": [],
            })),
            "semantic_delta_evaluation": deepcopy(SEMANTIC_DELTA_EVALUATION_REGISTRY.get(case_id, {
                "mode": "allow_none",
                "exists": False,
                "event_indices": [],
                "expected_fields": [],
                "basis": "本场景没有预登记的持续语义变化",
                "evidence": [],
                "source": "case fixture and pre-registered rule, before provider output",
            })),
            "interventions": deepcopy(spec.get("interventions", [])),
            "external_branches": [
                {"branch_id": f"{case_id}-B1", "meaning": "same entry, no semantic answer fixture", "frozen": True},
                {"branch_id": f"{case_id}-B2", "meaning": "new wording or opportunity arrives at the registered event", "frozen": True},
                {"branch_id": f"{case_id}-B3", "meaning": "boundary, evidence, silence, or restart condition is explicit", "frozen": True},
            ],
            "events": _events(case_id, spec),
            "response_rules": deepcopy(spec["rules"]),
            "assertions": deepcopy(spec.get("assertions", [])),
            "deviations": deepcopy(spec.get("deviations", [])),
            "controlled_overlay": deepcopy(spec.get("controlled_overlay")),
            "minimum_events": 4,
            "repetitions": 3,
            "worker_receives": {
                "case_id": False,
                "source_facts": False,
                "response_rules": False,
                "controlled_overlay": False,
                "expected_behavior": False,
                "oracle": False,
            },
        })
    return {
        "schemaVersion": "concern-case-manifest-v2",
        "createdAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "runRoot": run_root,
        "source_policy": {
            "initial_state_is_frozen_source_bound": True,
            "source_artifacts": [CONTEXT_REL, RECORDS_REL],
            "facts_are_verified_at_manifest_build": True,
            "unverified_external_sources_are_not_presented_as_confirmed": True,
        },
        "arms": {
            arm: {
                "prompt_path": path,
                "concerns_enabled": arm == "C",
                "repetitions": 3,
                "model_slots": 2,
                "cases": 12,
                "trajectories": 36,
            }
            for arm, path in prompt_paths.items()
        },
        "total_trajectories": 108,
        "case_count": 12,
        "cases": cases,
        "state_machine_rule": "All source facts, natural inputs, changes, branches, and response rules are frozen before any assistant output; no branch is selected after seeing output.",
        "human_review_policy": {
            "sample_generation_blocked_by_human_review": False,
            "final_subjective_conclusion_blocked_by_human_review": True,
        },
    }
