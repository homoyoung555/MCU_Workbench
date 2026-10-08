"""STANDARD_VERIFY plans to native assembly without workbook access."""

from dataclasses import replace

from program_gen.registered_recipe_modules import NATIVE_RECIPE_MODULE_REGISTRY
from program_gen.core.fbist_pattern_plan import compile_fbist_writable_field_catalog
from program_gen.core.verify_modules import JudgeMeasurementKind
from program_gen.recipe_module_registry import RecipeModuleEmission
from program_gen.render_plan import (
    ProgramContribution,
    RenderSymbolRef,
    ScheduleEntryContribution,
    SectionFragment,
    SymbolRequirement,
    TestDefinitionContribution,
)
from program_gen.skeleton import SkeletonBody
from program_gen.typed_kind_registry import TypedKindAssembly, TypedKindContext


def compile_standard_verify_assembly(plans, context: TypedKindContext) -> TypedKindAssembly:
    plans = tuple(plans)
    if not plans:
        return TypedKindAssembly("STANDARD_VERIFY")
    context.compilation.require_success()
    target = context.target
    platform = target.platform.casefold()
    if platform not in ("chroma", "s100"):
        raise ValueError(f"TK.STANDARD_VERIFY.PLATFORM: {target.platform!r}")
    schedule = context.compilation.for_cp(target.cp).canonical_schedule
    contributions = []
    bodies = []
    for plan in plans:
        definition = next(
            item for item in schedule.definitions
            if item.cp.casefold() == plan.cp.casefold()
            and plan.excel_row in item.source_rows
        )
        entry = next(
            item for item in schedule.entries
            if item.definition_id == definition.identity
        )
        ordinal = next(
            index for index, item in enumerate(schedule.entries)
            if item.identity == entry.identity
        )
        if plan.shmoo is None:
            emissions = [_emit_run(plan.protocol_enter, platform)]
            for step in plan.steps:
                emissions.extend(_emit_step(step, platform))
            emissions.append(_emit_run(plan.protocol_exit, platform))
            point_emissions = ()
        else:
            enter_target, swd_pin = _shmoo_enter_facts(plan, context)
            point_emissions = tuple(
                _emit_shmoo_point(
                    plan, point, platform, enter_target, swd_pin
                )
                for point in plan.shmoo.points
            )
            emissions = [
                emission
                for active, restore in point_emissions
                for emission in (*active, restore)
            ]
        ref = RenderSymbolRef("TEST_BODY", f"{platform}:{entry.identity}")
        owner = f"standard-verify:{target.identity}:{definition.identity}"
        extension = ".pln" if platform == "chroma" else ".prg"
        contribution = ProgramContribution(
            identity=owner,
            target=target,
            definitions=(TestDefinitionContribution(
                definition.identity, "STANDARD_VERIFY", owner,
            ),),
            schedule_entries=(ScheduleEntryContribution(
                entry.identity, definition.identity, ordinal, entry.enabled,
            ),),
            resource_requires=tuple(dict.fromkeys(
                requirement
                for emission in emissions
                for requirement in emission.resource_requires
            )),
            provides=tuple(
                provision for emission in emissions
                for provision in emission.provides
            ),
            requires=(
                SymbolRequirement(ref, "SECTION", None, "TARGET"),
            ),
        )
        body = (
            _render_body(
                definition.render_name, plan, emissions, platform,
                entry.bin_binding.hardware_bin,
            )
            if plan.shmoo is None else
            _render_shmoo_body(
                definition.render_name, plan, point_emissions, platform,
                entry.bin_binding.hardware_bin,
            )
        )
        fragment = SectionFragment(
            f"{target.program_name}{extension}",
            "TESTS",
            f"{owner}:body",
            body.replace("\r\n", "\n").replace("\n", "\r\n").encode("gbk"),
            order=ordinal,
        )
        contributions.append(contribution)
        bodies.append(SkeletonBody(ref, fragment))
    return TypedKindAssembly("STANDARD_VERIFY", tuple(contributions), tuple(bodies))


def _emit_run(plan, platform: str):
    return NATIVE_RECIPE_MODULE_REGISTRY.emit("RUN", plan, platform)


