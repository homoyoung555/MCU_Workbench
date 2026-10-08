"""Platform-neutral UID BakeID two-stage update plan."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Protocol

from program_gen.core.otp_program import PagePatternPlan, PgmOtpPlan, compile_pgm_otp_plan


ALL_ACTIVE_SITES = "ALL_ACTIVE_SITES"


class PersistenceOperationLike(Protocol):
    module: str
    excel_row: int
    requested_pages: tuple[str, ...]
    effective_pages: tuple[str, ...]


class PersistencePlanLike(Protocol):
    cp: str
    operations: tuple[PersistenceOperationLike, ...]


class BakeIdPlanError(ValueError):
    """BakeID target, gate, or UID page contract is invalid."""


class BakeIdOperationKind(str, Enum):
    READOTPMAP = "READOTPMAP"
    LOADMAP = "LOADMAP"
    CHECKOTP = "CHECKOTP"
    COMMIT = "COMMIT"
    PGMOTP = "PGMOTP"


@dataclass(frozen=True, slots=True)
class BakeIdOperation:
    kind: BakeIdOperationKind
    site_scope: str
    requested_pages: tuple[str, ...] = ("uid",)
    effective_pages: tuple[str, ...] = ("uid",)


@dataclass(frozen=True, slots=True)
class BakeIdLoadMapOperation(BakeIdOperation):
    read_dont_care_fields: tuple[str, ...] = ()
    prepares_program_pattern: bool = True
    prepares_read_compare_pattern: bool = True


@dataclass(frozen=True, slots=True)
class BakeIdCheckOtpOperation(BakeIdOperation):
    runs_read_compare: bool = True
    erases_page: bool = False
    programs_page: bool = False


@dataclass(frozen=True, slots=True)
class BakeIdCommitOperation(BakeIdOperation):
    pass


@dataclass(frozen=True, slots=True)
class BakeIdPgmOtpOperation(BakeIdOperation):
    program_plan: PgmOtpPlan | None = None


@dataclass(frozen=True, slots=True)
class BakeIdPlan:
    cp: str
    target: str
    read_state: str
    read_otp_map: BakeIdOperation
    load_map: BakeIdLoadMapOperation
    check_otp: BakeIdCheckOtpOperation
    commit: BakeIdCommitOperation
    pgm_otp: BakeIdPgmOtpOperation

    @property
    def operations(self):
        return (
            self.read_otp_map,
            self.load_map,
            self.check_otp,
            self.commit,
            self.pgm_otp,
        )


def compile_bakeid_plan(
    *,
    cp: str,
    target: str,
    read_state: str,
    page_pattern: PagePatternPlan,
    current_cp_unproduced_fields: tuple[str, ...] = (),
    persistence_plan: PersistencePlanLike | None = None,
    excel_row: int | None = None,
) -> BakeIdPlan:
    """Compile the agreed all-site precheck and gated final UID write."""
    normalized_target = str(target).strip().upper()
    match = re.fullmatch(r"CP(?P<station>\d+)_BAKEID", normalized_target)
    if not match:
        raise BakeIdPlanError(
            f"BakeID target 必须使用 CP<n>_BAKEID，收到 {target!r}"
        )
    expected_read_state = f"Read_CP{match.group('station')}_BakeID"
    if str(read_state).strip().casefold() != expected_read_state.casefold():
        raise BakeIdPlanError(
            f"{normalized_target} 必须消费 {expected_read_state} 的待补写状态"
        )
    if not page_pattern.is_uid or page_pattern.page.casefold() != "uid":
        raise BakeIdPlanError("BakeID PGMOTP 必须使用明确标记的 UID Page")
    selected = ()
    if persistence_plan is not None:
        if excel_row is None:
            raise BakeIdPlanError("提供 PersistencePlan 时必须提供 excel_row")
        if str(persistence_plan.cp).strip().upper() != str(cp).strip().upper():
            raise BakeIdPlanError("BakeID 与 PersistencePlan 必须属于同一道 CP")
        selected = tuple(
            operation for operation in persistence_plan.operations
            if operation.excel_row == excel_row
        )
        expected = tuple(kind.value for kind in BakeIdOperationKind)
        actual = tuple(operation.module for operation in selected)
        if actual != expected:
            raise BakeIdPlanError(
                f"FLOW row {excel_row}: BakeID Recipe 必须是 " + "→".join(expected)
            )
        if any(operation.requested_pages != ("uid",) for operation in selected):
            raise BakeIdPlanError("BakeID 全部页面操作必须仅针对 UID Page")
    requested = selected[0].requested_pages if selected else ("uid",)
    effective = selected[0].effective_pages if selected else ("uid",)
    gate_scope = str(read_state).strip().upper() + "_PENDING_SITES"
    return BakeIdPlan(
        cp=str(cp).strip().upper(),
        target=normalized_target,
        read_state=str(read_state).strip(),
        read_otp_map=BakeIdOperation(
            BakeIdOperationKind.READOTPMAP, ALL_ACTIVE_SITES, requested, effective
        ),
        load_map=BakeIdLoadMapOperation(
            kind=BakeIdOperationKind.LOADMAP,
            site_scope=ALL_ACTIVE_SITES,
            read_dont_care_fields=tuple(current_cp_unproduced_fields),
        ),
        check_otp=BakeIdCheckOtpOperation(
            kind=BakeIdOperationKind.CHECKOTP,
            site_scope=ALL_ACTIVE_SITES,
        ),
        commit=BakeIdCommitOperation(
            kind=BakeIdOperationKind.COMMIT,
            site_scope=gate_scope,
        ),
        pgm_otp=BakeIdPgmOtpOperation(
            kind=BakeIdOperationKind.PGMOTP,
            site_scope=gate_scope,
            program_plan=compile_pgm_otp_plan((page_pattern,)),
        ),
    )
