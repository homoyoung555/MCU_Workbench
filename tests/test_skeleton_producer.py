"""Typed Program Skeleton seam tests."""

from __future__ import annotations

import unittest

from program_gen.render_plan import (
    LifecycleAction,
    ProgramAssembler,
    ProgramContribution,
    RenderSymbolRef,
    ResourceRequest,
    ScheduleEntryContribution,
    SectionFragment,
    SymbolProvision,
    SymbolRequirement,
    TargetKey,
    TestDefinitionContribution,
)
from program_gen.compiler import ProductCompiler
from program_gen.standard_trim.assembly import compile_standard_trim_assembly_slice
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER
from program_gen.skeleton import (
    LifecycleHook,
    LifecyclePlan,
    SkeletonInput,
    SkeletonPlatformProfile,
    SkeletonProducer,
    SkeletonRender,
)


TARGET = TargetKey("chroma", "CP1", "lab", "V_TEST_CP1")
PROFILE = SkeletonPlatformProfile(
    platform="chroma",
    program_extension=".pln",
    section_order=("HEADER", "GLOBALS", "STARTUP", "TESTS", "FLOW"),
    required_structures=(
        "START_UP",
        "TEST_START",
        "TEST_PROGRAM",
        "TEST_END",
        "RELEASE",
    ),
)


class _Syntax:
    platform = "chroma"

    def render(self, plan: SkeletonInput) -> SkeletonRender:
        path = f"{plan.target.program_name}.pln"
        return SkeletonRender(
            sections=(
                SectionFragment(path, "HEADER", "skeleton:header", b"HEADER\n"),
                SectionFragment(path, "GLOBALS", "skeleton:globals", b"GLOBALS\n"),
                SectionFragment(path, "STARTUP", "skeleton:start", b"STARTUP\n"),
                SectionFragment(path, "FLOW", "skeleton:flow", b"FLOW\n"),
            ),
            provides=plan.required_provisions,
        )


