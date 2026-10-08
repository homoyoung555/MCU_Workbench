# S100 平台：.sd pattern 文件生成。
import os
import re
import shutil

from program_gen.core.encoding import decimal_to_hex
from program_gen import state as G


# tool
def copy_file(source, destination):
    """复制单个文件到目标目录"""
    try:
        # 确保目标目录存在
        os.makedirs(os.path.dirname(destination), exist_ok=True)

        # 执行复制
        shutil.copy2(source, destination)
        # print(f"文件复制成功: {source} -> {destination}")
        return True
    except Exception as e:
        # print(f"复制失败: {str(e)}")
        # print(source,type(source))
        with open(G.BASE_DIR + "\\pat_temp\\" + source.split("pat_temp")[1].split("\\")[1], 'w') as f:
            f.write(
                'HEAD[PIN_NAME]:\n\nPA14, PA13, NRST;\n\nEND_HEAD;\n\n@@PATTERN_DEFINE\n\n')
            f.write("START:011;;\n      011;RPT 100;\n")
            f.write("\n      111;\n      111;RPT 1000;// wait 100us \n      111;\n  END:011;\n\n@@END_PATTERN_DEFINE \n")
        with open(destination+"\\" + source.split("pat_temp")[1].split("\\")[1], 'w') as f:
            f.write(
                'HEAD[PIN_NAME]:\n\nPA14, PA13, NRST;\n\nEND_HEAD;\n\n@@PATTERN_DEFINE\n\n')
            f.write("START:011;;\n      011;RPT 100;\n")
            f.write("\n      111;\n      111;RPT 1000;// wait 100us \n      111;\n  END:011;\n\n@@END_PATTERN_DEFINE \n")

        return False


def trig_disp(trig_pin, is_default):
    """触发/发码 pattern 的**显示前缀**（2026-07-24 用户裁决，对称 chroma）：默认触发
    （step 无 `<PIN>:` 前缀、取 VERSION.GET PIN）用通用 `Trig`——不烤死真实 pin 名；
    显式 `<PIN>:` 指定的仍用该 pin 名。程序内默认触发脚唯一，`Trig_*` 无歧义。"""
    return "Trig" if is_default else trig_pin


def copy_trig_sd(base_real, base_disp, dest_dir):
    """把 pat_temp 里的触发/发码 .sd 种子（按**真实 pin** 命名）拷进程序目录、文件名改成
    **显示名**（默认→`Trig_*`）。S100 .sd 以文件名为 pattern 标识、无内部名，HEADER 驱动脚
    保持真实 pin 不改。`base_disp==base_real`（显式 pin）时等价 copy_file。产物由
    get_sd_filenames_with_os 扫目录登记进 .prj PATTERN_NAME。"""
    src = G.BASE_DIR + "\\pat_temp\\" + base_real + ".sd"
    if base_disp == base_real:
        copy_file(src, dest_dir)
        return
    os.makedirs(dest_dir, exist_ok=True)
    shutil.copy2(src, os.path.join(dest_dir, base_disp + ".sd"))


# keil step 电平序列 token（2026-07-15，对称 chroma/pattern_files.py，泛化自原写死
# "高1ms低1ms"的 HL）：token 是任意长度 H/L 序列，逐字符一段电平；紧跟的
# <数字><ns|us|ms> 指定每段宽度，默认 1ms（S100 现状值，chroma 侧默认是 5ms，两平台
# 各自向后兼容）。宽度→RPT 数按时序周期(200ns)换算，须整除。writers.py 的
# _keil_step_write 与本文件共用这几个 helper，避免解析漂移。
_TS_NS = 200
_DEFAULT_WIDTH_STR = "1ms"
LEVEL_SEQ_RE = re.compile(r'[HL]+')
_PULSE_WIDTH_RE = re.compile(r'(\d+)(ns|us|ms)', re.I)   # 大小写不敏感（用户裁决 2026-07-24：nS/US/MS 都认）
_WIDTH_UNIT_NS = {"ns": 1, "us": 1000, "ms": 1000000}


