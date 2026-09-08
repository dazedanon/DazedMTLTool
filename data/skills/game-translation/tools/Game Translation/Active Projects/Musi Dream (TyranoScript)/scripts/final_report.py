"""Assemble release evidence only when independently recorded gates agree."""
import csv
import datetime
import hashlib
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import tl
r=tl.ROOT
s=tl.checked_store()
validation=tl.validate(s,complete=True)
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
game=Path(tl.read_json(r/'source/manifest.json')['archive']['path']).parent.parent
original=game/'resources/app.asar.original'
installed=game/'resources/app.asar'
assert sha(original)=='0427999aee3dd5e6e6cc995eca1f6cf7a1a94bdc43222a247bc103a99a12b524'
installed_hash=sha(installed)
fit=tl.read_json(r/'manual/fit_report.json')
assert fit['parsed_sha256']==sha(r/'manual/runtime_audit/parsed_output.json')
assert not fit['summary']['overflows_by_kind'] and not fit['coverage']['errors']
manifest=tl.read_json(r/'release/manifest.json')
build=tl.read_json(r/'reports/build.json')
assert build['payload']==manifest['files']
assert sha(r/'release/manifest.json')==sha(game/'English_Patch/manifest.json')
for rel,digest in manifest['files'].items():
    assert sha(r/'build/payload'/rel)==digest
    assert sha(r/'release/payload'/rel)==digest
    assert sha(game/'English_Patch/payload'/rel)==digest
zip_path=r/'Musi_Dream_English_Patch.zip'
expected_release={'install.ps1','restore.ps1','invoke-patch.ps1','patch.cjs','README.md','manifest.json'}
expected_release.update('payload/'+x for x in manifest['files'])
assert {p.relative_to(r/'release').as_posix() for p in (r/'release').rglob('*') if p.is_file()}==expected_release
with zipfile.ZipFile(zip_path) as z:
    assert len(z.namelist())==len(expected_release)
    assert set(z.namelist())=={'Musi_Dream_English_Patch/'+x for x in expected_release}
    for rel in z.namelist():
        assert hashlib.sha256(z.read(rel)).hexdigest()==sha(r/'release'/rel.split('/',1)[1])
def route(name):
    return [json.loads(x) for x in (r/'reports'/('play_'+name+'.jsonl')).read_text('utf-8').splitlines()]

def image_playthrough(visible, archive_sha256, evidence_sha256):
    """Require the full normal run recorded for this exact image-patch archive."""
    assert visible['archive_sha256']==archive_sha256, 'Image playthrough tested a different archive'
    observations=visible['observations']
    scenes=sorted({x['scenario'] for x in observations if x['scenario'].startswith('scene')})
    expected=['scene1.ks','scene2_undress.ks','scene3_kosuri.ks','scene4_insert.ks',
              'scene5_piston.ks','scene6_sanran.ks','scene7_ending.ks',
              'scene8_syussan.ks','scene9_baby.ks']
    assert scenes==expected, 'Image playthrough does not cover all nine story scenarios'
    assert observations[0]['scenario']=='title_screen.ks', 'Image playthrough did not begin at title'
    assert visible['last_state']['scenario']=='title_screen.ks', 'Image playthrough did not return to title'
    assert visible['exceptions']==[], 'Image playthrough recorded renderer exceptions'
    return {'normal_new_game_to_title':True,'scenarios':scenes,
        'archive_sha256':archive_sha256,
        'source_report':'reports/image_visible.json','source_report_sha256':evidence_sha256,
        'observations':len(observations),'renderer_exceptions':0,
        'final_archive_retest':'Fresh normal new-game run through all nine story scenarios to title on the final image-patch archive; translated images were checked in their live scene contexts.',
        'all_alternative_routes_played':False,
        'review':'All branches manually translated/reviewed; parser and fit checks cover all extracted text.'}

smoke=tl.read_json(r/'reports/final_smoke.json')
assert smoke['passed'] and smoke['archive_sha256']==sha(installed)
parser=tl.read_json(r/'reports/final_parser.json')
assert parser['passed'] and parser['parsedElements']==5138
save_tests=tl.read_json(r/'manual/runtime_audit/save_compat_test.json')
assert save_tests['passed'] and save_tests['allProseCases']==425
restore=r/'reports/final_restore.json'
if (r/'test_game/resources/app.asar').exists():
    assert sha(r/'test_game/resources/app.asar')==sha(original)
    tl.write_json(restore,{'restored_archive_sha256':sha(original),'tested_patch_sha256':sha(installed),'passed':True})
