# S100 平台：.prg 各类测试项写出。
import math
import re
from dataclasses import dataclass
import pandas as pd
from flow_recipe import dynamic_recipe_enter_operations, recipe_setup_operations
from program_gen.core import clock_force
from program_gen.core.encoding import addr_map_field_width, addr_map_literal_value, bin_list_to_hex, calc_limit, decimal_to_hex, expand_dac_array, hex_to_bin_16bit, invert_hex_string, leading_bit_width, pattern_field_is_dynamic, process_dict, widen_pct
from program_gen.core.flash_seq import epr_pattern_capture
from program_gen.core.pattern_data import reuse_dac_pattern, reuse_dac_restore_items
from program_gen.core.recipe_trim import dac_final_symbol, generated_flow_item_name, recipe_pattern_name, trim_data_helper_name
from program_gen.core.shmoo import ShmooPlan
from program_gen.platforms.s100.commit_shmoo_adapter import write_commit_shmoo
from program_gen.core.trim_spec import dynamic_enter_operations
from program_gen.core.trim_data import trim_data_reference_matches
from program_gen.core.logical_item import logical_item_key
from program_gen.platforms.s100.pattern_files import copy_file, copy_trig_sd, trig_disp, LEVEL_SEQ_RE, default_pulse, level_seq_pat_name, parse_pulse_width
from program_gen.platforms.s100.project_files import prj_power_pins
from program_gen import state as G


@dataclass(frozen=True)
class UidRecipePolicy:
    readotpmap: bool
    loadmap: bool
    checkotp: bool
    commit: bool
    pgmotp: bool
    set_vposp: bool
    build_uid: bool


def uid_recipe_policy(recipe_row, *, legacy_build_uid=False):
    """Translate one UID row's typed Recipe without inserting modules."""
    if recipe_row is None:
        return UidRecipePolicy(True, True, True, True, True, True, legacy_build_uid)
    modules = {operation.name for operation in recipe_row.operations}
    return UidRecipePolicy(
        readotpmap="READOTPMAP" in modules,
        loadmap="LOADMAP" in modules,
        checkotp="CHECKOTP" in modules,
        commit="COMMIT" in modules,
        pgmotp="PGMOTP" in modules,
        set_vposp="SETVPOSP" in modules,
        build_uid="BUILDUID" in modules,
    )


def _commit_value_expression(value, width):
    if value.kind == "STEP":
        raise ValueError("S100 固定 COMMIT 不接受 STEP；请使用 COMMIT Shmoo adapter")
    if value.kind == "DECIMAL":
        constant = int(value.token, 10)
    elif value.kind == "HEX":
        constant = int(value.token, 16)
    elif value.kind == "BINARY":
        constant = int(value.token, 2)
    else:
        return value.token
    if constant < 0 or constant >= (1 << width):
        raise ValueError(f"COMMIT 常量 {value.token} 超出 {width} bit 字段范围")
    return str(constant)


def write_fixed_commit(recipe_row, f, *, cp, catalog=None):
    """Incrementally merge explicit COMMIT fields and flush each REG once."""
    if recipe_row is None:
        return ()
    assignments = tuple(
        assignment
        for operation in recipe_row.operations
        if operation.name == "COMMIT"
        for assignment in getattr(operation, "assignments", ())
    )
    if not assignments:
        return ()
    catalog = catalog or G.compiled_adapter.addr_map_catalog
    registers = {}
    pages = []
    for assignment in assignments:
        for field in catalog.resolve_fields(assignment.field):
            if not field.register_layout.applies_to(cp):
                continue
            key = (field.page, field.register)
            registers.setdefault(key, []).append((field, assignment.value))
            if field.page not in pages:
                pages.append(field.page)
    if not registers:
        return ()

    f.write("\t// explicit COMMIT: preserve complete REG image and update selected fields\n")
    f.write("\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n\t{\n")
    f.write("\t\tif(Sys_ActiveSite[T_SOCKET]==0)continue;\n")
    for (_page, register), writes in registers.items():
        reg_ref = "REG_" + register.upper() + "[T_SOCKET]"
        for field, value in writes:
            mask = ((1 << field.width) - 1) << field.lsb
            value_mask = (1 << field.width) - 1
            expression = _commit_value_expression(value, field.width)
            f.write(
                f"\t\t{reg_ref}=({reg_ref}&0x{(~mask & 0xFFFF):04X})|"
                f"(({expression}&0x{value_mask:X})<<{field.lsb});\n"
            )
    f.write("\t}\n\n")

    for (page, register), writes in registers.items():
        result = epr_pattern_capture(
            "normal", "cp" + cp[-1] + "_id" if page.casefold() == "uid" else page
        )
        layout = writes[0][0].register_layout
        write_pat_mem(
            f, result, 16, "-J", 0, register,
            "REG_" + register.upper(), register.lower() + "_",
            "yes" if layout.complement_half else "no", "arr",
        )
    return tuple(pages)


def write_uid_failed_site_reerase(f, result, *, vcc):
    """Erase the UID page again only on sites whose read-check failed."""
    f.write("\t///////////if fail erase uid page///////////\n\n")
    f.write("\t{\n\t\tint uidReeraseRequired=0;\n\n")
    f.write("\t\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n\t\t{\n")
    f.write("\t\t\tif(Sys_DriverResult[T_SOCKET] > 0.5)\n\t\t\t{\n")
    f.write("\t\t\t\tSys_ActiveSite[T_SOCKET]=0;\n\t\t\t\tcontinue;\n\t\t\t}\n")
    f.write("\t\t\tSys_ActiveSite[T_SOCKET]=1;\n")
    f.write("\t\t\tuidReeraseRequired=1;\n")
    f.write("\t\t}\n\n")
    f.write("\t\tif(uidReeraseRequired==1)\n\t\t{\n")
    f.write("\t\t\tCALL_MACRO POWER_ON(_C_" + vcc.upper() + ");\n\n")
    f.write("\t\t\tRUN_PATTERN(enter_fbist_mode:START,enter_fbist_mode:END,1,TS_5MHZ);\n\n")
    f.write("\t\t\tRUN_PATTERN(" + result["erase"] + ":START," + result["erase"] + ":END,1,TS_5MHZ);\n\n")
    f.write("\t\t\tCALL_MACRO POWER_OFF();\n")
    f.write("\t\t}\n\t}\n\n")


def _flow_item_key(value):
    """Normalize FLOW item names before case-insensitive dispatch."""
    return str(value).strip().lower()


def flow_relay(z):
    """Return the row relay only when the current CP pin-dec declares it."""
    if G.FLOW is None or "relay" not in G.FLOW.columns:
        return "/"
    relay = str(G.col("FLOW", "relay")[z]).strip()
    if relay == "/":
        return "/"
    cp_no = G.col("FLOW", "CP NO")[z]
    pin_cp = G.col("PIN_DEC_128", "CP NO")
    pin_pad = G.col("PIN_DEC_128", "E/C(Pad Name)")
    for u in range(len(pin_cp)):
        if pin_cp[u] == cp_no and relay == str(pin_pad[u]).strip():
            return relay
    return "/"


def _emit_flow_relay(f, relay, enabled):
    if relay != "/":
        mode = "CONNECT_MODE" if enabled else "DISCONNECT_MODE"
        f.write(
            "\tIO_CLOSE_USER_RELAY("
            + relay
            + ","
            + mode
            + ",ALL_SITE_ON,WAIT=1MS);\n"
        )


def shmoo_item_write(code_name, f, plan: ShmooPlan):
    """Generate one-dimensional Shmoo; S100 aliases stay static per case."""
    if code_name[G.i].split("_")[-1] != plan.cp or plan.mode != "fbist":
        return
    z = plan.flow_row_index
    relay = flow_relay(z)
    points = plan.points
    force_point = max(points, key=lambda point: max(abs(point.down_limit), abs(point.up_limit)))
    copy_file(G.BASE_DIR + "\\pat_temp\\" + plan.pattern_name + ".sd",
              G.OUT_DIR + "\\" + code_name[G.i])

    f.write("\n@@PLAN " + plan.function_name.title() + "\n")
    f.write("\tSITE_SEQUENCE      = OFF;\n\tGO_THROUGH         = ON;\n")
    f.write("\tDISABLE_BY_MARK_NO = NULL;\n\tS_SETUP_FILE       = c:\\set.dat;\n")
    f.write("\tREMARK             = " + plan.function_name.title() + ";\n\n")
    f.write("\tint shmooDac[" + str(len(points)) + "]={"
            + ",".join(str(point.dac) for point in points) + "};\n\n")
    _emit_flow_relay(f, relay, enabled=True)
    f.write("\tCALL_MACRO POWER_ON(_C_" + plan.vcc.upper() + ");\n\n")
    f.write("\tRUN_PATTERN(enter_fbist_mode:START,enter_fbist_mode:END,1,TS_5MHZ);\n\n")
    Force_Judge(plan.unit, plan.meas_pin, plan.force_value, force_point.target, 2,
                "FORCE", "PMU", force_point.low_range, force_point.high_range,
                "", "no", f, force_wait=plan.force_wait)
    f.write("\tfor(I=0;I<" + str(len(points)) + ";I++)\n\t{\n")
    f.write("\t\tCALL_MACRO set_" + plan.pattern_name + "_data(shmooDac[I]);\n")
    f.write("\t\tRUN_PATTERN(" + plan.pattern_name + ":START," + plan.pattern_name
            + ":END,1,TS_5MHZ);\n")
    f.write("\t\tswitch(I)\n\t\t{\n")
    for index, point in enumerate(points):
        f.write("\t\tcase " + str(index) + ":\n")
        if plan.pass_fail:
            Force_Judge(plan.unit, plan.meas_pin, plan.force_value, point.target, 10,
                        "JUDGE", "PMU", point.low_range, point.high_range,
                        point.log_name, "no", f)
        else:
            measure = "LOGIC_PPMU_MI" if "A" in plan.unit else "LOGIC_PPMU_MV"
            f.write("\t\t\t" + measure + "(" + plan.meas_pin
                    + ", MEAS_LOOP=8, AVG , LOG_ALIAS=" + point.log_name
                    + ", LOG_UNIT=" + plan.unit + ");\n")
        f.write("\t\t\tbreak;\n")
    f.write("\t\t}\n\t}\n")
    f.write("\tCALL_MACRO set_" + plan.pattern_name + "_data("
            + str(int(plan.default_value, 2)) + ");\n\n")
    f.write("\tRUN_PATTERN(exit_fbist_mode:START,exit_fbist_mode:END,1,TS_5MHZ);\n\n")
    if plan.unit == "V" and plan.force_value != "0uA":
        Force_Judge("V", plan.meas_pin, "0uA", force_point.target, 2, "FORCE", "PPMU",
                    force_point.low_range, force_point.high_range, "", "no", f)
    elif "A" in plan.unit and plan.force_value != "0V":
        Force_Judge(plan.unit, plan.meas_pin, "0V", force_point.target, 2, "FORCE", "PPMU",
                    force_point.low_range, force_point.high_range, "", "no", f)
    f.write("\tCALL_MACRO POWER_OFF();\n\n")
    _emit_flow_relay(f, relay, enabled=False)
    f.write("\tCONDITION\n\t\tIF_FAIL\n\t\tREJECT_BIN = " + str(plan.hbin) + ";\n@@END_PLAN\n\n")


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
            f, result, 16, "-J", 0, register,
            "REG_" + register.upper() + "[T_SOCKET]",
            register.lower() + "_", complement, "arr",
        )

    return write_commit_shmoo(
        code_name,
        f,
        plan,
        state=G,
        copy_file=copy_file,
        pattern_capture=epr_pattern_capture,
        load_register=load_register,
        failed_uid_reerase=lambda result: write_uid_failed_site_reerase(
            f, result, vcc=plan.vcc
        ),
    )


def write_full_scan_best_update(f, dac_final_name, explicit_codes):
    """Record the tested DAC value; legacy natural scans keep their old index form."""
    final_value = "trimDac[T_SOCKET]" if explicit_codes else "cyc - 1"
    f.write(
        '\t\t\tif(fabs(GB[2+T_SOCKET*64]-trimTar)<fabs(trimFinalValue[T_SOCKET]-trimTar))\n'
        '\t\t\t{\n'
        '\t\t\t\ttrimFinalValue[T_SOCKET] = GB[2+T_SOCKET*64];\n'
        '\t\t\t\t' + dac_final_name + '[T_SOCKET] = ' + final_value + ';\n'
        '\t\t\t}\n\n'
    )


def _recipe_duration(duration):
    if duration is None:
        return None
    return duration.canonical


def _write_recipe_wait(f, duration, indent):
    if duration is not None:
        f.write(f"{indent}WAIT({_recipe_duration(duration)});\n")


def _addr_map_literal_value(value):
    """Return a concrete ADDR_MAP Verilog literal's numeric value."""
    text = str(value).strip().replace("’", "'").replace("‘", "'")
    match = re.fullmatch(r"\d+\s*'\s*([hHbBdD])\s*([0-9a-fA-F_]+)", text)
    if not match:
        return None
    base = {"h": 16, "b": 2, "d": 10}[match.group(1).lower()]
    return int(match.group(2).replace("_", ""), base)


def _otp_verify_register_var(flow_item):
    """Return the declared S100 register buffer for an OTP verify item.

    FLOW item names describe tests (for example ``Ts_30C_Verify``), while the
    writable software buffer is named after the ADDR_MAP register field
    (``REG_REG_TS_30C``).  They must not be derived from one another.
    """
    item_key = _flow_item_key(flow_item)
    for row, mapped_items in enumerate(G.col("ADDR_MAP", "CP addr map")):
        if G.col("ADDR_MAP", "data type")[row] != "lable":
            continue
        if item_key not in _flow_item_key(mapped_items):
            continue
        for column in ("bit[15:0]", "bit[31:16]"):
            field = str(G.col("ADDR_MAP", column)[row]).split("[")[0].strip()
            if re.fullmatch(r"[A-Za-z_]\w*", field):
                return "REG_" + field.upper()
    raise ValueError(
        "FLOW item " + str(flow_item) +
        " is marked OTP=yes but has no named ADDR_MAP register field"
    )


def parse_fv_fi(fv_fi, meas_pin):
    """FV/FI → [(force_pin, force_value_str), ...]（2026-07-21 移植自 chroma/writers.py，
    与 Chroma F token 同步）：force pin 与 measure pin 解耦。'+' 分隔多段（不用 '-'，
    避免和负值如 -6mA 冲突）；每段 '<PIN>:值' 指定 force 到该 pin，无前缀则 force 到
    meas_pin。'/' 或空 → [](不 force)。值原样保留，调用方按单位/变量处理。"""
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


def _force_pass_write(f, z):
    """FLOW.item 绿色标记（`G.flow_row_flag(z)=="force_pass"`）：强制该测试项 PASS。
    2026-07-06 用户裁决——**跟 Chroma 侧不同**：Chroma 只在 `verify_item_write` 里
    支持这个标记，S100 这边用户要求**对所有 type 类型都生效**（trim/verify/os/hex/
    keil/main/VT/uid/id/...），所以做成一个共享小函数，在每个 @@PLAN 收尾的
    `CALL_MACRO POWER_OFF()` 之后、`CONDITION IF_FAIL` 之前统一调用（该点之后原有的
    电性判定/CONDITION 就不会再推翻这个强制结果——CONDITION IF_FAIL 是判"跑的过程中
    有没有 fail"，SYS_SetTestResult(PASS) 是显式覆盖当前 site 的结果，两者不冲突）。
    真实写法来自用户提供的参考（逐 site 判活后强制 PASS，不活的 site 跳过）。"""
    if G.flow_row_flag(z) != "force_pass":
        return
    f.write("	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n	{\n"
            "		if(Sys_ActiveSite[T_SOCKET]==0)continue;\n"
            "		SYS_SetTestResult(PASS, T_SOCKET);\n	}\n\n")


def _trim_variable_slots(lines):
    """筛出这组 description 行里真正要当 trim_data() 参数的字段——只有含 "=x"（可变
    trim 值占位符）的行，`pattern_files.py:fbist_pattern_created` 才会在 .sd 里写对应
    的 `<serial>_data` 标签、才有全局 `<NAME>DAC_FINAL` 变量；不含 "=x" 的纯字面量固定
    值行（如 `HSI_TC_TRIMCR_VDDK[3:0]=1000`）只是烤进 .sd 的常量，没有标签也没有全局
    变量，当成参数会导致引用不存在的全局变量（同 chroma/writers.py，2026-07-06 移植）。
    保留原始下标 d（`serial_number[d]` 要跟 pattern_files.py 写标签时用的下标 d 完全
    一致，过滤掉字面量行后不能重新连续编号）。"""
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


def _dac_adj_apply(dac_final_name, delta, bisection, dac_bit):
    """生成"给 DAC_FINAL 加减档"的边界安全代码。同 chroma/writers.py:_dac_adj_apply
    语义移植（2026-07-06），只是站点变量名换成 S100 的 T_SOCKET（Chroma 用 SOCKET）。
    **线性**（`bisection=="no"`，Dac_Loop 变体，DAC_FINAL 就是 0..2^bit-1 的原始码）
    直接对码值加减、夹到 [0,2^bit-1]。**折线**（`bisection=="yes"` 时函数体里已声明的
    `dacArray`——`FLOW.LINE=="yes"` 是单调 0..2^bit-1，`"no"` 则是 `step` 列给的自定义
    非单调排布）不能直接对原始码加减，要对 `dacFinalIndex[T_SOCKET]`（收敛过程中跟
    DAC_FINAL 同步记录的"历史最优"下标，见 trim_item_write 里
    `if(fabs(...)<fabs(...))` 那段）加减、夹到数组范围，再映射回 dacArray 的值——
    不能用循环末尾的 dacIndex（那是"下一轮该探的点"，从没被真正测量过）。"""
    max_code = pow(2, dac_bit) - 1
    if bisection == "yes":
        return (
            "			dacFinalIndex[T_SOCKET] += " + str(delta) + ";\n"
            "			if(dacFinalIndex[T_SOCKET]<0) dacFinalIndex[T_SOCKET] = 0;\n"
            "			if(dacFinalIndex[T_SOCKET]>(int)(sizeof(dacArray)/sizeof(dacArray[0]))-1) dacFinalIndex[T_SOCKET] = (int)(sizeof(dacArray)/sizeof(dacArray[0]))-1;\n"
            "			" + dac_final_name + "[T_SOCKET] = dacArray[dacFinalIndex[T_SOCKET]];\n"
        )
    return (
        "			" + dac_final_name + "[T_SOCKET] += " + str(delta) + ";\n"
        "			if(" + dac_final_name + "[T_SOCKET]<0) " + dac_final_name + "[T_SOCKET]=0;\n"
        "			if(" + dac_final_name + "[T_SOCKET]>" + str(max_code) + ") " +
        dac_final_name + "[T_SOCKET]=" + str(max_code) + ";\n"
    )


_DAC_ADJ_UNCOND_RE = re.compile(r"^([+-]\d+)$")
_DAC_ADJ_COND_RE = re.compile(r"^([<>])\s*(-?\d+(?:\.\d+)?)\s*:\s*([+-]\d+)$")


def _dac_adj_spec(z):
    """解析 FLOW."DAC ADJ" 列（trim 项收敛后手动加减档）。同 chroma/writers.py:
    _dac_adj_spec 逐字移植（2026-07-06，用户要求逻辑跟 Chroma 侧一致）。老母本没有
    这列，或填 "/"/空 时返回 None（不加档，行为与之前完全一致）。
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


def Force_Judge(type, pin, fvalue, mvalue, space, used, source, l_range, h_range,log ,shmoo,f,force_wait=None):
    # 缩进归一(2026-06-12)：space 实参 0/2→1 级、6→2 级，输出 TAB 缩进
    space_num = "\t" * ((space + 4) // 4)
    if used == "FORCE":
        if source == "PPMU":
            if "A" in type:
                f.write(space_num + "LOGIC_PPMU_FV(" + pin + ", " + fvalue + ",  E1,")
                # 2026-07-14 #6 审查：补上界兜底（uA>=512 / mA>=32 原来漏 range 档
                # → 残缺 LOGIC_PPMU_FV），超量程抛异常。
                if type == "uA":
                    if abs(mvalue) < 2:
                        f.write(" I1")
                    elif abs(mvalue) < 8:
                        f.write(" I2")
                    elif abs(mvalue) < 32:
                        f.write(" I3")
                    elif abs(mvalue) < 128:
                        f.write(" I4")
                    elif abs(mvalue) < 512:
                        f.write(" I5")
                    else:
                        raise ValueError("LOGIC_PPMU_FV: 判据电流 " + str(mvalue)
                                         + "uA 超出 PPMU 量程上限 512uA（pin=" + pin + "）")
                if type == "mA":
                    if abs(mvalue) < 2:
                        f.write(" I6")
                    elif abs(mvalue) < 8:
                        f.write(" I7")
                    elif abs(mvalue) < 32:
                        f.write(" I8")
                    else:
                        raise ValueError("LOGIC_PPMU_FV: 判据电流 " + str(mvalue)
                                         + "mA 超出 PPMU 量程上限 32mA（pin=" + pin + "）")

                f.write(");\n")
                f.write(space_num + "WAIT(" + (_recipe_duration(force_wait) or "3MS") + ");\n")
            if "V" in type:
                f.write(space_num + "LOGIC_PPMU_FI(" + pin + ", " + fvalue)
                # 2026-07-14 #6 审查：原用 int(mvalue) 截断（如 -0.6→0 归错 E 档），改 float。
                _mv = float(mvalue)
                if _mv < 0:
                    f.write(", E3, I1);\n")
                elif _mv < 3.5:
                    f.write(", E1, I1);\n")
                elif _mv < 7.0:
                    f.write(", E2, I1);\n")
                else:
                    f.write(", E1, I1);\n")
                f.write(space_num + "WAIT(" + (_recipe_duration(force_wait) or "3MS") + ");\n")
        if source == "PMU":
            if "A" in type:
                f.write(space_num + "LOGIC_PPMU_FV(" + pin + ", " + fvalue + ",  E1,")
                # 2026-07-14 #6 审查：补上界兜底（uA>=512 / mA>=32 原来漏 range 档
                # → 残缺 LOGIC_PPMU_FV），超量程抛异常。
                if type == "uA":
                    if abs(mvalue) < 2:
                        f.write(" I1")
                    elif abs(mvalue) < 8:
                        f.write(" I2")
                    elif abs(mvalue) < 32:
                        f.write(" I3")
                    elif abs(mvalue) < 128:
                        f.write(" I4")
                    elif abs(mvalue) < 512:
                        f.write(" I5")
                    else:
                        raise ValueError("LOGIC_PPMU_FV: 判据电流 " + str(mvalue)
                                         + "uA 超出 PPMU 量程上限 512uA（pin=" + pin + "）")
                if type == "mA":
                    if abs(mvalue) < 2:
                        f.write(" I6")
                    elif abs(mvalue) < 8:
                        f.write(" I7")
                    elif abs(mvalue) < 32:
                        f.write(" I8")
                    else:
                        raise ValueError("LOGIC_PPMU_FV: 判据电流 " + str(mvalue)
                                         + "mA 超出 PPMU 量程上限 32mA（pin=" + pin + "）")

                f.write(");\n")
                f.write(space_num + "WAIT(" + (_recipe_duration(force_wait) or "3MS") + ");\n")
            if "V" in type:
                f.write(space_num + "LOGIC_PPMU_FI(" + pin + ", " + fvalue)
                # 2026-07-14 #6 审查：原用 int(mvalue) 截断（如 -0.6→0 归错 E 档），改 float。
                _mv = float(mvalue)
                if _mv < 0:
                    f.write(", E3, I1);\n")
                elif _mv < 3.5:
                    f.write(", E1, I1);\n")
                elif _mv < 7.0:
                    f.write(", E2, I1);\n")
                else:
                    f.write(", E1, I1);\n")
                f.write(space_num + "WAIT(" + (_recipe_duration(force_wait) or "3MS") + ");\n")

        if source == "MLDPS":
            if "A" in type:
                f.write(space_num + "FORCE_V_MLDPS(" + pin + ", " + fvalue + ",@6V,")
                # 2026-07-14 #6 审查：同 chroma——原严格 < / > 致边界裸值漏档 +
                # mA>=500 / A>=1 无兜底，改半开区间 + 超上界抛异常。
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
                f.write(space_num + "FORCE_I_MLDPS(" + pin + ", " + fvalue + ", ,")
                f.write(", @25mA,@6V,2V,NORM,ON," + (_recipe_duration(force_wait) or "2mS") + ");\n")
        if source == "FREQ":
            if pin == "TP":
                f.write(space_num + "LOGIC_SET_CMP_LEVEL(" + pin + ", 0.8V, 0.3V, VR1);\n")
            else:
                # 2026-07-20：原写 `0.55*_C_VCC_TYP, 0.25*_C_VCC_TYP`（数字*VOLTAGE 常量）
                # YT5100 编译报 `Unknown '0.25*_C_VCC_TYP'`（PLAN 上下文不认这种表达式，此
                # 分支此前从没被非 TP 频率项真编译过、属潜伏 bug）。对齐 golden
                # `temp/LAB_PY32F420A/Z_*.prg:1958` 的固定阈值写法（测频用对称单一门限）。
                f.write(space_num + "LOGIC_SET_CMP_LEVEL(" + pin + ", 2V, 2V, VR1);\n")
            f.write(space_num + "WAIT(" + (_recipe_duration(force_wait) or "3MS") + "); \n")
            f.write(space_num + "LOGIC_TMU_STARTPIN(" + pin + ", VOH, POS);  // Should use VOH for STARTPIN\n")
            f.write(space_num + "LOGIC_TMU_STOPPIN(" + pin + ", VOL, POS);  // Should use VOL for STARTPIN\n")

    if used == "JUDGE":
        if source == "C_COMPARE":
            f.write(space_num + "C_COMPARE(" + pin + ", DOWN_LIMIT=" + str(
                calc_limit(mvalue, l_range, h_range, True)) + ', UP_LIMIT=' + str(
                calc_limit(mvalue, l_range, h_range, False)) + ", LOG_ALIAS="+str(log)+", LOG_UNIT="+str(type)+");\n")

        if source == "PPMU":
            if "A" in type:
                if shmoo == "no":
                    if log == "null":
                        f.write(space_num + "LOGIC_PPMU_MI(" + pin + ", DOWN_LIMIT=" + str(
                            calc_limit(mvalue, l_range, h_range, True)) + type + ', UP_LIMIT=' + str(
                            calc_limit(mvalue, l_range, h_range, False)) + type + ", MEAS_LOOP=8, AVG);\n")
  
                    else:
                        f.write(space_num + "LOGIC_PPMU_MI(" + pin + ", DOWN_LIMIT=" + str(
                            calc_limit(mvalue, l_range, h_range, True)) + type + ', UP_LIMIT=' + str(
                            calc_limit(mvalue, l_range, h_range, False)) + type + ", MEAS_LOOP=8, AVG , LOG_ALIAS="+str(log)+", LOG_UNIT="+str(type)+");\n")
                else:
                    f.write(space_num + "LOGIC_PPMU_MI(" + pin + ", MEAS_LOOP=8, AVG);\n")
      
            if "V" in type:
                if shmoo == "no":
                    if log == "null":
                        f.write(space_num + "LOGIC_PPMU_MV(" + pin + ", DOWN_LIMIT=" + str(
                            calc_limit(mvalue, l_range, h_range, True)) + type + ', UP_LIMIT=' + str(
                            calc_limit(mvalue, l_range, h_range, False)) + type + ", MEAS_LOOP=8, AVG);\n")
  
                    else:
                        f.write(space_num + "LOGIC_PPMU_MV(" + pin + ", DOWN_LIMIT=" + str(
                            calc_limit(mvalue, l_range, h_range, True)) + type + ', UP_LIMIT=' + str(
                            calc_limit(mvalue, l_range, h_range, False)) + type + ", MEAS_LOOP=8, AVG , LOG_ALIAS="+str(log)+", LOG_UNIT="+str(type)+");\n")
                else:
                    f.write(space_num + "LOGIC_PPMU_MV(" + pin + ", MEAS_LOOP=8, AVG);\n")
        if source == "PMU":
            if "A" in type:
                if shmoo == "no":
                    if log == "null":
                        f.write(space_num + "LOGIC_PPMU_MI(" + pin + ", DOWN_LIMIT=" + str(
                            calc_limit(mvalue, l_range, h_range, True)) + type + ', UP_LIMIT=' + str(
                            calc_limit(mvalue, l_range, h_range, False)) + type + ", MEAS_LOOP=8, AVG);\n")

                    else:
                        f.write(space_num + "LOGIC_PPMU_MI(" + pin + ", DOWN_LIMIT=" + str(
                            calc_limit(mvalue, l_range, h_range, True)) + type + ', UP_LIMIT=' + str(
                            calc_limit(mvalue, l_range, h_range, False)) + type + ", MEAS_LOOP=8, AVG , LOG_ALIAS="+str(log)+", LOG_UNIT="+str(type)+");\n")
                else:
                    f.write(space_num + "LOGIC_PPMU_MI(" + pin + ", MEAS_LOOP=8, AVG);\n")
      
            if "V" in type:
                if shmoo == "no":
                    if log == "null":
                        f.write(space_num + "LOGIC_PPMU_MV(" + pin + ", DOWN_LIMIT=" + str(
                            calc_limit(mvalue, l_range, h_range, True)) + type + ', UP_LIMIT=' + str(
                            calc_limit(mvalue, l_range, h_range, False)) + type + ", MEAS_LOOP=8, AVG);\n")
                 
                    else:
                        f.write(space_num + "LOGIC_PPMU_MV(" + pin + ", DOWN_LIMIT=" + str(
                            calc_limit(mvalue, l_range, h_range, True)) + type + ', UP_LIMIT=' + str(
                            calc_limit(mvalue, l_range, h_range, False)) + type + ", MEAS_LOOP=8, AVG , LOG_ALIAS="+str(log)+", LOG_UNIT="+str(type)+");\n")
                else:
                    f.write(space_num + "LOGIC_PPMU_MV(" + pin + ", MEAS_LOOP=8, AVG);\n")

        if source == "MLDPS":
            if "A" in type:
                if shmoo == "no":
                    if log == "null":
                        f.write(space_num + "LOGIC_DPS_MI(" + pin + ", DOWN_LIMIT=" + str(
                        calc_limit(mvalue, l_range, h_range, True)) + type + ', UP_LIMIT=' + str(
                        calc_limit(mvalue, l_range, h_range, False)) + type + ", MEAS_LOOP=8, AVG);\n")
                    else:
                        f.write(space_num + "LOGIC_DPS_MI(" + pin + ", DOWN_LIMIT=" + str(
                        calc_limit(mvalue, l_range, h_range, True)) + type + ', UP_LIMIT=' + str(
                        calc_limit(mvalue, l_range, h_range, False)) + type + ", MEAS_LOOP=8, AVG , LOG_ALIAS="+str(log)+", LOG_UNIT="+str(type)+");\n")
          
            if "V" in type:
                if shmoo == "no":
                    f.write(space_num + "LOGIC_DPS_MI(" + pin + ", DOWN_LIMIT=" + str(
                        calc_limit(mvalue, l_range, h_range, True)) + type + ', UP_LIMIT=' + str(
                        calc_limit(mvalue, l_range, h_range, False)) + type + ", MEAS_LOOP=8, AVG ,LOG_ALIAS="+str(log)+", LOG_UNIT="+str(type)+");\n")

        if source == "FREQ":
            if "Hz" in type:
                if shmoo == "no":
                    if mvalue < 100 and "hz" in type.lower():
                        f.write(space_num + "LOGIC_TMU_SET_AND_START(CMD_TRIG, NULL, AVG=128, HYS_ON);\n")
                    elif mvalue > 100 and "hz" in type.lower():
                        f.write(space_num + "LOGIC_TMU_SET_AND_START(CMD_TRIG, NULL, AVG=128, HYS_ON);\n")
                    f.write(space_num + "WAIT(3MS); \n")
                    if log == "null":
                        f.write(space_num + "LOGIC_TMU_MEAS_FREQ(" + "DOWN_LIMIT=" + str(
                        calc_limit(mvalue, l_range, h_range, True)) + type + ', UP_LIMIT=' + str(
                calc_limit(mvalue, l_range, h_range, False)) + type + ",TIME_OUT=50mS);\n")
                    else:
                        f.write(space_num + "LOGIC_TMU_MEAS_FREQ(" + "DOWN_LIMIT=" + str(
                        calc_limit(mvalue, l_range, h_range, True)) + type + ', UP_LIMIT=' + str(
                calc_limit(mvalue, l_range, h_range, False)) + type + ",TIME_OUT=50mS, LOG_ALIAS="+str(log)+", LOG_UNIT="+str(type)+");\n")
                else:
                    if mvalue < 100 and "hz" in type.lower():
                        f.write(space_num + "LOGIC_TMU_SET_AND_START(CMD_TRIG, NULL, AVG=128, HYS_ON);\n")
                    elif mvalue > 100 and "hz" in type.lower():
                        f.write(space_num + "LOGIC_TMU_SET_AND_START(CMD_TRIG, NULL, AVG=128, HYS_ON);\n")
                    f.write(space_num + "WAIT(3MS); \n")
                    if log == "null":
                        f.write(space_num + "LOGIC_TMU_MEAS_FREQ(TIME_OUT=50mS);\n")
                    else:
                        f.write(space_num + "LOGIC_TMU_MEAS_FREQ(TIME_OUT=50mS, LOG_ALIAS="+str(log)+", LOG_UNIT="+str(type)+");\n")


def _emit_trim_pe_boundary(f, pattern_names, start):
    """Emit the S100 PE half-pattern around a final DAC measurement phase."""
    for pattern_name in pattern_names:
        begin_label, end_label = (("START", "pe_1") if start else ("pe_1", "END"))
        f.write("\tRUN_PATTERN(" + pattern_name + ":" + begin_label + "," +
                pattern_name + ":" + end_label + ",1,TS_5MHZ);\n\n")


def _trim_pe_pattern_names(z):
    pe_mode = str(G.col("FLOW", "PE")[z]).strip().upper()
    if pe_mode == "ERASE":
        return list(G.nm_patterns("page erase 1st"))
    if pe_mode == "PROGRAM":
        return list(G.nm_patterns("page program PCKB 1st"))
    return []


def _emit_trim_final_dac_measure(f, trim_data_call, unit, meas_pin, force_value,
                                 target, low_range, high_range, pe_patterns=(),
                                 start_pe=True, end_pe=True):
    """Write one final DAC value to the DUT, then measure and capture its real result."""
    f.write(trim_data_call)
    if start_pe:
        _emit_trim_pe_boundary(f, pe_patterns, start=True)
    source = "FREQ" if "Hz" in unit else "PPMU"
    Force_Judge(
        unit, meas_pin, force_value, target, 2, "JUDGE", source,
        widen_pct(low_range, 50), widen_pct(high_range, 50), "null", "final", f,
    )
    f.write("\tC_ASSIGN(GB3," + meas_pin + ");\n")
    if "Hz" in unit:
        f.write("\tC_DIV(GB3, 1000);\n\n")
    elif "uA" in unit:
        f.write("\tC_MUL(GB3,1000000);\n\n")
    if end_pe:
        _emit_trim_pe_boundary(f, pe_patterns, start=False)


def write_pat_mem(f, result, bit, way, tabspace, write_item, write_temp, write_label, pn,aoi, fast_mode=False, read_dc=False):
    break_space = tabspace * " "
    F_num = int(((bit + 1) / 4)) * "F"
    # bake 结转字段重写（core/flash_seq.py Part B 生效后）参考程序里 hsi/vrefint/ts/
    # vrefbuf* 每一次 LOGIC_WRITE_PATTERN_MEMORY 都多带一个 FAST_MODE 参数（早写/晚写/
    # bake 三处都要，用户已确认不是 bake 专属）；其余既有调用方不传这个参数，行为不变。
    fast_suffix = ",FAST_MODE" if fast_mode else ""
    # read_dc=True：读侧比较值用 DATA1=X,DATA0=X（don't care，参考程序 ts_125c 字段
    # 就是这么写的）——bake 结转 seed 步骤专用，这一步只是把软件缓冲区跟"芯片里现在
    # 实际是什么"对齐，不需要、也不该去校验读回值，真正的校验留给 final 改写之后的
    # erase→prog→read。
    read_cmp = "DATA1=X,DATA0=X" if read_dc else "DATA1=H,DATA0=L"
    # f.write(break_space+"	SOCKET_INC(FRZ_OFF)\n	{\n")
    f.write(break_space + "	//******************" + write_item + "**************************\n")
    if aoi == "arr":
        f.write(break_space + "	CALL_MACRO write_pat_temp_arry(" + write_temp + "); // data\n")
    else:
        f.write(break_space + "	CALL_MACRO write_pat_temp_fixed(" + write_temp + "); // data\n")
    if pn == "yes":
        f.write(
            break_space +"	LOGIC_WRITE_PATTERN_MEMORY(" +result["pgm"]+":"+write_label + "w_p_st, " +result["pgm"]+":"+write_label + "w_p_sp, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", GB1, BIT_COUNT=" + str(bit) + ', SERIAL,MSB_LSB' + fast_suffix + ');\n')
        f.write(
            break_space +"	LOGIC_WRITE_PATTERN_MEMORY(" +result["read"]+":"+write_label + "r_p_st, " +result["read"]+":"+write_label + "r_p_sp, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", GB1, BIT_COUNT=" + str(bit) + ', SERIAL,MSB_LSB,' + read_cmp + fast_suffix + ');\n\n')
        if aoi == "arr":
            f.write(break_space + "	CALL_MACRO Bitwise_not_arry(" + write_temp + "); // data\n")
        else:
            f.write(break_space + "	CALL_MACRO Bitwise_not_fixed(" + write_temp + "); // data\n")

        f.write(
            break_space +"	LOGIC_WRITE_PATTERN_MEMORY(" +result["pgm"]+":"+write_label + "w_n_st, " +result["pgm"]+":"+write_label + "w_n_sp, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", GB1, BIT_COUNT=" + str(bit) + ', SERIAL,MSB_LSB' + fast_suffix + ');\n')
        f.write(
            break_space +"	LOGIC_WRITE_PATTERN_MEMORY(" +result["read"]+":"+write_label + "r_n_st, " +result["read"]+":"+write_label + "r_n_sp, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", GB1, BIT_COUNT=" + str(bit) + ', SERIAL,MSB_LSB,' + read_cmp + fast_suffix + ');\n\n')

    else:
        f.write(
            break_space +"	LOGIC_WRITE_PATTERN_MEMORY(" +result["pgm"]+":"+write_label + "w_st, " +result["pgm"]+":"+write_label + "w_sp, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", GB1, BIT_COUNT=" + str(bit) + ', SERIAL,MSB_LSB' + fast_suffix + ');\n')
        f.write(
            break_space +"	LOGIC_WRITE_PATTERN_MEMORY(" +result["read"]+":"+write_label + "r_st, " +result["read"]+":"+write_label + "r_sp, " + str(G.col("VERSION", "SWD PIN")[G.i]) + ", GB1, BIT_COUNT=" + str(bit) + ', SERIAL,MSB_LSB,' + read_cmp + fast_suffix + ');\n')


def _uid_pn_flag(temp_item_name):
    """按 ADDR_MAP uid 页该字段的真实数据判断是否为"正码+反码"关系（供 write_pat_mem
    的 pn 参数用）。逐字移植自 chroma/writers.py:_uid_pn_flag（2026-07-03 chroma 侧修复，
    2026-07-17 补到 S100）：S100 的 uid_write 原先跟修复前的 chroma 一样硬编码 pn="yes"，
    把所有 uid trim 字段当反码、引用 <label>w_p/w_n/r_p/r_n 四标签，但 flash 页 .sd 的
    label 生成端只对真含"反码"标记的字段才造这四标签，非反码字段（如 Hsi_8/16/24/48M_Trim，
    高 16bit 是常量 0）只造平 w/r 标签——两边不一致，YT5100 编译报 "pattern ... defined
    without any pattern labels"。规则与 flash_pattern_label_created 一致：uid 页某行
    bit[31:16] 含"反码"、或 bit[15:0] 含"bit[31:16]的反码"，才是 "yes"；找不到保守回 "no"。"""
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


def hex_code_item_write(code_name, f, j):
    if G.col("FLOW", "type")[j] == "hex" and code_name[G.i].split("_")[-1] == \
            G.col("FLOW", "CP NO")[j]:
        f.write(G.col("FLOW", "item")[j] + "()\n{\n")
        f.write("	TEST_NUM=" + str((j + 1) * 100) + ";\n" + '	TEST_NO( TEST_NUM);DATALOG_MSG="' +
                G.col("FLOW", "item")[j] + '"; \n\n')
        f.write("	POWER_ON(_C_" + G.col("FLOW", "Vcc")[j] + ");\n\n")


        f.write('	POWER_OFF();\n	//POWER_DOWN_FAIL_SITE_X(MODE_B);\n\n')
        f.write("}\n\n")  # item{}


def _dac_final_addrmap_expr(name_prefix):
    """按 ADDR_MAP `CP addr map` 列里 "<name_prefix>Trim[..]" 这种共享寄存器位段声明，
    解出该字段所在寄存器（`bit[15:0]` 列）与位偏移，拼出 "(REG_xxx[T_SOCKET]&mask)>>shift"
    表达式；找不到返回 None。同 chroma/writers.py:_dac_final_addrmap_expr 逐字移植
    （2026-07-06，站点变量换 T_SOCKET），跟 `trim_data_read_write` 里 `set_all_final_vposp`
    之前那段 ADDR_MAP bit_list/shift 解码是同一套算法，抽出来给 `reuse_dac_restore_items`
    的跨 CP 补值场景复用（如 CP3 复用 CP1 已经 trim 好的 Hsi_Vrega，需要从 EPR 读回的
    共享寄存器里单独抠出这个字段）。"""
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
        return "(REG_" + reg_name + "[T_SOCKET]&" + bin_list_to_hex(bit_list) + ")>>" + str(shift)
    return None


def set_all_final_vposp(f):
    f.write("	//set all trimming final data to Fbist  vposp\n")

    G.set_vposp_name.clear()
    for z in range(len(G.col("FLOW", "PUMP"))):
        if G.col("FLOW", "PUMP")[z] == "yes":
            G.set_vposp_name.append(
                dac_final_symbol(G.col("FLOW", "item")[z]) + str(
                    G.col("FLOW", "DAC bit")[z]))
    flow_trim_items = [str(G.col("FLOW", "item")[j].split("Trim")[0]).upper().rstrip("_") for j in range(len(G.col("FLOW", "item")))]
    if "VCSL" not in flow_trim_items:
        G.set_vposp_name.append("VCSL_DAC_FINAL3")
    if "VNEG2" not in flow_trim_items:
        G.set_vposp_name.append("VNEG2_DAC_FINAL3")
    if "VBL" not in flow_trim_items:
        G.set_vposp_name.append("VBL_DAC_FINAL4")

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
                f.write("	//////////////////////user " + G.set_vposp_name[z].split("_")[
                    0] + "////////////////////////\n")
            else:
                f.write("	//////////////////////" + G.set_vposp_name[z].split("_")[
                    0] + "////////////////////////\n")
            f.write("	write_pat_temp_arry(" + G.set_vposp_name[z].rstrip("0123456789") + "); // data\n\n")
            if cyc == 1 and G.set_vposp_name[z].split("_")[0][-1].lower() == "p":
                f.write(
                    "	LOGIC_WRITE_PATTERN_MEMORY(set_all_final_vposp:prog_" +
                    G.set_vposp_name[z][1].lower() + "dac_st, " + "set_all_final_vposp:prog_" +
                    G.set_vposp_name[z][1].lower() + "dac_sp, " +str(G.col("VERSION", "SWD PIN")[G.i])+", GB1, BIT_COUNT="+ str(
                        int(G.set_vposp_name[z][-1])) + ', SERIAL,MSB_LSB);\n\n')
            elif cyc == 1 and G.set_vposp_name[z].split("_")[0][-1].lower() == "e":
                f.write(
                    "	LOGIC_WRITE_PATTERN_MEMORY(set_all_final_vposp:ers_" +
                    G.set_vposp_name[z][1].lower() + "dac_st, " + "set_all_final_vposp:ers_" +
                    G.set_vposp_name[z][1].lower() + "dac_sp, " +str(G.col("VERSION", "SWD PIN")[G.i])+", GB1, BIT_COUNT="+ str(
                        int(G.set_vposp_name[z][-1])) + ', SERIAL,MSB_LSB);\n\n')


            elif cyc == 0 and G.set_vposp_name[z].split("_")[0][-1].lower() == "p":
                f.write(
                    "	LOGIC_WRITE_PATTERN_MEMORY(set_all_final_vposp:pre_" +
                    G.set_vposp_name[z][1].lower() + "dac_st, " + "set_all_final_vposp:pre_" +
                    G.set_vposp_name[z][1].lower() + "dac_sp, " +str(G.col("VERSION", "SWD PIN")[G.i])+", GB1, BIT_COUNT="+ str(
                        int(G.set_vposp_name[z][-1])) + ', SERIAL,MSB_LSB);\n\n')
            else:
                f.write(
                    "	LOGIC_WRITE_PATTERN_MEMORY(set_all_final_vposp:" +
                    G.set_vposp_name[z].split("_")[0].lower() + "_st, " + "set_all_final_vposp:" +
                    G.set_vposp_name[z].split("_")[0].lower() + "_sp, " +str(G.col("VERSION", "SWD PIN")[G.i])+", GB1, BIT_COUNT="+ str(
                        int(G.set_vposp_name[z][-1])) + ', SERIAL,MSB_LSB);\n\n')


def _page_field_layout(
    page_name, read_bit, uid_write_dic=None, cp_num=None, catalog=None
):
    """Compile S100 capture slots through the shared ADDR_MAP catalog."""
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
            target = "\t\t" + symbol.upper() + "W[T_SOCKET]="
        else:
            target = "\t\tREG_" + entry.register.upper() + "[T_SOCKET]="
        result.append((target, entry.slot_width, entry.real_offset))
    return result


def _page_field_layout_legacy(page_name, read_bit, uid_write_dic=None, cp_num=None):
    """S100 版，跟 chroma/writers.py 的同名函数是同一套修法（纯 ADDR_MAP 分析，不涉及
    平台差异，两边各自维护一份跟已有的 temp_data_capture 平台各一份保持一致）。

    按 ADDR_MAP 某个 Word No.（page_name，如 "uid"/"trim0"/"trim1"/"factory3"）逐字段
    判断真实字节宽度：带反码标记的字段占 4 字节（正码+反码，只读其中真实的 2 字节），
    不带反码标记的字段只占 2 字节（如 uid 页的 Hsi_8/16/24/48M_Trim）。原来的 capture
    生成代码（uid_write() 的 bake 分支、trim_data_read_write() 的 Trimdata_Read 分支）
    都是整页只判一次"页内有没有任意字段带反码"（pn_num=1或2）就统一套用到所有字段
    头上，页内混了两种宽度时后面字段的字节偏移全部算错。这里逐字段判断真实宽度。

    uid_write_dic/cp_num：仅 uid 页的 Verify 字段需要——按 CP 门控（<=cp_num 才算
    已建立），沿用原 label_num 逻辑；trim0/trim1/factory3 的字段全是寄存器名（不含
    "Verify"），不受门控，两参数可不传。

    另外 read_bit>32（本项目=64）时硬件按 read_bit 位宽整块捕获，块内高位那部分先出——
    原 temp_data_capture()(pn="yes"分支) 靠 c32_num 分组+sum_flag 递减实现的就是这个
    反转，只是它假设组内每个字段都占 4 字节（同上面那个 bug 一样）。这里按 ADDR_MAP
    绝对行号每 gs=read_bit//32 行分一组，组内若有 ≥2 个通过门控的字段，把这些字段的
    先后顺序整体反转（只反转组内顺序，组间顺序不变），再按各自真实宽度顺序编号偏移。

    4 字节（带反码）字段内部也分先后：捕获是 MSB 先出，即 4 字节槽的前 2 字节固定对应
    bit[31:16]、后 2 字节对应 bit[15:0]。哪一半是"真实值"由反码标记出现在哪一列决定
    （标记出现在 bit[15:0] 列文本里，说明 bit[15:0]=反码、真实值在 bit[31:16]=前 2 字节；
    反过来标记在 bit[31:16] 列文本里，真实值就在 bit[15:0]=后 2 字节）——之前统一按"永远
    读前 2 字节"处理，遇到反码标记出现在 bit[31:16] 列（真实值在 bit[15:0]/后 2 字节）
    的母本就会把反码值当成真实值读错（同 chroma/writers.py 的问题，用 program_PCD009_V0.4
    在 Chroma 侧实测坐实；S100 走 Sys_SW_BUFFER_DATA/DAQ_ARRAY_TRANSFER，字节序假定与
    Chroma 一致，同步改掉，未单独上机核实）。
    返回 [(type_flag_str, width, sub_off), ...]，type_flag_str 已带 S100 的 [T_SOCKET]
    后缀，sub_off 是真实 2 字节在其所在槽内的起始偏移（0 或 2）。"""
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
                width, real_val, sub_off = 4, b31, 0
            elif "反码" in b31:
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
                    type_flag = "\t\tREG_" + real_val.split("[")[0].upper() + "[T_SOCKET]="
                else:
                    type_flag = "\t\t" + real_val.split("Verify")[0].upper() + "W[T_SOCKET]="
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


def temp_data_capture(f, cyc, pn, bit, code_name):
    addr_map_item = []
    uid_flag = ""
    bit_015_1631_flag1 = 0
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

    # 同一个 item 名字可能在多个 CP 里都标 UID==yes（如某 trim 项在 CP1/CP3 都是），
    # dict(zip(...)) 遇重复 key 会后写覆盖先写，把该项"起算 CP"错记成最后一次出现的
    # CP，后面 "<=当前CP" 的判断就会因为这个被错记的值而漏判。改用 setdefault 保留
    # 第一次出现（即最早/最小的 CP digit），跟 FLOW 表按 CP 顺序排列的既有假设一致
    # （同 Chroma 2026-07-06 修的一样，此处是 S100 自己的同款 bug）。
    uid_write_dic = {}
    for _name, _num in zip(uid_write_item, uid_write_num):
        uid_write_dic.setdefault(_name, _num)

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
                    bit_015_1631_flag1 = 1
                    temp_item_flag = "bit[15:0]"
                
                temp_item_value = str(list(G.ADDR_MAP[temp_item_flag])[i+page_word*cyc]).lower()
                if "verify" not in temp_item_value:
                    type_flag1 = "		REG_" + list(G.ADDR_MAP[temp_item_flag])[i+page_word*cyc].split("[")[0].upper() + "[T_SOCKET]="
                elif "verify" in temp_item_value:
                    if G.col("ADDR_MAP", "Word No.")[i+page_word*cyc] == "uid":
                        if uid_write_dic[list(G.ADDR_MAP[temp_item_flag])[i+page_word*cyc]] <= int(code_name.split("_")[-1][-1]):
                            type_flag1 = "		" + list(G.ADDR_MAP[temp_item_flag])[i+page_word*cyc].split("Verify")[
                                0].upper() + "W[T_SOCKET]="
                    else:
                        type_flag1 = "		" + list(G.ADDR_MAP[temp_item_flag])[i+page_word*cyc].split("Verify")[
                            0].upper() + "W[T_SOCKET]="
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
                    
                    temp_item_value = str(list(G.ADDR_MAP[temp_item_flag])[i+1+page_word*cyc]).lower()
                    if "verify" not in temp_item_value:
                        type_flag2 = "		REG_" + list(G.ADDR_MAP[temp_item_flag])[i+1+page_word*cyc].split("[")[0].upper() + "[T_SOCKET]="
                    elif "verify" in temp_item_value:
                        if G.col("ADDR_MAP", "Word No.")[i+1+page_word*cyc] == "uid":
                            if uid_write_dic[list(G.ADDR_MAP[temp_item_flag])[i+1+page_word*cyc]] <= int(code_name.split("_")[-1][-1]):
                                type_flag2 = "		" + list(G.ADDR_MAP[temp_item_flag])[i+1+page_word*cyc].split("Verify")[
                                    0].upper() + "W[T_SOCKET]="
                        else:
                            type_flag2 = "		" + list(G.ADDR_MAP[temp_item_flag])[i+1+page_word*cyc].split("Verify")[
                                0].upper() + "W[T_SOCKET]="
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
                    
                    temp_item_value = str(list(G.ADDR_MAP[temp_item_flag])[i+2+page_word*cyc]).lower()
                    if "verify" not in temp_item_value:
                        type_flag3 = "		REG_" + list(G.ADDR_MAP[temp_item_flag])[i+2+page_word*cyc].split("[")[0].upper() + "[T_SOCKET]="
                    elif "verify" in temp_item_value:
                        if G.col("ADDR_MAP", "Word No.")[i+2+page_word*cyc] == "uid":
                            if uid_write_dic[list(G.ADDR_MAP[temp_item_flag])[i+2+page_word*cyc]] <= int(code_name.split("_")[-1][-1]):
                                type_flag3 = "		" + list(G.ADDR_MAP[temp_item_flag])[i+2+page_word*cyc].split("Verify")[
                                    0].upper() + "W[T_SOCKET]="
                        else:
                            type_flag3 = "		" + list(G.ADDR_MAP[temp_item_flag])[i+2+page_word*cyc].split("Verify")[
                                0].upper() + "W[T_SOCKET]="
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
                    
                    temp_item_value = str(list(G.ADDR_MAP[temp_item_flag])[i+3+page_word*cyc]).lower()
                    if "verify" not in temp_item_value:
                        type_flag4 = "		REG_" + list(G.ADDR_MAP[temp_item_flag])[i+3+page_word*cyc].split("[")[0].upper() + "[T_SOCKET]="
                    elif "verify" in temp_item_value:
                        if G.col("ADDR_MAP", "Word No.")[i+3+page_word*cyc] == "uid":
                            if uid_write_dic[list(G.ADDR_MAP[temp_item_flag])[i+3+page_word*cyc]] <= int(code_name.split("_")[-1][-1]):
                                type_flag4 = "		" + list(G.ADDR_MAP[temp_item_flag])[i+3+page_word*cyc].split("Verify")[
                                    0].upper() + "W[T_SOCKET]="
                        else:
                            type_flag4 = "		" + list(G.ADDR_MAP[temp_item_flag])[i+3+page_word*cyc].split("Verify")[
                                0].upper() + "W[T_SOCKET]="
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
                    
                    temp_item_value = str(list(G.ADDR_MAP[temp_item_flag])[i+4+page_word*cyc]).lower()
                    if "verify" not in temp_item_value:
                        type_flag5 = "		REG_" + list(G.ADDR_MAP[temp_item_flag])[i+4+page_word*cyc].split("[")[0].upper() + "[T_SOCKET]="
                    elif "verify" in temp_item_value:
                        if G.col("ADDR_MAP", "Word No.")[i+4+page_word*cyc] == "uid":
                            if uid_write_dic[list(G.ADDR_MAP[temp_item_flag])[i+4+page_word*cyc]] <= int(code_name.split("_")[-1][-1]):
                                type_flag5 = "		" + list(G.ADDR_MAP[temp_item_flag])[i+4+page_word*cyc].split("Verify")[
                                    0].upper() + "W[T_SOCKET]="
                        else:
                            type_flag5 = "		" + list(G.ADDR_MAP[temp_item_flag])[i+4+page_word*cyc].split("Verify")[
                                0].upper() + "W[T_SOCKET]="
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
                    
                    temp_item_value = str(list(G.ADDR_MAP[temp_item_flag])[i+5+page_word*cyc]).lower()
                    if "verify" not in temp_item_value:
                        type_flag6 = "		REG_" + list(G.ADDR_MAP[temp_item_flag])[i+5+page_word*cyc].split("[")[0].upper() + "[T_SOCKET]="
                    elif "verify" in temp_item_value:
                        if G.col("ADDR_MAP", "Word No.")[i+5+page_word*cyc] == "uid":
                            if uid_write_dic[list(G.ADDR_MAP[temp_item_flag])[i+5+page_word*cyc]] <= int(code_name.split("_")[-1][-1]):
                                type_flag6 = "		" + list(G.ADDR_MAP[temp_item_flag])[i+5+page_word*cyc].split("Verify")[
                                    0].upper() + "W[T_SOCKET]="
                        else:
                            type_flag6 = "		" + list(G.ADDR_MAP[temp_item_flag])[i+5+page_word*cyc].split("Verify")[
                                0].upper() + "W[T_SOCKET]="
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
                    
                    temp_item_value = str(list(G.ADDR_MAP[temp_item_flag])[i+6+page_word*cyc]).lower()
                    if "verify" not in temp_item_value:
                        type_flag7 = "		REG_" + list(G.ADDR_MAP[temp_item_flag])[i+6+page_word*cyc].split("[")[0].upper() + "[T_SOCKET]="
                    elif "verify" in temp_item_value:
                        if G.col("ADDR_MAP", "Word No.")[i+6+page_word*cyc] == "uid":
                            if uid_write_dic[list(G.ADDR_MAP[temp_item_flag])[i+6+page_word*cyc]] <= int(code_name.split("_")[-1][-1]):
                                type_flag7 = "		" + list(G.ADDR_MAP[temp_item_flag])[i+6+page_word*cyc].split("Verify")[
                                    0].upper() + "W[T_SOCKET]="
                        else:
                            type_flag7 = "		" + list(G.ADDR_MAP[temp_item_flag])[i+6+page_word*cyc].split("Verify")[
                                0].upper() + "W[T_SOCKET]="
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
                    
                    temp_item_value = str(list(G.ADDR_MAP[temp_item_flag])[i+7+page_word*cyc]).lower()
                    if "verify" not in temp_item_value:
                        type_flag8 = "		REG_" + list(G.ADDR_MAP[temp_item_flag])[i+7+page_word*cyc].split("[")[0].upper() + "[T_SOCKET]="
                    elif "verify" in temp_item_value:
                        if G.col("ADDR_MAP", "Word No.")[i+7+page_word*cyc] == "uid":
                            if uid_write_dic[list(G.ADDR_MAP[temp_item_flag])[i+7+page_word*cyc]] <= int(code_name.split("_")[-1][-1]):
                                type_flag8 = "		" + list(G.ADDR_MAP[temp_item_flag])[i+7+page_word*cyc].split("Verify")[
                                    0].upper() + "W[T_SOCKET]="
                        else:
                            type_flag8 = "		" + list(G.ADDR_MAP[temp_item_flag])[i+7+page_word*cyc].split("Verify")[
                                0].upper() + "W[T_SOCKET]="
                else:
                    type_flag8 = "888[15:0]"
                    bit_015_1631_flag8 = 9
            if bit == 32:
                groups_type.append((str(bit_015_1631_flag1)+"&"+G.col("ADDR_MAP", "data type")[i+page_word*cyc]+"&"+type_flag1))

            if bit == 64:
                groups_type.append((str(bit_015_1631_flag1)+"&"+G.col("ADDR_MAP", "data type")[i+page_word*cyc]+"&"+type_flag1, str(bit_015_1631_flag2)+"&"+G.col("ADDR_MAP", "data type")[i+1+page_word*cyc]+"&"+type_flag2))

            if bit == 128:
                groups_type.append((str(bit_015_1631_flag1) + "&" + G.col("ADDR_MAP", "data type")[i + page_word*cyc] + "&" + type_flag1,
                                    str(bit_015_1631_flag2) + "&" + G.col("ADDR_MAP", "data type")[i + 1 + page_word*cyc] + "&" + type_flag2,
                                    str(bit_015_1631_flag3) + "&" + G.col("ADDR_MAP", "data type")[i + 2 + page_word*cyc] + "&" + type_flag3,
                                    str(bit_015_1631_flag4) + "&" + G.col("ADDR_MAP", "data type")[i + 3 + page_word*cyc] + "&" + type_flag4
                                    ))

            if bit == 256:
                groups_type.append((str(bit_015_1631_flag1) + "&" + G.col("ADDR_MAP", "data type")[i + page_word*cyc] + "&" + type_flag1,
                                    str(bit_015_1631_flag2) + "&" + G.col("ADDR_MAP", "data type")[i + 1 + page_word*cyc] + "&" + type_flag2,
                                    str(bit_015_1631_flag3) + "&" + G.col("ADDR_MAP", "data type")[i + 2 + page_word*cyc] + "&" + type_flag3,
                                    str(bit_015_1631_flag4) + "&" + G.col("ADDR_MAP", "data type")[i + 3 + page_word*cyc] + "&" + type_flag4,
                                    str(bit_015_1631_flag5) + "&" + G.col("ADDR_MAP", "data type")[i + 4 + page_word*cyc] + "&" + type_flag5,
                                    str(bit_015_1631_flag6) + "&" + G.col("ADDR_MAP", "data type")[i + 5 + page_word*cyc] + "&" + type_flag6,
                                    str(bit_015_1631_flag7) + "&" + G.col("ADDR_MAP", "data type")[i + 6 + page_word*cyc] + "&" + type_flag7,
                                    str(bit_015_1631_flag8) + "&" + G.col("ADDR_MAP", "data type")[i + 7 + page_word*cyc] + "&" + type_flag8
                                    ))

        # print(groups_type)
        label_num_flag = 0
        if bit == 32:
            for i in range(len(groups_type)):
                if groups_type[i].split("&")[1] == "lable" :
                    if groups_type[i].split("&")[2] != "888[15:0]":
                        # f.write(groups_type[i].split("&")[2] + addr_map_item[cyc] + "_0x00" + str(
                        #     list(ADDR_MAP["SM Address"])[0 + page_word*cyc].split(";")[0].split("0x")[1])
                        #         + "[T_SOCKET][" + str(0 + int(groups_type[i][0].split("&")[0]) + 4 * lable_num_flag) + "]*256+" + addr_map_item[
                        #             cyc] + "_0x00"
                        #         + str(list(ADDR_MAP["SM Address"])[0 + page_word*cyc].split(";")[0].split("0x")[
                        #                   1]) + "[T_SOCKET][" + str(1 + int(groups_type[i][0].split("&")[0]) + 4 * lable_num_flag) + "];\n")
                        f.write(groups_type[i].split("&")[2] + "Sys_SW_BUFFER_DATA[T_SOCKET][" + str(0 + int(groups_type[i][0].split("&")[0]) + 4 * label_num_flag) + "]*256+" + "Sys_SW_BUFFER_DATA[T_SOCKET][" + str(1 + int(groups_type[i][0].split("&")[0]) + 4 * label_num_flag) + "];\n")
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
                    # f.write(groups_type[i][int(index_list[z].split("&")[0])].split("&")[2] + addr_map_item[cyc] + "_0x00" + str(list(ADDR_MAP["SM Address"])[0 + page_word*cyc].split(";")[0].split("0x")[1])
                    #       + "[T_SOCKET][" + str(0+int(groups_type[i][int(index_list[z].split("&")[0])].split("&")[0]) + 4 * (lable_num_flag+int(index_list[z].split("&")[1]))) + "]*256+" + addr_map_item[cyc] + "_0x00"
                    #       + str(list(ADDR_MAP["SM Address"])[0 + page_word*cyc].split(";")[0].split("0x")[1]) + "[T_SOCKET][" + str(1 +int(groups_type[i][int(index_list[z].split("&")[0])].split("&")[0]) + 4 * (lable_num_flag+int(index_list[z].split("&")[1]))) + "];\n")
                    f.write(groups_type[i][int(index_list[z].split("&")[0])].split("&")[2] + "Sys_SW_BUFFER_DATA[T_SOCKET][" + str(0+int(groups_type[i][int(index_list[z].split("&")[0])].split("&")[0]) + 4 * (label_num_flag+int(index_list[z].split("&")[1]))) + "]*256+" + "Sys_SW_BUFFER_DATA[T_SOCKET][" + str(1 +int(groups_type[i][int(index_list[z].split("&")[0])].split("&")[0]) + 4 * (label_num_flag+int(index_list[z].split("&")[1]))) + "];\n")

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
                    type_flag1 = "		REG_" + G.col("ADDR_MAP", "bit[15:0]")[i+page_word*cyc].split("[")[0].upper() + "[T_SOCKET]="
                elif "verify" in list(G.ADDR_MAP[temp_item_flag])[i + page_word * cyc].lower():
                    if uid_write_dic[G.col("ADDR_MAP", "bit[15:0]")[i+page_word*cyc]] <= int(code_name.split("_")[-1][-1]):
                        type_flag1 = "		" + G.col("ADDR_MAP", "bit[15:0]")[i+page_word*cyc].split("Verify")[
                            0].upper() + "W[T_SOCKET]="

            else:
                type_flag1 = "888[15:0]"
                bit_015_1631_flag1 = 9

            if bit != 32:
                if G.col("ADDR_MAP", "data type")[i+1+page_word*cyc] == "lable":
                    bit_015_1631_flag2 = 0
                    if "verify" not in list(G.ADDR_MAP[temp_item_flag])[i + page_word * cyc].lower():
                        type_flag2 = "		REG_" + G.col("ADDR_MAP", "bit[15:0]")[i+1+page_word*cyc].split("[")[0].upper() + "[T_SOCKET]="
                    elif "verify" in list(G.ADDR_MAP[temp_item_flag])[i + page_word * cyc].lower():
                        if uid_write_dic[G.col("ADDR_MAP", "bit[15:0]")[i+1+page_word*cyc]] <= int(code_name.split("_")[-1][-1]):
                            type_flag2 = "		" + G.col("ADDR_MAP", "bit[15:0]")[i+1+page_word*cyc].split("Verify")[
                                0].upper() + "W[T_SOCKET]="
                else:
                    type_flag2 = "888[15:0]"
                    bit_015_1631_flag2 = 9

            if bit != 32 and bit != 64:
                if G.col("ADDR_MAP", "data type")[i+2+page_word*cyc] == "lable":
                    bit_015_1631_flag3 = 0
                    if "verify" not in list(G.ADDR_MAP[temp_item_flag])[i + page_word * cyc].lower():
                        type_flag3 = "		REG_" + G.col("ADDR_MAP", "bit[15:0]")[i+2+page_word*cyc].split("[")[0].upper() + "[T_SOCKET]="
                    elif "verify" in list(G.ADDR_MAP[temp_item_flag])[i + page_word * cyc].lower():
                        if uid_write_dic[G.col("ADDR_MAP", "bit[15:0]")[i+2+page_word*cyc]] <= int(code_name.split("_")[-1][-1]):
                            type_flag3 = "		" + G.col("ADDR_MAP", "bit[15:0]")[i+2+page_word*cyc].split("Verify")[
                                0].upper() + "W[T_SOCKET]="
                else:
                    type_flag3 = "888[15:0]"
                    bit_015_1631_flag3 = 9

                if G.col("ADDR_MAP", "data type")[i+3+page_word*cyc] == "lable":
                    bit_015_1631_flag4 = 0
                    if "verify" not in list(G.ADDR_MAP[temp_item_flag])[i + page_word * cyc].lower():
                        type_flag4 = "		REG_" + G.col("ADDR_MAP", "bit[15:0]")[i+3+page_word*cyc].split("[")[0].upper() + "[T_SOCKET]="
                    elif "verify" in list(G.ADDR_MAP[temp_item_flag])[i + page_word * cyc].lower():
                        if uid_write_dic[G.col("ADDR_MAP", "bit[15:0]")[i+3+page_word*cyc]] <= int(code_name.split("_")[-1][-1]):
                            type_flag4 = "		" + G.col("ADDR_MAP", "bit[15:0]")[i+3+page_word*cyc].split("Verify")[
                                0].upper() + "W[T_SOCKET]="
                else:
                    type_flag4 = "888[15:0]"
                    bit_015_1631_flag4 = 9

            if bit == 256:
                if G.col("ADDR_MAP", "data type")[i+4+page_word*cyc] == "lable":
                    bit_015_1631_flag5 = 0
                    if "verify" not in list(G.ADDR_MAP[temp_item_flag])[i + page_word * cyc].lower():
                        type_flag5 = "		REG_" + G.col("ADDR_MAP", "bit[15:0]")[i+4+page_word*cyc].split("[")[0].upper() + "[T_SOCKET]="
                    elif "verify" in list(G.ADDR_MAP[temp_item_flag])[i + page_word * cyc].lower():
                        if uid_write_dic[G.col("ADDR_MAP", "bit[15:0]")[i+4+page_word*cyc]] <= int(code_name.split("_")[-1][-1]):
                            type_flag5 = "		" + G.col("ADDR_MAP", "bit[15:0]")[i+4+page_word*cyc].split("Verify")[
                                0].upper() + "W[T_SOCKET]="
                else:
                    type_flag5 = "888[15:0]"
                    bit_015_1631_flag5 = 9

                if G.col("ADDR_MAP", "data type")[i+5+page_word*cyc] == "lable":
                    bit_015_1631_flag6 = 0
                    if "verify" not in list(G.ADDR_MAP[temp_item_flag])[i + page_word * cyc].lower():
                        type_flag6 = "		REG_" + G.col("ADDR_MAP", "bit[15:0]")[i+5+page_word*cyc].split("[")[0].upper() + "[T_SOCKET]="
                    elif "verify" in list(G.ADDR_MAP[temp_item_flag])[i + page_word * cyc].lower():
                        if uid_write_dic[G.col("ADDR_MAP", "bit[15:0]")[i+5+page_word*cyc]] <= int(code_name.split("_")[-1][-1]):
                            type_flag6 = "		" + G.col("ADDR_MAP", "bit[15:0]")[i+5+page_word*cyc].split("Verify")[
                                0].upper() + "W[T_SOCKET]="
                else:
                    type_flag6 = "888[15:0]"
                    bit_015_1631_flag6 = 9

                if G.col("ADDR_MAP", "data type")[i+6+page_word*cyc] == "lable":
                    bit_015_1631_flag7 = 0
                    if "verify" not in list(G.ADDR_MAP[temp_item_flag])[i + page_word * cyc].lower():
                        type_flag7 = "		REG_" + G.col("ADDR_MAP", "bit[15:0]")[i+6+page_word*cyc].split("[")[0].upper() + "[T_SOCKET]="
                    elif "verify" in list(G.ADDR_MAP[temp_item_flag])[i + page_word * cyc].lower():
                        if uid_write_dic[G.col("ADDR_MAP", "bit[15:0]")[i+6+page_word*cyc]] <= int(code_name.split("_")[-1][-1]):
                            type_flag7 = "		" + G.col("ADDR_MAP", "bit[15:0]")[i+6+page_word*cyc].split("Verify")[
                                0].upper() + "W[T_SOCKET]="
                else:
                    type_flag7 = "888[15:0]"
                    bit_015_1631_flag7 = 9

                if G.col("ADDR_MAP", "data type")[i+7+page_word*cyc] == "lable":
                    bit_015_1631_flag8 = 0
                    if "verify" not in list(G.ADDR_MAP[temp_item_flag])[i + page_word * cyc].lower():
                        type_flag8 = "		REG_" + G.col("ADDR_MAP", "bit[15:0]")[i+7+page_word*cyc].split("[")[0].upper() + "[T_SOCKET]="
                    elif "verify" in list(G.ADDR_MAP[temp_item_flag])[i + page_word * cyc].lower():
                        if uid_write_dic[G.col("ADDR_MAP", "bit[15:0]")[i+7+page_word*cyc]] <= int(code_name.split("_")[-1][-1]):
                            type_flag8 = "		" + G.col("ADDR_MAP", "bit[15:0]")[i+7+page_word*cyc].split("Verify")[
                                0].upper() + "W[T_SOCKET]="
                else:
                    type_flag8 = "888[15:0]"
                    bit_015_1631_flag8 = 9
            if bit == 32:
                groups_type.append((str(bit_015_1631_flag1)+"&"+G.col("ADDR_MAP", "data type")[i+page_word*cyc]+"&"+type_flag1))

            if bit == 64:
                groups_type.append((str(bit_015_1631_flag1)+"&"+G.col("ADDR_MAP", "data type")[i+page_word*cyc]+"&"+type_flag1, str(bit_015_1631_flag2)+"&"+G.col("ADDR_MAP", "data type")[i+1+page_word*cyc]+"&"+type_flag2))

            if bit == 128:
                groups_type.append((str(bit_015_1631_flag1) + "&" + G.col("ADDR_MAP", "data type")[i + page_word*cyc] + "&" + type_flag1,
                                    str(bit_015_1631_flag2) + "&" + G.col("ADDR_MAP", "data type")[i + 1 + page_word*cyc] + "&" + type_flag2,
                                    str(bit_015_1631_flag3) + "&" + G.col("ADDR_MAP", "data type")[i + 2 + page_word*cyc] + "&" + type_flag3,
                                    str(bit_015_1631_flag4) + "&" + G.col("ADDR_MAP", "data type")[i + 3 + page_word*cyc] + "&" + type_flag4
                                    ))

            if bit == 256:
                groups_type.append((str(bit_015_1631_flag1) + "&" + G.col("ADDR_MAP", "data type")[i + page_word*cyc] + "&" + type_flag1,
                                    str(bit_015_1631_flag2) + "&" + G.col("ADDR_MAP", "data type")[i + 1 + page_word*cyc] + "&" + type_flag2,
                                    str(bit_015_1631_flag3) + "&" + G.col("ADDR_MAP", "data type")[i + 2 + page_word*cyc] + "&" + type_flag3,
                                    str(bit_015_1631_flag4) + "&" + G.col("ADDR_MAP", "data type")[i + 3 + page_word*cyc] + "&" + type_flag4,
                                    str(bit_015_1631_flag5) + "&" + G.col("ADDR_MAP", "data type")[i + 4 + page_word*cyc] + "&" + type_flag5,
                                    str(bit_015_1631_flag6) + "&" + G.col("ADDR_MAP", "data type")[i + 5 + page_word*cyc] + "&" + type_flag6,
                                    str(bit_015_1631_flag7) + "&" + G.col("ADDR_MAP", "data type")[i + 6 + page_word*cyc] + "&" + type_flag7,
                                    str(bit_015_1631_flag8) + "&" + G.col("ADDR_MAP", "data type")[i + 7 + page_word*cyc] + "&" + type_flag8
                                    ))

        # print(groups_type)
        label_num_flag = 0
        if bit == 32:
            for i in range(len(groups_type)):
                if groups_type[i].split("&")[1] == "lable" :
                    if groups_type[i].split("&")[2] != "888[15:0]":
                        # f.write(groups_type[i].split("&")[2] + addr_map_item[cyc] + "_0x00" + str(
                        #     list(ADDR_MAP["SM Address"])[0 + page_word*cyc].split(";")[0].split("0x")[1])
                        #         + "[T_SOCKET][" + str(0 + 2 * lable_num_flag) + "]*256+" + addr_map_item[
                        #             cyc] + "_0x00"
                        #         + str(list(ADDR_MAP["SM Address"])[0 + page_word*cyc].split(";")[0].split("0x")[
                        #                   1]) + "[T_SOCKET][" + str(1 + 2 * lable_num_flag) + "];\n")
                        f.write(groups_type[i].split("&")[2] +"Sys_SW_BUFFER_DATA[T_SOCKET][" + str(0 + 2 * label_num_flag) + "]*256+" +"Sys_SW_BUFFER_DATA[T_SOCKET][" + str(1 + 2 * label_num_flag) + "];\n")
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
                    # f.write(groups_type[i][int(index_list[z].split("&")[0])].split("&")[2] + addr_map_item[cyc] + "_0x00" + str(list(ADDR_MAP["SM Address"])[0 + page_word*cyc].split(";")[0].split("0x")[1])
                    #       + "[T_SOCKET][" + str(0 + 2 * (lable_num_flag+int(index_list[z].split("&")[1]))) + "]*256+" + addr_map_item[cyc] + "_0x00"
                    #       + str(list(ADDR_MAP["SM Address"])[0 + page_word*cyc].split(";")[0].split("0x")[1]) + "[T_SOCKET][" + str(1 + 2 * (lable_num_flag+int(index_list[z].split("&")[1]))) + "];\n")
                    f.write(groups_type[i][int(index_list[z].split("&")[0])].split("&")[2] + "Sys_SW_BUFFER_DATA[T_SOCKET][" + str(0 + 2 * (label_num_flag+int(index_list[z].split("&")[1]))) + "]*256+" + "Sys_SW_BUFFER_DATA[T_SOCKET][" + str(1 + 2 * (label_num_flag+int(index_list[z].split("&")[1]))) + "];\n")

                label_num_flag += len(index_list)
                index_list.clear()


def _bor_data_helper_write(code_name, f, z):
    if (_flow_item_key(G.col("FLOW", "item")[z]) != "bor_verify"
            or code_name[G.i].split("_")[-1] != G.col("FLOW", "CP NO")[z]):
        return False
    pattern_name = "set_bor_verify_dac"
    copy_file(G.BASE_DIR + "\\pat_temp\\" + pattern_name + ".sd",
              G.OUT_DIR + "\\" + code_name[G.i])
    f.write("@@MACRO set_bor_data(int a)\n\n")
    f.write("\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n\t{\n")
    f.write("\t\tGB[0+T_SOCKET*64]=a;\n\t}\n\n")
    f.write("\tLOGIC_WRITE_PATTERN_MEMORY(" + pattern_name + ":e_data_st," +
            pattern_name + ":e_data_sp," +
            str(G.col("VERSION", "SWD PIN")[G.i]) +
            ",GB1, BIT_COUNT=3, SERIAL,MSB_LSB);\n\n")
    f.write("\tRUN_PATTERN(" + pattern_name + ":START," + pattern_name +
            ":END,1,TS_5MHZ);\n\n")
    f.write("@@END_MACRO\n\n")
    return True


def sub_flow_write(code_name, f, name, pattern, temp_list,z):
    # //////////////////////////////////////////////Sub Flow 写入start/////////////////////////////////////////////
    _bor_data_helper_write(code_name, f, z)
    serial_number = ["a", "b", "c", "d", "e", "f", "g"]
    sub_item = G.col("PATTERN", "pattern")
    new_sub_item = [sub_item for sub_item in sub_item if sub_item == sub_item]  # 去除nan
    written_patterns = set()
    for j in range(len(name)):
        if G.col("FLOW", "item")[z] == name[j] and code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[
            z]:
            # and "Pdr" not in list(FLOW["item"])[z]
            if G.col("FLOW", "type")[z] == "trim"	and "set" in pattern[j]:
                if pattern[j] in written_patterns:
                    continue
                written_patterns.add(pattern[j])
                for cyc in range(len(G.col("PATTERN", "description"))):
                    if temp_list[cyc] == pattern[j]:
                        copy_file(G.BASE_DIR + "\\pat_temp\\" + pattern[j] + ".sd",
                                  G.OUT_DIR + "\\" + code_name[G.i])
                        # print(pattern[j])

                        # 复用 fbist_pattern_created() 已经算好的 G.exegesis[cyc]（起始位缺省的行
                        # 已经从 FB MAP 反查补全），不再自己对 description 原始文本重新 split("\n")；
                        # 只把含 "=x" 的行当 trim_data() 参数，同 chroma/writers.py（2026-07-06 移植）。
                        var_slots = _trim_variable_slots_for_merged_row(cyc)
                        f.write("@@MACRO "+str(pattern[j].split("dac")[0]) + "trim_data(")
                        for cyc1, (d, _line) in enumerate(var_slots):
                            f.write("int* " + str(serial_number[d]))
                            if cyc1 < len(var_slots) - 1:
                                f.write(",")
                        f.write(")\n\n")
                        f.write("	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n	{\n")
                        f.write("		GB[0+T_SOCKET*64]=0;\n")
                        write_specs = []
                        for d, line in var_slots:
                            if "[" in line and "]" in line:
                                dac_bit = str(int(line.split(":")[0].split("[")[-1]) - int(
                                    line.split(":")[1].split("]")[0]))
                                dac_item_name = line.split(",")[1].split("[")[0].split("_T")[0].lower()
                            elif pattern_field_is_dynamic(line):
                                value_part = line.split("=")[1].rstrip("*")
                                dac_bit = str(len(value_part) - 1)
                                dac_item_name = line.split(",")[1].split("=")[0].split("_T")[0].lower()

                            if len(var_slots) > 1:

                                f.write("		GB[" + str(d) + "+T_SOCKET*64]=" + str(serial_number[d]) + "[T_SOCKET]; //" + dac_item_name + "_dac\n")
                            else:
                                f.write("		GB[0+T_SOCKET*64]=" + str(serial_number[d]) + "[T_SOCKET]; //data\n")
                            write_specs.append((d, dac_bit))
                        f.write("	}\n\n")
                        for d, dac_bit in write_specs:
                            f.write("	LOGIC_WRITE_PATTERN_MEMORY(" + pattern[j] + ":" + serial_number[d] + "_data_st," +
                                        pattern[j] + ":" + serial_number[d] + "_data_sp," +str(G.col("VERSION", "SWD PIN")[G.i])+",GB" + str(d + 1) + ", "+
                                        "BIT_COUNT="+str(int(dac_bit) + 1)+", SERIAL,MSB_LSB);\n\n")


                f.write("	RUN_PATTERN("+pattern[j]+":START,"+pattern[j]+":END,"+"1,TS_5MHZ);\n\n")
                f.write("@@END_MACRO\n\n")


def dynamic_enter_helpers_write(
        code_name, f, trim_specs, current_cp, temp_list, recipe_rows=None,
        dac_write_plans=None):
    """Emit parameterized ENTER pattern-memory setters before test bodies."""
    serial_number = ["a_data", "b_data", "c_data", "d_data", "e_data", "f_data", "g_data"]
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
        helper = "set_" + operation.reference + "_data"
        f.write("@@MACRO " + helper + "(int data)\n\n")
        f.write("\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n\t{\n")
        f.write("\t\tGB[0+T_SOCKET*64]=data;\n\t}\n\n")
        f.write("\tLOGIC_WRITE_PATTERN_MEMORY(" + operation.reference + ":" +
                serial_number[slot] + "_st," + operation.reference + ":" +
                serial_number[slot] + "_sp," + str(G.col("VERSION", "SWD PIN")[G.i]) +
                ",GB1, BIT_COUNT=" + str(operation.field_width) + ", SERIAL,MSB_LSB);\n\n")
        f.write("@@END_MACRO\n\n")

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
        copy_file(G.BASE_DIR + "\\pat_temp\\" + operation.pattern_name + ".sd",
                  G.OUT_DIR + "\\" + code_name[G.i])
        slot, _line = slots[0]
        helper = operation.helper_name
        f.write("@@MACRO " + helper + "(int* a)\n\n")
        f.write("\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n\t{\n")
        f.write("\t\tGB[0+T_SOCKET*64]=a[T_SOCKET];\n\t}\n\n")
        f.write("\tLOGIC_WRITE_PATTERN_MEMORY(" + operation.pattern_name + ":" +
                serial_number[slot] + "_st," + operation.pattern_name + ":" +
                serial_number[slot] + "_sp," + str(G.col("VERSION", "SWD PIN")[G.i]) +
                ",GB1, BIT_COUNT=" + str(operation.field_width) + ", SERIAL,MSB_LSB);\n\n")
        f.write("\tRUN_PATTERN(" + operation.pattern_name + ":START," + operation.pattern_name +
                ":END,1,TS_5MHZ);\n\n")
        f.write("@@END_MACRO\n\n")


def trim_item_write(
        code_name, f, name, pattern, z, bisection, temp_list, trim_spec=None,
        dedicated_trim_plan=None):
    # //////////////////////////////////////////////trim 写入start/////////////////////////////////////////////
    global vref
    G.trash.clear()
    relay = flow_relay(z)

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
                # print(list(FLOW["item"])[z])
                for cyc in range(len(G.col("PATTERN", "description"))):
                    if temp_list[cyc] == pattern[j + 1] and pattern[j + 1].startswith("set_"):
                        # 同上：复用已含 FB MAP 起始位补全的 G.exegesis[cyc]，不重新解析原始文本。
                        candidate_slots = _trim_variable_slots_for_merged_row(cyc)
                        if candidate_slots:
                            var_slots = candidate_slots

                if spec_target:
                    enter_patterns = spec_enter_patterns if spec_target else [pattern[j]]
                    trim_force_wait = spec_trim_force_wait if spec_target else None
                    trim_set_wait = spec_trim_set_wait if spec_target else None
                    adjust_set_wait = spec_adjust_set_wait if spec_target else None
                    judge_set_wait = spec_judge_set_wait if spec_target else None
                    for enter_pattern in dict.fromkeys(enter_patterns):
                        copy_file(G.BASE_DIR + "\\pat_temp\\" + enter_pattern + ".sd",
                                  G.OUT_DIR + "\\" + code_name[G.i] )

                    if bisection == "no":
                        f.write("@@PLAN "+name[j].split("Trim")[0].title() + "Dac_Loop\n")
                        f.write("	SITE_SEQUENCE      = OFF;\n" +"	GO_THROUGH         = ON;\n"+ '	DISABLE_BY_MARK_NO = NULL;\n' +"	S_SETUP_FILE       = c:\\set.dat;\n"+
                                "	REMARK             = "+name[j].split("Trim")[0].title() + 'Dac_Loop; \n\n')
                    else:
                        f.write("@@PLAN "+name[j].title() + "\n")
                        f.write("	SITE_SEQUENCE      = OFF;\n" +"	GO_THROUGH         = ON;\n"+ '	DISABLE_BY_MARK_NO = NULL;\n' +"	S_SETUP_FILE       = c:\\set.dat;\n"+
                                "	REMARK             = "+name[j].title() + '; \n\n')

                    if name[j].split("_")[0].lower() in list(G.VERSION.columns):
                        f.write("	double trimTar=_C_" + name[j].split("_")[0].upper() + '_TAR;\n\n')
                    else:
                        f.write("	double trimTar=" + str(G.col("FLOW", "target")[z]) + ';\n\n')
                    f.write(
                        "	double trimFinalValue[MAX_SITE];\n	int trimDac[MAX_SITE];\n\n")
                    if spec_target and trim_spec.adjust is not None:
                        dac_adj = {
                            "cond": (trim_spec.adjust.operator, trim_spec.adjust.threshold),
                            "delta": trim_spec.adjust.delta,
                        }
                    else:
                        dac_adj = _dac_adj_spec(z)
                    search_codes = trim_spec.search.codes if spec_target else None
                    if spec_target:
                        dac_values = ",".join(str(code) for code in search_codes)
                        f.write("\tint dacArray[" + str(len(search_codes)) + "]={" +
                                dac_values + "};\n")
                        if bisection == "no":
                            f.write("\tint cyc=0;\n\tint endCyc=" + str(len(search_codes)) + ";\n\n")
                        else:
                            f.write(
                                "\tint dacIndex[MAX_SITE];\n\tint firstIndex=sizeof(dacArray)/sizeof(dacArray[0])/2;\n" +
                                "\tint binAryCyc = " + str(trim_spec.search.search_bits - 2) + ";\n\n")
                    elif bisection == "no":
                        f.write("	int cyc=0;\n	int endCyc=" + str(
                            pow(2, G.col("FLOW", "DAC bit")[z])) + ";\n\n")
                    elif G.col("FLOW", "LINE")[z] == "yes":
                        f.write(
                            "	int dacArray[" + str(pow(2, G.col("FLOW", "DAC bit")[z])) + "]={0};\n")
                        f.write("	for(I=0;I<" + str(
                            pow(2, G.col("FLOW", "DAC bit")[z])) + ";I++)\n	{\n		dacArray[I]=I;\n	}\n\n")
                        f.write(
                            "	int dacIndex[MAX_SITE];\n	int firstIndex=sizeof(dacArray)/sizeof(dacArray[0])/2;\n	//int binAryCyc=(int)(log((double)(sizeof(dacArray)/sizeof(dacArray[0])+1))/log(2.0))-2;\n"+"	int binAryCyc = "+str(int(math.log2(pow(2, G.col("FLOW", "DAC bit")[z])))-2)+";\n\n")
                    else:
                        step_str = expand_dac_array(G.col("FLOW", "step")[z])
                        step_count = len([x for x in step_str.replace("\n", ",").split(",") if x.strip()])
                        f.write("	int dacArray[" + str(step_count) + "]={" + step_str + "};\n\n")
                        f.write(
                            "	int dacIndex[MAX_SITE];\n	int firstIndex=sizeof(dacArray)/sizeof(dacArray[0])/2;\n	//int binAryCyc=(int)(log((double)(sizeof(dacArray)/sizeof(dacArray[0])+1))/log(2.0))-2;\n"+"	int binAryCyc = "+str(int(math.log2(pow(2, G.col("FLOW", "DAC bit")[z])))-2)+";\n\n")
                    if dac_adj is not None and bisection == "yes":
                        # 记下"历史最优"对应的 dacArray 下标（同 DAC_FINAL 一起在收敛过程中
                        # 更新），供收敛后加档直接用——不能用循环末尾的 dacIndex（同
                        # chroma/writers.py:trim_item_write 的既有理由，2026-07-06 移植）。
                        f.write("	int dacFinalIndex[MAX_SITE];\n\n")
                    f.write(
                        "	//initial\n	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n	{ \n")
                    if bisection == "no":
                        initial_dac = "dacArray[0]" if spec_target else "0"
                        f.write("		GB[1+T_SOCKET*64]=" + initial_dac +
                                "; // trimDac = GB2\n		trimDac[T_SOCKET]=" + initial_dac + ";\n")
                    else:
                        f.write(
                            "		GB[1+T_SOCKET*64]=dacArray[firstIndex]; // trimDac = GB2\n		trimDac[T_SOCKET]=dacArray[firstIndex];\n		dacIndex[T_SOCKET]=firstIndex;\n")
                        if dac_adj is not None:
                            f.write("		dacFinalIndex[T_SOCKET]=firstIndex;\n")
                    f.write("		GB[2+T_SOCKET*64]=0; // trimValue = GB3\n		GB[3+T_SOCKET*64]=0; // trimFinalDac = GB4\n		trimFinalValue[T_SOCKET]=0.0;\n	} \n\n")

                    _emit_flow_relay(f, relay, enabled=True)
                    f.write("	CALL_MACRO POWER_ON(_C_" + G.col("FLOW", "Vcc")[z].upper() + ");\n\n")

                    f.write(
                        '	RUN_PATTERN(enter_fbist_mode:START,enter_fbist_mode:END,1,TS_5MHZ);\n\n')
                    setup_operations = spec_setup_operations if spec_target else []
                    if spec_target:
                        setup_patterns = [operation.reference for operation in setup_operations]
                        for run_pattern in dict.fromkeys(
                            operation.reference for operation in setup_operations
                            if operation.kind == "RUN"
                        ):
                            copy_file(G.BASE_DIR + "\\pat_temp\\" + run_pattern + ".sd",
                                      G.OUT_DIR + "\\" + code_name[G.i])
                    else:
                        setup_patterns = enter_patterns
                    for enter_index, enter_pattern in enumerate(setup_patterns):
                        enter_operation = setup_operations[enter_index] if setup_operations else None
                        enter_wait = enter_operation.wait if enter_operation else None
                        if (enter_operation is not None and enter_operation.kind == "ENTER"
                                and enter_operation.value_source == "ARGUMENT"):
                            f.write("\tCALL_MACRO set_" + enter_pattern + "_data(" +
                                    str(int(enter_operation.value, 2)) + ");\n")
                        f.write('	RUN_PATTERN(' + enter_pattern + ':START,' + enter_pattern +
                                ':END,1,TS_5MHZ); \n\n')
                        if enter_wait is not None:
                            _write_recipe_wait(f, enter_wait, "\t")
                            f.write("\n")
                        if (enter_operation is not None and enter_operation.kind == "ENTER"
                                and enter_operation.value_source == "ARGUMENT"):
                            f.write("\tCALL_MACRO set_" + enter_pattern + "_data(" +
                                    str(int(enter_operation.default_value, 2)) + ");\n\n")
                    if spec_target:
                        dependency_patterns = [
                            operation.reference
                            for operation in trim_spec.operations
                            if operation.kind == "DEPEND"
                        ]
                        for dependency_pattern in dependency_patterns:
                            copy_file(G.BASE_DIR + "\\pat_temp\\" + dependency_pattern + ".sd",
                                      G.OUT_DIR + "\\" + code_name[G.i])
                            f.write('\tRUN_PATTERN(' + dependency_pattern + ':START,' +
                                    dependency_pattern + ':END,1,TS_5MHZ);  \n\n')
                    for vref_cyc in range(len(G.col("FLOW", "item"))):
                        if G.ws["B"][vref_cyc + 1].fill.fgColor.rgb == "FFFFFF00":
                            if G.col("FLOW", "item")[vref_cyc] not in G.vref:
                                G.vref.append(G.col("FLOW", "item")[vref_cyc])
                    index = 0
                    if code_name[G.i].split("_")[-1] == "CP1":
                        if not spec_target and len(G.vref) != 0:
                            for vref_num in G.vref:
                                index = name.index(vref_num)
                                if G.col("FLOW", "item")[z] != vref_num:
                                    f.write('	RUN_PATTERN(' + pattern[index + 1] + ':START,' + pattern[
                                                index + 1] + ':END,1,TS_5MHZ);  \n\n')
                    else:
                        f.write(
                            '	RUN_PATTERN(set_all_final_vposp:START,set_all_final_vposp:END,1,TS_5MHZ); \n\n')
                    if "Hz" in G.col("FLOW", "UNIT")[z]:
                        Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                    G.col("FLOW", "target")[z], 2, "FORCE", "FREQ", G.col("FLOW", "low_range(%)")[z],
                                    G.col("FLOW", "high_range(%)")[z],"" ,"no",f,force_wait=trim_force_wait)
                    else:
                        Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                    G.col("FLOW", "target")[z], 2, "FORCE", "PMU", G.col("FLOW", "low_range(%)")[z],
                                    G.col("FLOW", "high_range(%)")[z],"" ,"no",f,force_wait=trim_force_wait)

                    if spec_target:
                        reuse_patterns = []
                    else:
                        reuse_pat = reuse_dac_pattern(name[j])
                        reuse_patterns = [reuse_pat] if reuse_pat else []
                    for reuse_pat in reuse_patterns:
                        copy_file(G.BASE_DIR + "\\pat_temp\\" + reuse_pat + ".sd",
                                  G.OUT_DIR + "\\" + code_name[G.i])
                        f.write('	RUN_PATTERN(' + reuse_pat + ':START,' + reuse_pat + ':END,1,TS_5MHZ); \n\n')

                    f.write('	do\n	{\n')
                    if bisection == "no":
                        trim_name = str(G.col("FLOW", "item")[z].split("Trim")[0]).lower().rstrip("_")
                        upper_name = trim_name.upper()
                        f.write("		sprintf(_C_" + upper_name + "_LOG_MSG, \"" + trim_name + "_dac_%d\", trimDac);\n")
                        f.write('		cyc++; \n')
                    if len(var_slots) > 1:
                        f.write('		CALL_MACRO ' + str(pattern[j + 1].split("dac")[0]) + "trim_data(")
                        for cyc1, (d, line) in enumerate(var_slots):
                            dac_item_name = line.split(",")[1].split("[")[0]
                            if dac_item_name != name[j]:
                                f.write(dac_item_name.split("Trim")[0].upper() + "DAC_FINAL")
                            elif dac_item_name == name[j]:
                                f.write("trimDac")
                            if cyc1 < len(var_slots) - 1:
                                f.write(",")
                        f.write(");\n\n")
                    else:
                        f.write('		CALL_MACRO ' + str(pattern[j + 1].split("dac")[0]) + "trim_data(trimDac);\n\n")

                    if trim_set_wait is not None:
                        _write_recipe_wait(f, trim_set_wait, "\t\t")
                        f.write("\n")

                    if G.col("FLOW", "PE")[z].upper() == "ERASE":
                        for nm_name in G.nm_patterns("page erase 1st"):
                            copy_file(G.BASE_DIR + "\\pat_temp\\" +
                                      nm_name + ".sd",
                                      G.OUT_DIR + "\\" + code_name[G.i] )
                            f.write('		RUN_PATTERN(' +
                                    nm_name + ':START,' +
                                    nm_name + ':pe_1,1,TS_5MHZ);\n\n')
                    if G.col("FLOW", "PE")[z].upper() == "PROGRAM":
                        for nm_name in G.nm_patterns("page program PCKB 1st"):
                            copy_file(G.BASE_DIR + "\\pat_temp\\" +
                                    nm_name + ".sd",
                                    G.OUT_DIR + "\\" + code_name[G.i] )
                            f.write('		RUN_PATTERN(' +
                                    nm_name + ':START,' +
                                    nm_name + ':pe_1,1,TS_5MHZ);\n\n')

                    if "Hz" in G.col("FLOW", "UNIT")[z]:
                        Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                    G.col("FLOW", "target")[z], 6, "JUDGE", "FREQ", widen_pct(G.col("FLOW", "low_range(%)")[z], 50),
                                    widen_pct(G.col("FLOW", "high_range(%)")[z], 50), "null" ,"trim",f)
                    else:
                        Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                    G.col("FLOW", "target")[z], 6, "JUDGE", "PPMU", widen_pct(G.col("FLOW", "low_range(%)")[z], 50),
                                    widen_pct(G.col("FLOW", "high_range(%)")[z], 50), "null" ,"trim",f)
                    if G.col("FLOW", "PE")[z].upper() == "ERASE":
                        for nm_name in G.nm_patterns("page erase 1st"):
                            f.write('\n		RUN_PATTERN(' +
                                    nm_name + ':pe_1,' +
                                    nm_name + ':END,1,TS_5MHZ);\n\n')
                    if G.col("FLOW", "PE")[z].upper() == "PROGRAM":
                        for nm_name in G.nm_patterns("page program PCKB 1st"):
                            f.write('\n		RUN_PATTERN(' +
                                    nm_name + ':pe_1,' +
                                    nm_name + ':END,1,TS_5MHZ);\n\n')
                    f.write('		C_ASSIGN(GB3,'+G.col("FLOW", "meas pin")[z]+");\n")
                    if "Hz" in G.col("FLOW", "UNIT")[z]:
                        f.write('		C_DIV(GB3, 1000);\n\n')
                    elif "uA" in G.col("FLOW", "UNIT")[z]:
                        f.write('		C_MUL(GB3,1000000);\n\n')
                    if bisection != "yes":
                        # DAC 扫码过程只记录当前测量值，不能因尚未收敛到目标而触发
                        # C_COMPARE 失败；最终 DAC/结果判定在循环结束后仍保留。
                        f.write('\tC_COMPARE(GB3, LOG_ALIAS=_C_' + upper_name +
                                '_LOG_MSG, LOG_UNIT=' + G.col("FLOW", "UNIT")[z] + ');\n')
                        f.write('\n')
                    f.write('		for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n		{\n			if(Sys_ActiveSite[T_SOCKET]==0)continue;\n')
                    if bisection == "yes":
                        f.write(
                            '			if(fabs(GB[2+T_SOCKET*64]-trimTar)<fabs(trimFinalValue[T_SOCKET]-trimTar))\n			{\n				trimFinalValue[T_SOCKET] = GB[2+T_SOCKET*64];\n				' +
                            name[j].split("Trim")[0].upper() + 'DAC_FINAL[T_SOCKET] = dacArray[dacIndex[T_SOCKET]];\n' +
                            ("				dacFinalIndex[T_SOCKET] = dacIndex[T_SOCKET];\n"
                             if dac_adj is not None else "") +
                            '			}\n\n')
                    else:
                        write_full_scan_best_update(
                            f,
                            name[j].split("Trim")[0].upper() + "DAC_FINAL",
                            explicit_codes=spec_target,
                        )
                    if bisection == "yes":
                        f.write(
                            "			if (GB[2+T_SOCKET*64]<trimTar)\n			{\n				dacIndex[T_SOCKET] = dacIndex[T_SOCKET] + (int)pow((float)2, (float)binAryCyc);\n				trimDac[T_SOCKET] = dacArray[dacIndex[T_SOCKET]];\n			}\n\n")
                        f.write(
                            "			else\n			{\n				dacIndex[T_SOCKET] = dacIndex[T_SOCKET] - (int)pow((float)2, (float)binAryCyc);\n				trimDac[T_SOCKET] = dacArray[dacIndex[T_SOCKET]];\n			}\n\n")
                    else:
                        if spec_target:
                            f.write("			if(cyc<endCyc) trimDac[T_SOCKET] = dacArray[cyc];\n")
                        else:
                            f.write("			trimDac[T_SOCKET] = cyc;\n")

                    f.write('		}\n\n')  # socket_inc{}
                    if bisection == "yes":
                        f.write('		binAryCyc-=1;\n\n')
                    if bisection == "yes":
                        f.write('	}while(binAryCyc>=-1);\n\n')  # do while{}
                    else:
                        f.write('	}while(cyc<endCyc);   \n\n')  # do while{}

                    # # if bisection == "yes":
                    # if len(temp_pattern_variable) > 1:
                    #     f.write('	CALL_MACRO ' + str(pattern[j + 1].split("dac")[0]) + "trim_data(")
                    #     for cyc1 in range(len(temp_pattern_variable)):
                    #         dac_item_name = temp_pattern_variable[cyc1].split(",")[1].split("[")[0]
                    #         f.write(dac_item_name.split("Trim")[0].upper() + "DAC_FINAL")
                    #         if cyc1 < len(temp_pattern_variable) - 1:
                    #             f.write(",")
                    #     f.write(");\n\n")
                    # else:
                    #     f.write('	CALL_MACRO ' + str(pattern[j + 1].split("dac")[0]) + "trim_data(" +
                    #             name[j].split("Trim")[0].upper() + "DAC_FINAL);\n\n")

                    # if list(FLOW["PE"])[z].upper() == "ERASE":
                    #     for u in range(len(list(NM_PATTERN["used"]))):
                    #         if list(NM_PATTERN["used"])[u] == "page erase 1st":
                    #             f.write('	RUN_PATTERN(' +
                    #                     list(NM_PATTERN["Pattern name"])[u].split(".")[0] + ':START,' +
                    #                     list(NM_PATTERN["Pattern name"])[u].split(".")[
                    #                         0] + ':pe_1,1,TS_5MHZ);\n\n')
                    # if list(FLOW["PE"])[z].upper() == "PROGRAM":
                    #     for u in range(len(list(NM_PATTERN["used"]))):
                    #         if list(NM_PATTERN["used"])[u] == "page program PCKB 1st":
                    #             f.write('	RUN_PATTERN(' +
                    #                     list(NM_PATTERN["Pattern name"])[u].split(".")[0] + ':START,' +
                    #                     list(NM_PATTERN["Pattern name"])[u].split(".")[
                    #                         0] + ':pe_1,1,TS_5MHZ);\n\n')

                    dac_final_name = name[j].split("Trim")[0].upper() + "DAC_FINAL"
                    if len(var_slots) > 1:
                        _trim_data_args = []
                        for d, line in var_slots:
                            dac_item_name = line.split(",")[1].split("[")[0]
                            _trim_data_args.append(dac_item_name.split("Trim")[0].upper() + "DAC_FINAL")
                        _trim_data_call = '\tCALL_MACRO ' + str(pattern[j + 1].split("dac")[0]) + "trim_data(" + \
                            ",".join(_trim_data_args) + ");\n\n"
                    else:
                        _trim_data_call = '\tCALL_MACRO ' + str(pattern[j + 1].split("dac")[0]) + "trim_data(" + \
                            dac_final_name + ");\n\n"

                    final_pe_patterns = _trim_pe_pattern_names(z)
                    f.write(_trim_data_call)
                    _emit_trim_pe_boundary(f, final_pe_patterns, start=True)
                    final_raw_set_wait = adjust_set_wait if dac_adj is not None else judge_set_wait
                    if final_raw_set_wait is not None:
                        _write_recipe_wait(f, final_raw_set_wait, "\t")
                        f.write("\n")
                    if dac_adj is not None:
                        Force_Judge(
                            G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z],
                            G.col("FLOW", "FV/FI")[z], G.col("FLOW", "target")[z], 2, "FORCE",
                            "FREQ" if "Hz" in G.col("FLOW", "UNIT")[z] else "PMU",
                            G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z],
                            "", "no", f,
                            force_wait=spec_adjust_force_wait if spec_target else None,
                        )
                        # 收敛后手动加减档（用户 2026-07-06 要求逻辑跟 chroma/writers.py:
                        # trim_item_write 一致）：先把 DAC_FINAL 灌回芯片+测一次（S100 这里
                        # 跟 chroma 不同——本函数原本收敛后不重新测量，直接用循环里缓存的
                        # trimFinalValue 当最终判定值；但那是"调整前"的值，加档后必须真的
                        # 重新灌值+重新测一次，不能继续用旧缓存），按条件/无条件调整
                        # DAC_FINAL，再重新灌回芯片+再测一次拿到调整后的真实值。
                        if len(var_slots) > 1:
                            _trim_data_args = []
                            for d, line in var_slots:
                                dac_item_name = line.split(",")[1].split("[")[0]
                                _trim_data_args.append(dac_item_name.split("Trim")[0].upper() + "DAC_FINAL")
                            _trim_data_call = '	CALL_MACRO ' + str(pattern[j + 1].split("dac")[0]) + "trim_data(" + \
                                ",".join(_trim_data_args) + ");\n\n"
                        else:
                            _trim_data_call = '	CALL_MACRO ' + str(pattern[j + 1].split("dac")[0]) + "trim_data(" + \
                                dac_final_name + ");\n\n"

                        # 收敛出的 DAC_FINAL 写回后必须重新测量；C_ASSIGN 仅复制上一次
                        # PPMU 结果，不能作为调档条件。与 Chroma 的“写最终码→测量→调档”对齐。
                        if "Hz" in G.col("FLOW", "UNIT")[z]:
                            Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                        G.col("FLOW", "target")[z], 2, "JUDGE", "FREQ", widen_pct(G.col("FLOW", "low_range(%)")[z], 50),
                                        widen_pct(G.col("FLOW", "high_range(%)")[z], 50), "null", "trim", f)
                        else:
                            Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                        G.col("FLOW", "target")[z], 2, "JUDGE", "PPMU", widen_pct(G.col("FLOW", "low_range(%)")[z], 50),
                                        widen_pct(G.col("FLOW", "high_range(%)")[z], 50), "null", "trim", f)
                        f.write('	C_ASSIGN(GB3,' + G.col("FLOW", "meas pin")[z] + ");\n")
                        if "Hz" in G.col("FLOW", "UNIT")[z]:
                            f.write('	C_DIV(GB3, 1000);\n\n')
                        elif "uA" in G.col("FLOW", "UNIT")[z]:
                            f.write('	C_MUL(GB3,1000000);\n\n')
                        f.write('	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n	{\n		if(Sys_ActiveSite[T_SOCKET]==0)continue;\n')
                        if dac_adj["cond"] is not None:
                            cmp_op, threshold = dac_adj["cond"]
                            f.write("		if(GB[2+T_SOCKET*64]" + cmp_op + str(threshold) + ")\n		{\n" +
                                    _dac_adj_apply(dac_final_name, dac_adj["delta"], bisection,
                                                   G.col("FLOW", "DAC bit")[z]) + "		}\n\n")
                        else:
                            f.write(_dac_adj_apply(dac_final_name, dac_adj["delta"], bisection,
                                                    G.col("FLOW", "DAC bit")[z]))
                        f.write('	}\n\n')
                        f.write(_trim_data_call)
                        if judge_set_wait is not None:
                            _write_recipe_wait(f, judge_set_wait, "\t")
                            f.write("\n")
                        Force_Judge(
                            G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z],
                            G.col("FLOW", "FV/FI")[z], G.col("FLOW", "target")[z], 2, "FORCE",
                            "FREQ" if "Hz" in G.col("FLOW", "UNIT")[z] else "PMU",
                            G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z],
                            "", "no", f,
                            force_wait=spec_judge_force_wait if spec_target else None,
                        )
                        # 调档后的 DAC_FINAL 也必须物理复测，供 trimFinalValue 与最终 compare 使用。
                        if "Hz" in G.col("FLOW", "UNIT")[z]:
                            Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                        G.col("FLOW", "target")[z], 2, "JUDGE", "FREQ", widen_pct(G.col("FLOW", "low_range(%)")[z], 50),
                                        widen_pct(G.col("FLOW", "high_range(%)")[z], 50), "null", "trim", f)
                        else:
                            Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                        G.col("FLOW", "target")[z], 2, "JUDGE", "PPMU", widen_pct(G.col("FLOW", "low_range(%)")[z], 50),
                                        widen_pct(G.col("FLOW", "high_range(%)")[z], 50), "null", "trim", f)
                        f.write('	C_ASSIGN(GB3,' + G.col("FLOW", "meas pin")[z] + ");\n")
                        if "Hz" in G.col("FLOW", "UNIT")[z]:
                            f.write('	C_DIV(GB3, 1000);\n\n')
                        elif "uA" in G.col("FLOW", "UNIT")[z]:
                            f.write('	C_MUL(GB3,1000000);\n\n')
                        f.write('	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n	{\n		if(Sys_ActiveSite[T_SOCKET]==0)continue;\n		trimFinalValue[T_SOCKET]=GB[2+T_SOCKET*64];\n	}\n\n')

                        _emit_trim_pe_boundary(f, final_pe_patterns, start=False)

                    if dac_adj is None:
                        Force_Judge(
                            G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z],
                            G.col("FLOW", "FV/FI")[z], G.col("FLOW", "target")[z], 2, "FORCE",
                            "FREQ" if "Hz" in G.col("FLOW", "UNIT")[z] else "PMU",
                            G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z],
                            "", "no", f,
                            force_wait=spec_judge_force_wait if spec_target else None,
                        )
                        if "Hz" in G.col("FLOW", "UNIT")[z]:
                            Force_Judge(
                                G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z],
                                G.col("FLOW", "FV/FI")[z], G.col("FLOW", "target")[z], 2,
                                "JUDGE", "FREQ",
                                widen_pct(G.col("FLOW", "low_range(%)")[z], 50),
                                widen_pct(G.col("FLOW", "high_range(%)")[z], 50),
                                "null", "trim", f,
                            )
                        else:
                            Force_Judge(
                                G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z],
                                G.col("FLOW", "FV/FI")[z], G.col("FLOW", "target")[z], 2,
                                "JUDGE", "PPMU",
                                widen_pct(G.col("FLOW", "low_range(%)")[z], 50),
                                widen_pct(G.col("FLOW", "high_range(%)")[z], 50),
                                "null", "trim", f,
                            )
                        f.write('\tC_ASSIGN(GB3,' + G.col("FLOW", "meas pin")[z] + ');\n')
                        if "Hz" in G.col("FLOW", "UNIT")[z]:
                            f.write('\tC_DIV(GB3, 1000);\n\n')
                        elif "uA" in G.col("FLOW", "UNIT")[z]:
                            f.write('\tC_MUL(GB3,1000000);\n\n')
                        f.write('\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n\t{\n\t\tif(Sys_ActiveSite[T_SOCKET]==0)continue;\n\t\ttrimFinalValue[T_SOCKET]=GB[2+T_SOCKET*64];\n\t}\n\n')

                        _emit_trim_pe_boundary(f, final_pe_patterns, start=False)

                    f.write('	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n	{\n		GB[4+T_SOCKET*64]=' +
                            dac_final_name + '[T_SOCKET];\n		GB[2+T_SOCKET*64]=' +
                        'trimFinalValue[T_SOCKET];\n	}\n\n')
                    f.write('	C_COMPARE(GB5,' + 'DOWN_LIMIT=0, UP_LIMIT=' + str(
                        pow(2, G.col("FLOW", "DAC bit")[z]) - 1) + ', LOG_ALIAS= ' + name[j].split("Trim")[0] + 'dac_f);\n\n')

                    if name[j].split("_")[0].lower() in list(G.VERSION.columns):
                        f.write("	C_COMPARE(GB3, DOWN_LIMIT=_C_" +
                                name[j].split("_")[0].upper() + '_TAR-0.05, UP_LIMIT=_C_' +
                                name[j].split("_")[0].upper() + '_TAR+0.05,' + ' LOG_ALIAS='+name[j].split("Trim")[0] + 'value_f'+", LOG_UNIT="+G.col("FLOW", "UNIT")[z]+');\n\n')
                    else:
                        Force_Judge(G.col("FLOW", "UNIT")[z], "GB3", G.col("FLOW", "FV/FI")[z],
                                    G.col("FLOW", "target")[z], 2, "JUDGE", "C_COMPARE", G.col("FLOW", "low_range(%)")[z],
                                    G.col("FLOW", "high_range(%)")[z],name[j].split("Trim")[0] + 'value_f' ,"no",f)
                    # if list(FLOW["PE"])[z].upper() == "ERASE":
                    #     for u in range(len(list(NM_PATTERN["used"]))):
                    #         if list(NM_PATTERN["used"])[u] == "page erase 1st":
                    #             f.write('	RUN_PATTERN(' +
                    #                     list(NM_PATTERN["Pattern name"])[u].split(".")[0] + ':pe_1,' +
                    #                     list(NM_PATTERN["Pattern name"])[u].split(".")[
                    #                         0] + ':END,1,TS_5MHZ);\n\n')
                    # if list(FLOW["PE"])[z].upper() == "PROGRAM":
                    #     for u in range(len(list(NM_PATTERN["used"]))):
                    #         if list(NM_PATTERN["used"])[u] == "page program PCKB 1st":
                    #             f.write('	RUN_PATTERN(' +
                    #                     list(NM_PATTERN["Pattern name"])[u].split(".")[0] + ':pe_1,' +
                    #                     list(NM_PATTERN["Pattern name"])[u].split(".")[
                    #                         0] + ':END,1,TS_5MHZ);\n\n')
                    f.write('	RUN_PATTERN(exit_fbist_mode:START,exit_fbist_mode:END,1,TS_5MHZ);\n\n')
                    if "Hz" in G.col("FLOW", "UNIT")[z]:
                        f.write('')
                    else:
                        if G.col("FLOW", "UNIT")[z] == "uA" and G.col("FLOW", "FV/FI")[z] != "0V":
                            Force_Judge("uA", G.col("FLOW", "meas pin")[z], "0V", G.col("FLOW", "target")[z], 2, "FORCE", "PPMU",
                                    G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z],"" ,"no",f)
                        if G.col("FLOW", "UNIT")[z] == "V" and G.col("FLOW", "FV/FI")[z] != "0uA":
                            Force_Judge("V", G.col("FLOW", "meas pin")[z], "0uA", G.col("FLOW", "target")[z], 2, "FORCE", "PPMU",
                                        G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z],"" ,"no",f)

                    f.write('	CALL_MACRO POWER_OFF();\n\n')
                    _emit_flow_relay(f, relay, enabled=False)
                    _force_pass_write(f, z)
                    f.write("	CONDITION\n		IF_FAIL \n		REJECT_BIN = "+str(G.col("FLOW", "Hbin")[z])+";\n@@END_PLAN\n\n")
                elif dedicated_target:
                    copy_file(G.BASE_DIR + "\\pat_temp\\" + pattern[j] + ".sd",
                              G.OUT_DIR + "\\" + code_name[G.i] )
                    f.write("@@PLAN "+name[j].title() + "\n")
                    f.write("	SITE_SEQUENCE      = OFF;\n" +"	GO_THROUGH         = ON;\n"+ '	DISABLE_BY_MARK_NO = NULL;\n' +"	S_SETUP_FILE       = c:\\set.dat;\n"+
                                "	REMARK             = "+name[j].title() + '; \n\n')
                    f.write('	int trimDac[MAX_SITE],pdrPassflag[MAX_SITE];\n\n')
                    f.write('	int dacArray[16]={8,9,10,11,12,13,14,15,0,1,2,3,4,5,6,7}; \n\n')
                    f.write('	int cyc=0;\n')
                    f.write('	int endCyc='+str(G.col("FLOW", "DAC bit")[z])+";\n")
                    f.write('	char cycMsg[48];\n\n')

                    f.write('	//initial\n'+'	for(I=0;I<MAX_SITE;I++)\n'+'	{\n'+'		trimDac[I]=8;\n'+'		pdrPassflag[I]=0;\n'+'	}\n\n')
                    _emit_flow_relay(f, relay, enabled=True)
                    f.write("	CALL_MACRO POWER_ON(_C_VCC_MIN);\n\n")
                    f.write('	RUN_PATTERN(enter_fbist_mode:START,enter_fbist_mode:END,1,TS_5MHZ);\n\n')
                    f.write('	RUN_PATTERN(' + pattern[j] + ':START,' + pattern[j] + ':END,1,TS_5MHZ); \n\n')  
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
                                    f.write('	RUN_PATTERN(' + pattern[index + 1] + ':START,' + pattern[
                                                index + 1] + ':END,1,TS_5MHZ);  \n\n') 
                    f.write("	set_pdr_trim_data(trimDac);\n\n")

                    # PDR 切电压：对 .prj 全部真实电源轨执行（用户裁决 2026-06-12 方案2；
                    # 旧硬编码 VCC 在本芯片无此轨名 → 编译 Unknown 错）
                    for rail in prj_power_pins(code_name[G.i]):
                        f.write("	LOGIC_FORCE_DPS(" + rail + ", _C_VCC_PDR_TAR, 500MA, I7, WAIT=0.5MS);\n")
                    f.write("	LOGIC_SET_DRV_LEVEL(IO_ALLPINS, _C_VCC_PDR_TAR, 0.0V, 0.0V, VR1);\n")
                    f.write("	LOGIC_SET_CMP_LEVEL(IO_ALLPINS,_C_VCC_PDR_TAR*0.55,_C_VCC_PDR_TAR*0.45,VR2);\n")
                    f.write("	WAIT(10MS);\n\n")

                    f.write("	for(cyc=0;cyc<16;cyc++)\n	{\n"+'		sprintf(cycMsg,"pdr_trim_index_%d",cyc);\n		for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n		{\n			trimDac[T_SOCKET]=dacArray[cyc];\n		}\n\n')
                    f.write("		set_pdr_trim_data(trimDac);\n\n")
                    f.write('		RUN_PATTERN(read_status_mode:START,read_status_mode:END,1,TS_5MHZ);\n\n')
                    f.write('		for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n		{\n			if(Sys_DriverResult[T_SOCKET] < 0.5)\n			{\n				PDR_DAC_FINAL[T_SOCKET]=trimDac[T_SOCKET];\n				GB[4+T_SOCKET*64]=PDR_DAC_FINAL[T_SOCKET];\n			}\n			else\n			{\n')
                    f.write("				if(trimDac[T_SOCKET]==8)\n				{\n					PDR_DAC_FINAL[T_SOCKET]=8;\n					pdrPassflag[T_SOCKET]=1;\n				}\n			}\n			SYS_SetTestResult(PASS,T_SOCKET);\n		}\n	}\n\n")
                    f.write("	C_COMPARE(GB5,DOWN_LIMIT=0, UP_LIMIT=15, LOG_ALIAS= pdr_dac_f);\n\n")

                    f.write('	CALL_MACRO POWER_OFF();\n')
                    f.write("	CALL_MACRO POWER_ON(_C_VCC_MIN);\n\n")
                    f.write('	RUN_PATTERN(enter_fbist_mode:START,enter_fbist_mode:END,1,TS_5MHZ);\n\n')
                    f.write('	RUN_PATTERN(' + pattern[j] + ':START,' + pattern[j] + ':END,1,TS_5MHZ); \n\n')   
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
                                    f.write('	RUN_PATTERN(' + pattern[index + 1] + ':START,' + pattern[
                                                index + 1] + ':END,1,TS_5MHZ);  \n\n')
                    
                    for rail in prj_power_pins(code_name[G.i]):
                        f.write("	LOGIC_FORCE_DPS(" + rail + ", _C_VCC_PDR_MIN, 500MA, I7, WAIT=0.5MS);\n")
                    f.write("	LOGIC_SET_DRV_LEVEL(IO_ALLPINS, _C_VCC_PDR_MIN, 0.0V, 0.0V, VR1);\n")
                    f.write("	LOGIC_SET_CMP_LEVEL(IO_ALLPINS,_C_VCC_PDR_MIN*0.55,_C_VCC_PDR_MIN*0.45,VR2);\n")
                    f.write("	WAIT(10MS);\n\n")
                    f.write('	RUN_PATTERN(read_status_mode:START,read_status_mode:END,1,TS_5MHZ);\n\n')
                    f.write('	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n	{\n		if(Sys_DriverResult[T_SOCKET] > 0.5)\n		SYS_SetTestResult(PASS,T_SOCKET);\n		else\n		SYS_SetTestResult(FAIL,T_SOCKET);\n')
                    f.write('		if(pdrPassflag[T_SOCKET]==1)\n		SYS_SetTestResult(FAIL,T_SOCKET);\n	}\n\n')
                    f.write('	CALL_MACRO POWER_OFF();\n\n')
                    _emit_flow_relay(f, relay, enabled=False)
                    _force_pass_write(f, z)
                    f.write("	CONDITION\n		IF_FAIL \n		REJECT_BIN = "+str(G.col("FLOW", "Hbin")[z])+";\n@@END_PLAN\n\n")

            G.trash.append(name[j])


def verify_item_write(
    code_name, f, z, recipe_row=None, dac_write_plan=None,
    result_export_plan=None, pdr_verify_plan=None,
):
    # //////////////////////////////////////////////verify 写入start/////////////////////////////////////////////
    G.trash.clear()
    typed_pdr_verify = pdr_verify_plan is not None
    page_word = None if typed_pdr_verify else G.col("VERSION", "page word")[0]
    relay = pdr_verify_plan.relay if typed_pdr_verify else flow_relay(z)
    flow_item = (
        pdr_verify_plan.item
        if typed_pdr_verify
        else G.col("FLOW", "item")[z]
    )
    flow_cp = (
        pdr_verify_plan.cp
        if typed_pdr_verify
        else G.col("FLOW", "CP NO")[z]
    )
    if code_name[G.i].split("_")[-1] == flow_cp:
        item_key = _flow_item_key(flow_item)
        is_pdr_verify = typed_pdr_verify
        is_bor_verify = not typed_pdr_verify and item_key == "bor_verify"
        if not typed_pdr_verify and item_key == "pdr_verify":
            raise ValueError(
                "S100.PDR_VERIFY.PLAN_REQUIRED: typed plan is required"
            )
        is_fbist_verify = typed_pdr_verify or (
            G.col("FLOW", "type")[z] == "verify"
            and G.col("FLOW", "mode")[z] == "fbist"
        )
        if is_fbist_verify and not (is_pdr_verify or is_bor_verify):
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
                copy_file(G.BASE_DIR + "\\pat_temp\\" + setup_pattern + ".sd",
                          G.OUT_DIR + "\\" + code_name[G.i])
            f.write("@@PLAN " + generated_item.title() + "\n")
            f.write(
                "	SITE_SEQUENCE      = OFF;\n" +"	GO_THROUGH         = ON;\n"+ '	DISABLE_BY_MARK_NO = NULL;\n' + "	S_SETUP_FILE       = c:\\set.dat;\n" +
                "	REMARK             = " + generated_item.title() + '; \n\n')
            requires_result_capture = (
                result_export_plan is not None
                or G.col("FLOW", "UID")[z] == "yes"
                or "ts" in G.col("FLOW", "item")[z].lower()
            )
            if requires_result_capture:
                f.write("	C_ASSIGN(GB6,0); // verifyValue = GB6\n\n")
                if "ts" in G.col("FLOW", "item")[z].lower():
                    f.write("	C_ASSIGN(GB7,0); // TsValue = GB7\n\n")

            _emit_flow_relay(f, relay, enabled=True)
            f.write("	CALL_MACRO POWER_ON(_C_" + G.col("FLOW", "Vcc")[z].upper() + ");\n\n")

            f.write(
                '	RUN_PATTERN(enter_fbist_mode:START,enter_fbist_mode:END,1,TS_5MHZ);\n\n')
            for setup_index, setup_pattern in enumerate(setup_patterns):
                setup_operation = (setup_operations[setup_index]
                                   if setup_operations else None)
                if (setup_operation is not None
                        and setup_operation.name == "ENTER"
                            and getattr(setup_operation, "value_source", None) == "ARGUMENT"):
                    f.write("\tCALL_MACRO set_" + setup_pattern + "_data(" +
                            str(int(setup_operation.value, 2)) + ");\n")
                f.write('\tRUN_PATTERN(' + setup_pattern + ':START,' + setup_pattern + ':END,1,TS_5MHZ); \n\n')
                if (setup_operation is not None
                        and setup_operation.name == "ENTER"
                            and getattr(setup_operation, "value_source", None) == "ARGUMENT"):
                    f.write("\tCALL_MACRO set_" + setup_pattern + "_data(" +
                            str(int(setup_operation.dynamic_field.value, 2)) + ");\n\n")
            if dac_write_plan is not None:
                if dac_write_plan.value_source == "ADDR_MAP":
                    restore_expr = _dac_final_addrmap_expr(flow_item)
                    if restore_expr is None:
                        raise ValueError(
                            f"DAC_WRITE item {flow_item!r} 在当前 CP 无 Trim，且 ADDR_MAP 无法恢复"
                        )
                    f.write("\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n\t{\n\t\t" +
                            dac_write_plan.dac_symbol + "[T_SOCKET]=" +
                            restore_expr + ";\n\t}\n\n")
                elif dac_write_plan.value_source == "ARGUMENT":
                    f.write("\tint dacWriteData[MAX_SITE];\n")
                    f.write("\tfor(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n\t{\n\t\tdacWriteData[T_SOCKET]=" +
                            str(int(dac_write_plan.value, 2)) + ";\n\t}\n\n")
                write_source = (
                    "dacWriteData" if dac_write_plan.value_source == "ARGUMENT"
                    else dac_write_plan.dac_symbol
                )
                f.write("\tCALL_MACRO " + dac_write_plan.helper_name + "(" +
                        write_source + ");\n\n")
            if G.col("FLOW", "item")[z].split("_")[0].lower() in list(G.VERSION.columns):
                f.write(
                    '	RUN_PATTERN(set_all_final_vposp:START,set_all_final_vposp:END,1,TS_5MHZ); \n\n')

            if "Hz" in G.col("FLOW", "UNIT")[z]:
                Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                            G.col("FLOW", "target")[z], 2, "FORCE", "FREQ", G.col("FLOW", "low_range(%)")[z],
                            G.col("FLOW", "high_range(%)")[z],"" ,"no",f)
            else:
                Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                            G.col("FLOW", "target")[z], 2, "FORCE", "PMU", G.col("FLOW", "low_range(%)")[z],
                            G.col("FLOW", "high_range(%)")[z],"" ,"no",f)

            if G.col("FLOW", "PE")[z].upper() == "ERASE":
                for nm_name in G.nm_patterns("page erase 1st"):
                    copy_file(G.BASE_DIR + "\\pat_temp\\" +
                              nm_name + ".sd",
                              G.OUT_DIR + "\\" + code_name[G.i])
                    f.write('	RUN_PATTERN(' +
                            nm_name + ':START,' +
                            nm_name + ':pe_1,1,TS_5MHZ);\n\n')
            if G.col("FLOW", "PE")[z].upper() == "PROGRAM":
                for nm_name in G.nm_patterns("page program PCKB 1st"):
                    copy_file(G.BASE_DIR + "\\pat_temp\\" +
                              nm_name + ".sd",
                              G.OUT_DIR + "\\" + code_name[G.i])
                    f.write('	RUN_PATTERN(' +
                            nm_name + ':START,' +
                            nm_name + ':pe_1,1,TS_5MHZ);\n\n')


            if G.col("FLOW", "item")[z].split("_")[0].lower() in list(G.VERSION.columns):
                f.write(
                    "	LOGIC_PPMU_MV(" + G.col("FLOW", "meas pin")[z] + ", DOWN_LIMIT=_C_" + G.col("FLOW", "item")[z].split("_")[
                        0].upper() + '_TAR-0.05, UP_LIMIT=_C_' + G.col("FLOW", "item")[z].split("_")[
                        0].upper() + '_TAR+0.05' + ', LOG_ALIAS='+G.col("FLOW", "item")[z].lower()+", LOG_UNIT=_C_"+G.col("FLOW", "UNIT")[z] + ");\n\n")
            elif requires_result_capture:
                if "Hz" in G.col("FLOW", "UNIT")[z]:
                    Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                G.col("FLOW", "target")[z], 2, "JUDGE", "FREQ", G.col("FLOW", "low_range(%)")[z],
                                G.col("FLOW", "high_range(%)")[z],G.col("FLOW", "item")[z].lower(), "no",f)
                else:
                    Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                G.col("FLOW", "target")[z], 2, "JUDGE", "PMU", G.col("FLOW", "low_range(%)")[z],
                                G.col("FLOW", "high_range(%)")[z],G.col("FLOW", "item")[z].lower(), "no",f)
                f.write('	C_ASSIGN(GB6,' +G.col("FLOW", "meas pin")[z] + ');\n\n')
                f.write('	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n	{\n')
                if result_export_plan is not None and result_export_plan.format == "RAW":
                    f.write("\t\t" + result_export_plan.symbol +
                            "[T_SOCKET]=GB[5+T_SOCKET*64];\n")
                elif result_export_plan is not None and result_export_plan.format == "BCD16_MV":
                    f.write("\t\t" + result_export_plan.symbol +
                            "[T_SOCKET]=(int)(GB[5+T_SOCKET*64]*1000+0.5);\n")
                    f.write(
                        "\t\t" + result_export_plan.symbol + "[T_SOCKET]=((" +
                        result_export_plan.symbol + "[T_SOCKET]/1000)%10)*4096+((" +
                        result_export_plan.symbol + "[T_SOCKET]/100)%10)*256+((" +
                        result_export_plan.symbol + "[T_SOCKET]/10)%10)*16+(" +
                        result_export_plan.symbol + "[T_SOCKET]%10);\n")
                elif result_export_plan is not None and result_export_plan.format == "ADC12_3V3":
                    f.write("\t\tGB[6+T_SOCKET*64]=(int)(GB[5+T_SOCKET*64]/3.3*4096);\n")
                    f.write("\t\t" + result_export_plan.symbol +
                            "[T_SOCKET]=(int)(GB[5+T_SOCKET*64]/3.3*4096);\n")
                elif "ts" not in G.col("FLOW", "item")[z].lower():
                    f.write("		" + generated_item.split("Verify")[
                        0].upper() + "W[T_SOCKET]=(int)(GB[5+T_SOCKET*64]*1000+0.5);\n")
                    f.write(
                        "		" + generated_item.split("Verify")[0].upper() + "W[T_SOCKET]=((" + generated_item.split("Verify")[
                            0].upper() + "W[T_SOCKET]/1000)%10)*4096+((" + generated_item.split("Verify")[
                            0].upper() + "W[T_SOCKET]/100)%10)*256+((" + generated_item.split("Verify")[
                            0].upper() + "W[T_SOCKET]/10)%10)*16+(" + generated_item.split("Verify")[
                            0].upper() + "W[T_SOCKET]%10);\n")
                else:
                    f.write("		GB[6+T_SOCKET*64]=(int)(GB[5+T_SOCKET*64]/3.3*4096);\n")
                    if G.col("FLOW", "UID")[z] == "yes":
                        f.write("		TS_" + code_name[G.i].split("_")[-5].upper() + "_W[T_SOCKET]=(int)(GB[5+T_SOCKET*64]/3.3*4096);\n")
                    elif G.col("FLOW", "OTP")[z] == "yes":
                        f.write("		" + _otp_verify_register_var(G.col("FLOW", "item")[z]) +
                                "[T_SOCKET]=(int)(GB[5+T_SOCKET*64]/3.3*4096);\n")
                f.write("	}\n")

                if "ts"	in G.col("FLOW", "item")[z].lower():
                    f.write("\n	C_COMPARE(GB7, DOWN_LIMIT=" + str(int(round(
                        (calc_limit(G.col("FLOW", "target")[z], G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z], True)) / 3.3 * 4096, 0))) + ', UP_LIMIT=' +
                            str(int(round((calc_limit(G.col("FLOW", "target")[z], G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z], False)) / 3.3 * 4096,
                                          0))) + ', LOG_ALIAS=ts_' + code_name[G.i].split("_")[
                                -5] + '_value);\n')



            elif "ts" not in G.col("FLOW", "item")[z].lower():
                if "Hz" in G.col("FLOW", "UNIT")[z]:
                    Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                G.col("FLOW", "target")[z], 2, "JUDGE", "FREQ", G.col("FLOW", "low_range(%)")[z],
                                G.col("FLOW", "high_range(%)")[z],G.col("FLOW", "item")[z].lower(),"no" ,f)
                else:
                    Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                G.col("FLOW", "target")[z], 2, "JUDGE", "PMU", G.col("FLOW", "low_range(%)")[z],
                                G.col("FLOW", "high_range(%)")[z],G.col("FLOW", "item")[z].lower(),"no" ,f)

            if G.col("FLOW", "PE")[z].upper() == "ERASE":
                for nm_name in G.nm_patterns("page erase 1st"):
                    f.write('	RUN_PATTERN(' +
                            nm_name + ':pe_1,' +
                            nm_name + ':END,1,TS_5MHZ);\n\n')
            if G.col("FLOW", "PE")[z].upper() == "PROGRAM":
                for nm_name in G.nm_patterns("page program PCKB 1st"):
                    f.write('	RUN_PATTERN(' +
                            nm_name + ':pe_1,' +
                            nm_name + ':END,1,TS_5MHZ);\n\n')

            f.write(
                '\n	RUN_PATTERN(exit_fbist_mode:START,exit_fbist_mode:END,1,TS_5MHZ); \n\n')
            if "Hz" in G.col("FLOW", "UNIT")[z]:
                f.write('')
            else:
                if G.col("FLOW", "UNIT")[z] == "uA" and G.col("FLOW", "FV/FI")[z] != "0V":
                    Force_Judge("uA", G.col("FLOW", "meas pin")[z], "0V", G.col("FLOW", "target")[z], 2, "FORCE", "PPMU",
                            G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z],"" ,"no",f)
                if G.col("FLOW", "UNIT")[z] == "V" and G.col("FLOW", "FV/FI")[z] != "0uA":
                    Force_Judge("V", G.col("FLOW", "meas pin")[z], "0uA", G.col("FLOW", "target")[z], 2, "FORCE", "PPMU",
                                G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z],"" ,"no",f)


            if  G.col("FLOW", "OTP")[z] == "yes":
                addr_map_item = []
                title_flag=0
                pn_flag = ""
                for addr_cyc in range(len(G.col("ADDR_MAP", "Word No."))):
                    if G.col("ADDR_MAP", "Word No.")[addr_cyc] not in addr_map_item:
                        addr_map_item.append(G.col("ADDR_MAP", "Word No.")[addr_cyc])

                for cyc in range(len(addr_map_item)):
                    if code_name[G.i].split("_")[-1][-1] in G.col("ADDR_MAP", "line")[0 + page_word * cyc] and "lable" in list(
                            G.ADDR_MAP["data type"])[0 + page_word * cyc:(page_word - 1) + page_word * cyc]:
                        numbers = ''.join(filter(str.isdigit, G.col("ADDR_MAP", "line")[0 + page_word*cyc]))

                        if int(code_name[G.i].split("_")[-1][-1]) >= int(min(numbers)):
                            if addr_map_item[cyc] == "uid":
                                result = epr_pattern_capture("normal","cp" + str(int(code_name[G.i].split("_")[-1][-1])) + "_id")
                            else:
                                result = epr_pattern_capture("normal", addr_map_item[cyc])
                            for u in range(0 + page_word * cyc, (page_word-1) + page_word * cyc):

                                if G.col("ADDR_MAP", "data type")[u] == "lable" and generated_item in str(G.col("ADDR_MAP", "CP addr map")[u]):
                                    if title_flag == 0:
                                        f.write("\n	//******************" + addr_map_item[cyc] + " pattern**************************\n")
                                        title_flag = 1
                                    if "反码" in G.col("ADDR_MAP", "bit[31:16]")[u]:
                                        pn_flag = "yes"
                                    else:
                                        pn_flag = "no"
                                    if "TS" in G.col("FLOW", "item")[z].upper():
                                        if addr_map_item[cyc] == "uid":
                                            write_pat_mem(f, result, 16, "-J", 0, G.col("ADDR_MAP", "bit[15:0]")[u].split("[")[0],
                                                      G.col("ADDR_MAP", "bit[15:0]")[u].lower().split("verify")[0].upper() + "W",
                                                      G.col("ADDR_MAP", "bit[15:0]")[u].lower().split("_verify")[0].lower() + "_", pn_flag,"arr")
                                        else:
                                            write_pat_mem(f, result, 16, "-J", 0, G.col("ADDR_MAP", "bit[15:0]")[u].split("[")[0],
                                                      "REG_" + G.col("ADDR_MAP", "bit[15:0]")[u].split("[")[0].upper(),
                                                      G.col("ADDR_MAP", "bit[15:0]")[u].split("[")[0].lower() + "_", pn_flag, "arr")


                                    else:
                                        write_pat_mem(f, result, 16, "-J", 0, G.col("ADDR_MAP", "bit[15:0]")[u].split("[")[0],
                                                      "REG_" + G.col("ADDR_MAP", "bit[15:0]")[u].split("[")[0].upper(),
                                                      G.col("ADDR_MAP", "bit[15:0]")[u].split("[")[0].lower() + "_", pn_flag,"arr")

            f.write('\n	CALL_MACRO POWER_OFF();\n\n')
            _emit_flow_relay(f, relay, enabled=False)
            _force_pass_write(f, z)
            f.write("	CONDITION\n		IF_FAIL \n		REJECT_BIN = " + str(
                G.col("FLOW", "Hbin")[z]) + ";\n@@END_PLAN\n\n")
        if is_fbist_verify and (is_pdr_verify or is_bor_verify):
            if typed_pdr_verify:
                pattern_names = {
                    resource.role: resource.name
                    for resource in pdr_verify_plan.pattern_resources
                }
                enter_pattern = pattern_names["ENTER_PDR_VERIFY"]
                status_pattern = pattern_names["STATUS_READ"]
                initial_power_profile = pdr_verify_plan.initial_power_profile
            else:
                enter_pattern = "enter_" + flow_item.lower()
                status_pattern = "read_status_mode"
                initial_power_profile = G.col("FLOW", "Vcc")[z]
            flag_prefix = flow_item.lower().split("_")[0]
            copy_file(G.BASE_DIR + "\\pat_temp\\" + enter_pattern + ".sd",
                      G.OUT_DIR + "\\" + code_name[G.i] )
            f.write("@@PLAN " + flow_item.title() + "\n")
            f.write(
                "	SITE_SEQUENCE      = OFF;\n" +"	GO_THROUGH         = ON;\n"+ '	DISABLE_BY_MARK_NO = NULL;\n' + "	S_SETUP_FILE       = c:\\set.dat;\n" +
                "	REMARK             = " + flow_item.title() + '; \n\n')

            if is_pdr_verify:
                f.write("	int pdrVerifyflag[MAX_SITE];\n\n")
                space = 0
            else:
                f.write("	int borVerifyflag[MAX_SITE];\n\n")
                f.write("	int borDac["+str(len(G.col("FLOW", "LINE")[z].split("\n")[2].split(":")[1].split(",")))+"]={"+str(G.col("FLOW", "LINE")[z].split("\n")[2].split(":")[1])+"};\n")
                f.write("	double borRisingvoltage["+str(len(G.col("FLOW", "LINE")[z].split("\n")[0].split(":")[1].split(",")))+"]={"+str(G.col("FLOW", "LINE")[z].split("\n")[0].split(":")[1])+"};\n")
                f.write("	double borFallingvoltage["+str(len(G.col("FLOW", "LINE")[z].split("\n")[1].split(":")[1].split(",")))+"]={"+str(G.col("FLOW", "LINE")[z].split("\n")[1].split(":")[1])+"};\n")
                space = 2
            _emit_flow_relay(f, relay, enabled=True)
            f.write("	CALL_MACRO POWER_ON(_C_" + initial_power_profile.upper() + ");\n\n")
            f.write(
                '	RUN_PATTERN(enter_fbist_mode:START,enter_fbist_mode:END,1,TS_5MHZ);\n\n')
            f.write('	RUN_PATTERN(' + enter_pattern + ':START,' + enter_pattern + ':END,1,TS_5MHZ); \n\n')
            if is_pdr_verify:
                # PDR 切电压对全部真实电源轨执行（用户裁决 2026-06-12 方案2）
                for rail in prj_power_pins(code_name[G.i]):
                    f.write("	LOGIC_FORCE_DPS(" + rail + ", _C_VCC_PDR_MAX, 500MA, I7, WAIT=0.5MS);\n")
                f.write("	LOGIC_SET_DRV_LEVEL(IO_ALLPINS, _C_VCC_PDR_MAX, 0.0V, 0.0V, VR1);\n")
                f.write("	LOGIC_SET_CMP_LEVEL(IO_ALLPINS,_C_VCC_PDR_MAX*0.55,_C_VCC_PDR_MAX*0.45,VR2);\n")
                f.write("	WAIT(10MS);\n\n")
            else:
                f.write("	for(I=0;I<sizeof(borRisingvoltage)/sizeof(borRisingvoltage[0]);I++)\n	{\n")
                f.write("	CALL_MACRO set_bor_data(borDac[I]);\n\n")
                f.write("	CALL_MACRO POWER_ON(borFallingvoltage[I]);\n\n")
            copy_file(G.BASE_DIR + "\\pat_temp\\" + status_pattern + ".sd",
                        G.OUT_DIR + "\\" + code_name[G.i])
            f.write(space * " " + '	RUN_PATTERN(' + status_pattern + ':START,' + status_pattern + ':END,1,TS_5MHZ); \n\n')
            f.write(space * " " + '	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n' + space * " " + '	{\n' + space * " " + "		"+flag_prefix+'Verifyflag[T_SOCKET]=0;\n')
            f.write(space * " " + '		if(Sys_DriverResult[T_SOCKET] > 0.5) '+flag_prefix+'Verifyflag[T_SOCKET]=1;\n'+ space * " " + '	}\n\n')
            
            if is_pdr_verify:
                for rail in prj_power_pins(code_name[G.i]):
                    f.write("	LOGIC_FORCE_DPS(" + rail + ", _C_VCC_PDR_MIN, 500MA, I7, WAIT=0.5MS);\n")
                f.write("	LOGIC_SET_DRV_LEVEL(IO_ALLPINS, _C_VCC_PDR_MIN, 0.0V, 0.0V, VR1);\n")
                f.write("	LOGIC_SET_CMP_LEVEL(IO_ALLPINS,_C_VCC_PDR_MIN*0.55,_C_VCC_PDR_MIN*0.45,VR2);\n")
            else:
                f.write("	CALL_MACRO POWER_ON(borRisingvoltage[I]);\n\n")

            f.write(space * " " + '	RUN_PATTERN(' + status_pattern + ':START,' + status_pattern + ':END,1,TS_5MHZ); \n\n')
            f.write(space * " " + '	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n' + space * " " + '	{\n' + space * " " + "		"+flag_prefix+'Verifyflag[T_SOCKET]=0;\n')
            f.write(space * " " + '		if(Sys_DriverResult[T_SOCKET] < 0.5) '+flag_prefix+'Verifyflag[T_SOCKET]=1;\n'+ space * " " + '	}\n\n')

            if is_bor_verify:
                 f.write("	}\n\n")   

            f.write('	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n	{\n')
            f.write('		if('+flag_prefix+'Verifyflag[T_SOCKET]==1'+')\n		{\n			SYS_SetTestResult(FAIL,T_SOCKET);\n		}\n		else\n		{\n			SYS_SetTestResult(PASS,T_SOCKET);\n		}\n	}\n')

            f.write('\n	CALL_MACRO POWER_OFF();\n\n')
            _emit_flow_relay(f, relay, enabled=False)
            _force_pass_write(f, z)
            f.write("	CONDITION\n		IF_FAIL \n		REJECT_BIN = " + str(
                G.col("FLOW", "Hbin")[z]) + ";\n@@END_PLAN\n\n")
    G.trash.append(flow_item)


def _hex_rows(item_name, cp_no):
    """同 item+CP 下所有 mode=="hex" 的行号（verify 类型），按 FLOW 原始顺序。
    同 chroma/writers.py:_hex_rows，2026-07-06 移植（S100 侧新增，修复 handoff
    2026-07-05 第 4 条"S100 静默丢失 mode=hex 测试项"，如 Download_Code）。"""
    flow_item = G.col("FLOW", "item")
    flow_cp = G.col("FLOW", "CP NO")
    flow_type = G.col("FLOW", "type")
    flow_mode = G.col("FLOW", "mode")
    return [k for k in range(len(flow_item))
            if flow_item[k] == item_name and flow_cp[k] == cp_no
            and flow_type[k] == "verify" and flow_mode[k] == "hex"]


def _keil_rows_exist(item_name, cp_no):
    """同 item+CP 下是否混有 mode=="keil" 的行——S100 的 keil 紧凑记法架构（GET PIN
    触发/send_num/管脚对比较）尚未移植（2026-07-06 用户裁决暂缓，见
    .Codex/handoffs/2026-07-05-chroma-vs-s100-sync-gaps.md 第 4/5 条）。混用时明确
    报错，不要静默漏生成该测试项。"""
    flow_item = G.col("FLOW", "item")
    flow_cp = G.col("FLOW", "CP NO")
    flow_type = G.col("FLOW", "type")
    flow_mode = G.col("FLOW", "mode")
    return any(flow_item[k] == item_name and flow_cp[k] == cp_no
               and flow_type[k] == "verify" and flow_mode[k] == "keil"
               for k in range(len(flow_item)))


def _hex_step_body_write(code_name, f, z, dest_dir):
    """写一个 hex 行的 @@PLAN 函数体片段（不含 @@PLAN 头/REMARK/CONDITION 收尾）：
    固定三步 enter_fbist_mode+set_all_final_vposp+<step 列 pattern 名>，自己一次独立
    CALL_MACRO POWER_ON/POWER_OFF 包住（多 hex 交替合并场景用，见 hex_download_write）。
    S100 没有 Chroma JUDGE_PAT(pattern,__pattern) 那种"跑+判"合一指令——RUN_PATTERN
    只跑向量，pattern 内嵌的 strobe 失配由 @@PLAN 收尾的 CONDITION IF_FAIL 统一捕获；
    每步不单独加 TEST_NUM/DATALOG_MSG（**2026-07-06 实测修正**：本文件里 TEST_NUM/
    TEST_NO/DATALOG_MSG 这套写法只出现在从未被 main.py import 的历史死函数
    hex_code_item_write/hex_pattern_write 等里——它们是早年从 Chroma 语法误抄、从未
    编译验证过的遗留代码；用 tools/s100_compiler.py 真实编译一次后编译器报
    `Undefined symbol 'TEST_NUM'`，证实这套语法在 S100/YT5100 上根本不存在。真正
    活着能编过的写法是本文件 verify_item_write/trim_item_write 里大量"裸 RUN_PATTERN
    不单独标注"的既有约定——单个 pattern 的 strobe 失败完全由所在 @@PLAN 末尾的
    CONDITION IF_FAIL 统一捕获，@@PLAN 名字本身就是这条测试记录的标识，不需要每步
    再单独报数字/标签）。"""
    pattern_name = G.col("FLOW", "step")[z]
    copy_file(G.BASE_DIR + "\\pat_temp\\enter_fbist_mode.sd", dest_dir)
    copy_file(G.BASE_DIR + "\\pat_temp\\set_all_final_vposp.sd", dest_dir)
    copy_file(G.BASE_DIR + "\\pat_temp\\" + pattern_name + ".sd", dest_dir)

    f.write("	CALL_MACRO POWER_ON(_C_" + G.col("FLOW", "Vcc")[z].upper() + ");\n\n")
    f.write('	RUN_PATTERN(enter_fbist_mode:START,enter_fbist_mode:END,1,TS_5MHZ);\n\n')
    f.write('	RUN_PATTERN(set_all_final_vposp:START,set_all_final_vposp:END,1,TS_5MHZ);\n\n')
    f.write('	RUN_PATTERN(' + pattern_name + ':START,' + pattern_name + ':END,1,TS_5MHZ);\n\n')
    f.write('	CALL_MACRO POWER_OFF();\n\n')


def _keil_group_rows(item_name, cp_no):
    """同 item+CP 下所有 mode=="keil" 的行号（verify 类型），按 FLOW 原始顺序。
    同 chroma/writers.py:_keil_group_rows，2026-07-06 移植。"""
    flow_item = G.col("FLOW", "item")
    flow_cp = G.col("FLOW", "CP NO")
    flow_type = G.col("FLOW", "type")
    flow_mode = G.col("FLOW", "mode")
    return [k for k in range(len(flow_item))
            if flow_item[k] == item_name and flow_cp[k] == cp_no
            and flow_type[k] == "verify" and flow_mode[k] == "keil"]


def _hex_keil_ordered_rows(item_name, cp_no):
    """同 item+CP 下所有 mode in (hex,keil) 的行号（verify 类型），按 FLOW 原始顺序。
    同 chroma/writers.py:_hex_keil_ordered_rows，2026-07-06 移植。"""
    flow_item = G.col("FLOW", "item")
    flow_cp = G.col("FLOW", "CP NO")
    flow_type = G.col("FLOW", "type")
    flow_mode = G.col("FLOW", "mode")
    return [k for k in range(len(flow_item))
            if flow_item[k] == item_name and flow_cp[k] == cp_no
            and flow_type[k] == "verify" and flow_mode[k] in ("hex", "keil")]


_DPS_RANGES = [(5, "I1"), (25, "I2"), (250, "I3"), (2500, "I4"), (25000, "I5"), (250000, "I6")]


def _dps_range_and_compliance(high_limit_ua):
    """按电流上限（high_range 折算后的 UP_LIMIT，单位 uA）自动选 LOGIC_FORCE_DPS 的
    档位（I1~I6）+ compliance 字符串。2026-07-06 新增，档位表（用户给出）：
    I1<=5uA / I2<=25uA / I3<=250uA / I4<=2.5mA / I5<=25mA / I6<=250mA。

    **2026-07-06 实测修正**：最初按 target 本身直接当 compliance（依据真实参考
    `temp/L_PCD2509V1_PY32F420A_C8_30C_V00_50_12SS_CP1.prg:10505` target=2400uA →
    I4+compliance="2.4MA" 逆推），结果真实编译报 `Critical warning! DPS MI measure
    limit over/under clamp spec.`——因为该参考本身的 UP_LIMIT（28uA）远小于 compliance
    （2.4mA），两者不是同一回事：compliance 是"最坏情况下允许 DPS 灌多大电流"的安全
    上限，UP_LIMIT 是"实际期望测到的电流"，compliance 必须**明显大于** UP_LIMIT 才行
    （compliance 卡在跟 UP_LIMIT 同一量级甚至更低时，真实测量值一旦达到上限就会先撞
    上电流钳位、测不到真实值）。改成：**按本行的 UP_LIMIT（含 ±range% 后的上限）
    加 20% 余量选 compliance**，再按这个 compliance 挑档位（保证 compliance 本身也在
    所选档位量程内）。**这 20% 余量是本 session 给的保守经验值，不是任何真实参考验证
    过的确切数字**——如果之后有更精确的产品工程规格（例如"compliance 应比 spec 上限
    大多少倍"的既定惯例），应改用真实规格替换这个启发式。"""
    compliance_ua = abs(high_limit_ua) * 1.2
    for upper, rng in _DPS_RANGES:
        if compliance_ua <= upper:
            if upper >= 2500:
                compliance = ("%g" % round(compliance_ua / 1000, 3)) + "MA"
            else:
                compliance = ("%g" % round(compliance_ua, 3)) + "UA"
            return rng, compliance
    return "I6", ("%g" % round(compliance_ua / 1000, 3)) + "MA"


def _emit_clock_force_plan(f, plan, dest_dir):
    """输出已经计算好的 S100 外灌时钟计划。>=600kHz 走
    `LOGIC_SET_FREE_RUN_CLOCK_PIN` TMU 直接外灌；<600kHz 走 `RUN_PATTERN`+
    `<pin>_clkloop` 常驻子程序 pattern（`clock_force_pattern_created` 生成）——
    主 .sd + 子程序 .sr 都要 copy_file 进本程序目录（PATTERN_NAME 靠扫描输出目录
    现有 .sd 文件生成，pat_temp 里的源不会被 write_prj_file 自动看到，2026-07-07
    编译实测坐实"pattern not defined in PRJ file"）。"""
    for pin, info in plan.items():
        if info["mode"] == "tmu":
            f.write("	LOGIC_SET_FREE_RUN_CLOCK_PIN(" + pin + "," + str(int(round(info["freq_hz"]))) + ");\n")
        else:
            name = pin.lower() + "_clkloop"
            copy_file(G.BASE_DIR + "\\pat_temp\\" + name + ".sd", dest_dir)
            copy_file(G.BASE_DIR + "\\pat_temp\\R" + name + ".sr", dest_dir)
            # RUN_PATTERN 第 3 个参数是"这个时序名所在的 GROUP 号"（不是重复次数——
            # 2026-07-07 用户实测坐实，真实参考 PA10_1KHZ 用 1/100KHZ_PA8 用 2，各自
            # 对应它们时序名所在组）。TS_FORCE_CLK 声明在 GROUP_3（project_files.py
            # tim_hed_write），故这里填 3，不是默认的 1（早先按 GROUP_1 那套 1 试过，
            # 编译报 "TS_FORCE_CLK not found"，改 3 后过）。
            f.write("	RUN_PATTERN(" + name + ":START," + name + ":END,3,TS_FORCE_CLK);\n")
    f.write("\n")


def _emit_clock_force(f, z, dest_dir):
    """FLOW 行适配器；执行计划由 `clock_force.s100_row_plan` 计算。"""
    _emit_clock_force_plan(f, clock_force.s100_row_plan(z), dest_dir)


def _emit_clock_force_off_plan(f, plan):
    """S100 外灌时钟收尾：TMU 直接外灌的管脚传 NULL 关闭，pattern 降级的用
    `LOGIC_CLEAR_CONT()` 停常驻子程序（S100 侧不像 Chroma 那样互斥，收尾顺序无
    额外限制，2026-07-07 用户裁决）。"""
    for pin, info in plan.items():
        if info["mode"] == "tmu":
            f.write("	LOGIC_SET_FREE_RUN_CLOCK_PIN(NULL," + str(int(round(info["freq_hz"]))) + ");\n")
        else:
            f.write("	LOGIC_CLEAR_CONT();\n")
    f.write("\n")


def _emit_clock_force_off(f, z):
    """FLOW 行适配器；执行计划由 `clock_force.s100_row_plan` 计算。"""
    _emit_clock_force_off_plan(f, clock_force.s100_row_plan(z))


# ── T token 的量测/施压小件（2026-07-21 重构：抽出复用，消掉原 clk_forced/elec_forced
#    两个状态分支与纯 T 分支之间的代码重复；T 现在按 UNIT 出量测、施压(force/clock)独立）──

def _emit_pin_compare(f, meas_pin, target, dest_dir):
    """管脚对比较（pat 量测 / RCC-RTC 时钟收尾共用）：RUN_PATTERN(<pin1><pin2>_Cmp_<STATE>)。"""
    pin1, pin2 = str(meas_pin).split("+", 1)
    cmp_name = pin1.strip() + pin2.strip() + "_Cmp_" + str(target).strip().upper()
    copy_file(G.BASE_DIR + "\\pat_temp\\" + cmp_name + ".sd", dest_dir)
    f.write('	RUN_PATTERN(' + cmp_name + ':START,' + cmp_name + ':END,1,VIH_5MHZ);\n\n')


def _emit_dps_force(f, meas_pin, force_value, high):
    """DPS 施压（电流量测的 force 半，F token 与纯 T-uA 共用）。"""
    rng, compliance = _dps_range_and_compliance(high)
    f.write("	LOGIC_FORCE_DPS(" + meas_pin + ", _C_" + force_value + ", " + compliance
            + ", " + rng + ", WAIT=3MS);\n")


def _emit_dps_meas(f, meas_pin, low, high, sub_name):
    """DPS 电流量测+判定（elec_forced-T 与纯 T-uA 共用，逐字照原 GB30/GB31 写法）。"""
    f.write("	LOGIC_DPS_MI(" + meas_pin + ", UP_LIMIT=" + str(high) + "UA, DOWN_LIMIT="
            + str(low) + "UA,MEAS_LOOP=100,AVG);\n")
    f.write("	C_ASSIGN(GB30, " + meas_pin + ");\n")
    f.write("	C_MUL(GB30, 1000000);\n")
    f.write("	C_COMPARE(GB30, UP_LIMIT=" + str(high) + ", DOWN_LIMIT=" + str(low)
            + ", UNIT=UA, LOG_ALIAS=" + sub_name.upper() + ", LOG_UNIT=uA);\n")
    f.write("	C_ASSIGN(GB31, GB30);\n\n")


def _emit_freq_meas(f, unit, meas_pin, force_value, target, low_cell, high_cell, sub_name):
    """频率量测（TMU）：Force_Judge FREQ 的 FORCE(设电平+STARTPIN/STOPPIN)+JUDGE(SET_AND_START
    +MEAS_FREQ) 两段。"""
    _flog = str(sub_name).upper().replace(" ", "_")
    Force_Judge(unit, meas_pin, force_value, target, 0, "FORCE", "FREQ", low_cell, high_cell, _flog, "no", f)
    Force_Judge(unit, meas_pin, force_value, target, 0, "JUDGE", "FREQ", low_cell, high_cell, _flog, "no", f)
    f.write("\n")


def _sram_cap_judge(f, z, dest_dir):
    """keil `T` token 的 `UNIT=cap`+`cap_cfg=SRAM` 分支（2026-07-21 移植自 chroma
    _sram_cap_judge）：同 item+CP 的 keil 组**入口行生成整组 capture**、后续行跳过（capture 是
    整组一次读多个字）。单行=统一 limit（count=total_bits//bpd 个数同判据、alias 自动编号）；
    多行=逐数 limit（每行一个字、各自 low/high、alias=sub）。Read_SRAM 全局函数由 startup
    生成、sram_capture.sd 是手工种子（copy_file 拷入程序目录 → get_sd_filenames_with_os 登记）。"""
    from program_gen.platforms.s100.capture import parse_cap_cfg, capture_sram_write
    item_z = G.col("FLOW", "item")[z]
    cp_z = G.col("FLOW", "CP NO")[z]
    grp = _keil_group_rows(item_z, cp_z)
    if z != grp[0]:
        return   # 后续行，capture 已在入口行生成
    cap_cfg_val = str(G.col("FLOW", "cap_cfg")[z]).strip()
    if cap_cfg_val.split("-")[0].upper() != "SRAM":
        raise ValueError("keil T(UNIT=cap) 目前只支持 cap_cfg=SRAM，实际 '" + cap_cfg_val + "'")
    copy_file(G.BASE_DIR + "\\pat_temp\\sram_capture.sd", dest_dir)
    _pat, base, total_bits, bpd = parse_cap_cfg(cap_cfg_val)
    count = total_bits // bpd
    low_col = G.col("FLOW", "low_range(%)")
    high_col = G.col("FLOW", "high_range(%)")
    sub_col = G.col("FLOW", "sub")
    sub_z = str(G.col("FLOW", "sub")[z]).strip()
    if len(grp) == 1:
        entries = [(low_col[z], high_col[z], sub_z + "_" + str(k)) for k in range(count)]
        uniform, banner = True, (sub_z if sub_z != "/" else item_z)
    else:
        entries = [(low_col[r], high_col[r], str(sub_col[r]).strip()) for r in grp]
        uniform, banner = False, None
    capture_sram_write(f, base, entries, uniform, banner)


def _keil_step_write(f, z, get_pin, dest_dir, entry_only=False, emit_banner=True,
                     step_override=None):
    """写一个 sub 行（一个功耗模式）的紧凑 step 记法，S100 版本。FLOW.step 语法与
    Chroma 完全一致（`chroma/writers.py:_keil_step_write` 的 docstring 有完整说明，
    这里不重复），只是把生成的目标指令换成 S100 语法（2026-07-06 移植，依据用户提供
    的真实参考 `temp/LAB_PY32F420A_C8_25C_V00_50_1SS_FT/Z_..._FT.prg`（TRIGGER_HL/
    Trigger_Num pattern 引用写法）+ `temp/L_PCD2509V1_..._12SS_CP1.prg:10490`
    （`Power_test` @@PLAN 的电流量测写法））：
      电平序列 — H/L 任意长度逐字符一段（H/HL/HH/LL/HLHL…），紧跟 "-<数字><ns|us|ms>"
                指定每段宽度（默认 1ms）；RUN_PATTERN(<触发管脚>_<序列>_<宽度>:START,
                ...:END,1,VIH_5MHZ)（2026-07-15 泛化自原写死的 HL）
      裸整数N — RUN_PATTERN(<触发管脚>_send_num:s<3位十进制N>_st,...:s<...>_sp,1,VIH_5MHZ)
                （S100 送码标签是 3 位十进制，不是 Chroma 的十六进制，见
                get_pin_patterns_created 里 `_send_num_sd_write`）
      W<n>   — WAIT(<n>MS);
      T      — 两种互斥写法（按 UNIT 列区分，同 Chroma）：
               ① UNIT=="pat" → 管脚对比较：RUN_PATTERN(<pin1><pin2>_Cmp_<STATE>:START,
                  ...:END,1,VIH_5MHZ)（S100 没有 JUDGE_PAT 合一指令，失败由 @@PLAN
                  收尾 CONDITION IF_FAIL 统一捕获，同 hex_download_write 的既有约定）；
               ② 否则 → 电流量测：`LOGIC_FORCE_DPS`+`WAIT`+`LOGIC_DPS_MI`+`C_ASSIGN`+
                  `C_MUL`+`C_COMPARE`（逐字照抄真实参考的 GB30/GB31 写法，compliance/
                  档位见 `_dps_range_and_compliance`；`LOG_ALIAS` 用该行 sub 列大写命名，
                  对齐参考的 STOP0/STOP1 命名）。**目前只验证过 UNIT=="uA" 这一种量测
                  单位**（母本 Power_Test 三个 sub 都是 uA），其它单位没有真实参考、
                  未实现，遇到会抛错而不是猜语法生成错误代码。
    S100 没有 reset_pattern 概念——真实参考里每次判定完直接靠 POWER_OFF 收尾（见
    `_keil_group_body_write`/`_multi_hex_keil_write`），不需要额外收尾 pattern。"""
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

    if emit_banner:   # swd_pattern_write 把 sub 横幅提到配置 pattern 之前写，这里跳过（2026-07-21）
        f.write("	////////////////////" + sub_name.upper() + "////////////////////\n")
    clk_forced = False   # 本行 step 是否出现过 "F" token 且走外灌时钟（2026-07-07）
    clk_stopped = False  # 本行 step 是否已由 "FS" token 显式停过外灌（2026-07-23）
    elec_forced = False  # 本行 step 是否出现过 "F" token 且走电流 force（2026-07-07）
    step_value = G.col("FLOW", "step")[z] if step_override is None else step_override
    step_lines = str(step_value).strip().splitlines()
    for step_str in step_lines:
        step_str = step_str.strip()
        if not step_str:
            continue
        if ":" in step_str:
            trig_pin, step_str = step_str.split(":", 1)
            trig_pin = trig_pin.strip()
            is_default_trig = False
        else:
            trig_pin = get_pin
            is_default_trig = True
        # 触发/发码 pattern 显示前缀：默认触发用 `Trig`（不烤死真实 pin），显式用该 pin
        # （2026-07-24 用户裁决，对称 chroma）。真实 pin=trig_pin 仍是 HEADER 驱动脚。
        disp = trig_disp(trig_pin, is_default_trig)
        tokens = step_str.split("-")
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            # entry_only（2026-07-17，供 dc_scan_writer 复用触发部分）：DC 扫描族行的
            # step 常带字面 "T"，但 PPMU 组量测是 dc_scan_writer 自己写的，不走 T token
            # 的单 pin judge——只处理入口触发（H/L 序列、裸数字发码、W），T 跳过。
            if entry_only and tok == "T":
                i += 1
                continue
            if tok == "F":
                # 2026-07-07 用户裁决扩展：FV/FI 是 "<PIN>:<freq>" 才走外灌时钟，
                # 否则按 UNIT 列走 force 电流（S100 目前只验证过 UNIT=="uA" 这一种，
                # 同 T 分支既有限制，未验证单位直接抛错不猜语法）。
                if clock_force.is_clock_force_cell(G.col("FLOW", "FV/FI")[z]):
                    _emit_clock_force(f, z, dest_dir)
                    clk_forced = True
                elif str(unit).strip().lower() == "ua":
                    high = calc_limit(target, G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z], False)
                    _emit_dps_force(f, meas_pin, force_value, high)
                    elec_forced = True
                else:
                    # 2026-07-21 与 Chroma F token 同步：非 uA 的 F 施压走 parse_fv_fi 解耦多
                    # pin（<PIN>:值），IO pin → LOGIC_PPMU_FV 前置施压并保持到下电（如 TK 前置
                    # force PA0:3.3V，收尾走 T 的 UNIT=cap capture）。电源轨/uA 施压仍走上面
                    # 的 DPS 分支，不进这里。档位 E2/I7 取自用户提供的 TK_S100 参考。
                    for fpin, fval in parse_fv_fi(G.col("FLOW", "FV/FI")[z], meas_pin):
                        try:
                            float(fval)
                            fval_w = fval + "V"
                        except ValueError:
                            fval_w = fval
                        f.write("	LOGIC_PPMU_FV(" + fpin + ", " + fval_w + ", E2, I7);\n\n")
            elif LEVEL_SEQ_RE.fullmatch(tok):
                # 电平序列 token（H/L 任意长度，逐字符一段；2026-07-15 泛化自原写死的
                # "HL"）。紧跟的 <数字><ns|us|ms> 是每段宽度（消费掉 i+=1），不写=默认 1ms。
                levels = tok
                rpt, width_str = default_pulse()
                if i + 1 < len(tokens) and parse_pulse_width(tokens[i + 1]):
                    rpt, width_str = parse_pulse_width(tokens[i + 1])
                    i += 1
                pat_real = level_seq_pat_name(trig_pin, levels, width_str)   # 种子按真实 pin
                pat_name = level_seq_pat_name(disp, levels, width_str)       # 引用/文件用显示名
                copy_trig_sd(pat_real, pat_name, dest_dir)
                f.write('	RUN_PATTERN(' + pat_name + ':START,' + pat_name
                         + ':END,1,VIH_5MHZ);\n\n')
            elif tok.isdigit():
                n = int(tok)
                label = "s%03d" % n
                base = disp + "_send_num"
                copy_trig_sd(trig_pin + "_send_num", base, dest_dir)
                f.write('	RUN_PATTERN(' + base + ':' + label + '_st,'
                         + base + ':' + label + '_sp,1,VIH_5MHZ);\n\n')
            elif tok.startswith("W") and tok[1:].isdigit():
                f.write("	WAIT(" + tok[1:] + "MS);\n")
            elif tok == "T":
                # T = 按 UNIT 出量测；施压(force/clock)是独立前置步（F token 做，或本分支按需补）。
                # clk_forced（RCC/RTC）单独先判：它 UNIT 填 "/"、不带量测类型信息，语义是"时钟
                # 已灌 → 跑管脚比较 + 关时钟"，只能靠状态区分（2026-07-21 重构：其余全按 UNIT）。
                _ul = str(unit).strip().lower()
                if clk_forced:
                    _emit_pin_compare(f, meas_pin, target, dest_dir)
                    if not clk_stopped:   # 2026-07-23：FS 已提前停外灌则不重复停
                        _emit_clock_force_off(f, z)
                elif str(G.col("FLOW", "cap_cfg")[z]).strip() != "/":
                    # UNIT=cap + cap_cfg（SRAM capture，2026-07-21）：整组入口行生成逐字
                    # Read_SRAM + JUDGE_VARIABLE（同 chroma T(cap) 分支的 _sram_cap_judge）。
                    _sram_cap_judge(f, z, dest_dir)
                elif _ul == "pat":
                    _emit_pin_compare(f, meas_pin, target, dest_dir)
                elif _ul == "ua":
                    low = calc_limit(target, G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z], True)
                    high = calc_limit(target, G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z], False)
                    if not elec_forced:   # 纯 T：先施压+固定等待；F 已 force 过则跳过（W token 控等待）
                        _emit_dps_force(f, meas_pin, force_value, high)
                        f.write("	WAIT(100MS);\n")
                    _emit_dps_meas(f, meas_pin, low, high, sub_name)
                elif "hz" in _ul:
                    # 测频（KHz/MHz，如 Hsi_Verify/Clock_check/PLL/Hse）。**若 FV/FI 是外灌时钟
                    # 格式（如 Hse 的 PD0:32MHz）→ 先灌时钟再测、测完关**（2026-07-21 修 Hse 外灌
                    # 缺失：外灌只被 "F" token 消费，Hse step 只有 "T"，故这里按 FV/FI 自动补）；
                    # 内部时钟项（FV/FI="/"）不灌。触发在前面的电平序列/送码 token 已出。
                    _clk = clock_force.is_clock_force_cell(G.col("FLOW", "FV/FI")[z])
                    if _clk:
                        _emit_clock_force(f, z, dest_dir)
                    _emit_freq_meas(f, unit, meas_pin, force_value, target,
                                    G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z], sub_name)
                    if _clk:
                        _emit_clock_force_off(f, z)
                else:
                    raise NotImplementedError(
                        "_keil_step_write: sub='" + sub_name + "' UNIT='" + str(unit) + "' 不是 uA / pat / 频率，"
                        "S100 侧目前只有 uA 电流量测、pat 管脚比较、KHz 频率量测三种真实参考，"
                        "其它单位没有验证过的写法，不猜语法生成，请先补充真实参考再扩展。")
            elif tok == "RP":
                # 2026-07-23：上下电循环（re-power），同 Chroma。中途成对下电+上电。
                f.write("\tCALL_MACRO POWER_OFF();\n\tCALL_MACRO POWER_ON(_C_"
                        + G.col("FLOW", "Vcc")[z].upper() + ");\n\n")
            elif tok == "FS":
                # 2026-07-23：停外灌（force stop）。停后置 clk_stopped，后续 T 的 clk_forced
                # 分支跳过重复停（判定本就是 compare pattern）。无 FS 老路径逐字不变。
                if clk_forced and not clk_stopped:
                    _emit_clock_force_off(f, z)
                    clk_stopped = True
            else:
                raise ValueError(
                    "_keil_step_write: 未识别的 step token '" + tok + "'（sub=" + sub_name + "）")
            i += 1


def _keil_group_body_write(f, keil_rows, get_pin, dest_dir):
    """写纯 keil 组（不含 hex 行）的函数体片段：一次 CALL_MACRO POWER_ON 包住全部 sub
    步骤，末尾一次 CALL_MACRO POWER_OFF。同 chroma/writers.py:_keil_group_body_write，
    2026-07-06 移植。"""
    f.write("	CALL_MACRO POWER_ON(_C_" + G.col("FLOW", "Vcc")[keil_rows[0]].upper() + ");\n\n")
    for sub_cyc in keil_rows:
        _keil_step_write(f, sub_cyc, get_pin, dest_dir)
    f.write("	CALL_MACRO POWER_OFF();\n")


def _keil_sub_step_write(f, z, get_pin, dest_dir):
    """写一个 keil sub 行的函数体片段：自己独立一次 CALL_MACRO POWER_ON/POWER_OFF
    包住单个 sub（hex+keil 混用场景用，见 _multi_hex_keil_write；同真实参考
    `Power_test` 每个 STOP0/STOP1/STANDBY 各自独立开关电的写法）。"""
    f.write("	CALL_MACRO POWER_ON(_C_" + G.col("FLOW", "Vcc")[z].upper() + ");\n\n")
    _keil_step_write(f, z, get_pin, dest_dir)
    f.write("	CALL_MACRO POWER_OFF();\n")


def _multi_hex_keil_write(code_name, f, item_name, ordered_rows, dest_dir, get_pin):
    """同 item+CP 下 hex/keil 混用（如 `Power_Test`：1 个 hex 下载行 + 若干 keil 功耗
    sub 行）时的合并写法：按 FLOW 原始顺序把所有 hex/keil 行依次写进同一个 @@PLAN，
    每行各自独立一次 CALL_MACRO POWER_ON/POWER_OFF（同真实参考 `Power_test` 的写法、
    同 chroma/writers.py:_multi_hex_keil_write 语义，2026-07-06 移植）。"""
    for row in ordered_rows:
        if G.col("FLOW", "mode")[row] == "hex":
            _hex_step_body_write(code_name, f, row, dest_dir)
        else:
            _keil_sub_step_write(f, row, get_pin, dest_dir)


# S100 侧尚未实现、先出占位空 @@PLAN 的测试项（2026-07-17 用户裁决：先跳过测试内容、
# 只出 PLAN 骨架，保证结构完整/可编译/@@BOOKING 引用可解析，后续再补真实实现）：
#   - DC-scan 家族 Leakage/RPDRPU/VOLVOH/VIHVIL（Chroma-only，见 chroma/dc_scan_writer.py，
#     交接 B2；补时对齐 ODD/EVEN PPMU 交叉 force + golden temp/LAB_PY32F420A/Z_*.prg）。
#   - Hsi_Verify（keil KHz 频率量测；补时用 golden 的 LOGIC_TMU_MEAS_FREQ 序列，
#     缺母本字段：量测/TMU 管脚、AVG、STARTPIN 待定）。
_STUB_PLAN_ITEMS = {
    # Leakage / RPDRPU / VOLVOH / VIHVIL / Hsi_Verify 均已真实实现——DC-scan 家族 +
    # keil KHz 频率量测全部落地，占位机制暂无成员（保留机制供后续未实现项兜底）。
}


def _dc_scan_stub_plan_write(f, item_name, hbin):
    """DC-scan 家族 S100 未实现的占位 @@PLAN：沿用 keil_pattern_write 的 PLAN 骨架，
    body 只留 TODO 注释（不生成任何测试语句、隐含 PASS），保证 @@BOOKING 引用可解析、
    程序可编译。2026-07-17 用户裁决，后续补真实实现。"""
    plan = item_name.title()
    f.write("@@PLAN " + plan + "\n")
    f.write(
        "	SITE_SEQUENCE      = OFF;\n" + "	GO_THROUGH         = ON;\n" + '	DISABLE_BY_MARK_NO = NULL;\n' +
        "	S_SETUP_FILE       = c:\\set.dat;\n" + "	REMARK             = " + plan + '; \n\n')
    f.write("	//TODO: S100 (" + item_name + ") not implemented yet; placeholder empty PLAN\n")
    f.write("\n	CONDITION\n		IF_FAIL \n		REJECT_BIN = " + str(hbin) + ";\n@@END_PLAN\n\n")


def keil_pattern_write(code_name, f, z):
    """type=="verify" and mode=="keil" 项：header+sub 多行机制（同 hex_download_write
    同一套约定），只在"入口行"（本 CP 内该 item 名第一次出现的 keil 行）触发一次。
    同 chroma/writers.py:keil_pattern_write 语义移植（2026-07-06）。

    若同 item+CP 下还有 mode=="hex" 的行（如 `Power_Test`：先下载 hex 再测功耗），
    整块（含本 keil 组）由 `hex_download_write` 一次触发写出（避免生成两个同名
    @@PLAN），这里直接让路。"""
    if not (code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[z]
            and G.col("FLOW", "type")[z] == "verify" and G.col("FLOW", "mode")[z] == "keil"):
        return
    item_name = G.col("FLOW", "item")[z]
    cp_no = G.col("FLOW", "CP NO")[z]
    if _hex_rows(item_name, cp_no):
        return  # 该 item+CP 还有 hex 行，整块交给 hex_download_write
    keil_rows = _keil_group_rows(item_name, cp_no)
    if z != keil_rows[0]:
        return  # 非入口行（同组更早已经处理过），跳过避免重复开 @@PLAN

    # S100 未实现的族（DC-scan/Hsi_Verify，2026-07-17 用户裁决）：不进真实 keil 生成，
    # 只出占位 PLAN。
    if item_name in _STUB_PLAN_ITEMS:
        _dc_scan_stub_plan_write(f, item_name, G.col("FLOW", "Hbin")[z])
        return

    get_pin = G.col("VERSION", "GET PIN")[G.i]
    dest_dir = G.OUT_DIR + "\\" + code_name[G.i]
    f.write("@@PLAN " + item_name.title() + "\n")
    f.write(
        "	SITE_SEQUENCE      = OFF;\n" + "	GO_THROUGH         = ON;\n" + '	DISABLE_BY_MARK_NO = NULL;\n' +
        "	S_SETUP_FILE       = c:\\set.dat;\n" + "	REMARK             = " + item_name.title() + '; \n\n')
    _keil_group_body_write(f, keil_rows, get_pin, dest_dir)
    _force_pass_write(f, z)
    f.write("\n	CONDITION\n		IF_FAIL \n		REJECT_BIN = " + str(G.col("FLOW", "Hbin")[z]) + ";\n@@END_PLAN\n\n")


def _swd_group_rows(item_name, cp_no):
    """同 item+CP 下所有 mode=="swd" 的 verify 行号（FLOW 原序）。同
    chroma\\writers.py:_swd_group_rows（2026-07-20 移植）——swd 组多 sub 共用一次上下电。"""
    flow_item = G.col("FLOW", "item")
    flow_cp = G.col("FLOW", "CP NO")
    flow_type = G.col("FLOW", "type")
    flow_mode = G.col("FLOW", "mode")
    return [k for k in range(len(flow_item))
            if flow_item[k] == item_name and flow_cp[k] == cp_no
            and flow_type[k] == "verify" and flow_mode[k] == "swd"]


def _swd_pat_name(product_name, item_name, sub_z):
    """swd 入口配置 pattern 名：`<product>_SWD_<sub 或 item 去掉最后一个下划线段>`。
    逐字对位 chroma\\writers.py:_swd_pat_name（sub=="/" 退回 item；单段 sub 原样用、
    多段丢最后一段）。"""
    sub_raw = str(G.col("FLOW", "sub")[sub_z]).strip()
    name_src = item_name if sub_raw == "/" else sub_raw
    parts = name_src.split("_")
    stem = "_".join(parts[:-1]) if len(parts) > 1 else parts[0]
    return product_name + "_SWD_" + stem


def swd_pattern_write(code_name, f, z):
    """type=="verify" and mode=="swd" 项：固定 pattern link 机制（对位
    chroma\\writers.py:swd_pattern_write，2026-07-20 移植）。每 sub 先 link 一个固定 swd
    配置 pattern（`<product>_SWD_<名>`，走 SWD 调试口把芯片配成待测状态，取代 keil 的
    HL+发码触发），再复用 `_keil_step_write` 处理 step 列的 T token（含频率量测→
    Force_Judge FREQ，即 Clock_check/Hse/PLL 与 Hsi_Verify 共用的同一套 TMU 测频）。同
    item+CP 多 sub 共用一次 POWER_ON..POWER_OFF。swd 行 step 列不会出现 HL/裸数字（那是
    keil 触发专用），_keil_step_write 天然只处理它遇到的 token。

    **外部 swd 配置 pattern 若 pat_temp 里没有，copy_file 落占位假图形（同 S0 兜底）：
    能编过但非真实向量，上机前需真实覆盖。** F4 ADC 的 swd 另有 IOMUX 反查机制（对位
    chroma adc_test_write），不走本函数——遇到会照常 link 一个 `_SWD_Adc` 假图形+按其
    step 处理，语义不对，需另行实现（见 main.py 分派处的说明）。"""
    if not (code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[z]
            and G.col("FLOW", "type")[z] == "verify" and G.col("FLOW", "mode")[z] == "swd"):
        return
    item_name = G.col("FLOW", "item")[z]
    cp_no = G.col("FLOW", "CP NO")[z]
    swd_rows = _swd_group_rows(item_name, cp_no)
    if z != swd_rows[0]:
        return  # 非整组入口，让路（同组更早的行已处理）
    get_pin = G.col("VERSION", "GET PIN")[G.i]
    dest_dir = G.OUT_DIR + "\\" + code_name[G.i]
    product_name = str(G.col("VERSION", "product name")[G.i]).strip()

    # F4 ADC swd（FV/FI=ADCn）走 IOMUX capture 机制（对位 chroma adc_test_write），与本
    # 函数的频率/pattern-link 不同、S100 尚未实现——出占位 @@PLAN（既不静默丢、也避免
    # UNIT=cap 的 T token 落到 _keil_step_write 的 else 抛 NotImplementedError 崩生成）。
    # 待后续单独移植 ADC 族再从这里放行。
    if any(str(G.col("FLOW", "FV/FI")[r]).strip().upper().startswith("ADC") for r in swd_rows):
        _dc_scan_stub_plan_write(f, item_name, G.col("FLOW", "Hbin")[z])
        return

    f.write("@@PLAN " + item_name.title() + "\n")
    f.write(
        "	SITE_SEQUENCE      = OFF;\n	GO_THROUGH         = ON;\n	DISABLE_BY_MARK_NO = NULL;\n"
        "	S_SETUP_FILE       = c:\\set.dat;\n	REMARK             = " + item_name.title() + "; \n\n")
    f.write("	CALL_MACRO POWER_ON(_C_" + str(G.col("FLOW", "Vcc")[swd_rows[0]]).strip().upper() + ");\n\n")
    for sub_z in swd_rows:
        pat_name = _swd_pat_name(product_name, item_name, sub_z)
        copy_file(G.BASE_DIR + "\\pat_temp\\" + pat_name + ".sd", dest_dir)
        # sub 横幅放在配置 pattern 之前（该 sub 从这里开始更清晰，2026-07-21 用户要求）；
        # _keil_step_write 里的横幅用 emit_banner=False 关掉，避免重复。
        f.write("	////////////////////" + str(G.col("FLOW", "sub")[sub_z]).strip().upper() + "////////////////////\n")
        f.write("	RUN_PATTERN(" + pat_name + ":START," + pat_name + ":END,1,TS_5MHZ);\n\n")
        _keil_step_write(f, sub_z, get_pin, dest_dir, emit_banner=False)
    f.write("	CALL_MACRO POWER_OFF();\n")
    _force_pass_write(f, z)
    f.write("\n	CONDITION\n		IF_FAIL \n		REJECT_BIN = " + str(G.col("FLOW", "Hbin")[z]) + ";\n@@END_PLAN\n\n")


def hex_download_write(code_name, f, z):
    """type=="verify" and mode=="hex" 项：下载 hex，固定跑三步——enter_fbist_mode +
    set_all_final_vposp + <step 列给的 pattern 名>（step 列直接填字面量 pattern 名，
    非 keil 那套紧凑记法），自己一次上下电包住。同 chroma/writers.py:hex_download_write
    语义移植（2026-07-06，修复 handoff 2026-07-05 第 4 条"S100 静默丢失 mode=hex 测试项"
    ——golden 母本 FLOW 第153行 Download_Code/CP3 就是这个场景，之前 S100 生成器直接
    跳过、不生成任何东西也不报错）。

    若同 item+CP 下有 >=2 行 mode=="hex"（如下载-测试交替好几轮），对每行各开一次同名
    @@PLAN 会重复定义、编译报错——只在整组入口（z==该组第一行）触发一次，把所有行的
    三步依次写进同一个 @@PLAN，每行各自独立开关电。

    若同 item+CP 下混有 mode=="keil" 的行（如 `Power_Test`：1 个 hex 下载行 + 3 个
    keil 功耗 sub 行）——2026-07-06 用户提供真实参考后已移植 keil 架构（见
    `_keil_step_write`/`get_pin_patterns_created`），改走 `_multi_hex_keil_write`
    合并写法，每行各自独立上下电（同真实参考 `Power_test` @@PLAN 的写法）。"""
    if not (code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[z]
            and G.col("FLOW", "type")[z] == "verify" and G.col("FLOW", "mode")[z] == "hex"):
        return
    item_name = G.col("FLOW", "item")[z]
    cp_no = G.col("FLOW", "CP NO")[z]
    dest_dir = G.OUT_DIR + "\\" + code_name[G.i]
    get_pin = G.col("VERSION", "GET PIN")[G.i]

    if _keil_rows_exist(item_name, cp_no):
        ordered = _hex_keil_ordered_rows(item_name, cp_no)
        if z != ordered[0]:
            return  # 非整组入口，让路
        f.write("@@PLAN " + item_name.title() + "\n")
        f.write(
            "	SITE_SEQUENCE      = OFF;\n" + "	GO_THROUGH         = ON;\n" + '	DISABLE_BY_MARK_NO = NULL;\n' +
            "	S_SETUP_FILE       = c:\\set.dat;\n" + "	REMARK             = " + item_name.title() + '; \n\n')
        _multi_hex_keil_write(code_name, f, item_name, ordered, dest_dir, get_pin)
        _force_pass_write(f, z)
        f.write("	CONDITION\n		IF_FAIL \n		REJECT_BIN = " + str(G.col("FLOW", "Hbin")[z]) + ";\n@@END_PLAN\n\n")
        return

    hex_rows = _hex_rows(item_name, cp_no)
    if z != hex_rows[0]:
        return  # 非整组入口（同 item+CP 下更早的 hex 行已经处理过），让路避免重复开 @@PLAN

    f.write("@@PLAN " + item_name.title() + "\n")
    f.write(
        "	SITE_SEQUENCE      = OFF;\n" + "	GO_THROUGH         = ON;\n" + '	DISABLE_BY_MARK_NO = NULL;\n' +
        "	S_SETUP_FILE       = c:\\set.dat;\n" + "	REMARK             = " + item_name.title() + '; \n\n')

    for row in hex_rows:
        _hex_step_body_write(code_name, f, row, dest_dir)

    _force_pass_write(f, z)
    f.write("	CONDITION\n		IF_FAIL \n		REJECT_BIN = " + str(G.col("FLOW", "Hbin")[z]) + ";\n@@END_PLAN\n\n")


def hex_pattern_write(code_name, f, z):
    step_list = []
    relay_off = "	RELAY_OFF("
    relay_pin = []
    if code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[z]:
        if G.col("FLOW", "mode")[z] == "hex":
            step_list = G.col("FLOW", "step")[z].split("\n")
            for step in step_list:
                # print(step)
                if step == "reset":
                    f.write(
                        '	TEST_NUM++;\n	TEST_NO(TEST_NUM); DATALOG_MSG="' + "reset_pattern" + '";\n	JUDGE_PAT(' + "reset_pattern" + ',__' + "reset_pattern" + '); \n\n')
                elif "power" in step:
                    f.write("	POWER_Shmoo_ON(" + step.split(" ")[1] + ");\n\n")
                elif step == "turn on/off":
                    f.write("	POWER_OFF();\n" + "	POWER_ON(_C_" + G.col("FLOW", "Vcc")[z].upper() + ");\n\n")
                    if "Hz" not in G.col("FLOW", "UNIT")[z] and "VCC" not in G.col("FLOW", "meas pin")[z] and \
                            G.col("FLOW", "UNIT")[z] != "pat":
                        f.write("	RELAY_ON(" + G.col("FLOW", "meas pin")[z] + ", PPMU_PDCL, 2mS);\n\n")
                elif "forcepin" in step:
                    f.write("	RELAY_ON(" + step.split(" ")[1] + ", PPMU_PDCL, 2mS);\n\n")
                    relay_off += step.split(" ")[1]
                    for value in range(len(list(step.split(" ")[1].split("+")))):
                        relay_pin.append(list(step.split(" ")[1].split("+"))[value])
                elif "forcevalue" in step:
                    for value in range(len(list(step.split(" ")[1].split("+")))):
                        f.write("	FORCE_V_PPMU(" + relay_pin[value] + "," + list(step.split(" ")[1].split("+"))[
                            value] + ", ,@2mA, , 2mS);\n")
                elif step == "trigger":
                    # 2026-07-15：force_1_0 已泛化为电平序列 pattern，默认触发脉冲=
                    # <pin>_hl_1ms。hex 触发无 <PIN>: 前缀=默认触发 → 显示名 Trig（2026-07-24），
                    # 种子按真实 GET PIN。
                    _gp = G.col("VERSION", "GET PIN")[G.i]
                    _hlreal = level_seq_pat_name(_gp, "HL", default_pulse()[1])
                    _hlname = level_seq_pat_name(trig_disp(_gp, True), "HL", default_pulse()[1])
                    copy_trig_sd(_hlreal, _hlname, G.OUT_DIR + "\\" + code_name[G.i])
                    f.write('	TEST_NUM++;\n	TEST_NO(TEST_NUM); DATALOG_MSG="' + _hlname
                            + '";\n	JUDGE_PAT(' + _hlname + ',__' + _hlname + '); \n\n')
                elif "send" in step:
                    _gp = G.col("VERSION", "GET PIN")[G.i]
                    _base = trig_disp(_gp, True) + "_send_num"
                    _n = int(step.split(" ")[1])
                    copy_trig_sd(_gp + "_send_num", _base, G.OUT_DIR + "\\" + code_name[G.i])
                    f.write('	TEST_NUM++;\n	TEST_NO(TEST_NUM); DATALOG_MSG="' + _base + ":s" + decimal_to_hex(_n)
                            + '";\n	JUDGE_PAT(' + _base + ":s" + decimal_to_hex(_n) + ',' + _base + ":s"
                            + decimal_to_hex(_n + 1) + '); \n\n')
                elif "wait" in step:
                    f.write('	WAIT(' + step.split(" ")[1] + "mS);\n")
                elif step.isspace() or not step:
                    continue
                else:
                    f.write(
                        '	TEST_NUM++;\n	TEST_NO(TEST_NUM); DATALOG_MSG="' + step + '";\n	JUDGE_PAT(' + step + ',__' + step + '); \n\n')

            return relay_off


def hex_trim_item_write(code_name, f, z, bisection):
    # //////////////////////////////////////////////trim 写入start/////////////////////////////////////////////
    relay_off = ""
    if code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[z]:
        if G.col("FLOW", "type")[z] == "trim" and G.col("FLOW", "mode")[z] == "hex":
            if bisection == "no":
                f.write(G.col("FLOW", "item")[z].split("Trim")[0].title() + "Dac_Loop()\n{\n")
                f.write("	TEST_NUM=" + str(
                    (G.j + 1) * 50) + ";\n" + '	TEST_NO(TEST_NUM);DATALOG_MSG="' + G.col("FLOW", "item")[z].split("Trim")[
                            0].lower() + 'dac_loop"; \n\n')
            else:
                f.write(G.col("FLOW", "item")[z].title() + "()\n{\n")
                f.write("	TEST_NUM=" + str(
                    (G.j + 1) * 50) + ";\n" + '	TEST_NO(TEST_NUM);DATALOG_MSG="' + G.col("FLOW", "item")[
                            z].lower() + '"; \n\n')

            f.write("	double trimTar=" + str(G.col("FLOW", "target")[z]) + ';\n\n')
            f.write(
                "	double trimValue[MAX_SITE],trimFinalValue[MAX_SITE];\n	int trimDac[MAX_SITE];\n\n")
            if bisection == "no":
                f.write("	int cyc=0;\n	int endCyc=" + str(
                    pow(2, G.col("FLOW", "DAC bit")[z])) + ";\n	char cycMsg[48];\n\n")
            elif G.col("FLOW", "LINE")[z] == "yes":
                f.write(
                    "	int dacArray[" + str(pow(2, G.col("FLOW", "DAC bit")[z]) - 1) + "]={0};\n")
                f.write("	for(I=0;I<" + str(
                    pow(2, G.col("FLOW", "DAC bit")[z]) - 1) + ";I++)\n	{\n	dacArray[I]=I;\n	}\n\n")
                f.write(
                    "	int dacIndex[MAX_SITE];\n	int firstIndex=sizeof(dacArray)/sizeof(dacArray[0])/2;\n	int binAryCyc=(int)log2((double)(sizeof(dacArray)/sizeof(dacArray[0])+1))-2;\n\n")
            else:
                f.write("	int dacArray[" + str(
                    pow(2, G.col("FLOW", "DAC bit")[z]) - 1) + "]={" + str(
                    G.col("FLOW", "step")[z]) + "};\n\n")
                f.write(
                    "	int dacIndex[MAX_SITE];\n	int firstIndex=sizeof(dacArray)/sizeof(dacArray[0])/2;\n	int binAryCyc=(int)log2((double)(sizeof(dacArray)/sizeof(dacArray[0])+1))-2;\n\n")
            f.write(
                "	//initial\n	for(I=0;I<MAX_SITE;I++)\n	{\n	trimValue[I]=0;\n	trimFinalValue[I]=0;\n")
            if bisection == "no":
                f.write("\n	trimDac[I]=0;\n\n	} \n\n")
            else:
                f.write(
                    "\n	trimDac[I]=dacArray[firstIndex];\n	dacIndex[I]=firstIndex;\n\n	} \n\n")
            f.write("	POWER_ON(_C_" + G.col("FLOW", "Vcc")[z].upper() + ");\n\n")
            for sub_cyc in range(len(G.col("FLOW", "sub"))):

                if G.col("FLOW", "item")[sub_cyc] == G.col("FLOW", "item")[z] and G.col("FLOW", "CP NO")[sub_cyc] == \
                        code_name[G.i].split("_")[-1]:
                    if "Hz" not in G.col("FLOW", "UNIT")[sub_cyc] and "VCC" not in G.col("FLOW", "meas pin")[
                        sub_cyc] and "turn on/off" not in G.col("FLOW", "step")[sub_cyc]:
                        f.write("	RELAY_ON(" + G.col("FLOW", "meas pin")[sub_cyc] + ", PPMU_PDCL, 2mS);\n\n")
                    relay_off = hex_pattern_write(code_name, f, sub_cyc)
                    if "Hz" in G.col("FLOW", "UNIT")[z]:
                        Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                    G.col("FLOW", "target")[z], 0, "FORCE", "FREQ", G.col("FLOW", "low_range(%)")[z],
                                    G.col("FLOW", "high_range(%)")[z], "","no",f)
                    else:
                        Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                    G.col("FLOW", "target")[z], 0, "FORCE", "PPMU", G.col("FLOW", "low_range(%)")[z],
                                    G.col("FLOW", "high_range(%)")[z], "","no",f)

                    f.write('	do\n	{\n')
                    if bisection == "no":
                        f.write('	sprintf(cycMsg,"' + str(
                            G.col("FLOW", "item")[z].lower().split("trim")[0]) + '_dac_%d",cyc);\n	cyc++; \n')

                    f.write('	set_send_data(trimDac);\n\n')
                    if "Hz" in G.col("FLOW", "UNIT")[z]:
                        Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                    G.col("FLOW", "target")[z], 2, "MEAS", "FREQ", G.col("FLOW", "low_range(%)")[z],
                                    G.col("FLOW", "high_range(%)")[z],"", "no",f)
                    elif int(G.col("FLOW", "target")[z]) < 0 and "V" in G.col("FLOW", "UNIT")[z]:
                        f.write("	PARAL_INC(" + G.col("FLOW", "meas pin")[
                            z] + ")\n	{\n		RELAY_OFF(PIN_DEFS,PDCL,2mS);\n		RELAY_ON(PIN_DEFS,PMU,2mS);\n\n")
                        f.write(
                            "		FORCE_I_PMU(PMU,0uA,@100uA,@12V,6V,ON,3mS);\n		MEAS_V_PMU(PMU,IFVM,2mS,16,AVE,50uS);\n"
                            "		FORCE_I_PMU(PMU,0uA,@100uA,@12V,6V,OFF,3mS);\n\n")
                        f.write("		RELAY_OFF(PIN_DEFS,PMU,2mS);\n		RELAY_ON(PIN_DEFS,PDCL,2mS);\n"
                                "	}\n\n")
                        f.write("	//MEAS_V_PPMU(" + G.col("FLOW", "meas pin")[z] + ", 2mS, 16, AVE, 50uS);\n\n")
                    else:
                        Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                    G.col("FLOW", "target")[z], 2, "MEAS", "PPMU", G.col("FLOW", "low_range(%)")[z],
                                    G.col("FLOW", "high_range(%)")[z], "","no",f)
                    f.write(
                        '	TEST_NUM++;\n	TEST_NO(TEST_NUM);DATALOG_MSG="' + G.col("FLOW", "item")[z].lower() + '";\n')
                    f.write('	SOCKET_INC(FRZ_OFF)\n	{\n')

                    if "A" in G.col("FLOW", "UNIT")[z]:
                        f.write(
                            "		trimValue[T_SOCKET] = RESULT_PIN(T_SOCKET, " + G.col("FLOW", "meas pin")[
                                z] + ")*1000000; //uA\n")
                    elif "Hz" in G.col("FLOW", "UNIT")[z]:
                        f.write(
                            "		trimValue[T_SOCKET] = RESULT_PIN(T_SOCKET, " + G.col("FLOW", "meas pin")[
                                z] + ")/1000; //Khz\n")
                    else:
                        f.write(
                            "		trimValue[T_SOCKET] = RESULT_PIN(T_SOCKET, " + G.col("FLOW", "meas pin")[
                                z] + ");\n")

                    if bisection == "no":
                        f.write('		JUDGE_VARIABLE(T_SOCKET,trimValue[T_SOCKET], ' + str(
                            round(G.col("FLOW", "target")[z] - (abs(G.col("FLOW", "target")[z] * 2)),
                                  2)) + ', ' + str(
                            round(G.col("FLOW", "target")[z] + (abs(G.col("FLOW", "target")[z] * 5)),
                                  2)) + ', cycMsg);\n\n')
                    else:
                        f.write('		JUDGE_VARIABLE(T_SOCKET,trimDac[T_SOCKET], ' + '0, ' + str(
                            pow(2, G.col("FLOW", "DAC bit")[z]) - 1) + ', "' + G.col("FLOW", "item")[z].split("Trim")[
                                    0] + 'dac");\n')
                        f.write('		JUDGE_VARIABLE(T_SOCKET,trimValue[T_SOCKET], ' + str(
                            round(G.col("FLOW", "target")[z] - (abs(G.col("FLOW", "target")[z] * 2)),
                                  2)) + ', ' + str(
                            round(G.col("FLOW", "target")[z] + (abs(G.col("FLOW", "target")[z] * 5)),
                                  2)) + ', "' + G.col("FLOW", "item")[z].split("Trim")[0] + 'value");\n\n')
                    f.write(
                        '		if(fabs(trimValue[T_SOCKET]-trimTar)<fabs(trimFinalValue[T_SOCKET]-trimTar))\n		{\n		trimFinalValue[T_SOCKET] = trimValue[T_SOCKET];\n		' +
                        G.col("FLOW", "item")[z].split("Trim")[
                            0].upper() + 'DAC_FINAL[T_SOCKET] = trimDac[T_SOCKET];\n		}\n\n')
                    if bisection == "yes":
                        f.write(
                            "		if (trimValue[T_SOCKET] < trimTar)\n		{\n		dacIndex[T_SOCKET] = dacIndex[T_SOCKET] + (int)pow((float)2, (float)binAryCyc);\n		trimDac[T_SOCKET] = dacArray[dacIndex[T_SOCKET]];\n		}\n\n")
                        f.write(
                            "		else\n		{\n		dacIndex[T_SOCKET] = dacIndex[T_SOCKET] - (int)pow((float)2, (float)binAryCyc);\n		trimDac[T_SOCKET] = dacArray[dacIndex[T_SOCKET]];\n		}\n\n")
                    else:

                        f.write("		trimDac[T_SOCKET] = cyc;\n")

                    f.write('	}\n\n')  # socket_inc{}
                    if bisection == "yes":
                        f.write('	binAryCyc-=1;\n\n')
                    if bisection == "yes":
                        f.write('	}while(binAryCyc>=-1);  \n')  # do while{}
                    else:
                        f.write('	}while(cyc<endCyc);   \n')  # do while{}
                    f.write('	//fflush(stdout);\n\n')
                    f.write("	set_send_data(" +
                        str(G.col("FLOW", "item")[z].lower().split("trim")[0]).upper() + "DAC_FINAL);\n\n")

                    f.write(
                        '	TEST_NUM++;\n	TEST_NO(TEST_NUM); DATALOG_MSG="' + G.col("FLOW", "item")[z].lower() + '";\n\n')
                    f.write('	SOCKET_INC(FRZ_OFF)\n	{\n	JUDGE_VARIABLE(T_SOCKET,' +
                            G.col("FLOW", "item")[z].split("Trim")[0].upper() + 'DAC_FINAL[T_SOCKET],0, ' + str(
                        pow(2, G.col("FLOW", "DAC bit")[z]) - 1) + ', "' + G.col("FLOW", "item")[z].split("Trim")[
                                0] + 'dac_f");\n	}\n\n')

                    if G.col("FLOW", "UID")[z] == "yes":

                        if "Hz" in G.col("FLOW", "UNIT")[z]:
                            Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                        G.col("FLOW", "target")[z], 2, "MEAS", "FREQ", G.col("FLOW", "low_range(%)")[z],
                                        G.col("FLOW", "high_range(%)")[z],"", "no",f)
                        else:
                            Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                        G.col("FLOW", "target")[z], 2, "MEAS", "PPMU", G.col("FLOW", "low_range(%)")[z],
                                        G.col("FLOW", "high_range(%)")[z],"", "no",f)
                        f.write('	SOCKET_INC(FRZ_OFF)\n	{\n	' + G.col("FLOW", "item")[z].split("Trim")[
                            0].lower() + 'value_Final[T_SOCKET] = RESULT_PIN(T_SOCKET, TP);\n	}\n')
                        f.write('	JUDGE_VARIABLE_MS (' + G.col("FLOW", "item")[z].split("Trim")[
                            0].lower() + 'value_Final,' + str(round(calc_limit(G.col("FLOW", "target")[z], G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z], True), 2)) +
                                G.col("FLOW", "UNIT")[z] + ', ' + str(round(calc_limit(G.col("FLOW", "target")[z], G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z], False), 2)) +
                                G.col("FLOW", "UNIT")[z] + ',"' + G.col("FLOW", "item")[z].split("Trim")[
                                    0].lower() + 'value_f" );\n')
                    else:
                        f.write('	DATALOG_MSG="' + G.col("FLOW", "item")[z].split("Trim")[0] + 'value_f";\n')

                        if G.col("FLOW", "item")[z].split("_")[0].lower() in list(G.VERSION.columns):
                            if G.col("FLOW", "target")[z] < -2 and "V" in G.col("FLOW", "UNIT")[z]:
                                f.write(
                                    "	SOCKET_INC(FRZ_OFF)\n	{\n	trimValue[T_SOCKET] = RESULT_PIN(T_SOCKET, " +
                                    G.col("FLOW", "meas pin")[z] + ");\n" +
                                    '	JUDGE_VARIABLE(T_SOCKET,trimValue[T_SOCKET], ' + G.col("FLOW", "item")[z].split("_")[
                                        0].upper() + '_TAR-0.05,' + G.col("FLOW", "item")[z].split("_")[
                                        0].upper() + '_TAR+0.05,"' +
                                    G.col("FLOW", "item")[z].split("Trim")[0] + 'value_f");\n	}\n\n')
                            else:
                                f.write("	JUDGE_V_PPMU(" + G.col("FLOW", "meas pin")[z] + "," +
                                        G.col("FLOW", "item")[z].split("_")[0].upper() + '_TAR-0.05,' +
                                        G.col("FLOW", "item")[z].split("_")[0].upper() + '_TAR+0.05' + ',2mS);\n\n')
                        else:

                            if "Hz" in G.col("FLOW", "UNIT")[z]:
                                Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                            G.col("FLOW", "target")[z], 0, "JUDGE", "FREQ", G.col("FLOW", "low_range(%)")[z],
                                            G.col("FLOW", "high_range(%)")[z],"", "no",f)
                            else:
                                Force_Judge(G.col("FLOW", "UNIT")[z], G.col("FLOW", "meas pin")[z], G.col("FLOW", "FV/FI")[z],
                                            G.col("FLOW", "target")[z], 0, "JUDGE", "PPMU", G.col("FLOW", "low_range(%)")[z],
                                            G.col("FLOW", "high_range(%)")[z],"", "no",f)


                    if "Hz" in G.col("FLOW", "UNIT")[z]:
                        f.write("	SET_TFTM_MODE(" + G.col("FLOW", "meas pin")[z] + ", SCHMITT_OFF);\n\n")
                    else:
                        Force_Judge("uA", G.col("FLOW", "meas pin")[z], "0V", G.col("FLOW", "target")[z], 0, "FORCE", "PPMU",
                                    G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z],"", "no",f)
                        Force_Judge("V", G.col("FLOW", "meas pin")[z], "0uA", G.col("FLOW", "target")[z], 0, "FORCE", "PPMU",
                                    G.col("FLOW", "low_range(%)")[z], G.col("FLOW", "high_range(%)")[z],"", "no",f)
                    if "Hz" not in G.col("FLOW", "UNIT")[z]:
                        f.write("	RELAY_OFF(" + G.col("FLOW", "meas pin")[z] + ", PPMU_PDCL, 2mS);\n")

                    f.write('	POWER_OFF();\n	//POWER_DOWN_FAIL_SITE_X(MODE_B);\n\n')
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

            f.write("	TEST_NUM=" + str(
                (z + 1) * 50) + ";\n" + '	TEST_NO( TEST_NUM);DATALOG_MSG="' + G.col("FLOW", "item")[
                        z].lower() + '"; \n\n')
            if G.col("FLOW", "UID")[z] == "yes":
                f.write("	double verifyValue[MAX_SITE] = {0.0};\n\n")
            f.write("	POWER_ON(_C_" + G.col("FLOW", "Vcc")[z].upper() + ");\n\n")
            for sub_cyc in range(len(G.col("FLOW", "sub"))):
                temp_values.clear()
                temp_keys.clear()
                if G.col("FLOW", "item")[sub_cyc] == G.col("FLOW", "item")[z] and G.col("FLOW", "CP NO")[sub_cyc] == \
                        code_name[G.i].split("_")[-1]:
                    f.write("////////////////////" + G.col("FLOW", "sub")[sub_cyc].lower() + "/////////////////\n")
                    if "Hz" not in G.col("FLOW", "UNIT")[sub_cyc] and "VCC" not in G.col("FLOW", "meas pin")[
                        sub_cyc] and "turn on/off" not in G.col("FLOW", "step")[sub_cyc]:
                        f.write("	RELAY_ON(" + G.col("FLOW", "meas pin")[sub_cyc] + ", PPMU_PDCL, 2mS);\n\n")

                    relay_off = hex_pattern_write(code_name, f, sub_cyc)

                    if G.col("FLOW", "UNIT")[sub_cyc].lower() != "pat":
                        if "Hz" in G.col("FLOW", "UNIT")[sub_cyc]:
                            Force_Judge(G.col("FLOW", "UNIT")[sub_cyc], G.col("FLOW", "meas pin")[sub_cyc],
                                        G.col("FLOW", "FV/FI")[sub_cyc],
                                        G.col("FLOW", "target")[sub_cyc], 0, "FORCE", "FREQ",
                                        G.col("FLOW", "low_range(%)")[sub_cyc], G.col("FLOW", "high_range(%)")[sub_cyc],"", "no",f)
                        elif "VCC" in G.col("FLOW", "meas pin")[sub_cyc]:
                            Force_Judge(G.col("FLOW", "UNIT")[sub_cyc], G.col("FLOW", "meas pin")[sub_cyc],
                                        G.col("FLOW", "FV/FI")[sub_cyc],
                                        G.col("FLOW", "target")[sub_cyc], 0, "FORCE", "MLDPS",
                                        G.col("FLOW", "low_range(%)")[sub_cyc], G.col("FLOW", "high_range(%)")[sub_cyc],"", "no",f)
                        else:
                            Force_Judge(G.col("FLOW", "UNIT")[sub_cyc], G.col("FLOW", "meas pin")[sub_cyc],
                                        G.col("FLOW", "FV/FI")[sub_cyc],
                                        G.col("FLOW", "target")[sub_cyc], 0, "FORCE", "PPMU",
                                        G.col("FLOW", "low_range(%)")[sub_cyc], G.col("FLOW", "high_range(%)")[sub_cyc],"", "no",f)
                    else:
                        if G.col("FLOW", "FV/FI")[sub_cyc] == "/":
                            f.write("")
                        else:
                            f.write("	RELAY_ON(" + G.col("FLOW", "meas pin")[sub_cyc] + ", PPMU_PDCL, 2mS);\n\n")
                            Force_Judge("V", G.col("FLOW", "meas pin")[sub_cyc], G.col("FLOW", "FV/FI")[sub_cyc], 0, 0,
                                        "FORCE", "PPMU", 1, 1,"", "no",f)

                    f.write('	DATALOG_MSG="' + G.col("FLOW", "sub")[sub_cyc].lower() + '";\n')
                    if G.col("FLOW", "UID")[sub_cyc] == "yes":
                        if "Hz" in G.col("FLOW", "UNIT")[sub_cyc]:
                            Force_Judge(G.col("FLOW", "UNIT")[sub_cyc], G.col("FLOW", "meas pin")[sub_cyc],
                                        G.col("FLOW", "FV/FI")[sub_cyc],
                                        G.col("FLOW", "target")[sub_cyc], 0, "MEAS", "FREQ",
                                        G.col("FLOW", "low_range(%)")[sub_cyc], G.col("FLOW", "high_range(%)")[sub_cyc],"", "no",f)
                        elif "VCC" in G.col("FLOW", "meas pin")[sub_cyc]:
                            Force_Judge(G.col("FLOW", "UNIT")[sub_cyc], G.col("FLOW", "meas pin")[sub_cyc],
                                        G.col("FLOW", "FV/FI")[sub_cyc],
                                        G.col("FLOW", "target")[sub_cyc], 0, "MEAS", "MLDPS",
                                        G.col("FLOW", "low_range(%)")[sub_cyc], G.col("FLOW", "high_range(%)")[sub_cyc],"", "no",f)
                        else:
                            Force_Judge(G.col("FLOW", "UNIT")[sub_cyc], G.col("FLOW", "meas pin")[sub_cyc],
                                        G.col("FLOW", "FV/FI")[z],
                                        G.col("FLOW", "target")[sub_cyc], 0, "MEAS", "PPMU",
                                        G.col("FLOW", "low_range(%)")[sub_cyc], G.col("FLOW", "high_range(%)")[sub_cyc],"", "no",f)
                        f.write('	SOCKET_INC(FRZ_OFF)\n	{\n	' + 'verifyValue[T_SOCKET] = RESULT_PIN(T_SOCKET, ' +
                                G.col("FLOW", "meas pin")[sub_cyc] + ');\n')
                        f.write("	JUDGE_VARIABLE ( T_SOCKET, verifyValue[T_SOCKET] ," + str(round(
                            calc_limit(G.col("FLOW", "target")[sub_cyc], G.col("FLOW", "low_range(%)")[sub_cyc], G.col("FLOW", "high_range(%)")[sub_cyc], True),
                            3)) + G.col("FLOW", "UNIT")[sub_cyc] + ', ' + str(round(
                            calc_limit(G.col("FLOW", "target")[sub_cyc], G.col("FLOW", "low_range(%)")[sub_cyc], G.col("FLOW", "high_range(%)")[sub_cyc], False),
                            3)) + G.col("FLOW", "UNIT")[sub_cyc] + ', "' + G.col("FLOW", "item")[sub_cyc].split("Verify")[
                                    0] + 'value_f");\n\n')

                        f.write("	" + G.col("FLOW", "item")[sub_cyc].split("Verify")[
                            0].upper() + "W[T_SOCKET]=(int)(verifyValue[T_SOCKET]*1000+0.5);\n")
                        f.write(
                            "	" + G.col("FLOW", "item")[sub_cyc].split("Verify")[0].upper() + "W[T_SOCKET]=((" +
                            G.col("FLOW", "item")[sub_cyc].split("Verify")[0].upper() + "W[T_SOCKET]/1000)%10)*4096+((" +
                            G.col("FLOW", "item")[sub_cyc].split("Verify")[0].upper() + "W[T_SOCKET]/100)%10)*256+((" +
                            G.col("FLOW", "item")[sub_cyc].split("Verify")[0].upper() + "W[T_SOCKET]/10)%10)*16+(" +
                            G.col("FLOW", "item")[sub_cyc].split("Verify")[0].upper() + "W[T_SOCKET]%10);\n")
                        f.write("	}\n\n")

                    else:
                        if G.col("FLOW", "UNIT")[sub_cyc].lower() != "pat":
                            if "Hz" in G.col("FLOW", "UNIT")[sub_cyc]:
                                Force_Judge(G.col("FLOW", "UNIT")[sub_cyc], G.col("FLOW", "meas pin")[sub_cyc],
                                            G.col("FLOW", "FV/FI")[sub_cyc],
                                            G.col("FLOW", "target")[sub_cyc], 0, "JUDGE", "FREQ",
                                            G.col("FLOW", "low_range(%)")[sub_cyc], G.col("FLOW", "high_range(%)")[sub_cyc],"", "no",f)
                            elif "VCC" in G.col("FLOW", "meas pin")[sub_cyc]:
                                Force_Judge(G.col("FLOW", "UNIT")[sub_cyc], G.col("FLOW", "meas pin")[sub_cyc],
                                            G.col("FLOW", "FV/FI")[sub_cyc],
                                            G.col("FLOW", "target")[sub_cyc], 0, "JUDGE", "MLDPS",
                                            G.col("FLOW", "low_range(%)")[sub_cyc], G.col("FLOW", "high_range(%)")[sub_cyc],"", "no",f)
                            else:
                                Force_Judge(G.col("FLOW", "UNIT")[sub_cyc], G.col("FLOW", "meas pin")[sub_cyc],
                                            G.col("FLOW", "FV/FI")[sub_cyc],
                                            G.col("FLOW", "target")[sub_cyc], 0, "JUDGE", "PPMU",
                                            G.col("FLOW", "low_range(%)")[sub_cyc], G.col("FLOW", "high_range(%)")[sub_cyc],"", "no",f)
                        else:
                            if G.col("FLOW", "FV/FI")[sub_cyc] == "/":
                                f.write('\n	TEST_NUM++;\n	TEST_NO(TEST_NUM);\n	JUDGE_PAT(' + G.col("FLOW", "meas pin")[
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
                                                    "JUDGE", "PPMU", 10, 6,"", "no",f)
                                    elif measvalue == "L":
                                        Force_Judge("V", result_dict[measvalue], G.col("FLOW", "FV/FI")[sub_cyc], 0.5, 0,
                                                    "JUDGE", "PPMU", 100, 2,"", "no",f)

                    if G.col("FLOW", "UNIT")[sub_cyc].lower() == "pat" and G.col("FLOW", "FV/FI")[sub_cyc] != "/":
                        f.write("	RELAY_OFF(" + G.col("FLOW", "meas pin")[sub_cyc] + ", PPMU_PDCL, 2mS);\n")

                    if G.col("FLOW", "UNIT")[sub_cyc].lower() != "pat":
                        if "Hz" in G.col("FLOW", "UNIT")[sub_cyc]:
                            f.write("	SET_TFTM_MODE(" + G.col("FLOW", "meas pin")[sub_cyc] + ", SCHMITT_OFF);\n\n")
                        elif "VCC" in G.col("FLOW", "meas pin")[sub_cyc]:
                            continue
                        else:
                            Force_Judge("uA", G.col("FLOW", "meas pin")[sub_cyc], "0V", G.col("FLOW", "target")[sub_cyc], 0,
                                        "FORCE", "PPMU", G.col("FLOW", "low_range(%)")[sub_cyc],
                                        G.col("FLOW", "high_range(%)")[sub_cyc],"", "no", f)
                            Force_Judge("V", G.col("FLOW", "meas pin")[sub_cyc], "0uA", G.col("FLOW", "target")[sub_cyc], 0,
                                        "FORCE", "PPMU", G.col("FLOW", "low_range(%)")[sub_cyc],
                                        G.col("FLOW", "high_range(%)")[sub_cyc],"", "no", f)
                        if "Hz" not in G.col("FLOW", "UNIT")[sub_cyc] and "VCC" not in G.col("FLOW", "meas pin")[sub_cyc]:
                            f.write("	RELAY_OFF(" + G.col("FLOW", "meas pin")[sub_cyc] + ", PPMU_PDCL, 2mS);\n")
                    else:
                        f.write(relay_off + ", PPMU_PDCL, 2mS);\n\n")

            f.write('	POWER_OFF();\n	//POWER_DOWN_FAIL_SITE_X(MODE_B);\n\n')
            f.write("}\n\n")  # item{}


def trim_data_read_write(
    code_name, f, j, read_bit, recipe_row=None, persistence_row=None,
    trim_data_plan=None,
):
    trim_data_plan = trim_data_plan or G.compiled_adapter.trim_data_plan
    recipe_modules = None if recipe_row is None else {
        operation.name for operation in recipe_row.operations
    }
    def uses(module):
        return recipe_modules is None or module in recipe_modules

    use_buildmap = uses("BUILDMAP")
    use_readotpmap = uses("READOTPMAP")
    use_loadmap = uses("LOADMAP")
    use_set_vposp = recipe_modules is None or "SETVPOSP" in recipe_modules
    use_nmloop = uses("NMLOOP")
    use_checkotp = uses("CHECKOTP")
    use_commit = uses("COMMIT")
    use_pgmotp = uses("PGMOTP")
    effective_read_pages = None
    if persistence_row is not None:
        effective_read_pages = {
            page.casefold()
            for operation in persistence_row.operations
            if operation.module == "READOTPMAP"
            for page in operation.effective_pages
        }
    pgm_pages = None
    if recipe_modules is not None and G.col("FLOW", "type")[j] == "data":
        cp_trim_bindings = trim_data_plan.for_cp(code_name[G.i].split("_")[-1])
        pgm_pages = {
            G.col("ADDR_MAP", "Word No.")[row]
            for row, expression in enumerate(G.col("ADDR_MAP", "CP addr map"))
            if isinstance(expression, str) and any(
                binding.matches_addr_map(token)
                for token in expression.split(",")
                for binding in cp_trim_bindings
            )
        }
    addr_map_item = []
    temp_retrim_list = []
    page_word = G.col("VERSION", "page word")[0]
    if G.col("FLOW", "type")[j] != "trim" and G.col("FLOW", "type")[j] != "verify" and G.col("FLOW", "type")[
        j] != "os" and G.col("FLOW", "type")[j] != "id" and code_name[G.i].split("_")[-1] == \
            G.col("FLOW", "CP NO")[j]:
        f.write("@@PLAN " + G.col("FLOW", "item")[j].title() + "\n")
        f.write(
            "	SITE_SEQUENCE      = OFF;\n" + '	DISABLE_BY_MARK_NO = NULL;\n' + "	S_SETUP_FILE       = c:\\set.dat;\n" +
            "	REMARK             = " + G.col("FLOW", "item")[j].title() + '; \n\n')
        # trim write & read
        if G.col("FLOW", "type")[j] == "read" or G.col("FLOW", "type")[j] == "data" or G.col("FLOW", "type")[
            j] == "write" and code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[j]:

            if G.col("FLOW", "type")[j] == "read":
                f.write("	CALL_MACRO POWER_ON(_C_" + G.col("FLOW", "Vcc")[j].upper() + ");\n\n")
                f.write(
                    '	RUN_PATTERN(enter_fbist_mode:START,enter_fbist_mode:END,1,TS_5MHZ);\n\n')
                for z in range(len(G.col("ADDR_MAP", "Word No."))):
                    if G.col("ADDR_MAP", "Word No.")[z] not in addr_map_item:
                        addr_map_item.append(G.col("ADDR_MAP", "Word No.")[z])
                # f.write("	SOCKET_INC(FRZ_OFF)\n	{\n\n")
                for cyc in range(len(addr_map_item)):
                    numbers = ''.join(filter(str.isdigit, G.col("ADDR_MAP", "line")[0 + page_word*cyc]))
                    if use_readotpmap and (effective_read_pages is None or addr_map_item[cyc].casefold() in effective_read_pages) and code_name[G.i].split("_")[-1][-1] in G.col("ADDR_MAP", "line")[0 + page_word*cyc] and "lable" in list(
                            G.ADDR_MAP["data type"])[0 + page_word*cyc:(page_word)  + page_word*cyc] and addr_map_item[cyc] != "uid":
                        if int(code_name[G.i].split("_")[-1][-1]) > int(min(numbers)):
                            result = epr_pattern_capture("capture", addr_map_item[cyc])
                            copy_file(G.BASE_DIR + "\\pat_temp\\" + result["read"] + ".sd",
                                      G.OUT_DIR + "\\" + code_name[G.i] )
                            # 逐字段判断真实字节宽度(2或4字节)+按 read_bit 分组反序，修复
                            # 原先整页统一按32bit算的隐患（本项目 trim0/trim1/factory3 目前
                            # 恰好清一色反码字段、算出来数值没变，但代码本身跟 uid 页
                            # 是同一个 bug，见 _page_field_layout）。
                            layout = _page_field_layout(addr_map_item[cyc], read_bit)
                            total_bytes = sum(width for _, width, _so in layout)

                            f.write("	//******************" + addr_map_item[cyc] + " capture***********************\n\n")

                            f.write('	LOGIC_SET_AC_DATALOG(' + result["read"] + ':START,' + result[
                                        "read"] + ':END,LOG_ENABLE_ALL,AC_IGNORE_FAIL); \n')
                            f.write('	RUN_PATTERN(' + result["read"] + ':START,' + result[
                                        "read"] + ':END,1,TS_5MHZ); \n\n')
                            f.write("	LOGIC_CLEAR_SET_AC_FLAG( );\n\n")
                            f.write("	LOGIC_READ_LOG(LOG_ARRAY, " + str(
                                G.col("VERSION", "SWD PIN")[G.i]) + ",  " + str(
                                total_bytes * 8) + ", 1,BIN,TRIG_PINNAME=TRIGPIN);//" + str(
                                total_bytes) + "byte\n")
                            # YT5100 limits DAQ SHOWX (the second argument) to 100.  The
                            # LOGIC_READ_LOG bit count remains total_bytes * 8, so this only
                            # bounds the display axis; it must not truncate the capture layout.
                            f.write('	DAQ_ARRAY_TRANSFER(LOG_ARRAY,' + str(
                                min(total_bytes, 100)) + ', 1, 8, "1", "8,7,6,5,4,3,2,1", UP_LIMIT=255, DOWN_LIMIT=0,HEX);//'
                                    + str(total_bytes) + "byte\n\n")
                            f.write(
                                "	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n	{\n			if(Sys_ActiveSite[T_SOCKET]==0)continue;\n\n")

                            off = 0
                            for type_flag, width, sub_off in layout:
                                f.write(type_flag + "Sys_SW_BUFFER_DATA[T_SOCKET][" + str(off + sub_off) + "]*256+" +
                                        "Sys_SW_BUFFER_DATA[T_SOCKET][" + str(off + sub_off + 1) + "];\n")
                                off += width

                            f.write("	}\n\n")  # socket
                            # f.write("	fflush(stdout);\n\n")

                G.set_vposp_name.clear()
                for binding in trim_data_plan.bindings:
                    if binding.pump:
                        G.set_vposp_name.append(
                            binding.reference("T_SOCKET") + str(binding.dac_bits))
                flow_trim_items = [str(G.col("FLOW", "item")[j].split("Trim")[0]).upper().rstrip("_") for j in range(len(G.col("FLOW", "item")))]
                if "VCSL" not in flow_trim_items:
                    G.set_vposp_name.append("VCSL_DAC_FINAL[T_SOCKET]3")
                if "VNEG2" not in flow_trim_items:
                    G.set_vposp_name.append("VNEG2_DAC_FINAL[T_SOCKET]3")
                if "VBL" not in flow_trim_items:
                    G.set_vposp_name.append("VBL_DAC_FINAL[T_SOCKET]4")
                temp_list = []
                bit_list = []
                f.write("	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n	{\n\n")
                f.write("		//You need to check it by yourself\n")
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
                                    # print(bin_list_to_hex(bit_list))
                                    # 同上：rstrip 切掉变量名末尾全部位宽数字，不只切 1 个字符。
                                    f.write("		" + G.set_vposp_name[z].rstrip("0123456789").upper() + "=(REG_" +
                                            G.col("ADDR_MAP", "bit[15:0]")[item_cyc].split("[")[
                                                0].upper() + "[T_SOCKET]&" + bin_list_to_hex(bit_list) + ")>>" + str(
                                        shift) + ";\n")

                f.write("	}\n\n")

                if use_set_vposp:
                    set_all_final_vposp(f)
                    copy_file(G.BASE_DIR + "\\pat_temp\\" + "set_all_final_vposp" + ".sd",
                              G.OUT_DIR + "\\" + code_name[G.i] )

                # 跨 CP 复用 dac 补值（见 reuse_dac_restore_items）：本 CP 有 trim 项在
                # pattern sheet 标了 reuse dac，但被依赖项本身没在本 CP 里重新 trim 过
                # （如 CP3 的 Hsi_8/16/24/48M_Trim 依赖 CP1 已经 trim 好的 Hsi_Vrega，CP3
                # 没有 Hsi_Vrega_Trim 这一步）——该被依赖项对应 pattern（如 set_hsi_vrega_dac）
                # 内存里就没有 live 收敛值，trim_item_write 里现成的 reuse dac 逻辑会直接
                # 套用编译期写死的占位值。这里从刚读回的 EPR 值算出最终 dac、重新灌回该
                # pattern 一次，之后同 CP 内每个 reuse 该项的 trim 只需再跑一遍 pattern 即可
                # 拿到正确值（不用改 trim_item_write）。同 chroma/writers.py:
                # trim_data_read_write 同一块逻辑移植（2026-07-06）——S100 没有 JUDGE_PAT
                # 合一指令，改用 LOGIC_WRITE_PATTERN_MEMORY(BIT_COUNT=...) 一次性写入
                # （同 sub_flow_write 的 trim_data 宏内部写法）+ 裸 RUN_PATTERN 落地（失败靠
                # 本 @@PLAN 收尾的 CONDITION IF_FAIL 统一捕获，同本文件既有约定）。
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
                    var_name = dac_final_symbol(ref_item) + "[T_SOCKET]"
                    copy_file(G.BASE_DIR + "\\pat_temp\\" + reuse_pat_name + ".sd",
                              G.OUT_DIR + "\\" + code_name[G.i])
                    f.write("	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n	{\n")
                    f.write("		" + var_name + "=" + expr + ";\n")
                    f.write("		GB[0+T_SOCKET*64]=" + var_name +
                            "; //restore " + ref_item + " dac(not retrimmed in this CP)\n")
                    f.write("	}\n\n")
                    f.write("	LOGIC_WRITE_PATTERN_MEMORY(" + reuse_pat_name + ":a_data_st," +
                            reuse_pat_name + ":a_data_sp," + str(G.col("VERSION", "SWD PIN")[G.i]) +
                            ",GB1, BIT_COUNT=" + str(dac_bit) + ", SERIAL,MSB_LSB);\n\n")
                    f.write("	RUN_PATTERN(" + reuse_pat_name + ":START," + reuse_pat_name + ":END,1,TS_5MHZ);\n\n")

        addr_map_item = []
        pn_flag = ""
        for z in range(len(G.col("ADDR_MAP", "Word No."))):
            if G.col("ADDR_MAP", "Word No.")[z] not in addr_map_item:
                addr_map_item.append(G.col("ADDR_MAP", "Word No.")[z])
        if G.col("FLOW", "type")[j] == "read" or G.col("FLOW", "type")[j] == "data":
            for cyc in range(len(addr_map_item)):
                if use_loadmap and code_name[G.i].split("_")[-1][-1] in G.col("ADDR_MAP", "line")[0 + page_word * cyc] and "lable" in list(
                        G.ADDR_MAP["data type"])[0 + page_word * cyc:(page_word-1) + page_word * cyc]:
                    numbers = ''.join(filter(str.isdigit, G.col("ADDR_MAP", "line")[0 + page_word * cyc]))
                    if int(code_name[G.i].split("_")[-1][-1]) >= int(min(numbers)) and addr_map_item[cyc] != "uid":
                        f.write("	//******************" + addr_map_item[cyc] + " pattern**************************\n\n")
                        result = epr_pattern_capture("normal", addr_map_item[cyc])
                        copy_file(G.BASE_DIR + "\\pat_temp\\" + result["read"] + ".sd",
                                  G.OUT_DIR + "\\" + code_name[G.i] )
                        for u in range(0 + page_word*cyc, page_word-1 + page_word*cyc):
                            if G.col("ADDR_MAP", "data type")[u] == "lable":
                                if "反码" in G.col("ADDR_MAP", "bit[31:16]")[u]:
                                    pn_flag = "yes"
                                else:
                                    pn_flag = "no"
                                write_pat_mem(f, result, 16, "-J", 0, G.col("ADDR_MAP", "bit[15:0]")[u].split("[")[0],
                                              "REG_" + G.col("ADDR_MAP", "bit[15:0]")[u].split("[")[0].upper(),
                                              G.col("ADDR_MAP", "bit[15:0]")[u].split("[")[0].lower() + "_", pn_flag,"arr")
            f.write("	\n\n")  # for socket
            if G.col("FLOW", "type")[j] == "read" and use_checkotp:
                f.write("	////////////////////////check///////////////////////////\n")
                f.write("	CALL_MACRO POWER_ON(_C_" + G.col("FLOW", "Vcc")[j].upper() + ");\n\n")
                f.write(
                    '	RUN_PATTERN(enter_fbist_mode:START,enter_fbist_mode:END,1,TS_5MHZ);\n\n')
                for cyc in range(len(addr_map_item)):
                    if code_name[G.i].split("_")[-1][-1] in G.col("ADDR_MAP", "line")[0 + page_word*cyc] and addr_map_item[
                        cyc] != "uid":
                        result = epr_pattern_capture("normal", addr_map_item[cyc])
                        f.write(
                            '	RUN_PATTERN(' +
                            result["read"] + ':START,' + result["read"] + ':END,1,TS_5MHZ);  \n\n')

                f.write('	CALL_MACRO POWER_OFF();\n\n')
                _force_pass_write(f, j)
                f.write("	CONDITION\n		IF_FAIL \n		REJECT_BIN = " + str(
                    G.col("FLOW", "Hbin")[j]) + ";\n@@END_PLAN\n\n")
        if (G.col("FLOW", "type")[j] == "write" or G.col("FLOW", "type")[j] == "data") and (use_loadmap or use_commit):
            uid_result = None
            reg_list = []
            reg_temp = ""
            # 2026-07-07：去掉原有的 "!= CP1" 排除——用 program_V2.xlsx 的 ADDR_MAP 交叉核对
            # 确认 CP1 的 Hsi_8M_Trim 在 trim1 页也有 CLK_TRIM0 位段（跟 CP3 一样），参考程序
            # L_..._CP1.PRG 的 Trimdata_Write_Read（@7313）里也确实有这段 REG_CLK_TRIM0 写入
            # ——之前排除 CP1 会让这段、以及本次要新增的 uid 页早写都变成死代码，是遗留 bug。
            if "Rewrite" not in G.col("FLOW", "item")[j].title():
                temp_retrim_list.clear()
                for binding in trim_data_plan.for_cp(code_name[G.i].split("_")[-1]):
                    temp_retrim_list.append(
                        binding.reference("T_SOCKET") + str(binding.dac_bits))

                # print(temp_retrim_list, code_name[i].split("_")[-1])
                temp_list = []
                bit_list = []
                if len(temp_retrim_list) > 0:
                    f.write("	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n	{\n			if(Sys_ActiveSite[T_SOCKET]==0)continue;\n")
                    f.write("		//You need to check it by yourself\n")
                    uid_reg_list = []
                    # CP1 的 FLOW type=="data"（Trimdata_Write_Read），本函数上面那段
                    # "if type[j]=='read' or =='data':"（Section 2，@2555 附近）已经对
                    # 所有非 uid 页的每个 lable 字段通用地重新 write_pat_mem 过一遍——
                    # CP1 走这里的 reg_list（非 uid）分支会跟 Section 2 产出完全重复的
                    # LOGIC_WRITE_PATTERN_MEMORY（生成结果比对参考程序发现的，两份 PMU_TRIM0/
                    # CLK_TRIM0 等字段各写了一遍）。CP2/CP3 是 type=="write"，没有 Section 2，
                    # 必须靠这里补上，不能跳过。所以只有 CP1 的非 uid 匹配要跳过，uid 匹配
                    # （早写的核心目的）两边 CP 都要处理。
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
                                # temp_retrim_list[z] 形如 "Hsi_8M_DAC_FINAL[T_SOCKET]10"（末尾是
                                # FLOW DAC bit 位宽数字）；用 rstrip 去掉末尾全部数字（而非只切
                                # 1 个字符）——Hsi 系列位宽是两位数"10"，切 1 个字符会留下 1 个
                                # 杂散数字，拼出语法错误（同 Chroma 2026-07-06 修的一样，S100
                                # 这里是同款 bug，之前没触发是因为没有母本真正走到这条路径）。
                                f.write("		" + "REG_" + G.col("ADDR_MAP", "bit[15:0]")[item_cyc].split("[")[
                                    0].upper() + "[T_SOCKET]"
                                        + "=(REG_" + G.col("ADDR_MAP", "bit[15:0]")[item_cyc].split("[")[0].upper()
                                        + "[T_SOCKET]&" + invert_hex_string(bin_list_to_hex(bit_list),16) + ")|"
                                        + temp_retrim_list[z].rstrip("0123456789").upper() + "<<" + str(shift) + ";\n")

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
                    f.write("	}\n\n")
                    for z in reg_list:
                        result = epr_pattern_capture("normal", z.split("&&")[2])
                        write_pat_mem(f, result, 16, "-J", 0, z.split("&&")[0].split("[")[0],
                                      "REG_" + z.split("&&")[0].split("[")[0].upper(),
                                      z.split("&&")[0].split("[")[0].lower() + "_", z.split("&&")[1],"arr")

                    uid_result = None
                    if uid_reg_list:
                        uid_pat_name = "cp" + code_name[G.i].split("_")[-1][-1] + "_id"
                        uid_result = epr_pattern_capture("normal", uid_pat_name)
                        copy_file(G.BASE_DIR + "\\pat_temp\\" + uid_result["erase"] + ".sd",
                                  G.OUT_DIR + "\\" + code_name[G.i])
                        copy_file(G.BASE_DIR + "\\pat_temp\\" + uid_result["pgm"] + ".sd",
                                  G.OUT_DIR + "\\" + code_name[G.i])
                        copy_file(G.BASE_DIR + "\\pat_temp\\" + uid_result["read"] + ".sd",
                                  G.OUT_DIR + "\\" + code_name[G.i])
                        for z in uid_reg_list:
                            write_pat_mem(f, uid_result, 16, "-J", 0, z.split("&&")[0].split("[")[0],
                                          "REG_" + z.split("&&")[0].split("[")[0].upper(),
                                          z.split("&&")[0].split("[")[0].lower(), z.split("&&")[1], "arr")
                        # pass id flag：uid 页 word-offset5 现在是运行时 label（core/flash_seq.py
                        # Part B），早写阶段必须显式写一次占位值 0xFFFFFFFF——否则这个字段在
                        # 软件缓冲区里是未定义的，早写落地的 erase→prog→read 会把垃圾值烧进去。
                        # 真正的 pass 值留到 uid_write 晚写阶段再改写（同参考程序 Trimdata_Write_Read
                        # + Pgm_Cp1Id_Read 两段的关系）。
                        write_pat_mem(f, uid_result, 32, "-J", 0, "pass id flag", "0xFFFFFFFF",
                                      "cp12_id_", "no", "fixed")




            # if "Rewrite"	in list(FLOW["item"])[j].title() and code_name[i].split("_")[-1] != "CP1":
            #     for z in range(len(list(FLOW["type"]))):
            #         if list(FLOW["item"])[z] == "Verify" and list(FLOW["OTP"])[z] == "yes" and list(FLOW["CP NO"])[z] == code_name[i].split("_")[-1]:

            explicit_commit_pages = write_fixed_commit(
                recipe_row, f, cp=code_name[G.i].split("_")[-1]
            )
            if explicit_commit_pages:
                pgm_pages = set(explicit_commit_pages) if pgm_pages is None else (
                    set(pgm_pages) | set(explicit_commit_pages)
                )

            if recipe_modules is not None and use_set_vposp:
                set_all_final_vposp(f)
                copy_file(G.BASE_DIR + "\\pat_temp\\set_all_final_vposp.sd",
                          G.OUT_DIR + "\\" + code_name[G.i])

            if not use_pgmotp:
                _force_pass_write(f, j)
                f.write("\tCONDITION\n\t\tIF_FAIL \n\t\tREJECT_BIN = " + str(
                    G.col("FLOW", "Hbin")[j]) + ";\n@@END_PLAN\n\n")
                return

            f.write("	////////////////////////complete///////////////////////////\n")
            f.write("	CALL_MACRO POWER_ON(_C_" + G.col("FLOW", "Vcc")[j].upper() + ");\n\n")
            f.write(
                '	RUN_PATTERN(enter_fbist_mode:START,enter_fbist_mode:END,1,TS_5MHZ);\n\n')
            for cyc in range(len(addr_map_item)):
                if code_name[G.i].split("_")[-1][-1] in G.col("ADDR_MAP", "line")[0 + page_word*cyc] and addr_map_item[
                    cyc] != "uid" and (pgm_pages is None or addr_map_item[cyc] in pgm_pages):
                    result = epr_pattern_capture("normal", addr_map_item[cyc])
                    copy_file(G.BASE_DIR + "\\pat_temp\\" + result["erase"] + ".sd",
                              G.OUT_DIR + "\\" + code_name[G.i] )
                    f.write('	RUN_PATTERN(' +result["erase"] + ':START,' + result["erase"] + ':END,1,TS_5MHZ); \n\n')
                    copy_file(G.BASE_DIR + "\\pat_temp\\" + result["pgm"] + ".sd",
                              G.OUT_DIR + "\\" + code_name[G.i] )
                    f.write('	RUN_PATTERN(' +result["pgm"] + ':START,' + result["pgm"] + ':END,1,TS_5MHZ); \n\n')
                    copy_file(G.BASE_DIR + "\\pat_temp\\" + result["read"] + ".sd",
                              G.OUT_DIR + "\\" + code_name[G.i])
                    f.write('	RUN_PATTERN(' +result["read"] + ':START,' + result["read"] + ':END,1,TS_5MHZ); \n\n')

            # 早写的 uid 页（cp<N>_id）erase→prog→read 落地：紧跟在 FT/option0/option1/
            # trim0/trim1/factory23 这组"complete"收尾之后、同一次 POWER_ON/POWER_OFF
            # 周期内一起做（参考程序 Trimdata_Write_Read 尾段的真实顺序），不是单独一次
            # 电源周期——早写阶段只往软件缓冲区里写了 dac + pass-flag 占位值，只有真正
            # RUN_PATTERN 这三行才会把它物理烧进芯片。
            if uid_result is None and pgm_pages is not None and "uid" in pgm_pages:
                uid_result = epr_pattern_capture(
                    "normal", "cp" + code_name[G.i].split("_")[-1][-1] + "_id"
                )
                for pattern in ("erase", "pgm", "read"):
                    copy_file(G.BASE_DIR + "\\pat_temp\\" + uid_result[pattern] + ".sd",
                              G.OUT_DIR + "\\" + code_name[G.i])
            if uid_result is not None:
                f.write('	RUN_PATTERN(' + uid_result["erase"] + ':START,' + uid_result["erase"] + ':END,1,TS_5MHZ); \n\n')
                f.write('	RUN_PATTERN(' + uid_result["pgm"] + ':START,' + uid_result["pgm"] + ':END,1,TS_5MHZ); \n\n')
                f.write('	RUN_PATTERN(' + uid_result["read"] + ':START,' + uid_result["read"] + ':END,1,TS_5MHZ); \n\n')

            f.write('	CALL_MACRO POWER_OFF();\n\n')
            if uid_result is not None:
                write_uid_failed_site_reerase(
                    f, uid_result,
                    vcc=G.col("FLOW", "Vcc")[j],
                )
            _force_pass_write(f, j)
            f.write("	CONDITION\n		IF_FAIL \n		REJECT_BIN = " + str(
                G.col("FLOW", "Hbin")[j]) + ";\n@@END_PLAN\n\n")
        #
        #     # wakeup
        # wakeup
        if G.col("FLOW", "item")[j] == "Memory_Wakeup" and code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[j]:
            addr_map_item = []
            trimming_item = ["Vcsl_Trim", "Vneg2_Trim", "Vbl_Trim"] + [
                binding.addr_map_name
                for binding in trim_data_plan.for_cp(code_name[G.i].split("_")[-1])
            ]
            trimming_keys = {logical_item_key(item) for item in trimming_item}
            flow_trim_items = [
                binding.dac_final_symbol.removesuffix("_DAC_FINAL")
                for binding in trim_data_plan.bindings
            ]
            init_vars = []
            for var in ["VCSL", "VNEG2", "VBL"]:
                if var not in flow_trim_items:
                    init_vars.append(var + "_DAC_FINAL[T_SOCKET]=0;")
            if use_buildmap and init_vars:
                f.write(
                    "	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n	{\n			if(Sys_ActiveSite[T_SOCKET]==0)continue;\n		" + "\n		".join(init_vars) + "\n\n	")
            for z in range(len(G.col("ADDR_MAP", "Word No."))):
                if G.col("ADDR_MAP", "Word No.")[z] not in addr_map_item:
                    addr_map_item.append(G.col("ADDR_MAP", "Word No.")[z])
            for cyc in range(len(addr_map_item)):
                if use_buildmap and code_name[G.i].split("_")[-1][-1] in G.col("ADDR_MAP", "line")[0 + page_word*cyc] and "lable" in list(
                        G.ADDR_MAP["data type"])[0 + page_word*cyc:page_word-1 + page_word*cyc] :
                    f.write("		////////////////////////" + addr_map_item[cyc] + " page address map///////////////////////////\n\n")
                    for z in range(0 + page_word*cyc, page_word-1 + page_word*cyc):
                        if G.col("ADDR_MAP", "data type")[z] == "lable" and ("verify"	not in G.col("ADDR_MAP", "bit[15:0]")[z].lower() and "verify"	not in G.col("ADDR_MAP", "bit[31:16]")[z].lower()):
                            if type(G.col("ADDR_MAP", "description")[z]) == str:
                                f.write(
                                    "						//" + G.col("ADDR_MAP", "description")[
                                        z] + "\n						//Default = 0x" +
                                    (G.col("ADDR_MAP", "CP Data[31:0]")[z].split("h")[1]).split("_")[0]
                                    + (G.col("ADDR_MAP", "CP Data[31:0]")[z].split("h")[1]).split("_")[1] + "\n")
                            else:
                                f.write(
                                    "						//Default = 0x" +
                                    (G.col("ADDR_MAP", "CP Data[31:0]")[z].split("h")[1]).split("_")[0]
                                    + (G.col("ADDR_MAP", "CP Data[31:0]")[z].split("h")[1]).split("_")[1] + "\n")
                            f.write("		" + "REG_" + str(
                                G.col("ADDR_MAP", "bit[15:0]")[z].split("[")[0]).upper() + "[T_SOCKET]=")
                            desc = []
                            bit_temp = 0
                            try:
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
                                                dac_item = dac_final_symbol(desc[map_item]) + "[T_SOCKET]"
                                            else:
                                                temp_num = 0
                                                for cyc in range(range_num):
                                                    temp_num += int(
                                                        hex_to_bin_16bit(G.col("ADDR_MAP", "CP Data[31:0]")[z].split("_")[1])[
                                                            (bit_temp - 1) - cyc]) << cyc

                                                dac_item = str(temp_num)
                                        except:
                                            if logical_item_key(desc[map_item]) in trimming_keys:
                                                dac_item = dac_final_symbol(desc[map_item]) + "[T_SOCKET]"

                                        if map_item != len(desc) - 1:
                                            f.write("(" + dac_item + "<<" + str(
                                                16 - (bit_temp)) + ")" + "+")
                                        else:
                                            f.write("(" + dac_item + "<<" + str(
                                                16 - (bit_temp)) + ")" + ";")

                                    except:
                                        try:
                                            # 2026-07-06 修：原来判断"是不是常量前缀"靠 `"'" in desc[map_item]`
                                            # 精确匹配直引号，母本这类撇号被自动更正成弯引号（U+2018/2019）时判断
                                            # 直接落空、误当成普通字段（1 位宽），跟 leading_bit_width 要修的是
                                            # 同一类问题——改成看开头是不是数字，不依赖具体撇号字符。
                                            if desc[map_item][:1].isdigit():
                                                bit_temp += addr_map_field_width(desc[map_item])
                                                literal_value = addr_map_literal_value(desc[map_item])
                                                if literal_value is None:
                                                    literal_value = 0
                                                if map_item != len(desc) - 1:
                                                    f.write("(" + str(literal_value) + "<<" + str(16 - bit_temp) + ")+")
                                                else:
                                                    f.write("(" + str(literal_value) + "<<" + str(16 - bit_temp) + ");")
                                            else:
                                                item_name = desc[map_item]
                                                bit_temp += 1
                                                
                                                if logical_item_key(item_name) in trimming_keys:
                                                    dac_item = dac_final_symbol(item_name) + "[T_SOCKET]"
                                                else:
                                                    bit_index = bit_temp - 1
                                                    bit_value = int(hex_to_bin_16bit(G.col("ADDR_MAP", "CP Data[31:0]")[z].split("_")[1])[bit_index])
                                                    dac_item = str(bit_value)
                                                
                                                if map_item != len(desc) - 1:
                                                    f.write("(" + dac_item + "<<" + str(16 - bit_temp) + ")+")
                                                else:
                                                    f.write(dac_item + ";")
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
                            except:
                                f.write("0x" +
                                    (G.col("ADDR_MAP", "CP Data[31:0]")[z].split("h")[1]).split("_")[0]
                                    + (G.col("ADDR_MAP", "CP Data[31:0]")[z].split("h")[1]).split("_")[1] + ";")
                            f.write("\n\n")

            f.write("	}\n\n\n")


            if use_set_vposp:
                set_all_final_vposp(f)
                copy_file(G.BASE_DIR + "\\pat_temp\\" + "set_all_final_vposp" + ".sd",
                          G.OUT_DIR + "\\" + code_name[G.i])

            if not use_nmloop:
                _force_pass_write(f, j)
                f.write("\tCONDITION\n\t\tIF_FAIL \n\t\tREJECT_BIN = " + str(
                    G.col("FLOW", "Hbin")[j]) + ";\n@@END_PLAN\n\n")
                return

            f.write("	CALL_MACRO POWER_ON(_C_" + G.col("FLOW", "Vcc")[j].upper() + ");\n\n")
            f.write(
                '	RUN_PATTERN(enter_fbist_mode:START,enter_fbist_mode:END,1,TS_5MHZ);\n\n')
            # wake up
            f.write("	for(I=0;I<100;I++)\n	{\n")
            for nm_name in G.nm_patterns("bulk erase all", "bulk program 00 all"):
                copy_file(G.BASE_DIR + "\\pat_temp\\" +
                          nm_name + ".sd",
                          G.OUT_DIR + "\\" + code_name[G.i])
                f.write('		RUN_PATTERN(' +
                        nm_name + ':START,' +
                        nm_name + ':END,1,TS_5MHZ);\n\n')
            f.write("	}\n\n")

            for nm_name in G.nm_patterns("bulk erase all"):
                copy_file(G.BASE_DIR + "\\pat_temp\\" +
                          nm_name + ".sd",
                          G.OUT_DIR + "\\" + code_name[G.i] )
                f.write('	RUN_PATTERN(' +
                        nm_name + ':START,' +
                        nm_name + ':END,1,TS_5MHZ);\n\n')


            f.write('	CALL_MACRO POWER_OFF();\n\n')
            f.write("	CALL_MACRO POWER_ON(_C_" + G.col("FLOW", "Vcc")[j].upper() + ");\n\n")
            f.write(
                '	RUN_PATTERN(enter_fbist_mode:START,enter_fbist_mode:END,1,TS_5MHZ);\n\n')
            f.write("	for(I=0;I<49;I++)\n	{\n")
            for nm_name in G.nm_patterns("bulk erase NM", "bulk program PCKB NM"):
                copy_file(G.BASE_DIR + "\\pat_temp\\" +
                          nm_name + ".sd",
                          G.OUT_DIR + "\\" + code_name[G.i] )
                f.write('		RUN_PATTERN(' +
                        nm_name + ':START,' +
                        nm_name + ':END,1,TS_5MHZ);\n\n')

            for nm_name in G.nm_patterns("bulk erase NM", "bulk program NCKB NM"):
                copy_file(G.BASE_DIR + "\\pat_temp\\" +
                          nm_name + ".sd",
                          G.OUT_DIR + "\\" + code_name[G.i] )
                f.write('		RUN_PATTERN(' +
                        nm_name + ':START,' +
                        nm_name + ':END,1,TS_5MHZ);\n\n')

            f.write("	}\n\n")
            for u in range(len(G.col("NM_PATTERN", "used"))):
                if G.col("NM_PATTERN", "used")[u] == "bulk erase NM" or G.col("NM_PATTERN", "used")[
                    u] == "bulk program PCKB NM"or G.col("NM_PATTERN", "used")[u] == "bulk read PCKB NM":
                    copy_file(G.BASE_DIR + "\\pat_temp\\" +
                              G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ".sd",
                              G.OUT_DIR + "\\" + code_name[G.i] )
                    f.write('	RUN_PATTERN(' +
                            G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ':START,' +
                            G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ':END,1,TS_5MHZ);\n\n')

            for nm_name in G.nm_patterns("bulk erase NM", "bulk program NCKB NM", "bulk read NCKB NM"):
                copy_file(G.BASE_DIR + "\\pat_temp\\" +
                          nm_name + ".sd",
                          G.OUT_DIR + "\\" + code_name[G.i] )
                f.write('	RUN_PATTERN(' +
                        nm_name + ':START,' +
                        nm_name + ':END,1,TS_5MHZ);\n\n')

            f.write("	for(I=0;I<100;I++)\n	{\n")
            for nm_name in G.nm_patterns("bulk erase all", "bulk program FF all"):
                copy_file(G.BASE_DIR + "\\pat_temp\\" +
                          nm_name + ".sd",
                          G.OUT_DIR + "\\" + code_name[G.i])
                f.write('		RUN_PATTERN(' +
                        nm_name + ':START,' +
                        nm_name + ':END,1,TS_5MHZ);\n\n')
            f.write("	}\n\n")
            for nm_name in G.nm_patterns("bulk read FF NM"):
                copy_file(G.BASE_DIR + "\\pat_temp\\" +
                          nm_name + ".sd",
                          G.OUT_DIR + "\\" + code_name[G.i] )
                f.write('	RUN_PATTERN(' +
                        nm_name + ':START,' +
                        nm_name + ':END,1,TS_5MHZ);\n\n')

            f.write('	CALL_MACRO POWER_OFF();\n\n')
            _force_pass_write(f, j)
            f.write("	CONDITION\n		IF_FAIL \n		REJECT_BIN = " + str(
                G.col("FLOW", "Hbin")[j]) + ";\n@@END_PLAN\n\n")


def margin_write(code_name, f, j):
    bake_space = ""
    if G.col("FLOW", "type")[j] == "margin" and code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[j]:
        bake_space="	"
        f.write("@@PLAN " + G.col("FLOW", "item")[j].title() + "\n")
        if "bake" in G.col("FLOW", "item")[j].lower():
            f.write(
                "	SITE_SEQUENCE      = OFF;\n" +"	GO_THROUGH         = ON;\n"+ '	ENABLE_BY_MARK_NO = 1;\n' + "	S_SETUP_FILE       = c:\\set.dat;\n" +
                "	REMARK             = " + G.col("FLOW", "item")[j].title() + '; \n\n')
        else:
            f.write(
                "	SITE_SEQUENCE      = OFF;\n" + '	DISABLE_BY_MARK_NO = NULL;\n' + "	S_SETUP_FILE       = c:\\set.dat;\n" +
                "	REMARK             = " + G.col("FLOW", "item")[j].title() + '; \n\n')
        f.write("	int flag[MAX_SITE];\n	int finishSite;\n	double _C_forc_V;\n\n")

        f.write("	if(VTEN_FLAG)\n	{\n")

        f.write(bake_space + "	for(I=0;I<MAX_SITE;I++) flag[I]=1;\n\n")
        f.write(
            bake_space + "	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n	" + bake_space + "{\n		" + bake_space + "	if(Sys_ActiveSite[T_SOCKET]==0)continue; \n		" + bake_space + "	flag[T_SOCKET]=0;\n		" + bake_space +"	GB[7+T_SOCKET*64]=")
        if G.col("FLOW", "item")[j].split("_")[0].lower()[-1] == "e":
            f.write( "-1.0;\n	" + bake_space + "}\n\n")
        if G.col("FLOW", "item")[j].split("_")[0].lower()[-1] == "p":
            f.write( "1.0;\n	" + bake_space + "}\n\n")
        f.write(bake_space + "	CALL_MACRO POWER_ON(_C_" + G.col("FLOW", "Vcc")[j].upper() + ");\n\n")

        f.write(bake_space +
                '	RUN_PATTERN(enter_fbist_mode:START,enter_fbist_mode:END,1,TS_5MHZ); \n\n')
        vt_pattern = recipe_pattern_name(
            G.col("FLOW", "item")[j].split("_")[0], "verify mode"
        )
        f.write(
            bake_space + '	RUN_PATTERN(' + vt_pattern + ':START,' +
            vt_pattern + ':END,1,TS_5MHZ);\n\n'
        )
        f.write(bake_space +
                  bake_space + 'for(I=0;I<VT_RANG;I++)\n	' + bake_space + '{\n		' + bake_space + '	finishSite=0;\n		' + bake_space + '	for(J=0;J<MAX_SITE;J++)\n		' + bake_space + '	{\n		' + bake_space + '	if(flag[J]!=0) finishSite++;\n		' + bake_space + '	}\n\n')
        if G.col("FLOW", "item")[j].split("_")[0].lower()[-1] == "e":
            f.write(bake_space +
                    '		if(finishSite!=MAX_SITE)\n		' + bake_space + '	{\n		' + bake_space + '	//printf("TP= %f' + r'\n' + '"' + ', -0.0-0.02*I); \n		'+ bake_space + '	_C_forc_V=-0.0-0.02*I; \n		' + bake_space + '	//fflush(stdout);\n\n		' + bake_space + '	LOGIC_PPMU_FV(TP, _C_forc_V,  E2, I5);\n		' + bake_space + '\n')
        if G.col("FLOW", "item")[j].split("_")[0].lower()[-1] == "p":
            f.write(bake_space +
                    '		if(finishSite!=MAX_SITE)\n		' + bake_space + '	{\n		' + bake_space + '	//printf("TP= %f' + r'\n' + '"' + ', 0.0+0.02*I); \n		'+ bake_space + '	_C_forc_V=0.0+0.02*I; \n		' + bake_space + '	//fflush(stdout);\n\n		' + bake_space + '	LOGIC_PPMU_FV(TP, _C_forc_V,  E2, I5);\n		' + bake_space + '\n')

        FLAG = 0
        for u in range(len(G.col("NM_PATTERN", "used"))):
            if G.col("FLOW", "item")[j].split("_")[1].upper() == "CKB":
                nm_pattern_name = "PCKB"
            elif G.col("FLOW", "item")[j].split("_")[1].upper() == "CKBB":
                nm_pattern_name = "NCKB"
            else:
                nm_pattern_name = G.col("FLOW", "item")[j].split("_")[1].upper()
            if "NM" in G.col("NM_PATTERN", "used")[u] and "bulk read" in G.col("NM_PATTERN", "used")[u] and nm_pattern_name in G.col("NM_PATTERN", "used")[u]:
                f.write(bake_space + '			RUN_PATTERN(' +
                        G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ':START,' +
                        G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ':END,1,TS_5MHZ);\n\n')
            nm_pattern_name = ""
        f.write(bake_space +
                '			for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n		' + bake_space + '	{\n			' + bake_space + '		if(Sys_DriverResult[T_SOCKET] > 0.5)\n			' + bake_space + '		{\n			' + bake_space + '		SYS_SetTestResult(PASS,T_SOCKET);\n			' + bake_space + '		if(flag[T_SOCKET]==0)\n' +
                '			' + bake_space + '		{\n				' + bake_space + '			flag[T_SOCKET]=1;\n							' + bake_space + "GB[7+T_SOCKET*64]=")
        if G.col("FLOW", "item")[j].split("_")[0].lower()[-1] == "e":
            f.write(
                 "-0.0-0.02*(I-1);\n			" + bake_space + "		}\n			" + bake_space + "		}\n		" + bake_space + "	}\n")
        if G.col("FLOW", "item")[j].split("_")[0].lower()[-1] == "p":
            f.write(
                "0.0+0.02*(I-1);\n			" + bake_space + "		}\n			" + bake_space + "		}\n		" + bake_space + "	}\n")
        f.write(bake_space + "		}\n")
        f.write(bake_space + "	}\n\n")

        f.write(bake_space + '	C_COMPARE(GB8, LOG_ALIAS=' + G.col("FLOW", "item")[j] +',LOG_UNIT=V); \n')

        f.write(
            bake_space + "	LOGIC_PPMU_FV(TP, 0V,  E2, I5);\n\n")

        f.write('		CALL_MACRO POWER_OFF();\n\n')

        f.write("	}\n\n")
        _force_pass_write(f, j)
        f.write("	CONDITION\n		IF_FAIL \n	REJECT_BIN = " + str(
            G.col("FLOW", "Hbin")[j]) + ";\n@@END_PLAN\n\n")


def os_write(code_name, f, plan):
    j = plan.row
    os_vcc_F = "SOCKET_SET("
    FS_flage = 0
    repet_flag = 0
    os_vcc_trace = []
    os_vcc_site = []
    if code_name[G.i].split("_")[-1] == plan.cp:

        # f.write("@@MACRO set_send_data(int a)\n\n")

        # f.write("	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n	{\n")
        # f.write("		GB[0+T_SOCKET*64]=0;\n")
        # f.write("		GB[0+T_SOCKET*64]=a;\n")
        # f.write("	} \n\n")
        # f.write("	LOGIC_WRITE_PATTERN_MEMORY(" +
        #         str(list(VERSION["GET PIN"])[i]) + "_Send_mulX" + ":a_data_st, " +
        #         str(list(VERSION["GET PIN"])[i]) + "_Send_mulX" + ":a_data_sp, " + str(
        #     list(VERSION["GET PIN"])[i]) + ", GB1, BIT_COUNT=8, SERIAL,MSB_LSB);\n" )

        # f.write(
        #     '	RUN_PATTERN(' +
        #     str(list(VERSION["GET PIN"])[i]) + "_Send_mulX" + ":START," + str(
        #         list(VERSION["GET PIN"])[i]) + "_Send_mulX" + ":END,1,TS_5MHZ);\n\n")
        # f.write("@@END_MACRO\n\n")
        # copy_file(BASE_DIR + "\\pat_temp\\" +
        #     str(list(VERSION["GET PIN"])[i]) + "_Send_mulX" + ".sd",
        #           BASE_DIR + "\\" + code_name[i])
        f.write(
            "//////////////////////////////////////////////////////////////////\n//\n"
            + "//           Main Flow\n//\n//////////////////////////////////////////////////////////////////\n\n")
        # OS 段引用的电源轨必须是 .prj 里真实定义的代表轨（用户裁决 2026-06-12：
        # 多个 VCC 与 VCC4 共用 DPS 通道、注释行仅为针卡存档，.prg 只能引用未注释
        # 的 VCC4/VREFP；VCC_pin_rebuild 的改名清单含未定义名 VCC1/VCC2 → 编译报
        # Unknown 错。与上电函数 start_up_write 用同一来源 prj_power_pins）
        vccpinname = prj_power_pins(code_name[G.i])
        f.write("@@PLAN " + plan.item.title() + "\n")
        f.write(
            "	SITE_SEQUENCE      = OFF;\n" +"	GO_THROUGH         = ON;\n"+ '	DISABLE_BY_MARK_NO = NULL;\n' + "	S_SETUP_FILE       = c:\\set.dat;\n" +
            "	REMARK             = " + plan.item.title() + '; \n\n')

        relay = flow_relay(j)
        _emit_flow_relay(f, relay, enabled=True)
        f.write("	CALL_MACRO test_start();\n")
        f.write("	LOGIC_SET_DRV_LEVEL(IO_ALLPINS, 0.0V,0.0V, 0.0V, VR1);\n	LOGIC_SET_CMP_LEVEL(IO_ALLPINS,0.0V,0.0V,VR1);\n	LOGIC_CLOSE_PE_RELAY(IO_ALLPINS,WAIT=0.5MS);\n")
        for v in range(len(vccpinname)):
            f.write("	LOGIC_FORCE_DPS("+vccpinname[v]+", 0.0V, 500MA, I7, WAIT=0.5MS);\n\n	LOGIC_CLOSE_DPS_OUTPUT_RELAY("+vccpinname[v]+",ON,WAIT=1MS);\n")
        f.write("	///////////////////////OSTEST odd pins/////////////////////\n")
        f.write("	LOGIC_PPMU_FI(ODD_pins,-100uA, E2, I5);\n")
        f.write("	LOGIC_PPMU_MV(ODD_pins, UP_LIMIT=3.3V, DOWN_LIMIT=-3.3V);\n")
        f.write('	C_COMPARE(ODD_pins, DOWN_LIMIT=-1.2, UP_LIMIT=-0.2, UNIT=V, LOG_ALIAS=OS_[PINGROUP], LOG_UNIT=V);\n\n')
        f.write("	///////////////////////OSTEST even pins/////////////////////\n")
        f.write("	LOGIC_PPMU_FI(EVEN_pins,-100uA, E2, I5);\n")
        f.write("	LOGIC_PPMU_MV(EVEN_pins, UP_LIMIT=3.3V, DOWN_LIMIT=-3.3V);\n")
        f.write('	C_COMPARE(EVEN_pins, DOWN_LIMIT=-1.2, UP_LIMIT=-0.2, UNIT=V, LOG_ALIAS=OS_[PINGROUP], LOG_UNIT=V);\n\n')

        f.write("	///////////////////////TP pin/////////////////////\n")
        f.write('	LOGIC_PPMU_FI(TP,-100uA, E2, I5);\n')
        f.write("	LOGIC_PPMU_MV(TP, UP_LIMIT=3.3V, DOWN_LIMIT=-3.3V);\n")
        f.write("	C_COMPARE(TP, DOWN_LIMIT=-3.0, UP_LIMIT=-0.2, UNIT=V, LOG_ALIAS=OS_[PINGROUP], LOG_UNIT=V);\n\n")
        # OS 不调用 POWER_OFF 宏：该宏固定操作 VCCD，而 OS 由母本派生
        # 全部真实电源轨。这里内联同等的 S100 资源释放序列。
        f.write("	LOGIC_DISCONNECT_PPMU_PIN(IO_ALLPINS);\n")
        f.write("	LOGIC_CLOSE_PE_RELAY(NULL,WAIT=0.5MS);\n")
        for power_pin in vccpinname:
            f.write("	LOGIC_FORCE_DPS(" + power_pin + ", 0.0V, 500MA, I7, WAIT=0.5MS);\n")
        f.write("	WAIT(10mS);\n")
        for power_pin in vccpinname:
            f.write("	LOGIC_CLOSE_DPS_OUTPUT_RELAY(" + power_pin + ",OFF,WAIT=0.5MS);\n")
        f.write("	LOGIC_CLOSE_PMU_RELAY(NULL,WAIT=0.5MS);\n")
        f.write("	WAIT(5mS);\n\n")
        _emit_flow_relay(f, relay, enabled=False)


        # if list(FLOW["CP NO"])[j] == "CP1" or list(FLOW["CP NO"])[j] == "CP2":
        #     f.write("	FORCE_V_MLDPS(VCC,0V,@6V,@500mA,200mA,NORM,OFF,2mS);\n")
        #     f.write("	SET_CBIT(KP, OFF, 2mS);\n")
        #     f.write("	PIN_MODE(IO_ALLPINS,NRZ,EDGE,ENABLE,IO_OFF,NORM);\n\n")
        #     vccpinname = VCC_pin_rebulid("CP1")
        #     for v in range(len(vccpinname)):
        #         f.write("	/////////////////////// " + vccpinname[v] + " pin /////////////////////\n")
        #         f.write("	VOLTAGE vmeas[MAX_SITE];\n")
        #         f.write("	for(I=0;I<MAX_SITE;I++) vmeas[I] = 0;\n")
        #         os_vcc_trace.clear()
        #         os_vcc_site.clear()
        #         for u in range(len(list(PIN_DEC_128["CP NO"]))):
        #             if list(PIN_DEC_128["CP NO"])[u] == "CP1":
        #                 if "F" in str(list(PIN_DEC_128["Trace"])[u]) and list(PIN_DEC_128["Trace"])[
        #                     u] not in os_vcc_trace:
        #                     os_vcc_trace.append(list(PIN_DEC_128["Trace"])[u])
        #                     os_vcc_site.append("S" + str(int(list(PIN_DEC_128["Site"])[u]) - 1))
        #         f.write("	/////////////////////// " + vccpinname[v] + " pin F0/S0 closed /////////////////////\n")
        #         FS_flage = 0
        #         for u in range(len(os_vcc_trace)):
        #             if "F1" in os_vcc_trace[u]:
        #                 if FS_flage == 63:
        #                     os_vcc_F += os_vcc_site[u]
        #                     os_vcc_F += ",FRZ_OFF)//*F0/S0 closed\n	{\n"
        #                 elif FS_flage == 31:
        #                     os_vcc_F += os_vcc_site[u]
        #                     os_vcc_F += "|\n	"
        #                 else:
        #                     os_vcc_F += os_vcc_site[u]
        #                     os_vcc_F += "|"
        #                 FS_flage += 1
        #         f.write("	" + os_vcc_F)
        #         f.write("	SET_CBIT(KP, ON, 2mS);\n")
        #         f.write(
        #             "	FORCE_I_MLDPS(" + vccpinname[v] + ",-100uA,@25mA,@6V,2V,NORM,ON,2mS);\n\n")
        #         f.write(
        #             "	TEST_NUM++;\n" + '	TEST_NO( TEST_NUM);DATALOG_MSG = "OS_TEST_VDD";\n	//MEAS_V_MLDPS(' +
        #             vccpinname[v] + ',2mS, 4, AVE, 50uS);\n	MEAS_V_MLDPS(VCC,2mS);\n')
        #         f.write("	FORCE_I_MLDPS(" + vccpinname[v] + ",0uA,@25mA,@6V,2V,NORM,ON,2mS);\n\n")
        #         f.write("	SOCKET_INC(FRZ_OFF)\n	{\n		vmeas[T_SOCKET]=RESULT_MLDPS_EX(T_SOCKET," + vccpinname[
        #             v] + ");\n	}\n")
        #         f.write('	JUDGE_VARIABLE_MS(vmeas,-1.2V,-0.2V,"OS_TEST_VDD");\n\n')
        #         f.write('	FORCE_V_MLDPS(' + vccpinname[v] + ',0V,@6V,@500mA,500mA,NORM,OFF,2mS);\n')
        #         f.write('	SET_CBIT(KP, OFF, 2mS);\n')
        #         f.write('	}\n\n')
        #         os_vcc_F = "SOCKET_SET("
        #         f.write("	/////////////////////// " + vccpinname[v] + " pin F1/S1 closed /////////////////////\n")
        #         FS_flage = 0
        #         for u in range(len(os_vcc_trace)):
        #             if "F0" in os_vcc_trace[u]:
        #                 if FS_flage == 63:
        #                     os_vcc_F += os_vcc_site[u]
        #                     os_vcc_F += ",FRZ_OFF)//*F1/S1 closed\n	{\n"
        #                 elif FS_flage == 31:
        #                     os_vcc_F += os_vcc_site[u]
        #                     os_vcc_F += "|\n	"
        #                 else:
        #                     os_vcc_F += os_vcc_site[u]
        #                     os_vcc_F += "|"
        #                 FS_flage += 1
        #         f.write("	" + os_vcc_F)
        #         f.write("	SET_CBIT(KP, ON, 2mS);\n")
        #         f.write(
        #             "	FORCE_I_MLDPS(" + vccpinname[v] + ",-100uA,@25mA,@6V,2V,NORM,ON,2mS);\n\n")
        #         f.write(
        #             "	TEST_NUM++;\n" + '	TEST_NO( TEST_NUM);DATALOG_MSG = "OS_TEST_VDD";\n	//MEAS_V_MLDPS(VCC,2mS, 4, AVE, 50uS);\n	MEAS_V_MLDPS(VCC,2mS);\n')
        #         f.write("	FORCE_I_MLDPS(" + vccpinname[v] + ",0uA,@25mA,@6V,2V,NORM,ON,2mS);\n\n")
        #         f.write("	SOCKET_INC(FRZ_OFF)\n	{\n		vmeas[T_SOCKET]=RESULT_MLDPS_EX(T_SOCKET,VCC);\n	}\n")
        #         f.write('	JUDGE_VARIABLE_MS(vmeas,-1.2V,-0.2V,"OS_TEST_VDD");\n\n')
        #         f.write('	FORCE_V_MLDPS(' + vccpinname[v] + ',0V,@6V,@500mA,500mA,NORM,OFF,2mS);\n')
        #         f.write('	SET_CBIT(KP, OFF, 2mS);\n')
        #         f.write('	}\n\n')
        # if list(FLOW["CP NO"])[j] == "CP3":
        # vccpinname = VCC_pin_rebulid("CP3")

        # for v in range(len(vccpinname)):
        #     f.write("	/////////////////////// " + vccpinname[v] + " pin /////////////////////\n")
        #     f.write('	LOGIC_PPMU_FV(FUN_pins,0V, E2, I5);\n')
        #     f.write("	LOGIC_FORCE_DPS(" + vccpinname[v] + ", 0.0V, 500UA, I4, WAIT=0.5MS);\n")
        #     f.write("	LOGIC_CLOSE_DPS_OUTPUT_RELAY(" + vccpinname[v] + ",ON,WAIT=0.5MS); \n")
        #     f.write('	WAIT(2MS);\n')
        #     f.write("	LOGIC_FORCE_DPS(" + vccpinname[v] + ", -1.0V, -500UA, I4, WAIT=0.5MS);\n")
        #     f.write("	LOGIC_DPS_MV(" + vccpinname[v] + ",DOWN_LIMIT=-1.2, UP_LIMIT=-0.2, LOG_ALIAS="+vccpinname[v]+"_OS,LOG_UNIT=V); \n")
        #     f.write("	LOGIC_FORCE_DPS(" + vccpinname[v] + ", 0.0V, 500UA, I4, WAIT=0.5MS);\n\n")


        _force_pass_write(f, j)
        f.write("	CONDITION\n		IF_FAIL \n		REJECT_BIN = " + str(
            G.col("FLOW", "Hbin")[j]) + ";\n@@END_PLAN\n\n")


def main_write(code_name, f, j):
    # pgm_nm
    if G.col("FLOW", "type")[j] == "main" and code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[j]:
        f.write("@@PLAN " + G.col("FLOW", "item")[j].title() + "\n")
        f.write(
            "	SITE_SEQUENCE      = OFF;\n" +"	GO_THROUGH         = ON;\n"+ '	DISABLE_BY_MARK_NO = NULL;\n' + "	S_SETUP_FILE       = c:\\set.dat;\n" +
            "	REMARK             = " + G.col("FLOW", "item")[j].title() + '; \n\n')

        f.write("	CALL_MACRO POWER_ON(_C_" + G.col("FLOW", "Vcc")[j].upper() + ");\n\n")
        f.write(
            '	RUN_PATTERN(enter_fbist_mode:START,enter_fbist_mode:END,1,TS_5MHZ);\n\n')
        f.write(
            '	RUN_PATTERN(set_all_final_vposp:START,set_all_final_vposp:END,1,TS_5MHZ); \n\n')
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
                        copy_file(G.BASE_DIR + "\\pat_temp\\" + G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ".sd",
                                  G.OUT_DIR + "\\" + code_name[G.i] )
                        f.write('	RUN_PATTERN(' +
                                G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ':START,' +
                                G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ':END,1,TS_5MHZ);\n\n')
                except:
                    None

                if "NM" in G.col("NM_PATTERN", "used")[u] and "bulk" in G.col("NM_PATTERN", "used")[
                    u] and nm_pattern_name in G.col("NM_PATTERN", "used")[u] \
                        or G.col("NM_PATTERN", "used")[u] == "bulk erase NM":
                    copy_file(G.BASE_DIR + "\\pat_temp\\" +
                              G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ".sd",
                              G.OUT_DIR + "\\" + code_name[G.i] )
                    f.write('	RUN_PATTERN(' +
                            G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ':START,' +
                            G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ':END,1,TS_5MHZ);\n\n')

                nm_pattern_name = ""
        if G.col("FLOW", "item")[j].split("_")[0] == "Disturb":
            if G.col("FLOW", "item")[j].split("_")[1].upper() != "CKB":
                for nm_name in G.nm_patterns("bulk erase NM"):
                    copy_file(G.BASE_DIR + "\\pat_temp\\" +
                              nm_name + ".sd",
                              G.OUT_DIR + "\\" + code_name[G.i] )
                    f.write('	RUN_PATTERN(' +
                            nm_name + ':START,' +
                            nm_name + ':END,1,TS_5MHZ);\n\n')
                vref = 0
                for u in range(len(G.col("NM_PATTERN", "used"))):
                    if "NM" in G.col("NM_PATTERN", "used")[u] and "bulk" in G.col("NM_PATTERN", "used")[
                        u] and G.col("FLOW", "item")[j].split("_")[1] in G.col("NM_PATTERN", "used")[u]:
                        while vref < 2:
                            copy_file(G.BASE_DIR + "\\pat_temp\\" +
                                      G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ".sd",
                                      G.OUT_DIR + "\\" + code_name[G.i])
                            f.write('	RUN_PATTERN(' +
                                    G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ':START,' +
                                    G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ':END,1,TS_5MHZ);\n\n')
                            vref += 1

                for u in range(len(G.col("NM_PATTERN", "used"))):
                    if "NM" in G.col("NM_PATTERN", "used")[u] and "bulk read" in G.col("NM_PATTERN", "used")[
                        u] and G.col("FLOW", "item")[j].split("_")[1] in G.col("NM_PATTERN", "used")[u]:
                        copy_file(G.BASE_DIR + "\\pat_temp\\" +
                                  G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ".sd",
                                  G.OUT_DIR + "\\" + code_name[G.i] )
                        f.write('	RUN_PATTERN(' +
                                G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ':START,' +
                                G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ':END,1,TS_5MHZ);\n\n')

            if G.col("FLOW", "item")[j].split("_")[1].upper() == "CKB":
                for u in range(len(G.col("NM_PATTERN", "used"))):
                    if G.col("NM_PATTERN", "used")[u] == "bulk erase NM":
                        copy_file(G.BASE_DIR + "\\pat_temp\\" +
                                  G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ".sd",
                                  G.OUT_DIR + "\\" + code_name[G.i] )
                        f.write('	RUN_PATTERN(' +
                                G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ':START,' +
                                G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ':END,1,TS_5MHZ);\n\n')
                    vref = 0
                for nm_name in G.nm_patterns("bulk program PCKB NM"):
                    while vref < 2:
                        copy_file(G.BASE_DIR + "\\pat_temp\\" +
                                  nm_name + ".sd",
                                  G.OUT_DIR + "\\" + code_name[G.i])
                        f.write('	RUN_PATTERN(' +
                                nm_name + ':START,' +
                                nm_name + ':END,1,TS_5MHZ);\n\n')
                        vref += 1
                for u in range(len(G.col("NM_PATTERN", "used"))):
                    if "NM" in G.col("NM_PATTERN", "used")[u] and "bulk read" in G.col("NM_PATTERN", "used")[
                        u] and "PCKB" in G.col("NM_PATTERN", "used")[u]:
                        f.write('	RUN_PATTERN(' +
                                G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ':START,' +
                                G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ':END,1,TS_5MHZ);\n\n')

                for u in range(len(G.col("NM_PATTERN", "used"))):
                    if G.col("NM_PATTERN", "used")[u] == "bulk erase NM":
                        copy_file(G.BASE_DIR + "\\pat_temp\\" +
                                  G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ".sd",
                                  G.OUT_DIR + "\\" + code_name[G.i] )
                        f.write('	RUN_PATTERN(' +
                                G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ':START,' +
                                G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ':END,1,TS_5MHZ);\n\n')
                    vref = 0
                for nm_name in G.nm_patterns("bulk program NCKB NM"):
                    while vref < 2:
                        copy_file(G.BASE_DIR + "\\pat_temp\\" +
                                  nm_name + ".sd",
                                  G.OUT_DIR + "\\" + code_name[G.i] )
                        f.write('	RUN_PATTERN(' +
                                nm_name + ':START,' +
                                nm_name + ':END,1,TS_5MHZ);\n\n')
                        vref += 1
                for u in range(len(G.col("NM_PATTERN", "used"))):
                    if "NM" in G.col("NM_PATTERN", "used")[u] and "bulk read" in G.col("NM_PATTERN", "used")[
                        u] and "NCKB" in G.col("NM_PATTERN", "used")[u]:
                        copy_file(G.BASE_DIR + "\\pat_temp\\" +
                                  G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ".sd",
                                  G.OUT_DIR + "\\" + code_name[G.i] )
                        f.write('	RUN_PATTERN(' +
                                G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ':START,' +
                                G.col("NM_PATTERN", "Pattern name")[u].split(".")[
                                    0] + ':END,1,TS_5MHZ);\n\n')

        f.write('	CALL_MACRO POWER_OFF();\n\n')
        _force_pass_write(f, j)
        f.write("	CONDITION\n		IF_FAIL \n		REJECT_BIN = " + str(
            G.col("FLOW", "Hbin")[j]) + ";\n@@END_PLAN\n\n")


def vt_write(code_name, f, j):
    bake_space = ""
    if G.col("FLOW", "type")[j] == "VT" and code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[j]:
        f.write("@@PLAN " + G.col("FLOW", "item")[j].title() + "\n")
        if "bake" in G.col("FLOW", "item")[j]:
            f.write(
                "	SITE_SEQUENCE      = OFF;\n" +"	GO_THROUGH         = ON;\n"+ '	ENABLE_BY_MARK_NO = 1;\n' + "	S_SETUP_FILE       = c:\\set.dat;\n" +
                "	REMARK             = " + G.col("FLOW", "item")[j].title() + '; \n	GO_THROUGH = ON; \n')
        else:
            f.write(
                "	SITE_SEQUENCE      = OFF;\n" + '	DISABLE_BY_MARK_NO = NULL;\n' + "	S_SETUP_FILE       = c:\\set.dat;\n" +
                "	REMARK             = " + G.col("FLOW", "item")[j].title() + '; \n	GO_THROUGH = ON; \n')
            # "+bake_space+"
            # '+bake_space+'
        f.write("	CALL_MACRO POWER_ON(_C_" + G.col("FLOW", "Vcc")[j].upper() + ");\n\n")
        f.write(
                '	RUN_PATTERN(enter_fbist_mode:START,enter_fbist_mode:END,1,TS_5MHZ); \n\n')
        vt_pattern = recipe_pattern_name(
            G.col("FLOW", "item")[j].split("_")[0], "verify mode"
        )
        f.write('	RUN_PATTERN(' + vt_pattern + ':START,' + vt_pattern +
                ':END,1,TS_5MHZ);\n\n')
        copy_file(G.BASE_DIR + "\\pat_temp\\" + vt_pattern + ".sd",
                  G.OUT_DIR + "\\" + code_name[G.i])
        if "bake" in G.col("FLOW", "item")[j]:
            f.write( "	LOGIC_PPMU_FV(TP, _C_" + G.col("FLOW", "item")[j].split("_")[
                0].upper() + "_BAKE_VOLTAGE,  E2, I3); \n")
        else:
            f.write( "	LOGIC_PPMU_FV(TP, _C_" + G.col("FLOW", "item")[j].split("_")[
                0].upper() + "_VOLTAGE,  E2, I3); \n")
        f.write(bake_space + "\n")

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
                # bake VT 是 CP3 唯一引用 bulk read 的测试项——pattern 必须随程序复制，
                # 否则不进 .prj 清单、RUN_PATTERN 编译报 not defined（2026-06-12 编译实证）
                copy_file(G.BASE_DIR + "\\pat_temp\\" +
                          G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ".sd",
                          G.OUT_DIR + "\\" + code_name[G.i] )
                f.write( '	RUN_PATTERN(' +
                        G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ':START,' +
                        G.col("NM_PATTERN", "Pattern name")[u].split(".")[0] + ':END,1,TS_5MHZ); \n\n')
                FLAG = u
            nm_pattern_name = ""

        if G.col("FLOW", "item")[j].split("_")[0].lower() == "vte":
            f.write( "	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n	{\n")
            f.write("		if(Sys_ActiveSite[T_SOCKET]==0)continue;\n")
            f.write("		if(Sys_DriverResult[T_SOCKET] > 0.5)\n		{\n")
            f.write("			SYS_SetTestResult(PASS,T_SOCKET);\n")
            f.write('			RUN_PATTERN(' +
                    G.col("NM_PATTERN", "Pattern name")[FLAG].split(".")[0] + ':START,' +
                    G.col("NM_PATTERN", "Pattern name")[FLAG].split(".")[0] + ':END,1,TS_5MHZ); \n')
            f.write("		}\n")
            f.write( "	}\n\n")
        f.write(
             "	LOGIC_PPMU_FV(TP, 0V,  E2, I3);\n\n" )

        f.write('	CALL_MACRO POWER_OFF();\n\n')
        _force_pass_write(f, j)
        f.write("	CONDITION\n		IF_FAIL \n		REJECT_BIN = " + str(
            G.col("FLOW", "Hbin")[j]) + ";\n@@END_PLAN\n\n")


def id_write(code_name, f, j, id_plan=None):
    if G.col("FLOW", "type")[j] == "id" and code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[j]:
        is_bake_item = (
            id_plan.target.kind.upper() == "BAKEID"
            if id_plan is not None
            else "bake" in str(G.col("FLOW", "item")[j]).casefold()
        )
        if is_bake_item:
            result = epr_pattern_capture("check", "cp"+str(int(code_name[G.i].split("_")[-1][-1])-1)+"_bake_id")
        else:
            result = epr_pattern_capture("check", "cp"+str(int(code_name[G.i].split("_")[-1][-1])-1)+ "_id")
        f.write("@@PLAN " + G.col("FLOW", "item")[j].title() + "\n")
        f.write(
            "	SITE_SEQUENCE      = OFF;\n" + '	DISABLE_BY_MARK_NO = NULL;\n' + "	S_SETUP_FILE       = c:\\set.dat;\n" +
            "	REMARK             = " + G.col("FLOW", "item")[j].title() + '; \n\n')
        f.write("	CALL_MACRO POWER_ON(_C_" + G.col("FLOW", "Vcc")[j].upper() + ");\n\n")
        f.write(
            '	RUN_PATTERN(enter_fbist_mode:START,enter_fbist_mode:END,1,TS_5MHZ);\n\n')
        copy_file(G.BASE_DIR + "\\pat_temp\\" + result["read"] + ".sd",
                  G.OUT_DIR + "\\" + code_name[G.i] )
        if is_bake_item:
            f.write('	RUN_PATTERN(' +result["read"] + ':START,' +result["read"] + ':END,1,TS_5MHZ, IGNORE_FAIL);\n\n')
            # 用户裁决 2026-07-07：这里读回的 Sys_DriverResult 按 site 记进
            # CP<N-1>_BAKEID_FLAG（startup.py 已声明这个全局数组，Chroma 那边同名
            # 变量早就在用，S100 之前没人写）——真正驱动 Pgm_Cp<N-1>_Bakeid 要不要
            # 往 flash 写的信号改成这个变量，不再靠 MARK_NO（原因：pass die 复测时
            # cp<N-1>_bake_id 页的 pass-flag 已经在上一次测试写过，这里的 check 会
            # 一直判 PASS，MARK_NO 永远不会置 1，导致 Pgm_Cp<N-1>_Bakeid 每次复测都被
            # 跳过、UID 数据没有机会被 capture）。MARK_NO 仍然照写，供
            # Vte/Vtp_Ckb_Bake_Margin/Verify 这几个测试项继续用。
            f.write(
                "	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n	{\n"
                "		if(Sys_ActiveSite[T_SOCKET]==0)continue;\n"
                "		if(Sys_DriverResult[T_SOCKET]>0.5)CP" + str(int(code_name[G.i].split("_")[-1][-1]) - 1) + "_BAKEID_FLAG[T_SOCKET]=1;\n	}\n\n")
        else:
            f.write('	RUN_PATTERN(' + result["read"] + ':START,' + result["read"] + ':END,1,TS_5MHZ);\n\n')
        f.write('	CALL_MACRO POWER_OFF();\n\n')
        _force_pass_write(f, j)
        if is_bake_item:
            f.write("	CONDITION\n		IF_FAIL \n		MARK_NO = 1;\n@@END_PLAN\n\n")

        else:
            f.write("	CONDITION\n		IF_FAIL \n		REJECT_BIN = " + str(
                G.col("FLOW", "Hbin")[j]) + ";\n@@END_PLAN\n\n")


def uid_write(
    code_name, f, j, read_bit, recipe_row=None, persistence_row=None,
    id_plan=None, build_uid_plan=None,
):
    temp_item_name = ""
    addr_map_item = []
    page_word = G.col("VERSION", "page word")[0]
    if G.col("FLOW", "type")[j] == "uid" and code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[j]:
        item_name = str(G.col("FLOW", "item")[j])
        cp_suffix = code_name[G.i].split("_")[-1]
        policy = uid_recipe_policy(
            recipe_row,
            legacy_build_uid=False,
        )
        if policy.build_uid != (build_uid_plan is not None):
            raise ValueError("BUILDUID Recipe and typed BuildUidPlan are inconsistent")
        is_bake_item = (
            id_plan.target.kind.upper() == "BAKEID"
            if id_plan is not None else "bake" in item_name.casefold()
        )
        effective_read_pages = None
        if persistence_row is not None:
            effective_read_pages = {
                page.casefold()
                for operation in persistence_row.operations
                if operation.module == "READOTPMAP"
                for page in operation.effective_pages
            }
        uid_write_dic = {}
        for u in range(len(G.col("FLOW", "UID"))):
            if G.col("FLOW", "UID")[u] == "yes":
                generated_item = generated_flow_item_name(G.FLOW, u)
                if G.col("FLOW", "type")[u] == "trim":
                    item_key = generated_item + "[15:0]"
                else:
                    item_key = generated_item
                cp_num = int(G.col("FLOW", "CP NO")[u][-1])
                
                if item_key not in uid_write_dic or cp_num < uid_write_dic[item_key]:
                    uid_write_dic[item_key] = cp_num
        # print(uid_write_dic)
        filtered_dict = {k: v for k, v in uid_write_dic.items() if "ts" not in k.lower()}
        value_count = pd.Series(filtered_dict).value_counts().to_dict()
        if build_uid_plan is not None:
            f.write("unsigned char const CRC8_TAB[256]={\n"
                    "	0x00, 0x07, 0x0E, 0x09, 0x1C, 0x1B, 0x12, 0x15, 0x38, 0x3F, 0x36, 0x31,\n"
                    "	0x24, 0x23, 0x2A, 0x2D, 0x70, 0x77, 0x7E, 0x79, 0x6C, 0x6B, 0x62, 0x65,\n"
                    "	0x48, 0x4F, 0x46, 0x41, 0x54, 0x53, 0x5A, 0x5D, 0xE0, 0xE7, 0xEE, 0xE9,\n"
                    "	0xFC, 0xFB, 0xF2, 0xF5, 0xD8, 0xDF, 0xD6, 0xD1, 0xC4, 0xC3, 0xCA, 0xCD,\n"
                    "	0x90, 0x97, 0x9E, 0x99, 0x8C, 0x8B, 0x82, 0x85, 0xA8, 0xAF, 0xA6, 0xA1,\n"
                    "	0xB4, 0xB3, 0xBA, 0xBD, 0xC7, 0xC0, 0xC9, 0xCE, 0xDB, 0xDC, 0xD5, 0xD2,\n"
                    "	0xFF, 0xF8, 0xF1, 0xF6, 0xE3, 0xE4, 0xED, 0xEA, 0xB7, 0xB0, 0xB9, 0xBE,\n"
                    "	0xAB, 0xAC, 0xA5, 0xA2, 0x8F, 0x88, 0x81, 0x86, 0x93, 0x94, 0x9D, 0x9A,\n"
                    "	0x27, 0x20, 0x29, 0x2E, 0x3B, 0x3C, 0x35, 0x32, 0x1F, 0x18, 0x11, 0x16,\n"
                    "	0x03, 0x04, 0x0D, 0x0A, 0x57, 0x50, 0x59, 0x5E, 0x4B, 0x4C, 0x45, 0x42,\n"
                    "	0x6F, 0x68, 0x61, 0x66, 0x73, 0x74, 0x7D, 0x7A, 0x89, 0x8E, 0x87, 0x80,\n"
                    "	0x95, 0x92, 0x9B, 0x9C, 0xB1, 0xB6, 0xBF, 0xB8, 0xAD, 0xAA, 0xA3, 0xA4,\n"
                    "	0xF9, 0xFE, 0xF7, 0xF0, 0xE5, 0xE2, 0xEB, 0xEC, 0xC1, 0xC6, 0xCF, 0xC8,\n"
                    "	0xDD, 0xDA, 0xD3, 0xD4, 0x69, 0x6E, 0x67, 0x60, 0x75, 0x72, 0x7B, 0x7C,\n"
                    "	0x51, 0x56, 0x5F, 0x58, 0x4D, 0x4A, 0x43, 0x44, 0x19, 0x1E, 0x17, 0x10,\n"
                    "	0x05, 0x02, 0x0B, 0x0C, 0x21, 0x26, 0x2F, 0x28, 0x3D, 0x3A, 0x33, 0x34,\n"
                    "	0x4E, 0x49, 0x40, 0x47, 0x52, 0x55, 0x5C, 0x5B, 0x76, 0x71, 0x78, 0x7F,\n"
                    "	0x6A, 0x6D, 0x64, 0x63, 0x3E, 0x39, 0x30, 0x37, 0x22, 0x25, 0x2C, 0x2B,\n"
                    "	0x06, 0x01, 0x08, 0x0F, 0x1A, 0x1D, 0x14, 0x13, 0xAE, 0xA9, 0xA0, 0xA7,\n"
                    "	0xB2, 0xB5, 0xBC, 0xBB, 0x96, 0x91, 0x98, 0x9F, 0x8A, 0x8D, 0x84, 0x83,\n"
                    "	0xDE, 0xD9, 0xD0, 0xD7, 0xC2, 0xC5, 0xCC, 0xCB, 0xE6, 0xE1, 0xE8, 0xEF,\n"
                    "	0xFA, 0xFD, 0xF4, 0xF3\n};\n\n")
            f.write("unsigned char GetCRC8(unsigned char  *ucPtr, unsigned char ucLen)\n{\n	unsigned char ucIndex;\n"
                    "	unsigned char ucCRC8 = 0;\n\n	while (ucLen--)\n	{\n		ucIndex = ucCRC8 ^ (*ucPtr++);\n"
                    "		ucCRC8 = CRC8_TAB[ucIndex];\n	}\n	return (~ucCRC8);\n}\n\n")
        if is_bake_item:
            # 用户裁决 2026-07-07：不再用 ENABLE_BY_MARK_NO 门控整个 @@PLAN——原因见下方
            # capture 结束处的注释（pass die 复测场景下这个门控会导致该测试项被永久跳过）。
            f.write("@@PLAN " + G.col("FLOW", "item")[j].title() + "\n")
            f.write(
                "	SITE_SEQUENCE      = OFF;\n" + '	DISABLE_BY_MARK_NO = NULL;\n' + "	S_SETUP_FILE       = c:\\set.dat;\n" +
                "	REMARK             = " + G.col("FLOW", "item")[j].title() + '; \n\n')
        else:
            f.write("@@PLAN " + G.col("FLOW", "item")[j].title() + "\n")
            f.write(
                "	SITE_SEQUENCE      = OFF;\n" + '	DISABLE_BY_MARK_NO = NULL;\n' + "	S_SETUP_FILE       = c:\\set.dat;\n" +
                "	REMARK             = " + G.col("FLOW", "item")[j].title() + '; \n\n')

        if build_uid_plan is not None:
            f.write(
                "	int day,month,year;\n	struct tm * tmptr;//get time\n	time_t secnow;\n	time(&secnow);\n	tmptr = localtime(&secnow);\n\n")
            f.write("	day = tmptr->tm_mday;\n	month = tmptr->tm_mon;\n	year = tmptr->tm_year;\n\n")
            f.write("	year = year-100;\n	month = month+1;\n\n")
            # 参考程序：从 Sys_gszProberWaferID 解析 "-NN" 槽号 → wafer_num（ucPtr[7] 用）
            f.write("	char wafer_id[2];\n	int wafer_num=0;\n	int flag=999;\n")
            f.write("	for(int i=0;i<30;i++)\n	{\n")
            f.write("		if((Sys_gszProberWaferID[i]==0X2D)&&(flag==999)&&(Sys_gszProberWaferID[i+1]>=0X30)&&(Sys_gszProberWaferID[i+1]<=0X39)&&(Sys_gszProberWaferID[i+2]>=0X30)&&(Sys_gszProberWaferID[i+2]<=0X39))\n")
            f.write("		{\n			wafer_id[0]=Sys_gszProberWaferID[i+1];\n			wafer_id[1]=Sys_gszProberWaferID[i+2];\n			flag=0;\n		}\n	}\n")
            f.write("	wafer_num=atoi(wafer_id);\n\n")
            f.write(
                '	printf("WAFER ID = %s , LOT ID = %s(%XH %XH %XH %XH %XH %XH %XH)' + r'\n' + '",gszWaferID,gszLotID,gszLotID[0],gszLotID[1],gszLotID[2],gszLotID[3],gszLotID[4],gszLotID[5],gszLotID[6]);\n\n')
            f.write(
                "	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n	{\n" + '		GB[0+T_SOCKET*64] = X_CO[T_SOCKET];\n		C_COMPARE(GB1,DOWN_LIMIT=-1200, UP_LIMIT=5000, LOG_ALIAS=X_CO);\n'
                +'		GB[0+T_SOCKET*64] = Y_CO[T_SOCKET];\n		C_COMPARE(GB1,DOWN_LIMIT=-1200, UP_LIMIT=5000, LOG_ALIAS=Y_CO);\n	}\n	fflush(stdout);\n\n\n')

        if is_bake_item and policy.readotpmap and (
            effective_read_pages is None or "uid" in effective_read_pages
        ):
            result = epr_pattern_capture("capture", "uid")

            f.write("	CALL_MACRO POWER_ON(_C_" + G.col("FLOW", "Vcc")[j].upper() + ");\n\n")
            f.write(
                '	RUN_PATTERN(enter_fbist_mode:START,enter_fbist_mode:END,1,TS_5MHZ);\n\n')
            if G.col("FLOW", "UID").count("yes") != 0:
                for z in range(len(G.col("ADDR_MAP", "Word No."))):
                    if G.col("ADDR_MAP", "Word No.")[z] not in addr_map_item:
                        addr_map_item.append(G.col("ADDR_MAP", "Word No.")[z])
                # f.write("	SOCKET_INC(FRZ_OFF)\n	{\n\n")
                for cyc in range(len(addr_map_item)):
                    if "lable" in G.col("ADDR_MAP", "data type")[0 + page_word * cyc:(page_word-1) + page_word * cyc] and addr_map_item[cyc] == "uid":
                        result = epr_pattern_capture("capture", addr_map_item[cyc])
                        copy_file(G.BASE_DIR + "\\pat_temp\\" + result["read"] + ".sd",
                                  G.OUT_DIR + "\\" + code_name[G.i] )
                        # 逐字段判断真实字节宽度(2或4字节)+按 read_bit 分组反序，修复原先
                        # 整页统一按32bit算、字节数被高估、后续字段偏移全部错位的问题
                        # （同 chroma/writers.py:_page_field_layout 的问题与修法）。
                        layout = _page_field_layout("uid", read_bit, uid_write_dic, int(code_name[G.i].split("_")[-1][-1]))
                        total_bytes = sum(width for _, width, _so in layout)

                        f.write("	//******************" + addr_map_item[cyc] + " capture***********************\n\n")
                        f.write('	LOGIC_SET_AC_DATALOG(' + result["read"] + ':START,' + result["read"] + ':END,LOG_ENABLE_ALL,AC_IGNORE_FAIL);\n')
                        f.write('	RUN_PATTERN(' + result["read"] + ':START,' + result["read"] + ':END,1,TS_5MHZ);  \n\n')
                        f.write('	LOGIC_CLEAR_SET_AC_FLAG( );\n')
                        f.write('	LOGIC_READ_LOG(LOG_ARRAY,'+ str(G.col("VERSION", "SWD PIN")[G.i]) +", "+str(total_bytes * 8)+", 1,BIN,TRIG_PINNAME=TRIGPIN);//"
                                +str(total_bytes)+"byte\n")
                        # SHOWX is limited to 100 by YT5100; preserve the full LOGIC_READ_LOG
                        # capture length above and constrain only this display-axis parameter.
                        f.write('	DAQ_ARRAY_TRANSFER(LOG_ARRAY,'+str(min(total_bytes, 100))+', 1, 8, "1", "8,7,6,5,4,3,2,1", UP_LIMIT=255, DOWN_LIMIT=0,HEX);//'
                                +str(total_bytes)+"byte\n\n")
                        f.write(
                            "	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n	{\n			if(Sys_ActiveSite[T_SOCKET]==0)continue;\n\n")

                        f.write("		//You need to check it by yourself\n")
                        off = 0
                        for type_flag, width, sub_off in layout:
                            f.write(type_flag + "Sys_SW_BUFFER_DATA[T_SOCKET][" + str(off + sub_off) + "]*256+" +
                                    "Sys_SW_BUFFER_DATA[T_SOCKET][" + str(off + sub_off + 1) + "];\n")
                            off += width

                f.write("	}\n\n")  # socket

            # 用户裁决 2026-07-07：capture 到这里保持无条件执行——上面 @@PLAN 头已经去掉
            # ENABLE_BY_MARK_NO，不会再整体被跳过。但真正往 flash 写的部分（seed/字段
            # 重写/check/最终改写/erase→prog→read，从这里往下）改用 id_write() 里设置的
            # CP<N-1>_BAKEID_FLAG[T_SOCKET] 按 site 关掉 Sys_ActiveSite 来跳过——不需要
            # 真正写 flash 的 site（比如 Read_Cp<N-1>_Bakeid 的 check 已经确认过、不需要
            # 重新 bake 的 site）不参与后续 pattern，但已经不再影响其它 site 的 capture。
            # Site gating belongs after CHECKOTP; keep capture/load/check all-active.

        for_flag = 0
        # print(value_count[1])
        # if list(FLOW["CP NO"])[j] == code_name[i].split("_")[-1] and "yes" in list(FLOW["UID"]) and "bake" not in list(FLOW["item"])[j]:
        #     for u in range(len(list(FLOW["UID"]))):
        #         if list(FLOW["UID"])[u] == "yes"and code_name[i].split("_")[-1] == list(FLOW["CP NO"])[u]and "ts" not in list(FLOW["item"])[
        #             u].lower():
        #             if for_flag == 0:
        #                 f.write("	for(I=0;I<MAX_SITE;I++)\n	{\n")
        #             if list(FLOW["type"])[u] == "trim":
        #                 temp_item_name = list(FLOW["item"])[u].split("Trim")[0].lower()
        #             if list(FLOW["type"])[u] == "verify":
        #                 temp_item_name = list(FLOW["item"])[u].split("Verify")[0].lower()
        #             f.write("	" + temp_item_name + "w[I]=0;\n")
        #             for_flag += 1
        #             if for_flag == value_count[int(code_name[i].split("_")[-1][-1])]:
        #                 f.write("	}\n\n")
        #
        #     for_flag = 0
        #     for u in range(len(list(FLOW["UID"]))):
        #         if list(FLOW["UID"])[u] == "yes"and code_name[i].split("_")[-1] == list(FLOW["CP NO"])[u]and "ts" not in list(FLOW["item"])[
        #             u].lower() and "bake" not in list(FLOW["item"])[j]:
        #             if for_flag == 0:
        #                 f.write("	SOCKET_INC(FRZ_OFF)\n	{\n")
        #             if list(FLOW["type"])[u] == "trim":
        #                 temp_item_name = list(FLOW["item"])[u].split("Trim")[0].lower()
        #             if list(FLOW["type"])[u] == "verify":
        #                 temp_item_name = list(FLOW["item"])[u].split("Verify")[0].lower()
        #             f.write(
        #                 "	" + temp_item_name + "w[T_SOCKET]=(int)(" + temp_item_name + "value_Final[T_SOCKET]*1000+0.5);\n")
        #             f.write(
        #                 "	" + temp_item_name + "w[T_SOCKET]=((" + temp_item_name + "w[T_SOCKET]/1000)%10)*4096+((" + temp_item_name + "w[T_SOCKET]/100)%10)*256+((" + temp_item_name + "w[T_SOCKET]/10)%10)*16+(" + temp_item_name + "w[T_SOCKET]%10);\n\n")
        #             for_flag += 1
        #             if for_flag == value_count[int(code_name[i].split("_")[-1][-1])]:
        #                 f.write("	}\n\n")

        # uid page 的运行时可写 pass-flag（word-offset5 = cp12_id_w/_r，CP3 额外的
        # word-offset6 = cp34_id_w/_r，见 core/flash_seq.py:flash_pattern_label_created
        # Part B）：字面值跟那边 uid_pattern_item 保持同一份映射（该文件里对同一份常量
        # 也是逐函数各自定义一份，非共享，属既有惯例，这里跟随）。
        # 常量取值跟 core/flash_seq.py:flash_pattern_label_created Part B 是同一份映射
        # （该文件对同一份常量本来就逐函数各自定义一份，非共享，属既有惯例）。key 名字
        # "cp<N-1>_bake_id" 只是历史沿用的取值键名，不是 pattern 名——bake 分支实际写入
        # 的 pattern 是"本 CP 自己的 cp<N>_id"（见下方 result 计算的修正），跟 id_write() 里
        # 用同一个 key 名生成的、单独的 fbist_page_check_cp<N-1>_bake_id 只读 check pattern
        # 是两回事，不要混淆。
        uid_pass_flag_item = {"cp1_id": "65FF_FFFF", "cp2_id": "65BA_78FF", "cp3_id": "65BA_78BA",
                              "cp1_bake_id": "65BA_FFFF", "cp2_bake_id": "65BA_78BA"}
        cp_num = int(code_name[G.i].split("_")[-1][-1])

        if is_bake_item and policy.checkotp:
            # Part D 步骤2：先用"上一个 CP 已确定通过"的真实值播种本 CP 自己页面的
            # cp12_id 标签——不是给本 CP 定最终值，只是让软件缓冲区跟"芯片里现在实际
            # 是什么"保持一致，避免下面重写 hsi/vref 等字段时，同一次整页写入把
            # pass-flag 字段带偏（参考程序 Pgm_Cp1_Bakeid/Pgm_Cp2_Bakeid 开头都有这一步，
            # 都不带 FAST_MODE）。
            seed_result = epr_pattern_capture("normal", "cp" + str(cp_num) + "_id")
            write_pat_mem(f, seed_result, 32, "-J", 0, "bakID_CP" + str(cp_num) + "ID",
                          "0x" + uid_pass_flag_item["cp" + str(cp_num - 1) + "_id"].replace("_", ""),
                          "cp12_id_", "no", "fixed", read_dc=True)

        if "yes" in G.col("FLOW", "UID"):

            for u in uid_write_dic.keys():
                if int(code_name[G.i].split("_")[-1][-1]) >= uid_write_dic[u]:
                    # 早写（Part A，trim_data_read_write）已经把 type=="trim" 的 dac 字段
                    # 提前写进本 CP 的 cp<N>_id pattern——非 bake 场景这里跳过，避免重复写；
                    # bake 场景没有早写这一步（bake 走的是刚 capture 回来的值），仍要写。
                    if not is_bake_item and "verify" not in u.lower():
                        continue
                    # bake 场景也写进本 CP 自己的 cp<N>_id pattern（不是 cp<N-1>_bake_id
                    # ——那个只读 pattern 是 id_write() 的 check 分支专用，见上方注释）。
                    result = epr_pattern_capture("normal", "cp" + str(cp_num) + "_id")
                    # bake 场景里，若该字段"起算 CP"正好等于本 CP，说明它是本 CP 自己
                    # 后面才会真正 trim 出来的值——bake 这一步跑在本 CP 自己的 trim 之前，
                    # 此刻从 capture 抓到的只是 flash 里的旧/擦除态占位值，不是真实值，
                    # 读侧比较改用 X（don't care），真正校验交给该字段自己的 trim/verify
                    # 项（同 chroma/writers.py:uid_write 的问题与修法，Ts_125C 类字段实测
                    # 坐实）。非 bake（本函数正常 id 提交）不受影响，此时字段已经过
                    # 本 CP 自己的 trim，==cp_num 是正常已知值。
                    not_yet_real = is_bake_item and uid_write_dic[u] == cp_num
                    if "verify" not in u.lower():
                        temp_item_name = u.split("[")[0].lower()
                        write_pat_mem(f, result, 16, "-J", 0, temp_item_name.split("_")[0], "REG_" + temp_item_name.upper(),
                                  temp_item_name, _uid_pn_flag(temp_item_name),"arr", fast_mode=is_bake_item, read_dc=not_yet_real)
                    elif "verify" in u.lower():
                        temp_item_name = u.split("Verify")[0].lower()
                        write_pat_mem(f, result, 16, "-J", 0, temp_item_name.split("_")[0], temp_item_name.upper() + "W",
                                  temp_item_name, _uid_pn_flag(temp_item_name),"arr", fast_mode=is_bake_item, read_dc=not_yet_real)

        if is_bake_item:
            # Part D 步骤4："check 一下动态写 pattern 是否有问题"——参考程序原样只有一次
            # RUN_PATTERN(read) 落地检查，没有配对的 prog 调用（两份参考程序 Pgm_Cp1_Bakeid/
            # Pgm_Cp2_Bakeid 都是这个结构，不是遗漏，照抄，不自行调整顺序）。
            check_result = epr_pattern_capture("normal", "cp" + str(cp_num) + "_id")
            copy_file(G.BASE_DIR + "\\pat_temp\\" + check_result["read"] + ".sd",
                      G.OUT_DIR + "\\" + code_name[G.i])
            f.write('	/////////////////////////check//////////////////////////\n')
            f.write('	RUN_PATTERN(' + check_result["read"] + ':START,' + check_result["read"] + ':END,1,TS_5MHZ); \n\n')
            f.write('	CALL_MACRO POWER_OFF(); \n\n')
            f.write('	CALL_MACRO POWER_ON(_C_' + G.col("FLOW", "Vcc")[j].upper() + ');\n\n')

        if is_bake_item:
            f.write("	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n	{\n"
                    "		if(CP" + str(cp_num - 1) + "_BAKEID_FLAG[T_SOCKET]!=1) Sys_ActiveSite[T_SOCKET]=0;\n	}\n\n")

        if build_uid_plan is not None and not is_bake_item:
            result = epr_pattern_capture("normal", "cp" + str(cp_num) + "_id")

            f.write("	//*********************LOT_ID***********************\n")
            f.write("	for(I=0;I<7;I++)\n	{\n")
            f.write("		CALL_MACRO write_pat_temp_fixed((int)Sys_gszProberWaferID[I]);\n\n")
            # 偏移必须是编译期常量（pre.exe 不收 8*I 表达式），按参考程序展开为 if(I==N) 常量分支
            for lot_i in range(7):
                if lot_i < 4:
                    lot_w, lot_r, lot_off = "w0", "r0", 8 * lot_i
                else:
                    lot_w, lot_r, lot_off = "w1", "r1", 8 * (lot_i - 4)
                lot_cond = "if" if lot_i == 0 else "else if"
                f.write("		" + lot_cond + "(I==" + str(lot_i) + ")\n		{\n")
                f.write("			LOGIC_WRITE_PATTERN_MEMORY("+result["pgm"]+ ":lot_number_" + lot_w + "_st:" + str(lot_off) + ", "+result["pgm"]+ ":lot_number_" + lot_w + "_sp, "+ str(G.col("VERSION", "SWD PIN")[G.i]) + ", GB1, BIT_COUNT=8, SERIAL,MSB_LSB);\n")
                f.write("			LOGIC_WRITE_PATTERN_MEMORY("+result["read"]+ ":lot_number_" + lot_r + "_st:" + str(lot_off) + ", "+result["read"]+ ":lot_number_" + lot_r + "_sp, "+ str(G.col("VERSION", "SWD PIN")[G.i]) + ", GB1, BIT_COUNT=8, SERIAL,MSB_LSB,DATA1=H,DATA0=L);\n")
                f.write("		}\n")
            f.write("\n	}\n\n")
            temp_cp3_item = ["X_CO", "Y_CO","XY_CO"]
            for item_num in range(len(temp_cp3_item)):
                f.write("	//*********************" + temp_cp3_item[item_num] + "***********************\n")
                f.write("	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n	{\n")
                if temp_cp3_item[item_num] == "X_CO":
                    f.write("		GB[0+T_SOCKET*64] = X_CO[T_SOCKET];\n")
                elif temp_cp3_item[item_num] == "Y_CO":
                    f.write("		GB[0+T_SOCKET*64] = Y_CO[T_SOCKET];\n")
                else:
                    f.write("		GB[0+T_SOCKET*64] = ((Y_CO[T_SOCKET] >> 4) & 0xF0) | ((X_CO[T_SOCKET] >> 8) & 0x0F);\n")
                f.write("	}\n\n")
                co_label = temp_cp3_item[item_num].lower() + "or"  # X_CO -> x_coor 标签族（与 ADDR_MAP/.sd 标签一致）
                f.write("	LOGIC_WRITE_PATTERN_MEMORY(" + result["pgm"] + ":" + co_label + "_w_st, " + result[
                    "pgm"] + ":" + co_label + "_w_sp, " + str(
                    G.col("VERSION", "SWD PIN")[G.i]) + ", GB1, BIT_COUNT=8, SERIAL,MSB_LSB);\n")
                f.write("	LOGIC_WRITE_PATTERN_MEMORY(" + result["read"] + ":" + co_label + "_r_st, " + result[
                        "read"] + ":" + co_label + "_r_sp, " + str(
                        G.col("VERSION", "SWD PIN")[G.i]) + ", GB1, BIT_COUNT=8, SERIAL,MSB_LSB,DATA1=H,DATA0=L);\n")

            f.write("\n	unsigned char ucPtr[14];\n")
            f.write(
                "	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n	{\n		for(I=0;I<14;I++)\n		{\n			if(I<7) ucPtr[I]=int(Sys_gszProberWaferID[I]);//LOT_ID[I]\n			if(I==7) ucPtr[I]=wafer_num;//WAFER_SLOT\n			if(I==8) ucPtr[I]=((abs(Y_CO[T_SOCKET])>>8)&0xF)*16 + ((abs(X_CO[T_SOCKET])>>8)&0xF);\n"
                + "			if(I==9) ucPtr[I]=(X_CO[T_SOCKET])&0xFF;  \n			if(I==10) ucPtr[I]=(Y_CO[T_SOCKET])&0xFF; \n			if(I==11) ucPtr[I]=((year%10)<<4)+month;\n			if(I==12) ucPtr[I]=TESTING_HOUSE_ID;\n"
                + "			if(I==13) ucPtr[I]=CP_VERNO;\n\n		}\n	}\n\n")

            f.write("	unsigned char CRC8=GetCRC8(ucPtr,0x0E);\n\n")
            write_pat_mem(f, result, 8, "-J", 0, "CRC", "CRC8", "crc_8_", "no","fixed")

            write_pat_mem(f, result, 16, "-J", 0, "PROJECT_NAME&&version", "PROJECT_NAME*256+PROJECT_VERSION",
                          "project_", "yes","fixed")
            write_pat_mem(f, result, 8, "-J", 0, "WAFER_SLOT", "WAFER_SLOT", "slot_number_", "no","fixed")
            write_pat_mem(f, result, 8, "-J", 0, "year&&month", "((year%10)<<4)+month", "year_month_", "no","fixed")
            write_pat_mem(f, result, 8, "-J", 0, "TESTING_HOUSE_ID", "TESTING_HOUSE_ID", "testing_house_id_", "no","fixed")
            write_pat_mem(f, result, 8, "-J", 0, "CP_VERNO", "CP_VERNO", "cp_ver_No_", "no","fixed")
            write_pat_mem(f, result, 8, "-J", 0, "program_ver_H", "CP1_VERSION", "cp1_ver_", "no","fixed")
            write_pat_mem(f, result, 8, "-J", 0, "program_ver_L", "CP2_VERSION", "cp2_ver_", "no","fixed")

        # bake、非 bake 最终都写进本 CP 自己的 cp<N>_id pattern（不是 cp<N-1>_bake_id，
        # 理由同上方 seed/check 部分的注释）。
        result = epr_pattern_capture("normal", "cp" + str(cp_num) + "_id")
        if is_bake_item:
            # Part D 步骤5：把 cp12_id 从 seed 值改写成本次 bake 真正要提交的最终值；
            # CP3 的 bake 还要顺带给 CP3 自己的 cp34_id 播一个初始 0xFFFFFFFF 占位——
            # CP3 自己的常规 Pgm_Cp3Id_Read 这时候还没跑到，真正的最终值留给那边写
            # （参考程序 Pgm_Cp2_Bakeid 的"pass id flag"就是这么处理的）。两处都不带
            # FAST_MODE、不需要额外 POWER_ON（沿用 check 步骤留下的供电状态）。
            write_pat_mem(f, result, 32, "-J", 0, "bakID_CP" + str(cp_num) + "ID",
                          "0x" + uid_pass_flag_item["cp" + str(cp_num - 1) + "_bake_id"].replace("_", ""),
                          "cp12_id_", "no", "fixed")
            if code_name[G.i].split("_")[-1] == "CP3":
                write_pat_mem(f, result, 32, "-J", 0, "pass id flag", "0xFFFFFFFF",
                              "cp34_id_", "no", "fixed")
        else:
            # 常规 Pgm_Cp<N>Id_Read：写本 CP 自己真正的最终 pass 值（早写阶段 Part A
            # 只写了占位 0xFFFFFFFF，这里改写成真值）；CP3 额外的 cp34_id 同样在这里
            # 一次性提交最终值。
            write_pat_mem(f, result, 32, "-J", 0, "pass id flag",
                          "0x" + uid_pass_flag_item["cp" + str(cp_num) + "_id"].replace("_", ""),
                          "cp12_id_", "no", "fixed")
            if code_name[G.i].split("_")[-1] == "CP3":
                write_pat_mem(f, result, 32, "-J", 0, "pass id flag", "0x9AFFFFFF",
                              "cp34_id_", "no", "fixed")

        write_fixed_commit(recipe_row, f, cp=cp_suffix)

        if not policy.pgmotp:
            _force_pass_write(f, j)
            f.write("	CONDITION\n		IF_FAIL \n		REJECT_BIN = " + str(
                G.col("FLOW", "Hbin")[j]) + ";\n@@END_PLAN\n\n")
            return

        if not is_bake_item:
            f.write("	CALL_MACRO POWER_ON(_C_" + G.col("FLOW", "Vcc")[j].upper() + ");\n\n")
        f.write("	////////////////////////erase///////////////////////////\n")
        f.write(
            '	RUN_PATTERN(enter_fbist_mode:START,enter_fbist_mode:END,1,TS_5MHZ);\n\n')
        copy_file(G.BASE_DIR + "\\pat_temp\\" + result["erase"] + ".sd",
                  G.OUT_DIR + "\\" + code_name[G.i] )
        f.write('	RUN_PATTERN(' + result["erase"] + ':START,' + result["erase"] + ':END,1,TS_5MHZ); \n\n')
        f.write("	////////////////////////program/////////////////////////\n")
        copy_file(G.BASE_DIR + "\\pat_temp\\" + result["pgm"] + ".sd",
                  G.OUT_DIR + "\\" + code_name[G.i] )
        f.write('	RUN_PATTERN(' + result["pgm"] + ':START,' + result["pgm"] + ':END,1,TS_5MHZ); \n\n')
        f.write("	/////////////////////////read//////////////////////////\n")
        copy_file(G.BASE_DIR + "\\pat_temp\\" + result["read"] + ".sd",
                  G.OUT_DIR + "\\" + code_name[G.i] )
        f.write('	RUN_PATTERN(' + result["read"] + ':START,' + result["read"] + ':END,1,TS_5MHZ); \n\n')

        f.write('	CALL_MACRO POWER_OFF(); \n\n')
        # CP12 id,fail 擦
        write_uid_failed_site_reerase(
            f, result,
            vcc=G.col("FLOW", "Vcc")[j],
        )
        _force_pass_write(f, j)
        f.write("	CONDITION\n		IF_FAIL \n		REJECT_BIN = " + str(
            G.col("FLOW", "Hbin")[j]) + ";\n@@END_PLAN\n\n")


def otp_read_write(code_name, f):
    """OTP_READ debug 项（S100 .prg @@PLAN）：逐页读 OTP 并 datalog 打印。无条件生成，不进 FLOW。
    结构仿 temp/L_PCD2509V1_*12SS 样本的 @@PLAN OTP_test：进 fbist → 逐 distinct 页 RA →
    LOGIC_WRITE_PATTERN_MEMORY 经 otp_read:addr 标签写 8 位地址 → RUN_PATTERN(otp_read) →
    LOGIC_READ_LOG → 打包 → sprintf+WRITELN 排版（每行 4 字节，index 配对交换）。"""
    swd = str(G.col("VERSION", "SWD PIN")[G.i])
    page_word = G.col("VERSION", "page word")[0]
    byte_count = page_word * 4
    gs = max(1, int(G.col("VERSION", "read bit")[0]) // 32)  # 读位宽分组：32→1/64→2/128→4，组内反序

    # otp_read.sd 拷入该程序目录（get_sd_filenames_with_os 会据此登记进 dec）
    copy_file(G.BASE_DIR + "\\pat_temp\\otp_read.sd",
              G.OUT_DIR + "\\" + code_name[G.i] + "\\otp_read.sd")

    # ADDR_MAP distinct 页（Word No.）的 RA 列表
    addr_map_item = []
    for z in range(len(G.col("ADDR_MAP", "Word No."))):
        if G.col("ADDR_MAP", "Word No.")[z] not in addr_map_item:
            addr_map_item.append(G.col("ADDR_MAP", "Word No.")[z])
    ra_list = []
    for cyc in range(len(addr_map_item)):
        ra_list.append(int(G.col("ADDR_MAP", "SM Address")[0 + page_word * cyc].split(";")[0].split("=")[1], 16))
    addr_arry = "{" + ",".join("0x%02X" % r for r in ra_list) + "}"

    f.write("@@PLAN OTP_Read\n")
    f.write("	SITE_SEQUENCE      = OFF;\n	DISABLE_BY_MARK_NO = NULL;\n	S_SETUP_FILE       = c:\\set.dat;\n	REMARK             = OTP_Read; \n\n")
    # 循环变量用程序顶部全局大写 I/J/K（不再局部声明 j/k；用户裁决 2026-06-24）
    f.write("	int r=0;\n	int addr;\n	int cyc;\n")
    f.write("	int byte_count=" + str(byte_count) + ";\n")
    f.write("	int addr_arry[" + str(len(ra_list)) + "]=" + addr_arry + ";\n")
    f.write("	char buffer[2000];\n\n")

    f.write("	CALL_MACRO POWER_ON(_C_VCC_TYP);\n")
    f.write("	RUN_PATTERN(enter_fbist_mode:START,enter_fbist_mode:END,1,TS_5MHZ);\n\n")

    f.write("	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n	{\n")
    f.write("		if (Sys_ActiveSite[T_SOCKET] == 0)continue;\n")
    f.write("		for(cyc=0;cyc<" + str(len(ra_list)) + ";cyc++)\n		{\n")
    f.write("			GB[0+T_SOCKET*64]=addr_arry[cyc];\n")
    f.write("			addr=GB[0+T_SOCKET*64];\n")
    f.write("			C_COMPARE(GB1, UP_LIMIT=2048, DOWN_LIMIT=0.0,LOG_ALIAS=ADD,HEX);\n")
    # 写 8 位页地址：首/尾两标签 START2(RA[7]) / END2(RA[0])（同名单标签会报错，用户裁决 2026-06-24）
    f.write("			LOGIC_WRITE_PATTERN_MEMORY(otp_read:START2, otp_read:END2, " + swd + ", GB1, BIT_COUNT=8, SERIAL,FAST_MODE,VERIFY_DATA);\n\n")
    # START..START1 仅用于动态写 RA；从 START1 起才允许 TRIGPIN 进入 capture。
    f.write("			LOGIC_SET_AC_DATALOG(otp_read:START1,otp_read:END,LOG_ENABLE_ALL,AC_IGNORE_FAIL);\n")
    f.write("			RUN_PATTERN(otp_read:START,otp_read:END,1,TS_5MHZ);\n")
    f.write("			LOGIC_READ_LOG(otp_log, " + swd + ", " + str(byte_count * 8) + ", 1,BIN,TRIG_PINNAME=TRIGPIN);\n\n")
    # 打包：bit -> byte（MSB 先行）
    f.write("			//data in\n")
    f.write("			for(J=0;J<byte_count;J++)\n			{\n")
    f.write("				main_data[T_SOCKET][J]=0;\n")
    f.write("				for(K=0;K<8;K++)\n				{\n")
    f.write("					main_data[T_SOCKET][J] += ((int)Sys_SW_BUFFER_DATA[T_SOCKET][8*J+K]<<(7-K));\n")
    f.write("				}\n			}\n\n")
    # 打印：每行 4 字节，index 按 read bit 分组反序
    f.write("			//PRINT IN\n")
    f.write("			for(J=0;J<byte_count/4;J++)\n			{\n")
    f.write("				int index;\n")
    f.write("				index=(J/" + str(gs) + ")*" + str(gs) + "+(" + str(gs) + "-1-(J%" + str(gs) + "));\n")
    f.write('				sprintf(buffer,"0x%02X%02X: %02X %02X %02X %02X",addr,J*4,main_data[T_SOCKET][4*index+0],main_data[T_SOCKET][4*index+1],main_data[T_SOCKET][4*index+2],main_data[T_SOCKET][4*index+3]);\n')
    f.write("				WRITELN(buffer);\n")
    f.write("			}\n")
    f.write("		}\n	}\n\n")

    f.write("	RUN_PATTERN(exit_fbist_mode:START,exit_fbist_mode:END,1,TS_5MHZ);\n")
    f.write("	CALL_MACRO POWER_OFF();\n\n")
    f.write("	CONDITION\n		IF_FAIL \n		REJECT_BIN=16;\n@@END_PLAN\n\n")


def nm_read_write(code_name, f):
    """NM_Data_Read debug 项（S100 .prg @@PLAN）：整片 main 阵列逐页 capture 读、逐 site dump
    到 `.\\S<n>_main.txt`。无条件生成，接入 flow（@@BOOKING）。
    结构仿样本 @@PLAN NM_Data_Read：进 fbist → 逐 bank（fbist_capture_nm_bank<b>）：首页跑
    START..END1、后续页循环 START2..END2，各 RUN_PATTERN + LOGIC_READ_LOG → Sys_SW_BUFFER →
    打包 byte → fprintf 排版（每行 16 字节，字序分组反序同 otp）。**待上机核实**（pattern 非逐字节）。"""
    swd = str(G.col("VERSION", "SWD PIN")[G.i])
    page_byte = G.flash_mode_dic["PAGE_BYTES"]
    num_banks = 2 if G.col("VERSION", "bank")[0] == "double" else 1
    per_bank_pages = G.flash_mode_dic["NM"] // num_banks
    gs = max(1, int(G.col("VERSION", "read bit")[0]) // 32)

    for b in range(num_banks):
        copy_file(G.BASE_DIR + "\\pat_temp\\fbist_capture_nm_bank" + str(b) + ".sd",
                  G.OUT_DIR + "\\" + code_name[G.i] + "\\fbist_capture_nm_bank" + str(b) + ".sd")

    f.write("@@PLAN NM_Data_Read\n")
    f.write("	SITE_SEQUENCE      = OFF;\n	DISABLE_BY_MARK_NO = NULL;\n	S_SETUP_FILE       = c:\\set.dat;\n	REMARK             = NM_Data_Read; \n\n")
    f.write("	int r=0;\n	int page_byte=" + str(page_byte) + ";\n")
    f.write("	FILE *fp1;\n	char filepath[255];\n\n")

    f.write("	CALL_MACRO POWER_ON(_C_VCC_TYP);\n")
    f.write("	RUN_PATTERN(enter_fbist_mode:START,enter_fbist_mode:END,1,TS_5MHZ);\n\n")

    f.write("	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n	{\n")
    f.write("		if (Sys_ActiveSite[T_SOCKET] == 0)continue;\n")
    f.write('		sprintf(filepath,".\\\\S%d_main.txt",T_SOCKET);\n		fp1=fopen(filepath,"w");\n')
    f.write('		fprintf(fp1,"=============================== Site %d ===============================\\n",T_SOCKET);\n')
    f.write('		fprintf(fp1,"  -user-    0x0 0x1 0x2 0x3 0x4 0x5 0x6 0x7 0x8 0x9 0xA 0xB 0xC 0xD 0xE 0xF\\n");\n\n')

    for b in range(num_banks):
        pat = "fbist_capture_nm_bank" + str(b)
        gbase = "(" + str(b * per_bank_pages) + "+r)*page_byte"   # 全片字节偏移基址
        # 一页读+打包+dump 的公共体（seg = START..END1 首页 / START2..END2 后续页）
        def page_body(seg_lo, seg_hi):
            s = ""
            s += "			LOGIC_SET_AC_DATALOG(" + pat + ":" + seg_lo + "," + pat + ":" + seg_hi + ",LOG_ENABLE_ALL,AC_IGNORE_FAIL);\n"
            s += "			RUN_PATTERN(" + pat + ":" + seg_lo + "," + pat + ":" + seg_hi + ",1,TS_5MHZ);\n"
            s += "			LOGIC_READ_LOG(nm_log, " + swd + ", " + str(page_byte * 8) + ", 1,BIN,TRIG_PINNAME=TRIGPIN);\n"
            s += "			for(J=0;J<page_byte;J++)\n			{\n				main_data[T_SOCKET][J]=0;\n"
            s += "				for(K=0;K<8;K++) main_data[T_SOCKET][J] += ((int)Sys_SW_BUFFER_DATA[T_SOCKET][8*J+K]<<(7-K));\n			}\n"
            s += "			for(J=0;J<16;J++)\n			{\n"
            s += '				fprintf(fp1,"0x080%05X:",' + gbase + "+J*16);\n"
            s += "				for(K=0;K<16;K++)\n				{\n"
            s += "					int index=(K/" + str(gs) + ")*" + str(gs) + "+(" + str(gs) + "-1-(K%" + str(gs) + "));\n"
            s += '					fprintf(fp1,"  %02X",main_data[T_SOCKET][16*J+index]);\n'
            s += "				}\n				fprintf(fp1,\"\\n\");\n			}\n"
            return s
        f.write("		//===== bank" + str(b) + " =====\n")
        f.write("		r=0;\n")
        f.write(page_body("START", "END1"))                       # 首页
        f.write("		for(r=1;r<" + str(per_bank_pages) + ";r++)\n		{\n")
        f.write(page_body("START2", "END2"))                      # 后续页（连续读）
        f.write("		}\n")

    f.write("		fclose(fp1);\n")
    f.write("	}\n\n")
    f.write("	RUN_PATTERN(exit_fbist_mode:START,exit_fbist_mode:END,1,TS_5MHZ);\n")
    f.write("	CALL_MACRO POWER_OFF();\n\n")
    f.write("	CONDITION\n		IF_FAIL \n		REJECT_BIN=16;\n@@END_PLAN\n\n")
