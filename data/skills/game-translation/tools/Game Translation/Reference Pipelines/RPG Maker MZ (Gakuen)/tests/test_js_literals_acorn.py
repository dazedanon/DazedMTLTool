"""No game files or network required. Pass --node to select an existing runtime."""
import argparse
import json
import subprocess
from pathlib import Path

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--node',default='node')
    args=parser.parse_args()
    tool=Path(__file__).resolve().parents[1]/'tools/js_literals_acorn.cjs'
    checks=[]
    def run(source):
        return subprocess.run([args.node,'--expose-internals',str(tool)],
            input=json.dumps([{'name':'fixture','source':source}],ensure_ascii=True),
            text=True,encoding='utf-8',capture_output=True)
    # Regex, comments, escaped Unicode, CRLF, an astral glyph BEFORE the target,
    # nested expressions, quotes and backticks all occur in real plugin code.
    source='// "コメント"\r\nconst face="😀"; const label="\\u65e5\\u672c";\r\nconst re=/"偽"/; const msg=`値: ${fn({x: 1})}個`;'
    r=run(source)
    assert r.returncode==0,r.stderr
    literals=json.loads(r.stdout)[0]['literals']
    assert [x['text'] for x in literals]==['😀','日本','値: ','個']
    checks.append('Comments/regex excluded; escaped Japanese decoded')
    for x in literals:
        raw=source[x['start']:x['end']]
        if x.get('fragment'):assert raw==x['raw']
        else:assert raw[0]==raw[-1]==x['quote']
    assert literals[1]['line']==2
    assert source[literals[1]['start']:literals[1]['end']]=='"\\u65e5\\u672c"'
    checks.append('Offsets preserve CRLF and convert UTF-16 to Python code points')
    replacements={'日本':'English "quoted"', '値: ':"Value ` ${literal} O'Brien: ", '個':' items'}
    edited=source
    for x in sorted(literals,key=lambda x:x['start'],reverse=True):
        if x['text'] not in replacements:continue
        body=json.dumps(replacements[x['text']],ensure_ascii=False)[1:-1]
        if x.get('fragment'):body=body.replace('`',r'\`').replace('${',r'\${')
        else:body='"'+body+'"'
        edited=edited[:x['start']]+body+edited[x['end']:]
    assert '${fn({x: 1})}' in edited
    r=run(edited);assert r.returncode==0,r.stderr
    after=json.loads(r.stdout)[0]['literals']
    assert [x['text'] for x in after]==['😀',*replacements.values()]
    checks.append('Literal splice reparses and decoded readback matches; interpolation unchanged')
    r=run('const text="unterminated;')
    assert r.returncode!=0 and not r.stdout and 'fixture:' in r.stderr
    checks.append('Invalid syntax fails with source name and no partial output')
    r=run(r'const x=tag`\unicode`;')
    assert r.returncode==0,r.stderr
    tagged=json.loads(r.stdout)[0]['literals'][0]
    assert tagged['tagged'] and tagged['review_required'] and tagged['text'] is None
    checks.append('Tagged/invalid-cooked template fragments require review')
    print(json.dumps({'pass':True,'checks':checks},indent=2))

if __name__=='__main__':main()
