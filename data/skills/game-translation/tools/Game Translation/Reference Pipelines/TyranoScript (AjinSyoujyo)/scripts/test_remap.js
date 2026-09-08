// Verify save_compat's remap against the real scenarios, using the game's own
// Electron as the JS runtime (ELECTRON_RUN_AS_NODE=1).
//
//   node test_remap.js <old scenario dir> <new scenario dir>
//
// It reimplements parseScenario's element rules, parses every scenario in both
// builds, and for each element of the old build asks remap() where it went -
// once with the stamp a patched build would have written into the save, and
// once with only the line number an older save carries.
const fs = require('fs');
const path = require('path');

const OLD = process.argv[2];
const NEW = process.argv[3];

// --- the parser's element rules, from tyrano/plugins/kag/kag.parser.js -------
// The rule that is easy to miss: inside [iscript] the parser stops treating [
// and ] as tag delimiters, so each line of JavaScript is one `text` element.
// exp.ks is mostly array literals, and splitting on brackets there invents
// hundreds of elements that do not exist - which silently shifts every index
// this harness reports.
function parseScenario(text) {
  const out = [];
  const rows = text.split('\n');
  let inComment = false;
  let inScript = false;

  function pushTag(str, i) {
    const name = str.split(' ')[0].trim();
    if (name === 'iscript') inScript = true;
    else if (name === 'endscript') inScript = false;
    out.push({ line: i, name: name, val: str });
  }

  for (let i = 0; i < rows.length; i++) {
    let line = rows[i].trim();
    const first = line.substr(0, 1);
    // the engine looks for the word anywhere on the line, not just as a tag
    if (line.indexOf('endscript') !== -1) inScript = false;
    if (inComment === true && line === '*/') { inComment = false; continue; }
    if (line === '/*') { inComment = true; continue; }
    if (inComment || first === ';') continue;
    if (first === '#') { out.push({ line: i, name: 'chara_ptext', val: line }); continue; }
    if (first === '*') { out.push({ line: i, name: 'label', val: line }); continue; }
    if (first === '@') { pushTag(line.substr(1), i); continue; }
    if (first === '_') line = line.substring(1);

    let textBuf = '', tagStr = '', inTag = false, depth = 0;
    for (const c of line) {
      if (inTag) {
        if (c === ']' && !inScript) {
          if (--depth === 0) { inTag = false; pushTag(tagStr, i); tagStr = ''; }
          else tagStr += c;
        } else if (c === '[' && !inScript) { depth++; tagStr += c; }
        else tagStr += c;
      } else if (c === '[' && !inScript) {
        depth++;
        inTag = true;
        if (textBuf !== '') { out.push({ line: i, name: 'text', val: textBuf }); textBuf = ''; }
      } else textBuf += c;
    }
    if (textBuf !== '') out.push({ line: i, name: 'text', val: textBuf });
  }
  return out;
}

// --- the real implementation, read out of patch_src/save_compat.js ----------
// A copy here would drift from the shipping file and quietly measure code that
// is not the code that runs.
const COMPAT = fs.readFileSync(
  path.join(__dirname, '..', 'patch_src', 'save_compat.js'), 'utf8');

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

const source = [
  assignment('var DRIFT ='),
  assignment('var CLEARS ='),
  assignment('var WAITS ='),
  declaration('function normalise'),
  declaration('function messageAt'),
  declaration('function byMessage'),
  declaration('function ordinalOf'),
  declaration('function remap'),
].join('\n');
const [ordinalOf, messageAt, remap] = new Function(
  source + '\nreturn [ordinalOf, messageAt, remap];')();

function describeAt(array_tag, index) {
  const here = array_tag[index];
  if (!here) return null;
  // a real save records the text on screen; the corpus must too, or it
  // measures a path the shipping code never takes
  const message = messageAt(array_tag, index);
  let ordinal = 0;
  for (let i = index - 1; i >= 0 && array_tag[i].line === here.line; i--) ordinal++;
  return { v: 1, line: here.line, ordinal: ordinal, name: here.name,
           message: message };
}

