"""Interface tests for the global RUN Pattern Module."""

from __future__ import annotations

import unittest

from program_gen.core.flash_compare_plan import Operation
from program_gen.core.nm_test import NmTestMode, NmTestPlan, NmTestRun
from program_gen.core.run_pattern import (
    PatternResourceRef,
    PatternSpan,
    PatternSpanKind,
    RunPatternCompileError,
    RunPatternPlan,
)
from program_gen.platforms.chroma.run_pattern_adapter import adapt_run_pattern
from program_gen.platforms.chroma.nm_test_adapter import adapt_nm_test
from program_gen.platforms.s100.run_pattern_adapter import (
    adapt_run_pattern as adapt_s100_run_pattern,
)
from program_gen.render_plan import (
    ProgramAssembler,
    ProgramContribution,
    RenderPlanError,
    TargetKey,
)


class RunPatternModuleTests(unittest.TestCase):
    def test_full_plan_projects_to_both_platforms_and_requires_the_pattern(self):
        plan = RunPatternPlan(
            pattern=PatternResourceRef(
                name="enter_fbist_mode",
                logical_identity="pattern:enter_fbist_mode",
                ordered_labels=("START", "END"),
            ),
            span=PatternSpan.full(),
            timing_profile="TS_5MHZ",
        )

        chroma = adapt_run_pattern(plan)
        s100 = adapt_s100_run_pattern(plan)

        self.assertEqual(
            chroma.statements,
            (
                "  TEST_NUM++;",
                '  TEST_NO(TEST_NUM); DATALOG_MSG="enter_fbist_mode";',
                "  JUDGE_PAT(enter_fbist_mode,__enter_fbist_mode);",
                "",
            ),
        )
        self.assertEqual(
            chroma.resource_requires[0].relative_path,
            "pat/enter_fbist_mode.pat",
        )
        self.assertEqual(
            s100.statements,
            (
                "\tRUN_PATTERN(enter_fbist_mode:START,"
                "enter_fbist_mode:END,1,TS_5MHZ);",
            ),
        )
        self.assertEqual(
            s100.resource_requires[0].relative_path,
            "enter_fbist_mode.sd",
        )
        self.assertEqual(
            chroma.resource_requires[0].logical_identity,
            s100.resource_requires[0].logical_identity,
        )

    def test_named_segment_projects_logical_labels_to_platform_syntax(self):
        plan = RunPatternPlan(
            pattern=PatternResourceRef(
                name="fbist_page_erase_main_1st_page",
                logical_identity="pattern:fbist_page_erase_main_1st_page",
                ordered_labels=("START", "pe_1", "END"),
            ),
            span=PatternSpan.segment("START", "pe_1"),
            timing_profile="TS_5MHZ",
        )

        self.assertEqual(
            adapt_run_pattern(plan).statements,
            (
                "  TEST_NUM++;",
                '  TEST_NO(TEST_NUM); DATALOG_MSG="fbist_page_erase_main_1st_page";',
                "  JUDGE_PAT(fbist_page_erase_main_1st_page,"
                "fbist_page_erase_main_1st_page:pe_1);",
                "",
            ),
        )
        self.assertEqual(
            adapt_s100_run_pattern(plan).statements,
            (
                "\tRUN_PATTERN(fbist_page_erase_main_1st_page:START,"
                "fbist_page_erase_main_1st_page:pe_1,1,TS_5MHZ);",
            ),
        )

    def test_trailing_segment_projects_end_label_to_platform_syntax(self):
        plan = RunPatternPlan(
            pattern=PatternResourceRef(
                name="fbist_page_erase_main_1st_page",
                logical_identity="pattern:fbist_page_erase_main_1st_page",
                ordered_labels=("START", "pe_1", "END"),
            ),
            span=PatternSpan.segment("pe_1", "END"),
            timing_profile="TS_5MHZ",
        )

        self.assertEqual(
            adapt_run_pattern(plan).statements,
            (
                "  TEST_NUM++;",
                '  TEST_NO(TEST_NUM); DATALOG_MSG="fbist_page_erase_main_1st_page";',
                "  JUDGE_PAT(fbist_page_erase_main_1st_page:pe_1,"
                "__fbist_page_erase_main_1st_page);",
                "",
            ),
        )
        self.assertEqual(
            adapt_s100_run_pattern(plan).statements,
            (
                "\tRUN_PATTERN(fbist_page_erase_main_1st_page:pe_1,"
                "fbist_page_erase_main_1st_page:END,1,TS_5MHZ);",
            ),
        )

    def test_nm_test_does_not_duplicate_run_pattern_datalog_headers(self):
        def run(name):
            return RunPatternPlan(
                pattern=PatternResourceRef(
                    name=name,
                    logical_identity=f"pattern:{name}",
                    ordered_labels=("START", "END"),
                ),
                span=PatternSpan.full(),
                timing_profile="TS_5MHZ",
            )

        names = ("enter_fbist_mode", "set_all_final_vposp", "fbist_bulk_erase_nm")
        emission = adapt_nm_test(NmTestPlan(
            NmTestMode.NORMAL,
            "VCC_TYP",
            run(names[0]),
            run(names[1]),
            (NmTestRun(Operation.ERASE, run(names[2])),),
        ))
        source = "\n".join(emission.statements)

        for name in names:
            with self.subTest(name=name):
                self.assertEqual(source.count(f'DATALOG_MSG="{name}"'), 1)

    def test_run_requirement_participates_in_program_resource_closure(self):
        plan = RunPatternPlan(
            pattern=PatternResourceRef(
                name="enter_fbist_mode",
                logical_identity="pattern:enter_fbist_mode",
                ordered_labels=("START", "END"),
            ),
            span=PatternSpan.full(),
            timing_profile="TS_5MHZ",
        )
        target = TargetKey("chroma", "CP1", "LAB", "run-pattern-probe")
        contribution = ProgramContribution(
            identity="run-pattern:probe",
            target=target,
            resource_requires=adapt_run_pattern(plan).resource_requires,
        )

        with self.assertRaises(RenderPlanError) as raised:
            ProgramAssembler().assemble(target, (contribution,))

        self.assertEqual(raised.exception.code, "RP.RESOURCE.MISSING")

    def test_plan_rejects_a_segment_label_missing_from_compiled_pattern_facts(self):
        with self.assertRaisesRegex(
            RunPatternCompileError,
            "RUN.SPAN.LABEL_MISSING",
        ):
            RunPatternPlan(
                pattern=PatternResourceRef(
                    name="erase_page",
                    logical_identity="pattern:erase_page",
                    ordered_labels=("START", "END"),
                ),
                span=PatternSpan.segment("START", "pe_1"),
                timing_profile="TS_5MHZ",
            )

    def test_plan_rejects_a_reversed_segment(self):
        with self.assertRaisesRegex(
            RunPatternCompileError,
            "RUN.SPAN.ORDER_INVALID",
        ):
            RunPatternPlan(
                pattern=PatternResourceRef(
                    name="erase_page",
                    logical_identity="pattern:erase_page",
                    ordered_labels=("START", "pe_1", "END"),
                ),
                span=PatternSpan.segment("pe_1", "START"),
                timing_profile="TS_5MHZ",
            )

    def test_full_span_cannot_claim_a_partial_label_range(self):
        with self.assertRaisesRegex(
            RunPatternCompileError,
            "RUN.SPAN.FULL_INVALID",
        ):
            PatternSpan(PatternSpanKind.FULL, "START", "pe_1")

    def test_pattern_reference_rejects_an_invalid_tester_symbol(self):
        with self.assertRaisesRegex(
            RunPatternCompileError,
            "RUN.PATTERN.NAME_INVALID",
        ):
            PatternResourceRef(
                name="erase_page); POWER_OFF(",
                logical_identity="pattern:erase_page",
                ordered_labels=("START", "END"),
            )

    def test_pattern_reference_requires_a_stable_logical_identity(self):
        with self.assertRaisesRegex(
            RunPatternCompileError,
            "RUN.PATTERN.IDENTITY_MISSING",
        ):
            PatternResourceRef(
                name="erase_page",
                logical_identity=" ",
                ordered_labels=("START", "END"),
            )

    def test_pattern_reference_rejects_an_invalid_label_symbol(self):
        with self.assertRaisesRegex(
            RunPatternCompileError,
            "RUN.PATTERN.LABEL_INVALID",
        ):
            PatternResourceRef(
                name="erase_page",
                logical_identity="pattern:erase_page",
                ordered_labels=("START", "pe_1); POWER_OFF(", "END"),
            )

    def test_plan_requires_an_upstream_timing_profile(self):
        with self.assertRaisesRegex(
            RunPatternCompileError,
            "RUN.EXECUTION.TIMING_MISSING",
        ):
            RunPatternPlan(
                pattern=PatternResourceRef(
                    name="erase_page",
                    logical_identity="pattern:erase_page",
                    ordered_labels=("START", "END"),
                ),
                span=PatternSpan.full(),
                timing_profile=" ",
            )

    def test_plan_rejects_an_invalid_timing_symbol(self):
        with self.assertRaisesRegex(
            RunPatternCompileError,
            "RUN.EXECUTION.TIMING_INVALID",
        ):
            RunPatternPlan(
                pattern=PatternResourceRef(
                    name="erase_page",
                    logical_identity="pattern:erase_page",
                    ordered_labels=("START", "END"),
                ),
                span=PatternSpan.full(),
                timing_profile="TS_5MHZ); POWER_OFF(",
            )


if __name__ == "__main__":
    unittest.main()
