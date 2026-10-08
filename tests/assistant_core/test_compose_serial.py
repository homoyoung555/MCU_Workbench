"""Composer breadth-first acceptance — serial peripherals (node 2): SPI.

SPI is multi-instance (SPI1 @0x40013000, SPI2 @0x40003800); the `instance`
selector must route every field op to the right base. Expected CR1 words are
hand-derived from the SVD field map and pinned EXACT on the functional bits.

NOTE (documented KB gap, not a composer defect): I2C and BKP have no register
addresses in the L0 fieldmap (`register_addresses` lacks both), so the composer
cannot place their writes. They are registered backlog items pending an L1/L0
address backfill — see ARCHITECTURE.md «composer» backlog.
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
    # config-then-enable 后,使能寄存器会被写两次(配置→使能);取末行=最终值
    ws = [r for r in result.rows if r.type == "W" and r.addr == addr]
    return ws[-1] if ws else None


def _spi_master(composer, inst, extra=None):
    """Master, BR=fpclk/8, software NSS, enable — on the given instance."""
    ds = [
        Directive(kind="clk_enable", periph=inst),
        Directive(kind="enable_bit", peri="SPI", instance=inst, reg="CR1",
                  field="MSTR", note="master"),
        Directive(kind="field_value", peri="SPI", instance=inst, reg="CR1",
                  field="BR", value=2, note="fpclk/8"),
        Directive(kind="enable_bit", peri="SPI", instance=inst, reg="CR1",
                  field="SSM", note="software NSS"),
        Directive(kind="enable_bit", peri="SPI", instance=inst, reg="CR1",
                  field="SSI"),
    ]
    ds += extra or []
    ds.append(Directive(kind="enable_bit", peri="SPI", instance=inst,
                        reg="CR1", field="SPE", note="enable"))
    return composer.compile(ComposeRequest(name=f"spi_{inst}", directives=ds))


# ---- SPI1 master, SPI mode 0 (CPOL=0, CPHA=0) ------------------------------
# CR1 = MSTR(0x4) | BR=2<<3(0x10) | SPE(0x40) | SSI(0x100) | SSM(0x200) = 0x354

def test_spi1_master_mode0(composer):
    r = _spi_master(composer, "SPI1")
    assert _w(r, 0x40021088).data == 0x00400000      # APBENR3.SPI1EN bit22
    assert _w(r, 0x40013000).data == 0x00000354      # SPI1.CR1 @ SPI1 base
    # clock enable precedes the functional register
    addrs = [x.addr for x in r.rows if x.type == "W"]
    assert addrs.index(0x40021088) < addrs.index(0x40013000)


# ---- config-then-enable: 使能位拆成单独后置一次写 -------------------------

def test_enable_split_config_then_enable(composer):
    # CR1 拆成 配置(SPE=0)→ 使能(SPE=1)两步,使能在后(PHASE_ENABLE)。
    # 这是 DMA 等"必须配完再使能"外设能工作的前提;最终值仍是 0x354。
    r = _spi_master(composer, "SPI1")
    cr1 = [x for x in r.rows if x.type == "W" and x.addr == 0x40013000]
    assert len(cr1) == 2                       # 两步写
    assert cr1[0].data == 0x00000314           # 配置先:MSTR|BR|SSI|SSM,无 SPE(bit6)
    assert not cr1[0].data & 0x40              # SPE=0
    assert cr1[1].data == 0x00000354           # 使能后:含 SPE
    assert cr1[0].phase < cr1[1].phase         # 使能相位更后


# ---- instance routing: same config on SPI2 lands at the SPI2 base ----------

def test_spi2_instance_routing(composer):
    r = _spi_master(composer, "SPI2")
    assert _w(r, 0x40021088).data == 0x00800000      # APBENR3.SPI2EN bit23
    assert _w(r, 0x40003800).data == 0x00000354      # SPI2.CR1 @ SPI2 base
    assert _w(r, 0x40013000) is None                 # nothing at SPI1 base


# ---- SPI mode 3 (CPOL=1, CPHA=1): clock-polarity/phase bits set ------------

def test_spi1_mode3(composer):
    r = _spi_master(composer, "SPI1", extra=[
        Directive(kind="enable_bit", peri="SPI", instance="SPI1", reg="CR1",
                  field="CPOL", note="idle high"),
        Directive(kind="enable_bit", peri="SPI", instance="SPI1", reg="CR1",
                  field="CPHA", note="2nd edge"),
    ])
    # base 0x354 + CPHA(bit0) + CPOL(bit1) = 0x357
    assert _w(r, 0x40013000).data == 0x00000357


# ---- USART: 8N1, BRR divisor, TE/RE/UE enable -----------------------------
# BRR is a full-word operand (oversampling-16 divisor) -> write_reg.
# CR1 = RE(bit2) | TE(bit3) | UE(bit13) = 0x200C; 8N1 leaves CR2.STOP at reset.

def test_usart_8n1(composer):
    r = composer.compile(ComposeRequest(name="usart", directives=[
        Directive(kind="clk_enable", periph="USART"),
        Directive(kind="write_reg", peri="USART", reg="BRR", value=0x45,
                  note="8MHz/115200 = 69"),
        Directive(kind="enable_bit", peri="USART", reg="CR1", field="RE",
                  note="rx enable"),
        Directive(kind="enable_bit", peri="USART", reg="CR1", field="TE",
                  note="tx enable"),
        Directive(kind="enable_bit", peri="USART", reg="CR1", field="UE",
                  note="usart enable"),
    ]))
    assert _w(r, 0x40021088).data == 0x00000040      # APBENR3.USARTEN bit6
    assert _w(r, 0x40013808).data == 0x00000045      # BRR divisor
    assert _w(r, 0x4001380C).data == 0x0000200C      # CR1: RE | TE | UE
    # baud divisor is programmed before the peripheral is enabled
    addrs = [x.addr for x in r.rows if x.type == "W"]
    assert addrs.index(0x40013808) < addrs.index(0x4001380C)


# ---- UART (basic variant, multi-instance): frame format + baud -------------
# This UART models only the frame (M/STOP/PCE), no UE/TE/RE enable bits.
# CR1 = M=1 | STOP(bit2) | PCE(bit3) = 0xD.

def test_uart1_frame(composer):
    r = composer.compile(ComposeRequest(name="uart", directives=[
        Directive(kind="clk_enable", periph="UART1"),
        Directive(kind="write_reg", peri="UART", instance="UART1", reg="BRR",
                  value=0x45, note="baud divisor"),
        Directive(kind="field_value", peri="UART", instance="UART1", reg="CR1",
                  field="M", value=1, note="9-bit frame"),
        Directive(kind="enable_bit", peri="UART", instance="UART1", reg="CR1",
                  field="STOP", note="2 stop bits"),
        Directive(kind="enable_bit", peri="UART", instance="UART1", reg="CR1",
                  field="PCE", note="parity enable"),
    ]))
    assert _w(r, 0x40021088).data == 0x00000001      # APBENR3.UART1EN bit0
    assert _w(r, 0x40004C04).data == 0x00000045      # UART1.BRR
    assert _w(r, 0x40004C14).data == 0x0000000D      # UART1.CR1: M1|STOP|PCE


# ---- LPUART: USART-style CR1 (UE/TE/RE). No RCC clock-enable in the KB ------
# (LPUART1 has no clk_enable macro — recorded as a minor KB gap; the CR1/BRR
# placement is still EXACT.)

def test_lpuart_enable(composer):
    r = composer.compile(ComposeRequest(name="lpuart", directives=[
        Directive(kind="write_reg", peri="LPUART", reg="BRR", value=0x22B,
                  note="baud divisor"),
        Directive(kind="enable_bit", peri="LPUART", reg="CR1", field="RE"),
        Directive(kind="enable_bit", peri="LPUART", reg="CR1", field="TE"),
        Directive(kind="enable_bit", peri="LPUART", reg="CR1", field="UE"),
    ]))
    assert _w(r, 0x4000800C).data == 0x0000022B      # LPUART.BRR
    assert _w(r, 0x40008000).data == 0x0000000D      # CR1: RE(2)|TE(3)|UE(0)