def parse_pulse_width(tok):
    """'2ms'/'500us'/'1000ns'（单位大小写不限）→ (rpt, width_str)；不是宽度 token 返回
    None；非时序周期(200ns) 正整数倍抛异常。width_str 单位归一化小写，保证 pattern 名一致。"""
    m = _PULSE_WIDTH_RE.fullmatch(str(tok).strip())
    if not m:
        return None
    ns = int(m.group(1)) * _WIDTH_UNIT_NS[m.group(2).lower()]
    if ns <= 0 or ns % _TS_NS != 0:
        raise ValueError("keil step 脉冲宽度 '" + str(tok) + "' 必须是时序周期 "
                         + str(_TS_NS) + "ns 的正整数倍")
    return ns // _TS_NS, m.group(1) + m.group(2).lower()


def default_pulse():
    """不带宽度 token 时的默认 (rpt, width_str)（S100=1ms）。"""
    return parse_pulse_width(_DEFAULT_WIDTH_STR)


def level_seq_pat_name(pin, levels, width_str):
    """电平序列 pattern 名：<pin>_<levels小写>_<width>（如 PA0_hlhl_1ms）。"""
    return pin + "_" + levels.lower() + "_" + width_str


def _level_seq_sd_write(path, pin, levels, rpt, width_str):
    """<pin>_<levels>_<width>.sd：S100 keil 组 step 电平序列 token（H/L 任意长度，逐
    字符一段电平，每段宽度=rpt×时序周期(200ns)）用的触发向量。2026-07-15 把原写死
    "高1ms低1ms"的 _force_1_0_sd_write 泛化而来（对称 chroma）。preamble 只留
    START:X + X;RPT100 高阻建立（去掉预置低），随后逐字符段（H→1、L→0，各 RPT rpt），
    END:X 收尾。RUN_PATTERN 靠 :START/:END 标签引用。"""
    name = level_seq_pat_name(pin, levels, width_str)
    with open(path, "w") as f:
        f.write('HEAD[PIN_NAME]:\n\n' + pin + ';\n\nEND_HEAD;\n\n@@PATTERN_DEFINE\n\n')
        f.write("START:X;\n      X;RPT 100;\n")
        for ch in levels:
            f.write("      " + ("1" if ch == "H" else "0") + ";RPT " + str(rpt) + ";\n")
        f.write("  END:X;\n\n@@END_PATTERN_DEFINE\n")


def _send_num_sd_write(path, get_pin):
    """<GET_PIN>_send_num.sd：S100 keil 组紧凑记法裸数字 token 用的发码向量，0~255
    共 256 个数值，每个用 s<3位十进制>_ST/s<3位十进制>_SP 标签对包住其 8 位串行编码
    （MSB 先，末尾另加 1 位固定 0 停止位）。2026-07-06 移植（用户提供真实参考
    `temp/LAB_PY32F420A_C8_25C_V00_50_1SS_FT/Trigger_Num.SD`，逐拍照抄）。
    **标签用 3 位十进制**（s000~s255），跟 Chroma 版 `_send_num_pat_write` 的十六进制
    标签（s00~sFF）不同——两边各自照抄各自平台的真实参考样本，命名风格不必强求一致。"""
    with open(path, "w") as f:
        f.write('HEAD[PIN_NAME]:\n\n' + get_pin + ';\n\nEND_HEAD;\n\n@@PATTERN_DEFINE\n\n')
        f.write("START:X;\n      X;\n      X;RPT 100;\n      X;\n")
        for n in range(256):
            hh = decimal_to_hex(n)
            bits = format(n, "08b")
            label = "s%03d" % n
            f.write(label + "_st:X;\n")
            f.write("      X;\n      1;RPT 632;\n      0;RPT 422;\n      1;RPT 422;\n      0;RPT 422;\n\n")
            f.write("      " + bits[0] + ";RPT 422;//0x" + hh + "\n")
            f.write("      " + bits[1] + ";RPT 422;\n      " + bits[2] + ";RPT 422;\n      " + bits[3] + ";RPT 422;\n\n")
            f.write("      " + bits[4] + ";RPT 422;\n      " + bits[5] + ";RPT 422;\n      "
                    + bits[6] + ";RPT 422;\n      " + bits[7] + ";RPT 422;\n      0;RPT 502;\n")
            f.write(label + "_sp:X;\n\n")
        f.write("      X;\n      X;\n      X;RPT 500;\n      X;\n      X;\n      X;\n"
                "END:  X;\n\n@@END_PATTERN_DEFINE\n")


