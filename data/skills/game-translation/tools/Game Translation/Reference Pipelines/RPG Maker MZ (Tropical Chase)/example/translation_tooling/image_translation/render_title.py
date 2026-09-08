"""Composite the reviewed generated logo into the pristine title and credits."""
from render import *

j=Job(603)
gen=Image.open(HERE/'title_generated.png').convert('RGBA').resize((526,414),Image.Resampling.LANCZOS)
# The old and new logos occupy this silhouette. Outside it the original title
# pixels are restored exactly; only the logo and its obscured backdrop change.
poly=[(0,0),(142,0),(149,48),(177,58),(281,48),(336,57),(362,46),
      (401,26),(458,28),(488,71),(514,89),(526,98),(526,158),
      (516,192),(519,230),(503,272),(492,335),(520,350),(520,414),
      (367,414),(329,407),(209,390),(151,394),(102,369),(63,357),
      (28,345),(24,302),(36,269),(0,263)]
mask=Image.new('L',j.src.size);ImageDraw.Draw(mask).polygon(poly,fill=255)
ImageDraw.Draw(mask).rectangle((207,334,519,413),fill=255)
# Feather inward, never extend modifications beyond the declared silhouette.
dist=cv2.distanceTransform(np.array(mask),cv2.DIST_L2,5)
alpha=np.minimum(dist/7,1)*255
# At the canvas edge, keep the logo opaque rather than fading to old lettering.
alpha[:60,:142]=np.array(mask)[:60,:142]
mask=Image.fromarray(alpha.astype('uint8'))
canvas=j.src.copy();canvas.paste(gen,(0,0))
j.base.paste(canvas,(0,0),mask)
j.allow=Image.fromarray((np.asarray(mask)>0).astype('uint8')*255)
j.erase_mask=mask
j.regions=[{'source':'とろぴかる・ちぇいす！','target':'Tropical Chase!','box':[0,0,526,374]},
           {'source':'長年追っていた指名手配犯をヌーディストビーチで発見したクール系女刑事',
            'target':'A cool detective finds the fugitive / she has hunted for years... / on a nudist beach!',
            'box':[208,337,519,414]}]
j.save()

# Isolate the same logo for the scrolling credits. Its white perimeter forms
# closed contours; fill their interiors and keep a soft white glow at the edge.
a=np.asarray(gen)
bright=(a[:,:,:3].min(2)>190).astype('uint8')*255
contours,_=cv2.findContours(bright,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
solid=np.zeros(bright.shape,np.uint8)
for contour in contours:
    x,y,w,h=cv2.boundingRect(contour)
    if cv2.contourArea(contour)>45 and y<411:
        cv2.drawContours(solid,[contour],-1,255,-1)
cutmask=Image.fromarray(solid).filter(ImageFilter.GaussianBlur(1.8))
cutmask=Image.fromarray(np.maximum(np.asarray(cutmask),solid))
logo=gen.copy();logo.putalpha(cutmask)
logo.save(HERE/'english_logo.png')
j=Job(112)
j.flat((8,49,389,349),(0,0,0,173))
small=logo.resize((376,296),Image.Resampling.LANCZOS)
j.layers.append((small,(8,48)));j.allowbox((8,48,384,344))
j.regions=[{'source':'とろぴかる・ちぇいす！及び副題','target':'Tropical Chase! (same English logo and subtitle as title screen)','box':[8,48,384,344]}]
j.flat((110,419,284,449),(0,0,0,173))
j.text('順不同・敬称略','In no particular order',(45,420,350,442),17,'bold',align='center')
j.text('敬称略','Honorifics omitted',(45,442,350,464),15,'bold',align='center')
j.save()
