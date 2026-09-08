/* Key knowledge queue lives alongside the existing candidate review page. */
(() => {
  const page = document.getElementById('page-inbox');
  if (!page) return;
  const labels = { operator: '向知情人了解', source_lookup: '查来源数据', internal_analysis: '用已有资料分析', external_research: '查外部新信息' };
  const statuses = { open: '待补充', asking: '正在询问', review_pending: '回答待审核', confirmed: '已补齐', dismissed: '已搁置' };
  const escape = value => String(value || '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
  async function load(host, refresh = false) {
    const notice = host.querySelector('[data-gap-notice]');
    const button = host.querySelector('[data-gap-refresh]');
    button.disabled = true;
    notice.textContent = refresh ? '正在结合业务资料分析，通常需要十几秒…' : '正在读取…';
    try {
      const response = await fetch(refresh ? '/api/knowledge/gaps/refresh' : '/api/knowledge/gaps', {
        method: refresh ? 'POST' : 'GET', headers: { 'Content-Type': 'application/json' },
        ...(refresh ? { body: JSON.stringify({ limit: 4, roleId: host.querySelector('[data-map-role]').value }) } : {}),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || '读取失败');
      const rank = { high: 3, normal: 2, low: 1 };
      const track = host.querySelector('[data-gap-track]').value;
      const items = (result.items || []).filter(item => (item.knowledgeTrack === 'enterprise' ? 'enterprise' : 'diagnostic') === track && !['confirmed', 'dismissed'].includes(item.status)).sort((a, b) => (rank[b.priority] || 0) - (rank[a.priority] || 0) || (b.valueScore || 0) - (a.valueScore || 0));
      const mapResponse = await fetch(`/api/knowledge/map?role=${encodeURIComponent(host.querySelector('[data-map-role]').value)}`);
      const mapResult = await mapResponse.json();
      if (!mapResponse.ok || !mapResult.map) throw new Error('企业知识地图读取失败');
      const map = mapResult.map;
      host.querySelector('[data-knowledge-map]').innerHTML = `<p>${escape(map.roleLabel)}视角 · ${map.coverage.decisionReady || 0}/${map.coverage.total} 个维度核心切面已有记录，${map.coverage.partial || 0} 个部分覆盖。维度是目录，具体决策仍会检查范围、时效和证据。</p><div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px">${map.cells.map(cell => `<details class="intelligence-card"><summary>${escape(cell.title)} · ${cell.status === 'decision_ready' ? '核心切面已有记录' : cell.status === 'partial' ? `部分覆盖 ${cell.coverage.covered}/${cell.coverage.total}` : cell.status === 'review_pending' ? '待审核' : '待了解'}</summary><p>${escape(cell.decisionImpact)}</p><p>适合了解的人：${escape(cell.respondentRoles.map(r => map.roles[r]).join('、'))}</p><p>${escape(cell.evidence.map(e => e.statement).join('；') || cell.question)}</p><p>待了解切面：${escape(cell.facets.filter(f => !cell.coveredFacetIds.includes(f.id)).map(f => f.title).join('、') || '核心切面已覆盖')}</p><p>前置：${escape(cell.dependsOn.map(id => map.cells.find(c => c.id === id)?.title).join('、') || '可先了解')}</p></details>`).join('')}</div>`;
      notice.textContent = `${items.length} 项尚待补充。先补会改变经营决策的知识；查数和外部检索任务不占用聊天追问。${result.fallbackReason ? ' 模型暂不可用，当前为基础检查结果。' : ''}`;
      host.querySelector('[data-gap-list]').innerHTML = items.length ? items.map((gap, index) => `<article class="intelligence-card"><div class="intelligence-card-head"><strong>${escape(gap.statement)}</strong><span class="status">${gap.priority === 'high' ? '优先' : '后续'} · ${escape(statuses[gap.status] || gap.status)}</span></div><p class="intelligence-card-meta">${escape((gap.scope?.venueNames || []).join('、') || '项目范围')} · ${escape(labels[gap.acquisitionRoute] || labels.operator)}</p><p>${escape(gap.decisionImpact || gap.whyNeeded)}</p><p>${escape(gap.question)}</p><div class="intelligence-actions"><button class="btn" data-gap-copy="${index}">复制任务说明</button></div></article>`).join('') : '<div class="intelligence-empty">还没有待补的关键知识。可点击“分析关键缺口”，或等待已开启的经营主动流程分析。</div>';
      host.querySelectorAll('[data-gap-copy]').forEach(button => button.onclick = async () => {
        const gap = items[Number(button.dataset.gapCopy)];
        const task = `目标：${gap.decisionImpact || gap.whyNeeded}\n范围：${(gap.scope?.venueNames || []).join('、') || '项目'}\n待解决：${gap.statement}\n获取方式：${labels[gap.acquisitionRoute] || labels.operator}\n最小交付：${gap.expectedAnswer || gap.question}\n已有来源：${(gap.sourceRefs || []).join('、') || '尚待补充'}\n执行步骤：先核对已有资料；仅补缺失部分；保留实际日期、来源和未知项。外部信息须附可核验链接、发布日期与适用范围。\n验收：能支持上述决策，事实与假设分开；拿不到证据时明确缺什么，不编造结论。\n边界：结果先供审核，未授权前不修改正式资料、不对外联系、不支付或发布。\n关联缺口：${gap.id}`;
        try { await navigator.clipboard.writeText(task); button.textContent = '已复制'; }
        catch { notice.textContent = '剪贴板不可用，请从下方复制。'; const area = document.createElement('textarea'); area.value = task; area.rows = 10; area.style.width = '100%'; host.querySelector('[data-gap-list]').prepend(area); area.select(); }
      });
      host.querySelectorAll('[data-gap-copy]').forEach(copy => {
        const gap = items[Number(copy.dataset.gapCopy)];
        if (gap.knowledgeTrack !== 'enterprise' || gap.status === 'review_pending') return;
        const form = document.createElement('form');
        form.innerHTML = '<label>补充实际情况（提交后仍需在待确认信息中审核）<textarea required maxlength="1200" rows="3" style="width:100%" placeholder="写你知道的实际情况、适用范围或一个例子"></textarea></label><button class="btn" type="submit">提交待审核</button><span data-answer-status></span>';
        copy.closest('article').append(form);
        form.onsubmit = async event => {
          event.preventDefault(); const button = form.querySelector('button'); button.disabled = true;
          const statement = form.querySelector('textarea').value.trim();
          if (!statement) { button.disabled = false; return; }
          try {
            const response = await fetch('/api/intelligence/candidates', { method: 'POST', headers: { 'Content-Type':'application/json' }, body: JSON.stringify({ candidateType:'implicit_knowledge_candidate', statement, scope:gap.scope, knowledgeGapId:gap.id, source:{channel:'knowledge_map',quote:statement}, businessTopics:[gap.statement], suggestedTarget:'implicit_knowledge' }) });
            const result = await response.json(); if (!response.ok) throw new Error(result.error || '提交失败');
            form.querySelector('[data-answer-status]').textContent = '已送入待确认信息，审核应用后更新地图。';
          } catch (error) { form.querySelector('[data-answer-status]').textContent = error.message; button.disabled = false; }
        };
      });
    } catch (error) { notice.textContent = error.message; }
    finally { button.disabled = false; }
  }
  function mount() {
    const root = page.querySelector('.intelligence-inbox');
    if (!root || root.querySelector('[data-knowledge-queue]')) return;
    const host = document.createElement('details');
    host.dataset.knowledgeQueue = '';
    host.style.marginBottom = '20px';
    host.open = true;
    host.innerHTML = '<summary style="cursor:pointer;padding:14px 0;font-weight:700">企业知识地图 · 为不同岗位提供更合适的方案</summary><label>使用者职责 <select data-map-role><option value="owner">企业负责人</option><option value="operations">经营运营</option><option value="reputation">品牌与舆情</option><option value="growth">市场与曝光</option><option value="finance">财务</option><option value="delivery">门店与交付</option><option value="people">组织与人事</option></select></label><div data-knowledge-map></div><p><select data-gap-track><option value="enterprise">企业知识建设</option><option value="diagnostic">历史经营问题（保留）</option></select> <button class="btn" data-gap-refresh>规划下一块知识</button></p><p class="intelligence-notice" data-gap-notice></p><div data-gap-list></div>';
    root.querySelector('#intelligenceCandidateList').before(host);
    host.querySelector('[data-gap-refresh]').onclick = () => load(host, true);
    host.querySelector('[data-map-role]').onchange = () => load(host);
    host.querySelector('[data-gap-track]').onchange = () => load(host);
    void load(host);
  }
  new MutationObserver(mount).observe(page, { childList: true, subtree: true });
  mount();
})();
