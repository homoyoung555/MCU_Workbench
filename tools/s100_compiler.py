# S100 编译器封装（与 tools/chroma_compiler.py 对位）：把 YT5100_Pre.exe 包成
# 干净的程序化入口 + CLI，返回结构与 chroma_compiler 一致（GUI/web 后端可统一处理两平台）。
#   python tools/s100_compiler.py -p <程序文件夹>      # 编单个
#   python tools/s100_compiler.py -r <根目录>          # 自动发现并编全部
#   python tools/s100_compiler.py -a detect -r <根>    # 只列出发现的程序
# 返回 dict: {"name", "ok", "stages":[{"stage":"compile","ok","errors":[...],
#             "n_err","n_warn","gsw_ok"}]}  —— 与 chroma_compiler.compile_project 同构。
import argparse
import ctypes
from contextlib import contextmanager
import io
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_INTERMEDIATE = ("program", "pattern_ddr2", "timing_ddr2")   # 编译中间产物目录


def short_path(p):
    buf = ctypes.create_unicode_buffer(260)
    if ctypes.windll.kernel32.GetShortPathNameW(p, buf, 260):
        return buf.value
    return p


def find_s100_home(explicit=None):
    """定位 S100_Compiler 根（便携根布局优先，兼容旧 app 布局）；找不到回 None。"""
    cand = explicit or os.path.join(ROOT, "S100_Compiler")
    return cand if os.path.isfile(_pre(cand)) else None


def _tool_dirs(home):
    portable_s100 = os.path.join(home, "S100")
    portable_bcb = os.path.join(home, "BCB6")
    if (os.path.isfile(os.path.join(portable_s100, "YT5100_Pre.exe")) and
            os.path.isfile(os.path.join(portable_bcb, "Bin", "bcc32.exe"))):
        return portable_s100, portable_bcb
    return os.path.join(home, "app", "S100"), os.path.join(home, "app", "BCB6")


def _pre(home):
    s100, _ = _tool_dirs(home)
    return os.path.join(s100, "YT5100_Pre.exe")


def ensure_bcc_cfg(home):
    """bcc32(2002) cfg 解析装不下长路径——每次防御性用 8.3 短路径重写 bcc32.cfg。"""
    s100_dir, bcb_dir = _tool_dirs(home)
    bcb = short_path(bcb_dir)
    s100 = short_path(s100_dir)
    cfg = (f'-I"{bcb}\\Include";"{bcb}\\Include\\vcl";"{s100}"\n'
           f'-L"{bcb}\\Lib";"{bcb}\\Lib\\obj";"{bcb}\\Lib\\release";"{s100}"\n')
    with io.open(
        os.path.join(bcb_dir, "Bin", "bcc32.cfg"),
        "w",
        encoding="ascii",
    ) as config:
        config.write(cfg)


def _bcc_cfg_text(home):
    s100, bcb = _tool_dirs(home)
    return (f'-I"{bcb}\\Include";"{bcb}\\Include\\vcl";"{s100}"\n'
            f'-L"{bcb}\\Lib";"{bcb}\\Lib\\obj";"{bcb}\\Lib\\release";"{s100}"\n')


def needs_bcc_home_alias(home):
    """Old bcc32 rejects a configuration option when its line is too long."""
    candidate = short_path(os.path.abspath(home.rstrip("\\/")))
    return max(len(line) for line in _bcc_cfg_text(candidate).splitlines()) > 240


