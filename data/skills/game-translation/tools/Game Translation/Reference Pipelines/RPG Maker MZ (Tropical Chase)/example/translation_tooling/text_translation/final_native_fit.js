(()=>{
const fs=require('fs'),path=require('path');
const base=path.resolve('..');
const units=JSON.parse(fs.readFileSync(path.join(base,'units.json'),'utf8')).units;
const w=SceneManager._scene._messageWindow,docs={},measurements=[],problems=[],variables=$gameVariables._data.slice();
const get=(obj,p)=>p.reduce((v,k)=>v[k],obj);
const originalFont=w.contents.fontSize;
for(const u of units)for(const c of Object.values(u.codes))for(const m of c.matchAll(/\\V\[(\d+)\]/gi))$gameVariables._data[Number(m[1])]=99999;
for(let index=0;index<units.length;index++){
 const u=units[index];if(u.kind!=='dialogue')continue;
 const s=u.sites[0];docs[s.file] ||= JSON.parse(fs.readFileSync(s.file,'utf8').replace(/^\uFEFF/,''));
 const list=get(docs[s.file],s.path),body=list.slice(s.start,s.start+s.count).map(c=>c.parameters[0]).join('\n');
 w.resetFontSettings();const state=w.createTextState(body,4,0,780);state.drawing=false;
 Window_Base.prototype.processAllText.call(w,state);
 const heightLimit=s.count===4?144:108;
 const row={index,width:state.outputWidth,height:state.outputHeight,widthLimit:780,heightLimit};
 measurements.push(row);if(row.width>780.1||row.height>heightLimit+.1)problems.push(row);
}
$gameVariables._data=variables;w.contents.fontSize=originalFont;
const sha=p=>require('crypto').createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const result={pass:!problems.length,method:'Actual installed message command text, native MZ/standing-picture parser and canvas, five-digit dynamic substitution stress',count:measurements.length,problems,measurements,
 store_sha256:sha(path.join(base,'units.json')),artifact_hashes:Object.fromEntries([...Object.keys(docs),'js/plugins.js','js/plugins/TropicalChaseEnglish.js'].map(p=>[p,sha(p)]))};
fs.writeFileSync(path.join(base,'reports/native_final_dialogue_fit.json'),JSON.stringify(result,null,2));
return {...result,measurements:undefined};
})()
