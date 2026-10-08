# TEST_PRO 调度表 vs 函数定义 交叉核对（Chroma .pln，独立工具，不 import 生成器）。
#
# 背景：TEST_PRO 调度表（"<Name> ? : #C(hw_<Name>,sw_<Name>);"）由遍历 FLOW.item 的通用
# 逻辑生成，与各 writer（trim_item_write/verify_item_write/...）按精确字符串匹配写函数体
# 是两条独立路径——若某个 item 因为跨表拼写不一致（如 FLOW="MR_Trim" vs pattern="Mr_Trim"，
# 2026-07-03 真实踩过）等原因导致 writer 匹配失败，TEST_PRO 仍会正常生成调度行、全局变量
# 声明也照常生成，唯独函数体缺失——本地生成/编译都不报错（CRAFT 不检查这类符号是否真实
# 存在，同 JUDGE_PAT/WRITE_PAT_MEM 标签引用不被检查的道理），直到上机才暴露。
#
# 用法：python tools/check_test_functions.py <程序文件夹（含一个 .pln）>
import os
import re
import sys

# TEST_PRO{...} 块内的调度行：形如 "  Mr_Trim   ?    : #C(hw_Mr_Trim ,sw_Mr_Trim );"
# 取行首非空白 token 作为测试项名；跳过注释行（"//" 开头，如被 both_m 注释掉的 Dac_Loop）
# 与 BEFORE_TEST/AFTER_TEST 控制行。
_DISPATCH_RE = re.compile(r"^(\S+)\s+\?")
# 函数定义：独立一行 "<Name>()"，下一行紧跟 "{"（与项目内全部 writer 的输出格式一致）。
_FUNC_DEF_RE = re.compile(r"^(\w+)\(\)\s*\n\{", re.M)


def check_pln(pln_path):
    """返回 (dispatched, missing)：调度表引用的全部测试项名 与 其中缺函数定义的子集。"""
    with open(pln_path, encoding="utf-8", errors="replace") as f:
        text = f.read()

    m = re.search(r"TEST_PRO\{(.*?)\n\}", text, re.S)
    if not m:
        return [], []
    block = m.group(1)

    dispatched = []
    for line in block.splitlines():
        line = line.strip()
        if not line or line.startswith("//") or line.startswith("BEFORE_TEST") or line.startswith("AFTER_TEST"):
            continue
        dm = _DISPATCH_RE.match(line)
        if dm:
            dispatched.append(dm.group(1))

    defined = set(_FUNC_DEF_RE.findall(text))
    missing = [name for name in dispatched if name not in defined]
    return dispatched, missing


def check_folder(folder):
    """在程序文件夹里找 .pln 并核对；供 verify_all.py 等程序化调用。
    回 (dispatched, missing)；文件夹下没有 .pln 时回 (None, None)。"""
    plns = [f for f in os.listdir(folder) if f.endswith(".pln")]
    if not plns:
        return None, None
    return check_pln(os.path.join(folder, plns[0]))


def main(argv):
    if len(argv) < 1:
        print("用法: check_test_functions.py <程序文件夹>")
        return 1
    folder = argv[0]
    dispatched, missing = check_folder(folder)
    if dispatched is None:
        print(f"[提示] {folder} 下没找到 .pln")
        return 1
    print(f"程序: {os.path.basename(os.path.normpath(folder))}")
    print(f"TEST_PRO 调度项总数: {len(dispatched)}")
    if missing:
        print(f"\n缺函数定义的调度项（{len(missing)} 个，母本 item 名多半跨表拼写不一致）：")
        for name in missing:
            print(f"  {name}")
        return 1
    print("\n所有调度项均在同一 .pln 中找到对应函数定义（0 缺失）。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
