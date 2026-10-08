# 修缮辅助：列出每个模块中导入后从未引用的名字。
import ast
import sys
from pathlib import Path

for fp in sorted(Path(sys.argv[1]).rglob("*.py")):
    tree = ast.parse(fp.read_text(encoding="utf-8"))
    imported = {}  # name -> lineno
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                imported[(a.asname or a.name).split(".")[0]] = node.lineno
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                imported[a.asname or a.name] = node.lineno
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            pass  # 属性访问的根是 Name，已covered
    unused = {n: ln for n, ln in imported.items() if n not in used}
    if unused:
        print(fp.name + ":", ", ".join(f"{n}(L{ln})" for n, ln in sorted(unused.items(), key=lambda x: x[1])))
