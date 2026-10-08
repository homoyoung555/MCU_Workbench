"""Shared resource and label names for generated trigger protocol patterns."""

import re

from program_gen.core.run_sequence import LevelSequenceAction, SendCodeAction


def trigger_pattern_name(action: LevelSequenceAction | SendCodeAction) -> str:
    pin = _pin(action.pin)
    prefix = pin + '_' if action.explicit_pin else ''
    if isinstance(action, SendCodeAction):
        return prefix + 'Trigger_Send'
    if not re.fullmatch(r'[HL]+', action.levels):
        raise ValueError('Trigger levels must contain only H/L')
    duration = action.segment_duration_ns
    if not isinstance(duration, int) or duration <= 0:
        raise ValueError('Trigger duration must be a positive integer in ns')
    for scale, unit in ((1_000_000, 'mS'), (1_000, 'uS'), (1, 'nS')):
        if duration % scale == 0:
            return f'{prefix}Trigger_{action.levels}_{duration // scale}{unit}'
    raise AssertionError('unreachable duration')


def send_label(value: int) -> str:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 255:
        raise ValueError('Send code must be an integer from 0 to 255')
    return f'S{value:02X}'


def compare_pattern_name(pins: tuple[str, ...]) -> str:
    if not pins or len({pin.casefold() for pin in pins}) != len(pins):
        raise ValueError('Compare pins must be nonempty and distinct')
    return '_'.join(_pin(pin) for pin in pins) + '_Compare'


def compare_label(expected: tuple[str, ...]) -> str:
    if not expected or any(state not in ('H', 'L') for state in expected):
        raise ValueError('Compare states must contain only H/L')
    return ''.join(expected)


def _pin(pin: str) -> str:
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', pin):
        raise ValueError(f'Invalid pattern pin: {pin!r}')
    return pin
