import unittest
import io
from types import SimpleNamespace

from program_gen.platforms.chroma.writers import (
    _persistence_recipe_modules,
    _recipe_module_enabled,
    _trim_target_pages,
    _commit_value_expression,
    write_uid_failed_site_reerase,
    _write_explicit_commit,
)
from program_gen.core.trim_data import compile_trim_data_plan
from program_gen.core.addr_map import compile_addr_map_catalog
from program_gen import state as G
import pandas as pd
from program_gen.core.persistence_recipe import PersistenceOperation, PersistenceRowPlan
from flow_recipe import RecipeAssignment, RecipeValueToken


def _row(*names):
    return SimpleNamespace(
        operations=tuple(SimpleNamespace(name=name) for name in names)
    )


class ChromaPersistenceRecipeTests(unittest.TestCase):
    def _render_write(self, recipe_row):
        from unittest.mock import patch
        from program_gen.platforms.chroma import writers

        flow_row = {
            "CP NO": "CP2", "type": "write", "item": "Trimdata_Rewrite",
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
            patch.object(writers.G, "i", 0),
            patch.object(writers.G, "BASE_DIR", "base"),
            patch.object(writers.G, "OUT_DIR", "out"),
            patch.object(writers.G, "flow_row_flag", return_value=None),
            patch.object(writers.G, "compiled_adapter", SimpleNamespace(
                trim_data_plan=trim_plan,
                addr_map_catalog=SimpleNamespace(fields=()),
            )),
            patch.object(writers, "copy_file"),
            patch.object(writers, "set_all_final_vposp") as prepare_vposp,
        ):
            writers.trim_data_read_write(
                ["PROGRAM_CP2"], output, 0, 64, recipe_row=recipe_row
            )
        return output.getvalue(), prepare_vposp.call_count

    def test_pgmotp_does_not_run_setvposp(self):
        generated, prepare_count = self._render_write(
            _row("SETVPOSP", "PGMOTP")
        )

        self.assertEqual(prepare_count, 0)
        self.assertNotIn("JUDGE_PAT(set_all_final_vposp", generated)

    def test_id_and_uid_writers_require_matching_typed_roles(self):
        from io import StringIO
        from unittest.mock import patch
        from program_gen.platforms.chroma import writers
        from program_gen.core.uid_plan import IdItemPlan, IdTargetDefinition

        id_target = IdTargetDefinition("CP1_BakeID", "BAKEID")
        gate = IdItemPlan("Read_CP1_BakeID", id_target, "PRODUCE_GATE", "DEFER",
                          "CP1_BAKEID_NEEDS_WRITE")
        commit = IdItemPlan("Pgm_CP1_BakeID_Read", id_target, "COMMIT_CLOSURE",
                            "PGMOTP_RESULT")
        flow_rows = [
            {"CP NO": "CP2", "type": "id", "item": "Read_CP1_BakeID",
             "Vcc": "VCC_TYP", "Hbin": 9, "UID": "no"},
            {"CP NO": "CP2", "type": "uid", "item": "Pgm_CP1_BakeID",
             "Vcc": "VCC_TYP", "Hbin": 9, "UID": "no"},
        ]

        def fake_col(sheet, column):
            if sheet == "FLOW":
                return [row[column] for row in flow_rows]
            if sheet == "VERSION":
                return {"page word": [1], "SWD PIN": [0]}[column]
            if sheet == "ADDR_MAP":
                return []
            raise AssertionError((sheet, column))

        with (
            patch.object(writers.G, "col", side_effect=fake_col),
            patch.object(writers.G, "i", 0),
            patch.object(writers.G, "BASE_DIR", "base"),
            patch.object(writers.G, "OUT_DIR", "out"),
            patch.object(writers, "copy_file"),
            patch.object(writers, "epr_pattern_capture", return_value={"read": "check"}),
        ):
            writers.id_write(["PROGRAM_CP2"], StringIO(), 0, id_plan=gate)
            with self.assertRaisesRegex(ValueError, "PRODUCE_GATE"):
                writers.id_write(["PROGRAM_CP2"], StringIO(), 0, id_plan=commit)
            with self.assertRaisesRegex(ValueError, "COMMIT_CLOSURE"):
                writers.uid_write(["PROGRAM_CP2"], StringIO(), 1, 64,
                                  recipe_row=_row("COMMIT"), id_plan=gate)
    def test_uid_failed_site_reerase_is_reusable_by_cp1_and_shmoo_paths(self):
        from io import StringIO
        output = StringIO()

        write_uid_failed_site_reerase(
            output, {"erase": "fbist_page_erase_uid"}, vcc="VCC_TYP"
        )

        generated = output.getvalue()
        self.assertIn("PLAN_RESULT_MS[SOCKET]==FAIL", generated)
        self.assertIn("SOCKET_SET(B:shift_site", generated)
        self.assertIn("JUDGE_PAT(fbist_page_erase_uid", generated)
        self.assertNotIn("set_all_final_vposp", generated)

        resumed = StringIO()
        write_uid_failed_site_reerase(
            resumed, {"erase": "fbist_page_erase_uid"}, vcc="VCC_TYP",
            restore_power=True,
        )
        resumed_text = resumed.getvalue()
        self.assertRegex(resumed_text, r"\{\n\s*///////////if fail erase uid page")
        self.assertEqual(resumed_text.count("LUINT shift_site;"), 1)
        self.assertTrue(resumed_text.rstrip().endswith("POWER_ON(VCC_TYP);"))
    def test_readotpmap_uses_only_effective_pages_from_cp_plan(self):
        from io import StringIO
        from unittest.mock import patch
        from program_gen.platforms.chroma import writers

        flow_row = {"CP NO": "CP2", "type": "read", "item": "Trimdata_Read",
                    "Vcc": "VCC_TYP", "Hbin": 9}
        row_plan = PersistenceRowPlan(
            cp="CP2", excel_row=2,
            operations=(PersistenceOperation(
                "READOTPMAP", 2, ("trim0",), (),
            ),),
        )

        def fake_col(sheet, column):
            if sheet == "VERSION":
                return {"page word": [1], "SWD PIN": [0]}[column]
            if sheet == "FLOW":
                return [flow_row[column]]
            if sheet == "ADDR_MAP":
                return {"Word No.": ["trim0"], "line": ["CP1/2"],
                        "data type": ["lable"]}.get(column, [""])
            raise AssertionError((sheet, column))

        trim_plan = SimpleNamespace(bindings=(), for_cp=lambda _cp: ())
        output = StringIO()
        with (
            patch.object(writers.G, "col", side_effect=fake_col),
            patch.object(writers.G, "FLOW", pd.DataFrame([flow_row])),
            patch.object(writers.G, "ADDR_MAP", pd.DataFrame([{"data type": "lable"}])),
            patch.object(writers.G, "set_vposp_name", []),
            patch.object(writers.G, "i", 0),
            patch.object(writers.G, "flow_row_flag", return_value=None),
            patch.object(writers.G, "compiled_adapter", SimpleNamespace(trim_data_plan=trim_plan)),
            patch.object(writers, "reuse_dac_restore_items", return_value=[]),
            patch.object(writers, "epr_pattern_capture") as capture,
        ):
            writers.trim_data_read_write(
                ["PROGRAM_CP2"], output, 0, 64,
                recipe_row=_row("READOTPMAP"), persistence_row_plan=row_plan,
            )

        capture.assert_not_called()
    def test_missing_recipe_keeps_legacy_modules_enabled(self):
        modules = _persistence_recipe_modules(None)

        self.assertIsNone(modules)
        self.assertTrue(_recipe_module_enabled(modules, "SETVPOSP"))
        self.assertTrue(_recipe_module_enabled(modules, "PGMOTP"))

    def test_explicit_pgmotp_does_not_imply_setvposp(self):
        modules = _persistence_recipe_modules(_row("COMMIT", "PGMOTP"))

        self.assertFalse(_recipe_module_enabled(modules, "SETVPOSP"))
        self.assertTrue(_recipe_module_enabled(modules, "PGMOTP"))

    def test_explicit_read_modules_do_not_inherit_write_or_nm_actions(self):
        modules = _persistence_recipe_modules(
            _row("READOTPMAP", "LOADMAP", "SETVPOSP", "CHECKOTP")
        )

        self.assertTrue(_recipe_module_enabled(modules, "READOTPMAP"))
        self.assertTrue(_recipe_module_enabled(modules, "LOADMAP"))
        self.assertTrue(_recipe_module_enabled(modules, "SETVPOSP"))
        self.assertTrue(_recipe_module_enabled(modules, "CHECKOTP"))
        self.assertFalse(_recipe_module_enabled(modules, "COMMIT"))
        self.assertFalse(_recipe_module_enabled(modules, "PGMOTP"))
        self.assertFalse(_recipe_module_enabled(modules, "NMLOOP"))

    def test_explicit_memory_wakeup_keeps_declared_boundaries(self):
        modules = _persistence_recipe_modules(
            _row("BUILDMAP", "SETVPOSP", "NMLOOP")
        )

        self.assertEqual(modules, ("BUILDMAP", "SETVPOSP", "NMLOOP"))
        self.assertTrue(_recipe_module_enabled(modules, "BUILDMAP"))
        self.assertTrue(_recipe_module_enabled(modules, "SETVPOSP"))
        self.assertTrue(_recipe_module_enabled(modules, "NMLOOP"))
        self.assertFalse(_recipe_module_enabled(modules, "PGMOTP"))

    def test_builduid_is_recipe_driven_not_cp_name_driven(self):
        cp2_modules = _persistence_recipe_modules(
            _row("BUILDUID", "COMMIT", "PGMOTP")
        )
        cp3_modules = _persistence_recipe_modules(_row("COMMIT", "PGMOTP"))

        self.assertTrue(_recipe_module_enabled(cp2_modules, "BUILDUID"))
        self.assertFalse(_recipe_module_enabled(cp3_modules, "BUILDUID"))

    def test_fixed_commit_values_translate_without_rebuilding_a_page(self):
        self.assertEqual(
            _commit_value_expression(SimpleNamespace(kind="DECIMAL", token="3")),
            "3",
        )
        self.assertEqual(
            _commit_value_expression(SimpleNamespace(kind="HEX", token="0x65BA")),
            "0x65BA",
        )
        self.assertEqual(
            _commit_value_expression(SimpleNamespace(kind="VARIABLE", token="DAC_FINAL")),
            "DAC_FINAL",
        )

    def test_fixed_commit_emits_runtime_reg_rmw_and_refreshes_patterns(self):
        old_addr_map = G.ADDR_MAP
        try:
            G.ADDR_MAP = pd.DataFrame([{
                "Word No.": "trim1", "SM Address": "0x00", "line": "CP1",
                "data type": "lable", "bit[15:0]": "ANA_MUX_TRIM2[15:0]",
                "bit[31:16]": "反码",
                "CP addr map": "OTHER[13:4],DLPR1_VSEL_OP_VDDK[1:0],DLPR0_VSEL_OP_VDDK[1:0]",
                "CP Data[31:0]": "32'hFFFF_0000",
            }])
            recipe = _row("COMMIT", "PGMOTP")
            recipe.operations[0].assignments = (
                RecipeAssignment("DLPR0_VSEL_OP_VDDK", RecipeValueToken("DECIMAL", "1")),
            )
            stream = io.StringIO()

            import program_gen.platforms.chroma.writers as writers
            original_capture = writers.epr_pattern_capture
            original_write = writers.write_pat_mem
            writers.epr_pattern_capture = lambda _mode, _page: {
                "pgm": "fbist_page_prog_trim1", "read": "fbist_page_read_trim1",
                "erase": "fbist_page_ers_trim1",
            }
            writers.write_pat_mem = lambda *args, **kwargs: args[0].write("    //refresh program+read\n")
            try:
                touched = _write_explicit_commit(
                    stream, recipe, "CP1",
                    catalog=compile_addr_map_catalog(G.ADDR_MAP),
                )
            finally:
                writers.epr_pattern_capture = original_capture
                writers.write_pat_mem = original_write

            generated = stream.getvalue()
            self.assertIn("REG_ANA_MUX_TRIM2[SOCKET]=(REG_ANA_MUX_TRIM2[SOCKET]&0xFFFC)|((1)<<0)", generated)
            self.assertIn("//refresh program+read", generated)
            self.assertEqual(touched, (("trim1", "ANA_MUX_TRIM2"),))
        finally:
            G.ADDR_MAP = old_addr_map

    def test_cp1_pages_come_from_trim_field_locations_not_all_labels(self):
        old_addr_map = G.ADDR_MAP
        try:
            G.ADDR_MAP = pd.DataFrame([
                {"Word No.": "trim0", "SM Address": "0x00", "line": "CP1",
                 "data type": "lable", "bit[15:0]": "TRIM0[15:0]",
                 "bit[31:16]": "反码", "CP addr map": "Pump_Trim[2:0],13'h0",
                 "CP Data[31:0]": "32'hFFFF_0000"},
                {"Word No.": "factory", "SM Address": "0x04", "line": "CP1",
                 "data type": "lable", "bit[15:0]": "FACTORY[15:0]",
                 "bit[31:16]": "反码", "CP addr map": "16'h0",
                 "CP Data[31:0]": "32'hFFFF_0000"},
            ])
            flow = pd.DataFrame([
                {"CP NO": "CP1", "item": "Pump", "type": "trim",
                 "DAC bit": 3, "PUMP": "yes"},
            ])

            catalog = compile_addr_map_catalog(G.ADDR_MAP)
            self.assertEqual(_trim_target_pages(
                compile_trim_data_plan(flow), "CP1", catalog=catalog
            ),
                             ("trim0",))
        finally:
            G.ADDR_MAP = old_addr_map

    def test_cp1_trimdata_write_read_reerases_uid_on_failed_sites(self):
        from io import StringIO
        from unittest.mock import patch
        from program_gen.platforms.chroma import writers

        flow_row = {"CP NO": "CP1", "type": "data",
                    "item": "Trimdata_Write_Read", "Vcc": "VCC_TYP", "Hbin": 9}
        binding = SimpleNamespace(
            pump=False, dac_bits=3, addr_map_name="Pump_Trim",
            reference=lambda site: "PUMP_DAC_FINAL[" + site + "]",
            matches_addr_map=lambda token: "Pump_Trim" in str(token),
        )
        trim_plan = SimpleNamespace(bindings=(binding,), for_cp=lambda _cp: (binding,))
        addr_map = pd.DataFrame([{
            "Word No.": "uid", "SM Address": "0x00", "line": "CP1",
            "data type": "lable", "bit[15:0]": "UID_REG[15:0]",
            "bit[31:16]": "反码", "CP addr map": "Pump_Trim[2:0],13'h0",
            "CP Data[31:0]": "32'hFFFF_0000",
        }])

        def fake_col(sheet, column):
            if sheet == "VERSION":
                return {"page word": [1], "SWD PIN": [0]}[column]
            if sheet == "FLOW":
                return [flow_row[column]]
            if sheet == "ADDR_MAP":
                return list(addr_map[column])
            raise AssertionError((sheet, column))

        out = StringIO()
        result = {"erase": "erase_cp1_id", "pgm": "pgm_cp1_id", "read": "read_cp1_id"}
        with (
            patch.object(writers.G, "col", side_effect=fake_col),
            patch.object(writers.G, "FLOW", pd.DataFrame([flow_row])),
            patch.object(writers.G, "ADDR_MAP", addr_map),
            patch.object(writers.G, "i", 0),
            patch.object(writers.G, "BASE_DIR", "base"),
            patch.object(writers.G, "OUT_DIR", "out"),
            patch.object(writers.G, "flow_row_flag", return_value=None),
            patch.object(writers.G, "compiled_adapter", SimpleNamespace(
                trim_data_plan=trim_plan,
                addr_map_catalog=compile_addr_map_catalog(addr_map),
            )),
            patch.object(writers, "epr_pattern_capture", return_value=result),
            patch.object(writers, "write_pat_mem"),
            patch.object(writers, "copy_file"),
        ):
            writers.trim_data_read_write(
                ["PROGRAM_CP1"], out, 0, 64,
                recipe_row=_row("LOADMAP", "PGMOTP"),
            )

        generated = out.getvalue()
        self.assertIn("if fail erase uid page", generated)
        self.assertGreaterEqual(generated.count("JUDGE_PAT(erase_cp1_id"), 2)


if __name__ == "__main__":
    unittest.main()
