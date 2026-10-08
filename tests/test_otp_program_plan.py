import unittest

from program_gen.core.otp_program import (
    OtpProgramPlanError,
    PagePatternPlan,
    compile_cp1_trimdata_write_read_plan,
    compile_load_map_plan,
    compile_pgm_otp_plan,
)
from program_gen.core.page_image import FieldTarget


class OtpProgramPlanTests(unittest.TestCase):
    def test_pgmotp_has_fixed_physical_steps_and_uid_failure_reerase(self):
        otp_page = PagePatternPlan(
            page="trim1",
            erase_pattern="erase_trim1",
            program_pattern="program_trim1",
            read_pattern="read_trim1",
        )
        uid_page = PagePatternPlan(
            page="uid",
            erase_pattern="erase_uid",
            program_pattern="program_uid",
            read_pattern="read_uid",
            is_uid=True,
        )

        plan = compile_pgm_otp_plan((otp_page, uid_page))

        self.assertEqual(
            plan.page_operations[0].actions,
            ("ERASE", "PROGRAM", "READ_CHECK"),
        )
        self.assertEqual(
            plan.page_operations[1].actions,
            ("ERASE", "PROGRAM", "READ_CHECK", "RE_ERASE"),
        )
        self.assertEqual(plan.page_operations[1].steps[-1].site_scope, "FAILED_SITES")
        self.assertNotIn(
            "SETVPOSP",
            tuple(
                action
                for page_operation in plan.page_operations
                for action in page_operation.actions
            ),
        )

    def test_loadmap_accepts_a_buildmap_image_and_only_prepares_both_patterns(self):
        page = PagePatternPlan(
            page="trim1",
            erase_pattern="erase_trim1",
            program_pattern="program_trim1",
            read_pattern="read_trim1",
        )

        plan = compile_load_map_plan((page,), image_source="BUILDMAP")

        self.assertEqual(plan.image_source, "BUILDMAP")
        self.assertEqual(plan.target_pages, ("trim1",))
        self.assertEqual(
            plan.page_operations[0].pattern_updates,
            ("PROGRAM_PATTERN", "READ_COMPARE_PATTERN"),
        )
        self.assertFalse(plan.runs_pattern)

    def test_cp1_trimdata_write_read_selects_pages_from_field_targets(self):
        target_fields = (
            FieldTarget("VREF_TRIM", "trim1", "REG_TRIM1", 0, 6, "OTP"),
            FieldTarget("VDDK_TRIM", "uid", "UID_REG2", 8, 6, "UID"),
        )
        catalog = (
            PagePatternPlan("trim1", "e1", "p1", "r1"),
            PagePatternPlan("uid", "eu", "pu", "ru", is_uid=True),
            PagePatternPlan("trim2", "e2", "p2", "r2"),
        )

        plan = compile_cp1_trimdata_write_read_plan(
            target_fields,
            catalog,
            page_image_source="BUILDMAP",
        )

        self.assertEqual(plan.recipe, ("LOADMAP", "PGMOTP"))
        self.assertEqual(plan.load_map.target_pages, ("trim1", "uid"))
        self.assertEqual(
            tuple(operation.patterns.page for operation in plan.pgm_otp.page_operations),
            ("trim1", "uid"),
        )
        self.assertEqual(plan.pgm_otp.page_operations[1].actions[-1], "RE_ERASE")

    def test_cp1_trimdata_write_read_rejects_nondefault_recipe(self):
        catalog = (PagePatternPlan("trim1", "e1", "p1", "r1"),)
        targets = (FieldTarget("TRIM", "trim1", "REG1", 0, 4, "OTP"),)

        with self.assertRaisesRegex(OtpProgramPlanError, "LOADMAP.*PGMOTP"):
            compile_cp1_trimdata_write_read_plan(
                targets,
                catalog,
                recipe=("LOADMAP", "SETVPOSP", "PGMOTP"),
            )


if __name__ == "__main__":
    unittest.main()
