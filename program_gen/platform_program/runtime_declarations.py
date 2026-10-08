"""Render one typed RuntimeDeclarationPlan into the program GLOBALS section."""

from __future__ import annotations

from program_gen.core.declaration_plan import DeclarationKind, RuntimeDeclarationPlan
from program_gen.program_plan import SymbolCardinality
from program_gen.render_plan import ProgramContribution, SectionFragment


def compile_runtime_declaration_contribution(
    target, plan: RuntimeDeclarationPlan
) -> ProgramContribution:
    if not isinstance(plan, RuntimeDeclarationPlan):
        raise TypeError("RD.PLAN.TYPE")
    if plan.cp.casefold() != target.cp.casefold():
        raise ValueError("RD.TARGET.CP_MISMATCH")
    platform = target.platform.casefold()
    if platform not in ("chroma", "s100"):
        raise ValueError(f"RD.TARGET.PLATFORM: {target.platform!r}")
    path = f"{target.program_name}{'.pln' if platform == 'chroma' else '.prg'}"
    blocks = _render_blocks(plan.declarations)
    sections = () if not blocks else (SectionFragment(
        path,
        "GLOBALS",
        f"runtime-declarations:{plan.identity}",
        (("// Typed runtime declarations\r\n" + "\r\n\r\n".join(blocks) + "\r\n\r\n").encode("gbk")),
        order=50,
    ),)
    return ProgramContribution(
        identity=f"runtime-declarations:{target.identity}",
        target=target,
        sections=sections,
    )


def _render_blocks(declarations) -> tuple[str, ...]:
    groups = {}
    for declaration in declarations:
        page = None
        if declaration.kind is DeclarationKind.REGISTER_IMAGE:
            page = str(declaration.page or "").strip()
            if not page:
                raise ValueError(
                    f"RD.REGISTER_IMAGE.PAGE_MISSING: {declaration.name}"
                )
        groups.setdefault((declaration.kind, page), []).append(declaration)
    return tuple(
        "\r\n".join((_group_title(kind, page), *_render_lines(items)))
        for (kind, page), items in groups.items()
    )


def _group_title(kind: DeclarationKind, page: str | None) -> str:
    if kind is DeclarationKind.REGISTER_IMAGE:
        return f"// Addr Map page: {page}"
    return {
        DeclarationKind.DAC_FINAL: "// Trim DAC final",
        DeclarationKind.EXPORT: "// Export variables",
        DeclarationKind.BUILD_UID: "// Build UID variables",
        DeclarationKind.RUNTIME: "// Runtime variables",
    }[kind]


def _render_lines(declarations) -> tuple[str, ...]:
    lines = []
    current_type = None
    current = []
    for declaration in declarations:
        c_type, declarator = _declarator(declaration)
        if current and (c_type != current_type or len(current) == 4):
            lines.append(f"{current_type} {','.join(current)};")
            current = []
        current_type = c_type
        current.append(declarator)
    if current:
        lines.append(f"{current_type} {','.join(current)};")
    return tuple(lines)


def _declarator(declaration) -> tuple[str, str]:
    value_type = str(declaration.value_type).strip().upper()
    if value_type == "CHAR":
        if not declaration.bit_width:
            raise ValueError(f"RD.CHAR.LENGTH_MISSING: {declaration.name}")
        return "char", f"{declaration.name}[{declaration.bit_width}]"
    c_type = {"INT": "int", "DOUBLE": "double"}.get(value_type)
    if c_type is None:
        raise ValueError(
            f"RD.VALUE_TYPE.UNSUPPORTED: {declaration.name} {value_type}"
        )
    suffix = (
        "[MAX_SITE]"
        if declaration.cardinality is SymbolCardinality.SITE
        else ""
    )
    return c_type, f"{declaration.name}{suffix}"


__all__ = ["compile_runtime_declaration_contribution"]
