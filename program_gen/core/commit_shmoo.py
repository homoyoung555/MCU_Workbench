"""Compile one-dimensional persistent COMMIT Shmoo points."""

from dataclasses import dataclass, replace
import re
from typing import Mapping, Tuple

from program_gen.core.persistence_recipe import (
    PersistenceCompileError,
    PersistencePlan,
    compile_persistence_plan,
)


_PERSISTENCE_MODULES = frozenset((
    "BUILDMAP", "READOTPMAP", "LOADMAP", "SETVPOSP", "NMLOOP",
    "CHECKOTP", "COMMIT", "PGMOTP", "BUILDUID",
))


class CommitShmooPlanError(ValueError):
    """A persistence Shmoo cannot be expressed by the first-version contract."""


@dataclass(frozen=True)
class CommitShmooFieldWrite:
    field: str
    page: str
    register: str
    lsb: int
    width: int
    value: int


@dataclass(frozen=True)
class CommitShmooPhysicalAction:
    action: str
    pages: Tuple[str, ...]


@dataclass(frozen=True)
class CommitShmooPoint:
    step: int
    field_writes: Tuple[CommitShmooFieldWrite, ...]
    affected_pages: Tuple[str, ...]
    physical_actions: Tuple[CommitShmooPhysicalAction, ...]


@dataclass(frozen=True)
class CommitShmooPlan:
    cp: str
    steps: Tuple[int, ...]
    points: Tuple[CommitShmooPoint, ...]
    flow_row_index: int = -1
    item: str = "Commit_Shmoo"
    vcc: str = ""
    kind: str = "COMMIT_SHMOO"
    uses_enter_judge_shmoo: bool = False

    @property
    def function_name(self) -> str:
        return self.item if self.item.casefold().endswith("shmoo") else self.item + "_Shmoo"


def compile_commit_shmoo_plan(
    persistence_plan: PersistencePlan,
    *,
    flow_type: str,
    step_range: str,
) -> CommitShmooPlan:
    if str(flow_type).strip().casefold() != "shmoo":
        raise CommitShmooPlanError("COMMIT Shmoo requires type=shmoo")
    if tuple(operation.module for operation in persistence_plan.operations) != (
        "COMMIT", "PGMOTP",
    ):
        raise CommitShmooPlanError(
            "COMMIT Shmoo Recipe must be COMMIT(FIELD=STEP,...)-PGMOTP"
        )
    commit, pgm = persistence_plan.operations
    if not commit.field_writes or any(
        write.value.kind != "STEP" for write in commit.field_writes
    ):
        raise CommitShmooPlanError(
            "COMMIT Shmoo requires STEP for every committed field"
        )
    steps = _parse_single_range(step_range)
    affected_pages = tuple(dict.fromkeys(write.page for write in commit.field_writes))
    pgm_pages = pgm.requested_pages or affected_pages
    points = []
    for step in steps:
        writes = tuple(CommitShmooFieldWrite(
            field=write.field,
            page=write.page,
            register=write.register,
            lsb=write.lsb,
            width=write.width,
            value=step,
        ) for write in commit.field_writes)
        overflow = tuple(write.field for write in writes if step >= (1 << write.width))
        if overflow:
            raise CommitShmooPlanError(
                f"step {step} exceeds field width for " + ", ".join(overflow)
            )
        points.append(CommitShmooPoint(
            step=step,
            field_writes=writes,
            affected_pages=affected_pages,
            physical_actions=(CommitShmooPhysicalAction("PGMOTP", pgm_pages),),
        ))
    return CommitShmooPlan(
        cp=persistence_plan.cp,
        steps=steps,
        points=tuple(points),
    )


def compile_commit_shmoo_plans(
    flow,
    recipe_rows,
    catalog=None,
) -> dict[int, CommitShmooPlan]:
    """Compile only persistent COMMIT Shmoo rows; ENTER/JUDGE stays separate."""
    if catalog is None:
        persistence_plans = recipe_rows
    else:
        persistence_plans = _compile_row_persistence_plans(recipe_rows, catalog)
    plans = {}
    for row, persistence_plan in persistence_plans.items():
        if row < 0 or row >= len(flow):
            raise CommitShmooPlanError(f"FLOW row index {row} is out of range")
        record = flow.iloc[row]
        if str(record.get("type", "")).strip().casefold() != "shmoo":
            continue
        modules = tuple(operation.module for operation in persistence_plan.operations)
        if not modules or modules[0] != "COMMIT":
            continue
        plans[row] = replace(
            compile_commit_shmoo_plan(
                persistence_plan,
                flow_type=record.get("type", ""),
                step_range=record.get("step", ""),
            ),
            flow_row_index=row,
            item=str(record.get("item", "")).strip(),
            vcc=str(record.get("Vcc", "")).strip(),
        )
    return plans


def _compile_row_persistence_plans(recipe_rows, catalog):
    """Validate full CP state, then extract each COMMIT Shmoo row.

    A Shmoo row deliberately contains only COMMIT/PGMOTP.  Its complete page
    image must therefore come from an earlier row in the same CP.  Compiling
    the whole CP first keeps that load-bearing precondition in PersistencePlan
    rather than reconstructing pages from ADDR_MAP defaults.
    """
    plans = {}
    cps = tuple(dict.fromkeys(row.flow.cp for row in recipe_rows.values()))
    for cp in cps:
        rows = tuple(
            _persistence_only_row(row)
            for row in recipe_rows.values()
            if row.flow.cp == cp and any(
                operation.name in _PERSISTENCE_MODULES
                for operation in row.operations
            )
        )
        default_pages = {
            row.flow.excel_row: _row_default_pages(row, catalog) for row in rows
        }
        try:
            full_plan = compile_persistence_plan(
                rows, catalog, node_default_pages=default_pages
            )
        except PersistenceCompileError as exc:
            if any(_is_commit_shmoo_row(row) for row in rows):
                raise CommitShmooPlanError(
                    "COMMIT Shmoo requires a same-CP complete Page Image and "
                    f"prepared patterns: {exc}"
                ) from exc
            continue
        for row in rows:
            if not _is_commit_shmoo_row(row):
                continue
            operations = tuple(
                operation for operation in full_plan.operations
                if operation.excel_row == row.flow.excel_row
            )
            plans[row.flow.excel_row - 2] = PersistencePlan(cp, operations)
    return plans


def _persistence_only_row(row):
    """Drop ordinary ENTER/TRIM/JUDGE operations before persistence compile."""
    return replace(
        row,
        operations=tuple(
            operation for operation in row.operations
            if operation.name in _PERSISTENCE_MODULES
        ),
    )


def _is_commit_shmoo_row(row) -> bool:
    return (
        str(row.flow.flow_type).strip().casefold() == "shmoo"
        and bool(row.operations)
        and row.operations[0].name == "COMMIT"
    )


def _row_default_pages(row, catalog) -> tuple[str, ...]:
    if not _is_commit_shmoo_row(row):
        return catalog.pages
    return tuple(dict.fromkeys(
        field.page
        for assignment in row.operations[0].assignments
        for field in catalog.resolve_fields(assignment.field)
    ))


def _parse_single_range(value: str) -> Tuple[int, ...]:
    match = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", str(value))
    if not match:
        raise CommitShmooPlanError(
            "first-version COMMIT Shmoo step must be one inclusive range such as 0-7"
        )
    start, stop = (int(match.group(1)), int(match.group(2)))
    direction = 1 if stop >= start else -1
    return tuple(range(start, stop + direction, direction))
