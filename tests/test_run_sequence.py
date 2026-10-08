from dataclasses import FrozenInstanceError, dataclass
import unittest

from program_gen.core.run_sequence import (
    ForceStopAction,
    LevelSequenceAction,
    RepowerAction,
    RunSequenceCompileError,
    SendCodeAction,
    WaitAction,
    parse_run_sequence_step,
)


@dataclass(frozen=True, slots=True)
class ClockForceAction:
    pin: str
    frequency_hz: int


class RunSequenceParserTests(unittest.TestCase):
    def test_formal_generic_keil_steps_compile_to_ordered_actions(self):
        force = ClockForceAction("PD0", 32_000_000)

        cases = (
            (
                "PA13:HL-W500\nPA13:HL-W100",
                None,
                (
                    LevelSequenceAction("PA13", "HL", 5_000_000, True),
                    WaitAction(500),
                    LevelSequenceAction("PA13", "HL", 5_000_000, True),
                    WaitAction(100),
                ),
            ),
            (
                "PA11:HLHL-500uS-W100",
                None,
                (
                    LevelSequenceAction("PA11", "HLHL", 500_000, True),
                    WaitAction(100),
                ),
            ),
            (
                "PA13:HL-W400",
                None,
                (
                    LevelSequenceAction("PA13", "HL", 5_000_000, True),
                    WaitAction(400),
                ),
            ),
            (
                "HL-222-13-1-1-2-F-W100",
                force,
                (
                    LevelSequenceAction("PA0", "HL", 5_000_000),
                    SendCodeAction("PA0", 222),
                    SendCodeAction("PA0", 13),
                    SendCodeAction("PA0", 1),
                    SendCodeAction("PA0", 1),
                    SendCodeAction("PA0", 2),
                    force,
                    WaitAction(100),
                ),
            ),
            (
                "HL-222-16-F-W200",
                force,
                (
                    LevelSequenceAction("PA0", "HL", 5_000_000),
                    SendCodeAction("PA0", 222),
                    SendCodeAction("PA0", 16),
                    force,
                    WaitAction(200),
                ),
            ),
            (
                "HL-222-17-F-W200",
                force,
                (
                    LevelSequenceAction("PA0", "HL", 5_000_000),
                    SendCodeAction("PA0", 222),
                    SendCodeAction("PA0", 17),
                    force,
                    WaitAction(200),
                ),
            ),
        )
        for step, force_action, expected in cases:
            with self.subTest(step=step):
                self.assertEqual(
                    parse_run_sequence_step(
                        step, default_pin="PA0", force_action=force_action
                    ),
                    expected,
                )

    def test_explicit_width_is_case_insensitive_and_default_is_five_ms(self):
        actions = parse_run_sequence_step("H-200NS-L", default_pin="PA0")
        self.assertEqual(
            actions,
            (
                LevelSequenceAction("PA0", "H", 200),
                LevelSequenceAction("PA0", "L", 5_000_000),
            ),
        )
        with self.assertRaises(FrozenInstanceError):
            actions[0].levels = "L"

    def test_dynamic_code_requires_an_explicit_value_and_keeps_current_pin(self):
        self.assertEqual(
            parse_run_sequence_step(
                "PB2:HL-222-X", default_pin="PA0", dynamic_code=7
            ),
            (
                LevelSequenceAction("PB2", "HL", 5_000_000, True),
                SendCodeAction("PB2", 222, True),
                SendCodeAction("PB2", 7, True),
            ),
        )
        with self.assertRaises(RunSequenceCompileError) as raised:
            parse_run_sequence_step("HL-X", default_pin="PA0")
        self.assertEqual(raised.exception.code, "RUN_SEQUENCE.DYNAMIC_CODE_REQUIRED")

    def test_force_stop_and_repower_are_explicit_actions(self):
        force = ClockForceAction("PC14", 32_768)
        self.assertEqual(
            parse_run_sequence_step(
                "F-W200-FS-RP", default_pin="PA0", force_action=force
            ),
            (force, WaitAction(200), ForceStopAction(), RepowerAction()),
        )

    def test_terminal_token_is_forbidden_at_any_position_and_line(self):
        for step in ("T", "HL-T-W100", "PA0:HL-W5\nPB2:T"):
            with self.subTest(step=step):
                with self.assertRaises(RunSequenceCompileError) as raised:
                    parse_run_sequence_step(step, default_pin="PA0")
                self.assertEqual(
                    raised.exception.code,
                    "RUN_SEQUENCE.TERMINAL_TOKEN_FORBIDDEN",
                )

    def test_invalid_tokens_and_missing_inputs_fail_with_stable_codes(self):
        cases = (
            ("F", {}, "RUN_SEQUENCE.FORCE_ACTION_REQUIRED"),
            ("HL-500us", {"default_pin": ""}, "RUN_SEQUENCE.DEFAULT_PIN_REQUIRED"),
            ("HL-0ms", {}, "RUN_SEQUENCE.DURATION_INVALID"),
            ("256", {}, "RUN_SEQUENCE.CODE_OUT_OF_RANGE"),
            ("500us", {}, "RUN_SEQUENCE.TOKEN_UNKNOWN"),
            ("PA0:", {}, "RUN_SEQUENCE.LINE_EMPTY"),
        )
        for step, kwargs, code in cases:
            with self.subTest(step=step):
                with self.assertRaises(RunSequenceCompileError) as raised:
                    parse_run_sequence_step(step, **{"default_pin": "PA0", **kwargs})
                self.assertEqual(raised.exception.code, code)

        with self.assertRaises(RunSequenceCompileError) as raised:
            parse_run_sequence_step(
                "X", default_pin="PA0", dynamic_code=7.5
            )
        self.assertEqual(raised.exception.code, "RUN_SEQUENCE.CODE_OUT_OF_RANGE")

    def test_blank_or_slash_step_is_an_empty_sequence(self):
        for step in (None, "", "  ", "/"):
            with self.subTest(step=step):
                self.assertEqual(
                    parse_run_sequence_step(step, default_pin="PA0"), ()
                )


if __name__ == "__main__":
    unittest.main()
