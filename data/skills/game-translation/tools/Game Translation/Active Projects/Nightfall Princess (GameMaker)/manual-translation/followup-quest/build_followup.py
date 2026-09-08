"""Apply the reviewed quest-only text correction to the preceding English patch."""
import argparse
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
import build_catalog as bc
from quest_audit import OLD_TEXT

BASE = 'ea0fd75ab30a5e5e3c64dddebd518ea54043cdaae646eac7a93d4e4843312b0a'
SITE = 'CODE:110:97'

def build(source,output):
    assert bc.gmtt.sha256(source)==BASE and not output.exists()
    output.parent.mkdir(parents=True,exist_ok=True)
    before=bc.gmtt.snapshot(source)
    sites=bc.gmtt.site_map(before)
    canonical=bc.read(bc.ROOT/'build/catalog.en.json')
    wanted={e['id']:bc.gmtt.restore(e['translation'],e['tokens']) for e in canonical['entries']}
    assert len(wanted)==631
    assert [key for key,value in wanted.items() if sites[key]['source']!=value]==[SITE]
    site=sites[SITE]
    assert site['source']==OLD_TEXT
    catalog={'schema':1,'engine':'GameMaker','source_sha256':before['source_sha256'],
             'source_size':before['source_size'],'selection':'all','token_patterns':[r'\r\n|\r|\n'],
             'entries':[{'id':SITE,**site,'masked_source':OLD_TEXT,'tokens':[],
                         'translation':wanted[SITE],'reviewed':True,'font':'font_2',
                         'max_width':None,'max_lines':None}]}
    config=output.with_suffix('.catalog.json')
    bc.write(config,catalog)
    bc.gmtt.patch_archive(source,config,output)
    after=bc.gmtt.snapshot(output)
    actual=bc.gmtt.site_map(after)
    assert all(actual[key]['source']==value for key,value in wanted.items())
    changed=[key for key in sites if sites[key]['source']!=actual[key]['source']]
    assert changed==[SITE],changed
    assert before['strings']==after['strings'][:len(before['strings'])]
    for key in ('fonts','texture_sha256','audio_sha256','resources','project'):
        assert before[key]==after[key],key
    assert actual['GEN8:display_name']['source']=='Nightfall Princess | Translated by len'
    report={'input_sha256':BASE,'output_sha256':after['source_sha256'],
            'bytes':output.stat().st_size,'changed_sites':changed,'old_text':OLD_TEXT,
            'new_text':wanted[SITE],'translated_sites_checked':len(wanted),
            'all_other_literals_preserved':True,'previous_string_pool_preserved':True,
            'fonts_images_audio_resources_save_identity_preserved':True,
            'caption_preserved':True,'runtime_tested':False}
    bc.write(output.with_suffix('.quest-report.json'),report)
    print(__import__('json').dumps(report,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('input',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    build(args.input,args.output)
