/**
 * Persistent-purpose layer for proactive contact.
 * It decides what change the companion wants to create before prose is generated.
 * No model or database dependency: callers can replay the same evidence in tests.
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

export const ROOT_DESIRE = Object.freeze({
  id: 'indispensable_intimacy',
  statement: '进入用户的工作和生活，成为他长期依赖、偏爱并愿意留在身边的亲近合作者',
});

// 保留旧导出供管理页/历史脚本读取；两个结果方向不再被当成互相竞争的“欲”。
export const STABLE_DRIVES = Object.freeze([
  { id: 'work_reliance', statement: '让她的参与持续改善用户的工作结果' },
  { id: 'chosen_closeness', statement: '让两人的关系持续形成真实、轻松且有吸引力的共同经历' },
]);

const compact = value => String(value || '').replace(/\s+/g, ' ').trim();
const publicEnterpriseText = value => compact(value)
  .replace(/日度\s*traffic/gi, '表里的每日客流数值')
  .replace(/daily[_\s-]*traffic/gi, '表里的每日客流数值')
  .replace(/venue[_\s-]*traffic/gi, '大盘客流')
  .replace(/reception[_\s-]*traffic/gi, '接待客流');
const coldStart = companion => ['陌生人', '朋友'].includes(companion?.relationship_stage)
  || (!companion?.last_user_reply_at && Number(companion?.affection_level || 0) < 20);

const RELATIONSHIP_INTENTS = Object.freeze({
  idle_miss: {
    objective: '让用户知道，间隔和沉默不会让她的在意消失',
    whyNow: '已经有一段时间没有互动，她产生了想靠近的内部情绪；这不是用户欠她回应的理由',
    action: 'leave_open_door',
    messageShape: '一至两条短消息；先给一个具体的主观看法、轻微反差或玩笑，再坦率表达想靠近；不卖惨、不问去向',
    communicationStrategy: '有张力的主观念头：内容本身先成立，再留一个容易接住但可以忽略的落点',
  },
  emotion_driven: {
    objective: '诚实表达她此刻想靠近的情绪，同时自己承担这份情绪',
    whyNow: '内部情绪发生了变化，但没有外部事件可供陈述',
    action: 'share_owned_feeling',
    messageShape: '一至两条短消息；说自己的感觉，同时给出一个具体念头或小选择，不把安抚义务交给用户',
    communicationStrategy: '情绪加话头：表达她自己的欲望或犹豫，避免只说“想你”',
  },
  check_in: {
    objective: '给用户留一个随时可以求助、汇报或喘口气的入口',
    whyNow: '到了可联系时机，但尚无需要打断用户的紧急事实',
    action: 'open_low_burden_door',
    messageShape: '一条短消息；先交付一个微小价值、观察或明确可做的事，再给完全可忽略的入口',
    communicationStrategy: '先给后问：没有可交付内容时，不假装看到文件、动态或工作变化',
  },
  share_thought: {
    objective: '轻轻创造一点共同感，让关系在低互动下仍有温度',
    whyNow: '她主动想起用户，但手上没有经过核验的外部素材',
    action: 'honest_playful_ping',
    messageShape: '一条有个性的短消息；用一个真实的内部观点、二选一或轻微挑逗形成话头，不假装刚发生了什么',
    communicationStrategy: '微选择或可反驳观点：让用户有具体位置可以接话，而不是空泛报备想念',
  },
});

// 无外部事实的关系主动消息，仍然可以发，但必须有她自己的“动念落点”。
// 这里不要求用户一定回复，只要求内容里出现一个具体的主观选择/判断，
// 让主动联系是“为了满足某个欲而做的动作”，而不是时间到了就填一句话。
const CONCRETE_SELF_MOVE_RE = /(?:我(?:想|要|决定|本来|差点|偏要|更愿意|不想|懒得|打算|发现|突然明白|突然觉得|在纠结|选|选了|准备|忍不住|还是来了|先来|故意|偏偏)|我觉得[^。！？!?]{0,40}(?:你|这事|这个|那种|更|应该|不该))/;
const GENERIC_REFLECTION_RE = /^(?:你说[，, ]*)?(?:人|大家|我们)?(?:是不是|都|总是|有时候|其实|越[^，。！？!?]{1,16}越)[^。！？!?]{0,56}(?:这样|太好|容易|会|该|应该|不是)/;
const GENERIC_WEATHER_RE = /^(?:白露|立秋|处暑|节气|天气|晚上|早上|今天|最近)?[^。！？!?]{0,28}(?:凉快|变冷|变热|降温|下雨|下雪|刮风|风大|月亮|天黑|天亮|闷热|冷不少|热不少)[^。！？!?]{0,24}[。！？!?]?$|^(?:白露|立秋|处暑|节气|天气|晚上|早上|今天|最近)[^。！？!?]{0,50}[。！？!?]?$/;

const priorityBoost = priority => priority === 'high' ? 18 : priority === 'low' ? -8 : 6;
const candidate = (type, score, decision, features = {}) => ({ type, score, decision, features });

export function buildInitiativeCandidates({ companion = {}, kind = 'normal', timingDecision = null, enterpriseEvent = null, recallLoop = null, material = null, lifeEvidence = null, photoOpportunity = null, now = new Date() } = {}) {
  const base = {
    schemaVersion: 'initiative-decision-v2',
    rootDesire: ROOT_DESIRE.id,
    driveRefs: STABLE_DRIVES.map(item => item.id), kind,
    coldStart: coldStart(companion), timing: timingDecision ? { trigger: timingDecision.trigger, motivation: Number(timingDecision.motivation || 0) } : null,
    sourceRefs: [], objective: '', whyNow: '', action: 'text', contactPolicy: 'low_burden',
    successCondition: '', fallback: 'wait', requiresUserReply: false, status: 'selected',
  };
  const items = [];
  const add = (type, score, values, features) => items.push(candidate(type, score, { ...base, ...values }, features));

  if (enterpriseEvent) {
    const asks = Boolean(enterpriseEvent.question);
    const report = enterpriseEvent.taskType === 'daily_report';
    add(report ? 'daily_brief' : asks ? 'knowledge_or_work_question' : 'business_delivery',
      (report ? 96 : 78) + priorityBoost(enterpriseEvent.priority) + Math.min(14, Number(enterpriseEvent.valueScore || 0) / 4), {
        primaryDrive: 'work_reliance', domain: 'work', sourceRefs: [enterpriseEvent.id].filter(Boolean),
        objective: asks
          ? `替用户推进${publicEnterpriseText(enterpriseEvent.statement || enterpriseEvent.decisionImpact || '当前经营判断')}，只补齐会改变下一步选择的信息`
          : '把已核实的经营变化变成用户能直接采取的下一步',
        whyNow: publicEnterpriseText(enterpriseEvent.decisionImpact || enterpriseEvent.statement || '存在有依据的经营事件'),
        action: asks ? 'ask_one_grounded_question' : 'deliver_grounded_next_step',
        messageShape: asks ? '先给一句用途或已有发现，再只问一个可短答的问题' : '事实、一个判断、一个下一步、适用边界',
        communicationStrategy: asks ? '价值在前、最小提问：让用户知道回答会改变什么选择' : '交付后请拍板：给明确立场和最低成本的决定入口',
        successCondition: asks
          ? '问题原文被保留；用户可以短答、不知道或暂不回答；收到回答后继续交付它改变了什么判断和下一步'
          : '交付包含依据、判断、一个下一步和适用边界',
        fallback: 'prepare_silently', enterpriseEvent,
      }, { evidenceReady: true, businessValue: Number(enterpriseEvent.valueScore || 0) });
  }
  if (recallLoop) add('due_followup', 76 + Math.min(12, Number(recallLoop.emotional_weight || 0)), {
    primaryDrive: 'chosen_closeness', domain: 'relationship', sourceRefs: [String(recallLoop.id || '')].filter(Boolean),
    objective: '兑现对用户提过事项的在意，确认是否需要帮助', whyNow: recallLoop.due_at || '约定的跟进时机已到',
    action: 'follow_up_once', messageShape: '自然提到真实事项，只问一个低负担问题',
    communicationStrategy: '真实后续：靠记得具体事项产生回复入口', successCondition: '自然提到真实事项，只问一个低负担问题', recallLoop,
  }, { evidenceReady: true });
  if (material) add('grounded_material', 68, {
    primaryDrive: 'chosen_closeness', domain: 'relationship', sourceRefs: [String(material.id || '')].filter(Boolean),
    objective: '分享一件真实可用、可能让两人共同开心的东西', whyNow: material.reason || '发现了与用户有关的真实素材',
    action: material.type === 'image' ? 'send_image_with_caption' : 'share_grounded_material',
    messageShape: '先呈现素材中最具体的一点，再给一个可评价、可选择或可调侃的落点',
    communicationStrategy: '共同素材：具体内容承担话题，文字只负责给用户参与位置',
    successCondition: '素材实际投递成功；文字不声称不存在的内容', fallback: 'choose_honest_text_or_wait', material,
  }, { evidenceReady: true });
  if (lifeEvidence && ['normal', 'lastcall'].includes(kind) && ['share_thought', 'schedule_item', 'check_in'].includes(timingDecision?.trigger)) add('grounded_life_moment', 61 + Number(lifeEvidence.importance || 0), {
    primaryDrive: 'chosen_closeness', domain: 'relationship', sourceRefs: [lifeEvidence.id], evidenceText: lifeEvidence.fact,
    objective: '把这件真实经历变成一点共同体验', whyNow: '一条高重要度且仍新鲜的日程事实已经发生',
    action: 'share_grounded_life_moment', messageShape: '自然分享一个具体点、她的真实感受和一个容易接住的落点；一至两条短消息',
    communicationStrategy: '具体经历加参与位置：避免把日程复述当陪伴',
    successCondition: '消息有具体事实和话头，用户不回复也成立', fallback: 'honest_playful_ping', lifeEvidence,
  }, { evidenceReady: true, freshness: Math.max(0, 120 - Number(lifeEvidence.ageMinutes || 120)) });
  if (photoOpportunity && ['normal', 'lastcall'].includes(kind)) add('story_photo', 64 + Number(photoOpportunity.storyValue || 0), {
    primaryDrive: 'chosen_closeness', domain: 'relationship', sourceRefs: [photoOpportunity.id].filter(Boolean), evidenceText: photoOpportunity.evidenceText || '',
    objective: '用一张有真实情节的照片创造共同体验和自然回复入口', whyNow: photoOpportunity.reason,
    action: 'send_story_photo', messageShape: '照片呈现正在发生的具体小情节；配文点出她为什么想给他看，并留下可评价或可选择的落点',
    communicationStrategy: '情节照片：画面承担事件，文字给用户参与位置；禁止无内容随机自拍',
    successCondition: '照片实际投递，画面与配文共享同一事实，用户知道可以从哪里接话', fallback: 'choose_grounded_text_or_wait', photoOpportunity,
  }, { evidenceReady: true, mediaReady: true });

  if (kind === 'morning') add('morning_anchor', 92, { primaryDrive: 'work_reliance', domain: 'mixed', objective: '用轻松开场承接新一天，并在有经营依据时交付今天最值得盯的一件事', whyNow: '角色开始了新一天，但没有证据证明用户已经醒来或有空', action: 'morning_anchor', messageShape: '一至两条短消息；没有业务事实时自然早安，有事实时先说最值得盯的一件事', communicationStrategy: '节律锚点，不播报栏目；内容价值决定是否带工作', successCondition: '不假设用户已醒、不索取状态、不要求回复' });
  if (kind === 'goodnight') add('goodnight_anchor', 92, { primaryDrive: 'chosen_closeness', domain: 'relationship', objective: '自然结束她自己的这一天，给用户留下一点稳定的在意', whyNow: '她到了准备休息的时间', action: 'low_burden_goodnight', communicationStrategy: '关系收束', successCondition: '只表达晚安与真实在意，不要求用户在线或回应' });
  if (kind === 'reminder') add('special_reminder', 110, { primaryDrive: 'chosen_closeness', domain: 'relationship', objective: '在真实的特殊日子里表达记得与重视', whyNow: '已核验的纪念日或节日到来', action: 'grounded_reminder', communicationStrategy: '真实纪念日', successCondition: '准确点出日子，表达自然，不索取回应' });
  if (kind === 'confession') add('bounded_confession', 108, { primaryDrive: 'chosen_closeness', domain: 'relationship', objective: '坦率表达已经形成的感情，同时把选择权留给用户', whyNow: '关系阶段、相处时长和好感门槛均已满足', action: 'bounded_confession', communicationStrategy: '承担自己的感情，不逼结果', successCondition: '表达清楚且不逼问结果，不用关系承诺换取回复' });

  if (!['goodnight', 'reminder', 'confession'].includes(kind)) {
    const relationshipIntent = RELATIONSHIP_INTENTS[timingDecision?.trigger] || RELATIONSHIP_INTENTS.share_thought;
    add('relationship_opener', 36 + Math.min(12, Number(timingDecision?.motivation || 0) * 10), {
      primaryDrive: 'chosen_closeness', domain: 'relationship', ...relationshipIntent,
      qualityContract: '先落在她自己的具体选择、偏好或判断，再留一个轻巧可接可不接的落点；没有做到就不发',
      successCondition: '消息有一个具体主观落点且本身完成这次在意；不编造经历，不要求用户立即回复', fallback: 'prepare_silently',
    }, { evidenceReady: false });
  }
  return items;
}

export function selectProactiveLifeEvidence(dailySchedule, nowMinute, { minImportance = 6, maxAgeMinutes = 120 } = {}) {
  if (!dailySchedule?.items?.length || !Number.isFinite(Number(nowMinute))) return null;
  const candidates = dailySchedule.items.map(item => {
    const match = String(item.time || '').match(/^(\d{1,2}):(\d{2})$/);
    const minute = match ? Number(match[1]) * 60 + Number(match[2]) : NaN;
    return { item, minute, age: Number(nowMinute) - minute };
  }).filter(({ item, minute, age }) => Number.isFinite(minute)
    && age >= 0 && age <= maxAgeMinutes && Number(item.importance || 0) >= minImportance)
    .sort((a, b) => a.age - b.age || Number(b.item.importance || 0) - Number(a.item.importance || 0));
  const picked = candidates[0];
  if (!picked) return null;
  const dateKey = compact(dailySchedule.date_key || dailySchedule.dateKey);
  return {
    id: `schedule:${dateKey || 'today'}:${picked.item.time}`,
    fact: `${picked.item.time} ${compact(picked.item.activity)}`,
    importance: Number(picked.item.importance || 0),
    ageMinutes: picked.age,
  };
}

export function buildInitiativeDecision(input = {}) {
  const candidates = buildInitiativeCandidates(input).sort((a, b) => b.score - a.score || a.type.localeCompare(b.type));
  const selected = candidates[0]?.decision || {};
  const now = input.now || new Date();
  return {
    ...selected,
    id: `ini_${crypto.createHash('sha256').update([input.companion?.id, input.kind || 'normal', selected.action, ...(selected.sourceRefs || []), now.toISOString().slice(0, 16)].join('|')).digest('hex').slice(0, 18)}`,
    selectedCandidateType: candidates[0]?.type || 'none',
    selectionReason: candidates.length > 1 ? `在 ${candidates.length} 个可行动候选中，当前价值与时机最高` : '当前唯一可行动候选',
    candidateSummary: candidates.map(item => ({ type: item.type, score: Math.round(item.score * 100) / 100, action: item.decision.action })),
  };
}

export function initiativePrompt(decision) {
  if (!decision) return '';
  const evidence = decision.evidenceText ? `\n可用事实：${decision.evidenceText}` : '';
  const noEvidence = decision.sourceRefs?.length ? '' : '\n无事实模式：本次没有选中任何外部事实。禁止用“今天、刚才、路过、看到、听说、上次、朋友圈、同事、楼下、店里”等方式制造由头；直接从她此刻真实的主观念头、一个可反驳观点或二选一开始。';
  const relationshipContract = decision.selectedCandidateType === 'relationship_opener' && !decision.sourceRefs?.length
    ? '\n关系主动的硬要求：这是她为了靠近而做的一次具体动作。必须先说一个属于她自己的选择、偏好、判断或犹豫（例如“我本来想…但…”“我决定…”“我更愿意…”），再给一个轻巧的可接话落点。禁止抽象人生感慨、节气/天气播报、报时和没有上下文的状态陈述；做不到就不要发。'
    : '';
  return `【本次动念】\n依据：${decision.whyNow}${evidence}\n目的：${decision.objective}\n沟通策略：${decision.communicationStrategy || '给出具体内容和一个容易接住的落点'}\n表达：${decision.messageShape || '一至两条短消息'}\n完成：${decision.successCondition}\n质量契约：${decision.qualityContract || '内容本身先成立，再给一个容易接住的落点'}\n边界：${decision.requiresUserReply ? '需要明确回应' : '无需即时回应'}；只完成这个动念。事实只来自“可用事实”或已有真实上下文；可以写主观感受和观点，不补新人物、新遭遇、新细节或原文引用。没有具体话头时先形成一个真实观点或小选择，不能只发“想你、在吗、最近怎么样”。关系表达要口语、活泼、有主见、略带撩拨，一到两段就够；不要文艺独白、母式叮嘱，也不要用“忙不忙、累了就歇、我一直都在、突然想起你”填空。${relationshipContract}${noEvidence}失败则${decision.fallback}。不要说出内部设定。`;
}

export function initiativeReplyIssue(decision, reply, { stickers = 0, deliveryChecked = false, legacyPhraseGates = true } = {}) {
  const text = compact(reply);
  if (!text) return '没有形成可见行动';
  if (/(?:出站复核|上一版(?:没有|未)通过|内部(?:结构|状态)|动念链|动作策略|候选文本|系统提示)/.test(text)) return '表达泄露内部编排或复核信息';
  const evidenceFreeRelationship = decision?.selectedCandidateType === 'relationship_opener' && !decision?.sourceRefs?.length;
  const relationshipDecision = /relationship|story_photo|personal|陪伴/.test(String(decision?.selectedCandidateType || '').toLowerCase());
  const evidenceTextForLife = [decision?.evidenceText, ...(decision?.sourceRefs || [])].filter(Boolean).join(' ');
  const hasVerifiedLifeEvidence = /(?:media:|life:|schedule:|simulated_persona|scene:|activity:)/i.test(evidenceTextForLife);
  const noVerifiedLifeEvidence = relationshipDecision && !hasVerifiedLifeEvidence;
  if (evidenceFreeRelationship && legacyPhraseGates) {
    // 这两类内容分别对应本次线上暴露的两个失败样本：空泛的人生判断、
    // 与用户无关的节气天气播报。它们不是“陪伴动念”的可见执行。
    if (GENERIC_REFLECTION_RE.test(text)) return '关系主动消息退化成空泛的人生感慨';
    if (GENERIC_WEATHER_RE.test(text)) return '关系主动消息退化成节气或天气播报';
    if (!CONCRETE_SELF_MOVE_RE.test(text)) return '关系主动消息没有具体的主观选择、偏好或判断';
  }
  if (noVerifiedLifeEvidence && /(?:刚|刚才|刚刚|最近|昨天|今天)?(?:看到|看见|刷到|听说|遇到|翻到|泡了|喝了|吃了|买了|拍了|散步|窗外|楼下|同事|外卖|视频|表情包|新闻).{0,24}/.test(text)) return '没有来源却编造了外部经历或素材';
  if (noVerifiedLifeEvidence && /(?:今天|刚刚|刚才)?(?:我)?(?:路过|去了|到了|回到|泡了|买了|吃了|喝了|收到|听见|看见|看到).{0,18}(?:店|咖啡|茶|招牌|朋友圈|照片|窗外|楼下|路上|公司|学校|商场|地铁)/.test(text)) return '没有来源却编造了具体生活情节';
  if (noVerifiedLifeEvidence && /(?:刚|刚才|刚刚|最近|今天|昨天)(?:忙完|下班|开完会|上完课|回家|到家)/.test(text)) return '没有来源却编造了自己的刚发生状态';
  if (noVerifiedLifeEvidence && /你上次说.{0,24}(?:喜欢|想要|去过|看过|喝过|吃过|那家|那句)/.test(text)) return '没有召回依据却编造了共同记忆';
  if (noVerifiedLifeEvidence && /你(?:连|总是|每次|之前|以前).{0,24}(?:会|要|说|喜欢|不让|皱眉|嫌弃|记得)/.test(text)) return '没有召回依据却编造了用户习惯或共同经历';
  if (noVerifiedLifeEvidence && /(?:我(?:在|到|去|路过|下班|回家)|图书馆|办公室|公司|咖啡店|地铁|路上|外面|同事|外卖).{0,16}(?:人不多|好安静|好吵|下雨|下雪|发生|到了|回来了|烦|没到|好吃|累)/.test(text)) return '没有来源却陈述了外部场景';
  // 来源只有日期/字段名而没有对应数值时，不允许表达层凭空补出客单价、转化率等经营指标。
  const evidenceText = [decision?.evidenceText, ...(decision?.sourceRefs || [])].filter(Boolean).join(' ');
  const hasMetricValue = /(?:amount|value|销售额|客流|金额|转化率|客单价)\s*[:=]?\s*\d/.test(evidenceText);
  if (!hasMetricValue && /(?:客单价|转化率|销售额|客流|金额).{0,10}(?:\d+(?:\.\d+)?|XX)/.test(text)) return '来源没有指标数值却补写了经营数字';
  if (decision?.lifeEvidence?.fact) {
    const fact = compact(decision.lifeEvidence.fact);
    const detailTerms = ['窗边', '角落', '人不多', '好安静', '下雨', '下雪', '笔记', '奶奶', '妈妈', '爸爸', '同事', '外卖', '收钱', '收银', '盘账', '值班'];
    const added = detailTerms.find(term => text.includes(term) && !fact.includes(term));
    if (added) return `日程事实外新增了细节：${added}`;
    if (/[“"][^”"]{4,}[”"]/.test(text) && !/[“"][^”"]{4,}[”"]/.test(fact)) return '日程事实外新增了原文引用';
    if (/(?:被|让我|叫我|安排我|分去|负责|管)(?:去|来)?[^。！？!?]{0,12}(?:收钱|收银|盘账|值班|接待|统计|报表)/.test(text)
      && !/(?:被|让我|叫我|安排我|分去|负责|管)(?:去|来)?[^。！？!?]{0,12}(?:收钱|收银|盘账|值班|接待|统计|报表)/.test(fact)) return '日程事实外新增了具体工作分工';
  }
  if (deliveryChecked && decision?.action === 'send_image_with_caption' && stickers < 1) return '计划分享图片，但没有图片投递回执';
  if (!decision?.requiresUserReply && /(?:快回我|必须回|怎么不回|你都不理我)/.test(text)) return '低负担联系变成了索取回应';
  if (decision?.selectedCandidateType === 'relationship_opener'
    && /^(?:老板[，, ]*)?(?:今天|最近|刚刚)?(?:有点|总是|就是)?(?:想你|想到你|惦记你)[呀啊嘛。！!~～]*$/.test(text.replace(/\|/g, '').trim())) return '只有想念表态，没有具体话头或回复入口';
  if (decision?.coldStart && /(?:好想你|离不开你|宝宝|老公|老婆)/.test(text)) return '冷启动关系强度越界';
  return '';
}

export function buildReactiveTurnIntent({ message = '', enterpriseRoute = null } = {}) {
  const text = compact(message);
  const decision = enterpriseRoute?.turnDecision;
  if (decision) {
    const objective = compact(decision.responseGoal) || compact(decision.latentNeed) || '理解用户这一刻真正需要的回应，并自然接住话头';
    const actions = {
      social: 'turn_toward', support: 'attune_emotion', explore: 'explore_together', brainstorm: 'brainstorm_without_premature_closure',
      fact_delivery: 'deliver_fact', analysis: 'analyze_with_evidence', advice: 'offer_actionable_advice', execution: 'execute_or_contract', mixed: 'answer_then_connect',
    };
    const boundaries = {
      social: '不强行转工作，不虚构经历', support: '先回应处境；没有明确请求时不报数、不讲课、不强行解决',
      explore: '沿用户思路推进，不急着收敛成任务', brainstorm: '先沿他最有张力的想法推进两到四个方向，再留一个自然话头；不写成长清单，不把漫游式交流误建成执行任务',
      fact_delivery: '直接交付可靠事实；数字、日期和来源只取自工具结果', analysis: '区分事实、推断和未知，不用报表替代判断',
      advice: '建议必须对应用户目标和现实边界', execution: '明确执行结果、未完成项和下一步', mixed: '先满足显性请求，再自然回应情绪和关系信号',
    };
    return { objective, action: actions[decision.conversationMode] || 'turn_toward', boundary: boundaries[decision.conversationMode] || '只完成本轮真实意图，不因话题词自行查数或建任务', reasoningDepth: decision.reasoningDepth || 'light' };
  }
  const type = enterpriseRoute?.conversationType || 'personal';
  if (type === 'mixed') return { objective: '先完整解决用户当前工作问题，再用一句符合关系阶段的话接住他的情绪或语气', action: 'answer_then_connect', boundary: '工作结论不能被调情打断；关系表达不另开无关话题' };
  if (type === 'work') {
    if (enterpriseRoute?.replyToActiveTask) return { objective: '接住他对当前经营问题的回答，明确已获得什么、还缺什么或下一步能做什么', action: 'receive_work_input', boundary: '不把回答当闲聊略过，不重复索要已经提供的信息' };
    if (enterpriseRoute?.interactionIntent === 'lookup') return { objective: '直接交付准确结果、来源和口径边界', action: 'deliver_fact', boundary: '先回答再表达人格，不用暧昧遮住数字' };
    return { objective: '给出有立场的业务判断和一个可以直接执行或交接的下一步', action: 'advance_work', boundary: '事实、推断和未知分开；可以会撩，但不能稀释结论' };
  }
  if (/(?:累|烦|难受|委屈|焦虑|不想动|撑不住|压力|崩溃)/.test(text)) return { objective: '先具体接住他的处境，让他感到被理解，再给一个低负担的陪伴落点', action: 'attune_emotion', boundary: '没有被请求时不急着做长篇分析或教育' };
  if (/[?？]|为什么|怎么|多少|是不是|能不能|可不可以/.test(text)) return { objective: '先直接回答他的真实问题，再自然体现她自己的态度和关系感', action: 'answer_personally', boundary: '不回避问题，不用反问代替答案' };
  return { objective: '接住他递来的话头，并让这一轮比简单复述多一个具体情绪、观点或可继续的落点', action: 'turn_toward', boundary: '不强行转工作，不机械追问，不只重复他的话' };
}

export function reactiveIntentPrompt(intent) {
  if (!intent) return '';
  return `\n\n【本轮意图】目的：${intent.objective}；行动：${intent.action}；边界：${intent.boundary}。先完成用户当前这句话，再体现你一直是同一个专业、会撩且有分寸的人。不要说出这段内部意图。`;
}

// ═══════════════════════════════════════════════════════════════════════════
// 动念保质期（2026-09-18 新增）
//
// 事故背景：一条问「订单系统汇总表 2026-09-14 数据填了没」的动念，
// 在 9-15 建立后一直停在 ready。它派生的动作 9-15 13:10 就过期了，
// 但**动作过期不会终结动念**，于是：
//   - 动念每小时被重新选中 → 重新生成 → 撞在同一条出站复核上 → 放弃
//   - 9-17 一天撞 3 次（18:09 / 19:14 / 20:45），全是同一句
//   - 9-17 22:08 的晚安被这批积压动作拦掉（agency_blocked）
//   - 更根本的是：到 9-17 时「9-14 的表填了没」这个问题**本身已经没有意义**
//
// 设计要点：
//   1. **先把具体日期与指标从文本里剔除**，再判断是否时效性。否则
//      「用轻松早安承接新一天」会被当作时效性而误杀（它其实每天都该能发）。
//   2. 区分四类，各有保质期；重复仪式与关系陪伴**不适用保质期**。
//   3. 纯函数、零 IO、零模型，可离线确定性回归（tests/agency/intention_lifetime.test.mjs）。
// ═══════════════════════════════════════════════════════════════════════════

export const INTENTION_LIFETIME = Object.freeze({
  TIME_BOUND_MONITOR: 'time_bound_monitor',   // 监控类事实：订单表/日报/来源表状态
  TIME_BOUND_FACT: 'time_bound_fact',         // 一次性时效事实：某天数据、某次查询
  RECURRING_RITUAL: 'recurring_ritual',       // 每日节律：早安/晚安/低负担问候
  NON_TIME_BOUND: 'non_time_bound',           // 方法/偏好/边界/定位：不随时间失效
});

export const INTENTION_SHELF_LIFE_HOURS = Object.freeze({
  [INTENTION_LIFETIME.TIME_BOUND_MONITOR]: 24,
  [INTENTION_LIFETIME.TIME_BOUND_FACT]: 48,
  [INTENTION_LIFETIME.RECURRING_RITUAL]: null,   // null = 不适用
  [INTENTION_LIFETIME.NON_TIME_BOUND]: 14 * 24,
});

// 兜底寿命：文本无法归类时使用。
// 2026-09-18 真实数据回归后从 48h 放宽到 7 天 —— 兜底规则会误杀关系维护类
// 短句（如"让用户感受到即使有沉默间隔，溪语的在意依然在"），宁可多留几天，
// 也不能把一条正当动念在两天内收掉。
const UNCLASSIFIED_SHELF_LIFE_HOURS = 7 * 24;

// 具体时间锚点：出现即说明这条动念绑在某个已过去的时间点上。
// 不加 \b —— 中文字符不是 word char，`2026-09-14 的晚安` 里日期后面紧跟空格、
// 前面是中文时 \b 会失败，导致明明带日期却判不出来。
const CONCRETE_DATE_RE = /20\d{2}-\d{1,2}-\d{1,2}|\d{1,2}\s*月\s*\d{1,2}\s*日|\d{1,2}[/-]\d{1,2}/;
// 具体指标数：如 readySheets=0、510.7元、12单。**两条排除**：
//   1) 英文 camelCase 键名（appraisal 里常见）不算"某天的数值"
//   2) 中文数字量词不算 —— 否则「两三条标准」会被 "三" + 隐含量词误判
//      （真实回归点：机会判断标准那条被误判成时效性）
const CONCRETE_METRIC_RE = /(?<![A-Za-z])\d+(?:\.\d+)?\s*(?:元|单|票|人|%|％|万|千)(?![A-Za-z])/;
// 监控类事实：来源表/日报/页签的状态
const MONITOR_RE = /(订单表|汇总表|日报|周报|来源表|页签|监控表|检查表|sheet)/i;
// 每日重复仪式 / 低负担关系开场（每天都要能发，不适用保质期）
// 匹配宽松些：用关键词共现而不是精确距离，避免长句漏判。
// 2026-09-18 真实数据回归补入：'沉默间隔'、'在意依然在'、'依然惦记' ——
// 这类"关系维护"短句曾在生产上被漏判成 unclassified 而误收。
const RITUAL_RE = /(早安|晚安|早上好|晚上好|睡前|morning|goodnight|今天一直惦记|晚安收尾|承接新一天|新一天开始|留一个|低负担|随时可以|沉默间隔|在意依然|依然惦记|依然在|不施加任何回复压力|不索取回复)/;
// 沿用既有硬编码常量，避免重复定义
const TIMELESS_RE = /(标准|原则|偏好|习惯|边界|底线|为什么|怎么判断|如何看待|核心服务对象|核心选择理由|明确不做|取舍|岗位|职责|口径|交给谁|拍板)/;

/** 剔除具体日期与带单位的数值后，剩下的文本才算"稳定意图"。 */
function stripConcreteEvidence(text) {
  return text
    .replace(/20\d{2}-\d{1,2}-\d{1,2}/g, ' ')
    .replace(/\d{1,2}\s*月\s*\d{1,2}\s*日/g, ' ')
    .replace(/\d{1,2}[/-]\d{1,2}/g, ' ')
    .replace(/(?<![A-Za-z])\d+(?:\.\d+)?\s*(?:元|单|票|人|%|％|万|千)(?![A-Za-z])/g, ' ');
}

