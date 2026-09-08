// Parse only: never execute a game script. Acorn ships inside Node 22.
const fs = require('fs');
const acorn = require('internal/deps/acorn/acorn/dist/acorn');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const results = input.map(({name, source}) => {
  const ast = acorn.parse(source, {ecmaVersion: 'latest', sourceType: 'script', locations: true, allowReturnOutsideFunction: true});
  const literals = [];
  const visit = (n, ancestors = []) => {
    if (!n || typeof n !== 'object') return;
    if (n.type === 'Literal' && typeof n.value === 'string') {
      literals.push({start:n.start, end:n.end, text:n.value, quote:source[n.start], line:n.loc.start.line,
        parent:ancestors.at(-1)?.type, context:source.slice(ancestors.at(-1)?.start ?? n.start, ancestors.at(-1)?.end ?? n.end).slice(0,500)});
    } else if (n.type === 'TemplateLiteral') {
      // Each static fragment gets its own exact span; expressions are never editable.
      for (const q of n.quasis) literals.push({start:q.start, end:q.end, text:q.value.cooked ?? q.value.raw,
        raw:q.value.raw, quote:'`', fragment:true, line:q.loc.start.line, parent:'TemplateLiteral',
        context:source.slice(n.start,n.end).slice(0,500)});
    }
    for (const [key,value] of Object.entries(n)) {
      if (['loc','start','end'].includes(key)) continue;
      if (Array.isArray(value)) for (const c of value) visit(c,[...ancestors,n]);
      else if (value && typeof value === 'object') visit(value,[...ancestors,n]);
    }
  };
  visit(ast);
  // JS offsets are UTF-16, Python indexes Unicode code points.
  for (const l of literals) {
    l.start = [...source.slice(0,l.start)].length;
    l.end = [...source.slice(0,l.end)].length;
  }
  return {name,literals};
});
process.stdout.write(JSON.stringify(results));
