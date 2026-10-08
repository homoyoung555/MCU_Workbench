"""DAC_ADJUST action plans to native assembly without workbook access."""

from program_gen.registered_recipe_modules import NATIVE_RECIPE_MODULE_REGISTRY
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


def compile_dac_adjust_assembly(plans, context: TypedKindContext) -> TypedKindAssembly:
    plans = tuple(plans)
    if not plans:
        return TypedKindAssembly("DAC_ADJUST")
    context.compilation.require_success()
    target = context.target
    platform = target.platform.casefold()
    if platform not in ("chroma", "s100"):
        raise ValueError(f"TK.DAC_ADJUST.PLATFORM: {target.platform!r}")
    schedule = context.compilation.for_cp(target.cp).canonical_schedule
    contributions = []
    bodies = []
    for plan in plans:
        definition = next(
            item for item in schedule.definitions
            if item.cp.casefold() == plan.cp.casefold()
            and plan.excel_row in item.source_rows
        )
        entry = next(
            item for item in schedule.entries
            if item.definition_id == definition.identity
        )
        ordinal = next(
            index for index, item in enumerate(schedule.entries)
            if item.identity == entry.identity
        )
        emissions = tuple(
            NATIVE_RECIPE_MODULE_REGISTRY.emit(
                step.module, step.module_plan, platform
            )
            for step in plan.steps
        )
        ref = RenderSymbolRef("TEST_BODY", f"{platform}:{entry.identity}")
        owner = f"dac-adjust:{target.identity}:{definition.identity}"
        extension = ".pln" if platform == "chroma" else ".prg"
        contributions.append(ProgramContribution(
            identity=owner,
            target=target,
            definitions=(TestDefinitionContribution(
                definition.identity, "DAC_ADJUST", owner,
            ),),
            schedule_entries=(ScheduleEntryContribution(
                entry.identity, definition.identity, ordinal, entry.enabled,
            ),),
            resource_requires=tuple(
                requirement
                for emission in emissions
                for requirement in emission.resource_requires
            ),
            provides=tuple(
                provision for emission in emissions
                for provision in emission.provides
            ),
            requires=(SymbolRequirement(ref, "SECTION", None, "TARGET"),),
        ))
        body = _render_body(definition.render_name, emissions, platform)
        bodies.append(SkeletonBody(ref, SectionFragment(
            f"{target.program_name}{extension}",
            "TESTS",
            f"{owner}:body",
            body.replace("\r\n", "\n").replace("\n", "\r\n").encode("gbk"),
            order=ordinal,
        )))
    return TypedKindAssembly("DAC_ADJUST", tuple(contributions), tuple(bodies))


def _render_body(name, emissions, platform):
    statements = tuple(
        line for emission in emissions for line in emission.statements
    )
    if platform == "chroma":
        lines = [f"{name}()", "{", *statements, "}"]
    else:
        lines = [
            f"@@PLAN {name}",
            "\tSITE_SEQUENCE      = OFF;",
            "\tGO_THROUGH         = ON;",
            "\tDISABLE_BY_MARK_NO = NULL;",
            "\tS_SETUP_FILE       = c:\\set.dat;",
            f"\tREMARK             = {name};",
            "",
            *statements,
            "@END_PLAN",
        ]
    return "\n".join(lines) + "\n"


__all__ = ["compile_dac_adjust_assembly"]
