"""Pure S100 renderer for OPA_TEST."""

import re
from program_gen.core.firmware_render import FirmwareBodyRender
from program_gen.core.opa_test import OpaTestPlan
from program_gen.core.run_sequence import LevelSequenceAction, SendCodeAction, WaitAction
from program_gen.platforms.s100.firmware_test_renderer import action_pattern_span, generate_level_sequence_resource, generate_send_code_resource
from program_gen.render_plan import ResourceRequirement


def render_opa_test(plan, name, hardware_bin, facts):
    _validate(plan,name,facts)
    resources=[]; requirements=tuple(_external(pattern) for pattern in plan.patterns)
    if _loopable_swd(plan):
        return _render_swd_loop(plan,name,hardware_bin,resources,requirements)
    body=[*_start(plan), *_actions(plan.entry_actions,resources)]
    for index,case in enumerate(plan.cases):
        if index and case.repower_before: body.extend((*_stop(),*_start(plan),*_actions(plan.entry_actions,resources)))
        body.append(f"\t//////////////// OPA {case.mode} ////////////////")
        if case.config_pattern: body.extend((f"\tRUN_PATTERN({case.config_pattern}:START,{case.config_pattern}:END,1,TS_500K);",""))
        else: body.extend(_actions(case.actions,resources))
        if case.inp0_voltage is not None: body.append(f"\tLOGIC_PPMU_FV(OPA_INP0_pins,{_num(case.inp0_voltage)}V,E1,I2);")
        if case.inn0_voltage is not None: body.append(f"\tLOGIC_PPMU_FV(OPA_INN_pins,{_num(case.inn0_voltage)}V,E1,I2);")
        body.extend(("\tLOGIC_PPMU_FI(OPA_OUT_pins,0UA,E1,I6);",f"\tLOGIC_PPMU_MV(OPA_OUT_pins,DOWN_LIMIT={_num(case.low_limit)}V,UP_LIMIT={_num(case.high_limit)}V,LOG_ALIAS=OPA_{case.mode}_[PINGROUP],LOG_UNIT=V);","\tLOGIC_DISCONNECT_PPMU_PIN(OPA_INP0_pins);","\tLOGIC_DISCONNECT_PPMU_PIN(OPA_INN_pins);",""))
    body.extend(_actions(plan.exit_actions,resources)); body.extend(_stop())
    lines=[f"@@PLAN {name}","\tSITE_SEQUENCE      = OFF;","\tGO_THROUGH         = ON;","\tDISABLE_BY_MARK_NO = NULL;","\tS_SETUP_FILE       = c:\\set.dat;",f"\tREMARK             = {name};","",*body,"\tCONDITION","\t\tIF_FAIL",f"\t\tREJECT_BIN = {_hbin(hardware_bin)};","@@END_PLAN"]
    return FirmwareBodyRender("\n".join(lines)+"\n",resources=tuple(resources),resource_requires=requirements)


