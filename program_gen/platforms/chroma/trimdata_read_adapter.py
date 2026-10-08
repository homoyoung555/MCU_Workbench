"""Chroma Adapters for native TRIMDATA_READ Recipe Modules."""

from program_gen.core.otp_program import LoadMapPlan
from program_gen.core.trimdata_read import CheckOtpPlan, ReadOtpMapPlan
from program_gen.platforms.chroma.run_pattern_adapter import adapt_run_pattern
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
        name = _capture_name(page.page)
        lines.extend((
            f"  // {page.page} candidate Page Image capture",
            f"  int {name}[MAX_SITE][{page.byte_count}];",
            f"  int {name}_BITS[{page.byte_count * 8}];",
            f"  SET_CAPTURE_MEM_MODE({plan.swd_pin}, PEL_K, ON, 8K);",
            *run.statements,
            "  SOCKET_INC(FRZ_OFF)",
            "  {",
            f"    for(J=0;J<{page.byte_count * 8};J++) {name}_BITS[J]=8;",
            f"    READ_CAPTURE_MEM_BLOCK(SOCKET,{plan.swd_pin},0,{page.byte_count * 8 - 1},{name}_BITS);",
            f"    for(I=0;I<{page.byte_count};I++)",
            "    {",
            f"      {name}[SOCKET][I]=0;",
            f"      for(J=0;J<8;J++) if({name}_BITS[8*I+J]!=8) {name}[SOCKET][I]+={name}_BITS[8*I+J]<<(7-J);",
            "    }",
        ))
        offset = 0
        for entry in page.layout:
            real = offset + entry.real_offset
            if page.restore_registers is None or entry.register in page.restore_registers:
                lines.append(
                    f"    REG_{entry.register.upper()}[SOCKET]=({name}[SOCKET][{real}]<<8)+{name}[SOCKET][{real + 1}];"
                )
            offset += entry.slot_width
        lines.extend(("  }", f"  SET_CAPTURE_MEM_MODE({plan.swd_pin}, PEL_K, OFF, 8K);"))
    if plan.pumps:
        lines.extend((
            "",
            "  // ==================== Restore captured DAC values ====================",
        ))
        lines.extend(_restore_pumps(plan, "SOCKET", "  "))
    return RecipeModuleEmission(tuple(lines), tuple(requirements))


def adapt_load_map(plan: LoadMapPlan) -> RecipeModuleEmission:
    from program_gen.platforms.chroma.commit_adapter import render_field_values
    lines = ["", "  SOCKET_INC(FRZ_OFF)", "  {"]
    for target_index, target in enumerate(plan.targets):
        if target_index:
            lines.append("")
        lines.append(
            f"    // ==================== {target.page} / {target.register} pattern overwrite ===================="
        )
        lines.extend(_refresh(target, plan.swd_pin))
    for write in plan.word_writes:
        lines.extend((
            "",
            f"    // ==================== {write.page} / Word[{write.word_index:02d}] pattern overwrite ====================",
            f"    convert_to_string(0x{write.value:08X}u,32,BUFF_W_P,BUFF_W_N,BUFF_R_P,BUFF_R_N);",
            "    for(I=0;I<32;I++)",
            "    {",
        ))
        for label in write.labels:
            lines.extend((
                f"      WRITE_PAT_MEM(SOCKET,{plan.swd_pin},{write.program_pattern}:{label.write.chroma_start}+I,,BUFF_W_P[I]);",
                f"      WRITE_PAT_MEM(SOCKET,{plan.swd_pin},{write.read_pattern}:{label.read.chroma_start}+I,,BUFF_R_P[I]);",
            ))
        lines.append("    }")
    if plan.field_values:
        lines.extend((
            "",
            "    // ==================== Additional field pattern overwrite ====================",
        ))
    for field in plan.field_values:
        lines.extend((
            "",
            f"    // ==================== {field.field} pattern overwrite ====================",
        ))
        lines.extend(render_field_values((field,), plan.swd_pin))
    lines.append("  }")
    return RecipeModuleEmission(
        tuple(lines),
        tuple(ResourceRequirement(
            f"pattern:{name}", f"pat/{name}.pat", f"v13.pattern/1:chroma:{name}",
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


def _restore_pumps(plan, site, indent):
    lines = [f"{indent}SOCKET_INC(FRZ_OFF)", f"{indent}{{"] if plan.pumps else []
    for pump in plan.pumps:
        source = pump.restored_sources[0]
        symbol = next(item.symbol for item in pump.sources if item.symbol)
        mask = (1 << source.width) - 1
        lines.append(
            f"{indent}  {symbol}[{site}]=(REG_{source.register.upper()}[{site}]>>{source.lsb})&0x{mask:X};"
        )
    if plan.pumps:
        lines.append(f"{indent}}}")
    return lines


def _refresh(target, swd_pin):
    lines = [
        f"    convert_to_string({target.register_symbol}[SOCKET],16,BUFF_W_P,BUFF_W_N,BUFF_R_P,BUFF_R_N);",
        "    for(I=0;I<16;I++)",
        "    {",
    ]
    by_polarity = {label.polarity: label for label in target.labels}
    if set(by_polarity) == {"p", "n"}:
        ranges = (
            (target.program_pattern, by_polarity["p"].write, "BUFF_W_P"),
            (target.program_pattern, by_polarity["n"].write, "BUFF_W_N"),
            (target.read_pattern, by_polarity["p"].read, "BUFF_R_P"),
            (target.read_pattern, by_polarity["n"].read, "BUFF_R_N"),
        )
    else:
        label = by_polarity[""]
        ranges = (
            (target.program_pattern, label.write, "BUFF_W_P"),
            (target.read_pattern, label.read, "BUFF_R_P"),
        )
    for pattern, label_range, buffer in ranges:
        lines.append(
            f"      WRITE_PAT_MEM(SOCKET,{swd_pin},{pattern}:{label_range.chroma_start}+I,,{buffer}[I]);"
        )
    lines.append("    }")
    return lines


def _capture_name(page):
    return "TRIMDATA_" + "".join(char if char.isalnum() else "_" for char in page).upper()


__all__ = ["adapt_check_otp", "adapt_load_map", "adapt_read_otp_map"]
