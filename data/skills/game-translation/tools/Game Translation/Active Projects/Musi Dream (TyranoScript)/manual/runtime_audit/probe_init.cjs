// Read-only runtime probe. No game boot, UI, network, or save access.
const fs = require('fs');
const path = require('path');
const natives = process.binding('natives');
const names = Object.keys(natives).filter(x => x.includes('electron'));
console.log(JSON.stringify({versions:process.versions,nativeNames:names}, null, 2));
for (const name of names) {
  const text = natives[name];
  if (text.includes('appSearchPaths')) {
    fs.writeFileSync(path.join(__dirname, name.replace(/[^a-z0-9]/gi,'_')+'.js'),text);
    for(const term of ['appSearchPaths','OnlyLoadASAR']){
      const i=text.indexOf(term);
      console.log(name, term, i, text.slice(Math.max(0,i-300),i+900));
    }
  }
}
try {
  const v8 = process._linkedBinding('electron_common_v8_util');
  console.log('v8util',Object.keys(v8));
  console.log('appSearchPaths',v8.getHiddenValue(global,'appSearchPaths'));
  console.log('appSearchPathsOnlyLoadASAR',v8.getHiddenValue(global,'appSearchPathsOnlyLoadASAR'));
} catch (e) { console.log('v8util probe:',String(e)); }
const archive = path.resolve(__dirname,'../../..','resources','app.asar');
try {console.log('asarFS',fs.readFileSync(path.join(archive,'package.json'),'utf8'));}
catch (e) {console.log('asarFS error',String(e));}
