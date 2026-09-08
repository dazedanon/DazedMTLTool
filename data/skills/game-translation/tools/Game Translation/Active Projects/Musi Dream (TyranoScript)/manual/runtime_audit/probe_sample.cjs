// Read-only unit-level probe; the candidate repair exists only in VM memory.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const sourceFile = process.argv[2] || 'C:/Users/sw/Desktop/Tools/Game Translation/Active Projects/Musi Dream (TyranoScript)/source/app/data/others/plugin/theme_kopanda_16/testMessagePlus/gMessageTester.js';
const source = fs.readFileSync(sourceFile,'utf8');
const begin = source.indexOf('$.get(TM.sampleUrl, function(data){');
const end = source.indexOf('\n\t});',begin);
assert(begin >= 0 && end > begin);
const oldReader = source.slice(begin,end);
const candidateReader = oldReader
 .replace('data = data.replace(/;.*/g, "\\n");','data = data.replace(/^[ \\t]*;.*$/gm, "");')
 .replace('data = data.replace(/(\\n|\\s|\\t)/g, "");','data = data.replace(/\\r\\n?/g, "\\n").split("\\n").map(function(line) { return line.trim(); }).filter(Boolean).join(" ");')
 .replace('var arr = data.split("[p]");','var arr = data.split("[p]").map(function(text) { return text.trim(); });');
assert.notStrictEqual(candidateReader,oldReader);
const candidate = source.slice(0,begin)+candidateReader+source.slice(end);
function load(code) {
 const callbacks = {};
 const ctx = {$:{get:(url,cb)=>{callbacks[url]=cb;}},tyrano:{plugin:{kag:{config:{}}}}};
 ctx.window=ctx;
 vm.createContext(ctx);vm.runInContext(code,ctx);
 const tm=ctx.gMessageTester;
 callbacks[tm.cssUrl](fs.readFileSync(sourceFile.replace(/gMessageTester\.js$/,'style.css'),'utf8'));
 return {tm,read:callbacks[tm.sampleUrl]};
}
const baseline=load(source),fixed=load(candidate);
const sample='; comment\r\nTwo words[r]Next line[p]\r\nA semicolon; stays.\r\nMore words [kidoku]already read[endkidoku].[p]\r\n';
baseline.read(sample);fixed.read(sample);
assert.deepStrictEqual(Array.from(fixed.tm.sampleTexts),[
 'Two words[r]Next line',
 'A semicolon; stays. More words [kidoku]already read[endkidoku].'
]);
assert.strictEqual(fixed.tm.style.width,'760px');
assert.strictEqual(fixed.tm.style['font-size'],'18px');
assert.deepStrictEqual(JSON.parse(JSON.stringify(fixed.tm.style)),JSON.parse(JSON.stringify(baseline.tm.style)));
fixed.tm.getKidokuColor=()=> '#123456';
let rendered='';fixed.tm.messageArea={html:x=>{rendered=x;}};
fixed.tm.currentChar=fixed.tm.sampleTexts[1];fixed.tm.appendChar();
assert.strictEqual(rendered,"A semicolon; stays. More words <span style='color:#123456'>already read</span>.");
fixed.tm.currentHtml='';fixed.tm.currentChar=fixed.tm.sampleTexts[0];fixed.tm.appendChar();
assert.strictEqual(rendered,'Two words<br />Next line');
console.log(JSON.stringify({baseline:Array.from(baseline.tm.sampleTexts),candidate:Array.from(fixed.tm.sampleTexts),cssUnchanged:true,tagsRetained:true,sampleCallbackOffset:begin,checks:'passed; candidate only in VM'},null,2));
