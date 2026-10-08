# 拼写修缮：只改标识符（NAME token），字符串/注释一律不碰。
# 字符串里的 "lable" 是 Excel 数据值与产物文本，绝不能改 —— 这就是不用文本替换的原因。
import sys
import io
import token
import tokenize
from pathlib import Path

SUBSTR_MAP = {
    "wirte": "write",
    "fllow": "flow",
    "rebulid": "rebuild",
    "trush": "trash",
    "lable": "label",
}


def fix_name(name):
    new = name
    for bad, good in SUBSTR_MAP.items():
        new = new.replace(bad, good)
    return new


def collect_names(paths):
    names = set()
    for p in paths:
        with open(p, "rb") as fh:
            for tok in tokenize.tokenize(fh.readline):
                if tok.type == token.NAME:
                    names.add(tok.string)
    return names


def rewrite(path):
    src = Path(path).read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)
    repls = []  # (row, col_start, col_end, new)
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == token.NAME:
            new = fix_name(tok.string)
            if new != tok.string:
                srow, scol = tok.start
                erow, ecol = tok.end
                assert srow == erow
                repls.append((srow, scol, ecol, new))
    if not repls:
        return 0
    for srow, scol, ecol, new in sorted(repls, reverse=True):
        line = lines[srow - 1]
        lines[srow - 1] = line[:scol] + new + line[ecol:]
    Path(path).write_text("".join(lines), encoding="utf-8", newline="")
    return len(repls)


def main():
    files = [str(p) for p in Path(sys.argv[1]).rglob("*.py")]
    # 碰撞检查按文件：同一文件内改名后的新名字不能与既有名字重合
    # （跨文件同名是不同作用域，如局部 trush 与 state 里的 trash）
    clashes = []
    for fp in files:
        names = collect_names([fp])
        for n in names:
            new = fix_name(n)
            if new != n and new in names:
                clashes.append((fp, n, new))
    if clashes:
        print("COLLISION:", clashes)
        sys.exit(1)
    total = 0
    for fp in files:
        n = rewrite(fp)
        if n:
            print(f"{n:5d}  {fp}")
        total += n
    print("total replacements:", total)


if __name__ == "__main__":
    main()