def _emit_shmoo_point(
    plan, point, platform: str, enter_target=None, swd_pin: str | None = None,
):
    active = [_emit_run(plan.protocol_enter, platform)]
    restore = RecipeModuleEmission()
    for index, step in enumerate(point.steps):
        if index != plan.shmoo.consumer_index:
            active.extend(_emit_step(step, platform))
            continue
        if step.module == "ENTER":
            active.append(RecipeModuleEmission(statements=(
                *_enter_override(
                    enter_target, swd_pin, point.step, platform
                ),
            )))
            active.extend(_emit_step(step, platform))
            restore = RecipeModuleEmission(statements=(
                *_enter_override(
                    enter_target, swd_pin, plan.shmoo.default_value, platform
                ),
            ))
        else:
            original = step.module_plan
            active.append(_dac_literal_override(original, point.step, platform))
            restore = NATIVE_RECIPE_MODULE_REGISTRY.emit(
                "DAC_WRITE", replace(original, execute_pattern=False), platform
            )
    active.append(_emit_run(plan.protocol_exit, platform))
    return tuple(active), restore


def _enter_override(target, swd_pin: str, value: int, platform: str):
    if platform == "chroma":
        return (
            "  SOCKET_INC(FRZ_OFF)",
            "  {",
            f"    convert_to_string({value},{target.bit_width},"
            "BUFF_W_P,BUFF_W_N,BUFF_R_P,BUFF_R_N);",
            f"    for(I=0;I<{target.bit_width};I++)",
            "    {",
            f"      WRITE_PAT_MEM(SOCKET,{swd_pin},"
            f"{target.pattern_identity}:{target.chroma_start_label}+I,,BUFF_W_P[I]);",
            "    }",
            "  }",
        )
    return (
        f"\tC_ASSIGN(GB1,{value});",
        "\tLOGIC_WRITE_PATTERN_MEMORY("
        f"{target.pattern_identity}:{target.s100_start_label},"
        f"{target.pattern_identity}:{target.s100_end_label},"
        f"{swd_pin},GB1,BIT_COUNT={target.bit_width},SERIAL,MSB_LSB);",
    )


def _dac_literal_override(plan, value: int, platform: str):
    run = _emit_run(plan.run_pattern, platform)
    if platform == "chroma":
        memory = (
            "  SOCKET_INC(FRZ_OFF)",
            "  {",
            f"    convert_to_string({value},{plan.target.bit_width},"
            "BUFF_W_P,BUFF_W_N,BUFF_R_P,BUFF_R_N);",
            f"    for(I=0;I<{plan.target.bit_width};I++)",
            "    {",
            f"      WRITE_PAT_MEM(SOCKET,{plan.swd_pin},"
            f"{plan.target.pattern.name}:{plan.target.chroma_start_label}+I,,BUFF_W_P[I]);",
            "    }",
            "  }",
        )
    else:
        memory = (
            f"\tC_ASSIGN(GB1,{value});",
            "\tLOGIC_WRITE_PATTERN_MEMORY("
            f"{plan.target.pattern.name}:{plan.target.s100_start_label},"
            f"{plan.target.pattern.name}:{plan.target.s100_end_label},"
            f"{plan.swd_pin},GB1,BIT_COUNT={plan.target.bit_width},SERIAL,MSB_LSB);",
        )
    return RecipeModuleEmission(
        statements=(*memory, *run.statements),
        resource_requires=run.resource_requires,
    )


def _shmoo_enter_facts(plan, context):
    if plan.shmoo is None or plan.shmoo.consumer_module != "ENTER":
        return None, None
    step = plan.steps[plan.shmoo.consumer_index]
    fbist = context.compilation.plan.catalogs.fbist_pattern_plan
    matches = tuple(
        field for field in compile_fbist_writable_field_catalog(fbist)
        if field.pattern_identity == step.module_plan.pattern.name
    )
    if len(matches) != 1:
        raise ValueError(
            "SV.SHMOO.ENTER_FIELD_UNRESOLVED: "
            f"{step.module_plan.pattern.name!r} resolves to {len(matches)} fields"
        )
    target = matches[0]
    if target.bit_width != plan.shmoo.field_width:
        raise ValueError("SV.SHMOO.ENTER_FIELD_WIDTH_MISMATCH")
    return target, fbist.swd_pin


