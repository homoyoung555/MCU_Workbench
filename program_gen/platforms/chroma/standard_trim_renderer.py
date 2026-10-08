"""Render a typed ``TrimSpec`` (STANDARD_TRIM) into Chroma PLN source.

This family renderer owns STANDARD_TRIM sequencing and search semantics.  It
does not expose its Recipe-operation dispatch to other families: shared Chroma
mechanics live behind platform emitters such as ``emit_pattern_run`` instead.
Every business fact comes from ``TrimSpec``; only target-specific abilities such
as the test number and relay are supplied by the render context.  No global
``G`` state, workbook reads, filesystem writes, or final file handles.
"""

from __future__ import annotations

import re
from typing import Callable

from program_gen.core.encoding import calc_limit
from program_gen.core.trim_spec import (
    MeasurementPlan,
    TrimOperation,
    TrimSpec,
)
from program_gen.platforms.chroma.pattern_emitter import emit_pattern_run


_FORCE_CURRENT_RE = re.compile(r"^([+-]?[\d.]+)\s*(uA|mA|A)$", re.IGNORECASE)


def render_standard_trim_body(
    spec: TrimSpec,
    *,
    variant: str = "BISECTION",
    test_number: int,
    relay: str,
) -> str:
    """Return one canonical STANDARD_TRIM variant as a Chroma function block."""
    variant = str(variant).strip().upper()
    declared = tuple(item.kind for item in spec.search.variants)
    if variant not in declared:
        raise ValueError(
            f"STANDARD_TRIM variant {variant!r} is not declared; expected {declared!r}"
        )
    if variant not in ("BISECTION", "FULL_SCAN"):
        raise ValueError(f"STANDARD_TRIM renderer does not support variant {variant!r}")

    lines: list[str] = []
    _render_prologue(spec, variant, test_number, relay, lines)
    for operation in spec.operations:
        renderer = _operation_renderer(operation)
        renderer(operation, spec, variant, lines)
    _render_epilogue(spec, relay, lines)
    return "\n".join(lines) + "\n"


def _render_prologue(
    spec: TrimSpec,
    variant: str,
    test_number: int,
    relay: str,
    lines: list[str],
) -> None:
    """Function header, declarations, initial state, power/relay, and FBIST entry."""
    measurement = spec.measurement
    adjust = spec.adjust

    lines.append(f"{_func_name(spec.item, variant)}()")
    lines.append("{")
    lines.append(f"  TEST_NUM={test_number};")
    message = (
        f"{spec.item.lower()}_trim"
        if variant == "BISECTION"
        else f"{spec.item.lower()}_dac_loop"
    )
    lines.append(f'  TEST_NO(TEST_NUM);DATALOG_MSG="{message}";')
    lines.append("")
    lines.append(f"  double trimTar={spec.trim_tar_reference or _fmt(measurement.target)};")
    lines.append("")
    lines.append("  double trimValue[MAX_SITE],trimFinalValue[MAX_SITE];")
    lines.append("  int trimDac[MAX_SITE];")
    lines.append("")
    if adjust is not None:
        lines.append("  double tempValue[MAX_SITE];")
        lines.append("")

    codes = spec.search.codes
    lines.append(f"  int dacArray[{len(codes)}]={{{','.join(str(code) for code in codes)}}};")
    if variant == "BISECTION":
        lines.append("  int dacIndex[MAX_SITE];")
        lines.append("  int firstIndex=sizeof(dacArray)/sizeof(dacArray[0])/2;")
        lines.append(f"  int binAryCyc={spec.search.search_bits - 2};")
    else:
        lines.append("  int cyc=0;")
        lines.append(f"  int endCyc={len(codes)};")
        lines.append("  char cycMsg[48];")
    lines.append("")
    if adjust is not None and variant == "BISECTION":
        lines.append("  int dacFinalIndex[MAX_SITE];")
        lines.append("")

    lines.append("  //initial")
    lines.append("  for(I=0;I<MAX_SITE;I++)")
    lines.append("  {")
    lines.append("    trimValue[I]=0;")
    lines.append("    trimFinalValue[I]=0;")
    lines.append("")
    if variant == "BISECTION":
        lines.append("    trimDac[I]=dacArray[firstIndex];")
        lines.append("    dacIndex[I]=firstIndex;")
        if adjust is not None:
            lines.append("    dacFinalIndex[I]=firstIndex;")
    else:
        lines.append("    trimDac[I]=dacArray[0];")
    lines.append("")
    lines.append("  }")
    lines.append("")

    if relay != "/":
        lines.append(f"  SET_CBIT({relay}, ON, 5mS);")
    lines.append(f"  POWER_ON({spec.vcc});")
    lines.append("")
    if measurement.family != "FREQUENCY":
        lines.append(f"  RELAY_ON({measurement.pin},PPMU_PDCL,2mS);")
        lines.append("")

    lines.extend(emit_pattern_run(spec.protocol.enter_pattern))


