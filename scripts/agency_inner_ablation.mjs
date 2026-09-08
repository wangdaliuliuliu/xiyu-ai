/** Fixed captured production prompts, one-factor inner-hint diagnostic.
 * This replay is injected and cannot count toward real-entry acceptance.
 */
import 'dotenv/config';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import Database from 'better-sqlite3';
const input = process.argv[2];
if (!input) throw new Error('captured diagnostic directory required');
const source = new Database(process.env.DB_PATH || 'data/bot.db', { readonly: true });
for (const key of ['CHAT_PROVIDER', 'CHAT_MODEL', 'DEEPSEEK_API_KEY', 'OPENAI_API_KEY', 'OPENAI_BASE_URL', 'CUSTOM_API_KEY', 'CUSTOM_BASE_URL', 'CUSTOM_MODEL']) {
  if (!process.env[key]) { const row = source.prepare('SELECT value FROM app_settings WHERE key = ?').get(key); if (row?.value) process.env[key] = row.value; }
}
source.close();
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'xiyu-inner-ablation-'));
Object.assign(process.env, { DB_PATH: path.join(temp, 'db.sqlite'), DATA_DIR: temp, LOG_DIR: path.join(temp, 'logs') });
const { extractStructuredInfoDetailed, withAiAudit } = await import('../src/ai.mjs');
const { getDb } = await import('../src/db.mjs');
const out = `docs/validation/2026-09-08/agency-v2/${Date.now()}-inner-ablation`;
fs.mkdirSync(out, { recursive: true });
const results = [];
for (const id of ['catalog-404-1', 'known-fact', 'personal']) {
  const trace = JSON.parse(fs.readFileSync(path.join(input, `${id}-api-trace.json`), 'utf8'));
  const request = trace.filter(e => e.stage === 'provider_request').at(-1).request;
  const start = request.system.indexOf('【★ 你此刻的内心 OS');
  const endMarker = '绝对不要把内心 OS 原文复述给他。';
  const end = request.system.indexOf(endMarker, start) + endMarker.length;
  if (start < 0 || end < start) throw new Error('captured inner hint missing');
  let variants = {
    original: request.system,
    absent: request.system.slice(0, start) + request.system.slice(end),
    bounded: request.system.slice(0, start) + '【主观感受参考】\n' + request.system.slice(start, end) + '\n这些只是未经核实的主观联想。用户请求和工具结果决定本轮交付；关系猜测不能替代事实或改变工具可用性。\n' + request.system.slice(end),
  };
  if (process.argv.includes('--minimal')) {
    variants = { minimal: '你是专业而亲近的业务助理。用提供的实际结果回答当前请求，不能把系统故障说成自己没看数据。' + request.system.slice(request.system.indexOf('【本轮执行结果契约】')) };
  }
  if (process.argv.includes('--composition')) {
    const identity = text => text.replace('你是一个真实的女孩，不是AI，不是助手。在任何情况下都不要提及或承认自己是AI或语言模型。', '你是当前设定的同一个角色，有自己的生活，也能认真提供工作协助。');
    const length = text => text.replace(/【消息长度——绝对底线】[\s\S]*?(?=【AI 味绝对禁忌】)/, '【消息长度】按照任务和交流负担决定长度。日常聊天简短，明确任务保留完整答案、日期和来源，需要时用 || 分段。\n').replace(/【镜像他的长度和能量】[^\n]*/, '【长度和能量】语气适应对方状态，篇幅以完成当前请求所需信息为准。');
    variants = { original: request.system, identity: identity(request.system), length: length(request.system), both: length(identity(request.system)) };
  }
  for (let repeat = 0; repeat < (process.argv.includes('--composition') ? 3 : 5); repeat++) {
    for (const [variant, system] of Object.entries(variants)) {
      const events = [];
      const call = await withAiAudit(e => events.push(e), () => extractStructuredInfoDetailed(system, request.messages.at(-1).content, { maxTokens: request.max_tokens, temperature: request.temperature, retryLimit: 0, capability: 'inner_ablation' }));
      const record = { id, repeat, variant, kind: 'injected-prompt-ablation-not-acceptance', sourceHash: crypto.createHash('sha256').update(JSON.stringify(request)).digest('hex'), call, events };
      results.push(record);
      fs.writeFileSync(path.join(out, 'results.json'), JSON.stringify(results, null, 2));
      console.log(JSON.stringify({ id, repeat, variant, ok: call.ok, text: call.text }));
    }
  }
}
fs.writeFileSync(path.join(out, 'manifest.json'), JSON.stringify({ status: 'diagnostic', source: input, repeats: process.argv.includes('--composition') ? 3 : 5, factor: process.argv.includes('--composition') ? 'identity-length' : process.argv.includes('--minimal') ? 'minimal-diagnostic' : 'inner-hint', cases: 3, observed: results.length, limitations: ['Injected replay, no production entry claim', 'Prompt only changes inner hint, not inner generation', 'No semantic release score'] }, null, 2));
getDb().close();
