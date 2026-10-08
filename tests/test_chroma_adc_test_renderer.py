import unittest

from program_gen.compiler import ProductCompiler
from program_gen.platform_program.facts import compile_platform_program_facts
from program_gen.platforms.chroma.adc_test_renderer import render_adc_test
from program_gen.render_plan import TargetKey
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER


class ChromaAdcTestRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()
        cls.plan = cls.compilation.plan.catalogs.adc_test_plans[195]
        cls.facts = compile_platform_program_facts(
            cls.workbook,
            TargetKey("chroma", "CP3", "lab", "ADC_CHROMA_CP3"),
        )

    def _render(self):
        return render_adc_test(self.plan, "Adc_Test", 9, self.facts)

    def test_two_phases_each_own_a_complete_power_force_capture_cleanup_session(self):
        body = self._render().content

        self.assertEqual(body.count("POWER_ON(VCC_TYP);"), 2)
        self.assertEqual(body.count("POWER_OFF();"), 2)
        self.assertEqual(body.count("SET_CAPTURE_MEM_MODE(PA13, PEL_K, ON, 32K);"), 2)
        self.assertEqual(body.count("SET_CAPTURE_MEM_MODE(PA13, PEL_K, OFF, 32K);"), 2)
        first = body[body.index("// ADC1 session"):body.index("// ADC2 session")]
        self.assertLess(first.index("POWER_ON("), first.index("FORCE_V_PPMU("))
        self.assertLess(first.index("PT104_SWD_ADC1"), first.index("PT104_ADC1_capture"))
        self.assertLess(first.index("SET_CAPTURE_MEM_MODE(PA13, PEL_K, OFF"), first.index("RELAY_OFF("))
        self.assertLess(first.index("RELAY_OFF("), first.index("POWER_OFF("))

    def test_target_projection_forces_only_bonded_external_pins_and_judges_internal_slots(self):
        body = self._render().content
        adc1 = body[body.index("// ADC1 session"):body.index("// ADC2 session")]

        for statement in (
            "FORCE_V_PPMU(PC14, 1V",
            "FORCE_V_PPMU(PC15, 1.5V",
            "FORCE_V_PPMU(PA0, 2V",
            "FORCE_V_PPMU(PA7, 2.5V",
            "FORCE_V_PPMU(PA1, 1.2V",
            "FORCE_V_PPMU(PA2, 1.4V",
        ):
            self.assertIn(statement, adc1)
        self.assertNotIn("FORCE_V_PPMU(PD10", adc1)
        self.assertEqual(adc1.count("FORCE_V_PPMU(PA1,"), 1)
        self.assertIn("int adc1_channel[11]={2,3,4,5,8,9,15,18,19,20,21};", adc1)
        self.assertIn('sprintf(adc1_log,"ADC1_CH%d_%s_Verify",', adc1)
        self.assertEqual(adc1.count("JUDGE_VARIABLE("), 1)
        self.assertNotIn("PD10", adc1)
        socket_inc = adc1.index("SOCKET_INC(FRZ_OFF)")
        self.assertLess(adc1.index("int adc1_channel[11]"), socket_inc)
        self.assertNotIn("int adc1_channel", adc1[socket_inc:])

    def test_capture_decodes_all_sixteen_bits_without_masking_upper_four(self):
        body = self._render().content

        self.assertEqual(body.count("READ_CAPTURE_MEM_BLOCK(SOCKET, PA13, 0, 351"), 2)
        self.assertIn("for(J=0;J<16;J++)", body)
        self.assertNotIn("J<15", body)
        self.assertNotIn("!=8", body)
        self.assertNotIn("0x0FFF", body)

    def test_logical_capture_roles_map_to_four_explicit_platform_resources(self):
        rendered = self._render()
        self.assertEqual(rendered.resources, ())
        self.assertEqual(
            tuple(requirement.relative_path for requirement in rendered.resource_requires),
            (
                "pat/PT104_SWD_ADC1.pat",
                "pat/PT104_ADC1_capture.pat",
                "pat/PT104_SWD_ADC2.pat",
                "pat/PT104_ADC2_capture.pat",
            ),
        )
        self.assertTrue(all(
            requirement.logical_identity.startswith("adc-swd:chroma:")
            for requirement in rendered.resource_requires
        ))


if __name__ == "__main__":
    unittest.main()
