"""Compile the exact Pdr_Verify protocol without platform rendering.

The compiler consumes the normalized FLOW projection already owned by the
ProductCompiler and its typed ``FlowOperation``.  It performs no workbook I/O
and deliberately does not share a protocol with BOR.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd

from program_gen.core.input_normalization import token_key
from program_gen.diagnostics import WorkbookProvenance
from program_gen.flow_kinds import FlowOperation


class PdrVerifyPlanError(ValueError):
    """A FLOW operation cannot form the registered Pdr_Verify protocol."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


class PdrVerifyPlatform(str, Enum):
    CHROMA = "chroma"
    S100 = "s100"


class PdrExpectedStatus(str, Enum):
    NORMAL = "NORMAL"
    RESET = "RESET"


class PdrMismatchRule(str, Enum):
    TESTER_FAIL = "TESTER_FAIL"
    TESTER_PASS = "TESTER_PASS"
    DRIVER_RESULT_GT_HALF = "DRIVER_RESULT_GT_HALF"
    DRIVER_RESULT_LT_HALF = "DRIVER_RESULT_LT_HALF"


class PdrVoltageApplication(str, Enum):
    CHROMA_REGISTERED_LEVEL_AND_MLDPS = "CHROMA_REGISTERED_LEVEL_AND_MLDPS"
    S100_ALL_RAILS_AND_IO_THRESHOLDS = "S100_ALL_RAILS_AND_IO_THRESHOLDS"


@dataclass(frozen=True, slots=True)
class PdrPatternResource:
    role: str
    name: str
    logical_identity: str


@dataclass(frozen=True, slots=True)
class PdrStatusCheck:
    voltage_role: str
    expected_status: PdrExpectedStatus
    mismatch_rule: PdrMismatchRule
    settle_ms: float
    status_pattern_identity: str
    driver_result_threshold: float | None
    voltage_profile_identity: str
    level_profile_identity: str | None
    io_pin_group_identity: str | None


@dataclass(frozen=True, slots=True)
class PdrPowerLimits:
    rail_scope: str
    voltage_range_v: float | None
    current_range_ma: float
    current_limit_ma: float | None
    compliance_profile: str | None
    force_wait_ms: float
    level_settle_ms: float | None
    drive_high_ratio: float | None = None
    drive_low_v: float | None = None
    compare_high_ratio: float | None = None
    compare_low_ratio: float | None = None


@dataclass(frozen=True, slots=True)
class PdrVerifyPlan:
    row: int
    excel_row: int
    cp: str
    item: str
    provenance: WorkbookProvenance
    typed_kind: str
    initial_power_profile: str
    relay: str
    test_number: int
    pdr_min_voltage: str | None
    pdr_target_voltage: str | None
    pdr_max_voltage: str | None
    scalar_limits: tuple[float, float] | None
    pe_action: str | None
    platform: PdrVerifyPlatform
    voltage_application: PdrVoltageApplication
    pattern_resources: tuple[PdrPatternResource, ...]
    status_checks: tuple[PdrStatusCheck, ...]
    power_limits: PdrPowerLimits


