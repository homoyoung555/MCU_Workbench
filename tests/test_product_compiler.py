from tests.workspace_paths import FORMAL_MASTER as EXTERNAL_FORMAL_MASTER
import ast
from collections import Counter
from pathlib import Path
import unittest
from unittest.mock import patch

from preflight import ERROR, WARN, check_master
from program_gen.compiler import ProductCompiler
from program_gen.program_plan import ProgramPlanError
from program_gen.core.declaration_plan import DeclarationCompileError
from program_gen.core.schedule_plan import SchedulePlanError
from program_gen.workbook import WorkbookReader


ROOT = Path(__file__).resolve().parents[1]
FORMAL_MASTER = EXTERNAL_FORMAL_MASTER
FORMAL_MASTER_SHA256 = "EC90D9FF5D20CF96DB0A6CE78DCE961676AF77F36CE289BF8F64B8C714289003"
FORMAL_DIAGNOSTIC_CODES = Counter({
    "PF.CHAR.FULLWIDTH": 9,
    "PF.CHAR.OUTER_SPACE": 16,
    "PF.RECIPE.MIGRATION_INCOMPLETE": 1,
    "EXPORT.USE_DEF.UNCONSUMED": 1,
})


class ProductCompilerFormalMasterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook)

    def test_formal_master_compiles_to_a_valid_three_cp_product(self):
        self.assertEqual(self.workbook.source_sha256, FORMAL_MASTER_SHA256)
        self.assertTrue(self.compilation.is_valid)
        self.assertEqual(tuple(self.compilation.cp_plans), ("CP1", "CP2", "CP3"))
        for cp in self.compilation.cp_plans:
            self.assertEqual(self.compilation.for_cp(cp).cp, cp)

    def test_formal_diagnostics_are_the_stable_warning_multiset(self):
        diagnostics = self.compilation.diagnostics

        self.assertEqual(len(diagnostics.errors), 0)
        self.assertEqual(len(diagnostics.warnings), 27)
        self.assertEqual(
            Counter(item.code for item in diagnostics.items),
            FORMAL_DIAGNOSTIC_CODES,
        )
        for item in diagnostics.items:
            with self.subTest(code=item.code, location=item.provenance.location):
                self.assertEqual(
                    item.provenance.workbook_identity,
                    self.compilation.workbook_identity,
                )
                self.assertEqual(
                    item.provenance.source_sha256,
                    FORMAL_MASTER_SHA256,
                )
                self.assertTrue(item.remediation.strip())

        temporary = next(
            item for item in diagnostics.warnings
            if item.code == "EXPORT.USE_DEF.UNCONSUMED"
        )
        self.assertIn("CP2/Vrefint", temporary.message)
        self.assertIn("temporary", temporary.remediation.casefold())

    def test_repeat_compile_keeps_the_public_identity_and_diagnostics(self):
        repeated = ProductCompiler().compile(self.workbook)

        self.assertEqual(repeated.identity, self.compilation.identity)
        self.assertEqual(repeated.workbook_identity, self.compilation.workbook_identity)
        self.assertEqual(repeated.workbook_sha256, self.compilation.workbook_sha256)
        self.assertEqual(repeated.diagnostics.items, self.compilation.diagnostics.items)
        self.assertEqual(tuple(repeated.cp_plans), tuple(self.compilation.cp_plans))

    def test_flash_compare_catalog_is_workbook_free_and_complete(self):
        compiled = self.compilation.flash_compare_compilation
        self.assertIs(self.compilation.plan.catalogs.flash_compare_compilation, compiled)
        self.assertEqual(len(compiled.plans), 31)
        self.assertEqual(compiled.unsupported, ())

    def test_standard_verify_catalog_publishes_complete_effective_recipes(self):
        plans = self.compilation.plan.catalogs.standard_verify_plans

        self.assertEqual(len(plans), 59)
        self.assertTrue(all(plan.effective_recipe for plan in plans.values()))
        self.assertTrue(all("ENTER" in plan.effective_recipe for plan in plans.values()))
        self.assertTrue(all("JUDGE" in plan.effective_recipe for plan in plans.values()))
        definitions = tuple(
            definition
            for cp_plan in self.compilation.cp_plans.values()
            for definition in cp_plan.definitions
            if definition.typed_kind == "STANDARD_VERIFY"
        )
        self.assertTrue(definitions)
        self.assertNotIn("LEGACY", {
            module
            for definition in definitions
            for module in definition.effective_recipe
        })

    def test_product_catalog_publishes_explicit_cp1_vrefint_uid_binding(self):
        binding = self.compilation.plan.catalogs.result_bindings.for_symbol(
            "CP1", "VREFINT_EXPORT"
        )

        self.assertEqual(binding.identity.canonical, "CP1:Vrefint:/:VERIFY_RESULT")
        self.assertEqual(binding.encoding, "BCD16_MV")
        self.assertEqual(
            tuple((target.destination, target.page, target.field)
                  for target in binding.targets),
            (("UID", "uid", "Vrefint_Verify"),),
        )

    def test_platform_adapter_views_expose_the_existing_cp_plans(self):
        dedicated = self.compilation.plan.catalogs.dedicated_trim_plans
        self.assertEqual(tuple(dedicated), (7,))
        self.assertEqual(dedicated[7].typed_kind, "PDR_TRIM")
        for cp in ("CP1", "CP2", "CP3"):
            with self.subTest(cp=cp):
                cp_plan = self.compilation.for_cp(cp)
                chroma = self.compilation.adapter_view(cp, "chroma")
                s100 = self.compilation.adapter_view(cp, "s100")

                self.assertEqual(chroma.cp, cp)
                self.assertEqual(s100.cp, cp)
                self.assertIs(chroma.flow_operations, self.compilation.plan.catalogs.flow_operations)
                self.assertIs(s100.flow_operations, self.compilation.plan.catalogs.flow_operations)
                self.assertIs(chroma.dac_write_plans, cp_plan.dac_write_plans)
                self.assertIs(s100.dac_write_plans, cp_plan.dac_write_plans)
                self.assertIs(chroma.result_export_plans, cp_plan.result_export_plans)
                self.assertIs(s100.result_export_plans, cp_plan.result_export_plans)
                self.assertIs(chroma.build_uid_rows, cp_plan.build_uid_rows)
                self.assertIs(s100.build_uid_rows, cp_plan.build_uid_rows)
                self.assertIs(chroma.memory_wakeup_plan, cp_plan.memory_wakeup_plan)
                self.assertIs(s100.memory_wakeup_plan, cp_plan.memory_wakeup_plan)
                self.assertIs(chroma.declarations, cp_plan.runtime_state.declarations)
                self.assertIs(s100.declarations, cp_plan.runtime_state.declarations)
                self.assertIs(chroma.canonical_schedule, cp_plan.canonical_schedule)
                self.assertIs(s100.canonical_schedule, cp_plan.canonical_schedule)
                self.assertIs(s100.persistence_plans, chroma.persistence_plans)
                self.assertIsNotNone(chroma.persistence_plans)
                self.assertEqual(chroma.recipe_rows, s100.recipe_rows)
                self.assertIs(chroma.id_plans, s100.id_plans)
                self.assertIs(chroma.trim_data_plan, s100.trim_data_plan)
                self.assertIs(chroma.addr_map_catalog, s100.addr_map_catalog)
                self.assertIs(chroma.dedicated_trim_plans, dedicated)
                self.assertIs(s100.dedicated_trim_plans, dedicated)
                self.assertEqual(tuple(chroma.os_plans), (0, 95, 167))
                self.assertEqual(tuple(s100.os_plans), (0, 95, 167))
                self.assertEqual(chroma.os_plans[0].platform_profile.value, "chroma")
                self.assertEqual(s100.os_plans[0].platform_profile.value, "s100")

        pdr_definition = next(
            item
            for item in self.compilation.for_cp("CP1").tests.definitions
            if item.item == "Pdr_Trim"
        )
        self.assertEqual(pdr_definition.typed_kind, "PDR_TRIM")
        self.assertEqual(pdr_definition.effective_recipe, ("PDR_TRIM",))

    def test_check_master_projects_a_compilation_without_recompiling(self):
        with patch.object(
            ProductCompiler,
            "compile",
            side_effect=AssertionError("check_master must not re-run ProductCompiler"),
        ) as product_compile, patch(
            "program_gen.compiler.compile_recipe_rows",
            side_effect=AssertionError("check_master must not invoke a core compiler"),
        ) as core_compile:
            findings = check_master(self.compilation)

        product_compile.assert_not_called()
        core_compile.assert_not_called()
        self.assertEqual(sum(item.severity == ERROR for item in findings), 0)
        self.assertEqual(sum(item.severity == WARN for item in findings), 27)


