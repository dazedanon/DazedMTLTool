# -*- coding: utf-8 -*-
import os, sys, textwrap
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np
from PIL import Image, ImageDraw, ImageFont
SRC='C:/Users/sw/Desktop/Games/Belphegor/tooling/ImagesToTranslate'
OUT='C:/Users/sw/Desktop/Games/Belphegor/tooling/translated'
AB='C:/Windows/Fonts/arialbd.ttf'; AR='C:/Windows/Fonts/arial.ttf'

def med_dark(a,x0,y0,x1,y1):
    reg=a[y0:y1,x0:x1].reshape(-1,3).astype(int)
    d=reg[reg.sum(1)<reg.sum(1).mean()]
    return tuple(int(v) for v in np.median(d,0))

def tooltip():
    fn='連携説明.png'; im=Image.open(os.path.join(SRC,fn)).convert('RGB'); a=np.array(im)
    panel=med_dark(a,560,305,805,398)        # dark info-panel bg (name/class/lv/hp)
    strip=med_dark(a,478,404,660,436)         # darker bottom strip (weapon)
    d=ImageDraw.Draw(im)
    # (erase_box, text, anchor_x, anchor_y, max_size, fill_color, maxw)
    items=[((553,305,672,332),'Fee',          560,318,24,panel,150),
           ((553,334,675,356),'Arch Knight',  560,344,22,panel,128),
           ((474,403,580,437),'Kingdom Bow',   480,420,22,strip,150)]
    for (x0,y0,x1,y1),txt,tx,ty,mx,col,maxw in items:
        d.rectangle([x0,y0,x1,y1],fill=col)
        s=mx
        while s>12 and d.textlength(txt,font=ImageFont.truetype(AB,s))>maxw: s-=1
        d.text((tx,ty),txt,font=ImageFont.truetype(AB,s),fill=(245,245,245),anchor='lm')
    im.save(os.path.join(OUT,fn)); print('saved tooltip')

def footnote():
    fn='称号壁紙.png'; im=Image.open(os.path.join(SRC,fn)).convert('RGB'); a=np.array(im)
    W,H=im.size
    # patch parchment: copy a clean band from higher up over the footnote area
    box=(690,590,1245,695)
    patch=im.crop((690,300,1245,405))   # blank parchment same width
    im.paste(patch,(690,590))
    d=ImageDraw.Draw(im)
    ink=(70,55,52)
    txt=('* On the Title Screen and Base, titles earned across all save '
         'data are shown; on the Battle Map, titles earned in the current '
         'playthrough are shown.')
    f=ImageFont.truetype(AR,17)
    lines=textwrap.wrap(txt,52)
    y=600
    for ln in lines:
        d.text((715,y),ln,font=f,fill=ink); y+=24
    im.save(os.path.join(OUT,fn)); print('saved footnote')

if __name__=='__main__':
    tooltip(); footnote()
