"""Pure Chroma renderer for DAC_TEST."""

import re
from program_gen.core.dac_test import DacTestPlan
from program_gen.core.firmware_render import FirmwareBodyRender
from program_gen.core.run_sequence import LevelSequenceAction, SendCodeAction, WaitAction
from program_gen.platforms.chroma.firmware_test_renderer import action_pattern_span, generate_level_sequence_resource, generate_send_code_resource
from program_gen.render_plan import ResourceRequirement


def render_dac_test(plan, name, hardware_bin, facts):
    _validate(plan, name, facts); _ = hardware_bin
    pins = tuple(pin.name for pin in facts.pin_groups.dac_out)
    resources, requirements = [], {}
    if _loopable_swd(plan):
        return _render_swd_loops(plan, name, pins, resources, requirements)
    lines = [f"{name}()", "{", *_start(plan, pins, requirements, resources)]
    for pin in pins:
        previous_mode = None
        for index, case in enumerate(plan.cases):
            if index and case.repower_before:
                lines.extend((*_stop(pins), *_start(plan, pins, requirements, resources))); previous_mode = None
            if case.mode != previous_mode and plan.protocol == "swd":
                pattern = _output_pattern(plan, case.mode, pin)
                requirements[pattern] = _external(pattern)
                lines.extend(_run(pattern)); previous_mode = case.mode
            elif plan.protocol == "keil": lines.extend(_actions(case.actions, resources))
            if case.code_pattern:
                requirements[case.code_pattern] = _external(case.code_pattern); lines.extend(_run(case.code_pattern))
            lines.extend((f'  DATALOG_MSG="DAC_{case.mode}_{pin}_{case.code}_Verify";', f"  JUDGE_V_PPMU({pin},{_num(case.low_limit)}V,{_num(case.high_limit)}V,2mS);", ""))
    lines.extend(_actions(plan.exit_actions, resources)); lines.extend((*_stop(pins), "}"))
    return FirmwareBodyRender("\n".join(lines)+"\n", resources=tuple(resources), resource_requires=tuple(requirements.values()))


def _render_swd_loops(plan, name, pins, resources, requirements):
    groups = _swd_groups(plan.cases)
    lines = [f"{name}()", "{"]
    for variable, cases in groups:
        count = len(cases)
        codes = ",".join(f'"{case.code}"' for case in cases)
        lines.extend((
            f"  char {variable}_code[{count}][4]={{{codes}}};",
            f"  double {variable}_down[{count}]={{{_values(cases, 'low_limit')}}};",
            f"  double {variable}_up[{count}]={{{_values(cases, 'high_limit')}}};",
        ))
    lines.extend(("  char dac_st[64],dac_sp[64],dac_log[64];", "", *_start(plan, pins, requirements, resources)))
    for pin in pins:
        for variable, cases in groups:
            mode = cases[0].mode
            config = _output_pattern(plan, mode, pin)
            requirements[config] = _external(config)
            lines.extend(_run(config))
            for case in cases:
                requirements[case.code_pattern] = _external(case.code_pattern)
            lines.extend((f"  for(int c=0;c<{len(cases)};c++)", "  {"))
            lines.extend((
                f'    sprintf(dac_st,"{plan.product}_DAC_CODE_%s",{variable}_code[c]);',
                f'    sprintf(dac_sp,"__{plan.product}_DAC_CODE_%s",{variable}_code[c]);',
                "    TEST_NUM++;",
                "    TEST_NO(TEST_NUM); DATALOG_MSG=dac_st;",
                "    JUDGE_PAT(S:dac_st,S:dac_sp);",
                f'    sprintf(dac_log,"DAC_{mode}_{pin}_%s_Verify",{variable}_code[c]);',
                "    DATALOG_MSG=dac_log;",
                f"    JUDGE_V_PPMU({pin},{variable}_down[c],{variable}_up[c],2mS);",
                "  }", "",
            ))
    lines.extend(_actions(plan.exit_actions, resources)); lines.extend((*_stop(pins), "}"))
    return FirmwareBodyRender("\n".join(lines)+"\n", resources=tuple(resources), resource_requires=tuple(requirements.values()))


def _start(plan, pins, requirements, resources):
    result=[f"  POWER_ON({_power(plan.power_profile)});",f"  RELAY_ON({'+'.join(pins)},PPMU_PDCL,2mS);"]
    if plan.init_pattern: requirements[plan.init_pattern]=_external(plan.init_pattern); result.extend(_run(plan.init_pattern))
    else: result.extend(_actions(plan.entry_actions, resources))
    result.extend(f"  FORCE_I_PPMU({pin},0uA,@200uA,,6V,-2V,3mS);" for pin in pins); result.extend(("  WAIT(10mS);","")); return tuple(result)
def _stop(pins): return (f"  RELAY_OFF({'+'.join(pins)},PPMU_PDCL,2mS);","  POWER_OFF();","")
def _run(pattern, end=None): return ("  TEST_NUM++;",f'  TEST_NO(TEST_NUM); DATALOG_MSG="{pattern}";',f"  JUDGE_PAT({pattern},{end or '__' + pattern});","")
def _actions(actions, resources):
    lines=[]
    for action in actions:
        if isinstance(action,WaitAction): lines.append(f"  WAIT({action.duration_ms}mS);")
        else:
            resource=generate_level_sequence_resource(action) if isinstance(action,LevelSequenceAction) else generate_send_code_resource(action) if isinstance(action,SendCodeAction) else None
            if resource is None: raise ValueError(f"DAC.CHROMA.ACTION.INVALID: {type(action).__name__}")
            resources.append(resource); lines.extend(_run(*action_pattern_span(action)))
    return tuple(lines)
def _external(pattern): return ResourceRequirement(f"dac-swd:chroma:{pattern.casefold()}",f"pat/{pattern}.pat","v14.dac-swd/1:chroma:external",f"DAC SWD Pattern ({pattern})")
def _output_pattern(plan, mode, pin):
    original = f"{plan.product}_DAC_{mode}_{pin}_Test"
    return dict(plan.output_pattern_names).get(original.casefold(), dict(plan.output_pattern_names).get(original, original))
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
def _power(value): return value[:-1] if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)V",value,re.I) else value
def _validate(plan,name,facts):
    if not isinstance(plan,DacTestPlan): raise TypeError("DAC.CHROMA.PLAN.INVALID")
    if facts.platform.casefold()!="chroma" or facts.cp.casefold()!=plan.cp.casefold() or not facts.pin_groups.dac_out: raise ValueError("DAC.CHROMA.FACTS.INVALID")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",str(name)): raise ValueError("DAC.CHROMA.NAME.INVALID")


__all__=["render_dac_test"]