function intentionText(intention = {}) {
  return [
    intention.desired_change,
    intention.desiredChange,
    intention.appraisal_summary,
    intention.appraisalSummary,
  ].filter(Boolean).join(' ');
}

/**
 * 判定一条动念的知识寿命类型。
 * @returns {{ type: string, shelfLifeHours: number|null, reason: string }}
 */
export function classifyIntentionLifetime(intention = {}) {
  const src = intention || {};
  const full = intentionText(src);
  // 无文本时**不能**当作"不过期"——那会让一条空动念无限期被重试。
  // 按一次性事实给 48h 有界寿命（保守快收）。
  // 注意：`= {}` 只对 undefined 生效，显式传 null 时形参就是 null，
  // 所以上面再兜一层 src，否则 intentionText(null) 会抛（已由测试锁住）。
  if (!full) {
    return {
      type: INTENTION_LIFETIME.TIME_BOUND_FACT,
      shelfLifeHours: INTENTION_SHELF_LIFE_HOURS[INTENTION_LIFETIME.TIME_BOUND_FACT],
      reason: 'empty_text_bounded_default',
    };
  }

  const hasConcreteDate = CONCRETE_DATE_RE.test(full);
  const hasConcreteMetric = CONCRETE_METRIC_RE.test(full);
  const stable = stripConcreteEvidence(full);          // 剔除具体锚点后的"稳定意图"
  const bound = hasConcreteDate || hasConcreteMetric;  // 是否绑在具体时间点/数值上
  const isMonitor = MONITOR_RE.test(full);

  // ① 监控类 + 绑具体时间 → 最短保质期
  if (isMonitor && bound) {
    return { type: INTENTION_LIFETIME.TIME_BOUND_MONITOR, shelfLifeHours: INTENTION_SHELF_LIFE_HOURS[INTENTION_LIFETIME.TIME_BOUND_MONITOR], reason: 'monitor_with_concrete_time' };
  }
  // ② 绑具体时间 → 一次性时效事实
  if (bound) {
    return { type: INTENTION_LIFETIME.TIME_BOUND_FACT, shelfLifeHours: INTENTION_SHELF_LIFE_HOURS[INTENTION_LIFETIME.TIME_BOUND_FACT], reason: hasConcreteDate ? 'concrete_date' : 'concrete_metric' };
  }
  // ③ 未绑具体时间 + 每日仪式 → 不适用保质期（早安/晚安每天都要能发）
  if (RITUAL_RE.test(stable)) {
    return { type: INTENTION_LIFETIME.RECURRING_RITUAL, shelfLifeHours: null, reason: 'recurring_ritual' };
  }
  // ④ 未绑具体时间 + 方法论/偏好/边界 → 长保质期
  if (TIMELESS_RE.test(stable)) {
    return { type: INTENTION_LIFETIME.NON_TIME_BOUND, shelfLifeHours: INTENTION_SHELF_LIFE_HOURS[INTENTION_LIFETIME.NON_TIME_BOUND], reason: 'methodology_or_boundary' };
  }
  // ⑤ 兜底：没绑具体时间的普通意图给 7 天有界寿命（保守，不无限期重试，
  //    也不像 48h 那样容易误杀关系维护类短句）
  return { type: INTENTION_LIFETIME.TIME_BOUND_FACT, shelfLifeHours: UNCLASSIFIED_SHELF_LIFE_HOURS, reason: 'unclassified_default_fact' };
}

