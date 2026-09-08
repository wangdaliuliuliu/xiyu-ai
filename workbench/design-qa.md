# 经营策略工作台首页设计 QA

## 对照信息

- source visual truth path: `E:\Yuanqu-Operations-Workbench\weekly-ops-entry\qa\figma-homepage-source.png`
- implementation screenshot path: `E:\Yuanqu-Operations-Workbench\weekly-ops-entry\qa\implementation-homepage-final.png`
- source Figma: file `7TZUZSBxf1QFEkpDtGl0Hh`, node `7:69`
- viewport: browser override `1777 x 1140`; in-app browser content screenshot `1762 x 1130`
- source pixels: `1762 x 1130`
- implementation pixels: `1762 x 1130`
- CSS density: desktop, device scale factor 1; no density resampling required
- state: 经营地图首页，周期 `2026-08-15_2026-08-21`，全部门店，客源触达节点已选中

## Full-view comparison evidence

实现保留了现有产品的深色左侧导航和顶部业务头部，这是将 Figma 首页嵌入既有周报产品时的明确约束；经营地图主体保持 Figma 的浅色工作区、七节点横向链路、蓝色连接关系、客源触达入口、状态摘要和下方节点分析层级。首屏信息顺序与 Figma 一致，新增的周期、门店、数据版本和按需 AI 控件来自动态产品需求。

## Focused region comparison evidence

- 地图节点：七个节点的顺序、卡片尺寸关系、蓝色连接线、选中态和状态色均与源设计同一视觉语法。
- 地图下方：客源触达入口与经营状态摘要保持左右分组；动态值来自现有周记录，没有写死设计稿示例数字。
- 分析区：源设计的空白教学态替换为真实节点分析、长期机会、解决思路和打法验证，符合用户要求的可操作首页。
- 侧栏：源设计的提示卡被现有产品语境中的“分析与保留规则 / 共用信息源 / 最近验证记录”替代，承担相同的解释与辅助功能。

## Required fidelity surfaces

- Fonts and typography: 使用现有项目的 `Inter / PingFang SC / Microsoft YaHei` 字体链；标题、节点、状态和小字层级与源设计接近，动态长文本可换行。
- Spacing and layout rhythm: 经营地图、入口、摘要和分析区分组明确；修复了桌面 1440px 下由 grid 最小宽度造成的页面横向溢出。
- Colors and visual tokens: 主工作区使用源设计的 `#f6f8fb`、白卡、`#2157eb` 蓝色和红/橙/绿状态色；外壳沿用现有产品深色品牌色。
- Image quality and asset fidelity: 连接线与箭头使用从 Figma 节点导出的原始 SVG 资产；页面无占位图片或失真位图。
- Copy and content: 固定文案说明程序计算、按需 AI、缓存与长期保留边界；经营结论、机会和指标均从真实数据或提示词契约生成。
- States and interactions: 已验证周期/门店切换、节点切换、周报跳转、节点分析、分析缓存、验证弹窗、桌面/平板/窄屏布局。
- Accessibility: 核心控件使用原生 button/select，键盘可聚焦；状态不只依赖颜色，同时提供文字标签。

## Comparison history

### Iteration 1

- Earlier finding: `[P1]` 首页脚本缺少一个函数闭合括号，页面无法启动。
- Fix made: 补齐 `localWorkbenchAnalysis` 函数闭合并重新执行脚本语法检查。
- Post-fix evidence: 首页成功渲染，浏览器 DOM 快照能读取全部七个节点和分析区。

- Earlier finding: `[P2]` 1440px 桌面宽度出现约 127px 横向溢出。
- Fix made: 为既有 `.main` 和 `.workbench-page` 增加 `min-width: 0`，保留节点区域自身横向滚动能力。
- Post-fix evidence: 1440px 检查结果 `body.clientWidth === body.scrollWidth === 1425`；1024px 与 390px 同样无页面级横向溢出。

- Earlier finding: `[P2]` 未来测试周期 `2099` 抢占首页默认周期。
- Fix made: 周期仍保留可搜索，但默认选择当前时间后七天以内的最近有效周期，并显示“当前建议”。
- Post-fix evidence: 默认值稳定为 `2026-08-15_2026-08-21`。

- Earlier finding: `[P2]` 提示词 JSON 被静态服务安全规则拦截，外部模型模式只能使用前端兜底提示词。
- Fix made: 后端新增只读 `/api/strategy/prompts`，由版本化 JSON 提供提示词契约；页面改为从该接口读取。
- Post-fix evidence: 健康检查通过，接口返回 `operating-strategy-workbench-prompts-v1 / operating-node-analysis-v1`。

