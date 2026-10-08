# Chroma 平台：.pln 各类测试项写出。
import re
import pandas as pd
from flow_recipe import dynamic_recipe_enter_operations, recipe_setup_operations
from program_gen.core import clock_force
from program_gen.core.encoding import addr_map_field_width, addr_map_literal_value, bin_list_to_hex, calc_limit, decimal_to_hex, hex_to_bin_16bit, invert_hex_string, leading_bit_width, pattern_field_is_dynamic, process_dict
from program_gen.core.flash_seq import epr_pattern_capture
from program_gen.core.pattern_data import reuse_dac_pattern, reuse_dac_restore_items
from program_gen.core.recipe_trim import dac_final_symbol, generated_flow_item_name, recipe_pattern_name, trim_data_helper_name
from program_gen.core.shmoo import ShmooPlan
from program_gen.platforms.chroma.commit_shmoo_adapter import write_commit_shmoo
from program_gen.core.trim_spec import dynamic_enter_operations
from program_gen.core.trim_data import trim_data_reference_matches
from program_gen.core.logical_item import logical_item_key
from program_gen.platforms.chroma.pattern_files import copy_file, copy_trig_pat, trig_disp, LEVEL_SEQ_RE, default_pulse, level_seq_pat_name, parse_pulse_width
from program_gen.platforms.chroma.project_files import VCC_pin_rebuild, vcc_rails_str, cp_has_kp_relay
from program_gen import state as G


def _flow_item_key(value):
    """Normalize FLOW item names before case-insensitive dispatch."""
    return str(value).strip().lower()


def _persistence_recipe_modules(recipe_row):
    """Return declared persistence modules, or ``None`` for legacy rows.

    ``compile_recipe_rows`` deliberately omits blank Recipe rows.  Keeping
    ``None`` distinct from an empty tuple prevents migrated rows from silently
    inheriting legacy actions.
    """
    if recipe_row is None:
        return None
    return tuple(operation.name for operation in recipe_row.operations)


def _recipe_module_enabled(modules, name):
    """Legacy enables the historical path; explicit Recipe enables only itself."""
    return modules is None or str(name).strip().upper() in modules


def _trim_target_pages(trim_data_plan, cp, catalog=None):
    """Pages touched by this CP's actual Trim fields, never every label page."""
    catalog = catalog or G.compiled_adapter.addr_map_catalog
    pages = []
    for binding in trim_data_plan.for_cp(cp):
        for field in catalog.fields:
            if (binding.matches_addr_map(field.name)
                    and field.register_layout.applies_to(cp)
                    and field.page not in pages):
                pages.append(field.page)
    return tuple(pages)


def _commit_value_expression(value):
    if value.kind == "DECIMAL":
        return str(int(value.token, 10))
    if value.kind == "HEX":
        return "0x" + value.token.removeprefix("0x").removeprefix("0X")
    if value.kind == "BINARY":
        return str(int(value.token, 2))
    if value.kind in ("VARIABLE", "STEP"):
        return value.token
    raise ValueError(f"Chroma COMMIT 不支持值类型 {value.kind}")


def _write_explicit_commit(f, recipe_row, cp, catalog=None):
    """Incrementally update only explicitly assigned ADDR_MAP fields.

    The complete REG image must already have been established by BUILDMAP or
    READOTPMAP.  This adapter therefore emits a runtime read-modify-write and
    refreshes both Program and Read pattern memory; it never rebuilds a page
    from defaults.
    """
    if recipe_row is None:
        return ()
    catalog = catalog or G.compiled_adapter.addr_map_catalog
    writes = []
    for operation in recipe_row.operations:
        if operation.name != "COMMIT":
            continue
        for assignment in operation.assignments:
            expression = _commit_value_expression(assignment.value)
            for field in catalog.resolve_fields(assignment.field):
                if not field.register_layout.applies_to(cp):
                    continue
                writes.append((field, expression))
    if not writes:
        return ()

    touched = []
    f.write("  SOCKET_INC(FRZ_OFF)\n  {\n")
    for field, expression in writes:
        reg = "REG_" + field.register.upper() + "[SOCKET]"
        clear_mask = 0xFFFF ^ (((1 << field.width) - 1) << field.lsb)
        f.write(
            f"    {reg}=({reg}&0x{clear_mask:04X})|"
            f"(({expression})<<{field.lsb}); //COMMIT {field.name}\n"
        )
    for field, _expression in writes:
        key = (field.page, field.register)
        if key in touched:
            continue
        touched.append(key)
        pattern_page = (
            "cp" + str(cp)[-1] + "_id"
            if field.page.casefold() == "uid" else field.page
        )
        result = epr_pattern_capture("normal", pattern_page)
        pn_flag = "yes" if field.register_layout.complement_half else "no"
        write_pat_mem(
            f, result, 15, "-J", 0, field.register,
            "REG_" + field.register.upper() + "[SOCKET]",
            field.register.lower() + "_", pn_flag,
        )
    f.write("  }\n\n")
    return tuple(touched)


def write_uid_failed_site_reerase(f, result, *, vcc, indent="", restore_power=False):
    """Re-erase UID only on sites whose preceding read-check failed."""
    pad = indent
    body = pad + "  "
    f.write(pad + "{\n")
    f.write(body + "///////////if fail erase uid page///////////\n")
    f.write(body + "LUINT shift_site;\n\n")
    f.write(body + "SOCKET_INC(FRZ_OFF)\n" + body + "{\n")
    f.write(body + "  shift_site[SOCKET]=0;\n")
    f.write(body + "  if(PLAN_RESULT_MS[SOCKET]==FAIL) shift_site[SOCKET]=1;\n")
    f.write(body + "}\n\n")
    f.write(body + "SOCKET_SET(B:shift_site,FRZ_OFF)\n" + body + "{\n")
    f.write(body + "  POWER_ON(" + str(vcc).upper() + ");\n")
    f.write(body + '  JUDGE_PAT(enter_fbist_mode,__enter_fbist_mode);\n')
    f.write(body + "  JUDGE_PAT(" + result["erase"] + ",__" + result["erase"] + ");\n")
    f.write(body + "  POWER_OFF();\n")
    f.write(body + "}\n")
    f.write(pad + "}\n")
    if restore_power:
        f.write(pad + "POWER_ON(" + str(vcc).upper() + ");\n")
    f.write("\n")


def _recipe_duration(duration):
    if duration is None:
        return None
    suffix = "mS" if duration.unit == "MS" else "uS"
    return f"{duration.amount}{suffix}"


def _write_recipe_wait(f, duration, indent):
    if duration is not None:
        f.write(f"{indent}WAIT({_recipe_duration(duration)});\n")


def flow_relay(z):
    """FLOW.relay 列（可选列，老母本没有这列也不报错，一律当"/"处理）：值不是 "/" 时，
    该项上电前后各需要一层 SET_CBIT(<relay值>, ON/OFF, 5mS)——但仅当**当前这份 dec 真的
    声明了这个 relay 名**才发（跟 KP relay 同一个坑：LAB 单 site 用 PIN DEC SINGEL，可能
    没有这份 relay 的接线数据，dec 没声明就不能引用，否则编译报"未声明标识符"）。"""
    if "relay" not in G.FLOW.columns:
        return "/"
    relay = str(G.col("FLOW", "relay")[z]).strip()
    if relay == "/":
        return "/"
    cp_no = G.col("FLOW", "CP NO")[z]
    pin_cp = G.col("PIN_DEC_128", "CP NO")
    pin_pad = G.col("PIN_DEC_128", "E/C(Pad Name)")
    if any(
        pin_cp[u] == cp_no
        and relay == str(pin_pad[u]).strip()
        for u in range(len(pin_cp))
    ):
        return relay
    return "/"


def shmoo_item_write(code_name, f, plan: ShmooPlan):
    """Generate one-dimensional Shmoo with runtime DAC/limit/log arrays."""
    if code_name[G.i].split("_")[-1] != plan.cp or plan.mode != "fbist":
        return
    z = plan.flow_row_index
    relay = flow_relay(z)
    pattern_dir = G.OUT_DIR + "\\" + code_name[G.i] + "\\pat"
    copy_file(G.BASE_DIR + "\\pat_temp\\" + plan.pattern_name + ".pat", pattern_dir)
    points = plan.points
    n = len(points)
    force_point = max(points, key=lambda point: max(abs(point.down_limit), abs(point.up_limit)))

    f.write("\n" + plan.function_name.title() + "()\n{\n")
    f.write("  TEST_NUM=" + str((z + 1) * 100) + ";\n")
    f.write('  TEST_NO(TEST_NUM);DATALOG_MSG="' + plan.function_name.lower() + '";\n\n')
    f.write("  int shmooDac[" + str(n) + "]={" + ",".join(str(p.dac) for p in points) + "};\n")
    # Chroma 现有 OPA/DAC 循环均用无单位 double 数组直接传 JUDGE_*；单位由 API 决定。
    f.write("  double shmooDown[" + str(n) + "]={" + ",".join(str(p.down_limit) for p in points) + "};\n")
    f.write("  double shmooUp[" + str(n) + "]={" + ",".join(str(p.up_limit) for p in points) + "};\n")
    f.write("\n")
    if relay != "/":
        f.write("  SET_CBIT(" + relay + ", ON, 5mS);\n")
    f.write("  POWER_ON(" + plan.vcc.upper() + ");\n\n")
    f.write("  RELAY_ON(" + plan.meas_pin + ", PPMU_PDCL, 2mS);\n\n")
    f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="enter_fbist_mode";\n')
    f.write("  JUDGE_PAT(enter_fbist_mode,__enter_fbist_mode);\n\n")
    Force_Judge(plan.unit, plan.meas_pin, plan.force_value, force_point.target, 0,
                "FORCE", "PPMU", force_point.low_range, force_point.high_range, f,
                force_wait=plan.force_wait)
    f.write("  for(I=0;I<" + str(n) + ";I++)\n  {\n")
    f.write("    set_" + plan.pattern_name + "_data(shmooDac[I]);\n")
    f.write("    TEST_NUM++;\n    TEST_NO(TEST_NUM);\n")
    f.write("    switch(I)\n    {\n")
    for index, point in enumerate(points):
        f.write('      case ' + str(index) + ': DATALOG_MSG="' + point.log_name + '"; break;\n')
    f.write("    }\n")
    f.write("    JUDGE_PAT(" + plan.pattern_name + ",__" + plan.pattern_name + ");\n")
    judge = "JUDGE_I_PPMU" if "A" in plan.unit else "JUDGE_V_PPMU"
    f.write("    " + judge + "(" + plan.meas_pin
            + ", shmooDown[I], shmooUp[I], 2mS,16,AVE,50uS,,);\n")
    f.write("  }\n")
    f.write("  set_" + plan.pattern_name + "_data(" + str(int(plan.default_value, 2)) + ");\n\n")
    f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="exit_fbist_mode";\n')
    f.write("  JUDGE_PAT(exit_fbist_mode,__exit_fbist_mode);\n\n")
    if plan.unit == "V" and plan.force_value != "0uA":
        Force_Judge("V", plan.meas_pin, "0uA", force_point.target, 0, "FORCE", "PPMU",
                    force_point.low_range, force_point.high_range, f)
    elif "A" in plan.unit and plan.force_value != "0V":
        Force_Judge(plan.unit, plan.meas_pin, "0V", force_point.target, 0, "FORCE", "PPMU",
                    force_point.low_range, force_point.high_range, f)
    f.write("  RELAY_OFF(" + plan.meas_pin + ", PPMU_PDCL, 2mS);\n")
    f.write("  POWER_OFF();\n")
    if relay != "/":
        f.write("  SET_CBIT(" + relay + ", OFF, 5mS);\n")
    if not plan.pass_fail:
        f.write("  SOCKET_INC(FRZ_OFF)\n  {\n\tPLAN_RESULT_MS[SOCKET]=PASS;\n  }\n")
    f.write("}\n")


def commit_shmoo_item_write(code_name, f, plan):
    def load_register(page, register):
        result = epr_pattern_capture("normal", page)
        row = next(
            index for index, value in enumerate(G.col("ADDR_MAP", "bit[15:0]"))
            if str(value).split("[")[0].casefold() == register.casefold()
            and str(G.col("ADDR_MAP", "Word No.")[index]).casefold()
            == page.casefold()
        )
        complement = "yes" if "鍙嶇爜" in str(
            G.col("ADDR_MAP", "bit[31:16]")[row]
        ) else "no"
        write_pat_mem(
            f, result, 15, "-J", 0, register,
            "REG_" + register.upper() + "[SOCKET]",
            register.lower() + "_", complement,
        )

    return write_commit_shmoo(
        code_name,
        f,
        plan,
        state=G,
        copy_file=copy_file,
        pattern_capture=epr_pattern_capture,
        load_register=load_register,
        uid_failed_site_reerase=write_uid_failed_site_reerase,
    )


def _dac_adj_apply(dac_final_name, delta, bisection, dac_bit):
    """生成"给 DAC_FINAL 加减档"的边界安全代码。**线性**(`bisection=="no"`，Dac_Loop
    变体，DAC_FINAL 就是 0..2^bit-1 的原始码)可以直接对码值加减、夹到 [0,2^bit-1]。
    **折线**(`bisection=="yes"` 时函数体里已声明的 `dacArray`——`FLOW.LINE=="yes"` 是
    单调 0..2^bit-1，`"no"` 则是 `step` 列给的自定义非单调排布，如 Vref0p8 的
    "8,9,...,15,0,...,6")不能直接对原始码加减，要对 `dacFinalIndex[SOCKET]`（收敛
    过程中跟 DAC_FINAL 同步记录的"历史最优"下标，见 trim_item_write 里
    `if(fabs(...)<fabs(...))` 那段）加减、夹到数组范围，再映射回 dacArray 的值——
    不能用循环末尾的 dacIndex（那是"下一轮该探的点"，从没被真正测量过，跟 DAC_FINAL
    实际对应的下标不是同一个，用户核实过这一点）。"""
    max_code = pow(2, dac_bit) - 1
    if bisection == "yes":
        return (
            "      dacFinalIndex[SOCKET] += " + str(delta) + ";\n"
            "      if(dacFinalIndex[SOCKET]<0) dacFinalIndex[SOCKET] = 0;\n"
            "      if(dacFinalIndex[SOCKET]>(int)(sizeof(dacArray)/sizeof(dacArray[0]))-1) dacFinalIndex[SOCKET] = (int)(sizeof(dacArray)/sizeof(dacArray[0]))-1;\n"
            "      " + dac_final_name + "[SOCKET] = dacArray[dacFinalIndex[SOCKET]];\n"
        )
    return (
        "      " + dac_final_name + "[SOCKET] += " + str(delta) + ";\n"
        "      if(" + dac_final_name + "[SOCKET]<0) " + dac_final_name + "[SOCKET]=0;\n"
        "      if(" + dac_final_name + "[SOCKET]>" + str(max_code) + ") " +
        dac_final_name + "[SOCKET]=" + str(max_code) + ";\n"
    )


_DAC_ADJ_UNCOND_RE = re.compile(r"^([+-]\d+)$")
_DAC_ADJ_COND_RE = re.compile(r"^([<>])\s*(-?\d+(?:\.\d+)?)\s*:\s*([+-]\d+)$")


def _dac_adj_spec(z):
    """解析 FLOW."DAC ADJ" 列（trim 项收敛后手动加减档，用户裁决 2026-07-06，参照
    temp/temp_swd_cp3.pln 示例）。老母本没有这列，或填 "/"/空 时返回 None（不加档，
    行为与之前完全一致）。
      "±N"（纯数字带符号）      -> 无条件：{"cond": None, "delta": N}
      "<阈值:±N" / ">阈值:±N"   -> 有条件：{"cond": (比较符, 阈值), "delta": N}
    格式不认得也返回 None（容错，不因填错格式崩生成）。"""
    if "DAC ADJ" not in G.FLOW.columns:
        return None
    raw = G.col("FLOW", "DAC ADJ")[z]
    if not isinstance(raw, str) or raw.strip() in ("", "/"):
        return None
    raw = raw.strip()
    m = _DAC_ADJ_COND_RE.match(raw)
    if m:
        return {"cond": (m.group(1), float(m.group(2))), "delta": int(m.group(3))}
    m = _DAC_ADJ_UNCOND_RE.match(raw)
    if m:
        return {"cond": None, "delta": int(m.group(1))}
    return None


def _expand_dac_array(step_value):
    """把 FLOW.step 里手填的 dacArray 简写展开成完整的逗号分隔字面量（用于非线性
    bisection 的自定义 dacArray={...}）。逗号分隔的每个 token 支持：
      - 纯数字：原样保留，如 "1,2,3,4"
      - "a-b" 范围：展开成 a,a+1,...,b（含端点），如 "1-4,5-8" → "1,2,3,4,5,6,7,8"
    后续要加新格式，在这个函数里加分支即可，FLOW.step 的字面量协议全收口在这一处。"""
    tokens = str(step_value).split(",")
    values = []
    for tok in tokens:
        tok = tok.strip()
        if "-" in tok and not tok.startswith("-"):
            start, end = tok.split("-")
            values.extend(str(v) for v in range(int(start), int(end) + 1))
        else:
            values.append(tok)
    return ",".join(values)


def _trim_variable_slots(lines):
    """筛出这组 description 行里真正要当 trim_data() 参数的字段——只有含 "=x"（可变
    trim 值占位符）的行，`pattern_files.py:fbist_pattern_created` 才会在 .pat 里写
    对应的 `<serial>_data` 标签、才有全局 `<NAME>DAC_FINAL` 变量；不含 "=x" 的纯字面
    量固定值（如 2026-07-04 母本新增的 `HSI_TC_TRIMCR_VDDK[3:0]=1000`）只是烤进 .pat
    的常量，没有标签也没有全局变量，当成参数会导致 CRAFT 编译报未声明标识符。
    保留原始下标 d（`serial_number[d]+"_data"` 要跟 pattern_files.py 写标签时用的
    下标 d 完全一致，过滤掉字面量行后不能重新连续编号）。"""
    return [(d, line) for d, line in enumerate(lines) if pattern_field_is_dynamic(line)]


def _trim_variable_slots_for_merged_row(row):
    """读取 pattern 合并单元格覆盖的整组 description 中唯一可调字段。"""
    pattern_column = next(cell.column for cell in G.wc[1] if cell.value == "pattern")
    excel_row = row + 2
    rows = [row]
    for merged_range in G.wc.merged_cells.ranges:
        if (merged_range.min_col == pattern_column == merged_range.max_col
                and merged_range.min_row <= excel_row <= merged_range.max_row):
            rows = range(merged_range.min_row - 2, merged_range.max_row - 1)
            break
    matches = [(candidate, _trim_variable_slots(G.exegesis[candidate])) for candidate in rows]
    variable_matches = [slots for _candidate, slots in matches if slots]
    if len(variable_matches) != 1:
        raise ValueError(
            f"pattern row {excel_row}: expected one variable description row, "
            f"found {len(variable_matches)}"
        )
    return variable_matches[0]


_FORCE_CURRENT_RE = re.compile(r'^([+-]?[\d.]+)\s*(uA|mA|A)$', re.IGNORECASE)


def parse_fv_fi(fv_fi, meas_pin):
    """FV/FI → [(force_pin, force_value_str), ...]（2026-07-16 用户裁决：force pin 与
    measure pin 解耦）。'+' 分隔多段（不用 '-'，避免和负值如 -6mA 冲突）；每段
    '<PIN>:值' 指定 force 到该 pin，无前缀则 force 到 meas_pin。'/' 或空 → [](不 force)。
    值原样保留，调用方按单位/变量处理。"""
    s = str(fv_fi).strip()
    if not s or s == "/":
        return []
    out = []
    for seg in s.split("+"):
        seg = seg.strip()
        if not seg:
            continue
        if ":" in seg:
            pin, val = seg.split(":", 1)
            out.append((pin.strip(), val.strip()))
        else:
            out.append((str(meas_pin).strip(), seg))
    return out


def _force_src(force_pin, cp):
    """自动识别 force 走 MLDPS 还是 PPMU（2026-07-16 用户裁决，不硬编码电源名）：
    force_pin 在本 CP 电源轨集合（VCC_pin_rebuild，来自 PIN DEC 电源脚数据）→ MLDPS
    （电源单元）；否则普通 IO → PPMU。CP2 的电源行复用 CP1（同 vcc_rails_str）。"""
    rail_cp = "CP1" if cp == "CP2" else cp
    return "MLDPS" if str(force_pin).strip() in VCC_pin_rebuild(rail_cp) else "PPMU"


def _ppmu_i_clamp(magnitude, unit, *other_magnitudes):
    """按力值/量测值数量级选 PPMU 电流钳位档位——`FORCE_V_PPMU`（"A" in type，
    力压判流）和 `FORCE_I_PPMU`（"V" in type，力流判压）两条分支共用同一套
    分级（2026-07-10 用户裁决：后者原来写死 @2uA，改成按力值大小自动选，跟
    前者对齐，见 F2 VOH/VOL 需要 mA 级力流的真实反例）。"""
    scale_to_ua = {"na": 0.001, "ua": 1.0, "ma": 1000.0, "a": 1_000_000.0}
    unit_key = str(unit).strip().lower()
    if unit_key not in scale_to_ua:
        raise ValueError("PPMU 电流单位不支持: " + str(unit))
    magnitude_ua = max(
        abs(float(value)) for value in (magnitude,) + other_magnitudes
    ) * scale_to_ua[unit_key]
    for upper_ua, clamp in (
        (2, "@2uA"),
        (20, "@20uA"),
        (200, "@200uA"),
        (2000, "@2mA"),
        (32000, "@32mA"),
    ):
        if magnitude_ua < upper_ua:
            return clamp
    raise ValueError(
        "PPMU 电流 " + str(magnitude) + str(unit)
        + " 超出量程上限 32mA"
    )


def _parse_force_current(fvalue):
    """解析力流字符串（如 "-6mA"/"2uA"）→ (数值, 单位)，供 `_ppmu_i_clamp`
    自动选档位用。要求带明确单位，不识别就直接抛异常（母本填错要在生成期
    暴露，不静默兜底）。"""
    m = _FORCE_CURRENT_RE.match(str(fvalue).strip())
    if not m:
        raise ValueError("_parse_force_current: 无法解析力流值 '" + str(fvalue)
                          + "'（需要形如 '-6mA'/'2uA'）")
    return float(m.group(1)), m.group(2)


def Force_Judge(type, pin, fvalue, mvalue, space, used, source, l_range, h_range, f, force_wait=None):
    space_num = " " * space
    if used == "FORCE":
        if source == "PPMU":
            if "A" in type:
                low_limit = calc_limit(mvalue, l_range, h_range, True)
                high_limit = calc_limit(mvalue, l_range, h_range, False)
                clamp = _ppmu_i_clamp(mvalue, type, low_limit, high_limit)
                f.write(space_num + "  FORCE_V_PPMU(" + pin + ", " + fvalue + ", ,")
                f.write(clamp + ", , " + (_recipe_duration(force_wait) or "2mS") + ");\n")
            if "V" in type:
                mag, cur_unit = _parse_force_current(fvalue)
                clamp = _ppmu_i_clamp(mag, cur_unit)
                f.write(space_num + "  FORCE_I_PPMU(" + pin + ", " + fvalue)
                f.write(", " + clamp + ", ,6V, -2V ," + (_recipe_duration(force_wait) or "3mS") + ");\n")
        if source == "MLDPS":
            if "A" in type:
                f.write(space_num + "  FORCE_V_MLDPS(" + pin + ", " + fvalue + ",@6V,")
                # 2026-07-14 #6 审查：原来用严格 < / >，边界裸值（==5/25/250uA、
                # ==2.5/25mA）漏档，且 mA>=500 / A>=1 无兜底 → 残缺档位。改半开
                # 区间（边界归入相邻高档，量程更大不溢出）+ 超上界抛异常。
                if type == "uA":
                    if abs(mvalue) < 5:
                        f.write("@5uA,5uA")
                    elif abs(mvalue) < 25:
                        f.write("@25uA,25uA")
                    elif abs(mvalue) < 250:
                        f.write("@250uA,250uA")
                    elif abs(mvalue) <= 2500:
                        f.write("@2.5mA,2.5mA")
                    else:
                        raise ValueError("FORCE_V_MLDPS: 判据电流 " + str(mvalue)
                                         + "uA 超出 uA 档量程上限 2500uA（pin=" + pin + "）")
                if type == "mA":
                    if abs(mvalue) < 2.5:
                        f.write("@2.5mA,2.5mA")
                    elif abs(mvalue) < 25:
                        f.write("@25mA,25mA")
                    elif abs(mvalue) <= 500:
                        f.write("@500mA,500mA")
                    else:
                        raise ValueError("FORCE_V_MLDPS: 判据电流 " + str(mvalue)
                                         + "mA 超出 MLDPS 量程上限 500mA（pin=" + pin + "）")
                if type == "A":
                    if abs(mvalue) <= 1:
                        f.write("@1A,1A")
                    else:
                        raise ValueError("FORCE_V_MLDPS: 判据电流 " + str(mvalue)
                                         + "A 超出 MLDPS 量程上限 1A（pin=" + pin + "）")

                f.write(",NORM,ON," + (_recipe_duration(force_wait) or "2mS") + ");\n")
            if "V" in type:
                f.write(space_num + "  FORCE_I_MLDPS(" + pin + ", " + fvalue + ", ,")
                f.write(", @25mA,@6V,2V,NORM,ON," + (_recipe_duration(force_wait) or "2mS") + ");\n")
        if source == "FREQ":
            f.write(space_num + "  SET_TFTM_MODE(" + pin + ", SCHMITT_ON);\n")
            _write_recipe_wait(f, force_wait, space_num + "  ")
    if used == "JUDGE":
        if source == "PPMU":
            if "A" in type:
                f.write(space_num + "  JUDGE_I_PPMU(" + pin + ", " + str(
                    calc_limit(mvalue, l_range, h_range, True)) + type + ', ' + str(
                    calc_limit(mvalue, l_range, h_range, False)) + type + ", 2mS,16,AVE,50uS,,);\n")
            if "V" in type:
                f.write(space_num + "  JUDGE_V_PPMU(" + pin + ", " + str(
                    calc_limit(mvalue, l_range, h_range, True)) + type + ', ' + str(
                    calc_limit(mvalue, l_range, h_range, False)) + type + ", 2mS,16,AVE,50uS,,);\n")
        if source == "MLDPS":
            # 2026-07-14 #6 审查修复：原来 "A"(判电流)→JUDGE_V_MLDPS、"V"(判电压)
            # →JUDGE_I_MLDPS，方向反了，与同函数 PPMU(JUDGE_I/V_PPMU)、MEAS
            # (MEAS_I/V_MLDPS) 及 S100 侧(LOGIC_DPS_MI)全部矛盾——电流单位限值配到
            # 判电压函数上自相矛盾。此分支经 :2152（VCC+MLDPS 判定）可达。改为
            # "A"→JUDGE_I_MLDPS、"V"→JUDGE_V_MLDPS。
            if "A" in type:
                f.write(space_num + "  JUDGE_I_MLDPS(" + pin + ", " + str(
                    calc_limit(mvalue, l_range, h_range, True)) + type + ', ' + str(
                    calc_limit(mvalue, l_range, h_range, False)) + type + ",2mS,32,AVE,50uS,,);\n")
            if "V" in type:
                f.write(space_num + "  JUDGE_V_MLDPS(" + pin + ", " + str(
                    calc_limit(mvalue, l_range, h_range, True)) + type + ', ' + str(
                    calc_limit(mvalue, l_range, h_range, False)) + type + ",2mS,32,AVE,50uS,,);\n")

        if source == "FREQ":
            if "Hz" in type:
                f.write(space_num + "  JUDGE_FREQ(" + pin + ", , , ," + str(
                    calc_limit(mvalue, l_range, h_range, True)) + type + ', ' + str(
                    calc_limit(mvalue, l_range, h_range, False)) + type)
                if type == "Hz":
                    f.write(", @1KHZ, , 50mS, );\n")
                # 2026-07-17 修：原用严格 < / >，边界裸值（KHz==1/10/100、MHz==1/5/10）
                # 四分支全落空 → 不写 @gate、JUDGE_FREQ 残缺黏到下一行。改半开级联
                # （边界归入相邻高档 + else 兜底），同本仓 MLDPS 档位（:228）修法。golden
                # temp/fast/PY2113 证 1MHz 信号（高限 1.004>1MHz）用 @5MHZ 留量程。
                if type == "KHz":
                    if mvalue < 1:
                        f.write(", @1KHZ, , 50mS, );\n")
                    elif mvalue < 10:
                        f.write(", @10KHZ, , 50mS, );\n")
                    elif mvalue < 100:
                        f.write(", @100KHZ, , 50mS, );\n")
                    else:
                        f.write(", @1MHZ, , 50mS, );\n")
                if type == "MHz":
                    if mvalue < 1:
                        f.write(", @1MHZ, , 50mS, );\n")
                    elif mvalue < 5:
                        f.write(", @5MHZ, , 50mS, );\n")
                    elif mvalue < 10:
                        f.write(", @10MHZ, , 50mS, );\n")
                    else:
                        f.write(", @100MHZ, , 50mS, );\n")
    if used == "MEAS":
        if source == "PPMU":
            if "A" in type:
                f.write(space_num + "  MEAS_I_PPMU(" + pin + ", 2mS, 16, AVE, 50uS);\n")
            if "V" in type:
                f.write(space_num + "  MEAS_V_PPMU(" + pin + ", 2mS, 16, AVE, 50uS);\n")
        if source == "MLDPS":
            if "A" in type:
                f.write(space_num + "  MEAS_I_MLDPS(" + pin + ", 2mS, 16, AVE, 50uS);\n")
            if "V" in type:
                f.write(space_num + "  MEAS_V_MLDPS(" + pin + ", 2mS, 16, AVE, 50uS);\n")
        if source == "FREQ":
            if "Hz" in type:
                f.write(space_num + "  MEAS_FREQ(" + pin + ", , , ")
                if type == "Hz":
                    f.write(", @1KHZ, , 50mS, );\n")
                # 2026-07-17 修：同 JUDGE 分支——严格 < / > 边界漏档，改半开级联+else 兜底。
                if type == "KHz":
                    if mvalue < 1:
                        f.write(", @1KHZ, , 50mS, );\n")
                    elif mvalue < 10:
                        f.write(", @10KHZ, , 50mS, );\n")
                    elif mvalue < 100:
                        f.write(", @100KHZ, , 50mS, );\n")
                    else:
                        f.write(", @1MHZ, , 50mS, );\n")
                if type == "MHz":
                    if mvalue < 1:
                        f.write(", @1MHZ, , 50mS, );\n")
                    elif mvalue < 5:
                        f.write(", @5MHZ, , 50mS, );\n")
                    elif mvalue < 10:
                        f.write(", @10MHZ, , 50mS, );\n")
                    else:
                        f.write(", @100MHZ, , 50mS, );\n")


def _uid_pn_flag(temp_item_name):
    """按 ADDR_MAP uid 页该字段的真实数据判断是否为"正码+反码"关系（供 write_pat_mem
    的 pn 参数用）。2026-07-03 修：uid_write 里调用 write_pat_mem 原先不管字段实际数据、
    统一硬编码传 "yes"，导致所有 UID trim/verify 字段都被当成反码字段处理，生成
    WRITE_PAT_MEM 引用 <label>w_p/w_n/r_p/r_n 四个标签；但 flash_pattern_label_created
    只有真含"反码"标记的字段（如 Vrefint_Verify）才会在 .pat 里生成这四个标签，不含
    标记的字段（如 Hsi_8M_Trim，高 16bit 是常量 0）只生成不带 _p/_n 的普通标签——两边
    各自独立判断、互不知晓，才会引用不存在的标签（tools/check_pln_labels.py 可测出，
    CRAFT 编译期不查、不会报错，故此前一直没暴露）。

    temp_item_name 是去方括号、去 Verify 后缀、小写的字段名（如 "hsi_8m_trim"/
    "vrefint_"），在 ADDR_MAP 里 Word No.=="uid" 的行范围内找 bit[15:0]/bit[31:16]
    两列同样归一化后匹配的行，判断规则与 flash_pattern_label_created 一致：
    该行 bit[31:16] 含"反码"，或 bit[15:0] 含"bit[31:16]的反码"，才是 "yes"。
    找不到匹配行时保守回 "no"（不强加反码语义）。"""
    word_no = G.col("ADDR_MAP", "Word No.")
    b15_col = G.col("ADDR_MAP", "bit[15:0]")
    b31_col = G.col("ADDR_MAP", "bit[31:16]")
    for k in range(len(word_no)):
        if word_no[k] != "uid":
            continue
        b15 = str(b15_col[k])
        b31 = str(b31_col[k])
        name15 = b15.split("[")[0].split("Verify")[0].lower()
        name31 = b31.split("[")[0].split("Verify")[0].lower()
        if name15 == temp_item_name or name31 == temp_item_name:
            return "yes" if ("反码" in b31 or "bit[31:16]的反码" in b15) else "no"
    return "no"


def _page_field_layout(
    page_name, read_bit, uid_write_dic=None, cp_num=None, catalog=None
):
    """Compile Chroma capture slots through the shared ADDR_MAP catalog."""
    catalog = catalog or G.compiled_adapter.addr_map_catalog

    def include(register):
        if "verify" not in register.register.lower():
            return True
        try:
            return uid_write_dic[register.register] <= cp_num
        except (KeyError, TypeError):
            return False

    result = []
    for entry in catalog.capture_layout(
        page_name, read_bit=int(read_bit), include_register=include
    ):
        if "verify" in entry.register.lower():
            symbol = re.split("verify", entry.register, flags=re.IGNORECASE)[0]
            target = "    " + symbol.upper() + "W[SOCKET]="
        else:
            target = "    REG_" + entry.register.upper() + "[SOCKET]="
        result.append((target, entry.slot_width, entry.real_offset))
    return result


def _page_field_layout_legacy(page_name, read_bit, uid_write_dic=None, cp_num=None):
    """按 ADDR_MAP 某个 Word No.（page_name，如 "uid"/"trim0"/"trim1"/"factory3"）逐字段
    判断真实字节宽度：带反码标记的字段占 4 字节（正码+反码，只读其中真实的 2 字节），
    不带反码标记的字段只占 2 字节（如 uid 页的 Hsi_8/16/24/48M_Trim——它们另一半只是
    常量占位，不是真反码）。原来的 capture 生成代码（uid_write() 的 bake 分支、
    trim_data_read_write() 的 Trimdata_Read 分支）都是整页只判一次"页内有没有任意
    字段带反码"（pn_num=1或2）就统一套用到所有字段头上，一旦页内混了两种宽度（本项目
    uid 页正是如此；trim0/trim1/factory3 目前恰好都是清一色反码字段所以没暴露，但
    代码本身有同样的隐患）后面字段的字节偏移就会全部算错。这里逐字段判断真实宽度。

    uid_write_dic/cp_num：仅 uid 页的 Verify 字段需要——按 CP 门控（<=cp_num 才算
    已建立），沿用原 label_num 逻辑；trim0/trim1/factory3 的字段全是寄存器名（不含
    "Verify"），不受门控，两参数可不传。

    另外：read_bit>32（如本项目=64）时硬件按 read_bit 位宽整块捕获，块内高位那部分先出——
    同 otp_read_write 的 gs=read_bit//32 分组反序是同一套约定，原 temp_data_capture()
    (pn="yes"分支) 靠 c32_num 分组+sum_flag 递减实现的就是这个反转，只是它假设组内每个
    字段都占 4 字节（同上面那个 bug 一样的"整页统一"问题）。这里按 ADDR_MAP 绝对行号
    每 gs 行分一组（跟原逻辑的分组边界一致），组内若有 ≥2 个通过门控的字段，把这些字段
    的先后顺序整体反转（只反转组内顺序，组间顺序不变），再按各自真实宽度顺序编号偏移。

    4 字节（带反码）字段内部也分先后：捕获是 MSB 先出，即 4 字节槽的前 2 字节固定对应
    bit[31:16]、后 2 字节对应 bit[15:0]。哪一半是"真实值"由反码标记出现在哪一列决定
    （标记出现在 bit[15:0] 列文本里，说明 bit[15:0]=反码、真实值在 bit[31:16]=前 2 字节；
    反过来标记在 bit[31:16] 列文本里，真实值就在 bit[15:0]=后 2 字节）——之前统一按"永远
    读前 2 字节"处理，遇到反码标记出现在 bit[31:16] 列（真实值在 bit[15:0]/后 2 字节）
    的母本就会把反码值当成真实值读错（用户用 program_PCD009_V0.4 实测坐实）。
    返回 [(type_flag_str, width, sub_off), ...]，sub_off 是真实 2 字节在其所在槽内的
    起始偏移（0 或 2），非 0 只会出现在 width=4 且反码标记在 bit[31:16] 列的情况。"""
    gs = max(1, int(read_bit) // 32)
    grouped_rows = []  # (group_idx, type_flag, width, sub_off)
    idx_in_page = 0
    for item_uid in range(len(G.col("ADDR_MAP", "data type"))):
        if G.col("ADDR_MAP", "Word No.")[item_uid] != page_name:
            continue
        if G.col("ADDR_MAP", "data type")[item_uid] == "lable":
            b15 = str(G.col("ADDR_MAP", "bit[15:0]")[item_uid])
            b31 = str(G.col("ADDR_MAP", "bit[31:16]")[item_uid])
            if "反码" in b15:
                # bit[15:0] 是反码 → 真实值在 bit[31:16]，即 4 字节槽的前 2 字节
                width, real_val, sub_off = 4, b31, 0
            elif "反码" in b31:
                # bit[31:16] 是反码 → 真实值在 bit[15:0]，即 4 字节槽的后 2 字节
                width, real_val, sub_off = 4, b15, 2
            else:
                width, real_val, sub_off = 2, b15, 0
            if "verify" in real_val.lower():
                try:
                    gated_in = uid_write_dic[real_val] <= cp_num
                except (KeyError, TypeError):
                    gated_in = False
            else:
                gated_in = True
            if gated_in:
                if "verify" not in real_val.lower():
                    type_flag = "    REG_" + real_val.split("[")[0].upper() + "[SOCKET]="
                else:
                    type_flag = "    " + real_val.split("Verify")[0].upper() + "W[SOCKET]="
                grouped_rows.append((idx_in_page // gs, type_flag, width, sub_off))
        idx_in_page += 1

    layout = []
    i = 0
    while i < len(grouped_rows):
        j = i
        cur_group = grouped_rows[i][0]
        while j < len(grouped_rows) and grouped_rows[j][0] == cur_group:
            j += 1
        layout.extend(reversed(grouped_rows[i:j]))
        i = j
    return [(tf, w, so) for _, tf, w, so in layout]


def write_pat_mem(f, result, bit, way, tabspace, write_item, write_temp, write_label, pn, read_dc=False):
    # read_dc=True：读侧比较值一律写 "X"（don't care）——bake 结转 seed 步骤专用
    # （先把软件缓冲区跟"芯片里现在实际是什么"对齐，这一步本身不需要、也不应该去校验
    # 读回值，真正的校验留给后面 final 改写后的 erase→prog→read）。
    read_val = ["X", "X"] if read_dc else None
    break_space = tabspace * " "
    F_num = int(((bit + 1) / 4)) * "F"
    # f.write(break_space+"  SOCKET_INC(FRZ_OFF)\n  {\n")
    f.write(break_space + "    //******************" + write_item + "**************************\n")
    f.write(break_space + "    TEMP = 0x" + F_num + ";\n")
    f.write(break_space + "    TEMP = " + write_temp + ";\n")

    f.write(break_space + "    for(J=0;J<=" + str(
        bit) + ";J++)\n    {\n      BIT[J] = 0;\n      BIT[J] = TEMP%2;\n      TEMP = TEMP/2;\n    }\n\n")
    f.write(break_space + "    for(J=" + str(bit) + ";J>=0;J--)\n    {\n      if(BIT[J]==0)\n      {\n")
    if pn == "yes":
        f.write(break_space + "        WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", " + result[
            "pgm"] + ":" + write_label + 'w_p+' + str(bit) + way + ' , ,"0");\n')
        f.write(break_space + "        WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", " + result[
            "pgm"] + ":" + write_label + 'w_n+' + str(bit) + way + ' , ,"1");\n\n')
        f.write(break_space + "        WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", " + result[
            "read"] + ":" + write_label + 'r_p+' + str(bit) + way + ' , ,"' + (read_val[0] if read_val else "L") + '");\n')
        f.write(break_space + "        WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", " + result[
            "read"] + ":" + write_label + 'r_n+' + str(bit) + way + ' , ,"' + (read_val[1] if read_val else "H") + '");\n')
    else:
        f.write(break_space + "        WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", " + result[
            "pgm"] + ":" + write_label + 'w+' + str(bit) + way + ' , ,"0");\n\n')
        f.write(break_space + "        WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", " + result[
            "read"] + ":" + write_label + 'r+' + str(bit) + way + ' , ,"' + (read_val[0] if read_val else "L") + '");\n')

    f.write(break_space + "      }\n")  # for if

    f.write(break_space + "      else\n      {\n")
    if pn == "yes":
        f.write(break_space + "        WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", " + result[
            "pgm"] + ":" + write_label + 'w_p+' + str(bit) + way + ' , ,"1");\n')
        f.write(break_space + "        WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", " + result[
            "pgm"] + ":" + write_label + 'w_n+' + str(bit) + way + ' , ,"0");\n\n')
        f.write(break_space + "        WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", " + result[
            "read"] + ":" + write_label + 'r_p+' + str(bit) + way + ' , ,"' + (read_val[1] if read_val else "H") + '");\n')
        f.write(break_space + "        WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", " + result[
            "read"] + ":" + write_label + 'r_n+' + str(bit) + way + ' , ,"' + (read_val[0] if read_val else "L") + '");\n')
    else:
        f.write(break_space + "        WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", " + result[
            "pgm"] + ":" + write_label + 'w+' + str(bit) + way + ' , ,"1");\n\n')
        f.write(break_space + "        WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", " + result[
            "read"] + ":" + write_label + 'r+' + str(bit) + way + ' , ,"' + (read_val[1] if read_val else "H") + '");\n')

    f.write(break_space + "      }\n")  # for else
    f.write(break_space + "    }\n\n")  # for j


def hex_code_item_write(code_name, f, j):
    if G.col("FLOW", "type")[j] == "hex" and code_name[G.i].split("_")[-1] == \
            G.col("FLOW", "CP NO")[j]:
        f.write(G.col("FLOW", "item")[j] + "()\n{\n")
        f.write("  TEST_NUM=" + str((j + 1) * 100) + ";\n" + '  TEST_NO( TEST_NUM);DATALOG_MSG="' +
                G.col("FLOW", "item")[j] + '"; \n\n')
        f.write("  POWER_ON(" + G.col("FLOW", "Vcc")[j] + ");\n\n")


        f.write('  POWER_OFF();\n  //POWER_DOWN_FAIL_SITE_X(MODE_B);\n\n')
        f.write("}\n\n")  # item{}


def _dac_final_addrmap_expr(name_prefix):
    """按 ADDR_MAP `CP addr map` 列里 "<name_prefix>Trim[..]" 这种共享寄存器位段声明，
    解出该字段所在寄存器（`bit[15:0]` 列）与位偏移，拼出 "(REG_xxx[SOCKET]&mask)>>shift"
    表达式；找不到返回 None。跟 set_all_final_vposp 里 PUMP/Vcsl/Vneg2/Vbl 用的解码算法
    是同一套，抽出来给 [[reuse_dac_restore_items]] 的跨 CP 补值场景复用（如 CP3 复用
    CP1 已经 trim 好的 Hsi_Vrega，需要从 EPR 读回的共享寄存器里单独抠出这个字段）。"""
    target_symbol = dac_final_symbol(name_prefix)

    def is_target(field):
        return dac_final_symbol(field.split("[")[0]) == target_symbol

    for item_cyc in range(len(G.col("ADDR_MAP", "CP addr map"))):
        if type(G.col("ADDR_MAP", "CP addr map")[item_cyc]) != str:
            continue
        temp_list = G.col("ADDR_MAP", "CP addr map")[item_cyc].split(",")
        if not any(is_target(field) for field in temp_list):
            continue
        bit_list = []
        shift_flag = 0
        shift = 0
        for temp_cyc in range(len(temp_list)):
            bit_num = 0
            try:
                bit_num = int(temp_list[temp_cyc].split("[")[1].split(":")[0]) + 1
            except Exception:
                try:
                    bit_num = leading_bit_width(temp_list[temp_cyc])
                except Exception:
                    bit_num = 1
            if shift_flag == 1:
                shift += bit_num
            if is_target(temp_list[temp_cyc]):
                shift_flag = 1
                bit_list.extend([1] * bit_num)
            else:
                bit_list.extend([0] * bit_num)
        reg_name = G.col("ADDR_MAP", "bit[15:0]")[item_cyc].split("[")[0].upper()
        return "(REG_" + reg_name + "[SOCKET]&" + bin_list_to_hex(bit_list) + ")>>" + str(shift)
    return None


def set_all_final_vposp(f):
    f.write("  //set all trimming final data to Fbist  vposp\n")
    f.write("  SOCKET_INC(FRZ_OFF)\n  {\n")

    G.set_vposp_name.clear()
    for z in range(len(G.col("FLOW", "PUMP"))):
        if G.col("FLOW", "PUMP")[z] == "yes":
            G.set_vposp_name.append(
                dac_final_symbol(G.col("FLOW", "item")[z]) + "[SOCKET]" + str(
                    G.col("FLOW", "DAC bit")[z]))
    G.set_vposp_name.append("VCSL_DAC_FINAL[SOCKET]3")
    G.set_vposp_name.append("VNEG2_DAC_FINAL[SOCKET]3")
    G.set_vposp_name.append("VBL_DAC_FINAL[SOCKET]4")

    pos_cyc = 1
    for z in range(len(G.set_vposp_name)):
        if G.set_vposp_name[z].split("_")[0][-1].lower() == "p" or \
                G.set_vposp_name[z].split("_")[0][-1].lower() == "e":
            pos_cyc = 2
        else:
            pos_cyc = 1
        for cyc in range(pos_cyc):
            if cyc == 0 and G.set_vposp_name[z].split("_")[0][-1].lower() == "e":
                continue
            elif cyc == 1:
                f.write("    //////////////////////user " + G.set_vposp_name[z].split("_")[
                    0] + "////////////////////////\n")
            else:
                f.write("    //////////////////////" + G.set_vposp_name[z].split("_")[
                    0] + "////////////////////////\n")
            f.write("    TEMP = " + G.set_vposp_name[z].rstrip("0123456789") + "; // data\n")
            f.write("    for(J=0;J<=" + str(
                int(G.set_vposp_name[z].split("]")[1]) - 1) + ";J++)\n    {\n")
            f.write(
                "      BIT[J] = 0;\n      BIT[J] = TEMP%2;\n      TEMP = TEMP/2;\n    }\n\n")
            f.write("    for(J=" + str(
                int(G.set_vposp_name[z].split("]")[1]) - 1) + ";J>=0;J--)\n    {\n")
            if cyc == 1 and G.set_vposp_name[z].split("_")[0][-1].lower() == "p":
                f.write(
                    "      if(BIT[J]==0)\n      {\n        WRITE_PAT_MEM(SOCKET, " + str(
                        G.col("VERSION", "SWD PIN")[G.i]) + ", set_all_final_vposp:prog_" +
                    G.set_vposp_name[z][1].lower() + "dac+" + str(
                        int(G.set_vposp_name[z].split("]")[
                                1]) - 1) + '-J, ,"0");\n      }\n')

                f.write("      else\n      {\n        WRITE_PAT_MEM(SOCKET, " + str(
                    G.col("VERSION", "SWD PIN")[G.i]) + ", set_all_final_vposp:prog_" +
                        G.set_vposp_name[z][1].lower() + "dac+" + str(
                    int(G.set_vposp_name[z].split("]")[
                            1]) - 1) + '-J, ,"1");\n      }\n    }\n\n')
            elif cyc == 1 and G.set_vposp_name[z].split("_")[0][-1].lower() == "e":
                f.write(
                    "      if(BIT[J]==0)\n      {\n        WRITE_PAT_MEM(SOCKET, " + str(
                        G.col("VERSION", "SWD PIN")[G.i]) + ", set_all_final_vposp:ers_" +
                    G.set_vposp_name[z][1].lower() + "dac+" + str(
                        int(G.set_vposp_name[z].split("]")[
                                1]) - 1) + '-J, ,"0");\n      }\n')

                f.write("      else\n      {\n        WRITE_PAT_MEM(SOCKET, " + str(
                    G.col("VERSION", "SWD PIN")[G.i]) + ", set_all_final_vposp:ers_" +
                        G.set_vposp_name[z][1].lower() + "dac+" + str(
                    int(G.set_vposp_name[z].split("]")[
                            1]) - 1) + '-J, ,"1");\n      }\n    }\n\n')


            elif cyc == 0 and G.set_vposp_name[z].split("_")[0][-1].lower() == "p":
                f.write(
                    "      if(BIT[J]==0)\n      {\n        WRITE_PAT_MEM(SOCKET, " + str(
                        G.col("VERSION", "SWD PIN")[G.i]) + ", set_all_final_vposp:pre_" +
                    G.set_vposp_name[z][1].lower() + "dac+" + str(
                        int(G.set_vposp_name[z].split("]")[
                                1]) - 1) + '-J, ,"0");\n      }\n')

                f.write("      else\n      {\n        WRITE_PAT_MEM(SOCKET, " + str(
                    G.col("VERSION", "SWD PIN")[G.i]) + ", set_all_final_vposp:pre_" +
                        G.set_vposp_name[z][1].lower() + "dac+" + str(
                    int(G.set_vposp_name[z].split("]")[
                            1]) - 1) + '-J, ,"1");\n      }\n    }\n\n')
            else:
                f.write("      if(BIT[J]==0)\n      {\n        WRITE_PAT_MEM(SOCKET, " + str(
                    G.col("VERSION", "SWD PIN")[G.i]) + ", set_all_final_vposp:" +
                        G.set_vposp_name[z].split("_")[0].lower() + "+" + str(
                    int(G.set_vposp_name[z].split("]")[1]) - 1) + '-J, ,"0");\n      }\n')

                f.write("      else\n      {\n        WRITE_PAT_MEM(SOCKET, " + str(
                    G.col("VERSION", "SWD PIN")[G.i]) + ", set_all_final_vposp:" +
                        G.set_vposp_name[z].split("_")[0].lower() + "+" + str(
                    int(G.set_vposp_name[z].split("]")[
                            1]) - 1) + '-J, ,"1");\n      }\n    }\n\n')

    f.write("  }\n")
    f.write("  //fflush(stdout);\n\n\n")


def temp_data_capture(f, cyc, pn, bit, code_name):
    addr_map_item = []
    uid_flag = ""
    bit_015_1631_flag = 0
    temp_item_flag = "bit[15:0]"
    uid_write_dic = {}
    uid_write_item = []
    uid_write_num = []
    groups_type= []
    label_count = 1
    page_word = G.col("VERSION", "page word")[0]
    for u in range(len(G.col("FLOW", "UID"))):
        if G.col("FLOW", "UID")[u] == "yes":
            uid_write_item.append(G.col("FLOW", "item")[u])
            uid_write_num.append(int(G.col("FLOW", "CP NO")[u][-1]))

    # 同一个 item 名字可能在多个 CP 里都标 UID==yes（如 Hsi_8M_Trim 在 CP1/CP3 都是），
    # dict(zip(...)) 遇重复 key 会后写覆盖先写，把该项"起算 CP"错记成最后一次出现的 CP，
    # 后面 "<=当前CP" 的判断就会因为这个被错记的值而漏判。改用 setdefault 保留第一次
    # 出现（即最早/最小的 CP digit），跟 FLOW 表按 CP 顺序排列的既有假设一致
    # （2026-07-06 修，见 [[reuse_dac_restore_items]] 同批修复）。
    uid_write_dic = {}
    for name, num in zip(uid_write_item, uid_write_num):
        uid_write_dic.setdefault(name, num)

    for z in range(len(G.col("ADDR_MAP", "Word No."))):
        if G.col("ADDR_MAP", "Word No.")[z] not in addr_map_item:
            addr_map_item.append(G.col("ADDR_MAP", "Word No.")[z])

    if pn == "yes":
        if bit == 32:
            c32_num = 1
        if bit == 64:
            c32_num = 2
        if bit == 128:
            c32_num = 4
        if bit == 256:
            c32_num = 8

        for i in range(0,page_word,c32_num):
            if G.col("ADDR_MAP", "data type")[i+page_word*cyc] == "lable":
                if "反码" in G.col("ADDR_MAP", "bit[15:0]")[i+page_word*cyc]:
                    bit_015_1631_flag1 = 0
                    temp_item_flag = "bit[31:16]"
                elif "反码" in G.col("ADDR_MAP", "bit[31:16]")[i+page_word*cyc]:
                    bit_015_1631_flag1 = 2
                    temp_item_flag = "bit[15:0]"
                else:
                    # 对齐 S100：无"反码"标记时默认取 bit[15:0]，否则 temp_item_flag 会残留上一轮值
                    # → 读错字段，verify 寄存器被误写成 REG_*_VERIFY（未声明）而非 *_W。
                    bit_015_1631_flag1 = 1
                    temp_item_flag = "bit[15:0]"
                if "verify" not in list(G.ADDR_MAP[temp_item_flag])[i+page_word*cyc].lower():
                    type_flag1 = "    REG_" + list(G.ADDR_MAP[temp_item_flag])[i+page_word*cyc].split("[")[0].upper() + "[SOCKET]="
                elif "verify" in list(G.ADDR_MAP[temp_item_flag])[i+page_word*cyc].lower():
                    # 对齐 S100 大更新：仅 Word No.==uid 的 verify 受 CP 门控，非 uid 的 verify 无条件归 *_W
                    # （chroma 旧写法裸查 uid_write_dic[label]，遇非 uid 的 lable verify 会 KeyError）
                    if G.col("ADDR_MAP", "Word No.")[i+page_word*cyc] == "uid":
                        if uid_write_dic[list(G.ADDR_MAP[temp_item_flag])[i+page_word*cyc]] <= int(code_name.split("_")[-1][-1]):
                            type_flag1 = "    " + list(G.ADDR_MAP[temp_item_flag])[i+page_word*cyc].split("Verify")[
                                0].upper() + "W[SOCKET]="
                    else:
                        type_flag1 = "    " + list(G.ADDR_MAP[temp_item_flag])[i+page_word*cyc].split("Verify")[
                            0].upper() + "W[SOCKET]="

            else:
                type_flag1 = "888[15:0]"
                bit_015_1631_flag1 = 9

            if bit != 32:
                if G.col("ADDR_MAP", "data type")[i+1+page_word*cyc] == "lable":
                    if "反码" in G.col("ADDR_MAP", "bit[15:0]")[i+1+page_word*cyc]:
                        bit_015_1631_flag2 = 0
                        temp_item_flag = "bit[31:16]"
                    elif "反码" in G.col("ADDR_MAP", "bit[31:16]")[i+1+page_word*cyc]:
                        bit_015_1631_flag2 = 2
                        temp_item_flag = "bit[15:0]"
                    else:
                        bit_015_1631_flag2 = 1
                        temp_item_flag = "bit[15:0]"
                    if "verify" not in str(list(G.ADDR_MAP[temp_item_flag])[i+1+page_word*cyc]).lower():
                        type_flag2 = "    REG_" + list(G.ADDR_MAP[temp_item_flag])[i+1+page_word*cyc].split("[")[0].upper() + "[SOCKET]="
                    elif "verify" in str(list(G.ADDR_MAP[temp_item_flag])[i+1+page_word*cyc]).lower():
                        if G.col("ADDR_MAP", "Word No.")[i+1+page_word*cyc] == "uid":
                            if uid_write_dic[list(G.ADDR_MAP[temp_item_flag])[i+1+page_word*cyc]] <= int(code_name.split("_")[-1][-1]):
                                type_flag2 = "    " + list(G.ADDR_MAP[temp_item_flag])[i+1+page_word*cyc].split("Verify")[
                                    0].upper() + "W[SOCKET]="
                        else:
                            type_flag2 = "    " + list(G.ADDR_MAP[temp_item_flag])[i+1+page_word*cyc].split("Verify")[
                                0].upper() + "W[SOCKET]="
                else:
                    type_flag2 = "888[15:0]"
                    bit_015_1631_flag2 = 9

            if bit != 32 and bit != 64:
                if G.col("ADDR_MAP", "data type")[i+2+page_word*cyc] == "lable":
                    if "反码" in G.col("ADDR_MAP", "bit[15:0]")[i+2+page_word*cyc]:
                        bit_015_1631_flag3 = 0
                        temp_item_flag = "bit[31:16]"
                    elif "反码" in G.col("ADDR_MAP", "bit[31:16]")[i+2+page_word*cyc]:
                        bit_015_1631_flag3 = 2
                        temp_item_flag = "bit[15:0]"
                    else:
                        bit_015_1631_flag3 = 1
                        temp_item_flag = "bit[15:0]"
                    if "verify" not in str(list(G.ADDR_MAP[temp_item_flag])[i+2+page_word*cyc]).lower():
                        type_flag3 = "    REG_" + list(G.ADDR_MAP[temp_item_flag])[i+2+page_word*cyc].split("[")[0].upper() + "[SOCKET]="
                    elif "verify" in str(list(G.ADDR_MAP[temp_item_flag])[i+2+page_word*cyc]).lower():
                        if G.col("ADDR_MAP", "Word No.")[i+2+page_word*cyc] == "uid":
                            if uid_write_dic[list(G.ADDR_MAP[temp_item_flag])[i+2+page_word*cyc]] <= int(code_name.split("_")[-1][-1]):
                                type_flag3 = "    " + list(G.ADDR_MAP[temp_item_flag])[i+2+page_word*cyc].split("Verify")[
                                    0].upper() + "W[SOCKET]="
                        else:
                            type_flag3 = "    " + list(G.ADDR_MAP[temp_item_flag])[i+2+page_word*cyc].split("Verify")[
                                0].upper() + "W[SOCKET]="
                else:
                    type_flag3 = "888[15:0]"
                    bit_015_1631_flag3 = 9

                if G.col("ADDR_MAP", "data type")[i+3+page_word*cyc] == "lable":
                    if "反码" in G.col("ADDR_MAP", "bit[15:0]")[i+3+page_word*cyc]:
                        bit_015_1631_flag4 = 0
                        temp_item_flag = "bit[31:16]"
                    elif "反码" in G.col("ADDR_MAP", "bit[31:16]")[i+3+page_word*cyc]:
                        bit_015_1631_flag4 = 2
                        temp_item_flag = "bit[15:0]"
                    else:
                        bit_015_1631_flag4 = 1
                        temp_item_flag = "bit[15:0]"
                    if "verify" not in str(list(G.ADDR_MAP[temp_item_flag])[i+3+page_word*cyc]).lower():
                        type_flag4 = "    REG_" + list(G.ADDR_MAP[temp_item_flag])[i+3+page_word*cyc].split("[")[0].upper() + "[SOCKET]="
                    elif "verify" in str(list(G.ADDR_MAP[temp_item_flag])[i+3+page_word*cyc]).lower():
                        if G.col("ADDR_MAP", "Word No.")[i+3+page_word*cyc] == "uid":
                            if uid_write_dic[list(G.ADDR_MAP[temp_item_flag])[i+3+page_word*cyc]] <= int(code_name.split("_")[-1][-1]):
                                type_flag4 = "    " + list(G.ADDR_MAP[temp_item_flag])[i+3+page_word*cyc].split("Verify")[
                                    0].upper() + "W[SOCKET]="
                        else:
                            type_flag4 = "    " + list(G.ADDR_MAP[temp_item_flag])[i+3+page_word*cyc].split("Verify")[
                                0].upper() + "W[SOCKET]="
                else:
                    type_flag4 = "888[15:0]"
                    bit_015_1631_flag4 = 9

            if bit == 256:
                if G.col("ADDR_MAP", "data type")[i+4+page_word*cyc] == "lable":
                    if "反码" in G.col("ADDR_MAP", "bit[15:0]")[i+4+page_word*cyc]:
                        bit_015_1631_flag5 = 0
                        temp_item_flag = "bit[31:16]"
                    elif "反码" in G.col("ADDR_MAP", "bit[31:16]")[i+4+page_word*cyc]:
                        bit_015_1631_flag5 = 2
                        temp_item_flag = "bit[15:0]"
                    else:
                        bit_015_1631_flag5 = 1
                        temp_item_flag = "bit[15:0]"
                    if "verify" not in str(list(G.ADDR_MAP[temp_item_flag])[i+4+page_word*cyc]).lower():
                        type_flag5 = "    REG_" + list(G.ADDR_MAP[temp_item_flag])[i+4+page_word*cyc].split("[")[0].upper() + "[SOCKET]="
                    elif "verify" in str(list(G.ADDR_MAP[temp_item_flag])[i+4+page_word*cyc]).lower():
                        if G.col("ADDR_MAP", "Word No.")[i+4+page_word*cyc] == "uid":
                            if uid_write_dic[list(G.ADDR_MAP[temp_item_flag])[i+4+page_word*cyc]] <= int(code_name.split("_")[-1][-1]):
                                type_flag5 = "    " + list(G.ADDR_MAP[temp_item_flag])[i+4+page_word*cyc].split("Verify")[
                                    0].upper() + "W[SOCKET]="
                        else:
                            type_flag5 = "    " + list(G.ADDR_MAP[temp_item_flag])[i+4+page_word*cyc].split("Verify")[
                                0].upper() + "W[SOCKET]="
                else:
                    type_flag5 = "888[15:0]"
                    bit_015_1631_flag5 = 9

                if G.col("ADDR_MAP", "data type")[i+5+page_word*cyc] == "lable":
                    if "反码" in G.col("ADDR_MAP", "bit[15:0]")[i+5+page_word*cyc]:
                        bit_015_1631_flag6 = 0
                        temp_item_flag = "bit[31:16]"
                    elif "反码" in G.col("ADDR_MAP", "bit[31:16]")[i+5+page_word*cyc]:
                        bit_015_1631_flag6 = 2
                        temp_item_flag = "bit[15:0]"
                    else:
                        bit_015_1631_flag6 = 1
                        temp_item_flag = "bit[15:0]"
                    if "verify" not in str(list(G.ADDR_MAP[temp_item_flag])[i+5+page_word*cyc]).lower():
                        type_flag6 = "    REG_" + list(G.ADDR_MAP[temp_item_flag])[i+5+page_word*cyc].split("[")[0].upper() + "[SOCKET]="
                    elif "verify" in str(list(G.ADDR_MAP[temp_item_flag])[i+5+page_word*cyc]).lower():
                        if G.col("ADDR_MAP", "Word No.")[i+5+page_word*cyc] == "uid":
                            if uid_write_dic[list(G.ADDR_MAP[temp_item_flag])[i+5+page_word*cyc]] <= int(code_name.split("_")[-1][-1]):
                                type_flag6 = "    " + list(G.ADDR_MAP[temp_item_flag])[i+5+page_word*cyc].split("Verify")[
                                    0].upper() + "W[SOCKET]="
                        else:
                            type_flag6 = "    " + list(G.ADDR_MAP[temp_item_flag])[i+5+page_word*cyc].split("Verify")[
                                0].upper() + "W[SOCKET]="
                else:
                    type_flag6 = "888[15:0]"
                    bit_015_1631_flag6 = 9

                if G.col("ADDR_MAP", "data type")[i+6+page_word*cyc] == "lable":
                    if "反码" in G.col("ADDR_MAP", "bit[15:0]")[i+6+page_word*cyc]:
                        bit_015_1631_flag7 = 0
                        temp_item_flag = "bit[31:16]"
                    elif "反码" in G.col("ADDR_MAP", "bit[31:16]")[i+6+page_word*cyc]:
                        bit_015_1631_flag7 = 2
                        temp_item_flag = "bit[15:0]"
                    else:
                        bit_015_1631_flag7 = 1
                        temp_item_flag = "bit[15:0]"
                    if "verify" not in str(list(G.ADDR_MAP[temp_item_flag])[i+6+page_word*cyc]).lower():
                        type_flag7 = "    REG_" + list(G.ADDR_MAP[temp_item_flag])[i+6+page_word*cyc].split("[")[0].upper() + "[SOCKET]="
                    elif "verify" in str(list(G.ADDR_MAP[temp_item_flag])[i+6+page_word*cyc]).lower():
                        if G.col("ADDR_MAP", "Word No.")[i+6+page_word*cyc] == "uid":
                            if uid_write_dic[list(G.ADDR_MAP[temp_item_flag])[i+6+page_word*cyc]] <= int(code_name.split("_")[-1][-1]):
                                type_flag7 = "    " + list(G.ADDR_MAP[temp_item_flag])[i+6+page_word*cyc].split("Verify")[
                                    0].upper() + "W[SOCKET]="
                        else:
                            type_flag7 = "    " + list(G.ADDR_MAP[temp_item_flag])[i+6+page_word*cyc].split("Verify")[
                                0].upper() + "W[SOCKET]="
                else:
                    type_flag7 = "888[15:0]"
                    bit_015_1631_flag7 = 9

                if G.col("ADDR_MAP", "data type")[i+7+page_word*cyc] == "lable":
                    if "反码" in G.col("ADDR_MAP", "bit[15:0]")[i+7+page_word*cyc]:
                        bit_015_1631_flag8 = 0
                        temp_item_flag = "bit[31:16]"
                    elif "反码" in G.col("ADDR_MAP", "bit[31:16]")[i+7+page_word*cyc]:
                        bit_015_1631_flag8 = 2
                        temp_item_flag = "bit[15:0]"
                    else:
                        bit_015_1631_flag8 = 1
                        temp_item_flag = "bit[15:0]"
                    if "verify" not in str(list(G.ADDR_MAP[temp_item_flag])[i+7+page_word*cyc]).lower():
                        type_flag8 = "    REG_" + list(G.ADDR_MAP[temp_item_flag])[i+7+page_word*cyc].split("[")[0].upper() + "[SOCKET]="
                    elif "verify" in str(list(G.ADDR_MAP[temp_item_flag])[i+7+page_word*cyc]).lower():
                        if G.col("ADDR_MAP", "Word No.")[i+7+page_word*cyc] == "uid":
                            if uid_write_dic[list(G.ADDR_MAP[temp_item_flag])[i+7+page_word*cyc]] <= int(code_name.split("_")[-1][-1]):
                                type_flag8 = "    " + list(G.ADDR_MAP[temp_item_flag])[i+7+page_word*cyc].split("Verify")[
                                    0].upper() + "W[SOCKET]="
                        else:
                            type_flag8 = "    " + list(G.ADDR_MAP[temp_item_flag])[i+7+page_word*cyc].split("Verify")[
                                0].upper() + "W[SOCKET]="
                else:
                    type_flag8 = "888[15:0]"
                    bit_015_1631_flag8 = 9
            if bit == 32:
                groups_type.append((str(bit_015_1631_flag1)+"&"+G.col("ADDR_MAP", "data type")[i+page_word*cyc]+"&"+type_flag1))

            if bit == 64:
                groups_type.append((str(bit_015_1631_flag1)+"&"+G.col("ADDR_MAP", "data type")[i+page_word*cyc]+"&"+type_flag1, str(bit_015_1631_flag2)+"&"+G.col("ADDR_MAP", "data type")[i+1+page_word*cyc]+"&"+type_flag2))

            if bit == 128:
                groups_type.append((str(bit_015_1631_flag1) + "&" + G.col("ADDR_MAP", "data type")[i + page_word * cyc] + "&" + type_flag1,
                                    str(bit_015_1631_flag2) + "&" + G.col("ADDR_MAP", "data type")[i + 1 + page_word * cyc] + "&" + type_flag2,
                                    str(bit_015_1631_flag3) + "&" + G.col("ADDR_MAP", "data type")[i + 2 + page_word * cyc] + "&" + type_flag3,
                                    str(bit_015_1631_flag4) + "&" + G.col("ADDR_MAP", "data type")[i + 3 + page_word * cyc] + "&" + type_flag4
                                    ))

            if bit == 256:
                groups_type.append((str(bit_015_1631_flag1) + "&" + G.col("ADDR_MAP", "data type")[i + page_word * cyc] + "&" + type_flag1,
                                    str(bit_015_1631_flag2) + "&" + G.col("ADDR_MAP", "data type")[i + 1 + page_word * cyc] + "&" + type_flag2,
                                    str(bit_015_1631_flag3) + "&" + G.col("ADDR_MAP", "data type")[i + 2 + page_word * cyc] + "&" + type_flag3,
                                    str(bit_015_1631_flag4) + "&" + G.col("ADDR_MAP", "data type")[i + 3 + page_word * cyc] + "&" + type_flag4,
                                    str(bit_015_1631_flag5) + "&" + G.col("ADDR_MAP", "data type")[i + 4 + page_word * cyc] + "&" + type_flag5,
                                    str(bit_015_1631_flag6) + "&" + G.col("ADDR_MAP", "data type")[i + 5 + page_word * cyc] + "&" + type_flag6,
                                    str(bit_015_1631_flag7) + "&" + G.col("ADDR_MAP", "data type")[i + 6 + page_word * cyc] + "&" + type_flag7,
                                    str(bit_015_1631_flag8) + "&" + G.col("ADDR_MAP", "data type")[i + 7 + page_word * cyc] + "&" + type_flag8
                                    ))

        # print(groups_type)
        label_num_flag = 0
        if bit == 32:
            for i in range(len(groups_type)):
                if groups_type[i].split("&")[1] == "lable" :
                    if groups_type[i].split("&")[2] != "888[15:0]":
                        f.write(groups_type[i].split("&")[2] + addr_map_item[cyc] + "_0x00" + str(
                            G.col("ADDR_MAP", "SM Address")[0 + page_word * cyc].split(";")[0].split("0x")[1])
                                + "[SOCKET][" + str(0 + int(groups_type[i][0].split("&")[0]) + 4 * label_num_flag) + "]*256+" + addr_map_item[
                                    cyc] + "_0x00"
                                + str(G.col("ADDR_MAP", "SM Address")[0 + page_word * cyc].split(";")[0].split("0x")[
                                          1]) + "[SOCKET][" + str(1 + int(groups_type[i][0].split("&")[0]) + 4 * label_num_flag) + "];\n")

                        label_num_flag += 1
                elif groups_type[i].split("&")[0] != "lable" :
                    continue

        index_list=[]
        sum_flag = 0
        if bit != 32:
            for i in range(len(groups_type)):
                sum_flag = len(list(filter(lambda x: "lable" in x, groups_type[i]))) - 1
                for j in range(len(groups_type[i])):
                    if groups_type[i][j].split("&")[1] == "lable":
                        index_list.append(str(j)+"&"+str(sum_flag))
                        sum_flag-=1
                for z in range(len(index_list)):
                    f.write(groups_type[i][int(index_list[z].split("&")[0])].split("&")[2] + addr_map_item[cyc] + "_0x00" + str(G.col("ADDR_MAP", "SM Address")[0 + page_word * cyc].split(";")[0].split("0x")[1])
                          + "[SOCKET][" + str(0+int(groups_type[i][int(index_list[z].split("&")[0])].split("&")[0]) + 4 * (label_num_flag+int(index_list[z].split("&")[1]))) + "]*256+" + addr_map_item[cyc] + "_0x00"
                          + str(G.col("ADDR_MAP", "SM Address")[0 + page_word * cyc].split(";")[0].split("0x")[1]) + "[SOCKET][" + str(1 +int(groups_type[i][int(index_list[z].split("&")[0])].split("&")[0]) + 4 * (label_num_flag+int(index_list[z].split("&")[1]))) + "];\n")
                label_num_flag += len(index_list)
                index_list.clear()

    if pn == "no":
        if bit == 32:
            c32_num = 1
        if bit == 64:
            c32_num = 2
        if bit == 128:
            c32_num = 4
        if bit == 256:
            c32_num = 8

        for i in range(0,page_word,c32_num):
            if G.col("ADDR_MAP", "data type")[i+page_word*cyc] == "lable":
                bit_015_1631_flag1 = 0
                if "verify" not in list(G.ADDR_MAP[temp_item_flag])[i + page_word * cyc].lower():
                    type_flag1 = "    REG_" + G.col("ADDR_MAP", "bit[15:0]")[i+page_word*cyc].split("[")[0].upper() + "[SOCKET]="
                elif "verify" in list(G.ADDR_MAP[temp_item_flag])[i + page_word * cyc].lower():
                    if uid_write_dic[G.col("ADDR_MAP", "bit[15:0]")[i+page_word*cyc]] <= int(code_name.split("_")[-1][-1]):
                        type_flag1 = "    " + G.col("ADDR_MAP", "bit[15:0]")[i+page_word*cyc].split("Verify")[
                            0].upper() + "W[SOCKET]="

            else:
                type_flag1 = "888[15:0]"
                bit_015_1631_flag1 = 9

            if bit != 32:
                if G.col("ADDR_MAP", "data type")[i+1+page_word*cyc] == "lable":
                    bit_015_1631_flag2 = 0
                    if "verify" not in list(G.ADDR_MAP[temp_item_flag])[i + page_word * cyc].lower():
                        type_flag2 = "    REG_" + G.col("ADDR_MAP", "bit[15:0]")[i+1+page_word*cyc].split("[")[0].upper() + "[SOCKET]="
                    elif "verify" in list(G.ADDR_MAP[temp_item_flag])[i + page_word * cyc].lower():
                        if uid_write_dic[G.col("ADDR_MAP", "bit[15:0]")[i+1+page_word*cyc]] <= int(code_name.split("_")[-1][-1]):
                            type_flag2 = "    " + G.col("ADDR_MAP", "bit[15:0]")[i+1+page_word*cyc].split("Verify")[
                                0].upper() + "W[SOCKET]="
                else:
                    type_flag2 = "888[15:0]"
                    bit_015_1631_flag2 = 9

            if bit != 32 and bit != 64:
                if G.col("ADDR_MAP", "data type")[i+2+page_word*cyc] == "lable":
                    bit_015_1631_flag3 = 0
                    if "verify" not in list(G.ADDR_MAP[temp_item_flag])[i + page_word * cyc].lower():
                        type_flag3 = "    REG_" + G.col("ADDR_MAP", "bit[15:0]")[i+2+page_word*cyc].split("[")[0].upper() + "[SOCKET]="
                    elif "verify" in list(G.ADDR_MAP[temp_item_flag])[i + page_word * cyc].lower():
                        if uid_write_dic[G.col("ADDR_MAP", "bit[15:0]")[i+2+page_word*cyc]] <= int(code_name.split("_")[-1][-1]):
                            type_flag3 = "    " + G.col("ADDR_MAP", "bit[15:0]")[i+2+page_word*cyc].split("Verify")[
                                0].upper() + "W[SOCKET]="
                else:
                    type_flag3 = "888[15:0]"
                    bit_015_1631_flag3 = 9

                if G.col("ADDR_MAP", "data type")[i+3+page_word*cyc] == "lable":
                    bit_015_1631_flag4 = 0
                    if "verify" not in list(G.ADDR_MAP[temp_item_flag])[i + page_word * cyc].lower():
                        type_flag4 = "    REG_" + G.col("ADDR_MAP", "bit[15:0]")[i+3+page_word*cyc].split("[")[0].upper() + "[SOCKET]="
                    elif "verify" in list(G.ADDR_MAP[temp_item_flag])[i + page_word * cyc].lower():
                        if uid_write_dic[G.col("ADDR_MAP", "bit[15:0]")[i+3+page_word*cyc]] <= int(code_name.split("_")[-1][-1]):
                            type_flag4 = "    " + G.col("ADDR_MAP", "bit[15:0]")[i+3+page_word*cyc].split("Verify")[
                                0].upper() + "W[SOCKET]="
                else:
                    type_flag4 = "888[15:0]"
                    bit_015_1631_flag4 = 9

            if bit == 256:
                if G.col("ADDR_MAP", "data type")[i+4+page_word*cyc] == "lable":
                    bit_015_1631_flag5 = 0
                    if "verify" not in list(G.ADDR_MAP[temp_item_flag])[i + page_word * cyc].lower():
                        type_flag5 = "    REG_" + G.col("ADDR_MAP", "bit[15:0]")[i+4+page_word*cyc].split("[")[0].upper() + "[SOCKET]="
                    elif "verify" in list(G.ADDR_MAP[temp_item_flag])[i + page_word * cyc].lower():
                        if uid_write_dic[G.col("ADDR_MAP", "bit[15:0]")[i+4+page_word*cyc]] <= int(code_name.split("_")[-1][-1]):
                            type_flag5 = "    " + G.col("ADDR_MAP", "bit[15:0]")[i+4+page_word*cyc].split("Verify")[
                                0].upper() + "W[SOCKET]="
                else:
                    type_flag5 = "888[15:0]"
                    bit_015_1631_flag5 = 9

                if G.col("ADDR_MAP", "data type")[i+5+page_word*cyc] == "lable":
                    bit_015_1631_flag6 = 0
                    if "verify" not in list(G.ADDR_MAP[temp_item_flag])[i + page_word * cyc].lower():
                        type_flag6 = "    REG_" + G.col("ADDR_MAP", "bit[15:0]")[i+5+page_word*cyc].split("[")[0].upper() + "[SOCKET]="
                    elif "verify" in list(G.ADDR_MAP[temp_item_flag])[i + page_word * cyc].lower():
                        if uid_write_dic[G.col("ADDR_MAP", "bit[15:0]")[i+5+page_word*cyc]] <= int(code_name.split("_")[-1][-1]):
                            type_flag6 = "    " + G.col("ADDR_MAP", "bit[15:0]")[i+5+page_word*cyc].split("Verify")[
                                0].upper() + "W[SOCKET]="
                else:
                    type_flag6 = "888[15:0]"
                    bit_015_1631_flag6 = 9

                if G.col("ADDR_MAP", "data type")[i+6+page_word*cyc] == "lable":
                    bit_015_1631_flag7 = 0
                    if "verify" not in list(G.ADDR_MAP[temp_item_flag])[i + page_word * cyc].lower():
                        type_flag7 = "    REG_" + G.col("ADDR_MAP", "bit[15:0]")[i+6+page_word*cyc].split("[")[0].upper() + "[SOCKET]="
                    elif "verify" in list(G.ADDR_MAP[temp_item_flag])[i + page_word * cyc].lower():
                        if uid_write_dic[G.col("ADDR_MAP", "bit[15:0]")[i+6+page_word*cyc]] <= int(code_name.split("_")[-1][-1]):
                            type_flag7 = "    " + G.col("ADDR_MAP", "bit[15:0]")[i+6+page_word*cyc].split("Verify")[
                                0].upper() + "W[SOCKET]="
                else:
                    type_flag7 = "888[15:0]"
                    bit_015_1631_flag7 = 9

                if G.col("ADDR_MAP", "data type")[i+7+page_word*cyc] == "lable":
                    bit_015_1631_flag8 = 0
                    if "verify" not in list(G.ADDR_MAP[temp_item_flag])[i + page_word * cyc].lower():
                        type_flag8 = "    REG_" + G.col("ADDR_MAP", "bit[15:0]")[i+7+page_word*cyc].split("[")[0].upper() + "[SOCKET]="
                    elif "verify" in list(G.ADDR_MAP[temp_item_flag])[i + page_word * cyc].lower():
                        if uid_write_dic[G.col("ADDR_MAP", "bit[15:0]")[i+7+page_word*cyc]] <= int(code_name.split("_")[-1][-1]):
                            type_flag8 = "    " + G.col("ADDR_MAP", "bit[15:0]")[i+7+page_word*cyc].split("Verify")[
                                0].upper() + "W[SOCKET]="
                else:
                    type_flag8 = "888[15:0]"
                    bit_015_1631_flag8 = 9
            if bit == 32:
                groups_type.append((str(bit_015_1631_flag1)+"&"+G.col("ADDR_MAP", "data type")[i+page_word*cyc]+"&"+type_flag1))

            if bit == 64:
                groups_type.append((str(bit_015_1631_flag1)+"&"+G.col("ADDR_MAP", "data type")[i+page_word*cyc]+"&"+type_flag1, str(bit_015_1631_flag2)+"&"+G.col("ADDR_MAP", "data type")[i+1+page_word*cyc]+"&"+type_flag2))

            if bit == 128:
                groups_type.append((str(bit_015_1631_flag1) + "&" + G.col("ADDR_MAP", "data type")[i + page_word * cyc] + "&" + type_flag1,
                                    str(bit_015_1631_flag2) + "&" + G.col("ADDR_MAP", "data type")[i + 1 + page_word * cyc] + "&" + type_flag2,
                                    str(bit_015_1631_flag3) + "&" + G.col("ADDR_MAP", "data type")[i + 2 + page_word * cyc] + "&" + type_flag3,
                                    str(bit_015_1631_flag4) + "&" + G.col("ADDR_MAP", "data type")[i + 3 + page_word * cyc] + "&" + type_flag4
                                    ))

            if bit == 256:
                groups_type.append((str(bit_015_1631_flag1) + "&" + G.col("ADDR_MAP", "data type")[i + page_word * cyc] + "&" + type_flag1,
                                    str(bit_015_1631_flag2) + "&" + G.col("ADDR_MAP", "data type")[i + 1 + page_word * cyc] + "&" + type_flag2,
                                    str(bit_015_1631_flag3) + "&" + G.col("ADDR_MAP", "data type")[i + 2 + page_word * cyc] + "&" + type_flag3,
                                    str(bit_015_1631_flag4) + "&" + G.col("ADDR_MAP", "data type")[i + 3 + page_word * cyc] + "&" + type_flag4,
                                    str(bit_015_1631_flag5) + "&" + G.col("ADDR_MAP", "data type")[i + 4 + page_word * cyc] + "&" + type_flag5,
                                    str(bit_015_1631_flag6) + "&" + G.col("ADDR_MAP", "data type")[i + 5 + page_word * cyc] + "&" + type_flag6,
                                    str(bit_015_1631_flag7) + "&" + G.col("ADDR_MAP", "data type")[i + 6 + page_word * cyc] + "&" + type_flag7,
                                    str(bit_015_1631_flag8) + "&" + G.col("ADDR_MAP", "data type")[i + 7 + page_word * cyc] + "&" + type_flag8
                                    ))

        # print(groups_type)
        label_num_flag = 0
        if bit == 32:
            for i in range(len(groups_type)):
                if groups_type[i].split("&")[1] == "lable" :
                    if groups_type[i].split("&")[2] != "888[15:0]":
                        f.write(groups_type[i].split("&")[2] + addr_map_item[cyc] + "_0x00" + str(
                            G.col("ADDR_MAP", "SM Address")[0 + page_word * cyc].split(";")[0].split("0x")[1])
                                + "[SOCKET][" + str(0 + 2 * label_num_flag) + "]*256+" + addr_map_item[
                                    cyc] + "_0x00"
                                + str(G.col("ADDR_MAP", "SM Address")[0 + page_word * cyc].split(";")[0].split("0x")[
                                          1]) + "[SOCKET][" + str(1 + 2 * label_num_flag) + "];\n")

                        label_num_flag += 1
                elif groups_type[i].split("&")[0] != "lable" :
                    continue

        index_list=[]
        sum_flag = 0
        if bit != 32:
            for i in range(len(groups_type)):
                sum_flag = len(list(filter(lambda x: "lable" in x, groups_type[i]))) - 1
                for j in range(len(groups_type[i])):
                    if groups_type[i][j].split("&")[1] == "lable":
                        index_list.append(str(j)+"&"+str(sum_flag))
                        sum_flag-=1
                for z in range(len(index_list)):
                    f.write(groups_type[i][int(index_list[z].split("&")[0])].split("&")[2] + addr_map_item[cyc] + "_0x00" + str(G.col("ADDR_MAP", "SM Address")[0 + page_word * cyc].split(";")[0].split("0x")[1])
                          + "[SOCKET][" + str(0 + 2 * (label_num_flag+int(index_list[z].split("&")[1]))) + "]*256+" + addr_map_item[cyc] + "_0x00"
                          + str(G.col("ADDR_MAP", "SM Address")[0 + page_word * cyc].split(";")[0].split("0x")[1]) + "[SOCKET][" + str(1 + 2 * (label_num_flag+int(index_list[z].split("&")[1]))) + "];\n")
                label_num_flag += len(index_list)
                index_list.clear()


def sub_flow_write(code_name, f, name, pattern, temp_list,z):
    # //////////////////////////////////////////////Sub Flow 写入start/////////////////////////////////////////////
    serial_number = ["a", "b", "c", "d", "e", "f", "g"]
    sub_item = G.col("PATTERN", "pattern")
    new_sub_item = [sub_item for sub_item in sub_item if sub_item == sub_item]  # 去除nan
    written_patterns = set()
    for j in range(len(name)):
        if G.col("FLOW", "item")[z] == name[j] and code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[
            z]:
            # and "Pdr" not in list(FLOW["item"])[z]
            if G.col("FLOW", "type")[z] == "trim"  and "set" in pattern[j]:
                if pattern[j] in written_patterns:
                    continue
                written_patterns.add(pattern[j])
                for cyc in range(len(G.col("PATTERN", "description"))):
                    if temp_list[cyc] == pattern[j]:
                        copy_file(G.BASE_DIR + "\\pat_temp\\" + pattern[j] + ".pat",
                                  G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")

                        # 复用 fbist_pattern_created() 已经算好的 G.exegesis[cyc]（起始位缺省的行
                        # 已经从 FB MAP 反查补全），不再自己对 description 原始文本重新 split("\n")——
                        # 否则"起始位,"前缀留空时这里的 split(",")[1] 会错位/越界。
                        var_slots = _trim_variable_slots_for_merged_row(cyc)
                        f.write(str(pattern[j].split("dac")[0]) + "trim_data(")
                        for k, (d, _line) in enumerate(var_slots):
                            f.write("int* " + str(serial_number[d]))
                            if k < len(var_slots) - 1:
                                f.write(",")
                        f.write(")\n{\n")
                        f.write("  SOCKET_INC(FRZ_OFF)\n  {\n\n")
                        for d, line in var_slots:
                            dac_bit = str(int(line.split(":")[0].split("[")[-1]) - int(
                                line.split(":")[1].split("]")[0]))
                            f.write("    TRIM_DIGIT = " + str(int(dac_bit) + 1) + "-1;\n")
                            dac_item_name = line.split(",")[1].split("[")[0].split("_T")[
                                0].lower()
                            if len(var_slots) > 1:
                                f.write("    TEMP = " + str(
                                    serial_number[d]) + "[SOCKET]; //" + dac_item_name + "_dac\n\n")
                            else:
                                f.write("    TEMP = " + str(serial_number[d]) + "[SOCKET]; //data\n")
                            f.write("    for(J=0;J<=" + 'TRIM_DIGIT' + ";J++)\n    {\n")
                            f.write("      BIT[J] = 0;\n      BIT[J] = TEMP%2;\n      TEMP = TEMP/2;\n    }\n\n")
                            f.write("    for(J=" + 'TRIM_DIGIT' + ";J>=0;J--)\n    {\n")
                            f.write("      if(BIT[J]==0)\n      {\n         WRITE_PAT_MEM(SOCKET, " + str(
                                G.col("VERSION", "SWD PIN")[G.i]) + ", " + pattern[j] + ":" + serial_number[
                                        d] + "_data+" + 'TRIM_DIGIT' + '-J, ,"0");\n      }\n')
                            f.write("      else\n      {\n         WRITE_PAT_MEM(SOCKET, " + str(
                                G.col("VERSION", "SWD PIN")[G.i]) + ", " + pattern[j] + ":" + serial_number[
                                        d] + "_data+" + 'TRIM_DIGIT' + '-J, ,"1");\n      }\n    }\n\n')
                        f.write(" }\n\n")
                f.write(
                    ' TEST_NUM++;\n TEST_NO(TEST_NUM);  DATALOG_MSG ="' + pattern[j] + '";\n JUDGE_PAT(' +
                    pattern[j] + ",__" + pattern[j] + ");\n\n}\n\n\n")


def dynamic_enter_helpers_write(
        code_name, f, trim_specs, current_cp, temp_list, recipe_rows=None,
        dac_write_plans=None):
    """Emit parameterized ENTER pattern-memory setters before test bodies."""
    serial_number = ["a", "b", "c", "d", "e", "f", "g"]
    operations = list(dynamic_enter_operations(trim_specs, current_cp))
    operations.extend(dynamic_recipe_enter_operations(recipe_rows or {}, current_cp))
    selected = {}
    for operation in operations:
        selected.setdefault(operation.reference, operation)
    for operation in selected.values():
        slots = []
        for row, pattern_name in enumerate(temp_list):
            if pattern_name == operation.reference:
                slots = _trim_variable_slots_for_merged_row(row)
                if slots:
                    break
        if len(slots) != 1:
            raise ValueError(
                f"dynamic ENTER pattern {operation.reference!r} needs exactly one writable field"
            )
        slot, _line = slots[0]
        label = serial_number[slot] + "_data"
        helper = "set_" + operation.reference + "_data"
        f.write(helper + "(int data)\n{\n")
        f.write("  SOCKET_INC(FRZ_OFF)\n  {\n")
        f.write("    TEMP = data;\n")
        f.write("    TRIM_DIGIT = " + str(operation.field_width - 1) + ";\n")
        f.write("    for(J=0;J<=TRIM_DIGIT;J++)\n    {\n")
        f.write("      BIT[J] = TEMP%2;\n      TEMP = TEMP/2;\n    }\n")
        f.write("    for(J=TRIM_DIGIT;J>=0;J--)\n    {\n")
        f.write("      if(BIT[J]==0)\n      {\n")
        f.write("        WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) +
                ", " + operation.reference + ":" + label + "+TRIM_DIGIT-J, ,\"0\");\n")
        f.write("      }\n      else\n      {\n")
        f.write("        WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) +
                ", " + operation.reference + ":" + label + "+TRIM_DIGIT-J, ,\"1\");\n")
        f.write("      }\n    }\n  }\n}\n\n\n")

    for operation in (dac_write_plans.helper_plans if dac_write_plans else ()):
        slots = []
        for row, pattern_name in enumerate(temp_list):
            if pattern_name == operation.pattern_name:
                slots = _trim_variable_slots_for_merged_row(row)
                if slots:
                    break
        if len(slots) != 1:
            raise ValueError(
                f"DAC_WRITE pattern {operation.pattern_name!r} needs exactly one writable field"
            )
        copy_file(G.BASE_DIR + "\\pat_temp\\" + operation.pattern_name + ".pat",
                  G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
        slot, _line = slots[0]
        label = serial_number[slot] + "_data"
        helper = operation.helper_name
        f.write(helper + "(int* a)\n{\n")
        f.write("  SOCKET_INC(FRZ_OFF)\n  {\n")
        f.write("    TEMP = a[SOCKET];\n")
        f.write("    TRIM_DIGIT = " + str(operation.field_width - 1) + ";\n")
        f.write("    for(J=0;J<=TRIM_DIGIT;J++)\n    {\n")
        f.write("      BIT[J] = TEMP%2;\n      TEMP = TEMP/2;\n    }\n")
        f.write("    for(J=TRIM_DIGIT;J>=0;J--)\n    {\n")
        f.write("      if(BIT[J]==0)\n      {\n")
        f.write("        WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) +
                ", " + operation.pattern_name + ":" + label + "+TRIM_DIGIT-J, ,\"0\");\n")
        f.write("      }\n      else\n      {\n")
        f.write("        WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) +
                ", " + operation.pattern_name + ":" + label + "+TRIM_DIGIT-J, ,\"1\");\n")
        f.write("      }\n    }\n  }\n\n")
        f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + operation.pattern_name +
                '";\n  JUDGE_PAT(' + operation.pattern_name + ',__' + operation.pattern_name +
                ');\n}\n\n\n')


def trim_item_write(
        code_name, f, name, pattern, z, bisection, temp_list, trim_spec=None,
        dedicated_trim_plan=None):
    # //////////////////////////////////////////////trim 写入start/////////////////////////////////////////////
    G.trash.clear()

    recipe_test_index = None
    spec_enter_operations = []
    spec_setup_operations = []
    spec_enter_patterns = []
    spec_trim_force_wait = None
    spec_trim_set_wait = None
    spec_adjust_force_wait = None
    spec_adjust_set_wait = None
    spec_judge_force_wait = None
    spec_judge_set_wait = None
    spec_adjust_operation = None
    spec_judge_operation = None
    if trim_spec is not None:
        spec_enter_operations = [
            operation
            for operation in trim_spec.operations
            if operation.kind == "ENTER"
        ]
        spec_setup_operations = [
            operation for operation in trim_spec.operations
            if operation.kind in ("ENTER", "RUN")
        ]
        spec_enter_patterns = [operation.reference for operation in spec_enter_operations]
        spec_trim_operation = next(
            operation for operation in trim_spec.operations
            if operation.kind == "TRIM"
        )
        spec_adjust_operation = next(
            (operation for operation in trim_spec.operations
             if operation.kind == "DAC_ADJ"),
            None,
        )
        spec_judge_operation = next(
            operation for operation in trim_spec.operations
            if operation.kind == "JUDGE"
        )
        spec_trim_force_wait = spec_trim_operation.force_wait
        spec_trim_set_wait = spec_trim_operation.set_wait
        if spec_adjust_operation is not None:
            spec_adjust_force_wait = spec_adjust_operation.force_wait
            spec_adjust_set_wait = spec_adjust_operation.set_wait
        spec_judge_force_wait = spec_judge_operation.force_wait
        spec_judge_set_wait = spec_judge_operation.set_wait
        spec_trim_pattern = spec_trim_operation.reference
        recipe_test_index = next(
            (index for index, value in enumerate(pattern)
             if value == spec_enter_patterns[0] and name[index] == trim_spec.item),
            z,
        )
        synthetic_item = trim_spec.item
        if not synthetic_item.lower().endswith("trim"):
            synthetic_item += "_Trim"
        name = [synthetic_item, synthetic_item] + list(name)
        pattern = [spec_enter_patterns[0], spec_trim_pattern] + list(pattern)

    for j in range(len(name)):
        if name[j] not in G.trash:
            spec_target = trim_spec is not None and j == 0
            dedicated_target = (
                dedicated_trim_plan is not None
                and dedicated_trim_plan.flow_row_index == z
                and dedicated_trim_plan.item == name[j]
            )
            if (spec_target or dedicated_target) and code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[z]:
                test_number = ((recipe_test_index if recipe_test_index is not None else j) + 1) * 50
                # print(G.col("FLOW", "item")[z])
                relay = flow_relay(z)  # 非 "/" 时上下电前后各包一层 SET_CBIT
                for cyc in range(len(G.col("PATTERN", "description"))):
                    if temp_list[cyc] == pattern[j + 1] and pattern[j + 1].startswith("set_"):
                        # 同上：复用已含 FB MAP 起始位补全的 G.exegesis[cyc]，不重新解析原始文本。
                        candidate_slots = _trim_variable_slots_for_merged_row(cyc)
                        if candidate_slots:
                            var_slots = candidate_slots

                if spec_target:
                    enter_patterns = spec_enter_patterns if spec_target else [pattern[j]]
                    trim_set_wait = spec_trim_set_wait if spec_target else None
                    adjust_set_wait = spec_adjust_set_wait if spec_target else None
                    judge_set_wait = spec_judge_set_wait if spec_target else None
                    for enter_pattern in dict.fromkeys(enter_patterns):
                        copy_file(G.BASE_DIR + "\\pat_temp\\" + enter_pattern + ".pat",
                                  G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")

                    if bisection == "no":
                        f.write(name[j].split("Trim")[0].title() + "Dac_Loop()\n{\n")
                        f.write("  TEST_NUM=" + str(
                            test_number) + ";\n" + '  TEST_NO(TEST_NUM);DATALOG_MSG="' + name[j].split("Trim")[
                                    0].lower() + 'dac_loop"; \n\n')
                    else:
                        f.write(name[j].title() + "()\n{\n")
                        f.write("  TEST_NUM=" + str(
                            test_number) + ";\n" + '  TEST_NO(TEST_NUM);DATALOG_MSG="' + name[
                                    j].lower() + '"; \n\n')
                    if name[j].split("_")[0].lower() in list(G.VERSION.columns):
                        f.write("  double trimTar=" + name[j].split("_")[0].upper() + '_TAR;\n\n')
                    else:
                        f.write("  double trimTar=" + str(G.col("FLOW", "target")[z]) + ';\n\n')
                    f.write(
                        "  double trimValue[MAX_SITE],trimFinalValue[MAX_SITE];\n  int trimDac[MAX_SITE];\n\n")
                    if spec_target and trim_spec.adjust is not None:
                        dac_adj = {
                            "cond": (trim_spec.adjust.operator, trim_spec.adjust.threshold),
                            "delta": trim_spec.adjust.delta,
                        }
                    else:
                        dac_adj = _dac_adj_spec(z)
                    search_codes = trim_spec.search.codes if spec_target else None
                    if dac_adj is not None and dac_adj["cond"] is not None:
                        # tempValue 只在"有条件"加档时才需要（存收敛后重测的值供条件判断，
                        # 无条件加档不用比较，不声明这个变量），同 temp_swd_cp3.pln 示例。
                        f.write("  double tempValue[MAX_SITE];\n\n")
                    if spec_target:
                        dac_values = ",".join(str(code) for code in search_codes)
                        f.write("  int dacArray[" + str(len(search_codes)) + "]={" +
                                dac_values + "};\n")
                        if bisection == "no":
                            f.write("  int cyc=0;\n  int endCyc=" + str(len(search_codes)) +
                                    ";\n  char cycMsg[48];\n\n")
                        else:
                            f.write(
                                "  int dacIndex[MAX_SITE];\n  int firstIndex=sizeof(dacArray)/sizeof(dacArray[0])/2;\n  int binAryCyc=" +
                                str(trim_spec.search.search_bits - 2) + ";\n\n")
                    elif bisection == "no":
                        f.write("  int cyc=0;\n  int endCyc=" + str(
                            pow(2, G.col("FLOW", "DAC bit")[z])) + ";\n  char cycMsg[48];\n\n")
                    elif G.col("FLOW", "LINE")[z] == "yes":
                        f.write(
                            "  int dacArray[" + str(pow(2, G.col("FLOW", "DAC bit")[z])) + "]={0};\n")
                        f.write("  for(I=0;I<" + str(
                            pow(2, G.col("FLOW", "DAC bit")[z])) + ";I++)\n  {\n    dacArray[I]=I;\n  }\n\n")
                        f.write(
                            "  int dacIndex[MAX_SITE];\n  int firstIndex=sizeof(dacArray)/sizeof(dacArray[0])/2;\n  int binAryCyc=(int)log2((double)(sizeof(dacArray)/sizeof(dacArray[0])+1))-2;\n\n")
                    else:
                        f.write("  int dacArray[" + str(
                            pow(2, G.col("FLOW", "DAC bit")[z])) + "]={" +
                            _expand_dac_array(G.col("FLOW", "step")[z]) + "};\n\n")
                        f.write(
                            "  int dacIndex[MAX_SITE];\n  int firstIndex=sizeof(dacArray)/sizeof(dacArray[0])/2;\n  int binAryCyc=(int)log2((double)(sizeof(dacArray)/sizeof(dacArray[0])+1))-2;\n\n")
                    if dac_adj is not None and bisection == "yes":
                        # 记下"历史最优"对应的 dacArray 下标（同 DAC_FINAL 一起在收敛过程中
                        # 更新），供收敛后加档直接用——不能用循环末尾的 dacIndex：循环最后一步
                        # 算出的 dacIndex 是"下一轮该探的点"，从没被真正测量过，跟 DAC_FINAL
                        # 实际对应的下标不是同一个（用户核实的点）。
                        f.write("  int dacFinalIndex[MAX_SITE];\n\n")
                    f.write(
                        "  //initial\n  for(I=0;I<MAX_SITE;I++)\n  {\n    trimValue[I]=0;\n    trimFinalValue[I]=0;\n")
                    if bisection == "no":
                        initial_dac = "dacArray[0]" if spec_target else "0"
                        f.write("\n    trimDac[I]=" + initial_dac + ";\n\n  } \n\n")
                    else:
                        f.write(
                            "\n    trimDac[I]=dacArray[firstIndex];\n    dacIndex[I]=firstIndex;\n")
                        if dac_adj is not None:
                            f.write("    dacFinalIndex[I]=firstIndex;\n")
                        f.write("\n  } \n\n")
                    if relay != "/":
                        f.write("  SET_CBIT(" + relay + ", ON, 5mS);\n")
                    f.write("  POWER_ON(" + G.col("FLOW", "Vcc")[z].upper() + ");\n\n")
                    if G.col("FLOW", "UNIT")[z] != "KHz":
                        # 2026-07-12：负电压曾在此跳过 PPMU relay 为切 PMU 写法让路，
                        # 现改回统一走 PPMU，不再按 target 正负跳过。
                        f.write("  RELAY_ON(" + G.col("FLOW", "meas pin")[z] + ",PPMU_PDCL,2mS);\n\n")

                    f.write(
                        '  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="enter_fbist_mode";\n  JUDGE_PAT(enter_fbist_mode,__enter_fbist_mode); \n\n')
                    setup_operations = spec_setup_operations if spec_target else []
                    if spec_target:
                        setup_patterns = [operation.reference for operation in setup_operations]
                        for run_pattern in dict.fromkeys(
                            operation.reference for operation in setup_operations
                            if operation.kind == "RUN"
                        ):
                            copy_file(G.BASE_DIR + "\\pat_temp\\" + run_pattern + ".pat",
                                      G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                    else:
                        setup_patterns = enter_patterns
                    for enter_index, enter_pattern in enumerate(setup_patterns):
                        enter_operation = setup_operations[enter_index] if setup_operations else None
                        enter_wait = enter_operation.wait if enter_operation else None
                        if (enter_operation is not None and enter_operation.kind == "ENTER"
                                and enter_operation.value_source == "ARGUMENT"):
                            f.write("  set_" + enter_pattern + "_data(" +
                                    str(int(enter_operation.value, 2)) + ");\n")
                        if enter_wait is None:
                            f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + enter_pattern +
                                    '";\n  JUDGE_PAT(' + enter_pattern + ',__' + enter_pattern + '); \n\n')
                        else:
                            f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + enter_pattern +
                                    '";\n  JUDGE_PAT(' + enter_pattern + ',__' + enter_pattern + '); \n')
                            _write_recipe_wait(f, enter_wait, "  ")
                            f.write("\n")
                        if (enter_operation is not None and enter_operation.kind == "ENTER"
                                and enter_operation.value_source == "ARGUMENT"):
                            f.write("  set_" + enter_pattern + "_data(" +
                                    str(int(enter_operation.default_value, 2)) + ");\n\n")
                    if spec_target:
                        dependency_patterns = [
                            operation.reference
                            for operation in trim_spec.operations
                            if operation.kind == "DEPEND"
                        ]
                        for dependency_pattern in dependency_patterns:
                            copy_file(G.BASE_DIR + "\\pat_temp\\" + dependency_pattern + ".pat",
                                      G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                            f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' +
                                    dependency_pattern + '";\n  JUDGE_PAT(' + dependency_pattern +
                                    ',__' + dependency_pattern + '); \n\n')
                    else:
                        for vref_cyc in range(len(G.col("FLOW", "item"))):
                            if G.ws["B"][vref_cyc + 1].fill.fgColor.rgb == "FFFFFF00":
                                if G.col("FLOW", "item")[vref_cyc] not in G.vref:
                                    G.vref.append(G.col("FLOW", "item")[vref_cyc])
                        index = 0
                        if code_name[G.i].split("_")[-1] == "CP1":
                            if len(G.vref) != 0:
                                for vref_num in G.vref:
                                    index = name.index(vref_num)
                                    if G.col("FLOW", "item")[z] != vref_num:
                                        f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + pattern[
                                            index + 1] + '";\n  JUDGE_PAT(' + pattern[index + 1] + ',__' + pattern[
                                                    index + 1] + '); \n\n')
                    if code_name[G.i].split("_")[-1] != "CP1":
                        f.write(
                            '  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="set_all_final_vposp";\n  JUDGE_PAT(set_all_final_vposp,__set_all_final_vposp); \n\n')
                    trim_force_wait = spec_trim_force_wait if spec_target else None
                    if "Hz" in G.col("FLOW", "UNIT")[z]:
                        Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                    G.col("FLOW", "target")[z], 0, "FORCE", "FREQ", G.col("FLOW", "low_range(%)")[z],
                                    G.col("FLOW", "high_range(%)")[z], f, force_wait=trim_force_wait)
                    else:
                        # 2026-07-12：负电压曾在此跳过 PPMU FORCE 为切 PMU 写法让路，
                        # 现改回统一走 PPMU，不再按 target 正负跳过。
                        Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                    G.col("FLOW", "target")[z], 0, "FORCE", "PPMU", G.col("FLOW", "low_range(%)")[z],
                                    G.col("FLOW", "high_range(%)")[z], f, force_wait=trim_force_wait)

                    if spec_target:
                        reuse_patterns = []
                    else:
                        reuse_pat = reuse_dac_pattern(name[j])
                        reuse_patterns = [reuse_pat] if reuse_pat else []
                    for reuse_pat in reuse_patterns:
                        copy_file(G.BASE_DIR + "\\pat_temp\\" + reuse_pat + ".pat",
                                  G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                        f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + reuse_pat + '";\n  JUDGE_PAT(' +
                                reuse_pat + ',__' + reuse_pat + '); \n\n')

                    f.write('  do\n  {\n')
                    if bisection == "no":
                        f.write('    sprintf(cycMsg,"' + name[j].split("ming")[
                            0].lower() + '_dac_%d",cyc);\n    cyc++; \n')

                    if len(var_slots) > 1:
                        f.write('    ' + str(pattern[j + 1].split("dac")[0]) + "trim_data(")
                        for k, (d, line) in enumerate(var_slots):
                            dac_item_name = line.split(",")[1].split("[")[0]
                            if dac_item_name != name[j]:
                                f.write(dac_item_name.split("Trim")[0].upper() + "DAC_FINAL")
                            elif dac_item_name == name[j]:
                                f.write("trimDac")
                            if k < len(var_slots) - 1:
                                f.write(",")
                        f.write(");\n\n")
                    else:
                        f.write('    ' + str(pattern[j + 1].split("dac")[0]) + "trim_data(trimDac);\n\n")

                    if trim_set_wait is not None:
                        _write_recipe_wait(f, trim_set_wait, "    ")
                        f.write("\n")

                    if str(G.col("FLOW", "PE")[z]).upper() == "ERASE":

                        for nm_name in G.nm_patterns("page erase 1st"):
                            copy_file(G.BASE_DIR + "\\pat_temp\\" +
                                      nm_name + ".pat",
                                      G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                            f.write('    TEST_NO(TEST_NUM);  DATALOG_MSG = "' +
                                    nm_name + '";  \n    JUDGE_PAT(' +
                                    nm_name + ',' +
                                    nm_name + ':pe_1);\n\n')
                    if str(G.col("FLOW", "PE")[z]).upper() == "PROGRAM":

                        for nm_name in G.nm_patterns("page program PCKB 1st"):
                            copy_file(G.BASE_DIR + "\\pat_temp\\" +
                                      nm_name + ".pat",
                                      G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                            f.write('    TEST_NO(TEST_NUM);  DATALOG_MSG = "' +
                                    nm_name + '";  \n    JUDGE_PAT(' +
                                    nm_name + ',' +
                                    nm_name + ':pe_1);\n\n')
                    if "Hz" in G.col("FLOW", "UNIT")[z]:
                        Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                    G.col("FLOW", "target")[z], 2, "MEAS", "FREQ", G.col("FLOW", "low_range(%)")[z],
                                    G.col("FLOW", "high_range(%)")[z], f)
                    elif int(G.col("FLOW", "target")[z]) < 0 and "V" in G.col("FLOW", "UNIT")[z]:
                        # PMU 写法（用户 2026-07-12 认为有问题，屏蔽保留供参考，改走 PPMU）
                        f.write("    //PARAL_INC(" + G.col("FLOW", "meas pin")[
                            z] + ")\n    //{\n      //RELAY_OFF(PIN_DEFS,PDCL,2mS);\n      //RELAY_ON(PIN_DEFS,PMU,2mS);\n\n")
                        f.write(
                            "      //FORCE_I_PMU(PMU,0uA,@100uA,@12V,6V,ON,3mS);\n      //MEAS_V_PMU(PMU,IFVM,2mS,16,AVE,50uS);\n"
                            "      //FORCE_I_PMU(PMU,0uA,@100uA,@12V,6V,OFF,3mS);\n\n")
                        f.write("      //RELAY_OFF(PIN_DEFS,PMU,2mS);\n      //RELAY_ON(PIN_DEFS,PDCL,2mS);\n"
                                "    //}\n\n")
                        f.write("    MEAS_V_PPMU(" + G.col("FLOW", "meas pin")[z] + ", 2mS, 16, AVE, 50uS);\n\n")
                    else:
                        Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                    G.col("FLOW", "target")[z], 2, "MEAS", "PPMU", G.col("FLOW", "low_range(%)")[z],
                                    G.col("FLOW", "high_range(%)")[z], f)
                    if str(G.col("FLOW", "PE")[z]).upper() == "ERASE":
                        for nm_name in G.nm_patterns("page erase 1st"):
                            f.write('    TEST_NO(TEST_NUM);  DATALOG_MSG = "' +
                                    nm_name + '";  \n    JUDGE_PAT(' +
                                    nm_name + ':pe_1,__' +
                                    nm_name + ');\n\n')
                    if str(G.col("FLOW", "PE")[z]).upper() == "PROGRAM":
                        for nm_name in G.nm_patterns("page program PCKB 1st"):
                            f.write('    TEST_NO(TEST_NUM);  DATALOG_MSG = "' +
                                    nm_name + '";  \n    JUDGE_PAT(' +
                                    nm_name + ':pe_1,__' +
                                    nm_name + ');\n\n')
                    f.write('    TEST_NUM++;\n    TEST_NO(TEST_NUM);DATALOG_MSG="' + name[j].split("ming")[
                        0].lower() + '";\n')
                    f.write('    SOCKET_INC(FRZ_OFF)\n    {\n')

                    if "A" in G.col("FLOW", "UNIT")[z]:
                        f.write(
                            "      trimValue[SOCKET] = RESULT_PIN(SOCKET, " + G.col("FLOW", "meas pin")[
                                z] + ")*1000000; //uA\n")
                    elif "Hz" in G.col("FLOW", "UNIT")[z]:
                        f.write(
                            "      trimValue[SOCKET] = RESULT_PIN(SOCKET, " + G.col("FLOW", "meas pin")[
                                z] + ")/1000; //Khz\n")
                    else:
                        f.write(
                            "      trimValue[SOCKET] = RESULT_PIN(SOCKET, " + G.col("FLOW", "meas pin")[
                                z] + ");\n")

                    if bisection == "no":
                        f.write('      JUDGE_VARIABLE(SOCKET,trimValue[SOCKET], ' + str(
                            round(G.col("FLOW", "target")[z] - (abs(G.col("FLOW", "target")[z] * 2)),
                                  2)) + ', ' + str(
                            round(G.col("FLOW", "target")[z] + (abs(G.col("FLOW", "target")[z] * 5)),
                                  2)) + ', cycMsg);\n\n')
                    else:
                        f.write('      JUDGE_VARIABLE(SOCKET,trimDac[SOCKET], ' + '0, ' + str(
                            pow(2, G.col("FLOW", "DAC bit")[z]) - 1) + ', "' + name[j].split("Trim")[
                                    0] + 'dac");\n')
                        f.write('      JUDGE_VARIABLE(SOCKET,trimValue[SOCKET], ' + str(
                            round(G.col("FLOW", "target")[z] - (abs(G.col("FLOW", "target")[z] * 2)),
                                  2)) + ', ' + str(
                            round(G.col("FLOW", "target")[z] + (abs(G.col("FLOW", "target")[z] * 5)),
                                  2)) + ', "' + name[j].split("Trim")[0] + 'value");\n\n')
                    f.write(
                        '      if(fabs(trimValue[SOCKET]-trimTar)<fabs(trimFinalValue[SOCKET]-trimTar))\n      {\n        trimFinalValue[SOCKET] = trimValue[SOCKET];\n        ' +
                        name[j].split("Trim")[
                            0].upper() + 'DAC_FINAL[SOCKET] = trimDac[SOCKET];\n' +
                        ("        dacFinalIndex[SOCKET] = dacIndex[SOCKET];\n"
                         if dac_adj is not None and bisection == "yes" else "") +
                        '      }\n\n')
                    if bisection == "yes":
                        f.write(
                            "      if (trimValue[SOCKET] < trimTar)\n      {\n        dacIndex[SOCKET] = dacIndex[SOCKET] + (int)pow((float)2, (float)binAryCyc);\n        trimDac[SOCKET] = dacArray[dacIndex[SOCKET]];\n      }\n\n")
                        f.write(
                            "      else\n      {\n        dacIndex[SOCKET] = dacIndex[SOCKET] - (int)pow((float)2, (float)binAryCyc);\n        trimDac[SOCKET] = dacArray[dacIndex[SOCKET]];\n      }\n\n")
                    else:
                        if spec_target:
                            f.write("      if(cyc<endCyc) trimDac[SOCKET] = dacArray[cyc];\n")
                        else:
                            f.write("      trimDac[SOCKET] = cyc;\n")

                    f.write('    }\n\n')  # socket_inc{}
                    if bisection == "yes":
                        f.write('    binAryCyc-=1;\n\n')
                    if bisection == "yes":
                        f.write('  }while(binAryCyc>=-1);  \n')  # do while{}
                    else:
                        f.write('  }while(cyc<endCyc);   \n')  # do while{}
                    f.write('  //fflush(stdout);\n\n')
                    # if bisection == "yes":
                    if len(var_slots) > 1:
                        _trim_data_args = []
                        for d, line in var_slots:
                            dac_item_name = line.split(",")[1].split("[")[0]
                            _trim_data_args.append(dac_item_name.split("Trim")[0].upper() + "DAC_FINAL")
                        _trim_data_call = '  ' + str(pattern[j + 1].split("dac")[0]) + "trim_data(" + \
                            ",".join(_trim_data_args) + ");\n\n"
                    else:
                        _trim_data_call = '  ' + str(pattern[j + 1].split("dac")[0]) + "trim_data(" + \
                            name[j].split("Trim")[0].upper() + "DAC_FINAL);\n\n"
                    f.write(_trim_data_call)
                    final_raw_set_wait = adjust_set_wait if dac_adj is not None else judge_set_wait
                    if final_raw_set_wait is not None:
                        _write_recipe_wait(f, final_raw_set_wait, "  ")
                        f.write("\n")

                    if str(G.col("FLOW", "PE")[z]).upper() == "ERASE":
                        for nm_name in G.nm_patterns("page erase 1st"):
                            f.write('  TEST_NO(TEST_NUM);  DATALOG_MSG = "' +
                                    nm_name + '";  \n  JUDGE_PAT(' +
                                    nm_name + ',' +
                                    nm_name + ':pe_1);\n\n')
                    if str(G.col("FLOW", "PE")[z]).upper() == "PROGRAM":
                        for nm_name in G.nm_patterns("page program PCKB 1st"):
                            f.write('  TEST_NO(TEST_NUM);  DATALOG_MSG = "' +
                                    nm_name + '";  \n  JUDGE_PAT(' +
                                    nm_name + ',' +
                                    nm_name + ':pe_1);\n\n')
                    f.write(
                        '  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + name[j].lower() + '";\n\n')
                    dac_final_name = name[j].split("Trim")[0].upper() + "DAC_FINAL"
                    if dac_adj is not None:
                        # 收敛后手动加减档（用户裁决，见 temp/temp_swd_cp3.pln 示例）：重测一次，
                        # 有条件/无条件给 DAC_FINAL 加减档，再重新灌回芯片，最后才走电性判定。
                        Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z],
                                    G.col("FLOW", "FV/FI")[z], G.col("FLOW", "target")[z], 0,
                                    "FORCE", "FREQ" if "Hz" in G.col("FLOW", "UNIT")[z] else "PPMU",
                                    G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z],
                                    f, force_wait=spec_adjust_force_wait if spec_target else None)
                        f.write("  MEAS_V_PPMU(" + G.col("FLOW", "meas pin")[z] + ", 2mS, 16, AVE, 50uS);\n\n")
                    f.write('  SOCKET_INC(FRZ_OFF)\n  {\n')
                    if dac_adj is not None and dac_adj["cond"] is not None:
                        cmp_op, threshold = dac_adj["cond"]
                        f.write("    tempValue[SOCKET] = RESULT_PIN(SOCKET, " + G.col("FLOW", "meas pin")[
                            z] + ");\n")
                        f.write("    if(tempValue[SOCKET]" + cmp_op + str(threshold) + ")\n    {\n" +
                                _dac_adj_apply(dac_final_name, dac_adj["delta"], bisection,
                                               G.col("FLOW", "DAC bit")[z]) + "    }\n\n")
                    elif dac_adj is not None:
                        f.write(_dac_adj_apply(dac_final_name, dac_adj["delta"], bisection,
                                                G.col("FLOW", "DAC bit")[z]) + "\n")
                    f.write('    JUDGE_VARIABLE(SOCKET,' +
                            dac_final_name + '[SOCKET],0, ' + str(
                        pow(2, G.col("FLOW", "DAC bit")[z]) - 1) + ', "' + name[j].split("Trim")[
                                0] + 'dac_f");\n  }\n\n')
                    if dac_adj is not None:
                        f.write(_trim_data_call)
                        if judge_set_wait is not None:
                            _write_recipe_wait(f, judge_set_wait, "  ")
                            f.write("\n")

                    Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z],
                                G.col("FLOW", "FV/FI")[z], G.col("FLOW", "target")[z], 0,
                                "FORCE", "FREQ" if "Hz" in G.col("FLOW", "UNIT")[z] else "PPMU",
                                G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z],
                                f, force_wait=spec_judge_force_wait if spec_target else None)

                    # 不考虑 UID（参考 S100：trim_item_write 对 UID 列零引用、不分 UID=yes/no）。
                    # 原 UID=yes 的 value_Final 复测已去除——频率/电压复测交给独立的 *_Verify 项；
                    # 所有 trim 项统一走 JUDGE_FREQ / JUDGE_PPMU（与 Hsi_10M 等 UID=no 项一致）。
                    f.write('  DATALOG_MSG="' + name[j].split("Trim")[0] + 'value_f";\n')

                    if name[j].split("_")[0].lower() in list(G.VERSION.columns):
                        if G.col("FLOW", "target")[z] < -2 and "V" in G.col("FLOW", "UNIT")[z]:
                            f.write(
                                "  SOCKET_INC(FRZ_OFF)\n  {\n    trimValue[SOCKET] = RESULT_PIN(SOCKET, " +
                                G.col("FLOW", "meas pin")[z] + ");\n" +
                                '    JUDGE_VARIABLE(SOCKET,trimValue[SOCKET], ' + name[j].split("_")[
                                    0].upper() + '_TAR-0.05,' + name[j].split("_")[0].upper() + '_TAR+0.05,"' +
                                name[j].split("Trim")[0] + 'value_f");\n  }\n\n')
                        else:
                            if G.col("FLOW", "target")[z] < 0 and "V" in G.col("FLOW", "UNIT")[z]:
                                f.write("  RELAY_ON(" + G.col("FLOW", "meas pin")[z] + ", PPMU_PDCL, 2mS);\n")
                                Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                            G.col("FLOW", "target")[z], 0, "FORCE", "PPMU", G.col("FLOW", "low_range(%)")[z],
                                            G.col("FLOW", "high_range(%)")[z], f)
                            f.write("  JUDGE_V_PPMU(" + G.col("FLOW", "meas pin")[z] + "," +
                                    name[j].split("_")[0].upper() + '_TAR-0.05,' +
                                    name[j].split("_")[0].upper() + '_TAR+0.05' + ',2mS);\n\n')
                    else:

                        if "Hz" in G.col("FLOW", "UNIT")[z]:
                            Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                        G.col("FLOW", "target")[z], 0, "JUDGE", "FREQ", G.col("FLOW", "low_range(%)")[z],
                                        G.col("FLOW", "high_range(%)")[z], f)
                        else:
                            Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                        G.col("FLOW", "target")[z], 0, "JUDGE", "PPMU", G.col("FLOW", "low_range(%)")[z],
                                        G.col("FLOW", "high_range(%)")[z], f)

                    if str(G.col("FLOW", "PE")[z]).upper() == "ERASE":
                        for nm_name in G.nm_patterns("page erase 1st"):
                            f.write('  TEST_NO(TEST_NUM);  DATALOG_MSG = "' +
                                    nm_name + '";  \n  JUDGE_PAT(' +
                                    nm_name + ':pe_1,__' +
                                    nm_name + ');\n\n')
                    if str(G.col("FLOW", "PE")[z]).upper() == "PROGRAM":
                        for nm_name in G.nm_patterns("page program PCKB 1st"):
                            f.write('  TEST_NO(TEST_NUM);  DATALOG_MSG = "' +
                                    nm_name + '";  \n  JUDGE_PAT(' +
                                    nm_name + ':pe_1,__' +
                                    nm_name + ');\n\n')
                    f.write(
                        '  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="exit_fbist_mode";\n  JUDGE_PAT(exit_fbist_mode,__exit_fbist_mode);  \n\n')
                    if "Hz" in G.col("FLOW", "UNIT")[z]:
                        f.write("  SET_TFTM_MODE(" + G.col("FLOW", "meas pin")[z] + ", SCHMITT_OFF);\n\n")
                    else:
                        Force_Judge("uA", G.col("FLOW", "meas pin")[z], "0V", G.col("FLOW", "target")[z], 0, "FORCE", "PPMU",
                                    G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z], f)
                        Force_Judge("V", G.col("FLOW", "meas pin")[z], "0uA", G.col("FLOW", "target")[z], 0, "FORCE", "PPMU",
                                    G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z], f)
                    if "Hz" not in G.col("FLOW", "UNIT")[z]:
                        f.write("  RELAY_OFF(" + G.col("FLOW", "meas pin")[z] + ", PPMU_PDCL, 2mS);\n")

                    f.write('  POWER_OFF();\n  //POWER_DOWN_FAIL_SITE_X(MODE_B);\n\n')
                    if relay != "/":
                        f.write("  SET_CBIT(" + relay + ", OFF, 5mS);\n")
                    f.write("}\n\n")
                elif dedicated_target:
                    copy_file(G.BASE_DIR + "\\pat_temp\\" + pattern[j] + ".pat",
                              G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")

                    copy_file(G.BASE_DIR + "\\pat_temp\\read_status_mode.pat",
                              G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                    f.write(name[j].title() + "()\n{\n")
                    f.write("  TEST_NUM=" + str(
                        test_number) + ";\n" + '  TEST_NO(TEST_NUM);DATALOG_MSG="' + name[
                                j].lower() + '"; \n\n')
                    f.write('  int trimDac[MAX_SITE],pdrPassflag[MAX_SITE];\n\n')
                    f.write('  int dacArray[16]={8,9,10,11,12,13,14,15,0,1,2,3,4,5,6,7}; \n\n')
                    f.write('  int cyc=0;\n')
                    f.write('  int endCyc='+str(G.col("FLOW", "DAC bit")[z])+";\n")
                    f.write('  char cycMsg[48];\n\n')

                    f.write('  //initial\n'+'  for(I=0;I<MAX_SITE;I++)\n'+'  {\n'+'    trimDac[I]=8;\n'+'    pdrPassflag[I]=0;\n'+'  }\n\n')

                    if relay != "/":
                        f.write("  SET_CBIT(" + relay + ", ON, 5mS);\n")
                    f.write("  POWER_ON(" + G.col("FLOW", "Vcc")[z].upper() + ");\n\n")

                    f.write(
                        '  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="enter_fbist_mode";\n  JUDGE_PAT(enter_fbist_mode,__enter_fbist_mode);  \n\n')

                    f.write(
                        '  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="set_all_final_vposp";\n  JUDGE_PAT(set_all_final_vposp,__set_all_final_vposp);  \n\n')

                    f.write("  set_pdr_trim_data(trimDac);\n\n")

                    f.write("  LEVELS(PDR_TAR_LVL, 3mS);\n")
                    f.write("  FORCE_V_MLDPS(" + vcc_rails_str(code_name[G.i]) + ", VCC_PDR_TAR,@6V,@500mA,200mA,NORM,ON,2mS);\n")
                    f.write("  WAIT(10mS);\n\n")

                    f.write("  for(cyc=0;cyc<16;cyc++)\n  {\n"+'    sprintf(cycMsg,"pdr_trim_index_%d",cyc);\n    SOCKET_INC(FRZ_OFF)\n    {\n       trimDac[SOCKET]=dacArray[cyc];\n    }\n\n')
                    f.write("    set_pdr_trim_data(trimDac);\n\n")

                    f.write('    TEST_NUM++;\n    TEST_NO(TEST_NUM); DATALOG_MSG=cycMsg;\n    JUDGE_PAT(read_status_mode,__read_status_mode);  \n\n')

                    f.write('    SOCKET_INC(FRZ_OFF)\n    {\n      if(PLAN_RESULT_MS[SOCKET]==PASS)\n      {\n        PDR_DAC_FINAL[SOCKET]=trimDac[SOCKET];\n      }\n')
                    f.write('      else\n      {\n	    if(trimDac[SOCKET]==8)\n	    {\n		  PDR_DAC_FINAL[SOCKET]=8;\n		  pdrPassflag[SOCKET]=1;\n	    } \n      }\n      PLAN_RESULT_MS[SOCKET]=PASS;\n    }\n')
                    f.write("  }\n\n")

                    f.write('  SOCKET_INC(FRZ_OFF)\n  {\n    JUDGE_VARIABLE ( SOCKET, PDR_DAC_FINAL[SOCKET],    0,   15, "Pdr_DAC_Final"); \n  }\n\n')

                    f.write(
                        '  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="exit_fbist_mode";\n  JUDGE_PAT(exit_fbist_mode,__exit_fbist_mode);  \n\n')
                    f.write('  POWER_OFF();\n')
                    if relay != "/":
                        f.write("  SET_CBIT(" + relay + ", OFF, 5mS);\n")

                    if relay != "/":
                        f.write("  SET_CBIT(" + relay + ", ON, 5mS);\n")
                    f.write("  POWER_ON(" + G.col("FLOW", "Vcc")[z].upper() + ");\n\n")
                    f.write(
                        '  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="enter_fbist_mode";\n  JUDGE_PAT(enter_fbist_mode,__enter_fbist_mode);  \n\n')

                    f.write(
                        '  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="set_all_final_vposp";\n  JUDGE_PAT(set_all_final_vposp,__set_all_final_vposp);  \n\n')

                    f.write("  set_pdr_trim_data(PDR_DAC_FINAL);\n\n")

                    f.write("  LEVELS(PDR_MIN_LVL, 3mS);\n")
                    f.write("  FORCE_V_MLDPS(" + vcc_rails_str(code_name[G.i]) + ", VCC_PDR_MIN,@6V,@500mA,200mA,NORM,ON,2mS);\n")
                    f.write("  WAIT(10mS);\n\n")
                    f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG=cycMsg;\n  JUDGE_PAT(read_status_mode,__read_status_mode);  \n\n')

                    f.write("  SOCKET_INC(FRZ_OFF)\n  {\n    if(JUDGE_RESULT_MS[SOCKET]==FAIL)\n    {\n      PLAN_RESULT_MS[SOCKET]=PASS;\n    }\n    else\n    {\n      PLAN_RESULT_MS[SOCKET]=FAIL;\n    }\n\n")
                    f.write("    if(pdrPassflag[SOCKET]==1)PLAN_RESULT_MS[SOCKET]=FAIL;\n\n  }\n\n")
                    f.write(
                        '  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="exit_fbist_mode";\n  JUDGE_PAT(exit_fbist_mode,__exit_fbist_mode);  \n\n')
                    f.write('  POWER_OFF();\n  //POWER_DOWN_FAIL_SITE_X(MODE_B);\n\n')
                    if relay != "/":
                        f.write("  SET_CBIT(" + relay + ", OFF, 5mS);\n")
                    f.write("}\n\n")

            G.trash.append(name[j])


def verify_item_write(
    code_name, f, z, recipe_row=None, dac_write_plan=None,
    result_export_plan=None, pdr_verify_plan=None,
):
    typed_pdr_verify = pdr_verify_plan is not None
    program_cp = code_name[G.i].split("_")[-1]
    if typed_pdr_verify and program_cp.casefold() != pdr_verify_plan.cp.casefold():
        return
    # //////////////////////////////////////////////verify 写入start/////////////////////////////////////////////
    G.trash.clear()
    page_word = G.col("VERSION", "page word")[0]
    relay = flow_relay(z)  # 非 "/" 时上下电前后各包一层 SET_CBIT
    flow_cp = pdr_verify_plan.cp if typed_pdr_verify else G.col("FLOW", "CP NO")[z]
    if program_cp.casefold() == str(flow_cp).casefold():
        flow_item = (
            pdr_verify_plan.item
            if typed_pdr_verify
            else G.col("FLOW", "item")[z]
        )
        item_key = _flow_item_key(flow_item)
        is_pdr_verify = typed_pdr_verify or item_key == "pdr_verify"
        is_bor_verify = not typed_pdr_verify and item_key == "bor_verify"
        is_fbist_verify = typed_pdr_verify or (
            G.col("FLOW", "type")[z] == "verify"
            and G.col("FLOW", "mode")[z] == "fbist"
        )
        if is_fbist_verify:
            if not (is_pdr_verify or is_bor_verify):
                generated_item = generated_flow_item_name(G.FLOW, z)
                setup_operations = (list(recipe_setup_operations(recipe_row))
                                    if recipe_row is not None else [])
                if not setup_operations:
                    verify_pattern = recipe_pattern_name(flow_item, "verify mode")
                    setup_patterns = [verify_pattern]
                else:
                    setup_patterns = [
                        (recipe_pattern_name(flow_item, operation.pattern_role)
                         if operation.name == "ENTER" else operation.value)
                        for operation in setup_operations
                    ]
                for setup_pattern in dict.fromkeys(setup_patterns):
                    copy_file(G.BASE_DIR + "\\pat_temp\\" + setup_pattern + ".pat",
                              G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                f.write(generated_item.title() + "()\n{\n")

                f.write("  TEST_NUM=" + str(
                    (z + 1) * 100) + ";\n" + '  TEST_NO( TEST_NUM);DATALOG_MSG="' + G.col("FLOW", "item")[z].lower() + '"; \n\n')
                requires_result_capture = (
                    result_export_plan is not None
                    or G.col("FLOW", "UID")[z] == "yes"
                    or "ts" in G.col("FLOW", "item")[z].lower()
                )
                if requires_result_capture:
                    f.write("  double verifyValue[MAX_SITE] = {0.0};\n\n")
                if relay != "/":
                    f.write("  SET_CBIT(" + relay + ", ON, 5mS);\n")
                f.write("  POWER_ON(" + G.col("FLOW", "Vcc")[z].upper() + ");\n\n")
                if "Hz" not in G.col("FLOW", "UNIT")[z]:
                    f.write("  RELAY_ON(" + G.col("FLOW", "meas pin")[z] + ", PPMU_PDCL, 2mS);\n\n")
                f.write(
                    '  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="enter_fbist_mode";\n  JUDGE_PAT(enter_fbist_mode,__enter_fbist_mode); \n\n')
                for setup_index, setup_pattern in enumerate(setup_patterns):
                    setup_operation = (setup_operations[setup_index]
                                       if setup_operations else None)
                    if (setup_operation is not None
                            and setup_operation.name == "ENTER"
                            and getattr(setup_operation, "value_source", None) == "ARGUMENT"):
                        f.write("  set_" + setup_pattern + "_data(" +
                                str(int(setup_operation.value, 2)) + ");\n")
                    f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + setup_pattern +
                            '";\n  JUDGE_PAT(' + setup_pattern + ',__' + setup_pattern + '); \n\n')
                    if (setup_operation is not None
                            and setup_operation.name == "ENTER"
                            and getattr(setup_operation, "value_source", None) == "ARGUMENT"):
                        f.write("  set_" + setup_pattern + "_data(" +
                                str(int(setup_operation.dynamic_field.value, 2)) + ");\n\n")
                if dac_write_plan is not None:
                    if dac_write_plan.value_source == "ADDR_MAP":
                        restore_expr = _dac_final_addrmap_expr(flow_item)
                        if restore_expr is None:
                            raise ValueError(
                                f"DAC_WRITE item {flow_item!r} 在当前 CP 无 Trim，且 ADDR_MAP 无法恢复"
                            )
                        f.write("  SOCKET_INC(FRZ_OFF)\n  {\n    " +
                                dac_write_plan.dac_symbol + "[SOCKET]=" +
                                restore_expr + ";\n  }\n\n")
                    elif dac_write_plan.value_source == "ARGUMENT":
                        f.write("  int dacWriteData[MAX_SITE];\n")
                        f.write("  SOCKET_INC(FRZ_OFF)\n  {\n    dacWriteData[SOCKET]=" +
                                str(int(dac_write_plan.value, 2)) + ";\n  }\n\n")
                    write_source = (
                        "dacWriteData" if dac_write_plan.value_source == "ARGUMENT"
                        else dac_write_plan.dac_symbol
                    )
                    f.write("  " + dac_write_plan.helper_name + "(" +
                            write_source + ");\n\n")
                if G.col("FLOW", "item")[z].split("_")[0].lower() in list(G.VERSION.columns):
                    f.write(
                        '  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="set_all_final_vposp";;\n  JUDGE_PAT(set_all_final_vposp,__set_all_final_vposp); \n\n')

                if "Hz" in G.col("FLOW", "UNIT")[z]:
                    Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                G.col("FLOW", "target")[z], 0, "FORCE", "FREQ", G.col("FLOW", "low_range(%)")[z],
                                G.col("FLOW", "high_range(%)")[z], f)
                else:
                    Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                G.col("FLOW", "target")[z], 0, "FORCE", "PPMU", G.col("FLOW", "low_range(%)")[z],
                                G.col("FLOW", "high_range(%)")[z], f)

                if str(G.col("FLOW", "PE")[z]).upper() == "ERASE":
                    for nm_name in G.nm_patterns("page erase 1st"):
                        copy_file(G.BASE_DIR + "\\pat_temp\\" + nm_name + ".pat",
                                  G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                        f.write('  TEST_NO(TEST_NUM);  DATALOG_MSG = "' +
                                nm_name + '";  \n  JUDGE_PAT(' +
                                nm_name + ',' +
                                nm_name + ':pe_1);\n\n')
                if str(G.col("FLOW", "PE")[z]).upper() == "PROGRAM":
                    for u in range(len(G.col("NM_PATTERN", "used"))):
                        copy_file(G.BASE_DIR + "\\pat_temp\\" +
                                  G.col("NM_PATTERN", "Pattern name")[u].split(".")[
                                      0] + ".pat",
                                  G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                        if G.col("NM_PATTERN", "used")[u] == "page program PCKB 1st":
                            f.write('  TEST_NO(TEST_NUM);  DATALOG_MSG = "' +
                                    G.col("NM_PATTERN", "Pattern name")[u].split(".")[
                                        0] + '";  \n  JUDGE_PAT(' +
                                    G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ',' +
                                    G.col("NM_PATTERN", "Pattern name")[u].split(".")[
                                        0] + ':pe_1);\n\n')

                f.write('  DATALOG_MSG="' + G.col("FLOW", "item")[z].lower() + '";\n')
                if G.col("FLOW", "item")[z].split("_")[0].lower() in list(G.VERSION.columns):
                    f.write(
                        "  JUDGE_V_PPMU(" + G.col("FLOW", "meas pin")[z] + "," + G.col("FLOW", "item")[z].split("_")[
                            0].upper() + '_TAR-0.05,' + G.col("FLOW", "item")[z].split("_")[
                            0].upper() + '_TAR+0.05' + ',2mS,16,AVE,50uS, ,);\n\n')
                elif requires_result_capture:
                    if "Hz" in G.col("FLOW", "UNIT")[z]:
                        Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                    G.col("FLOW", "target")[z], 0, "MEAS", "FREQ", G.col("FLOW", "low_range(%)")[z],
                                    G.col("FLOW", "high_range(%)")[z], f)
                    else:
                        Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                    G.col("FLOW", "target")[z], 0, "MEAS", "PPMU", G.col("FLOW", "low_range(%)")[z],
                                    G.col("FLOW", "high_range(%)")[z], f)
                    f.write('  SOCKET_INC(FRZ_OFF)\n  {\n    ' + 'verifyValue[SOCKET] = RESULT_PIN(SOCKET, ' +
                            G.col("FLOW", "meas pin")[z] + ');\n')
                    f.write("    JUDGE_VARIABLE ( SOCKET, verifyValue[SOCKET] ," + str(round(
                        calc_limit(G.col("FLOW", "target")[z], G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z], True),
                        3)) + G.col("FLOW", "UNIT")[z] + ', ' + str(round(
                        calc_limit(G.col("FLOW", "target")[z], G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z], False),
                        3)) + G.col("FLOW", "UNIT")[z] + ', "' + generated_item.split("Verify")[0] + 'value_f");\n\n')
                    if result_export_plan is not None and result_export_plan.format == "RAW":
                        f.write("    " + result_export_plan.symbol +
                                "[SOCKET]=verifyValue[SOCKET];\n")
                    elif result_export_plan is not None and result_export_plan.format == "BCD16_MV":
                        f.write("    " + result_export_plan.symbol +
                                "[SOCKET]=(int)(verifyValue[SOCKET]*1000+0.5);\n")
                        f.write(
                            "    " + result_export_plan.symbol + "[SOCKET]=((" +
                            result_export_plan.symbol + "[SOCKET]/1000)%10)*4096+((" +
                            result_export_plan.symbol + "[SOCKET]/100)%10)*256+((" +
                            result_export_plan.symbol + "[SOCKET]/10)%10)*16+(" +
                            result_export_plan.symbol + "[SOCKET]%10);\n")
                    elif result_export_plan is not None and result_export_plan.format == "ADC12_3V3":
                        f.write("    " + result_export_plan.symbol +
                                "[SOCKET]=(int)(verifyValue[SOCKET]/3.3*4096);\n")
                        f.write("    JUDGE_VARIABLE(SOCKET," + result_export_plan.symbol +
                                "[SOCKET]," + str(int(round(
                            (calc_limit(G.col("FLOW", "target")[z], G.col("FLOW", "low_range(%)")[z],
                                        G.col("FLOW", "high_range(%)")[z], True)) / 3.3 * 4096, 0))) + ', ' +
                                str(int(round((calc_limit(G.col("FLOW", "target")[z],
                                                          G.col("FLOW", "low_range(%)")[z],
                                                          G.col("FLOW", "high_range(%)")[z], False)) / 3.3 * 4096,
                                              0))) + ', "' + flow_item.lower() + '_value");\n\n')
                    elif "ts" not in G.col("FLOW", "item")[z].lower():
                        f.write("    " + generated_item.split("Verify")[
                            0].upper() + "W[SOCKET]=(int)(verifyValue[SOCKET]*1000+0.5);\n")
                        f.write(
                            "    " + generated_item.split("Verify")[0].upper() + "W[SOCKET]=((" + generated_item.split("Verify")[
                                0].upper() + "W[SOCKET]/1000)%10)*4096+((" + generated_item.split("Verify")[
                                0].upper() + "W[SOCKET]/100)%10)*256+((" + generated_item.split("Verify")[
                                0].upper() + "W[SOCKET]/10)%10)*16+(" + generated_item.split("Verify")[
                                0].upper() + "W[SOCKET]%10);\n")
                    else:
                        f.write("    TS_" + code_name[G.i].split("_")[
                            -5].upper() + "_W[SOCKET]=(int)(verifyValue[SOCKET]/3.3*4096);\n")
                        f.write("    JUDGE_VARIABLE(SOCKET,TS_" + code_name[G.i].split("_")[
                            -5].upper() + "_W[SOCKET]," + str(int(round(
                            (calc_limit(G.col("FLOW", "target")[z], G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z], True)) / 3.3 * 4096, 0))) + ', ' +
                                str(int(round((calc_limit(G.col("FLOW", "target")[z], G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z], False)) / 3.3 * 4096,
                                              0))) + ', "ts_' + code_name[G.i].split("_")[
                                    -5] + '_value");\n\n')
                    f.write("  }\n\n")



                elif "ts" not in G.col("FLOW", "item")[z].lower():
                    if "Hz" in G.col("FLOW", "UNIT")[z]:
                        Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                    G.col("FLOW", "target")[z], 0, "JUDGE", "FREQ", G.col("FLOW", "low_range(%)")[z],
                                    G.col("FLOW", "high_range(%)")[z], f)
                    else:
                        Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                    G.col("FLOW", "target")[z], 0, "JUDGE", "PPMU", G.col("FLOW", "low_range(%)")[z],
                                    G.col("FLOW", "high_range(%)")[z], f)

                if str(G.col("FLOW", "PE")[z]).upper() == "ERASE":
                    for nm_name in G.nm_patterns("page erase 1st"):
                        f.write('  TEST_NO(TEST_NUM);  DATALOG_MSG = "' +
                                nm_name + '";  \n  JUDGE_PAT(' +
                                nm_name + ':pe_1,__' +
                                nm_name + ');\n\n')
                if str(G.col("FLOW", "PE")[z]).upper() == "PROGRAM":
                    for nm_name in G.nm_patterns("page program PCKB 1st"):
                        f.write('  TEST_NO(TEST_NUM);  DATALOG_MSG = "' +
                                nm_name + '";  \n  JUDGE_PAT(' +
                                nm_name + ':pe_1,__' +
                                nm_name + ');\n\n')

                f.write(
                    '  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="exit_fbist_mode";\n  JUDGE_PAT(exit_fbist_mode,__exit_fbist_mode);  \n\n')
                if "Hz" in G.col("FLOW", "UNIT")[z]:
                    f.write("  SET_TFTM_MODE(" + G.col("FLOW", "meas pin")[z] + ", SCHMITT_OFF);\n\n")
                else:
                    Force_Judge("uA", G.col("FLOW", "meas pin")[z], "0V", G.col("FLOW", "target")[z], 0, "FORCE", "PPMU",
                                G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z], f)
                    Force_Judge("V", G.col("FLOW", "meas pin")[z], "0uA", G.col("FLOW", "target")[z], 0, "FORCE", "PPMU",
                                G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z], f)
                if "Hz" not in G.col("FLOW", "UNIT")[z]:
                    f.write("  RELAY_OFF(" + G.col("FLOW", "meas pin")[z] + ", PPMU_PDCL, 2mS);\n")

                if "TS" in G.col("FLOW", "item")[z].upper() and G.col("FLOW", "UID")[z] == "yes" or G.col("FLOW", "OTP")[z] == "yes":
                    addr_map_item = []
                    title_flag=0
                    pn_flag = ""
                    for addr_cyc in range(len(G.col("ADDR_MAP", "Word No."))):
                        if G.col("ADDR_MAP", "Word No.")[addr_cyc] not in addr_map_item:
                            addr_map_item.append(G.col("ADDR_MAP", "Word No.")[addr_cyc])

                    f.write("\n  SOCKET_INC(FRZ_OFF)\n  {\n\n")
                    for cyc in range(len(addr_map_item)):
                        if code_name[G.i].split("_")[-1][-1] in G.col("ADDR_MAP", "line")[0 + page_word * cyc] and "lable" in list(
                                G.ADDR_MAP["data type"])[0 + page_word * cyc:(page_word-1) + page_word * cyc] :
                            numbers = ''.join(filter(str.isdigit, G.col("ADDR_MAP", "line")[0 + page_word * cyc]))

                            if int(code_name[G.i].split("_")[-1][-1]) >= int(min(numbers)):
                                if addr_map_item[cyc] == "uid":
                                    result = epr_pattern_capture("normal", "cp" + str(int(code_name[G.i].split("_")[-1][-1])) + "_id")
                                else:
                                    result = epr_pattern_capture("normal", addr_map_item[cyc])
                                for u in range(0 + page_word * cyc, (page_word-1) + page_word * cyc):
                                    if G.col("ADDR_MAP", "data type")[u] == "lable" and generated_item in G.col("ADDR_MAP", "CP addr map")[u]:
                                        if title_flag == 0:
                                            f.write("  //******************" + addr_map_item[cyc] + " pattern**************************\n\n")
                                            title_flag = 1
                                        if "反码" in G.col("ADDR_MAP", "bit[31:16]")[u]:
                                            pn_flag = "yes"
                                        else:
                                            pn_flag = "no"
                                        if "TS" in G.col("FLOW", "item")[z].upper():

                                            write_pat_mem(f, result, 15, "-J", 0, G.col("ADDR_MAP", "bit[15:0]")[u].split("[")[0],
                                                          G.col("ADDR_MAP", "bit[15:0]")[u].lower().split("verify")[0].upper() + "W[SOCKET]",
                                                          G.col("ADDR_MAP", "bit[15:0]")[u].lower().split("_verify")[0].lower() + "_", pn_flag)
                                        else:
                                            write_pat_mem(f, result, 15, "-J", 0, G.col("ADDR_MAP", "bit[15:0]")[u].split("[")[0],
                                                          "REG_" + G.col("ADDR_MAP", "bit[15:0]")[u].split("[")[
                                                              0].upper() + "[SOCKET]",
                                                          G.col("ADDR_MAP", "bit[15:0]")[u].split("[")[0].lower() + "_", pn_flag)
                    f.write("  }\n  fflush(stdout);\n\n")  # for socket

                f.write('  POWER_OFF();\n  //POWER_DOWN_FAIL_SITE_X(MODE_B);\n\n')
                if relay != "/":
                    f.write("  SET_CBIT(" + relay + ", OFF, 5mS);\n")
                if G.flow_row_flag(z) == "force_pass":
                    f.write("  SOCKET_INC(FRZ_OFF)\n  {\n\tPLAN_RESULT_MS[SOCKET]=PASS;\n  }\n\n")
                f.write("}\n\n")  # item{}
            else:
                copy_file(G.BASE_DIR + "\\pat_temp\\" + "enter_" + G.col("FLOW", "item")[z].lower() + ".pat",
                          G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                f.write(G.col("FLOW", "item")[z].title() + "()\n{\n")

                f.write("  TEST_NUM=" + str(
                    (z + 1) * 100) + ";\n" + '  TEST_NO( TEST_NUM);DATALOG_MSG="' + G.col("FLOW", "item")[z].lower() + '"; \n\n')
                if is_pdr_verify:
                    f.write("  int pdrVerifyflag[MAX_SITE];\n\n")
                    space = 0
                else:

                    f.write("  int borVerifyflag[MAX_SITE];\n\n")
                    f.write("  int borDac["+str(len(G.col("FLOW", "LINE")[z].split("\n")[2].split(":")[1].split(",")))+"]={"+str(G.col("FLOW", "LINE")[z].split("\n")[2].split(":")[1])+"};\n")
                    f.write("  double borRisingvoltage["+str(len(G.col("FLOW", "LINE")[z].split("\n")[0].split(":")[1].split(",")))+"]={"+str(G.col("FLOW", "LINE")[z].split("\n")[0].split(":")[1])+"};\n")
                    f.write("  double borFallingvoltage["+str(len(G.col("FLOW", "LINE")[z].split("\n")[1].split(":")[1].split(",")))+"]={"+str(G.col("FLOW", "LINE")[z].split("\n")[1].split(":")[1])+"};\n")
                    space = 2
                if relay != "/":
                    f.write("  SET_CBIT(" + relay + ", ON, 5mS);\n")
                f.write("  POWER_ON(" + G.col("FLOW", "Vcc")[z].upper() + ");\n\n")
                f.write(
                    '  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="enter_fbist_mode";\n  JUDGE_PAT(enter_fbist_mode,__enter_fbist_mode); \n\n')
                f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + "enter_" + G.col("FLOW", "item")[z].lower() + '";\n  JUDGE_PAT(' + "enter_" + G.col("FLOW", "item")[z].lower() + ',__' + "enter_" + G.col("FLOW", "item")[z].lower() + '); \n\n')

                if is_pdr_verify:
                    f.write("  LEVELS(PDR_MAX_LVL, 3mS);\n")
                    f.write("  FORCE_V_MLDPS(" + vcc_rails_str(code_name[G.i]) + ", VCC_PDR_MAX,@6V,@500mA,200mA,NORM,ON,2mS);\n")
                    f.write("  WAIT(10mS);\n\n")
                else:
                    f.write("  for(I=0;I<sizeof(borRisingvoltage)/sizeof(borRisingvoltage[0]);I++)\n  {\n")
                    f.write("	set_bor_data(borDac[I]);\n\n")
                    f.write("	POWER_Shmoo_ON(borFallingvoltage[I]);\n\n")
                copy_file(G.BASE_DIR + "\\pat_temp\\" + "read_status_mode" + ".pat",
                          G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                f.write(space*" "+'  TEST_NUM++;\n'+space*" "+'  TEST_NO(TEST_NUM); DATALOG_MSG="read_status_mode";\n'+space*" "+'  JUDGE_PAT(read_status_mode,__read_status_mode); \n\n')
                f.write(space * " " + '  SOCKET_INC(FRZ_OFF)\n' + space * " " + '  {\n' + space * " " + "    "+G.col("FLOW", "item")[z].lower().split("_")[0]+'Verifyflag[SOCKET]=0;\n')
                # PDR 在 MAX 电压下器件应正常工作（read_status 应 PASS），故判定 FAIL 才置 flag；
                # BOR 在下降沿电压下应已复位，PASS 才置 flag（语义不同，仅对 Pdr 取反）。
                _pdr_max_cond = "FAIL" if is_pdr_verify else "PASS"
                f.write(space * " " + '    if(JUDGE_RESULT_MS[SOCKET]=='+_pdr_max_cond+') '+G.col("FLOW", "item")[z].lower().split("_")[0]+'Verifyflag[SOCKET]=1;\n'+ space * " " + '  }\n\n')

                if is_pdr_verify:
                    f.write("  LEVELS(PDR_MIN_LVL, 3mS);\n")
                    f.write("  FORCE_V_MLDPS(" + vcc_rails_str(code_name[G.i]) + ", VCC_PDR_MIN,@6V,@500mA,200mA,NORM,ON,2mS);\n")
                    f.write("  WAIT(10mS);\n\n")
                else:
                    f.write("	POWER_Shmoo_ON(borRisingvoltage[I]);\n\n")

                f.write(space*" "+'  TEST_NUM++;\n'+space*" "+'  TEST_NO(TEST_NUM); DATALOG_MSG="read_status_mode";\n'+space*" "+'  JUDGE_PAT(read_status_mode,__read_status_mode); \n\n')
                f.write(space * " " + '  SOCKET_INC(FRZ_OFF)\n' + space * " " + '  {\n')
                # PDR 在 MIN 电压下器件应已复位（read_status 应 FAIL），故判定 PASS 才置 flag；
                # BOR 在上升沿电压下应正常工作、FAIL 才置 flag（语义不同，仅对 Pdr 取反）。
                _pdr_min_cond = "PASS" if is_pdr_verify else "FAIL"
                f.write(space * " " + '    if(JUDGE_RESULT_MS[SOCKET]=='+_pdr_min_cond+') '+G.col("FLOW", "item")[z].lower().split("_")[0]+'Verifyflag[SOCKET]=1;\n'+ space * " " + '  }\n\n')

                if is_bor_verify:
                    f.write("  }\n\n")

                f.write('  SOCKET_INC(FRZ_OFF)\n  {\n')
                f.write('    if('+G.col("FLOW", "item")[z].lower().split("_")[0]+'Verifyflag[SOCKET]==1'+')\n    {\n	  PLAN_RESULT_MS[SOCKET]=FAIL;\n    }\n    else\n    {\n	  PLAN_RESULT_MS[SOCKET]=PASS;\n    }\n  }\n\n')

                f.write(
                    '  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="exit_fbist_mode";\n  JUDGE_PAT(exit_fbist_mode,__exit_fbist_mode); \n\n')
                f.write('  POWER_OFF();\n  //POWER_DOWN_FAIL_SITE_X(MODE_B);\n\n')
                if relay != "/":
                    f.write("  SET_CBIT(" + relay + ", OFF, 5mS);\n")
                f.write("}\n\n")  # item{}
    G.trash.append(
        pdr_verify_plan.item
        if typed_pdr_verify
        else G.col("FLOW", "item")[z]
    )


def hex_pattern_write(code_name, f, z):
    step_list = []
    relay_off = "  RELAY_OFF("
    relay_pin = []
    if code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[z]:
        if G.col("FLOW", "mode")[z] == "hex":
            step_list = G.col("FLOW", "step")[z].split("\n")
            for step in step_list:
                # print(step)
                if step == "reset":
                    f.write(
                        '  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + "reset_pattern" + '";\n  JUDGE_PAT(' + "reset_pattern" + ',__' + "reset_pattern" + '); \n\n')
                elif "power" in step:
                    f.write("  POWER_Shmoo_ON(" + step.split(" ")[1] + ");\n\n")
                elif step == "turn on/off":
                    f.write("  POWER_OFF();\n" + "  POWER_ON(" + G.col("FLOW", "Vcc")[z].upper() + ");\n\n")
                    if "Hz" not in G.col("FLOW", "UNIT")[z] and "VCC" not in G.col("FLOW", "meas pin")[z] and \
                            G.col("FLOW", "UNIT")[z] != "pat":
                        f.write("  RELAY_ON(" + G.col("FLOW", "meas pin")[z] + ", PPMU_PDCL, 2mS);\n\n")
                elif "forcepin" in step:
                    f.write("  RELAY_ON(" + step.split(" ")[1] + ", PPMU_PDCL, 2mS);\n\n")
                    relay_off += step.split(" ")[1]
                    for value in range(len(list(step.split(" ")[1].split("+")))):
                        relay_pin.append(list(step.split(" ")[1].split("+"))[value])
                elif "forcevalue" in step:
                    for value in range(len(list(step.split(" ")[1].split("+")))):
                        f.write("  FORCE_V_PPMU(" + relay_pin[value] + "," + list(step.split(" ")[1].split("+"))[
                            value] + ", ,@2mA, , 2mS);\n")
                elif step == "trigger":
                    # 2026-07-15：force_1_0 已泛化为电平序列 pattern，默认触发脉冲=
                    # <pin>_hl_5ms（get_pin_patterns_created 无条件备一份）。hex 触发无 <PIN>:
                    # 前缀=默认触发 → 显示名 Trig（2026-07-24），种子按真实 GET PIN。
                    _gp = G.col("VERSION", "GET PIN")[G.i]
                    _hlreal = level_seq_pat_name(_gp, "HL", default_pulse()[1])
                    _hlname = level_seq_pat_name(trig_disp(_gp, True), "HL", default_pulse()[1])
                    copy_trig_pat(_hlreal, _hlname, G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                    f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + _hlname
                            + '";\n  JUDGE_PAT(' + _hlname + ',__' + _hlname + '); \n\n')
                elif "send" in step:
                    _gp = G.col("VERSION", "GET PIN")[G.i]
                    _base = trig_disp(_gp, True) + "_send_num"
                    _n = int(step.split(" ")[1])
                    copy_trig_pat(_gp + "_send_num", _base, G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                    f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + _base + ":s" + decimal_to_hex(_n)
                            + '";\n  JUDGE_PAT(' + _base + ":s" + decimal_to_hex(_n) + ',' + _base + ":s"
                            + decimal_to_hex(_n + 1) + '); \n\n')
                elif "wait" in step:
                    f.write('  WAIT(' + step.split(" ")[1] + "mS);\n")
                elif step.isspace() or not step:
                    continue
                else:
                    f.write(
                        '  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + step + '";\n  JUDGE_PAT(' + step + ',__' + step + '); \n\n')

            return relay_off


def hex_trim_item_write(code_name, f, z, bisection):
    # //////////////////////////////////////////////trim 写入start/////////////////////////////////////////////
    relay_off = ""
    if code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[z]:
        if G.col("FLOW", "type")[z] == "trim" and G.col("FLOW", "mode")[z] == "hex":
            if bisection == "no":
                f.write(G.col("FLOW", "item")[z].split("Trim")[0].title() + "Dac_Loop()\n{\n")
                f.write("  TEST_NUM=" + str(
                    (G.j + 1) * 50) + ";\n" + '  TEST_NO(TEST_NUM);DATALOG_MSG="' + G.col("FLOW", "item")[z].split("Trim")[
                            0].lower() + 'dac_loop"; \n\n')
            else:
                f.write(G.col("FLOW", "item")[z].title() + "()\n{\n")
                f.write("  TEST_NUM=" + str(
                    (G.j + 1) * 50) + ";\n" + '  TEST_NO(TEST_NUM);DATALOG_MSG="' + G.col("FLOW", "item")[
                            z].lower() + '"; \n\n')

            f.write("  double trimTar=" + str(G.col("FLOW", "target")[z]) + ';\n\n')
            f.write(
                "  double trimValue[MAX_SITE],trimFinalValue[MAX_SITE];\n  int trimDac[MAX_SITE];\n\n")
            if bisection == "no":
                f.write("  int cyc=0;\n  int endCyc=" + str(
                    pow(2, G.col("FLOW", "DAC bit")[z])) + ";\n  char cycMsg[48];\n\n")
            elif G.col("FLOW", "LINE")[z] == "yes":
                f.write(
                    "  int dacArray[" + str(pow(2, G.col("FLOW", "DAC bit")[z]) - 1) + "]={0};\n")
                f.write("  for(I=0;I<" + str(
                    pow(2, G.col("FLOW", "DAC bit")[z]) - 1) + ";I++)\n  {\n    dacArray[I]=I;\n  }\n\n")
                f.write(
                    "  int dacIndex[MAX_SITE];\n  int firstIndex=sizeof(dacArray)/sizeof(dacArray[0])/2;\n  int binAryCyc=(int)log2((double)(sizeof(dacArray)/sizeof(dacArray[0])+1))-2;\n\n")
            else:
                f.write("  int dacArray[" + str(
                    pow(2, G.col("FLOW", "DAC bit")[z]) - 1) + "]={" + str(
                    G.col("FLOW", "step")[z]) + "};\n\n")
                f.write(
                    "  int dacIndex[MAX_SITE];\n  int firstIndex=sizeof(dacArray)/sizeof(dacArray[0])/2;\n  int binAryCyc=(int)log2((double)(sizeof(dacArray)/sizeof(dacArray[0])+1))-2;\n\n")
            f.write(
                "  //initial\n  for(I=0;I<MAX_SITE;I++)\n  {\n    trimValue[I]=0;\n    trimFinalValue[I]=0;\n")
            if bisection == "no":
                f.write("\n    trimDac[I]=0;\n\n  } \n\n")
            else:
                f.write(
                    "\n    trimDac[I]=dacArray[firstIndex];\n    dacIndex[I]=firstIndex;\n\n  } \n\n")
            f.write("  POWER_ON(" + G.col("FLOW", "Vcc")[z].upper() + ");\n\n")
            for sub_cyc in range(len(G.col("FLOW", "sub"))):

                if G.col("FLOW", "item")[sub_cyc] == G.col("FLOW", "item")[z] and G.col("FLOW", "CP NO")[sub_cyc] == \
                        code_name[G.i].split("_")[-1]:
                    if "Hz" not in G.col("FLOW", "UNIT")[sub_cyc] and "VCC" not in G.col("FLOW", "meas pin")[
                        sub_cyc] and "turn on/off" not in G.col("FLOW", "step")[sub_cyc]:
                        f.write("  RELAY_ON(" + G.col("FLOW", "meas pin")[sub_cyc] + ", PPMU_PDCL, 2mS);\n\n")
                    relay_off = hex_pattern_write(code_name, f, sub_cyc)
                    if "Hz" in G.col("FLOW", "UNIT")[z]:
                        Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                    G.col("FLOW", "target")[z], 0, "FORCE", "FREQ", G.col("FLOW", "low_range(%)")[z],
                                    G.col("FLOW", "high_range(%)")[z], f)
                    else:
                        Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                    G.col("FLOW", "target")[z], 0, "FORCE", "PPMU", G.col("FLOW", "low_range(%)")[z],
                                    G.col("FLOW", "high_range(%)")[z], f)

                    f.write('  do\n  {\n')
                    if bisection == "no":
                        f.write('    sprintf(cycMsg,"' + str(
                            G.col("FLOW", "item")[z].lower().split("trim")[0]) + '_dac_%d",cyc);\n    cyc++; \n')

                    f.write('    set_send_data(trimDac);\n\n')
                    if "Hz" in G.col("FLOW", "UNIT")[z]:
                        Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                    G.col("FLOW", "target")[z], 2, "MEAS", "FREQ", G.col("FLOW", "low_range(%)")[z],
                                    G.col("FLOW", "high_range(%)")[z], f)
                    elif int(G.col("FLOW", "target")[z]) < 0 and "V" in G.col("FLOW", "UNIT")[z]:
                        # PMU 写法（用户 2026-07-12 认为有问题，屏蔽保留供参考，改走 PPMU）
                        f.write("    //PARAL_INC(" + G.col("FLOW", "meas pin")[
                            z] + ")\n    //{\n      //RELAY_OFF(PIN_DEFS,PDCL,2mS);\n      //RELAY_ON(PIN_DEFS,PMU,2mS);\n\n")
                        f.write(
                            "      //FORCE_I_PMU(PMU,0uA,@100uA,@12V,6V,ON,3mS);\n      //MEAS_V_PMU(PMU,IFVM,2mS,16,AVE,50uS);\n"
                            "      //FORCE_I_PMU(PMU,0uA,@100uA,@12V,6V,OFF,3mS);\n\n")
                        f.write("      //RELAY_OFF(PIN_DEFS,PMU,2mS);\n      //RELAY_ON(PIN_DEFS,PDCL,2mS);\n"
                                "    //}\n\n")
                        f.write("    MEAS_V_PPMU(" + G.col("FLOW", "meas pin")[z] + ", 2mS, 16, AVE, 50uS);\n\n")
                    else:
                        Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                    G.col("FLOW", "target")[z], 2, "MEAS", "PPMU", G.col("FLOW", "low_range(%)")[z],
                                    G.col("FLOW", "high_range(%)")[z], f)
                    f.write(
                        '    TEST_NUM++;\n    TEST_NO(TEST_NUM);DATALOG_MSG="' + G.col("FLOW", "item")[z].lower() + '";\n')
                    f.write('    SOCKET_INC(FRZ_OFF)\n    {\n')

                    if "A" in G.col("FLOW", "UNIT")[z]:
                        f.write(
                            "      trimValue[SOCKET] = RESULT_PIN(SOCKET, " + G.col("FLOW", "meas pin")[
                                z] + ")*1000000; //uA\n")
                    elif "Hz" in G.col("FLOW", "UNIT")[z]:
                        f.write(
                            "      trimValue[SOCKET] = RESULT_PIN(SOCKET, " + G.col("FLOW", "meas pin")[
                                z] + ")/1000; //Khz\n")
                    else:
                        f.write(
                            "      trimValue[SOCKET] = RESULT_PIN(SOCKET, " + G.col("FLOW", "meas pin")[
                                z] + ");\n")

                    if bisection == "no":
                        f.write('      JUDGE_VARIABLE(SOCKET,trimValue[SOCKET], ' + str(
                            round(G.col("FLOW", "target")[z] - (abs(G.col("FLOW", "target")[z] * 2)),
                                  2)) + ', ' + str(
                            round(G.col("FLOW", "target")[z] + (abs(G.col("FLOW", "target")[z] * 5)),
                                  2)) + ', cycMsg);\n\n')
                    else:
                        f.write('      JUDGE_VARIABLE(SOCKET,trimDac[SOCKET], ' + '0, ' + str(
                            pow(2, G.col("FLOW", "DAC bit")[z]) - 1) + ', "' + G.col("FLOW", "item")[z].split("Trim")[
                                    0] + 'dac");\n')
                        f.write('      JUDGE_VARIABLE(SOCKET,trimValue[SOCKET], ' + str(
                            round(G.col("FLOW", "target")[z] - (abs(G.col("FLOW", "target")[z] * 2)),
                                  2)) + ', ' + str(
                            round(G.col("FLOW", "target")[z] + (abs(G.col("FLOW", "target")[z] * 5)),
                                  2)) + ', "' + G.col("FLOW", "item")[z].split("Trim")[0] + 'value");\n\n')
                    f.write(
                        '      if(fabs(trimValue[SOCKET]-trimTar)<fabs(trimFinalValue[SOCKET]-trimTar))\n      {\n        trimFinalValue[SOCKET] = trimValue[SOCKET];\n        ' +
                        G.col("FLOW", "item")[z].split("Trim")[
                            0].upper() + 'DAC_FINAL[SOCKET] = trimDac[SOCKET];\n      }\n\n')
                    if bisection == "yes":
                        f.write(
                            "      if (trimValue[SOCKET] < trimTar)\n      {\n        dacIndex[SOCKET] = dacIndex[SOCKET] + (int)pow((float)2, (float)binAryCyc);\n        trimDac[SOCKET] = dacArray[dacIndex[SOCKET]];\n      }\n\n")
                        f.write(
                            "      else\n      {\n        dacIndex[SOCKET] = dacIndex[SOCKET] - (int)pow((float)2, (float)binAryCyc);\n        trimDac[SOCKET] = dacArray[dacIndex[SOCKET]];\n      }\n\n")
                    else:

                        f.write("      trimDac[SOCKET] = cyc;\n")

                    f.write('    }\n\n')  # socket_inc{}
                    if bisection == "yes":
                        f.write('    binAryCyc-=1;\n\n')
                    if bisection == "yes":
                        f.write('  }while(binAryCyc>=-1);  \n')  # do while{}
                    else:
                        f.write('  }while(cyc<endCyc);   \n')  # do while{}
                    f.write('  //fflush(stdout);\n\n')
                    f.write("  set_send_data(" +
                        str(G.col("FLOW", "item")[z].lower().split("trim")[0]).upper() + "DAC_FINAL);\n\n")

                    f.write(
                        '  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + G.col("FLOW", "item")[z].lower() + '";\n\n')
                    f.write('  SOCKET_INC(FRZ_OFF)\n  {\n    JUDGE_VARIABLE(SOCKET,' +
                            G.col("FLOW", "item")[z].split("Trim")[0].upper() + 'DAC_FINAL[SOCKET],0, ' + str(
                        pow(2, G.col("FLOW", "DAC bit")[z]) - 1) + ', "' + G.col("FLOW", "item")[z].split("Trim")[
                                0] + 'dac_f");\n  }\n\n')

                    if G.col("FLOW", "UID")[z] == "yes":

                        if "Hz" in G.col("FLOW", "UNIT")[z]:
                            Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                        G.col("FLOW", "target")[z], 2, "MEAS", "FREQ", G.col("FLOW", "low_range(%)")[z],
                                        G.col("FLOW", "high_range(%)")[z], f)
                        else:
                            Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                        G.col("FLOW", "target")[z], 2, "MEAS", "PPMU", G.col("FLOW", "low_range(%)")[z],
                                        G.col("FLOW", "high_range(%)")[z], f)
                        f.write('  SOCKET_INC(FRZ_OFF)\n  {\n    ' + G.col("FLOW", "item")[z].split("Trim")[
                            0].lower() + 'value_Final[SOCKET] = RESULT_PIN(SOCKET, TP);\n  }\n')
                        f.write('  JUDGE_VARIABLE_MS (' + G.col("FLOW", "item")[z].split("Trim")[
                            0].lower() + 'value_Final,' + str(round(calc_limit(G.col("FLOW", "target")[z], G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z], True), 2)) +
                                G.col("FLOW", "UNIT")[z] + ', ' + str(round(calc_limit(G.col("FLOW", "target")[z], G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z], False), 2)) +
                                G.col("FLOW", "UNIT")[z] + ',"' + G.col("FLOW", "item")[z].split("Trim")[
                                    0].lower() + 'value_f" );\n')
                    else:
                        f.write('  DATALOG_MSG="' + G.col("FLOW", "item")[z].split("Trim")[0] + 'value_f";\n')

                        if G.col("FLOW", "item")[z].split("_")[0].lower() in list(G.VERSION.columns):
                            if G.col("FLOW", "target")[z] < -2 and "V" in G.col("FLOW", "UNIT")[z]:
                                f.write(
                                    "  SOCKET_INC(FRZ_OFF)\n  {\n    trimValue[SOCKET] = RESULT_PIN(SOCKET, " +
                                    G.col("FLOW", "meas pin")[z] + ");\n" +
                                    '    JUDGE_VARIABLE(SOCKET,trimValue[SOCKET], ' + G.col("FLOW", "item")[z].split("_")[
                                        0].upper() + '_TAR-0.05,' + G.col("FLOW", "item")[z].split("_")[
                                        0].upper() + '_TAR+0.05,"' +
                                    G.col("FLOW", "item")[z].split("Trim")[0] + 'value_f");\n  }\n\n')
                            else:
                                f.write("  JUDGE_V_PPMU(" + G.col("FLOW", "meas pin")[z] + "," +
                                        G.col("FLOW", "item")[z].split("_")[0].upper() + '_TAR-0.05,' +
                                        G.col("FLOW", "item")[z].split("_")[0].upper() + '_TAR+0.05' + ',2mS);\n\n')
                        else:

                            if "Hz" in G.col("FLOW", "UNIT")[z]:
                                Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                            G.col("FLOW", "target")[z], 0, "JUDGE", "FREQ", G.col("FLOW", "low_range(%)")[z],
                                            G.col("FLOW", "high_range(%)")[z], f)
                            else:
                                Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                            G.col("FLOW", "target")[z], 0, "JUDGE", "PPMU", G.col("FLOW", "low_range(%)")[z],
                                            G.col("FLOW", "high_range(%)")[z], f)


                    if "Hz" in G.col("FLOW", "UNIT")[z]:
                        f.write("  SET_TFTM_MODE(" + G.col("FLOW", "meas pin")[z] + ", SCHMITT_OFF);\n\n")
                    else:
                        Force_Judge("uA", G.col("FLOW", "meas pin")[z], "0V", G.col("FLOW", "target")[z], 0, "FORCE", "PPMU",
                                    G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z], f)
                        Force_Judge("V", G.col("FLOW", "meas pin")[z], "0uA", G.col("FLOW", "target")[z], 0, "FORCE", "PPMU",
                                    G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z], f)
                    if "Hz" not in G.col("FLOW", "UNIT")[z]:
                        f.write("  RELAY_OFF(" + G.col("FLOW", "meas pin")[z] + ", PPMU_PDCL, 2mS);\n")

                    f.write('  POWER_OFF();\n  //POWER_DOWN_FAIL_SITE_X(MODE_B);\n\n')
                    f.write("}\n\n")


def hex_verify_item_write(code_name, f, z):
    # //////////////////////////////////////////////verify 写入start/////////////////////////////////////////////
    relay_off = ""
    temp_string = ""
    temp_dict = {}
    result_dict = {}
    temp_keys = []
    temp_values = []
    if code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[z]:
        if G.col("FLOW", "type")[z] == "verify" and G.col("FLOW", "mode")[z] == "hex":
            f.write(G.col("FLOW", "item")[z].title() + "()\n{\n")

            f.write("  TEST_NUM=" + str(
                (z + 1) * 50) + ";\n" + '  TEST_NO( TEST_NUM);DATALOG_MSG="' + G.col("FLOW", "item")[
                        z].lower() + '"; \n\n')
            if G.col("FLOW", "UID")[z] == "yes":
                f.write("  double verifyValue[MAX_SITE] = {0.0};\n\n")
            f.write("  POWER_ON(" + G.col("FLOW", "Vcc")[z].upper() + ");\n\n")
            for sub_cyc in range(len(G.col("FLOW", "sub"))):
                temp_values.clear()
                temp_keys.clear()
                if G.col("FLOW", "item")[sub_cyc] == G.col("FLOW", "item")[z] and G.col("FLOW", "CP NO")[sub_cyc] == \
                        code_name[G.i].split("_")[-1]:
                    f.write("////////////////////" + G.col("FLOW", "sub")[sub_cyc].lower() + "/////////////////\n")
                    if "Hz" not in G.col("FLOW", "UNIT")[sub_cyc] and "VCC" not in G.col("FLOW", "meas pin")[
                        sub_cyc] and "turn on/off" not in G.col("FLOW", "step")[sub_cyc]:
                        f.write("  RELAY_ON(" + G.col("FLOW", "meas pin")[sub_cyc] + ", PPMU_PDCL, 2mS);\n\n")

                    relay_off = hex_pattern_write(code_name, f, sub_cyc)

                    if G.col("FLOW", "UNIT")[sub_cyc].lower() != "pat":
                        if "Hz" in G.col("FLOW", "UNIT")[sub_cyc]:
                            Force_Judge(G.col("FLOW", "UNIT")[sub_cyc], G.col("FLOW", "meas pin")[sub_cyc],
                                        G.col("FLOW", "FV/FI")[sub_cyc],
                                        G.col("FLOW", "target")[sub_cyc], 0, "FORCE", "FREQ",
                                        G.col("FLOW", "low_range(%)")[sub_cyc], G.col("FLOW", "high_range(%)")[sub_cyc], f)
                        elif "VCC" in G.col("FLOW", "meas pin")[sub_cyc]:
                            Force_Judge(G.col("FLOW", "UNIT")[sub_cyc], G.col("FLOW", "meas pin")[sub_cyc],
                                        G.col("FLOW", "FV/FI")[sub_cyc],
                                        G.col("FLOW", "target")[sub_cyc], 0, "FORCE", "MLDPS",
                                        G.col("FLOW", "low_range(%)")[sub_cyc], G.col("FLOW", "high_range(%)")[sub_cyc], f)
                        else:
                            Force_Judge(G.col("FLOW", "UNIT")[sub_cyc], G.col("FLOW", "meas pin")[sub_cyc],
                                        G.col("FLOW", "FV/FI")[sub_cyc],
                                        G.col("FLOW", "target")[sub_cyc], 0, "FORCE", "PPMU",
                                        G.col("FLOW", "low_range(%)")[sub_cyc], G.col("FLOW", "high_range(%)")[sub_cyc], f)
                    else:
                        if G.col("FLOW", "FV/FI")[sub_cyc] == "/":
                            f.write("")
                        else:
                            f.write("  RELAY_ON(" + G.col("FLOW", "meas pin")[sub_cyc] + ", PPMU_PDCL, 2mS);\n\n")
                            Force_Judge("V", G.col("FLOW", "meas pin")[sub_cyc], G.col("FLOW", "FV/FI")[sub_cyc], 0, 0,
                                        "FORCE", "PPMU", 1, 1, f)

                    f.write('  DATALOG_MSG="' + G.col("FLOW", "sub")[sub_cyc].lower() + '";\n')
                    if G.col("FLOW", "UID")[sub_cyc] == "yes":
                        if "Hz" in G.col("FLOW", "UNIT")[sub_cyc]:
                            Force_Judge(G.col("FLOW", "UNIT")[sub_cyc], G.col("FLOW", "meas pin")[sub_cyc],
                                        G.col("FLOW", "FV/FI")[sub_cyc],
                                        G.col("FLOW", "target")[sub_cyc], 0, "MEAS", "FREQ",
                                        G.col("FLOW", "low_range(%)")[sub_cyc], G.col("FLOW", "high_range(%)")[sub_cyc], f)
                        elif "VCC" in G.col("FLOW", "meas pin")[sub_cyc]:
                            Force_Judge(G.col("FLOW", "UNIT")[sub_cyc], G.col("FLOW", "meas pin")[sub_cyc],
                                        G.col("FLOW", "FV/FI")[sub_cyc],
                                        G.col("FLOW", "target")[sub_cyc], 0, "MEAS", "MLDPS",
                                        G.col("FLOW", "low_range(%)")[sub_cyc], G.col("FLOW", "high_range(%)")[sub_cyc], f)
                        else:
                            Force_Judge(G.col("FLOW", "UNIT")[sub_cyc], G.col("FLOW", "meas pin")[sub_cyc],
                                        G.col("FLOW", "FV/FI")[z],
                                        G.col("FLOW", "target")[sub_cyc], 0, "MEAS", "PPMU",
                                        G.col("FLOW", "low_range(%)")[sub_cyc], G.col("FLOW", "high_range(%)")[sub_cyc], f)
                        f.write('  SOCKET_INC(FRZ_OFF)\n  {\n    ' + 'verifyValue[SOCKET] = RESULT_PIN(SOCKET, ' +
                                G.col("FLOW", "meas pin")[sub_cyc] + ');\n')
                        f.write("    JUDGE_VARIABLE ( SOCKET, verifyValue[SOCKET] ," + str(round(
                            calc_limit(G.col("FLOW", "target")[sub_cyc], G.col("FLOW", "low_range(%)")[sub_cyc], G.col("FLOW", "high_range(%)")[sub_cyc], True),
                            3)) + G.col("FLOW", "UNIT")[sub_cyc] + ', ' + str(round(
                            calc_limit(G.col("FLOW", "target")[sub_cyc], G.col("FLOW", "low_range(%)")[sub_cyc], G.col("FLOW", "high_range(%)")[sub_cyc], False),
                            3)) + G.col("FLOW", "UNIT")[sub_cyc] + ', "' + G.col("FLOW", "item")[sub_cyc].split("Verify")[
                                    0] + 'value_f");\n\n')

                        f.write("    " + G.col("FLOW", "item")[sub_cyc].split("Verify")[
                            0].upper() + "W[SOCKET]=(int)(verifyValue[SOCKET]*1000+0.5);\n")
                        f.write(
                            "    " + G.col("FLOW", "item")[sub_cyc].split("Verify")[0].upper() + "W[SOCKET]=((" +
                            G.col("FLOW", "item")[sub_cyc].split("Verify")[0].upper() + "W[SOCKET]/1000)%10)*4096+((" +
                            G.col("FLOW", "item")[sub_cyc].split("Verify")[0].upper() + "W[SOCKET]/100)%10)*256+((" +
                            G.col("FLOW", "item")[sub_cyc].split("Verify")[0].upper() + "W[SOCKET]/10)%10)*16+(" +
                            G.col("FLOW", "item")[sub_cyc].split("Verify")[0].upper() + "W[SOCKET]%10);\n")
                        f.write("  }\n\n")

                    else:
                        if G.col("FLOW", "UNIT")[sub_cyc].lower() != "pat":
                            if "Hz" in G.col("FLOW", "UNIT")[sub_cyc]:
                                Force_Judge(G.col("FLOW", "UNIT")[sub_cyc], G.col("FLOW", "meas pin")[sub_cyc],
                                            G.col("FLOW", "FV/FI")[sub_cyc],
                                            G.col("FLOW", "target")[sub_cyc], 0, "JUDGE", "FREQ",
                                            G.col("FLOW", "low_range(%)")[sub_cyc], G.col("FLOW", "high_range(%)")[sub_cyc],
                                            f)
                            elif "VCC" in G.col("FLOW", "meas pin")[sub_cyc]:
                                Force_Judge(G.col("FLOW", "UNIT")[sub_cyc], G.col("FLOW", "meas pin")[sub_cyc],
                                            G.col("FLOW", "FV/FI")[sub_cyc],
                                            G.col("FLOW", "target")[sub_cyc], 0, "JUDGE", "MLDPS",
                                            G.col("FLOW", "low_range(%)")[sub_cyc], G.col("FLOW", "high_range(%)")[sub_cyc],
                                            f)
                            else:
                                Force_Judge(G.col("FLOW", "UNIT")[sub_cyc], G.col("FLOW", "meas pin")[sub_cyc],
                                            G.col("FLOW", "FV/FI")[sub_cyc],
                                            G.col("FLOW", "target")[sub_cyc], 0, "JUDGE", "PPMU",
                                            G.col("FLOW", "low_range(%)")[sub_cyc], G.col("FLOW", "high_range(%)")[sub_cyc],
                                            f)
                        else:
                            if G.col("FLOW", "FV/FI")[sub_cyc] == "/":
                                f.write('\n  TEST_NUM++;\n  TEST_NO(TEST_NUM);\n  JUDGE_PAT(' + G.col("FLOW", "meas pin")[
                                    sub_cyc].replace("+", "").lower() + "_compare_" + G.col("FLOW", "target")[
                                            sub_cyc].lower() + ',__' + G.col("FLOW", "meas pin")[sub_cyc].replace("+",
                                                                                                               "").lower() + "_compare_" +
                                        G.col("FLOW", "target")[sub_cyc].lower() + '); \n\n')
                            else:
                                try:
                                    for temp_pin in range(len(G.col("FLOW", "meas pin")[sub_cyc].split("+"))):
                                        temp_keys.append(G.col("FLOW", "meas pin")[sub_cyc].split("+")[temp_pin])
                                        temp_values.append(G.col("FLOW", "target")[sub_cyc][temp_pin])
                                    temp_dict = dict(zip(temp_keys, temp_values))
                                except:
                                    temp_keys.append(G.col("FLOW", "meas pin")[sub_cyc])
                                    temp_values.append(G.col("FLOW", "target")[sub_cyc])
                                    temp_dict = dict(zip(temp_keys, temp_values))

                                result_dict = process_dict(temp_dict)

                                for measvalue in result_dict.keys():
                                    if measvalue == "H":
                                        Force_Judge("V", result_dict[measvalue], G.col("FLOW", "FV/FI")[sub_cyc], 3.3, 0,
                                                    "JUDGE", "PPMU", 10, 6, f)
                                    elif measvalue == "L":
                                        Force_Judge("V", result_dict[measvalue], G.col("FLOW", "FV/FI")[sub_cyc], 0.5, 0,
                                                    "JUDGE", "PPMU", 100, 2, f)

                    if G.col("FLOW", "UNIT")[sub_cyc].lower() == "pat" and G.col("FLOW", "FV/FI")[sub_cyc] != "/":
                        f.write("  RELAY_OFF(" + G.col("FLOW", "meas pin")[sub_cyc] + ", PPMU_PDCL, 2mS);\n")

                    if G.col("FLOW", "UNIT")[sub_cyc].lower() != "pat":
                        if "Hz" in G.col("FLOW", "UNIT")[sub_cyc]:
                            f.write("  SET_TFTM_MODE(" + G.col("FLOW", "meas pin")[sub_cyc] + ", SCHMITT_OFF);\n\n")
                        elif "VCC" in G.col("FLOW", "meas pin")[sub_cyc]:
                            continue
                        else:
                            Force_Judge("uA", G.col("FLOW", "meas pin")[sub_cyc], "0V", G.col("FLOW", "target")[sub_cyc], 0,
                                        "FORCE", "PPMU", G.col("FLOW", "low_range(%)")[sub_cyc],
                                        G.col("FLOW", "high_range(%)")[sub_cyc], f)
                            Force_Judge("V", G.col("FLOW", "meas pin")[sub_cyc], "0uA", G.col("FLOW", "target")[sub_cyc], 0,
                                        "FORCE", "PPMU", G.col("FLOW", "low_range(%)")[sub_cyc],
                                        G.col("FLOW", "high_range(%)")[sub_cyc], f)
                        if "Hz" not in G.col("FLOW", "UNIT")[sub_cyc] and "VCC" not in G.col("FLOW", "meas pin")[sub_cyc]:
                            f.write("  RELAY_OFF(" + G.col("FLOW", "meas pin")[sub_cyc] + ", PPMU_PDCL, 2mS);\n")
                    else:
                        f.write(relay_off + ", PPMU_PDCL, 2mS);\n\n")

            f.write('  POWER_OFF();\n  //POWER_DOWN_FAIL_SITE_X(MODE_B);\n\n')
            f.write("}\n\n")  # item{}


def trim_data_read_write(
    code_name, f, j, read_bit, recipe_row=None, persistence_row_plan=None,
    trim_data_plan=None,
):
    trim_data_plan = trim_data_plan or G.compiled_adapter.trim_data_plan
    recipe_modules = _persistence_recipe_modules(recipe_row)
    read_otp_operation = (
        persistence_row_plan.operation("READOTPMAP")
        if persistence_row_plan is not None else None
    )
    effective_read_pages = (
        read_otp_operation.effective_pages if read_otp_operation is not None else None
    )
    current_cp = code_name[G.i].split("_")[-1]
    target_pages = (
        _trim_target_pages(trim_data_plan, current_cp)
        if (recipe_modules is not None
            and G.col("FLOW", "type")[j] in ("data", "write")) else None
    )
    addr_map_item = []
    temp_retrim_list = []
    page_word = G.col("VERSION", "page word")[0]
    if G.col("FLOW", "type")[j] != "trim" and G.col("FLOW", "type")[j] != "verify" and G.col("FLOW", "type")[
        j] != "os" and G.col("FLOW", "type")[j] != "id" and code_name[G.i].split("_")[-1] == \
            G.col("FLOW", "CP NO")[j]:
        f.write(G.col("FLOW", "item")[j].title() + "()\n{\n")
        f.write("  TEST_NUM=" + str((j + 1) * 50) + ";\n" + '  TEST_NO(TEST_NUM);DATALOG_MSG="' +
                G.col("FLOW", "item")[j] + '"; \n\n')
        # trim write & read
        if G.col("FLOW", "type")[j] == "read" or G.col("FLOW", "type")[j] == "data" or G.col("FLOW", "type")[
            j] == "write" and code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[j]:

            if (G.col("FLOW", "type")[j] == "read"
                    and _recipe_module_enabled(recipe_modules, "READOTPMAP")):
                f.write("  POWER_ON(" + G.col("FLOW", "Vcc")[j].upper() + ");\n\n")
                f.write(
                    '  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="enter_fbist_mode";\n  JUDGE_PAT(enter_fbist_mode,__enter_fbist_mode); \n\n')
                for z in range(len(G.col("ADDR_MAP", "Word No."))):
                    if G.col("ADDR_MAP", "Word No.")[z] not in addr_map_item:
                        addr_map_item.append(G.col("ADDR_MAP", "Word No.")[z])
                # f.write("  SOCKET_INC(FRZ_OFF)\n  {\n\n")
                for cyc in range(len(addr_map_item)):
                    numbers = ''.join(filter(str.isdigit, G.col("ADDR_MAP", "line")[0 + page_word * cyc]))
                    if (effective_read_pages is None or addr_map_item[cyc] in effective_read_pages) and code_name[G.i].split("_")[-1][-1] in G.col("ADDR_MAP", "line")[0 + page_word * cyc] and "lable" in list(
                            G.ADDR_MAP["data type"])[0 + page_word * cyc:page_word + page_word * cyc] and addr_map_item[cyc] != "uid":
                        if int(code_name[G.i].split("_")[-1][-1]) > int(min(numbers)):
                            result = epr_pattern_capture("capture", addr_map_item[cyc])
                            copy_file(G.BASE_DIR + "\\pat_temp\\" + result["read"] + ".pat",
                                      G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                            # 逐字段判断真实字节宽度(2或4字节)+按 read_bit 分组反序，修复
                            # 原先整页统一按32bit算的隐患（本项目 trim0/trim1/factory3 目前
                            # 恰好清一色反码字段、算出来数值没变，但代码本身跟 uid 页
                            # 是同一个 bug，见 _page_field_layout）。
                            layout = _page_field_layout(addr_map_item[cyc], read_bit)
                            total_bytes = sum(width for _, width, _so in layout)

                            f.write("  //******************" + addr_map_item[cyc] + " capture***********************\n\n")
                            f.write("  int " + addr_map_item[cyc].lower() + "_0x00" +
                                    G.col("ADDR_MAP", "SM Address")[0 + page_word * cyc].split(";")[0].split("0x")[
                                        1] + "[MAX_SITE]" + "[" + str(total_bytes) + "];\n\n")
                            f.write("  SET_CAPTURE_MEM_MODE(" + str(
                                G.col("VERSION", "SWD PIN")[G.i]) + ", PEL_K, ON, 8K);\n\n")
                            f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' +
                                    result["read"] + '";\n  JUDGE_PAT(' + result["read"] + ',__' + result[
                                        "read"] + '); \n\n')

                            f.write(
                                "  SOCKET_INC(FRZ_OFF)\n  {\n    for(J=0;J<" + str(
                                    total_bytes * 8) + ";J++) TEMP_DATA[J]=8;\n\n")
                            f.write("    READ_CAPTURE_MEM_BLOCK(SOCKET, " + str(
                                G.col("VERSION", "SWD PIN")[G.i]) + ", 0, " + str(
                                total_bytes * 8 - 1) + ", TEMP_DATA);//" + str(
                                total_bytes) + "byte\n")
                            f.write('    printf("S%d:' + r"\n" + '",SOCKET);\n')
                            f.write('    printf("data 0x0200:' + r"\n" + '",SOCKET);\n')
                            f.write('    for(I=0;I<' + str(
                                total_bytes) + ';I++)//' + str(
                                total_bytes) + 'byte\n    {\n')
                            f.write("      " + addr_map_item[cyc] + "_0x00" + str(
                                G.col("ADDR_MAP", "SM Address")[0 + page_word * cyc].split(";")[0].split("0x")[
                                    1]) + "[SOCKET]" + "[I]" + "=0;\n")
                            f.write(
                                "      for(J=0;J<8;J++)\n      {\n        if(TEMP_DATA[8*I+J]!=8) " + addr_map_item[
                                    cyc] + "_0x00" + str(
                                    G.col("ADDR_MAP", "SM Address")[0 + page_word * cyc].split(";")[0].split("0x")[
                                        1]) + "[SOCKET]" + "[I]" + " += TEMP_DATA[8*I+J]<<(7-J);\n      }\n\n")
                            f.write('      if(I%4==0)\n      {\n        printf("%02X: ",I);\n      }\n\n')
                            f.write('      printf("0x%02X ",' + addr_map_item[cyc] + "_0x00" + str(
                                G.col("ADDR_MAP", "SM Address")[0 + page_word * cyc].split(";")[0].split("0x")[
                                    1]) + "[SOCKET]" + "[I]" + ');\n\n')
                            f.write('      if((I+1)%2==0)\n      {\n        printf("' + r"\n" + '");\n      }\n\n')
                            f.write("    }\n\n")  # for i
                            f.write('    printf("' + r"\n" + '");\n\n')

                            arr_name = addr_map_item[cyc] + "_0x00" + str(
                                G.col("ADDR_MAP", "SM Address")[0 + page_word * cyc].split(";")[0].split("0x")[1])
                            off = 0
                            for type_flag, width, sub_off in layout:
                                f.write(type_flag + arr_name + "[SOCKET][" + str(off + sub_off) + "]*256+" + arr_name +
                                        "[SOCKET][" + str(off + sub_off + 1) + "];\n")
                                off += width

                            f.write("  }\n\n")  # socket
                            f.write("  fflush(stdout);\n\n")
                            f.write("  SET_CAPTURE_MEM_MODE(" + str(
                                G.col("VERSION", "SWD PIN")[G.i]) + ", PEL_K, OFF, 8K);\n\n")

                G.set_vposp_name.clear()
                for binding in trim_data_plan.bindings:
                    if binding.pump:
                        G.set_vposp_name.append(
                            binding.reference("SOCKET") + str(binding.dac_bits))
                G.set_vposp_name.append("Vcsl_DAC_FINAL[SOCKET]3")
                G.set_vposp_name.append("Vneg2_DAC_FINAL[SOCKET]3")
                G.set_vposp_name.append("Vbl_DAC_FINAL[SOCKET]4")
                temp_list = []
                bit_list = []
                f.write("  SOCKET_INC(FRZ_OFF)\n  {\n\n")
                f.write("    //You need to check it by yourself\n")
                # print(set_vposp_name)
                for z in range(len(G.set_vposp_name)):
                    # print(set_vposp_name[z].split("DAC_FINAL")[0]+"Trim")

                    for item_cyc in range(len(G.col("ADDR_MAP", "CP addr map"))):
                        if type(G.col("ADDR_MAP", "CP addr map")[item_cyc]) == str:
                            for item_num in G.col("ADDR_MAP", "CP addr map")[item_cyc].split(",") :
                                if trim_data_reference_matches(G.set_vposp_name[z], item_num):
                                    temp_list = G.col("ADDR_MAP", "CP addr map")[item_cyc].split(",")
                                    # print(temp_list)
                                    bit_list.clear()
                                    shift_flag = 0
                                    shift = 0
                                    for temp_cyc in range(len(temp_list)):
                                        bit_num = 0
                                        try:
                                            # print(int(temp_list[temp_cyc].split("[")[1].split(":")[0])+1)
                                            bit_num = int(temp_list[temp_cyc].split("[")[1].split(":")[0]) + 1
                                        except:
                                            try:
                                                # print(int(temp_list[temp_cyc].split("'")[0]))
                                                bit_num = leading_bit_width(temp_list[temp_cyc])
                                            except:
                                                # print(1)
                                                bit_num = 1
                                        if shift_flag == 1:
                                            shift += bit_num
                                        if trim_data_reference_matches(G.set_vposp_name[z], temp_list[temp_cyc]):
                                            shift_flag = 1
                                            for bit in range(bit_num):
                                                bit_list.append(1)
                                        else:
                                            for bit in range(bit_num):
                                                bit_list.append(0)
                                    # print(G.col("ADDR_MAP", "CP addr map")[item_cyc], 0)

                                    f.write("    " + G.set_vposp_name[z].rstrip("0123456789").upper() + "=(REG_" +
                                            G.col("ADDR_MAP", "bit[15:0]")[item_cyc].split("[")[
                                                0].upper() + "[SOCKET]&" + bin_list_to_hex(bit_list) + ")>>" + str(
                                        shift) + ";\n")

                f.write("  }\n\n")

                if _recipe_module_enabled(recipe_modules, "SETVPOSP"):
                    set_all_final_vposp(f)
                    copy_file(G.BASE_DIR + "\\pat_temp\\" + "set_all_final_vposp" + ".pat",
                              G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")

                # 跨 CP 复用 dac 补值（见 reuse_dac_restore_items）：本 CP 有 trim 项在
                # pattern sheet 标了 reuse dac，但被依赖项本身没在本 CP 里重新 trim 过
                # （如 CP3 的 Hsi_8/16/24/48M_Trim 依赖 CP1 已经 trim 好的 Hsi_Vrega，CP3
                # 没有 Hsi_Vrega_Trim 这一步）——该被依赖项对应 pattern（如 set_hsi_vrega_dac）
                # 内存里就没有 live 收敛值，trim_item_write 里现成的 reuse dac 逻辑会直接
                # 套用编译期写死的占位值。这里从刚读回的 EPR 值算出最终 dac、重新
                # WRITE_PAT_MEM 灌回该 pattern 一次，之后同 CP 内每个 reuse 该项的 trim
                # 只需 JUDGE_PAT 复跑即可拿到正确值（不用改 trim_item_write）。
                for ref_item in reuse_dac_restore_items(code_name[G.i].split("_")[-1]):
                    expr = _dac_final_addrmap_expr(ref_item)
                    if expr is None:
                        continue
                    ref_row = next(
                        row for row, flow_item in enumerate(G.col("FLOW", "item"))
                        if dac_final_symbol(flow_item) == dac_final_symbol(ref_item)
                        and G.col("FLOW", "type")[row] == "trim"
                    )
                    dac_bit = int(G.col("FLOW", "DAC bit")[ref_row])
                    reuse_pat_name = recipe_pattern_name(ref_item, "trim dac")
                    var_name = dac_final_symbol(ref_item) + "[SOCKET]"
                    f.write("  SOCKET_INC(FRZ_OFF)\n  {\n\n")
                    f.write("    " + var_name + "=" + expr + ";\n")
                    f.write("    TEMP = " + var_name + "; //restore " + ref_item +
                            " dac(not retrimmed in this CP)\n")
                    f.write("    for(J=0;J<=" + str(dac_bit - 1) + ";J++)\n    {\n"
                            "      BIT[J] = 0;\n      BIT[J] = TEMP%2;\n      TEMP = TEMP/2;\n    }\n\n")
                    f.write("    for(J=" + str(dac_bit - 1) + ";J>=0;J--)\n    {\n")
                    f.write("      if(BIT[J]==0)\n      {\n         WRITE_PAT_MEM(SOCKET, " + str(
                        G.col("VERSION", "SWD PIN")[G.i]) + ", " + reuse_pat_name + ":a_data+" + str(
                        dac_bit - 1) + '-J, ,"0");\n      }\n')
                    f.write("      else\n      {\n         WRITE_PAT_MEM(SOCKET, " + str(
                        G.col("VERSION", "SWD PIN")[G.i]) + ", " + reuse_pat_name + ":a_data+" + str(
                        dac_bit - 1) + '-J, ,"1");\n      }\n    }\n\n')
                    f.write("  }\n\n")
                    copy_file(G.BASE_DIR + "\\pat_temp\\" + reuse_pat_name + ".pat",
                              G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                    f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + reuse_pat_name +
                            '";\n  JUDGE_PAT(' + reuse_pat_name + ',__' + reuse_pat_name + '); \n\n')

        addr_map_item = []
        pn_flag = ""
        for z in range(len(G.col("ADDR_MAP", "Word No."))):
            if G.col("ADDR_MAP", "Word No.")[z] not in addr_map_item:
                addr_map_item.append(G.col("ADDR_MAP", "Word No.")[z])
        if ((G.col("FLOW", "type")[j] == "read" or G.col("FLOW", "type")[j] == "data")
                and _recipe_module_enabled(recipe_modules, "LOADMAP")):

            f.write("  SOCKET_INC(FRZ_OFF)\n  {\n\n")
            for cyc in range(len(addr_map_item)):
                if code_name[G.i].split("_")[-1][-1] in G.col("ADDR_MAP", "line")[0 + page_word * cyc] and "lable" in list(
                        G.ADDR_MAP["data type"])[0 + page_word * cyc:(page_word-1) + page_word * cyc]:
                    numbers = ''.join(filter(str.isdigit, G.col("ADDR_MAP", "line")[0 + page_word * cyc]))
                    if (int(code_name[G.i].split("_")[-1][-1]) >= int(min(numbers))
                            and addr_map_item[cyc] != "uid"
                            and (target_pages is None or addr_map_item[cyc] in target_pages)):
                        f.write("  //******************" + addr_map_item[cyc] + " pattern**************************\n\n")
                        result = epr_pattern_capture("normal", addr_map_item[cyc])
                        copy_file(G.BASE_DIR + "\\pat_temp\\" + result["read"] + ".pat",
                                  G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                        for u in range(0 + page_word * cyc, (page_word-1) + page_word * cyc):
                            if G.col("ADDR_MAP", "data type")[u] == "lable":
                                if "反码" in G.col("ADDR_MAP", "bit[31:16]")[u]:
                                    pn_flag = "yes"
                                else:
                                    pn_flag = "no"
                                write_pat_mem(f, result, 15, "-J", 0, G.col("ADDR_MAP", "bit[15:0]")[u].split("[")[0],
                                              "REG_" + G.col("ADDR_MAP", "bit[15:0]")[u].split("[")[0].upper() + "[SOCKET]",
                                              G.col("ADDR_MAP", "bit[15:0]")[u].split("[")[0].lower() + "_", pn_flag)
            f.write("  }\n  fflush(stdout);\n\n")  # for socket
            if (G.col("FLOW", "type")[j] == "read"
                    and _recipe_module_enabled(recipe_modules, "CHECKOTP")):
                f.write("  ////////////////////////check///////////////////////////\n")
                f.write("  POWER_ON(" + G.col("FLOW", "Vcc")[j].upper() + ");\n\n")
                f.write(
                    '  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="enter_fbist_mode";\n  JUDGE_PAT(enter_fbist_mode,__enter_fbist_mode); \n\n')
                for cyc in range(len(addr_map_item)):
                    if code_name[G.i].split("_")[-1][-1] in G.col("ADDR_MAP", "line")[0 + page_word * cyc] and addr_map_item[
                        cyc] != "uid" and (target_pages is None or addr_map_item[cyc] in target_pages):
                        result = epr_pattern_capture("normal", addr_map_item[cyc])
                        f.write(
                            '  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + result["read"] + '";\n  JUDGE_PAT(' +
                            result["read"] + ',__' + result["read"] + '); \n\n')

                f.write('  POWER_OFF(); \n\n')
                f.write("}\n\n")
        if ((G.col("FLOW", "type")[j] == "write" or G.col("FLOW", "type")[j] == "data")
                and (recipe_modules is None or any(module in recipe_modules for module in
                                                   ("COMMIT", "LOADMAP", "PGMOTP")))):
            uid_result = None
            reg_list = []
            reg_temp = ""
            _write_explicit_commit(f, recipe_row, current_cp)
            # 2026-07-07：去掉原有的 "!= CP1" 排除——跟 S100 platforms/s100/writers.py
            # 同款修法，CP1 需要走这条路径把 uid 页的 dac 早写补上（原来的排除会让下方
            # uid_reg_list 变成死代码）；CP1 自己非 uid 的 reg_list 匹配（如 CLK_TRIM0）
            # 在别处（本函数上方的通用 EPR 回读+重写段）已经处理过一遍，这里用 is_cp1
            # 单独跳过，避免重复写（见下）。
            if "Rewrite" not in G.col("FLOW", "item")[j].title():
                temp_retrim_list.clear()
                for binding in trim_data_plan.for_cp(code_name[G.i].split("_")[-1]):
                    temp_retrim_list.append(
                        binding.reference("SOCKET") + str(binding.dac_bits))

                # print(temp_retrim_list, code_name[G.i].split("_")[-1])
                temp_list = []
                bit_list = []
                if len(temp_retrim_list) > 0:
                    f.write("  SOCKET_INC(FRZ_OFF)\n  {\n\n")
                    f.write("    //You need to check it by yourself\n")
                    uid_reg_list = []
                    # CP1 的 FLOW type=="data"，上方那段"if type[j]=='read' or =='data':"
                    # （@2280 附近）已经对所有非 uid 页的每个 lable 字段通用 write_pat_mem
                    # 过一遍——CP1 走这里的 reg_list（非 uid）分支会产出重复的
                    # WRITE_PAT_MEM。CP2/CP3 是 type=="write"，没有那段，必须靠这里补上，
                    # 不能跳过。所以只有 CP1 的非 uid 匹配要跳过，uid 匹配（早写的核心
                    # 目的）两边 CP 都要处理。
                    is_cp1 = code_name[G.i].split("_")[-1] == "CP1"
                    for z in range(len(temp_retrim_list)):
                        # print(temp_retrim_list[z].split("DAC_FINAL")[0] + "Trim")
                        for item_cyc in range(len(G.col("ADDR_MAP", "line"))):
                            if type(G.col("ADDR_MAP", "CP addr map")[item_cyc]) == str and any(
                                    trim_data_reference_matches(temp_retrim_list[z], token)
                                    for token in G.col("ADDR_MAP", "CP addr map")[item_cyc].split(",")):
                                if is_cp1 and G.col("ADDR_MAP", "Word No.")[item_cyc] != "uid":
                                    continue
                                temp_list = G.col("ADDR_MAP", "CP addr map")[item_cyc].split(",")
                                # print(temp_list)
                                bit_list.clear()
                                shift_flag = 0
                                shift = 0
                                for temp_cyc in range(len(temp_list)):
                                    bit_num = 0
                                    try:
                                        # print(int(temp_list[temp_cyc].split("[")[1].split(":")[0]) + 1)
                                        bit_num = int(temp_list[temp_cyc].split("[")[1].split(":")[0]) + 1
                                    except:
                                        try:
                                            # print(int(temp_list[temp_cyc].split("'")[0]))
                                            bit_num = leading_bit_width(temp_list[temp_cyc])
                                        except:
                                            # print(1)
                                            bit_num = 1
                                    if shift_flag == 1:
                                        shift += bit_num
                                    if trim_data_reference_matches(temp_retrim_list[z], temp_list[temp_cyc]):
                                        shift_flag = 1
                                        for bit in range(bit_num):
                                            bit_list.append(1)
                                    else:
                                        for bit in range(bit_num):
                                            bit_list.append(0)
                                # print(invert_hex_string(bin_list_to_hex(bit_list), 16))
                                # temp_retrim_list[z] 形如 "Hsi_8M_DAC_FINAL[SOCKET]10"（末尾是
                                # FLOW DAC bit 位宽数字）；这里要把变量名和位宽数字拼开，用
                                # rstrip 去掉末尾全部数字（而非只切 1 个字符）——Hsi 系列位宽是
                                # 两位数"10"，切 1 个字符会留下 1 个杂散数字，拼出语法错误的
                                # "...[SOCKET]1<<0"（2026-07-06 修）。
                                f.write("    " + "REG_" + G.col("ADDR_MAP", "bit[15:0]")[item_cyc].split("[")[
                                    0].upper() + "[SOCKET]"
                                        + "=(REG_" + G.col("ADDR_MAP", "bit[15:0]")[item_cyc].split("[")[
                                            0].upper() + "[SOCKET]&" + invert_hex_string(bin_list_to_hex(bit_list),
                                                                                         16) + ")|" + temp_retrim_list[
                                                                                                          z].rstrip(
                                    "0123456789").upper() + "<<" + str(
                                    shift) + ";\n")

                                if "反码" in G.col("ADDR_MAP", "bit[31:16]")[item_cyc]:
                                    reg_temp = G.col("ADDR_MAP", "bit[15:0]")[item_cyc] + "&&yes&&" + \
                                               G.col("ADDR_MAP", "Word No.")[item_cyc]
                                else:
                                    reg_temp = G.col("ADDR_MAP", "bit[15:0]")[item_cyc] + "&&no&&" + \
                                               G.col("ADDR_MAP", "Word No.")[item_cyc]
                                # uid 页的 dac 字段（如 Hsi_8M_Trim）要在 trim 刚出炉时就提前写进
                                # cp<N>_id pattern（早写），不能跟 trim0/trim1 等普通页一样走
                                # 下面 reg_list 的 epr_pattern_capture("normal", Word No.) 逻辑——
                                # 那样会去找一个不存在的 "fbist_page_prog_uid" pattern。分流到
                                # uid_reg_list，用本 CP 自己的 cp<N>_id pattern 单独处理（见下）。
                                if G.col("ADDR_MAP", "Word No.")[item_cyc] == "uid":
                                    if reg_temp not in uid_reg_list:
                                        uid_reg_list.append(reg_temp)
                                elif reg_temp not in reg_list:
                                    reg_list.append(reg_temp)
                    f.write("\n")
                    for z in reg_list:
                        result = epr_pattern_capture("normal", z.split("&&")[2])
                        write_pat_mem(f, result, 15, "-J", 0, z.split("&&")[0].split("[")[0],
                                      "REG_" + z.split("&&")[0].split("[")[0].upper() + "[SOCKET]",
                                      z.split("&&")[0].split("[")[0].lower() + "_", z.split("&&")[1])

                    if uid_reg_list:
                        uid_pat_name = "cp" + code_name[G.i].split("_")[-1][-1] + "_id"
                        uid_result = epr_pattern_capture("normal", uid_pat_name)
                        copy_file(G.BASE_DIR + "\\pat_temp\\" + uid_result["erase"] + ".pat",
                                  G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                        copy_file(G.BASE_DIR + "\\pat_temp\\" + uid_result["pgm"] + ".pat",
                                  G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                        copy_file(G.BASE_DIR + "\\pat_temp\\" + uid_result["read"] + ".pat",
                                  G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                        for z in uid_reg_list:
                            write_pat_mem(f, uid_result, 15, "-J", 0, z.split("&&")[0].split("[")[0],
                                          "REG_" + z.split("&&")[0].split("[")[0].upper() + "[SOCKET]",
                                          z.split("&&")[0].split("[")[0].lower(), z.split("&&")[1])
                        # pass id flag：uid 页 word-offset5 现在是运行时 label（core/flash_seq.py
                        # Part B），早写阶段必须显式写一次占位值 0xFFFFFFFF——否则这个字段在
                        # 软件缓冲区里是未定义的，早写落地的 erase→prog→read 会把垃圾值烧进去。
                        # 真正的 pass 值留到 uid_write 晚写阶段再改写。
                        write_pat_mem(f, uid_result, 31, "-J", 0, "pass id flag", "0xFFFFFFFF",
                                      "cp12_id_", "no")

                    f.write("  }\n\n")
            # if "Rewrite"  in list(FLOW["item"])[j].title() and code_name[i].split("_")[-1] != "CP1":
            #     for z in range(len(list(FLOW["type"]))):
            #         if list(FLOW["item"])[z] == "Verify" and list(FLOW["OTP"])[z] == "yes" and list(FLOW["CP NO"])[z] == code_name[i].split("_")[-1]:


            if not _recipe_module_enabled(recipe_modules, "PGMOTP"):
                f.write("}\n\n")
                return

            f.write("  ////////////////////////complete///////////////////////////\n")
            f.write("  POWER_ON(" + G.col("FLOW", "Vcc")[j].upper() + ");\n\n")
            f.write(
                '  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="enter_fbist_mode";\n  JUDGE_PAT(enter_fbist_mode,__enter_fbist_mode); \n\n')
            for cyc in range(len(addr_map_item)):
                if code_name[G.i].split("_")[-1][-1] in G.col("ADDR_MAP", "line")[0 + page_word * cyc] and addr_map_item[
                    cyc] != "uid" and (target_pages is None or addr_map_item[cyc] in target_pages):
                    result = epr_pattern_capture("normal", addr_map_item[cyc])
                    copy_file(G.BASE_DIR + "\\pat_temp\\" + result["erase"] + ".pat",
                              G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                    f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + result["erase"] + '";\n  JUDGE_PAT(' +
                            result["erase"] + ',__' + result["erase"] + '); \n\n')
                    copy_file(G.BASE_DIR + "\\pat_temp\\" + result["pgm"] + ".pat",
                              G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                    f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + result["pgm"] + '";\n  JUDGE_PAT(' +
                            result["pgm"] + ',__' + result["pgm"] + '); \n\n')
                    copy_file(G.BASE_DIR + "\\pat_temp\\" + result["read"] + ".pat",
                              G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                    f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + result["read"] + '";\n  JUDGE_PAT(' +
                            result["read"] + ',__' + result["read"] + '); \n\n')

            # 早写的 uid 页（cp<N>_id）erase→prog→read 落地：紧跟在上面这组"complete"
            # 收尾之后、同一次 POWER_ON/POWER_OFF 周期内一起做，不是单独一次电源周期——
            # 早写阶段只往软件缓冲区里写了 dac + pass-flag 占位值，只有真正 JUDGE_PAT
            # 这三行才会把它物理烧进芯片。
            if uid_result is not None:
                f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + uid_result["erase"] + '";\n  JUDGE_PAT(' +
                        uid_result["erase"] + ',__' + uid_result["erase"] + '); \n\n')
                f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + uid_result["pgm"] + '";\n  JUDGE_PAT(' +
                        uid_result["pgm"] + ',__' + uid_result["pgm"] + '); \n\n')
                f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + uid_result["read"] + '";\n  JUDGE_PAT(' +
                        uid_result["read"] + ',__' + uid_result["read"] + '); \n\n')

            f.write('  POWER_OFF(); \n\n')
            if uid_result is not None:
                write_uid_failed_site_reerase(
                    f, uid_result, vcc=G.col("FLOW", "Vcc")[j]
                )
            f.write("}\n\n")

            # wakeup
        # wakeup
        if G.col("FLOW", "item")[j] == "Memory_Wakeup" and code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[j]:
            addr_map_item = []
            trimming_item = ["Vcsl_Trim", "Vneg2_Trim", "Vbl_Trim"] + [
                binding.addr_map_name
                for binding in trim_data_plan.for_cp(code_name[G.i].split("_")[-1])
            ]
            trimming_keys = {logical_item_key(item) for item in trimming_item}
            # 对齐 startup.py 的同款规则：VCSL/VNEG2/VBL 只在 FLOW 没有对应 Trim 项时才
            # 硬编码默认值——否则会把该 Trim 项 bisection 算出来的真实 DAC_FINAL 覆盖回写死值
            # （若 Memory_Wakeup 排在对应 Trim 项之后执行，会用错的硬编码码去做 wakeup）。
            flow_trim_items = [
                binding.dac_final_symbol.removesuffix("_DAC_FINAL")
                for binding in trim_data_plan.bindings
            ]
            pump_defaults = [("VCSL", "0"), ("VNEG2", "0"), ("VBL", "5")]
            reset_lines = [var + "_DAC_FINAL[SOCKET]=" + default + ";"
                           for var, default in pump_defaults if var not in flow_trim_items]
            if reset_lines:
                f.write("  SOCKET_INC(FRZ_OFF)\n  {\n    " + "\n    ".join(reset_lines) + "\n  }\n\n")
            f.write("  SOCKET_INC(FRZ_OFF)\n  {\n")
            for z in range(len(G.col("ADDR_MAP", "Word No."))):
                if G.col("ADDR_MAP", "Word No.")[z] not in addr_map_item:
                    addr_map_item.append(G.col("ADDR_MAP", "Word No.")[z])
            for cyc in range(len(addr_map_item)):
                if code_name[G.i].split("_")[-1][-1] in G.col("ADDR_MAP", "line")[0 + page_word * cyc] and "lable" in list(
                        G.ADDR_MAP["data type"])[0 + page_word * cyc:(page_word) + page_word * cyc]:
                    f.write("    ////////////////////////" + addr_map_item[
                        cyc] + " page address map///////////////////////////\n\n")
                    for z in range(0 + page_word * cyc, (page_word) + page_word * cyc):
                        # 对齐 S100：跳过 verify 寄存器（其结果存在 *_W，由 verify 测量写；
                        # uid 页 map 不应写未声明的 REG_*_VERIFY）。
                        if G.col("ADDR_MAP", "data type")[z] == "lable" and "verify" not in str(G.col("ADDR_MAP", "bit[15:0]")[z]).lower() and "verify" not in str(G.col("ADDR_MAP", "bit[31:16]")[z]).lower():
                            if type(G.col("ADDR_MAP", "description")[z]) == str:
                                f.write(
                                    "                        //" + G.col("ADDR_MAP", "description")[
                                        z] + "\n                        //Default = 0x" +
                                    (G.col("ADDR_MAP", "CP Data[31:0]")[z].split("h")[1]).split("_")[0]
                                    + (G.col("ADDR_MAP", "CP Data[31:0]")[z].split("h")[1]).split("_")[1] + "\n")
                            else:
                                f.write(
                                    "                        //Default = 0x" +
                                    (G.col("ADDR_MAP", "CP Data[31:0]")[z].split("h")[1]).split("_")[0]
                                    + (G.col("ADDR_MAP", "CP Data[31:0]")[z].split("h")[1]).split("_")[1] + "\n")
                            f.write("    " + "REG_" + str(
                                G.col("ADDR_MAP", "bit[15:0]")[z].split("[")[0]).upper() + "[SOCKET]=")
                            desc = []
                            bit_temp = 0
                            # print(G.col("ADDR_MAP", "CP addr map")[z])
                            desc = G.col("ADDR_MAP", "CP addr map")[z].split(",")

                            for map_item in range(len(desc)):
                                desc[map_item] = desc[map_item].strip()
                                try:
                                    range_num = addr_map_field_width(desc[map_item])
                                    if "[" not in desc[map_item] or ":" not in desc[map_item]:
                                        raise ValueError
                                    bit_temp += range_num
                                    try:
                                        if logical_item_key(desc[map_item]) in trimming_keys:
                                            dac_item = dac_final_symbol(desc[map_item]) + "[SOCKET]"


                                        else:
                                            temp_num = 0
                                            for cyc in range(range_num):
                                                temp_num += int(
                                                    hex_to_bin_16bit(G.col("ADDR_MAP", "CP Data[31:0]")[z].split("_")[1])[
                                                        (bit_temp - 1) - cyc]) << cyc

                                            dac_item = str(temp_num)
                                    except:
                                        if logical_item_key(desc[map_item]) in trimming_keys:
                                            dac_item = dac_final_symbol(desc[map_item]) + "[SOCKET]"

                                    if map_item != len(desc) - 1:
                                        f.write("(" + dac_item + "<<" + str(
                                            16 - (bit_temp)) + ")" + "+")
                                    else:
                                        f.write("(" + dac_item + "<<" + str(
                                            16 - (bit_temp)) + ")" + ";")

                                except:
                                    try:
                                        if desc[map_item][:1].isdigit():
                                            bit_temp += addr_map_field_width(desc[map_item])
                                            literal_value = addr_map_literal_value(desc[map_item])
                                            if literal_value is None:
                                                literal_value = 0
                                            suffix = "+" if map_item != len(desc) - 1 else ";"
                                            f.write("(" + str(literal_value) + "<<" + str(16 - bit_temp) + ")" + suffix)
                                        else:
                                            raise ValueError
                                    except:
                                        if map_item != len(desc) - 1:
                                            dac_item = str(
                                                int(hex_to_bin_16bit(G.col("ADDR_MAP", "CP Data[31:0]")[z].split("_")[1])[
                                                        (bit_temp - 1)]))
                                            bit_temp += 1
                                            f.write("(" + dac_item + "<<" + str(16 - (bit_temp)) + ")+")
                                        else:
                                            dac_item = str(
                                                int(hex_to_bin_16bit(G.col("ADDR_MAP", "CP Data[31:0]")[z].split("_")[1])[
                                                        (bit_temp - 1)]))
                                            f.write(dac_item + ";")
                            f.write("\n\n")

            f.write("  }\n")
            f.write("  //fflush(stdout);\n\n\n")

            if _recipe_module_enabled(recipe_modules, "SETVPOSP"):
                set_all_final_vposp(f)
                copy_file(G.BASE_DIR + "\\pat_temp\\" + "set_all_final_vposp" + ".pat",
                          G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")

            if not _recipe_module_enabled(recipe_modules, "NMLOOP"):
                f.write("}\n\n")
                return

            f.write("  POWER_ON(" + G.col("FLOW", "Vcc")[j].upper() + ");\n\n")
            f.write(
                '  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="enter_fbist_mode";\n  JUDGE_PAT(enter_fbist_mode,__enter_fbist_mode); \n\n')
            # wake up
            f.write("  for(I=0;I<10;I++)\n  {\n")

            for nm_name in G.nm_patterns("bulk erase all", "bulk program 00 all"):
                copy_file(G.BASE_DIR + "\\pat_temp\\" +
                          nm_name + ".pat",
                          G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                f.write('    TEST_NO(TEST_NUM);  DATALOG_MSG = "' +
                        nm_name + '";  \n    JUDGE_PAT(' +
                        nm_name + ',__' +
                        nm_name + ');\n\n')
            f.write("  }\n\n")

            for nm_name in G.nm_patterns("bulk erase all"):
                copy_file(G.BASE_DIR + "\\pat_temp\\" +
                          nm_name + ".pat",
                          G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                f.write('  TEST_NO(TEST_NUM);  DATALOG_MSG = "' +
                        nm_name + '";  \n  JUDGE_PAT(' +
                        nm_name + ',__' +
                        nm_name + ');\n\n')


            f.write('  POWER_OFF();\n\n')
            f.write("  POWER_ON(" + G.col("FLOW", "Vcc")[j].upper() + ");\n\n")
            f.write(
                '  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="enter_fbist_mode";\n  JUDGE_PAT(enter_fbist_mode,__enter_fbist_mode); \n\n')
            f.write("  for(I=0;I<25;I++)\n  {\n")
            for nm_name in G.nm_patterns("bulk erase NM", "bulk program PCKB NM"):
                copy_file(G.BASE_DIR + "\\pat_temp\\" +
                          nm_name + ".pat",
                          G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                f.write('    TEST_NO(TEST_NUM);  DATALOG_MSG = "' +
                        nm_name + '";  \n    JUDGE_PAT(' +
                        nm_name + ',__' +
                        nm_name + ');\n\n')

            for nm_name in G.nm_patterns("bulk erase NM", "bulk program NCKB NM"):
                copy_file(G.BASE_DIR + "\\pat_temp\\" +
                          nm_name + ".pat",
                          G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                f.write('    TEST_NO(TEST_NUM);  DATALOG_MSG = "' +
                        nm_name + '";  \n    JUDGE_PAT(' +
                        nm_name + ',__' +
                        nm_name + ');\n\n')

            f.write("  }\n\n")

            f.write('  POWER_OFF();\n  //POWER_DOWN_FAIL_SITE_X(MODE_B);\n\n')
            f.write("}\n\n")


def margin_write(code_name, f, j):
    bake_space = ""
    if G.col("FLOW", "type")[j] == "margin" and code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[j]:
        item = G.col("FLOW", "item")[j]
        type0 = item.split("_")[0]            # Vte / Vtp
        is_vte = type0.lower()[-1] == "e"     # 擦除(负压) / 编程(正压)
        enter = type0.lower()
        MarginVar = type0.title() + "Margin"
        if is_vte:
            vt_start, vt_end = "-0.2V", "-1.8V"
            jv_low, jv_high = "vt_end", "vt_start"
        else:
            vt_start, vt_end = "0.2V", "1.0V"
            jv_low, jv_high = "vt_start", "vt_end"

        f.write(item.title() + "()\n{\n")
        f.write("  TEST_NUM=" + str((j + 1) * 100) + ";\n" +
                '  TEST_NO( TEST_NUM);DATALOG_MSG="' + item + '"; \n\n')
        f.write("  int flag[MAX_SITE];\n  int finishSite;\n  VOLTAGE " + MarginVar + "[MAX_SITE];\n\n")
        if "bake" in item:
            f.write("  LUINT site_f;\n\n")
            f.write("  SOCKET_INC(FRZ_OFF)\n  {\n    site_f[SOCKET]=0;\n    if(CP" +
                    str(int(code_name[G.i].split("_")[-1][-1]) - 1) +
                    "_BAKEID_FLAG[SOCKET]==1) \n    {\n      site_f[SOCKET]=1;\n    }\n  }\n\n")

        f.write("  if(VTEN_FLAG)\n  {\n")

        # ===== 二分法 margin（替代原 75 步线性扫描，参照 temp 下用户参考程序）=====
        # 每 site 在 [vt_start, vt_end] 区间二分 step 次逼近翻转电压；力压逐 site
        # 独立(FORCE_V_PPMU 在 SOCKET_INC 内)。区间/步数/力流写死参考值。
        f.write("    VOLTAGE vt_start = " + vt_start + ";\n" +
                "    VOLTAGE vt_end   = " + vt_end + ";\n" +
                "    int step = 7;\n" +
                "    VOLTAGE vt_temp[MAX_SITE],vt_finish[MAX_SITE],vt_st[MAX_SITE],vt_ed[MAX_SITE];\n\n")

        if "bake" in item:
            bake_space = "  "
            f.write("    SOCKET_SET(B:site_f,FRZ_OFF)\n    {\n")

        f.write(bake_space + "    POWER_ON(" + G.col("FLOW", "Vcc")[j].upper() + ");\n\n")
        f.write(bake_space + "    RELAY_ON(TP,PPMU_PDCL,2mS);\n\n")
        f.write(bake_space + '    TEST_NUM++;\n    ' + bake_space +
                'TEST_NO(TEST_NUM); DATALOG_MSG="enter_fbist_mode";\n    ' + bake_space +
                'JUDGE_PAT(enter_fbist_mode,__enter_fbist_mode); \n\n')
        f.write(bake_space + '    TEST_NO(TEST_NUM);  DATALOG_MSG = "enter_' + enter + '";  \n    ' +
                bake_space + 'JUDGE_PAT(enter_' + enter + ',__enter_' + enter + ');\n\n')

        # 初始化每 site 的二分区间
        f.write(bake_space + "    SOCKET_INC(FRZ_OFF)\n    " + bake_space + "{\n      " + bake_space +
                "vt_finish[SOCKET] = 0;\n      " + bake_space + "vt_st[SOCKET] = vt_start;\n      " +
                bake_space + "vt_ed[SOCKET] = vt_end;\n    " + bake_space + "}\n\n")

        # 二分循环
        f.write(bake_space + "    TEST_NUM++;\n    " + bake_space + "for(I=0;I<step;I++)\n    " +
                bake_space + "{\n")
        f.write(bake_space + "      SOCKET_INC(FRZ_OFF)\n      " + bake_space + "{\n        " +
                bake_space + "vt_temp[SOCKET] = (vt_st[SOCKET]+vt_ed[SOCKET])/2;\n        " +
                bake_space + "FORCE_V_PPMU(TP, vt_temp[SOCKET], ,@20uA, , 0mS);\n      " +
                bake_space + "}\n      " + bake_space + "WAIT(5mS);\n\n")
        # 复位本轮 plan 结果（兼容一条/多条 NM 读 pattern：任一失败即本轮 FAIL）
        f.write(bake_space + "      SOCKET_INC(FRZ_OFF)\n      " + bake_space + "{\n        " +
                bake_space + "PLAN_RESULT_MS[SOCKET] = PASS;\n      " + bake_space + "}\n\n")

        for u in range(len(G.col("NM_PATTERN", "used"))):
            if item.split("_")[1].upper() == "CKB":
                nm_pattern_name = "PCKB"
            elif item.split("_")[1].upper() == "CKBB":
                nm_pattern_name = "NCKB"
            else:
                nm_pattern_name = item.split("_")[1].upper()
            if "NM" in G.col("NM_PATTERN", "used")[u] and "bulk read" in G.col("NM_PATTERN", "used")[u] and nm_pattern_name in G.col("NM_PATTERN", "used")[u]:
                nm = G.col("NM_PATTERN", "Pattern name")[u].split(".")[0]
                copy_file(G.BASE_DIR + "\\pat_temp\\" + nm + ".pat",
                          G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                f.write(bake_space + '      TEST_NO(TEST_NUM);  DATALOG_MSG = "' + nm + '";\n      ' +
                        bake_space + 'JUDGE_PAT(' + nm + ',__' + nm + ');\n\n')
            nm_pattern_name = ""

        # 据本轮结果收窄区间：通过→抬下界，失败→压上界
        f.write(bake_space + "      SOCKET_INC(FRZ_OFF)\n      " + bake_space + "{\n        " +
                bake_space + "if(PLAN_RESULT_MS[SOCKET]==PASS)\n        " + bake_space +
                "{vt_st[SOCKET] = vt_temp[SOCKET];}\n        " + bake_space + "else\n        " +
                bake_space + "{vt_ed[SOCKET] = vt_temp[SOCKET];}\n      " + bake_space + "}\n")
        f.write(bake_space + "    }\n\n")

        # 终值 = 收敛区间中点，输出判定（判定上下限即搜索区间）
        f.write(bake_space + "    TEST_NUM++;\n    " + bake_space + "SOCKET_INC(FRZ_OFF)\n    " +
                bake_space + "{\n      " + bake_space + "PLAN_RESULT_MS[SOCKET] = PASS;\n      " +
                bake_space + "vt_finish[SOCKET] = (vt_st[SOCKET]+vt_ed[SOCKET])/2;\n      " +
                bake_space + MarginVar + "[SOCKET] = vt_finish[SOCKET];\n      " +
                bake_space + 'TEST_NO( TEST_NUM);DATALOG_MSG="' + item + '";\n      ' +
                bake_space + 'JUDGE_VARIABLE (SOCKET, ' + MarginVar + '[SOCKET], ' + jv_low + ', ' +
                jv_high + ', "' + item + '");\n    ' + bake_space + "}\n\n")

        f.write(bake_space + "    FORCE_V_PPMU(TP, 0V, ,@20uA, , 2mS);\n    " + bake_space +
                "RELAY_OFF(TP,PPMU_PDCL,2mS);\n\n")
        f.write(bake_space + '    POWER_OFF();\n    ' + bake_space + '//POWER_DOWN_FAIL_SITE_X(MODE_B);\n\n')
        if "bake" in item:
            f.write("    }\n\n")
        f.write("  }\n\n")
        f.write("}\n\n")


def os_write(code_name, f, plan):
    j = plan.row
    if code_name[G.i].split("_")[-1] == plan.cp:
        # f.write("set_send_data" + "(")
        # f.write("int a)\n{\n")
        # f.write("  SOCKET_INC(FRZ_OFF)\n  {\n\n")
        # f.write("    TEMP = a; //data\n")
        # f.write(
        #     "    for(J=0;J<=7;J++)\n    {\n      BIT[J] = 0;\n      BIT[J] = TEMP%2;\n      TEMP = TEMP/2;\n    }\n\n")
        # f.write("    for(J=7;J>=0;J--)\n    {\n")
        # f.write("      if(BIT[J]==0)\n      {\n         WRITE_PAT_MEM(SOCKET, " + str(
        #     list(VERSION["GET PIN"])[i]) + ", " +
        #         str(list(VERSION["GET PIN"])[i]) + "_Send_mulX" + ":data_num+" + '7' + '-J, ,"0");\n      }\n')
        # f.write("      else\n      {\n         WRITE_PAT_MEM(SOCKET, " + str(list(VERSION["GET PIN"])[i]) + ", " +
        #         str(list(VERSION["GET PIN"])[i]) + "_Send_mulX" + ":data_num+" + '7' + '-J, ,"1");\n      }\n')
        # f.write("    }\n\n")
        # f.write("  }\n\n")
        # f.write(
        #     '  TEST_NUM++;\n  TEST_NO(TEST_NUM);  DATALOG_MSG ="' + str(
        #         list(VERSION["GET PIN"])[i]) + "_Send_mulX" + '";\n  JUDGE_PAT(' +
        #     str(list(VERSION["GET PIN"])[i]) + "_Send_mulX" + ",__" + str(
        #         list(VERSION["GET PIN"])[i]) + "_Send_mulX" + ");\n\n}\n\n\n")
        # copy_file(
        #     G.BASE_DIR + "\\pat_temp\\" + str(
        #         list(VERSION["GET PIN"])[i]) + "_Send_mulX" + ".pat",
        #     G.OUT_DIR + "\\" + code_name[i] + "\\pat")
        for cyc in range(len(G.col("FLOW", "item"))):
            if _flow_item_key(G.col("FLOW", "item")[cyc]) == "bor_verify" and code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[cyc]:
                f.write("set_bor_data" + "(")
                f.write("int a)\n{\n")
                f.write("  SOCKET_INC(FRZ_OFF)\n  {\n\n")
                f.write("    TEMP = a; //data\n")
                f.write(
                    "    for(J=0;J<=2;J++)\n    {\n      BIT[J] = 0;\n      BIT[J] = TEMP%2;\n      TEMP = TEMP/2;\n    }\n\n")
                f.write("    for(J=2;J>=0;J--)\n    {\n")
                f.write("      if(BIT[J]==0)\n      {\n         WRITE_PAT_MEM(SOCKET, " + str(
                    G.col("VERSION", "GET PIN")[G.i]) + ', set_bor_verify_dac:e_data+2-J, ,"0");\n      }\n')
                f.write("      else\n      {\n         WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "GET PIN")[G.i]) + ', set_bor_verify_dac:e_data+2-J, ,"1");\n      }\n')
                f.write("    }\n\n")
                f.write("  }\n\n")
                f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM);  DATALOG_MSG ="set_bor_verify_dac";\n  JUDGE_PAT(set_bor_verify_dac,__set_bor_verify_dac);\n\n}\n\n\n')
                copy_file(
                    G.BASE_DIR + "\\pat_temp\\set_bor_verify_dac.pat",
                    G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
        f.write(
            "//////////////////////////////////////////////////////////////////\n//\n"
            + "//           Main Flow\n//\n//////////////////////////////////////////////////////////////////\n\n")
        f.write(plan.item.title() + "()\n{\n")
        f.write("  TEST_NUM=" + str(
            (j + 1) * 100) + ";\n" + '  TEST_NO( TEST_NUM);DATALOG_MSG="' + plan.item + '"; \n\n')

        cp_no = plan.cp
        has_kp = cp_has_kp_relay(cp_no)
        f.write("  LEVELS(RST_LVL,3mS);\n")
        if (cp_no == "CP1" or cp_no == "CP2") and has_kp:
            f.write("  SET_CBIT(KP, ON, 2mS);\n")
        f.write("  RELAY_ON(IO_ALLPINS,PDCL,2mS);\n  FORCE_V_MLDPS(" + vcc_rails_str(code_name[G.i]) + ",0V,@6V,@500mA,200mA,NORM,ON,2mS);\n\n  PIN_MODE(IO_ALLPINS,F0,EDGE,MASK,IO_ON,OFF);\n\n")
        f.write("  ///////////////////////OSTEST pins/////////////////////\n")
        f.write("  RELAY_OFF(IO_ALLPINS, PDCL, 2mS);\n")
        f.write("  RELAY_ON(IO_ALLPINS,PPMU,2mS);\n\n")
        f.write('  TEST_NUM++;\n  TEST_NO( TEST_NUM); DATALOG_MSG = "OSTEST pins";\n\n')
        f.write("  FORCE_I_PPMU(IO_ALLPINS-TP, -100uA, @200uA, ,2V, -2V ,3mS);\n")
        f.write("  JUDGE_V_PPMU(IO_ALLPINS-TP, -1.2V, -0.2V, 2mS);\n\n")
        f.write(
            "  FORCE_I_PPMU(IO_ALLPINS-TP, 0uA, @200uA, ,2V, -2V ,3mS);\n  FORCE_V_PPMU(IO_ALLPINS-TP,0.0V,,@200uA,,3mS);\n\n")
        f.write("  ///////////////////////TP pin/////////////////////\n\n")
        f.write('  TEST_NUM++;\n  TEST_NO( TEST_NUM); DATALOG_MSG = "OSTEST TP";\n\n')
        f.write("  FORCE_I_PPMU(TP, -100uA, @200uA, ,2V, -2V ,3mS);\n")
        f.write("  JUDGE_V_PPMU(TP, -3.0V, -0.2V, 2mS);\n\n")
        f.write("  FORCE_I_PPMU(TP, 0uA, @200uA, ,2V, -2V ,3mS);\n")
        f.write("  FORCE_V_PPMU(TP,0.0V,,@200uA,,3mS);\n\n")

        f.write("  RELAY_OFF(IO_ALLPINS, PPMU, 2mS);\n")
        f.write("  RELAY_ON(IO_ALLPINS,PDCL,2mS);\n\n")

        if cp_no == "CP1" or cp_no == "CP2":
            f.write("  FORCE_V_MLDPS(" + vcc_rails_str(code_name[G.i]) + ",0V,@6V,@500mA,200mA,NORM,OFF,2mS);\n")
            if has_kp:
                f.write("  SET_CBIT(KP, OFF, 2mS);\n")
            f.write("  PIN_MODE(IO_ALLPINS,NRZ,EDGE,ENABLE,IO_OFF,NORM);\n\n")
            cp_cur = plan.cp
            vccpinname = VCC_pin_rebuild(cp_cur)
            # 站点从 Site 列推导（site N -> S(N-1)），按偶/奇拆 F0/S0 与 F1/S1（对齐 golden：
            # 偶站点=F0/S0、奇站点=F1/S1）。旧逻辑按 trace 含 "F" 找站点——单 site 电源是纯通道号
            # 无 F -> 站点空 -> SOCKET_SET( 残缺；闭合又写死第 64 个站点(FS_flage==63)，非 128-site 全失配。
            pin_cp = G.col("PIN_DEC_128", "CP NO")
            pin_site = G.col("PIN_DEC_128", "Site")
            all_s = sorted({int(pin_site[u]) - 1 for u in range(len(pin_cp)) if pin_cp[u] == cp_cur})
            s_groups = [([s for s in all_s if s % 2 == 0], "F0/S0"),
                        ([s for s in all_s if s % 2 == 1], "F1/S1")]

            def socket_set_open(sites, label):
                # 'SOCKET_SET(S0|S2|...,FRZ_OFF)//*<label> closed\n  {\n'；每 32 个站点换行；空组回 ''
                if not sites:
                    return ""
                out = "  SOCKET_SET("
                for idx, s in enumerate(sites):
                    out += "S" + str(s)
                    if idx == len(sites) - 1:
                        out += ",FRZ_OFF)//*" + label + " closed\n  {\n"
                    elif (idx + 1) % 32 == 0:
                        out += "|\n  "
                    else:
                        out += "|"
                return out

            f.write("  VOLTAGE vmeas[MAX_SITE];\n")  # 只声明一次（多电源轨复用，避免 C2086 重复定义）
            for v in range(len(vccpinname)):
                rail = vccpinname[v]
                f.write("  /////////////////////// " + rail + " pin /////////////////////\n")
                f.write("  for(I=0;I<MAX_SITE;I++) vmeas[I] = 0;\n")
                for sites, label in s_groups:
                    block = socket_set_open(sites, label)
                    if not block:
                        continue  # 该继电器组无站点（如单 site 只有偶站点 S0，奇组为空）则跳过
                    f.write("  /////////////////////// " + rail + " pin " + label + " closed /////////////////////\n")
                    f.write(block)
                    if has_kp:
                        f.write("    SET_CBIT(KP, ON, 2mS);\n")
                    f.write("    FORCE_I_MLDPS(" + rail + ",-100uA,@25mA,@6V,2V,NORM,ON,2mS);\n\n")
                    f.write('    TEST_NUM++;\n    TEST_NO( TEST_NUM);DATALOG_MSG = "OS_TEST_VDD";\n')
                    f.write("    //MEAS_V_MLDPS(" + rail + ",2mS, 4, AVE, 50uS);\n    MEAS_V_MLDPS(" + rail + ",2mS);\n")
                    f.write("    FORCE_I_MLDPS(" + rail + ",0uA,@25mA,@6V,2V,NORM,ON,2mS);\n\n")
                    f.write("    SOCKET_INC(FRZ_OFF)\n    {\n      vmeas[SOCKET]=RESULT_MLDPS_EX(SOCKET," + rail + ");\n    }\n")
                    f.write('    JUDGE_VARIABLE_MS(vmeas,-1.2V,-0.2V,"OS_TEST_VDD");\n\n')
                    f.write("    FORCE_V_MLDPS(" + rail + ",0V,@6V,@500mA,500mA,NORM,OFF,2mS);\n")
                    if has_kp:
                        f.write("    SET_CBIT(KP, OFF, 2mS);\n")
                    f.write("  }\n\n")
        if plan.cp == "CP3":
            vccpinname = VCC_pin_rebuild("CP3")
            for v in range(len(vccpinname)):
                f.write("  /////////////////////// " + vccpinname[v] + " pin /////////////////////\n")
                f.write("  FORCE_V_MLDPS(" + vccpinname[v] + ",0V,@6V,@500mA,100mA,NORM,OFF,2mS);\n\n")
                f.write("  FORCE_I_MLDPS(" + vccpinname[v] + ",-100uA,@25mA,@6V,2V,NORM,ON,2mS);\n\n")
                f.write('  TEST_NUM++;\n  TEST_NO( TEST_NUM);DATALOG_MSG = "OS_TEST_' + vccpinname[v] + '";\n\n')
                f.write("  JUDGE_V_MLDPS(" + vccpinname[v] + ",-1.2V,-0.09V,2mS);\n\n")
                f.write("  FORCE_I_MLDPS(" + vccpinname[v] + ",0uA,@25mA,@6V,2V,NORM,ON,2mS);\n")
                f.write("  FORCE_I_MLDPS(" + vccpinname[v] + ",0uA,@500mA,@6V,2V,NORM,ON,2mS);\n\n")
                f.write("  FORCE_V_MLDPS(" + vccpinname[v] + ",0V,@6V,@500mA,100mA,NORM,OFF,2mS);\n\n")
                f.write("  PIN_MODE(IO_ALLPINS,NRZ,EDGE,ENABLE,IO_OFF,NORM);\n  RELAY_OFF(IO_ALLPINS,PDCL,2mS);\n\n")

        f.write('}\n\n')


def _fmt_ns(value_ns):
    """把纳秒浮点值格式化成 Chroma TIME 字面量，自动按数量级选 nS/uS/mS
    （2026-07-10 用户裁决：32768Hz 半周期原来死用 nS 会写成 15258.79nS 这种
    没必要的长数字，改成按量级选单位——15.26uS 更可读，CRAFT 本身认
    nS/uS/mS 三种）。保留 2 位小数。"""
    if value_ns >= 1e6:
        return ("%.2f" % (value_ns / 1e6)) + "mS"
    if value_ns >= 1e3:
        return ("%.2f" % (value_ns / 1e3)) + "uS"
    return ("%.2f" % value_ns) + "nS"


def _emit_clock_force_plan(f, plan, pat_dir):
    """输出已经计算好的 Chroma 外灌时钟计划。TMU 直接外灌的管脚用
    `PIN_MODE`+`FRUN_CLK`+`FRUN_CLK_MODE(...,ON)`；同 PMU 组降级的那根改成
    `JUDGE_PAT` 启动 `<pin>_clkloop` 无限翻转 pattern（`clock_force_pattern_created`
    生成）。"""
    for pin, info in plan.items():
        f.write("  PIN_MODE(" + pin + ",FCLK,EDGE,MASK,IO_ON,OFF);\n")
        if info["mode"] == "tmu":
            half_ns = clock_force.half_period_ns(info["freq_hz"])
            f.write("  FRUN_CLK(" + pin + "," + _fmt_ns(2 * half_ns) + ",0nS," + _fmt_ns(half_ns) + ");\n")
    for pin, info in plan.items():
        if info["mode"] == "tmu":
            f.write("  FRUN_CLK_MODE(" + pin + ",1,0,ON);\n")
    for pin, info in plan.items():
        if info["mode"] == "pattern":
            name = pin.lower() + "_clkloop"
            copy_file(G.BASE_DIR + "\\pat_temp\\" + name + ".pat", pat_dir)
            f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + name + '";\n'
                    '  JUDGE_PAT(' + name + ',__' + name + ');\n\n')
    f.write("\n")
    return plan


def _emit_clock_force(f, z, pat_dir):
    """FLOW 行适配器；执行计划由 `clock_force.chroma_row_plan` 计算。"""
    return _emit_clock_force_plan(f, clock_force.chroma_row_plan(z), pat_dir)


def _emit_clock_force_off_plan(f, plan):
    """关闭一份 Chroma 外灌时钟计划。"""
    if any(info["mode"] == "pattern" for info in plan.values()):
        f.write("  PAT_CONTINUE();\n")
    for pin, info in plan.items():
        if info["mode"] == "tmu":
            f.write("  FRUN_CLK_MODE(" + pin + ",1,0,OFF);\n")
    f.write("\n")


def _clock_force_judge(f, z, pat_dir, meas_pin, target, downgraded):
    """RCC/RTC 外灌时钟行 "T" token 收尾（2026-07-07 用户裁决，只针对 Chroma）：
    - 不降级（该行涉及的管脚全部走 TMU）：跟普通 keil 行 UNIT=="pat" 一样，跑
      `<pin1><pin2>_compare_<target>` 数字比较 pattern（母本这类行 UNIT 列填 "/"，
      不能靠 UNIT 判断，故单独判 `downgraded`）。
    - 降级（同 PMU 组占用了 pattern 引擎，不能再跑别的 pattern）：改成对 meas pin
      逐根做 PPMU 电压量测——force 0uA 测电压，按 target 字符串逐位判断该管脚该是
      高还是低：高电平 `VCC-0.6~VCC+0.1`（VCC 取该行 Vcc 列变量名，如 VCC_TYP）、
      低电平固定 0.1V~0.5V；量测完对每个降级管脚各调一次 `PAT_CONTINUE()` 打断
      `_clkloop` pattern。"""
    if not downgraded:
        cmp_name = meas_pin.replace("+", "").lower() + "_compare_" + str(target).strip().lower()
        copy_file(G.BASE_DIR + "\\pat_temp\\" + cmp_name + ".pat", pat_dir)
        f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + cmp_name + '";\n'
                '  JUDGE_PAT(' + cmp_name + ',__' + cmp_name + ');\n\n')
        return
    vcc_name = G.col("FLOW", "Vcc")[z].upper()
    pins = [p.strip() for p in str(meas_pin).split("+")]
    target_str = str(target).strip().upper()
    for idx, pin in enumerate(pins):
        if target_str[idx] == "H":
            low, high = vcc_name + "-0.6", vcc_name + "+0.1"
        else:
            low, high = "0.1V", "0.5V"
        # 2026-07-14 B3 真实验证修复：同组降级电压兜底原来用 MLDPS
        # （FORCE_I_MLDPS/JUDGE_V_MLDPS），但 meas pin 是普通 IO 管脚（PA13/PA11），
        # 不是 MLDPS 电源单元管脚——CRAFT 报 "not a MLDPS pin type"。之前只
        # monkeypatch 检查生成串、没真编译，未暴露。按本函数注释（PPMU force
        # 0uA 测电压）改回 PPMU，配 RELAY_ON/OFF 接通 PPMU 继电器（对齐项目 IO
        # 管脚 PPMU 量测范式）。
        f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + pin + '_clk_v";\n')
        f.write("  RELAY_ON(" + pin + ", PPMU_PDCL, 2mS);\n")
        f.write("  FORCE_I_PPMU(" + pin + ", 0uA, @200uA, ,6V, -2V ,3mS);\n")
        f.write("  JUDGE_V_PPMU(" + pin + "," + low + "," + high + ",2mS);\n")
        f.write("  RELAY_OFF(" + pin + ", PPMU_PDCL, 2mS);\n\n")
    for pin, info in clock_force.chroma_row_plan(z).items():
        if info["mode"] == "pattern":
            f.write("  PAT_CONTINUE();\n")
    f.write("\n")


def _emit_reset(f, pat_dir):
    """T 收尾的 reset_pattern（2026-07-21 抽出：原 clk_forced/elec_forced/纯 T 三处逐字
    重复的 copy+JUDGE_PAT，收口成一个函数；调用点各自的 emit_reset/降级条件不变）。"""
    copy_file(G.BASE_DIR + "\\pat_temp\\reset_pattern.pat", pat_dir)
    f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="reset_pattern";\n'
            '  JUDGE_PAT(reset_pattern,__reset_pattern);\n\n')


def _keil_step_write(f, z, get_pin, pat_dir, emit_reset=True, entry_only=False,
                     emit_banner=True, step_override=None):
    """写一个 sub 行（一个功耗模式）的紧凑 step 记法：FLOW.step 形如 "HL-1-2-3-W20-T"，
    '-' 分隔 token（母本直接填字面量配方，工具不做抽象名/模板展开，改配方=改这格+重新生成）：
      电平序列 — H/L 任意长度，逐字符一段电平（H/HL/HH/LL/HLHL…）；紧跟
                "-<数字><ns|us|ms>" 指定每段宽度（默认 5ms），生成
                <触发管脚>_<序列小写>_<宽度> pattern（2026-07-15 泛化自原写死的 HL）
      裸整数N — 发送第 N 个选码（<触发管脚>_send_num:s<hex(N)>_ST -> s<hex(N)>_SP，
                标签对写法对齐 S100 的 st/sp 风格（用户裁决 2026-07-02），见
                get_pin_patterns_created；标签不能以 "0x" 开头——CRAFT 标识符按 C
                规则解析，数字开头会被当数字字面量、报 Undefined symbol，实测坐实）
      W<n>   — WAIT(<n>mS)
      T      — 收尾判定，两种互斥写法（按该行 UNIT 列区分，用户裁决 2026-07-03）：
               ① UNIT!="pat"（如 uA/V）→ 测量：FORCE_V_MLDPS(<meas pin>,...)（复用
                  Force_Judge 按 target 量级自动选钳位档位@5uA/@25uA/@250uA/@2.5mA，
                  不写死档位）+ JUDGE_I_MLDPS(<meas pin>,low,high,...)（low/high 取
                  该行 low_range(%)/high_range(%) 列，calc_limit 三种写法；
                  DATALOG_MSG 用该行 sub 列命名；force 的 pin 取 meas pin 列，不写死 VCC）；
               ② UNIT=="pat"→ 管脚对比较：不测量，改 JUDGE_PAT 跑一个比较 pattern，
                  沿用老 hex_verify_item_write 的命名习惯——meas pin 列填 "<PIN1>+<PIN2>"、
                  target 列填 "HH"/"LL"/"LH"，拼成 <pin1><pin2小写去+>_compare_<target小写>
                  （如 meas pin="PA13+PA14"、target="HH" → pa13pa14_compare_hh；该 pattern
                  需真实向量内容，源缺失时 copy_file 兜底占位假 pat，同 S0 流程）。
               两种写法末尾都统一收尾 reset_pattern（`emit_reset=False` 时跳过，
               2026-07-10 用户裁决：`mode=swd` 复用本函数处理 T token 时不要
               reset_pattern——swd 组多个 sub 共享一次上下电，中途 reset 没
               意义，只在整组收尾时可能需要，不是每个 sub 各来一次）。
    触发管脚（HL/裸数字两个 token 用的 <触发管脚>_force_1_0/<触发管脚>_send_num）默认
    取 VERSION.GET PIN；行内可选前缀 "<PIN>:" 覆盖触发管脚，如 "PA0:HL-1-2-3-T"
    （用户裁决 2026-07-02；覆盖用的管脚须是该程序 pin.dec 里已声明的真实管脚，否则
    CRAFT 编译期报错——与 GET PIN 本就有的要求一致，母本填写时自行注意）。

    FLOW.step **按真实换行（Alt+Enter）分组**（用户裁决 2026-07-03）：一个格子可以
    填多组独立的 "<PIN>:"-前缀 + "-" token 序列，每组各自独立、各自可选带 W/T，如
    "PA0:HL-1-2-3\nPB2:HL-W10-T"（第一组只触发发码不测量，第二组换管脚触发后等待
    再测量判定）。不带换行的单行格子行为完全不变（等价于只有一组）。

    FV/FI 列：纯数字（如 "3.3"）→ 当字面电压值,补 V 单位；非数字（如 "VCC_MAX"）→
    直接当全局变量名字面量用，不加引号不加单位。
    未识别的 token 直接抛异常——母本填错要生成期立刻暴露，不静默跳过。

    三个引用的 pattern（<触发管脚>_force_1_0/<触发管脚>_send_num/reset_pattern）各自
    在用到的 token 分支里 copy_file 进本程序 pat/（2026-07-02 修：此前从未拷贝，
    keil 组因另一处入口行 bug 一直没真正生成过，这个缺口才没暴露；源缺失时 copy_file
    兜底生成占位假 pat；<触发管脚>_* 两个 seed 由 get_pin_patterns_created 按
    VERSION.GET PIN 与 FLOW 里出现过的 "<PIN>:" 前缀去重后各生成一份）。"""
    fv_fi = str(G.col("FLOW", "FV/FI")[z]).strip()
    try:
        float(fv_fi)
        force_value = fv_fi + "V"
    except ValueError:
        force_value = fv_fi.upper()
    meas_pin = G.col("FLOW", "meas pin")[z]
    unit = G.col("FLOW", "UNIT")[z]
    target = G.col("FLOW", "target")[z]
    sub_name = G.col("FLOW", "sub")[z]
    # DATALOG_MSG/注释横幅用的可读标签：sub=="/"（没填子步骤名）时退回用 item
    # 本身，避免真实生成结果里出现裸 "/" 这种没有辨识度的 DATALOG_MSG（2026-07-10
    # 用户从真实生成结果里发现的问题）。
    label = G.col("FLOW", "item")[z] if str(sub_name).strip() == "/" else sub_name

    if emit_banner:   # swd_pattern_write 把 sub 横幅提到配置 pattern 之前写，这里跳过（2026-07-21）
        f.write("  ////////////////////" + label.lower() + "////////////////////\n")
    clk_forced = False    # 本行 step 是否出现过 "F" token 且走外灌时钟（2026-07-07）
    clk_plan = None
    clk_downgraded = False
    clk_stopped = False   # 本行 step 是否已由 "FS" token 显式停过外灌（2026-07-23）
    elec_forced = False   # 本行 step 是否出现过 "F" token 且走电压/电流 force（2026-07-07）
    step_value = G.col("FLOW", "step")[z] if step_override is None else step_override
    step_lines = str(step_value).strip().splitlines()
    for step_str in step_lines:
        step_str = step_str.strip()
        if not step_str:
            continue  # 容忍多余空行（如末尾换行）
        if ":" in step_str:
            trig_pin, step_str = step_str.split(":", 1)
            trig_pin = trig_pin.strip()
            is_default_trig = False
        else:
            trig_pin = get_pin
            is_default_trig = True
        # 触发/发码 pattern 的显示前缀：默认触发用 `Trig`（不烤死真实 pin 名），显式用该 pin
        # （2026-07-24 用户裁决）。真实 pin=trig_pin 仍用于 HEADER 驱动脚 / CLK PIN 撞车判断。
        disp = trig_disp(trig_pin, is_default_trig)
        tokens = step_str.split("-")
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if entry_only and tok == "T":
                # 2026-07-13 真实母本反例（DC 扫描族）：DC 行 step 列会带字面
                # "T"（如 "HL-222-1-T"），但 DC 自己的 PPMU 组循环是
                # dc_scan_test_write 另外写的代码，不能让这里的 T 分支再跑一次
                # 判定（会拿 DC 行"target 留空"的惯例硬 float() 崩掉）——
                # entry_only=True 时只处理入口触发 token（电平序列/裸数字/W），
                # 遇到 T 直接跳过。
                i += 1
                continue
            if tok == "F":
                # 2026-07-07 用户裁决扩展："F" 不再只等于外灌时钟——FV/FI 是
                # "<PIN>:<freq>" 格式才走外灌时钟，否则按 UNIT 列走 force 电压/电流
                # （V→force 电流、后面 T 处 judge 电压；uA→force 电压、后面 T 处
                # judge 电流，同 `Force_Judge` 既有的 V/uA 判据，"A" in type 即 uA 系）。
                if clock_force.is_clock_force_cell(G.col("FLOW", "FV/FI")[z]):
                    clk_plan = _emit_clock_force(f, z, pat_dir)
                    clk_forced = True
                    clk_downgraded = any(info["mode"] == "pattern" for info in clk_plan.values())
                else:
                    # 2026-07-16 FV/FI 通用增强：parse_fv_fi 解析 <PIN>:值+... force 多 pin
                    # （force pin 与 measure pin 解耦），每个 force pin 自动识别——电源轨→
                    # MLDPS（现有 Power_Test，判电流走后面 elec_forced 的 T）/ IO→PPMU（如 TK
                    # 前置 force PA0，保持到下电，收尾走 T 的 UNIT=cap capture）。
                    cp_z = G.col("FLOW", "CP NO")[z]
                    for fpin, fval in parse_fv_fi(G.col("FLOW", "FV/FI")[z], meas_pin):
                        if _force_src(fpin, cp_z) == "PPMU":
                            try:
                                float(fval)
                                fval_w = fval + "V"
                            except ValueError:
                                fval_w = fval
                            f.write("  RELAY_ON(" + fpin + ", PPMU_PDCL, 2mS);\n")
                            f.write("  FORCE_V_PPMU(" + fpin + ", " + fval_w + ", ,@2mA, , 2mS);\n\n")
                        else:
                            Force_Judge(unit, fpin, fval, float(target), 0, "FORCE", "MLDPS",
                                        G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z], f)
                            elec_forced = True
            elif LEVEL_SEQ_RE.fullmatch(tok):
                # 电平序列 token（H/L 任意长度，逐字符一段；2026-07-15 泛化自原写死的
                # "HL"）。紧跟的 <数字><ns|us|ms> 是每段宽度（消费掉 i+=1），不写=默认
                # 5ms。2026-07-06 用户裁决：触发管脚若跟 VERSION.CLK PIN(SCLK) 撞车，
                # POWER_ON 已把它设成 RZ，拿它当普通 GPIO 触发前须先切回 NRZ。
                levels = tok
                rpt, width_str = default_pulse()
                if i + 1 < len(tokens) and parse_pulse_width(tokens[i + 1]):
                    rpt, width_str = parse_pulse_width(tokens[i + 1])
                    i += 1
                pat_real = level_seq_pat_name(trig_pin, levels, width_str)   # 种子按真实 pin
                pat_name = level_seq_pat_name(disp, levels, width_str)       # 引用/文件用显示名
                if trig_pin == G.col("VERSION", "CLK PIN")[G.i]:
                    f.write("  PIN_MODE(      " + trig_pin + ", NRZ, EDGE, ENABLE, IO_NRZ, OFF);\n")
                copy_trig_pat(pat_real, pat_name, pat_dir)
                f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + pat_name + '";\n'
                        '  JUDGE_PAT(' + pat_name + ',__' + pat_name + ');\n\n')
            elif tok.isdigit():
                n = int(tok)
                hh = decimal_to_hex(n)
                base = disp + "_send_num"
                copy_trig_pat(trig_pin + "_send_num", base, pat_dir)
                f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + base + ':s'
                        + hh + '_ST";\n  JUDGE_PAT(' + base + ':s' + hh + '_ST,'
                        + base + ':s' + hh + '_SP);\n\n')
            elif tok.startswith("W") and tok[1:].isdigit():
                f.write("  WAIT(" + tok[1:] + "mS);\n")
            elif tok == "T" and clk_forced:
                # RCC/RTC 外灌时钟行的收尾判定：不看 UNIT 列（母本这类行 UNIT 一律填
                # "/"），只看这一行实际有没有降级到 pattern（2026-07-07 用户裁决）。
                if clk_stopped:
                    # 2026-07-23：FS 已提前停外灌、引擎空出 → 跑 compare pattern 判定
                    # （等价非降级路径），不再 PPMU 兜底、不再重复停时钟。
                    _clock_force_judge(f, z, pat_dir, meas_pin, target, False)
                    if emit_reset:
                        _emit_reset(f, pat_dir)
                else:
                    _clock_force_judge(f, z, pat_dir, meas_pin, target, clk_downgraded)
                    for pin, info in clk_plan.items():
                        if info["mode"] == "tmu":
                            f.write("  FRUN_CLK_MODE(" + pin + ",1,0,OFF);\n")
                    if not clk_downgraded and emit_reset:
                        _emit_reset(f, pat_dir)
            elif tok == "T" and elec_forced:
                # F 处已经 force 过（电压或电流，按 UNIT 判），这里只做 judge。
                # **不能**复用 `Force_Judge` 的 "JUDGE"+"MLDPS" 分支——那个分支对
                # MLDPS 的判定方向是反的（"A" in type 时吐 JUDGE_V_MLDPS 却配 uA
                # 单位限值，自相矛盾；PPMU 分支反而是对的，MLDPS 这条之前没人真的
                # 调用过、是个从没暴露的既有 bug，2026-07-07 生成实测坐实）。照抄
                # Power_Test 原来验证过的写法：uA→JUDGE_I_MLDPS，否则（V）→
                # JUDGE_V_MLDPS，自己按 unit 判断，不经过那条坏分支。
                low = calc_limit(target, G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z], True)
                high = calc_limit(target, G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z], False)
                f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + label.lower() + '";\n')
                if "A" in str(unit):
                    f.write("  JUDGE_I_MLDPS(" + meas_pin + "," + str(low) + unit + "," + str(high) + unit + ",2mS,32,AVE,50uS,,);\n\n")
                else:
                    f.write("  JUDGE_V_MLDPS(" + meas_pin + "," + str(low) + unit + "," + str(high) + unit + ",2mS,32,AVE,50uS,,);\n\n")
                if emit_reset:
                    _emit_reset(f, pat_dir)
            elif tok == "T":
                # capture 组判断看 cap_cfg（非 "/"）而非 UNIT——多行 capture 组只有入口行
                # 填 UNIT=cap，后续行 UNIT 留空但 cap_cfg 都填了（2026-07-16）。
                if str(G.col("FLOW", "cap_cfg")[z]).strip() != "/":
                    _sram_cap_judge(f, z, pat_dir)
                elif str(unit).strip().lower() == "pat":
                    cmp_name = meas_pin.replace("+", "").lower() + "_compare_" + str(target).strip().lower()
                    copy_file(G.BASE_DIR + "\\pat_temp\\" + cmp_name + ".pat", pat_dir)
                    f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + cmp_name + '";\n'
                            '  JUDGE_PAT(' + cmp_name + ',__' + cmp_name + ');\n\n')
                elif str(unit).strip() in ("Hz", "KHz", "MHz"):
                    # 2026-07-10 用户裁决：频率量测收尾判定跟入口是 keil 还是 swd 无关，
                    # 只看 UNIT 列，两条入口路径共用这一分支（复用 Force_Judge 已在
                    # trim_item_write 验证过的 FREQ 逻辑，不新造一套）。真实参考
                    # V_PY2409V1B_.../Lsi_Verify()：SET_TFTM_MODE(pin,SCHMITT_ON)→
                    # JUDGE_FREQ(...)→SET_TFTM_MODE(pin,SCHMITT_OFF)。
                    # 若 FV/FI 是外灌时钟格式（如 Hse/PLL_HSE32 的 PD0:32MHz）→ 先灌时钟再测、
                    # 测完关（2026-07-21 修：外灌只被 "F" token 消费，Hse step 只有 "T"，这里按
                    # FV/FI 自动补，与 S100 对齐）；内部时钟项（FV/FI="/"）不灌、逐字不变。
                    _clkp = _emit_clock_force(f, z, pat_dir) if clock_force.is_clock_force_cell(G.col("FLOW", "FV/FI")[z]) else None
                    Force_Judge(unit, meas_pin, force_value, float(target), 0, "FORCE", "FREQ",
                                G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z], f)
                    f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + label.lower() + '";\n')
                    Force_Judge(unit, meas_pin, force_value, float(target), 0, "JUDGE", "FREQ",
                                G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z], f)
                    f.write("  SET_TFTM_MODE(" + meas_pin + ", SCHMITT_OFF);\n\n")
                    if _clkp:   # 关外灌（TMU 直灌走 FRUN_CLK_MODE OFF，同 clk_forced-T 收尾；
                        for _cpin, _cinfo in _clkp.items():   # Hse/PLL_HSE32=32MHz≥600kHz 均 TMU）
                            if _cinfo["mode"] == "tmu":
                                f.write("  FRUN_CLK_MODE(" + _cpin + ",1,0,OFF);\n")
                        f.write("\n")
                else:
                    low = calc_limit(target, G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z], True)
                    high = calc_limit(target, G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z], False)
                    Force_Judge(unit, meas_pin, force_value, float(target), 0, "FORCE", "MLDPS",
                                G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z], f)
                    f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + label.lower() + '";\n')
                    f.write("  JUDGE_I_MLDPS(" + meas_pin + "," + str(low) + unit + "," + str(high) + unit + ",2mS,32,AVE,50uS,,);\n\n")
                if emit_reset and str(G.col("FLOW", "cap_cfg")[z]).strip() == "/":
                    _emit_reset(f, pat_dir)
            elif tok == "RP":
                # 2026-07-23：上下电循环（re-power）——中途成对下电+上电（如 IWDG 多次
                # 上下电）。首次上电/末次下电由测试项外壳负责，这里只出中途的一对。
                f.write("  POWER_OFF();\n  POWER_ON(" + G.col("FLOW", "Vcc")[z].upper() + ");\n\n")
            elif tok == "FS":
                # 2026-07-23：停外灌（force stop）——F 启外灌、等待完后显式停（如 RTC/RCC
                # "等 200ms 再停"）。降级 pattern 先 PAT_CONTINUE 打断 loop、TMU 直灌走
                # FRUN_CLK_MODE OFF；停后置 clk_stopped，后续 T 走 compare pattern 判定。
                # 无 FS 的老 RCC/RTC 路径 clk_stopped 恒 False、逐字不变，零回归。
                if clk_forced and clk_plan and not clk_stopped:
                    if clk_downgraded:
                        f.write("  PAT_CONTINUE();\n")
                    for _fpin, _finfo in clk_plan.items():
                        if _finfo["mode"] == "tmu":
                            f.write("  FRUN_CLK_MODE(" + _fpin + ",1,0,OFF);\n")
                    f.write("\n")
                    clk_stopped = True
            else:
                raise ValueError(
                    "keil_pattern_write: 未识别的 step token '" + tok + "'（sub=" + sub_name + "）")
            i += 1


def _sram_cap_judge(f, z, pat_dir):
    """keil `T` token 的 `UNIT=cap` 分支（2026-07-16）：SRAM capture（cap_cfg pattern 段
    =SRAM）。同 item+CP 的 keil 组**入口行生成整组 capture**、后续行跳过（capture 是整组
    一次读多个数）。单行=统一 limit（count=bit/位宽 个数同判据，alias 自动编号）；多行=
    逐数 limit（每行一个数、各自 low/high、alias=sub，对齐 C_COMPARE 的 LOG_ALIAS）。
    Read_SRAM 全局函数由 startup 生成、sram_cpature.pat 是手工种子。"""
    from program_gen.platforms.chroma.capture import parse_cap_cfg, capture_sram_write
    item_z = G.col("FLOW", "item")[z]
    cp_z = G.col("FLOW", "CP NO")[z]
    grp = _keil_group_rows(item_z, cp_z)
    if z != grp[0]:
        return   # 后续行，capture 已在入口行生成
    cap_cfg_val = str(G.col("FLOW", "cap_cfg")[z]).strip()
    if cap_cfg_val.split("-")[0].upper() != "SRAM":
        raise ValueError("keil T(UNIT=cap) 目前只支持 cap_cfg=SRAM，实际 '" + cap_cfg_val + "'")
    product = G.col("VERSION", "product name")[G.i]
    sub_z = str(G.col("FLOW", "sub")[z]).strip()
    stem = item_z if sub_z == "/" else sub_z
    _pat, base, total_bits, bpd = parse_cap_cfg(cap_cfg_val, product, stem)
    count = total_bits // bpd
    low_col = G.col("FLOW", "low_range(%)")
    high_col = G.col("FLOW", "high_range(%)")
    sub_col = G.col("FLOW", "sub")
    if len(grp) == 1:
        entries = [(low_col[z], high_col[z], sub_z + "_" + str(k)) for k in range(count)]
        uniform, banner = True, (sub_z if sub_z != "/" else item_z)
    else:
        entries = [(low_col[r], high_col[r], str(sub_col[r]).strip()) for r in grp]
        uniform, banner = False, None
    copy_file(G.BASE_DIR + "\\pat_temp\\sram_cpature.pat", pat_dir)
    capture_sram_write(f, base, entries, uniform, banner)


def _keil_group_rows(item_name, cp_no):
    """同 item+CP 下所有 mode=="keil" 的行号（verify 类型），按 FLOW 原始顺序。"""
    flow_item = G.col("FLOW", "item")
    flow_cp = G.col("FLOW", "CP NO")
    flow_type = G.col("FLOW", "type")
    flow_mode = G.col("FLOW", "mode")
    return [k for k in range(len(flow_item))
            if flow_item[k] == item_name and flow_cp[k] == cp_no
            and flow_type[k] == "verify" and flow_mode[k] == "keil"]


def _hex_rows(item_name, cp_no):
    """同 item+CP 下所有 mode=="hex" 的行号（verify 类型），按 FLOW 原始顺序。"""
    flow_item = G.col("FLOW", "item")
    flow_cp = G.col("FLOW", "CP NO")
    flow_type = G.col("FLOW", "type")
    flow_mode = G.col("FLOW", "mode")
    return [k for k in range(len(flow_item))
            if flow_item[k] == item_name and flow_cp[k] == cp_no
            and flow_type[k] == "verify" and flow_mode[k] == "hex"]


def _hex_row(item_name, cp_no):
    """同 item+CP 下第一个 mode=="hex" 的行号，没有则 None（Power_Test 单 hex 场景用）。"""
    rows = _hex_rows(item_name, cp_no)
    return rows[0] if rows else None


def _hex_keil_ordered_rows(item_name, cp_no):
    """同 item+CP 下所有 mode in (hex,keil) 的行号（verify 类型），按 FLOW 原始顺序
    （可能交替，如 Sram_Test：hex-keil-hex-keil）。"""
    flow_item = G.col("FLOW", "item")
    flow_cp = G.col("FLOW", "CP NO")
    flow_type = G.col("FLOW", "type")
    flow_mode = G.col("FLOW", "mode")
    return [k for k in range(len(flow_item))
            if flow_item[k] == item_name and flow_cp[k] == cp_no
            and flow_type[k] == "verify" and flow_mode[k] in ("hex", "keil")]


def _hex_step_body_write(code_name, f, z, pat_dir):
    """写一个 hex 行的函数体片段（不含 HEADER/TEST_NO/花括号）：固定三步
    enter_fbist_mode+set_all_final_vposp+<step 列 pattern 名>，自己一次独立
    POWER_ON/POWER_OFF 包住（多 hex 交替合并场景用，见 _multi_hex_keil_write；
    与 hex_download_write 主体里单 hex 场景的写法逻辑等价，未合并复用以免改动
    已验证过的 Power_Test 单 hex 路径）。"""
    pattern_name = G.col("FLOW", "step")[z]
    copy_file(G.BASE_DIR + "\\pat_temp\\enter_fbist_mode.pat", pat_dir)
    copy_file(G.BASE_DIR + "\\pat_temp\\set_all_final_vposp.pat", pat_dir)
    copy_file(G.BASE_DIR + "\\pat_temp\\" + pattern_name + ".pat", pat_dir)
    f.write("  POWER_ON(" + G.col("FLOW", "Vcc")[z].upper() + ");\n\n")
    f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="enter_fbist_mode";\n'
            '  JUDGE_PAT(enter_fbist_mode,__enter_fbist_mode); \n\n')
    f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="set_all_final_vposp";\n'
            '  JUDGE_PAT(set_all_final_vposp,__set_all_final_vposp); \n\n')
    f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + pattern_name + '";\n'
            '  JUDGE_PAT(' + pattern_name + ',__' + pattern_name + '); \n\n')
    f.write('  POWER_OFF();\n  //POWER_DOWN_FAIL_SITE_X(MODE_B);\n\n')


def _keil_sub_step_write(code_name, f, z, pat_dir):
    """写一个 keil sub 行的函数体片段：自己独立一次 POWER_ON/POWER_OFF 包住单个 sub
    （多 hex 交替合并场景用，见 _multi_hex_keil_write；与 _keil_group_body_write
    的"多 sub 共享一次电"不同，这里每个 sub 各自独立开关一次）。"""
    get_pin = G.col("VERSION", "GET PIN")[G.i]
    f.write("  POWER_ON(" + G.col("FLOW", "Vcc")[z].upper() + ");\n\n")
    _keil_step_write(f, z, get_pin, pat_dir)
    f.write("  POWER_OFF();\n")


def _multi_hex_keil_write(code_name, f, item_name, ordered_rows, pat_dir):
    """同 item+CP 下有 >=2 个 mode=="hex" 行（如 Sram_Test：下载-测试-下载-测试交替）
    时的合并写法：按 FLOW 原始顺序把所有 hex/keil 行依次写进同一个函数体，**每行
    各自独立一次 POWER_ON/POWER_OFF**（用户裁决 2026-07-03——与 Power_Test 那种
    "1 hex 独立+N keil 共享一次电"场景不同、含义也不同：这里是"下载紧跟着验证"的
    配对流程，用户要求每步都独立开关电，不共享）。只在整组最早一行触发（用户报的
    真实 bug：hex_download_write 原先对同 item+CP 下每一个 hex 行都无条件各开一次
    函数，多个 hex 行会重复定义同名函数，CRAFT 报 error C2084；改成两个 writer
    都判定"该 item+CP 有≥2 个 hex 行"时统一让路给本函数，只有 z==ordered_rows[0]
    才真正生成，其余行 return）。"""
    entry_z = ordered_rows[0]
    flow_mode = G.col("FLOW", "mode")
    f.write(item_name.title() + "()\n{\n")
    f.write("  TEST_NUM=" + str((entry_z + 1) * 100) + ";\n"
            + '  TEST_NO(TEST_NUM);DATALOG_MSG="' + item_name + '"; \n\n')
    for row in ordered_rows:
        if flow_mode[row] == "hex":
            _hex_step_body_write(code_name, f, row, pat_dir)
        else:
            _keil_sub_step_write(code_name, f, row, pat_dir)
    f.write("}\n\n")


def _keil_group_body_write(f, keil_rows, pat_dir):
    """写 keil 组的函数体片段（不含 HEADER/TEST_NO/花括号）：一次 POWER_ON 包住全部
    sub 步骤（功耗模式间靠 pattern 内部切档，不物理断电），末尾一次 POWER_OFF。"""
    get_pin = G.col("VERSION", "GET PIN")[G.i]
    f.write("  POWER_ON(" + G.col("FLOW", "Vcc")[keil_rows[0]].upper() + ");\n\n")
    for sub_cyc in keil_rows:
        _keil_step_write(f, sub_cyc, get_pin, pat_dir)
    f.write("  POWER_OFF();\n")


def _swd_group_rows(item_name, cp_no):
    """同 item+CP 下所有 mode=="swd" 的行号（verify 类型），按 FLOW 原始顺序——
    对齐 `_keil_group_rows` 的写法，swd 组同理支持多个 sub 行共用一次上下电。"""
    flow_item = G.col("FLOW", "item")
    flow_cp = G.col("FLOW", "CP NO")
    flow_type = G.col("FLOW", "type")
    flow_mode = G.col("FLOW", "mode")
    return [k for k in range(len(flow_item))
            if flow_item[k] == item_name and flow_cp[k] == cp_no
            and flow_type[k] == "verify" and flow_mode[k] == "swd"]


def _swd_pat_name(product_name, item_name, sub_z):
    # pattern 名来源：sub 列填了才用 sub（同 item 一样"去掉最后一个下划线段"，
    # 2026-07-10 用户裁决），sub=="/" 时退回用 item——对齐 keil 那边 sub 列的
    # 既有语义（sub="/"=没有子步骤名，用 item 本身）。
    # 2026-07-10 实测发现修复：单词 sub（如 F2 的 "Low"/"High"，没有下划线）
    # 按"去掉最后一段"会把唯一那段整个丢光变成空字符串——只有 >1 段时才丢最后
    # 一段，单段直接原样用。
    sub_raw = str(G.col("FLOW", "sub")[sub_z]).strip()
    name_src = item_name if sub_raw == "/" else sub_raw
    parts = name_src.split("_")
    stem = "_".join(parts[:-1]) if len(parts) > 1 else parts[0]
    return product_name + "_SWD_" + stem


def swd_pattern_write(code_name, f, z, pat_dir):
    """type=="verify" and mode=="swd" 项：固定 pattern link 机制（2026-07-10
    用户裁决，见 .Codex/handoffs/2026-07-07-analog-test-family-classification-
    decision.md 续11）——pattern 名固定公式 "<VERSION.product name>_SWD_<item
    或 sub 去掉最后一个下划线段>"，`JUDGE_PAT` link 该 pattern 作为入口，取代
    keil 的 HL+发码触发。入口之后的 step 列 token 处理（F 外灌时钟、T 收尾
    判定，含频率量测分支）跟 keil 共用 `_keil_step_write`——swd 行的 step 列
    不会出现 HL/裸数字 token（那是 keil 触发专用），天然只处理它遇到的 token。

    **同 item+CP 下多个 sub 行共用一次上下电**（2026-07-10 用户裁决，对齐
    `_keil_group_body_write` 的写法，区别于每行各自 `POWER_ON`/`POWER_OFF`）：
    只在整组入口行（该 item+CP 第一个 swd 行）触发一次，内部循环所有同组行，
    每行各自 link 自己的 pattern + 走 `_keil_step_write` 的 F/T 处理。
    **且不写 reset_pattern**（`emit_reset=False`，用户裁决区别于 keil：组内
    途中不需要复位，只有整组收尾 `POWER_OFF` 前才可能需要，这里选择完全不写，
    对齐真实参考 `Lsi_Verify` 等 swd 例子里没有中途 reset 的现状）。

    F3/F4 若也走 swd 但需要按 item 名反查多个按序 pattern（类似 SCAN/Mbist 的
    discover_patterns，向量内容非人工填的固定 pattern 名），需要另外设计，
    不复用这个函数。"""
    if not (code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[z]
            and G.col("FLOW", "type")[z] == "verify" and G.col("FLOW", "mode")[z] == "swd"):
        return
    item_name = G.col("FLOW", "item")[z]
    cp_no = G.col("FLOW", "CP NO")[z]
    swd_rows = _swd_group_rows(item_name, cp_no)
    if z != swd_rows[0]:
        return  # 非整组入口，让路（同组更早的行已经处理过）

    product_name = G.col("VERSION", "product name")[G.i]
    get_pin = G.col("VERSION", "GET PIN")[G.i]

    f.write(item_name.title() + "()\n{\n")
    f.write("  TEST_NUM=" + str((swd_rows[0] + 1) * 100) + ";\n"
            + '  TEST_NO(TEST_NUM);DATALOG_MSG="' + item_name + '"; \n\n')
    f.write("  POWER_ON(" + G.col("FLOW", "Vcc")[swd_rows[0]].upper() + ");\n\n")

    for sub_z in swd_rows:
        pat_name = _swd_pat_name(product_name, item_name, sub_z)
        copy_file(G.BASE_DIR + "\\pat_temp\\" + pat_name + ".pat", pat_dir)
        # sub 横幅放在配置 pattern 之前（该 sub 从这里开始更清晰，2026-07-21 用户要求）；
        # _keil_step_write 里的横幅用 emit_banner=False 关掉，避免重复。
        _sub = str(G.col("FLOW", "sub")[sub_z]).strip()
        _label = G.col("FLOW", "item")[sub_z] if _sub == "/" else _sub
        f.write("  ////////////////////" + _label.lower() + "////////////////////\n")
        f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + pat_name + '";\n'
                '  JUDGE_PAT(' + pat_name + ',__' + pat_name + ');\n\n')
        _keil_step_write(f, sub_z, get_pin, pat_dir, emit_reset=False, emit_banner=False)

    f.write("  POWER_OFF();\n}\n\n")


def keil_pattern_write(code_name, f, z):
    """type=="verify" and mode=="keil" 项：header+sub 多行机制（跟 hex_download_write
    同一套约定，"keil" 走 mode 列区分、不占用 type，对齐 fbist/hex 也是靠 mode 分流的
    既有惯例）——FLOW 里同一个 item 名连续填好几行（含入口行自己），每行代表一个子步骤
    （这里是一个功耗模式），`sub` 列给子步骤命名。只在"入口行"（本 CP 内该 item 名
    第一次出现的 keil 行）触发一次，内部重新扫一遍 FLOW，把所有同 item+CP 的 keil 行
    当子步骤逐个写进同一个函数体，不会每行各开一个函数。

    若同 item+CP 下恰好有 1 行 mode=="hex"（同一测试项块里先下载 hex 再测功耗，用户
    裁决 2026-07-02：hex 单独一次上下电、keil 组共享一次上下电），则整块（含本 keil
    组）由 `hex_download_write` 一次性写出（避免生成两个同名函数），这里直接让路。
    若同 item+CP 下有 >=2 行 mode=="hex"（如 Sram_Test：下载-测试交替好几轮），走
    另一套合并（见 _multi_hex_keil_write，每行各自独立上下电，用户裁决 2026-07-03），
    这里同样让路。"""
    if not (code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[z]
            and G.col("FLOW", "type")[z] == "verify" and G.col("FLOW", "mode")[z] == "keil"):
        return
    item_name = G.col("FLOW", "item")[z]
    cp_no = G.col("FLOW", "CP NO")[z]
    hex_rows = _hex_rows(item_name, cp_no)
    if len(hex_rows) >= 2:
        ordered = _hex_keil_ordered_rows(item_name, cp_no)
        if z != ordered[0]:
            return  # 非整组入口，让路
        pat_dir = G.OUT_DIR + "\\" + code_name[G.i] + "\\pat"
        _multi_hex_keil_write(code_name, f, item_name, ordered, pat_dir)
        return
    if hex_rows:
        return  # 该 item+CP 有唯一 1 个 hex 行，整块交给 hex_download_write（Power_Test 场景）
    keil_rows = _keil_group_rows(item_name, cp_no)
    if z != keil_rows[0]:
        return  # 非入口行（同组更早已经处理过），跳过避免重复开函数

    pat_dir = G.OUT_DIR + "\\" + code_name[G.i] + "\\pat"
    f.write(item_name.title() + "()\n{\n")
    f.write("  TEST_NUM=" + str((z + 1) * 100) + ";\n" + '  TEST_NO(TEST_NUM);DATALOG_MSG="' + item_name + '"; \n\n')
    _keil_group_body_write(f, keil_rows, pat_dir)
    f.write("}\n\n")


def hex_download_write(code_name, f, z):
    """type=="verify" and mode=="hex" 项：下载 hex，固定跑一个 pattern，流程写死三步——
    enter_fbist_mode + set_all_final_vposp + <step 列给的 pattern 名>（step 列直接填字面量
    pattern 名，不是 keil 那套紧凑记法），自己一次上下电包住这三步。

    若同 item+CP 下恰好有 1 行 mode=="hex"、且还有 mode=="keil" 的行（同一测试项块：
    先下载 hex 再测功耗，用户裁决 2026-07-02），则这里是整块的入口——hex 三步写完、
    上下电收尾后，紧接着把 keil 组（sub 多行聚合、自己再一次独立上下电）内嵌进同一
    个函数体，避免生成两个同名函数（原先 hex 行与 keil 组的 item 名相同时，
    keil_pattern_write 的"入口行"扫描不区分 mode，会把 keil 组整个吞掉——见
    keil_pattern_write 文档字符串）。没有 keil 行时行为不变（一行 FLOW = 一个独立
    测试项，不做聚合）。

    若同 item+CP 下有 >=2 行 mode=="hex"（如 Sram_Test：下载-测试交替好几轮，用户报
    的真实 bug——原先这里对每个 hex 行都无条件各开一次函数，多行同名重定义，CRAFT
    报 error C2084），改走 _multi_hex_keil_write 那套合并（每行各自独立上下电，
    用户裁决 2026-07-03），只在整组入口触发。"""
    if not (code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[z]
            and G.col("FLOW", "type")[z] == "verify" and G.col("FLOW", "mode")[z] == "hex"):
        return
    item_name = G.col("FLOW", "item")[z]
    cp_no = G.col("FLOW", "CP NO")[z]
    pat_dir = G.OUT_DIR + "\\" + code_name[G.i] + "\\pat"

    if len(_hex_rows(item_name, cp_no)) >= 2:
        ordered = _hex_keil_ordered_rows(item_name, cp_no)
        if z != ordered[0]:
            return  # 非整组入口，让路
        _multi_hex_keil_write(code_name, f, item_name, ordered, pat_dir)
        return

    pattern_name = G.col("FLOW", "step")[z]
    # 三步各自引用的 pattern 都要拷进本程序 pat/（enter_fbist_mode 虽已在 startup 无条件拷过一次，
    # 这里仍显式拷，使本函数不依赖其它 writer 的调用顺序副作用；源缺失时 copy_file 兜底生成占位假 pat）
    copy_file(G.BASE_DIR + "\\pat_temp\\enter_fbist_mode.pat", pat_dir)
    copy_file(G.BASE_DIR + "\\pat_temp\\set_all_final_vposp.pat", pat_dir)
    copy_file(G.BASE_DIR + "\\pat_temp\\" + pattern_name + ".pat", pat_dir)

    f.write(item_name.title() + "()\n{\n")
    f.write("  TEST_NUM=" + str((z + 1) * 100) + ";\n" + '  TEST_NO(TEST_NUM);DATALOG_MSG="' + item_name + '"; \n\n')
    f.write("  POWER_ON(" + G.col("FLOW", "Vcc")[z].upper() + ");\n\n")
    f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="enter_fbist_mode";\n'
            '  JUDGE_PAT(enter_fbist_mode,__enter_fbist_mode); \n\n')
    f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="set_all_final_vposp";\n'
            '  JUDGE_PAT(set_all_final_vposp,__set_all_final_vposp); \n\n')
    f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + pattern_name + '";\n'
            '  JUDGE_PAT(' + pattern_name + ',__' + pattern_name + '); \n\n')
    f.write('  POWER_OFF();\n  //POWER_DOWN_FAIL_SITE_X(MODE_B);\n\n')

    keil_rows = _keil_group_rows(item_name, cp_no)
    if keil_rows:
        _keil_group_body_write(f, keil_rows, pat_dir)
    f.write("}\n\n")


def main_write(code_name, f, j):
    # pgm_nm
    if G.col("FLOW", "type")[j] == "main" and code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[j]:
        f.write(G.col("FLOW", "item")[j].title() + "()\n{\n")
        f.write("  TEST_NUM=" + str(
            (j + 1) * 100) + ";\n" + '  TEST_NO( TEST_NUM);DATALOG_MSG="' + G.col("FLOW", "item")[j].lower() + '"; \n\n')
        f.write("  POWER_ON(" + G.col("FLOW", "Vcc")[j].upper() + ");\n\n")
        f.write(
            '  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="enter_fbist_mode";\n  JUDGE_PAT(enter_fbist_mode,__enter_fbist_mode); \n\n')
        f.write(
            '  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="set_all_final_vposp";\n  JUDGE_PAT(set_all_final_vposp,__set_all_final_vposp); \n\n')
        if G.col("FLOW", "item")[j].split("_")[0] != "Disturb":
            for u in range(len(G.col("NM_PATTERN", "used"))):

                if G.col("FLOW", "item")[j].lower() == "initialization":
                    nm_pattern_name = "bulk read FF NM"
                elif G.col("FLOW", "item")[j].split("_")[1] == "PgmCKB":
                    nm_pattern_name = "PCKB"
                elif G.col("FLOW", "item")[j].split("_")[1] == "PgmCKBB":
                    nm_pattern_name = "NCKB"
                elif G.col("FLOW", "item")[j].split("_")[1] == "Pgm00":
                    nm_pattern_name = "00"
                else:
                    nm_pattern_name = G.col("FLOW", "item")[j].split("_")[1]
                try:
                    if G.col("FLOW", "item")[j].split("_")[1] == "Erase" and G.col("NM_PATTERN", "used")[
                        u] == "bulk read FF NM":
                        copy_file(G.BASE_DIR + "\\pat_temp\\" +G.col("NM_PATTERN", "Pattern name")[u].split(".")[0]+ ".pat",
                                  G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                        f.write('  TEST_NO(TEST_NUM);  DATALOG_MSG = "' +
                                G.col("NM_PATTERN", "Pattern name")[u].split(".")[
                                    0] + '";  \n  JUDGE_PAT(' +
                                G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ',__' +
                                G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ');\n\n')
                except:
                    None

                if "NM" in G.col("NM_PATTERN", "used")[u] and "bulk" in G.col("NM_PATTERN", "used")[
                    u] and nm_pattern_name in G.col("NM_PATTERN", "used")[u] \
                        or G.col("NM_PATTERN", "used")[u] == "bulk erase NM":
                    copy_file(
                        G.BASE_DIR + "\\pat_temp\\" + G.col("NM_PATTERN", "Pattern name")[u].split(".")[
                            0] + ".pat",
                        G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                    f.write('  TEST_NO(TEST_NUM);  DATALOG_MSG = "' +
                            G.col("NM_PATTERN", "Pattern name")[u].split(".")[
                                0] + '";  \n  JUDGE_PAT(' +
                            G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ',__' +
                            G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ');\n\n')

                nm_pattern_name = ""
        if G.col("FLOW", "item")[j].split("_")[0] == "Disturb":
            if G.col("FLOW", "item")[j].split("_")[1] != "CKB":
                for nm_name in G.nm_patterns("bulk erase NM"):
                    copy_file(G.BASE_DIR + "\\pat_temp\\" +nm_name+ ".pat",
                              G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                    f.write('  TEST_NO(TEST_NUM);  DATALOG_MSG = "' +
                            nm_name + '";  \n  JUDGE_PAT(' +
                            nm_name + ',__' +
                            nm_name + ');\n\n')
                vref = 0
                for u in range(len(G.col("NM_PATTERN", "used"))):
                    if "NM" in G.col("NM_PATTERN", "used")[u] and "bulk" in G.col("NM_PATTERN", "used")[
                        u] and G.col("FLOW", "item")[j].split("_")[1] in G.col("NM_PATTERN", "used")[u]:
                        copy_file(G.BASE_DIR + "\\pat_temp\\" +G.col("NM_PATTERN", "Pattern name")[u].split(".")[0]+ ".pat",
                                  G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                        while vref < 2:
                            f.write('  TEST_NO(TEST_NUM);  DATALOG_MSG = "' +
                                    G.col("NM_PATTERN", "Pattern name")[u].split(".")[
                                        0] + '";  \n  JUDGE_PAT(' +
                                    G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ',__' +
                                    G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ');\n\n')
                            vref += 1

                for u in range(len(G.col("NM_PATTERN", "used"))):
                    if "NM" in G.col("NM_PATTERN", "used")[u] and "bulk read" in G.col("NM_PATTERN", "used")[
                        u] and G.col("FLOW", "item")[j].split("_")[1] in G.col("NM_PATTERN", "used")[u]:
                        copy_file(G.BASE_DIR + "\\pat_temp\\" +G.col("NM_PATTERN", "Pattern name")[u].split(".")[0]+ ".pat",
                                  G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                        f.write('  TEST_NO(TEST_NUM);  DATALOG_MSG = "' +
                                G.col("NM_PATTERN", "Pattern name")[u].split(".")[
                                    0] + '";  \n  JUDGE_PAT(' +
                                G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ',__' +
                                G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ');\n\n')

            if G.col("FLOW", "item")[j].split("_")[1] == "CKB":
                for u in range(len(G.col("NM_PATTERN", "used"))):
                    if G.col("NM_PATTERN", "used")[u] == "bulk erase NM":
                        copy_file(G.BASE_DIR + "\\pat_temp\\" +G.col("NM_PATTERN", "Pattern name")[u].split(".")[0]+ ".pat",
                                  G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                        f.write('  TEST_NO(TEST_NUM);  DATALOG_MSG = "' +
                                G.col("NM_PATTERN", "Pattern name")[u].split(".")[
                                    0] + '";  \n  JUDGE_PAT(' +
                                G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ',__' +
                                G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ');\n\n')
                    vref = 0

                    if G.col("NM_PATTERN", "used")[u] == "bulk program PCKB NM":
                        copy_file(G.BASE_DIR + "\\pat_temp\\" +G.col("NM_PATTERN", "Pattern name")[u].split(".")[0]+ ".pat",
                                  G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                        while vref < 2:

                            f.write('  TEST_NO(TEST_NUM);  DATALOG_MSG = "' +
                                    G.col("NM_PATTERN", "Pattern name")[u].split(".")[
                                        0] + '";  \n  JUDGE_PAT(' +
                                    G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ',__' +
                                    G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ');\n\n')
                            vref += 1
                        for u in range(len(G.col("NM_PATTERN", "used"))):
                            if "NM" in G.col("NM_PATTERN", "used")[u] and "bulk read" in G.col("NM_PATTERN", "used")[
                                u] and "PCKB" in G.col("NM_PATTERN", "used")[u]:
                                copy_file(G.BASE_DIR + "\\pat_temp\\" +
                                          G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ".pat",
                                          G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                                f.write('  TEST_NO(TEST_NUM);  DATALOG_MSG = "' +
                                        G.col("NM_PATTERN", "Pattern name")[u].split(".")[
                                            0] + '";  \n  JUDGE_PAT(' +
                                        G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ',__' +
                                        G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ');\n\n')

                        for u in range(len(G.col("NM_PATTERN", "used"))):
                            if G.col("NM_PATTERN", "used")[u] == "bulk erase NM":
                                copy_file(G.BASE_DIR + "\\pat_temp\\" +
                                          G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ".pat",
                                          G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                                f.write('  TEST_NO(TEST_NUM);  DATALOG_MSG = "' +
                                        G.col("NM_PATTERN", "Pattern name")[u].split(".")[
                                            0] + '";  \n  JUDGE_PAT(' +
                                        G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ',__' +
                                        G.col("NM_PATTERN", "Pattern name")[u].split(".")[
                                            0] + ');\n\n')
                            vref = 0

                            if G.col("NM_PATTERN", "used")[u] == "bulk program NCKB NM":
                                copy_file(G.BASE_DIR + "\\pat_temp\\" +
                                          G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ".pat",
                                          G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                                while vref < 2:
                                    f.write('  TEST_NO(TEST_NUM);  DATALOG_MSG = "' +
                                            G.col("NM_PATTERN", "Pattern name")[u].split(".")[
                                                0] + '";  \n  JUDGE_PAT(' +
                                            G.col("NM_PATTERN", "Pattern name")[u].split(".")[
                                                0] + ',__' +
                                            G.col("NM_PATTERN", "Pattern name")[u].split(".")[
                                                0] + ');\n\n')
                                    vref += 1
                                for u in range(len(G.col("NM_PATTERN", "used"))):
                                    if "NM" in G.col("NM_PATTERN", "used")[u] and "bulk read" in G.col("NM_PATTERN", "used")[
                                        u] and "NCKB" in G.col("NM_PATTERN", "used")[u]:
                                        copy_file(G.BASE_DIR + "\\pat_temp\\" +
                                                  G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ".pat",
                                                  G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                                        f.write('  TEST_NO(TEST_NUM);  DATALOG_MSG = "' +
                                                G.col("NM_PATTERN", "Pattern name")[u].split(".")[
                                                    0] + '";  \n  JUDGE_PAT(' +
                                                G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ',__' +
                                                G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ');\n\n')


        f.write('  POWER_OFF(); \n  //POWER_DOWN_FAIL_SITE_X(MODE_B);\n')
        f.write('}\n\n')


def vt_write(code_name, f, j):
    bake_space = ""
    if G.col("FLOW", "type")[j] == "VT" and code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[j]:
        copy_file(G.BASE_DIR + "\\pat_temp\\" + "enter_" + G.col("FLOW", "item")[j].split("_")[0].lower() + ".pat",
                  G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
        f.write(G.col("FLOW", "item")[j].title() + "()\n{\n")
        f.write("  TEST_NUM=" + str(
            (j + 1) * 100) + ";\n" + '  TEST_NO( TEST_NUM);DATALOG_MSG="' + G.col("FLOW", "item")[j].lower() + '"; \n\n')
        if "bake" in G.col("FLOW", "item")[j]:
            # "+bake_space+"
            # '+bake_space+'
            bake_space = "  "
            f.write("  LUINT site_f;\n\n")
            f.write(
                "  SOCKET_INC(FRZ_OFF)\n  {\n    site_f[SOCKET]=0;\n    if(CP" + str(int(code_name[G.i].split("_")[-1][
                                                                                             -1]) - 1) + "_BAKEID_FLAG[SOCKET]==1) \n    {\n      site_f[SOCKET]=1;\n    }\n  }\n\n")
            f.write("  SOCKET_SET(B:site_f,FRZ_OFF)\n  {\n")
        f.write(bake_space + "  POWER_ON(" + G.col("FLOW", "Vcc")[j] + ");\n\n")
        f.write(bake_space + "  RELAY_ON(TP,PPMU_PDCL,2mS);\n\n")
        f.write(bake_space +
                '  TEST_NUM++;\n  ' + bake_space + 'TEST_NO(TEST_NUM); DATALOG_MSG="enter_fbist_mode";\n  ' + bake_space + 'JUDGE_PAT(enter_fbist_mode,__enter_fbist_mode); \n\n')
        f.write(bake_space + '  TEST_NO(TEST_NUM);  DATALOG_MSG = "enter_' + G.col("FLOW", "item")[j].split("_")[0].lower() + '";  \n  ' + bake_space + 'JUDGE_PAT(enter_' + G.col("FLOW", "item")[j].split("_")[0].lower() + ',__enter_' + G.col("FLOW", "item")[j].split("_")[
                    0].lower() + ');\n\n')
        if "bake" in G.col("FLOW", "item")[j]:
            f.write(bake_space + "  FORCE_V_PPMU(TP, " + G.col("FLOW", "item")[j].split("_")[
                0].upper() + "_BAKE_VOLTAGE, ,@2uA, , 2mS); \n")
        else:
            f.write(bake_space + "  FORCE_V_PPMU(TP, " + G.col("FLOW", "item")[j].split("_")[
                0].upper() + "_VOLTAGE, ,@2uA, , 2mS); \n")
        f.write(bake_space + "\n")
        if G.col("FLOW", "item")[j].split("_")[0].lower()[-1] == "e":
            f.write(bake_space + "  BACKUP_PLAN_RESULT();\n")
        FLAG = 0
        for u in range(len(G.col("NM_PATTERN", "used"))):
            if G.col("FLOW", "item")[j].split("_")[1].upper() == "CKB":
                nm_pattern_name = "PCKB"
            elif G.col("FLOW", "item")[j].split("_")[1].upper() == "CKBB":
                nm_pattern_name = "NCKB"
            else:
                nm_pattern_name = G.col("FLOW", "item")[j].split("_")[1].upper()
            if "NM" in G.col("NM_PATTERN", "used")[u] and "bulk read" in G.col("NM_PATTERN", "used")[
                u] and nm_pattern_name in G.col("NM_PATTERN", "used")[u]:
                f.write(bake_space + '  TEST_NUM++;\n  ' + bake_space + 'TEST_NO(TEST_NUM);  DATALOG_MSG = "' +
                        G.col("NM_PATTERN", "Pattern name")[u].split(".")[
                            0] + '";  \n  ' + bake_space + 'JUDGE_PAT(' +
                        G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ',__' +
                        G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ');\n\n')
                FLAG = u
            nm_pattern_name = ""

        if G.col("FLOW", "item")[j].split("_")[0].lower() == "vte":
            f.write(bake_space + "  FAIL_REJUDGE(1,FRZ_OFF)\n  " + bake_space + "{\n")
            f.write(bake_space + '    TEST_NUM++;\n    ' + bake_space + 'TEST_NO(TEST_NUM);  DATALOG_MSG = "' +
                    G.col("NM_PATTERN", "Pattern name")[FLAG].split(".")[
                        0] + '";  \n    ' + bake_space + 'JUDGE_PAT(' +
                    G.col("NM_PATTERN", "Pattern name")[FLAG].split(".")[0] + ',__' +
                    G.col("NM_PATTERN", "Pattern name")[FLAG].split(".")[0] + ');\n\n')
            f.write(bake_space + "  }\n\n")
        f.write(
            bake_space + "  FORCE_V_PPMU(TP, 0V, ,@200uA, , 2mS);\n  " + bake_space + "RELAY_OFF(TP,PPMU_PDCL,2mS);\n\n")

        f.write(bake_space + '  POWER_OFF();\n  ' + bake_space + '//POWER_DOWN_FAIL_SITE_X(MODE_B);\n\n')
        if "bake" in G.col("FLOW", "item")[j]:
            f.write("  }\n\n")
        f.write("}\n\n")


def id_write(code_name, f, j, id_plan=None):
    if id_plan is not None and id_plan.role not in ("HARD_CHECK", "PRODUCE_GATE"):
        raise ValueError("Chroma ID writer requires HARD_CHECK or PRODUCE_GATE typed plan")
    if G.col("FLOW", "type")[j] == "id" and code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[j]:
        if "bake" in G.col("FLOW", "item")[j]:
            result = epr_pattern_capture("check", "cp"+str(int(code_name[G.i].split("_")[-1][-1])-1)+"_bake_id")
        else:
            result = epr_pattern_capture("check", "cp"+str(int(code_name[G.i].split("_")[-1][-1])-1)+ "_id")
        f.write(G.col("FLOW", "item")[j].title() + "()\n{\n")
        f.write("  TEST_NUM=" + str(
            (j + 1) * 100) + ";\n" + '  TEST_NO( TEST_NUM);DATALOG_MSG="' + G.col("FLOW", "item")[j].lower() + '"; \n\n')
        f.write("  POWER_ON(" + G.col("FLOW", "Vcc")[j].upper() + ");\n\n")
        f.write(
            '  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="enter_fbist_mode";\n  JUDGE_PAT(enter_fbist_mode,__enter_fbist_mode); \n\n')
        copy_file(G.BASE_DIR + "\\pat_temp\\" + result["read"] + ".pat",
                  G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
        f.write('  TEST_NO(TEST_NUM);  DATALOG_MSG = "' +
                result["read"] + '";  \n  JUDGE_PAT(' +
                result["read"] + ',__' +
                result["read"] + ');\n\n')

        if "bake" in G.col("FLOW", "item")[j]:
            f.write(
                "  SOCKET_INC(FRZ_OFF)\n  {\n    CP" + str(int(code_name[G.i].split("_")[-1][
                                                                   -1]) - 1) + "_BAKEID_FLAG[SOCKET]=0;\n    if(PLAN_RESULT_MS[SOCKET]==FAIL) \n    {\n      PLAN_RESULT_MS[SOCKET]=PASS;\n      CP" + str(
                    int(code_name[G.i].split("_")[-1][-1]) - 1) + "_BAKEID_FLAG[SOCKET]=1;\n    }\n\n  }\n\n")

        f.write('  POWER_OFF();\n  //POWER_DOWN_FAIL_SITE_X(MODE_B);\n\n')
        f.write("}\n\n")


def uid_write(code_name, f, j, read_bit, recipe_row=None, id_plan=None):
    if id_plan is not None and id_plan.role != "COMMIT_CLOSURE":
        raise ValueError("Chroma UID writer requires COMMIT_CLOSURE typed plan")
    temp_item_name = ""
    addr_map_item = []
    recipe_modules = _persistence_recipe_modules(recipe_row)
    build_uid_enabled = (
        recipe_modules is None
        and G.col("FLOW", "item")[j].strip().casefold() == "pgm_cp3id_read"
    ) or _recipe_module_enabled(recipe_modules, "BUILDUID")
    page_word = G.col("VERSION", "page word")[0]
    if G.col("FLOW", "type")[j] == "uid" and code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[j]:
        uid_write_dic = {}
        uid_write_item = []
        uid_write_num = []
        for u in range(len(G.col("FLOW", "UID"))):
            if G.col("FLOW", "UID")[u] == "yes":
                generated_item = generated_flow_item_name(G.FLOW, u)
                if G.col("FLOW", "type")[u] == "trim":
                    uid_write_item.append(generated_item + "[15:0]")
                else:
                    uid_write_item.append(generated_item)
                uid_write_num.append(int(G.col("FLOW", "CP NO")[u][-1]))

        # 同一个 item 名字可能在多个 CP 里都标 UID==yes（如 Hsi_8M_Trim 在 CP1/CP3 都是），
        # 同 temp_data_capture 里那份 uid_write_dic，改用 setdefault 保留第一次出现
        # （2026-07-06 修）。
        uid_write_dic = {}
        for name, num in zip(uid_write_item, uid_write_num):
            uid_write_dic.setdefault(name, num)
        # print(uid_write_dic)
        filtered_dict = {k: v for k, v in uid_write_dic.items() if "ts" not in k.lower()}
        value_count = pd.Series(filtered_dict).value_counts().to_dict()
        if build_uid_enabled:
            f.write("unsigned char const CRC8_TAB[256]={\n"
                    "    0x00, 0x07, 0x0E, 0x09, 0x1C, 0x1B, 0x12, 0x15, 0x38, 0x3F, 0x36, 0x31,\n"
                    "    0x24, 0x23, 0x2A, 0x2D, 0x70, 0x77, 0x7E, 0x79, 0x6C, 0x6B, 0x62, 0x65,\n"
                    "    0x48, 0x4F, 0x46, 0x41, 0x54, 0x53, 0x5A, 0x5D, 0xE0, 0xE7, 0xEE, 0xE9,\n"
                    "    0xFC, 0xFB, 0xF2, 0xF5, 0xD8, 0xDF, 0xD6, 0xD1, 0xC4, 0xC3, 0xCA, 0xCD,\n"
                    "    0x90, 0x97, 0x9E, 0x99, 0x8C, 0x8B, 0x82, 0x85, 0xA8, 0xAF, 0xA6, 0xA1,\n"
                    "    0xB4, 0xB3, 0xBA, 0xBD, 0xC7, 0xC0, 0xC9, 0xCE, 0xDB, 0xDC, 0xD5, 0xD2,\n"
                    "    0xFF, 0xF8, 0xF1, 0xF6, 0xE3, 0xE4, 0xED, 0xEA, 0xB7, 0xB0, 0xB9, 0xBE,\n"
                    "    0xAB, 0xAC, 0xA5, 0xA2, 0x8F, 0x88, 0x81, 0x86, 0x93, 0x94, 0x9D, 0x9A,\n"
                    "    0x27, 0x20, 0x29, 0x2E, 0x3B, 0x3C, 0x35, 0x32, 0x1F, 0x18, 0x11, 0x16,\n"
                    "    0x03, 0x04, 0x0D, 0x0A, 0x57, 0x50, 0x59, 0x5E, 0x4B, 0x4C, 0x45, 0x42,\n"
                    "    0x6F, 0x68, 0x61, 0x66, 0x73, 0x74, 0x7D, 0x7A, 0x89, 0x8E, 0x87, 0x80,\n"
                    "    0x95, 0x92, 0x9B, 0x9C, 0xB1, 0xB6, 0xBF, 0xB8, 0xAD, 0xAA, 0xA3, 0xA4,\n"
                    "    0xF9, 0xFE, 0xF7, 0xF0, 0xE5, 0xE2, 0xEB, 0xEC, 0xC1, 0xC6, 0xCF, 0xC8,\n"
                    "    0xDD, 0xDA, 0xD3, 0xD4, 0x69, 0x6E, 0x67, 0x60, 0x75, 0x72, 0x7B, 0x7C,\n"
                    "    0x51, 0x56, 0x5F, 0x58, 0x4D, 0x4A, 0x43, 0x44, 0x19, 0x1E, 0x17, 0x10,\n"
                    "    0x05, 0x02, 0x0B, 0x0C, 0x21, 0x26, 0x2F, 0x28, 0x3D, 0x3A, 0x33, 0x34,\n"
                    "    0x4E, 0x49, 0x40, 0x47, 0x52, 0x55, 0x5C, 0x5B, 0x76, 0x71, 0x78, 0x7F,\n"
                    "    0x6A, 0x6D, 0x64, 0x63, 0x3E, 0x39, 0x30, 0x37, 0x22, 0x25, 0x2C, 0x2B,\n"
                    "    0x06, 0x01, 0x08, 0x0F, 0x1A, 0x1D, 0x14, 0x13, 0xAE, 0xA9, 0xA0, 0xA7,\n"
                    "    0xB2, 0xB5, 0xBC, 0xBB, 0x96, 0x91, 0x98, 0x9F, 0x8A, 0x8D, 0x84, 0x83,\n"
                    "    0xDE, 0xD9, 0xD0, 0xD7, 0xC2, 0xC5, 0xCC, 0xCB, 0xE6, 0xE1, 0xE8, 0xEF,\n"
                    "    0xFA, 0xFD, 0xF4, 0xF3\n};\n\n")
            f.write("unsigned char GetCRC8(unsigned char  *ucPtr, unsigned char ucLen)\n{\n    unsigned char ucIndex;\n"
                    "    unsigned char ucCRC8 = 0;\n\n    while (ucLen--)\n    {\n        ucIndex = ucCRC8 ^ (*ucPtr++);\n"
                    "        ucCRC8 = CRC8_TAB[ucIndex];\n    }\n   return (~ucCRC8);\n}\n\n")

        f.write(G.col("FLOW", "item")[j].title() + "()\n{\n")
        f.write("  TEST_NUM=" + str((j + 1) * 100) + ";\n" + '  TEST_NO(TEST_NUM);DATALOG_MSG="' +
                G.col("FLOW", "item")[j].lower() + '"; \n\n')

        if build_uid_enabled:
            f.write(
                "  int day,month,year;\n  struct tm * tmptr;//get time\n  time_t secnow;\n  time(&secnow);\n  tmptr = localtime(&secnow);\n\n")
            f.write("  day = tmptr->tm_mday;\n  month = tmptr->tm_mon;\n  year = tmptr->tm_year;\n\n")
            f.write("  year = year-100;\n  month = month+1;\n\n")
            f.write(
                '  printf("WAFER ID = %s , LOT ID = %s(%XH %XH %XH %XH %XH %XH %XH)' + r'\n' + '",WAFERID,LOT_ID,LOT_ID[0],LOT_ID[1],LOT_ID[2],LOT_ID[3],LOT_ID[4],LOT_ID[5],LOT_ID[6]);\n\n')
            f.write(
                '  TDO_PRINTF("##date = %d.%d.%d %d:%d:%d' + r'\n' + '",year,month,day,tmptr->tm_hour,tmptr->tm_min,tmptr->tm_sec);\n\n')
            f.write("  READ_PROBER_XY (X_CO,Y_CO);\n")
            f.write(
                "  SOCKET_INC(FRZ_OFF)\n  {\n" + '    // printf("S%d x=%d,y=%d' + r'\n' + '",SOCKET,X_CO[SOCKET],Y_CO[SOCKET]);\n\n      JUDGE_VARIABLE (SOCKET, X_CO[SOCKET],-1200,5000 ,"X_CO");\n'
                                                                                          '      JUDGE_VARIABLE (SOCKET, Y_CO[SOCKET],-1200,5000 ,"Y_CO");\n  }\n  fflush(stdout);\n\n\n')

        if "bake" in G.col("FLOW", "item")[j]:
            result = epr_pattern_capture("capture", "uid")

            f.write("  POWER_ON(" + G.col("FLOW", "Vcc")[j].upper() + ");\n\n")
            f.write(
                '  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="enter_fbist_mode";\n  JUDGE_PAT(enter_fbist_mode,__enter_fbist_mode); \n\n')
            if G.col("FLOW", "UID").count("yes") != 0:
                for z in range(len(G.col("ADDR_MAP", "Word No."))):
                    if G.col("ADDR_MAP", "Word No.")[z] not in addr_map_item:
                        addr_map_item.append(G.col("ADDR_MAP", "Word No.")[z])
                # f.write("  SOCKET_INC(FRZ_OFF)\n  {\n\n")
                for cyc in range(len(addr_map_item)):
                    if "lable" in G.col("ADDR_MAP", "data type")[0 + page_word * cyc:(page_word-1) + page_word * cyc] and addr_map_item[cyc] == "uid":
                        result = epr_pattern_capture("capture", addr_map_item[cyc])
                        copy_file(G.BASE_DIR + "\\pat_temp\\" + result["read"] + ".pat",
                                  G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                        # 逐字段判断真实字节宽度（2或4字节），修复原先整页统一按32bit算、
                        # 导致无反码字段（如 Hsi_8/16/24/48M_Trim、Ts_30C/125C）字节数
                        # 被高估、后续字段偏移全部错位的问题（见 _uid_bake_field_layout）。
                        layout = _page_field_layout("uid", read_bit, uid_write_dic, int(code_name[G.i].split("_")[-1][-1]))
                        total_bytes = sum(width for _, width, _so in layout)

                        f.write("  //******************" + addr_map_item[cyc] + " capture***********************\n\n")
                        f.write("  int " + addr_map_item[cyc].lower() + "_0x00" +
                                G.col("ADDR_MAP", "SM Address")[0 + page_word * cyc].split(";")[0].split("0x")[
                                    1] + "[MAX_SITE]" + "[" + str(
                            total_bytes) + "];\n\n")
                        f.write("  SET_CAPTURE_MEM_MODE(" + str(
                            G.col("VERSION", "SWD PIN")[G.i]) + ", PEL_K, ON, 8K);\n\n")
                        f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' +
                                result["read"] + '";\n  JUDGE_PAT(' + result["read"] + ',__' + result[
                                    "read"] + '); \n\n')

                        f.write(
                            "  SOCKET_INC(FRZ_OFF)\n  {\n    for(J=0;J<" + str(
                                total_bytes * 8) + ";J++) TEMP_DATA[J]=8;\n\n")
                        f.write("    READ_CAPTURE_MEM_BLOCK(SOCKET, " + str(
                            G.col("VERSION", "SWD PIN")[G.i]) + ", 0, " + str(
                            total_bytes * 8 - 1) + ", TEMP_DATA);//" + str(
                            total_bytes) + "byte\n")
                        f.write('    printf("S%d:' + r"\n" + '",SOCKET);\n')
                        f.write('    printf("data 0x0200:' + r"\n" + '",SOCKET);\n')
                        f.write('    for(I=0;I<' + str(
                            total_bytes) + ';I++)//' + str(
                            total_bytes) + 'byte\n    {\n')
                        f.write("      " + addr_map_item[cyc] + "_0x00" + str(
                            G.col("ADDR_MAP", "SM Address")[0 + page_word * cyc].split(";")[0].split("0x")[
                                1]) + "[SOCKET]" + "[I]" + "=0;\n")
                        f.write(
                            "      for(J=0;J<8;J++)\n      {\n        if(TEMP_DATA[8*I+J]!=8) " + addr_map_item[
                                cyc] + "_0x00" + str(
                                G.col("ADDR_MAP", "SM Address")[0 + page_word * cyc].split(";")[0].split("0x")[
                                    1]) + "[SOCKET]" + "[I]" + " += TEMP_DATA[8*I+J]<<(7-J);\n      }\n\n")
                        f.write('      if(I%4==0)\n      {\n        printf("%02X: ",I);\n      }\n\n')
                        f.write('      printf("0x%02X ",' + addr_map_item[cyc] + "_0x00" + str(
                            G.col("ADDR_MAP", "SM Address")[0 + page_word * cyc].split(";")[0].split("0x")[
                                1]) + "[SOCKET]" + "[I]" + ');\n\n')
                        f.write('      if((I+1)%2==0)\n      {\n        printf("' + r"\n" + '");\n      }\n\n')
                        f.write("    }\n\n")  # for I
                        f.write('    printf("' + r"\n" + '");\n\n')

                        f.write("    //You need to check it by yourself\n")
                        arr_name = addr_map_item[cyc] + "_0x00" + str(
                            G.col("ADDR_MAP", "SM Address")[0 + page_word * cyc].split(";")[0].split("0x")[1])
                        off = 0
                        for type_flag, width, sub_off in layout:
                            f.write(type_flag + arr_name + "[SOCKET][" + str(off + sub_off) + "]*256+" + arr_name +
                                    "[SOCKET][" + str(off + sub_off + 1) + "];\n")
                            off += width

                f.write("  }\n\n")  # socket
                f.write("  fflush(stdout);\n\n")
                f.write("  SET_CAPTURE_MEM_MODE(" + str(
                    G.col("VERSION", "SWD PIN")[G.i]) + ", PEL_K, OFF, 8K);\n\n")
        for_flag = 0
        # print(value_count[1])
        # if list(FLOW["CP NO"])[j] == code_name[i].split("_")[-1] and "yes" in list(FLOW["UID"]) and "bake" not in list(FLOW["item"])[j]:
        #     for u in range(len(list(FLOW["UID"]))):
        #         if list(FLOW["UID"])[u] == "yes"and code_name[i].split("_")[-1] == list(FLOW["CP NO"])[u]and "ts" not in list(FLOW["item"])[
        #             u].lower():
        #             if for_flag == 0:
        #                 f.write("  for(I=0;I<MAX_SITE;I++)\n  {\n")
        #             if list(FLOW["type"])[u] == "trim":
        #                 temp_item_name = list(FLOW["item"])[u].split("Trim")[0].lower()
        #             if list(FLOW["type"])[u] == "verify":
        #                 temp_item_name = list(FLOW["item"])[u].split("Verify")[0].lower()
        #             f.write("    " + temp_item_name + "w[I]=0;\n")
        #             for_flag += 1
        #             if for_flag == value_count[int(code_name[i].split("_")[-1][-1])]:
        #                 f.write("  }\n\n")
        #
        #     for_flag = 0
        #     for u in range(len(list(FLOW["UID"]))):
        #         if list(FLOW["UID"])[u] == "yes"and code_name[i].split("_")[-1] == list(FLOW["CP NO"])[u]and "ts" not in list(FLOW["item"])[
        #             u].lower() and "bake" not in list(FLOW["item"])[j]:
        #             if for_flag == 0:
        #                 f.write("  SOCKET_INC(FRZ_OFF)\n  {\n")
        #             if list(FLOW["type"])[u] == "trim":
        #                 temp_item_name = list(FLOW["item"])[u].split("Trim")[0].lower()
        #             if list(FLOW["type"])[u] == "verify":
        #                 temp_item_name = list(FLOW["item"])[u].split("Verify")[0].lower()
        #             f.write(
        #                 "    " + temp_item_name + "w[SOCKET]=(int)(" + temp_item_name + "value_Final[SOCKET]*1000+0.5);\n")
        #             f.write(
        #                 "    " + temp_item_name + "w[SOCKET]=((" + temp_item_name + "w[SOCKET]/1000)%10)*4096+((" + temp_item_name + "w[SOCKET]/100)%10)*256+((" + temp_item_name + "w[SOCKET]/10)%10)*16+(" + temp_item_name + "w[SOCKET]%10);\n\n")
        #             for_flag += 1
        #             if for_flag == value_count[int(code_name[i].split("_")[-1][-1])]:
        #                 f.write("  }\n\n")

        # 常量取值同 core/flash_seq.py:flash_pattern_label_created Part B（S100 那边
        # writers.py 里也各自定义一份同名字典，属既有惯例）。
        uid_pass_flag_item = {"cp1_id": "65FFFFFF", "cp2_id": "65BA78FF", "cp3_id": "65BA78BA",
                              "cp1_bake_id": "65BAFFFF", "cp2_bake_id": "65BA78BA"}
        is_bake_item = "bake" in G.col("FLOW", "item")[j].lower()
        cp_num = int(code_name[G.i].split("_")[-1][-1])
        if "yes" in G.col("FLOW", "UID"):
            f.write("  SOCKET_INC(FRZ_OFF)\n  {\n")
            for u in uid_write_dic.keys():
                if "ts" not in u.lower() and int(code_name[G.i].split("_")[-1][-1]) >= uid_write_dic[u] and "bake" not in \
                        G.col("FLOW", "item")[j]:
                    # 早写（Part A，trim_data_read_write）已经把 type=="trim" 的 dac 字段
                    # 提前写进本 CP 的 cp<N>_id pattern——这里跳过，避免重复写。
                    if "verify" not in u.lower():
                        continue
                    result = epr_pattern_capture("normal", "cp" + str(int(code_name[G.i].split("_")[-1][-1])) + "_id")
                    temp_item_name = u.split("Verify")[0].lower()
                    write_pat_mem(f, result, 15, "-J", 0, temp_item_name.split("_")[0], temp_item_name.upper() + "W[SOCKET]",
                                  temp_item_name, _uid_pn_flag(temp_item_name))
                else:
                    if int(code_name[G.i].split("_")[-1][-1]) >= uid_write_dic[u] and "bake" not in G.col("FLOW", "item")[j]:
                        if "verify" not in u.lower():
                            continue
                        result = epr_pattern_capture("normal", "cp" + str(int(code_name[G.i].split("_")[-1][-1])) + "_id")
                        temp_item_name = u.split("Verify")[0].lower()
                        write_pat_mem(f, result, 15, "-J", 0, temp_item_name.split("_")[0], temp_item_name.upper() + "W[SOCKET]",
                                      temp_item_name, _uid_pn_flag(temp_item_name))
                    elif int(code_name[G.i].split("_")[-1][-1]) >= uid_write_dic[u] and "bake" in G.col("FLOW", "item")[j]:
                        # bake 也写进本 CP 自己的 cp<N>_id pattern（不是 cp<N-1>_bake_id——
                        # 那个只读 pattern 是 id_write() 的 check 分支专用，跟 S100 的
                        # writers.py:uid_write 同一处修正）。bake 场景没有早写，trim 类
                        # 字段仍要写。
                        # 若该字段的"起算 CP"正好等于本 CP（uid_write_dic[u]==cp_num），
                        # 说明它是本 CP 自己后面才会真正 trim 出来的值——Pgm_Cp<n-1>_Bakeid
                        # 这一步在 FLOW 里跑在本 CP 自己的 trim 之前，此刻从 uid_capture
                        # 抓到的只是 flash 里的旧/擦除态占位值（如 0xFFFF），不是真实值。
                        # 照常按"真实值"写回 pattern 的话，读侧比较会跟后面 trim 完写入的
                        # 真值对不上、check 失败（用户实测坐实，如 Ts_125C）。这种"本 CP 起算
                        # 且还没轮到"的字段，读侧比较改用 X（don't care）——只把软件缓冲区
                        # 占位对齐，不做真值校验，真正的校验交给该字段自己的 trim/verify 项。
                        result = epr_pattern_capture("normal", "cp" + str(cp_num) + "_id")
                        not_yet_real = uid_write_dic[u] == cp_num
                        if "verify" not in u.lower():
                            temp_item_name = u.split("[")[0].lower()
                            write_pat_mem(f, result, 15, "-J", 0, temp_item_name.split("_")[0], "REG_"+temp_item_name.upper() + "[SOCKET]",
                                          temp_item_name, _uid_pn_flag(temp_item_name), read_dc=not_yet_real)
                        elif "verify" in u.lower():
                            temp_item_name = u.split("Verify")[0].lower()
                            write_pat_mem(f, result, 15, "-J", 0, temp_item_name.split("_")[0], temp_item_name.upper() + "W[SOCKET]",
                                          temp_item_name, _uid_pn_flag(temp_item_name), read_dc=not_yet_real)
            if is_bake_item:
                # Part D 步骤2：跟字段重写在同一个（未按 site 门控的）SOCKET_INC 块里，
                # 先用"上一个 CP 已确定通过"的真实值播种本 CP 自己页面的 cp12_id 标签
                # ——不是给本 CP 定最终值，只是让软件缓冲区跟"芯片里现在实际是什么"
                # 保持一致，避免后面整页写入把 pass-flag 字段带偏。读侧比较值用 "X"
                # （don't care），真正的校验留给最终改写之后的 erase→prog→read。
                seed_result = epr_pattern_capture("normal", "cp" + str(cp_num) + "_id")
                write_pat_mem(f, seed_result, 31, "-J", 0, "pass id flag",
                              "0x" + uid_pass_flag_item["cp" + str(cp_num - 1) + "_id"],
                              "cp12_id_", "no", read_dc=True)
                if code_name[G.i].split("_")[-1] == "CP3":
                    write_pat_mem(f, seed_result, 31, "-J", 0, "pass id flag", "0xFFFFFFFF",
                                  "cp34_id_", "no", read_dc=True)
            f.write("  }\n\n")
            if is_bake_item:
                # Part D 步骤4："check 一下动态写 pattern 是否有问题"——只有一次
                # JUDGE_PAT(read) 落地检查，没有配对的 prog 调用（同 S100 uid_write
                # 的对应注释，两边照抄参考程序/用户模板给的真实结构）。
                check_result = epr_pattern_capture("normal", "cp" + str(cp_num) + "_id")
                copy_file(G.BASE_DIR + "\\pat_temp\\" + check_result["read"] + ".pat",
                          G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
                f.write("  ////////////////////////////check/////////////////////////////////////\n\n")
                f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + check_result["read"] + '";\n  JUDGE_PAT(' +
                        check_result["read"] + ',__' + check_result["read"] + '); \n\n')
                f.write('  POWER_OFF();\n\n')
        if build_uid_enabled and "bake" not in G.col("FLOW", "item")[j]:
            f.write("  SOCKET_INC(FRZ_OFF)\n  {\n")
            f.write("    //*********************LOT_ID***********************\n")
            f.write("    for(I=0;I<7;I++)\n    {\n")
            f.write("      TEMP = 0xFF;\n      TEMP = LOT_ID[I];\n\n")
            f.write(
                "      for(J=0;J<=7;J++)\n      {\n        BIT[J] = 0;\n        BIT[J] = TEMP%2;\n        TEMP = TEMP/2;\n      }\n\n")
            f.write("      if(I<4)\n      {\n")
            f.write("        for(J=7;J>=0;J--)\n        {\n          if(BIT[J]==0)\n          {\n")
            f.write("            WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", " + result[
                "pgm"] + ':lot_number_w0+7-J+8*I , ,' + '"0");\n\n')
            f.write("            WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", " + result[
                "read"] + ':lot_number_r0+7-J+8*I , ,' + '"L");\n')
            f.write("          }\n")
            f.write("          else\n          {\n")
            f.write("            WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", " + result[
                "pgm"] + ':lot_number_w0+7-J+8*I , ,' + '"1");\n\n')
            f.write("            WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", " + result[
                "read"] + ':lot_number_r0+7-J+8*I , ,' + '"H");\n')
            f.write("          }\n")
            f.write("        }\n")
            f.write("      }\n")
            f.write("      else\n      {\n")
            f.write("        for(J=7;J>=0;J--)\n        {\n          if(BIT[J]==0)\n          {\n")
            f.write("            WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", " + result[
                "pgm"] + ':lot_number_w1+7-J+8*(I-4) , ,' + '"0");\n\n')
            f.write("            WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", " + result[
                "read"] + ':lot_number_r1+7-J+8*(I-4) , ,' + '"L");\n')
            f.write("          }\n")
            f.write("          else\n          {\n")
            f.write("            WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", " + result[
                "pgm"] + ':lot_number_w1+7-J+8*(I-4) , ,' + '"1");\n\n')
            f.write("            WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", " + result[
                "read"] + ':lot_number_r1+7-J+8*(I-4) , ,' + '"H");\n')
            f.write("          }\n")
            f.write("        }\n")
            f.write("      }\n")
            f.write("    }\n\n")

            temp_cp3_item = ["X_CO", "Y_CO"]
            for item_num in range(len(temp_cp3_item)):
                f.write("    //*********************" + temp_cp3_item[item_num] + "***********************\n")
                f.write("    TEMP = 0xFF;\n    TEMP = " + temp_cp3_item[item_num] + "[SOCKET];\n\n")
                f.write(
                    "    for(J=0;J<12;J++)\n    {\n      BIT[J] = 0;\n      BIT[J] = TEMP%2;\n      TEMP = TEMP/2;\n    }\n\n")
                f.write("    for(J=7;J>=0;J--)\n    {\n      if(BIT[J]==0)\n      {\n")
                f.write(
                    "        WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", " + result["pgm"] + ':' +
                    temp_cp3_item[item_num].lower() + 'or_w+7-J , ,' + '"0");\n\n')
                f.write(
                    "        WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", " + result["read"] + ':' +
                    temp_cp3_item[item_num].lower() + 'or_r+7-J , ,' + '"L");\n')
                f.write("      }\n")
                f.write("      else\n      {\n")
                f.write(
                    "        WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", " + result["pgm"] + ':' +
                    temp_cp3_item[item_num].lower()+ 'or_w+7-J , ,' + '"1");\n\n')
                f.write(
                    "        WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", " + result["read"] + ':' +
                    temp_cp3_item[item_num].lower() + 'or_r+7-J , ,' + '"H");\n')
                f.write("      }\n")
                f.write("    }\n")
                if temp_cp3_item[item_num] == "X_CO":
                    f.write("    for(J=3;J>=0;J--)\n    {\n      if(BIT[J+8]==0)\n      {\n")
                    f.write("        WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", " + result[
                        "pgm"] + ':xy_coor_w+7-J , ,' + '"0");\n\n')
                    f.write("        WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", " + result[
                        "read"] + ':xy_coor_r+7-J , ,' + '"L");\n')
                    f.write("      }\n")
                    f.write("      else\n      {\n")
                    f.write("        WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", " + result[
                        "pgm"] + ':xy_coor_w+7-J , ,' + '"1");\n\n')
                    f.write("        WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", " + result[
                        "read"] + ':xy_coor_r+7-J , ,' + '"H");\n')
                    f.write("      }\n")
                    f.write("    }\n\n")
                else:
                    f.write("    for(J=3;J>=0;J--)\n    {\n      if(BIT[J+8]==0)\n      {\n")
                    f.write("        WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", " + result[
                        "pgm"] + ':xy_coor_w+3-J , ,' + '"0");\n\n')
                    f.write("        WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", " + result[
                        "read"] + ':xy_coor_r+3-J , ,' + '"L");\n')
                    f.write("      }\n")
                    f.write("      else\n      {\n")
                    f.write("        WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", " + result[
                        "pgm"] + ':xy_coor_w+3-J , ,' + '"1");\n\n')
                    f.write("        WRITE_PAT_MEM(SOCKET, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", " + result[
                        "read"] + ':xy_coor_r+3-J , ,' + '"H");\n')
                    f.write("      }\n")
                    f.write("    }\n\n")

            f.write("    unsigned char ucPtr[14];\n")
            f.write(
                "    for(I=0;I<14;I++)\n    {\n      if(I<7) ucPtr[I]=LOT_ID[I];\n      if(I==7) ucPtr[I]=WAFER_SLOT;\n      if(I==8) ucPtr[I]=((abs(Y_CO[SOCKET])>>8)&0xF)*16 + ((abs(X_CO[SOCKET])>>8)&0xF);\n"
                + "      if(I==9) ucPtr[I]=(X_CO[SOCKET])&0xFF;  \n      if(I==10) ucPtr[I]=Y_CO[SOCKET]&0xFF; \n      if(I==11) ucPtr[I]=((year%10)<<4)+month;\n      if(I==12) ucPtr[I]=TESTING_HOUSE_ID;\n"
                + "      if(I==13) ucPtr[I]=CP_VERNO;\n\n    }\n\n")
            f.write("unsigned char CRC8=GetCRC8(ucPtr,0x0E);")
            write_pat_mem(f, result, 7, "-J", 0, "CRC", "CRC8", "crc_8_", "no")

            write_pat_mem(f, result, 15, "-J", 0, "PROJECT_NAME&&version", "PROJECT_NAME*256+PROJECT_VERSION",
                          "project_", "yes")
            write_pat_mem(f, result, 7, "-J", 0, "WAFER_SLOT", "WAFER_SLOT", "slot_number_", "no")
            write_pat_mem(f, result, 7, "-J", 0, "year&&month", "((year%10)<<4)+month", "year_month_", "no")
            write_pat_mem(f, result, 7, "-J", 0, "TESTING_HOUSE_ID", "TESTING_HOUSE_ID", "testing_house_id_", "no")
            write_pat_mem(f, result, 7, "-J", 0, "CP_VERNO", "CP_VERNO", "cp_ver_no_", "no")
            write_pat_mem(f, result, 7, "-J", 0, "program_ver_H", "CP1_VERSION", "cp1_ver_", "no")
            write_pat_mem(f, result, 7, "-J", 0, "program_ver_L", "CP2_VERSION", "cp2_ver_", "no")

            f.write("  }\n\n")

            # CP3 id 页的擦/写/读：上面只把数据写进了 cp3_id 的 pattern memory，
            # 之前漏了实际擦写读（fbist_page_prog/read_cp3_id 的 .pat 也因此没拷进程序）。
            # 与 CP1/CP2 的 else 分支及 S100 公共尾段一致补上。
            result = epr_pattern_capture("normal", "cp" + str(int(code_name[G.i].split("_")[-1][-1])) + "_id")
            # pass id flag：uid 页 word-offset5/6（cp12_id/cp34_id）现在是运行时 label
            # （core/flash_seq.py Part B），必须显式写一次最终值，否则这个字段是未定义的
            # ——之前 Chroma 这里完全没有写过 cp12_id，是 Part B 生效后新出现的回归，
            # 跟 S100 uid_write 尾段的写法保持一致（本 CP 自己真正的最终 pass 值）。
            f.write("  SOCKET_INC(FRZ_OFF)\n  {\n")
            write_pat_mem(f, result, 31, "-J", 0, "pass id flag",
                          "0x" + uid_pass_flag_item["cp" + str(cp_num) + "_id"], "cp12_id_", "no")
            write_pat_mem(f, result, 31, "-J", 0, "pass id flag", "0x9AFFFFFF", "cp34_id_", "no")
            f.write("  }\n\n")
            f.write("  POWER_ON(" + G.col("FLOW", "Vcc")[j].upper() + ");\n\n")
            f.write("  ////////////////////////erase///////////////////////////\n")
            f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="enter_fbist_mode";\n  JUDGE_PAT(enter_fbist_mode,__enter_fbist_mode); \n\n')
            copy_file(G.BASE_DIR + "\\pat_temp\\" + result["erase"] + ".pat",
                      G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
            f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + result["erase"] + '";\n  JUDGE_PAT(' + result["erase"] + ',__' + result["erase"] + '); \n\n')
            f.write("  ////////////////////////program/////////////////////////\n")
            copy_file(G.BASE_DIR + "\\pat_temp\\" + result["pgm"] + ".pat",
                      G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
            f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + result["pgm"] + '";\n  JUDGE_PAT(' + result["pgm"] + ',__' + result["pgm"] + '); \n\n')
            f.write("  /////////////////////////read//////////////////////////\n")
            copy_file(G.BASE_DIR + "\\pat_temp\\" + result["read"] + ".pat",
                      G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
            f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + result["read"] + '";\n  JUDGE_PAT(' + result["read"] + ',__' + result["read"] + '); \n\n')
            f.write('  POWER_OFF(); \n\n')
        # bake的擦写读,fail 擦
        elif "bake" in G.col("FLOW", "item")[j]:
            # POWER_OFF 已经在上面 Part D 步骤4 的 check 段落里做过一次，这里不用重复。
            f.write("  //////////////////////Write_CP1bakeID/////////////////////////////////\n")
            f.write("  LUINT site_f;\n\n")
            f.write(
                "  SOCKET_INC(FRZ_OFF)\n  {\n    site_f[SOCKET]=0;\n    if(CP" + str(int(code_name[G.i].split("_")[-1][
                                                                                             -1]) - 1) + "_BAKEID_FLAG[SOCKET]==1) \n    {\n      site_f[SOCKET]=1;\n    }\n  }\n\n")
            f.write("  SOCKET_SET(B:site_f,FRZ_OFF)\n  {\n")

            # pass id flag：bake 最终提交到本 CP 自己页面的真实值（理由同上方两处
            # 非 bake 分支的注释）。CP2 bake 用 uid_pass_flag_item["cp1_bake_id"]，
            # CP3 bake 用 uid_pass_flag_item["cp2_bake_id"]——同 S100 uid_write 的映射。
            # SOCKET_SET(B:site_f,...) 本身只圈定参与的 site，块内直接用 SOCKET 做
            # 表达式是非法的（跟本文件 2695 行附近同款结构一致）——必须再嵌一层
            # SOCKET_INC(FRZ_OFF) 才能拿到可用的 SOCKET 循环变量，write_pat_mem 里的
            # WRITE_PAT_MEM(SOCKET,...) 才编译得过。
            f.write("    SOCKET_INC(FRZ_OFF)\n    {\n")
            write_pat_mem(f, result, 31, "-J", 2, "pass id flag",
                          "0x" + uid_pass_flag_item["cp" + str(cp_num - 1) + "_bake_id"], "cp12_id_", "no")
            if code_name[G.i].split("_")[-1] == "CP3":
                write_pat_mem(f, result, 31, "-J", 2, "pass id flag", "0xFFFFFFFF", "cp34_id_", "no")
            f.write("    }\n\n")

            f.write("    POWER_ON(" + G.col("FLOW", "Vcc")[j].upper() + ");\n\n")
            f.write("    ////////////////////////erase///////////////////////////\n")
            f.write(
                '    TEST_NUM++;\n    TEST_NO(TEST_NUM); DATALOG_MSG="enter_fbist_mode";\n    JUDGE_PAT(enter_fbist_mode,__enter_fbist_mode);   \n\n')
            copy_file(G.BASE_DIR + "\\pat_temp\\" + result["erase"] + ".pat",
                      G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
            f.write(
                '    TEST_NUM++;\n    TEST_NO(TEST_NUM); DATALOG_MSG="' + result["erase"] + '";\n    JUDGE_PAT(' +result["erase"] + ',__' + result["erase"] + '); \n\n')

            f.write("    ////////////////////////program/////////////////////////\n")
            copy_file(G.BASE_DIR + "\\pat_temp\\" + result["pgm"] + ".pat",
                      G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
            f.write(
                '    TEST_NUM++;\n    TEST_NO(TEST_NUM); DATALOG_MSG="' + result["pgm"] + '";\n    JUDGE_PAT(' + result["pgm"] + ',__' + result["pgm"] + '); \n\n')
            f.write("    /////////////////////////read//////////////////////////\n")
            copy_file(G.BASE_DIR + "\\pat_temp\\" + result["read"] + ".pat",
                      G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
            f.write(
                '    TEST_NUM++;\n    TEST_NO(TEST_NUM); DATALOG_MSG="' + result["read"] + '";\n    JUDGE_PAT(' +result["read"] + ',__' + result["read"] + '); \n\n')

            f.write('    POWER_OFF(); \n\n')
            f.write('  } \n\n')
        # CP123 id的擦写读
        else:
            result = epr_pattern_capture("normal", "cp" + str(int(code_name[G.i].split("_")[-1][-1])) + "_id")
            # pass id flag：理由同上方 CP3 分支的注释（Part B 生效后的必须补写）。
            f.write("  SOCKET_INC(FRZ_OFF)\n  {\n")
            write_pat_mem(f, result, 31, "-J", 0, "pass id flag",
                          "0x" + uid_pass_flag_item["cp" + str(cp_num) + "_id"], "cp12_id_", "no")
            f.write("  }\n\n")
            f.write("  POWER_ON(" + G.col("FLOW", "Vcc")[j].upper() + ");\n\n")
            f.write("  ////////////////////////erase///////////////////////////\n")
            f.write(
                '  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="enter_fbist_mode";\n  JUDGE_PAT(enter_fbist_mode,__enter_fbist_mode); \n\n')
            copy_file(G.BASE_DIR + "\\pat_temp\\" + result["erase"] + ".pat",
                      G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
            f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + result["erase"] + '";\n  JUDGE_PAT(' + result[
                "erase"] + ',__' + result["erase"] + '); \n\n')
            f.write("  ////////////////////////program/////////////////////////\n")
            copy_file(G.BASE_DIR + "\\pat_temp\\" + result["pgm"] + ".pat",
                      G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
            f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + result["pgm"] + '";\n  JUDGE_PAT(' + result[
                "pgm"] + ',__' + result["pgm"] + '); \n\n')
            f.write("  /////////////////////////read//////////////////////////\n")
            copy_file(G.BASE_DIR + "\\pat_temp\\" + result["read"] + ".pat",
                      G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")
            f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + result["read"] + '";\n  JUDGE_PAT(' + result[
                "read"] + ',__' + result["read"] + '); \n\n')

            f.write('  POWER_OFF(); \n\n')
        # CP12 id,fail 擦
        if _recipe_module_enabled(recipe_modules, "PGMOTP"):
            f.write("///////////if fail erase uid page///////////\n  LUINT shift_site;\n\n")
            f.write(
                "  SOCKET_INC(FRZ_OFF)\n  {\n    shift_site[SOCKET]=0;\n    if(PLAN_RESULT_MS[SOCKET]==FAIL) \n    {\n      shift_site[SOCKET]=1;\n    }\n  }\n\n")
            f.write("  SOCKET_SET(B:shift_site,FRZ_OFF)\n  {\n")
            f.write("    POWER_ON(" + G.col("FLOW", "Vcc")[j].upper() + ");\n\n")
            f.write("    ////////////////////////erase///////////////////////////\n")
            f.write(
                '    TEST_NUM++;\n    TEST_NO(TEST_NUM); DATALOG_MSG="enter_fbist_mode";\n    JUDGE_PAT(enter_fbist_mode,__enter_fbist_mode); \n\n')
            f.write(
                '    TEST_NUM++;\n    TEST_NO(TEST_NUM); DATALOG_MSG="' + result["erase"] + '";\n    JUDGE_PAT(' +
                result[
                    "erase"] + ',__' + result["erase"] + '); \n\n')


            f.write('    POWER_OFF(); \n\n')
            f.write("  } \n")

        f.write("}\n")


def otp_read_write(code_name, f):
    """OTP_READ debug 项（Chroma .pln）：逐页读 OTP 并 datalog 打印。无条件生成，不进 FLOW。
    结构仿 temp/V_*128SC 样本的 OTP_Data_Read：进 fbist → 逐 distinct 页 RA →
    经 otp_read:addr 标签逐位写 8 位地址 → JUDGE_PAT(otp_read) → READ_CAPTURE_MEM_BLOCK →
    打包 otp_data → printf 排版（每行 4 字节，index 配对交换，<0x10 补前导 0）。"""
    swd = str(G.col("VERSION", "SWD PIN")[G.i])
    page_word = G.col("VERSION", "page word")[0]
    byte_count = page_word * 4
    gs = max(1, int(G.col("VERSION", "read bit")[0]) // 32)  # 读位宽分组：32→1/64→2/128→4，组内反序

    # otp_read pattern 拷入该程序 pat/
    copy_file(G.BASE_DIR + "\\pat_temp\\otp_read.pat", G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")

    # ADDR_MAP distinct 页（Word No.）的 RA 列表（取每页第 0 字的 SM Address RA 值）
    addr_map_item = []
    for z in range(len(G.col("ADDR_MAP", "Word No."))):
        if G.col("ADDR_MAP", "Word No.")[z] not in addr_map_item:
            addr_map_item.append(G.col("ADDR_MAP", "Word No.")[z])
    ra_list = []
    for cyc in range(len(addr_map_item)):
        ra_list.append(int(G.col("ADDR_MAP", "SM Address")[0 + page_word * cyc].split(";")[0].split("=")[1], 16))
    addr_arry = "{" + ",".join("0x%02X" % r for r in ra_list) + "}"

    f.write("OTP_Read()\n{\n")
    f.write("  TEST_NUM=999900;\n" + '  TEST_NO(TEST_NUM);DATALOG_MSG="OTP_Read";\n\n')
    f.write("  int byte_count=" + str(byte_count) + ";\n")
    f.write("  int otp_read_bit[" + str(byte_count * 8) + "];//" + str(byte_count) + " byte\n")
    f.write("  int otp_data[1][" + str(byte_count) + "];//page,byte\n")
    f.write("  int temp=0;\n")
    f.write("  int addr_arry[" + str(len(ra_list)) + "]=" + addr_arry + ";\n\n")

    f.write("  POWER_ON(VCC_TYP);\n")
    f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="enter_fbist_mode";\n  JUDGE_PAT(enter_fbist_mode,__enter_fbist_mode);\n\n')

    f.write("  SET_CAPTURE_MEM_MODE(" + swd + ", PEL_K, ON, 64K);\n\n")
    f.write("  SOCKET_INC(FRZ_OFF)\n  {\n")
    f.write("    for(int cyc=0;cyc<sizeof(addr_arry)/sizeof(addr_arry[0]);cyc++)\n    {\n")
    # 写 8 位页地址
    f.write("      /////////////write pattern addr///////////////////\n")
    f.write("      temp = addr_arry[cyc];\n")
    # 循环变量用程序顶部全局大写 I/J/K、BIT（小写 i/j/k/bit 未定义会报错，用户裁决 2026-06-24）
    f.write("      for(J=0;J<=7;J++)\n      {\n        BIT[J] = 0;\n        BIT[J] = temp%2;\n        temp = temp/2;\n      }\n\n")
    f.write("      for(J=7;J>=0;J--)\n      {\n")
    f.write("        if(BIT[J]==0)\n        {\n")
    f.write("          WRITE_PAT_MEM(SOCKET, " + swd + ', otp_read:addr+7-J, ,"0");\n        }\n')
    f.write("        else\n        {\n")
    f.write("          WRITE_PAT_MEM(SOCKET, " + swd + ', otp_read:addr+7-J, ,"1");\n        }\n      }\n\n')
    # 跑 pattern
    f.write('      TEST_NUM++;\n      TEST_NO(TEST_NUM); DATALOG_MSG="otp_read";\n      JUDGE_PAT(otp_read,__otp_read);\n\n')
    f.write("      for(J=0;J<byte_count*8;J++) otp_read_bit[J]=8;\n")
    f.write("      READ_CAPTURE_MEM_BLOCK(SOCKET, " + swd + ", 0, " + str(byte_count * 8 - 1) + ", otp_read_bit);\n\n")
    # 打包
    f.write("      //data in\n      for(I=0;I<1;I++)\n      {\n")
    f.write("        for(J=0;J<byte_count;J++)\n        {\n")
    f.write("          otp_data[I][J]=0;\n")
    f.write("          for(K=0;K<8;K++) if(otp_read_bit[byte_count*8*I+8*J+K]!=8) otp_data[I][J] += otp_read_bit[byte_count*8*I+8*J+K]<<(7-K);\n")
    f.write("        }\n      }\n\n")
    # 打印
    f.write("      //data print\n      for(I=0;I<1;I++)\n      {\n")
    f.write('        printf("- SM - Bit31  -->   Bit0\\n");\n')
    f.write("        for(J=0;J<byte_count/4;J++)\n        {\n")
    f.write("          int index=(J/" + str(gs) + ")*" + str(gs) + "+(" + str(gs) + "-1-(J%" + str(gs) + "));\n")
    f.write('          printf("0x%04X:",addr_arry[cyc]*byte_count+J*4);\n')
    f.write("          for(K=0;K<4;K++)\n          {\n")
    f.write('            if(otp_data[I][4*index+K]<=0xF&&otp_data[I][4*index+K]>=0x0) printf("  0%X",otp_data[I][4*index+K]);\n')
    f.write('            else printf("  %2X",otp_data[I][4*index+K]);\n')
    f.write("          }\n")
    f.write('          printf("\\n");\n')
    f.write("        }\n")
    f.write('        printf("\\n");\n')
    f.write("      }\n")
    f.write("      fflush(stdout);\n")
    f.write("    }\n  }\n\n")

    f.write("  SET_CAPTURE_MEM_MODE(" + swd + ", PEL_K, OFF, 64K);\n\n")
    f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="exit_fbist_mode";\n  JUDGE_PAT(exit_fbist_mode,__exit_fbist_mode);\n\n')
    f.write("  POWER_OFF();\n")
    f.write("}\n\n")


def nm_read_write(code_name, f):
    """NM_Data_Read debug 项（Chroma .pln）：整片 main 阵列 capture 读、逐 site dump 到
    .\\..\\S<n>_main.txt。无条件生成，不进 FLOW 测试列表（接入 TEST_PRO）。
    机制对齐本项目 otp_read_write（*1K1* capture → READ_CAPTURE_MEM_BLOCK），非样本的 ECM；
    pattern nm_read 双 bank 硬件循环已读满整片。page_count=NM、page_byte=PAGE_BYTES。
    **待上机核实**：capture buffer 容量(整片 256KB)、SET_CAPTURE_MEM_MODE 尺寸参数、循环计数。

    2026-07-03 用户上机实测坐实两处 bug（S0_main.txt 前半页数据对、后半页是垃圾值，
    定位到是紧邻栈变量 filepath[255] 被越界读出）：
    ① 打印内层行数循环原硬编码 "for(J=0;J<16;J++)"（假设每页固定 256 字节=16 行×16
       字节），当 page_byte!=256（本母本=128）时，行数仍打印 16 行、`main_data[16*J+
       index]` 下标最大到 255，超出只声明了 page_byte 个元素的 main_data 数组，读到
       相邻栈变量（filepath）的内容——改成 page_byte//16 行，随 page_byte 走。
    ② 打印字节序分组 gs 原按 "read_bit//32" 算（照抄 otp_read_write 的公式），但 NM
       走的是 ECM 块读（SET_ECM_MODE 的 X<n> 参数），字节分组跟 read_bit 无关——gs 改
       为跟 ECM 的 X 参数绑定同一个变量，不再各自独立硬编码/计算，避免两处脱节。
       X<n> 本身是 ECM 每引脚容量规格（X8=每引脚 8×1024=8192 个数据点，用户裁决
       2026-07-03：固定用 X8，不随母本变化），跟"打印分组"字面不是一回事——这次两者
       数值刚好都是 8，用截图 dump 实测验证过，不是巧合套用；若以后换更大容量规格
       （如 X16），这里的 gs 是否还该原样跟着变，需要重新用真机 dump 验证，不能想当然。"""
    swd = str(G.col("VERSION", "SWD PIN")[G.i])
    page_count = G.flash_mode_dic["NM"]            # 整片页数（双 bank 合计，本母本=1024）
    page_byte = G.flash_mode_dic["PAGE_BYTES"]     # 每页字节（本母本=128）
    total_bytes = page_count * page_byte
    ecm_x = 8                                      # SET_ECM_MODE 的 X<n>：每引脚容量规格
                                                    # （X8=8×1024=8192 数据点/引脚，用户裁决固定）
    gs = ecm_x                                     # 打印字序分组，数值上与 ecm_x 相同（实测坐实，
                                                    # 非该参数本义），两处绑同一变量避免脱节
    print_rows = page_byte // 16                   # 打印行数随 page_byte 走，不再硬编码 16

    copy_file(G.BASE_DIR + "\\pat_temp\\nm_read.pat", G.OUT_DIR + "\\" + code_name[G.i] + "\\pat")

    f.write("NM_Data_Read()\n{\n")
    f.write("  TEST_NUM=999800;\n" + '  TEST_NO(TEST_NUM);DATALOG_MSG="NM_Data_Read";\n\n')
    f.write("  int page_count=" + str(page_count) + ";\n")
    f.write("  int page_byte=" + str(page_byte) + ";\n")
    # ECM 整片读（对齐样本 NM_Data_Read）：READ_ECM_BLOCK 支持表达式参数、读入 tester 管理的
    # CUSTOM_3DIM_BOOL —— 避开 READ_CAPTURE_MEM_BLOCK 偏移须字面量(`*`变量报 C1000) 与整片巨型栈数组
    f.write("  CUSTOM_3DIM_BOOL temp_nm_data;\n")
    f.write("  int main_data[" + str(page_byte) + "];//one page bytes\n")
    f.write("  FILE *fp1;\n  char filepath[255];\n\n")

    f.write("  POWER_ON(VCC_TYP);\n")
    f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="enter_fbist_mode";\n  JUDGE_PAT(enter_fbist_mode,__enter_fbist_mode);\n\n')

    f.write("  SET_ECM_MODE(" + swd + ", PEL_K, ON, X" + str(ecm_x) + ");//ECM size TBD on tester\n\n")
    f.write("  SOCKET_INC(FRZ_OFF)\n  {\n")
    f.write('    printf("================== Site %d data output to file ==================\\n",SOCKET);\n')
    f.write('    printf("Please Waiting...\\n");\n    fflush(stdout);\n')
    f.write('    sprintf(filepath,".\\\\..\\\\S%d_main.txt",SOCKET);\n    fp1=fopen(filepath,"w");\n\n')

    # 跑 nm_read（双 bank 硬件循环 capture 整片到 ECM）+ 一次性整片读回
    f.write('    TEST_NUM++;\n    TEST_NO(TEST_NUM); DATALOG_MSG="nm_read";\n    JUDGE_PAT(nm_read,__nm_read);\n\n')
    f.write("    READ_ECM_BLOCK(" + swd + ", 0, page_count*page_byte*8-1, temp_nm_data);\n\n")
    f.write('    fprintf(fp1,"=============================== Site %d ===============================\\n",SOCKET);\n')
    f.write('    fprintf(fp1,"  -user-    0x0 0x1 0x2 0x3 0x4 0x5 0x6 0x7 0x8 0x9 0xA 0xB 0xC 0xD 0xE 0xF\\n");\n')
    # 逐页：从 ECM 结构按页打包 byte → dump 16 行（变量 I 作数组下标，C 合法）
    f.write("    for(I=0;I<page_count;I++)\n    {\n")
    f.write("      for(J=0;J<page_byte;J++)\n      {\n")
    f.write("        main_data[J]=0;\n")
    f.write("        for(K=0;K<8;K++) main_data[J] += (temp_nm_data[SOCKET][0][page_byte*8*I+8*J+K]<<(7-K));\n")
    f.write("      }\n")
    f.write("      for(J=0;J<" + str(print_rows) + ";J++)\n      {\n")
    f.write('        fprintf(fp1,"0x080%03X%02X:",I,J*16);\n')
    f.write("        for(K=0;K<16;K++)\n        {\n")
    f.write("          int index=(K/" + str(gs) + ")*" + str(gs) + "+(" + str(gs) + "-1-(K%" + str(gs) + "));\n")
    f.write('          fprintf(fp1,"  %02X",main_data[16*J+index]);\n')
    f.write("        }\n")
    f.write('        fprintf(fp1,"\\n");\n')
    f.write("      }\n    }\n\n")
    f.write("    fclose(fp1);\n")
    f.write('    printf("Site %d data output FINISH!\\n",SOCKET);\n')
    f.write("  }\n  fflush(stdout);\n\n")

    f.write("  SET_ECM_MODE(" + swd + ", PEL_K, OFF, X" + str(ecm_x) + ");\n\n")
    f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="exit_fbist_mode";\n  JUDGE_PAT(exit_fbist_mode,__exit_fbist_mode);\n\n')
    f.write("  POWER_OFF();\n")
    f.write("}\n\n")
