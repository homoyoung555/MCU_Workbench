from __future__ import annotations

from tests.workspace_paths import FORMAL_MASTER as EXTERNAL_FORMAL_MASTER

from pathlib import Path
import unittest

from program_gen.compiler import ProductCompiler
from program_gen.contributions import compile_business_contributions
from program_gen.core.input_normalization import normalize_flow_table, token_key
from program_gen.core.pdr_verify import compile_pdr_verify_plan
from program_gen.render_plan import (
    ProgramAssembler,
    ProgramContribution,
    ResourceRequest,
    SymbolProvision,
    TargetKey,
)
from program_gen.workbook import WorkbookReader


ROOT = Path(__file__).resolve().parents[1]
FORMAL_MASTER = EXTERNAL_FORMAL_MASTER


class ContributionCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        workbook = WorkbookReader().read(FORMAL_MASTER)
        base = ProductCompiler().compile(workbook).require_success()
        flow = normalize_flow_table(workbook.dataframe("FLOW"))
        operations = tuple(
            operation
            for operation in base.plan.catalogs.flow_operations
            if token_key(operation.item) == "pdr_verify"
        )
        pdr_verify_plans = {
            platform: {
                operation.row: compile_pdr_verify_plan(
                    flow, operation, platform
                )
                for operation in operations
            }
            for platform in ("chroma", "s100")
        }
        cls.compilation = _CompilationWithPdrVerifyPlans(
            base, pdr_verify_plans
        )

    def test_formal_targets_compile_all_currently_closed_business_families(self):
        expected_counts = {"CP1": 35, "CP2": 4, "CP3": 5}
        for platform in ("chroma", "s100"):
            for cp, expected in expected_counts.items():
                with self.subTest(platform=platform, cp=cp):
                    target = TargetKey(platform, cp, "lab", f"V_TEST_{cp}")
                    contributions = compile_business_contributions(
                        self.compilation, target
                    )
                    self.assertEqual(len(contributions), expected)
                    self.assertEqual(
                        len({item.identity.casefold() for item in contributions}),
                        expected,
                    )
                    self.assertTrue(all(item.target == target for item in contributions))

    def test_every_schedule_projection_uses_the_canonical_global_ordinal(self):
        target = TargetKey("chroma", "CP1", "lab", "V_TEST_CP1")
        contributions = compile_business_contributions(self.compilation, target)
        schedule = self.compilation.for_cp("CP1").canonical_schedule
        canonical_ordinals = {
            entry.identity.casefold(): ordinal
            for ordinal, entry in enumerate(schedule.entries)
        }

        projected = tuple(
            entry
            for contribution in contributions
            for entry in contribution.schedule_entries
        )
        self.assertTrue(projected)
        self.assertEqual(
            tuple(entry.ordinal for entry in projected),
            tuple(canonical_ordinals[entry.identity.casefold()] for entry in projected),
        )

    def test_pdr_verify_uses_exact_canonical_identity_and_global_ordinal(self):
        for platform in ("chroma", "s100"):
            for cp in ("CP1", "CP2"):
                with self.subTest(platform=platform, cp=cp):
                    target = TargetKey(platform, cp, "lab", f"V_TEST_{cp}")
                    contributions = compile_business_contributions(
                        self.compilation, target
                    )
                    matches = tuple(
                        contribution
                        for contribution in contributions
                        if contribution.definitions
                        and contribution.definitions[0].typed_kind == "PDR_VERIFY"
                    )
                    self.assertEqual(len(matches), 1)
                    contribution = matches[0]
                    schedule = self.compilation.for_cp(cp).canonical_schedule
                    plan = next(
                        plan
                        for plan in self.compilation.plan.catalogs
                        .pdr_verify_plans[platform].values()
                        if plan.cp == cp
                    )
                    definition = next(
                        item
                        for item in schedule.definitions
                        if item.item.casefold() == plan.item.casefold()
                        and item.source_rows == (plan.excel_row,)
                    )
                    entry = next(
                        item
                        for item in schedule.entries
                        if item.definition_id == definition.identity
                    )
                    ordinal = next(
                        index
                        for index, item in enumerate(schedule.entries)
                        if item.identity == entry.identity
                    )

                    self.assertEqual(
                        contribution.definitions[0].identity,
                        definition.identity,
                    )
                    self.assertEqual(
                        contribution.schedule_entries[0].identity,
                        entry.identity,
                    )
                    self.assertEqual(
                        contribution.schedule_entries[0].ordinal,
                        ordinal,
                    )

    def test_cp2_standard_id_forwards_canonical_identity_ordinal_and_closure(self):
        definition_identity = "DEF:CP2:uid:Pgm_CP2ID_Read:(168,)"
        pattern_names = (
            "fbist_page_erase_uid",
            "fbist_page_prog_cp2_id",
            "fbist_page_read_cp2_id",
        )
        for platform, prefix, extension in (
            ("chroma", "pat/", ".pat"),
            ("s100", "", ".sd"),
        ):
            with self.subTest(platform=platform):
                target = TargetKey(platform, "CP2", "lab", "V_TEST_CP2")
                contribution = next(
                    contribution
                    for contribution in compile_business_contributions(
                        self.compilation, target
                    )
                    if contribution.definitions
                    and contribution.definitions[0].identity == definition_identity
                )
                schedule = self.compilation.for_cp("CP2").canonical_schedule
                entry = next(
                    entry
                    for entry in schedule.entries
                    if entry.definition_id == definition_identity
                )
                ordinal = next(
                    ordinal
                    for ordinal, item in enumerate(schedule.entries)
                    if item.identity == entry.identity
                )

                self.assertEqual(
                    contribution.identity,
                    f"persistence-id:{target.identity}:{definition_identity}",
                )
                self.assertEqual(
                    contribution.schedule_entries[0].identity,
                    entry.identity,
                )
                self.assertEqual(
                    contribution.schedule_entries[0].ordinal,
                    ordinal,
                )
                self.assertEqual(
                    tuple(
                        requirement.relative_path
                        for requirement in contribution.resource_requires
                    ),
                    tuple(f"{prefix}{name}{extension}" for name in pattern_names),
                )
                ProgramAssembler().assemble(
                    target,
                    (contribution, _support_for(contribution)),
                )

    def test_rejects_unknown_platform_and_cp_before_partial_projection(self):
        with self.assertRaisesRegex(ValueError, "BC.TARGET.PLATFORM"):
            compile_business_contributions(
                self.compilation,
                TargetKey("other", "CP1", "lab", "V_TEST_CP1"),
            )
        with self.assertRaisesRegex(ValueError, "BC.TARGET.CP"):
            compile_business_contributions(
                self.compilation,
                TargetKey("chroma", "CP9", "lab", "V_TEST_CP9"),
            )

    def test_pdr_verify_contracts_close_for_cp1_cp2_on_both_platforms(self):
        for platform in ("chroma", "s100"):
            for cp in ("CP1", "CP2"):
                with self.subTest(platform=platform, cp=cp):
                    target = TargetKey(platform, cp, "lab", f"V_TEST_{cp}")
                    contribution = next(
                        item
                        for item in compile_business_contributions(
                            self.compilation, target
                        )
                        if item.definitions
                        and item.definitions[0].typed_kind == "PDR_VERIFY"
                    )

                    render_plan = ProgramAssembler().assemble(
                        target,
                        (contribution, _support_for(contribution)),
                    )

                    self.assertEqual(
                        tuple(
                            artifact.relative_path
                            for artifact in render_plan.artifacts
                        ),
                        tuple(sorted(
                            requirement.relative_path
                            for requirement in contribution.resource_requires
                        )),
                    )

    def test_ordinary_shmoo_reuses_canonical_identity_and_closes_contracts(self):
        self.assertEqual(self.compilation.plan.catalogs.commit_shmoo_plans, {})
        for platform in ("chroma", "s100"):
            for cp in ("CP1", "CP2"):
                with self.subTest(platform=platform, cp=cp):
                    target = TargetKey(platform, cp, "lab", f"V_TEST_{cp}")
                    matches = tuple(
                        contribution
                        for contribution in compile_business_contributions(
                            self.compilation, target
                        )
                        if contribution.definitions
                        and contribution.definitions[0].typed_kind == "SHMOO"
                    )
                    self.assertEqual(len(matches), 1)
                    contribution = matches[0]
                    plan = next(
                        plan
                        for plan in self.compilation.plan.catalogs.shmoo_plans.values()
                        if plan.cp == cp
                    )
                    schedule = self.compilation.for_cp(cp).canonical_schedule
                    source_rows = tuple(dict.fromkeys(
                        point.flow_row_index + 2 for point in plan.points
                    ))
                    definition = next(
                        item
                        for item in schedule.definitions
                        if item.item.casefold() == plan.item.casefold()
                        and item.source_rows == source_rows
                    )
                    entry = next(
                        item
                        for item in schedule.entries
                        if item.definition_id == definition.identity
                    )
                    ordinal = next(
                        index
                        for index, item in enumerate(schedule.entries)
                        if item.identity == entry.identity
                    )

                    self.assertEqual(
                        contribution.definitions[0].identity,
                        definition.identity,
                    )
                    self.assertEqual(
                        contribution.schedule_entries[0].identity,
                        entry.identity,
                    )
                    self.assertEqual(
                        contribution.schedule_entries[0].ordinal,
                        ordinal,
                    )
                    render_plan = ProgramAssembler().assemble(
                        target,
                        (contribution, _support_for(contribution)),
                    )
                    self.assertEqual(
                        tuple(
                            artifact.relative_path
                            for artifact in render_plan.artifacts
                        ),
                        tuple(sorted(
                            requirement.relative_path
                            for requirement in contribution.resource_requires
                        )),
                    )


