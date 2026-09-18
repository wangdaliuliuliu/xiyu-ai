# 溪语后续开发追加日志

> 本文件是 `XIYU-MASTER-HANDOFF-2026-09-14.md` 的配套活日志。  
> 规则：只在末尾追加，不删除或改写历史记录；敏感凭据永不写入。  
> 每次调查、开发、测试、真实调用、部署、回滚或产品决策都必须留下记录。

## 固定记录模板

复制以下模板追加到文件末尾：

```markdown
## YYYY-MM-DD HH:mm — 简短任务名

- 执行者：
- 用户目标：
- 授权边界：
- 开始分支/HEAD：
- 工作区基线：
- 生产基线（如涉及）：

### 调查与判断

- 已检查：
- 证据：
- 根因/结论：
- 与主交接产品原点是否一致：

### 实际改动

- 文件与位置：
- 行为变化：
- 明确未改：
- 产品/架构决策：

### 验证

- 确定性测试：
- fake/隔离结果：
- 真实provider结果及usage：
- 完整用户可见样本：
- 失败与分类：

### 生产

- 是否部署：否 / 是
- 生产文件hash：
- 配置/策略变化（不写敏感值）：
- 备份：
- 重启与健康：
- 回滚入口：
- 用户实际观察：

### 分状态结论

- designed：
- implemented_local：
- verified_isolated：
- verified_real_api：
- deployed：
- enabled：
- observed_effective：

### 后续交接

- 仍需开发：
- 待执行测试：
- 真实外部阻塞：
- 用户最小协助（仅确有需要时）：
- 下一条安全命令：
- 结束分支/HEAD：
```

## 2026-09-14 — 建立总交接基线

- 执行者：Codex（当前会话）
- 用户目标：在算力不足而切换其他技术执行时，保留整个项目、人格塑造、设计演进、生产状态和后续路线的完整上下文，避免反复推倒和误解。
- 授权边界：仅整理和固化交接文档；未修改生产，未调用付费provider。
- 开始分支/HEAD：`codex/ideal-lab-completion-20260908` / `a7590a356021e1b8f99ecb6dac24f9c9ec122bf2`
- 工作区基线：创建文档前工作区无 `git status --short` 输出。

### 调查与判断

- 已检查：仓库维护规则、旧HANDOFF、统一主动设计、欲与动念研究、agency v2、持续关切、实验规范、生产部署记录、近期提交、自拍方案和用户提供的生产执行证据。
- 结论：旧 `docs/HANDOFF.md` 已明显落后，不能承担本轮跨技术交接；需要新的主交接和强制追加日志。
- 命名结论：“小狐狸精”是溪语/Xiyu的人格体验昵称，不是第二服务或第二人格；“西渔/西宇”通常是同一名称的口语/转写。

### 实际改动

- 新增 `docs/XIYU-MASTER-HANDOFF-2026-09-14.md`。
- 新增 `docs/XIYU-SUCCESSOR-WORKLOG.md`。
- 更新根 `AGENTS.md`，要求相关任务先读主交接并在移交前更新本日志。
- 明确未改：任何运行时代码、数据库、生产文件、服务、开关、provider或用户数据。

### 分状态结论

- designed：主交接机制和后续路线已成文。
- implemented_local：文档与仓库维护入口已建立。
- verified_isolated：不适用；本次无运行时改动。
- verified_real_api：不适用。
- deployed：否。
- enabled：不适用。
- observed_effective：需由下一位技术实际按文档接手后验证。

### 后续交接

- 仍需开发：见主交接第6节及第5.4节。
- 待执行测试：先做生产只读基线，再打通最小真实业务闭环和真实自拍效果回查。
- 真实外部阻塞：当前无；生产操作需使用已有已登录WorkBench或其他获授权入口。
- 下一条安全动作：完整阅读主交接后，只读核对当前仓库与生产状态，并将结果作为下一条日志追加。
- 结束分支/HEAD：提交前仍为 `a7590a356021e1b8f99ecb6dac24f9c9ec122bf2`。

## 2026-09-14 20:53 — 新执行者接手：基线确认与 P3 任务立项

- 执行者：DeepSeek Harness（接手会话）
- 用户目标：以 `XIYU-MASTER-HANDOFF-2026-09-14.md` 为唯一入口继续开发；本轮优先方向由用户选定为 **P3 小幅校准“小狐狸精感”与个人主动**；并要求先写日志再动代码。
- 授权边界：本轮仅本地只读核对 + 文档记录。**未**修改任何运行时代码、数据库、生产文件、服务、开关、provider 或用户数据。生产操作采用“用户在生产执行、本执行者提供逐条只读命令”的方式，不自行连接生产。
- 开始分支/HEAD：`codex/ideal-lab-completion-20260908` / `a7590a356021e1b8f99ecb6dac24f9c9ec122bf2`
- 工作区基线：与主交接基准日一致，**尚无本地改动**（本轮仅追加本日志）。
- 生产基线：**未核对**。主交接第 5 节的生产结论均为历史证据，本轮不采信、不引用为当前事实。

### 调查与判断

- 已检查（本地只读）：
  - 主交接全文 545 行、`AGENTS.md`、`docs/xiyu-architecture-maintenance-map.md` 全文、本日志历史记录。
  - `git log/rev-parse`：HEAD 与分支与主交接第 8 行、第 266 行完全一致，**交接基线未漂移**。
  - `src/` 模块清点：`initiative.mjs`、`agency_protocol.mjs`、`proactive.mjs`、`proactive_engine.mjs`、`enterprise_context.mjs`、`photo_planner.mjs`、`photo_sender.mjs`、`bot.mjs`、`db.mjs` 均存在，与维护地图声明的 owner 一致，**未发现第二套 scheduler/selector/sender 模块**。
  - `src/initiative.mjs` 第 30–59 行 `RELATIONSHIP_INTENTS`（4 类个人动念的硬编码文案契约）、第 64–66 行三道正则质量门、第 136–143 行 `relationship_opener` 构造、第 168 行按 score 降序选择。
  - `config/agency-prompts.v1.json`：`promptVersion = agency-production-2026-09-13-v3`，五个必需段（desire/appraise/plan/feedback/review/semanticProposal）齐全。
  - `docs/validation/2026-09-14/turn-decision-implementation.md` 存在（回合决策升级记录）。
- 证据与结论（仅本地，均限于 `implemented_local`）：
  1. **个人主动的“感”由三层叠加决定**，不是单一 prompt 问题：候选评分 → 硬编码 `messageShape/communicationStrategy/qualityContract` → 生成后正则门与 `review` 语义门。
  2. **结构上个人候选分数系统性低于经营候选**：`relationship_opener` 基础分 36–48（第 138 行），而 `daily_brief`/`business_delivery` 等为 78–100+（第 86–100 行），`morning/goodnight/reminder/confession` 为 92–110。因此个人动念在多数 tick 中**结构性地赢不过工作候选**，且其失败分支是 `prepare_silently`（安静不发），而非降级为一次轻互动。
  3. **质量门的失败会转化为“什么都不发”**：`CONCRETE_SELF_MOVE_RE` 要求出现显式自我动作词（我+想/要/偏要/懒得/纠结…）才通过，同时 `GENERIC_REFLECTION_RE`/`GENERIC_WEATHER_RE` 主动拦截泛化反思与天气式开场。契约要求“没有做到就不发”。
  4. 因此 P3 表面症状（“她不够狐狸精”或“她主动太少”）在代码上至少有三种互斥成因：**(a) 候选分数败给工作**、**(b) 质量门拦掉后静默**、**(c) prompt 措辞约束过紧导致表达平淡**。**当前无任何真实样本可区分这三者**，主交接第 5.4 节第 7 条亦确认未经受控对照证明改善。
  5. 主交接第 6 节 P3 明确要求“先小改、做同条件对照，不大改人格”。据此判断：**在没有真实同条件样本之前修改 `RELATIONSHIP_INTENTS` 文案或调整分数权重，属于无基线改动，无法证明改善，也与仓库纪律冲突。**
  6. **仍需生产只读核对（本执行者无法自行完成）**：`XIYU_AGENCY_MODE` 当前值、`enterprise_proactive_policies` 中目标 `account_id + companion_id` 的五个字段、本地与生产 `initiative.mjs` / `agency-prompts.v1.json` 的 hash 是否一致。若生产 `agency-prompts.v1.json` 不是 `v3`，则本地阅读的文案契约不代表线上真实行为。
- 与主交接产品原点是否一致：一致。本轮未降低任何产品目标，也未把未验证项写成完成。

### 实际改动

- 文件与位置：仅追加本日志条目。
- 行为变化：无。运行时零改动。
- 明确未改：`src/**`、`config/**`、`experiments/**`、根 `AGENTS.md`、主交接文档、数据库、生产环境。
- 产品/架构决策：把“P3 直接改文案”改为“**先取真实个人主动样本并定型成因，再做最小对照改动**”。理由见上第 4、5 条。

### 验证

- 确定性测试：本轮未运行测试（无代码改动）。
- fake/隔离结果：不适用。
- 真实provider结果及usage：未调用，无费用。
- 完整用户可见样本：**无**。这是当前 P3 的核心缺口，也是下一步第一优先。
- 失败与分类：不适用。

### 生产

- 是否部署：否
- 生产文件hash：未核对
- 配置/策略变化：无
- 备份：不适用
- 重启与健康：未核对
- 回滚入口：不适用（无改动）
- 用户实际观察：无变化

### 分状态结论

- designed：P3 的“先定型成因、再最小对照”执行方式已确定。
- implemented_local：本地代码已存在（含 `initiative.mjs`、`agency-prompts.v1.json`）；本轮未新增。
- verified_isolated：不适用。
- verified_real_api：不适用。
- deployed：否（本轮无部署）。
- enabled：**未知**，需生产只读核对。
- observed_effective：否，无真实样本。

### 后续交接

- 仍需开发：P3（在 `src/initiative.mjs` 的候选评分与 `RELATIONSHIP_INTENTS` 契约处做最小改动）；其后 P1 最小真实业务闭环、P2 经营机会发现补全、P4 自拍效果闭环、P5 实验与主观判断，均按主交接第 6 节顺序。
- 待执行测试：先取真实个人主动样本并归类成因（a/b/c），再做同条件对照；每次改动必须补离线确定性检查，**不得为验证触发真实外发消息**。
- 真实外部阻塞：生产只读核对待用户提供执行结果；生产入口不在本执行者可及范围。
- 用户最小协助（仅确有需要时）：(1) 在生产执行本日志所列只读命令并回贴输出；(2) 提供一段近期真实个人主动消息样本（脱敏）或指明“哪几句不像她”，以便定型成因。
- 下一条安全命令：在生产执行 `XIYU_AGENCY_MODE`、`enterprise_proactive_policies`、`agency-prompts.v1.json` hash 的只读查询（命令清单由本执行者单独提供，均为只读）。
- 结束分支/HEAD：`codex/ideal-lab-completion-20260908` / `a7590a356021e1b8f99ecb6dac24f9c9ec122bf2`（仅文档改动，未提交）。

## 2026-09-14 22:26 — 打通生产只读直连；解除 P3 前置三项阻塞

- 执行者：DeepSeek Harness（接手会话）
- 用户目标：让执行者直接连接线上服务器做信息查询，替代上一条日志的“用户在生产执行、执行者提供命令”模式。
- 授权边界：**显式变更**。用户在本轮明确授权执行者通过 SSH 直连生产，范围限定为**只读查询**；本条对上一条“不自行连接生产”的自我限制做显式修订。仍未修改任何运行时数据、服务、开关、生产文件或用户数据。
- 开始分支/HEAD：未核对（本会话沙箱禁止执行 `git.exe`；沿用上条日志的 `a7590a3…`，本轮未验证）。
- 工作区基线：本轮仅追加本日志条目。
- 生产基线：已核对（主机身份、服务、磁盘、内存、开关、文件指纹、策略表），见下。

### 调查与判断

- 已检查：本机 OpenSSH 客户端与 `~/.ssh` 既有密钥、`known_hosts`、`ops/xiyu-readonly-check/` 工具集、服务器 22 端口与 sshd 协商日志（`ssh -vvv`）、私钥头部加密标识、线上只读元数据。
- 证据：
  1. `39.106.153.59:22` 可达，对端 sshd 为 `OpenSSH_9.6p1 Ubuntu-3ubuntu13.19`，登录账号 `admin`，主机名 `iZ2zegvp8qr8jwkob665p2Z`。
  2. 既有密钥 `xiyu-readonly` 的公钥**早已被服务器接受**：`debug1: Server accepts key`。据此判定上一条日志与 `README.md` 中“公钥没贴对 / `authorized_keys` 权限不对”的排查方向属于**误诊**。
  3. 真实根因：`debug2: we did not send a packet, disable method`（客户端在签名环节主动放弃发送）+ 私钥头部 `cipher=aes256-ctr, kdf=bcrypt` ⇒ 私钥带 passphrase，与 `BatchMode=yes` 冲突，OpenSSH 静默放弃公钥认证，并给出误导性的 `Permission denied (publickey,password)`。
  4. 旁证：`~/.ssh` 内同时存在 `limi_overseas_ed25519`（加密）与 `limi_overseas_nopass2`（免密），说明同一问题此前已被踩到并以免密密钥绕过。
  5. 用户尝试输入 passphrase 失败（`Bad passphrase` ×3），旧密钥判定不可用。
  6. 方法纠错：以“文件中是否出现 `bcrypt` 字样”判断私钥是否加密**无效**（OpenSSH 私钥为 base64 编码，KDF 名不以明文出现）。正确判据是私钥头部 base64 前缀（`cipher=none` 对 `aes256-ctr`/`bcrypt`），或 `ssh-keygen -y` 是否索要口令。
- 根因/结论：生成免密只读专用密钥 `xiyu-readonly-nopass`（ed25519，`cipher=none`，411B），公钥由用户在生产追加至 `/home/admin/.ssh/authorized_keys`，直连验证通过（退出码 0，`MARKER:LOGIN_OK`）。
- 与主交接产品原点是否一致：一致。本轮未改动任何产品行为。

### 实际改动

- 文件与位置：本机新增 `C:\Users\Administrator\.ssh\xiyu-readonly-nopass`（私钥）与 `.pub`；生产 `/home/admin/.ssh/authorized_keys` 追加一行；追加本日志条目。
- 行为变化：执行者具备生产只读直连能力，此前“生产入口不可及”的阻塞解除。
- 明确未改：`src/**`、`config/**`、`experiments/**`、`/opt/xiyu-ai` 全部内容、数据库任何行、服务、开关、provider、用户数据。本轮**未**读取 `agency_intentions` / `agency_actions` / `agency_feedback` 等含业务与用户内容的表。
- 产品/架构决策：无产品侧变更。

### 验证

