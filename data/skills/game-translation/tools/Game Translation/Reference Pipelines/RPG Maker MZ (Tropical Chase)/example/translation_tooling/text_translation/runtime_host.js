/* Temporary native-runtime QA hook. Loaded only during the isolated QA launch.
 * No network listener. Commands and replies stay in this workspace.
 */
(() => {
  const fs=require('fs'),path=require('path');
  const root=path.resolve(process.cwd(),'translation_tooling/text_translation');
  const qa=path.join(root,'runtime'); fs.mkdirSync(qa,{recursive:true});
  const saves=path.join(qa,'save');fs.mkdirSync(saves,{recursive:true});
  const put=(name,value)=>fs.writeFileSync(path.join(qa,name),JSON.stringify(value,null,2));
  put('booted.json',{href:location.href,pid:process.pid,versions:process.versions});
  window.addEventListener('error',event=>put('error.json',{message:event.message,stack:event.error?.stack}));
  let busy=false,seen='';
  const oldRequest=path.join(qa,'request.json');
  if(fs.existsSync(oldRequest)) {try{seen=JSON.parse(fs.readFileSync(oldRequest,'utf8')).id;}catch{}}
  const captured=new Set();
  setInterval(()=>{
    if(typeof SceneManager==='undefined'||typeof Bitmap==='undefined')return;
    const scene=SceneManager._scene;if(!scene||scene._fadeDuration||scene._fadeOpacity)return;
    const splash=scene._originalSplash;
    let label;
    if(splash&&splash.bitmap&&splash.bitmap.isReady()) label='boot_'+path.basename(splash.bitmap.url,'.png');
    else if(scene.constructor.name==='Scene_Title'&&ImageManager.isReady())label='boot_title';
    if(!label||captured.has(label))return;
    captured.add(label);
    const output=path.join(qa,'screens');fs.mkdirSync(output,{recursive:true});
    const snap=Bitmap.snap(scene);
    fs.writeFileSync(path.join(output,label+'.png'),Buffer.from(snap.canvas.toDataURL('image/png').split(',')[1],'base64'));
  },100);
  setInterval(async()=>{
    if(typeof StorageManager!=='undefined') StorageManager.fileDirectoryPath=()=>saves+path.sep;
    if(busy) return;
    const request=path.join(qa,'request.json'); if(!fs.existsSync(request)) return;
    let task;
    try {task=JSON.parse(fs.readFileSync(request,'utf8'));} catch {return;}
    if(task.id===seen) return; seen=task.id;busy=true;
    try {
      const result=await window.eval(task.code);
      put('response.json',{id:task.id,ok:true,result});
    } catch(error) {put('response.json',{id:task.id,ok:false,error:String(error),stack:error.stack});}
    finally {busy=false;}
  },100);
})();
