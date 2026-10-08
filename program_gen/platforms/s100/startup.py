# S100 平台：.prg 程序框架（变量声明、bin 定义、启动代码）。
import os
from program_gen.core.pattern_data import reuse_dac_restore_items
from program_gen.platforms.s100.pattern_files import copy_file
from program_gen.platforms.s100.project_files import prj_power_pins
from program_gen.platforms.s100.adc_writer import adc_global_decls, adc_csv_setup
from program_gen import state as G
from program_gen.core.recipe_trim import dac_final_symbol, generated_flow_item_name
from program_gen.core.schedule_plan import BinBindingKind


def _build_uid_startup_plan(cp):
    """Resolve BUILDUID startup dependencies from this CP's explicit Recipe."""
    if G.product_compilation is None:
        raise RuntimeError("ProductCompilation must be installed before rendering")
    rows = G.product_compilation.for_cp(cp).build_uid_rows
    return next(iter(rows.values()), None)


def pln_file_created(code_name, only=None):
    # //////////////////////////////////////////////PLN文件生成 start///////////////////////////////////////////////////////
    # only: 只生成这些 VERSION 行下标对应的程序（None=全部）——用于"只生成某个 CP"，
    # 不选中的下标直接跳过，不会用 'w' 截断它已有的 .prg（否则会把没选中的 CP 清空成空壳）。

    for i in range(len(G.col("VERSION", "Program Name"))):
        if only is not None and i not in only:
            continue
        os.makedirs(G.OUT_DIR + "\\" + code_name[i], exist_ok=True)
        build_uid_startup = _build_uid_startup_plan(G.col("VERSION", "CP num")[i])
        # os.makedirs(BASE_DIR + "\\" + code_name[i]+"\\pat", exist_ok=True)
        copy_file(G.BASE_DIR + "\\pat_temp\\" + "enter_fbist_mode" + ".sd",
                  G.OUT_DIR + "\\" + code_name[i])
        copy_file(G.BASE_DIR + "\\pat_temp\\" + "exit_fbist_mode" + ".sd",
                  G.OUT_DIR + "\\" + code_name[i])
        # copy_file(BASE_DIR + "\\pat_temp\\pin_" + str(code_name[i].split("_")[-2].split("S")[0]) + "S.dec",BASE_DIR + "\\" + code_name[i]+"\\pat")

        # for u in range(len(list(NM_PATTERN["description"]))):
        #     copy_file(BASE_DIR + "\\pat_temp\\" + list(NM_PATTERN["Pattern name"])[u].split(".")[0] + ".sd",
        #               BASE_DIR + "\\" + code_name[i] + "\\pat")

        with open(G.OUT_DIR + "\\" + code_name[i] + "\\"+ code_name[i] + ".prg", 'w') as f:
            f.write(
                "////////////////////////////////////////////////////////////////////////////////////////////////\n// UPDATE LOG\n"
                + "// " + str(code_name[i].split("_")[-4]) + "_" + str(code_name[i].split("_")[-3]) + " version\n//\n////////////////////////////////////////////////////////////////////////////////////////////////\n\n")
            f.write("#include <time.h>\n#include <math.h>\n#define MAX_SITE "+code_name[i].split("_")[-2].split("S")[0]+"\n\n")
            f.write('int BIT[24];\nint I,J,K;\nint TEMP;\nint TRIM_DIGIT;\nint T_SOCKET;\n\n')
            if G.col("VERSION", "CP num")[i] != "CP1":
                f.write('int CP' + str(int(G.col("VERSION", "CP num")[i][-1]) - 1) + '_BAKEID_FLAG[MAX_SITE];\nint TEMP_DATA[1024];\nint CAP_DATA[MAX_SITE];\n\n')

            if G.col("VERSION", "CP num")[i] == "CP1":
                f.write('double _C_VCC_PDR_MIN = ' + str(G.col("VERSION", "pdr min")[i]) + ';\ndouble _C_VCC_PDR_TAR = ' +
                        str(G.col("VERSION", "pdr target")[i]) + ';\ndouble _C_VCC_PDR_MAX = ' + str(
                    G.col("VERSION", "pdr max")[i]) + ';\n\n\n')
            if G.col("VERSION", "CP num")[i] == "CP2":
                f.write('double _C_VCC_PDR_MIN = ' + str(
                    G.col("VERSION", "pdr min")[i]) + ';\ndouble _C_VCC_PDR_MAX = ' + str(
                    G.col("VERSION", "pdr max")[i]) + ';\n\n\n')
            if build_uid_startup is not None:
                project_name = str(G.col("VERSION", "project name")[i]).strip()
                # PROJECT_NAME is a decimal project identifier.  Leading zeroes make the
                # YT5100 C parser treat it as octal, so e.g. "088" must be emitted as "88".
                if project_name.isdecimal():
                    project_name = str(int(project_name, 10))
                f.write('\n\n//test condition\n')
                f.write('int CP_VERNO= ' + str(G.col("VERSION", "CP spec")[i]) + ';\n')
                f.write('int CP1_VERSION= ' + str(G.col("VERSION", "CP ver high")[i]) + ';\n')
                f.write('int CP2_VERSION= ' + str(G.col("VERSION", "CP ver low")[i]) + ';\n')
                f.write('int PROJECT_NAME= ' + project_name + ';\n')
                f.write('int PROJECT_VERSION= ' + str(G.col("VERSION", "project ver")[i]) + ';\n')
                f.write('int TESTING_HOUSE_ID = ' + "'" + code_name[i].split("_")[0] + "'" + ';\n\n\n')

            f.write('double _C_VCC_MIN = ' + str(G.col("VERSION", "vcc min")[i]) + ';\ndouble _C_VCC_TYP = ' + str(
                G.col("VERSION", "vcc typ")[i]) + ';\ndouble _C_VCC_MAX = '
                    + str(G.col("VERSION", "vcc max")[i]) + ';\n\n')
            # f.write('TIME FSCLK_TYP   = 200nS; //TS1\nTIME FSCLK_500K  = 2000nS;//TS2\n\n')
            # f.write('TIME FSCLK_ERASE = ' + str(
            #     int((list(VERSION["erase time(ms)"])[i] / 0.0125) + 0.5)) + 'nS;//TS5  200ns=erase 2.5ms\n')
            # f.write('TIME FSCLK_PGM   = ' + str(
            #     int((list(VERSION["program time(ms)"])[i] / 0.0075) + 0.5)) + 'nS;//TS6    200ns=pgm 1.5ms\n\n')
            if G.col("VERSION", "CP num")[i] == "CP1" or G.col("VERSION", "CP num")[i] == "CP2":
                f.write(
                    'double _C_VTE_VOLTAGE = ' + str(G.col("VERSION", "VTE target")[i]) + ';\ndouble _C_VTP_VOLTAGE = ' +
                    str(G.col("VERSION", "VTP target")[i]) + ';\n\n')
            if G.col("VERSION", "CP num")[i] == "CP2" or G.col("VERSION", "CP num")[i] == "CP3":
                f.write('double _C_VTE_BAKE_VOLTAGE = ' + str(
                    G.col("VERSION", "VTE bake target")[i]) + ';\ndouble _C_VTP_BAKE_VOLTAGE = ' +
                        str(G.col("VERSION", "VTP bake target")[i]) + ';\n\n')

            if G.col("VERSION", "CP num")[i] == "CP1" or G.col("VERSION", "CP num")[i] == "CP2":
                f.write('double _C_VPOSE_TAR = ' + str(G.col("VERSION", "vpose")[i]) + ';\ndouble _C_VNEGE_TAR = ' +
                        str(G.col("VERSION", "vnege")[i]) + ';\ndouble _C_VPOSP_TAR = ' + str(
                    G.col("VERSION", "vposp")[i]) + ";\ndouble _C_VNEGP_TAR = "
                        + str(G.col("VERSION", "vnegp")[i]) + ";\n\n")
            if build_uid_startup is not None:
                f.write('char WAFERID[32], LOT_ID[32] ;\nint WAFER_SLOT;\nint LOAD_ID_FLAG;\n\n')

            f.write('int X_CO[MAX_SITE],Y_CO[MAX_SITE];\n\n')
            # OTP_Read / NM_Data_Read debug 项打包用全局缓冲（每 site 一页字节）；两处都引用，原先漏声明
            f.write('int main_data[MAX_SITE][' + str(G.col("VERSION", "page word")[0] * 4) + '];\n\n')
            f.write('int VT_RANG = 75;// 0.02*VT_RANG=1.5V\n\n')
            f.write('bool VTEN_FLAG = false;\n\n')


