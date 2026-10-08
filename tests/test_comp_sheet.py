import unittest
from io import StringIO
from unittest.mock import patch

from openpyxl import Workbook

import analog_sweep as A
from program_gen.core import comp as C
from program_gen.platforms.s100 import comp_writer as S100_COMP
from program_gen.platforms.chroma import comp_writer as CHROMA_COMP
from program_gen.platforms.chroma import startup as CHROMA_STARTUP
from program_gen.platforms.s100 import startup as S100_STARTUP


def _workbook():
    wb = Workbook()
    ws = wb.active
    ws.title = "IOMUX"
    ws.append(["pin", "analog", None])
    ws.append([None, "COMP", None])
    ws.append(["PA00", "COMP1234_VINN3", None])
    ws.append(["PC02", "COMP1_VINP0/COMP1_VINP3", None])
    ws.append(["PC03", "COMP1_VINN0", None])
    ws.append(["PB13", "COMP1_VOUT", None])
    comp = wb.create_sheet("COMP")
    comp.append(["COMP", "mode", "case", "inp", "inp_force", "inn", "inn_force",
                 "expect", "down_limit", "up_limit", "step"])
    comp.append(["COMP1", "NORM", "01", 0, "3.0", 0, "1.5", "H", "/", "/", 1])
    comp.append([None, None, "01", 0, "2.0", 0, "1.5", "H", "/", "/", 1])
    comp.append([None, None, "02", 3, "2.0", "INT:DAC1", "1.2", "H", "/", "/", 2])
    return wb