## Findings

当前无未解决的 P0 / P1 / P2 问题。现有深色产品外壳与 Figma 白色全局导航的差异属于既有产品集成约束；主体经营地图视觉和交互已经对齐。

## Follow-up polish

- `[P3]` 后续若建设全站设计系统，可把旧周报页的深色控件逐步统一到经营地图的浅色内容体系；本次不扩散重构范围。

## Primary interactions tested

- 首页默认加载和当前建议周期。
- 周期、门店和经营节点切换。
- “查看本周周报 / 查看关联周报”。
- 本地提示词模拟的“AI分析当前节点”及缓存版本状态。
- 打法“记录执行/验证”弹窗打开和取消。
- 1440、1024、390 宽度下无页面级横向溢出。
- 浏览器 console errors checked: none.

final result: passed

### Iteration 5 — operating analysis decision chain

- Rebuilt the selected-node analysis as a four-step operating decision chain: current state → weekly problem/opportunity → solution direction → executable tactic.
- Weekly problems and opportunities now come from current-period thresholds, data gaps, channel concentration, report signals, AI candidates, and confirmed long-term items. Long-term opportunities are a user-confirmed persistence state, not a prerequisite for showing current opportunities.
- Selecting a different problem/opportunity changes the relevant solution directions. Selecting a different direction filters tactics to that direction only; inactive tactics are no longer shown as a static catalog.
- Nodes without a meaningful current signal show an explicit observation state and do not invent an opportunity. The repurchase/referral data gap correctly routes to measurement setup with two concrete data-collection tactics.
- Verified in Chrome: all seven nodes render; problem switching changes direction candidates; direction switching changes tactic cards; no fresh console errors.
- Evidence: `qa/analysis-flow-after.png`.

final result: passed

### Iteration 4 — selected-node breakdown

- Fixed the map footer that previously rendered the same hard-coded acquisition entries for every selected operating node.
- The footer title and four supporting metrics now derive from the selected node and current period/scope: channel mix, entry/reception, first-purchase metrics, playback mix, value/card metrics, cumulative customer assets, or explicit repurchase data gaps.
- Verified all seven nodes in Chrome. Each node produced a distinct title and content set; the repurchase/referral node correctly shows four unconfigured data gaps instead of unrelated acquisition data.
- Evidence: `qa/node-breakdown-after.png`.

final result: passed

### Iteration 3 — source traceability

- Removed the internal match-count summary from the homepage source card.
- Replaced it with user-facing traceability: the selected node now shows the exact Feishu source document, sheet, data scope, verification state, and a direct link back to that sheet.
- Added a separate formal landing destination sourced from `data/feishu-target.json` through the read-only `/api/feishu/sources` endpoint, so the frontend does not maintain a second copy of the Feishu sheet catalog.
- Verified that changing the selected operating node changes both its source links and its formal target sheet. All visible external links open in a new tab.
- Evidence: `qa/source-trace-after.png`.

final result: passed

### Iteration 2 — operating-map icons

- Replaced the seven single-character placeholders with semantic Phosphor regular icons: acquisition, entry, first purchase, experience, value/card, customer asset, and repurchase/referral.
- Kept the icon treatment visually consistent with the existing blue operating-map system; hover and selected states now use a solid-blue container with a white icon.
- Verified all seven local SVG assets load successfully at 150 × 150 intrinsic size, retain their node labels, and do not change the card layout.
- Evidence: `qa/icons-after.png`.

final result: passed

### Iteration 6 — knowledge-grounded tactics and plan validation

- Replaced model-only tactic suggestions with retrieval from a versioned strategy knowledge contract. Current-period calendar matches, venue/audience context, internal experience, industry references, metrics and experiment templates now produce visible source-backed tactic cards.
- Added a separate “打法方案” page so the operating map remains a selection surface. The new page covers execution design, audience, scenario, mechanism, resources, primary/secondary/guardrail metrics, comparison, success criteria, stop conditions and recording rules.
- Added `tactic-plan-design-v1` as a versioned AI contract. The local simulator and external provider use the same payload and response schema; the model may adapt a retrieved tactic but cannot invent an unsupported tactic or rewrite operating facts.
- Added read-only GitHub repository search for technical tactics. Results show public repository metadata and remain candidates until license, security and modification cost are reviewed; no code is downloaded or executed.
- Chrome verification covered: calendar/profile retrieval, tactic source chips, selection into the independent plan page, local prompt-contract generation, human edit/fix state, persistence after reload, validation modal, GitHub search and external links. No page console errors remained.
- Evidence: `qa/tactic-recommendation-after.png`, `qa/tactic-plan-after.png`.

final result: passed
