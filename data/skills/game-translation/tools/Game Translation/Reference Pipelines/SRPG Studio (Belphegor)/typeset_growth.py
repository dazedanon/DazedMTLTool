# -*- coding: utf-8 -*-
"""Typeset the 6 growth-rate banners onto the shared erased sword plate (680x100)."""
import os, sys
sys.stdout.reconfigure(encoding='utf-8')
from PIL import Image, ImageDraw, ImageFont

PLATE='C:/Users/sw/Desktop/Games/Belphegor/tooling/growth_plate.png'
OUTDIR='C:/Users/sw/Desktop/Games/Belphegor/tooling/translated'
FONT='C:/Windows/Fonts/ariblk.ttf'
WHITE=(248,248,255,255); PINK=(255,135,178,255); OUT=(28,12,44,255)
SHEAR=0.16

def F(s): return ImageFont.truetype(FONT,s)
def render(text,size,fill):
    f=F(size); sw=max(3,size//7)
    t=Image.new('RGBA',(1,1)); td=ImageDraw.Draw(t)
    bb=td.textbbox((0,0),text,font=f,stroke_width=sw); w,h=bb[2]-bb[0]+8,bb[3]-bb[1]+8
    img=Image.new('RGBA',(w+int(h*SHEAR)+4,h),(0,0,0,0)); d=ImageDraw.Draw(img)
    d.text((4-bb[0],4-bb[1]),text,font=f,fill=fill,stroke_width=sw,stroke_fill=OUT)
    return img.transform((img.width,img.height),Image.AFFINE,(1,SHEAR,-SHEAR*h/2,0,1,0),resample=Image.BICUBIC)

STATS=[('成長率選択力.png','Power'),('成長率選択守備力.png','Defense'),
       ('成長率選択技.png','Skill'),('成長率選択速さ.png','Speed'),
       ('成長率選択魔力.png','Magic'),('成長率選択魔防力.png','Magic Def.')]

def typeset(fn,stat):
    base=Image.open(PLATE).convert('RGBA'); W,H=base.size
    label='Growth Rate Boost'
    size=40
    while size>16:
        a=render(label,size,WHITE); b=render(stat,size,PINK)
        if a.width+24+b.width<=W-70: break
        size-=1
    a=render(label,size,WHITE); b=render(stat,size,PINK)
    gap=24; tot=a.width+gap+b.width
    x=(W-tot)//2; cy=48
    base.alpha_composite(a,(x,cy-a.height//2))
    base.alpha_composite(b,(x+a.width+gap,cy-b.height//2))
    os.makedirs(OUTDIR,exist_ok=True)
    base.save(os.path.join(OUTDIR,fn)); print('saved',stat)

if __name__=='__main__':
    for fn,st in STATS: typeset(fn,st)
