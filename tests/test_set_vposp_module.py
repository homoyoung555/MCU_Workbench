"""Public-interface tests for the shared SETVPOSP Recipe Module."""

from __future__ import annotations

from dataclasses import replace
import unittest

from program_gen.core.fbist_pattern_plan import FbistFieldLabel
from program_gen.core.run_pattern import PatternResourceRef, PatternSpan, RunPatternPlan
from program_gen.core.set_vposp import (
    PumpDacPlan,
    SetVpospCompileError,
    SetVpospSnapshot,
    compile_set_vposp_plan,
)
from program_gen.platforms.chroma.set_vposp_adapter import adapt_set_vposp
from program_gen.platforms.s100.set_vposp_adapter import (
    adapt_set_vposp as adapt_s100_set_vposp,
)
from program_gen.registered_recipe_modules import NATIVE_RECIPE_MODULE_REGISTRY


def _label(item: str, base: str, width: int = 5) -> FbistFieldLabel:
    return FbistFieldLabel(
        logical_field_identity=f"{item}:{base}",
        pattern_identity="set_all_final_vposp",
        item=item,
        field_label_base=base,
        addr_bits="0010100",
        bit_hi=width - 1,
        bit_lo=0,
        bit_width=width,
        dynamic=True,
        chroma_start_label=base,
        chroma_end_label="",
        s100_start_label=f"{base}_st",
        s100_end_label=f"{base}_sp",
    )


def _run_plan() -> RunPatternPlan:
    return RunPatternPlan(
        pattern=PatternResourceRef(
            name="set_all_final_vposp",
            logical_identity="pattern:set_all_final_vposp",
            ordered_labels=("START", "END"),
        ),
        span=PatternSpan.full(),
        timing_profile="TS_5MHZ",
    )


class SetVpospStateTests(unittest.TestCase):
    def test_first_or_dirty_call_prepares_then_the_next_clean_call_runs(self):
        pumps = (PumpDacPlan("Vposp", "VPOSP_DAC_FINAL"),)
        labels = (_label("Vposp", "pre_pdac"),)

        first = compile_set_vposp_plan(
            pumps, labels, SetVpospSnapshot(), swd_pin="PA13", run_pattern=_run_plan()
        )
        clean = compile_set_vposp_plan(
            pumps, labels, first.snapshot, swd_pin="PA13", run_pattern=_run_plan()
        )
        dirty = compile_set_vposp_plan(
            pumps,
            labels,
            clean.snapshot.invalidate(("Vposp",)),
            swd_pin="PA13",
            run_pattern=_run_plan(),
        )

        self.assertEqual(
            tuple(update.label.logical_field_identity for update in first.plan.updates),
            ("Vposp:pre_pdac",),
        )
        self.assertFalse(first.plan.should_run)
        self.assertEqual(clean.plan.updates, ())
        self.assertTrue(clean.plan.should_run)
        self.assertEqual(
            tuple(update.label.logical_field_identity for update in dirty.plan.updates),
            ("Vposp:pre_pdac",),
        )
        self.assertFalse(dirty.plan.should_run)

    def test_dirty_pump_without_a_dynamic_catalog_label_is_blocking(self):
        with self.assertRaises(SetVpospCompileError) as raised:
            compile_set_vposp_plan(
                (PumpDacPlan("Vposp", "VPOSP_DAC_FINAL"),),
                (),
                SetVpospSnapshot(),
                swd_pin="PA13",
                run_pattern=_run_plan(),
            )

        self.assertEqual(raised.exception.code, "SETVPOSP.LABEL.MISSING")

    def test_catalog_labels_must_belong_to_the_run_pattern_resource(self):
        wrong_pattern = replace(
            _label("Vposp", "vposp_target"),
            pattern_identity="another_pattern",
        )

        with self.assertRaises(SetVpospCompileError) as raised:
            compile_set_vposp_plan(
                (PumpDacPlan("Vposp", "VPOSP_DAC_FINAL"),),
                (wrong_pattern,),
                SetVpospSnapshot(),
                swd_pin="PA13",
                run_pattern=_run_plan(),
            )

        self.assertEqual(raised.exception.code, "SETVPOSP.PATTERN.MISMATCH")


