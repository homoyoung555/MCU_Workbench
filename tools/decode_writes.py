# 把 .sd 向量解码成寄存器写序列：110 strobe + 111 之后取 7 拍地址 + 16 拍数据（中间引脚位）。
# 其余拍折叠为事件（TS 切换 / 长等待 / 读命令 100 / 期望拍 L/H/X）。
import io
import re
import sys

sys.path.insert(0, r"F:\01_work\99_Claude\06_Chroma_MCU_program\V1.1\tools")
from compare_golden import parse_sd


def beats(path):
    out = []
    for bits, cmd, n in parse_sd(path):
        if cmd:
            out.append((bits, cmd))
        out.extend([(bits, "")] * (n if not cmd else 0))
    return out


def decode(path):
    bs = beats(path)
    ev = []
    i = 0
    while i < len(bs):
        b, cmd = bs[i]
        if cmd:
            ev.append("[" + cmd + "]")
            i += 1
            continue
        if b == "110" and i + 1 < len(bs) and bs[i + 1][0] == "111" and not bs[i + 1][1]:
            seg = [x[0] for x in bs[i + 2:i + 2 + 23]]
            if len(seg) == 23 and all(len(x) == 3 and x[0] == "1" and x[2] == "1" for x in seg):
                addr = "".join(x[1] for x in seg[:7])
                data = "".join(x[1] for x in seg[7:])
                ev.append(f"WR a={int(addr,2):02X} d={int(data,2):04X}")
                i += 2 + 23
                continue
        # 非写段：折叠同值连续拍
        j = i
        while j < len(bs) and bs[j][0] == b and not bs[j][1]:
            j += 1
        ev.append(f"{b}x{j-i}")
        i = j
    # 合并相邻的纯过渡拍串，便于肉眼比较
    return ev


def main():
    a = decode(sys.argv[1])
    b = decode(sys.argv[2])
    import difflib
    print(f"golden events={len(a)}  gen events={len(b)}")
    for x in difflib.unified_diff(a, b, fromfile="golden", tofile="gen", lineterm="", n=2):
        print(x)


if __name__ == "__main__":
    main()
