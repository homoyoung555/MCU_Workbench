import inspect
import unittest

from program_gen.compiler import ProductCompiler
from program_gen.platform_program.facts import compile_platform_program_facts
from program_gen.platforms.s100 import adc_test_renderer
from program_gen.render_plan import TargetKey
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER


class S100AdcTestRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()
        cls.plan = cls.compilation.plan.catalogs.adc_test_plans[195]
        cls.facts = compile_platform_program_facts(
            cls.workbook,
            TargetKey("s100", "CP3", "lab", "ADC_S100_CP3"),
        )

    def _render(self, hardware_bin=27):
        return adc_test_renderer.render_adc_test(
            self.plan, "Adc_Test", hardware_bin, self.facts
        )

    def test_each_phase_owns_power_force_capture_cleanup_session(self):
        body = self._render().content

        self.assertEqual(body.count("CALL_MACRO POWER_ON(_C_VCC_TYP);"), 2)
        self.assertEqual(body.count("CALL_MACRO POWER_OFF();"), 2)
        self.assertEqual(body.count("WAIT(5MS);"), 2)
        adc1 = body[body.index("// ADC1 session"):body.index("// ADC2 session")]
        self.assertLess(adc1.index("POWER_ON("), adc1.index("LOGIC_SET_DRV_LEVEL(PC14"))
        self.assertLess(
            adc1.index("LOGIC_SET_DRV_LEVEL(PC14"),
            adc1.index("LOGIC_DRIVE_PIN(PC14, DRIVE_ENABLE, HIGH)"),
        )
        self.assertLess(adc1.index("WAIT(5MS)"), adc1.index("PT104_SWD_ADC1"))
        self.assertLess(adc1.index("PT104_SWD_ADC1"), adc1.index("PT104_ADC1_capture"))
        self.assertLess(adc1.index("LOGIC_DAQ_DATA_READ"), adc1.index("C_COMPARE("))
        self.assertLess(
            adc1.index("C_COMPARE("),
            adc1.index("LOGIC_DRIVE_PIN(PC14, DRIVE_DISABLE)"),
        )
        self.assertLess(adc1.index("DRIVE_DISABLE"), adc1.index("POWER_OFF("))

    def test_projection_uses_single_pin_drive_and_only_judges_selected_slots(self):
        body = self._render().content
        adc1 = body[body.index("// ADC1 session"):body.index("// ADC2 session")]

        expected_drives = (
            ("PC14", "1"), ("PC15", "1.5"), ("PA0", "2"),
            ("PA7", "2.5"), ("PA1", "1.2"), ("PA2", "1.4"),
        )
        for pin, voltage in expected_drives:
            self.assertIn(
                f"LOGIC_SET_DRV_LEVEL({pin}, {voltage}V, 0.0V, 0.0V, VR1);",
                adc1,
            )
            self.assertEqual(
                adc1.count(f"LOGIC_DRIVE_PIN({pin}, DRIVE_ENABLE, HIGH);"), 1
            )
            self.assertEqual(
                adc1.count(f"LOGIC_DRIVE_PIN({pin}, DRIVE_DISABLE);"), 1
            )
        self.assertNotIn("PPMU_GROUP", body)
        self.assertNotIn("LOGIC_SET_DRV_LEVEL(PD10", adc1)
        self.assertNotIn("LOGIC_DRIVE_PIN(INT_", body)

        self.assertIn("int adc1_channel[11]={2,3,4,5,8,9,15,18,19,20,21};", body)
        self.assertNotIn("sprintf(adc1_log", body)
        self.assertEqual(body.count("C_COMPARE(GBX2"), 18)
        self.assertIn("for(int item=0;item<11;item++)", body)
        self.assertIn("for(int item=0;item<7;item++)", body)
        self.assertNotIn("DOWN_LIMIT=adc1_down[item]", body)
        self.assertNotIn("DOWN_LIMIT=adc2_down[item]", body)
        self.assertIn(
            "case 0: C_COMPARE(GBX2, DOWN_LIMIT=1177, UP_LIMIT=1305, "
            "LOG_ALIAS=ADC1_CH2_PC14_VERIFY); break;",
            body,
        )
        self.assertNotIn("PD10", body)

    def test_capture_decodes_all_twenty_two_sixteen_bit_slots_without_masking(self):
        body = self._render().content

        self.assertEqual(body.count("LOGIC_DAQ_DATA_READ(DATA_COUNT=352);"), 2)
        self.assertEqual(body.count("for(int K=0;K<22;K++)"), 2)
        self.assertEqual(body.count("for(int J=0;J<16;J++)"), 2)
        self.assertNotIn("J<15", body)
        self.assertNotIn("0x0FFF", body)
        self.assertNotIn("&4095", body)
        self.assertNotIn("%4096", body)

    def test_resources_are_explicit_s100_config_and_capture_requirements(self):
        rendered = self._render()

        self.assertEqual(rendered.resources, ())
        self.assertEqual(
            tuple(item.relative_path for item in rendered.resource_requires),
            (
                "PT104_SWD_ADC1.sd",
                "PT104_ADC1_capture.sd",
                "PT104_SWD_ADC2.sd",
                "PT104_ADC2_capture.sd",
            ),
        )
        self.assertEqual(
            tuple(item.logical_identity for item in rendered.resource_requires),
            (
                "adc-swd:s100:adc1:config",
                "adc-swd:s100:adc1:capture",
                "adc-swd:s100:adc2:config",
                "adc-swd:s100:adc2:capture",
            ),
        )
        self.assertTrue(all("ADC SWD" in item.purpose for item in rendered.resource_requires))
        self.assertEqual(rendered.content.count("AC_IGNORE_FAIL"), 2)
        self.assertIn("REJECT_BIN = 27;", rendered.content)

    def test_renderer_has_no_workbook_or_legacy_global_dependency(self):
        source = inspect.getsource(adc_test_renderer)

        self.assertNotIn("WorkbookReader", source)
        self.assertNotIn("program_gen import state", source)
        self.assertNotRegex(source, r"\bG\.")
        self.assertNotIn("analog_sweep", source)


if __name__ == "__main__":
    unittest.main()
