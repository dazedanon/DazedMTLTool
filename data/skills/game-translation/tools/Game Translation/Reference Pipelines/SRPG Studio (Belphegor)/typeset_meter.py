# -*- coding: utf-8 -*-
"""Typeset the two breeding/prenatal meters (300x360, transparent). Pink title + 6 stacked stat labels."""
import os, sys
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np
from PIL import Image, ImageDraw, ImageFont

SRC='C:/Users/sw/Desktop/Games/Belphegor/tooling/ImagesToTranslate'
OUT='C:/Users/sw/Desktop/Games/Belphegor/tooling/translated'
FB='C:/Windows/Fonts/arialbd.ttf'
WHITE=(255,255,255,255)
LABELS=['STR','MAG','SKL','SPD','DEF','RES']
XC=[66,89,111,134,162,184]    # true original label centers
# exact original label colors (力魔力技速さ red, 守備 blue, 魔防 purple)
COLORS=[(222,20,20),(222,20,20),(222,28,28),(218,18,18),(70,95,255),(178,48,255)]

def F(s): return ImageFont.truetype(FB,s)

def sample_color(a, x, y0=315, y1=355):
    reg=a[y0:y1, x-10:x+10].reshape(-1,4)
    op=reg[reg[:,3]>120][:,:3].astype(int)
    if not len(op): return (255,80,160)
    # pick the most saturated bright pixels
    sat=op.max(1)-op.min(1)
    bright=op[(sat>40)&(op.max(1)>120)]
    use=bright if len(bright) else op
    return tuple(int(v) for v in np.median(use,0))

def stack(d, cx, y0, text, col, size=13):
    f=F(size); sw=3
    for i,ch in enumerate(text):
        d.text((cx, y0+i*(size+1)), ch, font=f, fill=(255,255,255,255), stroke_width=sw,
               stroke_fill=col+(255,), anchor='ma')   # white fill + colored glow/outline

def typeset(fn, title):
    im=Image.open(os.path.join(SRC,fn)).convert('RGBA'); a=np.array(im)
    cols=COLORS
    # clear title row + bottom-label band (avoid the frame, and the left/right axis numbers)
    a[0:50, 0:156]=0          # title (frame top border starts y51; axis '8'/'60%' at y>=57)
    a[315:356, 52:212]=0      # stat labels only (frame bottom border is y292-314; keep it)
    im=Image.fromarray(a); d=ImageDraw.Draw(im)
    # title (pink) auto-fit
    s=28
    while s>14 and d.textlength(title,font=F(s))>140: s-=1
    d.text((10,26), title, font=F(s), fill=(255,255,255,255), stroke_width=3,
           stroke_fill=(255,40,195,255), anchor='lm')   # white fill + pink glow
    # stat labels (vertical letter stacks) in sampled colors
    for cx,lab,col in zip(XC,LABELS,cols):
        stack(d, cx, 318, lab, col)
    os.makedirs(OUT,exist_ok=True)
    im.save(os.path.join(OUT,fn)); print('saved',fn.encode('ascii','replace').decode(),'colors',cols)

if __name__=='__main__':
    typeset('種付けメーター.png','Breeding')
    typeset('胎教メーター.png','Prenatal')