def compile_pdr_verify_plan(
    flow: pd.DataFrame,
    operation: FlowOperation,
    platform: str | PdrVerifyPlatform,
    *,
    version_frame: pd.DataFrame | None = None,
) -> PdrVerifyPlan:
    """Compile one exact Pdr_Verify row into an immutable protocol plan."""
    profile = _platform(platform)
    _validate_operation(flow, operation)
    record = flow.iloc[operation.row]
    _validate_record_inputs(record)
    common_patterns = (
        _pattern("ENTER_FBIST", "enter_fbist_mode"),
        _pattern("ENTER_PDR_VERIFY", "enter_pdr_verify"),
        _pattern("STATUS_READ", "read_status_mode"),
    )
    if profile is PdrVerifyPlatform.CHROMA:
        patterns = common_patterns + (_pattern("EXIT_FBIST", "exit_fbist_mode"),)
        voltage_application = (
            PdrVoltageApplication.CHROMA_REGISTERED_LEVEL_AND_MLDPS
        )
        mismatch_rules = (
            PdrMismatchRule.TESTER_FAIL,
            PdrMismatchRule.TESTER_PASS,
        )
        settle_ms = (10.0, 10.0)
        driver_result_threshold = None
        level_profile_identities = (
            "level_profile:PDR_MAX_LVL",
            "level_profile:PDR_MIN_LVL",
        )
        io_pin_group_identity = None
        power_limits = PdrPowerLimits(
            rail_scope="ALL_TARGET_POWER_RAILS",
            voltage_range_v=6.0,
            current_range_ma=500.0,
            current_limit_ma=200.0,
            compliance_profile=None,
            force_wait_ms=2.0,
            level_settle_ms=3.0,
        )
    else:
        patterns = common_patterns
        voltage_application = (
            PdrVoltageApplication.S100_ALL_RAILS_AND_IO_THRESHOLDS
        )
        mismatch_rules = (
            PdrMismatchRule.DRIVER_RESULT_GT_HALF,
            PdrMismatchRule.DRIVER_RESULT_LT_HALF,
        )
        settle_ms = (10.0, 0.0)
        driver_result_threshold = 0.5
        level_profile_identities = (None, None)
        io_pin_group_identity = "pin_group:IO_ALLPINS"
        power_limits = PdrPowerLimits(
            rail_scope="ALL_TARGET_POWER_RAILS",
            voltage_range_v=None,
            current_range_ma=500.0,
            current_limit_ma=None,
            compliance_profile="I7",
            force_wait_ms=0.5,
            level_settle_ms=None,
            drive_high_ratio=1.0,
            drive_low_v=0.0,
            compare_high_ratio=0.55,
            compare_low_ratio=0.45,
        )
    pdr_min, pdr_target, pdr_max = _pdr_voltages(
        version_frame, operation.cp
    )
    return PdrVerifyPlan(
        row=operation.row,
        excel_row=operation.row + 2,
        cp=operation.cp,
        item=operation.item,
        provenance=operation.provenance,
        typed_kind="PDR_VERIFY",
        initial_power_profile=_text(record.get("Vcc")).upper(),
        relay=_text(record.get("relay")),
        test_number=(operation.row + 1) * 100,
        pdr_min_voltage=pdr_min,
        pdr_target_voltage=pdr_target,
        pdr_max_voltage=pdr_max,
        scalar_limits=None,
        pe_action=None,
        platform=profile,
        voltage_application=voltage_application,
        pattern_resources=patterns,
        status_checks=(
            PdrStatusCheck(
                "PDR_MAX",
                PdrExpectedStatus.NORMAL,
                mismatch_rules[0],
                settle_ms[0],
                "pattern:read_status_mode",
                driver_result_threshold,
                "voltage_profile:VCC_PDR_MAX",
                level_profile_identities[0],
                io_pin_group_identity,
            ),
            PdrStatusCheck(
                "PDR_MIN",
                PdrExpectedStatus.RESET,
                mismatch_rules[1],
                settle_ms[1],
                "pattern:read_status_mode",
                driver_result_threshold,
                "voltage_profile:VCC_PDR_MIN",
                level_profile_identities[1],
                io_pin_group_identity,
            ),
        ),
        power_limits=power_limits,
    )


def _pdr_voltages(
    version: pd.DataFrame | None, cp: str
) -> tuple[str | None, str | None, str | None]:
    if version is None:
        return None, None, None
    if "CP num" not in version.columns:
        raise PdrVerifyPlanError("PV.VERSION.CP", "VERSION lacks CP num")
    rows = version[
        version["CP num"].astype(str).str.strip().str.casefold() == cp.casefold()
    ]
    if len(rows) != 1:
        raise PdrVerifyPlanError(
            "PV.VERSION.CP", f"expected one VERSION row for {cp}, found {len(rows)}"
        )
    values = []
    for column, role, required in (
        ("pdr min", "MIN", True),
        ("pdr target", "TARGET", False),
        ("pdr max", "MAX", True),
    ):
        text = _text(rows.iloc[0].get(column))
        if not required and text in ("", "/"):
            values.append(None)
            continue
        try:
            value = float(text)
        except ValueError as exc:
            raise PdrVerifyPlanError(
                f"PV.VOLTAGE.{role}", f"invalid PDR {role.lower()} voltage"
            ) from exc
        if value <= 0:
            raise PdrVerifyPlanError(
                f"PV.VOLTAGE.{role}", f"PDR {role.lower()} voltage must be positive"
            )
        values.append(value)
    if values[1] is not None and not values[0] < values[1] < values[2]:
        raise PdrVerifyPlanError(
            "PV.VOLTAGE.ORDER", "PDR voltages must satisfy min < target < max"
        )
    if values[1] is None and not values[0] < values[2]:
        raise PdrVerifyPlanError(
            "PV.VOLTAGE.ORDER", "PDR voltages must satisfy min < max"
        )
    return tuple(None if value is None else f"{value:g}" for value in values)


