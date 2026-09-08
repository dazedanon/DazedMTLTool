(async()=>{
 $gameSystem.onBeforeSave();await DataManager.saveGame(24);
 // Match Map010 event 28's preparation: actor 8 is a map utility and leaves combat.
 $gameParty.removeActor(8);
 for(const c of $dataCommonEvents[34].list.filter(c=>c.code===357))PluginManager.callCommand(new Game_Interpreter(),c.parameters[0],c.parameters[1],c.parameters[3]);
 const troopId=$gameVariables.value(4)||1;
 BattleManager.setup(troopId,false,true);SceneManager.push(Scene_Battle);
 for(let k=0;k<70&&!BattleManager.isInputting();k++){
  if($gameMessage.isBusy()){Input._currentState.ok=true;await new Promise(r=>setTimeout(r,70));Input._currentState.ok=false;}
  await new Promise(r=>setTimeout(r,100));
 }
 const s=SceneManager._scene;tqa.capture('battle_start');
 if(s._partyCommandWindow.active)s.commandFight();await new Promise(r=>setTimeout(r,300));
 const actor=BattleManager.actor()||$gameActors.actor(9),rows=[];
 if(!BattleManager.isInputting())throw new Error('Battle never reached input');
 s._actorCommandWindow.selectSymbol('skill');s._actorCommandWindow.processOk();
 await new Promise(r=>setTimeout(r,150));
 if(!s._skillWindow.active||!s._skillWindow.visible)throw new Error('Native skill command failed to open skill window');
 for(let i=0;i<s._skillWindow.maxItems();i++){
  s._skillWindow.select(i);s._skillWindow.ensureCursorVisible(false);s._skillWindow.updateHelp();
  const item=s._skillWindow.item(),m=s._helpWindow.textSizeEx(item.description);
  rows.push({id:item.id,name:item.name,description:item.description,width:m.width,height:m.height,limitWidth:s._helpWindow.innerWidth-8,limitHeight:s._helpWindow.innerHeight});
  await new Promise(r=>setTimeout(r,100));tqa.capture('skill_'+item.id);
 }
 const skillNames=rows.map(r=>r.name);if(!skillNames.includes('Blind'))throw new Error('Corrected skill name missing from native battle menu');
 const result={scope:'Native battle and active skill-menu fixture, with the same party preparation and troop variable as Map010 event 28; not a normal-world battle trigger',troopId,party:$gameParty.battleMembers().map(a=>a.name()),rows,skillWindowActive:s._skillWindow.active,pass:rows.every(r=>r.width<=r.limitWidth&&r.height<=r.limitHeight)&&s._skillWindow.active};
 tqa.save('battle_ui_validation',result);
 BattleManager.abort();await new Promise(r=>setTimeout(r,800));
 await DataManager.loadGame(24);SceneManager.goto(Scene_Map);await new Promise(r=>setTimeout(r,1000));return result;
})()
