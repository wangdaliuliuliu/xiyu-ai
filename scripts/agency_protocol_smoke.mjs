import assert from 'node:assert/strict';
import {
  parseStructuredJson,
  validateAppraisalProposal,
  validatePlanProposal,
  validateFeedbackProposal,
  buildSemanticKey,
  buildAgencyAppraisalPrompt,
  buildAgencyPlanPrompt,
  decisionFeatures,
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
assert.equal(decisionFeatures({ appraisal: appraisal.value }).sourceReady, true);

console.log(JSON.stringify({ status: 'passed', checks: 11 }));
