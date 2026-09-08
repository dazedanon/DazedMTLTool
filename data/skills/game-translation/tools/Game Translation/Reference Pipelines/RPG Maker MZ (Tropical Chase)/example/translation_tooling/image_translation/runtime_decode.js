(async()=>{
  const fs=require('fs'),path=require('path'),crypto=require('crypto');
  const root=path.resolve(process.cwd(),'translation_tooling/image_translation');
  const manifest=JSON.parse(fs.readFileSync(path.join(root,'manifest.json'),'utf8'));
  const out=path.join(root,'runtime/decoded');fs.mkdirSync(out,{recursive:true});
  const rows=[];
  for(const item of manifest.assets){
    const url=item.path.slice(0,-1);
    const bitmap=Bitmap.load(url);
    await new Promise((resolve,reject)=>{
      const deadline=setTimeout(()=>reject(Error('Image timeout: '+url)),10000);
      bitmap.addLoadListener(()=>{clearTimeout(deadline);resolve();});
    });
    const bytes=fs.readFileSync(path.join(process.cwd(),item.path));
    const encodedHash=crypto.createHash('sha256').update(bytes).digest('hex');
    if(encodedHash!==item.encrypted_sha256) throw Error('Installed hash mismatch: '+url);
    const rgba=bitmap.context.getImageData(0,0,bitmap.width,bitmap.height).data;
    fs.writeFileSync(path.join(out,item.id+'.rgba'),Buffer.from(rgba));
    rows.push({id:item.id,url,encodedHash,width:bitmap.width,height:bitmap.height,ready:bitmap.isReady(),native:'shipped Bitmap.load / encrypted loader'});
  }
  fs.writeFileSync(path.join(root,'runtime/decode.json'),JSON.stringify(rows,null,2));
  ImageManager.clear();SceneManager.goto(Scene_Title);
  return {decoded:rows.length,scene:'Scene_Title requested'};
})()
