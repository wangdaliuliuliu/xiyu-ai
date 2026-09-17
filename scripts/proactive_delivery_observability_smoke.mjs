/**
 * Proactive delivery observability regression (2026-09-17).
 *
 * Covers three real incidents:
 *   1) 9-15: the schedule marked internal early-exits (collision / no ctx) as sent:true,
 *      so "13 sent" was actually 0 delivered -- the state lied and nothing could alert.
 *      -> assert deliveryOutcome semantics.
 *   2) 9-15 18:10: after an intention was blocked by the outbound gate, the next
 *      opportunity generated again and got blocked again -- pure token waste.
 *      -> assert the pre-generation gate (pure function evaluatePrecheckGate).
 *   3) 9-16/9-17: closed-window skips were silent; the user found out two days later.
 *      -> assert the consecutive-closed counter and its alert threshold.
 *
 * Zero LLM, zero network, zero database: pure logic + source contract only.
 * NOTE: this file is intentionally ASCII-only so it survives transfer over
 * PowerShell/GBK pipes; Chinese literals are written as \uXXXX escapes.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { evaluatePrecheckGate } from '../src/proactive.mjs';

let pass = 0, fail = 0;
const ok = (cond, name) => { if (cond) { pass++; } else { fail++; console.error('  [FAIL]', name); } };

const src = readFileSync(new URL('../src/proactive.mjs', import.meta.url), 'utf8');

// --- 1) sent must not stand in for "delivered" ---------------------------------
{
  ok(/item\.deliveryOutcome = 'failed'/.test(src), 'internal early-exit records deliveryOutcome=failed');
  ok(/item\.deliveryOutcome = 'delivered'/.test(src), 'real delivery records deliveryOutcome=delivered');
  ok(/item\.deliveryOutcome = 'expired'/.test(src), 'expired slot records deliveryOutcome=expired');
  ok(/item\.deliveryOutcome = 'precheck_skip'/.test(src), 'precheck skip records deliveryOutcome=precheck_skip');
  ok(/not_delivered:/.test(src), 'non-delivery feeds the health counter (visible to deadman/diagnostics)');
  // the old "early exit counts as sent" wording must be gone
  const oldPhrase = '\u5185\u90e8\u65e9\u9000\uff08\u649e\u8f66/\u65e0 ctx\uff09\u90fd\u7b97\u4eca\u65e5\u5df2\u5c1d\u8bd5';
  ok(!src.includes(oldPhrase), 'old "early exit counts as sent" logic removed');
  // outcome must persist with the schedule, with a length guard
  ok(/deliveryOutcome: item\.deliveryOutcome\.slice\(0, 40\)/.test(src), 'deliveryOutcome persisted (truncated)');
  ok(/deliveryError: item\.deliveryError\.slice\(0, 80\)/.test(src), 'deliveryError persisted (truncated)');
}

// --- 2) pre-generation gate ---------------------------------------------------
{
  const NOW = 1_700_000_000_000;
  const base = { companionId: 1, intentionId: 'agi_x', planKey: 'plan:1', hasEnterpriseEvent: false, effectiveKind: 'normal', nowMs: NOW };
  const memo = { companionId: 1, intentionId: 'agi_x', planKey: 'plan:1', reason: 'collision_after_retry', at: NOW - 5 * 60_000 };

  ok(evaluatePrecheckGate(memo, base).skip === true, 'same intention + same plan within cooldown -> skip generation');
  ok(evaluatePrecheckGate(memo, { ...base, intentionId: 'agi_y' }).skip === false, 'new intention -> allowed immediately');
  ok(evaluatePrecheckGate(memo, { ...base, planKey: 'plan:2' }).skip === false, 'new plan -> allowed immediately');
  ok(evaluatePrecheckGate(memo, { ...base, companionId: 2 }).skip === false, 'other companion unaffected');

  // NOTE: memo.at is already 5 min old, so ages below are measured from THAT point.
  // +14min after NOW => memo age 19 min (inside the 20 min cooldown) -> skip.
  // +16min after NOW => memo age 21 min (past the cooldown)            -> allowed.
  ok(evaluatePrecheckGate(memo, { ...base, nowMs: NOW + 16 * 60_000 }).skip === false, 'past cooldown -> allowed again');
  ok(evaluatePrecheckGate(memo, { ...base, nowMs: NOW + 14 * 60_000 }).skip === true, 'inside cooldown -> still skipped');
  // 边界：正好落在冷却窗上不应被当作过期（用 age > cooldown，不是 >=）
  ok(evaluatePrecheckGate(memo, { ...base, nowMs: NOW + 15 * 60_000 }).skip === true, 'exactly at cooldown edge -> still skipped');

  ok(evaluatePrecheckGate(memo, { ...base, effectiveKind: 'reminder' }).skip === false, 'anniversary/reminder is exempt');
  ok(evaluatePrecheckGate(memo, { ...base, hasEnterpriseEvent: true }).skip === false, 'enterprise event is exempt');
  ok(evaluatePrecheckGate(memo, { ...base, intentionId: null, planKey: null }).skip === false, 'no fingerprint -> allowed');

  // fail-open: bad input must never lock the companion out of speaking
  ok(evaluatePrecheckGate(null, base).skip === false, 'fail-open: no memory -> allowed');
  ok(evaluatePrecheckGate('not-an-object', base).skip === false, 'fail-open: dirty memory -> allowed');
  ok(evaluatePrecheckGate({ ...memo, at: 'garbage' }, base).skip === false, 'fail-open: bad timestamp -> allowed');
  ok(evaluatePrecheckGate({ ...memo, at: NOW + 60 * 60_000 }, base).skip === false, 'fail-open: future timestamp -> allowed');
  ok(evaluatePrecheckGate(memo, {}).skip === false, 'fail-open: empty args -> allowed');
}

// --- 3) closed-window observability --------------------------------------------
{
  ok(/CHANNEL_CLOSED_KEY = 'proactive_channel_closed_streak'/.test(src), 'closed-window streak has a persisted key');
  ok(/CHANNEL_CLOSED_ALERT_AT = 6/.test(src), 'alert threshold defined (6 consecutive missed opportunities)');
  ok(/noteChannelClosedSkip\(companion\.id, kind\)/.test(src), 'each closed-window skip is counted');
  ok(/clearChannelClosedStreak\(\)/.test(src), 'streak resets on real delivery');
  const alertText = '\u4e3b\u52a8\u901a\u9053\u5df2\u8fde\u7eed';   // "proactive channel has been continuously"
  ok(src.includes(alertText), 'explicit warning text emitted past the threshold');
}

console.log(`proactive_delivery_observability: pass ${pass} fail ${fail}`);
process.exit(fail ? 1 : 0);
