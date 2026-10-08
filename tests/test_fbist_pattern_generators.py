"""Dual-platform FBIST Pattern Generators execute the plan into artifacts.

The generators must be pure functions of ``FbistPatternGenerationPlan``:
no workbook, no DataFrame, no VERSION/FB MAP, no global ``G``, no file I/O.
Expected file contents below pin the exact legacy vector layout.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

from tests.test_fbist_pattern_plan import compile_fixture

from program_gen.core.fbist_pattern_plan import AGGREGATE_PATTERN_NAME
from program_gen.platforms.chroma.fbist_pattern_generator import (
    generate_fbist_patterns as generate_chroma,
)
from program_gen.platforms.s100.fbist_pattern_generator import (
    generate_fbist_patterns as generate_s100,
)


SET_PATTERN_ROWS = [
    {"item": "Vref0p8_ABS", "addr": "0000000", "description": "8,BG_ABS_TRIM[3:0]=0000*", "pattern": "trim dac"},
    {"addr": "0100010", "description": "2,fbist_trg=0"},
]

AGGREGATE_ROWS = [
    {"item": "Vposp", "addr": "0010100", "description": "9,prog_pdac[4:0]=00000*", "pattern": "trim dac"},
    {"item": "Vnegp", "addr": "0010100", "description": "4,prog_ndac[4:0]=00000*", "pattern": "trim dac"},
]

PUMP_FLOW = [
    {"CP NO": "CP1", "item": "Vposp", "type": "trim", "PUMP": "yes"},
    {"CP NO": "CP1", "item": "Vnegp", "type": "trim", "PUMP": "yes"},
]

EXPECTED_CHROMA_SET = """SET_DEC_FILE "pin.dec"

HEADER

PA11, PA13, NRST;

SPM_PATTERN(set_vref0p8_abs_dac) {

  *011*TS1;
  *011*RPT 100;

  *111*;
  *111*RPT 50;// wait 50 us
  *111*;

  *111*;
  *111*;
  *110*;// 1 bit strobe
  *111*;// PA13=1, write register
  *101*;// 7bits addr0000000
  *101*;
  *101*;
  *101*;
  *101*;
  *101*;
  *101*;

  *101*;// 16bits data
  *101*;
  *101*;
  *101*;

  *101*;
  *101*;
  *101*;
a_data:
  *101*;// BG_ABS_TRIM[3:0]=0000*

  *101*;
  *101*;
  *101*;
  *101*;

  *101*;
  *101*;
  *101*;
  *101*;

  *111*;
  *111*RPT 50;// wait 50 us
  *111*;

  *111*;
  *111*;
  *110*;// 1 bit strobe
  *111*;// PA13=1, write register
  *101*;// 7bits addr0100010
  *111*;
  *101*;
  *101*;
  *101*;
  *111*;
  *101*;

  *101*;// 16bits data
  *101*;
  *101*;
  *101*;

  *101*;
  *101*;
  *101*;
  *101*;

  *101*;
  *101*;
  *101*;
  *101*;

  *101*;
  *101*;// fbist_trg=0
  *101*;
  *101*;

  *111*;
  *111*RPT 1000;// wait 100us 
  *111*;
  *011*STOP;

}"""

EXPECTED_CHROMA_AGGREGATE = """SET_DEC_FILE "pin.dec"

HEADER

PA11, PA13, NRST;

SPM_PATTERN(set_all_final_vposp) {

  *011*TS1;
  *011*RPT 100;

  *111*;
  *111*RPT 50;// wait 50 us
  *111*;

  *111*;
  *111*;
  *110*;// 1 bit strobe
  *111*;// PA13=1, write register
  *101*;// 7bits addr0010100
  *101*;
  *111*;
  *101*;
  *111*;
  *101*;
  *101*;

  *101*;// 16bits data
  *101*;
  *101*;
  *101*;

  *101*;
  *101*;
prog_pdac:
  *101*;// prog_pdac[4:0]=00000*
  *101*;

  *101*;
  *101*;
  *101*;
prog_ndac:
  *101*;// prog_ndac[4:0]=00000*

  *101*;
  *101*;
  *101*;
  *101*;

  *111*;
  *111*RPT 1000;// wait 100us 
  *111*;
  *011*STOP;

}"""

EXPECTED_S100_SET = """HEAD[PIN_NAME]:

PA11, PA13, NRST,TRIGPIN;

END_HEAD;

@@PATTERN_DEFINE

    START:0111;
          0111;RPT 100;

          1111;
          1111;RPT 50;// wait 50 us
          1111;

          1111;
          1111;
          1101;// 1 bit strobe
          1111;// PA13=1, write register
          1011;//7bits addr0000000
          1011;
          1011;
          1011;
          1011;
          1011;
          1011;

          1011;//16bits data
          1011;
          1011;
          1011;

          1011;
          1011;
          1011;
a_data_st:1010;//BG_ABS_TRIM[3:0]=0000*

          1010;
          1010;