- 确定性测试：`ssh -o BatchMode=yes -i xiyu-readonly-nopass admin@39.106.153.59` 返回 `MARKER:LOGIN_OK`，退出码 0。
- 隔离结果：不适用；无运行时改动。
- 真实provider结果及usage：未调用，无费用。
- 完整用户可见样本（只读元数据）：
  - `XIYU_AGENCY_MODE=enabled`（`.env` 中亦存在该键，计 1 处）
  - `promptVersion = agency-production-2026-09-13-v3`
  - `enterprise_proactive_policies`：单行，`account_id=1`、`companion_id=1`、`enabled=1`、`report_enabled=1`、`knowledge_enabled=1`、`order_monitor_enabled=1`、`updated_at=2026-09-14 14:03:58`
  - 本地与生产四文件 sha256 **完全一致**：`agency-prompts.v1.json 016bef73…`、`initiative.mjs 23f59c77…`、`proactive.mjs d170621e…`、`agency_protocol.mjs 18193865…`
  - `bot.db` 属主 `xiyu:xiyu`，1830912 字节，修改时间 `Sep 14 22:08`（较本次核对早约 18 分钟，线上在持续写入）
  - `xiyu-ai.service` active、`yuanqu-workbench-api.service` active；`/` 40G 已用 20G（52%）；内存 1.6GiB，已用 848MiB，free 仅 105MiB，可用 765MiB
- 失败与分类：passphrase 丢失导致旧密钥不可用 —— 用户侧凭据问题，非代码缺陷。

### 生产

- 是否部署：否
- 生产文件hash：已核对，与本地一致（见上）
- 配置/策略变化（不写敏感值）：`authorized_keys` 新增一行免密只读公钥；**未改** sshd 配置
- 备份：无。仅追加一行，回滚即删除该行
- 重启与健康：未重启；两服务均 active
- 回滚入口：`sed -i '/xiyu-readonly-nopass/d' /home/admin/.ssh/authorized_keys && chmod 600 /home/admin/.ssh/authorized_keys`
- 用户实际观察：直连只读查询可用

### 分状态结论

- designed：生产只读直连通道的建立方式已定型
- implemented_local：不适用（无运行时代码改动）
- verified_isolated：不适用
- verified_real_api：不适用（未调用付费 provider）
- deployed：否
- enabled：**是** —— 通道已可用；且生产 `XIYU_AGENCY_MODE=enabled`（上一条日志中该项为“未知”）
- observed_effective：**是** —— 已取得线上实时只读数据，并完成本地/生产指纹比对

### 后续交接

- 仍需开发：P3（个人主动“感”的成因定型与最小对照改动）。
- 待执行测试：`ops/xiyu-readonly-check/xiyu-p0.sh` 全量只读体检（本执行者现可直接执行，无需用户代跑）。**注意**：该脚本会输出 `agency_intentions` / `agency_actions` / `agency_feedback` 中含业务与用户内容的行，执行前须先取得用户对“把生产用户内容读入本地会话”的明确同意，或改用仅元数据的子集。
- 真实外部阻塞：此前记录的“生产入口不可及”**已解除**；新的唯一阻塞是用户对用户内容读取范围的授权。
- 用户最小协助（仅确有需要时）：确认是否允许以只读方式读取 `agency_*` 表中的业务/用户内容行。
- 下一条安全命令（仅元数据，不含用户内容）：
  `ssh -i ~/.ssh/xiyu-readonly-nopass admin@39.106.153.59 "systemctl show xiyu-ai -p Environment --no-pager | tr ' ' '\n' | grep -E '^XIYU_AGENCY_MODE='"`
- 结束分支/HEAD：未核对（本会话禁止执行 `git.exe`）。

### 运维观察（非本次改动，供后续参考）

- 主机内存 1.6GiB 偏紧：已用 848MiB，`free` 仅 105MiB，依赖 buff/cache（817MiB）周转，可用 765MiB。同机还运行 LIMI 与 capybara-game。当前 load average 0.04，尚未触及瓶颈，但内存是本机最先会碰到的天花板。

## 2026-09-14 22:35 — P0 只读体检复跑；P3 成因取得首批真实证据；修复只读工具集

- 执行者：DeepSeek Harness（接手会话）
- 用户目标：在已打通的生产只读直连上取回真实基线；用户并明确授权**只读读取 `agency_*` 表内容**，以及修复硬编码旧密钥的工具脚本。
- 授权边界：只读查询 + 本地 `ops/` 工具文件修改。**未**修改任何运行时数据、服务、开关、生产文件、数据库或用户数据；**未**部署。
- 开始分支/HEAD：未核对（本会话最初禁止执行 `git.exe`；沿用 `a7590a3…`，未验证）。
- 工作区基线：`ops/xiyu-readonly-check/` 下 7 个文件被修改，另有 2 个新的体检结果文件。
- 生产基线：已核对；`XIYU_AGENCY_MODE=enabled`；本地/生产五文件指纹见下。

### 调查与判断

- 已检查：`xiyu-p0.sh` 全量只读体检（两次）、`agency_intentions` / `agency_actions` / `agency_feedback` / `enterprise_proactive_policies`、`agency_feedback` 的真实 schema、进程隔离（含 sudo 复测）、`journalctl`（含 sudo 复测）、`.env` 键名清单、服务单元定义。
- 证据：
  1. **三项前置阻塞全部解除**：
     - `XIYU_AGENCY_MODE=enabled`（此前为“未知”）。这是唯一允许把普通主动投递接进现有发送器的模式，因此线上确实在走这条代码路径。
     - `promptVersion = agency-production-2026-09-13-v3`。
     - 本地与生产五文件 sha256 完全一致：`agency-prompts.v1.json 016bef73…`、`initiative.mjs 23f59c77…`、`proactive.mjs d170621e…`、`agency_protocol.mjs 18193865…`、`enterprise_context.mjs c49f56ff…`。**结论：本地阅读的文案契约与代码即线上真实行为**，上一条日志对此的保留意见可以撤销。
     - `enterprise_proactive_policies`：单行 `account_id=1`、`companion_id=1`，四个开关全为 1，`updated_at=2026-09-14 14:03:58`。
  2. **分区隔离第一次被真正验证**：`xiyu-ai` 主进程 `MainPID=808948 user=xiyu cwd=/opt/xiyu-ai`，工作台 `user=admin cwd=/opt/yuanqu-workbench-api`。隔离确实存在。
     但**此前的检查方法从未验证过任何东西**：原 `xiyu-p0.sh` 第 3 节用 `readlink /proc/$pid/cwd` 而不加 sudo，`admin` 读不到 `xiyu` 属主进程的 cwd，于是 `xiyu-ai` 主进程被**静默漏掉**（首次体检只列出工作台一个进程）。已修正为 `sudo -n readlink`。
  3. 原第 8 节 `journalctl` 同样缺 sudo，只会打印一行 `No entries`。已修正为 `sudo -n journalctl`。
  4. **`agency_feedback` 没有 `next_state` 列**（原脚本查询必然报错，首次体检确实报 `no such column: next_state`）。真实列为 `id, account_id, companion_id, intention_id, action_id, source_message_id, kind, raw_ref, interpretation, confidence, created_at`。已修正。
  5. **P3 首批真实证据**：
     - `agency_actions` 全年只有 8 行：`contact_text delivered 7`、`contact_text planned 1`。
     - **唯一那条非 delivered 正是个人动念**：`agi_mu002vba_30b3a3938947cc`（睡前晚安，personal），动念停在 `ready`，动作停在 `planned`，**从未投递**。这是成因 (b)「准备完却没发」的第一个实证，而非推测。
     - 最近一次成功投递是 `2026-09-13 00:12:55`；此后至今（约 22 小时）主动通道无任何 delivered，同时存在 1 planned + 3 suspended + 1 preparing。
     - `agency_intentions` 状态分布：`suspended/mixed 3`、`active/personal 2`、`preparing/work 1`、`ready/personal 1`。**没有任何一条动念处于已投递/已完成态**。
     - `agency_feedback` 6 行中 4 行为 `topic_shift`，且**每一条 topic_shift 都打掉了一个个人或混合动念**：`agi_mturok87`（早安）0.85、`agi_mttawzk3`（早安）0.8、`agi_mu002xm2`（取数）0.72/0.85/0.95。唯一一条 `answer 0.95` 是用户真的提出了业绩查询。
     - **新增成因 (d)：话题漂移挂起个人动念。** 用户持续把话题拉向经营数据，系统性挤掉陪伴型动念。这与 (a) 候选分数结构性偏低叠加，导致个人主动在线性上几乎不可能存活。
  6. `agency_intentions` 中存在两条近乎重复的早安动念（`agi_mturok87` 10:57:05 与 `agi_mttawzk3` 11:00:55，`desired_change` 文案完全相同，仅差 3 分钟）。是否属于重复生成，需在改代码前确认。
  7. **时间戳口径存疑**：服务日志同时打印 UTC（`2026-09-14T14:26:40Z`）与 CST（`22:26`），而数据库 `updated_at` 看上去按 UTC 落库。解读投递时间线时必须先确认口径，否则会把 22 小时误读成 6 小时。
  8. 安全/运维观察（非本次改动）：`/opt/xiyu-ai` 目录权限为 `drwxrwxrwx root:root`，**任何用户可写应用代码**；`data/` 下有 4 组 `before-rollback-*` 与 `bot.db-wal` 达 4.1MB；`iLink getUpdates` 每约 18 秒返回 HTTP 200 但 `received=0`。
- 与主交接产品原点是否一致：一致。本轮只取证据与修工具，未改任何产品行为。

### 实际改动

- 文件与位置（全部在 `ops/xiyu-readonly-check/`）：
  - `xiyu-check.ps1`：密钥解析改为候选列表（优先 `xiyu-readonly-nopass`，回退旧键）；新增 `Test-KeyNeedsPassphrase` 本地预检；失败分支纠正误诊文案；doctor 增加 `-n` 与非敏感计数。
  - `xiyu-login-diag.ps1`：同样改为候选密钥列表；指纹匹配放宽为 `xiyu-readonly`。
  - `README.md`：重写 1-1/1-2 为免密密钥与正确公钥；**新增 1-3 节**完整记录 passphrase 误诊的机制、判据与 ssh-agent 备选方案；改正 2-1 中「`Permission denied` → 公钥没贴对」的错误指引。
  - `公钥-贴到服务器.txt`：替换为新的免密公钥。
  - `server-diag.sh`：`grep 'xiyu-readonly-check'` 放宽为 `grep -E 'xiyu-readonly'`。
  - `xiyu-p0.sh`：修正 `agency_feedback` 列名、第 3 节与第 8 节补 `sudo -n`、新增动念状态分布查询、所有 sudo 加 `-n`、统一为 LF 行尾、文件头记录本次修正原因与正确的调用方式。
- 行为变化：只读工具集恢复可用且不再掩盖真实故障；体检不再静默漏检。
- 明确未改：`src/**`、`config/**`、`experiments/**`、生产 `/opt/**`、数据库、服务单元、开关、provider、用户数据。本地代码零改动。
- 产品/架构决策：**不**在取得成因定型前修改 `initiative.mjs` 文案或分数权重。新增成因 (d) 已登记，但定性仍需更多样本。

### 验证

- 确定性测试：`xiyu-check.ps1` 与 `xiyu-login-diag.ps1` 经 PowerShell 解析器校验，**语法错误 0 处**；`xiyu-p0.sh` 与 `server-diag.sh` 行尾归一为 LF（剩余 CR = 0）。
- 隔离结果：`xiyu-p0.sh` 全量只读复跑完成，末段报错仅剩 PowerShell 管道附加 CR 所致，改用 base64 经 stdin 传输后消除。
- 真实provider结果及usage：未调用付费 provider，无费用。
- 完整用户可见样本：见「证据」第 1、2、5、6、7、8 条。
- 失败与分类：`exit 127` 与 `no such column: next_state` 均为工具缺陷，已修复；passphrase 误诊为用户侧凭据问题 + 工具误判，已双重修复。

### 生产

- 是否部署：否
- 生产文件hash：已核对，五文件与本地一致
- 配置/策略变化：无（仅新增 `authorized_keys` 一行，见上一条日志）
- 备份：不适用
- 重启与健康：未重启；`xiyu-ai.service` 与 `yuanqu-workbench-api.service` 均 active；`bot.db` 完整性 `ok`
- 回滚入口：本地文件可用 git 回滚；生产无改动
- 用户实际观察：只读查询与体检工具均可用

### 分状态结论

- designed：P3 执行方式（先定型成因再最小对照）不变
- implemented_local：仅只读工具集修复
- verified_isolated：不适用
- verified_real_api：不适用
- deployed：否
- enabled：是（`XIYU_AGENCY_MODE=enabled` 已确认）
- observed_effective：**否，且有反证** —— 线上主动通道已约 22 小时无成功投递，个人动念存在「ready + planned 却未送达」的实例

### 后续交接

- 仍需开发：P3。**改代码前必须先定型成因 (a)/(b)/(c)/(d) 的相对权重**。
- 待执行测试：定位 `agi_mu002vba` 为何停在 `planned`（查 `initiative-ledger.jsonl`、`agency_runtime`、`proactive_runtime_schedules`，并核对时间戳口径）；确认 `agi_mturok87`/`agi_mttawzk3` 是否为重复生成。
- 真实外部阻塞：无。生产只读通道已可用，先前阻塞全部解除。
- 用户最小协助（仅确有需要时）：确认数据库 `updated_at` 的时区口径；确认是否有正在进行的用户侧操作影响了 09-13 之后的投递。
- 下一条安全命令：
  `ssh -i ~/.ssh/xiyu-readonly-nopass admin@39.106.153.59 'bash -s' < ops/xiyu-readonly-check/xiyu-p0.sh`
- 结束分支/HEAD：未核对。

## 2026-09-14 22:45 — 定位主动通道全天零投递的根因；动念预算上限改为可配置

- 执行者：DeepSeek Harness（接手会话）
- 用户目标：先查明「她太少主动出现」的真实成因，再据用户决定实施「A 修准预算记账 + B 提高日上限（额外 ×2）」。
- 授权边界：**显式授权**。用户批准修改预算相关代码并授权直连生产只读查询；本轮**未部署到生产**，未重启服务，未改数据库、开关或 `config/**`。
- 开始分支/HEAD：`codex/ideal-lab-completion-20260908` / `a7590a356021e1b8f99ecb6dac24f9c9ec122bf2`
- 工作区基线：`AGENTS.md` 已改、`docs/` 与 `ops/` 未跟踪；`src/**` 本轮开始前干净。
- 生产基线：`xiyu-ai.service` active（PID 808948，user=xiyu，cwd=/opt/xiyu-ai）；`yuanqu-workbench-api.service` active（PID 808863，user=admin）；`XIYU_AGENCY_MODE=enabled`；prompt 绑定 `agency-production-2026-09-13-v3`，sha256 前缀 `016bef736889`。

### 调查与判断

- 已检查（生产只读，经 SSH 直连）：
  - `agency_budget_reservations`（按日/目的聚合 + 逐条明细）
  - `agency_intentions` / `agency_actions` / `agency_feedback` / `agency_concern_events` / `agency_runtime`
  - `app_settings`（`proactive_health_*`、`proactive_deadman_last_class`）
  - `proactive_runtime_schedules`（当日与历史 `schedule_json`）
  - `companion_arc_signal_log`、`companion_conversation_turns`
  - `initiative-ledger.jsonl`（含完整 `reason`）
  - `journalctl -u xiyu-ai`（已过滤 iLink 轮询噪音）
  - 生产源码：`src/db.mjs` `reserveAgencyBudget`、`src/proactive.mjs` 预算调用点与 `arc_skip`/`stale_slot` 分支、`src/agency_protocol.mjs` 上下文裁剪常量
