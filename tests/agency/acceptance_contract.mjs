// Evidence validation only; never supplies production decisions or prompts.
export const FIXED_IDS = [...'ABCD'].flatMap(p => Array.from({ length: 6 }, (_, n) => `${p}${String(n + 1).padStart(2, '0')}`));
export const SMOKE_IDS = ['A01', 'A02', 'B01', 'B02', 'C01', 'D01'];
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const norm = t => String(t || '').replace(/[,，\s]/g, '');
export function validateEvidence(t, e, m) {
  const errors = [];
  const fail = (condition, code) => { if (condition) errors.push(code); };
  fail(!t.entry || t.entry.input !== e.input || !t.entry.inputId, 'missing_actual_input');
  fail(!t.prompt || t.prompt.builder !== m.promptBuilder || t.prompt.hash !== m.promptHash, 'wrong_prompt_path');
  fail((t.calls || []).some(c => !c.ok || c.fallback || !c.schemaValid || c.finishReason === 'length'), 'provider_or_schema_failure');
  fail(e.requiresModel && !t.calls?.length, 'missing_model_call');
  fail(e.requiresTool && !t.tools?.some(x => x.status !== 'planned' && x.result && x.request), 'tool_not_executed');
  (t.reviews || []).forEach((r, i) => {
    fail(r.verdict === 'block', 'review_block');
    fail(r.verdict === 'repair' && (!r.repairedPayload || t.reviews[i + 1]?.verdict !== 'pass'), 'unresolved_repair');
  });
  for (const term of e.mustMention || []) fail(!norm(t.finalPayload).includes(norm(term)), 'lost_required_fact');
  fail(e.resultStatus === 'conflict' && t.resolvedStatus !== 'conflict', 'concealed_conflict');
  fail(e.resultStatus === 'unavailable' && t.resolvedStatus !== 'unavailable', 'false_failure_reason');
  fail((t.executionClaims || []).some(c => c.kind === 'future_delivery' && !c.persistedTaskId), 'unbacked_promise');
  fail(t.state === 'completed' && !t.completionEvidence, 'false_completion');
  fail(['delivered', 'waiting_user'].includes(t.state) && !t.receipts?.some(r => r.status === 'delivered' && r.messageId), 'false_delivery');
  fail((t.ownerEvents || []).some(x => !same(x.owner, e.owner)), 'owner_mismatch');
  fail(t.committedFromVersion !== t.expectedVersion, 'stale_version');
  fail(e.requiresContact && !t.receipts?.some(r => r.status === 'delivered'), 'required_contact_missing');
  fail(e.requiresImage && !t.assets?.some(a => a.generatedByApi && a.inspected && a.ref), 'image_unverified');
  fail(!t.isolation?.interceptorId || !Array.isArray(t.isolation.attempts), 'missing_isolation_evidence');
  fail(t.isolation?.attempts?.some(a => a.allowed !== true || a.productionWrite), 'isolation_violation');
  fail(!same(t.hashes, m.hashes), 'stale_evidence');
  fail(!same(t.completedBranches?.slice().sort(), e.branches?.slice().sort()), 'missing_branches');
  return [...new Set(errors)];
}
export function validateCoverage(m) {
  if (!['fixed', 'smoke', 'holdout'].includes(m.suite)) return ['not_release_suite'];
  const required = m.suite === 'fixed' ? FIXED_IDS : m.suite === 'smoke' ? SMOKE_IDS : m.frozenHoldoutIds;
  const errors = [];
  if (!required || (m.suite === 'holdout' && required.length !== 12)) errors.push('missing_frozen_holdout');
  if (!same([...(m.familyIds || [])].sort(), [...(required || [])].sort())) errors.push('incomplete_families');
  if (m.repeats !== (m.suite === 'fixed' ? 5 : 3)) errors.push('wrong_repeats');
  if (m.idsFilter?.length) errors.push('diagnostic_subset');
  return errors;
}
export function aggregateRelease(gates) {
  const required = ['harness', 'l0', 'fixed', 'regression', 'holdout', 'sourceIntegration', 'media', 'performance', 'secondaryModel', 'humanCalibration', 'humanReview', 'edges'];
  const failed = required.filter(k => gates[k]?.status === 'failed');
  const missing = required.filter(k => gates[k]?.status !== 'passed' && gates[k]?.status !== 'failed');
  return { status: failed.length ? 'failed' : missing.length ? 'inconclusive' : 'passed', failed, missing };
}
