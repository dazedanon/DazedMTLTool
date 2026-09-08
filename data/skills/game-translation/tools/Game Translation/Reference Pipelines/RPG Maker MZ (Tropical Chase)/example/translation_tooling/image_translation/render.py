"""Reproducible image lettering. Reads only the pinned pristine PNG sources.

User selected local lettering, with generation available for difficult repairs.
No installed game assets are written by this renderer.
"""
from pathlib import Path
import hashlib, json, sys, math
from collections import Counter
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import imgtl

HERE = Path(__file__).resolve().parent
REVIEW = HERE.parent / 'image_review'
PINS = {r['id']: r for r in json.loads((REVIEW/'pinned.json').read_bytes())['pins']}
FONT = Path('C:/Windows/Fonts')
FONTS = {'sans':'arial.ttf', 'bold':'arialbd.ttf', 'round':'comicbd.ttf',
         'heavy':'ariblk.ttf', 'condensed':'bahnschrift.ttf', 'script':'segoeprb.ttf'}
S = 4

def digest(data): return hashlib.sha256(data).hexdigest()

def lettering(text, size, font='sans', fill=(255,255,255,255), stroke=0,
              outline=(0,0,0,220), max_width=None, max_height=None):
    """Supersample coverage only: no coloured-RGB resampling fringes."""
    requested = size
    while True:
        f = ImageFont.truetype(str(FONT/FONTS[font]), round(size*S))
        box = f.getbbox(text, stroke_width=round(stroke*S))
        w,h = box[2]-box[0], box[3]-box[1]
        if (max_width is None or w/S <= max_width) and (max_height is None or h/S <= max_height): break
        size -= .25
        if size < 8: raise ValueError(('Text cannot fit',text,max_width,max_height))
    masks=[]
    for sw in (stroke,0):
        mask=Image.new('L',(w+S*2,h+S*2))
        ImageDraw.Draw(mask).text((S-box[0],S-box[1]),text,font=f,fill=255,stroke_width=round(sw*S),stroke_fill=255)
        mask=mask.resize((math.ceil(mask.width/S),math.ceil(mask.height/S)),Image.Resampling.LANCZOS)
        masks.append(mask)
    rgba=Image.new('RGBA',masks[0].size)
    for color,mask in zip((outline,fill),masks):
        col=tuple(color) if len(color)==4 else (*color,255)
        layer=Image.new('RGBA',mask.size,col)
        layer.putalpha(mask.point(lambda a: round(a*col[3]/255)))
        rgba=Image.alpha_composite(rgba,layer)
    bb=rgba.getbbox()
    return rgba.crop(bb), {'font':str(FONT/FONTS[font]),'requested_size':requested,'size':size,'stroke':stroke,'text':text}

