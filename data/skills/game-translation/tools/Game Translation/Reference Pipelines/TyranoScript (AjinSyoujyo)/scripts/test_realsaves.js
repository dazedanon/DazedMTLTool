// Replay every real save slot through the shipping remap against the 1.0.2 build.
//   ELECTRON_RUN_AS_NODE=1 ajin_syoujyo.exe realsaves.js <save.sav> <scenario dir>
const fs = require('fs');
const path = require('path');

const COMPAT = fs.readFileSync(
  path.join(process.cwd(), 'tools', 'patch_src', 'save_compat.js'), 'utf8');

function declaration(opener) {
  const at = COMPAT.indexOf(opener);
  if (at < 0) throw new Error('not found: ' + opener);
  let depth = 0;
  for (let j = COMPAT.indexOf('{', at); j < COMPAT.length; j++) {
    if (COMPAT[j] === '{') depth++;
    else if (COMPAT[j] === '}' && --depth === 0) return COMPAT.slice(at, j + 1);
  }
  throw new Error('unbalanced: ' + opener);
}
function assignment(opener) {
  const at = COMPAT.indexOf(opener);
  return COMPAT.slice(at, COMPAT.indexOf(';', at) + 1);
}
const remap = new Function([
  assignment('var DRIFT ='),
  assignment('var CLEARS ='),
  assignment('var WAITS ='),
  declaration('function normalise'),
  declaration('function messageAt'),
  declaration('function byMessage'),
  declaration('function ordinalOf'),
  declaration('function remap'),
  'return remap;',
].join('\n'))();

function parseScenario(text) {
  const out = [];
  const rows = text.split('\n');
  let inComment = false;
  for (let i = 0; i < rows.length; i++) {
    let line = rows[i].trim();
    const first = line.substr(0, 1);
    if (inComment === true && line === '*/') { inComment = false; continue; }
    if (line === '/*') { inComment = true; continue; }
    if (inComment || first === ';') continue;
    if (first === '#') { out.push({ line: i, name: 'chara_ptext' }); continue; }
    if (first === '*') { out.push({ line: i, name: 'label', val: line }); continue; }
    if (first === '@') { out.push({ line: i, name: line.substr(1).split(' ')[0] }); continue; }
    if (first === '_') line = line.substring(1);
    let textBuf = '', tagStr = '', inTag = false, depth = 0;
    for (const c of line) {
      if (inTag) {
        if (c === ']') {
          if (--depth === 0) {
            inTag = false;
            out.push({ line: i, name: tagStr.split(' ')[0].trim(), val: tagStr });
            tagStr = '';
          } else tagStr += c;
        } else if (c === '[') { depth++; tagStr += c; }
        else tagStr += c;
      } else if (c === '[') {
        depth++; inTag = true;
        if (textBuf !== '') { out.push({ line: i, name: 'text', val: textBuf }); textBuf = ''; }
      } else textBuf += c;
    }
    if (textBuf !== '') out.push({ line: i, name: 'text', val: textBuf });
  }
  return out;
}

const raw = fs.readFileSync(process.argv[2], 'utf8');
const slots = JSON.parse(unescape(raw)).data;
const root = process.argv[3];

slots.forEach((slot, index) => {
  const stat = slot && slot.stat;
  if (!stat || !stat.current_scenario) return;
  const file = path.join(root, stat.current_scenario);
  if (!fs.existsSync(file)) {
    console.log(`slot ${index}: ${stat.current_scenario} is gone from this build`);
    return;
  }
  const tags = parseScenario(fs.readFileSync(file, 'utf8'));
  const saved = slot.current_order_index;
  const mark = slot.__compat && typeof slot.__compat.line === 'number'
    ? slot.__compat
    : { line: stat.current_line };
  if (typeof stat.current_message_str === 'string') mark.message = stat.current_message_str;

  const fixed = remap(tags, saved, mark);
  const landsRaw = tags[saved + 1];
  const lands = tags[fixed + 1];
  console.log(`slot ${index}  ${stat.current_scenario}  saved index ${saved} (line ${mark.line}` +
    (mark.ordinal !== undefined ? `, ordinal ${mark.ordinal}, [${mark.name}]` : ', no stamp') + ')');
  console.log(`   without remap -> [${landsRaw ? landsRaw.name : 'nothing'}] at line ${landsRaw ? landsRaw.line : '-'}`);
  console.log(`   with remap    -> [${lands ? lands.name : 'nothing'}] at line ${lands ? lands.line : '-'}` +
    `   ${lands && lands.name === (mark.name || 's') ? 'OK' : 'CHECK'}`);
});
