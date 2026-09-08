(async()=>{
 const fs=require('fs');
 const source=JSON.parse(fs.readFileSync('translation_tooling/text_translation/runtime/baseline_save.json','utf8'));
 await DataManager.loadGame(20);
 const loaded={actor:$gameActors.actor(9).name(),condition:$gameVariables.value(125),index:$gameMap._interpreter._index,
   commandCount:$gameMap._interpreter._list.length,readFlags:$gameVariables.value(104)};
 if(loaded.actor!=='Shizuka Utsugi'||loaded.condition!=='Normal')throw new Error('Legacy display refresh failed');
 if(loaded.index!==source.map._interpreter._index||loaded.commandCount!==source.map._interpreter._list.length)throw new Error('Legacy interpreter changed');
 const before=JSON.stringify(source.variables._data[104]),after=JSON.stringify(loaded.readFlags);
 if(before!==after)throw new Error('Legacy read-history data changed');
 // Re-run the already-read opening from current English data through real command101.
 DataManager.loadMapData(3);while(!DataManager.isMapLoaded())await new Promise(r=>setTimeout(r,50));
 $gameMessage.clear();const i=new Game_Interpreter();i.setup($dataMap.events[1].pages[0].list,1);i._index=5;
 const header=i._list.findIndex(c=>c.code===101);i._index=header;i.command101(i.currentCommand().parameters);
 const read=$gameMessage.SkipAlreadyReadMessage.already_read;
 if(!read)throw new Error('Japanese read-history key was not recognized for English text');
 const report={actor:loaded.actor,condition:loaded.condition,indexPreserved:true,commandsPreserved:true,readFlagsPreserved:true,oldReadRecognizedInEnglish:read,message:$gameMessage.allText()};
 fs.writeFileSync('translation_tooling/text_translation/runtime/legacy_validation.json',JSON.stringify(report,null,2));
 $gameMessage.clear();await DataManager.loadGame(21);SceneManager.goto(Scene_Map);
 await new Promise(r=>setTimeout(r,1200));return report;
})()
