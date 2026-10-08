"""Row-scoped Pattern choices use the existing Recipe draft/save boundary."""
from pathlib import Path
import tempfile
import unittest

from gui.server import Session
from gui.workbook_editor import WorkbookEditor


class TrimPatternTests(unittest.TestCase):
    def test_verify_mapping_select_reset_and_compile(self):
        session = self.session
        payload = {'baseSha256': session.editor.sha256, 'changes': [], 'row': 37}
        view = session.trim_pattern(payload)
        enter = next(u for u in view['uses'] if u['module'] == 'ENTER')
        self.assertEqual(enter['current'], 'enter_vref0p8_abs_verify')
        self.assertNotIn('TRIM', [u['module'] for u in view['uses']])
        names = [o['name'] for o in enter['options']]
        self.assertNotIn('enter_hsi_8m', names)
        selected = next(name for name in names if name != enter['current'])
        result = session.trim_pattern({**payload, 'step': enter['step'], 'pattern': selected})
        self.assertIn('PATTERN=' + selected, result['change']['value'])
        raw = session.editor.apply(session.editor.sha256, [result['change']])
        _, compiled = session.compile(raw)
        self.assertTrue(compiled.is_valid, [d.message for d in compiled.diagnostics.errors])
        plan = compiled.plan.catalogs.standard_verify_plans[35]
        self.assertEqual(next(s.module_plan for s in plan.steps if s.module == 'ENTER').pattern.name, selected)
        restored = session.trim_pattern({**payload, 'changes': [result['change']], 'step': enter['step'], 'pattern': None})
        self.assertNotIn('PATTERN=', restored['change']['value'])
        self.assertEqual(restored['uses'][0]['current'], enter['current'])

    def test_verify_mapping_preserves_uid_export_and_explicit_step_parameters(self):
        from flow_recipe import parse_recipe
        session = self.session
        sheet = session.editor.by_name['FLOW']
        uid = next(i for i, c in enumerate(sheet['columns']) if c['label'] == 'UID')
        row = next(i + 1 for i, cells in enumerate(sheet['rows'])
                   if str(cells[4]['value']).lower() == 'verify'
                   and str(cells[uid]['value']).lower() == 'yes'
                   and not cells[5]['value'])
        payload = {'baseSha256': session.editor.sha256, 'changes': [], 'row': row}
        view = session.trim_pattern(payload)
        self.assertEqual([c.name for c in parse_recipe(view['recipeText'])], ['ENTER', 'JUDGE', 'EXPORT'])
        selected = view['uses'][0]['options'][0]['name']
        result = session.trim_pattern({**payload, 'step': 0, 'pattern': selected})
        self.assertEqual([c.name for c in parse_recipe(result['change']['value'])], ['ENTER', 'JUDGE', 'EXPORT'])
        change = {'sheet': 'FLOW', 'cell': f'F{row}', 'old': sheet['rows'][row-1][5]['value'],
                  'value': 'ENTER(ROLE=TRIM,WAIT=1MS)-RUN(enter_hsi_8m)-JUDGE(PF=NO)-EXPORT'}
        payload['changes'] = [change]
        view = session.trim_pattern(payload)
        self.assertIn('enter_hsi_16m', [o['name'] for o in view['uses'][0]['options']])
        result = session.trim_pattern({**payload, 'step': 0, 'pattern': 'enter_hsi_16m'})
        self.assertIn('ROLE=TRIM,WAIT=1MS,PATTERN=enter_hsi_16m', result['change']['value'])
        self.assertIn('RUN(enter_hsi_8m)\nJUDGE(PF=NO)\nEXPORT', result['change']['value'])

    def test_copied_item_with_explicit_patterns_compiles_without_same_name_bundle(self):
        session = self.session
        sheet = session.editor.by_name['FLOW']
        row = sheet['maxRow'] + 1
        changes = [
            {'sheet':'FLOW','cell':f'B{row}','old':sheet['rows'][2][1]['value'],'value':'VREF0P8_TC_Copy1'},
            {'sheet':'FLOW','cell':f'F{row}','old':sheet['rows'][2][5]['value'],
             'value':'ENTER(PATTERN=enter_vref0p8_tc)-TRIM(PATTERN=set_vref0p8_tc_dac)-JUDGE'}]
        order = list(range(1, row))
        order.insert(3, row)
        raw = session.editor.apply(session.editor.sha256, changes, [{'sheet':'FLOW','sourceRow':3,'copy':True}], order)
        _, compiled = session.compile(raw)
        self.assertFalse(compiled.is_valid)
        self.assertTrue(all('在 ADDR_MAP 中没有适用字段' in d.message for d in compiled.diagnostics.errors))
        payload = {'baseSha256':session.editor.sha256,'changes':changes,'appendRows':[{'sheet':'FLOW','sourceRow':3,'copy':True}],'flowOrder':order,'row':4}
        prepared = session.storage_mapping(payload)
        self.assertEqual(prepared['item'], 'VREF0P8_TC_Copy1')
        self.assertEqual(prepared['current'], [])
        self.assertTrue(prepared['options'])
        selected = session.storage_mapping({**payload, 'targets': []})
        self.assertTrue(selected['valid'], selected.get('diagnostics'))
        raw = session.editor.apply(session.editor.sha256, changes, payload['appendRows'], order, selected['trimStorageMappings'])
        _, compiled = session.compile(raw)
        self.assertTrue(compiled.is_valid, [d.message for d in compiled.diagnostics.errors])
        _, baseline = session.compile(session.editor.raw)
        current = {(s.cp,s.item):s.test_number for s in compiled.plan.catalogs.trim_specs.values()}
        for original in baseline.plan.catalogs.trim_specs.values():
            self.assertEqual(current[(original.cp,original.item)], original.test_number)
        self.assertNotIn(current[('CP1','VREF0P8_TC_Copy1')], [s.test_number for s in baseline.plan.catalogs.trim_specs.values() if s.cp=='CP1'])
        spec = compiled.plan.catalogs.trim_specs[2]
        self.assertEqual(spec.item, 'VREF0P8_TC_Copy1')
        self.assertEqual(spec.dac.pattern_name, 'set_vref0p8_tc_dac')

    def test_blank_appended_trim_can_map_before_full_validation(self):
        session = self.session
        sheet = session.editor.by_name['FLOW']
        row = sheet['maxRow'] + 1
        additions = [{'sheet': 'FLOW', 'sourceRow': sheet['appendableRows'][-1], 'copy': False}]
        changes = [{'sheet': 'FLOW', 'cell': f'{col}{row}', 'old': None, 'value': value}
                   for col, value in [('A', 'CP1'), ('B', 'test'), ('C', '/'), ('D', '/'), ('E', 'trim')]]
        payload = {'baseSha256': session.editor.sha256, 'changes': changes, 'appendRows': additions, 'row': row}
        view = session.trim_pattern(payload)
        self.assertEqual([u['module'] for u in view['uses']], ['ENTER', 'TRIM'])
        self.assertTrue(view['pendingValidation'])
        for step, name in [(0, 'enter_hsi_8m'), (1, 'set_hsi_8m_dac')]:
            result = session.trim_pattern({**payload, 'step': step, 'pattern': name})
            changes = [c for c in changes if c['cell'] != f'F{row}'] + [result['change']]
            payload['changes'] = changes
        self.assertEqual(result['change']['cell'], f'F{row}')
        raw = session.editor.apply(session.editor.sha256, changes, additions)
        saved = WorkbookEditor(raw, 'new-row.xlsx')
        self.assertIn('PATTERN=set_hsi_8m_dac', saved.by_name['FLOW']['rows'][row-1][5]['value'])
        self.assertEqual(saved.by_name['FLOW']['rows'][11][5]['value'], sheet['rows'][11][5]['value'])
        self.assertTrue(result['pendingValidation'], 'Mapping must not certify missing required fields')
        dac_column = next(i for i, c in enumerate(sheet['columns']) if c['label'] == 'DAC bit')
        self.assertIsNone(saved.by_name['FLOW']['rows'][row-1][dac_column]['value'])

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.session = Session(output=Path(cls.folder.name))

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_cached_open_and_candidate_invalidation(self):
        from unittest.mock import patch
        session = self.session
        payload = {'baseSha256': session.editor.sha256, 'changes': [], 'row': 12,
                   'trimStorageMappings': session.editor.trim_storage_mappings,
                   'verifyStorageMappings': session.editor.verify_storage_mappings}
        with patch.object(session, 'compile', wraps=session.compile) as compile_call:
            view = session.trim_pattern(payload)
            self.assertEqual(compile_call.call_count, 0)
            self.assertEqual(session.trim_pattern(payload), view)
            self.assertEqual(compile_call.call_count, 0)
            step = next(u['step'] for u in view['uses'] if u['module'] == 'ENTER')
            result = session.trim_pattern({**payload, 'step': step, 'pattern': 'enter_hsi_16m'})
            self.assertTrue(result['valid'])
            self.assertTrue(result['pendingValidation'])
            self.assertEqual(compile_call.call_count, 0)
            updated = session.trim_pattern({**payload, 'changes': [result['change']]})
            self.assertEqual(compile_call.call_count, 0)
            self.assertEqual(updated['uses'][0]['current'], 'enter_hsi_16m')
            restored = session.trim_pattern(payload)
            self.assertEqual(compile_call.call_count, 0)
            self.assertEqual(restored['uses'][0]['current'], view['uses'][0]['current'])
            with self.assertRaises(ValueError):
                session.trim_pattern({**payload, 'baseSha256': 'stale'})

    def test_current_bindings_and_row_scoped_save_roundtrip(self):
        session = self.session
        payload = {'baseSha256': session.editor.sha256, 'changes': [], 'row': 12}
        view = session.trim_pattern(payload)
        self.assertEqual(view['item'], 'Hsi_8M')
        enter = next(s for s in view['uses'] if s['module'] == 'ENTER')
        self.assertEqual(enter['current'], 'enter_hsi_8m')
        self.assertIn('enter_hsi_16m', [o['name'] for o in enter['options']])
        result = session.trim_pattern({**payload, 'step': enter['step'], 'pattern': 'enter_hsi_16m'})
        self.assertTrue(result['valid'], result.get('diagnostics'))
        change = result['change']
        self.assertEqual((change['sheet'], change['cell']), ('FLOW', 'F12'))
        self.assertIn('PATTERN=enter_hsi_16m', change['value'])
        raw = session.editor.apply(session.editor.sha256, [change])
        reopened = WorkbookEditor(raw, 'selected.xlsx')
        workbook, compiled = session.compile(raw)
        self.assertTrue(compiled.is_valid)
        specs = compiled.plan.catalogs.trim_specs
        self.assertEqual(specs[10].operations[0].reference, 'enter_hsi_16m')
        self.assertEqual(specs[177].operations[0].reference, 'enter_hsi_8m')
        self.assertEqual(reopened.by_name['FLOW']['rows'][11][5]['value'], change['value'])
        reset = session.trim_pattern({**payload, 'changes': [change], 'step': enter['step'], 'pattern': None})
        self.assertTrue(reset['valid'])
        self.assertNotIn('PATTERN=', reset['change']['value'])
        with self.assertRaisesRegex(ValueError, 'Pattern|绑定|必需'):
            session.trim_pattern({**payload, 'step': enter['step'], 'pattern': ''})
        with self.assertRaisesRegex(ValueError, 'Pattern|候选|适用'):
            session.trim_pattern({**payload, 'step': enter['step'], 'pattern': 'missing_pattern'})

    def test_http_choice_check_and_save_from_frontend(self):
        import json
        import subprocess
        import threading
        from gui.server import make_server
        session = self.session
        server = make_server(0, session)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            state = session.state()
            state.update(testOrigin=server.origin, testToken=server.token)
            root = Path(self.folder.name)
            state_file, evidence_file = root / 'state.json', root / 'evidence.json'
            state_file.write_text(json.dumps(state), encoding='utf-8')
            result = subprocess.run(['node', 'tests/test_gui_ui.cjs', str(state_file), str(evidence_file), 'trim-pattern'],
                                    capture_output=True, text=True, encoding='utf-8', timeout=240)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            evidence = json.loads(evidence_file.read_text(encoding='utf-8'))
            raw = Path(evidence['path']).read_bytes()
            _, compiled = session.compile(raw)
            self.assertTrue(compiled.is_valid)
            self.assertEqual(compiled.plan.catalogs.trim_specs[10].dac.pattern_name, 'set_hsi_16m_dac')
            self.assertEqual(compiled.plan.catalogs.trim_specs[177].dac.pattern_name, 'set_hsi_8m_dac')
            self.assertEqual(len(evidence['changes']), 1)
            print('HTTP_TRIM_PATTERN', result.stdout.splitlines()[-1])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_recipe_steps_include_independent_runs_and_dependency_targets(self):
        from flow_recipe import parse_recipe
        from unittest.mock import patch
        session = self.session
        old = session.editor.by_name['FLOW']['rows'][11][5]['value']
        change = {'sheet': 'FLOW', 'cell': 'F12', 'old': old,
                  'value': 'ENTER(WAIT=1MS)-RUN(enter_hsi_8m)-RUN(enter_hsi_16m)-DEPEND(Hsi_Vrega)-TRIM-JUDGE'}
        payload = {'baseSha256': session.editor.sha256, 'changes': [change], 'row': 12}
        view = session.trim_pattern(payload)
        self.assertEqual([u['module'] for u in view['uses']], ['ENTER', 'RUN', 'RUN', 'DEPEND', 'TRIM'])
        dependency = view['uses'][3]
        names = [o['name'] for o in dependency['options']]
        self.assertIn('Vref0p8_ABS', names)
        self.assertNotIn('Hsi_8M', names)
        self.assertNotIn('Hsi_16M', names)
        self.assertIn('set_vref0p8_abs_dac', next(o['description'] for o in dependency['options'] if o['name'] == 'Vref0p8_ABS'))
        with patch.object(session, 'compile', wraps=session.compile) as compile_call:
            result = session.trim_pattern({**payload, 'step': 2, 'pattern': 'enter_hsi_24m'})
            result = session.trim_pattern({**payload, 'changes': [result['change']], 'step': 3, 'pattern': 'Vref0p8_ABS'})
            self.assertEqual(compile_call.call_count, 0)
        calls = parse_recipe(result['change']['value'])
        self.assertEqual(calls[1].argument, 'enter_hsi_8m')
        self.assertEqual(calls[2].argument, 'enter_hsi_24m')
        self.assertEqual(calls[3].argument, 'Vref0p8_ABS')
        self.assertIn('WAIT=1MS', result['change']['value'])
        self.assertEqual(result['recipeText'], result['change']['value'])
        with self.assertRaises(ValueError):
            session.trim_pattern({**payload, 'changes': [result['change']], 'step': 2, 'pattern': None})
        reset = session.trim_pattern({**payload, 'changes': [result['change']], 'step': 0, 'pattern': None})
        self.assertTrue(reset['valid'], reset.get('diagnostics'))
        self.assertEqual(reset['uses'][2]['current'], 'enter_hsi_24m')
        self.assertEqual(reset['uses'][3]['current'], 'Vref0p8_ABS')


if __name__ == '__main__':
    unittest.main()
