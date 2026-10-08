"""Generic STANDARD_TRIM native function-block acceptance tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import ast
import unittest

from tests.workspace_paths import CHROMA_GOLDEN_ROOT, FORMAL_MASTER, S100_GOLDEN_ROOT

from program_gen.compiler import ProductCompiler
from program_gen.core.trim_spec import LinearRange, TrimOperation
from program_gen.render_plan import TargetKey
from program_gen.standard_trim.contracts import StandardTrimContractError
from program_gen.standard_trim.function_blocks import (
    StandardTrimSkeletonError,
    StandardTrimSliceError,
    render_standard_trim,
    request_assembly,
)
from program_gen.workbook import WorkbookReader


ROOT = Path(__file__).resolve().parents[1]
CHROMA_TARGET = TargetKey("chroma", "CP1", "lab", "V_TEST_CP1")
GOLDEN_STEM = "V_PCD2509V1_PY32F420A_C8_30C_V00_50_1SLAB_CP1"
CHROMA_GOLDEN = CHROMA_GOLDEN_ROOT / "LAB" / "CHROMA" / GOLDEN_STEM / f"{GOLDEN_STEM}.pln"
S100_GOLDEN = S100_GOLDEN_ROOT / "LAB" / "S100" / GOLDEN_STEM / f"{GOLDEN_STEM}.prg"


def _chroma_block(source: bytes, name: str) -> bytes:
    start = source.index(f"{name}()\r\n{{".encode("ascii"))
    opening = source.index(b"{", start)
    depth = 0
    for index in range(opening, len(source)):
        token = source[index:index + 1]
        if token == b"{":
            depth += 1
        elif token == b"}":
            depth -= 1
            if depth == 0:
                return source[start:index + 3]
    raise AssertionError(f"Golden Chroma block {name!r} is not closed")


def _s100_block(source: bytes, name: str) -> bytes:
    start = source.index(f"@@PLAN {name}\r\n".encode("ascii"))
    end = source.index(b"@@END_PLAN", start) + len(b"@@END_PLAN")
    while source[end:end + 2] == b"\r\n":
        end += 2
    return source[start:end]


def _platform_bytes(content: object) -> bytes:
    text = content.decode("utf-8") if isinstance(content, bytes) else str(content)
    return text.replace("\n", "\r\n").encode("gbk")


class StandardTrimFunctionBlockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.compilation = ProductCompiler().compile(
            WorkbookReader().read(FORMAL_MASTER)
        ).require_success()
        cls.spec = next(
            spec for spec in cls.compilation.plan.catalogs.trim_specs.values()
            if spec.item == "Hsi_8M" and spec.cp == "CP1"
        )
        cls.specs = {
            spec.item.casefold(): spec
            for spec in cls.compilation.plan.catalogs.trim_specs.values()
            if spec.cp == "CP1"
        }
        cls.schedule = cls.compilation.for_cp("CP1").canonical_schedule

    def _blocks(self, platform: str, spec=None):
        target = TargetKey(platform, "CP1", "lab", "V_TEST_CP1")
        return render_standard_trim(spec or self.spec, target, self.schedule)

    def test_product_compiler_owns_all_confirmed_render_facts(self):
        self.assertEqual(self.spec.dac.helper_name, "set_hsi_8m_trim_data")
        self.assertEqual(self.spec.dac.write_pin, "PA13")
        self.assertEqual(self.spec.measurement.sample_timeout_value, 50)
        self.assertEqual(self.spec.measurement.sample_timeout_unit, "mS")
        self.assertEqual(self.spec.measurement.search_low_limit, -125)
        self.assertEqual(self.spec.measurement.search_high_limit, 750)
        self.assertIsNone(self.spec.relay)
        self.assertEqual(self.spec.test_number, 2000)

    def test_hsi_8m_linear_search_uses_arithmetic_not_a_1024_code_array(self):
        chroma = {
            fragment.identity.rsplit(":", 1)[-1]: str(fragment.content)
            for fragment in self._blocks("chroma")
        }
        s100 = {
            fragment.identity.rsplit(":", 1)[-1]: str(fragment.content)
            for fragment in self._blocks("s100")
        }

        for content in (*chroma.values(), *s100.values()):
            self.assertNotIn("dacArray[1024]", content)
        self.assertNotIn("{0,1,2,3,4,5,6,7,8,9", content)

        self.assertIn("trimDac[I]=512;", chroma["BISECTION"])
        self.assertIn("trimDac[SOCKET] = trimDac[SOCKET] +", chroma["BISECTION"])
        self.assertIn("trimDac[I]=0;", chroma["FULL_SCAN"])
        self.assertIn("trimDac[SOCKET] = cyc;", chroma["FULL_SCAN"])
        self.assertIn("trimDac[T_SOCKET]=512;", s100["BISECTION"])
        self.assertIn("trimDac[T_SOCKET] = trimDac[T_SOCKET] +", s100["BISECTION"])
        self.assertIn("trimDac[T_SOCKET]=0;", s100["FULL_SCAN"])
        self.assertIn("trimDac[T_SOCKET] = cyc;", s100["FULL_SCAN"])

    def test_measurement_force_is_reset_only_when_it_started_nonzero(self):
        zero_force = self.specs["iref1u"]
        nonzero_force = self.specs["isa"]

        for platform in ("chroma", "s100"):
            marker = (
                "JUDGE_PAT(exit_fbist_mode"
                if platform == "chroma"
                else "RUN_PATTERN(exit_fbist_mode:START"
            )
            zero_body = str(self._blocks(platform, zero_force)[0].content)
            nonzero_body = str(self._blocks(platform, nonzero_force)[0].content)
            zero_tail = zero_body[zero_body.rindex(marker):]
            nonzero_tail = nonzero_body[nonzero_body.rindex(marker):]

            if platform == "chroma":
                self.assertNotIn("FORCE_V_PPMU(TP, 0V", zero_tail)
                self.assertNotIn("FORCE_I_PPMU(TP, 0uA", zero_tail)
                self.assertIn("FORCE_V_PPMU(TP, 0V", nonzero_tail)
                self.assertNotIn("FORCE_I_PPMU(TP, 0uA", nonzero_tail)
            else:
                self.assertNotIn("LOGIC_PPMU_FV(TP, 0V", zero_tail)
                self.assertIn("LOGIC_PPMU_FV(TP, 0V", nonzero_tail)

    def test_timeout_is_typed_input_not_renderer_default(self):
        changed = replace(
            self.spec,
            measurement=replace(
                self.spec.measurement,
                sample_timeout_value=40,
                sample_timeout_unit="mS",
            ),
        )
        content = str(self._blocks("chroma", changed)[0].content)
        self.assertIn("40mS", content)
        self.assertNotIn("50mS", content)
        source = (ROOT / "program_gen" / "standard_trim" / "function_blocks.py").read_text(encoding="utf-8")
        self.assertNotIn('"50mS"', source)

    def test_real_relay_is_explicitly_blocked_until_semantics_exist(self):
        with self.assertRaisesRegex(StandardTrimSliceError, "ST.RELAY.UNSUPPORTED"):
            self._blocks("chroma", replace(self.spec, relay="RELAY_X"))
        for fragment in (*self._blocks("chroma"), *self._blocks("s100")):
            self.assertNotIn("SET_CBIT", str(fragment.content))

    def test_target_and_identity_mismatches_block(self):
        with self.assertRaisesRegex(StandardTrimSliceError, "SC.TARGET.CP_MISMATCH"):
            render_standard_trim(
                self.spec,
                TargetKey("chroma", "CP2", "lab", "V_TEST_CP2"),
                self.schedule,
            )
        with self.assertRaisesRegex(StandardTrimSliceError, "SC.TARGET.PLATFORM"):
            render_standard_trim(
                self.spec,
                TargetKey("unknown", "CP1", "lab", "V_TEST_CP1"),
                self.schedule,
            )
        wrong = replace(
            self.schedule,
            definitions=tuple(
                replace(item, source_rows=(999,))
                for item in self.schedule.definitions
                if item.item.casefold() == "hsi_8m"
            ),
        )
        with self.assertRaisesRegex(StandardTrimSliceError, "SC.DEFINITION.IDENTITY_UNRESOLVED"):
            render_standard_trim(self.spec, CHROMA_TARGET, wrong)

    def test_undeclared_variant_and_missing_typed_facts_block(self):
        one_variant = replace(
            self.spec,
            search=replace(
                self.spec.search,
                variants=(self.spec.search.variants[0],),
            ),
        )
        with self.assertRaisesRegex(StandardTrimSliceError, "SC.VARIANT.UNDECLARED"):
            self._blocks("chroma", one_variant)
        no_protocol = replace(
            self.spec, protocol=replace(self.spec.protocol, enter_pattern="")
        )
        with self.assertRaisesRegex(StandardTrimContractError, "ST.FBIST.PATTERN_MISSING"):
            self._blocks("chroma", no_protocol)
        no_timeout = replace(
            self.spec,
            measurement=replace(
                self.spec.measurement,
                sample_timeout_value=None,
                sample_timeout_unit=None,
            ),
        )
        with self.assertRaisesRegex(StandardTrimContractError, "ST.MEASUREMENT.TIMEOUT_MISSING"):
            self._blocks("chroma", no_timeout)
        unsupported = replace(
            self.spec,
            measurement=replace(self.spec.measurement, family="TEMPERATURE"),
        )
        with self.assertRaisesRegex(StandardTrimContractError, "ST.MEASUREMENT.FAMILY"):
            self._blocks("s100", unsupported)
        no_search_limits = replace(
            self.spec,
            measurement=replace(
                self.spec.measurement,
                search_low_limit=None,
                search_high_limit=None,
            ),
        )
        with self.assertRaisesRegex(
            StandardTrimContractError, "ST.MEASUREMENT.SEARCH_LIMIT_MISSING"
        ):
            render_standard_trim(no_search_limits, CHROMA_TARGET, self.schedule)

    def test_helper_identity_is_compiled_and_not_rederived_from_item(self):
        renamed = replace(self.spec, item="Any_Other_Ordinary_Trim")
        self.assertEqual(renamed.dac.helper_name, "set_hsi_8m_trim_data")
        source = (ROOT / "program_gen" / "standard_trim" / "function_blocks.py").read_text(encoding="utf-8")
        self.assertNotIn("removesuffix", source)
        self.assertNotIn("trim_data_helper_name", source)

    def test_recipe_judge_does_not_own_protocol_exit(self):
        without_judge = replace(
            self.spec,
            operations=tuple(
                operation for operation in self.spec.operations
                if operation.kind != "JUDGE"
            ),
        )
        content = str(self._blocks("chroma", without_judge)[0].content)
        self.assertNotIn("JUDGE_FREQ", content)
        self.assertIn("exit_fbist_mode", content)
        with self.assertRaisesRegex(
            StandardTrimSliceError, "SC.OPERATION.SHAPE_UNSUPPORTED"
        ):
            self._blocks("s100", without_judge)

    def test_s100_preserves_a_run_inserted_between_trim_and_judge(self):
        operations = list(self.spec.operations)
        judge_index = next(
            index for index, operation in enumerate(operations)
            if operation.kind == "JUDGE"
        )
        operations.insert(
            judge_index,
            TrimOperation("RUN", reference="after_trim_probe", scope="ONCE"),
        )
        source = str(self._blocks(
            "s100", replace(self.spec, operations=tuple(operations))
        )[0].content)
        trim_end = source.index("}while(binAryCyc>=-1);")
        inserted = source.index(
            "RUN_PATTERN(after_trim_probe:START,after_trim_probe:END,1,TS_5MHZ);"
        )
        judge = source.index("C_COMPARE(GB5")
        self.assertLess(trim_end, inserted)
        self.assertLess(inserted, judge)

    def test_s100_rejects_dac_adjustment_outside_trim_judge_interval(self):
        spec = self.specs["hsi_vrega"]
        operations = list(spec.operations)
        adjustment = operations.pop(next(
            index for index, operation in enumerate(operations)
            if operation.kind == "DAC_ADJ"
        ))
        trim_index = next(
            index for index, operation in enumerate(operations)
            if operation.kind == "TRIM"
        )
        operations.insert(trim_index, adjustment)
        with self.assertRaisesRegex(StandardTrimSliceError, "SC.OPERATION.ORDER"):
            self._blocks("s100", replace(spec, operations=tuple(operations)))

    def test_four_function_blocks_match_external_golden_exactly(self):
        chroma = CHROMA_GOLDEN.read_bytes()
        s100 = S100_GOLDEN.read_bytes()
        expected = {
            ("chroma", "BISECTION"): _chroma_block(chroma, "Hsi_8M_Trim"),
            ("chroma", "FULL_SCAN"): _chroma_block(chroma, "Hsi_8M_Dac_Loop"),
            ("s100", "BISECTION"): _s100_block(s100, "Hsi_8M_Trim"),
            ("s100", "FULL_SCAN"): _s100_block(s100, "Hsi_8M_Dac_Loop"),
        }
        for platform in ("chroma", "s100"):
            by_variant = {
                fragment.identity.rsplit(":", 1)[-1]: fragment
                for fragment in self._blocks(platform)
            }
            for variant in ("BISECTION", "FULL_SCAN"):
                with self.subTest(platform=platform, variant=variant):
                    content = str(by_variant[variant].content)
                    if isinstance(self.spec.search.domain, LinearRange):
                        self.assertNotIn("dacArray", content)
                    else:
                        self.assertEqual(
                            _platform_bytes(content), expected[(platform, variant)]
                        )

    def test_voltage_trim_function_blocks_match_external_golden_exactly(self):
        spec = self.specs["vref0p8_tc"]
        chroma = CHROMA_GOLDEN.read_bytes()
        s100 = S100_GOLDEN.read_bytes()
        for platform, source, block_reader in (
            ("chroma", chroma, _chroma_block),
            ("s100", s100, _s100_block),
        ):
            by_variant = {
                fragment.identity.rsplit(":", 1)[-1]: fragment
                for fragment in self._blocks(platform, spec)
            }
            for variant, render_name in (
                ("BISECTION", "Vref0P8_Tc_Trim"),
                ("FULL_SCAN", "Vref0P8_Tc_Dac_Loop"),
            ):
                with self.subTest(platform=platform, variant=variant):
                    self.assertEqual(
                        _platform_bytes(by_variant[variant].content),
                        block_reader(source, render_name),
                    )

    def test_current_trim_function_blocks_match_external_golden_exactly(self):
        spec = self.specs["iref1u"]
        chroma = CHROMA_GOLDEN.read_bytes()
        s100 = S100_GOLDEN.read_bytes()
        for platform, source, block_reader in (
            ("chroma", chroma, _chroma_block),
            ("s100", s100, _s100_block),
        ):
            by_variant = {
                fragment.identity.rsplit(":", 1)[-1]: fragment
                for fragment in self._blocks(platform, spec)
            }
            for variant, render_name in (
                ("BISECTION", "Iref1U_Trim"),
                ("FULL_SCAN", "Iref1U_Dac_Loop"),
            ):
                with self.subTest(platform=platform, variant=variant):
                    self.assertEqual(
                        _platform_bytes(by_variant[variant].content),
                        block_reader(source, render_name),
                    )

    def test_dac_adjustment_keeps_code_delta_and_domain_clamps(self):
        spec = self.specs["hsi_vrega"]
        for platform, source, block_reader in (
            ("chroma", CHROMA_GOLDEN.read_bytes(), _chroma_block),
            ("s100", S100_GOLDEN.read_bytes(), _s100_block),
        ):
            fragments = self._blocks(platform, spec)
            for fragment, render_name in zip(
                fragments, ("Hsi_Vrega_Trim", "Hsi_Vrega_Dac_Loop")
            ):
                with self.subTest(platform=platform, render_name=render_name):
                    content = str(fragment.content)
                    if isinstance(spec.search.domain, LinearRange):
                        site = "SOCKET" if platform == "chroma" else "T_SOCKET"
                        self.assertNotIn("dacArray", content)
                        self.assertIn(f"HSI_VREGA_DAC_FINAL[{site}] += 1;", content)
                        if render_name.endswith("Trim"):
                            self.assertIn(f"HSI_VREGA_DAC_FINAL[{site}] = 0;", content)
                            self.assertIn(f"HSI_VREGA_DAC_FINAL[{site}] = 7;", content)
                    else:
                        self.assertEqual(
                            _platform_bytes(content),
                            block_reader(source, render_name),
                        )

    def test_assembly_stays_blocked_without_skeleton(self):
        with self.assertRaisesRegex(StandardTrimSkeletonError, "SC.SKELETON.UNAVAILABLE"):
            request_assembly(self.spec, CHROMA_TARGET, self.schedule)

    def test_native_renderer_is_pure_and_has_no_hsi_production_branch(self):
        package = ROOT / "program_gen" / "standard_trim"
        for path in package.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            imports = {
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            }
            self.assertFalse(
                {
                    "openpyxl", "pandas", "os", "pathlib", "shutil", "subprocess",
                    "program_gen.state", "program_gen.workbook", "program_gen.platforms",
                } & imports,
                msg=path.name,
            )
            for forbidden in (
                "WorkbookReader", "hsi_8m_cp1_golden", "Golden", "legacy", "writers.py",
            ):
                self.assertNotIn(forbidden, source, msg=path.name)


if __name__ == "__main__":
    unittest.main()
