"""Manual, reproducible title lettering; original art is never overwritten."""
from pathlib import Path
import hashlib
import json
import numpy as np
import cv2
from scipy import ndimage as ndi
from PIL import Image, ImageDraw, ImageFont
import imgtl

ROOT = Path(__file__).resolve().parent
REL = 'data/bgimage/ev_title.jpg'
SOURCE = ROOT / 'source' / REL
DONOR = ROOT / 'source/data/bgimage/ev_ne_okita.jpg'
OUTPUT = ROOT / 'output' / REL
QA = ROOT / 'qa_title'
QA.mkdir(exist_ok=True)

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

src = Image.open(SOURCE)
assert src.mode == 'RGB' and src.size == (2880, 1620)
original = np.array(src)
donor = np.array(Image.open(DONOR))
im = src.convert('RGBA')

# The upper-right backdrop is the same bed illustration in another scene.
# This independent strip has never held title ink in either picture.
control = (1440, 0, 2880, 70)
delta = np.abs(original[:70, 1440:].astype(int) - donor[:70, 1440:].astype(int))
assert int(delta.max()) <= 2

# Preserve the author's ornaments at their exact original coordinates.
keep_boxes = [(1503, 83, 1608, 180), (1475, 177, 1538, 232),
              (1545, 198, 1565, 222), (1518, 338, 1593, 409),
              (1502, 329, 1529, 358), (2002, 113, 2145, 229),
              (2680, 145, 2708, 177), (2702, 190, 2804, 286),
              (2708, 291, 2733, 320)]
keep = np.zeros(original.shape[:2], dtype=bool)
central_keep = None
central_halo = None
purple = (original[...,2].astype(int)-original[...,1] > 22) & (original[...,0].astype(int)-original[...,1] > 8)
for x0, y0, x1, y1 in keep_boxes:
    candidate=purple[y0:y1,x0:x1].astype('uint8')
    if x0==2002:
        boundary=Image.new('L',src.size,0)
        ImageDraw.Draw(boundary).polygon([(2009,166),(2018,158),(2020,145),(2031,132),
            (2049,131),(2068,141),(2071,130),(2083,117),(2104,114),(2119,125),
            (2125,143),(2140,148),(2145,160),(2144,180),(2131,192),(2118,194),
            (2113,207),(2098,213),(2081,205),(2070,199),(2063,216),(2050,229),
            (2030,229),(2017,214),(2014,200),(2006,197),(2003,180)],fill=255)
        candidate &= np.asarray(boundary)[y0:y1,x0:x1]>0
    n, labels, stats, centers=cv2.connectedComponentsWithStats(candidate)
    which=1+int(np.argmax(stats[1:,cv2.CC_STAT_AREA]))
    component=np.zeros(keep.shape,dtype='uint8')
    component[y0:y1,x0:x1]=labels==which
    if x0==2002:
        central_keep=cv2.dilate(ndi.binary_fill_holes(component).astype('uint8'),imgtl._disk(1).astype('uint8'))>0
        central_halo=cv2.dilate(central_keep.astype('uint8'),imgtl._disk(13).astype('uint8'))>0
        keep |= central_keep
        continue
    halo=cv2.dilate(component,imgtl._disk(19).astype('uint8'))>0
    # The white halo may touch neighboring lettering. Keep only this star's
    # colored component and its white ring, never an adjacent purple glyph.
    halo &= (~purple | (cv2.dilate(component,imgtl._disk(2).astype('uint8'))>0))
    halo=ndi.binary_fill_holes(halo)
    keep |= halo

erase = np.zeros(original.shape[:2], dtype=bool)
erase[91:480, 1574:2741] = True
erase[480:505,1574:1656]=True
erase[480:505,2649:2741]=True
erase &= ~keep
changed_source_ink = np.max(np.abs(original.astype(int) - donor.astype(int)), axis=2) > 3
assert int((erase & changed_source_ink).sum()) > 100000
base = original.copy()
base[erase] = donor[erase]

