# RCC/RTC 外灌时钟共用逻辑（两平台共用，纯计算/查表，不写文件）。
# 背景：RCC/RTC 测试项在 F5（keil write）族里，跟 Sram_Test 同构，只是 step 列多一个
# "F" token、FV/FI 列换成 "<PIN>:<freq><单位>"（可多行）表示外灌时钟。2026-07-07 用户
# 裁决记录见 .Codex/handoffs/2026-07-07-analog-test-family-classification-decision.md。
import re

from program_gen import state as G
from program_gen.platforms.chroma.project_files import process_pin_name

_FREQ_RE = re.compile(r'^([A-Za-z0-9_]+):([0-9]+(?:\.[0-9]+)?)\s*(Hz|kHz|MHz)$', re.IGNORECASE)
_UNIT_MULT = {"hz": 1.0, "khz": 1e3, "mhz": 1e6}


def is_clock_force_cell(cell_value):
    """判断 FV/FI 单元格是不是外灌时钟格式（`<PIN>:<freq><Hz|kHz|MHz>`，可多行）。
    2026-07-07 用户裁决扩展："F" token 不只管外灌时钟——FV/FI 是这个格式就走外灌
    时钟，**不是**就走"force 该行 meas pin 的电压/电流"（按 UNIT 列：uA→force 电压
    /judge 电流，V→force 电流/judge 电压，同 `Force_Judge` 既有的 V/uA 判据）。
    只看第一行是否匹配即可区分两种用途，不需要完整解析、不抛异常。"""
    first_line = str(cell_value).strip().splitlines()[0].strip() if str(cell_value).strip() else ""
    return bool(_FREQ_RE.match(first_line))


def parse_freq_cell(cell_value):
    """解析 FV/FI 列的 "<PIN>:<freq><Hz|kHz|MHz>" 格式（可多行，真实换行分组，同 step
    列惯例）。返回 [(pin, freq_hz), ...]，保持原始行序（顺序对同 PMU 组降级判断里
    "频率高的留 TMU" 有意义，但真正决定用哪根的是频率大小，不是顺序，顺序只影响
    报错信息里"第几行"这种描述）。格式不对直接抛异常（母本填错要生成期立刻暴露）。"""
    lines = str(cell_value).strip().splitlines()
    result = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        m = _FREQ_RE.match(line)
        if not m:
            raise ValueError(
                "parse_freq_cell: 无法识别的外灌时钟格式 '" + line + "'，"
                "期望 '<PIN>:<数字><Hz|kHz|MHz>'，如 'PD0:24MHz'。")
        pin = m.group(1).strip()
        freq_hz = float(m.group(2)) * _UNIT_MULT[m.group(3).lower()]
        result.append((pin, freq_hz))
    if not result:
        raise ValueError("parse_freq_cell: FV/FI 内容为空，无法解析外灌时钟：'" + str(cell_value) + "'")
    return result


def half_period_ns(freq_hz):
    """50% 占空比方波：pattern 逐拍翻转一次，一拍=半周期。半周期(nS)=1e9/(2*freq)。"""
    return 1e9 / (2.0 * freq_hz)


def pmu_group(pin_name, cp_no):
    """Chroma 专用：按 PIN_DEC_128.Trace 反查该管脚所在 PMU 组（每 8 通道一组，
    group=trace//8）。2026-07-07 用户裁决：只有 Chroma 存在"同 PMU 组不能同时外灌
    不同频率"的资源限制，S100 没有这个概念，不要在 S100 侧调用本函数。

    pin_name 是 FLOW 里的短管脚名（如 "PD0"），PIN_DEC_128 的 "E/C(Pad Name)" 列是
    "PAD_PD[0]" 这种长格式，用 project_files.process_pin_name 统一转换后比对。"""
    pin_cp = G.col("PIN_DEC_128", "CP NO")
    pin_pad = G.col("PIN_DEC_128", "E/C(Pad Name)")
    pin_trace = G.col("PIN_DEC_128", "Trace")
    for u in range(len(pin_cp)):
        if pin_cp[u] == cp_no and process_pin_name(pin_pad[u]) == pin_name:
            return int(pin_trace[u]) // 8
    raise ValueError(
        "pmu_group: 在 PIN DEC（CP=" + str(cp_no) + "）里找不到管脚 '" + pin_name
        + "'，无法判断 PMU 组——请检查 FV/FI 列填的管脚名是否与 PIN DEC 一致。")


