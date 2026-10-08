from dataclasses import FrozenInstanceError, replace
import unittest

from program_gen.compiler import ProductCompiler
from program_gen.core.opa_test import OpaTestPlan
from program_gen.platform_program import PlatformProgramBuilder, ProgramAssemblyInput, WorkspacePatternProducer
from program_gen.platform_program.facts import compile_platform_program_facts
from program_gen.platforms.chroma.opa_test_renderer import render_opa_test as render_chroma
from program_gen.platforms.s100.opa_test_renderer import render_opa_test as render_s100
from program_gen.registered_typed_kinds import NATIVE_TYPED_KIND_REGISTRY
from program_gen.render_plan import TargetKey
from program_gen.typed_kind_registry import TypedKindContext
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER, WORKSPACE_ROOT


class OpaTestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook=WorkbookReader().read(FORMAL_MASTER)
        cls.compilation=ProductCompiler().compile(cls.workbook).require_success()
        cls.plan=cls.compilation.plan.catalogs.opa_test_plans[197]

    def test_formal_opa_compiles_eleven_sheet_cases(self):
        self.assertIsInstance(self.plan,OpaTestPlan)
        self.assertEqual(self.plan.protocol,"swd")
        self.assertEqual(len(self.plan.cases),11)
        self.assertEqual(self.plan.cases[0].mode,"FOLLOW")
        self.assertEqual((self.plan.cases[-1].inp0_voltage,self.plan.cases[-1].inn0_voltage),(0.85,0.8))
        self.assertEqual(len(self.plan.patterns),12)
        with self.assertRaises(FrozenInstanceError): self.plan.item="x"

    def test_cp3_opa_groups_are_compiled_from_bonded_iomux_roles(self):
        for platform in ("chroma","s100"):
            facts=compile_platform_program_facts(self.workbook,TargetKey(platform,"CP3","lab","X"))
            self.assertEqual(tuple(pin.name for pin in facts.pin_groups.opa_inp0),("PA1",))
            self.assertEqual(tuple(pin.name for pin in facts.pin_groups.opa_inn0),("PA2",))
            self.assertEqual(tuple(pin.name for pin in facts.pin_groups.opa_out),("PC14",))

    def test_swd_renderers_use_one_runtime_loop_for_the_shared_case_flow(self):
        renderers = {"chroma": render_chroma, "s100": render_s100}
        for platform, renderer in renderers.items():
            facts = compile_platform_program_facts(
                self.workbook, TargetKey(platform, "CP3", "lab", "OPA_LOOP")
            )
            body = renderer(self.plan, "Opa_Test", 12, facts).content
            self.assertIn("for(int it=0;it<11;it++)", body)
            if platform == "chroma":
                self.assertIn("double opa_inp0[11]={", body)
                self.assertIn("double opa_down[11]={", body)
                self.assertNotIn("opa_pattern", body)
                self.assertIn(
                    'sprintf(pat_st,"PT104_OPA_%s_Test",opa_mode[it]);', body
                )
                self.assertIn(
                    'sprintf(pat_sp,"__PT104_OPA_%s_Test",opa_mode[it]);', body
                )
                self.assertEqual(body.count("POWER_ON(VCC_TYP);"), 1)
                self.assertEqual(body.count("JUDGE_V_PPMU(OPA_OUT_pins,"), 1)
                self.assertIn('sprintf(log_msg,"OPA_%s_Verify",opa_mode[it]);', body)
                self.assertIn("JUDGE_PAT(S:pat_st,S:pat_sp);", body)
            else:
                self.assertNotIn("opa_inp0[it]", body)
                self.assertNotIn("DOWN_LIMIT=opa_down[it]", body)
                self.assertIn(
                    "LOGIC_PPMU_FV(OPA_INP0_pins,1.65V,E1,I2);", body
                )
                self.assertIn(
                    "DOWN_LIMIT=1.62V,UP_LIMIT=1.68V", body
                )
                self.assertEqual(body.count("CALL_MACRO POWER_ON(_C_VCC_TYP);"), 1)
                self.assertEqual(body.count("LOGIC_PPMU_FI(OPA_OUT_pins,"), 1)
                self.assertEqual(body.count("switch(it)"), 2)
                for case in self.plan.cases:
                    self.assertIn(f"LOG_ALIAS=OPA_{case.mode}_[PINGROUP]", body)

    def test_repower_keeps_the_literal_safe_path(self):
        cases = list(self.plan.cases)
        cases[1] = replace(cases[1], repower_before=True)
        plan = replace(self.plan, cases=tuple(cases))
        for platform, renderer in (("chroma", render_chroma), ("s100", render_s100)):
            facts = compile_platform_program_facts(
                self.workbook, TargetKey(platform, "CP3", "lab", "OPA_LITERAL")
            )
            self.assertNotIn(
                "for(int it=", renderer(plan, "Opa_Test", 12, facts).content
            )

    def test_registered_native_slice_closes_with_twelve_stubs(self):
        self.assertIn("OPA_TEST",NATIVE_TYPED_KIND_REGISTRY.registered_kinds)
        for platform in ("chroma","s100"):
            target=TargetKey(platform,"CP3","lab",f"OPA_{platform}")
            facts=compile_platform_program_facts(self.workbook,target)
            producer=WorkspacePatternProducer(WORKSPACE_ROOT/"input"/platform)
            assembly=NATIVE_TYPED_KIND_REGISTRY.compile("OPA_TEST",(self.plan,),TypedKindContext(self.compilation,target,facts,producer))
            rendered=PlatformProgramBuilder(producer).build(ProgramAssemblyInput(target,facts,self.compilation.for_cp("CP3").canonical_schedule,assembly.contributions,assembly.bodies))
            program=rendered.artifact(target.program_name+(".pln" if platform=="chroma" else ".prg")).content
            self.assertIn(b"Opa_Test",program)
            self.assertIn(b"OPA_INP0_pins",program)
            self.assertEqual(sum(b"STUB: no real OPA SWD configuration vector" in artifact.content for artifact in rendered.artifacts),12)


if __name__=="__main__": unittest.main()
