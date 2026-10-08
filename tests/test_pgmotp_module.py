"""Public contract tests for the shared native PGMOTP Recipe Module."""

import unittest

from program_gen.core.otp_program import (
    PagePatternPlan,
    PgmOtpModulePlan,
    compile_pgm_otp_module_plan,
)
from program_gen.registered_recipe_modules import NATIVE_RECIPE_MODULE_REGISTRY


class PgmOtpModulePlanTests(unittest.TestCase):
    def test_compiles_one_complete_non_uid_flash_session(self):
        plan = compile_pgm_otp_module_plan(
            (PagePatternPlan("trim0", "erase_trim0", "program_trim0", "read_trim0"),),
            cp="CP2",
            power_profile="VCC_TYP",
        )

        self.assertIsInstance(plan, PgmOtpModulePlan)
        self.assertEqual(plan.cp, "CP2")
        self.assertEqual(plan.power_profile, "VCC_TYP")
        self.assertEqual(plan.enter_fbist_mode.pattern.name, "enter_fbist_mode")
        self.assertEqual(plan.set_all_final_vposp.pattern.name, "set_all_final_vposp")
        self.assertEqual(
            plan.page_program.page_operations[0].actions,
            ("ERASE", "PROGRAM", "READ_CHECK"),
        )
        self.assertEqual(
            tuple(
                step.run.pattern.name
                for step in plan.page_program.page_operations[0].steps
            ),
            ("erase_trim0", "program_trim0", "read_trim0"),
        )

    def test_uid_failure_cleanup_is_a_second_vposp_guarded_session(self):
        plan = compile_pgm_otp_module_plan(
            (PagePatternPlan(
                "uid", "erase_cp2_id", "program_cp2_id", "read_cp2_id",
                is_uid=True,
            ),),
            cp="CP2",
            power_profile="VCC_TYP",
        )

        for platform, power_on, enter, vposp, erase, failed_site in (
            (
                "chroma", "POWER_ON(VCC_TYP)",
                "JUDGE_PAT(enter_fbist_mode,__enter_fbist_mode)",
                "JUDGE_PAT(set_all_final_vposp,__set_all_final_vposp)",
                "JUDGE_PAT(erase_cp2_id,__erase_cp2_id)", "JUDGE_RESULT_MS",
            ),
            (
                "s100", "CALL_MACRO POWER_ON(_C_VCC_TYP)",
                "RUN_PATTERN(enter_fbist_mode:START,enter_fbist_mode:END",
                "RUN_PATTERN(set_all_final_vposp:START,set_all_final_vposp:END",
                "RUN_PATTERN(erase_cp2_id:START,erase_cp2_id:END", "Sys_DriverResult",
            ),
        ):
            with self.subTest(platform=platform):
                emission = NATIVE_RECIPE_MODULE_REGISTRY.emit("PGMOTP", plan, platform)
                source = "\n".join(emission.statements)
                self.assertEqual(source.count(power_on), 2)
                self.assertEqual(source.count(enter), 2)
                self.assertEqual(source.count(vposp), 2)
                self.assertEqual(source.count(erase), 2)
                self.assertIn(failed_site, source)
                self.assertEqual(
                    {item.logical_identity for item in emission.resource_requires},
                    {
                        "pattern:enter_fbist_mode",
                        "pattern:set_all_final_vposp",
                        "pattern:erase_cp2_id",
                        "pattern:program_cp2_id",
                        "pattern:read_cp2_id",
                    },
                )

    def test_mixed_pages_capture_uid_read_failure_before_later_page_results(self):
        plan = compile_pgm_otp_module_plan(
            (
                PagePatternPlan("uid", "eu", "pu", "ru", is_uid=True),
                PagePatternPlan("trim0", "e0", "p0", "r0"),
            ), cp="CP1", power_profile="VCC_TYP",
        )
        for platform, read, result, later in (
            ("chroma", "JUDGE_PAT(ru,__ru)", "JUDGE_RESULT_MS", "JUDGE_PAT(e0,__e0)"),
            ("s100", "RUN_PATTERN(ru:START,ru:END", "Sys_DriverResult", "RUN_PATTERN(e0:START,e0:END"),
        ):
            with self.subTest(platform=platform):
                source = "\n".join(NATIVE_RECIPE_MODULE_REGISTRY.emit("PGMOTP", plan, platform).statements)
                self.assertLess(source.index(read), source.index(result))
                self.assertLess(source.index(result), source.index(later))
        source = "\n".join(NATIVE_RECIPE_MODULE_REGISTRY.emit("PGMOTP", plan, "s100").statements)
        self.assertIn("Sys_ActiveSite[T_SOCKET]=uidActiveSites[T_SOCKET]", source)
        self.assertIn("if(uidReadFailed[T_SOCKET]) SYS_SetTestResult(FAIL,T_SOCKET)", source)


if __name__ == "__main__":
    unittest.main()
