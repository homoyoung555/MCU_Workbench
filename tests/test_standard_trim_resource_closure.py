"""STANDARD_TRIM FBIST protocol pattern resource-closure ownership tests.

Single resource ownership chain for the FBIST protocol patterns:

    canonical Recipe (TrimSpec.protocol / operations / dac)
        → CpProgramPlan resource closure (ResourcesGroup.identities)
        → STANDARD_TRIM Contribution resource reference

The canonical enter/exit identities (``enter_fbist_mode`` / ``exit_fbist_mode``)
come from the typed Recipe only.  The Contribution must never derive them from
item names, legacy writers, Golden output, platform extensions, or historical
defaults, and it may only reference identities the CP resource closure owns.
Removing any Recipe-declared resource from the closure blocks the projection.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import ast
import unittest

from tests.workspace_paths import FORMAL_MASTER as EXTERNAL_FORMAL_MASTER

from program_gen.compiler import ProductCompiler
from program_gen.core.standard_trim_contribution import (
    StandardTrimContributionError,
    compile_standard_trim_contribution,
    standard_trim_pattern_names,
)
from program_gen.render_plan import TargetKey
from program_gen.workbook import WorkbookReader


ROOT = Path(__file__).resolve().parents[1]
FORMAL_MASTER = EXTERNAL_FORMAL_MASTER
CHROMA_TARGET = TargetKey("chroma", "CP1", "lab", "V_TEST_CP1")
S100_TARGET = TargetKey("s100", "CP1", "lab", "V_TEST_CP1")


class StandardTrimResourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.compilation = (
            ProductCompiler()
            .compile(WorkbookReader().read(FORMAL_MASTER))
            .require_success()
        )
        cls.spec = next(
            spec
            for spec in cls.compilation.plan.catalogs.trim_specs.values()
            if spec.item == "Hsi_8M" and spec.cp == "CP1"
        )
        cls.schedule = cls.compilation.for_cp("CP1").canonical_schedule
        cls.closure = cls.compilation.for_cp("CP1").resources.identities

    def _required_names(self, contribution) -> set[str]:
        return {
            requirement.logical_identity.removeprefix("pattern:").casefold()
            for requirement in contribution.resource_requires
        }

    def _owned_names(self) -> set[str]:
        return {str(name).strip().casefold() for name in self.closure}

    # ------------------------------------------------------------------
    # GREEN: the canonical Recipe owns every FBIST protocol pattern, and
    # the CP resource closure contains every Recipe-declared pattern.
    # ------------------------------------------------------------------

    def test_recipe_declared_protocol_patterns_are_owned_by_cp_closure(self):
        recipe_declared = {
            self.spec.protocol.enter_pattern.casefold(),
            self.spec.protocol.exit_pattern.casefold(),
            self.spec.dac.pattern_name.casefold(),
        }
        recipe_declared.update(
            operation.reference.casefold()
            for operation in self.spec.operations
            if operation.reference
        )
        missing = recipe_declared - self._owned_names()
        self.assertFalse(
            missing,
            f"recipe-declared patterns not owned by the CP resource closure: "
            f"{sorted(missing)}",
        )

    def test_contribution_pattern_identities_are_owned_by_cp_closure(self):
        for target in (CHROMA_TARGET, S100_TARGET):
            with self.subTest(platform=target.platform):
                contribution = compile_standard_trim_contribution(
                    self.spec,
                    target,
                    self.schedule,
                    resource_closure=self.closure,
                )
                missing = self._required_names(contribution) - self._owned_names()
                self.assertFalse(
                    missing,
                    f"contribution references unowned pattern identities: "
                    f"{sorted(missing)}",
                )

    def test_contribution_and_closure_share_the_canonical_identity(self):
        # The contribution's logical identities are exactly
        # ``pattern:<canonical>`` for the Recipe-declared pattern names.
        contribution = compile_standard_trim_contribution(
            self.spec,
            CHROMA_TARGET,
            self.schedule,
            resource_closure=self.closure,
        )
        canonical = set(standard_trim_pattern_names(self.spec))
        self.assertEqual(
            {
                requirement.logical_identity
                for requirement in contribution.resource_requires
            },
            {f"pattern:{name}" for name in canonical},
        )

    # ------------------------------------------------------------------
    # RED→GREEN: removing a Recipe-declared resource from the closure
    # blocks the projection.
    # ------------------------------------------------------------------

    def test_closure_missing_enter_pattern_blocks(self):
        closure = tuple(
            name
            for name in self.closure
            if name.casefold() != self.spec.protocol.enter_pattern.casefold()
        )
        with self.assertRaisesRegex(
            StandardTrimContributionError, "SC.RESOURCE.CLOSURE_MISSING"
        ) as ctx:
            compile_standard_trim_contribution(
                self.spec,
                CHROMA_TARGET,
                self.schedule,
                resource_closure=closure,
            )
        self.assertIn("enter_fbist_mode", str(ctx.exception))

    def test_closure_missing_exit_pattern_blocks(self):
        closure = tuple(
            name
            for name in self.closure
            if name.casefold() != self.spec.protocol.exit_pattern.casefold()
        )
        with self.assertRaisesRegex(
            StandardTrimContributionError, "SC.RESOURCE.CLOSURE_MISSING"
        ):
            compile_standard_trim_contribution(
                self.spec,
                S100_TARGET,
                self.schedule,
                resource_closure=closure,
            )

    # ------------------------------------------------------------------
    # Mismatch coverage: CP / platform / definition identity.
    # ------------------------------------------------------------------

    def test_cp_mismatched_closure_blocks(self):
        # A CP1-only trim spec must not project against CP2's closure.
        spec = next(
            item
            for item in self.compilation.plan.catalogs.trim_specs.values()
            if item.item == "Vrefbuf2p5" and item.cp == "CP1"
        )
        cp2_closure = self.compilation.for_cp("CP2").resources.identities
        with self.assertRaisesRegex(
            StandardTrimContributionError, "SC.RESOURCE.CLOSURE_MISSING"
        ):
            compile_standard_trim_contribution(
                spec,
                CHROMA_TARGET,
                self.schedule,
                resource_closure=cp2_closure,
            )

    def test_platform_neutral_closure_serves_both_platforms(self):
        # The closure owns platform-neutral logical identities; the same
        # closure validates both Chroma and S100 projections.
        for target in (CHROMA_TARGET, S100_TARGET):
            with self.subTest(platform=target.platform):
                contribution = compile_standard_trim_contribution(
                    self.spec,
                    target,
                    self.schedule,
                    resource_closure=self.closure,
                )
                self.assertTrue(contribution.resource_requires)
                self.assertEqual(
                    self._required_names(contribution) - self._owned_names(),
                    set(),
                )

    def test_definition_identity_mismatch_blocks(self):
        wrong = replace(
            self.schedule,
            definitions=tuple(
                replace(item, source_rows=(999,))
                for item in self.schedule.definitions
                if item.item.casefold() == "Hsi_8M"
            ),
        )
        with self.assertRaisesRegex(
            StandardTrimContributionError, "SC.DEFINITION.IDENTITY_UNRESOLVED"
        ):
            compile_standard_trim_contribution(
                self.spec,
                CHROMA_TARGET,
                wrong,
                resource_closure=self.closure,
            )

    # ------------------------------------------------------------------
    # Purity: no Excel / G / legacy writer / Golden / filesystem, and
    # enter/exit identities come only from typed Recipe fields.
    # ------------------------------------------------------------------

    def test_resource_closure_validation_is_pure(self):
        source = (
            ROOT
            / "program_gen"
            / "core"
            / "standard_trim_contribution.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertFalse(
            {
                "openpyxl", "pandas", "os", "pathlib", "shutil", "subprocess",
                "program_gen.state", "program_gen.workbook",
                "program_gen.platforms", "tools",
            } & imports
        )
        calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertFalse(
            {"open", "read_bytes", "glob", "rglob", "listdir", "scandir"} & calls
        )
        for forbidden in ("ResourceRequest", "source_identity", "WorkbookReader"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)
        # enter/exit identities must come from the typed protocol fields only.
        self.assertIn("spec.protocol.enter_pattern", source)
        self.assertIn("spec.protocol.exit_pattern", source)

    def test_pattern_identity_derivation_uses_only_typed_spec_fields(self):
        # standard_trim_pattern_names reads only typed Recipe fields
        # (protocol / operations / dac) — never item names or extensions.
        raw = (
            self.spec.protocol.enter_pattern,
            *(op.reference for op in self.spec.operations if op.reference),
            self.spec.dac.pattern_name,
            self.spec.protocol.exit_pattern,
        )
        expected = tuple(dict.fromkeys(name for name in raw if name))
        actual = standard_trim_pattern_names(self.spec)
        self.assertEqual(
            tuple(name.casefold() for name in actual),
            tuple(name.casefold() for name in expected),
        )
        self.assertNotIn("Hsi_8M", actual)


if __name__ == "__main__":
    unittest.main()
