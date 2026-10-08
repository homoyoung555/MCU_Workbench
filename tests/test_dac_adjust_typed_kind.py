import unittest
from dataclasses import dataclass, field
from types import MappingProxyType, SimpleNamespace

import pandas as pd

from flow_recipe import (
    RecipeValueToken,
    ResultExportPlan,
    ResultExportPlanSet,
    compile_recipe_rows,
)
from program_gen.core.addr_map import compile_addr_map_catalog
from program_gen.core.commit_module import compile_commit_module_plan
from program_gen.core.flash_label_plan import compile_flash_label_contract
from program_gen.core.dac_adjust import (
    DacAdjustActionPlanError,
    DacAdjustTargetSourceKind,
    compile_dac_adjust_action_plans,
)
from program_gen.core.default_commit import compile_default_commit_bindings
from program_gen.core.fbist_pattern_plan import (
    FbistPatternField,
    FbistPatternGenerationPlan,
    FbistPumpAggregate,
    FbistPumpTarget,
)
from program_gen.core.persistence_recipe import (
    PersistenceFieldWrite,
    PersistenceOperation,
    PersistencePlanSet,
    PersistenceRowPlan,
)
from program_gen.compiler import _canonical
from program_gen.registered_recipe_modules import NATIVE_RECIPE_MODULE_REGISTRY
from program_gen.diagnostics import WorkbookProvenance
from program_gen.flow_kinds import FlowOperation, compile_flow_rows
from program_gen.registered_typed_kinds import NATIVE_TYPED_KIND_REGISTRY
from program_gen.render_plan import TargetKey
from program_gen.typed_kind_registry import TypedKindContext


