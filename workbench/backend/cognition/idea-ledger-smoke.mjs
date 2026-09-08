import assert from 'node:assert/strict';
import { ideaSemanticKey, normalizeDailyIdeas, server } from '../feishu-sync-server.mjs';

const base = { venue:'东坝', problemScope:'工作日傍晚空闲', causalHypothesis:'年轻上班族未被触达', solutionMechanism:'设置下班后短时体验', targetAudience:'年轻上班族' };
assert.equal(ideaSemanticKey(base), ideaSemanticKey({ ...base }));
assert.notEqual(ideaSemanticKey(base), ideaSemanticKey({ ...base, solutionMechanism:'在门口设置三分钟体验' }));
const context = { scope:{ venue:'东坝', asOf:'2026-09-06' }, contextFingerprint:'fixture' };
const [idea] = normalizeDailyIdeas({ ideas:[{ ideaId:'1', title:'下班后来一场', problemScope:base.problemScope, causalHypothesis:base.causalHypothesis, solutionMechanism:base.solutionMechanism, targetAudience:base.targetAudience }] }, context, { headline:'fixture' }, 1);
assert.equal(idea.semanticKey, ideaSemanticKey(base));
assert.equal(idea.problemScope, base.problemScope);
server.close();
console.log(JSON.stringify({ status:'passed', checks:['stable semantic identity','mechanism change creates new identity','normalized idea carries semantic ledger fields'] }));