class SkeletonProducerTests(unittest.TestCase):
    def test_lifecycle_actions_are_ordered_and_have_one_owner(self):
        lifecycle = LifecyclePlan.for_profile(PROFILE, (
            LifecycleAction("START_UP", "second", "SECOND\n", 20),
            LifecycleAction("START_UP", "first", "FIRST\n", 10),
        ))
        self.assertEqual(
            tuple(action.identity for action in lifecycle.actions_for("START_UP")),
            ("first", "second"),
        )
        with self.assertRaisesRegex(ValueError, "SK.LIFECYCLE.ACTION_CONFLICT"):
            LifecyclePlan.for_profile(PROFILE, (
                LifecycleAction("START_UP", "same", "FIRST\n"),
                LifecycleAction("START_UP", "same", "SECOND\n"),
            ))
        with self.assertRaisesRegex(ValueError, "SK.LIFECYCLE.ACTION_HOOK_UNKNOWN"):
            LifecyclePlan.for_profile(PROFILE, (
                LifecycleAction("UNKNOWN", "unknown", "ACTION\n"),
            ))

    def test_required_structures_are_declared_by_platform_profile(self):
        s100_profile = SkeletonPlatformProfile(
            platform="s100",
            program_extension=".prg",
            section_order=("HEADER", "GLOBALS", "STARTUP", "TESTS", "FLOW"),
            required_structures=("START_UP", "TEST_START", "TEST_PROGRAM"),
        )
        lifecycle = LifecyclePlan.empty_for(s100_profile)
        self.assertEqual(
            tuple(hook.identity for hook in lifecycle.hooks),
            ("START_UP", "TEST_START", "TEST_PROGRAM"),
        )
        with self.assertRaisesRegex(ValueError, "SK.LIFECYCLE.UNKNOWN"):
            SkeletonInput.for_test_bodies(
                target=TargetKey("s100", "CP1", "lab", "V_TEST_CP1"),
                profile=s100_profile,
                lifecycle=LifecyclePlan((
                    *lifecycle.hooks,
                    LifecycleHook("TEST_END"),
                )),
                schedule_entries=(),
                bodies=(),
            )

    def test_typed_skeleton_closes_body_provider_and_orders_program(self):
        body_ref = RenderSymbolRef("TEST_BODY", "chroma:test:hsi_8m:bisection")
        business = ProgramContribution(
            identity="standard-trim:test",
            target=TARGET,
            definitions=(TestDefinitionContribution(
                "test:hsi_8m", "STANDARD_TRIM", "standard-trim:test"
            ),),
            schedule_entries=(ScheduleEntryContribution(
                "test:hsi_8m:bisection", "test:hsi_8m", 0, True
            ),),
            requires=(SymbolRequirement(
                body_ref, "SECTION", None, "TARGET"
            ),),
        )
        body = SectionFragment(
            f"{TARGET.program_name}.pln",
            "TESTS",
            "standard-trim:test:body",
            b"Hsi_8M_Trim() {}\n",
        )
        plan = SkeletonInput.for_test_bodies(
            target=TARGET,
            profile=PROFILE,
            lifecycle=LifecyclePlan.empty_for(PROFILE),
            schedule_entries=business.schedule_entries,
            bodies=((body_ref, body),),
        )
        skeleton = SkeletonProducer(_Syntax()).produce(plan)

        render_plan = ProgramAssembler(
            section_order=PROFILE.section_order
        ).assemble(TARGET, (business, skeleton))

        self.assertEqual(
            render_plan.artifact("V_TEST_CP1.pln").content,
            b"HEADER\nGLOBALS\nSTARTUP\nHsi_8M_Trim() {}\nFLOW\n",
        )

    def test_missing_body_provider_blocks_before_materialization(self):
        plan = SkeletonInput.for_test_bodies(
            target=TARGET,
            profile=PROFILE,
            lifecycle=LifecyclePlan.empty_for(PROFILE),
            schedule_entries=(ScheduleEntryContribution(
                "test:hsi_8m:bisection", "test:hsi_8m", 0, True
            ),),
            bodies=(),
        )
        with self.assertRaisesRegex(ValueError, "SK.TEST_BODY.MISSING"):
            SkeletonProducer(_Syntax()).produce(plan)

    def test_platform_mismatch_blocks(self):
        wrong = SkeletonPlatformProfile(
            platform="s100",
            program_extension=".prg",
            section_order=("HEADER", "GLOBALS", "TESTS", "FLOW"),
            required_structures=("START_UP", "TEST_START", "TEST_PROGRAM"),
        )
        plan = SkeletonInput.for_test_bodies(
            target=TARGET,
            profile=wrong,
            lifecycle=LifecyclePlan.empty_for(wrong),
            schedule_entries=(),
            bodies=(),
        )
        with self.assertRaisesRegex(ValueError, "SK.TARGET.PLATFORM_MISMATCH"):
            SkeletonProducer(_Syntax()).produce(plan)

    def test_real_standard_trim_body_closes_with_canonical_provider(self):
        workbook = WorkbookReader().read(FORMAL_MASTER)
        compilation = ProductCompiler().compile(workbook).require_success()
        spec = next(
            item for item in compilation.plan.catalogs.trim_specs.values()
            if item.cp == "CP1" and item.item == "Hsi_8M"
        )
        cp_plan = compilation.for_cp("CP1")
        slice_plan = compile_standard_trim_assembly_slice(
            (spec,),
            TARGET,
            cp_plan.canonical_schedule,
            profile=PROFILE,
            lifecycle=LifecyclePlan.empty_for(PROFILE),
            resource_closure=cp_plan.resources.identities,
        )
        skeleton = SkeletonProducer(_Syntax()).produce(
            slice_plan.skeleton_input
        )
        business = slice_plan.business_contributions[0]
        support = ProgramContribution(
            identity="native-support:hsi-8m",
            target=TARGET,
            provides=(SymbolProvision(
                RenderSymbolRef("HELPER", spec.dac.helper_name),
                spec.dac.helper_name,
                "CALLABLE",
                None,
                "TARGET",
            ),),
            resources=tuple(
                ResourceRequest(
                    requirement.logical_identity,
                    requirement.relative_path,
                    b"PATTERN\n",
                    requirement.spec_identity,
                    "test:explicit-resource",
                    requirement.purpose,
                )
                for requirement in business.resource_requires
            ),
        )

        render_plan = ProgramAssembler(
            section_order=PROFILE.section_order
        ).assemble(TARGET, (business, skeleton, support))

        source = render_plan.artifact("V_TEST_CP1.pln").content.decode()
        self.assertIn("Hsi_8M_Trim()", source)
        self.assertIn("Hsi_8M_Dac_Loop()", source)


if __name__ == "__main__":
    unittest.main()
