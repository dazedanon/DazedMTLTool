"""Package freshly injected text and reviewed images, excluding private QA/source."""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser()
p.add_argument('--game-root',type=Path,default=ROOT.parent)
a=p.parse_args()
subprocess.run([sys.executable,str(ROOT/'scripts/build.py')],check=True)
game=a.game_root.resolve()
original=game/'resources/app.asar.original'
if not original.exists(): original=game/'resources/app.asar'
with original.open('rb') as f: original_hash=hashlib.file_digest(f,'sha256').hexdigest()
if original_hash!='0427999aee3dd5e6e6cc995eca1f6cf7a1a94bdc43222a247bc103a99a12b524':
    raise ValueError('Unsupported original game archive')
out=ROOT/'release'
out.mkdir(exist_ok=True)
allowed=['install.ps1','restore.ps1','invoke-patch.ps1','patch.cjs','README.md']
for name in allowed: shutil.copy2(ROOT/'release_tools'/name,out/name)
payload=ROOT/'build/payload'
shutil.copytree(payload,out/'payload',dirs_exist_ok=True)
files={p.relative_to(payload).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
       for p in sorted(payload.rglob('*')) if p.is_file()}
build=json.loads((ROOT/'reports/build.json').read_text(encoding='utf-8-sig'))
if build['payload']!=files:
    raise ValueError('Payload changed after the validated build')
manifest={'format_version':1,'game_executable':'musi_dream.exe',
          'original_sha256':original_hash,'files':files}
(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
expected=set(allowed+['manifest.json']+['payload/'+x for x in files])
actual={p.relative_to(out).as_posix() for p in out.rglob('*') if p.is_file()}
if expected!=actual: raise ValueError(f'Unexpected stale release files: {actual-expected}')
archive=ROOT/'Musi_Dream_English_Patch.zip'
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
    for rel in sorted(expected): z.write(out/rel,'Musi_Dream_English_Patch/'+rel)
print(json.dumps({'archive':str(archive),'files':len(expected),'bytes':archive.stat().st_size,
                 'changed_payload_files':len(files),
                 'localized_images':(build.get('images') or {}).get('replaced_images',0),
                 'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()},indent=2))
