import json
import tempfile
import contextlib
import uuid
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

import project as p
import claude_batch as b
from tyranotl.store import Unit,Site
from tyranotl import codes,jsstr,kslex

TEST_TMP = p.ROOT/'qa'/'temporary'
TEST_TMP.mkdir(parents=True,exist_ok=True)

@contextlib.contextmanager
def fixture():
    # Python 3.14 TemporaryDirectory's restrictive Windows ACL excludes the
    # sandbox token. A normal workspace directory inherits the usable ACL.
    target=(TEST_TMP/uuid.uuid4().hex).resolve()
    target.mkdir()
    try:yield str(target)
    finally:
        if TEST_TMP.resolve() not in target.parents:
            raise ValueError('unsafe fixture cleanup')
        shutil.rmtree(target)


class ToolingTests(unittest.TestCase):
    def test_real_validator_valid_and_invalid(self):
        u=Unit(id='x',kind='dialogue',src='日本語⟦0⟧',sites=[Site('x.ks',1,0,3,tokens=['[r]'])])
        self.assertEqual(p.validate_text(u,'Hello⟦0⟧'),[])
        for bad in ['',None,'Hello','日本語⟦0⟧','Hello⟦item⟧','*Hello⟦0⟧','Hello\n⟦0⟧','Hello[tag]⟦0⟧']:
            self.assertTrue(p.validate_text(u,bad),repr(bad))

    def test_placeholder_order_and_occurrence_maps(self):
        u=Unit(id='x',kind='dialogue',src='a⟦0⟧b⟦1⟧')
        self.assertIn('placeholder-sequence',p.validate_text(u,'a⟦1⟧b⟦0⟧'))
        a=Site('x.ks',1,0,3,tokens=['[emb exp="f.one"]'])
        c=Site('x.ks',2,0,3,tokens=['[emb exp="f.two"]'])
        self.assertNotEqual(p.render_site(u,a,'Hello ⟦0⟧'),p.render_site(u,c,'Hello ⟦0⟧'))

    def test_template_before_kag_masking(self):
        src="${tiredCharacters[0]}は疲れているようです。"
        masked,tokens=codes.mask(src)
        self.assertEqual(tokens,['${tiredCharacters[0]}'])
        self.assertEqual(codes.restore(masked,tokens),src)

    def test_json_reply_contract(self):
        self.assertEqual(b.parse_reply('{"t":{"0":"Hi"}}',['0']),{'0':'Hi'})
        for bad in ['{"t":{"0":"A","0":"B"}}','{"t":{"1":"Hi"}}','{"t":{"0":"Hi","1":"extra"}}','{}','```json\n{}\n```']:
            with self.assertRaises(ValueError):b.parse_reply(bad,['0'])

    def test_import_uses_validator_and_does_not_erase(self):
        with fixture() as tmp:
            u=Unit(id='x',kind='dialogue',src='日本語')
            with patch.object(p,'ROOT',Path(tmp)),patch.object(p,'load_catalog',return_value=({},[u])):
                self.assertEqual(b.import_mapping({'x':'Hello'},{'test':True}),1)
                with self.assertRaises(ValueError):b.import_mapping({'x':'日本語'},{})
                with self.assertRaises(ValueError):b.import_mapping({'other':'Hello'},{})
                with self.assertRaises(ValueError):b.import_mapping({'x':'Changed'},{})
                self.assertEqual(b.store()['translations'],{'x':'Hello'})

    def test_cross_process_lock_refuses_second_submit(self):
        with fixture() as tmp:
            with b.lock(Path(tmp)):
                with self.assertRaises(FileExistsError):
                    with b.lock(Path(tmp)):pass
            self.assertFalse((Path(tmp)/'operation.lock').exists())

    def test_batch_splitting_and_limits(self):
        rows=[{'custom_id':str(i),'params':{'model':'test'}} for i in range(5)]
        self.assertEqual([len(x) for x in b.split_requests(rows,max_count=2)],[2,2,1])
        with self.assertRaises(ValueError):b.split_requests(rows,max_bytes=10)

    def test_paths(self):
        with fixture() as tmp:
            with self.assertRaises(ValueError):p.safe_path(Path(tmp),'../outside')

    def test_multiline_comment_state_and_encoding(self):
        text='/* example\n"日本語"\n*/\nlet x="表示";'
        self.assertEqual([x.value for x in jsstr.scan(text)],['表示'])
        with fixture() as tmp:
            file=Path(tmp)/'test.js';raw='// 日本語\r\nvar x="表示";\n'.encode('cp932');file.write_bytes(raw)
            parsed=kslex.read(file,'test.js')
            self.assertEqual(parsed.render().encode(parsed.encoding),raw)

    def test_ui_and_state_keys_are_separate(self):
        ex=p.GameExtractor(p.SOURCE);ex.state_values.add('普通')
        line=kslex.Line(1,"f.state='普通'",'\n','text')
        ex._scan_js_span('example.ks',line,'Root',line.text,0,'eval','exp','code')
        us=list(ex.units.values())
        self.assertEqual(len(us),1);self.assertEqual(us[0].kind,'display_value')
        self.assertEqual(us[0].sites[0].start,-1)

    def test_fetch_maps_out_of_order_results_and_records_usage(self):
        with fixture() as tmp:
            folder=Path(tmp)
            units=[Unit(id='a',kind='dialogue',src='一'),Unit(id='b',kind='dialogue',src='二')]
            catalog={'source':'test'}
            manifest={'catalog_fingerprint':p.digest(catalog),'requests':[
                {'custom_id':'ra','unit_ids':['a']},{'custom_id':'rb','unit_ids':['b']}],
                'estimate':{'model':'claude-sonnet-5','cache_ttl':'5m'}}
            p.write_json(folder/'state.json',{'identity':{},'jobs':[{'id':'fake'}]})
            rows=[]
            for rid,word in [('rb','Two'),('ra','One')]:
                row={'custom_id':rid,'result':{'type':'succeeded','message':{
                    'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps({'t':{'0':word}})}],
                    'usage':{'input_tokens':10,'output_tokens':5}}}}
                rows.append(SimpleNamespace(model_dump=lambda mode,row=row:row))
            batches=SimpleNamespace(retrieve=lambda job:SimpleNamespace(processing_status='ended'),results=lambda job:iter(rows))
            api=SimpleNamespace(messages=SimpleNamespace(batches=batches))
            with patch.object(p,'ROOT',folder),patch.object(p,'load_catalog',return_value=(catalog,units)),\
                 patch.object(b,'get_run',return_value=(folder,manifest)),patch.object(b,'client',return_value=(api,{})),\
                 patch.object(b,'config',return_value={'pricing':{'batch_input_per_million':1,'batch_output_per_million':5}}):
                report=b.fetch('fake')
                self.assertEqual(report['accepted_units'],2)
                self.assertEqual(b.store()['translations'],{'b':'Two','a':'One'})
                self.assertEqual(report['usage']['output_tokens'],10)

    def test_ambiguous_submission_is_checkpointed_before_network(self):
        with fixture() as tmp:
            folder=Path(tmp);(folder/'runs').mkdir()
            catalog={'source':'test'};cfg={'submission_budget_usd':20}
            manifest={'catalog_fingerprint':p.digest(catalog),'config_fingerprint':p.digest(cfg),
                      'instructions_fingerprint':p.digest('test'),'phase':'names',
                      'estimate':{'usd':{'planning_budget_with_retry_margin':1}},
                      'requests':[{'custom_id':'r1','unit_ids':['a'],'params':{'model':'claude-sonnet-5'}}]}
            p.write_json(folder/'blockers.json',[])
            def lost_response(**kwargs):
                self.assertTrue(p.read_json(folder/'state.json')['pending'])
                raise TimeoutError('simulated lost response')
            api=SimpleNamespace(messages=SimpleNamespace(batches=SimpleNamespace(create=lost_response)))
            with patch.object(p,'ROOT',folder),patch.object(p,'REPORTS',folder),patch.object(p,'load_catalog',return_value=(catalog,[])),\
                 patch.object(b,'get_run',return_value=(folder,manifest)),patch.object(b,'client',return_value=(api,{})),\
                 patch.object(b,'config',return_value=cfg),patch.object(b,'prefix',return_value='test'):
                with self.assertRaises(TimeoutError):b.submit('fake')
                with self.assertRaisesRegex(ValueError,'uncertain'):b.submit('fake')


if __name__=='__main__':unittest.main()
