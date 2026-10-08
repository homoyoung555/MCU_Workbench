"""Composer breadth-first acceptance — TIM / DMA (node 6).

TIM: multi-instance time-base (PSC/ARR/EGR/CR1), instance selector routes to
the right base. DMA: exercises `write_reg` for the full-word address operands
CPAR/CMAR that are NOT bit-fields — the second motivation for that directive.
Expected words hand-derived from the SVD field map, pinned EXACT.
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


# ---- TIM3 time-base: prescale, auto-reload, force update, enable -----------
# PSC=7999 (0x1F3F), ARR=999 (0x3E7, replaces the 0xFFFFFFFF reset),
# EGR.UG latches the shadow regs, CR1.CEN starts the counter.

def test_tim3_timebase(composer):
    r = composer.compile(ComposeRequest(name="tim3", directives=[
        Directive(kind="clk_enable", periph="TIM3"),
        Directive(kind="field_value", peri="TIM", instance="TIM3", reg="PSC",
                  field="PSC", value=7999, note="prescaler"),
        Directive(kind="field_value", peri="TIM", instance="TIM3", reg="ARR",
                  field="ARR", value=999, note="auto-reload"),
        Directive(kind="enable_bit", peri="TIM", instance="TIM3", reg="EGR",
                  field="UG", note="latch shadow regs"),
        Directive(kind="enable_bit", peri="TIM", instance="TIM3", reg="CR1",
                  field="CEN", note="start counter"),
    ]))
    assert _w(r, 0x40021080).data == 0x00000008       # APBENR1.TIM3EN bit3
    assert _w(r, 0x40000428).data == 0x00001F3F       # TIM3.PSC
    assert _w(r, 0x4000042C).data == 0x000003E7       # TIM3.ARR (32-bit)
    assert _w(r, 0x40000414).data == 0x00000001       # TIM3.EGR.UG
    assert _w(r, 0x40000400).data == 0x00000001       # TIM3.CR1.CEN
    # update event latches the period before the counter starts
    addrs = [x.addr for x in r.rows if x.type == "W"]
    assert addrs.index(0x40000428) < addrs.index(0x40000414) < \
        addrs.index(0x40000400)


# ---- instance routing: same config on TIM1 lands at the TIM1 base ----------

def test_tim_instance_routing(composer):
    r = composer.compile(ComposeRequest(name="tim1", directives=[
        Directive(kind="clk_enable", periph="TIM1"),
        Directive(kind="enable_bit", peri="TIM", instance="TIM1", reg="CR1",
                  field="CEN"),
    ]))
    assert _w(r, 0x40012C00).data == 0x00000001       # TIM1.CR1 @ TIM1 base
    assert _w(r, 0x40000400) is None                  # nothing at TIM3 base


# ---- DMA channel 1: address operands via write_reg, then CCR config --------
# CPAR/CMAR are full 32-bit addresses (not fields) -> write_reg.
# CCR = DIR(0x20) | MINC=1<<10(0x400) | PL=2<<16(0x20000) | EN(0x1) = 0x20421.

def test_dma_channel1(composer):
    r = composer.compile(ComposeRequest(name="dma", directives=[
        Directive(kind="clk_enable", periph="DMA"),
        Directive(kind="write_reg", peri="DMA", reg="CPAR1", value=0x4001380C,
                  note="peripheral address"),
        Directive(kind="write_reg", peri="DMA", reg="CMAR1", value=0x20000000,
                  note="memory address"),
        Directive(kind="field_value", peri="DMA", reg="CNDTR1", field="NDT",
                  value=16, note="transfer count"),
        Directive(kind="enable_bit", peri="DMA", reg="CCR1", field="DIR"),
        Directive(kind="field_value", peri="DMA", reg="CCR1", field="MINC",
                  value=1, note="memory increment"),
        Directive(kind="field_value", peri="DMA", reg="CCR1", field="PL",
                  value=2, note="high priority"),
        Directive(kind="enable_bit", peri="DMA", reg="CCR1", field="EN",
                  note="enable last"),
    ]))
    assert _w(r, 0x40021070).data == 0x00000021       # AHBENR1: DMAEN | SRAMSMEN
    assert _w(r, 0x40020010).data == 0x4001380C       # CPAR1 (32-bit operand)
    assert _w(r, 0x40020014).data == 0x20000000       # CMAR1 (32-bit operand)
    assert _w(r, 0x4002000C).data == 0x00000010       # CNDTR1 = 16
    assert _w(r, 0x40020008).data == 0x00020421       # CCR1 config word
    # operands are programmed before the channel is enabled
    addrs = [x.addr for x in r.rows if x.type == "W"]
    assert addrs.index(0x40020010) < addrs.index(0x40020008)


# ---- LPTIM: ENABLE must precede ARR/CMP; CNTSTRT comes after ---------------
# LPTIM requires CR.ENABLE=1 *before* writing ARR/CMP, then CR.CNTSTRT to start.
# CR is written twice (0x1 then 0x5) — write_reg keeps them ordered around the
# period registers; aggregation would wrongly collapse them.

def test_lptim_bringup(composer):
    r = composer.compile(ComposeRequest(name="lptim", directives=[
        Directive(kind="clk_enable", periph="LPTIM"),
        Directive(kind="field_value", peri="LPTIM", reg="CFGR", field="PRESC",
                  value=3, note="prescaler /8"),
        Directive(kind="write_reg", peri="LPTIM", reg="CR", value=0x1,
                  note="ENABLE (before ARR/CMP)"),
        Directive(kind="field_value", peri="LPTIM", reg="ARR", field="ARR",
                  value=0xFFFF, note="auto-reload"),
        Directive(kind="field_value", peri="LPTIM", reg="CMP", field="CMP",
                  value=0x8000, note="compare"),
        Directive(kind="write_reg", peri="LPTIM", reg="CR", value=0x5,
                  note="CNTSTRT (after ARR/CMP)"),
    ]))
    assert _w(r, 0x40021084).data == 0x00010000      # APBENR2.LPTIMEN bit16
    assert _w(r, 0x40007C0C).data == 0x00000600      # CFGR: PRESC=3<<9
    assert _w(r, 0x40007C18).data == 0x0000FFFF      # ARR
    assert _w(r, 0x40007C14).data == 0x00008000      # CMP
    cr = [x for x in r.rows if x.type == "W" and x.addr == 0x40007C10]
    assert [w.data for w in cr] == [0x1, 0x5]        # ENABLE then CNTSTRT
    # ENABLE precedes the period writes, which precede CNTSTRT
    seq = [(w.addr, w.data) for w in r.rows if w.type == "W"]
    assert seq.index((0x40007C10, 0x1)) < seq.index((0x40007C18, 0xFFFF)) < \
        seq.index((0x40007C10, 0x5))
