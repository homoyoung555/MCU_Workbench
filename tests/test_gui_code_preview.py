"""Pre-generation preview: authenticated snapshots, no writes, exact output bytes."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from gui.server import Session, fingerprint, make_server
from program_gen.render_plan import ArtifactPlan, RenderPlan, TargetKey


class PreviewBoundaryTests(unittest.TestCase):
    def test_checked_http_preview_never_creates_a_job_or_output(self):
        with TemporaryDirectory() as tmp:
            s = object.__new__(Session)
            s.output = Path(tmp) / 'absent'
            s.job = None
            s.editor = SimpleNamespace(sha256='base', ensure_source_current=lambda: None)
            key = TargetKey('chroma', 'CP1', 'lab', 'example')
            payload = dict(baseSha256='base', changes=[], checkId='checked',
                           targets=[key.identity], scope='program', target=key.identity)
            s.checked = dict(id='checked', scope='program', fingerprint=fingerprint(payload),
                             raw=b'input', workbook=None, compilation=None,
                             targets=[{'id': key.identity}])
            plan = RenderPlan.from_artifacts(key, [ArtifactPlan('main.pln', 'void example() {}\n', 'PROGRAM', ('test',))])
            server = make_server(0, s)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            def request(path, data=None, token=True):
                headers = {'Content-Type': 'application/json'}
                if token: headers['X-GUI-Session'] = server.token
                return json.load(urlopen(Request(server.origin + path,
                    data=json.dumps(data).encode() if data is not None else None, headers=headers), timeout=5))
            try:
                with patch('gui.generation.preview_plan', return_value=plan), patch('gui.server.write_new', side_effect=AssertionError('preview wrote files')):
                    result = request('/api/preview', payload)
                    self.assertEqual(result['files'][0]['path'], 'main.pln')
                    query = '/api/preview?' + urlencode({'id': result['previewId'], 'file': 'main.pln'})
                    self.assertEqual(request(query)['text'], 'void example() {}\n')
                    self.assertIsNone(s.job)
                    self.assertFalse(s.output.exists())
                    for bad in [dict(payload, checkId='old'), dict(payload, changes=[{}]),
                                dict(payload, scope='pump'), dict(payload, target='unknown'),
                                dict(payload, targets=[]), dict(payload, targets=[{}, {}])]:
                        with self.assertRaises(HTTPError) as error: request('/api/preview', bad)
                        self.assertEqual(error.exception.code, 422)
                    with self.assertRaises(HTTPError) as error: request('/api/preview', payload, False)
                    self.assertEqual(error.exception.code, 403)
                    with self.assertRaises(HTTPError): request(query.replace('main.pln', '..%2Fsecret'))
                    newer = request('/api/preview', payload)
                    self.assertNotEqual(newer['previewId'], result['previewId'])
                    with self.assertRaises(HTTPError): request(query)
                    s.checked = None
                    with self.assertRaises(HTTPError): request('/api/preview?' + urlencode({'id': newer['previewId'], 'file': 'main.pln'}))
            finally:
                server.shutdown(); server.server_close(); thread.join()


class RealPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from program_gen.compiler import ProductCompiler
        from program_gen.workbook import WorkbookReader
        from tests.workspace_paths import FORMAL_MASTER
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()

    def test_real_page_previews_edited_program_and_pump_without_generating(self):
        from gui.server import MASTER
        original = MASTER.read_bytes()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            s = Session(output=root / 'absent')
            server = make_server(0, s)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                state = s.state(); state.update(testOrigin=server.origin, testToken=server.token)
                source, evidence = root / 'state.json', root / 'evidence.json'
                source.write_text(json.dumps(state), encoding='utf-8')
                with patch('gui.server.write_new', side_effect=AssertionError('preview wrote files')):
                    result = subprocess.run(['node', 'tests/test_gui_ui.cjs', str(source), str(evidence), 'code-preview'],
                                            capture_output=True, text=True, encoding='utf-8', timeout=240)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(len(json.loads(evidence.read_text())), 4)
                self.assertFalse(s.output.exists())
                self.assertIsNone(s.job)
                self.assertEqual(MASTER.read_bytes(), original)
                print('REAL_CODE_PREVIEW', evidence.read_text()); print(result.stdout.splitlines()[-1])
            finally:
                server.shutdown(); server.server_close(); thread.join()

    def test_all_scopes_both_platforms_match_generated_bytes(self):
        from gui import generation as g
        catalogs = {'program': g.available_targets(self.workbook, self.compilation),
                    'pin': g.available_pin_targets(self.workbook), 'fbist': g.available_fbist_targets(),
                    'pump': g.available_pump_targets(), 'flash': g.available_flash_targets(),
                    'flash_labels': g.available_flash_label_targets()}
        catalogs['patterns'] = catalogs['program']
        with TemporaryDirectory(dir=Path.cwd(), prefix='') as tmp:
            parent = Path(tmp)
            with patch.object(g, '_RUN_PARENT', parent):
                for scope, choices in catalogs.items():
                    for platform in ('chroma', 's100'):
                        target = next(t for t in choices if t['platform'] == platform)
                        with patch('pathlib.Path.mkdir', side_effect=AssertionError('preview created directory')):
                            plan = g.preview_plan(self.workbook, self.compilation, target['id'], scope)
                        run = parent / (scope + platform)
                        (run / 'input').mkdir(parents=True)
                        result = g.generate_review(self.workbook, self.compilation, [target['id']], run, scope=scope)
                        output = result['outputs'][0]
                        self.assertIsNone(output['error'], output)
                        self.assertEqual(plan.identity, output['manifest_identity'])
                        self.assertEqual(list(plan.release_blockers), output['release_blockers'])
                        root = Path(output['path'])
                        self.assertEqual(len(plan.artifacts), output['artifact_count'])
                        for artifact in plan.artifacts:
                            self.assertEqual(artifact.content, (root / artifact.relative_path).read_bytes())
                        print('PREVIEW_MATCH', scope, platform, len(plan.artifacts))


if __name__ == '__main__':
    unittest.main()
