from __future__ import annotations

from tests.workspace_paths import FORMAL_MASTER as EXTERNAL_FORMAL_MASTER

import ast
from dataclasses import replace
from pathlib import Path
import unittest

from program_gen.compiler import ProductCompiler
from program_gen.core.input_normalization import normalize_flow_table, token_key
from program_gen.core.pdr_verify import compile_pdr_verify_plan
from program_gen.core.pdr_verify_contribution import (
    PdrVerifyContributionError,
    compile_pdr_verify_contribution,
)
from program_gen.render_plan import (
    ProgramAssembler,
    ProgramContribution,
    RenderSymbolRef,
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


class PdrVerifyContributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(workbook).require_success()
        cls.flow = normalize_flow_table(workbook.dataframe("FLOW"))
        cls.operations = tuple(
            operation
            for operation in cls.compilation.plan.catalogs.flow_operations
            if token_key(operation.item) == "pdr_verify"
        )

    def test_formal_cp1_cp2_project_exact_canonical_and_plan_identities(self):
        for operation in self.operations:
            schedule = self.compilation.for_cp(operation.cp).canonical_schedule
            for platform in ("chroma", "s100"):
                with self.subTest(cp=operation.cp, platform=platform):
                    plan = compile_pdr_verify_plan(self.flow, operation, platform)
                    target = TargetKey(
                        platform,
                        operation.cp,
                        "formal",
                        f"V_TEST_{operation.cp}",
                    )

                    contribution = compile_pdr_verify_contribution(
                        plan, target, schedule
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
                    self.assertEqual(contribution.sections, ())
                    self.assertEqual(contribution.resources, ())
                    self.assertEqual(contribution.provides, ())
                    self.assertEqual(
                        contribution.definitions,
                        (TestDefinitionContribution(
                            definition.identity,
                            "PDR_VERIFY",
                            contribution.identity,
                        ),),
                    )
                    self.assertEqual(
                        contribution.schedule_entries,
                        (ScheduleEntryContribution(
                            entry.identity,
                            definition.identity,
                            ordinal,
                            entry.enabled,
                        ),),
                    )
                    expected_result_type = (
                        "PASS_FAIL" if platform == "chroma" else "FLOAT"
                    )
                    self.assertEqual(
                        contribution.requires,
                        (
                            SymbolRequirement(
                                RenderSymbolRef(
                                    "RESULT",
                                    f"{platform}:pattern:read_status_mode",
                                ),
                                expected_result_type,
                                None,
                                "SITE",
                            ),
                            SymbolRequirement(
                                RenderSymbolRef(
                                    "TEST_BODY",
                                    f"{platform}:{entry.identity}",
                                ),
                                "SECTION",
                                None,
                                "TARGET",
                            ),
                        ),
                    )
                    prefix, extension = (
                        ("pat/", ".pat")
                        if platform == "chroma"
                        else ("", ".sd")
                    )
                    self.assertEqual(
                        contribution.resource_requires,
                        tuple(
                            ResourceRequirement(
                                resource.logical_identity,
                                f"{prefix}{resource.name}{extension}",
                                f"v13.pattern/1:{platform}:{resource.name}",
                                f"PDR_VERIFY {resource.role} pattern",
                            )
                            for resource in plan.pattern_resources
                        ),
                    )

    def test_assembler_closes_all_body_helper_result_and_resource_requirements(self):
        plan, target, schedule = self._formal_case("CP1", "s100")
        contribution = compile_pdr_verify_contribution(plan, target, schedule)
        support = _support_for(contribution)

        render_plan = ProgramAssembler().assemble(
            target, (contribution, support)
        )

        self.assertEqual(
            tuple(artifact.relative_path for artifact in render_plan.artifacts),
            tuple(sorted(
                requirement.relative_path
                for requirement in contribution.resource_requires
            )),
        )

    def test_consumes_resource_and_result_identities_from_the_plan(self):
        plan, target, schedule = self._formal_case("CP1", "s100")
        status_index = next(
            index
            for index, resource in enumerate(plan.pattern_resources)
            if resource.role == "STATUS_READ"
        )
        custom_pattern = replace(
            plan.pattern_resources[status_index],
            logical_identity="canonical-pattern:read-status:v3",
        )
        custom_patterns = list(plan.pattern_resources)
        custom_patterns[status_index] = custom_pattern
        custom_status = tuple(
            replace(
                check,
                status_pattern_identity=custom_pattern.logical_identity,
            )
            for check in plan.status_checks
        )
        custom_plan = replace(
            plan,
            pattern_resources=tuple(custom_patterns),
            status_checks=custom_status,
        )

        contribution = compile_pdr_verify_contribution(
            custom_plan, target, schedule
        )

        self.assertEqual(
            contribution.resource_requires[status_index].logical_identity,
            custom_pattern.logical_identity,
        )
        self.assertEqual(
            contribution.requires[0].ref,
            RenderSymbolRef(
                "RESULT", "s100:canonical-pattern:read-status:v3"
            ),
        )

    def test_rejects_plan_target_schedule_and_result_identity_mismatches(self):
        plan, target, schedule = self._formal_case("CP1", "chroma")
        cases = (
            (
                plan,
                TargetKey("s100", "CP1", "formal", "V_TEST_CP1"),
                schedule,
                "PVC.TARGET.PROFILE_MISMATCH",
            ),
            (
                plan,
                TargetKey("chroma", "CP2", "formal", "V_TEST_CP2"),
                schedule,
                "PVC.TARGET.CP_MISMATCH",
            ),
            (
                plan,
                target,
                replace(schedule, cp="CP2"),
                "PVC.SCHEDULE.CP_MISMATCH",
            ),
            (
                replace(plan, typed_kind="STANDARD_VERIFY"),
                target,
                schedule,
                "PVC.PLAN.UNSUPPORTED",
            ),
            (
                replace(
                    plan,
                    status_checks=(
                        plan.status_checks[0],
                        replace(
                            plan.status_checks[1],
                            status_pattern_identity="pattern:other_status",
                        ),
                    ),
                ),
                target,
                schedule,
                "PVC.RESULT.IDENTITY_CONFLICT",
            ),
            (
                replace(
                    plan,
                    pattern_resources=(
                        replace(plan.pattern_resources[0], logical_identity=""),
                        *plan.pattern_resources[1:],
                    ),
                ),
                target,
                schedule,
                "PVC.RESOURCE.IDENTITY_MISSING",
            ),
        )
        for candidate, candidate_target, candidate_schedule, code in cases:
            with self.subTest(code=code), self.assertRaisesRegex(
                PdrVerifyContributionError, code
            ):
                compile_pdr_verify_contribution(
                    candidate, candidate_target, candidate_schedule
                )

        with self.assertRaisesRegex(
            PdrVerifyContributionError, "PVC.TARGET.PLATFORM"
        ):
            compile_pdr_verify_contribution(
                plan,
                TargetKey("other", "CP1", "formal", "V_TEST_CP1"),
                schedule,
            )

    def test_core_has_no_global_workbook_seed_bytes_or_tester_rendering(self):
        source_path = (
            ROOT / "program_gen" / "core" / "pdr_verify_contribution.py"
        )
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

        self.assertFalse(
            {"program_gen.state", "program_gen.workbook", "openpyxl"} & imports
        )
        self.assertFalse(any(
            isinstance(node, ast.Name) and node.id == "G"
            for node in ast.walk(tree)
        ))
        for forbidden in (
            "ResourceRequest",
            "source_identity",
            "seed:",
            "RUN_PATTERN(",
            "JUDGE_PAT(",
            "CALL_MACRO",
            ".write(",
            'f"DEF:',
            'f"SCHEDULE:',
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def _formal_case(self, cp, platform):
        operation = next(item for item in self.operations if item.cp == cp)
        plan = compile_pdr_verify_plan(self.flow, operation, platform)
        target = TargetKey(platform, cp, "formal", f"V_TEST_{cp}")
        return plan, target, self.compilation.for_cp(cp).canonical_schedule


def _support_for(contribution) -> ProgramContribution:
    return ProgramContribution(
        identity=f"support:{contribution.target.identity}",
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
                f"source:{index}",
                requirement.purpose,
            )
            for index, requirement in enumerate(
                contribution.resource_requires
            )
        ),
    )


if __name__ == "__main__":
    unittest.main()
