"""Flash resource scope preserves canonical facts, diagnostics and output bytes."""
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
from program_gen.core.flash_compare_product import compile_required_flash_compare_plans, FlashCompareProductCompileError
from program_gen.core.flash_compare_renderer import render_flash_compare_plans
from program_gen.workbook import TableModel


class FlashCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = Session()
        cls.workbook, cls.compilation = cls.session.compile(cls.session.editor.raw)
        cls.compilation.require_success()

    def replace_table(self, name, frame):
        return replace(self.workbook, tables=tuple(TableModel.from_dataframe(name, frame) if t.title == name else t
                                                   for t in self.workbook.tables))

    def payload(self):
        s = self.session
        changes = []
        for sheet, row, col, cell, value in [('FLOW', 4, 2, 'B4', 'GUI_Unfinished_FLOW'),
                                           ('pattern', 14, 3, 'C14', 'unfinished ordinary FBIST')]:
            changes.append({'sheet': sheet, 'cell': cell, 'old': s.editor.by_name[sheet]['rows'][row-1][col-1]['value'], 'value': value})
        return {'baseSha256': s.editor.sha256, 'changes': changes, 'appendRows': [], 'scope': 'flash',
                'targets': [generation.available_flash_targets()[0]['id']]}

    def test_missing_pattern_name_is_not_converted_into_a_literal_filename(self):
        frame = self.workbook.dataframe('NM_pattern'); frame.loc[0, 'Pattern name'] = None
        with self.assertRaisesRegex(FlashCompareProductCompileError, 'NM_pattern row 2'):
            compile_required_flash_compare_plans(self.replace_table('NM_pattern', frame)).require_complete()

    def test_unrelated_errors_do_not_block_and_check_cannot_authorize_other_scopes(self):
        s = self.session; p = self.payload()
        self.assertFalse(s.check({**p, 'scope': 'program'})['valid'])
        with patch('gui.server.ProductCompiler.compile', side_effect=AssertionError('Flash must not compile full program')):
            checked = s.check(p)
        self.assertTrue(checked['valid'], checked); self.assertEqual(checked['scope'], 'flash')
        self.assertIsNone(s.checked['compilation'])
        request = {**p, 'checkId': checked['checkId']}
        for scope in ('pin', 'fbist', 'patterns', 'program'):
            with self.assertRaises(ValueError): s.generate({**request, 'scope': scope})
        with self.assertRaises(ValueError): s.save(request)
        with self.assertRaises(ValueError): s.generate({**request, 'changes': []})
        with self.assertRaises(ValueError): s.generate({**request, 'targets': [generation.available_flash_targets()[1]['id']]})
        columns = s.editor.by_name['NM_pattern']['columns']
        column = next(c['letter'] for c in columns if c['label'] == 'Pattern name')
        index = next(i for i,c in enumerate(columns) if c['label'] == 'Pattern name')
        old = s.editor.by_name['NM_pattern']['rows'][1][index]['value']
        p['changes'].append({'sheet': 'NM_pattern', 'cell': column+'2', 'old': old, 'value': ''})
        failed = s.check(p)
        self.assertFalse(failed['valid']); self.assertIsNone(s.checked)
        self.assertEqual(failed['diagnostics'][0]['provenance'], {'sheet': 'NM_pattern', 'coordinate': 'row 2'})

    def test_required_facts_requests_and_empty_selection_produce_scoped_errors(self):
        target = [generation.available_flash_targets()[0]['id']]
        cases = [('VERSION', 'SWD PIN', '', 'VERSION'), ('VERSION', 'bank', 'invalid', 'VERSION'),
                 ('FLASH_EPR', 'configs', 'invalid_field', 'FLASH_EPR'),
                 ('NM_pattern', 'used', 'sector erase all', 'NM_pattern')]
        for sheet, column, value, source in cases:
            frame = self.workbook.dataframe(sheet)
            row = next(i for i,v in frame[column].items() if v is not None)
            if sheet == 'VERSION': frame[column] = value
            else: frame.loc[row, column] = value
            with self.subTest(sheet=sheet, column=column):
                diagnostics = generation.check_flash_targets(self.replace_table(sheet, frame), target)
                self.assertTrue(diagnostics); self.assertEqual(diagnostics[0]['provenance']['sheet'], source)
        frame = self.workbook.dataframe('NM_pattern').iloc[:0]
        self.assertTrue(generation.check_flash_targets(self.replace_table('NM_pattern', frame), target))
        for ids in (None, [], ['unknown'], target*2):
            with self.assertRaises(ValueError): generation.check_flash_targets(self.workbook, ids)

    def test_narrow_inputs_generate_identical_both_platform_resources_and_manifest(self):
        names = {'VERSION', 'FLASH_EPR', 'FB MAP', 'NM_pattern'}
        version = self.workbook.dataframe('VERSION')[['CLK PIN', 'SWD PIN', 'bank', 'program bit', 'read bit']]
        narrow = replace(self.workbook, sheets=tuple(s for s in self.workbook.sheets if s.title in names),
                         tables=tuple(TableModel.from_dataframe('VERSION', version) if t.title == 'VERSION' else t
                                      for t in self.workbook.tables if t.title in names))
        for target in generation.available_flash_targets():
            expected = {a.relative_path: a.content for a in render_flash_compare_plans(
                self.compilation.flash_compare_compilation.require_complete().plans, target['platform']).artifacts}
            with tempfile.TemporaryDirectory() as temp:
                parent = Path(temp); run = parent/'run'; (run/'input').mkdir(parents=True)
                with patch('gui.generation._RUN_PARENT', parent), patch('gui.generation.build_native_target_plan', side_effect=AssertionError('no full native plan')):
                    result = generation.generate_review(narrow, None, [target['id']], run, scope='flash')
                self.assertEqual(result['status'], 'REVIEW_READY', result)
                root = Path(result['outputs'][0]['path'])
                manifest = json.loads((root/'.render-manifest.json').read_text())
                actual = {a['path']: (root/a['path']).read_bytes() for a in manifest['artifacts']}
                self.assertEqual(actual, expected); self.assertEqual(len(actual), 31)
                for a in manifest['artifacts']:
                    self.assertEqual(hashlib.sha256(actual[a['path']]).hexdigest().upper(), a['sha256'])
                self.assertFalse(result['validation']['vendor_compiler_executed'])

    def test_real_page_http_generation_retry_and_preview(self):
        s = self.session; old_output = s.output
        original = MASTER.read_bytes()
        with tempfile.TemporaryDirectory(prefix='gui-flash-') as temp:
            s.output = Path(temp)/'gui_runs'; s.job = None
            server = make_server(0, s)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                state = s.state(); state.update(testOrigin=server.origin, testToken=server.token)
                input_path = Path(temp)/'state.json'; output_path = Path(temp)/'evidence.json'
                input_path.write_text(json.dumps(state), encoding='utf-8')
                with patch('gui.generation._RUN_PARENT', s.output), patch('gui.server.ProductCompiler.compile', side_effect=AssertionError('no full compiler')):
                    done = subprocess.run(['node','tests/test_gui_ui.cjs',str(input_path),str(output_path),'flash'],
                                          capture_output=True,text=True,encoding='utf-8',timeout=170)
                self.assertEqual(done.returncode,0,done.stdout+'\n'+done.stderr)
                evidence=json.loads(output_path.read_text()); self.assertEqual([e['files'] for e in evidence],[31,31])
                self.assertEqual(MASTER.read_bytes(),original)
                print('REAL_FLASH_HTTP',json.dumps(evidence));print(done.stdout.splitlines()[-1])
            finally:
                server.shutdown();server.server_close();thread.join();s.output=old_output;s.job=None


if __name__ == '__main__': unittest.main()
