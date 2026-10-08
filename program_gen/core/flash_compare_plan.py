"""Platform-neutral planning for Flash compare patterns.

This module owns user intent and product rules.  It deliberately knows
nothing about Excel cells, GUI state, output directories, Chroma or S100
syntax.  Platform renderers consume the immutable plan produced here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Iterable, Mapping, Sequence


class FlashCompareCompileError(ValueError):
    """A request cannot be compiled against the supplied product facts."""


class FlashProductDefinitionMissing(FlashCompareCompileError):
    """The product master does not define enough facts for this scope."""


class Scope(str, Enum):
    PAGE = "page"
    BULK = "bulk"
    SECTOR = "sector"


class Operation(str, Enum):
    ERASE = "erase"
    PROGRAM = "program"
    READ = "read"
    REPAIR = "repair"
    EPR = "epr"


class DataKind(str, Enum):
    ZERO = "00"
    ONE = "FF"
    PCKB = "PCKB"
    NCKB = "NCKB"
    CUSTOM = "CUSTOM"


class Region(str, Enum):
    NM = "NM"
    SM = "SM"


class BulkStrategy(str, Enum):
    EVEN_ODD = "EVEN_ODD"
    ALL_PAGES = "ALL_PAGES"


class BulkCoverage(str, Enum):
    NM_ONLY = "NM_ONLY"
    NM_PLUS_SM = "NM_PLUS_SM"


@dataclass(frozen=True)
class KnownPage:
    name: str
    region: Region
    logical_bank: int
    ra: int


@dataclass(frozen=True)
class FlashRegisterField:
    name: str
    bit_offset: int
    bit_width: int


@dataclass(frozen=True)
class FlashRegister:
    addr_bits: str
    fields: tuple[FlashRegisterField, ...]


@dataclass(frozen=True)
class FlashModeFacts:
    normal: str
    clear_latches: str
    write_latches: str
    pep: str
    erase_page: str
    erase_bulk: str
    program_page: str
    program_bulk_even_odd: str
    program_bulk_all: str


@dataclass(frozen=True)
class FlashOprFacts:
    pre: str
    erase: str
    program: str


@dataclass(frozen=True)
class FlashHardwareFacts:
    clk_pin: str
    swd_pin: str
    registers: tuple[FlashRegister, ...]
    modes: FlashModeFacts
    opr: FlashOprFacts


@dataclass(frozen=True)
class FlashCompareFacts:
    """Validated hardware/product facts, normally compiled from the master."""

    product_identity: str
    nm_page_count: int
    bank_count: int
    page_bytes: int
    program_bits: int
    read_bits: int
    ecc_cycles: int = 0
    pckb_block_bytes: int = 8
    comp_flag_byte: int | None = None
    known_pages: tuple[KnownPage, ...] = ()
    boot_loader_page_count: int = 0
    hardware: FlashHardwareFacts | None = None

    @property
    def pages_per_bank(self) -> int:
        return self.nm_page_count // self.bank_count


@dataclass(frozen=True)
class PageTarget:
    """Exactly one of ``page_index`` and ``known_page`` must be supplied."""

    page_index: int | None = None
    known_page: str | None = None


@dataclass(frozen=True)
class PageData:
    kind: DataKind
    payload: bytes = b""
    random_seed: int | None = None


@dataclass(frozen=True)
class FlashCompareRequest:
    output_identity: str
    scope: Scope
    operation: Operation
    data: PageData | None = None
    pages: tuple[PageTarget, ...] = ()
    bulk_strategy: BulkStrategy | None = None
    bulk_coverage: BulkCoverage | None = None
    repair_bank: int | None = None
    operation_boundary_label: str | None = None


@dataclass(frozen=True)
class CanonicalPageAddress:
    region: Region
    logical_bank: int
    bank_bits: str
    axa: int
    ra: int
    ca: int = 0
    pa: int = 0


@dataclass(frozen=True)
class FlashComparePass:
    """One independently closed Page/Bulk hardware operation pass."""

    logical_bank: int
    bank_bits: str
    axa: int
    ra: int
    stages: tuple[str, ...]
    data: PageData | None = None
    parity: str | None = None
    compare_number: int = 0
    fbist_cmd: str | None = None


@dataclass(frozen=True)
class FlashComparePatternPlan:
    output_identity: str
    facts: FlashCompareFacts
    scope: Scope
    operation: Operation
    passes: tuple[FlashComparePass, ...]
    program_groups_per_page: int
    read_groups_per_page: int
    ecc_cycles: int
    comp_flag_bits: str
    operation_boundary_label: str | None = None

    @property
    def identity(self) -> str:
        raw = json.dumps(
            _canonical(self), sort_keys=True, separators=(",", ":")
        ).encode("ascii")
        return hashlib.sha256(raw).hexdigest().upper()


def compile_flash_compare_plan(
    request: FlashCompareRequest, facts: FlashCompareFacts
) -> FlashComparePatternPlan:
    """Compile one explicit request without consulting Excel or global state."""
    _validate_facts(facts)
    _validate_request_identity(request.output_identity)
    if request.scope is Scope.SECTOR:
        raise FlashProductDefinitionMissing(
            "SECTOR_PRODUCT_DEFINITION_MISSING: sector erase mode, geometry, "
            "RA encoding, region/AXA, RED, SEQ profile and chessboard phase "
            "are not defined"
        )

    data = _validate_data(request, facts)
    if request.scope is Scope.PAGE:
        passes = _compile_page(request, facts, data)
    elif request.scope is Scope.BULK:
        passes = _compile_bulk(request, facts, data)
    else:  # defensive against non-Enum construction
        raise FlashCompareCompileError(f"unsupported Flash scope: {request.scope!r}")

    return FlashComparePatternPlan(
        output_identity=request.output_identity,
        facts=facts,
        scope=request.scope,
        operation=request.operation,
        passes=passes,
        program_groups_per_page=facts.page_bytes * 8 // facts.program_bits,
        read_groups_per_page=facts.page_bytes * 8 // facts.read_bits,
        ecc_cycles=facts.ecc_cycles,
        comp_flag_bits=(
            "" if facts.comp_flag_byte is None else f"{facts.comp_flag_byte:08b}"
        ),
        operation_boundary_label=request.operation_boundary_label,
    )


def compile_flash_compare_plans(
    requests: Iterable[FlashCompareRequest], facts: FlashCompareFacts
) -> tuple[FlashComparePatternPlan, ...]:
    """Compile an ordered request set and reject artifact identity collisions."""
    plans = []
    identities = set()
    for request in requests:
        plan = compile_flash_compare_plan(request, facts)
        if plan.output_identity in identities:
            raise FlashCompareCompileError(
                f"duplicate Flash output identity: {plan.output_identity!r}"
            )
        identities.add(plan.output_identity)
        plans.append(plan)
    return tuple(plans)


def parse_word_value(value: int | str) -> int:
    """Parse ``0x44332211`` or ``44 33 22 11`` as the same 32-bit word."""
    if isinstance(value, bool):
        raise FlashCompareCompileError("boolean is not a 32-bit word")
    if isinstance(value, int):
        word = value
    else:
        text = str(value).strip()
        byte_tokens = text.split()
        if len(byte_tokens) == 4 and all(
            re.fullmatch(r"(?:0x)?[0-9a-fA-F]{2}", token)
            for token in byte_tokens
        ):
            text = "".join(token.removeprefix("0x").removeprefix("0X") for token in byte_tokens)
            word = int(text, 16)
        else:
            try:
                word = int(text, 0)
            except ValueError as exc:
                raise FlashCompareCompileError(
                    f"invalid 32-bit word literal: {value!r}"
                ) from exc
    if not 0 <= word <= 0xFFFFFFFF:
        raise FlashCompareCompileError(f"32-bit word out of range: {value!r}")
    return word


def custom_page_data(values: Sequence[int | str], page_bytes: int) -> PageData:
    """Normalize ascending-address 32-bit words or byte tokens to PageData."""
    if page_bytes <= 0 or page_bytes % 4:
        raise FlashCompareCompileError("page_bytes must be a positive multiple of 4")
    if len(values) == page_bytes // 4:
        words = [parse_word_value(value) for value in values]
    elif len(values) == page_bytes:
        octets = []
        for value in values:
            text = str(value).strip()
            if not re.fullmatch(r"(?:0x)?[0-9a-fA-F]{2}", text):
                raise FlashCompareCompileError(f"invalid byte token: {value!r}")
            octets.append(int(text, 16))
        words = [
            int.from_bytes(bytes(octets[index:index + 4]), "big")
            for index in range(0, len(octets), 4)
        ]
    else:
        raise FlashCompareCompileError(
            f"custom page requires exactly {page_bytes // 4} words or "
            f"{page_bytes} byte tokens; got {len(values)}"
        )
    return PageData(
        DataKind.CUSTOM,
        b"".join(word.to_bytes(4, "big") for word in words),
    )


def random_page_data(seed: int, page_bytes: int) -> PageData:
    """Build one reproducible pseudo-random page from an explicit 64-bit seed."""
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 1 << 64:
        raise FlashCompareCompileError("random seed must be a 64-bit unsigned integer")
    if isinstance(page_bytes, bool) or not isinstance(page_bytes, int) or page_bytes <= 0:
        raise FlashCompareCompileError("page_bytes must be a positive integer")
    prefix = b"flash-page-random/v1\0" + seed.to_bytes(8, "big")
    payload = bytearray()
    counter = 0
    while len(payload) < page_bytes:
        payload.extend(hashlib.sha256(prefix + counter.to_bytes(8, "big")).digest())
        counter += 1
    return PageData(DataKind.CUSTOM, bytes(payload[:page_bytes]), seed)


def materialize_page_data(data: PageData, facts: FlashCompareFacts) -> bytes:
    """Return bytes in ascending Page Word address order."""
    if data.kind is DataKind.ZERO:
        return bytes(facts.page_bytes)
    if data.kind is DataKind.ONE:
        return bytes([0xFF]) * facts.page_bytes
    if data.kind in (DataKind.PCKB, DataKind.NCKB):
        first = 0 if data.kind is DataKind.PCKB else 0xFF
        block = facts.pckb_block_bytes
        return bytes(
            first if (index // block) % 2 == 0 else first ^ 0xFF
            for index in range(facts.page_bytes)
        )
    if data.kind is DataKind.CUSTOM:
        if len(data.payload) != facts.page_bytes:
            raise FlashCompareCompileError(
                f"custom page payload is {len(data.payload)} bytes; expected {facts.page_bytes}"
            )
        return data.payload
    raise FlashCompareCompileError(f"unsupported PageData kind: {data.kind!r}")


def serialize_command_groups(
    data: PageData, facts: FlashCompareFacts, command_bits: int
) -> tuple[str, ...]:
    """Split one page into commands, reversing 32-bit words inside each command."""
    if command_bits <= 0 or command_bits % 32:
        raise FlashCompareCompileError("command width must be a positive multiple of 32")
    command_bytes = command_bits // 8
    if facts.page_bytes % command_bytes:
        raise FlashCompareCompileError("page size must be divisible by command width")
    page = materialize_page_data(data, facts)
    groups = []
    for offset in range(0, len(page), command_bytes):
        chunk = page[offset:offset + command_bytes]
        words = [chunk[index:index + 4] for index in range(0, len(chunk), 4)]
        groups.append("".join(f"{byte:08b}" for word in reversed(words) for byte in word))
    return tuple(groups)


def _compile_page(request, facts, data):
    if not request.pages:
        raise FlashCompareCompileError("Page request requires at least one page target")
    if request.operation is Operation.REPAIR:
        raise FlashCompareCompileError("Repair is a Bulk-only operation")
    if request.bulk_strategy is not None or request.bulk_coverage is not None or request.repair_bank is not None:
        raise FlashCompareCompileError("Page request cannot set Bulk/Repair options")
    stages = {
        Operation.ERASE: ("pre_program", "erase", "clear_latches"),
        Operation.PROGRAM: ("clear_latches", "write_latches", "program"),
        Operation.READ: ("read_compare",),
        Operation.EPR: (
            "pre_program", "erase", "clear_latches",
            "clear_latches", "write_latches", "program", "read_compare",
        ),
    }[request.operation]
    return tuple(
        FlashComparePass(
            logical_bank=address.logical_bank,
            bank_bits=address.bank_bits,
            axa=address.axa,
            ra=address.ra,
            stages=stages,
            data=data,
            fbist_cmd="1000" if request.operation in (Operation.READ, Operation.EPR) else None,
        )
        for address in (_resolve_page(target, facts) for target in request.pages)
    )


def _compile_bulk(request, facts, data):
    if request.pages:
        raise FlashCompareCompileError("Bulk request cannot set Page targets")
    if request.operation is Operation.EPR:
        raise FlashCompareCompileError("EPR is a Page-only composite operation")
    bank_order = range(facts.bank_count)
    if request.operation is Operation.ERASE:
        if request.repair_bank is not None:
            raise FlashCompareCompileError("Bulk Erase cannot set repair_bank")
        if request.bulk_strategy is not None:
            raise FlashCompareCompileError("Bulk Erase has no EVEN_ODD/ALL_PAGES strategy")
        coverage = request.bulk_coverage or BulkCoverage.NM_ONLY
        return tuple(
            _bulk_pass(bank, coverage, 0, ("pre_program", "erase", "clear_latches"))
            for bank in bank_order
        )
    if request.operation is Operation.READ:
        if request.repair_bank is not None:
            raise FlashCompareCompileError("Bulk Read cannot set repair_bank")
        if request.bulk_strategy is not None or request.bulk_coverage not in (None, BulkCoverage.NM_ONLY):
            raise FlashCompareCompileError("Bulk Read is fixed to NM_ONLY and has no strategy")
        compare_number = facts.pages_per_bank * facts.page_bytes * 8 // facts.read_bits
        return tuple(
            FlashComparePass(
                logical_bank=bank,
                bank_bits=_bank_bits(bank, facts.bank_count),
                axa=0,
                ra=0,
                stages=("read_compare_internal",),
                data=data,
                compare_number=compare_number,
                fbist_cmd="1101",
            )
            for bank in bank_order
        )

    if request.operation is Operation.REPAIR:
        if request.bulk_strategy is not None or request.bulk_coverage not in (None, BulkCoverage.NM_ONLY):
            raise FlashCompareCompileError("Repair is fixed to NM_ONLY and has no strategy")
        if request.repair_bank is None or not 0 <= request.repair_bank < facts.bank_count:
            raise FlashCompareCompileError(
                f"Repair requires repair_bank in 0..{facts.bank_count - 1}"
            )
        compare_number = facts.pages_per_bank * facts.page_bytes * 8 // facts.read_bits
        bank = request.repair_bank
        return (FlashComparePass(
            logical_bank=bank,
            bank_bits=_bank_bits(bank, facts.bank_count),
            axa=0,
            ra=0,
            stages=("repair_compare_internal",),
            data=data,
            compare_number=compare_number,
            fbist_cmd="1010",
        ),)

    if request.bulk_strategy is None:
        raise FlashCompareCompileError("Bulk Program requires EVEN_ODD or ALL_PAGES strategy")
    coverage = request.bulk_coverage or BulkCoverage.NM_ONLY
    stages = ("clear_latches", "write_latches", "program")
    if request.bulk_strategy is BulkStrategy.ALL_PAGES:
        return tuple(_bulk_pass(bank, coverage, 0, stages, data=data) for bank in bank_order)

    passes = []
    for parity, ra in (("odd", 1), ("even", 0)):
        phase = data
        if data is not None and data.kind in (DataKind.PCKB, DataKind.NCKB):
            selected = data.kind
            if parity == "even":
                selected = DataKind.NCKB if selected is DataKind.PCKB else DataKind.PCKB
            phase = PageData(selected)
        for bank in bank_order:
            passes.append(_bulk_pass(bank, coverage, ra, stages, data=phase, parity=parity))
    return tuple(passes)


def _bulk_pass(bank, coverage, ra, stages, data=None, parity=None):
    return FlashComparePass(
        logical_bank=bank,
        bank_bits="01" if bank == 0 else "10",
        axa=0 if coverage is BulkCoverage.NM_ONLY else 1,
        ra=ra,
        stages=stages,
        data=data,
        parity=parity,
    )


def _resolve_page(target, facts):
    if (target.page_index is None) == (target.known_page is None):
        raise FlashCompareCompileError(
            "Page target must set exactly one of page_index and known_page"
        )
    if target.known_page is not None:
        catalog: Mapping[str, KnownPage] = {
            page.name.casefold(): page for page in facts.known_pages
        }
        try:
            page = catalog[target.known_page.casefold()]
        except KeyError as exc:
            raise FlashCompareCompileError(
                f"unknown catalog Page: {target.known_page!r}"
            ) from exc
        if not 0 <= page.logical_bank < facts.bank_count:
            raise FlashCompareCompileError(f"known Page {page.name!r} has invalid bank")
        _validate_ra_width(page.ra, facts)
        return CanonicalPageAddress(
            region=page.region,
            logical_bank=page.logical_bank,
            bank_bits=_bank_bits(page.logical_bank, facts.bank_count),
            axa=1 if page.region is Region.SM else 0,
            ra=page.ra,
        )
    index = target.page_index
    if index is None or not 0 <= index < facts.nm_page_count:
        raise FlashCompareCompileError(
            f"NM page_index must be in 0..{facts.nm_page_count - 1}; got {index!r}"
        )
    bank = index // facts.pages_per_bank
    ra = index % facts.pages_per_bank
    _validate_ra_width(ra, facts)
    return CanonicalPageAddress(
        region=Region.NM,
        logical_bank=bank,
        bank_bits=_bank_bits(bank, facts.bank_count),
        axa=0,
        ra=ra,
    )


def _validate_data(request, facts):
    if request.operation is Operation.ERASE:
        if request.data is not None:
            raise FlashCompareCompileError("Erase request does not accept PageData")
        return None
    if request.data is None:
        raise FlashCompareCompileError(f"{request.operation.value} request requires PageData")
    materialize_page_data(request.data, facts)
    if request.scope is Scope.BULK and request.operation in (Operation.READ, Operation.REPAIR):
        if request.data.kind not in (DataKind.ZERO, DataKind.ONE, DataKind.PCKB, DataKind.NCKB):
            raise FlashCompareCompileError(
                "Bulk Read supports only 00/FF/PCKB/NCKB; verify custom data with Page Read"
            )
    return request.data


def _validate_facts(facts):
    integers = (
        ("nm_page_count", facts.nm_page_count),
        ("bank_count", facts.bank_count),
        ("page_bytes", facts.page_bytes),
        ("program_bits", facts.program_bits),
        ("read_bits", facts.read_bits),
        ("pckb_block_bytes", facts.pckb_block_bytes),
    )
    for name, value in integers:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise FlashCompareCompileError(f"{name} must be a positive integer")
    if facts.nm_page_count % facts.bank_count:
        raise FlashCompareCompileError("NM pages must divide evenly across banks")
    total_bits = facts.page_bytes * 8
    if total_bits % facts.program_bits or total_bits % facts.read_bits:
        raise FlashCompareCompileError("page bits must divide by program_bits and read_bits")
    if facts.program_bits % 32 or facts.read_bits % 32:
        raise FlashCompareCompileError("program_bits/read_bits must be multiples of 32")
    if facts.page_bytes % facts.pckb_block_bytes:
        raise FlashCompareCompileError("page_bytes must divide by pckb_block_bytes")
    if isinstance(facts.ecc_cycles, bool) or not isinstance(facts.ecc_cycles, int) or facts.ecc_cycles < 0:
        raise FlashCompareCompileError("ecc_cycles must be a non-negative integer")
    if (
        isinstance(facts.boot_loader_page_count, bool)
        or not isinstance(facts.boot_loader_page_count, int)
        or not 0 <= facts.boot_loader_page_count <= facts.nm_page_count
    ):
        raise FlashCompareCompileError(
            "boot_loader_page_count must be in 0..nm_page_count"
        )
    if facts.comp_flag_byte is not None and not 0 <= facts.comp_flag_byte <= 0xFF:
        raise FlashCompareCompileError("comp_flag_byte must be 0..255 or None")


def _validate_request_identity(identity):
    if not isinstance(identity, str) or not identity.strip():
        raise FlashCompareCompileError("output_identity must be non-empty")
    if any(char in identity for char in "\\/\0"):
        raise FlashCompareCompileError("output_identity must not contain path separators")


def _validate_ra_width(ra, facts):
    hardware = facts.hardware
    if hardware is None:
        return
    widths = tuple(
        field.bit_width
        for register in hardware.registers
        for field in register.fields
        if field.name == "RA"
    )
    if len(widths) != 1:
        raise FlashCompareCompileError(
            "Flash hardware contract must define exactly one RA field"
        )
    if ra >= 1 << widths[0]:
        raise FlashCompareCompileError(
            f"RA={ra} requires {ra.bit_length()} bits, but FLASH_EPR RA width is {widths[0]}"
        )


def _bank_bits(bank, count):
    if count > 2:
        raise FlashCompareCompileError("current BANK_SEL/BANK_EN encoding supports at most 2 banks")
    if not 0 <= bank < count:
        raise FlashCompareCompileError(f"logical bank out of range: {bank}")
    return "01" if bank == 0 else "10"


def _canonical(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bytes):
        return value.hex().upper()
    if hasattr(value, "__dataclass_fields__"):
        return {
            name: _canonical(getattr(value, name))
            for name in value.__dataclass_fields__
        }
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    return value


__all__ = [
    "BulkCoverage", "BulkStrategy", "CanonicalPageAddress", "DataKind",
    "FlashCompareCompileError", "FlashCompareFacts", "FlashComparePass",
    "FlashHardwareFacts", "FlashModeFacts", "FlashOprFacts", "FlashRegister",
    "FlashRegisterField",
    "FlashComparePatternPlan", "FlashCompareRequest",
    "FlashProductDefinitionMissing", "KnownPage", "Operation", "PageData",
    "PageTarget", "Region", "Scope", "compile_flash_compare_plan",
    "compile_flash_compare_plans",
    "custom_page_data", "random_page_data", "materialize_page_data", "parse_word_value",
    "serialize_command_groups",
]
