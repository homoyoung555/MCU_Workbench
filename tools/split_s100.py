# 把 S100_program/pattern.py 的函数按架构切分到 program_gen 各模块。
# 自动：提取函数源码（含紧邻注释）、按用名生成 import、检测模块循环依赖、
#       重新生成只含主流程的 pattern.py。
import ast
import io
import sys
from collections import defaultdict

SRC = r"F:\01_work\99_Claude\06_Chroma_MCU_program\V1.1\S100_program\pattern.py"
PKG = r"F:\01_work\99_Claude\06_Chroma_MCU_program\V1.1\program_gen"

# 函数 → 目标模块
PLACEMENT = {
    "excel_error_backtrack": "core.errors",
    # 平台无关：flash 操作序列与配置
    "write_values": "core.flash_seq",
    "fold_binary": "core.flash_seq",
    "SEQ_1230": "core.flash_seq",
    "flash_erase": "core.flash_seq",
    "flash_program": "core.flash_seq",
    "flash_read": "core.flash_seq",
    "epr_pattern_capture": "core.flash_seq",
    "flash_pattern_dic_created": "core.flash_seq",
    "flash_mode_value_get": "core.flash_seq",
    "flash_pattern_get": "core.flash_seq",
    # 平台无关：pattern 与测试项的关联
    "pattern_testitem_merge_rname": "core.pattern_data",
    "pattern_testitem_merge_rpattern": "core.pattern_data",
    # S100：.sd pattern 文件生成
    "copy_file": "platforms.s100.pattern_files",
    "fbist_pattern_created": "platforms.s100.pattern_files",
    "fbist_pattern_get": "core.pattern_data",
    "fbist_mode_pattern_created": "platforms.s100.pattern_files",
    "flash_pattern_lable_created": "platforms.s100.pattern_files",
    "flash_test_pattern_created": "platforms.s100.pattern_files",
    # S100：.prg 测试项写出
    "Force_Judge": "platforms.s100.writers",
    "write_pat_mem": "platforms.s100.writers",
    "hex_code_item_write": "platforms.s100.writers",
    "set_all_final_vposp": "platforms.s100.writers",
    "temp_data_capture": "platforms.s100.writers",
    "sub_fllow_write": "platforms.s100.writers",
    "trim_item_write": "platforms.s100.writers",
    "verify_item_wirte": "platforms.s100.writers",
    "hex_pattern_write": "platforms.s100.writers",
    "hex_trim_item_write": "platforms.s100.writers",
    "hex_verify_item_wirte": "platforms.s100.writers",
    "trim_data_read_wirte": "platforms.s100.writers",
    "margin_write": "platforms.s100.writers",
    "os_wirte": "platforms.s100.writers",
    "main_write": "platforms.s100.writers",
    "vt_write": "platforms.s100.writers",
    "id_write": "platforms.s100.writers",
    "uid_write": "platforms.s100.writers",
    # S100：工程文件（.hed/.prj/.dec/.tim）与引脚映射
    "process_pin_name": "platforms.s100.project_files",
    "process_trace_name": "platforms.s100.project_files",
    "get_pin_data": "platforms.s100.project_files",
    "write_hed_file": "platforms.s100.project_files",
    "write_prj_file": "platforms.s100.project_files",
    "dec_file_created": "platforms.s100.project_files",
    "tim_hed_write": "platforms.s100.project_files",
    "TEST_PRO": "platforms.s100.project_files",
    "VCC_pin_rebulid": "platforms.s100.project_files",
    "get_filenames_with_os": "platforms.s100.project_files",
    "get_sd_filenames_with_os": "platforms.s100.project_files",
    # S100：.prg 程序框架
    "pln_file_created": "platforms.s100.startup",
    "item_variable_created": "platforms.s100.startup",
    "Hw_Sw_Bin": "platforms.s100.startup",
    "start_up_write": "platforms.s100.startup",
}

IMPORT_LINES = {
    "pd": "import pandas as pd",
    "shutil": "import shutil",
    "math": "import math",
    "np": "import numpy as np",
    "os": "import os",
    "openpyxl": "import openpyxl",
    "get_column_letter": "from openpyxl.utils import get_column_letter",
    "PatternFill": "from openpyxl.styles import PatternFill",
    "re": "import re",
    "base64": "import base64",
    "defaultdict": "from collections import defaultdict",
    "tempfile": "import tempfile",
    "lru_cache": "from functools import lru_cache",
    "sys": "import sys",
    "traceback": "import traceback",
}
ENCODING_FUNCS = {"process_dict", "dict_created", "bin_list_to_hex", "hex_to_bin_16bit",
                  "hex_to_Wbin_32bit", "hex_to_Rbin_32bit", "invert_hex_string",
                  "bin8_to_hex", "value_to_binary", "decimal_to_hex"}

MODULE_HEADER = {
    "core.errors": "# 全局异常处理：出错时反推 Excel 位置（平台无关）。",
    "core.flash_seq": "# flash 操作序列生成与 FLASH_EPR 配置解析（平台无关逻辑，输出格式当前为 S100 .sd 文本）。",
    "core.pattern_data": "# PATTERN 表与 FLOW 测试项的关联（平台无关）。",
    "platforms.s100.pattern_files": "# S100 平台：.sd pattern 文件生成。",
    "platforms.s100.writers": "# S100 平台：.prg 各类测试项写出。",
    "platforms.s100.project_files": "# S100 平台：.hed/.prj/.dec/.tim 工程文件与引脚映射。",
    "platforms.s100.startup": "# S100 平台：.prg 程序框架（变量声明、bin 定义、启动代码）。",
}


