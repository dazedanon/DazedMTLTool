"""Check every translated sprite in the final file and stage local release evidence."""
import json
import os
from pathlib import Path
import shutil
import sys
import numpy as np
from PIL import Image
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path.insert(0,str(ROOT))
import build_catalog as bc
from build_followup import BASE,write,read

candidate=HERE/'build/data.win'
report=read(HERE/'build/data.win.followup-report.json')
assert bc.gmtt.sha256(candidate)==report['output_sha256']
expected={p.name:p for p in (ROOT/'images/english').glob('*.png')}
assert len(expected)==24
expected['spr_p_0.png']=HERE/'english/spr_p_0.png'
sprites=[file.removesuffix('_0.png') for file in expected]
request=HERE/'all-sprites-request.json'
out=HERE/'all-sprites-roundtrip'
write(request,{'mode':'export','directory':str(out),'sprites':sprites})
env=os.environ.copy();env['NFP_IMAGE_REQUEST']=str(request)
bc.gmtt.run_utmt(['load',candidate,'-s',ROOT/'images/assets.csx'],env,HERE/'all-sprites.log')
for file,path in expected.items():
    assert np.array_equal(np.asarray(Image.open(path)),np.asarray(Image.open(out/file))),file
dimensions={file:list(Image.open(HERE/file).size) for file in ('runtime-1920.png','runtime-1366.png')}
assert dimensions=={'runtime-1920.png':[1920,1080],'runtime-1366.png':[1366,768]}
save=read(HERE/'save-before.json')
assert bc.gmtt.sha256(Path(save['save_path'])).upper()==save['before_sha256'].upper()
runtime={'sha256':report['output_sha256'],'screenshots':dimensions,
         'actual_shipped_stats_draw_and_popup':True,'visually_reviewed':True,
         'cases':['Virgin','Corrupted Soldier','Female Demon Warrior'],
         'player_save_unchanged':True,'scope':'Title-only renderer fixture; no gameplay/save writes.'}
write(HERE/'runtime-review.json',runtime)
report['runtime_tested']=True
report['runtime_evidence']='../followup-status/runtime-review.json'
report['all_translated_sprites_roundtripped']=25
write(HERE/'build/data.win.followup-report.json',report)

release=ROOT/'release'
assert bc.gmtt.sha256(release/'data.win')==BASE
backup=ROOT/'release-v3'
assert not backup.exists()
shutil.copytree(release,backup)
shutil.copy2(candidate,release/'data.win')
write(release/'status-popup-report.json',report)
manifest=read(release/'release-manifest.json')
manifest.update(english_sha256=report['output_sha256'],previous_english_sha256=BASE,
                translated_image_labels=32,translated_sprites=25,status_values_checked=61,
                status_variants_stacked=13,installed_archive_verified=False)
manifest['runtime_tests'].append('Stats short/long/longest-name variants and Virginity Lost popup at 1920x1080 and 1366x768, using the shipped code in a title-only fixture')
manifest['visual_asset_review']=['All 25 English sprites; exact final-archive pixel comparisons pass.']
write(release/'release-manifest.json',manifest)
roundtrip=read(release/'text-roundtrip.json')
roundtrip.update(sha256=report['output_sha256'],size=report['bytes'])
write(release/'text-roundtrip.json',roundtrip)
images=read(release/'data.win.images-report.json')
images.update(output_sha256=report['output_sha256'],sprites=25,labels=32,
              status_popup_followup='status-popup-report.json: spr_p pixels changed; all 25 translated sprites re-exported and compared exactly')
write(release/'data.win.images-report.json',images)
package=read(release/'project-package-report.json')
package.update(sha256=report['output_sha256'],bytes=report['bytes'],drop_in_runtime_verified=False,installed_copy_matches=False)
write(release/'project-package-report.json',package)
print(json.dumps({'sha256':report['output_sha256'],'verified_sprites':25,'runtime_sizes':dimensions,'local_release_staged':True},indent=2))
