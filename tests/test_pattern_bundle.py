import unittest

import pandas as pd

from pattern_bundle import (
    PatternCompileError,
    bind_dynamic_argument,
    compile_pattern_bundles,
    parse_pattern_fields,
)


class PatternBundleTests(unittest.TestCase):
    def test_bundle_and_role_are_inherited_from_merged_cell_top_left_values(self):
        frame = pd.DataFrame(
            [
                {"item": "MRVDDD", "addr": "0101110", "description": "2,MR_LEVEL[2:0]=001*", "pattern": "enter"},
                {"item": None, "addr": "0011101", "description": "7,trim_sel=0", "pattern": None},
                {"item": None, "addr": "0000010", "description": "3,MR_DAC[3:0]=0000*", "pattern": "set dac"},
            ]
        )

        catalog = compile_pattern_bundles(frame)

        bundle = catalog.bundle("MRVDDD")
        self.assertEqual([step.role for step in bundle.steps], ["enter", "set dac"])
        self.assertEqual([row.excel_row for row in bundle.steps[0].rows], [2, 3])

    def test_one_contiguous_item_block_may_contain_multiple_roles(self):
        frame = pd.DataFrame(
            [
                {"item": "MRVDDD", "addr": "0101110", "description": "2,MR_LEVEL[2:0]=001*", "pattern": "trim mode"},
                {"item": None, "addr": "0000010", "description": "3,MR_DAC[3:0]=0000*", "pattern": "trim dac"},
                {"item": None, "addr": "0101110", "description": "2,MR_LEVEL[2:0]=001*", "pattern": "verify mode"},
            ]
        )

        catalog = compile_pattern_bundles(frame)

        self.assertEqual(
            [step.role for step in catalog.bundle("MRVDDD").steps],
            ["trim mode", "trim dac", "verify mode"],
        )

    def test_same_item_cannot_be_split_into_noncontiguous_blocks(self):
        frame = pd.DataFrame(
            [
                {"item": "MRVDDD", "addr": "0101110", "description": "2,MR_LEVEL[2:0]=001*", "pattern": "trim mode"},
                {"item": "HSI", "addr": "0110000", "description": "3,HSI_FS[2:0]=000*", "pattern": "verify mode"},
                {"item": "MRVDDD", "addr": "0101110", "description": "2,MR_LEVEL[2:0]=001*", "pattern": "verify mode"},
            ]
        )

        with self.assertRaisesRegex(PatternCompileError, "连续块"):
            compile_pattern_bundles(frame)

    def test_star_keeps_default_value_and_no_argument_restores_it(self):
        catalog = compile_pattern_bundles(_mr_frame())

        binding = bind_dynamic_argument(catalog, "MRVDDD", "enter", None)

        self.assertEqual(binding.field.name, "MR_LEVEL[2:0]")
        self.assertEqual(binding.value, "001")

    def test_argument_preserves_width_and_replaces_default(self):
        catalog = compile_pattern_bundles(_mr_frame())

        binding = bind_dynamic_argument(catalog, "MRVDDD", "enter", "010")

        self.assertEqual(binding.value, "010")
        with self.assertRaisesRegex(PatternCompileError, "位宽"):
            bind_dynamic_argument(catalog, "MRVDDD", "enter", "10")

    def test_binding_requires_exactly_one_starred_field_in_selected_role(self):
        frame = _mr_frame()
        frame.loc[0, "description"] = "2,MR_LEVEL[2:0]=001"
        catalog = compile_pattern_bundles(frame)

        with self.assertRaisesRegex(PatternCompileError, "一个 '\\*' 字段"):
            bind_dynamic_argument(catalog, "MRVDDD", "enter", "010")

    def test_star_cannot_be_combined_with_legacy_x_placeholder(self):
        with self.assertRaisesRegex(PatternCompileError, "不能使用 x"):
            parse_pattern_fields("3,MR_DAC[3:0]=xxxx*", 40)

    def test_field_width_must_match_default_value(self):
        with self.assertRaisesRegex(PatternCompileError, "位宽"):
            parse_pattern_fields("2,MR_LEVEL[2:0]=01*", 35)


def _mr_frame():
    return pd.DataFrame(
        [
            {"item": "MRVDDD", "addr": "0101110", "description": "2,MR_LEVEL[2:0]=001*", "pattern": "enter"},
            {"item": None, "addr": "0011101", "description": "7,trim_sel=0", "pattern": None},
        ]
    )


if __name__ == "__main__":
    unittest.main()