def item_variable_created(
    code_name, cp_num, f, dac_write_plans=None, result_export_plans=None,
    declarations=None,
):
    # //////////////////////////////////////////////item variable 写入start//////////////////////////////////////////////
    global i
    G.i = cp_num
    flag = 0
    num_flag = 0
    CP_NUM = []
    page_word = G.col("VERSION", "page word")[0]
    legacy_declared_names = set()

    for j in range(len(G.col("FLOW", "CP NO"))):
        if G.col("FLOW", "CP NO")[j] == code_name[G.i].split("_")[-1]:
            CP_NUM.append(j)

    if "trim" in G.col("FLOW", "type")[CP_NUM[0]:CP_NUM[-1]]:
        f.write("//trim dac write variable\n")
        for j in range(CP_NUM[0], CP_NUM[-1]):
            if G.col("FLOW", "CP NO")[j] == code_name[G.i].split("_")[-1]:
                if G.col("FLOW", "OTP")[j] == "yes" and flag == 0:
                    f.write("int ")
                if G.col("FLOW", "OTP")[j] == "yes" and flag != 3:
                    if num_flag == G.col("FLOW", "OTP")[CP_NUM[0]:CP_NUM[-1]].count("yes")-1:
                        f.write(generated_flow_item_name(G.FLOW, j).split("Trim")[0].upper() + "DAC_FINAL[MAX_SITE];\n")
                    else:
                        f.write(generated_flow_item_name(G.FLOW, j).split("Trim")[0].upper() + "DAC_FINAL[MAX_SITE],")
                        flag += 1
                        num_flag += 1

                elif G.col("FLOW", "OTP")[j] == "yes":
                    f.write(generated_flow_item_name(G.FLOW, j).split("Trim")[0].upper() + "DAC_FINAL[MAX_SITE];\n")
                    flag = 0
                    num_flag += 1
        if code_name[G.i].split("_")[-1] == "CP1":
            flow_trim_items = [generated_flow_item_name(G.FLOW, j).split("Trim")[0].upper().rstrip("_") for j in range(len(G.col("FLOW", "item")))]
            vars_to_write = []
            for var in ["VCSL", "VNEG2", "VBL"]:
                if var not in flow_trim_items:
                    vars_to_write.append(var + "_DAC_FINAL[MAX_SITE]")
            if vars_to_write:
                f.write("int " + ",".join(vars_to_write) + ";\n\n")

    addr_map_item = []
    for cyc in range(len(G.col("ADDR_MAP", "Word No."))):
        if G.col("ADDR_MAP", "Word No.")[cyc] not in addr_map_item :
            addr_map_item.append(G.col("ADDR_MAP", "Word No.")[cyc])

    for cyc in range(len(addr_map_item)):

        if code_name[G.i].split("_")[-1][-1] in G.col("ADDR_MAP", "line")[cyc * (page_word+1)] and "lable" in G.col("ADDR_MAP", "data type")[page_word * cyc:page_word * (cyc+1)] and addr_map_item[cyc] != "uid":

            f.write("//" + addr_map_item[cyc] + "\n")
            flag = 0
            num_flag = 0
            for j in range(len(G.col("ADDR_MAP", "data type"))):
                if G.col("ADDR_MAP", "Word No.")[j] == addr_map_item[cyc]:
                    if G.col("ADDR_MAP", "data type")[j] == "lable" and flag == 0:
                        f.write("int ")
                    if G.col("ADDR_MAP", "data type")[j] == "lable" and flag != 3:
                        if num_flag == G.col("ADDR_MAP", "data type")[page_word * cyc:page_word * (cyc+1)].count("lable")-1:
                            _name = "REG_" + str(G.col("ADDR_MAP", "bit[15:0]")[j].split("[")[0].upper())
                            legacy_declared_names.add(_name)
                            f.write(_name + "[MAX_SITE];\n")
                        else:
                            _name = "REG_" + str(G.col("ADDR_MAP", "bit[15:0]")[j].split("[")[0].upper())
                            legacy_declared_names.add(_name)
                            f.write(_name + "[MAX_SITE],")
                            flag += 1
                            num_flag += 1

                    elif G.col("ADDR_MAP", "data type")[j] == "lable":
                        _name = "REG_" + str(G.col("ADDR_MAP", "bit[15:0]")[j].split("[")[0].upper())
                        legacy_declared_names.add(_name)
                        f.write(_name + "[MAX_SITE];\n")
                        flag = 0
                        num_flag += 1
            f.write("\n")
    # 本 CP 需要声明的 uid 寄存器/校验变量名（按首次出现顺序去重）。原先靠"item 名字
    # -> 字典"统计各 CP 数量再用计数器猜"跑到第几个该收尾"的写法，遇到同一个 item
    # 名字跨多个 CP 出现（如某 trim 项在 CP1/CP3 都是 UID==yes）时会重复声明
    # （C2086 同款风险，同 Chroma 2026-07-06 修的一样，S100 这里是自己独立的同款
    # bug）。这里直接按最终变量名去重，不再依赖那套计数逻辑。
    cp_digit = int(code_name[G.i].split("_")[-1][-1])
    seen_uid_names = set()
    uid_names = []
    for j in range(len(G.col("FLOW", "item"))):
        if G.col("FLOW", "UID")[j] != "yes":
            continue
        if int(G.col("FLOW", "CP NO")[j][-1]) > cp_digit:
            continue
        flow_type_j = G.col("FLOW", "type")[j]
        if flow_type_j == "trim":
            name = "REG_" + str(G.col("FLOW", "item")[j]).upper()
        elif flow_type_j == "verify":
            name = generated_flow_item_name(G.FLOW, j).lower().split("verify")[0].upper() + "W"
        else:
            continue
        if name not in seen_uid_names:
            seen_uid_names.add(name)
            uid_names.append(name)
            legacy_declared_names.add(name)

    f.write("//uid\n")
    for idx, name in enumerate(uid_names):
        if idx % 4 == 0:
            f.write("int ")
        sep = ";\n" if (idx % 4 == 3 or idx == len(uid_names) - 1) else ","
        f.write(name + "[MAX_SITE]" + sep)
    f.write("\n")
    if declarations is not None:
        missing_registers = tuple(
            item.name
            for item in declarations.register_images
            if item.name not in legacy_declared_names
        )
        if missing_registers:
            f.write("//typed register image closure\n")
            for offset in range(0, len(missing_registers), 4):
                f.write(
                    "int "
                    + ",".join(
                        name + "[MAX_SITE]"
                        for name in missing_registers[offset:offset + 4]
                    )
                    + ";\n"
                )
            f.write("\n")

    if code_name[G.i].split("_")[-1] != "CP1":
        f.write("//pump dac write variable\n")
        flag = 0
        num_flag = 0
        for j in range(len(G.col("FLOW", "item"))):
            if G.col("FLOW", "PUMP")[j] == "yes" and flag == 0:
                f.write("int ")
            if G.col("FLOW", "PUMP")[j] == "yes" and flag != 3:
                if num_flag == G.col("FLOW", "PUMP").count("yes") - 1:
                    f.write(generated_flow_item_name(G.FLOW, j).split("Trim")[0].upper() + "DAC_FINAL[MAX_SITE];\n")
                else:
                    f.write(generated_flow_item_name(G.FLOW, j).split("Trim")[0].upper() + "DAC_FINAL[MAX_SITE],")
                    flag += 1
                    num_flag += 1

            elif G.col("FLOW", "PUMP")[j] == "yes":
                f.write(generated_flow_item_name(G.FLOW, j).split("Trim")[0].upper() + "DAC_FINAL[MAX_SITE];\n")
                flag = 0
                num_flag += 1
        flow_trim_items = [generated_flow_item_name(G.FLOW, j).split("Trim")[0].upper().rstrip("_") for j in range(len(G.col("FLOW", "item")))]
        vars_to_write = []
        for var in ["VCSL", "VNEG2", "VBL"]:
            if var not in flow_trim_items:
                vars_to_write.append(var + "_DAC_FINAL[MAX_SITE]")
        if vars_to_write:
            f.write("int " + ",".join(vars_to_write) + ";\n\n\n")

        # 跨 CP 复用 dac 补值的变量（如 CP3 复用 CP1 已 trim 好的 Hsi_Vrega，本 CP 没有
        # 对应 Trim 步骤，需要单独声明 *_DAC_FINAL 接住从 EPR 读回算出的值）。同
        # chroma/startup.py:item_variable_created 同一块逻辑移植（2026-07-06）。
        restore_items = reuse_dac_restore_items(code_name[G.i].split("_")[-1])
        restore_vars = [dac_final_symbol(item) + "[MAX_SITE]" for item in restore_items]
        if restore_vars:
            f.write("//reuse dac write variable\n")
            f.write("int " + ",".join(restore_vars) + ";\n\n\n")

    dac_write_vars = [
        symbol + "[MAX_SITE]"
        for symbol in (dac_write_plans.global_symbols if dac_write_plans else ())
    ]
    if dac_write_vars:
        f.write("//DAC_WRITE ADDR_MAP restore variable\n")
        f.write("int " + ",".join(dac_write_vars) + ";\n\n")

    export_declarations = [
        (c_type, symbol)
        for c_type, symbol in (
            result_export_plans.global_declarations if result_export_plans else ()
        )
        if symbol not in seen_uid_names
    ]
    if export_declarations:
        f.write("//EXPORT result variable\n")
        for c_type, symbol in export_declarations:
            f.write(f"{c_type} {symbol}[MAX_SITE];\n")
        f.write("\n")

    # [Trae AI Generated Code] - Declare LOG_MSG variables for trim items
    f.write("//trim dac print variable\n")
    trim_log_msg_vars = []
    for z in range(len(G.col("FLOW", "type"))):
        if G.col("FLOW", "type")[z] == "trim" and G.col("FLOW", "CP NO")[z] == code_name[G.i].split("_")[-1]:
            trim_name = str(G.col("FLOW", "item")[z].split("Trim")[0]).lower().rstrip("_")
            upper_name = trim_name.upper()
            if upper_name + "_LOG_MSG" not in trim_log_msg_vars:
                trim_log_msg_vars.append("_C_" + upper_name + "_LOG_MSG")
    
    if trim_log_msg_vars:
        f.write("char ")
        for idx, var in enumerate(trim_log_msg_vars):
            if idx == len(trim_log_msg_vars) - 1:
                f.write(var + "[64];\n\n")
            elif (idx + 1) % 4 == 0:
                f.write(var + "[64];\nchar ")
            else:
                f.write(var + "[64],")

    # ADC 满通道全局表（方案2，2026-07-20）：chanl_ADCn_item/_C_ADCn_limit_*/_C_LOG_MSG_ADCn，
    # 仅本 CP 有 Adc_Test 时写（无则空串、不污染其它母本）。
    f.write(adc_global_decls(code_name[G.i].split("_")[-1]))