class Job:
    def __init__(self, ident):
        self.id=ident; self.pin=PINS[ident]
        p=REVIEW/self.pin['source_png']; raw=p.read_bytes()
        assert digest(raw)==self.pin['decoded_sha256'], p
        self.src=Image.open(p); self.info=dict(self.src.info)
        self.src=self.src.convert('RGBA'); self.base=self.src.copy()
        self.layers=[]; self.regions=[]
        self.protect=[]
        self.allow=Image.new('L',self.src.size)
        self.erase_mask=Image.new('L',self.src.size)

    def allowbox(self,box):
        x0,y0,x1,y1=box
        assert 0<=x0<x1<=self.src.width and 0<=y0<y1<=self.src.height, (self.id,box)
        ImageDraw.Draw(self.allow).rectangle((x0,y0,x1-1,y1-1),fill=255)

    def flat(self,box,color=None):
        self.allowbox(box)
        if color is None: color=self.src.getpixel((box[0],box[1]))
        self.base.paste(color,box)
        ImageDraw.Draw(self.erase_mask).rectangle((box[0],box[1],box[2]-1,box[3]-1),fill=255)

    def erase(self,box,kind='white',grow=2):
        """Mask known glyph colours within an audited text region only.
        Use the shared pure-ink detector; repair with surrounding native pixels.
        """
        self.allowbox(box)
        a=np.asarray(self.src.crop(box)); rgb=a[...,:3].astype(float)
        if kind=='white':
            mask=imgtl.glyph_mask_pure(self.src,box,thr=180,halo=2,grow=grow,dark_delta=18)
        elif kind=='color':
            mask=((rgb.max(2)-rgb.min(2)>65)&(rgb.max(2)>155)) | (rgb.min(2)>175)
            mask=cv2.dilate(mask.astype('uint8'),np.ones((grow*2+1,grow*2+1),np.uint8))>0
        elif kind=='dark':
            mask=rgb.max(2)<170
            mask=cv2.dilate(mask.astype('uint8'),np.ones((grow*2+1,grow*2+1),np.uint8))>0
        elif kind=='all': mask=np.ones(a.shape[:2],bool)
        else: raise ValueError(kind)
        whole=np.zeros((self.src.height,self.src.width),np.uint8)
        whole[box[1]:box[3],box[0]:box[2]]=mask.astype('uint8')*255
        # Inpaint sees the complete frame; the write is strictly mask-limited.
        old=np.asarray(self.base).copy()
        repaired=cv2.inpaint(old[...,:3],whole,3,cv2.INPAINT_NS)
        old[whole>0,:3]=repaired[whole>0]
        self.base=Image.fromarray(old)
        self.erase_mask=Image.fromarray(np.maximum(np.asarray(self.erase_mask),whole))

    def text(self,source,target,box,size=22,font='sans',fill=(255,255,255,255),stroke=0,
             outline=(0,0,0,220),align='left',rotate=0):
        self.allowbox(box)
        dims=(box[2]-box[0],box[3]-box[1])
        maxw,maxh=dims if rotate==0 else dims[::-1]
        layer,rec=lettering(target,size,font,fill,stroke,outline,maxw-2,maxh-2)
        if rotate: layer=layer.rotate(rotate,expand=True)
        x=box[0] if align=='left' else box[0]+(dims[0]-layer.width)//2
        y=box[1]+(dims[1]-layer.height)//2
        assert x+layer.width<=box[2] and y+layer.height<=box[3], (target,box,layer.size)
        self.layers.append((layer,(x,y)))
        self.regions.append({'source':source,'target':target,'box':list(box),'ink_box':[x,y,x+layer.width,y+layer.height],**rec})

    def save(self):
        out=self.base.copy()
        for layer,xy in self.layers: out.alpha_composite(layer,xy)
        for mask in self.protect: out.paste(self.src,(0,0),mask)
        before=np.asarray(self.src); after=np.asarray(out)
        changed=np.any(before!=after,axis=2)
        assert not np.any(changed & (np.asarray(self.allow)==0)),self.id
        name=self.pin['path'][:-1]
        dst=HERE/'out'/name; dst.parent.mkdir(parents=True,exist_ok=True)
        kwargs={k:self.info[k] for k in ('icc_profile','dpi') if k in self.info}
        out.save(dst,**kwargs)
        for folder,img in [('base',self.base),('mask',self.erase_mask),('allow',self.allow)]:
            p=HERE/folder/f'{self.id}.png'; p.parent.mkdir(exist_ok=True); img.save(p)
        rec={'id':self.id,'path':self.pin['path'],'source_sha256':self.pin['sha256'],
             'source_png_sha256':self.pin['decoded_sha256'],'output_sha256':digest(dst.read_bytes()),
             'size':list(out.size),'mode':out.mode,'changed_pixels':int(changed.sum()),
             'outside_allowed_changed':0,'regions':self.regions,'technique':'local lettering',
             'review':'pending','output':dst.relative_to(HERE).as_posix()}
        if self.id in (112,603):
            rec['technique']='built-in imagegen logo; local masked compositing'
            rec['generation_input_sha256']=digest((HERE/'title_edit_input.png').read_bytes())
            rec['generation_output_sha256']=digest((HERE/'title_generated.png').read_bytes())
            rec['generation_prompt']='title_prompt.txt'
        (HERE/'records').mkdir(exist_ok=True)
        (HERE/'records'/f'{self.id}.json').write_text(json.dumps(rec,ensure_ascii=False,indent=2),encoding='utf-8')
        print(self.id,name,len(self.regions))
        return out

