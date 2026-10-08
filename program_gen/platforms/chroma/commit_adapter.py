"""Chroma Adapter for the shared COMMIT Recipe Module."""

from program_gen.core.commit_module import CommitModulePlan
from program_gen.recipe_module_registry import RecipeModuleEmission
from program_gen.render_plan import ResourceRequirement


def adapt_commit(plan: CommitModulePlan) -> RecipeModuleEmission:
    if not plan.writes and not plan.field_values:
        return RecipeModuleEmission()
    lines = ["  SOCKET_INC(FRZ_OFF)", "  {"]
    for write in plan.writes:
        mask = ((1 << write.width) - 1) << write.lsb
        value_mask = (1 << write.width) - 1
        source = _value(write.value, "SOCKET")
        register = f"REG_{write.register.upper()}[SOCKET]"
        if mask == 0xFFFF:
            lines.append(f"    {register}=({source}&0xFFFF);")
        else:
            lines.append(
                f"    {register}=({register}&0x{(~mask & 0xFFFF):04X})|"
                f"(({source}&0x{value_mask:X})<<{write.lsb});"
            )
    for target in plan.targets:
        lines.extend(_refresh(target, plan.swd_pin))
    lines.extend(render_field_values(plan.field_values, plan.swd_pin))
    lines.append("  }")
    return RecipeModuleEmission(
        statements=tuple(lines),
        resource_requires=tuple(
            ResourceRequirement(
                f"pattern:{name}", f"pat/{name}.pat", f"v13.pattern/1:chroma:{name}",
                "COMMIT incremental Pattern refresh",
            )
            for target in (*plan.targets, *plan.field_values)
            for name in (target.program_pattern, target.read_pattern)
        ),
    )


def render_field_values(fields, pin):
    """Called inside the caller's Site loop; values and labels are already bound."""
    lines = []
    for field in fields:
        for label in field.labels:
            write_buffer = "BUFF_W_N" if label.polarity == "n" else "BUFF_W_P"
            read_buffer = "BUFF_R_N" if label.polarity == "n" else "BUFF_R_P"
            read_value = '"X"' if field.read_dont_care else f"{read_buffer}[I]"
            lines.extend((
                f"    convert_to_string({_value(field.value, 'SOCKET')},{label.width},BUFF_W_P,BUFF_W_N,BUFF_R_P,BUFF_R_N);",
                f"    for(I=0;I<{label.width};I++)",
                "    {",
            ))
            if field.write_program:
                lines.append(f"      WRITE_PAT_MEM(SOCKET,{pin},{field.program_pattern}:{label.write.chroma_start}+I,,{write_buffer}[I]);")
            lines.extend((
                f"      WRITE_PAT_MEM(SOCKET,{pin},{field.read_pattern}:{label.read.chroma_start}+I,,{read_value});",
                "    }",
            ))
    return lines


def _refresh(target, swd_pin: str):
    lines = [
        f"    convert_to_string({target.register_symbol}[SOCKET],16,"
        "BUFF_W_P,BUFF_W_N,BUFF_R_P,BUFF_R_N);",
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
            f"      WRITE_PAT_MEM(SOCKET,{swd_pin},{pattern}:"
            f"{label_range.chroma_start}+I,,{buffer}[I]);"
        )
    lines.append("    }")
    return lines


def _value(value, site: str) -> str:
    if value.kind == "DECIMAL":
        return str(int(value.token, 10))
    if value.kind == "HEX":
        return "0x" + value.token.removeprefix("0x").removeprefix("0X")
    if value.kind == "BINARY":
        return str(int(value.token, 2))
    if value.kind == "VARIABLE":
        return f"{value.token}[{site}]"
    if value.kind == "STEP":
        return value.token
    raise ValueError(f"COMMIT.VALUE_KIND_UNSUPPORTED: {value.kind!r}")


__all__ = ["adapt_commit"]
