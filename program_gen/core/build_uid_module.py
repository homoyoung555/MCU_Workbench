"""Compile BUILDUID values and established platform policies once upstream."""

from dataclasses import dataclass
import re

from program_gen.core.flash_label_plan import FlashLabelSpan


@dataclass(frozen=True, slots=True)
class BuildUidOutputField:
    semantic_name: str
    symbol: str
    source: str
    width: int
    index: int | None
    word_index: int
    spans: tuple[FlashLabelSpan, ...]


@dataclass(frozen=True, slots=True)
class BuildUidWord:
    word_index: int
    symbol: str
    default_value: int
    label: FlashLabelSpan
    value_type: str = "uint32_t"


@dataclass(frozen=True, slots=True)
class BuildUidPlatformPolicy:
    platform: str
    field_expressions: tuple[tuple[str, str], ...]
    crc_inputs: tuple[str, ...]
    crc_scope: str
    refresh_coordinates: bool
    parse_wafer_slot: bool
    manual_wafer_input: bool
    coordinate_limits: tuple[int, int] = (-1200, 5000)
    word_expressions: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class BuildUidModulePlan:
    cp: str
    fields: tuple[BuildUidOutputField, ...]
    constants: tuple[tuple[str, int], ...]
    policies: tuple[BuildUidPlatformPolicy, ...]
    crc_table: tuple[int, ...]
    words: tuple[BuildUidWord, ...]

    def policy_for(self, platform: str) -> BuildUidPlatformPolicy:
        return next(policy for policy in self.policies if policy.platform == platform)


def compile_build_uid_module_plan(*, cp, version_frame, flash_label_plan):
    """Accept already-read compiler inputs; never open a workbook or old output."""
    rows = version_frame[version_frame["CP num"].astype(str).str.strip().str.casefold() == str(cp).strip().casefold()]
    if len(rows) != 1:
        raise ValueError(f"BUILDUID.VERSION: expected one VERSION row for {cp}")
    row = rows.iloc[0]
    # Manufacturing fields belong to the shared physical UID layout, not a CP.
    layout = dict(flash_label_plan.uid_field_layout)
    fields = []
    lot_index = 0
    source_names = {
        "lot_number": "LOT_BYTES", "slot_number": "WAFER_SLOT",
        "xy_coor": "XY_RAW_HIGH", "x_coor": "X_LOW", "y_coor": "Y_LOW",
        "year_month": "DATE_YM", "testing_house_id": "FAB_ID",
        "cp_ver_no": "CP_SPEC", "crc_8": "CRC8", "project": "PROJECT_WORD",
    }
    for word_index, spans in sorted(layout.items()):
        names = tuple(dict.fromkeys(span.semantic_name for span in spans))
        for name in names:
            if name in ("cp12_id", "cp34_id", "f_pass_id"):
                continue  # PASS ID belongs to COMMIT, never BUILDUID.
            matching = tuple(span for span in spans if span.semantic_name == name)
            width = matching[0].width
            if any(span.width != width for span in matching):
                raise ValueError(f"BUILDUID.FIELD_WIDTH: {name}")
            version_match = re.fullmatch(r"cp(\d+)_ver", name)
            source = "CP_VERSION" if version_match else source_names.get(name)
            if source is None:
                raise ValueError(f"BUILDUID.FIELD_SOURCE: {name}")
            index = int(version_match[1]) if version_match else (lot_index if name == "lot_number" else None)
            symbol = f"BUILD_UID_{str(cp).upper()}_{name.upper()}"
            if name == "lot_number":
                if width % 8:
                    raise ValueError("BUILDUID.LOT_WIDTH: expected complete bytes")
                symbol += f"_{lot_index}"
                lot_index += width // 8
            fields.append(BuildUidOutputField(name, symbol, source, width, index, word_index, matching))
    if not fields:
        raise ValueError(f"BUILDUID.LAYOUT: no manufacturing fields for {cp}")
    if lot_index != 7 or not any(field.source == "CRC8" for field in fields):
        raise ValueError("BUILDUID.LAYOUT: requires seven Lot bytes and CRC field")
    house = str(row["Program Name"]).split("_")[0]
    if len(house) != 1 or not house.isascii():
        raise ValueError("BUILDUID.TESTING_HOUSE: program prefix must be one ASCII character")
    constants = [
        ("CP_VERNO", _integer(row["CP spec"])),
        ("PROJECT_NAME", _integer(row["project name"])),
        ("PROJECT_VERSION", _integer(row["project ver"])),
        ("TESTING_HOUSE_ID", ord(house)),
    ]
    for field in fields:
        if field.source == "CP_VERSION":
            key = {1: "CP ver high", 2: "CP ver low"}.get(field.index, f"CP{field.index} version")
            if key not in row:
                raise ValueError(f"BUILDUID.VERSION: missing declared field {key}")
            constants.append((f"CP{field.index}_VERSION", _integer(row[key])))
    for name, value in constants:
        if not 0 <= value <= 0xFF:
            raise ValueError(f"BUILDUID.CONSTANT: {name} must be one unsigned byte")
    variant = next((v for v in flash_label_plan.uid_variants
                    if v.name.casefold() == str(cp).casefold() + "_id"), None)
    if variant is None:
        raise ValueError(f"BUILDUID.UID_VARIANT: missing {cp}")
    page = next(p for p in flash_label_plan.pages if p.name.casefold() == "uid")
    overrides = dict(variant.word_overrides)
    words = tuple(BuildUidWord(index, f"BUILD_UID_{str(cp).upper()}_{spans[0].semantic_name.upper()}",
                              overrides.get(index, page.words[index].value), spans[0])
                  for index, spans in variant.identity_labels)
    policies = tuple(_policy(platform, tuple(fields), words) for platform in ("chroma", "s100"))
    table = []
    for value in range(256):
        for _ in range(8):
            value = ((value << 1) ^ 0x07) & 0xFF if value & 0x80 else (value << 1) & 0xFF
        table.append(value)
    return BuildUidModulePlan(str(cp), tuple(fields), tuple(constants), policies, tuple(table), words)