class ProductCompilerBoundaryTests(unittest.TestCase):
    def test_embedded_cp_group_errors_become_stable_compiler_diagnostics(self):
        workbook = WorkbookReader().read(FORMAL_MASTER)
        errors = (
            DeclarationCompileError("DP.DECLARATION.CONFLICT", "conflict"),
            SchedulePlanError("SP.BIN_REFERENCE.MISSING", "missing"),
        )
        for error in errors:
            with self.subTest(code=error.code), patch(
                "program_gen.compiler.compile_program_plan", side_effect=error
            ):
                compilation = ProductCompiler().compile(workbook)
                self.assertFalse(compilation.is_valid)
                self.assertEqual(compilation.diagnostics.errors[0].code, error.code)

    def test_program_plan_contract_error_keeps_its_stable_diagnostic_code(self):
        workbook = WorkbookReader().read(FORMAL_MASTER)
        with patch(
            "program_gen.compiler.compile_program_plan",
            side_effect=ProgramPlanError(
                "PP.RESOURCE.CONFLICT", "logical resource has two specifications"
            ),
        ):
            compilation = ProductCompiler().compile(workbook)

        self.assertFalse(compilation.is_valid)
        self.assertEqual(
            tuple(item.code for item in compilation.diagnostics.errors),
            ("PP.RESOURCE.CONFLICT",),
        )

    def test_entrypoints_do_not_directly_import_or_call_core_compilers(self):
        entrypoints = (
            ROOT / "main.py",
            ROOT / "program_gen" / "platforms" / "chroma" / "main.py",
            ROOT / "program_gen" / "platforms" / "s100" / "main.py",
        )

        for source_path in entrypoints:
            with self.subTest(entrypoint=source_path.relative_to(ROOT).as_posix()):
                tree = ast.parse(source_path.read_text(encoding="utf-8"))
                local_compile_functions = {
                    node.name
                    for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name.startswith("compile_")
                }
                direct_compile_imports = [
                    f"{node.module}.{alias.name}"
                    for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom)
                    and node.module
                    for alias in node.names
                    if alias.name.startswith("compile_")
                ]
                direct_compile_calls = [
                    _call_name(node.func)
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Call)
                    and _is_direct_core_compile_call(node.func, local_compile_functions)
                ]

                self.assertEqual(
                    direct_compile_imports,
                    [],
                    "entrypoint must obtain plans through ProductCompiler, not compile_* imports",
                )
                self.assertEqual(
                    direct_compile_calls,
                    [],
                    "entrypoint must obtain plans through ProductCompiler.compile, not core compile_* calls",
                )

    def test_platform_entrypoints_route_dedicated_pdr_plan_explicitly(self):
        for platform in ("chroma", "s100"):
            source = (
                ROOT / "program_gen" / "platforms" / platform / "main.py"
            ).read_text(encoding="utf-8")
            with self.subTest(platform=platform):
                self.assertIn('kind == "PDR_TRIM"', source)
                self.assertIn("dedicated_trim_plan=", source)

    def test_platform_entrypoints_have_no_unreachable_raw_verify_dispatch(self):
        forbidden = (
            'flow_type = G.col("FLOW", "type")',
            'flow_mode = G.col("FLOW", "mode")',
            'if flow_type[No] == "verify"',
            "is_adc_force",
            "is_comp_row",
            "is_opa_row",
            "is_dac_row",
            "is_freq_row",
            "is_pvd_row",
            "is_dc_scan_item",
        )
        for platform in ("chroma", "s100"):
            source = (
                ROOT / "program_gen" / "platforms" / platform / "main.py"
            ).read_text(encoding="utf-8")
            with self.subTest(platform=platform):
                self.assertEqual(
                    tuple(token for token in forbidden if token in source), ()
                )


def _is_direct_core_compile_call(function, local_compile_functions):
    if isinstance(function, ast.Name):
        return (
            function.id.startswith("compile_")
            and function.id not in local_compile_functions
        )
    return isinstance(function, ast.Attribute) and function.attr.startswith("compile_")


def _call_name(function):
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        return function.attr
    return ast.unparse(function)


if __name__ == "__main__":
    unittest.main()
