// The 1.0.0 -> 1.0.2 remap, measured where a save can actually be taken and
// judged by whether the player lands back in the same moment of the story.
//
// Two corrections over test_remap.js, which walks every element and calls any
// change of line a miss:
//
//   * a save is written while the engine waits, so the resume point is always
//     a [s], [p], [l] or [lr] - the other 90% of elements cannot be one;
//   * after an upstream patch the *right* element legitimately sits on a
//     different line, so "same line" is not the question. "Same text on
//     screen, same kind of wait" is.
//
//   ELECTRON_RUN_AS_NODE=1 game.exe waitpoints.js <old dir> <new dir>
const fs = require('fs');
const path = require('path');

const COMPAT = fs.readFileSync(
  path.join(process.cwd(), 'tools', 'patch_src', 'save_compat.js'), 'utf8');

function declaration(opener) {
  const at = COMPAT.indexOf(opener);
  if (at < 0) throw new Error('save_compat.js no longer has: ' + opener);
  let depth = 0;
  for (let j = COMPAT.indexOf('{', at); j < COMPAT.length; j++) {
    if (COMPAT[j] === '{') depth++;
    else if (COMPAT[j] === '}' && --depth === 0) return COMPAT.slice(at, j + 1);
  }
  throw new Error('unbalanced braces in: ' + opener);
}
function assignment(opener) {
  const at = COMPAT.indexOf(opener);
  if (at < 0) throw new Error('save_compat.js no longer has: ' + opener);
  return COMPAT.slice(at, COMPAT.indexOf(';', at) + 1);
}

const [messageAt, remap] = new Function([
  assignment('var DRIFT ='),
  assignment('var CLEARS ='),
  assignment('var WAITS ='),
  declaration('function normalise'),
  declaration('function messageAt'),
  declaration('function byMessage'),
  declaration('function ordinalOf'),
  declaration('function remap'),
  'return [messageAt, remap];',
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

function walk(dir, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else if (entry.name.endsWith('.ks')) out.push(full);
  }
  return out;
}

const OLD = process.argv[2], NEW = process.argv[3];
const WAIT = { s: 1, p: 1, l: 1, lr: 1 };

// three ways of resolving the same save, so the gain is visible
const MODES = [
  ['no remap        ', null],
  ['line + ordinal  ', mark => ({ v: 1, line: mark.line, ordinal: mark.ordinal, name: mark.name })],
  ['+ message text  ', mark => mark],
];
const tally = MODES.map(() => ({ right: 0, wrong: 0, lost: 0 }));
const misses = [];

for (const oldPath of walk(OLD)) {
  const rel = path.relative(OLD, oldPath);
  const newPath = path.join(NEW, rel);
  if (!fs.existsSync(newPath)) continue;
  const a = parseScenario(fs.readFileSync(oldPath, 'utf8'));
  const b = parseScenario(fs.readFileSync(newPath, 'utf8'));
  if (a.length === b.length) continue;

  for (let i = 0; i < a.length; i++) {
    if (!WAIT[a[i].name]) continue;
    const saved = i - 1;
    let ordinal = 0;
    for (let j = i - 1; j >= 0 && a[j].line === a[i].line; j--) ordinal++;
    const full = { v: 1, line: a[i].line, ordinal: ordinal, name: a[i].name,
                   message: messageAt(a, i) };
    const wantMessage = full.message;

    MODES.forEach(([label, build], m) => {
      const at = build === null ? saved : remap(b, saved, build(full));
      const landed = b[at + 1];
      if (!landed) { tally[m].lost++; return; }
      // the same moment of the story: same kind of wait, same text on screen
      const ok = landed.name === a[i].name && messageAt(b, at + 1) === wantMessage;
      if (ok) tally[m].right++;
      else {
        tally[m].wrong++;
        if (m === MODES.length - 1 && misses.length < 6) {
          misses.push(`${rel}:${a[i].line + 1} [${a[i].name}] ` +
                      `"${wantMessage.slice(0, 40)}" -> line ${landed.line + 1} ` +
                      `[${landed.name}] "${messageAt(b, at + 1).slice(0, 40)}"`);
        }
      }
    });
  }
}

const points = tally[0].right + tally[0].wrong + tally[0].lost;
console.log(`save-capable elements in the files this update changed: ${points}\n`);
MODES.forEach(([label], m) => {
  const t = tally[m];
  const pct = n => (100 * n / points).toFixed(1).padStart(5) + '%';
  console.log(`  ${label} resumes in the right place ${pct(t.right)}` +
              `   wrong ${pct(t.wrong)}   lost ${pct(t.lost)}`);
});
if (misses.length) {
  console.log('\n  remaining misses:');
  for (const m of misses) console.log('   ' + m);
}
