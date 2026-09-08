"""Install only manifest-listed text files, after checking the entire source set."""
import json,sys,shutil,hashlib
from pathlib import Path
HERE=Path(__file__).resolve().parent;BASE=HERE.parent;GAME=BASE.parent
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
build=Path(sys.argv[1]).resolve();report=read(build/'BUILD_REPORT.json')
manifest=read(BASE/'manifest.json')['files']
prior=read(HERE/'installed_text.json') if (HERE/'installed_text.json').exists() else {}
for rel,m in manifest.items():
    assert sha(build/rel)==report['output_hashes'][rel],('Stale build',rel)
    expected={m['sha256']}
    if rel in prior.get('hashes',{}):expected.add(prior['hashes'][rel])
    assert sha(GAME/rel) in expected,('Unexpected game edit',rel)
changed=report['changed_files']
for rel in set(report['output_hashes'])-set(manifest):
    assert rel=='js/plugins/TropicalChaseEnglish.js',('Unexpected added file',rel)
    assert sha(build/rel)==report['output_hashes'][rel]
    if (GAME/rel).exists():assert sha(GAME/rel)==prior.get('hashes',{}).get(rel),('Unowned extra file',rel)
print('Precheck passed; installing',len(changed),'text files from',build.name)
for rel in changed:
    if rel in manifest:
        backup=HERE/'backup'/rel;backup.parent.mkdir(parents=True,exist_ok=True)
        if backup.exists():assert sha(backup)==manifest[rel]['sha256']
        else:shutil.copy2(BASE/'source'/rel,backup)
    shutil.copy2(build/rel,GAME/rel)
for rel,h in report['output_hashes'].items():assert sha(GAME/rel)==h,rel
(HERE/'installed_text.json').write_text(json.dumps({'build':str(build),'phase':report['phase'],'hashes':report['output_hashes'],'changed_files':changed},indent=2),encoding='utf-8')
print('Installed file hashes verified.')
