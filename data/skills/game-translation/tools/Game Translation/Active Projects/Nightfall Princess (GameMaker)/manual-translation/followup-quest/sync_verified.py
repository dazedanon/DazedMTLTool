"""Publish the verified local build to the existing stable tooling workspace."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
from PIL import Image

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path.insert(0,str(ROOT))
import build_catalog as bc

stable=bc.PROJECT/'manual-translation'
project=Path('C:/Users/sw/Desktop/Projects/nightfall-princess-en')
assert stable.resolve()==Path('C:/Users/sw/Desktop/Tools/Game Translation/Active Projects/Nightfall Princess (GameMaker)/manual-translation').resolve()
release=ROOT/'release'
report=bc.read(release/'quest-text-report.json')
expected=report['output_sha256']
assert report['runtime_tested']
for path in (release/'data.win',ROOT.parent/'data.win',ROOT/'project-package/data.win',
             project/'data.win',HERE/'drop-in-test/data.win'):
    assert bc.gmtt.sha256(path)==expected,str(path)
assert bc.gmtt.sha256(stable/'release/data.win') in (report['input_sha256'],expected)
assert Image.open(HERE/'drop-in-title.png').size==(1920,1080)
save=json.loads((HERE/'save-before.json').read_text(encoding='utf-8-sig'))
assert bc.gmtt.sha256(Path(save['save_path']))==save['before_sha256'].lower()
commit=subprocess.check_output(['git','-C',str(project),'rev-parse','--short','HEAD'],text=True).strip()
assert not subprocess.check_output(['git','-C',str(project),'status','--porcelain'],text=True).strip()
package=bc.read(release/'project-package-report.json')
package.update(local_commit=commit,drop_in_runtime_verified=True,save_unchanged=True,installed_copy_matches=True)
bc.write(release/'project-package-report.json',package)
manifest=bc.read(release/'release-manifest.json')
manifest['installed_archive_verified']=True
manifest['runtime_tests'].append('Quest-corrected drop-in project payload launched to the title menu with the credited caption; player save unchanged')
bc.write(release/'release-manifest.json',manifest)
bc.write(HERE/'drop-in-runtime-review.json',{
    'sha256':expected,'source':str(project/'data.win'),'caption':'Nightfall Princess | Translated by len',
    'title_menu_visually_reviewed':True,'screenshot':'drop-in-title.png','player_save_unchanged':True,
    'local_commit':commit,'test_process_closed':True})

files=[ROOT/name for name in ('README.md','quests.en.json','quest_audit.py','layout_audit.py',
                              'install_translation.py','installation.json')]
files += [ROOT/'followup-status'/name for name in ('build_followup.py','README.md','status-audit.json')]
files += [p for p in (ROOT/'build').iterdir() if p.is_file() and p.suffix in ('.json','.tsv')]
files += [p for p in HERE.rglob('*') if p.is_file() and 'drop-in-test' not in p.parts
          and '__pycache__' not in p.parts and p.suffix.lower() not in ('.win','.exe','.pyc')]
files += [p for p in release.iterdir() if p.is_file()]
files += [ROOT/'project-package/data.win']
for path in files:
    relative=path.relative_to(ROOT)
    target=stable/relative
    assert target.resolve().is_relative_to(stable.resolve())
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(path,target)
    assert bc.gmtt.sha256(path)==bc.gmtt.sha256(target),str(relative)
hashes={name:bc.gmtt.sha256(path) for name,path in {
    'installed':ROOT.parent/'data.win','local_release':release/'data.win',
    'stable_tooling_release':stable/'release/data.win','drop_in_project':project/'data.win'}.items()}
assert set(hashes.values())=={expected}
receipt={'hashes':hashes,'synced_files':len(files),'all_equal':True,'local_commit':commit,
         'player_save_unchanged':True,'no_remote_publish':True}
bc.write(HERE/'delivery-report.json',receipt)
bc.write(stable/'followup-quest/delivery-report.json',receipt)
print(json.dumps(receipt,indent=2))
