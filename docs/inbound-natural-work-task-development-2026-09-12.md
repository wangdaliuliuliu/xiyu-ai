# 溪语入站自然工作任务链开发交接

日期：2026-09-12  
状态：FROZEN_FOR_IMPLEMENTATION  
任务类型：代码开发、隔离验证、真实模型小额验收；不部署生产

## 0. 固定工作位置

- 唯一工作目录：`E:\FoxSpirit\xiyu-ai`
- 唯一工作分支：`codex/ideal-lab-completion-20260908`
- 必须直接使用这个现有工作树；禁止新建 worktree、分支、仓库或复制项目。
- 禁止进入 `C:\Users\Administrator\.codex\worktrees\*` 或 Codex 自动生成的默认目录实施代码。
- 当前工作树已有未提交改动，均视为现有成果；禁止 reset、checkout、clean、stash 或覆盖与本任务无关的文件。
- 旧实验目录和 `E:\FoxSpirit\xiyu-ai-agency-concerns-20260908` 只读，不继续追加 v41、v42 等实验。

开工前执行并把输出写入进度文档；任一目录或分支不符立即停止：

```powershell
Set-Location -LiteralPath 'E:\FoxSpirit\xiyu-ai'
git rev-parse --show-toplevel
git branch --show-current
git status --short
```

## 1. 故障和目标

真实对话中，用户先问“帮我看看最近业绩怎么样”，随后补充“最近这几天中影的”。系统没有把两句话理解成同一个持续工作任务，先声称看不到工作台，又编出北京、上海、广州，最后只返回笼统连接错误。

已核实：工作台授权目录只有东坝和中影；中影近期真实数据可读取。问题不是缺少某一个关键词，而是当前 AI 路由只产生单轮标签，没有维护可更新的工作任务语义。

完成后的系统必须：

1. 用完整对话、授权目录和当前任务理解用户真正想完成的工作。
2. 将跨轮省略、补充和改口更新到同一个工作任务。
3. 用结构化任务选择知识能力和数据源，不靠穷举自然语言关键词。
4. 数据可得时交付真实结果、日期、口径和来源；只在必要时问一个缺失信息。
5. 保持溪语人格，但不能让人格吞掉业务答案。
6. 禁止目录外实体、无来源数字、虚假权限说明和面向用户的内部报错。

## 2. 禁止方案

- 禁止继续添加“业绩、生意、流水、卖得如何”等关键词或正则来承担自然语言理解。
- 禁止针对截图原句、case ID、固定门店或日期写特判。
- 禁止新增第二套聊天入口、企业路由器、模型客户端、状态库、调度器或发送器。
- 禁止把全部工作台资料塞进提示词。
- 禁止模型直接决定权限、数据是否存在或工具是否成功。
- 禁止用 fake provider 结果声明语义效果通过。
- 禁止真实发送微信消息、修改生产数据库、生产配置、systemd 或线上服务。

## 3. 必须沿用的链路

```text
src/bot.mjs
  -> src/enterprise_context.mjs
     -> 现有 DeepSeek 结构化语义调用
     -> /api/knowledge/catalog
     -> /api/knowledge/retrieve
  -> src/companion.mjs / src/ai.mjs
  -> 现有安全、分段和 ilink 发送
```

工作台来源能力仍由以下唯一原点负责：

```text
workbench/backend/cognition/source-router.mjs
workbench/backend/feishu-sync-server.mjs
```

## 4. 目标设计

### 4.1 AI 生成持续工作任务帧

将 `classifyWorkContext()` 从“本轮属于 work/personal”升级为“本轮如何更新当前工作任务”。模型输入必须包含当前消息、最近 8 个有效 turn、授权 catalog、当前 active task、上海日期和输出 schema。

模型只做语义理解，不读取资料、不回答用户。输出至少包含：

