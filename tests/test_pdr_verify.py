from __future__ import annotations

from tests.workspace_paths import FORMAL_MASTER as EXTERNAL_FORMAL_MASTER

from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import unittest

from pandas.testing import assert_frame_equal

from program_gen.compiler import ProductCompiler
from program_gen.core.input_normalization import normalize_flow_table, token_key
from program_gen.core.pdr_verify import (
    PdrExpectedStatus,
    PdrMismatchRule,
    PdrPatternResource,
    PdrVerifyPlatform,
    PdrVerifyPlanError,
    PdrVoltageApplication,
    compile_pdr_verify_plan,
)
from program_gen.workbook import WorkbookReader


FORMAL_MASTER = (
    EXTERNAL_FORMAL_MASTER
)


class PdrVerifyPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        workbook = WorkbookReader().read(FORMAL_MASTER)
        compilation = ProductCompiler().compile(workbook).require_success()
        cls.flow = normalize_flow_table(workbook.dataframe("FLOW"))
        cls.operations = tuple(
            operation
            for operation in compilation.plan.catalogs.flow_operations
            if token_key(operation.item) == "pdr_verify"
        )

    def test_chroma_plan_freezes_formal_identity_judgment_and_resources(self):
        operation = self.operations[0]

        plan = compile_pdr_verify_plan(self.flow, operation, "chroma")

        self.assertEqual(plan.row, 41)
        self.assertEqual(plan.excel_row, 43)
        self.assertEqual(plan.cp, "CP1")
        self.assertEqual(plan.item, "Pdr_Verify")
        self.assertEqual(plan.provenance, operation.provenance)
        self.assertEqual(plan.typed_kind, "PDR_VERIFY")
        self.assertEqual(plan.initial_power_profile, "VCC_TYP")
        self.assertEqual(plan.relay, "/")
        self.assertIsNone(plan.scalar_limits)
        self.assertIsNone(plan.pe_action)
        self.assertEqual(plan.platform, PdrVerifyPlatform.CHROMA)
        self.assertEqual(
            plan.voltage_application,
            PdrVoltageApplication.CHROMA_REGISTERED_LEVEL_AND_MLDPS,
        )
        self.assertEqual(
            plan.pattern_resources,
            (
                PdrPatternResource(
                    "ENTER_FBIST",
                    "enter_fbist_mode",
                    "pattern:enter_fbist_mode",
                ),
                PdrPatternResource(
                    "ENTER_PDR_VERIFY",
                    "enter_pdr_verify",
                    "pattern:enter_pdr_verify",
                ),
                PdrPatternResource(
                    "STATUS_READ",
                    "read_status_mode",
                    "pattern:read_status_mode",
                ),
                PdrPatternResource(
                    "EXIT_FBIST",
                    "exit_fbist_mode",
                    "pattern:exit_fbist_mode",
                ),
            ),
        )
        self.assertEqual(
            tuple(
                (
                    check.voltage_role,
                    check.expected_status,
                    check.mismatch_rule,
                    check.settle_ms,
                    check.status_pattern_identity,
                    check.driver_result_threshold,
                    check.voltage_profile_identity,
                    check.level_profile_identity,
                    check.io_pin_group_identity,
                )
                for check in plan.status_checks
            ),
            (
                (
                    "PDR_MAX",
                    PdrExpectedStatus.NORMAL,
                    PdrMismatchRule.TESTER_FAIL,
                    10.0,
                    "pattern:read_status_mode",
                    None,
                    "voltage_profile:VCC_PDR_MAX",
                    "level_profile:PDR_MAX_LVL",
                    None,
                ),
                (
                    "PDR_MIN",
                    PdrExpectedStatus.RESET,
                    PdrMismatchRule.TESTER_PASS,
                    10.0,
                    "pattern:read_status_mode",
                    None,
                    "voltage_profile:VCC_PDR_MIN",
                    "level_profile:PDR_MIN_LVL",
                    None,
                ),
            ),
        )
        self.assertEqual(plan.power_limits.voltage_range_v, 6.0)
        self.assertEqual(plan.power_limits.current_range_ma, 500.0)
        self.assertEqual(plan.power_limits.current_limit_ma, 200.0)
        self.assertEqual(plan.power_limits.force_wait_ms, 2.0)
        self.assertEqual(plan.power_limits.level_settle_ms, 3.0)

    def test_s100_profile_preserves_legacy_min_timing_and_no_exit_pattern(self):
        plan = compile_pdr_verify_plan(self.flow, self.operations[0], "s100")

        self.assertEqual(plan.platform, PdrVerifyPlatform.S100)
        self.assertEqual(
            plan.voltage_application,
            PdrVoltageApplication.S100_ALL_RAILS_AND_IO_THRESHOLDS,
        )
        self.assertEqual(
            tuple(resource.name for resource in plan.pattern_resources),
            ("enter_fbist_mode", "enter_pdr_verify", "read_status_mode"),
        )
        self.assertEqual(
            tuple(
                (
                    check.voltage_role,
                    check.expected_status,
                    check.mismatch_rule,
                    check.settle_ms,
                    check.driver_result_threshold,
                    check.voltage_profile_identity,
                    check.level_profile_identity,
                    check.io_pin_group_identity,
                )
                for check in plan.status_checks
            ),
            (
                (
                    "PDR_MAX",
                    PdrExpectedStatus.NORMAL,
                    PdrMismatchRule.DRIVER_RESULT_GT_HALF,
                    10.0,
                    0.5,
                    "voltage_profile:VCC_PDR_MAX",
                    None,
                    "pin_group:IO_ALLPINS",
                ),
                (
                    "PDR_MIN",
                    PdrExpectedStatus.RESET,
                    PdrMismatchRule.DRIVER_RESULT_LT_HALF,
                    0.0,
                    0.5,
                    "voltage_profile:VCC_PDR_MIN",
                    None,
                    "pin_group:IO_ALLPINS",
                ),
            ),
        )
        limits = plan.power_limits
        self.assertEqual(limits.rail_scope, "ALL_TARGET_POWER_RAILS")
        self.assertIsNone(limits.voltage_range_v)
        self.assertEqual(limits.current_range_ma, 500.0)
        self.assertIsNone(limits.current_limit_ma)
        self.assertEqual(limits.compliance_profile, "I7")
        self.assertEqual(limits.force_wait_ms, 0.5)
        self.assertIsNone(limits.level_settle_ms)
        self.assertEqual(limits.drive_high_ratio, 1.0)
        self.assertEqual(limits.drive_low_v, 0.0)
        self.assertEqual(limits.compare_high_ratio, 0.55)
        self.assertEqual(limits.compare_low_ratio, 0.45)

    def test_both_formal_rows_share_protocol_without_absorbing_step(self):
        self.assertEqual(
            tuple((op.row, op.cp, op.item) for op in self.operations),
            ((41, "CP1", "Pdr_Verify"), (113, "CP2", "Pdr_Verify")),
        )

        for platform in PdrVerifyPlatform:
            plans = tuple(
                compile_pdr_verify_plan(self.flow, operation, platform)
                for operation in self.operations
            )
            self.assertEqual(
                tuple((plan.row, plan.excel_row, plan.cp) for plan in plans),
                ((41, 43, "CP1"), (113, 115, "CP2")),
            )
            self.assertEqual(
                tuple(
                    (
                        plan.typed_kind,
                        plan.initial_power_profile,
                        plan.relay,
                        plan.scalar_limits,
                        plan.pe_action,
                        plan.platform,
                        plan.voltage_application,
                        plan.pattern_resources,
                        plan.status_checks,
                        plan.power_limits,
                    )
                    for plan in plans
                ),
                (self._protocol_signature(plans[0]),) * 2,
            )
            self.assertFalse(hasattr(plans[0], "step"))
            with self.assertRaises(FrozenInstanceError):
                plans[0].cp = "CP9"

    def test_rejects_bor_ordinary_verify_and_misaligned_operation_identity(self):
        pdr_operation = self.operations[0]
        for item in ("Bor_Verify", "Ordinary_Verify"):
            flow = self.flow.copy()
            flow.at[pdr_operation.row, "item"] = item
            operation = replace(pdr_operation, item=item)
            with self.subTest(item=item):
                self._assert_error(
                    "PV.PROTOCOL.UNSUPPORTED",
                    lambda operation=operation, flow=flow: compile_pdr_verify_plan(
                        flow, operation, "chroma"
                    ),
                )

        operation = pdr_operation
        mismatches = (
            replace(operation, source_type="trim"),
            replace(operation, mode="hex"),
            replace(operation, typed_kind="VERIFY_HEX"),
            replace(
                operation,
                provenance=replace(operation.provenance, coordinate="A999"),
            ),
        )
        for mismatch in mismatches:
            with self.subTest(operation=mismatch):
                self._assert_error(
                    "PV.OPERATION.MISMATCH",
                    lambda mismatch=mismatch: compile_pdr_verify_plan(
                        self.flow, mismatch, "chroma"
                    ),
                )

        changed_flow = self.flow.copy()
        changed_flow.at[operation.row, "item"] = "Ordinary_Verify"
        self._assert_error(
            "PV.ROW.MISMATCH",
            lambda: compile_pdr_verify_plan(changed_flow, operation, "chroma"),
        )

    def test_rejects_pe_scalar_judge_and_missing_power_profile(self):
        operation = self.operations[0]
        mutations = (
            ("PE", "PROGRAM", "PV.PE.UNSUPPORTED"),
            ("Low", 0.1, "PV.JUDGE.SCALAR_INPUT_UNSUPPORTED"),
            ("target", 0.2, "PV.JUDGE.SCALAR_INPUT_UNSUPPORTED"),
            ("High", 0.3, "PV.JUDGE.SCALAR_INPUT_UNSUPPORTED"),
            ("FV/FI", "PDR", "PV.JUDGE.SCALAR_INPUT_UNSUPPORTED"),
            ("meas pin", "PA0", "PV.JUDGE.SCALAR_INPUT_UNSUPPORTED"),
            ("UNIT", "V", "PV.JUDGE.SCALAR_INPUT_UNSUPPORTED"),
            ("Vcc", "/", "PV.POWER.PROFILE_REQUIRED"),
        )
        for column, value, code in mutations:
            with self.subTest(column=column):
                changed_flow = self.flow.copy()
                changed_flow.at[operation.row, column] = value
                self._assert_error(
                    code,
                    lambda changed_flow=changed_flow: compile_pdr_verify_plan(
                        changed_flow, operation, "s100"
                    ),
                )

    def test_rejects_unknown_platform_and_invalid_row(self):
        operation = self.operations[0]
        self._assert_error(
            "PV.PLATFORM.UNKNOWN",
            lambda: compile_pdr_verify_plan(self.flow, operation, "future"),
        )
        self._assert_error(
            "PV.ROW.INVALID",
            lambda: compile_pdr_verify_plan(
                self.flow, replace(operation, row=len(self.flow)), "chroma"
            ),
        )

    def test_compiler_is_deterministic_pure_and_not_a_tester_renderer(self):
        before = self.flow.copy(deep=True)

        first = compile_pdr_verify_plan(self.flow, self.operations[0], "chroma")
        second = compile_pdr_verify_plan(self.flow, self.operations[0], "chroma")

        self.assertEqual(first, second)
        assert_frame_equal(self.flow, before)
        source = (
            Path(__file__).resolve().parents[1]
            / "program_gen"
            / "core"
            / "pdr_verify.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "program_gen import state",
            "WorkbookReader",
            "openpyxl",
            "ResourceRequest",
            "RUN_PATTERN(",
            "JUDGE_PAT(",
            "CALL_MACRO",
            ".write(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    @staticmethod
    def _protocol_signature(plan):
        return (
            plan.typed_kind,
            plan.initial_power_profile,
            plan.relay,
            plan.scalar_limits,
            plan.pe_action,
            plan.platform,
            plan.voltage_application,
            plan.pattern_resources,
            plan.status_checks,
            plan.power_limits,
        )

    def _assert_error(self, code, call):
        with self.assertRaises(PdrVerifyPlanError) as caught:
            call()
        self.assertEqual(caught.exception.code, code)


if __name__ == "__main__":
    unittest.main()
