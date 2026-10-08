# 缩进归一：s100 .prg 写出层（writers.py/startup.py）模板字符串里的行首空格 → TAB。
# 规则：\n 转义后的空白串中，t 个 TAB + s 个空格 → (t + max(1,(s+2)//4)) 个 TAB（s>0 时）。
# 仅处理 .prg 文本的写出文件；.prj/.tim/.hed/.sd 的列对齐字符串不在范围内。
import io
import re
import sys


def repl(m):
    ws = m.group(1)
    t = ws.count("\t")
    s = ws.count(" ")
    n = t + (max(1, (s + 2) // 4) if s else 0)
    return "\\n" + "\t" * n


def pass_escaped_newline(src):
    # 源码中的 \n 转义（非 \\n，即非 C 目标换行）后跟的字面空白
    return re.subn(r"(?<!\\)\\n([ \t]*[ ][ \t]*)(?=\S)", repl, src)


def pass_write_leading(src):
    # f.write("   xxx...") 形式：字符串起始处的 >=2 个空格
    def r(m):
        ws = m.group(2)
        t = ws.count("\t")
        s = ws.count(" ")
        n = t + max(1, (s + 2) // 4)
        return m.group(1) + "\t" * n
    return re.subn(r"(f\.write\(\s*[fr]?['\"])([ ]{2,}[\t ]*)(?=[^ \t])", r, src)


def main():
    for fp in sys.argv[1:]:
        src = io.open(fp, encoding="utf-8", newline="").read()
        src, n1 = pass_escaped_newline(src)
        src, n2 = pass_write_leading(src)
        io.open(fp, "w", encoding="utf-8", newline="").write(src)
        print(f"{fp}: newline-indents={n1} write-leading={n2}")


if __name__ == "__main__":
    main()
