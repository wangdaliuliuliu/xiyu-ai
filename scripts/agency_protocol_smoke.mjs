import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {
  parseStructuredJson,
  validateAppraisalProposal,
  validatePlanProposal,
  validateFeedbackProposal,
  buildSemanticKey,
  buildAgencyAppraisalPrompt,
  buildAgencyPlanPrompt,
  buildAgencyContinuationPrompt,
  decisionFeatures,
  getAgencyPromptBinding,
  __resetAgencyPromptCacheForTest,
  compactAgencyResultRefs,
  mergeAgencyEvidenceRefs,
  buildAgencyContinuityKey,
} from '../src/agency_protocol.mjs';

assert.deepEqual(parseStructuredJson('```json\n{"shouldAct":true}\n```').value, { shouldAct: true });
assert.equal(parseStructuredJson('前言\n{"shouldAct":true}\n结尾').ok, true);
assert.equal(parseStructuredJson('not json').ok, false);

const appraisal = validateAppraisalProposal({ shouldAct: true, domain: 'work', desiredChange: '确认东大店客流口径并推进转化判断', appraisalSummary: '有销售和客流证据，但口径未知', basisRefs: ['sales:2026-09-02', 'traffic:2026-09-02'], priorityClass: 'high', confidence: 0.9, needsUserInput: true });
assert.equal(appraisal.ok, true);
assert.equal(validateAppraisalProposal({ shouldAct: true, domain: 'work', desiredChange: '无证据', confidence: 0.9 }).ok, false);

const plan = validatePlanProposal({ actionType: 'contact_text', strategySummary: '先说发现，再只问统计范围', inputRefs: ['traffic:2026-09-02'], expectedEffect: '口径确认后继续计算', needsUserInput: true, completionCriteria: ['问题送达'], nextIfAnswered: 'continue', nextIfUnanswered: 'wait', dedupKey: 'traffic-scope-v1', shouldContact: true });
assert.equal(plan.ok, true);
assert.equal(validatePlanProposal({ actionType: 'contact_text', strategySummary: 'x', dedupKey: 'x', shouldContact: false }).value.shouldContact, true);
assert.equal(validateFeedbackProposal({ kind: 'no_response_observed', nextState: 'waiting_user', shouldContinue: true, confidence: 0.8 }).ok, true);
assert.equal(buildSemanticKey({ domain: 'work', desiredChange: '  东大店销售  ', basisRefs: ['b', 'a'] }), buildSemanticKey({ domain: 'work', desiredChange: '东大店销售', basisRefs: ['a', 'b'] }));
assert.match(buildAgencyAppraisalPrompt({ trigger: 'test' }), /评估协议/);
assert.match(buildAgencyPlanPrompt({}, appraisal.value), /动作协议/);
assert.match(buildAgencyContinuationPrompt({}, appraisal.value, { status: 'complete' }), /工具续接/);
assert.equal(validatePlanProposal({ actionType: 'contact_media', strategySummary: '发情节照片', dedupKey: 'm1' }, { capabilities: { contact_media: false } }).reason, 'capability_unavailable:contact_media');
assert.equal(validatePlanProposal({ actionType: 'contact_media', strategySummary: '发情节照片', dedupKey: 'm2' }, { capabilities: { contact_media: true } }).ok, true);
assert.equal(decisionFeatures({ appraisal: appraisal.value }).sourceReady, true);

const binding = getAgencyPromptBinding();
assert.equal(binding.status, 'bound');
assert.equal(binding.schemaVersion, 'agency-prompts-v1');
assert.match(binding.promptVersion, /^agency-production-/);
assert.match(binding.sha256, /^[a-f0-9]{64}$/);
const originalCwd = process.cwd();
const unrelatedCwd = fs.mkdtempSync(path.join(os.tmpdir(), 'xiyu-agency-cwd-'));
process.chdir(unrelatedCwd);
__resetAgencyPromptCacheForTest();
assert.equal(getAgencyPromptBinding().sha256, binding.sha256, 'prompt binding must not depend on process cwd');
process.env.XIYU_AGENCY_PROMPT_PATH = path.join(unrelatedCwd, 'missing.json');
__resetAgencyPromptCacheForTest();
assert.throws(() => getAgencyPromptBinding(), /agency_prompt_unavailable/);
delete process.env.XIYU_AGENCY_PROMPT_PATH;
process.chdir(originalCwd);
__resetAgencyPromptCacheForTest();
const toolRefs = compactAgencyResultRefs([{ kind: 'enterprise_knowledge', summary: { venue: '东坝店', reception_traffic: 201 } }], { actionType: 'lookup' });
assert.match(toolRefs[0], /reception_traffic/);
assert.deepEqual(mergeAgencyEvidenceRefs(['source:9753'], ['source:9753', ...toolRefs]).slice(0, 1), ['source:9753']);
assert.equal(
  buildAgencyContinuityKey({ domain: 'work', desiredChange: '先查资料', basisRefs: ['old'] }, { selectedCandidateType: 'business_delivery', sourceRefs: ['event:9754'] }),
  buildAgencyContinuityKey({ domain: 'work', desiredChange: '基于新资料交付判断', basisRefs: ['new'] }, { selectedCandidateType: 'business_delivery', sourceRefs: ['event:9754'] }),
  'new evidence must keep the same intention continuity key',
);

console.log(JSON.stringify({ status: 'passed', checks: 23, promptVersion: binding.promptVersion, promptSha256: binding.sha256 }));
