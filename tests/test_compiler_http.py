"""Compiler page is usable without a workbook and uses the same-origin session."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from gui.server import Session, make_server


class CompilerHttpTests(unittest.TestCase):
    def test_folder_upload_without_workbook_is_authenticated_and_finalized(self):
        with tempfile.TemporaryDirectory() as directory:
            server = make_server(0, session=Session(master=None, output=Path(directory)), compiler_enabled=True)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            def request(path, data=None, extra=None, token=True):
                headers = {'X-GUI-Session': server.token} if token else {}
                if data is not None:
                    headers['Content-Type'] = 'application/json'
                    if not isinstance(data, bytes):
                        data = json.dumps(data).encode()
                headers.update(extra or {})
                with urlopen(Request(server.origin + path, data=data, headers=headers), timeout=5) as response:
                    return json.load(response)
            try:
                with self.assertRaises(HTTPError) as failure:
                    request('/api/compiler/create', {'name': 'demo'}, token=False)
                self.assertEqual(failure.exception.code, 403)
                task = request('/api/compiler/create', {'name': 'demo'})
                request('/api/compiler/file', b'PRJ', {'Content-Type': 'application/octet-stream',
                        'X-Task-Id': task['id'], 'X-File-Name': 'demo.prj'})
                # Empty include files are legitimate folder content.
                request('/api/compiler/file', b'', {'Content-Type': 'application/octet-stream',
                        'X-Task-Id': task['id'], 'X-File-Name': 'empty.h'})
                self.assertEqual(request('/api/compiler/ready', {'id': task['id']})['platform'], 's100')
                self.assertEqual(request('/api/compiler/state')['tasks'][0]['status'], 'ready')
                with self.assertRaises(HTTPError) as failure:
                    request('/api/compiler/clear', {}, token=False)
                self.assertEqual(failure.exception.code, 403)
                self.assertEqual(request('/api/compiler/clear', {})['tasks'], [])
                self.assertEqual(request('/api/compiler/state')['tasks'], [])
            finally:
                server.shutdown()
                server.server_close()
                worker.join(5)
