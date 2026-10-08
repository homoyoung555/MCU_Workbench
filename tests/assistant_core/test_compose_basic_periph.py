"""Composer breadth-first acceptance — register-bag peripherals (node 1).

IWDG / WWDG / EXTI: simple peripherals with no clock-tree ordering. Every
expected word is hand-derived from the SVD field map (the human oracle the
project uses in lieu of silicon) and pinned here as EXACT on the functional
bits. Skips when the encoding_v2 KB products are absent.

Surfaces and locks the first engine gap this node exposed: command/key
registers (IWDG.KR) need a *sequence* of distinct writes to one address, which
field aggregation would collapse — handled by the new `write_reg` directive.
"""
from __future__ import annotations

import pytest

from swd_authoring import Composer, ComposeRequest, Directive
from swd_authoring.encoding import CACHE_ROOT

CHIP = "py32f420"

pytestmark = pytest.mark.skipif(
    not (CACHE_ROOT / CHIP / "fieldmap.json").exists(),
    reason="encoding_v2 products not built (run build first)",
)


@pytest.fixture(scope="module")
def composer():
    return Composer(CHIP)


def _w(result, addr):
    """First W row at addr (single-write registers)."""
    return next((r for r in result.rows if r.type == "W" and r.addr == addr),
                None)


def _writes(result, addr):
    """All W rows at addr, in emitted order (sequenced key registers)."""
    return [r for r in result.rows if r.type == "W" and r.addr == addr]


# ---- IWDG: classic unlock -> prescale -> reload -> start -> feed ------------
# KR takes a *sequence* of distinct writes to one address; PR/RLR are fields.

def test_iwdg_bringup_sequence(composer):
    r = composer.compile(ComposeRequest(name="iwdg", directives=[
        Directive(kind="write_reg", peri="IWDG", reg="KR", value=0x5555,
                  note="unlock PR/RLR"),
        Directive(kind="field_value", peri="IWDG", reg="PR", field="PR",
                  value=6, note="prescaler /256"),
        Directive(kind="field_value", peri="IWDG", reg="RLR", field="RL",
                  value=0xFFF, note="reload max"),
        Directive(kind="write_reg", peri="IWDG", reg="KR", value=0xCCCC,
                  note="start IWDG"),
        Directive(kind="write_reg", peri="IWDG", reg="KR", value=0xAAAA,
                  note="feed dog"),
    ]))
    assert not r.warnings
    # KR must appear three times, in order, with the standard keys —
    # aggregation must NOT collapse them into one word.
    kr = _writes(r, 0x40003000)
    assert [w.data for w in kr] == [0x5555, 0xCCCC, 0xAAAA]
    assert _w(r, 0x40003004).data == 0x00000006     # PR = /256
    assert _w(r, 0x40003008).data == 0x00000FFF     # RLR = 0xFFF (12-bit max)
    # unlock precedes the field writes it gates
    seq = [(w.type, w.addr, w.data) for w in r.rows]
    assert seq.index(("W", 0x40003000, 0x5555)) < seq.index(("W", 0x40003004, 6))


# ---- WWDG: clock enable -> window/timebase (CFR) -> counter/activate (CR) ---
# CR/CFR reset to 0x3F; the field merges must layer onto that base.

def test_wwdg_window_config(composer):
    r = composer.compile(ComposeRequest(name="wwdg", directives=[
        Directive(kind="clk_enable", periph="WWDG"),
        Directive(kind="field_value", peri="WWDG", reg="CFR", field="WDGTB",
                  value=3, note="timebase /8"),
        Directive(kind="field_value", peri="WWDG", reg="CFR", field="W",
                  value=0x50, note="window"),
        Directive(kind="field_value", peri="WWDG", reg="CR", field="T",
                  value=0x7F, note="counter"),
        Directive(kind="enable_bit", peri="WWDG", reg="CR", field="WDGA",
                  note="activate"),
    ]))
    assert _w(r, 0x40021084).data == 0x80000000     # APBENR2.WWDGEN bit31
    assert _w(r, 0x40002C04).data == 0x000001D0      # CFR: W=0x50 | WDGTB=3<<7
    assert _w(r, 0x40002C00).data == 0x000000FF      # CR: T=0x7F | WDGA<<7
    # clock enable is ordered before the functional registers
    addrs = [x.addr for x in r.rows if x.type == "W"]
    assert addrs.index(0x40021084) < addrs.index(0x40002C00)


# ---- EXTI: line 0 edge trigger. No clock gate (EXTI is never RCC-gated). ----
# IMR low bits are a documented reset gap -> base assumed 0, warning surfaces.

def test_exti_line0_rising(composer):
    r = composer.compile(ComposeRequest(name="exti", directives=[
        Directive(kind="enable_bit", peri="EXTI", reg="IMR", field="IMR0",
                  note="unmask line0"),
        Directive(kind="enable_bit", peri="EXTI", reg="RTSR", field="RTSR0",
                  note="rising line0"),
    ]))
    # IMR functional bit (line0 unmasked) layered on the documented reset
    # (bits 22-25 high); RTSR rising on line0.
    assert _w(r, 0x40010400).data == 0x03C00001      # IMR0 | reset 0x03C00000
    assert _w(r, 0x40010408).data == 0x00000001      # RTSR0 rising
    # IMR low-bit reset gap is a doc defect — must surface, not be silent
    assert any("EXTI.IMR" in w and "doc defect" in w for w in r.warnings)


def test_exti_line0_falling(composer):
    r = composer.compile(ComposeRequest(name="exti_f", directives=[
        Directive(kind="enable_bit", peri="EXTI", reg="IMR", field="IMR0"),
        Directive(kind="enable_bit", peri="EXTI", reg="FTSR", field="FTSR0",
                  note="falling line0"),
    ]))
    assert _w(r, 0x40010400).data == 0x03C00001      # IMR0 unmasked
    assert _w(r, 0x4001040C).data == 0x00000001      # FTSR0 falling
