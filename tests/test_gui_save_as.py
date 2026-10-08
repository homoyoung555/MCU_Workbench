"""Native Save As preserves workbook bytes and Link identity at the chosen path."""
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest
import openpyxl
from gui.desktop import DesktopBridge
from gui.server import Session, fingerprint
from gui.workbook_editor import WorkbookEditor, sha
from gui.swd_workspace import SwdWorkspace
from program_gen.core.pattern_links import read_pattern_links

class SaveAsTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        book = openpyxl.Workbook(); book.active.title = 'FLOW'
        book.active.append(['CP NO', 'item']); book.active.append(['CP3', 'ADC'])
        raw = BytesIO(); book.save(raw); book.close()
        self.source = self.root / 'source.xlsx'; self.source.write_bytes(raw.getvalue())
        self.session = Session.__new__(Session)
        self.session.output = self.root / 'outputs'
        self.session.editor = WorkbookEditor(raw.getvalue(), 'source.xlsx', self.source)
        self.session.checked = self.session.job = None
        self.session.swd = SwdWorkspace(self.session)
        self.binding = {'target': {'id':'target'}, 'swdSource': {'documentId':'steps','pattern':'ADC_V03'}}
        self.session.swd.data['links'][self.session.editor.sha256] = [self.binding]
        self.record = dict(cp='CP3',item='ADC',phase='ADC1',role='config',platform='shared',original='ADC_Old',pattern='ADC_V03')
        self.payload = dict(baseSha256=self.session.editor.sha256, changes=[], patternLinks=[self.record])
        self.window = SimpleNamespace(create_file_dialog=Mock(return_value=None))
        self.bridge = DesktopBridge(None, self.window, lambda: self.session)
        self.module = patch.dict('sys.modules', {'webview':SimpleNamespace(FileDialog=SimpleNamespace(SAVE=30))})
        self.module.start(); self.addCleanup(self.module.stop)

    def test_cancel_creates_no_copy_or_link_record(self):
        self.assertEqual(self.bridge.save_workbook(self.payload, False), {'cancelled':True})
        self.assertFalse(self.session.output.exists())
        self.assertEqual(len(self.session.swd.data['links']),1)

    def test_chosen_path_roundtrips_json_and_link_fingerprint_for_both_modes(self):
        for checked in (False, True):
            with self.subTest(checked=checked):
                destination = self.root / ('checked.xlsx' if checked else 'chosen draft.xlsx')
                destination.write_bytes(b'previous confirmed overwrite')
                self.window.create_file_dialog.return_value = (str(destination),)
                if checked:
                    raw = self.session.editor.apply(self.payload['baseSha256'], [], pattern_links=[self.record])
                    self.session.checked = dict(id='checked',scope='program',fingerprint=fingerprint(self.payload),raw=raw,saved=None)
                    self.payload['checkId'] = 'checked'
                result = self.bridge.save_workbook(self.payload, checked)
                self.assertEqual(result['path'], str(destination.resolve()))
                self.assertEqual(read_pattern_links(destination.read_bytes()), [self.record])
                digest = sha(destination.read_bytes())
                self.assertEqual(self.session.swd.data['links'][digest], [self.binding])
                self.assertEqual(self.source.read_bytes(), self.session.editor.raw)
                self.assertEqual(result['sha256'], digest)
                if not checked: self.assertEqual(result['validation'], 'NOT_CHECKED')

    def test_failed_replace_preserves_existing_destination_and_cleans_temp(self):
        destination = self.root / 'chosen.xlsx'; destination.write_bytes(b'keep')
        self.window.create_file_dialog.return_value = (str(destination),)
        with patch('gui.desktop.os.replace', side_effect=PermissionError('file in use')):
            with self.assertRaises(PermissionError): self.bridge.save_workbook(self.payload, False)
        self.assertEqual(destination.read_bytes(), b'keep')
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['chosen.xlsx','outputs','source.xlsx'])

    def test_source_and_changed_workbook_are_not_overwritten(self):
        self.window.create_file_dialog.return_value = (str(self.source),)
        with self.assertRaisesRegex(ValueError, '源文件'): self.bridge.save_workbook(self.payload, False)
        def changed(*args, **kwargs):
            self.session.editor = None
            return (str(self.root/'changed.xlsx'),)
        self.window.create_file_dialog.side_effect = changed
        with self.assertRaisesRegex(ValueError, '工作簿'): self.bridge.save_workbook(self.payload, False)
        self.assertFalse((self.root/'changed.xlsx').exists())

if __name__ == '__main__': unittest.main()
