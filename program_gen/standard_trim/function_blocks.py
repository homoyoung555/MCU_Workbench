"""Generic STANDARD_TRIM dual-platform function-block rendering.

``render_standard_trim`` consumes ONLY typed facts — the compiled ``TrimSpec``
(canonical Recipe), the canonical
schedule (definition identity / render name / bin), the ``TargetKey`` and the
platform syntax profiles — and returns the TESTS ``SectionFragment`` bytes for
the BISECTION and FULL_SCAN variants on Chroma and S100.  It never reads
workbook or global state and never performs I/O or renderer registration.

- the ``50mS`` measurement settle comes from ``MeasurementContract``;
- no-relay is ``RelayContract.relay is None`` (never ``"/"``);
- helper identities come from ``HelperContract`` (typed contract facts);
- assembly without an explicitly supplied typed Skeleton remains blocked with
  ``SC.SKELETON.UNAVAILABLE``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from program_gen.core.run_pattern import PatternResourceRef
from program_gen.core.dac_adjust import DacAdjustCondition, DacAdjustModulePlan
from program_gen.core.trim_spec import LinearRange, TrimOperation, TrimSpec
from program_gen.core.verify_modules import (
    EnterPlan,
    JudgeDacFinalPlan,
    JudgeMeasurementKind,
    JudgeMeasurementPlan,
    JudgePlan,
)
from program_gen.registered_recipe_modules import NATIVE_RECIPE_MODULE_REGISTRY
from program_gen.render_plan import SectionFragment, TargetKey
from program_gen.standard_trim.contracts import (
    StandardTrimContractError,
    StandardTrimContracts,
    compile_standard_trim_contracts,
)
from program_gen.standard_trim.syntax import ChromaSyntax, S100Syntax, _num


class StandardTrimSliceError(ValueError):
    """A STANDARD_TRIM function-block slice request is invalid or blocked."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


class StandardTrimSkeletonError(StandardTrimSliceError):
    """Assembly was requested without a concrete typed Skeleton."""


@dataclass(frozen=True, slots=True)
class StandardTrimSliceTarget:
    """One target's canonical render identity for the function blocks."""

    definition_identity: str
    render_name: str
    hardware_bin: str


def resolve_slice_target(
    spec: TrimSpec, schedule
) -> StandardTrimSliceTarget:
    """Resolve the canonical definition identity for one typed TrimSpec."""
    definitions = tuple(
        definition
        for definition in schedule.definitions
        if str(definition.cp).strip().casefold() == str(spec.cp).strip().casefold()
        and str(definition.item).strip().casefold() == str(spec.item).strip().casefold()
        and str(definition.source_rows) == f"({spec.flow_row_index + 2},)"
    )
    if len(definitions) != 1:
        raise StandardTrimSliceError(
            "SC.DEFINITION.IDENTITY_UNRESOLVED",
            f"canonical schedule contains {len(definitions)} definitions for "
            f"{spec.cp}/{spec.item} (row {spec.flow_row_index + 2})",
        )
    definition = definitions[0]
    entries = tuple(
        entry
        for entry in schedule.entries
        if str(entry.definition_id).casefold()
        == str(definition.identity).casefold()
    )
    hardware_bin = str(entries[0].bin_binding.hardware_bin) if entries else ""
    return StandardTrimSliceTarget(
        definition_identity=str(definition.identity),
        render_name=str(definition.render_name),
        hardware_bin=hardware_bin,
    )


def render_standard_trim(
    spec: TrimSpec,
    target: TargetKey,
    schedule,
) -> Tuple[SectionFragment, ...]:
    """Return platform TESTS fragments from one fully typed ordinary Trim."""
    platform = str(target.platform).strip().casefold()
    if platform not in ("chroma", "s100"):
        raise StandardTrimSliceError(
            "SC.TARGET.PLATFORM",
            f"unsupported STANDARD_TRIM slice platform {target.platform!r}",
        )
    if str(target.cp).strip().casefold() != str(spec.cp).strip().casefold():
        raise StandardTrimSliceError(
            "SC.TARGET.CP_MISMATCH",
            f"trim spec belongs to {spec.cp!r}, not target {target.cp!r}",
        )
    contracts = compile_standard_trim_contracts(spec)
    if contracts.relay.relay is not None:
        raise StandardTrimSliceError(
            "ST.RELAY.UNSUPPORTED",
            "STANDARD_TRIM relay semantics are not confirmed; non-empty relay "
            "facts cannot enter the native renderer yet",
        )
    slice_target = resolve_slice_target(spec, schedule)
    if platform == "chroma":
        blocks = (
            _chroma_block(spec, contracts, slice_target.render_name,
                          "BISECTION", spec.test_number),
            _chroma_block(spec, contracts, slice_target.render_name,
                          "FULL_SCAN", spec.test_number),
        )
    else:
        blocks = (
            _s100_block(spec, contracts, slice_target, "BISECTION"),
            _s100_block(spec, contracts, slice_target, "FULL_SCAN"),
        )
    return tuple(
        SectionFragment(
            artifact_path=f"{target.program_name}{_program_extension(platform)}",
            section="TESTS",
            identity=(
                f"standard-trim:{target.identity}:{slice_target.definition_identity}"
                f":{variant}"
            ),
            content=content,
            order=ordinal,
        )
        for ordinal, (variant, content) in enumerate(
            (("BISECTION", blocks[0]), ("FULL_SCAN", blocks[1]))
        )
    )


