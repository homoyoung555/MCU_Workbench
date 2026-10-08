import unittest
import os
from pathlib import Path
import re

import pandas as pd

from program_gen.core.trim_spec import (
    ExplicitCodes,
    LinearRange,
    TrimCompileError,
    compile_trim_specs,
    dynamic_enter_operations,
)
from tests.workspace_paths import FORMAL_MASTER, S100_SEED_ROOT


class TrimSpecTests(unittest.TestCase):
    def test_standard_trim_compiles_to_small_ordered_operation_interface(self):
        spec = _compile_one()[0]

        self.assertEqual(
            [operation.kind for operation in spec.operations],
            ["ENTER", "TRIM", "JUDGE"],
        )
        self.assertEqual(spec.search.codes, tuple(range(16)))
        self.assertEqual(spec.search.domain_source, "FULL_RANGE")
        self.assertEqual(spec.search.domain, LinearRange(0, 15))
        self.assertEqual(
            [(variant.kind, variant.scheduled) for variant in spec.search.variants],
            [("BISECTION", True), ("FULL_SCAN", False)],
        )

    def test_fbist_protocol_patterns_are_explicit_typed_plan_inputs(self):
        spec = _compile_one()[0]

        self.assertEqual(spec.protocol.enter_pattern, "enter_fbist_mode")
        self.assertEqual(spec.protocol.exit_pattern, "exit_fbist_mode")

    def test_dynamic_enter_metadata_is_available_through_trim_spec(self):
        flow = _flow_row()
        flow.loc[0, "Recipe"] = "ENTER(010)\nTRIM\nJUDGE"
        pattern = _pattern_rows(
            "Mr_VDDD_DC",
            "7,MR_DAC[3:0]=0000*",
            enter_description="2,MR_LEVEL[2:0]=001*",
        )

        specs = compile_trim_specs(flow, pattern)
        operation = dynamic_enter_operations(specs, "CP1")[0]

        self.assertEqual(operation.reference, "enter_mr_vddd_dc")
        self.assertEqual(operation.value_source, "ARGUMENT")
        self.assertEqual(operation.value, "010")
        self.assertEqual(operation.default_value, "001")
        self.assertEqual(operation.field_width, 3)

    def test_explicit_step_is_the_search_domain_even_when_line_says_yes(self):
        flow = _flow_row(
            item="Pclk_Trim",
            bits=3,
            step="4,5,6,7,0,1,2",
            line="yes",
            unit="KHz",
            force="/",
            pe="ERASE",
        )
        pattern = _pattern_rows("Pclk_Trim", "11,PCLK[2:0]=000*")

        spec = compile_trim_specs(flow, pattern, nm_pattern_frame=_nm_pattern_rows())[0]

        self.assertEqual(spec.search.codes, (4, 5, 6, 7, 0, 1, 2))
        self.assertEqual(spec.search.domain_source, "EXPLICIT_STEP")
        self.assertEqual(
            spec.search.domain,
            ExplicitCodes((4, 5, 6, 7, 0, 1, 2)),
        )
        self.assertEqual(
            [operation.kind for operation in spec.search.per_point_actions],
            ["SET_DAC", "ERASE", "MEASURE"],
        )
        self.assertEqual(spec.search.per_point_actions[1].reference, "fbist_erase_main_1st_page")
        self.assertEqual(spec.measurement.family, "FREQUENCY")

    def test_pattern_field_width_and_search_width_are_independent(self):
        flow = _flow_row(item="Vrefbuf1p024_Trim", bits=7, step="64-127,0-62")
        pattern = _pattern_rows("Vrefbuf1p024_Trim", "7,VREFBUF[7:0]=00000000*")

        spec = compile_trim_specs(flow, pattern)[0]

        self.assertEqual(spec.dac.field_width, 8)
        self.assertEqual(spec.search.search_bits, 7)
        self.assertEqual(len(spec.search.codes), 127)
        self.assertEqual(spec.search.codes[:3], (64, 65, 66))
        self.assertEqual(spec.search.codes[-3:], (60, 61, 62))

    def test_depend_recipe_is_the_explicit_dependency_source(self):
        flow = _flow_row(item="Hsi_8M_Trim", bits=10, unit="KHz", force="/")
        flow.loc[0, "Recipe"] = "ENTER\nDEPEND(Hsi_Vrega)\nTRIM\nJUDGE"
        pattern = _pattern_rows(
            "Hsi_8M_Trim",
            "15,HSI_TC[3:0]=1000\n9,HSI_ABS[9:0]=0000000000*",
        )
        pattern = pd.concat(
            [
                pattern,
                _pattern_rows(
                    "Hsi_Vrega",
                    "15,HSI_VREG[2:0]=000*",
                ).iloc[1:],
            ],
            ignore_index=True,
        )
        pattern.loc[len(pattern) - 1, "item"] = "Hsi_Vrega"

        spec = compile_trim_specs(flow, pattern)[0]

        self.assertEqual(spec.dependencies, ("Hsi_Vrega",))
        self.assertEqual(
            [operation.kind for operation in spec.operations],
            ["ENTER", "DEPEND", "TRIM", "JUDGE"],
        )

    def test_highlighted_and_explicit_dependencies_share_set_dac_operations(self):
        flow = _flow_row(item="Hsi_8M", bits=10, unit="KHz", force="/")
        flow.loc[0, "Recipe"] = "ENTER\nDEPEND(Hsi_Vrega)\nTRIM\nJUDGE"
        flow.attrs["common_dac_dependencies"] = ("Vref0p8_ABS", "Iref1U")
        pattern = _pattern_rows(
            "Hsi_8M",
            "15,HSI_TC[3:0]=1000\n9,HSI_ABS[9:0]=0000000000*",
        )
        for item, description in (
            ("Vref0p8_ABS", "3,VREF[3:0]=0000*"),
            ("Iref1U", "3,IREF[3:0]=0000*"),
            ("Hsi_Vrega", "15,HSI_VREG[2:0]=000*"),
        ):
            dependency = _pattern_rows(item, description).iloc[1:].copy()
            dependency.iloc[0, dependency.columns.get_loc("item")] = item
            pattern = pd.concat([pattern, dependency], ignore_index=True)

        spec = compile_trim_specs(flow, pattern)[0]

        dependencies = [operation for operation in spec.operations if operation.kind == "DEPEND"]
        self.assertEqual(spec.dependencies, ("Vref0p8_ABS", "Iref1U", "Hsi_Vrega"))
        self.assertEqual(
            [operation.reference for operation in dependencies],
            ["set_vref0p8_abs_dac", "set_iref1u_dac", "set_hsi_vrega_dac"],
        )
        self.assertEqual(
            [operation.value for operation in dependencies],
            ["Vref0p8_ABS", "Iref1U", "Hsi_Vrega"],
        )
        self.assertEqual(
            [operation.source_symbol for operation in dependencies],
            [
                "VREF0P8_ABS_DAC_FINAL",
                "IREF1U_DAC_FINAL",
                "HSI_VREGA_DAC_FINAL",
            ],
        )
        self.assertEqual(
            [operation.helper_name for operation in dependencies],
            [
                "set_vref0p8_abs_trim_data",
                "set_iref1u_trim_data",
                "set_hsi_vrega_trim_data",
            ],
        )

    def test_dac_adjust_is_a_typed_final_policy(self):
        flow = _flow_row(item="Hsi_Vrega_Trim", bits=3)
        flow.loc[0, "Recipe"] = "ENTER\nTRIM\nDAC_ADJ(<1.16:+1)\nJUDGE"
        flow = flow.drop(columns=["DAC ADJ"])
        pattern = _pattern_rows("Hsi_Vrega_Trim", "15,HSI_VREG[2:0]=000*")

        spec = compile_trim_specs(flow, pattern)[0]

        self.assertEqual(spec.adjust.operator, "<")
        self.assertEqual(spec.adjust.threshold, 1.16)
        self.assertEqual(spec.adjust.delta, 1)
        self.assertIn("DAC_ADJ", [operation.kind for operation in spec.operations])

    def test_negative_current_uses_measurement_adapter_without_new_recipe_module(self):
        flow = _flow_row(
            item="Isa_Trim",
            bits=5,
            step="15-0,31-17",
            unit="uA",
            force="0.7V",
            target=-4.5,
        )
        pattern = _pattern_rows("Isa_Trim", "7,IDAC[4:0]=00000*")

        spec = compile_trim_specs(flow, pattern)[0]

        self.assertEqual(spec.measurement.family, "CURRENT")
        self.assertEqual(spec.measurement.target, -4.5)
        self.assertEqual(spec.measurement.force, "0.7V")

    def test_special_trim_can_insert_typed_operations_without_expanding_recipe_vocabulary(self):
        spec = _compile_one()[0]

        special = spec.insert_operations(
            before="TRIM",
            operations=(spec.operation("RUN_PATTERN", reference="prepare_special_mode"),),
        )

        self.assertEqual(
            [operation.kind for operation in special.operations],
            ["ENTER", "RUN_PATTERN", "TRIM", "JUDGE"],
        )
        self.assertEqual(special.operations[1].reference, "prepare_special_mode")

        special_search = spec.search.insert_operations(
            before="MEASURE",
            operations=(
                spec.operation(
                    "RUN_PATTERN",
                    reference="pulse_before_measure",
                    scope="EACH_SEARCH_POINT",
                ),
            ),
        )
        self.assertEqual(
            [operation.kind for operation in special_search.per_point_actions],
            ["SET_DAC", "RUN_PATTERN", "MEASURE"],
        )

    def test_pdr_and_bor_cannot_enter_generic_trim_compiler(self):
        for item in ("Pdr_Trim", "Bor_Trim"):
            with self.subTest(item=item):
                with self.assertRaisesRegex(TrimCompileError, "专用流程"):
                    compile_trim_specs(
                        _flow_row(item=item),
                        _pattern_rows(item, "3,SPECIAL[3:0]=0000*"),
                    )

    def test_all_ordinary_fbist_trim_rows_in_current_master_fit_the_generic_spec(self):
        from program_gen import state as G

        original_cwd = Path.cwd()
        try:
            G.init(
                str(S100_SEED_ROOT),
                platform="s100",
                mode="production",
                master=str(FORMAL_MASTER),
            )
            flow = G.FLOW.copy(deep=True)
            pattern = G.PATTERN.copy(deep=True)
        finally:
            os.chdir(original_cwd)

        ordinary = (
            flow["type"].fillna("").astype(str).str.strip().str.casefold().eq("trim")
            & flow["mode"].fillna("").astype(str).str.strip().str.casefold().eq("fbist")
            & ~flow["item"].fillna("").astype(str).str.strip().str.casefold().isin(
                ("pdr_trim", "bor_trim")
            )
        )
        _migrate_legacy_trim_dac_markers_in_memory(pattern)

        specs = compile_trim_specs(
            flow, pattern, nm_pattern_frame=G.NM_PATTERN.copy(deep=True)
        )

        self.assertEqual(len(specs), 35)
        self.assertEqual(len({spec.item for spec in specs.values()}), 31)
        self.assertEqual(
            sum("ERASE" in [action.kind for action in spec.search.per_point_actions]
                for spec in specs.values()),
            4,
        )
        self.assertEqual(
            sum("PROGRAM" in [action.kind for action in spec.search.per_point_actions]
                for spec in specs.values()),
            3,
        )
        self.assertEqual(sum(bool(spec.dependencies) for spec in specs.values()), 35)
        self.assertEqual(
            sum("Hsi_Vrega" in spec.dependencies for spec in specs.values()),
            8,
        )
        self.assertEqual(sum(spec.adjust is not None for spec in specs.values()), 1)


