import unittest

import pandas as pd

from flow_recipe import (
    FlowCompileError,
    RecipeCall,
    ResolvedRecipeCall,
    compile_flow,
    compile_recipe_program,
    compile_recipe_rows,
    compile_dac_write_plan_set,
    compile_result_export_plan_set,
    dynamic_recipe_enter_operations,
    parse_recipe,
    recipe_setup_operations,
)
from preflight.reader import Cell
from preflight.report import ERROR, WARN
from preflight.rules import check_flow_recipe
from program_gen.core.sram_capture import SramCaptureArgument


class FlowRecipeTests(unittest.TestCase):
    def test_sram_capture_preserves_one_canonical_argument(self):
        call = parse_recipe("sram_capture(0x3000, 22X16 @ 2)")[0]

        self.assertEqual(call.name, "SRAM_CAPTURE")
        self.assertEqual(call.argument, "0X3000,22x16@2")
        self.assertIsInstance(call.sram_capture, SramCaptureArgument)
        self.assertEqual(
            (call.sram_capture.base, call.sram_capture.count,
             call.sram_capture.width, call.sram_capture.stride),
            (0x3000, 22, 16, 2),
        )

    def test_sram_capture_defaults_stride_to_four(self):
        call = parse_recipe("SRAM_CAPTURE(12288,22x16)")[0]

        self.assertEqual(call.argument, "0X3000,22x16@4")
        self.assertEqual(call.sram_capture.stride, 4)

    def test_sram_capture_typed_argument_survives_recipe_resolution(self):
        flow = pd.DataFrame([{
            "CP NO": "CP3", "item": "Adc_Test", "type": "verify",
            "sub": "ADC1", "Recipe": "SRAM_CAPTURE(0X3000,22x16@2)",
        }])
        pattern = pd.DataFrame(columns=("item", "addr", "description", "pattern"))

        operation = compile_recipe_program(
            flow, pattern
        ).functions[0].rows[0].operations[0]

        self.assertEqual(operation.argument, "0X3000,22x16@2")
        self.assertEqual(
            operation.sram_capture,
            parse_recipe("SRAM_CAPTURE(0X3000,22x16@2)")[0].sram_capture,
        )

    def test_sram_capture_contract_errors_are_flow_compile_errors(self):
        for invalid in (
            "SRAM_CAPTURE",
            "SRAM_CAPTURE(0X10000,1x16)",
            "SRAM_CAPTURE(0X3000,0x16)",
            "SRAM_CAPTURE(0X3000,1x33)",
            "SRAM_CAPTURE(0X3000,1x16@0)",
            "SRAM_CAPTURE(0XFFFF,1x9)",
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(FlowCompileError):
                    parse_recipe(invalid)

    def test_recipe_call_cannot_hold_conflicting_sram_capture_forms(self):
        typed = parse_recipe("SRAM_CAPTURE(0X3000,1x16)")[0].sram_capture

        for call_type in (RecipeCall, ResolvedRecipeCall):
            with self.subTest(call_type=call_type.__name__, conflict="raw"):
                with self.assertRaises(FlowCompileError):
                    call_type(
                        name="SRAM_CAPTURE", argument="bogus", sram_capture=typed
                    )
            with self.subTest(call_type=call_type.__name__, conflict="module"):
                with self.assertRaises(FlowCompileError):
                    call_type(name="RUN", argument="pattern", sram_capture=typed)
            with self.subTest(call_type=call_type.__name__, conflict="missing_typed"):
                with self.assertRaises(FlowCompileError):
                    call_type(name="SRAM_CAPTURE", argument=typed.canonical_spec)

    def test_persistence_modules_parse_in_order_with_uid_page_arguments(self):
        calls = parse_recipe(
            "BUILDMAP-READOTPMAP(uid)-LOADMAP(UID)-SETVPOSP-"
            "NMLOOP-CHECKOTP(Uid)-PGMOTP(UID)-BUILDUID"
        )

        self.assertEqual([call.name for call in calls], [
            "BUILDMAP", "READOTPMAP", "LOADMAP", "SETVPOSP",
            "NMLOOP", "CHECKOTP", "PGMOTP", "BUILDUID",
        ])
        self.assertEqual(
            [calls[index].argument for index in (1, 2, 5, 6)],
            ["UID", "UID", "UID", "UID"],
        )

    def test_commit_parses_typed_field_assignments_without_evaluating_rhs(self):
        call = parse_recipe(
            "COMMIT(F_DEC=15,F_HEX=0x0F,F_BIN=0b0011,F_STEP=step,F_VAR=VREF_EXPORT)"
        )[0]

        self.assertEqual(call.name, "COMMIT")
        self.assertIsNone(call.argument)
        self.assertEqual(
            [(assignment.field, assignment.value.kind, assignment.value.token)
             for assignment in call.assignments],
            [
                ("F_DEC", "DECIMAL", "15"),
                ("F_HEX", "HEX", "0x0F"),
                ("F_BIN", "BINARY", "0b0011"),
                ("F_STEP", "STEP", "STEP"),
                ("F_VAR", "VARIABLE", "VREF_EXPORT"),
            ],
        )

    def test_bare_commit_is_valid_and_commit_rejects_ambiguous_assignments(self):
        call = parse_recipe("COMMIT")[0]

        self.assertEqual(call.assignments, ())
        for invalid in (
            "COMMIT()",
            "COMMIT(FIELD=STEP+1)",
            "COMMIT(FIELD=-1)",
            "COMMIT(FIELD=1.5)",
            "COMMIT(FIELD=0xGG)",
            "COMMIT(FIELD=1,field=2)",
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(FlowCompileError):
                    parse_recipe(invalid)

    def test_commit_assignments_survive_platform_neutral_recipe_compilation(self):
        flow = pd.DataFrame([{
            "CP NO": "CP2", "item": "Trimdata_Rewrite", "type": "write",
            "sub": "/", "Recipe": "COMMIT(FIELD=STEP,OTHER=0x2)-PGMOTP",
        }])
        pattern = pd.DataFrame(columns=("item", "addr", "description", "pattern"))

        operations = compile_recipe_program(flow, pattern).functions[0].rows[0].operations

        self.assertEqual([operation.name for operation in operations], ["COMMIT", "PGMOTP"])
        self.assertEqual(
            [(assignment.field, assignment.value.kind, assignment.value.token)
             for assignment in operations[0].assignments],
            [("FIELD", "STEP", "STEP"), ("OTHER", "HEX", "0x2")],
        )

    def test_persistence_module_argument_ownership_is_explicit(self):
        for invalid in (
            "BUILDMAP(UID)",
            "BUILDUID(UID)",
            "SETVPOSP(UID)",
            "NMLOOP(UID)",
            "COMMIT(UID)",
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(FlowCompileError):
                    parse_recipe(invalid)

        for invalid in (
            "READOTPMAP(TRIM1)",
            "LOADMAP(ALL)",
            "CHECKOTP(OTP)",
            "PGMOTP(UID,TRIM1)",
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(FlowCompileError):
                    parse_recipe(invalid)

    def test_export_parses_context_default_and_named_formats(self):
        calls = parse_recipe(
            "JUDGE-EXPORT-EXPORT(FORMAT=raw)-EXPORT(FORMAT=bcd16_mv)-EXPORT(FORMAT=adc12_3v3)"
        )

        self.assertEqual([call.name for call in calls], [
            "JUDGE", "EXPORT", "EXPORT", "EXPORT", "EXPORT",
        ])
        self.assertIsNone(calls[1].named_parameter("FORMAT"))
        self.assertEqual(calls[2].named_parameter("FORMAT"), "RAW")
        self.assertEqual(calls[3].named_parameter("FORMAT"), "BCD16_MV")
        self.assertEqual(calls[4].named_parameter("FORMAT"), "ADC12_3V3")

    def test_explicit_export_compiles_raw_result_plan_for_uid_no(self):
        flow = pd.DataFrame([
            {
                "CP NO": "CP2", "item": "Vrefint", "type": "verify", "sub": "/",
                "Recipe": "JUDGE-EXPORT", "UID": "no",
            }
        ])

        pattern = pd.DataFrame(columns=("item", "addr", "description", "pattern"))
        rows = compile_recipe_rows(flow, pattern)
        plans = compile_result_export_plan_set(flow, rows, "CP2")
        plan = plans.for_row(0)

        self.assertEqual(plan.format, "RAW")
        self.assertEqual(plan.source_kind, "MEASUREMENT")
        self.assertEqual(plan.symbol, "VREFINT_EXPORT")
        self.assertTrue(plan.explicit)
        self.assertFalse(plan.implied_by_uid)
        self.assertEqual(plans.global_declarations, (("double", "VREFINT_EXPORT"),))

    def test_uid_implicitly_exports_with_existing_default_encoding(self):
        flow = pd.DataFrame([
            {
                "CP NO": "CP1", "item": "Vrefint", "type": "verify", "sub": "/",
                "Recipe": "JUDGE", "UID": "yes",
            },
            {
                "CP NO": "CP1", "item": "Ts_30C", "type": "verify", "sub": "/",
                "Recipe": "JUDGE", "UID": "yes",
            },
        ])

        pattern = pd.DataFrame(columns=("item", "addr", "description", "pattern"))
        rows = compile_recipe_rows(flow, pattern)
        plans = compile_result_export_plan_set(flow, rows, "CP1")

        self.assertEqual(plans.for_row(0).format, "BCD16_MV")
        self.assertEqual(plans.for_row(0).symbol, "VREFINT_EXPORT")
        self.assertEqual(plans.for_row(1).format, "ADC12_3V3")
        self.assertEqual(plans.for_row(1).symbol, "TS_30C_EXPORT")
        self.assertTrue(plans.for_row(0).implied_by_uid)

    def test_trim_uid_implicitly_exports_raw_dac_snapshot_with_sub(self):
        flow = pd.DataFrame([{
            "CP NO": "CP1", "item": "Hsi_8M", "type": "trim", "sub": "fast/1",
            "Recipe": "ENTER-TRIM-JUDGE", "UID": "yes",
        }])
        pattern = pd.DataFrame([
            {"item": "Hsi_8M", "addr": "0", "description": "", "pattern": "trim mode"},
            {"item": None, "addr": "0", "description": "3,DAC[3:0]=0000*", "pattern": "trim dac"},
        ])

        rows = compile_recipe_rows(flow, pattern)
        plan = compile_result_export_plan_set(flow, rows, "CP1").for_row(0)

        self.assertEqual(plan.format, "RAW")
        self.assertEqual(plan.source_kind, "DAC_FINAL")
        self.assertEqual(plan.symbol, "HSI_8M_FAST_1_DAC_EXPORT")
        self.assertEqual(plan.c_type, "int")

    def test_explicit_export_format_overrides_uid_default_without_duplication(self):
        flow = pd.DataFrame([
            {
                "CP NO": "CP1", "item": "Vrefint", "type": "verify", "sub": "/",
                "Recipe": "JUDGE-EXPORT(FORMAT=RAW)", "UID": "yes",
            }
        ])
        pattern = pd.DataFrame(columns=("item", "addr", "description", "pattern"))

        rows = compile_recipe_rows(flow, pattern)
        plans = compile_result_export_plan_set(flow, rows, "CP1")

        self.assertEqual(len(plans.plans), 1)
        self.assertEqual(plans.for_row(0).format, "RAW")
        self.assertEqual(plans.for_row(0).symbol, "VREFINT_EXPORT")
        self.assertTrue(plans.for_row(0).explicit)
        self.assertTrue(plans.for_row(0).implied_by_uid)

    def test_export_requires_one_judge_before_it_and_rejects_unsupported_formats(self):
        invalid_recipes = (
            "EXPORT-JUDGE",
            "JUDGE-EXPORT-EXPORT",
            "EXPORT",
        )
        pattern = pd.DataFrame(columns=("item", "addr", "description", "pattern"))
        for recipe in invalid_recipes:
            with self.subTest(recipe=recipe):
                flow = pd.DataFrame([{
                    "CP NO": "CP1", "item": "Vrefint", "type": "verify", "sub": "/",
                    "Recipe": recipe, "UID": "no",
                }])
                with self.assertRaisesRegex(FlowCompileError, "EXPORT"):
                    compile_recipe_rows(flow, pattern)

        with self.assertRaises(FlowCompileError):
            parse_recipe("JUDGE-EXPORT(FORMAT=HEX)")

    def test_standard_verify_allows_multiple_judges_with_one_export_per_judge(self):
        flow = pd.DataFrame([{
            "CP NO": "CP1", "item": "Vrefint", "type": "verify", "sub": "/",
            "mode": "fbist",
            "Recipe": "ENTER-JUDGE-EXPORT-DAC_WRITE-JUDGE-EXPORT",
        }])

        row = compile_flow(flow).functions[0].rows[0]

        self.assertEqual(
            tuple(call.name for call in row.recipe),
            ("ENTER", "JUDGE", "EXPORT", "DAC_WRITE", "JUDGE", "EXPORT"),
        )

    def test_recipe_sequence_preserves_order_and_binary_width(self):
        calls = parse_recipe("ENTER(010)-DAC_WRITE(0)-JUDGE")

        self.assertEqual([call.name for call in calls], ["ENTER", "DAC_WRITE", "JUDGE"])
        self.assertEqual(calls[0].argument, "010")
        self.assertEqual(calls[1].argument, "0")

    def test_named_wait_parameters_are_canonicalized_and_owned_by_modules(self):
        calls = parse_recipe(
            "ENTER(wait=3ms)-TRIM(fwait=5MS, swait=20us)-JUDGE(FWAIT=0MS)"
        )

        self.assertEqual(calls[0].time_parameter("WAIT").canonical, "3MS")
        self.assertEqual(calls[1].time_parameter("FWAIT").canonical, "5MS")
        self.assertEqual(calls[1].time_parameter("SWAIT").canonical, "20US")
        self.assertEqual(calls[2].time_parameter("FWAIT").canonical, "0MS")

    def test_shmoo_step_is_an_execution_parameter_on_enter_or_dac_write(self):
        calls = parse_recipe(
            "ENTER(SHMOO=step)-DAC_WRITE(SHMOO=STEP)-JUDGE(PF=NO)"
        )

        self.assertEqual(calls[0].named_parameter("SHMOO"), "STEP")
        self.assertEqual(calls[1].named_parameter("SHMOO"), "STEP")
        self.assertEqual(calls[2].named_parameter("PF"), "NO")
        with self.assertRaisesRegex(FlowCompileError, "不接受参数 SHMOO"):
            parse_recipe("RUN(foo,SHMOO=STEP)")

    def test_binary_enter_argument_can_coexist_with_named_wait(self):
        call = parse_recipe("ENTER(010,WAIT=3MS)")[0]

        self.assertEqual(call.argument, "010")
        self.assertEqual(call.time_parameter("WAIT").canonical, "3MS")

    def test_dac_adj_rule_can_coexist_with_set_and_force_waits(self):
        call = parse_recipe("DAC_ADJ(<1.16:+1,SWAIT=20US,FWAIT=3MS)")[0]

        self.assertEqual(call.name, "DAC_ADJ")
        self.assertEqual(call.argument, "<1.16:+1")
        self.assertEqual(call.time_parameter("SWAIT").canonical, "20US")
        self.assertEqual(call.time_parameter("FWAIT").canonical, "3MS")

    def test_depend_accepts_one_logical_item_name(self):
        call = parse_recipe("DEPEND(Hsi_Vrega)")[0]

        self.assertEqual(call.name, "DEPEND")
        self.assertEqual(call.argument, "Hsi_Vrega")

    def test_judge_owns_final_set_and_force_waits(self):
        call = parse_recipe("JUDGE(SWAIT=20US,FWAIT=3MS)")[0]

        self.assertEqual(call.time_parameter("SWAIT").canonical, "20US")
        self.assertEqual(call.time_parameter("FWAIT").canonical, "3MS")

    def test_wait_parameters_reject_bad_units_duplicates_and_wrong_owners(self):
        invalid = (
            "ENTER(WAIT=3)",
            "ENTER(WAIT=3S)",
            "ENTER(SWAIT=3MS)",
            "TRIM(WAIT=3MS)",
            "TRIM(FWAIT=3MS,FWAIT=4MS)",
            "JUDGE(WAIT=3MS)",
        )
        for recipe in invalid:
            with self.subTest(recipe=recipe):
                with self.assertRaises(FlowCompileError):
                    parse_recipe(recipe)

    def test_module_names_are_canonicalized_but_unknown_names_are_rejected(self):
        self.assertEqual(parse_recipe(" enter(001) - judge ")[0].name, "ENTER")

        with self.assertRaisesRegex(FlowCompileError, "未知 Recipe 模块"):
            parse_recipe("ENTER(001)-GUESS")

    def test_newlines_are_equivalent_to_hyphen_separators(self):
        horizontal = parse_recipe("ENTER(010)-DAC_WRITE(0)-JUDGE")
        vertical = parse_recipe("ENTER(010)\r\nDAC_WRITE(0)\n\nJUDGE")

        self.assertEqual(vertical, horizontal)

    def test_positional_argument_remains_binary_only(self):
        for invalid in ("ENTER(2)", "ENTER(level=010)", "ENTER()"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(FlowCompileError):
                    parse_recipe(invalid)

    def test_modules_reject_arguments_they_do_not_own(self):
        with self.assertRaisesRegex(FlowCompileError, "JUDGE 不接受参数"):
            parse_recipe("JUDGE(0)")

        with self.assertRaisesRegex(FlowCompileError, "未知 Recipe 模块: JUDGE_DAC"):
            parse_recipe("JUDGE_DAC")

    def test_run_accepts_a_named_pattern_reference(self):
        call = parse_recipe("RUN(external_ready_pattern)")[0]

        self.assertEqual(call.name, "RUN")
        self.assertEqual(call.argument, "external_ready_pattern")

        with self.assertRaisesRegex(FlowCompileError, "RUN 必须填写 Pattern 名"):
            parse_recipe("RUN")

    def test_enter_role_is_a_named_override_not_a_time_parameter(self):
        call = parse_recipe("ENTER(010,ROLE=TRIM,WAIT=3MS)")[0]

        self.assertEqual(call.argument, "010")
        self.assertEqual(call.named_parameter("ROLE"), "TRIM")
        self.assertEqual(call.time_parameter("WAIT").canonical, "3MS")

    def test_compile_groups_subs_into_one_item_type_function_in_flow_order(self):
        frame = pd.DataFrame(
            [
                {"CP NO": "CP1", "item": "MRVDDD", "type": "Verify", "sub": "VDDD", "Recipe": "ENTER(001)-JUDGE"},
                {"CP NO": "CP1", "item": "MRVDDD", "type": "Verify", "sub": "VDDA", "Recipe": "ENTER(010)\nJUDGE"},
                {"CP NO": "CP1", "item": "MRVDDD", "type": "Shmoo", "sub": "level0", "Recipe": "ENTER(000)-JUDGE"},
            ]
        )

        program = compile_flow(frame)

        self.assertEqual(len(program.functions), 2)
        self.assertEqual(program.functions[0].key.item, "MRVDDD")
        self.assertEqual(program.functions[0].key.flow_type, "verify")
        self.assertEqual([row.sub for row in program.functions[0].rows], ["VDDD", "VDDA"])
        self.assertEqual(program.functions[1].key.flow_type, "shmoo")

    def test_exact_cp_item_type_sub_duplicate_is_rejected_even_if_recipe_differs(self):
        frame = pd.DataFrame(
            [
                {"CP NO": "CP1", "item": "MRVDDD", "type": "Verify", "sub": "VDDD", "Recipe": "ENTER(001)-JUDGE"},
                {"CP NO": "CP1", "item": "MRVDDD", "type": "Verify", "sub": "VDDD", "Recipe": "ENTER(010)-JUDGE"},
            ]
        )

        with self.assertRaisesRegex(FlowCompileError, "重复 FLOW 行身份"):
            compile_flow(frame)

    def test_same_cp_item_type_group_must_be_contiguous(self):
        frame = pd.DataFrame(
            [
                {"CP NO": "CP1", "item": "MRVDDD", "type": "Verify", "sub": "VDDD", "Recipe": "JUDGE"},
                {"CP NO": "CP1", "item": "HSI", "type": "Verify", "sub": "8M", "Recipe": "JUDGE"},
                {"CP NO": "CP1", "item": "MRVDDD", "type": "Verify", "sub": "VDDA", "Recipe": "JUDGE"},
            ]
        )

        with self.assertRaisesRegex(FlowCompileError, "必须连续"):
            compile_flow(frame)

    def test_same_item_type_in_different_cp_is_not_one_function(self):
        frame = pd.DataFrame(
            [
                {"CP NO": "CP1", "item": "MRVDDD", "type": "Verify", "sub": "VDDD", "Recipe": "JUDGE"},
                {"CP NO": "CP2", "item": "MRVDDD", "type": "Verify", "sub": "VDDD", "Recipe": "JUDGE"},
            ]
        )

        program = compile_flow(frame)

        self.assertEqual([plan.key.cp for plan in program.functions], ["CP1", "CP2"])

    def test_preflight_reports_all_bad_recipe_cells_and_keeps_group_validation_running(self):
        reader = _RecipeReader(
            [
                (2, "CP1", "MRVDDD", "Verify", "VDDD", "ENTER(2)-JUDGE"),
                (3, "CP1", "MRVDDD", "Verify", "VDDD", "JUDGE"),
            ]
        )
        findings = []

        check_flow_recipe(reader, findings)

        self.assertEqual([finding.severity for finding in findings], [ERROR, ERROR])
        self.assertIn("Recipe 语法非法", findings[0].message)
        self.assertIn("重复 FLOW 行身份", findings[1].message)

    def test_preflight_summarizes_blank_recipe_migration_without_one_warning_per_row(self):
        reader = _RecipeReader(
            [
                (2, "CP1", "MRVDDD", "Verify", "VDDD", None),
                (3, "CP1", "MRVDDD", "Verify", "VDDA", None),
            ]
        )
        findings = []

        check_flow_recipe(reader, findings)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, WARN)
        self.assertIn("2 行为空", findings[0].message)

    def test_recipe_program_resolves_default_argument_trim_loop_and_dac_final_sources(self):
        flow = pd.DataFrame(
            [
                {"CP NO": "CP1", "item": "Mr_VDDD_DC", "type": "trim", "sub": "/", "Recipe": "ENTER-TRIM-JUDGE"},
                {"CP NO": "CP1", "item": "Mr_VDDD_DC", "type": "verify", "sub": "/", "Recipe": "ENTER(010)-DAC_WRITE-JUDGE"},
            ]
        )
        pattern = _mrvddd_pattern_frame()

        program = compile_recipe_program(flow, pattern)

        trim_ops = program.functions[0].rows[0].operations
        self.assertEqual([(op.name, op.value_source, op.value) for op in trim_ops], [
            ("ENTER", "DEFAULT", "001"),
            ("TRIM", "TRIM_LOOP", None),
                ("JUDGE", "EFFECTIVE_DAC", None),
        ])
        verify_ops = program.functions[1].rows[0].operations
        self.assertEqual([(op.name, op.value_source, op.value) for op in verify_ops], [
            ("ENTER", "ARGUMENT", "010"),
            ("DAC_WRITE", "DAC_FINAL", None),
            ("JUDGE", None, None),
        ])

    def test_dac_write_reuses_live_dac_and_existing_set_helper_when_cp_has_trim(self):
        flow = pd.DataFrame(
            [
                {"CP NO": "CP1", "item": "Mr_VDDD_DC", "type": "trim", "sub": "/",
                 "Recipe": "ENTER-TRIM-JUDGE"},
                {"CP NO": "CP1", "item": "Mr_VDDD_DC", "type": "verify", "sub": "/",
                 "Recipe": "ENTER(ROLE=TRIM)-DAC_WRITE-JUDGE"},
            ]
        )

        operation = compile_recipe_program(
            flow, _mrvddd_pattern_frame()
        ).functions[1].rows[0].operations[1]

        self.assertEqual(operation.name, "DAC_WRITE")
        self.assertEqual(operation.value_source, "DAC_FINAL")
        self.assertFalse(operation.requires_set_helper)
        self.assertEqual(operation.dynamic_field.width, 4)

        plan_set = compile_dac_write_plan_set(
            compile_recipe_rows(flow, _mrvddd_pattern_frame()), "CP1"
        )
        plan = plan_set.for_row(1)
        self.assertEqual(plan.value_source, "DAC_FINAL")
        self.assertFalse(plan.needs_global_variable)
        self.assertFalse(plan.needs_set_helper)
        self.assertEqual(plan_set.global_symbols, ())
        self.assertEqual(plan_set.helper_plans, ())

    def test_dac_write_requires_register_restore_and_set_helper_without_cp_trim(self):
        flow = pd.DataFrame(
            [
                {"CP NO": "CP1", "item": "Mr_VDDD_DC", "type": "trim", "sub": "/",
                 "Recipe": "ENTER-TRIM-JUDGE"},
                {"CP NO": "CP2", "item": "Mr_VDDD_DC", "type": "verify", "sub": "/",
                 "Recipe": "ENTER(ROLE=TRIM)-DAC_WRITE-JUDGE"},
            ]
        )

        operation = compile_recipe_program(
            flow, _mrvddd_pattern_frame()
        ).functions[1].rows[0].operations[1]

        self.assertEqual(operation.value_source, "ADDR_MAP")
        self.assertTrue(operation.requires_set_helper)

        plan_set = compile_dac_write_plan_set(
            compile_recipe_rows(flow, _mrvddd_pattern_frame()), "CP2"
        )
        plan = plan_set.for_row(1)
        self.assertEqual(plan.item, "Mr_VDDD_DC")
        self.assertEqual(plan.dac_symbol, "MR_VDDD_DC_DAC_FINAL")
        self.assertEqual(plan.pattern_name, "set_mr_vddd_dc_dac")
        self.assertEqual(plan.helper_name, "set_mr_vddd_dc_trim_data")
        self.assertEqual(plan.value_source, "ADDR_MAP")
        self.assertTrue(plan.needs_global_variable)
        self.assertTrue(plan.needs_set_helper)
        self.assertEqual(plan.field_width, 4)
        self.assertEqual(plan_set.global_symbols, ("MR_VDDD_DC_DAC_FINAL",))
        self.assertEqual(plan_set.helper_plans, (plan,))

    def test_blank_legacy_trim_row_still_supplies_dac_write_in_same_cp(self):
        flow = pd.DataFrame(
            [
                {"CP NO": "CP1", "item": "Mr_VDDD_DC", "type": "trim", "sub": "/",
                 "Recipe": None},
                {"CP NO": "CP1", "item": "Mr_VDDD_DC", "type": "verify", "sub": "/",
                 "Recipe": "ENTER(ROLE=TRIM)-DAC_WRITE-JUDGE"},
            ]
        )

        rows = compile_recipe_rows(flow, _mrvddd_pattern_frame())
        operation = rows[1].operations[1]

        self.assertEqual(operation.value_source, "DAC_FINAL")
        self.assertFalse(operation.requires_set_helper)

    def test_dac_write_fixed_binary_uses_argument_without_register_restore(self):
        flow = pd.DataFrame(
            [{"CP NO": "CP2", "item": "Mr_VDDD_DC", "type": "verify", "sub": "/",
              "Recipe": "ENTER(ROLE=TRIM)-DAC_WRITE(0011)-JUDGE"}]
        )

        operation = compile_recipe_program(
            flow, _mrvddd_pattern_frame()
        ).functions[0].rows[0].operations[1]

        self.assertEqual(operation.value_source, "ARGUMENT")
        self.assertEqual(operation.value, "0011")
        self.assertTrue(operation.requires_set_helper)

        plan_set = compile_dac_write_plan_set(
            compile_recipe_rows(flow, _mrvddd_pattern_frame()), "CP2"
        )
        plan = plan_set.for_row(0)
        self.assertEqual(plan.value_source, "ARGUMENT")
        self.assertEqual(plan.value, "0011")
        self.assertFalse(plan.needs_global_variable)
        self.assertTrue(plan.needs_set_helper)
        self.assertEqual(plan_set.global_symbols, ())
        self.assertEqual(plan_set.helper_plans, (plan,))

    def test_static_enter_pattern_does_not_need_a_starred_field(self):
        flow = pd.DataFrame(
            [{"CP NO": "CP1", "item": "STATIC", "type": "trim", "sub": "/", "Recipe": "ENTER-TRIM-JUDGE"}]
        )
        pattern = pd.DataFrame(
            [
                {"item": "STATIC", "addr": "0011101", "description": "7,trim_sel=1", "pattern": "trim mode"},
                {"item": None, "addr": "0000010", "description": "3,DAC[3:0]=0000*", "pattern": "trim dac"},
            ]
        )

        enter = compile_recipe_program(flow, pattern).functions[0].rows[0].operations[0]

        self.assertEqual(enter.value_source, "STATIC")
        self.assertIsNone(enter.dynamic_field)

    def test_dac_write_fixed_argument_is_not_confused_with_dac_final(self):
        flow = pd.DataFrame(
            [{"CP NO": "CP1", "item": "Mr_VDDD_DC", "type": "verify", "sub": "/", "Recipe": "ENTER-DAC_WRITE(0011)-JUDGE"}]
        )

        operation = compile_recipe_program(flow, _mrvddd_pattern_frame()).functions[0].rows[0].operations[1]

        self.assertEqual(operation.value_source, "ARGUMENT")
        self.assertEqual(operation.value, "0011")

    def test_dac_write_must_appear_once_before_judge(self):
        invalid = (
            "ENTER-JUDGE-DAC_WRITE",
            "ENTER-DAC_WRITE-DAC_WRITE-JUDGE",
            "ENTER-DAC_WRITE",
        )
        for recipe in invalid:
            with self.subTest(recipe=recipe):
                flow = pd.DataFrame(
                    [{"CP NO": "CP1", "item": "Mr_VDDD_DC", "type": "verify",
                      "sub": "/", "Recipe": recipe}]
                )
                with self.assertRaises(FlowCompileError):
                    compile_recipe_program(flow, _mrvddd_pattern_frame())

    def test_verify_can_explicitly_enter_trim_role_and_run_external_pattern(self):
        flow = pd.DataFrame(
            [{"CP NO": "CP1", "item": "Mr_VDDD_DC", "type": "verify", "sub": "/",
              "Recipe": "ENTER(ROLE=TRIM)-RUN(external_ready_pattern)-JUDGE"}]
        )

        operations = compile_recipe_program(flow, _mrvddd_pattern_frame()).functions[0].rows[0].operations

        self.assertEqual(operations[0].pattern_role, "trim mode")
        self.assertEqual(operations[0].value_source, "DEFAULT")
        self.assertEqual(operations[1].name, "RUN")
        self.assertEqual(operations[1].value, "external_ready_pattern")

    def test_dynamic_enter_helpers_include_verify_rows_and_deduplicate_by_pattern(self):
        flow = pd.DataFrame(
            [
                {"CP NO": "CP1", "item": "Mr_VDDD_DC", "type": "verify", "sub": "/", "mode": "fbist",
                 "Recipe": "ENTER(010)-JUDGE"},
                {"CP NO": "CP1", "item": "Mr_VDDD_DC", "type": "verify", "sub": "repeat", "mode": "fbist",
                 "Recipe": "ENTER(011)-JUDGE"},
            ]
        )

        rows = compile_recipe_rows(flow, _mrvddd_pattern_frame())
        helpers = dynamic_recipe_enter_operations(rows, "CP1")

        self.assertEqual(len(helpers), 1)
        self.assertEqual(helpers[0].reference, "enter_mr_vddd_dc_verify")
        self.assertEqual(helpers[0].default_value, "001")
        self.assertEqual(helpers[0].field_width, 3)

    def test_setup_modules_cannot_silently_move_after_judge(self):
        flow = pd.DataFrame(
            [{"CP NO": "CP1", "item": "Mr_VDDD_DC", "type": "verify", "sub": "/",
              "Recipe": "ENTER-JUDGE-RUN(external_ready_pattern)"}]
        )
        row = compile_recipe_program(flow, _mrvddd_pattern_frame()).functions[0].rows[0]

        with self.assertRaisesRegex(FlowCompileError, "ENTER/RUN 必须连续位于流程前部"):
            recipe_setup_operations(row)


def _mrvddd_pattern_frame():
    return pd.DataFrame(
        [
            {"item": "Mr_VDDD_DC", "addr": "0101110", "description": "2,MR_LEVEL[2:0]=001*", "pattern": "trim mode"},
            {"item": None, "addr": "0000010", "description": "3,MR_DAC[3:0]=0000*", "pattern": "trim dac"},
            {"item": "Mr_VDDD_DC", "addr": "0101110", "description": "2,MR_LEVEL[2:0]=001*", "pattern": "verify mode"},
        ]
    )


class _RecipeReader:
    _headers = ("CP NO", "item", "type", "sub", "Recipe")

    def __init__(self, rows):
        self._rows = rows

    @staticmethod
    def has_sheet(sheet):
        return sheet == "FLOW"

    @classmethod
    def header_map(cls, sheet):
        return {name: index + 1 for index, name in enumerate(cls._headers)}

    def row_values(self, sheet, headers):
        for row, cp, item, flow_type, sub, recipe in self._rows:
            values = (cp, item, flow_type, sub, recipe)
            yield {
                header: Cell("FLOW", row, index + 1, header, value, "s", "General")
                for index, (header, value) in enumerate(zip(self._headers, values))
            }


if __name__ == "__main__":
    unittest.main()
