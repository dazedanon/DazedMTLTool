// Uses the shipped parser directly. No UI, network, save access, or game boot.
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');
const root = path.resolve(__dirname, '..');
const source = path.join(root, 'source', 'app');
const context = {
  tyrano: {plugin: {kag: {}}},
  $: {trim: x => String(x).trim(), replaceAll: (x,a,b) => x.split(a).join(b)},
  alert: x => {throw new Error(x);}
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(source,'tyrano/plugins/kag/kag.parser.js'),'utf8'),context);
const parser=context.tyrano.plugin.kag.parser;
const config=parser.compileConfig(fs.readFileSync(path.join(source,'data/system/Config.tjs'),'utf8'));
const warnings=[];
parser.kag={config,stat:{current_scenario:'probe.ks'},convertLang:()=>{},
  warning:(...x)=>warnings.push(x),error:(...x)=>{throw new Error(JSON.stringify(x));}};
assert.strictEqual(config.KeepSpaceInParameterValue,'2');
const choice=parser.makeTag('glink text="Two words" target="*same_target"',0);
assert.strictEqual(choice.pm.text,'Two words');
const expr=parser.makeTag('eval exp="f.sample=\'Two words\'"',0);
assert.strictEqual(expr.pm.exp,"f.sample='Two words'");
const spaced=parser.parseScenario('First sentence.\n_ Second sentence.[p]').array_s;
assert.strictEqual(spaced.filter(x=>x.name==='text').map(x=>x.val).join(''),'First sentence. Second sentence.');
const speaker=parser.parseScenario('#Small-Time Ytuber Himarii\nHello.[p]').array_s;
assert.strictEqual(speaker[0].name,'chara_ptext');
assert.strictEqual(speaker[0].pm.name,'Small-Time Ytuber Himarii');
const core=fs.readFileSync(path.join(source,'tyrano/plugins/kag/kag.tag_ext.js'),'utf8');
assert(core.includes('j_chara_name.updatePText(cpm.jname)'));
const runtime=JSON.parse(fs.readFileSync(path.join(root,'reports/runtime_files.json'),'utf8'));
let files=0,elements=0;
const failures=[];
for(const rel of Object.keys(runtime.active).filter(x=>x.endsWith('.ks'))){
  parser.flag_script=false;parser.deep_if=0;
  parser.kag.stat.current_scenario=rel;
  try {elements+=parser.parseScenario(fs.readFileSync(path.join(source,rel),'utf8')).array_s.length;files++;}
  catch(e){failures.push({file:rel,error:String(e)});}
}
const result={electron:process.versions.electron,node:process.versions.node,
  config_version:config['global.config_version'],keep_spaces:config.KeepSpaceInParameterValue,
  ascii_spaces_survive:true,leading_underscore_space_survives:true,speaker_names_parse:true,
  parsed_files:files,parsed_elements:elements,source_parser_warnings:warnings,source_parser_failures:failures};
fs.writeFileSync(path.join(root,'reports/parser_probe.json'),JSON.stringify(result,null,2)+'\n');
console.log(JSON.stringify(result,null,2));
if(failures.length)process.exitCode=1;
