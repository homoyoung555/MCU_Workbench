from tests.workspace_paths import FORMAL_MASTER as EXTERNAL_FORMAL_MASTER
"""Platform schedule renderers consume the compiler-owned canonical schedule."""

from io import StringIO
import ast
from pathlib import Path
import unittest
from unittest.mock import patch

from program_gen.compiler import ProductCompiler
from program_gen.platforms.chroma import startup as chroma_startup
from program_gen.platforms.s100 import startup as s100_startup
from program_gen.workbook import WorkbookReader


ROOT = Path(__file__).resolve().parents[1]
FORMAL_MASTER = EXTERNAL_FORMAL_MASTER


class ChromaCanonicalScheduleRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        workbook = WorkbookReader().read(FORMAL_MASTER)
        compilation = ProductCompiler().compile(workbook).require_success()
        cls.schedule = compilation.adapter_view("CP1", "chroma").canonical_schedule

    def test_bins_and_test_pro_consume_canonical_schedule_without_flow_reads(self) -> None:
        output = StringIO()

        with patch.object(chroma_startup.G, "col", side_effect=AssertionError("FLOW read")), \
                patch.object(chroma_startup.G, "f", output):
            chroma_startup.Hw_Sw_Bin(
                ["PROGRAM_CP1"], output, canonical_schedule=self.schedule
            )
            chroma_startup.TEST_PRO(
                ["PROGRAM_CP1"], canonical_schedule=self.schedule
            )

        rendered = output.getvalue()
        self.assertIn("hw_Pgm_Cp1Id_Read" + " " * 21 + "=!60;", rendered)
        self.assertNotIn("NM_Data_Read", rendered)
        self.assertIn("#C(hw_Pgm_Cp1Id_Read", rendered)
        self.assertNotIn("OTP_Read", rendered)


class S100CanonicalScheduleRendererTests(ChromaCanonicalScheduleRendererTests):
    def test_booking_consumes_canonical_schedule_without_flow_reads(self) -> None:
        output = StringIO()

        with patch.object(s100_startup.G, "col", side_effect=AssertionError("FLOW read")):
            s100_startup.Hw_Sw_Bin(
                ["PROGRAM_CP1"], output, canonical_schedule=self.schedule
            )

        rendered = output.getvalue()
        self.assertIn("@@BOOKING", rendered)
        self.assertIn("Pgm_Cp1Id_Read;", rendered)
        self.assertNotIn("NM_Data_Read;", rendered)
        self.assertIn("//Vref0P8_Tc_Dac_Loop;", rendered)
        self.assertNotIn("OTP_Read;", rendered)


class ProductionScheduleWiringTests(unittest.TestCase):
    def test_platform_mains_pass_compiled_canonical_schedule_to_renderers(self) -> None:
        root = Path(__file__).resolve().parents[1]

        chroma = ast.parse((root / "program_gen" / "platforms" / "chroma" / "main.py").read_text(encoding="utf-8"))
        s100 = ast.parse((root / "program_gen" / "platforms" / "s100" / "main.py").read_text(encoding="utf-8"))

        self.assertTrue(_calls_with_compiled_schedule(chroma, "Hw_Sw_Bin"))
        self.assertTrue(_calls_with_compiled_schedule(chroma, "TEST_PRO"))
        self.assertTrue(_calls_with_compiled_schedule(s100, "Hw_Sw_Bin"))


def _calls_with_compiled_schedule(module, name: str) -> bool:
    for node in ast.walk(module):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != name:
            continue
        for keyword in node.keywords:
            value = keyword.value
            if keyword.arg == "canonical_schedule" and isinstance(value, ast.Attribute):
                if isinstance(value.value, ast.Name) and value.value.id == "compiled":
                    return value.attr == "canonical_schedule"
    return False
