"""Source names become workbook references when a user confirms a Link."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from time import perf_counter

from gui.server import Session, MASTER
from gui.scan_workspace import ScanWorkspace
from gui.swd_workspace import SwdWorkspace
from tests.test_hex_link import workspace as hex_fixture


class PatternLinkNameTests(unittest.TestCase):
    def test_repeated_target_queries_reuse_unchanged_workbook(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        with TemporaryDirectory() as temp:
            session = SimpleNamespace(output=Path(temp),editor=SimpleNamespace(raw=b'base',sha256='base',name='book.xlsx',apply=Mock(return_value=b'draft'),ensure_source_current=Mock()),
                scan=SimpleNamespace(candidate=lambda draft:(SimpleNamespace(dataframe=lambda name:None),b'draft')),links=[])
            workspace = SwdWorkspace(session)
            with patch('program_gen.compiler.ProductCompiler.compile') as compile_plan, \
                 patch('gui.workbook_editor.WorkbookEditor'), patch('gui.links.pattern_links',return_value=[]):
                workspace.targets({});workspace.targets({});workspace.targets({})
                self.assertEqual(compile_plan.call_count,1)
                self.assertEqual(session.editor.apply.call_count,1, 'unchanged draft was packed twice')
                session.editor.ensure_source_current.side_effect = ValueError('disk changed')
                with self.assertRaisesRegex(ValueError, 'disk changed'):
                    workspace.targets({})

    def test_consecutive_name_links_match_full_rebuild_and_validate_drafts(self):
        from copy import deepcopy
        from tests.test_swd_integration import step_book
        with TemporaryDirectory() as temp:
            session = Session(master=MASTER, output=Path(temp))
            session.scan = ScanWorkspace(session)
            session.swd = SwdWorkspace(session)
            session.hex = hex_fixture(Path(temp) / 'fixture')[0].hex
            draft = {'baseSha256': session.editor.sha256, 'changes': []}
            doc = session.swd.import_excel(step_book('Speed_Source'), 'steps.xlsx')['documents'][0]
            for role, old, selection in (
                ('config', 'PT104_SWD_ADC1', {'swdSource': {'documentId': doc['id'], 'pattern': 'Speed_Source'}}),
                ('download', None, {'hexTaskId': 'task', 'hexRun': 'run-one'}),
                ('config', 'Speed_Source', {'swdSource': {'documentId': doc['id'], 'pattern': 'Speed_Source'}}),
            ):
                state = session.swd.targets(draft)
                target = next(t for t in state['targets'] if t['cp'] == 'CP3' and t['role'] == role
                              and (old is None or old in sum(t['names'].values(), [])))
                started = perf_counter()
                result = session.swd.link(dict(targetId=target['id'], adoptSourceName=True, draft=draft, **selection))
                self.assertLess(perf_counter() - started, 2)
                draft = result['draft']
                self.assertEqual(result['previewLinks'], SwdWorkspace(session).targets(draft)['previewLinks'])
                self.assertEqual(result['targets'], SwdWorkspace(session).targets(draft)['targets'])
            invalid = deepcopy(draft)
            invalid['baseSha256'] = 'stale'
            with self.assertRaisesRegex(ValueError, '版本'):
                session.swd.targets(invalid)
            # Undo to the base and redo must restore a matching preview context.
            session.swd.targets({'baseSha256': session.editor.sha256, 'changes': []})
            self.assertEqual(session.swd.targets(draft)['previewLinks'], result['previewLinks'])

    def test_hex_confirmation_updates_reference_and_survives_saved_excel(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            session = Session(master=MASTER, output=root)
            session.scan = ScanWorkspace(session)
            session.hex = hex_fixture(root / 'fixture')[0].hex
            session.swd = SwdWorkspace(session)
            target = next(t for t in session.swd.targets()['targets'] if t['role'] == 'download' and t['cp'] == 'CP3')
            draft = {'baseSha256': session.editor.sha256, 'changes': []}
            started = perf_counter()
            result = session.swd.link({'targetId': target['id'], 'hexTaskId': 'task', 'hexRun': 'run-one',
                                       'adoptSourceName': True, 'draft': draft})
            self.assertLess(perf_counter() - started, 2, 'HEX Link must not rebuild the workbook')
            self.assertIn('draft', result)
            self.assertEqual(result['previewLinks'], SwdWorkspace(session).targets(result['draft'])['previewLinks'])
            updated = result['draft']
            workbook, raw = session.scan.candidate(updated)
            self.assertEqual(workbook['FLOW'].cell(int(target['phase']), 12).value, 'input_swd')
            self.assertNotEqual(raw, session.editor.raw)
            frozen = session.swd.freeze(updated)
            self.assertEqual(frozen[0]['names'], {'shared': ['input_swd']})
            saved = session.save_draft(updated)
            reloaded = Session(master=Path(saved['path']), output=root)
            reloaded.scan = ScanWorkspace(reloaded)
            reloaded.swd = SwdWorkspace(reloaded)
            self.assertEqual(reloaded.swd.freeze(), frozen)

    def test_swd_source_name_is_persisted_and_used_by_both_platforms(self):
        from tests.test_swd_integration import step_book
        from gui.generation import preview_plan
        from program_gen.core.pattern_links import read_pattern_links
        with TemporaryDirectory() as temp:
            root = Path(temp)
            session = Session(master=MASTER, output=root)
            session.scan = ScanWorkspace(session)
            session.swd = SwdWorkspace(session)
            target = next(t for t in session.swd.targets()['targets'] if t['cp'] == 'CP3'
                          and t['names'].get('shared') == ['PT104_SWD_ADC1'])
            doc = session.swd.import_excel(step_book('ADC_Source_V03'), 'steps.xlsx')['documents'][0]
            session.swd.configure({'chip':'PT104','pins':{'swc':'PA11','swd':'PA13','reset':'NRST','trig':'SYS_SHARE_TRIGPIN'}})
            started = perf_counter()
            result = session.swd.link({'targetId': target['id'],
                'swdSource': {'documentId':doc['id'], 'pattern':'ADC_Source_V03'},
                'adoptSourceName':True, 'draft':{'baseSha256':session.editor.sha256,'changes':[]}})
            self.assertLess(perf_counter() - started, 2, 'SWD Link must not rebuild the workbook')
            self.assertEqual(result['previewLinks'], SwdWorkspace(session).targets(result['draft'])['previewLinks'])
            draft = result['draft']
            workbook, raw = session.scan.candidate(draft)
            self.assertEqual(read_pattern_links(raw)[0]['pattern'], 'ADC_Source_V03')
            self.assertNotIn('Pattern Link', workbook.sheetnames)
            renamed = next(t for t in result['targets'] if t['cp']=='CP3' and 'ADC_Source_V03' in sum(t['names'].values(), []))
            before_links = session.swd.targets(draft)['links']
            from unittest.mock import patch
            with patch('program_gen.compiler.ProductCompiler.compile', side_effect=AssertionError('unchanged Link draft was recompiled')):
                self.assertEqual(session.swd.targets(draft)['links'], before_links)
            clash = session.swd.import_excel(step_book('PT104_SWD_ADC2'), 'clash.xlsx')['documents'][-1]
            with self.assertRaisesRegex(ValueError, '冲突|已被'):
                session.swd.link({'targetId':renamed['id'], 'swdSource':{'documentId':clash['id'],'pattern':'PT104_SWD_ADC2'},
                                  'adoptSourceName':True, 'draft':draft})
            self.assertEqual(session.swd.targets(draft)['links'], before_links)
            compilation = session.compile(raw)[1]
            frozen = session.swd.freeze(draft)
            for platform in ('chroma','s100'):
                target_id = next(t['id'] for t in session.targets if t['platform']==platform and t['cp']=='CP3' and t['variant']=='lab')
                plan = preview_plan(workbook, compilation, target_id, swd_bindings=frozen)
                paths = [a.relative_path for a in plan.artifacts]
                suffix = '.pat' if platform == 'chroma' else '.sd'
                self.assertTrue(any(p.endswith('ADC_Source_V03'+suffix) for p in paths), paths)
                self.assertFalse(any(p.endswith('PT104_SWD_ADC1'+suffix) for p in paths))
                program = next(a.content for a in plan.artifacts if a.relative_path.endswith('.pln' if platform=='chroma' else '.prg'))
                self.assertIn(b'ADC_Source_V03', program)
                self.assertNotIn(b'PT104_SWD_ADC1', program)
            saved = session.save_draft(draft)
            reloaded = Session(master=Path(saved['path']), output=root)
            reloaded.scan = ScanWorkspace(reloaded)
            reloaded.swd = SwdWorkspace(reloaded)
            self.assertEqual(reloaded.swd.freeze(), frozen)


if __name__ == '__main__':
    unittest.main()
