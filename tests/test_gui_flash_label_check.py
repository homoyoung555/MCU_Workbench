"""Independent page/UID resources use the canonical plans and output contract."""
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
from program_gen.core.addr_map import compile_addr_map_catalog, catalog_for_cp
from program_gen.core.flash_compare_product import compile_flash_compare_facts
from program_gen.core.flash_label_plan import compile_flash_label_plan, FlashLabelCompileError
from program_gen.core.flash_label_renderer import render_flash_label_plan
from program_gen.workbook import TableModel


class FlashLabelCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = Session()
        cls.workbook, cls.compilation = cls.session.compile(cls.session.editor.raw)
        cls.compilation.require_success()

    def replace_table(self, name, frame):
        return replace(self.workbook, tables=tuple(TableModel.from_dataframe(name, frame) if t.title == name else t
                                                   for t in self.workbook.tables))

    def test_unfinished_other_sheets_do_not_block_and_credentials_stay_scoped(self):
        s = self.session
        changes = []
        for sheet, column, value in [('FLOW', 'item', 'GUI_Unfinished_FLOW'),
                                     ('NM_pattern', 'Pattern name', ''),
                                     ('pattern', 'description', 'unfinished FBIST')]:
            info = s.editor.by_name[sheet]
            index, col = next((i, c) for i, c in enumerate(info['columns']) if c['label'] == column)
            row = 4 if sheet == 'FLOW' else 14 if sheet == 'pattern' else 2
            changes.append({'sheet': sheet, 'cell': col['letter']+str(row),
                            'old': info['rows'][row-1][index]['value'], 'value': value})
        targets = generation.available_flash_label_targets()
        p = {'baseSha256': s.editor.sha256, 'changes': changes, 'appendRows': [],
             'scope': 'flash_labels', 'targets': [targets[0]['id']]}
        self.assertFalse(s.check({**p, 'scope': 'program'})['valid'])
        with patch('gui.server.ProductCompiler.compile', side_effect=AssertionError('no full compiler')):
            checked = s.check(p)
        self.assertTrue(checked['valid'], checked)
        self.assertEqual(checked['scope'], 'flash_labels'); self.assertIsNone(s.checked['compilation'])
        request = {**p, 'checkId': checked['checkId']}
        for scope in ('program', 'patterns', 'pin', 'fbist', 'flash'):
            with self.assertRaises(ValueError): s.generate({**request, 'scope': scope})
        with self.assertRaises(ValueError): s.save(request)
        with self.assertRaises(ValueError): s.generate({**request, 'changes': []})
        with self.assertRaises(ValueError): s.generate({**request, 'targets': [targets[1]['id']]})
        with self.assertRaises(ValueError): s.check({**p, 'targets': []})
        self.assertIsNone(s.checked)

    def test_required_hardware_and_page_images_report_the_responsible_sheet(self):
        ids = [generation.available_flash_label_targets()[0]['id']]
        for name, column, value in [('VERSION', 'SWD PIN', ''), ('FLASH_EPR', 'configs', 'invalid_field'),
                                    ('ADDR_MAP', 'SM Address', ''), ('ADDR_MAP', 'CP Data[31:0]', 'invalid')]:
            frame = self.workbook.dataframe(name)
            frame[column] = value
            with self.subTest(name=name, column=column):
                errors = generation.check_flash_label_targets(self.replace_table(name, frame), ids)
                self.assertTrue(errors)
                self.assertEqual(errors[0]['provenance']['sheet'], name)
        frame = self.workbook.dataframe('ADDR_MAP')
        for broken in (frame.iloc[1:], frame[frame['Word No.'].str.casefold() != 'uid'],
                       frame.drop(columns=['CP addr map'])):
            errors = generation.check_flash_label_targets(self.replace_table('ADDR_MAP', broken), ids)
            self.assertTrue(errors); self.assertEqual(errors[0]['provenance']['sheet'], 'ADDR_MAP')
        for targets in (None, [], ['unknown'], ids*2):
            with self.assertRaises(ValueError): generation.check_flash_label_targets(self.workbook, targets)

    def test_narrow_inputs_match_full_compilation_bytes_and_manifest_on_both_platforms(self):
        names = {'VERSION', 'FLASH_EPR', 'FB MAP', 'ADDR_MAP'}
        version = self.workbook.dataframe('VERSION')[['CLK PIN', 'SWD PIN', 'bank', 'program bit', 'read bit']]
        narrow = replace(self.workbook, sheets=tuple(s for s in self.workbook.sheets if s.title in names),
                         tables=tuple(TableModel.from_dataframe('VERSION', version) if t.title == 'VERSION' else t
                                      for t in self.workbook.tables if t.title in names))
        for target in generation.available_flash_label_targets():
            expected = {a.relative_path: a.content for a in render_flash_label_plan(
                self.compilation.flash_label_plan, target['platform']).artifacts}
            self.assertEqual(generation.check_flash_label_targets(narrow, [target['id']]), [])
            with tempfile.TemporaryDirectory() as temp:
                parent = Path(temp); run = parent/'run'; (run/'input').mkdir(parents=True)
                with patch('gui.generation._RUN_PARENT', parent), patch('gui.generation.build_native_target_plan', side_effect=AssertionError('no full native plan')):
                    result = generation.generate_review(narrow, None, [target['id']], run, scope='flash_labels')
                self.assertEqual(result['status'], 'REVIEW_READY', result)
                root = Path(result['outputs'][0]['path'])
                manifest = json.loads((root/'.render-manifest.json').read_text())
                actual = {a['path']: (root/a['path']).read_bytes() for a in manifest['artifacts']}
                self.assertEqual(actual, expected); self.assertEqual(len(actual), 33)
                for a in manifest['artifacts']:
                    self.assertEqual(hashlib.sha256(actual[a['path']]).hexdigest().upper(), a['sha256'])
                self.assertFalse(result['validation']['vendor_compiler_executed'])

    def test_incomplete_page_addresses_do_not_silently_drop_a_page(self):
        facts = compile_flash_compare_facts(self.workbook)
        for page, value, whole_page in [('trim0', 'invalid', True), ('FT', '', True),
                                         ('option0', '', False), ('trim1', 'RA=0', False)]:
            frame = self.workbook.dataframe('ADDR_MAP')
            indices = frame.index[frame['Word No.'] == page]
            frame.loc[indices if whole_page else indices[:1], 'SM Address'] = value
            with self.subTest(page=page, value=value):
                catalog = compile_addr_map_catalog(frame)
                # Register-only consumers may still use a partial storage mapping.
                self.assertTrue(catalog.registers)
                self.assertEqual(catalog_for_cp(catalog, 'CP1').incomplete_storage_pages, catalog.incomplete_storage_pages)
                with self.assertRaisesRegex(FlashLabelCompileError, 'ADDR_MAP.*'+page):
                    compile_flash_label_plan(catalog, facts)
                errors = generation.check_flash_label_targets(self.replace_table('ADDR_MAP', frame),
                                                              [generation.available_flash_label_targets()[0]['id']])
                self.assertTrue(errors); self.assertEqual(errors[0]['provenance']['sheet'], 'ADDR_MAP')

    def test_real_page_http_generation_retry_and_preview(self):
        s = self.session; old_output = s.output; original = MASTER.read_bytes()
        with tempfile.TemporaryDirectory(prefix='gui-label-') as temp:
            s.output = Path(temp)/'gui_runs'; s.job = None
            server = make_server(0, s)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                state = s.state(); state.update(testOrigin=server.origin, testToken=server.token)
                input_path = Path(temp)/'state.json'; evidence_path = Path(temp)/'evidence.json'
                input_path.write_text(json.dumps(state), encoding='utf-8')
                with patch('gui.generation._RUN_PARENT', s.output), patch('gui.server.ProductCompiler.compile', side_effect=AssertionError('no full compiler')):
                    done = subprocess.run(['node', 'tests/test_gui_ui.cjs', str(input_path), str(evidence_path), 'flash_labels'],
                                          capture_output=True, text=True, encoding='utf-8', timeout=170)
                self.assertEqual(done.returncode, 0, done.stdout+'\n'+done.stderr)
                evidence = json.loads(evidence_path.read_text())
                self.assertEqual([e['files'] for e in evidence], [33, 33]); self.assertEqual(MASTER.read_bytes(), original)
                print('REAL_FLASH_LABEL_HTTP', json.dumps(evidence)); print(done.stdout.splitlines()[-1])
            finally:
                server.shutdown(); server.server_close(); thread.join(); s.output = old_output; s.job = None


if __name__ == '__main__': unittest.main()
