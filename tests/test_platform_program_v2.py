"""Generic Platform Program Frame / Skeleton V2 contracts."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re
from types import SimpleNamespace
import unittest

import pandas as pd

from program_gen.compiler import ProductCompiler
from program_gen.platform_program import (
    WorkspacePatternProducer,
    build_standard_trim_program_plan,
    compile_platform_program_facts,
)
from program_gen.platform_program.facts import (
    PinBinding,
    _program_version_token,
    compile_pin_group_facts,
)
from program_gen.platform_program.s100 import S100SkeletonSyntax, project_contribution as s100_project_contribution
from program_gen.platform_program.chroma import (
    ChromaSkeletonSyntax,
    project_contribution as chroma_project_contribution,
)
from program_gen.standard_trim.support import _globals as standard_trim_globals
from program_gen.render_plan import RenderSymbolRef, SectionFragment, TargetKey
from program_gen.skeleton import SkeletonBody
from program_gen.workbook import WorkbookReader
from program_gen.workbook import TableModel
from tests.workspace_paths import FORMAL_MASTER, WORKSPACE_ROOT


class PlatformProgramV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()
        cls.spec = next(
            item for item in cls.compilation.plan.catalogs.trim_specs.values()
            if item.cp == "CP1" and item.item == "Hsi_8M"
        )

    def _source(self, platform: str):
        target = TargetKey(platform, "CP1", "lab", f"V2_{platform.upper()}_CP1")
        plan = build_standard_trim_program_plan(
            self.compilation,
            target,
            specs=(self.spec,),
            platform_facts=compile_platform_program_facts(self.workbook, target),
            pattern_producer=WorkspacePatternProducer(
                WORKSPACE_ROOT / "input" / platform
            ),
        )
        extension = "pln" if platform == "chroma" else "prg"
        return plan, plan.artifact(f"{target.program_name}.{extension}").content.decode("gbk")

    def test_chroma_scheduled_body_gets_one_item_level_datalog_header(self):
        definition = SimpleNamespace(
            identity="definition:sram",
            render_name="Sram_Ckb_Test",
            source_rows=(80,),
        )
        entry = SimpleNamespace(
            identity="entry:sram",
            definition_id=definition.identity,
            render_name=definition.render_name,
        )
        syntax = ChromaSkeletonSyntax(
            SimpleNamespace(),
            (entry,),
            SimpleNamespace(definitions=(definition,), entries=(entry,)),
        )
        body = SkeletonBody(
            RenderSymbolRef("TEST_BODY", "chroma:entry:sram"),
            SectionFragment(
                "PROGRAM.pln",
                "TESTS",
                "sram:body",
                b"Sram_Ckb_Test()\r\n{\r\n"
                b"  SOCKET_SET(B:CP1_BAKEID_NEEDS_WRITE,FRZ_OFF)\r\n"
                b"  {\r\n  POWER_ON(VCC_MAX);\r\n  }\r\n}\r\n",
            ),
        )

        normalized = syntax.normalize_bodies((body,))
        source = syntax.normalize_bodies(normalized)[0].fragment.content.decode("gbk")

        self.assertIn(
            "{\r\n  TEST_NUM=7900;\r\n"
            '  TEST_NO(TEST_NUM);DATALOG_MSG="Sram_Ckb_Test";\r\n',
            source,
        )
        self.assertEqual(source.count('DATALOG_MSG="Sram_Ckb_Test"'), 1)
        self.assertIn(
            "  SOCKET_SET(B:CP1_BAKEID_NEEDS_WRITE,FRZ_OFF)\r\n"
            "  {\r\n"
            "    POWER_ON(VCC_MAX);\r\n"
            "  }\r\n",
            source,
        )
        self.assertTrue(source.endswith("}\r\n\r\n"))

    def test_s100_body_boundary_has_one_blank_line(self):
        syntax = S100SkeletonSyntax(SimpleNamespace(), ())
        for ending in (b"", b"\r\n", b"\r\n\r\n\r\n"):
            body = SkeletonBody(
                RenderSymbolRef("TEST_BODY", "s100:entry:test"),
                SectionFragment("PROGRAM.prg", "TESTS", "test:body", b"@@PLAN Test\r\n@@END_PLAN" + ending),
            )
            normalized = syntax.normalize_bodies((body,))
            self.assertEqual(normalized[0].fragment.content, b"@@PLAN Test\r\n@@END_PLAN\r\n\r\n")
            self.assertEqual(syntax.normalize_bodies(normalized), normalized)

    def test_chroma_baseline_is_complete_without_pdr(self):
        _plan, source = self._source("chroma")
        for token in (
            "GLOBAL int LIST_TEST_TIME = 0;",
            "bool VTEN_FLAG = false;",
            "VTEN_FLAG=true;",
            "VTEN_FLAG=false;",
            "VOLTAGE VTE_VOLTAGE = ",
            "TIME FSCLK_500K = 2000nS;",
            "TIME FSCLK_ERASE = ",
            "TIME FSCLK_PGM = ",
            "RATEN(TS2,FSCLK_500K);",
            "RATEN(TS5,FSCLK_ERASE);",
            "RATEN(TS6,FSCLK_PGM);",
            "void convert_to_string(",
            "READ_PROBER_XY(X_CO,Y_CO);",
        ):
            self.assertIn(token, source)
        self.assertNotIn("PDR_MIN_LVL", source)
        self.assertNotIn("VTEN_FLAG=1;", source)
        self.assertNotIn("VTEN_FLAG=0;", source)

    def test_s100_baseline_always_contains_non_pdr_timesets(self):
        plan, source = self._source("s100")
        timing = plan.artifact("V2_S100_CP1.tim").content.decode("gbk")
        for token in (
            "[NAME=TS_5MHZ]", "[NAME=TS_500K]",
            "[NAME=TS_erase]", "[NAME=TS_pgm]",
        ):
            self.assertIn(token, timing)
        self.assertIn("int main_data[MAX_SITE][256];", source)
        self.assertIn("@@MACRO Clear_GB()", source)
        self.assertIn("CALL_MACRO Clear_GB();", source)
        self.assertIn("@@MACRO write_pat_temp_arry(int* a)", source)
        self.assertIn("if(Sys_ActiveSite[T_SOCKET]==0)continue;", source)
        self.assertIn("GB[0+T_SOCKET*64]=a[T_SOCKET];", source)

    def test_complete_project_artifacts_publish_platform_pin_groups(self):
        chroma_plan, _source = self._source("chroma")
        chroma_dec = chroma_plan.artifact("pat/pin.dec").content.decode("gbk")
        self.assertIn("   // Pin Name     = Tester Channels = Pin No. = Type", chroma_dec)
        self.assertNotIn("   IO_ALLPINS =", chroma_dec)
        self.assertIn(
            "   ODD_pins = PC15+PD1+NRST+PA1+PA7+PA9+PA13+PA14+PC10+PD2;",
            chroma_dec,
        )
        self.assertIn(
            "   EVEN_pins = PC14+PD0+PA0+PA2+PA8+PA11+PA15+PC12;",
            chroma_dec,
        )

        s100_plan, _source = self._source("s100")
        s100_prj = s100_plan.artifact("V2_S100_CP1.prj").content.decode("gbk")
        self.assertIn("   // Pin Name        ,Type,No.,Site tester channels;", s100_prj)
        self.assertIn("   IO_ALLPINS,[1,2,3,4,6,7,8,9,10,11,12,13,14,16,17,18,19,20,21];", s100_prj)
        self.assertIn("   ODD_pins,[1,3,7,9,11,13,17,19];", s100_prj)
        self.assertIn("   EVEN_pins,[2,4,6,8,10,12,14,16,18,20];", s100_prj)

    def test_multisite_s100_pin_groups_use_chip_pin_number_parity(self):
        pins = (
            PinBinding("PA0", "io", 1, ("102", "203")),
            PinBinding("PA1", "io", 2, ("101", "202")),
            PinBinding("TP", "io", 3, ("103", "203")),
            PinBinding("VCC", "pwr", 4, ("LOGIC_DPS1", "LOGIC_DPS2")),
        )
        groups = compile_pin_group_facts("s100", pins)
        target = TargetKey("s100", "CP1", "fixture", "V2_S100_2SITE")
        base_facts = compile_platform_program_facts(
            self.workbook, TargetKey("s100", "CP1", "lab", "unused")
        )
        facts = replace(
            base_facts,
            site_count=2,
            pins=pins,
            pin_groups=groups,
            io_pins=("PA0", "PA1", "TP"),
            power_pins=("VCC",),
            force_rails=("VCC",),
        )

        contribution = s100_project_contribution(
            target, facts, pattern_names=(), bins=(1,), timing_sets=()
        )
        project = next(
            resource for resource in contribution.resources
            if resource.relative_path == "V2_S100_2SITE.prj"
        ).content.decode("gbk")

        self.assertIn("TEST_DIE      = 2;", project)
        self.assertIn("   IO_ALLPINS,[1,2,3];", project)
        self.assertIn("   ODD_pins,[1];", project)
        self.assertIn("   EVEN_pins,[2];", project)

    def test_formal_chroma_production_pin_facts_cover_all_declared_sites(self):
        target = TargetKey(
            "chroma",
            "CP1",
            "production",
            "V_PCD2509V1_PY32F420A_C8_30C_V00_50_24SS_CP1",
        )

        facts = compile_platform_program_facts(self.workbook, target)

        self.assertEqual(facts.site_count, 84)
        self.assertTrue(facts.pins)
        self.assertTrue(
            all(len(pin.channels) == facts.site_count for pin in facts.pins)
        )

    def test_production_pin_facts_classify_blank_xy_channels_as_relays(self):
        pin_dec = self.workbook.dataframe("PIN DEC")
        cp1 = pin_dec[
            pin_dec["CP NO"].astype(str).str.strip().str.upper() == "CP1"
        ]
        relay_rows = []
        for site in sorted({int(value) for value in cp1["Site"]}):
            row = {column: None for column in pin_dec.columns}
            row.update({
                "CP NO": "CP1",
                "Trace": "150",
                "E/C(Pad Name)": "UR_OS",
                "Site": site,
            })
            relay_rows.append(row)
        extended = pd.concat(
            [pin_dec, pd.DataFrame(relay_rows)],
            ignore_index=True,
        )
        workbook = replace(
            self.workbook,
            tables=tuple(
                TableModel.from_dataframe(table.title, extended)
                if table.title == "PIN DEC" else table
                for table in self.workbook.tables
            ),
        )

        facts = compile_platform_program_facts(
            workbook,
            TargetKey("chroma", "CP1", "production", "RELAY_FACTS_CP1"),
        )

        self.assertEqual(tuple(pin.name for pin in facts.relay_pins), ("UR_OS",))
        self.assertEqual(facts.relay_pins[0].kind, "relay")
        self.assertNotIn("UR_OS", facts.io_pins)

    def test_project_resources_declare_typed_relay_channels(self):
        for platform in ("chroma", "s100"):
            with self.subTest(platform=platform):
                target = TargetKey(platform, "CP1", "lab", f"RELAY_{platform}")
                facts = compile_platform_program_facts(self.workbook, target)
                relay = PinBinding(
                    "UR_OS", "relay",
                    max(pin.pin_no for pin in facts.pins) + 1,
                    ("150",),
                )
                facts = replace(
                    facts,
                    pins=(*facts.pins, relay),
                    relay_pins=(relay,),
                )
                if platform == "chroma":
                    contribution = chroma_project_contribution(target, facts)
                    project = contribution.resources[0].content.decode("gbk")
                    self.assertIn("UR_OS", project)
                    self.assertIn("= 150 =     = UR;", project)
                else:
                    contribution = s100_project_contribution(
                        target, facts, pattern_names=(), bins=(1,), timing_sets=()
                    )
                    project = next(
                        resource for resource in contribution.resources
                        if resource.relative_path.endswith(".prj")
                    ).content.decode("gbk")
                    self.assertIn("UR_OS", project)
                    relay_table = project.split("@@USER_RELAY_TABLE", 1)[1].split(
                        "@@END_USER_RELAY_TABLE", 1
                    )[0]
                    self.assertIn("150;", relay_table)
                    pin_group_table = project.split("@@PIN_GROUP_TABLE", 1)[1].split(
                        "@@END_PIN_GROUP_TABLE", 1
                    )[0]
                    self.assertIn('UR_OS,["150"];', pin_group_table)

    def test_s100_schedule_and_startup_are_rendered_as_public_blocks(self):
        _plan, source = self._source("s100")
        unbooking = source.index("@@UNBOOKING")
        startup = source.index("@@START_UP\r\n")
        first_plan = source.index("@@PLAN")
        booking = source.index("@@BOOKING")
        self.assertLess(unbooking, startup)
        self.assertLess(startup, first_plan)
        self.assertLess(first_plan, booking)
        self.assertGreater(booking, source.rindex("@@END_PLAN"))
        self.assertIn(
            "@@UNBOOKING\r\n\tOTP_Read;\r\n\tNM_Data_Read;\r\n@@END_UNBOOKING",
            source,
        )
        self.assertIn(
            "@@START_UP\r\n"
            "\tIO_SET_DUT_BOARD_POWER(ON,5V_USER_POWER);\r\n"
            "\tWAIT(3ms);\r\n"
            "\tblSoftwareBin=1;\r\n"
            "\tLOGIC_SET_DRV_LEVEL(IO_ALLPINS,0.0V,0.0V,0.0V,VR1);\r\n"
            "\tLOGIC_SET_CMP_LEVEL(IO_ALLPINS,0.0V,0.0V,VR2);\r\n"
            "\tWAIT(20MS);\r\n"
            "@@END_START_UP",
            source,
        )

    def test_each_flow_row_comments_its_actual_software_bin_at_one_column(self):
        _plan, chroma = self._source("chroma")
        test_pro = chroma.split("TEST_PRO{", 1)[1].split("\r\n}", 1)[0]
        routed_rows = tuple(line for line in test_pro.splitlines() if "#C(" in line)
        self.assertGreater(len(routed_rows), 1)
        self.assertTrue(all(
            re.search(r" // SBin=\d+$", line)
            for line in routed_rows
        ))
        self.assertEqual(len({line.index("// SBin=") for line in routed_rows}), 1)
        self.assertFalse(any("HBin=" in line for line in routed_rows))
        self.assertIn(" // SBin=9", next(
            line for line in routed_rows if "Hsi_8M_Trim" in line
        ))
        self.assertIn(" // SBin=250", next(
            line for line in routed_rows if "OTP_Read" in line
        ))
        self.assertIn(" // SBin=255", next(
            line for line in routed_rows if "last_item_test" in line
        ))

        _plan, s100 = self._source("s100")
        booking = s100.split("@@BOOKING", 1)[1].split("@@END_BOOKING", 1)[0]
        booked_rows = tuple(line for line in booking.splitlines() if ";" in line)
        self.assertGreater(len(booked_rows), 1)
        self.assertTrue(all(
            re.search(r" // SBin=\d+$", line)
            for line in booked_rows
        ))
        self.assertEqual(len({line.index("// SBin=") for line in booked_rows}), 1)
        self.assertFalse(any("HBin=" in line for line in booked_rows))
        self.assertRegex(booking, r"(?m)^\tHsi_8M_Trim; +// SBin=9\r?$")

    def test_system_read_blocks_explain_intent_and_expand_control_flow(self):
        _plan, s100 = self._source("s100")
        _plan, chroma = self._source("chroma")
        for source in (s100, chroma):
            self.assertIn("// System test: read OTP contents.", source)
            self.assertIn("// System test: dump nonvolatile memory data.", source)
        self.assertIn(
            "for(J=0;J<byte_count;J++)\r\n"
            "\t\t\t{\r\n"
            "\t\t\t\tmain_data[T_SOCKET][J]=0;",
            s100,
        )
        self.assertIn(
            "if(BIT[J]==0)\r\n"
            "        {\r\n"
            "          WRITE_PAT_MEM(",
            chroma,
        )

    def test_skeleton_sections_have_stable_intent_comments_and_multiline_control(self):
        _plan, chroma = self._source("chroma")
        _plan, s100 = self._source("s100")
        for source in (chroma, s100):
            self.assertIn("// Fixed Program Baseline", source)
            self.assertIn("// Voltage/Timing baseline", source)
            self.assertIn("// Session/Power baseline", source)
            self.assertIn("// Schedule", source)
        self.assertIn(
            "for(I=0;I<MAX_SITE;I++)\r\n"
            "  {\r\n"
            "    X_CO[I]=0;\r\n"
            "    Y_CO[I]=0;\r\n"
            "  }",
            chroma,
        )
        self.assertIn(
            "for(I=0;I<MAX_SITE;I++)\r\n"
            "\t{\r\n"
            "\t\tX_CO[I]=Sys_ProberX[I];\r\n"
            "\t\tY_CO[I]=Sys_ProberY[I];\r\n"
            "\t}",
            s100,
        )

    def test_version_token_is_compiled_from_version_program_name(self):
        self.assertEqual(
            _program_version_token(
                "V_PCD2509V1_PY32F420A_C8_30C_V00_50_24SS_CP1", "CP1"
            ),
            "V00_50",
        )
        for invalid in (
            "NO_VERSION_HERE",
            "XV00_50Y",
            "PROGRAM_V00_50_AND_V01_00_CP1",
        ):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                ValueError, "STN.VERSION.PROGRAM_NAME"
            ):
                _program_version_token(invalid, "CP1")

    def test_generated_programs_have_stable_flow_partitions(self):
        _plan, chroma = self._source("chroma")
        _plan, s100 = self._source("s100")
        self.assertLess(
            chroma.index("//           Sub Flow"),
            chroma.index("set_hsi_8m_trim_data"),
        )
        self.assertLess(
            chroma.index("set_hsi_8m_trim_data"),
            chroma.index("//           Main Flow"),
        )
        self.assertLess(
            chroma.index("//           Main Flow"), chroma.index("Hsi_8M_Trim()")
        )
        self.assertLess(
            chroma.index("Hsi_8M_Dac_Loop()"),
            chroma.index("//           Debug Flow"),
        )
        self.assertLess(
            chroma.index("//           Debug Flow"), chroma.index("OTP_Read()")
        )
        self.assertLess(
            s100.index("//           Sub Flow"),
            s100.index("@@MACRO set_hsi_8m_trim_data"),
        )
        self.assertLess(
            s100.index("@@MACRO set_hsi_8m_trim_data"),
            s100.index("//           Main Flow"),
        )
        self.assertLess(
            s100.index("//           Main Flow"), s100.index("@@PLAN Hsi_8M_Trim")
        )
        self.assertLess(
            s100.index("@@PLAN Hsi_8M_Dac_Loop"),
            s100.index("//           Debug Flow"),
        )
        self.assertLess(
            s100.index("//           Debug Flow"), s100.index("@@PLAN OTP_Read")
        )

    def test_only_global_definitions_receive_assignment_spacing(self):
        sources = {
            platform: self._source(platform)[1]
            for platform in ("chroma", "s100")
        }
        for platform, source in sources.items():
            with self.subTest(platform=platform):
                self.assertIn("// V00_50 version", source)
                for line_number, line in enumerate(source.splitlines(), 1):
                    self.assertEqual(
                        line.rstrip(" \t"), line,
                        msg=f"{platform}:{line_number}: trailing whitespace",
                    )
        for global_definition in (
            "GLOBAL int LIST_TEST_TIME = 0;",
            "VOLTAGE VCC_MIN = 2.7V;",
            "double VPOSE_TAR = 1.4;",
        ):
            self.assertIn(global_definition, sources["chroma"])
        for global_definition in (
            "double _C_VCC_MIN = 2.7;",
            "double _C_VPOSE_TAR = 1.4;",
            "bool VTEN_FLAG = false;",
        ):
            self.assertIn(global_definition, sources["s100"])
        for original_function_text in (
            "for(I=0;I<MAX_SITE;I++)",
            "X_CO[I]=0;",
            "TEST_NUM=2150;",
            "double trimTar=125;",
            'DATALOG_MSG="hsi_8m_trim";',
            "binAryCyc-=1;",
        ):
            self.assertIn(original_function_text, sources["chroma"])
        for original_function_text in (
            "blSoftwareBin=1;",
            "for(I=0;I<MAX_SITE;I++)",
            "X_CO[I]=Sys_ProberX[I];",
            "double trimTar=125;",
            "binAryCyc-=1;",
        ):
            self.assertIn(original_function_text, sources["s100"])
        self.assertIn("WAIT=1.0MS", sources["s100"])
        self.assertIn("DOWN_LIMIT=0", sources["s100"])
        self.assertIn("=!9", sources["chroma"])
        self.assertIn("// Typed runtime declarations", sources["chroma"])
        self.assertNotIn("// Trim DAC globals", sources["chroma"])
        self.assertIn("// Trim CSV globals", sources["s100"])
        hw_bin_lines = tuple(
            line for line in sources["chroma"].splitlines()
            if line.startswith("  hw_")
        )
        self.assertGreater(len(hw_bin_lines), 1)
        self.assertEqual(len({line.index("=!") for line in hw_bin_lines}), 1)
        self.assertIn(
            "\r\n\r\n  fail_last_item_test =!255;",
            sources["chroma"],
        )
        for level, voltage in (
            ("MIN_LVL", "VCC_MIN"),
            ("TYP_LVL", "VCC_TYP"),
            ("MAX_LVL", "VCC_MAX"),
        ):
            self.assertEqual(
                sources["chroma"].count(
                    f"SET_LEVELN({level},TP,0V,{voltage},0.3V,0.8V,"
                    f"0uA,0uA,{voltage}*0.5,,);"
                ),
                1,
            )

    def test_chroma_startup_preserves_visual_group_boundaries(self):
        _plan, source = self._source("chroma")
        boundaries = (
            ("  WAIT(20mS);", "  RATEN(TS1,FSCLK_TYP);"),
            ("FSCLK_TYP*0.5,FSCLK_TYP);", "  RATEN(TS2,FSCLK_500K);"),
            ("FSCLK_500K*0.5,FSCLK_500K);", "  RATEN(TS5,FSCLK_ERASE);"),
            ("FSCLK_ERASE*0.5,FSCLK_ERASE);", "  RATEN(TS6,FSCLK_PGM);"),
            ("FSCLK_PGM*0.5,FSCLK_PGM);", "  SET_LEVELN(MIN_LVL,IO_ALLPINS"),
            ("VCC_MIN*0.5,,);", "  SET_LEVELN(TYP_LVL,IO_ALLPINS"),
            ("VCC_TYP*0.5,,);", "  SET_LEVELN(MAX_LVL,IO_ALLPINS"),
            ("VCC_MAX*0.5,,);", '  LOAD_PAT("./PAT/pin_pat.ppo");'),
        )
        for before, after in boundaries:
            with self.subTest(before=before, after=after):
                self.assertIn(f"{before}\r\n\r\n{after}", source)

    def test_platform_globals_use_single_blank_line_semantic_groups(self):
        sources = {platform: self._source(platform)[1] for platform in ("chroma", "s100")}
        chroma_groups = (
            ("GLOBAL int LIST_TEST_TIME = 0;", "int BIT[64];"),
            ("int TRIM_DIGIT;", "int TEST_NUM;"),
            ("int X_CO[MAX_SITE],Y_CO[MAX_SITE];", "bool VTEN_FLAG = false;"),
            ("bool VTEN_FLAG = false;", "char BUFF_W_P"),
            ("char BUFF_W_P[32][2],BUFF_W_N[32][2],BUFF_R_P[32][2],BUFF_R_N[32][2];", "double VTE_Shift"),
            ("double VTE_Shift[MAX_SITE],VTP_Shift[MAX_SITE];", "int RST_LVL = 1;"),
            ("int MAX_LVL = 4;", "VOLTAGE VCC_MIN = 2.7V;"),
            ("VOLTAGE VCC_MAX = 5.5V;", "VOLTAGE VTE_VOLTAGE = -0.2V;"),
            ("VOLTAGE VTP_VOLTAGE = 0.45V;", "// Voltage/Timing baseline"),
            ("double VNEGP_TAR = -1.7;", "TIME FSCLK_TYP = 200nS;"),
            ("TIME FSCLK_PGM = 200nS;", "// Typed runtime declarations"),
        )
        s100_groups = (
            ("#define MAX_SITE 1", "int I,J,K;"),
            ("int T_SOCKET;", "int main_data[MAX_SITE][256];"),
            ("int main_data[MAX_SITE][256];", "double _C_VCC_MIN = 2.7;"),
            ("double _C_VTP_VOLTAGE = 0.45;", "// Voltage/Timing baseline"),
            ("double _C_VNEGP_TAR = -1.7;", "int X_CO[MAX_SITE],Y_CO[MAX_SITE];"),
            ("int X_CO[MAX_SITE],Y_CO[MAX_SITE];", "bool VTEN_FLAG = false;"),
            ("bool VTEN_FLAG = false;", "// Typed runtime declarations"),
            ("REG_VREFINT_VERIFY[MAX_SITE];", "// Addr Map page: factory23"),
            ("REG_REDRA_CFG7[MAX_SITE];", "// Trim CSV globals"),
        )
        for platform, groups in (("chroma", chroma_groups), ("s100", s100_groups)):
            with self.subTest(platform=platform):
                source = sources[platform]
                for before, after in groups:
                    self.assertIn(f"{before}\r\n\r\n{after}", source)
                self.assertNotIn("// Trim DAC globals", source)

    def test_chroma_globals_split_site_constants_and_timesets(self):
        source = self._source("chroma")[1]
        for before, after in (
            ("const int MAX_SITE = 1;", "GLOBAL int LIST_TEST_TIME = 0;"),
            ("TIME FSCLK_500K = 2000nS;", "TIME FSCLK_ERASE = 560nS;"),
        ):
            self.assertIn(f"{before}\r\n\r\n{after}", source)
            self.assertNotIn(f"{before}\r\n\r\n\r\n{after}", source)

    def test_standard_trim_support_keeps_only_targets_and_s100_csv_globals(self):
        spec = SimpleNamespace(
            dac_final_symbol="HSI_8M_DAC_FINAL",
            item="Hsi_8M",
            trim_tar_reference="VPOSE_TAR",
            measurement=SimpleNamespace(target=1.4),
        )
        for platform, target_line in (
            ("chroma", "VOLTAGE VPOSE_TAR = 1.4V;"),
            ("s100", "double _C_VPOSE_TAR = 1.4;"),
        ):
            with self.subTest(platform=platform):
                source = standard_trim_globals(platform, (spec,))
                self.assertIn(target_line, source)
                self.assertNotIn("// Trim DAC globals", source)
                if platform == "s100":
                    self.assertIn(
                        f"{target_line}\r\n\r\n// Trim CSV globals", source
                    )

    def test_generic_builder_and_new_renderers_do_not_read_workbook(self):
        root = Path(__file__).resolve().parents[1] / "program_gen"
        builder = (root / "platform_program" / "builder.py").read_text(encoding="utf-8")
        self.assertNotIn("standard_trim", builder)
        self.assertNotIn("system_tests", builder)
        for path in (
            root / "system_tests" / "function_blocks.py",
            root / "system_tests" / "contributions.py",
            root / "platform_program" / "chroma.py",
            root / "platform_program" / "s100.py",
        ):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("G.col", source, msg=path.name)
            self.assertNotIn("WorkbookReader", source, msg=path.name)
            self.assertNotIn("dataframe(", source, msg=path.name)


if __name__ == "__main__":
    unittest.main()
