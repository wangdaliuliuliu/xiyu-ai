// Stable enterprise dimensions are an index. Facets decide whether knowledge is
// sufficient for analysis; one confirmed sentence must never complete a dimension.
export const roles = {
  owner: '企业负责人', operations: '经营运营', reputation: '品牌与舆情',
  growth: '市场与曝光', finance: '财务', delivery: '门店与交付', people: '组织与人事',
};

const facet = (id, title, question, decisionUse) => ({ id, title, question, decisionUse });
const definitions = [
  ['identity', '企业定位与边界', ['owner'], [], '决定哪些机会值得做，避免偏离企业定位', [
    facet('audience', '核心服务对象', '目前最希望优先服务哪一类人？', '判断机会是否服务核心对象'),
    facet('core_value', '核心选择理由', '这类顾客选择我们而不是其他娱乐项目，最常见的理由是什么？', '判断产品和表达应突出什么价值'),
    facet('exclusions', '明确不做的事', '哪些客户、业务或承诺即使能带来收入也明确不做？', '排除会伤害定位或无法兑现的机会'),
    facet('opportunity_test', '机会判断标准', '遇到一个新机会时，你通常用哪两三条标准判断该不该做？', '把定位变成可执行的筛选规则'),
  ]],
  ['goals', '目标与取舍', ['owner'], ['identity'], '为各岗位方案建立共同的取舍依据', [
    facet('priority', '当前首要结果', '当前阶段最需要优先改善的结果是什么，期限大概到什么时候？', '确定方案优化目标'),
    facet('tradeoff', '冲突取舍', '收入、利润、增长或稳定性冲突时，眼下优先保哪一个？', '处理互相冲突的建议'),
    facet('success_signal', '成功信号', '看到什么具体变化，你会认为这一阶段做对了？', '定义验收和停止条件'),
  ]],
  ['role_goals', '岗位目标与协作', Object.keys(roles), ['goals'], '按使用者职责而非统一营收视角选择方案', [
    facet('owned_outcome', '负责结果', '你主要对什么结果负责，用什么指标和期限判断做好了？', '按岗位筛选建议'),
    facet('responsibility_boundary', '职责边界', '哪些事情由你决定，哪些需要交给别人或向上确认？', '避免把任务交给错误角色'),
    facet('dependencies', '协作依赖', '你完成工作最常需要谁提供什么输入？', '形成可执行交接'),
  ]],
  ['customers', '客户与购买理由', ['operations', 'growth', 'delivery'], ['identity'], '选择产品表达、获客对象和服务改进', [
    facet('segments', '客户分层', '目前最重要的客户群分别是谁，使用场景有什么不同？', '选择目标客群'),
    facet('purchase_drivers', '购买动力', '顾客最终下单最常因为哪一点？这个判断来自什么观察？', '选择表达和产品重点'),
    facet('dropoffs', '放弃原因', '顾客最常在哪一步放弃，现场通常能观察到什么原因？', '定位转化损失'),
  ]],
  ['offering', '产品与价值承诺', ['operations', 'delivery'], ['identity'], '避免推荐不适合客户或无法交付的产品', [
    facet('portfolio_fit', '产品与适用对象', '主要产品或套餐分别适合谁、解决什么需求？', '匹配客户和产品'),
    facet('promise', '体验承诺', '哪些体验或结果是稳定能承诺的？', '确定可对外表达的价值'),
    facet('promise_boundary', '承诺边界', '哪些效果、时效或服务目前不能承诺？', '避免过度承诺'),
  ]],
  ['economics', '财务与经营模型', ['finance', 'owner'], ['goals'], '判断活动投入是否承受得起，而非只追求销售额', [
    facet('unit_economics', '单位经营账', '判断一个产品或活动值不值得做时，至少要守住哪些成本和毛利口径？', '核算单项动作是否成立'),
    facet('budget_cash', '预算与现金边界', '目前哪些预算或现金流底线不能突破？', '约束投入规模和节奏'),
    facet('exception_rule', '例外批准', '什么情况下可以接受短期亏损，谁来批准？', '区分试验投入和失控亏损'),
  ]],
  ['capacity', '资源与交付能力', ['delivery', 'operations'], ['offering'], '把建议限定在真实可执行范围内', [
    facet('bottleneck', '当前瓶颈', '现在哪种人手、设备、场地或时段最限制交付？', '找到首先要解除的约束'),
    facet('available_capacity', '可用余量', '哪些时段或资源仍有可稳定利用的余量？', '判断增量动作放在哪里'),
    facet('failure_boundary', '失效边界', '业务量增加到什么程度时，体验或交付最先出问题？', '设置扩张停止条件'),
  ]],
  ['authority', '权限与流程', ['owner', 'people'], ['role_goals'], '形成可交付给执行者的步骤与审批路径', [
    facet('decision_owners', '决策人', '价格、预算、宣传和合作分别由谁最终拍板？', '正确路由决策'),
    facet('lead_time', '审批时效', '这些审批通常需要多久，最常卡在哪一步？', '估算执行周期'),
    facet('handoff', '交接要求', '提交审批或交给下一位执行者时，必须带哪些材料？', '生成完整交付物'),
  ]],
  ['channels', '渠道与合作资源', ['growth', 'operations'], ['customers'], '选择能触达目标人群的现实渠道', [
    facet('inventory', '可用渠道', '哪些自有渠道和合作关系目前确实可以调用？', '选择现实触达路径'),
    facet('constraints', '调用条件', '这些渠道各自有什么费用、权限、频次或内容限制？', '评估执行成本和边界'),
    facet('performance', '有效性证据', '哪些渠道过去对哪类客户有效，依据是什么？', '避免平均分配资源'),
  ]],
  ['reputation', '品牌与舆情边界', ['reputation', 'delivery'], ['identity'], '兼顾声誉、传播和服务补救', [
    facet('desired_perception', '目标认知', '最希望客户怎样描述我们，最不希望形成什么印象？', '校验表达和服务动作'),
    facet('escalation', '升级条件', '哪些投诉、舆情或表达必须立即升级，由谁处理？', '建立风险响应'),
    facet('recovery', '补救边界', '发生体验问题后，现场可以直接做到什么程度的补救？', '生成可执行恢复方案'),
  ]],
  ['measurement', '数据来源与口径', ['finance', 'operations'], ['role_goals'], '让方案效果可以核对，避免跨口径比较', [
    facet('definitions', '指标口径', '关键指标分别怎么算，最容易被混淆的口径是什么？', '防止错误比较和推导'),
    facet('source_owner', '来源与维护人', '每项关键数据从哪里取、由谁维护？', '路由查询并追责缺数'),
    facet('quality', '数据质量', '哪些数据经常缺失、延迟或只能作为近似？', '标注结论置信度'),
  ]],
  ['learning', '有效做法与失败边界', Object.keys(roles), ['role_goals', 'capacity'], '复用有条件的经验，而非把一次相关性当因果', [
    facet('repeatable_action', '反复有效的做法', '哪种做法至少重复有效过两次，当时共同条件是什么？', '识别可复用机制'),
    facet('failure_conditions', '失败条件', '哪些做法试过没有效果，在哪些条件下失败？', '避免重复踩坑'),
    facet('evidence_strength', '证据强度', '这些经验是数据验证、现场观察还是个人判断？', '控制复用置信度'),
  ]],
];