def request_assembly(
    spec: TrimSpec,
    target: TargetKey,
    schedule,
) -> None:
    """Block any assembly of STANDARD_TRIM slices.

    This compatibility entry point has no Skeleton input.  The typed assembly
    bridge lives in ``standard_trim.assembly`` and requires an explicit
    ``SkeletonProducer`` plus platform facts.
    """
    render_standard_trim(spec, target, schedule)
    raise StandardTrimSkeletonError(
        "SC.SKELETON.UNAVAILABLE",
        "STANDARD_TRIM assembly requires an explicit typed SkeletonProducer "
        "and platform skeleton facts",
    )


# ---------------------------------------------------------------------------
# Chroma function blocks.
# ---------------------------------------------------------------------------


def _chroma_block(
    spec: TrimSpec,
    contracts: StandardTrimContracts,
    render_name: str,
    variant: str,
    test_number: int,
) -> str:
    declared = tuple(item.kind for item in spec.search.variants)
    if variant not in declared:
        raise StandardTrimSliceError(
            "SC.VARIANT.UNDECLARED",
            f"STANDARD_TRIM variant {variant!r} is not declared; "
            f"expected {declared!r}",
        )
    syntax = ChromaSyntax()
    measurement = contracts.measurement
    relay = contracts.relay.relay
    helpers = contracts.helpers
    lines: list[str] = []

    # Function header / datalog identity / declarations.
    lines.append(syntax.function_header(_variant_render_name(render_name, variant)))
    lines.append(syntax.function_open())
    lines.append(syntax.test_num(test_number))
    message = (
        f"{spec.item.lower()}_trim"
        if variant == "BISECTION"
        else f"{spec.item.lower()}_dac_loop"
    )
    lines.append(syntax.datalog_msg(message))
    lines.append("")
    lines.append(
        f"  double trimTar={spec.trim_tar_reference or _num(measurement.target)};"
    )
    lines.append("")
    lines.append("  double trimValue[MAX_SITE],trimFinalValue[MAX_SITE];")
    lines.append("  int trimDac[MAX_SITE];")
    if spec.adjust is not None:
        lines.append("")
        lines.append("  double tempValue[MAX_SITE];")
    lines.append("")
    domain = _variant_domain(spec, variant)
    linear = isinstance(domain, LinearRange)
    if not linear:
        codes = spec.search.codes
        lines.append(
            f"  int dacArray[{len(codes)}]={{{','.join(str(code) for code in codes)}}};"
        )
    if variant == "BISECTION":
        if not linear:
            lines.append("  int dacIndex[MAX_SITE];")
            lines.append("  int firstIndex=sizeof(dacArray)/sizeof(dacArray[0])/2;")
        lines.append(f"  int binAryCyc={spec.search.search_bits - 2};")
        if spec.adjust is not None and not linear:
            lines.append("")
            lines.append("  int dacFinalIndex[MAX_SITE];")
    else:
        lines.append("  int cyc=0;")
        lines.append(f"  int endCyc={_domain_count(domain)};")
        lines.append("  char cycMsg[48];")
    lines.append("")
    lines.append("  //initial")
    lines.append("  for(I=0;I<MAX_SITE;I++)")
    lines.append("  {")
    lines.append("    trimValue[I]=0;")
    lines.append("    trimFinalValue[I]=0;")
    lines.append("")
    if variant == "BISECTION":
        if linear:
            lines.append(f"    trimDac[I]={_linear_value(domain, domain.count // 2)};")
        else:
            lines.append("    trimDac[I]=dacArray[firstIndex];")
            lines.append("    dacIndex[I]=firstIndex;")
        if spec.adjust is not None and not linear:
            lines.append("    dacFinalIndex[I]=firstIndex;")
    else:
        lines.append(
            f"    trimDac[I]={domain.start if linear else 'dacArray[0]'};"
        )
    lines.append("")
    lines.append("  }")
    lines.append("")
    if relay is not None:
        lines.append(syntax.relay_on(relay))
    lines.append(syntax.power_on(contracts.power.rail))
    lines.append("")
    if measurement.family != "FREQUENCY":
        lines.append(syntax.ppmu_relay_on(measurement.pin))
        lines.append("")
    lines.extend(syntax.pattern_run(contracts.fbist.enter_pattern))

    for operation in spec.operations:
        _chroma_operation(spec, contracts, variant, operation, lines)

    # Protocol epilogue wraps the Recipe; JUDGE does not own FBIST exit.
    lines.extend(syntax.pattern_run(contracts.fbist.exit_pattern))
    if measurement.family == "FREQUENCY":
        lines.append(syntax.frequency_release(measurement.pin))
        lines.append("")
    else:
        judge = _shared_judge_plan(spec, contracts).measurement
        lines.extend(syntax.ppmu_release(
            measurement.pin, measurement.family, judge.requires_zero_reset
        ))
    lines.append(syntax.power_off())
    lines.append(syntax.power_down_fail_comment())
    lines.append("")
    lines.append(syntax.function_close())
    return "\n".join(lines) + "\n"