def split_by_group(pin_freqs, cp_no):
    """Chroma 专用：把 [(pin,freq_hz),...] 按 pmu_group 分组，同组内按频率降序排序
    （频率最高的排第 0 位=该组里唯一能留 TMU 的那根，其余同组的都要降级 pattern，
    2026-07-07 用户裁决："频率高的用 TMU"）。返回 {group: [(pin,freq_hz),...]}。"""
    groups = {}
    for pin, freq in pin_freqs:
        grp = pmu_group(pin, cp_no)
        groups.setdefault(grp, []).append((pin, freq))
    for grp in groups:
        groups[grp].sort(key=lambda pf: pf[1], reverse=True)
    return groups


def _step_has_f_token(step_cell):
    """判断 FLOW.step 单元格（可能多行，每行 '-' 分隔 token）里是否出现过独立的
    "F" token（外灌时钟标记，2026-07-07 用户在 step 列新加的第 5 种 token）。"""
    for line in str(step_cell).strip().splitlines():
        line = line.strip()
        if ":" in line:
            line = line.split(":", 1)[1]
        if "F" in line.split("-"):
            return True
    return False


def clock_force_rows(cp_no=None):
    """返回 FLOW 里所有 step 含 "F" token **且** FV/FI 是外灌时钟格式的行号（可选按
    CP NO 过滤），按原始顺序。2026-07-07 用户裁决扩展"F"语义后，"F" 也可能是走
    电压/电流 force（如 Power_Test，FV/FI="VCC_MAX"）——这类行不该被当成外灌时钟
    行处理（`parse_freq_cell` 会直接报格式错），必须用 `is_clock_force_cell` 再
    过滤一次，不能只看 step 有没有 "F"。"""
    flow_cp = G.col("FLOW", "CP NO")
    flow_step = G.col("FLOW", "step")
    flow_fv_fi = G.col("FLOW", "FV/FI")
    return [z for z in range(len(flow_step))
            if (cp_no is None or flow_cp[z] == cp_no) and _step_has_f_token(flow_step[z])
            and is_clock_force_cell(flow_fv_fi[z])]


def chroma_cell_plan(cell_value, cp_no):
    """Chroma 专用：给定外灌时钟单元格和 CP，返回执行计划
    {pin: {"freq_hz": float, "mode": "tmu"|"pattern"}}。单管脚行永远 "tmu"（Chroma
    的降级判据是"同 PMU 组资源冲突"，单管脚不存在冲突）；多管脚行按 PMU 组分组，
    每组频率最高的 "tmu"、其余 "pattern"（2026-07-07 用户裁决）。"""
    pin_freqs = parse_freq_cell(cell_value)
    if len(pin_freqs) == 1:
        pin, freq = pin_freqs[0]
        return {pin: {"freq_hz": freq, "mode": "tmu"}}
    groups = split_by_group(pin_freqs, cp_no)
    plan = {}
    for members in groups.values():
        plan[members[0][0]] = {"freq_hz": members[0][1], "mode": "tmu"}
        for pin, freq in members[1:]:
            plan[pin] = {"freq_hz": freq, "mode": "pattern"}
    return plan


def chroma_row_plan(z):
    """FLOW 行适配器；核心计算见 :func:`chroma_cell_plan`。"""
    return chroma_cell_plan(G.col("FLOW", "FV/FI")[z], G.col("FLOW", "CP NO")[z])


def _freq_sheet_force_cells(cp_no=None):
    """FREQ sheet 入口行引用到的外灌时钟单元格，供时序/pattern 预生成扫描。

    旧 FLOW 行仍由 clock_force_rows 扫描；新结构只在 FLOW.FV/FI=FREQ 时读取同 item
    的 FREQ 组，因此两种母本互不干扰。
    """
    import analog_sweep as A

    result = []
    flow_cp = G.col("FLOW", "CP NO")
    flow_item = G.col("FLOW", "item")
    flow_force = G.col("FLOW", "FV/FI")
    for z, marker in enumerate(flow_force):
        if str(marker).strip().upper() != "FREQ":
            continue
        if cp_no is not None and flow_cp[z] != cp_no:
            continue
        for case in A.freq_cases(G.wb, flow_item[z]):
            if is_clock_force_cell(case["force"]):
                result.append((flow_cp[z], case["force"]))
    return result


