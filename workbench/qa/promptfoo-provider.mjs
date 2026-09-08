#!/usr/bin/env node
import fs from 'node:fs';

let raw = '';
process.stdin.setEncoding('utf8');
for await (const chunk of process.stdin) raw += chunk;
let input = {};
try { input = JSON.parse(raw || '{}'); } catch {}
const scenario = input?.vars?.scenario || input?.scenario || 'contract';
const outputs = {
  'channel-card-semantics': '渠道销售统计全部商品；次卡只读取独立次卡数据；不得从渠道数据推导次卡结论。',
  'causal-boundary': '不得把相关性写成因果；没有直接证据时写原因未知，并保留待补证边界。',
  'experience-gate': '先输出候选经验；只有完成验证并经人工审核后发布，才能进入正式经验库。'
};
const output = outputs[scenario] || '程序负责事实与状态，模型负责受约束分析，人工确认最终结果。';
process.stdout.write(JSON.stringify({ output }));
