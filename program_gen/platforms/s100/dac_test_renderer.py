"""Pure S100 renderer for DAC_TEST."""

import re
from program_gen.core.dac_test import DacTestPlan
from program_gen.core.firmware_render import FirmwareBodyRender
from program_gen.core.run_sequence import LevelSequenceAction, SendCodeAction, WaitAction
from program_gen.platforms.s100.firmware_test_renderer import action_pattern_span, generate_level_sequence_resource, generate_send_code_resource
from program_gen.render_plan import ResourceRequirement


def render_dac_test(plan,name,hardware_bin,facts):
    _validate(plan,name,facts); pins=tuple(pin.name for pin in facts.pin_groups.dac_out); resources=[]; requirements={}
    if _loopable_swd(plan):
        return _render_swd_loops(plan,name,hardware_bin,pins,resources,requirements)
    body=list(_start(plan,pins,requirements,resources))
    for pin in pins:
        previous=None
        for index,case in enumerate(plan.cases):
            if index and case.repower_before: body.extend((*_stop(),*_start(plan,pins,requirements,resources))); previous=None
            if case.mode!=previous and plan.protocol=="swd":
                pattern=_output_pattern(plan,case.mode,pin); requirements[pattern]=_external(pattern); body.extend((f"\tRUN_PATTERN({pattern}:START,{pattern}:END,1,TS_500K);",)); previous=case.mode
            elif plan.protocol=="keil": body.extend(_actions(case.actions,resources))
            if case.code_pattern: requirements[case.code_pattern]=_external(case.code_pattern); body.append(f"\tRUN_PATTERN({case.code_pattern}:START,{case.code_pattern}:END,1,TS_500K);")
            body.extend((f"\tLOGIC_PPMU_MV({pin},DOWN_LIMIT={_num(case.low_limit)}V,UP_LIMIT={_num(case.high_limit)}V,LOG_ALIAS=DAC_{case.mode}_{pin}_{case.code}_Verify,LOG_UNIT=V);",""))
    body.extend(_actions(plan.exit_actions,resources)); body.extend(_stop())
    lines=[f"@@PLAN {name}","\tSITE_SEQUENCE      = OFF;","\tGO_THROUGH         = ON;","\tDISABLE_BY_MARK_NO = NULL;","\tS_SETUP_FILE       = c:\\set.dat;",f"\tREMARK             = {name};","",*body,"\tCONDITION","\t\tIF_FAIL",f"\t\tREJECT_BIN = {_hbin(hardware_bin)};","@@END_PLAN"]
    return FirmwareBodyRender("\n".join(lines)+"\n",resources=tuple(resources),resource_requires=tuple(requirements.values()))


def _render_swd_loops(plan,name,hardware_bin,pins,resources,requirements):
    groups=_swd_groups(plan.cases); body=[]
    for variable,cases in groups:
        count=len(cases); codes=",".join(f'"{case.code}"' for case in cases)
        body.extend((
            f"\tchar {variable}_code[{count}][4]={{{codes}}};",
        ))
    body.extend(("\tchar _C_dac_st[64],_C_dac_sp[64];","",*_start(plan,pins,requirements,resources)))
    for pin in pins:
        for variable,cases in groups:
            mode=cases[0].mode; config=_output_pattern(plan,mode,pin)
            requirements[config]=_external(config)
            body.extend((
                f"\tRUN_PATTERN({config}:START,{config}:END,1,TS_500K);",
                f"\tfor(int c=0;c<{len(cases)};c++)", "\t{",
                f'\t\tsprintf(_C_dac_st,"{plan.product}_DAC_CODE_%s:START",{variable}_code[c]);',
                f'\t\tsprintf(_C_dac_sp,"{plan.product}_DAC_CODE_%s:END",{variable}_code[c]);',
                "\t\tRUN_PATTERN(_C_dac_st,_C_dac_sp,1,TS_500K);",
                "\t\tswitch(c)", "\t\t{",
            ))
            for index,case in enumerate(cases):
                requirements[case.code_pattern]=_external(case.code_pattern)
                body.append(
                    f"\t\t\tcase {index}: LOGIC_PPMU_MV({pin},DOWN_LIMIT={_num(case.low_limit)}V,UP_LIMIT={_num(case.high_limit)}V,LOG_ALIAS=DAC_{mode}_{pin}_{case.code}_Verify,LOG_UNIT=V); break;"
                )
            body.extend(("\t\t}","\t}",""))
    body.extend(_actions(plan.exit_actions,resources)); body.extend(_stop())
    lines=[f"@@PLAN {name}","\tSITE_SEQUENCE      = OFF;","\tGO_THROUGH         = ON;","\tDISABLE_BY_MARK_NO = NULL;","\tS_SETUP_FILE       = c:\\set.dat;",f"\tREMARK             = {name};","",*body,"\tCONDITION","\t\tIF_FAIL",f"\t\tREJECT_BIN = {_hbin(hardware_bin)};","@@END_PLAN"]
    return FirmwareBodyRender("\n".join(lines)+"\n",resources=tuple(resources),resource_requires=tuple(requirements.values()))


