"""Pattern-to-FB-MAP edits stay within the ordinary GUI draft boundary."""
from pathlib import Path
import tempfile
import re
import unittest
from unittest.mock import patch

from gui.server import Session
from gui.workbook_editor import WorkbookEditor


class FbMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.session = Session(output=Path(cls.folder.name))

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_real_catalog_repairs_each_hse_bank_en_line_and_preserves_dynamic_value(self):
        from gui.fb_mapping import fb_mapping
        editor = self.session.editor
        for row in (117, 121):
            old = editor.by_name['pattern']['rows'][row - 1][2]['value']
            wrong = re.sub(r'\bBANK_EN\b', 'BANK_SEL', str(old), flags=re.IGNORECASE)
            self.assertNotEqual(wrong, str(old), 'fixture must inject a wrong field name')
            payload = {'baseSha256': editor.sha256,
                       'changes': [{'sheet': 'pattern', 'cell': f'C{row}', 'old': old, 'value': wrong}],
                       'appendRows': [], 'flowOrder': [], 'row': row}
            view = fb_mapping(self.session, payload)
            field = view['fields'][0]
            self.assertEqual(field['status'], 'name_mismatch')
            target = next(t for t in view['targets'] if t['name'] == 'BANK_EN'
                          and t['address'] == '0110011' and (t['high'], t['low']) == (9, 8))
            result = fb_mapping(self.session, {**payload, 'line': field['line'], 'target': target['id']})
            self.assertIn('BANK_EN[1:0]=11', next(c['value'] for c in result['changes']
                                                  if c['sheet'] == 'pattern' and c['cell'] == f'C{row}'))
            raw = editor.apply(editor.sha256, result['changes'])
            reopened = WorkbookEditor(raw, 'repaired.xlsx')
            self.assertIn('BANK_EN[1:0]=11', reopened.by_name['pattern']['rows'][row - 1][2]['value'])

    def test_single_field_target_moves_vector_position_and_keeps_dynamic_marker(self):
        from gui.fb_mapping import fb_mapping
        editor = self.session.editor
        row = 24
        payload = {'baseSha256': editor.sha256, 'changes': [], 'appendRows': [], 'flowOrder': [], 'row': row}
        view = fb_mapping(self.session, payload)
        field = view['fields'][0]
        target = next(t for t in view['targets'] if t['name'] == 'MR_TRIM_VDDK'
                      and t['address'] == '0000010' and (t['high'], t['low']) == (7, 4))
        result = fb_mapping(self.session, {**payload, 'line': field['line'], 'target': target['id']})
        values = {c['cell']: c['value'] for c in result['changes'] if c['sheet'] == 'pattern'}
        self.assertEqual(values[f'B{row}'], '0000010')
        self.assertIn('7,MR_TRIM_VDDK[3:0]=', values[f'C{row}'])
        self.assertTrue(values[f'C{row}'].endswith('*'))
        draft_address = {'sheet': 'pattern', 'cell': f'B{row}',
                         'old': editor.by_name['pattern']['rows'][row - 1][1]['value'], 'value': '0000010'}
        kept = fb_mapping(self.session, {**payload, 'changes': [draft_address],
                                         'line': field['line'], 'target': target['id']})
        self.assertIn(draft_address, kept['changes'])

    def test_rejects_width_overlap_cross_address_and_stale_source(self):
        from gui.fb_mapping import fb_mapping
        editor = self.session.editor
        payload = {'baseSha256': editor.sha256, 'changes': [], 'appendRows': [], 'flowOrder': [], 'row': 117}
        view = fb_mapping(self.session, payload)
        field = view['fields'][0]
        wrong_width = next(t for t in view['targets'] if t['width'] != field['width'])
        with self.assertRaisesRegex(ValueError, '位宽'):
            fb_mapping(self.session, {**payload, 'line': field['line'], 'target': wrong_width['id']})
        other_address = next(t for t in view['targets'] if t['width'] == field['width'] and t['address'] != '0110011')
        with self.assertRaisesRegex(ValueError, '跨地址'):
            fb_mapping(self.session, {**payload, 'line': field['line'], 'target': other_address['id']})
        overlap = {'id': '0110011:7:6:OVERLAP', 'name': 'OVERLAP', 'register': 'fixture',
                   'address': '0110011', 'high': 7, 'low': 6, 'width': 2}
        with patch('gui.fb_mapping._targets', side_effect=lambda index: [*view['targets'], overlap]):
            with self.assertRaisesRegex(ValueError, '重叠'):
                fb_mapping(self.session, {**payload, 'line': field['line'], 'target': overlap['id']})
        with self.assertRaisesRegex(ValueError, '版本不匹配'):
            fb_mapping(self.session, {**payload, 'baseSha256': '0' * 64})


if __name__ == '__main__':
    unittest.main()
