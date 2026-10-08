"""Live FLOW preview uses the current draft and canonical test bodies."""
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from gui.server import MASTER, Session, make_server


class ItemPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = Session()

    def test_live_draft_recipe_and_append_without_check_or_output(self):
        s = self.session
        payload = dict(baseSha256=s.editor.sha256, changes=[], appendRows=[], row=4, platform='chroma', variant='lab')
        original = MASTER.read_bytes()
        with patch('gui.server.write_new', side_effect=AssertionError('live preview wrote files')):
            baseline = s.item_preview(payload)
            self.assertTrue(baseline['valid'], baseline)
            self.assertEqual(baseline['item'], 'Vref0p8_ABS')
            self.assertIn('double trimTar=0.8;', baseline['text'])
            changed = dict(payload, changes=[dict(sheet='FLOW', cell='S4', old=0.8, value='0.801')])
            self.assertIn('double trimTar=0.801;', s.item_preview(changed)['text'])
            flow = s.editor.by_name['FLOW']
            from openpyxl.utils import get_column_letter
            recipe_col = next(i+1 for i,c in enumerate(flow['columns']) if c['label']=='Recipe')
            enter = next(p['name'] for x in s.links if x['flowRow']==4 for p in x['patterns'] if 'ENTER' in p['uses'])
            recipe = 'ENTER-RUN('+enter+')-TRIM-JUDGE'
            changed['changes'].append(dict(sheet='FLOW',cell=get_column_letter(recipe_col)+'4',old=None,value=recipe))
            with_module = s.item_preview(changed)
            self.assertTrue(with_module['valid'], with_module)
            self.assertIn('RUN', with_module['recipe'])
            self.assertNotEqual(with_module['text'], s.item_preview(dict(payload,changes=changed['changes'][:1]))['text'])
            changed['changes'][-1]['value']='ENTER-UNKNOWN_MODULE-TRIM-JUDGE'
            invalid = s.item_preview(changed)
            self.assertFalse(invalid['valid']); self.assertEqual(invalid['text'],''); self.assertTrue(invalid['diagnostics'])
            appended = dict(payload, row=flow['maxRow']+1,
                            appendRows=[dict(sheet='FLOW',sourceRow=201,copy=True)],
                            changes=[dict(sheet='FLOW',cell='B'+str(flow['maxRow']+1),old='Pvd_Test',value='GUI_Live_Pvd')])
            new_item = s.item_preview(appended)
            self.assertTrue(new_item['valid'],new_item); self.assertIn('Gui_Live_Pvd',new_item['text'])
            self.assertIsNone(s.checked); self.assertIsNone(s.job); self.assertEqual(MASTER.read_bytes(), original)

    def test_real_page_automatic_updates_and_late_guards(self):
        s=self.session
        with TemporaryDirectory() as tmp:
            root=Path(tmp);server=make_server(0,s)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                state=s.state();state.update(testOrigin=server.origin,testToken=server.token)
                source=root/'state.json';evidence=root/'evidence.json';source.write_text(json.dumps(state),encoding='utf-8')
                result=subprocess.run(['node','tests/test_gui_ui.cjs',str(source),str(evidence),'item-preview'],capture_output=True,text=True,encoding='utf-8',timeout=180)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertTrue(evidence.exists());self.assertIsNone(s.job);self.assertIsNone(s.checked)
                print('LIVE_ITEM_HTTP',evidence.read_text(encoding='utf-8'));print(result.stdout.splitlines()[-1])
            finally:
                server.shutdown();server.server_close();thread.join()

    def test_both_platform_bodies_match_full_program_and_cache_does_not_authorize(self):
        from gui.generation import preview_plan
        s=self.session
        payload=dict(baseSha256=s.editor.sha256,changes=[],appendRows=[],row=4,platform='chroma',variant='lab')
        for row in (4,201):
            for platform in ('chroma','s100'):
                from program_gen.platform_program.native_target import build_native_definition_bodies
                bodies=[]
                def capture(*args, **kwargs):
                    result=build_native_definition_bodies(*args, **kwargs);bodies.extend(result);return result
                with patch('gui.item_preview.build_native_definition_bodies',side_effect=capture):
                    result=s.item_preview(dict(payload,row=row,platform=platform))
                self.assertTrue(result['valid'],result)
                cache=s.item_cache
                plan=preview_plan(cache['workbook'],cache['compilation'],result['target'])
                from gui.server import preview_text
                raw=next(a.content for a in plan.artifacts if a.relative_path.endswith(('.pln','.prg')))
                # Compare all bytes, with the same decoding, beyond the viewer's display limit.
                codec=preview_text(raw)['encoding']
                complete=raw.decode(codec)
                # A TRIM definition has several function variants; the complete program
                # may place other functions between them. Compare each actual body.
                for body in bodies:
                    content=body.fragment.content
                    if platform=='s100':
                        from program_gen.core.s100_indent import format_s100
                        content=format_s100(content.decode('latin-1')).encode('latin-1')
                    text=preview_text(content)['text'].rstrip('\r\n')
                    self.assertTrue(text in result['text'],f'preview lost body {body.ref.identity}')
                    self.assertTrue(text in complete,f'full program differs: {platform} row {row} {body.ref.identity}')
        with patch.object(s,'compile',side_effect=AssertionError('manual check must not be used')):
            self.assertTrue(s.item_preview(dict(payload,row=201,platform='s100'))['valid'])
        self.assertIsNone(s.checked)
        for bad in [dict(payload,row=1),dict(payload,row=True),dict(payload,row=9999),
                    dict(payload,platform='unknown'),dict(payload,baseSha256='old')]:
            with self.assertRaises(ValueError):s.item_preview(bad)
        with self.assertRaises(ValueError):s.require_checked(payload)

    def test_http_preview_has_own_lock_and_keeps_existing_check(self):
        s=self.session;server=make_server(0,s)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        def call(token=True):
            headers={'Content-Type':'application/json'}
            if token:headers['X-GUI-Session']=server.token
            return json.load(urlopen(Request(server.origin+'/api/item-preview',data=b'{}',headers=headers),timeout=5))
        try:
            with patch.object(s,'item_preview',return_value={'valid':True,'text':'example'}):
                with server.guard:self.assertEqual(call()['text'],'example')
                with server.preview_guard:
                    with self.assertRaises(HTTPError) as error:call()
                    self.assertEqual(error.exception.code,409)
                with self.assertRaises(HTTPError) as error:call(False)
                self.assertEqual(error.exception.code,403)
            marker=s.checked={'id':'retained'}
            try:
                result=s.item_preview(dict(baseSha256=s.editor.sha256,changes=[],appendRows=[],row=4,platform='chroma'))
                self.assertTrue(result['valid'],result);self.assertIs(s.checked,marker)
            finally:s.checked=None
        finally:
            server.shutdown();server.server_close();worker.join()


if __name__=='__main__': unittest.main()
