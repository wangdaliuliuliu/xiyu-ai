/**
 * Live-model prompt comparison only. It never calls iLink and never writes conversation state.
 * Run explicitly: node scripts/proactive_prompt_ab.mjs
 */
import fs from 'node:fs';
import path from 'node:path';
import { getCompanionById, getDailySchedule, shanghaiDateKey } from '../src/db.mjs';
import { buildSystemPrompt } from '../src/companion.mjs';
import { generateReply } from '../src/ai.mjs';
import { buildInitiativeDecision, selectProactiveLifeEvidence, initiativePrompt } from '../src/initiative.mjs';
import { safeOutboundReply } from '../src/moderation.mjs';

const companionId = Number(process.argv[2] || 1);
const companion = getCompanionById(companionId);
if (!companion) throw new Error(`companion ${companionId} not found`);
const dailySchedule = getDailySchedule(companionId, shanghaiDateKey());
if (!dailySchedule?.items?.length) throw new Error('today schedule not found');

const lifeItem = [...dailySchedule.items]
  .filter(item => String(item.time || '') <= '15:59')
  .sort((a, b) => String(b.time).localeCompare(String(a.time)))[0];
const evidence = `${lifeItem.time} ${lifeItem.activity}`;
const systemPrompt = buildSystemPrompt(companion, { dailySchedule: { ...dailySchedule, date_key: shanghaiDateKey() }, promptMode: 'proactive' });
const currentDecision = buildInitiativeDecision({ companion, kind: 'normal', timingDecision: { trigger: 'share_thought', motivation: 55 } });
const clockParts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(new Date()).map(part => [part.type, part.value]));
const nowMinute = Number(clockParts.hour) * 60 + Number(clockParts.minute);
const lifeEvidence = selectProactiveLifeEvidence({ ...dailySchedule, date_key: shanghaiDateKey() }, nowMinute);
const proposedDecision = buildInitiativeDecision({ companion, kind: 'normal', timingDecision: { trigger: 'share_thought', motivation: 55 }, lifeEvidence });
const groundedSystemPrompt = buildSystemPrompt(companion, { dailySchedule: { ...dailySchedule, date_key: shanghaiDateKey() }, promptMode: 'proactive', proactiveLifeEvidence: lifeEvidence });

const variants = {
  current_layered: { system: systemPrompt, prompt: `${initiativePrompt(currentDecision)}\n\n把本次已选意图说得像真人随手发出的短消息：允许有情绪和个性，但只能使用真实上下文，不得随机编造同事、外卖、天气、视频、表情包或刚发生的生活事件。最多 2 段，用 || 分隔；不要套取资料，不要把回复当作关系考核。` },
  schedule_bare: { system: systemPrompt, prompt: `你要主动给他发一条自然的短消息。结合你今天的安排，可以聊你现在正在做的事。最多 2 段，用 || 分隔。` },
  compact_evidence_bound: { system: systemPrompt, prompt: `【本次动念】你按今天的安排正在做一件自己觉得值得分享的事，想借这件小事和他建立一点共同感。\n【可用事实】${evidence}\n【行动】自然分享其中一个具体点，可以带真实感受或一个低负担邀请；1-2 段短消息。\n【边界】只能把“可用事实”中的人、地点和事件当成已经发生；可以表达你的主观感受，但不要补写事实中没有的新人物、新遭遇或细节，也不要求他回复。` },
  proposed_compact_grounded: { system: groundedSystemPrompt, prompt: initiativePrompt(proposedDecision) },
};

const results = [];
for (const [variant, spec] of Object.entries(variants)) {
  for (let run = 1; run <= 3; run++) {
    const startedAt = Date.now();
    const raw = await generateReply(spec.system, [], spec.prompt, {
      temperature: 0.85, max_tokens: 180, top_p: companion.top_p,
    }, { accountId: null, skipSearch: true });
    results.push({ variant, run, latencyMs: Date.now() - startedAt, reply: safeOutboundReply(raw) });
  }
}

const report = {
  at: new Date().toISOString(), companionId, evidence,
  note: 'No iLink call and no conversation write; live chat model generation only.',
  promptChars: Object.fromEntries(Object.entries(variants).map(([key, value]) => [key, value.prompt.length])),
  results,
};
const out = path.resolve('docs/validation/2026-09-06/proactive-prompt-ab.json');
fs.mkdirSync(path.dirname(out), { recursive: true });
fs.writeFileSync(out, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
console.log(JSON.stringify(report, null, 2));
