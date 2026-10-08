"""SWD source links defer Pattern rendering until program freeze."""
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

import openpyxl


def steps(data='0X00000001', pattern='PT104_demo'):
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(['pattern', 'addr', 'data', 'step', 'reset value', 'type', 'continue', 'description'])
    sheet.append([pattern, '0X40021000', data, '/', '/', 'W', 'Y', 'demo'])
    raw = BytesIO(); book.save(raw)
    return raw.getvalue()


def workspace(root):
    slot = {'phase': 'CONFIG', 'role': 'config', 'status': 'referenced',
            'names': {'shared': ['PT104_SWD_VOL']}}
    session = SimpleNamespace(
        output=root, checked='checked-before-link',
        editor=SimpleNamespace(sha256='program-sha', raw=b'program', name='program.xlsx'),
        scan=SimpleNamespace(candidate=lambda draft: (None, b'program')),
        links=[{'flowRow': 10, 'cp': 'CP3', 'item': 'VOL', 'resourceSlots': [slot]}])
    from gui.swd_workspace import SwdWorkspace
    return session, SwdWorkspace(session)


class SwdSourceLinkTests(unittest.TestCase):
    def test_saved_source_link_generates_current_steps_only_when_frozen(self):
        with TemporaryDirectory() as temp:
            session, links = workspace(Path(temp))
            doc = links.import_excel(steps(), 'steps.xlsx')['documents'][0]
            target = links.targets()['targets'][0]
            session.checked = 'checked-before-link'

            linked = links.link({'targetId': target['id'],
                                 'swdSource': {'documentId': doc['id'], 'pattern': 'PT104_demo'}})

            self.assertIsNone(session.checked)
            self.assertEqual(linked['links'][0]['swdSource'], {'documentId': doc['id'], 'pattern': 'PT104_demo'})
            self.assertFalse((Path(temp) / 'swd' / 'generated').exists())
            source = links.pattern_state()['sources'][0]
            self.assertEqual(source['sourceLabel'], 'steps.xlsx')
            self.assertEqual({file['platform'] for file in source['files']}, {'chroma', 's100'})

            from gui.swd_workspace import SwdWorkspace
            links = SwdWorkspace(session)
            first = links.freeze()
            first_bytes = dict(first[0]['contents'])
            self.assertEqual(set(first[0]['contents']), {'chroma', 's100'})
            saved = links.state()['documents'][0]
            saved['rows'][0]['data'] = '0X00000002'
            links.save({'documentId': doc['id'], 'rows': saved['rows']})
            second = links.freeze()
            self.assertNotEqual(first[0]['contents'], second[0]['contents'])
            self.assertEqual(first[0]['contents'], first_bytes)
            config = links.state()['config']
            config['pins']['swc'] = 'PA11'
            links.configure(config)
            self.assertNotEqual(second[0]['contents'], links.freeze()[0]['contents'])

    def test_rejects_missing_or_pending_source_and_multiple_sources(self):
        with TemporaryDirectory() as temp:
            session, links = workspace(Path(temp))
            doc = links.import_excel(steps(), 'steps.xlsx')['documents'][0]
            pending = links.create_pattern({'name': 'PT104_pending'})
            target = links.targets()['targets'][0]

            with self.assertRaisesRegex(ValueError, '不存在|尚未保存'):
                links.link({'targetId': target['id'],
                            'swdSource': {'documentId': pending['createdDocumentId'], 'pattern': 'PT104_pending'}})
            with self.assertRaisesRegex(ValueError, '一次只能'):
                links.link({'targetId': target['id'], 'generationId': 'old-generation',
                            'swdSource': {'documentId': doc['id'], 'pattern': 'PT104_demo'}})
            with self.assertRaisesRegex(ValueError, '不存在'):
                links.link({'targetId': target['id'],
                            'swdSource': {'documentId': 'missing', 'pattern': 'PT104_demo'}})
            with self.assertRaisesRegex(ValueError, 'SWD'):
                links.link({'targetId': target['id'], 'swdSource': {}})
            with self.assertRaisesRegex(ValueError, 'generationId'):
                links.link({'targetId': target['id'], 'generationId': ''})
            with self.assertRaisesRegex(ValueError, 'hexTaskId'):
                links.link({'targetId': target['id'], 'hexTaskId': ''})

    def test_rejects_different_source_for_shared_resource_in_the_same_cp(self):
        with TemporaryDirectory() as temp:
            session, links = workspace(Path(temp))
            session.links.append({'flowRow': 11, 'cp': 'CP3', 'item': 'VOL_SECOND', 'resourceSlots': [
                {'phase': 'CONFIG', 'role': 'config', 'status': 'referenced',
                 'names': {'shared': ['PT104_SWD_VOL']}}]})
            first = links.import_excel(steps(pattern='PT104_first'), 'first.xlsx')['documents'][0]
            second = links.import_excel(steps(pattern='PT104_second'), 'second.xlsx')['documents'][1]
            targets = links.targets()['targets']
            links.link({'targetId': targets[0]['id'],
                        'swdSource': {'documentId': first['id'], 'pattern': 'PT104_first'}})
            with self.assertRaisesRegex(ValueError, '共享'):
                links.link({'targetId': targets[1]['id'],
                            'swdSource': {'documentId': second['id'], 'pattern': 'PT104_second'}})

    def test_rejects_source_and_legacy_generation_for_shared_resource_in_both_orders(self):
        with TemporaryDirectory() as temp:
            session, links = workspace(Path(temp))
            session.links.append({'flowRow': 11, 'cp': 'CP3', 'item': 'VOL_SECOND', 'resourceSlots': [
                {'phase': 'CONFIG', 'role': 'config', 'status': 'referenced',
                 'names': {'shared': ['PT104_SWD_VOL']}}]})
            doc = links.import_excel(steps(), 'steps.xlsx')['documents'][0]
            links.data['generations'].append({'id': 'legacy-generation', 'documentId': doc['id'],
                                              'pattern': 'PT104_demo', 'revision': links._revision(doc), 'files': []})
            targets = links.targets()['targets']
            links.link({'targetId': targets[0]['id'],
                        'swdSource': {'documentId': doc['id'], 'pattern': 'PT104_demo'}})
            with self.assertRaisesRegex(ValueError, '共享'):
                links.link({'targetId': targets[1]['id'], 'generationId': 'legacy-generation'})
            links = workspace(Path(temp) / 'reverse')[1]
            doc = links.import_excel(steps(), 'steps.xlsx')['documents'][0]
            links.session.links.append({'flowRow': 11, 'cp': 'CP3', 'item': 'VOL_SECOND', 'resourceSlots': [
                {'phase': 'CONFIG', 'role': 'config', 'status': 'referenced',
                 'names': {'shared': ['PT104_SWD_VOL']}}]})
            links.data['generations'].append({'id': 'legacy-generation', 'documentId': doc['id'],
                                              'pattern': 'PT104_demo', 'revision': links._revision(doc), 'files': []})
            targets = links.targets()['targets']
            links.link({'targetId': targets[0]['id'], 'generationId': 'legacy-generation'})
            with self.assertRaisesRegex(ValueError, '共享'):
                links.link({'targetId': targets[1]['id'],
                            'swdSource': {'documentId': doc['id'], 'pattern': 'PT104_demo'}})


if __name__ == '__main__':
    unittest.main()
