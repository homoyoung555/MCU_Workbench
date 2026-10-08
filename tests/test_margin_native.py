"""Margin is compiled once and rendered without reopening product inputs."""

import unittest
from dataclasses import replace
from unittest.mock import patch

from flow_recipe import FlowCompileError, parse_recipe
from program_gen.compiler import ProductCompiler
from program_gen.core.margin_test import MarginTestCompileError, compile_margin_plans, validate_margin_gate_schedule
from program_gen.core.vt_test import VtTestCompileError, compile_vt_plans
from program_gen.platform_program import (PlatformProgramBuilder, ProgramAssemblyInput,
    WorkspacePatternProducer, compile_platform_program_facts)
from program_gen.platform_program.pattern import GeneratedPatternProducer
from program_gen.registered_typed_kinds import NATIVE_TYPED_KIND_REGISTRY
from program_gen.render_plan import TargetKey
from program_gen.typed_kind_registry import TypedKindContext
from program_gen.workbook import WorkbookReader, WorkbookModel, TableModel
from tests.workspace_paths import FORMAL_MASTER, WORKSPACE_ROOT


class MarginNativeTests(unittest.TestCase):
    OTP_PAGES = ("trim0", "trim1", "uid")

    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()

    def test_read_target_recipe_aliases_and_argument_validation(self):
        for name in ("MARGIN", "VT", "MARGIN_TEST", "VT_TEST"):
            canonical = name if name.endswith("_TEST") else name + "_TEST"
            with self.subTest(name=name):
                self.assertEqual(parse_recipe(name)[0].name, canonical)
                self.assertEqual(parse_recipe(f"{name}(nm)")[0].argument, "NM")
                call = parse_recipe(f"{name}(otp-TRIM0)")[0]
                self.assertEqual((call.name, call.argument), (canonical, "OTP-trim0"))
                for argument in ("", "OTP", "OTP-", "OTP-trim0-trim1", "OTP-../trim0",
                                 "OTP-trim0.pat", "NM-trim0", "repair", "OTP-trim0,NM",
                                 "page=trim0"):
                    with self.subTest(argument=argument), self.assertRaises(FlowCompileError):
                        parse_recipe(f"{name}({argument})")
        calls = parse_recipe("MARGIN(OTP-trim0)-VT(OTP-trim1)")
        self.assertEqual(tuple(c.argument for c in calls), ("OTP-trim0", "OTP-trim1"))

    def test_shared_read_binding_only_changes_read_and_rejects_missing_pages(self):
        catalog = self.compilation.plan.catalogs
        for kind, compiler, error in (("MARGIN", compile_margin_plans, MarginTestCompileError),
                                      ("VT", compile_vt_plans, VtTestCompileError)):
            operation = next(op for op in catalog.flow_operations
                             if op.typed_kind == kind and "bake" in op.item.lower())
            original = getattr(catalog, kind.lower() + "_plans")[operation.row]
            arguments = dict(operations=(operation,), flow=self.workbook.dataframe("FLOW"),
                requests=self.compilation.flash_compare_compilation.requests,
                fbist_plan=catalog.fbist_pattern_plan, id_plans=catalog.id_module_plans,
                flash_label_plan=catalog.flash_label_plan)
            if kind == "VT":
                arguments["version"] = self.workbook.dataframe("VERSION")

            def compile_target(target, **overrides):
                recipes = dict(catalog.recipe_rows)
                recipes[operation.row] = replace(recipes[operation.row],
                    operations=parse_recipe(f"{kind}({target})"))
                return compiler(**dict(arguments, recipe_rows=recipes, **overrides))[operation.row]

            with self.subTest(kind=kind):
                self.assertEqual(compile_target("NM"), original)
                for selected in catalog.flash_label_plan.pages:
                    if selected.name.casefold() == "uid":
                        continue
                    # Prove we bind the producer's name, not a guessed filename, and do not need NM.
                    labels = replace(catalog.flash_label_plan, pages=(replace(selected,
                        names=replace(selected.names, read_pattern="product_otp_compare")),))
                    rebound = compile_target(f"OTP-{selected.name}", flash_label_plan=labels, requests=())
                    self.assertEqual(rebound.test.read.pattern.name, "product_otp_compare")
                    self.assertEqual(replace(rebound.test, read=original.test.read), original.test)
                with self.assertRaisesRegex(error, "PATTERN.BINDING_INVALID"):
                    compile_target("OTP-missing")
                trim0 = next(p for p in catalog.flash_label_plan.pages if p.name == "trim0")
                for labels in (None, replace(catalog.flash_label_plan, pages=()),
                               replace(catalog.flash_label_plan, pages=(trim0, trim0)),
                               replace(catalog.flash_label_plan, pages=(replace(trim0,
                                   names=replace(trim0.names, read_pattern=None)),))):
                    with self.assertRaisesRegex(error, "PATTERN.BINDING_INVALID"):
                        compile_target("OTP-trim0", flash_label_plan=labels)

    def test_uid_read_target_uses_existing_cp_variant_for_both_kinds(self):
        catalog = self.compilation.plan.catalogs
        labels = catalog.flash_label_plan
        for kind, compiler, error in (("MARGIN", compile_margin_plans, MarginTestCompileError),
                                      ("VT", compile_vt_plans, VtTestCompileError)):
            for cp in ("CP1", "CP2", "CP3"):
                operation = next(op for op in catalog.flow_operations
                                 if op.typed_kind == kind and op.cp == cp)
                original = getattr(catalog, kind.lower() + "_plans")[operation.row]
                recipes = dict(catalog.recipe_rows)
                recipes[operation.row] = replace(recipes[operation.row],
                    operations=parse_recipe(f"{kind}(OTP-UID)"))
                arguments = dict(operations=(operation,), recipe_rows=recipes,
                    flow=self.workbook.dataframe("FLOW"), requests=(),
                    fbist_plan=catalog.fbist_pattern_plan, id_plans=catalog.id_module_plans)
                if kind == "VT":
                    arguments["version"] = self.workbook.dataframe("VERSION")
                with self.subTest(kind=kind, cp=cp):
                    names = labels.contract.uid_variant(cp)
                    variant = next(v for v in labels.uid_variants if v.name == names.name)
                    rebound = compiler(**arguments, flash_label_plan=labels)[operation.row]
                    self.assertEqual(rebound.test.read.pattern.name, names.read_pattern)
                    self.assertEqual(replace(rebound.test, read=original.test.read), original.test)
                    renamed = replace(variant, names=replace(variant.names,
                        read_pattern="product_uid_compare"))
                    rebound = compiler(**arguments, flash_label_plan=replace(labels,
                        uid_variants=(renamed,)))[operation.row]
                    self.assertEqual(rebound.test.read.pattern.name, "product_uid_compare")
                    for invalid in (None, replace(labels, pages=()),
                                    replace(labels, uid_variants=()),
                                    replace(labels, uid_variants=(variant, variant)),
                                    replace(labels, uid_variants=(replace(variant,
                                        names=replace(variant.names, read_pattern=None)),)),
                                    replace(labels, contract=replace(labels.contract, uid_variants=()))):
                        with self.assertRaisesRegex(error, "PATTERN.BINDING_INVALID"):
                            compiler(**arguments, flash_label_plan=invalid)

    @classmethod
    def compile_otp_recipes(cls, *, pages=None):
        pages = cls.OTP_PAGES if pages is None else pages
        flow = cls.workbook.dataframe("FLOW")
        for kind in ("MARGIN", "VT"):
            plans = getattr(cls.compilation.plan.catalogs, kind.lower() + "_plans")
            for index, plan in enumerate(plans.values()):
                name = kind if index % 2 == 0 else kind + "_TEST"
                flow.loc[plan.row, "Recipe"] = f"{name}(OTP-{pages[index % len(pages)]})"
        workbook = replace(cls.workbook, tables=tuple(TableModel.from_dataframe("FLOW", flow)
            if table.title == "FLOW" else table for table in cls.workbook.tables))
        return ProductCompiler().compile(workbook).require_success()

    def test_otp_recipes_compile_and_render_both_kinds_without_reloading_compare(self):
        compilation = self.compile_otp_recipes()
        labels = compilation.plan.catalogs.flash_label_plan
        for kind in ("MARGIN", "VT"):
            plans = getattr(compilation.plan.catalogs, kind.lower() + "_plans")
            for index, plan in enumerate(plans.values()):
                page = self.OTP_PAGES[index % len(self.OTP_PAGES)]
                names = labels.contract.uid_variant(plan.cp) if page == "uid" else next(
                    p.names for p in labels.pages if p.name == page)
                self.assertEqual(plan.test.read.pattern.name, names.read_pattern)
        for platform in ("chroma", "s100"):
            for cp in ("CP1", "CP2", "CP3"):
                with self.subTest(platform=platform, cp=cp):
                    render = self.build_program(platform, cp, compilation, kinds=("MARGIN", "VT"))
                    source = next(a.content.decode("gbk") for a in render.artifacts
                                  if a.relative_path.endswith(".pln" if platform == "chroma" else ".prg"))
                    self.assertIn(labels.contract.uid_variant(cp).read_pattern, source)
                    self.assertNotIn("fbist_page_prog_", source)
                    self.assertNotIn("LOADMAP", source)
                    self.assertNotIn("REG_TRIM", source)
                    reads = {p.test.read.pattern.name for kind in ("MARGIN", "VT")
                             for p in getattr(compilation.plan.catalogs, kind.lower() + "_plans").values()
                             if p.cp == cp}
                    for read in reads:
                        self.assertIn(read, source)
                        extension = ".pat" if platform == "chroma" else ".sd"
                        self.assertTrue(any(a.relative_path.endswith(f"{read}{extension}")
                                            for a in render.artifacts))

    def test_formal_margin_plans_bind_resources_parameters_and_existing_gate(self):
        catalog = self.compilation.plan.catalogs
        operations = tuple(op for op in catalog.flow_operations if op.typed_kind == "MARGIN")
        plans = getattr(catalog, "margin_plans", {})
        self.assertEqual(len(operations), 16)
        self.assertEqual(set(plans), {op.row for op in operations})
        for plan in plans.values():
            test = plan.test
            self.assertEqual(tuple(call.name for call in catalog.recipe_rows[plan.row].operations),
                             ("MARGIN_TEST",))
            self.assertEqual(test.iterations, 8)
            self.assertEqual((test.start_voltage, test.end_voltage),
                             (0.0, -1.0) if plan.item.upper().startswith("VTE_") else (0.2, 1.0))
            if "bake" in plan.item.lower():
                producers = [p.steps[0].module_plan for p in catalog.id_module_plans.values()
                             if p.cp == plan.cp and p.row < plan.row and p.steps[0].module == "READID"
                             and p.steps[0].module_plan.id_item.target.kind == "BAKEID"]
                self.assertEqual(len(producers), 1)
                self.assertIs(test.gate, producers[0])
            else:
                self.assertIsNone(test.gate)

    def test_bad_resources_gate_and_recipe_are_rejected_upstream(self):
        catalog = self.compilation.plan.catalogs
        operation = next(op for op in catalog.flow_operations if op.typed_kind == "MARGIN" and "bake" in op.item.lower())
        arguments = dict(operations=(operation,), recipe_rows=catalog.recipe_rows,
            flow=self.workbook.dataframe("FLOW"), requests=self.compilation.flash_compare_compilation.requests,
            fbist_plan=catalog.fbist_pattern_plan, id_plans=catalog.id_module_plans)
        with self.assertRaisesRegex(MarginTestCompileError, "GATE.BINDING_INVALID"):
            compile_margin_plans(**dict(arguments, id_plans={}))
        read = catalog.margin_plans[operation.row].test.read.pattern.name
        request = next(r for r in arguments["requests"] if r.output_identity == read)
        for requests in (tuple(r for r in arguments["requests"] if r is not request),
                         (*arguments["requests"], request)):
            with self.assertRaisesRegex(MarginTestCompileError, "PATTERN.BINDING_INVALID"):
                compile_margin_plans(**dict(arguments, requests=requests))
        with self.assertRaisesRegex(MarginTestCompileError, "ENTER.BINDING_INVALID"):
            compile_margin_plans(**dict(arguments, fbist_plan=replace(catalog.fbist_pattern_plan, patterns=())))
        flow = arguments["flow"].copy()
        flow.loc[operation.row, "Vcc"] = "UNKNOWN"
        with self.assertRaisesRegex(MarginTestCompileError, "VCC.INVALID"):
            compile_margin_plans(**dict(arguments, flow=flow))
        recipes = dict(catalog.recipe_rows)
        recipes[operation.row] = replace(recipes[operation.row], operations=parse_recipe("VT_TEST"))
        with self.assertRaisesRegex(MarginTestCompileError, "RECIPE.INVALID"):
            compile_margin_plans(**dict(arguments, recipe_rows=recipes))
        self.assertEqual(dict(compile_margin_plans((), {}, None, (), None, {})), {})
        for text in ("MARGIN_TEST(repair)", "MARGIN_TEST(iterations=8)"):
            with self.assertRaises(FlowCompileError):
                parse_recipe(text)

    def test_disabled_readid_cannot_supply_enabled_margin(self):
        catalog = self.compilation.plan.catalogs
        margin = next(p for p in catalog.margin_plans.values() if p.test.gate)
        producer = next(p for p in catalog.id_module_plans.values() if p.steps[0].module_plan is margin.test.gate)
        cp = self.compilation.for_cp(margin.cp)
        schedule = cp.canonical_schedule
        definition = next(d for d in schedule.definitions if producer.excel_row in d.source_rows)
        schedule = replace(schedule, entries=tuple(replace(e, enabled=False)
            if e.definition_id == definition.identity else e for e in schedule.entries))
        cp_plans = dict(self.compilation.plan.cp_plans)
        cp_plans[margin.cp] = replace(cp, scheduling=replace(cp.scheduling, canonical=schedule))
        with self.assertRaisesRegex(MarginTestCompileError, "GATE.PRODUCER_DISABLED"):
            validate_margin_gate_schedule(catalog.margin_plans, catalog.id_module_plans, cp_plans)

    def test_both_platforms_build_all_margin_rows_without_input_reopening(self):
        for platform in ("chroma", "s100"):
            for cp in ("CP1", "CP2", "CP3"):
                with self.subTest(platform=platform, cp=cp):
                    render = self.build_program(platform, cp)
                    source = next(a.content.decode("gbk") for a in render.artifacts
                                  if a.relative_path.endswith(".pln" if platform == "chroma" else ".prg"))
                    self.assertIn("bool VTEN_FLAG = false;", source)
                    self.assertIn("if(VTEN_FLAG)", source)
                    self.assertNotIn("set_all_final_vposp", source)
                    self.assertNotIn("ENABLE_BY_MARK_NO", source)
                    for plan in self.compilation.plan.catalogs.margin_plans.values():
                        if plan.cp != cp:
                            continue
                        definition = next(d for d in self.compilation.for_cp(cp).canonical_schedule.definitions
                                          if plan.excel_row in d.source_rows)
                        self.assertIn(definition.render_name, source)
                        if plan.test.gate:
                            symbol = plan.test.gate.gate_symbol
                            declaration = f"LUINT {symbol};" if platform == "chroma" else f"int {symbol}[MAX_SITE];"
                            self.assertEqual(source.count(declaration), 1)

    @classmethod
    def build_program(cls, platform, cp, compilation=None, *, kinds=("MARGIN",)):
        compilation = compilation or cls.compilation
        target = TargetKey(platform, cp, "lab", f"MARGIN_{platform}_{cp}")
        facts = compile_platform_program_facts(cls.workbook, target)
        catalog = compilation.plan.catalogs
        selected = tuple((kind, tuple(p for p in getattr(catalog, kind.lower() + "_plans").values()
                                      if p.cp == cp)) for kind in kinds)
        ids = tuple(p for p in catalog.id_module_plans.values()
                    if p.cp == cp and any(p.steps[0].module_plan is m.test.gate
                                         for _, plans in selected for m in plans))
        with patch.object(WorkbookReader, "read", side_effect=AssertionError("workbook reopened")), \
             patch.object(WorkbookModel, "dataframe", side_effect=AssertionError("downstream workbook read")):
            producer = GeneratedPatternProducer.from_compilation(compilation, platform,
                fallback=WorkspacePatternProducer(WORKSPACE_ROOT / "input" / platform)).for_target(facts)
            context = TypedKindContext(compilation, target, facts, producer)
            assemblies = tuple(NATIVE_TYPED_KIND_REGISTRY.compile(kind, plans, context)
                               for kind, plans in (("ID", ids), *selected))
            return PlatformProgramBuilder(producer).build(ProgramAssemblyInput(
                target, facts, compilation.for_cp(cp).canonical_schedule,
                tuple(c for a in assemblies for c in a.contributions),
                tuple(b for a in assemblies for b in a.bodies),
                compilation.for_cp(cp).runtime_state.declarations))


if __name__ == "__main__":
    unittest.main()
