"""Pin checks validate their own dependencies and cannot authorize program output."""
import unittest
import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch
from gui.server import Session, generation_key, make_server


class PinCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = Session()

    def payload(self):
        s = self.session
        target = next(t for t in s.state()['pinTargets'] if t['platform']=='s100' and t['cp']=='CP3' and t['variant']=='lab')
        old = s.editor.by_name['FLOW']['rows'][3][1]['value']
        return {'baseSha256':s.editor.sha256,'changes':[{'sheet':'FLOW','cell':'B4','old':old,'value':'GUI_Unfinished_FLOW'}],
                'appendRows':[],'scope':'pin','targets':[target['id']]}

    def test_pin_check_ignores_broken_flow_and_binds_scope_and_targets(self):
        s=self.session;p=self.payload()
        self.assertFalse(s.check({**p,'scope':'program'})['valid'])
        with patch('gui.server.ProductCompiler.compile',side_effect=AssertionError('Pin must not compile FLOW')):
            result=s.check(p)
        self.assertTrue(result['valid'],result)
        self.assertEqual(result['scope'],'pin')
        self.assertEqual(result['checkedTargets'],p['targets'])
        self.assertIsNone(s.checked['compilation'])
        checked={**p,'checkId':result['checkId']}
        with self.assertRaisesRegex(ValueError,'范围|整本|Pin'):
            s.save(checked)
        with self.assertRaisesRegex(ValueError,'范围|整本|Pin'):
            s.generate({**checked,'scope':'program'})
        with self.assertRaises(ValueError):
            s.generate({**checked,'targets':['another-target']})
        with self.assertRaises(ValueError):
            s.generate({**checked,'changes':[]})

    def test_invalid_pin_is_a_scoped_diagnostic_and_clears_previous_success(self):
        s=self.session;p=self.payload()
        with patch('gui.server.ProductCompiler.compile',side_effect=AssertionError('Pin must not compile FLOW')):
            with patch('gui.generation.compile_pin_map_facts',side_effect=ValueError('STN.PIN.SITE_MISSING: missing Site 2')):
                result=s.check(p)
        self.assertFalse(result['valid']);self.assertIsNone(s.checked)
        self.assertEqual(result['diagnostics'][0]['provenance']['sheet'],'PIN DEC SINGEL')
        self.assertIn('Site 2',result['diagnostics'][0]['message'])

    def test_running_pin_job_retry_uses_the_same_scope_key(self):
        s=self.session;p=self.payload()
        result=s.check(p)
        request={**p,'checkId':result['checkId']}
        s.job={'id':'running-pin-check-test','status':'running','requestKey':generation_key(request)}
        server=make_server(0,s)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        def post(payload):
            return urlopen(Request(server.origin+'/api/generate',data=json.dumps(payload).encode(),
                           headers={'Content-Type':'application/json','Origin':server.origin,
                                    'X-GUI-Session':server.token}),timeout=10)
        try:
            with post(request) as response:
                self.assertEqual(json.load(response)['jobId'],s.job['id'])
            with self.assertRaises(HTTPError) as error:
                post({**request,'scope':'program'})
            self.assertEqual(error.exception.code,409)
        finally:
            s.job=None
            server.shutdown();server.server_close();thread.join()

    def test_loading_unfinished_flow_preserves_pin_target_choices(self):
        s=self.session;p=self.payload()
        raw=s.editor.apply(p['baseSha256'],p['changes'],[])
        # Use an independent session so other tests retain the original workbook.
        loaded=Session.__new__(Session)
        loaded.output=s.output;loaded.job=None
        state=loaded.load(raw,'unfinished-flow.xlsx')
        self.assertEqual(state['targets'],[])
        self.assertTrue(any(t['id']==p['targets'][0] for t in state['pinTargets']))
        result=loaded.check({'baseSha256':state['sha256'],'changes':[],
                             'scope':'pin','targets':p['targets']})
        self.assertTrue(result['valid'],result)