def _canonical_booking(f, schedule):
    definitions = {item.identity: item for item in schedule.definitions}
    f.write("@@BOOKING\n\n")
    emitted = set()
    for entry in schedule.entries:
        if entry.placement != "BOOKED":
            continue
        binding = entry.bin_binding
        if binding.kind is BinBindingKind.DIRECT:
            definitions[entry.definition_id]
        elif binding.kind is BinBindingKind.DEFINITION_REFERENCE:
            definitions[binding.definition_id]
        else:
            raise ValueError(f"unsupported canonical bin binding: {binding.kind!r}")
        if entry.identity in emitted:
            continue
        f.write("\t" + ("//" if not entry.enabled else "") + entry.render_name + ";\n")
        emitted.add(entry.identity)
    f.write("\n@@END_BOOKING" + "\n" * 4)


def Hw_Sw_Bin(code_name, f, trim_specs=None, *, canonical_schedule=None):
    if canonical_schedule is not None:
        _canonical_booking(f, canonical_schedule)
        return
    if trim_specs is None:
        if G.compiled_adapter is None:
            raise RuntimeError("compiled adapter must be installed before rendering")
        trim_specs = G.compiled_adapter.trim_specs
    trash = []
    # //////////////////////////////////////////////item 分bin 写入start//////////////////////////////////////////////
    f.write("@@BOOKING\n\n")

    for j in range(len(G.col("FLOW", "item"))):
        from program_gen.platforms.s100.comp_writer import is_comp_row, package_cases
        if is_comp_row(j) and not package_cases(j):
            continue
        s = G.col("FLOW", "item")
        s[j] = generated_flow_item_name(G.FLOW, j)
        if len(s[j]) < 40:
            s[j] += ";"
            s[j] += " " * (35 - len(s[j]))
        # mode=="hex"（hex_download_write）/mode=="keil"（keil_pattern_write）/两者
        # 混用（hex_download_write 的 _multi_hex_keil_write 合并分支）现在都各自生成
        # 对应的 @@PLAN 了（2026-07-06，修复 handoff 2026-07-05 第 4/5 条"S100 静默
        # 丢失 mode=hex/keil 测试项"），调度不再需要按 mode 特殊排除——跟 Chroma 的
        # TEST_PRO 一样，泛化地按 item 名去重调度即可。
        if G.col("FLOW", "CP NO")[j] == code_name[G.i].split("_")[-1]:
            if s[j].title() + G.col("FLOW", "CP NO")[j] not in trash:
                # FLOW.item 灰色标记（G.flow_row_flag=="comment_out"，同 chroma 一样的
                # 用户裁决 2026-07-05）：该测试项在调度里整行注释掉。S100 用户 2026-07-06
                # 确认写法就是"直接在 booking 里面屏蔽它"——@@BOOKING 每行本就是普通调度
                # 项名字，屏蔽=行首加 "//"（跟本函数已有的 both_m 场景注释写法一致）。
                row_commented = G.flow_row_flag(j) == "comment_out"
                trim_spec = trim_specs.get(j)
                if trim_spec is not None:
                    for variant in trim_spec.search.variants:
                        if variant.kind == "FULL_SCAN":
                            plan_name = s[j].split("Trim")[0].title() + "Dac_Loop;"
                        else:
                            plan_name = s[j].title()
                        commented = row_commented or not variant.scheduled
                        f.write("\t" + ("//" if commented else "") + plan_name + "\n")
                elif G.col("FLOW", "Bisection")[j] == "both" or G.col("FLOW", "Bisection")[j] == "both_m":
                    if G.col("FLOW", "Bisection")[j] == "both_m" or row_commented:
                        f.write("	" + ("//" if row_commented else "") + s[j].split("Trim")[0].title()+ "Dac_Loop;" + "\n")
                        f.write("	//" + s[j].title() + "\n")
                    else:
                        f.write("	//" + s[j].split("Trim")[0].title()+ "Dac_Loop;" + "\n")
                        f.write("	" + s[j].title() + "\n")
                else:
                    f.write("	" + ("//" if row_commented else "") + s[j].title() +"\n")
                trash.append(s[j].title() + G.col("FLOW", "CP NO")[j])

    f.write("	OTP_Read;\n")  # OTP_READ debug 项接入 booking 末尾（用户裁决 2026-06-24）
    f.write("	NM_Data_Read;\n")  # NM_Data_Read debug 项接入 booking（无条件，2026-06-25）
    f.write("\n@@END_BOOKING" + "\n" * 4)
    trash.clear()


