"""STANDARD_TRIM platform support excluding business runtime declarations."""

from __future__ import annotations

from program_gen.render_plan import (
    ProgramContribution, RenderSymbolRef, SectionFragment, SymbolProvision,
)


def compile_standard_trim_support(
    target,
    specs,
    write_regions,
    *,
    provided_target_references=(),
) -> ProgramContribution:
    platform = target.platform.casefold()
    path = f"{target.program_name}{'.pln' if platform == 'chroma' else '.prg'}"
    specs = tuple(specs)
    globals_text = _globals(
        platform,
        specs,
        provided_target_references=provided_target_references,
    )
    helpers = {}
    for spec in specs:
        name = spec.dac.helper_name
        content = _helper(platform, spec, write_regions[spec.dac.pattern_name])
        if name in helpers and helpers[name] != content:
            raise ValueError(f"STN.HELPER_CONFLICT: {name}")
        helpers[name] = content
    helpers_text = "".join(helpers.values())
    return ProgramContribution(
        identity=f"standard-trim:support:{target.identity}",
        target=target,
        sections=(
            *((SectionFragment(
                path, "GLOBALS", "standard-trim:globals",
                globals_text.encode("gbk"), order=100,
            ),) if globals_text else ()),
            SectionFragment(path, "HELPERS", "standard-trim:helpers", helpers_text.encode("gbk")),
        ),
        provides=tuple(SymbolProvision(
            RenderSymbolRef("HELPER", name), name,
            "CALLABLE", None, "TARGET",
        ) for name in helpers),
    )


def _globals(platform, specs, *, provided_target_references=()):
    provided = {str(name).strip() for name in provided_target_references}
    targets = tuple(
        (name, value) for name, value in _target_references(specs)
        if name not in provided
    )
    if platform == "chroma":
        target_text = ("// Trim target voltages\r\n" + "\r\n".join(
            f"VOLTAGE {name} = {value}V;" for name, value in targets
        )) if targets else ""
        symbols = ""
    else:
        target_text = ("// Trim target voltages\r\n" + "\r\n".join(
            f"double _C_{name} = {value};" for name, value in targets
        )) if targets else ""
        symbols = "// Trim CSV globals\r\n" + "\r\n".join(
            f"char _C_{spec.item.upper()}_LOG_MSG[64];" for spec in specs
        )
    content = target_text + ("\r\n\r\n" if target_text and symbols else "") + symbols
    return content + ("\r\n\r\n" if content else "")


def _helper(platform, spec, region):
    if not spec.dac.write_pin:
        raise ValueError(f"STN.{platform.upper()}.HELPER_PIN: {spec.item}")
    if platform == "chroma":
        return (
            f"{spec.dac.helper_name}(int* b)\r\n{{\r\n  SOCKET_INC(FRZ_OFF)\r\n  {{\r\n"
            f"    TRIM_DIGIT={spec.dac.field_width}-1;\r\n    TEMP=b[SOCKET];\r\n"
            "    for(J=0;J<=TRIM_DIGIT;J++){BIT[J]=TEMP%2;TEMP=TEMP/2;}\r\n"
            "    for(J=TRIM_DIGIT;J>=0;J--)\r\n    {\r\n"
            f"      if(BIT[J]==0) WRITE_PAT_MEM(SOCKET,{spec.dac.write_pin},{spec.dac.pattern_name}:{region.base_label}+TRIM_DIGIT-J,,\"0\");\r\n"
            f"      else WRITE_PAT_MEM(SOCKET,{spec.dac.write_pin},{spec.dac.pattern_name}:{region.base_label}+TRIM_DIGIT-J,,\"1\");\r\n"
            "    }\r\n  }\r\n  TEST_NUM++;\r\n"
            f"  TEST_NO(TEST_NUM);DATALOG_MSG=\"{spec.dac.pattern_name}\";\r\n"
            f"  JUDGE_PAT({spec.dac.pattern_name},__{spec.dac.pattern_name});\r\n}}\r\n\r\n"
        )
    return (
        f"@@MACRO {spec.dac.helper_name}(int* a)\r\n"
        "  for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\r\n  {\r\n"
        "    GB[0+T_SOCKET*64]=a[T_SOCKET];\r\n  }\r\n"
        f"  LOGIC_WRITE_PATTERN_MEMORY({spec.dac.pattern_name}:{region.start_label},"
        f"{spec.dac.pattern_name}:{region.end_label},{spec.dac.write_pin},GB1,"
        f"BIT_COUNT={spec.dac.field_width},SERIAL,FAST_MODE,VERIFY_DATA);\r\n"
        f"  RUN_PATTERN({spec.dac.pattern_name}:START,{spec.dac.pattern_name}:END,1,TS_5MHZ);\r\n"
        "@@END_MACRO\r\n\r\n"
    )


def _target_references(specs):
    values = {}
    for spec in specs:
        if spec.trim_tar_reference:
            values.setdefault(spec.trim_tar_reference, spec.measurement.target)
    return tuple(values.items())


__all__ = ["compile_standard_trim_support"]