def credit(ident,lines):
    j=Job(ident)
    for jp,en,y0,y1,size in lines:
        b=(12,y0,382,y1); j.flat(b,(0,0,0,173)); j.text(jp,en,b,size,'bold',align='center')
    return j.save()

def credits():
    creditspec={
      110:[('◆キャスト','CAST',48,83,25),('空木静香','Shizuka Utsugi',290,327,25),('"ビッグディック"ジョージ・コロッサル','George "Big Dick" Colossal',532,568,24)],
      111:[('◆キャスト','CAST',48,83,25),('男ども','The Men',302,336,25),('警察署長','Police Chief',530,568,25)],
      113:[('◆制作','PRODUCTION',244,283,25),('豪放磊落','Goho Rairaku',284,323,32)],
      114:[('◆原案','ORIGINAL CONCEPT',244,283,25)],
      115:[('◆キャラクターデザイン','CHARACTER DESIGN',244,283,25),('豪放磊落','Goho Rairaku',284,323,32)],
      116:[('◆イベントスチル','EVENT ILLUSTRATIONS',244,283,25),('豪放磊落','Goho Rairaku',284,323,32)],
      117:[('◆キャラチップ','CHARACTER SPRITES',95,134,25),('豪放磊落','Goho Rairaku',138,177,32),('ぴぽや倉庫','Pipoya Warehouse',226,270,30),('ぴぽや','Pipoya',273,314,30),('白黒洋菓子店','Noir et Blanc Patisserie',414,457,28)],
      118:[('◆タイルセット','TILESETS',98,140,25),('豪放磊落','Goho Rairaku',142,182,32),('ハト タイルセット','Hato Tilesets',232,276,30),('広報ハト','Koho Hato',276,316,30),('コミュ将','Com Sho',443,484,32)],
      119:[('◆音楽・効果音','MUSIC & SOUND EFFECTS',45,84,23),('創作堂さくら紅葉','Sousakudou Sakura Momiji',83,127,28),('にっちぃ。','Nicchi.',126,165,30),('泡沫堂','Utakata-do',165,204,30),('やっすん','Yassun',209,248,30),('えだまめ88','Edamame 88',328,369,32),('効果音ラボ','Sound Effect Lab',490,534,32)],
      120:[('ゆうり(Yuli Audio Craft)','Yuli (Yuli Audio Craft)',158,201,30),('のる','Noru',258,298,30)],
      121:[('◆プラグイン','PLUGINS',16,55,25),('豪放磊落','Goho Rairaku',59,101,32),('トリアコンタン','Triacontane',154,197,32)],
      122:[('まこねっと','Maconetto',38,78,30),('奏ねこま','Otobuki Nekoma',78,116,30),('マンカインド','Mankind',330,370,30),('ケケー','Keke',480,521,30)],
      123:[('ルルの教会',"Lulu's Church",77,119,30),('しぐれん','Siguren',452,492,30)],
      124:[('砂川赳','Takeshi Sunagawa',72,111,29),('鳥小屋ポータRu','Torigoya Portal',317,360,30),('Ruたん','Ru-tan',360,401,30),('りんねぐりっど','Rinne Grid',509,550,30)],
      125:[('むーてぃ(翻訳・改変)','Mooty (translation / edits)',161,203,27)],
      127:[('◆テストプレイ','PLAYTESTING',143,184,25),('タダノ＝ヒナリ','Tadano = Hinari',287,331,30)],
    }
    for ident,lines in creditspec.items(): credit(ident,lines)