def _render_epilogue(spec: TrimSpec, relay: str, lines: list[str]) -> None:
    """Post-test safety release, power-down, and relay close."""
    _release(lines, spec.measurement)
    lines.append("  POWER_OFF();")
    lines.append("  //POWER_DOWN_FAIL_SITE_X(MODE_B);")
    lines.append("")
    if relay != "/":
        lines.append(f"  SET_CBIT({relay}, OFF, 5mS);")
    lines.append("}")


def render_enter_operation(
    operation: TrimOperation,
    spec: TrimSpec,
    variant: str,
    lines: list[str],
) -> None:
    """ENTER: run the enter-mode pattern once."""
    lines.extend(emit_pattern_run(operation.reference))


def render_run_operation(
    operation: TrimOperation,
    spec: TrimSpec,
    variant: str,
    lines: list[str],
) -> None:
    """RUN: run an external pattern once."""
    lines.extend(emit_pattern_run(operation.reference))


def render_depend_operation(
    operation: TrimOperation,
    spec: TrimSpec,
    variant: str,
    lines: list[str],
) -> None:
    """DEPEND: apply the typed DAC source, then run its bound pattern once."""
    if operation.value_source != "DAC_FINAL":
        raise ValueError(
            f"STANDARD_TRIM DEPEND requires DAC_FINAL, got {operation.value_source!r}"
        )
    if not operation.helper_name or not operation.source_symbol:
        raise ValueError("STANDARD_TRIM DEPEND requires typed helper and source symbol")
    lines.append(f"  {operation.helper_name}({operation.source_symbol});")
    lines.append("")
    lines.extend(emit_pattern_run(operation.reference))


def render_trim_operation(
    operation: TrimOperation,
    spec: TrimSpec,
    variant: str,
    lines: list[str],
) -> None:
    """TRIM: the bisection search loop plus the final DAC write-back."""
    measurement = spec.measurement
    pe_name = _pe_pattern_name(spec)
    helper = _trim_data_helper(spec.dac.pattern_name)

    _force(lines, measurement)

    if variant == "FULL_SCAN":
        _render_full_scan_loop(spec, measurement, pe_name, helper, lines)
    else:
        _render_bisection_loop(spec, measurement, pe_name, helper, lines)

    lines.append(f"  {helper}({spec.dac_final_symbol});")
    lines.append("")
    if pe_name is not None:
        _pe_step(lines, pe_name, "  ", close=False)


