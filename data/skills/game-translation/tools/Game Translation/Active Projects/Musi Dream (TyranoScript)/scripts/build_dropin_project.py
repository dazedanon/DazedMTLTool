"""Build a minimal player Git tree from the durable, validated release.

No extraction, translation, network calls, or game writes. Rebuild tools and QA
stay in the Tools project; the generated directory contains only player files
and its Git allowlist. Refuses stale/unknown files instead of deleting them.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path('C:/Users/sw/Desktop/Tools/Game Translation/Active Projects/Musi Dream (TyranoScript)')
README="""# Musi Dream - English Patch

English text and 30 translated image assets. Translation by **len**.
Translated manually, without APIs. Requires your own Windows copy of the game.

## Install

1. Close the game. If updating an older English patch, restore Japanese with that patch first.
2. Copy `English_Patch`, `Install_English.cmd`, and `Restore_Japanese.cmd` beside `musi_dream.exe`.
3. Double-click `Install_English.cmd`, then launch `musi_dream.exe` normally.

No Python, separate Node installation, API key, or internet connection is needed.
The installer checks the game version and creates `resources/app.asar.original`
as an exact backup before applying the patch. Keep that backup and `English_Patch`.

Your saves are unchanged. To uninstall, close the game and double-click
`Restore_Japanese.cmd`. Installing this same patch again is safe.

One video-listing image (`ev_Hdouga.jpg`) remains untranslated.
Original game and artwork: **Horochi / 250歩の路地**. Keep the game's original credits.
"""

def sha(data):return hashlib.sha256(data).hexdigest()

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--output',type=Path,default=ROOT/'dropin_stage/musi-dream-en')
 a=p.parse_args();out=a.output.resolve()
 release=SOURCE/'release'
 evidence=json.loads((SOURCE/'reports/RELEASE_VALIDATION.json').read_text(encoding='utf8'))
 manifest_bytes=(release/'manifest.json').read_bytes()
 manifest=json.loads(manifest_bytes)
 assert sha(manifest_bytes)==evidence['manifest_sha256']
 assert len(manifest['files'])==50 and evidence['image_translation']['replaced_images']==30
 assert evidence['image_translation']['runtime_validation']['passed']
 assert evidence['playthrough']['normal_new_game_to_title']
 assets={}
 for name in ['install.ps1','restore.ps1','invoke-patch.ps1','patch.cjs','manifest.json']:
  assets['English_Patch/'+name]=(release/name).read_bytes()
 for rel,digest in manifest['files'].items():
  if Path(rel).is_absolute() or '\\' in rel or ':' in rel or any(v in ('','..','.')for v in rel.split('/')):
   raise ValueError('Unsafe payload path: '+rel)
  data=(release/'payload'/rel).read_bytes();assert sha(data)==digest
  assets['English_Patch/payload/'+rel]=data
 assert not any('ev_Hdouga.jpg' in name for name in assets)
 assets['README.md']=README.encode('utf8')
 for name,script in [('Install_English.cmd','install.ps1'),('Restore_Japanese.cmd','restore.ps1')]:
  text='\r\n'.join(['@echo off',
   f'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0English_Patch\\{script}" -GameRoot "%~dp0."',
   'set "_MUSI_PATCH_EXIT=%errorlevel%"',
   'if not "%_MUSI_PATCH_EXIT%"=="0" pause',
   'exit /b %_MUSI_PATCH_EXIT%',''])
  assets[name]=text.encode('ascii')
 assets['.gitattributes']=b'# Preserve the exact tested payload bytes on every checkout.\n* -text\n'
 expected=set(assets)|{'.gitignore'}
 parents={p.as_posix()for rel in expected for p in Path(rel).parents if p.as_posix()!='.'}
 ignore=['# Only the reviewed player patch is tracked.','*']
 ignore+=['!/'+d+'/'for d in sorted(parents,key=lambda x:(x.count('/'),x))]
 ignore+=['!/'+f for f in sorted(expected)]
 assets['.gitignore']=('\n'.join(ignore)+'\n').encode('utf8')
 if out.exists():
  actual={x.relative_to(out).as_posix()for x in out.rglob('*')if x.is_file()and'.git'not in x.relative_to(out).parts}
  if actual-expected:raise ValueError('Unexpected files in destination: '+str(sorted(actual-expected)))
 out.mkdir(parents=True,exist_ok=True)
 for rel,data in sorted(assets.items()):
  target=out/rel
  if target.is_symlink() or not target.resolve().is_relative_to(out):raise ValueError('Unsafe destination: '+str(target))
  target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
 actual={x.relative_to(out).as_posix()for x in out.rglob('*')if x.is_file()and'.git'not in x.relative_to(out).parts}
 assert actual==expected
 for rel,data in assets.items():assert (out/rel).read_bytes()==data
 report={'project_name':'musi-dream-en','output':str(out),'source_project':str(SOURCE),
  'files':{x:sha(assets[x])for x in sorted(assets)},'tracked_files':len(assets),
  'runtime_files':len(assets)-2,'payload_files':50,'translated_images':30,
  'release_manifest_sha256':sha(manifest_bytes),'expected_archive_sha256':evidence['installed_archive_sha256'],
  'prior_release_validation_sha256':sha((SOURCE/'reports/RELEASE_VALIDATION.json').read_bytes()),
  'unchanged_runtime_payload':True,'bytes':sum(map(len,assets.values()))}
 (ROOT/'reports/dropin_build.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
 print(json.dumps({k:report[k]for k in ('output','tracked_files','runtime_files','payload_files','translated_images','bytes')},indent=2))

if __name__=='__main__':main()