- 证据（生产实测，2026-09-14）：
  1. **全天 `sent=0`**。计划表 9 个时段（08:53、13:09、15:16、16:24、18:06、19:22、20:45、21:16、22:06）无一投递成功。
  2. **根因一：日 token 预算被一次用完。** 当日用量 23446 / 上限 24000（96%）。日志显示此后每次动念均为 `status=blocked calls=0`（13:09、16:24、18:06、21:16），即**连一次模型调用都没发出**。
  3. **记账严重低估。** 单次 `appraise` 实测 5242～10209 token（均值约 6900），而代码预留仅 2900（2400+500）；`plan` 预留 3800 而实测约 6072。
  4. **根因二：关系弧压制。** `companion_arc_signal_log` 第 5 条 `pressure_spam`（severity 3）将状态由 `normal` 推入 `hurt`；`proactive.mjs` 第 884/888 行对 `arc=hurt` 返回 `arc_skip`，当日 4 次正常时段与 1 次晚安被降频跳过（15:16、19:22、20:45、22:06）。**该机制本身符合产品意图，不改。**
  5. **次要原因：重启作废时段。** 当日服务重启 7 次（10:31、12:06、12:26、13:28、14:07、14:36、16:26、16:31），产生 3 次 `过期时段作废`（`stale_slot`）。服务器内存 1.6Gi 且无 Swap，疑与 OOM 有关，**本轮未处理**。
  6. **更正上一条日志的错误结论**：`[Proactive]` 层面「个人动念被工作候选压制（分数 36–48 vs 78–100）」**不是**本次观测到的成因。生产在走到候选比较之前就被预算与 arc 拦掉，静态代码推理未被数据证实。上一条「溪语主进程未出现在进程列表」亦为 `readlink` 未加 `sudo` 导致的静默漏检（直连说明「坑 3」），实测主进程为 `pid=808948 user=xiyu cwd=/opt/xiyu-ai`。
  7. **另发现两个独立问题（本轮未修，已登记）**：
     - `app_settings.DEEPSEEK_API_KEY` **以明文存库**。
     - `[Agency] 反馈事务未提交 … status=invalid` 当日出现 6 次以上（11:38、11:39、14:39、14:40、17:25、17:26、17:52），即用户发言后的反馈落库失败。
- 根因/结论：**主动通道零投递 = 日 token 预算被单次动念耗尽（可修）+ 关系弧 hurt 降频（设计如此）+ 重启作废时段（次要）**。用户诉求「她太少出现」的直接可修项是预算记账与上限。
- 与主交接产品原点是否一致：一致。未修改人格、候选评分、文案、事实边界或情绪设计；仅修改预算会计与上限。

### 实际改动

- 文件与位置：
  - `src/db.mjs`：新增 `AGENCY_DAILY_ATTEMPT_CAP`（默认 16）、`AGENCY_DAILY_TOKEN_CAP`（默认 96000）、`AGENCY_FORMATION_CAP`（=8，保持原单次预留上限语义）三个常量，均可由环境变量覆盖；`reserveAgencyBudget` 的硬编码 `8`/`24000` 改为引用上述常量；新增导出 `getAgencyBudgetCaps()` 供测试与运维核对生效值。
  - `src/proactive.mjs`：三处预留值按实测上调——`appraise` 2400+500 → 10000+800；`plan` 3200+600 → 8000+900；`continue` 2800+600 → 7000+900。
  - `tests/agency/state_budget.test.mjs`：原「stops at eight」断言同步为读取 `getAgencyBudgetCaps()`；新增测试「budget refuses a reservation that would exceed the token cap」，锁住「预留值必须能真正挡住超额」这一旧实现失效的性质。
- 行为变化：日上限由 8 次/24000 token 变为 16 次/96000 token；单次预留不再严重低估。按实测单次完整动念约 19700 token 预留计算，约可支撑 4–5 次动念/天（原约 1 次）。
- 明确未改：候选评分与 `RELATIONSHIP_INTENTS` 文案、关系弧 `arc_skip` 降频逻辑、`stale_slot` 作废逻辑、人格与 prompt、数据库、开关、生产文件。
- 产品/架构决策：上限改为**配置优先**（`XIYU_AGENCY_DAILY_ATTEMPT_CAP`、`XIYU_AGENCY_DAILY_TOKEN_CAP`），使成本可在不改代码的前提下调整。96000 为「先让基础设施真正可用」的取值，**非成本最优值**，待有真实观测后再调。

### 验证

- 确定性测试：`node --test tests/agency/state_budget.test.mjs` —— **5/5 通过**（Node v20.20.0）。含新增的 token 上限测试。
- 隔离结果：在服务器 `/tmp/xiyu-budget-verify/` 独立目录执行，依赖以符号链接只读引用生产 `node_modules`，`src/` 全量上传以解析跨模块 import。**该目录外未写入任何文件；生产 `/opt/xiyu-ai` 零改动**（脚本内已核对并输出「生产尚未包含改动」）。
- 真实provider结果及usage：未调用付费 provider，无费用。
- 完整用户可见样本：不适用（本次为后端预算会计改动，不改变单条消息文本）。相关用户可见事实见「证据」第 1、4 条。
- 失败与分类：首次隔离验证因只上传两个改动文件而 `ERR_MODULE_NOT_FOUND`（`provider_costs.mjs`），属**验证脚手架缺陷**，改为全量上传 `src/` 后通过；非产品代码失败。

### 生产

- 是否部署：**否**（本轮止于 `verified_isolated`，等待用户对部署的明确授权）
- 生产文件hash：改动前已核对，`config/agency-prompts.v1.json`、`src/initiative.mjs`、`src/proactive.mjs` 与本地一致；`src/enterprise_context.mjs` **不一致**（本地 `0c33bd86…` vs 生产 `c49f56ff…`），原因待查
- 配置/策略变化：无
- 备份：未创建（未部署）
- 重启与健康：未重启
- 回滚入口：本地 `git checkout -- src/db.mjs src/proactive.mjs tests/agency/state_budget.test.mjs`；生产无改动故无需回滚
- 用户实际观察：尚无变化

### 分状态结论

- designed：预算会计修正与上限配置化
- implemented_local：`src/db.mjs`、`src/proactive.mjs`、`tests/agency/state_budget.test.mjs`
- verified_isolated：**是**，5/5 通过（服务器 Node v20，隔离目录）
- verified_real_api：否（未调用 provider，未产生真实动念）
- deployed：否
- enabled：不适用（未部署）
- observed_effective：否，需部署后观察次日 `agency_actions` 的 `delivered` 条数与 `proactive_health_sent`

### 后续交接

- 仍需开发（按优先级）：
  1. **部署本次预算改动**（待用户授权），并在部署后观察次日投递量与 token 实际消耗。
  2. **`enterprise_context.mjs` 生产与本地不一致** —— 需查清生产是哪个版本，否则 P1 业务链分析会基于错误代码。
  3. **`[Agency] 反馈事务未提交 status=invalid`（当日 6+ 次）** —— 用户发言后的反馈落库失败，属功能缺失级 bug。
  4. `app_settings` 内**明文 API 密钥** —— 建议移入环境变量并**轮换**该密钥。
  5. 关系弧 `hurt` 状态**无恢复路径**（9-14 03:43 进入，至 22:30 仍为 hurt），需产品决策是否需要恢复机制。
  6. 服务频繁重启（当日 7 次）+ 1.6Gi 内存无 Swap —— 需查是否 OOM。
  7. `agi_mu002vba` 与 `agi_mu002xm2` 等意图的 `ready`/`preparing` 长期滞留问题。
  8. P3 原目标（小狐狸精感）—— **在预算与 arc 修复并取得真实样本后再动**。
- 待执行测试：部署后核对次日 `agency_budget_reservations` 日合计、`agency_actions` 各状态计数、`Deadman` 心跳中 `sent` 是否大于 0。
- 真实外部阻塞：无。
- 用户最小协助（仅确有需要时）：(1) 是否授权部署本次改动；(2) 是否授权轮换明文 API 密钥；(3) 是否要处理关系弧 `hurt` 恢复与内存/Swap 问题。
- 下一条安全命令：
  `git -C E:\FoxSpirit\xiyu-ai diff --stat src/ tests/`
- 结束分支/HEAD：`codex/ideal-lab-completion-20260908` / `a7590a356021e1b8f99ecb6dac24f9c9ec122bf2`（未提交）

## 2026-09-14 22:54 — 部署预算修正到生产（已生效）

- 执行者：DeepSeek Harness（接手会话）
- 用户目标：把上一轮的预算修正部署到生产，让主动通道恢复工作。
- 授权边界：用户**明确批准部署**。范围限定为 `src/db.mjs`、`src/proactive.mjs` 两个文件 + 重启 `xiyu-ai.service`。未改 `.env`、未改 systemd 单元、未改数据库内容、未改开关、未触碰 LIMI / capybara-game。
- 开始分支/HEAD：`codex/ideal-lab-completion-20260908` / `a7590a356021e1b8f99ecb6dac24f9c9ec122bf2`
- 工作区基线：`src/db.mjs`、`src/proactive.mjs`、`tests/agency/state_budget.test.mjs` 为已改未提交状态。
- 生产基线（部署前）：
  - `src/db.mjs` sha256 `64cc65ef0366f637ac0c5da81f0af6f56a4fa82ff4ad206bbfde95e3ae7a0fbe`，属主 `xiyu:xiyu`，权限 644
  - `src/proactive.mjs` sha256 `d170621e2dbb566177bbe0a7a60ec4cd23bfb672efa83fc33eedec857c3ce3bc`，属主 `root:root`，权限 644
  - `xiyu-ai.service` active，MainPID 808948，启动于 2026-09-14 16:31:56
  - 健康接口 `http://127.0.0.1:3000/api/health` 返回 `{"ok":true,...}`

### 调查与判断

- 已检查：生产文件 hash 与属主、服务 MainPID 与启动时间、健康接口、`sudo -n -l` 权限、备份目录、磁盘余量、node 运行时（`/usr/bin/node` v20.20.0）、以服务用户 `xiyu` 做语法检查与 `better-sqlite3` 解析的能力。
- 证据：
  1. Dry-run 的完整 diff 证明：生产文件与本地基线的**唯一差异就是本次改动本身**（`db.mjs` +34/−3，`proactive.mjs` +4/−4），不存在隐藏的第三方补丁。上一轮日志记录的“`db.mjs` 生产与本地基线不一致”由此得到解释：差异即本轮改动。
  2. `admin` 拥有 `(ALL) NOPASSWD: ALL`，即全量免密 sudo。**因此重启服务无需人工介入。**
- 根因/结论：预算上限被硬编码为 8 次/24000 token，而单次 `appraise` 实测 5242～10209 token，导致当日额度在第一次动念后耗尽，全天 `sent=0`。
- 与主交接产品原点是否一致：一致。仅改预算会计与上限，未动人格、prompt、候选评分、事实边界或关系设计。

### 实际改动（生产）

- 文件与位置：
  - `/opt/xiyu-ai/src/db.mjs` → sha256 `a5f9deabbd7a110923431731e2f3f4e670c123a46c05d89e2c60cdb566e8aff1`（属主保持 `xiyu:xiyu`，权限 644）
  - `/opt/xiyu-ai/src/proactive.mjs` → sha256 `41b1b065a268ecb4930a4e7fbc3e368f3696878b4b20524e864a76abff6cb51b`（属主保持 `root:root`，权限 644）
- 行为变化：日动念上限 8 次/24000 token → **16 次/96000 token**（可用 `XIYU_AGENCY_DAILY_ATTEMPT_CAP` / `XIYU_AGENCY_DAILY_TOKEN_CAP` 覆盖）；`appraise` 预留 2900→10800、`plan` 3800→8900、`continue` 3400→7900。
- 明确未改：关系弧 `arc_skip` 降频、`stale_slot` 作废逻辑、候选评分与 `RELATIONSHIP_INTENTS` 文案、`config/agency-prompts.v1.json`、`.env`、systemd 单元、数据库内容。
- 产品/架构决策：上限配置化，使成本可在不改代码的前提下调整。**96000 是“先让基础设施可用”的取值，不是成本最优值**，需按真实观测再调。

### 验证

- 确定性测试（隔离，服务器）：`node --test tests/agency/state_budget.test.mjs` → **5/5 通过**（Node v20.20.0，`/tmp/xiyu-budget-verify`，依赖以符号链接只读引用生产 `node_modules`）。
- 部署后隔离冒烟（临时 DB、独立进程、不碰生产库）：
  ```
  CAPS={"attempts":16,"tokens":96000,"formation":8}
  RESERVED=16
  OVERFLOW_BLOCKED=yes
  TOKEN_RESERVED=9
  SMOKE=PASS
  ```
  即：16 次预留全部成功、第 17 次被挡；token 上限 96000 下 10000/次 允许 9 次、第 10 次被挡。
- 真实provider结果及usage：本次未调用 provider（冒烟用临时 DB 与极小额预留，不触达模型）。
- 完整用户可见样本：**尚无**。需等次日真实投递后才能取得。
- 失败与分类（过程中的两次失败均为**部署脚手架缺陷**，非产品代码问题，已修复）：
  1. 首次部署：脚本对 `systemctl restart` 未加 `sudo`，报 `Interactive authentication required` → 重启失败。**但文件替换已成功**，运行中的旧进程仍加载旧模块（node 模块缓存），因此当时新上限未生效。已用「核对文件 hash → `sudo -n systemctl restart` → 健康校验」补齐。
  2. 冒烟脚本放在 `/tmp` 却用相对路径 `./src/db.mjs`，报 `ERR_MODULE_NOT_FOUND`；改为绝对路径 `/opt/xiyu-ai/src/db.mjs` 后通过。

### 生产

- 是否部署：**是**
- 生产文件hash：`src/db.mjs` = `a5f9deab…`；`src/proactive.mjs` = `41b1b065…`
- 配置/策略变化：无（未写 `.env`，未改 systemd drop-in）
- 备份：`/opt/xiyu-backups/budget-deploy-20260914T225254/`，含 `db.mjs`（`64cc65ef…`）、`proactive.mjs`（`d170621e…`）、`SHA256SUMS`
- 重启与健康：`sudo systemctl restart xiyu-ai` 成功；旧 MainPID 808948（16:31:56 启动）→ 新 MainPID **896899**（22:53:43 启动）；`systemctl is-active` = active；健康接口返回 `ok:true`；启动日志显示数据库初始化完成、主动消息调度启动、REST 服务监听 127.0.0.1:3000、iLink notifyStart HTTP=200
- 回滚入口：
  ```
  sudo cp -p /opt/xiyu-backups/budget-deploy-20260914T225254/db.mjs /opt/xiyu-ai/src/db.mjs
  sudo cp -p /opt/xiyu-backups/budget-deploy-20260914T225254/proactive.mjs /opt/xiyu-ai/src/proactive.mjs
  sudo systemctl restart xiyu-ai
  ```
- 用户实际观察：**尚无**（部署后约 1 分钟，未到下一个动念时机）

### 分状态结论

