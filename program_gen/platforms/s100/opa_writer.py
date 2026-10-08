# S100 平台：OPA 族（F3）生成器 —— 与 chroma/opa_writer.py 对位。
#
# 母本填法与 Chroma 完全相同（平台无关的 OPA sweep 表 + IOMUX 拓扑，见
# `.Codex/handoffs/2026-07-23-analog-item-sheet-schema-draft.html` §3.1/§7）：
#   FLOW：item="Opa_Test"、mode="swd"、FV/FI="OPA"（哨兵分派）、Vcc、Hbin。
#   OPA sheet：mode / step / inp0_force / inp1_force / inn0_force / inn1_force /
#             down_limit / target / up_limit（一行一档）。
#   IOMUX：OPA 列给各 OPAn 的 VINP0/1 · VINN0/1 · VOUT。
#
# 【用户裁决 2026-07-23】S100 **也用 pin group 组**（与 Chroma 一致，不逐脚展开 force——
# golden 是逐脚写的，但用户要求统一走组）。S100 的组在 `.prj` 的 `@@PIN_GROUP_TABLE`：
# 本模块出 `opa_pin_group_defs(cp_no)` 文本，由 `project_files.write_prj_file` 惰性 import
# 写入（同 adc 的 `ADCn_PPMU_GROUP` 机制）。组成员用两平台共用的
# `analog_sweep.opa_group_specs`——**按"可用实例"过滤**（该 OPA 的 INP0 与 OUT 都出针才计入，
# 否则输出无对应输入激励），与 Chroma 逐字同源。
#
# @@PLAN 结构对齐 golden `temp/LAB_PY32F420A.../Z_*.prg` 的 @@PLAN OPA_test，但 force/量测
# 换成组名：POWER_ON → RUN_PATTERN(GPIO_INIT) → 逐档{ RUN_PATTERN(<prod>_OPA_<mode>_Test)
# → LOGIC_PPMU_FV(OPA_INP0_pins,…) → (diff 档) LOGIC_PPMU_FV(OPA_INN_pins,…)
# → LOGIC_PPMU_FI(OPA_OUT_pins,0UA) + LOGIC_PPMU_MV(OPA_OUT_pins,DOWN/UP_LIMIT,LOG_ALIAS) }
# → POWER_OFF → CONDITION IF_FAIL REJECT_BIN。**S100 逐档展开**（不像 Chroma 用 C 循环），
# 与其它 S100 writer 的既有风格一致。档位 E1/I2(FV)、E1/I6(FI) 照 golden。
# 配置图形 `<prod>_OPA_*` 是外部 SWD 工具产物，copy_file 进程序目录（缺源走占位兜底 + WARN），
# 因为 S100 的 RUN_PATTERN 引用必须能在 .prj PATTERN_NAME 里登记到（不同于 Chroma 的 JUDGE_PAT）。
import analog_sweep as A
from program_gen import state as G
from program_gen.platforms.s100.pattern_files import copy_file
from program_gen.platforms.s100.writers import _keil_step_write


def is_opa_row(z):
    """FLOW 行是否 OPA 族——FV/FI 哨兵 "OPA"（与 Chroma 同一约定）。"""
    return str(G.col("FLOW", "FV/FI")[z]).strip().upper() == "OPA"


def _present_pins(cp_no):
    """本 CP 引出的 IO 短名集合。惰性 import dc_io_pins——避免 project_files 反过来
    import 本模块时循环（同 adc_writer._present_pins）。"""
    from program_gen.platforms.s100.project_files import dc_io_pins
    return set(dc_io_pins(cp_no))


def _opa_rows(cp_no):
    """本 CP 的 OPA FLOW 行号列表（type=verify，mode=swd/keil）。"""
    items = G.col("FLOW", "item")
    return [z for z in range(len(items))
            if str(G.col("FLOW", "CP NO")[z]) == str(cp_no)
            and G.col("FLOW", "type")[z] == "verify"
            and G.col("FLOW", "mode")[z] in ("swd", "keil")
            and is_opa_row(z)]


def _specs(cp_no):
    """本 CP 的 OPA 组规格（可用实例过滤后），[(组名, 出针子集, 全集), ...]。"""
    return A.opa_group_specs(A.build_iomux_roles(G.wb), _present_pins(cp_no))


def opa_pin_group_defs(cp_no):
    """`@@PIN_GROUP_TABLE` 里的 OPA 组定义文本。由 project_files.write_prj_file 调用。
    仅本 CP 有 Opa_Test 行时非空；出针子集为空的组跳过。"""
    if not _opa_rows(cp_no):
        return ""
    out = []
    for name, probed, _full in _specs(cp_no):
        if probed:
            out.append("\t%s, [%s];" % (name, ",".join(probed)))
    return ("\n".join(out) + "\n") if out else ""


def _fval(cell):
    """OPA force 单元格 → S100 电压字面量（"1.65"→"1.65V"）；空返回 None。"""
    v = A.parse_value(cell)
    if v["kind"] == "blank":
        return None
    if v["kind"] == "abs":
        return ("%g" % v["value"]) + "V"
    raise ValueError("s100 opa_writer: OPA 力值只支持绝对电压数字，实际 '%s'" % cell)


