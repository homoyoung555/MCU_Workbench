"""Real HTTP -> edited workbook -> native full-program outputs, isolated from published outputs."""
import json
from pathlib import Path
import threading
import time
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from gui.server import make_server, MASTER, OUTPUT
from gui.workbook_editor import sha


class GuiHttpIntegrationTests(unittest.TestCase):
    def test_real_multitarget_generation_and_snapshot_binding(self):
        baseline=MASTER.read_bytes()
        service=make_server(0)
        worker=threading.Thread(target=service.serve_forever,daemon=True);worker.start()
        def call(path,body=None,token=None):
            headers={'Origin':service.origin,'X-GUI-Session':token or service.token,'Content-Type':'application/json'}
            request=Request(service.origin+path,headers=headers,data=None if body is None else json.dumps(body).encode())
            try:
                with urlopen(request,timeout=90) as response: return response.status,json.load(response)
            except HTTPError as error: return error.code,json.load(error)
        try:
            self.assertEqual(call('/api/state',token='wrong')[0],403)
            status,state=call('/api/state');self.assertEqual(status,200)
            self.assertEqual(len(state['sheets']),16)
            self.assertEqual(len(state['targets']),9)
            self.assertTrue(all(not c['editable'] for s in state['sheets'] if s['name']=='PIN DEC' for row in s['rows'] for c in row))
            draft={'baseSha256':state['sha256'],'changes':[{'sheet':'FLOW','cell':'S4','old':.8,'value':'0.801'}]}
            status,checked=call('/api/check',draft)
            self.assertEqual(status,200,checked);self.assertTrue(checked['valid'],checked)
            self.assertEqual(checked['errors'],0);self.assertEqual(checked['warnings'],51)
            payload={**draft,'checkId':checked['checkId']}
            status,saved=call('/api/save',payload);self.assertEqual(status,200,saved)
            self.assertEqual(sha(Path(saved['path']).read_bytes()),checked['sha256'])
            self.assertEqual(call('/api/save',payload)[1],saved)
            generate={**payload,'targets':[t['id'] for t in checked['targets']],'validate':False}
            status,started=call('/api/generate',generate);self.assertEqual(status,200,started)
            self.assertEqual(call('/api/generate',generate)[1]['jobId'],started['jobId'])
            deadline=time.monotonic()+180
            while True:
                status,job=call('/api/job?id='+started['jobId'])
                self.assertEqual(status,200,job)
                if job['status']!='running':break
                if time.monotonic()>deadline:self.fail('Generation did not finish in 180 seconds')
                time.sleep(.25)
            self.assertEqual(job['status'],'completed',job)
            outputs=job['result']['outputs'];self.assertEqual(len(outputs),9)
            self.assertFalse(job['result']['validation']['vendor_compiler_executed'])
            self.assertEqual(job['inputSha256'],checked['sha256'])
            for result in outputs:
                directory=Path(result['path']).resolve()
                self.assertTrue(directory.is_relative_to(OUTPUT.resolve()))
                self.assertIsNone(result['error'])
                self.assertGreater(result['file_count'],1)
                extension='.pln' if result['platform']=='chroma' else '.prg'
                self.assertTrue(any(p.suffix.lower()==extension for p in directory.rglob('*')))
                if result['cp']=='CP1':
                    programs=[p for p in directory.rglob('*') if p.suffix.lower()==extension]
                    self.assertTrue(any('double trimTar=0.801;' in p.read_text(encoding='utf-8',errors='replace') for p in programs))
            stale={**payload,'changes':[{'sheet':'FLOW','cell':'S4','old':.8,'value':'0.802'}]}
            self.assertEqual(call('/api/save',stale)[0],422)
            self.assertEqual(MASTER.read_bytes(),baseline)
            print(json.dumps({'GUI_HTTP_FULL_GENERATION':'PASS','targets':len(outputs),
                              'files':sum(x['file_count'] for x in outputs),
                              'run_dir':job['result']['run_dir'],'inputSha256':checked['sha256'],
                              'releaseBlockers':sum(len(x['release_blockers']) for x in outputs),
                              'vendorCompiled':False},ensure_ascii=True),flush=True)
        finally:
            service.shutdown();service.server_close();worker.join(timeout=5)


if __name__=='__main__':unittest.main()
