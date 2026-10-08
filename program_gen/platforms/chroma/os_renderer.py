"""Render a typed ``OsPlan`` into Chroma PLN tester source.

Platform adapter at the native-renderer seam, mirroring ``pdr_verify_renderer``
for the OS family.  It maps the immutable OS plan plus a resolved OS render
context (KP relay, power pins, site groups) onto Chroma's C-like PLN function
block, byte-for-byte with the legacy ``os_write`` body.
"""

from __future__ import annotations

from program_gen.core.os_plan import OsPlan
from program_gen.os_assembly import OsRenderContext


def render_os_body(
    plan: OsPlan, *, context: OsRenderContext, test_number: int
) -> str:
    """Return the Chroma PLN function block for one OS definition."""
    if plan.item.casefold() != "os_test":
        raise ValueError(f"plan {plan.item!r} is not an OS plan")

    cp = plan.cp
    has_kp = context.kp_relay
    rails = context.force_rails
    lines: list[str] = []
    lines.append(f"{plan.item.title()}()")
    lines.append("{")
    if plan.relay is not None:
        lines.append(f"  SET_CBIT({plan.relay}, ON, 5mS);")
    lines.append(f"  TEST_NUM={test_number};")
    lines.append(f'  TEST_NO( TEST_NUM);DATALOG_MSG="{plan.item}";')
    lines.append("")
    lines.append("  LEVELS(RST_LVL,3mS);")
    if cp in ("CP1", "CP2") and has_kp:
        lines.append("  SET_CBIT(KP, ON, 2mS);")
    lines.append(
        f"  RELAY_ON(IO_ALLPINS,PDCL,2mS);\n"
        f"  FORCE_V_MLDPS({rails},0V,@6V,@500mA,200mA,NORM,ON,2mS);\n\n"
        f"  PIN_MODE(IO_ALLPINS,F0,EDGE,MASK,IO_ON,OFF);\n"
    )
    lines.append("  ///////////////////////OSTEST pins/////////////////////")
    lines.append("  RELAY_OFF(IO_ALLPINS, PDCL, 2mS);")
    lines.append("  RELAY_ON(IO_ALLPINS,PPMU,2mS);")
    lines.append("")
    lines.append('  TEST_NUM++;\n  TEST_NO( TEST_NUM); DATALOG_MSG = "OSTEST pins";')
    lines.append("")
    lines.append("  FORCE_I_PPMU(IO_ALLPINS-TP, -100uA, @200uA, ,2V, -2V ,3mS);")
    lines.append("  JUDGE_V_PPMU(IO_ALLPINS-TP, -1.2V, -0.2V, 2mS);")
    lines.append("")
    lines.append(
        "  FORCE_I_PPMU(IO_ALLPINS-TP, 0uA, @200uA, ,2V, -2V ,3mS);\n"
        "  FORCE_V_PPMU(IO_ALLPINS-TP,0.0V,,@200uA,,3mS);\n"
    )
    lines.append("  ///////////////////////TP pin/////////////////////")
    lines.append("")
    lines.append('  TEST_NUM++;\n  TEST_NO( TEST_NUM); DATALOG_MSG = "OSTEST TP";')
    lines.append("")
    lines.append("  FORCE_I_PPMU(TP, -100uA, @200uA, ,2V, -2V ,3mS);")
    lines.append("  JUDGE_V_PPMU(TP, -3.0V, -0.2V, 2mS);")
    lines.append("")
    lines.append(
        "  FORCE_I_PPMU(TP, 0uA, @200uA, ,2V, -2V ,3mS);\n"
        "  FORCE_V_PPMU(TP,0.0V,,@200uA,,3mS);\n"
    )
    lines.append("  RELAY_OFF(IO_ALLPINS, PPMU, 2mS);")
    lines.append("  RELAY_ON(IO_ALLPINS,PDCL,2mS);")
    lines.append("")

    if cp in ("CP1", "CP2"):
        _render_power_rail_os_cp12(lines, context, has_kp)
    elif cp == "CP3":
        _render_power_rail_os_cp3(lines, context)

    if plan.relay is not None:
        lines.append(f"  SET_CBIT({plan.relay}, OFF, 5mS);")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _render_power_rail_os_cp12(lines, context, has_kp) -> None:
    lines.append(
        f"  FORCE_V_MLDPS({context.force_rails},0V,@6V,@500mA,200mA,NORM,OFF,2mS);"
    )
    if has_kp:
        lines.append("  SET_CBIT(KP, OFF, 2mS);")
    lines.append("  PIN_MODE(IO_ALLPINS,NRZ,EDGE,ENABLE,IO_OFF,NORM);")
    lines.append("")
    lines.append("  VOLTAGE vmeas[MAX_SITE];")
    for rail in context.power_pins:
        lines.append(f"  /////////////////////// {rail} pin /////////////////////")
        lines.append("  for(I=0;I<MAX_SITE;I++) vmeas[I] = 0;")
        for sites, label in context.site_groups:
            block = _socket_set_open(sites, label)
            if not block:
                continue
            lines.append(
                f"  /////////////////////// {rail} pin {label} closed /////////////////////"
            )
            lines.append(block)
            lines.append("  {")
            if has_kp:
                lines.append("    SET_CBIT(KP, ON, 2mS);")
            lines.append(
                f"    FORCE_I_MLDPS({rail},-100uA,@25mA,@6V,2V,NORM,ON,2mS);\n"
            )
            lines.append(
                '    TEST_NUM++;\n    TEST_NO( TEST_NUM);DATALOG_MSG = "OS_TEST_VDD";\n'
                f"    //MEAS_V_MLDPS({rail},2mS, 4, AVE, 50uS);\n"
                f"    MEAS_V_MLDPS({rail},2mS);\n"
                f"    FORCE_I_MLDPS({rail},0uA,@25mA,@6V,2V,NORM,ON,2mS);\n"
            )
            lines.append(
                f"    SOCKET_INC(FRZ_OFF)\n    {{\n      vmeas[SOCKET]=RESULT_MLDPS_EX(SOCKET,{rail});\n    }}\n"
                '    JUDGE_VARIABLE_MS(vmeas,-1.2V,-0.2V,"OS_TEST_VDD");\n'
            )
            lines.append(
                f"    FORCE_V_MLDPS({rail},0V,@6V,@500mA,500mA,NORM,OFF,2mS);"
            )
            if has_kp:
                lines.append("    SET_CBIT(KP, OFF, 2mS);")
            lines.append("  }")
            lines.append("")


