import unittest

import pandas as pd

from flow_recipe import compile_recipe_program
from program_gen.core.addr_map import compile_addr_map_catalog
from program_gen.core.fbist_pattern_plan import (
    FbistPatternField, FbistPatternGenerationPlan, FbistPumpAggregate, FbistPumpTarget,
)
from program_gen.core.flash_label_plan import compile_flash_label_contract
from program_gen.core.persistence_recipe import PersistenceOperation, PersistencePlan, compile_persistence_plan
from program_gen.core.otp_program import LoadMapPlan
from program_gen.core.set_vposp import SetVpospPlan, SetVpospPurpose
from program_gen.core.trim_data import compile_trim_data_plan
from program_gen.core.trimdata_read import (
    CheckOtpPlan, ReadOtpMapPlan, TrimdataReadCompileError,
    compile_trimdata_read_plan,
)


def _catalog():
    return compile_addr_map_catalog(pd.DataFrame([{
        "Word No.": "trim0", "line": "CP1,CP2,CP3,CP4", "SM Address": "RA=0x1;",
        "bit[31:16]": "反码", "bit[15:0]": "REG_TRIM0[15:0]",
        "data type": "lable", "CP Data[31:0]": "32'hFFFF_0000",
        "CP addr map": "Vposp_Trim[3:0]",
    }]))


def _trim_data_plan():
    return compile_trim_data_plan(pd.DataFrame([
        {"CP NO": "CP1", "item": "Vposp", "type": "trim", "DAC bit": 4, "PUMP": "yes"},
        {"CP NO": "CP4", "item": "Vposp", "type": "trim", "DAC bit": 4, "PUMP": "yes"},
    ]))


def _fbist():
    field = FbistPatternField(2, 0, "VPOSP", "vposp", 0, 4, 3, 0, "xxxx", True)
    target = FbistPumpTarget("Vposp", 2, "set_vposp", "pump dac", "0000001", field)
    return FbistPatternGenerationPlan(
        "wb", "PA0", "PA1", (), (),
        FbistPumpAggregate("set_all_final_vposp", (), (target,)),
        ("Vposp",), (),
    )


def _persistence_plan(cp="CP2", recipe="READOTPMAP-LOADMAP-SETVPOSP-CHECKOTP"):
    flow = pd.DataFrame([
        {"CP NO": cp, "item": "Earlier_Read", "type": "data", "sub": "/", "Recipe": "READOTPMAP"},
        {"CP NO": cp, "item": "Trimdata_Read", "type": "read", "sub": "/", "Recipe": recipe},
    ])
    program = compile_recipe_program(flow, pd.DataFrame(columns=("item", "addr", "description", "pattern")))
    rows = tuple(row for function in program.functions for row in function.rows)
    return compile_persistence_plan(rows, _catalog(), node_default_pages={2: ("trim0",), 3: ("trim0",)})


def _compile(cp="CP2", recipe="READOTPMAP-LOADMAP-SETVPOSP-CHECKOTP", **kwargs):
    catalog = _catalog()
    return compile_trimdata_read_plan(
        _persistence_plan(cp, recipe), _trim_data_plan(), catalog,
        excel_row=3, power_profile="VCC_TYP", fbist_plan=_fbist(),
        flash_labels=compile_flash_label_contract(catalog), read_bit=64, **kwargs,
    )


class TrimdataReadPlanTests(unittest.TestCase):
    def test_compiles_native_spine_and_explicit_read_is_not_globally_deduplicated(self):
        plan = _compile()

        self.assertEqual(plan.cp, "CP2")
        self.assertEqual(plan.effective_recipe, ("READOTPMAP", "LOADMAP", "SETVPOSP", "CHECKOTP"))
        self.assertIsInstance(plan.steps[0].module_plan, ReadOtpMapPlan)
        self.assertEqual(tuple(page.page for page in plan.steps[0].module_plan.pages), ("trim0",))
        self.assertIsInstance(plan.steps[1].module_plan, LoadMapPlan)
        self.assertIsInstance(plan.steps[2].module_plan, SetVpospPlan)
        self.assertEqual(plan.steps[2].module_plan.purpose, SetVpospPurpose.PREPARE_FOR_FLASH)
        self.assertFalse(plan.steps[2].module_plan.should_run)
        self.assertIsInstance(plan.steps[3].module_plan, CheckOtpPlan)
        self.assertEqual(plan.steps[3].module_plan.set_all_final_vposp.pattern.name, "set_all_final_vposp")

    def test_future_cp_identity_is_not_hardcoded(self):
        self.assertEqual(_compile("CP4").cp, "CP4")

    def test_extra_shared_module_can_be_inserted_with_an_explicit_typed_plan(self):
        marker = object()
        plan = _compile(
            recipe="READOTPMAP-LOADMAP-COMMIT-SETVPOSP-CHECKOTP",
            extra_module_plans={2: marker},
        )
        self.assertEqual(plan.effective_recipe[2], "COMMIT")
        self.assertIs(plan.steps[2].module_plan, marker)

    def test_mandatory_spine_must_be_complete_and_ordered(self):
        with self.assertRaises(TrimdataReadCompileError) as raised:
            _compile(recipe="READOTPMAP-SETVPOSP-LOADMAP-CHECKOTP")
        self.assertEqual(raised.exception.code, "TRIMDATA_READ.RECIPE.ORDER_INVALID")

    def test_each_repeated_segment_keeps_its_own_explicit_capture(self):
        plan = _compile(recipe=(
            "READOTPMAP-LOADMAP-SETVPOSP-CHECKOTP-"
            "READOTPMAP-LOADMAP-SETVPOSP-CHECKOTP"
        ))
        reads = tuple(step for step in plan.steps if step.module == "READOTPMAP")
        prepares = tuple(step for step in plan.steps if step.module == "SETVPOSP")
        self.assertEqual(tuple(step.segment for step in reads), (0, 1))
        self.assertEqual(tuple(page.page for step in reads for page in step.module_plan.pages), ("trim0", "trim0"))
        self.assertTrue(all(step.module_plan.updates for step in prepares))

    def test_uid_only_scope_is_rejected(self):
        persistence = PersistencePlan("CP2", (
            PersistenceOperation("READOTPMAP", 3, ("uid",), ("uid",)),
            PersistenceOperation("LOADMAP", 3, ("uid",), ("uid",)),
            PersistenceOperation("SETVPOSP", 3, ("uid",), ("uid",)),
            PersistenceOperation("CHECKOTP", 3, ("uid",), ("uid",)),
        ))
        catalog = _catalog()
        with self.assertRaises(TrimdataReadCompileError) as raised:
            compile_trimdata_read_plan(
                persistence, _trim_data_plan(), catalog, excel_row=3,
                power_profile="VCC_TYP", fbist_plan=_fbist(),
                flash_labels=compile_flash_label_contract(catalog), read_bit=64,
            )
        self.assertEqual(raised.exception.code, "TRIMDATA_READ.PAGE_SCOPE.MISMATCH")


if __name__ == "__main__":
    unittest.main()
