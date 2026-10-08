# 比对 Chroma pattern.py 的每个函数与 program_gen 中同名函数的源码是否完全一致
# （行尾归一化后逐字符比较）。一致 → 可直接 import 共享；不一致 → 留 chroma 本地。
import ast
import io
import glob

CHROMA = r"F:\01_work\99_Claude\06_Chroma_MCU_program\V1.1\Chroma_program\pattern.py"
PKG = r"F:\01_work\99_Claude\06_Chroma_MCU_program\V1.1\program_gen"


def funcs_of(path):
    src = io.open(path, encoding="utf-8", newline="").read().replace("\r\n", "\n")
    tree = ast.parse(src)
    out = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            out[node.name] = ast.get_source_segment(src, node)
    return out


core = {}
for p in glob.glob(PKG + r"\core\*.py") + [PKG + r"\state.py"]:
    for name, src in funcs_of(p).items():
        core[name] = (p.split("program_gen")[-1], src)

chroma = funcs_of(CHROMA)
same, diff, only = [], [], []
for name, src in chroma.items():
    if name in core:
        (same if core[name][1] == src else diff).append((name, core[name][0]))
    else:
        only.append(name)

print("== 与 core 完全一致（可去重共享）==")
for n, w in same:
    print(f"  {n}  <- {w}")
print("== 同名但内容不同（留 chroma 本地，Day 4 同步）==")
for n, w in diff:
    print(f"  {n}  vs {w}")
print(f"== Chroma 独有（{len(only)} 个）==")
print("  " + ", ".join(only))
