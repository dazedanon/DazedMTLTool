// Offline: run using ELECTRON_RUN_AS_NODE=1 and the game's executable.
// Usage: compare_runtime.cjs SOURCE_APP TRANSLATED_APP RUNTIME_FILES_JSON [--overlay] [--parsed-output JSON]
// --overlay means absent translated files intentionally resolve from SOURCE_APP.
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');
const [sourceArg, translatedArg, runtimeArg] = process.argv.slice(2);
if (!sourceArg || !translatedArg || !runtimeArg) throw new Error('Need SOURCE_APP TRANSLATED_APP RUNTIME_FILES_JSON [--overlay]');
const source = path.resolve(sourceArg), translated = path.resolve(translatedArg);
const overlay = process.argv.includes('--overlay');
const outputIndex=process.argv.indexOf('--parsed-output');
const parsedOutput=outputIndex>=0?process.argv[outputIndex+1]:null;
if(outputIndex>=0&&!parsedOutput)throw new Error('--parsed-output needs a JSON path');
function read(root,rel) {
 const file = path.join(root,rel);
 if(fs.existsSync(file)) return fs.readFileSync(file,'utf8');
 if(root===translated && overlay) return fs.readFileSync(path.join(source,rel),'utf8');
 throw new Error('Missing input: '+file);
}
function makeParser(root) {
 const warnings=[];
 const context={tyrano:{plugin:{kag:{}}},$:{trim:x=>String(x).trim(),replaceAll:(x,a,b)=>x.split(a).join(b)},alert:x=>{throw new Error(String(x));}};
 vm.createContext(context);
 vm.runInContext(read(root,'tyrano/plugins/kag/kag.parser.js'),context);
 const parser=context.tyrano.plugin.kag.parser;
 const config=parser.compileConfig(read(root,'data/system/Config.tjs'));
 parser.kag={config,stat:{current_scenario:''},convertLang:()=>{},warning:(...x)=>warnings.push(x),error:(...x)=>{throw new Error(JSON.stringify(x));}};
 return {parser,config,warnings};
}
const original=makeParser(source),patched=makeParser(translated);
for(const key of ['projectID','configSave','configSaveOverwrite','KeepSpaceInParameterValue','scWidth','scHeight'])
 assert.strictEqual(patched.config[key],original.config[key],'Protected config: '+key);
