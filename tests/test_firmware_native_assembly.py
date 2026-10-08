import unittest
import tempfile

from program_gen.compiler import ProductCompiler
from program_gen.core.firmware_render import FirmwareBodyRender
from program_gen.firmware_test_assembly import (
    compile_code_download_assembly,
    compile_firmware_function_test_assembly,
    compile_firmware_run_test_assembly,
)
from program_gen.platform_program.facts import compile_platform_program_facts
from program_gen.platform_program import (
    PlatformProgramBuilder,
    ProgramAssemblyInput,
    WorkspacePatternProducer,
)
from program_gen.registered_typed_kinds import NATIVE_TYPED_KIND_REGISTRY
from program_gen.render_plan import ResourceRequest, ResourceRequirement, TargetKey
from program_gen.typed_kind_registry import TypedKindContext
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER, WORKSPACE_ROOT


_COMPILERS = {
    "CODE_DOWNLOAD": compile_code_download_assembly,
    "FIRMWARE_FUNCTION_TEST": compile_firmware_function_test_assembly,
    "FIRMWARE_RUN_TEST": compile_firmware_run_test_assembly,
}


class _RecordingRenderer:
    def __init__(self, platform):
        self.platform = platform
        self.calls = []

    def __call__(self, plan, render_name, hardware_bin, platform_facts):
        self.calls.append((plan, render_name, hardware_bin, platform_facts))
        identity = f"firmware-render:{self.platform}:{plan.cp}:{plan.item}"
        return FirmwareBodyRender(
            f"{render_name}:{hardware_bin}:{plan.item}\n",
            resources=(ResourceRequest(
                identity,
                f"generated/{plan.cp}_{plan.item}.txt",
                plan.item,
                purpose="recording firmware body resource",
            ),),
            resource_requires=(ResourceRequirement(
                f"firmware-support:{self.platform}",
                f"support/{self.platform}.txt",
                f"firmware-support/1:{self.platform}",
                "recording firmware body dependency",
            ),),
        )


class FirmwareNativeAssemblyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()
        cls.plans = tuple(
            cls.compilation.plan.catalogs.firmware_test_plans.values()
        )

    def test_formal_fourteen_plans_assemble_one_canonical_body_on_both_platforms(self):
        self.assertEqual(len(self.plans), 14)
        for platform in ("chroma", "s100"):
            renderer = _RecordingRenderer(platform)
            contributions = []
            bodies = []
            for cp in ("CP1", "CP2", "CP3"):
                target = TargetKey(platform, cp, "lab", f"FIRMWARE_{platform}_{cp}")
                context = TypedKindContext(
                    self.compilation,
                    target,
                    f"{platform}-facts",
                    None,
                )
                for typed_kind, compiler in _COMPILERS.items():
                    plans = tuple(
                        plan for plan in self.plans
                        if plan.cp == cp and plan.typed_kind == typed_kind
                    )
                    assembly = compiler(plans, context, renderer)
                    self.assertEqual(assembly.typed_kind, typed_kind)
                    contributions.extend(assembly.contributions)
                    bodies.extend(assembly.bodies)

            self.assertEqual(len(contributions), 14)
            self.assertEqual(len(bodies), 14)
            self.assertEqual(len(renderer.calls), 14)
            self.assertEqual(
                len({item.definitions[0].identity for item in contributions}),
                14,
            )
            self.assertEqual(
                len({item.schedule_entries[0].identity for item in contributions}),
                14,
            )
            self.assertEqual(len({body.ref.identity for body in bodies}), 14)

            by_ref = {body.ref: body for body in bodies}
            extension = ".pln" if platform == "chroma" else ".prg"
            for contribution in contributions:
                self.assertEqual(len(contribution.definitions), 1)
                self.assertEqual(len(contribution.schedule_entries), 1)
                body_requirement = next(
                    requirement for requirement in contribution.requires
                    if requirement.ref.namespace == "TEST_BODY"
                )
                body = by_ref[body_requirement.ref]
                entry = contribution.schedule_entries[0]
                self.assertEqual(body.fragment.section, "TESTS")
                self.assertEqual(body.fragment.order, entry.ordinal)
                self.assertEqual(
                    body.fragment.artifact_path,
                    f"{contribution.target.program_name}{extension}",
                )
                self.assertTrue(body.fragment.content.endswith(b"\r\n"))
                self.assertEqual(len(contribution.resources), 1)
                self.assertIn(
                    f"firmware-support:{platform}",
                    {
                        requirement.logical_identity
                        for requirement in contribution.resource_requires
                    },
                )

    def test_renderer_receives_canonical_identity_and_its_resources_are_merged(self):
        plan = next(
            plan for plan in self.plans
            if plan.cp == "CP3" and plan.typed_kind == "CODE_DOWNLOAD"
        )
        schedule = self.compilation.for_cp("CP3").canonical_schedule
        definition = next(
            item for item in schedule.definitions
            if item.source_rows == plan.excel_rows
        )
        entry = next(
            item for item in schedule.entries
            if item.definition_id == definition.identity
        )
        target = TargetKey("chroma", "CP3", "lab", "FIRMWARE_CHROMA_CP3")
        facts = object()
        renderer = _RecordingRenderer("chroma")

        assembly = compile_code_download_assembly(
            (plan,),
            TypedKindContext(self.compilation, target, facts, None),
            renderer,
        )

        self.assertEqual(
            renderer.calls,
            [(plan, definition.render_name, entry.bin_binding.hardware_bin, facts)],
        )
        contribution = assembly.contributions[0]
        self.assertEqual(len(contribution.resources), 1)
        self.assertEqual(
            tuple(item.logical_identity for item in contribution.resource_requires),
            (
                plan.phases[0].pattern.logical_identity,
                "firmware-support:chroma",
            ),
        )

    def test_three_firmware_kinds_are_registered_and_use_production_renderers(self):
        registered = set(NATIVE_TYPED_KIND_REGISTRY.registered_kinds)
        self.assertTrue(set(_COMPILERS) <= registered)

        for platform in ("chroma", "s100"):
            for cp in ("CP1", "CP2", "CP3"):
                target = TargetKey(platform, cp, "lab", f"FIRMWARE_{platform}_{cp}")
                context = TypedKindContext(
                    self.compilation,
                    target,
                    compile_platform_program_facts(self.workbook, target),
                    None,
                )
                for typed_kind in _COMPILERS:
                    plans = tuple(
                        plan for plan in self.plans
                        if plan.cp == cp and plan.typed_kind == typed_kind
                    )
                    assembly = NATIVE_TYPED_KIND_REGISTRY.compile(
                        typed_kind, plans, context
                    )
                    self.assertEqual(assembly.typed_kind, typed_kind)
                    self.assertEqual(len(assembly.contributions), len(plans))
                    self.assertEqual(len(assembly.bodies), len(plans))

    def test_registered_firmware_slice_closes_in_platform_program_builder(self):
        for platform in ("chroma", "s100"):
            producer = WorkspacePatternProducer(WORKSPACE_ROOT / "input" / platform)
            for cp in ("CP1", "CP2", "CP3"):
                target = TargetKey(platform, cp, "lab", f"FIRMWARE_{platform}_{cp}")
                facts = compile_platform_program_facts(self.workbook, target)
                context = TypedKindContext(
                    self.compilation, target, facts, producer
                )
                assemblies = tuple(
                    NATIVE_TYPED_KIND_REGISTRY.compile(
                        typed_kind,
                        tuple(
                            plan for plan in self.plans
                            if plan.cp == cp and plan.typed_kind == typed_kind
                        ),
                        context,
                    )
                    for typed_kind in _COMPILERS
                )
                contributions = tuple(
                    contribution
                    for assembly in assemblies
                    for contribution in assembly.contributions
                )
                bodies = tuple(
                    body for assembly in assemblies for body in assembly.bodies
                )
                if not contributions:
                    continue

                rendered = PlatformProgramBuilder(producer).build(
                    ProgramAssemblyInput(
                        target,
                        facts,
                        self.compilation.for_cp(cp).canonical_schedule,
                        contributions,
                        bodies,
                    )
                )

                extension = ".pln" if platform == "chroma" else ".prg"
                self.assertTrue(rendered.artifact(target.program_name + extension).content)
                if cp == "CP1":
                    download_path = (
                        "pat/FLASH_RWW_V01_02.pat"
                        if platform == "chroma"
                        else "FLASH_RWW_V01_02.sd"
                    )
                    self.assertIn(b"STUB", rendered.artifact(download_path).content)
                if cp == "CP3":
                    reset_path = (
                        "pat/firmware_dut_reset.pat"
                        if platform == "chroma"
                        else "dut_reset.sd"
                    )
                    reset = rendered.artifact(reset_path).content
                    self.assertIn(b"RPT 25000", reset)

    def test_missing_s100_download_pattern_gets_an_explicit_compile_only_stub(self):
        target = TargetKey("s100", "CP3", "lab", "FIRMWARE_STUB_S100")
        facts = compile_platform_program_facts(self.workbook, target)
        plan = next(
            plan for plan in self.plans
            if plan.cp == "CP3" and plan.typed_kind == "CODE_DOWNLOAD"
        )
        requirement = compile_code_download_assembly(
            (plan,),
            TypedKindContext(self.compilation, target, facts, None),
        ).contributions[0].resource_requires[0]

        with tempfile.TemporaryDirectory() as directory:
            producer = WorkspacePatternProducer(directory).for_target(facts)
            self.assertEqual(producer.timing_sets((requirement,)), ())
            resource = producer.produce(requirement)

        self.assertIn(b"STUB: no firmware download vector", resource.content)
        self.assertIn(":STUB:", resource.source_identity)
        self.assertEqual(resource.relative_path, requirement.relative_path)


if __name__ == "__main__":
    unittest.main()
