"""Manual, offline lettering for the three eligible fictional browser images.

Coordinates were read from native source crops/grid sheets. No OCR or translation
service is called. The separate Hdouga listing image is deliberately excluded.
"""
from pathlib import Path
import json,hashlib
import numpy as np
import cv2
from scipy import ndimage as ndi
from PIL import Image,ImageDraw,ImageFont
import imgtl
from web_reconstruction import recover
ROOT=Path(__file__).resolve().parent
QA=ROOT/'qa/web';QA.mkdir(parents=True,exist_ok=True)
TRANS=[];ASSETS=[]

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

class Edit:
 def __init__(self,rel):
  self.rel=rel;self.src=Image.open(ROOT/'source'/rel);self.im=self.src.convert('RGBA');self.a=np.array(self.im)
  self.clean=self.a.copy();self.mask=np.zeros(self.a.shape[:2],bool);self.regions=[];self.drawn=[]
 def erase(self,box,col=None,tol=45,fill=None,polygon=None,grow=3,predicate=None):
  x0,y0,x1,y1=box;rgb=self.a[y0:y1,x0:x1,:3].astype(float)
  if predicate is not None:m=predicate(rgb)
  elif fill is not None:
   m=np.max(np.abs(rgb-np.array(fill[:3])),axis=2)>2
  else:
   cols=col if isinstance(col[0],(list,tuple)) else [col]
   m=np.zeros(rgb.shape[:2],bool)
   for c in cols:m|=np.max(np.abs(rgb-np.array(c)),axis=2)<tol
  if polygon:
   poly=Image.new('L',self.im.size);ImageDraw.Draw(poly).polygon(polygon,fill=255)
   m &= np.array(poly)[y0:y1,x0:x1]>0
  m=ndi.binary_dilation(m,iterations=grow)
  mask=np.zeros(self.a.shape[:2],bool);mask[y0:y1,x0:x1]=m
  assert mask.sum()>0,(self.rel,box,'empty erasure')
  cur=np.array(self.im)
  if fill is not None:cur[mask,:3]=fill[:3]
  else:
   # Context surrounds the mask; fully masked tight crops are never fed to Telea.
   cx0=max(0,x0-25);cy0=max(0,y0-25);cx1=min(self.im.width,x1+25);cy1=min(self.im.height,y1+25)
   crop=cur[cy0:cy1,cx0:cx1,:3].copy();cm=mask[cy0:cy1,cx0:cx1]
   repair=cv2.inpaint(crop,cm.astype('uint8')*255,5,cv2.INPAINT_TELEA)
   cur[cy0:cy1,cx0:cx1,:3][cm]=repair[cm]
   if (self.rel.endswith('ev_Ytube.jpg') and y0>600) or (self.rel.endswith('ev_sakuzyo.jpg') and y0>1100):
    cur=recover(self.a,mask,box)
    # Preserve preceding independent English lettering and erasures.
    combined=np.array(self.im);combined[mask]=cur[mask];cur=combined
  assert np.any(cur[mask]!=np.array(self.im)[mask]),'erasure did not change pixels'
  self.clean[mask]=cur[mask];self.im=Image.fromarray(cur);self.mask|=mask;self.regions.append(list(box))
 def line(self,source,target,box,color=(70,75,72,255),font='arialbd',size=42,angle=0,align='left'):
  x0,y0,x1,y1=box
  if angle:
   # The segment preserves the source sloping/vertical baseline.
   before=np.array(self.im)
   imgtl.marker_line(self.im,target,(x0,y0),(x1,y1),size,imgtl.FONTS[font],color,ow=0,fatr=0,stretch=1.25,squash=.3)
   used=size
  else:
   fontpath=imgtl.FONTS[font]
   used=size
   while used>15:
    f=ImageFont.truetype(fontpath,used);bb=f.getbbox(target)
    if bb[2]-bb[0]<=x1-x0 and bb[3]-bb[1]<=y1-y0:break
    used-=1
   if bb[2]-bb[0]>x1-x0 or bb[3]-bb[1]>y1-y0:raise ValueError(('does not fit',target,box))
   before=np.array(self.im);d=ImageDraw.Draw(self.im)
   tx=x0-bb[0] if align=='left' else (x0+x1-(bb[2]-bb[0]))/2-bb[0]
   ty=(y0+y1-(bb[3]-bb[1]))/2-bb[1]
   d.text((tx,ty),target,font=f,fill=color)
  diff=np.any(before!=np.array(self.im),axis=2);self.mask|=diff
  ys,xs=np.where(diff);assert len(xs)>0
  self.drawn.append([int(xs.min()),int(ys.min()),int(xs.max()+1),int(ys.max()+1)])
  TRANS.append(dict(path=self.rel,source=source,target=target,draw_box=list(box),font=font,size=used,status='translated'))
 def erase_preview(self):
  # Additional preview may be captured before every lettering group.
  self.im.convert('RGB').resize((1440,810)).save(QA/(Path(self.rel).stem+'_erased_current.png'))
 def finish(self):
  out=ROOT/'output'/self.rel;out.parent.mkdir(parents=True,exist_ok=True)
  self.im.convert(self.src.mode).save(out,format='PNG',optimize=True)
  dst=Image.open(out);diff=np.any(np.array(self.src.convert('RGBA'))!=np.array(dst.convert('RGBA')),axis=2)
  assert np.count_nonzero(diff&~self.mask)==0
  assert dst.size==self.src.size and dst.mode==self.src.mode
  stem=Path(self.rel).stem
  Image.fromarray(self.clean).convert('RGB').resize((1440,810)).save(QA/(stem+'_erased.png'))
  Image.fromarray(self.mask.astype('uint8')*255).save(QA/(stem+'_mask.png'))
  self.im.convert('RGB').resize((1440,810)).save(QA/(stem+'_after.png'))
  boxes=self.regions+self.drawn
  for n,b in enumerate(boxes):
   x0,y0,x1,y1=b;b=(max(0,x0-6),max(0,y0-6),min(self.im.width,x1+6),min(self.im.height,y1+6))
   # Three columns: pristine, cleaned/redrawn, amplified local diff.
   left=self.src.crop(b).convert('RGB');right=dst.crop(b).convert('RGB')
   w,h=left.size;sheet=Image.new('RGB',(w*2,h));sheet.paste(left,(0,0));sheet.paste(right,(w,0))
   sheet.resize((w*4,h*2)).save(QA/f'{stem}_{n:02}.png')
  approved=json.loads((ROOT/'web_review.json').read_text(encoding='utf8')) if (ROOT/'web_review.json').exists() else {}
  reviewed=approved.get('outputs',{}).get(self.rel)==sha(out)
  ASSETS.append(dict(path=self.rel,source_sha256=sha(ROOT/'source'/self.rel),output_sha256=sha(out),width=dst.width,height=dst.height,mode=dst.mode,source_format=self.src.format,output_format=dst.format,status='rendered',reviewed=reviewed,changed_pixels=int(diff.sum()),outside_mask_changes=0,regions=self.regions))

