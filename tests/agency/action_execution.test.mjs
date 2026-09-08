/* global process */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

test('preparation actions execute through adapters and never remain planned', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xiyu-agency-actions-'));
  process.env.DB_PATH = path.join(root, 'bot.db');
  const db = await import('../../src/db.mjs');
  const { runAgencyCycle } = await import('../../src/proactive.mjs');
  const row = db.getDb().prepare('INSERT INTO companions (user_id, bot_id, name) VALUES (NULL, ?, ?)').run('action-bot', '动作角色');
  const companionId = Number(row.lastInsertRowid);
  const owner = { accountId: 17, companionId };
  const actionTypes = ['lookup', 'analyze', 'research', 'prepare_media', 'wait'];
  const executed = [];
  for (const [index, actionType] of actionTypes.entries()) {
    let call = 0;
    const extract = async () => {
      call += 1;
      const payload = call === 1
        ? { shouldAct: true, domain: actionType === 'research' ? 'work' : 'mixed', desiredChange: `执行${actionType}准备`, appraisalSummary: '有明确的准备目标', basisRefs: [`fixture:${actionType}`], priorityClass: 'normal', confidence: 0.9, needsUserInput: false, reconsiderAfterMinutes: 30 }
        : { actionType, strategySummary: `通过${actionType}适配器准备结果`, inputRefs: [`fixture:${actionType}`], expectedEffect: '形成下一步可用结果', needsUserInput: false, completionCriteria: ['动作有明确结果'], nextIfAnswered: 'continue', nextIfUnanswered: 'wait', notBeforeMinutes: 0, expiresAfterMinutes: 60, dedupKey: `fixture-${actionType}-${call}`, shouldContact: false };
      return { ok: true, text: JSON.stringify(payload), usage: { prompt_tokens: 1, completion_tokens: 1 }, provider: 'fixture', model: 'fixture', attempts: 1, fallback: false };
    };
    const deps = { extractStructuredInfoDetailed: extract, now: `2026-09-08T0${actionTypes.indexOf(actionType)}:00:00.000Z` };
    if (actionType !== 'wait') {
      deps[`execute${actionType === 'prepare_media' ? 'PrepareMedia' : actionType[0].toUpperCase() + actionType.slice(1)}`] = async ({ action }) => {
        executed.push(action.actionType);
        return { status: 'complete', resultRefs: [{ kind: action.actionType, status: 'complete', ref: `fixture:${action.actionType}` }] };
      };
    }
    const result = await runAgencyCycle({ ...owner, accountId: owner.accountId + index, mode: 'shadow', decision: { selectedCandidateType: actionType, objective: `完成${actionType}` }, snapshot: { evidence: [`fixture:${actionType}`], capabilities: { [actionType]: true } }, deps });
    assert.equal(result.status, 'prepared', actionType);
    assert.equal(result.action.state, 'prepared', actionType);
    assert.ok(result.action.resultRefs.length >= 1, actionType);
  }
  assert.deepEqual(executed.sort(), ['analyze', 'lookup', 'prepare_media', 'research'].sort());
});

test('missing preparation adapter is an explicit infrastructure failure', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xiyu-agency-action-failure-'));
  process.env.DB_PATH = path.join(root, 'bot.db');
  const db = await import('../../src/db.mjs');
  const { runAgencyCycle } = await import('../../src/proactive.mjs');
  const row = db.getDb().prepare('INSERT INTO companions (user_id, bot_id, name) VALUES (NULL, ?, ?)').run('missing-adapter-bot', '故障角色');
  const companionId = Number(row.lastInsertRowid);
  let call = 0;
  const result = await runAgencyCycle({
    accountId: 18,
    companionId,
    mode: 'shadow',
    decision: { selectedCandidateType: 'research', objective: '查找外部经营案例' },
    snapshot: { evidence: ['fixture:research'], capabilities: { research: true } },
    deps: {
      now: '2026-09-08T05:00:00.000Z',
      extractStructuredInfoDetailed: async () => {
        call += 1;
        const payload = call === 1
          ? { shouldAct: true, domain: 'work', desiredChange: '研究经营案例', appraisalSummary: '有研究目标', basisRefs: ['fixture:research'], priorityClass: 'normal', confidence: 0.9, needsUserInput: false, reconsiderAfterMinutes: 30 }
          : { actionType: 'research', strategySummary: '执行研究', inputRefs: ['fixture:research'], expectedEffect: '得到有日期的案例', needsUserInput: false, completionCriteria: ['有来源'], nextIfAnswered: 'continue', nextIfUnanswered: 'wait', notBeforeMinutes: 0, expiresAfterMinutes: 60, dedupKey: 'fixture-missing-research', shouldContact: false };
        return { ok: true, text: JSON.stringify(payload), usage: { prompt_tokens: 1, completion_tokens: 1 }, provider: 'fixture', model: 'fixture', attempts: 1, fallback: false };
      },
    },
  });
  assert.equal(result.status, 'infra_failure');
  assert.equal(result.action.state, 'failed');
  assert.equal(result.intention.state, 'suspended');
  assert.match(result.error, /research_adapter_not_supplied/);
});

test('contact_media is rejected when the capability snapshot does not allow it', async () => {
  const db = await import('../../src/db.mjs');
  const { runAgencyCycle } = await import('../../src/proactive.mjs');
  const row = db.getDb().prepare('INSERT INTO companions (user_id, bot_id, name) VALUES (NULL, ?, ?)').run('media-capability-bot', '媒体能力角色');
  const companionId = Number(row.lastInsertRowid);
  let call = 0;
  const result = await runAgencyCycle({
    accountId: 19,
    companionId,
    mode: 'shadow',
    decision: { selectedCandidateType: 'relationship_opener', objective: '用一张图创造共同体验' },
    snapshot: { evidence: ['fixture:no-media'], capabilities: { contact_media: false } },
    deps: {
      now: '2026-09-08T06:00:00.000Z',
      extractStructuredInfoDetailed: async () => {
        call += 1;
        const payload = call === 1
          ? { shouldAct: true, domain: 'personal', desiredChange: '准备一次有情节的图片分享', appraisalSummary: '关系动念成立', basisRefs: ['fixture:no-media'], priorityClass: 'normal', confidence: 0.9, needsUserInput: false, reconsiderAfterMinutes: 30 }
          : { actionType: 'contact_media', strategySummary: '发送图片', inputRefs: ['fixture:no-media'], expectedEffect: '形成共同体验', needsUserInput: false, completionCriteria: ['实际送达'], nextIfAnswered: 'continue', nextIfUnanswered: 'wait', notBeforeMinutes: 0, expiresAfterMinutes: 60, dedupKey: 'fixture-no-media', shouldContact: true };
        return { ok: true, text: JSON.stringify(payload), usage: { prompt_tokens: 1, completion_tokens: 1 }, provider: 'fixture', model: 'fixture', attempts: 1, fallback: false };
      },
    },
  });
  assert.equal(result.status, 'inconclusive');
  assert.equal(result.error, 'capability_unavailable');
  assert.equal(db.listAgencyActions({ accountId: 19, companionId }).length, 0);
});