- designed：预算会计修正与上限配置化
- implemented_local：`src/db.mjs`、`src/proactive.mjs`、`tests/agency/state_budget.test.mjs`
- verified_isolated：**是**（5/5 测试 + 部署后冒烟 `SMOKE=PASS`）
- verified_real_api：否
- deployed：**是**（22:53:43 新进程已加载新版代码）
- enabled：是（`XIYU_AGENCY_MODE=enabled`，新上限默认值即生效，未设环境变量覆盖）
- observed_effective：**否，待观察**。判据：次日 `agency_actions` 中 `delivered` 条数与 `Deadman` 心跳中 `sent` 是否大于 0

### 后续交接

- 仍需开发：
  1. **观察本次部署效果**（次日核对投递量与 token 实际消耗；若 96000 仍不足，用环境变量上调）。
  2. **关系弧 `hurt` 状态疑似卡死**：部署后 22:50 的心跳仍为 `restrainedBy={"1":{"arc_skip":1,...}}`。**这意味着即使额度充足，`arc=hurt` 仍会跳过主动时段**。arc 恢复机制需产品决策。（用户已确认第 1–4 项要做，此项属其中。）
  3. **`[Agency] 反馈事务未提交 … status=invalid`**（当日 6+ 次）：用户发言后的反馈落库失败。
  4. `src/enterprise_context.mjs` 生产版（`c49f56ff…`）与本地（`0c33bd86…`）不一致，需查清版本来源。
  5. 服务频繁重启（当日 7 次）+ 1.6Gi 内存无 Swap，疑 OOM。
  6. 意图 `agi_mu002vba` / `agi_mu002xm2` 的 `ready`/`preparing` 长期滞留。
  7. P3 原目标（小狐狸精感）—— 待预算与 arc 修复并取得真实样本后再动。
- 待执行测试：次日核对 `agency_budget_reservations` 当日合计、`agency_actions` 各状态计数、`Deadman` 心跳 `sent`。
- 真实外部阻塞：无。
- 用户最小协助（仅确有需要时）：(1) 是否上调 token 上限；(2) 是否处理关系弧 `hurt` 恢复与内存/Swap；(3) 是否轮换明文 API 密钥（用户已明确表示该项不做）。
- 下一条安全命令：
  `ssh -i ~/.ssh/xiyu-readonly-nopass admin@39.106.153.59 'bash /tmp/xiyu-budget-deploy/run-budget-smoke.sh'`
- 结束分支/HEAD：`codex/ideal-lab-completion-20260908` / `a7590a356021e1b8f99ecb6dac24f9c9ec122bf2`（本地改动仍未提交）

## 2026-09-14 23:16 — 关闭冲突弧（按用户要求）并复位卡住的 hurt

- 执行者：DeepSeek Harness（接手会话）
- 用户目标：用户判断 `pressure_spam` 对「我看看你的洗衣机」的判定**明显不准**，并要求**暂时关闭整个受伤机制**。
- 授权边界：用户**明确授权**关闭该机制。范围：新增可配置总开关 + 写入 systemd drop-in + 复位库中存量状态。未改 `.env`、未改其他源码逻辑、未动数据库结构、未触碰 LIMI / capybara-game。
- 开始分支/HEAD：`codex/ideal-lab-completion-20260908` / `a7590a356021e1b8f99ecb6dac24f9c9ec122bf2`
- 生产基线（关闭前）：`companions.arc_state='hurt'`（`arc_state_changed_at=2026-09-14T03:43:38.688Z`）；未结事件 1 条（`pressure_spam` severity 3，`repair_warm=0`）；`src/relationship_arc.mjs` sha256 `97c60a623f0b646e7da35386bd592c57a5f97e2b8898de53684d35928aac586b`；`xiyu-ai.service` active，MainPID 896899。

### 调查与判断

- 已检查：`relationship_arc.mjs` 两个 tick 入口与钳位逻辑、`getArcProactivePolicy`、`docs/CONFLICT_ARC.md` 转移表与红线、生产弧状态与未结事件、事件后入站计数。
- 证据与根因：
  1. **hurt 不是"永久卡死"，但当前三条恢复路径同时不可达**：
     - `soothed` 需 `repair_warm>=3` 且 ≥12h —— 实测 `repair_warm=0`（用户 9 条消息全是"要照片/查数据"，无安抚语句），时间 11.3h，**双条件均不满足**。
     - `faded` 需互动 ≥5 且 ≥72h —— 互动 9 条已满足，但**只过了 11.3h**。
     - `hurt_then_ignored` 需互动 ==0 —— 互动 9 条，不适用。
     故需等到 **2026-09-17 03:43** 才自然消化，期间 `hurt` 以 70% 概率跳过主动时段。
  2. **设计文档确认这是刻意行为而非缺陷**：`CONFLICT_ARC.md` 第 99-100 行明确「72h 消化要求期间正常互动 ≥5 轮；零互动时 hurt 绝不清零，反而走'伤了又晾'路径加重」。因此**不缩短时间阈值**（那会降低既有产品设计）。
  3. **但存在真实缺口**：`hurt` 是唯一没有"主动台阶"（oliveBranch）的冲突状态（`cold` 有 anxious 试探、`repairing` 有台阶消息）。文档称 hurt 状态「还愿意被哄…接得住台阶」，代码却未给她递台阶的机会。**此项已登记为后续开发项，本轮未实施**（用户选择先整体关闭）。
  4. 用户判定 `pressure_spam` 触发条件不准（由「我看看你的洗衣机」判为 severity 3）。该判定链在 `escalation.mjs` / `inner_os`，属独立问题，尚未排查。
- 与主交接产品原点是否一致：**存在张力，已如实记录**。关闭冲突弧会移除既有的情绪张力设计；这是用户的明确决定，且实现为**可随时恢复的开关**，未删除任何代码路径。

### 实际改动

- 文件与位置：
  - `src/relationship_arc.mjs`：新增 `arcEnabled()` 与 `ARC_DISABLED_VALUES`；`tickArcOnSignal` 与 `tickArcOnTime` 两个入口各加一处总开关短路（关闭时返回 `normal`、`reason='arc_disabled'`、不建/结事件、不计信任）。`ctx.arcEnabled` 可显式注入（测试用），缺省读 `ARC_ENABLED`，**默认 on**，故既有调用方行为不变。
  - `scripts/conflict_arc_smoke.mjs`：新增 9 条开关断言（off 不建事件/不进 hurt/压回 normal/不结事件/不推 neglect；on 与缺省保持原行为）。
  - 生产 systemd drop-in：`/etc/systemd/system/xiyu-ai.service.d/arc-disable.conf` → `Environment=ARC_ENABLED=off`。
  - 一次性运维脚本：`ops/xiyu-readonly-check/reset-arc-hurt.mjs`、`disable-arc.sh`、`prove-arc-off.mjs`、`verify-arc-off.sh`。
- 行为变化：冲突弧**整体停用**；`companions.arc_state` 复位为 `normal`，那条 `pressure_spam` 未结事件被标记 `repair_status='stale'`、写入 `resolved_at`（note 为运维复位，不冒充"她自己消气"）。
- 明确未改：`.env`、`config/**`、`db.mjs`、`initiative.mjs`、`proactive.mjs`（预算改动保持）、数据库结构、其他 systemd 单元、LIMI / capybara-game。

### 验证

- 确定性测试（隔离，服务器 `/tmp/xiyu-arc-verify`）：`conflict_arc_smoke.mjs` **默认（开）= 通过 108 失败 0**。此前生产版为 99 条，新增 9 条开关断言。
- 关闭态验证：同一套件以 `ARC_ENABLED=off` 运行时 55 条失败 —— **这是预期**（该套件本就断言弧在工作），非缺陷；因此关闭态不用整套件判定。
- 开关语义直接验证（`prove-arc-off.mjs`，用生产代码 + 生产服务实际环境）：
  ```
  ARC_ENABLED 环境值 = "off"
  arcEnabled()      = false
  重伤信号(sev4) → normal | reason = arc_disabled | 建事件 = NO
  存量 hurt     → normal | reason = arc_disabled
  neglect 信号   → normal | reason = arc_disabled
  SWITCH_EFFECTIVE=YES
  ```
  对照（不带该变量）：`sev4 → cold`、建事件、`hurt` 不消 —— 证明开关确实改变了行为。
- 复位结果：`RESET=PASS`；`companions` → `arc_state='normal'`，`arc_state_changed_at=2026-09-14T15:14:53.674Z`；未结事件数 1 → 0。
- 真实provider结果及usage：未调用 provider，无费用。
- 失败与分类（均为**部署脚手架缺陷**，非产品代码问题，已修复）：
  1. 复位脚本首次运行报 `Cannot open database because the directory does not exist`：未设 `DB_PATH` 时 `db.mjs` 以**当前工作目录**解析 `data/bot.db`，而脚本在 `/tmp` 下执行。改用 `env DB_PATH=/opt/xiyu-ai/data/bot.db` 后成功。
  2. **drop-in 写到了错误目录**：脚本用 `DROPIN_DIR=/etc/systemd/system/$SERVICE.d`（`$SERVICE=xiyu-ai`）得到 `/etc/systemd/system/xiyu-ai.d/`，**缺少 `.service`**，因此 systemd 从未读取它，`ARC_ENABLED` 未生效。已移至 `/etc/systemd/system/xiyu-ai.service.d/arc-disable.conf`、删除错误目录、`daemon-reload` + 重启后确认 `systemctl show` 输出 `ARC_ENABLED=off`。**这个缺陷一度让"已部署成功"成为假象**，是靠 `prove-arc-off.mjs` 用真实环境复测得出的，值得作为教训保留。

### 生产

- 是否部署：**是**
- 生产文件hash：`src/relationship_arc.mjs` = `51fa484f2a93a11d826caf272607a3ceef21d5829b9acfa957e65d5a9154a964`（原 `97c60a62…`）
- 配置/策略变化：新增 systemd drop-in `xiyu-ai.service.d/arc-disable.conf`，内容 `[Service]` + `Environment=ARC_ENABLED=off`
- 备份：`/opt/xiyu-backups/arc-disable-20260914T151422Z/`，含 `relationship_arc.mjs`、`bot.db`（`sqlite3 .backup` 一致性快照，`integrity_check=ok`）
- 重启与健康：MainPID 896899 → 902401 → 903715（多次重启，最后一次 23:15:55）；`systemctl is-active`=active；健康接口 `ok:true`；启动日志正常（数据库初始化、调度启动、REST 监听 3000、iLink notifyStart HTTP=200）
- 回滚入口：
  ```
  sudo cp -p /opt/xiyu-backups/arc-disable-20260914T151422Z/relationship_arc.mjs /opt/xiyu-ai/src/relationship_arc.mjs
  sudo rm /etc/systemd/system/xiyu-ai.service.d/arc-disable.conf
  sudo systemctl daemon-reload && sudo systemctl restart xiyu-ai
  ```
- 重新启用：把 drop-in 内 `ARC_ENABLED` 改为 `on`（或删除 drop-in），`daemon-reload` + 重启即可，**无需改代码**
- 用户实际观察：**尚无**（关闭时刻为 23:15，当日时段已全部耗尽）

### 分状态结论

- designed：总开关方案
- implemented_local：`src/relationship_arc.mjs`、`scripts/conflict_arc_smoke.mjs`
- verified_isolated：**是**（108/108 通过；开关语义用生产代码实测）
- verified_real_api：否
- deployed：**是**（`ARC_ENABLED=off` 已由 `systemctl show` 与进程环境双重确认）
- enabled：是（开关已生效，弧状态已复位为 `normal`）
- observed_effective：**否，待观察**。判据：后续 `Deadman` 心跳不再出现 `restrainedBy` 中的 `arc_skip`

### 后续交接

- 仍需开发（按优先级）：
  1. **观察两项改动叠加效果**（预算上限 + 弧关闭）：次日核对 `agency_actions` 的 `delivered` 数、`Deadman` 心跳 `sent`、以及 `arc_skip` 是否消失。
  2. **`pressure_spam` 判定不准**（用户明确判定）：入口在 `escalation.mjs` / `inner_os`，需查为何「我看看你的洗衣机」被判 severity 3。
  3. **`hurt` 缺少主动台阶**（本轮查出的真实缺口，已登记）：`cold`/`repairing` 有 `oliveBranch`，`hurt` 没有，与文档「接得住台阶」不符。重新启用弧之前应先补此项。
  4. `[Agency] 反馈事务未提交 status=invalid`（9-14 出现 6+ 次）。
  5. `src/enterprise_context.mjs` 生产版 `c49f56ff…` 与本地 `0c33bd86…` 不一致，需查版本来源。
  6. 服务频繁重启（9-14 共 7 次）+ 1.6Gi 内存无 Swap，疑 OOM。
  7. P3 原目标（小狐狸精感）—— 待前述项稳定并有真实样本后再动。
- 待执行测试：次日核对 `Deadman` 心跳的 `restrainedBy`、`agency_budget_reservations` 当日合计、`agency_actions` 各状态计数。
- 真实外部阻塞：无。
- 用户最小协助（仅确有需要时）：(1) 是否需要重新启用冲突弧及何时补 `hurt` 台阶；(2) 是否排查 `pressure_spam` 误判；(3) 是否处理内存/Swap。
- 下一条安全命令：
  `ssh -i ~/.ssh/xiyu-readonly-nopass admin@39.106.153.59 'sudo -n -u xiyu sqlite3 -readonly /opt/xiyu-ai/data/bot.db "SELECT arc_state FROM companions;"'`
- 结束分支/HEAD：`codex/ideal-lab-completion-20260908` / `a7590a356021e1b8f99ecb6dac24f9c9ec122bf2`（本地改动仍未提交）

## 2026-09-14 23:22 — 修复 pressure_spam 误判、反馈落库失败；查清 enterprise_context 版本差异

- 执行者：DeepSeek Harness（接手会话）
- 用户目标：继续修此前登记的三项——(1) `pressure_spam` 误判、(2) 反馈事务未提交、(3) `enterprise_context.mjs` 版本差异。用户已明确第 5 项（明文密钥轮换）不做。
- 授权边界：用户以「修一下吧」授权继续开发与部署。范围限定为三项缺陷修复。未改 `.env`、未改数据库结构、未触碰 LIMI / capybara-game。
- 开始分支/HEAD：`codex/ideal-lab-completion-20260908` / `a7590a356021e1b8f99ecb6dac24f9c9ec122bf2`

### 调查与判断

**项目 1：`pressure_spam` 误判（已修并部署）**

- 证据：`src/escalation.mjs` 第 6 行 `PUSHY_RE` 原含 `看看你` / `想看你`。这两句是最普通的亲昵表达，且 `src/photo_intent.mjs` 本就把它们识别为**正常索图请求**——只有升级模块误当施压。
- 复现事故序列：`想看…` → `我想看看你自己私人的东西` →（她回「刚不都说了嘛」触发 `RESIST_RE` 的「说了」）→ `现在可以发啦` → `我现在单纯就是想看看你` → `我看看你的洗衣机`。连发 4 条后 `consec` 达 3，`persist=4` → `level=3` → `composeArcSignal` 建 `pressure_spam` severity 3 事件，角色进入 `hurt`。
- 根因：施压词表把「亲昵软表达」与「索要产出/催促回应」混为一类。
- 结论：把 `看看你`/`想看你` 移出 `PUSHY_RE`。**不放松真正反复索要的路径**——`>=5` 字的雷同连发仍由 `isSemanticallySimilar` 兜底累计。

