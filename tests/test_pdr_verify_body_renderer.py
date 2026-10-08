"""Body renderer for a typed PDR_VERIFY plan.

These tests pin the *behaviour* of turning a platform-neutral ``PdrVerifyPlan``
into Chroma/S100 tester source.  They do not read global ``G`` state or write
files, so they are the first native-renderer seam after the metadata-only
contribution graph.
"""

from __future__ import annotations

from tests.workspace_paths import (
    CHROMA_GOLDEN_ROOT,
    FORMAL_MASTER as EXTERNAL_FORMAL_MASTER,
    S100_GOLDEN_ROOT,
)

from pathlib import Path
import unittest

from program_gen.compiler import ProductCompiler
from program_gen.core.input_normalization import normalize_flow_table, token_key
from program_gen.core.pdr_verify import compile_pdr_verify_plan
from program_gen.workbook import WorkbookReader


ROOT = Path(__file__).resolve().parents[1]
FORMAL_MASTER = EXTERNAL_FORMAL_MASTER


class _PdrVerifyBodyFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        workbook = WorkbookReader().read(FORMAL_MASTER)
        compilation = ProductCompiler().compile(workbook).require_success()
        cls._flow = normalize_flow_table(workbook.dataframe("FLOW"))
        cls._operations = tuple(
            operation
            for operation in compilation.plan.catalogs.flow_operations
            if token_key(operation.item) == "pdr_verify"
        )

    def _plan(self, platform: str, cp: str = "CP1"):
        operation = next(
            operation
            for operation in self._operations
            if operation.cp.casefold() == cp.casefold()
        )
        return compile_pdr_verify_plan(self._flow, operation, platform)


class ChromaPdrVerifyBodyTests(_PdrVerifyBodyFixture):
    def _body(self, cp: str = "CP1"):
        from program_gen.platforms.chroma.pdr_verify_renderer import (
            render_pdr_verify_body,
        )

        plan = self._plan("chroma", cp)
        return render_pdr_verify_body(
            plan, power_rails=("VCC4",), test_number=(plan.row + 1) * 100
        )

    def test_body_expresses_pdr_max_normal_semantics(self):
        body = self._body()
        # PDR MAX voltage: device must stay alive, so a FAIL on the status
        # pattern is the anomaly that raises the flag.
        self.assertIn(
            "FORCE_V_MLDPS(VCC4, VCC_PDR_MAX,@6V,@500mA,200mA,NORM,ON,2mS)",
            body,
        )
        self.assertIn(
            "if(JUDGE_RESULT_MS[SOCKET]==FAIL) pdrVerifyflag[SOCKET]=1;", body
        )

    def test_body_expresses_pdr_min_reset_semantics(self):
        body = self._body()
        # PDR MIN voltage: device must reset, so a PASS on the status pattern
        # is the anomaly that raises the flag.
        self.assertIn(
            "FORCE_V_MLDPS(VCC4, VCC_PDR_MIN,@6V,@500mA,200mA,NORM,ON,2mS)",
            body,
        )
        self.assertIn(
            "if(JUDGE_RESULT_MS[SOCKET]==PASS) pdrVerifyflag[SOCKET]=1;", body
        )

    def test_body_runs_the_fbist_pattern_sequence(self):
        body = self._body()
        self.assertIn("JUDGE_PAT(enter_fbist_mode,__enter_fbist_mode)", body)
        self.assertIn("JUDGE_PAT(enter_pdr_verify,__enter_pdr_verify)", body)
        self.assertIn("JUDGE_PAT(read_status_mode,__read_status_mode)", body)
        self.assertIn("JUDGE_PAT(exit_fbist_mode,__exit_fbist_mode)", body)

    def test_body_reads_status_pattern_twice(self):
        body = self._body()
        self.assertEqual(
            body.count("JUDGE_PAT(read_status_mode,__read_status_mode)"), 2
        )

    def test_body_declares_per_site_flag_and_sets_power_profile(self):
        plan = self._plan("chroma")
        body = self._body()
        self.assertIn("int pdrVerifyflag[MAX_SITE];", body)
        # initial Vcc profile comes from the plan, not from G.
        self.assertIn(f"POWER_ON({plan.initial_power_profile});", body)


class S100PdrVerifyBodyTests(_PdrVerifyBodyFixture):
    def _body(self, cp: str = "CP1"):
        from program_gen.platforms.s100.pdr_verify_renderer import (
            render_pdr_verify_body,
        )

        plan = self._plan("s100", cp)
        return render_pdr_verify_body(plan, power_rails=("VCC4",), reject_bin=25)

    def test_body_uses_driver_result_threshold_semantics(self):
        body = self._body()
        # S100 judges the status pattern through Sys_DriverResult rather than
        # JUDGE_RESULT_MS; PDR MAX (normal) flags >0.5, PDR MIN (reset) <0.5.
        self.assertIn("LOGIC_FORCE_DPS(VCC4, _C_VCC_PDR_MAX, 500MA, I7, WAIT=0.5MS)", body)
        self.assertIn("if(Sys_DriverResult[T_SOCKET] > 0.5) pdrVerifyflag[T_SOCKET]=1;", body)
        self.assertIn("if(Sys_DriverResult[T_SOCKET] < 0.5) pdrVerifyflag[T_SOCKET]=1;", body)

    def test_body_runs_s100_pattern_sequence(self):
        body = self._body()
        self.assertIn("RUN_PATTERN(enter_fbist_mode:START,enter_fbist_mode:END,1,TS_5MHZ)", body)
        self.assertIn("RUN_PATTERN(enter_pdr_verify:START,enter_pdr_verify:END,1,TS_5MHZ)", body)


class GoldenByteAlignmentTests(_PdrVerifyBodyFixture):
    """Pin renderer output to the committed golden program artifacts.

    These are the function-block Golden comparisons the handoff names as the
    acceptance gate: the native body renderer must reproduce, byte for byte,
    the PDR_VERIFY block the legacy writer emitted for CP1 LAB.
    """

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

    @staticmethod
    def _read_gbk(path: Path) -> list[str]:
        return path.read_bytes().decode("gbk", errors="replace").splitlines()

    def test_chroma_body_matches_golden_function_block_byte_for_byte(self):
        from program_gen.platforms.chroma.pdr_verify_renderer import (
            render_pdr_verify_body,
        )

        golden = self._read_gbk(self.CHROMA_GOLDEN)
        start = next(i for i, l in enumerate(golden) if l.strip() == "Pdr_Verify()")
        end = next(i for i in range(start, len(golden)) if golden[i] == "}")
        golden_block = golden[start:end + 1]

        plan = self._plan("chroma")
        body = render_pdr_verify_body(
            plan, power_rails=("VCC4",), test_number=(plan.row + 1) * 100
        )
        self.assertEqual(body.splitlines(), golden_block)

    def test_s100_body_matches_golden_function_block_byte_for_byte(self):
        from program_gen.platforms.s100.pdr_verify_renderer import (
            render_pdr_verify_body,
        )

        golden = self._read_gbk(self.S100_GOLDEN)
        start = next(i for i, l in enumerate(golden) if l.strip() == "@@PLAN Pdr_Verify")
        end = next(i for i in range(start, len(golden)) if golden[i].strip() == "@@END_PLAN")
        golden_block = golden[start:end + 1]

        plan = self._plan("s100")
        body = render_pdr_verify_body(plan, power_rails=("VCC4",), reject_bin=25)
        self.assertEqual(body.splitlines(), golden_block)


if __name__ == "__main__":
    unittest.main()
