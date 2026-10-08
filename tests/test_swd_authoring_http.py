"""Public HTTP entry points for standalone Pattern authoring and bundled materials."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from urllib.request import Request, urlopen

from gui.server import Session, make_server


class SwdAuthoringHttpTests(unittest.TestCase):
    def test_create_cached_register_save_and_generate_without_program(self):
        with TemporaryDirectory() as directory:
            service = make_server(0, session=Session(master=None, output=Path(directory)))
            worker = threading.Thread(target=service.serve_forever, daemon=True)
            worker.start()
            def call(path, payload):
                request = Request(service.origin + path, data=json.dumps(payload).encode(), headers={
                    'Origin': service.origin, 'X-GUI-Session': service.token,
                    'Content-Type': 'application/json'})
                with urlopen(request, timeout=20) as response:
                    return json.load(response)
            try:
                created = call('/api/swd/create', {'name': 'CACHE_TEST'})
                cached = call('/api/swd/cache', {})
                material = cached['materials']['materials'][0]
                self.assertEqual(material['kind'], 'svd_cache')
                self.assertEqual(material['sha256'], 'c068e728cdc121cce63abbb909cdb9a50e1bc2dd19c2e2bcfa1fab8c2ebcb2fa')
                sources = [s for r in cached['materials']['registers'] for s in r['sources']]
                self.assertEqual(len(sources), 525)
                self.assertEqual(sum(len(s['fields']) for s in sources), 3717)
                again = call('/api/swd/cache', {})
                self.assertEqual(again['materials'], cached['materials'])
                row = created['documents'][0]['rows'][0]
                row.update(addr=sources[0]['address'], data='0x80000000', type='W', step='/')
                saved = call('/api/swd/save', {'documentId': created['createdDocumentId'], 'rows': [row]})
                self.assertEqual(saved['documents'][0]['rows'][0]['data'], '0x80000000')
                generated = call('/api/swd/generate', {'documentId': created['createdDocumentId'], 'pattern': 'CACHE_TEST'})
                self.assertEqual({f['platform'] for f in generated['generations'][-1]['files']}, {'chroma', 's100'})
            finally:
                service.shutdown(); service.server_close(); worker.join(5)
