import io
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from flow_recipe import (
    DacWritePlan,
    DacWritePlanSet,
    ResultExportPlan,
    ResultExportPlanSet,
)
from program_gen.core import pattern_data
from program_gen import state as G
from program_gen.platforms.chroma import writers as chroma_writers
from program_gen.platforms.chroma import startup as chroma_startup
from program_gen.platforms.s100.writers import write_full_scan_best_update
from program_gen.platforms.s100 import writers as s100_writers
from program_gen.platforms.s100 import startup as s100_startup
from tests.workspace_paths import FORMAL_MASTER, S100_SEED_ROOT


class TrimWriterAdapterTests(unittest.TestCase):
    def test_chroma_uid_trim_globals_use_generated_trim_identity(self):
        flow_columns = {
            "CP NO": ["CP1", "CP3"],
            "type": ["trim", "trim"],
            "OTP": ["no", "no"],
            "item": ["Hsi_8M", "Hsi_8M"],
            "UID": ["yes", "yes"],
            "PUMP": ["no", "no"],
            "Recipe": ["ENTER-TRIM-JUDGE", "ENTER-TRIM-JUDGE"],
        }

        def fake_col(sheet, column):
            if sheet == "VERSION" and column == "page word":
                return [1]
            if sheet == "FLOW":
                return flow_columns[column]
            if sheet == "ADDR_MAP" and column == "Word No.":
                return []
            raise AssertionError(f"unexpected column access: {sheet}.{column}")

        output = io.StringIO()
        import pandas as pd
        field = SimpleNamespace(page="uid", register="Hsi_8M_Trim")
        catalog = SimpleNamespace(resolve_fields=lambda item: (field,))
        with (
            patch.object(chroma_startup.G, "col", side_effect=fake_col),
            patch.object(chroma_startup.G, "FLOW", pd.DataFrame(flow_columns)),
            patch.object(chroma_startup.G, "ADDR_MAP", pd.DataFrame()),
            patch.object(chroma_startup.G, "compiled_adapter", SimpleNamespace(addr_map_catalog=catalog)),
            patch.object(chroma_startup, "reuse_dac_restore_items", return_value=[]),
        ):
            chroma_startup.item_variable_created(["PROGRAM_CP3"], 0, output)

        generated = output.getvalue()
        self.assertIn("REG_HSI_8M_TRIM[MAX_SITE]", generated)
        self.assertNotIn("REG_HSI_8M[MAX_SITE]", generated)

    def test_explicit_raw_export_declares_and_assigns_one_global_per_site(self):
        export_plan = ResultExportPlan(
            flow_row_index=0, item="Vrefint", sub="/", flow_type="verify",
            source_kind="MEASUREMENT", format="RAW", symbol="VREFINT_EXPORT",
            c_type="double", explicit=True, implied_by_uid=False,
        )
        export_plans = ResultExportPlanSet((export_plan,))
        flow_row = {
            "CP NO": "CP2", "type": "verify", "mode": "fbist",
            "item": "Vrefint", "Vcc": "VCC_TYP", "UID": "no",
            "UNIT": "V", "meas pin": "TP", "FV/FI": "0uA", "target": 1.2,
            "low_range(%)": 1.5, "high_range(%)": 1.5, "PE": "no",
            "OTP": "no", "LINE": "/", "Recipe": "ENTER-JUDGE-EXPORT",
            "Hbin": 1,
        }

        def fake_col(sheet, column):
            if sheet == "VERSION" and column == "page word":
                return [1]
            if sheet == "FLOW":
                if column == "PUMP":
                    return ["no"]
                return [flow_row[column]]
            if sheet == "ADDR_MAP" and column == "Word No.":
                return []
            raise AssertionError(f"unexpected column access: {sheet}.{column}")

        for startup in (chroma_startup, s100_startup):
            with self.subTest(platform=startup.__name__):
                output = io.StringIO()
                extra = (
                    patch.object(startup, "adc_global_decls", return_value="")
                    if startup is s100_startup
                    else patch.object(startup.G, "compiled_adapter", SimpleNamespace(
                        trim_specs={},
                        addr_map_catalog=SimpleNamespace(resolve_fields=lambda _item: ()),
                    ))
                )
                with (
                    patch.object(startup.G, "col", side_effect=fake_col),
                    patch.object(startup, "reuse_dac_restore_items", return_value=[]),
                    patch.object(startup, "generated_flow_item_name", return_value="Vrefint_Verify"),
                    extra,
                ):
                    startup.item_variable_created(
                        ["PROGRAM_CP2"], 0, output,
                        result_export_plans=export_plans,
                    )
                self.assertEqual(output.getvalue().count(
                    "double VREFINT_EXPORT[MAX_SITE];"
                ), 1)

        for writers, assignment in (
            (chroma_writers, "VREFINT_EXPORT[SOCKET]=verifyValue[SOCKET];"),
            (s100_writers, "VREFINT_EXPORT[T_SOCKET]=GB[5+T_SOCKET*64];"),
        ):
            with self.subTest(platform=writers.__name__):
                output = io.StringIO()
                with (
                    patch.object(writers.G, "col", side_effect=fake_col),
                    patch.object(writers.G, "trash", []),
                    patch.object(writers.G, "i", 0),
                    patch.object(writers.G, "BASE_DIR", "base"),
                    patch.object(writers.G, "OUT_DIR", "out"),
                    patch.object(writers.G, "VERSION", __import__("pandas").DataFrame()),
                    patch.object(writers.G, "flow_row_flag", return_value=None),
                    patch.object(writers, "copy_file"),
                    patch.object(writers, "Force_Judge"),
                    patch.object(writers, "generated_flow_item_name", return_value="Vrefint_Verify"),
                    patch.object(writers, "flow_relay", return_value="/", create=True),
                    patch.object(writers, "vcc_rails_str", return_value="VCC", create=True),
                ):
                    writers.verify_item_write(
                        ["PROGRAM_CP2"], output, 0,
                        result_export_plan=export_plan,
                    )
                generated = output.getvalue()
                self.assertEqual(generated.count(assignment), 1)

    def test_export_named_formats_emit_existing_bcd_and_adc_algorithms(self):
        flow_row = {
            "CP NO": "CP1", "type": "verify", "mode": "fbist",
            "item": "Vrefint", "Vcc": "VCC_TYP", "UID": "yes",
            "UNIT": "V", "meas pin": "TP", "FV/FI": "0uA", "target": 1.2,
            "low_range(%)": 1.5, "high_range(%)": 1.5, "PE": "no",
            "OTP": "no", "LINE": "/", "Recipe": "JUDGE", "Hbin": 1,
        }

        def fake_col(sheet, column):
            if sheet == "VERSION" and column == "page word":
                return [1]
            if sheet == "FLOW":
                return [flow_row[column]]
            raise AssertionError(f"unexpected column access: {sheet}.{column}")

        cases = (
            (
                "BCD16_MV", "VREFINT_W",
                "VREFINT_W[SOCKET]=(int)(verifyValue[SOCKET]*1000+0.5);",
                "VREFINT_W[T_SOCKET]=(int)(GB[5+T_SOCKET*64]*1000+0.5);",
            ),
            (
                "ADC12_3V3", "VREFINT_W",
                "VREFINT_W[SOCKET]=(int)(verifyValue[SOCKET]/3.3*4096);",
                "VREFINT_W[T_SOCKET]=(int)(GB[5+T_SOCKET*64]/3.3*4096);",
            ),
        )
        for export_format, symbol, chroma_line, s100_line in cases:
            plan = ResultExportPlan(
                flow_row_index=0, item="Vrefint", sub="/", flow_type="verify",
                source_kind="MEASUREMENT", format=export_format, symbol=symbol,
                c_type="int", explicit=False, implied_by_uid=True,
            )
            for writers, expected in (
                (chroma_writers, chroma_line),
                (s100_writers, s100_line),
            ):
                with self.subTest(format=export_format, platform=writers.__name__):
                    output = io.StringIO()
                    with (
                        patch.object(writers.G, "col", side_effect=fake_col),
                        patch.object(writers.G, "trash", []),
                        patch.object(writers.G, "i", 0),
                        patch.object(writers.G, "BASE_DIR", "base"),
                        patch.object(writers.G, "OUT_DIR", "out"),
                        patch.object(writers.G, "VERSION", __import__("pandas").DataFrame()),
                        patch.object(writers.G, "flow_row_flag", return_value=None),
                        patch.object(writers, "copy_file"),
                        patch.object(writers, "Force_Judge"),
                        patch.object(writers, "generated_flow_item_name", return_value="Vrefint_Verify"),
                        patch.object(writers, "flow_relay", return_value="/", create=True),
                        patch.object(writers, "vcc_rails_str", return_value="VCC", create=True),
                    ):
                        writers.verify_item_write(
                            ["PROGRAM_CP1"], output, 0,
                            result_export_plan=plan,
                        )
                    self.assertEqual(output.getvalue().count(expected), 1)

    def test_cp_without_trim_declares_dac_final_required_by_dac_write(self):
        dac_write_plans = DacWritePlanSet((DacWritePlan(
            flow_row_index=0,
            item="Mr_VDDD_DC",
            dac_symbol="MR_VDDD_DC_DAC_FINAL",
            pattern_name="set_mr_vddd_dc_dac",
            helper_name="set_mr_vddd_dc_trim_data",
            default_value="0000",
            field_width=4,
            value_source="ADDR_MAP",
            value=None,
            needs_global_variable=True,
            needs_set_helper=True,
        ),))
        flow_columns = {
            "CP NO": ["CP2"],
            "type": ["verify"],
            "OTP": ["no"],
            "item": ["Mr_VDDD_DC"],
            "UID": ["no"],
            "PUMP": ["no"],
        }

        def fake_col(sheet, column):
            if sheet == "VERSION" and column == "page word":
                return [1]
            if sheet == "FLOW":
                return flow_columns[column]
            if sheet == "ADDR_MAP" and column == "Word No.":
                return []
            raise AssertionError(f"unexpected column access: {sheet}.{column}")

        for startup in (chroma_startup, s100_startup):
            with self.subTest(platform=startup.__name__):
                output = io.StringIO()
                patches = [
                    patch.object(startup.G, "col", side_effect=fake_col),
                    patch.object(startup, "reuse_dac_restore_items", return_value=[]),
                    patch.object(startup, "generated_flow_item_name", return_value="Mr_VDDD_DC_Verify"),
                ]
                if startup is s100_startup:
                    patches.append(patch.object(startup, "adc_global_decls", return_value=""))
                with patches[0], patches[1], patches[2], patches[3] if len(patches) > 3 else patch.object(
                    startup.G, "compiled_adapter", SimpleNamespace(
                        trim_specs={},
                        addr_map_catalog=SimpleNamespace(resolve_fields=lambda _item: ()),
                    )
                ):
                    startup.item_variable_created(
                        ["PROGRAM_CP2"], 0, output, dac_write_plans=dac_write_plans
                    )
                self.assertIn(
                    "int MR_VDDD_DC_DAC_FINAL[MAX_SITE];",
                    output.getvalue(),
                )

    def test_missing_cp_trim_emits_one_dac_set_helper_on_each_platform(self):
        operation = DacWritePlan(
            flow_row_index=0,
            item="Mr_VDDD_DC",
            dac_symbol="MR_VDDD_DC_DAC_FINAL",
            pattern_name="set_mr_vddd_dc_dac",
            helper_name="set_mr_vddd_dc_trim_data",
            field_width=4,
            default_value="0000",
            value_source="ADDR_MAP",
            value=None,
            needs_global_variable=True,
            needs_set_helper=True,
        )
        dac_write_plans = DacWritePlanSet((operation,))

        for writers, expected_header, expected_run in (
            (
                chroma_writers,
                "set_mr_vddd_dc_trim_data(int* a)",
                "JUDGE_PAT(set_mr_vddd_dc_dac,__set_mr_vddd_dc_dac);",
            ),
            (
                s100_writers,
                "@@MACRO set_mr_vddd_dc_trim_data(int* a)",
                "RUN_PATTERN(set_mr_vddd_dc_dac:START,set_mr_vddd_dc_dac:END,1,TS_5MHZ);",
            ),
        ):
            with self.subTest(platform=writers.__name__):
                output = io.StringIO()
                with (
                    patch.object(writers, "dynamic_enter_operations", return_value=()),
                    patch.object(writers, "dynamic_recipe_enter_operations", return_value=()),
                    patch.object(writers, "copy_file"),
                    patch.object(writers.G, "BASE_DIR", "base"),
                    patch.object(writers.G, "OUT_DIR", "out"),
                    patch.object(writers, "_trim_variable_slots_for_merged_row",
                                 return_value=[(0, "3,MR_DAC[3:0]=0000*")]),
                    patch.object(writers.G, "col", return_value=["PA13"]),
                    patch.object(writers.G, "i", 0),
                ):
                    writers.dynamic_enter_helpers_write(
                        ["PROGRAM_CP2"], output, {}, "CP2", ["set_mr_vddd_dc_dac"], {},
                        dac_write_plans=dac_write_plans,
                    )
                generated = output.getvalue()
                self.assertEqual(generated.count(expected_header), 1)
                self.assertIn(expected_run, generated)

    def test_verify_dac_write_uses_existing_trim_helper_before_measurement(self):
        recipe_row = SimpleNamespace(operations=(
            SimpleNamespace(name="ENTER", pattern_role="trim mode", value_source="DEFAULT"),
            SimpleNamespace(
                name="DAC_WRITE",
                pattern_role="trim dac",
                value_source="DAC_FINAL",
                value=None,
                dynamic_field=SimpleNamespace(value="0000", width=4),
                requires_set_helper=False,
            ),
            SimpleNamespace(name="JUDGE", pattern_role=None, value=None),
        ))
        flow_row = {
            "CP NO": "CP1", "type": "verify", "mode": "fbist",
            "item": "Mr_VDDD_DC", "Vcc": "VCC_TYP", "UID": "no",
            "UNIT": "V", "meas pin": "TP", "FV/FI": "0uA", "target": 1.2,
            "low_range(%)": 1.5, "high_range(%)": 1.5, "PE": "no",
            "OTP": "no", "LINE": "/", "Recipe": "ENTER(ROLE=TRIM)-DAC_WRITE-JUDGE",
            "Hbin": 1,
        }

        def fake_col(sheet, column):
            if sheet == "VERSION" and column == "page word":
                return [1]
            if sheet == "FLOW":
                return [flow_row[column]]
            raise AssertionError(f"unexpected column access: {sheet}.{column}")

        for writers, expected in (
            (chroma_writers, "set_mr_vddd_dc_trim_data(MR_VDDD_DC_DAC_FINAL);"),
            (s100_writers, "CALL_MACRO set_mr_vddd_dc_trim_data(MR_VDDD_DC_DAC_FINAL);"),
        ):
            with self.subTest(platform=writers.__name__):
                output = io.StringIO()
                dac_write_plan = DacWritePlan(
                    flow_row_index=0, item="Mr_VDDD_DC",
                    dac_symbol="MR_VDDD_DC_DAC_FINAL",
                    pattern_name="set_mr_vddd_dc_dac",
                    helper_name="set_mr_vddd_dc_trim_data",
                    default_value="0000", field_width=4,
                    value_source="DAC_FINAL", value=None,
                    needs_global_variable=False, needs_set_helper=False,
                )
                with (
                    patch.object(writers.G, "col", side_effect=fake_col),
                    patch.object(writers.G, "trash", []),
                    patch.object(writers.G, "i", 0),
                    patch.object(writers.G, "BASE_DIR", "base"),
                    patch.object(writers.G, "OUT_DIR", "out"),
                    patch.object(writers.G, "VERSION", __import__("pandas").DataFrame()),
                    patch.object(writers.G, "flow_row_flag", return_value=None),
                    patch.object(writers, "copy_file"),
                    patch.object(writers, "Force_Judge"),
                    patch.object(writers, "generated_flow_item_name", return_value="Mr_VDDD_DC_Verify"),
                    patch.object(writers, "flow_relay", return_value="/", create=True),
                    patch.object(writers, "vcc_rails_str", return_value="VCC", create=True),
                ):
                    writers.verify_item_write(
                        ["PROGRAM_CP1"], output, 0, recipe_row,
                        dac_write_plan=dac_write_plan,
                    )
                self.assertIn(expected, output.getvalue())

    def test_verify_dac_write_restores_from_addr_map_when_cp_has_no_trim(self):
        recipe_row = SimpleNamespace(operations=(
            SimpleNamespace(name="ENTER", pattern_role="trim mode", value_source="DEFAULT"),
            SimpleNamespace(
                name="DAC_WRITE", pattern_role="trim dac", value_source="ADDR_MAP",
                value=None, dynamic_field=SimpleNamespace(value="0000", width=4),
                requires_set_helper=True,
            ),
            SimpleNamespace(name="JUDGE", pattern_role=None, value=None),
        ))
        flow_row = {
            "CP NO": "CP2", "type": "verify", "mode": "fbist",
            "item": "Mr_VDDD_DC", "Vcc": "VCC_TYP", "UID": "no",
            "UNIT": "V", "meas pin": "TP", "FV/FI": "0uA", "target": 1.2,
            "low_range(%)": 1.5, "high_range(%)": 1.5, "PE": "no",
            "OTP": "no", "LINE": "/", "Recipe": "ENTER(ROLE=TRIM)-DAC_WRITE-JUDGE",
            "Hbin": 1,
        }

        def fake_col(sheet, column):
            if sheet == "VERSION" and column == "page word":
                return [1]
            if sheet == "FLOW":
                return [flow_row[column]]
            raise AssertionError(f"unexpected column access: {sheet}.{column}")

        for writers, site, call in (
            (
                chroma_writers,
                "SOCKET",
                "set_mr_vddd_dc_trim_data(MR_VDDD_DC_DAC_FINAL);",
            ),
            (
                s100_writers,
                "T_SOCKET",
                "CALL_MACRO set_mr_vddd_dc_trim_data(MR_VDDD_DC_DAC_FINAL);",
            ),
        ):
            with self.subTest(platform=writers.__name__):
                output = io.StringIO()
                expr = f"(REG_PMU_TRIM2[{site}]&0x00F0)>>4"
                dac_write_plan = DacWritePlan(
                    flow_row_index=0, item="Mr_VDDD_DC",
                    dac_symbol="MR_VDDD_DC_DAC_FINAL",
                    pattern_name="set_mr_vddd_dc_dac",
                    helper_name="set_mr_vddd_dc_trim_data",
                    default_value="0000", field_width=4,
                    value_source="ADDR_MAP", value=None,
                    needs_global_variable=True, needs_set_helper=True,
                )
                with (
                    patch.object(writers.G, "col", side_effect=fake_col),
                    patch.object(writers.G, "trash", []),
                    patch.object(writers.G, "i", 0),
                    patch.object(writers.G, "BASE_DIR", "base"),
                    patch.object(writers.G, "OUT_DIR", "out"),
                    patch.object(writers.G, "VERSION", __import__("pandas").DataFrame()),
                    patch.object(writers.G, "flow_row_flag", return_value=None),
                    patch.object(writers, "copy_file"),
                    patch.object(writers, "Force_Judge"),
                    patch.object(writers, "generated_flow_item_name", return_value="Mr_VDDD_DC_Verify"),
                    patch.object(writers, "flow_relay", return_value="/", create=True),
                    patch.object(writers, "vcc_rails_str", return_value="VCC", create=True),
                    patch.object(writers, "_dac_final_addrmap_expr", return_value=expr),
                ):
                    writers.verify_item_write(
                        ["PROGRAM_CP2"], output, 0, recipe_row,
                        dac_write_plan=dac_write_plan,
                    )
                generated = output.getvalue()
                assignment = f"MR_VDDD_DC_DAC_FINAL[{site}]={expr};"
                self.assertIn(assignment, generated)
                self.assertLess(generated.index(assignment), generated.index(call))

    def test_verify_dac_write_fixed_value_builds_per_site_data_without_addr_map(self):
        recipe_row = SimpleNamespace(operations=(
            SimpleNamespace(name="ENTER", pattern_role="trim mode", value_source="DEFAULT"),
            SimpleNamespace(
                name="DAC_WRITE", pattern_role="trim dac", value_source="ARGUMENT",
                value="0011", dynamic_field=SimpleNamespace(value="0000", width=4),
                requires_set_helper=True,
            ),
            SimpleNamespace(name="JUDGE", pattern_role=None, value=None),
        ))
        flow_row = {
            "CP NO": "CP2", "type": "verify", "mode": "fbist",
            "item": "Mr_VDDD_DC", "Vcc": "VCC_TYP", "UID": "no",
            "UNIT": "V", "meas pin": "TP", "FV/FI": "0uA", "target": 1.2,
            "low_range(%)": 1.5, "high_range(%)": 1.5, "PE": "no",
            "OTP": "no", "LINE": "/", "Recipe": "ENTER(ROLE=TRIM)-DAC_WRITE(0011)-JUDGE",
            "Hbin": 1,
        }

        def fake_col(sheet, column):
            if sheet == "VERSION" and column == "page word":
                return [1]
            if sheet == "FLOW":
                return [flow_row[column]]
            raise AssertionError(f"unexpected column access: {sheet}.{column}")

        for writers, assignment in (
            (chroma_writers, "dacWriteData[SOCKET]=3;"),
            (s100_writers, "dacWriteData[T_SOCKET]=3;"),
        ):
            with self.subTest(platform=writers.__name__):
                output = io.StringIO()
                dac_write_plan = DacWritePlan(
                    flow_row_index=0, item="Mr_VDDD_DC",
                    dac_symbol="MR_VDDD_DC_DAC_FINAL",
                    pattern_name="set_mr_vddd_dc_dac",
                    helper_name="set_mr_vddd_dc_trim_data",
                    default_value="0000", field_width=4,
                    value_source="ARGUMENT", value="0011",
                    needs_global_variable=False, needs_set_helper=True,
                )
                with (
                    patch.object(writers.G, "col", side_effect=fake_col),
                    patch.object(writers.G, "trash", []),
                    patch.object(writers.G, "i", 0),
                    patch.object(writers.G, "BASE_DIR", "base"),
                    patch.object(writers.G, "OUT_DIR", "out"),
                    patch.object(writers.G, "VERSION", __import__("pandas").DataFrame()),
                    patch.object(writers.G, "flow_row_flag", return_value=None),
                    patch.object(writers, "copy_file"),
                    patch.object(writers, "Force_Judge"),
                    patch.object(writers, "generated_flow_item_name", return_value="Mr_VDDD_DC_Verify"),
                    patch.object(writers, "flow_relay", return_value="/", create=True),
                    patch.object(writers, "vcc_rails_str", return_value="VCC", create=True),
                    patch.object(writers, "_dac_final_addrmap_expr",
                                 side_effect=AssertionError("fixed DAC must not read ADDR_MAP")),
                ):
                    writers.verify_item_write(
                        ["PROGRAM_CP2"], output, 0, recipe_row,
                        dac_write_plan=dac_write_plan,
                    )
                generated = output.getvalue()
                self.assertIn(assignment, generated)
                self.assertNotIn("MR_VDDD_DC_DAC_FINAL[SOCKET]=3;", generated)
                self.assertNotIn("MR_VDDD_DC_DAC_FINAL[T_SOCKET]=3;", generated)

    def test_verify_dynamic_enter_writes_argument_then_restores_default(self):
        recipe_row = SimpleNamespace(operations=(
            SimpleNamespace(
                name="ENTER",
                pattern_role="verify mode",
                value_source="ARGUMENT",
                value="010",
                dynamic_field=SimpleNamespace(value="001", width=3),
            ),
            SimpleNamespace(name="JUDGE", pattern_role=None, value=None),
        ))
        flow_row = {
            "CP NO": "CP1", "type": "verify", "mode": "fbist",
            "item": "Mr_VDDD_DC", "Vcc": "VCC_TYP", "UID": "no",
            "UNIT": "/", "meas pin": "/", "FV/FI": "/", "target": "/",
            "low_range(%)": "/", "high_range(%)": "/", "PE": "no",
            "OTP": "no", "LINE": "/", "Recipe": "ENTER(010)-JUDGE",
            "Hbin": 1,
        }

        def fake_col(sheet, column):
            if sheet == "VERSION" and column == "page word":
                return [1]
            if sheet == "FLOW":
                return [flow_row[column]]
            raise AssertionError(f"unexpected column access: {sheet}.{column}")

        for writers, set_argument, run_enter, restore_default in (
            (
                chroma_writers,
                "set_enter_mr_vddd_dc_verify_data(2);",
                "JUDGE_PAT(enter_mr_vddd_dc_verify",
                "set_enter_mr_vddd_dc_verify_data(1);",
            ),
            (
                s100_writers,
                "CALL_MACRO set_enter_mr_vddd_dc_verify_data(2);",
                "RUN_PATTERN(enter_mr_vddd_dc_verify:START",
                "CALL_MACRO set_enter_mr_vddd_dc_verify_data(1);",
            ),
        ):
            with self.subTest(platform=writers.__name__):
                output = io.StringIO()
                with (
                    patch.object(writers.G, "col", side_effect=fake_col),
                    patch.object(writers.G, "trash", []),
                    patch.object(writers.G, "i", 0),
                    patch.object(writers.G, "BASE_DIR", "base"),
                    patch.object(writers.G, "OUT_DIR", "out"),
                    patch.object(writers.G, "VERSION", __import__("pandas").DataFrame()),
                    patch.object(writers.G, "flow_row_flag", return_value=None),
                    patch.object(writers, "copy_file"),
                    patch.object(writers, "Force_Judge"),
                    patch.object(writers, "generated_flow_item_name", return_value="Mr_VDDD_DC_Verify"),
                    patch.object(writers, "flow_relay", return_value="/", create=True),
                    patch.object(writers, "vcc_rails_str", return_value="VCC", create=True),
                ):
                    writers.verify_item_write(["PROGRAM_CP1"], output, 0, recipe_row)
                generated = output.getvalue()
                self.assertLess(generated.index(set_argument), generated.index(run_enter))
                self.assertLess(generated.index(run_enter), generated.index(restore_default))

    def test_verify_writers_execute_explicit_enter_role_and_external_run_in_order(self):
        recipe_row = SimpleNamespace(operations=(
            SimpleNamespace(name="ENTER", pattern_role="trim mode", value=None),
            SimpleNamespace(name="RUN", pattern_role=None, value="external_ready_pattern"),
            SimpleNamespace(name="JUDGE", pattern_role=None, value=None),
        ))
        flow_row = {
            "CP NO": "CP1", "type": "verify", "mode": "fbist",
            "item": "Mr_VDDD_DC", "Vcc": "VCC_TYP", "UID": "no",
            "UNIT": "/", "meas pin": "/", "FV/FI": "/", "target": "/",
            "low_range(%)": "/", "high_range(%)": "/", "PE": "no",
            "OTP": "no", "LINE": "/", "Recipe": "ENTER(ROLE=TRIM)-RUN(external_ready_pattern)-JUDGE",
            "Hbin": 1,
        }

        def fake_col(sheet, column):
            if sheet == "VERSION" and column == "page word":
                return [1]
            if sheet == "FLOW":
                return [flow_row[column]]
            raise AssertionError(f"unexpected column access: {sheet}.{column}")

        for writers, expected in (
            (chroma_writers, ("JUDGE_PAT(enter_mr_vddd_dc", "JUDGE_PAT(external_ready_pattern")),
            (s100_writers, ("RUN_PATTERN(enter_mr_vddd_dc:START", "RUN_PATTERN(external_ready_pattern:START")),
        ):
            with self.subTest(platform=writers.__name__):
                output = io.StringIO()
                with (
                    patch.object(writers.G, "col", side_effect=fake_col),
                    patch.object(writers.G, "trash", []),
                    patch.object(writers.G, "i", 0),
                    patch.object(writers.G, "BASE_DIR", "base"),
                    patch.object(writers.G, "OUT_DIR", "out"),
                    patch.object(writers.G, "VERSION", __import__("pandas").DataFrame()),
                    patch.object(writers.G, "flow_row_flag", return_value=None),
                    patch.object(writers, "copy_file"),
                    patch.object(writers, "Force_Judge"),
                    patch.object(writers, "generated_flow_item_name", return_value="Mr_VDDD_DC_Verify"),
                    patch.object(writers, "flow_relay", return_value="/", create=True),
                    patch.object(writers, "vcc_rails_str", return_value="VCC", create=True),
                ):
                    writers.verify_item_write(["PROGRAM_CP1"], output, 0, recipe_row)
                generated = output.getvalue()
                self.assertIn(expected[0], generated)
                self.assertIn(expected[1], generated)
                self.assertLess(generated.index(expected[0]), generated.index(expected[1]))

    def test_cross_cp_restore_uses_explicit_depend_recipe_without_reuse_metadata(self):
        original_cwd = Path.cwd()
        try:
            G.init(
                str(S100_SEED_ROOT),
                platform="s100",
                mode="production",
                master=str(FORMAL_MASTER),
            )
            self.assertEqual(pattern_data.reuse_dac_restore_items("CP1"), [])
            self.assertEqual(pattern_data.reuse_dac_restore_items("CP3"), ["Hsi_Vrega"])
        finally:
            os.chdir(original_cwd)

    def test_s100_full_scan_records_actual_dac_for_compiled_search_domain(self):
        output = io.StringIO()

        write_full_scan_best_update(output, "PCLK_DAC_FINAL", explicit_codes=True)

        generated = output.getvalue()
        self.assertIn("PCLK_DAC_FINAL[T_SOCKET] = trimDac[T_SOCKET];", generated)
        self.assertNotIn("PCLK_DAC_FINAL[T_SOCKET] = cyc - 1;", generated)

    def test_s100_legacy_natural_scan_keeps_existing_index_semantics(self):
        output = io.StringIO()

        write_full_scan_best_update(output, "LEGACY_DAC_FINAL", explicit_codes=False)

        self.assertIn(
            "LEGACY_DAC_FINAL[T_SOCKET] = cyc - 1;",
            output.getvalue(),
        )

    def test_reuse_dac_uses_logical_item_and_explicit_trim_dac_role(self):
        pairs = [("Hsi_8M", "Hsi_Vrega")]
        with patch.object(pattern_data, "_reuse_dac_pairs", return_value=pairs):
            self.assertEqual(pattern_data.reuse_dac_pattern("Hsi_8M"), "set_hsi_vrega_dac")
            self.assertEqual(pattern_data.reuse_dac_pattern("Hsi_8M_Trim"), "set_hsi_vrega_dac")

    def test_restore_items_ignore_verify_only_flow_rows(self):
        columns = {
            ("FLOW", "item"): ["Hsi_8M", "Hsi_8M"],
            ("FLOW", "CP NO"): ["CP2", "CP3"],
            ("FLOW", "type"): ["verify", "trim"],
        }

        def col(sheet, column):
            return list(columns[(sheet, column)])

        with (
            patch.object(pattern_data, "_reuse_dac_pairs", return_value=[("Hsi_8M", "Hsi_Vrega")]),
            patch.object(pattern_data.G, "col", side_effect=col),
        ):
            self.assertEqual(pattern_data.reuse_dac_restore_items("CP2"), [])
            self.assertEqual(pattern_data.reuse_dac_restore_items("CP3"), ["Hsi_Vrega"])

    def test_set_all_final_uses_shared_dac_symbol_for_logical_item(self):
        columns = {
            ("FLOW", "PUMP"): ["yes"],
            ("FLOW", "item"): ["Iref1u"],
            ("FLOW", "DAC bit"): [4],
            ("VERSION", "SWD PIN"): ["PA13"],
        }

        def col(sheet, column):
            return list(columns[(sheet, column)])

        for writers, expected_variable, expected_label in (
            (chroma_writers, "IREF1U_DAC_FINAL[SOCKET]", "set_all_final_vposp:iref1u+"),
            (s100_writers, "IREF1U_DAC_FINAL", "set_all_final_vposp:iref1u_st"),
        ):
            with self.subTest(platform=writers.__name__):
                output = io.StringIO()
                writers.G.i = 0
                with patch.object(writers.G, "col", side_effect=col):
                    writers.set_all_final_vposp(output)
                generated = output.getvalue()
                self.assertIn(expected_variable, generated)
                self.assertIn(expected_label, generated)
                self.assertNotIn("IREF1UDAC_FINAL", generated)

    def test_cross_cp_dac_restore_resolves_logical_item_against_trim_addrmap_name(self):
        columns = {
            ("ADDR_MAP", "CP addr map"): ["Other[3:0],Hsi_Vrega_Trim[4:0],Tail[6:0]"],
            ("ADDR_MAP", "bit[15:0]"): ["trim0_word0[15:0]"],
        }

        def col(sheet, column):
            return list(columns[(sheet, column)])

        for writers, socket_name in (
            (chroma_writers, "SOCKET"),
            (s100_writers, "T_SOCKET"),
        ):
            with self.subTest(platform=writers.__name__):
                with patch.object(writers.G, "col", side_effect=col):
                    expr = writers._dac_final_addrmap_expr("Hsi_Vrega")
                self.assertIsNotNone(expr)
                self.assertIn(f"REG_TRIM0_WORD0[{socket_name}]", expr)
                self.assertTrue(expr.endswith(">>7"), expr)


if __name__ == "__main__":
    unittest.main()
