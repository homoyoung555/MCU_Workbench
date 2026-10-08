"""Read-only result browsing, using the real local HTTP boundary."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from gui.server import Session, make_server


class OutputViewerTests(unittest.TestCase):
    def test_job_bound_files_preview_and_access_guards(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); run=base/'run'; root=run/'review'/'chroma'; root.mkdir(parents=True)
            (root/'main.pln').write_bytes(b'void GUI_Test() {}\n')
            (root/'pins.dec').write_bytes('引脚配置'.encode('gb18030'))
            (root/'large.pat').write_bytes(b'A'*(512*1024+10))
            (root/'image.bin').write_bytes(b'\x00secret')
            (run/'input.xlsx').write_bytes(b'private workbook')
            s=object.__new__(Session); s.output=base
            s.job={'id':'test-job','status':'completed','inputSha256':'snapshot',
                   'result':{'run_dir':str(run),'outputs':[{'id':'chroma','path':str(root),'error':None}]}}
            server=make_server(0,s); thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
            def get(query,token=True):
                headers={'X-GUI-Session':server.token} if token else {}
                return json.load(urlopen(Request(server.origin+'/api/output?'+query,headers=headers),timeout=5))
            try:
                result=get('id=test-job&target=0')
                self.assertEqual(result['inputSha256'],'snapshot')
                self.assertEqual({f['path'] for f in result['files']},{'main.pln','pins.dec','large.pat','image.bin'})
                self.assertEqual(get('id=test-job&target=0&file=main.pln')['text'],'void GUI_Test() {}\n')
                self.assertEqual(get('id=test-job&target=0&file=pins.dec')['text'],'引脚配置')
                self.assertTrue(get('id=test-job&target=0&file=large.pat')['truncated'])
                for query in ['id=old&target=0','id=test-job&target=-1','id=test-job&target=0&file=../input.xlsx',
                              'id=test-job&target=0&file=image.bin','id=test-job&target=0&file=missing.pln']:
                    with self.assertRaises(HTTPError) as error: get(query)
                    self.assertEqual(error.exception.code,422)
                with self.assertRaises(HTTPError) as error: get('id=test-job&target=0',False)
                self.assertEqual(error.exception.code,403)
                s.job['status']='running'
                with self.assertRaises(HTTPError) as error: get('id=test-job&target=0')
                self.assertEqual(error.exception.code,422)
                s.job['status']='completed'; s.job['result']['outputs'][0]['path']=str(base)
                with self.assertRaises(HTTPError) as error: get('id=test-job&target=0')
                self.assertEqual(error.exception.code,422)
            finally:
                server.shutdown();server.server_close();thread.join()
