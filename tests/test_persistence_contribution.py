from __future__ import annotations

from tests.workspace_paths import FORMAL_MASTER as EXTERNAL_FORMAL_MASTER

from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import unittest

from program_gen.compiler import ProductCompiler
from program_gen.core.otp_program import PagePatternPlan
from program_gen.core.persistence_contribution import (
    PersistenceContributionError,
    compile_persistence_id_contribution,
)
from program_gen.core.persistence_recipe import (
    PersistenceOperation,
    PersistenceRowPlan,
)
from program_gen.render_plan import (
    ProgramAssembler,
    ProgramContribution,
    RenderSymbolRef,
    RenderPlanError,
    ResourceRequest,
    ResourceRequirement,
    ScheduleEntryContribution,
    SymbolProvision,
    SymbolRequirement,
    TargetKey,
    TestDefinitionContribution,
)
from program_gen.workbook import WorkbookReader


ROOT = Path(__file__).resolve().parents[1]
FORMAL_MASTER = EXTERNAL_FORMAL_MASTER
S100_TARGET = TargetKey("s100", "CP2", "lab", "V_PCD009_CP2")
CHROMA_TARGET = TargetKey("chroma", "CP2", "lab", "V_PCD009_CP2")


class PersistenceIdContributionFormalMasterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        compilation = ProductCompiler().compile(
            WorkbookReader().read(FORMAL_MASTER)
        ).require_success()
        cls.schedule = compilation.for_cp("CP2").canonical_schedule
        cls.id_plan = compilation.plan.catalogs.id_plans.for_row(166)
        cls.persistence_plan = compilation.plan.catalogs.persistence.for_row(166)
        cls.uid_patterns = (PagePatternPlan(
            page="uid",
            erase_pattern="fbist_page_erase_uid",
            program_pattern="fbist_page_prog_cp2_id",
            read_pattern="fbist_page_read_cp2_id",
            is_uid=True,
        ),)

    def test_preserves_formal_definition_and_schedule_identity(self) -> None:
        contribution = compile_persistence_id_contribution(
            S100_TARGET,
            self.schedule,
            self.id_plan,
            self.persistence_plan,
            self.uid_patterns,
        )
        definition_identity = "DEF:CP2:uid:Pgm_CP2ID_Read:(168,)"
        entry_ordinal = next(
            ordinal
            for ordinal, entry in enumerate(self.schedule.entries)
            if entry.definition_id == definition_identity
        )

        self.assertEqual(
            contribution.definitions,
            (TestDefinitionContribution(
                definition_identity,
                "UID",
                contribution.identity,
            ),),
        )
        self.assertEqual(
            contribution.schedule_entries,
            (ScheduleEntryContribution(
                f"SCHEDULE:{definition_identity}",
                definition_identity,
                entry_ordinal,
                True,
            ),),
        )
        self.assertEqual(contribution.sections, ())
        self.assertEqual(contribution.resources, ())

    def test_declares_dual_platform_body_helper_symbol_and_pattern_contracts(
        self,
    ) -> None:
        definition_identity = "DEF:CP2:uid:Pgm_CP2ID_Read:(168,)"
        pattern_names = (
            "fbist_page_erase_uid",
            "fbist_page_prog_cp2_id",
            "fbist_page_read_cp2_id",
        )
        for target, prefix, extension in (
            (S100_TARGET, "", ".sd"),
            (CHROMA_TARGET, "pat/", ".pat"),
        ):
            with self.subTest(platform=target.platform):
                contribution = compile_persistence_id_contribution(
                    target,
                    self.schedule,
                    self.id_plan,
                    self.persistence_plan,
                    self.uid_patterns,
                )

                self.assertEqual(
                    contribution.resource_requires,
                    tuple(
                        ResourceRequirement(
                            f"pattern:{name}",
                            f"{prefix}{name}{extension}",
                            f"v13.pattern/1:{target.platform}:{name}",
                            f"UID {role} pattern",
                        )
                        for role, name in zip(
                            ("erase", "program", "read"), pattern_names
                        )
                    ),
                )
                self.assertEqual(
                    contribution.requires,
                    (
                        SymbolRequirement(
                            RenderSymbolRef("RESULT", "TS_125C_EXPORT"),
                            "INT",
                            16,
                            "SITE",
                        ),
                        SymbolRequirement(
                            RenderSymbolRef("HELPER", "commit_page_image"),
                            "CALLABLE",
                            None,
                            "TARGET",
                        ),
                        SymbolRequirement(
                            RenderSymbolRef("HELPER", "program_otp_page"),
                            "CALLABLE",
                            None,
                            "TARGET",
                        ),
                        SymbolRequirement(
                            RenderSymbolRef("HELPER", "uid_failed_site_reerase"),
                            "CALLABLE",
                            None,
                            "TARGET",
                        ),
                        SymbolRequirement(
                            RenderSymbolRef(
                                "TEST_BODY",
                                f"{target.platform}:{definition_identity}",
                            ),
                            "SECTION",
                            None,
                            "TARGET",
                        ),
                    ),
                )
                self.assertEqual(contribution.sections, ())
                self.assertEqual(contribution.resources, ())

    def test_opaque_canonical_identities_are_forwarded_without_reconstruction(
        self,
    ) -> None:
        original_definition = next(
            definition for definition in self.schedule.definitions
            if definition.item == "Pgm_CP2ID_Read"
        )
        original_entry = next(
            entry for entry in self.schedule.entries
            if entry.definition_id == original_definition.identity
        )
        opaque_definition = replace(
            original_definition,
            identity="opaque-definition-owned-by-schedule",
        )
        opaque_entry = replace(
            original_entry,
            identity="opaque-entry-owned-by-schedule",
            definition_id=opaque_definition.identity,
        )
        schedule = replace(
            self.schedule,
            definitions=tuple(
                opaque_definition if item == original_definition else item
                for item in self.schedule.definitions
            ),
            entries=tuple(
                opaque_entry if item == original_entry else item
                for item in self.schedule.entries
            ),
        )

        contribution = compile_persistence_id_contribution(
            S100_TARGET,
            schedule,
            self.id_plan,
            self.persistence_plan,
            self.uid_patterns,
        )

        self.assertEqual(
            contribution.definitions[0].identity,
            opaque_definition.identity,
        )
        self.assertEqual(
            contribution.schedule_entries[0].identity,
            opaque_entry.identity,
        )
        self.assertEqual(
            contribution.schedule_entries[0].definition_identity,
            opaque_definition.identity,
        )

    def test_rejects_rows_outside_the_first_standard_cp_id_family(self) -> None:
        cases = (
            (
                S100_TARGET,
                self.schedule,
                replace(self.id_plan, role="PRODUCE_GATE"),
                self.persistence_plan,
                self.uid_patterns,
                "PIC.PLAN.UNSUPPORTED",
            ),
            (
                TargetKey("s100", "CP1", "lab", "V_PCD009_CP1"),
                self.schedule,
                self.id_plan,
                self.persistence_plan,
                self.uid_patterns,
                "PIC.TARGET.CP_MISMATCH",
            ),
            (
                S100_TARGET,
                self.schedule,
                self.id_plan,
                PersistenceRowPlan(
                    "CP2",
                    168,
                    (PersistenceOperation("BUILDUID", 168, ("uid",), ("uid",)),),
                ),
                self.uid_patterns,
                "PIC.RECIPE.UNSUPPORTED",
            ),
            (
                S100_TARGET,
                self.schedule,
                self.id_plan,
                self.persistence_plan,
                (PagePatternPlan("trim1", "e", "p", "r"),),
                "PIC.PAGE_PATTERN.CLOSURE",
            ),
            (
                TargetKey("other", "CP2", "lab", "V_PCD009_CP2"),
                self.schedule,
                self.id_plan,
                self.persistence_plan,
                self.uid_patterns,
                "PIC.TARGET.PLATFORM",
            ),
        )
        for target, schedule, id_plan, row_plan, patterns, code in cases:
            with self.subTest(code=code), self.assertRaisesRegex(
                PersistenceContributionError,
                code,
            ):
                compile_persistence_id_contribution(
                    target,
                    schedule,
                    id_plan,
                    row_plan,
                    patterns,
                )

    def test_assembler_requires_providers_and_only_materializes_provider_bytes(
        self,
    ) -> None:
        contribution = compile_persistence_id_contribution(
            S100_TARGET,
            self.schedule,
            self.id_plan,
            self.persistence_plan,
            self.uid_patterns,
        )
        with self.assertRaisesRegex(RenderPlanError, "RP.SYMBOL.MISSING"):
            ProgramAssembler().assemble(S100_TARGET, (contribution,))

        support = ProgramContribution(
            identity="support:cp2-id:s100",
            target=S100_TARGET,
            provides=tuple(
                SymbolProvision(
                    requirement.ref,
                    requirement.ref.semantic_key,
                    requirement.value_type,
                    requirement.bit_width,
                    requirement.scope,
                )
                for requirement in contribution.requires
            ),
            resources=tuple(
                ResourceRequest(
                    requirement.logical_identity,
                    requirement.relative_path,
                    f"provider bytes for {requirement.logical_identity}",
                    requirement.spec_identity,
                    f"seed:{requirement.logical_identity}:ABC",
                    requirement.purpose,
                )
                for requirement in contribution.resource_requires
            ),
        )

        render_plan = ProgramAssembler().assemble(
            S100_TARGET,
            (contribution, support),
        )

        self.assertEqual(
            tuple(artifact.relative_path for artifact in render_plan.artifacts),
            tuple(sorted(
                requirement.relative_path
                for requirement in contribution.resource_requires
            )),
        )
        self.assertTrue(all(
            artifact.content.startswith(b"provider bytes")
            for artifact in render_plan.artifacts
        ))

    def test_contribution_contracts_are_immutable(self) -> None:
        contribution = compile_persistence_id_contribution(
            S100_TARGET,
            self.schedule,
            self.id_plan,
            self.persistence_plan,
            self.uid_patterns,
        )

        with self.assertRaises(FrozenInstanceError):
            contribution.definitions[0].typed_kind = "OTHER"
        with self.assertRaises(FrozenInstanceError):
            contribution.requires[0].bit_width = 8
        with self.assertRaises(FrozenInstanceError):
            contribution.resource_requires[0].relative_path = "other.sd"


if __name__ == "__main__":
    unittest.main()
