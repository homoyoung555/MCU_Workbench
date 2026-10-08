"""Actual GUI row handlers -> HTTP -> preserved workbook -> both platform programs."""
import json
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import openpyxl
from gui.server import make_server, MASTER
from gui.workbook_editor import sha


class GuiRowIntegrationTests(unittest.TestCase):
    def test_added_pvd_row_reaches_both_programs(self):
        self.run_copy('row')

    def test_complete_power_group_reaches_both_programs(self):
        self.run_copy('group')

    def run_copy(self, mode):
        item='GUI_Power_Group_Copy' if mode=='group' else 'GUI_Row_Verify'
        symbol='Gui_Power_Group_Copy' if mode=='group' else 'Gui_Row_Verify'
        sources=[191,192,193] if mode=='group' else [201]
        original=MASTER.read_bytes()
        service=make_server(0)
        worker=threading.Thread(target=service.serve_forever,daemon=True);worker.start()

        def call(path,body=None):
            request=Request(service.origin+path,
                            headers={'Origin':service.origin,'X-GUI-Session':service.token,'Content-Type':'application/json'},
                            data=None if body is None else json.dumps(body).encode())
            try:
                with urlopen(request,timeout=90) as response:return response.status,json.load(response)
            except HTTPError as error:return error.code,json.load(error)

        try:
            _,state=call('/api/state')
            if mode=='group':
                g=next(g for g in state['groups'] if 192 in g['rows'])
                self.assertEqual(g['rows'],sources)
                self.assertEqual(g['kind'],'FIRMWARE_RUN_TEST')
                state['testOrigin']=service.origin;state['testToken']=service.token
            with tempfile.TemporaryDirectory(prefix='gui-append-') as folder:
                state_path=Path(folder)/'state.json';draft_path=Path(folder)/'draft.json'
                state_path.write_text(json.dumps(state),encoding='utf-8')
                script=Path(__file__).with_name('test_gui_ui.cjs')
                result=subprocess.run([shutil.which('node') or r'C:\Program Files\nodejs\node.exe',
                                       str(script),str(state_path),str(draft_path),mode],capture_output=True,text=True,encoding='utf-8')
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                draft=json.loads(draft_path.read_text(encoding='utf-8'))
            self.assertEqual(draft['appendRows'],[{'sheet':'FLOW','sourceRow':r,'copy':True} for r in sources])
            if mode=='group':
                status,checked=200,draft.pop('_checkedResult')
                copied=next(g for g in checked['groups'] if g['item']==item)
                self.assertEqual(copied['rows'],[208,209,210])
                self.assertEqual(copied['subs'],['stop0','stop1','standby'])
                self.assertEqual(copied['kind'],'FIRMWARE_RUN_TEST')
            else:status,checked=call('/api/check',draft)
            self.assertEqual(status,200,checked);self.assertTrue(checked['valid'],checked)
            self.assertEqual(checked['appendCount'],len(sources));self.assertEqual(checked['errors'],0)
            payload={**draft,'checkId':checked['checkId']}
            self.assertEqual(call('/api/save',{**payload,'appendRows':[]})[0],422)
            status,saved=call('/api/save',payload);self.assertEqual(status,200,saved)
            raw=Path(saved['path']).read_bytes();self.assertEqual(sha(raw),checked['sha256'])
            workbook=openpyxl.load_workbook(saved['path'],data_only=True)
            try:
                self.assertEqual(workbook['FLOW'].max_row,207+len(sources))
                for offset,source in enumerate(sources,208):
                    self.assertEqual(workbook['FLOW'][f'B{offset}'].value,item)
                    self.assertEqual(workbook['FLOW'][f'D{offset}'].value,workbook['FLOW'][f'D{source}'].value)
                    self.assertEqual(workbook['FLOW'][f'B{offset}'].style_id,workbook['FLOW'][f'B{source}'].style_id)
                self.assertEqual(workbook['FLOW']['B201'].value,'Pvd_Test')
                if mode=='group':self.assertEqual(workbook['FLOW']['B191'].value,'Power_Test')
            finally:workbook.close()
            targets=[t['id'] for t in checked['targets'] if t['cp']=='CP3' and t['variant']=='lab']
            self.assertEqual(len(targets),2)
            status,started=call('/api/generate',{**payload,'targets':targets,'validate':False})
            self.assertEqual(status,200,started)
            deadline=time.monotonic()+180
            while True:
                _,job=call('/api/job?id='+started['jobId'])
                if job['status']!='running':break
                if time.monotonic()>deadline:self.fail('Timed out waiting for row generation')
                time.sleep(.25)
            self.assertEqual(job['status'],'completed',job)
            self.assertEqual(job['inputSha256'],checked['sha256'])
            outputs=job['result']['outputs'];self.assertEqual(len(outputs),2)
            evidence=[]
            for output in outputs:
                self.assertIsNone(output['error'])
                ext='.pln' if output['platform']=='chroma' else '.prg'
                programs=[p for p in Path(output['path']).rglob('*') if p.suffix.lower()==ext]
                matches=[(p,p.read_bytes().decode('utf-8',errors='replace')) for p in programs]
                body_marker=symbol+'()' if ext=='.pln' else '@@PLAN '+symbol
                call_pattern=re.escape(symbol)+(r'\s+\?' if ext=='.pln' else r';\s*// SBin')
                self.assertTrue(any(body_marker in text and re.search(call_pattern,text) for _,text in matches),[str(p) for p in programs])
                evidence.extend(str(p) for p,text in matches if symbol in text)
            self.assertEqual(MASTER.read_bytes(),original)
            print(json.dumps({'GUI_HTTP_GENERATION':'PASS','mode':mode,'sourceRows':sources,'addedRows':list(range(208,208+len(sources))),
                              'saved':saved['path'],'programs':evidence,'run_dir':job['result']['run_dir'],
                              'files':sum(x['file_count'] for x in outputs),'vendorCompiled':False},ensure_ascii=True),flush=True)
        finally:
            service.shutdown();service.server_close();worker.join(timeout=5)


if __name__=='__main__':unittest.main()
