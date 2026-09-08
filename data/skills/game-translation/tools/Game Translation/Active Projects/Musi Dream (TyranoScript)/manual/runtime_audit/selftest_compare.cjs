const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const project='C:/Users/sw/Desktop/Tools/Game Translation/Active Projects/Musi Dream (TyranoScript)';
const source=path.join(project,'source/app'),runtime=path.join(project,'reports/runtime_files.json');
const files=Object.keys(JSON.parse(fs.readFileSync(runtime,'utf8')).active).filter(x=>x.endsWith('.ks'));
const scene='data/scenario/scene1.ks', sceneSource=fs.readFileSync(path.join(source,scene),'utf8');
const choiceFile=files.find(x=>/\[glink[^\r\n]*target="/.test(fs.readFileSync(path.join(source,x),'utf8')));
assert(choiceFile,'Need existing glink target for negative fixture');
const choiceSource=fs.readFileSync(path.join(source,choiceFile),'utf8');
const results=[];
function run(name,entries,pass,check){
 const out=path.join(__dirname,'fixtures',name);fs.mkdirSync(out,{recursive:true});
 for(const [rel,code] of Object.entries(entries)){const file=path.join(out,rel);fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,code);}
 let output='';
 const testProcess={argv:[process.execPath,'compare_runtime.cjs',source,out,runtime,'--overlay'],versions:process.versions,version:process.version,binding:process.binding};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'compare_runtime.cjs'),'utf8'),{require,process:testProcess,console:{log:x=>{output+=x;}}});
 const data=JSON.parse(output);
 assert.strictEqual(data.passed,pass,name);
 if(check)assert(data.issues.some(x=>x.check===check),name+': missing '+check);
 results.push({name,passed:data.passed,expected:pass,issues:data.issues.map(x=>x.check)});
}
run('english_name',{[scene]:sceneSource.replace('#底辺Ytuberヒマリィ','#Small-Time Ytuber Himarii')},true);
run('underscore_spacing',{[scene]:sceneSource.replace('やった～～　やっと終わったよ～','_ All done at last!')},true);
run('glink_display',{[choiceFile]:choiceSource.replace(/(\[glink[^\r\n]*?text=")[^"]*/, '$1English Choice')},true);
run('inserted_break',{[scene]:sceneSource.replace('#底辺Ytuberヒマリィ','#底辺Ytuberヒマリィ\n[r]')},false,'element-count');
run('changed_target',{[choiceFile]:choiceSource.replace(/(\[glink[^\r\n]*?target=")[^"]*/, '$1*bad_target')},false,'control-parameters');
run('bad_javascript',{'qa_bad.js':'const = ;'},false,'javascript-syntax');
const theme='data/others/plugin/theme_kopanda_16/init.ks',themeSource=fs.readFileSync(path.join(source,theme),'utf8');
run('changed_script_identifier',{[theme]:themeSource.replace('mp.font_color','mp.bad_color')},false,'iscript-structure-except-string-values');
console.log(JSON.stringify({checks:results.length,results},null,2));