def _has_sram_cap(cp_no):
    """本 CP 是否有 SRAM capture 行（UNIT=cap 且 cap_cfg pattern 段=SRAM）。同
    chroma/startup.py:_has_sram_cap。"""
    flow_cp = G.col("FLOW", "CP NO")
    flow_unit = G.col("FLOW", "UNIT")
    flow_cap = G.col("FLOW", "cap_cfg")
    for k in range(len(flow_cp)):
        if flow_cp[k] == cp_no and str(flow_unit[k]).strip().lower() == "cap" \
                and str(flow_cap[k]).strip().split("-")[0].upper() == "SRAM":
            return True
    return False


def _read_sram_write(code_name, f):
    """Read_SRAM(address) 全局函数（S100 版，对位 chroma/startup.py:_read_sram_write）：SWD 读
    SRAM 一个 **32bit** 字。种子 sram_capture.sd 手工制作（copy_file 拷入程序目录）：运行时
    `LOGIC_WRITE_PATTERN_MEMORY` 改 addr_st..addr_sp（低 16 位地址，高位/SRAM 基址固定在种子）
    + parity_st..parity_sp（popcount+1 取奇偶），`RUN_PATTERN` 跑、`LOGIC_DAQ_DATA_READ` 读回
    32bit（`Sys_SW_BUFFER_DATA` LSB 拼）存 sram_data[T_SOCKET]（多工位各一份）。
    **读固定 32bit**——cap_cfg 的 bpd 只在 capture_sram_write 里决定 count(=total_bits//bpd)，
    不影响读宽（对齐 Chroma 权威参考：TK bpd=16 / SRAM_cap bpd=32 共用同一 Read_SRAM 读 32bit）。
    地址/parity 装 GB1/GB2、写 LSB_MSB、SWD 从 VERSION（2026-07-21 用户裁决）。只在该 CP 有
    UNIT=cap+cap_cfg=SRAM 行时写。"""
    cp_no = code_name[G.i].split("_")[-1]
    if not _has_sram_cap(cp_no):
        return
    swd = str(G.col("VERSION", "SWD PIN")[G.i])
    daq = ",".join(str(i) for i in range(1, 33))   # "1,2,...,32"
    f.write("int sram_data[MAX_SITE];\n")
    f.write("void Read_SRAM(int address)\n{\n")
    f.write("	int cnta=0, parity=0;\n")
    f.write("	cnta=0; for(int x=address;x;x&=x-1) cnta++; parity=(cnta+1)&1;\n\n")
    f.write("	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n	{\n")
    f.write("		if(Sys_ActiveSite[T_SOCKET]==0)continue;\n")
    f.write("		GB[0+T_SOCKET*64]=address; // GB1=address\n")
    f.write("		GB[1+T_SOCKET*64]=parity;  // GB2=parity\n")
    f.write("	}\n")
    f.write("	LOGIC_WRITE_PATTERN_MEMORY(sram_capture:addr_st, sram_capture:addr_sp, " + swd + ", GB1, BIT_COUNT=16, SERIAL, LSB_MSB);\n")
    f.write("	LOGIC_WRITE_PATTERN_MEMORY(sram_capture:parity_st, sram_capture:parity_sp, " + swd + ", GB2, BIT_COUNT=1, SERIAL, LSB_MSB);\n")
    f.write("	LOGIC_SET_AC_DATALOG(sram_capture:START, sram_capture:END, LOG_ENABLE_ALL, AC_IGNORE_FAIL);\n")
    f.write('	LOGIC_DAQ_TRANSFER_SETTING(' + swd + ', "' + daq + '", TRIG=PTN_TRIG,ACLOG_FILTER_BY_PTN_TRIG_MODE);\n')
    f.write("	RUN_PATTERN(sram_capture:START, sram_capture:END, 1, TS_5MHZ);\n")
    f.write("	LOGIC_DAQ_DATA_READ(DATA_COUNT=32);\n")
    f.write("	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n	{\n")
    f.write("		if(Sys_ActiveSite[T_SOCKET]==0)continue;\n")
    f.write("		sram_data[T_SOCKET]=0;\n")
    f.write("		for(J=0;J<32;J++) sram_data[T_SOCKET] += (int)Sys_SW_BUFFER_DATA[T_SOCKET][J]<<J;\n")
    f.write("		GBX[1+1024*T_SOCKET]=sram_data[T_SOCKET];\n")
    f.write("	}\n")
    f.write("}\n\n")


