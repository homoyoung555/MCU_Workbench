"""Chroma CRAFT 编译器封装 —— S100 编译器(YT5100_Pre)的 Chroma 对等工具。

S100 侧用 YT5100_Pre.exe 把 .prj/.prg 编成机台二进制(.gsw)；本工具用 CRAFT 自带的
命令行编译器把一份 Chroma 测试程序(.pln + pat/*.pat + pat/*.dec)编成机台产物，并解析
错误/警告、用退出码表达成败——和 verify_all 里的 s100_compile() 完全对应。

CRAFT 编译三段(与官方 makefile 一致)：
  1) deccmp   pin.dec       —— 引脚声明编译，产出 *.pinmap/*.pgmap/*_init.dll（完整校验）
  2) patcmp   -o<out> *.pat —— 向量编译+链接，产出 *.ppo (二进制 pattern)（完整校验）
  3) plncmp   *.pln         —— 测试计划：完整编译，解析 + 测试主体 C++ 编译/链接，产出 <名>.pin
deccmp/plncmp/patcmp 内部会调用 CRAFT 的 bin\\cl.bat(用 vswhere 拉起 VS 的 cl.exe)编 C++，
因此运行前必须把 CRAFT 的 bin/include/lib 顶到 PATH/INCLUDE/LIB 前面（相当于 S100 侧的 bcc32.cfg）。

PLN 完整编译（2026-06-25 起）：本机 CRAFT 安装(C:\\CRAFT，含破解授权)已修复大号 plncmp 的
无头自旋——早先无站台运行时 plncmp 打印 'default linked library : ws2_32.lib' 后卡死、编不到
测试主体；现在它能一路编完测试主体 C++ 并 'Linking ...Success!!' 产出 .pin，无需上站台。
故本工具的 pln 段默认走大号 plncmp 做**完整编译**（覆盖测试主体 C++ 语法/#include），成功判据=
输出 'Pln File compile successful' 且无错误行（注意 .pin 会被提前建成 512B 桩、主体失败时仍残留，
不能用 .pin 存在判成功）。带 timeout 兜底：万一在非破解 CRAFT 上仍自旋，超时即 taskkill 杀树并判失败。
旧的 plncmp2 前端预检仍保留（`--pln-precheck`），供无破解授权的环境降级使用。

用法：
  python tools/chroma_compiler.py -p <程序文件夹>          # 编一个程序(含 .pln 和 pat/)
  python tools/chroma_compiler.py -r Chroma_program         # 自动发现并编全部程序
  python tools/chroma_compiler.py -a selftest               # 用 CRAFT 自带 LS299 样例自检工具链
  python tools/chroma_compiler.py -a detect -r Chroma_program
  python tools/chroma_compiler.py -h
退出码非 0 = 有失败。
"""
import argparse
import glob
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_craft_home(explicit=None):
    """CRAFT 安装根：显式参数 > 环境变量 CRAFT_HOME > 仓库内 Chroma_Compiler/Craft。"""
    for cand in (explicit, os.environ.get("CRAFT_HOME"),
                 os.path.join(ROOT, "Chroma_Compiler", "Craft")):
        if cand and os.path.isfile(os.path.join(cand, "bin", "patcmp.exe")):
            return os.path.abspath(cand)
    return None


def build_env(craft):
    """把 CRAFT 的 bin/include/lib 顶到最前——deccmp/patcmp/plncmp 会 shell 出 cl(=bin\\cl.bat)
    并 #include "uti/..."、链接 plnlib.lib，少了这三个路径就编不过。"""
    env = dict(os.environ)
    env["CRAFT_HOME"] = craft
    sep = os.pathsep
    env["PATH"] = os.path.join(craft, "bin") + sep + env.get("PATH", "")
    env["INCLUDE"] = os.path.join(craft, "include") + sep + env.get("INCLUDE", "")
    env["LIB"] = os.path.join(craft, "lib") + sep + env.get("LIB", "")
    env["_CRAFT_BIN"] = os.path.join(craft, "bin")  # run() 用它把首个 exe 解析成绝对路径
    return env


