"""Native assembly of explicitly associated SCAN/MBIST converted artifacts."""

from __future__ import annotations

from program_gen.core.scan_test import ScanBindingSet, ScanTestPlan
from program_gen.render_plan import (
    ProgramContribution, RenderSymbolRef, ResourceRequest, ResourceRequirement,
    ScheduleEntryContribution, SectionFragment, SymbolRequirement,
    TestDefinitionContribution,
)
from program_gen.skeleton import SkeletonBody
from program_gen.typed_kind_registry import TypedKindAssembly, TypedKindContext


def compile_scan_test_assembly(plans, context: TypedKindContext) -> TypedKindAssembly:
    plans = tuple(plans)
    if not plans:
        return TypedKindAssembly("VERIFY_SCAN")
    context.compilation.require_success()
    platform = context.target.platform.casefold()
    if platform not in {"chroma", "s100"}:
        raise ValueError(f"SCAN.ASSEMBLY.PLATFORM: {platform!r}")
    bindings = context.scan_bindings if isinstance(context.scan_bindings, ScanBindingSet) else ScanBindingSet(())
    schedule = context.compilation.for_cp(context.target.cp).canonical_schedule
    extension = ".pln" if platform == "chroma" else ".prg"
    contributions, bodies = [], []
    for plan in plans:
        if not isinstance(plan, ScanTestPlan) or plan.typed_kind not in {"VERIFY_SCAN", "VERIFY_MBIST"}:
            raise ValueError("SCAN.ASSEMBLY.KIND_MISMATCH")
        binding = bindings.require(plan, context.target)
        definition = _definition(schedule, plan)
        ordinal, entry = _entry(schedule, definition.identity)
        owner = f"scan:{context.target.identity}:{definition.identity}"
        body_ref = RenderSymbolRef("TEST_BODY", f"{platform}:{entry.identity}")
        patterns = binding.artifacts_for(platform, "pattern")
        requirements = tuple(_requirement(plan, binding, platform, artifact.logical_name) for artifact in patterns)
        if platform == "chroma":
            requirements += (_chroma_reset_requirement(),)
        timing = tuple(binding.artifact(platform, "timing", artifact.logical_name) for artifact in patterns)
        code = tuple(binding.artifact(platform, "code", artifact.logical_name) for artifact in patterns)
        if platform == "chroma":
            rendered, sections = _render_chroma(plan, definition.render_name, timing, code, owner, context.target.program_name)
            timing_fragments = ()
        else:
            rendered = _render_s100(plan, definition.render_name, entry.bin_binding.hardware_bin, code)
            sections = ()
            timing_fragments = tuple(ResourceRequest(
                requirement.logical_identity,
                f"{artifact.logical_name}.scan.timing", artifact.content,
                f"scan-binding/1:{binding.configuration_fingerprint}:s100:{artifact.logical_name}",
                f"scan-binding:{binding.configuration_fingerprint}", "SCAN timing fragment",
            ) for requirement, artifact in zip(requirements, timing))
        contributions.append(ProgramContribution(
            identity=owner, target=context.target, sections=sections,
            timing_fragments=timing_fragments, resource_requires=requirements,
            definitions=(TestDefinitionContribution(definition.identity, plan.typed_kind, owner),),
            schedule_entries=(ScheduleEntryContribution(entry.identity, definition.identity, ordinal, entry.enabled),),
            requires=(SymbolRequirement(body_ref, "SECTION", None, "TARGET"),),
        ))
        bodies.append(SkeletonBody(body_ref, SectionFragment(
            f"{context.target.program_name}{extension}", "TESTS", f"{owner}:body",
            _encode(rendered), ordinal,
        )))
    kind = plans[0].typed_kind
    if any(plan.typed_kind != kind for plan in plans):
        raise ValueError("SCAN.ASSEMBLY.MIXED_KIND")
    return TypedKindAssembly(kind, tuple(contributions), tuple(bodies))


