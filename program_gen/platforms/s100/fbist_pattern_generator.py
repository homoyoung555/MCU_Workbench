"""S100 FBIST Pattern Generator: executes one immutable plan into .sd files.

The generator is a pure function of ``FbistPatternGenerationPlan``: it reads no
workbook, no DataFrame, no VERSION/FB MAP sheet, no global ``G`` and no output
directory.  It returns immutable artifacts plus the label catalog; publishing
files is the caller's job.

The vector layout (TRIGPIN column, label padding, START/END markers and the
per-dynamic-field ``0;``/``1;`` TRIGPIN state) is the exact legacy S100
behavior; only the upstream facts moved into the plan.
"""

from __future__ import annotations

import hashlib

from program_gen.core.fbist_pattern_plan import (
    AGGREGATE_PATTERN_NAME,
    FbistPatternArtifact,
    FbistPatternGenerationPlan,
    FbistPatternGenerationResult,
    FbistPatternWrite,
    compile_fbist_label_catalog,
)

_SERIAL_BASES = ("a", "b", "c", "d", "e")


def generate_fbist_patterns(
    plan: FbistPatternGenerationPlan,
) -> FbistPatternGenerationResult:
    """Render every ordinary pattern plus the PUMP aggregate as .sd bytes."""
    if not isinstance(plan, FbistPatternGenerationPlan):
        raise TypeError("S100 generator expects FbistPatternGenerationPlan")
    artifacts = []
    for pattern in plan.patterns:
        content = _render_sd(plan, pattern.pattern_name, pattern.writes)
        artifacts.append(_artifact(plan, pattern.pattern_name, content))
    if plan.pump_aggregate.writes:
        content = _render_sd(plan, AGGREGATE_PATTERN_NAME, plan.pump_aggregate.writes)
        artifacts.append(_artifact(plan, AGGREGATE_PATTERN_NAME, content))
    return FbistPatternGenerationResult(
        platform="s100",
        workbook_identity=plan.workbook_identity,
        artifacts=tuple(artifacts),
        label_catalog=compile_fbist_label_catalog(plan),
    )


def _render_sd(plan: FbistPatternGenerationPlan, name: str, writes) -> bytes:
    enter = "enter" in name
    end = ";" if enter else "1;"
    width = _label_width(plan, name, writes)
    lines: list[str] = []
    lines.append("HEAD[PIN_NAME]:")
    lines.append("")
    if enter:
        lines.append(f"{plan.clk_pin}, {plan.swd_pin}, NRST;")
    else:
        lines.append(f"{plan.clk_pin}, {plan.swd_pin}, NRST,TRIGPIN;")
    lines.append("")
    lines.append("END_HEAD;")
    lines.append("")
    lines.append("@@PATTERN_DEFINE")
    lines.append("")
    lines.append(" " * (width - len("START:")) + f"START:011{end}")
    lines.append(" " * width + f"011{end}RPT 100;")

    pattern_end = end
    for write in writes:
        pattern_end = _render_write(plan, name, write, lines, width, pattern_end)

    lines.append("")
    lines.append(" " * width + f"111{pattern_end}")
    lines.append(" " * width + f"111{pattern_end}RPT 1000;// wait 100 us")
    lines.append(" " * width + f"111{pattern_end}")
    lines.append(" " * (width - len("END:")) + f"END:011{pattern_end}")
    lines.append("")
    lines.append("@@END_PATTERN_DEFINE ")
    return "\n".join(lines).encode("ascii")


