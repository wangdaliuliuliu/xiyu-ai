/* 溪语经营知识桥最小可用性回归（不访问真实模型或工作台）。 */
process.env.XIYU_WORKBENCH_CONTEXT_URL = 'http://workbench.test';
process.env.XIYU_WORKBENCH_CONTEXT_ENABLED = 'true';

const calls = [];
globalThis.fetch = async (url, options = {}) => {
  calls.push({ url: String(url), method: options.method || 'GET' });
  if (String(url).endsWith('/api/knowledge/catalog')) {
    return new Response(JSON.stringify({ ok: true, catalog: {
      project: { id: 'demo-project', name: '演示项目' },
      venues: [{ id: 'VENUE_A', name: '门店A' }], nodes: []
    }}), { status: 200, headers: { 'content-type': 'application/json' } });
  }
  if (String(url).endsWith('/api/knowledge/retrieve')) {
    return new Response(JSON.stringify({ ok: true, context: {
      contextVersion: 'enterprise-context-v1',
      items: [{ id: 'profile:venue:VENUE_A', assetType: 'venue_profile', epistemicStatus: 'confirmed_background', title: '门店A', summary: '门店A与场域客流相关。' }],
      boundaries: ['背景不能单独证明因果'], missingInformation: [], fingerprint: 'smoke'
    }}), { status: 200, headers: { 'content-type': 'application/json' } });
  }
  const posted = options.body ? JSON.parse(options.body) : null;
  return new Response(JSON.stringify({ ok: true, candidate: posted }), { status: 200, headers: { 'content-type': 'application/json' } });
};

const { prepareEnterpriseContext, extractWorkIntelligence, drainEnterpriseOutbox, formatEnterpriseContext, __resetEnterpriseContextCacheForTest } = await import('../src/enterprise_context.mjs');
__resetEnterpriseContextCacheForTest();

const route = {
  conversationType: 'mixed',
  workSegments: ['门店A场域客流回落'],
  scope: { projectId: 'demo-project', venueIds: ['VENUE_A'] },
  intent: { topics: ['场域客流'], assetTypes: ['venue_profile'] },
  retrievalNeeded: true, writebackPotential: true, confidence: 0.9
};
const prepared = await prepareEnterpriseContext({ message: '门店A场域客流回落', history: [], accountId: 'smoke-account', companionId: 'smoke-companion' }, {
  route: () => route,
  retrieve: async () => ({ contextVersion: 'enterprise-context-v1', items: [{ id: 'profile:venue:VENUE_A', assetType: 'venue_profile', epistemicStatus: 'confirmed_background', title: '门店A', summary: '门店A与场域客流相关。' }], boundaries: ['背景不能单独证明因果'], missingInformation: [], fingerprint: 'smoke' })
});
if (!prepared.promptBlock.includes('enterpriseContext') || !prepared.promptBlock.includes('门店A')) throw new Error('经营上下文没有进入主提示词');

const saved = [];
const extracted = await extractWorkIntelligence({ route, context: prepared.context, message: '门店A场域客流回落', reply: '这个变化值得看一下。', accountId: 'u1', conversationId: 'c1', turnId: 't1' }, {
  extract: async () => JSON.stringify({ candidates: [{ candidateType: 'operating_fact_candidate', epistemicStatus: 'operator_observation', statement: '门店A场域客流回落', businessTopics: ['场域客流'], suggestedTarget: 'operating_fact', confidence: 0.8, source: { quote: '门店A场域客流回落' } }] }),
  write: async candidate => { saved.push(candidate); return { ok: true, candidate }; }
});
if (extracted.skipped || saved.length !== 1 || saved[0].reviewStatus !== 'pending' || saved[0].source.channel !== 'xiyu_conversation') throw new Error('工作新知候选没有按待审核协议生成');
const direct = await extractWorkIntelligence({ route, context: prepared.context, message: '门店A又补充了一个事实', reply: '记下了。', accountId: 'u1', conversationId: 'c2', turnId: 't2' }, {
  extract: async () => JSON.stringify({ candidates: [{ candidateType: 'operating_fact_candidate', statement: '门店A又补充了一个事实', source: { quote: '门店A又补充了一个事实' } }] })
});
if (direct.savedCount !== 1 || (await drainEnterpriseOutbox({ force: true })).remaining !== 0) throw new Error('候选 outbox 未能投递并清空');
const personal = await prepareEnterpriseContext({ message: '今天有点累', history: [], accountId: 'smoke-account', companionId: 'smoke-companion' }, { route: () => ({ conversationType: 'personal', workSegments: [], retrievalNeeded: false, writebackPotential: false, confidence: 0.98 }) });
if (personal.promptBlock || personal.context) throw new Error('纯私人聊天不应携带经营上下文');
if (!calls.some(call => call.url.endsWith('/api/knowledge/catalog'))) throw new Error('未读取动态目录');
console.log(JSON.stringify({ ok: true, catalogCalls: calls.filter(call => call.url.endsWith('/api/knowledge/catalog')).length, retrieveCalls: calls.filter(call => call.url.endsWith('/api/knowledge/retrieve')).length, candidatePosts: calls.filter(call => call.url.endsWith('/api/intelligence/candidates')).length, mixedPrompt: formatEnterpriseContext(prepared.context).length, candidateCount: saved.length + direct.savedCount }));
