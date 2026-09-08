"""Destructive-path and corruption regression checks on throwaway staging only."""
import copy
import json
import subprocess
import contextlib
import shutil
import uuid
from pathlib import Path
import tl

@contextlib.contextmanager
def test_directory():
    # Python 3.14 TemporaryDirectory uses a private Windows ACL that conflicts
    # with restricted workspace tokens. Inherit the workspace ACL instead.
    root=tl.REPORTS.resolve()
    path=root/('selftest-'+uuid.uuid4().hex)
    path.mkdir()
    try:
        yield path
    finally:
        resolved=path.resolve()
        if resolved.parent!=root or not resolved.name.startswith('selftest-'):
            raise ValueError('Unsafe cleanup target')
        shutil.rmtree(resolved)

def require_failure(fn, text):
    try:
        fn()
    except ValueError as e:
        assert text in str(e),str(e)
    else:
        raise AssertionError('Expected rejection: '+text)

def main():
    original=tl.STORE.read_bytes()
    store=tl.read_json(tl.STORE)
    checks=[]
    # A known Japanese canary proves both JS parsing and Unicode decoding work.
    canary=tl.js_parse([{'name':'canary','source':'// "コメント"\nconst x = "日本語"; const t = `表示 ${n}`;'}])['canary']
    assert [x['text'] for x in canary]==['日本語','表示 ','']
    checks.append('JS parser canary: comments ignored, Unicode and template spans read')
    sample=r'\F3[sn_01]\F5[m_01]\F6[\V[1]]\AA[N]Display'
    masked,cmap=tl.codes.mask_codes(sample)
    assert masked=='⟦0⟧⟦1⟧⟦2⟧⟦3⟧Display'
    assert tl.codes.unmask_codes(masked,cmap,pad_inserts=False)==sample
    checks.append('Numbered portrait IDs and nested variable arguments are indivisible placeholders')
    with test_directory() as tmp:
        temp=Path(tmp)
        # An empty store is the exact identity for every snapshotted source file.
        noop=copy.deepcopy(store)
        for u in noop['units']:u['target']=''
        result=tl.build(temp/'noop',noop)
        assert result['changed_files']==[]
        for rel,meta in tl.read_json(tl.BASE/'manifest.json')['files'].items():
            assert tl.sha((temp/'noop'/rel).read_bytes())==meta['sha256'],rel
        checks.append('106 source files byte-identical through an empty build')
        # Exercise every real write-back site, including the actual validator.
        synthetic=copy.deepcopy(store)
        for i,u in enumerate(synthetic['units']):
            u['target']=f"Probe {i}: O'Brien says \"hello\" ` ${{literal}} " + ' '.join(u['codes'])
        result=tl.build(temp/'synthetic',synthetic)
        assert result['translated_units']==len(store['units'])
        checks.append(f"All {len(store['units'])} units / {sum(len(u['sites']) for u in store['units'])} sites injected with synthetic English; string-only structural proof passed")
        checks.append('Patched JS reparsed and decoded literal values read back')
        # Also verify every VALUE and SPAN in the *written* files, not the in-memory tree.
        targets=tl.targets_for(synthetic)
        docs={}
        for u in synthetic['units']:
            for site in u['sites']:
                rel=site['file']
                if rel not in docs:
                    p=temp/'synthetic'/rel
                    if rel=='js/plugins.js':docs[rel]=tl.plugins_doc(p.read_text(encoding='utf-8-sig'))[0]
                    elif rel.endswith('.json'):docs[rel]=tl.read_json(p)
                    else:docs[rel]=p.read_text(encoding='utf-8-sig')
                value=tl.get(docs[rel],site['path'])
                target=targets[u['id']]
                if site['mode']=='value':
                    fixes=[f for f in result['source_corrections'] if f['file']==rel and f['path']==site['path']]
                    expected=fixes[0]['target'] if fixes else target
                    assert value==expected,(rel,site['path'])
                elif site['mode']=='run':
                    rendered='\n'.join(c['parameters'][0] for c in value[site['start']:site['start']+site['count']])
                    assert rendered.rstrip('\n')==target,(rel,site['start'])
                elif site['mode']=='span':assert target in value
        checks.append('All written JSON values, message runs and note values read back')
        require_failure(lambda:tl.build(temp/'synthetic',synthetic),'must be new')
        checks.append('Existing output refused (prevents stale merged builds)')
        bad=copy.deepcopy(synthetic)
        coded=next(u for u in bad['units'] if len(u['codes'])>1)
        coded['target']='Probe '+ ' '.join(reversed(coded['codes']))
        require_failure(lambda:tl.targets_for(bad),'reordered placeholders')
        coded['target']='Probe '
        require_failure(lambda:tl.targets_for(bad),'missing, added')
        coded['target']='Probe '+ ' '.join(coded['codes'])+' '+next(iter(coded['codes']))
        require_failure(lambda:tl.targets_for(bad),'duplicated')
        checks.append('Actual validator rejects missing, duplicated and reordered controls')
        bad=copy.deepcopy(synthetic);bad['units'][0]['target']='日本語 '+' '.join(bad['units'][0]['codes'])
        require_failure(lambda:tl.targets_for(bad),'Japanese remains')
        checks.append('Actual validator rejects Japanese residue')
        altered=copy.deepcopy(synthetic)
        next(u for u in altered['units'] if u['sites'][0]['mode']=='value')['sites'][0]['original']='wrong source'
        require_failure(lambda:tl.build(temp/'bad-source',altered),'Catalog metadata changed')
        checks.append('Changed catalog source metadata rejected before replacement')
        p=temp/'stale-store';altered=copy.deepcopy(synthetic);altered['source_manifest']='stale'
        require_failure(lambda:tl.build(p,altered),'manifest mismatch')
        checks.append('Stale catalog rejected')
    result=subprocess.run([tl.CFG['node'],'--expose-internals',str(tl.BASE/'runtime_probe.cjs'),str(tl.SOURCE)],capture_output=True,text=True,encoding='utf-8')
    assert result.returncode==0,result.stderr
    runtime=json.loads(result.stdout)
    checks.append('Shipped engine parser: spaces, escape parsing and message command index verified')
    assert tl.STORE.read_bytes()==original,'Selftest modified the translation store'
    tl.verify_source()
    tl.write_json(tl.REPORTS/'selftest.json',{'pass':True,'checks':checks,'runtime':runtime,'game_launched':False})
    print(json.dumps({'pass':True,'checks':checks},indent=2))

if __name__=='__main__':main()
