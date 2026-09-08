/**
 * 企业认知 Context Compiler。
 * 这里只负责按输入对象编译稳定、可追溯的上下文包，不读取任何文件。
 */

import { assertCognitionSourcePort } from './source-port.mjs';

export const ENTERPRISE_CONTEXT_VERSION = 'enterprise-context-v3';

const asList = value => Array.isArray(value) ? value.filter(Boolean) : [];
const asText = (value, max = 1200) => {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim();
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
};

function normalizeRef(item, index, type) {
  const id = asText(item?.id || `${type}:${index}`, 180);
  return {
    id,
    type,
    assetType: type,
    epistemicStatus: asText(item?.epistemicStatus || item?.status || 'unknown', 80),
    status: asText(item?.status || item?.epistemicStatus || 'unknown', 80),
    title: asText(item?.title || item?.name || item?.statement || item?.decision || item?.target || id, 240),
    summary: asText(item?.summary || item?.statement || '', 1400),
    relevance: Number.isFinite(Number(item?.relevance)) ? Number(item.relevance) : undefined,
    scope: item?.scope && typeof item.scope === 'object' ? item.scope : {},
    sourceRefs: asList(item?.sourceRefs || item?.refs || item?.supportingEvidenceRefs).map(value => asText(value, 180)).slice(0, 20),
    refs: asList(item?.refs || item?.sourceRefs || item?.supportingEvidenceRefs).map(value => asText(value, 180)).slice(0, 20),
  };
}

function normalizeGoal(item, index) {
  const goal = normalizeRef(item, index, 'goal');
  return {
    ...goal,
    target: item?.target ?? item?.targetValue ?? null,
    metricRefs: asList(item?.metricRefs || item?.metrics).map(value => asText(value, 120)).slice(0, 20),
    timeRange: item?.timeRange && typeof item.timeRange === 'object' ? { start: item.timeRange.start || null, end: item.timeRange.end || null } : null,
    priority: ['low', 'normal', 'high'].includes(item?.priority) ? item.priority : 'normal',
  };
}

function normalizeDecision(item, index) {
  const decision = normalizeRef(item, index, 'decision');
  return {
    ...decision,
    decision: asText(item?.decision || item?.statement || item?.summary || '', 1200),
    reason: asText(item?.reason || '', 1200),
    basedOnRefs: asList(item?.basedOnRefs || item?.sourceRefs || item?.refs).map(value => asText(value, 180)).slice(0, 20),
    rejectedAlternatives: asList(item?.rejectedAlternatives).map(value => asText(value, 600)).slice(0, 10),
    decidedAt: asText(item?.decidedAt || item?.updatedAt || '', 80),
  };
}

function scopeAllows(item, venueNames) {
  if (!venueNames.length) return true;
  const scope = item?.scope || {};
  const itemVenues = asList(scope.venueNames || scope.venues || scope.venueIds).map(String);
  return !itemVenues.length || itemVenues.some(value => venueNames.includes(value));
}

function validateCognitionProtocol({ objects, goals, decisions }) {
  const warnings = [];
  for (const item of [...objects, ...goals, ...decisions]) {
    if (!item?.id || !item?.assetType) warnings.push('对象缺少稳定 id 或 assetType');
  }
  for (const item of objects) {
    if (item.assetType === 'experience' && item.epistemicStatus === 'accepted_experience' && !item.sourceRefs.length) {
      warnings.push(`正式经验 ${item.id} 缺少来源引用`);
    }
  }
  return { ok: warnings.length === 0, warnings: [...new Set(warnings)].slice(0, 20) };
}

export function compileEnterpriseContext({
  source,
  input = {},
  items = [],
  goals = [],
  decisions = [],
  missingInformation = [],
  boundaries = [],
  fingerprint = '',
} = {}) {
  assertCognitionSourcePort(source);
  const requestedScope = input.scope && typeof input.scope === 'object' ? input.scope : {};
  const venueNames = [...new Set(asList(requestedScope.venueNames || requestedScope.venues || requestedScope.venueIds).map(String).filter(Boolean))];
  const boundedItems = items.filter(item => scopeAllows(item, venueNames)).map((item, index) => normalizeRef(item, index, item?.assetType || 'asset'));
  const normalizedGoals = goals.filter(item => scopeAllows(item, venueNames)).map(normalizeGoal).filter(item => item.id && item.summary || item.target !== null);
  const normalizedDecisions = decisions.filter(item => scopeAllows(item, venueNames)).map(normalizeDecision).filter(item => item.id && (item.decision || item.summary));
  const allMissing = [...new Set(asList(missingInformation).map(value => asText(value, 300)).filter(Boolean))].slice(0, 12);
  const allBoundaries = [...new Set(asList(boundaries).map(value => asText(value, 500)).filter(Boolean))];
  const confirmedFacts = boundedItems.filter(item => ['confirmed_operating_fact', 'system_fact'].includes(item.epistemicStatus));
  const implicitKnowledge = boundedItems.filter(item => item.assetType === 'implicit_knowledge' && item.epistemicStatus === 'confirmed_implicit_knowledge');
  const knowledgeGaps = boundedItems.filter(item => item.assetType === 'knowledge_gap');
  const activeWork = boundedItems.filter(item => item.assetType === 'validation');
  const publishedExperiences = boundedItems.filter(item => item.assetType === 'experience' && item.epistemicStatus === 'accepted_experience');
  const claimsAndHypotheses = boundedItems.filter(item => !confirmedFacts.includes(item) && !implicitKnowledge.includes(item) && !knowledgeGaps.includes(item) && !activeWork.includes(item) && !publishedExperiences.includes(item));
  const protocolValidation = validateCognitionProtocol({ objects: boundedItems, goals: normalizedGoals, decisions: normalizedDecisions });
  const constraints = [
    ...(source.profile?.project?.commonConstraints || []),
    ...Object.values(source.profile?.venues || {}).flatMap(venue => venue?.constraints || []),
  ].map(value => asText(value, 500)).filter(Boolean).slice(0, 30);
  return {
    // contextVersion 保留旧桥接消费者的 v1 语义；schemaVersion 是新协议的真实版本。
    contextVersion: 'enterprise-context-v1',
    schemaVersion: ENTERPRISE_CONTEXT_VERSION,
    sourcePortVersion: source.version,
    scope: {
      projectId: String(requestedScope.projectId || source.catalog?.project?.id || source.profile?.project?.id || ''),
      venueNames,
    },
    // items 是 v1 兼容字段；objects 及下列分组是 v2 结构化字段。
    items: boundedItems,
    objects: boundedItems,
    goalsAndDecisions: { goals: normalizedGoals, decisions: normalizedDecisions },
    protocolValidation,
    confirmedFacts,
    implicitKnowledge,
    knowledgeGaps,
    claimsAndHypotheses,
    capabilitiesAndConstraints: constraints,
    activeWork,
    publishedExperiences,
    supportingEvidence: boundedItems.flatMap(item => item.sourceRefs || []).slice(0, 60),
    counterEvidence: [],
    boundaries: allBoundaries,
    missingInformation: allMissing,
    fingerprint: String(fingerprint || ''),
  };
}
