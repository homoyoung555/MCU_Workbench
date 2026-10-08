from __future__ import annotations

import unittest
from unittest.mock import patch

from program_gen.platforms.chroma.project_files import (
    cp_has_kp_relay,
)


class ChromaPinCapabilityTests(unittest.TestCase):
    def test_kp_capability_matches_the_dec_renderer_for_multi_site_cp2(self):
        columns = {
            ("PIN_DEC_128", "CP NO"): ["CP2", "CP2"],
            ("PIN_DEC_128", "Trace"): ["596F0", "597F1"],
            ("PIN_DEC_128", "Site"): [1, 2],
        }
        with patch(
            "program_gen.platforms.chroma.project_files.G.col",
            side_effect=lambda table, column: columns[(table, column)],
        ):
            self.assertFalse(cp_has_kp_relay("CP2"))

    def test_kp_capability_keeps_multi_site_cp1_and_single_site_cp2(self):
        cases = (
            ("CP1", ["CP1", "CP1"], ["596F0", "597F1"], [1, 2]),
            ("CP2", ["CP2"], ["596"], [1]),
        )
        for cp, cps, traces, sites in cases:
            columns = {
                ("PIN_DEC_128", "CP NO"): cps,
                ("PIN_DEC_128", "Trace"): traces,
                ("PIN_DEC_128", "Site"): sites,
            }
            with self.subTest(cp=cp), patch(
                "program_gen.platforms.chroma.project_files.G.col",
                side_effect=lambda table, column: columns[(table, column)],
            ):
                self.assertTrue(cp_has_kp_relay(cp))


if __name__ == "__main__":
    unittest.main()