```json
{
  "conversationType": "personal|work|mixed",
  "interactionIntent": "support|lookup|explore|delegate",
  "taskTransition": "none|start|continue|revise|complete|exit",
  "task": {
    "goal": "用户最终想知道或完成什么",
    "question": "结合上下文补全后的完整问题",
    "scope": {
      "projectId": "只能来自 authorizedScopes",
      "venueIds": ["只能来自 authorizedScopes"]
    },
    "timeSpec": {
      "kind": "exact_date|date_range|recent_complete_days|current_period|unspecified",
      "start": "YYYY-MM-DD|null",
      "end": "YYYY-MM-DD|null",
      "count": "number|null"
    },
    "requestedOutcome": {
      "kind": "fact|performance_summary|comparison|diagnosis|plan|execution",
      "businessMeaning": "用户真正要判断什么",
      "metricIds": ["只能来自 catalog capability metrics"]
    },
    "missingSlots": ["venue|time|metric|decision_context"]
  },
  "workSegments": ["本轮用户原文中的工作片段"],
  "retrievalNeeded": true,
  "writebackPotential": false,
  "confidence": 0.0
}
```

“最近业绩怎么样”应在语义层成为 `performance_summary`。具体指标由模型结合业务含义和 catalog 能力决定，不由自然语言关键词表决定。“最近几天”解析为 `recent_complete_days`；数量未明确时采用最近 3 个已有完整数据日，并在回答中展示真实日期。

### 4.2 复用现有 active enterprise task

不得新建状态库。扩展 `src/enterprise_context.mjs` 已有 active enterprise task，使其同时承载 proactive follow-up 和 inbound task：

```json
{
  "taskId": "稳定ID",
  "origin": "inbound|proactive",
  "accountId": "owner",
  "companionId": "owner",
  "status": "collecting|ready|executing|answered|suspended",
  "frame": "上节task对象",
  "sourceRefs": [],
  "createdAt": "ISO",
  "updatedAt": "ISO",
  "expiresAt": "ISO"
}
```

状态规则：

- `start`：创建新任务。
- `continue`：同一 taskId 合并本轮补充，未提及槽位保持不变。
- `revise`：用户改口时覆盖相应槽位，并清除旧范围的工具结果。
- `complete`：结果已经交付。
- `exit`：用户明确退出工作语境。
- 寒暄、调情和情绪表达不能自动确认企业事实。
- 新目标与当前任务明显不同时，新任务 start，旧任务 suspended。

继续使用现有 owner key 和原子写文件方式；企业内容不得进入 `companion_memories`。

### 4.3 工作台消费结构化任务

`source-router.mjs` 新链路优先读取 `task.scope`、`task.timeSpec`、`task.requestedOutcome`。原始 text 仅作旧调用兼容，不承担新链路的主要判断。

- scope 只能来自 catalog。
- `recent_complete_days` 默认 3、上限 7，从今天之前返回最近的完整数据日。
- 多日结果按日期返回独立事实，携带实际日期、指标、来源和缺失日。
- `performance_summary` 返回可用规模指标与基于真实数值的变化描述。
- 销售与客流可以由多个来源分别读取后合并，不能要求用户拆成两次提问。
- 部分数据缺失时返回已有结果和具体缺口，不能整体伪装成连接失败。

### 4.4 回复与门禁

回复模型只能接收人格、任务帧、工具结果摘要和事实边界。`finalizeEnterpriseReply()` 负责：

- 门店必须属于本轮 catalog 和 task scope；
- 数字、日期、来源必须存在于工具结果；
- 主要业务结果不能被人格话术吞掉；
- 错误类型必须与工具实际结果一致。

确定性代码不得理解自然表达。缺槽位时只问一个问题，并引用真实目录。例如只缺门店时问“你想看中影还是东坝？”。

只读 catalog/retrieve 遇到网络异常或 502/503/504 时内部重试一次。仍失败时说明“工作台这次没有返回”，保留任务为 ready；不得声称没有权限或没有数据，也不得要求用户重新描述整个任务。

## 5. 文件范围

允许修改：

- `src/enterprise_context.mjs`
- `src/bot.mjs`
- `src/playground.mjs`（仅入口一致性）
- `config/prompts/work-context-router-v1.json`
- `config/prompts/work-response-v1.json`
- `workbench/backend/cognition/source-router.mjs`
- `workbench/backend/feishu-sync-server.mjs`
- 对应 smoke/eval 脚本
- `docs/validation/2026-09-12/inbound-work-task-*`
- `docs/xiyu-architecture-maintenance-map.md`

