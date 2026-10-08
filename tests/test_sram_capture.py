from dataclasses import FrozenInstanceError
import unittest

from program_gen.core.sram_capture import (
    SramCaptureArgument,
    SramCaptureCompileError,
    compile_sram_capture_layout,
    compile_sram_capture_plan,
    parse_sram_capture_argument,
)
from program_gen.core.result_binding import ResultIdentity
from program_gen.diagnostics import WorkbookProvenance


class SramCaptureTests(unittest.TestCase):
    def test_typed_argument_rejects_non_integer_fields(self):
        invalid_fields = (
            {"base": True, "count": 1, "width": 16, "stride": 4},
            {"base": 0x3000, "count": 1.0, "width": 16, "stride": 4},
            {"base": 0x3000, "count": 1, "width": "16", "stride": 4},
            {"base": 0x3000, "count": 1, "width": 16, "stride": 4.0},
        )

        for fields in invalid_fields:
            with self.subTest(fields=fields):
                with self.assertRaises(SramCaptureCompileError):
                    SramCaptureArgument(**fields)

    def test_aligned_layout_is_immutable_and_exposes_each_read32(self):
        layout = compile_sram_capture_layout("0X3000,2x16@2")

        self.assertEqual(
            (layout.base, layout.count, layout.width, layout.stride),
            (0x3000, 2, 16, 2),
        )
        self.assertIsInstance(layout.values, tuple)
        self.assertEqual(
            [
                (
                    value.index,
                    value.value_address,
                    value.read32_address,
                    value.bit_offset,
                    value.crosses_word,
                    value.second_read32_address,
                )
                for value in layout.values
            ],
            [
                (0, 0x3000, 0x3000, 0, False, None),
                (1, 0x3002, 0x3000, 16, False, None),
            ],
        )
        with self.assertRaises(FrozenInstanceError):
            layout.values = ()

    def test_unaligned_value_exposes_second_read32_when_it_crosses_word(self):
        layout = compile_sram_capture_layout("0X3003,1x16@2")
        value = layout.values[0]

        self.assertEqual(value.value_address, 0x3003)
        self.assertEqual(value.read32_address, 0x3000)
        self.assertEqual(value.bit_offset, 24)
        self.assertTrue(value.crosses_word)
        self.assertEqual(value.second_read32_address, 0x3004)

    def test_layout_declares_little_endian_unsigned_low_width_semantics(self):
        layout = compile_sram_capture_layout("0X3003,1x16@2")
        value = layout.values[0]
        first_word = 0x44332211
        second_word = 0x88776655

        decoded = (
            (first_word | (second_word << 32)) >> value.bit_offset
        ) & layout.value_mask

        self.assertEqual(layout.byte_order, "little")
        self.assertFalse(layout.signed)
        self.assertEqual(layout.value_mask, 0xFFFF)
        self.assertEqual(decoded, 0x5544)

    def test_base_must_fit_the_16_bit_pattern_window(self):
        for spec in ("-1,1x1@1", "0X10000,1x1@1"):
            with self.subTest(spec=spec):
                with self.assertRaises(SramCaptureCompileError):
                    compile_sram_capture_layout(spec)

    def test_count_must_be_positive(self):
        for spec in ("0X3000,0x16@1", "0X3000,-1x16@1"):
            with self.subTest(spec=spec):
                with self.assertRaises(SramCaptureCompileError):
                    compile_sram_capture_layout(spec)

    def test_width_must_be_between_one_and_32_bits(self):
        for spec in ("0X3000,1x0@1", "0X3000,1x33@1"):
            with self.subTest(spec=spec):
                with self.assertRaises(SramCaptureCompileError):
                    compile_sram_capture_layout(spec)

    def test_stride_must_be_positive(self):
        for spec in ("0X3000,1x16@0", "0X3000,1x16@-1"):
            with self.subTest(spec=spec):
                with self.assertRaises(SramCaptureCompileError):
                    compile_sram_capture_layout(spec)

    def test_final_value_byte_coverage_must_remain_in_pattern_window(self):
        for spec in ("0XFFFF,1x9@1", "0XFFFE,2x16@1"):
            with self.subTest(spec=spec):
                with self.assertRaises(SramCaptureCompileError):
                    compile_sram_capture_layout(spec)

        boundary = compile_sram_capture_layout("0XFFFE,2x8@1")
        self.assertEqual(boundary.values[-1].value_address, 0xFFFF)

    def test_production_plan_carries_capture_context_and_layout(self):
        identity = ResultIdentity("CP3", "Adc_Test", "ADC1", "SRAM_CAPTURE")
        provenance = WorkbookProvenance("FLOW", "L27", "formal.xlsx", "abc123")

        plan = compile_sram_capture_plan(
            parse_sram_capture_argument("0X3000,2x16@2"),
            result_identity=identity,
            provenance=provenance,
            capture_pin="PA13",
        )

        self.assertEqual(plan.result_identity, identity)
        self.assertEqual(plan.provenance, provenance)
        self.assertEqual(plan.capture_pin, "PA13")
        self.assertEqual(plan.layout.canonical_spec, "0X3000,2x16@2")
        self.assertEqual(
            plan.result_symbol,
            "SRAM_CAPTURE_CP3_ADC_TEST_ADC1_SRAM_CAPTURE",
        )
        with self.assertRaises(FrozenInstanceError):
            plan.capture_pin = "PA14"

    def test_production_plan_requires_the_already_typed_recipe_argument(self):
        with self.assertRaises(SramCaptureCompileError):
            compile_sram_capture_plan(
                "0X3000,1x16",
                result_identity=ResultIdentity(
                    "CP3", "Adc_Test", "ADC1", "SRAM_CAPTURE"
                ),
                provenance=WorkbookProvenance("FLOW", "L27"),
                capture_pin="PA13",
            )

    def test_production_plan_rejects_missing_or_unsafe_capture_pin(self):
        identity = ResultIdentity("CP3", "Adc_Test", "ADC1", "SRAM_CAPTURE")
        provenance = WorkbookProvenance("FLOW", "L27")
        argument = parse_sram_capture_argument("0X3000,1x16")

        for capture_pin in (None, "", "/", "PA-13", "PA13 "):
            with self.subTest(capture_pin=capture_pin):
                with self.assertRaises(SramCaptureCompileError):
                    compile_sram_capture_plan(
                        argument,
                        result_identity=identity,
                        provenance=provenance,
                        capture_pin=capture_pin,
                    )


if __name__ == "__main__":
    unittest.main()
