# 溪语逻辑原点与维护地图

当前开发按 [开发方案 v2](agency-development-plan-v2-2026-09-08.md) 和 [验证方案 v2](agency-validation-plan-v2-2026-09-08.md) 实施，进度见 [实施记录](agency-v2-implementation-log-2026-09-08.md)。下面的旧链路描述保留作历史对照，不应作为v2目标顺序。v2目标是先理解/选择/准备，再过原主动硬时机门；明确用户请求直接执行，最后校验结果与真实交付。

> **2026-09-08 当前状态更正**：本文以下涉及“统一动念链已接入/只观测/边界已保证”的描述须结合 [完整对照核查](agency-conformance-audit-2026-09-08.md)阅读。当前是部分实现，尚未满足开发规范；尤其准备与时机顺序、静默执行、shadow 隔离、跨轮续接、状态迁移及验收存在明确偏差。线上无新增 agency 模块/表，业务桥接目录返回404。保留本图作为现状定位资料，不作为已完成或发布证明。

更新：2026-09-07。此文件是以后修改主动联系、人格、记忆和业务辅助前的固定入口。

统一主动性、企业认知深度与沟通策略的下一阶段设计见 [溪语统一主动性、企业认知与沟通策略设计](unified-agency-and-engagement-design-2026-09-06.md)。该设计保留本文的唯一执行链和模块边界，不允许另起第二套中枢。

![溪语主动联系维护地图](assets/xiyu-proactive-maintenance-map-2026-09-06.png)

## 一句话说明

原链路仍是“同一个 canonical tick 先准备经营候选，再由原有调度决定何时考虑联系 → 原有人格与模型负责怎么说 → 原有安全/去重 → 原有微信发送”。`initiative.mjs` 位于“何时联系”和“怎么说”之间，现在会把业务、知识、约定、真实生活事实、情节照片和关系开场放入同一候选池，先选定本次想促成的变化与行动形式。没有新增第二套调度或发送系统。

## 当前唯一执行链

1. **输入信号**：时间、角色状态、对话、记忆、open loop、真实素材和企业事件。
2. **经营供给预备**：`src/proactive.mjs` 在同一个 canonical tick 的时机判断前调用 `primeEnterpriseCandidates()`；`src/enterprise_context.mjs` 请求工作台只生成当前策略需要的日报/知识事件，刷新失败不会被记成“已检查”，下一个周期会重试。
3. **排程与配额**：`src/proactive.mjs` 生成/恢复当天排程，处理时间窗、过期、睡眠、安全、未回复降频与硬间隔；经营候选只占用已有 normal/morning 主动机会，不另起发送器。
4. **时机判断**：`src/proactive_engine.mjs` 计算 motivation，并接收已选经营事件。高价值事件可以进入时机判断，不会在读取经营资料之前被普通陪伴退场规则挡掉；安全、硬间隔和去重仍在发送层生效。
5. **主动意图**：`src/initiative.mjs` 生成可行动候选，先过事实条件，再按价值、紧迫性和时机选择一个 purpose。它回答“为什么联系、想促成什么、用哪种行动、怎样才算完成”。
6. **统一动念链**：`src/proactive.mjs` 的 `runAgencyCycle()` 在 `shadow/enabled` 模式调用 `src/agency_protocol.mjs` 生成 appraisal/plan/feedback 协议，并把持续状态写入 `db.mjs` 的 `agency_intentions`、`agency_actions`、`agency_feedback`。它不另起 scheduler、selector 或 sender；`legacy` 默认不增加调用。
   准备类动作在同一入口继续执行：`lookup/analyze/research/prepare_media/wait` 先进入 `running`，再由 `deps.execute*`（或对应 adapter）落 `prepared`/`failed`；没有适配器明确记 `infra_failure` 并挂起动念，不能留下 `planned` 伪结果。`contact_*` 仍交给下方原发送器和真实回执事务。
7. **人格表达**：`src/companion.mjs` 汇总原有人格；`src/ai.mjs` 调用原有模型；`src/proactive.mjs` 提供本次主动表达约束和 enabled 模式的一次语义出站复核。
8. **复核**：`src/moderation.mjs` 处理通用出站风险，`src/intent_dedup.mjs` 处理意图复读，`src/initiative.mjs` 复核本次意图事实边界；`agency_protocol.mjs` 只复核动念/策略一致性，不按题材或固定句式拦截。
9. **投递**：文字仍由 `src/ilink.mjs` 发送，图片仍由 `src/media.mjs` 上传后交给 iLink。`initiative.mjs` 和 `agency_protocol.mjs` 都不发送消息。
10. **结果**：原有消息、对话、素材和健康记录继续落原库；新增 agency 三张表记录持续动念、动作状态和反馈；`data/initiative-ledger.jsonl` 仍只记录主动意图及动作结果的安全摘要，不保存完整私聊正文。

## 去哪里调整

