# -*- coding: utf-8 -*-
"""生成器总控台（TUI）—— 选母本 → 校验 / 生成 / 编译，一个菜单串起三个能力。

风格对齐 Chroma_Compiler / S100_Compiler 的菜单式编译器：编号菜单、UTF-8 输出、
操作完停顿返回。本程序自己不碰 pandas，只用标准库当**编排壳**，三个能力都靠子进程调
现成 CLI（隔离、稳、无全局/chdir 污染）：
  - 校验：tools/check_master.py <母本>            （preflight，出控制台+HTML 报告）
  - 生成：main.py --platform <X> --master <母本> [--cp CPn] [--variant lab|production]
          （可只生成某个 CP / 某个版本；全量重生成时会先自动清理旧产物，避免 'a' 追写翻倍——
          只生成部分 CP/版本时不清理，避免误删没选中的其它程序）
  - 编译：tools/chroma_compiler.py -r <root>（全部）或 -p <program>（单个程序）
          / tools/s100_compiler.py 同上

用法：双击 启动生成器.bat（用 .venv 的 python 跑本文件）；或 <python> console.py。
"""
import io
import os
import shutil
import subprocess
import sys

# stdout/stderr 统一 UTF-8（启动脚本已 chcp 65001；默认 cp936 会让中文/子进程输出乱码）
for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8")
    except Exception:
        try:
            setattr(sys, _s, io.TextIOWrapper(getattr(sys, _s).buffer, encoding="utf-8"))
        except Exception:
            pass

REPO = os.path.dirname(os.path.abspath(__file__))          # V1.1 目录
PY = sys.executable                                        # 用当前解释器跑子进程（bat 指定 .venv）
TEST_DATA = os.path.join(REPO, "test_data")
PRODUCT_ROOT = {"s100": os.path.join(REPO, "S100_program"),
                "chroma": os.path.join(REPO, "Chroma_program")}
# 清理生成产物时保留的子目录（种子 pattern / fbist / 手写 code），其余子目录（LAB + 各程序文件夹）删除
KEEP_DIRS = {"pat_temp", "fbist_pattern", "code"}

BANNER = """\
==============================================
  MCU 测试程序 生成器总控台
  母本(Excel) → 校验 / 生成 / 编译
=============================================="""


def _pause():
    try:
        input("\n按 Enter 返回菜单...")
    except EOFError:
        pass


def find_masters():
    """列出 test_data 下的母本 .xlsx/.xlsm（跳过 Excel 临时锁文件 ~$）。"""
    if not os.path.isdir(TEST_DATA):
        return []
    out = []
    for f in sorted(os.listdir(TEST_DATA)):
        if f.startswith("~$"):
            continue
        if f.endswith(".xlsx") or f.endswith(".xlsm"):
            out.append(f)
    return out


def master_abspath(master):
    """把「传给 --master 的值」解析成校验用的绝对路径：绝对路径原样，文件名拼到 test_data。"""
    return master if os.path.isabs(master) else os.path.join(TEST_DATA, master)