class SetVpospChromaAdapterTests(unittest.TestCase):
    def test_dirty_pump_writes_all_catalog_labels_per_site_and_preserves_other_fields(self):
        pumps = (
            PumpDacPlan("PumpA", "PUMP_A_DAC_FINAL"),
            PumpDacPlan("PumpB", "PUMP_B_DAC_FINAL"),
        )
        labels = (
            _label("PumpA", "field_a_first"),
            _label("PumpB", "field_b"),
            _label("PumpA", "field_a_second"),
        )
        snapshot = SetVpospSnapshot(
            prepared_items=frozenset(("pumpa", "pumpb"))
        ).invalidate(("PumpA",))
        transition = compile_set_vposp_plan(
            pumps, labels, snapshot, swd_pin="PA13", run_pattern=_run_plan()
        )

        emission = adapt_set_vposp(transition.plan)

        self.assertEqual(
            emission.statements,
            (
                "  SOCKET_INC(FRZ_OFF)",
                "  {",
                "    convert_to_string(PUMP_A_DAC_FINAL[SOCKET],5,BUFF_W_P,BUFF_W_N,BUFF_R_P,BUFF_R_N);",
                "    for(I=0;I<5;I++)",
                "    {",
                "      WRITE_PAT_MEM(SOCKET,PA13,set_all_final_vposp:field_a_first+I,,BUFF_W_P[I]);",
                "    }",
                "    for(I=0;I<5;I++)",
                "    {",
                "      WRITE_PAT_MEM(SOCKET,PA13,set_all_final_vposp:field_a_second+I,,BUFF_W_P[I]);",
                "    }",
                "  }",
            ),
        )
        self.assertNotIn("field_b", "\n".join(emission.statements))
        self.assertNotIn("pre_", "\n".join(emission.statements))

    def test_each_catalog_width_controls_its_own_conversion(self):
        transition = compile_set_vposp_plan(
            (PumpDacPlan("PumpA", "PUMP_A_DAC_FINAL"),),
            (
                _label("PumpA", "wide_target", 5),
                _label("PumpA", "narrow_target", 3),
            ),
            SetVpospSnapshot(),
            swd_pin="PA13",
            run_pattern=_run_plan(),
        )

        statements = adapt_set_vposp(transition.plan).statements

        self.assertIn(
            "    convert_to_string(PUMP_A_DAC_FINAL[SOCKET],3,"
            "BUFF_W_P,BUFF_W_N,BUFF_R_P,BUFF_R_N);",
            statements,
        )
        self.assertIn("    for(I=0;I<3;I++)", statements)


class SetVpospS100AdapterTests(unittest.TestCase):
    def test_dirty_pump_writes_catalog_start_and_end_labels_from_each_site_value(self):
        pumps = (
            PumpDacPlan("PumpA", "PUMP_A_DAC_FINAL"),
            PumpDacPlan("PumpB", "PUMP_B_DAC_FINAL"),
        )
        labels = (
            _label("PumpA", "field_a_first"),
            _label("PumpB", "field_b"),
            _label("PumpA", "field_a_second"),
        )
        snapshot = SetVpospSnapshot(
            prepared_items=frozenset(("pumpa", "pumpb"))
        ).invalidate(("PumpA",))
        transition = compile_set_vposp_plan(
            pumps, labels, snapshot, swd_pin="PA13", run_pattern=_run_plan()
        )

        emission = adapt_s100_set_vposp(transition.plan)

        self.assertEqual(
            emission.statements,
            (
                "\tCALL_MACRO write_pat_temp_arry(PUMP_A_DAC_FINAL);",
                "\tLOGIC_WRITE_PATTERN_MEMORY(set_all_final_vposp:field_a_first_st,"
                "set_all_final_vposp:field_a_first_sp,PA13,GB1,BIT_COUNT=5,SERIAL,MSB_LSB);",
                "\tLOGIC_WRITE_PATTERN_MEMORY(set_all_final_vposp:field_a_second_st,"
                "set_all_final_vposp:field_a_second_sp,PA13,GB1,BIT_COUNT=5,SERIAL,MSB_LSB);",
            ),
        )
        self.assertNotIn("field_b", "\n".join(emission.statements))


class SetVpospRegistrationTests(unittest.TestCase):
    def test_registered_setvposp_routes_clean_snapshot_to_global_run(self):
        transition = compile_set_vposp_plan(
            (PumpDacPlan("Vposp", "VPOSP_DAC_FINAL"),),
            (_label("Vposp", "catalog_only_label"),),
            SetVpospSnapshot(prepared_items=frozenset(("vposp",))),
            swd_pin="PA13",
            run_pattern=_run_plan(),
        )

        chroma = NATIVE_RECIPE_MODULE_REGISTRY.emit(
            "SETVPOSP", transition.plan, "chroma"
        )
        s100 = NATIVE_RECIPE_MODULE_REGISTRY.emit(
            "SETVPOSP", transition.plan, "s100"
        )

        self.assertEqual(
            chroma.statements,
            (
                "  TEST_NUM++;",
                '  TEST_NO(TEST_NUM); DATALOG_MSG="set_all_final_vposp";',
                "  JUDGE_PAT(set_all_final_vposp,__set_all_final_vposp);",
                "",
            ),
        )
        self.assertEqual(
            s100.statements,
            (
                "\tRUN_PATTERN(set_all_final_vposp:START,"
                "set_all_final_vposp:END,1,TS_5MHZ);",
            ),
        )


if __name__ == "__main__":
    unittest.main()
