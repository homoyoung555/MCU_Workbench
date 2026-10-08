"""Shared PDR voltage profiles contributed by PDR typed kinds."""

from __future__ import annotations

from program_gen.render_plan import LifecycleAction, ProgramContribution, SectionFragment


def compile_pdr_voltage_support(
    target,
    *,
    minimum: str,
    target_voltage: str | None,
    maximum: str,
) -> ProgramContribution:
    platform = target.platform.casefold()
    roles = (("MIN", minimum), ("MAX", maximum))
    if target_voltage is not None:
        roles = (("MIN", minimum), ("TAR", target_voltage), ("MAX", maximum))
    if platform == "chroma":
        path = f"{target.program_name}.pln"
        globals_text = (
            "// PDR voltage profiles\r\n"
            + "\r\n".join(
                f"int PDR_{role}_LVL = {index + 6};"
                for index, (role, _value) in enumerate(roles)
            )
            + "\r\n\r\n"
            + "\r\n".join(
                f"VOLTAGE VCC_PDR_{role} = {value}V;"
                for role, value in roles
            )
            + "\r\n\r\n"
        )
        actions = (LifecycleAction(
            "START_UP", "pdr:voltage-levels", _chroma_level_setup(roles), 200
        ),)
    elif platform == "s100":
        path = f"{target.program_name}.prg"
        globals_text = (
            "// PDR voltage profiles\r\n"
            + "\r\n".join(
                f"double _C_VCC_PDR_{role} = {value};"
                for role, value in roles
            )
            + "\r\n\r\n"
        )
        actions = ()
    else:
        raise ValueError(f"PDR.VOLTAGE.PLATFORM: {target.platform!r}")
    return ProgramContribution(
        identity=f"pdr-voltage:{target.identity}",
        target=target,
        sections=(SectionFragment(
            path,
            "GLOBALS",
            "pdr:voltage-globals",
            globals_text.encode("gbk"),
            order=190,
        ),),
        lifecycle_actions=actions,
    )


def _chroma_level_setup(roles) -> str:
    lines = []
    for role, _value in roles:
        lines.extend((
            f"  SET_LEVELN(PDR_{role}_LVL,IO_ALLPINS,0V,VCC_PDR_{role},VCC_PDR_{role}*0.45,VCC_PDR_{role}*0.55,0uA,0uA,VCC_PDR_{role}*0.5,,);",
            f"  SET_LEVELN(PDR_{role}_LVL,TP,0V,VCC_PDR_{role},VCC_PDR_{role}*0.35,VCC_PDR_{role}*0.5,0uA,0uA,VCC_PDR_{role}*0.5,,);",
            "",
        ))
    return "\r\n".join(lines) + "\r\n"


__all__ = ["compile_pdr_voltage_support"]
