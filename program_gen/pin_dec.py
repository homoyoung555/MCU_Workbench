"""Standalone Chroma and S100 pin-map generation from compiled facts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from program_gen.platform_program.facts import PinBinding, PinGroupFacts


@dataclass(frozen=True, slots=True)
class PinMapGenerationPlan:
    """Immutable pin topology consumed by both platform adapters."""

    platform: str
    cp: str
    site_count: int
    pins: tuple[PinBinding, ...]
    pin_groups: PinGroupFacts
    kp_channels: tuple[str, ...] = ()


def compile_pin_map_generation_plan(facts) -> PinMapGenerationPlan:
    """Narrow complete-program facts to the standalone pin-map contract."""
    platform = str(facts.platform).strip().casefold()
    pins = tuple(facts.pins)
    site_count = int(facts.site_count)
    if platform not in ("chroma", "s100"):
        raise ValueError(f"PIN_MAP.PLATFORM: {facts.platform!r}")
    if site_count < 1 or not pins:
        raise ValueError("PIN_DEC.PINS.EMPTY")
    if any(len(pin.channels) != site_count for pin in pins):
        raise ValueError("PIN_DEC.PIN.SITE_COUNT_MISMATCH")
    pin_numbers = tuple(pin.pin_no for pin in pins)
    if any(number < 1 for number in pin_numbers) or len(set(pin_numbers)) != len(pin_numbers):
        raise ValueError("PIN_DEC.PIN.NUMBER_INVALID")
    kp_channels = tuple(
        channel.strip() for channel in str(facts.kp_channel or "").split(":")
        if channel.strip()
    )
    if kp_channels and len(kp_channels) != site_count:
        raise ValueError("PIN_DEC.KP.SITE_COUNT_MISMATCH")
    return PinMapGenerationPlan(
        platform=platform,
        cp=str(facts.cp),
        site_count=site_count,
        pins=pins,
        pin_groups=facts.pin_groups,
        kp_channels=kp_channels,
    )


def generate_pin_dec(plan: PinMapGenerationPlan) -> bytes:
    """Render one complete Chroma ``pin.dec`` without writing to disk."""
    if plan.platform != "chroma":
        raise ValueError(f"PIN_DEC.PLATFORM: {plan.platform!r}")
    lines = ["DEC_MODE APAS;", "", f"PIN_LIST(CP_{plan.site_count}S)", "{"]
    lines.append("   // Site = " + ":".join(str(i) for i in range(plan.site_count)))
    lines.append("   // Pin Name     = Tester Channels = Pin No. = Type")
    name_width = max(len(pin.name) for pin in plan.pins)
    channel_width = max(len(":".join(pin.channels)) for pin in plan.pins)
    for pin in plan.pins:
        channel = ":".join(pin.channels)
        if pin.kind == "relay":
            lines.append(
                f"   {pin.name:<{name_width}} = {channel:<{channel_width}} =     = UR;"
            )
        else:
            pin_type = "MLDPS" if pin.kind == "pwr" else "IO"
            lines.append(
                f"   {pin.name:<{name_width}} = {channel:<{channel_width}} = "
                f"{pin.pin_no:>3} = {pin_type};"
            )
    if plan.kp_channels:
        lines.append(f"   KP = {':'.join(plan.kp_channels)} =   = UR;")
    lines.extend(("}", "", "PIN_GROUP", "{", "   // Group Name = Pin Names"))
    # IO_ALLPINS is a CRAFT-reserved group derived from all IO pin types.
    for name, members in (
        ("ODD_pins", plan.pin_groups.odd),
        ("EVEN_pins", plan.pin_groups.even),
        ("Leakage_ODD_pins", plan.pin_groups.leakage_odd),
        ("Leakage_EVEN_pins", plan.pin_groups.leakage_even),
        ("VILVIH_ODD", plan.pin_groups.vih_vil_odd),
        ("VILVIH_EVEN", plan.pin_groups.vih_vil_even),
        ("OPA_INP0_pins", plan.pin_groups.opa_inp0),
        ("OPA_INN_pins", plan.pin_groups.opa_inn0),
        ("OPA_OUT_pins", plan.pin_groups.opa_out),
        *((f"DC{index}_pins", members)
          for index, members in enumerate(plan.pin_groups.dc_groups, start=1)),
    ):
        if members:
            lines.append(f"   {name} = {'+'.join(pin.name for pin in members)};")
    lines.extend(("}", ""))
    return "\r\n".join(lines).encode("ascii")


def generate_s100_prj_resources(plan: PinMapGenerationPlan) -> bytes:
    """Render only S100 pin, relay and pin-group resource definitions."""
    if plan.platform != "s100":
        raise ValueError(f"S100_PIN_RESOURCES.PLATFORM: {plan.platform!r}")
    relay_pins = tuple(pin for pin in plan.pins if pin.kind == "relay")
    name_width = max(len(pin.name) for pin in plan.pins)
    pin_rows = "\r\n".join(
        f"   {pin.name:<{name_width}},{'io' if pin.kind == 'relay' else pin.kind:<4},"
        f"{pin.pin_no:>3},{','.join(pin.channels)};"
        for pin in plan.pins
    )
    relay_rows = "\r\n".join(
        "   " + ",".join(pin.channels) + ";" for pin in relay_pins
    )
    relay_groups = "\r\n".join(
        f'   {pin.name},["{pin.channels[0]}"];' for pin in relay_pins
    )
    pin_groups = "\r\n".join(
        f"   {group_name},[" + ",".join(str(pin.pin_no) for pin in members) + "];"
        for group_name, members in (
            ("IO_ALLPINS", plan.pin_groups.io_all),
            ("ODD_pins", plan.pin_groups.odd),
            ("EVEN_pins", plan.pin_groups.even),
            ("Leakage_ODD_pins", plan.pin_groups.leakage_odd),
            ("Leakage_EVEN_pins", plan.pin_groups.leakage_even),
            ("VILVIH_ODD", plan.pin_groups.vih_vil_odd),
            ("VILVIH_EVEN", plan.pin_groups.vih_vil_even),
            ("OPA_INP0_pins", plan.pin_groups.opa_inp0),
            ("OPA_INN_pins", plan.pin_groups.opa_inn0),
            ("OPA_OUT_pins", plan.pin_groups.opa_out),
            *((f"DC{index}_pins", members)
              for index, members in enumerate(plan.pin_groups.dc_groups, start=1)),
        )
        if members
    )
    return (
        "@@PIN_DEFINE_TABLE\r\n"
        "   // Pin Name        ,Type,No.,Site tester channels;\r\n"
        + pin_rows
        + "\r\n   SYS_SHARE_TRIGPIN,i,64,"
        + ",".join("254" for _ in range(plan.site_count))
        + ";\r\n@@END_PIN_DEFINE_TABLE\r\n\r\n"
        "@@USER_RELAY_TABLE\r\n"
        + relay_rows
        + ("\r\n" if relay_rows else "")
        + "@@END_USER_RELAY_TABLE\r\n\r\n"
        "@@PIN_GROUP_TABLE\r\n"
        "   // Group Name, S100 pin numbers;\r\n"
        + relay_groups
        + ("\r\n" if relay_groups else "")
        + pin_groups
        + "\r\n@@END_PIN_GROUP_TABLE\r\n\r\n"
    ).encode("gbk")


__all__ = [
    "PinMapGenerationPlan",
    "compile_pin_map_generation_plan",
    "generate_pin_dec",
    "generate_s100_prj_resources",
]
