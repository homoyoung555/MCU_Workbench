"""ProductCompiler integration of the FBIST pattern generation plan.

``ProductCompilation.pattern_compilation`` now returns the immutable
``FbistPatternGenerationPlan``; the legacy PatternCompilation wrapper is gone.
The compatibility pattern_files entry points publish generator artifacts, and
GeneratedPatternProducer overlays them on non-FBIST workspace resources.
"""

from __future__ import annotations

from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests.workspace_paths import FORMAL_MASTER as EXTERNAL_FORMAL_MASTER

from program_gen import state as G
from program_gen.compiler import ProductCompiler
from program_gen.core.fbist_pattern_plan import (
    FbistPatternCompileError,
    FbistPatternGenerationPlan,
    compile_fbist_pattern_plan,
)
from program_gen.platform_program.pattern import (
    GeneratedPatternProducer,
    PatternWriteRegion,
    WorkspacePatternProducer,
)
from program_gen.render_plan import ResourceRequirement
from program_gen.workbook import WorkbookReader

ROOT = Path(__file__).resolve().parents[1]
FORMAL_MASTER = EXTERNAL_FORMAL_MASTER


class ProductCompilerFbistPatternTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()

    def test_pattern_compilation_returns_the_fbist_pattern_plan(self):
        plan = self.compilation.pattern_compilation
        self.assertIsInstance(plan, FbistPatternGenerationPlan)
        self.assertIs(self.compilation.plan.catalogs.fbist_pattern_plan, plan)
        self.assertEqual(plan.clk_pin, "PA11")
        self.assertEqual(plan.swd_pin, "PA13")
        self.assertEqual(len(plan.pump_aggregate.targets), 8)
        self.assertEqual(plan.dynamic_enter_patterns, ("enter_mr_vddd_dc_verify",))

    def test_plan_matches_direct_upstream_compilation(self):
        flow = self.workbook.dataframe("FLOW")
        direct = compile_fbist_pattern_plan(
            self.workbook,
            flow,
            trim_specs=self.compilation.plan.catalogs.trim_specs,
            recipe_rows=self.compilation.plan.catalogs.recipe_rows,
        )
        self.assertEqual(direct, self.compilation.pattern_compilation)
        self.assertEqual(direct.identity, self.compilation.pattern_compilation.identity)

    def test_legacy_adapter_view_still_exposes_recipe_and_trim_facts(self):
        view = self.compilation.adapter_view("CP1", "chroma")
        self.assertTrue(view.recipe_rows)
        self.assertTrue(view.trim_specs)
        self.assertEqual(tuple(view.dedicated_trim_plans), (7,))

    def test_compile_failure_becomes_a_fbist_pattern_error_diagnostic(self):
        with patch(
            "program_gen.compiler.compile_fbist_pattern_plan",
            side_effect=FbistPatternCompileError("pattern row 9: addr 非法"),
        ):
            compilation = ProductCompiler().compile(self.workbook)
        self.assertFalse(compilation.is_valid)
        self.assertEqual(
            tuple(item.code for item in compilation.diagnostics.errors),
            ("COMPILER.FBIST_PATTERN",),
        )
        self.assertIn("pattern row 9", compilation.diagnostics.errors[0].message)


