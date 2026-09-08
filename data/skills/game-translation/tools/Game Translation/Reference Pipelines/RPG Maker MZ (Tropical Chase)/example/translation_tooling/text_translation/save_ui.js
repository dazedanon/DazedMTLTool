(async()=>{
 const before={map:$gameMap.mapId(),x:$gamePlayer.x,y:$gamePlayer.y,actor:$gameActors.actor(9).name()};
 SceneManager.push(Scene_Save);await new Promise(r=>setTimeout(r,700));
 SceneManager._scene.executeSave(22);await new Promise(r=>setTimeout(r,1000));
 if(SceneManager._scene.constructor.name!=='Scene_Map')throw new Error('Save did not return to map');
 SceneManager.push(Scene_Load);await new Promise(r=>setTimeout(r,700));
 SceneManager._scene.executeLoad(22);await new Promise(r=>setTimeout(r,1500));
 const after={map:$gameMap.mapId(),x:$gamePlayer.x,y:$gamePlayer.y,actor:$gameActors.actor(9).name()};
 if(JSON.stringify(before)!==JSON.stringify(after))throw new Error('Save/load state changed');
 const result={before,after,scene:SceneManager._scene.constructor.name,saveUi:true,loadUi:true};
 tqa.capture('saved_and_loaded');tqa.save('save_ui_validation',result);return result;
})()
