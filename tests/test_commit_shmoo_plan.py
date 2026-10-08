import unittest
from dataclasses import replace
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch
import pandas as pd

from flow_recipe import RecipeValueToken
from flow_recipe import compile_recipe_rows
from program_gen.core.addr_map import compile_addr_map_catalog
from program_gen.core.commit_shmoo import (
    CommitShmooPlanError,
    compile_commit_shmoo_plan,
    compile_commit_shmoo_plans,
)
from program_gen.core.persistence_recipe import (
    PersistenceFieldWrite,
    PersistenceOperation,
    PersistencePlan,
)
from program_gen.platforms.chroma.commit_shmoo_adapter import execute_commit_shmoo as execute_chroma_commit_shmoo
from program_gen.platforms.s100.commit_shmoo_adapter import execute_commit_shmoo as execute_s100_commit_shmoo
from program_gen.platforms.s100 import writers as s100_writers
from program_gen.platforms.chroma import writers as chroma_writers
from program_gen.core.shmoo import compile_shmoo_plans


class CommitShmooPlanTests(unittest.TestCase):
    def test_one_dimensional_step_range_expands_field_writes_pages_and_pgm(self):
        plan = compile_commit_shmoo_plan(
            _persistence_plan(),
            flow_type="shmoo",
            step_range="0-3",
        )

        self.assertEqual(plan.kind, "COMMIT_SHMOO")
        self.assertEqual(plan.steps, (0, 1, 2, 3))
        self.assertEqual(
            [point.affected_pages for point in plan.points],
            [("trim1", "uid")] * 4,
        )
        self.assertEqual(
            [(write.field, write.value) for write in plan.points[2].field_writes],
            [("FIELD_A", 2), ("FIELD_B", 2)],
        )
        self.assertEqual(
            [(action.action, action.pages)
             for action in plan.points[0].physical_actions],
            [("PGMOTP", ("trim1", "uid"))],
        )
        self.assertFalse(plan.uses_enter_judge_shmoo)

    def test_first_version_rejects_nonstep_multiline_and_enter_judge_contracts(self):
        invalid = (
            (_persistence_plan(value_kind="DECIMAL"), "shmoo", "0-3", "STEP"),
            (_persistence_plan(), "verify", "0-3", "type=shmoo"),
            (_persistence_plan(), "shmoo", "0-3,5-7", "one inclusive range"),
            (_persistence_plan(modules=("COMMIT", "JUDGE")), "shmoo", "0-3", "PGMOTP"),
        )
        for persistence, flow_type, step_range, message in invalid:
            with self.subTest(message=message):
                with self.assertRaisesRegex(CommitShmooPlanError, message):
                    compile_commit_shmoo_plan(
                        persistence, flow_type=flow_type, step_range=step_range
                    )

        with self.assertRaisesRegex(CommitShmooPlanError, "exceeds field width"):
            compile_commit_shmoo_plan(
                _persistence_plan(), flow_type="shmoo", step_range="0-8"
            )

    def test_collection_compiler_prioritizes_commit_shmoo_and_skips_enter_judge(self):
        flow = pd.DataFrame([
            {"CP NO": "CP2", "item": "Trimdata_Read", "type": "read",
             "step": "/", "sub": "/", "Recipe": "READOTPMAP-LOADMAP"},
            {"CP NO": "CP2", "item": "RegSweep", "type": "shmoo",
             "step": "3-1", "sub": "/",
             "Recipe": "COMMIT(FIELD_A=STEP)-PGMOTP"},
            {"CP NO": "CP2", "item": "MeasureSweep", "type": "shmoo",
             "step": "0", "sub": "/", "Recipe": ""},
        ])
        pattern = pd.DataFrame(columns=("item", "addr", "description", "pattern"))

        plans = compile_commit_shmoo_plans(
            flow,
            compile_recipe_rows(flow, pattern),
            _catalog(),
        )

        self.assertEqual(tuple(plans), (1,))
        self.assertEqual(plans[1].steps, (3, 2, 1))
        self.assertEqual(plans[1].flow_row_index, 1)
        self.assertEqual(plans[1].function_name, "RegSweep_Shmoo")

    def test_collection_compiler_ignores_ordinary_recipe_rows_but_keeps_page_producers(self):
        flow = pd.DataFrame([
            {"CP NO": "CP2", "item": "Trimdata_Read", "type": "read",
             "step": "/", "sub": "/", "Recipe": "READOTPMAP-LOADMAP"},
            {"CP NO": "CP2", "item": "Vref_Trim", "type": "trim",
             "step": "/", "sub": "/", "Recipe": "ENTER-TRIM-DAC_ADJ(<1.16:+1)-JUDGE"},
            {"CP NO": "CP2", "item": "RegSweep", "type": "shmoo",
             "step": "0-1", "sub": "/",
             "Recipe": "COMMIT(FIELD_A=STEP)-PGMOTP"},
        ])
        pattern = pd.DataFrame([
            {"item": "Vref_Trim", "addr": "0", "description": "", "pattern": "trim mode"},
            {"item": None, "addr": "0", "description": "3,DAC[3:0]=0000*", "pattern": "trim dac"},
        ])

        plans = compile_commit_shmoo_plans(
            flow,
            compile_recipe_rows(flow, pattern),
            _catalog(),
        )

        self.assertEqual(tuple(plans), (2,))
        self.assertEqual(plans[2].steps, (0, 1))

    def test_measurement_compiler_skips_commit_shmoo_rows(self):
        flow = pd.DataFrame([
            {"CP NO": "CP2", "item": "RegSweep", "type": "shmoo",
             "step": "0-1", "sub": "/", "Recipe": "COMMIT(FIELD_A=STEP)-PGMOTP"},
        ])
        pattern = pd.DataFrame(columns=("item", "addr", "description", "pattern"))

        self.assertEqual(compile_shmoo_plans(flow, pattern), {})

    def test_collection_compiler_requires_same_cp_complete_page_producer(self):
        flow = pd.DataFrame([{
            "CP NO": "CP2", "item": "RegSweep", "type": "shmoo",
            "step": "0-1", "sub": "/",
            "Recipe": "COMMIT(FIELD_A=STEP)-PGMOTP",
        }])
        pattern = pd.DataFrame(columns=("item", "addr", "description", "pattern"))

        with self.assertRaisesRegex(CommitShmooPlanError, "complete Page Image"):
            compile_commit_shmoo_plans(
                flow,
                compile_recipe_rows(flow, pattern),
                _catalog(),
            )

    def test_platform_adapters_order_each_field_update_before_each_pgm_action(self):
        plan = compile_commit_shmoo_plan(
            _persistence_plan(), flow_type="shmoo", step_range="0-1"
        )
        for adapter, platform in (
            (execute_chroma_commit_shmoo, "CHROMA"),
            (execute_s100_commit_shmoo, "S100"),
        ):
            events = []
            adapter(
                plan,
                begin_step=lambda step: events.append(("BEGIN", step)),
                commit_field=lambda write: events.append(
                    ("COMMIT_FIELD", write.field, write.value)
                ),
                pgm_pages=lambda pages: events.append(("PGMOTP_PAGES", pages)),
                end_step=lambda step: events.append(("END", step)),
            )
            with self.subTest(platform=platform):
                self.assertEqual(events, [
                    ("BEGIN", 0),
                    ("COMMIT_FIELD", "FIELD_A", 0),
                    ("COMMIT_FIELD", "FIELD_B", 0),
                    ("PGMOTP_PAGES", ("trim1", "uid")),
                    ("END", 0),
                    ("BEGIN", 1),
                    ("COMMIT_FIELD", "FIELD_A", 1),
                    ("COMMIT_FIELD", "FIELD_B", 1),
                    ("PGMOTP_PAGES", ("trim1", "uid")),
                    ("END", 1),
                ])
                self.assertFalse(
                    any(event[0] in ("ENTER", "JUDGE") for event in events)
                )

    def test_s100_writer_updates_register_then_programs_each_point(self):
        plan = compile_commit_shmoo_plan(
            _persistence_plan(modules=("COMMIT", "PGMOTP")),
            flow_type="shmoo",
            step_range="0-1",
        )
        out = StringIO()
        fake_g = SimpleNamespace(
            i=0,
            BASE_DIR=r"D:\master",
            OUT_DIR=r"D:\out",
            col=lambda sheet, column: {
                ("VERSION", "SWD PIN"): ["PA0"],
                ("ADDR_MAP", "bit[15:0]"): ["REG_A[15:0]", "REG_B[15:0]"],
                ("ADDR_MAP", "bit[31:16]"): ["complement", "complement"],
                ("ADDR_MAP", "Word No."): ["trim1", "uid"],
            }[(sheet, column)],
        )

        with patch.object(s100_writers, "G", fake_g), patch.object(
            s100_writers, "copy_file"
        ), patch.object(
            s100_writers, "epr_pattern_capture",
            side_effect=lambda mode, page: {
                "erase": "erase_" + page,
                "pgm": "pgm_" + page,
                "read": "read_" + page,
            },
        ), patch.object(
            s100_writers, "write_pat_mem",
            side_effect=lambda f, *args, **kwargs: f.write("LOAD_REGISTER\n"),
        ):
            s100_writers.commit_shmoo_item_write(["L_X_CP2"], out, plan)

        text = out.getvalue()
        self.assertEqual(text.count("@@PLAN Commit_Shmoo"), 1)
        self.assertEqual(text.count("REG_REG_A[T_SOCKET]="), 2)
        self.assertEqual(text.count("RUN_PATTERN(erase_trim1:START"), 2)
        self.assertEqual(text.count("RUN_PATTERN(pgm_trim1:START"), 2)
        self.assertEqual(text.count("RUN_PATTERN(read_trim1:START"), 2)
        self.assertEqual(text.count("LOAD_REGISTER"), 4)
        self.assertNotIn("set_all_final_vposp", text)

    def test_chroma_writer_updates_register_then_programs_each_point(self):
        plan = compile_commit_shmoo_plan(
            _persistence_plan(modules=("COMMIT", "PGMOTP")),
            flow_type="shmoo",
            step_range="0-1",
        )
        plan = replace(plan, vcc="VCC_TYP")
        out = StringIO()
        fake_g = SimpleNamespace(
            i=0, BASE_DIR=r"D:\master", OUT_DIR=r"D:\out",
            col=lambda sheet, column: {
                ("VERSION", "SWD PIN"): ["PA0"],
                ("ADDR_MAP", "bit[15:0]"): ["REG_A[15:0]", "REG_B[15:0]"],
                ("ADDR_MAP", "bit[31:16]"): ["complement", "complement"],
                ("ADDR_MAP", "Word No."): ["trim1", "uid"],
            }[(sheet, column)],
        )
        with patch.object(chroma_writers, "G", fake_g), patch.object(
            chroma_writers, "copy_file"
        ), patch.object(
            chroma_writers, "epr_pattern_capture",
            side_effect=lambda mode, page: {
                "erase": "erase_" + page,
                "pgm": "pgm_" + page,
                "read": "read_" + page,
            },
        ), patch.object(
            chroma_writers, "write_pat_mem",
            side_effect=lambda f, *args, **kwargs: f.write("LOAD_REGISTER\n"),
        ):
            chroma_writers.commit_shmoo_item_write(["L_X_CP2"], out, plan)

        text = out.getvalue()
        self.assertEqual(text.count("Commit_Shmoo()"), 1)
        self.assertEqual(text.count("REG_REG_A[SOCKET]="), 2)
        self.assertEqual(text.count("JUDGE_PAT(erase_trim1"), 2)
        self.assertEqual(text.count("JUDGE_PAT(pgm_trim1"), 2)
        self.assertEqual(text.count("JUDGE_PAT(read_trim1"), 2)
        self.assertEqual(text.count("if fail erase uid page"), 2)
        self.assertEqual(text.count("JUDGE_PAT(erase_uid"), 4)
        # 每个 STEP 的临时 shift_site 声明必须有独立作用域；失败重擦会
        # POWER_OFF，因此恢复供电后下一 STEP 才能继续 PGMOTP。
        self.assertEqual(text.count("LUINT shift_site;"), 2)
        self.assertEqual(text.count("POWER_ON(VCC_TYP);"), 5)
        self.assertEqual(text.count("LOAD_REGISTER"), 4)
        self.assertNotIn("set_all_final_vposp", text)


