# Chroma 平台：.pat pattern 文件生成（SPM_PATTERN / *011* 时序向量格式）。
import os
import re
import shutil

from program_gen.core.encoding import decimal_to_hex
from program_gen import state as G

# .pat 的 HEADER 管脚声明行：形如 "PA14, PA13, NRST;"（首尾可有空白）。
_PAT_HEADER_RE = re.compile(
    rb"(?m)^([ \t]*)[A-Za-z][A-Za-z0-9_]*[ \t]*,[ \t]*[A-Za-z][A-Za-z0-9_]*[ \t]*,[ \t]*NRST[ \t]*;[ \t]*\r?$")


def write_placeholder_pat(dest_dir, name):
    """pattern 源缺失时的全局兜底：生成一个能过 CRAFT 编译的占位假 .pat（**非真实向量**，
    只是空转 wait，用户裁决要求"pattern 没有就自动生成能编译的假 pat"，用于打通编译链路，
    等真实 pattern 数据到位后需替换 pat_temp 源文件重新生成）。
    HEADER 管脚沿用项目内全部 pattern 同一套约定（VERSION CLK PIN=时钟/SWD PIN=调试口/
    字面量 NRST=复位），与该程序 pin.dec 已声明的管脚一致，保证能编过；不用字面量
    "SCLK"/"SWD" 这两个名字——pin.dec 里没有声明这两个名字的管脚，编译会报未定义管脚。"""
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, name + ".pat")
    header = (G.col("VERSION", "CLK PIN")[0] + ", "
              + G.col("VERSION", "SWD PIN")[0] + ", NRST;")
    with open(path, "w") as f:
        f.write('SET_DEC_FILE "pin.dec"\n\nHEADER\n\n' + header
                + '\n\nSPM_PATTERN(' + name + ') {\n\n')
        f.write("  *011*TS1;\n  *011*RPT 100;\n\n")
        f.write("  *111*;// placeholder stub, no functional vector\n  *111*RPT 100;\n  *111*;\n\n")
        f.write("  *111*;\n  *111*RPT 1000;// wait 100us\n  *111*;\n  *011*STOP;\n\n}\n")
    print(f"  [WARN] pattern 源缺失，已生成占位假 pat（非真实向量，待补真实数据后重新生成覆盖）: {path}")
    return path


def copy_file(source, destination):
    """复制单个文件到目标目录；.pat 源文件缺失时**全局兜底生成占位假 pat**（用户裁决，
    2026-07-02：需要能在 pattern 数据未就绪时先打通生成+编译链路；用醒目 WARN 打印，
    不静默——避免把"该有真数据却没配"的问题彻底藏起来）。非 .pat 源缺失仍直接报错。

    复制 .pat 时把 HEADER 管脚行统一改写为 VERSION 管脚（对齐 fbist：CLK PIN/SWD PIN
    取自 VERSION，NRST 留字面由 dec 映射）。手工种子（enter_fbist_mode/exit_fbist_mode/
    read_status_mode）写死 PA14/PA13，靠此自愈；对生成端已正确的 pattern 是幂等替换。
    用字节级替换、只动 ASCII 管脚行，避免破坏文件内其它编码（中文注释）。"""
    if not os.path.isfile(source):
        if source.lower().endswith(".pat"):
            name = os.path.splitext(os.path.basename(source))[0]
            write_placeholder_pat(destination, name)
            return True
        raise FileNotFoundError("pattern 源文件缺失: " + source + "（目标 " + destination + "）")
    os.makedirs(destination, exist_ok=True)
    if source.lower().endswith(".pat"):
        with open(source, "rb") as fh:
            raw = fh.read()
        header = (G.col("VERSION", "CLK PIN")[0] + ", "
                  + G.col("VERSION", "SWD PIN")[0] + ", NRST;").encode("ascii")
        new_raw = _PAT_HEADER_RE.sub(lambda m: m.group(1) + header, raw, count=1)
        with open(os.path.join(destination, os.path.basename(source)), "wb") as fh:
            fh.write(new_raw)
        return True
    shutil.copy2(source, destination)
    return True


