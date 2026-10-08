"""Platform-neutral parser for native ``RUN_SEQUENCE`` step syntax."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import TypeVar


DEFAULT_SEGMENT_DURATION_NS = 5_000_000
_LEVEL_RE = re.compile(r"[HL]+")
_DURATION_RE = re.compile(r"(\d+)(ns|us|ms)", re.IGNORECASE)
_DURATION_SCALE_NS = {"ns": 1, "us": 1_000, "ms": 1_000_000}


class RunSequenceCompileError(ValueError):
    """A native RUN_SEQUENCE step violates the shared syntax contract."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        line: int | None = None,
        token: int | None = None,
    ):
        self.code = code
        self.line = line
        self.token = token
        location = ""
        if line is not None:
            location += f" line {line}"
        if token is not None:
            location += f" token {token}"
        super().__init__(f"{code}:{location}: {message}")


@dataclass(frozen=True, slots=True)
class LevelSequenceAction:
    pin: str
    levels: str
    segment_duration_ns: int
    explicit_pin: bool = False


@dataclass(frozen=True, slots=True)
class SendCodeAction:
    pin: str
    value: int
    explicit_pin: bool = False


@dataclass(frozen=True, slots=True)
class WaitAction:
    duration_ms: int


@dataclass(frozen=True, slots=True)
class ForceStopAction:
    pass


@dataclass(frozen=True, slots=True)
class RepowerAction:
    pass


NativeRunSequenceAction = (
    LevelSequenceAction
    | SendCodeAction
    | WaitAction
    | ForceStopAction
    | RepowerAction
)
ForceActionT = TypeVar("ForceActionT")


def parse_run_sequence_step(
    step: object,
    default_pin: str,
    *,
    force_action: ForceActionT | None = None,
    dynamic_code: int | None = None,
) -> tuple[NativeRunSequenceAction | ForceActionT, ...]:
    return _parse_run_sequence_step(
        step, default_pin, force_action=force_action, dynamic_code=dynamic_code
    )


def parse_run_sequence_template(step: object, default_pin: str) -> tuple[tuple, tuple]:
    """Split one insertion X after parsing, retaining pin scope on both sides."""
    slot = object()
    actions = _parse_run_sequence_step(step, default_pin, template_slot=slot)
    positions = [index for index, action in enumerate(actions) if action is slot]
    if len(positions) != 1:
        raise RunSequenceCompileError(
            'RUN_SEQUENCE.TEMPLATE_X_REQUIRED', '模板必须含且只含一个 X'
        )
    index = positions[0]
    return actions[:index], actions[index + 1:]


def _parse_run_sequence_step(
    step, default_pin, *, force_action=None, dynamic_code=None, template_slot=None
):
    """Compile ordered native step tokens without inferring FLOW business data.

    Each token may override its line's current pin with ``<PIN>:``. ``F``
    inserts the already-typed action supplied by the caller; this parser never
    classifies UNIT/FV-FI data.  ``X`` similarly requires an explicit code.
    """
    raw = "" if step is None else str(step).strip()
    if raw in ("", "/"):
        return ()

    actions: list[NativeRunSequenceAction | ForceActionT] = []
    for line_number, raw_line in enumerate(raw.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        pin, explicit_pin = str(default_pin).strip(), False
        tokens = line.split("-")
        index = 0
        while index < len(tokens):
            token_number = index + 1
            token = tokens[index].strip()
            if ":" in token:
                pin, token = (part.strip() for part in token.split(":", 1))
                explicit_pin = True
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", pin):
                    raise RunSequenceCompileError(
                        "RUN_SEQUENCE.PIN_REQUIRED", "显式 Pin 必须是有效标识符",
                        line=line_number, token=token_number,
                    )
                if not token:
                    raise RunSequenceCompileError(
                        "RUN_SEQUENCE.LINE_EMPTY", "Pin 前缀后必须有 token",
                        line=line_number, token=token_number,
                    )
            if not pin:
                raise RunSequenceCompileError(
                    "RUN_SEQUENCE.DEFAULT_PIN_REQUIRED", "未带 Pin 前缀的 step 行需要 default_pin",
                    line=line_number, token=token_number,
                )
            if token == "T":
                raise RunSequenceCompileError(
                    "RUN_SEQUENCE.TERMINAL_TOKEN_FORBIDDEN",
                    "Native RUN_SEQUENCE 使用显式 JUDGE/Capture，禁止 Legacy T",
                    line=line_number,
                    token=token_number,
                )
            if _LEVEL_RE.fullmatch(token):
                duration_ns = DEFAULT_SEGMENT_DURATION_NS
                if index + 1 < len(tokens):
                    parsed_duration = _duration_ns(
                        tokens[index + 1], line_number, token_number + 1
                    )
                    if parsed_duration is not None:
                        duration_ns = parsed_duration
                        index += 1
                actions.append(LevelSequenceAction(pin, token, duration_ns, explicit_pin))
            elif token.isdigit():
                actions.append(SendCodeAction(pin, _code_value(token, line_number, token_number), explicit_pin))
            elif token == "X":
                if template_slot is not None:
                    actions.append(template_slot)
                    index += 1
                    continue
                if dynamic_code is None:
                    raise RunSequenceCompileError(
                        "RUN_SEQUENCE.DYNAMIC_CODE_REQUIRED",
                        "X 必须由调用方显式绑定动态码值",
                        line=line_number,
                        token=token_number,
                    )
                actions.append(
                    SendCodeAction(
                        pin,
                        _code_value(dynamic_code, line_number, token_number),
                        explicit_pin,
                    )
                )
            elif token.startswith("W") and token[1:].isdigit():
                duration_ms = int(token[1:])
                if duration_ms <= 0:
                    raise RunSequenceCompileError(
                        "RUN_SEQUENCE.DURATION_INVALID",
                        "W 等待时长必须大于 0ms",
                        line=line_number,
                        token=token_number,
                    )
                actions.append(WaitAction(duration_ms))
            elif token == "F":
                if force_action is None:
                    raise RunSequenceCompileError(
                        "RUN_SEQUENCE.FORCE_ACTION_REQUIRED",
                        "F 必须由上层提供已分类的 typed force action",
                        line=line_number,
                        token=token_number,
                    )
                actions.append(force_action)
            elif token == "FS":
                actions.append(ForceStopAction())
            elif token == "RP":
                actions.append(RepowerAction())
            else:
                raise RunSequenceCompileError(
                    "RUN_SEQUENCE.TOKEN_UNKNOWN",
                    f"无法识别 token {token!r}",
                    line=line_number,
                    token=token_number,
                )
            index += 1
    return tuple(actions)


def _duration_ns(value: object, line: int, token: int) -> int | None:
    match = _DURATION_RE.fullmatch(str(value).strip())
    if match is None:
        return None
    duration_ns = int(match.group(1)) * _DURATION_SCALE_NS[match.group(2).lower()]
    if duration_ns <= 0:
        raise RunSequenceCompileError(
            "RUN_SEQUENCE.DURATION_INVALID",
            "电平段时长必须大于 0",
            line=line,
            token=token,
        )
    return duration_ns


def _code_value(value: object, line: int, token: int) -> int:
    code = (
        value
        if isinstance(value, int) and not isinstance(value, bool)
        else int(value)
        if isinstance(value, str) and value.isdigit()
        else -1
    )
    if not 0 <= code <= 255:
        raise RunSequenceCompileError(
            "RUN_SEQUENCE.CODE_OUT_OF_RANGE",
            "发送码必须是 0..255 的整数",
            line=line,
            token=token,
        )
    return code