def _integer(value):
    text = str(value).strip()
    try:
        return int(text, 16) if text.lower().startswith("0x") else int(text, 10)
    except ValueError:
        try:
            number = float(text)
        except ValueError as error:
            raise ValueError(f"BUILDUID.CONSTANT: expected integer, got {value!r}") from error
        if not number.is_integer():
            raise ValueError(f"BUILDUID.CONSTANT: expected integer, got {value!r}")
        return int(number)


def _policy(platform, fields, words):
    chroma = platform == "chroma"
    lot = "LOT_ID" if chroma else "Sys_gszProberWaferID"
    site = "SOCKET" if chroma else "T_SOCKET"
    expressions = {
        "WAFER_SLOT": "WAFER_SLOT",
        "XY_RAW_HIGH": f"((Y_CO[{site}]>>4)&0xF0)|((X_CO[{site}]>>8)&0x0F)",
        "X_LOW": f"X_CO[{site}]&0xFF", "Y_LOW": f"Y_CO[{site}]&0xFF",
        "DATE_YM": "((year%10)<<4)+month", "FAB_ID": "TESTING_HOUSE_ID",
        "CP_SPEC": "CP_VERNO", "PROJECT_WORD": "PROJECT_NAME*256+PROJECT_VERSION",
    }
    output = []
    for field in fields:
        if field.source == "CRC8":
            continue
        if field.source == "LOT_BYTES":
            count = field.width // 8
            expression = "|".join(
                f"((uint32_t)(unsigned char){lot}[{field.index+i}]<<{8*(count-i-1)})"
                for i in range(count)
            )
        elif field.source == "CP_VERSION":
            expression = f"CP{field.index}_VERSION"
        else:
            expression = expressions[field.source]
        output.append((field.symbol, expression))
    crc = tuple(f"{lot}[{i}]" for i in range(7)) + (
        "WAFER_SLOT" if chroma else "wafer_num",
        f"((abs(Y_CO[{site}])>>8)&0xF)*16+((abs(X_CO[{site}])>>8)&0xF)",
        f"X_CO[{site}]&0xFF", f"Y_CO[{site}]&0xFF",
        "((year%10)<<4)+month", "TESTING_HOUSE_ID", "CP_VERNO",
    )
    sources = dict(output)
    sources.update((f.symbol, "CRC8") for f in fields if f.source == "CRC8")
    packed = []
    for word in words:
        occupied = 0
        terms = []
        for field in fields:
            if field.word_index != word.word_index:
                continue
            for span in field.spans:
                mask = (1 << span.width) - 1
                shift = 32 - span.msb_index - span.width
                if shift < 0 or occupied & (mask << shift):
                    raise ValueError(f"BUILDUID.WORD_LAYOUT: overlapping/out-of-range {field.semantic_name}")
                occupied |= mask << shift
                source = f"~({sources[field.symbol]})" if span.polarity == "n" else sources[field.symbol]
                terms.append(f"(((uint32_t)({source})&0x{mask:X}U)<<{shift})")
        base = word.default_value & (~occupied & 0xFFFFFFFF)
        packed.append((word.symbol, "|".join([f"0x{base:08X}U"] + terms)))
    return BuildUidPlatformPolicy(platform, tuple(output), crc,
                                  "PER_SITE" if chroma else "LAST_SITE_BROADCAST",
                                  chroma, not chroma, chroma, word_expressions=tuple(packed))
