# -*- coding: utf-8 -*-
"""Typeset the 27 chapter-title cards onto the shared erased parchment plate (1067x600)."""
import os, sys
sys.stdout.reconfigure(encoding='utf-8')
from PIL import Image, ImageDraw, ImageFont

PLATE='C:/Users/sw/Desktop/Games/Belphegor/tooling/title_plate.png'
OUTDIR='C:/Users/sw/Desktop/Games/Belphegor/tooling/translated'
SERIF='C:/Windows/Fonts/georgia.ttf'
INK=(61,46,45)
CX=533

def F(s): return ImageFont.truetype(SERIF,s)

def draw_tracked(d, cx, cy, text, font, fill, track):
    """Centered text with letter spacing."""
    widths=[d.textlength(c,font=font) for c in text]
    total=sum(widths)+track*(len(text)-1)
    x=cx-total/2
    for c,w in zip(text,widths):
        d.text((x,cy),c,font=font,fill=fill,anchor='lm')
        x+=w+track

def fit(d,text,maxw,start,floor=20):
    s=start
    while s>floor and d.textlength(text,font=F(s))>maxw: s-=1
    return F(s)

def typeset(fn, chapter, title):
    im=Image.open(PLATE).convert('RGB'); d=ImageDraw.Draw(im)
    draw_tracked(d, CX, 208, chapter.upper(), F(27), INK, 6)
    sf=fit(d,title,760,start=48,floor=26)
    d.text((CX,307),title,font=sf,fill=INK,anchor='mm')
    os.makedirs(OUTDIR,exist_ok=True)
    im.save(os.path.join(OUTDIR,fn)); print('saved',fn,'|',chapter,'|',title)

TITLES=[
 ('title00.png','Prologue','Oath and Corruption'),
 ('title01.png','Chapter 1','The Rebel Army'),
 ('title02.png','Chapter 2','Enhanced Slaves'),
 ('title03.png','Chapter 3','The Enemy'),
 ('title04.png','Chapter 4','The Turning Point'),
 ('title05a.png','Chapter 5','The Merchant Monks'),
 ('title05b.png','Chapter 5','Village of Betrayal'),
 ('title06a.png','Chapter 6','The Villagers of Musodo'),
 ('title06b.png','Chapter 6','Family'),
 ('title07a.png','Chapter 7','Roles'),
 ('title07b.png','Chapter 7','The Frozen Town'),
 ('title08a.png','Chapter 8','The Sea of Death'),
 ('title08b.png','Chapter 8','Estrangement'),
 ('title09a.png','Chapter 9','The Return'),
 ('title09b.png','Chapter 9','The War Goddess'),
 ('title10a.png','Chapter 10','Trust and Betrayal'),
 ('title10b.png','Chapter 10','Submission'),
 ('title11a.png','Chapter 11','A Ghastly Power'),
 ('title11b.png','Chapter 11','The Rightful Place'),
 ('title12a.png','Chapter 12','The Awaited One Never Came'),
 ('title12b.png','Chapter 12','Strongest Spear, Weakest Shield'),
 ('title13a.png','Chapter 13','Vessel of the God'),
 ('title13b.png','Chapter 13','The Depths'),
 ('title14a.png','Chapter 14','Belphegor'),
 ('title14b.png','Chapter 14','Hope'),
 ('title15a.png','Final Chapter','The Oath'),
 ('title15b.png','Final Chapter','Corruption'),
]

if __name__=='__main__':
    for t in TITLES: typeset(*t)
