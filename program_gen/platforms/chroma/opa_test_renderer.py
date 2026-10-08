"""Pure Chroma renderer for OPA_TEST."""

import re
from program_gen.core.firmware_render import FirmwareBodyRender
from program_gen.core.opa_test import OpaTestPlan
from program_gen.core.run_sequence import LevelSequenceAction, SendCodeAction, WaitAction
from program_gen.platforms.chroma.firmware_test_renderer import action_pattern_span, generate_level_sequence_resource, generate_send_code_resource
from program_gen.render_plan import ResourceRequirement


def render_opa_test(plan, name, hardware_bin, facts):
    _validate(plan, name, facts); _ = hardware_bin
    resources, requirements = [], tuple(_external(pattern) for pattern in plan.patterns)
    if _loopable_swd(plan):
        return _render_swd_loop(plan, name, resources, requirements)
    lines = [f"{name}()", "{", *_start(plan), *_actions(plan.entry_actions, resources)]
    for index, case in enumerate(plan.cases):
        if index and case.repower_before: lines.extend((*_stop(), *_start(plan), *_actions(plan.entry_actions, resources)))
        if case.config_pattern: lines.extend(_run(case.config_pattern))
        else: lines.extend(_actions(case.actions, resources))
        if case.inp0_voltage is not None: lines.append(f"  FORCE_V_PPMU(OPA_INP0_pins,{_num(case.inp0_voltage)}V,,@32mA,,2mS);")
        if case.inn0_voltage is not None: lines.append(f"  FORCE_V_PPMU(OPA_INN_pins,{_num(case.inn0_voltage)}V,,@32mA,,2mS);")
        lines.extend((f'  DATALOG_MSG="OPA_{case.mode}_Verify";', "  FORCE_I_PPMU(OPA_OUT_pins,0uA,@200uA,,6V,-2V,3mS);", f"  JUDGE_V_PPMU(OPA_OUT_pins,{_num(case.low_limit)}V,{_num(case.high_limit)}V,2mS);", "  FORCE_I_PPMU(OPA_INP0_pins,0uA,@200uA,,6V,-2V,2mS);", "  FORCE_I_PPMU(OPA_INN_pins,0uA,@200uA,,6V,-2V,2mS);", ""))
    lines.extend(_actions(plan.exit_actions, resources)); lines.extend((*_stop(), "}"))
    return FirmwareBodyRender("\n".join(lines)+"\n", resources=tuple(resources), resource_requires=requirements)


def _render_swd_loop(plan, name, resources, requirements):
    cases = plan.cases; count = len(cases)
    pattern_format = _loop_pattern_format(plan)
    modes = ",".join(_quoted(case.mode) for case in cases)
    mode_width = max(len(case.mode) for case in cases) + 1
    lines = [
        f"{name}()", "{",
        f"  char opa_mode[{count}][{mode_width}]={{{modes}}};",
        f"  double opa_inp0[{count}]={{{_numbers(cases, 'inp0_voltage')}}};",
        f"  int opa_inp0_on[{count}]={{{_enabled(cases, 'inp0_voltage')}}};",
        f"  double opa_inn0[{count}]={{{_numbers(cases, 'inn0_voltage')}}};",
        f"  int opa_inn0_on[{count}]={{{_enabled(cases, 'inn0_voltage')}}};",
        f"  double opa_down[{count}]={{{_numbers(cases, 'low_limit')}}};",
        f"  double opa_up[{count}]={{{_numbers(cases, 'high_limit')}}};",
        "  char pat_st[64],pat_sp[64],log_msg[64];", "", *_start(plan),
        f"  for(int it=0;it<{count};it++)", "  {",
        f'    sprintf(pat_st,"{pattern_format}",opa_mode[it]);',
        f'    sprintf(pat_sp,"__{pattern_format}",opa_mode[it]);',
        "    TEST_NUM++;", "    TEST_NO(TEST_NUM); DATALOG_MSG=pat_st;",
        "    JUDGE_PAT(S:pat_st,S:pat_sp);", "",
        "    if(opa_inp0_on[it]) FORCE_V_PPMU(OPA_INP0_pins,opa_inp0[it],,@32mA,,2mS);",
        "    if(opa_inn0_on[it]) FORCE_V_PPMU(OPA_INN_pins,opa_inn0[it],,@32mA,,2mS);",
        '    sprintf(log_msg,"OPA_%s_Verify",opa_mode[it]);',
        "    DATALOG_MSG=log_msg;",
        "    FORCE_I_PPMU(OPA_OUT_pins,0uA,@200uA,,6V,-2V,3mS);",
        "    JUDGE_V_PPMU(OPA_OUT_pins,opa_down[it],opa_up[it],2mS);",
        "    FORCE_I_PPMU(OPA_INP0_pins,0uA,@200uA,,6V,-2V,2mS);",
        "    FORCE_I_PPMU(OPA_INN_pins,0uA,@200uA,,6V,-2V,2mS);",
        "  }", "",
    ]
    lines.extend(_actions(plan.exit_actions, resources)); lines.extend((*_stop(), "}"))
    return FirmwareBodyRender("\n".join(lines)+"\n", resources=tuple(resources), resource_requires=requirements)


