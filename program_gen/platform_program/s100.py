"""Reusable S100 skeleton and project-resource providers."""

from __future__ import annotations

from dataclasses import replace

from program_gen.core.schedule_plan import BinBindingKind
from program_gen.render_plan import (
    ProgramContribution,
    ResourceRequest,
    SectionFragment,
)
from program_gen.pin_dec import (
    compile_pin_map_generation_plan,
    generate_s100_prj_resources,
)
from program_gen.skeleton import SkeletonRender
from program_gen.platform_program.baseline import vt_coordinate_policy


S100_REQUIRED_STRUCTURES = ("START_UP", "TEST_START", "TEST_PROGRAM")
S100_SECTION_ORDER = (
    "PREAMBLE", "GLOBALS", "UNBOOKING", "SETUP", "SESSION", "POWER",
    "HELPERS", "TESTS", "BOOKING",
)


class S100SkeletonSyntax:
    platform = "s100"

    def __init__(self, facts, canonical_entries) -> None:
        self._facts = facts
        self._entries = tuple(canonical_entries)

    def normalize_bodies(self, bodies):
        """Separate every scheduled test body with one blank line."""
        return tuple(
            replace(body, fragment=replace(
                body.fragment,
                content=body.fragment.content.rstrip(b"\r\n") + b"\r\n\r\n",
            ))
            for body in bodies
        )

    def render(self, plan) -> SkeletonRender:
        path = f"{plan.target.program_name}.prg"
        providers = (
            ("PREAMBLE", "preamble", self._preamble(), 0),
            ("GLOBALS", "globals", self._globals(), 0),
            ("UNBOOKING", "unbooking", self._unbooking(), 0),
            ("SETUP", "start-up", self._startup(
                plan.lifecycle.actions_for("START_UP")
            ), 0),
            ("SESSION", "session", self._session(plan.lifecycle.actions_for("TEST_START")), 0),
            ("POWER", "power", self._power(), 0),
            ("HELPERS", "flow-sub", self._flow_header("Sub Flow"), -100),
            ("TESTS", "flow-main", self._flow_header("Main Flow"), -100),
            ("TESTS", "flow-debug", self._flow_header("Debug Flow"), 99999),
            ("BOOKING", "booking", self._booking(), 0),
        )
        return SkeletonRender(
            sections=tuple(SectionFragment(
                path, section, f"skeleton:s100:{identity}",
                content.encode("gbk"), order=order,
            ) for section, identity, content, order in providers),
            provides=plan.required_provisions,
        )

    def _preamble(self) -> str:
        return ("////////////////////////////////////////////////////////////////////////////////////////////////\r\n"
                "// UPDATE LOG\r\n// {version} version\r\n//\r\n"
                "////////////////////////////////////////////////////////////////////////////////////////////////\r\n\r\n"
                "// Fixed Program Baseline\r\n#include <time.h>\r\n#include <math.h>\r\n#include <stdint.h>\r\n\r\n").format(version=self._facts.program_version_token)

    def _globals(self) -> str:
        f = self._facts
        groups = [
            "// Fixed Program Baseline\r\n"
            f"#define MAX_SITE {f.site_count}",
            "int I,J,K;\r\nint T_SOCKET;",
            f"int main_data[MAX_SITE][{f.page_bytes}];",
            f"double _C_VCC_MIN = {f.vcc_min};\r\n"
            f"double _C_VCC_TYP = {f.vcc_typ};\r\n"
            f"double _C_VCC_MAX = {f.vcc_max};",
        ]
        vt_lines = tuple(
            f"double _C_{name} = {value};"
            for name, value in (
                ("VTE_VOLTAGE", f.vte_voltage),
                ("VTP_VOLTAGE", f.vtp_voltage),
            )
            if value is not None
        )
        if vt_lines:
            groups.append("\r\n".join(vt_lines))
        target_lines = tuple(
            f"double _C_{name} = {value};"
            for name, value in (
                ("VPOSE_TAR", f.vpose_target),
                ("VNEGE_TAR", f.vnege_target),
                ("VPOSP_TAR", f.vposp_target),
                ("VNEGP_TAR", f.vnegp_target),
            )
            if value is not None
        )
        if target_lines:
            groups.append(
                "// Voltage/Timing baseline\r\n" + "\r\n".join(target_lines)
            )
        groups.extend((
            "int X_CO[MAX_SITE],Y_CO[MAX_SITE];",
            "bool VTEN_FLAG = false;",
        ))
        return "\r\n\r\n".join(groups) + "\r\n\r\n"

    @staticmethod
    def _flow_header(name: str) -> str:
        border = "//////////////////////////////////////////////////////////////////\r\n"
        return border + "//\r\n//           " + name + "\r\n//\r\n" + border + "\r\n"


    def _unbooking(self) -> str:
        lines = ["// Schedule\r\n@@UNBOOKING"]
        for entry in self._entries:
            if entry.placement != "SYSTEM_UNBOOKED":
                continue
            prefix = "" if entry.enabled else "//"
            lines.append(f"\t{prefix}{entry.render_name};")
        lines.extend(("@@END_UNBOOKING", ""))
        return "\r\n".join(lines)

    def _booking(self) -> str:
        lines = ["// Schedule\r\n@@BOOKING"]
        booked_rows = []
        for entry in self._entries:
            if entry.placement != "BOOKED":
                continue
            binding = entry.bin_binding
            if binding.kind is not BinBindingKind.DIRECT:
                raise ValueError(f"PP.S100.BIN_SOURCE: {entry.identity!r} is not direct")
            prefix = "" if entry.enabled else "//"
            booked_rows.append((f"\t{prefix}{entry.render_name};", binding.software_bin))
        comment_column = max((len(line) for line, _bin in booked_rows), default=0) + 2
        lines.extend(f"{line:<{comment_column}}// SBin={sbin}" for line, sbin in booked_rows)
        lines.extend(("@@END_BOOKING", ""))
        return "\r\n".join(lines)

    @staticmethod
    def _startup(actions) -> str:
        contributed = "".join(action.content for action in actions)
        return (
            "// Voltage/Timing baseline\r\n"
            "@@START_UP\r\n"
            "\tIO_SET_DUT_BOARD_POWER(ON,5V_USER_POWER);\r\n"
            "\tWAIT(3ms);\r\n"
            "\tblSoftwareBin=1;\r\n"
            "\tLOGIC_SET_DRV_LEVEL(IO_ALLPINS,0.0V,0.0V,0.0V,VR1);\r\n"
            "\tLOGIC_SET_CMP_LEVEL(IO_ALLPINS,0.0V,0.0V,VR2);\r\n"
            "\tWAIT(20MS);\r\n"
            + contributed
            +
            "@@END_START_UP\r\n\r\n"
        )

    def _power(self) -> str:
        rails = self._facts.force_rails
        on = []
        off = []
        for rail in rails:
            on.extend((
                f"  LOGIC_CLOSE_DPS_OUTPUT_RELAY({rail},ON,WAIT=1.0MS);",
                f"  LOGIC_FORCE_DPS({rail},_C_vccVolt,200MA,I7,WAIT=0.5MS);",
            ))
            off.extend((
                f"  LOGIC_FORCE_DPS({rail},0.0V,200MA,I7,WAIT=0.5MS);",
                f"  LOGIC_CLOSE_DPS_OUTPUT_RELAY({rail},OFF,WAIT=0.5MS);",
            ))
        return (
            "// Session/Power baseline\r\n"
            "@@MACRO POWER_ON(double _C_vccVolt)\r\n"
            + "\r\n".join(on)
            + "\r\n  LOGIC_CLOSE_PE_RELAY(IO_ALLPINS,WAIT=3MS);\r\n"
            "  LOGIC_SET_DRV_LEVEL(IO_ALLPINS,_C_vccVolt,0.0V,0.0V,VR1);\r\n"
            "  LOGIC_SET_CMP_LEVEL(IO_ALLPINS,_C_vccVolt*0.55,_C_vccVolt*0.45,VR1);\r\n"
            "  LOGIC_SET_DRV_LEVEL(TP,_C_vccVolt,0.0V,0.0V,VR1);\r\n"
            "  LOGIC_SET_CMP_LEVEL(TP,0.8,0.3,VR1);\r\n@@END_MACRO\r\n\r\n"
            "@@MACRO POWER_OFF()\r\n"
            "  LOGIC_SET_DRV_LEVEL(IO_ALLPINS,0.0V,0.0V,0.0V,VR1);\r\n"
            "  LOGIC_SET_CMP_LEVEL(IO_ALLPINS,0.0V,0.0V,VR1);\r\n"
            "  LOGIC_CLOSE_PE_RELAY(NULL,WAIT=3MS);\r\n"
            + "\r\n".join(off)
            + "\r\n@@END_MACRO\r\n\r\n"
        )

    def _session(self, actions=()) -> str:
        p = vt_coordinate_policy(self._facts.cp)
        return (
            "// Session/Power baseline\r\n"
            "@@MACRO Clear_GB()\r\n"
            "  for(I=0;I<64;I++)\r\n  {\r\n"
            "    for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\r\n"
            "    {\r\n"
            "      GB[I+T_SOCKET*64]=0;\r\n"
            "    }\r\n"
            "  }\r\n@@END_MACRO\r\n\r\n"
            "@@MACRO write_pat_temp_arry(int* a)\r\n"
            "  for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\r\n"
            "  {\r\n"
            "    if(Sys_ActiveSite[T_SOCKET]==0)continue;\r\n"
            "    GB[0+T_SOCKET*64]=a[T_SOCKET];\r\n"
            "  }\r\n@@END_MACRO\r\n\r\n"
            # YT5100 emits macro prototypes before stdint.h is included.
            "@@MACRO write_pat_temp_long(unsigned int* a)\r\n"
            "  for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\r\n"
            "  {\r\n"
            "    if(Sys_ActiveSite[T_SOCKET]==0)continue;\r\n"
            "    GB[0+T_SOCKET*64]=a[T_SOCKET];\r\n"
            "  }\r\n@@END_MACRO\r\n\r\n"
            "@@MACRO write_pat_temp_fixed(unsigned int a)\r\n"
            "  for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\r\n"
            "  {\r\n"
            "    if(Sys_ActiveSite[T_SOCKET]==0)continue;\r\n"
            "    GB[0+T_SOCKET*64]=a;\r\n"
            "  }\r\n@@END_MACRO\r\n\r\n"
            "@@MACRO Bitwise_not_arry(int* a)\r\n"
            "  for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\r\n"
            "  {\r\n"
            "    if(Sys_ActiveSite[T_SOCKET]==0)continue;\r\n"
            "    GB[0+T_SOCKET*64]=a[T_SOCKET]^0xFFFF;\r\n"
            "  }\r\n@@END_MACRO\r\n\r\n"
            "@@MACRO test_start()\r\n  CALL_MACRO Clear_GB();\r\n"
            "  for(I=0;I<MAX_SITE;I++)\r\n  {\r\n"
            "    X_CO[I]=Sys_ProberX[I];\r\n    Y_CO[I]=Sys_ProberY[I];\r\n  }\r\n"
            f"  if((Y_CO[MAX_SITE-1]>{p.y_min_exclusive}&&Y_CO[MAX_SITE-1]<{p.y_max_exclusive})&&X_CO[0]<{p.left_x_max_exclusive})\r\n  {{\r\n    VTEN_FLAG=true;\r\n  }}\r\n"
            f"  else if((Y_CO[0]>{p.y_min_exclusive}&&Y_CO[0]<{p.y_max_exclusive})&&X_CO[0]>{p.right_x_min_exclusive})\r\n  {{\r\n    VTEN_FLAG=true;\r\n  }}\r\n"
            "  else\r\n  {\r\n    VTEN_FLAG=false;\r\n  }\r\n"
            + "".join(action.content for action in actions) + "@@END_MACRO\r\n\r\n"
        )


