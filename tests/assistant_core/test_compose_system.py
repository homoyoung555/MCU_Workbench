"""Composer breadth-first acceptance — system/analog peripherals (node 5):
CRC / VREFBUF / PWR.

Expected words hand-derived from the SVD field map, pinned EXACT. CRC and DMA
share RCC.AHBENR1, whose reset is 0x20 (SRAMSMEN default-on) — the composer
must preserve that base bit, not zero the register; this locks that behaviour.
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
    return next((r for r in result.rows if r.type == "W" and r.addr == addr),
                None)


# ---- CRC: clock enable (preserving SRAMSMEN reset) + reset the unit --------

def test_crc_enable_reset(composer):
    r = composer.compile(ComposeRequest(name="crc", directives=[
        Directive(kind="clk_enable", periph="CRC"),
        Directive(kind="enable_bit", peri="CRC", reg="CR", field="RESET",
                  note="reset CRC"),
    ]))
    assert _w(r, 0x40021070).data == 0x00010020      # AHBENR1: CRCEN | SRAMSMEN
    assert _w(r, 0x40023008).data == 0x00000001      # CR.RESET


# ---- VREFBUF: enable buffer + select reference voltage ---------------------

def test_vrefbuf_enable(composer):
    r = composer.compile(ComposeRequest(name="vref", directives=[
        Directive(kind="clk_enable", periph="VREFBUF"),
        Directive(kind="enable_bit", peri="VREFBUF", reg="CR",
                  field="VREFBUFEN"),
        Directive(kind="field_value", peri="VREFBUF", reg="CR",
                  field="VREFBUFSEL", value=1, note="voltage scale 1"),
    ]))
    assert _w(r, 0x4002108C).data == 0x00000100      # APBENR4.VREFBUFEN bit8
    assert _w(r, 0x40012000).data == 0x00000003      # CR: EN | SEL=1<<1


# ---- PWR: backup-domain unlock (CR1, reset 0x02000000) + PVD (CR2) ---------

def test_pwr_dbp_and_pvd(composer):
    r = composer.compile(ComposeRequest(name="pwr", directives=[
        Directive(kind="clk_enable", periph="PWR"),
        Directive(kind="enable_bit", peri="PWR", reg="CR1", field="DBP",
                  note="unlock backup domain"),
        Directive(kind="enable_bit", peri="PWR", reg="CR2", field="PVDE"),
        Directive(kind="field_value", peri="PWR", reg="CR2", field="PVDT",
                  value=4, note="threshold level 4"),
    ]))
    assert _w(r, 0x4002108C).data == 0x00000200      # APBENR4.PWREN bit9
    assert _w(r, 0x40007000).data == 0x02000100      # CR1: reset | DBP(bit8)
    assert _w(r, 0x40007004).data == 0x00000009      # CR2: PVDE | PVDT=4<<1


# ---- SYSCFG: memory remap + I2C1 fast-mode-plus ----------------------------

def test_syscfg_cfgr1(composer):
    """Previously emitted unchecked output; V1 must refuse the known missing semantics."""
    with pytest.raises(ValueError, match='UNKNOWN'):
        composer.compile(ComposeRequest(name="syscfg", directives=[
                Directive(kind="clk_enable", periph="SYSCFG"),
                Directive(kind="field_value", peri="SYSCFG", reg="CFGR1",
                          field="MEM_MODE", value=1, note="remap"),
                Directive(kind="enable_bit", peri="SYSCFG", reg="CFGR1",
                          field="I2C1_FMP", note="I2C1 fast-mode+"),
            ]))


# ---- RTC (F1-style): config-mode enter -> prescaler -> exit -----------------
# CRL is written twice (CNF=1 enter, CNF=0 exit), preserving RTOFF (reset bit5);
# the two writes must stay separate and ordered around the PRLL write.

def test_rtc_config_window(composer):
    """Previously emitted unchecked output; V1 must refuse the known missing semantics."""
    with pytest.raises(ValueError, match='raw RTC.CRL access'):
        composer.compile(ComposeRequest(name="rtc", directives=[
                Directive(kind="write_reg", peri="RTC", reg="CRL", value=0x30,
                          note="enter config (CNF=1, keep RTOFF)"),
                Directive(kind="field_value", peri="RTC", reg="PRLL", field="PRL",
                          value=0x7FFF, note="prescaler low (1 Hz from 32768)"),
                Directive(kind="write_reg", peri="RTC", reg="CRL", value=0x20,
                          note="exit config (CNF=0)"),
            ]))