# Keep both surviving portions of the subtitle frame's upper rule. The long
# Japanese character had obscured the middle portion; its final tip is cleared
# onto the white plate and the visible rule is continued through that gap.
im = Image.fromarray(base).convert('RGBA')
upper_plate = Image.new('RGBA', im.size, (0,0,0,0))
pd=ImageDraw.Draw(upper_plate)
pd.rounded_rectangle((1656,444,2648,618),radius=62,fill='white')
pd.rounded_rectangle((1677,464,2628,594),radius=30,outline=(140,64,164,255),width=2)
# Only the upper strip was occluded by the Japanese title. The existing lower
# frame, purple plate, and play arrow retain their exact pixels.
im.alpha_composite(upper_plate.crop((1656,444,2649,484)),(1656,444))
erase[444:484,1656:2649]=True
tip_box=(2080,484,2290,510)
tip=np.asarray(im.crop(tip_box))[...,:3].min(axis=2)>220
tip[:,:24]=False
tip[:,170:]=False
tip=cv2.dilate(tip.astype('uint8'),imgtl._disk(4).astype('uint8'))>0
tip[0]=False
imgtl.inpaint_rows(im,tip_box,tip)
erase[484:510,2080:2290] |= tip

# The subtitle has white Gothic lettering on a purple bokeh plate. Erase only
# the measured bright glyph cores and antialiasing; retain plate edges/play icon.
sub_box = (1712, 493, 2519, 567)
sub_mask = imgtl.glyph_mask_pure(im, sub_box, thr=232, halo=3, grow=2)
assert int(sub_mask.sum()) > 15000
imgtl.inpaint_diffuse(im, sub_box, sub_mask, smooth=1.2)
erased = im.copy()
erased.crop((1440, 60, 2840, 640)).save(QA / 'erased.png')

# Custom display-letter recipe uses the shared toolkit's coverage rasterizer.
# All rings are expanded from the same mask before colors are applied.
cov = imgtl.coverage('BUG DREAM', imgtl.FONTS['impact'], base=400, tracking=0.025)
cov = cov.resize((1020, 205), Image.Resampling.LANCZOS)
cov = np.pad(np.asarray(cov), ((42, 42), (42, 42)))
height, width = cov.shape
tile = Image.new('RGBA', (width, height), (0, 0, 0, 0))

def dilation(radius):
    return cv2.dilate(cov, imgtl._disk(radius).astype('uint8')) if radius else cov

def layer(color, mask):
    plane = Image.new('RGBA', tile.size, color)
    plane.putalpha(Image.fromarray(mask))
    tile.alpha_composite(plane)

layer((255, 255, 255, 255), dilation(30))
layer((137, 58, 172, 255), dilation(19))
layer((255, 255, 255, 255), dilation(11))
yy, xx = np.indices(cov.shape)
t = np.clip((yy - 42) / 205, 0, 1)
top, bottom = np.array([225., 166., 249.]), np.array([100., 45., 140.])
colors = top[None, None, :] * (1 - t[..., None]) + bottom[None, None, :] * t[..., None]
# Hard-edged diagonal gloss bands follow the same construction as the source.
phase = yy + xx * 0.23
for lo, hi, alpha in [(134, 171, .23), (259, 271, .17), (328, 368, .15)]:
    zone = (phase >= lo) & (phase < hi)
    colors[zone] = colors[zone] * (1-alpha) + 255*alpha
gradient = Image.fromarray(np.clip(colors, 0, 255).astype('uint8')).convert('RGBA')
gradient.putalpha(Image.fromarray(cov))
tile.alpha_composite(gradient)

# Small white highlight dots stay clipped inside the letter fill.
dots = Image.new('RGBA', tile.size, (0, 0, 0, 0))
dd = ImageDraw.Draw(dots)
for x,y,radius in [(79,75,7),(166,78,3),(361,202,6),(607,78,7),(835,203,5),(1059,194,7)]:
    dd.ellipse((x-radius,y-radius,x+radius,y+radius), fill='white')
