(async()=>{
 const sleep=ms=>new Promise(r=>setTimeout(r,ms));
 SceneManager.goto(Scene_Title);await sleep(800);
 await DataManager.loadGame(24);SceneManager.goto(Scene_Map);await sleep(1200);
 $gamePlayer.setTransparent(true);$gamePlayer.reserveTransfer(14,0,0,2,0);await sleep(9000);
 const sprite=SceneManager._scene._spriteset._pictureContainer.children.find(s=>s._pictureId===1);
 const source=ImageManager.loadPicture('result_back');
 const a=source.context.getImageData(0,0,816,624).data,b=sprite.bitmap.context.getImageData(0,0,816,624).data;
 let outsideMaxDelta=0;
 for(let y=0;y<624;y++)for(let x=0;x<816;x++)if(!(x>=88&&x<728&&y>=94&&y<525)){
  const n=(y*816+x)*4;for(let k=0;k<4;k++)outsideMaxDelta=Math.max(outsideMaxDelta,Math.abs(a[n+k]-b[n+k]));
 }
 SceneManager.goto(Scene_Title);await sleep(800);
 await DataManager.loadGame(22);SceneManager.goto(Scene_Map);await sleep(1200);
 const snapshot=()=>({map:$gameMap.mapId(),x:$gamePlayer.x,y:$gamePlayer.y,actor:$gameActors.actor(9).name()});
 const before=snapshot();
 SceneManager.push(Scene_Save);await sleep(600);SceneManager._scene.executeSave(26);await sleep(1000);
 SceneManager.push(Scene_Load);await sleep(600);SceneManager._scene.executeLoad(26);await sleep(1400);
 const after=snapshot(),engineError=Graphics._errorPrinter?.textContent||'';
 const result={outsidePanelMaxPixelDelta:outsideMaxDelta,titleAndOtherPixelsPreserved:outsideMaxDelta<=1,before,after,saveUi:true,loadUi:true,engineError,pass:outsideMaxDelta<=1&&JSON.stringify(before)===JSON.stringify(after)&&!engineError};
 tqa.save('results_fix_lifecycle',result);return result;
})()
