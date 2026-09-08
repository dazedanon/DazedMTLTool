// Execute the generated shipping append itself against an unmodified real save.
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert'),crypto=require('crypto');
const saveFile=path.resolve(process.argv[2] || path.join(__dirname,'../../reports/fixtures/musi_dream_tyrano_data.sav'));
const bytes=fs.readFileSync(saveFile),hash=x=>crypto.createHash('sha256').update(x).digest('hex');
const saveRoot=JSON.parse(unescape(bytes.toString('utf8'))),source=saveRoot.data[0],clone=x=>JSON.parse(JSON.stringify(x));
const code=fs.readFileSync(path.join(__dirname,'save_compat_append.js'),'utf8');
const display=JSON.parse(code.match(/var display = ([^\r\n]+);/)[1]);
let calls=0;const menu={getSaveData:()=>clone(saveRoot),loadGameData:function(data,options){calls++;assert.strictEqual(options,'unchanged-options');return data;}};
const context={tyrano:{plugin:{kag:{menu}}}};vm.createContext(context);vm.runInContext(code,context);
const migrate=data=>menu.loadGameData(data,'unchanged-options');
const find=(node,cls)=>{if(!node||typeof node!=='object')return null;if((' '+(node.class||'')+' ').includes(' '+cls+' '))return node;for(const child of node.children||[]){const hit=find(child,cls);if(hit)return hit;}return null;};
const leafText=node=>!node.tag?node.text:(node.children||[]).map(leafText).join('');
const attrs=node=>{let result=[];if(node&&typeof node==='object'){if(node.attr&&Object.keys(node.attr).length)result.push(JSON.stringify(node.attr));for(const child of node.children||[])result=result.concat(attrs(child));}return result;};
const oldMessage=find(source.layer.map_layer_fore.message0,'message_inner');
const result=migrate(clone(source));
const expected=display.scenarios['data/scenario/scene1.ks'].rows.find(x=>x[0]===source.current_order_index)[2];
const message=find(result.layer.map_layer_fore.message0,'message_inner');
assert.strictEqual(message.text,expected);assert.strictEqual(leafText(message),expected);
const name=find(result.layer.map_layer_fore.message0,'chara_name_area');
assert.strictEqual(leafText(name),display.names['底辺Ytuberヒマリィ']);
assert.strictEqual(result.stat.current_message_str,expected);
assert.strictEqual(result.stat.current_speaker,display.names['底辺Ytuberヒマリィ']);
assert.strictEqual(result.title,display.names['底辺Ytuberヒマリィ']+': '+expected);
assert(result.stat.current_save_str.includes('>'+expected+'</span>'));
assert(result.stat.current_save_str.includes('class="backlog_chara_name 底辺Ytuberヒマリィ"'));
const menuSave=menu.getSaveData();assert.strictEqual(menuSave.hash,saveRoot.hash);assert.strictEqual(menuSave.data[0].title,result.title);
for(let i=0;i<saveRoot.data.length;i++)if(!saveRoot.data[i].stat&&display.captions[saveRoot.data[i].title])assert.strictEqual(menuSave.data[i].title,display.captions[saveRoot.data[i].title]);
for(const key of Object.keys(source.stat))if(!['current_message_str','current_save_str','current_speaker'].includes(key))assert.deepStrictEqual(result.stat[key],source.stat[key],'Protected stat '+key);
for(const key of Object.keys(source))if(!['title','stat','layer'].includes(key))assert.deepStrictEqual(result[key],source[key],'Protected slot '+key);
assert.strictEqual(message.style,oldMessage.style);assert.strictEqual(find(message,'current_span').style,find(oldMessage,'current_span').style);
for(const group of ['map_layer_fore','map_layer_back'])for(const key of Object.keys(source.layer[group]))assert.deepStrictEqual(attrs(result.layer[group][key]),attrs(source.layer[group][key]),'DOM event attributes '+group+'/'+key);
const stable=JSON.stringify(result);migrate(result);assert.strictEqual(JSON.stringify(result),stable,'Migration must be idempotent');
const jpName='底辺Ytuberヒマリィ',enName=display.names[jpName];
const englishNext=display.scenarios['data/scenario/scene1.ks'].rows.find(x=>x[0]===10)[2];
const mixed=clone(result);mixed.current_order_index=10;mixed.stat.current_speaker=jpName;mixed.stat.current_message_str=englishNext;
mixed.title=jpName+'：'+englishNext;
mixed.stat.current_save_str='<b class="backlog_chara_name '+jpName+'">'+jpName+'</b>：<span class="backlog_text '+jpName+'">'+englishNext+'</span>';
migrate(mixed);assert.strictEqual(mixed.stat.current_speaker,enName);assert.strictEqual(mixed.stat.current_message_str,englishNext);
assert.strictEqual(mixed.title,enName+': '+englishNext);assert(mixed.stat.current_save_str.includes('>'+enName+'</b>'));
assert(mixed.stat.current_save_str.includes('class="backlog_chara_name '+jpName+'"'));assert(mixed.stat.current_save_str.includes('>'+englishNext+'</span>'));
const advanced=clone(result);advanced.current_order_index=10;advanced.stat.current_message_str=englishNext;
advanced.title=advanced.stat.current_speaker+'：'+englishNext;
advanced.stat.current_save_str='<b class="backlog_chara_name '+advanced.stat.current_speaker+'">'+advanced.stat.current_speaker+'</b>：<span class="backlog_text '+advanced.stat.current_speaker+'">'+englishNext+'</span>';
assert(!advanced.title.includes(jpName));assert(!advanced.stat.current_save_str.includes(jpName));migrate(advanced);assert.strictEqual(advanced.stat.current_speaker,enName);
for(const protectedTable of ['charas','jcharas']) {
 const registered=clone(source);registered.stat[protectedTable][jpName]=protectedTable==='charas'?{name:jpName}:'undress_bug';migrate(registered);
 assert.strictEqual(registered.stat.current_speaker,jpName,'Registered speaker key protected in '+protectedTable);
}
const technicalSpeaker=clone(source);technicalSpeaker.stat.current_speaker='undress_bug';migrate(technicalSpeaker);assert.strictEqual(technicalSpeaker.stat.current_speaker,'undress_bug');
let actualMixedSlot=false;
if(saveRoot.data[2]&&saveRoot.data[2].stat&&saveRoot.data[2].stat.current_speaker===jpName){
 const slot2=migrate(clone(saveRoot.data[2]));assert.strictEqual(slot2.stat.current_speaker,enName);assert(!slot2.title.startsWith(jpName+'：'));actualMixedSlot=true;
}
const choiceSource=Object.keys(display.choices)[0],event={text:choiceSource,target:'*日本語の技術キー',storage:'日本語.ks',exp:'f.日本語の技術キー += 1'};
const testChoice=clone(source);testChoice.stat.f['日本語の技術キー']=123;
const choice={tag:'DIV',class:'glink_button',style:'left:100px',text:choiceSource,attr:{'data-event-tag':'glink','data-event-pm':JSON.stringify(event)},children:[{text:choiceSource,attr:{},children:[]}]};
testChoice.layer.layer_free.children.push(choice);const beforeEvent=choice.attr['data-event-pm'];migrate(testChoice);
assert.strictEqual(leafText(choice),display.choices[choiceSource]);assert.strictEqual(choice.attr['data-event-pm'],beforeEvent);assert.strictEqual(testChoice.stat.f['日本語の技術キー'],123);
const maskedChoiceSource='深くゆっくり\u00a0';assert(Object.prototype.hasOwnProperty.call(display.choices,maskedChoiceSource));
const maskedFixture=clone(source),maskedChoice=clone(choice);maskedChoice.text=maskedChoiceSource;maskedChoice.children=[{text:maskedChoiceSource,attr:{},children:[]}];
maskedChoice.attr['data-event-pm']=JSON.stringify({text:'深くゆっくり&nbsp;',target:'*piston_deep_slow'});
const maskedEvent=maskedChoice.attr['data-event-pm'];maskedFixture.layer.layer_free.children.push(maskedChoice);migrate(maskedFixture);
assert.strictEqual(leafText(maskedChoice),display.choices[maskedChoiceSource]);assert.strictEqual(maskedChoice.attr['data-event-pm'],maskedEvent);assert(!/⟦\d+⟧/.test(code));
let scopedCases=0,allProseCases=0;
for(const [scenario,entry] of Object.entries(display.scenarios))for(const row of entry.rows){
 const fixture=clone(source);fixture.stat.current_scenario=scenario;fixture.current_order_index=row[0];fixture.stat.current_message_str=row[1];
 const wrapper=find(fixture.layer.map_layer_fore.message0,'current_span').children[0];wrapper.text=row[1];wrapper.children=[{tag:'SPAN',class:'char',style:'opacity:1',text:row[1],attr:{},children:[{text:row[1],attr:{},children:[]}]}];
 migrate(fixture);assert.strictEqual(wrapper.text,row[2],'Saved prose '+scenario+':'+row[0]);allProseCases++;
 if(!Object.prototype.hasOwnProperty.call(display.unique,row[1]))scopedCases++;
}
assert.strictEqual(hash(fs.readFileSync(saveFile)),hash(bytes),'Baseline save changed');
console.log(JSON.stringify({baselineSave:saveFile,baselineSha256:hash(bytes),scenario:source.stat.current_scenario,index:source.current_order_index,renderedMessage:leafText(message),renderedName:leafText(name),realSaveRefresh:true,currentSpeakerRefresh:true,registeredSpeakerKeysPreserved:true,loadAdvanceSaveSimulation:true,mixedCaptionRefresh:true,actualMixedSlot,allStatKeysExceptDisplayPreserved:true,allEventAttributesPreserved:true,technicalJapaneseKeysPreserved:true,choiceRefresh:true,maskedNbspChoiceRefresh:true,noSentinels:true,saveMenuCaptionRefresh:true,backlogMarkupClassPreserved:true,idempotent:true,allProseCases,ambiguousScopedCases:scopedCases,loadCalls:calls,passed:true},null,2));
