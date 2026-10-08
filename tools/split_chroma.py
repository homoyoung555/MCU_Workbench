# 把 Chroma_program/pattern.py 切分到 program_gen/platforms/chroma/，
# 与 core 完全一致的函数直接去重（import core），主流程包装为 main.run()。
import ast
import io
from collections import defaultdict

SRC = r"F:\01_work\99_Claude\06_Chroma_MCU_program\V1.1\Chroma_program\pattern.py"
PKG = r"F:\01_work\99_Claude\06_Chroma_MCU_program\V1.1\program_gen"

# 与 core 逐字符一致（compare_chroma_core.py 验证），直接共享
DEDUPE = {
    "process_dict": "core.encoding", "dict_created": "core.encoding",
    "bin_list_to_hex": "core.encoding", "hex_to_bin_16bit": "core.encoding",
    "hex_to_Wbin_32bit": "core.encoding", "hex_to_Rbin_32bit": "core.encoding",
    "invert_hex_string": "core.encoding", "bin8_to_hex": "core.encoding",
    "decimal_to_hex": "core.encoding",
    "epr_pattern_capture": "core.flash_seq", "flash_pattern_dic_created": "core.flash_seq",
}

PLACEMENT = {
    # 与 core 同名但内容是旧版（Day 4 逐个与 core 对齐）
    "write_values": "platforms.chroma.flash_seq", "fold_binary": "platforms.chroma.flash_seq",
    "SEQ_1230": "platforms.chroma.flash_seq", "flash_erase": "platforms.chroma.flash_seq",
    "flash_program": "platforms.chroma.flash_seq", "flash_read": "platforms.chroma.flash_seq",
    "flash_mode_value_get": "platforms.chroma.flash_seq", "flash_pattern_get": "platforms.chroma.flash_seq",
    "pattern_testitem_merge_rname": "platforms.chroma.pattern_data",
    "pattern_testitem_merge_rpattern": "platforms.chroma.pattern_data",
    "fbist_pattern_get": "platforms.chroma.pattern_data",
    # Chroma 输出层
    "copy_file": "platforms.chroma.pattern_files",
    "fbist_pattern_created": "platforms.chroma.pattern_files",
    "flash_pattern_lable_created": "platforms.chroma.pattern_files",
    "flash_test_pattern_created": "platforms.chroma.pattern_files",
    "Force_Judge": "platforms.chroma.writers", "write_pat_mem": "platforms.chroma.writers",
    "hex_code_item_write": "platforms.chroma.writers", "set_all_final_vposp": "platforms.chroma.writers",
    "temp_data_capture": "platforms.chroma.writers", "sub_fllow_write": "platforms.chroma.writers",
    "trim_item_write": "platforms.chroma.writers", "verify_item_wirte": "platforms.chroma.writers",
    "hex_pattern_write": "platforms.chroma.writers", "hex_trim_item_write": "platforms.chroma.writers",
    "hex_verify_item_wirte": "platforms.chroma.writers", "trim_data_read_wirte": "platforms.chroma.writers",
    "margin_write": "platforms.chroma.writers", "os_wirte": "platforms.chroma.writers",
    "main_write": "platforms.chroma.writers", "vt_write": "platforms.chroma.writers",
    "id_write": "platforms.chroma.writers", "uid_write": "platforms.chroma.writers",
    "VCC_pin_rebulid": "platforms.chroma.project_files",
    "dec_file_created": "platforms.chroma.project_files",
    "pln_file_created": "platforms.chroma.startup", "item_variable_created": "platforms.chroma.startup",
    "Hw_Sw_Bin": "platforms.chroma.startup", "TEST_PRO": "platforms.chroma.startup",
    "start_up_write": "platforms.chroma.startup",
}

IMPORT_LINES = {
    "pd": "import pandas as pd", "shutil": "import shutil", "math": "import math",
    "np": "import numpy as np", "os": "import os", "openpyxl": "import openpyxl",
    "get_column_letter": "from openpyxl.utils import get_column_letter",
    "PatternFill": "from openpyxl.styles import PatternFill", "re": "import re",
    "base64": "import base64", "defaultdict": "from collections import defaultdict",
    "tempfile": "import tempfile", "lru_cache": "from functools import lru_cache",
    "sys": "import sys", "traceback": "import traceback",
}

MODULE_HEADER = {
    "platforms.chroma.flash_seq": "# Chroma 平台：flash 操作序列（旧版，与 core.flash_seq 同名函数逐个对齐中）。",
    "platforms.chroma.pattern_data": "# Chroma 平台：pattern 与测试项关联（旧版，与 core.pattern_data 对齐中）。",
    "platforms.chroma.pattern_files": "# Chroma 平台：.pat pattern 文件生成（SPM_PATTERN / *011* 时序向量格式）。",
    "platforms.chroma.writers": "# Chroma 平台：.pln 各类测试项写出。",
    "platforms.chroma.project_files": "# Chroma 平台：.dec 引脚文件与电源引脚处理。",
    "platforms.chroma.startup": "# Chroma 平台：.pln 程序框架（变量声明、bin 定义、启动代码、TEST_PRO）。",
}


