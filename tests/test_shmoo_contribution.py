from __future__ import annotations

from tests.workspace_paths import FORMAL_MASTER as EXTERNAL_FORMAL_MASTER

from dataclasses import replace
from pathlib import Path
import unittest

from program_gen.compiler import ProductCompiler
from program_gen.core.commit_shmoo import CommitShmooPlan
from program_gen.core.shmoo import ShmooPlan, ShmooPoint
from program_gen.core.shmoo_contribution import ShmooContributionError
from program_gen.core.shmoo_contribution import compile_shmoo_contribution
from program_gen.platform_program.facts import compile_platform_program_facts
from program_gen.standard_verify_assembly import compile_standard_verify_assembly
from program_gen.render_plan import (
    RenderSymbolRef,
    ResourceRequirement,
    ScheduleEntryContribution,
    SymbolRequirement,
    TargetKey,
    TestDefinitionContribution,
)
from program_gen.workbook import WorkbookReader
from program_gen.typed_kind_registry import TypedKindContext


ROOT = Path(__file__).resolve().parents[1]
FORMAL_MASTER = EXTERNAL_FORMAL_MASTER


class ShmooContributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()

    def test_formal_four_target_projections_reuse_canonical_identities(self):
        catalogs = self.compilation.plan.catalogs
        self.assertEqual(catalogs.shmoo_plans, {})
        self.assertEqual(catalogs.commit_shmoo_plans, {})
        scans = {
            row: catalogs.standard_verify_plans[row].shmoo
            for row in (40, 110)
        }
        self.assertEqual(tuple(len(plan.points) for plan in scans.values()), (8, 3))
        self.assertEqual(
            tuple(plan.consumer_module for plan in scans.values()),
            ("ENTER", "ENTER"),
        )
        for cp, rows in (("CP1", (42,)), ("CP2", (112, 113, 114))):
            definition = next(
                item for item in self.compilation.for_cp(cp).canonical_schedule.definitions
                if item.source_rows == rows
            )
            self.assertEqual(definition.render_name, "Mr_Vddd_Dc_Shmoo")

    def test_declares_plan_proven_body_helper_results_and_patterns(self):
        self.assertEqual(self.compilation.plan.catalogs.shmoo_plans, {})

    def test_formal_standard_verify_shmoo_uses_one_runtime_session_loop(self):
        for platform in ("chroma", "s100"):
            for cp, row, steps in (("CP1", 40, "0,1,2,3,4,5,6,7"),
                                   ("CP2", 110, "0,3,7")):
                with self.subTest(platform=platform, cp=cp):
                    target = TargetKey(platform, cp, "lab", f"SHMOO_{platform}_{cp}")
                    facts = compile_platform_program_facts(
                        self.workbook, target
                    )
                    plan = self.compilation.plan.catalogs.standard_verify_plans[row]
                    assembly = compile_standard_verify_assembly(
                        (plan,), TypedKindContext(self.compilation, target, facts, None)
                    )
                    body = assembly.bodies[0].fragment.content.decode("gbk")
                    count = len(plan.shmoo.points)
                    self.assertIn(f"for(int shmoo_index=0;shmoo_index<{count};shmoo_index++)", body)
                    power_on = "POWER_ON(" if platform == "chroma" else "CALL_MACRO POWER_ON("
                    power_off = "POWER_OFF();" if platform == "chroma" else "CALL_MACRO POWER_OFF();"
                    self.assertEqual(body.count(power_on), 1)
                    self.assertEqual(body.count(power_off), 1)
                    if platform == "chroma":
                        self.assertIn(f"int shmoo_step[{count}]={{{steps}}};", body)
                        self.assertEqual(body.count("JUDGE_V_PPMU("), 1)
                        self.assertIn("sprintf(shmoo_log,\"%s\",shmoo_alias[shmoo_index]);", body)
                    else:
                        self.assertNotIn("int shmoo_step[", body)
                        self.assertEqual(body.count("switch(shmoo_index)"), 2)
                        self.assertEqual(body.count("LOGIC_PPMU_MV("), count)

    def test_rejects_commit_shmoo_until_its_resource_contract_is_typed(self):
        target = TargetKey("s100", "CP1", "formal", "V_TEST_CP1")
        schedule = self.compilation.for_cp("CP1").canonical_schedule

        with self.assertRaisesRegex(
            ShmooContributionError, "SHC.PLAN.COMMIT_UNSUPPORTED"
        ):
            compile_shmoo_contribution(
                CommitShmooPlan("CP1", (), ()), target, schedule
            )

    def test_rejects_plan_target_and_schedule_ownership_mismatches(self):
        point = ShmooPoint(40, "dac0", "Mr_VDDD_DC_dac0", 0, 1.2, 1.2, 1.2, 1.2, 1.2)
        plan = ShmooPlan(
            40, "CP1", "Mr_VDDD_DC", "fbist", "enter_mr_vddd_dc_verify",
            "001", 3, "VCC_TYP", "TP", "0uA", "V", 24, None, False,
            (point,),
        )
        schedule = self.compilation.for_cp("CP1").canonical_schedule
        target = TargetKey("s100", "CP1", "formal", "V_TEST_CP1")
        cases = (
            (
                plan,
                TargetKey("s100", "CP2", "formal", "V_TEST_CP2"),
                schedule,
                "SHC.TARGET.CP_MISMATCH",
            ),
            (
                plan,
                target,
                replace(schedule, cp="CP2"),
                "SHC.SCHEDULE.CP_MISMATCH",
            ),
            (
                replace(plan, mode="hex"),
                target,
                schedule,
                "SHC.PLAN.MODE",
            ),
        )
        for candidate, candidate_target, candidate_schedule, code in cases:
            with self.subTest(code=code), self.assertRaisesRegex(
                ShmooContributionError, code
            ):
                compile_shmoo_contribution(
                    candidate, candidate_target, candidate_schedule
                )


if __name__ == "__main__":
    unittest.main()
