"""Offline manual English redraw of controls and bundled theme image samples.

Read-only pristine sources; local Pillow/imgtl only, no OCR or translation API.
Every edit has a bounded zone; RGBA pixels outside those zones remain exact.
Indexed inputs retain their original palette and all unedited indices.
"""
from pathlib import Path
from collections import Counter
import hashlib, json, textwrap
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
import imgtl

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT/'source'; OUTPUT=ROOT/'output'; QA=ROOT/'qa'/'controls'
INVENTORY={r['id']:r for r in json.loads((ROOT/'inventory.json').read_text(encoding='utf-8'))}
ORIGINAL_SHA='0427999aee3dd5e6e6cc995eca1f6cf7a1a94bdc43222a247bc103a99a12b524'

SPECS={
402: ('subtitle','CG鑑賞モード','CG Gallery'),
403: ('subtitle','コンフィグ','Settings'),
404: ('subtitle','回想モード','Scene Replay'),
410: ('stock_button','CGモード','CG Gallery'),
411: ('stock_button','コンフィグ','Config'),
412: ('stock_button','つづきから','Continue'),
413: ('stock_button','回想モード','Scene Replay'),
414: ('stock_button','はじめから','New Game'),
415: ('paper_button','はやい','Fast'),
416: ('paper_button','ふつう','Normal'),
417: ('paper_button','挿れる','Insert'),
418: ('paper_button','つづきから','Continue'),
419: ('paper_button','はじめから','New Game'),
420: ('paper_button','止まる','Stop'),
421: ('paper_button','ゆっくり','Slow'),
422: ('plugin_splash','個別画像表示・消去 プラグイン','Show / Hide Individual Images\nPlugin'),
471: ('theme_preview','',''),
}

def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def bounds_mask(size, boxes):
 a=np.zeros((size[1],size[0]),dtype=bool)
 for x0,y0,x1,y1 in boxes:a[y0:y1,x0:x1]=True
 return a

def draw_fit(im, box, value, face='arialbd', size=24, color=(92,73,73,255), align='center'):
 """Use toolkit metrics, draw supersampled, then clip to the reviewed zone."""
 x0,y0,x1,y1=box; w=x1-x0; h=y1-y0
 lines=value.split('\n')
 while size>5:
  widths=[imgtl.text_width(s,face,size) for s in lines]
  if max(widths)<=w-2 and len(lines)*(size+1)<=h+4:break
  size-=1
 scale=4
 layer=Image.new('RGBA',(w*scale,h*scale),(0,0,0,0))
 line_h=size+2; total=line_h*len(lines)
 for n,s in enumerate(lines):
  px=w/2 if align=='center' else 1
  py=(h-total)/2+n*line_h+line_h/2
  imgtl.text(layer,(round(px*scale),round(py*scale)),s,face,size*scale,color,
             anchor='mm' if align=='center' else 'lm')
 tile=layer.resize((w,h),Image.Resampling.LANCZOS)
 im.alpha_composite(tile,(x0,y0))
 return {'font':face,'font_size':size,'line_widths':widths,'box':list(box)}

def erase_glyphs(im,box,polarity='dark',delta=20):
 mask=imgtl.glyph_mask(im,box,delta=delta,dark_delta=8,halo=2,grow=1,polarity=polarity)
 assert int(mask.sum())>0,f'Nothing was erased in {box}'
 before=np.array(im)
 imgtl.inpaint_diffuse(im,box,mask,smooth=.7,iters=200)
 changed=np.any(before!=np.array(im),axis=2)
 assert changed.any(),f'Erase returned its input in {box}'
 return int(mask.sum())