def opa_test_write(code_name, f, z):
    """@@PLAN Opa_Test；FLOW.mode 支持 swd/keil，测量主体共用。"""
    entry_mode = str(G.col("FLOW", "mode")[z]).strip().lower()
    if not (code_name[G.i].split("_")[-1] == G.col("FLOW", "CP NO")[z]
            and G.col("FLOW", "type")[z] == "verify" and entry_mode in ("swd", "keil")):
        return
    cp_no = G.col("FLOW", "CP NO")[z]
    rows_flow = _opa_rows(cp_no)
    if not rows_flow or z != rows_flow[0]:
        return

    product = str(G.col("VERSION", "product name")[G.i]).strip()
    dest_dir = G.OUT_DIR + "\\" + code_name[G.i]
    vcc = str(G.col("FLOW", "Vcc")[z]).strip().upper()
    hbin = G.col("FLOW", "Hbin")[z]
    plan = str(G.col("FLOW", "item")[z]).strip().title()

    names = {n for n, probed, _f in _specs(cp_no) if probed}
    has_inp0 = "OPA_INP0_pins" in names
    has_inn = "OPA_INN_pins" in names
    has_out = "OPA_OUT_pins" in names
    rows = A.read_sweep_sheet(G.wb, "OPA", required=True)

    f.write("@@PLAN " + plan + "\n")
    f.write("\tSITE_SEQUENCE      = OFF;\n\tGO_THROUGH         = ON;\n\tDISABLE_BY_MARK_NO = NULL;\n"
            "\tS_SETUP_FILE       = c:\\set.dat;\n\tREMARK             = " + plan + "; \n\n")
    f.write("\tCALL_MACRO POWER_ON(_C_" + vcc + ");\n\n")

    prefix, suffix = A.split_flow_step_template(G.col("FLOW", "step")[z])
    get_pin = G.col("VERSION", "GET PIN")[G.i]
    if entry_mode == "swd":
        init_name = product + "_OPA_GPIO_INIT"
        copy_file(G.BASE_DIR + "\\pat_temp\\" + init_name + ".sd", dest_dir)
        f.write("\tRUN_PATTERN(" + init_name + ":START," + init_name + ":END,1,TS_500K);\n\n")
    elif prefix:
        _keil_step_write(f, z, get_pin, dest_dir, entry_only=True, emit_banner=False,
                         step_override=prefix)

    for row in rows:
        mode = str(row.get("mode") or "").strip()
        if not mode:
            continue
        inp0 = _fval(row.get("inp0_force"))
        inn0 = _fval(row.get("inn0_force"))
        down = str(row.get("down_limit") or "").strip()
        up = str(row.get("up_limit") or "").strip()
        f.write("\t//////////////// OPA " + mode + " ////////////////\n")
        if entry_mode == "swd":
            cfg = product + "_OPA_" + mode + "_Test"
            copy_file(G.BASE_DIR + "\\pat_temp\\" + cfg + ".sd", dest_dir)
            f.write("\tRUN_PATTERN(" + cfg + ":START," + cfg + ":END,1,TS_500K);\n")
        else:
            sheet_step = str(row.get("step") or "").strip()
            if not sheet_step or sheet_step == "/":
                raise ValueError("OPA keil: OPA sheet 的 %s 档缺少 step" % mode)
            _keil_step_write(f, z, get_pin, dest_dir, entry_only=True, emit_banner=False,
                             step_override=sheet_step)
        if has_inp0 and inp0 is not None:
            f.write("\tLOGIC_PPMU_FV(OPA_INP0_pins, " + inp0 + ", E1, I2);\n")
        if has_inn and inn0 is not None:
            f.write("\tLOGIC_PPMU_FV(OPA_INN_pins, " + inn0 + ", E1, I2);\n")
        if has_out:
            f.write("\tLOGIC_PPMU_FI(OPA_OUT_pins, 0UA, E1, I6);\n")
            # LOG_ALIAS 带内建 `[PINGROUP]` token：组量测时按 pin 展开日志名（同
            # dc_scan_writer 的 leakage/RPDRPU 写法），否则整组只记一条、分不清是哪根脚。
            f.write("\tLOGIC_PPMU_MV(OPA_OUT_pins, DOWN_LIMIT=" + down + ", UP_LIMIT=" + up
                    + ", LOG_ALIAS=OPA_" + mode + "_[PINGROUP], LOG_UNIT=V);\n")
        f.write("\n")

    if entry_mode == "keil" and suffix:
        _keil_step_write(f, z, get_pin, dest_dir, entry_only=True, emit_banner=False,
                         step_override=suffix)

    f.write("\tCALL_MACRO POWER_OFF();\n\n")
    f.write("\tCONDITION\n\t\tIF_FAIL \n\t\tREJECT_BIN = " + str(hbin) + ";\n@@END_PLAN\n\n")
