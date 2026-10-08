import inspect
import unittest

from program_gen.core.result_binding import ResultIdentity
from program_gen.core.sram_capture import (
    SramCapturePlan,
    compile_sram_capture_layout,
)
from program_gen.diagnostics import WorkbookProvenance
from program_gen.platforms.chroma import sram_capture_adapter
from program_gen.recipe_module_registry import RecipeModuleEmission


class ChromaSramCaptureAdapterTests(unittest.TestCase):
    def test_16bit_stride2_reads_each_unique_aligned_word_once(self):
        plan = _plan("0X3000,4x16@2")
        emission = sram_capture_adapter.adapt_sram_capture(plan)
        text = "\n".join(emission.statements)

        self.assertIsInstance(emission, RecipeModuleEmission)
        self.assertEqual(
            text.count("READ_CAPTURE_MEM_BLOCK(SOCKET, PA13, 0, 31"), 2
        )
        self.assertEqual(text.count("JUDGE_PAT(sram_capture,__sram_capture);"), 2)
        self.assertEqual(text.count("convert_to_string(0X3000,16"), 1)
        self.assertEqual(text.count("convert_to_string(0X3004,16"), 1)
        self.assertEqual(
            text.count("WRITE_PAT_MEM(SOCKET,PA13,sram_capture:addr+I"), 2
        )
        self.assertIn(
            'WRITE_PAT_MEM(SOCKET,PA13,sram_capture:parity,,"1");', text
        )
        self.assertIn(
            'WRITE_PAT_MEM(SOCKET,PA13,sram_capture:parity,,"0");', text
        )
        self.assertLess(
            text.index("convert_to_string(0X3000,16"),
            text.index("JUDGE_PAT(sram_capture,__sram_capture);"),
        )
        self.assertLess(
            text.index("JUDGE_PAT(sram_capture,__sram_capture);"),
            text.index("READ_CAPTURE_MEM_BLOCK(SOCKET, PA13, 0, 31"),
        )
        self.assertIn(
            "SRAM_CAPTURE_CP3_ADC_TEST_ADC1_ADC_CODES_READ32[SOCKET][0]", text
        )
        self.assertIn(
            "SRAM_CAPTURE_CP3_ADC_TEST_ADC1_ADC_CODES_READ32[SOCKET][1]", text
        )
        self.assertEqual(text.count("&0XFFFFU;"), 4)
        self.assertNotRegex(text, r"0X0?FFF(?!F)")

    def test_cross_word_value_uses_two_cached_words_and_unsigned_projection(self):
        plan = _plan("0X3002,1x32@2")
        text = "\n".join(
            sram_capture_adapter.adapt_sram_capture(plan).statements
        )

        self.assertEqual(
            text.count("READ_CAPTURE_MEM_BLOCK(SOCKET, PA13, 0, 31"), 2
        )
        self.assertIn("convert_to_string(0X3000,16", text)
        self.assertIn("convert_to_string(0X3004,16", text)
        self.assertIn(
            "(SRAM_CAPTURE_CP3_ADC_TEST_ADC1_ADC_CODES_READ32[SOCKET][0]>>16)",
            text,
        )
        self.assertIn(
            "(SRAM_CAPTURE_CP3_ADC_TEST_ADC1_ADC_CODES_READ32[SOCKET][1]<<16)",
            text,
        )
        self.assertIn("&0XFFFFFFFFU;", text)
        self.assertIn("unsigned int SRAM_CAPTURE_CP3_ADC_TEST_ADC1_ADC_CODES", text)
        self.assertNotIn("C_COMPARE", text)
        self.assertNotIn("JUDGE_VARIABLE", text)

    def test_pattern_resource_labels_and_captured_values_symbol_are_explicit(self):
        plan = _plan("0X3000,4x16@2")
        emission = sram_capture_adapter.adapt_sram_capture(plan)
        text = "\n".join(emission.statements)

        self.assertIn("sram_capture:addr+I", text)
        self.assertIn("sram_capture:parity", text)
        self.assertIn("JUDGE_PAT(sram_capture,__sram_capture);", text)
        self.assertEqual(len(emission.resource_requires), 1)
        resource = emission.resource_requires[0]
        self.assertEqual(resource.relative_path, "pat/sram_capture.pat")
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
