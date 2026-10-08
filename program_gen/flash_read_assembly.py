"""Shared assembly of compiler-owned Flash read tests and canonical schedule."""

from program_gen.registered_recipe_modules import NATIVE_RECIPE_MODULE_REGISTRY
from program_gen.recipe_module_registry import RecipeModuleEmission
from program_gen.render_plan import (
    ProgramContribution, RenderSymbolRef, ScheduleEntryContribution,
    SectionFragment, SymbolRequirement, TestDefinitionContribution,
)
from program_gen.skeleton import SkeletonBody
from program_gen.trimdata_write_assembly import _render_body
from program_gen.typed_kind_registry import TypedKindAssembly


def compile_flash_read_assembly(plans, context, *, kind, module):
    plans = tuple(plans)
    if not plans:
        return TypedKindAssembly(kind)
    context.compilation.require_success()
    target = context.target
    platform = target.platform.casefold()
    if platform not in ("chroma", "s100"):
        raise ValueError(f"TK.{kind}.PLATFORM: {target.platform!r}")
    if "TP" not in context.platform_facts.io_pins:
        raise ValueError(f"TK.{kind}.PIN_MISSING: TP")
    schedule = context.compilation.for_cp(target.cp).canonical_schedule
    contributions, bodies = [], []
    path = target.program_name + (".pln" if platform == "chroma" else ".prg")
    for plan in plans:
        if plan.cp.casefold() != target.cp.casefold():
            raise ValueError(f"TK.{kind}.CP_MISMATCH: {plan.cp!r}")
        definition = next(d for d in schedule.definitions if plan.excel_row in d.source_rows)
        ordinal, entry = next((i, e) for i, e in enumerate(schedule.entries)
                              if e.definition_id == definition.identity)
        emission = NATIVE_RECIPE_MODULE_REGISTRY.emit(module, plan.test, platform)
        owner = f"{kind.lower()}:{target.identity}:{definition.identity}"
        ref = RenderSymbolRef("TEST_BODY", f"{platform}:{entry.identity}")
        contributions.append(ProgramContribution(
            identity=owner, target=target,
            definitions=(TestDefinitionContribution(definition.identity, kind, owner),),
            schedule_entries=(ScheduleEntryContribution(entry.identity, definition.identity, ordinal, entry.enabled),),
            resource_requires=emission.resource_requires,
            provides=emission.provides,
            requires=(*emission.requires, SymbolRequirement(ref, "SECTION", None, "TARGET")),
        ))
        header = (RecipeModuleEmission((f'  TEST_NO(TEST_NUM);DATALOG_MSG="{definition.render_name}";',)),) \
            if platform == "chroma" else ()
        source = _render_body(definition.render_name, plan.test_number, (*header, emission),
                              platform, entry.bin_binding.hardware_bin)
        bodies.append(SkeletonBody(ref, SectionFragment(
            path, "TESTS", f"{owner}:body",
            source.replace("\r\n", "\n").replace("\n", "\r\n").encode("gbk"), ordinal,
        )))
    return TypedKindAssembly(kind, tuple(contributions), tuple(bodies))
