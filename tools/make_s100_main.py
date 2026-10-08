# 把 S100_program/pattern.py 的主流程包装为 program_gen/platforms/s100/main.py 的 run()，
# pattern.py 退役为薄兼容入口。
import io

SRC = r"F:\01_work\99_Claude\06_Chroma_MCU_program\V1.1\S100_program\pattern.py"
DST = r"F:\01_work\99_Claude\06_Chroma_MCU_program\V1.1\program_gen\platforms\s100\main.py"

lines = io.open(SRC, encoding="utf-8", newline="").read().split("\n")

# 导入块：bootstrap 之后到 sys.excepthook 之前的 from program_gen 行
imports = [l for l in lines if l.startswith("from program_gen")]
# 主流程：G.init() 之后的所有内容
flow_at = lines.index("G.init()")
flow = lines[flow_at + 1:]
while flow and not flow[0].strip():
    flow.pop(0)
while flow and not flow[-1].strip():
    flow.pop()
indented = [("    " + l if l.strip() else l) for l in flow]

main_py = "\n".join([
    "# S100 平台主流程：按 FLOW 表生成各 CP 的 .prg/.sd/.hed/.prj/.tim 程序。",
    "import sys",
    "",
] + imports + [
    "",
    "",
    "def run(base_dir=None):",
    "    sys.excepthook = excel_error_backtrack",
    "    G.init(base_dir)",
    "",
] + indented) + "\n"
io.open(DST, "w", encoding="utf-8", newline="").write(main_py)

shim = """# 兼容入口：等价于在 V1.1 目录运行 python main.py --platform s100
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from program_gen.platforms.s100.main import run

run(os.path.dirname(os.path.abspath(__file__)))
"""
io.open(SRC, "w", encoding="utf-8", newline="").write(shim)
print("wrote main.py and shim")