dot_alpha = np.minimum(np.asarray(dots.getchannel('A')),cov)
dots.putalpha(Image.fromarray(dot_alpha))
tile.alpha_composite(dots)
# A slight rise gives the display lettering the original playful tilt.
tile = tile.rotate(2.0, Image.Resampling.BICUBIC, expand=True)
title_xy = (1608, 150)
im.alpha_composite(tile, title_xy)

subtitle = "A Sleeping Ytuber's Viral Night"
sub_font = imgtl.font('arialbd', 50)
sub_width = float(sub_font.getlength(subtitle))
assert sub_width <= 805
imgtl.text(im, (2116, 529), subtitle, 'arialbd', 50, (255,255,255,255), anchor='mm')

# Retain every ornament pixel even where the original ornament layers over type.
result = np.array(im.convert('RGB'))
result[central_halo] = 255
result[keep] = original[keep]
out = Image.fromarray(result)
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
out.save(OUTPUT, format='PNG', optimize=True)

allowed = erase.copy()
allowed |= central_halo
x0,y0,x1,y1=sub_box
allowed[y0:y1,x0:x1] |= sub_mask
allowed[493:566,1712:2519] = True
tx,ty=title_xy
ta=np.asarray(tile.getchannel('A'))>0
allowed[ty:ty+tile.height,tx:tx+tile.width] |= ta
allowed[keep]=False
diff=(original!=result).any(axis=2)
assert not (diff & ~allowed).any(), 'Title renderer touched undeclared art'
assert not diff[keep].any(), 'Title renderer altered an ornament'
Image.fromarray((allowed*255).astype('uint8')).save(QA/'edit_mask.png')
Image.fromarray((diff*255).astype('uint8')).save(QA/'actual_diff.png')
out.crop((1440,60,2840,640)).save(QA/'output.png')
out.crop((1540,100,2760,620)).resize((2440,1040),Image.Resampling.LANCZOS).save(QA/'output_2x.png')
out.crop(sub_box).resize((1614,148),Image.Resampling.LANCZOS).save(QA/'subtitle_2x.png')
transcription={'path':REL,'method':'Manual translation and local PIL lettering; no translation API.',
    'blocks':[{'source':'虫ドリーム','target':'BUG DREAM','region':[1574,91,2741,480]},
              {'source':'寝落ちYtuberとバズの夜','target':subtitle,'region':list(sub_box)}]}
(ROOT/'title_translations.json').write_text(json.dumps(transcription,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
report={'path':REL,'source_sha256':sha(SOURCE),'output_sha256':sha(OUTPUT),
    'width':out.width,'height':out.height,'mode':out.mode,'source_format':'JPEG','output_format':'PNG',
    'status':'rendered','reviewed':False,'regions':transcription['blocks'],
    'notes':'Pristine sleeping heroine and colored star artwork preserved. Purple gradient lettering; shared white title/central-star halo and occluded upper subtitle border reconstructed. Lower frame and play icon retained.',
    'qa':{'changed_pixels':int(diff.sum()),'outside_edit_mask_changes':int((diff&~allowed).sum()),
          'ornament_changes':int(diff[keep].sum()),'erased_ink_pixels':int((erase&changed_source_ink).sum()),
          'donor_control_box':list(control),'donor_control_max_channel_difference':int(delta.max()),
          'subtitle_font':'Arial Bold','subtitle_size':50,'subtitle_width':sub_width}}
review_path=ROOT/'title_review.json'
if review_path.exists():
    review=json.loads(review_path.read_text(encoding='utf-8-sig'))
    if review.get('passed') is True and review.get('output_sha256')==report['output_sha256']:
        report['reviewed']=True
        report['qa']['visual_review']=review.get('notes')
(ROOT/'title_manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report['qa'],indent=2))