def _compare_sd_write(path, pin1, pin2, state):
    """<pin1><pin2>_Cmp_<state>.sd：S100 keil 组紧凑记法 "T" token 在 UNIT=="pat" 时
    用的管脚对电平比较向量。2026-07-06 移植（用户提供真实参考
    `temp/L_PCD2509V1_PY32F420A_C8_30C_V00_50_12SS_CP1/PA11PA13_Cmp_HH.sd`，逐拍照抄，
    命名对齐真实样本 `<PIN1><PIN2>_Cmp_<STATE>`，两个管脚都保持大写、state 大写）。"""
    with open(path, "w") as f:
        f.write('HEAD[PIN_NAME]:\n\n' + pin1 + ',' + pin2 + ';\n\nEND_HEAD;\n\n@@PATTERN_DEFINE\n\n')
        f.write("START:XX;\n      XX;RPT 100;\n\n")
        f.write("      " + state + ";\n      " + state + ";RPT 500;// wait 100uS\n      " + state + ";\n\n")
        f.write("      XX;\n  END:XX;\n\n@@END_PATTERN_DEFINE \n")


def get_pin_patterns_created(code_name):
    """<GET_PIN>_force_1_0.sd / <GET_PIN>_send_num.sd / <pin1><pin2>_Cmp_<state>.sd：
    S100 keil 组紧凑记法（`s100/writers.py:_keil_step_write`）引用的 pattern。
    2026-07-06 移植（对齐 `chroma/pattern_files.py:get_pin_patterns_created` 的收集
    逻辑：GET PIN 逐 CP 取值 + FLOW 里 `"<PIN>:"` 前缀覆盖去重 + `UNIT=="pat"` 的
    管脚对比较去重生成，S100 侧没有 reset_pattern——真实参考里每个 sub 各自独立一次
    POWER_ON/POWER_OFF，物理上电本身就是复位，不需要额外 reset pattern）。"""
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
                # (管脚, 序列, 宽度) 组合供按需生成（与 _keil_step_write 共用 helper）。
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
            # UNIT=="pat" 行照旧；此外 step 含 "F" 且 FV/FI 是外灌时钟格式的行也要
            # 走同一套 <pin1><pin2>_Cmp_<state> 数字比较 pattern（2026-07-07 用户
            # 裁决），母本这类行 UNIT 一律填 "/"；**但 "F" 走电流 force 的行**（如
            # Power_Test，FV/FI="VCC_MAX"）不属于这里，用 `is_clock_force_cell`
            # 精确区分（否则 meas pin 单管脚会在 split("+") 处炸掉）。
            from program_gen.core.clock_force import is_clock_force_cell
            # PVD/COMP 哨兵行跳过：compare pattern 由各自专用 writer 根据独立 sheet 生成。
            if (str(flow_unit[k]).strip().lower() == "pat" or is_clock_force_cell(flow_fv_fi[k])) \
                    and str(flow_fv_fi[k]).strip().upper() not in {"PVD", "COMP"}:
                pin1, pin2 = str(flow_meas_pin[k]).split("+", 1)
                state = str(flow_target[k]).strip().upper()
                seen_compare.add((pin1.strip(), pin2.strip(), state))
    # hex 模式的 "trigger" step 及默认触发都用默认脉冲 <pin>_hl_1ms（等价原来无条件
    # 生成的 force_1_0），无条件为每个 GET PIN 备一份。
    _dp_rpt, _dp_w = default_pulse()
    seen_seqs_any.add(("HL", _dp_w, _dp_rpt))
    for pin in seen_pins:
        _send_num_sd_write(G.BASE_DIR + "\\pat_temp\\" + pin + "_send_num.sd", pin)
        for levels, width_str, rpt in seen_seqs_any:
            _level_seq_sd_write(G.BASE_DIR + "\\pat_temp\\"
                                + level_seq_pat_name(pin, levels, width_str) + ".sd",
                                pin, levels, rpt, width_str)
    for pin, levels, width_str, rpt in seen_seqs_pinned:
        _level_seq_sd_write(G.BASE_DIR + "\\pat_temp\\"
                            + level_seq_pat_name(pin, levels, width_str) + ".sd",
                            pin, levels, rpt, width_str)
    for pin1, pin2, state in seen_compare:
        name = pin1 + pin2 + "_Cmp_" + state
        _compare_sd_write(G.BASE_DIR + "\\pat_temp\\" + name + ".sd", pin1, pin2, state)