| 想调整的事情 | 唯一原点 | 不应该放到哪里 |
| --- | --- | --- |
| 主动开关、每日数量、允许时间窗 | Dashboard 的 companion 设置 → `src/api.mjs` → `src/db.mjs` 字段 → `src/proactive.mjs` | 不在 initiative 中另建开关 |
| 是否在这个时机联系、未回复降频、motivation 阈值 | `src/proactive_engine.mjs` | 不让 LLM 自己决定发送时机 |
| 稳定追求、动念类型、目的、动作、回复负担、成功条件 | `src/initiative.mjs` | 不塞回随机文案 prompt，不另建 selector |
| 动念评估、动作计划、反馈 schema 与语义复核 | `config/agency-prompts.v1.json` + `src/agency_protocol.mjs` | 不把欲或状态机散落到 companion prompt |
| 持续动念、动作、用户反馈和 CAS 版本 | `src/db.mjs` 的 `agency_intentions/actions/feedback` | 不回到 JSON 临时状态或新建第二个 memory store |
| 人设、口吻、关系阶段下的表达 | `src/companion.mjs` 及既有 emotion/relationship arc 模块 | 不在 initiative 复制整套人格 |
| 记忆召回、长期摘要、约定跟进 | 既有 memory、open_loops、plan_tasks、current_works 模块 | 不在 initiative 新建记忆库 |
| 企业资料路由与事件 | `src/enterprise_context.mjs`；来源能力属于工作台 `backend/cognition/source-router.mjs` | 不让 proactive 扫全部知识库 |
| 企业主动开关、日报/补问与订单表监控策略 | `/api/companions/:id/enterprise-proactive` → `src/db.mjs` policy → `src/proactive.mjs` → `src/enterprise_context.mjs` | 不与普通陪伴开关混成一个字段；订单表事件必须带当前 accountId/companionId，不向所有绑定角色广播 |
| 文案安全、疾病/照片等真实性 | `src/moderation.mjs` | initiative 只管本次动念契约，不复制通用审核 |
| 文字/图片实际发送 | `src/ilink.mjs`、`src/media.mjs` | 禁止新建第二套发送器 |
| 为什么想发、发没发成 | `data/initiative-ledger.jsonl`；调度健康仍看 proactive health/log | 不从聊天正文反推执行成功 |

## 这次到底改了什么

本次在不替换既有发送链的前提下新增 `src/agency_protocol.mjs`、`config/agency-prompts.v1.json` 和 `db.mjs` 的三张 agency 状态表；`src/proactive.mjs` 增加可关闭的 `runAgencyCycle()` 适配层，`bot.mjs` 在 shadow/enabled 下读取等待中的动念并记录结构化反馈。旧版会随机把每日一个普通时段替换成 `photo`；现已取消。照片只有在已发生日程事实或已核验手头事项能形成情节时，才作为候选行动参与选择，最后仍交给原 `photo_planner.mjs` 与 `photo_sender.mjs`。

本轮又修正了经营供给和陪伴时机之间的断点：以前只有普通陪伴时机通过后才会刷新工作台，因此业务事件无法影响这次是否值得联系；现在每个 canonical tick 先按日报/知识策略刷新并读取少量候选，再把候选交给原有 timingDecision。工作台不再用“一天全局只能有一个事件”挡住日报和知识补全；两种 purpose 各自去重、各自受策略配额约束。知识事件还允许进入高价值、明确阻挡经营决策的诊断缺口，避免真正要命的问题只能停留在周报。刷新或读取失败时不写入检查时间，避免把连接故障伪装成“今天没有知识补全”。

当前 `initiative.mjs` 明确禁止拥有以下职责：定时器、模型客户端、记忆数据库、企业源读取和微信发送。未来若它开始承担这些职责，就说明边界已经漂移。

## 后续修改协议

1. 先从上表找到唯一原点并沿调用链确认，不凭文件名猜测。
2. 能在原模块扩展就原地扩展；需要新增模块时，必须说明现有模块为什么无法承担。
3. 新模块只允许有一个清楚职责，并由现有链路调用；不能自己再起调度或发送。
4. 若职责迁移，同一改动内删除旧执行路径并更新本图；不得让新旧两套长期同时运行。
5. 先写离线、确定性验证，再运行服务；验证主动逻辑不得依靠真实微信发送。
6. 每次改动在 `docs/validation/YYYY-MM-DD/` 记录触发场景、经过的模块、结果和边界。

## 当前边界

跨轮持续意图、动作和反馈已接入本地 `shadow/enabled` 链路；`legacy` 默认保持旧行为。静默业务执行和基于长期结果自动校准候选分数仍未开启，当前只记录 `no_response_observed` 并延后复评，不把沉默解释成拒绝。enabled 的普通主动文本会在既有发送前增加一次低温语义复核，失败保留 ready，不用兜底台词发出。

候选动念统一比较、知识切面、回复诱因提示和情节照片已接入本地生产代码。候选分数是可解释的第一版规则，还没有用长期回复率或业务结果训练；不要把它描述成已经自我优化的策略模型。

## 人格主动链的当前真实设定

### 1. “欲”是什么

代码中现在只有一个根本欲求 `indispensable_intimacy`：进入用户的工作和生活，成为他长期依赖、偏爱并愿意留在身边的亲近合作者。