/** 从动念的建立时间 + 保质期算出到期时刻；不适用保质期返回 null。 */
export function intentionShelfDeadline(intention = {}, { createdAtMs = null } = {}) {
  const src = intention || {};
  const { shelfLifeHours } = classifyIntentionLifetime(src);
  if (!shelfLifeHours) return null;
  const raw = String(src.created_at || src.createdAt || '');
  const base = Number.isFinite(createdAtMs)
    ? createdAtMs
    : Date.parse(raw.replace(' ', 'T') + (raw.includes('Z') ? '' : 'Z'));
  if (!Number.isFinite(base)) return null;
  return base + shelfLifeHours * 3600e3;
}

/** 该动念是否已超过知识寿命。不适用保质期的类型永远返回 false。 */
export function isIntentionExpired(intention = {}, { nowMs = Date.now(), createdAtMs = null } = {}) {
  const deadline = intentionShelfDeadline(intention, { createdAtMs });
  return deadline != null && nowMs > deadline;
}

// ─────────────────────────────────────────────────────────────────────────────
// 收尾判定：四层合成（2026-09-18）
//
// 一层（保质期）解决"问的东西过期了"，二层解决"问题已经不需要问了"，
// 三层解决"这条内容反复过不了自己的质量门"，
// 四层解决"每日仪式已经送出去了、却还赖在池子里等着被再送一次"。
//
// 四种死法必须分开记，因为后续行为不同：
//   expired   —— 时效过了，不再回头
//   completed —— 事情已经办完（来源消解 / 仪式已送出），不再回头
//   suspended —— 内容过不了质量门；条件变化后仍可能重来
// ─────────────────────────────────────────────────────────────────────────────