def chroma_downgrade_pins(cp_no=None):
    """Chroma 专用：返回全部（可选按 CP 过滤）需要走 pattern 降级的 {pin: freq_hz}
    （跨含 "F" 的 FLOW 行去重，供 pattern 模板生成 + TS3 周期计算用）。"""
    result = {}
    for z in clock_force_rows(cp_no):
        for pin, info in chroma_row_plan(z).items():
            if info["mode"] == "pattern":
                result[pin] = info["freq_hz"]
    for case_cp, cell in _freq_sheet_force_cells(cp_no):
        for pin, info in chroma_cell_plan(cell, case_cp).items():
            if info["mode"] == "pattern":
                result[pin] = info["freq_hz"]
    return result


def chroma_ts3_half_period_ns(cp_no=None):
    """Chroma 专用：算 TS3 该声明的半周期（nS）。TS3 是全局唯一一个号位，只能装一个
    频率值——若同一 CP 下出现 >1 个不同的降级频率，当前设计撑不住，直接报错（不静默
    选一个猜，2026-07-07 用户裁决的"先只支持单一降级频率"场景，绝大多数情况下降级
    的都是 RTC 的 32768Hz，理论上不会撞见第二个）。没有任何降级需求时返回 None
    （调用方据此决定要不要声明 TS3）。"""
    freqs = set(chroma_downgrade_pins(cp_no).values())
    if not freqs:
        return None
    if len(freqs) > 1:
        raise ValueError(
            "chroma_ts3_half_period_ns: CP=" + str(cp_no) + " 同时出现 " + str(len(freqs))
            + " 个不同的 pattern 降级频率 " + str(sorted(freqs)) + "，但 TS3 只有一个号位，"
            "当前生成器不支持——请检查母本是否真的需要同时降级多个不同频率。")
    return half_period_ns(freqs.pop())


# 2026-07-07 用户口头给的判据是"<100kHz"，但真实 YT5100_Pre 编译报错实测坐实
# LOGIC_SET_FREE_RUN_CLOCK_PIN（FREERUN_FREQ）硬件范围是 600000~200000000Hz——
# 232768Hz 这类 100k~600k 之间的频率若按 100kHz 门槛判走 TMU 会被编译器拒绝
# （"FREERUN_FREQ range must from 600000.000000 to 200000000.000000"）。改用编译
# 实测的真实下限，不用口头给的数字。
S100_PATTERN_THRESHOLD_HZ = 600e3


def s100_cell_plan(cell_value):
    """S100 专用：给定外灌时钟单元格，返回执行计划。
    判据纯粹是"频率是否 <600kHz"（S100_PATTERN_THRESHOLD_HZ，编译实测下限），跟同行其它管脚有没有共用资源无关——S100 不存在
    Chroma 那种 PMU 组资源冲突（2026-07-07 用户明确裁决两平台判据不能混用）。"""
    pin_freqs = parse_freq_cell(cell_value)
    return {pin: {"freq_hz": freq, "mode": "tmu" if freq >= S100_PATTERN_THRESHOLD_HZ else "pattern"}
            for pin, freq in pin_freqs}


def s100_row_plan(z):
    """FLOW 行适配器；核心计算见 :func:`s100_cell_plan`。"""
    return s100_cell_plan(G.col("FLOW", "FV/FI")[z])


def s100_downgrade_pins(cp_no=None):
    """S100 专用：返回全部（可选按 CP 过滤）需要走 pattern 降级（<600kHz）的
    {pin: freq_hz}（供 pattern 模板生成 + GROUP_3 周期计算用）。"""
    result = {}
    for z in clock_force_rows(cp_no):
        for pin, info in s100_row_plan(z).items():
            if info["mode"] == "pattern":
                result[pin] = info["freq_hz"]
    for _case_cp, cell in _freq_sheet_force_cells(cp_no):
        for pin, info in s100_cell_plan(cell).items():
            if info["mode"] == "pattern":
                result[pin] = info["freq_hz"]
    return result


def s100_group3_half_period_ns(cp_no=None):
    """S100 专用：GROUP_3 只放一个 AC_SET_1，跟 Chroma TS3 同理只能支持单一降级
    频率，同时出现 >1 个不同降级频率直接报错。"""
    freqs = set(s100_downgrade_pins(cp_no).values())
    if not freqs:
        return None
    if len(freqs) > 1:
        raise ValueError(
            "s100_group3_half_period_ns: CP=" + str(cp_no) + " 同时出现 " + str(len(freqs))
            + " 个不同的 pattern 降级频率 " + str(sorted(freqs)) + "，但 GROUP_3 只有一个"
            " AC_SET_1，当前生成器不支持——请检查母本是否真的需要同时降级多个不同频率。")
    return half_period_ns(freqs.pop())
