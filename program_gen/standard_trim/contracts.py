"""Internal validated view of one generic STANDARD_TRIM typed plan.

``compile_standard_trim_contracts`` consumes ONLY the already-compiled
``TrimSpec`` (canonical Recipe) and produces the six confirmed domain
contracts: PowerContract, FbistContract, MeasurementContract, TimingContract,
RelayContract, HelperContract. It is a pure projection and adds no defaults:

- the FBIST protocol enter/exit patterns come from ``TrimSpec.protocol``;
- the measurement timeout is consumed from ``TrimSpec.measurement``;
- no-relay is modelled as ``None`` (NoRelay) — ``"/"`` is rejected;
- helper identities consume typed contract facts (``TrimOperation.helper_name``
  for dependencies and ``DacBinding.helper_name`` for the trim-data helper).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from program_gen.core.encoding import calc_limit
from program_gen.core.trim_spec import TrimOperation, TrimSpec


class StandardTrimContractError(ValueError):
    """A STANDARD_TRIM domain contract cannot be compiled or is invalid."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class PowerContract:
    """Power rail compiled from the typed Recipe (``TrimSpec.vcc``)."""

    rail: str

    @classmethod
    def compile(cls, spec: TrimSpec) -> "PowerContract":
        rail = str(spec.vcc).strip()
        if not rail:
            raise StandardTrimContractError(
                "ST.POWER.RAIL_MISSING",
                f"STANDARD_TRIM {spec.item!r} has no power rail (TrimSpec.vcc)",
            )
        return cls(rail=rail)


@dataclass(frozen=True, slots=True)
class FbistContract:
    """FBIST protocol enter/exit pattern identities from the typed Recipe."""

    enter_pattern: str
    exit_pattern: str

    @classmethod
    def compile(cls, spec: TrimSpec) -> "FbistContract":
        enter = str(spec.protocol.enter_pattern).strip()
        exit_pattern = str(spec.protocol.exit_pattern).strip()
        if not enter or not exit_pattern:
            raise StandardTrimContractError(
                "ST.FBIST.PATTERN_MISSING",
                f"STANDARD_TRIM {spec.item!r} lacks FBIST protocol patterns "
                "(TrimSpec.protocol)",
            )
        return cls(enter_pattern=enter, exit_pattern=exit_pattern)


@dataclass(frozen=True, slots=True)
class MeasurementContract:
    """Measurement facts compiled from ``TrimSpec.measurement``.

    The native vertical slice supports the three ordinary-Trim measurement
    families compiled from FLOW. Timeout values must already exist in the
    typed plan.
    """

    family: str
    unit: str
    pin: str
    force: str
    target: float
    low_limit: str
    high_limit: str
    limit_low: float
    limit_high: float
    search_limit_low: float
    search_limit_high: float
    freq_gate: str
    sample_timeout_value: int
    sample_timeout_unit: str

    @classmethod
    def compile(cls, spec: TrimSpec) -> "MeasurementContract":
        measurement = spec.measurement
        family = str(measurement.family).strip().upper()
        if family not in ("FREQUENCY", "VOLTAGE", "CURRENT"):
            raise StandardTrimContractError(
                "ST.MEASUREMENT.FAMILY",
                f"STANDARD_TRIM native slice does not support "
                f"measurement family {measurement.family!r}",
            )
        unit = str(measurement.unit).strip()
        pin = str(measurement.pin).strip()
        if not unit or not pin:
            raise StandardTrimContractError(
                "ST.MEASUREMENT.UNIT_PIN",
                f"STANDARD_TRIM {spec.item!r} measurement unit/pin is empty",
            )
        try:
            target = float(measurement.target)
        except (TypeError, ValueError) as exc:
            raise StandardTrimContractError(
                "ST.MEASUREMENT.TARGET",
                f"STANDARD_TRIM {spec.item!r} measurement target is not numeric",
            ) from exc
        if (
            measurement.sample_timeout_value is None
            or not str(measurement.sample_timeout_unit).strip()
        ):
            raise StandardTrimContractError(
                "ST.MEASUREMENT.TIMEOUT_MISSING",
                f"STANDARD_TRIM {spec.item!r} lacks typed sample timeout",
            )
        if (
            measurement.search_low_limit is None
            or measurement.search_high_limit is None
        ):
            raise StandardTrimContractError(
                "ST.MEASUREMENT.SEARCH_LIMIT_MISSING",
                f"STANDARD_TRIM {spec.item!r} lacks typed search observation limits",
            )
        return cls(
            family=family,
            unit=unit,
            pin=pin,
            force=str(measurement.force).strip(),
            target=target,
            low_limit=str(measurement.low_limit).strip(),
            high_limit=str(measurement.high_limit).strip(),
            limit_low=calc_limit(target, measurement.low_limit,
                                 measurement.high_limit, True),
            limit_high=calc_limit(target, measurement.low_limit,
                                  measurement.high_limit, False),
            search_limit_low=float(measurement.search_low_limit),
            search_limit_high=float(measurement.search_high_limit),
            freq_gate=_freq_gate(target, unit) if family == "FREQUENCY" else "",
            sample_timeout_value=int(measurement.sample_timeout_value),
            sample_timeout_unit=str(measurement.sample_timeout_unit).strip(),
        )


