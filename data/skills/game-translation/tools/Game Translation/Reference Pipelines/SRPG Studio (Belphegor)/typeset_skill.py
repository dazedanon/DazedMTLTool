# -*- coding: utf-8 -*-
"""Typeset skill-description overlays (610x80, transparent bg). Yellow fill + navy outline + red +."""
import os, sys
sys.stdout.reconfigure(encoding='utf-8')
from PIL import Image, ImageDraw, ImageFont

SRCDIR='C:/Users/sw/Desktop/Games/Belphegor/tooling/ImagesToTranslate'
OUTDIR='C:/Users/sw/Desktop/Games/Belphegor/tooling/translated'
FONT='C:/Windows/Fonts/ariblk.ttf'   # Arial Black (heavy)

YELLOW=(252,255,140,255); NAVY=(20,6,48,255); RED=(220,30,30,255)
SHEAR=0.18  # synthetic italic

def F(s): return ImageFont.truetype(FONT,s)

def render_line(text, size):
    """Render one line (yellow fill, navy stroke, leading + in red) to its own RGBA, then shear."""
    f=F(size); sw=max(2,size//8)
    tmp=Image.new('RGBA',(1,1)); td=ImageDraw.Draw(tmp)
    bb=td.textbbox((0,0),text,font=f,stroke_width=sw)
    w,h=bb[2]-bb[0]+8, bb[3]-bb[1]+8
    img=Image.new('RGBA',(w+int(h*SHEAR)+4,h),(0,0,0,0)); d=ImageDraw.Draw(img)
    ox,oy=4-bb[0],4-bb[1]
    d.text((ox,oy),text,font=f,fill=YELLOW,stroke_width=sw,stroke_fill=NAVY)
    # red plus on top (first char)
    if text.startswith('+'):
        d.text((ox,oy),'+',font=f,fill=RED,stroke_width=sw,stroke_fill=NAVY)
    img=img.transform((img.width,img.height),Image.AFFINE,(1,SHEAR,-SHEAR*h/2,0,1,0),resample=Image.BICUBIC)
    return img

def typeset(s):
    W,H=Image.open(os.path.join(SRCDIR,s['file'])).size
    canvas=Image.new('RGBA',(W,H),(0,0,0,0))
    lines=s['lines']; maxw=W-30
    # choose size so widest line fits maxw and total height fits
    size=44
    while size>14:
        imgs=[render_line(t,size) for t in lines]
        if max(i.width for i in imgs)<=maxw and sum(i.height for i in imgs)-len(lines)*size//5<=H-6:
            break
        size-=1
    imgs=[render_line(t,size) for t in lines]
    gap=-size//6
    th=sum(i.height for i in imgs)+gap*(len(imgs)-1)
    y=(H-th)//2
    for i,img in enumerate(imgs):
        if len(imgs)==1: x=14
        else: x=14 if i==0 else min(maxw-img.width+14, 14+int(W*0.16))
        canvas.alpha_composite(img,(x,y)); y+=img.height+gap
    os.makedirs(OUTDIR,exist_ok=True)
    canvas.save(os.path.join(OUTDIR,s['file'])); print('saved',s['name'])

SKILLS=[
 {'file':'スキル選択(体術2).png','name':'MartialArts','lines':['+Martial Arts II - Skill x2% chance to','evade melee weapon attacks']},
 {'file':'スキル選択(切り払い2).png','name':'ArrowDeflect','lines':['+Arrow Deflect II - Skill x2% chance','to nullify bow-type attacks']},
 {'file':'スキル選択(後の先2).png','name':'Counter','lines':['+Counter II - Skill x2% chance to land','a critical hit when counterattacking']},
 {'file':'スキル選択(狂戦士2).png','name':'Berserker','lines':['+Berserker II - Power% chance to attack 3x in a row']},
 {'file':'スキル選択(肉の壁2).png','name':'FleshArmor','lines':['+Flesh Armor II - Parameter Boost   HP +8']},
 {'file':'スキル選択(追撃2).png','name':'FlashStrike','lines':['+Flash Strike II - Speed x2% chance to attack again']},
 {'file':'スキル選択(通し2).png','name':'Pierce','lines':['+Pierce II - Skill x2% chance for an','attack to deal effective damage']},
 {'file':'スキル選択(重撃2).png','name':'HeavyStrike','lines':['+Heavy Strike II - Power x2% chance for','an attack to ignore defense']},
 {'file':'スキル選択(野駆け).png','name':'FieldRun','lines':['+Field Run - Parameter Boost   Movement +1']},
]
if __name__=='__main__':
    only=sys.argv[1] if len(sys.argv)>1 else None
    for s in SKILLS:
        if only and only not in s['file']: continue
        typeset(s)
