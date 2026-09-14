/* Verify the local import closure of the installed project without shell interpolation. */
import fs from 'node:fs';
import path from 'node:path';

const rootValue = process.env.PROJECT_ROOT;
const entryValue = process.env.ENTRY_FILE;
if (!rootValue || !entryValue) {
  console.error('static_closure_input_missing');
  process.exit(2);
}

const root = path.resolve(rootValue);
const entry = path.resolve(entryValue);
const queue = [[entry, 'scripts/agency_online_shadow_smoke.mjs']];
const seen = new Set();
const missing = [];
const patterns = [
  /\b(?:import|export)\s+(?:[\s\S]*?\sfrom\s*)?["'](\.[^"']+)["']/g,
  /\bimport\s*\(\s*["'](\.[^"']+)["']\s*\)/g,
];

const resolveLocal = (base, specifier) => {
  const virtual = path.normalize(path.join(path.dirname(base), specifier));
  const candidates = [
    virtual,
    virtual + '.mjs',
    virtual + '.js',
    path.join(virtual, 'index.mjs'),
    path.join(virtual, 'index.js'),
  ];
  return candidates.find(candidate => fs.existsSync(path.join(root, candidate))) || null;
};

while (queue.length) {
  const [readPath, virtualPath] = queue.shift();
  if (seen.has(virtualPath)) continue;
  seen.add(virtualPath);
  let source;
  try {
    source = fs.readFileSync(readPath, 'utf8');
  } catch (error) {
    missing.push(virtualPath + ' -> read failed: ' + error.message);
    continue;
  }
  for (const pattern of patterns) {
    pattern.lastIndex = 0;
    for (const match of source.matchAll(pattern)) {
      const resolved = resolveLocal(virtualPath, match[1]);
      if (!resolved) {
        missing.push(virtualPath + ' -> ' + match[1]);
      } else {
        queue.push([path.join(root, resolved), resolved]);
      }
    }
  }
}

if (missing.length) {
  console.error('missing_static_imports=' + missing.length);
  for (const item of missing) console.error(item);
  process.exit(2);
}

console.log('static_import_closure=' + seen.size);
