// NODE_PATH may point to an existing Acorn installation; do not install one implicitly.
const fs = require('node:fs');
const path = require('node:path');
const acorn = require('acorn');
const report = [];
function walk(node, file) {
  if (!node || typeof node !== 'object') return;
  if (['FunctionDeclaration','FunctionExpression','ArrowFunctionExpression'].includes(node.type)) {
    report.push({path:file, name:node.id?.name || node.type, start:node.loc.start.line,
      end:node.loc.end.line, span:node.loc.end.line - node.loc.start.line + 1});
  }
  for (const child of Object.values(node)) {
    if (Array.isArray(child)) child.forEach(x => walk(x, file));
    else if (child && typeof child === 'object') walk(child, file);
  }
}
function scan(dir) {
  for (const entry of fs.readdirSync(dir, {withFileTypes:true})) {
    const file = path.join(dir, entry.name);
    if (entry.isDirectory()) scan(file);
    else if (/\.(js|mjs|cjs)$/.test(file)) {
      walk(acorn.parse(fs.readFileSync(file, 'utf8'), {ecmaVersion:'latest', sourceType:'module', locations:true}), file);
    }
  }
}
if (process.argv[2] === '--stdin') {
  walk(acorn.parse(fs.readFileSync(0, 'utf8'), {ecmaVersion:'latest', sourceType:'module', locations:true}), process.argv[3] || 'stdin');
} else for (const home of ['studio','tests','tools','native-package']) scan(home);
console.log(JSON.stringify(report));
