"""PDR_TRIM-owned DAC write helper."""

from __future__ import annotations

from program_gen.render_plan import (
    ProgramContribution,
    RenderSymbolRef,
    SectionFragment,
    SymbolProvision,
)


def compile_pdr_trim_support(target, plan, write_region) -> ProgramContribution:
    platform = target.platform.casefold()
    extension = ".pln" if platform == "chroma" else ".prg"
    path = f"{target.program_name}{extension}"
    if platform == "chroma":
        sections = (SectionFragment(
                path,
                "HELPERS",
                "pdr-trim:helper",
                _chroma_helper(plan, write_region).encode("gbk"),
                order=200,
            ),)
    elif platform == "s100":
        sections = (SectionFragment(
                path,
                "HELPERS",
                "pdr-trim:helper",
                _s100_helper(plan, write_region).encode("gbk"),
                order=200,
            ),)
    else:
        raise ValueError(f"TK.PDR_TRIM.PLATFORM: {target.platform!r}")
    return ProgramContribution(
        identity=f"pdr-trim:support:{target.identity}",
        target=target,
        sections=sections,
        provides=(SymbolProvision(
            RenderSymbolRef("HELPER", plan.helper_name),
            plan.helper_name,
            "CALLABLE",
            None,
            "TARGET",
        ),),
    )

def _chroma_helper(plan, region) -> str:
    return (
        f"{plan.helper_name}(int* a)\r\n{{\r\n"
        "  SOCKET_INC(FRZ_OFF)\r\n  {\r\n"
        f"    TRIM_DIGIT={plan.dac_bits}-1;\r\n"
        "    TEMP=a[SOCKET];\r\n"
        "    for(J=0;J<=TRIM_DIGIT;J++){BIT[J]=TEMP%2;TEMP=TEMP/2;}\r\n"
        "    for(J=TRIM_DIGIT;J>=0;J--)\r\n    {\r\n"
        f"      if(BIT[J]==0) WRITE_PAT_MEM(SOCKET,{plan.write_pin},{plan.dac_pattern_name}:{region.base_label}+TRIM_DIGIT-J,,\"0\");\r\n"
        f"      else WRITE_PAT_MEM(SOCKET,{plan.write_pin},{plan.dac_pattern_name}:{region.base_label}+TRIM_DIGIT-J,,\"1\");\r\n"
        "    }\r\n  }\r\n  TEST_NUM++;\r\n"
        f"  TEST_NO(TEST_NUM);DATALOG_MSG=\"{plan.dac_pattern_name}\";\r\n"
        f"  JUDGE_PAT({plan.dac_pattern_name},__{plan.dac_pattern_name});\r\n"
        "}\r\n\r\n"
    )

def _s100_helper(plan, region) -> str:
    return (
        f"@@MACRO {plan.helper_name}(int* a)\r\n"
        "  for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\r\n  {\r\n"
        "    GB[0+T_SOCKET*64]=a[T_SOCKET];\r\n  }\r\n"
        f"  LOGIC_WRITE_PATTERN_MEMORY({plan.dac_pattern_name}:{region.start_label},"
        f"{plan.dac_pattern_name}:{region.end_label},{plan.write_pin},GB1,"
        f"BIT_COUNT={plan.dac_bits},SERIAL,MSB_LSB);\r\n"
        f"  RUN_PATTERN({plan.dac_pattern_name}:START,{plan.dac_pattern_name}:END,1,TS_5MHZ);\r\n"
        "@@END_MACRO\r\n\r\n"
    )


__all__ = ["compile_pdr_trim_support"]
