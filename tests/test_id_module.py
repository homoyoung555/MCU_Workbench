"""READID/CHECKID preserve tester result policy using compiler-bound RUN plans."""

from dataclasses import FrozenInstanceError, replace
import unittest
import pandas as pd

from flow_recipe import FlowCompileError, compile_flow, compile_recipe_rows, parse_recipe
from program_gen.core.id_module import IdModulePlanError, compile_id_module_plan
from program_gen.core.run_pattern import PatternResourceRef, PatternSpan, RunPatternPlan
from program_gen.core.uid_plan import IdItemPlan, IdTargetDefinition, IdPlanError, compile_id_plan_set
from program_gen.platforms.chroma.id_adapter import adapt_check_id as chroma_check
from program_gen.platforms.chroma.id_adapter import adapt_read_id as chroma_read
from program_gen.platforms.s100.id_adapter import adapt_check_id as s100_check
from program_gen.platforms.s100.id_adapter import adapt_read_id as s100_read


def _plan(read=True):
    item = IdItemPlan(
        "arbitrary_upstream_item", IdTargetDefinition("unrelated_target", "ID"),
        "PRODUCE_GATE" if read else "HARD_CHECK",
        "DEFER" if read else "FLOW_BIN", "CUSTOM_NEEDS_WRITE" if read else None,
    )
    enter = RunPatternPlan(
        PatternResourceRef("custom_enter", "pattern:custom_enter", ("START", "END")),
        PatternSpan.full(), "TS_CUSTOM",
    )
    check = RunPatternPlan(
        PatternResourceRef("custom_check", "pattern:custom_check", ("head", "tail")),
        PatternSpan.segment("head", "tail"), "TS_CHECK",
    )
    return compile_id_module_plan(
        item, cp="CP4", power_profile="VCC_TYP",
        enter_fbist_mode=enter, check_pattern=check,
    )