def project_contribution(target, facts, pattern_names, bins, timing_sets, timing_fragments=()) -> ProgramContribution:
    name = target.program_name
    resources = (
        _resource("project:s100:prj", f"{name}.prj", _prj(name, facts, pattern_names, bins), target),
        _resource("project:s100:hed", f"{name}.hed", _hed(facts), target),
        _resource("project:s100:tim", f"{name}.tim", _tim(facts, timing_sets, timing_fragments), target),
    )
    return ProgramContribution(
        identity=f"native-project:s100:{target.identity}", target=target,
        resources=resources,
    )


def _resource(identity, path, text, target):
    return ResourceRequest(
        identity, path, text.encode("gbk"), f"v14.s100.{path.rsplit('.',1)[-1]}/1",
        f"typed-profile:{target.cp}:{target.variant}", "S100 native project resource",
    )


def _prj(name, facts, pattern_names, bins) -> str:
    patterns = ",\r\n                    ".join(
        item if item.casefold().endswith(".sr") else f"{item}.sd"
        for item in pattern_names
    )
    pin_resources = generate_s100_prj_resources(
        compile_pin_map_generation_plan(facts)
    ).decode("gbk")
    bin_rows = []
    for number in sorted({1, *(int(value) for value in bins)}):
        bin_rows.append(f"   {number},{number},{1 if number == 1 else 0},{0 if number == 1 else 1};")
    return (
        "@@START_UP_TABLE\r\n"
        f"   TEST_DIE      = {facts.site_count};\r\n"
        "   APG_NAME      = NULL;\r\n"
        f"   PATTERN_NAME  = {patterns};\r\n"
        f"   PROGRAM_NAME  = {name}.prg;\r\n"
        f"   PATTERN_HEAD  = {name}.hed;\r\n"
        f"   TIMING_NAME   = {name}.tim;\r\n"
        "   SYSTEM_CLK    = 200Mhz;\r\n"
        "   TESTER_TYPE   = 7D;\r\n"
        "   BIN_MAP_TABLE = NEW_HARDWARE_BIN_STYLE;\r\n"
        "@@END_START_UP_TABLE\r\n\r\n"
        + pin_resources
        + "@@BIN_MAP\r\n" + "\r\n".join(bin_rows)
        + "\r\n@@END_BIN_MAP\r\n\r\n"
        + "@@SOFTWARE_BIN_GOOD_DVC\r\n   GOOD1=1;\r\n"
        + "@@END_SOFTWARE_BIN_GOOD_DVC\r\n"
    )