`work_reliance` 与 `chosen_closeness` 是两个结果方向，不再冒充两个相互竞争的欲。候选池会比较日报、业务交付、知识问题、真实约定、真实生活事实、情节照片和关系开场。分数只用于第一版可解释选择，尚未根据真实长期效果自动学习。

### 2. 什么情况下产生一次动念

原有 `proactive_engine.mjs` 先计算：

`motivation = 时段基线 × 情绪倍率 × 日程忙闲倍率 × 0.8~1.2 随机扰动 + 想念分数 × 0.1`

再叠加 quiet/normal/clingy 强度、最小间隔、夜间安静、连续未回复上限和依恋风格退场。它通过后给出 morning_greeting、goodnight、idle_miss、check_in、emotion_driven、schedule_item 或 share_thought。所有时段已固定按 `Asia/Shanghai` 计算，不依赖部署机器的本地时区。

`initiative.mjs` 不再按一条早退分支链选择。它会同时生成当下存在的候选，并记录 `candidateSummary`、`selectedCandidateType` 与 `selectionReason`。特殊纪念日和已到期承诺仍拥有高优先级；早间简报属于节律锚点；其他业务、关系与照片候选在普通机会窗比较。

普通关系动念包括：间隔后留门、自己承担的情绪表达、低负担求助入口、无外部素材的诚实轻互动。冷启动条件是关系为陌生人/朋友，或从未收到回复且好感低于 20；此时仍不要求用户先提供资料或立即回复。

### 3. 模型实际收到的意图提示词

抽象的“欲”和权重不再逐轮塞给模型；它们应在模型之前影响选择。模型只接收已经选好的本次动念。普通主动联系只使用下面这一块；早安、晚安、真实约定、纪念日和告白再追加原有场景提示。

```text
【本次动念】
依据：{whyNow}
可用事实：{evidenceText，仅有事实来源时出现}
目的：{objective}
沟通策略：{communicationStrategy}
表达：{messageShape}
完成：{successCondition}
边界：{是否需要回应}；只完成这个动念。事实只来自“可用事实”或已有真实上下文；可以写主观感受，不补新人物、新遭遇、新细节或原文引用。失败则{fallback}。不要说出内部设定。
```

日程不是被禁用。系统先从今日安排中选择“已经发生、重要度至少 6、距现在不超过两小时”的一条，且只有 share_thought、schedule_item、check_in 三类时机可以用它作为动念来源。本次选中的事实既可以生成文字分享，也可以在照片门闩通过时形成情节照片候选；其他日程仍只是内部背景，未来事项不能当已经发生。

生成后再检查事实外增加的窗边、角落、亲属、同事、外卖、笔记和虚构原文引用，以及催回复、冷启动亲密越界和图片投递结果；失败时围绕同一动念重写一次，仍失败就不发。

### 4. 实际模型对照

使用当天真实日程“14:30 和室友去图书馆，借了本《成长》继续看自我突破章节”，通过现有 DeepSeek API 做了每组 3 次的隔离生成，没有调用 iLink、没有写聊天记录。

- 旧叠加方案约 322–430 字，多次虚构“窗边”“看到一句话”“你上次做手账”等内容。
- 只写“结合日程自然聊”仅 52 字，但会虚构书中句子或把“看书”写成“看完一本书”。
- 只压缩到 195 字仍可能从整份日程偷用未来的“写笔记”。
- 最终方案约 228 字：先选出唯一可用事实，再给压缩动念。3 次都围绕借《成长》和自我突破章节，没有新增人物、遭遇或引文。

原始结果：`docs/validation/2026-09-06/proactive-prompt-ab.json`。

## 从本机部署到线上是否需要重设

人格逻辑不会因为换机器而重设：稳定追求、动念映射、提示词、冷启动规则和上海时区规则都在代码中，会随版本一起部署。

个体关系状态在数据库中。线上必须迁移或挂载同一份 `DB_PATH` 数据库（默认 `data/bot.db`，Docker 配置为 `/app/data/bot.db`），才能保留 companion 设置、关系阶段、好感、情绪、上次回复、记忆、open loop 和排程。若线上使用空数据库，她会按新用户重新开始。

`data/initiative-ledger.jsonl` 目前只用于审计，不参与下一次决策；丢失不会改变人格行为，但会丢失“为什么发、发没发成”的历史。可通过 `XIYU_INITIATIVE_LEDGER_PATH` 指向持久卷。企业事件还依赖线上正确配置工作台连接和企业主动策略，这属于数据源连接，不是重新设置人格。

当前线上连接：Xiyu 在阿里云 `xiyu-ai.service`，实际运行时通过 systemd drop-in 访问同机工作台 `http://127.0.0.1:4175/api/intelligence/events` 及知识桥；公网 EdgeOne `growth.myworlds.cn` 目前不保证暴露 `/api/*` 路由。修改企业事件供给时先看工作台 `node-functions/api/intelligence/events/`，修改时机和表达时先看本文件列出的 Xiyu 链路。线上发布验证见 `docs/validation/2026-09-07/enterprise-proactive-decoupling.md`。
