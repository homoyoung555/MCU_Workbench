"""Render-layer seam: typed plan → SectionFragment → assembled artifact.

These tests prove the missing native-renderer producer end to end: a typed
``PdrVerifyPlan`` becomes a real tester-body SectionFragment, which the
ProgramAssembler closes (with the same symbol/resource providers the core
contribution already declares) into a byte-exact artifact matching the golden
function block.
"""

from __future__ import annotations

from tests.workspace_paths import (
    CHROMA_GOLDEN_ROOT,
    CHROMA_SEED_ROOT,
    FORMAL_MASTER as EXTERNAL_FORMAL_MASTER,
    S100_GOLDEN_ROOT,
)

from dataclasses import replace
from pathlib import Path
import unittest

from program_gen.compiler import ProductCompiler
from program_gen.core.input_normalization import normalize_flow_table, token_key
from program_gen.core.pdr_verify import compile_pdr_verify_plan
from program_gen.core.pdr_verify_contribution import compile_pdr_verify_contribution
from program_gen.platform_render import (
    CHROMA_SECTION_ORDER,
    PdrVerifyRenderContext,
    PlatformRenderPlanner,
    chroma_fixed_skeleton,
    render_pdr_verify_section,
    resolve_pattern_resource,
    resolve_power_rails,
)
from program_gen.render_plan import (
    ArtifactMaterializer,
    ProgramAssembler,
    ProgramContribution,
    RenderSymbolRef,
    ResourceRequest,
    SectionFragment,
    SymbolProvision,
    TargetKey,
)
from program_gen.workbook import WorkbookReader


ROOT = Path(__file__).resolve().parents[1]
FORMAL_MASTER = EXTERNAL_FORMAL_MASTER
CHROMA_GOLDEN = (
    CHROMA_GOLDEN_ROOT / "LAB" / "CHROMA"
    / "V_PCD2509V1_PY32F420A_C8_30C_V00_50_1SLAB_CP1"
    / "V_PCD2509V1_PY32F420A_C8_30C_V00_50_1SLAB_CP1.pln"
)
S100_GOLDEN = (
    S100_GOLDEN_ROOT / "LAB" / "S100"
    / "V_PCD2509V1_PY32F420A_C8_30C_V00_50_1SLAB_CP1"
    / "V_PCD2509V1_PY32F420A_C8_30C_V00_50_1SLAB_CP1.prg"
)


def _read_gbk(path: Path) -> list[str]:
    return path.read_bytes().decode("gbk", errors="replace").splitlines()


def _golden_chroma_body() -> list[str]:
    lines = _read_gbk(CHROMA_GOLDEN)
    start = next(i for i, l in enumerate(lines) if l.strip() == "Pdr_Verify()")
    end = next(i for i in range(start, len(lines)) if lines[i] == "}")
    return lines[start:end + 1]


def _golden_s100_body() -> list[str]:
    lines = _read_gbk(S100_GOLDEN)
    start = next(i for i, l in enumerate(lines) if l.strip() == "@@PLAN Pdr_Verify")
    end = next(i for i in range(start, len(lines)) if lines[i].strip() == "@@END_PLAN")
    return lines[start:end + 1]


def _support_for(contribution: ProgramContribution) -> ProgramContribution:
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
            for index, requirement in enumerate(contribution.resource_requires)
        ),
    )


class PlatformRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.workbook = workbook
        cls.compilation = ProductCompiler().compile(workbook).require_success()
        cls.flow = normalize_flow_table(workbook.dataframe("FLOW"))
        cls.pin_dec = workbook.dataframe("PIN DEC")
        cls.operations = tuple(
            operation
            for operation in cls.compilation.plan.catalogs.flow_operations
            if token_key(operation.item) == "pdr_verify"
        )

    def _plan(self, platform: str, cp: str = "CP1"):
        operation = next(
            operation
            for operation in self.operations
            if operation.cp.casefold() == cp.casefold()
        )
        return compile_pdr_verify_plan(self.flow, operation, platform)

    def _schedule(self, cp: str = "CP1"):
        return self.compilation.for_cp(cp).canonical_schedule

    def test_resolve_power_rails_reads_pin_dec_without_global_state(self):
        self.assertEqual(resolve_power_rails(self.pin_dec, "CP1"), ("VCC4",))

    def test_chroma_section_matches_golden_function_block(self):
        plan = self._plan("chroma")
        target = TargetKey("chroma", "CP1", "lab", "V_TEST_CP1")
        context = PdrVerifyRenderContext(power_rails=("VCC4",))
        section = render_pdr_verify_section(
            plan, target, self._schedule(), context=context
        )
        self.assertEqual(section.content.decode().splitlines(), _golden_chroma_body())

    def test_s100_section_matches_golden_function_block(self):
        plan = self._plan("s100")
        target = TargetKey("s100", "CP1", "lab", "V_TEST_CP1")
        context = PdrVerifyRenderContext(power_rails=("VCC4",))
        section = render_pdr_verify_section(
            plan, target, self._schedule(), context=context
        )
        self.assertEqual(section.content.decode().splitlines(), _golden_s100_body())

    def test_assembler_closes_section_into_a_body_artifact(self):
        plan = self._plan("chroma")
        target = TargetKey("chroma", "CP1", "lab", "V_TEST_CP1")
        schedule = self._schedule()
        context = PdrVerifyRenderContext(power_rails=("VCC4",))

        contribution = compile_pdr_verify_contribution(plan, target, schedule)
        section = render_pdr_verify_section(plan, target, schedule, context=context)
        contribution = replace(contribution, sections=(section,))

        render_plan = ProgramAssembler(section_order=("TESTS",)).assemble(
            target, (contribution, _support_for(contribution))
        )
        artifact = render_plan.artifact(f"{target.program_name}.pln")
        self.assertEqual(artifact.content.decode().splitlines(), _golden_chroma_body())

    def test_resolve_pattern_resource_loads_committed_seed_bytes(self):
        seed_root = CHROMA_SEED_ROOT
        resource = resolve_pattern_resource(
            "pattern:enter_fbist_mode", "chroma", seed_root
        )
        self.assertEqual(resource.relative_path, "pat/enter_fbist_mode.pat")
        self.assertEqual(
            resource.content,
            (seed_root / "pat_temp" / "enter_fbist_mode.pat").read_bytes(),
        )
        self.assertTrue(resource.content)

    def test_assembler_closes_real_pattern_resources_against_the_contribution(self):
        plan = self._plan("chroma")
        target = TargetKey("chroma", "CP1", "lab", "V_TEST_CP1")
        schedule = self._schedule()
        context = PdrVerifyRenderContext(power_rails=("VCC4",))

        contribution = compile_pdr_verify_contribution(plan, target, schedule)
        section = render_pdr_verify_section(plan, target, schedule, context=context)
        contribution = replace(contribution, sections=(section,))

        resources = tuple(
            resolve_pattern_resource(
                requirement.logical_identity, "chroma", CHROMA_SEED_ROOT
            )
            for requirement in contribution.resource_requires
        )
        support = ProgramContribution(
            identity=f"support:{target.identity}",
            target=target,
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
            resources=resources,
        )

        render_plan = ProgramAssembler(section_order=("TESTS",)).assemble(
            target, (contribution, support)
        )
        for requirement in contribution.resource_requires:
            artifact = render_plan.artifact(requirement.relative_path)
            self.assertIsNotNone(artifact)
            self.assertEqual(
                artifact.content,
                (CHROMA_SEED_ROOT / "pat_temp" / f"{requirement.logical_identity.rsplit(':', 1)[-1]}.pat").read_bytes(),
            )

    def test_materializer_writes_body_and_pattern_artifacts_to_staging(self):
        import shutil

        plan = self._plan("chroma")
        target = TargetKey("chroma", "CP1", "lab", "V_TEST_CP1")
        schedule = self._schedule()
        context = PdrVerifyRenderContext(power_rails=("VCC4",))

        contribution = compile_pdr_verify_contribution(plan, target, schedule)
        section = render_pdr_verify_section(plan, target, schedule, context=context)
        contribution = replace(contribution, sections=(section,))
        resources = tuple(
            resolve_pattern_resource(
                requirement.logical_identity, "chroma", CHROMA_SEED_ROOT
            )
            for requirement in contribution.resource_requires
        )
        support = ProgramContribution(
            identity=f"support:{target.identity}",
            target=target,
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
            resources=resources,
        )
        render_plan = ProgramAssembler(section_order=("TESTS",)).assemble(
            target, (contribution, support)
        )

        # pathlib mkdir (0o777) is writable under the sandbox, unlike
        # tempfile.TemporaryDirectory (0o700).
        staging = ROOT / ".tmp_materialize_test"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir()
        try:
            artifact_set = ArtifactMaterializer().materialize(render_plan, staging)
            self.assertEqual(artifact_set.target, target)
            self.assertTrue((staging / f"{target.program_name}.pln").exists())
            for requirement in contribution.resource_requires:
                self.assertTrue(
                    (staging / requirement.relative_path).exists()
                )
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def test_platform_render_planner_closes_the_full_native_slice(self):
        planner = PlatformRenderPlanner(
            section_order=("TESTS",),
            seed_root=CHROMA_SEED_ROOT,
        )
        target = TargetKey("chroma", "CP1", "lab", "V_TEST_CP1")

        render_plan = planner.plan(self.compilation, target, self.workbook)

        content = render_plan.artifact(f"{target.program_name}.pln").content.decode()
        # PDR_VERIFY body is present (OS renders alongside it in the same plan).
        self.assertIn("\n".join(_golden_chroma_body()), content)

        # All four PDR_VERIFY patterns are materialized from real seed bytes.
        plan = self._plan("chroma")
        for resource in plan.pattern_resources:
            artifact = render_plan.artifact(f"pat/{resource.name}.pat")
            self.assertIsNotNone(artifact)
            self.assertEqual(
                artifact.content,
                (CHROMA_SEED_ROOT / "pat_temp" / f"{resource.name}.pat").read_bytes(),
            )

    def test_planner_renders_both_standard_trim_variants_and_closes_patterns(self):
        planner = PlatformRenderPlanner(
            section_order=("TESTS",),
            seed_root=CHROMA_SEED_ROOT,
        )
        target = TargetKey("chroma", "CP1", "lab", "V_TEST_CP1")

        render_plan = planner.plan(self.compilation, target, self.workbook)

        content = render_plan.artifact(f"{target.program_name}.pln").content.decode()
        self.assertIn("Vrefint_Trim()", content)
        self.assertIn("Vrefint_Dac_Loop()", content)
        self.assertIn(
            "set_vref0p8_abs_trim_data(VREF0P8_ABS_DAC_FINAL);",
            content,
        )
        for name in (
            "enter_fbist_mode",
            "enter_vrefint",
            "set_vrefint_dac",
            "exit_fbist_mode",
        ):
            self.assertEqual(
                render_plan.artifact(f"pat/{name}.pat").content,
                (CHROMA_SEED_ROOT / "pat_temp" / f"{name}.pat").read_bytes(),
            )

    def test_planner_injects_the_required_skeleton(self):
        skeleton = SectionFragment(
            "header.pln", "SKELETON", "skeleton:header", b"/* header */\n"
        )
        planner = PlatformRenderPlanner(
            section_order=("SKELETON", "TESTS"),
            skeleton=(skeleton,),
            seed_root=CHROMA_SEED_ROOT,
        )
        target = TargetKey("chroma", "CP1", "lab", "V_TEST_CP1")

        render_plan = planner.plan(self.compilation, target, self.workbook)

        self.assertEqual(
            render_plan.artifact("header.pln").content, b"/* header */\n"
        )

    def test_planner_exposes_the_family_renderer_registry(self):
        planner = PlatformRenderPlanner(seed_root=CHROMA_SEED_ROOT)
        # The registry is the copy-paste seam for the next family: migrating
        # OS/STANDARD_TRIM adds one entry here plus one _render_<family> method.
        self.assertEqual(
            planner.families,
            ("pdr_verify", "os", "pdr_trim", "standard_trim"),
        )

    def test_chroma_fixed_skeleton_matches_golden_prefix(self):
        skeleton = chroma_fixed_skeleton(CHROMA_GOLDEN, "V_TEST_CP1")
        self.assertEqual(len(skeleton), 2)
        header, globals_frag = skeleton
        self.assertEqual(header.artifact_path, "V_TEST_CP1.pln")
        self.assertEqual(header.section, "HEADER")
        self.assertEqual(globals_frag.section, "GLOBALS")

        golden_lines = _read_gbk(CHROMA_GOLDEN)
        header_end = next(
            i for i, l in enumerate(golden_lines) if l.startswith("TIME FSCLK_ERASE")
        )
        globals_end = next(
            i for i, l in enumerate(golden_lines) if l.startswith("START_UP()")
        )
        self.assertEqual(
            header.content.decode(), "\n".join(golden_lines[:header_end]) + "\n"
        )
        self.assertEqual(
            globals_frag.content.decode(),
            "\n".join(golden_lines[header_end:globals_end]) + "\n",
        )

    def test_planner_uses_section_order_and_fixed_skeleton(self):
        skeleton = chroma_fixed_skeleton(CHROMA_GOLDEN, "V_TEST_CP1")
        planner = PlatformRenderPlanner(
            section_order=CHROMA_SECTION_ORDER,
            skeleton=skeleton,
            seed_root=CHROMA_SEED_ROOT,
        )
        target = TargetKey("chroma", "CP1", "lab", "V_TEST_CP1")

        render_plan = planner.plan(self.compilation, target, self.workbook)

        content = render_plan.artifact("V_TEST_CP1.pln").content.decode()
        golden_lines = _read_gbk(CHROMA_GOLDEN)
        globals_end = next(
            i for i, l in enumerate(golden_lines) if l.startswith("START_UP()")
        )
        # The fixed header+globals skeleton lands first, then the PDR_VERIFY body.
        self.assertTrue(content.startswith("\n".join(golden_lines[:globals_end]) + "\n"))
        self.assertIn("Pdr_Verify()", content)


if __name__ == "__main__":
    unittest.main()
