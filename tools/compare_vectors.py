# 跨平台向量一致性比对（用户确认的不变量）：
# 同一份 Excel 下，S100 的 .sd 与 Chroma 的 .pat 归一化后应逐拍一致。
# 允许差异：*…* 包裹 / S100 额外引脚列 / 时序集命名 / 标签写法 / 注释 / 文件框架。
# 归一化后仍存在的差异 = 某一侧生成逻辑的 bug。
import io
import os
import re
import difflib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # = V1.1（脚本相对，避免硬编码绝对路径）
S100_DIR = ROOT + r"\S100_program\pat_temp"
CHROMA_DIR = ROOT + r"\Chroma_program\pat_temp"
OUT = ROOT + r"\平台向量一致性报告.md"

TS_MAP = {  # chroma -> 统一名
    "TS1": "TS_NORMAL", "TS2": "TS_500K", "TS5": "TS_ERASE", "TS6": "TS_PGM",
    "TIMING_SET G1_1": "TS_NORMAL", "TIMING_SET G1_2": "TS_500K",
    "TIMING_SET G1_4": "TS_ERASE", "TIMING_SET G1_5": "TS_PGM",
}

BITS_RE = re.compile(r"^([01XLHKC]+)")


def norm_cmd(cmd):
    cmd = cmd.strip().rstrip(";").strip()
    if not cmd:
        return ""
    for k in sorted(TS_MAP, key=len, reverse=True):
        if cmd == k:
            return TS_MAP[k]
    m = re.match(r"RPT\s+(\d+)$", cmd)
    if m:
        return f"RPT {m.group(1)}"
    return cmd


def parse_chroma(text):
    out = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.split("//")[0].strip()
        if not line or line in ("{", "}"):
            continue
        m = re.match(r"^\*([01XLHKC]+)\*(.*)$", line)
        if m:
            cmd = norm_cmd(m.group(2))
            if cmd == "STOP":
                cmd = ""
            out.append((m.group(1), cmd))
    return out


def parse_s100(text):
    out = []
    in_body = False
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.split("//")[0].strip()
        if "@@PATTERN_DEFINE" in line:
            in_body = True
            continue
        if "@@END_PATTERN_DEFINE" in line:
            break
        if not in_body or not line:
            continue
        line = re.sub(r"^[A-Za-z0-9_]+:", "", line).strip()  # 去标签
        m = BITS_RE.match(line)
        if not m:
            continue
        bits = m.group(1)
        rest = line[len(bits):].lstrip(";").strip()
        if len(bits) >= 4:
            bits = bits[:3]  # 丢弃额外引脚列
        out.append((bits, norm_cmd(rest)))
    return out


def squash_first_last_ts(vec):
    # chroma 首向量带 TS_NORMAL 声明、S100 无：首拍命令为 TS_NORMAL 时忽略
    if vec and vec[0][1] == "TS_NORMAL":
        vec[0] = (vec[0][0], "")
    return vec


def expand_capture(vec):
    # capture 等价：S100 逐拍 1L1+PTN_TRIG ↔ Chroma 1K1+RPT n（K 位折叠），统一展开为 CAPTURE 拍
    out = []
    for bits, cmd in vec:
        if bits == "1L1" and cmd == "PTN_TRIG":
            out.append(("CAPTURE", ""))
        elif "K" in bits:
            m = re.match(r"RPT (\d+)$", cmd)
            out.extend([("CAPTURE", "")] * (int(m.group(1)) if m else 1))
        else:
            out.append((bits, cmd))
    return out


def main():
    s100 = {f[:-3] for f in os.listdir(S100_DIR) if f.endswith(".sd")}
    chroma = {f[:-4] for f in os.listdir(CHROMA_DIR) if f.endswith(".pat")}
    # NM_Data_Read 两平台用不同 capture 机制（chroma 单 nm_read+硬件循环 / s100 per-bank
    # fbist_capture_nm_bank+C 软件循环），向量本就不跨平台匹配，从 oracle 排除。
    _nm = lambda n: n == "nm_read" or n.startswith("fbist_capture_nm_bank")
    s100 = {n for n in s100 if not _nm(n)}
    chroma = {n for n in chroma if not _nm(n)}
    both = sorted(s100 & chroma)
    only_s, only_c = sorted(s100 - chroma), sorted(chroma - s100)

    same, diff = [], {}
    for name in both:
        a = expand_capture(squash_first_last_ts(parse_s100(io.open(
            S100_DIR + "\\" + name + ".sd", encoding="utf-8", errors="replace").read())))
        b = expand_capture(squash_first_last_ts(parse_chroma(io.open(
            CHROMA_DIR + "\\" + name + ".pat", encoding="utf-8", errors="replace").read())))
        if a == b:
            same.append(name)
        else:
            la = [f"{bits} {cmd}".strip() for bits, cmd in a]
            lb = [f"{bits} {cmd}".strip() for bits, cmd in b]
            d = list(difflib.unified_diff(la, lb, fromfile="s100", tofile="chroma", lineterm="", n=1))
            diff[name] = d

    lines = ["# 平台向量一致性报告（归一化后逐拍比对）", "",
             f"- 双方都有的 pattern: {len(both)}，其中一致 {len(same)}、不一致 {len(diff)}",
             f"- 仅 S100 有: {len(only_s)}  → {', '.join(only_s[:20])}",
             f"- 仅 Chroma 有: {len(only_c)}（多为旧 Excel 时代遗留）", ""]
    for name, d in diff.items():
        adds = sum(1 for x in d if x.startswith("+") and not x.startswith("+++"))
        dels = sum(1 for x in d if x.startswith("-") and not x.startswith("---"))
        lines.append(f"## {name}  (+{adds}/-{dels})")
        lines.append("```diff")
        lines.extend(d[:60])
        if len(d) > 60:
            lines.append(f"...（共 {len(d)} 行，截断）")
        lines.append("```")
        lines.append("")
    io.open(OUT, "w", encoding="utf-8", newline="").write("\n".join(lines))
    print(f"both={len(both)} same={len(same)} diff={len(diff)} onlyS100={len(only_s)} onlyChroma={len(only_c)}")
    print("report ->", OUT)


if __name__ == "__main__":
    main()