def favorites(e):
 e.erase((2510,25,2740,89),fill=(167,171,183))
 e.line('お気に入り','Favorites',(2512,29,2738,86),color=(216,218,224,255),font='arial',size=44)

def caption(e,src,tgt,box,color=(76,82,78,255),size=39,background=(255,255,255)):
 e.erase(box,fill=background);e.line(src,tgt,box,color=color,size=size)

def ytube():
 e=Edit('data/bgimage/ev_Ytube.jpg');favorites(e)
 # Titles under thumbnails, leaving avatars, music note, circled 3 and hearts.
 caption(e,'大きなチューリップの育て方','How to Grow Giant Tulips',(125,805,660,866))
 # Keep the source circled 3 at x~660? Native crop review determines final bound.
 caption(e,'仲良し友達４人組で廃病院肝試し！','4 friends brave an abandoned hospital!',(1197,805,1850,867),size=32)
 caption(e,'お嬢様にゴキブリ降らせてみたドッキリｗ','Roach rain prank on a rich girl lol',(2014,805,2840,867),size=38)
 caption(e,'拘束されてきたけど楽しすぎて草','Got tied up. Way too much fun lol',(125,1495,910,1557),size=38)
 caption(e,'助けてください！虫に襲われました…','Help! A bug attacked me...',(1070,1495,1850,1557),size=40)
 caption(e,'ちなみの虫うんちく寝かしつけ','Chinami’s bug facts to lull you to sleep',(2055,1495,2630,1557),size=31)
 # Artwork lettering. Color masks are bounded to individually inspected strokes.
 e.erase((22,609,833,775),(108,72,123),tol=36,grow=3)
 e.line('大きな チューリップの育て方','GROW GIANT TULIPS',(27,632,794,761),color=(108,72,123,255),font='segoepr',size=63)
 for box,col in [((1000,652,1177,770),(245,184,194)),((1190,680,1288,766),(255,248,242)),((1284,660,1550,774),(90,75,111)),((1550,681,1607,772),(255,248,242)),((1607,659,1840,778),(252,232,227))]:e.erase(box,col,tol=29,grow=3)
 e.line('友達と廃病院を肝試し','FRIENDS TAKE THE',(990,654,1844,703),color=(245,184,194,255),font='segoepr',size=48)
 e.line('友達と廃病院を肝試し','ABANDONED HOSPITAL DARE',(990,716,1844,775),color=(255,240,236,255),font='segoepr',size=49)
 # Flat dark prank panel. The arrow above y360 remains untouched.
 e.erase((2220,383,2510,759),[(181,143,166),(241,235,235)],tol=30,grow=3)
 e.line('ドッキリ','PRANK',(2230,387,2500,465),color=(181,143,166,255),font='segoepr',size=65,align='center')
 for s,t,b in [('ゴキブリ','ROACH',(2230,488,2500,559)),('降らせた','RAIN',(2230,582,2500,654)),('結果','RESULTS',(2230,678,2500,754))]:e.line(s,t,b,color=(241,235,235,255),font='segoepr',size=60,align='center')
 # The bondage thumbnail is clothed/non-explicit. Polygon clips the diagonal plate.
 e.erase((17,945,440,1260),[(252,254,248),(174,44,73)],tol=35,polygon=[(16,1094),(223,943),(433,943),(17,1247)],grow=3)
 e.line('拘束してみた','TRIED BONDAGE',(42,1175,340,956),color=(252,254,248,255),font='segoepr',size=60,angle=-1)
 e.erase((803,959,906,1391),(174,44,73),tol=35,grow=3)
 e.line('ぬるぬる 触手','SLIMY TENTACLES',(850,975,850,1381),color=(174,44,73,255),font='segoepr',size=62,angle=90)
 # Preserve the original squiggle at bottom, arrow above the insect and leading ※.
 e.erase((1317,944,1580,1062),(136,95,171),tol=35,grow=3)
 e.line('何コレ','WHAT IS THIS?',(1325,950,1580,1038),color=(136,95,171,255),font='segoepr',size=42)
 e.erase((1067,1328,1572,1451),(136,95,171),tol=70,grow=5)
 e.line('実際の映像','REAL FOOTAGE',(1083,1350,1556,1442),color=(136,95,171,255),font='segoepr',size=52)
 e.erase((1938,941,2238,1010),(25,25,23),tol=36,grow=3)
 e.line('JKちなみ','Schoolgirl Chinami',(1940,945,2360,1006),color=(25,25,23,255),font='segoepr',size=38)
 e.erase((1945,1090,2143,1298),(108,99,165),tol=65,grow=5)
 e.line('蟲','BUG',(1952,1110,2135,1280),color=(108,99,165,255),font='segoeprb',size=78)
 e.finish()

