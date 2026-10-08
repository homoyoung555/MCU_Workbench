# 生成 Day 4 同步清单：chroma 本地旧版函数 vs core 新版（S100 逻辑）的逐函数 diff。
import ast
import difflib
import io
import glob

PKG = r"F:\01_work\99_Claude\06_Chroma_MCU_program\V1.1\program_gen"
OUT = r"F:\01_work\99_Claude\06_Chroma_MCU_program\V1.1\Day4同步清单.md"

TARGETS = {  # chroma 模块 -> core 模块
    r"\platforms\chroma\flash_seq.py": "core/flash_seq.py",
    r"\platforms\chroma\pattern_data.py": "core/pattern_data.py",
}


def funcs_of(path):
    src = io.open(path, encoding="utf-8", newline="").read().replace("\r\n", "\n")
    out = {}
    for node in ast.parse(src).body:
        if isinstance(node, ast.FunctionDef):
            seg = ast.get_source_segment(src, node)
            args = ast.unparse(node.args)
            out[node.name] = (args, seg)
    return out


lines = ["# Day 4 同步清单：Chroma 旧版 ←→ core 新版（S100 逻辑）",
         "",
         "同步方式：逐个函数把 chroma 本地旧版替换为 core 版本，每替换一个重新生成、",
         "记录产物 diff；产物的每处变化必须能对应到下面的代码差异，否则回退。",
         ""]

n = 0
for cmod, core_rel in TARGETS.items():
    chroma_funcs = funcs_of(PKG + cmod)
    core_funcs = funcs_of(PKG + "\\" + core_rel.replace("/", "\\"))
    for name, (cargs, csrc) in chroma_funcs.items():
        kargs, ksrc = core_funcs[name]
        n += 1
        lines.append(f"## {n}. `{name}`")
        lines.append(f"- chroma 旧签名: `{name}({cargs})`")
        lines.append(f"- core 新签名:   `{name}({kargs})`")
        diff = list(difflib.unified_diff(
            csrc.split("\n"), ksrc.split("\n"),
            fromfile=f"chroma/{name}", tofile=f"core/{name}", lineterm="", n=1))
        adds = sum(1 for d in diff if d.startswith("+") and not d.startswith("+++"))
        dels = sum(1 for d in diff if d.startswith("-") and not d.startswith("---"))
        lines.append(f"- 差异规模: +{adds} / -{dels} 行")
        lines.append("")
        lines.append("```diff")
        lines.extend(diff)
        lines.append("```")
        lines.append("")

io.open(OUT, "w", encoding="utf-8", newline="").write("\n".join(lines))
print(f"wrote {OUT} ({n} functions)")