class IdModuleTests(unittest.TestCase):
    def test_compiled_plan_is_immutable_and_keeps_upstream_facts(self):
        plan = _plan()
        self.assertEqual(plan.module_name, "READID")
        self.assertEqual(plan.gate_symbol, "CUSTOM_NEEDS_WRITE")
        self.assertEqual(plan.gate_semantic_identity, "CP4:CUSTOM_NEEDS_WRITE")
        self.assertEqual(plan.check_pattern.pattern.name, "custom_check")
        with self.assertRaises(FrozenInstanceError):
            plan.cp = "CP1"

    def test_readid_records_current_failure_and_does_not_reject_sites(self):
        for adapter, predicate, restore in (
            (chroma_read, "CUSTOM_NEEDS_WRITE[SOCKET]=(PLAN_RESULT_MS[SOCKET]==FAIL)?1:0;", "PLAN_RESULT_MS[SOCKET]=PASS;"),
            (s100_read, "CUSTOM_NEEDS_WRITE[T_SOCKET]=(Sys_DriverResult[T_SOCKET]<0.5)?1:0;", "IGNORE_FAIL"),
        ):
            with self.subTest(adapter=adapter.__module__):
                emission = adapter(_plan())
                source = "\n".join(emission.statements)
                self.assertIn(predicate, source)
                self.assertIn(restore, source)
                self.assertNotIn("REJECT_BIN", source)
                self.assertNotIn("MARK_NO", source)
                self.assertLess(source.index("custom_check"), source.index("CUSTOM_NEEDS_WRITE"))
                self.assertLess(source.index("CUSTOM_NEEDS_WRITE"), source.index("POWER_OFF"))
                self.assertEqual(len(emission.provides), 1)
                provision = emission.provides[0]
                self.assertEqual(provision.ref.identity, "ID_GATE.CP4:CUSTOM_NEEDS_WRITE")
                self.assertEqual(provision.rendered_name, "CUSTOM_NEEDS_WRITE")
                self.assertEqual((provision.value_type, provision.bit_width, provision.scope), ("BOOL", 1, "SITE"))

    def test_checkid_keeps_hard_failure_without_gate_or_pass_override(self):
        for adapter in (chroma_check, s100_check):
            with self.subTest(adapter=adapter.__module__):
                emission = adapter(_plan(False))
                source = "\n".join(emission.statements)
                self.assertNotIn("IGNORE_FAIL", source)
                self.assertNotIn("=PASS", source)
                self.assertNotIn("NEEDS_WRITE", source)
                self.assertEqual(emission.provides, ())

    def test_both_adapters_use_bound_pattern_spans_and_complete_resources(self):
        for adapter, statement in (
            (chroma_read, "JUDGE_PAT(custom_check:head,custom_check:tail);"),
            (s100_read, "RUN_PATTERN(custom_check:head,custom_check:tail,1,TS_CHECK, IGNORE_FAIL);"),
        ):
            with self.subTest(adapter=adapter.__module__):
                emission = adapter(_plan())
                self.assertIn(statement, "\n".join(emission.statements))
                self.assertEqual(
                    {resource.logical_identity for resource in emission.resource_requires},
                    {"pattern:custom_enter", "pattern:custom_check"},
                )
                self.assertEqual(len(emission.resource_requires), 2)

    def test_adapter_rejects_wrong_module_role(self):
        for adapter, read in ((chroma_read, False), (s100_read, False), (chroma_check, True), (s100_check, True)):
            with self.subTest(adapter=adapter.__module__, read=read):
                with self.assertRaises(IdModulePlanError):
                    adapter(_plan(read))

    def test_compile_rejects_missing_gate_invalid_scope_and_wrong_role(self):
        plan = _plan()
        valid = dict(cp=plan.cp, power_profile=plan.power_profile,
                     enter_fbist_mode=plan.enter_fbist_mode, check_pattern=plan.check_pattern)
        for item, changes in (
            (replace(plan.id_item, gate_symbol=None), {}),
            (replace(plan.id_item, gate_symbol="bad;symbol"), {}),
            (replace(plan.id_item, role="COMMIT_CLOSURE"), {}),
            (replace(plan.id_item, failure_policy="FLOW_BIN"), {}),
            (plan.id_item, {"cp": "bogus"}),
            (plan.id_item, {"power_profile": "VCC_TYP);"}),
            (plan.id_item, {"check_pattern": None}),
        ):
            with self.subTest(item=item, changes=changes):
                with self.assertRaises(IdModulePlanError):
                    compile_id_module_plan(item, **(valid | changes))

    def test_gate_requires_one_same_cp_preceding_exact_target_producer(self):
        read = {"CP NO": "CP2", "item": "Read_CP1_BakeID", "type": "id"}
        write = {"CP NO": "CP2", "item": "Pgm_CP1_BakeID", "type": "uid"}
        for rows in (
            [dict(read, **{"CP NO": "CP3"}), write],
            [write, read],
            [read, read, write],
            [dict(read, item="Read_CP11_BakeID"), write],
        ):
            with self.subTest(rows=rows):
                with self.assertRaises(IdPlanError):
                    compile_id_plan_set(pd.DataFrame(rows))
        plans = compile_id_plan_set(pd.DataFrame([
            dict(read, **{"CP NO": "CP3"}), read, write,
        ], index=[90, 30, 10]))
        self.assertIs(plans.bake_gate_for_row(10), plans.for_row(30))

    def test_formal_target_parser_rejects_substrings_and_wrong_type_roles(self):
        for item, flow_type in (
            ("Read_fakebakeid", "id"), ("Read_CP1_BakeID_Extra", "id"),
            ("Check_CP1ID_Read", "id"), ("Read_CP1ID", "uid"),
            ("Pgm_CP1ID_Read", "id"), ("Read_CP1junkID", "id"),
        ):
            with self.subTest(item=item, flow_type=flow_type):
                with self.assertRaises(IdPlanError):
                    compile_id_plan_set(pd.DataFrame([
                        {"CP NO": "CP2", "item": item, "type": flow_type},
                    ]))

    def test_standard_target_aliases_canonicalize_before_matching(self):
        plans = compile_id_plan_set(pd.DataFrame([
            {"CP NO": "cp4", "item": "read_cp3bakeid", "type": "id"},
            {"CP NO": "CP4", "item": "Pgm_CP3_BakeID_Read", "type": "uid"},
        ]))
        self.assertEqual(plans.for_row(0).target.target, "CP3_BakeID")
        self.assertEqual(plans.bake_gate_for_row(1).gate_symbol, "CP3_BAKEID_NEEDS_WRITE")

    def test_id_modules_reject_arguments_and_defaults_compile_once_upstream(self):
        self.assertEqual([call.name for call in parse_recipe("READID-CHECKID")], ["READID", "CHECKID"])
        for recipe in ("READID(UID)", "CHECKID(CP1ID)"):
            with self.subTest(recipe=recipe):
                with self.assertRaises(FlowCompileError):
                    parse_recipe(recipe)
        frame = pd.DataFrame([
            {"CP NO": "CP4", "item": "Read_CP3_BakeID", "type": "id", "sub": "/", "Recipe": ""},
            {"CP NO": "CP4", "item": "Check_CP3ID", "type": "id", "sub": "/", "Recipe": None},
            {"CP NO": "CP4", "item": "Pgm_CP4ID_Read", "type": "uid", "sub": "/", "Recipe": ""},
            {"CP NO": "CP4", "item": "Pgm_CP3_BakeID", "type": "uid", "sub": "/", "Recipe": ""},
        ])
        pattern = pd.DataFrame(columns=("item", "addr", "description", "pattern"))
        rows = compile_recipe_rows(frame, pattern)
        self.assertEqual(tuple(rows), (0, 1, 2))
        self.assertEqual([[call.name for call in row.operations] for row in rows.values()],
                         [["READID"], ["CHECKID"], ["COMMIT", "PGMOTP"]])
        self.assertEqual(rows[2].operations[-1].argument, "UID")
        self.assertEqual(frame.loc[2, "Recipe"], "")
        with self.assertRaises(FlowCompileError):
            compile_flow(frame.iloc[3:])
        explicit = frame.iloc[2:3].copy()
        explicit["Recipe"] = "BUILDUID-COMMIT-PGMOTP(UID)"
        self.assertEqual([call.name for call in compile_recipe_rows(explicit, pattern)[2].operations],
                         ["BUILDUID", "COMMIT", "PGMOTP"])


if __name__ == "__main__":
    unittest.main()