修改其他文件前必须在进度文档说明原因并向主任务请求决定。

## 6. 四个里程碑

任务只有 M1–M4，禁止通过不断创建 run/vN 延长任务。

### M1：语义任务状态

完成 schema、active task 扩展、start/continue/revise/complete/exit、owner 隔离和重启恢复。12 个跨轮 fixture 全过；不得包含截图原句特判或新关键词路由。

### M2：结构化来源执行

source router 消费结构化 scope/timeSpec/outcome，支持最近完整数据日、多源合并和明确缺失。真实工作台只读测试必须返回中影最近三个完整数据日；精确日期能力不得退步。

### M3：端到端真实模型测试

使用项目现有 DeepSeek provider、隔离数据库，不发 Bot。真实模型费用设置人民币 1 元硬上限；达到上限立即停止，不做第二模型和 108 条矩阵。

### M4：回归和交付

运行相关 smoke、语法、lint、生产差异审计；输出最终报告、失败样本、部署文件清单和回滚说明。不部署。

完成定义：M1–M4 全部通过，并交由主任务完成主观效果判断。

## 7. 必测场景

每项至少 3 种自然改写，测试原句不得进入生产代码：

1. 模糊经营查询，只缺门店时询问 catalog 中真实选项。
2. 下一轮只补门店，续接同一任务。
3. 下一轮只补“最近几天”，更新 timeSpec 并执行。
4. 单轮完整的经营表现查询，多种自然措辞语义一致。
5. 用户改口换店，旧证据失效。
6. 从整体表现继续追问客流。
7. 精确日期、门店、销售额的旧能力回归。
8. 工作请求与私人表达混合，业务交付和人格均保留。
9. “我最近状态怎么样”“我们最近怎么样”等私人近似表达不得进入企业路由。
10. 用户明确不聊工作，任务退出。
11. 工作台一次 502 后恢复，用户只看到结果。
12. 持续失败、空数据、权限拒绝必须分别表达。

## 8. 硬验收

- 跨轮任务 ID 和语义连续性：100%。
- 用户改口后旧工具证据清除：100%。
- 目录外门店：0。
- 无来源数字、日期和来源名称：0。
- 工具成功却声称看不到工作台：0。
- 一次瞬时失败恢复后向用户暴露报错：0。
- 私人对话误路由：0。
- 精确日期旧查数回归：100%。
- 测试期间真实 Bot 发送：0。
- 生产写入和部署：0。

主观评审材料必须能判断：是否像溪语本人认真帮忙、是否先完成业务、追问是否必要、是否避免客服和报错腔、是否对“表现怎么样”给出结论而非只念数字。

## 9. 进度透明与换方案规则

唯一进度文件：`docs/validation/2026-09-12/inbound-work-task-progress.md`。

固定表格：

| 里程碑 | 状态 | 已完成 | 尚缺 | 阻塞原因 | 下一动作 |
| --- | --- | --- | --- | --- | --- |
| M1 | not_started | | | | |
| M2 | not_started | | | | |
| M3 | not_started | | | | |
| M4 | not_started | | | | |

状态只能为 `not_started`、`in_progress`、`passed`、`failed`、`blocked`、`alternative_required`。

每完成一个里程碑更新一次。每次失败记录命令、错误、根因、修复和是否同根因。同一根因连续两次未解决时：停止第三次重试，标记 `alternative_required`，提出保留架构与替代实现两种方案，并向主任务请求选择。

目录/分支错误、需要生产写入或 Bot 发送、预计费用超过 1 元、需要第二套状态库/路由器/发送器时，立即停止并报告。

## 10. 最终交付物

- `inbound-work-task-progress.md`
- `inbound-work-task-final-report.md`
- `inbound-work-task-results.json`
- `inbound-work-task-transcripts.jsonl`：输入历史、任务帧变化、工具请求/结果、最终回复、调用数和费用。
- `inbound-work-task-failures.md`
- `inbound-work-task-deployment-manifest.md`：只列未来部署和回滚，不执行。
- 更新维护地图。

最终汇报必须写明“完成到 M几/4、通过项、失败项、是否达到完成定义”，禁止只报控制流、run 编号或“目标模式完成”。