def _render_bisection_loop(
    spec: TrimSpec,
    measurement: MeasurementPlan,
    pe_name: str | None,
    helper: str,
    lines: list[str],
) -> None:
    adjust = spec.adjust

    lines.append("  do")
    lines.append("  {")
    lines.append(f"    {helper}(trimDac);")
    lines.append("")
    if pe_name is not None:
        _pe_step(lines, pe_name, "    ", close=False)
    if _is_negative_voltage_measure(measurement):
        _negative_voltage_measure_block(lines, measurement.pin)
    else:
        _measure(lines, measurement)
    if pe_name is not None:
        _pe_step(lines, pe_name, "    ", close=True)
    lines.append("    TEST_NUM++;")
    lines.append(f'    TEST_NO(TEST_NUM);DATALOG_MSG="{spec.item.lower()}_trim";')
    lines.append("    SOCKET_INC(FRZ_OFF)")
    lines.append("    {")
    lines.append(_result_conversion(measurement))
    high = (1 << spec.search.search_bits) - 1
    lines.append(
        f'      JUDGE_VARIABLE(SOCKET,trimDac[SOCKET], 0, {high}, "{spec.item}_dac");'
    )
    low_scan = round(measurement.target - abs(measurement.target * 2), 2)
    high_scan = round(measurement.target + abs(measurement.target * 5), 2)
    lines.append(
        f'      JUDGE_VARIABLE(SOCKET,trimValue[SOCKET], {str(low_scan)}, {str(high_scan)}, "{spec.item}_value");'
    )
    lines.append("")
    lines.append("      if(fabs(trimValue[SOCKET]-trimTar)<fabs(trimFinalValue[SOCKET]-trimTar))")
    lines.append("      {")
    lines.append("        trimFinalValue[SOCKET] = trimValue[SOCKET];")
    lines.append(f"        {spec.dac_final_symbol}[SOCKET] = trimDac[SOCKET];")
    if adjust is not None:
        lines.append("        dacFinalIndex[SOCKET] = dacIndex[SOCKET];")
    lines.append("      }")
    lines.append("")
    lines.append("      if (trimValue[SOCKET] < trimTar)")
    lines.append("      {")
    lines.append("        dacIndex[SOCKET] = dacIndex[SOCKET] + (int)pow((float)2, (float)binAryCyc);")
    lines.append("        trimDac[SOCKET] = dacArray[dacIndex[SOCKET]];")
    lines.append("      }")
    lines.append("")
    lines.append("      else")
    lines.append("      {")
    lines.append("        dacIndex[SOCKET] = dacIndex[SOCKET] - (int)pow((float)2, (float)binAryCyc);")
    lines.append("        trimDac[SOCKET] = dacArray[dacIndex[SOCKET]];")
    lines.append("      }")
    lines.append("")
    lines.append("    }")
    lines.append("")
    lines.append("    binAryCyc-=1;")
    lines.append("")
    lines.append("  }while(binAryCyc>=-1);")
    lines.append("  //fflush(stdout);")
    lines.append("")



def _render_full_scan_loop(
    spec: TrimSpec,
    measurement: MeasurementPlan,
    pe_name: str | None,
    helper: str,
    lines: list[str],
) -> None:
    lines.append("  do")
    lines.append("  {")
    lines.append(f'    sprintf(cycMsg,"{spec.item.lower()}_trim_dac_%d",cyc);')
    lines.append("    cyc++;")
    lines.append(f"    {helper}(trimDac);")
    lines.append("")
    if pe_name is not None:
        _pe_step(lines, pe_name, "    ", close=False)
    if _is_negative_voltage_measure(measurement):
        _negative_voltage_measure_block(lines, measurement.pin)
    else:
        _measure(lines, measurement)
    if pe_name is not None:
        _pe_step(lines, pe_name, "    ", close=True)
    lines.append("    TEST_NUM++;")
    lines.append(f'    TEST_NO(TEST_NUM);DATALOG_MSG="{spec.item.lower()}_trim";')
    lines.append("    SOCKET_INC(FRZ_OFF)")
    lines.append("    {")
    lines.append(_result_conversion(measurement))
    low_scan = round(measurement.target - abs(measurement.target * 2), 2)
    high_scan = round(measurement.target + abs(measurement.target * 5), 2)
    lines.append(
        f"      JUDGE_VARIABLE(SOCKET,trimValue[SOCKET], {low_scan}, {high_scan}, cycMsg);"
    )
    lines.append("")
    lines.append("      if(fabs(trimValue[SOCKET]-trimTar)<fabs(trimFinalValue[SOCKET]-trimTar))")
    lines.append("      {")
    lines.append("        trimFinalValue[SOCKET] = trimValue[SOCKET];")
    lines.append(f"        {spec.dac_final_symbol}[SOCKET] = trimDac[SOCKET];")
    lines.append("      }")
    lines.append("")
    lines.append("      if(cyc<endCyc) trimDac[SOCKET] = dacArray[cyc];")
    lines.append("    }")
    lines.append("")
    lines.append("  }while(cyc<endCyc);")
    lines.append("  //fflush(stdout);")
    lines.append("")