def run(cmd, cwd, env, timeout=900):
    """跑一个 CRAFT 工具，回 (returncode, 合并输出)。CRAFT 工具输出 GBK(含中文)。
    Windows 下 subprocess 用父进程 PATH 解析可执行文件、忽略 env['PATH']，所以这里把
    首个 exe 显式指向 CRAFT bin；该 exe 内部再 shell 出的 cl/deccmp 走子进程 PATH 即可。"""
    exe = cmd[0]
    if not os.path.isabs(exe):
        exe = os.path.join(env["_CRAFT_BIN"], exe)
    p = subprocess.run([exe] + cmd[1:], cwd=cwd, env=env, capture_output=True,
                       encoding="gbk", errors="replace", timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


# 各阶段的错误特征行（CRAFT 工具不统一用退出码，得靠文本+产物双重判定）
_ERR_RE = re.compile(
    r"(parse error|fatal error|: error|Error\s*:|Error\s+to|"
    r"fail to|cannot open|No such file|undefined|unresolved|: 错误)",
    re.IGNORECASE)


def _scan(out):
    """从输出里挑出错误行（去重保序，最多 12 行）。"""
    seen, errs = set(), []
    for ln in out.splitlines():
        s = ln.strip()
        if s and _ERR_RE.search(s) and s not in seen:
            seen.add(s)
            errs.append(s)
    return errs[:12]


def _find_project(folder):
    """在程序文件夹里定位 .pln 与 pat 目录；回 (pln_path, pat_dir) 或 (None, None)。"""
    plns = glob.glob(os.path.join(folder, "*.pln"))
    pat = None
    for name in ("pat", "PAT"):
        d = os.path.join(folder, name)
        if os.path.isdir(d):
            pat = d
            break
    return (plns[0] if plns else None), pat


def compile_dec(pat_dir, env):
    """编 pat/ 下的全部 .dec。"""
    decs = glob.glob(os.path.join(pat_dir, "*.dec"))
    if not decs:
        return {"stage": "dec", "ok": False, "errors": ["no .dec found in pat/"]}
    errs = []
    for dec in decs:
        rc, out = run(["deccmp.exe", os.path.basename(dec)], pat_dir, env)
        base = os.path.splitext(os.path.basename(dec))[0]
        # 成功判据：生成了 *_0.pinmap 且无错误行
        made = glob.glob(os.path.join(pat_dir, base + "_*.pinmap"))
        e = _scan(out)
        if e or not made:
            errs += [f"{os.path.basename(dec)}: {x}" for x in (e or ["no .pinmap produced"])]
    return {"stage": "dec", "ok": not errs, "errors": errs}


def _sorted_pats(pat_dir):
    """pat/ 下 .pat 文件名，**大小写不敏感**排序（对齐 mkwizard 的列表顺序）。"""
    names = [os.path.basename(p) for p in glob.glob(os.path.join(pat_dir, "*.pat"))]
    return sorted(names, key=str.lower)


def generate_makefile(folder, pat_dir):
    """复刻 mkwizard「生成 makefile」：在程序根目录写出 makefile / makefile_pat0.lst /
    makefile_pdt0.lst，与 CRAFT GUI 勾选「生成 makefile」等价（非复制 mkwizard 产物，
    而是按同规则程序化生成；makefile_pat0.lst 已对 mkwizard CP1 逐行验证一致）。
    **关键**：`PAT_LFLAGS0 = -o.\\PAT\\pin_pat` → 链接成 `pin_pat.ppo`，对齐 .pln 写死的
    `LOAD_PAT("./PAT/pin_pat.ppo")`——否则上机加载 pattern 会找不到文件。回 pat 文件名列表。"""
    pln, _ = _find_project(folder)
    base = os.path.splitext(os.path.basename(pln))[0] if pln else "pin"
    pats = _sorted_pats(pat_dir)
    nl = "\n"  # mkwizard makefile/lst 用 LF 行尾（cat -A 实测无 ^M）
    with open(os.path.join(folder, "makefile_pat0.lst"), "w", encoding="ascii", newline="") as f:
        f.write("".join(".\\PAT\\%s%s" % (n, nl) for n in pats))
    with open(os.path.join(folder, "makefile_pdt0.lst"), "w", encoding="ascii", newline="") as f:
        f.write("".join(".\\PAT\\%s.pdt%s" % (n[:-4], nl) for n in pats))
    L = []
    L.append("# ---------------------User Definition Area Begin-----------------------------")
    L.append("# PLN_SOURCE: Specify plan source file name whose extension name is .pln.")
    L.append("# PLN_CFLAGS: plncmp options on compiling phase e.g. -c, -v")
    L.append("#")
    L.append("# PAT_SOURCE: Specify pattern source file name whose extension name is .pat.")
    L.append("# PAT_CFLAGS: patcmp options on compiling phase e.g. -x, -p, -eXXX")
    L.append("# PAT_LFLAGS: patcmp options on linking phase e.g -oXXX, -r")
    L.append('# NOCOMPRESS_FLAG => remove comment mark "#" below to turn on the patcmp\'s "-n" flag.')
    L.append("#")
    L.append("PATH_PAT0     = .\\PAT")
    L.append("PLN_SOURCE   = %s.pln " % base)
    L.append("PLN_TARGET   = %s.pin" % base)
    L.append("PLN_CFLAGS   = ")
    for i, n in enumerate(pats):
        prefix = "PAT_SOURCE0   =                 " if i == 0 else "              "
        tail = "\\ " if i < len(pats) - 1 else " "   # 续行 `\ `；末行仅尾随空格
        L.append("%s$(PATH_PAT0)\\%s%s" % (prefix, n, tail))
    L.append("")
    L.append("PAT_CFLAGS0   =")
    L.append("PAT_LFLAGS0   = -o.\\PAT\\pin_pat")
    L.append("PAT_TARGET0   =.\\PAT\\pin_pat.ppo")
    L.append("# ---------------------User Definition Area End------------------------------")
    L.append("")
    L.append("PAT_OBJECTS_TMP0    = $(PAT_SOURCE0:.pat=.pdt)")
    L.append("PAT_OBJECTS0        = $(PAT_OBJECTS_TMP0:.PAT=.pdt)")
    L.append("# ---------------------------------------------------------------------------")
    L.append(".precious: $(PAT_OBJECTS0) $(PAT_COBJECTS0)")
    L.append("")
    L.append("all: $(PLN_TARGET) $(PAT_TARGET0) ")
    L.append("")
    L.append("$(PLN_TARGET): $(PLN_SOURCE) .\\PAT\\pin.dec")
    L.append("  @$(CRAFT_HOME)\\bin\\plncmp $(PLN_CFLAGS) $(PLN_SOURCE)")
    L.append("")
    L.append("$(PAT_TARGET0):: .\\PAT\\pin.dec")
    L.append("  @$(CRAFT_HOME)\\bin\\patcmp $(PAT_CFLAGS0) $(PAT_LFLAGS0) -f makefile_pat0.lst")
    L.append("")
    L.append("$(PAT_TARGET0):: $(PAT_OBJECTS0)")
    L.append("  @$(CRAFT_HOME)\\bin\\patcmp $(PAT_LFLAGS0) -f makefile_pdt0.lst")
    L.append("")
    L.append(".pat.pdt :")
    L.append("  @$(CRAFT_HOME)\\bin\\patcmp -c -s $(PAT_CFLAGS0) $<")
    L.append("")
    L.append("build:")
    L.append("  @$(CRAFT_HOME)\\bin\\plncmp $(PLN_CFLAGS) $(PLN_SOURCE)")
    L.append("  @$(CRAFT_HOME)\\bin\\patcmp $(PAT_CFLAGS0) $(PAT_LFLAGS0) -f makefile_pat0.lst")
    L.append("")
    L.append("clean:")
    L.append("  @touch -c *.pln")
    for n in pats:
        L.append("  @touch -c $(PATH_PAT0)\\%s" % n)
    with open(os.path.join(folder, "makefile"), "w", encoding="ascii", newline="") as f:
        f.write(nl.join(L) + nl)
    return pats


def compile_pat(folder, pat_dir, env):
    """先生成 makefile（复刻 mkwizard），再在**程序根目录**按 makefile_pat0.lst 把全部
    .pat 链接成 `pin_pat.ppo`（对齐 .pln 的 LOAD_PAT 与上机 make 流程）。"""
    pats = _sorted_pats(pat_dir)
    if not pats:
        return {"stage": "pat", "ok": False, "errors": ["no .pat found in pat/"]}
    generate_makefile(folder, pat_dir)  # 写 makefile / makefile_pat0.lst / makefile_pdt0.lst
    rc, out = run(["patcmp.exe", "-o.\\PAT\\pin_pat", "-f", "makefile_pat0.lst"], folder, env)
    ppo = os.path.join(pat_dir, "pin_pat.ppo")
    errs = _scan(out)
    ok = not errs and os.path.isfile(ppo) and os.path.getsize(ppo) > 0
    if not ok and not errs:
        errs = ["no pin_pat.ppo produced (rc=%d)" % rc]
    return {"stage": "pat", "ok": ok, "errors": errs, "n_pat": len(pats)}


# PLN 完整编译的成功标志行（大号 plncmp 编完测试主体 C++ 后打印）
_PLN_OK_RE = re.compile(r"Pln File compile successful", re.I)


def compile_pln_full(folder, pln, env, timeout=600):
    """用大号 plncmp 完整编译 .pln：解析 + 测试主体 C++ 编译/链接，产出 <名>.pin。
    破解版 CRAFT(C:\\CRAFT) 已修复无头自旋(原卡在 'ws2_32.lib' 后)，本机可完整编译主体。
    成功判据=出现 'Pln File compile successful' 且无错误行——.pin 会被提前建成 512B 桩、
    主体编译失败时仍残留，故不能用 .pin 存在判成功。timeout 仅作防卡死兜底（非破解 CRAFT 会自旋）。"""
    base = os.path.basename(pln)
    exe = os.path.join(env["_CRAFT_BIN"], "plncmp.exe")
    try:
        p = subprocess.run([exe, base], cwd=folder, env=env, capture_output=True,
                           encoding="gbk", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        subprocess.run(["taskkill", "/F", "/T", "/IM", "plncmp.exe"], capture_output=True)
        return {"stage": "pln", "ok": False,
                "errors": ["plncmp 超时 %ds 未完成（疑无头自旋；非破解 CRAFT 用 --pln-precheck 降级）"
                           % timeout]}
    out = (p.stdout or "") + (p.stderr or "")
    errs = _scan(out)
    ok = (p.returncode == 0) and bool(_PLN_OK_RE.search(out)) and not errs
    if not ok and not errs:
        errs = ["plncmp 未报成功（rc=%d，无 'Pln File compile successful'）" % p.returncode]
    return {"stage": "pln", "ok": ok, "errors": errs, "note": "完整编译(测试主体C++已编)"}


# PLN 预检：大号 plncmp 的 banner（到这里=预处理+dec 预解析都过了）
_PLN_BANNER_RE = re.compile(r"Test Plan file compiler for CRAFT", re.I)
# PLN 预检阶段的真错误（避开 VsDevCmd 那句无害的 "vError 0x57: Unknown parameter: path"）
_PLN_ERR_RE = re.compile(
    r"(error C\d{3,}|error LNK\d|: fatal error|: error [A-Z]|Pre-Compiler Fail|"
    r"Dec Pre Parser Error|Pre-Parser.*Error|Fail to open|Can Not Open|Can't Open|"
    r"Cannot open|unresolved external|语法错误|: 错误)", re.IGNORECASE)


def _pln_precheck(pln_base, cwd, env, timeout):
    """流式跑 plncmp2 的预处理+dec 预解析段。逐行读 stdout：
      - 命中错误行 → ('fail', 错误行, 全部行)
      - 到达大号 plncmp banner（预处理段已过，再往后是会卡死的 .exe 组装）→ ('pass', None, 行)
      - 超时/进程自己结束且无上述 → ('timeout'/'done', None, 行)
    无论哪种结局都 taskkill /T 杀掉整棵进程树，绝不把卡死的 plncmp 留在后台。"""
    exe = os.path.join(env["_CRAFT_BIN"], "plncmp2.exe")
    proc = subprocess.Popen(
        [exe, pln_base], cwd=cwd, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    q = queue.Queue()

    def _reader():
        for raw in iter(proc.stdout.readline, b""):
            q.put(raw)
        proc.stdout.close()

    threading.Thread(target=_reader, daemon=True).start()
    lines, verdict, hit = [], None, None
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            raw = q.get(timeout=1.0)
        except queue.Empty:
            if proc.poll() is not None and q.empty():
                verdict = verdict or "done"
                break
            continue
        s = raw.decode("gbk", "replace").replace("\x00", "").rstrip()
        if not s:
            continue
        lines.append(s)
        if _PLN_ERR_RE.search(s):
            verdict, hit = "fail", s
            break
        if _PLN_BANNER_RE.search(s):
            verdict = "pass"
            break
    if verdict is None:
        verdict = "timeout"
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True)
    except Exception:
        pass
    return verdict, hit, lines


def compile_pln(folder, pln, env, full=True, timeout=600):
    """PLN 编译分发：full=True(默认)走大号 plncmp 完整编译（含测试主体 C++）；
    full=False 走 plncmp2 前端预检（无破解授权环境的降级）。"""
    if full:
        return compile_pln_full(folder, pln, env, timeout=timeout)
    return compile_pln_precheck(folder, pln, env, timeout=min(timeout, 180))


def compile_pln_precheck(folder, pln, env, timeout=180):
    """PLN 前端预检（用 plncmp2，有界、绝不卡）。覆盖范围已实测确认：
    ✓ 抓得到：plncmp2 前端能否处理 .pln、SET_DEC_FILE/dec 引用能否解析（dec 名不匹配类 bug）、
              plncmp2 启动/锁/找不到文件类失败。
    ✗ 抓不到：测试主体的 C++ 逻辑语法、#include（实测坏 include 也漏过）。这些只有大号 plncmp
              在正式安装的 CRAFT 站台运行时下编主体时才会查——无头下编不到主体（到 banner 就会
              卡在 .exe 组装），故本预检到 banner 即判过并 taskkill 杀树。主体语法/.exe 须上站台。"""
    base = os.path.basename(pln)
    verdict, hit, lines = _pln_precheck(base, folder, env, timeout)
    if verdict == "fail":
        return {"stage": "pln", "ok": False, "errors": [hit],
                "note": "前端/dec 引用错"}
    if verdict in ("pass", "done"):
        return {"stage": "pln", "ok": True, "errors": [],
                "note": "前端+dec引用过; 主体C++/.exe 须站台"}
    # timeout 且未到 banner、未报错 —— 多半卡在更早处，按未过处理
    errs = _scan("\n".join(lines)) or [
        "plncmp2 未在 %ds 内到达 PlnCmp 段（可能更早处卡住）" % timeout]
    return {"stage": "pln", "ok": False, "errors": errs}


def compile_project(folder, env, do_pln=True, pln_full=True):
    """编一个 Chroma 程序：dec → pat → pln。回汇总 dict。三段都能在本机无头跑：
      dec/pat —— 独立编译器，完整校验引脚声明 + 全部向量；
      pln     —— 大号 plncmp 完整编译（含测试主体 C++ 编译/链接，破解版 CRAFT 已修无头自旋）；
                 pln_full=False 降级为 plncmp2 前端预检（不查测试主体），供无破解授权环境用。
    do_pln=False 可只跑 dec+pat。"""
    name = os.path.basename(os.path.normpath(folder))
    pln, pat_dir = _find_project(folder)
    if not pln or not pat_dir:
        return {"name": name, "ok": False,
                "stages": [{"stage": "scan", "ok": False,
                            "errors": ["missing .pln or pat/ dir in " + folder]}]}
    stages = [compile_dec(pat_dir, env),
              compile_pat(folder, pat_dir, env)]
    if do_pln:
        stages.append(compile_pln(folder, pln, env, full=pln_full))
    return {"name": name, "ok": all(s["ok"] for s in stages), "stages": stages}


def detect_projects(root):
    """在 root 下找所有"含 .pln + pat/"的程序文件夹。"""
    found = []
    for folder, _, _ in os.walk(root):
        pln, pat = _find_project(folder)
        if pln and pat:
            found.append(folder)
    return sorted(found)


def _print_result(res):
    ok = res["ok"]
    print(f"[{'PASS' if ok else 'FAIL'}] {res['name']}")
    for s in res["stages"]:
        tag = "ok" if s["ok"] else "FAIL"
        extra = f" ({s.get('n_pat')} pat)" if s.get("n_pat") else ""
        note = f"  — {s['note']}" if s.get("note") else ""
        print(f"    {s['stage']:4} {tag}{extra}{note}")
        for e in s.get("errors", []):
            print("        " + e)
    return ok


def selftest(craft, env, do_pln=False):
    """用 CRAFT 自带 LS299 教程样例验证工具链可用（拷到临时目录编，不动原件）。
    只验 dec+pat（秒级）即可证明 cl 工具链 OK；不验 pln（该样例 .pln 自带损坏二进制，
    且 pln 主体编译本就需站台——pln 预检请直接对真实程序 `-a pln` 或 `compile`）。"""
    ex = os.path.join(craft, "TestPlanExamples", "3380P_LS299_tutorial")
    if not os.path.isdir(ex):
        print("[SKIP] selftest: LS299 example not found")
        return True
    tmp = os.path.join(ROOT, "tools", "_chroma_selftest_tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(ex, tmp)
    # 清掉样例里已有的编译产物，确保是真编
    for ext in ("*.pin", "*.ppo", "*.pdt", "*.pinmap", "*.pgmap"):
        for f in glob.glob(os.path.join(tmp, "**", ext), recursive=True):
            os.remove(f)
    print("=== selftest: compiling CRAFT LS299 tutorial example ===")
    res = compile_project(tmp, env, do_pln=do_pln)
    ok = _print_result(res)
    shutil.rmtree(tmp, ignore_errors=True)
    print("=== selftest %s ===" % ("PASS — CRAFT toolchain OK" if ok else "FAIL — check CRAFT/VS setup"))
    return ok


def main():
    ap = argparse.ArgumentParser(description="Chroma CRAFT 编译器（S100 编译器的对等工具）")
    ap.add_argument("-p", "--project", help="单个程序文件夹（含 .pln 和 pat/）")
    ap.add_argument("-r", "--root", help="在此根目录下自动发现并编全部程序")
    ap.add_argument("-a", "--action", default="compile",
                    choices=["compile", "dec", "pat", "pln", "detect", "selftest"],
                    help="compile=全程(默认) / dec|pat|pln=单段 / detect=只列程序 / selftest=工具链自检")
    ap.add_argument("--craft-home", help="CRAFT 安装根（默认 Chroma_Compiler/Craft 或 $CRAFT_HOME）")
    ap.add_argument("--no-pln", action="store_true",
                    help="compile 时跳过 pln 段（默认 dec+pat+pln 完整编译都跑）")
    ap.add_argument("--pln-precheck", action="store_true",
                    help="pln 段降级为 plncmp2 前端预检（不编测试主体；无破解授权的 CRAFT 用）")
    args = ap.parse_args()

    craft = find_craft_home(args.craft_home)
    if not craft:
        print("ERROR: CRAFT not found. 设 --craft-home 或环境变量 CRAFT_HOME，"
              "或把 CRAFT 解压到 Chroma_Compiler/Craft（需含 bin/patcmp.exe）。")
        sys.exit(2)
    env = build_env(craft)
    print(f"CRAFT_HOME = {craft}")

    if args.action == "selftest":
        sys.exit(0 if selftest(craft, env) else 1)

    if args.action == "detect":
        root = args.root or args.project or os.path.join(ROOT, "Chroma_program")
        for f in detect_projects(root):
            print(f)
        return

    targets = []
    if args.project:
        targets = [args.project]
    elif args.root:
        targets = detect_projects(args.root)
    else:
        print("ERROR: 需要 -p <程序文件夹> 或 -r <根目录>")
        sys.exit(2)
    if not targets:
        print("ERROR: 没找到任何程序文件夹（需含 .pln 和 pat/）")
        sys.exit(2)

    failed = False
    for folder in targets:
        if args.action == "compile":
            res = compile_project(folder, env, do_pln=not args.no_pln,
                                  pln_full=not args.pln_precheck)
        else:
            pln, pat_dir = _find_project(folder)
            name = os.path.basename(os.path.normpath(folder))
            if args.action == "dec":
                stage = compile_dec(pat_dir, env)
            elif args.action == "pat":
                stage = compile_pat(folder, pat_dir, env)
            else:
                stage = compile_pln(folder, pln, env, full=not args.pln_precheck)
            res = {"name": name, "ok": stage["ok"], "stages": [stage]}
        failed |= not _print_result(res)

    print()
    print("===== ALL PASS =====" if not failed else "===== FAILURES =====")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
