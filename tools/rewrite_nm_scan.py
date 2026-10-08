# 结构修缮：把 writers 里的 NM_PATTERN 线性扫描
#   for u in range(len(G.col("NM_PATTERN", "used"))):
#       if G.col("NM_PATTERN", "used")[u] == "X" (or == "Y" ...):
#           <体内用 G.col("NM_PATTERN", "Pattern name")[u].split(".")[0]>
# 改写为表序保持的字典式查询：
#   for nm_name in G.nm_patterns("X", "Y"):
#       <体内用 nm_name>
# 安全回退：条件不是纯等值 or 链、或替换后体内仍残留 [u]/NM_PATTERN 引用的位置不动。
import io
import re
import sys

FOR_RE = re.compile(r'^(\s*)for u in range\(len\(G\.col\("NM_PATTERN", "used"\)\)\):\s*$')
NAME_REF = re.compile(
    r'G\.col\("NM_PATTERN",\s*"Pattern name"\)\[\s*u\s*\]\s*\.split\("\."\)\[\s*0\s*\]', re.S)
COND_KEY = re.compile(r'G\.col\("NM_PATTERN", "used"\)\[\s*u\s*\]\s*==\s*"([^"]+)"', re.S)
PURE_COND = re.compile(
    r'^(?:G\.col\("NM_PATTERN", "used"\)\[\s*u\s*\]\s*==\s*"[^"]+"(?:\s+or\s+)?)+$', re.S)


def indent_of(line):
    return len(line) - len(line.lstrip(" "))


def transform(path):
    lines = io.open(path, encoding="utf-8", newline="").read().split("\n")
    out = []
    i = 0
    done = skipped = 0
    while i < len(lines):
        m = FOR_RE.match(lines[i])
        if not m:
            out.append(lines[i])
            i += 1
            continue
        base = m.group(1)
        # 收集 if 条件（可能折行：直到出现行尾冒号）
        j = i + 1
        cond_lines = []
        while j < len(lines):
            cond_lines.append(lines[j])
            if lines[j].rstrip().endswith(":"):
                break
            j += 1
        cond_text = "\n".join(cond_lines).strip()
        if not (cond_text.startswith("if ") and cond_text.endswith(":")):
            out.append(lines[i]); i += 1; skipped += 1; continue
        cond = cond_text[3:-1].strip()
        # 体 = if 之后所有缩进更深的行（空行随体）
        body_start = j + 1
        k = body_start
        if_indent = indent_of(lines[i]) + 4
        while k < len(lines):
            if lines[k].strip() == "":
                k += 1
                continue
            if indent_of(lines[k]) <= if_indent:
                break
            k += 1
        body = lines[body_start:k]
        # if 块必须覆盖整个 for 体（循环里有并列的第二个 if / else 时跳过，
        # 否则它们会被甩到循环外、u 失绑）
        for_indent = indent_of(lines[i])
        k2 = k
        while k2 < len(lines):
            if lines[k2].strip() == "":
                k2 += 1
                continue
            if indent_of(lines[k2]) <= for_indent:
                break
            k2 += 1
        if any(lines[t].strip() for t in range(k, k2)):
            out.append(lines[i]); i += 1; skipped += 1; continue
        # 仅处理纯等值 or 链
        if not PURE_COND.match(cond):
            out.append(lines[i]); i += 1; skipped += 1; continue
        keys = COND_KEY.findall(cond)
        new_body_text = NAME_REF.sub("nm_name", "\n".join(body))
        # 残留 [u] 或 NM_PATTERN 引用 → 回退
        if "[u]" in new_body_text or "NM_PATTERN" in new_body_text or re.search(r"\[\s*\n\s*u\s*\]", new_body_text):
            out.append(lines[i]); i += 1; skipped += 1; continue
        # 重排：for+if 两层并一层，体整体回退 4 空格
        key_args = ", ".join(f'"{x}"' for x in keys)
        out.append(f"{base}for nm_name in G.nm_patterns({key_args}):")
        for b in new_body_text.split("\n"):
            out.append(b[4:] if b.startswith("    ") else b)
        done += 1
        i = k
    io.open(path, "w", encoding="utf-8", newline="").write("\n".join(out))
    print(f"{path}: rewritten={done} skipped={skipped}")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        transform(p)