def trig_disp(trig_pin, is_default):
    """触发/发码 pattern 的**显示前缀**（2026-07-24 用户裁决："不要带 pin 名字"）：默认触发
    （step 无 `<PIN>:` 前缀、取 VERSION.GET PIN）用通用 `Trig`——生成的 pattern 名不再烤死
    真实 pin（如 PA0/PA13），方便复用/手改；显式 `<PIN>:` 指定的仍用该 pin 名。程序内默认
    触发脚唯一（每 CP 一个 GET PIN），故 `Trig_*` 在单个程序内无歧义。"""
    return "Trig" if is_default else trig_pin


def copy_trig_pat(base_real, base_disp, dest_dir):
    """把 pat_temp 里的触发/发码 pattern 种子（按**真实 pin** 命名，如 `PA0_send_num`）拷进
    程序 pat 目录、文件名+内部 `SPM_PATTERN` 名都改成**显示名**（默认→`Trig_*`）；HEADER 驱动
    脚保持真实 pin（内容不变，单管脚 HEADER 不被 `_PAT_HEADER_RE` 匹配）。`base_disp==base_real`
    （显式 pin）时等价 copy_file。种子缺失走占位兜底（名用显示名）。"""
    src = G.BASE_DIR + "\\pat_temp\\" + base_real + ".pat"
    if base_disp == base_real:
        copy_file(src, dest_dir)
        return
    if not os.path.isfile(src):
        write_placeholder_pat(dest_dir, base_disp)
        return
    os.makedirs(dest_dir, exist_ok=True)
    with open(src, "rb") as fh:
        raw = fh.read()
    header = (G.col("VERSION", "CLK PIN")[0] + ", "
              + G.col("VERSION", "SWD PIN")[0] + ", NRST;").encode("ascii")
    raw = _PAT_HEADER_RE.sub(lambda m: m.group(1) + header, raw, count=1)   # 单管脚头不匹配，仅与 copy_file 对齐
    raw = raw.replace(b"SPM_PATTERN(" + base_real.encode() + b")",
                      b"SPM_PATTERN(" + base_disp.encode() + b")")
    with open(os.path.join(dest_dir, base_disp + ".pat"), "wb") as fh:
        fh.write(raw)


# keil step 电平序列 token（2026-07-15，泛化自原写死"高5ms低5ms"的 HL）：
# token 是任意长度 H/L 序列，逐字符一段电平（段数=字符数）；紧跟的 <数字><ns|us|ms>
# 指定每段宽度，默认 5ms。宽度→RPT 数按 TS1 周期(200ns)换算，须整除（母本填错生成期
# 暴露）。writers.py 的 _keil_step_write（token 识别/引用名）与本文件（收集/生成）
# 共用这几个 helper，避免解析逻辑漂移。
_TS1_NS = 200
_DEFAULT_WIDTH_STR = "5ms"
LEVEL_SEQ_RE = re.compile(r'[HL]+')
_PULSE_WIDTH_RE = re.compile(r'(\d+)(ns|us|ms)', re.I)   # 大小写不敏感（用户裁决 2026-07-24：nS/US/MS 都认）
_WIDTH_UNIT_NS = {"ns": 1, "us": 1000, "ms": 1000000}


def parse_pulse_width(tok):
    """'2ms'/'500us'/'1000ns'（单位大小写不限）→ (rpt, width_str)；不是宽度 token 返回
    None；非 TS1(200ns) 正整数倍抛异常。width_str 单位归一化小写，保证 pattern 名一致。"""
    m = _PULSE_WIDTH_RE.fullmatch(str(tok).strip())
    if not m:
        return None
    ns = int(m.group(1)) * _WIDTH_UNIT_NS[m.group(2).lower()]
    if ns <= 0 or ns % _TS1_NS != 0:
        raise ValueError("keil step 脉冲宽度 '" + str(tok) + "' 必须是 TS1 周期 "
                         + str(_TS1_NS) + "ns 的正整数倍")
    return ns // _TS1_NS, m.group(1) + m.group(2).lower()


