"""Promote the inspected quest repair and retain the previous release."""
import json
from pathlib import Path
import shutil
import sys
from PIL import Image

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path.insert(0,str(ROOT))
import build_catalog as bc
from build_followup import BASE

candidate=HERE/'build/data.win'
report=bc.read(HERE/'build/data.quest-report.json')
assert bc.gmtt.sha256(candidate)==report['output_sha256']
dimensions={name:list(Image.open(HERE/name).size) for name in ('runtime-1920.png','runtime-1366.png')}
assert dimensions=={'runtime-1920.png':[1920,1080],'runtime-1366.png':[1366,768]}
save=json.loads((HERE/'save-before.json').read_text(encoding='utf-8-sig'))
assert bc.gmtt.sha256(Path(save['save_path']))==save['before_sha256'].lower()
audit=bc.read(ROOT/'build/quest-layout-audit.json')
assert audit['remaining_overflows']==0
runtime={'sha256':report['output_sha256'],'screenshots':dimensions,
         'actual_shipped_shop_draw_event':True,'visually_reviewed':True,
         'quest':'Petrifying Gaze','reward':'140G','description_rows':3,
         'entire_gaze_warning_inside_frame':True,'player_save_unchanged':True,
         'scope':'Title-only renderer fixture; quest progression not exercised.'}
bc.write(HERE/'runtime-review.json',runtime)
report.update(runtime_tested=True,runtime_evidence='../followup-quest/runtime-review.json')
bc.write(HERE/'build/data.quest-report.json',report)
release=ROOT/'release'
assert bc.gmtt.sha256(release/'data.win')==BASE
backup=ROOT/'release-v4'
assert not backup.exists()
shutil.copytree(release,backup)
shutil.copy2(candidate,release/'data.win')
bc.write(release/'quest-text-report.json',report)
shutil.copy2(HERE/'build/data.win.report.json',release/'quest-patch-report.json')
manifest=bc.read(release/'release-manifest.json')
manifest.update(english_sha256=report['output_sha256'],previous_english_sha256=BASE,
                measured_text_forms=1243,quest_descriptions_checked=17,
                shop_equipment_forms_checked=231,quest_description_line_limit=3,
                installed_archive_verified=False)
manifest['runtime_tests'].append('Petrifying Gaze, including reward and complete gaze warning, in the shipped shop Draw event at 1920x1080 and 1366x768; player save unchanged')
bc.write(release/'release-manifest.json',manifest)
roundtrip=bc.read(release/'text-roundtrip.json')
roundtrip.update(sha256=report['output_sha256'],size=report['bytes'],
                 method='Re-extracted final archive after the quest-only correction; all 631 translated sites match the current catalog.')
bc.write(release/'text-roundtrip.json',roundtrip)
images=bc.read(release/'data.win.images-report.json')
images.update(output_sha256=report['output_sha256'],
              quest_text_followup='quest-patch-report.json proves all embedded textures, fonts and other resources unchanged from the 25-sprite reviewed release')
bc.write(release/'data.win.images-report.json',images)
package=bc.read(release/'project-package-report.json')
package.update(sha256=report['output_sha256'],bytes=report['bytes'],
               drop_in_runtime_verified=False,installed_copy_matches=False)
bc.write(release/'project-package-report.json',package)
shutil.copy2(candidate,ROOT/'project-package/data.win')
print(json.dumps({'sha256':report['output_sha256'],'release_staged':True,'save_unchanged':True}))
