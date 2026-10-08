"""TRIMDATA_READ plans to native assembly without workbook access."""

from program_gen.core.run_pattern import PatternResourceRef, PatternSpan, RunPatternPlan
from program_gen.registered_recipe_modules import NATIVE_RECIPE_MODULE_REGISTRY
from program_gen.render_plan import (
    ProgramContribution, RenderSymbolRef, ScheduleEntryContribution,
    SectionFragment, SymbolRequirement, TestDefinitionContribution,
)
from program_gen.skeleton import SkeletonBody
from program_gen.typed_kind_registry import TypedKindAssembly, TypedKindContext


def compile_trimdata_read_assembly(plans, context: TypedKindContext) -> TypedKindAssembly:
    plans = tuple(plans)
    if not plans:
        return TypedKindAssembly("TRIMDATA_READ")
    context.compilation.require_success()
    target = context.target
    platform = target.platform.casefold()
    if platform not in ("chroma", "s100"):
        raise ValueError(f"TK.TRIMDATA_READ.PLATFORM: {target.platform!r}")
    schedule = context.compilation.for_cp(target.cp).canonical_schedule
    contributions = []
    bodies = []
    for plan in plans:
        definition = next(
            item for item in schedule.definitions
            if item.cp.casefold() == plan.cp.casefold() and plan.excel_row in item.source_rows
        )
        entry = next(item for item in schedule.entries if item.definition_id == definition.identity)
        ordinal = next(index for index, item in enumerate(schedule.entries) if item.identity == entry.identity)
        emissions = tuple(
            NATIVE_RECIPE_MODULE_REGISTRY.emit(step.module, step.module_plan, platform)
            for step in plan.steps
        )
        enter = NATIVE_RECIPE_MODULE_REGISTRY.emit("RUN", _run("enter_fbist_mode"), platform)
        all_emissions = (*emissions, *(enter for step in plan.steps if step.module in ("READOTPMAP", "CHECKOTP")))
        ref = RenderSymbolRef("TEST_BODY", f"{platform}:{entry.identity}")
        owner = f"trimdata-read:{target.identity}:{definition.identity}"
        extension = ".pln" if platform == "chroma" else ".prg"
        contributions.append(ProgramContribution(
            identity=owner,
            target=target,
            definitions=(TestDefinitionContribution(definition.identity, "TRIMDATA_READ", owner),),
            schedule_entries=(ScheduleEntryContribution(entry.identity, definition.identity, ordinal, entry.enabled),),
            resource_requires=tuple(
                requirement for emission in all_emissions for requirement in emission.resource_requires
            ),
            provides=tuple(provision for emission in emissions for provision in emission.provides),
            requires=(SymbolRequirement(ref, "SECTION", None, "TARGET"),),
        ))
        body = _render_body(
            definition.render_name, plan, emissions, enter, platform,
            entry.bin_binding.hardware_bin,
        )
        bodies.append(SkeletonBody(ref, SectionFragment(
            f"{target.program_name}{extension}", "TESTS", f"{owner}:body",
            body.replace("\r\n", "\n").replace("\n", "\r\n").encode("gbk"),
            order=ordinal,
        )))
    return TypedKindAssembly("TRIMDATA_READ", tuple(contributions), tuple(bodies))


def _render_body(name, plan, emissions, enter, platform, hardware_bin):
    lines = (
        [f"{name}()", "{", f"  TEST_NUM={plan.test_number};"]
        if platform == "chroma" else [
            f"@@PLAN {name}", "\tSITE_SEQUENCE      = OFF;", "\tGO_THROUGH         = ON;",
            "\tDISABLE_BY_MARK_NO = NULL;", "\tS_SETUP_FILE       = c:\\set.dat;",
            f"\tREMARK             = {name};", "",
        ]
    )
    power_on = (
        f"  POWER_ON({plan.power_profile.upper()});" if platform == "chroma"
        else f"\tCALL_MACRO POWER_ON(_C_{plan.power_profile.upper()});"
    )
    power_off = "  POWER_OFF();" if platform == "chroma" else "\tCALL_MACRO POWER_OFF();"
    for step, emission in zip(plan.steps, emissions):
        if step.module in ("READOTPMAP", "CHECKOTP"):
            lines.extend((power_on, *enter.statements))
        lines.extend(emission.statements)
        if step.module in ("READOTPMAP", "CHECKOTP"):
            lines.append(power_off)
    if platform == "chroma":
        lines.append("}")
    else:
        lines.extend(("", "\tCONDITION", "\tIF_FAIL", f"\tREJECT_BIN = {hardware_bin};", "@@END_PLAN"))
    return "\n".join(lines) + "\n"


def _run(name):
    return RunPatternPlan(
        PatternResourceRef(name, f"pattern:{name}", ("START", "END")),
        PatternSpan.full(), "TS_5MHZ",
    )


__all__ = ["compile_trimdata_read_assembly"]