def _migrate_legacy_trim_dac_markers_in_memory(pattern):
    current_item = None
    current_role = None
    for index, record in pattern.iterrows():
        if not pd.isna(record["item"]):
            current_item = str(record["item"]).strip()
            current_role = None
        if not pd.isna(record["pattern"]):
            current_role = str(record["pattern"]).strip().casefold()
        if current_item is None or current_item.casefold() in ("pdr_trim", "bor_trim"):
            continue
        if current_role != "trim dac" or pd.isna(record["description"]):
            continue
        pattern.at[index, "description"] = re.sub(
            r"(?im)(=\s*)(x+)(\s*)$",
            lambda match: match.group(1) + ("0" * len(match.group(2))) + "*" + match.group(3),
            str(record["description"]),
        )


def _compile_one():
    return compile_trim_specs(
        _flow_row(),
        _pattern_rows("Mr_VDDD_DC", "7,MR_DAC[3:0]=0000*"),
    )


def _flow_row(
    *,
    item="Mr_VDDD_DC",
    bits=4,
    step="/",
    line="yes",
    unit="V",
    force="0uA",
    target=1.2,
    pe="no",
    dac_adj="/",
):
    return pd.DataFrame(
        [
            {
                "CP NO": "CP1",
                "item": item,
                "type": "trim",
                "sub": "/",
                "Recipe": "ENTER\nTRIM\nJUDGE",
                "mode": "fbist",
                "DAC bit": bits,
                "step": step,
                "LINE": line,
                "Bisection": "both_m",
                "PE": pe,
                "DAC ADJ": dac_adj,
                "FV/FI": force,
                "meas pin": "TP",
                "low_range(%)": "-1%",
                "target": target,
                "high_range(%)": "+1%",
                "UNIT": unit,
                "Vcc": "VCC_TYP",
            }
        ]
    )


def _pattern_rows(item, dac_description, reuse=None, enter_description="7,trim_sel=1"):
    rows = [
        {
            "item": item,
            "addr": "0011101",
            "description": enter_description,
            "pattern": "trim mode",
        }
    ]
    if reuse is not None:
        rows.append(
            {
                "item": None,
                "addr": None,
                "description": reuse,
                "pattern": "reuse dac",
            }
        )
    rows.append(
        {
            "item": None,
            "addr": "0000010",
            "description": dac_description,
            "pattern": "trim dac",
        }
    )
    return pd.DataFrame(rows)


def _nm_pattern_rows():
    return pd.DataFrame(
        [
            {"No": 1, "used": "page erase 1st", "Pattern name": "fbist_erase_main_1st_page.pat"},
            {"No": 2, "used": "page program PCKB 1st", "Pattern name": "fbist_pgm_main_1st_page.pat"},
        ]
    )


if __name__ == "__main__":
    unittest.main()
