import unittest
import re
from program_gen.core.run_sequence import SendCodeAction, LevelSequenceAction
from program_gen.core.firmware_judge import DigitalCompareJudgePlan
from program_gen.platforms.chroma.firmware_test_renderer import generate_send_code_resource, generate_level_sequence_resource, generate_digital_compare_resource

class ChromaTriggerPatternTests(unittest.TestCase):
    def test_send_codes_share_resource_with_independent_complete_frames(self):
        one = generate_send_code_resource(SendCodeAction("PA0", 1))
        self.assertEqual(one.relative_path, "pat/Trigger_Send.pat")
        self.assertEqual(one, generate_send_code_resource(SendCodeAction("PA0", 255)))
        text = one.content.decode("ascii")
        for value in range(256):
            label = f"S{value:02X}"
            frame = text.split(label + "_ST:\n", 1)[1].split(label + "_SP:", 1)[0]
            self.assertTrue(frame.startswith("  *X*TS1;"))
            self.assertIn("\n".join(f"  *{bit}*RPT 422;" for bit in f"{value:08b}"), frame)
            self.assertTrue(frame.endswith("  *0*RPT 502;\n"))
        self.assertEqual(text.count("SPM_PATTERN("), 1)
        self.assertNotIn("0x", text)
        self.assertEqual(len(re.findall(r"^S[0-9A-F]{2}_(?:ST|SP):$", text, re.M)), 512)

    def test_trigger_name_keeps_explicit_pin_origin(self):
        implicit = generate_level_sequence_resource(LevelSequenceAction("PA13", "HL", 5000000))
        explicit = generate_level_sequence_resource(LevelSequenceAction("PA13", "HL", 5000000, True))
        self.assertEqual(implicit.relative_path, "pat/Trigger_HL_5mS.pat")
        self.assertEqual(explicit.relative_path, "pat/PA13_Trigger_HL_5mS.pat")

    def test_compare_states_share_file(self):
        a = DigitalCompareJudgePlan(("PA13", "PA14"), ("H", "H"), "pat", "test", None)
        b = DigitalCompareJudgePlan(a.pins, ("L", "L"), "pat", "other", None)
        resource = generate_digital_compare_resource(a)
        self.assertEqual(resource.relative_path, "pat/PA13_PA14_Compare.pat")
        self.assertEqual(resource, generate_digital_compare_resource(b))
        for state in ("HH", "HL", "LH", "LL"):
            self.assertIn((state + "_ST:\n").encode(), resource.content)

    def test_opa_and_dac_actions_call_send_labels_not_file_bounds(self):
        from program_gen.platforms.chroma.dac_test_renderer import _actions as dac_actions
        from program_gen.platforms.chroma.opa_test_renderer import _actions as opa_actions
        for render in (dac_actions, opa_actions):
            resources = []
            body = "\n".join(render((SendCodeAction("PA0", 1, True), SendCodeAction("PA0", 2, True)), resources))
            self.assertIn("JUDGE_PAT(PA0_Trigger_Send:S01_ST,PA0_Trigger_Send:S01_SP);", body)
            self.assertIn("JUDGE_PAT(PA0_Trigger_Send:S02_ST,PA0_Trigger_Send:S02_SP);", body)
            self.assertEqual(resources[0], resources[1])

    def test_compare_spans_use_full_pvd_waveform(self):
        from program_gen.platforms.chroma.firmware_test_renderer import compare_pattern_span
        judge = DigitalCompareJudgePlan(("PA13", "PA14"), ("H", "H"), "pat", "test", None)
        source = generate_digital_compare_resource(judge).content.decode("ascii").splitlines()
        labels = [line[:-1] for line in source if line.endswith(":")]
        self.assertEqual(len(labels), 8)
        self.assertEqual(len(set(labels)), 8)
        for state in ("HH", "HL", "LH", "LL"):
            start, end = compare_pattern_span(judge.pins, tuple(state))
            first = source.index(start.split(":")[1] + ":")
            last = source.index(end.split(":")[1] + ":")
            vectors = tuple(line.strip() for line in source[first + 1:last + 2] if line.lstrip().startswith("*"))
            self.assertEqual(vectors, (
                "*XX*TS1;", "*XX*RPT 100;", "*XX*RPT 100;",
                f"*{state}*;", f"*{state}*;", f"*{state}*RPT 100;", f"*{state}*;",
                "*XX*;", "*XX*;", "*XX*;",
            ))
            cycles = sum(int(match.group(1)) if (match := re.search(r"RPT (\d+)", line)) else 1 for line in vectors)
            self.assertEqual(cycles, 307)
