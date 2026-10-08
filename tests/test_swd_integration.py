"""HTTP acceptance coverage for the SWD link lifecycle on the real PT104 mother workbook."""
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import openpyxl

from gui.server import MASTER, Session, make_server


def step_book(pattern):
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = 'SWD_STEPS'
    sheet.append(['pattern', 'addr', 'data', 'step', 'reset value', 'type', 'continue', 'description'])
    sheet.append([pattern, '0X40021000', '0X00000001', '/', '/', 'W', 'N', 'HTTP acceptance step'])
    raw = BytesIO()
    book.save(raw)
    return raw.getvalue()


class SwdHttpIntegrationTests(unittest.TestCase):
    def test_persisted_pre_revision_two_generation_is_stale(self):
        """An output made by the previous S100 renderer must be regenerated before linking."""
        from gui.swd_workspace import SwdWorkspace, digest
        with TemporaryDirectory(prefix='swd-revision-') as temp:
            session = SimpleNamespace(output=Path(temp), checked=None, editor=None)
            workspace = SwdWorkspace(session)
            document = workspace.import_excel(step_book('PT104_SWD_ADC1'), 'steps.xlsx')['documents'][0]
            workspace.generate({'documentId': document['id'], 'pattern': 'PT104_SWD_ADC1'})
            generation = workspace.data['generations'][0]
            generation['revision'] = digest([
                document['rows'], workspace.data['config'], workspace.data['materialsRevision']])
            workspace._persist()
            restored = SwdWorkspace(session).state()['generations'][0]
            self.assertTrue(restored['stale'])
            self.assertIn('重新生成', restored['reason'])

    def test_real_pt104_http_link_preview_generation_and_relink_lifecycle(self):
        """A saved PT104 program consumes both frozen SWD outputs only after an explicit Link."""
        with TemporaryDirectory(prefix='swd-http-') as temp:
            with patch('gui.generation._RUN_PARENT', Path(temp)):
                self._run_lifecycle(Path(temp))

    def _run_lifecycle(self, output):
            session = Session(master=MASTER, output=output)
            service = make_server(0, session=session)
            worker = threading.Thread(target=service.serve_forever, daemon=True)
            worker.start()
            def stop_server():
                service.shutdown()
                service.server_close()
                worker.join(5)
            self.addCleanup(stop_server)

            def call(path, payload=None, *, raw=None, name=None):
                data = raw if raw is not None else (None if payload is None else json.dumps(payload).encode('utf-8'))
                headers = {'Origin': service.origin, 'X-GUI-Session': service.token,
                           'Content-Type': 'application/octet-stream' if raw is not None else 'application/json'}
                if name is not None:
                    headers['X-File-Name'] = name
                request = Request(service.origin + path, headers=headers, data=data)
                try:
                    with urlopen(request, timeout=90) as response:
                        return response.status, json.load(response) if response.headers.get_content_type() == 'application/json' else response.read()
                except HTTPError as error:
                    return error.code, json.load(error)

            status, state = call('/api/state')
            self.assertEqual(status, 200)
            self.assertEqual(state['name'], MASTER.name)
            status, choices = call('/api/swd/targets', {})
            self.assertEqual(status, 200, choices)
            target = next((item for item in choices['targets']
                           if item['cp'] == 'CP3' and item['names'].get('shared') == ['PT104_SWD_ADC1']), None)
            self.assertIsNotNone(target, 'real PT104 master must expose its explicit ADC1 SWD resource')

            status, swd = call('/api/swd/import', raw=step_book('PT104_SWD_ADC1'), name='pt104_steps.xlsx')
            self.assertEqual(status, 200, swd)
            document = swd['documents'][0]
            status, configured = call('/api/swd/config', {'chip': 'PT104', 'pins': {
                'swc': 'PA14', 'swd': 'PA13', 'reset': 'NRST', 'trig': 'SYS_SHARE_TRIGPIN'}})
            self.assertEqual(status, 200, configured)
            status, generated = call('/api/swd/generate', {'documentId': document['id'], 'pattern': 'PT104_SWD_ADC1'})
            self.assertEqual(status, 200, generated)
            generation = generated['generations'][-1]
            self.assertEqual({item['platform'] for item in generation['files']}, {'chroma', 's100'})

            status, linked = call('/api/swd/link', {'targetId': target['id'], 'generationId': generation['id']})
            self.assertEqual(status, 200, linked)
            self.assertEqual(linked['links'][0]['generationId'], generation['id'])

            draft = {'baseSha256': state['sha256'], 'changes': [], 'appendRows': [], 'flowOrder': []}
            status, checked = call('/api/check', draft)
            self.assertEqual(status, 200, checked)
            self.assertTrue(checked['valid'], checked)
            cp3 = [item['id'] for item in checked['targets'] if item['cp'] == 'CP3' and item['variant'] == 'lab']
            self.assertEqual(len(cp3), 2, checked['targets'])
            request = {**draft, 'checkId': checked['checkId'], 'targets': cp3, 'validate': False}

            status, preview = call('/api/preview', {**request, 'target': cp3[0]})
            self.assertEqual(status, 200, preview)
            chroma = next(item['path'] for item in preview['files'] if item['path'].endswith('PT104_SWD_ADC1.pat'))
            status, preview_text = call('/api/preview?id=' + preview['previewId'] + '&file=' + chroma)
            self.assertEqual(status, 200, preview_text)
            self.assertIn('SPM_PATTERN(PT104_SWD_ADC1)', preview_text['text'])

            status, saved = call('/api/save', request)
            self.assertEqual(status, 200, saved)
            status, reloaded = call('/api/load', raw=Path(saved['path']).read_bytes(), name=Path(saved['path']).name)
            self.assertEqual(status, 200, reloaded)
            fresh_draft = {**draft, 'baseSha256': reloaded['sha256']}
            status, checked = call('/api/check', fresh_draft)
            self.assertEqual(status, 200, checked)
            request = {**fresh_draft, 'checkId': checked['checkId'], 'targets': cp3, 'validate': False}
            status, started = call('/api/generate', request)
            self.assertEqual(status, 200, started)
            deadline = time.monotonic() + 180
            while True:
                status, job = call('/api/job?id=' + started['jobId'])
                self.assertEqual(status, 200, job)
                if job['status'] != 'running':
                    break
                self.assertLess(time.monotonic(), deadline, 'timed out waiting for SWD-linked program generation')
                time.sleep(.25)
            self.assertEqual(job['status'], 'completed', job)
            self.assertEqual({output['platform'] for output in job['result']['outputs']}, {'chroma', 's100'})

            changed_rows = document['rows']
            changed_rows[0]['data'] = '0X00000002'
            status, stale = call('/api/swd/save', {'documentId': document['id'], 'rows': changed_rows})
            self.assertEqual(status, 200, stale)
            self.assertTrue(stale['generations'][-1]['stale'])
            status, checked = call('/api/check', fresh_draft)
            if status != 200:
                self.fail('checking the stale saved workbook failed: ' + repr(checked))
            stale_request = {**fresh_draft, 'checkId': checked['checkId'], 'targets': cp3, 'validate': False}
            status, error = call('/api/generate', stale_request)
            self.assertEqual(status, 422)
            self.assertIn('重新生成', error['error'])

            status, regenerated = call('/api/swd/generate', {'documentId': document['id'], 'pattern': 'PT104_SWD_ADC1'})
            self.assertEqual(status, 200, regenerated)
            replacement = regenerated['generations'][-1]
            status, checked = call('/api/check', fresh_draft)
            self.assertEqual(status, 200, checked)
            status, error = call('/api/generate', {**fresh_draft, 'checkId': checked['checkId'], 'targets': cp3, 'validate': False})
            self.assertEqual(status, 422)
            self.assertIn('重新生成', error['error'])
            status, relinked = call('/api/swd/link', {'targetId': target['id'], 'generationId': replacement['id']})
            self.assertEqual(status, 200, relinked)
            self.assertEqual(relinked['links'][0]['generationId'], replacement['id'])

            renamed_draft = {**fresh_draft, 'changes': [{
                'sheet': 'FLOW', 'cell': 'B' + str(target['row']),
                'old': target['item'], 'value': target['item'] + '_renamed'}]}
            status, renamed_targets = call('/api/swd/targets', {'draft': renamed_draft})
            self.assertEqual(status, 200, renamed_targets)
            self.assertNotIn(target['id'], {item['id'] for item in renamed_targets['targets']})
            status, unlinked = call('/api/swd/link', {
                'targetId': target['id'], 'generationId': None, 'draft': renamed_draft})
            self.assertEqual(status, 200, unlinked)
            self.assertEqual(unlinked['links'], [])
            # The renamed ADC item is deliberately no longer a valid typed item;
            # returning to the unchanged saved mother after unbinding proves the
            # obsolete Link itself no longer blocks the normal preview path.
            status, checked = call('/api/check', fresh_draft)
            self.assertEqual(status, 200, checked)
            self.assertTrue(checked['valid'], checked)
            restored_request = {**fresh_draft, 'checkId': checked['checkId'], 'targets': cp3, 'validate': False}
            status, restored = call('/api/preview', {**restored_request, 'target': cp3[0]})
            self.assertEqual(status, 200, restored)


if __name__ == '__main__':
    unittest.main()