def default_pulse():
    """不带宽度 token 时的默认 (rpt, width_str)。"""
    return parse_pulse_width(_DEFAULT_WIDTH_STR)


def level_seq_pat_name(pin, levels, width_str):
    """电平序列 pattern 名：<pin>_<levels小写>_<width>（如 PA0_hlhl_5ms）。"""
    return pin + "_" + levels.lower() + "_" + width_str


def _level_seq_pat_write(path, pin, levels, rpt, width_str):
    """<pin>_<levels>_<width>.pat：keil 组 step 电平序列 token（H/L 任意长度，逐字符
    一段电平，每段宽度=rpt×TS1(200ns)）用的触发向量。2026-07-15 把原写死"高5ms低5ms"
    脉冲的 _force_1_0_pat_write 泛化而来（用户裁决：token 数数、宽度可配、去掉预置低、
    统一新命名）。preamble 只留 *X*RPT100 高阻建立，随后逐字符段（H→*1*、L→*0*，各
    RPT rpt），末尾 STOP。"""
    name = level_seq_pat_name(pin, levels, width_str)
    with open(path, "w") as f:
        f.write('SET_DEC_FILE "pin.dec"\n\nHEADER\n\n' + pin + ';\n\n'
                'SPM_PATTERN(' + name + ') {\n\n')
        f.write("  *X*TS1;\n  *X*RPT 100;\n")
        for ch in levels:
            f.write("  *" + ("1" if ch == "H" else "0") + "*RPT " + str(rpt) + ";\n")
        f.write("  *X*STOP;\n}\n")


def _send_num_pat_write(path, get_pin):
    """<GET_PIN>_send_num.pat：keil 组紧凑记法裸数字 token 用的发码向量，0x00~0xFF
    共 256 个数值，每个用 s<HH>_ST/s<HH>_SP 标签对包住其 8 位串行编码（MSB 先）。
    内容来自用户提供的 temp/Trigger_Num.SD（S100 .sd 格式，2026-07-02）逐拍翻译；
    标签命名用十六进制+ST/SP 后缀对齐 S100 风格（用户裁决），十六进制与本项目已有的
    decimal_to_hex 编码一致；**不能用 "0x" 前缀**——CRAFT 标识符按 C 规则解析，数字
    开头会被当数字字面量解析、报 Undefined symbol（2026-07-02 实测坐实，故用字母
    前缀 "s"，与 _keil_step_write 的 JUDGE_PAT 引用一一对应）。"""
    with open(path, "w") as f:
        f.write('SET_DEC_FILE "pin.dec"\n\nHEADER\n\n' + get_pin + ';\n\n'
                'SPM_PATTERN(' + get_pin + '_send_num) {\n\n')
        f.write("  *X*TS1;\n  *X*;\n  *X*RPT 100;\n  *X*;\n")
        for n in range(256):
            hh = decimal_to_hex(n)
            bits = format(n, "08b")
            f.write("s" + hh + "_ST:\n")
            f.write("  *X*;\n  *X*;\n  *1*RPT 632;\n  *0*RPT 422;\n  *1*RPT 422;\n  *0*RPT 422;\n\n")
            f.write("  *" + bits[0] + "*RPT 422;// 0x" + hh + "\n")
            f.write("  *" + bits[1] + "*RPT 422;\n  *" + bits[2] + "*RPT 422;\n  *" + bits[3] + "*RPT 422;\n\n")
            f.write("  *" + bits[4] + "*RPT 422;\n  *" + bits[5] + "*RPT 422;\n  *" + bits[6] + "*RPT 422;\n")
            f.write("  *" + bits[7] + "*RPT 502;\n")
            f.write("s" + hh + "_SP:\n  *X*;\n\n")
        f.write("  *X*;\n  *X*RPT 500;\n  *X*;\n  *X*;\n  *X*STOP;\n}\n")


