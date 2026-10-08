from tests.workspace_paths import FORMAL_MASTER as EXTERNAL_FORMAL_MASTER
from pathlib import Path
import unittest

import pandas as pd

from program_gen.compiler import ProductCompiler
from program_gen.program_plan import (
    AllActiveSites,
    ResourceClosureState,
    ProgramPlanError,
    SemanticDependency,
    SymbolCardinality,
    SymbolLifetime,
    SymbolRef,
    RuntimeSymbol,
    RuntimeSymbolUse,
    compile_program_plan,
    validate_runtime_state,
    validate_semantic_dependencies,
)
from program_gen.workbook import WorkbookReader


ROOT = Path(__file__).resolve().parents[1]
FORMAL_MASTER = EXTERNAL_FORMAL_MASTER
SEMANTIC_GROUPS = (
    "IDENTITY",
    "ENVIRONMENT",
    "RUNTIME_STATE",
    "LIFECYCLE",
    "HELPERS",
    "TESTS",
    "SCHEDULE",
    "RESOURCES",
)


class ProgramPlanIntegrationTests(unittest.TestCase):
    def test_formal_compilation_exposes_a_deterministic_eight_group_cp_plan(self):
        workbook = WorkbookReader().read(FORMAL_MASTER)

        first = ProductCompiler().compile(workbook).require_success().plan
        second = ProductCompiler().compile(workbook).require_success().plan

        self.assertEqual(first.identity, second.identity)
        self.assertEqual(first.canonical_json(), second.canonical_json())
        self.assertEqual(tuple(first.cp_plans), ("CP1", "CP2", "CP3"))
        for cp, cp_plan in first.cp_plans.items():
            with self.subTest(cp=cp):
                self.assertEqual(cp_plan.semantic_groups, SEMANTIC_GROUPS)
                self.assertTrue(cp_plan.definitions)
                self.assertTrue(cp_plan.schedule)
                scheduled = {entry.definition_id for entry in cp_plan.schedule}
                by_item = {item.item: item for item in cp_plan.definitions}
                self.assertIn(by_item["NM_Data_Read"].identity, scheduled)
                self.assertIn(by_item["OTP_READ"].identity, scheduled)
                self.assertEqual(cp_plan.canonical_schedule.cp, cp)
                self.assertIn(
                    by_item["OTP_READ"].identity,
                    tuple(
                        entry.definition_id
                        for entry in cp_plan.canonical_schedule.entries
                    ),
                )
                self.assertEqual(by_item["OTP_READ"].source_rows, ())
                self.assertEqual(by_item["NM_Data_Read"].source_rows, ())
                self.assertTrue(all(
                    definition.typed_kind
                    for definition in cp_plan.definitions
                ))
                self.assertTrue(all(
                    definition.family
                    for definition in cp_plan.definitions
                ))
                self.assertIsInstance(cp_plan.runtime_state.site_scope, AllActiveSites)
                self.assertEqual(cp_plan.runtime_state.declarations.cp, cp)
                self.assertIn(
                    "REG_HSI_8M_TRIM",
                    cp_plan.runtime_state.declarations.names,
                )
                self.assertEqual(
                    cp_plan.resources.state, ResourceClosureState.DISCOVERED
                )
                self.assertFalse(cp_plan.resources.closure_complete)
                self.assertEqual(cp_plan.lifecycle.contributions, ())

    def test_product_compilation_has_one_authoritative_cp_plan_tree(self):
        workbook = WorkbookReader().read(FORMAL_MASTER)
        compilation = ProductCompiler().compile(workbook).require_success()

        self.assertNotIn("_plan", compilation.__dataclass_fields__)
        self.assertNotIn("cp_plans", compilation.__dataclass_fields__)
        for cp, cp_plan in compilation.plan.cp_plans.items():
            self.assertIs(compilation.for_cp(cp), cp_plan)
            self.assertIs(compilation.cp_plans[cp], cp_plan)

    def test_persistence_state_uses_immutable_page_and_pattern_versions(self):
        workbook = WorkbookReader().read(FORMAL_MASTER)
        cp1 = ProductCompiler().compile(workbook).require_success().for_cp("CP1")

        transitions = cp1.runtime_state.page_timeline.transitions
        self.assertTrue(transitions)
        for transition in transitions:
            self.assertEqual(transition.after.cp, "CP1")
            if transition.action == "COMMIT":
                self.assertIsNotNone(transition.before)
                self.assertEqual(
                    transition.after.generation,
                    transition.before.generation + 1,
                )
        prepared = cp1.runtime_state.prepared_patterns
        self.assertTrue(prepared)
        self.assertTrue(all(item.page_input.cp == "CP1" for item in prepared))

    def test_runtime_state_rejects_missing_and_forward_symbol_references(self):
        ref = SymbolRef("CP1", "RESULT", "DAC_FINAL")
        with self.assertRaisesRegex(ProgramPlanError, "PP.SYMBOL.MISSING"):
            validate_runtime_state(
                definitions=(),
                uses=(RuntimeSymbolUse("CP1", ref, consumer_order=2),),
            )

    def test_runtime_state_rejects_conflicting_symbol_definitions(self):
        with self.assertRaisesRegex(ProgramPlanError, "PP.SYMBOL.CONFLICT"):
            validate_runtime_state(
                definitions=(
                    RuntimeSymbol(SymbolRef("CP1", "RESULT", "RESULT"), 1, value_type="INT", bit_width=16),
                    RuntimeSymbol(SymbolRef("CP1", "RESULT", "RESULT"), 1, value_type="FLOAT", bit_width=32),
                ),
                uses=(),
            )

    def test_runtime_state_rejects_cross_cp_runtime_references(self):
        with self.assertRaisesRegex(ProgramPlanError, "PP.SYMBOL.CROSS_CP_RUNTIME"):
            validate_runtime_state(
                definitions=(RuntimeSymbol(SymbolRef("CP1", "RESULT", "RESULT"), 1),),
                uses=(
                    RuntimeSymbolUse(
                        "CP2", SymbolRef("CP1", "RESULT", "RESULT"), consumer_order=2
                    ),
                ),
            )

    def test_semantic_dependency_cycle_is_rejected_before_rendering(self):
        with self.assertRaisesRegex(ProgramPlanError, "PP.DEPENDENCY.CYCLE"):
            validate_semantic_dependencies((
                SemanticDependency("A", depends_on=("B",)),
                SemanticDependency("B", depends_on=("A",)),
            ))

        with self.assertRaisesRegex(ProgramPlanError, "PP.SYMBOL.FORWARD_REFERENCE"):
            validate_runtime_state(
                definitions=(RuntimeSymbol(SymbolRef("CP1", "RESULT", "DAC_FINAL"), producer_order=3),),
                uses=(RuntimeSymbolUse("CP1", SymbolRef("CP1", "RESULT", "DAC_FINAL"), consumer_order=2),),
            )

    def test_runtime_symbols_have_typed_scope_and_lifetime(self):
        symbol = RuntimeSymbol(
            SymbolRef("CP1", "RESULT", "ADC_RESULT"),
            producer_order=1,
            cardinality=SymbolCardinality.SITE,
            lifetime=SymbolLifetime.CP,
        )
        table = validate_runtime_state(definitions=(symbol,), uses=())

        self.assertIs(table["CP1.RESULT.ADC_RESULT"], symbol)

    def test_nonconsecutive_same_item_is_not_merged_but_subrows_are(self):
        flow = pd.DataFrame((
            {"CP NO": "CP1", "item": "A", "type": "verify", "mode": "fbist", "FV/FI": "/", "sub": "s1"},
            {"CP NO": "CP1", "item": "A", "type": "verify", "mode": "fbist", "FV/FI": "/", "sub": "s2"},
            {"CP NO": "CP1", "item": "B", "type": "read", "mode": "/", "FV/FI": "/", "sub": ""},
            {"CP NO": "CP1", "item": "A", "type": "verify", "mode": "fbist", "FV/FI": "/", "sub": "s3"},
        ))

        plan = compile_program_plan(
            flow,
            workbook_identity="fixture",
            workbook_sha256="0" * 64,
            recipe_rows={},
            row_flags={0: "comment_out", 1: None, 2: "force_pass", 3: None},
        ).cp_plans["CP1"]

        flow_definitions = tuple(d for d in plan.definitions if d.source_rows)
        flow_schedule = plan.schedule[:3]
        self.assertEqual(tuple(d.item for d in flow_definitions), ("A", "B", "A"))
        self.assertEqual(flow_definitions[0].source_rows, (2, 3))
        self.assertEqual(tuple(s.enabled for s in flow_schedule), (False, True, True))
        self.assertEqual(tuple(s.force_pass for s in flow_schedule), (False, True, False))


if __name__ == "__main__":
    unittest.main()
