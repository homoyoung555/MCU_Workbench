"""Render a self-contained PDR_TRIM plan into S100 PRG source."""

from __future__ import annotations

from program_gen.core.dedicated_trim import DedicatedTrimPlan


def render_pdr_trim_body(
    plan: DedicatedTrimPlan,
    *,
    power_rails: tuple[str, ...],
    reject_bin,
) -> str:
    if plan.typed_kind != "PDR_TRIM":
        raise ValueError(f"plan {plan.item!r} is not a PDR_TRIM plan")
    if not power_rails:
        raise ValueError("PDR.S100.POWER_RAILS: no target power rails")
    if reject_bin in (None, ""):
        raise ValueError("PDR.S100.REJECT_BIN: missing canonical hardware bin")

    codes = ",".join(str(code) for code in plan.search_codes)
    lines = [
        f"@@PLAN {plan.item.title()}",
        "\tSITE_SEQUENCE      = OFF;",
        "\tGO_THROUGH         = ON;",
        "\tDISABLE_BY_MARK_NO = NULL;",
        "\tS_SETUP_FILE       = c:\\set.dat;",
        f"\tREMARK             = {plan.item.title()};",
        "",
        "\tint trimDac[MAX_SITE],pdrPassflag[MAX_SITE];",
        f"\tint dacArray[16]={{{codes}}};",
        "\tint cyc=0;",
        f"\tint endCyc={plan.dac_bits};",
        "\tchar cycMsg[48];",
        "",
        "\tfor(I=0;I<MAX_SITE;I++)",
        "\t{",
        "\t\ttrimDac[I]=8;",
        "\t\tpdrPassflag[I]=0;",
        "\t}",
        "",
    ]
    _relay(lines, plan.relay, connect=True)
    lines.extend((
        f"\tCALL_MACRO POWER_ON(_C_{plan.initial_vcc});",
        "",
        "\tRUN_PATTERN(enter_fbist_mode:START,enter_fbist_mode:END,1,TS_5MHZ);",
        "\tRUN_PATTERN(set_all_final_vposp:START,set_all_final_vposp:END,1,TS_5MHZ);",
        f"\tCALL_MACRO {plan.helper_name}(trimDac);",
        "",
    ))
    _force_voltage(lines, power_rails, "TAR")
    lines.extend((
        "\tWAIT(10MS);",
        "",
        "\tfor(cyc=0;cyc<16;cyc++)",
        "\t{",
        '\t\tsprintf(cycMsg,"pdr_trim_index_%d",cyc);',
        "\t\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)",
        "\t\t{",
        "\t\t\ttrimDac[T_SOCKET]=dacArray[cyc];",
        "\t\t}",
        f"\t\tCALL_MACRO {plan.helper_name}(trimDac);",
        "\t\tRUN_PATTERN(read_status_mode:START,read_status_mode:END,1,TS_5MHZ);",
        "\t\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)",
        "\t\t{",
        "\t\t\tif(Sys_DriverResult[T_SOCKET] < 0.5)",
        "\t\t\t{",
        "\t\t\t\tPDR_DAC_FINAL[T_SOCKET]=trimDac[T_SOCKET];",
        "\t\t\t\tGB[4+T_SOCKET*64]=PDR_DAC_FINAL[T_SOCKET];",
        "\t\t\t}",
        "\t\t\telse if(trimDac[T_SOCKET]==8)",
        "\t\t\t{",
        "\t\t\t\tPDR_DAC_FINAL[T_SOCKET]=8;",
        "\t\t\t\tpdrPassflag[T_SOCKET]=1;",
        "\t\t\t}",
        "\t\t\tSYS_SetTestResult(PASS,T_SOCKET);",
        "\t\t}",
        "\t}",
        "",
        "\tC_COMPARE(GB5,DOWN_LIMIT=0,UP_LIMIT=15,LOG_ALIAS=pdr_dac_f);",
        "",
        "\tCALL_MACRO POWER_OFF();",
        f"\tCALL_MACRO POWER_ON(_C_{plan.initial_vcc});",
        "\tRUN_PATTERN(enter_fbist_mode:START,enter_fbist_mode:END,1,TS_5MHZ);",
        "\tRUN_PATTERN(set_all_final_vposp:START,set_all_final_vposp:END,1,TS_5MHZ);",
        f"\tCALL_MACRO {plan.helper_name}(PDR_DAC_FINAL);",
        "",
    ))
    _force_voltage(lines, power_rails, "MIN")
    lines.extend((
        "\tWAIT(10MS);",
        "\tRUN_PATTERN(read_status_mode:START,read_status_mode:END,1,TS_5MHZ);",
        "\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)",
        "\t{",
        "\t\tif(Sys_DriverResult[T_SOCKET] > 0.5)",
        "\t\t\tSYS_SetTestResult(PASS,T_SOCKET);",
        "\t\telse",
        "\t\t\tSYS_SetTestResult(FAIL,T_SOCKET);",
        "\t\tif(pdrPassflag[T_SOCKET]==1)",
        "\t\t\tSYS_SetTestResult(FAIL,T_SOCKET);",
        "\t}",
        "\tRUN_PATTERN(exit_fbist_mode:START,exit_fbist_mode:END,1,TS_5MHZ);",
        "\tCALL_MACRO POWER_OFF();",
        "",
    ))
    _relay(lines, plan.relay, connect=False)
    lines.extend((
        "\tCONDITION",
        "\tIF_FAIL",
        f"\tREJECT_BIN = {reject_bin};",
        "@@END_PLAN",
    ))
    return "\n".join(lines) + "\n"


def _force_voltage(lines: list[str], rails: tuple[str, ...], role: str) -> None:
    voltage = f"_C_VCC_PDR_{role}"
    for rail in rails:
        lines.append(
            f"\tLOGIC_FORCE_DPS({rail}, {voltage}, 500MA, I7, WAIT=0.5MS);"
        )
    lines.extend((
        f"\tLOGIC_SET_DRV_LEVEL(IO_ALLPINS, {voltage}, 0.0V, 0.0V, VR1);",
        f"\tLOGIC_SET_CMP_LEVEL(IO_ALLPINS,{voltage}*0.55,{voltage}*0.45,VR2);",
    ))


def _relay(lines: list[str], relay: str | None, *, connect: bool) -> None:
    if relay is None:
        return
    mode = "CONNECT_MODE" if connect else "DISCONNECT_MODE"
    lines.append(
        f"\tIO_CLOSE_USER_RELAY({relay},{mode},ALL_SITE_ON,WAIT=1MS);"
    )


__all__ = ["render_pdr_trim_body"]