class DacAdjustTypedKindTests(unittest.TestCase):
    def test_empty_optional_catalog_does_not_change_existing_semantic_identity(self):
        @dataclass(frozen=True)
        class Catalog:
            existing: str
            future: tuple = field(metadata={"canonical_omit_if_empty": True})

        self.assertEqual(_canonical(Catalog("same", ())), {"existing": "same"})
        self.assertEqual(
            _canonical(Catalog("same", ("ACTION",))),
            {"existing": "same", "future": ["ACTION"]},
        )

    def test_type_adjust_is_classified_without_enter_or_judge(self):
        operations = compile_flow_rows(pd.DataFrame([{
            "CP NO": "CP1", "item": "VPOSE", "type": "adjust", "mode": "/",
            "FV/FI": "/",
        }]), workbook_identity="book", source_sha256="sha")

        self.assertEqual(operations[0].typed_kind, "DAC_ADJUST")
        self.assertEqual(operations[0].family, "DAC_ADJUST")

    def test_single_input_plan_uses_live_dac_then_dirty_setvposp_and_commit(self):
        plan = self._compile_action(target_producer_row=0)

        self.assertEqual(plan.effective_recipe, ("DAC_ADJ", "SETVPOSP", "COMMIT"))
        adjust, setvposp, commit = (step.module_plan for step in plan.steps)
        self.assertEqual(adjust.condition.source_symbol, "A_EXPORT")
        self.assertEqual(adjust.target_source.kind, DacAdjustTargetSourceKind.DAC_FINAL)
        self.assertEqual(adjust.codes, tuple(range(17, 32)) + tuple(range(17)))
        self.assertFalse(setvposp.should_run)
        self.assertEqual(
            tuple(update.pump.item for update in setvposp.updates),
            ("VPOSE",),
        )
        self.assertEqual(commit.writes[0].value.token, "VPOSE_DAC_FINAL")

    def test_target_restores_from_prior_addr_map_read_when_live_dac_is_unavailable(self):
        plan = self._compile_action(target_producer_row=3)
        adjust = plan.steps[0].module_plan

        self.assertEqual(adjust.target_source.kind, DacAdjustTargetSourceKind.ADDR_MAP)
        self.assertEqual(adjust.target_source.register_symbol, "REG_FLASH_OP6")
        self.assertEqual(adjust.target_source.bit_lsb, 5)
        self.assertEqual(adjust.target_source.restored_at_excel_row, 2)
        for platform, site in (("chroma", "SOCKET"), ("s100", "T_SOCKET")):
            source = "\n".join(
                NATIVE_RECIPE_MODULE_REGISTRY.emit(
                    "DAC_ADJ", adjust, platform
                ).statements
            )
            self.assertIn(
                f"VPOSE_DAC_FINAL[{site}]=(REG_FLASH_OP6[{site}]>>5)&0x1F;",
                source,
            )

    def test_naked_commit_binds_only_the_adjusted_non_uid_trim_field(self):
        frame = pd.DataFrame([{
            "CP NO": "CP1", "item": "VPOSE", "type": "adjust", "sub": "/",
            "mode": "/", "Recipe": "DAC_ADJ(A<0.4:VPOSE+2)-SETVPOSP-COMMIT",
        }], index=(1,))
        rows = compile_recipe_rows(
            frame,
            pd.DataFrame(columns=("item", "addr", "description", "pattern")),
        )

        bindings = compile_default_commit_bindings(frame, rows, _catalog())

        self.assertEqual(len(bindings[1]), 1)
        self.assertEqual(bindings[1][0].field, "VPOSE")
        self.assertEqual(bindings[1][0].value.token, "VPOSE_DAC_FINAL")

    def test_first_version_rejects_more_than_one_adjustment(self):
        operation, rows = _operation_and_rows(
            "DAC_ADJ(A<0.4:VPOSE+2)-DAC_ADJ(A>0.6:VPOSE-1)-SETVPOSP-COMMIT"
        )
        with self.assertRaisesRegex(
            DacAdjustActionPlanError, "SINGLE_ADJUST_REQUIRED"
        ):
            compile_dac_adjust_action_plans(
                (operation,), rows, _exports(), _trim_specs(0), _catalog(),
                _persistence(), _fbist_plan(), {1: (_commit_plan(),)},
            )

    def test_native_assembly_has_no_implicit_run_judge_or_program_otp(self):
        plan = self._compile_action(target_producer_row=0)
        definition = SimpleNamespace(
            identity="DEF-ADJUST", cp="CP1", source_rows=(3,),
            render_name="VPOSE_Adjust",
        )
        entry = SimpleNamespace(
            identity="ENTRY-ADJUST", definition_id="DEF-ADJUST", enabled=True,
            bin_binding=SimpleNamespace(hardware_bin="1"),
        )
        schedule = SimpleNamespace(definitions=(definition,), entries=(entry,))
        compilation = SimpleNamespace(
            require_success=lambda: None,
            for_cp=lambda _cp: SimpleNamespace(canonical_schedule=schedule),
        )

        for platform, condition, prepare in (
            ("chroma", "A_EXPORT[SOCKET]<0.4", "convert_to_string(VPOSE_DAC_FINAL[SOCKET]"),
            ("s100", "A_EXPORT[T_SOCKET]<0.4", "write_pat_temp_arry(VPOSE_DAC_FINAL)"),
        ):
            target = TargetKey(platform, "CP1", "lab", f"DAC_ADJUST_{platform}_CP1")
            assembly = NATIVE_TYPED_KIND_REGISTRY.compile(
                "DAC_ADJUST", (plan,),
                TypedKindContext(compilation, target, None, None),
            )
            body = assembly.bodies[0].fragment.content.decode("gbk")

            self.assertEqual(assembly.typed_kind, "DAC_ADJUST")
            self.assertIn(condition, body)
            self.assertIn(prepare, body)
            self.assertIn("REG_FLASH_OP6", body)
            if platform == "chroma":
                for expected in (
                    "flash_op6_w_p+I,,BUFF_W_P[I]",
                    "flash_op6_w_n+I,,BUFF_W_N[I]",
                    "flash_op6_r_p+I,,BUFF_R_P[I]",
                    "flash_op6_r_n+I,,BUFF_R_N[I]",
                ):
                    self.assertIn(expected, body)
            for forbidden in ("POWER_ON", "JUDGE", "RUN_PATTERN", "PGMOTP"):
                self.assertNotIn(forbidden, body)
        self.assertIn("DAC_ADJUST", NATIVE_TYPED_KIND_REGISTRY.registered_kinds)

    def _compile_action(self, *, target_producer_row):
        operation, rows = _operation_and_rows(
            "DAC_ADJ(A<0.4:VPOSE+2)-SETVPOSP-COMMIT"
        )
        return compile_dac_adjust_action_plans(
            (operation,), rows, _exports(), _trim_specs(target_producer_row),
            _catalog(), _persistence(), _fbist_plan(), {1: (_commit_plan(),)},
        )[1]


