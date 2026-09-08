/** Read-only source integration probe through the existing production workbench
 * bridge. It does not call the dialogue model, write back candidates, or send.
 * Use only with an SSH tunnel to the workbench service.
 */
import fs from 'node:fs';
import path from 'node:path';
process.env.XIYU_WORKBENCH_CONTEXT_URL ||= 'http://127.0.0.1:4175';
process.env.XIYU_WORKBENCH_CONTEXT_TOKEN ||= 'synthetic-test-only';
process.env.XIYU_WORKBENCH_CONTEXT_ENABLED = 'true';
process.env.XIYU_WORKBENCH_TIMEOUT_MS ||= '20000';
const { getEnterpriseCatalogResult, retrieveEnterpriseResult, buildEnterpriseFactReply } = await import('../src/enterprise_context.mjs');
const out = path.resolve(`docs/validation/2026-09-08/agency-v2/${Date.now()}-live-source-integration`);
fs.mkdirSync(out, { recursive: true });
const catalog = await getEnterpriseCatalogResult({ force: true });
if (catalog.status !== 'complete') throw new Error(`catalog failed: ${JSON.stringify(catalog)}`);
const route = {
  conversationType: 'work', interactionIntent: 'lookup', retrievalNeeded: true, confidence: 1,
  scope: { projectId: catalog.catalog.project.id, venueIds: ['DONGBA'], venueNames: ['东坝'] },
  intent: { topics: ['sales'], metricIds: ['box_office_total'], assetTypes: [], timeRange: '2026-09-02', question: '9月2号东坝销售额是多少' },
};
const result = await retrieveEnterpriseResult(route, { accountId: 9001, catalog: catalog.catalog });
const fact = result.context ? buildEnterpriseFactReply({ message: route.intent.question, route, context: result.context }) : null;
const report = {
  kind: 'real-workbench-source-integration-readonly', at: new Date().toISOString(),
  endpoint: process.env.XIYU_WORKBENCH_CONTEXT_URL, owner: 9001,
  catalog: { status: catalog.status, project: catalog.catalog.project, venueIds: catalog.catalog.venues.map(v => v.id), capabilities: catalog.catalog.capabilities.map(c => c.id || c) },
  retrieve: { status: result.status, stage: result.stage, sourceLookup: result.context?.sourceLookup || null, items: result.context?.items?.map(item => ({ id: item.id, title: item.title, summary: item.summary, refs: item.refs })) || [] },
  fact: fact ? { status: fact.status, matched: fact.matched, reply: fact.reply, requiredTerms: fact.requiredTerms, requiredValues: fact.requiredValues } : null,
  limitations: ['Read-only retrieval through SSH tunnel', 'No dialogue provider, candidate writeback, web auth, WeChat, or outbound delivery', 'accountId is a probe actor and does not grant production authorization'],
};
fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(report, null, 2));
console.log(JSON.stringify({ output: out, catalog: catalog.status, retrieve: result.status, fact: fact?.status || null, reply: fact?.reply || '' }, null, 2));
