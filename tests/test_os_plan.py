from tests.workspace_paths import FORMAL_MASTER as EXTERNAL_FORMAL_MASTER
"""Public-contract tests for platform-neutral typed OS plans."""

from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import unittest

from program_gen.core.os_plan import (
    DEFAULT_OS_RECIPE,
    OsPlanError,
    OsPlatformProfile,
    OsSafetyAction,
    compile_os_plan,
)
from program_gen.flow_kinds import compile_flow_operations
from program_gen.workbook import WorkbookReader


MASTER_WORKBOOK = EXTERNAL_FORMAL_MASTER


class OsPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        workbook = WorkbookReader().read(MASTER_WORKBOOK)
        cls.os_operations = tuple(
            operation
            for operation in compile_flow_operations(workbook)
            if operation.typed_kind == "OS"
        )

    def test_formal_master_has_one_os_operation_for_each_cp(self) -> None:
        self.assertEqual(
            tuple((operation.row, operation.cp, operation.item) for operation in self.os_operations),
            ((0, "CP1", "os_test"), (95, "CP2", "os_test"), (167, "CP3", "os_test")),
        )

    def test_chroma_plan_keeps_formal_flow_identity_and_safe_actions(self) -> None:
        operation = self.os_operations[0]

        plan = compile_os_plan(operation, "chroma")

        self.assertEqual(plan.cp, operation.cp)
        self.assertEqual(plan.item, operation.item)
        self.assertEqual(plan.provenance, operation.provenance)
        self.assertEqual(plan.platform_profile, OsPlatformProfile.CHROMA)
        self.assertEqual(plan.effective_recipe, DEFAULT_OS_RECIPE)
        self.assertIsNone(plan.relay)
        self.assertEqual(
            plan.safety_actions,
            (
                OsSafetyAction.ORDINARY_IO,
                OsSafetyAction.TP,
                OsSafetyAction.POWER_RAIL,
            ),
        )
        with self.assertRaises(FrozenInstanceError):
            plan.effective_recipe = "MUTATED"

    def test_s100_profile_excludes_power_rail_without_changing_flow_identity(self) -> None:
        operation = self.os_operations[-1]

        plan = compile_os_plan(operation, OsPlatformProfile.S100)

        self.assertEqual(plan.cp, operation.cp)
        self.assertEqual(plan.item, operation.item)
        self.assertEqual(plan.provenance, operation.provenance)
        self.assertEqual(plan.platform_profile, OsPlatformProfile.S100)
        self.assertEqual(plan.effective_recipe, "OS_TEST")
        self.assertEqual(
            plan.safety_actions,
            (OsSafetyAction.ORDINARY_IO, OsSafetyAction.TP),
        )
        self.assertNotIn(OsSafetyAction.POWER_RAIL, plan.safety_actions)

    def test_os_plan_rejects_unknown_platform_and_noncompliant_mode_stably(self) -> None:
        operation = self.os_operations[0]

        with self.assertRaisesRegex(OsPlanError, "OS.PLATFORM.UNKNOWN"):
            compile_os_plan(operation, "unknown-platform")
        with self.assertRaisesRegex(OsPlanError, "OS.MODE.INVALID"):
            compile_os_plan(replace(operation, mode="keil"), "chroma")

    def test_os_plan_rejects_a_non_os_typed_operation_stably(self) -> None:
        operation = self.os_operations[0]

        with self.assertRaisesRegex(OsPlanError, "OS.TYPE.INVALID"):
            compile_os_plan(replace(operation, typed_kind="MAIN"), "chroma")

    def test_os_plan_consumes_a_named_flow_relay(self) -> None:
        operation = replace(self.os_operations[0], relay="UR_OS")

        plan = compile_os_plan(operation, "chroma")

        self.assertEqual(plan.relay, "UR_OS")
