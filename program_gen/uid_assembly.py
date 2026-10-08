"""UID and ID native assemblies consume only ProductCompiler plans."""

from program_gen.registered_recipe_modules import NATIVE_RECIPE_MODULE_REGISTRY as MODULES
from program_gen.render_plan import (LifecycleAction, ProgramContribution, RenderSymbolRef,
    ScheduleEntryContribution, SectionFragment, SymbolRequirement, TestDefinitionContribution)
from program_gen.skeleton import SkeletonBody
from program_gen.typed_kind_registry import TypedKindAssembly
from program_gen.trimdata_write_assembly import _render_body


def compile_uid_assembly(plans, context):
    return _compile("UID", plans, context)


def compile_id_assembly(plans, context):
    return _compile("ID", plans, context)


def _compile(kind, plans, context):
    if not plans:
        return TypedKindAssembly(kind)
    context.compilation.require_success()
    target = context.target
    platform = target.platform.casefold()
    if platform not in ("chroma", "s100"):
        raise ValueError(f"{kind}.PLATFORM.INVALID: {platform}")
    schedule = context.compilation.for_cp(target.cp).canonical_schedule
    path = target.program_name + (".pln" if platform == "chroma" else ".prg")
    contributions, bodies = [], []
    for plan in plans:
        if plan.cp.casefold() != target.cp.casefold():
            raise ValueError(f"{kind}.CP.MISMATCH")
        definition = next(d for d in schedule.definitions if plan.excel_row in d.source_rows)
        ordinal, entry = next((i, e) for i, e in enumerate(schedule.entries)
                              if e.definition_id == definition.identity)
        owner = f"{kind.lower()}:{target.identity}:{definition.identity}"
        ref = RenderSymbolRef("TEST_BODY", f"{platform}:{entry.identity}")
        emissions = tuple(MODULES.emit(step.module, step.module_plan, platform) for step in plan.steps)
        resources = [r for e in emissions for r in e.resource_requires]
        requires = [r for e in emissions for r in e.requires]
        sections, lifecycle = [], []
        if kind == "UID":
            enter = MODULES.emit("RUN", plan.enter_fbist_mode, platform)
            if any(step.module in ("READOTPMAP", "CHECKOTP") for step in plan.steps):
                resources.extend(enter.resource_requires)
            source = _uid_body(definition.render_name, plan, emissions, enter,
                               platform, entry.bin_binding.hardware_bin)
            if plan.gate_symbol:
                requires.append(SymbolRequirement(RenderSymbolRef("ID_GATE", f"{plan.cp}:{plan.gate_symbol}"),
                                                  "BOOL", 1, "SITE"))
            for step in plan.steps:
                if step.module != "BUILDUID":
                    continue
                if platform == "chroma":
                    from program_gen.platforms.chroma.build_uid_adapter import render_build_uid_support
                else:
                    from program_gen.platforms.s100.build_uid_adapter import render_build_uid_support
                globals_text, helpers, startup, test_start = render_build_uid_support(step.module_plan)
                sections.extend(SectionFragment(path, section, f"{owner}:{section}", _encode(text), order=60)
                                for section, text in (("GLOBALS", globals_text), ("HELPERS", helpers)) if text)
                lifecycle.extend(LifecycleAction(hook, f"{owner}:{hook}", text.replace("\n", "\r\n"))
                                 for hook, text in (("START_UP", startup), ("TEST_START", test_start)) if text)
        else:
            source = _render_body(definition.render_name, plan.test_number, emissions,
                                  platform, entry.bin_binding.hardware_bin)
            gate = plan.steps[0].module_plan.gate_symbol
            if gate:
                declaration = f"LUINT {gate};" if platform == "chroma" else f"int {gate}[MAX_SITE];"
                sections.append(SectionFragment(path, "GLOBALS", f"{owner}:gate", _encode(declaration + "\n"), 60))
        requires.append(SymbolRequirement(ref, "SECTION", None, "TARGET"))
        contributions.append(ProgramContribution(
            identity=owner, target=target, sections=tuple(sections), lifecycle_actions=tuple(lifecycle),
            definitions=(TestDefinitionContribution(definition.identity, kind, owner),),
            schedule_entries=(ScheduleEntryContribution(entry.identity, definition.identity, ordinal, entry.enabled),),
            resource_requires=tuple(resources), provides=tuple(p for e in emissions for p in e.provides),
            requires=tuple(requires),
        ))
        bodies.append(SkeletonBody(ref, SectionFragment(path, "TESTS", f"{owner}:body", _encode(source), ordinal)))
    return TypedKindAssembly(kind, tuple(contributions), tuple(bodies))


def _uid_body(name, plan, emissions, enter, platform, hardware_bin):
    from program_gen.recipe_module_registry import RecipeModuleEmission
    lines = []
    gated = False
    for step, emission in zip(plan.steps, emissions):
        if step.gated and not gated:
            gated = True
            if platform == "chroma":
                lines.extend((f"  SOCKET_SET(B:{plan.gate_symbol},FRZ_OFF)", "  {"))
            else:
                lines.extend(("  {", "  int uidPreviousSites[MAX_SITE],uidPending=0;",
                    "  for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)", "  {",
                    "    uidPreviousSites[T_SOCKET]=Sys_ActiveSite[T_SOCKET];",
                    f"    Sys_ActiveSite[T_SOCKET]=uidPreviousSites[T_SOCKET] && {plan.gate_symbol}[T_SOCKET];",
                    "    uidPending=uidPending || Sys_ActiveSite[T_SOCKET];", "  }", "  if(uidPending)", "  {"))
        if step.module in ("READOTPMAP", "CHECKOTP"):
            lines.append(f"  POWER_ON({plan.power_profile});" if platform == "chroma"
                         else f"  CALL_MACRO POWER_ON(_C_{plan.power_profile});")
            lines.extend(enter.statements)
        lines.extend(emission.statements)
        if step.module in ("READOTPMAP", "CHECKOTP"):
            lines.append("  POWER_OFF();" if platform == "chroma" else "  CALL_MACRO POWER_OFF();")
    if gated:
        lines.append("  }")
        if platform == "s100":
            lines.extend(("  for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)",
                          "    Sys_ActiveSite[T_SOCKET]=uidPreviousSites[T_SOCKET];", "  }"))
    return _render_body(name, plan.test_number, (RecipeModuleEmission(tuple(lines)),), platform, hardware_bin)


def _encode(text):
    return text.replace("\r\n", "\n").replace("\n", "\r\n").encode("gbk")
