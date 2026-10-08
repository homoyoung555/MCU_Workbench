import io
import unittest
from types import SimpleNamespace
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from program_gen.core.encoding import expand_dac_array
from program_gen.core.recipe_trim import pattern_output_name
from program_gen.platforms.s100 import writers as s100_writers
from program_gen.platforms.s100 import main as s100_main


class V12GeneratorCompatibilityTests(unittest.TestCase):
    def test_s100_legacy_master_gets_an_in_memory_blank_recipe_column(self):
        original = s100_main.G.FLOW
        try:
            s100_main.G.FLOW = pd.DataFrame({"item": ["os_test"]})
            s100_main._enable_legacy_recipe_compatibility()

            self.assertEqual(list(s100_main.G.FLOW["Recipe"]), [""])
        finally:
            s100_main.G.FLOW = original

    def test_public_step_expansion_keeps_descending_and_ascending_ranges(self):
        expanded = expand_dac_array("63-0,64-128")

        self.assertEqual(
            [int(value) for value in expanded.split(",")],
            list(range(63, -1, -1)) + list(range(64, 129)),
        )

    def test_frequency_final_measure_is_wrapped_by_one_pe_pair_without_limits(self):
        output = io.StringIO()

        s100_writers._emit_trim_final_dac_measure(
            output,
            "\tCALL_MACRO set_pclk_trim_data(PCLK_DAC_FINAL);\n\n",
            unit="KHz",
            meas_pin="PA0",
            force_value="0V",
            target=10,
            low_range="-5%",
            high_range="+5%",
            pe_patterns=("fbist_page_erase_trim",),
        )

        generated = output.getvalue()
        start = (
            "RUN_PATTERN(fbist_page_erase_trim:START,"
            "fbist_page_erase_trim:pe_1,1,TS_5MHZ);"
        )
        end = (
            "RUN_PATTERN(fbist_page_erase_trim:pe_1,"
            "fbist_page_erase_trim:END,1,TS_5MHZ);"
        )
        measure = "LOGIC_TMU_MEAS_FREQ(TIME_OUT=50mS);"
        self.assertEqual(generated.count(start), 1)
        self.assertEqual(generated.count(end), 1)
        self.assertLess(generated.index(start), generated.index(measure))
        self.assertLess(generated.index(measure), generated.index(end))
        self.assertNotIn("DOWN_LIMIT", generated)
        self.assertNotIn("UP_LIMIT", generated)

    def test_os_tp_measure_and_cleanup_use_the_actual_prj_power_rails(self):
        flow = {
            "type": ["os"],
            "item": ["OS_CP1"],
            "CP NO": ["CP1"],
            "Hbin": [9],
        }
        output = io.StringIO()

        def fake_col(sheet, column):
            self.assertEqual(sheet, "FLOW")
            return flow[column]

        with (
            patch.object(s100_writers.G, "col", side_effect=fake_col),
            patch.object(s100_writers.G, "i", 0),
            patch.object(s100_writers.G, "flow_row_flag", return_value=None),
            patch.object(s100_writers, "prj_power_pins", return_value=["VCC4", "VREFP"]),
            patch.object(s100_writers, "flow_relay", return_value="/"),
        ):
            s100_writers.os_write(
                ["PROGRAM_CP1"], output,
                SimpleNamespace(row=0, cp="CP1", item="os_test"),
            )

        generated = output.getvalue()
        self.assertIn("LOGIC_PPMU_MV(TP, UP_LIMIT=3.3V, DOWN_LIMIT=-3.3V);", generated)
        self.assertNotIn("LOGIC_PPMU_MV(IO_ALLPINS, UP_LIMIT=3.3V, DOWN_LIMIT=-3.3V);", generated)
        for rail in ("VCC4", "VREFP"):
            self.assertIn(f"LOGIC_FORCE_DPS({rail}, 0.0V, 500MA, I7, WAIT=0.5MS);", generated)
            self.assertIn(f"LOGIC_CLOSE_DPS_OUTPUT_RELAY({rail},OFF,WAIT=0.5MS);", generated)
        self.assertNotIn("LOGIC_FORCE_DPS(VCCD", generated)
        self.assertNotIn("LOGIC_CLOSE_DPS_OUTPUT_RELAY(VCCD", generated)

    def test_os_wraps_the_measurement_with_the_flow_relay(self):
        flow = {
            "type": ["os"],
            "item": ["os_test"],
            "CP NO": ["CP1"],
            "Hbin": [3],
        }
        output = io.StringIO()

        with (
            patch.object(s100_writers.G, "col", side_effect=lambda sheet, column: flow[column]),
            patch.object(s100_writers.G, "i", 0),
            patch.object(s100_writers.G, "flow_row_flag", return_value=None),
            patch.object(s100_writers, "prj_power_pins", return_value=["VCCD"]),
            patch.object(s100_writers, "flow_relay", return_value="UR_OS"),
        ):
            s100_writers.os_write(
                ["PROGRAM_CP1"], output,
                SimpleNamespace(row=0, cp="CP1", item="os_test"),
            )

        generated = output.getvalue()
        relay_on = "IO_CLOSE_USER_RELAY(UR_OS,CONNECT_MODE,ALL_SITE_ON,WAIT=1MS);"
        relay_off = "IO_CLOSE_USER_RELAY(UR_OS,DISCONNECT_MODE,ALL_SITE_ON,WAIT=1MS);"
        self.assertEqual(generated.count(relay_on), 1)
        self.assertEqual(generated.count(relay_off), 1)
        self.assertLess(generated.index(relay_on), generated.index("LOGIC_FORCE_DPS(VCCD"))
        self.assertLess(
            generated.index("LOGIC_CLOSE_DPS_OUTPUT_RELAY(VCCD,OFF"),
            generated.index(relay_off),
        )

    def test_flow_relay_is_used_only_when_declared_by_the_current_cp_dec(self):
        tables = {
            ("FLOW", "relay"): ["K1"],
            ("FLOW", "CP NO"): ["CP1"],
            ("PIN_DEC_128", "CP NO"): ["CP1", "CP2"],
            ("PIN_DEC_128", "E/C(Pad Name)"): ["K1", "K2"],
            ("PIN_DEC_128", "Trace"): [150, 250],
        }
        with (
            patch.object(s100_writers.G, "FLOW", SimpleNamespace(columns=["relay"])),
            patch.object(s100_writers.G, "col", side_effect=lambda sheet, column: tables[(sheet, column)]),
        ):
            self.assertEqual(s100_writers.flow_relay(0), "K1")
            tables[("PIN_DEC_128", "E/C(Pad Name)")][0] = "K9"
            self.assertEqual(s100_writers.flow_relay(0), "/")
            tables[("FLOW", "relay")][0] = 150
            self.assertEqual(s100_writers.flow_relay(0), "/")

    def test_s100_flow_relay_emits_matching_connect_and_disconnect_commands(self):
        output = io.StringIO()

        s100_writers._emit_flow_relay(output, "UR_OS", enabled=True)
        s100_writers._emit_flow_relay(output, "UR_OS", enabled=False)
        s100_writers._emit_flow_relay(output, "/", enabled=True)

        self.assertEqual(
            output.getvalue(),
            "\tIO_CLOSE_USER_RELAY(UR_OS,CONNECT_MODE,ALL_SITE_ON,WAIT=1MS);\n"
            "\tIO_CLOSE_USER_RELAY(UR_OS,DISCONNECT_MODE,ALL_SITE_ON,WAIT=1MS);\n",
        )

    def test_bor_verify_emits_the_set_bor_data_macro_it_calls(self):
        tables = {
            ("FLOW", "item"): ["BOR_VERIFY"],
            ("FLOW", "CP NO"): ["CP1"],
            ("VERSION", "SWD PIN"): ["SWD"],
        }
        output = io.StringIO()

        with (
            patch.object(s100_writers.G, "i", 0),
            patch.object(s100_writers.G, "BASE_DIR", r"C:\base"),
            patch.object(s100_writers.G, "OUT_DIR", r"C:\out"),
            patch.object(s100_writers.G, "col", side_effect=lambda sheet, column: tables[(sheet, column)]),
            patch.object(s100_writers, "copy_file") as copy_pattern,
        ):
            emitted = s100_writers._bor_data_helper_write(["PROGRAM_CP1"], output, 0)

        generated = output.getvalue()
        self.assertTrue(emitted)
        self.assertIn("@@MACRO set_bor_data(int a)", generated)
        self.assertIn("LOGIC_WRITE_PATTERN_MEMORY(set_bor_verify_dac:e_data_st,set_bor_verify_dac:e_data_sp,SWD,GB1, BIT_COUNT=3, SERIAL,MSB_LSB);", generated)
        self.assertIn("RUN_PATTERN(set_bor_verify_dac:START,set_bor_verify_dac:END,1,TS_5MHZ);", generated)
        copy_pattern.assert_called_once()

    def test_bor_verify_dac_pattern_does_not_collide_with_bor_trim_dac(self):
        self.assertEqual(
            pattern_output_name("Bor_Trim", "trim dac", "15,BOR_TRIM[3:0]=xxxx"),
            "set_bor_dac",
        )
        self.assertEqual(
            pattern_output_name("Bor_Trim", "trim dac", "2,BOR_OPCR[2:0]=xxx"),
            "set_bor_verify_dac",
        )

    def test_s100_vt_writer_uses_the_v13_verify_pattern_name(self):
        tables = {
            ("FLOW", "type"): ["VT"],
            ("FLOW", "item"): ["VTE_CKB"],
            ("FLOW", "CP NO"): ["CP1"],
            ("FLOW", "Vcc"): ["vcc_typ"],
            ("FLOW", "Hbin"): [9],
            ("NM_PATTERN", "used"): ["NM bulk read PCKB"],
            ("NM_PATTERN", "Pattern name"): ["fbist_bulk_read_ckbd_nm.sd"],
        }
        output = io.StringIO()

        with (
            patch.object(s100_writers.G, "i", 0),
            patch.object(s100_writers.G, "BASE_DIR", r"C:\base"),
            patch.object(s100_writers.G, "OUT_DIR", r"C:\out"),
            patch.object(s100_writers.G, "col", side_effect=lambda sheet, column: tables[(sheet, column)]),
            patch.object(s100_writers.G, "flow_row_flag", return_value=None),
            patch.object(s100_writers, "copy_file") as copy_pattern,
        ):
            s100_writers.vt_write(["PROGRAM_CP1"], output, 0)

        generated = output.getvalue()
        self.assertIn(
            "RUN_PATTERN(enter_vte_verify:START,enter_vte_verify:END,1,TS_5MHZ);",
            generated,
        )
        self.assertNotIn("RUN_PATTERN(enter_vte:START", generated)
        self.assertIn(
            ((r"C:\base\pat_temp\enter_vte_verify.sd", r"C:\out\PROGRAM_CP1"), {}),
            [(call.args, call.kwargs) for call in copy_pattern.call_args_list],
        )

    def test_s100_vt_margin_uses_the_v13_verify_pattern_name(self):
        tables = {
            ("FLOW", "type"): ["margin"],
            ("FLOW", "item"): ["VTP_CKB_MARGIN"],
            ("FLOW", "CP NO"): ["CP1"],
            ("FLOW", "Vcc"): ["vcc_typ"],
            ("FLOW", "Hbin"): [9],
            ("NM_PATTERN", "used"): ["NM bulk read PCKB"],
            ("NM_PATTERN", "Pattern name"): ["fbist_bulk_read_ckbd_nm.sd"],
        }
        output = io.StringIO()

        with (
            patch.object(s100_writers.G, "i", 0),
            patch.object(s100_writers.G, "col", side_effect=lambda sheet, column: tables[(sheet, column)]),
            patch.object(s100_writers.G, "flow_row_flag", return_value=None),
        ):
            s100_writers.margin_write(["PROGRAM_CP1"], output, 0)

        generated = output.getvalue()
        self.assertIn(
            "RUN_PATTERN(enter_vtp_verify:START,enter_vtp_verify:END,1,TS_5MHZ);",
            generated,
        )
        self.assertNotIn("RUN_PATTERN(enter_vtp:START", generated)


if __name__ == "__main__":
    unittest.main()
