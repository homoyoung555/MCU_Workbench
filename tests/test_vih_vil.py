from dataclasses import FrozenInstanceError
import unittest

import pandas as pd

from flow_recipe import compile_recipe_rows
from program_gen.compiler import ProductCompiler
from program_gen.core.vih_vil import (
    KeilVihVilPlan,
    SwdVihVilPlan,
    compile_vih_vil_plans,
)
from program_gen.flow_kinds import compile_flow_rows
from program_gen.platform_program.facts import compile_platform_program_facts
from program_gen.platforms.chroma.vih_vil_renderer import render_vih_vil as render_chroma
from program_gen.platforms.s100.vih_vil_renderer import render_vih_vil as render_s100
from program_gen.render_plan import TargetKey
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER


class VihVilTests(unittest.TestCase):
    def test_formal_swd_row_compiles_to_one_shared_five_pattern_session(self):
        compilation = ProductCompiler().compile(
            WorkbookReader().read(FORMAL_MASTER)
        ).require_success()
        plans = compilation.plan.catalogs.vih_vil_plans

        self.assertEqual(tuple(plans), (187,))
        plan = plans[187]
        self.assertIsInstance(plan, SwdVihVilPlan)
        self.assertEqual(plan.typed_kind, "DC_VIH_VIL")
        self.assertEqual(plan.effective_recipe, ("VIH_VIL_TEST",))
        self.assertEqual(plan.cases, ("LL", "HH", "HL", "LH"))
        self.assertEqual(len(plan.patterns), 5)
        self.assertTrue(plan.shared_power_session)
        with self.assertRaises(FrozenInstanceError):
            plan.item = "mutated"

    def test_keil_requires_exactly_two_variants_and_compiles_typed_entry_actions(self):
        flow = pd.DataFrame([
            self._keil_row("VIHVIL1", "PA13:HL-222-W100"),
            self._keil_row("VIHVIL2", "PA13:LH-223-W100"),
        ])
        operations = compile_flow_rows(
            flow, workbook_identity="synthetic", source_sha256="0" * 64
        )
        recipe_rows = compile_recipe_rows(
            flow, pd.DataFrame(columns=("item", "addr", "description", "pattern"))
        )
        plans = compile_vih_vil_plans(
            operations,
            recipe_rows,
            flow,
            pd.DataFrame([{"CP num": "CP3", "product name": "PT104", "GET PIN": "PA13"}]),
        )

        plan = plans[0]
        self.assertIsInstance(plan, KeilVihVilPlan)
        self.assertEqual(tuple(variant.variant for variant in plan.variants), (1, 2))
        self.assertEqual(tuple(variant.pattern for variant in plan.variants), (
            "PT104_VILVIH1", "PT104_VILVIH2",
        ))
        self.assertTrue(all(variant.independent_power_session for variant in plan.variants))
        self.assertTrue(all(variant.entry_actions for variant in plan.variants))

        workbook = WorkbookReader().read(FORMAL_MASTER)
        for platform, renderer in (("chroma", render_chroma), ("s100", render_s100)):
            facts = compile_platform_program_facts(
                workbook, TargetKey(platform, "CP3", "lab", f"KEIL_{platform}")
            )
            rendered = renderer(plan, "Dc_Vihvil_Test", 12, facts)
            self.assertEqual(rendered.content.count("POWER_ON("), 2)
            self.assertEqual(rendered.content.count("POWER_OFF();"), 2)
            self.assertEqual(sum(variant.pattern in resource.relative_path for variant in plan.variants for resource in rendered.resources), 2)

    @staticmethod
    def _keil_row(sub, step):
        return {
            "CP NO": "CP3", "item": "DC_VIHVIL_Test", "type": "verify",
            "sub": sub, "mode": "keil", "Recipe": "VIH_VIL_TEST",
            "step": step, "Vcc": "VCC_TYP", "FV/FI": "/",
            "meas pin": "DC", "Hbin": 12, "Sbin": 12, "relay": "/",
        }


if __name__ == "__main__":
    unittest.main()
