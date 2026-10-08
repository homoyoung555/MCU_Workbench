"""COMP 族的纯数据编译：pattern 向量、配置名、force/limit 数值。

Excel/IOMUX 解析留在 analog_sweep；平台 writer 只负责把这里的结果翻译成 ATE 语句。
"""
import os
import re

import analog_sweep as A
from program_gen.core.encoding import calc_limit


def config_pattern_name(product, case):
    prefix = f"COMP{case['comp']}" if case["mode"] == "NORM" else case["mode"]
    token = re.sub(r"[^0-9A-Za-z]", "_", str(case["case"]).upper())
    if token.isdigit():
        token = token.zfill(2)
    return f"{product}_{prefix}_CASE{token}_Test"


def compare_pattern_name(product, expect):
    expect = str(expect).strip().upper()
    if expect not in {"H", "L"}:
        raise ValueError(f"COMP compare pattern expect 只支持 H/L，实际为 {expect!r}")
    return f"{product}_COMP_COMPARE_{expect}"


def force_voltage(cell, vcc):
    value = A.parse_value(cell)
    if value["kind"] == "abs":
        return value["value"]
    if value["kind"] == "rel_mul":
        return round(float(vcc) * value["factor"], 6)
    if value["kind"] == "rel_off":
        return round(float(vcc) + value["offset"], 6)
    raise ValueError(f"COMP force={cell!r} 不是绝对电压或 VCC 相对写法")


def _pin_key(pin):
    return str(pin).strip().upper().lstrip("/")


def compile_cases(cases, present_pins, vcc):
    """把 full-pin COMP 需求裁剪为本封装 case，并派生正向/反向外部激励。

    内部源的 force 是理论参考电压，只参与比较方向计算，不会进入返回的 force 表。
    """
    present = {_pin_key(pin) for pin in present_pins}
    compiled = []
    for case in cases:
        required = {_pin_key(case["out_pin"])}
        for source in (case["inp"], case["inn"]):
            if not source["internal"]:
                required.add(_pin_key(source["pin"]))
        if not required.issubset(present):
            continue

        if case["expect"] != "H":
            raise ValueError(
                f"COMP sheet 第 {case['_row']} 行现在只填写正向状态，expect 必须为 H；"
                "反向 L 由生成器自动追加"
            )

        inp_v = force_voltage(case["inp_force"], vcc)
        inn_v = force_voltage(case["inn_force"], vcc)
        if inp_v <= inn_v:
            raise ValueError(
                f"COMP sheet 第 {case['_row']} 行必须填写正向状态：inp_force({inp_v}V) > "
                f"inn_force({inn_v}V)"
            )
        if case["inp"]["internal"] and case["inn"]["internal"]:
            raise ValueError(f"COMP sheet 第 {case['_row']} 行 inp/inn 都是内部源，无法生成外部反向激励")

        forward, reverse = {}, {}
        inp, inn = case["inp"], case["inn"]
        if not inp["internal"] and not inn["internal"]:
            forward[inp["pin"]], forward[inn["pin"]] = inp_v, inn_v
            reverse[inp["pin"]], reverse[inn["pin"]] = inn_v, inp_v
        else:
            external = inn if inp["internal"] else inp
            internal_v = inp_v if inp["internal"] else inn_v
            external_v = inn_v if inp["internal"] else inp_v
            reverse_v = round(2 * internal_v - external_v, 6)
            if not 0 <= reverse_v <= float(vcc):
                raise ValueError(
                    f"COMP sheet 第 {case['_row']} 行按内部参考 {internal_v}V 镜像得到的反向电压 "
                    f"{reverse_v}V 超出 0~{float(vcc):g}V"
                )
            forward[external["pin"]] = external_v
            reverse[external["pin"]] = reverse_v

        levels, forward_drive, reverse_drive = {}, {}, {}
        for pin, forward_v in forward.items():
            reverse_v = reverse[pin]
            vil, vih = min(forward_v, reverse_v), max(forward_v, reverse_v)
            levels[pin] = {"vil": vil, "vih": vih}
            forward_drive[pin] = "1" if forward_v == vih else "0"
            reverse_drive[pin] = "1" if reverse_v == vih else "0"

        item = dict(case)
        item.update(pattern_index=len(compiled) + 1,
                    forward_forces=forward, reverse_forces=reverse,
                    levels=levels, forward_drive=forward_drive, reverse_drive=reverse_drive)
        compiled.append(item)
    return compiled


