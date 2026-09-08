"""Rebuild seven reviewed UI/tutorial images from pristine originals, offline.

Uses the copied imgtl toolkit. PNG bytes are intentional even at original .jpg
paths: Chromium sniffs them, retaining every source RGB pixel outside edit zones.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi
import imgtl

ROOT = Path(__file__).resolve().parent
SRC, OUT, QA = ROOT/'source', ROOT/'output', ROOT/'ui_qa'
imgtl.SRC, imgtl.OUT = str(SRC), str(OUT)
INV = {r['id']:r for r in json.loads((ROOT/'inventory.json').read_text(encoding='utf8'))}
WORDS = {r['id']:r for r in json.loads((ROOT/'ui_translations.json').read_text(encoding='utf8'))['records']}
BROWN = (92,72,71,255)
LABEL = (159,90,86,255)
CREAM = (247,242,236,255)

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

class Edit:
    def __init__(self, ident):
        self.ident, self.rec = ident, INV[ident]
        self.rel = self.rec['path']
        assert sha(SRC/self.rel)==self.rec['sha256'], self.rel
        self.src = imgtl.load(self.rel)
        self.im = self.src.copy()
        self.zones = np.zeros((self.im.height,self.im.width),bool)
        self.probes=[]
        self.draws=[]
        self.clean=None

    def zone(self,box):
        x,y,r,b=box; assert 0<=x<r<=self.im.width and 0<=y<b<=self.im.height
        self.zones[y:b,x:r]=True

    def dark(self,box,threshold=160,grow=4):
        a=np.asarray(self.src.crop(box))
        core=(a[:,:,:3].max(2)<threshold)&(a[:,:,3]>24)
        assert core.any(), f'No ink erased: {self.rel} {box}'
        mask=ndi.binary_dilation(core,iterations=grow)
        self.probes.append({'box':box,'core_pixels':int(core.sum()),'erase_pixels':int(mask.sum())})
        self.zone(box)
        return mask

    def donor_erase(self,box,donor,dy=0,threshold=160,grow=4):
        mask=self.dark(box,threshold,grow)
        x,y,r,b=box
        patch=donor.crop((x,y+dy,r,b+dy))
        assert patch.size==(r-x,b-y)
        a=np.array(self.im.crop(box)); d=np.asarray(patch)
        # Donor must be light backdrop, never another line of ink.
        assert d[:,:,:3].max(2)[mask].min()>160, f'Dirty donor: {box}'
        a[mask]=d[mask]; self.im.paste(Image.fromarray(a),(x,y))

    def diffuse_erase(self,box,threshold=160):
        mask=self.dark(box,threshold,grow=4)
        imgtl.inpaint_diffuse(self.im,box,mask,smooth=1.0,iters=350)

    def outlined_label_erase(self,box,donor):
        # The tiny brown labels have broad WHITE halos. Dark-only masking leaves
        # perfect Japanese outlines behind. Seed their saturated red-brown core
        # (the arrow's translucent red and dark rim do not match), then grow by
        # the measured 10px white reach plus 2px antialias allowance.
        a=np.asarray(self.src.crop(box)).astype(int)
        core=(a[:,:,0]-a[:,:,1]>40)&(a[:,:,0]-a[:,:,2]>40)&(a[:,:,0]<210)
        assert core.any()
        mask=ndi.binary_dilation(core,iterations=12)
        self.zone(box)
        self.probes.append({'box':box,'core_pixels':int(core.sum()),'erase_pixels':int(mask.sum()),'method':'red-brown seed + 12px measured halo'})
        patch=np.array(self.im.crop(box));clean=np.asarray(donor.crop(box))
        patch[mask]=clean[mask];self.im.paste(Image.fromarray(patch),box[:2])

    def flat(self,box,colour,keep=None):
        a=np.asarray(self.src.crop(box)); col=np.array(colour)
        consumed=int(np.any(a!=col,axis=2).sum()); assert consumed>0
        self.probes.append({'box':box,'erase_pixels':consumed,'fill':colour})
        self.zone(box)
        imgtl.fill_rect(self.im,(box[0],box[1],box[2]-1,box[3]-1),colour)
        if keep:
            self.im.paste(self.src.crop(keep),keep[:2])

    def text(self,lines,box,hi=70,lo=45,font='ariblk',fill=BROWN,stroke=0,stroke_fill=None):
        if isinstance(lines,str): lines=[lines]
        x,y,r,b=box; self.zone(box)
        d=ImageDraw.Draw(self.im)
        chosen=None
        for size in range(hi,lo-1,-1):
            f=imgtl.font(font,size)
            bbs=[d.textbbox((0,0),s,font=f,anchor='lt',stroke_width=stroke) for s in lines]
            h=max(bb[3]-bb[1] for bb in bbs)
            gap=max(4,int(size*.23))
            if max(bb[2]-bb[0] for bb in bbs)<=r-x and h*len(lines)+gap*(len(lines)-1)<=b-y:
                chosen=(size,f,bbs,h,gap);break
        assert chosen, f'Text cannot fit: {lines} in {box}'
        size,f,bbs,h,gap=chosen
        top=y+(b-y-h*len(lines)-gap*(len(lines)-1))//2
        for s,bb in zip(lines,bbs):
            left=x+(r-x-(bb[2]-bb[0]))//2
            # Toolkit draws at a glyph-top anchor; account for font ink offset.
            imgtl.text(self.im,(left-bb[0],top-bb[1]),s,font,size,fill,stroke,stroke_fill,anchor='lt')
            top+=h+gap
        self.draws.append({'lines':lines,'box':box,'font':font,'point_size':size,'requested_size':hi,'fit':'requested' if size==hi else 'measured shrink','max_width':max(bb[2]-bb[0] for bb in bbs),'row_height':h})

    def finish(self):
        a=np.asarray(self.src); b=np.asarray(self.im)
        changed=np.any(a!=b,axis=2)
        outside=int((changed&~self.zones).sum())
        assert outside==0,f'Changed pixels outside allowlist: {self.rel} {outside}'
        assert changed.any()
        out=OUT/self.rel;out.parent.mkdir(parents=True,exist_ok=True)
        mode=self.rec['mode']; self.im.convert(mode).save(out,format='PNG',optimize=True)
        decoded=Image.open(out).convert('RGBA')
        assert np.array_equal(np.asarray(decoded),b)
        Image.fromarray((self.zones*255).astype('uint8')).save(QA/f'{self.ident}_zones.png')
        Image.fromarray((changed*255).astype('uint8')).save(QA/f'{self.ident}_changed.png')
        # Original-sized full output plus dedicated 2x/3x ink crops for review.
        for i,draw in enumerate(self.draws):
            box=draw['box'];scale=3 if max(box[2]-box[0],box[3]-box[1])<500 else 2
            imgtl.zoom(self.src,box,scale,str(QA/f'{self.ident}_{i:02d}_source.png'))
            imgtl.zoom(self.im,box,scale,str(QA/f'{self.ident}_{i:02d}_output.png'))
        if self.clean is not None:self.clean.convert(mode).save(QA/f'{self.ident}_erased.png',format='PNG')
        output_sha=sha(out)
        review_path=ROOT/'ui_review.json'
        approved=json.loads(review_path.read_text(encoding='utf8')).get('approved_outputs',{}) if review_path.exists() else {}
        reviewed=approved.get(self.rel)==output_sha
        return {'id':self.ident,'path':self.rel,'source_sha256':self.rec['sha256'],'output_sha256':output_sha,'width':self.im.width,'height':self.im.height,'mode':mode,'source_mode':mode,'output_mode':mode,'output_format':'PNG','status':'rendered','reviewed':reviewed,'review_status':'reviewed' if reviewed else 'needs_visual_review','translations':WORDS[self.ident],'changed_pixels':int(changed.sum()),'outside_allowed_pixels':outside,'erase_probes':self.probes,'layout':self.draws}

def hints(ident):
    e=Edit(ident)
    keepbox=(256,100,310,163) if ident==356 else (300,171,352,235)
    p=np.asarray(e.src.crop(keepbox)).astype(int)
    core=np.max(np.abs(p[:,:,:3]-np.array(CREAM[:3])),axis=2)>=2
    labs,n=ndi.label(core,np.ones((3,3)))
    sizes=ndi.sum(core,labs,range(1,n+1));which=int(np.argmax(sizes))+1
    hand=ndi.binary_dilation(labs==which,iterations=1)
    assert hand.sum()>1000
    def restore_hand():
        patch=np.array(e.im.crop(keepbox));patch[hand]=np.asarray(e.src.crop(keepbox))[hand]
        e.im.paste(Image.fromarray(patch),keepbox[:2])
        assert np.array_equal(np.asarray(e.im.crop(keepbox))[hand],np.asarray(e.src.crop(keepbox))[hand])
    if ident==356:
        # Keep the original HINT plaque and clicking-hand symbol exactly.
        e.flat((32,107,394,235),CREAM)
        restore_hand()
        e.clean=e.im.copy()
        e.text('Click the bug',(45,113,253,156),hi=32,lo=30,font='arialbd',fill=(96,77,76,255))
        e.text(['to rub its rear','against her slit.'],(35,161,392,239),hi=32,lo=30,font='arialbd',fill=(96,77,76,255))
    else:
        e.flat((33,102,394,236),CREAM)
        restore_hand()
        e.clean=e.im.copy()
        e.text(['Undress Himarii','without waking her.'],(35,103,391,181),hi=32,lo=30,font='arialbd',fill=(96,77,76,255))
        e.text('Click her clothes',(39,187,296,229),hi=30,lo=28,font='arialbd',fill=(96,77,76,255))
    # Drawing cannot alter the original retained hand or the HINT plaque.
    assert np.array_equal(np.asarray(e.im.crop(keepbox))[hand],np.asarray(e.src.crop(keepbox))[hand])
    assert np.array_equal(np.asarray(e.im.crop((0,0,423,100))),np.asarray(e.src.crop((0,0,423,100))))
    return e.finish()

def icons(ident):
    e=Edit(ident); lab,recs=imgtl.components(e.src)
    ids=[r['id'] for r in recs if r['id']!=1]
    imgtl.comp_sheet(e.src,lab,[1],str(QA/f'{ident}_keep.png'))
    imgtl.comp_sheet(e.src,lab,ids,str(QA/f'{ident}_erase.png'))
    e.im=imgtl.clear_components(e.src,lab,ids,grow=2)
    # Match the source's white RGB beneath alpha zero for image viewers that
    # inspect raw channels. Transparency itself remains zero.
    raw=np.array(e.im);raw[raw[:,:,3]==0,:3]=255;e.im=Image.fromarray(raw)
    erased=np.any(np.asarray(e.src)!=np.asarray(e.im),axis=2)
    e.zones|=erased;e.probes.append({'components':ids,'erase_pixels':int(erased.sum())})
    e.clean=e.im.copy()
    box=(130,185,283,241) if ident==358 else (101,84,202,127)
    e.text(WORDS[ident]['target'],box,hi=35 if ident==358 else 30,lo=25,font='comicbd',fill=LABEL,stroke=2,stroke_fill=(255,255,255,255))
    # Preserve arrow/foot silhouette and all original decoration pixels.
    a=np.array(e.im);src=np.asarray(e.src);keep=lab==1;a[keep]=src[keep];e.im=Image.fromarray(a)
    assert np.array_equal(np.asarray(e.im)[keep],src[keep])
    return e.finish()

def inset(e,old=False):
    dx,dy=(-97,136) if old else (0,0)
    for sourcebox,label in [((1048,711,1134,744),'Insert'),((1048,827,1134,860),'Stop')]:
        x,y,r,b=sourcebox;box=(x+dx,y+dy,r+dx,b+dy)
        a=np.asarray(e.src)
        # Flat plate sampled immediately left of lettering, same row.
        sample=a[box[1]+5:box[3]-5,box[0]-25:box[0]-10]
        colour=tuple(map(int,np.median(sample.reshape(-1,4),axis=0)))
        e.flat(box,colour)
        e.text(label,box,hi=25,lo=23,font='comicbd')
    # Tiny Reload caption is part of the baked screenshot; retain its frame.
    box=(950+dx,245+dy,1014+dx,266+dy)
    e.flat(box,(239,239,239,255))
    e.text('Reload',box,hi=14,lo=12,font='arial',fill=(75,75,75,255))

def tutorial(ident):
    e=Edit(ident);mission=imgtl.load(INV[346]['path']); old=ident==17
    e.diffuse_erase((210,122,660,222))
    # Unchanged wallpaper is confirmed by source pixel comparisons. The mission
    # donor is clean in these regions; +312 follows its exact repeated pattern.
    if old:
        e.donor_erase((175,500,650,691),mission)
        e.donor_erase((175,888,650,1175),mission,dy=-312)
        e.donor_erase((875,1295,2210,1490),mission)
        # Label only; preserve the original broad arrow and its white halo.
        e.outlined_label_erase((2395,1300,2590,1385),mission)
    else:
        e.donor_erase((275,365,738,555),mission)
        e.donor_erase((275,750,738,1040),mission,dy=312)
        e.donor_erase((90,1435,1385,1535),mission)
        e.donor_erase((1480,1435,2780,1535),mission)
        e.outlined_label_erase((175,1364,310,1430),mission)
        e.outlined_label_erase((345,1295,475,1355),mission)
    e.clean=e.im.copy()
    e.text('INSERTION GAME',(140,113,744,223),hi=64,lo=55)
    if old:
        e.text(['Watch',"Himarii's face."],(135,498,651,693),hi=66,lo=55)
        e.text(['Choose','"Insert"','or "Stop"!'],(150,885,640,1178),hi=72,lo=60)
        e.text(['Wrong choices raise danger.','Too much danger means Game Over.'],(867,1292,2220,1490),hi=70,lo=54)
        e.text('DANGER',(2400,1305,2590,1370),hi=39,lo=30,font='comicbd',fill=LABEL,stroke=3,stroke_fill=(255,255,255,255))
    else:
        e.text(['Watch',"Himarii's face."],(222,358,748,558),hi=66,lo=55)
        e.text(['Choose','"Insert"','or "Stop"!'],(260,743,745,1044),hi=72,lo=60)
        e.text('Repeated mistakes = Game Over!',(96,1438,1385,1532),hi=70,lo=52)
        e.text('Reach 80% insertion to clear!',(1480,1438,2780,1532),hi=70,lo=52)
        e.text('DANGER',(175,1364,312,1425),hi=29,lo=24,font='comicbd',fill=LABEL,stroke=3,stroke_fill=(255,255,255,255))
        e.text('WIMP',(327,1292,465,1342),hi=34,lo=25,font='comicbd',fill=LABEL,stroke=3,stroke_fill=(255,255,255,255))
    inset(e,old)
    return e.finish()

def mission():
    e=Edit(346)
    # Probe the 312px wallpaper period on an untouched 200px-wide strip. JPEG
    # block artifacts produce at most 4 levels on 194 of 1,046,400 channels.
    a=np.asarray(e.src)
    delta=np.abs(a[312:,2500:2700].astype(int)-a[:-312,2500:2700].astype(int))
    assert delta.max()<=4 and delta.mean()<.001
    e.diffuse_erase((1208,472,1630,563))
    e.donor_erase((1025,775,1920,875),e.src,dy=312)
    e.donor_erase((680,907,2270,1005),e.src,dy=312)
    e.clean=e.im.copy()
    e.text('MISSION',(1150,467,1710,567),hi=90,lo=80)
    e.text(["Find Himarii's egg-laying video",'adrift in the sea of the internet.'],(655,767,2280,1010),hi=78,lo=65)
    return e.finish()

def main():
    OUT.mkdir(exist_ok=True);QA.mkdir(exist_ok=True)
    results=[hints(356),hints(357),icons(358),icons(359),tutorial(345),tutorial(17),mission()]
    report={'format_version':1,'mode':'manual offline','toolkit':'imgtl.py','source_identity':'current-game original ASAR','assets':results,'total':len(results),'review_status':'reviewed' if all(r['reviewed'] for r in results) else 'needs_visual_review'}
    (ROOT/'ui_manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'rendered':len(results),'changed_pixels':sum(r['changed_pixels'] for r in results),'outside_allowed_pixels':sum(r['outside_allowed_pixels'] for r in results)},indent=2))

if __name__=='__main__':main()