def _reset_pattern_pat_write(path):
    """reset_pattern.pat：keil 组紧凑记法 "T" token 收尾用。除 NRST 外全部管脚给 X，
    NRST 先 1 RPT5000 后 0 RPT5000（用户裁决字面描述，2026-07-02）。沿用项目统一的
    3 管脚 HEADER 约定（VERSION CLK PIN/SWD PIN + 字面量 NRST，与 copy_file 的
    HEADER 改写正则一致，虽然这里本就正确不需要改写）。"""
    with open(path, "w") as f:
        header = G.col("VERSION", "CLK PIN")[0] + ", " + G.col("VERSION", "SWD PIN")[0] + ", NRST;"
        f.write('SET_DEC_FILE "pin.dec"\n\nHEADER\n\n' + header
                + '\n\nSPM_PATTERN(reset_pattern) {\n\n')
        f.write("  *XX1*TS1,RPT 5000;\n  *XX0*RPT 5000;\n  *XX0*STOP;\n}\n")


def _compare_pat_write(path, pin1, pin2, state):
    """<pin1><pin2>_compare_<state>.pat：keil 组紧凑记法 "T" token 在 UNIT=="pat" 时
    用的管脚对电平比较 pattern（见 _keil_step_write）。骨架来自用户提供的真实参考样本
    `temp/V_PY2208V1_.../PAT/judge_PA2PB6_HH.pat`（+`_HL.pat`）逐拍照抄（2026-07-03）：
    两拍框架 X 电平热身，中段 4 拍用 state 两字符原样做双管脚同时比较状态（如
    state="HH" → 每拍写 *HH*，两个管脚各自都判"期望读到 H"；state="HL" → 第一个管脚
    判 H、第二个判 L，以此类推——state 字符串本身就是要写进向量的比较状态，不是标签），
    末尾 X 收尾 STOP。"""
    with open(path, "w") as f:
        f.write('SET_DEC_FILE "pin.dec"\n\nHEADER\n' + pin1 + ',' + pin2 + ';\n\n'
                'SPM_PATTERN(' + pin1.lower() + pin2.lower() + '_compare_' + state.lower() + ') {\n\n')
        f.write("  *XX*TS1;\n  *XX*RPT 100;\n  *XX*RPT 100;\n")
        f.write("  *" + state + "*;\n  *" + state + "*;\n  *" + state + "*RPT 100;\n  *" + state + "*;\n")
        f.write("  *XX*;\n  *XX*;\n  *XX*STOP;\n}\n")