def main():
    src = io.open(SRC, encoding="utf-8", newline="").read().replace("\r\n", "\n")
    lines = src.split("\n")
    tree = ast.parse(src)

    funcs, order, top_stmts = {}, [], []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            start = node.lineno
            if node.decorator_list:
                start = min(d.lineno for d in node.decorator_list)
            while start > 1 and lines[start - 2].strip().startswith("#"):
                start -= 1
            funcs[node.name] = (start, node.end_lineno)
            order.append(node.name)
        else:
            top_stmts.append(node)
    mapped = set(PLACEMENT) | set(DEDUPE)
    missing = mapped ^ set(funcs)
    assert not missing, f"映射与实际函数不一致: {missing}"

    func_nodes = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}

    def used_names(node):
        return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}

    uses = {name: used_names(func_nodes[name]) for name in funcs}

    def imports_for(all_used, self_mod):
        imp = [IMPORT_LINES[k] for k in sorted(IMPORT_LINES) if k in all_used]
        by_mod = defaultdict(set)
        for ref in all_used:
            tgt = DEDUPE.get(ref) or (PLACEMENT.get(ref) if PLACEMENT.get(ref) != self_mod else None)
            if tgt and tgt != self_mod:
                by_mod[tgt].add(ref)
        for dep in sorted(by_mod):
            imp.append(f"from program_gen.{dep} import " + ", ".join(sorted(by_mod[dep])))
        return imp

    # 环检测
    edges = defaultdict(set)
    for fn, mod in PLACEMENT.items():
        for ref in uses[fn]:
            tgt = PLACEMENT.get(ref)
            if tgt and tgt != mod:
                edges[mod].add(tgt)
    state_, cycles = {}, []

    def dfs(m, stack):
        state_[m] = 1
        for d in edges[m]:
            if state_.get(d) == 1:
                cycles.append(stack + [d])
            elif d not in state_:
                dfs(d, stack + [d])
        state_[m] = 2

    for m in set(PLACEMENT.values()):
        if m not in state_:
            dfs(m, [m])
    assert not cycles, f"循环依赖: {cycles}"

    # 模块文件
    mod_funcs = defaultdict(list)
    for fn in order:
        if fn in PLACEMENT:
            mod_funcs[PLACEMENT[fn]].append(fn)
    for mod, fns in mod_funcs.items():
        body = ["\n".join(lines[funcs[fn][0] - 1:funcs[fn][1]]) for fn in fns]
        all_used = set().union(*(uses[fn] for fn in fns))
        imp = imports_for(all_used, mod)
        if any("G." in b for b in body):
            imp.append("from program_gen import state as G")
        path = PKG + "\\" + mod.replace(".", "\\") + ".py"
        io.open(path, "w", encoding="utf-8", newline="").write(
            MODULE_HEADER[mod] + "\n" + "\n".join(imp) + "\n\n\n" + "\n\n\n".join(body) + "\n")
        print(f"wrote {path} ({len(fns)} funcs)")

    # 主流程 → platforms/chroma/main.py 的 run()
    init_end = None
    for node in top_stmts:
        d = ast.dump(node)
        if "attr='init'" in d and "id='G'" in d:
            init_end = node.end_lineno
    first = min(n.lineno for n in top_stmts if n.lineno > init_end)
    while first > 1 and (lines[first - 2].strip().startswith("#") or not lines[first - 2].strip()):
        first -= 1
    flow = lines[first - 1:]
    while flow and not flow[-1].strip():
        flow.pop()
    flow_used = set()
    for node in top_stmts:
        if node.lineno >= first:
            flow_used |= used_names(node)
    imp = imports_for(flow_used, None)
    main_py = "\n".join(
        ["# Chroma 平台主流程：按 FLOW 表生成各 CP 的 .pln/.pat 程序。", "import sys", ""]
        + imp + ["from program_gen import state as G", "", "",
                 "def run(base_dir=None):",
                 '    G.init(base_dir, platform="chroma")', ""]
        + [("    " + l if l.strip() else l) for l in flow]) + "\n"
    io.open(PKG + r"\platforms\chroma\main.py", "w", encoding="utf-8", newline="").write(main_py)
    print("wrote platforms/chroma/main.py")

    shim = (
        "# 兼容入口：等价于在 V1.1 目录运行 python main.py --platform chroma\n"
        "import os\nimport sys\n\n"
        "sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\n"
        "from program_gen.platforms.chroma.main import run\n\n"
        "run(os.path.dirname(os.path.abspath(__file__)))\n")
    io.open(SRC, "w", encoding="utf-8", newline="").write(shim)
    print("rewrote pattern.py as shim")


if __name__ == "__main__":
    main()