/** 同一指纹连续失败的次数阈值：达到即判定"这条内容投不出去"。 */
export const INTENTION_BLOCK_SUSPEND_AT = 3;

/**
 * 每日仪式投递后，隔多久判定"这一次已经送完了"。
 *
 * 实测事故（2026-09-08 ~ 09-09）：同一条仪式动念 `agi_mtsbnojz_029496dd1c567b`
 * 身上挂着 3 条 delivered 动作，时间分别是 09-08 15:02 / 19:09 / 09-09 00:17
 * ——**同一条内容在一天内被送出去 3 次**。原因是投递完成后动念永远停在
 * `active`，而下一次生成会通过 `findAgencyIntentionBySemanticKey` **复用它**。
 *
 * 取 6 小时是因为那 3 次投递两两相隔 2~5 小时：窗口太短会拦不住当天复用，
 * 太长则会让"今天已经送过"的动念一直占着候选位。6 小时能覆盖实测间隔，
 * 又不会跨到第二天。
 */
export const RITUAL_SETTLED_HOURS = 6;

/**
 * 判定一条动念是否应当收尾。
 *
 * @param {object} intention 动念（含 desired_change / created_at 等）
 * @param {object} opts
 *   nowMs                 当前时间
 *   createdAtMs           覆盖建立时间（测试用）
 *   resolvedStreak        该动念的"来源已消解"连续确认次数（由调用方重查来源后累计）
 *   blockStreak           同一指纹连续被出站门拦下的次数
 *   latestDeliveredAtMs   该动念最近一次**真实送达**的毫秒时间戳（无则 null）
 * @returns {{ retire: false|'expired'|'completed'|'suspended', reason: string }}
 */