def main(dry_run):
    src = io.open(SRC, encoding="utf-8", newline="").read()
    lines = src.split("\n")
    tree = ast.parse(src)

    funcs = {}      # name -> (start_line, end_line) 1-based 闭区间，含紧邻前置注释
    order = []
    top_stmts = []
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
    missing = set(PLACEMENT) ^ set(funcs)
    assert not missing, f"映射与实际函数不一致: {missing}"

    # 每个函数使用到的名字
    def used_names(node):
        return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}

    func_nodes = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    uses = {name: used_names(func_nodes[name]) for name in funcs}

    # 模块依赖图（函数调用跨模块 → import 边）
    mod_funcs = defaultdict(list)
    for fn in order:
        mod_funcs[PLACEMENT[fn]].append(fn)
    edges = defaultdict(set)
    needs = defaultdict(lambda: defaultdict(set))  # module -> dep_module -> {func}
    for fn in order:
        mod = PLACEMENT[fn]
        for ref in uses[fn]:
            if ref in PLACEMENT and PLACEMENT[ref] != mod:
                edges[mod].add(PLACEMENT[ref])
                needs[mod][PLACEMENT[ref]].add(ref)

    # 简单环检测（DFS）
    state_ = {}
    cycle = []

    def dfs(m, stack):
        state_[m] = 1
        for d in edges[m]:
            if state_.get(d) == 1:
                cycle.append(stack + [d])
            elif d not in state_:
                dfs(d, stack + [d])
        state_[m] = 2

    for m in list(mod_funcs):
        if m not in state_:
            dfs(m, [m])
    if cycle:
        print("发现循环依赖:")
        for c in cycle:
            print("  " + " -> ".join(c))
        sys.exit(1)

    # 主流程 = G.init() 之后的非函数定义顶层语句
    flow_start = None
    for node in top_stmts:
        s = ast.dump(node)
        if "attr='init'" in s and "id='G'" in s:
            flow_start = node.end_lineno + 1
    first_stmt = min((n.lineno for n in top_stmts if n.lineno > flow_start), default=None)
    fs = first_stmt
    while fs > 1 and (lines[fs - 2].strip().startswith("#") or not lines[fs - 2].strip()):
        fs -= 1
    main_flow = "\n".join(lines[fs - 1:]).rstrip("\n") + "\n"

    if dry_run:
        print("模块依赖（无环）:")
        for m in sorted(mod_funcs):
            print(f"  {m}: {len(mod_funcs[m])} funcs, deps={sorted(edges[m])}")
        print(f"主流程从行 {fs} 开始, 共 {len(lines) - fs + 1} 行")
        return

    # 生成各模块文件
    for mod in mod_funcs:
        body_parts = ["\n".join(lines[funcs[fn][0] - 1:funcs[fn][1]]) for fn in mod_funcs[mod]]
        all_used = set().union(*(uses[fn] for fn in mod_funcs[mod]))
        imp = [IMPORT_LINES[k] for k in sorted(IMPORT_LINES) if k in all_used]
        enc = sorted(ENCODING_FUNCS & all_used)
        if enc:
            imp.append("from program_gen.core.encoding import " + ", ".join(enc))
        for dep in sorted(needs[mod]):
            imp.append(f"from program_gen.{dep} import " + ", ".join(sorted(needs[mod][dep])))
        if any("G." in p for p in body_parts):
            imp.append("from program_gen import state as G")
        path = PKG + "\\" + mod.replace(".", "\\") + ".py"
        text = MODULE_HEADER[mod] + "\n" + "\n".join(imp) + "\n\n\n" + "\n\n\n".join(body_parts) + "\n"
        io.open(path, "w", encoding="utf-8", newline="").write(text)
        print(f"wrote {path} ({len(mod_funcs[mod])} funcs)")

    # 重新生成 pattern.py：只保留入口与主流程
    flow_used = set()
    for node in top_stmts:
        if node.lineno >= fs:
            flow_used |= used_names(node)
    imp = [IMPORT_LINES[k] for k in sorted(IMPORT_LINES) if k in flow_used]
    enc = sorted(ENCODING_FUNCS & flow_used)
    if enc:
        imp.append("from program_gen.core.encoding import " + ", ".join(enc))
    by_mod = defaultdict(set)
    for ref in flow_used:
        if ref in PLACEMENT:
            by_mod[PLACEMENT[ref]].add(ref)
    new_lines = [
        "# Excel -> S100 ATE 测试程序生成（入口与主流程）。",
        "# 功能实现位于 program_gen 包：core（平台无关）+ platforms/s100（平台输出层）。",
        "import os",
        "import sys",
        "",
        "sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))",
        "from program_gen import state as G",
        "from program_gen.core.errors import excel_error_backtrack",
    ]
    new_lines += imp
    for dep in sorted(by_mod):
        new_lines.append(f"from program_gen.{dep} import " + ", ".join(sorted(by_mod[dep])))
    new_lines += ["", "sys.excepthook = excel_error_backtrack", "", "G.init()", "", ""]
    io.open(SRC, "w", encoding="utf-8", newline="").write("\n".join(new_lines) + main_flow)
    print(f"rewrote {SRC}")


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
