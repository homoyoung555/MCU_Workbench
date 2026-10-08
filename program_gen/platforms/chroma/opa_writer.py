# Chroma 平台：OPA 族（F3 "INIT + 元素测量循环"）生成器。
#
# 母本填法（用户 program_PCD009_V0.9）：
#   FLOW：item="Opa_Test"、mode="swd"、FV/FI="OPA"（哨兵，据此分派）、Vcc；step 列 swd 不用。
#   OPA sheet：一行一档，列 = mode / step / inp0_force / inp1_force / inn0_force / inn1_force /
#         down_limit / target / up_limit。力值绝对电压数字或空("/"); 限值用显式 down/up。
#   IOMUX：OPA 列给各 OPAn 的 VINP0/1 · VINN0/1 · VOUT 引脚。
#   VERSION：product name（配置图形前缀）。
#
# 【用户裁决 2026-07-23】用 **pin group 组**（写进 pin.dec 的 PIN_GROUP 块），不内联引脚名，
# 也不按实例展开。组值 = IOMUX 该角色的全部脚 ∩ 本程序出针脚（`pin.dec` PIN_LIST），注释附
# IOMUX 全集（出针可能只出一个 OPA，组里就一根，注释记全四个）。.pln 引用组名整组 force/测，
# 完全对齐功能项 golden `Opa_Test`（C 数组 + for 循环 + sprintf 拼配置图形名）：force
# OPA_INP0_pins、diff 档 force OPA_INN_pins、FORCE_I 0uA + JUDGE_V OPA_OUT_pins（down/up）。
# INP0 力值取 inp0_force、INN 取 inn0_force（inp1/inn1 列本轮不消费，对齐功能项/pin.dec 里
# INP1 被注释——若后续要 INP1 趟再扩）。配置图形是外部 SWD 工具产物，只 JUDGE_PAT link、不
# copy_file（plncmp 不校验引用存在性；上机前需真实向量）。
import os
import re

import analog_sweep as A
from program_gen import state as G
from program_gen.platforms.chroma.dc_scan_writer import _pin_dec_io_order
from program_gen.platforms.chroma.writers import _keil_step_write

_PIN_GROUP_RE = re.compile(r"(PIN_GROUP\s*\{.*?)(\n\})", re.DOTALL)


def is_opa_row(z):
    """FLOW 行是否 OPA 族——FV/FI 哨兵 "OPA"（对位 adc 的 is_adc_force，分派看 FV/FI）。"""
    return str(G.col("FLOW", "FV/FI")[z]).strip().upper() == "OPA"


