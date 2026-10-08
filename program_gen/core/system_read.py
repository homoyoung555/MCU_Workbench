"""Compile the two mandatory system read tests into workbook-free specs."""

from __future__ import annotations

from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Mapping

import pandas as pd


class SystemReadCompileError(ValueError):
    """VERSION/ADDR_MAP/FLASH_EPR cannot close mandatory read facts."""


@dataclass(frozen=True, slots=True)
class SystemReadFacts:
    cp: str
    swd_pin: str
    page_bytes: int
    read_bit: int
    ra_addresses: tuple[int, ...]
    nm_page_count: int
    bank_count: int


@dataclass(frozen=True, slots=True)
class OtpReadSpec:
    typed_kind: str
    cp: str
    definition_identity: str
    render_name: str
    swd_pin: str
    page_bytes: int
    read_bit: int
    ra_addresses: tuple[int, ...]
    chroma_hardware_bin: str
    chroma_software_bin: str
    chroma_bin_source: str


@dataclass(frozen=True, slots=True)
class NmDataReadSpec:
    typed_kind: str
    cp: str
    definition_identity: str
    render_name: str
    swd_pin: str
    page_bytes: int
    page_count: int
    bank_count: int
    read_bit: int
    chroma_hardware_bin: str
    chroma_software_bin: str
    chroma_bin_source: str

    @property
    def pages_per_bank(self) -> int:
        return self.page_count // self.bank_count


@dataclass(frozen=True, slots=True)
class SystemReadSpecSet:
    otp_read: OtpReadSpec
    nm_data_read: NmDataReadSpec


def compile_system_read_facts(
    version: pd.DataFrame,
    addr_map: pd.DataFrame,
    flash_epr: pd.DataFrame,
) -> Mapping[str, SystemReadFacts]:
    """Compile all raw workbook cells used by the two fixed algorithms."""
    _require_columns(
        version, "VERSION", ("CP num", "SWD PIN", "page word", "read bit", "bank")
    )
    _require_columns(addr_map, "ADDR_MAP", ("Word No.", "SM Address"))
    _require_columns(flash_epr, "FLASH_EPR", ("space", "page_num"))

    nm_page_count = _space_value(flash_epr, "NM")
    declared_page_bytes = _space_value(flash_epr, "PAGE_BYTES")
    ra_addresses = _ra_addresses(addr_map)

    by_cp: dict[str, SystemReadFacts] = {}
    for _, row in version.iterrows():
        cp = _text(row["CP num"]).upper()
        if not cp:
            continue
        if cp in by_cp:
            raise SystemReadCompileError(
                f"SYS.READ.VERSION.CP_DUPLICATE: {cp} has more than one VERSION row"
            )
        page_words = _positive_int(row["page word"], f"VERSION.{cp}.page word")
        page_bytes = page_words * 4
        if page_bytes != declared_page_bytes:
            raise SystemReadCompileError(
                "SYS.READ.PAGE_BYTES_MISMATCH: "
                f"VERSION {page_bytes} != FLASH_EPR {declared_page_bytes}"
            )
        read_bit = _positive_int(row["read bit"], f"VERSION.{cp}.read bit")
        if read_bit % 32:
            raise SystemReadCompileError(
                f"SYS.READ.READ_BIT: {cp} read bit must be a 32-bit multiple"
            )
        bank = _text(row["bank"]).casefold()
        if bank not in ("single", "double"):
            raise SystemReadCompileError(
                f"SYS.READ.BANK: {cp} bank must be single or double"
            )
        bank_count = 1 if bank == "single" else 2
        if nm_page_count % bank_count:
            raise SystemReadCompileError(
                f"SYS.READ.NM_PAGE_COUNT: {nm_page_count} is not divisible by {bank_count}"
            )
        swd_pin = _text(row["SWD PIN"])
        if not swd_pin:
            raise SystemReadCompileError(f"SYS.READ.SWD_PIN_MISSING: {cp}")
        by_cp[cp] = SystemReadFacts(
            cp=cp,
            swd_pin=swd_pin,
            page_bytes=page_bytes,
            read_bit=read_bit,
            ra_addresses=ra_addresses,
            nm_page_count=nm_page_count,
            bank_count=bank_count,
        )
    if not by_cp:
        raise SystemReadCompileError("SYS.READ.VERSION.EMPTY: no CP rows")
    return MappingProxyType(by_cp)


