import assert from 'node:assert/strict';
import { createCognitionSourcePort } from './source-port.mjs';
import { compileEnterpriseContext } from './context-compiler.mjs';

const source = createCognitionSourcePort({
  catalog: { project: { id: 'yuanqu-vr' } },
  profile: { project: { id: 'yuanqu-vr' }, venues: { 中影: { venueId: 'ZHONGYING', constraints: ['容量待核实'] } } },
  revisions: { profile: 1, workbench: 2 },
});
const context = compileEnterpriseContext({
  source,
  input: { scope: { projectId: 'yuanqu-vr', venueNames: ['中影'] } },
  items: [
    { id: 'fact:tech-museum', assetType: 'operating_fact', epistemicStatus: 'confirmed_operating_fact', summary: '科技馆客流回落', scope: { venueNames: ['中影'] }, sourceRefs: ['weekly:2026-08-15'] },
    { id: 'experience:unverified', assetType: 'experience', epistemicStatus: 'candidate_experience', summary: '只可作为候选', scope: { venueNames: ['东坝'] } },
  ],
  goals: [{ id: 'goal:traffic', title: '提升接待客流', target: 400, scope: { venueNames: ['中影'] }, sourceRefs: ['decision:1'] }],
  decisions: [{ id: 'decision:pilot', decision: '先做周末小规模验证', scope: { venueNames: ['中影'] }, basedOnRefs: ['fact:tech-museum'] }],
  missingInformation: ['具体影响时段'],
  fingerprint: 'smoke-fingerprint',
});

assert.equal(context.schemaVersion, 'enterprise-context-v3');
assert.equal(context.contextVersion, 'enterprise-context-v1');
assert.equal(context.objects.length, 1);
assert.equal(context.confirmedFacts.length, 1);
assert.equal(context.goalsAndDecisions.goals.length, 1);
assert.equal(context.goalsAndDecisions.decisions.length, 1);
assert.equal(context.protocolValidation.ok, true);
assert.deepEqual(context.missingInformation, ['具体影响时段']);
assert.equal(context.capabilitiesAndConstraints.includes('容量待核实'), true);
console.log(JSON.stringify({ ok: true, schemaVersion: context.schemaVersion, legacyVersion: context.contextVersion, objects: context.objects.length, goals: context.goalsAndDecisions.goals.length, decisions: context.goalsAndDecisions.decisions.length }));
