"""S100 Adapter for the shared COMMIT Recipe Module."""

from program_gen.core.commit_module import CommitModulePlan
from program_gen.recipe_module_registry import RecipeModuleEmission
from program_gen.render_plan import ResourceRequirement


def adapt_commit(plan: CommitModulePlan) -> RecipeModuleEmission:
    if not plan.writes and not plan.field_values:
        return RecipeModuleEmission()
    lines = [
        "\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)",
        "\t{",
        "\t\tif(Sys_ActiveSite[T_SOCKET]==0)continue;",
    ]
    for write in plan.writes:
        mask = ((1 << write.width) - 1) << write.lsb
        value_mask = (1 << write.width) - 1
        source = _value(write.value)
        register = f"REG_{write.register.upper()}[T_SOCKET]"
        if mask == 0xFFFF:
            lines.append(f"\t\t{register}=({source}&0xFFFF);")
        else:
            lines.append(
                f"\t\t{register}=({register}&0x{(~mask & 0xFFFF):04X})|"
                f"(({source}&0x{value_mask:X})<<{write.lsb});"
            )
    lines.append("\t}")
    for target in plan.targets:
        lines.extend(_refresh(target, plan.swd_pin))
    lines.extend(render_field_values(plan.field_values, plan.swd_pin))
    return RecipeModuleEmission(
        statements=tuple(lines),
        resource_requires=tuple(
            ResourceRequirement(
                f"pattern:{name}", f"{name}.sd", f"v13.pattern/1:s100:{name}",
                "COMMIT incremental Pattern refresh",
            )
            for target in (*plan.targets, *plan.field_values)
            for name in (target.program_pattern, target.read_pattern)
        ),
    )


def render_field_values(fields, pin):
    lines = []
    for field in fields:
        for label in field.labels:
            if field.value.kind == "VARIABLE":
                macro = "Bitwise_not_arry" if label.polarity == "n" else "write_pat_temp_arry"
                if label.polarity == "n" and label.width != 16:
                    raise ValueError("COMMIT.COMPLEMENT_WIDTH_UNSUPPORTED")
                if field.value_type == "uint32_t":
                    if label.polarity == "n":
                        raise ValueError("COMMIT.UINT32_COMPLEMENT_UNSUPPORTED")
                    macro = "write_pat_temp_long"
                argument = field.value.token
            else:
                macro = "write_pat_temp_fixed"
                argument = _value(field.value)
                if label.polarity == "n":
                    argument = f"({argument}^0x{(1 << label.width) - 1:X})"
            lines.append(f"\tCALL_MACRO {macro}({argument});")
            if field.write_program:
                lines.append(_write(field.program_pattern, label.write, pin, bits=label.width))
            lines.append(_write(field.read_pattern, label.read, pin, compare=True,
                                bits=label.width, dont_care=field.read_dont_care))
    return lines


def _refresh(target, swd_pin: str):
    source = f"{target.register_symbol}"
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


def _write(pattern: str, label_range, pin: str, *, compare=False, bits=16, dont_care=False) -> str:
    suffix = (",DATA1=X,DATA0=X" if dont_care else ",DATA1=H,DATA0=L") if compare else ""
    return (
        f"\tLOGIC_WRITE_PATTERN_MEMORY({pattern}:{label_range.s100_start},"
        f"{pattern}:{label_range.s100_end},{pin},GB1,BIT_COUNT={bits},SERIAL,MSB_LSB{suffix});"
    )


def _value(value) -> str:
    if value.kind == "DECIMAL":
        return str(int(value.token, 10))
    if value.kind == "HEX":
        return "0x" + value.token.removeprefix("0x").removeprefix("0X")
    if value.kind == "BINARY":
        return str(int(value.token, 2))
    if value.kind == "VARIABLE":
        return f"{value.token}[T_SOCKET]"
    if value.kind == "STEP":
        return value.token
    raise ValueError(f"COMMIT.VALUE_KIND_UNSUPPORTED: {value.kind!r}")


__all__ = ["adapt_commit"]
