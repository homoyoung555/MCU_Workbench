"""Compile CP definitions into one platform-neutral canonical schedule."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

import pandas as pd

from program_gen.core.recipe_trim import generated_flow_item_name
from program_gen.core.trim_spec import TrimSpec
from program_gen.program_plan import CpProgramPlan, ScheduleEntry, TestDefinition


class SchedulePlanError(ValueError):
    """A CP definition/schedule relationship cannot be represented canonically."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


class BinBindingKind(str, Enum):
    DIRECT = "DIRECT"
    DEFINITION_REFERENCE = "DEFINITION_REFERENCE"


@dataclass(frozen=True, slots=True)
class BinBinding:
    """The sole source of a scheduled item's hardware/software bin routing."""

    kind: BinBindingKind
    hardware_bin: str | None = None
    software_bin: str | None = None
    definition_id: str | None = None


@dataclass(frozen=True, slots=True)
class CanonicalScheduleDefinition:
    """A rendered test definition, including definitions without Flow entries."""

    identity: str
    cp: str
    item: str
    render_name: str
    source_rows: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class CanonicalScheduleEntry:
    """One ordered Flow call to a canonical definition or its trim variant."""

    identity: str
    definition_id: str
    flow_order: int
    variant_order: int
    variant: str | None
    render_name: str
    enabled: bool
    force_pass: bool
    bin_binding: BinBinding
    placement: str = "BOOKED"


@dataclass(frozen=True, slots=True)
class CanonicalSchedulePlan:
    """The immutable CP-level Definition and Schedule view for both platforms."""

    cp: str
    definitions: tuple[CanonicalScheduleDefinition, ...]
    entries: tuple[CanonicalScheduleEntry, ...]


def compile_canonical_schedule_plan(
    cp_plan: CpProgramPlan,
    flow_frame: pd.DataFrame,
    trim_specs: Mapping[int, TrimSpec],
) -> CanonicalSchedulePlan:
    """Compile existing CP semantics without mutating the FLOW dataframe."""
    return compile_schedule_groups(
        cp_plan.cp,
        cp_plan.definitions,
        cp_plan.schedule,
        flow_frame,
        trim_specs,
    )


def compile_schedule_groups(
    cp: str,
    source_definitions: tuple[TestDefinition, ...],
    source_schedule: tuple[ScheduleEntry, ...],
    flow_frame: pd.DataFrame,
    trim_specs: Mapping[int, TrimSpec],
) -> CanonicalSchedulePlan:
    """Compile the schedule while its eight-group CP plan is being assembled."""
    definitions: list[CanonicalScheduleDefinition] = []
    definitions_by_id: dict[str, CanonicalScheduleDefinition] = {}
    rows_by_definition: dict[str, int | None] = {}

    for definition in source_definitions:
        if definition.identity in definitions_by_id:
            raise SchedulePlanError(
                "SP.IDENTITY.DUPLICATE",
                f"duplicate definition identity {definition.identity!r}",
            )
        row_index = _definition_row_index(definition, flow_frame)
        render_name = _definition_render_name(definition, flow_frame, row_index)
        canonical = CanonicalScheduleDefinition(
            identity=definition.identity,
            cp=definition.cp,
            item=definition.item,
            render_name=render_name,
            source_rows=definition.source_rows,
        )
        definitions.append(canonical)
        definitions_by_id[canonical.identity] = canonical
        rows_by_definition[canonical.identity] = row_index

    entries: list[CanonicalScheduleEntry] = []
    seen_schedule_ids: set[str] = set()
    # CpProgramPlan already carries the authoritative CP-local order.  Its
    # ``order`` field is a product-wide FLOW coordinate, whereas the injected
    # NM_Data_Read entry deliberately uses the CP-local terminal position.
    for schedule in source_schedule:
        if schedule.identity in seen_schedule_ids:
            raise SchedulePlanError(
                "SP.IDENTITY.DUPLICATE",
                f"duplicate schedule identity {schedule.identity!r}",
            )
        seen_schedule_ids.add(schedule.identity)
        try:
            definition = definitions_by_id[schedule.definition_id]
        except KeyError as exc:
            raise SchedulePlanError(
                "SP.DEFINITION.MISSING",
                f"schedule {schedule.identity!r} references {schedule.definition_id!r}",
            ) from exc

        source_row = rows_by_definition[definition.identity]
        trim_spec = trim_specs.get(source_row) if source_row is not None else None
        bin_binding = _bin_binding(definition, definitions_by_id, schedule)
        if trim_spec is None:
            entries.append(_entry(
                schedule,
                definition,
                identity=schedule.identity,
                variant_order=0,
                variant=None,
                render_name=definition.render_name,
                enabled=schedule.enabled,
                bin_binding=bin_binding,
            ))
            continue

        for variant_order, variant in enumerate(trim_spec.search.variants):
            render_name = _trim_variant_render_name(definition.render_name, variant.kind)
            entries.append(_entry(
                schedule,
                definition,
                identity=f"{schedule.identity}:{variant.kind}",
                variant_order=variant_order,
                variant=variant.kind,
                render_name=render_name,
                enabled=schedule.enabled and variant.scheduled,
                bin_binding=bin_binding,
            ))

    _validate_render_names(definitions)
    return CanonicalSchedulePlan(
        cp=str(cp).strip().upper(),
        definitions=tuple(definitions),
        entries=tuple(entries),
    )


