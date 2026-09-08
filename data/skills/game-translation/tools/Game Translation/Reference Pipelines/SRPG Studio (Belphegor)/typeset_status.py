# -*- coding: utf-8 -*-
"""Typeset (erase JP + draw EN) for the shared monster-status template (600x200)."""
import os
import numpy as np
from PIL import Image, ImageDraw, ImageFont

SRCDIR = 'C:/Users/sw/Desktop/Games/Belphegor/tooling/ImagesToTranslate'
OUTDIR = 'C:/Users/sw/Desktop/Games/Belphegor/tooling/translated'
FB = 'C:/Windows/Fonts/arialbd.ttf'

TEAL=(20,34,34); WHITE=(245,245,245); GREEN=(83,233,48)
GLBL=(96,210,80); ORANGE=(236,152,44); REDFILL=(67,27,27); GBOXFILL=(67,77,27)

# shared geometry
GREEN_BOX=(297,26,371,52)   # inset to preserve the double bevel border
RED_BOX=(384,25,580,110)
ROWS=[37,66,95]
LBLL_X,COLL_X,VALL_X=390,434,456
LBLR_X,COLR_X,VALR_X=490,534,556
LBL_L=['STR','SKL','DEF']; LBL_R=['MAG','SPD','RES']

def F(sz): return ImageFont.truetype(FB,sz)
def fit(d,text,maxw,start=19,floor=12):
    s=start
    while s>floor and d.textlength(text,font=F(s))>maxw: s-=1
    return F(s)

def typeset(m):
    im=Image.open(os.path.join(SRCDIR,m['file'])).convert('RGB')
    two = len(m['atk'])==2
    # green Move box: erase ONLY the white glyphs (keeps the beveled tan/black border intact)
    arr=np.array(im)
    gx0,gy0,gx1,gy1=299,25,371,54
    sub=arr[gy0:gy1,gx0:gx1]
    sub[sub[:,:,1].astype(int)>86]=GBOXFILL   # olive g=77; white text g~245
    arr[gy0:gy1,gx0:gx1]=sub
    im=Image.fromarray(arr)
    d=ImageDraw.Draw(im)
    # ERASE: race row, middle atk block, skills block; then refill the (dark-bordered) red box
    d.rectangle([115,24,284,60],fill=TEAL)   # stop before green box left border (x287-292)
    d.rectangle([115,58,374,122] if two else [115,60,362,100],fill=TEAL)
    d.rectangle([28,124,586,192],fill=TEAL)   # stop before the right ornate frame (x591-599)
    d.rectangle(list(RED_BOX),fill=REDFILL)

    # race (auto-fit so it never hits the green box at x290)
    rf=fit(d,f"Race:  {m['race']}",163,start=26,floor=15)
    d.text((118,44),f"Race:  {m['race']}",font=rf,fill=WHITE,anchor='lm')
    # move box
    gcx=(GREEN_BOX[0]+GREEN_BOX[2])//2; gcy=(GREEN_BOX[1]+GREEN_BOX[3])//2
    d.text((gcx,gcy),f"Move {m['move']}",font=F(16),fill=WHITE,anchor='mm')
    # attack lines (1 or 2)
    al=m['atk']
    ys,patx,valx = ([78,106],210,343) if two else ([80],248,354)
    for (typ,pat,val),y in zip(al,ys):
        d.text((118,y),typ,font=fit(d,typ,patx-118-6,start=17),fill=WHITE,anchor='lm')
        d.text((patx,y),pat,font=fit(d,pat,valx-patx-18,start=17),fill=WHITE,anchor='lm')
        d.text((valx,y),str(val),font=F(17),fill=WHITE,anchor='mm')
    # stat grid
    for i,y in enumerate(ROWS):
        d.text((LBLL_X,y),LBL_L[i],font=F(19),fill=WHITE,anchor='lm')
        d.text((COLL_X,y),':',font=F(19),fill=WHITE,anchor='lm')
        if m['L'][i]: d.text((VALL_X,y),m['L'][i],font=F(19),fill=GREEN,anchor='lm')
        d.text((LBLR_X,y),LBL_R[i],font=F(19),fill=WHITE,anchor='lm')
        d.text((COLR_X,y),':',font=F(19),fill=WHITE,anchor='lm')
        if m['R'][i]: d.text((VALR_X,y),m['R'][i],font=F(19),fill=GREEN,anchor='lm')
    # skills
    d.text((40,138),'Skills',font=F(17),fill=GLBL,anchor='lm')
    for (nm,desc),y in zip(m['skills'],[139,171]):
        d.text((118,y),nm,font=F(16),fill=ORANGE,anchor='lm')
        df=fit(d,':  '+desc,322,start=17,floor=12)
        d.text((258,y),':  '+desc,font=df,fill=WHITE,anchor='lm')

    os.makedirs(OUTDIR,exist_ok=True)
    out=os.path.join(OUTDIR,m['file'])
    im.save(out); print('saved', m['race'])

MONSTERS=[
 {'file':'ステータス_ゴブリン.png','race':'Goblin','move':'5',
  'atk':[('Physical Atk','Volley Atk','1')],'L':['+4','+2','+2'],'R':['','+2',''],
  'skills':[('Group Attack','Always attacks 3 times'),
            ('Accuracy Down','Hit rate -30 instead of triple attack')]},
 {'file':'ステータス_スライム.png','race':'Slime','move':'4',
  'atk':[('Physical Atk','Melt Atk','1')],'L':['+3','','+8'],'R':['','',''],
  'skills':[('Soft Body','Halves all incoming physical damage'),
            ('Magic Frailty','Magic defense -10 (will not go below 0)')]},
 {'file':'ステータス_ケイローン.png','race':'Chiron','move':'6',
  'atk':[('Physical Atk','Physical Bow','2-3'),('Magic Atk','Magic Bow','2-3')],
  'L':['+2','+2',''],'R':['+2','+3',''],
  'skills':[('Magic Archer','Hit rate becomes 100%, can move after attacking'),
            ('Physical Frailty','Physical defense -5 (will not go below 0)')]},
 {'file':'ステータス_バジリスク.png','race':'Basilisk','move':'6',
  'atk':[('Physical Atk','Petrify Atk','1-2')],'L':['+2','+3','+2'],'R':['','+1','+1'],
  'skills':[('Petrify Attack','Performs an attack with a petrify effect'),
            ('Mass Petrify','Allies within 2 tiles: hit & evade -10%')]},
 {'file':'ステータス_ベヒモス.png','race':'Behemoth','move':'7',
  'atk':[('Physical Atk','Beast Charge','1')],'L':['+5','','+1'],'R':['','+2',''],
  'skills':[('Beast Charge','Pierces defense, but -30% evade from huge size'),
            ('Abyss Miasma','Allies within 2 tiles: defense -3')]},
 {'file':'ステータス_魔界樹.png','race':'Abyss Tree','move':'4',
  'atk':[('Magic Atk','Miasma Seed','2-3')],'L':['','',''],'R':['+4','+1','+4'],
  'skills':[('Absorb Attack','Absorbs HP from the damaged enemy'),
            ('Life Drain','Allied units within 2 tiles: attack -2')]},
]

if __name__=='__main__':
    for m in MONSTERS: typeset(m)
