# 平台无关的进制/位转换与字典工具。
# 代码原样迁自 S100_program/pattern.py（机械重构，不改行为）。
import re
from collections import defaultdict
from functools import lru_cache


def expand_dac_array(step_value):
    """展开逗号分隔 DAC 值及包含端点的范围；范围方向由起止值决定。"""
    values = []
    for token in str(step_value).replace("\n", ",").split(","):
        token = token.strip()
        if not token:
            continue
        match = re.fullmatch(r"(-?\d+)\s*-\s*(-?\d+)", token)
        if match:
            start, end = (int(value) for value in match.groups())
            direction = 1 if end >= start else -1
            values.extend(str(value) for value in range(start, end + direction, direction))
        else:
            values.append(token)
    return ",".join(values)


def process_dict(d):
    value_to_keys = defaultdict(list)

    # 1. 先按值分组，收集所有相同值的键
    for key, value in d.items():
        value_to_keys[value].append(key)

    # 2. 处理每个值对应的键列表
    result = {}
    for value, keys in value_to_keys.items():
        if len(keys) > 1:
            # 如果有多个键，用 "+" 连接
            result[value] = "+".join(keys)
        else:
            # 如果只有一个键，直接输出该键
            result[value] = keys[0]

    return result


def bin_list_to_hex(bit_list):
    # 检查输入有效性
    if len(bit_list) != 16:
        raise ValueError("输入必须是16位的列表")
    if any(bit not in (0, 1) for bit in bit_list):
        raise ValueError("列表元素只能是0或1")

    # 转换为二进制字符串
    binary_str = ''.join(str(bit) for bit in bit_list)

    # 转换为整数
    decimal_value = int(binary_str, 2)

    # 转换为4位大写十六进制（带0x前缀）
    return f"0x{decimal_value:04X}"


def hex_to_bin_16bit(hex_string):
    decimal_number = int(hex_string, 16)
    binary_number = bin(decimal_number)

    return binary_number[2:].zfill(16)


def hex_to_Wbin_32bit(hex_string):
    decimal_number = int(hex_string, 16)
    binary_number = bin(decimal_number)

    return binary_number[2:].zfill(32)


def hex_to_Rbin_32bit(hex_string):
    decimal_number = int(hex_string, 16)
    binary_number = bin(decimal_number)
    binary_number = binary_number[2:].zfill(32)
    decimal_number_list = list(binary_number)

    for j in range(len(decimal_number_list)):
        if decimal_number_list[j] == "0":
            decimal_number_list[j] = "L"
        if decimal_number_list[j] == "1":
            decimal_number_list[j] = "H"
    new_s = "".join(decimal_number_list)
    return new_s