def run():
 QA.mkdir(parents=True,exist_ok=True)
 review_path=ROOT/'controls_review.json'
 reviews=json.loads(review_path.read_text(encoding='utf-8')).get('assets',{}) if review_path.exists() else {}
 assets=[]; translations=[]
 for k,(kind,source_text,target_text) in SPECS.items():
  row=INVENTORY[k]; path=SOURCE/row['path']; original=Image.open(path)
  source_palette=original.getpalette('RGB') if original.mode=='P' else None
  assert digest(path)==row['sha256']; assert getattr(original,'n_frames',1)==1
  im=original.convert('RGBA'); source_pixels=np.array(im); boxes=[]; blocks=[]

  def block(source,target,box,method,**kwargs):
   box=tuple(box); boxes.append(box)
   before=np.array(im)
   if method=='clear':
    erased=int((before[box[1]:box[3],box[0]:box[2],3]>0).sum())
    assert erased>0
    imgtl.clear_rect(im,(box[0],box[1],box[2]-1,box[3]-1))
   elif method=='flat':
    color=kwargs.pop('background')
    erased=int(np.any(before[box[1]:box[3],box[0]:box[2]]!=color,axis=2).sum())
    assert erased>0
    imgtl.fill_rect(im,(box[0],box[1],box[2]-1,box[3]-1),color)
   else:
    erased=erase_glyphs(im,box,polarity=kwargs.pop('polarity','dark'),delta=kwargs.pop('delta',20))
   record={'source':source,'target':target,'box':list(box),'erase_method':method,'erased_pixels':erased}
   record.update(draw_fit(im,box,target,**kwargs));blocks.append(record)

  if kind=='paper_button':
   # Measured source dark-ink bands are y18--39; plate/border starts below y49.
   color=im.getpixel((15,29)); assert color==(214,194,183,255)
   block(source_text,target_text,(8,12,134,46),'flat',background=color,face='comicbd',size=24)
  elif kind=='stock_button':
   # White text on a vertically shaded brown plate. Interpolate glyph holes only.
   block(source_text,target_text,(24,9,228,42),'inpaint',polarity='bright',delta=48,face='arialbd',size=22,color=(255,255,255,255))
  elif kind=='subtitle':
   # Alpha probe separates existing English logo (y15--88) from JP subtitle (y93--108).
   block(source_text,target_text,(14,91,im.width-3,112),'clear',face='arialbd',size=14,color=(255,255,255,255),align='left')
  elif kind=='plugin_splash':
   # Two text bands y409--484 and y490--566. Illustration ends at y340.
   bg=im.getpixel((110,440)); assert bg==(233,230,240,255)
   box=(122,397,831,579); boxes.append(box)
   erased=int(np.any(source_pixels[397:579,122:831]!=bg,axis=2).sum()); assert erased>0
   imgtl.fill_rect(im,(122,397,830,578),bg)
   a=draw_fit(im,(124,405,830,486),'Show / Hide Individual Images',size=52,color=(40,53,101,255))
   b=draw_fit(im,(124,485,830,574),'Plugin',size=75,color=(40,53,101,255))
   blocks.append({'source':source_text,'target':target_text,'box':list(box),'erased_pixels':erased,'erase_method':'flat','lines':[a,b]})
  elif kind=='theme_preview':
   block('ガイド','Guide',(791,259,841,279),'flat',background=im.getpixel((789,269)),face='arialbd',size=11,color=(150,170,105,255))
   block('一括テーマ変換です。','This changes the entire theme.',(744,292,916,316),'inpaint',delta=18,face='arial',size=10,color=(125,117,108,255),align='left')
   sample_source='どこで生れたかとんと見当がつかぬ。何でも薄暗いじめじめした所でニャーニャー泣いていた事だけは記憶している。'
   sample_target='I have no idea where I was born.\nAll I remember is mewing in some dark, damp place.'
   block(sample_source,sample_target,(181,646,553,676),'inpaint',delta=13,face='arial',size=9,color=(127,115,105,255),align='left')
   block('ガイド：一括テーマ変換です。','Guide: This changes the entire theme.',(859,489,1082,504),'inpaint',delta=12,face='arial',size=7,color=(110,108,76,255),align='left')
   for box in [(859,554,1084,570),(859,620,1084,636)]:
    block('まだ、保存されているデータがありません。','There is no saved data yet.',box,'inpaint',delta=12,face='arial',size=7,color=(140,125,116,255),align='left')
   # The tiny saved preview is the same translated demonstration screen.
   box=(763,476,837,516); boxes.append(box)
   im.paste(im.crop((652,21,1260,347)).resize((74,40),Image.Resampling.LANCZOS),(763,476))
   blocks.append({'source':'縮小された同じ画面','target':'Translated demonstration screen thumbnail','box':list(box),'erase_method':'paste translated matching screen'})

  zone=bounds_mask(im.size,boxes)
  if original.mode=='P':
   # Preserve the original palette, transparency index and all unrelated pixels.
   palette_image=Image.new('P',(1,1)); palette_image.putpalette(source_palette)
   quantized=im.convert('RGB').quantize(palette=palette_image,dither=Image.Dither.NONE)
   result=original.copy(); result.putpalette(source_palette)
   result.paste(quantized,(0,0),Image.fromarray(zone.astype('uint8')*255))
  else:result=im.convert(original.mode)
  dst=OUTPUT/row['path'];dst.parent.mkdir(parents=True,exist_ok=True)
  result.save(dst,format=original.format,**({'optimize':False} if original.format=='GIF' else {}))
  reread=Image.open(dst); actual=np.array(reread.convert('RGBA'))
  assert reread.size==original.size and reread.mode==original.mode
  changed=np.any(actual!=source_pixels,axis=2)
  assert int((changed&~zone).sum())==0, f'Out-of-zone pixels changed for {k}'
  assert changed.any(), f'No changes for {k}'
  maskpath=QA/f'{k}_zones.png';Image.fromarray(zone.astype('uint8')*255).save(maskpath)
  for n,box in enumerate(boxes):
   imgtl.zoom(reread.convert('RGBA'),box,3,str(QA/f'{k}_{n}_after.png'))
   imgtl.zoom(original.convert('RGBA'),box,3,str(QA/f'{k}_{n}_before.png'))
  imgtl.zoom(reread.convert('RGBA'),(0,0,im.width,im.height),2,str(QA/f'{k}_full.png'))
  output_sha=digest(dst)
  reviewed=reviews.get(str(k),{}).get('output_sha256')==output_sha and reviews.get(str(k),{}).get('source_sha256')==row['sha256']
  asset={'id':k,'path':row['path'],'source_sha256':row['sha256'],'output_sha256':output_sha,
         'width':im.width,'height':im.height,'mode':original.mode,'source_mode':original.mode,'output_mode':reread.mode,
         'source_format':original.format,'output_format':reread.format,'status':'rendered','reviewed':reviewed,
         'qa':{'outside_zone_changed_pixels':0,'changed_pixels':int(changed.sum()),'zone_mask':str(maskpath.relative_to(ROOT)).replace('\\','/')},'blocks':blocks}
  assets.append(asset); translations.append({'id':k,'path':row['path'],'status':'translated','blocks':blocks})
  print(k,row['path'],original.mode,'changed',int(changed.sum()))
 manifest={'format_version':1,'original_archive_sha256':ORIGINAL_SHA,'assets':assets}
 (ROOT/'controls_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 (ROOT/'controls_translations.json').write_text(json.dumps(translations,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':run()
