"""Pure Chroma Pattern resource generator for firmware sub-boundary reset."""

from __future__ import annotations

import hashlib
import re

from program_gen.core.firmware_test import DutResetAction
from program_gen.render_plan import ResourceRequest


_PIN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_PATTERN_NAME = "firmware_dut_reset"
_TS1_NS = 200


def generate_dut_reset_pattern(
    nrst_pin: str,
    action: DutResetAction,
) -> ResourceRequest:
    """Render LOW 5ms -> HIGH 5ms -> released-high as a real .pat resource."""
    pin = nrst_pin.strip() if isinstance(nrst_pin, str) else ""
    if not _PIN_RE.fullmatch(pin):
        raise ValueError(
            f"CHROMA.DUT_RESET.PIN_INVALID: invalid Chroma pin {nrst_pin!r}"
        )
    if not isinstance(action, DutResetAction) or (
        action.low_duration_ms,
        action.high_duration_ms,
        action.final_state,
    ) != (5, 5, "RELEASED_HIGH"):
        raise ValueError(
            "CHROMA.DUT_RESET.PROFILE_UNSUPPORTED: expected "
            "LOW 5ms -> HIGH 5ms -> RELEASED_HIGH"
        )

    low_rpt = action.low_duration_ms * 1_000_000 // _TS1_NS
    high_rpt = action.high_duration_ms * 1_000_000 // _TS1_NS
    content = (
        'SET_DEC_FILE "pin.dec"\n\n'
        f"HEADER\n\n{pin};\n\n"
        f"SPM_PATTERN({_PATTERN_NAME}) {{\n\n"
        "  *X*TS1;\n"
        f"  *0*RPT {low_rpt};// assert NRST low for 5ms\n"
        f"  *1*RPT {high_rpt};// deassert NRST high for 5ms\n"
        "  *X*STOP;// release NRST\n"
        "}"
    ).encode("ascii")
    digest = hashlib.sha256(content).hexdigest().upper()
    profile = "low5ms:high5ms:released-high"
    return ResourceRequest(
        logical_identity=f"firmware-dut-reset:{pin}:{profile}",
        relative_path=f"pat/{_PATTERN_NAME}.pat",
        content=content,
        spec_identity="v14.firmware-dut-reset/1:chroma:ts1-200ns",
        source_identity=(
            f"generated:chroma:firmware-dut-reset:{pin}:sha256:{digest}"
        ),
        purpose="Chroma firmware sub-boundary NRST reset Pattern",
    )


__all__ = ["generate_dut_reset_pattern"]
