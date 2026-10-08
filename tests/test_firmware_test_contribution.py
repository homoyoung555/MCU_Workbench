from dataclasses import replace
import unittest

from program_gen.compiler import ProductCompiler
from program_gen.core.firmware_test import DownloadPhase
from program_gen.core.firmware_test_contribution import (
    FirmwareTestContributionError,
    compile_firmware_test_contribution,
)
from program_gen.render_plan import TargetKey
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER


class FirmwareTestContributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compilation = ProductCompiler().compile(
            WorkbookReader().read(FORMAL_MASTER)
        ).require_success()
        cls.plans = tuple(
            cls.compilation.plan.catalogs.firmware_test_plans.values()
        )

    def test_formal_fourteen_plans_bind_one_definition_and_entry_each(self):
        self.assertEqual(len(self.plans), 14)
        for platform in ("chroma", "s100"):
            contributions = []
            for plan in self.plans:
                target = TargetKey(
                    platform, plan.cp, "lab", f"FIRMWARE_{platform}_{plan.cp}"
                )
                contribution = compile_firmware_test_contribution(
                    plan,
                    target,
                    self.compilation.for_cp(plan.cp).canonical_schedule,
                )
                contributions.append(contribution)
                self.assertEqual(len(contribution.definitions), 1)
                self.assertEqual(len(contribution.schedule_entries), 1)
                self.assertEqual(len(contribution.requires), 1)
                self.assertEqual(
                    contribution.requires[0].ref.namespace,
                    "TEST_BODY",
                )
                self.assertEqual(contribution.sections, ())
                self.assertEqual(contribution.resources, ())
                self.assertEqual(contribution.provides, ())
            self.assertEqual(
                len({item.identity for item in contributions}),
                14,
            )
            self.assertEqual(
                len({item.definitions[0].identity for item in contributions}),
                14,
            )

    def test_download_resources_are_platform_specific_and_deduplicated(self):
        plan = self._plan("CP3", "Download_Code")
        phase = plan.phases[0]
        self.assertIsInstance(phase, DownloadPhase)
        duplicated = replace(
            plan,
            phases=(phase, phase),
            execution_steps=(phase, phase),
        )
        schedule = self.compilation.for_cp("CP3").canonical_schedule
        definition = next(
            item for item in schedule.definitions
            if item.source_rows == plan.excel_rows
        )
        schedule = replace(
            schedule,
            definitions=tuple(
                replace(item, source_rows=duplicated.excel_rows)
                if item.identity == definition.identity else item
                for item in schedule.definitions
            ),
        )

        chroma = compile_firmware_test_contribution(
            duplicated,
            TargetKey("chroma", "CP3", "lab", "FW_CHROMA_CP3"),
            schedule,
        )
        s100 = compile_firmware_test_contribution(
            duplicated,
            TargetKey("s100", "CP3", "lab", "FW_S100_CP3"),
            schedule,
        )

        self.assertEqual(len(chroma.resource_requires), 1)
        self.assertEqual(len(s100.resource_requires), 1)
        self.assertEqual(
            chroma.resource_requires[0].relative_path,
            f"pat/{phase.pattern.name}.pat",
        )
        self.assertEqual(
            s100.resource_requires[0].relative_path,
            f"{phase.pattern.name}.sd",
        )
        self.assertEqual(
            chroma.resource_requires[0].logical_identity,
            phase.pattern.logical_identity,
        )
        self.assertEqual(
            s100.resource_requires[0].logical_identity,
            phase.pattern.logical_identity,
        )

    def test_rejects_a_plan_typed_kind_inconsistent_with_its_phases(self):
        plan = self._plan("CP1", "SRAM_CKB_Test")
        invalid = replace(plan, typed_kind="CODE_DOWNLOAD")

        with self.assertRaises(FirmwareTestContributionError) as raised:
            compile_firmware_test_contribution(
                invalid,
                TargetKey("chroma", "CP1", "lab", "FW_CP1"),
                self.compilation.for_cp("CP1").canonical_schedule,
            )

        self.assertEqual(raised.exception.code, "FWC.PLAN.TYPED_KIND_MISMATCH")

    def test_rejects_a_definition_that_only_matches_the_first_phase_row(self):
        plan = self._plan("CP3", "Power_Test")
        schedule = self.compilation.for_cp("CP3").canonical_schedule
        definition = next(
            item for item in schedule.definitions
            if item.source_rows == plan.excel_rows
        )
        schedule = replace(
            schedule,
            definitions=tuple(
                replace(item, source_rows=plan.excel_rows[:1])
                if item.identity == definition.identity else item
                for item in schedule.definitions
            ),
        )

        with self.assertRaises(FirmwareTestContributionError) as raised:
            compile_firmware_test_contribution(
                plan,
                TargetKey("chroma", "CP3", "lab", "FW_CP3"),
                schedule,
            )

        self.assertEqual(
            raised.exception.code,
            "FWC.DEFINITION.IDENTITY_UNRESOLVED",
        )

    def test_rejects_target_schedule_and_entry_mismatches(self):
        plan = self._plan("CP1", "SRAM_CKB_Test")
        cp1_schedule = self.compilation.for_cp("CP1").canonical_schedule

        cases = (
            (
                TargetKey("chroma", "CP2", "lab", "FW_CP2"),
                cp1_schedule,
                "FWC.TARGET.CP_MISMATCH",
            ),
            (
                TargetKey("other", "CP1", "lab", "FW_CP1"),
                cp1_schedule,
                "FWC.TARGET.PLATFORM_UNSUPPORTED",
            ),
            (
                TargetKey("chroma", "CP1", "lab", "FW_CP1"),
                replace(cp1_schedule, cp="CP2"),
                "FWC.SCHEDULE.CP_MISMATCH",
            ),
        )
        for target, schedule, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(FirmwareTestContributionError) as raised:
                    compile_firmware_test_contribution(plan, target, schedule)
                self.assertEqual(raised.exception.code, code)

        definition = next(
            item for item in cp1_schedule.definitions
            if item.source_rows == plan.excel_rows
        )
        entry = next(
            item for item in cp1_schedule.entries
            if item.definition_id == definition.identity
        )
        ambiguous = replace(
            cp1_schedule,
            entries=cp1_schedule.entries + (replace(entry, identity="duplicate"),),
        )
        with self.assertRaises(FirmwareTestContributionError) as raised:
            compile_firmware_test_contribution(
                plan,
                TargetKey("chroma", "CP1", "lab", "FW_CP1"),
                ambiguous,
            )
        self.assertEqual(raised.exception.code, "FWC.SCHEDULE.IDENTITY_UNRESOLVED")

    def _plan(self, cp, item):
        return next(
            plan for plan in self.plans
            if plan.cp == cp and plan.item == item
        )


if __name__ == "__main__":
    unittest.main()