def _definition(schedule, plan):
    matches = tuple(value for value in schedule.definitions if value.cp.casefold() == plan.cp.casefold() and value.item.casefold() == plan.item.casefold() and value.source_rows == plan.excel_rows)
    if len(matches) != 1:
        raise ValueError(f"SCAN.ASSEMBLY.DEFINITION_UNRESOLVED: {plan.cp}/{plan.item}")
    return matches[0]


def _entry(schedule, definition_id):
    matches = tuple((index, value) for index, value in enumerate(schedule.entries) if value.definition_id.casefold() == definition_id.casefold())
    if len(matches) != 1:
        raise ValueError(f"SCAN.ASSEMBLY.SCHEDULE_UNRESOLVED: {definition_id}")
    return matches[0]


def _requirement(plan, binding, platform, logical_name):
    suffix = ".pat" if platform == "chroma" else ".sd"
    return ResourceRequirement(
        f"scan:{plan.cp}:{plan.item}:{plan.typed_kind}:{platform}:{logical_name}",
        (f"pat/{logical_name}{suffix}" if platform == "chroma" else f"{logical_name}{suffix}"),
        f"scan-binding/1:{binding.configuration_fingerprint}:{platform}:{logical_name}",
        "SCAN converted Pattern",
    )


def _chroma_reset_requirement():
    return ResourceRequirement(
        "scan-reset-pattern", "pat/reset_pattern.pat", "v14.scan-reset/1",
        "SCAN fixed cleanup Pattern",
    )


def _render_chroma(plan, name, timing, code, owner, program_name):
    lines = [f"{name}()", "{", f"  POWER_ON({plan.power_profile});"]
    for timing_artifact, code_artifact in zip(timing, code):
        lines.append("  {")
        lines.extend("  " + line if line else "" for line in _text(timing_artifact.content).splitlines())
        lines.extend("  " + line if line else "" for line in _chroma_statements(code_artifact.content).splitlines())
        lines.append("  }")
    lines.extend((
        "  RELAY_ON(IO_ALLPINS,PDCL,2mS);",
        "  JUDGE_PAT(reset_pattern,__reset_pattern);",
        "  POWER_OFF();", "}",
    ))
    sections = tuple(SectionFragment(
        f"{program_name}.pln", "HELPERS", f"{owner}:code:{artifact.logical_name}",
        _encode(_text(artifact.content)), 0,
    ) for artifact in ())
    return "\n".join(lines) + "\n", sections


def _render_s100(plan, name, hardware_bin, code):
    if isinstance(hardware_bin, bool) or not str(hardware_bin).strip().isdigit():
        raise ValueError(f"SCAN.S100.BIN_INVALID: {hardware_bin!r}")
    lines = [f"@@PLAN {name}", "\tSITE_SEQUENCE      = OFF;", "\tGO_THROUGH         = ON;", "\tDISABLE_BY_MARK_NO = NULL;", "\tS_SETUP_FILE       = c:\\set.dat;", f"\tREMARK             = {name};", "", f"\tCALL_MACRO POWER_ON(_C_{plan.power_profile});", "\tWAIT(3MS);"]
    for artifact in code:
        lines.extend(_s100_statements(artifact.content))
    lines.extend(("\tCALL_MACRO POWER_OFF();", "\tCONDITION", "\tIF_FAIL", f"\tREJECT_BIN = {int(str(hardware_bin).strip())};", "@@END_PLAN"))
    return "\n".join(lines) + "\n"


def _chroma_statements(content):
    text = _text(content).replace("\r\n", "\n")
    start, end = text.find("{"), text.rfind("}")
    if start < 1 or end <= start:
        raise ValueError("SCAN.CHROMA.CODE_INVALID")
    return text[start + 1:end].strip()


def _s100_statements(content):
    lines = _text(content).replace("\r\n", "\n").splitlines()
    statements = tuple(line for line in lines if line.strip())
    if not statements or any(line.strip().startswith("@@") for line in statements):
        raise ValueError("SCAN.S100.CODE_INVALID")
    return statements


def _text(content):
    return bytes(content).decode("utf-8", errors="strict")


def _encode(content):
    return content.replace("\r\n", "\n").replace("\n", "\r\n").encode("gbk")


__all__ = ["compile_scan_test_assembly"]
