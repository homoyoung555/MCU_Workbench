"""临时：交叉核对 Chroma 单个程序里 .pln 的 WRITE_PAT_MEM 引用 vs pat/ 下 .pat 的标签定义。
用法: python tools/check_pln_labels.py <程序目录>
输出：引用了但在对应 .pat 里找不到定义的 (模块:标签) 清单。
"""
import os
import re
import sys
import glob

prog_dir = sys.argv[1]

# 1) 收集每个 .pat 模块定义的标签集合：模块名=文件名(去 .pat)
pat_labels = {}  # module -> set(label)
for pat in glob.glob(os.path.join(prog_dir, "pat", "*.pat")):
    mod = os.path.splitext(os.path.basename(pat))[0]
    labels = set()
    with open(pat, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            # 标签定义行形如  "   flash_op0_w_p_st:"（行内仅标签+冒号）
            m = re.match(r"\s*([A-Za-z_][\w]*)\s*:\s*$", line)
            if m:
                labels.add(m.group(1))
    pat_labels[mod] = labels

# 2) 扫描 .pln 的 WRITE_PAT_MEM 引用： 模块:标签[+偏移]
ref_re = re.compile(r"WRITE_PAT_MEM\([^,]+,[^,]+,\s*([A-Za-z_][\w]*)\s*:\s*([A-Za-z_][\w]*)")
missing = {}   # (module,label) -> 次数
mod_absent = {}  # 模块文件根本不存在
total_refs = 0
for pln in glob.glob(os.path.join(prog_dir, "*.pln")):
    with open(pln, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = ref_re.search(line)
            if not m:
                continue
            total_refs += 1
            mod, label = m.group(1), m.group(2)
            if mod not in pat_labels:
                mod_absent[mod] = mod_absent.get(mod, 0) + 1
                continue
            if label not in pat_labels[mod]:
                missing[(mod, label)] = missing.get((mod, label), 0) + 1

print(f"程序: {os.path.basename(prog_dir.rstrip(os.sep))}")
print(f"WRITE_PAT_MEM 引用总数: {total_refs}")
print(f".pat 模块数: {len(pat_labels)}")
print()

if mod_absent:
    print("== 引用的 .pat 模块文件不存在 ==")
    for mod, n in sorted(mod_absent.items()):
        print(f"  [缺模块] {mod}  (x{n})")
    print()

if missing:
    print("== 模块存在、但标签未定义（引用 vs .pat 对不上）==")
    for (mod, label), n in sorted(missing.items()):
        print(f"  {mod}:{label}  (x{n})")
    print(f"\n不匹配标签种类: {len(missing)}")
else:
    print("所有引用标签均在对应 .pat 中找到定义（0 未匹配）。")
