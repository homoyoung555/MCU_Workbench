"""Compile ADC FLOW phases into one platform-neutral capture/judge plan."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import re
from types import MappingProxyType
from typing import Mapping

import pandas as pd

from flow_recipe import ExecutableFlowRow
from program_gen.core.firmware_judge import (
    DigitalCompareJudgePlan,
    FirmwareJudgeCompileError,
    compile_firmware_judge_plan,
)
from program_gen.core.result_binding import ResultIdentity
from program_gen.core.run_sequence import (
    LevelSequenceAction,
    RunSequenceCompileError,
    SendCodeAction,
    WaitAction,
    parse_run_sequence_step,
)
from program_gen.core.sram_capture import (
    SramCaptureCompileError,
    SramCapturePlan,
    compile_sram_capture_plan,
)
from program_gen.diagnostics import WorkbookProvenance
from program_gen.flow_kinds import FlowOperation


_ADC_RECIPE = ("SWD_CAPTURE", "ADC_JUDGE")
_ADC_KEIL_SRAM_RECIPE = ("RUN_SEQUENCE", "SRAM_CAPTURE", "ADC_JUDGE")
_ADC_KEIL_DIGITAL_RECIPE = ("RUN_SEQUENCE", "JUDGE")
_SLOT_COUNT = 22
_CODE_SCALE = 4096


def adc_pattern_names(adc_id: str) -> tuple[str, str]:
    """Shared external-resource names; platform adapters choose file formats."""
    return f"PT104_SWD_{adc_id}", f"PT104_{adc_id}_capture"


class AdcTestCompileError(ValueError):
    def __init__(self, code: str, row: int, message: str):
        self.code = code
        self.row = row
        super().__init__(f"{code}: FLOW row {row + 2}: {message}")


class AdcPatternRole(str, Enum):
    CONFIG_PATTERN = "CONFIG_PATTERN"
    CAPTURE_PATTERN = "CAPTURE_PATTERN"


class AdcSourceKind(str, Enum):
    EXTERNAL = "EXTERNAL"
    INTERNAL = "INTERNAL"


class AdcPhaseKind(str, Enum):
    SWD_CAPTURE = "SWD_CAPTURE"
    KEIL_SRAM_CAPTURE = "KEIL_SRAM_CAPTURE"
    KEIL_DIGITAL_COMPARE = "KEIL_DIGITAL_COMPARE"


@dataclass(frozen=True, slots=True)
class AdcCaptureContract:
    slot_count: int = _SLOT_COUNT
    word_width_bits: int = 16
    code_width_bits: int = 12
    upper_bits_must_be_zero: bool = True
    masks_upper_bits: bool = False

    def decode_word(self, raw_word: int) -> int:
        if isinstance(raw_word, bool) or not isinstance(raw_word, int):
            raise TypeError("ADC.CAPTURE.WORD_TYPE: raw capture word must be an integer")
        if not 0 <= raw_word < (1 << self.word_width_bits):
            raise ValueError(
                f"ADC.CAPTURE.WORD_RANGE: raw capture word must fit {self.word_width_bits} bits"
            )
        return raw_word


@dataclass(frozen=True, slots=True)
class AdcCaptureSlot:
    channel: int
    logical_pin: str
    source_kind: AdcSourceKind
    expected_voltage: float
    tolerance_codes: int
    expected_code: int
    low_limit: int
    high_limit: int

    @property
    def force_voltage(self) -> float | None:
        return self.expected_voltage if self.source_kind is AdcSourceKind.EXTERNAL else None

    def accepts(self, raw_value: int) -> bool:
        return self.low_limit <= raw_value <= self.high_limit


@dataclass(frozen=True, slots=True)
class AdcPhase:
    row: int
    adc_id: str
    sub: str
    mode: str
    provenance: WorkbookProvenance
    power_profile: str
    reference_voltage: float
    capture_pin: str
    slots: tuple[AdcCaptureSlot, ...]
    kind: AdcPhaseKind = AdcPhaseKind.SWD_CAPTURE
    effective_recipe: tuple[str, ...] = _ADC_RECIPE
    pattern_roles: tuple[AdcPatternRole, ...] = (
        AdcPatternRole.CONFIG_PATTERN,
        AdcPatternRole.CAPTURE_PATTERN,
    )
    # Platform projection records the explicit external names by role.  Empty
    # keeps the historic adc_pattern_names() default intact.
    pattern_names: tuple[tuple[str, str], ...] = ()
    capture: AdcCaptureContract = AdcCaptureContract()
    run_actions: tuple[LevelSequenceAction | SendCodeAction | WaitAction, ...] = ()
    sram_capture: SramCapturePlan | None = None
    digital_judge: DigitalCompareJudgePlan | None = None
    independent_power_session: bool = True


@dataclass(frozen=True, slots=True)
class AdcTestPlan:
    row: int
    row_indices: tuple[int, ...]
    cp: str
    item: str
    provenance: WorkbookProvenance
    hardware_bin: str
    software_bin: str
    phases: tuple[AdcPhase, ...]
    typed_kind: str = "ADC_TEST"

    @property
    def excel_rows(self) -> tuple[int, ...]:
        return tuple(row + 2 for row in self.row_indices)

    @property
    def effective_recipe(self) -> tuple[str, ...]:
        recipes = tuple(phase.effective_recipe for phase in self.phases)
        if recipes and all(recipe == recipes[0] for recipe in recipes[1:]):
            return recipes[0]
        return tuple(module for recipe in recipes for module in recipe)


def compile_adc_test_plans(
    operations: tuple[FlowOperation, ...],
    recipe_rows: Mapping[int, ExecutableFlowRow],
    flow: pd.DataFrame,
    adc: pd.DataFrame,
    iomux: pd.DataFrame,
    version: pd.DataFrame,
) -> Mapping[int, AdcTestPlan]:
    groups = _adc_groups(operations)
    if not groups:
        return MappingProxyType({})

    adc_rows = _adc_sheet_rows(adc, groups[0][0].row)
    pin_map = _iomux_pin_map(iomux, groups[0][0].row)
    version_facts = _version_facts(version)
    plans: dict[int, AdcTestPlan] = {}
    for group in groups:
        first = group[0]
        records = tuple(flow.iloc[operation.row] for operation in group)
        _require_shared_bins(first.row, records)
        if first.cp.upper() not in version_facts:
            raise AdcTestCompileError(
                "ADC.VERSION.CP_MISSING", first.row, f"VERSION has no row for {first.cp}"
            )
        facts = version_facts[first.cp.upper()]
        phases = tuple(
            _compile_phase(
                operation,
                recipe_rows,
                record,
                adc_rows,
                pin_map,
                facts,
            )
            for operation, record in zip(group, records)
        )
        adc_ids = tuple(phase.adc_id for phase in phases)
        if len(set(adc_ids)) != len(adc_ids):
            raise AdcTestCompileError(
                "ADC.PHASE.DUPLICATE", first.row, f"duplicate ADC phase in {adc_ids!r}"
            )
        plans[first.row] = AdcTestPlan(
            row=first.row,
            row_indices=tuple(operation.row for operation in group),
            cp=first.cp,
            item=first.item,
            provenance=first.provenance,
            hardware_bin=_text(records[0].get("Hbin")),
            software_bin=_text(records[0].get("Sbin")),
            phases=phases,
        )
    return MappingProxyType(plans)


def _compile_phase(
    operation: FlowOperation,
    recipe_rows: Mapping[int, ExecutableFlowRow],
    record: pd.Series,
    adc_rows: Mapping[str, Mapping[int, tuple[float, int]]],
    pin_map: Mapping[str, Mapping[int, str]],
    version_facts: Mapping[str, object],
) -> AdcPhase:
    executable = recipe_rows.get(operation.row)
    operations = tuple(getattr(executable, "operations", ()))
    recipe = tuple(call.name for call in operations)
    if operation.mode == "swd" and recipe != _ADC_RECIPE:
        raise AdcTestCompileError(
            "ADC.RECIPE.INVALID", operation.row,
            "SWD ADC phase requires Recipe=SWD_CAPTURE-ADC_JUDGE",
        )
    if operation.mode == "keil" and recipe not in (
        _ADC_KEIL_SRAM_RECIPE, _ADC_KEIL_DIGITAL_RECIPE
    ):
        raise AdcTestCompileError(
            "ADC.RECIPE.INVALID", operation.row,
            "KEIL ADC phase requires RUN_SEQUENCE-SRAM_CAPTURE(...)-ADC_JUDGE "
            "or RUN_SEQUENCE-JUDGE",
        )
    if operation.mode not in ("swd", "keil"):
        raise AdcTestCompileError(
            "ADC.MODE.UNSUPPORTED", operation.row,
            "native ADC supports only mode='swd' or mode='keil'",
        )
    adc_id = _text(record.get("FV/FI")).upper()
    if re.fullmatch(r"ADC\d+", adc_id) is None:
        raise AdcTestCompileError(
            "ADC.PHASE.ID_INVALID", operation.row, f"FV/FI must name ADCn, got {adc_id!r}"
        )
    sub = _text(record.get("sub"))
    if sub.upper() != adc_id:
        raise AdcTestCompileError(
            "ADC.PHASE.SUB_MISMATCH", operation.row, f"sub {sub!r} does not match {adc_id}"
        )
    channels = adc_rows.get(adc_id)
    pins = pin_map.get(adc_id)
    if channels is None:
        raise AdcTestCompileError(
            "ADC.SHEET.GROUP_MISSING", operation.row, f"ADC sheet has no {adc_id} group"
        )
    expected_channels = tuple(range(_SLOT_COUNT))
    if tuple(channels) != expected_channels:
        raise AdcTestCompileError(
            "ADC.SLOTS.NOT_CONTIGUOUS",
            operation.row,
            f"{adc_id} requires exactly CH0..CH{_SLOT_COUNT - 1}; got {tuple(channels)!r}",
        )
    if pins is None or tuple(pins) != expected_channels:
        actual = () if pins is None else tuple(pins)
        raise AdcTestCompileError(
            "ADC.IOMUX.NOT_CONTIGUOUS",
            operation.row,
            f"IOMUX requires exactly {adc_id} IN0..IN{_SLOT_COUNT - 1}; got {actual!r}",
        )
    power_profile = _required(record.get("Vcc"), operation.row, "Vcc").upper()
    voltage_key = power_profile.casefold().replace("_", " ")
    try:
        reference_voltage = float(version_facts[voltage_key])
    except (KeyError, TypeError, ValueError) as exc:
        raise AdcTestCompileError(
            "ADC.VERSION.VCC_MISSING",
            operation.row,
            f"VERSION {voltage_key!r} is missing or non-numeric",
        ) from exc
    capture_pin = _normalize_pin(_text(version_facts.get("swd pin")))
    if recipe in (_ADC_RECIPE, _ADC_KEIL_SRAM_RECIPE) and (
        not capture_pin or capture_pin == "/"
    ):
        raise AdcTestCompileError(
            "ADC.VERSION.SWD_PIN_MISSING", operation.row,
            "SWD/SRAM capture requires VERSION SWD PIN",
        )
    slots = tuple(
        _compile_slot(
            operation.row,
            channel,
            pins[channel],
            channels[channel],
            reference_voltage,
        )
        for channel in expected_channels
    )
    kind = AdcPhaseKind.SWD_CAPTURE
    pattern_roles: tuple[AdcPatternRole, ...] = (
        AdcPatternRole.CONFIG_PATTERN,
        AdcPatternRole.CAPTURE_PATTERN,
    )
    run_actions: tuple[LevelSequenceAction | SendCodeAction | WaitAction, ...] = ()
    sram_capture = None
    digital_judge = None
    if operation.mode == "keil":
        try:
            parsed_actions = parse_run_sequence_step(
                record.get("step"), _text(version_facts.get("get pin"))
            )
        except RunSequenceCompileError as exc:
            raise AdcTestCompileError(exc.code, operation.row, str(exc)) from exc
        if any(not isinstance(action, (LevelSequenceAction, SendCodeAction, WaitAction))
               for action in parsed_actions):
            raise AdcTestCompileError(
                "ADC.RUN_SEQUENCE.ACTION_UNSUPPORTED", operation.row,
                "ADC KEIL RUN_SEQUENCE currently supports level/send/wait actions",
            )
        run_actions = tuple(parsed_actions)
        pattern_roles = ()
        if recipe == _ADC_KEIL_SRAM_RECIPE:
            kind = AdcPhaseKind.KEIL_SRAM_CAPTURE
            try:
                sram_capture = compile_sram_capture_plan(
                    operations[1].sram_capture,
                    result_identity=ResultIdentity(
                        operation.cp, operation.item, adc_id, "SRAM_CAPTURE"
                    ),
                    provenance=operation.provenance,
                    capture_pin=capture_pin,
                )
            except SramCaptureCompileError as exc:
                raise AdcTestCompileError(
                    "ADC.SRAM_CAPTURE.INVALID", operation.row, str(exc)
                ) from exc
            if (
                sram_capture.layout.count != _SLOT_COUNT
                or sram_capture.layout.width != 16
            ):
                raise AdcTestCompileError(
                    "ADC.SRAM_CAPTURE.LAYOUT_MISMATCH", operation.row,
                    "ADC SRAM_CAPTURE requires count=22 and width=16",
                )
        else:
            kind = AdcPhaseKind.KEIL_DIGITAL_COMPARE
            try:
                digital_judge = compile_firmware_judge_plan(operation, record)
            except FirmwareJudgeCompileError as exc:
                raise AdcTestCompileError(exc.code, operation.row, str(exc)) from exc
            if not isinstance(digital_judge, DigitalCompareJudgePlan):
                raise AdcTestCompileError(
                    "ADC.JUDGE.DIGITAL_REQUIRED", operation.row,
                    "ADC RUN_SEQUENCE-JUDGE requires an H/L digital comparison",
                )
    return AdcPhase(
        row=operation.row,
        adc_id=adc_id,
        sub=sub,
        mode=operation.mode,
        provenance=operation.provenance,
        power_profile=power_profile,
        reference_voltage=reference_voltage,
        capture_pin=capture_pin,
        slots=slots,
        kind=kind,
        effective_recipe=recipe,
        pattern_roles=pattern_roles,
        run_actions=run_actions,
        sram_capture=sram_capture,
        digital_judge=digital_judge,
    )


def _compile_slot(
    row: int,
    channel: int,
    logical_pin: str,
    stimulus: tuple[float, int],
    reference_voltage: float,
) -> AdcCaptureSlot:
    expected_voltage, tolerance = stimulus
    if not 0 <= expected_voltage <= reference_voltage:
        raise AdcTestCompileError(
            "ADC.FORCE.OUT_OF_RANGE",
            row,
            f"CH{channel} voltage {expected_voltage} must be within 0..{reference_voltage}",
        )
    expected_code = int(round(expected_voltage / reference_voltage * _CODE_SCALE))
    low_limit, high_limit = expected_code - tolerance, expected_code + tolerance
    if not 0 <= low_limit <= high_limit < _CODE_SCALE:
        raise AdcTestCompileError(
            "ADC.LIMIT.OUT_OF_RANGE",
            row,
            f"CH{channel} limits {low_limit}..{high_limit} must fit 12-bit code range",
        )
    source_kind = (
        AdcSourceKind.INTERNAL
        if logical_pin.upper().startswith("INT_")
        else AdcSourceKind.EXTERNAL
    )
    return AdcCaptureSlot(
        channel=channel,
        logical_pin=logical_pin,
        source_kind=source_kind,
        expected_voltage=expected_voltage,
        tolerance_codes=tolerance,
        expected_code=expected_code,
        low_limit=low_limit,
        high_limit=high_limit,
    )


def _adc_groups(operations: tuple[FlowOperation, ...]) -> tuple[tuple[FlowOperation, ...], ...]:
    groups: list[tuple[FlowOperation, ...]] = []
    active: list[FlowOperation] = []
    active_key: tuple[str, str, str] | None = None
    closed: set[tuple[str, str, str]] = set()
    for operation in operations:
        if operation.typed_kind != "ADC_TEST":
            if active:
                groups.append(tuple(active))
                closed.add(active_key)  # type: ignore[arg-type]
                active, active_key = [], None
            continue
        key = (operation.cp.casefold(), operation.item.casefold(), operation.source_type.casefold())
        if active_key == key:
            active.append(operation)
            continue
        if active:
            groups.append(tuple(active))
            closed.add(active_key)  # type: ignore[arg-type]
        if key in closed:
            raise AdcTestCompileError(
                "ADC.GROUP.NONCONTIGUOUS",
                operation.row,
                "ADC phases for one CP/item/type must be contiguous",
            )
        active, active_key = [operation], key
    if active:
        groups.append(tuple(active))
    return tuple(groups)


def _adc_sheet_rows(adc: pd.DataFrame, flow_row: int) -> Mapping[str, Mapping[int, tuple[float, int]]]:
    adc_column = _column(adc, "ADC")
    channel_column = _first_column(adc, ("Chanel", "Channel", "CH"))
    force_column = _column(adc, "force")
    limit_column = _column(adc, "limit")
    groups: dict[str, dict[int, tuple[float, int]]] = {}
    current = ""
    for _index, record in adc.iterrows():
        label = _text(record.get(adc_column))
        if label:
            current = label.upper()
        channel_text = _text(record.get(channel_column))
        if not current or not channel_text:
            continue
        try:
            channel_number = float(channel_text)
            channel = int(channel_number)
            force = float(record.get(force_column))
            tolerance_number = float(record.get(limit_column))
            tolerance = int(tolerance_number)
        except (TypeError, ValueError) as exc:
            raise AdcTestCompileError(
                "ADC.SHEET.VALUE_INVALID", flow_row, f"{current} channel row is non-numeric"
            ) from exc
        if (
            not math.isfinite(channel_number)
            or channel_number != channel
            or not math.isfinite(force)
            or not math.isfinite(tolerance_number)
            or tolerance_number != tolerance
            or tolerance < 0
        ):
            raise AdcTestCompileError(
                "ADC.SHEET.VALUE_INVALID", flow_row, f"{current} channel row is invalid"
            )
        group = groups.setdefault(current, {})
        if channel in group:
            raise AdcTestCompileError(
                "ADC.SHEET.CHANNEL_DUPLICATE", flow_row, f"{current} duplicates CH{channel}"
            )
        group[channel] = (force, tolerance)
    return MappingProxyType({
        adc_id: MappingProxyType(dict(sorted(channels.items())))
        for adc_id, channels in groups.items()
    })


def _iomux_pin_map(iomux: pd.DataFrame, flow_row: int) -> Mapping[str, Mapping[int, str]]:
    pin_column = _column(iomux, "pin")
    analog_column = _column(iomux, "analog")
    mapping: dict[str, dict[int, str]] = {}
    for _index, record in iomux.iterrows():
        pin = _text(record.get(pin_column))
        analog = _text(record.get(analog_column))
        if not pin or not analog:
            continue
        for token in analog.split("/"):
            match = re.fullmatch(r"ADC(12|\d+)_IN(\d+)", token.strip(), re.IGNORECASE)
            if match is None:
                continue
            adc_ids = ("ADC1", "ADC2") if match.group(1) == "12" else (f"ADC{int(match.group(1))}",)
            channel = int(match.group(2))
            for adc_id in adc_ids:
                group = mapping.setdefault(adc_id, {})
                if channel in group:
                    raise AdcTestCompileError(
                        "ADC.IOMUX.CHANNEL_DUPLICATE",
                        flow_row,
                        f"IOMUX maps {adc_id} IN{channel} more than once",
                    )
                group[channel] = _normalize_pin(pin)
    return MappingProxyType({
        adc_id: MappingProxyType(dict(sorted(channels.items())))
        for adc_id, channels in mapping.items()
    })


def _version_facts(version: pd.DataFrame) -> Mapping[str, Mapping[str, object]]:
    cp_column = _column(version, "CP num")
    return MappingProxyType({
        _text(record.get(cp_column)).upper(): MappingProxyType({
            str(column).strip().casefold(): value for column, value in record.items()
        })
        for _index, record in version.iterrows()
        if _text(record.get(cp_column))
    })


def _require_shared_bins(row: int, records: tuple[pd.Series, ...]) -> None:
    for column in ("Hbin", "Sbin"):
        values = tuple(_text(record.get(column)) for record in records)
        if any(value != values[0] for value in values[1:]):
            raise AdcTestCompileError(
                "ADC.GROUP.BIN_MISMATCH", row, f"all ADC phases must share {column}"
            )


def _normalize_pin(value: object) -> str:
    pin = _text(value).split("-", 1)[0]
    match = re.fullmatch(r"(P[A-FY])0*(\d+)", pin, re.IGNORECASE)
    return f"{match.group(1).upper()}{int(match.group(2))}" if match else pin


def _column(frame: pd.DataFrame, expected: str) -> str:
    return _first_column(frame, (expected,))


def _first_column(frame: pd.DataFrame, expected: tuple[str, ...]) -> str:
    columns = {str(column).strip().casefold(): str(column) for column in frame.columns}
    for name in expected:
        if name.casefold() in columns:
            return columns[name.casefold()]
    raise AdcTestCompileError(
        "ADC.SHEET.COLUMN_MISSING", 0, f"missing column; expected one of {expected!r}"
    )


def _required(value: object, row: int, name: str) -> str:
    text = _text(value)
    if not text or text == "/":
        raise AdcTestCompileError("ADC.FLOW.FACT_MISSING", row, f"{name} is required")
    return text


def _text(value: object) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip()


__all__ = [
    "AdcCaptureContract",
    "AdcCaptureSlot",
    "AdcPatternRole",
    "AdcPhase",
    "AdcPhaseKind",
    "AdcSourceKind",
    "AdcTestCompileError",
    "AdcTestPlan",
    "compile_adc_test_plans",
]
