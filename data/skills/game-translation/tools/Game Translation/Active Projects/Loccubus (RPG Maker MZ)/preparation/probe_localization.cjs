// Exercise functions taken from this game's source, without booting the game.
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
let acorn;
try { acorn = require('acorn'); }
catch { acorn = require('internal/deps/acorn/acorn/dist/acorn'); }
const source = fs.readFileSync(path.join(__dirname, 'source/js/plugins/MUUI_Localization.js'), 'utf8');
const ast = acorn.parse(source, {ecmaVersion: 'latest'});
const names = new Set(['getText', '_doGetText', '_resolveTags']);
const definitions = new Map();
function visit(node) {
  if (!node || typeof node !== 'object') return;
  if (node.type === 'AssignmentExpression' && node.left.type === 'MemberExpression' &&
      node.left.object.name === 'n' && names.has(node.left.property.name) &&
      node.right.type === 'FunctionExpression') {
    assert(!definitions.has(node.left.property.name), 'Duplicate runtime function');
    definitions.set(node.left.property.name, source.slice(node.right.start, node.right.end));
  }
  for (const value of Object.values(node)) {
    if (Array.isArray(value)) value.forEach(visit);
    else if (value && typeof value === 'object') visit(value);
  }
}
visit(ast);
assert.equal(definitions.size, names.size, 'Shipped function anchors moved');
const parameters = {get(key) { return {ParseDepth: '2', DebugMode: 'false'}[key]; }};
const runtime = {_enabled: true, _refreshing: false, _currentLocale: 'en', _cache: new Map(),
  _tagIndex: new Map([['存档', 'Save'], ['取消', 'Cancel']]),
  _textIndex: new Map([['测试标签', 'Test Label']])};
for (const [name, definition] of definitions) {
  runtime[name] = new Function('t', 'o', `return (${definition});`)(parameters, '\0MUUI_HASH\0');
}
assert.equal(runtime.getText('#存档#'), 'Save');
assert.equal(runtime.getText('#存档# / #取消#'), 'Save / Cancel');
assert.equal(runtime.getText('English words stay spaced.'), 'English words stay spaced.');
assert.equal(runtime.getText('测试标签'), 'Test Label');
assert.equal(runtime.getText('[c=#ffffff]#存档#[/c]'), '[c=#ffffff]Save[/c]');
assert.equal(runtime.getText('#MissingKey#'), 'MissingKey');
assert.equal(runtime.getText('#存档#'), 'Save');
console.log(JSON.stringify({checks: 7, runtime_functions_from_shipped_source: [...definitions.keys()],
  game_launched: false, network_calls: 0}));
