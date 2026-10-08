"""Navigation follows compiled references and write provenance, not item spelling."""
from types import SimpleNamespace as NS
import unittest
from gui.links import pattern_links


class TrimLinksTests(unittest.TestCase):
    def test_read_write_rows_are_available_alongside_verify(self):
        import pandas as pd
        def spec(row):
            return NS(excel_row=row,cp='CP1',item='x',steps=[NS(module='RUN',module_plan=NS(pattern=NS(name='P')))])
        catalogs=NS(trim_specs={},standard_verify_plans={},fbist_pattern_plan=None,main_plans={i:spec(i+2) for i in range(4)})
        flow=pd.DataFrame([{'type':t} for t in ('read','WRITE','wirte','verify')])
        links=pattern_links(NS(is_valid=True,plan=NS(catalogs=catalogs)),NS(by_name={}),flow)
        self.assertEqual([x['flowRow'] for x in links],[2,3,4,5])

    def test_run_only_main_exposes_resource_interface_and_generated_source(self):
        generated=NS(pattern_name='local',writes=[])
        spec=NS(excel_row=2,cp='CP1',item='run_only',steps=[
            NS(module='RUN',module_plan=NS(pattern=NS(name=name))) for name in ('external','local')])
        catalogs=NS(trim_specs={},standard_verify_plans={},main_plans={0:spec},
                    fbist_pattern_plan=NS(patterns=[generated]))
        links=pattern_links(NS(is_valid=True,plan=NS(catalogs=catalogs)),NS(by_name={}))
        self.assertEqual(len(links),1)
        slots=links[0]['resourceSlots']
        self.assertEqual([s['names'] for s in slots],[{'shared':['external']},{'shared':['local']}])
        self.assertEqual([s['status'] for s in slots],['referenced','generated'])
        self.assertTrue(all(not s['configurable'] for s in slots))

    def test_compiled_buildmap_keeps_configured_field_even_when_flags_are_off(self):
        from gui.links import _storage_details
        fields=[NS(page='trim0',register='R',name=name,lsb=lsb,width=4,source='description',
                   register_layout=NS(row_index=0)) for name,lsb in [('used',0),('unused',4)]]
        write=NS(field='used',symbol='ADS_DAC_FINAL',lsb=0,width=4)
        register=NS(page='trim0',register='R',writes=[write],terms=[NS(lsb=0,symbol=write.symbol)])
        consumer=NS(cp='CP1',excel_row=36,steps=[NS(module='BUILDMAP',module_plan=NS(registers=[register]))])
        catalog=NS(addr_map=NS(selected_storage_fields=lambda kind,item:fields,storage_fields=fields,registers=[]),flash_window_plans={34:consumer})
        spec=NS(cp='CP1',item='ads',dac_final_symbol=write.symbol);editor=NS(by_name={})
        def details(): return _storage_details(2,spec,catalog,editor,enabled=set())
        result=details()
        self.assertEqual([d['storageMapping']['field'] for d in result if d.get('storageMapping')],['used'])
        self.assertTrue(any('BUILDMAP' in d.get('summary','') for d in result))
        for cp,row,symbol in [('CP2',36,'ADS_DAC_FINAL'),('CP1',1,'ADS_DAC_FINAL'),('CP1',36,'OTHER')]:
            consumer.cp=cp;consumer.excel_row=row;write.symbol=symbol
            self.assertFalse(any(d.get('storageMapping') for d in details()))

    def test_current_row_flags_filter_uid_and_otp_independently(self):
        from gui.links import _configured_storage_details
        fields=[NS(page=page,register='REG',name=page,lsb=0,width=4,source='description',
                   register_layout=NS(row_index=0)) for page in ('uid','trim1')]
        catalog=NS(addr_map=NS(selected_storage_fields=lambda kind,item:fields))
        spec=NS(cp='CP2',item='Example');editor=NS(by_name={'ADDR_MAP':{'maxRow':2,'columns':[]}})
        for kind in ('TRIM','VERIFY'):
            for enabled,expected in ((set(),[]),({'UID'},['uid']),({'OTP'},['trim1']),({'UID','OTP'},['uid','trim1'])):
                details=_configured_storage_details(spec,catalog,editor,kind,enabled)
                self.assertEqual([d['storageMapping']['page'] for d in details],expected)
        import pandas as pd
        spec.excel_row=2;spec.steps=();spec.shmoo=None;spec.protocol_enter=None;spec.protocol_exit=None
        catalog.trim_specs={};catalog.standard_verify_plans={0:spec};catalog.fbist_pattern_plan=None
        compiled=NS(is_valid=True,plan=NS(catalogs=catalog))
        draft=pd.DataFrame([{'UID':'YES','OTP':'no'}])
        details=pattern_links(compiled,editor,draft)[0]['details']
        self.assertEqual([d['storageMapping']['page'] for d in details if d.get('storageMapping')],['uid'])
        draft.loc[0,'UID']='no'
        details=pattern_links(compiled,editor,draft)[0]['details']
        self.assertFalse(any(d.get('storageMapping') for d in details))
        self.assertIn('未启用',details[0]['summary'])

    def test_trim_storage_uses_compiled_writes_and_exact_catalog_provenance(self):
        spec=NS(cp='CP1',item='UnrelatedDisplayName',dac_final_symbol='A_DAC_FINAL')
        write=NS(field='DifferentFieldName',symbol='A_DAC_FINAL',lsb=4,width=3)
        reg=NS(page='trim0',register='REG_A',writes=[write],terms=[NS(lsb=4,symbol='A_DAC_FINAL')])
        window=NS(cp='CP1',excel_row=30,steps=[NS(module='BUILDMAP',module_plan=NS(registers=[reg]))])
        catalog=NS(flash_window_plans={28:window},addr_map=NS(registers=[NS(page='trim0',register='REG_A',row_index=8)]))
        editor=NS(by_name={'ADDR_MAP':{'maxRow':20,'columns':[{'label':'CP addr map'}]},'FLOW':{'maxRow':40,'columns':[]}})
        spec.operations=[];spec.search=NS(per_point_actions=[]);spec.protocol=NS(enter_pattern=None,exit_pattern=None)
        catalog.trim_specs={2:spec};catalog.standard_verify_plans={};catalog.fbist_pattern_plan=None
        def details_for():
            return pattern_links(NS(is_valid=True,plan=NS(catalogs=catalog)),editor)[0]['details']
        details=details_for()
        self.assertIn('A_DAC_FINAL',details[0]['text']);self.assertIn('REG_A[6:4]',details[0]['text'])
        self.assertIn('trim0',details[0]['text']);self.assertIn('3 bit',details[0]['text'])
        self.assertEqual(details[0]['locations'][0]['coordinate'],'A10')
        window.cp='CP2';self.assertIn('未解析',details_for()[0]['text'])
        window.cp='CP1';reg.terms[0].symbol='OTHER';self.assertIn('未解析',details_for()[0]['text'])
        commit=NS(field='ExplicitField',page='trim1',register='REG_B',lsb=0,width=4,value=NS(kind='VARIABLE',token='A_DAC_FINAL'))
        catalog.persistence=NS(rows={30:NS(cp='CP1',excel_row=32,operations=[NS(module='COMMIT',field_writes=[commit])])})
        details=details_for();self.assertIn('REG_B[3:0]',details[0]['text']);self.assertIn('来源坐标未解析',details[0]['text'])
        self.assertFalse(any(l['sheet']=='ADDR_MAP' for l in details[0]['locations']))
        commit.value.kind='LITERAL';self.assertIn('未解析',details_for()[0]['text'])
        physical=NS(page='uid',register='REG_UID',name='ConfiguredField',lsb=0,width=6,
                    source='description',register_layout=NS(row_index=9))
        catalog.addr_map.selected_storage_fields=lambda kind,item:(physical,)
        details=details_for()
        self.assertEqual(details[0]['storageMapping'],{'page':'uid','register':'REG_UID','field':'ConfiguredField'})
        self.assertIn('已配置',details[0]['summary'])
        self.assertEqual(details[0]['locations'][0]['coordinate'],'row 11')
        self.assertIn('尚未确认',details[-1]['summary'])
        catalog.addr_map.selected_storage_fields=lambda kind,item:()
        self.assertFalse(any(d.get('storageMapping') for d in details_for()))


    def test_adjust_details_follow_compiled_condition_and_dac_source(self):
        from program_gen.native_target_renderer import NativeTargetRenderer  # Same initialization order as the GUI.
        from tests.test_dac_adjust_typed_kind import DacAdjustTypedKindTests, _fbist_plan
        for producer,source_text in ((0,'本CP的TRIM结果'),(3,'寄存器恢复值')):
            plan=DacAdjustTypedKindTests()._compile_action(target_producer_row=producer)
            catalog=NS(trim_specs={},standard_verify_plans={},fbist_pattern_plan=_fbist_plan(),dac_adjust_plans={1:plan})
            editor=NS(by_name={'FLOW':{'columns':[{'label':'item'},{'label':'Recipe'}],'maxRow':20}})
            links=pattern_links(NS(is_valid=True,plan=NS(catalogs=catalog)),editor)
            self.assertEqual(len(links),1)
            self.assertEqual(links[0]['kind'],'DAC_ADJUST')
            details=links[0]['details'];self.assertIn('A_EXPORT < 0.4 V',details[0]['text'])
            self.assertIn('码表',details[0]['text']);self.assertIn(source_text,details[0]['text'])
            self.assertEqual(details[0]['locations'][0]['coordinate'],'B3')
            self.assertIn('不执行',details[1]['text'])
            self.assertIn('VPOSE_DAC_FINAL',details[1]['text'])
            self.assertIn('set_all_final_vposp',[p['name'] for p in links[0]['patterns']])
            self.assertEqual(links[0]['unexpanded'],[])

    def test_setvposp_aggregate_uses_generated_sources_not_old_fixed_block(self):
        run=NS(pattern=NS(name='aggregate'))
        setvposp=NS(updates=[],should_run=True,run_pattern=run)
        spec=NS(excel_row=50,cp='CP2',item='Window',steps=[NS(module='SETVPOSP',module_plan=setvposp)])
        aggregate=NS(pattern_name='aggregate',writes=[NS(source_rows=(14,24),addr_bits='0000001',data_bits='0'*16,fields=[])])
        catalogs=NS(trim_specs={},standard_verify_plans={},flash_window_plans={48:spec},fbist_pattern_plan=NS(patterns=[],pump_aggregate=aggregate))
        editor=NS(by_name={'pattern':{'columns':[{'label':'description'}],'maxRow':250}})
        links=pattern_links(NS(is_valid=True,plan=NS(catalogs=catalogs)),editor)
        self.assertEqual([l['coordinate'] for l in links[0]['patterns'][0]['locations']],['A14','A24'])
        self.assertIn('执行',links[0]['details'][0]['text'])
        setvposp.should_run=False
        links=pattern_links(NS(is_valid=True,plan=NS(catalogs=catalogs)),editor)
        self.assertEqual(links[0]['patterns'],[])
        self.assertIn('无需',links[0]['details'][0]['text'])

    def test_verify_uses_typed_patterns_and_deduplicates_shmoo_rows(self):
        resource=lambda name:NS(pattern=NS(name=name))
        step=lambda module,plan:NS(module=module,module_plan=plan)
        steps=[step('ENTER',resource('shared')),step('RUN',resource('shared')),
               step('JUDGE',NS(pe_window=NS(before=resource('pe'),after=resource('pe')))),
               step('DAC_WRITE',NS(target=resource('dac'))),
               step('COMMIT',NS(writes=[],targets=[NS(program_pattern='program',read_pattern='read')],
                                field_values=[NS(program_pattern='program',read_pattern='read',value=NS(token='RESULT'),field='RESULT')])),
               step('EXPORT',NS()),step('DAC_ADJ',None),step('SETVPOSP',None)]
        verify=NS(excel_row=40,cp='CP2',item='NOT_A_PATTERN_NAME',steps=steps,
                  protocol_enter=resource('protocol'),protocol_exit=None,
                  shmoo=NS(points=[NS(excel_row=40,steps=steps),NS(excel_row=40,steps=steps),
                                       NS(excel_row=41,steps=[step('ENTER',resource('second'))])]))
        catalog=NS(trim_specs={},standard_verify_plans={38:verify},fbist_pattern_plan=None)
        links=pattern_links(NS(is_valid=True,plan=NS(catalogs=catalog)),NS(by_name={}))
        self.assertEqual([x['flowRow'] for x in links],[40,41])
        self.assertEqual(links[0]['kind'],'VERIFY')
        refs={p['name']:p for p in links[0]['patterns']}
        self.assertEqual(set(refs),{'shared','pe','dac','program','read','protocol'})
        self.assertEqual(refs['shared']['uses'],['ENTER','RUN'])
        self.assertEqual(refs['pe']['uses'],['JUDGE_WINDOW'])
        self.assertEqual(links[0]['unexpanded'],['DAC_ADJ','SETVPOSP'])
        self.assertEqual([p['name'] for p in links[1]['patterns']],['second','protocol'])

    def test_reference_to_write_rows_and_deduplicated_uses(self):
        spec=NS(cp='CP1',item='TRIM_NAME',operations=[NS(kind='ENTER',reference='actual_entry'),NS(kind='TRIM',reference='actual_dac')],
                search=NS(per_point_actions=[NS(kind='SET_DAC',reference='actual_dac')]),
                protocol=NS(enter_pattern='protocol',exit_pattern='unmapped_exit'))
        write=lambda rows:NS(source_rows=rows,addr_bits='0010010',data_bits='0000000000000011',fields=[NS(field_name='DAC[3:0]',bit_hi=3,bit_lo=0,value='0011*',dynamic=True)])
        patterns=[NS(pattern_name='actual_entry',writes=[write((7,9))]),NS(pattern_name='actual_dac',writes=[write((11,))]),NS(pattern_name='unused_same_item',writes=[write((20,))])]
        compiled=NS(is_valid=True,plan=NS(catalogs=NS(trim_specs={2:spec},standard_verify_plans={},fbist_pattern_plan=NS(patterns=patterns))))
        editor=NS(by_name={'pattern':{'columns':[{'label':'item'},{'label':'description'}],'maxRow':30}})
        links=pattern_links(compiled,editor);self.assertEqual(links[0]['flowRow'],4)
        refs={p['name']:p for p in links[0]['patterns']}
        self.assertNotIn('unused_same_item',refs)
        self.assertEqual([l['coordinate'] for l in refs['actual_entry']['locations']],['B7','B9'])
        self.assertEqual(refs['actual_dac']['uses'],['TRIM','SET_DAC'])
        preview=refs['actual_dac']['preview'][0]
        self.assertEqual(preview['address'],'0010010')
        self.assertEqual(preview['fields'][0],{'name':'DAC[3:0]','high':3,'low':0,'value':'0011','dynamic':True})
        self.assertEqual(refs['unmapped_exit']['locations'],[])
        self.assertTrue(refs['unmapped_exit']['note'])
        editor.by_name['pattern']['columns']=[]
        self.assertEqual(pattern_links(compiled,editor)[0]['patterns'][0]['locations'][0]['coordinate'],'row 7')

    def test_invalid_compilation_never_reuses_old_links(self):
        self.assertEqual(pattern_links(NS(is_valid=False),NS()),[])


