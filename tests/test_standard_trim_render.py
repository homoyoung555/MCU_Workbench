"""STANDARD_TRIM native-renderer: correct architecture (translate TrimSpec, no G).

Pins the body renderer byte-for-byte against the golden function blocks for the
three measurement families, and asserts the renderer never reads global ``G``
state.  All business facts come from the compiled ``TrimSpec``; the render
context supplies only test number / Vcc / relay.
"""

from __future__ import annotations

from tests.workspace_paths import (
    CHROMA_GOLDEN_ROOT,
    FORMAL_MASTER as EXTERNAL_FORMAL_MASTER,
)

import ast
from dataclasses import replace
from pathlib import Path
import unittest

from program_gen.compiler import ProductCompiler
from program_gen.platform_render import resolve_trim_test_number
from program_gen.platforms.chroma.pattern_emitter import emit_pattern_run
from program_gen.platforms.chroma.standard_trim_renderer import (
    render_standard_trim_body,
)
from program_gen.workbook import WorkbookReader


ROOT = Path(__file__).resolve().parents[1]
FORMAL_MASTER = EXTERNAL_FORMAL_MASTER
CHROMA_GOLDEN = (
    CHROMA_GOLDEN_ROOT / "LAB" / "CHROMA"
    / "V_PCD2509V1_PY32F420A_C8_30C_V00_50_1SLAB_CP1"
    / "V_PCD2509V1_PY32F420A_C8_30C_V00_50_1SLAB_CP1.pln"
)
CHROMA_CP3_GOLDEN = next(
    (CHROMA_GOLDEN_ROOT / "LAB" / "CHROMA").glob("*CP3/*.pln")
)


def _read_gbk(path: Path) -> list[str]:
    return path.read_bytes().decode("gbk", errors="replace").splitlines()


def _golden_body(
    item: str,
    variant: str = "BISECTION",
    spec=None,
    golden: Path = CHROMA_GOLDEN,
) -> list[str]:
    lines = _read_gbk(golden)
    fname = (
        item if item.casefold().endswith("trim") else f"{item}_Trim"
    ).title()
    if variant == "FULL_SCAN":
        fname = f"{item}_Dac_Loop".title()
    start = next(i for i, l in enumerate(lines) if l.strip() == f"{fname}()")
    end = next(i for i in range(start, len(lines)) if lines[i] == "}")
    body = lines[start:end + 1]
    if spec is not None:
        for operation in (
            operation for operation in spec.operations
            if operation.kind == "DEPEND"
        ):
            pattern_row = next(
                index for index, line in enumerate(body)
                if f'DATALOG_MSG="{operation.reference}"' in line
            )
            body[pattern_row - 1:pattern_row - 1] = [
                f"  {operation.helper_name}({operation.source_symbol});",
                "",
            ]
        for operation in (
            operation for operation in spec.operations
            if operation.kind == "EXPORT"
        ):
            exit_row = next(
                index for index, line in enumerate(body)
                if f"JUDGE_PAT({spec.protocol.exit_pattern}," in line
            )
            body[exit_row + 2:exit_row + 2] = [
                "  for(I=0;I<MAX_SITE;I++)",
                "  {",
                f"    {operation.source_symbol}[I]={spec.dac_final_symbol}[I];",
                "  }",
                "",
            ]
    return body


def _without_legacy_implicit_vposp(body: list[str]) -> list[str]:
    body = list(body)
    datalog = next(
        (
            index for index, line in enumerate(body)
            if 'DATALOG_MSG="set_all_final_vposp"' in line
        ),
        None,
    )
    if datalog is not None:
        del body[datalog - 1:datalog + 3]
    return body


class StandardTrimRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()
        cls.flow = cls.workbook.dataframe("FLOW")

    def _body(self, item: str):
        spec = self._spec(item)
        test_number = resolve_trim_test_number(self.workbook, "CP1", item)
        return render_standard_trim_body(
            spec, test_number=test_number, relay="/"
        )

    def _spec(self, item: str):
        return next(
            s for s in self.compilation.plan.catalogs.trim_specs.values()
            if s.item == item
        )

    def test_frequency_trim_matches_golden(self):
        self.assertEqual(
            self._body("Hsi_10M").splitlines(),
            _golden_body("Hsi_10M", spec=self._spec("Hsi_10M")),
        )

    def test_voltage_trim_matches_golden(self):
        self.assertEqual(
            self._body("Vrefint").splitlines(),
            _golden_body("Vrefint", spec=self._spec("Vrefint")),
        )

    def test_current_trim_matches_golden(self):
        self.assertEqual(
            self._body("Iref1u").splitlines(),
            _golden_body("Iref1u", spec=self._spec("Iref1u")),
        )

    def test_full_scan_variant_matches_its_canonical_definition(self):
        spec = next(
            s for s in self.compilation.plan.catalogs.trim_specs.values()
            if s.item == "Vrefint"
        )
        body = render_standard_trim_body(
            spec,
            variant="FULL_SCAN",
            test_number=resolve_trim_test_number(self.workbook, "CP1", spec.item),
            relay="/",
        )

        self.assertEqual(
            body.splitlines(),
            _golden_body("Vrefint", "FULL_SCAN", spec=spec),
        )

    def test_all_formal_trim_variants_match_approved_business_differences(self):
        for spec in self.compilation.plan.catalogs.trim_specs.values():
            golden = CHROMA_GOLDEN if spec.cp == "CP1" else CHROMA_CP3_GOLDEN
            test_number = resolve_trim_test_number(self.workbook, spec.cp, spec.item)
            for variant in spec.search.variants:
                with self.subTest(cp=spec.cp, item=spec.item, variant=variant.kind):
                    expected = _golden_body(
                        spec.item,
                        variant.kind,
                        spec=spec,
                        golden=golden,
                    )
                    if spec.cp != "CP1":
                        expected = _without_legacy_implicit_vposp(expected)
                    actual = render_standard_trim_body(
                        spec,
                        variant=variant.kind,
                        test_number=test_number,
                        relay="/",
                    ).splitlines()
                    self.assertEqual(actual, expected)

    def test_chroma_pattern_run_emitter_has_a_family_neutral_interface(self):
        self.assertEqual(
            emit_pattern_run("pattern_a"),
            (
                "  TEST_NUM++;",
                '  TEST_NO(TEST_NUM); DATALOG_MSG="pattern_a";',
                "  JUDGE_PAT(pattern_a,__pattern_a);",
                "",
            ),
        )

    def test_renderer_never_reads_global_state(self):
        source = (
            ROOT / "program_gen" / "platforms" / "chroma"
            / "standard_trim_renderer.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertFalse(
            {"program_gen.state", "program_gen.workbook", "openpyxl"} & imports
        )
        self.assertFalse(any(
            isinstance(node, ast.Name) and node.id == "G"
            for node in ast.walk(tree)
        ))

    def test_repeated_run_actions_preserve_recipe_order_and_execution_count(self):
        """Execution preserves duplicate RUN actions; only resources may dedupe."""
        spec = next(
            s for s in self.compilation.plan.catalogs.trim_specs.values()
            if s.item == "Vrefint"
        )
        operations = (
            spec.operations[0],
            spec.operation("RUN", reference="recipe_probe_a"),
            spec.operation("RUN", reference="recipe_probe_b"),
            spec.operation("RUN", reference="recipe_probe_a"),
            *spec.operations[1:],
        )
        rendered = render_standard_trim_body(
            replace(spec, operations=operations),
            test_number=resolve_trim_test_number(self.workbook, "CP1", spec.item),
            relay="/",
        )
        run_a = "  JUDGE_PAT(recipe_probe_a,__recipe_probe_a);"
        run_b = "  JUDGE_PAT(recipe_probe_b,__recipe_probe_b);"
        self.assertEqual(rendered.count(run_a), 2)
        first_a = rendered.index(run_a)
        middle_b = rendered.index(run_b)
        second_a = rendered.index(run_a, first_a + 1)
        self.assertLess(first_a, middle_b)
        self.assertLess(middle_b, second_a)

    def test_depend_applies_the_typed_dac_source_before_running_its_pattern(self):
        body = self._body("Vrefint")

        first_dependency = (
            "  set_vref0p8_abs_trim_data(VREF0P8_ABS_DAC_FINAL);\n\n"
            "  TEST_NUM++;\n"
            '  TEST_NO(TEST_NUM); DATALOG_MSG="set_vref0p8_abs_dac";\n'
            "  JUDGE_PAT(set_vref0p8_abs_dac,__set_vref0p8_abs_dac);"
        )
        second_dependency = (
            "  set_iref1u_trim_data(IREF1U_DAC_FINAL);\n\n"
            "  TEST_NUM++;\n"
            '  TEST_NO(TEST_NUM); DATALOG_MSG="set_iref1u_dac";\n'
            "  JUDGE_PAT(set_iref1u_dac,__set_iref1u_dac);"
        )
        self.assertIn(first_dependency, body)
        self.assertIn(second_dependency, body)


if __name__ == "__main__":
    unittest.main()
