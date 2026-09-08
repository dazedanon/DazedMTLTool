"""Apply the requested window credit without changing gameplay or save identity."""
import argparse
import json
from pathlib import Path
import build_catalog as bc

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('input',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    assert args.input.is_file() and not args.output.exists()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    snapshot=bc.gmtt.snapshot(args.input)
    site=bc.gmtt.site_map(snapshot)['GEN8:display_name']
    caption=bc.read(bc.ROOT/'title-credit.json')['caption']
    assert site['source']=='Nightfall Princess',site['source']
    assert caption=='Nightfall Princess | Translated by len'
    catalog={'schema':1,'engine':'GameMaker','source_sha256':snapshot['source_sha256'],
             'source_size':snapshot['source_size'],'selection':'all','token_patterns':[r'\r\n|\r|\n'],
             'entries':[{'id':'GEN8:display_name',**site,'masked_source':site['source'],'tokens':[],
                         'translation':caption,'reviewed':True,'font':None,'max_width':None,'max_lines':None}]}
    path=args.output.with_suffix(args.output.suffix+'.title-catalog.json')
    bc.write(path,catalog)
    bc.gmtt.patch_archive(args.input,path,args.output)
    after=bc.gmtt.snapshot(args.output)
    assert after['project']==snapshot['project']
    sites=bc.gmtt.site_map(after)
    assert sites['GEN8:display_name']['source']==caption
    translation=bc.read(bc.ROOT/'build/catalog.en.json')
    assert all(sites[e['id']]['source']==bc.gmtt.restore(e['translation'],e['tokens']) for e in translation['entries'])
    report={'caption':caption,'sha256':after['source_sha256'],'previous_sha256':snapshot['source_sha256'],
            'translated_sites_preserved':len(translation['entries']),'save_identity_preserved':after['project'],
            'code_unchanged':after['code']==snapshot['code'],
            'fonts_and_media_unchanged':all(after[k]==snapshot[k] for k in ('fonts','texture_sha256','audio_sha256'))}
    assert report['code_unchanged'] and report['fonts_and_media_unchanged']
    bc.write(args.output.with_suffix(args.output.suffix+'.title-report.json'),report)
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
