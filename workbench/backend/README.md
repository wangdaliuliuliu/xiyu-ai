# 后端同步服务

`feishu-sync-server.mjs` 是正式落盘适配器。它读取 `data/feishu-target.json`，使用后端配置的飞书开放平台应用凭证，把网页确认后的结构化任务 upsert 到新飞书表的各个 `录入_*` 事实表。

启动：

```powershell
node backend/feishu-sync-server.mjs
```

默认监听 `http://127.0.0.1:4174`，健康检查为 `/health`，同步接口为 `POST /api/feishu/sync`，只读对比接口为 `POST /api/feishu/compare`。网页在“总设置”选择“确认后通过同步服务写入正式飞书表”后调用同步接口；新安装页面默认使用该模式，仍需经过确认弹窗。页面的“对比飞书”按钮调用对比接口，不会写入数据。运营填数页的“读取本周来源数据”调用只读接口 `POST /api/feishu/source-preview`，按周期间和门店批量读取来源表并返回汇总预览，不会改写任何飞书数据。

总设置通过 `GET/PUT /api/settings` 持久化到 `data/weekly-ops-settings.json`（可用 `WEEKLY_OPS_SETTINGS_PATH` 指向持久化磁盘）。模型 API Key 只写入服务端文件，GET 不返回密钥，只返回 `reportApiKeyConfigured`。周报模型请求调用 `POST /api/weekly-report`；经营节点专家分析调用 `POST /api/strategy/analyze-node`。两者都由服务端读取已保存的模型地址、Key 和模型名，浏览器不直连模型。

模型调用默认优先启用 DeepSeek thinking，并由服务端统一做结果保护：为最终 `message.content` 预留独立 token 预算；遇到 thinking 参数不被供应商支持、只返回 `reasoning_content`、`finish_reason=length`、JSON 截断或超时，会按“扩大预算重试 → 关闭 thinking 兜底”的顺序自动重试。只有可读取且（请求 JSON 时）可解析的最终内容才会返回给页面；响应头 `X-Model-Thinking` 和 `X-Model-Attempts` 可用于排查本次实际采用的模式与尝试次数。默认单次模型请求超时为 90 秒、同一请求所有重试总计不超过 120 秒，可用 `MODEL_REQUEST_TIMEOUT_MS`、`MODEL_TOTAL_TIMEOUT_MS` 调整；token 上限可用 `MODEL_MAX_TOKENS` 调整。

“总设置”中的 thinking 总开关和任务勾选会同时保存到服务端。当前可配置节点为：本周问题与机会识别、因果调查对话、复盘结论/经验/动作、经营节点专家分析、打法执行与验证方案、执行结果 AI 审校、完整周报生成。服务端按任务键强制应用选择，避免页面旧缓存偷偷改变实际模式。

经营策略接口：

- `GET /api/strategy/knowledge`：读取版本化经营日历、门店画像、行业/内部打法和测试模板。
- `GET /api/strategy/prompts`：读取经营节点、打法方案、长期机会、验证审校以及周报复盘的版本化提示词注册表。
- `GET /api/strategy/github-search?q=...`：按方案生成的技术检索词查询 GitHub 仓库候选；只返回公开元数据，不下载或运行代码。
- `POST /api/strategy/analyze-node`：接收 `analyze_operating_node_v5` 事实包，调用 `operating-node-analysis-v5`，校验证据引用和输出枚举；首次失败自动修复一次，仍不合格则拒绝展示。
- `GET/PUT /api/strategy/profile`：读取或保存长期项目档案与门店档案，持久化到 `data/strategy-project-profile.json`；该档案进入专家分析和打法方案上下文，但不属于周经营事实。

企业认知第一阶段新增 `backend/cognition/`：`source-port.mjs` 定义中立来源端口，`context-compiler.mjs` 只编译传入对象，不直接读取文件。`POST /api/knowledge/retrieve` 保留旧 `contextVersion`，同时返回 `schemaVersion=enterprise-context-v2`、`goalsAndDecisions` 和结构化分组字段。当前目标/决策通过项目档案的 `project.goals`、`project.decisions` 保存，缺少时返回空集合，不由模型补造。

溪语主动经营事件由 `POST /api/intelligence/events/refresh` 按当前经营信号、知识缺口和进行中验证确定性生成；同一账号有待处理事件时不会重复生成，且每天最多生成一条，避免主动协同变成消息轰炸。事件带 `question`、来源引用和任务类型，溪语投递成功后保存短期 active business task，用户下一条短回答可回绑到原任务。

第一阶段纯协议回归可运行 `node backend/cognition/context-compiler-smoke.mjs`；它验证门店作用域、目标/决策、已确认事实、缺口和 v1 兼容字段，不连接飞书或模型。

浏览器不能通过这些接口修改知识库。打法推荐先按知识标签和当前经营上下文检索，再由模型适配与排序；模型不得创造知识库之外的打法。方案生成结果保存在策略状态中，不会写入经营事实表。

运行前提：后端应用已开通电子表格读写权限，且应用对目标表和来源表有相应访问权限。凭证和 `FEISHU_SOURCE_SPREADSHEET_TOKEN` 放在 `backend/.env`（该文件已加入 `.gitignore`），不会从浏览器接收或展示。可用 `FEISHU_API_BASE` 覆盖 API 域名，`WEEKLY_OPS_PORT` 覆盖端口。

同步行为：按字段映射读取目标表表头，以事实表主键查找已有行，存在则更新，不存在则追加；不会写入 `AI周报` 的 AI 结论列。次卡已核销次数目前只有门店汇总口径，服务会保留提示，不会擅自拆分到卡种。

当前页面的周记录、草稿和周报修订仍使用 localStorage 演示前端闭环，后端接入时必须复用 `schema.json` 的键、状态和粒度；总设置不再只依赖 localStorage：

- `period_id + venue` 唯一标识一条周记录。
- 数值字段只接受 number 或 null，拒绝带单位的字符串。
- 草稿只能落 staging；确认后写入 outbox；只有同步服务返回成功才标记 success。
- 修改已确认记录时生成 revision，不覆盖原始 revision。
- 播控字段属于事实同步接口，按“周期 × 门店 × 项目”写入 `录入_播控`。

周报分析契约另见 `report-schema.json`。经营节点契约见 `strategy-workbench-schema.json`，提示词见 `strategy-workbench-prompts-v1.json`。节点接口只接受 evidence id 引用，阈值结果只能作为 candidate signal；没有同口径且可追溯的行业 benchmark 时，输出必须明确不使用行业对标。
