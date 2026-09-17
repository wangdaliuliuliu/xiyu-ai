/**
 * AI 决策式照片规划。
 *
 * 这里不负责上传和发送，只判断是否适合发图，并产出安全清洗后的
 * imagePrompt / caption。程序侧仍负责冷却、限额、provider 可用性等硬门闩。
 */

import { extractStructuredInfo } from './ai.mjs';
import { getDb, listPhotoRequestAudits, shanghaiDayBounds } from './db.mjs';
import { log } from './logger.mjs';
import { getImageProviderCapabilities } from './providers/image.mjs';
import { getVisualIdentity, selectReferenceImage } from './visual_identity.mjs';
import { moonFactLine } from './utils/moon_phase.mjs';   // v1.21.5 PR-C 月相锚定
import { sunsetFactLine } from './utils/sun_times.mjs';  // v1.21.6 PR-C 晚霞窗口锚定
import { realityDateFacts } from './utils/reality_facts.mjs';   // v1.21.4 PR-W3 节气/节日历法事实

const DEFAULT_PLAN = Object.freeze({
  shouldSendPhoto: false,
  mode: 'text_only',
  trigger: 'none',
  photoType: 'other',
  realism: 'realistic_daily',
  imagePrompt: '',
  caption: '',
  delayImageMs: 0,
  delayCaptionMs: 900,
  maintainIdentity: true,
  reason: '',
});

/**
 * 单份画面方案（2026-09-15 由「三候选 + 本地挑选」改为「单方案」）。
 *
 * 为什么改（用户决定）：
 *   1. 成本——一次规划出三个完整候选，规划模型的输出 token 约为单方案的三倍；
 *      而预算刚调整为按真实用量计费，三候选没有必要。
 *   2. 可归因——去掉本地打分挑选后，"画面方向"完全由规划模型一次决定，
 *      出问题时只需看一个方案的输入输出，不再有"选错了"这一层。
 *
 * 字段按「自拍提示词九块结构」组织，每块只负责一件事（一个属性只有一个 owner），
 * 避免同一属性被两个字段重复描述而在生图时互相打架：
 *   ① 拍摄声明      固定模板（photo_sender 的 cameraAnchor），不由模型写
 *   ② 构图距离      framing
 *   ③ 人物真实感    固定模板（visual_identity），不由模型写
 *   ④ 瞬间动作      action
 *   ⑤ 表情          expression
 *   ⑥ 穿搭          wardrobe
 *   ⑦ 生活环境      environment（= 场景 + 光线 + 具体生活物件锚点）
 *   ⑧ 缺陷块        固定模板（realismTail），不由模型写
 *   ⑨ 负面约束      固定模板，放提示词最后
 * 模型另需给出两个"选择用的元字段"（不进入生图提示词）：
 *   sceneMoment / compositionFamily / timelineRelation / variationTags
 */
const DEFAULT_VISUAL_PLAN = Object.freeze({
  sceneMoment: '',
  framing: '',
  action: '',
  expression: '',
  wardrobe: '',
  environment: '',
  compositionFamily: '',
  timelineRelation: 'current',
  variationTags: [],
});

const PHOTO_TYPES = new Set([
  'casual_daily',
  'self_present',
  'current_activity',
  'place_share',
  'night',
  'comfort',
  'other',
]);

// 机位是照片提示词链路的权威路由信号。无脸机位不能因为 planner 的文字漂移
// 又回到人物/i2i 分支，否则桌面或风景会被角色参考图和人像构图污染。
export const NO_FACE_SHOTMODES = Object.freeze(new Set(['ACTIVITY_POV', 'SCENERY']));
const SELFIE_SHOTMODES = Object.freeze(new Set(['SELFIE', 'ENV_SELFIE']));