def simple():
    # Two equal-height frames are an atlas, not two independent buttons.
    for ident,jp,en,col in [(605,'はじめから','New Game',(247,0,94)),(606,'つづきから','Continue',(0,182,230)),(607,'回想モード','Gallery',(232,190,0)),(608,'オプション','Options',(17,17,17))]:
        j=Job(ident);j.flat((0,0,200,100),(255,255,255,0))
        for frame in range(2):
            outline=col if frame==0 else tuple(round(v*.65) for v in col)
            fill=(255,255,255,255) if frame==0 else (165,165,165,255)
            j.text(jp,en,(2,frame*50+2,198,frame*50+48),32,'round',fill,3,(*outline,255),align='center')
        j.save()
    j=Job(571);j.flat((238,197,564,340),(0,0,0,255))
    j.text('豪放磊落','Goho Rairaku',(208,221,608,327),51,'script',align='center');j.save()
    j=Job(572);j.flat((82,161,735,429),(0,0,0,255))
    j.text('本作品はフィクションです。','This is a work of fiction.',(65,150,751,193),34,'bold',align='center')
    paragraphs=[
      ['All people, groups, organizations, companies, countries, regions, facilities, events,',
       'systems, cultures, customs, religions, beliefs, ethnicities, races, ideologies, convictions,',
       'political positions, social values, and all other names, settings and depictions in this',
       'work are fictional and have no connection to their real-world counterparts.'],
      ["Characters' words, actions, beliefs and values, and all other depictions, are not intended",
       'to express support, rejection, criticism, insult, discrimination or ridicule toward any',
       'individual, group, race, ethnicity, nationality, religion, ideology, belief, political position,',
       'occupation, social class, culture or way of life.'],
      ['Any resemblance to real people, groups, events, beliefs, cultures or other real-world',
       'subjects is purely coincidental and does not imply a direct connection to this work.'],
      ['Please bear this in mind and enjoy the story as a wholly fictional work.']]
    y=219
    for para in paragraphs:
        for line in para:
            j.text('フィクション免責文',line,(60,y,756,y+22),16,'sans',align='center');y+=23
        y+=15
    j.save()
    for ident in range(132,139):
        j=Job(ident)
        b=(68,376,127,401); j.allowbox(b)
        # Complete black fill + white stroke. A nearby clean sea patch is a
        # better donor than thresholding black, which leaves the white outline.
        j.base.paste(j.src.crop((68,350,127,375)),(68,376))
        ImageDraw.Draw(j.erase_mask).rectangle((68,376,126,400),fill=255)
        j.text('現在地','You are here',(68,374,201,404),18,'bold',(0,0,0,255),1.5,(255,255,255,255));j.save()
    j=Job(563)
    for jp,en,b in [('エナジードリンク','Energy Drink',(37,87,251,122)),('スタミナドリンク','Stamina Drink',(310,87,535,122)),('バッテリー','Battery',(609,87,759,122))]:
        j.flat(b,(255,255,255,0));j.text(jp,en,b,26,'bold',(0,0,0,255),1.5,(255,255,255,255),align='center')
    j.save()

def ui(j,jp,en,erase,draw=None,size=21,kind='white',color=(255,255,255,255),font='sans',stroke=1):
    j.erase(erase,kind)
    j.text(jp,en,draw or erase,size,font,color,stroke,(20,20,20,190))