def _emit_step(step, platform: str):
    if step.module not in NATIVE_RECIPE_MODULE_REGISTRY.registered_modules:
        raise ValueError(
            f"SV.ASSEMBLY.MODULE_UNREGISTERED: {step.module}"
        )
    if step.module_plan is None:
        raise ValueError(
            f"SV.ASSEMBLY.MODULE_PLAN_MISSING: {step.module}"
        )
    if step.module != "JUDGE" or step.module_plan.pe_window is None:
        return (
            NATIVE_RECIPE_MODULE_REGISTRY.emit(
                step.module, step.module_plan, platform
            ),
        )
    window = step.module_plan.pe_window
    return (
        NATIVE_RECIPE_MODULE_REGISTRY.emit("RUN", window.before, platform),
        NATIVE_RECIPE_MODULE_REGISTRY.emit("JUDGE", step.module_plan, platform),
        NATIVE_RECIPE_MODULE_REGISTRY.emit("RUN", window.after, platform),
    )


def _render_body(name, plan, emissions, platform: str, hardware_bin: str | None) -> str:
    statements = [line for emission in emissions for line in emission.statements]
    measurement = next(
        step.module_plan.measurement for step in reversed(plan.steps)
        if step.module == "JUDGE"
    )
    if platform == "chroma":
        lines = [f"{name}()", "{", f"  TEST_NUM={plan.test_number};"]
        lines.append(f"  POWER_ON({plan.initial_power_profile});")
        if measurement.kind is not JudgeMeasurementKind.FREQUENCY:
            lines.append(f"  RELAY_ON({measurement.pin},PPMU_PDCL,2mS);")
        lines.extend(statements)
        if measurement.kind is JudgeMeasurementKind.FREQUENCY:
            lines.append(f"  SET_TFTM_MODE({measurement.pin}, SCHMITT_OFF);")
        else:
            lines.extend(_chroma_cleanup(measurement))
        lines.extend(("  POWER_OFF();", "}"))
    else:
        lines = [
            f"@@PLAN {name}",
            "\tSITE_SEQUENCE      = OFF;",
            "\tGO_THROUGH         = ON;",
            "\tDISABLE_BY_MARK_NO = NULL;",
            "\tS_SETUP_FILE       = c:\\set.dat;",
            f"\tREMARK             = {name};",
            "",
            f"\tCALL_MACRO POWER_ON(_C_{plan.initial_power_profile});",
        ]
        lines.extend(statements)
        if measurement.requires_zero_reset and (
            measurement.kind is JudgeMeasurementKind.CURRENT
        ):
            lines.append(
                f"\tLOGIC_PPMU_FV({measurement.pin}, 0V, E2, I5);"
            )
        elif measurement.requires_zero_reset and (
            measurement.kind is JudgeMeasurementKind.VOLTAGE
        ):
            lines.append(
                f"\tLOGIC_PPMU_FI({measurement.pin}, 0uA, E2, I5);"
            )
        lines.extend((
            "\tCALL_MACRO POWER_OFF();",
            "",
            "\tCONDITION",
            "\tIF_FAIL",
            f"\tREJECT_BIN = {hardware_bin};",
            "@@END_PLAN",
        ))
    return "\n".join(lines) + "\n"


def _render_shmoo_body(
    name, plan, point_emissions, platform: str, hardware_bin: str | None,
) -> str:
    looped = _render_shmoo_loop_body(
        name, plan, point_emissions, platform, hardware_bin
    )
    if looped is not None:
        return looped
    if platform == "chroma":
        lines = [f"{name}()", "{", f"  TEST_NUM={plan.test_number};"]
        for point, (active, restore) in zip(plan.shmoo.points, point_emissions):
            measurement = _point_measurement(point)
            lines.append(f"  POWER_ON({plan.initial_power_profile});")
            if measurement.kind is not JudgeMeasurementKind.FREQUENCY:
                lines.append(f"  RELAY_ON({measurement.pin},PPMU_PDCL,2mS);")
            lines.extend(
                line for emission in active for line in emission.statements
            )
            lines.extend(_chroma_cleanup(measurement))
            lines.append("  POWER_OFF();")
            lines.extend(restore.statements)
            if not plan.shmoo.pass_fail:
                lines.extend((
                    "  SOCKET_INC(FRZ_OFF)",
                    "  {",
                    "    PLAN_RESULT_MS[SOCKET]=PASS;",
                    "  }",
                ))
        lines.append("}")
    else:
        lines = [
            f"@@PLAN {name}",
            "\tSITE_SEQUENCE      = OFF;",
            "\tGO_THROUGH         = ON;",
            "\tDISABLE_BY_MARK_NO = NULL;",
            "\tS_SETUP_FILE       = c:\\set.dat;",
            f"\tREMARK             = {name};",
            "",
        ]
        for point, (active, restore) in zip(plan.shmoo.points, point_emissions):
            measurement = _point_measurement(point)
            lines.append(f"\tCALL_MACRO POWER_ON(_C_{plan.initial_power_profile});")
            lines.extend(
                line for emission in active for line in emission.statements
            )
            lines.extend(_s100_cleanup(measurement))
            lines.append("\tCALL_MACRO POWER_OFF();")
            lines.extend(restore.statements)
            lines.append("")
        if plan.shmoo.pass_fail:
            lines.extend((
                "\tCONDITION",
                "\tIF_FAIL",
                f"\tREJECT_BIN = {hardware_bin};",
            ))
        lines.append("@@END_PLAN")
    return "\n".join(lines) + "\n"


