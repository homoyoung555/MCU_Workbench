import inspect
import re
import unittest

from program_gen.core.result_binding import ResultIdentity
from program_gen.core.sram_capture import (
    SramCapturePlan,
    compile_sram_capture_layout,
)
from program_gen.diagnostics import WorkbookProvenance
from program_gen.platforms.s100 import sram_capture_adapter
from program_gen.recipe_module_registry import RecipeModuleEmission


class S100SramCaptureAdapterTests(unittest.TestCase):
    def test_16bit_stride2_reads_each_unique_aligned_word_once(self):
        plan = _plan("0X3000,4x16@2")
        emission = sram_capture_adapter.adapt_sram_capture(plan)
        text = "\n".join(emission.statements)

        self.assertIsInstance(emission, RecipeModuleEmission)
        self.assertEqual(text.count("LOGIC_DAQ_DATA_READ(DATA_COUNT=32);"), 2)
        self.assertEqual(text.count("RUN_PATTERN(sram_capture:START"), 2)
        self.assertEqual(text.count("GB[0+T_SOCKET*64]=0X3000;"), 1)
        self.assertEqual(text.count("GB[0+T_SOCKET*64]=0X3004;"), 1)
        self.assertIn("SRAM_CAPTURE_CP3_ADC_TEST_ADC1_ADC_CODES_READ32[T_SOCKET][0]", text)
        self.assertIn("SRAM_CAPTURE_CP3_ADC_TEST_ADC1_ADC_CODES_READ32[T_SOCKET][1]", text)
        self.assertEqual(text.count("&0XFFFFU;"), 4)
        self.assertNotRegex(text, r"0X0?FFF(?!F)")

    def test_cross_word_value_uses_two_cached_words_and_unsigned_projection(self):
        plan = _plan("0X3002,1x32@2")
        text = "\n".join(
            sram_capture_adapter.adapt_sram_capture(plan).statements
        )

        self.assertEqual(text.count("LOGIC_DAQ_DATA_READ(DATA_COUNT=32);"), 2)
        self.assertIn("GB[0+T_SOCKET*64]=0X3000;", text)
        self.assertIn("GB[0+T_SOCKET*64]=0X3004;", text)
        self.assertIn(
            "(SRAM_CAPTURE_CP3_ADC_TEST_ADC1_ADC_CODES_READ32[T_SOCKET][0]>>16)",
            text,
        )
        self.assertIn(
            "(SRAM_CAPTURE_CP3_ADC_TEST_ADC1_ADC_CODES_READ32[T_SOCKET][1]<<16)",
            text,
        )
        self.assertIn("&0XFFFFFFFFU;", text)
        self.assertIn("unsigned int SRAM_CAPTURE_CP3_ADC_TEST_ADC1_ADC_CODES", text)
        self.assertNotIn("C_COMPARE", text)
        self.assertNotIn("JUDGE", text)

    def test_resource_and_captured_values_symbol_contract_are_explicit(self):
        plan = _plan("0X3000,4x16@2")
        emission = sram_capture_adapter.adapt_sram_capture(plan)

        self.assertEqual(len(emission.resource_requires), 1)
        resource = emission.resource_requires[0]
        self.assertEqual(resource.relative_path, "sram_capture.sd")
        self.assertTrue(resource.purpose.startswith("SRAM_CAPTURE"))
        self.assertEqual(len(emission.provides), 1)
        provision = emission.provides[0]
        self.assertEqual(provision.ref.namespace, "CAPTURED_VALUES")
        self.assertEqual(provision.ref.semantic_key, plan.result_identity.canonical)
        self.assertEqual(provision.rendered_name, plan.result_symbol)
        self.assertEqual(
            (provision.value_type, provision.bit_width, provision.scope),
            ("UINT", 16, "SITE"),
        )

    def test_adapter_rejects_non_plan_and_has_no_workbook_or_global_dependency(self):
        with self.assertRaises(TypeError):
            sram_capture_adapter.adapt_sram_capture(object())

        source = inspect.getsource(sram_capture_adapter)
        self.assertNotIn("WorkbookReader", source)
        self.assertNotIn("program_gen import state", source)
        self.assertNotRegex(source, r"\bG\.")


def _plan(spec: str) -> SramCapturePlan:
    return SramCapturePlan(
        layout=compile_sram_capture_layout(spec),
        result_identity=ResultIdentity("CP3", "Adc_Test", "ADC1", "ADC_CODES"),
        provenance=WorkbookProvenance("FLOW", "A197", "wb", "sha"),
        capture_pin="PA13",
    )


if __name__ == "__main__":
    unittest.main()