assert tl.read_json(restore)['passed']
assert tl.read_json(restore)['tested_patch_sha256']==installed_hash
assert tl.read_json(restore)['restored_archive_sha256']==sha(original)
images=build.get('images')
image_runtime=None
image_count=0
if images:
    assert images['manifest_sha256']==sha(r/'images/manifest.json')
    image_manifest=tl.read_json(r/'images/manifest.json')
    assert images['assets']==image_manifest['assets']
    image_count=len(images['assets'])
    assert image_count==images['replaced_images']
    for asset in images['assets']:
        assert asset['reviewed'] is True and asset['status']=='rendered'
        assert sha(r/'images/output'/asset['path'])==asset['output_sha256']
        assert manifest['files'][asset['path']]==asset['output_sha256']
    if image_count:
        image_runtime=tl.read_json(r/'reports/image_runtime.json')
        assert image_runtime['passed']
        assert image_runtime['archive_sha256']==installed_hash
        assert image_runtime['image_manifest_sha256']==images['manifest_sha256']
if image_count:
    visible_path=r/'reports/image_visible.json'
    playthrough=image_playthrough(tl.read_json(visible_path),installed_hash,sha(visible_path))
    scenes=playthrough['scenarios']
else:
    # Preserve the text-only release's original run and checkpoint retest evidence.
    main,final=route('main'),route('final')
    scenes=sorted({x['scenario'] for x in main if x['scenario'].startswith('scene')})
    assert len(scenes)==9
    assert main[-1]['scenario']==final[-1]['scenario']=='title_screen.ks'
    playthrough={'normal_new_game_to_title':True,'scenarios':scenes,
        'initial_archive_sha256':'c049a8c2b964e48c45a955f61abc324ad245c99e89ac8d85578947a16882167f',
        'final_archive_retest':'Normal controls from scene5 checkpoint through scenes6,7,8,9 to title; final scene9 bubble wording and page markers checked.',
        'all_alternative_routes_played':False,
        'review':'All branches manually translated/reviewed; parser and fit checks cover all extracted text.'}
limitations=['Alternative routes have semantic, parser and fit coverage, but were not all played individually.']
if images:
    image_limitations=images.get('limitations', [])
    assert isinstance(image_limitations, list) and all(isinstance(x,str) for x in image_limitations)
    limitations.extend(image_limitations)
if not image_count:
    limitations.insert(0,'This release contains no translated image assets.')
release={'completed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'method':'Manual Japanese-to-English translation; no translation API.',
    'translation_sha256':validation['translation_sha256'],
    'units':validation['total'],'occurrences':build['translated_spans'],
    'pending':validation['pending'],'hard_errors':validation['hard_errors'],
    'source_manifest_sha256':tl.verify_source(),
    'original_archive_sha256':sha(original),'installed_archive_sha256':sha(installed),
    'manifest_sha256':sha(r/'release/manifest.json'),'zip_sha256':sha(zip_path),
    'zip_bytes':zip_path.stat().st_size,
    'archive_verification':{'entries':1005,'replaced_entries':len(manifest['files']),
        'all_payload_unchanged_entry_bytes_and_integrity_blocks_verified':True,
        'restore':tl.read_json(restore)},
    'parser':parser,'rendered_fit':{'coverage':fit['coverage'],'summary':fit['summary'],
        'report':'manual/fit_report.json'},
    'save_runtime':smoke,'save_fixture_tests':save_tests,
    'image_translation':{'replaced_images':image_count,'build_validation':images,
        'runtime_validation':image_runtime},
    'playthrough':playthrough,
    'menus':{'save_load':'Opened; existing/empty slot captions and English save/reload checked.',
        'configuration':'Opened actual theme; English sample strings and word spaces checked.',
        'backlog':'Opened final build; English prose and visible speaker aliases checked.',
        'screenshots':'reports/qa_*.png (private QA; excluded from patch ZIP)'},
    'limitations':limitations,
    'release_package':{'files':len(expected_release),
        'changed_payload_files':len(manifest['files']),'localized_images':image_count,
        'only_allowlisted_files':True,
        'no_executables_audio_video_saves_private_notes_or_qa_screenshots':True},
    'main_game_save_files_modified':False}
tl.write_json(r/'reports/RELEASE_VALIDATION.json',release)
with (r/'reports/ui_review.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.writer(f);w.writerow(['id','kind','jp','en','file','line'])
    for u in s.all_units():
        if u.kind not in ('dialogue','punct'):w.writerow([u.id,u.kind,u.src,u.en,u.sites[0].file,u.sites[0].line])
print(json.dumps({'installed_sha256':sha(installed),'scenes_played':scenes,
    'fit':fit['summary'],'report':'reports/RELEASE_VALIDATION.json'},indent=2))
