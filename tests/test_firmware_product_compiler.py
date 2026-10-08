from dataclasses import replace
import unittest

from program_gen.compiler import ProductCompiler
from program_gen.core.firmware_force import (
    ClockForceAction,
    ClockStopAction,
    SupplyForceAction,
)
from program_gen.core.firmware_judge import (
    DigitalCompareJudgePlan,
    ScalarMeasurementJudgePlan,
)
from program_gen.core.firmware_test import _clock_cleanup_for, _execution_steps_for
from program_gen.core.run_sequence import ForceStopAction, LevelSequenceAction, WaitAction
from program_gen.flow_kinds import compile_flow_operations
from program_gen.workbook import TableModel, WorkbookReader
from tests.workspace_paths import FORMAL_MASTER


class FirmwareProductCompilerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)

    def test_same_item_compiles_ordered_download_and_keil_phases(self):
        compilation = ProductCompiler().compile(
            _with_migrated_firmware_recipes(self.workbook)
        ).require_success()

        plan = next(
            plan
            for plan in compilation.plan.catalogs.firmware_test_plans.values()
            if plan.cp == "CP1" and plan.item == "SRAM_CKB_Test"
        )
        self.assertEqual(plan.typed_kind, "FIRMWARE_FUNCTION_TEST")
        self.assertEqual(plan.row_indices, (78, 79))
        self.assertEqual(plan.excel_rows, (80, 81))
        self.assertEqual(
            tuple(type(phase).__name__ for phase in plan.phases),
            ("DownloadPhase", "KeilPhase"),
        )
        self.assertEqual(
            tuple(phase.effective_recipe for phase in plan.phases),
            (("DOWNLOAD_CODE",), ("RUN_SEQUENCE", "JUDGE")),
        )
        self.assertEqual(tuple(phase.row for phase in plan.phases), (78, 79))
        self.assertEqual(plan.phases[0].pattern.name, "SRAM_V02_06_CKB")
        self.assertEqual(
            tuple(phase.power_profile for phase in plan.phases),
            ("VCC_MAX", "VCC_MAX"),
        )
        self.assertEqual(
            plan.phases[1].actions,
            (
                LevelSequenceAction("PA13", "HL", 5_000_000, True),
                WaitAction(500),
                LevelSequenceAction("PA13", "HL", 5_000_000, True),
                WaitAction(100),
            ),
        )
        self.assertIsInstance(plan.phases[1].judge, DigitalCompareJudgePlan)
        self.assertEqual(
            tuple(phase.sub for phase in plan.phases),
            ("down load code", "SRAM_CKB"),
        )
        self.assertEqual(
            tuple(phase.provenance.coordinate for phase in plan.phases),
            ("A80", "A81"),
        )
        definition = next(
            definition
            for definition in compilation.for_cp("CP1").definitions
            if definition.item == "SRAM_CKB_Test"
        )
        self.assertEqual(definition.typed_kind, "FIRMWARE_FUNCTION_TEST")
        self.assertEqual(
            definition.effective_recipe,
            ("DOWNLOAD_CODE", "RUN_SEQUENCE", "JUDGE"),
        )

        power = next(
            plan
            for plan in compilation.plan.catalogs.firmware_test_plans.values()
            if plan.cp == "CP3" and plan.item == "Power_Test"
        )
        self.assertEqual(power.typed_kind, "FIRMWARE_RUN_TEST")
        self.assertEqual(tuple(phase.row for phase in power.phases), (189, 190, 191))
        self.assertEqual(
            tuple(phase.sub for phase in power.phases),
            ("stop0", "stop1", "standby"),
        )
        self.assertEqual(
            tuple(phase.effective_recipe for phase in power.phases),
            (("RUN_SEQUENCE", "JUDGE"),) * 3,
        )
        self.assertTrue(all(
            any(isinstance(action, SupplyForceAction) for action in phase.actions)
            and isinstance(phase.judge, ScalarMeasurementJudgePlan)
            for phase in power.phases
        ))
        self.assertEqual(
            tuple(type(step).__name__ for step in power.execution_steps),
            (
                "KeilPhase",
                "DutResetAction",
                "KeilPhase",
                "DutResetAction",
                "KeilPhase",
            ),
        )
        resets = tuple(
            step
            for step in power.execution_steps
            if type(step).__name__ == "DutResetAction"
        )
        self.assertEqual(
            tuple(
                (reset.low_duration_ms, reset.high_duration_ms, reset.final_state)
                for reset in resets
            ),
            ((5, 5, "RELEASED_HIGH"), (5, 5, "RELEASED_HIGH")),
        )
        self.assertEqual(
            tuple(type(step).__name__ for step in plan.execution_steps),
            ("DownloadPhase", "KeilPhase"),
        )
        download = next(
            plan
            for plan in compilation.plan.catalogs.firmware_test_plans.values()
            if plan.cp == "CP3" and plan.item == "Download_Code"
        )
        self.assertEqual(download.typed_kind, "CODE_DOWNLOAD")
        rcc = next(
            plan
            for plan in compilation.plan.catalogs.firmware_test_plans.values()
            if plan.cp == "CP3" and plan.item == "RCC_Test"
        )
        self.assertTrue(any(
            isinstance(action, ClockForceAction)
            for action in rcc.phases[0].actions
        ))
        self.assertIsInstance(rcc.phases[0].judge, DigitalCompareJudgePlan)
        self.assertEqual(len(rcc.phases[0].cleanup_actions), 1)
        self.assertIsInstance(rcc.phases[0].cleanup_actions[0], ClockStopAction)
        clock = next(
            action for action in rcc.phases[0].actions
            if isinstance(action, ClockForceAction)
        )
        self.assertEqual(_clock_cleanup_for((clock, ForceStopAction())), ())
        self.assertNotIn(
            "Pvd_Test",
            {
                plan.item
                for plan in compilation.plan.catalogs.firmware_test_plans.values()
            },
        )
        pvd_definition = next(
            definition
            for definition in compilation.for_cp("CP3").definitions
            if definition.item == "Pvd_Test"
        )
        self.assertEqual(pvd_definition.typed_kind, "PVD_TEST")

    def test_firmware_run_test_does_not_reset_between_equal_subs(self):
        compilation = ProductCompiler().compile(
            _with_migrated_firmware_recipes(self.workbook)
        ).require_success()
        power = next(
            plan
            for plan in compilation.plan.catalogs.firmware_test_plans.values()
            if plan.cp == "CP3" and plan.item == "Power_Test"
        )
        equal_sub_phases = tuple(
            replace(phase, sub="same-sub") for phase in power.phases
        )

        self.assertEqual(
            tuple(
                type(step).__name__
                for step in _execution_steps_for(
                    power.typed_kind, equal_sub_phases
                )
            ),
            ("KeilPhase", "KeilPhase", "KeilPhase"),
        )

    def test_hex_recipe_is_rejected_because_download_code_is_intrinsic(self):
        workbook = _with_migrated_firmware_recipes(self.workbook)
        flow = workbook.dataframe("FLOW")
        flow.loc[78, "Recipe"] = "DOWNLOAD_CODE"

        compilation = ProductCompiler().compile(_with_flow(workbook, flow))

        self.assertFalse(compilation.is_valid)
        diagnostic = compilation.diagnostics.errors[0]
        self.assertEqual(diagnostic.code, "FW.RECIPE.HEX_INTRINSIC_ONLY")
        self.assertIn("FLOW row 80", diagnostic.message)
        self.assertIn("DOWNLOAD_CODE", diagnostic.message)

    def test_keil_recipe_must_be_explicit(self):
        workbook = _with_migrated_firmware_recipes(self.workbook)
        flow = workbook.dataframe("FLOW")
        flow.loc[79, "Recipe"] = ""

        compilation = ProductCompiler().compile(_with_flow(workbook, flow))

        self.assertFalse(compilation.is_valid)
        diagnostic = compilation.diagnostics.errors[0]
        self.assertEqual(diagnostic.code, "FW.RECIPE.KEIL_REQUIRED")
        self.assertIn("FLOW row 81", diagnostic.message)
        self.assertIn("mode=keil", diagnostic.message)

    def test_native_keil_terminal_token_is_rejected(self):
        workbook = _with_migrated_firmware_recipes(self.workbook)
        flow = workbook.dataframe("FLOW")
        flow.loc[79, "step"] = str(flow.loc[79, "step"]) + "-T"

        compilation = ProductCompiler().compile(_with_flow(workbook, flow))

        self.assertFalse(compilation.is_valid)
        self.assertEqual(
            compilation.diagnostics.errors[0].code,
            "RUN_SEQUENCE.TERMINAL_TOKEN_FORBIDDEN",
        )

    def test_same_firmware_item_cannot_reappear_after_another_item(self):
        workbook = _with_migrated_firmware_recipes(self.workbook)
        flow = workbook.dataframe("FLOW")
        flow.loc[79, "item"] = "Between_Firmware_Item"
        flow.loc[80, "item"] = flow.loc[78, "item"]

        compilation = ProductCompiler().compile(_with_flow(workbook, flow))

        self.assertFalse(compilation.is_valid)
        diagnostic = compilation.diagnostics.errors[0]
        self.assertEqual(diagnostic.code, "FW.GROUP.NONCONTIGUOUS")
        self.assertIn("FLOW row 82", diagnostic.message)

    def test_firmware_phases_must_share_one_bin_binding(self):
        workbook = _with_migrated_firmware_recipes(self.workbook)
        flow = workbook.dataframe("FLOW")
        flow.loc[190, "Hbin"] = 99

        compilation = ProductCompiler().compile(_with_flow(workbook, flow))

        self.assertFalse(compilation.is_valid)
        self.assertEqual(
            compilation.diagnostics.errors[0].code,
            "FW.GROUP.BIN_CONFLICT",
        )

    def test_firmware_run_phases_must_share_one_power_profile(self):
        workbook = _with_migrated_firmware_recipes(self.workbook)
        flow = workbook.dataframe("FLOW")
        flow.loc[190, "Vcc"] = "VCC_TYP"

        compilation = ProductCompiler().compile(_with_flow(workbook, flow))

        self.assertFalse(compilation.is_valid)
        self.assertEqual(
            compilation.diagnostics.errors[0].code,
            "FW.GROUP.POWER_CONFLICT",
        )


def _with_migrated_firmware_recipes(workbook):
    flow = workbook.dataframe("FLOW")
    operations = compile_flow_operations(workbook)
    hex_rows = [operation.row for operation in operations
                if operation.typed_kind == "VERIFY_HEX"]
    keil_rows = [operation.row for operation in operations
                 if operation.typed_kind == "VERIFY_KEIL"]
    flow.loc[hex_rows, "Recipe"] = ""
    flow.loc[keil_rows, "Recipe"] = "RUN_SEQUENCE-JUDGE"
    return _with_flow(workbook, flow)


def _with_flow(workbook, flow):
    return replace(
        workbook,
        tables=tuple(
            TableModel.from_dataframe("FLOW", flow)
            if table.title == "FLOW"
            else table
            for table in workbook.tables
        ),
    )


if __name__ == "__main__":
    unittest.main()
