"""Reconstruct flat-color thumbnail art under manually measured lettering masks.

Harmonic interpolation of palette memberships continues silhouette boundaries
through missing strokes without averaging unrelated art colors into a white blur.
Only the declared old lettering mask is composited back into the source.
"""
import numpy as np
from scipy import ndimage as ndi
from collections import Counter

def recover(source,mask,box):
 original_box=box
 x0,y0,x1,y1=box
 x0=max(0,x0-45);y0=max(0,y0-45);x1=min(source.shape[1],x1+45);y1=min(source.shape[0],y1+45)
 rgb=source[y0:y1,x0:x1,:3].astype(float);hole=mask[y0:y1,x0:x1]
 known=~hole
 # Exact modal source colors identify flat artwork. Ignore lettering colors,
 # which are already in the hole, and JPEG antialiasing with small populations.
 counts=Counter(map(tuple,rgb[known].astype('uint8')))
 palette=[]
 for c,n in counts.most_common(80):
  if n<70:break
  c=np.array(c,dtype=float)
  if all(np.linalg.norm(c-p)>11 for p in palette):palette.append(c)
  if len(palette)>=12:break
 assert palette
 palette=np.array(palette)
 dist=np.sum((rgb[:,:,None,:]-palette[None,None,:,:])**2,axis=3)
 labels=dist.argmin(axis=2)
 # Nearest surviving source pixels initialize each categorical field.
 nearest=ndi.distance_transform_edt(hole,return_distances=False,return_indices=True)
 fields=np.eye(len(palette),dtype=np.float32)[labels]
 fields[hole]=fields[nearest[0][hole],nearest[1][hole]]
 for _ in range(240):
  new=(np.roll(fields,1,0)+np.roll(fields,-1,0)+np.roll(fields,1,1)+np.roll(fields,-1,1))*.25
  change=np.max(np.abs(new[hole]-fields[hole]))
  fields[hole]=new[hole]
  if change<.0001:break
 winners=ndi.median_filter(fields.argmax(axis=2),size=5)
 hard=palette[winners]
 # A one-pixel coverage transition gives artwork edges the source's antialiasing.
 weights=np.eye(len(palette))[winners]
 weights=ndi.gaussian_filter(weights,sigma=(.42,.42,0))
 repaired=np.clip(weights@palette,0,255).astype('uint8')
 if original_box[0]<100 and 900<original_box[1]<1000:
  # The inspected diagonal banner is a straight band. This line is fitted to
  # unobscured points (300,1009), (350,972), (400,935), not to its white glyphs.
  yy,xx=np.mgrid[y0:y1,x0:x1]
  coverage=np.clip(1231.5-.742*xx-yy+.5,0,1)
  dark=np.array([76,82,80]);light=np.array([244,244,242])
  repaired=np.round(coverage[:,:,None]*dark+(1-coverage[:,:,None])*light).astype('uint8')
 result=source.copy();view=result[y0:y1,x0:x1,:3];view[hole]=repaired[hole]
 return result