export const dimensions = definitions.map(([id, title, respondentRoles, dependsOn, decisionImpact, facets]) => ({
  id, title, question: facets[0].question, respondentRoles, dependsOn, decisionImpact, facets,
}));

const sameScope = (item, scope) => item.scope?.projectId === scope.projectId
  && (!item.scope?.venueNames?.length || (scope.venueNames || []).every(v => item.scope.venueNames.includes(v)));

export function buildKnowledgeMap(knowledge, scope, role = 'owner') {
  const selected = roles[role] ? role : 'owner';
  const cells = dimensions.map(d => {
    const evidence = (knowledge.implicitItems || []).filter(item => item.status === 'confirmed' && item.dimensionId === d.id && sameScope(item, scope) && (d.id !== 'role_goals' || item.roleId === selected));
    const tasks = (knowledge.gaps || []).filter(item => item.dimensionId === d.id && sameScope(item, scope) && (d.id !== 'role_goals' || item.roleId === selected));
    const coveredFacetIds = [...new Set(evidence.map(item => item.facetId).filter(id => d.facets.some(f => f.id === id)))];
    const pendingFacetIds = [...new Set(tasks.filter(item => ['open', 'asking', 'review_pending'].includes(item.status)).map(item => item.facetId).filter(Boolean))];
    const status = coveredFacetIds.length === d.facets.length ? 'decision_ready'
      : evidence.length ? 'partial'
      : tasks.some(t => t.status === 'review_pending') ? 'review_pending'
      : 'unknown';
    return {
      ...d, status, coveredFacetIds, pendingFacetIds,
      evidence: evidence.map(e => ({ id: e.id, facetId: e.facetId || '', statement: e.statement, confirmedAt: e.confirmedAt })),
      taskIds: tasks.map(t => t.id), relevantToRole: d.respondentRoles.includes(selected),
      coverage: { covered: coveredFacetIds.length, total: d.facets.length },
    };
  });
  return {
    schemaVersion: 'enterprise-knowledge-map-v2', role: selected, roleLabel: roles[selected], scope, roles, cells,
    coverage: {
      decisionReady: cells.filter(c => c.status === 'decision_ready').length,
      partial: cells.filter(c => c.status === 'partial').length,
      documented: cells.filter(c => ['partial', 'decision_ready'].includes(c.status)).length,
      total: cells.length,
    },
    boundary: '12个维度只是索引。单条确认记录只形成部分覆盖；decision_ready 表示核心切面已有记录，也仍需结合具体决策检查时效、范围与证据。',
  };
}