def _render_shmoo_loop_body(
    name, plan, point_emissions, platform: str, hardware_bin: str | None,
):
    points = plan.shmoo.points
    if not points or plan.shmoo.consumer_module != "ENTER":
        return None
    measurements = tuple(_point_measurement(point) for point in points)
    if any(
        measurement.kind is JudgeMeasurementKind.FREQUENCY
        for measurement in measurements
    ):
        return None
    normalized = []
    judge_lines = []
    restore_lines = []
    for point, (active, restore) in zip(points, point_emissions):
        flat = [line for emission in active for line in emission.statements]
        step_matches = [
            index for index, line in enumerate(flat)
            if (
                f"convert_to_string({point.step},{plan.shmoo.field_width}," in line
                if platform == "chroma"
                else line.strip() == f"C_ASSIGN(GB1,{point.step});"
            )
        ]
        judge_matches = [
            index for index, line in enumerate(flat)
            if (
                line.strip().startswith(("JUDGE_V_PPMU(", "JUDGE_I_PPMU("))
                if platform == "chroma"
                else line.strip().startswith(("LOGIC_PPMU_MV(", "LOGIC_PPMU_MI("))
                and "LOG_ALIAS=" in line
            )
        ]
        log_matches = [
            index for index, line in enumerate(flat)
            if line.strip() == f'DATALOG_MSG="{_point_measurement(point).alias}";'
        ] if platform == "chroma" else []
        if len(step_matches) != 1 or len(judge_matches) != 1 or (
            platform == "chroma" and len(log_matches) != 1
        ):
            return None
        judge_lines.append(flat[judge_matches[0]])
        flat[step_matches[0]] = "<SHMOO_STEP>"
        flat[judge_matches[0]] = "<SHMOO_JUDGE>"
        if log_matches:
            flat[log_matches[0]] = "<SHMOO_LOG>"
        normalized.append(tuple(flat))
        restore_lines.append(tuple(restore.statements))
    if any(item != normalized[0] for item in normalized[1:]) or any(
        item != restore_lines[0] for item in restore_lines[1:]
    ):
        return None

    count = len(points)
    steps = ",".join(str(point.step) for point in points)
    first = points[0]
    first_measurement = measurements[0]
    active_lines = [
        line for emission in point_emissions[0][0] for line in emission.statements
    ]
    if platform == "chroma":
        lows = ",".join(_number(item.low_limit) for item in measurements)
        highs = ",".join(_number(item.high_limit) for item in measurements)
        aliases = ",".join(f'"{item.alias}"' for item in measurements)
        lines = [
            f"{name}()", "{", f"  TEST_NUM={plan.test_number};",
            f"  int shmoo_step[{count}]={{{steps}}};",
            f"  double shmoo_down[{count}]={{{lows}}};",
            f"  double shmoo_up[{count}]={{{highs}}};",
            f"  char shmoo_alias[{count}][64]={{{aliases}}};",
            "  char shmoo_log[64]={0};",
            f"  for(int shmoo_index=0;shmoo_index<{count};shmoo_index++)", "  {",
            f"    POWER_ON({plan.initial_power_profile});",
            f"    RELAY_ON({first_measurement.pin},PPMU_PDCL,2mS);",
        ]
        dynamic = []
        for line in active_lines:
            if f"convert_to_string({first.step}," in line:
                line = line.replace(
                    f"convert_to_string({first.step},",
                    "convert_to_string(shmoo_step[shmoo_index],", 1,
                )
            if line.strip() == f'DATALOG_MSG="{first_measurement.alias}";':
                dynamic.extend((
                    '  sprintf(shmoo_log,"%s",shmoo_alias[shmoo_index]);',
                    "  DATALOG_MSG=shmoo_log;",
                ))
                continue
            if line == judge_lines[0]:
                line = line.replace(
                    f"{_number(first_measurement.low_limit)}{first_measurement.unit}",
                    "shmoo_down[shmoo_index]", 1,
                ).replace(
                    f"{_number(first_measurement.high_limit)}{first_measurement.unit}",
                    "shmoo_up[shmoo_index]", 1,
                )
            dynamic.append(line)
        lines.extend("  " + line if line else "" for line in dynamic)
        lines.extend("  " + line if line else "" for line in _chroma_cleanup(first_measurement))
        lines.append("    POWER_OFF();")
        lines.extend("  " + line if line else "" for line in restore_lines[0])
        if not plan.shmoo.pass_fail:
            lines.extend((
                "    SOCKET_INC(FRZ_OFF)", "    {",
                "      PLAN_RESULT_MS[SOCKET]=PASS;", "    }",
            ))
        lines.extend(("  }", "}"))
    else:
        lines = [
            f"@@PLAN {name}",
            "\tSITE_SEQUENCE      = OFF;", "\tGO_THROUGH         = ON;",
            "\tDISABLE_BY_MARK_NO = NULL;", "\tS_SETUP_FILE       = c:\\set.dat;",
            f"\tREMARK             = {name};", "",
            f"\tfor(int shmoo_index=0;shmoo_index<{count};shmoo_index++)", "\t{",
            f"\t\tCALL_MACRO POWER_ON(_C_{plan.initial_power_profile});",
        ]
        dynamic = []
        for line in active_lines:
            if line.strip() == f"C_ASSIGN(GB1,{first.step});":
                dynamic.extend(("\tswitch(shmoo_index)", "\t{"))
                dynamic.extend(
                    f"\t\tcase {index}: C_ASSIGN(GB1,{point.step}); break;"
                    for index, point in enumerate(points)
                )
                dynamic.append("\t}")
                continue
            if line == judge_lines[0]:
                dynamic.extend(("\tswitch(shmoo_index)", "\t{"))
                dynamic.extend(
                    f"\t\tcase {index}: {judge.strip()} break;"
                    for index, judge in enumerate(judge_lines)
                )
                dynamic.append("\t}")
                continue
            dynamic.append(line)
        lines.extend("\t" + line if line else "" for line in dynamic)
        lines.extend("\t" + line if line else "" for line in _s100_cleanup(first_measurement))
        lines.append("\t\tCALL_MACRO POWER_OFF();")
        lines.extend("\t" + line if line else "" for line in restore_lines[0])
        lines.append("\t}")
        if plan.shmoo.pass_fail:
            lines.extend((
                "\tCONDITION", "\tIF_FAIL", f"\tREJECT_BIN = {hardware_bin};",
            ))
        lines.append("@@END_PLAN")
    return "\n".join(lines) + "\n"