def _render_write(
    plan: FbistPatternGenerationPlan,
    name: str,
    write: FbistPatternWrite,
    lines: list[str],
    width: int,
    pattern_end: str,
) -> str:
    pad = " " * width
    lines.append("")
    lines.append(f"{pad}111{pattern_end}")
    lines.append(f"{pad}111{pattern_end}RPT 50;// wait 50 us")
    lines.append(f"{pad}111{pattern_end}")
    lines.append("")
    lines.append(f"{pad}111{pattern_end}")
    lines.append(f"{pad}111{pattern_end}")
    lines.append(f"{pad}110{pattern_end}// 1 bit strobe")
    lines.append(f"{pad}111{pattern_end}// {plan.swd_pin}=1, write register")
    for index, bit in enumerate(write.addr_bits):
        if index == 0:
            lines.append(f"{pad}1{bit}1{pattern_end}//7bits addr{write.addr_bits}")
        else:
            lines.append(f"{pad}1{bit}1{pattern_end}")
    lines.append("")

    set_pattern = name.startswith("set_")
    aggregate = name == AGGREGATE_PATTERN_NAME
    for z in range(len(write.data_bits)):
        flag = False
        for field in write.fields:
            if z == 15 - field.start_bit:
                if z % 4 == 0:
                    lines.append("")
                if set_pattern:
                    pattern_end = "0;"
                    if field.dynamic:
                        if aggregate:
                            label = f"{field.label_base}_st:"
                        else:
                            label = f"{_SERIAL_BASES[field.line_index]}_data_st:"
                        lines.append(
                            " " * (width - len(label))
                            + label
                            + f"1{write.data_bits[z]}1{pattern_end}"
                            + f"//{field.description}"
                        )
                        flag = True
                    else:
                        lines.append(
                            f"{pad}1{write.data_bits[z]}1{pattern_end}"
                            + f"//{field.description}"
                        )
                        flag = True
                else:
                    if field.dynamic:
                        label = f"{_SERIAL_BASES[field.line_index]}_data_st:"
                        lines.append(
                            " " * (width - len(label))
                            + label
                            + f"1{write.data_bits[z]}1{pattern_end}"
                            + f"//{field.description}"
                        )
                    else:
                        if z % 4 == 0:
                            lines.append("")
                        lines.append(
                            f"{pad}1{write.data_bits[z]}1{pattern_end}"
                            + f"//{field.description}"
                        )
                    flag = True
            if field.dynamic:
                if z == 15 - field.start_bit + field.bit_width - 1:
                    if z % 4 == 0:
                        lines.append("")
                    if aggregate:
                        label = f"{field.label_base}_sp:"
                    else:
                        label = f"{_SERIAL_BASES[field.line_index]}_data_sp:"
                    lines.append(
                        " " * (width - len(label))
                        + label
                        + f"1{write.data_bits[z]}1{pattern_end}"
                    )
                    flag = True
                    if set_pattern:
                        pattern_end = "1;"
        if z == 0 and not flag:
            lines.append(f"{pad}1{write.data_bits[0]}1{pattern_end}//16bits data")
        elif not flag:
            if z % 4 == 0:
                lines.append("")
            lines.append(f"{pad}1{write.data_bits[z]}1{pattern_end}")
    return pattern_end


def _label_width(plan: FbistPatternGenerationPlan, name: str, writes) -> int:
    """Legacy alignment width: 6 for enter patterns, else the longest label."""
    if "enter" in name:
        return 6
    labels: list[str] = []
    for write in writes:
        if name == AGGREGATE_PATTERN_NAME:
            for field in write.fields:
                labels.append(f"{field.label_base}_st:")
        elif write.raw_pattern == "trim dac":
            for field in write.fields:
                labels.append(f"{_SERIAL_BASES[field.line_index]}_data_st:")
    return max([6] + [len(label) for label in labels])


def _artifact(
    plan: FbistPatternGenerationPlan, name: str, content: bytes
) -> FbistPatternArtifact:
    digest = hashlib.sha256(content).hexdigest().upper()
    return FbistPatternArtifact(
        pattern_name=name,
        relative_path=f"{name}.sd",
        content=content,
        source_identity=(
            f"fbist-pattern:{plan.workbook_identity}:{name}:sha256:{digest}"
        ),
    )


__all__ = ["generate_fbist_patterns"]