class CompSheetTests(unittest.TestCase):
    def test_iomux_slash_roles_and_shared_vinn_index_are_expanded(self):
        roles = A.build_iomux_roles(_workbook())
        self.assertEqual(roles["roles"][("COMP", 1, "INP", 3)], "PC2")
        self.assertEqual(roles["roles"][("COMP", 4, "INN", 3)], "PA0")

    def test_comp_cases_support_repeated_config_and_internal_source(self):
        cases = A.comp_cases(_workbook(), required=True)
        self.assertEqual(len(cases), 3)
        self.assertEqual(cases[0]["out_pin"], "PB13")
        self.assertEqual(cases[1]["case"], "01")
        self.assertTrue(cases[2]["inn"]["internal"])
        self.assertEqual(cases[2]["inn"]["role"], "INT:DAC1")

    def test_external_source_requires_force(self):
        wb = _workbook()
        wb["COMP"]["E2"] = "/"
        with self.assertRaisesRegex(ValueError, "inp.*force"):
            A.comp_cases(wb, required=True)

    def test_internal_source_requires_reference_voltage(self):
        wb = _workbook()
        wb["COMP"]["G4"] = "/"
        with self.assertRaisesRegex(ValueError, "内部源.*参考电压"):
            A.comp_cases(wb, required=True)

    def test_package_compile_filters_absent_full_pin_cases_and_reindexes(self):
        cases = A.comp_cases(_workbook(), required=True)
        absent = dict(cases[0])
        absent["out_pin"] = "PB14"
        cases.insert(1, absent)
        compiled = C.compile_cases(cases, {"PC2", "PC3", "PB13"}, 3.3)
        self.assertEqual(len(compiled), 3)
        self.assertEqual([case["pattern_index"] for case in compiled], [1, 2, 3])
        self.assertTrue(all(case["out_pin"] == "PB13" for case in compiled))

    def test_external_pair_reverse_swaps_forces(self):
        case = A.comp_cases(_workbook(), required=True)[0]
        compiled = C.compile_cases([case], {"PC2", "PC3", "PB13"}, 3.3)[0]
        self.assertEqual(compiled["forward_forces"], {"PC2": 3.0, "PC3": 1.5})
        self.assertEqual(compiled["reverse_forces"], {"PC2": 1.5, "PC3": 3.0})
        self.assertEqual(compiled["levels"], {
            "PC2": {"vil": 1.5, "vih": 3.0},
            "PC3": {"vil": 1.5, "vih": 3.0},
        })
        self.assertEqual(compiled["forward_drive"], {"PC2": "1", "PC3": "0"})
        self.assertEqual(compiled["reverse_drive"], {"PC2": "0", "PC3": "1"})

    def test_internal_pair_reverse_mirrors_external_around_reference(self):
        case = A.comp_cases(_workbook(), required=True)[2]
        compiled = C.compile_cases([case], {"PC2", "PB13"}, 3.3)[0]
        self.assertEqual(compiled["forward_forces"], {"PC2": 2.0})
        self.assertEqual(compiled["reverse_forces"], {"PC2": 0.4})

    def test_reverse_voltage_out_of_vcc_range_is_rejected(self):
        wb = _workbook()
        wb["COMP"]["E4"] = "3.0"
        case = A.comp_cases(wb, required=True)[2]
        with self.assertRaisesRegex(ValueError, "反向电压"):
            C.compile_cases([case], {"PC2", "PB13"}, 3.3)

    def test_sheet_only_accepts_forward_h_for_present_case(self):
        case = A.comp_cases(_workbook(), required=True)[0]
        case["expect"] = "L"
        with self.assertRaisesRegex(ValueError, "expect 必须为 H"):
            C.compile_cases([case], {"PC2", "PC3", "PB13"}, 3.3)

    def test_old_cmp_sheet_name_is_accepted(self):
        wb = _workbook()
        wb["COMP"].title = "CMP"
        self.assertEqual(len(A.comp_cases(wb, required=True)), 3)

    def test_big_patterns_use_two_files_with_same_paired_labels(self):
        import os
        import tempfile
        cases = C.compile_cases(A.comp_cases(_workbook(), required=True),
                                {"PC2", "PC3", "PB13"}, 3.3)
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for platform, ext in (("chroma", ".pat"), ("s100", ".sd")):
                for expect in ("H", "L"):
                    path = os.path.join(tmp, platform + expect + ext)
                    C.write_compare_pattern(path, "COMP_" + expect, cases, platform, expect)
                    paths.append(path)
            for path in paths:
                with open(path, encoding="utf-8") as stream:
                    text = stream.read()
                self.assertIn("s001_st:", text)
                self.assertIn("s001_sp:", text)
                self.assertIn("s003_st:", text)
                self.assertNotIn("s004_st:", text)
                self.assertNotIn("_inv", text)

    def test_compare_pattern_drives_then_waits_before_comparing(self):
        import os
        import tempfile

        cases = C.compile_cases(A.comp_cases(_workbook(), required=True),
                                {"PC2", "PC3", "PB13"}, 3.3)
        with tempfile.TemporaryDirectory() as tmp:
            chroma = os.path.join(tmp, "COMP_H.pat")
            s100 = os.path.join(tmp, "COMP_H.sd")
            C.write_compare_pattern(chroma, "COMP_H", cases, "chroma", "H")
            C.write_compare_pattern(s100, "COMP_H", cases, "s100", "H")
            with open(chroma, encoding="utf-8") as stream:
                chroma_text = stream.read()
            with open(s100, encoding="utf-8") as stream:
                s100_text = stream.read()

        self.assertIn("s001_st:\n  *XXX*RPT 100;\n  *10X*RPT 20000;\n  *10H*RPT 9;", chroma_text)
        self.assertIn("s001_sp:\n  *10H*;", chroma_text)
        self.assertIn("s001_st:XXX;RPT 100;", s100_text)
        self.assertIn("                         10X;RPT 20000;\n"
                      "                         10H;RPT 9;", s100_text)
        self.assertIn("s001_sp:10H;", s100_text)

        s100_case_lines = [line for line in s100_text.splitlines()
                           if line.startswith("s001_") or line.startswith("      ")][:4]
        vector_columns = []
        for line in s100_case_lines:
            search_from = line.index(":") + 1 if ":" in line else 0
            vector_columns.append(next(i for i in range(search_from, len(line))
                                       if line[i] in "01HLX"))
        self.assertEqual(len(set(vector_columns)), 1,
                         "S100 COMP pattern 的 label 行和后续向量行必须列对齐")

    def test_low_pattern_selects_per_pin_reverse_level(self):
        import os
        import tempfile
        cases = C.compile_cases(A.comp_cases(_workbook(), required=True),
                                {"PC2", "PC3", "PB13"}, 3.3)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "COMP_L.pat")
            C.write_compare_pattern(path, "COMP_L", cases, "chroma", "L")
            with open(path, encoding="utf-8") as stream:
                text = stream.read()
        self.assertIn("s001_st:\n  *XXX*RPT 100;\n  *01X*RPT 20000;\n  *01L*RPT 9;", text)

    def test_s100_stub_uses_final_nrst_alias(self):
        import os
        import tempfile

        version = {
            "CLK PIN": ["PA11"],
            "SWD PIN": ["PA13"],
            "NRST PIN": ["PD11"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "COMP_INIT.sd")
            with patch.object(S100_COMP.G, "i", 0), \
                    patch.object(S100_COMP.G, "col", side_effect=lambda _sheet, col: version[col]):
                S100_COMP._stub(path)
            with open(path, encoding="utf-8") as stream:
                text = stream.read()
        self.assertIn("PA11,PA13,NRST;", text)
        self.assertNotIn("PD11", text)

    def test_zero_package_cases_are_removed_from_both_schedulers(self):
        cols = {
            ("FLOW", "item"): ["Comp_Test"],
            ("FLOW", "CP NO"): ["CP3"],
            ("FLOW", "FV/FI"): ["COMP"],
            ("FLOW", "Bisection"): ["/"],
        }
        def col(sheet, name):
            return cols[(sheet, name)]

        chroma_out = StringIO()
        with patch.object(CHROMA_STARTUP.G, "i", 0), \
                patch.object(CHROMA_STARTUP.G, "f", chroma_out), \
                patch.object(CHROMA_STARTUP.G, "OUT_DIR", r"C:\tmp"), \
                patch.object(CHROMA_STARTUP.G, "col", side_effect=col), \
                patch.object(CHROMA_STARTUP.G, "flow_row_flag", return_value=None), \
                patch.object(CHROMA_COMP, "package_cases", return_value=[]):
            CHROMA_STARTUP.TEST_PRO(["DEMO_CP3"], trim_specs={})
        self.assertNotIn("Comp_Test", chroma_out.getvalue())

        s100_out = StringIO()
        with patch.object(S100_STARTUP.G, "i", 0), \
                patch.object(S100_STARTUP.G, "col", side_effect=col), \
                patch.object(S100_COMP, "package_cases", return_value=[]):
            S100_STARTUP.Hw_Sw_Bin(["DEMO_CP3"], s100_out, trim_specs={})
        self.assertNotIn("Comp_Test", s100_out.getvalue())

    def test_swd_power_and_init_wrap_the_case_loop_once(self):
        import os
        import tempfile

        cases = C.compile_cases(A.comp_cases(_workbook(), required=True),
                                {"PC2", "PC3", "PB13"}, 3.3)
        cols = {
            ("FLOW", "mode"): ["swd"], ("FLOW", "CP NO"): ["CP3"],
            ("FLOW", "type"): ["verify"], ("FLOW", "item"): ["Comp_Test"],
            ("FLOW", "Vcc"): ["VCC_TYP"], ("FLOW", "UNIT"): ["pat"],
            ("FLOW", "sub"): ["COMP_INIT"], ("FLOW", "step"): ["X"],
            ("FLOW", "Hbin"): [28],
            ("VERSION", "product name"): ["PT104"],
            ("VERSION", "vcc min"): [2.7], ("VERSION", "vcc typ"): [3.3],
            ("VERSION", "vcc max"): [5.5], ("VERSION", "GET PIN"): ["PA0"],
            ("VERSION", "CLK PIN"): ["PA11"], ("VERSION", "SWD PIN"): ["PA13"],
            ("VERSION", "NRST PIN"): ["PD11"],
        }
        def col(sheet, name):
            return cols[(sheet, name)]

        with tempfile.TemporaryDirectory() as tmp:
            chroma_out = StringIO()
            pat_dir = os.path.join(tmp, "pat")
            os.makedirs(pat_dir)
            with patch.object(CHROMA_COMP.G, "i", 0), \
                    patch.object(CHROMA_COMP.G, "col", side_effect=col), \
                    patch.object(CHROMA_COMP, "package_cases", return_value=cases), \
                    patch.object(CHROMA_COMP, "write_placeholder_pat"):
                CHROMA_COMP.comp_test_write(["DEMO_CP3"], chroma_out, 0, pat_dir)
            chroma_text = chroma_out.getvalue()
            self.assertEqual(chroma_text.count("POWER_ON(VCC_TYP)"), 1)
            self.assertEqual(chroma_text.count("POWER_OFF()"), 1)
            self.assertEqual(chroma_text.count("JUDGE_PAT(PT104_COMP_INIT"), 1)

            s100_out = StringIO()
            os.makedirs(os.path.join(tmp, "DEMO_CP3"))
            with patch.object(S100_COMP.G, "i", 0), \
                    patch.object(S100_COMP.G, "OUT_DIR", tmp), \
                    patch.object(S100_COMP.G, "col", side_effect=col), \
                    patch.object(S100_COMP, "package_cases", return_value=cases), \
                    patch.object(S100_COMP, "_stub"):
                S100_COMP.comp_test_write(["DEMO_CP3"], s100_out, 0)
            s100_text = s100_out.getvalue()
            self.assertEqual(s100_text.count("CALL_MACRO POWER_ON(_C_VCC_TYP)"), 1)
            self.assertEqual(s100_text.count("CALL_MACRO POWER_OFF()"), 1)
            self.assertEqual(s100_text.count("RUN_PATTERN(PT104_COMP_INIT:"), 1)

    def test_keil_flow_step_wraps_switch_and_sheet_step_stays_in_case(self):
        import os
        import tempfile

        cases = C.compile_cases(A.comp_cases(_workbook(), required=True),
                                {"PC2", "PC3", "PB13"}, 3.3)
        cols = {
            ("FLOW", "mode"): ["keil"], ("FLOW", "CP NO"): ["CP3"],
            ("FLOW", "type"): ["verify"], ("FLOW", "item"): ["Comp_Test"],
            ("FLOW", "Vcc"): ["VCC_TYP"], ("FLOW", "UNIT"): ["pat"],
            ("FLOW", "sub"): ["/"], ("FLOW", "step"): ["FLOW-X-END"],
            ("FLOW", "Hbin"): [28],
            ("VERSION", "product name"): ["PT104"],
            ("VERSION", "vcc min"): [2.7], ("VERSION", "vcc typ"): [3.3],
            ("VERSION", "vcc max"): [5.5], ("VERSION", "GET PIN"): ["PA0"],
        }
        def col(sheet, name):
            return cols[(sheet, name)]
        def marker(out, *_args, **kwargs):
            out.write("  MARK_" + str(kwargs["step_override"]) + "\n")
        def marker_s100(out, *_args, **kwargs):
            out.write("\tMARK_" + str(kwargs["step_override"]) + "\n")

        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(CHROMA_COMP.G, "i", 0), \
                patch.object(CHROMA_COMP.G, "col", side_effect=col), \
                patch.object(CHROMA_COMP, "package_cases", return_value=cases), \
                patch.object(CHROMA_COMP, "_keil_step_write", side_effect=marker):
            out = StringIO()
            CHROMA_COMP.comp_test_write(["DEMO_CP3"], out, 0, tmp)
            text = out.getvalue()
        self.assertEqual(text.count("MARK_FLOW"), 1)
        self.assertEqual(text.count("MARK_END"), 1)
        self.assertLess(text.index("MARK_FLOW"), text.index("switch(comp_index)"))
        self.assertGreater(text.index("MARK_END"), text.index("    }\n"))
        self.assertEqual(text.count("MARK_1"), 2)
        self.assertEqual(text.count("MARK_2"), 1)
        self.assertIn("    MARK_FLOW\n", text)
        self.assertIn("        MARK_1\n", text)
        self.assertIn("    MARK_END\n", text)

        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(S100_COMP.G, "i", 0), \
                patch.object(S100_COMP.G, "OUT_DIR", tmp), \
                patch.object(S100_COMP.G, "col", side_effect=col), \
                patch.object(S100_COMP, "package_cases", return_value=cases), \
                patch.object(S100_COMP, "_keil_step_write", side_effect=marker_s100):
            os.makedirs(os.path.join(tmp, "DEMO_CP3"))
            out = StringIO()
            S100_COMP.comp_test_write(["DEMO_CP3"], out, 0)
            text = out.getvalue()
        self.assertEqual(text.count("MARK_FLOW"), 1)
        self.assertEqual(text.count("MARK_END"), 1)
        self.assertLess(text.index("MARK_FLOW"), text.index("switch(comp_index)"))
        self.assertEqual(text.count("MARK_1"), 2)
        self.assertEqual(text.count("MARK_2"), 1)
        self.assertIn("\t\tMARK_FLOW\n", text)
        self.assertIn("\t\t\t\tMARK_1\n", text)
        self.assertIn("\t\tMARK_END\n", text)


if __name__ == "__main__":
    unittest.main()
