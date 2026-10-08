"""S100 Adapters for native TRIMDATA_READ Recipe Modules."""

from program_gen.core.otp_program import LoadMapPlan
from program_gen.core.trimdata_read import CheckOtpPlan, ReadOtpMapPlan
from program_gen.platforms.s100.run_pattern_adapter import adapt_run_pattern
from program_gen.recipe_module_registry import RecipeModuleEmission
from program_gen.render_plan import ResourceRequirement


def adapt_read_otp_map(plan: ReadOtpMapPlan) -> RecipeModuleEmission:
    lines = []
    requirements = []
    for page_index, page in enumerate(plan.pages):
        if page_index:
            lines.append("")
        run = adapt_run_pattern(page.capture)
        requirements.extend(run.resource_requires)
        lines.extend((
            f"\t// {page.page} candidate Page Image capture",
            f"\tLOGIC_SET_AC_DATALOG({page.capture.pattern.name}:START,{page.capture.pattern.name}:END,LOG_ENABLE_ALL,AC_IGNORE_FAIL);",
            *run.statements,
            "\tLOGIC_CLEAR_SET_AC_FLAG( );",
            f"\tLOGIC_READ_LOG(LOG_ARRAY,{plan.swd_pin},{page.byte_count * 8},1,BIN,TRIG_PINNAME=TRIGPIN);",
            f"\tDAQ_ARRAY_TRANSFER(LOG_ARRAY,{min(page.byte_count, 100)},1,8,\"1\",\"8,7,6,5,4,3,2,1\",UP_LIMIT=255,DOWN_LIMIT=0,HEX);",
            "\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)",
            "\t{",
            "\t\tif(Sys_ActiveSite[T_SOCKET]==0)continue;",
        ))
        offset = 0
        for entry in page.layout:
            real = offset + entry.real_offset
            if page.restore_registers is None or entry.register in page.restore_registers:
                lines.append(
                    f"\t\tREG_{entry.register.upper()}[T_SOCKET]=((int)Sys_SW_BUFFER_DATA[T_SOCKET][{real}]<<8)+Sys_SW_BUFFER_DATA[T_SOCKET][{real + 1}];"
                )
            offset += entry.slot_width
        lines.append("\t}")
    if plan.pumps:
        lines.extend((
            "",
            "\t// ==================== Restore captured DAC values ====================",
        ))
        lines.extend(_restore_pumps(plan))
    return RecipeModuleEmission(tuple(lines), tuple(requirements))


def adapt_load_map(plan: LoadMapPlan) -> RecipeModuleEmission:
    from program_gen.platforms.s100.commit_adapter import render_field_values
    lines = [""]
    for target_index, target in enumerate(plan.targets):
        if target_index:
            lines.append("")
        lines.append(
            f"\t// ==================== {target.page} / {target.register} pattern overwrite ===================="
        )
        lines.extend(_refresh(target, plan.swd_pin))
    for write in plan.word_writes:
        lines.extend((
            "",
            f"\t// ==================== {write.page} / Word[{write.word_index:02d}] pattern overwrite ====================",
            f"\tCALL_MACRO write_pat_temp_fixed(0x{write.value:08X});",
        ))
        for label in write.labels:
            lines.extend((
                _write(write.program_pattern, label.write, plan.swd_pin, bits=32),
                _write(write.read_pattern, label.read, plan.swd_pin, compare=True, bits=32),
            ))
    if plan.field_values:
        lines.extend((
            "",
            "\t// ==================== Additional field pattern overwrite ====================",
        ))
    for field in plan.field_values:
        lines.extend((
            "",
            f"\t// ==================== {field.field} pattern overwrite ====================",
        ))
        lines.extend(render_field_values((field,), plan.swd_pin))
    return RecipeModuleEmission(
        tuple(lines),
        tuple(ResourceRequirement(
            f"pattern:{name}", f"{name}.sd", f"v13.pattern/1:s100:{name}",
            "LOADMAP Program/Read Pattern Memory",
        ) for target in (*plan.targets, *plan.word_writes, *plan.field_values)
          for name in (target.program_pattern, target.read_pattern)),
    )


def adapt_check_otp(plan: CheckOtpPlan) -> RecipeModuleEmission:
    emissions = (
        adapt_run_pattern(plan.set_all_final_vposp),
        *(adapt_run_pattern(read) for read in plan.page_reads),
    )
    return RecipeModuleEmission(
        tuple(line for emission in emissions for line in emission.statements),
        tuple(item for emission in emissions for item in emission.resource_requires),
    )


def _restore_pumps(plan):
    if not plan.pumps:
        return []
    lines = [
        "\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)", "\t{",
        "\t\tif(Sys_ActiveSite[T_SOCKET]==0)continue;",
    ]
    for pump in plan.pumps:
        source = pump.restored_sources[0]
        symbol = next(item.symbol for item in pump.sources if item.symbol)
        mask = (1 << source.width) - 1
        lines.append(
            f"\t\t{symbol}[T_SOCKET]=(REG_{source.register.upper()}[T_SOCKET]>>{source.lsb})&0x{mask:X};"
        )
    lines.append("\t}")
    return lines


def _refresh(target, swd_pin):
    source = target.register_symbol
    lines = [f"\tCALL_MACRO write_pat_temp_arry({source});"]
    by_polarity = {label.polarity: label for label in target.labels}
    if set(by_polarity) == {"p", "n"}:
        lines.extend((
            _write(target.program_pattern, by_polarity["p"].write, swd_pin),
            _write(target.read_pattern, by_polarity["p"].read, swd_pin, compare=True),
            f"\tCALL_MACRO Bitwise_not_arry({source});",
            _write(target.program_pattern, by_polarity["n"].write, swd_pin),
            _write(target.read_pattern, by_polarity["n"].read, swd_pin, compare=True),
        ))
    else:
        label = by_polarity[""]
        lines.extend((
            _write(target.program_pattern, label.write, swd_pin),
            _write(target.read_pattern, label.read, swd_pin, compare=True),
        ))
    return lines


def _write(pattern, label_range, pin, compare=False, bits=16):
    suffix = ",DATA1=H,DATA0=L" if compare else ""
    return (
        f"\tLOGIC_WRITE_PATTERN_MEMORY({pattern}:{label_range.s100_start},"
        f"{pattern}:{label_range.s100_end},{pin},GB1,BIT_COUNT={bits},SERIAL,MSB_LSB{suffix});"
    )


__all__ = ["adapt_check_otp", "adapt_load_map", "adapt_read_otp_map"]