def choose_master():
    """列 test_data 母本让用户选，或手动输入任意路径；回选中的值
    （test_data 内=文件名 / 外部=绝对路径）或 None。"""
    masters = find_masters()
    print("\ntest_data 下的母本：" if masters else f"\n[提示] {TEST_DATA} 下暂无 .xlsx/.xlsm 母本。")
    for i, m in enumerate(masters, 1):
        print(f"  [{i}] {m}")
    print("  [M] 手动输入母本完整路径（可在 test_data 之外任意位置）")
    print("  [0] 返回")
    sel = input("选择母本编号（或 M）: ").strip()
    if sel.lower() == "m":
        p = input("母本完整路径（文件或文件夹）: ").strip().strip('"')
        if not p:
            return None
        if os.path.isdir(p):
            # 贴的是文件夹 → 找里面的 .xlsx/.xlsm（跳过 Excel 锁文件 ~$）
            xs = sorted(f for f in os.listdir(p)
                        if not f.startswith("~$") and (f.endswith(".xlsx") or f.endswith(".xlsm")))
            if not xs:
                print(f"  [提示] 该文件夹里没有 .xlsx/.xlsm: {p}")
                _pause()
                return None
            if len(xs) == 1:
                return os.path.abspath(os.path.join(p, xs[0]))
            print(f"\n{p} 里有多个母本：")
            for i, x in enumerate(xs, 1):
                print(f"  [{i}] {x}")
            print("  [0] 返回")
            s2 = input("选择编号: ").strip()
            if not s2.isdigit() or int(s2) == 0 or int(s2) > len(xs):
                return None
            return os.path.abspath(os.path.join(p, xs[int(s2) - 1]))
        if not os.path.isfile(p):
            print(f"  [提示] 找不到文件或文件夹: {p}")
            _pause()
            return None
        return os.path.abspath(p)
    if not sel.isdigit():
        return None
    n = int(sel)
    if n == 0 or n > len(masters):
        return None
    return masters[n - 1]


def choose_platform():
    print("\n选择平台：")
    print("  [1] chroma")
    print("  [2] s100")
    print("  [0] 返回")
    sel = input("选择: ").strip()
    return {"1": "chroma", "2": "s100"}.get(sel)


def choose_cp():
    """返回 "CP1"/"CP2"/"CP3"（只生成/编译该 CP）、"ALL"（全部 CP）、或 None（取消）。"""
    print("\n选择 CP：")
    print("  [1] CP1")
    print("  [2] CP2")
    print("  [3] CP3")
    print("  [A] 全部 CP")
    print("  [0] 返回")
    sel = input("选择: ").strip().upper()
    if sel == "A":
        return "ALL"
    return {"1": "CP1", "2": "CP2", "3": "CP3"}.get(sel)


def choose_variant():
    """返回 "lab"/"production"/"both"，或 None（取消）。"""
    print("\n选择版本：")
    print("  [1] LAB 单 site 版")
    print("  [2] 量产多 site 版")
    print("  [3] 都要")
    print("  [0] 返回")
    sel = input("选择: ").strip()
    return {"1": "lab", "2": "production", "3": "both"}.get(sel)


def list_program_dirs(platform, cp=None, variant=None):
    """扫描磁盘上已存在的程序文件夹（可选按 CP/variant 过滤），返回 [(展示名, 绝对路径), ...]。
    LAB 版在 <root>/LAB/CHROMA 或 <root>/LAB/S100 子目录下，量产版在 <root> 顶层
    （顶层需排除 LAB 目录本身与 KEEP_DIRS 这些非程序子目录）。"""
    root = PRODUCT_ROOT[platform]
    lab_sub = "CHROMA" if platform == "chroma" else "S100"
    lab_root = os.path.join(root, "LAB", lab_sub)
    skip = KEEP_DIRS | {"LAB"}
    out = []

    def _scan(base, tag):
        if not os.path.isdir(base):
            return
        for name in sorted(os.listdir(base)):
            if name in skip:
                continue
            p = os.path.join(base, name)
            if not os.path.isdir(p):
                continue
            cp_suffix = name.split("_")[-1]
            if cp and cp not in ("ALL", None) and cp_suffix != cp:
                continue
            out.append((f"[{tag}] {name}", os.path.abspath(p)))

    if variant in (None, "both", "production"):
        _scan(root, "量产")
    if variant in (None, "both", "lab"):
        _scan(lab_root, "LAB")
    return out


def choose_compile_scope(platform):
    """[1] 全部编译 [2] 选择单个程序 [0] 返回。返回 "all" / 绝对路径 / None（取消）。"""
    print("\n编译范围：")
    print("  [1] 全部编译（自动发现该平台所有程序）")
    print("  [2] 选择单个程序")
    print("  [0] 返回")
    sel = input("选择: ").strip()
    if sel == "1":
        return "all"
    if sel == "2":
        progs = list_program_dirs(platform)
        if not progs:
            print("  [提示] 还没有已生成的程序，请先生成。")
            return None
        print()
        for i, (label, _) in enumerate(progs, 1):
            print(f"  [{i}] {label}")
        print("  [0] 返回")
        s2 = input("选择编号: ").strip()
        if not s2.isdigit() or int(s2) == 0 or int(s2) > len(progs):
            return None
        return progs[int(s2) - 1][1]
    return None