**项目 2：反馈落库失败（已修并部署）**

- 症状：`[Agency] 反馈事务未提交 … status=invalid`，2026-09-14 出现 6 次以上（11:38、11:39、14:39、14:40、17:25、17:26、17:52），表现为"她记不住用户的反应"。
- 排查过程（**第一判断是错的，被测试纠正**）：
  1. 初判为「版本冲突未重试」，据此在 `bot.mjs` 加了 `conflict_retry` 重读重试。
  2. 新写的测试返回 `status=invalid / error=invalid_transition`，**没有通过**——说明重试不是充分修复。
  3. 用独立探针（`probe-feedback-retry.mjs`）实测确认：**动念处于 `preparing`（正在取数）时模型给 `nextState='active'`，而转移表 `preparing: ['ready','suspended','abandoned','expired']` 不含 `active`**，`updateAgencyIntention` 返回 null → 事务抛错 → 整条反馈被丢弃。**此类失败重试无用。**
- 结论：真正修法是**写库前把非法 `nextState` 收敛到合法目标**（`clampAgencyNextState`，优先取 `waiting_user`/`active`/`ready`/`suspended` 中允许者）。版本冲突重试作为独立改进保留。

**项目 3：`enterprise_context.mjs` 版本差异（已查清，无需改动）**

- 证据：生产 sha256 `c49f56ff…` / 1558 行；本地 `0c33bd86…` / 1573 行。生产目录**不是 git 仓库**（发布包部署）。拉取生产原文做 `git diff --no-index --ignore-cr-at-eol`：**10 增 25 删，全部是注释与排版差异**（英文注释 vs 中文注释、一行拆多行、模板字符串 vs 字符串拼接、函数声明与注释块的相对顺序）。
- 结论：**无任何行为差异**。此前记录的"生产与本地不一致"属实但不构成风险，相关担心过重，据此关闭该项。

### 实际改动

- `src/escalation.mjs`：`PUSHY_RE` 移除 `看看你`、`想看你`；补注释说明边界。
- `scripts/photo_escalation_smoke.mjs`：新增事故序列回归断言（亲昵话 `pushy=false`；连发不得升到 L2；真的反复索图仍须 `level>=2`）。
- `src/db.mjs`：新增 `clampAgencyNextState()` 并在 `commitAgencyFeedback` 写库前调用。
- `src/bot.mjs`：反馈提交增加 `conflict_retry` 重读重试（最多 3 次）；补 `getAgencyIntention` 导入；失败日志补 `error` 字段。
- `tests/agency/state_budget.test.mjs`：新增两条测试（版本冲突重读后成功；非法 `nextState` 收敛且反馈仍落库）。
- 明确未改：`config/**`、`.env`、数据库结构、systemd 单元（冲突弧开关保持 `off`）、LIMI / capybara-game。

### 验证

- 隔离验证（服务器 `/tmp/xiyu-verify-all`，依赖只读引用生产 `node_modules`；**生产文件未参与测试**）：
  - `node --test tests/agency/state_budget.test.mjs` → **7/7 通过**
  - `conflict_arc_smoke.mjs` → **108/108 通过**（默认开关 on）
  - `photo_escalation_smoke.mjs` → passed（含新增事故序列断言）
  - `bot.mjs` 语法 + 实际 import 加载 → OK
- 部署后**用生产代码实测**（临时 DB，独立进程，不碰生产库）：
  - 升级修复：`亲昵话(单条) pushy=false level=0`；`事故序列(连发) level=0`；`真的反复索图 level=3`；`FIX_EFFECTIVE=YES`
  - 反馈修复：`状态=preparing 模型想要=active（非法）` → `status=committed`、`收敛后 state=ready`、`反馈已落库=YES`；`FIX_EFFECTIVE=YES`
- 真实provider结果及usage：未调用 provider，无费用。
- 完整用户可见样本：**尚无**（两项修复都需下次真实对话/动念才能观察到用户可见效果）。
- 失败与分类：
  1. 我的**第一版反馈修复判断错误**（以为只是版本冲突）。是**自己新写的测试把错误暴露出来**，随后用探针查到真实成因。属排查方法问题，非产品缺陷。
  2. 测试断言 `sourceMessageId` 写成驼峰，而 `parseAgencyFeedback` 返回原始行（snake_case `source_message_id`）——**测试自身缺陷**，已修。
  3. 多次隔离验证脚本因只复制顶层文件导致 `ERR_MODULE_NOT_FOUND`（缺 `src/providers/`、`tests/`）——**脚手架缺陷**，已改为 `cp -r`。

### 生产

- 是否部署：**是**（三项均已部署，逐项备份）
- 生产文件hash：
  - `src/escalation.mjs` = `b0433fa41d1a838eaa56eb69339531c8e9699f3f345890edea49db7ae4615d78`（原 `383c61e2…`）
  - `src/db.mjs` = `52d1cb6e414edc7b4eef32f3d3280ff47d56e3c9cd62b76350cc8502e1b67dac`（原 `a5f9deab…`）
  - `src/bot.mjs` = `5078d0029e48286064645e27ec9744b8ae94a3b2bee32df54052d127503bde7c`（原 `90a059bd…`）
  - `src/relationship_arc.mjs` = `51fa484f…`（本时段之前部署，未再改动）
- 配置/策略变化：无新增（`ARC_ENABLED=off` 保持）
- 备份：`/opt/xiyu-backups/escalation-fix-20260914T151919Z/`、`/opt/xiyu-backups/feedback-fix-20260914T152137Z/`
- 重启与健康：MainPID 905749 → 907856（23:21:40）；`systemctl is-active`=active；健康接口 `ok:true`；启动日志正常
- 回滚入口：
  ```
  # 反馈修复
  sudo cp -p /opt/xiyu-backups/feedback-fix-20260914T152137Z/db.mjs /opt/xiyu-backups/feedback-fix-20260914T152137Z/bot.mjs /opt/xiyu-ai/src/
  # 升级修复
  sudo cp -p /opt/xiyu-backups/escalation-fix-20260914T151919Z/escalation.mjs /opt/xiyu-ai/src/
  sudo systemctl restart xiyu-ai
  ```
- 用户实际观察：**尚无**（部署时刻无新用户消息）

### 分状态结论

- designed：三项修复方案
- implemented_local：`src/escalation.mjs`、`src/db.mjs`、`src/bot.mjs`、`scripts/photo_escalation_smoke.mjs`、`tests/agency/state_budget.test.mjs`
- verified_isolated：**是**（7/7 + 108/108 + photo smoke passed）
- verified_real_api：否（未调用 provider）
- deployed：**是**（三项均已上线，hash 与重启后 MainPID 已核对）
- enabled：是
- observed_effective：**否，待观察**。判据：后续真实对话中不再出现 `status=invalid`（反馈落库），且不再出现由亲昵话触发的 `pressure_spam` 事件

### 后续交接

- 仍需开发（按优先级）：
  1. **观察三项改动叠加效果**（预算上限 + 弧关闭 + 两项修复）：次日核对 `agency_actions.delivered`、`Deadman` 心跳 `sent`、`restrainedBy` 是否还有 `arc_skip`、以及是否仍出现 `status=invalid`。
  2. **`hurt` 缺少主动台阶**（本轮查出、尚未实施）：`cold`/`repairing` 有 `oliveBranch`，`hurt` 没有，与 `docs/CONFLICT_ARC.md`「接得住台阶」不符。**重新启用冲突弧之前应先补此项**，否则同样的"干等"会复现。
  3. 服务频繁重启（9-14 共 7 次）+ 1.6Gi 内存无 Swap，疑 OOM。
  4. P3 原目标（小狐狸精感）—— 待前述稳定并取得真实样本后再动。**当前弧已关闭，此时正是观察"无人为压制下她的自然主动频率与说法"的窗口。**
- 已关闭项：`enterprise_context.mjs` 版本差异（查清为纯注释/排版差异，无行为影响）。
- 按用户要求不做：明文 API 密钥轮换。
- 待执行测试：次日核对 `agency_feedback` 是否仍有 `invalid`、`companion_relationship_events` 是否不再新增 `pressure_spam`、`agency_budget_reservations` 当日合计。
- 真实外部阻塞：无。
- 用户最小协助（仅确有需要时）：(1) 是否/何时重新启用冲突弧；(2) 是否处理内存与 Swap。
- 下一条安全命令：
  `ssh -i ~/.ssh/xiyu-readonly-nopass admin@39.106.153.59 'sudo -n journalctl -u xiyu-ai --since "-1 hour" --no-pager | grep -viE "getUpdates" | grep -iE "Agency|Deadman" | tail -20'`
- 结束分支/HEAD：`codex/ideal-lab-completion-20260908` / `a7590a356021e1b8f99ecb6dac24f9c9ec122bf2`（本地改动仍未提交）

## 2026-09-17 — 照片链路改造（自拍九块结构 + 身份去形状词）；主动通道零投递根因与可观测性修复

- 执行者：DeepSeek Harness（接手会话）
- 用户目标：(1) 采纳外部总结的「自拍提示词九块结构」，并去掉身份模板里影响角色一致性的"定形状"描述；(2) 用户反映"她两天没理我"，要求查清并修复。
- 授权边界：用户明确授权改造与部署。范围限定为照片链路 3 个源文件 + 主动链路 1 个源文件 + 对应测试与 `identity.json` 数据文件。未改 `.env`、未改 systemd 单元、未触碰 LIMI / capybara-game。
- 开始分支/HEAD：`codex/ideal-lab-completion-20260908` / `a7590a356021e1b8f99ecb6dac24f9c9ec122bf2`

### 调查与判断

**A. 照片链路（用户决定：三候选 → 单份九块方案）**

- 证据（生产 `photo_request_audit` 真实提示词）：
  1. 三张历史照片（id 17/18/19）**服装提示词完全相同**，都是 `lightweight breathable casual clothes suited to the current place and activity`。定位到 `photo_planner.mjs` 旧 `visualCandidatePrompt` 的季节护栏：命中 `cardigan|sweater|hoodie|knit|heavy|thick|scarf|long-sleeve` 就整句替换。模型给出的具体服装（`light long-sleeve top`、`cream knit top`、`long-sleeve tee/cardigan`）**三张全部命中**，故全被替换。
  2. 身份模板 `visual_identity.mjs` 含 `soft round full cheeks`（圆脸）、`large warm doe eyes`（大鹿眼）、`small delicate chin`（小下巴）、`slim petite youthful frame`（纤细娇小）——与用户亲自锁定的参考图**争抢身份定义**。
  3. **关键**：线上 `data/companion_visuals/1/identity.json` 是 2026-09-06 生成的，**缓存着旧模板的完整拷贝**。只改代码不生效。
- 结论：用户决定采用外部总结的九块结构（拍摄声明/构图/人物真实感/瞬间动作/表情/穿搭/环境/缺陷/负面约束）。经核对，**该结构几乎与现有架构同构**（`photo_planner.mjs` 已是唯一 owner、已有结构化中间表示、已在本地选择、已是分层拼装），**不需要改初始架构**，缺的是字段填充与分块拼装。

**B. 主动通道零投递（用户报告"两天没理我"）**

- 证据链：
  1. `wechat_messages` 出站记录：9-14 最后一条 17:27；**9-15、9-16、9-17 均为 0 条**。
  2. 同期 `proactive_runtime_schedules` 却写 9-15 4 条、9-16 9 条全部 `sent:true` —— **状态撒谎**。
  3. 日志直指原因：`[Proactive] 跳过：context_token 窗口已关闭（用户 >24h 未互动，主动消息发不出，不生成内容）`。
  4. 代码注释已实测记录该平台限制：`互动后 +22h 仍成功、+29h 起全失败`。
- 根因（两个独立缺陷）：
  - **缺陷 1**：`proactive.mjs` 原 `else { item.sent = true }` 把内部早退（撞车 / `not_sent` / 无 ctx）**一并标成已发**。于是"发不出去"被伪装成"已发"，既无重试也无告警，用户只能自己发现。
  - **缺陷 2**：9-15 当天 18:10 出现 `复核重生 → 重生后仍撞车，放弃本次主动`。撞车/复核**只能在生成后**发现，命中就要重新生成一次，那一次 token 全白花。9-15 实际消耗 150,737 token / 32 次调用，其中 `structured`（动念评估）18 次 94,455 token 对应"生成了但没送出去"。
- **更正此前日志的错误**：上一轮用 `ai_usage_daily` 汇总表得出"9-15 花 86,805 token、平均每条 29,000"，与逐次记录（`ai_usage_events`，毫秒时间戳）不符。真实为 **150,737 token / 32 次调用、每次均价约 4,711**，与 9-14 的 4,185 相比只高 13%。**"单次均价异常高"的前提不成立**；异常在于"贵的能力（动念评估）占比过大且结果无法投递"。

**C. 仓库与生产的版本一致性（两次误判，均已更正）**

- 期间两次误判"生产代码比本地新"，根因分别是：用 `bash wc -c` 查生产、用 PowerShell 查本地（单位/工具不一致）；以及拿错误命名的本地文件对比。
- 逐个 SHA256 核对结论：**本轮改动的 4 个源文件，生产与本地 git HEAD 完全一致**，可安全改动。
- 真实存在的版本差异：`scripts/photo_aspect_smoke.mjs` 本地 4,573 字节 / 生产 5,800 字节，断言了源码中不存在的功能（`soft warm pastel`/`body posture grows naturally`/`productionReferencePaths`）；`scripts/initiative_integration_smoke.mjs` 则相反——本地用 `let`（正确），生产用 `const`（旧）。**两处均未改动**，登记待查。

### 实际改动

**照片链路（已部署）**
- `src/visual_identity.mjs`：`buildVisualIdentitySpec` 删除 `face` 里的圆脸/鹿眼/小下巴与 `body` 里的"纤细娇小"；保留 `ageLook`（成年标记，安全相关）、`hair`、`style`、`vibe`、`avoid`。`face` 收敛为 `natural skin texture, relaxed fresh makeup-free complexion`。
- `src/photo_sender.mjs`：新增 `referenceFirst`，把身份锚定句**提到最终提示词最前**，并明确"同一人物、脸部特征与整体气质一致"；保留 `FACE IDENTITY ONLY` 提法（无脸闸门判据）；`referenceNote` 的身份分支清空以消除重复。
- `src/photo_planner.mjs`：
  - 新增 `normalizeVisualPlan()` / `visualPlanPrompt()`，删除 `visualCandidatePrompt()` 与 `selectVisualCandidate()`（连同服装季节护栏）。
  - 九块中模型负责 6 块（sceneMoment/framing/action/expression/wardrobe/environment），其余由模板承担（拍摄声明、人物真实感、缺陷块、参考图锚定、负面约束），保证"一个属性只有一个 owner"。
  - `normalizePlan` 改用单方案；审计落 `visualPlan`（含逐块 blocks），兼容旧记录的 `selectedVisualCandidate` 读取。
  - 规划提示词改写为九块要求；`wardrobe` 明确要求同时自洽"季节基线 + 地点 + 正在做的事"，并禁止冬季单品出现在夏秋场景。
