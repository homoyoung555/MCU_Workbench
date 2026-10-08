"""TRIMDATA_WRITE plans to native assembly without workbook access."""

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


def compile_trimdata_write_assembly(plans, context: TypedKindContext) -> TypedKindAssembly:
    plans = tuple(plans)
    if not plans:
        return TypedKindAssembly("TRIMDATA_WRITE")
    context.compilation.require_success()
    target = context.target
    platform = target.platform.casefold()
    if platform not in ("chroma", "s100"):
        raise ValueError(f"TK.TRIMDATA_WRITE.PLATFORM: {target.platform!r}")
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
        ref = RenderSymbolRef("TEST_BODY", f"{platform}:{entry.identity}")
        owner = f"trimdata-write:{target.identity}:{definition.identity}"
        extension = ".pln" if platform == "chroma" else ".prg"
        contributions.append(ProgramContribution(
            identity=owner,
            target=target,
            definitions=(TestDefinitionContribution(
                definition.identity, "TRIMDATA_WRITE", owner,
            ),),
            schedule_entries=(ScheduleEntryContribution(
                entry.identity, definition.identity, ordinal, entry.enabled,
            ),),
            resource_requires=tuple(
                requirement for emission in emissions for requirement in emission.resource_requires
            ),
            provides=tuple(provision for emission in emissions for provision in emission.provides),
            requires=(
                *(requirement for emission in emissions for requirement in emission.requires),
                SymbolRequirement(ref, "SECTION", None, "TARGET"),
            ),
        ))
        bodies.append(SkeletonBody(ref, SectionFragment(
            f"{target.program_name}{extension}",
            "TESTS",
            f"{owner}:body",
            _render_body(
                definition.render_name,
                plan.test_number,
                emissions,
                platform,
                entry.bin_binding.hardware_bin,
            ).replace("\r\n", "\n").replace("\n", "\r\n").encode("gbk"),
            order=ordinal,
        )))
    return TypedKindAssembly("TRIMDATA_WRITE", tuple(contributions), tuple(bodies))


def _render_body(name, test_number, emissions, platform, hardware_bin):
    if platform == "chroma":
        lines = [f"{name}()", "{", f"  TEST_NUM={test_number};"]
    else:
        lines = [
            f"@@PLAN {name}",
            "\tSITE_SEQUENCE      = OFF;",
            "\tGO_THROUGH         = ON;",
            "\tDISABLE_BY_MARK_NO = NULL;",
            "\tS_SETUP_FILE       = c:\\set.dat;",
            f"\tREMARK             = {name};",
            "",
        ]
    lines.extend(line for emission in emissions for line in emission.statements)
    if platform == "chroma":
        lines.append("}")
    else:
        lines.extend((
            "", "\tCONDITION", "\tIF_FAIL",
            f"\tREJECT_BIN = {hardware_bin};", "@@END_PLAN",
        ))
    return "\n".join(lines) + "\n"


__all__ = ["compile_trimdata_write_assembly"]