def _render_swd_loop(plan,name,hardware_bin,resources,requirements):
    cases=plan.cases; count=len(cases)
    body=[
        "", *_start(plan), f"\tfor(int it=0;it<{count};it++)", "\t{",
        "\t\tswitch(it)", "\t\t{",
    ]
    for index,case in enumerate(cases):
        case_lines = [
            f"\t\t\tcase {index}:",
            f"\t\t\t\tRUN_PATTERN({case.config_pattern}:START,{case.config_pattern}:END,1,TS_500K);",
        ]
        if case.inp0_voltage is not None:
            case_lines.append(
                f"\t\t\t\tLOGIC_PPMU_FV(OPA_INP0_pins,{_num(case.inp0_voltage)}V,E1,I2);"
            )
        if case.inn0_voltage is not None:
            case_lines.append(
                f"\t\t\t\tLOGIC_PPMU_FV(OPA_INN_pins,{_num(case.inn0_voltage)}V,E1,I2);"
            )
        case_lines.append("\t\t\t\tbreak;")
        body.extend(case_lines)
    body.extend((
        "\t\t}",
        "\t\tLOGIC_PPMU_FI(OPA_OUT_pins,0UA,E1,I6);",
        "\t\tswitch(it)", "\t\t{",
    ))
    for index,case in enumerate(cases):
        body.extend((
            f"\t\t\tcase {index}:",
            f"\t\t\t\tLOGIC_PPMU_MV(OPA_OUT_pins,DOWN_LIMIT={_num(case.low_limit)}V,UP_LIMIT={_num(case.high_limit)}V,LOG_ALIAS=OPA_{case.mode}_[PINGROUP],LOG_UNIT=V);",
            "\t\t\t\tbreak;",
        ))
    body.extend((
        "\t\t}",
        "\t\tLOGIC_DISCONNECT_PPMU_PIN(OPA_INP0_pins);",
        "\t\tLOGIC_DISCONNECT_PPMU_PIN(OPA_INN_pins);",
        "\t}", "",
    ))
    body.extend(_actions(plan.exit_actions,resources)); body.extend(_stop())
    lines=[f"@@PLAN {name}","\tSITE_SEQUENCE      = OFF;","\tGO_THROUGH         = ON;","\tDISABLE_BY_MARK_NO = NULL;","\tS_SETUP_FILE       = c:\\set.dat;",f"\tREMARK             = {name};","",*body,"\tCONDITION","\t\tIF_FAIL",f"\t\tREJECT_BIN = {_hbin(hardware_bin)};","@@END_PLAN"]
    return FirmwareBodyRender("\n".join(lines)+"\n",resources=tuple(resources),resource_requires=requirements)


def _start(plan): return (f"\tCALL_MACRO POWER_ON({_power(plan.power_profile)});",*( (f"\tRUN_PATTERN({plan.init_pattern}:START,{plan.init_pattern}:END,1,TS_500K);","") if plan.init_pattern else ()))
def _stop(): return ("\tLOGIC_DISCONNECT_PPMU_PIN(OPA_OUT_pins);","\tCALL_MACRO POWER_OFF();","")
def _actions(actions,resources):
    lines=[]
    for action in actions:
        if isinstance(action,WaitAction): lines.append(f"\tWAIT({action.duration_ms}MS);")
        else:
            resource=generate_level_sequence_resource(action) if isinstance(action,LevelSequenceAction) else generate_send_code_resource(action) if isinstance(action,SendCodeAction) else None
            if resource is None: raise ValueError(f"OPA.S100.ACTION.INVALID: {type(action).__name__}")
            resources.append(resource); start,end=action_pattern_span(action); lines.extend((f"\tRUN_PATTERN({start},{end},1,TS_5MHZ);",""))
    return tuple(lines)
def _external(pattern): return ResourceRequirement(f"opa-swd:s100:{pattern.casefold()}",f"{pattern}.sd","v14.opa-swd/1:s100:external",f"OPA SWD Pattern ({pattern})")
def _loopable_swd(plan): return plan.protocol == "swd" and all(case.config_pattern and not case.actions and not case.repower_before for case in plan.cases)
def _numbers(cases,field): return ",".join(_num(getattr(case,field) or 0) for case in cases)
def _enabled(cases,field): return ",".join("1" if getattr(case,field) is not None else "0" for case in cases)
def _power(value): return value[:-1] if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)V",value,re.I) else f"_C_{value}"
def _num(value): return format(float(value),".12g")
def _hbin(value):
    if isinstance(value,bool) or not str(value).strip().isdigit(): raise ValueError("OPA.S100.BIN.INVALID")
    return int(str(value).strip())
def _validate(plan,name,facts):
    if not isinstance(plan,OpaTestPlan) or plan.typed_kind!="OPA_TEST": raise TypeError("OPA.S100.PLAN.INVALID")
    if facts.platform.casefold()!="s100" or facts.cp.casefold()!=plan.cp.casefold(): raise ValueError("OPA.S100.FACTS.INVALID")
    if not facts.pin_groups.opa_inp0 or not facts.pin_groups.opa_out: raise ValueError("OPA.S100.GROUPS.EMPTY")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",str(name)): raise ValueError("OPA.S100.NAME.INVALID")


__all__=["render_opa_test"]