def ensure_opa_pin_groups(pat_dir, specs):
    """把 OPA 组追加进 pat_dir/pin.dec 的 PIN_GROUP 块（幂等：组名已存在跳过）；每行附
    IOMUX 全集注释。出针子集为空的组跳过（该角色本程序未出针）。返回真正写入的组名集合。"""
    dec_path = os.path.join(pat_dir, "pin.dec")
    with open(dec_path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    written = set()
    lines = []
    for name, probed, full in specs:
        if name in text:                       # 幂等
            if probed:
                written.add(name)
            continue
        if not probed:
            continue                           # 本程序没出这个角色的针，不写
        comment = "    //" + "+".join(full) if full else ""
        lines.append("   " + name + " = " + "+".join(probed) + ";" + comment)
        written.add(name)
    if lines:
        m = _PIN_GROUP_RE.search(text)
        if not m:
            raise ValueError("ensure_opa_pin_groups: " + dec_path + " 找不到 PIN_GROUP 块")
        new_text = text[:m.end(1)] + "\n" + "\n".join(lines) + m.group(2) + text[m.end(2):]
        with open(dec_path, "w", encoding="utf-8") as fh:
            fh.write(new_text)
    return written


def _fval(cell):
    """OPA force 单元格 → 电压字面量数值串（"1.65"→"1.65"）；空返回 None。"""
    v = A.parse_value(cell)
    if v["kind"] == "blank":
        return None
    if v["kind"] == "abs":
        return "%g" % v["value"]
    raise ValueError("opa_writer: OPA 力值只支持绝对电压数字，实际 '%s'" % cell)


def _c_array(decl, name, values):
    """生成 C 数组声明串，如 double inp0[3]={1.65,1.2,0.6};"""
    return "  " + decl + " " + name + "[" + str(len(values)) + "]={" + ",".join(values) + "};\n"


def opa_test_write(code_name, f, z, pat_dir):
    """生成一个 OPA 测试项；FLOW.mode 支持 swd/keil，测量主体共用。"""
    entry_mode = str(G.col("FLOW", "mode")[z]).strip().lower()
    if not (code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[z]
            and G.col("FLOW", "type")[z] == "verify" and entry_mode in ("swd", "keil")):
        return
    roles = A.build_iomux_roles(G.wb)
    rows = A.read_sweep_sheet(G.wb, "OPA", required=True)
    product = str(G.col("VERSION", "product name")[G.i]).strip()
    item = G.col("FLOW", "item")[z]
    vcc = str(G.col("FLOW", "Vcc")[z]).strip().upper()

    real_pins = set(_pin_dec_io_order(pat_dir))
    specs = A.opa_group_specs(roles, real_pins)   # 可用实例过滤，两平台共用
    written = ensure_opa_pin_groups(pat_dir, specs)
    has_inp0 = "OPA_INP0_pins" in written
    has_inn = "OPA_INN_pins" in written
    has_out = "OPA_OUT_pins" in written
    relay_grp = "+".join(n for n in ("OPA_INP0_pins", "OPA_INN_pins", "OPA_OUT_pins") if n in written)

    # C 数组：mode / inp0 / inn0(空→哨兵 99) / down / up
    modes = [str(r.get("mode") or "").strip() for r in rows if str(r.get("mode") or "").strip()]
    inp0, inn0, dn, up = [], [], [], []
    for r in rows:
        if not str(r.get("mode") or "").strip():
            continue
        v = _fval(r.get("inp0_force"));  inp0.append(v if v is not None else "0")
        vn = _fval(r.get("inn0_force")); inn0.append(vn if vn is not None else "99")
        dn.append(str(r.get("down_limit") or "").strip())
        up.append(str(r.get("up_limit") or "").strip())
    n = len(modes)

    f.write("\n" + item + "()\n{\n")
    # 测试项开头的号段基数 + 项名 datalog，同其它 chroma 测试项惯例（基号=(FLOW行号+1)*100）
    f.write("  TEST_NUM=" + str((z + 1) * 100) + ";\n"
            '  TEST_NO(TEST_NUM);DATALOG_MSG="' + item + '";\n\n')
    f.write("  char opa_mode[" + str(n) + "][32]={" + ",".join('"' + m + '"' for m in modes) + "};\n")
    f.write(_c_array("double", "opa_inp0", inp0))
    f.write(_c_array("double", "opa_inn0", inn0))
    f.write(_c_array("double", "opa_down", dn))
    f.write(_c_array("double", "opa_up", up))
    f.write("  char pat_st[48],pat_sp[48],log_msg[48];\n\n")

    f.write("  POWER_ON(" + vcc + ");\n\n")
    if relay_grp:
        f.write("  RELAY_ON(" + relay_grp + ", PPMU_PDCL, 2mS);\n\n")
    prefix, suffix = A.split_flow_step_template(G.col("FLOW", "step")[z])
    get_pin = G.col("VERSION", "GET PIN")[G.i]
    if entry_mode == "swd":
        init_name = product + "_OPA_GPIO_INIT"
        f.write('  TEST_NUM++;\n  TEST_NO(TEST_NUM); DATALOG_MSG="' + init_name + '";\n'
                '  JUDGE_PAT(' + init_name + ',__' + init_name + ');\n\n')
    elif prefix:
        _keil_step_write(f, z, get_pin, pat_dir, entry_only=True, emit_banner=False,
                         step_override=prefix)

    if entry_mode == "swd":
        f.write("  for(int it=0;it<" + str(n) + ";it++)\n  {\n")
        f.write('    sprintf(pat_st,"' + product + '_OPA_%s_Test:START",opa_mode[it]);\n')
        f.write('    sprintf(pat_sp,"' + product + '_OPA_%s_Test:END",opa_mode[it]);\n')
        f.write("    DATALOG_MSG=pat_st;\n    JUDGE_PAT(S:pat_st,S:pat_sp);\n\n")
        if has_inp0:
            f.write("    FORCE_V_PPMU(OPA_INP0_pins, opa_inp0[it], ,@32mA, , 2mS);\n")
        if has_inn:
            f.write("    if(opa_inn0[it]<90) FORCE_V_PPMU(OPA_INN_pins, opa_inn0[it], ,@32mA, , 2mS);\n")
        f.write('\n    sprintf(log_msg,"OPA_%s_Verify",opa_mode[it]);\n    DATALOG_MSG=log_msg;\n')
        if has_out:
            f.write("    FORCE_I_PPMU(OPA_OUT_pins, 0uA, @200uA, ,6V, -2V ,3mS);\n")
            f.write("    JUDGE_V_PPMU(OPA_OUT_pins, opa_down[it], opa_up[it], 2mS);\n")
        f.write("  }\n\n")
    else:
        for row in rows:
            mode = str(row.get("mode") or "").strip()
            if not mode:
                continue
            sheet_step = str(row.get("step") or "").strip()
            if not sheet_step or sheet_step == "/":
                raise ValueError("OPA keil: OPA sheet 的 %s 档缺少 step" % mode)
            _keil_step_write(f, z, get_pin, pat_dir, entry_only=True, emit_banner=False,
                             step_override=sheet_step)
            inp = _fval(row.get("inp0_force"))
            inn = _fval(row.get("inn0_force"))
            if has_inp0 and inp is not None:
                f.write("  FORCE_V_PPMU(OPA_INP0_pins, %s, ,@32mA, , 2mS);\n" % inp)
            if has_inn and inn is not None:
                f.write("  FORCE_V_PPMU(OPA_INN_pins, %s, ,@32mA, , 2mS);\n" % inn)
            f.write('  DATALOG_MSG="OPA_%s_Verify";\n' % mode)
            if has_out:
                f.write("  FORCE_I_PPMU(OPA_OUT_pins, 0uA, @200uA, ,6V, -2V ,3mS);\n")
                f.write("  JUDGE_V_PPMU(OPA_OUT_pins, %s, %s, 2mS);\n\n"
                        % (str(row.get("down_limit") or "").strip(),
                           str(row.get("up_limit") or "").strip()))
        if suffix:
            _keil_step_write(f, z, get_pin, pat_dir, entry_only=True, emit_banner=False,
                             step_override=suffix)

    if relay_grp:
        f.write("  RELAY_OFF(" + relay_grp + ", PPMU_PDCL, 2mS);\n\n")
    f.write("  POWER_OFF();\n}\n")