class _CatalogsWithPdrVerifyPlans:
    def __init__(self, base, plans):
        self._base = base
        self.pdr_verify_plans = plans

    def __getattr__(self, name):
        return getattr(self._base, name)


class _PlanWithCatalogs:
    def __init__(self, base, catalogs):
        self._base = base
        self.catalogs = catalogs

    def __getattr__(self, name):
        return getattr(self._base, name)


class _CompilationWithPdrVerifyPlans:
    def __init__(self, base, plans):
        self._base = base
        catalogs = _CatalogsWithPdrVerifyPlans(base.plan.catalogs, plans)
        self.plan = _PlanWithCatalogs(base.plan, catalogs)

    def require_success(self):
        self._base.require_success()
        return self

    def for_cp(self, cp):
        return self._base.for_cp(cp)


def _support_for(contribution):
    return ProgramContribution(
        identity=f"support:{contribution.identity}",
        target=contribution.target,
        provides=tuple(
            SymbolProvision(
                requirement.ref,
                f"provider_{index}",
                requirement.value_type,
                requirement.bit_width,
                requirement.scope,
            )
            for index, requirement in enumerate(contribution.requires)
        ),
        resources=tuple(
            ResourceRequest(
                requirement.logical_identity,
                requirement.relative_path,
                f"bytes for {requirement.logical_identity}",
                requirement.spec_identity,
                f"catalog-test:{index}",
                requirement.purpose,
            )
            for index, requirement in enumerate(
                contribution.resource_requires
            )
        ),
    )


if __name__ == "__main__":
    unittest.main()