@dataclass(frozen=True, slots=True)
class TimingContract:
    """Recipe timing facts (``WAIT``/``FWAIT``/``SWAIT``) from ``TrimSpec``.

    A missing value stays ``None``: no default timing is invented here.  The
    platform syntax profile supplies the statement-level timings that are part
    of the registered platform syntax.
    """

    enter_wait: Optional[str]
    trim_force_wait: Optional[str]
    trim_set_wait: Optional[str]
    judge_force_wait: Optional[str]
    judge_set_wait: Optional[str]

    @classmethod
    def compile(cls, spec: TrimSpec) -> "TimingContract":
        by_kind = {operation.kind: operation for operation in spec.operations}
        return cls(
            enter_wait=_duration_text(by_kind.get("ENTER"), "wait"),
            trim_force_wait=_duration_text(by_kind.get("TRIM"), "force_wait"),
            trim_set_wait=_duration_text(by_kind.get("TRIM"), "set_wait"),
            judge_force_wait=_duration_text(by_kind.get("JUDGE"), "force_wait"),
            judge_set_wait=_duration_text(by_kind.get("JUDGE"), "set_wait"),
        )


@dataclass(frozen=True, slots=True)
class RelayContract:
    """Relay identity for one target.

    ``None`` is the explicit no-relay model. Placeholder text is rejected.
    """

    relay: Optional[str]

    @classmethod
    def compile(cls, relay: Optional[str]) -> "RelayContract":
        if relay is None:
            return cls(relay=None)
        text = str(relay).strip()
        if text in ("", "/"):
            raise StandardTrimContractError(
                "ST.RELAY.SLASH",
                "no-relay must be modelled as None/NoRelay, never '/'",
            )
        return cls(relay=text)


@dataclass(frozen=True, slots=True)
class HelperUse:
    """One typed dependency helper: identity, DAC source, bound pattern."""

    helper_name: str
    source_symbol: str
    pattern_ref: str


@dataclass(frozen=True, slots=True)
class HelperContract:
    """Helper identities consumed from confirmed typed contract facts.

    Dependency helpers use ``TrimOperation.helper_name``; the trim-data helper
    identity is consumed from ``TrimSpec.dac.helper_name``.
    """

    dependency_helpers: Tuple[HelperUse, ...]
    trim_data_helper: str
    dac_final_symbol: str

    @classmethod
    def compile(cls, spec: TrimSpec) -> "HelperContract":
        dependency_helpers = tuple(
            HelperUse(
                helper_name=str(operation.helper_name),
                source_symbol=str(operation.source_symbol),
                pattern_ref=str(operation.reference),
            )
            for operation in spec.operations
            if operation.kind == "DEPEND"
            and operation.helper_name
            and operation.source_symbol
        )
        if not dependency_helpers and any(
            operation.kind == "DEPEND" for operation in spec.operations
        ):
            raise StandardTrimContractError(
                "ST.HELPER.DEPEND",
                f"STANDARD_TRIM {spec.item!r} DEPEND operations lack typed "
                "helper/source facts",
            )
        return cls(
            dependency_helpers=dependency_helpers,
            trim_data_helper=str(spec.dac.helper_name),
            dac_final_symbol=str(spec.dac_final_symbol),
        )


@dataclass(frozen=True, slots=True)
class StandardTrimContracts:
    """The six compiled STANDARD_TRIM domain contracts for one target."""

    power: PowerContract
    fbist: FbistContract
    measurement: MeasurementContract
    timing: TimingContract
    relay: RelayContract
    helpers: HelperContract


def compile_standard_trim_contracts(
    spec: TrimSpec,
) -> StandardTrimContracts:
    """Compile and validate all six contracts for one typed TrimSpec.

    This is an internal validation/projection step; it adds no defaults.
    """
    return StandardTrimContracts(
        power=PowerContract.compile(spec),
        fbist=FbistContract.compile(spec),
        measurement=MeasurementContract.compile(spec),
        timing=TimingContract.compile(spec),
        relay=RelayContract.compile(spec.relay),
        helpers=HelperContract.compile(spec),
    )


# ---------------------------------------------------------------------------
# Small typed helpers.
# ---------------------------------------------------------------------------


def _duration_text(operation: Optional[TrimOperation], attribute: str) -> Optional[str]:
    if operation is None:
        return None
    value = getattr(operation, attribute, None)
    if value is None:
        return None
    amount = getattr(value, "amount", None)
    unit = getattr(value, "unit", None)
    if amount is None or unit is None:
        return str(value)
    return f"{amount}{unit}"


def _freq_gate(target: float, unit: str) -> str:
    """Compile the confirmed frequency-measurement gate tiers."""
    magnitude = float(target)
    normalized = str(unit).strip().casefold()
    if normalized == "hz":
        return "@1KHZ"
    if normalized == "khz":
        if magnitude < 1:
            return "@1KHZ"
        if magnitude < 10:
            return "@10KHZ"
        if magnitude < 100:
            return "@100KHZ"
        return "@1MHZ"
    if normalized == "mhz":
        if magnitude < 1:
            return "@1MHZ"
        if magnitude < 5:
            return "@5MHZ"
        if magnitude < 10:
            return "@10MHZ"
        return "@100MHZ"
    raise StandardTrimContractError(
        "ST.MEASUREMENT.UNIT",
        f"frequency unit not supported: {unit!r}",
    )


__all__ = [
    "FbistContract",
    "HelperContract",
    "HelperUse",
    "MeasurementContract",
    "PowerContract",
    "RelayContract",
    "StandardTrimContractError",
    "StandardTrimContracts",
    "TimingContract",
    "compile_standard_trim_contracts",
]