assert.strictEqual(patched.config.KeepSpaceInParameterValue,'2');
const active=JSON.parse(fs.readFileSync(runtimeArg,'utf8')).active;
const files=Object.keys(active).filter(x=>x.endsWith('.ks')).sort();
assert(files.length>0,'No active scenarios');
function parse(holder,rel,root) {
 holder.parser.flag_script=false;holder.parser.deep_if=0;holder.parser.kag.stat.current_scenario=rel;
 return holder.parser.parseScenario(read(root,rel));
}
const sourceParsed=new Map(), translatedParsed=new Map(), protectedNames=new Set();
for(const file of files) {
 const a=parse(original,file,source),b=parse(patched,file,translated);
 sourceParsed.set(file,a);translatedParsed.set(file,b);
 for(const tag of a.array_s) if(['chara_new','chara_mod'].includes(tag.name)) {
  if(tag.pm.name)protectedNames.add(tag.pm.name);
  if(tag.pm.jname)protectedNames.add(tag.pm.jname);
 }
}
// Parse JS with this runtime's own bundled Acorn, avoiding dependency downloads.
const acornCode=process.binding('natives')['internal/deps/acorn/acorn/dist/acorn'];
assert(acornCode,'Runtime must expose its bundled Acorn');
const acornExports={};vm.runInNewContext(acornCode,{exports:acornExports,module:{exports:acornExports}});
function scriptShape(code) {
 const ast=acornExports.parse(code,{ecmaVersion:'latest'});
 function clean(value,key) {
  if(key==='start'||key==='end'||key==='raw')return undefined;
  if(Array.isArray(value))return value.map(x=>clean(x));
  if(value&&typeof value==='object') {
   const out={};
   for(const [k,v] of Object.entries(value)) {
    const r=value.type==='Literal'&&k==='value'&&typeof v==='string'?'__DISPLAY_LITERAL__':clean(v,k);
    if(r!==undefined)out[k]=r;
   }
   return out;
  }
  return value;
 }
 return clean(ast);
}
const issues=[],stats={scenarioFiles:files.length,parsedElements:0,displayChanges:0,iscriptBlocks:0,changedJavaScript:0,overlayFallback:overlay};
function equal(a,b,detail){if(JSON.stringify(a)!==JSON.stringify(b))issues.push(detail);}
for(const file of files) {
 const a=sourceParsed.get(file),b=translatedParsed.get(file);
 equal(a.array_s.length,b.array_s.length,{file,check:'element-count',source:a.array_s.length,translated:b.array_s.length});
 equal(a.map_label,b.map_label,{file,check:'labels'});
 stats.parsedElements+=a.array_s.length;
 let inScript=false,scriptA='',scriptB='';
 for(let i=0;i<Math.min(a.array_s.length,b.array_s.length);i++) {
  const x=a.array_s[i],y=b.array_s[i],at={file,index:i,line:x.line};
  equal([x.name,x.line],[y.name,y.line],{...at,check:'kind-and-line',source:[x.name,x.line],translated:[y.name,y.line]});
  const pmA={...x.pm},pmB={...y.pm};
  if(x.name==='text') {delete pmA.val;delete pmB.val; if(x.val!==y.val)stats.displayChanges++;}
  if(x.name==='glink') {delete pmA.text;delete pmB.text;}
  if(x.name==='chara_ptext'&&!protectedNames.has(x.pm.name)&&x.pm.name!=='') {delete pmA.name;delete pmB.name;}
  equal(pmA,pmB,{...at,check:'control-parameters',source:pmA,translated:pmB});
  const propsA={...x},propsB={...y};delete propsA.pm;delete propsB.pm;
  if(x.name==='text'){delete propsA.val;delete propsB.val;}
  equal(propsA,propsB,{...at,check:'element-metadata'});
  if(x.name==='iscript'){inScript=true;scriptA='';scriptB='';}
  else if(x.name==='endscript') {
   if(inScript)try {
    new vm.Script(scriptA,{filename:file+':source-iscript'});new vm.Script(scriptB,{filename:file+':translated-iscript'});
    equal(scriptShape(scriptA),scriptShape(scriptB),{...at,check:'iscript-structure-except-string-values'});
    stats.iscriptBlocks++;
   } catch(error) {issues.push({...at,check:'iscript-syntax',error:String(error)});}
   inScript=false;
  } else if(inScript&&x.name==='text') {scriptA+=x.val+'\n';scriptB+=y.val+'\n';}
 }
}
function walk(root) {
 const out=[];
 for(const entry of fs.readdirSync(root,{withFileTypes:true})) {
  const file=path.join(root,entry.name);
  if(entry.isDirectory())out.push(...walk(file));else out.push(file);
 }
 return out;
}
for(const file of walk(translated).filter(x=>x.endsWith('.js')||x.endsWith('.cjs'))) {
 const rel=path.relative(translated,file),code=fs.readFileSync(file,'utf8'),old=path.join(source,rel);
 if(fs.existsSync(old)&&fs.readFileSync(old,'utf8')===code)continue;
 try{new vm.Script(code,{filename:file});stats.changedJavaScript++;}
 catch(error){issues.push({file:rel,check:'javascript-syntax',error:String(error)});}
}
equal(original.warnings,[],{check:'source-parser-warnings',warnings:original.warnings});
equal(patched.warnings,[],{check:'translated-parser-warnings',warnings:patched.warnings});
if(parsedOutput) {
 const reportPath=path.resolve(parsedOutput);
 fs.mkdirSync(path.dirname(reportPath),{recursive:true});
 fs.writeFileSync(reportPath,JSON.stringify({source,translated,config:patched.config,files:Object.fromEntries(translatedParsed)},null,2)+'\n');
 stats.parsedOutput=reportPath;
}
console.log(JSON.stringify({runtime:process.versions.electron||process.version,source,translated,...stats,issues,passed:issues.length===0},null,2));
if(issues.length)process.exitCode=1;
