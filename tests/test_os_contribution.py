from __future__ import annotations

from tests.workspace_paths import FORMAL_MASTER as EXTERNAL_FORMAL_MASTER

import ast
from dataclasses import replace
from pathlib import Path
import unittest

from program_gen.compiler import ProductCompiler
from program_gen.core.os_contribution import (
    OsContributionError,
    compile_os_contribution,
)
from program_gen.core.os_plan import (
    OsPlatformProfile,
    OsSafetyAction,
    compile_os_plan,
)
from program_gen.flow_kinds import compile_flow_operations
from program_gen.render_plan import (
    RenderSymbolRef,
    ScheduleEntryContribution,
    SymbolRequirement,
    TargetKey,
    TestDefinitionContribution,
)
from program_gen.workbook import WorkbookReader


ROOT = Path(__file__).resolve().parents[1]
FORMAL_MASTER = EXTERNAL_FORMAL_MASTER


class OsContributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(workbook).require_success()
        cls.os_operations = {
            operation.cp: operation
            for operation in compile_flow_operations(workbook)
            if operation.typed_kind == "OS"
        }

    def test_formal_master_contributes_each_cp_to_both_platform_profiles(self):
        expected_actions = {
            OsPlatformProfile.CHROMA: (
                OsSafetyAction.ORDINARY_IO,
                OsSafetyAction.TP,
                OsSafetyAction.POWER_RAIL,
            ),
            OsPlatformProfile.S100: (
                OsSafetyAction.ORDINARY_IO,
                OsSafetyAction.TP,
            ),
        }
        for profile, actions in expected_actions.items():
            for cp, operation in self.os_operations.items():
                with self.subTest(platform=profile.value, cp=cp):
                    cp_plan = self.compilation.for_cp(cp)
                    os_plan = compile_os_plan(operation, profile)
                    target = TargetKey(profile.value, cp, "formal", f"V_TEST_{cp}")

                    contribution = compile_os_contribution(os_plan, target, cp_plan)
                    definition, schedule_entry = _canonical_os_identity(
                        cp_plan.canonical_schedule, os_plan
                    )

                    self.assertEqual(contribution.target, target)
                    self.assertEqual(contribution.sections, ())
                    self.assertEqual(contribution.resources, ())
                    self.assertEqual(contribution.resource_requires, ())
                    self.assertEqual(
                        contribution.definitions,
                        (TestDefinitionContribution(
                            definition.identity, "OS", contribution.identity
                        ),),
                    )
                    self.assertEqual(
                        contribution.schedule_entries,
                        (ScheduleEntryContribution(
                            schedule_entry.identity,
                            definition.identity,
                            next(
                                ordinal
                                for ordinal, entry in enumerate(
                                    cp_plan.canonical_schedule.entries
                                )
                                if entry.identity == schedule_entry.identity
                            ),
                            schedule_entry.enabled,
                        ),),
                    )
                    self.assertEqual(
                        contribution.requires,
                        (
                            SymbolRequirement(
                                RenderSymbolRef(
                                    "TEST_BODY",
                                    f"{profile.value}:{schedule_entry.identity}",
                                ),
                                "SECTION",
                                None,
                                "TARGET",
                            ),
                            *(
                                SymbolRequirement(
                                    RenderSymbolRef(
                                        "OS_ENVIRONMENT",
                                        f"{profile.value}:{action.value}",
                                    ),
                                    "SAFETY_ACTION",
                                    None,
                                    "TARGET",
                                )
                                for action in actions
                            ),
                        ),
                    )

    def test_uses_the_existing_canonical_definition_and_schedule_identities(self):
        plan = compile_os_plan(self.os_operations["CP1"], "chroma")
        cp_plan = self.compilation.for_cp("CP1")
        contribution = compile_os_contribution(
            plan, TargetKey("chroma", "CP1", "formal", "V_TEST_CP1"), cp_plan
        )
        definition, entry = _canonical_os_identity(cp_plan.canonical_schedule, plan)

        self.assertEqual(contribution.definitions[0].identity, definition.identity)
        self.assertEqual(contribution.schedule_entries[0].identity, entry.identity)
        self.assertEqual(
            contribution.schedule_entries[0].definition_identity, entry.definition_id
        )

    def test_rejects_mismatched_profile_cp_and_unresolved_canonical_identity(self):
        operation = self.os_operations["CP1"]
        chroma_plan = compile_os_plan(operation, "chroma")
        cp1 = self.compilation.for_cp("CP1")

        with self.assertRaisesRegex(OsContributionError, "OC.TARGET.PROFILE_MISMATCH"):
            compile_os_contribution(
                chroma_plan, TargetKey("s100", "CP1", "formal", "V_TEST_CP1"), cp1
            )
        with self.assertRaisesRegex(OsContributionError, "OC.TARGET.CP_MISMATCH"):
            compile_os_contribution(
                chroma_plan, TargetKey("chroma", "CP2", "formal", "V_TEST_CP2"), cp1
            )
        with self.assertRaisesRegex(OsContributionError, "OC.TARGET.PLATFORM"):
            compile_os_contribution(
                chroma_plan, TargetKey("other", "CP1", "formal", "V_TEST_CP1"), cp1
            )
        with self.assertRaisesRegex(OsContributionError, "OC.PLAN.SAFETY_ACTIONS"):
            compile_os_contribution(
                replace(chroma_plan, safety_actions=(OsSafetyAction.ORDINARY_IO,)),
                TargetKey("chroma", "CP1", "formal", "V_TEST_CP1"),
                cp1,
            )
        with self.assertRaisesRegex(OsContributionError, "OC.SCHEDULE.MISSING"):
            compile_os_contribution(
                chroma_plan,
                TargetKey("chroma", "CP1", "formal", "V_TEST_CP1"),
                replace(cp1, scheduling=replace(cp1.scheduling, canonical=None)),
            )

        definition, _ = _canonical_os_identity(cp1.canonical_schedule, chroma_plan)
        without_os = replace(
            cp1.canonical_schedule,
            definitions=tuple(
                item for item in cp1.canonical_schedule.definitions
                if item.identity != definition.identity
            ),
        )
        with self.assertRaisesRegex(
            OsContributionError, "OC.DEFINITION.IDENTITY_UNRESOLVED"
        ):
            compile_os_contribution(
                chroma_plan,
                TargetKey("chroma", "CP1", "formal", "V_TEST_CP1"),
                replace(cp1, scheduling=replace(cp1.scheduling, canonical=without_os)),
            )

    def test_core_is_pure_and_does_not_construct_canonical_identities(self):
        source_path = ROOT / "program_gen" / "core" / "os_contribution.py"
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(source_path))
        imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        imports.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )

        self.assertFalse({"program_gen.state", "program_gen.workbook"} & imports)
        self.assertFalse(any(
            isinstance(node, ast.Name) and node.id == "G" for node in ast.walk(tree)
        ))
        self.assertNotIn('f"DEF:', source)
        self.assertNotIn('f"SCHEDULE:', source)
        self.assertNotIn("open(", source)


def _canonical_os_identity(schedule, os_plan):
    definitions = tuple(
        definition
        for definition in schedule.definitions
        if definition.cp == os_plan.cp
        and definition.item.casefold() == os_plan.item.casefold()
        and definition.source_rows == (os_plan.row + 2,)
    )
    if len(definitions) != 1:
        raise AssertionError(f"fixture expected one OS definition, got {definitions!r}")
    entries = tuple(
        entry for entry in schedule.entries if entry.definition_id == definitions[0].identity
    )
    if len(entries) != 1:
        raise AssertionError(f"fixture expected one OS schedule entry, got {entries!r}")
    return definitions[0], entries[0]


if __name__ == "__main__":
    unittest.main()
