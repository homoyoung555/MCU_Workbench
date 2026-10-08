"""Upstream workbook compiler for the Flash compare generator.

This is the only layer in the new Flash chain allowed to inspect WorkbookModel.
Its output freezes every Excel-derived value needed by the generator.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re

import fb_map
from program_gen.core.flash_compare_plan import (
    FlashCompareCompileError,
    FlashCompareFacts,
    FlashComparePatternPlan,
    FlashCompareRequest,
    FlashHardwareFacts,
    FlashModeFacts,
    FlashOprFacts,
    FlashRegister,
    FlashRegisterField,
    BulkCoverage,
    BulkStrategy,
    DataKind,
    Operation,
    PageData,
    PageTarget,
    Scope,
    compile_flash_compare_plan,
    random_page_data,
)
from program_gen.workbook import WorkbookModel


class FlashCompareProductCompileError(FlashCompareCompileError):
    """Workbook hardware facts cannot form a deterministic Flash contract."""


REQUIRED_RANDOM_PAGE_SEED = 0x5043443030395631


@dataclass(frozen=True)
class UnsupportedRequiredFlashPattern:
    excel_row: int
    used: str
    output_identity: str
    reason: str


@dataclass(frozen=True)
class RequiredFlashCompareCompilation:
    facts: FlashCompareFacts
    plans: tuple[FlashComparePatternPlan, ...]
    unsupported: tuple[UnsupportedRequiredFlashPattern, ...]
    requests: tuple[FlashCompareRequest, ...] = ()

    def require_complete(self) -> "RequiredFlashCompareCompilation":
        if self.unsupported:
            details = "; ".join(
                f"row {item.excel_row} {item.output_identity}: {item.reason}"
                for item in self.unsupported
            )
            raise FlashCompareProductCompileError(
                "NM_pattern contains unsupported required patterns: " + details
            )
        return self


def compile_flash_compare_facts(workbook: WorkbookModel) -> FlashCompareFacts:
    """Compile VERSION/FLASH_EPR into immutable, workbook-free facts."""
    if not isinstance(workbook, WorkbookModel):
        raise TypeError("compile_flash_compare_facts expects WorkbookModel")
    try:
        version = workbook.dataframe("VERSION")
        epr = workbook.dataframe("FLASH_EPR")
    except KeyError as exc:
        raise FlashCompareProductCompileError(str(exc)) from exc

    spaces = _value_catalog(epr, "space", "page_num")
    modes = _value_catalog(epr, "Description", "mode")
    opr = _value_catalog(epr, "opr_mode", "opr_value")
    chessboard = _value_catalog(epr, "chessboard_mode", "chessboard_data")
    block_bytes = _chessboard_block(chessboard)
    bank_count = _bank_count(_first(version, "bank"))
    comp_flag = str(_first(epr, "comp_flag", default="no")).strip().casefold()
    comp_flag_byte = None
    if comp_flag == "yes":
        comp_flag_byte = _integer(_first(epr, "comp_data"), "FLASH_EPR.comp_data", base=0)

    hardware = FlashHardwareFacts(
        clk_pin=str(_first(version, "CLK PIN")).strip(),
        swd_pin=str(_first(version, "SWD PIN")).strip(),
        registers=_compile_registers(workbook, epr),
        modes=FlashModeFacts(
            normal=_catalog_bits(modes, "normal mode", 4),
            clear_latches=_catalog_bits(modes, "clear page latches", 4),
            write_latches=_catalog_bits(modes, "write page latches", 4),
            pep=_catalog_bits(modes, "PEP", 4),
            erase_page=_catalog_bits(modes, "erase page", 4),
            erase_bulk=_catalog_bits(modes, "bulk erase", 4),
            program_page=_catalog_bits(modes, "program page", 4),
            program_bulk_even_odd=_catalog_bits(modes, "bulk program even/odd pages", 4),
            program_bulk_all=_catalog_bits(modes, "bulk program all pages", 4),
        ),
        opr=FlashOprFacts(
            pre=_catalog_bits(opr, "pre", 2),
            erase=_catalog_bits(opr, "erase", 2),
            program=_catalog_bits(opr, "program", 2),
        ),
    )
    if not hardware.clk_pin or not hardware.swd_pin:
        raise FlashCompareProductCompileError("VERSION CLK PIN/SWD PIN must be non-empty")

    facts = FlashCompareFacts(
        product_identity=workbook.identity,
        nm_page_count=_catalog_int(spaces, "NM"),
        bank_count=bank_count,
        page_bytes=_catalog_int(spaces, "PAGE_BYTES"),
        program_bits=_integer(_first(version, "program bit"), "VERSION.program bit"),
        read_bits=_integer(_first(version, "read bit"), "VERSION.read bit"),
        ecc_cycles=_integer(_first(epr, "ecc", default=0), "FLASH_EPR.ecc"),
        pckb_block_bytes=block_bytes,
        comp_flag_byte=comp_flag_byte,
        boot_loader_page_count=_catalog_int(spaces, "boot loader", default=0),
        hardware=hardware,
    )
    # Reuse the request compiler's product-level validation once, without
    # fabricating a request.
    from program_gen.core.flash_compare_plan import _validate_facts

    _validate_facts(facts)
    return facts


def compile_required_flash_compare_plans(
    workbook: WorkbookModel,
    facts: FlashCompareFacts | None = None,
) -> RequiredFlashCompareCompilation:
    """Compile fixed ``NM_pattern`` rows; never pass their text to Generator."""
    if not isinstance(workbook, WorkbookModel):
        raise TypeError("compile_required_flash_compare_plans expects WorkbookModel")
    facts = facts or compile_flash_compare_facts(workbook)
    try:
        frame = workbook.dataframe("NM_pattern")
    except KeyError as exc:
        raise FlashCompareProductCompileError(str(exc)) from exc
    missing = [name for name in ("used", "Pattern name") if name not in frame.columns]
    if missing:
        raise FlashCompareProductCompileError(
            "NM_pattern missing columns: " + ", ".join(missing)
        )

    plans = []
    requests = []
    unsupported = []
    identities = set()
    for row_index, row in frame.iterrows():
        if _blank(row["used"]) and _blank(row["Pattern name"]):
            continue
        excel_row = int(row_index) + 2
        used = str(row["used"]).strip()
        output = str(row["Pattern name"]).strip()
        if _blank(row['used']) or _blank(row['Pattern name']):
            raise FlashCompareProductCompileError(
                f"NM_pattern row {excel_row}: used and Pattern name must both be set"
            )
        identity = re.sub(r"\.(?:pat|sd)$", "", output, flags=re.IGNORECASE)
        if identity in identities:
            raise FlashCompareProductCompileError(
                f"NM_pattern row {excel_row}: duplicate output identity {identity!r}"
            )
        identities.add(identity)
        try:
            request = _required_request(used, identity, facts)
            plan = compile_flash_compare_plan(request, facts)
        except FlashCompareCompileError as exc:
            unsupported.append(UnsupportedRequiredFlashPattern(
                excel_row, used, identity, str(exc)
            ))
            continue
        plans.append(plan)
        requests.append(request)
    return RequiredFlashCompareCompilation(
        facts, tuple(plans), tuple(unsupported), tuple(requests)
    )


def _required_request(used, identity, facts):
    tokens = used.split()
    if len(tokens) < 3:
        raise FlashCompareProductCompileError(f"invalid used expression: {used!r}")
    scope, operation, data_token = (token.casefold() for token in tokens[:3])
    data_map = {
        "00": DataKind.ZERO,
        "ff": DataKind.ONE,
        "pckb": DataKind.PCKB,
        "nckb": DataKind.NCKB,
    }
    if scope == "page" and operation == "erase" and data_token == "1st":
        return FlashCompareRequest(
            identity, Scope.PAGE, Operation.ERASE,
            pages=(PageTarget(page_index=0),),
            operation_boundary_label="pe_1",
        )
    if scope == "page" and operation in ("program", "epr"):
        if data_token == "random":
            data = random_page_data(REQUIRED_RANDOM_PAGE_SEED, facts.page_bytes)
        else:
            try:
                data = PageData(data_map[data_token])
            except KeyError as exc:
                raise FlashCompareProductCompileError(
                    f"unsupported PageData token: {tokens[2]!r}"
                ) from exc
        if len(tokens) < 4:
            raise FlashCompareProductCompileError("Page program/epr requires a target group")
        target = tokens[3].casefold()
        if target == "1st":
            count = 1
        elif target == "nm":
            count = facts.nm_page_count
        elif target == "btld":
            count = facts.boot_loader_page_count
            if count <= 0:
                raise FlashCompareProductCompileError("boot loader page count is not defined")
        else:
            raise FlashCompareProductCompileError(f"unsupported Page target group: {tokens[3]!r}")
        return FlashCompareRequest(
            identity,
            Scope.PAGE,
            Operation.PROGRAM if operation == "program" else Operation.EPR,
            data=data,
            pages=tuple(PageTarget(page_index=index) for index in range(count)),
            operation_boundary_label=(
                "pe_1" if operation == "program" and target == "1st" else None
            ),
        )
    if scope == "bulk" and operation == "erase":
        coverage_by_token = {
            "all": BulkCoverage.NM_PLUS_SM,
            "nm+sm": BulkCoverage.NM_PLUS_SM,
            "nm": BulkCoverage.NM_ONLY,
        }
        try:
            coverage = coverage_by_token[data_token]
        except KeyError as exc:
            raise FlashCompareProductCompileError(f"unsupported Bulk Erase coverage: {tokens[2]!r}")
        if len(tokens) != 3:
            raise FlashCompareProductCompileError("Bulk Erase requires exactly one coverage")
        return FlashCompareRequest(
            identity, Scope.BULK, Operation.ERASE, bulk_coverage=coverage
        )
    if scope == "bulk" and operation in ("program", "read", "repair"):
        try:
            data = PageData(data_map[data_token])
        except KeyError as exc:
            raise FlashCompareProductCompileError(
                f"unsupported Bulk data token: {tokens[2]!r}"
            ) from exc
        if len(tokens) < 4:
            raise FlashCompareProductCompileError("Bulk expression requires a target")
        target = tokens[3].casefold()
        if operation == "read":
            if len(tokens) != 4:
                raise FlashCompareProductCompileError("Bulk Read accepts only an NM target")
            if target != "nm":
                raise FlashCompareProductCompileError("Bulk Read must target NM")
            return FlashCompareRequest(identity, Scope.BULK, Operation.READ, data=data)
        if operation == "repair":
            if len(tokens) != 4:
                raise FlashCompareProductCompileError("Repair accepts only a bank<N> target")
            match = re.fullmatch(r"bank(\d+)", target)
            if not match:
                raise FlashCompareProductCompileError("Repair target must be bank<N>")
            return FlashCompareRequest(
                identity, Scope.BULK, Operation.REPAIR, data=data,
                repair_bank=int(match.group(1)),
            )
        if len(tokens) == 4:  # backward-compatible legacy Required rows
            if target == "all":
                strategy, coverage = BulkStrategy.ALL_PAGES, BulkCoverage.NM_PLUS_SM
            elif target == "nm":
                strategy, coverage = BulkStrategy.EVEN_ODD, BulkCoverage.NM_ONLY
            else:
                raise FlashCompareProductCompileError(f"unsupported Bulk Program target: {tokens[3]!r}")
        elif len(tokens) == 5:
            try:
                strategy = {
                    "all_pages": BulkStrategy.ALL_PAGES,
                    "even_odd": BulkStrategy.EVEN_ODD,
                }[target]
                coverage = {
                    "nm": BulkCoverage.NM_ONLY,
                    "nm+sm": BulkCoverage.NM_PLUS_SM,
                }[tokens[4].casefold()]
            except KeyError as exc:
                raise FlashCompareProductCompileError(
                    f"unsupported Bulk Program strategy/coverage: {' '.join(tokens[3:])!r}"
                ) from exc
        else:
            raise FlashCompareProductCompileError(
                "Bulk Program requires strategy and coverage"
            )
        return FlashCompareRequest(
            identity, Scope.BULK, Operation.PROGRAM, data=data,
            bulk_strategy=strategy, bulk_coverage=coverage,
        )
    raise FlashCompareProductCompileError(f"unsupported used expression: {used!r}")


def _compile_registers(workbook, frame):
    required = ("addr", "configs")
    missing = [name for name in required if name not in frame.columns]
    if missing:
        raise FlashCompareProductCompileError(
            "FLASH_EPR missing columns: " + ", ".join(missing)
        )
    fb_index = fb_map.build_index_from_workbook(workbook)
    by_addr: dict[str, list[FlashRegisterField]] = {}
    order = []
    for row_index, row in frame.iterrows():
        raw_configs = row["configs"]
        if _blank(raw_configs):
            continue
        excel_row = int(row_index) + 2
        try:
            parsed = fb_map.parse_epr_configs(raw_configs)
            names = [name for name, _offset, _width in parsed]
            addr, _derived = fb_map.resolve_addr(row["addr"], names, fb_index)
            addr = str(addr).strip()
            if not re.fullmatch(r"[01]{7}", addr):
                raise ValueError(f"addr {addr!r} is not 7 bits")
            addr_int = int(addr, 2)
            fields = []
            for name, offset, width in parsed:
                if offset is None:
                    offset, width = fb_map.resolve_field_width(name, addr_int, fb_index)
                fields.append(FlashRegisterField(str(name), int(offset), int(width)))
        except (TypeError, ValueError) as exc:
            raise FlashCompareProductCompileError(
                f"FLASH_EPR row {excel_row}: {exc}"
            ) from exc
        if addr not in by_addr:
            by_addr[addr] = []
            order.append(addr)
        by_addr[addr].extend(fields)

    registers = []
    seen_names = set()
    for addr in order:
        fields = tuple(by_addr[addr])
        occupied = {}
        for field in fields:
            if field.bit_offset < 0 or field.bit_width <= 0 or field.bit_offset + field.bit_width > 16:
                raise FlashCompareProductCompileError(
                    f"FLASH_EPR {addr}: field {field.name} exceeds 16-bit register"
                )
            if field.name in seen_names:
                raise FlashCompareProductCompileError(
                    f"FLASH_EPR field appears more than once: {field.name}"
                )
            seen_names.add(field.name)
            for bit in range(field.bit_offset, field.bit_offset + field.bit_width):
                if bit in occupied:
                    raise FlashCompareProductCompileError(
                        f"FLASH_EPR {addr}: {field.name} overlaps {occupied[bit]} at bit {bit}"
                    )
                occupied[bit] = field.name
        registers.append(FlashRegister(addr, fields))
    if not registers:
        raise FlashCompareProductCompileError("FLASH_EPR contains no register definitions")
    return tuple(registers)


def _value_catalog(frame, key_column, value_column):
    missing = [name for name in (key_column, value_column) if name not in frame.columns]
    if missing:
        raise FlashCompareProductCompileError(
            "FLASH_EPR missing columns: " + ", ".join(missing)
        )
    values = {}
    for key, value in zip(frame[key_column], frame[value_column]):
        if _blank(key):
            continue
        normalized = str(key).strip().casefold()
        if normalized in values and str(values[normalized]) != str(value):
            raise FlashCompareProductCompileError(
                f"FLASH_EPR duplicate catalog key with different values: {key!r}"
            )
        values[normalized] = value
    return values


def _catalog_bits(catalog, key, width):
    normalized = key.casefold()
    if normalized not in catalog:
        raise FlashCompareProductCompileError(f"FLASH_EPR missing encoding: {key}")
    value = catalog[normalized]
    text = str(value).strip()
    if isinstance(value, bool):
        raise FlashCompareProductCompileError(f"{key} must be a {width}-bit value")
    if re.fullmatch(r"[01]+", text):
        bits = text.zfill(width)
    else:
        bits = format(_integer(value, key), f"0{width}b")
    if len(bits) != width:
        raise FlashCompareProductCompileError(f"{key} must be exactly {width} bits")
    return bits


def _catalog_int(catalog, key, default=None):
    try:
        value = catalog[key.casefold()]
    except KeyError:
        if default is not None:
            return default
        raise FlashCompareProductCompileError(f"FLASH_EPR missing product fact: {key}")
    return _integer(value, f"FLASH_EPR.{key}")


def _chessboard_block(catalog):
    parsed = {}
    for name in ("PCKB", "NCKB"):
        try:
            value = str(catalog[name.casefold()]).strip()
        except KeyError as exc:
            raise FlashCompareProductCompileError(f"FLASH_EPR missing {name} definition") from exc
        match = re.fullmatch(r"(\d+)\s*bytes?\s*([01])", value, flags=re.IGNORECASE)
        if not match:
            raise FlashCompareProductCompileError(
                f"FLASH_EPR {name} must use '<bytes> bytes <0|1>' format"
            )
        parsed[name] = (int(match.group(1)), match.group(2))
    if parsed["PCKB"][0] != parsed["NCKB"][0] or parsed["PCKB"][1:] != ("0",) or parsed["NCKB"][1:] != ("1",):
        raise FlashCompareProductCompileError(
            "PCKB/NCKB must use the same block size and inverse 0/1 phases"
        )
    return parsed["PCKB"][0]


def _bank_count(value):
    normalized = str(value).strip().casefold()
    if normalized == "single":
        return 1
    if normalized == "double":
        return 2
    raise FlashCompareProductCompileError(
        f"VERSION.bank must be single or double; got {value!r}"
    )


def _first(frame, column, default=None):
    if column not in frame.columns:
        if default is not None:
            return default
        raise FlashCompareProductCompileError(f"missing column: {column}")
    for value in frame[column]:
        if not _blank(value):
            return value
    if default is not None:
        return default
    raise FlashCompareProductCompileError(f"column has no value: {column}")


def _integer(value, label, base=10):
    if isinstance(value, bool):
        raise FlashCompareProductCompileError(f"{label} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value) or not value.is_integer():
            raise FlashCompareProductCompileError(f"{label} must be an integer")
        return int(value)
    text = str(value).strip()
    try:
        return int(text, base)
    except ValueError as exc:
        raise FlashCompareProductCompileError(f"{label} must be an integer") from exc


def _blank(value):
    return value is None or (isinstance(value, float) and math.isnan(value)) or (
        isinstance(value, str) and not value.strip()
    )


__all__ = [
    "FlashCompareProductCompileError", "RequiredFlashCompareCompilation",
    "UnsupportedRequiredFlashPattern", "compile_flash_compare_facts",
    "compile_required_flash_compare_plans",
]
