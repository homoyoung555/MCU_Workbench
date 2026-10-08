import unittest
from datetime import date
import pandas as pd
from unittest.mock import patch
from types import SimpleNamespace

from program_gen.platforms.chroma.startup import _build_uid_startup_plan as chroma_startup_plan
from program_gen.platforms.s100.startup import _build_uid_startup_plan as s100_startup_plan

from program_gen.core.uid_plan import (
    BuildUidSchema,
    BuildUidField,
    BuildUidInputs,
    IdPlanError,
    IdTargetDefinition,
    UidPlanCompiler,
    compile_bakeid_plan,
    compile_build_uid_startup_plan,
    compile_build_uid_startup_plan_from_flow,
    generate_build_uid_values,
    compile_id_item_plan,
    compile_id_plan_set,
)


class UidPlanTests(unittest.TestCase):
    def test_id_plan_set_compiles_real_flow_roles_and_bake_gate_pair(self):
        flow = pd.DataFrame([
            {"CP NO": "CP2", "item": "Read_CP1_BakeID", "type": "id"},
            {"CP NO": "CP2", "item": "Pgm_CP1_BakeID", "type": "uid"},
            {"CP NO": "CP2", "item": "Check_CP1ID", "type": "id"},
            {"CP NO": "CP2", "item": "Pgm_CP2ID_Read", "type": "uid"},
        ])

        plans = compile_id_plan_set(flow)

        self.assertEqual(plans.for_row(0).role, "PRODUCE_GATE")
        self.assertEqual(plans.for_row(1).role, "COMMIT_CLOSURE")
        self.assertEqual(plans.bake_gate_for_row(1).item, "Read_CP1_BakeID")
        self.assertEqual(plans.for_row(2).role, "HARD_CHECK")
        self.assertEqual(plans.for_row(3).target.kind, "ID")
    def test_standard_id_items_compile_to_distinct_failure_contracts(self):
        targets = (
            IdTargetDefinition("CP2ID", "ID"),
            IdTargetDefinition("CP1_BakeID", "BAKEID"),
        )

        hard_check = compile_id_item_plan("Check_CP2ID", targets)
        gate_read = compile_id_item_plan("Read_CP1_BakeID", targets)
        commit = compile_id_item_plan("Pgm_CP2ID_Read", targets)

        self.assertEqual((hard_check.role, hard_check.failure_policy),
                         ("HARD_CHECK", "FLOW_BIN"))
        self.assertEqual((gate_read.role, gate_read.failure_policy),
                         ("PRODUCE_GATE", "DEFER"))
        self.assertEqual(gate_read.gate_symbol, "CP1_BAKEID_NEEDS_WRITE")
        self.assertEqual(commit.role, "COMMIT_CLOSURE")

        for item in ("Check", "Read_CP9ID", "Pgm_CP2ID", "Maybe_CP2ID"):
            with self.subTest(item=item):
                with self.assertRaises(IdPlanError):
                    compile_id_item_plan(item, targets)

    def test_builduid_enables_its_complete_dependency_closure_only_when_requested(self):
        schema = BuildUidSchema(
            startup_cache_inputs=("LOT_ID", "WAFER_ID", "WAFER_SLOT", "X", "Y"),
            global_symbols=("lot_id", "wafer_id", "wafer_slot", "die_x", "die_y"),
            fields=("LOT_FIELD", "WAFER_FIELD", "XY_FIELD", "DATE_FIELD", "CRC_FIELD"),
            crc_field="CRC_FIELD",
            crc_input_fields=("LOT_FIELD", "WAFER_FIELD", "XY_FIELD", "DATE_FIELD"),
        )
        compiler = UidPlanCompiler(schema)

        self.assertIsNone(compiler.plan_for_cp("CP1", recipe_modules=("COMMIT",)))

        cp2 = compiler.plan_for_cp("CP2", recipe_modules=("BUILDUID", "COMMIT"))
        cp3 = compiler.plan_for_cp("CP3", recipe_modules=("BUILDUID", "COMMIT"))

        self.assertEqual(cp2.cp, "CP2")
        self.assertEqual(cp3.cp, "CP3")
        self.assertEqual(cp2.fields, schema.fields)
        self.assertEqual(cp3.fields, schema.fields)
        self.assertTrue(cp2.full_replace)
        self.assertEqual(cp2.startup_cache_inputs, schema.startup_cache_inputs)
        self.assertEqual(cp2.global_symbols, schema.global_symbols)
        self.assertEqual(cp2.crc.field, "CRC_FIELD")
        self.assertNotIn("CP3", cp2.activation_condition)

        with self.assertRaisesRegex(IdPlanError, "BUILDUID.*once"):
            compiler.plan_for_cp("CP4", recipe_modules=("BUILDUID", "BUILDUID"))

    def test_bakeid_precheck_is_all_site_but_final_commit_and_program_are_gated(self):
        targets = (IdTargetDefinition("CP1_BakeID", "BAKEID"),)
        read_plan = compile_id_item_plan("Read_CP1_BakeID", targets)

        plan = compile_bakeid_plan(
            item="Pgm_CP1_BakeID_Read",
            target_definitions=targets,
            gate_producer=read_plan,
        )

        self.assertEqual(plan.gate_symbol, "CP1_BAKEID_NEEDS_WRITE")
        self.assertEqual(
            [(operation.action, operation.site_scope) for operation in plan.operations],
            [
                ("READOTPMAP_UID", "ALL_ACTIVE_SITES"),
                ("LOADMAP_UID", "ALL_ACTIVE_SITES"),
                ("CHECKOTP_UID", "ALL_ACTIVE_SITES"),
                ("COMMIT_BAKEID", "GATED_SITES"),
                ("PGMOTP_UID", "GATED_SITES"),
            ],
        )

        wrong_gate = compile_id_item_plan(
            "Read_CP2_BakeID", (IdTargetDefinition("CP2_BakeID", "BAKEID"),)
        )
        with self.assertRaisesRegex(IdPlanError, "gate.*target"):
            compile_bakeid_plan(
                item="Pgm_CP1_BakeID_Read",
                target_definitions=targets,
                gate_producer=wrong_gate,
            )

    def test_builduid_generates_a_complete_deterministic_field_map_and_crc(self):
        fields = tuple(
            [BuildUidField(f"LOT_{index}", "LOT_BYTE", index=index)
             for index in range(7)]
            + [
                BuildUidField("WAFER_0", "WAFER_BYTE", index=0),
                BuildUidField("SLOT", "WAFER_SLOT"),
                BuildUidField("XY_HIGH", "XY_HIGH"),
                BuildUidField("X_LOW", "X_LOW"),
                BuildUidField("Y_LOW", "Y_LOW"),
                BuildUidField("DATE_YM", "DATE_YM"),
                BuildUidField("FAB", "FAB_ID"),
                BuildUidField("PROJECT", "PROJECT_WORD", width=16),
                BuildUidField("PROGRAM", "PROGRAM_VERSION"),
                BuildUidField("CRC", "CRC8"),
            ]
        )
        crc_inputs = tuple(
            [f"LOT_{index}" for index in range(7)]
            + ["SLOT", "XY_HIGH", "X_LOW", "Y_LOW", "DATE_YM", "FAB", "PROGRAM"]
        )
        schema = BuildUidSchema(
            startup_cache_inputs=("LOT_ID", "WAFER_ID", "WAFER_SLOT", "X", "Y"),
            global_symbols=("lot_id", "wafer_id", "wafer_slot", "die_x", "die_y"),
            fields=tuple(field.field for field in fields),
            crc_field="CRC",
            crc_input_fields=crc_inputs,
            field_bindings=fields,
        )
        inputs = BuildUidInputs(
            lot_id="ABC1234",
            wafer_id="W01",
            wafer_slot=7,
            x=0x123,
            y=-0x234,
            build_date=date(2026, 8, 14),
            fab_id=3,
            project_id=0x25,
            project_version=0x09,
            program_version=4,
        )

        first = generate_build_uid_values(inputs, schema)
        second = generate_build_uid_values(inputs, schema)

        self.assertEqual(first, second)
        self.assertEqual(tuple(first), schema.fields)
        self.assertEqual(first["LOT_0"], ord("A"))
        self.assertEqual(first["WAFER_0"], ord("W"))
        self.assertEqual(first["XY_HIGH"], 0x21)
        self.assertEqual((first["X_LOW"], first["Y_LOW"]), (0x23, 0xCC))
        self.assertEqual(first["DATE_YM"], 0x68)
        self.assertEqual(first["PROJECT"], 0x2509)
        self.assertEqual(first["CRC"], 0xA3)

    def test_builduid_rejects_invalid_cached_inputs_and_exposes_startup_dependencies(self):
        schema = BuildUidSchema(
            startup_cache_inputs=("LOT_ID", "WAFER_ID", "WAFER_SLOT", "X", "Y"),
            global_symbols=("lot_id", "wafer_id", "wafer_slot", "die_x", "die_y"),
            fields=("LOT", "CRC"),
            crc_field="CRC",
            crc_input_fields=("LOT",),
            field_bindings=(
                BuildUidField("LOT", "LOT_BYTE", index=0),
                BuildUidField("CRC", "CRC8"),
            ),
        )
        invalid = BuildUidInputs(
            lot_id="A", wafer_id="W", wafer_slot=0, x=0, y=0,
            build_date=date(2026, 8, 14), fab_id=1, project_id=1,
            project_version=1, program_version=1,
        )

        with self.assertRaisesRegex(IdPlanError, "wafer_slot"):
            generate_build_uid_values(invalid, schema)

        disabled = compile_build_uid_startup_plan(
            schema, recipe_modules=("COMMIT",)
        )
        enabled = compile_build_uid_startup_plan(
            schema, recipe_modules=("BUILDUID", "COMMIT")
        )

        self.assertIsNone(disabled)
        self.assertEqual(enabled.cache_inputs, schema.startup_cache_inputs)
        self.assertEqual(enabled.global_symbols, schema.global_symbols)
        self.assertEqual(enabled.validation_phase, "STARTUP_FAIL_FAST")
        self.assertTrue(enabled.read_once)

    def test_startup_dependency_activation_follows_each_cp_recipe_not_cp_number(self):
        flow = pd.DataFrame(
            [
                {"CP NO": "CP2", "Recipe": "BUILDUID-COMMIT-PGMOTP(UID)"},
                {"CP NO": "CP3", "Recipe": "COMMIT-PGMOTP(UID)"},
                {"CP NO": "CP4", "Recipe": "BUILDUID-COMMIT-PGMOTP(UID)"},
            ]
        )

        cp2 = compile_build_uid_startup_plan_from_flow(flow, "CP2")
        cp3 = compile_build_uid_startup_plan_from_flow(flow, "CP3")
        cp4 = compile_build_uid_startup_plan_from_flow(flow, "CP4")

        self.assertIsNotNone(cp2)
        self.assertIsNone(cp3)
        self.assertIsNotNone(cp4)
        self.assertEqual(cp2, cp4)

        plans = {"CP2": cp2, "CP3": cp3, "CP4": cp4}
        product = SimpleNamespace(for_cp=lambda cp: SimpleNamespace(
            build_uid_rows={} if plans[cp] is None else {0: plans[cp]}
        ))
        with patch("program_gen.state.product_compilation", product):
            self.assertIsNotNone(chroma_startup_plan("CP2"))
            self.assertIsNone(chroma_startup_plan("CP3"))
            self.assertIsNotNone(s100_startup_plan("CP4"))

    def test_startup_dependency_ignores_unmigrated_blank_recipes(self):
        flow = pd.DataFrame([
            {"CP NO": "CP2", "Recipe": None},
            {"CP NO": "CP2", "Recipe": float("nan")},
            {"CP NO": "CP2", "Recipe": "BUILDUID-COMMIT-PGMOTP(UID)"},
        ])

        self.assertIsNotNone(compile_build_uid_startup_plan_from_flow(flow, "CP2"))


if __name__ == "__main__":
    unittest.main()