export function selectKnowledgeSlots(map, knowledge, limit = 4) {
  const dependencyKnown = id => ['partial', 'decision_ready'].includes(map.cells.find(c => c.id === id)?.status);
  return map.cells
    .filter(cell => cell.status !== 'decision_ready' && cell.dependsOn.every(dependencyKnown))
    .flatMap(cell => {
      const openFacetIds = new Set((knowledge.gaps || []).filter(g => g.dimensionId === cell.id && sameScope(g, map.scope) && g.status !== 'dismissed').map(g => g.facetId));
      const nextFacet = cell.facets.find(f => !cell.coveredFacetIds.includes(f.id) && !openFacetIds.has(f.id));
      return nextFacet ? [{ cell, nextFacet }] : [];
    })
    .sort((a, b) => Number(b.cell.relevantToRole) - Number(a.cell.relevantToRole)
      || Number(['identity', 'goals', 'role_goals'].includes(b.cell.id)) - Number(['identity', 'goals', 'role_goals'].includes(a.cell.id)))
    .slice(0, limit)
    .map(({ cell, nextFacet }) => ({
      dimensionId: cell.id, facetId: nextFacet.id, facetTitle: nextFacet.title,
      roleId: map.role, knowledgeTrack: 'enterprise',
      statement: `补齐${cell.title}：${nextFacet.title}`, question: nextFacet.question,
      decisionImpact: nextFacet.decisionUse || cell.decisionImpact, whyNeeded: nextFacet.decisionUse || cell.decisionImpact,
      expectedAnswer: '说眼下最确定的一点或一个实际例子；不知道可明确说未知，不要求完整填表',
      respondentRoles: cell.respondentRoles, acquisitionRoute: 'operator', scope: map.scope,
      priority: ['identity', 'goals', 'role_goals'].includes(cell.id) ? 'high' : 'normal',
      assessment: { impact: 5, urgency: 3, reuse: 5, answerCost: 2 },
    }));
}
