# 一条命令的回归流水线：生成双平台 → 跨平台向量 oracle → S100 三 CP 全量编译。
# 用法：D:\Python\python.exe tools\verify_all.py [--skip-compile]
# 退出码非 0 = 有失败。Chroma 侧编译器用户开发中，留有接入位（chroma_compile）。
import ctypes
import io
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
PRE = os.path.join(ROOT, "S100_Compiler", "app", "S100", "YT5100_Pre.exe")
BCB_BIN = os.path.join(ROOT, "S100_Compiler", "app", "BCB6", "Bin")


def short_path(p):
    buf = ctypes.create_unicode_buffer(260)
    if ctypes.windll.kernel32.GetShortPathNameW(p, buf, 260):
        return buf.value
    return p


def ensure_bcc_cfg():
    """bcc32(2002) 的 cfg 解析装不下长路径——每次防御性地用 8.3 短路径重写。"""
    bcb = short_path(os.path.join(ROOT, "S100_Compiler", "app", "BCB6"))
    s100 = short_path(os.path.join(ROOT, "S100_Compiler", "app", "S100"))
    cfg = (f'-I"{bcb}\\Include";"{bcb}\\Include\\vcl";"{s100}"\n'
           f'-L"{bcb}\\Lib";"{bcb}\\Lib\\obj";"{bcb}\\Lib\\release";"{s100}"\n')
    io.open(os.path.join(BCB_BIN, "bcc32.cfg"), "w", encoding="ascii").write(cfg)


def step(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    return ok


def gen(platform):
    r = subprocess.run([PY, os.path.join(ROOT, "main.py"), "--platform", platform],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       cwd=ROOT, timeout=600)
    return r.returncode == 0, (r.stdout + r.stderr).strip().splitlines()[-3:] if r.returncode else ""


def oracle():
    r = subprocess.run([PY, os.path.join(ROOT, "tools", "compare_vectors.py")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    line = (r.stdout or "").strip().splitlines()
    summary = line[0] if line else ""
    ok = "diff=0" in summary and "onlyS100=0" in summary and "onlyChroma=0" in summary
    return ok, summary


def program_names():
    import pandas as pd
    df = pd.read_excel(os.path.join(ROOT, "test_data", "program.xlsx"), sheet_name="VERSION")
    return [str(n) for n in df["Program Name"]]


def s100_compile(cp):
    d = os.path.join(ROOT, "S100_program", cp)
    for sub in ("pattern_ddr2", "program", "timing_ddr2"):
        p = os.path.join(d, sub)
        if os.path.isdir(p):
            import shutil
            shutil.rmtree(p)
    env = dict(os.environ)
    env["PATH"] = BCB_BIN + ";" + env["PATH"]
    r = subprocess.run([PRE, os.path.join(d, cp + ".prj"), "-A", "-bcb6", "-de"],
                       capture_output=True, text=True, encoding="gbk", errors="replace",
                       env=env, timeout=900)
    out = r.stdout or ""
    # 取最末一个 Errors 汇总（pre.exe 分阶段多次打印）
    errs = re.findall(r"Errors\s+:\s+(\d+)", out)
    warns = re.findall(r"Warnings\s+:\s+(\d+)", out)
    n_err = int(errs[-1]) if errs else 99
    n_warn = int(warns[-1]) if warns else 0
    gsw = os.path.join(d, "program", cp + ".gsw")
    gsw_ok = os.path.isfile(gsw) and os.path.getsize(gsw) > 0
    detail_lines = [l.strip() for l in out.splitlines()
                    if re.search(r"(PRG|PRJ|TIM)\s+\d+\s*:|Unknown|Fail|mising|define error", l)]
    return n_err == 0 and gsw_ok, n_err, n_warn, gsw_ok, detail_lines[:8]


def test_functions_check():
    """TEST_PRO 调度表 vs 函数定义交叉核对（Chroma 全部程序，含 LAB+生产），见
    tools/check_test_functions.py（2026-07-03 用户裁决接入回归：item 名跨表拼写不一致
    等原因导致的"调度表引用了但函数体没写出来"，本地生成/编译都不报错，只有这个检查
    能兜住）。回 [(name, ok, missing), ...]；Chroma_program 不存在时回 []（不算失败，
    跟 chroma_compile() 对 CRAFT 缺失的处理方式一致）。"""
    import chroma_compiler as cc
    import check_test_functions as ctf
    root = os.path.join(ROOT, "Chroma_program")
    if not os.path.isdir(root):
        return []
    results = []
    for folder in cc.detect_projects(root):
        name = os.path.basename(os.path.normpath(folder))
        dispatched, missing = ctf.check_folder(folder)
        if dispatched is None:
            continue
        results.append((name, len(missing) == 0, missing))
    return results


def chroma_compile():
    """Chroma 侧编译：用 CRAFT 工具链(deccmp/patcmp/plncmp)编 Chroma_program 下全部程序。
    回 [(name, ok, errlines), ...]；CRAFT 未安装时回 None（跳过，不算失败）。引擎见 tools/chroma_compiler.py。"""
    import chroma_compiler as cc
    craft = cc.find_craft_home()
    if not craft:
        return None
    env = cc.build_env(craft)
    results = []
    for folder in cc.detect_projects(os.path.join(ROOT, "Chroma_program")):
        res = cc.compile_project(folder, env)
        errs = [f"{s['stage']}: {e}" for s in res["stages"] for e in s.get("errors", [])]
        results.append((res["name"], res["ok"], errs[:6]))
    return results


def main():
    skip_compile = "--skip-compile" in sys.argv
    failed = False

    # 输出标签用 ASCII——GBK 控制台下中文会乱码
    ok, tail = gen("s100")
    failed |= not step("gen s100", ok, "" if ok else str(tail))
    ok, tail = gen("chroma")
    failed |= not step("gen chroma", ok, "" if ok else str(tail))

    ok, summary = oracle()
    failed |= not step("vector oracle", ok, summary)

    tf_results = test_functions_check()
    if not tf_results:
        step("test functions check", True, "no Chroma_program found - skipped")
    else:
        for name, ok, missing in tf_results:
            failed |= not step(f"test functions {name}", ok,
                               f"missing={missing}" if missing else "")

    if not skip_compile:
        if not os.path.isfile(PRE):
            step("s100 compile", False, "YT5100_Pre.exe not found - S100_Compiler/app not extracted?")
            failed = True
        else:
            ensure_bcc_cfg()
            for cp in program_names():
                ok, n_err, n_warn, gsw_ok, details = s100_compile(cp)
                failed |= not step(f"compile {cp}", ok, f"errors={n_err} warnings={n_warn} gsw={'OK' if gsw_ok else 'MISSING'}")
                for l in details:
                    print("        " + l)

        cres = chroma_compile()
        if cres is None:
            step("chroma compile", True, "CRAFT not found - skipped (set CRAFT_HOME or extract Chroma_Compiler/Craft)")
        else:
            for name, ok, errs in cres:
                failed |= not step(f"chroma {name}", ok)
                for e in errs:
                    print("        " + e)

    print()
    print("===== ALL PASS =====" if not failed else "===== FAILURES =====")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