def _render_power_rail_os_cp3(lines, context) -> None:
    for rail in context.power_pins:
        lines.append(f"  /////////////////////// {rail} pin /////////////////////")
        lines.append(f"  FORCE_V_MLDPS({rail},0V,@6V,@500mA,100mA,NORM,OFF,2mS);")
        lines.append("")
        lines.append(f"  FORCE_I_MLDPS({rail},-100uA,@25mA,@6V,2V,NORM,ON,2mS);")
        lines.append("")
        lines.append(
            f'  TEST_NUM++;\n  TEST_NO( TEST_NUM);DATALOG_MSG = "OS_TEST_{rail}";\n'
        )
        lines.append(f"  JUDGE_V_MLDPS({rail},-1.2V,-0.09V,2mS);")
        lines.append("")
        lines.append(f"  FORCE_I_MLDPS({rail},0uA,@25mA,@6V,2V,NORM,ON,2mS);")
        lines.append(f"  FORCE_I_MLDPS({rail},0uA,@500mA,@6V,2V,NORM,ON,2mS);")
        lines.append("")
        lines.append(f"  FORCE_V_MLDPS({rail},0V,@6V,@500mA,100mA,NORM,OFF,2mS);")
        lines.append("")
        lines.append("  PIN_MODE(IO_ALLPINS,NRZ,EDGE,ENABLE,IO_OFF,NORM);\n  RELAY_OFF(IO_ALLPINS,PDCL,2mS);")
        lines.append("")


def _socket_set_open(sites, label) -> str:
    if not sites:
        return ""
    out = "  SOCKET_SET("
    for idx, site in enumerate(sites):
        out += "S" + str(site)
        if idx == len(sites) - 1:
            out += ",FRZ_OFF)//*" + label + " closed"
        elif (idx + 1) % 32 == 0:
            out += "|\n  "
        else:
            out += "|"
    return out
