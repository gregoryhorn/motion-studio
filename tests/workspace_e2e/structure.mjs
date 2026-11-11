// Focused syntax and COMPLETE function-span check using the existing Acorn dependency.
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url), acorn = require('acorn');
let maximum = 0, count = 0;
function walk(node) {
  if (!node || typeof node !== 'object') return;
  if (['FunctionDeclaration', 'FunctionExpression', 'ArrowFunctionExpression'].includes(node.type)) {
    count++;
    const span = node.loc.end.line - node.loc.start.line + 1;
    maximum = Math.max(maximum, span);
    if (span > 300) throw Error('WORKSPACE_FUNCTION_SPAN_EXCEEDED');
  }
  for (const value of Object.values(node)) {
    if (Array.isArray(value)) value.forEach(walk);
    else if (value && typeof value === 'object') walk(value);
  }
}
for (const name of fs.readdirSync('tests/workspace_e2e')) {
  if (!/\.(mjs|js)$/.test(name)) continue;
  const text = fs.readFileSync(path.join('tests/workspace_e2e', name), 'utf8');
  walk(acorn.parse(text, {ecmaVersion:'latest', sourceType:'module', locations:true}));
}
console.log(JSON.stringify({functions:count, maximum, violations:0}));
