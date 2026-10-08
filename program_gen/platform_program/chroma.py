"""Reusable Chroma skeleton and project-resource providers."""

from __future__ import annotations

from dataclasses import replace
import re

from program_gen.core.reindent import reindent_text
from program_gen.core.schedule_plan import BinBinding, BinBindingKind
from program_gen.render_plan import (
    ProgramContribution,
    ResourceRequest,
    SectionFragment,
)
from program_gen.pin_dec import (
    compile_pin_map_generation_plan,
    generate_pin_dec,
)
from program_gen.skeleton import SkeletonRender
from program_gen.platform_program.baseline import vt_coordinate_policy


CHROMA_REQUIRED_STRUCTURES = (
    "START_UP", "TEST_START", "TEST_PROGRAM", "TEST_END", "RELEASE"
)
CHROMA_DEBUG_BIN_NAME = "Debug"
CHROMA_DEBUG_BIN_NUMBER = "250"
CHROMA_DEBUG_TESTS = frozenset(("OTP_Read", "NM_Data_Read"))
CHROMA_SECTION_ORDER = (
    "PREAMBLE", "GLOBALS", "BINS", "SETUP", "SESSION", "POWER",
    "HELPERS", "TESTS", "SCHEDULE",
)


class ChromaSkeletonSyntax:
    platform = "chroma"

    def __init__(self, facts, schedule_entries, canonical_schedule=None) -> None:
        self._facts = facts
        self._entries = tuple(schedule_entries)
        schedule = canonical_schedule
        self._definitions = {
            item.identity: item
            for item in getattr(schedule, "definitions", ())
        }
        self._schedule_entries = tuple(getattr(schedule, "entries", ()))

    def normalize_bodies(self, bodies):
        """Normalize scheduled Chroma headers and body boundaries."""
        entries = {
            f"chroma:{entry.identity}".casefold(): entry
            for entry in self._entries
        }
        normalized = []
        for body in bodies:
            entry = entries.get(body.ref.semantic_key.casefold())
            if entry is None:
                raise ValueError(
                    f"PP.CHROMA.BODY.SCHEDULE_MISSING: {body.ref.identity!r}"
                )
            normalized.append(self._normalize_body(body, entry))
        return tuple(normalized)

    def _normalize_body(self, body, entry):
        source = body.fragment.content.decode("gbk")
        lines = source.replace("\r\n", "\n").split("\n")
        name = entry.render_name
        if len(lines) < 2 or lines[0] != f"{name}()" or lines[1].strip() != "{":
            raise ValueError(f"PP.CHROMA.BODY.SHAPE_INVALID: {name!r}")
        header_pattern = (
            r'\s*TEST_NO\s*\(\s*TEST_NUM\s*\)\s*;\s*'
            rf'DATALOG_MSG\s*=\s*"{re.escape(name)}"\s*;\s*'
        )
        prelude_end = min(len(lines), 14)
        has_header = any(
            re.fullmatch(header_pattern, line)
            for line in lines[2:prelude_end]
        )
        if not has_header:
            number_index = next((
                index
                for index in range(2, prelude_end)
                if re.fullmatch(r"\s*TEST_NUM\s*=\s*\d+\s*;\s*", lines[index])
            ), None)
            if number_index is None:
                definition = self._definitions.get(entry.definition_id)
                source_rows = tuple(getattr(definition, "source_rows", ()))
                if not source_rows:
                    raise ValueError(f"PP.CHROMA.BODY.TEST_NUMBER_MISSING: {name!r}")
                number_index = 2
                lines.insert(number_index, f"  TEST_NUM={(source_rows[0] - 1) * 100};")
            lines.insert(
                number_index + 1,
                f'  TEST_NO(TEST_NUM);DATALOG_MSG="{name}";',
            )
        while lines and not lines[-1].strip():
            lines.pop()
        content, final_depth = reindent_text(
            "\r\n".join(lines) + "\r\n\r\n", "  ", False
        )
        if final_depth:
            raise ValueError(
                f"PP.CHROMA.BODY.BRACE_UNCLOSED: {name!r} depth={final_depth}"
            )
        content = content.encode("gbk")
        return replace(body, fragment=replace(body.fragment, content=content))

    def render(self, plan) -> SkeletonRender:
        path = f"{plan.target.program_name}.pln"
        providers = (
            ("PREAMBLE", "preamble", self._preamble(), 0),
            ("GLOBALS", "globals", self._globals(), 0),
            ("BINS", "bins", self._bins(), 0),
            ("SETUP", "start-up", self._start_up(
                plan.lifecycle.actions_for("START_UP")
            ), 0),
            ("SESSION", "session", self._session(plan.lifecycle.actions_for("TEST_START")), 0),
            ("POWER", "power", self._power(), 0),
            ("HELPERS", "flow-sub", self._flow_header("Sub Flow"), -100),
            ("HELPERS", "fixed-runtime-helpers", self._fixed_helpers(), 1000),
            ("SCHEDULE", "test-program", self._test_program(), 0),
            ("TESTS", "flow-main", self._flow_header("Main Flow"), -100),
            ("TESTS", "flow-debug", self._flow_header("Debug Flow"), 99999),
        )
        return SkeletonRender(
            sections=tuple(
                SectionFragment(
                    path, section, f"skeleton:chroma:{identity}",
                content.encode("gbk"), order=section_order,
                )
                for section, identity, content, section_order in providers
            ),
            provides=plan.required_provisions,
        )

    def _preamble(self) -> str:
        return (
            "////////////////////////////////////////////////////////////////////////////////////////////////\r\n"
            "// UPDATE LOG\r\n"
            "// {version} version\r\n"
            "//\r\n"
            "////////////////////////////////////////////////////////////////////////////////////////////////\r\n\r\n"
        ).format(version=self._facts.program_version_token) + (
            "// Fixed Program Baseline\r\n"
            "#include <time.h>\r\n#include <math.h>\r\n#include <stdint.h>\r\n\r\n"
            'SET_DEC_FILE ".\\PAT\\pin.dec"\r\n\r\n'
        )

    def _flow_header(self, name: str) -> str:
        border = "//////////////////////////////////////////////////////////////////\r\n"
        return border + "//\r\n//           " + name + "\r\n//\r\n" + border + "\r\n"


    def _globals(self) -> str:
        f = self._facts
        groups = [
            "// Fixed Program Baseline\r\n"
            f"const int MAX_SITE = {f.site_count};",
            "GLOBAL int LIST_TEST_TIME = 0;",
            "int BIT[64];\r\nint I,J,K;\r\nuint32_t TEMP;\r\nint TRIM_DIGIT;",
            "int TEST_NUM;\r\nint X_CO[MAX_SITE],Y_CO[MAX_SITE];",
            "bool VTEN_FLAG = false;",
            "char BUFF_W_P[32][2],BUFF_W_N[32][2],BUFF_R_P[32][2],BUFF_R_N[32][2];",
            "double VTE_Shift[MAX_SITE],VTP_Shift[MAX_SITE];",
            "int RST_LVL = 1;\r\nint MIN_LVL = 2;\r\nint TYP_LVL = 3;\r\nint MAX_LVL = 4;",
            f"VOLTAGE VCC_MIN = {f.vcc_min}V;\r\n"
            f"VOLTAGE VCC_TYP = {f.vcc_typ}V;\r\n"
            f"VOLTAGE VCC_MAX = {f.vcc_max}V;",
        ]
        vt_lines = tuple(
            f"VOLTAGE {name} = {value}V;"
            for name, value in (
                ("VTE_VOLTAGE", f.vte_voltage),
                ("VTP_VOLTAGE", f.vtp_voltage),
            )
            if value is not None
        )
        if vt_lines:
            groups.append("\r\n".join(vt_lines))
        target_lines = tuple(
            f"double {name} = {value};"
            for name, value in (
                ("VPOSE_TAR", f.vpose_target),
                ("VNEGE_TAR", f.vnege_target),
                ("VPOSP_TAR", f.vposp_target),
                ("VNEGP_TAR", f.vnegp_target),
            )
            if value is not None
        )
        target_group = "// Voltage/Timing baseline"
        if target_lines:
            target_group += "\r\n" + "\r\n".join(target_lines)
        groups.extend((
            target_group,
            "TIME FSCLK_TYP = 200nS;\r\nTIME FSCLK_500K = 2000nS;",
            f"TIME FSCLK_ERASE = {_erase_period_ns(f)}nS;\r\n"
            f"TIME FSCLK_PGM = {_program_period_ns(f)}nS;",
        ))
        return "\r\n\r\n".join(groups) + "\r\n\r\n"

    def _bins(self) -> str:
        rows = []
        seen = set()
        for entry in self._entries:
            name, binding = self._routing(entry)
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            rows.append((
                name,
                str(binding.hardware_bin),
                str(binding.software_bin),
            ))
        width = max((len(f"hw_{name}") for name, _hw, _sw in rows), default=0)
        hw = "\r\n".join(
            f"  hw_{name:<{width - 3}} =!{number};"
            for name, number, _software_bin in rows
        )
        sw = "\r\n".join(
            f"  sw_{name:<{width - 3}} =!{number};"
            for name, _hardware_bin, number in rows
        )
        return (
            "// Schedule bin routing\r\n"
            "HW_BIN_DEF\r\n{\r\n  all_pass = 1;\r\n"
            + hw + "\r\n\r\n  fail_last_item_test =!255;\r\n}\r\n\r\n"
            "SW_BIN_DEF\r\n{\r\n  all_pass = 1;\r\n"
            + sw + "\r\n\r\n  fail_last_item_test =!255;\r\n}\r\n\r\n"
        )

    def _start_up(self, actions) -> str:
        f = self._facts
        clk = f.clk_pin
        contributed = "".join(action.content for action in actions)
        return (
            "// Voltage/Timing baseline\r\n"
            "START_UP()\r\n{\r\n"
            "  SET_LEVELN(RST_LVL,IO_ALLPINS,0V,0V,0V,0V,0mA,0mA,0V,,);\r\n"
            "  LEVELS(RST_LVL,3mS);\r\n  WAIT(20mS);\r\n\r\n"
            "  RATEN(TS1,FSCLK_TYP);\r\n"
            "  MARKERN(TS1,IO_ALLPINS,0nS,0nS,,0nS,0nS,FSCLK_TYP*0.5,FSCLK_TYP);\r\n"
            f"  MARKERN(TS1,{clk},FSCLK_TYP*0.25,FSCLK_TYP*0.75,,0nS,0nS,FSCLK_TYP*0.5,FSCLK_TYP);\r\n\r\n"
            "  RATEN(TS2,FSCLK_500K);\r\n"
            "  MARKERN(TS2,IO_ALLPINS,0nS,0nS,,0nS,0nS,FSCLK_500K*0.5,FSCLK_500K);\r\n"
            f"  MARKERN(TS2,{clk},FSCLK_500K*0.25,FSCLK_500K*0.75,,0nS,0nS,FSCLK_500K*0.5,FSCLK_500K);\r\n\r\n"
            "  RATEN(TS5,FSCLK_ERASE);\r\n"
            "  MARKERN(TS5,IO_ALLPINS,0nS,0nS,,0nS,0nS,FSCLK_ERASE*0.5,FSCLK_ERASE);\r\n"
            f"  MARKERN(TS5,{clk},FSCLK_ERASE*0.25,FSCLK_ERASE*0.75,,0nS,0nS,FSCLK_ERASE*0.5,FSCLK_ERASE);\r\n\r\n"
            "  RATEN(TS6,FSCLK_PGM);\r\n"
            "  MARKERN(TS6,IO_ALLPINS,0nS,0nS,,0nS,0nS,FSCLK_PGM*0.5,FSCLK_PGM);\r\n"
            f"  MARKERN(TS6,{clk},FSCLK_PGM*0.25,FSCLK_PGM*0.75,,0nS,0nS,FSCLK_PGM*0.5,FSCLK_PGM);\r\n\r\n"
            "  SET_LEVELN(MIN_LVL,IO_ALLPINS,0V,VCC_MIN,VCC_MIN*0.45,VCC_MIN*0.55,0uA,0uA,VCC_MIN*0.5,,);\r\n"
            "  SET_LEVELN(MIN_LVL,TP,0V,VCC_MIN,0.3V,0.8V,0uA,0uA,VCC_MIN*0.5,,);\r\n\r\n"
            "  SET_LEVELN(TYP_LVL,IO_ALLPINS,0V,VCC_TYP,VCC_TYP*0.45,VCC_TYP*0.55,0uA,0uA,VCC_TYP*0.5,,);\r\n"
            "  SET_LEVELN(TYP_LVL,TP,0V,VCC_TYP,0.3V,0.8V,0uA,0uA,VCC_TYP*0.5,,);\r\n\r\n"
            "  SET_LEVELN(MAX_LVL,IO_ALLPINS,0V,VCC_MAX,VCC_MAX*0.45,VCC_MAX*0.55,0uA,0uA,VCC_MAX*0.5,,);\r\n"
            "  SET_LEVELN(MAX_LVL,TP,0V,VCC_MAX,0.3V,0.8V,0uA,0uA,VCC_MAX*0.5,,);\r\n\r\n"
            + contributed
            +
            '  LOAD_PAT("./PAT/pin_pat.ppo");\r\n}\r\n\r\n'
        )

    def _session(self, actions=()) -> str:
        p = vt_coordinate_policy(self._facts.cp)
        return (
            "// Session/Power baseline\r\n"
            "test_start()\r\n{\r\n"
            "  for(I=0;I<MAX_SITE;I++)\r\n  {\r\n"
            "    X_CO[I]=0;\r\n    Y_CO[I]=0;\r\n  }\r\n"
            "  READ_PROBER_XY(X_CO,Y_CO);\r\n"
            f"  if((Y_CO[MAX_SITE-1]>{p.y_min_exclusive}&&Y_CO[MAX_SITE-1]<{p.y_max_exclusive})&&X_CO[0]<{p.left_x_max_exclusive})\r\n  {{\r\n    VTEN_FLAG=true;\r\n  }}\r\n"
            f"  else if((Y_CO[0]>{p.y_min_exclusive}&&Y_CO[0]<{p.y_max_exclusive})&&X_CO[0]>{p.right_x_min_exclusive})\r\n  {{\r\n    VTEN_FLAG=true;\r\n  }}\r\n"
            "  else\r\n  {\r\n    VTEN_FLAG=false;\r\n  }\r\n"
            "  SHOW_TEST_TIME(LIST_TEST_TIME);\r\n"
            + "".join(action.content for action in actions) + "}\r\n\r\n"
        )

    @staticmethod
    def _fixed_helpers() -> str:
        return (
            "// Fixed Program Baseline helper\r\n"
            "void convert_to_string(unsigned int value,int bits,char out0[][2],char out1[][2],char out2[][2],char out3[][2])\r\n"
            "{\r\n  if(bits<0||bits>32)return;\r\n"
            "  unsigned int mask=(bits==32)?0xFFFFFFFFu:((1u<<bits)-1);\r\n"
            "  value&=mask;\r\n  for(I=bits-1;I>=0;I--)\r\n  {\r\n"
            "    unsigned int bit=(value>>I)&1u;int pos=bits-1-I;\r\n"
            "    out0[pos][0]=bit?'1':'0';out0[pos][1]='\\0';\r\n"
            "    out1[pos][0]=bit?'0':'1';out1[pos][1]='\\0';\r\n"
            "    out2[pos][0]=bit?'H':'L';out2[pos][1]='\\0';\r\n"
            "    out3[pos][0]=bit?'L':'H';out3[pos][1]='\\0';\r\n"
            "  }\r\n}\r\n\r\n"
        )

    def _power(self) -> str:
        rail = "+".join(self._facts.force_rails)
        kp_on = "  SET_CBIT(KP,ON,2mS);\r\n" if self._facts.kp_channel else ""
        kp_off = "  SET_CBIT(KP,OFF,2mS);\r\n" if self._facts.kp_channel else ""
        off = (
            "  LEVELS(RST_LVL,3mS);\r\n"
            "  PIN_MODE(IO_ALLPINS,NRZ,EDGE,ENABLE,IO_NRZ,OFF);\r\n"
            f"  FORCE_V_MLDPS({rail},0V,@6V,@500mA,200mA,,ON,2mS);\r\n"
            "  WAIT(5mS);\r\n"
            f"  FORCE_V_MLDPS({rail},0V,@6V,@500mA,200mA,,OFF,2mS);\r\n"
            "  RELAY_OFF(IO_ALLPINS,PDCL,2mS);\r\n"
        )
        return (
            "// Session/Power baseline\r\n"
            "test_end()\r\n{\r\n" + off + "}\r\n\r\n"
            "RELEASE()\r\n{\r\n" + off + "}\r\n\r\n"
            "POWER_ON(double vccVolt)\r\n{\r\n" + kp_on +
            "  RELAY_ON(IO_ALLPINS,PDCL,2mS);\r\n"
            f"  FORCE_V_MLDPS({rail},vccVolt,@6V,@500mA,200mA,NORM,ON,2mS);\r\n"
            "  PIN_MODE(IO_ALLPINS,NRZ,EDGE,ENABLE,IO_NRZ,OFF);\r\n"
            f"  PIN_MODE({self._facts.clk_pin},RZ,EDGE,ENABLE,IO_NRZ,OFF);\r\n"
            "  if(vccVolt==VCC_MIN)\r\n  {\r\n    LEVELS(MIN_LVL,3mS);\r\n  }\r\n"
            "  else if(vccVolt==VCC_MAX)\r\n  {\r\n    LEVELS(MAX_LVL,3mS);\r\n  }\r\n"
            "  else\r\n  {\r\n    LEVELS(TYP_LVL,3mS);\r\n  }\r\n"
            "  WAIT(10mS);\r\n}\r\n\r\n"
            "POWER_OFF()\r\n{\r\n" + off + kp_off + "}\r\n\r\n"
        )

    def _test_program(self) -> str:
        lines = [
            "// Schedule", "", "last_item_test()", "{", "  TEST_NUM++;",
            '  TEST_NO(TEST_NUM);DATALOG_MSG="last_item_test";',
            '  printf(\"last item test finished !!\");',
            "}", "", "TEST_PRO{", "  BEFORE_TEST: test_start;",
        ]
        routed_rows = []
        for entry in self._entries:
            name = entry.render_name
            prefix = "" if entry.enabled else "//"
            display = prefix + name
            base, binding = self._routing(entry)
            routed_rows.append((
                f"  {display:<34}?{'':23}: #C(hw_{base:<35},sw_{base:<35});",
                binding.software_bin,
            ))
        routed_rows.append((
            "  last_item_test                    ?#C(all_pass,all_pass)  : "
            "#C(fail_last_item_test                   ,fail_last_item_test                   );",
            "255",
        ))
        comment_column = max(len(line) for line, _bin in routed_rows) + 2
        lines.extend(f"{line:<{comment_column}}// SBin={sbin}" for line, sbin in routed_rows)
        lines.extend((
            "  AFTER_TEST: test_end;", "}", "",
        ))
        return "\r\n".join(lines)

    def _routing(self, entry):
        if entry.render_name in CHROMA_DEBUG_TESTS:
            return CHROMA_DEBUG_BIN_NAME, BinBinding(
                kind=BinBindingKind.DIRECT,
                hardware_bin=CHROMA_DEBUG_BIN_NUMBER,
                software_bin=CHROMA_DEBUG_BIN_NUMBER,
            )
        binding = entry.bin_binding
        if getattr(binding.kind, "value", binding.kind) == "DIRECT":
            definition = self._definitions.get(entry.definition_id)
            name = (
                definition.render_name if definition is not None
                else _base_name(entry.render_name)
            )
            return name, binding
        if getattr(binding.kind, "value", binding.kind) != "DEFINITION_REFERENCE":
            raise ValueError(f"unsupported canonical bin binding: {binding.kind!r}")
        definition = self._definitions[binding.definition_id]
        candidates = tuple(
            candidate for candidate in self._schedule_entries
            if candidate.definition_id == definition.identity
            and getattr(candidate.bin_binding.kind, "value", candidate.bin_binding.kind)
            == "DIRECT"
        )
        if len(candidates) != 1:
            raise ValueError(
                f"PP.CHROMA.BIN_SOURCE: {definition.identity!r} has {len(candidates)} direct entries"
            )
        return definition.render_name, candidates[0].bin_binding


def project_contribution(target, facts) -> ProgramContribution:
    dec = generate_pin_dec(compile_pin_map_generation_plan(facts))
    resources = [ResourceRequest(
        "project:chroma:pin-dec", "pat/pin.dec", dec,
        "v14.chroma.pin-dec/1", f"workbook-pin-dec:{target.cp}:{target.variant}",
        "Chroma native pin map",
    )]
    return ProgramContribution(
        identity=f"native-project:chroma:{target.identity}",
        target=target,
        resources=tuple(resources),
    )


def _base_name(name: str) -> str:
    return name.replace("_Dac_Loop", "_Trim")


def _erase_period_ns(facts) -> int:
    return int(facts.erase_time_ms * 1_000_000 / 12_500 + 0.5)


def _program_period_ns(facts) -> int:
    return int(facts.program_time_ms * 1_000_000 / 7_500 + 0.5)


__all__ = [
    "CHROMA_REQUIRED_STRUCTURES", "CHROMA_SECTION_ORDER", "ChromaSkeletonSyntax",
    "project_contribution",
]