class RealTrimLinkTests(unittest.TestCase):
    def test_page_navigation_edits_real_dac_pattern_and_rechecks(self):
        import json
        from pathlib import Path
        import tempfile
        import subprocess
        import threading
        from gui.server import Session, make_server, MASTER
        original=MASTER.read_bytes()
        session=Session()
        server=make_server(0,session);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            from gui.generation import preview_plan
            compilation=session.item_cache['compilation'];workbook=session.item_cache['workbook']
            mapped=[x for x in session.links if x['kind']=='TRIM' and any(l['sheet']=='ADDR_MAP' for d in x['details'] for l in d['locations'])]
            self.assertTrue(mapped)
            print('REAL_STORAGE_LINK',json.dumps(mapped[0],ensure_ascii=True))
            for platform in ('chroma','s100'):
                target=next(t['id'] for t in session.targets if t['platform']==platform and t['cp']=='CP1' and t['variant']=='lab')
                before=preview_plan(workbook,compilation,target)
                self.assertEqual(pattern_links(compilation,session.editor,workbook.dataframe('FLOW'),workbook),session.links)
                after=preview_plan(workbook,compilation,target)
                self.assertEqual([(a.relative_path,a.content) for a in before.artifacts],[(a.relative_path,a.content) for a in after.artifacts])
                print('STORAGE_READ_ONLY',platform,len(before.artifacts))
            state=session.state();state['testOrigin']=server.origin;state['testToken']=server.token
            self.assertEqual(sum(x['kind']=='TRIM' for x in state['links']),35)
            self.assertGreater(sum(x['kind']=='VERIFY' for x in state['links']),0)
            with tempfile.TemporaryDirectory(prefix='gui-trim-links-') as tmp:
                state_path=Path(tmp)/'state.json';result_path=Path(tmp)/'result.json'
                state_path.write_text(json.dumps(state),encoding='utf-8')
                done=subprocess.run(['node','tests/test_gui_ui.cjs',str(state_path),str(result_path),'links'],capture_output=True,text=True,encoding='utf-8')
                self.assertEqual(done.returncode,0,done.stdout+'\n'+done.stderr)
                evidence=json.loads(result_path.read_text(encoding='utf-8'))
                compiled=session.checked['compilation']
                self.assertEqual(compiled.plan.catalogs.trim_specs[2].dac.default_value,evidence['bits'])
                self.assertEqual(len(evidence['changes']),1)
                self.assertEqual(MASTER.read_bytes(),original)
                print('REAL_TRIM_LINK',json.dumps(evidence,ensure_ascii=True))
                print(done.stdout.splitlines()[-1])
        finally:
            server.shutdown();server.server_close();thread.join()
