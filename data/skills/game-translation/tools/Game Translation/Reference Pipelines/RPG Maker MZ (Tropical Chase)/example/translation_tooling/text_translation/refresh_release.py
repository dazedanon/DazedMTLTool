"""Refresh an owned staged payload and clean game after a reviewed text revision."""
from pathlib import Path
import json,sys,shutil
HERE=Path(__file__).resolve().parent;BASE=HERE.parent
sys.path.insert(0,str(BASE));import tl
build=Path(sys.argv[1]).resolve();report=tl.read_json(build/'BUILD_REPORT.json')
release=HERE/'release';payload=release/'EnglishPatch';clean=BASE/'clean_game'
old=tl.read_json(release/'payload_manifest.json')
files={rel:build/rel for rel in report['changed_files']}
for r in tl.read_json(BASE/'image_translation/manifest.json')['assets']:files[r['path']]=BASE/'image_translation/payload'/r['path']
assert set(files)==set(old['files']),'Payload paths changed; separate reviewed migration required'
for root in [payload,clean]:
    for rel,h in old['files'].items():assert tl.sha((root/rel).read_bytes())==h,('Unexpected staging edit',root,rel)
new={**old,'files':{rel:tl.sha(p.read_bytes()) for rel,p in files.items()}}
for root in [payload,clean]:
    for rel,p in files.items():shutil.copy2(p,root/rel)
    for rel,h in new['files'].items():assert tl.sha((root/rel).read_bytes())==h
tl.write_json(release/'payload_manifest.previous.json',old)
tl.write_json(release/'payload_manifest.json',new);tl.write_json(payload/'EnglishPatch_Manifest.json',new)
tl.write_json(release/'clean_revision.json',{'build':build.name,'changed_paths':[p for p,h in new['files'].items() if old['files'][p]!=h],'hashes':new['files']})
print('Refreshed 69 owned payload files and verified the independent game copy.')
