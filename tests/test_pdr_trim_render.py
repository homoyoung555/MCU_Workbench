"""PDR_TRIM family native-renderer: body renderer + function-block Golden.

Third family on the ``PlatformRenderPlanner`` template.  Pins the Chroma body
byte-for-byte; test_number/relay/vcc/resolve wiring is the next integration
step (test_number derives from the PATTERN-sheet ordering, not FLOW row).
"""

from __future__ import annotations

from tests.workspace_paths import (
    CHROMA_GOLDEN_ROOT,
    CHROMA_SEED_ROOT,
    FORMAL_MASTER as EXTERNAL_FORMAL_MASTER,
)

from pathlib import Path
import unittest

from program_gen.compiler import ProductCompiler
from program_gen.platforms.chroma.pdr_trim_renderer import render_pdr_trim_body
from program_gen.workbook import WorkbookReader


ROOT = Path(__file__).resolve().parents[1]
FORMAL_MASTER = EXTERNAL_FORMAL_MASTER
CHROMA_GOLDEN = (
    CHROMA_GOLDEN_ROOT / "LAB" / "CHROMA"
    / "V_PCD2509V1_PY32F420A_C8_30C_V00_50_1SLAB_CP1"
    / "V_PCD2509V1_PY32F420A_C8_30C_V00_50_1SLAB_CP1.pln"
)


def _read_gbk(path: Path) -> list[str]:
    return path.read_bytes().decode("gbk", errors="replace").splitlines()


def _golden_pdr_trim_body() -> list[str]:
    lines = _read_gbk(CHROMA_GOLDEN)
    start = next(i for i, l in enumerate(lines) if l.strip() == "Pdr_Trim()")
    end = next(i for i in range(start, len(lines)) if lines[i] == "}")
    return lines[start:end + 1]


class PdrTrimRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.workbook = workbook
        cls.compilation = ProductCompiler().compile(workbook).require_success()

    def _plan(self, cp: str = "CP1"):
        return next(
            plan
            for plan in self.compilation.plan.catalogs.dedicated_trim_plans.values()
            if plan.cp == cp
        )

    def test_chroma_pdr_trim_body_matches_golden_byte_for_byte(self):
        plan = self._plan()
        body = render_pdr_trim_body(
            plan,
            power_rails="VCC4",
        )
        self.assertEqual(body.splitlines(), _golden_pdr_trim_body())

    def test_rejects_non_pdr_trim_plan(self):
        plan = self._plan()
        from dataclasses import replace

        with self.assertRaises(ValueError):
            render_pdr_trim_body(
                replace(plan, typed_kind="STANDARD_TRIM"),
                power_rails="VCC4",
            )

    def test_planner_renders_pdr_trim_body(self):
        from program_gen.platform_render import PlatformRenderPlanner
        from program_gen.render_plan import TargetKey

        planner = PlatformRenderPlanner(
            section_order=("HEADER", "GLOBALS", "STARTUP", "TESTS", "FLOW"),
            seed_root=CHROMA_SEED_ROOT,
        )
        target = TargetKey("chroma", "CP1", "lab", "V_TEST_CP1")
        render_plan = planner.plan(self.compilation, target, self.workbook)
        content = render_plan.artifact("V_TEST_CP1.pln").content.decode()
        self.assertIn("\n".join(_golden_pdr_trim_body()), content)


if __name__ == "__main__":
    unittest.main()