def get_pin_patterns_created(code_name):
    """<GET_PIN>_force_1_0.pat / <GET_PIN>_send_num.pat / reset_pattern.pat /
    <pin1><pin2>_compare_<state>.pat：keil 组紧凑记法（_keil_step_write）引用的
    pattern，此前从未真正生成过（keil 组一直被另一处入口行判断 bug 吞掉，从没端到端
    跑出过内容，这个缺口才没暴露——2026-07-02 交接记录）。触发管脚有两个来源，取并集
    去重后各生成一份到 pat_temp（多个 CP/sub 共用同一管脚时只生成一次，与项目里
    enter_fbist_mode 等共享种子同一惯例）：
      ① VERSION.GET PIN 逐 CP 取值（默认触发管脚，同一母本内不同 CP 可能不同，如 PB6/PB2）；
      ② FLOW 里 type=="verify" and mode=="keil" 行的 step 列若带 "<PIN>:" 前缀
         （每行可覆盖自己的触发管脚，见 _keil_step_write，用户裁决 2026-07-02；
         一格可按真实换行分多组、每组各自可能带不同前缀，2026-07-03 逐行都要扫）。
    reset_pattern 与触发管脚无关，只需生成一份。compare pattern 按 FLOW 里
    type=="verify" and mode=="keil" and UNIT=="pat" 的行去重生成（meas pin 列=
    "<PIN1>+<PIN2>"、target 列=比较状态字符串，如 "HH"/"HL"，2026-07-03）。"""
    seen_pins = set()
    for i in range(len(code_name)):
        get_pin = G.col("VERSION", "GET PIN")[i]
        if get_pin not in seen_pins:
            seen_pins.add(get_pin)
    flow_type = G.col("FLOW", "type")
    flow_mode = G.col("FLOW", "mode")
    flow_step = G.col("FLOW", "step")
    flow_unit = G.col("FLOW", "UNIT")
    flow_meas_pin = G.col("FLOW", "meas pin")
    flow_target = G.col("FLOW", "target")
    flow_fv_fi = G.col("FLOW", "FV/FI")
    seen_compare = set()
    seen_seqs_any = set()     # (levels, width_str, rpt)：不带前缀，配所有 GET PIN
    seen_seqs_pinned = set()  # (pin, levels, width_str, rpt)：带 <PIN>: 前缀，仅该管脚
    for k in range(len(flow_type)):
        if flow_type[k] == "verify" and flow_mode[k] == "keil":
            for line in str(flow_step[k]).strip().splitlines():
                line = line.strip()
                if not line:
                    continue
                if ":" in line:
                    trig_pin, rest = line.split(":", 1)
                    trig_pin = trig_pin.strip()
                    seen_pins.add(trig_pin)
                else:
                    trig_pin, rest = None, line
                # 扫电平序列 token（H/L 任意长度）+ 紧跟的可选宽度 token，收集
                # (管脚, 序列, 宽度) 组合供按需生成（不带 <PIN>: 前缀的配所有 GET PIN，
                # 与 _keil_step_write 里"不带前缀用当前 CP 的 GET PIN"一致但跨 CP 保守
                # 展开）。解析规则与 _keil_step_write 共用同一批 helper，避免漂移。
                toks = rest.split("-")
                j = 0
                while j < len(toks):
                    if LEVEL_SEQ_RE.fullmatch(toks[j]):
                        levels = toks[j]
                        rpt, width_str = default_pulse()
                        if j + 1 < len(toks) and parse_pulse_width(toks[j + 1]):
                            rpt, width_str = parse_pulse_width(toks[j + 1])
                            j += 1
                        if trig_pin is None:
                            seen_seqs_any.add((levels, width_str, rpt))
                        else:
                            seen_seqs_pinned.add((trig_pin, levels, width_str, rpt))
                    j += 1
            # UNIT=="pat" 行照旧；此外 step 含 "F" 且 FV/FI 是外灌时钟格式的行，
            # "不同 PMU 组"结果也要走同一套 <pin1><pin2>_compare_<state> 数字比较
            # pattern（2026-07-07 用户裁决），母本这类行 UNIT 一律填 "/"，不能只靠
            # UNIT=="pat" 判断；**但 "F" 走电压/电流 force 的行**（如 Power_Test，
            # FV/FI="VCC_MAX"）不属于这里——用 `is_clock_force_cell` 精确区分，不能
            # 只看 step 有没有 "F"（否则 meas pin 是单管脚会在 split("+") 处炸掉）。
            from program_gen.core.clock_force import is_clock_force_cell
            # PVD/COMP 哨兵行跳过：两者 UNIT 也可填 pat，但 target/meas pin 是分派哨兵；
            # compare pattern 分别由专用 writer 根据独立 sheet 生成。
            if (str(flow_unit[k]).strip().lower() == "pat" or is_clock_force_cell(flow_fv_fi[k])) \
                    and str(flow_fv_fi[k]).strip().upper() not in {"PVD", "COMP"}:
                pin1, pin2 = str(flow_meas_pin[k]).split("+", 1)
                state = str(flow_target[k]).strip().upper()
                seen_compare.add((pin1.strip(), pin2.strip(), state))
    # hex 模式的 "trigger" step 及默认触发都用默认脉冲 <pin>_hl_5ms（等价原来无条件
    # 生成的 force_1_0），无条件为每个 GET PIN 备一份。
    _dp_rpt, _dp_w = default_pulse()
    seen_seqs_any.add(("HL", _dp_w, _dp_rpt))
    for pin in seen_pins:
        _send_num_pat_write(G.BASE_DIR + "\\pat_temp\\" + pin + "_send_num.pat", pin)
        for levels, width_str, rpt in seen_seqs_any:
            _level_seq_pat_write(G.BASE_DIR + "\\pat_temp\\"
                                 + level_seq_pat_name(pin, levels, width_str) + ".pat",
                                 pin, levels, rpt, width_str)
    for pin, levels, width_str, rpt in seen_seqs_pinned:
        _level_seq_pat_write(G.BASE_DIR + "\\pat_temp\\"
                             + level_seq_pat_name(pin, levels, width_str) + ".pat",
                             pin, levels, rpt, width_str)
    for pin1, pin2, state in seen_compare:
        name = pin1.lower() + pin2.lower() + "_compare_" + state.lower()
        _compare_pat_write(G.BASE_DIR + "\\pat_temp\\" + name + ".pat", pin1, pin2, state)
    _reset_pattern_pat_write(G.BASE_DIR + "\\pat_temp\\reset_pattern.pat")


