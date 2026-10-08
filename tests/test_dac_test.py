from dataclasses import FrozenInstanceError, replace
import unittest

from program_gen.compiler import ProductCompiler
from program_gen.core.dac_test import DacTestPlan
from program_gen.platform_program import PlatformProgramBuilder, ProgramAssemblyInput, WorkspacePatternProducer
from program_gen.platform_program.facts import compile_platform_program_facts
from program_gen.platforms.chroma.dac_test_renderer import render_dac_test as render_chroma
from program_gen.platforms.s100.dac_test_renderer import render_dac_test as render_s100
from program_gen.registered_typed_kinds import NATIVE_TYPED_KIND_REGISTRY
from program_gen.render_plan import TargetKey
from program_gen.typed_kind_registry import TypedKindContext
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER, WORKSPACE_ROOT


class DacTestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook=WorkbookReader().read(FORMAL_MASTER)
        cls.compilation=ProductCompiler().compile(cls.workbook).require_success()
        cls.plan=cls.compilation.plan.catalogs.dac_test_plans[198]

    def test_formal_sheet_compiles_three_modes_and_thirty_three_points(self):
        self.assertIsInstance(self.plan,DacTestPlan)
        self.assertEqual(len(self.plan.cases),33)
        self.assertEqual(tuple(dict.fromkeys(case.mode for case in self.plan.cases)),("BUFFOFF","BUFFON","VREF2P9"))
        self.assertEqual((self.plan.cases[0].code,self.plan.cases[-1].code),("001","E92"))
        self.assertAlmostEqual(self.plan.cases[-1].target,2.640869140625)
        with self.assertRaises(FrozenInstanceError): self.plan.item="x"

    def test_cp3_bonding_selects_only_pa7_dac_output(self):
        for platform in ("chroma","s100"):
            facts=compile_platform_program_facts(self.workbook,TargetKey(platform,"CP3","lab","X"))
            self.assertEqual(tuple(pin.name for pin in facts.pin_groups.dac_out),("PA7",))

    def test_swd_renderers_loop_each_mode_code_set(self):
        for platform, renderer in (("chroma", render_chroma), ("s100", render_s100)):
            facts = compile_platform_program_facts(
                self.workbook, TargetKey(platform, "CP3", "lab", "DAC_LOOP")
            )
            rendered = renderer(self.plan, "Dac_Test", 12, facts)
            body = rendered.content
            self.assertIn(
                'char dac_buffoff_code[13][4]={"001","002","004"', body
            )
            self.assertEqual(body.count("for(int c=0;c<"), 3)
            self.assertEqual(len(rendered.resource_requires), 20)
            if platform == "chroma":
                self.assertIn("double dac_buffoff_down[13]={-0.009,-0.008", body)
                self.assertEqual(body.count("JUDGE_V_PPMU(PA7,"), 3)
                self.assertIn(
                    'sprintf(dac_log,"DAC_BUFFOFF_PA7_%s_Verify",'
                    "dac_buffoff_code[c]);",
                    body,
                )
                self.assertIn("JUDGE_PAT(S:dac_st,S:dac_sp);", body)
            else:
                self.assertNotIn("double dac_buffoff_down", body)
                self.assertNotIn("DOWN_LIMIT=dac_buffoff_down[c]", body)
                self.assertIn("DOWN_LIMIT=-0.009V,UP_LIMIT=0.011V", body)
                self.assertEqual(body.count("switch(c)"), 3)
                self.assertEqual(body.count("LOGIC_PPMU_MV(PA7,"), 33)
                self.assertIn(
                    'sprintf(_C_dac_st,"PT104_DAC_CODE_%s:START",'
                    "dac_buffoff_code[c]);",
                    body,
                )
                self.assertEqual(body.count("RUN_PATTERN(_C_dac_st,_C_dac_sp"), 3)
                self.assertIn("LOG_ALIAS=DAC_BUFFOFF_PA7_001_Verify", body)

    def test_repower_keeps_the_literal_safe_path(self):
        cases = list(self.plan.cases)
        cases[1] = replace(cases[1], repower_before=True)
        plan = replace(self.plan, cases=tuple(cases))
        for platform, renderer in (("chroma", render_chroma), ("s100", render_s100)):
            facts = compile_platform_program_facts(
                self.workbook, TargetKey(platform, "CP3", "lab", "DAC_LITERAL")
            )
            self.assertNotIn(
                "for(int c=", renderer(plan, "Dac_Test", 12, facts).content
            )

    def test_registered_slice_closes_with_twenty_unique_stubs(self):
        self.assertIn("DAC_TEST",NATIVE_TYPED_KIND_REGISTRY.registered_kinds)
        for platform in ("chroma","s100"):
            target=TargetKey(platform,"CP3","lab",f"DAC_{platform}")
            facts=compile_platform_program_facts(self.workbook,target)
            producer=WorkspacePatternProducer(WORKSPACE_ROOT/"input"/platform)
            assembly=NATIVE_TYPED_KIND_REGISTRY.compile("DAC_TEST",(self.plan,),TypedKindContext(self.compilation,target,facts,producer))
            rendered=PlatformProgramBuilder(producer).build(ProgramAssemblyInput(target,facts,self.compilation.for_cp("CP3").canonical_schedule,assembly.contributions,assembly.bodies))
            program=rendered.artifact(target.program_name+(".pln" if platform=="chroma" else ".prg")).content
            self.assertIn(b"Dac_Test",program); self.assertIn(b"PA7",program)
            self.assertEqual(sum(b"STUB: no real DAC SWD configuration vector" in artifact.content for artifact in rendered.artifacts),20)
            if platform == "s100":
                self.assertIsNotNone(rendered.artifact("PT104_DAC_BUFFOFF_PA7_Test.sd"))
                project = rendered.artifact(target.program_name + ".prj").content
                self.assertIn(b"PT104_DAC_BUFFOFF_PA7_Test.sd", project)


if __name__=="__main__": unittest.main()
