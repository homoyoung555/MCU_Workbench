"""MAIN assembly consumes ProductCompiler plans and canonical schedule only."""

from program_gen.registered_recipe_modules import NATIVE_RECIPE_MODULE_REGISTRY
from program_gen.recipe_module_registry import RecipeModuleEmission
from program_gen.render_plan import (
    ProgramContribution, RenderSymbolRef, ScheduleEntryContribution,
    SectionFragment, SymbolRequirement, TestDefinitionContribution,
)
from program_gen.skeleton import SkeletonBody
from program_gen.trimdata_write_assembly import _render_body
from program_gen.typed_kind_registry import TypedKindAssembly, TypedKindContext


def compile_main_assembly(plans, context: TypedKindContext) -> TypedKindAssembly:
    plans = tuple(plans)
    if not plans:
        return TypedKindAssembly("MAIN")
    context.compilation.require_success()
    target = context.target
    platform = target.platform.casefold()
    if platform not in ("chroma", "s100"):
        raise ValueError(f"TK.MAIN.PLATFORM: {target.platform!r}")
    schedule = context.compilation.for_cp(target.cp).canonical_schedule
    contributions, bodies = [], []
    for plan in plans:
        if plan.cp.casefold() != target.cp.casefold():
            raise ValueError(f"TK.MAIN.CP_MISMATCH: {plan.cp!r}")
        definition = next(item for item in schedule.definitions
                          if item.cp.casefold() == plan.cp.casefold() and plan.excel_row in item.source_rows)
        ordinal, entry = next((index, item) for index, item in enumerate(schedule.entries)
                              if item.definition_id == definition.identity)
        emissions = tuple(NATIVE_RECIPE_MODULE_REGISTRY.emit(step.module, step.module_plan, platform)
                          for step in plan.steps)
        ref = RenderSymbolRef("TEST_BODY", f"{platform}:{entry.identity}")
        owner = f"main:{target.identity}:{definition.identity}"
        contributions.append(ProgramContribution(
            identity=owner, target=target,
            definitions=(TestDefinitionContribution(definition.identity, "MAIN", owner),),
            schedule_entries=(ScheduleEntryContribution(entry.identity, definition.identity, ordinal, entry.enabled),),
            resource_requires=tuple(r for emission in emissions for r in emission.resource_requires),
            provides=tuple(p for emission in emissions for p in emission.provides),
            requires=(*(r for emission in emissions for r in emission.requires),
                      SymbolRequirement(ref, "SECTION", None, "TARGET")),
        ))
        header = (RecipeModuleEmission((f'  TEST_NO(TEST_NUM);DATALOG_MSG="{definition.render_name}";',)),) \
            if platform == "chroma" else ()
        source = _render_body(definition.render_name, plan.test_number, (*header, *emissions),
                              platform, entry.bin_binding.hardware_bin)
        extension = ".pln" if platform == "chroma" else ".prg"
        bodies.append(SkeletonBody(ref, SectionFragment(
            f"{target.program_name}{extension}", "TESTS", f"{owner}:body",
            source.replace("\r\n", "\n").replace("\n", "\r\n").encode("gbk"), ordinal,
        )))
    return TypedKindAssembly("MAIN", tuple(contributions), tuple(bodies))