def _hed(facts) -> str:
    return "HEAD[PIN_NAME]:\r\n\t" + ",\r\n\t".join((*facts.io_pins, "TRIGPIN")) + ",\r\nEND_HEAD;\r\n"


def _tim(facts, timing_sets, timing_fragments=()) -> str:
    sets = [
        _ac_set(1, "TS_5MHZ", 200, facts.clk_pin),
        _ac_set(2, "TS_500K", 2000, facts.clk_pin),
        _ac_set(
            4, "TS_erase",
            int(facts.erase_time_ms * 1_000_000 / 12_500 + 0.5),
            facts.clk_pin,
        ),
        _ac_set(
            5, "TS_pgm",
            int(facts.program_time_ms * 1_000_000 / 7_500 + 0.5),
            facts.clk_pin,
        ),
        _ac_set(6, "VIH_5MHZ", 200, None),
    ]
    consumed = set(timing_sets)
    unknown = consumed - {"G1_1", "G1_2", "G1_4", "G1_5", "G3_1"}
    if unknown:
        raise ValueError(f"STN.S100.TIMING_SET_UNSUPPORTED: {sorted(unknown)!r}")
    scan_timing = _scan_timing(timing_fragments)
    return (
        "@@TIMING_DEFINE\r\n\t@@GROUP_1\r\n"
        + "\r\n".join(sets)
        + "\r\n\t@@END_GROUP_1\r\n"
        + (_force_clock_group() if "G3_1" in consumed else "")
        + scan_timing
        + "@@END_TIMING_DEFINE\r\n"
    )