def _pattern(role: str, name: str) -> PdrPatternResource:
    return PdrPatternResource(role, name, f"pattern:{name}")


def _validate_operation(flow: pd.DataFrame, operation: FlowOperation) -> None:
    if token_key(operation.item) != "pdr_verify":
        raise PdrVerifyPlanError(
            "PV.PROTOCOL.UNSUPPORTED",
            f"item {operation.item!r} is not the registered Pdr_Verify protocol",
        )
    if (
        operation.source_type.casefold() != "verify"
        or operation.mode.casefold() != "fbist"
        or operation.typed_kind != "PDR_VERIFY"
    ):
        raise PdrVerifyPlanError(
            "PV.OPERATION.MISMATCH",
            "Pdr_Verify requires verify/fbist and a compatible typed kind",
        )
    if (
        not isinstance(flow, pd.DataFrame)
        or not isinstance(operation.row, int)
        or operation.row < 0
        or operation.row >= len(flow)
    ):
        raise PdrVerifyPlanError(
            "PV.ROW.INVALID", f"FLOW row {operation.row!r} is out of bounds"
        )
    expected_coordinate = f"A{operation.row + 2}"
    if (
        operation.provenance.sheet != "FLOW"
        or operation.provenance.coordinate.upper() != expected_coordinate
    ):
        raise PdrVerifyPlanError(
            "PV.OPERATION.MISMATCH",
            f"provenance must identify FLOW!{expected_coordinate}",
        )

    record = flow.iloc[operation.row]
    row_identity = (
        _text(record.get("CP NO")),
        token_key(record.get("item")),
        _text(record.get("type")).casefold(),
        _text(record.get("mode")).casefold(),
    )
    operation_identity = (
        operation.cp,
        "pdr_verify",
        operation.source_type.casefold(),
        operation.mode.casefold(),
    )
    if row_identity != operation_identity:
        raise PdrVerifyPlanError(
            "PV.ROW.MISMATCH",
            "normalized FLOW row does not match the typed FlowOperation",
        )


def _validate_record_inputs(record: pd.Series) -> None:
    pe = _text(record.get("PE"))
    if pe.casefold() not in {"", "/", "no"}:
        raise PdrVerifyPlanError(
            "PV.PE.UNSUPPORTED",
            f"Pdr_Verify has no program/erase action, got PE={pe!r}",
        )

    scalar_columns = ("Low", "target", "High", "FV/FI", "meas pin", "UNIT")
    populated = tuple(
        column
        for column in scalar_columns
        if _text(record.get(column)) not in {"", "/"}
    )
    if populated:
        raise PdrVerifyPlanError(
            "PV.JUDGE.SCALAR_INPUT_UNSUPPORTED",
            "Pdr_Verify uses status judgment, not scalar fields: "
            + ", ".join(populated),
        )

    power_profile = _text(record.get("Vcc"))
    if power_profile in {"", "/"}:
        raise PdrVerifyPlanError(
            "PV.POWER.PROFILE_REQUIRED",
            "Pdr_Verify requires its initial Vcc power profile",
        )


def _platform(value: str | PdrVerifyPlatform) -> PdrVerifyPlatform:
    if isinstance(value, PdrVerifyPlatform):
        return value
    try:
        return PdrVerifyPlatform(str(value).strip().casefold())
    except ValueError as exc:
        raise PdrVerifyPlanError(
            "PV.PLATFORM.UNKNOWN", f"unsupported Pdr_Verify platform {value!r}"
        ) from exc


def _text(value: object) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip()
