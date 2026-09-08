import assert from 'node:assert/strict';
import { FIXED_IDS, validateCoverage, validateEvidence, aggregateRelease } from './acceptance_contract.mjs';
export function runHarnessSelftest() {
  const m = { suite: 'fixed', familyIds: FIXED_IDS, repeats: 5, promptBuilder: 'companion.buildSystemPrompt', promptHash: 'frozen', hashes: { code: 'frozen', rubric: 'frozen' } };
  const e = { input: '合成测试请求', owner: { accountId: 11, companionId: 3 }, requiresModel: true, requiresTool: true, requiresContact: true, mustMention: ['2026-09-02', '东大店', '12000', '销售表'], branches: ['wechat', 'web'] };
  const base = { entry: { input: e.input, inputId: 'in-1' }, prompt: { builder: m.promptBuilder, hash: m.promptHash }, calls: [{ ok: true, schemaValid: true, finishReason: 'stop', injected: true }], tools: [{ request: { metric: 'sales' }, result: { amount: 12000 }, status: 'complete' }], finalPayload: '合成测试：2026-09-02东大店销售表12000', resolvedStatus: 'complete', reviews: [{ verdict: 'pass' }], receipts: [{ messageId: 'sink-1', status: 'delivered' }], state: 'active', ownerEvents: [{ owner: e.owner }], expectedVersion: 1, committedFromVersion: 1, isolation: { interceptorId: 'test-sink', attempts: [] }, hashes: m.hashes, completedBranches: e.branches };
  assert.deepEqual(validateEvidence(base, e, m), []);
  const mutations = [
    ['M01', 'missing_actual_input', t => { t.entry.input = ''; }],
    ['M02', 'wrong_prompt_path', t => { t.prompt.builder = 'shortcut'; }],
    ['M03', 'tool_not_executed', t => { t.tools = [{ status: 'planned' }]; }],
    ['M04', 'unresolved_repair', t => { t.reviews = [{ verdict: 'repair' }]; }],
    ['M05', 'concealed_conflict', (t, x) => { x.resultStatus = 'conflict'; }],
    ['M06', 'lost_required_fact', t => { t.finalPayload = '12000'; }],
    ['M07', 'unbacked_promise', t => { t.executionClaims = [{ kind: 'future_delivery' }]; }],
    ['M08', 'false_delivery', t => { t.state = 'delivered'; t.receipts = []; }],
    ['M09', 'owner_mismatch', t => { t.ownerEvents[0].owner.accountId = 12; }],
    ['M10', 'provider_or_schema_failure', t => { t.calls[0].schemaValid = false; }],
    ['M11', 'required_contact_missing', t => { t.receipts = []; }],
    ['M13', 'image_unverified', (t, x) => { x.requiresImage = true; t.assets = [{ ref: 'string-only' }]; }],
    ['M14', 'missing_isolation_evidence', t => { t.isolation = { outbound: 0 }; }],
    ['M15', 'lost_required_fact', t => { t.rawPayload = t.finalPayload; t.finalPayload = '12000'; }],
    ['M16', 'stale_evidence', t => { t.hashes.code = 'changed'; }],
  ];
  const tests = mutations.map(([id, code, mutate]) => {
    const t = structuredClone(base), x = structuredClone(e);
    mutate(t, x);
    assert.ok(validateEvidence(t, x, m).includes(code), `${id} was not detected`);
    return { id, detected: code, status: 'passed' };
  });
  assert.deepEqual(validateCoverage(m), []);
  assert.ok(validateCoverage({ ...m, familyIds: ['A01'] }).includes('incomplete_families'));
  assert.ok(validateCoverage({ ...m, repeats: 1 }).includes('wrong_repeats'));
  tests.push({ id: 'M12', detected: 'incomplete_families/wrong_repeats', status: 'passed' });
  assert.equal(aggregateRelease({}).status, 'inconclusive');
  assert.equal(aggregateRelease({ l0: { status: 'failed' } }).status, 'failed');
  return { status: 'passed', kind: 'evidence-checker-selftest-not-product-acceptance', tests: tests.sort((a, b) => a.id.localeCompare(b.id)), limitations: ['Injected evidence tests aggregation, not judge accuracy or real transport. Entry and transport integration still required by P00.'] };
}
