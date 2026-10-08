"""MAIN consumes ProductCompiler plans, including commented repair reads."""

import unittest
from dataclasses import replace
from unittest.mock import patch

from flow_recipe import FlowCompileError, parse_recipe

from program_gen.compiler import ProductCompiler
from program_gen.core.nm_test import NmTestMode, NmTestCompileError, compile_nm_test_plan, compile_main_plans
from program_gen.core.flash_compare_plan import Operation, BulkCoverage
from program_gen.core.set_vposp import SetVpospSnapshot
from program_gen.registered_recipe_modules import NATIVE_RECIPE_MODULE_REGISTRY
from program_gen.registered_typed_kinds import NATIVE_TYPED_KIND_REGISTRY
from program_gen.platform_program import (PlatformProgramBuilder, ProgramAssemblyInput,
    WorkspacePatternProducer, compile_platform_program_facts)
from program_gen.platform_program.pattern import GeneratedPatternProducer
from program_gen.render_plan import TargetKey
from program_gen.typed_kind_registry import TypedKindContext
from program_gen.workbook import WorkbookModel, WorkbookReader
from tests.workspace_paths import FORMAL_MASTER, WORKSPACE_ROOT


class MainNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()

    def test_formal_main_rows_have_upstream_plans(self):
        plans = getattr(self.compilation.plan.catalogs, "main_plans", {})
        operations = tuple(op for op in self.compilation.plan.catalogs.flow_operations
                           if op.typed_kind == "MAIN")
        self.assertEqual(len(operations), 13)
        self.assertEqual(set(plans), {op.row for op in operations})
        self.assertTrue(all(plan.steps[-1].module == "NM_TEST" for plan in plans.values()))

    def test_main_recipe_defaults_and_repair_are_compiled_upstream(self):
        for text, mode in (("NM_TEST", None), ("NM_TEST(normal)", "normal"),
                           ("NM_TEST(repair)", "repair"), ("NM_TEST(REPAIR)", "repair")):
            with self.subTest(text=text):
                self.assertEqual(parse_recipe(text)[0].argument, mode)
        for text in ("NM_TEST(skip)", "NM_TEST(repair,normal)", "NM_TEST(mode=repair)"):
            with self.subTest(text=text), self.assertRaises(FlowCompileError):
                parse_recipe(text)
        compilation = self.compile_with_recipe("NM_TEST(repair)")
        for row, plan in compilation.plan.catalogs.main_plans.items():
            self.assertEqual(plan.steps[-1].module_plan.mode.value, "repair")
            self.assertEqual(compilation.plan.catalogs.recipe_rows[row].operations[0].argument, "repair")
        for row in self.compilation.plan.catalogs.main_plans:
            self.assertEqual(self.compilation.plan.catalogs.recipe_rows[row].operations[0].name, "NM_TEST")

    @classmethod
    def compile_with_recipe(cls, recipe, rows=None):
        original = WorkbookModel.dataframe
        main_rows = tuple(cls.compilation.plan.catalogs.main_plans) if rows is None else rows

        def dataframe(workbook, name, *args, **kwargs):
            frame = original(workbook, name, *args, **kwargs)
            if name == "FLOW":
                frame.loc[list(main_rows), "Recipe"] = recipe
            return frame

        with patch.object(WorkbookModel, "dataframe", dataframe):
            return ProductCompiler().compile(cls.workbook).require_success()

    def test_mode_is_row_local_and_changes_compilation_identity(self):
        compilation = self.compile_with_recipe("NM_TEST(repair)", rows=(65,))
        self.assertNotEqual(compilation.identity, self.compilation.identity)
        for row, main in compilation.plan.catalogs.main_plans.items():
            self.assertEqual(main.steps[-1].module_plan.mode,
                             NmTestMode.REPAIR if row == 65 else NmTestMode.NORMAL)

    def test_repair_only_comments_read_calls_and_logs_on_both_platforms(self):
        for main in self.compilation.plan.catalogs.main_plans.values():
            plan = main.steps[-1].module_plan
            read_names = {run.pattern.pattern.name for run in plan.runs if run.operation is Operation.READ}
            for platform in ("chroma", "s100"):
                with self.subTest(item=main.item, platform=platform):
                    normal = NATIVE_RECIPE_MODULE_REGISTRY.emit("NM_TEST", plan, platform)
                    repair = NATIVE_RECIPE_MODULE_REGISTRY.emit("NM_TEST", replace(plan, mode=NmTestMode.REPAIR), platform)
                    read_lines = {i for i, line in enumerate(normal.statements)
                                  if any(name in line for name in read_names)}
                    if platform == "chroma":
                        # A read step includes its counter, datalog, call and separator.
                        calls = [i for i in read_lines if "JUDGE_PAT(" in normal.statements[i]]
                        read_lines = {j for i in calls for j in range(i - 2, i + 2)}
                    expected = tuple("//" + line if i in read_lines else line
                                     for i, line in enumerate(normal.statements))
                    self.assertEqual(repair.statements, expected)
                    self.assertEqual(normal.resource_requires, repair.resource_requires)
                    calls_per_read = 4 if platform == "chroma" else 1
                    self.assertEqual(sum(line.startswith("//") for line in repair.statements),
                                     len(read_names) * calls_per_read)
                    text = "\n".join(normal.statements)
                    self.assertEqual(text.count("POWER_ON("), 1)
                    self.assertEqual(text.count("POWER_OFF("), 1)
                    self.assertNotIn("_sm", text)

    def test_both_platforms_build_all_main_rows_without_workbook_access(self):
        for platform in ("chroma", "s100"):
            for cp in ("CP1", "CP2", "CP3"):
                with self.subTest(platform=platform, cp=cp):
                    render = self.build_program(platform, cp)
                    extension = ".pln" if platform == "chroma" else ".prg"
                    source = next(a.content.decode("gbk") for a in render.artifacts if a.relative_path.endswith(extension))
                    for plan in self.compilation.plan.catalogs.main_plans.values():
                        if plan.cp == cp:
                            definition = next(d for d in self.compilation.for_cp(cp).canonical_schedule.definitions
                                              if plan.excel_row in d.source_rows)
                            self.assertIn(definition.render_name, source)

    def test_business_sequences_and_nm_only_binding(self):
        expected = {
            "chip_erase_read": ("erase", "read"), "initialization": ("erase", "read"),
            "chip_pgm00_read": ("erase", "program", "read"),
            "chip_pgmckb_read": ("erase", "program", "read"),
            "chip_pgmckbb_read": ("erase", "program", "read"),
            "disturb_ff": ("erase", "program", "program", "read"),
            "disturb_ckb_ckbb": ("erase", "program", "program", "read") * 2,
        }
        requests = self.compilation.flash_compare_compilation.requests
        by_name = {r.output_identity: r for r in requests}
        backgrounds = {"chip_erase_read": ("FF",), "initialization": ("FF",),
                       "chip_pgm00_read": ("00",), "chip_pgmckb_read": ("PCKB",),
                       "chip_pgmckbb_read": ("NCKB",), "disturb_ff": ("FF",),
                       "disturb_ckb_ckbb": ("PCKB", "NCKB")}
        for main in self.compilation.plan.catalogs.main_plans.values():
            with self.subTest(item=main.item):
                runs = main.steps[-1].module_plan.runs
                self.assertEqual(tuple(r.operation.value.lower() for r in runs), expected[main.item.lower()])
                self.assertTrue(all((by_name[r.pattern.pattern.name].bulk_coverage or BulkCoverage.NM_ONLY)
                                    is BulkCoverage.NM_ONLY for r in runs))
                self.assertEqual(tuple(by_name[r.pattern.pattern.name].data.kind.value for r in runs
                                       if r.operation is Operation.READ), backgrounds[main.item.lower()])
                programs = [r for r in runs if r.operation is Operation.PROGRAM]
                if main.item.lower().startswith("disturb"):
                    self.assertEqual(programs[0], programs[1])
                    if len(programs) == 4:
                        self.assertEqual(programs[2], programs[3])
                        self.assertNotEqual(programs[0], programs[2])

    def test_missing_duplicate_or_sm_only_patterns_fail_in_compiler(self):
        requests = self.compilation.flash_compare_compilation.requests
        plan = compile_nm_test_plan("Initialization", "VCC_TYP", requests)
        erase_name = plan.runs[0].pattern.pattern.name
        erase = next(r for r in requests if r.output_identity == erase_name)
        remaining = tuple(r for r in requests if r is not erase)
        for invalid in (remaining, (*requests, erase),
                        (*remaining, replace(erase, bulk_coverage=BulkCoverage.NM_PLUS_SM))):
            with self.subTest(count=len(invalid)), self.assertRaisesRegex(NmTestCompileError, "PATTERN.BINDING_INVALID"):
                compile_nm_test_plan("Initialization", "VCC_TYP", invalid)
        for item, vcc, mode, code in (("unknown", "VCC_TYP", "normal", "ITEM.UNSUPPORTED"),
                                      ("Initialization", "", "normal", "VCC.INVALID"),
                                      ("Initialization", "VCC_TYP", "skip", "MODE.INVALID")):
            with self.subTest(code=code), self.assertRaisesRegex(NmTestCompileError, code):
                compile_nm_test_plan(item, vcc, requests, mode=mode)

    def test_adapters_obey_detached_pattern_identity_and_span(self):
        plan = self.compilation.plan.catalogs.main_plans[65].steps[-1].module_plan
        run = plan.runs[-1]
        from program_gen.core.run_pattern import PatternSpan
        renamed = replace(run.pattern, pattern=replace(run.pattern.pattern, name="renamed_compare",
                          logical_identity="pattern:renamed_compare", ordered_labels=("a", "b")),
                          span=PatternSpan.segment("a", "b"))
        plan = replace(plan, runs=(replace(run, pattern=renamed),), mode=NmTestMode.REPAIR)
        with patch.object(WorkbookModel, "dataframe", side_effect=AssertionError("downstream workbook read")):
            for platform in ("chroma", "s100"):
                emission = NATIVE_RECIPE_MODULE_REGISTRY.emit("NM_TEST", plan, platform)
                self.assertTrue(any(line.startswith("//") and "renamed_compare:a" in line for line in emission.statements))
                self.assertIn("pattern:renamed_compare", {r.logical_identity for r in emission.resource_requires})

    def test_vposp_missing_or_dirty_is_rejected_and_explicit_prepare_composes(self):
        catalog = self.compilation.plan.catalogs
        operation = next(op for op in catalog.flow_operations if op.row == 65)
        pumps = frozenset(item.casefold() for item in catalog.fbist_pattern_plan.pump_items)
        for snapshot in (SetVpospSnapshot(), SetVpospSnapshot(pumps, pumps)):
            with self.subTest(snapshot=snapshot), self.assertRaisesRegex(NmTestCompileError, "SETVPOSP.NOT_READY"):
                compile_main_plans((operation,), catalog.recipe_rows, self.workbook.dataframe("FLOW"),
                    self.compilation.flash_compare_compilation.requests, catalog.fbist_pattern_plan, {65: snapshot})
        compilation = self.compile_with_recipe("SETVPOSP-NM_TEST(repair)")
        for main in compilation.plan.catalogs.main_plans.values():
            self.assertEqual(main.effective_recipe, ("SETVPOSP", "NM_TEST"))
            for platform in ("chroma", "s100"):
                emissions = [NATIVE_RECIPE_MODULE_REGISTRY.emit(step.module, step.module_plan, platform) for step in main.steps]
                text = "\n".join(line for e in emissions for line in e.statements)
                self.assertEqual(text.count("POWER_ON("), 1)

    def test_empty_main_requires_no_fbist_catalog(self):
        self.assertEqual(dict(compile_main_plans((), {}, None, (), None, {})), {})

    @classmethod
    def build_program(cls, platform, cp, compilation=None):
        compilation = compilation or cls.compilation
        target = TargetKey(platform, cp, "lab", f"MAIN_{platform}_{cp}")
        facts = compile_platform_program_facts(cls.workbook, target)
        with patch.object(WorkbookReader, "read", side_effect=AssertionError("workbook reopened")), \
             patch.object(WorkbookModel, "dataframe", side_effect=AssertionError("downstream read FLOW")):
            producer = GeneratedPatternProducer.from_compilation(compilation, platform,
                fallback=WorkspacePatternProducer(WORKSPACE_ROOT / "input" / platform)).for_target(facts)
            context = TypedKindContext(compilation, target, facts, producer)
            assembly = NATIVE_TYPED_KIND_REGISTRY.compile("MAIN",
                tuple(p for p in compilation.plan.catalogs.main_plans.values() if p.cp == cp), context)
            return PlatformProgramBuilder(producer).build(ProgramAssemblyInput(
                target, facts, compilation.for_cp(cp).canonical_schedule,
                assembly.contributions, assembly.bodies, compilation.for_cp(cp).runtime_state.declarations))


if __name__ == "__main__":
    unittest.main()
