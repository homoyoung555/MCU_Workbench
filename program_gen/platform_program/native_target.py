"""Compose every typed kind for one target into a complete native RenderPlan."""

from __future__ import annotations

from program_gen.platform_program.builder import PlatformProgramBuilder
from program_gen.platform_program.contracts import ProgramAssemblyInput
from program_gen.registered_typed_kinds import NATIVE_TYPED_KIND_REGISTRY
from program_gen.system_tests import compile_system_read_assembly
from program_gen.typed_kind_registry import TypedKindContext
from program_gen.core.pattern_link_names import project_specialized_plan


class NativeTargetCompositionError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


_CATALOG_BY_KIND = {
    "STANDARD_TRIM": "trim_specs",
    "PDR_TRIM": "dedicated_trim_plans",
    "STANDARD_VERIFY": "standard_verify_plans",
    "DAC_ADJUST": "dac_adjust_plans",
    "FLASH_WINDOW": "flash_window_plans",
    "TRIMDATA_READ": "trimdata_read_plans",
    "TRIMDATA_WRITE": "trimdata_write_plans",
    "UID": "uid_plans",
    "ID": "id_module_plans",
    "MAIN": "main_plans",
    "VT": "vt_plans",
    "MARGIN": "margin_plans",
    "PVD_TEST": "pvd_test_plans",
    "ADC_TEST": "adc_test_plans",
    "DC_PARAMETRIC_TEST": "dc_parametric_plans",
    "DC_VIH_VIL": "vih_vil_plans",
    "FREQ_TEST": "freq_test_plans",
    "OPA_TEST": "opa_test_plans",
    "DAC_TEST": "dac_test_plans",
    "VERIFY_SCAN": "scan_test_plans",
    "VERIFY_MBIST": "scan_test_plans",
}
_PLATFORM_CATALOG_BY_KIND = {
    "OS": "os_plans",
    "PDR_VERIFY": "pdr_verify_plans",
}
_FIRMWARE_KINDS = frozenset((
    "CODE_DOWNLOAD",
    "FIRMWARE_FUNCTION_TEST",
    "FIRMWARE_RUN_TEST",
))
_SYSTEM_KINDS = frozenset(("SYSTEM_OTP_READ", "SYSTEM_NM_DATA_READ"))


def build_native_target_plan(
    compilation,
    target,
    platform_facts,
    pattern_producer,
    scan_bindings=None,
):
    """Build one complete workbook-free native target through existing registries."""
    pattern_producer = _scan_bound_producer(pattern_producer, scan_bindings)
    compilation.require_success()
    cp_plan = compilation.for_cp(target.cp)
    schedule = cp_plan.canonical_schedule
    catalogs = compilation.plan.catalogs
    context = TypedKindContext(
        compilation, target, platform_facts, pattern_producer, scan_bindings
    )
    kinds = tuple(dict.fromkeys(
        definition.typed_kind
        for definition in cp_plan.definitions
        if definition.typed_kind not in _SYSTEM_KINDS
    ))
    assemblies = []
    for kind in kinds:
        plans = _plans_for_kind(catalogs, kind, target.platform, target.cp,
                                getattr(compilation, 'pattern_links', ()))
        if not plans:
            raise NativeTargetCompositionError(
                "NTC.PLAN.MISSING",
                f"{target.cp} canonical kind {kind!r} has no typed plan",
            )
        assemblies.append(
            NATIVE_TYPED_KIND_REGISTRY.compile(kind, plans, context)
        )

    system_reads = compile_system_read_assembly(
        compilation.system_read_specs(target.cp), target, schedule
    )
    contributions = tuple(
        contribution
        for assembly in assemblies
        for contribution in assembly.contributions
    ) + system_reads.contributions
    bodies = tuple(
        body for assembly in assemblies for body in assembly.bodies
    ) + system_reads.bodies
    _require_complete_schedule(cp_plan.definitions, schedule, contributions)
    return PlatformProgramBuilder(pattern_producer).build(ProgramAssemblyInput(
        target=target,
        platform_facts=platform_facts,
        canonical_schedule=schedule,
        contributions=contributions,
        bodies=bodies,
        runtime_declarations=cp_plan.runtime_state.declarations,
    ))


