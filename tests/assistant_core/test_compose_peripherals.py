"""Composer coverage acceptance — DAC / OPA / PLL targets.

Pins the values dry-run #3 verified against the corpus, plus the PLL ordering
invariant (config before enable before mux). Skips when KB products absent.
"""
from __future__ import annotations

import pytest

from swd_authoring import Composer, ComposeRequest, Directive
from swd_authoring.encoding import CACHE_ROOT

CHIP = "py32f420"

pytestmark = pytest.mark.skipif(
    not (CACHE_ROOT / CHIP / "fieldmap.json").exists(),
    reason="encoding_v2 products not built (run run_all first)",
)


@pytest.fixture(scope="module")
def composer():
    return Composer(CHIP)


def _w(result, addr):
    # config-then-enable 后,使能寄存器会被写两次(配置→使能);取末行=最终值
    ws = [r for r in result.rows if r.type == "W" and r.addr == addr]
    return ws[-1] if ws else None


# ---- DAC -------------------------------------------------------------------

def test_dac_buffoff(composer):
    r = composer.compile(ComposeRequest(name="dac", directives=[
        Directive(kind="clk_enable", periph="DAC"),
        Directive(kind="field_symbol", peri="DAC", reg="OC",
                  symbol="DAC_OUTPUT_ENABLE_BUFFER_DISABLE"),
        Directive(kind="field_symbol", peri="DAC", reg="OC",
                  symbol="DAC_OUTPUTSELECT_VOUT1_EXT"),
        Directive(kind="enable_bit", peri="DAC", reg="CR", field="EN1"),
        Directive(kind="field_value", peri="DAC", reg="DHR12R1",
                  field="DACC1DHR", value=0x800),
    ]))
    assert _w(r, 0x40007438).data == 0x00000202     # OC: EXTEN=2 | EXTCH=1
    assert _w(r, 0x40007400).data == 0x00000001     # CR EN1
    assert _w(r, 0x40007408).data == 0x00000800     # DHR12R1 mid-code
    assert _w(r, 0x4002108C).data == 0x00010000     # APBENR4.DACEN bit16


# ---- OPA -------------------------------------------------------------------

def test_opa_follower(composer):
    """Previously emitted unchecked output; V1 must refuse the known missing semantics."""
    with pytest.raises(ValueError, match='UNKNOWN'):
        composer.compile(ComposeRequest(name="opa", directives=[
                Directive(kind="clk_enable", periph="OPA"),
                Directive(kind="field_symbol", peri="OPA", reg="CSR",
                          symbol="OPA_FOLLOWER_MODE"),
                Directive(kind="enable_bit", peri="OPA", reg="CSR", field="EXTOEN"),
                Directive(kind="enable_bit", peri="OPA", reg="CSR", field="OPAEN"),
            ]))


# ---- PLL chain -------------------------------------------------------------

@pytest.fixture(scope="module")
def pll(composer):
    return composer.compile(ComposeRequest(name="pll", directives=[
        Directive(kind="check_ready", peri="RCC", reg="CR", field="HSIRDY"),
        Directive(kind="field_symbol", peri="RCC", reg="PLLCFGR1",
                  symbol="RCC_PLLSOURCE_HSI"),
        Directive(kind="field_symbol", peri="RCC", reg="PLLCFGR1",
                  symbol="RCC_PLL_MUL6"),
        Directive(kind="enable_bit", peri="RCC", reg="CR", field="PLLON"),
        Directive(kind="check_ready", peri="RCC", reg="CR", field="PLLRDY"),
        Directive(kind="field_value", peri="RCC", reg="CFGR1",
                  field="MCO2SEL", value=0b0100),
        Directive(kind="field_value", peri="RCC", reg="CFGR1",
                  field="MCO2PRE", value=0b1110),
        Directive(kind="clk_enable", periph="GPIOA"),
        Directive(kind="pin_config", pin="PA4", func="MCO2"),
    ]))


def test_pll_values(pll):
    assert _w(pll, 0x40021024).data == 0x00000010   # PLLCFGR1 MUL6
    assert _w(pll, 0x40021000).data == 0x01000100   # CR PLLON | HSION kept
    assert _w(pll, 0x40021014).data == 0xE4000000   # CFGR1 MCO2=PLL /128


