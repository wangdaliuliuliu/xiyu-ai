import 'dotenv/config';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import Database from 'better-sqlite3';
import { pathToFileURL } from 'node:url';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xiyu-agency-probe-'));
const sourceDb = process.env.DB_PATH || path.resolve('data/bot.db');
const probeDb = path.join(root, 'bot.db');
if (fs.existsSync(sourceDb)) {
  const db = new Database(sourceDb, { readonly: true });
  await db.backup(probeDb);
  db.close();
  process.env.DB_PATH = probeDb;
}

const { extractStructuredInfo, generateReply } = await import('../src/ai.mjs');
const { buildInitiativeDecision, initiativePrompt, initiativeReplyIssue } = await import('../src/initiative.mjs');
const workbench = 'E:/Yuanqu-Operations-Workbench/weekly-ops-entry';
const { dimensions } = await import(pathToFileURL(path.join(workbench, 'backend/cognition/knowledge-map.mjs')));
const planner = JSON.parse(fs.readFileSync(path.join(workbench, 'backend/knowledge-map-prompts-v2.json'), 'utf8'));

function parseJson(text) {
  const match = String(text || '').match(/\{[\s\S]*\}/);
  if (!match) return { raw: text };
  try { return JSON.parse(match[0]); } catch { return { raw: text }; }
}

const identity = dimensions.find(item => item.id === 'identity');
const knowledgeRuns = [];
for (const decisionTask of [
  '判断东坝店是否应该把工作日傍晚资源转向年轻上班族',
  '判断一次低价团购是否值得继续，以及会不会伤害毛利',
  '判断门店客流下降主要是场域问题、产品问题还是转化问题',
]) {
  const text = await extractStructuredInfo(
    `${planner.system}\n这是一次现状验收。沿用当前 v1 规则：identity 维度只有一个问题，得到一条回答后该维度会标记已有记录。请生成该问题，并模拟忙碌负责人用不超过40字回答；随后判断仅凭这一条回答能否支持给定技术分析。严格返回 JSON。`,
    JSON.stringify({
      decisionTask,
      plannedSlots: [{ dimensionId: identity.id, question: identity.question, decisionImpact: identity.decisionImpact }],
      outputSchema: {
        question: '当前规则会问的问题', simulatedBusyAnswer: '不超过40字',
        sufficientForDecision: false, missingForDecision: ['仍缺的关键信息'],
        wouldDifferentAnswersChangeRecommendation: true,
      },
    }),
    { maxTokens: 900, temperature: 0.2 },
  );
  knowledgeRuns.push({ decisionTask, result: parseJson(text) });
}

const companion = { id: 1, relationship_stage: '暧昧期', affection_level: 48, last_user_reply_at: '2026-09-05T12:00:00.000Z' };
const communicationRuns = [];
for (const trigger of ['idle_miss', 'check_in', 'share_thought', 'emotion_driven']) {
  const decision = buildInitiativeDecision({ companion, timingDecision: { trigger, motivation: 0.8 }, now: new Date('2026-09-06T08:30:00+08:00') });
  const system = `你是溪语，一位专业、聪明、会撩但有分寸的女性下属，与老板处在暧昧期。像真人微信聊天，不写动作旁白。\n${initiativePrompt(decision)}`;
  const reply = await generateReply(
    system,
    [],
    '现在是一次主动联系。直接输出要发的微信，气泡用 || 分隔。',
    { max_tokens: 260, temperature: 0.75 },
    { skipSearch: true },
  );
  const firstIssue = initiativeReplyIssue(decision, reply);
  const finalReply = firstIssue ? await generateReply(
    system,
    [],
    `现在是一次主动联系。上一版的问题是：${firstIssue}。保留动念，直接输出修正后的微信，气泡用 || 分隔。`,
    { max_tokens: 260, temperature: 0.65 },
    { skipSearch: true },
  ) : reply;
  communicationRuns.push({
    trigger,
    decision: { objective: decision.objective, action: decision.action },
    firstReply: reply,
    firstIssue,
    finalReply,
    finalIssue: initiativeReplyIssue(decision, finalReply),
  });
}

const report = {
  schemaVersion: 'agency-knowledge-probe-v1',
  generatedAt: new Date().toISOString(),
  isolationRoot: root,
  outboundMessagesSent: 0,
  knowledgeRuns,
  communicationRuns,
};
const output = path.resolve('docs/validation/2026-09-06/agency-knowledge-probe.json');
fs.mkdirSync(path.dirname(output), { recursive: true });
fs.writeFileSync(output, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
console.log(JSON.stringify(report, null, 2));