def measurement_limits(case, vcc):
    low, high = case["down_limit"], case["up_limit"]
    if not low or not high or low == "/" or high == "/":
        raise ValueError(f"COMP sheet 第 {case['_row']} 行 UNIT=V 时 down_limit/up_limit 必填")
    target = float(vcc) if case["expect"] == "H" else 0.0
    if case["expect"] == "L" and (str(low).endswith("%") or str(high).endswith("%")):
        raise ValueError(f"COMP sheet 第 {case['_row']} 行 expect=L、target=0，不能使用百分比限值")
    return calc_limit(target, low, high, True), calc_limit(target, low, high, False)


def pattern_pins(cases):
    pins = []
    for case in cases:
        for source in (case["inp"], case["inn"]):
            pin = source["pin"]
            if not source["internal"] and pin not in pins:
                pins.append(pin)
        if case["out_pin"] not in pins:
            pins.append(case["out_pin"])
    return pins


def case_vector(case, pins, expect, compare_output=False):
    vector = ["X"] * len(pins)
    drive = case["forward_drive"] if expect == "H" else case["reverse_drive"]
    for pin, state in drive.items():
        vector[pins.index(pin)] = state
    if compare_output:
        vector[pins.index(case["out_pin"])] = expect
    return "".join(vector)


def write_compare_pattern(path, name, cases, platform, expect):
    """生成 H 或 L 大 pattern；每个测量点使用相同编号的 sNNN_st/sNNN_sp。"""
    expect = str(expect).strip().upper()
    if expect not in {"H", "L"}:
        raise ValueError(f"COMP pattern expect 只支持 H/L，实际为 {expect!r}")
    pins = pattern_pins(cases)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="\n") as f:
        if platform == "chroma":
            f.write('SET_DEC_FILE "pin.dec"\n\nHEADER\n\n' + ",".join(pins) + ";\n\n")
            f.write(f"SPM_PATTERN({name}) {{\n\n  *{'X' * len(pins)}*TS1;\n")
            for index, case in enumerate(cases, 1):
                drive = case_vector(case, pins, expect)
                compare = case_vector(case, pins, expect, compare_output=True)
                f.write(f"s{index:03d}_st:\n  *{'X' * len(pins)}*RPT 100;\n")
                f.write(f"  *{drive}*RPT 20000;\n  *{compare}*RPT 9;\n")
                f.write(f"s{index:03d}_sp:\n  *{compare}*;\n\n")
            f.write("}\n")
        elif platform == "s100":
            f.write("HEAD[PIN_NAME]:\n\n" + ",".join(pins) + ";\n\nEND_HEAD;\n\n@@PATTERN_DEFINE\n")
            vector_col = 25
            for index, case in enumerate(cases, 1):
                drive = case_vector(case, pins, expect)
                compare = case_vector(case, pins, expect, compare_output=True)
                start_label = f"s{index:03d}_st:"
                stop_label = f"s{index:03d}_sp:"
                f.write(f"{start_label:>{vector_col}}{'X' * len(pins)};RPT 100;\n")
                f.write(f"{'':{vector_col}}{drive};RPT 20000;\n")
                f.write(f"{'':{vector_col}}{compare};RPT 9;\n")
                f.write(f"{stop_label:>{vector_col}}{compare};\n\n")
            f.write("@@END_PATTERN_DEFINE\n")
        else:
            raise ValueError(f"unknown COMP pattern platform: {platform}")
    return pins