def _scan_timing(fragments) -> str:
    content = []
    identities = set()
    for fragment in fragments:
        identity = str(fragment.logical_identity).casefold()
        if identity in identities:
            raise ValueError(f"STN.S100.SCAN_TIMING_DUPLICATE: {fragment.logical_identity}")
        identities.add(identity)
        text = bytes(fragment.content).decode("utf-8", errors="strict").replace("\r\n", "\n").strip()
        if not text.startswith("@@AC_SET_") or "@@TIMING_DEFINE" in text or "@@GROUP_" in text:
            raise ValueError(f"STN.S100.SCAN_TIMING_INVALID: {fragment.logical_identity}")
        content.append(text.replace("\n", "\r\n"))
    return "" if not content else "\t@@GROUP_2\r\n" + "\r\n".join(content) + "\r\n\t@@END_GROUP_2\r\n"


def _force_clock_group() -> str:
    return (
        "\t@@GROUP_3\r\n\t\t@@AC_SET_1\r\n"
        "\t\t\t[NAME=TS_FORCE_CLK]\r\n\t\t\t[TS ReserveEdges=14]\r\n"
        "\t\t\t\tPERIOD    = 30518;\r\n"
        "\t\t\t\tIO_ALLPINS: {DRV_RS=1525}\r\n"
        "\t\t\t\t            {DRV_FL=22888}\r\n"
        "\t\t\t\t            {STB_RS=15259}\r\n"
        "\t\t\t[END_TS]\r\n\t\t\t[FMT]\r\n"
        "\t\t\t\tIO_ALLPINS: {DRV_FMT=NF}\r\n"
        "\t\t\t[END_FMT]\r\n\t\t@@END_AC_SET_1\r\n"
        "\t@@END_GROUP_3\r\n"
    )