def _persistence_plan(value_kind="STEP", modules=("COMMIT", "PGMOTP")):
    writes = (
        PersistenceFieldWrite(
            "FIELD_A", "trim1", "REG_A", 0, 3,
            RecipeValueToken(value_kind, "STEP" if value_kind == "STEP" else "1"),
        ),
        PersistenceFieldWrite(
            "FIELD_B", "uid", "REG_B", 4, 3,
            RecipeValueToken(value_kind, "STEP" if value_kind == "STEP" else "1"),
        ),
    )
    operations = []
    for module in modules:
        operations.append(PersistenceOperation(
            module=module,
            excel_row=2,
            requested_pages=("trim1", "uid"),
            effective_pages=("trim1", "uid"),
            field_writes=writes if module == "COMMIT" else (),
            commit_source="EXPLICIT" if module == "COMMIT" else None,
        ))
    return PersistencePlan("CP2", tuple(operations))


def _catalog():
    return compile_addr_map_catalog(pd.DataFrame([
        {
            "Word No.": "trim1", "line": "CP1,CP2",
            "bit[31:16]": "complement", "bit[15:0]": "REG_A[15:0]",
            "data type": "lable", "CP Data[31:0]": "32'hFFFF_0000",
            "CP addr map": "OTHER[12:3],FIELD_A[2:0]",
        },
    ]))


if __name__ == "__main__":
    unittest.main()