def removed():
 e=Edit('data/bgimage/ev_sakuzyo.jpg');favorites(e)
 caption(e,'助けてください！虫に襲われました…','Help! A bug attacked me...',(189,1495,1130,1557),size=40)
 # The dimmed thumbnail is already flattened. Use its own dark lettering shade.
 dark_ink=lambda a:(a[:,:,2]>a[:,:,0]+5)&(a[:,:,2]>a[:,:,1]+9)&(a[:,:,0]<33)
 e.erase((883,312,1440,525),predicate=dark_ink,grow=4)
 e.line('何コレ','WHAT IS THIS?',(895,328,1408,503),color=(25,20,36,255),font='segoepr',size=82)
 e.erase((291,1154,1388,1415),predicate=dark_ink,grow=4)
 e.line('実際の映像','REAL FOOTAGE',(301,1180,1350,1370),color=(25,20,36,255),font='segoepr',size=100)
 # Text-only glyph erase keeps the alert icon and the dimmed artwork.
 e.erase((823,688,1910,988),(255,255,255),tol=65,grow=3)
 for t,b in [('This video was removed',(830,696,1910,780)),('for violating Ytube’s',(830,803,1910,882)),('terms of service.',(830,906,1910,984))]:
  e.line('この動画は、Ytube利用規約違反のため、削除されました。',t,b,color=(255,255,255,255),font='timesbd',size=75)
 e.finish()

def final_video():
 e=Edit('data/fgimage/default/ev_baby8.jpg');favorites(e)
 caption(e,'虫を大量に産んでアヘってしまいました','I gave birth to a swarm of bugs and went cross-eyed.',(45,1495,1900,1560),size=42,color=(255,255,255,255),background=(0,0,0))
 e.finish()

if __name__=='__main__':
 ytube();removed();final_video()
 (ROOT/'web_translations.json').write_text(json.dumps(TRANS,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
 (ROOT/'web_manifest.json').write_text(json.dumps(ASSETS,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
 print('Rendered',len(ASSETS),'images and',len(TRANS),'lettering regions; visual review pending.')
