"""Combined image/text patch verification, exact restoration and packaging."""
from pathlib import Path
import sys,json,shutil,zipfile
HERE=Path(__file__).resolve().parent;BASE=HERE.parent;GAME=BASE.parent
sys.path.insert(0,str(BASE));import tl
release=HERE/'release';payload=release/'EnglishPatch';manifest=tl.read_json(release/'payload_manifest.json')
original={rel:(tl.SOURCE/rel,m['sha256']) for rel,m in tl.read_json(BASE/'manifest.json')['files'].items()}
for row in tl.read_json(BASE/'image_review/inventory.json'):
    rel=row['path'];backup=BASE/'image_translation/backup'/rel
    original[rel]=(backup if backup.exists() else GAME/rel,row['sha256'])
extra='js/plugins/TropicalChaseEnglish.js'
def verify(english=True):
    for rel,(src,h) in original.items():
        expected=manifest['files'].get(rel,h) if english else h
        assert tl.sha((GAME/rel).read_bytes())==expected,('Installed mismatch',rel)
    if english:assert tl.sha((GAME/extra).read_bytes())==manifest['files'][extra]
    else:assert not (GAME/extra).exists()
    return {'verified_original_or_english_files':len(original)+1,'english':english}
def install():
    verify(False)
    for rel,h in manifest['files'].items():assert tl.sha((payload/rel).read_bytes())==h
    for rel in manifest['files']:shutil.copy2(payload/rel,GAME/rel)
    return verify(True)
def restore():
    verify(True)
    for rel in manifest['files']:
        if rel==extra:continue
        src,h=original[rel];assert tl.sha(src.read_bytes())==h,('Bad original backup',rel)
    for rel in manifest['files']:
        if rel!=extra:shutil.copy2(original[rel][0],GAME/rel)
    target=(GAME/extra).resolve();assert target.parent==(GAME/'js/plugins').resolve() and target.name=='TropicalChaseEnglish.js'
    target.unlink()
    return verify(False)
def package():
    verify(True)
    audit=tl.read_json(BASE/'reports/release_audit.json');assert audit['pass']
    qa=tl.read_json(BASE/'reports/final_qa.json')
    assert qa['translation_complete'] and qa['verified_checks_pass']
    assert qa['artifact_hashes']==manifest['files']
    assert qa['payload_manifest_sha256']==tl.sha((release/'payload_manifest.json').read_bytes())
    for rel,h in audit['artifact_hashes'].items():assert tl.sha((GAME/rel).read_bytes())==h
    for e in qa['evidence']:assert tl.sha((BASE/e['path']).read_bytes())==e['sha256'],('QA evidence changed',e['path'])
    for rel,h in manifest['files'].items():assert tl.sha((payload/rel).read_bytes())==h
    names=set(manifest['files'])|{'README_English.txt','EnglishPatch_Manifest.json'}
    assert {p.relative_to(payload).as_posix() for p in payload.rglob('*') if p.is_file()}==names
    dst=GAME/'Tropical_Chase_English_Patch.zip';tmp=dst.with_suffix('.zip.tmp')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for rel in sorted(names):z.write(payload/rel,'EnglishPatch/'+rel)
    with zipfile.ZipFile(tmp) as z:
        assert set(z.namelist())=={'EnglishPatch/'+p for p in names};assert z.testzip() is None
        for rel,h in manifest['files'].items():assert tl.sha(z.read('EnglishPatch/'+rel))==h
    tmp.replace(dst)
    result={'archive':dst.name,'sha256':tl.sha(dst.read_bytes()),'bytes':dst.stat().st_size,'entries':len(names),'game_files':len(manifest['files'])}
    tl.write_json(release/'archive_report.json',result);return result
command=sys.argv[1]
if command=='roundtrip':
    a=restore();b=install();result={'restore':a,'reinstall':b};tl.write_json(release/'roundtrip.json',result)
elif command=='verify':result=verify(True)
elif command=='restore':result=restore()
elif command=='install':result=install()
elif command=='package':result=package()
else:raise ValueError(command)
print(json.dumps(result,indent=2))
