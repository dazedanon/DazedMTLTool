// Read-only probe using this game's shipped parser in its own Electron runtime.
const fs=require('fs'), path=require('path'), vm=require('vm'), assert=require('assert');
const root=path.resolve(__dirname,'..'), source=path.join(root,'source');
const alerts=[],warnings=[];
const context={tyrano:{plugin:{kag:{}}},$:{trim:x=>String(x==null?'':x).trim(),replaceAll:(s,a,b)=>s.split(a).join(b),lang:x=>x},alert:x=>alerts.push(String(x))};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(source,'tyrano/plugins/kag/kag.parser.js'),'utf8'),context);
const parser=context.tyrano.plugin.kag.parser;
const config=parser.compileConfig(fs.readFileSync(path.join(source,'data/system/Config.tjs'),'utf8'));
parser.kag={config,stat:{current_scenario:'probe.ks'},warning:x=>warnings.push(String(x))};
const plain=parser.makeTag('glink text="Two words" target="*same_target"',0);
const nbsp=parser.makeTag('glink text="Two\u00a0words" target="*same_target"',0);
assert.strictEqual(plain.pm.text,'Twowords');
assert.strictEqual(nbsp.pm.text,'Two\u00a0words');
assert.strictEqual(nbsp.pm.target,'*same_target');
const expr=parser.makeTag('eval exp="f.sample=\'Two\u00a0words\'"',0);
assert.strictEqual(expr.pm.exp,"f.sample='Two\u00a0words'");
const continued=parser.parseScenario('First sentence.\n_ Second sentence.[p]').array_s;
assert.strictEqual(continued.filter(x=>x.name==='text').map(x=>x.val).join(''),'First sentence. Second sentence.');
const catalog=JSON.parse(fs.readFileSync(path.join(root,'catalog.json'),'utf8'));
let files=0,elements=0;
const baseline=[];
for(const rel of Object.keys(catalog.source_files).filter(x=>x.endsWith('.ks'))){
  parser.flag_script=false;parser.deep_if=0;parser.kag.stat.current_scenario=rel;
  const oldA=alerts.length,oldW=warnings.length;
  try{const parsed=parser.parseScenario(fs.readFileSync(path.join(source,rel),'utf8'));files++;elements+=parsed.array_s.length;}
  catch(e){baseline.push({file:rel,error:String(e)});}
  if(alerts.length>oldA||warnings.length>oldW)baseline.push({file:rel,alerts:alerts.slice(oldA),warnings:warnings.slice(oldW)});
}
const report={electron:process.versions.electron,node:process.versions.node,
  ascii_attribute_spaces_survive:false,nbsp_attribute_spaces_survive:true,
  continuation_marker_preserves_space:true,source_files:files,source_elements:elements,
  source_parser_diagnostics:baseline,config,
  scope:'Source parser and whitespace behavior only; no GUI, save, or deployment validation.'};
fs.writeFileSync(path.join(root,'reports/parser_probe.json'),JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify({electron:report.electron,node:report.node,files,elements,source_diagnostic_files:baseline.length,whitespace_probes:'passed'}));