def _run(cmd):
    """子进程跑一条命令（stdout/stderr 直通控制台，实时可见），回退出码。"""
    print(">>> " + " ".join(os.path.basename(c) if c == PY else c for c in cmd))
    try:
        r = subprocess.run(cmd, cwd=REPO)
        return r.returncode
    except Exception as e:  # noqa: BLE001
        print(f"[错误] 子进程启动失败: {e}")
        return 1


def do_check(master):
    """校验母本（preflight）。exit 0=无 ERROR。"""
    rc = _run([PY, os.path.join("tools", "check_master.py"),
               master_abspath(master)])
    print("\n[校验通过：0 ERROR]" if rc == 0 else "\n[校验有 ERROR，见上表 / HTML 报告]")
    return rc == 0


def clean_products(platform):
    """生成前清理该平台产物：删 LAB + 各程序文件夹，保留 KEEP_DIRS 与所有文件。
    （main.py 以 'a' 追加写 .prg/.pln，脏目录上重跑会翻倍内容——见 PROJECT_MAP。）"""
    root = PRODUCT_ROOT[platform]
    if not os.path.isdir(root):
        return
    removed = []
    for name in os.listdir(root):
        p = os.path.join(root, name)
        if os.path.isdir(p) and name not in KEEP_DIRS:
            try:
                shutil.rmtree(p)
                removed.append(name)
            except Exception as e:  # noqa: BLE001
                print(f"  [警告] 删不掉 {name}: {e}（可能被占用，请关掉相关程序后重试）")
    if removed:
        print(f"  已清理旧产物: {', '.join(removed)}")
    else:
        print("  无旧产物需清理。")


def do_generate(platform, master, cp=None, variant=None):
    """生成（可选只生成某个 CP / 某个版本）→ main.py 内部还会跑一遍 preflight gate
    （有 ERROR 会自行中止）。cp=None/"ALL" 且 variant 为 None/"both" 时视为「全量重生成」，
    这种情况才会先清理该平台全部旧产物（'a' 追写脏目录翻倍的老问题）；
    只要限定了 CP 或版本，就不清理——main.py 只会重写被选中的那些程序，其余的
    保持原样（否则会把没选中的 CP/版本 一并删掉，之前就因为这个丢过量产版程序）。"""
    cp_arg = None if cp in (None, "ALL") else cp
    full_regen = cp_arg is None and variant in (None, "both")
    if full_regen:
        print(f"\n--- 清理 {platform} 旧产物（全量重生成）---")
        clean_products(platform)
    else:
        print(f"\n--- 只生成 {cp_arg or '全部CP'} / {variant or 'both'}，不清理其余已有产物 ---")
    cmd = [PY, os.path.join(REPO, "main.py"), "--platform", platform, "--master", master]
    if cp_arg:
        cmd += ["--cp", cp_arg]
    if variant and variant != "both":
        cmd += ["--variant", variant]
    print(f"--- 生成 {platform}（母本 {master}）---")
    rc = _run(cmd)
    print(f"\n[生成完成: {platform}]" if rc == 0 else f"\n[生成失败: 退出码 {rc}]")
    return rc == 0


def do_compile(platform, target="all"):
    """target="all" 用 -r 自动发现该平台全部程序；否则 target 是单个程序的绝对路径，用 -p。"""
    tool = os.path.join("tools", "chroma_compiler.py" if platform == "chroma" else "s100_compiler.py")
    if target == "all":
        root_rel = "Chroma_program" if platform == "chroma" else "S100_program"
        cmd = [PY, tool, "-r", root_rel]
    else:
        cmd = [PY, tool, "-p", target]
    rc = _run(cmd)
    print(f"\n[编译完成: {platform}]" if rc == 0 else f"\n[编译有失败: 退出码 {rc}]")
    return rc == 0