def render_dac_adjust_operation(
    operation: TrimOperation,
    spec: TrimSpec,
    variant: str,
    lines: list[str],
) -> None:
    """DAC_ADJ: re-measure then conditionally step the final DAC and re-write."""
    measurement = spec.measurement
    adjust = spec.adjust
    high = (1 << spec.search.search_bits) - 1
    helper = _trim_data_helper(spec.dac.pattern_name)

    lines.append("  TEST_NUM++;")
    lines.append(f'  TEST_NO(TEST_NUM); DATALOG_MSG="{spec.item.lower()}_trim";')
    lines.append("")
    _force(lines, measurement)
    lines.append(f"  MEAS_V_PPMU({measurement.pin}, 2mS, 16, AVE, 50uS);")
    lines.append("")
    lines.append("  SOCKET_INC(FRZ_OFF)")
    lines.append("  {")
    lines.append(f"    tempValue[SOCKET] = RESULT_PIN(SOCKET, {measurement.pin});")
    lines.append(f"    if(tempValue[SOCKET]{adjust.operator}{str(adjust.threshold)})")
    lines.append("    {")
    if variant == "BISECTION":
        _dac_adjust_apply(lines, spec.dac_final_symbol, adjust.delta)
    else:
        lines.append(f"      {spec.dac_final_symbol}[SOCKET] += {adjust.delta};")
        lines.append(
            f"      if({spec.dac_final_symbol}[SOCKET]<0) "
            f"{spec.dac_final_symbol}[SOCKET]=0;"
        )
        lines.append(
            f"      if({spec.dac_final_symbol}[SOCKET]>{high}) "
            f"{spec.dac_final_symbol}[SOCKET]={high};"
        )
    lines.append("    }")
    lines.append("")
    lines.append(
        f'    JUDGE_VARIABLE(SOCKET,{spec.dac_final_symbol}[SOCKET],0, {high}, "{spec.item}_dac_f");'
    )
    lines.append("  }")
    lines.append("")
    lines.append(f"  {helper}({spec.dac_final_symbol});")
    lines.append("")


def render_judge_operation(
    operation: TrimOperation,
    spec: TrimSpec,
    variant: str,
    lines: list[str],
) -> None:
    """JUDGE: assert the final DAC, the electrical target, then exit FBIST."""
    measurement = spec.measurement
    high = (1 << spec.search.search_bits) - 1
    pe_name = _pe_pattern_name(spec)

    if spec.adjust is None:
        # Without DAC_ADJ the final-DAC assertion belongs to JUDGE.
        lines.append("  TEST_NUM++;")
        lines.append(f'  TEST_NO(TEST_NUM); DATALOG_MSG="{spec.item.lower()}_trim";')
        lines.append("")
        lines.append("  SOCKET_INC(FRZ_OFF)")
        lines.append("  {")
        lines.append(
            f'    JUDGE_VARIABLE(SOCKET,{spec.dac_final_symbol}[SOCKET],0, {high}, "{spec.item}_dac_f");'
        )
        lines.append("  }")
        lines.append("")

    _force(lines, measurement)
    lines.append(f'  DATALOG_MSG="{spec.item}_value_f";')
    _judge(lines, measurement, spec.trim_tar_reference)
    if pe_name is not None:
        _pe_step(lines, pe_name, "  ", close=True)
    lines.extend(emit_pattern_run(spec.protocol.exit_pattern))