// --- unit checks on remap, before the corpus comparison ---------------------
// Each case is a small array_tag and the mark a save would carry.
function checkRemap() {
  const row = (line, name, val) => ({ line: line, name: name, val: val === undefined ? name : val });
  const cases = [];

  // nothing moved
  cases.push(['unchanged', [row(1, 'cm'), row(2, 'cancelskip'), row(2, 's')],
    1, { v: 1, line: 2, ordinal: 1, name: 's' }, 1]);

  // a tag was inserted earlier in the file: same line, index shifted
  cases.push(['a tag added above',
    [row(1, 'cm'), row(1, 'wait'), row(2, 'cancelskip'), row(2, 's')],
    1, { v: 1, line: 2, ordinal: 1, name: 's' }, 2]);

  // the tag moved to a different line and its old line holds nothing. This is
  // the case that broke a real save: without the drift scan remap returned the
  // stored index and the game resumed on the label after [s], playing a scene
  // the player was not in.
  cases.push(['the line itself moved',
    [row(1, 'cm'), row(2, 'cancelskip'), row(2, 's'), row(4, 'label')],
    2, { v: 1, line: 3, ordinal: 1, name: 's' }, 1]);

  // too far to be the same tag: leave the index alone rather than guess
  const far = [row(1, 'cm')];
  for (let i = 0; i < 40; i++) far.push(row(2 + i, 'wait'));
  far.push(row(99, 's'));
  cases.push(['drifted out of reach', far, 5,
    { v: 1, line: 500, ordinal: 0, name: 's' }, 5]);


  // The line moved *and* an identical tag sits nearby, so name+ordinal cannot
  // tell them apart - but the text in front of them can. This is the case an
  // upstream game update produces, where whole lines are added and removed.
  cases.push(['the message picks it out',
    [row(1, 'text', 'first line of dialogue'), row(1, 'p'),
     row(2, 'text', 'the line we were on'), row(2, 'p'),
     row(3, 'text', 'a later line'), row(3, 'p')],
    1, { v: 1, line: 9, ordinal: 1, name: 'p', message: 'the line we were on' }, 2]);

  // The same text twice over. byMessage must refuse and let the line logic
  // answer: that gives index 3 (the [p] on line 2), where a guess at the first
  // match would have given index 1 and rewound the player a scene.
  cases.push(['a repeated message is not guessed at',
    [row(1, 'text', 'same words'), row(1, 'p'),
     row(2, 'text', 'same words'), row(2, 'p')],
    1, { v: 1, line: 2, ordinal: 1, name: 'p', message: 'same words' }, 2]);

  // a save with no message on screen must not be dragged to a random wait
  cases.push(['an empty message changes nothing',
    [row(1, 'cm'), row(2, 'cancelskip'), row(2, 's')],
    1, { v: 1, line: 2, ordinal: 1, name: 's', message: '' }, 1]);

  let failed = 0;
  for (const [label, tags, saved, mark, expected] of cases) {
    const got = remap(tags, saved, mark);
    const ok = got === expected;
    if (!ok) failed++;
    console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}: ${saved} -> ${got}` +
      (ok ? '' : ` (expected ${expected})`));
  }
  if (failed) {
    console.error(`${failed} remap check(s) failed`);
    process.exit(1);
  }
}

console.log('remap checks:');
checkRemap();
console.log('');

// ---------------------------------------------------------------------------
function walk(dir, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else if (entry.name.endsWith('.ks')) out.push(full);
  }
  return out;
}

const score = { stamped: { exact: 0, sameLine: 0, wrongLine: 0 },
                legacy: { exact: 0, sameLine: 0, wrongLine: 0 } };
let files = 0, shiftedFiles = 0, elements = 0, baseline = 0;
const sample = [];

for (const oldPath of walk(OLD)) {
  const rel = path.relative(OLD, oldPath);
  const newPath = path.join(NEW, rel);
  if (!fs.existsSync(newPath)) continue;
  files++;
  const a = parseScenario(fs.readFileSync(oldPath, 'utf8'));
  const b = parseScenario(fs.readFileSync(newPath, 'utf8'));
  if (a.length === b.length) continue;
  shiftedFiles++;
  for (let i = 0; i < a.length; i++) {
    elements++;
    const saved = i - 1;
    if (b[i] && b[i].name === a[i].name && b[i].val === a[i].val) baseline++;
    for (const [kind, mark] of [['stamped', describeAt(a, i)],
                                ['legacy', { v: 0, line: a[i].line }]]) {
      const landed = b[remap(b, saved, mark) + 1];
      if (!landed) { score[kind].wrongLine++; continue; }
      if (landed.line !== a[i].line) { score[kind].wrongLine++; continue; }
      if (landed.name === a[i].name && landed.val === a[i].val) score[kind].exact++;
      else {
        score[kind].sameLine++;
        if (kind === 'stamped' && sample.length < 6) {
          sample.push({ rel, i, line: a[i].line,
                        want: a[i].name + ':' + String(a[i].val).slice(0, 24),
                        got: landed.name + ':' + String(landed.val).slice(0, 24) });
        }
      }
    }
  }
}

const pct = (n) => elements ? (100 * n / elements).toFixed(1) + '%' : '-';
console.log('scenarios compared        ', files, '(' + shiftedFiles + ' shifted by the patch)');
console.log('elements in shifted files ', elements);
console.log('');
console.log('  no remap (what ships today)  exact', pct(baseline));
console.log('  legacy save (line only)      exact', pct(score.legacy.exact),
            ' same line', pct(score.legacy.sameLine),
            ' wrong line', pct(score.legacy.wrongLine));
console.log('  stamped save (line+ordinal)  exact', pct(score.stamped.exact),
            ' same line', pct(score.stamped.sameLine),
            ' wrong line', pct(score.stamped.wrongLine));
for (const s of sample) console.log('    stamped miss:', JSON.stringify(s));