- 数据文件：`data/companion_visuals/1/identity.json` 同步清除缓存的形状词（`face`/`body`），单独备份。
- 测试：重写 `scripts/photo_visual_direction_smoke.mjs`；更新 `scripts/photo_planner_prompt_smoke.mjs`（三候选断言 → 九块断言）。

**主动通道可观测性（已部署，`src/proactive.mjs` 唯一 owner）**
- 修 1：`item.deliveryOutcome` 明确区分 `delivered` / `failed` / `expired` / `throttled` / `inflight` / `safety_blocked` / `arc_skipped` / `precheck_skip`；`normalizePersistedRuntimeSchedule` 持久化 `deliveryOutcome`/`deliveryAt`/`deliveryError`；未送达进入健康计数 `not_delivered:<reason>`。
- 修 2：新增 `evaluatePrecheckGate()`（纯函数，已导出）与 `proactivePrecheckGate()`/`recordPrecheckFailure()`/`clearPrecheckFailure()`。同一动念 + 同一计划在 20 分钟冷却窗内失败过 → 生成前跳过；指纹变化、`reminder`、`enterpriseEvent` 均豁免；全部 fail-open。
- 修 3：新增 `noteChannelClosedSkip()`/`clearChannelClosedStreak()`，用 `app_settings.proactive_channel_closed_streak` 累计"连续因窗口关闭放弃的机会"，达 6 次明确 warn 告警；真实送达后清零。
- 新增测试：`scripts/proactive_delivery_observability_smoke.mjs`（28 条断言，纯 ASCII）。

**工具**
- `ops/xiyu-readonly-check/safe-push.ps1`：base64 传输 + 逐文件 sha256 校验的上传器。**起因**：`cmd /c ssh ... < 文件` 传含中文的 `.mjs` 时 PowerShell 按 GBK 解码会破坏 UTF-8，本轮两次导致远端语法报废。

### 验证

- **照片链路隔离验证**（服务器 `/tmp/xiyu-photo-verify`）：受影响 4 个测试全部通过；同条件对照 改造前 12 通过 / 8 失败 → 改造后 **13 通过 / 7 失败**（零新增失败；余 7 项为环境缺失与过期测试文件）。
- **照片链路部署后端到端验证**（生产代码）：最终提示词 3,794 字符；九块逐项断言全通过；身份描述与最终提示词**均不含形状词**。
- **真实出图已发生**（部署后 01:26、01:27 两张，id 21/22）：同晚同卧室但机位/动作/表情/穿搭各不相同（大 T 恤 vs 棉睡衣；抬眼 vs 枕头转头；困倦半笑 vs 转头浅笑），环境含床单褶皱、充电线、半杯水等具体物件。**审美与身份一致性仍需用户目视确认。**
- **主动通道隔离验证**（服务器 `/tmp/xiyu-obs-verify`）：新增 28 条断言全通过；同条件对照 基线 15 通过 / 13 失败 → 改动后 **16 通过 / 12 失败**（零新增失败）。
- **主动通道部署后生产验证**：`proactive_delivery_observability: pass 28 fail 0`。
- 失败与分类（均为脚手架/测试文件问题，非产品缺陷）：
  1. 预检测试 `inside cooldown -> still skipped` 曾失败——**是我的测试算错**（`memo.at` 本身已 5 分钟前，再加 19 分钟即 24 分钟 > 20 分钟窗）。代码正确，已修测试。
  2. 照片测试 `自拍不保留越过肩膀措辞` 曾失败——**是真 bug**：我的替换正则漏了 `the`（`over-the-shoulder` 中间不是 `her`）。已修。
  3. 非 ASCII 经 PowerShell 上传被破坏两次。已用 base64 上传器解决。
  4. 多次隔离验证因只复制顶层文件导致 `ERR_MODULE_NOT_FOUND`。已改 `cp -r`。

### 生产

- 是否部署：**是**（照片链路 + 主动通道可观测性，分两次部署）
- 生产文件hash：
  - `src/visual_identity.mjs` = `98e0e7314cbd…`
  - `src/photo_sender.mjs` = `77c6ffcaea30…`
  - `src/photo_planner.mjs` = `7f6fc81ad820…`
  - `src/proactive.mjs` = `8868e78db0c4…`
  - `scripts/proactive_delivery_observability_smoke.mjs` = `cc2afdb7d871…`
  - `data/companion_visuals/1/identity.json`：`face`/`body` 已无形状词，`ageLook`/`hair`/`style`/`avoid`/`referenceImages` 保留
- 配置/策略变化：无新增（`ARC_ENABLED=off` 保持）
- 备份：`/opt/xiyu-backups/photo-9block-20260914T172126Z/`、`/opt/xiyu-backups/proactive-observability-20260917T034651Z/`、`identity.json.before-shapespec-2026-09-14T17-21-27-196Z`
- 重启与健康：MainPID 935792 → 1549394；两次部署健康检查均通过；启动日志正常
- 回滚入口：
  ```
  # 照片链路
  sudo cp -p /opt/xiyu-backups/photo-9block-20260914T172126Z/{visual_identity,photo_sender,photo_planner}.mjs /opt/xiyu-ai/src/
  sudo cp -p /opt/xiyu-backups/photo-9block-20260914T172126Z/{photo_planner_prompt_smoke,photo_visual_direction_smoke}.mjs /opt/xiyu-ai/scripts/
  sudo cp -p /opt/xiyu-backups/photo-9block-20260914T172126Z/identity.json /opt/xiyu-ai/data/companion_visuals/1/identity.json
  # 主动通道
  sudo cp -p /opt/xiyu-backups/proactive-observability-20260917T034651Z/proactive.mjs /opt/xiyu-ai/src/proactive.mjs
  sudo rm -f /opt/xiyu-ai/scripts/proactive_delivery_observability_smoke.mjs
  sudo systemctl restart xiyu-ai
  ```
- 用户实际观察：照片两张已实际送达；主动通道修复效果**待用户下次发消息、窗口重开后观察**

### 分状态结论

- designed：自拍九块结构采纳方案；主动通道可观测性三修
- implemented_local：`src/visual_identity.mjs`、`src/photo_sender.mjs`、`src/photo_planner.mjs`、`src/proactive.mjs` + 3 个测试
- verified_isolated：**是**（照片 4 个受影响测试全通过；主动 28/28；两组同条件对照零新增失败）
- verified_real_api：**部分**。真实出图已发生（id 21/22），但**审美与身份一致性未经用户目视确认**
- deployed：**是**
- enabled：是（`XIYU_AGENCY_MODE=enabled`）
- observed_effective：**否**。照片需用户看图确认；主动通道需下一次真实投递/关闭周期才能观察到

### 后续交接

- 仍需开发（按优先级）：
  1. **用户目视验收照片效果**：脸是否更贴参考图（删掉文字锚点后最大风险）。若脸漂，需加回**极少量**文字锚点（如 "same face shape as the reference"），不可再用"圆脸/鹿眼"这类具体形状。
  2. **仓库与生产测试文件版本不一致（双向）**：`scripts/photo_aspect_smoke.mjs`（本地旧，生产新）；`scripts/initiative_integration_smoke.mjs`（本地新，生产旧）。需查清是否有未合并版本。
  3. **配文撞限速被丢弃**（`outbound_caption_sent=0`，id 17 与 22 均出现）：图送达但文字丢失，改动前即存在。
  4. **微信 24h 会话窗口是平台硬限制**；现已有明确告警，但无法从代码侧绕过。
  5. `hurt` 缺少主动台阶（2026-09-14 查出、仍未实施）：重新启用冲突弧前应补。
  6. 服务频繁重启 + 1.6Gi 内存无 Swap，疑 OOM（未处理）。
  7. P3 原目标（小狐狸精感）——当前弧已关闭，是观察自然主动频率的窗口。
- 按用户要求不做：明文 API 密钥轮换（2026-09-14 已明确）。
- 待执行测试：用户发一条微信消息后，核对 `proactive_channel_closed_streak` 是否清零、`deliveryOutcome` 是否如实记录、`not_delivered:` 是否出现在健康计数。
- 真实外部阻塞：微信平台 24h 会话窗口（需用户先发起互动）。
- 用户最小协助：(1) 目视确认照片效果；(2) 发一条消息以重开窗口并验证修复。
- 下一条安全命令：
  `ssh -i ~/.ssh/xiyu-readonly-nopass admin@39.106.153.59 'sudo -n -u xiyu sqlite3 -readonly /opt/xiyu-ai/data/bot.db "SELECT key,value FROM app_settings WHERE key LIKE \"proactive_%\";"'`
- **上传文件必须用** `ops/xiyu-readonly-check/safe-push.ps1`（base64 + sha256 校验），不要用 `cmd /c ssh < 文件`，否则中文会被破坏。
- 结束分支/HEAD：`codex/ideal-lab-completion-20260908` / `a7590a356021e1b8f99ecb6dac24f9c9ec122bf2`（本地改动仍未提交）

## 2026-09-18 — 主动通道再次静默：过期动作死循环；新增「动念保质期与收尾」机制

- 执行者：DeepSeek Harness（接手会话）
- 用户目标：用户反映「9-17 下午之后她又不理我了」，怀疑又被阻拦。要求查清并修复。
- 授权边界：用户明确授权调查、清理积压与实现修复。范围限定为动念生命周期（`initiative.mjs` / `db.mjs` / `proactive.mjs`）+ 一次数据清理。未改 `.env`、未改 systemd 单元、未触碰 LIMI / capybara-game。
- 开始分支/HEAD：`codex/ideal-lab-completion-20260908` / 已推送 `b68f804`（本轮改动未提交）

### 调查与判断

**症状与取证**

9-17 真实投递情况（`wechat_messages` 出站，唯一可信依据）：

| 时间 | 结果 |
|---|---|
| 05:22 | 成功送达（"嘿什么呀，看完了就傻笑"）|
| 15:58 | 成功送达 |
| **18:09** | 复核重生 → 重生后仍撞车 → **放弃** |
| **19:14** | 同一条，同样放弃 |
| **20:45** | 同一条，同样放弃 |
| **22:08** | `low_burden_goodnight` → **`agency_blocked`**（连晚安也被拦）|

四次失败撞车原因完全相同：`订单表日报没有说清当前更新状态`。

**根因：一条卡了两天的过期动念**

```
动念 agi_mu2igy2z_78b222d0c75665
  state      = ready          ← 一直在候选池里（选择器含 ready）
  expires_at = (空)           ← 动念从不过期
  version    = 8              ← 被反复更新 8 次
  desired    = 确认订单系统汇总表 2026-09-14 数据是尚未开始填写还是仍在路上

它派生的动作 aga_mu2igzfi_448f47594dfeca
  state      = planned        ← 从没进入 sending
  expires_at = 2026-09-15T13:10:34Z   ← 过期已达 53.5 小时
```

**动作过期不会终结动念**，于是动念每小时被重新选中 → 重新生成（含一次重生）→ 撞在同一条出站复核上。这是死循环。

同时库里还有 **5 条 `planned` 动作全部过期**（最短 48.6h、最长 94.6h，其中 4 条是历史晚安）。9-17 22:08 的晚安就是被这批陈旧动作拦掉的（`agency_blocked`）。

**排除项**：预算充足（9-18 仅用 11,648 / 96,000），不是预算问题；微信窗口开着（15:58 刚成功过），不是平台限制。

**三个子问题**
1. 过期动作仍留在候选池 —— 选择器只查动念状态，不检查其派生动作是否已过期
2. 上一轮新增的生成前预检未能拦住 —— 冷却窗 20 分钟，但 18:09→19:14 相隔 65 分钟已过窗；**对"内容注定失败"的情况，时间冷却无效**
3. 晚安被旧动作拦 —— 与 1 同源（晚安动念下堆了 4 条陈旧动作）

**规则回溯验证（部署前，纯只读）**

新写 `ops/xiyu-readonly-check/probe-shelf-life-rule.mjs`，用拟议规则跑真实积压数据：
- ✅ 5 条积压全部正确判为应过期
- ⚠️ **同时暴露 3 条误杀**：`查询中影三天业绩`、`用早安承接新一天`、`睡前晚安` 被判过期
- 误杀原因：正则看到"今天/最近"就当时效性。**这直接改变了设计**——必须先把具体日期与指标剔除，再判断"稳定意图"，且每日仪式不适用保质期。

### 实际改动

**清理积压（数据操作，可回滚）**
- `ops/xiyu-readonly-check/cleanup-stale-actions.sh`：5 条过期 `planned` 动作 → `cancelled`；清空预检失败记忆。**未改动念状态**。
- 备份：`/opt/xiyu-backups/stale-cleanup-20260917T183955Z/bot.db`（`integrity_check=ok`）

**机制实现（三层）**
- `src/initiative.mjs`：新增纯函数
  - `classifyIntentionLifetime()`：四类 —— `time_bound_monitor`（24h）/ `time_bound_fact`（48h）/ `recurring_ritual`（**不适用保质期**）/ `non_time_bound`（14 天）；无法归类兜底 **7 天**
  - **关键机制**：先 `stripConcreteEvidence()` 剔除具体日期与带单位数值，再判断稳定意图。英文 camelCase 键名（`readySheets=0`）不算具体指标。
  - `intentionShelfDeadline()` / `isIntentionExpired()`
  - `judgeIntentionRetirement()`：三层合成 —— 超保质期 → `expired`；来源连续**两次**确认消解 → `completed`；同指纹连续被拦 ≥3 次 → `suspended`
- `src/db.mjs`：新增 `retireAgencyIntention()`
  - **同一事务**内收尾动念 + 把其 `planned/running/prepared/sending` 动作置为 `cancelled`
  - 允许从任意非终态一步收尾（含 `waiting_user → completed/expired`），因为"知识已过期"是生命周期终止而非普通状态转移
  - 幂等；非法收尾状态被拒且不写库
- `src/proactive.mjs`：新增 `retireExpiredIntentions()` 并接入选动念入口
- 新增测试：`tests/agency/intention_lifetime.test.mjs`（**70 条**）；`tests/agency/state_budget.test.mjs`（+1 条收尾事务断言，共 8 条）

### 验证

- **离线确定性**：`intention_lifetime` **70/70**；`state_budget` **8/8**
- **同条件对照**（隔离目录 `/tmp/xiyu-life-verify`）：
  - 基线（生产原版三文件）：通过 13 / 失败 4
  - 改动后：通过 **13** / 失败 **4**，**失败清单完全一致**
  - 余 4 项均为预存问题：`proactive_prompt_ab` / `proactive_three_preview`（缺 DB 数据）、`agency_acceptance`（缺 `--suite`）、`initiative_integration_smoke`（生产测试期望 `const`、生产源码是 `let`）
- **生产部署后**：两套测试全部通过
- **真实数据判定（关键）**：对当时 9 条未完成动念跑规则
  - 修复前：命中收尾 **3/9**，其中 **2 条误杀**
  - 修复后：命中收尾 **1/9**，只收掉真正过期的订单表动念
