"""Mapping edits survive the same protected draft/check/save boundary as cells."""
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from gui.server import MASTER, Session, fingerprint
from gui.workbook_editor import WorkbookEditor


class StorageMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.editor = WorkbookEditor(MASTER.read_bytes(), MASTER.name)

    def test_mapping_only_draft_roundtrip_and_clear_preserve_all_existing_parts(self):
        mapping = {'item': 'VREF0P8_TC', 'targets': [{'page': 'trim1',
                   'register': 'PMU_TRIM0', 'field': 'BG_TC_TRIM_VDDK'}]}
        editor = self.editor
        raw = editor.apply(editor.sha256, [], trim_storage_mappings=[mapping])
        reloaded = WorkbookEditor(raw, 'mapped.xlsx')
        self.assertEqual(reloaded.trim_storage_mappings, [mapping])
        import json
        with ZipFile(BytesIO(raw)) as archive:
            self.assertEqual(json.loads(archive.read('mcu/mappings.json'))['version'], 3)
        with ZipFile(BytesIO(editor.raw)) as old, ZipFile(BytesIO(raw)) as new:
            for name in old.namelist():
                self.assertEqual(old.read(name), new.read(name), name)
        cleared = reloaded.apply(reloaded.sha256, [], trim_storage_mappings=[])
        self.assertEqual(WorkbookEditor(cleared, 'cleared.xlsx').trim_storage_mappings, [])
        self.assertEqual(reloaded.apply(reloaded.sha256, []), raw)

    def test_verify_empty_override_roundtrip_is_separate_from_trim(self):
        editor = self.editor
        verify = [{'item': 'Vrefint', 'targets': []}]
        raw = editor.apply(editor.sha256, [], verify_storage_mappings=verify)
        reloaded = WorkbookEditor(raw, 'verify.xlsx')
        self.assertEqual(reloaded.verify_storage_mappings, verify)
        self.assertEqual(reloaded.trim_storage_mappings, [])
        self.assertNotEqual(fingerprint({'changes': []}), fingerprint({'changes': [], 'verifyStorageMappings': verify}))

    def test_old_mapping_alias_resolves_to_description_at_same_physical_interval(self):
        from program_gen.core.addr_map import compile_addr_map_catalog
        from program_gen.core.project_mappings import StorageMapping, StorageTarget
        from program_gen.workbook import WorkbookReader
        workbook = WorkbookReader().read(MASTER)
        catalog = compile_addr_map_catalog(workbook.dataframe('ADDR_MAP'), (
            StorageMapping('VREF0P8_TC', (StorageTarget('trim1', 'PMU_TRIM0', 'VREF0P8_TC'),)),
        ))
        field = catalog.selected_storage_fields('trim', 'VREF0P8_TC')[0]
        self.assertEqual((field.name, field.lsb, field.width), ('BG_TC_TRIM_VDDK', 0, 5))
        uid = catalog.resolve_storage_field('uid', 'Hsi_8M_Trim', 'Hsi_8M')
        self.assertEqual(catalog.resolve_fields(catalog.storage_field_reference(uid, exact=True)), (uid,))

    def test_mapping_changes_invalidate_check_fingerprint(self):
        p = {'baseSha256': self.editor.sha256, 'changes': []}
        self.assertNotEqual(fingerprint(p), fingerprint({**p, 'trimStorageMappings': [
            {'item': 'A', 'page': 'trim1', 'register': 'REG_A', 'field': 'F'}]}))

    def test_hsi_shared_mapping_includes_trim_and_uid_copies_for_cp1_and_cp3(self):
        with tempfile.TemporaryDirectory() as folder:
            session = Session(output=Path(folder))
            payload = {'baseSha256': session.editor.sha256, 'changes': [], 'row': 12,
                       'trimStorageMappings': []}
            prepared = session.storage_mapping(payload)
            self.assertEqual(prepared['item'], 'Hsi_8M')
            self.assertEqual(set(prepared['cps']), {'CP1', 'CP3'})
            targets = [
                {'page': 'trim1', 'register': 'CLK_TRIM0', 'field': 'HSI_ABS_TRIMCR_VDDK'},
                {'page': 'uid', 'register': 'Hsi_8M_Trim', 'field': 'Hsi_8M'},
            ]
            for target in targets:
                self.assertIn(target, prepared['current'])
                self.assertTrue(any(all(o[k] == v for k, v in target.items())
                                    for o in prepared['options']))
            candidate = session.storage_mapping({**payload, 'targets': targets})
            self.assertTrue(candidate['valid'], candidate.get('diagnostics'))
            preview=next(x for x in candidate['links'] if x['flowRow']==12)
            self.assertCountEqual([d['storageMapping'] for d in preview['details'] if d.get('storageMapping')],targets)
            other_cp = session.storage_mapping({**payload, 'row': 179,
                                                'trimStorageMappings': candidate['trimStorageMappings']})
            self.assertCountEqual(other_cp['current'], targets)
            self.assertEqual(other_cp['cp'], 'CP3')
            reset = session.storage_mapping({**payload, 'row': 179, 'targets': None,
                                             'trimStorageMappings': candidate['trimStorageMappings']})
            self.assertTrue(reset['valid'], reset.get('diagnostics'))
            self.assertEqual(reset['trimStorageMappings'], [])

    def test_verify_field_click_uses_measurement_export_and_explicit_unlink(self):
        with tempfile.TemporaryDirectory() as folder:
            session = Session(output=Path(folder))
            payload = {'baseSha256': session.editor.sha256, 'changes': [], 'row': 38,
                       'trimStorageMappings': [], 'verifyStorageMappings': []}
            view = session.storage_mapping(payload)
            self.assertEqual(view['kind'], 'VERIFY')
            self.assertEqual(view['symbol'], 'VREFINT_EXPORT')
            self.assertEqual(len(view['current']), 1)
            def assert_preview(links, expected):
                item = next(x for x in links if x['flowRow'] == 38)
                mapped = [d for d in item['details'] if d.get('storageMapping')]
                self.assertEqual([d['storageMapping'] for d in mapped], expected)
                for detail in mapped:
                    self.assertIn('已配置', detail['text'])
                    self.assertTrue(any(l['sheet'] == 'ADDR_MAP' for l in detail['locations']))
            assert_preview(session.links, view['current'])
            cp2 = next(x for x in session.links if x['flowRow'] == 108)
            self.assertFalse(any(d.get('storageMapping') for d in cp2['details']))
            self.assertTrue(any('未启用' in d.get('summary','') for d in cp2['details']))
            cp1 = next(x for x in session.links if x['flowRow'] == 38)
            self.assertTrue(any('COMMIT' in d.get('summary','') for d in cp1['details']))
            result = session.storage_mapping({**payload, 'targets': view['current']})
            self.assertTrue(result['valid'], result['diagnostics'])
            assert_preview(result['links'], view['current'])
            self.assertEqual(result['trimStorageMappings'], [])
            mapped = {**payload, 'verifyStorageMappings': result['verifyStorageMappings']}
            with self.assertRaisesRegex(ValueError, '测量结果格式'):
                session.storage_mapping({**mapped, 'row': 108})
            removed = session.storage_mapping({**mapped, 'targets': []})
            self.assertTrue(removed['valid'], removed['diagnostics'])
            assert_preview(removed['links'], [])
            self.assertEqual(removed['current'], [])
            self.assertEqual(removed['verifyStorageMappings'], [{'item': 'Vrefint', 'targets': []}])
            raw = session.editor.apply(session.editor.sha256, [], verify_storage_mappings=removed['verifyStorageMappings'])
            self.assertEqual(WorkbookEditor(raw, 'verify-unlinked.xlsx').verify_storage_mappings, removed['verifyStorageMappings'])
            # The actual persistence plan consumes the exported measurement, never DAC_FINAL.
            candidate = session.storage_mapping({**payload, 'targets': view['current']})
            compiled = session.item_cache['compilation']
            writes = [w for plan in compiled.plan.catalogs.persistence.rows.values()
                      for operation in plan.operations if operation.module == 'COMMIT'
                      for w in operation.field_writes if w.value.token == 'VREFINT_EXPORT']
            self.assertTrue(writes)
            conflict = {'page': 'uid', 'register': 'Vrefbuf1p024_Verify', 'field': 'Vrefbuf1p024_Verify'}
            rejected = session.storage_mapping({**payload, 'targets': [conflict]})
            self.assertFalse(rejected['valid'])
            self.assertTrue(any('重叠' in d['message'] for d in rejected['diagnostics']))

    def test_real_prepare_apply_save_reload_and_reject_stale_mapping(self):
        with tempfile.TemporaryDirectory() as folder:
            session = Session(output=Path(folder))
            payload = {'baseSha256': session.editor.sha256, 'changes': [], 'row': 3,
                       'trimStorageMappings': []}
            options = session.storage_mapping(payload)
            self.assertEqual(options['item'], 'VREF0P8_TC')
            current = options['current'][0]
            self.assertEqual(current['register'], 'PMU_TRIM0')
            destination = {'page': 'trim0', 'register': 'FLASH_OP7', 'field': 'IDAC_LP'}
            before = session.item_cache
            result = session.storage_mapping({**payload, 'targets': [current, destination]})
            self.assertTrue(result['valid'], result.get('diagnostics'))
            self.assertIsNone(session.checked)
            self.assertEqual(len(result['trimStorageMappings']), 1)
            self.assertEqual(len(result['trimStorageMappings'][0]['targets']), 2)
            self.assertTrue(all('cp' not in m for m in result['trimStorageMappings']))
            mapped = {**payload, 'trimStorageMappings': result['trimStorageMappings']}
            checked = session.check(mapped)
            self.assertTrue(checked['valid'], checked['diagnostics'])
            details = next(link for link in checked['links'] if link['flowRow'] == 3)['details']
            text = '\n'.join(d['text'] for d in details)
            self.assertIn('FLASH_OP7[7:3]', text)
            self.assertIn('PMU_TRIM0[4:0]', text)
            self.assertTrue(any(loc['coordinate'].endswith('273') for d in details for loc in d['locations']))
            from gui.generation import preview_plan
            for platform in ('chroma', 's100'):
                target = next(t['id'] for t in session.targets if t['platform'] == platform
                              and t['cp'] == 'CP1' and t['variant'] == 'lab')
                old = preview_plan(before['workbook'], before['compilation'], target, 'program')
                new = preview_plan(session.checked['workbook'], session.checked['compilation'], target, 'program')
                old_files = {a.relative_path: a.content for a in old.artifacts}
                changed = [a.relative_path for a in new.artifacts if old_files[a.relative_path] != a.content]
                self.assertTrue(changed)
                self.assertTrue(all(Path(p).suffix in ('.pln', '.prg') for p in changed), changed)
                print('MAPPING_GENERATION_DELTA', platform, changed)
            with self.assertRaises(ValueError):
                session.save({**payload, 'checkId': checked['checkId']})
            saved = session.save({**mapped, 'checkId': checked['checkId']})
            state = session.load(Path(saved['path']).read_bytes(), 'mapped.xlsx')
            self.assertEqual(state['trimStorageMappings'], result['trimStorageMappings'])
            with self.assertRaises(ValueError):
                session.storage_mapping(payload)


if __name__ == '__main__':
    unittest.main()