def _definition_row_index(
    definition: TestDefinition,
    flow_frame: pd.DataFrame,
) -> int | None:
    if not definition.source_rows:
        return None
    row_index = definition.source_rows[0] - 2
    if row_index < 0 or row_index >= len(flow_frame):
        raise SchedulePlanError(
            "SP.DEFINITION.MISSING",
            f"definition {definition.identity!r} points outside FLOW",
        )
    record = flow_frame.iloc[row_index]
    if (
        _text(record.get("CP NO")).casefold() != definition.cp.casefold()
        or _text(record.get("item")) != definition.item
        or _text(record.get("type")).casefold() != definition.flow_type.casefold()
    ):
        raise SchedulePlanError(
            "SP.DEFINITION.MISSING",
            f"definition {definition.identity!r} does not match its FLOW row",
        )
    return row_index


def _definition_render_name(
    definition: TestDefinition,
    flow_frame: pd.DataFrame,
    row_index: int | None,
) -> str:
    if definition.item == "OTP_READ":
        return "OTP_Read"
    if definition.item == "NM_Data_Read":
        return "NM_Data_Read"
    if row_index is None:
        raise SchedulePlanError(
            "SP.DEFINITION.MISSING",
            f"definition {definition.identity!r} has no FLOW source row",
        )
    return generated_flow_item_name(flow_frame, row_index).title()


def _trim_variant_render_name(render_name: str, kind: str) -> str:
    if kind == "FULL_SCAN":
        return render_name.split("Trim")[0] + "Dac_Loop"
    return render_name


def _validate_render_names(
    definitions: list[CanonicalScheduleDefinition],
) -> None:
    rendered_by_name: dict[str, str] = {}
    for definition in definitions:
        existing = rendered_by_name.get(definition.render_name)
        if existing is not None:
            raise SchedulePlanError(
                "SP.RENDER_NAME.DUPLICATE",
                f"definition {definition.identity!r} and {existing!r} render as {definition.render_name!r}",
            )
        rendered_by_name[definition.render_name] = definition.identity


def _bin_binding(
    definition: CanonicalScheduleDefinition,
    definitions_by_id: Mapping[str, CanonicalScheduleDefinition],
    schedule: ScheduleEntry,
) -> BinBinding:
    if definition.item not in ("OTP_READ", "NM_Data_Read"):
        return BinBinding(
            kind=BinBindingKind.DIRECT,
            hardware_bin=schedule.hardware_bin,
            software_bin=schedule.software_bin,
        )

    expected_item = f"Pgm_CP{definition.cp.removeprefix('CP')}ID_Read"
    matches = tuple(
        item.identity
        for item in definitions_by_id.values()
        if item.item == expected_item
    )
    if not matches:
        raise SchedulePlanError(
            "SP.BIN_REFERENCE.MISSING",
            f"{definition.item} requires definition {expected_item!r}",
        )
    if len(matches) != 1:
        raise SchedulePlanError(
            "SP.BIN_REFERENCE.AMBIGUOUS",
            f"{definition.item} matches {len(matches)} definitions for {expected_item!r}",
        )
    return BinBinding(
        kind=BinBindingKind.DEFINITION_REFERENCE,
        definition_id=matches[0],
    )


def _entry(
    schedule: ScheduleEntry,
    definition: CanonicalScheduleDefinition,
    *,
    identity: str,
    variant_order: int,
    variant: str | None,
    render_name: str,
    enabled: bool,
    bin_binding: BinBinding,
) -> CanonicalScheduleEntry:
    return CanonicalScheduleEntry(
        identity=identity,
        definition_id=definition.identity,
        flow_order=schedule.order,
        variant_order=variant_order,
        variant=variant,
        render_name=render_name,
        enabled=enabled,
        force_pass=schedule.force_pass,
        bin_binding=bin_binding,
        placement=schedule.placement,
    )


def _text(value: object) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip()