def do_full(platform, master, cp=None, variant=None, compile_scoped=False):
    """一键：校验 → 生成（可限定 CP/版本） → 编译。校验有 ERROR 即停。
    compile_scoped=True 时只编译刚生成的那部分（按 cp/variant 过滤磁盘上匹配的程序，
    生成之后再扫描，能扫到刚生成的新文件夹）；False 时照常全部编译。"""
    if not do_check(master):
        print("\n[一键流程中止] 母本校验未过，先修母本。")
        return
    if not do_generate(platform, master, cp=cp, variant=variant):
        print("\n[一键流程中止] 生成失败。")
        return
    if not compile_scoped:
        do_compile(platform, "all")
        return
    cp_arg = None if cp in (None, "ALL") else cp
    progs = list_program_dirs(platform, cp=cp_arg, variant=variant)
    if not progs:
        print("\n[提示] 没扫到刚生成的程序文件夹，改为全部编译。")
        do_compile(platform, "all")
        return
    for label, path in progs:
        print(f"\n--- 编译 {label} ---")
        do_compile(platform, path)


def menu():
    master = None
    platform = None
    # 只有一个母本时默认选中，省一步
    masters = find_masters()
    if len(masters) == 1:
        master = masters[0]
    while True:
        print("\n" + BANNER)
        if not master:
            master_disp = "(未选，先按 [1])"
        elif os.path.isabs(master):
            master_disp = f"{os.path.basename(master)}  [外部: {os.path.dirname(master)}]"
        else:
            master_disp = master
        print(f"  当前母本  : {master_disp}")
        print(f"  当前平台  : {platform or '(未选)'}")
        print("----------------------------------------------")
        print("  [1] 选择母本")
        print("  [2] 选择平台 (chroma / s100)")
        print("  [3] 校验母本 (preflight)")
        print("  [4] 生成程序 (选 CP / 版本 → 生成)")
        print("  [5] 编译产物 (选全部 / 单个程序)")
        print("  [6] 一键全流程 (校验 → 生成 → 编译)")
        print("  [0] 退出")
        choice = input("请选择: ").strip()

        if choice == "0":
            return 0
        elif choice == "1":
            m = choose_master()
            if m:
                master = m
        elif choice == "2":
            p = choose_platform()
            if p:
                platform = p
        elif choice == "3":
            if not master:
                print("\n[提示] 请先按 [1] 选择母本。")
            else:
                do_check(master)
            _pause()
        elif choice == "4":
            if not master or not platform:
                print("\n[提示] 请先选择母本 [1] 和平台 [2]。")
            else:
                cp = choose_cp()
                if cp is not None:
                    variant = choose_variant()
                    if variant is not None:
                        do_generate(platform, master, cp=cp, variant=variant)
            _pause()
        elif choice == "5":
            if not platform:
                print("\n[提示] 请先按 [2] 选择平台。")
            else:
                target = choose_compile_scope(platform)
                if target is not None:
                    do_compile(platform, target)
            _pause()
        elif choice == "6":
            if not master or not platform:
                print("\n[提示] 请先选择母本 [1] 和平台 [2]。")
            else:
                cp = choose_cp()
                if cp is not None:
                    variant = choose_variant()
                    if variant is not None:
                        print("\n生成完之后编译：")
                        print("  [1] 全部编译")
                        print("  [2] 只编译刚生成的这部分")
                        print("  [0] 返回")
                        csel = input("选择: ").strip()
                        if csel in ("1", "2"):
                            do_full(platform, master, cp=cp, variant=variant, compile_scoped=(csel == "2"))
            _pause()
        else:
            print("无效选择。")


def main():
    try:
        rc = menu()
    except KeyboardInterrupt:
        print("\n已取消。")
        rc = 130
    sys.exit(rc or 0)


if __name__ == "__main__":
    main()
