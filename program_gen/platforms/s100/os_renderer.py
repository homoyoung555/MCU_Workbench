"""Render a typed ``OsPlan`` into S100 PRG tester source.

Mirror of ``chroma/os_renderer.py`` for S100/YT5100.  S100 OS covers ordinary
IO pins (ODD/EVEN groups) and TP pins only — the power-rail MLDPS block stays
commented out in the legacy writer, matching the platform's OS scope.
"""

from __future__ import annotations

from program_gen.core.os_plan import OsPlan


def render_os_body(
    plan: OsPlan,
    *,
    power_pins: tuple[str, ...],
    reject_bin: int,
) -> str:
    """Return the S100 PRG ``@@PLAN`` block for one OS definition."""
    if plan.item.casefold() != "os_test":
        raise ValueError(f"plan {plan.item!r} is not an OS plan")

    lines: list[str] = []
    lines.append(f"@@PLAN {plan.item.title()}")
    lines.append("	SITE_SEQUENCE      = OFF;")
    lines.append("	GO_THROUGH         = ON;")
    lines.append("	DISABLE_BY_MARK_NO = NULL;")
    lines.append("	S_SETUP_FILE       = c:\\set.dat;")
    lines.append(f"	REMARK             = {plan.item.title()};")
    lines.append("")
    if plan.relay is not None:
        lines.append(
            f"	IO_CLOSE_USER_RELAY({plan.relay},CONNECT_MODE,"
            "ALL_SITE_ON,WAIT=1MS);"
        )
    lines.append("	CALL_MACRO test_start();")
    lines.append(
        "	LOGIC_SET_DRV_LEVEL(IO_ALLPINS, 0.0V,0.0V, 0.0V, VR1);\n"
        "	LOGIC_SET_CMP_LEVEL(IO_ALLPINS,0.0V,0.0V,VR1);\n"
        "	LOGIC_CLOSE_PE_RELAY(IO_ALLPINS,WAIT=0.5MS);"
    )
    for rail in power_pins:
        lines.append(
            f"	LOGIC_FORCE_DPS({rail}, 0.0V, 500MA, I7, WAIT=0.5MS);\n"
        )
        lines.append(f"	LOGIC_CLOSE_DPS_OUTPUT_RELAY({rail},ON,WAIT=1MS);")
    lines.append("	///////////////////////OSTEST odd pins/////////////////////")
    lines.append("	LOGIC_PPMU_FI(ODD_pins,-100uA, E2, I5);")
    lines.append("	LOGIC_PPMU_MV(ODD_pins, UP_LIMIT=3.3V, DOWN_LIMIT=-3.3V);")
    lines.append(
        "	C_COMPARE(ODD_pins, DOWN_LIMIT=-1.2, UP_LIMIT=-0.2, UNIT=V, "
        "LOG_ALIAS=OS_[PINGROUP], LOG_UNIT=V);"
    )
    lines.append("")
    lines.append("	///////////////////////OSTEST even pins/////////////////////")
    lines.append("	LOGIC_PPMU_FI(EVEN_pins,-100uA, E2, I5);")
    lines.append("	LOGIC_PPMU_MV(EVEN_pins, UP_LIMIT=3.3V, DOWN_LIMIT=-3.3V);")
    lines.append(
        "	C_COMPARE(EVEN_pins, DOWN_LIMIT=-1.2, UP_LIMIT=-0.2, UNIT=V, "
        "LOG_ALIAS=OS_[PINGROUP], LOG_UNIT=V);"
    )
    lines.append("")
    lines.append("	///////////////////////TP pin/////////////////////")
    lines.append("	LOGIC_PPMU_FI(TP,-100uA, E2, I5);")
    lines.append("	LOGIC_PPMU_MV(TP, UP_LIMIT=3.3V, DOWN_LIMIT=-3.3V);")
    lines.append(
        "	C_COMPARE(TP, DOWN_LIMIT=-3.0, UP_LIMIT=-0.2, UNIT=V, "
        "LOG_ALIAS=OS_[PINGROUP], LOG_UNIT=V);"
    )
    lines.append("")
    lines.append("	LOGIC_DISCONNECT_PPMU_PIN(IO_ALLPINS);")
    lines.append("	LOGIC_CLOSE_PE_RELAY(NULL,WAIT=0.5MS);")
    for rail in power_pins:
        lines.append(f"	LOGIC_FORCE_DPS({rail}, 0.0V, 500MA, I7, WAIT=0.5MS);")
    lines.append("	WAIT(10mS);")
    for rail in power_pins:
        lines.append(
            f"	LOGIC_CLOSE_DPS_OUTPUT_RELAY({rail},OFF,WAIT=0.5MS);"
        )
    lines.append("	LOGIC_CLOSE_PMU_RELAY(NULL,WAIT=0.5MS);")
    lines.append("	WAIT(5mS);")
    lines.append("")
    if plan.relay is not None:
        lines.append(
            f"	IO_CLOSE_USER_RELAY({plan.relay},DISCONNECT_MODE,"
            "ALL_SITE_ON,WAIT=1MS);"
        )
    lines.append("	CONDITION")
    lines.append("	IF_FAIL")
    lines.append(f"	REJECT_BIN = {reject_bin};")
    lines.append("@@END_PLAN")
    return "\n".join(lines) + "\n"
