# -*- coding: utf-8 -*-
"""Typeset English class skill descriptions onto the erased starfield class screens.
Keeps gold name + katakana. White text + dark outline, centered, auto-wrap long skills."""
import os, sys
sys.stdout.reconfigure(encoding='utf-8')
from PIL import Image, ImageDraw, ImageFont
BG='C:/Users/sw/Desktop/Games/Belphegor/tooling/cclean'
OUT='C:/Users/sw/Desktop/Games/Belphegor/tooling/translated'
FB='C:/Windows/Fonts/arialbd.ttf'
WHITE=(248,248,255); OUTC=(28,14,60); CX=868; MAXW=660

def F(s): return ImageFont.truetype(FB,s)

def draw_skill(d, text, cy):
    """1 line if it fits at size 20, else wrap to 2 lines at size 19."""
    if d.textlength(text, font=F(20)) <= MAXW:
        d.text((CX,cy),text,font=F(20),fill=WHITE,stroke_width=3,stroke_fill=OUTC,anchor='mm')
        return
    # split near the middle space
    words=text.split(' '); best=len(words)//2
    a=' '.join(words[:best]); b=' '.join(words[best:])
    for ln,yy in [(a,cy-15),(b,cy+15)]:
        f=F(19)
        s=19
        while s>14 and d.textlength(ln,font=F(s))>MAXW: s-=1
        d.text((CX,yy),ln,font=F(s),fill=WHITE,stroke_width=3,stroke_fill=OUTC,anchor='mm')

def typeset(bg, out_name, skills):
    im=Image.open(os.path.join(BG,bg)).convert('RGB'); d=ImageDraw.Draw(im)
    centers=[360,420,496] if len(skills)==3 else [380,444]
    for text,cy in zip(skills,centers): draw_skill(d,text,cy)
    os.makedirs(OUT,exist_ok=True)
    im.save(os.path.join(OUT,out_name)); print('saved',out_name.encode('ascii','replace').decode())

J={'archknight':'アーチナイト','archer':'アーチャー','priest':'プリースト','mage':'マージ',
   'archarmor':'アーチアーマー','armorknight':'アーマーナイト','assault':'アサルトナイト',
   'combat':'コンバットナイト','social':'ソシアルナイト'}
BGF={'archknight':'cerase2_archknight_00001_.png'}  # others filled below
for k in J:
    if k not in BGF: BGF[k]=f'cer_{k}_00001_.png'

SKILLS={
 'archknight':['Horse-Breaker  ·  always hits cavalry-type enemies',
               'Mounted Archery  ·  evade counters & re-move,  range −1  (Mov +1)',
               'Terrain: Plains  ·  on plains, Attack +1 and Hit +10'],
 'archer':['Double Strike  ·  Skill% chance to attack twice',
           'Horse-Breaker  ·  always hits cavalry-type enemies',
           'Terrain: Forest  ·  in forest, Attack +1 and Hit +10'],
 'priest':['Fortune  ·  Luck% chance to survive a fatal hit on 1 HP',
           'Blessing  ·  self-buff,  Defense +1'],
 'mage':['Homing Magic  ·  Skill% chance for attacks to always hit',
         'Magic Barrier  ·  M.Def% chance to halve bow & magic attacks'],
 'archarmor':['Pierce  ·  Power% chance for attacks to ignore defense',
              'Heavy Bow  ·  can equip heavy bows',
              'Terrain: Paved  ·  on paved ground, Attack +1 and Hit +10'],
 'armorknight':['Ambush  ·  when attacked, Def×2% chance to strike first',
                'Iron Wall  ·  Def% chance to block all non-magic attacks',
                'Guard  ·  fight in place of an adjacent set ally for 1 turn'],
 'assault':['Charge  ·  when attacking, Def×2% chance to evade the counter',
            'Adaptable  ·  can equip swords, axes, lances & poleaxes'],
 'combat':['Steal  ·  can steal items the enemy is holding',
           'Sabotage  ·  destroy adjacent watchtowers & horse-barricades',
           'Light March  ·  re-move after attacking or stealing  (Evade +10)'],
 'social':['Preempt  ·  when attacked, Speed×2% chance to strike first',
           'Cavalry Charge  ·  vs infantry: evade counter, re-move  (Mov +1)'],
}

if __name__=='__main__':
    only=sys.argv[1:] if len(sys.argv)>1 else list(J)
    for k in only:
        typeset(BGF[k], f'クラス選択画面{J[k]}.png', SKILLS[k])
