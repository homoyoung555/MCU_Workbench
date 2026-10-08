"""Shared upstream binding for VT and Margin read-only Flash sessions."""

from dataclasses import dataclass
import re

from program_gen.core.flash_compare_plan import BulkCoverage, DataKind, Operation, Scope
from program_gen.core.flash_label_plan import FlashLabelCompileError
from program_gen.core.flash_window import _run
from program_gen.core.id_module import IdModulePlan
from program_gen.core.run_pattern import RunPatternPlan


@dataclass(frozen=True, slots=True)
class FlashReadSessionPlan:
    power_profile: str
    enter: RunPatternPlan
    enter_vt: RunPatternPlan
    read: RunPatternPlan
    gate: IdModulePlan | None


def bind_flash_read_session(operation, mode, background, bake, flow, requests,
                            fbist_plan, id_plans, *, kind, error_type,
                            read_target=None, flash_label_plan=None):
    """Bind semantic resources and the existing Gate; never invent a producer."""
    location = f"FLOW!A{operation.row + 2}"
    if read_target in (None, "NM"):
        data = {"FF": DataKind.ONE, "00": DataKind.ZERO,
                "CKB": DataKind.PCKB, "CKBB": DataKind.NCKB}[background.upper()]
        reads = tuple(request for request in requests
                      if request.scope is Scope.BULK and request.operation is Operation.READ
                      and request.data is not None and request.data.kind is data
                      and (request.bulk_coverage or BulkCoverage.NM_ONLY) is BulkCoverage.NM_ONLY
                      and request.bulk_strategy is None)
        if len(reads) != 1:
            raise error_type(f"{kind}.PATTERN.BINDING_INVALID",
                             f"{location}: expected one NM Read {data.value}, got {len(reads)}")
        read_name = reads[0].output_identity
    else:
        match = re.fullmatch(r"OTP-([A-Za-z][A-Za-z0-9_]*)", read_target, re.I)
        if match is None:
            raise error_type(f"{kind}.RECIPE.INVALID", f"{location}: {read_target!r}")
        pages = tuple(page for page in (flash_label_plan.pages if flash_label_plan else ())
                      if page.name.casefold() == match[1].casefold())
        if len(pages) == 1 and pages[0].name.casefold() == "uid":
            try:
                names = flash_label_plan.contract.uid_variant(operation.cp)
            except FlashLabelCompileError as exc:
                raise error_type(f"{kind}.PATTERN.BINDING_INVALID", f"{location}: {exc}") from exc
            pages = tuple(variant for variant in flash_label_plan.uid_variants
                          if variant.name == names.name)
        if len(pages) != 1 or not pages[0].names.read_pattern:
            raise error_type(f"{kind}.PATTERN.BINDING_INVALID",
                             f"{location}: expected one OTP Page Read for {read_target}")
        # Reuse the compare data loaded earlier; this session never reloads the map.
        read_name = pages[0].names.read_pattern
    enter_names = {row.output_pattern for row in fbist_plan.rows
                   if row.item.casefold() == mode.casefold() and row.role == "verify mode"
                   and not row.excluded and row.output_pattern}
    if len(enter_names) != 1:
        raise error_type(f"{kind}.ENTER.BINDING_INVALID", f"{location}: {mode}")
    enter_name = next(iter(enter_names))
    if sum(pattern.pattern_name == enter_name for pattern in fbist_plan.patterns) != 1:
        raise error_type(f"{kind}.ENTER.BINDING_INVALID", f"{location}: {enter_name}")
    profile = str(flow.iloc[operation.row].get("Vcc", "")).strip().upper()
    if profile not in ("VCC_MIN", "VCC_TYP", "VCC_MAX"):
        raise error_type(f"{kind}.VCC.INVALID", f"{location}: {profile!r}")
    gate = None
    if bake:
        producers = tuple(plan.steps[0].module_plan for plan in id_plans.values()
                          if plan.cp == operation.cp and plan.row < operation.row
                          and plan.steps[0].module == "READID"
                          and plan.steps[0].module_plan.id_item.target.kind == "BAKEID")
        if len(producers) != 1:
            raise error_type(f"{kind}.GATE.BINDING_INVALID",
                             f"{location}: expected one preceding Read Bake ID, got {len(producers)}")
        gate = producers[0]
    return FlashReadSessionPlan(profile, _run("enter_fbist_mode"), _run(enter_name),
                                _run(read_name), gate)


def validate_flash_read_gate_schedule(plans, id_plans, cp_plans, *, kind, error_type):
    """A declared Gate is insufficient if its READID never runs first."""
    for plan in plans.values():
        if plan.test.gate is None:
            continue
        schedule = cp_plans[plan.cp].canonical_schedule
        definitions = {definition.identity: definition for definition in schedule.definitions}
        positions = {row: (index, entry.enabled) for index, entry in enumerate(schedule.entries)
                     for row in definitions[entry.definition_id].source_rows}
        consumer_order, enabled = positions[plan.excel_row]
        if not enabled:
            continue
        producer = next(p for p in id_plans.values() if p.cp == plan.cp
                        and p.steps[0].module_plan is plan.test.gate)
        producer_order, producer_enabled = positions[producer.excel_row]
        if not producer_enabled or producer_order >= consumer_order:
            raise error_type(f"{kind}.GATE.PRODUCER_DISABLED",
                             f"FLOW!A{plan.excel_row}: READID at row {producer.excel_row} must run first")
