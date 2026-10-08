from __future__ import annotations

import tempfile
from pathlib import Path
import unittest


WGL = '''waveform chip_top
signal
    "PAD_PA"[0] : input initialp[N];
end
timeplate "_WFT_" period 40ns
    "PAD_PA"[0] := input [0ns:D, 20ns:S, 30ns:D];
end
pattern tiny_scan("PAD_PA"[0] :I)
    vector(+, "_WFT_") := [0];
    vector(+, "_WFT_") := [1];
end
'''


class Wgl2ChromaCraftCompatibilityTests(unittest.TestCase):
    def test_chroma_pattern_keeps_marker_names_as_comments_not_executable_labels(self):
        from tools.wgl2chroma.converter import convert_one

        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "tiny_scan.wgl"
            output = Path(temp) / "tiny_scan.pat"
            source.write_text(WGL, encoding="utf-8")
            convert_one(str(source), str(output), target="chroma")

            pattern = output.read_text(encoding="utf-8")
            self.assertIn("// tiny_scan_st::", pattern)
            self.assertIn("// tiny_scan_sp::", pattern)
            self.assertNotRegex(pattern, r"(?m)^tiny_scan_(?:st|sp)::$")
            self.assertIn("*0* WFT;", pattern)
            self.assertIn("*1*STOP;", pattern)


if __name__ == "__main__":
    unittest.main()
