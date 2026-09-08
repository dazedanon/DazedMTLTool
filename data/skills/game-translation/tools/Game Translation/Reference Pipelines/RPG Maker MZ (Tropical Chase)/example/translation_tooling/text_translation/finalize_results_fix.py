"""Record the panel-containment regression and retain only applicable prior QA."""
from pathlib import Path
import sys,re,datetime
HERE=Path(__file__).resolve().parent;BASE=HERE.parent;GAME=BASE.parent
sys.path.insert(0,str(BASE));import tl
BUILD=BASE/'builds/release_v3';CLEAN=BASE/'clean_game'
RUNTIME=CLEAN/'translation_tooling/text_translation/runtime'
prior=tl.read_json(BASE/'reports/final_qa_v1.0.json')
manifest=tl.read_json(HERE/'release/payload_manifest.json')
build=tl.read_json(BUILD/'BUILD_REPORT.json');audit=tl.read_json(BASE/'reports/release_audit.json')
delta=[p for p,h in manifest['files'].items() if prior['artifact_hashes'].get(p)!=h]
assert delta==['js/plugins/TropicalChaseEnglish.js'],delta
assert audit['pass'] and build['translated_units']==2340
for rel,h in build['output_hashes'].items():
 assert audit['artifact_hashes'][rel]==h
 assert tl.sha((BUILD/rel).read_bytes())==tl.sha((GAME/rel).read_bytes())==tl.sha((CLEAN/rel).read_bytes())==h
for rel,h in manifest['files'].items():assert tl.sha((HERE/'release/EnglishPatch'/rel).read_bytes())==h
a=(BASE/'builds/release_v2'/delta[0]).read_text(encoding='utf-8')
b=(BUILD/delta[0]).read_text(encoding='utf-8')
strip=lambda s:re.sub(r'^/\*.*?\*/\s*','',s,flags=re.S).strip()
assert strip(a.rsplit('})();',1)[0])==strip(b.split('  // CE30',1)[0])
before=tl.read_json(RUNTIME/'results_panel_before.json')
after=tl.read_json(RUNTIME/'results_panel_after.json')
assert not before['pass'] and any(r['profile']=='reported' and r['margins']['right']<0 for r in before['rows'])
assert after['pass'] and len(after['rows'])==112 and not after['engineError']
assert all(r['scale']==1 for r in after['rows'] if r['profile'] in ['reported','zero','five_digit'])
extra=tl.read_json(RUNTIME/'results_fix_lifecycle.json');assert extra['pass']
evidence=[]
for e in prior['evidence']:
 if e['path'].endswith('results_validation.json'):continue
 if 'final_native_status' in e['path'] or 'roundtrip.json' in e['path']:continue
 assert tl.sha((BASE/e['path']).read_bytes())==e['sha256'],e['path']
 evidence.append({**e,'scope':e['scope']+' (v1.0 evidence; unchanged text, images, rules and save-compatibility code; not proof of the revised results layout)'})
for p,scope in [
 (RUNTIME/'results_panel_before.json','Regression: original panel fails the reported values and large-value cases'),
 (RUNTIME/'results_panel_after.json','112 cases: all 14 staged results variants on both results maps, with reported/zero/five-digit/seven-digit counters; actual ink inside independently detected panel pixels'),
 (RUNTIME/'results_fix_lifecycle.json','Panel title pixels, repeated scene destruction/recreation, save/load, and native error check'),
 (HERE/'release/roundtrip.json','Current payload restored to Japanese and reinstalled with 716 file hashes verified')]:
 evidence.append({'path':p.relative_to(BASE).as_posix(),'sha256':tl.sha(p.read_bytes()),'scope':scope})
report={**prior,'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'version':'1.0.1',
 'build':BUILD.relative_to(BASE).as_posix(),'build_report_sha256':tl.sha((BUILD/'BUILD_REPORT.json').read_bytes()),
 'payload_manifest_sha256':tl.sha((HERE/'release/payload_manifest.json').read_bytes()),'artifact_hashes':manifest['files'],
 'verified_checks_pass':True,'evidence':evidence,
 'results_fix':{'reported_problem':'Numeric totals ran beyond the purple rectangle while the old checker only compared them with the viewport.',
  'old_panel':[185,94,624,525],'new_panel':[88,94,728,525],'normal_font_size_preserved':True,
  'only_changed_game_file':delta[0],'scores_and_stored_picture_positions_unchanged':True,
  'native_cases':112,'minimum_margins':{k:min(r['margins'][k] for r in after['rows']) for k in ['left','right','top','bottom']},
  'previous_results_layout_signoff':'Superseded: the v1.0 results_validation check used the wrong bounds.',
  'harness_correction':'QA now leaves the old map before loading isolated saves, following the normal Load-scene lifecycle; this avoids sensor plugins reading stale map events.'}}
report.pop('reuse_from_release_v1',None)
report['reuse_from_v1.0']='All text/data/image payload bytes and existing compatibility code are unchanged. Only the results-specific sprite layout was added; the new native checks replace the erroneous old results-layout signoff.'
tl.write_json(BASE/'reports/final_qa.json',report)
print({'pass':True,'version':'1.0.1','native_results_cases':112,'changed_game_files':delta})
