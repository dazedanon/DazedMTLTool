"""Preserve reviewed project files in Tools, backing up changed destination files."""
import argparse
import datetime
import hashlib
import json
import shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DEST=Path('C:/Users/sw/Desktop/Tools/Game Translation/Active Projects/Musi Dream (TyranoScript)')
p=argparse.ArgumentParser();p.add_argument('--apply',action='store_true');a=p.parse_args()
dirs=['scripts','source','store','packets','prompts','manual','history','release','images']
files=[x for x in ROOT.iterdir() if x.is_file() and x.suffix in ('.py','.md','.json','.zip')]
for name in dirs:
    files.extend(x for x in (ROOT/name).rglob('*') if x.is_file())
files.extend(x for x in (ROOT/'reports').rglob('*') if x.is_file()
             and not any(v in x.parts for v in ('noop_output','import_test_store','import_test')))
files.extend(x for x in (ROOT/'release_tools').iterdir() if x.is_file())
files.extend(x for x in (ROOT/'build/payload').rglob('*') if x.is_file())
files=sorted(set(x for x in files if '__pycache__' not in x.parts and x.suffix not in ('.pyc','.asar','.exe','.dll')))
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
changed=[]
for source in files:
    rel=source.relative_to(ROOT)
    target=(DEST/rel).resolve()
    if not target.is_relative_to(DEST.resolve()):raise ValueError('Target escapes project')
    before=sha(target) if target.exists() else None
    after=sha(source)
    if before!=after:changed.append((source,target,rel,before,after))
result={'destination':str(DEST),'reviewed_files':len(files),'changed_files':len(changed),
        'bytes_to_copy':sum(x[0].stat().st_size for x in changed),'applied':a.apply}
if a.apply:
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    for source,target,rel,before,after in changed:
        if before is not None:
            backup=DEST/'.sync_backups'/stamp/rel
            backup.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(target,backup)
            if sha(backup)!=before:raise ValueError('Backup mismatch: '+str(rel))
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,target)
        if sha(target)!=after:raise ValueError('Copy mismatch: '+str(rel))
    result['backup_directory']=str(DEST/'.sync_backups'/stamp)
    for source in files:
        if sha(source)!=sha(DEST/source.relative_to(ROOT)):raise ValueError('Final verification mismatch')
    result['all_files_hash_verified']=True
    report=ROOT/'reports/project_sync.json'
    report.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    shutil.copy2(report,DEST/'reports/project_sync.json')
print(json.dumps(result,indent=2))
