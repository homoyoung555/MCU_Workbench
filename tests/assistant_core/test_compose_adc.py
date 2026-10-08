"""Composer breadth-first acceptance — ADC (node 4).

Modern SQR-sequenced ADC (CR/CFGR/SQRx), multi-instance ADC1 @0x40012400 /
ADC2 @0x40012800. Expected words hand-derived from the SVD field map and pinned
EXACT on the functional bits.
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


# ---- ADC1: 10-bit resolution, continuous, 1 conversion on channel 5 --------
# CFGR = RES=1<<3 (10-bit) | CONT (bit13)        = 0x2008
# SQR1 = SQ1 = 5<<6 (channel 5 as 1st in sequence) = 0x140
# CR   = ADEN (bit0)                               = 0x1

def test_adc1_single_channel(composer):
    r = composer.compile(ComposeRequest(name="adc", directives=[
        Directive(kind="clk_enable", periph="ADC1"),
        Directive(kind="field_value", peri="ADC", instance="ADC1", reg="CFGR",
                  field="RES", value=1, note="10-bit"),
        Directive(kind="enable_bit", peri="ADC", instance="ADC1", reg="CFGR",
                  field="CONT", note="continuous"),
        Directive(kind="field_value", peri="ADC", instance="ADC1", reg="SQR1",
                  field="SQ1", value=5, note="channel 5 first"),
        Directive(kind="enable_bit", peri="ADC", instance="ADC1", reg="CR",
                  field="ADEN", note="enable"),
    ]))
    assert _w(r, 0x4002108C).data == 0x00000800      # APBENR4.ADC1EN bit11
    assert _w(r, 0x4001240C).data == 0x00002008      # CFGR: RES=10b | CONT
    assert _w(r, 0x40012430).data == 0x00000140      # SQR1: SQ1=ch5
    assert _w(r, 0x40012408).data == 0x00000001      # CR: ADEN
    # clock enable precedes the converter enable
    addrs = [x.addr for x in r.rows if x.type == "W"]
    assert addrs.index(0x4002108C) < addrs.index(0x40012408)


# ---- instance routing: ADC2 lands at the ADC2 base -------------------------

def test_adc2_instance_routing(composer):
    r = composer.compile(ComposeRequest(name="adc2", directives=[
        Directive(kind="clk_enable", periph="ADC2"),
        Directive(kind="enable_bit", peri="ADC", instance="ADC2", reg="CR",
                  field="ADEN", note="enable"),
    ]))
    assert _w(r, 0x40012808).data == 0x00000001      # ADC2.CR @ ADC2 base
    assert _w(r, 0x40012408) is None                 # nothing at ADC1 base