@contextmanager
def compiler_home_alias(home, *, run=None, drive_exists=None):
    """Yield a bcc32-safe compiler root and release any temporary subst drive."""
    home = os.path.abspath(home.rstrip("\\/"))
    shortened = short_path(home)
    if not needs_bcc_home_alias(shortened):
        yield shortened
        return
    run = subprocess.run if run is None else run
    drive_exists = os.path.exists if drive_exists is None else drive_exists
    drive = next(
        (f"{letter}:" for letter in reversed("PQRSTUVWXYZ")
         if not drive_exists(f"{letter}:\\")),
        None,
    )
    if drive is None:
        raise RuntimeError("no free drive letter for the S100 compiler path alias")
    run(["subst", drive, home], check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        yield drive + "\\"
    finally:
        run(["subst", drive, "/d"], check=False,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def build_env(home):
    """编译环境：BCB6\\Bin 顶到 PATH + 防御性重写 bcc32.cfg。"""
    ensure_bcc_cfg(home)
    s100, bcb = _tool_dirs(home)
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join((
        s100,
        os.path.join(bcb, "Bin"),
        env.get("PATH", ""),
    ))
    return env


@contextmanager
def compiler_environment(home):
    """Use relocated include/library paths, restoring the user's config on exit."""
    with compiler_home_alias(str(home)) as alias:
        cfg = Path(_tool_dirs(alias)[1]) / 'Bin/bcc32.cfg'
        original = cfg.read_bytes() if cfg.exists() else None
        try:
            yield alias, build_env(alias)
        finally:
            if original is None:
                cfg.unlink(missing_ok=True)
            else:
                cfg.write_bytes(original)


def _scan(out):
    errs = re.findall(r"Errors\s+:\s+(\d+)", out)
    warns = re.findall(r"Warnings\s+:\s+(\d+)", out)
    n_err = int(errs[-1]) if errs else 99            # 没匹配到=异常，按失败算
    n_warn = int(warns[-1]) if warns else 0
    detail = [l.strip() for l in out.splitlines()
              if re.search(r"Unknown|Undefined|Failed|: *error|define error|mising", l, re.I)]
    return n_err, n_warn, detail[:8]


def compile_project(folder, home, env, timeout=900):
    """编单个 S100 程序文件夹（含 <名>.prj）。回与 chroma_compiler 同构的 dict。"""
    folder = os.path.abspath(folder.rstrip("\\/"))   # YT5100_Pre 需绝对路径
    name = os.path.basename(folder)
    prj = os.path.join(folder, name + ".prj")
    if not os.path.isfile(prj):
        return {"name": name, "ok": False,
                "stages": [{"stage": "compile", "ok": False,
                            "errors": ["缺 .prj: " + prj]}]}
    # 清理中间产物（YT5100_Pre 会重建）
    for sub in _INTERMEDIATE:
        p = os.path.join(folder, sub)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
    r = subprocess.run([_pre(home), prj, "-A", "-bcb6", "-de"],
                       capture_output=True, text=True, encoding="gbk", errors="replace",
                       env=env, timeout=timeout)
    n_err, n_warn, detail = _scan(r.stdout or "")
    gsw = os.path.join(folder, "program", name + ".gsw")
    gsw_ok = os.path.isfile(gsw) and os.path.getsize(gsw) > 0
    ok = n_err == 0 and gsw_ok
    stage = {"stage": "compile", "ok": ok, "errors": detail,
             "n_err": n_err, "n_warn": n_warn, "gsw_ok": gsw_ok}
    return {"name": name, "ok": ok, "stages": [stage]}


def detect_projects(root):
    """根目录下自动发现 S100 程序（含 <文件夹名>.prj 的目录）；跳过中间产物/点目录。"""
    found = []
    for dirpath, dirnames, _ in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in _INTERMEDIATE]
        name = os.path.basename(dirpath)
        if os.path.isfile(os.path.join(dirpath, name + ".prj")):
            found.append(os.path.abspath(dirpath))
    return sorted(found)


def _print_result(res):
    print(f"[{'PASS' if res['ok'] else 'FAIL'}] {res['name']}")
    for s in res["stages"]:
        extra = ""
        if "n_err" in s:
            extra = f"  Errors={s['n_err']} Warnings={s['n_warn']} gsw={s['gsw_ok']}"
        print(f"    {s['stage']:<8} {'ok' if s['ok'] else 'FAIL'}{extra}")
        for e in s.get("errors", []):
            print(f"        {e}")


def main():
    ap = argparse.ArgumentParser(description="S100 编译器（YT5100_Pre 封装，chroma_compiler 的对等工具）")
    ap.add_argument("-p", "--project", help="单个程序文件夹（含 .prj）")
    ap.add_argument("-r", "--root", help="在此根目录下自动发现并编全部程序")
    ap.add_argument("-a", "--action", default="compile",
                    choices=["compile", "detect", "selftest"])
    ap.add_argument("--home", help="S100_Compiler 根（默认 V1.1/S100_Compiler）")
    args = ap.parse_args()

    discovered_home = find_s100_home(args.home)
    if not discovered_home:
        print("[FAIL] 未找到 S100_Compiler/app/S100/YT5100_Pre.exe（编译器未解压？）")
        return 1
    print("S100_HOME =", discovered_home)
    home = discovered_home

    if args.action == "detect":
        root = args.root or os.path.join(ROOT, "S100_program")
        for f in detect_projects(root):
            print("  ", f)
        return 0
    if args.action == "selftest":
        env = build_env(home)   # 顺带验证 cfg 可写
        print("[PASS] YT5100_Pre 就位、bcc32.cfg 已重写、环境就绪")
        return 0

    targets = []
    if args.project:
        targets = [args.project]
    elif args.root:
        targets = detect_projects(args.root)
    else:
        targets = detect_projects(os.path.join(ROOT, "S100_program"))
    if not targets:
        print("没找到可编译的 S100 程序（-p 指定文件夹，或 -r 指定根目录）")
        return 1

    allok = True
    with compiler_home_alias(discovered_home) as home:
        env = build_env(home)
        for folder in targets:
            res = compile_project(folder, home, env)
            _print_result(res)
            allok &= res["ok"]
    print("=====", "ALL PASS" if allok else "HAS FAIL", "=====")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