def _clkloop_sd_sr_write(sd_path, sr_path, pin):
    """<pin>_clkloop.sd + R<pin>_clkloop.sr：RCC/RTC 外灌时钟 S100 <600kHz 降级分支
    用的纯翻转 pattern（2026-07-07 用户裁决+参考 temp/freq/PC14_37KHZ.sd+
    RPC14_37KHZ.sr）。主 .sd 只在 START 段 `SUB_CONT_ON` 常驻调子程序（节拍由
    GROUP_3/AC_SET_1 提供，见 project_files.py:tim_hed_write），子程序 `0,1;RTN`
    两拍翻转——50% 占空比（用户裁决），比参考的 `0,0,1;RTN`（33%）更简单；**`RTN`
    后必须再跟至少一行**（编译实测坐实："Subroutine pattern(.sr) RTN mi code must
    not at the last pattern line!"——参考里 `RTN` 后也跟了 2 行没被真正执行到的
    `11;XX;`，起初误当成死代码，其实是编译器语法要求的收尾行，不能省）。TRIGPIN
    是参考本来就有的第二列（占位不参与翻转），照抄保留。"""
    label = pin.lower() + "_clkloop"
    with open(sd_path, "w") as f:
        f.write('HEAD[PIN_NAME]:\n\n' + pin + ',TRIGPIN,\n\nEND_HEAD;\n\n@@PATTERN_DEFINE\n\n')
        f.write("START:0X;\n      XX;SUB_CONT_ON R" + label + ":" + label + ";\n"
                "      0X;\n      0X;\n  END:0X;\n\n@@END_PATTERN_DEFINE\n")
    with open(sr_path, "w") as f:
        f.write('HEAD[PIN_NAME]:\n\n' + pin + ',TRIGPIN\n\nEND_HEAD;\n\n@@PATTERN_DEFINE\n\n')
        f.write("      " + label + ":0X;\n      1X;RTN;\n      XX;\n\n@@END_PATTERN_DEFINE\n")


def clock_force_pattern_created():
    """RCC/RTC 外灌时钟 S100 <600kHz 降级分支要用的 <pin>_clkloop.sd/R<pin>_clkloop.sr，
    按 FLOW 里所有 step 含 "F" 的行、跨全部 CP 反查需要降级（<600kHz）的管脚，去重后
    各生成一对（2026-07-07 用户裁决，见 clock_force.s100_downgrade_pins）。没有降级
    需求时不生成任何文件。"""
    from program_gen.core.clock_force import s100_downgrade_pins
    for pin in s100_downgrade_pins():
        # 文件名必须跟 .sd 内 "SUB_CONT_ON R<name>:<name>" 引用的大小写完全一致
        # （2026-07-07 编译实测坐实：caller 原先用原始大小写拼路径、内部引用却统一
        # 转小写，两边对不上导致 "SUB_CONT_ON label_name not found"），统一用小写。
        name = pin.lower() + "_clkloop"
        _clkloop_sd_sr_write(G.BASE_DIR + "\\pat_temp\\" + name + ".sd",
                             G.BASE_DIR + "\\pat_temp\\R" + name + ".sr", pin)


def fbist_pattern_created(pattern_compilation):
    """Legacy entry: run the plan-driven S100 generator and publish the
    immutable artifacts into ``pat_temp`` (text-mode newline translation keeps
    the files byte-identical to the historical writer).  The generator itself
    only consumes the upstream ``FbistPatternGenerationPlan``.
    """
    from program_gen.platforms.s100.fbist_pattern_generator import (
        generate_fbist_patterns,
    )

    result = generate_fbist_patterns(pattern_compilation)
    os.makedirs(G.BASE_DIR + "\\pat_temp", exist_ok=True)
    for artifact in result.artifacts:
        path = os.path.join(
            G.BASE_DIR, "pat_temp", artifact.pattern_name + ".sd"
        )
        with open(path, "w") as fh:
            fh.write(artifact.content.decode("ascii"))


def flash_compare_patterns_created(compilation):
    """Publish workbook-free Required Flash Compare artifacts into pat_temp."""
    from program_gen.core.flash_compare_renderer import render_flash_compare_plans

    plans = compilation.require_complete().plans
    result = render_flash_compare_plans(plans, "s100")
    destination = os.path.join(G.BASE_DIR, "pat_temp")
    os.makedirs(destination, exist_ok=True)
    for artifact in result.artifacts:
        path = os.path.join(destination, artifact.pattern_name + ".sd")
        with open(path, "wb") as stream:
            stream.write(artifact.content)
    return result
