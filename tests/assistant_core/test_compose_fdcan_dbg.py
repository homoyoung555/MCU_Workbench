"""Composer breadth-first acceptance — FDCAN / DBGMCU (node 8, final sweep).

FDCAN: Bosch M_CAN config-window protocol (CCCR INIT/CCE around the NBTP bit-
timing write) — three ordered writes to CCCR via write_reg. DBGMCU: debug-freeze
bits, and a regression lock for the malformed-reset hardening (DBGMCU.CR1 has
source-defect reset strings "1'b9"/"1'b8" that must degrade to a warning, never
crash the compile).

DEFERRED (documented, not done): EPWM is a 112-register, EALLOW-protected
motor-control crossbar with chip-specific semantics; a faithful EXACT corpus
needs the part datasheet, so it is a registered backlog item rather than
fabricated values. I2C and BKP remain address gaps (see test_compose_serial).
"""
from __future__ import annotations

import pytest

from swd_authoring import Composer, ComposeRequest, Directive
from swd_authoring import EncodingDB
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


# ---- FDCAN: enter config window, set nominal bit timing, exit to run --------
# CCCR written three times (INIT -> INIT|CCE -> clear) straddling the NBTP
# write; NBTP = NTSEG2(3) | NTSEG1=12<<8 | NSJW=3<<25 = 0x06000C03.

def test_fdcan_bit_timing(composer):
    """Previously emitted unchecked output; V1 must refuse the known missing semantics."""
    with pytest.raises(ValueError, match='access'):
        composer.compile(ComposeRequest(name="fdcan", directives=[
                Directive(kind="clk_enable", periph="FDCAN"),
                Directive(kind="write_reg", peri="FDCAN", reg="CCCR", value=0x1,
                          note="INIT request"),
                Directive(kind="write_reg", peri="FDCAN", reg="CCCR", value=0x3,
                          note="INIT|CCE config access"),
                Directive(kind="field_value", peri="FDCAN", reg="NBTP", field="NTSEG2",
                          value=3),
                Directive(kind="field_value", peri="FDCAN", reg="NBTP", field="NTSEG1",
                          value=12),
                Directive(kind="field_value", peri="FDCAN", reg="NBTP", field="NSJW",
                          value=3),
                Directive(kind="write_reg", peri="FDCAN", reg="CCCR", value=0x0,
                          note="clear INIT -> run"),
            ]))


# ---- DBGMCU: debug-freeze in stop/standby. No clock gate. ------------------
# CR1 = base 0x80000 (DBG_TIM6_STOP reset=1) | DBG_STOP(bit1) | DBG_STDBY(bit2).

def test_dbgmcu_freeze(composer):
    r = composer.compile(ComposeRequest(name="dbgmcu", directives=[
        Directive(kind="enable_bit", peri="DBGMCU", reg="CR1",
                  field="DBG_STOP", note="freeze in stop"),
        Directive(kind="enable_bit", peri="DBGMCU", reg="CR1",
                  field="DBG_STDBY", note="freeze in standby"),
    ]))
    assert _w(r, 0xE0042004).data == 0x00080006      # TIM6 reset | STOP | STDBY
    # the source-defect reset fields ("1'b9"/"1'b8") must surface as a warning,
    # not crash — this is the malformed-reset hardening regression lock.
    assert any("DBGMCU.CR1" in w and "doc defect" in w for w in r.warnings)


# ---- unit: malformed Verilog reset string degrades to None (no crash) ------

def test_parse_reset_malformed():
    assert EncodingDB._parse_reset("1'b9") is None    # 1-bit can't hold 9
    assert EncodingDB._parse_reset("1'b8") is None
    assert EncodingDB._parse_reset("1'b0") == 0       # well-formed still works
    assert EncodingDB._parse_reset("8'hFF") == 0xFF