def start_up_write(code_name, f):
    # //////////////////////////////////////////////start up 写入start//////////////////////////////////////////////
    f.write("@@START_UP\n")
    f.write("	blSoftwareBin = 1; \n")
    f.write("	LOGIC_SET_DRV_LEVEL(IO_ALLPINS, 0.0V, 0.0V, 0.0V, VR1); \n	LOGIC_SET_CMP_LEVEL(IO_ALLPINS, 0.0V, 0.0V, VR1);\n	WAIT(20MS);\n")
    f.write("	//LOGIC_SET_OPTIMIZE(PPMU=ON,DPS=TURBO); \n")
    
    # [Trae AI Generated Code] - Generate for loops for each trim item
    for z in range(len(G.col("FLOW", "type"))):
        if G.col("FLOW", "type")[z] == "trim" and G.col("FLOW", "CP NO")[z] == code_name[G.i].split("_")[-1]:
            trim_name = str(G.col("FLOW", "item")[z].split("Trim")[0]).lower().rstrip("_")
            dac_bit = G.col("FLOW", "DAC bit")[z]
            dac_max = int(pow(2, dac_bit) - 1)
            upper_name = "_C_"+trim_name.upper()
            f.write("	for(I=0; I<pow(2, " + str(dac_bit) + "); I++)\n")
            f.write("	{\n")
            f.write("		sprintf(" + upper_name + "_LOG_MSG, \"" + trim_name + "_dac_%d\", I);\n")
            f.write("		SET_CSV_LOG_ALIAS(LOG_ALIAS=" + upper_name + "_LOG_MSG, DOWN_LIMIT=0, UP_LIMIT=" + str(dac_max) + ", LOG_UNIT=NA);\n")
            f.write("	}\n")
    # [End Trae AI Generated Code]

    # ADC CSV 列预注册（方案2，2026-07-20）：每通道 SET_CSV_LOG_ALIAS，仅本 CP 有 Adc_Test 时写。
    f.write(adc_csv_setup(code_name[G.i].split("_")[-1]))

    f.write("@@END_START_UP \n\n")
    f.write("@@MACRO write_pat_temp_arry(int* a)\n")
    f.write("	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n	{\n		if (Sys_ActiveSite[T_SOCKET] == 0)continue;\n		GB[0+T_SOCKET*64]=0;\n		GB[0+T_SOCKET*64]=a[T_SOCKET];\n	}\n\n")
    f.write("@@END_MACRO \n\n")

    f.write("@@MACRO write_pat_temp_fixed(int a)\n")
    f.write("	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n	{\n		if (Sys_ActiveSite[T_SOCKET] == 0)continue;\n		GB[0+T_SOCKET*64]=0;\n		GB[0+T_SOCKET*64]=a;\n	}\n\n")
    f.write("@@END_MACRO \n\n")

    f.write("@@MACRO Bitwise_not_arry(int* a)\n")
    f.write("	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n	{\n		if (Sys_ActiveSite[T_SOCKET] == 0)continue;\n		GB[0+T_SOCKET*64]=0;\n		GB[0+T_SOCKET*64]=a[T_SOCKET]^0xFFFF;\n	}\n\n")
    f.write("@@END_MACRO \n\n")

    f.write("@@MACRO Bitwise_not_fixed(int a)\n")
    f.write("	for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n	{\n		if (Sys_ActiveSite[T_SOCKET] == 0)continue;\n		GB[0+T_SOCKET*64]=0;\n		GB[0+T_SOCKET*64]=a^0xFFFF;\n	}\n\n")
    f.write("@@END_MACRO \n\n")

    f.write("@@MACRO Clear_GB()\n")
    f.write("	for(I=0;I<64;I++)\n	{\n		for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\n		{\n				GB[I+T_SOCKET*64]=0;\n		}\n	}\n\n")
    f.write("@@END_MACRO \n\n")
    # //////////////////////////////////////////////start up 写入end/////////////////////////////////////////////////
    # //////////////////////////////////////////////test start 写入start//////////////////////////////////////////////
    f.write("@@MACRO test_start()\n")
    f.write("	CALL_MACRO Clear_GB();\n\n")
    f.write("	for(I=0;I<MAX_SITE;I++)\n	{\n		X_CO[I]=Sys_ProberX[I];\n		Y_CO[I]=Sys_ProberY[I];\n	}\n\n")
    f.write("	//Y_CO[0]=100;\n\n")

    # 修正(用户裁决 2026-06-12)：原小写 y_co/x_co 是未定义符号(C 大小写敏感，
    # bcc32 报 Undefined symbol)；下标 31 越界(MAX_SITE=12)改为 MAX_SITE-1；
    # 晶圆分区阈值(57/67/30/29)保持不变
    f.write("	if((Y_CO[MAX_SITE-1]>57 && Y_CO[MAX_SITE-1]<67) && X_CO[0]<30)VTEN_FLAG=true;\n")
    f.write("	else if((Y_CO[0]>57 && Y_CO[0]<67) && X_CO[0]>29)VTEN_FLAG=true;\n")
    f.write("	else\n	{VTEN_FLAG=false;}")
    f.write("	//VTEN_FLAG=true;\n") 

    # if code_name[i].split("_")[-1] == "CP3":
    #     f.write("	///////////////////////////wafer infor///////////////////////////////\n\n")
    #     f.write(
    #         "	if(LOAD_ID_FLAG==1)\n	{\n" + '		printf("WAFER ID = %s , LOT ID = %s(%XH %XH %XH %XH %XH %XH %XH)' + r"\n" + '",gszWaferID,gszLotID,gszLotID[0],gszLotID[1],gszLotID[2],gszLotID[3],gszLotID[4],gszLotID[5],gszLotID[6]);\n\n')
    #     f.write(
    #         "		if(strlen(WAFERID)<10)\n		{\n		" )
    #     f.write(
    #         '			printf("Manual INPUT WAFER ID = %s , LOT ID = %s(%XH %XH %XH %XH %XH %XH %XH)' + r"\n" + '",gszWaferID,gszLotID,gszLotID[0],gszLotID[1],gszLotID[2],gszLotID[3],gszLotID[4],gszLotID[5],gszLotID[6]);\n		}\n')
    #     f.write(
    #         "		if(strlen(WAFERID)>10) WAFER_SLOT = ((int)gszWaferID[8]-48)*10+((int)gszWaferID[9]-48); //WAFERID example AP12972-23-D2\n")
    #     f.write(
    #         "		else\n		{\n			WAFER_SLOT = 0xFF;\n			for(I=0;I<7;I++) LOT_ID[I]=0xFF;\n			ABORT_TEST_PLN();\n		}\n")
    #     f.write("		if((WAFER_SLOT<1)||(WAFER_SLOT>25))ABORT_TEST_PLN();\n")
    #     f.write(
    #         '		printf("Slot No = %d' + r"\n" + '",WAFER_SLOT);\n		fflush(stdout); \n		LOAD_ID_FLAG = 0;\n	}\n\n')
    f.write("@@END_MACRO \n\n")

    # //////////////////////////////////////////////test start 写入end//////////////////////////////////////////////
    # 真实电源轨从生成的 .prj 取（未注释 pwr 行，排除 VDDD），见 prj_power_pins
    vccpin = prj_power_pins(code_name[G.i])

    # //////////////////////////////////////////////power_on 写入start////////////////////////////////////////////
    f.write("@@MACRO POWER_ON_1ST(double _C_vccVolt)\n")
    f.write("	LOGIC_SET_DRV_LEVEL(IO_ALLPINS, 0.0V, 0.0V, 0.0V, VR1);\n")
    f.write("	LOGIC_SET_CMP_LEVEL(IO_ALLPINS, 0.0V, 0.0V,VR2);\n")
    f.write("	LOGIC_SET_DRV_LEVEL(TP, 0.0V, 0.0V, 0.0V, VR1);\n")
    f.write("	LOGIC_SET_CMP_LEVEL(TP, 0.0V, 0.0V,VR2);\n")
    for v in range(len(vccpin)):
        f.write("	LOGIC_FORCE_DPS(" + vccpin[v] + ", 0.0V, 500MA, I7, WAIT=0.5MS);\n")
    f.write("	WAIT(5MS);\n")
    for v in range(len(vccpin)):
        f.write("	LOGIC_CLOSE_DPS_OUTPUT_RELAY("+vccpin[v]+",ON,WAIT=0.5MS); \n")
    for v in range(len(vccpin)):   
        f.write("	LOGIC_FORCE_DPS(" + vccpin[v] + ", _C_vccVolt, 500MA, I7, WAIT=0.5MS);\n")
    f.write("	LOGIC_SET_DRV_LEVEL(IO_ALLPINS, _C_vccVolt, 0.0V, 0.0V, VR1);\n")
    f.write("	LOGIC_SET_CMP_LEVEL(IO_ALLPINS, _C_vccVolt*0.55, _C_vccVolt*0.45, VR2);\n")
    f.write("	LOGIC_SET_DRV_LEVEL(TP, _C_vccVolt, 0.0V, 0.0V, VR1);\n")
    f.write("	LOGIC_SET_CMP_LEVEL(TP,0.8,0.3,VR2);\n")
    f.write("	LOGIC_CLOSE_PE_RELAY(IO_ALLPINS,WAIT=0.5MS);\n")
    f.write("	WAIT(10MS);\n\n")
    f.write("@@END_MACRO \n\n")

    f.write("@@MACRO POWER_ON(double _C_vccVolt)\n")
    f.write("	LOGIC_SET_DRV_LEVEL(IO_ALLPINS, 0.0V, 0.0V, 0.0V, VR1);\n")
    f.write("	LOGIC_SET_CMP_LEVEL(IO_ALLPINS, 0.0V, 0.0V,VR2);\n")
    f.write("	LOGIC_SET_DRV_LEVEL(TP, 0.0V, 0.0V, 0.0V, VR1);\n")
    f.write("	LOGIC_SET_CMP_LEVEL(TP, 0.0V, 0.0V,VR2);\n")
    for v in range(len(vccpin)):
        f.write("	LOGIC_FORCE_DPS(" + vccpin[v] + ", 0.0V, 500MA, I7, WAIT=0.5MS);\n")
    f.write("	WAIT(5MS);\n")
    for v in range(len(vccpin)):
        f.write("	LOGIC_CLOSE_DPS_OUTPUT_RELAY("+vccpin[v]+",ON,WAIT=0.5MS); \n")
    for v in range(len(vccpin)):   
        f.write("	LOGIC_FORCE_DPS(" + vccpin[v] + ", _C_vccVolt, 500MA, I7, WAIT=0.5MS);\n")

    f.write("	LOGIC_SET_DRV_LEVEL(IO_ALLPINS, _C_vccVolt, 0.0V, 0.0V, VR1);\n")
    f.write("	LOGIC_SET_CMP_LEVEL(IO_ALLPINS,_C_vccVolt*0.55,_C_vccVolt*0.45,VR2);\n")
    f.write("	LOGIC_SET_DRV_LEVEL(TP, _C_vccVolt, 0.0V, 0.0V, VR1);\n")
    f.write("	LOGIC_SET_CMP_LEVEL(TP,0.8,0.3,VR2);\n")
    f.write("	LOGIC_CLOSE_PE_RELAY(IO_ALLPINS,WAIT=0.5MS);\n")
    f.write("	WAIT(10MS);\n\n")
    f.write("@@END_MACRO \n\n")

    # POWER_ON_VIHVIL：DC_VIHVIL_Test（VIL/VIH 输入门限测试）专用上电宏（2026-07-20）。
    # 结构照上面的普通 POWER_ON（同一份 vccpin 逐轨上电），只把 IO_ALLPINS 的驱动/比较
    # 电平从满幅换成 VIL/VIH 半摆：驱动 VIH=vcc*0.55 / VIL=vcc*0.45、比较 VOH=vcc*0.67 /
    # VOL=vcc*0.33（VT=50%）。VILVIH 测试靠把输入脚只驱动到阈值附近的窄窗口、跑功能
    # pattern 比较判 pass/fail，故驱动电平必须是半摆而非满幅。
    # golden Y_PY32E407 的 POWER_ON_VIHVIL 用了该产品专属轨名（VCC_DPS/VBAT_DPS/VREF_PMU），
    # 不能照抄——这里基于本项目通用的 vccpin 逐轨机制克隆。
    # 百分比取值：2026-07-20 用户裁决先对齐 Chroma POWER_VIHL_ON（VIL45/VIH55、VOL33/VOH67）；
    # TODO 后续两平台同步改成从母本 limit 列读上下限。仅在该 CP 真有 DC_VIHVIL_Test 行时写。
    _cp_suffix_vihvil = code_name[G.i].split("_")[-1]
    if any(item == "DC_VIHVIL_Test" and cp == _cp_suffix_vihvil
           for item, cp in zip(G.col("FLOW", "item"), G.col("FLOW", "CP NO"))):
        f.write("@@MACRO POWER_ON_VIHVIL(double _C_vccVolt)\n")
        f.write("	LOGIC_SET_DRV_LEVEL(IO_ALLPINS, 0.0V, 0.0V, 0.0V, VR1);\n")
        f.write("	LOGIC_SET_CMP_LEVEL(IO_ALLPINS, 0.0V, 0.0V,VR2);\n")
        f.write("	LOGIC_SET_DRV_LEVEL(TP, 0.0V, 0.0V, 0.0V, VR1);\n")
        f.write("	LOGIC_SET_CMP_LEVEL(TP, 0.0V, 0.0V,VR2);\n")
        for v in range(len(vccpin)):
            f.write("	LOGIC_FORCE_DPS(" + vccpin[v] + ", 0.0V, 500MA, I7, WAIT=0.5MS);\n")
        f.write("	WAIT(5MS);\n")
        for v in range(len(vccpin)):
            f.write("	LOGIC_CLOSE_DPS_OUTPUT_RELAY(" + vccpin[v] + ",ON,WAIT=0.5MS); \n")
        for v in range(len(vccpin)):
            f.write("	LOGIC_FORCE_DPS(" + vccpin[v] + ", _C_vccVolt, 500MA, I7, WAIT=0.5MS);\n")
        # VIL/VIH 半摆驱动 + VOL/VOH 比较窗口（对齐 Chroma POWER_VIHL_ON 的百分比）。
        f.write("	LOGIC_SET_DRV_LEVEL(IO_ALLPINS, _C_vccVolt*0.55, _C_vccVolt*0.45, 0.0V, VR1);\n")
        f.write("	LOGIC_SET_CMP_LEVEL(IO_ALLPINS, _C_vccVolt*0.67, _C_vccVolt*0.33, VR2);\n")
        f.write("	LOGIC_SET_DRV_LEVEL(TP, _C_vccVolt, 0.0V, 0.0V, VR1);\n")
        f.write("	LOGIC_SET_CMP_LEVEL(TP,0.8,0.3,VR2);\n")
        f.write("	LOGIC_CLOSE_PE_RELAY(IO_ALLPINS,WAIT=0.5MS);\n")
        f.write("	WAIT(10MS);\n\n")
        f.write("@@END_MACRO \n\n")

    # //////////////////////////////////////////////power_on 写入end/////////////////////////////////////////////

    # //////////////////////////////////////////////power_shmoo_on 写入start////////////////////////////////////////////

    # //////////////////////////////////////////////power_off 写入start////////////////////////////////////////////
    f.write("@@MACRO POWER_OFF()\n")
    f.write(
        "	LOGIC_SET_DRV_LEVEL(IO_ALLPINS, 0.0V, 0.0V, 0.0V, VR1); \n	LOGIC_SET_CMP_LEVEL(IO_ALLPINS, 0.0V, 0.0V, VR2);\n	WAIT(20MS);\n")
    f.write("	LOGIC_DISCONNECT_PPMU_PIN(IO_ALLPINS);\n")
    f.write("	LOGIC_CLOSE_PE_RELAY(NULL,WAIT=0.5MS);\n")
    for v in range(len(vccpin)):
        f.write("	LOGIC_FORCE_DPS(" + vccpin[v] + ", 0.0V, 500MA, I7, WAIT=0.5MS);\n")
    f.write("	WAIT(10mS);\n")
    for v in range(len(vccpin)):
        f.write("	LOGIC_CLOSE_DPS_OUTPUT_RELAY("+vccpin[v]+",OFF,WAIT=0.5MS); \n")
    f.write("	WAIT(5mS);\n")
    f.write("	LOGIC_CLOSE_PMU_RELAY(NULL,WAIT=0.5MS);\n")
    f.write("	WAIT(5mS);\n\n")

    f.write("@@END_MACRO \n\n")
    # //////////////////////////////////////////////power_off 写入end/////////////////////////////////////////////

    # SRAM capture 的 Read_SRAM(address) 全局函数（仅本 CP 有 UNIT=cap+cap_cfg=SRAM 行时写）。
    _read_sram_write(code_name, f)

    f.write(
        "//////////////////////////////////////////////////////////////////\n//\n"
        + "//           Sub Flow\n//\n//////////////////////////////////////////////////////////////////\n\n")
