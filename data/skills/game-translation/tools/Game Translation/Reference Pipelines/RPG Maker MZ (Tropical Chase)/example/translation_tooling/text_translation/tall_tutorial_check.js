(async()=>{
 SceneManager.callCustomMenu('Scene_tutorial');await new Promise(r=>setTimeout(r,600));
 const s=SceneManager._scene,w=s._windowLayer.children.find(w=>w._data?.Id==='Tutorial_list');
 if(!w)throw new Error('Tutorial list missing');
 w.select(1);w.ensureCursorVisible(false);w.processOk();
 const rows=[],seen=new Set(),until=Date.now()+20000;
 while(Date.now()<until){
  const text=$gameMessage.allText(),m=SceneManager._scene._messageWindow;
  if(m?.pause&&!seen.has(text)){
   seen.add(text);const size=m.textSizeEx(text);
   rows.push({text,width:size.width,height:size.height,windowHeight:m.height,innerHeight:m.innerHeight});
   tqa.capture('tutorial_menu_'+rows.length);
  }
  if(m?.pause||m?._textState){Input._currentState.ok=true;await new Promise(r=>setTimeout(r,80));Input._currentState.ok=false;}
  await new Promise(r=>setTimeout(r,100));
  if(rows.length>=5&&!$gameMessage.isBusy())break;
 }
 const tall=rows.filter(r=>r.text.split('\n').length===4);
 const result={scope:'Selected Menu from the actual Tutorial menu; source CommonEvent33 manages window height',rows,pass:rows.length===5&&tall.length===3&&tall.every(r=>r.windowHeight===192&&r.height<=r.innerHeight)};
 tqa.save('tall_tutorial_validation',result);
 await DataManager.loadGame(24);SceneManager.goto(Scene_Map);await new Promise(r=>setTimeout(r,700));
 return result;
})()