a_data_sp:1010;
          1011;

          1011;
          1011;
          1011;
          1011;

          1111;
          1111;RPT 50;// wait 50 us
          1111;

          1111;
          1111;
          1101;// 1 bit strobe
          1111;// PA13=1, write register
          1011;//7bits addr0100010
          1111;
          1011;
          1011;
          1011;
          1111;
          1011;

          1011;//16bits data
          1011;
          1011;
          1011;

          1011;
          1011;
          1011;
          1011;

          1011;
          1011;
          1011;
          1011;

          1011;
          1010;//fbist_trg=0
          1010;
          1010;

          1110;
          1110;RPT 1000;// wait 100 us
          1110;
      END:0110;

@@END_PATTERN_DEFINE """

EXPECTED_S100_AGGREGATE = """HEAD[PIN_NAME]:

PA11, PA13, NRST,TRIGPIN;

END_HEAD;

@@PATTERN_DEFINE

       START:0111;
             0111;RPT 100;

             1111;
             1111;RPT 50;// wait 50 us
             1111;

             1111;
             1111;
             1101;// 1 bit strobe
             1111;// PA13=1, write register
             1011;//7bits addr0010100
             1011;
             1111;
             1011;
             1111;
             1011;
             1011;

             1011;//16bits data
             1011;
             1011;
             1011;

             1011;
             1011;
prog_pdac_st:1010;//prog_pdac[4:0]=00000*
             1010;

             1010;
             1010;
prog_pdac_sp:1010;
prog_ndac_st:1010;//prog_ndac[4:0]=00000*

             1010;
             1010;
             1010;
prog_ndac_sp:1010;

             1111;
             1111;RPT 1000;// wait 100 us
             1111;
         END:0111;