def _start(plan): return (f"  POWER_ON({_power(plan.power_profile)});", "  RELAY_ON(OPA_INP0_pins+OPA_INN_pins+OPA_OUT_pins,PPMU_PDCL,2mS);", *(_run(plan.init_pattern) if plan.init_pattern else ()), "")
def _stop(): return ("  RELAY_OFF(OPA_INP0_pins+OPA_INN_pins+OPA_OUT_pins,PPMU_PDCL,2mS);", "  POWER_OFF();", "")
def _run(pattern, end=None): return ("  TEST_NUM++;", f'  TEST_NO(TEST_NUM); DATALOG_MSG="{pattern}";', f"  JUDGE_PAT({pattern},{end or '__' + pattern});", "")
def _actions(actions, resources):
    lines=[]
    for action in actions:
        if isinstance(action, WaitAction): lines.append(f"  WAIT({action.duration_ms}mS);")
        else:
            resource = generate_level_sequence_resource(action) if isinstance(action, LevelSequenceAction) else generate_send_code_resource(action) if isinstance(action, SendCodeAction) else None
            if resource is None: raise ValueError(f"OPA.CHROMA.ACTION.INVALID: {type(action).__name__}")
            resources.append(resource); lines.extend(_run(*action_pattern_span(action)))
    return tuple(lines)
def _external(pattern): return ResourceRequirement(f"opa-swd:chroma:{pattern.casefold()}", f"pat/{pattern}.pat", "v14.opa-swd/1:chroma:external", f"OPA SWD Pattern ({pattern})")
def _loop_pattern_format(plan):
    if not plan.cases or not plan.cases[0].config_pattern:
        return None
    first = plan.cases[0]
    template = first.config_pattern.replace(first.mode, "%s", 1)
    return template if all(template % case.mode == case.config_pattern for case in plan.cases) else None
def _loopable_swd(plan): return plan.protocol == "swd" and _loop_pattern_format(plan) is not None and all(not case.actions and not case.repower_before for case in plan.cases)
def _numbers(cases, field): return ",".join(_num(getattr(case, field) or 0) for case in cases)
def _enabled(cases, field): return ",".join("1" if getattr(case, field) is not None else "0" for case in cases)
def _quoted(value): return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'
def _power(value): return value[:-1] if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)V",value,re.I) else value
def _num(value): return format(float(value), ".12g")
def _validate(plan,name,facts):
    if not isinstance(plan,OpaTestPlan) or plan.typed_kind!="OPA_TEST": raise TypeError("OPA.CHROMA.PLAN.INVALID")
    if facts.platform.casefold()!="chroma" or facts.cp.casefold()!=plan.cp.casefold(): raise ValueError("OPA.CHROMA.FACTS.INVALID")
    if not facts.pin_groups.opa_inp0 or not facts.pin_groups.opa_out: raise ValueError("OPA.CHROMA.GROUPS.EMPTY")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",str(name)): raise ValueError("OPA.CHROMA.NAME.INVALID")


__all__=["render_opa_test"]
