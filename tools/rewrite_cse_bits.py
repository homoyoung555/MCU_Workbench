# 结构修缮：公共子表达式提取（CSE）。
# 形态：for j in range(len(hex_to_Wbin_32bit(<EXPR>))):
#           ... hex_to_Wbin_32bit(<EXPR>)[j] ...   ← 每拍重算
# 改为：wbits = hex_to_Wbin_32bit(<EXPR>)
#       for j in range(len(wbits)):
#           ... wbits[j] ...
# 提升点 = 原循环头求值处（分支保护语义不变）；体内仅替换与头部完全相同的
# 表达式（允许空白差异）。
import io
import re
import sys

HEAD_RE = re.compile(r"^(\s*)for (\w+) in range\(len\((hex_to_[WR]bin_32bit\()")


def balanced_expr(text, start):
    """从 start（指向函数名起点）截取括号配平的完整调用表达式。"""
    i = text.index("(", start)
    depth = 0
    for k in range(i, len(text)):
        if text[k] == "(":
            depth += 1
        elif text[k] == ")":
            depth -= 1
            if depth == 0:
                return text[start:k + 1]
    raise ValueError("unbalanced")


def flexible_pattern(expr):
    """表达式 → 空白容忍的正则。"""
    pat = re.escape(re.sub(r"\s+", " ", expr.strip()))
    pat = pat.replace(r"\ ", r"\s*")
    pat = pat.replace(r"\+", r"\s*\+\s*")
    return re.compile(pat, re.S)


def indent_of(line):
    return len(line) - len(line.lstrip(" "))


def transform(path):
    lines = io.open(path, encoding="utf-8", newline="").read().split("\n")
    out = []
    i = 0
    done = 0
    while i < len(lines):
        m = HEAD_RE.match(lines[i])
        if not m:
            out.append(lines[i])
            i += 1
            continue
        indent, loop_var = m.group(1), m.group(2)
        try:
            expr = balanced_expr(lines[i], lines[i].index("hex_to_"))
        except ValueError:
            out.append(lines[i]); i += 1; continue
        # 循环头必须形如 for X in range(len(EXPR)):
        expected = f"{indent}for {loop_var} in range(len({expr})):"
        if lines[i].rstrip() != expected:
            out.append(lines[i]); i += 1; continue
        var = "wbits" if "_Wbin_" in expr else "rbits"
        # 体范围
        k = i + 1
        while k < len(lines):
            if lines[k].strip() == "":
                k += 1
                continue
            if indent_of(lines[k]) <= len(indent):
                break
            k += 1
        body = "\n".join(lines[i + 1:k])
        pat = flexible_pattern(expr)
        new_body, n = pat.subn(var, body)
        out.append(f"{indent}{var} = {expr}")
        out.append(f"{indent}for {loop_var} in range(len({var})):")
        out.extend(new_body.split("\n"))
        done += 1
        i = k
    io.open(path, "w", encoding="utf-8", newline="").write("\n".join(out))
    print(f"{path}: hoisted={done}")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        transform(p)