def test_pll_ordering(pll):
    seq = [(r.type, r.addr) for r in pll.rows]
    i_cfg = seq.index(("W", 0x40021024))            # PLLCFGR1 (config)
    i_on = seq.index(("W", 0x40021000))             # CR PLLON (enable)
    i_mux = seq.index(("W", 0x40021014))            # CFGR1 (clock mux)
    i_mode = seq.index(("W", 0x40024000))           # GPIO MODER (last)
    assert i_cfg < i_on < i_mux < i_mode            # config before enable
    # PLL ready check sits between enable and mux
    i_rdy = seq.index(("C_H", 0x40021000)) if ("C_H", 0x40021000) in seq else -1
    assert i_rdy != -1


# ---- clock-source family: HSE + a second PLL multiplier --------------------

def test_hse_mco(composer):
    r = composer.compile(ComposeRequest(name="hse", directives=[
        Directive(kind="enable_bit", peri="RCC", reg="CR", field="HSEON"),
        Directive(kind="check_ready", peri="RCC", reg="CR", field="HSERDY"),
        Directive(kind="field_value", peri="RCC", reg="CFGR1",
                  field="MCO2SEL", value=0b0011),
        Directive(kind="field_value", peri="RCC", reg="CFGR1",
                  field="MCO2PRE", value=0b1110),
        Directive(kind="clk_enable", periph="GPIOA"),
        Directive(kind="pin_config", pin="PA4", func="MCO2"),
    ]))
    assert _w(r, 0x40021014).data == 0xE3000000     # CFGR1 MCO2=HSE /128
    assert _w(r, 0x40021000).data == 0x00010100     # CR HSEON | HSION(reset)
    assert any(x.type == "C_H" and x.addr == 0x40021000 and x.data == 0x20000
               for x in r.rows)                     # HSERDY @ bit17 verified


def test_pll_x9_mco(composer):
    r = composer.compile(ComposeRequest(name="pllx9", directives=[
        Directive(kind="check_ready", peri="RCC", reg="CR", field="HSIRDY"),
        Directive(kind="field_symbol", peri="RCC", reg="PLLCFGR1",
                  symbol="RCC_PLLSOURCE_HSI"),
        Directive(kind="field_symbol", peri="RCC", reg="PLLCFGR1",
                  symbol="RCC_PLL_MUL9"),
        Directive(kind="enable_bit", peri="RCC", reg="CR", field="PLLON"),
        Directive(kind="check_ready", peri="RCC", reg="CR", field="PLLRDY"),
        Directive(kind="field_value", peri="RCC", reg="CFGR1",
                  field="MCO2SEL", value=0b0100),
        Directive(kind="field_value", peri="RCC", reg="CFGR1",
                  field="MCO2PRE", value=0b1110),
        Directive(kind="clk_enable", periph="GPIOA"),
        Directive(kind="pin_config", pin="PA4", func="MCO2"),
    ]))
    assert _w(r, 0x40021024).data == 0x0000001C     # PLLCFGR1 MUL9 (7<<2)
    assert _w(r, 0x40021014).data == 0xE4000000     # CFGR1 MCO2=PLL /128


# ---- OPA programmable-gain: single channel (OPA1), value matches corpus ----

def test_opa_pga_x2(composer):
    """Previously emitted unchecked output; V1 must refuse the known missing semantics."""
    with pytest.raises(ValueError, match='UNKNOWN'):
        composer.compile(ComposeRequest(name="pga2", directives=[
                Directive(kind="clk_enable", periph="OPA"),
                Directive(kind="field_symbol", peri="OPA", reg="CSR",
                          symbol="OPA_PGA_MODE"),
                Directive(kind="field_symbol", peri="OPA", reg="CSR",
                          symbol="OPA_PGA_GAIN_2_OR_MINUS_1"),
                Directive(kind="enable_bit", peri="OPA", reg="CSR", field="EXTOEN"),
                Directive(kind="enable_bit", peri="OPA", reg="CSR", field="OPAEN"),
            ]))


# ---- backup-domain clocks: LSI / LSE (PWR unlock -> BDCR -> MCO) ------------

