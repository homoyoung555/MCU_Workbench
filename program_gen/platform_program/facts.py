"""Typed electrical, lifecycle and project facts for platform programs."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True, slots=True)
class PinBinding:
    name: str
    kind: str
    pin_no: int
    channels: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PinGroupFacts:
    """The three confirmed platform pin groups, compiled from pin bindings."""

    io_all: tuple[PinBinding, ...]
    odd: tuple[PinBinding, ...]
    even: tuple[PinBinding, ...]
    leakage_odd: tuple[PinBinding, ...] = ()
    leakage_even: tuple[PinBinding, ...] = ()
    dc_groups: tuple[tuple[PinBinding, ...], ...] = ()
    vih_vil_odd: tuple[PinBinding, ...] = ()
    vih_vil_even: tuple[PinBinding, ...] = ()
    opa_inp0: tuple[PinBinding, ...] = ()
    opa_inn0: tuple[PinBinding, ...] = ()
    opa_out: tuple[PinBinding, ...] = ()
    dac_out: tuple[PinBinding, ...] = ()


@dataclass(frozen=True, slots=True)
class PinMapFacts:
    """The complete, pin-only contract shared by standalone pin generators."""

    platform: str
    cp: str
    site_count: int
    pins: tuple[PinBinding, ...]
    pin_groups: PinGroupFacts
    kp_channel: str | None


@dataclass(frozen=True, slots=True)
class PlatformProgramFacts:
    platform: str
    cp: str
    site_count: int
    pins: tuple[PinBinding, ...]
    pin_groups: PinGroupFacts
    io_pins: tuple[str, ...]
    power_pins: tuple[str, ...]
    force_rails: tuple[str, ...]
    relay_pins: tuple[PinBinding, ...]
    clk_pin: str
    swd_pin: str
    nrst_pin: str
    vcc_min: str
    vcc_typ: str
    vcc_max: str
    erase_time_ms: float
    program_time_ms: float
    kp_channel: str | None
    page_bytes: int
    vte_voltage: str | None
    vtp_voltage: str | None
    vpose_target: str | None
    vnege_target: str | None
    vposp_target: str | None
    vnegp_target: str | None
    program_version_token: str


def compile_platform_program_facts(workbook, target) -> PlatformProgramFacts:
    """Compile VERSION and PIN DEC facts once, before any platform rendering."""
    platform = target.platform.casefold()
    version = workbook.dataframe("VERSION")
    rows = version[
        version["CP num"].astype(str).str.strip().str.casefold()
        == target.cp.casefold()
    ]
    if len(rows) != 1:
        raise ValueError(f"STN.VERSION.CP: expected one VERSION row for {target.cp}")
    version_row = rows.iloc[0]
    program_version_token = _program_version_token(
        _text(version_row.get("Program Name")), target.cp
    )
    nrst_physical = _required_version_pin(version_row, "NRST PIN")
    pin_facts = compile_pin_map_facts(workbook, target)
    power_pins = tuple(pin.name for pin in pin_facts.pins if pin.kind == "pwr")
    force_rails = tuple(name for name in power_pins if name.upper() != "VDDD")
    if not force_rails:
        raise ValueError("STN.POWER.RAIL_MISSING: no externally forced power rail")
    io_pins = tuple(pin.name for pin in pin_facts.pins if pin.kind == "io")
    relay_pins = tuple(pin for pin in pin_facts.pins if pin.kind == "relay")
    return PlatformProgramFacts(
        platform=platform,
        cp=target.cp,
        site_count=pin_facts.site_count,
        pins=pin_facts.pins,
        pin_groups=pin_facts.pin_groups,
        io_pins=io_pins,
        power_pins=power_pins,
        force_rails=force_rails,
        relay_pins=relay_pins,
        clk_pin=_required_version_pin(version_row, "CLK PIN"),
        swd_pin=_required_version_pin(version_row, "SWD PIN"),
        nrst_pin=nrst_physical,
        vcc_min=_text(version_row["vcc min"]),
        vcc_typ=_text(version_row["vcc typ"]),
        vcc_max=_text(version_row["vcc max"]),
        erase_time_ms=float(version_row["erase time(ms)"]),
        program_time_ms=float(version_row["program time(ms)"]),
        kp_channel=pin_facts.kp_channel,
        page_bytes=int(float(version_row["page word"])) * 4,
        vte_voltage=_optional_text(version_row["VTE target"]),
        vtp_voltage=_optional_text(version_row["VTP target"]),
        vpose_target=_optional_text(version_row["vpose"]),
        vnege_target=_optional_text(version_row["vnege"]),
        vposp_target=_optional_text(version_row["vposp"]),
        vnegp_target=_optional_text(version_row["vnegp"]),
        program_version_token=program_version_token,
    )


def compile_pin_map_facts(workbook, target) -> PinMapFacts:
    """Compile only the workbook facts needed to render a platform pin map."""
    platform = target.platform.casefold()
    version = workbook.dataframe("VERSION")
    rows = version[
        version["CP num"].astype(str).str.strip().str.casefold()
        == target.cp.casefold()
    ]
    if len(rows) != 1:
        raise ValueError(f"STN.VERSION.CP: expected one VERSION row for {target.cp}")
    version_row = rows.iloc[0]
    pin_frame = _pin_frame_for_target(workbook, target, platform)
    if pin_frame.empty:
        raise ValueError(f"STN.PIN.EMPTY: no {platform}/{target.cp} pin rows")

    nrst_physical = _required_version_pin(version_row, "NRST PIN")
    swd_pin = _required_version_pin(version_row, "SWD PIN")
    clk_pin = _required_version_pin(version_row, "CLK PIN")
    site_values = tuple(int(value) for value in pin_frame["Site"] if _text(value))
    if not site_values:
        raise ValueError("STN.PIN.SITE_MISSING: no Site values")
    site_count = max(site_values)
    kp_channel = _compile_kp_channel(
        workbook, platform, target.cp, site_count, pin_frame
    )
    pins = _compile_pin_bindings(platform, pin_frame, nrst_physical, site_count)
    pin_groups = compile_pin_group_facts(
        platform,
        pins,
        iomux=workbook.dataframe("IOMUX"),
        vih_vil_excluded=(swd_pin, clk_pin, "NRST", "TP"),
    )
    return PinMapFacts(
        platform=platform,
        cp=target.cp,
        site_count=site_count,
        pins=pins,
        pin_groups=pin_groups,
        kp_channel=kp_channel,
    )


def _pin_frame_for_target(workbook, target, platform):
    if target.variant.casefold() == "lab":
        pin_frame = workbook.dataframe("PIN DEC SINGEL")
        return pin_frame[
            pin_frame["TESTER"].astype(str).str.strip().str.casefold() == platform
        ]
    if target.variant.casefold() == "production":
        pin_frame = workbook.dataframe("PIN DEC")
        return pin_frame[
            pin_frame["CP NO"].astype(str).str.strip().str.casefold()
            == target.cp.casefold()
        ]
    raise ValueError(f"STN.TARGET.VARIANT: {target.variant!r}")


def _compile_pin_bindings(
    platform: str, pin_frame, nrst_physical: str, site_count: int
) -> tuple[PinBinding, ...]:
    grouped: dict[tuple[str, str], dict[int, str]] = {}
    names: dict[tuple[str, str], str] = {}
    order: list[tuple[str, str]] = []
    for _, row in pin_frame.iterrows():
        trace = _text(row.get("Trace"))
        raw_pad = _text(row.get("E/C(Pad Name)"))
        if not trace or "GND" in trace.upper() or not raw_pad:
            continue
        name = _pin_name(raw_pad)
        if name == nrst_physical:
            name = "NRST"
        kind = (
            "relay" if _is_relay(row, pin_frame.columns)
            else "pwr" if _is_power(raw_pad, trace)
            else "io"
        )
        key = (kind, name.casefold())
        if key not in grouped:
            grouped[key] = {}
            names[key] = name
            order.append(key)
        site = int(row["Site"])
        previous = grouped[key].get(site)
        if previous is not None and previous.casefold() != trace.casefold():
            raise ValueError(
                f"STN.PIN.SITE_CONFLICT: {name!r} has multiple channels for Site {site}"
            )
        grouped[key][site] = trace

    pins: list[PinBinding] = []
    first_pin_number = 2 if platform == "chroma" else 1
    power_channels: set[tuple[str, ...]] = set()
    for key in order:
        kind, _identity = key
        channel_by_site = grouped[key]
        name = names[key]
        missing_sites = tuple(
            site for site in range(1, site_count + 1)
            if site not in channel_by_site
        )
        if missing_sites:
            raise ValueError(
                f"STN.PIN.SITE_MISSING: {name!r} lacks Site {missing_sites[0]}"
            )
        channels = tuple(
            _channel(channel_by_site[site], platform, kind)
            for site in range(1, site_count + 1)
        )
        if kind == "pwr":
            if channels in power_channels:
                continue
            power_channels.add(channels)
        pins.append(PinBinding(
            name, kind, len(pins) + first_pin_number, channels
        ))

    return tuple(pins)


def _program_version_token(program_name: str, cp: str) -> str:
    tokens = tuple(re.findall(
        r"(?<![A-Za-z0-9])V\d+_\d+(?![A-Za-z0-9])",
        str(program_name),
        re.I,
    ))
    if len(tokens) != 1:
        raise ValueError(
            f"STN.VERSION.PROGRAM_NAME: expected exactly one Vxx_yy token for {cp}"
        )
    return tokens[0].upper()


def _required_version_pin(version_row, column: str) -> str:
    try:
        pin = _pin_name(version_row[column])
    except KeyError as error:
        raise ValueError(f"STN.VERSION.PIN_MISSING: {column}") from error
    if not pin:
        raise ValueError(f"STN.VERSION.PIN_MISSING: {column}")
    return pin


def _has_kp_relay(platform: str, cp: str, site_count: int, pin_frame) -> bool:
    if platform != "chroma" or cp not in ("CP1", "CP2"):
        return False
    if site_count == 1:
        return True
    if cp != "CP1":
        return False
    return any(
        "F0" in _text(trace).upper() or "F1" in _text(trace).upper()
        for trace in pin_frame["Trace"]
    )


def _compile_kp_channel(workbook, platform, cp, site_count, pin_frame):
    if not _has_kp_relay(platform, cp, site_count, pin_frame):
        return None
    if site_count == 1:
        return "2501"

    relay_frame = workbook.dataframe("KP RELAY")
    relay_by_trace = {}
    for suffix in ("F0", "F1"):
        for trace, relay in zip(
            relay_frame[f"{suffix} Channel"],
            relay_frame[f"KP RELAY {suffix}"],
        ):
            trace_text = _text(trace).upper()
            relay_text = _text(relay)
            if not trace_text or not relay_text:
                continue
            previous = relay_by_trace.get(trace_text)
            if previous is not None and previous != relay_text:
                raise ValueError(f"STN.KP_RELAY.CONFLICT: {trace_text!r}")
            relay_by_trace[trace_text] = relay_text

    channels = []
    for site in range(1, site_count + 1):
        traces = {
            match.group(1).upper()
            for value in pin_frame.loc[pin_frame["Site"] == site, "Trace"]
            if (match := re.fullmatch(r"\s*(\d+F[01])\s*", _text(value), re.I))
        }
        if len(traces) != 1:
            raise ValueError(f"STN.KP_RELAY.SITE_TRACE: Site {site}")
        trace = next(iter(traces))
        try:
            channels.append(relay_by_trace[trace])
        except KeyError as error:
            raise ValueError(f"STN.KP_RELAY.MAPPING_MISSING: {trace!r}") from error
    return ":".join(channels)


def compile_pin_group_facts(
    platform: str,
    pins: tuple[PinBinding, ...],
    *,
    iomux=None,
    vih_vil_excluded: tuple[str, ...] = (),
) -> PinGroupFacts:
    """Compile confirmed IO/parity groups once, before platform rendering."""
    io_all = tuple(pin for pin in pins if pin.kind == "io")
    parity_candidates = tuple(
        pin for pin in io_all if pin.name.casefold() != "tp"
    )
    if platform not in ("chroma", "s100"):
        raise ValueError(f"STN.PIN_GROUP.PLATFORM: {platform!r}")
    odd = tuple(pin for pin in parity_candidates if pin.pin_no % 2)
    even = tuple(pin for pin in parity_candidates if not pin.pin_no % 2)
    dc_candidates = tuple(
        pin for pin in io_all
        if pin.name.casefold() not in ("tp", "nrst")
    )
    excluded = {name.casefold() for name in vih_vil_excluded}
    vih_vil_candidates = tuple(
        pin for pin in io_all
        if pin.name.casefold() not in excluded
        and re.fullmatch(r"P[A-F]\d+", pin.name, re.I)
    )
    vih_vil_odd = tuple(
        pin for pin in vih_vil_candidates
        if int(re.search(r"\d+$", pin.name).group()) % 2 == 0
    )
    vih_vil_even = tuple(
        pin for pin in vih_vil_candidates
        if int(re.search(r"\d+$", pin.name).group()) % 2 == 1
    )
    opa_inp0, opa_inn0, opa_out = _opa_groups(iomux, io_all)
    dac_out = _dac_group(iomux, io_all)
    return PinGroupFacts(
        io_all=io_all,
        odd=odd,
        even=even,
        leakage_odd=dc_candidates[1::2],
        leakage_even=dc_candidates[0::2],
        dc_groups=_balanced_groups(dc_candidates, 8),
        vih_vil_odd=vih_vil_odd,
        vih_vil_even=vih_vil_even,
        opa_inp0=opa_inp0,
        opa_inn0=opa_inn0,
        opa_out=opa_out,
        dac_out=dac_out,
    )


def _opa_groups(iomux, io_all):
    if iomux is None or iomux.empty:
        return (), (), ()
    opa_columns = tuple(
        column for column in iomux.columns
        if any(_text(value).upper() == "OPA" for value in iomux[column].iloc[:2])
    )
    if len(opa_columns) != 1:
        return (), (), ()
    roles = {}
    column = opa_columns[0]
    for _, row in iomux.iterrows():
        pin = _normalize_iomux_pin(row.get("pin"))
        if not pin:
            continue
        for label in _text(row.get(column)).split("/"):
            match = re.fullmatch(r"OPA(\d+)_V(INP|INN)(\d+)|OPA(\d+)_VOUT", label, re.I)
            if not match:
                continue
            if match.group(4):
                roles[(int(match.group(4)), "OUT", 0)] = pin
            else:
                roles[(int(match.group(1)), match.group(2).upper(), int(match.group(3)))] = pin
    by_name = {pin.name.casefold(): pin for pin in io_all}
    instances = sorted({key[0] for key in roles})
    usable = tuple(
        instance for instance in instances
        if roles.get((instance, "INP", 0), "").casefold() in by_name
        and roles.get((instance, "OUT", 0), "").casefold() in by_name
    )
    def members(kind):
        return tuple(
            by_name[name.casefold()] for instance in usable
            if (name := roles.get((instance, kind, 0))) and name.casefold() in by_name
        )
    return members("INP"), members("INN"), members("OUT")


def _normalize_iomux_pin(value):
    base = _text(value).split("-", 1)[0]
    match = re.fullmatch(r"(P[A-FY])0*(\d+)", base, re.I)
    return f"{match.group(1).upper()}{match.group(2)}" if match else base


def _dac_group(iomux, io_all):
    if iomux is None or iomux.empty: return ()
    columns = tuple(column for column in iomux.columns if any(_text(value).upper() == "DAC" for value in iomux[column].iloc[:2]))
    if len(columns) != 1: return ()
    by_name = {pin.name.casefold(): pin for pin in io_all}
    names = []
    for _, row in iomux.iterrows():
        if re.fullmatch(r"DAC_OUT\d*", _text(row.get(columns[0])), re.I):
            name = _normalize_iomux_pin(row.get("pin"))
            if name.casefold() in by_name and name.casefold() not in {item.casefold() for item in names}: names.append(name)
    return tuple(by_name[name.casefold()] for name in names)


def _balanced_groups(
    pins: tuple[PinBinding, ...], maximum_size: int
) -> tuple[tuple[PinBinding, ...], ...]:
    if not pins:
        return ()
    count = (len(pins) + maximum_size - 1) // maximum_size
    base, extra = divmod(len(pins), count)
    groups = []
    offset = 0
    for index in range(count):
        size = base + (1 if index < extra else 0)
        groups.append(pins[offset:offset + size])
        offset += size
    return tuple(groups)


def _text(value) -> str:
    if value is None or (isinstance(value, float) and value != value):
        return ""
    return str(value).strip()


def _optional_text(value) -> str | None:
    text = _text(value)
    return None if text in ("", "/") else text


def _pin_name(value) -> str:
    text = _text(value)
    match = re.search(r"(P[A-FY])[\[_<]\s*(\d+)", text, re.I)
    return f"{match.group(1).upper()}{match.group(2)}" if match else text


def _is_power(pad: str, trace: str) -> bool:
    return "DPS" in trace.upper() or (
        "V" in pad.upper() and not re.match(r"^PAD_P", pad, re.I)
    )


def _is_relay(row, columns) -> bool:
    if "X [um]" not in columns or "Y [um]" not in columns:
        return False
    return not _text(row.get("X [um]")) and not _text(row.get("Y [um]"))


def _channel(trace: str, platform: str, kind: str) -> str:
    text = str(trace).split("F", 1)[0].split("*", 1)[0].strip()
    if platform == "s100" and kind == "pwr":
        match = re.search(r"DPS\s*(\d+)(?:-(\d+))?", text, re.I)
        if match:
            number = match.group(2) or match.group(1)
            return f"LOGIC_DPS{number}"
        if text.isdigit():
            return text
        raise ValueError(f"STN.S100.DPS_CHANNEL: {trace!r}")
    return text


__all__ = [
    "PinBinding", "PinGroupFacts", "PinMapFacts", "PlatformProgramFacts",
    "compile_pin_group_facts", "compile_pin_map_facts",
    "compile_platform_program_facts",
]
