import 'dotenv/config';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import Database from 'better-sqlite3';
const workbench = 'E:/Yuanqu-Operations-Workbench/weekly-ops-entry';
const root = fs.mkdtempSync(path.join(os.tmpdir(),'enterprise-routing-'));
const runtime = path.join(root,'runtime'); fs.mkdirSync(runtime);
for (const file of fs.readdirSync(path.join(workbench,'data/runtime-state')).filter(f=>f.endsWith('.json'))) fs.copyFileSync(path.join(workbench,'data/runtime-state',file),path.join(runtime,file));
const db = new Database(process.env.DB_PATH || 'data/bot.db',{readonly:true});
await db.backup(path.join(root,'bot.db')); db.close();
process.env.DB_PATH = path.join(root,'bot.db');
process.env.WEEKLY_OPS_RUNTIME_STATE_DIR = runtime;
process.env.XIYU_WORKBENCH_ACTIVE_TASKS_PATH = path.join(root,'tasks.json');
process.env.XIYU_WORKBENCH_OUTBOX_PATH = path.join(root,'outbox.json');
process.env.XIYU_WORKBENCH_TIMEOUT_MS = '5000';
const backend = await import(pathToFileURL(path.join(workbench,'backend/feishu-sync-server.mjs')));
await new Promise(resolve=>backend.server.listen(0,'127.0.0.1',resolve));
const base = `http://127.0.0.1:${backend.server.address().port}`;
process.env.XIYU_WORKBENCH_CONTEXT_URL = base;
const bridge = await import('../src/enterprise_context.mjs');
const report = { root, checks:[], samples:[] };
const request = async (url,method='GET',body) => {
  const r = await fetch(base+url,{method,headers:{'content-type':'application/json'},body:body ? JSON.stringify(body) : undefined});
  const data = await r.json(); assert.ok(r.ok,JSON.stringify(data)); return data;
};
const scope = {projectId:'yuanqu-vr',venueNames:['东坝']};
try {
  fs.writeFileSync(path.join(runtime,'knowledge.json'),JSON.stringify({__runtimeState:1,revision:1,data:{implicitItems:[],gaps:[]}}));
  const initial = await backend.refreshKnowledgeGaps({scope,useModel:false,roleId:'finance'});
  assert.deepEqual(initial.created.map(g=>g.dimensionId),['identity']);
  const gap = initial.created[0];
  const candidate = (await request('/api/intelligence/candidates','POST',{candidateType:'implicit_knowledge_candidate',statement:'验证样本：我们为家庭提供线下体验服务，不承接定制硬件研发。',scope,knowledgeGapId:gap.id,source:{channel:'isolated_probe',quote:'验证样本：我们为家庭提供线下体验服务，不承接定制硬件研发。'}})).candidate;
  assert.ok(candidate?.id);
  let map = (await request('/api/knowledge/map?venue=东坝&role=finance')).map;
  assert.equal(map.coverage.documented,0);
  await request(`/api/intelligence/candidates/${candidate.id}`,'PUT',{reviewStatus:'accepted'});
  await request(`/api/intelligence/candidates/${candidate.id}/apply`,'POST',{target:'implicit_knowledge'});
  map = (await request('/api/knowledge/map?venue=东坝&role=finance')).map;
  assert.equal(map.cells.find(c=>c.id==='identity').status,'partial');
  assert.equal(map.cells.find(c=>c.id==='identity').coverage.covered,1);
  const next = await backend.refreshKnowledgeGaps({scope,useModel:false,roleId:'finance'});
  assert.ok(next.created.some(g=>g.dimensionId==='goals'));
  assert.ok(next.created.some(g=>g.dimensionId==='identity' && g.facetId==='core_value'));
  const other = (await request('/api/knowledge/map?venue=中影&role=finance')).map;
  assert.equal(other.coverage.documented,0);
  report.checks.push('knowledge answer-review-map-next-slot and scope isolation');
  if (process.argv.includes('--live')) {
    for (const message of ['查一下9月2号东坝店销售额是多少','查一下9月2号东大店销售额是多少','查一下9月2日东坝触达人数']) {
      const turn = await bridge.prepareEnterpriseContext({message,accountId:'1',companionId:'routing-probe'});
      const fact = bridge.buildEnterpriseFactReply({message,route:turn.route,context:turn.context});
      report.samples.push({message,route:turn.route,source:turn.context?.sourceLookup,fact});
      assert.ok(['work','mixed'].includes(turn.route?.conversationType));
      if (message.includes('东大')) assert.equal(turn.context?.sourceLookup?.status,'clarification');
      else if (message.includes('销售额')) { assert.equal(turn.context?.sourceLookup?.status,'complete'); assert.equal(fact?.requiredValues?.[0]?.value,266); assert.equal(turn.context.sourceLookup.budget.documents,1); }
      else assert.ok(['complete','incomplete'].includes(turn.context?.sourceLookup?.status));
    }
    report.checks.push('real semantic API and two live Feishu sources');
  }
  report.status='passed'; console.log(JSON.stringify(report,null,2));
} finally {
  fs.writeFileSync(path.join(root,'report.json'),JSON.stringify(report,null,2));
  backend.server.close();
}
