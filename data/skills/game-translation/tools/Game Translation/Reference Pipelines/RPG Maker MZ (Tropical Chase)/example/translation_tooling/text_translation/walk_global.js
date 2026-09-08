(()=>{
 tqa.gwalk=async(gx,gy,ms=25000)=>{
  const stop=Date.now()+ms;let route=[];
  const plan=()=>{
   const W=$gameMap.width(),H=$gameMap.height(),start=$gamePlayer.x+$gamePlayer.y*W,goal=gx+gy*W;
   const previous=new Int32Array(W*H).fill(-1),dirs=new Uint8Array(W*H),queue=[start];previous[start]=start;
   for(let at=0;at<queue.length&&previous[goal]===-1;at++){
    const n=queue[at],x=n%W,y=Math.floor(n/W);
    for(const d of [2,4,6,8]){
     const nx=$gameMap.roundXWithDirection(x,d),ny=$gameMap.roundYWithDirection(y,d),next=nx+ny*W;
     if(nx<0||ny<0||nx>=W||ny>=H||previous[next]!==-1||!$gamePlayer.canPass(x,y,d))continue;
     previous[next]=n;dirs[next]=d;queue.push(next);
    }
   }
   if(previous[goal]===-1)return [];
   const path=[];for(let n=goal;n!==start;n=previous[n])path.push(dirs[n]);return path.reverse();
  };
  while(Date.now()<stop&&($gamePlayer.x!==gx||$gamePlayer.y!==gy)){
   if($gameMessage.isBusy())break;
   if(!$gamePlayer.isMoving()&&$gamePlayer.canMove()){
    if(!route.length)route=plan();if(!route.length)break;
    const d=route.shift();if(!$gamePlayer.canPass($gamePlayer.x,$gamePlayer.y,d)){route=[];continue;}
    $gamePlayer.executeMove(d);
   }
   await new Promise(r=>setTimeout(r,40));
  }
  return tqa.status();
 };
 return {globalPathfindingReady:true};
})()
