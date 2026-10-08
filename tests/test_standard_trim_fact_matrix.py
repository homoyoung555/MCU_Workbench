"""STANDARD_TRIM / Hsi_8M CP1 domain-fact forensic package tests.

The package is read-only: it consumes ONLY the already-compiled typed facts of
a ProductCompilation (TrimSpec, canonical schedule, TestDefinition, plan
groups, TargetPlatformProfile).  It never reads Excel raw objects, ``G``,
legacy writers, Golden output, or scans the filesystem, and it must stop at
"pending confirmation" because not all seven domain contracts have a complete
authoritative typed source.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import ast
import unittest

from tests.workspace_paths import FORMAL_MASTER as EXTERNAL_FORMAL_MASTER

from program_gen.compiler import ProductCompiler
from program_gen.forensics.standard_trim_matrix import (
    CONTRACTS,
    DomainFact,
    FactStatus,
    build_fact_matrix,
    extract_snapshot,
    pending_adjudication_questions,
    render_html,
    typed_contracts_complete,
)
from program_gen.workbook import WorkbookReader


ROOT = Path(__file__).resolve().parents[1]
FORMAL_MASTER = EXTERNAL_FORMAL_MASTER
REPORT_ARTIFACT = (
    ROOT / "program_gen" / "forensics" / "STANDARD_TRIM_Hsi_8M_CP1_fact_matrix.html"
)
GENERATOR_SOURCE = ROOT / "program_gen" / "forensics" / "standard_trim_matrix.py"


class StandardTrimFactMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()

    def _snapshot(self, platform: str = "chroma"):
        return extract_snapshot(
            self.compilation,
            cp="CP1",
            item="Hsi_8M",
            platform=platform,
            variant="lab",
            program_name="V_TEST_CP1",
        )

    # ------------------------------------------------------------------
    # Matrix shape: every contract is covered with valid statuses.
    # ------------------------------------------------------------------

    def test_matrix_covers_all_seven_contracts(self):
        for platform in ("chroma", "s100"):
            with self.subTest(platform=platform):
                snapshot = self._snapshot(platform)
                facts = build_fact_matrix(snapshot)
                covered = {fact.contract for fact in facts}
                self.assertEqual(covered, set(CONTRACTS))
                for fact in facts:
                    self.assertIn(
                        fact.status, (FactStatus.CONFIRMED, FactStatus.MISSING,
                                      FactStatus.CONTRADICTED)
                    )
                    self.assertTrue(fact.fact_name.strip())
                    self.assertTrue(fact.scope.strip())
                    self.assertTrue(fact.typed_producer.strip())
                    self.assertTrue(fact.authority.strip())
                    self.assertTrue(fact.value.strip())

    def test_matrix_stops_at_pending_confirmation(self):
        # Not all seven contracts have a complete authoritative typed source,
        # so the package must NOT offer a model interface draft.
        for platform in ("chroma", "s100"):
            with self.subTest(platform=platform):
                snapshot = self._snapshot(platform)
                facts = build_fact_matrix(snapshot)
                self.assertFalse(typed_contracts_complete(facts))
                questions = pending_adjudication_questions(snapshot, facts)
                self.assertTrue(questions)

    # ------------------------------------------------------------------
    # Confirmed typed values pinned for Hsi_8M CP1.
    # ------------------------------------------------------------------

    def test_confirmed_power_fbist_measurement_facts(self):
        snapshot = self._snapshot()
        self.assertEqual(snapshot.cp, "CP1")
        self.assertEqual(snapshot.item, "Hsi_8M")
        self.assertEqual(snapshot.typed_kind, "STANDARD_TRIM")
        self.assertEqual(snapshot.mode, "fbist")
        # PowerContract
        self.assertEqual(snapshot.vcc, "VCC_TYP")
        # FbistContract
        self.assertEqual(snapshot.protocol_enter_pattern, "enter_fbist_mode")
        self.assertEqual(snapshot.protocol_exit_pattern, "exit_fbist_mode")
        self.assertEqual(snapshot.chroma_enter_pattern_path, "pat/enter_fbist_mode.pat")
        self.assertEqual(snapshot.s100_enter_pattern_path, "enter_fbist_mode.sd")
        # MeasurementContract
        self.assertEqual(snapshot.measurement_family, "FREQUENCY")
        self.assertEqual(snapshot.measurement_unit, "KHz")
        self.assertEqual(snapshot.measurement_pin, "TP")
        self.assertEqual(snapshot.measurement_force, "/")
        self.assertEqual(snapshot.measurement_target, 125)
        self.assertEqual(snapshot.measurement_low_limit, "0.4%")
        self.assertEqual(snapshot.measurement_high_limit, "0.4%")
        self.assertEqual(snapshot.dac_pattern_name, "set_hsi_8m_dac")
        self.assertEqual(snapshot.dac_field_width, 10)
        self.assertEqual(snapshot.dac_default_value, "0000000000")
        self.assertEqual(snapshot.search_bits, 10)
        self.assertEqual(snapshot.search_variant_kinds, ("BISECTION", "FULL_SCAN"))
        self.assertEqual(snapshot.search_scheduled_kinds, ("BISECTION",))
        self.assertEqual(snapshot.dac_final_symbol, "HSI_8M_DAC_FINAL")

    def test_confirmed_schedule_and_plan_group_facts(self):
        snapshot = self._snapshot()
        self.assertEqual(snapshot.definition_identity, "DEF:CP1:trim:Hsi_8M:(12,)")
        self.assertEqual(snapshot.definition_render_name, "Hsi_8M_Trim")
        self.assertEqual(len(snapshot.schedule_entries), 2)
        self.assertIn("Hsi_8M_Trim", snapshot.schedule_entries[0])
        self.assertIn("Hsi_8M_Dac_Loop", snapshot.schedule_entries[1])
        self.assertIn("enabled=True", snapshot.schedule_entries[0])
        self.assertIn("enabled=False", snapshot.schedule_entries[1])
        self.assertEqual(snapshot.hardware_bin, "9")
        self.assertEqual(snapshot.software_bin, "9")
        self.assertEqual(
            snapshot.environment_catalogs, ("PIN", "LEVEL", "TIMING", "RELAY", "BIN")
        )
        self.assertEqual(snapshot.lifecycle_contributions, ())
        self.assertEqual(snapshot.runtime_symbol, "HSI_8M_DAC_FINAL")
        self.assertEqual(snapshot.runtime_symbol_width, 10)
        self.assertEqual(snapshot.effective_recipe, ("ENTER", "DEPEND", "TRIM", "JUDGE"))

    # ------------------------------------------------------------------
    # No defaults: timing facts stay MISSING when the mother says nothing.
    # ------------------------------------------------------------------

    def test_timing_waits_are_missing_without_defaults(self):
        snapshot = self._snapshot()
        self.assertIsNone(snapshot.enter_wait)
        self.assertIsNone(snapshot.trim_force_wait)
        self.assertIsNone(snapshot.trim_set_wait)
        self.assertIsNone(snapshot.judge_force_wait)
        self.assertIsNone(snapshot.judge_set_wait)
        self.assertFalse(snapshot.per_point_wait_any)
        facts = build_fact_matrix(snapshot)
        timing = [fact for fact in facts if fact.contract == "TimingContract"]
        missing = [fact for fact in timing
                   if fact.fact_name in ("ENTER WAIT", "TRIM FWAIT（Force 等待）",
                                         "TRIM SWAIT（Set DAC 等待）",
                                         "JUDGE FWAIT / SWAIT")]
        self.assertEqual(len(missing), 4)
        for fact in missing:
            self.assertIs(fact.status, FactStatus.MISSING)
            self.assertIn("不注入默认值", fact.value)

    # ------------------------------------------------------------------
    # Relay facts are absent from the typed layer by design.
    # ------------------------------------------------------------------

    def test_relay_value_is_missing_in_typed_layer(self):
        facts = build_fact_matrix(self._snapshot())
        relay = next(
            fact for fact in facts
            if fact.contract == "RelayContract"
            and fact.fact_name == "每目标 relay 值（FLOW 'relay' 列）"
        )
        self.assertIs(relay.status, FactStatus.MISSING)
        self.assertIn("ProductCompilation", relay.value)
        self.assertIn("typed", relay.value)

    # ------------------------------------------------------------------
    # The FBIST protocol resource-closure divergence is resolved: the CP
    # closure now owns the Recipe-declared enter/exit patterns.
    # ------------------------------------------------------------------

    def test_fbist_protocol_resource_closure_contradiction_is_resolved(self):
        snapshot = self._snapshot()
        self.assertTrue(snapshot.fbist_protocol_in_resources)
        facts = build_fact_matrix(snapshot)
        contradictions = [
            fact for fact in facts if fact.status is FactStatus.CONTRADICTED
        ]
        self.assertEqual(contradictions, [])
        resource_fact = next(
            fact for fact in facts
            if fact.contract == "FbistContract"
            and fact.fact_name == "FBIST 协议 Pattern 的资源闭包归属"
        )
        self.assertIs(resource_fact.status, FactStatus.CONFIRMED)
        self.assertIn("enter_fbist_mode", resource_fact.value)
        self.assertIn("exit_fbist_mode", resource_fact.value)
        self.assertIn("SC.RESOURCE.CLOSURE_MISSING", resource_fact.value)

    def test_fbist_protocol_resource_fact_detects_divergence(self):
        # If the CP closure ever stops owning the protocol patterns, the fact
        # must flip back to CONTRADICTED instead of silently passing.
        divergent = replace(self._snapshot(), fbist_protocol_in_resources=False)
        facts = build_fact_matrix(divergent)
        resource_fact = next(
            fact for fact in facts
            if fact.contract == "FbistContract"
            and fact.fact_name == "FBIST 协议 Pattern 的资源闭包归属"
        )
        self.assertIs(resource_fact.status, FactStatus.CONTRADICTED)
        self.assertIn("相互矛盾", resource_fact.value)

    # ------------------------------------------------------------------
    # HTML report content.
    # ------------------------------------------------------------------

    def test_html_report_marks_statuses_and_stops_at_pending(self):
        snapshot = self._snapshot()
        facts = build_fact_matrix(snapshot)
        questions = pending_adjudication_questions(snapshot, facts)
        document = render_html(snapshot, facts, questions)
        self.assertIn("待确认", document)
        self.assertIn("不提出模型接口草案", document)
        self.assertIn("仅消费 WorkbookModel / ProductCompilation", document)
        self.assertIn("Golden", document)
        for contract in CONTRACTS:
            self.assertIn(contract, document)
        for status in ("CONFIRMED", "MISSING", "CONTRADICTED"):
            self.assertIn(f"class=\"{status}\"", document)
        self.assertIn("待蛤蟆羊先生裁决的问题", document)

    def test_html_artifact_matches_generator_output(self):
        # The checked-in report artifact must be byte-identical to what the
        # pure generator renders from the same compiled typed facts.
        snapshot = self._snapshot()
        facts = build_fact_matrix(snapshot)
        questions = pending_adjudication_questions(snapshot, facts)
        expected = render_html(snapshot, facts, questions)
        actual = REPORT_ARTIFACT.read_text(encoding="utf-8")
        self.assertEqual(actual, expected)

    # ------------------------------------------------------------------
    # Purity: the generator never touches G / legacy writers / Golden /
    # filesystem scanning / workbook objects.
    # ------------------------------------------------------------------

    def test_report_generator_is_pure(self):
        source = GENERATOR_SOURCE.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertFalse(
            {
                "openpyxl", "pandas", "os", "pathlib", "shutil", "subprocess",
                "program_gen.state", "program_gen.workbook", "program_gen.platforms",
                "tools",
            } & imports
        )
        calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertFalse(
            {"open", "read_bytes", "glob", "rglob", "listdir", "scandir"} & calls
        )
        attributes = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
        }
        self.assertNotIn("read_bytes", attributes)
        from_import_modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        # The only program_gen dependency is the pure shadow profile authority;
        # everything else (workbook, state, platforms, tools) is forbidden.
        self.assertFalse(
            {
                "program_gen.state", "program_gen.workbook",
                "program_gen.platforms", "tools",
            } & from_import_modules
        )
        program_gen_modules = {
            module for module in from_import_modules
            if module == "program_gen" or module.startswith("program_gen.")
        }
        self.assertEqual(program_gen_modules, {"program_gen.shadow.profile"})

    def test_snapshot_extraction_only_consumes_compilation(self):
        # extract_snapshot reads only the compiled graph; it must not open the
        # workbook again (proven by the purity scan above plus a spot check on
        # the compiled identities it carries).
        snapshot = self._snapshot()
        self.assertEqual(snapshot.workbook_identity, self.workbook.identity)
        self.assertEqual(
            snapshot.compilation_identity, self.compilation.identity
        )


if __name__ == "__main__":
    unittest.main()
