// Parse-only companion for MZ adapters. No game code is executed.
// stdin: [{name, source}]; stdout: [{name, literals}].
// Run with Node 22.18.0 --expose-internals, or provide an installed acorn.
const fs = require('fs');
let acorn;
try { acorn = require('acorn'); }
catch (_) {
  try { acorn = require('internal/deps/acorn/acorn/dist/acorn'); }
  catch (_) { throw new Error('Acorn unavailable: use Node --expose-internals (verified on 22.18.0), or install/provide acorn.'); }
}
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
if (!Array.isArray(input)) throw new Error('Expected an array of {name, source} objects');
const results = input.map(({name, source}) => {
  if (typeof name !== 'string' || typeof source !== 'string') throw new Error('name/source must be strings');
  let ast;
  try { ast = acorn.parse(source, {ecmaVersion:'latest', sourceType:'script', locations:true, allowReturnOutsideFunction:true}); }
  catch (e) { throw new Error(`${name}: ${e.message}`); }
  // Acorn offsets use UTF-16; Python splice offsets use Unicode code points.
  const offsets = new Map([[0,0]]);
  let utf16 = 0, codepoints = 0;
  for (const ch of source) {
    utf16 += ch.length;
    offsets.set(utf16, ++codepoints);
  }
  const literals = [];
  const visit = (n, parent = null) => {
    if (!n || typeof n !== 'object') return;
    if (n.type === 'Literal' && typeof n.value === 'string') {
      literals.push({start:n.start,end:n.end,text:n.value,quote:source[n.start],line:n.loc.start.line,
        parent:parent?.type,context:source.slice(parent?.start ?? n.start,parent?.end ?? n.end).slice(0,500)});
    } else if (n.type === 'TemplateLiteral') {
      const tagged = parent?.type === 'TaggedTemplateExpression';
      for (const q of n.quasis) literals.push({start:q.start,end:q.end,text:q.value.cooked,
        raw:q.value.raw,quote:'`',fragment:true,tagged,review_required:tagged || q.value.cooked === null,
        line:q.loc.start.line,parent:'TemplateLiteral',context:source.slice(n.start,n.end).slice(0,500)});
    }
    for (const [key,value] of Object.entries(n)) {
      if (['loc','start','end'].includes(key)) continue;
      if (Array.isArray(value)) for (const child of value) visit(child,n);
      else if (value && typeof value === 'object') visit(value,n);
    }
  };
  visit(ast);
  for (const literal of literals) {
    literal.start = offsets.get(literal.start);
    literal.end = offsets.get(literal.end);
    if (literal.start === undefined || literal.end === undefined) throw new Error(`${name}: invalid UTF-16 boundary`);
  }
  return {name,literals};
});
process.stdout.write(JSON.stringify(results));