def _lsi_lse(composer, osc):
    pre = [
        Directive(kind="clk_enable", periph="PWR"),
        Directive(kind="enable_bit", peri="PWR", reg="CR1", field="DBP"),
    ]
    if osc == "LSI":
        mid = [
            Directive(kind="enable_bit", peri="RCC", reg="BDCR", field="LSION"),
            Directive(kind="check_ready", peri="RCC", reg="BDCR", field="LSIRDY"),
            Directive(kind="field_value", peri="RCC", reg="CFGR1",
                      field="MCO2SEL", value=0b0101),
        ]
    else:
        mid = [
            Directive(kind="enable_bit", peri="RCC", reg="BDCR", field="LSEON"),
            Directive(kind="field_value", peri="RCC", reg="BDCR",
                      field="LSEDRV", value=3),
            Directive(kind="field_value", peri="RCC", reg="BDCR",
                      field="LSE_RDYSEL", value=3),
            Directive(kind="check_ready", peri="RCC", reg="BDCR", field="LSERDY"),
            Directive(kind="field_value", peri="RCC", reg="CFGR1",
                      field="MCO2SEL", value=0b0110),
        ]
    post = [
        Directive(kind="field_value", peri="RCC", reg="CFGR1",
                  field="MCO2PRE", value=0b1110),
        Directive(kind="clk_enable", periph="GPIOA"),
        Directive(kind="pin_config", pin="PA4", func="MCO2"),
    ]
    return composer.compile(ComposeRequest(name=osc.lower(), directives=pre + mid + post))


def test_lsi_mco(composer):
    r = _lsi_lse(composer, "LSI")
    assert _w(r, 0x4002108C).data == 0x00000200      # RCC.APBENR4.PWREN
    assert (_w(r, 0x40007000).data >> 8) & 1 == 1    # PWR.CR1.DBP unlock
    assert _w(r, 0x400210B0).data == 0x06000000      # BDCR LSION + reset trim
    assert _w(r, 0x40021014).data == 0xE5000000      # CFGR1 MCO2=LSI /128


def test_lse_mco(composer):
    r = _lsi_lse(composer, "LSE")
    assert _w(r, 0x400210B0).data == 0x32000019      # BDCR LSEON|LSEDRV=3|RDYSEL=3
    assert _w(r, 0x40021014).data == 0xE6000000      # CFGR1 MCO2=LSE /128


def test_backup_domain_unlock_before_bdcr(composer):
    # DBP (PWR.CR1) must be written before the BDCR oscillator write
    r = _lsi_lse(composer, "LSI")
    addrs = [x.addr for x in r.rows if x.type == "W"]
    assert addrs.index(0x40007000) < addrs.index(0x400210B0)


# ---- DAC dual-channel: buffer on/off, PA5 routing, code --------------------

def _dac(composer, buffer_sym, vout_sym, extsrc=False, code=0x800):
    ds = [
        Directive(kind="clk_enable", periph="DAC"),
        Directive(kind="field_symbol", peri="DAC", reg="OC", symbol=buffer_sym),
        Directive(kind="field_symbol", peri="DAC", reg="OC", symbol=vout_sym),
    ]
    if extsrc:
        ds.append(Directive(kind="field_value", peri="DAC", reg="OC",
                            field="DAC_EXTSRC_CR", value=1))
    ds += [
        Directive(kind="enable_bit", peri="DAC", reg="CR", field="EN1"),
        Directive(kind="enable_bit", peri="DAC", reg="CR", field="EN2"),
        Directive(kind="field_value", peri="DAC", reg="DHR12R1",
                  field="DACC1DHR", value=code),
        Directive(kind="field_value", peri="DAC", reg="DHR12R2",
                  field="DACC2DHR", value=code),
    ]
    return composer.compile(ComposeRequest(name="dac", directives=ds))


def test_dac_buffon_pa4(composer):
    r = _dac(composer, "DAC_OUTPUT_ENABLE_BUFFER_ENABLE",
             "DAC_OUTPUTSELECT_VOUT1_EXT")
    assert _w(r, 0x40007438).data == 0x00000201     # OC: BUF_EN | VOUT1
    assert _w(r, 0x40007400).data == 0x00010001     # CR: EN1 | EN2 (dual ch)
    assert _w(r, 0x40007408).data == 0x00000800     # DHR12R1
    assert _w(r, 0x40007414).data == 0x00000800     # DHR12R2 (corpus mirror)


def test_dac_buffoff_pa5(composer):
    r = _dac(composer, "DAC_OUTPUT_ENABLE_BUFFER_DISABLE",
             "DAC_OUTPUTSELECT_VOUT2_EXT", extsrc=True)
    assert _w(r, 0x40007438).data == 0x00000406     # OC: BUF_DIS|EXTSRC|VOUT2
    assert _w(r, 0x40007400).data == 0x00010001


def test_dac_code_parametric(composer):
    for code in (0x001, 0x800, 0xFFF):
        r = _dac(composer, "DAC_OUTPUT_ENABLE_BUFFER_DISABLE",
                 "DAC_OUTPUTSELECT_VOUT1_EXT", code=code)
        assert _w(r, 0x40007408).data == code        # DHR12R1 scales with code
        assert _w(r, 0x40007414).data == code        # DHR12R2