- 失败与分类：
  1. **部署当天真实数据暴露误杀**（"沉默间隔"类关系短句被判过期）→ 补入 `沉默间隔|在意依然|依然惦记|依然在|不施加任何回复压力|不索取回复` 等关键词。
  2. **修误杀时引入新误判**：`查询中影三天业绩` 落入兜底类，保质期由 48h 变 7 天。这是粒度取舍，选择放宽兜底（48h → 7 天）。
  3. 测试自身多次写错期望值（兜底期改动后未同步、fixture 日期晚于基准、断言写反）—— 均为测试缺陷，已逐个改正并写明原因。

### 生产

- 是否部署：**是**（两次：先部署规则，再部署误杀修正）
- 生产文件hash：
  - `src/initiative.mjs` = `e59e1591e5ae…`（最终版）
  - `src/db.mjs` = `c1a936936c20…`
  - `src/proactive.mjs` = `6271bd698cbf…`
  - `tests/agency/intention_lifetime.test.mjs` = `a7162f2a7f44…`
  - `tests/agency/state_budget.test.mjs` = `f73ae8717bc4…`
- 配置/策略变化：无
- 备份：`/opt/xiyu-backups/intention-lifetime-20260917T184623Z/`、`...184736Z/`、清理前库 `/opt/xiyu-backups/stale-cleanup-20260917T183955Z/bot.db`
- 重启与健康：MainPID 1549394 → 1709665 → 1710416；健康检查均通过；部署后积压动作 = 0
- 回滚入口：
  ```
  sudo cp -p /opt/xiyu-backups/intention-lifetime-20260917T184736Z/{initiative,db,proactive}.mjs /opt/xiyu-ai/src/
  sudo cp -p /opt/xiyu-backups/intention-lifetime-20260917T184736Z/state_budget.test.mjs /opt/xiyu-ai/tests/agency/
  sudo rm -f /opt/xiyu-ai/tests/agency/intention_lifetime.test.mjs
  sudo systemctl restart xiyu-ai
  ```
- 用户实际观察：**待观察**。积压已清零，机制效果需下一次主动 tick 与真实投递才能看到

### 分状态结论

- designed：四类保质期 + 三层收尾判定（含"每日仪式不过期"的防误杀设计）
- implemented_local：`src/initiative.mjs`、`src/db.mjs`、`src/proactive.mjs` + 2 个测试 + 5 个运维脚本
- verified_isolated：**是**（70/70 + 8/8；同条件对照零新增失败；真实数据 9 条动念逐条核对）
- verified_real_api：否（未触发真实 provider 生成）
- deployed：**是**
- enabled：是（无开关，机制随代码生效）
- observed_effective：**否，待观察**。判据：下一次主动 tick 后（a）订单表动念变为 `expired` 且动作被作废；（b）晚安不再因陈旧动作被 `agency_blocked`；（c）同一陈旧内容不再每小时重试

### 后续交接

- **本轮最重要的一条方法论结论**：
  本项目在主动通道上**已卡过至少 5 次互不相同的静默故障**（预算耗尽 / 弧误判 / 复核撞车 / 窗口关闭 / 过期动作死循环）。共同特征是**失败不可见**：状态显示已发或什么都不说，用户只能自己发现"她不理我了"。
  **因此后续不应只修症状，而应把"失败能不能被发现"当作验收标准之一。** 已知仍需补：
  1. **不变量监控（尚未实现）**：`sent:true` 必须伴随真实投递；非终态动念长期无投递应告警；`preparing` 卡住超时应告警。
  2. **第二、三层证据尚未接入**：`judgeIntentionRetirement` 的 `resolvedStreak` 与 `blockStreak` 在调用点仍硬编码为 0。**即"来源已消解自动完结"与"反复失败自动挂起"两层还没真正生效，只实现了第一层（保质期）。** 这是下一步明确工作。
  3. `blockStreak` 需把预检失败记忆扩展成"按指纹计数"并接进收尾判定，替代纯时间冷却。
- 仍需开发（按优先级）：
  1. 接入第二/三层证据
  2. 不变量监控与告警
  3. 用户目视验收 9-15 部署的照片链路
  4. 仓库与生产测试文件双向版本不一致（`photo_aspect_smoke.mjs` 本地旧；`initiative_integration_smoke.mjs` 生产旧）
  5. 配文撞限速被丢弃（`outbound_caption_sent=0`）
  6. 微信 24h 会话窗口（平台硬限制）
- 待执行测试：下一次主动 tick 后核对订单表动念是否变 `expired`、其动作是否 `cancelled`、`proactive_precheck_last_failure` 是否不再堆积。
- 真实外部阻塞：微信平台 24h 会话窗口。
- 用户最小协助：发一条消息以重开窗口并验证投递链路。
- 结束分支/HEAD：`codex/ideal-lab-completion-20260908` / 已推送 `b68f804`，本轮改动未提交

---

## 2026-09-18（续） — 回答"你怎么证明不会再卡"：不变量检查器 + 收尾闸解耦

### 起因

用户直接质疑上一轮结论：

> "你怎么证明现在她的对话触发就不再有问题了？我们貌似已经卡了好多次了不同的问题··"

这个问题不能靠"我改好了"回答。本项目主动通道已卡过 5 次互不相同的静默故障，
其中 3 次是**用户自己发现的**。逐一修症状永远追不上，所以这一轮的目标改成
**让下一个故障自己冒出来**，并且把上一轮"已部署但实际没生效"的部分补齐。

### 调查与判断

**1）上一轮部署的收尾闸其实没生效——被"窗口比池子小"挡住了**

上一轮报告"已部署"，但生产上那条订单表动念 `agi_mu2igy2z_78b222d0c75665`
依旧是 `ready`，9-17 全天撞车记录完整：

| CST | kind | deliveryOutcome |
| --- | --- | --- |
| 12:17 | normal | failed `not_sent` |
| 13:16 | normal | failed `not_sent` |
| 15:57 | normal | **delivered** |
| 18:08 | normal | failed `not_sent` |
| 19:13 | normal | failed `not_sent` |
| 20:44 | normal | failed `not_sent` |
| 22:08 | goodnight | failed `not_sent`（被 `agency_blocked` 挤掉） |

8 次尝试只送到 1 条（另 08:21 那格无记录）。18:08 / 19:13 / 20:44 三次的日志
原因都是同一句 `订单表日报没有说清当前更新状态` → `重生后仍撞车，放弃本次主动`。

根因：收尾闸的**入参**直接复用了候选列表，而候选列表是 `limit: 8`。
池子涨到 **9** 条后，第 9 条（恰好就是这条）永远排在窗口外，
**永远不被判定、永远不过期**。

> 关键判断：把 `8` 改成 `10` 只是把窗口挪一格，池子再长一条就复发。
> 这类"闸门看不见它该管的东西"的错会随数据量反复出现，
> 所以必须让**扫描面与候选面彻底解耦**，而不是调大常量。

**2）该检查器第一次跑时自己骗了自己**

`check-proactive-invariants.mjs` 首次从错误目录启动。`db.mjs` 里
`DB_PATH || path.resolve(process.cwd(), 'data/bot.db')` 是**相对 cwd** 解析的，
于是它打开了一个**新建的空库**——没有任何表、零条记录，
六条不变量**全部 PASS**。

也就是说：检查器犯了它自己要抓的那类错（报"正常"而实际没查）。

**3）I6 一开始把"正常等待"误判成"卡住"**

原始判据把 `waiting_user` 也算作"未推进"。但 `waiting_user` 是**正常等用户回答**，
`suspended` 是**主动暂停**，两者长期不动不等于卡住。已收窄为只查
`preparing / ready / active`。

### 实际改动

| 文件 | 改动 |
| --- | --- |
| `src/proactive.mjs` | ① `retireExpiredIntentions` 的扫描面改为独立查全量非终态动念（`limit: 50`），与候选面（`limit: 8`）解耦；② 新增 `sweepIntentionRetirement(owner)`；③ 在 `tick()` 里**每个 tick 都调用**，且特意放在**时间窗口判断之前**（清垃圾不该只在允许说话的时间段做），并保证**不受认知周期冷却影响**；④ owner 解析与 `runAgencyCycle` 完全同源（同一条微信绑定优先），否则会扫一个 account_id、认知用另一个，扫描等于白扫 |
| `ops/xiyu-readonly-check/check-proactive-invariants.mjs` | ① 新增**自证闸**：未传绝对路径 `DB_PATH`、库不存在、缺预期表、`agency_intentions` 零条 → 一律 `exit 2`，**绝不输出"全部通过"**；② 输出改为同时报"总数/非终态数"并附库文件最后写入时间（原先两个口径的数字在同一份输出里对不上，像自相矛盾）；③ I6 排除 `waiting_user`/`suspended` |
| `ops/xiyu-readonly-check/install-invariant-timer.sh` | 新增。装 `xiyu-invariants.service` + `.timer`，**每小时**跑一次，日志追加到 `/var/log/xiyu-invariants.log`，`SuccessExitStatus=0 1 2`（0 通过 / 1 有违反 / 2 无法确证连对库，退出码本身就是结论） |

### 验证

- 隔离验证（生产库只读副本 `/tmp/test-sweep.db`，不碰线上）：
  `verify-sweep-rule.mjs` → 扫描前 9 条 → 命中收尾 **1** 条
  （`agi_mu2igy2z_78b222d0c75665` → `expired`，理由
  `shelf_life_time_bound_monitor:monitor_with_concrete_time`）→ 扫描后 8 条；
  I3 残留过期动念 **0**；**每日仪式保留 6 条**（证明没有误杀）。
- **隔离脚本自身也修了一个错**：早先写成"先查 `after` 再 UPDATE"，
  等于拿旧数据复核，报出"每日仪式保留 0 条"的假警报。已改为 UPDATE 之后再查。
- 本地：`node --check src/proactive.mjs` 通过；`intention_lifetime` 70/70。
  （`state_budget.test.mjs` 本地跑不动是环境问题：`better-sqlite3` 原生模块
  与本机 Node 版本不匹配，与改动无关。）
- 生产部署后 `sweepIntentionRetirement` **自动生效**，日志为证：

  ```
  Sep 18 02:57:55 [Agency] 动念收尾 companion=1
    id=agi_mu2igy2z_78b222d0c75665 → expired
    （shelf_life_time_bound_monitor:monitor_with_concrete_time）
    同时作废未完成动作 0 个
  ```

  注意这条**发生在认知周期之外**（上一轮认知是 00:01）——正是解耦要达成的效果。
- 收尾后不变量复跑：**I1 I2 I3 I4 I5 全 PASS，只剩 I6 一条**。
- 检查器退出码确认：有违反时 `exitcode=1`（定时告警依赖此语义）。

### 生产

- 备份：`/opt/xiyu-backups/sweep-decouple-20260917T185632Z`（首次）、
  `/opt/xiyu-backups/sweep-decouple-20260917T185750Z`（tick 级扫描版）
- `src/proactive.mjs` sha256 `2d1d25315256…`；`check-invariants.mjs` 已更新至 `/opt/xiyu-ai/`
- 服务：`xiyu-ai.service` active；部署后健康 `{"ok":true}`
- 定时器：`xiyu-invariants.timer` **active**，下一次 03:00 CST
- 冲突弧仍关闭（`ARC_ENABLED=off`）；`XIYU_AGENCY_MODE=enabled`

### 分状态结论

- designed：不变量检查器（自证闸 + 六条不变量 + 退出码语义）+ 收尾闸解耦
- implemented_local：`src/proactive.mjs`、`check-proactive-invariants.mjs`、`install-invariant-timer.sh`、`verify-sweep-rule.mjs`
- verified_isolated：**是**（生产库副本上"收 1 保 6"；假警报已定位为脚本自身错误）
- verified_real_api：否（未触发真实 provider 生成）
- deployed：**是**
- enabled：是（timer 已 `enable --now`）
- observed_effective：**部分**
  - I3（过期动念滞留）：**observed_effective** —— 生产上自动由 9 条降到 8 条，日志留痕
  - I6（长期停滞的每日仪式）：**blocked（待设计）** —— 见下

### 后续交接

- **I6 是真实缺陷，不是检查器误报**：3 条 `active` 每日仪式动念（最久 218.7h）
  早已投递过、且不会再推进，却因为"每日仪式永不过期"而永久驻留。
  其中 `agi_mtsbnojz_029496dd1c567b` 身上挂着 **3 条 delivered 动作**（9 天前起），
  说明它被反复选中投递了多次——正是用户担心的"同一件事换着法儿重来"。
  修复方向（**未实施**）：已投递且超过 N 小时无新进展的每日仪式应完结；
  或者给同一仪式类型加"新世代取代旧世代"的规则。
  **不可直接套用保质期**——每日仪式必须能每天重发，误杀会停掉早安/晚安。
- **第二、三层证据仍未接入**：`judgeIntentionRetirement` 的 `resolvedStreak` 与
  `blockStreak` 在调用点仍硬编码 `0`。**"来源已消解自动完结"与"反复失败自动挂起"
  两层依然没生效，只有第一层（保质期）在跑。**
- `blockStreak` 需把预检失败记忆扩展为"按指纹计数"，替代纯时间冷却。
- 定时检查目前只写日志，**尚未接外部告警**（无邮件/推送）。若要不依赖人看
  `/var/log/xiyu-invariants.log`，还需要一层通知。
- 用户本轮的原始问题"你怎么证明不会再卡"，**正确的回答不是"保证不再有 bug"**，
  而是：已知失败模式已变成可自动检查的不变量，下一个同类故障会在 1 小时内
  出现在日志里，而不是等用户在两天后发现"她不理我了"。
- 结束分支/HEAD：`codex/ideal-lab-completion-20260908` / 本条目随 `da1b7c0` 推送
  （原写"未提交"，是撰写时的状态；后续已提交，此处更正以免误导接手人）

---

## 2026-09-18（续二） — 清掉 3 条卡了 9 天的每日仪式；发现"冷却即静默"这个大坑

用户回复「做吧」，授权处理上一条工作日志里标记为 `blocked（待设计）` 的 I6。

### 调查与判断

**1）I6 不是检查器误报，是"同一件事被反复投递"的实锤**

先取证：6 条每日仪式动念，逐个看它们的动作历史。

| 动念 | 状态 | delivered 动作 | 关键发现 |
| --- | --- | --- | --- |
| `agi_mtsbnojz_029496dd1c567b` | active | **3 条** | 09-08 15:02 / 19:09 / 09-09 00:17 |
| `agi_mttawzk3_13bc38c34772b4` | suspended | 1 条 | 09-09 08:29 |
| `agi_mtucbi0l_a338a5c6fe72d3` | active | 1 条 | 09-09 01:56 |
| `agi_mturok87_406151e5ecb246` | suspended | 1 条 | 09-10 09:06 |
| `agi_mtz28i5t_cb48d55ce4c8c2` | suspended | 1 条 | 09-13 11:12 |
| `agi_mu002vba_30b3a3938947cc` | suspended | 0 条（4 条 cancelled） | 从未送出 |

`agi_mtsbnojz` 那 3 次投递**落在同一天内、两两相隔 2~5 小时**——这就是
"同一条内容换着法儿重来"的直接证据，也是用户原本抱怨的东西。

