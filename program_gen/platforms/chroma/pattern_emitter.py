"""Render family-neutral Chroma pattern execution statements.

Business-family renderers decide *which* pattern runs and in what order.  This
module owns only Chroma's concrete TEST_NUM / datalog / JUDGE_PAT translation,
so callers never need to depend on another family's plan type.
"""

from __future__ import annotations

import re


_PATTERN_IDENTITY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ChromaPatternRenderError(ValueError):
    """A logical pattern identity cannot be emitted as a Chroma symbol."""


def emit_pattern_run(pattern_identity: str) -> tuple[str, ...]:
    """Return one complete Chroma pattern-run step, including its datalog row."""
    name = str(pattern_identity).strip()
    if not _PATTERN_IDENTITY.fullmatch(name):
        raise ChromaPatternRenderError(
            f"invalid Chroma pattern identity: {pattern_identity!r}"
        )
    return (
        "  TEST_NUM++;",
        f'  TEST_NO(TEST_NUM); DATALOG_MSG="{name}";',
        f"  JUDGE_PAT({name},__{name});",
        "",
    )
