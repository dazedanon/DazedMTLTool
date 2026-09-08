(async()=>{
 const results={menus:[],achievementRows:[],shopRows:[]};
 SceneManager.callCustomMenu('Scene_point');await new Promise(r=>setTimeout(r,800));
 const shop=SceneManager._scene._windowLayer.children.find(w=>w._data?.Id==='product_list');
 for(let i=0;i<shop.maxItems();i++){
   shop.select(i);shop.ensureCursorVisible(false);const item=shop.getItem(i);const text=item.Text;
   results.shopRows.push({index:i,text,width:shop.textSizeEx(text).width,available:shop.itemLineRect(i).width});
   if([0,10,20,24].includes(i)){await new Promise(r=>setTimeout(r,150));tqa.capture('shop_page_'+i);}
 }
 SceneManager.pop();await new Promise(r=>setTimeout(r,600));
 const manager=Torigoya.Achievement2.Manager,old=manager._unlockInfo;
 try{
  manager._unlockInfo=new Map(manager.achievements.map(a=>[a.key,{date:Date.now()}]));
  SceneManager.push(Torigoya.Achievement2.Scene_Achievement);await new Promise(r=>setTimeout(r,700));
  const s=SceneManager._scene;
  for(let i=0;i<s._listWindow.maxItems();i++){
   s._listWindow.select(i);s._listWindow.ensureCursorVisible(false);s._listWindow.updateHelp();
   const text=s._helpWindow._text,measure=s._helpWindow.textSizeEx(text);
   results.achievementRows.push({index:i,text,width:measure.width,height:measure.height,availableWidth:s._helpWindow.innerWidth-8,availableHeight:s._helpWindow.innerHeight});
   if([0,12,17,18,23].includes(i)){await new Promise(r=>setTimeout(r,100));tqa.capture('achievement_'+i);}
  }
  SceneManager.pop();await new Promise(r=>setTimeout(r,500));
 }finally{manager._unlockInfo=old;}
 Scene_Title.prototype.commandRecollection.call({});await new Promise(r=>setTimeout(r,1000));
 tqa.capture('gallery_home');results.menus.push({name:'gallery',commands:SceneManager._scene._rec_window._list});
 SceneManager._scene.commandShowRecollection();await new Promise(r=>setTimeout(r,600));tqa.capture('gallery_list');
 SceneManager.pop();await new Promise(r=>setTimeout(r,500));
 results.pass=results.shopRows.every(r=>r.width<=r.available)&&results.achievementRows.every(r=>r.width<=r.availableWidth&&r.height<=r.availableHeight);
 tqa.save('final_ui_validation',results);return results;
})()