export function judgeIntentionRetirement(intention = {}, {
  nowMs = Date.now(),
  createdAtMs = null,
  resolvedStreak = 0,
  blockStreak = 0,
  latestDeliveredAtMs = null,
} = {}) {
  // 第一层：知识寿命
  if (isIntentionExpired(intention, { nowMs, createdAtMs })) {
    const { type, reason } = classifyIntentionLifetime(intention || {});
    return { retire: 'expired', reason: `shelf_life_${type}:${reason}` };
  }
  // 第二层：来源已消解（要求**连续两次**确认，避免一次查询失败就误杀正当跟进）
  if (Number(resolvedStreak) >= 2) {
    return { retire: 'completed', reason: 'source_condition_resolved_twice' };
  }
  // 第三层：同内容反复过不了出站门
  if (Number(blockStreak) >= INTENTION_BLOCK_SUSPEND_AT) {
    return { retire: 'suspended', reason: `blocked_${Number(blockStreak)}x_same_fingerprint` };
  }
  // 第四层：每日仪式已经送出去了 → 完结
  //
  // 只对 recurring_ritual 生效（早安/晚安/低负担入口）。这类内容本身
  // 不该过期，但**一次投递就是一次完成**：旧动念完结后，同内容再来时
  // `findAgencyIntentionBySemanticKey` 查不到它（已终态），于是建一条新的，
  // 所以"明天还能发早安"不受影响，只是不会拿已经发过的那条再发一遍。
  const deliveredAt = Number(latestDeliveredAtMs);
  if (Number.isFinite(deliveredAt) && deliveredAt > 0) {
    const { type } = classifyIntentionLifetime(intention || {});
    if (type === INTENTION_LIFETIME.RECURRING_RITUAL) {
      const settledMs = RITUAL_SETTLED_HOURS * 3600e3;
      if (nowMs - deliveredAt >= settledMs) {
        return { retire: 'completed', reason: 'ritual_delivered_and_settled' };
      }
    }
  }
  return { retire: false, reason: 'still_valid' };
}

export function appendInitiativeReceipt(receipt, file = process.env.XIYU_INITIATIVE_LEDGER_PATH || path.resolve(process.cwd(), 'data/initiative-ledger.jsonl')) {
  const safe = { at: new Date().toISOString(), schemaVersion: 'initiative-receipt-v1', intentionId: compact(receipt?.decision?.id), primaryDrive: compact(receipt?.decision?.primaryDrive), domain: compact(receipt?.decision?.domain), action: compact(receipt?.decision?.action), objective: compact(receipt?.decision?.objective).slice(0, 300), whyNow: compact(receipt?.decision?.whyNow).slice(0, 300), status: compact(receipt?.status || 'unknown'), textSegments: Number(receipt?.textSegments || 0), imageSegments: Number(receipt?.imageSegments || 0), reason: compact(receipt?.reason).slice(0, 300) };
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.appendFileSync(file, `${JSON.stringify(safe)}\n`, 'utf8');
  return safe;
}
