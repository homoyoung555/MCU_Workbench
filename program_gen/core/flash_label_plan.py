"""Compile the canonical Flash Pattern/Label contract and generation plan."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re

from program_gen.core.addr_map import AddrMapCatalog
from program_gen.core.flash_compare_plan import FlashCompareFacts, FlashHardwareFacts


class FlashLabelCompileError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FlashLabelRange:
    """Concrete platform labels for one writable range."""

    chroma_start: str
    s100_start: str
    s100_end: str


@dataclass(frozen=True, slots=True)
class FlashLabelSpan:
    semantic_name: str
    msb_index: int
    width: int
    polarity: str
    write: FlashLabelRange
    read: FlashLabelRange


@dataclass(frozen=True, slots=True)
class FlashLabelPageNames:
    page: str
    erase_pattern: str
    program_pattern: str | None
    read_pattern: str | None
    capture_pattern: str | None


@dataclass(frozen=True, slots=True)
class FlashUidVariantNames:
    name: str
    program_pattern: str | None
    read_pattern: str | None
    check_pattern: str | None


@dataclass(frozen=True, slots=True)
class FlashLabelRegisterBinding:
    page: str
    register: str
    spans: tuple[FlashLabelSpan, ...]


@dataclass(frozen=True, slots=True)
class FlashLabelConsumerBinding:
    program_pattern: str
    read_pattern: str
    spans: tuple[FlashLabelSpan, ...]


@dataclass(frozen=True, slots=True)
class FlashLabelContract:
    """Compiler-owned use/definition seam for every concrete name."""

    pages: tuple[FlashLabelPageNames, ...]
    uid_variants: tuple[FlashUidVariantNames, ...]
    registers: tuple[FlashLabelRegisterBinding, ...]

    def uid_variant(self, cp: str) -> FlashUidVariantNames:
        cp_name = str(cp).strip().casefold()
        if not re.fullmatch(r"cp\d+", cp_name):
            raise FlashLabelCompileError(f"FLASH_LABEL.CP_INVALID: {cp!r}")
        variant_name = f"{cp_name}_id"
        try:
            return next(item for item in self.uid_variants if item.name == variant_name)
        except StopIteration as exc:
            raise FlashLabelCompileError(
                f"FLASH_LABEL.UID_VARIANT_MISSING: {variant_name}"
            ) from exc

    def uid_pass_fields(self, cp: str):
        """Identity word locations/labels come from the same producer catalog."""
        name = self.uid_variant(cp).name
        overrides = dict(next(values for variant, values, _, _ in _UID_VARIANT_FACTS if variant == name))
        return tuple(
            (index, spans) for index, spans in _UID_WORD_LABELS
            if index in overrides and spans[0].semantic_name in ("cp12_id", "cp34_id")
        )

    def bind_register(self, page: str, register: str, cp: str) -> FlashLabelConsumerBinding:
        page_key = str(page).strip().casefold()
        register_key = str(register).strip().casefold()
        try:
            binding = next(
                item for item in self.registers
                if item.page.casefold() == page_key
                and item.register.casefold() == register_key
            )
        except StopIteration as exc:
            raise FlashLabelCompileError(
                f"FLASH_LABEL.BINDING_MISSING: {page}/{register}"
            ) from exc
        if page_key == "uid":
            names = self.uid_variant(cp)
            return FlashLabelConsumerBinding(
                names.program_pattern, names.read_pattern, binding.spans
            )
        try:
            names = next(item for item in self.pages if item.page.casefold() == page_key)
        except StopIteration as exc:
            raise FlashLabelCompileError(f"FLASH_LABEL.PAGE_MISSING: {page}") from exc
        if names.program_pattern is None or names.read_pattern is None:
            raise FlashLabelCompileError(
                f"FLASH_LABEL.PATTERN_MISSING: {page} has no program/read pair"
            )
        return FlashLabelConsumerBinding(
            names.program_pattern, names.read_pattern, binding.spans
        )


@dataclass(frozen=True, slots=True)
class FlashLabelWordPlan:
    value: int
    data_type: str
    labels: tuple[FlashLabelSpan, ...] = ()


@dataclass(frozen=True, slots=True)
class FlashLabelPagePlan:
    name: str
    ra: int
    words: tuple[FlashLabelWordPlan, ...]
    names: FlashLabelPageNames

    @property
    def has_labels(self) -> bool:
        return any(word.labels for word in self.words)


@dataclass(frozen=True, slots=True)
class FlashUidVariant:
    names: FlashUidVariantNames
    word_overrides: tuple[tuple[int, int], ...]
    check_mask: int | None = None
    identity_labels: tuple[tuple[int, tuple[FlashLabelSpan, ...]], ...] = ()

    @property
    def name(self) -> str:
        return self.names.name


@dataclass(frozen=True, slots=True)
class FlashLabelGenerationPlan:
    product_identity: str
    facts: FlashCompareFacts
    contract: FlashLabelContract
    pages: tuple[FlashLabelPagePlan, ...]
    uid_variants: tuple[FlashUidVariant, ...]
    uid_field_layout: tuple[tuple[int, tuple[FlashLabelSpan, ...]], ...] = ()

    @property
    def identity(self) -> str:
        def canonical(value):
            if isinstance(value, Enum):
                return value.value
            if hasattr(value, "__dataclass_fields__"):
                return {
                    name: canonical(getattr(value, name))
                    for name in value.__dataclass_fields__
                }
            if isinstance(value, tuple):
                return [canonical(item) for item in value]
            return value

        raw = json.dumps(canonical(self), sort_keys=True, separators=(",", ":")).encode("ascii")
        return hashlib.sha256(raw).hexdigest().upper()


def _range(base: str) -> FlashLabelRange:
    return FlashLabelRange(base, f"{base}_st", f"{base}_sp")


def _span(
    semantic_name: str,
    msb_index: int,
    width: int,
    polarity: str = "",
    *,
    write_name: str | None = None,
    read_name: str | None = None,
) -> FlashLabelSpan:
    polarity_suffix = f"_{polarity}" if polarity else ""
    write_base = f"{write_name or semantic_name + '_w'}{polarity_suffix}"
    read_base = f"{read_name or semantic_name + '_r'}{polarity_suffix}"
    return FlashLabelSpan(
        semantic_name, msb_index, width, polarity,
        _range(write_base), _range(read_base),
    )


_UID_PASS_LABELS = ((5, (_span(
    "cp12_id", 0, 32, write_name="cp12_id_w", read_name="cp12_id_r",
),)),)


_UID_VARIANT_FACTS = (
    ("cp1_id", ((5, 0x65FFFFFF),), 0xFF000000, _UID_PASS_LABELS),
    ("cp2_id", ((5, 0x65BA78FF),), 0xFFFFFF00, _UID_PASS_LABELS),
    (
        "cp3_id",
        ((3, 0xFFFFFF78), (5, 0x65BA78BA), (6, 0x9AFFFFFF)),
        None,
        _UID_PASS_LABELS + (
            (0, (_span("lot_number", 0, 32, write_name="lot_number_w0", read_name="lot_number_r0"),)),
            (1, (
                _span("lot_number", 0, 24, write_name="lot_number_w1", read_name="lot_number_r1"),
                _span("slot_number", 24, 8),
            )),
            (2, (
                _span("xy_coor", 0, 8), _span("x_coor", 8, 8),
                _span("y_coor", 16, 8), _span("year_month", 24, 8),
            )),
            (3, (
                _span("testing_house_id", 0, 8), _span("cp_ver_no", 8, 8),
                _span("crc_8", 16, 8), _span("f_pass_id", 24, 8),
            )),
            (4, (_span("cp1_ver", 0, 8), _span("cp2_ver", 8, 8))),
            (6, (_span("cp34_id", 0, 32),)),
            (15, (_span("project", 0, 16, "n"), _span("project", 16, 16, "p"))),
        ),
    ),
    ("cp1_bake_id", ((5, 0x65BAFFFF),), 0xFFFF0000, _UID_PASS_LABELS),
    ("cp2_bake_id", ((5, 0x65BA78BA),), 0xFFFFFFFF, _UID_PASS_LABELS),
)

# Fixed UID protocol: logical subfields above, physical writable words below.
_UID_WORD_LABELS = tuple((index, (_span(name, 0, 32),)) for index, name in (
    (0, "lot0"), (1, "lot1"), (2, "uid_xy"), (3, "uid_info"),
    (4, "cp_ver"), (5, "cp12_id"), (6, "cp34_id"), (15, "project"),
))


def compile_flash_label_contract(catalog: AddrMapCatalog) -> FlashLabelContract:
    """Compile every concrete Pattern/Label name once, without hardware data."""
    if not isinstance(catalog, AddrMapCatalog):
        raise TypeError("catalog must be AddrMapCatalog")
    declared_pages = tuple(dict.fromkeys(
        page.name for page in catalog.storage_pages
    )) + tuple(
        page for page in dict.fromkeys(register.page for register in catalog.registers)
        if page.casefold() not in {
            item.name.casefold() for item in catalog.storage_pages
        }
    )
    page_names = tuple(
        FlashLabelPageNames(
            page,
            f"fbist_page_erase_{page}",
            None if page.casefold() == "uid" else f"fbist_page_prog_{page}",
            None if page.casefold() == "uid" else f"fbist_page_read_{page}",
            f"{page}_capture" if any(
                register.page.casefold() == page.casefold()
                for register in catalog.registers
            ) else None,
        )
        for page in declared_pages
    )
    uid_names = tuple(
        FlashUidVariantNames(
            name,
            None if name.endswith("_bake_id") else f"fbist_page_prog_{name}",
            None if name.endswith("_bake_id") else f"fbist_page_read_{name}",
            f"fbist_page_check_{name}" if mask is not None else None,
        )
        for name, _overrides, mask, _labels in _UID_VARIANT_FACTS
    )
    registers = tuple(
        FlashLabelRegisterBinding(
            register.page, register.register, _register_labels(register)
        )
        for register in catalog.registers
    )
    contract = FlashLabelContract(page_names, uid_names, registers)
    _validate_contract(contract)
    return contract


def compile_flash_label_plan(
    catalog: AddrMapCatalog,
    facts: FlashCompareFacts,
    *,
    contract: FlashLabelContract | None = None,
) -> FlashLabelGenerationPlan:
    """Compile once upstream; renderers consume no workbook or global state."""
    if not isinstance(catalog, AddrMapCatalog):
        raise TypeError("catalog must be AddrMapCatalog")
    if not isinstance(facts, FlashCompareFacts):
        raise TypeError("facts must be FlashCompareFacts")
    if not isinstance(facts.hardware, FlashHardwareFacts):
        raise FlashLabelCompileError("Flash Label plan requires compiled hardware facts")
    expected_words = facts.page_bytes // 4
    if facts.page_bytes % 4:
        raise FlashLabelCompileError("page_bytes must be divisible by four")
    if catalog.incomplete_storage_pages:
        raise FlashLabelCompileError(
            "ADDR_MAP incomplete SM Address mapping for pages: "
            + ", ".join(catalog.incomplete_storage_pages)
        )
    if not catalog.storage_pages:
        raise FlashLabelCompileError("ADDR_MAP does not retain complete page images")
    contract = contract or compile_flash_label_contract(catalog)
    register_by_position = {
        (register.page.casefold(), register.page_row_index): register
        for register in catalog.registers
    }
    names_by_page = {item.page.casefold(): item for item in contract.pages}
    pages = []
    for page in catalog.storage_pages:
        if len(page.words) != expected_words:
            raise FlashLabelCompileError(
                f"page {page.name} contains {len(page.words)} words; expected {expected_words}"
            )
        words = tuple(
            FlashLabelWordPlan(
                word.default_storage_word,
                word.data_type,
                _register_labels(register_by_position[(page.name.casefold(), word.page_row_index)])
                if (page.name.casefold(), word.page_row_index) in register_by_position else (),
            )
            for word in page.words
        )
        pages.append(FlashLabelPagePlan(
            page.name, page.ra, words, names_by_page[page.name.casefold()]
        ))
    if not any(page.name.casefold() == "uid" for page in pages):
        raise FlashLabelCompileError("ADDR_MAP does not contain uid page")
    uid_names = {item.name: item for item in contract.uid_variants}
    variants = tuple(FlashUidVariant(uid_names[name], overrides, mask, _UID_WORD_LABELS)
                     for name, overrides, mask, _ in _UID_VARIANT_FACTS)
    layout = {}
    for _, _, _, fields in _UID_VARIANT_FACTS:
        for index, spans in fields:
            for span in spans:
                if span not in layout.setdefault(index, []):
                    layout[index].append(span)
    return FlashLabelGenerationPlan(
        facts.product_identity, facts, contract, tuple(pages), variants,
        tuple((index, tuple(spans)) for index, spans in sorted(layout.items())),
    )



def _register_labels(register) -> tuple[FlashLabelSpan, ...]:
    base = _label_base(register.register)
    if register.complement_half is None:
        start = 0 if register.real_half == "HIGH" else 16
        return (_span(base, start, 16),)
    high_polarity = "p" if register.real_half == "HIGH" else "n"
    low_polarity = "p" if register.real_half == "LOW" else "n"
    return (
        _span(base, 0, 16, high_polarity),
        _span(base, 16, 16, low_polarity),
    )


def _validate_contract(contract: FlashLabelContract) -> None:
    patterns = []
    for page in contract.pages:
        patterns.extend(filter(None, (
            page.erase_pattern, page.program_pattern, page.read_pattern, page.capture_pattern,
        )))
    for variant in contract.uid_variants:
        patterns.extend(filter(None, (
            variant.program_pattern, variant.read_pattern, variant.check_pattern,
        )))
    if len(patterns) != len({name.casefold() for name in patterns}):
        raise FlashLabelCompileError("FLASH_LABEL.PATTERN_NAME_CONFLICT")
    for page in {binding.page.casefold() for binding in contract.registers}:
        spans = tuple(
            span
            for binding in contract.registers
            if binding.page.casefold() == page
            for span in binding.spans
        )
        namespaces = (
            tuple(span.write.chroma_start for span in spans),
            tuple(span.read.chroma_start for span in spans),
            tuple(name for span in spans for name in (
                span.write.s100_start, span.write.s100_end,
            )),
            tuple(name for span in spans for name in (
                span.read.s100_start, span.read.s100_end,
            )),
        )
        if any(
            len(names) != len({name.casefold() for name in names})
            for names in namespaces
        ):
            raise FlashLabelCompileError(
                f"FLASH_LABEL.LABEL_NAME_CONFLICT: {page}"
            )


def _label_base(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_]+", "_", str(value).strip()).strip("_").lower()
    token = re.sub(r"_verify$", "", token)
    if not token or token[0].isdigit():
        raise FlashLabelCompileError(f"invalid Flash label base: {value!r}")
    return token


__all__ = [
    "FlashLabelCompileError", "FlashLabelConsumerBinding", "FlashLabelContract",
    "FlashLabelGenerationPlan", "FlashLabelPageNames", "FlashLabelPagePlan",
    "FlashLabelRange", "FlashLabelRegisterBinding", "FlashLabelSpan",
    "FlashUidVariantNames", "FlashLabelWordPlan", "FlashUidVariant",
    "compile_flash_label_contract", "compile_flash_label_plan",
]
