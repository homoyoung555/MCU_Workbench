"""Chroma FBIST Pattern Generator: executes one immutable plan into .pat files.

The generator is a pure function of ``FbistPatternGenerationPlan``: it reads no
workbook, no DataFrame, no VERSION/FB MAP sheet, no global ``G`` and no output
directory.  It returns immutable artifacts plus the label catalog; publishing
files is the caller's job.
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
    """Render every ordinary pattern plus the PUMP aggregate as .pat bytes."""
    if not isinstance(plan, FbistPatternGenerationPlan):
        raise TypeError("Chroma generator expects FbistPatternGenerationPlan")
    artifacts = []
    for pattern in plan.patterns:
        content = _render_pat(plan, pattern.pattern_name, pattern.writes)
        artifacts.append(_artifact(plan, pattern.pattern_name, content))
    if plan.pump_aggregate.writes:
        content = _render_pat(plan, AGGREGATE_PATTERN_NAME, plan.pump_aggregate.writes)
        artifacts.append(_artifact(plan, AGGREGATE_PATTERN_NAME, content))
    return FbistPatternGenerationResult(
        platform="chroma",
        workbook_identity=plan.workbook_identity,
        artifacts=tuple(artifacts),
        label_catalog=compile_fbist_label_catalog(plan),
    )


def _render_pat(plan: FbistPatternGenerationPlan, name: str, writes) -> bytes:
    lines: list[str] = []
    lines.append('SET_DEC_FILE "pin.dec"')
    lines.append("")
    lines.append("HEADER")
    lines.append("")
    lines.append(f"{plan.clk_pin}, {plan.swd_pin}, NRST;")
    lines.append("")
    lines.append(f"SPM_PATTERN({name}) {{")
    lines.append("")
    lines.append("  *011*TS1;")
    lines.append("  *011*RPT 100;")
    for write in writes:
        _render_write(plan, name, write, lines)
    lines.append("")
    lines.append("  *111*;")
    lines.append("  *111*RPT 1000;// wait 100us ")
    lines.append("  *111*;")
    lines.append("  *011*STOP;")
    lines.append("")
    lines.append("}")
    return "\n".join(lines).encode("ascii")


def _render_write(
    plan: FbistPatternGenerationPlan,
    name: str,
    write: FbistPatternWrite,
    lines: list[str],
) -> None:
    lines.append("")
    lines.append("  *111*;")
    lines.append("  *111*RPT 50;// wait 50 us")
    lines.append("  *111*;")
    lines.append("")
    lines.append("  *111*;")
    lines.append("  *111*;")
    lines.append("  *110*;// 1 bit strobe")
    lines.append(f"  *111*;// {plan.swd_pin}=1, write register")
    for index, bit in enumerate(write.addr_bits):
        if index == 0:
            lines.append(f"  *1{bit}1*;// 7bits addr{write.addr_bits}")
        else:
            lines.append(f"  *1{bit}1*;")
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
                    if aggregate:
                        lines.append(f"{field.label_base}:")
                    elif field.dynamic:
                        lines.append(f"{_SERIAL_BASES[field.line_index]}_data:")
                    lines.append(
                        f"  *1{write.data_bits[z]}1*;// {field.description}"
                    )
                    flag = True
                else:
                    if field.dynamic:
                        lines.append(f"{_SERIAL_BASES[field.line_index]}_data:")
                    if z % 4 == 0:
                        lines.append("")
                    lines.append(
                        f"  *1{write.data_bits[z]}1*;// {field.description}"
                    )
                    flag = True
        if z == 0 and not flag:
            lines.append(f"  *1{write.data_bits[0]}1*;// 16bits data")
        elif not flag:
            if z % 4 == 0:
                lines.append("")
            lines.append(f"  *1{write.data_bits[z]}1*;")


def _artifact(
    plan: FbistPatternGenerationPlan, name: str, content: bytes
) -> FbistPatternArtifact:
    digest = hashlib.sha256(content).hexdigest().upper()
    return FbistPatternArtifact(
        pattern_name=name,
        relative_path=f"pat/{name}.pat",
        content=content,
        source_identity=(
            f"fbist-pattern:{plan.workbook_identity}:{name}:sha256:{digest}"
        ),
    )


__all__ = ["generate_fbist_patterns"]
