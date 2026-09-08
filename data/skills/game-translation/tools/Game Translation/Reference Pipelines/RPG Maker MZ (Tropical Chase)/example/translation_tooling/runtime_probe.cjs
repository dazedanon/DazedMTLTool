// Test selected functions read from this game's shipped engine, not copies.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert/strict');
const acorn = require('internal/deps/acorn/acorn/dist/acorn');
const root = process.argv[2];
const files = ['js/rmmz_objects.js','js/rmmz_windows.js'];
const wanted = new Set(['Game_Message.prototype.add','Game_Message.prototype.allText',
  'Game_Interpreter.prototype.command101','Window_Base.prototype.obtainEscapeCode']);
const found = new Map();
for (const file of files) {
  const src = fs.readFileSync(path.join(root,file),'utf8');
  const ast = acorn.parse(src,{ecmaVersion:'latest'});
  for (const n of ast.body) {
    const e = n.type === 'ExpressionStatement' ? n.expression : null;
    if (e?.type === 'AssignmentExpression') {
      const name = src.slice(e.left.start,e.left.end);
      if (wanted.has(name)) found.set(name,src.slice(n.start,n.end));
    }
  }
}
assert.equal(found.size,wanted.size,'Engine anchors changed');
const sandbox = {Game_Message:function(){},Game_Interpreter:function(){},Window_Base:function(){}};
vm.createContext(sandbox);
for (const code of found.values()) vm.runInContext(code,sandbox);
const msg = new sandbox.Game_Message();
msg._texts=[];msg.isBusy=()=>false;
for (const method of ['setFaceImage','setBackground','setPositionType','setSpeakerName']) msg[method]=()=>{};
sandbox.$gameMessage=msg;
const it = new sandbox.Game_Interpreter();
it._index=0;
it._list=[{code:101,parameters:['',0,0,2,'Test Speaker']},
  {code:401,parameters:['English words keep their spaces.']},
  {code:401,parameters:['Second row\nThird row']},{code:0,parameters:[]}];
it.nextEventCode=()=>it._list[it._index+1]?.code ?? 0;
it.currentCommand=()=>it._list[it._index];it.setWaitMode=()=>{};
assert.equal(it.command101(it._list[0].parameters),true);
assert.equal(it._index,2);
assert.equal(msg.allText(),'English words keep their spaces.\nSecond row\nThird row');
const win = new sandbox.Window_Base();
for (const [input,expected] of [['C[2]','C'],['V[103]','V'],['F[sn_01]','F'],['AA[1]','AA'],['G Words','G']]) {
  const state={text:input,index:0};
  assert.equal(win.obtainEscapeCode(state),expected);
}
assert.equal(win.obtainEscapeCode({text:'GWords',index:0}),'GWORDS');
// The enabled portrait plugin removes its numbered and nested codes BEFORE
// the engine escape parser. Read that exact function from the plugin AST.
const portrait = fs.readFileSync(path.join(root,'js/plugins/LL_StandingPicture.js'),'utf8');
const portraitAst = acorn.parse(portrait,{ecmaVersion:'latest'});
let portraitCode;
const findPortrait = n => {
  if (!n || typeof n !== 'object') return;
  if (n.type === 'AssignmentExpression' && portrait.slice(n.left.start,n.left.end) === 'Window_Base.prototype.convertEscapeCharacters')
    portraitCode=portrait.slice(n.start,n.end);
  for (const v of Object.values(n)) {
    if (Array.isArray(v)) v.forEach(findPortrait);
    else if (v && typeof v === 'object') findPortrait(v);
  }
};
findPortrait(portraitAst);
assert.ok(portraitCode,'Portrait parser anchor changed');
sandbox._Window_Base_convertEscapeCharacters=function(text){return text;};
vm.runInContext(portraitCode,sandbox);
const portraitText='\\F3[sn_01]\\F5[m_01]\\F6[\\V[1]]\\AA[N]English words stay here.';
assert.equal(win.convertEscapeCharacters(portraitText),'English words stay here.');
process.stdout.write(JSON.stringify({pass:true,shipped_functions:[...wanted],
  message_command_index_preserved:true,spaces_preserved:true,multiline_existing_slot_supported:true,
  adjacent_latin_escape_hazard_confirmed:true,numbered_and_nested_portrait_codes_verified:true}));
