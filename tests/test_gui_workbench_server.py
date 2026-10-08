"""Workbench entry and SCAN session boundaries."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import json
import threading
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from gui.server import Session, make_server
from gui.scan_workspace import ScanWorkspace
from tests.test_gui_scan_conversion import WGL


class WorkbenchServerTests(unittest.TestCase):
    def test_rejected_draft_does_not_leave_conversion_running(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        with TemporaryDirectory() as folder:
            session = Session(master=None, output=Path(folder))
            scan = ScanWorkspace(session)
            record = scan.add_input(WGL.encode(), 'sample.wgl')
            session.editor = SimpleNamespace(sha256='test-workbook')
            scan.associations = [{'cp': 'CP1'}]
            previous = {'id': 'previous', 'status': 'completed'}
            scan.job = previous
            with patch.object(scan, '_load_associations'), patch.object(scan, 'candidate', side_effect=ValueError('invalid draft')):
                with self.assertRaisesRegex(ValueError, 'invalid draft'):
                    scan.start({'inputIds': [record['id']], 'platforms': ['chroma']})
            self.assertIs(scan.job, previous)

    def test_linked_draft_generates_both_platforms_and_stale_source_is_blocked(self):
        from gui.generation import preview_plan
        from gui.workbook_editor import WorkbookEditor
        with TemporaryDirectory() as folder:
            session = Session(output=Path(folder))
            scan = ScanWorkspace(session)
            session.scan = scan
            flow = session.editor.by_name['FLOW']
            row = flow['maxRow'] + 1
            values = {'CP NO': 'CP1', 'item': 'Scan_Link_Test', 'type': 'verify', 'mode': 'scan',
                      'OTP': 'no', 'UID': 'no', 'PUMP': 'no', 'Vcc': 'VCC_TYP', 'Hbin': '61', 'Sbin': '61'}
            draft = {'baseSha256': session.editor.sha256, 'appendRows': [{'sheet': 'FLOW', 'sourceRow': 4, 'copy': False}],
                     'changes': [{'sheet': 'FLOW', 'cell': column['letter'] + str(row), 'old': None, 'value': values[column['label']]}
                                 for column in flow['columns'] if column['label'] in values]}
            record = scan.add_input(WGL.encode(), 'linked_scan.wgl')
            scan.start({'inputIds': [record['id']], 'platforms': ['chroma', 's100'], 'adapt': True, 'cp': 'CP1', 'draft': draft})
            self.wait_job(scan)
            self.assertIn(row, [t['row'] for t in scan.targets(draft)['targets']])
            state = scan.link({'jobId': scan.job['id'], 'row': row, 'draft': draft})
            self.assertFalse(state['associations'][0]['stale'])
            self.assertEqual(session.editor.by_name['FLOW']['maxRow'], row - 1)
            checked = session.check(draft)
            self.assertTrue(checked['valid'], checked.get('diagnostics'))
            targets = [t['id'] for t in checked['targets'] if t['cp'] == 'CP1' and t['variant'] == 'lab']
            payload = {**draft, 'checkId': checked['checkId'], 'targets': targets}
            prepared, _, _ = session.require_generation(payload)
            for target in targets:
                plan = preview_plan(prepared['workbook'], prepared['compilation'], target, scan_bindings=prepared['scanBindings'])
                self.assertTrue(any('linked_scan' in a.relative_path for a in plan.artifacts))
                program = next(a for a in plan.artifacts if a.relative_path.endswith(('.pln', '.prg')))
                self.assertIn(b'linked_scan', program.content)
            saved = session.save_draft(draft)
            session.load(Path(saved['path']).read_bytes(), 'saved.xlsx')
            self.assertEqual(len(scan.state()['scan']['associations']), 1)
            previous_job = scan.associations[0]['jobId']
            scan.start({'inputIds': [record['id']], 'platforms': ['chroma', 's100'], 'adapt': True,
                        'cp': 'CP1', 'draft': {'baseSha256': session.editor.sha256, 'changes': []}}, refresh_associations=False)
            self.wait_job(scan)
            self.assertNotEqual(scan.job['id'], previous_job)
            self.assertEqual(scan.associations[0]['jobId'], previous_job)
            scan.add_input((WGL + '\n// changed').encode(), 'linked_scan.wgl')
            with self.assertRaisesRegex(ValueError, 'WGL'):
                scan.freeze()

    def wait_job(self, scan):
        deadline = time.monotonic() + 60
        while scan.job['status'] == 'running' and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(scan.job['status'], 'completed', scan.job)

    def test_full_pin_job_preserves_snapshot_and_detects_original_change(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'sample.wgl'
            source.write_text(WGL)
            scan = ScanWorkspace(Session(master=None, output=root / 'runs'))
            record = scan.register_paths([str(source)])['inputs'][0]
            scan.start({'inputIds': [record['id']], 'platforms': ['chroma', 's100']})
            self.wait_job(scan)
            original = scan.job['sources'][0]['sha256']
            self.assertFalse(scan.state()['scan']['job']['stale'])
            self.assertEqual(len(scan.job['result']['files']), 6)
            source.write_text(WGL + '\n// changed')
            self.assertTrue(scan.state()['scan']['job']['stale'])
            self.assertEqual(scan.job['sources'][0]['sha256'], original)
            with self.assertRaises(ValueError):
                scan.output_file(scan.job['id'], '../input/sample.wgl')

    def test_http_empty_entry_full_pin_and_auth_boundaries(self):
        with TemporaryDirectory() as folder:
            service = make_server(0, Session(master=None, output=Path(folder)))
            threading.Thread(target=service.serve_forever, daemon=True).start()
            def request(path, value=None, mime='application/json', authenticated=True):
                headers = {'Content-Type': mime, 'X-File-Name': 'sample.wgl'}
                if authenticated:
                    headers['X-GUI-Session'] = service.token
                raw = json.dumps(value).encode() if value is not None and mime == 'application/json' else value
                return urlopen(Request(service.origin + path, data=raw, headers=headers), timeout=10)
            try:
                with request('/') as response:
                    self.assertIn(b'wb-program-frame', response.read())
                with self.assertRaises(HTTPError) as error:
                    request('/api/workbench', authenticated=False)
                self.assertEqual(error.exception.code, 403)
                labeled_wgl = WGL.replace('    vector(', '{ Measure Iddq All }\n    vector(')
                with request('/api/scan/input', labeled_wgl.encode(), 'application/octet-stream') as response:
                    record = json.load(response)
                with request('/api/scan/pins', {'inputIds': [record['id']]}) as response:
                    catalog = json.load(response)
                    self.assertEqual(catalog['pins'], ['PA1', 'PA0', 'PB0'])
                    self.assertEqual(catalog['inputs'][0]['id'], record['id'])
                with self.assertRaises(HTTPError) as error:
                    request('/api/scan/pins', {'inputIds': [record['id']]}, authenticated=False)
                self.assertEqual(error.exception.code, 403)
                with self.assertRaises(HTTPError) as error:
                    request('/api/scan/start', {'inputIds': [record['id']], 'platforms': ['chroma'], 'manualPins': []})
                self.assertEqual(error.exception.code, 422)
                self.assertIsNone(service.scan.job)
                with self.assertRaises(HTTPError) as error:
                    request('/api/scan/start', {'inputIds': [record['id']], 'platforms': ['chroma'], 'labelMarker': 'Measure Iddq All'})
                self.assertEqual(error.exception.code, 422)
                self.assertIsNone(service.scan.job)
                with request('/api/scan/start', {'inputIds': [record['id']], 'platforms': ['chroma'], 'manualPins': ['PA0'], 'labelMarker': 'Measure Iddq All', 'labelBase': 'M_Iddq'}) as response:
                    job_id = json.load(response)['jobId']
                self.wait_job(service.scan)
                with request('/api/scan/status', {}) as response:
                    state = json.load(response)
                    self.assertEqual(state['job']['id'], job_id)
                    self.assertFalse(state['job']['stale'])
                    self.assertEqual(state['job']['manualPins'], ['PA0'])
                    self.assertEqual(state['job']['labelBase'], 'M_Iddq')
                    self.assertEqual(state['job']['result']['mode'], 'manual-pins')
                    pattern = service.scan.output_file(job_id, 'chroma/sample.pat').read_text(encoding='utf-8')
                    self.assertIn('PA0;', pattern)
                    self.assertIn('*1*', pattern)
                    self.assertIn('M_Iddq_1:', pattern)
                    self.assertNotIn('PA1', pattern)
                with self.assertRaises(HTTPError) as error:
                    request('/api/check', {})
                self.assertEqual(error.exception.code, 422)
            finally:
                service.shutdown()
                service.server_close()

    def test_empty_workbench_does_not_require_a_master(self):
        with TemporaryDirectory() as folder:
            session = Session(master=None, output=Path(folder))
            self.assertFalse(session.state()['loaded'])
            self.assertEqual(session.state()['sheets'], [])
            service = make_server(0, session)
            try:
                self.assertFalse(service.scan.state()['program']['loaded'])
            finally:
                service.server_close()


if __name__ == '__main__':
    unittest.main()