def build_native_definition_bodies(compilation, target, platform_facts, pattern_producer, definition, scan_bindings=None):
    """Return canonical bodies for one definition, using the full-target registry."""
    pattern_producer = _scan_bound_producer(pattern_producer, scan_bindings)
    bind_target = getattr(pattern_producer, "for_target", None)
    if callable(bind_target):
        pattern_producer = bind_target(platform_facts)
    compilation.require_success()
    schedule = compilation.for_cp(target.cp).canonical_schedule
    if not any(d.identity == definition.identity for d in schedule.definitions):
        raise ValueError('NTC.DEFINITION.UNKNOWN')
    keys = {f'{target.platform.casefold()}:{entry.identity}'.casefold()
            for entry in schedule.entries if entry.definition_id == definition.identity}
    context = TypedKindContext(compilation, target, platform_facts, pattern_producer, scan_bindings)
    if definition.typed_kind in _SYSTEM_KINDS:
        assembly = compile_system_read_assembly(compilation.system_read_specs(target.cp), target, schedule)
    else:
        plans = _plans_for_kind(compilation.plan.catalogs, definition.typed_kind, target.platform, target.cp,
                                getattr(compilation, 'pattern_links', ()))
        assembly = NATIVE_TYPED_KIND_REGISTRY.compile(definition.typed_kind, plans, context)
    bodies = tuple(body for body in assembly.bodies if body.ref.semantic_key.casefold() in keys)
    if not bodies or {body.ref.semantic_key.casefold() for body in bodies} != keys:
        raise ValueError('NTC.DEFINITION.BODY_MISSING')
    entries = tuple(entry for entry in schedule.entries if entry.definition_id == definition.identity)
    if target.platform.casefold() == 'chroma':
        from program_gen.platform_program.chroma import ChromaSkeletonSyntax
        syntax = ChromaSkeletonSyntax(platform_facts, entries, schedule)
    else:
        from program_gen.platform_program.s100 import S100SkeletonSyntax
        syntax = S100SkeletonSyntax(platform_facts, entries)
    return syntax.normalize_bodies(bodies)


def _plans_for_kind(catalogs, kind: str, platform: str, cp: str, pattern_links=()) -> tuple:
    if kind in _FIRMWARE_KINDS:
        mapping = catalogs.firmware_test_plans
    elif kind in _PLATFORM_CATALOG_BY_KIND:
        mapping = getattr(catalogs, _PLATFORM_CATALOG_BY_KIND[kind])[
            str(platform).casefold()
        ]
    else:
        try:
            mapping = getattr(catalogs, _CATALOG_BY_KIND[kind])
        except KeyError as error:
            raise NativeTargetCompositionError(
                "NTC.KIND.UNMAPPED", f"canonical kind {kind!r} has no catalog"
            ) from error
    selected = tuple(
        plan for _row, plan in sorted(mapping.items())
        if str(getattr(plan, "cp", "")).casefold() == str(cp).casefold()
        and (
            kind not in _FIRMWARE_KINDS
            or str(getattr(plan, "typed_kind", "")).upper() == kind
        )
    )
    return tuple(project_specialized_plan(plan, platform, pattern_links) for plan in selected)


def _scan_bound_producer(pattern_producer, scan_bindings):
    if scan_bindings is None:
        return pattern_producer
    from program_gen.core.scan_test import ScanArtifactProducer
    return (
        pattern_producer if isinstance(pattern_producer, ScanArtifactProducer)
        else ScanArtifactProducer(scan_bindings, pattern_producer)
    )


def _require_complete_schedule(source_definitions, schedule, contributions) -> None:
    definitions = [
        definition
        for contribution in contributions
        for definition in contribution.definitions
    ]
    entries = [
        entry
        for contribution in contributions
        for entry in contribution.schedule_entries
    ]
    _require_exactly_once(
        "DEFINITION",
        tuple((item.identity, item.typed_kind) for item in source_definitions),
        tuple((item.identity, item.typed_kind) for item in definitions),
    )
    _require_exactly_once(
        "SCHEDULE",
        tuple((item.identity, item.definition_id) for item in schedule.entries),
        tuple((item.identity, item.definition_identity) for item in entries),
    )


def _require_exactly_once(label: str, expected, actual) -> None:
    counts = {}
    values = {}
    for identity, value in actual:
        key = identity.casefold()
        counts[key] = counts.get(key, 0) + 1
        values[key] = value
    for identity, value in expected:
        key = identity.casefold()
        if counts.get(key, 0) != 1:
            raise NativeTargetCompositionError(
                f"NTC.{label}.PROVIDER_COUNT",
                f"{identity!r} has {counts.get(key, 0)} providers",
            )
        if str(values[key]).casefold() != str(value).casefold():
            raise NativeTargetCompositionError(
                f"NTC.{label}.CONTRACT_MISMATCH",
                f"{identity!r} provider contract differs from canonical schedule",
            )
    expected_keys = {identity.casefold() for identity, _value in expected}
    extra = next(
        (identity for identity, _value in actual if identity.casefold() not in expected_keys),
        None,
    )
    if extra is not None:
        raise NativeTargetCompositionError(
            f"NTC.{label}.UNSCHEDULED", f"{extra!r} is not canonical"
        )


__all__ = ["NativeTargetCompositionError", "build_native_target_plan", "build_native_definition_bodies"]
