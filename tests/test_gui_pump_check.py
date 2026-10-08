"""PUMP-only GUI scope preserves the canonical set_all_final_vposp resource."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from gui import generation
from gui.server import MASTER, Session, make_server
from program_gen.core import fbist_pattern_plan as fbist
from program_gen.platforms.chroma.fbist_pattern_generator import generate_fbist_patterns as chroma
from program_gen.platforms.s100.fbist_pattern_generator import generate_fbist_patterns as s100
from program_gen.workbook import TableModel
from tests.test_fbist_pattern_plan import make_workbook


def fixture(rows=None, flow=None, fills=None):
    return make_workbook(pattern_rows=rows if rows is not None else [
        {'item': 'Pump', 'pattern': 'trim dac', 'addr': '0000001', 'description': '3,DAC[3:0]=001x'}],
        flow_rows=flow if flow is not None else [{'item': 'Pump', 'PUMP': 'yes'}],
        version_rows=[{'CLK PIN': 'PA11', 'SWD PIN': 'PA13'}], pattern_fills=fills)


class PumpPlanTests(unittest.TestCase):
    def test_ignores_unrelated_rows_and_preserves_inheritance_merge_and_labels(self):
        rows=[{'description': 'unfinished before first item'},
              {'item': 'Pump', 'pattern': 'trim mode', 'description': 'unfinished mode'},
              {'pattern': 'trim dac', 'addr': '0000001', 'description': '3,DAC[3:0]=001x\n7,STATIC[3:0]=1111'},
              {'item': 'Other', 'pattern': 'pump dac', 'addr': '0000001', 'description': '7,BIAS[3:0]=1010*'},
              {'item': 'Unselected', 'pattern': 'pump dac', 'description': 'unfinished'},
              {'pattern': 'set_all_final_vposp', 'description': 'obsolete'}]
        w=fixture(rows, [{'item':'PUMP','PUMP':' yes '}, {'item':'Other','PUMP':'YES'}, {'item':'Pump','PUMP':'yes'}])
        with self.assertRaises(fbist.FbistPatternCompileError): fbist.compile_fbist_pattern_plan(w,w.dataframe('FLOW'))
        p=fbist.compile_pump_fbist_pattern_plan(w)
        self.assertFalse(p.patterns);self.assertEqual(len(p.pump_aggregate.writes),1)
        self.assertEqual(p.pump_aggregate.writes[0].data_bits, '0000000010100010')
        self.assertEqual([t.field.label_base for t in p.pump_aggregate.targets],['dac','bias'])
        for renderer in (chroma,s100): self.assertEqual([a.pattern_name for a in renderer(p).artifacts],['set_all_final_vposp'])

    def test_missing_selection_configuration_and_conflicts_are_blocking(self):
        cases=[fixture(flow=[]), fixture(flow=[{'item':'Pump','PUMP':'no'}]),
               fixture(flow=[{'item':'Pump'}]), fixture(flow=[{'item':'','PUMP':'yes'}]),
               fixture(flow=[{'item':'Missing','PUMP':'yes'}]), fixture(fills=['FFFF0000']),
               fixture(rows=[{'item':'Pump','pattern':'pump dac','addr':'bad','description':'3,DAC[3:0]=0000*'}]),
               fixture(rows=[{'item':'Pump','pattern':'pump dac','addr':'0000001','description':'3,DAC[3:0]=0000'}])]
        for w in cases:
            with self.subTest(w=w.identity):
                with self.assertRaises(fbist.FbistPatternCompileError): fbist.compile_pump_fbist_pattern_plan(w)
        for field,addr in [('DAC','0000010'), ('OTHER','0000001')]:
            w=fixture(rows=[{'item':'Pump','pattern':'pump dac','addr':'0000001','description':'3,DAC[3:0]=0000*'},
                            {'addr':addr,'description':f'3,{field}[3:0]=0000*'}])
            with self.assertRaises(fbist.FbistPatternCompileError): fbist.compile_pump_fbist_pattern_plan(w)


class GuiPumpCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session=Session()
        cls.workbook,cls.compilation=cls.session.compile(cls.session.editor.raw)
        cls.compilation.require_success()

    def test_unrelated_errors_and_scoped_credentials_and_missing_item(self):
        s=self.session
        changes=[]
        for sheet,cell,row,col in [('FLOW','S4',4,19),('pattern','C10',10,3)]:
            changes.append({'sheet':sheet,'cell':cell,'old':s.editor.by_name[sheet]['rows'][row-1][col-1]['value'],'value':'unfinished'})
        targets=generation.available_pump_targets()
        p={'baseSha256':s.editor.sha256,'changes':changes,'appendRows':[],'scope':'pump','targets':[targets[0]['id']]}
        self.assertFalse(s.check({**p,'scope':'program'})['valid'])
        with patch('gui.server.ProductCompiler.compile',side_effect=AssertionError('no full compiler')): checked=s.check(p)
        self.assertTrue(checked['valid'],checked);self.assertIsNone(s.checked['compilation'])
        request={**p,'checkId':checked['checkId']}
        for scope in ('program','patterns','pin','fbist','flash','flash_labels'):
            with self.assertRaises(ValueError):s.generate({**request,'scope':scope})
        with self.assertRaises(ValueError):s.save(request)
        with self.assertRaises(ValueError):s.generate({**request,'changes':[]})
        with self.assertRaises(ValueError):s.generate({**request,'targets':[targets[1]['id']]})
        for ids in (None,[],['unknown'],[targets[0]['id']]*2):
            with self.assertRaises(ValueError):generation.check_pump_targets(self.workbook,ids)
        changes.append({'sheet':'FLOW','cell':'B4','old':s.editor.by_name['FLOW']['rows'][3][1]['value'],'value':'MissingPump'})
        failed=s.check(p);self.assertFalse(failed['valid']);self.assertIsNone(s.checked)
        self.assertEqual(failed['diagnostics'][0]['provenance']['sheet'],'FLOW')

    def test_narrow_inputs_match_full_compilation_bytes_and_manifest_on_both_platforms(self):
        names = {'VERSION', 'FLOW', 'FB MAP', 'pattern'}
        version = self.workbook.dataframe('VERSION')[['CLK PIN', 'SWD PIN']]
        narrow = replace(self.workbook, sheets=tuple(s for s in self.workbook.sheets if s.title in names),
                         tables=tuple(TableModel.from_dataframe('VERSION', version) if t.title == 'VERSION' else
                                      TableModel.from_dataframe('FLOW', self.workbook.dataframe('FLOW')[['item', 'PUMP']]) if t.title == 'FLOW' else t
                                      for t in self.workbook.tables if t.title in names))
        for target in generation.available_pump_targets():
            expected = {a.relative_path: a.content for a in ({'chroma': chroma, 's100': s100}[target['platform']])(
                self.compilation.pattern_compilation).artifacts if a.pattern_name == fbist.AGGREGATE_PATTERN_NAME}
            self.assertEqual(generation.check_pump_targets(narrow, [target['id']]), [])
            with tempfile.TemporaryDirectory() as temp:
                parent = Path(temp); run = parent/'run'; (run/'input').mkdir(parents=True)
                with patch('gui.generation._RUN_PARENT', parent), patch('gui.generation.build_native_target_plan', side_effect=AssertionError('no full native plan')):
                    result = generation.generate_review(narrow, None, [target['id']], run, scope='pump')
                self.assertEqual(result['status'], 'REVIEW_READY', result)
                root = Path(result['outputs'][0]['path'])
                manifest = json.loads((root/'.render-manifest.json').read_text())
                actual = {a['path']: (root/a['path']).read_bytes() for a in manifest['artifacts']}
                self.assertEqual(actual, expected); self.assertEqual(len(actual), 1)
                for a in manifest['artifacts']:
                    self.assertEqual(hashlib.sha256(actual[a['path']]).hexdigest().upper(), a['sha256'])
                self.assertFalse(result['validation']['vendor_compiler_executed'])

    def test_real_page_http_generation_retry_and_preview(self):
        s = self.session; old_output = s.output; original = MASTER.read_bytes()
        with tempfile.TemporaryDirectory(prefix='gui-pump-') as temp:
            s.output = Path(temp)/'gui_runs'; s.job = None
            server = make_server(0, s)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                state = s.state(); state.update(testOrigin=server.origin, testToken=server.token)
                input_path = Path(temp)/'state.json'; evidence_path = Path(temp)/'evidence.json'
                input_path.write_text(json.dumps(state), encoding='utf-8')
                with patch('gui.generation._RUN_PARENT', s.output), patch('gui.server.ProductCompiler.compile', side_effect=AssertionError('no full compiler')):
                    done = subprocess.run(['node', 'tests/test_gui_ui.cjs', str(input_path), str(evidence_path), 'pump'],
                                          capture_output=True, text=True, encoding='utf-8', timeout=170)
                self.assertEqual(done.returncode, 0, done.stdout+'\n'+done.stderr)
                evidence = json.loads(evidence_path.read_text())
                self.assertEqual([e['files'] for e in evidence], [1, 1]); self.assertEqual(MASTER.read_bytes(), original)
                print('REAL_PUMP_HTTP', json.dumps(evidence)); print(done.stdout.splitlines()[-1])
            finally:
                server.shutdown(); server.server_close(); thread.join(); s.output = old_output; s.job = None


if __name__ == '__main__': unittest.main()
