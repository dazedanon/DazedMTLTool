(()=>{
 const fs=require('fs'),path=require('path'),root=path.resolve('translation_tooling/text_translation/runtime');
 window.tqa={fs,path,root,log:[],seen:new Set(),step:0};
 tqa.save=(name,obj)=>fs.writeFileSync(path.join(root,name+'.json'),JSON.stringify(obj,null,2));
 tqa.capture=name=>{
   const p=path.join(root,'screens',name+'.png');
   fs.writeFileSync(p,Buffer.from(Bitmap.snap(SceneManager._scene).canvas.toDataURL().split(',')[1],'base64'));
   return p;
 };
 tqa.status=()=>({scene:SceneManager._scene.constructor.name,map:$gameMap?.mapId(),x:$gamePlayer?.x,y:$gamePlayer?.y,
   busy:$gameMessage?.isBusy(),speaker:$gameMessage?.speakerName(),text:$gameMessage?.allText(),
   choices:$gameMessage?.choices(),window:SceneManager._scene._messageWindow&&{open:SceneManager._scene._messageWindow.openness,pause:SceneManager._scene._messageWindow.pause},
   events:$gameMap?._interpreter&&{event:$gameMap._interpreter._eventId,index:$gameMap._interpreter._index,wait:$gameMap._interpreter._waitMode}});
 tqa.advance=async(ms=20000)=>{
   const stop=Date.now()+ms;
   while(Date.now()<stop){
     const w=SceneManager._scene._messageWindow;
     const text=$gameMessage.allText();
     if(text&&!tqa.seen.has(text)){
       tqa.seen.add(text);tqa.log.push({...tqa.status(),time:Date.now()});
     }
     if($gameMessage.isChoice()&&SceneManager._scene._choiceListWindow?.active)break;
     if(w?.pause&&tqa.lastShot!==text){tqa.lastShot=text;if(tqa.step<14)tqa.capture('route_'+String(tqa.step).padStart(3,'0'));tqa.step++;}
     Input._currentState.ok=true;await new Promise(r=>setTimeout(r,90));
     Input._currentState.ok=false;await new Promise(r=>setTimeout(r,90));
   }
   tqa.save('route_log',tqa.log);return tqa.status();
 };
 tqa.walk=async(x,y,ms=20000)=>{
   const stop=Date.now()+ms;
   while(Date.now()<stop&&($gamePlayer.x!==x||$gamePlayer.y!==y)){
     if($gameMessage.isBusy())break;
     if(!$gamePlayer.isMoving())$gamePlayer.moveStraight($gamePlayer.findDirectionTo(x,y));
     await new Promise(r=>setTimeout(r,70));
   }
   return tqa.status();
 };
 return tqa.status();
})()