def render_export_operation(
    operation: TrimOperation,
    spec: TrimSpec,
    variant: str,
    lines: list[str],
) -> None:
    """EXPORT: copy the final DAC into the declared cross-CP result."""
    if not operation.source_symbol:
        raise ValueError("STANDARD_TRIM EXPORT requires a typed result symbol")
    lines.extend((
        "  for(I=0;I<MAX_SITE;I++)",
        "  {",
        f"    {operation.source_symbol}[I]={spec.dac_final_symbol}[I];",
        "  }",
        "",
    ))


_OPERATION_RENDERERS: dict[
    str, Callable[[TrimOperation, TrimSpec, str, list[str]], None]
] = {
    "ENTER": render_enter_operation,
    "RUN": render_run_operation,
    "DEPEND": render_depend_operation,
    "TRIM": render_trim_operation,
    "DAC_ADJ": render_dac_adjust_operation,
    "JUDGE": render_judge_operation,
    "EXPORT": render_export_operation,
}


def _operation_renderer(
    operation: TrimOperation,
) -> Callable[[TrimOperation, TrimSpec, str, list[str]], None]:
    renderer = _OPERATION_RENDERERS.get(operation.kind)
    if renderer is None:
        raise ValueError(f"STANDARD_TRIM 不支持 operation {operation.kind!r}")
    return renderer


def _func_name(item: str, variant: str = "BISECTION") -> str:
    synthetic = (
        item if item.casefold().endswith("trim") else f"{item}_Trim"
    )
    if variant == "FULL_SCAN":
        synthetic = f"{item}_Dac_Loop"
    return synthetic.title()


