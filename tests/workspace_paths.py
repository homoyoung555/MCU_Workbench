"""Shared paths for integration tests backed by the external workspace."""

from __future__ import annotations

import os
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = Path(
    os.environ.get("MCU_WORKBENCH_WORKSPACE") or SOURCE_ROOT.parent / "MCU_Workbench_WORKSPACE"
).resolve()
FORMAL_MASTER = (
    WORKSPACE_ROOT / "input" / "workbook" / "program_PCD009_V1.0.xlsx"
)
CHROMA_SEED_ROOT = WORKSPACE_ROOT / "input" / "chroma"
S100_SEED_ROOT = WORKSPACE_ROOT / "input" / "s100"
CHROMA_GOLDEN_ROOT = WORKSPACE_ROOT / "golden" / "legacy" / "Chroma_program"
S100_GOLDEN_ROOT = WORKSPACE_ROOT / "golden" / "legacy" / "S100_program"