class PatternPublicationEntryPointTests(unittest.TestCase):
    """Compatibility entry points publish the exact generator artifacts.

    These tests cover publication only; they are not an independent comparison
    with the pre-rewrite generator.
    """

    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()

    def _run_entrypoint(self, platform: str) -> tuple[dict[str, bytes], object]:
        tmp_root = ROOT / ".test_tmp"
        tmp_root.mkdir(exist_ok=True)
        counter = len(list(tmp_root.glob("fbist-legacy-*")))
        base = tmp_root / f"fbist-legacy-{counter}"
        base.mkdir(exist_ok=False)
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        G.init(str(base), platform=platform, mode="production", workbook_model=self.workbook)
        if platform == "chroma":
            from program_gen.platforms.chroma.pattern_files import (
                fbist_pattern_created,
            )
        else:
            from program_gen.platforms.s100.pattern_files import (
                fbist_pattern_created,
            )
        fbist_pattern_created(self.compilation.pattern_compilation)
        files = {
            path.name: path.read_bytes()
            for path in (base / "pat_temp").glob("*")
        }
        return files, base

    def test_chroma_entry_writes_generator_artifacts_byte_identical(self):
        from program_gen.platforms.chroma.fbist_pattern_generator import (
            generate_fbist_patterns,
        )

        files, _base = self._run_entrypoint("chroma")
        result = generate_fbist_patterns(self.compilation.pattern_compilation)
        self.assertTrue(files)
        for artifact in result.artifacts:
            with self.subTest(pattern=artifact.pattern_name):
                expected = artifact.content.replace(b"\n", b"\r\n")
                self.assertEqual(files[artifact.pattern_name + ".pat"], expected)

    def test_s100_entry_writes_generator_artifacts_byte_identical(self):
        from program_gen.platforms.s100.fbist_pattern_generator import (
            generate_fbist_patterns,
        )

        files, _base = self._run_entrypoint("s100")
        result = generate_fbist_patterns(self.compilation.pattern_compilation)
        self.assertTrue(files)
        for artifact in result.artifacts:
            with self.subTest(pattern=artifact.pattern_name):
                expected = artifact.content.replace(b"\n", b"\r\n")
                self.assertEqual(files[artifact.pattern_name + ".sd"], expected)


class GeneratedPatternProducerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(workbook).require_success()
        from program_gen.platforms.chroma.fbist_pattern_generator import (
            generate_fbist_patterns,
        )
        cls.chroma = generate_fbist_patterns(cls.compilation.pattern_compilation)
        from program_gen.platforms.s100.fbist_pattern_generator import (
            generate_fbist_patterns,
        )
        cls.s100 = generate_fbist_patterns(cls.compilation.pattern_compilation)

    def test_produce_serves_content_from_the_generation_result(self):
        producer = GeneratedPatternProducer(self.chroma)
        artifact = next(
            item for item in self.chroma.artifacts
            if item.pattern_name == "set_vref0p8_abs_dac"
        )
        request = producer.produce(ResourceRequirement(
            logical_identity="pattern:set_vref0p8_abs_dac",
            relative_path="pat/set_vref0p8_abs_dac.pat",
            spec_identity="v13.pattern/1:chroma:set_vref0p8_abs_dac",
            purpose="STANDARD_TRIM pattern",
        ))
        self.assertEqual(request.content, artifact.content)
        self.assertEqual(request.source_identity, artifact.source_identity)
        self.assertEqual(request.spec_identity, "v13.pattern/1:chroma:set_vref0p8_abs_dac")
        self.assertEqual(request.logical_identity, "pattern:set_vref0p8_abs_dac")

    def test_produce_missing_pattern_raises(self):
        producer = GeneratedPatternProducer(self.chroma)
        with self.assertRaises(ValueError) as ctx:
            producer.produce(ResourceRequirement(
                logical_identity="pattern:missing",
                relative_path="pat/missing.pat",
                spec_identity="x",
            ))
        self.assertIn("FBIST.PATTERN.MISSING", str(ctx.exception))

    def test_generated_patterns_overlay_workspace_patterns(self):
        base = ROOT / ".test_tmp" / "fbist-pattern-overlay"
        shutil.rmtree(base, ignore_errors=True)
        (base / "pat_temp").mkdir(parents=True)
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        pe_content = b"TIMING_SET G1_2;\r\nPE CONTENT\r\n"
        (base / "pat_temp" / "fbist_erase_main_1st_page.pat").write_bytes(
            pe_content
        )
        producer = GeneratedPatternProducer(
            self.chroma,
            fallback=WorkspacePatternProducer(base),
        )
        requirements = (
            ResourceRequirement(
                logical_identity="pattern:set_vref0p8_abs_dac",
                relative_path="pat/set_vref0p8_abs_dac.pat",
                spec_identity="generated",
            ),
            ResourceRequirement(
                logical_identity="pattern:fbist_erase_main_1st_page",
                relative_path="pat/fbist_erase_main_1st_page.pat",
                spec_identity="workspace",
            ),
        )

        generated = producer.produce(requirements[0])
        workspace = producer.produce(requirements[1])

        self.assertNotEqual(generated.content, pe_content)
        self.assertEqual(workspace.content, pe_content)
        self.assertTrue(workspace.source_identity.startswith("workspace-input:"))
        self.assertEqual(producer.timing_sets(requirements), ("G1_2",))

    def test_compilation_overlay_serves_flash_and_reports_s100_timing_sets(self):
        producer = GeneratedPatternProducer.from_compilation(
            self.compilation,
            "s100",
        )
        requirement = ResourceRequirement(
            logical_identity="pattern:fbist_bulk_prog_ckbd_nm_sm",
            relative_path="fbist_bulk_prog_ckbd_nm_sm.sd",
            spec_identity="flash-window:test",
        )

        request = producer.produce(requirement)

        self.assertTrue(request.source_identity.startswith("flash-compare:"))
        self.assertEqual(
            producer.timing_sets((requirement,)),
            ("G1_1", "G1_5"),
        )

    def test_generated_overlay_rejects_duplicate_pattern_names(self):
        with self.assertRaisesRegex(ValueError, "PATTERN.GENERATED_DUPLICATE"):
            GeneratedPatternProducer(self.chroma, self.chroma)

    def test_overlay_uses_workspace_write_region_when_pattern_is_not_generated(self):
        base = ROOT / ".test_tmp" / "fbist-pattern-write-region-overlay"
        shutil.rmtree(base, ignore_errors=True)
        (base / "pat_temp").mkdir(parents=True)
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        (base / "pat_temp" / "legacy_dac.pat").write_text(
            "a_data:\r\n",
            encoding="gbk",
        )
        producer = GeneratedPatternProducer(
            self.chroma,
            fallback=WorkspacePatternProducer(base),
        )

        self.assertEqual(
            producer.write_region("legacy_dac"),
            PatternWriteRegion("a_data", "a_data", "a_data"),
        )

    def test_overlay_binds_target_facts_to_workspace_fallback(self):
        base = ROOT / ".test_tmp" / "fbist-pattern-target-overlay"
        shutil.rmtree(base, ignore_errors=True)
        (base / "pat_temp").mkdir(parents=True)
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        (base / "pat_temp" / "legacy.pat").write_bytes(
            b"HEADER\r\nPA14, PA13, NRST;\r\n"
        )
        producer = GeneratedPatternProducer(
            self.chroma,
            fallback=WorkspacePatternProducer(base),
        ).for_target(SimpleNamespace(
            platform="chroma",
            clk_pin="PA11",
            swd_pin="PA13",
        ))

        request = producer.produce(ResourceRequirement(
            logical_identity="pattern:legacy",
            relative_path="pat/legacy.pat",
            spec_identity="workspace",
        ))

        self.assertIn(b"PA11, PA13, NRST;", request.content)

    def test_write_region_of_single_field_patterns(self):
        chroma = GeneratedPatternProducer(self.chroma)
        region = chroma.write_region("set_vref0p8_abs_dac")
        self.assertEqual(region, PatternWriteRegion("a_data", "a_data", "a_data"))
        s100 = GeneratedPatternProducer(self.s100)
        region = s100.write_region("set_vref0p8_abs_dac")
        self.assertEqual(
            region, PatternWriteRegion("a_data", "a_data_st", "a_data_sp")
        )

    def test_dynamic_enter_write_region_exists_without_runtime_consumer(self):
        self.assertNotIn(
            "enter_mr_vddd_dc",
            self.compilation.pattern_compilation.dynamic_enter_patterns,
        )
        self.assertEqual(
            GeneratedPatternProducer(self.chroma).write_region("enter_mr_vddd_dc"),
            PatternWriteRegion("a_data", "a_data", "a_data"),
        )
        self.assertEqual(
            GeneratedPatternProducer(self.s100).write_region("enter_mr_vddd_dc"),
            PatternWriteRegion("a_data", "a_data_st", "a_data_sp"),
        )

    def test_write_region_of_aggregate_is_rejected(self):
        producer = GeneratedPatternProducer(self.chroma)
        with self.assertRaises(ValueError) as ctx:
            producer.write_region("set_all_final_vposp")
        self.assertIn("WRITE_REGION", str(ctx.exception))

    def test_timing_sets_are_empty_and_input_is_rejected(self):
        producer = GeneratedPatternProducer(self.chroma)
        self.assertEqual(producer.timing_sets(()), ())
        with self.assertRaises(TypeError):
            GeneratedPatternProducer("not a result")


if __name__ == "__main__":
    unittest.main()