def _clkloop_pat_write(path, pin):
    """<pin>_clkloop.pat：RCC/RTC 外灌时钟 Chroma"同 PMU 组"降级分支用的纯翻转
    pattern（2026-07-07 用户裁决+提供参考 temp/freq/OSC_IN_24MHZ.pat）。单管脚
    HEADER，50% 占空比（1 低 1 高交替），用 TS3（专门留给 pattern 出频率的号位，
    见 startup.py 的 TS3 声明）控制节拍，`JCONT LOOP` 无限翻转——调用方（writers.py
    的 _emit_clock_force）负责用 JUDGE_PAT 启动、之后必须配对 PAT_CONTINUE() 打断，
    不会自己退出。"""
    with open(path, "w") as f:
        f.write('SET_DEC_FILE "pin.dec"\n\nHEADER\n\n' + pin + ';\n\n'
                'SPM_PATTERN(' + pin.lower() + '_clkloop) {\n\n')
        f.write("  *X*TS3;\n  *X*;\n  *X*;\n"
                "LOOP:  *0*;\n  *1*JCONT LOOP;\n"
                "  *X*;\n  *X*;\n  *X*;\n  *X*STOP;\n}\n")


def clock_force_pattern_created():
    """RCC/RTC 外灌时钟 Chroma"同 PMU 组"降级分支要用的 <pin>_clkloop.pat，按 FLOW
    里所有 step 含 "F" 的行、跨全部 CP 反查需要降级的管脚，去重后各生成一份
    （2026-07-07 用户裁决，见 clock_force.chroma_downgrade_pins）。没有任何降级
    需求时不生成任何文件（此时 startup.py 也不会声明 TS3，pattern 引用不到 TS3
    也就无从谈起）。"""
    from program_gen.core.clock_force import chroma_downgrade_pins
    for pin in chroma_downgrade_pins():
        _clkloop_pat_write(G.BASE_DIR + "\\pat_temp\\" + pin + "_clkloop.pat", pin)


def fbist_pattern_created(pattern_compilation):
    """Legacy entry: run the plan-driven Chroma generator and publish the
    immutable artifacts into ``pat_temp`` (text-mode newline translation keeps
    the files byte-identical to the historical writer).  The generator itself
    only consumes the upstream ``FbistPatternGenerationPlan``.
    """
    from program_gen.platforms.chroma.fbist_pattern_generator import (
        generate_fbist_patterns,
    )

    result = generate_fbist_patterns(pattern_compilation)
    os.makedirs(G.BASE_DIR + "\\pat_temp", exist_ok=True)
    for artifact in result.artifacts:
        path = os.path.join(
            G.BASE_DIR, "pat_temp", artifact.pattern_name + ".pat"
        )
        with open(path, "w") as fh:
            fh.write(artifact.content.decode("ascii"))


def flash_compare_patterns_created(compilation):
    """Publish workbook-free Required Flash Compare artifacts into pat_temp."""
    from program_gen.core.flash_compare_renderer import render_flash_compare_plans

    plans = compilation.require_complete().plans
    result = render_flash_compare_plans(plans, "chroma")
    destination = os.path.join(G.BASE_DIR, "pat_temp")
    os.makedirs(destination, exist_ok=True)
    for artifact in result.artifacts:
        path = os.path.join(destination, artifact.pattern_name + ".pat")
        with open(path, "wb") as stream:
            stream.write(artifact.content)
    return result