成因链已查明：
1. 投递完成后动念**永远停在 `active`**，没有任何东西把它完结；
2. 下一次生成走 `findAgencyIntentionBySemanticKey`，而它只查"非终态"
   （`state NOT IN ('completed','abandoned','expired')`），
   于是**复用了已经发过的那条**；
3. 重复投递。

**2）为什么不能直接套用"保质期"**

每日仪式（早安/晚安/低负担入口）必须每天都能发。给它加保质期会让
早安晚安**发不出去**——比不修更糟。这是上一条日志把它标成"待设计"的原因。

**3）解法：第四层 —— 仪式"已真实送达且已静置"即完结**

- 静置窗口 `RITUAL_SETTLED_HOURS = 6`：实测那 3 次投递两两相隔 2~5 小时，
  6 小时能覆盖实测间隔，又不会跨到第二天。
- 完结后同内容再来时，`findAgencyIntentionBySemanticKey` **查不到它**
  （已终态），于是建一条**新的**。所以"明天还能发早安"不受影响，
  只是不会拿已经发过的那条再发一遍。

### 实际改动

| 文件 | 改动 |
| --- | --- |
| `src/initiative.mjs` | 新增 `RITUAL_SETTLED_HOURS = 6`；`judgeIntentionRetirement` 新增第四层：`latestDeliveredAtMs` 存在、类型为 `recurring_ritual`、且静置 ≥ 6h → `completed`（理由 `ritual_delivered_and_settled`） |
| `src/proactive.mjs` | `sweepIntentionRetirement` 一次查全量 `delivered` 动作并按 `intentionId` 归并最大 `updated_at`，传给判定；`retireExpiredIntentions` 新增 `deliveredByIntention` 参数 |
| `src/db.mjs` | `beginAgencyCognition` 返回值由 `boolean` 改为 `{started, reason}`，三道否决各自带原因（`lease_invalid` / `cognition_gap_Nmin_left` / `reconsider_after_<ISO>` / `runtime_row_missing` / `runtime_update_no_rows`） |
| `src/proactive.mjs` | cycle 日志带出 `reason=...` |
| `tests/agency/intention_lifetime.test.mjs` | +11 条（70 → 81），锁住第四层的边界、无证据不误收、非仪式不适用、保质期优先级 |
| `tests/agency/state_budget.test.mjs` | +1 条，锁住三道否决各自的原因（9 条全过） |

**契约确认**：`retireAgencyIntention` 用直连 SQL 是有意为之，注释里写明
"知识已经过期不是普通状态转移，而是生命周期终止"，允许从任意非终态一步收尾。
所以 `suspended → completed` 在其契约内，不是绕过校验。
但记一个语义坑：`suspended → completed` 之后**只看 `state` 分不清**
"事情办完了"和"被中断了"，只能靠 `next_review_condition` 区分。

### 验证

- 离线：`intention_lifetime` **81/81**；`state_budget` **9/9**。
- 隔离验证（生产库副本 + 独立 staging 目录 + **待部署**的 `initiative.mjs`）：
  - 6 条仪式中命中收尾 **5** 条（都是"已投递过"的）
  - 剩余 1 条 = `agi_mu002vba`（**从未送出**，只有 cancelled 动作）→ 正确保留
  - **正在等用户回答的 `agi_mu58m3qj` 仍在池中** ✅（最关键的安全断言）
  - 残留"已投递过"的仪式：**0** ✅；残留过期动念：**0** ✅
- 生产实测（部署后自动跑）：日志确认
  `agi_mtucbi0l_a338a5c6fe72d3 → completed（ritual_delivered_and_settled）`、
  `agi_mtsbnojz_029496dd1c567b → completed（ritual_delivered_and_settled）`
  （另 3 条 suspended 的收尾日期不在当日窗口，非终态动念 8 → 6 条，
  I6 违规由 3 条降到 1 条）。

**本轮我自己犯的错（记录以免重犯）**：
- `verify-sweep-rule.mjs` 先查 `after` 再 UPDATE → 拿旧数据复核，报出
  "每日仪式保留 0 条"的**假警报**。
- `state_budget` 新测试连错两次：① 租约只有 90 秒有效却用 10/31 分钟后的
  时间戳调用，先撞 `lease_invalid`；② `acquireAgencyLease` 的守卫比较的是
  库里存的**绝对**到期时间，时间旅行前必须**显式释放**上一份租约。
  两处都已把原因写进测试注释。

### 生产

- 备份：`/opt/xiyu-backups/ritual-settle-20260918T014640Z`、
  `/opt/xiyu-backups/cooldown-reason-20260918T015036Z`
- `src/initiative.mjs` `87c5c4245842…`、`src/proactive.mjs` `d6d1ca54babc…`、
  `src/db.mjs` `87f01c124a5f…`
- 测试文件已补齐到生产（上一轮部署脚本只备份未替换，导致部署校验跑出 70 条；
  本轮修正并确认生产为 81 条）
- 服务 active；不变量 I1~I5 全 PASS，I6 从 3 条降到 1 条

### 分状态结论

- designed：第四层（仪式已送达即完结）+ 认知冷却自报原因
- implemented_local：`src/initiative.mjs`、`src/proactive.mjs`、`src/db.mjs`、2 个测试、3 个部署脚本
- verified_isolated：**是**（副本上"收 5 保 1"，等用户回答那条未被误杀）
- verified_real_api：否
- deployed：**是**（两个改动均已上线）
- enabled：是
- observed_effective：**部分**
  - I6 的仪式堆积：**部分生效** —— 生产已自动收 2 条、总数 8→6；
    剩 1 条 `preparing` 属下一节的另一个问题
  - 冷却原因可见性：**尚未观察到** —— 部署后还没出现新的 `cooldown`，
    需要等下一次出现才能确认日志带出原因

### 后续交接

**本轮发现一个更大的问题，尚未修：**

`proactive.mjs:1743` 写着

```js
if (activeAgencyMode === AGENCY_MODE.ENABLED && agencyCycle.status !== 'contact_ready') {
  recordInitiative('blocked', { reason: `agency_${agencyCycle.status || 'not_ready'}` });
  return false;   // ← 直接取消整次主动发送
}
```

也就是说在 `XIYU_AGENCY_MODE=enabled` 下，**认知周期的任何非 `contact_ready`
结果都会硬拦整条主动发送**，其中包括 `cooldown`。

而 `cooldown` 来自 `beginAgencyCognition` 的三道否决，其中
`reconsiderAfter` 取的是 `currentIntentions[0]?.reconsiderAfter`
——**某一条动念的话题级冷却，能否决掉当天的早安**。

生产证据：2026-09-18 08:45:56

```
[Agency] cycle companion=1 mode=enabled status=cooldown calls=0
[Proactive] 未送达 companion=1 kind=morning reason=not_sent
```

（08:20:58 还有一次 `status=inconclusive`。）当天 08:45 的早安因此没发出去。

**但具体是哪一道闸，当时无法确定**——这正是本轮先加
`{started, reason}` 的原因。部署后尚未再次出现 `cooldown`，所以
**还没有实证**，不能凭推测去改。

设计上的问题很清楚，与"话题冷却可否决每日仪式"有关：
早安/晚安属于每日仪式，与"某个话题现在不适合再提"是两件不同的事，
后者不该拦住前者。修之前需要先拿到 `reason` 实证，否则会改错地方。

**其余未完成（沿用上一轮）：**
1. `judgeIntentionRetirement` 第二/三层（`resolvedStreak` / `blockStreak`）
   在调用点仍硬编码 `0`，"来源已消解"与"反复失败挂起"两层仍未生效。
2. 剩余 1 条 I6：`agi_mu002xm2_bf1742cc920ccc`（`preparing` 已 80.4h，
   内容"查询中影门店最近三天的销售业绩"，**没有任何动作**）。
   它是"工具链没回执"的典型——`preparing` 卡住没有超时兜底。
3. 定时不变量检查只写日志，尚未接外部告警。
4. 用户目视验收 9-15 部署的照片链路。
5. 仓库与生产测试文件双向版本不一致。
6. 配文撞限速被丢弃（`outbound_caption_sent=0`）。
7. 微信 24h 会话窗口（平台硬限制，不可修）。
- 用户最小协助：**发一条消息**既能重开 24h 窗口，也能顺便验证投递链路。
- 结束分支/HEAD：`codex/ideal-lab-completion-20260908` / 本条目随 `8bc121f` 推送

---

## 2026-09-18（续三） — 用户报"对话时间和状态对不上"：两个根因

用户发来微信截图（10:06）：

> 他：你在做什么
> 她：刚跟你发完照片不就躺回去了嘛，灯还关着一半呢。
> 她：结果正经问题你还没答我呢，先说那两三条标准呗，我拿小本本记着。

用户判断："对话时间明显对不上，现在是上午，但她应该只考虑晚上的上下文了，
是不是把个人状态这个因素给丢失了，还是撞上什么 bug 了？"

**用户的直觉是对的，而且他指出的方向（个人状态丢失）命中了第一处。**

### 调查与判断

**先确认不是投递故障**：日志显示消息真实发出
（`sendMessage success` ×2），`[Agency] 反馈已记录 kind=topic_shift status=committed`。
链路正常，是**内容**错了。

**取证：她当天的日程本来写得清清楚楚**（`companion_daily_schedule`，9-18）：

| 时间 | 安排 |
| --- | --- |
| 07:30 | 被闹钟叫醒，赖床五分钟 |
| 08:00 | 洗漱完赶去上早课 |
| 08:30 | 专业课上偷翻《成长》 |
| **10:00** | **课间和室友对义卖海报翘边怎么压平** |
| 12:00 | 食堂鸡腿饭 |

10:06 她该在课间，却说自己"刚躺下、灯关一半"——**日程完全没起到约束作用**。

**根因 ①：时间事实约束只在主动模式构造**

`companion.mjs` 里那套硬约束（"你现在应该在学校上课，不可能'放学''下班''刚到家'"）
整段包在 `if (promptMode === 'proactive')` 里。而 `bot.mjs:1096` 用的是
`promptMode: 'reply'`——**被动回复时她手上只有一行钟表信息，没有任何一致性硬约束**。

所以同一件事：她主动开口时说得出符合时段的场景，你一问她，就穿帮。
`current_scene` 又是中性默认值 `'日常'`，注入的是"你现在在家，很随意地和他聊天"
——与 9-14 晚上的自我描述完全同构，于是她顺着那个记忆说了下去。

**根因 ②：【最近对话上下文】每一条都没有时间**

`companion.mjs:556-559` 拼上下文时把 `created_at` 丢掉了：

```js
return `- ${roleLabel[t.role]}${topic}：${content}`;   // 没有时间
```

而时间戳**一直在数据里**（`getConversationContext` 返回 `created_at`，见 `db.mjs:1571`）。
后果：9-14 晚上的对话和一分钟前的对话长得一模一样，她无从判断"刚"指什么时候
——所以她说"刚跟你发完照片"（照片是三天半前的），还回头追 9-17 那个问题
"那两三条标准"，像在追刚发生的事。

### 实际改动

| 文件 | 改动 |
| --- | --- |
| `src/companion.mjs` | ① 新增 `buildTimeRealityConstraint(c)`：时间事实约束从 `proactive` 分支抽出，**两种模式共用**，并补上"白天不要说自己刚睡下/灯关了/准备睡了""说法必须和【你今天的安排】一致；对方问'你在做什么'就照日程回答，不要凭空编与日程冲突的场景"；② 新增 `relativeTimeLabel(raw, now)`，容错解析 ISO 与 SQLite 两种时间格式，认不出返回空串（宁可不标也不错标）；③ 【最近对话上下文】每行加 `[多久以前]`，并写明"标着 N 天前的绝不能当成刚发生，要当'前几天那事'来提" |
| `tests/agency/time_consistency.test.mjs` | 新增，21 条断言 |

### 验证

- **反向验证（关键）**：同一测试跑**改动前**的生产版本 → **10 通过 / 11 失败**，
  跑改动后的版本 → **21/21**。证明测试不是空转，确实抓的是这个 bug。
  该反向验证已内置进部署脚本作为上线前门禁（旧版若意外全过则拒绝部署）。
- 回归全绿：`time_consistency` 21/21、`intention_lifetime` 81/81、`state_budget` 9/9。
- 测试覆盖：回复模式必须含时间事实、主动模式不能被抽函数弄丢、近处标"分钟前"、
  三天前标"天前"、SQLite 时间格式、不可解析时间不输出空/畸形标注、
  未来时间不出负数、无上下文时不注入空块。

### 生产

- 备份：`/opt/xiyu-backups/time-consistency-20260918T021242Z`
- `src/companion.mjs` sha256 `68ac6c334802…`
- 服务 active，健康通过；启动日志显示恢复当日排程
  `remaining=9 times=08:45✓,12:15,12:45,13:15,14:15,14:45,15:15,16:15,20:45,21:29`
- **下一个可验证时点：12:15 的主动消息**——那是第一次能用真话验证
  "她的说法是否与 10:00/12:00 日程一致"的机会

### 分状态结论

- designed：时间事实两种模式共用 + 对话上下文时间标注
- implemented_local：`src/companion.mjs` + 1 个测试 + 1 个部署脚本
- verified_isolated：**是**（含反向验证：旧版 11 条失败）
- verified_real_api：否
- deployed：**是**
- enabled：是（无开关）
- observed_effective：**否，待观察**。判据：下一次用户问她"在做什么"，
  她的回答必须与【你今天的安排】里当前时段的安排一致，且不得在白天说
  "刚躺下/灯关了"；提及三天前的照片时应说"前几天"而不是"刚"

### 后续交接

- **这一轮暴露的是同一类问题的第三、第四例**：能力做在了一条路径上，
  另一条路径没有。已知同类：
  1. 时间事实约束只在主动模式（本轮修）
  2. 对话上下文不带时间（本轮修）
  3. **收尾闸的扫描面曾跟着候选条数走**（2026-09-18 续一修）
  4. **认知冷却能否决每日仪式**（尚未修，见续二）
  → 后续改动应养成"这个能力在 reply / proactive 两条路径上都在吗"的检查习惯。
- 仍未修（沿用）：
  1. `proactive.mjs:1743` 在 `enabled` 下任何非 `contact_ready` 都硬拦发送，
     含 `cooldown`；`reconsiderAfter` 取 `currentIntentions[0]`，
     某条动念的话题冷却能否决当天早安。已加 `reason` 证据日志，
     **等下一次出现 cooldown 拿到实证再改**。
  2. `judgeIntentionRetirement` 第二/三层（`resolvedStreak` / `blockStreak`）
     调用点仍硬编码 `0`。
  3. 剩余 1 条 I6：`agi_mu002xm2_bf1742cc920ccc`（`preparing` 80+ 小时、
     零动作，"查询中影门店销售业绩"）——`preparing` 缺超时兜底。
  4. 定时不变量检查只写日志，未接外部告警。
  5. 用户目视验收 9-15 部署的照片链路。
  6. 仓库与生产测试文件双向版本不一致。
  7. 配文撞限速被丢弃（`outbound_caption_sent=0`）。
  8. 微信 24h 会话窗口（平台硬限制）。
- 结束分支/HEAD：`codex/ideal-lab-completion-20260908` / 本条目随 `4370247` 推送
