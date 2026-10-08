# 性能修缮：把循环内反复全列转换的 list(G.<表>["<列>"]) 机械改写为缓存访问 G.col("表","列")。
# 仅匹配 8 个只读 sheet；list(G.X["c"][i]) 这类"单元格转 list"形态不会被误伤
# （正则要求 ] 后紧跟 )）。
import io
import re
import sys
from pathlib import Path

SHEETS = "FLOW|VERSION|ADDR_MAP|PIN_DEC_128|KP_RELAY|NM_PATTERN|FLASH_EPR|PATTERN"
PAT = re.compile(r'list\(G\.(' + SHEETS + r')\["([^"]+)"\]\)')


def main():
    total = 0
    for fp in Path(sys.argv[1]).rglob("*.py"):
        src = io.open(fp, encoding="utf-8", newline="").read()
        new, n = PAT.subn(lambda m: f'G.col("{m.group(1)}", "{m.group(2)}")', src)
        if n:
            io.open(fp, "w", encoding="utf-8", newline="").write(new)
            print(f"{n:5d}  {fp}")
        total += n
    print("total:", total)


if __name__ == "__main__":
    main()
