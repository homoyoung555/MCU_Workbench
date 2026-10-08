"""Associations project compiler facts without changing the workbook or plans."""
from dataclasses import replace
from types import SimpleNamespace as NS
import unittest

from program_gen.compiler import ProductCompiler
from program_gen.workbook import WorkbookReader
from gui.workbook_editor import WorkbookEditor
from gui.links import pattern_links
from tests.workspace_paths import FORMAL_MASTER


class SpecializedLinksTests(unittest.TestCase):
    def test_memory_families_show_compiled_configuration_and_generated_resources(self):
        links=pattern_links(self.compiled,self.editor,self.workbook.dataframe('FLOW'),self.workbook)
        for family in ('margin','vt','trimdata_read','trimdata_write'):
            plans=getattr(self.compiled.plan.catalogs,family+'_plans')
            self.assertTrue(plans)
            for plan in plans.values():
                item=next(x for x in links if x['flowRow']==plan.excel_row)
                self.assertTrue(item['details'])
                self.assertTrue(item['resourceSlots'])
                self.assertTrue(any(s['status']=='generated' for s in item['resourceSlots']), (family,item['resourceSlots']))
                if family in ('margin','vt'):
                    self.assertEqual([s['label'] for s in item['stages']],['进入','进入测量模式','扫描与记录' if family=='margin' else '读取与判定'])
                    self.assertEqual({p['name'] for p in item['patterns']},{r.pattern.name for r in (plan.test.enter,plan.test.enter_vt,plan.test.read)})
                    for run in (plan.test.enter_vt,plan.test.read):
                        self.assertTrue(any(s['status']=='generated' and run.pattern.name in s['names']['shared'] for s in item['resourceSlots']))
                    if family=='vt': self.assertTrue(any(l['sheet']=='VERSION' for d in item['details'] for l in d['locations']))
                    else: self.assertIn('生成器固定',item['details'][-1]['text'])
                else:
                    self.assertEqual([s['label'] for s in item['stages']],[s.module for s in plan.steps])
                    self.assertNotIn('PGMOTP',item['unexpanded'])
                    self.assertNotIn('READOTPMAP',item['unexpanded'])
                    self.assertEqual([d['title'] for d in item['details']],[s.module for s in plan.steps])

    def test_dac_mode_pin_resources_match_both_platform_renderers(self):
        from program_gen.platform_program.facts import compile_platform_program_facts
        from program_gen.platforms.chroma.dac_test_renderer import render_dac_test as chroma
        from program_gen.platforms.s100.dac_test_renderer import render_dac_test as s100
        from pathlib import PurePosixPath
        links=pattern_links(self.compiled,self.editor,workbook=self.workbook)
        for plan in self.compiled.plan.catalogs.dac_test_plans.values():
            item=next(x for x in links if x['flowRow']==plan.row+2)
            names={n for s in item['resourceSlots'] for n in s['names']['shared']}
            for platform,render in (('chroma',chroma),('s100',s100)):
                facts=compile_platform_program_facts(self.workbook,NS(platform=platform,cp=plan.cp,variant='production'))
                body=render(plan,'DAC_Test',10,facts)
                expected={PurePosixPath(r.relative_path).stem for r in body.resource_requires}
                self.assertEqual(names,expected)

    def test_dc_groups_expose_real_config_names_on_each_row(self):
        links=pattern_links(self.compiled,self.editor)
        for plan in self.compiled.plan.catalogs.dc_parametric_plans.values():
            for row in plan.excel_rows:
                item=next(x for x in links if x['flowRow']==row)
                self.assertEqual(item['resourceSlots'][0]['names'],{'shared':list(plan.config_patterns)})
                self.assertEqual(len(item['details']),len(plan.phases))
        for plan in self.compiled.plan.catalogs.vih_vil_plans.values():
            for row in plan.excel_rows:
                item=next(x for x in links if x['flowRow']==row)
                names=[n for s in item['resourceSlots'] for n in s['names']['shared']]
                self.assertEqual(names,list(plan.patterns) if hasattr(plan,'patterns') else [v.pattern for v in plan.variants])
                if hasattr(plan,'variants'):
                    self.assertTrue(all(s['status']=='generated' for s in item['resourceSlots']))

    @classmethod
    def setUpClass(cls):
        cls.raw = FORMAL_MASTER.read_bytes()
        cls.editor = WorkbookEditor(cls.raw, 'links.xlsx')
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compiled = ProductCompiler().compile(cls.workbook).require_success()

    def test_all_five_families_have_sources_and_every_group_row_is_selectable(self):
        links = pattern_links(self.compiled, self.editor)
        catalogs = self.compiled.plan.catalogs
        for family in ('opa', 'dac', 'freq', 'adc', 'firmware'):
            plans = getattr(catalogs, family + '_test_plans')
            self.assertTrue(plans, family)
            for plan in plans.values():
                for row in plan.excel_rows:
                    item = next(x for x in links if x['flowRow'] == row)
                    self.assertTrue(item['specialized'])
                    self.assertEqual(item['cp'], plan.cp)
                    self.assertEqual(item['item'], plan.item)
                    self.assertTrue(item['details'])
                    self.assertNotIn('None V',' '.join(d['text'] for d in item['details']))
                    locations = [l for d in item['details'] for l in d['locations']]
                    self.assertTrue(any(l['sheet'] == 'FLOW' for l in locations))
                    if family in ('opa','dac','freq','adc'):
                        self.assertTrue(any(l['sheet'] == family.upper() for l in locations))
                    if family in ('opa','dac','freq'):
                        cards=[d for d in item['details'] if d['title']==family.upper()+' 专表配置']
                        self.assertEqual(len(cards),1)
                        self.assertEqual(len(cards[0]['locations']),1)
                        self.assertFalse(any('测试点 ' in d['title'] for d in item['details']))
                    if family == 'adc':
                        self.assertTrue(any(l['sheet'] == 'IOMUX' for l in locations))
                        self.assertEqual(len([d for d in item['details'] if d['title'].endswith(' 通道配置')]),len(plan.phases))
        self.assertEqual(FORMAL_MASTER.read_bytes(), self.raw)
        self.assertEqual(links, pattern_links(self.compiled, self.editor))

    def test_keil_cases_show_compiled_actions_and_repower_not_swd_resources(self):
        from program_gen.core.run_sequence import LevelSequenceAction, SendCodeAction, WaitAction
        for family in ('opa','dac','freq'):
            plan = next(iter(getattr(self.compiled.plan.catalogs, family+'_test_plans').values()))
            cases = tuple(replace(c, actions=(SendCodeAction('PA0',17),WaitAction(3)),
                                  repower_before=i > 0,
                                  **{('code_pattern' if family=='dac' else 'config_pattern'):None})
                          for i,c in enumerate(plan.cases))
            changes = dict(protocol='keil',cases=cases,entry_actions=(LevelSequenceAction('PA0','HL',5000000),),exit_actions=(WaitAction(7),))
            if family != 'freq': changes['init_pattern']=None
            plan=replace(plan,**changes)
            catalog=NS(trim_specs={},standard_verify_plans={},fbist_pattern_plan=None,
                       **{family+'_test_plans':{plan.row:plan}})
            links=pattern_links(NS(is_valid=True,plan=NS(catalogs=catalog)),self.editor)
            self.assertEqual(len(links),1)
            text=' '.join(d['text'] for d in links[0]['details'])
            for expected in ('PA0','7 ms','重供电','HL','专表'):
                self.assertIn(expected,text)
            self.assertEqual(links[0]['patterns'],[])

    def test_invalid_compilation_never_presents_confirmed_links(self):
        self.assertEqual(pattern_links(NS(is_valid=False),self.editor),[])

    def test_adc_placeholder_slots_follow_each_platform_and_are_not_bound(self):
        links=pattern_links(self.compiled,self.editor)
        adc=next(x for x in links if x['kind']=='ADC_TEST')
        slots=adc['resourceSlots']
        self.assertEqual(len(slots),4)
        config=next(s for s in slots if s['phase']=='ADC1' and s['role']=='config')
        self.assertEqual(config['names'],{'shared':['PT104_SWD_ADC1']})
        capture=next(s for s in slots if s['phase']=='ADC1' and s['role']=='capture')
        self.assertEqual(capture['names'],{'shared':['PT104_ADC1_capture']})
        self.assertTrue(all(s['status']=='placeholder' and not s['configurable'] for s in slots))
        self.assertEqual([s['label'] for s in adc['stages']],['ADC1 · SWD 采集','ADC2 · SWD 采集'])
        self.assertEqual(adc['stages'][0]['patterns'],['PT104_SWD_ADC1','PT104_ADC1_capture'])
        self.assertTrue(set(adc['stages'][0]['details']).isdisjoint(adc['stages'][1]['details']))

    def test_adc_keil_sram_and_digital_show_distinct_capture_and_judge_facts(self):
        from tests.test_adc_keil_variants import AdcKeilVariantTests
        plan=next(iter(self.compiled.plan.catalogs.adc_test_plans.values()))
        phases=(AdcKeilVariantTests._sram_phase(plan.phases[0]),
                AdcKeilVariantTests._digital_phase(plan.phases[1]))
        catalog=NS(trim_specs={},standard_verify_plans={},fbist_pattern_plan=None,
                   adc_test_plans={plan.row:replace(plan,phases=phases)})
        links=pattern_links(NS(is_valid=True,plan=NS(catalogs=catalog)),self.editor)
        self.assertEqual([x['flowRow'] for x in links],list(plan.excel_rows))
        self.assertEqual(links[0]['details'],links[1]['details'])
        text=' '.join(d['text'] for d in links[0]['details'])
        for expected in ('0X3000','22x16@2','PA11=H','PA13=H','KEIL 数字判定'):
            self.assertIn(expected,text)
        self.assertNotIn('SWD 采集',text)
        self.assertEqual(links[0]['resourceSlots'],[])

    def test_check_uses_current_draft_iomux_sources_not_original_editor(self):
        from gui.server import Session
        from gui.specialized_links import _records
        session=Session.__new__(Session)
        session.editor=self.editor;session.checked=None
        rows=list(_records(self.editor,'IOMUX'))
        source=next((r,v) for r,v in rows if 'ADC12_IN0' in v.get('analog',''))
        destination=next((r,v) for r,v in rows if v.get('pin')=='PA03')
        changes=[{'sheet':'IOMUX','cell':f'B{source[0]}','old':source[1]['analog'],'value':destination[1]['analog']},
                 {'sheet':'IOMUX','cell':f'B{destination[0]}','old':destination[1]['analog'],'value':source[1]['analog']}]
        result=session.check({'baseSha256':self.editor.sha256,'changes':changes})
        self.assertTrue(result['valid'],result['diagnostics'])
        adc=next(x for x in result['links'] if x['kind']=='ADC_TEST')
        channel=next(d for d in adc['details'] if d['title']=='ADC1 通道配置')
        self.assertIn({'sheet':'IOMUX','coordinate':f'B{destination[0]}','label':f'查看 IOMUX!B{destination[0]}'},channel['locations'])
        self.assertFalse(any(l['sheet']=='IOMUX' and l['coordinate']==f'B{source[0]}' for l in channel['locations']))
