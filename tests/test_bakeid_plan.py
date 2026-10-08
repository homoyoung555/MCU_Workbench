import unittest

from program_gen.core.bakeid_plan import (
    ALL_ACTIVE_SITES,
    BakeIdPlanError,
    BakeIdOperationKind,
    compile_bakeid_plan,
)
from program_gen.core.otp_program import PagePatternPlan
from program_gen.core.persistence_recipe import PersistenceOperation, PersistencePlan


class BakeIdPlanTests(unittest.TestCase):
    def test_only_final_commit_and_pgmotp_use_the_matching_read_gate(self):
        uid = PagePatternPlan(
            page="uid",
            erase_pattern="erase_uid",
            program_pattern="program_uid",
            read_pattern="read_uid",
            is_uid=True,
        )

        plan = compile_bakeid_plan(
            cp="CP2",
            target="CP1_BAKEID",
            read_state="Read_CP1_BakeID",
            page_pattern=uid,
            current_cp_unproduced_fields=("TS_125C_VERIFY",),
        )

        self.assertEqual(
            tuple(operation.kind for operation in plan.operations),
            (
                BakeIdOperationKind.READOTPMAP,
                BakeIdOperationKind.LOADMAP,
                BakeIdOperationKind.CHECKOTP,
                BakeIdOperationKind.COMMIT,
                BakeIdOperationKind.PGMOTP,
            ),
        )
        self.assertTrue(all(
            operation.site_scope == ALL_ACTIVE_SITES
            for operation in plan.operations[:3]
        ))
        self.assertEqual(plan.commit.site_scope, "READ_CP1_BAKEID_PENDING_SITES")
        self.assertEqual(plan.pgm_otp.site_scope, "READ_CP1_BAKEID_PENDING_SITES")
        self.assertEqual(plan.load_map.read_dont_care_fields, ("TS_125C_VERIFY",))
        self.assertTrue(plan.load_map.prepares_program_pattern)
        self.assertTrue(plan.load_map.prepares_read_compare_pattern)
        self.assertTrue(plan.check_otp.runs_read_compare)
        self.assertFalse(plan.check_otp.erases_page)
        self.assertFalse(plan.check_otp.programs_page)
        self.assertEqual(
            plan.pgm_otp.program_plan.page_operations[0].actions,
            ("ERASE", "PROGRAM", "READ_CHECK", "RE_ERASE"),
        )
        self.assertEqual(
            plan.pgm_otp.program_plan.page_operations[0].steps[-1].site_scope,
            "FAILED_SITES",
        )

    def test_target_gate_and_uid_page_must_match_the_standard_protocol(self):
        uid = PagePatternPlan("uid", "e", "p", "r", is_uid=True)

        with self.assertRaisesRegex(BakeIdPlanError, "Read_CP1_BakeID"):
            compile_bakeid_plan(
                cp="CP2", target="CP1_BAKEID", read_state="Read_CP2_BakeID",
                page_pattern=uid,
            )
        with self.assertRaisesRegex(BakeIdPlanError, "UID Page"):
            compile_bakeid_plan(
                cp="CP2", target="CP1_BAKEID", read_state="Read_CP1_BakeID",
                page_pattern=PagePatternPlan("trim1", "e", "p", "r"),
            )

    def test_compiles_the_uid_chain_from_persistence_plan_and_preserves_capture_dedup(self):
        persistence = PersistencePlan(
            cp="CP2",
            operations=(
                PersistenceOperation("READOTPMAP", 20, ("uid",), ()),
                PersistenceOperation("LOADMAP", 20, ("uid",), ("uid",)),
                PersistenceOperation("CHECKOTP", 20, ("uid",), ("uid",)),
                PersistenceOperation("COMMIT", 20, ("uid",), ("uid",)),
                PersistenceOperation("PGMOTP", 20, ("uid",), ("uid",)),
            ),
        )

        plan = compile_bakeid_plan(
            cp="CP2", target="CP1_BAKEID", read_state="Read_CP1_BakeID",
            page_pattern=PagePatternPlan("uid", "e", "p", "r", is_uid=True),
            persistence_plan=persistence, excel_row=20,
        )

        self.assertEqual(plan.read_otp_map.requested_pages, ("uid",))
        self.assertEqual(plan.read_otp_map.effective_pages, ())

        wrong = PersistencePlan(cp="CP2", operations=persistence.operations[:-1])
        with self.assertRaisesRegex(BakeIdPlanError, "READOTPMAP.*PGMOTP"):
            compile_bakeid_plan(
                cp="CP2", target="CP1_BAKEID", read_state="Read_CP1_BakeID",
                page_pattern=PagePatternPlan("uid", "e", "p", "r", is_uid=True),
                persistence_plan=wrong, excel_row=20,
            )


if __name__ == "__main__":
    unittest.main()
