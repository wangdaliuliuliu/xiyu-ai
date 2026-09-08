# 周报复盘 v6 实现说明

## 主链路

`本周事实与历史 → 识别重要变化 → 形成待验证假设 → 卡片内对话补证 → 生成复盘结论 → 选择经验/动作 → 生成完整周报`

程序计算的数字是唯一权威；模型只能识别信号、组织假设、审校运营回答和组织文字，不能修改数字。

## 调查卡片

每张卡片绑定稳定的 `signalKey` 和 `targetMetric`，同时保存 `evidence`、`trendEvidence`、`hypothesis`、`hypothesisBasis`、`retrievalHits`。调查尝试放在 `attempts[]` 中，当前尝试由 `activeAttemptId` 指向，消息按 `ai/user` 顺序保存，不显示轮次。

回答审校返回 `answerIntent`、`relevance`、`causalFit`、`evidenceLevel`、`decision` 和可选的一个 `nextQuestion`。最多两次追问；问题重复或没有信息增量时停止，最终以“已确认变化 + 运营事实 + 因果边界 + 待观察状态”形成结论。

## 刷新与追溯

系统用当前周期事实、经营背景和历史输入生成 `sourceFingerprint`。同一指纹再次刷新只重新渲染，不新建卡片、不清空对话；数据变化时按 `signalKey` 合并，旧尝试继续保留。用户点击“重新开始调查”会把当前尝试标记为 `superseded`，新建独立尝试。

## 模型接口

模型阶段对应 `backend/weekly-review-prompts-v6.json` 中的五个提示词 ID。初始识别允许模型返回新的调查信号，但每个信号必须引用输入事实；程序会校验引用并保留本地计算的数字。外部模型不可用时，内测模式使用同一输出契约的本地提示词模拟器。