// 仅检查「正向」人物/自拍描述；合法的 "do NOT show her face" 等排除句先移除，
// 避免把已经正确的无脸提示词误判成冲突。
const ROUTE_NEGATIVE_CLAUSE_RE = /\b(?:no|without|not)\s+[a-z][a-z\s-]*?(?=[,.;]|$)/gi;
const NO_FACE_ROUTE_CONFLICT_RE = /\b(?:selfie|self[- ]portrait|front[- ]camera|portrait|woman|girl|(?<!first-)person|face|hair|eyes|skin|body|torso|clothing|outfit|wearing|chest[- ]?up|waist[- ]?up|full[- ]body|head[- ]to[- ]toe)\b|\bshe\s+(?:is|has|wears|holds|sits|stands|looks|reaches)\b/i;
// 生图模型会把“她举着/拿着手机自拍”解释成镜子自拍或第三人称拍摄，导致手机本体
// 出现在画面里。SELFIE 的 prompt 应描述前摄最终成像，而不是描述拍照动作。
const SELFIE_VISIBLE_DEVICE_RE = /\b(?:(?:phone|front camera)\s+held\s+(?:up\s+)?(?:in\s+front\s+of\s+her|at\s+(?:chest|face|eye|shoulder)(?:[- ]level)?)|front camera(?:\s+selfie)?\s+at\s+arm(?:'s|s)?[- ]length|(?:she\s+)?(?:is\s+)?hold(?:s|ing)\s+(?:her|a|the)\s+(?:smart)?phone|(?:one|her)\s+arm\s+(?:is\s+)?(?:partially\s+)?(?:visible\s+)?(?:extended|reaching)\s+(?:toward|towards)\s+(?:the\s+)?camera(?:\s+(?:while\s+)?holding\s+(?:her|a|the)\s+(?:smart)?phone)?|(?:looks?|glances?|turns?\s+her\s+head)\b[^,.;]{0,40}\b(?:at|toward|towards|from)\s+(?:the|her)\s+(?:smart)?phone|eyes?\s+on\s+(?:the\s+)?screen|mirror\s+selfie)\b/i;
const SELFIE_BOTH_HANDS_RE = /\b(?:(?:with|using)\s+both\s+hands|both\s+hands\s+(?:are\s+)?(?:holding|gripping|carrying|occupied|busy))\b/i;
const DIRECT_CAMERA_ATTENTION_RE = /\b(?:look(?:s|ing)?|glance(?:s|d|ing)?|gaze(?:s|d|ing)?|eyes?(?:\s+are)?(?:\s+fixed)?|attention)\b[^,.;]{0,48}\b(?:at|into|toward|towards|on)\s+(?:the\s+)?(?:front[- ](?:facing\s+)?camera|camera|lens)\b|\bdirect (?:eye contact|camera attention|gaze)\b/i;
const STANDARD_SELFIE_RE = /\b(?:standing|sitting|reclining|lying)\b[^.]{0,140}\b(?:look(?:s|ing)?|glance(?:s|d|ing)?|gaze(?:s|d|ing)?)\b[^,.;]{0,48}\b(?:at|into|toward|towards)\s+(?:the\s+)?(?:front[- ](?:facing\s+)?camera|camera|lens)\b|\b(?:gentle|warm) smile\b|\b(?:centered|centred|symmetrical|posed) (?:portrait|selfie|composition|framing)\b/i;
const THIRD_PERSON_SELFIE_RE = /\b(?:over (?:her )?shoulder|from behind|camera follows her|seen watching her|observer(?:'s)? view)\b/i;
const EXPLICIT_POSED_REQUEST_RE = /(?:认真|正经|正式|好好|端正|站好|拍清楚|看清楚|证件照).{0,8}(?:拍|照片|自拍)|(?:拍|照片|自拍).{0,8}(?:认真|正经|正式|好好|端正|清楚)/i;

const BLOCKED_CAPTION_RE = /作为\s*AI|当前情绪状态|情绪分数|11维|生成了?一张图片|根据系统判断|\[PHOTO\]|\[STICKER:photo\]|图片URL|图片地址/i;
const BLOCKED_PROMPT_RE = /\b(anime|illustration|poster|app icon|glamour shoot|nsfw|nude|sexual|minor|celebrity|loneliness|attachment)\b|11[-\s]*dimensional\s+emotion|二次元|插画|海报|头像|未成年|名人|情绪分数|当前情绪状态|11维/i;
const REQUIRED_PROMPT_BITS = [
  'realistic casual phone snapshot',
  'natural lighting',
  'everyday environment',
  'safe adult everyday content',
];

function envFlag(name, fallback = true) {
  const raw = process.env[name];
  if (raw == null || raw === '') return fallback;
  return !['0', 'false', 'no', 'off'].includes(String(raw).toLowerCase());
}

function numberEnv(name, fallback, min = 0) {
  // 空字符串和未设置都走 fallback，避免 PHOTO_DAILY_LIMIT_PER_COMPANION= 这种空配置
  // 把默认值 3 退化为 0（无限制）。
  const raw = process.env[name];
  if (raw == null || raw === '') return Math.max(min, fallback);
  const n = Number(raw);
  return Math.max(min, Number.isFinite(n) ? n : fallback);
}

function normalizeSqlDate(raw) {
  if (!raw) return null;
  const ts = new Date(String(raw).replace(' ', 'T') + (String(raw).includes('Z') ? '' : 'Z')).getTime();
  return Number.isFinite(ts) ? ts : null;
}

function messageTimestampMs(message) {
  const raw = message?.created_at ?? message?.createdAt ?? message?.timestamp ?? message?.ts;
  if (raw == null || raw === '') return null;
  if (typeof raw === 'number') return raw > 1e12 ? raw : raw * 1000;
  const text = String(raw);
  const ts = new Date(text.replace(' ', 'T') + (text.includes('Z') || /[+-]\d\d:\d\d$/.test(text) ? '' : 'Z')).getTime();
  return Number.isFinite(ts) ? ts : null;
}

/**
 * 照片只使用仍能代表“此刻”的近期对话。普通聊天和长期记忆不受影响。
 * 生产消息都有 created_at；无时间戳的 mock/旧调用方继续保留，避免兼容性断裂。
 */
export function selectFreshPhotoContext(recentMessages = [], {
  now = new Date(),
  maxAgeMinutes = numberEnv('PHOTO_CONTEXT_FRESH_MINUTES', 90, 10),
} = {}) {
  const nowMs = now instanceof Date ? now.getTime() : Number(now);
  const maxAgeMs = maxAgeMinutes * 60_000;
  let staleCount = 0;
  const messages = (Array.isArray(recentMessages) ? recentMessages : []).filter((message) => {
    const ts = messageTimestampMs(message);
    if (ts == null) return true;
    const age = nowMs - ts;
    const fresh = age >= -5 * 60_000 && age <= maxAgeMs;
    if (!fresh) staleCount += 1;
    return fresh;
  });
  return { messages, staleCount, maxAgeMinutes };
}

function captureIntentFor(userText = '') {
  return EXPLICIT_POSED_REQUEST_RE.test(String(userText || '')) ? 'posed' : 'lived';
}

function pickImageProviderKey(provider) {
  const name = String(provider || process.env.IMAGE_PROVIDER || 'zhipu').toLowerCase();
  const map = {
    zhipu: ['ZHIPU_API_KEY'],
    qwen: ['QWEN_API_KEY', 'DASHSCOPE_API_KEY'],
    doubao: ['DOUBAO_API_KEY'],
    wenxin: ['WENXIN_API_KEY'],
    openai: ['OPENAI_API_KEY'],
    // v1.10.30: 补 openrouter — v1.10.19 加了 image provider 但没同步这里，
    // 导致 isImageProviderConfigured 返 false，photo gate 拒绝所有照片请求。
    openrouter: ['OPENROUTER_API_KEY'],
    '302ai': ['AI302_API_KEY'],
    // iotwq Grok 图片中转复用 XAI_API_KEY，但只用于 IMAGE_PROVIDER=iotwq 生图。
    iotwq: ['XAI_API_KEY', 'IOTWQ_API_KEY'],
  };
  return { provider: name, keys: map[name] || [] };
}

export function isImageProviderConfigured(provider = process.env.IMAGE_PROVIDER || 'zhipu') {
  const { keys } = pickImageProviderKey(provider);
  return keys.some(k => !!process.env[k]);
}

export function getPhotoLimits() {
  return {
    // 0 explicitly disables the user-request cooldown; proactive cadence is
    // controlled separately by PHOTO_PROACTIVE_MIN_HOURS.
    requestCooldownMinutes: numberEnv('PHOTO_REQUEST_COOLDOWN_MINUTES', 10, 0),
    dailyLimitPerCompanion: Math.floor(numberEnv('PHOTO_DAILY_LIMIT_PER_COMPANION', 3, 0)),
    proactiveMinHours: numberEnv('PHOTO_PROACTIVE_MIN_HOURS', 36, 1),
    requestEnabled: envFlag('PHOTO_REQUEST_ENABLED', true),
    sendEnabled: envFlag('PHOTO_SEND_ENABLED', true),
    aiDecisionEnabled: envFlag('PHOTO_AI_DECISION_ENABLED', true),
    realisticMode: envFlag('PHOTO_REALISTIC_MODE', true),
  };
}

export function getPhotoCooldownState(companion, { source = 'request' } = {}) {
  const limits = getPhotoLimits();
  const lastTs = normalizeSqlDate(companion?.last_photo_at);
  if (!lastTs) return { cooling: false, remainingMs: 0, lastPhotoAt: null };
  const thresholdMs = (source === 'proactive' ? limits.proactiveMinHours * 60 : limits.requestCooldownMinutes) * 60_000;
  const remainingMs = thresholdMs - (Date.now() - lastTs);
  return { cooling: remainingMs > 0, remainingMs: Math.max(0, remainingMs), lastPhotoAt: companion?.last_photo_at || null };
}

export function countTodayPhotoMessages(companion) {
  const toUser = companion?.wechat_user_id;
  if (!toUser) return 0;
  try {
    const { startSql, endSql } = shanghaiDayBounds();
    return getDb().prepare(`
      SELECT COUNT(*) AS n
      FROM wechat_messages
      WHERE direction = 'out'
        AND to_user = ?
        AND msg_type = 'image'
        AND content LIKE '照片：%'
        AND created_at >= ?
        AND created_at < ?
    `).get(toUser, startSql, endSql)?.n ?? 0;
  } catch (e) {
    log('warn', `[PhotoPlanner] daily count failed: ${e.message}`);
    return 0;
  }
}

export function getPhotoGateState({
  companion,
  source = 'request',
  trigger = source === 'proactive' ? 'proactive' : 'user_request',
  imageProviderAvailable = isImageProviderConfigured(),
} = {}) {
  const limits = getPhotoLimits();
  const cooldown = getPhotoCooldownState(companion, { source });
  const todayCount = countTodayPhotoMessages(companion);
  const reasons = [];
  if (!limits.sendEnabled) reasons.push('PHOTO_SEND_ENABLED disabled');
  if (trigger === 'user_request' && !limits.requestEnabled) reasons.push('PHOTO_REQUEST_ENABLED disabled');
  if (!limits.aiDecisionEnabled) reasons.push('PHOTO_AI_DECISION_ENABLED disabled');
  if (!limits.realisticMode) reasons.push('PHOTO_REALISTIC_MODE disabled');
  if (!imageProviderAvailable) reasons.push('image provider unavailable');
  if (cooldown.cooling) reasons.push('cooldown');
  if (limits.dailyLimitPerCompanion > 0 && todayCount >= limits.dailyLimitPerCompanion) reasons.push('daily limit');

  return {
    allowed: reasons.length === 0,
    reasons,
    trigger,
    source,
    imageProviderAvailable,
    cooldown,
    todayCount,
    limits,
  };
}

function safeText(text, maxLen) {
  return String(text || '')
    .replace(/[\u0000-\u001f]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, maxLen);
}

function clampEmotionNumber(value, fallback = 0) {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(0, Math.min(100, n));
}

export function buildEmotionPhotoContext(emotionState = null) {
  if (!emotionState || typeof emotionState !== 'object') {
    return {
      toneHint: '自然、轻松，不额外放大情绪',
      visualHint: '普通生活场景，像随手分享当下',
      captionHint: '短句、日常、不过度解释',
      sendBias: 'neutral',
    };
  }

  const affection = clampEmotionNumber(emotionState.affection);
  const trust = clampEmotionNumber(emotionState.trust, 50);
  const dependency = clampEmotionNumber(emotionState.dependency, 30);
  const possessiveness = clampEmotionNumber(emotionState.possessiveness, 20);
  const security = clampEmotionNumber(emotionState.security, 50);
  const energy = clampEmotionNumber(emotionState.energy, 60);
  const patience = clampEmotionNumber(emotionState.patience, 60);
  const excitement = clampEmotionNumber(emotionState.excitement, 30);
  const annoyance = clampEmotionNumber(emotionState.annoyance);
  const gratitude = clampEmotionNumber(emotionState.gratitude, 40);
  const mood = String(emotionState.mood || 'neutral').toLowerCase();

  const tone = [];
  const visual = [];
  const caption = [];
  let sendBias = 'neutral';

  if (['angry', 'cold'].includes(mood) || annoyance >= 65 || security <= 25) {
    tone.push('克制一点，不要过分亲昵');
    visual.push('画面保持距离感，选择安静、整洁的日常物件或半身以外场景');
    caption.push('语气短一些，避免撒娇和强烈情绪词');
    sendBias = 'lower';
  } else if (['tired', 'wronged'].includes(mood) || energy <= 35 || patience <= 30) {
    tone.push('柔和、安静，像疲惫时顺手分享');
    visual.push('低干扰的生活角落，光线柔和，动作自然');
    caption.push('少说解释，多用轻声短句');
    sendBias = 'neutral';
  } else if (['happy', 'shy'].includes(mood) || excitement >= 65 || gratitude >= 70) {
    tone.push('轻快、温柔，有一点亲近感');
    visual.push('明亮一点的日常瞬间，可以有桌面、窗边、杯子或正在做的事');
    caption.push('像刚好想到对方时发出的短句');
    sendBias = 'higher';
  }

  if ((affection >= 70 && trust >= 65) || dependency >= 70) {
    tone.push('更亲近，但不要夸张表白');
    visual.push('可以更贴近当下生活细节，像只给熟人看的随手照');
    caption.push('自然带一点只给你看的感觉');
    if (sendBias !== 'lower') sendBias = 'higher';
  }
  if (possessiveness >= 70 && sendBias !== 'lower') {
    tone.push('带一点小占有欲，但保持轻松');
    caption.push('不要变成命令或质问');
  }

  return {
    toneHint: safeText(tone.join('；') || '自然、轻松，不额外放大情绪', 160),
    visualHint: safeText(visual.join('；') || '普通生活场景，像随手分享当下', 180),
    captionHint: safeText(caption.join('；') || '短句、日常、不过度解释', 160),
    sendBias,
  };
}

export function sanitizePhotoCaption(text) {
  const cleaned = safeText(text, 60)
    .replace(/[\[【].*?[\]】]/g, '')
    .replace(/\|\|/g, '')
    .replace(BLOCKED_CAPTION_RE, '')
    .trim();
  if (!cleaned || BLOCKED_CAPTION_RE.test(cleaned)) return '';
  return cleaned.slice(0, 35);
}

function stripPrivateDetails(text) {
  return String(text || '')
    .replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, '')
    .replace(/\+?\d[\d\s-]{8,}\d/g, '')
    .replace(/(?:身份证|手机号|电话|住址|地址)[:：]?\s*\S+/g, '');
}

export function sanitizePhotoPrompt(text, maxLength = 2200) {
  // v1.20.1: 900→2200。i2i 的 referenceNote 就占 ~400 字，900 上限把尾部的
  // REALISM_PERSON 反磨皮词全截掉了——生产 i2i 路径质感词从没真正生效，
  // 这是"照片假"的隐藏根因（A/B 实验实测）。gemini/gpt-image 的真实 prompt
  // 上限远大于此，2200 可容纳 identity+scene+refNote+完整 realism tail。
  const limit = Math.max(200, Number(maxLength) || 2200);
  let prompt = stripPrivateDetails(safeText(text, limit));
  prompt = prompt.replace(/[\r\n]+/g, ' ').replace(/\s+/g, ' ').trim();
  if (!prompt) return '';

  // v1.10.36: 先剥掉所有 "no XXX / without XXX / not XXX / -XXX" 这种 negative 排除
  // 短语 — 它们是 LLM 在告诉模型"不要 minor/teen/professional..."，本来是安全
  // 措施，但我们的 BLOCKED_PROMPT_RE 用 \bword\b 匹配会把"no minor"里的 minor 也
  // 当成命中误拒。stripped 只用于做安全检查，原 prompt 仍保留（模型自己能理解
  // negative 句式）。
  const stripped = prompt
    .replace(/\bno\s+[a-z][a-z\s-]*?(?=[,.;]|$)/gi, '')
    .replace(/\bwithout\s+[a-z][a-z\s-]*?(?=[,.;]|$)/gi, '')
    .replace(/\bnot\s+[a-z][a-z\s-]*?(?=[,.;]|$)/gi, '');

  if (BLOCKED_PROMPT_RE.test(stripped)) return '';

  const lower = prompt.toLowerCase();
  const missing = REQUIRED_PROMPT_BITS.filter(bit => !lower.includes(bit.toLowerCase()));
  if (missing.length) prompt = `${prompt}, ${missing.join(', ')}`;

  // 再用 stripped 重新过滤（防 missing 追加引入了敏感词）
  const stripped2 = prompt
    .replace(/\bno\s+[a-z][a-z\s-]*?(?=[,.;]|$)/gi, '')
    .replace(/\bwithout\s+[a-z][a-z\s-]*?(?=[,.;]|$)/gi, '')
    .replace(/\bnot\s+[a-z][a-z\s-]*?(?=[,.;]|$)/gi, '');
  if (BLOCKED_PROMPT_RE.test(stripped2)) return '';
  return prompt.slice(0, limit);
}

function routeContextText({ userText = '', currentScene = '', proactiveScene = '' } = {}) {
  return safeText([
    userText ? `user request: ${userText}` : '',
    currentScene ? `current scene: ${currentScene}` : '',
    proactiveScene ? `planned scene: ${proactiveScene}` : '',
  ].filter(Boolean).join('; '), 420);
}

function buildNoFaceRouteFallback({ shotMode = '', userText = '', currentScene = '', proactiveScene = '' } = {}) {
  const context = routeContextText({ userText, currentScene, proactiveScene }) || 'the requested object or scene';
  const activityOnly = shotMode === 'ACTIVITY_POV';
  return sanitizePhotoPrompt([
    `first-person POV smartphone photo responding directly to this request: "${context}"`,
    'the requested object or scene is the clear main subject and fills one coherent frame',
    'ordinary everyday setting with context-appropriate time and natural lighting',
    activityOnly
      ? 'the entire frame is the tabletop or requested object, with no hands, sleeves, lap, legs or torso visible'
      : 'at most one natural hand or sleeve at the extreme edge',
    'do NOT show a person, face, body, clothing, portrait or selfie composition',
    'single unedited phone photo',
  ].join(', '));
}

function removeVisibleSelfieDeviceCues(text) {
  return String(text || '')
    .replace(/\bphone\s+held\s+up\s+in\s+front\s+of\s+her\b/gi, 'direct front-camera viewpoint')
    .replace(/\b(?:she\s+)?(?:is\s+)?holding\s+(?:her|a|the)\s+(?:smart)?phone\s+up\s+for\s+a\s+selfie\b/gi, 'direct front-camera selfie')
    .replace(/\b(?:she\s+)?(?:is\s+)?holding\s+(?:her|a|the)\s+(?:smart)?phone\b(?:\s+(?:up|in front of her|at arm(?:'s|s)? length))?/gi, 'direct front-camera viewpoint')
    .replace(/\bphone\s+held\s+(?:up\s+)?at\s+(chest|face|eye|shoulder)(?:[- ]level)?\b/gi, '$1-level front-camera viewpoint')
    .replace(/\bfront camera\s+held\s+at\s+(chest|face|eye|shoulder)(?:[- ]level)?\b/gi, '$1-level selfie viewpoint')
    .replace(/\bfront camera(?:\s+selfie)?\s+at\s+arm(?:'s|s)?[- ]length\b/gi, 'arm-length selfie viewpoint')
    .replace(/\b(?:she\s+)?hold(?:s|ing)\s+(?:her|a|the)\s+(?:smart)?phone(?:\s+up)?(?:\s+for\s+(?:a\s+)?(?:quick\s+)?selfie)?\b/gi, 'direct front-camera selfie')
    .replace(/\b((?:looks?|glances?)\b[^,.;]{0,40})\bat\s+(?:the|her)\s+(?:smart)?phone\b/gi, '$1toward the lens')
    .replace(/\b((?:looks?|glances?)\s+up)\s+from\s+(?:the|her)\s+(?:smart)?phone\b/gi, '$1 mid-action')
    .replace(/\b((?:turns?\s+her\s+head)\b[^,.;]{0,40})\b(?:at|toward|towards)\s+(?:the|her)\s+(?:smart)?phone\b/gi, '$1toward the lens')
    .replace(/\beyes?\s+on\s+(?:the\s+)?screen\b/gi, 'attention near the lens')
    .replace(/\b(?:one|her)\s+arm\s+(?:is\s+)?(?:partially\s+)?(?:visible\s+)?(?:extended|reaching)\s+(?:toward|towards)\s+(?:the\s+)?camera(?:\s+(?:while\s+)?holding\s+(?:her|a|the)\s+(?:smart)?phone)?\b/gi, 'natural near-field selfie perspective')
    .replace(/\bmirror\s+selfie\b/gi, 'direct front-camera selfie')
    .replace(/\s+([,.;])/g, '$1')
    .replace(/(?:,\s*){2,}/g, ', ')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

function removeImpossibleSelfieHandCues(text) {
  return String(text || '')
    // 只删除“双手同时被占用”这个物理冲突；不替 planner 规定哪只手、
    // 不强行让手入镜，保留图片模型对自然构图的自由度。
    .replace(/\b(?:with|using)\s+both\s+hands\b/gi, '')
    .replace(/\bboth\s+hands\s+(?:are\s+)?(?=(?:holding|gripping|carrying|occupied|busy)\b)/gi, '')
    .replace(/\s+([,.;])/g, '$1')
    .replace(/(?:,\s*){2,}/g, ', ')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

/**
 * 把 planner 输出接入机位硬路由。
 *
 * 正常情况下直接沿用 planner prompt；只有 ACTIVITY_POV/SCENERY 产出人物或自拍
 * 语义时，才在本地用用户原始需求和场景上下文重建一次，不重新调用大模型。
 */
export function normalizePhotoPromptForShot({
  shotMode = '',
  imagePrompt = '',
  userText = '',
  currentScene = '',
  proactiveScene = '',
} = {}) {
  const candidate = sanitizePhotoPrompt(imagePrompt);
  if (!candidate) return { prompt: '', corrected: false, reason: 'empty_prompt' };
  if (SELFIE_SHOTMODES.has(shotMode)) {
    const deviceConflict = candidate.match(SELFIE_VISIBLE_DEVICE_RE)?.[0] || '';
    const handConflict = candidate.match(SELFIE_BOTH_HANDS_RE)?.[0] || '';
    const conflict = deviceConflict || handConflict;
    if (!conflict) return { prompt: candidate, corrected: false, reason: 'route_ok' };
    const cleaned = sanitizePhotoPrompt(removeImpossibleSelfieHandCues(removeVisibleSelfieDeviceCues(candidate)));
    return {
      prompt: cleaned || candidate,
      corrected: Boolean(cleaned),
      reason: cleaned
        ? (deviceConflict ? 'selfie_viewpoint_conflict' : 'selfie_physical_conflict')
        : 'selfie_conflict_cleanup_failed',
      conflictSignal: safeText(conflict, 80),
    };
  }
  if (!NO_FACE_SHOTMODES.has(shotMode)) {
    return { prompt: candidate, corrected: false, reason: 'route_ok' };
  }

  const positive = candidate.replace(ROUTE_NEGATIVE_CLAUSE_RE, ' ');
  const conflict = positive.match(NO_FACE_ROUTE_CONFLICT_RE)?.[0] || '';
  if (!conflict) return { prompt: candidate, corrected: false, reason: 'route_ok' };

  const fallback = buildNoFaceRouteFallback({ shotMode, userText, currentScene, proactiveScene });
  return {
    prompt: fallback || candidate,
    corrected: Boolean(fallback),
    reason: fallback ? 'shot_mode_conflict' : 'shot_mode_conflict_fallback_failed',
    conflictSignal: safeText(conflict, 40),
  };
}

function extractJson(text) {
  if (!text || typeof text !== 'string') return null;
  try { return JSON.parse(text); } catch {}
  const m = text.match(/\{[\s\S]*\}/);
  if (!m) return null;
  try { return JSON.parse(m[0]); } catch {}
  return null;
}

function getVisualContext(companion, imageProviderCapabilities = getImageProviderCapabilities()) {
  if (!companion?.id) {
    return {
      enabled: envFlag('PHOTO_VISUAL_IDENTITY_ENABLED', true),
      exists: false,
      hasReferenceImage: false,
      providerCapabilities: imageProviderCapabilities,
    };
  }
  try {
    const identity = getVisualIdentity(companion.id);
    const referenceImagePath = selectReferenceImage(companion.id);
    return {
      enabled: envFlag('PHOTO_VISUAL_IDENTITY_ENABLED', true),
      exists: Boolean(identity),
      hasReferenceImage: Boolean(referenceImagePath),
      providerCapabilities: imageProviderCapabilities,
      fallback: imageProviderCapabilities?.referenceImage ? 'reference_image' : 'identity_text_prompt',
    };
  } catch (e) {
    log('warn', `[PhotoPlanner] visual context failed companion=${companion.id}: ${e.message}`);
    return {
      enabled: envFlag('PHOTO_VISUAL_IDENTITY_ENABLED', true),
      exists: false,
      hasReferenceImage: false,
      providerCapabilities: imageProviderCapabilities,
    };
  }
}


/**
 * 规范化模型给出的单份画面方案（九块结构）。
 *
 * 与旧 selectVisualCandidate 的区别：不再从多个候选里挑，而是把**这一份**
 * 方案的各块做确定性清洗：
 *   - 每块独立取词、独立截断（不再整条 1400 字一刀，避免某块过长挤掉别人）
 *   - framing 里的"居中/对称"在 LIVED 意图下改写为偏轴（保留旧行为）
 *   - 自拍机位里不保留"越过肩膀"等外部视角措辞
 *   - 块内空白折叠
 * 返回 null 表示方案不可用（调用方据此判 imagePrompt rejected）。
 */
export function normalizeVisualPlan(raw = {}, { captureIntent = 'lived', shotMode = 'SELFIE' } = {}) {
  if (!raw || typeof raw !== 'object') return null;
  const pick = (value, max) => safeText(value, max).replace(/\s+/g, ' ').trim();

  let framing = pick(raw.framing, 300);
  // LIVED 下把"居中/对称"改成自然偏轴——与旧候选逻辑一致，避免每张都是证件照式正对。
  if (captureIntent === 'lived' && /\b(?:centered|centred|symmetrical)\b/i.test(framing)) {
    framing = framing
      .replace(/\bfront-facing\b/gi, 'slightly off-axis')
      .replace(/\b(?:her (?:face|figure|upper body) )?(?:centered|centred)(?: but not rigid)?\b/gi,
        'a loose asymmetric placement that lets the active surroundings share the frame')
      .replace(/\bsymmetrical\b/gi, 'naturally asymmetric');
  }
  // 自拍机位里不能再出现"越过肩膀/从背后"这类外部视角措辞，否则生图模型会画成
  // 第三人称或镜子自拍。注意 over-the-shoulder 中间是 "the"（不是 her），
  // "over her shoulder" 是另一种写法——两者都要覆盖。
  if (SELFIE_SHOTMODES.has(shotMode)) {
    framing = framing
      .replace(/\bover[\s-]+(?:the|her)[\s-]+shoulder\b/gi, 'off-axis')
      .replace(/\bfrom[\s-]+behind\b/gi, 'from a close off-axis angle');
  }

  const plan = {
    sceneMoment: pick(raw.sceneMoment, 400),
    framing,
    action: pick(raw.action, 300),
    expression: pick(raw.expression, 160),
    wardrobe: pick(raw.wardrobe, 300),
    environment: pick(raw.environment, 400),
    compositionFamily: pick(raw.compositionFamily, 80),
    timelineRelation: (() => {
      const v = String(raw.timelineRelation || 'current').toLowerCase();
      return ['current', 'advanced', 'paused', 'invented'].includes(v) ? v : 'current';
    })(),
    variationTags: Array.isArray(raw.variationTags)
      ? raw.variationTags.slice(0, 8).map((t) => pick(t, 40)).filter(Boolean)
      : [],
  };
  // 场景瞬间/动作是画面主体，取景/环境是画面骨架：各自至少有一个才算出得了图。
  if (!plan.sceneMoment && !plan.action) return null;
  if (!plan.framing && !plan.environment) return null;
  return plan;
}

/**
 * 把单份方案按「自拍提示词九块结构」拼成给生图模型的一段文本。
 *
 * 这里只输出**模型负责的 6 块**（场景瞬间/构图/动作/表情/穿搭/环境）；
 * 其余由固定模板承担，保证"一个属性只有一个 owner"，不会两处描述互相打架：
 *   拍摄声明 + 人物真实感 + 缺陷块 → photo_sender（cameraAnchor / identityPrompt / realismTail）
 *   参考图锚定句 + 负面约束        → photo_sender（referenceFirst / 尾部约束）
 */
export function visualPlanPrompt(raw = {}, { captureIntent = 'lived', shotMode = 'SELFIE' } = {}) {
  const plan = normalizeVisualPlan(raw, { captureIntent, shotMode });
  if (!plan) return '';
  const blocks = [
    plan.sceneMoment,
    plan.framing,
    plan.action,
    plan.expression,
    plan.wardrobe,
    plan.environment,
  ].filter(Boolean);
  return sanitizePhotoPrompt([...new Set(blocks)].join(', '), 1600);
}

function normalizePlan(raw, {
  trigger,
  gate,
  shotMode = '',
  sceneText = '',
  userText = '',
  currentScene = '',
  proactiveScene = '',
  captureIntent = 'lived',
  recentPhotoContext = '',
  freshContextText = '',
  seasonalClothing = '',
}) {
  const plan = { ...DEFAULT_PLAN, trigger, reason: 'normalized' };
  if (!raw || typeof raw !== 'object') return { ...plan, reason: 'invalid planner json' };
  const should = raw.shouldSendPhoto === true && raw.mode !== 'text_only';
  if (!should) {
    return {
      ...plan,
      shouldSendPhoto: false,
      mode: 'text_only',
      // v1.21.5: 保留人设婉拒句（拒绝时也给一句自然的"现在拍不了/改天拍"，
      // 替代 bot.mjs 罐头拖延池）+ 改期可行性（夜里拍不出≠永远拍不出）
      declineCaption: sanitizePhotoCaption(raw.caption) || '',
      canRetakeLater: raw.canRetakeLater === true,
      reason: safeText(raw.reason || 'planner declined', 160),
    };
  }

  const caption = sanitizePhotoCaption(raw.caption);
  // 2026-09-15：三候选 + 本地挑选 → 单份方案（用户决定，为省 token 并去掉一层出错点）。
  // 人物机位用九块结构拼装；无脸机位（SCENERY/ACTIVITY_POV）仍走模型给的整段 imagePrompt。
  const usesVisualPlan = SELFIE_SHOTMODES.has(shotMode) || shotMode === 'CANDID';
  const visualPlan = usesVisualPlan
    ? normalizeVisualPlan(raw.visualPlan || raw, { captureIntent, shotMode })
    : null;
  const planPrompt = usesVisualPlan ? visualPlanPrompt(visualPlan || {}, { captureIntent, shotMode }) : '';
  const routedPrompt = normalizePhotoPromptForShot({
    shotMode,
    imagePrompt: planPrompt || raw.imagePrompt,
    userText,
    currentScene,
    proactiveScene,
  });
  const imagePrompt = routedPrompt.prompt;
  if (!caption) return { ...plan, reason: 'caption rejected' };
  if (!imagePrompt) return { ...plan, reason: 'imagePrompt rejected' };

  const delayImageMs = Math.min(Math.max(Number(raw.delayImageMs) || 900, 500), 4500);
  const delayCaptionMs = Math.min(Math.max(Number(raw.delayCaptionMs) || 900, 300), 3000);
  return {
    shouldSendPhoto: true,
    mode: 'send_photo',
    trigger,
    photoType: PHOTO_TYPES.has(raw.photoType) ? raw.photoType : 'other',
    realism: 'realistic_daily',
    imagePrompt,
    caption,
    delayImageMs,
    delayCaptionMs,
    maintainIdentity: raw.maintainIdentity !== false,
    routeCorrected: routedPrompt.corrected,
    routeCorrectionReason: routedPrompt.corrected ? routedPrompt.reason : '',
    captureIntent,
    // 2026-09-15：由 selectedVisualCandidate（三候选结果）改为 visualPlan（单份方案）。
    // 保留 compositionFamily / timelineRelation / variationTags —— 它们是**防止
    // 与最近几张机械重复**的依据，也是出问题时唯一可回看的画面元信息。
    visualPlan: visualPlan ? {
      compositionFamily: visualPlan.compositionFamily,
      timelineRelation: visualPlan.timelineRelation,
      variationTags: visualPlan.variationTags,
      // 逐块留存，便于核对"到底哪一块写了什么"（该字段不进入生图提示词）
      blocks: {
        sceneMoment: visualPlan.sceneMoment,
        framing: visualPlan.framing,
        action: visualPlan.action,
        expression: visualPlan.expression,
        wardrobe: visualPlan.wardrobe,
        environment: visualPlan.environment,
      },
    } : null,
    // v1.21.6 hotfix: shotMode/aspect 必须挂到 plan 上——调用方（proactive/bot）读
    // plan.shotMode / plan.aspect 喂 sendCompanionPhoto。d22bf73(v1.21.2) 把
    // buildPlannerPrompt 改成返回 {prompt,shotMode} 却没在此落库，导致比例路由是死代码。
    shotMode: shotMode || '',
    aspect: aspectForShot(shotMode, sceneText),
    reason: safeText(raw.reason || 'planner approved', 160),
    gate,
  };
}

// v1.10.21: 把当前上海小时映射成「光线 + 合理场景」，让 imagePrompt 别再凌晨画奶茶店白天。
function dayPartHint(h) {
  if (h < 5)  return { id: 'late_night', label: '深夜', light: 'the low available light actually present in the room, dark surroundings, ordinary front-camera low-light exposure', scenes: 'in bed, pillow view, pajamas, dim bedroom, brushing teeth' };
  if (h < 9)  return { id: 'early_morning', label: '清晨', light: 'ordinary early-morning ambient light as it naturally reaches the scene, phone auto-exposure', scenes: 'just-woke-up bed, kitchen making breakfast, brushing hair, window with morning sky' };
  if (h < 12) return { id: 'morning', label: '上午', light: 'ordinary available morning daylight, natural phone auto-exposure', scenes: 'desk study, library, classroom, cafe, on the way outside' };
  if (h < 14) return { id: 'noon', label: '中午', light: 'ordinary available midday light with natural phone dynamic range', scenes: 'lunch table, cafeteria, outdoor walk' };
  if (h < 17) return { id: 'afternoon', label: '下午', light: 'available afternoon ambient light as it actually falls in the current scene', scenes: 'cafe with notebook, window, park bench, study desk' };
  if (h < 19) return { id: 'dusk', label: '傍晚', light: 'available dusk light with natural phone auto-exposure as daylight fades and practical lights appear', scenes: 'seaside boardwalk, riverside walk, walking home, balcony with the evening sky, city street as the lights come on, sky over the sea, palm-lined promenade' };
  if (h < 22) return { id: 'evening', label: '晚上', light: 'the existing indoor lamps, screens or street lighting, with ordinary mixed color temperature and phone auto-exposure', scenes: 'sofa with tea, study desk lamp, watching show, late dinner' };
  return         { id: 'night', label: '夜晚', light: 'the low available nighttime light, dark surroundings, scene-appropriate front-camera softness and noise', scenes: 'in bed, pajamas, pillow, dim bedroom' };
}

// v1.10.21: 把人设外观打平成英文友好的 compact 描述（不暴露具体年龄数字，防 OpenAI 安全过滤）
function compactAppearance(c) {
  if (!c) return 'unknown';
  const parts = [];
  if (c.role_title) parts.push(`role=${c.role_title}`);
  if (c.hair_color || c.hair_style) parts.push(`hair=${[c.hair_color, c.hair_style].filter(Boolean).join('/')}`);
  if (c.eye_color) parts.push(`eyes=${c.eye_color}`);
  if (c.body_type) parts.push(`body=${c.body_type}`);
  if (c.height) parts.push(`height=${c.height}cm`);
  if (c.clothing_style) parts.push(`style=${c.clothing_style}`);
  try {
    const tags = JSON.parse(c.personality_tags || '[]');
    if (Array.isArray(tags) && tags.length) parts.push(`personality=${tags.slice(0, 4).join('/')}`);
  } catch {}
  return parts.join(', ') || 'unknown';
}

// v1.10.34/v1.23.0: 当前情绪 → 英文状态/氛围词。
// 不再把常见情绪直接钉成同一种面部表情；由 planner 结合上下文把情绪画面化。
function moodToFacialCue(mood) {
  const m = String(mood || '').toLowerCase();
  if (/开心|happy|joy|excited|兴奋/.test(m)) return 'warm buoyant mood, lively attention, emotionally open presence';
  if (/害羞|shy|bashful|羞涩/.test(m)) return 'shy self-conscious mood, softened attention, quietly warm presence';
  if (/温柔|gentle|calm|平静/.test(m)) return 'calm affectionate mood, unhurried presence, gentle attention';
  if (/疲惫|tired|累/.test(m)) return 'low-energy sleepy mood, relaxed pace, softened attention';
  if (/思念|想念|miss|melancholy/.test(m)) return 'quietly missing someone, inward but warm mood, emotionally present';
  if (/sad|难过|低落/.test(m)) return 'low reflective mood, subdued presence, emotionally honest but natural';
  if (/撒娇|pout|coy/.test(m)) return 'playfully teasing mood, lightly engaged attention, warm presence';
  if (/恼|生气|angry/.test(m)) return 'mildly annoyed mood, guarded attention, still emotionally connected';
  return 'natural everyday mood, genuine unforced presence, responsive to the current moment';
}

// v1.10.34: clothing_style → 英文具体着装关键词
function clothingStyleToEnglish(style) {
  const s = String(style || '').toLowerCase();
  // v1.22.0: 只保留宽泛的服装风格，避免“甜美”每次被展开成同一件开衫。
  if (/甜美|sweet|cute|可爱/.test(s)) return 'sweet casual everyday wardrobe, naturally varied to fit the current setting, comfortable and believable';
  if (/清新|elegant|fresh/.test(s)) return 'fresh casual everyday wardrobe, naturally varied to fit the current setting, clean and believable';
  if (/酷|cool|street/.test(s)) return 'casual streetwear style, naturally varied to fit the current setting, comfortable and believable';
  if (/性感|sexy|mature/.test(s)) return 'tasteful casual wardrobe, naturally varied to fit the current setting, modest and believable';
  if (/学院|preppy|学生/.test(s)) return 'casual preppy wardrobe, naturally varied to fit the current setting, fresh and believable';
  return 'casual everyday wardrobe, naturally varied to fit the current setting, comfortable and believable';
}

// 只提供季节级穿衣基线，不冒充实时天气。使用上海时区的日期，
// 并把 9 月初单独视为偏轻薄的夏秋过渡，避免“甜美”被默认翻译成厚毛衣。
export function seasonalClothingHint(now = new Date()) {
  const shanghai = new Date(new Date(now).getTime() + 8 * 60 * 60 * 1000);
  const month = shanghai.getUTCMonth() + 1;
  const day = shanghai.getUTCDate();
  if (month === 12 || month <= 2) {
    return 'winter seasonal baseline (not real-time weather): naturally warm everyday layers appropriate to the location and activity';
  }
  if (month <= 5) {
    return 'spring seasonal baseline (not real-time weather): light, adaptable everyday layers appropriate to the location and activity';
  }
  if (month <= 8) {
    return 'summer seasonal baseline (not real-time weather): lightweight breathable everyday clothing appropriate to the location and activity';
  }
  if (month === 9 && day <= 15) {
    return 'early-autumn warm transition baseline (not real-time weather): generally lightweight breathable clothing, with only light layering when the setting naturally calls for it';
  }
  if (month <= 10) {
    return 'autumn transitional baseline (not real-time weather): light practical layers appropriate to the location and activity';
  }
  return 'late-autumn seasonal baseline (not real-time weather): moderate practical layering appropriate to the location and activity';
}

// v1.22.0: 近期照片只作为“反重复”参考，不把上一张照片当作身份模板。
// 使用已有审计记录做轻量、确定性的特征摘要，不增加任何大模型调用。
export function extractRecentPhotoFeatures(row = {}) {
  const text = String(row.final_prompt || '').toLowerCase();
  const features = [];
  let selected = null;
  try {
    const plan = typeof row.plan_json === 'string' ? JSON.parse(row.plan_json) : row.plan_json;
    // 新结构优先；旧记录回退到 selectedVisualCandidate（见下方 attention 取值）
    selected = plan?.visualPlan || plan?.selectedVisualCandidate || null;
  } catch {
    selected = null;
  }
  const shot = String(row.shot_mode || '').trim();
  if (shot) features.push(shot);
  if (/mirror selfie|bathroom mirror/.test(text)) features.push('mirror framing');
  else if (/phone front camera|front-camera|phone selfie/.test(text)) features.push('phone selfie');
  if (/off-center|slightly imperfect framing|cropped|edge of the frame/.test(text)) features.push('imperfect framing');
  // 2026-09-15：读新结构 visualPlan（单方案）；同时兼容历史审计记录里的旧结构
  // selectedVisualCandidate，否则改动前的照片会突然"不被算作重复"，反重复判断退化。
  const attention = String(selected?.attentionState || selected?.blocks?.action || '').toLowerCase();
  const composition = String(selected?.compositionFamily || '').toLowerCase();
  const variationTags = Array.isArray(selected?.variationTags)
    ? selected.variationTags.map((tag) => safeText(tag, 40).toLowerCase()).filter(Boolean)
    : [];
  if (/profile|looking away|gazing away|head turned|tilted head/.test(text) || /off-camera|split|activity|side/.test(attention)) features.push('non-frontal gaze');
  else if (DIRECT_CAMERA_ATTENTION_RE.test(`${text} ${attention}`) || /direct eye contact|face clearly in focus/.test(text)) features.push('front-facing gaze');
  if (composition) features.push(`composition:${composition}`);
  for (const tag of variationTags.slice(0, 4)) features.push(`visual:${tag}`);
  if (/smile|smiling|grin|cheerful/.test(text)) features.push('smiling expression');
  else if (/neutral|thoughtful|pensive|relaxed expression/.test(text)) features.push('quieter expression');
  for (const place of ['bedroom', 'living room', 'sofa', 'desk', 'cafe', 'kitchen', 'street', 'balcony', 'park']) {
    if (text.includes(place)) {
      features.push(`${place} setting`);
      break;
    }
  }
  for (const garment of ['cardigan', 'hoodie', 'tee', 'blouse', 'dress', 'pajamas', 'sweater']) {
    if (text.includes(garment)) {
      features.push(`${garment} wardrobe`);
      break;
    }
  }
  return [...new Set(features)];
}

function recentPhotoVariationContext(companionId, limit = 3) {
  if (!companionId) return '';
  try {
    const rows = listPhotoRequestAudits({
      companionId,
      status: 'sent',
      days: 30,
      limit,
    })?.rows || [];
    const extracted = rows.map((row) => {
      // 只读最终送给生图模型的 prompt；planner_prompt 含规则示例，不能拿来当照片特征。
      const features = extractRecentPhotoFeatures(row);
      return {
        line: `- photo ${row.id}: ${features.join(', ') || 'recent sent photo'}`,
        features,
      };
    });
    const counts = new Map();
    for (const item of extracted) {
      for (const feature of item.features) counts.set(feature, (counts.get(feature) || 0) + 1);
    }
    const repeated = [...counts.entries()]
      .filter(([feature, count]) => count >= 2 && !['SELFIE', 'ENV_SELFIE', 'CANDID', 'phone selfie', 'imperfect framing'].includes(feature))
      .map(([feature]) => feature);
    const guard = repeated.length
      ? `- repeat guard: at least one of these repeatedly used visual elements must change this time; choose the replacement from the current scene, do not reuse the whole combination: ${repeated.join(', ')}`
      : '';
    return [...extracted.map((item) => item.line), guard].filter(Boolean).join('\n');
  } catch {
    return '';
  }
}

// v1.18.0: shot mode 三态 + 优先级修正；v1.19.5 (issue #237) 提炼为纯函数 + 上下文兜底。
// 旧 bug 1：用户明说"发张自拍"，但 current_scene 含晚霞/海时 isScenery 抢先命中 → 远景小背影。
//   修：拆「想看她」「想看景」「场景有景」三信号按意图定优先级，ENV_SELFIE 兜环境自拍。
// 旧 bug 2 (issue #237)：判定只看当前一条消息——聊了半天作业后用户说"你是不是发不了照片啊"，
//   这句没有"作业"字样 → 退回默认自拍，1 小时前的话题全丢。
//   修：当前消息有明确方向（自拍/景/活动）时永远优先；当前消息只是泛请求时，查最近几轮
//   上下文有没有"她正在做的事"（作业/代码/画…），有 → ACTIVITY_POV。
// v1.21.2 PR-D：按机位路由照片比例（手机前摄默认竖屏——'谁家好人自拍 1:1'修复）。
// SELFIE/ENV_SELFIE/ACTIVITY_POV/CANDID → 3:4 竖；SCENERY 默认 4:3 横，
// 窄竖景（塔/巷/瀑布/树）→ 3:4。provider 不支持原生比例时由 sender 文本兜底+落地裁切。
const TALL_SCENERY_RE = /(塔|高楼|大厦|巷|瀑布|树|竹|寺|楼梯|tower|alley|waterfall|tree|temple)/i;
export function aspectForShot(shotMode, sceneText = '') {
  if (shotMode === 'SCENERY') return TALL_SCENERY_RE.test(String(sceneText)) ? '3:4' : '4:3';
  return '3:4';
}

export function decideShotMode({ userText, recentText = '', currentScene = '', trigger = '' } = {}) {
  const _ptxt = String(userText || '');
  const _pscene = String(currentScene || '');
  const sceneIsScenic = /晚霞|夕阳|日落|余晖|落日|火烧云|天空|云海?|海边?|湖泊?|雪|月亮|星空|夜景|彩虹|樱花|风景|景色|窗外|江边?|河边?/.test(_ptxt + _pscene);
  const wantsSelfie = /自拍|看看你|看一下你|看看你的|你的样子|你长(啥|什么)样|想看你|拍张你|你的脸|露(个|张)?脸/.test(_ptxt);
  const wantsScenery = /(拍|看看|给我看|分享|来张|来一张|发张).{0,6}(晚霞|夕阳|日落|余晖|落日|火烧云|天空|云|海|湖|雪|月亮|星空|夜景|彩虹|樱花|风景|景色|外面|窗外)|外面.{0,4}(什么样|怎么样|长啥样)/.test(_ptxt);
  // v1.19.2: ACTIVITY-POV —— 用户想看"她手头正在做的事/作业/工作内容"(拍物不拍脸)。
  const wantsActivity = /(拍|看看|给我看|发张?|晒).{0,6}(作业|功课|工作|手头|笔记|手账|代码|方案|文档|在写的|在做的|在看的|在画的|在弄的|在练的|画|稿|书)|你(在|手头)?(写|做|弄|画|忙|敲|看|读|练|弹|搞)(的|了|啥|什么|到哪了?|多少了?)|(作业|功课|工作|代码|方案|稿|笔记|手账|画).{0,6}(到哪了?|多少了?|拍张?|看看|给我看)/.test(_ptxt);
  const selfieCapable = trigger === 'user_request' || trigger === 'request' || trigger === 'selfie';
  // 上下文兜底：当前消息没有任何明确方向（泛索图如"发不了照片啊？/再发一张"）时，
  // 最近对话里聊的是她手头的事 → 拍那个东西，别甩一张自拍装没聊过。
  const ctxActivity = !wantsSelfie && !wantsScenery && !wantsActivity
    && /(作业|功课|题|卷子|笔记|手账|代码|方案|文档|稿子?|论文|在写|在画|在做|字丑|公式)/.test(String(recentText || ''));
  if (wantsActivity || ctxActivity) return 'ACTIVITY_POV';
  if (wantsScenery && !wantsSelfie) return 'SCENERY';
  if (wantsSelfie || selfieCapable) return sceneIsScenic ? 'ENV_SELFIE' : 'SELFIE';
  return sceneIsScenic ? 'SCENERY' : 'CANDID';
}

function buildPlannerPrompt({ companion, userText, recentMessages, trigger, proactiveContext, gate, emotionContext, visualContext, recentPhotoContext = '', now = new Date() }) {
  const freshContext = selectFreshPhotoContext(recentMessages, { now });
  const freshMessages = freshContext.messages;
  const recent = freshMessages
    .slice(-8)
    .map((m) => {
      const ts = messageTimestampMs(m);
      const ageMin = ts == null ? '' : ` [${Math.max(0, Math.round((now.getTime() - ts) / 60_000))} min ago]`;
      return `${m.direction === 'in' || m.role === 'user' ? 'user' : 'assistant'}${ageMin}: ${safeText(m.content, 120)}`;
    })
    .filter(Boolean)
    .join('\n');

  // v1.10.21/34: 时间感 + 完整人设外观 + 美学层
  // 测试钩子：仅当显式设 PHOTO_TEST_HOUR(0-23) 才覆盖小时，用于评测不同时段；生产不设。
  const _testH = Number(process.env.PHOTO_TEST_HOUR);
  const h = Number.isInteger(_testH) && _testH >= 0 && _testH <= 23 ? _testH : (now.getUTCHours() + 8) % 24;
  const mm = String(now.getUTCMinutes()).padStart(2, '0');
  const dp = dayPartHint(h);
  const appearance = compactAppearance(companion);
  const facialCue = moodToFacialCue(companion?.current_mood);
  const clothingEn = clothingStyleToEnglish(companion?.clothing_style);
  const seasonalClothing = seasonalClothingHint(now);
  const recentPlain = freshMessages
    .slice(-8)
    .map(m => safeText(m.content, 120))
    .filter(Boolean)
    .join(' ');
  const rawCurrentScene = String(companion?.current_scene || '').trim();
  const neutralScene = !rawCurrentScene || /^(?:日常|无|未知)$/.test(rawCurrentScene);
  const sceneConfirmedByFreshContext = rawCurrentScene && recentPlain.includes(rawCurrentScene);
  const proactiveSceneIsCurrent = Boolean(proactiveContext?.scene || proactiveContext?.category?.sceneSeed);
  const effectiveCurrentScene = neutralScene || sceneConfirmedByFreshContext || proactiveSceneIsCurrent
    ? rawCurrentScene
    : '';
  const captureIntent = captureIntentFor(userText);
  let shotMode = decideShotMode({
    userText,
    recentText: recentPlain,
    currentScene: effectiveCurrentScene,
    trigger,
  });
  // v1.21.6 PR-A: proactive 加权采样命中的品类（仅主动分享时存在）——用品类默认机位
  // 覆盖 decideShotMode。放在安全模式钳位之前，安全模式仍最高优先级。
  const sampledCategory = (trigger === 'proactive' && proactiveContext?.category && typeof proactiveContext.category === 'object')
    ? proactiveContext.category : null;
  if (sampledCategory?.shotMode) shotMode = sampledCategory.shotMode;
  // v1.20 安全收尾：安全模式（疑似未成年）强制中性照片——只拍景/物，绝不自拍/人像/flirt
  const safeModePhoto = !!Number(companion?.safe_mode);
  if (safeModePhoto && shotMode !== 'SCENERY' && shotMode !== 'ACTIVITY_POV') {
    shotMode = 'SCENERY';
  }
  // v1.21.6 PR-C candid 实验（默认关，PHOTO_CANDID_EXPERIMENT）：开时低概率给 imagePrompt
  // 注入随手抓拍质感词。默认值待 20 张沙箱评估图维护者拍板，本 PR 不做开启决策。
  const candidExperiment = envFlag('PHOTO_CANDID_EXPERIMENT', false)
    && Math.random() < numberEnv('PHOTO_CANDID_PROB', 0.25, 0);

  // v1.23.0: 人物入镜时先构造“正在发生的视觉瞬间”，再把它写成 imagePrompt。
  // 这不是动作模板，也不改变 shotMode；SELFIE 只负责限定该瞬间必须从她自己的
  // 手机前摄里呈现。SCENERY/ACTIVITY-POV 不注入人物状态，避免污染无脸机位。
  const humanVisualMomentRule = (shotMode === 'SELFIE' || shotMode === 'ENV_SELFIE' || shotMode === 'CANDID')
    ? `
★★★ 画面方案：按「九块结构」一次给出一份完整方案 ★★★
本次 capture intent 是 ${captureIntent === 'posed' ? 'POSED：对方明确想要一张认真、端正的照片，可以自然摆拍' : 'LIVED：普通索图，应从她正在经历的生活里选择一个自然瞬间，不把标准正面微笑当默认答案'}。
只给**一份**方案（不再给多个候选），每块只写自己那一件事，块与块之间不得重复描述同一个属性：
  framing      —— 机位与取景：距离、角度、是否偏轴、裁切多少、环境占画面比例。
  action       —— 这一瞬间她正在做什么（正在说话/刚抬眼/手刚离开键盘…）。
  expression   —— 脸部表情，独立成块，不要在 action 里重复描写表情。
  wardrobe     —— 这一张的穿着。
  environment  —— 场景 + 光线 + **2~4 个具体生活物件**（皱床单、台灯、充电线、摊开的书、水杯、搭在椅背上的衣服…）。只写"卧室/咖啡馆"这类类别词不够：生活感来自背景里有可验证的、带使用痕迹的物件。
  sceneMoment  —— 把这一瞬间写成一句完整的英文画面描述（上面各块的总纲）。
环境不能只是人物背后的布景，道具也不能只是证明上下文的标签。若上下文明确她正在进行某项活动，
必须停留在同一时刻：不能让她先停下、坐好、到达目的地或换到下一场景后再拍。
LIVED 模式下不要给标准正面微笑+居中的证件照式方案；只有 POSED 才允许端正、居中、直视。
timelineRelation 必须按事实判断：原文是"正在走向/在路上"时，停在入口、已经进入、排队、坐下都属于 advanced；只有仍在走的同一动作才是 current。
不要为了显得不同而凭空添加与上下文无关的动作和物品。不要逐个规定身体部位或每只手；只描述成片真正需要看见的整体状态，避免多个动作互相竞争。
${shotMode === 'SELFIE' || shotMode === 'ENV_SELFIE'
    ? '方案必须是手机前置摄像头最终拍到的自拍成片，不是外部观察者看她自拍，也不是镜子自拍。framing 只描述最终画面里的角度、距离、取景偏移和环境占比，不重复 front camera，也不描述她举着手机的外部动作；不要出现 phone held、holding/holds a phone、eyes on screen、看向手机、over-the-shoulder 或 from-behind 等外部视角措辞。'
    : ''}
以上字段写在 \`visualPlan\` 对象里；另有三个**只用于防重复、不进入生图提示词**的元字段：
compositionFamily（英文短标签）、timelineRelation（current/advanced/paused/invented）、variationTags（2-5 个英文短标签）。`
    : '';

  const prompt = `请判断是否适合发送一张生活感照片，并只返回 JSON。

场景事实优先级（必须遵守）：
请综合 user text、仍然新鲜的 recent messages 以及其他可用上下文，提取此刻已经明确或高度确定的事实。旧消息只能作为关系背景，不能冒充当前地点、活动、衣着或光线。持久化 current scene 若未被新鲜对话或本次主动事件确认，只是低置信背景，不得直接用于当前照片。对于没有明确说明的部分，只做最少且自然的补全。

上下文：
- current shanghai time: ${String(h).padStart(2, '0')}:${mm}
- day part: ${dp.label} (${dp.id})
- lighting hint: ${dp.light}
- plausible scenes for this hour: ${dp.scenes}${(() => {
    // v1.21.5 PR-C 月相锚定：夜间 + 夜空类场景才注入真实月相，杜绝凭空"月亮好圆"。
    const isNight = h >= 19 || h < 5;
    const skyScene = /月亮|月色|星空|夜空|夜景|天空|月/.test(String(userText || '') + effectiveCurrentScene + String(proactiveContext?.scene || '') + String(sampledCategory?.sceneSeed || ''));
    if (!isNight || !skyScene) return '';
    return `
- ★ 月相事实（真实天象，不可违背）：${moonFactLine(now)}。**若前半夜不可见，绝不能拍月亮/月色，caption 也不许说"看到月亮/月色好/月亮好圆"**——改拍室内灯光或别的；若可见，按真实照亮比例描述（残月就别说满月）。`;
  })()}${(() => {
    // v1.21.6 PR-C 晚霞锚定：晚霞/夕阳类场景注入真实日落窗口，杜绝正午发晚霞（色温对不上=假）。
    const sunsetScene = /晚霞|夕阳|日落|余晖|落日|火烧云|黄昏/.test(String(userText || '') + effectiveCurrentScene + String(proactiveContext?.scene || '') + String(sampledCategory?.sceneSeed || ''));
    if (!sunsetScene) return '';
    return `
- ★ 日落事实（真实天象，不可违背）：${sunsetFactLine(now)}`;
  })()}${(() => {
    // v1.21.4 PR-W3：节气/节日真实历法（caption 可自然带，如"中秋拍的月饼"）——月相/日落上面已单管。
    try { const d = realityDateFacts(now); return d ? `\n- ★ 真实历法（caption 可自然带，不编造）：今天是${d}。` : ''; } catch { return ''; }
  })()}

- trigger: ${trigger}${sampledCategory ? `
- ★ 本次主动分享品类（加权采样命中）：「${safeText(sampledCategory.label, 20)}」—— ${safeText(sampledCategory.sceneSeed, 120)}。优先围绕这个品类决定拍什么；**但若此刻她的时段/场景与该品类实在不自洽（如深夜让拍晚霞、在家却要拍货架），宁可 shouldSendPhoto=false 也不要硬凑**。` : ''}${safeModePhoto ? `
- ★★ SAFE MODE（最高优先级）：对方可能是未成年人。只允许分享风景/食物/手头事物等**中性照片**（已强制非自拍机位）；imagePrompt 绝不写任何人物/外貌/表情；caption 必须是普通朋友分享的口吻，**绝无**暧昧/撒娇/调情。拿不准就 shouldSendPhoto=false。` : ''}
- shot mode: ${
  shotMode === 'ACTIVITY_POV' ? 'ACTIVITY-POV（她拍自己正在做的事/手头的东西给对方看，像"你看我在写的作业"。first-person POV 低头看自己的桌面/手头：**主体是那个作业本/电脑屏幕/工作内容/手头的物件**——写满字的笔记本+笔、屏幕上的文档或代码、画了一半的画、做饭的案板等，桌面/物体填满画面；**绝不出现她的脸、身体、手、衣袖或其他身体部位，不是自拍**；镜头只对准桌面/物件；写明当前时段光线如 warm desk lamp at night / soft daylight by the window。规则 4/5/6/9（人物外貌/表情/着装）对它不适用）'
  : shotMode === 'ENV_SELFIE' ? 'ENVIRONMENTAL SELFIE（输出画面就是手机前置摄像头直接拍到的成片，不是别人看她自拍，也不是镜子自拍；手机/相机本体绝不入镜。她是主要人物，环境景物必须与当前对话一致；具体距离、取景、视线、姿态和表情由这个生活瞬间自然决定，不要把参考图的构图照搬过来）'
  : shotMode === 'SELFIE' ? 'SELFIE（输出画面就是手机前置摄像头直接拍到的成片，不是别人看她自拍，也不是镜子自拍；手机/相机本体绝不入镜。人物身份清楚，imagePrompt 需要描述她在成片里呈现的当前生活状态；距离、取景、头部角度、视线、姿态、表情、衣着和背景都由当前场景决定，不要自动重复最近照片的组合）'
  : shotMode === 'SCENERY' ? 'SCENERY-POV（主体是她眼前的景本身——晚霞/天空/海等，那个景填满画面，像真人随手拍"你看这个"发给对方；最多一只手或衣角出现在画面极边缘，**手机/相机本身绝不能出现在画面里**（别写 holding a phone / a phone in frame）；绝不是站在景前的人像或全身照）'
  : 'CANDID（natural everyday photo；取景和人物入镜方式由当前场景决定，不要摆成标准肖像）'
}
- companion name: ${safeText(companion?.name || '她', 40)}
- companion appearance: ${appearance}
- companion clothing in english: ${clothingEn}
- seasonal clothing baseline: ${seasonalClothing}
- companion current mood / facial cue (英文，可参考但不强制复制): ${facialCue}
- relationship stage: ${safeText(companion?.relationship_stage || '', 40)}
- persistent current scene: ${effectiveCurrentScene ? safeText(effectiveCurrentScene, 80) : '(withheld: stale or unconfirmed for the current photo)'}
- persistent scene status for this photo: ${effectiveCurrentScene ? 'confirmed/neutral enough to use' : 'STALE OR UNCONFIRMED — do not use as the current photo location'}
- photo context freshness window: ${freshContext.maxAgeMinutes} minutes; ${freshContext.staleCount} older messages excluded
- capture intent: ${captureIntent}
- user text: ${safeText(userText || '', 160)}
- recent messages:
${recent || '(none)'}
- proactive context: ${safeText(JSON.stringify(proactiveContext || {}), 400)}
- hidden emotion photo context: ${safeText(JSON.stringify(emotionContext || buildEmotionPhotoContext(null)), 500)}
- visual identity context: ${safeText(JSON.stringify(visualContext || {}), 500)}
- gate: ${safeText(JSON.stringify({ todayCount: gate?.todayCount, dailyLimit: gate?.limits?.dailyLimitPerCompanion }), 200)}
${recentPhotoContext ? `- recent sent-photo variation signatures（仅用于避免机械重复，不要逐字复制）：\n${recentPhotoContext}` : ''}

要求：
1. 你只判断是否应发一张现实生活感图片，不要每次暗示都发。
2. 明确要求看你/发照片时可更倾向发送，但仍要自然。
3. 主动照片必须低频，像临时想分享当下。
${humanVisualMomentRule}
★★★ imagePrompt 美学强约束（v1.10.34）★★★
4. visualPlan 各块与 imagePrompt 的画面描述必须是英文。**（若 shot mode = SCENERY-POV 或 ACTIVITY-POV，不需要 visualPlan，只输出 imagePrompt。）** 人物机位不要在 visualPlan 里重复完整外貌身份，身份会由发送层统一加入；visualPlan 只负责真正决定这张照片的生活瞬间与视觉状态。
5. visualPlan.expression 只写这一张的脸部表情（半成品微笑/刚抬眼/若有所思…），不要写成"完美营业笑"；也不要把上一张照片的表情当默认值。表情不要和 action 块重复描写。
6. visualPlan.wardrobe 由你判断穿着，必须同时自洽于三件事：**seasonal clothing baseline（上面的季节基线）、当前地点、正在做的事**。海边/校园/床上休息/室内家居/通勤路上各自选物理上舒服、现实可信的穿搭。角色的"甜美/清新/酷"只决定款式倾向，不能覆盖季节厚薄与场景功能。可以按天气常理选择长袖、针织、开衫或薄外套——但**不要把厚外套、羽绒服、围巾这类冬季单品穿在夏秋场景里**。**禁止 navy office sweater / formal collar shirt / professional attire**。
7. **必须严格按上面给出的 shot mode 写构图**：
   - **ENVIRONMENTAL SELFIE**：人是主要人物，环境景物也要成为当前场景的一部分；只写前摄最终成像，不写举手机、拿手机、手机在面前、手臂拿手机或镜子自拍；具体景别、姿态、视线和背景比例由上下文决定，不能机械套用近景半身。
   - **SELFIE**：是真实手机前摄的最终成片，人物身份清楚，日常环境与对话相符；手机和镜子不入镜，不写外部观察者看见她拍照；不要默认胸像、正脸、伸手、微笑或统一的背景虚化。
   - **SCENERY-POV**：主体写那个景（如 "warm sunset glow over the sea, looking out over the water, the scenery fills the frame"），**景填满画面、是绝对主角**；最多 "a hand or sleeve at the very edge of the frame"，**绝不能让手机/相机出现在画面里**（别写 holding a phone / a phone in frame / taking a photo —— 否则模型会把一只手举着手机怼在镜头前，很出戏）。**SCENERY-POV 时只写景本身，不要写任何人物外貌/表情/着装/skin —— 规则 4/5/6/9 对它不适用**（写了 skin/face/young woman 会让模型硬塞一个人进画面当主体）。
   - **ACTIVITY-POV**：拍她手头正在做的事/东西（作业本+笔、电脑屏幕上的文档/代码、画到一半的画、做饭案板…），first-person POV 低头看桌面，**那个物件/作业/工作内容填满画面、是绝对主角**；**绝不出现她的脸、不是自拍**，最多一只手或衣袖在画面边缘；写当前时段光线。**只写桌面/物件不写人物外貌/表情/着装 —— 规则 4/5/6/9 对它不适用**。
   - **CANDID**：随手抓拍，slightly imperfect framing, natural everyday moment。
   **人像照的景别和姿态不要固定**：由当前活动、身体状态、空间大小和拍摄关系决定；上下文没有规定时，只需避免与最近照片完全重复，不要列举或强行指定某个动作。
8. **【最重要】照片里的时间感必须与 current shanghai time 严格一致**：必须写当前 day part 的 lighting hint 并明确点出时段——**夜晚/深夜就必须写 "at night, dark sky / dark window outside, lit only by the available indoor light"，绝对禁止出现 daylight / sunshine / bright daytime / sunny / 户外白天**；只有白天才写日光。**visualPlan/imagePrompt 与 caption 必须同一时间、同一地点自洽**：caption 说"刚到家台灯下补作业"，画面就必须是"室内夜晚书桌台灯"，绝不能是户外/白天。**若 companion current scene 与当前时段冲突**（如夜里 22 点 current_scene 还写"在路上"），**一律以当前时段的合理场景为准**重新设定（22 点该是到家/卧室/书桌，不是还在路上的大白天）。只选 plausible scenes 范围内的场景；**深夜禁 cafe/奶茶店/outdoor daylight**，清晨禁 dark bedroom。**忠实使用现场原有环境光和普通手机自动曝光，不为人物重新布光、不把现场优化成专业人像；保留由当前环境自然造成的曝光、白平衡、清晰度和动态范围差异。**自拍使用符合当前画面的 phone-camera perspective，风景使用 wide natural phone-camera perspective。**户外场景要符合现实**：放学/通勤路上应有 a few passersby / 路灯 / 店铺等真实街景，夜晚户外要有 street lights / lit shops，不是空无一人的大白天。**必须明确写出所在背景/环境，且与 caption 一致**——只写人不写环境，模型会自己乱编背景；环境应像正在使用中的真实空间，不要无依据地整理成布景或添加装饰。**不要为了满足固定词序而把每张照片都写成 close chest-up；先写当前场景和可见事实，再自然决定人物和取景。**
9. 人物身份、肤质与稳定外貌由发送层统一补充；visualPlan 不重复这些固定信息。visualPlan 可以写由当下环境真实造成的碎发、风、运动轻微模糊、曝光或白平衡变化，但只能在场景确实支持时使用，不能把它们变成每张照片的新模板。严禁具体年龄数字以及 minor / teen / underage / child / kid / schoolgirl / lolita / high school，也不要写 8k / 4k / ultra HD / masterpiece / hyperreal / flawless skin / perfect skin。
10. visualPlan 各块与 imagePrompt **不要写 "no XXX" / "without XXX" 等 negative 排除句**（会被本系统的安全过滤误伤）。改用**正面同义词替代**：
    - 想表达「不要专业写真」→ 写 "casual amateur smartphone snapshot vibe, everyday spontaneous moment"
    - 想表达「不要 35mm 电影感」→ 写 "available ambient light with ordinary phone auto-exposure"
    - 想表达「不要疲惫脸」→ 写 "fresh lively bright face, gentle warm energy"
    - 想表达「不要办公室风着装」→ 写 "casual youthful home or campus outfit"
    - 想表达「不要 anime/插画」→ 写 "photorealistic, real life photography"
    - 想表达「不要 minor/teen/schoolgirl」→ 写 "youthful early-college vibe, soft natural features, warm bright eyes, fresh clear complexion with realistic natural skin texture and fine pores"（不要 dewy/baby-faced/round-cheeks 那种磨皮娃娃脸）
    - 想表达「不要 NSFW/nude/sexual」→ 写 "wholesome, fully clothed, casual everyday attire"
11. visualPlan 各块与 imagePrompt 不要包含隐私、token、手机号、精确地址。
12. hidden emotion / visual identity context 只作为隐藏参考，不要把内部 JSON 字段或分数写进 imagePrompt 或 caption。
★ **真实出版物护栏（V1214 正式解前临时规矩）**：若画面涉及真实出版物（书/杂志/专辑/教材/报纸），**只拍摊开内页、或书脊/封面一角的局部，绝不拍完整正面封面**（生成封面=伪造、复刻=版权，两条都死）；POV 俯拍翻开的跨页或文字段落即可。**例外不受限：她自己的笔记本/手账/便签本封面**（私人物品非出版物，可正常拍）。
★ **天气护栏（真实天气数据接入前）**：**禁止拍雨/雪/雷暴/大雾等天气依赖场景**（无法核实当天真实天气，瞎拍即假）；晴/阴/室内不受限，晚霞/月亮已有专门锚定（见上面日落/月相事实）。${candidExperiment ? `
★ **随手抓拍质感（实验）**：imagePrompt 末尾补 "casual unstaged candid phone grab, slightly imperfect off-center framing, natural and relaxed, not posed"——更松弛、别摆拍。` : ''}

caption：
13. caption 是发给他看的微信短句，10 到 35 字，不解释系统逻辑，不说作为 AI，不说生成图片，不说当前情绪状态，不输出 [PHOTO]。caption 内容必须与 day part 一致（深夜不要说"路过咖啡店"等白天动作；夜晚多用"躺床上 / 灯关了一半 / 突然想你"等贴近时间的描述）。**优先与最近聊天/记忆里的事自然勾连**（他提过累→"看我给你拍的，歇会儿吧"），想不到关联就发自然的当下短句、别硬蹭。${proactiveContext?.inviteBack ? '\n★ **本次额外带一句互拍邀请**（低频）：caption 自然收一句"到你了 / 你那边呢 / 也给我看看你那边"，像情侣互拍的轻邀请，别生硬别像任务。' : ''}

返回 JSON 结构：
{
  "shouldSendPhoto": true,
  "mode": "send_photo",
  "trigger": "${trigger}",
  "photoType": "casual_daily",
  "realism": "realistic_daily",
  "imagePrompt": "非人物机位使用；人物机位可留空作为兼容兜底",
  "visualPlan": {
    "sceneMoment": "一句完整的英文画面描述：此刻正在发生的那个瞬间",
    "framing": "机位与取景：距离、角度、偏轴、裁切、环境占画面比例",
    "action": "这一瞬间她正在做什么（不要在表情块里重复）",
    "expression": "脸部表情（独立一块）",
    "wardrobe": "这一张的穿着（自己判断季节基线+地点+活动是否自洽）",
    "environment": "场景 + 光线 + 2~4 个具体生活物件",
    "compositionFamily": "英文短标签",
    "timelineRelation": "current|advanced|paused|invented",
    "variationTags": ["...", "..."]
  },
  "caption": "短句",
  "delayImageMs": 1200,
  "delayCaptionMs": 900,
  "maintainIdentity": true,
  "reason": "日志用原因"
}

如果不适合发图，返回（caption 用她的语气说一句此刻拍不了的自然话，别用罐头"刚才没拍好"；
canRetakeLater：若只是此刻条件不行、换个时间能拍 = true，若根本拍不出该物 = false）：
{"shouldSendPhoto":false,"mode":"text_only","trigger":"${trigger}","photoType":"other","realism":"realistic_daily","imagePrompt":"","caption":"（此刻拍不了的自然话）","canRetakeLater":true,"delayImageMs":0,"delayCaptionMs":0,"reason":"为什么拍不了"}`;
  return { prompt, shotMode, captureIntent, recentPhotoContext, freshContext, freshContextText: recentPlain, seasonalClothing };
}

export async function planPhotoMessage({
  companion,
  user = null,
  userText = '',
  recentMessages = [],
  trigger = 'none',
  context = {},
  cooldownState = null,
  imageProviderAvailable = isImageProviderConfigured(),
  proactiveContext = null,
  emotionState = null,
  imageProviderCapabilities = getImageProviderCapabilities(),
} = {}, deps = {}) {
  const gate = cooldownState || getPhotoGateState({
    companion,
    trigger,
    source: trigger === 'proactive' ? 'proactive' : 'request',
    imageProviderAvailable,
  });
  if (!gate.allowed) {
    return { ...DEFAULT_PLAN, trigger, reason: `gate blocked: ${gate.reasons.join(', ')}`, gate };
  }

  const system = `你是照片发送决策器。你不聊天，只返回合法 JSON。目标是让陪伴对象偶尔像现实世界里的人一样自然分享生活照片。`;
  const emotionContext = buildEmotionPhotoContext(emotionState);
  const visualContext = getVisualContext(companion, imageProviderCapabilities);
  // v1.21.6 hotfix（P0 静默断图）：buildPlannerPrompt 自 d22bf73(v1.21.2) 起返回
  // {prompt, shotMode} 对象，但此处一直当字符串接收 → 整个对象被当 message content
  // 传给 LLM（"content should be a string" 400）→ 自 06-11 起所有照片静默失败。
  // 必须解构出字符串 prompt；shotMode 顺带落库到 plan（比例路由）。
  const recentPhotoContext = recentPhotoVariationContext(companion?.id);
  const planningNow = deps.now instanceof Date ? deps.now : new Date();
  const { prompt, shotMode, captureIntent, freshContext, freshContextText, seasonalClothing } = buildPlannerPrompt({
    companion, user, userText, recentMessages, trigger, context, proactiveContext, gate,
    emotionContext, visualContext, recentPhotoContext, now: planningNow,
  });
  const proactiveScene = [
    proactiveContext?.scene,
    proactiveContext?.category?.sceneSeed,
  ].filter(Boolean).join(' ');
  const sceneText = `${userText || ''} ${companion?.current_scene || ''} ${proactiveScene}`;
  try {
    const raw = deps.mockResponse != null
      ? deps.mockResponse
      : deps.llm
        ? await deps.llm({ system, prompt })
        : await extractStructuredInfo(system, prompt, {
          accountId: context?.accountId || user?.account_id || null,
          maxTokens: 1100,
          temperature: 0.35,
        });
    const parsed = extractJson(raw);
    return {
      ...normalizePlan(parsed, {
        trigger,
        gate,
        shotMode,
        sceneText,
        userText,
          currentScene: companion?.current_scene || '',
          proactiveScene,
          captureIntent,
          recentPhotoContext,
          freshContextText,
          seasonalClothing,
        }),
      // 给后台审计用；不进入用户聊天，也不改变规划结果。
      plannerPrompt: prompt,
      plannerRaw: parsed,
      photoContextFreshness: {
        maxAgeMinutes: freshContext.maxAgeMinutes,
        staleCount: freshContext.staleCount,
        usedMessageCount: freshContext.messages.length,
      },
    };
  } catch (e) {
    log('warn', `[PhotoPlanner] plan failed: ${e.message}`);
    return {
      ...DEFAULT_PLAN,
      trigger,
      reason: `planner error: ${e.message}`,
      gate,
      plannerPrompt: prompt,
      plannerRaw: null,
    };
  }
}
