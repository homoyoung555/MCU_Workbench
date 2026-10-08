"""UID native compilation through the public product compiler."""

import unittest

from program_gen.compiler import ProductCompiler
from program_gen.workbook import WorkbookReader
from program_gen.registered_recipe_modules import NATIVE_RECIPE_MODULE_REGISTRY
from tests.workspace_paths import FORMAL_MASTER
from tests.workspace_paths import WORKSPACE_ROOT
from program_gen.platform_program import (PlatformProgramBuilder, ProgramAssemblyInput,
    WorkspacePatternProducer, compile_platform_program_facts)
from program_gen.platform_program.pattern import GeneratedPatternProducer
from program_gen.registered_typed_kinds import NATIVE_TYPED_KIND_REGISTRY
from program_gen.typed_kind_registry import TypedKindContext
from program_gen.render_plan import TargetKey


class UidNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()

    def test_formal_uid_commit_has_explicit_pass_and_uid_only_exports(self):
        plans = self.compilation.plan.catalogs.uid_plans
        self.assertEqual(tuple(plans), (94, 102, 166, 174, 205))
        plan = plans[94]
        commit = next(step.module_plan for step in plan.steps if step.module == "COMMIT")
        self.assertEqual({write.page for write in commit.writes}, {"uid"})
        self.assertEqual([(write.field, write.value.token) for write in commit.field_values],
                         [("cp12_id", "0x65FFFFFF")])
        self.assertTrue(any(write.register == "Ts_30C_Verify" for write in commit.writes))
        self.assertIsNone(plan.gate_symbol)

    def test_cp3_commits_exactly_eight_packed_identity_words(self):
        plan = self.compilation.plan.catalogs.uid_plans[205]
        commit = next(s.module_plan for s in plan.steps if s.module == "COMMIT")
        self.assertEqual(len(commit.field_values), 8)
        self.assertTrue(all(len(f.labels) == 1 and f.labels[0].width == 32 for f in commit.field_values))
        self.assertTrue(all(f.value.kind == "VARIABLE" for f in commit.field_values))
        self.assertTrue(all(f.value_type == "uint32_t" for f in commit.field_values))
        text = "\n".join(NATIVE_RECIPE_MODULE_REGISTRY.emit("COMMIT", commit, "s100").statements)
        for field in commit.field_values:
            self.assertIn(f"CALL_MACRO write_pat_temp_long({field.value.token});", text)

    def test_no_uid_operations_require_no_uid_page(self):
        from types import SimpleNamespace
        from program_gen.core.uid_write import compile_uid_write_plans
        plans = compile_uid_write_plans((), {}, None, None, None, None,
            SimpleNamespace(contract=SimpleNamespace(pages=())), swd_pin="", read_bit=32)
        self.assertEqual(dict(plans), {})

    def test_pass_id_is_loaded_into_both_platforms_program_and_compare(self):
        plan = self.compilation.plan.catalogs.uid_plans[94]
        commit = next(step.module_plan for step in plan.steps if step.module == "COMMIT")
        for platform in ("chroma", "s100"):
            with self.subTest(platform=platform):
                text = "\n".join(NATIVE_RECIPE_MODULE_REGISTRY.emit("COMMIT", commit, platform).statements)
                self.assertIn("0x65FFFFFF", text)
                self.assertIn("cp12_id_w", text)
                self.assertIn("cp12_id_r", text)

    def test_bake_loads_only_prior_fields_into_current_cp_id_patterns(self):
        plan = self.compilation.plan.catalogs.uid_plans[102]
        self.assertEqual(plan.gate_symbol, "CP1_BAKEID_NEEDS_WRITE")
        self.assertEqual(tuple(step.module for step in plan.steps if step.gated), ("COMMIT", "PGMOTP"))
        capture, load = plan.steps[0].module_plan, plan.steps[1].module_plan
        self.assertEqual(capture.pages[0].byte_count, 40)
        self.assertEqual(capture.pages[0].capture.pattern.name, "uid_capture")
        self.assertEqual({target.program_pattern for target in load.targets}, {"fbist_page_prog_cp2_id"})
        self.assertNotIn("Ts_125C_Verify", {target.register for target in load.targets})
        self.assertIn("Ts_30C_Verify", {target.register for target in load.targets})
        self.assertEqual(set(capture.pages[0].restore_registers), {target.register for target in load.targets})
        flag = next(field for field in load.field_values if field.field == "cp12_id")
        self.assertEqual(flag.value.token, "0x65FFFFFF")
        self.assertTrue(flag.read_dont_care)
        self.assertTrue(flag.write_program)
        ts = next(field for field in load.field_values if field.field == "Ts_125C_Verify")
        self.assertTrue(ts.read_dont_care)
        self.assertFalse(ts.write_program)
        self.assertFalse(any(field.field == "Ts_30C_Verify" for field in load.field_values))

    def test_cp3_bake_clears_later_pass_fields_and_restores_only_prior_values(self):
        plan = self.compilation.plan.catalogs.uid_plans[174]
        load = plan.steps[1].module_plan
        self.assertEqual(len(load.targets), 12)
        self.assertEqual({t.program_pattern for t in load.targets}, {"fbist_page_prog_cp3_id"})
        fields = {f.field: f for f in load.field_values}
        self.assertEqual(fields["cp34_id"].value.token, "0xFFFFFFFF")
        self.assertEqual(fields["uid_info"].value.token, "0xFFFFFFFF")
        self.assertTrue(fields["cp34_id"].read_dont_care)
        commit = next(s.module_plan for s in plan.steps if s.module == "COMMIT")
        self.assertEqual([(f.field, f.value.token) for f in commit.field_values], [("cp12_id", "0x65BA78BA")])
        # Offsets in the user-verified CP3 golden's 40-byte capture.
        capture = plan.steps[0].module_plan.pages[0]
        offsets, offset = {}, 0
        for entry in capture.layout:
            offsets[entry.register] = offset + entry.real_offset
            offset += entry.slot_width
        self.assertEqual(offsets, {
            "Vrefint_Verify": 2, "Vrefbuf1p024_Verify": 6, "Vrefbuf2p5_Verify": 10,
            "Vrefbuf2p048_Verify": 14, "Vrefbuf2p9_Verify": 18, "Vrefbuf4p096_Verify": 22,
            "Hsi_16M_Trim": 24, "Hsi_8M_Trim": 26, "Hsi_24M_Trim": 28, "Hsi_48M_Trim": 30,
            "Ts_125C_Verify": 34, "Ts_30C_Verify": 38,
        })
        from program_gen.core.flash_label_renderer import render_flash_label_plan
        for platform in ("chroma", "s100"):
            artifact = next(a for a in render_flash_label_plan(self.compilation.flash_label_plan, platform).artifacts
                            if a.pattern_name == capture.capture.pattern.name)
            self.assertEqual(artifact.content.count(b"1K1" if platform == "chroma" else b"PTN_TRIG;"), 320)

    def test_bake_masks_all_identity_labels_and_formal_uid_restores_compare(self):
        plans = self.compilation.plan.catalogs.uid_plans
        for row in (102, 174):
            plan = plans[row]
            variant = next(v for v in self.compilation.flash_label_plan.uid_variants
                           if v.name == plan.cp.lower() + "_id")
            load = next(s.module_plan for s in plan.steps if s.module == "LOADMAP")
            with self.subTest(cp=plan.cp):
                expected = {span for _, spans in variant.identity_labels for span in spans}
                masked = [span for f in load.field_values if f.read_dont_care for span in f.labels]
                self.assertTrue(expected.issubset(masked),
                                sorted(span.read.chroma_start for span in expected - set(masked)))
                self.assertEqual(len(masked), len(set(masked)))
                self.assertEqual(tuple(s.module for s in plan.steps),
                                 ("READOTPMAP", "LOADMAP", "CHECKOTP", "COMMIT", "PGMOTP"))
                lot = [f for f in load.field_values if f.field in ("lot0", "lot1")]
                self.assertEqual(len(lot), 2)
                self.assertTrue(all(not f.write_program for f in lot))
                for platform in ("chroma", "s100"):
                    text = "\n".join(NATIVE_RECIPE_MODULE_REGISTRY.emit("LOADMAP", load, platform).statements)
                    for span in expected:
                        label = span.read.chroma_start if platform == "chroma" else span.read.s100_start
                        line, = [line for line in text.splitlines()
                                 if f"{variant.names.read_pattern}:{label}" in line]
                        self.assertIn(',"X"' if platform == "chroma" else "DATA1=X,DATA0=X", line)

        formal = next(s.module_plan for s in plans[205].steps if s.module == "COMMIT")
        # Simulate stale per-Site compare state: formal UID -> Bake -> formal UID.
        bake = next(s.module_plan for s in plans[174].steps if s.module == "LOADMAP")
        state = {span: False for f in formal.field_values for span in f.labels}
        for _ in range(2):
            state.update((span, f.read_dont_care) for f in bake.field_values for span in f.labels)
            self.assertTrue(all(state[span] for f in formal.field_values for span in f.labels))
            state.update((span, f.read_dont_care) for f in formal.field_values for span in f.labels)
            self.assertFalse(any(state[span] for f in formal.field_values for span in f.labels))
        for platform in ("chroma", "s100"):
            text = "\n".join(NATIVE_RECIPE_MODULE_REGISTRY.emit("COMMIT", formal, platform).statements)
            self.assertNotIn(',"X"', text)
            self.assertNotIn("DATA1=X,DATA0=X", text)

    def test_adapters_use_detached_compiler_inputs_and_supplied_labels(self):
        from dataclasses import replace
        from unittest.mock import patch
        plan = self.compilation.plan.catalogs.uid_plans[94].steps[0].module_plan
        field = plan.field_values[0]
        label = field.labels[0]
        field = replace(field, program_pattern="renamed_program", read_pattern="renamed_compare",
            labels=(replace(label, write=replace(label.write, chroma_start="renamed_write",
                         s100_start="renamed_write_st", s100_end="renamed_write_sp")),))
        detached = replace(plan, writes=(), targets=(), field_values=(field,))
        with patch.object(WorkbookReader, "read", side_effect=AssertionError("workbook reopened")):
            for platform in ("chroma", "s100"):
                emission = NATIVE_RECIPE_MODULE_REGISTRY.emit("COMMIT", detached, platform)
                self.assertIn("renamed_program:renamed_write", "\n".join(emission.statements))
                self.assertEqual({r.logical_identity for r in emission.resource_requires},
                                 {"pattern:renamed_program", "pattern:renamed_compare"})

    def test_uid_rejects_inconsistent_page_scope_and_missing_persisted_module(self):
        from dataclasses import replace
        from program_gen.core.uid_write import compile_uid_write_plans
        catalog = self.compilation.plan.catalogs
        row = catalog.persistence.rows[102]
        variants = (
            replace(row, operations=(replace(row.operations[0], requested_pages=("trim0",)), *row.operations[1:])),
            replace(row, operations=tuple(op for op in row.operations if op.module != "COMMIT")),
        )
        for invalid in variants:
            with self.subTest(operations=invalid.operations), self.assertRaisesRegex(ValueError, "UID\\.(PAGE_SCOPE|RECIPE)"):
                persistence = replace(catalog.persistence, rows={**catalog.persistence.rows, 102: invalid})
                compile_uid_write_plans(
                    tuple(op for op in catalog.flow_operations if op.row == 102), catalog.recipe_rows,
                    persistence, catalog.id_plans, self.workbook.dataframe("FLOW"), catalog.addr_map,
                    self.compilation.flash_label_plan, swd_pin=catalog.fbist_pattern_plan.swd_pin,
                    read_bit=self.compilation.flash_compare_compilation.facts.read_bits)

    def test_bake_explicit_commit_uses_its_compiled_target_patterns(self):
        from dataclasses import replace
        from program_gen.core.uid_write import compile_uid_write_plans
        catalog = self.compilation.plan.catalogs
        row = catalog.persistence.rows[102]
        write = next(write for write in catalog.persistence.rows[166].operation("COMMIT").field_writes
                     if write.page == "uid")
        row = replace(row, operations=tuple(replace(op, field_writes=(write,), commit_source="EXPLICIT")
                      if op.module == "COMMIT" else op for op in row.operations))
        persistence = replace(catalog.persistence, rows={**catalog.persistence.rows, 102: row})
        plans = compile_uid_write_plans(
            tuple(op for op in catalog.flow_operations if op.row == 102), catalog.recipe_rows,
            persistence, catalog.id_plans, self.workbook.dataframe("FLOW"), catalog.addr_map,
            self.compilation.flash_label_plan, swd_pin=catalog.fbist_pattern_plan.swd_pin,
            read_bit=self.compilation.flash_compare_compilation.facts.read_bits)
        commit = next(step.module_plan for step in plans[102].steps if step.module == "COMMIT")
        self.assertEqual({(target.program_pattern, target.read_pattern) for target in commit.targets},
                         {("fbist_page_prog_cp2_id", "fbist_page_read_cp2_id")})

    def test_uid_and_id_close_native_program_with_startup_and_crc(self):
        for platform in ("chroma", "s100"):
            with self.subTest(platform=platform):
                render = self.build_program(platform, "CP3")
                extension = ".pln" if platform == "chroma" else ".prg"
                source = next(a.content.decode("gbk") for a in render.artifacts if a.relative_path.endswith(extension))
                self.assertIn("GetCRC8", source)
                self.assertIn("CP2_BAKEID_NEEDS_WRITE", source)
                self.assertIn("0x65BA78BA", source)
                self.assertIn("BUILD_UID_CP3", source)
                self.assertNotIn("UID_IMAGE", source)
                self.assertNotIn("uid_image_capture", source)
                self.assertNotIn("fbist_page_prog_cp2_bake_id", source)
                self.assertNotIn("fbist_page_read_cp2_bake_id", source)
                self.assertIn("fbist_page_check_cp2_bake_id", source)
                self.assertEqual(source.count("int WAFER_SLOT;"), 1)
                if platform == "chroma":
                    self.assertIn("INPUT_BOX", source)
                    self.assertIn("LOAD_ID_FLAG=1;", source)
                else:
                    self.assertNotIn("INPUT_BOX", source)
                    self.assertIn("#include <stdint.h>", source)
                    self.assertIn("@@MACRO write_pat_temp_long(unsigned int* a)", source)
                    self.assertIn("@@MACRO write_pat_temp_fixed(unsigned int a)", source)

    @classmethod
    def build_program(cls, platform, cp):
        target = TargetKey(platform, cp, "lab", f"UID_{platform}_{cp}")
        facts = compile_platform_program_facts(cls.workbook, target)
        producer = GeneratedPatternProducer.from_compilation(cls.compilation, platform,
            fallback=WorkspacePatternProducer(WORKSPACE_ROOT / "input" / platform)).for_target(facts)
        context = TypedKindContext(cls.compilation, target, facts, producer)
        catalog = cls.compilation.plan.catalogs
        assemblies = [NATIVE_TYPED_KIND_REGISTRY.compile(kind,
            tuple(p for p in plans.values() if p.cp == cp), context)
            for kind, plans in (("UID", catalog.uid_plans), ("ID", catalog.id_module_plans))]
        return PlatformProgramBuilder(producer).build(ProgramAssemblyInput(
            target, facts, cls.compilation.for_cp(cp).canonical_schedule,
            tuple(c for a in assemblies for c in a.contributions),
            tuple(b for a in assemblies for b in a.bodies),
            cls.compilation.for_cp(cp).runtime_state.declarations))


if __name__ == "__main__":
    unittest.main()
