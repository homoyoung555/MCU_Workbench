"""The default V0.5 server must not expose vendor compilation."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from gui.server import Session, make_server


class ReleaseTests(unittest.TestCase):
    def test_default_blocks_page_and_all_compiler_operations(self):
        with tempfile.TemporaryDirectory() as folder:
            server = make_server(0, session=Session(master=None, output=Path(folder)))
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                for path, data in [('/compiler', None), ('/api/compiler/state', None),
                                   ('/api/compiler/log?id=missing', None),
                                   ('/api/compiler/download?id=missing', None),
                                   ('/api/compiler/create', b'{}'),
                                   ('/api/compiler/file', b'PRJ'),
                                   ('/api/compiler/ready', b'{}'),
                                   ('/api/compiler/start', b'{}'),
                                   ('/api/compiler/discard', b'{}'),
                                   ('/api/compiler/clear', b'{}')]:
                    with self.subTest(path=path):
                        request = Request(server.origin + path, data=data,
                                          headers={'X-GUI-Session': server.token})
                        with self.assertRaises(HTTPError) as error:
                            urlopen(request, timeout=5)
                        self.assertEqual(error.exception.code, 403)
                        self.assertIn('暂未开放', json.load(error.exception)['error'])
                self.assertEqual(server.compiler.state()['tasks'], [])
                with urlopen(server.origin, timeout=5) as response:
                    html = response.read().decode('utf-8')
                self.assertIn('V0.5', html)
                self.assertIn('disabled data-page="compiler"', html)
                for path in ('/swd', '/assistant', '/program', '/hex'):
                    with urlopen(server.origin + path, timeout=5) as response:
                        self.assertEqual(response.status, 200)
            finally:
                server.shutdown()
                server.server_close()
                worker.join(5)
