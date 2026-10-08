"""Assemble PVD hysteresis plans into native tester program bodies."""

from program_gen.core.firmware_render import FirmwareBodyRender
from program_gen.render_plan import (
    ProgramContribution,
    RenderSymbolRef,
    ScheduleEntryContribution,
    SectionFragment,
    SymbolRequirement,
    TestDefinitionContribution,
)
from program_gen.skeleton import SkeletonBody
from program_gen.typed_kind_registry import TypedKindAssembly, TypedKindContext


def compile_pvd_test_assembly(
    plans,
    context: TypedKindContext,
    renderer=None,
) -> TypedKindAssembly:
    plans = tuple(plans)
    if not plans:
        return TypedKindAssembly("PVD_TEST")
    context.compilation.require_success()
    platform = context.target.platform.strip().casefold()
    render = renderer if renderer is not None else _renderer_for(platform)
    schedule = context.compilation.for_cp(context.target.cp).canonical_schedule
    extension = ".pln" if platform == "chroma" else ".prg"
    contributions = []
    bodies = []

    for plan in plans:
        if plan.typed_kind != "PVD_TEST":
            raise ValueError(
                "PVD.ASSEMBLY.KIND_MISMATCH: "
                f"expected 'PVD_TEST', got {plan.typed_kind!r}"
            )
        if plan.cp.casefold() != context.target.cp.casefold():
            raise ValueError(
                "PVD.ASSEMBLY.CP_MISMATCH: "
                f"plan belongs to {plan.cp!r}, not {context.target.cp!r}"
            )
        definition = _one_definition(schedule, plan)
        entry = _one_entry(schedule, definition.identity)
        ordinal = next(
            index
            for index, candidate in enumerate(schedule.entries)
            if candidate.identity.casefold() == entry.identity.casefold()
        )
        identity = f"pvd-test:{context.target.identity}:{definition.identity}"
        body_ref = RenderSymbolRef("TEST_BODY", f"{platform}:{entry.identity}")
        rendered = render(
            plan,
            definition.render_name,
            entry.bin_binding.hardware_bin,
            context.platform_facts,
        )
        if not isinstance(rendered, FirmwareBodyRender):
            raise TypeError("PVD renderer must return FirmwareBodyRender")

        contribution = ProgramContribution(
            identity=identity,
            target=context.target,
            sections=_chroma_shmoo_support(
                context.target,
                context.platform_facts,
                identity,
            ) if platform == "chroma" else (),
            resources=rendered.resources,
            resource_requires=rendered.resource_requires,
            definitions=(TestDefinitionContribution(
                definition.identity,
                "PVD_TEST",
                identity,
            ),),
            schedule_entries=(ScheduleEntryContribution(
                entry.identity,
                definition.identity,
                ordinal,
                entry.enabled,
            ),),
            requires=(SymbolRequirement(body_ref, "SECTION", None, "TARGET"),),
        )
        fragment = SectionFragment(
            f"{context.target.program_name}{extension}",
            "TESTS",
            f"{identity}:body",
            _encode(rendered.content),
            ordinal,
        )
        contributions.append(contribution)
        bodies.append(SkeletonBody(body_ref, fragment))

    return TypedKindAssembly("PVD_TEST", tuple(contributions), tuple(bodies))


def _one_definition(schedule, plan):
    matches = tuple(
        definition
        for definition in schedule.definitions
        if definition.cp.casefold() == plan.cp.casefold()
        and definition.item.casefold() == plan.item.casefold()
        and definition.source_rows == plan.excel_rows
    )
    if len(matches) != 1:
        raise ValueError(
            "PVD.ASSEMBLY.DEFINITION_UNRESOLVED: canonical schedule contains "
            f"{len(matches)} matches for {plan.cp}/{plan.item} {plan.excel_rows}"
        )
    return matches[0]


def _one_entry(schedule, definition_identity):
    matches = tuple(
        entry for entry in schedule.entries
        if entry.definition_id.casefold() == definition_identity.casefold()
    )
    if len(matches) != 1:
        raise ValueError(
            "PVD.ASSEMBLY.SCHEDULE_UNRESOLVED: canonical schedule contains "
            f"{len(matches)} entries for {definition_identity!r}"
        )
    return matches[0]


def _renderer_for(platform):
    if platform == "chroma":
        from program_gen.platforms.chroma.pvd_test_renderer import render_pvd_test
    elif platform == "s100":
        from program_gen.platforms.s100.pvd_test_renderer import render_pvd_test
    else:
        raise ValueError(f"PVD.ASSEMBLY.PLATFORM_INVALID: {platform!r}")
    return render_pvd_test


def _chroma_shmoo_support(target, facts, owner):
    """Contribute the variable-voltage helper required by PVD point sweeps."""
    path = f"{target.program_name}.pln"
    rails = tuple(str(rail).strip() for rail in facts.force_rails)
    if not rails or any(not rail for rail in rails):
        raise ValueError("PVD.CHROMA.SHMOO.RAIL_MISSING: force rails are required")
    force = "\n".join(
        f"  FORCE_V_MLDPS({rail},vccVolt,@6V,@500mA,200mA,NORM,ON,2mS);"
        for rail in rails
    )
    helper = (
        "POWER_Shmoo_ON(double vccVolt)\n"
        "{\n"
        "  LEVELS(RST_LVL,3mS);\n"
        "  RELAY_ON(IO_ALLPINS,PDCL,2mS);\n"
        f"{force}\n"
        "  PIN_MODE(IO_ALLPINS,NRZ,EDGE,ENABLE,IO_NRZ,OFF);\n"
        f"  PIN_MODE({facts.clk_pin},RZ,EDGE,ENABLE,IO_NRZ,OFF);\n"
        "  SET_LEVELN(SHMOO_LVL,IO_ALLPINS,0.0V,vccVolt,"
        "vccVolt*0.45,vccVolt*0.55,0uA,0uA,vccVolt*0.5,,);\n"
        "  LEVELS(SHMOO_LVL,3mS);\n"
        "  WAIT(10mS);\n"
        "}\n"
    )
    return (
        SectionFragment(
            path,
            "GLOBALS",
            f"{owner}:shmoo-level",
            _encode("int SHMOO_LVL = 5;\n"),
            60,
        ),
        SectionFragment(
            path,
            "HELPERS",
            f"{owner}:shmoo-power",
            _encode(helper),
            60,
        ),
    )


def _encode(content):
    return content.replace("\r\n", "\n").replace("\n", "\r\n").encode("gbk")


__all__ = ["compile_pvd_test_assembly"]
