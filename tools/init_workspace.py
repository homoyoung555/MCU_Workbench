"""Create the external V1.4 runtime workspace skeleton."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT))

from program_gen.workspace import WorkspaceLayout, WorkspaceLayoutError


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="初始化 V1.4 外部运行工作区")
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args(argv)
    try:
        layout = WorkspaceLayout(args.workspace, source_root=SOURCE_ROOT).create()
    except WorkspaceLayoutError as exc:
        parser.error(str(exc))
    print(layout.root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