def _chroma_operation(
    spec: TrimSpec,
    contracts: StandardTrimContracts,
    variant: str,
    operation,
    lines: list[str],
) -> None:
    syntax = ChromaSyntax()
    kind = operation.kind
    if kind == "ENTER":
        lines.extend(NATIVE_RECIPE_MODULE_REGISTRY.emit(
            "ENTER", _shared_enter_plan(operation.reference), "chroma"
        ).statements)
        return
    if kind == "RUN":
        lines.extend(syntax.pattern_run(operation.reference))
        return
    if kind == "DEPEND":
        lines.extend(syntax.pattern_run(operation.reference))
        return
    if kind == "TRIM":
        _chroma_trim(spec, contracts, variant, lines)
        return
    if kind == "DAC_ADJ":
        _chroma_adjust(spec, contracts, variant, lines)
        return
    if kind == "JUDGE":
        _chroma_judge(spec, contracts, lines)
        return
    if kind == "EXPORT":
        lines.extend((
            "  for(I=0;I<MAX_SITE;I++)",
            "  {",
            f"    {operation.source_symbol}[I]={spec.dac_final_symbol}[I];",
            "  }",
            "",
        ))
        return
    raise StandardTrimSliceError(
        "SC.OPERATION.UNSUPPORTED",
        f"STANDARD_TRIM chroma slice does not support operation {kind!r}",
    )


def _chroma_trim(
    spec: TrimSpec,
    contracts: StandardTrimContracts,
    variant: str,
    lines: list[str],
) -> None:
    syntax = ChromaSyntax()
    measurement = contracts.measurement
    helpers = contracts.helpers
    domain = _variant_domain(spec, variant)
    linear = isinstance(domain, LinearRange)
    lines.append(syntax.measurement_force(
        measurement.family, measurement.pin, measurement.force
    ))
    lines.append("  do")
    lines.append("  {")
    if variant == "FULL_SCAN":
        lines.append(f'    sprintf(cycMsg,"{spec.item.lower()}_trim_dac_%d",cyc);')
        lines.append("    cyc++;")
    lines.append(syntax.helper_call_loop(helpers.trim_data_helper))
    lines.append("")
    lines.append(
        syntax.measure(
            measurement.family, measurement.pin, measurement.freq_gate,
            _settle_text(measurement)
        )
    )
    lines.append("    TEST_NUM++;")
    lines.append(f'    TEST_NO(TEST_NUM);DATALOG_MSG="{spec.item.lower()}_trim";')
    lines.append(syntax.socket_inc_open())
    lines.append(syntax.socket_inc_body_open())
    lines.append(syntax.result(measurement.family, measurement.pin))
    high = (1 << spec.search.search_bits) - 1
    if variant == "BISECTION":
        lines.append(
            syntax.judge_variable(
                "trimDac[SOCKET]", 0, high, f"{spec.item}_dac"
            )
        )
        lines.append(
            syntax.judge_variable(
                "trimValue[SOCKET]",
                _round(measurement.search_limit_low),
                _round(measurement.search_limit_high),
                f"{spec.item}_value",
            )
        )
    else:
        lines.append(
            syntax.judge_variable(
                "trimValue[SOCKET]",
                _round(measurement.search_limit_low),
                _round(measurement.search_limit_high),
                "cycMsg",
                quoted=False,
            )
        )
    lines.append("")
    lines.append("      if(fabs(trimValue[SOCKET]-trimTar)<fabs(trimFinalValue[SOCKET]-trimTar))")
    lines.append("      {")
    lines.append("        trimFinalValue[SOCKET] = trimValue[SOCKET];")
    lines.append(
        f"        {helpers.dac_final_symbol}[SOCKET] = trimDac[SOCKET];"
    )
    if spec.adjust is not None and variant == "BISECTION" and not linear:
        lines.append("        dacFinalIndex[SOCKET] = dacIndex[SOCKET];")
    lines.append("      }")
    lines.append("")
    if variant == "BISECTION":
        lines.append("      if (trimValue[SOCKET] < trimTar)")
        lines.append("      {")
        if linear:
            lines.append(
                "        trimDac[SOCKET] = trimDac[SOCKET] + "
                f"{_linear_bisection_delta(domain)};"
            )
        else:
            lines.append("        dacIndex[SOCKET] = dacIndex[SOCKET] + (int)pow((float)2, (float)binAryCyc);")
            lines.append("        trimDac[SOCKET] = dacArray[dacIndex[SOCKET]];")
        lines.append("      }")
        lines.append("")
        lines.append("      else")
        lines.append("      {")
        if linear:
            lines.append(
                "        trimDac[SOCKET] = trimDac[SOCKET] - "
                f"{_linear_bisection_delta(domain)};"
            )
        else:
            lines.append("        dacIndex[SOCKET] = dacIndex[SOCKET] - (int)pow((float)2, (float)binAryCyc);")
            lines.append("        trimDac[SOCKET] = dacArray[dacIndex[SOCKET]];")
        lines.append("      }")
        lines.append("")
    else:
        if linear:
            lines.append(
                "      if(cyc<endCyc) trimDac[SOCKET] = "
                f"{_linear_value(domain, 'cyc')};"
            )
        else:
            lines.append("      if(cyc<endCyc) trimDac[SOCKET] = dacArray[cyc];")
    lines.append("    }")
    lines.append("")
    if variant == "BISECTION":
        lines.append("    binAryCyc-=1;")
        lines.append("")
        lines.append("  }while(binAryCyc>=-1);")
    else:
        lines.append("  }while(cyc<endCyc);")
    lines.append("  //fflush(stdout);")
    lines.append("")
    lines.append(
        syntax.helper_call(helpers.trim_data_helper, helpers.dac_final_symbol)
    )
    lines.append("")