def tutorials():
    j=Job(540)
    # Preserve the key diagram and its coloured legend cells exactly.
    rows=[('Z：決定・スタンガン使用','Z: Confirm / Use stun gun',(39,221,298,241),(255,0,0,255)),
          ('X：キャンセル・メニューを開く','X: Cancel / Open menu',(39,245,298,265),(255,255,0,255)),
          ('A：メッセージ自動送り','A: Auto-advance text',(39,269,298,289),(0,255,0,255)),
          ('S：既読スキップ','S: Skip read text',(39,293,298,313),(173,67,229,255)),
          ('カーソル：移動・カーソル移動','Arrows: Move / Navigate',(346,221,606,241),(255,153,153,255)),
          ('Shift：ダッシュ（押しながら移動）','Shift: Run (hold to move)',(346,244,690,266),(0,255,255,255)),
          ('メッセージウインドウを隠す/出す','          Show/hide message window',(346,266,690,288),(0,255,255,255))]
    for jp,en,b,c in rows:
        # Sample the actual flat tint, including the purple legend.
        j.flat(b,Counter(j.src.crop(b).get_flattened_data()).most_common(1)[0][0])
        j.text(jp,en,b,18,'bold',(0,0,0,255))
    j.save()
    for ident in (541,543):
        j=Job(ident)
        offset=-2 if ident==543 else 0
        for jp,en,y in [('ドリンク','Drinks',111),('所持品','Items',146),('実績','Achievements',182),('設定','Options',218),('ゲーム終了','Quit Game',253)]:
            b=(18,y+offset,196,y+offset+29)
            ui(j,jp,en,b,size=23)
        ui(j,'空木 静香 ｳﾂｷﾞｼｽﾞｶ','Shizuka Utsugi',(234,105,387,132),(237,105,447,132),size=20)
        stamina='100%' if ident==541 else '67%'
        for jp,en,y,col in [
          ('スタミナ残量','Stamina: '+stamina,168,(0,212,100,255)),
          ('絶頂回数','Orgasms: 0',198,(225,191,52,255)),
          ('膣内射精回数','Vaginal creampies: 0',227,(225,191,52,255)),
          ('直腸射精回数','Anal creampies: 0',255,(225,191,52,255)),
          ('状態:通常','Condition: Normal',283,(225,191,52,255))]:
            b=(235,y+offset,429,y+offset+27)
            ui(j,jp,en,b,draw=(237,y+offset,429,y+offset+27),size=20,kind='color',color=col)
        if ident==543: ui(j,'ドリンクを使用する。','Use a drink.',(16,57,221,83),(17,55,416,84),22)
        j.save()
    j=Job(544)
    j.erase((205,28,370,53),'all')
    # Black callout letters have a thick white outline.
    j.text('プレイヤーの残りHP','Player HP remaining',(207,25,426,57),19,'bold',(0,0,0,255),2,(255,255,255,255))
    for jp,en,box,draw in [('スタミナ残量(ダッシュ時のみ表示)','Stamina (shown while running)',(11,146,278,168),(12,143,341,171)),
                         ('スタンガン残り使用回数','Stun gun charges',(423,94,610,118),(426,94,625,120))]:
        j.erase(box,'all');j.text(jp,en,draw,17,'bold',(0,0,0,255),2,(255,255,255,255))
    ui(j,'スタンガンバッテリー','Stun gun battery',(451,23,566,49),(451,23,566,49),13,'all',(133,161,232,255))
    j.save()
    for ident in (552,553):
        j=Job(ident)
        for jp,en,y in [('無条件①','No Conditions 1',57),('無条件②','No Conditions 2',93)]:
            ui(j,jp,en,(47,y,144,y+28),(49,y,310,y+28),22)
        if ident==552:
            ui(j,'【解放条件】','[Unlock Requirement]',(17,432,143,459),(17,431,368,461),22)
            ui(j,'実績を５個達成する','Earn 5 achievements.',(14,462,212,488),(17,462,470,488),21)
        else:
            ui(j,'他の条件を満たさずに捕まる','Get caught without meeting any other condition.',(14,432,293,460),(17,432,632,462),22)
        j.save()
    j=Job(554)
    ui(j,'体力','HP',(23,24,73,49),(25,23,77,50),22,'all',(142,159,230,255))
    ui(j,'スタンガンバッテリー','Stun gun battery',(449,25,552,48),(449,25,557,48),13,'all',(142,159,230,255))
    j.erase((153,82,419,108),'all')
    j.text('スタミナ残量(ダッシュ時のみ表示)','Stamina (shown while running)',(153,80,484,111),17,'bold',(225,0,0,255),2,(255,255,255,255));j.save()
    j=Job(558)
    for jp,en,y in [('捕まった回数','Times caught',93),('絶頂回数','Orgasms',121),('膣内射精回数','Vaginal creampies',150),('直腸射精回数','Anal creampies',179),('ドリンク所持数','Drinks held',208),('バッテリー残量','Battery remaining',237),('おとしもの回収','Lost items found',266)]:
        b=(158,y,312,y+27); j.erase(b,'white')
        j.text(jp,en,b,19,'condensed',(245,245,245,255),.65,(80,80,94,255))
    ui(j,'合計','Total',(347,322,402,351),(343,322,418,352),22,'all')
    j.save()
    j=Job(559)
    ui(j,'どのファイルにセーブしますか？','Which file would you like to save to?',(263,40,502,63),(264,40,724,64),17)
    for n,y in enumerate([78,136,194,252,311],1):
        ui(j,f'ファイル {n}',f'File {n}',(264,y,352,y+26),(268,y,379,y+26),18)
    # Restore the red/white arrow that overlaps the third file label's margin.
    ar=(230,157,284,223); protect=Image.new('L',j.src.size)
    a=np.asarray(j.src); region=np.zeros(a.shape[:2],bool);region[157:223,230:284]=True
    red=region&(a[:,:,0]>200)&(a[:,:,1]<80)&(a[:,:,2]<80)
    arrow=cv2.dilate(red.astype('uint8'),np.ones((7,7),np.uint8))>0
    # This protection is applied after all lettering in the dedicated overlay.
    j.protect.append(Image.fromarray(arrow.astype('uint8')*255))
    j.save()
    j=Job(560)
    ui(j,'所持ポイント','Points:',(265,44,368,65),(268,42,365,65),17,'color',(234,191,61,255))
    for jp,en,y in [('エナジードリンク','Energy Drink',96),('スタミナドリンク','Stamina Drink',125)]:
        ui(j,jp,en,(266,y,380,y+25),(268,y,406,y+25),17)
    shop=[('エナジードリンク','Energy Drink'),('スタミナドリンク','Stamina Drink'),
          ('実績◆ゲームを１回プレイする','Achievement: Play once'),('実績◆ゲームを２回プレイする','Achievement: Play twice'),
          ('実績◆ゲームを３回プレイする','Achievement: Play 3 times'),('実績◆ゲームを５回プレイする','Achievement: Play 5 times'),
          ('実績◆シュノーケルを拾得','Achievement: Find a snorkel'),('実績◆車のキーを拾得','Achievement: Find car keys'),
          ('実績◆メガネを拾得','Achievement: Find glasses'),('実績◆サイフを拾得','Achievement: Find a wallet')]
    for n,(jp,en) in enumerate(shop):
        y=43+26.5*n; b=(446,round(y),686,round(y+23))
        ui(j,jp,en,b,(447,b[1],687,b[3]),16)
    ui(j,'実績を解放します','Unlock an achievement.',(263,322,396,345),(265,321,622,347),17)
    j.save()
    j=Job(561)
    ui(j,'回想シーン1','Gallery Scene 1',(340,9,444,29),(324,7,461,30),15)
    for jp,en,y in [('回想を見る','Replay scene',211),('CGを見る','View CG',238),('戻る','Back',263)]:
        ui(j,jp,en,(531,y,619,y+24),(522,y,631,y+24),16)
    j.save()

