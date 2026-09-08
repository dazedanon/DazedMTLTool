// Generates append-only kag.menu.js compatibility code from reviewed manual text
// and the actual injected parser values. No saves are opened or changed here.
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const [source,payload,packetFile,replyFile,outFile]=process.argv.slice(2);
assert(source&&payload&&packetFile&&replyFile&&outFile,'Need SOURCE PAYLOAD PACKET REPLY OUTPUT');
const packet=JSON.parse(fs.readFileSync(packetFile,'utf8')),reply=JSON.parse(fs.readFileSync(replyFile,'utf8'));
const runtime=JSON.parse(fs.readFileSync(path.resolve(source,'../../reports/runtime_files.json'),'utf8'));
function read(root,rel){const file=path.join(root,rel);return fs.readFileSync(fs.existsSync(file)?file:path.join(source,rel),'utf8');}
function parserFor(root){
 const ctx={tyrano:{plugin:{kag:{}}},$:{trim:x=>String(x).trim(),replaceAll:(x,a,b)=>x.split(a).join(b)},alert:x=>{throw Error(x);}};
 vm.createContext(ctx);vm.runInContext(read(root,'tyrano/plugins/kag/kag.parser.js'),ctx);
 const parser=ctx.tyrano.plugin.kag.parser,config=parser.compileConfig(read(root,'data/system/Config.tjs'));
 parser.kag={config,stat:{current_scenario:''},convertLang:()=>{},warning:(...x)=>{throw Error(JSON.stringify(x));},error:(...x)=>{throw Error(JSON.stringify(x));}};
 return parser;
}
const p0=parserFor(source),p1=parserFor(payload);
const data={names:{},choices:{},captions:{},unique:{},scenarios:{}};
function restore(text,tokens){return text.replace(/⟦(\d+)⟧/g,(_,index)=>{assert(index<tokens.length,'Unknown token');return tokens[index];});}
function domText(text){
 const entities={nbsp:'\u00a0',amp:'&',lt:'<',gt:'>',quot:'"',apos:"'"};
 return text.replace(/&(#x[\da-f]+|#\d+|[a-z]+);/gi,(all,key)=>{
  if(key[0]==='#')return String.fromCodePoint(key[1].toLowerCase()==='x'?parseInt(key.slice(2),16):parseInt(key.slice(1),10));
  assert(Object.prototype.hasOwnProperty.call(entities,key.toLowerCase()),'Unsupported HTML entity '+all);return entities[key.toLowerCase()];
 });
}
for(const unit of packet.units)if(unit.kind==='name'||unit.kind==='choice') {
 assert(typeof reply[unit.id]==='string','Missing manual reply '+unit.id);
 const sourceText=restore(unit.source,unit.tokens||[]),translatedText=restore(reply[unit.id],unit.tokens||[]);
 data[unit.kind==='name'?'names':'choices'][unit.kind==='choice'?domText(sourceText):sourceText]=unit.kind==='choice'?domText(translatedText):translatedText;
}
for(const unit of packet.units)if(['ゲームスタート','まだ、保存されているデータがありません。'].includes(unit.source)) {
 assert(typeof reply[unit.id]==='string');data.captions[unit.source]=reply[unit.id];
}
const candidates=new Map();
for(const rel of Object.keys(runtime.active).filter(x=>x.endsWith('.ks'))){
 p0.flag_script=p1.flag_script=false;p0.deep_if=p1.deep_if=0;
 p0.kag.stat.current_scenario=p1.kag.stat.current_scenario=rel;
 const a=p0.parseScenario(read(source,rel)).array_s,b=p1.parseScenario(read(payload,rel)).array_s;
 assert.strictEqual(a.length,b.length,rel+': structural mismatch');
 const entry={breaks:[],rows:[]};let script=false,html=false;
 for(let i=0;i<a.length;i++){
  assert.strictEqual(a[i].name,b[i].name,rel+': tag mismatch');assert.strictEqual(a[i].line,b[i].line,rel+': line mismatch');
  const name=a[i].name;
  if(['p','cm','ct','er'].includes(name))entry.breaks.push(i);
  if(name==='iscript')script=true;else if(name==='endscript')script=false;
  if(name==='html')html=true;else if(name==='endhtml')html=false;
  if(name==='text'&&!script&&!html&&a[i].val!==b[i].val){
   entry.rows.push([i,a[i].val,b[i].val]);
   if(!candidates.has(a[i].val))candidates.set(a[i].val,new Set());candidates.get(a[i].val).add(b[i].val);
  }
 }
 if(entry.rows.length)data.scenarios[rel]=entry;
}
for(const [src,values] of candidates)if(values.size===1)data.unique[src]=[...values][0];
const template=fs.readFileSync(path.join(__dirname,'save_compat_runtime.template.js'),'utf8');
assert(template.includes('__MUSI_SAVE_DISPLAY_DATA__'));
const output=template.replace('__MUSI_SAVE_DISPLAY_DATA__',JSON.stringify(data));
assert(!/⟦\d+⟧/.test(output),'Unrestored translation sentinel reached save helper');
new vm.Script(output);
fs.writeFileSync(outFile,output);
console.log(JSON.stringify({output:outFile,bytes:Buffer.byteLength(output),names:Object.keys(data.names).length,choices:Object.keys(data.choices).length,uniqueProse:Object.keys(data.unique).length,ambiguousProse:[...candidates].filter(([k,v])=>v.size>1).length,scenarios:Object.keys(data.scenarios).length},null,2));
