"""Ordinary FBIST checks use canonical compilation without unrelated program facts."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import subprocess
import threading
import unittest
from unittest.mock import patch

from gui.server import Session, make_server, MASTER
from program_gen.core import fbist_pattern_plan as fbist
from program_gen.platforms.chroma.fbist_pattern_generator import generate_fbist_patterns as chroma
from program_gen.platforms.s100.fbist_pattern_generator import generate_fbist_patterns as s100
from tests.test_fbist_pattern_plan import make_workbook


class OrdinaryFbistTests(unittest.TestCase):
    def test_ordinary_entry_skips_pump_only_rows_but_preserves_full_validation(self):
        workbook = make_workbook(pattern_rows=[
            {'pattern': 'pump dac', 'description': 'unfinished before ordinary item'},
            {'item': 'Vref', 'pattern': 'trim dac', 'addr': '0000000', 'description': '3,DAC[3:0]=001x'},
            {'item': 'Pump', 'pattern': 'pump dac', 'addr': 'broken', 'description': 'unfinished'},
        ], flow_rows=[{'item': 'Pump', 'PUMP': 'yes'}], version_rows=[{'CLK PIN': 'PA11', 'SWD PIN': 'PA13'}])
        with self.assertRaises(fbist.FbistPatternCompileError):
            fbist.compile_fbist_pattern_plan(workbook, workbook.dataframe('FLOW'))
        narrow = replace(workbook, tables=tuple(t for t in workbook.tables if t.title != 'FLOW'))
        with patch.object(fbist, '_pump_items', side_effect=AssertionError('must not inspect FLOW')):
            plan = fbist.compile_ordinary_fbist_pattern_plan(narrow)
        self.assertFalse(plan.pump_aggregate.writes)
        self.assertEqual(plan.patterns[0].pattern_name, 'set_vref_dac')
        self.assertIn(b'a_data:', chroma(plan).artifacts[0].content)
        self.assertIn(b'a_data_st:', s100(plan).artifacts[0].content)

    def test_required_pin_and_ordinary_field_errors_remain_blocking(self):
        from gui.generation import check_fbist_targets, available_fbist_targets
        target = [available_fbist_targets()[0]['id']]
        for pins, addr, description, source in [
            ({'CLK PIN': '', 'SWD PIN': 'PA13'}, '0000000', '0,BIT=1', 'VERSION'),
            ({'CLK PIN': 'PA11', 'SWD PIN': 'PA13'}, 'wrong', '0,BIT=1', 'pattern'),
            ({'CLK PIN': 'PA11', 'SWD PIN': 'PA13'}, '0000000', '0,BIT=1\n0,OTHER=0', 'pattern'),
        ]:
            workbook = make_workbook(pattern_rows=[{'item': 'Test', 'pattern': 'trim mode', 'addr': addr, 'description': description}],
                                     flow_rows=[], version_rows=[pins])
            diagnostics = check_fbist_targets(workbook, target)
            self.assertTrue(diagnostics)
            self.assertEqual(diagnostics[0]['provenance']['sheet'], source)


class GuiFbistCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = Session()

    def payload(self):
        s = self.session
        target = next(t for t in s.state()['fbistTargets'] if t['platform'] == 'chroma')
        old = s.editor.by_name['FLOW']['rows'][3][1]['value']
        return {'baseSha256': s.editor.sha256, 'changes': [
            {'sheet': 'FLOW', 'cell': 'B4', 'old': old, 'value': 'GUI_Unfinished_FLOW'}],
            'appendRows': [], 'scope': 'fbist', 'targets': [target['id']]}

    def test_check_binds_scope_selection_snapshot_and_ignores_full_compiler(self):
        s = self.session; p = self.payload()
        with patch('gui.server.ProductCompiler.compile', side_effect=AssertionError('no full compile')):
            result = s.check(p)
        self.assertTrue(result['valid'], result)
        self.assertEqual(result['scope'], 'fbist')
        request = {**p, 'checkId': result['checkId']}
        self.assertIsNone(s.checked['compilation'])
        for scope in ('program', 'patterns', 'pin'):
            with self.assertRaises(ValueError):
                s.generate({**request, 'scope': scope})
        with self.assertRaises(ValueError): s.save(request)
        other = next(t['id'] for t in s.state()['fbistTargets'] if t['platform'] == 's100')
        with self.assertRaises(ValueError): s.generate({**request, 'targets': [other]})
        with self.assertRaises(ValueError): s.generate({**request, 'changes': []})

    def test_bad_pattern_reports_real_row_and_clears_success(self):
        s = self.session; p = self.payload()
        self.assertTrue(s.check(p)['valid'])
        old = s.editor.by_name['pattern']['rows'][13][2]['value']
        p['changes'].append({'sheet': 'pattern', 'cell': 'C14', 'old': old, 'value': 'not a field'})
        result = s.check(p)
        self.assertFalse(result['valid']); self.assertIsNone(s.checked)
        self.assertEqual(result['diagnostics'][0]['provenance'], {'sheet': 'pattern', 'coordinate': 'row 14'})

    def test_real_narrow_models_match_full_fbist_and_write_hashed_resources(self):
        from gui.generation import available_fbist_targets, generate_review
        from program_gen.workbook import WorkbookReader, TableModel
        from gui.server import MASTER
        w = WorkbookReader().read(MASTER)
        full = fbist.compile_fbist_pattern_plan(w, w.dataframe('FLOW'))
        names = {'VERSION', 'pattern', 'FB MAP'}
        version = w.dataframe('VERSION')[['CLK PIN', 'SWD PIN']]
        narrow = replace(w, sheets=tuple(s for s in w.sheets if s.title in names),
                         tables=tuple(TableModel.from_dataframe('VERSION', version) if t.title == 'VERSION' else t
                                      for t in w.tables if t.title in names))
        for platform, generator in [('chroma', chroma), ('s100', s100)]:
            expected = {a.relative_path: a.content for a in generator(full).artifacts
                        if a.pattern_name != fbist.AGGREGATE_PATTERN_NAME}
            target = next(t for t in available_fbist_targets() if t['platform'] == platform)
            with tempfile.TemporaryDirectory() as temp:
                parent = Path(temp); run = parent / 'run'; (run / 'input').mkdir(parents=True)
                with patch('gui.generation._RUN_PARENT', parent), patch('gui.generation.build_native_target_plan', side_effect=AssertionError('no full plan')):
                    result = generate_review(narrow, None, [target['id']], run, scope='fbist')
                self.assertEqual(result['status'], 'REVIEW_READY', result)
                output = result['outputs'][0]; root = Path(output['path'])
                manifest = json.loads((root / '.render-manifest.json').read_text())
                actual = {a['path']: (root / a['path']).read_bytes() for a in manifest['artifacts']}
                self.assertEqual(actual, expected)
                for a in manifest['artifacts']:
                    self.assertEqual(hashlib.sha256(actual[a['path']]).hexdigest().upper(), a['sha256'])
                self.assertFalse(result['validation']['vendor_compiler_executed'])

    def test_real_page_http_generation_retry_and_preview(self):
        session = self.session
        original = MASTER.read_bytes()
        with tempfile.TemporaryDirectory(prefix='gui-fbist-') as temp:
            old_output = session.output
            session.output = Path(temp) / 'gui_runs'
            session.job = None
            server = make_server(0, session)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                state = session.state(); state.update(testOrigin=server.origin, testToken=server.token)
                input_path = Path(temp) / 'state.json'; output_path = Path(temp) / 'evidence.json'
                input_path.write_text(json.dumps(state), encoding='utf-8')
                with patch('gui.generation._RUN_PARENT', session.output), patch('gui.server.ProductCompiler.compile', side_effect=AssertionError('no full compiler')):
                    done = subprocess.run(['node', 'tests/test_gui_ui.cjs', str(input_path), str(output_path), 'fbist'],
                                          capture_output=True, text=True, encoding='utf-8', timeout=100)
                self.assertEqual(done.returncode, 0, done.stdout+'\n'+done.stderr)
                evidence = json.loads(output_path.read_text())
                self.assertEqual([x['files'] for x in evidence], [96, 96])
                self.assertEqual(MASTER.read_bytes(), original)
                print('REAL_FBIST_HTTP', json.dumps(evidence)); print(done.stdout.splitlines()[-1])
            finally:
                server.shutdown(); server.server_close(); thread.join()
                session.output = old_output; session.job = None


if __name__ == '__main__':
    unittest.main()
