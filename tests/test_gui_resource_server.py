"""Actual page logic -> HTTP -> resource generation -> result viewer."""
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest

from gui.server import MASTER, Session, make_server


class ResourceServerTests(unittest.TestCase):
    def test_checked_resource_generation_retry_and_preview(self):
        original = MASTER.read_bytes()
        session = Session()
        server = make_server(0, session)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            state = session.state()
            state.update(testOrigin=server.origin, testToken=server.token)
            with tempfile.TemporaryDirectory(prefix='gui-resources-') as tmp:
                input_path, output_path = Path(tmp)/'state.json', Path(tmp)/'evidence.json'
                input_path.write_text(json.dumps(state), encoding='utf-8')
                done = subprocess.run(['node', 'tests/test_gui_ui.cjs', str(input_path), str(output_path), 'resources'],
                                      capture_output=True, text=True, encoding='utf-8', timeout=100)
                self.assertEqual(done.returncode, 0, done.stdout+'\n'+done.stderr)
                evidence = json.loads(output_path.read_text(encoding='utf-8'))
                self.assertEqual([x['scope'] for x in evidence], ['pin', 'patterns'])
                self.assertNotEqual(evidence[0]['job'], evidence[1]['job'])
                self.assertEqual(session.checked['raw'], original)
                self.assertEqual(MASTER.read_bytes(), original)
                print('REAL_RESOURCE_HTTP', json.dumps(evidence))
                print(done.stdout.splitlines()[-1])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
