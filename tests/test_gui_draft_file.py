"""Unchecked draft copies retain OOXML protections and grant no generation permission."""
from copy import copy
from io import BytesIO
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from gui.server import Session, MASTER, make_server
from gui.workbook_editor import WorkbookEditor, sha


class DraftFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.editor = WorkbookEditor(MASTER.read_bytes(), MASTER.name, MASTER)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='gui-draft-file-')
        self.addCleanup(self.temp.cleanup)
        self.session = Session.__new__(Session)
        self.session.output = Path(self.temp.name) / 'outputs'
        self.session.editor = self.editor
        self.session.checked = self.session.job = None

    def payload(self):
        e = self.editor
        return {'baseSha256': e.sha256, 'changes': [
            {'sheet': 'FLOW', 'cell': 'B4', 'old': e.by_name['FLOW']['rows'][3][1]['value'], 'value': 'Unfinished_Draft_Item'}],
            'appendRows': []}

    def test_unfinished_copy_roundtrips_appends_and_preserves_other_xml(self):
        s = self.session; p = self.payload()
        last = self.editor.by_name['FLOW']['maxRow'] + 1
        p['appendRows'] = [{'sheet': 'FLOW', 'sourceRow': 4, 'copy': False}]
        p['changes'].append({'sheet': 'FLOW', 'cell': f'B{last}', 'old': None, 'value': 'Draft_New_Row'})
        with patch('gui.server.ProductCompiler.compile', side_effect=AssertionError('saving draft must not compile')):
            result = s.save_draft(p)
        path = Path(result['path']); raw = path.read_bytes()
        self.assertTrue(path.name.startswith('DRAFT_UNCHECKED_'))
        self.assertEqual(result['validation'], 'NOT_CHECKED')
        self.assertEqual(result['sha256'], sha(raw)); self.assertNotIn('checkId', result)
        self.assertIsNone(s.checked)
        with self.assertRaises(ValueError): s.generate({**p, 'checkId': result.get('checkId')})
        with self.assertRaises(ValueError): s.save(p)
        with ZipFile(BytesIO(self.editor.raw)) as old, ZipFile(BytesIO(raw)) as new:
            self.assertEqual(old.namelist(), new.namelist())
            self.assertEqual({name for name in old.namelist() if old.read(name) != new.read(name)},
                             {self.editor.sheet_paths['FLOW']})
        state = s.load(raw, path.name, path)
        self.assertEqual(s.editor.by_name['FLOW']['rows'][3][1]['value'], 'Unfinished_Draft_Item')
        self.assertEqual(s.editor.by_name['FLOW']['rows'][last-1][1]['value'], 'Draft_New_Row')
        self.assertEqual(state['targets'], [])
        self.assertEqual(MASTER.read_bytes(), self.editor.raw)

    def test_repeat_reuses_copy_but_never_overwrites_modified_output(self):
        s = self.session; p = self.payload()
        first = s.save_draft(p); self.assertEqual(s.save_draft(p), first)
        self.assertEqual(len(list((s.output / 'drafts').glob('*.xlsx'))), 1)
        Path(first['path']).write_bytes(b'external change')
        with self.assertRaisesRegex(ValueError, '已存在|修改|冲突'): s.save_draft(p)
        self.assertEqual(Path(first['path']).read_bytes(), b'external change')

    def test_long_names_and_repeated_draft_names_keep_xlsx_suffix(self):
        s = self.session; s.editor = copy(self.editor)
        s.editor.name = 'long_name_' * 20 + '.xlsx'
        first = s.save_draft(self.payload())
        self.assertTrue(first['path'].endswith('.xlsx'))
        s.editor.name = Path(first['path']).name
        self.assertEqual(s.save_draft(self.payload())['path'], first['path'])

    def test_old_value_formula_source_and_io_errors_do_not_authorize_or_write(self):
        s = self.session; p = self.payload()
        bad = [
            {**p, 'baseSha256': 'stale'},
            {**p, 'changes': [{**p['changes'][0], 'old': 'stale'}]},
            {**p, 'changes': [{**p['changes'][0], 'value': '=1+1'}]},
            {**p, 'changes': [{'sheet': 'FLOW', 'cell': 'B1', 'old': 'item', 'value': 'x'}]},
            {**p, 'appendRows': 'wrong'},
        ]
        protected = self.editor.by_name['PIN DEC']['rows'][1][2]
        bad.append({**p, 'changes': [{'sheet': 'PIN DEC', 'cell': 'C2', 'old': protected['value'], 'value': '1'}]})
        for payload in bad:
            with self.subTest(payload=payload), self.assertRaises(ValueError): s.save_draft(payload)
        self.assertFalse(s.output.exists())
        with patch('gui.server.write_new', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): s.save_draft(p)
        source = Path(self.temp.name) / 'source.xlsx'; source.write_bytes(b'changed source')
        s.editor = copy(self.editor); s.editor.source_path = source
        with self.assertRaisesRegex(ValueError, '母本已变化'): s.save_draft(p)
        self.assertIsNone(s.checked); self.assertFalse(s.output.exists())

    def test_actual_page_http_save_retry_and_reload(self):
        s = self.session
        s.load(self.editor.raw, self.editor.name)
        server = make_server(0, s)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            state = s.state(); state.update(testOrigin=server.origin, testToken=server.token)
            root = Path(self.temp.name); state_file = root / 'state.json'; evidence_file = root / 'evidence.json'
            state_file.write_text(json.dumps(state), encoding='utf-8')
            with patch('gui.server.ProductCompiler.compile', side_effect=AssertionError('draft save must not compile')):
                done = subprocess.run(['node', 'tests/test_gui_ui.cjs', str(state_file), str(evidence_file), 'draft-file'],
                                      capture_output=True, text=True, encoding='utf-8', timeout=60)
            self.assertEqual(done.returncode, 0, done.stdout+'\n'+done.stderr)
            evidence = json.loads(evidence_file.read_text())
            raw = Path(evidence['path']).read_bytes()
            s.load(raw, Path(evidence['path']).name)
            self.assertEqual(s.editor.by_name['FLOW']['rows'][3][1]['value'], 'GUI_Unfinished_Draft')
            self.assertIsNone(s.checked); self.assertEqual(MASTER.read_bytes(), self.editor.raw)
            print('REAL_DRAFT_FILE_HTTP', evidence['validation'], evidence['sha256'])
            print(done.stdout.splitlines()[-1])
        finally:
            server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    unittest.main()