def invert_hex_string(hex_str, bits=8):
    """
    将带0x前缀的十六进制字符串按位取反，返回带0x前缀的结果字符串

    参数:
        hex_str: 输入的十六进制字符串 (如 "0xA")
        bits: 位数 (8, 16, 32等)，决定结果的范围

    返回:
        带0x前缀的取反结果字符串 (如 "0xF5")
    """
    # 将十六进制字符串转为整数
    num = int(hex_str, 0)  # 自动识别0x前缀

    # 按位取反并限制位数
    inverted_num = (~num) & ((1 << bits) - 1)

    # 格式化为带0x前缀的字符串，保持原输入的大小写风格
    prefix = '0x' if hex_str.startswith('0x') else '0X'
    return prefix + format(inverted_num, '0{}X'.format(bits // 4))


def bin8_to_hex(bin_str):
    # 输入验证
    if len(bin_str) != 8:
        raise ValueError("输入必须是8位二进制字符串")
    if not all(c in "01" for c in bin_str):
        raise ValueError("输入包含非二进制字符")

    # 转换逻辑
    decimal = int(bin_str, 2)  # 二进制转十进制
    hex_str = f"{decimal:02X}"  # 十进制转两位大写十六进制
    return hex_str


@lru_cache(maxsize=1024)
def value_to_binary(input_str, xbit=16):
    """
    将传入值转换为 Xbit 的二进制字符串

    参数:
        input_str: 输入字符串，格式为多个字段的组合，用\\n分隔
                  每个字段格式：起始位,变量名=值 或 纯值
                  示例1: "3,PMU_TMODE=0101"
                  示例2: "7,trim_sel=1\\n6,sleep=0\\n5,reset=0\\n4,tmode[4:0]=10100"
        xbit: 总位数，默认为16

    返回:
        Xbit 长度的二进制字符串，用空格分隔每4位

    示例:
        value_to_binary("3,PMU_TMODE=0101", 16) -> "0000 0000 0000 0101"
        value_to_binary("7,trim_sel=1\\n6,sleep=0\\n5,reset=0\\n4,tmode[4:0]=10100", 16)
        -> "0000 0000 1001 0100"
    """
    if xbit <= 0:
        raise ValueError("xbit 必须大于 0")

    input_str = input_str.replace(' ', '')

    result = 0

    fields = input_str.split('\n')

    for field in fields:
        field = field.strip()
        if not field:
            continue

        if ',' in field and '=' in field:
            pos_part, value_part = field.split(',', 1)
            start_bit = int(pos_part)

            var_name, value = value_part.split('=', 1)
            value = value.strip()
            if value.endswith('*'):
                value = value[:-1]

            if 'x' in value.lower():
                bit_width = None
                if '[' in var_name and ':' in var_name:
                    try:
                        start_idx = var_name.index('[')
                        end_idx = var_name.index(']')
                        bit_range = var_name[start_idx+1:end_idx]
                        if ':' in bit_range:
                            high_bit = int(bit_range.split(':')[0])
                            low_bit = int(bit_range.split(':')[1])
                            bit_width = high_bit - low_bit + 1
                    except:
                        pass
                if bit_width:
                    value = '0' * bit_width
                else:
                    value = value.lower().replace('x', '0')

            if all(c in '01' for c in value):
                value_int = int(value, 2)
                bit_len = len(value)
            else:
                value_int = int(value)
                bit_len = len(bin(value_int)) - 2

            shift = start_bit - bit_len + 1
            result |= (value_int << shift)
        else:
            if all(c in '01' for c in field):
                value_int = int(field, 2)
            else:
                value_int = int(field)
            result |= value_int

    result = result & ((1 << xbit) - 1)

    binary_str = bin(result)[2:].zfill(xbit)

    return binary_str


def pattern_field_is_dynamic(line):
    """Return whether a Pattern field is runtime replaceable.

    V1.3 uses ``FIELD=001*`` (default plus dynamic marker).  Legacy ``=x``
    remains detectable while blank Recipe rows are still being migrated.
    """
    if '=' not in str(line):
        return False
    value = str(line).split('=', 1)[1].strip()
    return value.endswith('*') or 'x' in value.lower()


def decimal_to_hex(decimal):
    # 使用hex()函数将十进制转换为十六进制，并去掉前面的'0x'
    hex_value = hex(decimal)[2:]

    # 使用zfill()函数确保输出是两位的，高位补零
    hex_value = hex_value.zfill(2)

    # 转换为大写
    hex_value = hex_value.upper()

    return hex_value


def calc_limit(target, low_cell, high_cell, is_low):
    """FLOW low_range(%)/high_range(%) 一对单元格 → 上/下限值（保留 3 位小数）。三种写法：
    - 带 `%`（百分号，数值取绝对值）：相对 target 的百分比，low = target - |target*pct/100|、
      high = target + |target*pct/100|（沿用原算法，方向由 is_low 决定）。
    - 纯数字、**低/高两格都带 ± 号且符号不同**（一负一正，如 low=-0.5/high=+0.5）：
      相对 target 的有符号偏移，limit = target + 该格自己的值（如 low=-0.5 → target-0.5）。
      这是唯一表示"偏移"的写法——单看一个格子的符号不足以判定，必须两格一起看：只有
      "一负一正"才说明这两个数是同一个中心点两侧的偏移量；同号（两个都负/都正）说明这
      两个数本身就是各自独立的绝对限值，只是恰好都是负数（电流类项 target 为负时常见）。
    - 其它情况（两格都不带符号，或都带符号但同号）：**每格直接就是该上/下限值本身**
      （绝对限值，与 target 无关）。
    2026-07-06 用户裁决：修复"两格同号（如低=-4.7/高=-4.3）被误当偏移"的真实 bug——
    golden 母本 `Isa_Verify` 这一行历史上恰好也是同号（-0.75/-0.25），当时验证过对应
    S100 golden `.prg` 里 `DOWN_LIMIT=-4.75uA/UP_LIMIT=-4.25uA`，说明那一行**本意确实是
    偏移**——这条规则生效后那一行会变成绝对值 -0.75/-0.25（不再是 -4.75/-4.25），
    用户已确认接受这个回归、后续会把 golden 母本那一行也改成新写法（真绝对值）。
    注意：不带 % 一律按数字处理，故母本中原有的百分比单元格都需补上 `%`。
    2026-07-10 用户裁决（F2 DC扫描族）：绝对限值这条分支允许 `target` 留空——
    `float(target)` 改成只在真正用到 `t` 的两个分支（百分比/有符号偏移）里才
    解析，绝对限值分支不再要求 `target` 能转成数字。"""
    cell = low_cell if is_low else high_cell
    s = str(cell).strip()
    if s.endswith("%"):
        t = float(target)
        off = abs(t * abs(float(s[:-1])) / 100)
        return round(t - off if is_low else t + off, 3)
    low_s = str(low_cell).strip()
    high_s = str(high_cell).strip()
    low_sign = low_s[:1] if low_s[:1] in ("+", "-") else ""
    high_sign = high_s[:1] if high_s[:1] in ("+", "-") else ""
    if low_sign and high_sign and low_sign != high_sign:   # 一负一正 → 相对 target 偏移
        t = float(target)
        return round(t + float(s), 3)
    return round(float(s), 3)        # 同号或都不带符号 → 直接就是该限值本身


def resolve_vcc_value(vcc_cell, vcc_min, vcc_typ, vcc_max):
    """FLOW.Vcc 的命名电平或数值 → VERSION 中对应的实际电压值。"""
    s = str(vcc_cell).strip().upper()
    if s.startswith("_C_"):
        s = s[3:]
    named = {
        "VCC_MIN": vcc_min,
        "VCC_TYP": vcc_typ,
        "VCC_MAX": vcc_max,
    }
    if s in named:
        return float(named[s])
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?V?", s):
        return float(s.rstrip("V"))
    raise ValueError(
        f"无法解析 FLOW.Vcc={vcc_cell!r}；应填 VCC_MIN/VCC_TYP/VCC_MAX 或数值电压"
    )


def dac_target_voltage(code, resolution, vcc):
    """十六进制 DAC code / 满量程码数 × VCC → 理论输出电压。"""
    token = str(code).strip().upper()
    if token.startswith("0X"):
        token = token[2:]
    if not token or not re.fullmatch(r"[0-9A-F]+", token):
        raise ValueError(f"DAC code={code!r} 不是十六进制码")
    full_scale = float(resolution)
    if full_scale <= 0:
        raise ValueError(f"DAC FLOW.target={resolution!r} 必须大于 0")
    code_value = int(token, 16)
    if code_value >= full_scale:
        raise ValueError(
            f"DAC code={code!r} 的数值 {code_value} 必须小于 FLOW.target={resolution}"
        )
    return code_value / full_scale * float(vcc)


def dac_reference_voltage(mode, vcc):
    """Return the voltage reference used by a DAC mode."""
    mode_name = str(mode or "").strip().upper()
    match = re.fullmatch(r"VREF(\d+)P(\d+)", mode_name)
    if match:
        return float(match.group(1) + "." + match.group(2))
    return float(vcc)


def calc_dac_limits(code, resolution, vcc, low_cell, high_cell, mode=None):
    """按 FLOW limit 三种写法，围绕 DAC 理论输出电压计算最终上下限。"""
    target = dac_target_voltage(
        code, resolution, dac_reference_voltage(mode, vcc)
    )
    return (
        calc_limit(target, low_cell, high_cell, True),
        calc_limit(target, low_cell, high_cell, False),
    )


def leading_bit_width(s):
    """从 ADDR_MAP 里 Verilog 风格常量前缀（如 `4'h0`/`15'b0`）提取开头的位宽数字。
    2026-07-06 真实踩过一次：母本这类撇号被 Excel/WPS 自动更正成弯引号（U+2018/2019，
    人眼几乎看不出跟直引号 U+0027 的区别），原来按 `.split("'")[0]` 精确匹配直引号的
    写法解析失败，被外层 except 吞掉、静默把这个常量当成 1 位宽处理，导致同一格里后面
    所有字段的位偏移全部算错（如 `Mr_Trim[3:0]` 该在 bit[7:4] 却被错算成 bit[7:3]右移
    3 位变成 <<7）。改成只认"字符串开头连续的数字"，不依赖具体是哪个撇号字符、也不
    要求撇号后面跟什么，从根上规避这一类肉眼难辨的字符问题。"""
    m = re.match(r"\d+", str(s).strip())
    if not m:
        raise ValueError(f"无法从 {s!r} 提取位宽（应形如 \"4'h0\"）")
    return int(m.group())


def addr_map_field_width(value):
    """Return one ADDR_MAP field's actual bit width."""
    text = str(value).strip()
    match = re.search(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", text)
    if match:
        high_bit = int(match.group(1))
        low_bit = int(match.group(2))
        if high_bit < low_bit:
            raise ValueError(f"ADDR_MAP 位段顺序错误：{value!r}")
        return high_bit - low_bit + 1
    if text[:1].isdigit():
        return leading_bit_width(text)
    return 1


def addr_map_literal_value(value):
    """Return a concrete ADDR_MAP Verilog literal's numeric value."""
    text = str(value).strip().replace("’", "'").replace("‘", "'")
    match = re.fullmatch(r"\d+\s*'\s*([hHbBdD])\s*([0-9a-fA-F_]+)", text)
    if not match:
        return None
    base = {"h": 16, "b": 2, "d": 10}[match.group(1).lower()]
    return int(match.group(2).replace("_", ""), base)


def widen_pct(cell, n):
    """把百分比单元格的百分值 +n（trim 判定加宽 +50 用）；非 % 单元格原样返回。"""
    s = str(cell).strip()
    return (str(float(s[:-1]) + n) + "%") if s.endswith("%") else cell
