"""Composer vertical-slice acceptance — MCO_PA4_HSI_8M.

Pins the deterministic compile: target-function values exact, ordering rule
(GPIO MODER last) honored, every row sourced. Skips when KB products absent.
"""
from __future__ import annotations

import pytest

from swd_authoring import Composer, ComposeRequest, Directive
from swd_authoring.composer import PHASE_GPIO_MODE
from swd_authoring.encoding import CACHE_ROOT

CHIP = "py32f420"

pytestmark = pytest.mark.skipif(
    not (CACHE_ROOT / CHIP / "fieldmap.json").exists(),
    reason="encoding_v2 products not built (run run_all first)",
)


def _req() -> ComposeRequest:
    return ComposeRequest(name="MCO_PA4_HSI_8M", directives=[
        Directive(kind="check_ready", peri="RCC", reg="CR", field="HSIRDY"),
        Directive(kind="field_value", peri="RCC", reg="CFGR1",
                  field="MCO2SEL", value=0b0010),
        Directive(kind="field_value", peri="RCC", reg="CFGR1",
                  field="MCO2PRE", value=0b1110),
        Directive(kind="clk_enable", periph="GPIOA"),
        Directive(kind="pin_config", pin="PA4", func="MCO2"),
    ])


@pytest.fixture(scope="module")
def result():
    return Composer(CHIP).compile(_req())


def _w(result, addr):
    return next((r for r in result.rows if r.type == "W" and r.addr == addr),
                None)


def test_cfgr1_mco2_hsi_div128(result):
    # 0x02000000 (MCO2SEL=HSI) | 0xE0000000 (MCO2PRE=/128)
    assert _w(result, 0x40021014).data == 0xE2000000


def test_gpioa_clock_enable(result):
    assert _w(result, 0x40021074).data == 0x00000001     # AHBENR2.GPIOAEN


def test_afrl_af0_mco2(result):
    assert _w(result, 0x40024020).data == 0x00000000     # AFSEL4 = AF0 = MCO2


def test_moder_pa4_af_preserves_swd(result):
    w = _w(result, 0x40024000)
    assert (w.data >> 8) & 0b11 == 0b10                  # MODE4 = AF
    assert (w.data >> 26) & 0b11 == 0b10                 # PA13 (SWDIO) AF kept
    assert (w.data >> 28) & 0b11 == 0b10                 # PA14 (SWCLK) AF kept


def test_otyper_push_pull(result):
    assert _w(result, 0x40024004).data == 0x00000000


def test_ospeedr_pa4_very_high(result):
    assert (_w(result, 0x40024008).data >> 8) & 0b11 == 0b11   # OSPEED4 = very high


def test_pupdr_pa4_nopull_preserves_swd(result):
    # composer bases the word on the L0 reset, so the SWD pin pulls survive —
    # the corpus reference blunt-writes 0x0 and clears them. Lock the safe form.
    w = _w(result, 0x4002400C)
    assert (w.data >> 8) & 0b11 == 0b00                  # PUPD4 = no pull
    assert (w.data >> 26) & 0b11 == 0b01                 # PA13 (SWDIO) pull-up kept
    assert (w.data >> 28) & 0b11 == 0b10                 # PA14 (SWCLK) pull-down kept


def test_check_ready_hsirdy(result):
    rows = [r for r in result.rows if r.type == "C_H" and r.addr == 0x40021000]
    assert rows and rows[0].data == 0x400                # HSIRDY @ bit10


def test_moder_is_last_write(result):
    writes = [r for r in result.rows if r.type == "W"]
    assert writes[-1].addr == 0x40024000                # GPIO MODE rule
    assert writes[-1].phase == PHASE_GPIO_MODE


def test_clock_enable_before_gpio(result):
    writes = [r for r in result.rows if r.type == "W"]
    addrs = [r.addr for r in writes]
    assert addrs.index(0x40021074) < addrs.index(0x40024000)


def test_every_row_is_sourced(result):
    for r in result.rows:
        assert r.sources, f"row {r.addr_hex} has no provenance"


def test_afrl_doc_defect_surfaced(result):
    assert any("AFRL" in w and "doc defect" in w for w in result.warnings)
