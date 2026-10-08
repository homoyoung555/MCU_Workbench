from tests.workspace_paths import FORMAL_MASTER as EXTERNAL_FORMAL_MASTER
"""Public-contract tests for canonical CP schedule plans."""

from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import unittest

from program_gen.compiler import ProductCompiler
from program_gen.core.schedule_plan import (
    BinBindingKind,
    SchedulePlanError,
    compile_canonical_schedule_plan,
)
from program_gen.program_plan import ScheduleGroup, TestsGroup as _TestsGroup
from program_gen.workbook import WorkbookReader


ROOT = Path(__file__).resolve().parents[1]
FORMAL_MASTER = EXTERNAL_FORMAL_MASTER


class CanonicalSchedulePlanFormalMasterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        workbook = WorkbookReader().read(FORMAL_MASTER)
        compilation = ProductCompiler().compile(workbook).require_success()
        cls.flow = workbook.dataframe("FLOW")
        cls.trim_specs = compilation.plan.catalogs.trim_specs
        cls.cp_plans = compilation.cp_plans

    def test_cp1_expands_trim_variants_without_changing_flow_input(self) -> None:
        original_flow = self.flow.copy(deep=True)

        schedule = compile_canonical_schedule_plan(
            self.cp_plans["CP1"], self.flow, self.trim_specs
        )

        self.assertEqual(schedule.cp, "CP1")
        self.assertEqual(len(schedule.definitions), 92)
        self.assertEqual(len(schedule.entries), 123)
        self.assertEqual(
            tuple(
                (entry.flow_order, entry.render_name, entry.variant, entry.enabled)
                for entry in schedule.entries[:3]
            ),
            (
                (0, "Os_Test", None, True),
                (1, "Vref0P8_Tc_Trim", "BISECTION", True),
                (1, "Vref0P8_Tc_Dac_Loop", "FULL_SCAN", False),
            ),
        )
        self.assertTrue(self.flow.equals(original_flow))
        with self.assertRaises(FrozenInstanceError):
            schedule.cp = "MUTATED"

    def test_formal_cp_schedule_preserves_bins_and_system_schedule_contract(self) -> None:
        expected_counts = {"CP1": (92, 123), "CP2": (67, 67), "CP3": (35, 39)}

        for cp, (definition_count, entry_count) in expected_counts.items():
            with self.subTest(cp=cp):
                cp_plan = self.cp_plans[cp]
                schedule = compile_canonical_schedule_plan(cp_plan, self.flow, self.trim_specs)
                original_by_definition = {
                    entry.definition_id: entry for entry in cp_plan.schedule
                }
                definitions_by_item = {definition.item: definition for definition in schedule.definitions}

                self.assertEqual(len(schedule.definitions), definition_count)
                self.assertEqual(len(schedule.entries), entry_count)
                self.assertEqual(
                    len({definition.identity for definition in schedule.definitions}),
                    len(schedule.definitions),
                )
                self.assertEqual(
                    len({definition.render_name for definition in schedule.definitions}),
                    len(schedule.definitions),
                )
                self.assertEqual(definitions_by_item["OTP_READ"].render_name, "OTP_Read")
                self.assertEqual(definitions_by_item["NM_Data_Read"].render_name, "NM_Data_Read")
                system_entries = schedule.entries[-2:]
                self.assertEqual(
                    tuple(entry.definition_id for entry in system_entries),
                    (
                        definitions_by_item["OTP_READ"].identity,
                        definitions_by_item["NM_Data_Read"].identity,
                    ),
                )
                self.assertEqual(
                    tuple(entry.render_name for entry in system_entries),
                    ("OTP_Read", "NM_Data_Read"),
                )
                for entry in system_entries:
                    self.assertEqual(entry.placement, "SYSTEM_UNBOOKED")
                    self.assertEqual(
                        entry.bin_binding.kind,
                        BinBindingKind.DEFINITION_REFERENCE,
                    )
                    self.assertEqual(
                        entry.bin_binding.definition_id,
                        definitions_by_item[f"Pgm_CP{cp[-1]}ID_Read"].identity,
                    )
                for entry in schedule.entries:
                    original = original_by_definition[entry.definition_id]
                    with self.subTest(entry=entry.identity):
                        self.assertEqual(entry.force_pass, original.force_pass)
                        if entry.placement == "SYSTEM_UNBOOKED":
                            continue
                        self.assertEqual(entry.bin_binding.kind, BinBindingKind.DIRECT)
                        self.assertEqual(entry.bin_binding.hardware_bin, original.hardware_bin)
                        self.assertEqual(entry.bin_binding.software_bin, original.software_bin)

    def test_schedule_projects_enabled_and_force_pass_from_cp_plan(self) -> None:
        cp_plan = self.cp_plans["CP1"]
        first = replace(cp_plan.schedule[0], enabled=False, force_pass=True)
        fixture = replace(cp_plan, scheduling=ScheduleGroup((first,)))

        schedule = compile_canonical_schedule_plan(fixture, self.flow, self.trim_specs)

        self.assertEqual(len(schedule.entries), 1)
        self.assertFalse(schedule.entries[0].enabled)
        self.assertTrue(schedule.entries[0].force_pass)
        self.assertEqual(
            (schedule.entries[0].bin_binding.hardware_bin, schedule.entries[0].bin_binding.software_bin),
            ("3", "3"),
        )

    def test_schedule_rejects_missing_definition_and_duplicate_identity_stably(self) -> None:
        cp_plan = self.cp_plans["CP1"]
        missing = replace(
            cp_plan,
            scheduling=ScheduleGroup((replace(cp_plan.schedule[0], definition_id="missing"),)),
        )
        duplicate = replace(
            cp_plan,
            tests=_TestsGroup((cp_plan.definitions[0], cp_plan.definitions[0])),
        )

        with self.assertRaisesRegex(SchedulePlanError, "SP.DEFINITION.MISSING"):
            compile_canonical_schedule_plan(missing, self.flow, self.trim_specs)
        with self.assertRaisesRegex(SchedulePlanError, "SP.IDENTITY.DUPLICATE"):
            compile_canonical_schedule_plan(duplicate, self.flow, self.trim_specs)

    def test_nm_data_read_requires_exactly_one_same_cp_program_id_definition(self) -> None:
        cp_plan = self.cp_plans["CP1"]
        target = next(item for item in cp_plan.definitions if item.item == "Pgm_CP1ID_Read")
        missing = replace(
            cp_plan,
            tests=_TestsGroup(tuple(item for item in cp_plan.definitions if item != target)),
            scheduling=ScheduleGroup(tuple(
                entry for entry in cp_plan.schedule if entry.definition_id != target.identity
            )),
        )
        ambiguous = replace(
            cp_plan,
            tests=_TestsGroup(cp_plan.definitions + (replace(target, identity="DEF:DUPLICATE"),)),
        )

        with self.assertRaisesRegex(SchedulePlanError, "SP.BIN_REFERENCE.MISSING"):
            compile_canonical_schedule_plan(missing, self.flow, self.trim_specs)
        with self.assertRaisesRegex(SchedulePlanError, "SP.BIN_REFERENCE.AMBIGUOUS"):
            compile_canonical_schedule_plan(ambiguous, self.flow, self.trim_specs)
