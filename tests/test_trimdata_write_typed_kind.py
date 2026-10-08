"""Formal-master tracer for native TRIMDATA_WRITE."""

import unittest
from dataclasses import replace

from flow_recipe import compile_recipe_rows

from program_gen.compiler import ProductCompiler
from program_gen.core.otp_program import PgmOtpModulePlan
from program_gen.core.trimdata_write import compile_write_page_scopes, compile_trimdata_write_plans
from program_gen.core.commit_module import compile_commit_module_plans
from program_gen.core.input_normalization import normalize_flow_table
from program_gen.core.persistence_recipe import compile_persistence_plan_set
from program_gen.flow_kinds import compile_flow_rows
from program_gen.registered_recipe_modules import NATIVE_RECIPE_MODULE_REGISTRY
from program_gen.platform_program import (
    PlatformProgramBuilder,
    ProgramAssemblyInput,
    WorkspacePatternProducer,
    compile_platform_program_facts,
)
from program_gen.platform_program.pattern import GeneratedPatternProducer
from program_gen.registered_typed_kinds import NATIVE_TYPED_KIND_REGISTRY
from program_gen.render_plan import TargetKey
from program_gen.typed_kind_registry import TypedKindContext
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER, WORKSPACE_ROOT


class TrimdataWriteTypedKindTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()

    def test_formal_master_routes_data_and_five_write_rows_to_same_native_kind(self):
        plans = self.compilation.plan.catalogs.trimdata_write_plans

        self.assertEqual(
            tuple((plan.excel_row, plan.cp, plan.item) for plan in plans.values()),
            (
                (36, "CP1", "Trimdata_Write_Read"),
                (95, "CP1", "Trimdata_Rewrite"),
                (106, "CP2", "Trimdata_Write"),
                (167, "CP2", "Trimdata_Rewrite"),
                (204, "CP3", "Trimdata_Write"),
                (206, "CP3", "Trimdata_Rewrite"),
            ),
        )
        self.assertTrue(all(
            plan.effective_recipe == ("COMMIT", "PGMOTP")
            for plan in plans.values() if plan.excel_row != 36
        ))
        self.assertTrue(all(
            operation.typed_kind == "TRIMDATA_WRITE"
            for operation in self.compilation.plan.catalogs.flow_operations
            if operation.source_type in ("write", "data")
        ))
        self.assertIn("TRIMDATA_WRITE", NATIVE_TYPED_KIND_REGISTRY.registered_kinds)

    def test_cp2_write_tracer_programs_the_three_non_uid_pages(self):
        plan = self.compilation.plan.catalogs.trimdata_write_plans[104]
        pgmotp = next(
            step.module_plan for step in plan.steps if step.module == "PGMOTP"
        )

        self.assertIsInstance(pgmotp, PgmOtpModulePlan)
        self.assertEqual(
            tuple(operation.patterns.page for operation in pgmotp.page_program.page_operations),
            ("trim0", "trim1", "factory23"),
        )
        self.assertFalse(any(
            operation.patterns.is_uid
            for operation in pgmotp.page_program.page_operations
        ))

    def test_cp1_loadmap_write_is_native_and_suppresses_pass_id(self):
        plans = self.compilation.plan.catalogs.trimdata_write_plans
        self.assertIn(34, plans)
        plan = plans[34]
        self.assertEqual(plan.effective_recipe, ("LOADMAP", "PGMOTP"))
        load, pgm = (step.module_plan for step in plan.steps)
        self.assertEqual(load.target_pages, ("uid", "trim0", "trim1", "factory23"))
        self.assertEqual(
            [(write.page, write.word_index, write.value) for write in load.word_writes],
            [("uid", 5, 0xFFFFFFFF)],
        )
        self.assertEqual(
            tuple(op.patterns.page for op in pgm.page_program.page_operations),
            load.target_pages,
        )
        build = self.compilation.plan.catalogs.flash_window_plans[33].steps[0].module_plan
        registers = {reg.register: reg for reg in build.registers}
        self.assertIn("Vrefint_Verify", registers)
        self.assertEqual(registers["Vrefint_Verify"].default_value, 0xFFFF)
        self.assertTrue(registers["Hsi_8M_Trim"].writes)

    def test_uid_with_only_verify_is_not_early_programmed(self):
        catalog = self.compilation.plan.catalogs.addr_map
        verify_only = replace(catalog, registers=tuple(
            reg for reg in catalog.registers
            if reg.page.casefold() != "uid" or reg.register.endswith("_Verify")
        ), _fields_by_name={
            name: tuple(field for field in fields
                        if field.page.casefold() != "uid" or field.register.endswith("_Verify"))
            for name, fields in catalog._fields_by_name.items()
        })
        scopes = compile_write_page_scopes(
            self.workbook.dataframe("FLOW"), self.compilation.plan.catalogs.recipe_rows,
            verify_only,
        )
        self.assertEqual(scopes[36], ("trim0", "trim1", "factory23"))
        plan = self._compile_write_row(self.workbook.dataframe("FLOW"), verify_only)
        self.assertFalse(plan.steps[0].module_plan.word_writes)
        self.assertNotIn("uid", tuple(
            page.patterns.page for page in plan.steps[-1].module_plan.page_program.page_operations
        ))

    def test_early_uid_write_has_no_failed_site_cleanup_or_extra_scope(self):
        pgm = self.compilation.plan.catalogs.trimdata_write_plans[34].steps[-1].module_plan
        for platform in ("chroma", "s100"):
            with self.subTest(platform=platform):
                source = "\n".join(NATIVE_RECIPE_MODULE_REGISTRY.emit("PGMOTP", pgm, platform).statements)
                self.assertEqual(source.count("POWER_ON"), 1)
                self.assertEqual(source.count("POWER_OFF"), 1)
                self.assertNotIn("shift_site", source)
                self.assertNotIn("uidReadFailed", source)
                self.assertNotIn("{", source)
        self.assertTrue(all(op.actions == ("ERASE", "PROGRAM", "READ_CHECK")
                            for op in pgm.page_program.page_operations))

    def test_early_loadmap_does_not_fill_uid_verify_values_or_defaults(self):
        load = self.compilation.plan.catalogs.trimdata_write_plans[34].steps[0].module_plan
        self.assertEqual({target.register for target in load.targets if target.page == "uid"},
                         {"Hsi_8M_Trim", "Hsi_16M_Trim", "Hsi_24M_Trim", "Hsi_48M_Trim"})
        for platform in ("chroma", "s100"):
            with self.subTest(platform=platform):
                source = "\n".join(NATIVE_RECIPE_MODULE_REGISTRY.emit("LOADMAP", load, platform).statements)
                self.assertNotIn("VERIFY", source)
                self.assertNotIn(":vrefint_", source)
                self.assertNotIn(":ts_30c_", source)
                self.assertIn("REG_HSI_8M_TRIM", source)
                self.assertIn("0xFFFFFFFF", source)
        self.assertEqual([(write.word_index, write.value) for write in load.word_writes],
                         [(5, 0xFFFFFFFF)])

    def test_write_type_accepts_explicit_loadmap_and_additional_commit(self):
        flow = self.workbook.dataframe("FLOW")
        flow.loc[34, "type"] = "write"
        flow.loc[34, "Recipe"] = "LOADMAP-COMMIT-PGMOTP"
        plan = self._compile_write_row(flow, self.compilation.plan.catalogs.addr_map)
        self.assertEqual(plan.effective_recipe, ("LOADMAP", "COMMIT", "PGMOTP"))
        self.assertEqual(plan.steps[0].module_plan.word_writes[0].value, 0xFFFFFFFF)

    def _compile_write_row(self, flow, catalog):
        flow = normalize_flow_table(flow)
        recipes = compile_recipe_rows(flow, self.workbook.dataframe("pattern"))
        persistence = compile_persistence_plan_set(
            flow, recipes, catalog,
            node_write_pages=compile_write_page_scopes(flow, recipes, catalog),
            node_default_bindings={
                row + 2: bindings for row, bindings
                in self.compilation.plan.catalogs.default_commit_bindings.items()
            },
        )
        labels = self.compilation.flash_label_plan.contract
        commits = compile_commit_module_plans(persistence, catalog, swd_pin="PA13", flash_labels=labels)
        operations = compile_flow_rows(flow, workbook_identity="fixture", source_sha256="fixture")
        return compile_trimdata_write_plans(
            tuple(op for op in operations if op.row == 34), persistence, commits, flow, labels,
            catalog=catalog, swd_pin="PA13", recipe_rows=recipes,
        )[34]

    def test_loadmap_suppresses_pass_in_both_patterns_on_both_platforms(self):
        load = self.compilation.plan.catalogs.trimdata_write_plans[34].steps[0].module_plan
        for platform in ("chroma", "s100"):
            with self.subTest(platform=platform):
                emission = NATIVE_RECIPE_MODULE_REGISTRY.emit("LOADMAP", load, platform)
                source = "\n".join(emission.statements)
                self.assertIn("0xFFFFFFFF", source)
                self.assertIn("fbist_page_prog_cp1_id:cp12_id_w", source)
                self.assertIn("fbist_page_read_cp1_id:cp12_id_r", source)
                self.assertIn("REG_HSI_8M_TRIM", source)
                self.assertNotIn("0x65FFFFFF", source)
                if platform == "s100":
                    self.assertIn("CALL_MACRO write_pat_temp_fixed(0xFFFFFFFF);", source)
                    self.assertNotIn("GB[", source)

    def test_cp3_commit_may_refresh_uid_but_bare_pgmotp_does_not_program_it(self):
        plan = self.compilation.plan.catalogs.trimdata_write_plans[202]
        commit = next(step.module_plan for step in plan.steps if step.module == "COMMIT")
        pgmotp = next(step.module_plan for step in plan.steps if step.module == "PGMOTP")

        self.assertIn("uid", {target.page.casefold() for target in commit.targets})
        self.assertNotIn(
            "uid",
            {
                operation.patterns.page.casefold()
                for operation in pgmotp.page_program.page_operations
            },
        )

    def test_s100_loadmap_and_commit_invert_each_complemented_register_once(self):
        plans = self.compilation.plan.catalogs.trimdata_write_plans
        for module, plan in (
            ("LOADMAP", plans[34].steps[0].module_plan),
            ("COMMIT", plans[202].steps[0].module_plan),
        ):
            source = "\n".join(NATIVE_RECIPE_MODULE_REGISTRY.emit(module, plan, "s100").statements)
            for target in plan.targets:
                with self.subTest(module=module, register=target.register):
                    expected = int({label.polarity for label in target.labels} == {"p", "n"})
                    self.assertEqual(source.count(f"CALL_MACRO Bitwise_not_arry({target.register_symbol});"), expected)

    def test_write_tracers_close_the_full_dual_platform_resource_graph(self):
        for platform, row in ((p, r) for p in ("chroma", "s100") for r in (34, 104)):
            plan = self.compilation.plan.catalogs.trimdata_write_plans[row]
            with self.subTest(platform=platform, cp=plan.cp):
                target = TargetKey(platform, plan.cp, "lab", f"TRIMDATA_WRITE_{platform}")
                facts = compile_platform_program_facts(self.workbook, target)
                fallback = WorkspacePatternProducer(WORKSPACE_ROOT / "input" / platform)
                producer = GeneratedPatternProducer.from_compilation(
                    self.compilation, platform, fallback=fallback,
                ).for_target(facts)
                assembly = NATIVE_TYPED_KIND_REGISTRY.compile(
                    "TRIMDATA_WRITE", (plan,),
                    TypedKindContext(self.compilation, target, facts, producer),
                )
                render = PlatformProgramBuilder(producer).build(ProgramAssemblyInput(
                    target=target,
                    platform_facts=facts,
                    canonical_schedule=self.compilation.for_cp(plan.cp).canonical_schedule,
                    contributions=assembly.contributions,
                    bodies=assembly.bodies,
                    runtime_declarations=self.compilation.for_cp(plan.cp).runtime_state.declarations,
                ))
                source = assembly.bodies[0].fragment.content.decode("gbk")
                self.assertEqual(source.count("POWER_ON"), 1)
                self.assertEqual(source.count("POWER_OFF"), 1)
                self.assertLess(source.index("set_all_final_vposp"), source.index("fbist_page_erase_trim0"))
                self.assertGreater(len(render.artifacts), 1)
                if platform == "s100" and row == 34:
                    program = next(artifact.content.decode("gbk") for artifact in render.artifacts
                                   if artifact.relative_path.endswith(".prg"))
                    self.assertIn("@@MACRO Bitwise_not_arry(int* a)", program)
                    self.assertIn("@@MACRO write_pat_temp_fixed(unsigned int a)", program)


if __name__ == "__main__":
    unittest.main()
