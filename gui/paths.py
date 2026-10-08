"""Keep bundled application resources separate from the external workbook workspace."""
from pathlib import Path
import os
import sys

RESOURCE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = (Path(sys.executable).resolve().parent.parent
                if getattr(sys, 'frozen', False) else RESOURCE_ROOT)
WORKSPACE_ROOT = Path(os.environ.get('MCU_WORKBENCH_WORKSPACE') or
                      PROJECT_ROOT.parent / 'MCU_Workbench_WORKSPACE').expanduser().resolve()
