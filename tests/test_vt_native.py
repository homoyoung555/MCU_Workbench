"""VT contracts are compiled upstream and shared by both tester platforms."""

import unittest
from dataclasses import replace
from unittest.mock import patch

from flow_recipe import FlowCompileError, parse_recipe
from program_gen.compiler import ProductCompiler
from program_gen.core.vt_test import VtTestCompileError, compile_vt_plans
from program_gen.platform_program import (PlatformProgramBuilder, ProgramAssemblyInput,
    WorkspacePatternProducer, compile_platform_program_facts)
from program_gen.platform_program.pattern import GeneratedPatternProducer
from program_gen.registered_typed_kinds import NATIVE_TYPED_KIND_REGISTRY
from program_gen.render_plan import TargetKey
from program_gen.typed_kind_registry import TypedKindContext
from program_gen.workbook import ColorModel, TableModel, WorkbookModel, WorkbookReader
from tests.workspace_paths import FORMAL_MASTER, WORKSPACE_ROOT


class VtNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()

    def test_formal_vt_rows_have_upstream_plans_and_reuse_readid_gate(self):
        catalogs = self.compilation.plan.catalogs
        plans = getattr(catalogs, "vt_plans", {})
        operations = tuple(op for op in catalogs.flow_operations if op.typed_kind == "VT")
        self.assertEqual(len(operations), 16)
        self.assertEqual(set(plans), {op.row for op in operations})
        for plan in plans.values():
            self.assertEqual(tuple(call.name for call in catalogs.recipe_rows[plan.row].operations),
                             ("VT_TEST",))
            self.assertEqual(plan.test.retry_failed, plan.item.casefold().startswith("vte_"))
            if "bake" in plan.item.casefold():
                producers = [p for p in catalogs.id_module_plans.values()
                             if p.cp == plan.cp and p.row < plan.row
                             and p.steps[0].module == "READID"
                             and p.steps[0].module_plan.id_item.target.kind == "BAKEID"]
                self.assertEqual(len(producers), 1)
                self.assertIs(plan.test.gate, producers[0].steps[0].module_plan)
            else:
                self.assertIsNone(plan.test.gate)

    def test_disabled_readid_cannot_supply_an_enabled_bake_vt(self):
        producer = next(p for p in self.compilation.plan.catalogs.id_module_plans.values()
                        if p.cp == "CP2" and p.steps[0].module == "READID"
                        and p.steps[0].module_plan.id_item.target.kind == "BAKEID")
        sheet = self.workbook["FLOW"]
        cell = sheet.cell(producer.excel_row, 2)
        disabled = replace(cell, fill=replace(cell.fill, fgColor=ColorModel(type="theme", theme=0, tint=-0.5)))
        sheet = replace(sheet, rows=tuple(tuple(disabled if c.coordinate == cell.coordinate else c for c in row)
                                         for row in sheet.rows))
        workbook = replace(self.workbook, sheets=tuple(sheet if s.title == "FLOW" else s
                                                      for s in self.workbook.sheets))
        result = ProductCompiler().compile(workbook)
        self.assertTrue(result.diagnostics.blocking_errors)
        self.assertTrue(any("VT.GATE.PRODUCER_DISABLED" in d.message
                            for d in result.diagnostics.blocking_errors))

    def test_voltage_comes_from_each_cp_version_including_bake(self):
        version = self.workbook.dataframe("VERSION")
        version.loc[version["CP num"] == "CP2", "VTE target"] = -0.17
        version.loc[version["CP num"] == "CP2", "VTP bake target"] = 0.07
        workbook = replace(self.workbook, tables=tuple(TableModel.from_dataframe("VERSION", version)
                           if table.title == "VERSION" else table for table in self.workbook.tables))
        compilation = ProductCompiler().compile(workbook).require_success()
        self.assertNotEqual(compilation.identity, self.compilation.identity)
        for plan in compilation.plan.catalogs.vt_plans.values():
            mode = plan.item.split("_")[0].upper()
            column = f"{mode}{' bake' if 'bake' in plan.item.casefold() else ''} target"
            expected = float(version.loc[version["CP num"] == plan.cp, column].iloc[0])
            self.assertEqual(plan.test.voltage, expected)

    def test_invalid_voltage_patterns_and_gate_fail_upstream(self):
        catalog = self.compilation.plan.catalogs
        operation = next(op for op in catalog.flow_operations if op.row == 100)
        arguments = dict(operations=(operation,), recipe_rows=catalog.recipe_rows,
                         flow=self.workbook.dataframe("FLOW"), version=self.workbook.dataframe("VERSION"),
                         requests=self.compilation.flash_compare_compilation.requests,
                         fbist_plan=catalog.fbist_pattern_plan, id_plans=catalog.id_module_plans)
        for value in ("/", float("nan"), float("inf")):
            version = arguments["version"].copy()
            version.loc[version["CP num"] == "CP2", "VTE bake target"] = value
            with self.subTest(value=value), self.assertRaisesRegex(VtTestCompileError, "VOLTAGE.INVALID"):
                compile_vt_plans(**dict(arguments, version=version))
        with self.assertRaisesRegex(VtTestCompileError, "GATE.BINDING_INVALID"):
            compile_vt_plans(**dict(arguments, id_plans={}))
        read_name = catalog.vt_plans[operation.row].test.read.pattern.name
        read = next(r for r in arguments["requests"] if r.output_identity == read_name)
        for requests in (tuple(r for r in arguments["requests"] if r is not read),
                         (*arguments["requests"], read)):
            with self.assertRaisesRegex(VtTestCompileError, "PATTERN.BINDING_INVALID"):
                compile_vt_plans(**dict(arguments, requests=requests))
        with self.assertRaisesRegex(VtTestCompileError, "ENTER.BINDING_INVALID"):
            compile_vt_plans(**dict(arguments, fbist_plan=replace(catalog.fbist_pattern_plan, patterns=())))

        fbist = catalog.fbist_pattern_plan
        enter_name = catalog.vt_plans[operation.row].test.enter_vt.pattern.name
        renamed = replace(fbist,
            patterns=tuple(replace(p, pattern_name="product_vt_enter") if p.pattern_name == enter_name else p
                           for p in fbist.patterns),
            rows=tuple(replace(r, output_pattern="product_vt_enter") if r.output_pattern == enter_name else r
                       for r in fbist.rows))
        rebound = compile_vt_plans(**dict(arguments, fbist_plan=renamed))[operation.row]
        self.assertEqual(rebound.test.enter_vt.pattern.name, "product_vt_enter")

    def test_recipe_does_not_claim_repair_support(self):
        self.assertEqual(parse_recipe("VT_TEST")[0].name, "VT_TEST")
        for recipe in ("VT_TEST(repair)", "VT_TEST(retry=2)"):
            with self.assertRaises(FlowCompileError):
                parse_recipe(recipe)
        self.assertEqual(dict(compile_vt_plans((), {}, None, None, (), None, {})), {})

    def test_both_platforms_build_with_existing_gate_and_no_workbook_access(self):
        for platform in ("chroma", "s100"):
            for cp in ("CP1", "CP2", "CP3"):
                with self.subTest(platform=platform, cp=cp):
                    render = self.build_program(platform, cp)
                    extension = ".pln" if platform == "chroma" else ".prg"
                    source = next(a.content.decode("gbk") for a in render.artifacts
                                  if a.relative_path.endswith(extension))
                    for plan in self.compilation.plan.catalogs.vt_plans.values():
                        if plan.cp != cp:
                            continue
                        definition = next(d for d in self.compilation.for_cp(cp).canonical_schedule.definitions
                                          if plan.excel_row in d.source_rows)
                        self.assertIn(definition.render_name, source)
                        if plan.test.gate:
                            symbol = plan.test.gate.gate_symbol
                            declaration = f"LUINT {symbol};" if platform == "chroma" else f"int {symbol}[MAX_SITE];"
                            self.assertEqual(source.count(declaration), 1)
                    self.assertNotIn("set_all_final_vposp", source)
                    self.assertNotIn("ENABLE_BY_MARK_NO", source)

    @classmethod
    def build_program(cls, platform, cp, compilation=None):
        compilation = compilation or cls.compilation
        target = TargetKey(platform, cp, "lab", f"VT_{platform}_{cp}")
        facts = compile_platform_program_facts(cls.workbook, target)
        catalog = compilation.plan.catalogs
        vt = tuple(p for p in catalog.vt_plans.values() if p.cp == cp)
        ids = tuple(p for p in catalog.id_module_plans.values()
                    if p.cp == cp and any(p.steps[0].module_plan is v.test.gate for v in vt))
        with patch.object(WorkbookReader, "read", side_effect=AssertionError("workbook reopened")), \
             patch.object(WorkbookModel, "dataframe", side_effect=AssertionError("downstream workbook read")):
            producer = GeneratedPatternProducer.from_compilation(compilation, platform,
                fallback=WorkspacePatternProducer(WORKSPACE_ROOT / "input" / platform)).for_target(facts)
            context = TypedKindContext(compilation, target, facts, producer)
            assemblies = tuple(NATIVE_TYPED_KIND_REGISTRY.compile(kind, plans, context)
                               for kind, plans in (("ID", ids), ("VT", vt)))
            return PlatformProgramBuilder(producer).build(ProgramAssemblyInput(
                target, facts, compilation.for_cp(cp).canonical_schedule,
                tuple(c for a in assemblies for c in a.contributions),
                tuple(b for a in assemblies for b in a.bodies),
                compilation.for_cp(cp).runtime_state.declarations))


if __name__ == "__main__":
    unittest.main()