def _start(plan,pins,requirements,resources):
    lines=[f"\tCALL_MACRO POWER_ON({_power(plan.power_profile)});"]
    if plan.init_pattern: requirements[plan.init_pattern]=_external(plan.init_pattern); lines.append(f"\tRUN_PATTERN({plan.init_pattern}:START,{plan.init_pattern}:END,1,TS_500K);")
    else: lines.extend(_actions(plan.entry_actions,resources))
    lines.extend(f"\tLOGIC_PPMU_FI({pin},0UA,E2,I1);" for pin in pins); lines.extend(("\tWAIT(10MS);","")); return tuple(lines)
def _stop(): return ("\tCALL_MACRO POWER_OFF();","")
def _actions(actions,resources):
    lines=[]
    for action in actions:
        if isinstance(action,WaitAction): lines.append(f"\tWAIT({action.duration_ms}MS);")
        else:
            resource=generate_level_sequence_resource(action) if isinstance(action,LevelSequenceAction) else generate_send_code_resource(action) if isinstance(action,SendCodeAction) else None
            if resource is None: raise ValueError(f"DAC.S100.ACTION.INVALID: {type(action).__name__}")
            resources.append(resource); start,end=action_pattern_span(action); lines.append(f"\tRUN_PATTERN({start},{end},1,TS_5MHZ);")
    return tuple(lines)
def _external(pattern): return ResourceRequirement(f"dac-swd:s100:{pattern.casefold()}",f"{pattern}.sd","v14.dac-swd/1:s100:external",f"DAC SWD Pattern ({pattern})")
def _output_pattern(plan,mode,pin):
    original=f"{plan.product}_DAC_{mode}_{pin}_Test"
    names=dict(plan.output_pattern_names)
    return names.get(original.casefold(),names.get(original,original))
def _loopable_swd(plan): return plan.protocol == "swd" and all(not case.actions and not case.repower_before and case.code_pattern == f"{plan.product}_DAC_CODE_{case.code}" for case in plan.cases)
def _swd_groups(cases):
    groups=[]; names={}
    for case in cases:
        if not groups or groups[-1][1][-1].mode != case.mode:
            stem="dac_"+re.sub(r"[^0-9A-Za-z]","_",case.mode).lower(); names[stem]=names.get(stem,0)+1
            groups.append([stem if names[stem] == 1 else f"{stem}_{names[stem]}",[case]])
        else: groups[-1][1].append(case)
    return tuple((name,tuple(group)) for name,group in groups)
def _values(cases,field): return ",".join(_num(getattr(case,field)) for case in cases)
def _num(value): return format(float(value),".12g")
def _power(value): return value[:-1] if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)V",value,re.I) else f"_C_{value}"
def _hbin(value):
    if isinstance(value,bool) or not str(value).strip().isdigit(): raise ValueError("DAC.S100.BIN.INVALID")
    return int(str(value).strip())
def _validate(plan,name,facts):
    if not isinstance(plan,DacTestPlan): raise TypeError("DAC.S100.PLAN.INVALID")
    if facts.platform.casefold()!="s100" or facts.cp.casefold()!=plan.cp.casefold() or not facts.pin_groups.dac_out: raise ValueError("DAC.S100.FACTS.INVALID")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",str(name)): raise ValueError("DAC.S100.NAME.INVALID")


__all__=["render_dac_test"]