def _ac_set(index: int, name: str, period: int, clk_pin: str | None) -> str:
    clock_edges = "" if clk_pin is None else (
        f"\t\t\t\t{clk_pin}: {{DRV_RS={int(period * 0.25)}}}\r\n"
        f"\t\t\t\t      {{DRV_FL={int(period * 0.75)}}}\r\n"
        f"\t\t\t\t      {{STB_RS={int(period * 0.5)}}}\r\n"
    )
    clock_format = "" if clk_pin is None else (
        f"\t\t\t\t{clk_pin}: {{DRV_FMT=RZ}}\r\n"
    )
    return (
        f"\t\t@@AC_SET_{index}\r\n"
        f"\t\t\t[NAME={name}]\r\n\t\t\t[TS ReserveEdges=14]\r\n"
        f"\t\t\t\tPERIOD    = {period};\r\n"
        f"\t\t\t\tIO_ALLPINS: {{DRV_RS={int(period * 0.05)}}}\r\n"
        f"\t\t\t\t            {{DRV_FL={int(period * 0.75)}}}\r\n"
        f"\t\t\t\t            {{STB_RS={int(period * 0.5)}}}\r\n"
        + clock_edges
        + "\t\t\t[END_TS]\r\n\t\t\t[FMT]\r\n"
        "\t\t\t\tIO_ALLPINS: {DRV_FMT=NF}\r\n"
        + clock_format
        + f"\t\t\t[END_FMT]\r\n\t\t@@END_AC_SET_{index}\r\n"
    )


__all__ = [
    "S100_REQUIRED_STRUCTURES", "S100_SECTION_ORDER", "S100SkeletonSyntax",
    "project_contribution",
]
