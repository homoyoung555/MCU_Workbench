"""STANDARD_TRIM missing-domain-model declaration and blocking.

This stage declares which STANDARD_TRIM domain models are missing and blocks
every attempt to project/assemble/register/render STANDARD_TRIM.  There is no
typed profile, no projection success path, no tester text, and no fabricated
"confirmed" business facts.
"""

from __future__ import annotations

from pathlib import Path
import unittest

from tests.workspace_paths import FORMAL_MASTER as EXTERNAL_FORMAL_MASTER

from program_gen.compiler import ProductCompiler
from program_gen.render_plan import TargetKey
from program_gen.shadow.typed_profile import (
    MISSING_DOMAIN_MODELS,
    StandardTrimGap,
    StandardTrimGapError,
    gap_for,
)
from program_gen.workbook import WorkbookReader


ROOT = Path(__file__).resolve().parents[1]
FORMAL_MASTER = EXTERNAL_FORMAL_MASTER


class StandardTrimGapModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()
        cls.spec = next(
            spec for spec in cls.compilation.plan.catalogs.trim_specs.values()
            if spec.item == "Hsi_8M" and spec.cp == "CP1"
        )
        cls.schedule = cls.compilation.for_cp("CP1").canonical_schedule

    def _chroma_target(self) -> TargetKey:
        return TargetKey("chroma", "CP1", "lab", "V_TEST_CP1")

    def _s100_target(self) -> TargetKey:
        return TargetKey("s100", "CP1", "lab", "V_TEST_CP1")

    # ------------------------------------------------------------------
    # GREEN: the gap scaffold enumerates exactly the missing domain models
    # ------------------------------------------------------------------

    def test_gap_declares_only_remaining_full_artifact_models(self):
        self.assertEqual(
            MISSING_DOMAIN_MODELS,
            (
                "PlatformLifecycleFacts",
                "PlatformElectricalFacts",
                "PlatformProjectResources",
            ),
        )

    def test_gap_scaffold_lists_missing_models_for_each_platform(self):
        for platform in ("chroma", "s100"):
            with self.subTest(platform=platform):
                gap = gap_for(platform)
                self.assertIsInstance(gap, StandardTrimGap)
                self.assertEqual(gap.platform, platform)
                self.assertEqual(gap.missing_domain_models, MISSING_DOMAIN_MODELS)
                # File-level naming facts only; no business facts exist.
                self.assertEqual(
                    gap.pattern_path("enter_fbist_mode"),
                    "pat/enter_fbist_mode.pat"
                    if platform == "chroma"
                    else "enter_fbist_mode.sd",
                )

    def test_gap_has_no_business_fact_fields(self):
        # The gap model must not carry any (fake) business facts at all.
        for platform in ("chroma", "s100"):
            with self.subTest(platform=platform):
                gap = gap_for(platform)
                for name in (
                    "power_contract",
                    "fbist_contract",
                    "measurement_contract",
                    "timing_contract",
                    "relay_contract",
                    "helper_contract",
                    "skeleton_producer",
                ):
                    with self.subTest(fact=name):
                        self.assertFalse(hasattr(gap, name))

    # ------------------------------------------------------------------
    # RED: projection requests are always blocked
    # ------------------------------------------------------------------

    def test_projection_is_unavailable_for_any_platform(self):
        for platform in ("chroma", "s100"):
            with self.subTest(platform=platform):
                gap = gap_for(platform)
                with self.assertRaises(StandardTrimGapError) as ctx:
                    gap.require_projection_available()
                self.assertEqual(ctx.exception.code, "SG.PROJECTION.UNAVAILABLE")
                self.assertIn("PlatformElectricalFacts", str(ctx.exception))

    # ------------------------------------------------------------------
    # RED: CP / platform / identity requests are blocked
    # ------------------------------------------------------------------

    def test_gap_cannot_serve_mismatched_platform_target(self):
        chroma_gap = gap_for("chroma")
        with self.assertRaises(StandardTrimGapError) as ctx:
            chroma_gap.require_target(self._s100_target())
        self.assertEqual(ctx.exception.code, "SG.TARGET.PLATFORM_MISMATCH")

    def test_gap_never_provides_cp_or_identity_resolution(self):
        # The gap scaffold exposes no API that resolves a TrimSpec, canonical
        # schedule, CP, or definition identity: there is nothing to project.
        gap = gap_for("chroma")
        for name in (
            "project",
            "project_standard_trim",
            "resolve_definition",
            "resolve_cp",
            "contributions",
            "sections",
            "provides",
            "requires",
        ):
            with self.subTest(api=name):
                self.assertFalse(hasattr(gap, name))

    # ------------------------------------------------------------------
    # Pure gap model: no renderer, no filesystem, no legacy/Golden
    # ------------------------------------------------------------------

    def test_gap_model_is_pure_declaration(self):
        source = (
            ROOT / "program_gen" / "shadow" / "typed_profile.py"
        ).read_text(encoding="utf-8")
        import ast

        tree = ast.parse(source)
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertFalse(
            {"openpyxl", "pandas", "program_gen.state", "program_gen.workbook"}
            & imports
        )
        calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertFalse(
            {"open", "read_bytes", "glob", "rglob", "listdir", "scandir"} & calls
        )
        self.assertFalse({"os", "pathlib", "shutil", "subprocess"} & imports)
        attributes = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
        }
        self.assertNotIn("read_bytes", attributes)
        # Only TargetKey is imported from render_plan — never the output types.
        from program_gen.render_plan import TargetKey  # noqa: F401

        imported_names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
            if node.module == "program_gen.render_plan"
        }
        self.assertEqual(imported_names, {"TargetKey"})


if __name__ == "__main__":
    unittest.main()
