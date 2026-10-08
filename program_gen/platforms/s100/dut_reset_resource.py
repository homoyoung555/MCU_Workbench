"""Pure S100 SD resource generator for a firmware sub-boundary reset."""

from __future__ import annotations

import hashlib
import re

from program_gen.core.firmware_test import DutResetAction
from program_gen.render_plan import ResourceRequest


_PIN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SUPPORTED_PROFILE = DutResetAction()
_RPT_PER_MS = 1_000_000 // 200


def generate_dut_reset_resource(
    nrst_pin: str, action: DutResetAction
) -> ResourceRequest:
    """Render LOW 5ms -> HIGH 5ms -> released using the S100 200ns period."""
    pin = str(nrst_pin).strip()
    if not _PIN_RE.fullmatch(pin):
        raise ValueError("S100.DUT_RESET.PIN_INVALID: NRST pin must be one identifier")
    if action != _SUPPORTED_PROFILE:
        raise ValueError(
            "S100.DUT_RESET.PROFILE_UNSUPPORTED: expected LOW 5ms, HIGH 5ms, "
            "then RELEASED_HIGH"
        )

    low_rpt = action.low_duration_ms * _RPT_PER_MS
    high_rpt = action.high_duration_ms * _RPT_PER_MS
    content = (
        "HEAD[PIN_NAME]:\n"
        "\n"
        f"{pin};\n"
        "\n"
        "END_HEAD;\n"
        "\n"
        "@@PATTERN_DEFINE\n"
        "\n"
        "START:X;\n"
        f"      0;RPT {low_rpt};// low 5ms\n"
        f"      1;RPT {high_rpt};// high 5ms\n"
        f"      X;// release {pin}\n"
        "  END:X;\n"
        "\n"
        "@@END_PATTERN_DEFINE\n"
    ).encode("ascii")
    digest = hashlib.sha256(content).hexdigest().upper()
    return ResourceRequest(
        logical_identity="pattern:dut_reset",
        relative_path="dut_reset.sd",
        content=content,
        spec_identity="v14.dut-reset/1:s100:5ms-5ms",
        source_identity=f"generated:s100:dut-reset:sha256:{digest}",
        purpose="FIRMWARE DutResetAction NRST reset",
    )


__all__ = ["generate_dut_reset_resource"]