def _chroma_judge(
    spec: TrimSpec,
    contracts: StandardTrimContracts,
    lines: list[str],
) -> None:
    lines.extend(NATIVE_RECIPE_MODULE_REGISTRY.emit(
        "JUDGE", _shared_judge_plan(spec, contracts), "chroma"
    ).statements)


def _chroma_adjust(
    spec: TrimSpec,
    contracts: StandardTrimContracts,
    variant: str,
    lines: list[str],
) -> None:
    adjustment = _dac_adjust_plan(spec)
    if adjustment is None:
        return
    syntax = ChromaSyntax()
    measurement = contracts.measurement
    helpers = contracts.helpers
    high = (1 << spec.search.search_bits) - 1
    final = helpers.dac_final_symbol
    domain = _variant_domain(spec, variant)
    linear = isinstance(domain, LinearRange)
    lines.append("  TEST_NUM++;")
    lines.append(f'  TEST_NO(TEST_NUM); DATALOG_MSG="{spec.item.lower()}_trim";')
    lines.append("")
    lines.append(syntax.measurement_force(
        measurement.family, measurement.pin, measurement.force
    ))
    lines.append(syntax.measure(
        measurement.family, measurement.pin, measurement.freq_gate,
        _settle_text(measurement)
    ).replace("    ", "  ", 1))
    lines.append("")
    lines.append("  SOCKET_INC(FRZ_OFF)")
    lines.append("  {")
    lines.append(f"    tempValue[SOCKET] = RESULT_PIN(SOCKET, {measurement.pin});")
    lines.append(
        f"    if(tempValue[SOCKET]{adjustment.condition.operator}{_num(adjustment.condition.threshold)})"
    )
    lines.append("    {")
    if variant == "BISECTION":
        if linear:
            lines.append(
                f"      {final}[SOCKET] += {_linear_adjustment_delta(domain, adjustment.delta)};"
            )
            lines.append(
                f"      if({final}[SOCKET]<{domain.start}) {final}[SOCKET] = {domain.start};"
            )
            lines.append(
                f"      if({final}[SOCKET]>{domain.stop}) {final}[SOCKET] = {domain.stop};"
            )
        else:
            lines.append(f"      dacFinalIndex[SOCKET] += {adjustment.delta};")
            lines.append("      if(dacFinalIndex[SOCKET]<0) dacFinalIndex[SOCKET] = 0;")
            lines.append("      if(dacFinalIndex[SOCKET]>(int)(sizeof(dacArray)/sizeof(dacArray[0]))-1) dacFinalIndex[SOCKET] = (int)(sizeof(dacArray)/sizeof(dacArray[0]))-1;")
            lines.append(f"      {final}[SOCKET] = dacArray[dacFinalIndex[SOCKET]];")
    else:
        lines.append(f"      {final}[SOCKET] += {adjustment.delta};")
        lines.append(f"      if({final}[SOCKET]<0) {final}[SOCKET] = 0;")
        lines.append(f"      if({final}[SOCKET]>{high}) {final}[SOCKET] = {high};")
    lines.append("    }")
    lines.append("")
    lines.append(syntax.judge_variable_final(
        f"{final}[SOCKET]", 0, high, f"{spec.item}_dac_f"
    ))
    lines.append("  }")
    lines.append("")
    lines.append(syntax.helper_call(helpers.trim_data_helper, final))
    lines.append("")


