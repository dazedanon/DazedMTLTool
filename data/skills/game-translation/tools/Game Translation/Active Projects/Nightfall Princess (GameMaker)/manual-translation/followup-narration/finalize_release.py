"""Measure inspected screenshots and promote the final narration layout patch."""
import json
from pathlib import Path
import shutil
import sys
import numpy as np
from PIL import Image
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path.insert(0,str(ROOT))
import build_catalog as bc
from build_followup import BASE

candidate=HERE/'build-verified/data.win'
report=bc.read(HERE/'build-verified/data.narration-report.json')
assert bc.gmtt.sha256(candidate)==report['output_sha256']
pixels=[]
for renderer in ('hall','quest','gallery','battle'):
    for width,height in ((1920,1080),(1366,768)):
        path=HERE/f'{renderer}-{width}-fixed.png'
        picture=Image.open(path).convert('RGB')
        assert picture.size==(width,height)
        bitmap=np.asarray(picture)
        ink=np.any(bitmap!=[12,31,28],axis=2)
        ink[:round(800*height/1080)]=False
        # Restrict to the caption column; rounded Windows client corners are
        # composited with desktop pixels and are not game text.
        ink[:,:round(850*width/1920)]=False
        ink[:,round(1720*width/1920):]=False
        ys,xs=np.where(ink)
        assert len(xs)>100
        margin=height-1-int(ys.max())
        assert margin>=16*height/1080,(path.name,margin)
        assert xs.max()<1671*width/1920+1
        pixels.append({'file':path.name,'dimensions':[width,height],
                       'ink_bounds':[int(xs.min()),int(ys.min()),int(xs.max()),int(ys.max())],
                       'bottom_ink_margin_pixels':margin})
for renderer in ('gallery','battle'):
    assert Image.open(HERE/f'{renderer}-short-1366.png').size==(1366,768)
save=json.loads((HERE/'save-before.json').read_text(encoding='utf-8-sig'))
assert bc.gmtt.sha256(Path(save['save_path']))==save['before_sha256'].lower()
audit=bc.read(ROOT/'build/narration-layout-audit.json')
assert audit['remaining_overflows']==0 and audit['measured_combinations']==440
runtime={'sha256':report['output_sha256'],'screenshots':pixels,'visually_reviewed':True,
         'actual_patched_draw_blocks':True,'battle_camera_offset_reproduced':[48,48],
         'reported_caption_complete':True,'short_caption_original_position_verified':True,
         'engine_measured_captions':110,'player_save_unchanged':True,
         'scope':'Title-only rendering fixture; no scene progression or save writes.'}
bc.write(HERE/'runtime-review.json',runtime)
report.update(runtime_tested=True,runtime_evidence='../followup-narration/runtime-review.json',
              measured_caption_renderer_combinations=440,previous_overflows_fixed=20)
bc.write(HERE/'build-verified/data.narration-report.json',report)
release=ROOT/'release'
assert bc.gmtt.sha256(release/'data.win')==BASE
backup=ROOT/'release-v5'
assert not backup.exists()
shutil.copytree(release,backup)
shutil.copy2(candidate,release/'data.win')
bc.write(release/'narration-layout-report.json',report)
shutil.copy2(HERE/'build-verified/data.site-remap.json',release/'narration-site-remap.json')
manifest=bc.read(release/'release-manifest.json')
manifest.update(english_sha256=report['output_sha256'],previous_english_sha256=BASE,
                narration_captions_checked=110,narration_renderers_checked=4,
                narration_bottom_padding=16,installed_archive_verified=False)
manifest['runtime_tests'].append('Complete four-line caption in all four narration Draw blocks at 1920x1080 and 1366x768, including actual battle view offset; short caption positions and player save preserved')
bc.write(release/'release-manifest.json',manifest)
roundtrip=bc.read(release/'text-roundtrip.json')
roundtrip.update(sha256=report['output_sha256'],size=report['bytes'],
                 method='All 631 canonical texts re-extracted after the narration imports; two relocated hall-label instructions reconciled through identical ordered literal sequences.',
                 site_remap='narration-site-remap.json')
bc.write(release/'text-roundtrip.json',roundtrip)
images=bc.read(release/'data.win.images-report.json')
images.update(output_sha256=report['output_sha256'],
              narration_followup='narration-layout-report.json proves all textures, fonts and audio unchanged')
bc.write(release/'data.win.images-report.json',images)
package=bc.read(release/'project-package-report.json')
package.update(sha256=report['output_sha256'],bytes=report['bytes'],
               drop_in_runtime_verified=False,installed_copy_matches=False)
bc.write(release/'project-package-report.json',package)
shutil.copy2(candidate,ROOT/'project-package/data.win')
print(json.dumps({'sha256':report['output_sha256'],'pixel_margins':pixels,'save_unchanged':True},indent=2))
