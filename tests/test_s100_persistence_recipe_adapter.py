import io
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

from flow_recipe import RecipeAssignment, RecipeValueToken
from flow_recipe import compile_recipe_rows
from program_gen.compiler import (
    _compile_build_uid_rows,
)
from program_gen.core.addr_map import compile_addr_map_catalog
from program_gen.core.persistence_recipe import compile_persistence_plan_set
from program_gen.core.uid_plan import compile_id_plan_set
from program_gen.platforms.s100 import main as s100_main
from program_gen.platforms.s100 import writers


class S100PersistenceRecipeAdapterTests(unittest.TestCase):
    def test_s100_main_prioritizes_commit_shmoo_over_measurement_shmoo(self):
        output = io.StringIO()
        with (
            patch.object(s100_main, "commit_shmoo_item_write") as commit_writer,
            patch.object(s100_main, "shmoo_item_write") as measure_writer,
        ):
            handled = s100_main.write_shmoo_row(
                ["PROGRAM_CP2"], output, 3,
                commit_plans={3: "commit-plan"},
                measurement_plans={3: "measure-plan"},
            )

        self.assertTrue(handled)
        commit_writer.assert_called_once_with(["PROGRAM_CP2"], output, "commit-plan")
        measure_writer.assert_not_called()

    def test_readotpmap_effective_pages_are_forwarded_to_writer(self):
        operation = SimpleNamespace(
            module="READOTPMAP", requested_pages=("uid",), effective_pages=(),
        )
        row_plan = SimpleNamespace(operations=(operation,))
        self.assertEqual(
            s100_main.persistence_effective_pages(row_plan, "READOTPMAP"), ()
        )

    def test_s100_cp_plan_deduplicates_same_read_page_across_writer_rows(self):
        flow = pd.DataFrame([
            {"CP NO": "CP2", "item": "Pgm_CP1_BakeID", "type": "uid",
             "sub": "/", "Recipe": "READOTPMAP(UID)"},
            {"CP NO": "CP2", "item": "Pgm_CP2ID_Read", "type": "uid",
             "sub": "/", "Recipe": "READOTPMAP(UID)"},
        ])
        rows = compile_recipe_rows(
            flow, pd.DataFrame(columns=("item", "addr", "description", "pattern"))
        )
        catalog = compile_addr_map_catalog(pd.DataFrame([{
            "Word No.": "uid", "line": "CP1,CP2", "bit[31:16]": "reverse",
            "bit[15:0]": "UID_REG0[15:0]", "data type": "lable",
            "CP Data[31:0]": "32'hFFFF_0000", "CP addr map": "UID_FIELD[15:0]",
        }]))

        plans = compile_persistence_plan_set(flow, rows, catalog).rows

        self.assertEqual(
            s100_main.persistence_effective_pages(plans[0], "READOTPMAP"),
            ("uid",),
        )
        self.assertEqual(
            s100_main.persistence_effective_pages(plans[1], "READOTPMAP"),
            (),
        )

    def test_id_rows_are_compiled_by_full_protocol_not_bake_substring(self):
        flow = pd.DataFrame([
            {"CP NO": "CP1", "type": "id", "item": "Read_CP1_BakeID"},
            {"CP NO": "CP1", "type": "uid", "item": "Pgm_CP1_BakeID_Read"},
            {"CP NO": "CP2", "type": "uid", "item": "Pgm_CP2ID_Read"},
        ])
        plans = compile_id_plan_set(flow).rows

        self.assertEqual(plans[0].role, "PRODUCE_GATE")
        self.assertEqual(plans[1].target.kind, "BAKEID")
        self.assertEqual(plans[2].target.kind, "ID")

    def test_unknown_uid_item_is_rejected_instead_of_substring_inferred(self):
        flow = pd.DataFrame([{"CP NO": "CP1", "type": "uid", "item": "MaybeBakeWriter"}])
        with self.assertRaisesRegex(ValueError, "unknown ID item protocol"):
            compile_id_plan_set(flow)

    def test_commit_shmoo_uid_program_adds_failed_site_reerase(self):
        from program_gen.core.commit_shmoo import (
            CommitShmooPhysicalAction, CommitShmooPlan, CommitShmooPoint,
        )
        point = CommitShmooPoint(
            step=0, field_writes=(), affected_pages=("uid",),
            physical_actions=(CommitShmooPhysicalAction("PGMOTP", ("uid",)),),
        )
        plan = CommitShmooPlan(
            cp="CP2", steps=(0,), points=(point,),
            item="UID_COMMIT", vcc="VCC_TYP",
        )
        output = io.StringIO()
        with (
            patch.object(writers.G, "i", 0),
            patch.object(writers.G, "BASE_DIR", "base"),
            patch.object(writers.G, "OUT_DIR", "out"),
            patch.object(writers, "copy_file"),
            patch.object(writers, "epr_pattern_capture", return_value={
                "erase": "erase_uid", "pgm": "pgm_uid", "read": "read_uid",
            }),
        ):
            writers.commit_shmoo_item_write(["PROGRAM_CP2"], output, plan)

        generated = output.getvalue()
        self.assertIn("Sys_DriverResult[T_SOCKET] > 0.5", generated)
        self.assertEqual(generated.count("RUN_PATTERN(erase_uid:START"), 2)

    def test_fixed_commit_merges_same_register_and_preserves_other_bits(self):
        addr_map = pd.DataFrame([{
            "Word No.": "trim1", "RA": "0x01", "line": "CP2",
            "bit[31:16]": "~ANA_MUX_TRIM2[15:0]",
            "bit[15:0]": "ANA_MUX_TRIM2[15:0]", "data type": "lable",
            "Default": "0xFFFF0000",
            "CP Data[31:0]": "0xFFFF0000",
            "CP addr map": "OTHER[13:4],DLPR1_VSEL_OP_VDDK[1:0],DLPR0_VSEL_OP_VDDK[1:0]",
        }])
        recipe_row = SimpleNamespace(operations=(SimpleNamespace(
            name="COMMIT",
            assignments=(
                RecipeAssignment("DLPR0_VSEL_OP_VDDK", RecipeValueToken("DECIMAL", "1")),
                RecipeAssignment("DLPR1_VSEL_OP_VDDK", RecipeValueToken("VARIABLE", "TARGET_SEL")),
            ),
        ),))
        output = io.StringIO()
        result = {"pgm": "pgm_trim1", "read": "read_trim1"}
        with (
            patch.object(writers.G, "ADDR_MAP", addr_map),
            patch.object(writers.G, "i", 0),
            patch.object(writers.G, "col", side_effect=lambda sheet, column: [0] if (sheet, column) == ("VERSION", "SWD PIN") else []),
            patch.object(writers, "epr_pattern_capture", return_value=result),
            patch.object(writers, "write_pat_mem") as write_pattern,
        ):
            catalog = compile_addr_map_catalog(addr_map)
            pages = writers.write_fixed_commit(
                recipe_row, output, cp="CP2", catalog=catalog
            )

        generated = output.getvalue()
        self.assertEqual(pages, ("trim1",))
        self.assertIn("REG_ANA_MUX_TRIM2[T_SOCKET]&0xFFFC", generated)
        self.assertIn("(1&0x3)<<0", generated)
        self.assertIn("REG_ANA_MUX_TRIM2[T_SOCKET]&0xFFF3", generated)
        self.assertIn("(TARGET_SEL&0x3)<<2", generated)
        write_pattern.assert_called_once()

    def test_uid_recipe_policy_is_explicit_and_build_uid_is_not_cp3_implied(self):
        cp2 = SimpleNamespace(operations=tuple(
            SimpleNamespace(name=name) for name in ("BUILDUID", "COMMIT", "PGMOTP")
        ))
        cp3 = SimpleNamespace(operations=tuple(
            SimpleNamespace(name=name) for name in ("COMMIT", "PGMOTP")
        ))

        self.assertTrue(writers.uid_recipe_policy(cp2, legacy_build_uid=False).build_uid)
        self.assertFalse(writers.uid_recipe_policy(cp3, legacy_build_uid=True).build_uid)
        self.assertFalse(writers.uid_recipe_policy(cp3, legacy_build_uid=True).set_vposp)

    def test_build_uid_plan_is_bound_only_to_the_recipe_row_that_declares_it(self):
        flow = pd.DataFrame([
            {"CP NO": "CP2", "item": "Pgm_CP1_BakeID", "type": "uid",
             "sub": "/", "Recipe": "READOTPMAP(UID)-COMMIT-PGMOTP(UID)"},
            {"CP NO": "CP2", "item": "Pgm_CP2ID_Read", "type": "uid",
             "sub": "/", "Recipe": "BUILDUID-COMMIT-PGMOTP(UID)"},
        ])
        rows = compile_recipe_rows(
            flow, pd.DataFrame(columns=("item", "addr", "description", "pattern"))
        )

        plans = _compile_build_uid_rows(rows, "CP2")

        self.assertNotIn(0, plans)
        self.assertEqual(plans[1].cp, "CP2")
        self.assertTrue(plans[1].full_replace)
        self.assertIn("CRC", plans[1].fields)

    def test_uid_failed_site_cleanup_builds_full_mask_before_one_physical_erase(self):
        output = io.StringIO()
        writers.write_uid_failed_site_reerase(
            output,
            {"erase": "erase_uid"},
            vcc="VCC_TYP",
        )

        generated = output.getvalue()
        self.assertIn("Sys_DriverResult[T_SOCKET] > 0.5", generated)
        self.assertNotIn("Sys_DriverResult[T_SOCKET] <= 0.5", generated)
        self.assertIn("Sys_ActiveSite[T_SOCKET]=0", generated)
        self.assertIn(
            "\t\t}\n\n\t\tif(uidReeraseRequired==1)\n\t\t{\n"
            "\t\t\tCALL_MACRO POWER_ON(_C_VCC_TYP);",
            generated,
        )
        self.assertEqual(generated.count("RUN_PATTERN(erase_uid:START"), 1)
        self.assertEqual(generated.count("CALL_MACRO POWER_ON"), 1)
        self.assertEqual(generated.count("CALL_MACRO POWER_OFF"), 1)
        self.assertNotIn("set_all_final_vposp", generated)

    def test_generated_migrated_uid_plans_are_recipe_driven(self):
        program_root = (
            "S100_program/LAB/S100"
        )
        generated = {}
        from pathlib import Path
        for path in Path(program_root).glob("**/*.prg"):
            text = path.read_text(encoding="gb18030", errors="replace")
            cp = path.stem.rsplit("_", 1)[-1]
            generated[cp] = text
        if not {"CP1", "CP2", "CP3"}.issubset(generated):
            self.skipTest("run migrated CP1/2/3 generation before artifact audit")

        def plan(text, item):
            import re
            match = re.search(
                rf"(?s)@@PLAN {item}\b.*?@@END_PLAN", text,
                flags=re.IGNORECASE,
            )
            self.assertIsNotNone(match, item)
            return match.group(0)

        cp1 = plan(generated["CP1"], "Pgm_Cp1Id_Read")
        cp2 = plan(generated["CP2"], "Pgm_Cp2Id_Read")
        bake1 = plan(generated["CP2"], "Pgm_Cp1_Bakeid")
        cp3 = plan(generated["CP3"], "Pgm_Cp3Id_Read")
        bake2 = plan(generated["CP3"], "Pgm_Cp2_Bakeid")
        for uid_plan in (cp1, cp2, bake1, cp3, bake2):
            self.assertNotIn("RUN_PATTERN(set_all_final_vposp:", uid_plan)
            self.assertIn("Sys_DriverResult[T_SOCKET] > 0.5", uid_plan)
        for bake_plan in (bake1, bake2):
            self.assertLess(
                bake_plan.index("/////////////////////////check"),
                bake_plan.index("_BAKEID_FLAG[T_SOCKET]!=1"),
            )
        self.assertEqual(generated["CP2"].count("RUN_PATTERN(uid_capture:START"), 1)
        self.assertEqual(generated["CP3"].count("RUN_PATTERN(uid_capture:START"), 1)
        self.assertIn("LOT_ID", cp3)
        self.assertNotIn("LOT_ID", cp2)

    def _render_read(self, recipe_row):
        flow_row = {
            "CP NO": "CP2", "type": "read", "item": "Trimdata_Read",
            "Vcc": "VCC_TYP", "Hbin": 9,
        }

        def fake_col(sheet, column):
            if sheet == "VERSION":
                return {"page word": [1], "SWD PIN": [0]}[column]
            if sheet == "FLOW":
                return [flow_row[column]]
            if sheet == "ADDR_MAP":
                return []
            raise AssertionError(f"unexpected column access: {sheet}.{column}")

        output = io.StringIO()
        trim_plan = SimpleNamespace(bindings=(), for_cp=lambda _cp: ())
        with (
            patch.object(writers.G, "col", side_effect=fake_col),
            patch.object(writers.G, "FLOW", pd.DataFrame([flow_row])),
            patch.object(writers.G, "ADDR_MAP", pd.DataFrame()),
            patch.object(writers.G, "set_vposp_name", []),
            patch.object(writers.G, "i", 0),
            patch.object(writers.G, "BASE_DIR", "base"),
            patch.object(writers.G, "OUT_DIR", "out"),
            patch.object(writers.G, "flow_row_flag", return_value=None),
            patch.object(writers.G, "compiled_adapter", SimpleNamespace(trim_data_plan=trim_plan)),
            patch.object(writers, "copy_file"),
            patch.object(writers, "set_all_final_vposp") as prepare_vposp,
            patch.object(writers, "reuse_dac_restore_items", return_value=[]),
        ):
            writers.trim_data_read_write(
                ["PROGRAM_CP2"], output, 0, 64, recipe_row=recipe_row
            )
        return output.getvalue(), prepare_vposp.call_count

    def _render_write(self, recipe_row):
        flow_row = {
            "CP NO": "CP2",
            "type": "write",
            "item": "Trimdata_Rewrite",
            "Vcc": "VCC_TYP",
            "Hbin": 9,
        }

        def fake_col(sheet, column):
            if sheet == "VERSION":
                return {"page word": [1], "SWD PIN": [0]}[column]
            if sheet == "FLOW":
                return [flow_row[column]]
            if sheet == "ADDR_MAP":
                return []
            raise AssertionError(f"unexpected column access: {sheet}.{column}")

        output = io.StringIO()
        trim_plan = SimpleNamespace(bindings=(), for_cp=lambda _cp: ())
        with (
            patch.object(writers.G, "col", side_effect=fake_col),
            patch.object(writers.G, "FLOW", pd.DataFrame([flow_row])),
            patch.object(writers.G, "ADDR_MAP", pd.DataFrame()),
            patch.object(writers.G, "i", 0),
            patch.object(writers.G, "BASE_DIR", "base"),
            patch.object(writers.G, "OUT_DIR", "out"),
            patch.object(writers.G, "flow_row_flag", return_value=None),
            patch.object(writers.G, "compiled_adapter", SimpleNamespace(trim_data_plan=trim_plan)),
            patch.object(writers, "copy_file"),
            patch.object(writers, "set_all_final_vposp") as prepare_vposp,
        ):
            writers.trim_data_read_write(
                ["PROGRAM_CP2"], output, 0, 64, recipe_row=recipe_row
            )
        return output.getvalue(), prepare_vposp.call_count

    def test_explicit_pgmotp_does_not_implicitly_prepare_or_run_setvposp(self):
        recipe_row = SimpleNamespace(
            operations=(
                SimpleNamespace(name="COMMIT"),
                SimpleNamespace(name="PGMOTP"),
            )
        )

        generated, prepare_count = self._render_write(recipe_row)

        self.assertEqual(prepare_count, 0)
        self.assertNotIn("RUN_PATTERN(set_all_final_vposp:", generated)
        self.assertIn("////////////////////////complete", generated)

    def test_explicit_setvposp_prepares_but_pgmotp_does_not_run_it(self):
        recipe_row = SimpleNamespace(operations=(
            SimpleNamespace(name="COMMIT"),
            SimpleNamespace(name="SETVPOSP"),
            SimpleNamespace(name="PGMOTP"),
        ))

        generated, prepare_count = self._render_write(recipe_row)

        self.assertEqual(prepare_count, 1)
        self.assertNotIn("RUN_PATTERN(set_all_final_vposp:", generated)

    def test_blank_recipe_does_not_make_pgmotp_run_setvposp(self):
        generated, prepare_count = self._render_write(None)

        self.assertEqual(prepare_count, 0)
        self.assertNotIn("RUN_PATTERN(set_all_final_vposp:", generated)

    def test_memory_wakeup_without_explicit_setvposp_does_not_prepare_or_run_it(self):
        flow_row = {
            "CP NO": "CP1", "type": "wake", "item": "Memory_Wakeup",
            "Vcc": "VCC_TYP", "Hbin": 7,
        }

        def fake_col(sheet, column):
            if sheet == "VERSION":
                return {"page word": [1], "SWD PIN": [0]}[column]
            if sheet == "FLOW":
                return [flow_row[column]]
            if sheet == "ADDR_MAP":
                return []
            if sheet == "NM_PATTERN":
                return []
            raise AssertionError(f"unexpected column access: {sheet}.{column}")

        output = io.StringIO()
        trim_plan = SimpleNamespace(bindings=(), for_cp=lambda _cp: ())
        recipe_row = SimpleNamespace(operations=(
            SimpleNamespace(name="BUILDMAP"),
            SimpleNamespace(name="NMLOOP"),
        ))
        with (
            patch.object(writers.G, "col", side_effect=fake_col),
            patch.object(writers.G, "FLOW", pd.DataFrame([flow_row])),
            patch.object(writers.G, "ADDR_MAP", pd.DataFrame()),
            patch.object(writers.G, "i", 0),
            patch.object(writers.G, "BASE_DIR", "base"),
            patch.object(writers.G, "OUT_DIR", "out"),
            patch.object(writers.G, "flow_row_flag", return_value=None),
            patch.object(writers.G, "nm_patterns", return_value=[]),
            patch.object(writers.G, "compiled_adapter", SimpleNamespace(trim_data_plan=trim_plan)),
            patch.object(writers, "copy_file"),
            patch.object(writers, "set_all_final_vposp") as prepare_vposp,
        ):
            writers.trim_data_read_write(
                ["PROGRAM_CP1"], output, 0, 64, recipe_row=recipe_row
            )

        self.assertEqual(prepare_vposp.call_count, 0)
        self.assertNotIn("RUN_PATTERN(set_all_final_vposp:", output.getvalue())

    def test_explicit_commit_without_pgmotp_does_not_emit_physical_program_sequence(self):
        recipe_row = SimpleNamespace(
            operations=(SimpleNamespace(name="COMMIT"),)
        )

        generated, _prepare_count = self._render_write(recipe_row)

        self.assertNotIn("////////////////////////complete", generated)
        self.assertNotIn("RUN_PATTERN(set_all_final_vposp:", generated)

    def test_trimdata_read_setvposp_prepares_but_checkotp_does_not_run_it(self):
        recipe_row = SimpleNamespace(operations=tuple(
            SimpleNamespace(name=name) for name in (
                "READOTPMAP", "LOADMAP", "SETVPOSP", "CHECKOTP"
            )
        ))

        generated, prepare_count = self._render_read(recipe_row)

        self.assertEqual(prepare_count, 1)
        self.assertNotIn("RUN_PATTERN(set_all_final_vposp:", generated)

    def test_cp1_loadmap_pgmotp_programs_only_pages_with_cp1_trim_fields(self):
        flow_row = {
            "CP NO": "CP1", "type": "data", "item": "Trimdata_Write_Read",
            "Vcc": "VCC_TYP", "Hbin": 9,
        }
        pages = ("FT", "trim0", "trim1", "uid")
        addr_columns = {
            "Word No.": list(pages),
            "line": ["CP1"] * len(pages),
            "data type": ["lable"] * len(pages),
            "CP addr map": ["OTHER", "DAC_A[2:0]", "DAC_B[2:0]", "DAC_C[2:0]"],
        }

        def fake_col(sheet, column):
            if sheet == "VERSION":
                return {"page word": [1], "SWD PIN": [0]}[column]
            if sheet == "FLOW":
                return [flow_row[column]]
            if sheet == "ADDR_MAP":
                return addr_columns[column]
            raise AssertionError(f"unexpected column access: {sheet}.{column}")

        class Binding:
            dac_bits = 3

            def reference(self, _site):
                return "DAC_A_DAC_FINAL[T_SOCKET]"

            def matches_addr_map(self, token):
                return token.strip().startswith("DAC_")

        trim_plan = SimpleNamespace(bindings=(), for_cp=lambda _cp: (Binding(),))
        recipe_row = SimpleNamespace(operations=(
            SimpleNamespace(name="LOADMAP"), SimpleNamespace(name="PGMOTP"),
        ))
        output = io.StringIO()
        patterns = {
            page: {"erase": f"erase_{page}", "pgm": f"pgm_{page}", "read": f"read_{page}"}
            for page in pages
        }
        patterns["cp1_id"] = {
            # Real S100 EPR identity shares UID erase, while program/read are CP-specific.
            "erase": "erase_uid", "pgm": "pgm_cp1_id", "read": "read_cp1_id",
        }
        with (
            patch.object(writers.G, "col", side_effect=fake_col),
            patch.object(writers.G, "FLOW", pd.DataFrame([flow_row])),
            patch.object(writers.G, "ADDR_MAP", pd.DataFrame(addr_columns)),
            patch.object(writers.G, "i", 0),
            patch.object(writers.G, "BASE_DIR", "base"),
            patch.object(writers.G, "OUT_DIR", "out"),
            patch.object(writers.G, "flow_row_flag", return_value=None),
            patch.object(writers.G, "compiled_adapter", SimpleNamespace(trim_data_plan=trim_plan)),
            patch.object(writers, "epr_pattern_capture", side_effect=lambda _mode, page: patterns[page]),
            patch.object(writers, "copy_file"),
            patch.object(writers, "write_pat_mem"),
        ):
            writers.trim_data_read_write(
                ["PROGRAM_CP1"], output, 0, 64, recipe_row=recipe_row
            )

        generated = output.getvalue()
        self.assertNotIn("erase_FT", generated)
        for page in ("trim0", "trim1"):
            self.assertIn(f"erase_{page}", generated)
        self.assertEqual(generated.count("RUN_PATTERN(erase_uid:START"), 2)
        self.assertIn("Sys_DriverResult[T_SOCKET] > 0.5", generated)
        self.assertNotIn("RUN_PATTERN(pgm_uid:START", generated)
        self.assertNotIn("RUN_PATTERN(read_uid:START", generated)
        self.assertEqual(generated.count("RUN_PATTERN(pgm_cp1_id:START"), 1)
        self.assertEqual(generated.count("RUN_PATTERN(read_cp1_id:START"), 1)


if __name__ == "__main__":
    unittest.main()