def _fmt(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _trim_data_helper(dac_pattern_name: str) -> str:
    return dac_pattern_name.removesuffix("dac") + "trim_data"


def _pe_pattern_name(spec: TrimSpec) -> str | None:
    """Return the flash pattern name when the search erases/programs each point."""
    for action in spec.search.per_point_actions:
        if action.kind in ("ERASE", "PROGRAM"):
            return action.reference
    return None


def _pe_step(lines: list[str], name: str, indent: str, *, close: bool) -> None:
    """Emit the JUDGE_PAT pair that wraps the erase/program around a measure."""
    lines.append(f'{indent}TEST_NO(TEST_NUM);  DATALOG_MSG = "{name}";')
    if close:
        lines.append(f"{indent}JUDGE_PAT({name}:pe_1,__{name});")
    else:
        lines.append(f"{indent}JUDGE_PAT({name},{name}:pe_1);")
    lines.append("")


def _is_negative_voltage_measure(measurement: MeasurementPlan) -> bool:
    """A negative voltage target measures through the commented PMU fallback."""
    return measurement.family == "VOLTAGE" and float(measurement.target) < 0


def _negative_voltage_measure_block(lines: list[str], pin: str) -> None:
    lines.append(f"    //PARAL_INC({pin})")
    lines.append("    //{")
    lines.append("    //RELAY_OFF(PIN_DEFS,PDCL,2mS);")
    lines.append("    //RELAY_ON(PIN_DEFS,PMU,2mS);")
    lines.append("")
    lines.append("    //FORCE_I_PMU(PMU,0uA,@100uA,@12V,6V,ON,3mS);")
    lines.append("    //MEAS_V_PMU(PMU,IFVM,2mS,16,AVE,50uS);")
    lines.append("    //FORCE_I_PMU(PMU,0uA,@100uA,@12V,6V,OFF,3mS);")
    lines.append("")
    lines.append("    //RELAY_OFF(PIN_DEFS,PMU,2mS);")
    lines.append("    //RELAY_ON(PIN_DEFS,PDCL,2mS);")
    lines.append("    //}")
    lines.append("")
    lines.append(f"    MEAS_V_PPMU({pin}, 2mS, 16, AVE, 50uS);")
    lines.append("")


def _dac_adjust_apply(lines: list[str], dac_final_name: str, delta: int) -> None:
    lines.append(f"      dacFinalIndex[SOCKET] += {delta};")
    lines.append("      if(dacFinalIndex[SOCKET]<0) dacFinalIndex[SOCKET] = 0;")
    lines.append(
        "      if(dacFinalIndex[SOCKET]>(int)(sizeof(dacArray)/sizeof(dacArray[0]))-1) "
        "dacFinalIndex[SOCKET] = (int)(sizeof(dacArray)/sizeof(dacArray[0]))-1;"
    )
    lines.append(f"      {dac_final_name}[SOCKET] = dacArray[dacFinalIndex[SOCKET]];")


def _result_conversion(measurement: MeasurementPlan) -> str:
    pin = measurement.pin
    if measurement.family == "FREQUENCY":
        return f"      trimValue[SOCKET] = RESULT_PIN(SOCKET, {pin})/1000; //Khz"
    if measurement.family == "CURRENT":
        return f"      trimValue[SOCKET] = RESULT_PIN(SOCKET, {pin})*1000000; //uA"
    return f"      trimValue[SOCKET] = RESULT_PIN(SOCKET, {pin});"


def _force(lines: list[str], measurement: MeasurementPlan) -> None:
    if measurement.family == "FREQUENCY":
        lines.append(f"  SET_TFTM_MODE({measurement.pin}, SCHMITT_ON);")
        return
    if measurement.family == "CURRENT":
        low = calc_limit(measurement.target, measurement.low_limit, measurement.high_limit, True)
        high = calc_limit(measurement.target, measurement.low_limit, measurement.high_limit, False)
        clamp = _ppmu_i_clamp(measurement.target, measurement.unit, low, high)
        lines.append(
            f"  FORCE_V_PPMU({measurement.pin}, {measurement.force}, ,{clamp}, , 2mS);"
        )
        return
    mag, cur_unit = _parse_force_current(measurement.force)
    clamp = _ppmu_i_clamp(mag, cur_unit)
    lines.append(
        f"  FORCE_I_PPMU({measurement.pin}, {measurement.force}, "
        f"{clamp}, ,6V, -2V ,3mS);"
    )


def _measure(lines: list[str], measurement: MeasurementPlan) -> None:
    pin = measurement.pin
    if measurement.family == "FREQUENCY":
        gate = _freq_gate(measurement.target, measurement.unit)
        lines.append(f"    MEAS_FREQ({pin}, , , , {gate}, , 50mS, );")
    elif measurement.family == "CURRENT":
        lines.append(f"    MEAS_I_PPMU({pin}, 2mS, 16, AVE, 50uS);")
    else:
        lines.append(f"    MEAS_V_PPMU({pin}, 2mS, 16, AVE, 50uS);")


def _freq_gate(target, unit: str) -> str:
    """Select the frequency-measurement gate from the target magnitude and unit.

    Mirrors the golden half-open ladder: each tier is assigned to the next higher
    gate, so a 1 MHz-class signal lands on @5MHZ instead of clipping at @1MHZ.
    """
    magnitude = float(target)
    normalized = str(unit).strip().casefold()
    if normalized == "hz":
        return "@1KHZ"
    if normalized == "khz":
        if magnitude < 1:
            return "@1KHZ"
        if magnitude < 10:
            return "@10KHZ"
        if magnitude < 100:
            return "@100KHZ"
        return "@1MHZ"
    if normalized == "mhz":
        if magnitude < 1:
            return "@1MHZ"
        if magnitude < 5:
            return "@5MHZ"
        if magnitude < 10:
            return "@10MHZ"
        return "@100MHZ"
    raise ValueError("频率单位不支持: " + str(unit))


def _judge(
    lines: list[str],
    measurement: MeasurementPlan,
    trim_tar_reference: str | None = None,
) -> None:
    pin = measurement.pin
    if trim_tar_reference is not None:
        if measurement.family == "VOLTAGE" and float(measurement.target) < 0:
            # Negative supply target: re-force through PPMU after the reference
            # symbol, then judge against the VERSION-declared value ±0.05.
            lines.append(f"  RELAY_ON({pin}, PPMU_PDCL, 2mS);")
            _force(lines, measurement)
        lines.append(
            f"  JUDGE_V_PPMU({pin},{trim_tar_reference}-0.05,"
            f"{trim_tar_reference}+0.05,2mS);"
        )
        lines.append("")
        return
    low = calc_limit(measurement.target, measurement.low_limit, measurement.high_limit, True)
    high = calc_limit(measurement.target, measurement.low_limit, measurement.high_limit, False)
    if measurement.family == "FREQUENCY":
        lines.append(
            f"  JUDGE_FREQ({pin}, , , ,{low}{measurement.unit}, {high}{measurement.unit}, "
            f"{_freq_gate(measurement.target, measurement.unit)}, , 50mS, );"
        )
    elif measurement.family == "CURRENT":
        lines.append(
            f"  JUDGE_I_PPMU({pin}, {low}{measurement.unit}, {high}{measurement.unit}, "
            f"2mS,16,AVE,50uS,,);"
        )
    else:
        lines.append(
            f"  JUDGE_V_PPMU({pin}, {low}{measurement.unit}, {high}{measurement.unit}, "
            f"2mS,16,AVE,50uS,,);"
        )


def _release(lines: list[str], measurement: MeasurementPlan) -> None:
    """Post-test safety release: SCHMITT_OFF for frequency, PPMU teardown otherwise."""
    pin = measurement.pin
    if measurement.family == "FREQUENCY":
        lines.append(f"  SET_TFTM_MODE({pin}, SCHMITT_OFF);")
        lines.append("")
        return
    low = calc_limit(measurement.target, measurement.low_limit, measurement.high_limit, True)
    high = calc_limit(measurement.target, measurement.low_limit, measurement.high_limit, False)
    clamp_v = _ppmu_i_clamp(measurement.target, "uA", low, high)
    lines.append(f"  FORCE_V_PPMU({pin}, 0V, ,{clamp_v}, , 2mS);")
    lines.append(f"  FORCE_I_PPMU({pin}, 0uA, @2uA, ,6V, -2V ,3mS);")
    lines.append(f"  RELAY_OFF({pin}, PPMU_PDCL, 2mS);")


def _parse_force_current(fvalue: str):
    m = _FORCE_CURRENT_RE.match(str(fvalue).strip())
    if not m:
        raise ValueError(
            f"_parse_force_current: 无法解析力流值 '{fvalue}'（需要形如 '-6mA'/'2uA'）"
        )
    return float(m.group(1)), m.group(2)


def _ppmu_i_clamp(magnitude, unit, *other_magnitudes) -> str:
    """Select the PPMU current clamp tier from the force/measure magnitude."""
    scale_to_ua = {"na": 0.001, "ua": 1.0, "ma": 1000.0, "a": 1_000_000.0}
    unit_key = str(unit).strip().lower()
    if unit_key not in scale_to_ua:
        raise ValueError("PPMU 电流单位不支持: " + str(unit))
    magnitude_ua = max(
        abs(float(value)) for value in (magnitude,) + other_magnitudes
    ) * scale_to_ua[unit_key]
    for upper_ua, clamp in (
        (2, "@2uA"),
        (20, "@20uA"),
        (200, "@200uA"),
        (2000, "@2mA"),
        (32000, "@32mA"),
    ):
        if magnitude_ua < upper_ua:
            return clamp
    raise ValueError(
        "PPMU 电流 " + str(magnitude) + str(unit) + " 超出量程上限 32mA"
    )