# ---------------------------------------------------------------------------
# S100 function blocks.
# ---------------------------------------------------------------------------


def _s100_block(
    spec: TrimSpec,
    contracts: StandardTrimContracts,
    slice_target: StandardTrimSliceTarget,
    variant: str,
) -> str:
    _validate_s100_recipe(spec)
    declared = tuple(item.kind for item in spec.search.variants)
    if variant not in declared:
        raise StandardTrimSliceError(
            "SC.VARIANT.UNDECLARED",
            f"STANDARD_TRIM variant {variant!r} is not declared; "
            f"expected {declared!r}",
        )
    syntax = S100Syntax()
    measurement = contracts.measurement
    helpers = contracts.helpers
    render_name = _variant_render_name(slice_target.render_name, variant)
    lines: list[str] = []
    domain = _variant_domain(spec, variant)
    linear = isinstance(domain, LinearRange)

    lines.extend(syntax.plan_header(render_name))
    trim_target = (
        f"_C_{spec.trim_tar_reference}"
        if spec.trim_tar_reference else _num(measurement.target)
    )
    lines.append(f"\tdouble trimTar={trim_target};")
    lines.append("")
    lines.append("\tdouble trimFinalValue[MAX_SITE];")
    lines.append("\tint trimDac[MAX_SITE];")
    lines.append("")
    if not linear:
        codes = spec.search.codes
        lines.append(
            f"\tint dacArray[{len(codes)}]={{{','.join(str(code) for code in codes)}}};"
        )
    if variant == "BISECTION":
        if not linear:
            lines.append("\tint dacIndex[MAX_SITE];")
            lines.append("\tint firstIndex=sizeof(dacArray)/sizeof(dacArray[0])/2;")
        lines.append(f"\tint binAryCyc = {spec.search.search_bits - 2};")
        if spec.adjust is not None and not linear:
            lines.append("")
            lines.append("\tint dacFinalIndex[MAX_SITE];")
    else:
        lines.append("\tint cyc=0;")
        lines.append(f"\tint endCyc={_domain_count(domain)};")
    lines.append("")
    lines.append("\t//initial")
    lines.append("\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)")
    lines.append("\t{")
    if variant == "BISECTION":
        if linear:
            initial = _linear_value(domain, domain.count // 2)
            lines.append(f"\t\tGB[1+T_SOCKET*64]={initial}; // trimDac = GB2")
            lines.append(f"\t\ttrimDac[T_SOCKET]={initial};")
        else:
            lines.append("\t\tGB[1+T_SOCKET*64]=dacArray[firstIndex]; // trimDac = GB2")
            lines.append("\t\ttrimDac[T_SOCKET]=dacArray[firstIndex];")
            lines.append("\t\tdacIndex[T_SOCKET]=firstIndex;")
        if spec.adjust is not None and not linear:
            lines.append("\t\tdacFinalIndex[T_SOCKET]=firstIndex;")
    else:
        initial = domain.start if linear else "dacArray[0]"
        lines.append(f"\t\tGB[1+T_SOCKET*64]={initial}; // trimDac = GB2")
        lines.append(f"\t\ttrimDac[T_SOCKET]={initial};")
    lines.append("\t\tGB[2+T_SOCKET*64]=0; // trimValue = GB3")
    lines.append("\t\tGB[3+T_SOCKET*64]=0; // trimFinalDac = GB4")
    lines.append("\t\ttrimFinalValue[T_SOCKET]=0.0;")
    lines.append("\t}")
    lines.append("")
    lines.append(syntax.power_on(contracts.power.rail))
    lines.append("")
    lines.append(syntax.pattern_run_protocol(contracts.fbist.enter_pattern))
    lines.append("")
    for operation in spec.operations:
        _s100_operation(spec, contracts, variant, operation, lines)
    lines.append(syntax.pattern_run_exit(contracts.fbist.exit_pattern))
    lines.append("")
    if measurement.family != "FREQUENCY":
        judge = _shared_judge_plan(spec, contracts).measurement
        lines.extend(syntax.ppmu_release(
            measurement.pin, measurement.family, judge.requires_zero_reset
        ))
    lines.append(syntax.power_off())
    lines.append("")
    footer = list(syntax.plan_footer())
    footer[2] = footer[2].format(bin=slice_target.hardware_bin)
    lines.extend(footer)
    return "\n".join(lines) + "\n"


def _s100_operation(
    spec: TrimSpec,
    contracts: StandardTrimContracts,
    variant: str,
    operation: TrimOperation,
    lines: list[str],
) -> None:
    syntax = S100Syntax()
    if operation.kind == "ENTER":
        lines.extend(NATIVE_RECIPE_MODULE_REGISTRY.emit(
            "ENTER", _shared_enter_plan(operation.reference), "s100"
        ).statements)
    elif operation.kind == "RUN":
        lines.append(syntax.pattern_run_enter(operation.reference))
        lines.append("")
    elif operation.kind == "DEPEND":
        lines.append(syntax.pattern_run_depend(operation.reference))
        lines.append("")
    elif operation.kind == "TRIM":
        _s100_trim(spec, contracts, variant, lines)
    elif operation.kind == "DAC_ADJ":
        _s100_adjust(spec, contracts, variant, lines)
    elif operation.kind == "JUDGE":
        _s100_judge(spec, contracts, lines)
    elif operation.kind == "EXPORT":
        lines.extend((
            "\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)",
            "\t{",
            f"\t\t{operation.source_symbol}[T_SOCKET]={spec.dac_final_symbol}[T_SOCKET];",
            "\t}",
            "",
        ))
    else:
        raise StandardTrimSliceError(
            "SC.OPERATION.UNSUPPORTED",
            f"STANDARD_TRIM s100 slice does not support {operation.kind!r}",
        )


def _s100_trim(
    spec: TrimSpec,
    contracts: StandardTrimContracts,
    variant: str,
    lines: list[str],
) -> None:
    syntax = S100Syntax()
    measurement = contracts.measurement
    helpers = contracts.helpers
    domain = _variant_domain(spec, variant)
    linear = isinstance(domain, LinearRange)
    lines.extend(syntax.measurement_force(
        measurement.family, measurement.pin, measurement.force
    ))
    lines.append("\tdo")
    lines.append("\t{")
    if variant == "FULL_SCAN":
        log_stem = str(spec.item).split("Trim")[0].lower().rstrip("_")
        lines.append(
            f'\t\tsprintf(_C_{log_stem.upper()}_LOG_MSG, "{log_stem}_dac_%d", trimDac);'
        )
        lines.append("\t\tcyc++;")
    lines.append(syntax.helper_call_loop(helpers.trim_data_helper))
    lines.append("")
    lines.extend(syntax.measurement(
        measurement.family, measurement.pin, _settle_text(measurement), indent="\t\t"
    ))
    if measurement.family != "VOLTAGE":
        lines.append("")
    if variant == "FULL_SCAN":
        log_stem = str(spec.item).split("Trim")[0].lower().rstrip("_")
        lines.append(
            syntax.compare_value_point(f"_C_{log_stem.upper()}_LOG_MSG",
                                       measurement.unit).replace("\t", "\t\t", 1)
        )
        lines.append("")
    lines.append("\t\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)")
    lines.append("\t\t{")
    lines.append("\t\t\tif(Sys_ActiveSite[T_SOCKET]==0)continue;")
    if variant == "BISECTION":
        lines.append("\t\t\tif(fabs(GB[2+T_SOCKET*64]-trimTar)<fabs(trimFinalValue[T_SOCKET]-trimTar))")
        lines.append("\t\t\t{")
        lines.append("\t\t\t\ttrimFinalValue[T_SOCKET] = GB[2+T_SOCKET*64];")
        lines.append(
            f"\t\t\t\t{helpers.dac_final_symbol}[T_SOCKET] = "
            f"{'trimDac[T_SOCKET]' if linear else 'dacArray[dacIndex[T_SOCKET]]'};"
        )
        if spec.adjust is not None and not linear:
            lines.append("\t\t\t\tdacFinalIndex[T_SOCKET] = dacIndex[T_SOCKET];")
        lines.append("\t\t\t}")
        lines.append("")
        lines.append("\t\t\tif (GB[2+T_SOCKET*64]<trimTar)")
        lines.append("\t\t\t{")
        if linear:
            lines.append(
                "\t\t\t\ttrimDac[T_SOCKET] = trimDac[T_SOCKET] + "
                f"{_linear_bisection_delta(domain)};"
            )
        else:
            lines.append("\t\t\t\tdacIndex[T_SOCKET] = dacIndex[T_SOCKET] + (int)pow((float)2, (float)binAryCyc);")
            lines.append("\t\t\t\ttrimDac[T_SOCKET] = dacArray[dacIndex[T_SOCKET]];")
        lines.append("\t\t\t}")
        lines.append("")
        lines.append("\t\t\telse")
        lines.append("\t\t\t{")
        if linear:
            lines.append(
                "\t\t\t\ttrimDac[T_SOCKET] = trimDac[T_SOCKET] - "
                f"{_linear_bisection_delta(domain)};"
            )
        else:
            lines.append("\t\t\t\tdacIndex[T_SOCKET] = dacIndex[T_SOCKET] - (int)pow((float)2, (float)binAryCyc);")
            lines.append("\t\t\t\ttrimDac[T_SOCKET] = dacArray[dacIndex[T_SOCKET]];")
        lines.append("\t\t\t}")
        lines.append("")
    else:
        lines.append("\t\t\tif(fabs(GB[2+T_SOCKET*64]-trimTar)<fabs(trimFinalValue[T_SOCKET]-trimTar))")
        lines.append("\t\t\t{")
        lines.append("\t\t\t\ttrimFinalValue[T_SOCKET] = GB[2+T_SOCKET*64];")
        lines.append(
            f"\t\t\t\t{helpers.dac_final_symbol}[T_SOCKET] = trimDac[T_SOCKET];"
        )
        lines.append("\t\t\t}")
        lines.append("")
        if linear:
            lines.append(
                "\t\t\tif(cyc<endCyc) trimDac[T_SOCKET] = "
                f"{_linear_value(domain, 'cyc')};"
            )
        else:
            lines.append("\t\t\tif(cyc<endCyc) trimDac[T_SOCKET] = dacArray[cyc];")
    lines.append("\t\t}")
    lines.append("")
    if variant == "BISECTION":
        lines.append("\t\tbinAryCyc-=1;")
        lines.append("")
        lines.append("\t}while(binAryCyc>=-1);")
    else:
        lines.append("\t}while(cyc<endCyc);")
    lines.append("")
    lines.append(
        syntax.helper_call(helpers.trim_data_helper, helpers.dac_final_symbol)
    )
    lines.append("")


def _s100_judge(
    spec: TrimSpec,
    contracts: StandardTrimContracts,
    lines: list[str],
) -> None:
    lines.extend(NATIVE_RECIPE_MODULE_REGISTRY.emit(
        "JUDGE", _shared_judge_plan(spec, contracts), "s100"
    ).statements)


def _s100_adjust(
    spec: TrimSpec,
    contracts: StandardTrimContracts,
    variant: str,
    lines: list[str],
) -> None:
    adjustment = _dac_adjust_plan(spec)
    if adjustment is None:
        return
    syntax = S100Syntax()
    measurement = contracts.measurement
    final = contracts.helpers.dac_final_symbol
    high = (1 << spec.search.search_bits) - 1
    domain = _variant_domain(spec, variant)
    linear = isinstance(domain, LinearRange)
    lines.extend(syntax.measurement_force(
        measurement.family, measurement.pin, measurement.force
    ))
    lines.extend(syntax.measurement(
        measurement.family, measurement.pin, _settle_text(measurement), indent="\t"
    ))
    lines.append("\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)")
    lines.append("\t{")
    lines.append("\t\tif(Sys_ActiveSite[T_SOCKET]==0)continue;")
    lines.append(
        f"\t\tif(GB[2+T_SOCKET*64]{adjustment.condition.operator}{_num(adjustment.condition.threshold)})"
    )
    lines.append("\t\t{")
    if variant == "BISECTION":
        if linear:
            lines.append(
                f"\t\t\t{final}[T_SOCKET] += {_linear_adjustment_delta(domain, adjustment.delta)};"
            )
            lines.append(
                f"\t\t\tif({final}[T_SOCKET]<{domain.start}) {final}[T_SOCKET] = {domain.start};"
            )
            lines.append(
                f"\t\t\tif({final}[T_SOCKET]>{domain.stop}) {final}[T_SOCKET] = {domain.stop};"
            )
        else:
            lines.append(f"\t\t\tdacFinalIndex[T_SOCKET] += {adjustment.delta};")
            lines.append("\t\t\tif(dacFinalIndex[T_SOCKET]<0) dacFinalIndex[T_SOCKET] = 0;")
            lines.append("\t\t\tif(dacFinalIndex[T_SOCKET]>(int)(sizeof(dacArray)/sizeof(dacArray[0]))-1) dacFinalIndex[T_SOCKET] = (int)(sizeof(dacArray)/sizeof(dacArray[0]))-1;")
            lines.append(f"\t\t\t{final}[T_SOCKET] = dacArray[dacFinalIndex[T_SOCKET]];")
    else:
        lines.append(f"\t\t\t{final}[T_SOCKET] += {adjustment.delta};")
        lines.append(f"\t\t\tif({final}[T_SOCKET]<0) {final}[T_SOCKET] = 0;")
        lines.append(f"\t\t\tif({final}[T_SOCKET]>{high}) {final}[T_SOCKET] = {high};")
    lines.append("\t\t}")
    lines.append("")
    lines.append("\t}")
    lines.append("")
    lines.append(syntax.helper_call(contracts.helpers.trim_data_helper, final))
    lines.append("")


def _validate_s100_recipe(spec: TrimSpec) -> None:
    """Refuse Recipe shapes the first S100 slice cannot compose yet."""
    kinds = tuple(operation.kind for operation in spec.operations)
    unsupported = tuple(
        kind for kind in kinds
        if kind not in (
            "ENTER", "RUN", "DEPEND", "TRIM", "DAC_ADJ", "JUDGE", "EXPORT"
        )
    )
    if unsupported:
        raise StandardTrimSliceError(
            "SC.OPERATION.UNSUPPORTED",
            f"STANDARD_TRIM s100 slice does not support {unsupported!r}",
        )
    if kinds.count("TRIM") != 1 or kinds.count("JUDGE") != 1:
        raise StandardTrimSliceError(
            "SC.OPERATION.SHAPE_UNSUPPORTED",
            "STANDARD_TRIM s100 first slice requires exactly one TRIM and one JUDGE",
        )
    if kinds.index("TRIM") > kinds.index("JUDGE"):
        raise StandardTrimSliceError(
            "SC.OPERATION.ORDER",
            "STANDARD_TRIM s100 Recipe must place TRIM before JUDGE",
        )
    adjustment_count = kinds.count("DAC_ADJ")
    expected_adjustment_count = 1 if spec.adjust is not None else 0
    if adjustment_count != expected_adjustment_count:
        raise StandardTrimSliceError(
            "SC.OPERATION.SHAPE_UNSUPPORTED",
            "STANDARD_TRIM s100 Recipe DAC_ADJ operation must match its typed "
            "adjustment contract",
        )
    if adjustment_count:
        trim_index = kinds.index("TRIM")
        adjustment_index = kinds.index("DAC_ADJ")
        judge_index = kinds.index("JUDGE")
        if not trim_index < adjustment_index < judge_index:
            raise StandardTrimSliceError(
                "SC.OPERATION.ORDER",
                "STANDARD_TRIM s100 Recipe must place DAC_ADJ between TRIM "
                "and JUDGE",
            )


# ---------------------------------------------------------------------------
# Small helpers.
# ---------------------------------------------------------------------------


def _shared_enter_plan(pattern: str) -> EnterPlan:
    return EnterPlan(PatternResourceRef(
        pattern,
        f"pattern:{pattern}",
        ("START", "END"),
    ))


def _shared_judge_plan(
    spec: TrimSpec,
    contracts: StandardTrimContracts,
) -> JudgePlan:
    measurement = contracts.measurement
    return JudgePlan(
        item=spec.item,
        measurement=JudgeMeasurementPlan(
            kind=JudgeMeasurementKind(measurement.family),
            pin=measurement.pin,
            force=measurement.force,
            low_limit=measurement.limit_low,
            high_limit=measurement.limit_high,
            unit=measurement.unit,
            gate=measurement.freq_gate,
            settle=_settle_text(measurement),
            alias=f"{spec.item}_value_f",
        ),
        dac_final=JudgeDacFinalPlan(
            symbol=contracts.helpers.dac_final_symbol,
            max_code=(1 << spec.search.search_bits) - 1,
            alias=f"{spec.item}_dac_f",
        ),
    )


def _domain_count(domain) -> int:
    return domain.count if isinstance(domain, LinearRange) else len(domain.codes)


def _variant_domain(spec: TrimSpec, variant: str):
    if str(variant).strip().upper() == "FULL_SCAN":
        return LinearRange(0, (1 << spec.search.search_bits) - 1)
    return spec.search.domain


def _linear_value(domain: LinearRange, index: int | str) -> str:
    """Render the DAC code at a linear-domain index without materializing it."""
    if isinstance(index, int):
        return str(domain.start + domain.step * index)
    if domain.start == 0 and domain.step == 1:
        return index
    if domain.step == 1:
        return f"{domain.start}+{index}"
    return f"{domain.start}+{domain.step}*{index}"


def _linear_bisection_delta(domain: LinearRange) -> str:
    base = "(int)pow((float)2, (float)binAryCyc)"
    return base if domain.step == 1 else f"{domain.step}*{base}"


def _linear_adjustment_delta(domain: LinearRange, delta: int) -> int:
    """DAC_ADJ moves an old array index, hence a linear code moves by step."""
    return domain.step * delta


def _dac_adjust_plan(spec: TrimSpec) -> DacAdjustModulePlan | None:
    """Project the existing trim adjustment onto the shared DAC_ADJ contract."""
    adjustment = spec.adjust
    if adjustment is None:
        return None
    return DacAdjustModulePlan(
        DacAdjustCondition(
            "MEASUREMENT", spec.measurement.unit, adjustment.operator,
            adjustment.threshold,
        ),
        spec.dac_final_symbol,
        spec.search.codes,
        adjustment.delta,
    )


def _program_extension(platform: str) -> str:
    return ".pln" if platform == "chroma" else ".prg"


def _variant_render_name(render_name: str, variant: str) -> str:
    if str(variant).strip().upper() == "FULL_SCAN":
        return str(render_name).split("Trim")[0] + "Dac_Loop"
    return str(render_name)


def _settle_text(measurement) -> str:
    return (
        f"{measurement.sample_timeout_value}"
        f"{measurement.sample_timeout_unit}"
    )


def _round(value) -> str:
    rounded = round(value, 2)
    if isinstance(rounded, float) and rounded.is_integer():
        return str(int(rounded))
    return str(rounded)


__all__ = [
    "StandardTrimSliceError",
    "StandardTrimSliceTarget",
    "StandardTrimSkeletonError",
    "request_assembly",
    "resolve_slice_target",
    "render_standard_trim",
]