def _number(value: float) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else str(number)


def _point_measurement(point):
    return next(
        step.module_plan.measurement for step in reversed(point.steps)
        if step.module == "JUDGE"
    )


def _chroma_cleanup(measurement):
    if measurement.kind is JudgeMeasurementKind.FREQUENCY:
        return (f"  SET_TFTM_MODE({measurement.pin}, SCHMITT_OFF);",)
    lines = []
    if measurement.requires_zero_reset:
        if measurement.kind is JudgeMeasurementKind.CURRENT:
            lines.append(
                f"  FORCE_V_PPMU({measurement.pin}, 0V, ,@2uA, , 2mS);"
            )
        else:
            lines.append(
                f"  FORCE_I_PPMU({measurement.pin}, 0uA, @2uA, ,6V, -2V ,3mS);"
            )
    lines.append(f"  RELAY_OFF({measurement.pin}, PPMU_PDCL, 2mS);")
    return tuple(lines)


def _s100_cleanup(measurement):
    if measurement.requires_zero_reset and (
        measurement.kind is JudgeMeasurementKind.CURRENT
    ):
        return (f"\tLOGIC_PPMU_FV({measurement.pin}, 0V, E2, I5);",)
    if measurement.requires_zero_reset and (
        measurement.kind is JudgeMeasurementKind.VOLTAGE
    ):
        return (f"\tLOGIC_PPMU_FI({measurement.pin}, 0uA, E2, I5);",)
    return ()


__all__ = ["compile_standard_verify_assembly"]
