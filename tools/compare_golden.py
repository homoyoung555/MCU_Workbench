# 已验证 pattern（V1.1/temp，上机验证过的 golden）与生成产物（S100_program/pat_temp）逐拍比对。
# 归一化：去注释/标签/文件框架 → RPT 展开成逐拍 → 重新 RLE 折叠（对 RPT 分块方式不敏感）。
# 带命令的拍（TIMING_SET 等）单独成段，不参与折叠。
import io
import os
import re
import html
import difflib

ROOT = r"F:\01_work\99_Claude\06_Chroma_MCU_program\V1.1"
GOLD = ROOT + r"\temp"
GEN = ROOT + r"\S100_program\pat_temp"
OUT = ROOT + r"\验证pattern对比报告.html"

BITS_RE = re.compile(r"^([01XLHKC]+)")


def parse_sd(path):
    out = []
    in_body = False
    for raw in io.open(path, encoding="utf-8", errors="replace").read().replace("\r\n", "\n").split("\n"):
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
        rest = line[len(bits):].lstrip(";").strip().rstrip(";").strip()
        m2 = re.match(r"RPT\s+(\d+)$", rest)
        if m2:
            out.append((bits, "", int(m2.group(1))))
        elif rest:
            out.append((bits, rest, 1))
        else:
            out.append((bits, "", 1))
    return out


def canon(items):
    """RPT 展开后重新 RLE：返回 (规范化行列表, 总拍数)"""
    out = []
    total = 0
    for bits, cmd, n in items:
        total += n
        if cmd:
            out.append([bits, cmd, n])
        elif out and out[-1][0] == bits and not out[-1][1]:
            out[-1][2] += n
        else:
            out.append([bits, "", n])
    lines = [f"{b}{(' ' + c) if c else ''} x{k}" for b, c, k in out]
    return lines, total


def main():
    gold_files = sorted(f for f in os.listdir(GOLD) if f.endswith(".sd"))
    rows = []
    diffs = {}
    for fn in gold_files:
        gen_path = GEN + "\\" + fn
        if not os.path.isfile(gen_path):
            rows.append((fn, "生成侧缺失", "-", "-"))
            continue
        ga, na = canon(parse_sd(GOLD + "\\" + fn))
        gb, nb = canon(parse_sd(gen_path))
        if ga == gb:
            rows.append((fn, "一致", na, nb))
        else:
            rows.append((fn, "不一致", na, nb))
            diffs[fn] = list(difflib.unified_diff(
                ga, gb, fromfile="golden(temp)", tofile="generated(pat_temp)", lineterm="", n=2))

    same = sum(1 for r in rows if r[1] == "一致")
    parts = ["<!DOCTYPE html><html><head><meta charset='utf-8'><title>验证 pattern 对比报告</title>",
             "<style>body{font-family:Consolas,monospace;margin:24px;background:#fafafa}"
             "table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:4px 10px}"
             "th{background:#eee}.ok{color:#1a7f37}.bad{color:#c92a2a;font-weight:bold}"
             "pre{background:#fff;border:1px solid #ddd;padding:10px;overflow-x:auto}"
             ".add{color:#1a7f37}.del{color:#c92a2a}</style></head><body>",
             "<h1>验证 pattern（temp/）vs 生成产物（S100_program/pat_temp/）</h1>",
             f"<p>归一化逐拍比对（RPT 分块不敏感）。共 {len(rows)} 个文件，一致 {same}，不一致 {len(rows)-same}。</p>",
             "<table><tr><th>pattern</th><th>结论</th><th>golden 拍数</th><th>生成 拍数</th></tr>"]
    for fn, verdict, na, nb in rows:
        cls = "ok" if verdict == "一致" else "bad"
        parts.append(f"<tr><td>{fn}</td><td class='{cls}'>{verdict}</td><td>{na}</td><td>{nb}</td></tr>")
    parts.append("</table>")
    for fn, d in diffs.items():
        parts.append(f"<h2>{fn}</h2><pre>")
        for x in d[:200]:
            esc = html.escape(x)
            if x.startswith("+") and not x.startswith("+++"):
                parts.append(f"<span class='add'>{esc}</span>")
            elif x.startswith("-") and not x.startswith("---"):
                parts.append(f"<span class='del'>{esc}</span>")
            else:
                parts.append(esc)
        if len(d) > 200:
            parts.append(f"...（共 {len(d)} 行，截断）")
        parts.append("</pre>")
    parts.append("</body></html>")
    io.open(OUT, "w", encoding="utf-8", newline="").write("\n".join(parts))
    for fn, verdict, na, nb in rows:
        print(f"{verdict:4s} beats {str(na):>8s}/{str(nb):>8s}  {fn}")
    print("report ->", OUT)


if __name__ == "__main__":
    main()
