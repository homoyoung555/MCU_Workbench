"""从一份 V1.4 母本独立生成 Chroma pin.dec。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


SOURCE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SOURCE_ROOT))

from program_gen.pin_dec import compile_pin_map_generation_plan, generate_pin_dec
from program_gen.platform_program.facts import compile_platform_program_facts
from program_gen.render_plan import TargetKey
from program_gen.workbook import WorkbookReader


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", required=True, help="V1.4 Excel 母本路径")
    parser.add_argument("--cp", required=True, choices=("CP1", "CP2", "CP3"))
    parser.add_argument(
        "--variant", required=True, choices=("lab", "production")
    )
    parser.add_argument("--output", required=True, help="目标 pin.dec 文件路径")
    args = parser.parse_args(argv)

    workbook = WorkbookReader().read(Path(args.workbook))
    target = TargetKey("chroma", args.cp, args.variant, f"PIN_DEC_{args.cp}")
    facts = compile_platform_program_facts(workbook, target)
    content = generate_pin_dec(compile_pin_map_generation_plan(facts))

    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(content)
    print(f"[pin.dec] {args.cp}/{args.variant} sites={facts.site_count} -> {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