@@END_PATTERN_DEFINE """


class ChromaGeneratorTests(unittest.TestCase):
    def test_generates_ordinary_set_pattern_with_serial_label(self):
        plan = compile_fixture(pattern_rows=SET_PATTERN_ROWS, flow_rows=[])
        result = generate_chroma(plan)

        self.assertEqual(result.platform, "chroma")
        self.assertEqual(len(result.artifacts), 1)
        artifact = result.artifacts[0]
        self.assertEqual(artifact.pattern_name, "set_vref0p8_abs_dac")
        self.assertEqual(artifact.relative_path, "pat/set_vref0p8_abs_dac.pat")
        self.assertEqual(artifact.content.decode("ascii"), EXPECTED_CHROMA_SET)
        self.assertIn("fbist-pattern:fixture-identity:set_vref0p8_abs_dac:sha256:", artifact.source_identity)
        self.assertEqual(result.label_catalog, ())

    def test_generates_aggregate_with_field_labels_and_catalog(self):
        plan = compile_fixture(pattern_rows=AGGREGATE_ROWS, flow_rows=PUMP_FLOW)
        result = generate_chroma(plan)

        names = tuple(artifact.pattern_name for artifact in result.artifacts)
        self.assertEqual(names, ("set_vposp_dac", "set_vnegp_dac", AGGREGATE_PATTERN_NAME))
        aggregate = result.artifacts[-1]
        self.assertEqual(aggregate.relative_path, "pat/set_all_final_vposp.pat")
        self.assertEqual(aggregate.content.decode("ascii"), EXPECTED_CHROMA_AGGREGATE)

        catalog = result.label_catalog
        self.assertEqual(
            tuple(entry.logical_field_identity for entry in catalog),
            ("Vposp:prog_pdac", "Vnegp:prog_ndac"),
        )
        prog = catalog[0]
        self.assertEqual(prog.pattern_identity, AGGREGATE_PATTERN_NAME)
        self.assertEqual(prog.chroma_start_label, "prog_pdac")
        self.assertEqual(prog.chroma_end_label, "")
        self.assertEqual(prog.s100_start_label, "prog_pdac_st")
        self.assertEqual(prog.s100_end_label, "prog_pdac_sp")
        self.assertEqual((prog.addr_bits, prog.bit_hi, prog.bit_lo, prog.bit_width), ("0010100", 9, 5, 5))
        self.assertTrue(prog.dynamic)

    def test_enter_pattern_has_no_labels_and_plain_header(self):
        plan = compile_fixture(
            pattern_rows=[
                {"item": "Vpose", "addr": "0011101", "description": "7,trim_sel=1\n6,sleep=0\n5,reset=0\n4,tmode[4:0]=01110", "pattern": "trim mode"},
            ],
            flow_rows=[],
        )
        result = generate_chroma(plan)
        self.assertEqual(len(result.artifacts), 1)
        text = result.artifacts[0].content.decode("ascii")
        self.assertIn("SPM_PATTERN(enter_vpose) {", text)
        self.assertNotIn("_data:", text)
        self.assertIn("  *111*;// trim_sel=1", text)
        self.assertNotIn("set_all_final_vposp", text)

    def test_dynamic_enter_pattern_gets_serial_label_without_runtime_consumer(self):
        plan = compile_fixture(
            pattern_rows=[
                {"item": "Mr_VDDD_DC", "addr": "0101110", "description": "2,MR_VSEL_OPTR_VDDK=001*", "pattern": "trim mode"},
            ],
            flow_rows=[],
        )
        self.assertEqual(plan.dynamic_enter_patterns, ())
        result = generate_chroma(plan)
        text = result.artifacts[0].content.decode("ascii")
        self.assertIn("a_data:\n", text)

    def test_generator_rejects_non_plan_input(self):
        with self.assertRaises(TypeError):
            generate_chroma(object())
        with self.assertRaises(TypeError):
            generate_chroma("set_all_final_vposp")


class S100GeneratorTests(unittest.TestCase):
    def test_generates_ordinary_set_pattern_with_serial_labels_and_trigpin_state(self):
        plan = compile_fixture(pattern_rows=SET_PATTERN_ROWS, flow_rows=[])
        result = generate_s100(plan)

        self.assertEqual(result.platform, "s100")
        self.assertEqual(len(result.artifacts), 1)
        artifact = result.artifacts[0]
        self.assertEqual(artifact.pattern_name, "set_vref0p8_abs_dac")
        self.assertEqual(artifact.relative_path, "set_vref0p8_abs_dac.sd")
        self.assertEqual(artifact.content.decode("ascii"), EXPECTED_S100_SET)

    def test_generates_aggregate_with_st_sp_labels(self):
        plan = compile_fixture(pattern_rows=AGGREGATE_ROWS, flow_rows=PUMP_FLOW)
        result = generate_s100(plan)

        aggregate = result.artifacts[-1]
        self.assertEqual(aggregate.relative_path, "set_all_final_vposp.sd")
        self.assertEqual(aggregate.content.decode("ascii"), EXPECTED_S100_AGGREGATE)
        self.assertEqual(
            tuple(entry.s100_start_label for entry in result.label_catalog),
            ("prog_pdac_st", "prog_ndac_st"),
        )

    def test_enter_pattern_uses_semicolon_end_and_plain_header(self):
        plan = compile_fixture(
            pattern_rows=[
                {"item": "Vpose", "addr": "0011101", "description": "7,trim_sel=1\n6,sleep=0\n5,reset=0\n4,tmode[4:0]=01110", "pattern": "trim mode"},
            ],
            flow_rows=[],
        )
        result = generate_s100(plan)
        text = result.artifacts[0].content.decode("ascii")
        self.assertIn("PA11, PA13, NRST;\n", text)
        self.assertNotIn("TRIGPIN", text)
        self.assertIn("START:011;", text)
        self.assertIn("END:011;", text)
        self.assertNotIn("_st:", text)

    def test_dynamic_enter_pattern_gets_write_region_without_runtime_consumer(self):
        plan = compile_fixture(
            pattern_rows=[
                {"item": "Mr_VDDD_DC", "addr": "0101110", "description": "2,MR_VSEL_OPTR_VDDK=001*", "pattern": "trim mode"},
            ],
            flow_rows=[],
        )
        self.assertEqual(plan.dynamic_enter_patterns, ())
        result = generate_s100(plan)
        text = result.artifacts[0].content.decode("ascii")
        self.assertIn("a_data_st:", text)
        self.assertIn("a_data_sp:", text)

    def test_output_is_deterministic(self):
        plan = compile_fixture(pattern_rows=AGGREGATE_ROWS, flow_rows=PUMP_FLOW)
        first = generate_chroma(plan)
        second = generate_chroma(plan)
        self.assertEqual(
            tuple(artifact.content for artifact in first.artifacts),
            tuple(artifact.content for artifact in second.artifacts),
        )
        self.assertEqual(first.label_catalog, second.label_catalog)
        s100_first = generate_s100(plan)
        s100_second = generate_s100(plan)
        self.assertEqual(
            tuple(artifact.content for artifact in s100_first.artifacts),
            tuple(artifact.content for artifact in s100_second.artifacts),
        )

    def test_results_are_immutable(self):
        plan = compile_fixture(pattern_rows=AGGREGATE_ROWS, flow_rows=PUMP_FLOW)
        result = generate_chroma(plan)
        with self.assertRaises(FrozenInstanceError):
            result.artifacts = ()
        with self.assertRaises(FrozenInstanceError):
            result.label_catalog = ()


class GeneratorBoundaryTests(unittest.TestCase):
    """The generators are pure plan executors: no workbook/global/file access."""

    def test_generator_modules_do_not_read_workbook_or_global_state(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        forbidden = (
            "WorkbookReader",
            "openpyxl",
            "import pandas",
            "from program_gen import state",
            "G.PATTERN",
            "G.wb",
            "G.wc",
            "G.exegesis",
            "G.BASE_DIR",
            "copy_file",
            "os.makedirs",
            "open(",
        )
        modules = (
            root / "program_gen" / "platforms" / "chroma" / "fbist_pattern_generator.py",
            root / "program_gen" / "platforms" / "s100" / "fbist_pattern_generator.py",
        )
        for module in modules:
            with self.subTest(module=module.name):
                source = module.read_text(encoding="utf-8")
                self.assertEqual(
                    tuple(token for token in forbidden if token in source),
                    (),
                    f"{module.name} must not touch workbook/global/file facts",
                )


if __name__ == "__main__":
    unittest.main()