def _operation_and_rows(recipe):
    frame = pd.DataFrame([{
        "CP NO": "CP1", "item": "VPOSE", "type": "adjust", "sub": "/",
        "mode": "/", "Recipe": recipe,
    }], index=(1,))
    rows = compile_recipe_rows(
        frame, pd.DataFrame(columns=("item", "addr", "description", "pattern"))
    )
    operation = FlowOperation(
        1, "CP1", "VPOSE", "adjust", "/", "DAC_ADJUST", "DAC_ADJUST", None,
        WorkbookProvenance("FLOW", "A3", "book", "sha"),
    )
    return operation, rows


def _exports():
    return {"CP1": ResultExportPlanSet((ResultExportPlan(
        0, "A", "/", "verify", "MEASUREMENT", "RAW", "A_EXPORT",
        "double", True, False, unit="V",
    ),))}


def _trim_specs(row):
    return {row: SimpleNamespace(
        flow_row_index=row,
        cp="CP1",
        item="VPOSE",
        dac_final_symbol="VPOSE_DAC_FINAL",
        search=SimpleNamespace(codes=tuple(range(17, 32)) + tuple(range(17))),
    )}


def _catalog():
    return compile_addr_map_catalog(pd.DataFrame([
        {
            "Word No.": "trim0", "line": "CP1",
            "bit[31:16]": "bit[15:0]的反码",
            "bit[15:0]": "FLASH_OP6[15:0]", "data type": "lable",
            "CP Data[31:0]": "32'hFFFF_0000",
            "CP addr map": "6'h0,VPOSE[4:0],VNEGE[4:0]",
        },
        {
            "Word No.": "uid", "line": "CP1", "bit[31:16]": "16'h0000",
            "bit[15:0]": "UID_WORD[15:0]", "data type": "lable",
            "CP Data[31:0]": "32'h0000_0000", "CP addr map": "VPOSE[4:0]",
        },
    ]))


def _persistence():
    read = PersistenceOperation(
        "READOTPMAP", 2, ("trim0",), ("trim0",), (), None,
    )
    return PersistencePlanSet(MappingProxyType({
        0: PersistenceRowPlan("CP1", 2, (read,)),
    }))


def _commit_plan():
    operation = PersistenceOperation(
        "COMMIT", 3, ("trim0",), ("trim0",),
        (PersistenceFieldWrite(
            "VPOSE", "trim0", "FLASH_OP6", 5, 5,
            RecipeValueToken("VARIABLE", "VPOSE_DAC_FINAL"),
        ),),
        "DEFAULT",
    )
    catalog = _catalog()
    return compile_commit_module_plan(
        operation, catalog, cp="CP1", swd_pin="PA13",
        flash_labels=compile_flash_label_contract(catalog),
    )


def _fbist_plan():
    field = FbistPatternField(
        10, 0, "VPOSE_DAC[4:0]", "vpose_dac", 0, 5, 4, 0, "0000*", True,
    )
    target = FbistPumpTarget(
        "VPOSE", 10, "set_vpose_dac", "trim dac", "0000001", field,
    )
    return FbistPatternGenerationPlan(
        "book", "PA0", "PA13", (), (),
        FbistPumpAggregate("set_all_final_vposp", (), (target,)),
        ("VPOSE",), (),
    )


if __name__ == "__main__":
    unittest.main()
