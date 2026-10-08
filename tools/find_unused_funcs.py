# 修缮辅助：列出 program_gen 中定义后从未被引用的顶层函数。
# 注意：hex_* 系列调用被注释保留备用，属预期"未引用"。
import ast
import sys
from pathlib import Path

defs = {}  # name -> file
uses = set()
files = sorted(Path(sys.argv[1]).rglob("*.py")) + [Path(p) for p in sys.argv[2:]]
for fp in files:
    tree = ast.parse(fp.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            defs.setdefault(node.name, []).append(fp.name)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            uses.add(node.id)
        elif isinstance(node, ast.Attribute):
            uses.add(node.attr)
        elif isinstance(node, (ast.ImportFrom,)):
            for a in node.names:
                uses.add(a.name)

# def 本身不产生 Name 节点，调用/导入才会，所以 name not in uses 即未引用
for name, where in sorted(defs.items()):
    if name not in uses:
        print(f"{name}  <- {', '.join(where)}")
