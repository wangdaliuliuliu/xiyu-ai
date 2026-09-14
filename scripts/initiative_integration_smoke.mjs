import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(new URL('../src/proactive.mjs', import.meta.url), 'utf8');

assert.match(source, /let timingDecision = null;[\s\S]*timingDecision = evaluateProactive\(companion, \{ enterpriseEvent: event \}\)/);
assert.match(source, /primeEnterpriseCandidates\(account, companion, minuteNow\)/);
assert.match(source, /refresh: false/);
assert.match(source, /minuteNow - item\.minute > PROACTIVE_SLOT_GRACE_MINUTES/);
assert.match(source, /sendProactiveMessageGuarded\(companion, item\.kind, account, \{ enterpriseEvent: event, timingDecision \}\)/);
assert.match(source, /\['normal', 'morning'\]\.includes\(item\.kind\)/);
assert.match(source, /buildInitiativeDecision\([\s\S]*timingDecision: opts\.timingDecision/);
assert.match(source, /photoOpportunity/);
assert.doesNotMatch(source, /items\[pick\.idx\] = \{ \.\.\.items\[pick\.idx\], kind: 'photo' \}/);
assert.match(source, /initiativeDecision\.action === 'send_story_photo'/);
assert.match(source, /let userMessage = \[initiativePrompt\(initiativeDecision\), userMessageBase\]/);
assert.match(source, /initiativeReplyIssue\(initiativeDecision, reply\)/);
assert.doesNotMatch(source, /我同事真的服了|外卖怎么还没到啊|刷到个视频笑死/);
assert.match(source, /保留本次已选目的和真实事实/);
assert.match(source, /totalStickers\+\+;\s*sentAnySegment = true;/);
assert.match(source, /recordInitiative\(deliveryIssue \|\| !agencyReceiptCommitted \|\| deliveryState !== 'delivered' \? 'partial' : 'delivered'/);

console.log(JSON.stringify({
  status: 'passed',
  checks: [
    'timing decision reaches generation',
    'stale scheduled contact expires',
    'initiative prompt gates prose',
    'photo competes as a grounded action instead of a fixed schedule item',
    'fabricated examples removed',
    'continuity preserved during dedup',
    'image delivery counted after success',
    'delivery receipt persisted',
  ],
}));