def bind_system_read_specs(
    facts: SystemReadFacts,
    canonical_schedule,
) -> SystemReadSpecSet:
    """Bind fixed definitions and the approved Chroma shared-bin policy."""
    definitions = {item.item.casefold(): item for item in canonical_schedule.definitions}
    try:
        otp_definition = definitions["otp_read"]
        nm_definition = definitions["nm_data_read"]
    except KeyError as error:
        raise SystemReadCompileError(
            f"SYS.READ.DEFINITION_MISSING: {error.args[0]}"
        ) from error

    id_item = f"pgm_{facts.cp}id_read".casefold()
    try:
        id_definition = definitions[id_item]
    except KeyError as error:
        raise SystemReadCompileError(
            f"SYS.READ.CHROMA_BIN_SOURCE_MISSING: Pgm_{facts.cp}ID_Read"
        ) from error
    entries = tuple(
        item for item in canonical_schedule.entries
        if item.definition_id.casefold() == id_definition.identity.casefold()
    )
    if len(entries) != 1:
        raise SystemReadCompileError(
            "SYS.READ.CHROMA_BIN_SOURCE_AMBIGUOUS: "
            f"{id_definition.item} has {len(entries)} schedule entries"
        )
    binding = entries[0].bin_binding
    if not binding.hardware_bin or not binding.software_bin:
        raise SystemReadCompileError(
            f"SYS.READ.CHROMA_BIN_MISSING: {id_definition.item}"
        )
    common = dict(
        cp=facts.cp,
        swd_pin=facts.swd_pin,
        page_bytes=facts.page_bytes,
        read_bit=facts.read_bit,
        chroma_hardware_bin=binding.hardware_bin,
        chroma_software_bin=binding.software_bin,
        chroma_bin_source=id_definition.item,
    )
    return SystemReadSpecSet(
        otp_read=OtpReadSpec(
            typed_kind="SYSTEM_OTP_READ",
            definition_identity=otp_definition.identity,
            render_name=otp_definition.render_name,
            ra_addresses=facts.ra_addresses,
            **common,
        ),
        nm_data_read=NmDataReadSpec(
            typed_kind="SYSTEM_NM_DATA_READ",
            definition_identity=nm_definition.identity,
            render_name=nm_definition.render_name,
            page_count=facts.nm_page_count,
            bank_count=facts.bank_count,
            **common,
        ),
    )


def _space_value(frame: pd.DataFrame, key: str) -> int:
    selected = tuple(
        row for _, row in frame.iterrows()
        if _text(row["space"]).casefold() == key.casefold()
    )
    if len(selected) != 1:
        raise SystemReadCompileError(
            f"SYS.READ.FLASH_EPR.{key}: expected one row, got {len(selected)}"
        )
    return _positive_int(selected[0]["page_num"], f"FLASH_EPR.{key}.page_num")


def _ra_addresses(frame: pd.DataFrame) -> tuple[int, ...]:
    seen_pages: set[str] = set()
    result: list[int] = []
    for _, row in frame.iterrows():
        page = _text(row["Word No."])
        if not page or page.casefold() in seen_pages:
            continue
        seen_pages.add(page.casefold())
        address = _text(row["SM Address"])
        match = re.search(r"\bRA\s*\[[^]]+\]\s*=\s*0x([0-9a-f]+)", address, re.I)
        if match is None:
            raise SystemReadCompileError(
                f"SYS.READ.ADDR_MAP.RA_MISSING: page {page!r}"
            )
        result.append(int(match.group(1), 16))
    if not result:
        raise SystemReadCompileError("SYS.READ.ADDR_MAP.EMPTY: no page RA addresses")
    return tuple(result)


def _positive_int(value, context: str) -> int:
    try:
        result = int(float(value))
    except (TypeError, ValueError) as error:
        raise SystemReadCompileError(
            f"SYS.READ.NUMBER_INVALID: {context}={value!r}"
        ) from error
    if result <= 0 or float(value) != result:
        raise SystemReadCompileError(
            f"SYS.READ.NUMBER_INVALID: {context}={value!r}"
        )
    return result


def _require_columns(frame: pd.DataFrame, sheet: str, columns: tuple[str, ...]) -> None:
    missing = tuple(column for column in columns if column not in frame.columns)
    if missing:
        raise SystemReadCompileError(
            f"SYS.READ.COLUMN_MISSING: {sheet}.{missing[0]}"
        )


def _text(value) -> str:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return ""
    return str(value).strip()


__all__ = [
    "NmDataReadSpec",
    "OtpReadSpec",
    "SystemReadCompileError",
    "SystemReadFacts",
    "SystemReadSpecSet",
    "bind_system_read_specs",
    "compile_system_read_facts",
]