def poster():
    j=Job(141); yellow=j.src.getpixel((525,30)); red=(240,0,0,255)
    j.flat((521,36,619,577),yellow)
    j.text('国際指名手配','WANTED WORLDWIDE',(595,38,619,289),17,'bold',(0,0,0,255),rotate=-90,align='center')
    j.text('ヘイ、ジョージ！','HEY, GEORGE!',(521,57,597,574),61,'heavy',red,rotate=-90,align='center')
    j.flat((304,396,441,419),yellow)
    j.text('連続婦女暴行犯','Serial rapist',(250,395,508,419),20,'bold',align='center')
    j.flat((269,419,475,428),yellow) # Remove Japanese pronunciation above the unchanged Latin name.
    j.regions.append({'source':'ジョージ コロッサル','target':'George Colossal (Latin original retained)','box':[269,419,475,428]})
    j.flat((243,456,512,531),red)
    j.text('特別報奨金','SPECIAL REWARD',(243,455,512,486),23,'bold',align='center')
    j.text('５００万円（上限額）','UP TO ¥5,000,000',(243,485,512,529),27,'heavy',(255,255,255,255),1.1,(0,0,0,255),align='center')
    j.flat((243,539,510,567),j.src.getpixel((233,541)))
    j.text('情報をお寄せください','Please send us information',(239,538,529,568),21,'bold',(0,0,0,255),align='center')
    j.save()

if __name__=='__main__':
    selected=sys.argv[1:] or ['credits','simple']
    for name in selected: globals()[name]()
