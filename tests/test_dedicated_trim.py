from tests.workspace_paths import FORMAL_MASTER as EXTERNAL_FORMAL_MASTER
from dataclasses import FrozenInstanceError
from pathlib import Path
import unittest

import pandas as pd

from program_gen.core.dedicated_trim import (
    DedicatedTrimCompileError,
    compile_dedicated_trim_plans,
)
from program_gen.flow_kinds import compile_flow_rows
from program_gen.workbook import WorkbookReader


ROOT = Path(__file__).resolve().parents[1]
FORMAL_MASTER = EXTERNAL_FORMAL_MASTER


class DedicatedTrimFormalMasterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.flow = workbook.dataframe("FLOW")
        cls.operations = compile_flow_rows(
            cls.flow,
            workbook_identity=workbook.identity,
            source_sha256=workbook.source_sha256,
        )
        cls.plans = compile_dedicated_trim_plans(
            cls.flow,
            cls.operations,
            pattern_frame=workbook.dataframe("pattern"),
            version_frame=workbook.dataframe("VERSION"),
        )

    def test_pdr_is_an_explicit_plan_and_not_a_generic_trim_spec(self):
        self.assertEqual(tuple(self.plans), (7,))
        plan = self.plans[7]
        self.assertEqual(plan.cp, "CP1")
        self.assertEqual(plan.item, "Pdr_Trim")
        self.assertEqual(plan.typed_kind, "PDR_TRIM")
        self.assertEqual(plan.effective_recipe, ("PDR_TRIM",))
        self.assertEqual(plan.search_variant, "PDR_STATUS_TRANSITION")
        self.assertEqual(plan.dac_bits, 4)
        self.assertEqual(
            plan.search_codes,
            (8, 9, 10, 11, 12, 13, 14, 15, 0, 1, 2, 3, 4, 5, 6, 7),
        )
        self.assertEqual(plan.initial_vcc, "VCC_TYP")
        self.assertIsNone(plan.relay)
        self.assertEqual(plan.test_number, 1650)
        self.assertEqual(plan.pdr_min_voltage, "2.31")
        self.assertEqual(plan.pdr_target_voltage, "2.37")
        self.assertEqual(plan.pdr_max_voltage, "2.43")
        self.assertEqual(plan.dac_pattern_name, "set_pdr_dac")
        self.assertEqual(plan.helper_name, "set_pdr_trim_data")
        self.assertEqual(plan.write_pin, "PA13")
        self.assertEqual(plan.provenance.coordinate, "A9")
        with self.assertRaises(FrozenInstanceError):
            plan.item = "mutated"


class DedicatedTrimBoundaryTests(unittest.TestCase):
    def test_bor_is_not_guessed_as_pdr(self):
        flow = _flow_row(item="Bor_Trim")
        operations = compile_flow_rows(
            flow, workbook_identity="wb", source_sha256="sha"
        )

        with self.assertRaisesRegex(
            DedicatedTrimCompileError, "DT.KIND.UNSUPPORTED.*Bor_Trim"
        ):
            compile_dedicated_trim_plans(
                flow,
                operations,
                pattern_frame=_pattern_table(),
                version_frame=_version_table(),
            )

    def test_pdr_contract_requires_yes_search_and_four_dac_bits(self):
        for column, value, code in (
            ("Bisection", "no", "DT.PDR.SEARCH"),
            ("DAC bit", 5, "DT.PDR.DAC_BITS"),
        ):
            with self.subTest(column=column):
                flow = _flow_row(**{column: value})
                operations = compile_flow_rows(
                    flow, workbook_identity="wb", source_sha256="sha"
                )
                with self.assertRaisesRegex(DedicatedTrimCompileError, code):
                    compile_dedicated_trim_plans(
                        flow,
                        operations,
                        pattern_frame=_pattern_table(),
                        version_frame=_version_table(),
                    )

    def test_pdr_contract_rejects_unknown_initial_vcc_symbol(self):
        flow = _flow_row(Vcc="PDR_MAGIC")
        operations = compile_flow_rows(
            flow, workbook_identity="wb", source_sha256="sha"
        )

        with self.assertRaisesRegex(DedicatedTrimCompileError, "DT.PDR.VCC"):
            compile_dedicated_trim_plans(
                flow,
                operations,
                pattern_frame=_pattern_table(),
                version_frame=_version_table(),
            )


def _flow_row(**updates):
    row = {
        "CP NO": "CP1",
        "item": "Pdr_Trim",
        "type": "trim",
        "Recipe": "",
        "mode": "fbist",
        "Bisection": "yes",
        "DAC bit": 4,
        "FV/FI": "/",
        "relay": "/",
        "Vcc": "VCC_TYP",
        "step": "8,9,10,11,12,13,14,15,0,1,2,3,4,5,6,7",
    }
    row.update(updates)
    return pd.DataFrame([row])


def _pattern_table():
    return pd.DataFrame([
        {"item": "Pdr_Trim", "pattern": "trim dac"},
    ])


def _version_table():
    return pd.DataFrame([{
        "CP num": "CP1",
        "pdr min": "2.31",
        "pdr target": "2.37",
        "pdr max": "2.43",
        "SWD PIN": "PA13",
    }])


if __name__ == "__main__":
    unittest.main()
