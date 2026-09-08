(()=>{
 const sleep=ms=>new Promise(r=>setTimeout(r,ms));
 const bounds=(bitmap,test)=>{
  const {data,width,height}=bitmap.context.getImageData(0,0,bitmap.width,bitmap.height);
  let left=width,top=height,right=-1,bottom=-1;
  for(let y=0;y<height;y++)for(let x=0;x<width;x++){
   const n=(y*width+x)*4;
   if(test(data[n],data[n+1],data[n+2],data[n+3])){
    left=Math.min(left,x);right=Math.max(right,x);top=Math.min(top,y);bottom=Math.max(bottom,y);
   }
  }
  return {left,top,right:right+1,bottom:bottom+1};
 };
 tqa.resultsPanelCheck=async(label,maps=[4,14])=>{
  const rows=[],panels=[],naturals=[];
  for(const map of maps){
   // Leave the old map before replacing game objects, as the real Load scene does.
   // Otherwise sensor plugins can update old events against newly loaded map data.
   SceneManager.goto(Scene_Title);await sleep(800);
   DataManager.createGameObjects();await DataManager.loadGame(24);SceneManager.goto(Scene_Map);await sleep(1200);
   $gamePlayer.setTransparent(true);
   $gameSwitches.setValue(22,map===14);$gameSwitches.setValue(123,false);$gameSwitches.setValue(122,false);
   for(const c of $dataCommonEvents[34].list.filter(c=>c.code===357))PluginManager.callCommand(new Game_Interpreter(),c.parameters[0],c.parameters[1],c.parameters[3]);
   $gamePlayer.reserveTransfer(map,0,0,2,0);await sleep(9000);
   if($gameMap.mapId()!==map)throw new Error('Results map transfer failed: '+$gameMap.mapId());
   const sprites=SceneManager._scene._spriteset._pictureContainer.children;
   const bg=sprites.find(s=>s._pictureId===1),text=sprites.find(s=>s._pictureId===10);
   const raw=bounds(bg.bitmap,(r,g,b,a)=>a>64&&b>r+5&&b>g+5&&r>60&&r<230);
   const panel={map,left:bg.x+raw.left*bg.scale.x,top:bg.y+raw.top*bg.scale.y,right:bg.x+raw.right*bg.scale.x,bottom:bg.y+raw.bottom*bg.scale.y};
   panels.push(panel);
   naturals.push({map,points:$gameVariables.value(152),clear:$gameSwitches.value(22)});
   for(const profile of ['reported','zero','five_digit','seven_digit']){
    let v={81:2,122:16,123:6,124:0,142:200,143:160,144:120,145:0,146:100,147:0,148:0,152:580,154:1,155:0,156:0};
    if(profile!=='reported'){
     const n=profile==='zero'?0:profile==='five_digit'?99999:9999999;
     v={81:n,122:n,123:n,124:n,142:n*100,143:n*10,144:n*20,145:n*20,146:n*100,147:n*200,148:n*300,152:Math.floor((n*750+1000)*1.5),154:n,155:n,156:n};
    }
    for(const [id,n] of Object.entries(v))$gameVariables.setValue(Number(id),n);
    for(const [index,c] of $dataCommonEvents[30].list.entries()){
     if(c.code!==357||c.parameters[0]!=='TextPicture')continue;
     tqa.panelStage={map,profile,index};
     PluginManager.callCommand(new Game_Interpreter(),c.parameters[0],c.parameters[1],c.parameters[3]);
     $gameScreen.showPicture(10,'',0,208,112,100,100,255,0);await sleep(90);
     if($gameMap.mapId()!==map||!text.bitmap||text.mzkp_text!==c.parameters[3].text)throw new Error('Results consumer did not render '+JSON.stringify(tqa.panelStage));
     const ink=bounds(text.bitmap,(r,g,b,a)=>a>32);
     const displayed={left:text.x+ink.left*text.scale.x,top:text.y+ink.top*text.scale.y,right:text.x+ink.right*text.scale.x,bottom:text.y+ink.bottom*text.scale.y};
     const margins={left:displayed.left-panel.left,right:panel.right-displayed.right,top:displayed.top-panel.top,bottom:panel.bottom-displayed.bottom};
     rows.push({map,profile,index,panel,displayed,margins,scale:text.scale.x,storedPosition:[$gameScreen.picture(10).x(),$gameScreen.picture(10).y()],sourceTextPreserved:$gameScreen.picture(10).mzkp_text===c.parameters[3].text,pass:Object.values(margins).every(n=>n>=12)});
     if([70,90,102].includes(index))tqa.capture(label+'_'+map+'_'+profile+'_'+index);
    }
   }
  }
  const result={scope:'Native text ink compared with independently detected purple panel pixels, not the image canvas or screen',panels,naturals,rows,pass:rows.length===maps.length*56&&rows.every(r=>r.pass&&r.sourceTextPreserved&&r.storedPosition[0]===208&&r.storedPosition[1]===112)};
  SceneManager.goto(Scene_Title);await sleep(800);
  result.engineError=Graphics._errorPrinter?.textContent||'';
  result.pass=result.pass&&!result.engineError;
  tqa.save(label,result);
  return {pass:result.pass,cases:rows.length,failures:rows.filter(r=>!r.pass).length,panels,minimumMargins:Object.fromEntries(['left','right','top','bottom'].map(k=>[k,Math.min(...rows.map(r=>r.margins[k]))]))};
 };
 return {ready:true};
})()
