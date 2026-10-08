# Chroma 平台：.pln 程序框架（变量声明、bin 定义、启动代码、TEST_PRO）。
import os
from program_gen.core.clock_force import chroma_ts3_half_period_ns as clock_ts3_half_period_ns
from program_gen.core.pattern_data import reuse_dac_restore_items
from program_gen.platforms.chroma.pattern_files import copy_file
from program_gen.platforms.chroma.project_files import VCC_pin_rebuild, cp_has_kp_relay
from program_gen.platforms.chroma.dc_scan_writer import DC_SCAN_ITEMS
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
    # 不选中的下标直接跳过，不会用 'w' 截断它已有的 .pln（否则会把没选中的 CP 清空成空壳）。

    for i in range(len(G.col("VERSION", "Program Name"))):
        if only is not None and i not in only:
            continue
        os.makedirs(G.OUT_DIR + "\\" + code_name[i], exist_ok=True)
        os.makedirs(G.OUT_DIR + "\\" + code_name[i]+"\\pat", exist_ok=True)
        build_uid_startup = _build_uid_startup_plan(G.col("VERSION", "CP num")[i])
        # pin dec 由 dec_file_created 直接生成到本程序的 pat/ 文件夹，不再经 pat_temp 复制
        copy_file(G.BASE_DIR + "\\pat_temp\\" + "enter_fbist_mode" + ".pat",
                  G.OUT_DIR + "\\" + code_name[i]+"\\pat")
        copy_file(G.BASE_DIR + "\\pat_temp\\" + "exit_fbist_mode" + ".pat",
                  G.OUT_DIR + "\\" + code_name[i]+"\\pat")

        with open(G.OUT_DIR + "\\" + code_name[i] + "\\"+ code_name[i] + ".pln", 'w') as f:
            f.write(
                "////////////////////////////////////////////////////////////////////////////////////////////////\n// UPDATE LOG\n"
                + "// " + str(code_name[i].split("_")[-4]) + "_" + str(code_name[i].split("_")[-3]) + " version\n//\n////////////////////////////////////////////////////////////////////////////////////////////////\n\n")
            f.write("#include <time.h>\n#include <math.h>\n#include <stdint.h>\n\n")
            f.write('SET_DEC_FILE ".\PAT\pin.dec"\n\n')
            f.write('GLOBAL int LIST_TEST_TIME = 0;\n\n')
            f.write('const int MAX_SITE = ' + code_name[i].split("_")[-2].split("S")[0] + ';\n\n')
            f.write('int BIT[64];\nint I,J,K;\nuint32_t TEMP;\nint TRIM_DIGIT;\n\n')
            if G.col("VERSION", "CP num")[i] != "CP1":
                f.write('int CP' + str(int(G.col("VERSION", "CP num")[i][
                                               -1]) - 1) + '_BAKEID_FLAG[MAX_SITE];\nint TEMP_DATA[1024];\nint CAP_DATA[MAX_SITE];\n\n')
            f.write(
                'int RST_LVL     = 1;\nint MIN_LVL     = 2;\nint TYP_LVL     = 3;\nint MAX_LVL     = 4;\nint SHMOO_LVL   = 5;\n\n')
            # VIHL_LVL（DC_VIHVIL_Test 用的 POWER_VIHL_ON 里 SET_LEVELN 引用）—
            # 固定用 9 号位（CP1/CP2 的 PDR_*_LVL 最多用到 8，9 一定空闲），只在
            # 该 CP 真有 DC_VIHVIL_Test 行时才声明（2026-07-14）。
            if any(item == "DC_VIHVIL_Test" and cp == G.col("VERSION", "CP num")[i]
                   for item, cp in zip(G.col("FLOW", "item"), G.col("FLOW", "CP NO"))):
                f.write('int VIHL_LVL    = 9;\n\n')
            if G.col("VERSION", "CP num")[i] == "CP1":
                f.write('int PDR_MIN_LVL = 6;\nint PDR_TAR_LVL = 7;\nint PDR_MAX_LVL = 8;\n\n\n')
                f.write('VOLTAGE VCC_PDR_MIN = ' + str(G.col("VERSION", "pdr min")[i]) + 'V;\nVOLTAGE VCC_PDR_TAR = ' +
                        str(G.col("VERSION", "pdr target")[i]) + 'V;\nVOLTAGE VCC_PDR_MAX = ' + str(
                    G.col("VERSION", "pdr max")[i]) + 'V;\n\n\n')
            if G.col("VERSION", "CP num")[i] == "CP2":
                f.write('int PDR_MIN_LVL = 6;\nint PDR_MAX_LVL = 7;\nint PDR_CHECK_LVL = 8;\n\n\n')
                f.write('VOLTAGE VCC_PDR_MIN = ' + str(
                    G.col("VERSION", "pdr min")[i]) + 'V;\nVOLTAGE VCC_PDR_MAX = ' + str(
                    G.col("VERSION", "pdr max")[i]) + 'V;\n\n\n')
            if build_uid_startup is not None:
                f.write('\n\n//test condition\n')
                f.write('int CP_VERNO= ' + str(G.col("VERSION", "CP spec")[i]) + ';\n')
                f.write('int CP1_VERSION= ' + str(G.col("VERSION", "CP ver high")[i]) + ';\n')
                f.write('int CP2_VERSION= ' + str(G.col("VERSION", "CP ver low")[i]) + ';\n')
                f.write('int PROJECT_NAME= ' + str(G.col("VERSION", "project name")[i]) + ';\n')
                f.write('int PROJECT_VERSION= ' + str(G.col("VERSION", "project ver")[i]) + ';\n')
                f.write('int TESTING_HOUSE_ID = ' + "'" + code_name[i].split("_")[0] + "'" + ';\n\n\n')

            f.write('VOLTAGE VCC_MIN = ' + str(G.col("VERSION", "vcc min")[i]) + 'V;\nVOLTAGE VCC_TYP = ' + str(
                G.col("VERSION", "vcc typ")[i]) + 'V;\nVOLTAGE VCC_MAX = '
                    + str(G.col("VERSION", "vcc max")[i]) + 'V;\n\n')
            f.write('TIME FSCLK_TYP   = 200nS; //TS1\nTIME FSCLK_500K  = 2000nS;//TS2\n\n')
            f.write('TIME FSCLK_ERASE = ' + str(
                int((G.col("VERSION", "erase time(ms)")[i] / 0.0125) + 0.5)) + 'nS;//TS5  200ns=erase 2.5ms\n')
            f.write('TIME FSCLK_PGM   = ' + str(
                int((G.col("VERSION", "program time(ms)")[i] / 0.0075) + 0.5)) + 'nS;//TS6    200ns=pgm 1.5ms\n\n')
            # TS3：RCC/RTC 外灌时钟 Chroma"同 PMU 组"降级分支专用（2026-07-07 用户
            # 裁决号位），只在这个 CP 真有降级需求时才声明——没有 clkloop pattern 会
            # 引用它，声明了也没用，且能在没需求时保持 TS3 空号（对齐续4 的现状盘点）。
            _ts3_half_ns = clock_ts3_half_period_ns(G.col("VERSION", "CP num")[i])
            if _ts3_half_ns is not None:
                f.write('TIME FSCLK_FORCE = ' + str(round(_ts3_half_ns, 2)) + 'nS;//TS3  外灌时钟 pattern 降级用\n\n')
            if G.col("VERSION", "CP num")[i] == "CP1" or G.col("VERSION", "CP num")[i] == "CP2":
                f.write(
                    'VOLTAGE VTE_VOLTAGE = ' + str(G.col("VERSION", "VTE target")[i]) + 'V;\nVOLTAGE VTP_VOLTAGE = ' +
                    str(G.col("VERSION", "VTP target")[i]) + 'V;\n\n')
            if G.col("VERSION", "CP num")[i] == "CP2" or G.col("VERSION", "CP num")[i] == "CP3":
                f.write('VOLTAGE VTE_BAKE_VOLTAGE = ' + str(
                    G.col("VERSION", "VTE bake target")[i]) + 'V;\nVOLTAGE VTP_BAKE_VOLTAGE = ' +
                        str(G.col("VERSION", "VTP bake target")[i]) + 'V;\n\n')

            if G.col("VERSION", "CP num")[i] == "CP1" or G.col("VERSION", "CP num")[i] == "CP2":
                f.write('double VPOSE_TAR = ' + str(G.col("VERSION", "vpose")[i]) + ';\ndouble VNEGE_TAR = ' +
                        str(G.col("VERSION", "vnege")[i]) + ';\ndouble VPOSP_TAR = ' + str(
                    G.col("VERSION", "vposp")[i]) + ";\ndouble VNEGP_TAR = "
                        + str(G.col("VERSION", "vnegp")[i]) + ";\n\n")
            if build_uid_startup is not None:
                f.write('char WAFERID[32], LOT_ID[32] ;\nint WAFER_SLOT;\nint LOAD_ID_FLAG;\n\n')

            f.write('int TEST_NUM;\nint X_CO[MAX_SITE],Y_CO[MAX_SITE];\n\n')
            f.write('int VTEN_FLAG = 0;\n\n')


def item_variable_created(
    code_name, cp_num, f, dac_write_plans=None, result_export_plans=None,
    addr_map_catalog=None,
):
    # //////////////////////////////////////////////item variable 写入start//////////////////////////////////////////////
    G.i = cp_num
    flag = 0
    num_flag = 0
    CP_NUM = []
    page_word = G.col("VERSION", "page word")[0]

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
            # 对齐 S100：VCSL/VNEG2/VBL 仅在 FLOW 没有对应 Trim 项时才硬编码；
            # 若 FLOW 已有（如 Vbl_Trim）则由上面的循环生成，避免 C2086 重复定义。
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

        if code_name[G.i].split("_")[-1][-1] in G.col("ADDR_MAP", "line")[cyc * (page_word+1)] and "lable" in G.col("ADDR_MAP", "data type")[0 + page_word * cyc:page_word + page_word * cyc] and addr_map_item[cyc] != "uid":

            f.write("//" + addr_map_item[cyc] + "(1 page = 32 words = 128 bytes = 1Kbits)\n")
            flag = 0
            num_flag = 0
            for j in range(len(G.col("ADDR_MAP", "data type"))):
                if G.col("ADDR_MAP", "Word No.")[j] == addr_map_item[cyc]:
                    if G.col("ADDR_MAP", "data type")[j] == "lable" and flag == 0:
                        f.write("int ")
                    if G.col("ADDR_MAP", "data type")[j] == "lable" and flag != 3:
                        if num_flag == G.col("ADDR_MAP", "data type")[0 + page_word * cyc:page_word + page_word * cyc].count("lable")-1:
                            f.write(
                                "REG_" + str(G.col("ADDR_MAP", "bit[15:0]")[j].split("[")[0].upper()) + "[MAX_SITE];\n")
                        else:
                            f.write("REG_" + str(G.col("ADDR_MAP", "bit[15:0]")[j].split("[")[0].upper()) + "[MAX_SITE],")
                            flag += 1
                            num_flag += 1

                    elif G.col("ADDR_MAP", "data type")[j] == "lable":
                        f.write("REG_" + str(G.col("ADDR_MAP", "bit[15:0]")[j].split("[")[0].upper()) + "[MAX_SITE];\n")
                        flag = 0
                        num_flag += 1
            f.write("\n")
    # 本 CP 需要声明的 uid 寄存器/校验变量名（按首次出现顺序去重）。原先靠
    # "item 名字 -> 字典" 统计各 CP 数量再用计数器猜"跑到第几个该收尾"的写法，
    # 遇到同一个 item 名字跨多个 CP 出现（如 Hsi_8M_Trim 在 CP1/CP3 都是
    # UID==yes）时，字典按名字覆盖导致计数错位——CP3 会把 CP1、CP3 两行都原样
    # 声明一遍（C2086 重复定义），CP1 又会因计数提前触顶而漏声明后面的项
    # （C2065 未声明标识符，如 VREFBUF2P048_W）。这里直接按最终变量名去重，
    # 不再依赖那份计数逻辑，两个症状同一次改掉。
    cp_digit = int(code_name[G.i].split("_")[-1][-1])
    seen_uid_names = set()
    uid_names = []
    if addr_map_catalog is None:
        if G.compiled_adapter is None:
            raise RuntimeError("compiled adapter must be installed before rendering")
        addr_map_catalog = G.compiled_adapter.addr_map_catalog
    for j in range(len(G.col("FLOW", "item"))):
        if G.col("FLOW", "UID")[j] != "yes":
            continue
        if int(G.col("FLOW", "CP NO")[j][-1]) > cp_digit:
            continue
        flow_type_j = G.col("FLOW", "type")[j]
        if flow_type_j == "trim":
            # A logical Trim field can land in several physical registers.
            # UID/BUILDUID consumes the UID page image, so declare its real
            # ADDR_MAP register instead of guessing from the FLOW item name.
            names = [
                "REG_" + field.register.upper()
                for field in addr_map_catalog.resolve_fields(
                    G.col("FLOW", "item")[j]
                )
                if field.page.casefold() == "uid"
            ]
        elif flow_type_j == "verify":
            names = [
                generated_flow_item_name(G.FLOW, j).split("Verify")[0].upper() + "W"
            ]
        else:
            continue
        for name in names:
            if name not in seen_uid_names:
                seen_uid_names.add(name)
                uid_names.append(name)

    f.write("//uid(1 page = 32 words = 128 bytes = 1Kbits)\n")
    for idx, name in enumerate(uid_names):
        if idx % 4 == 0:
            f.write("int ")
        sep = ";\n" if (idx % 4 == 3 or idx == len(uid_names) - 1) else ","
        f.write(name + "[MAX_SITE]" + sep)
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
        # 对齐 S100 与 CP1 路径：VCSL/VNEG2/VBL 仅在 PUMP 循环未生成对应项时才硬编码，
        # 避免 C2086 重复定义（如 Vbl_Trim 的 PUMP==yes 已由上面循环生成 VBL_DAC_FINAL）。
        pump_items = [generated_flow_item_name(G.FLOW, j).split("Trim")[0].upper().rstrip("_")
                      for j in range(len(G.col("FLOW", "item")))
                      if G.col("FLOW", "PUMP")[j] == "yes"]
        vars_to_write = [var + "_DAC_FINAL[MAX_SITE]" for var in ["VCSL", "VNEG2", "VBL"]
                         if var not in pump_items]
        if vars_to_write:
            f.write("int " + ",".join(vars_to_write) + ";\n\n\n")
        else:
            f.write("\n\n")

        # 跨 CP 复用 dac 补值的变量（如 CP3 复用 CP1 已 trim 好的 Hsi_Vrega，本 CP 没有
        # 对应 Trim 步骤，需要单独声明 *_DAC_FINAL 接住从 EPR 读回算出的值，见
        # program_gen.core.pattern_data.reuse_dac_restore_items）。
        restore_items = reuse_dac_restore_items(code_name[G.i].split("_")[-1])
        restore_vars = [dac_final_symbol(item) + "[MAX_SITE]" for item in restore_items]
        if restore_vars:
            f.write("//reuse dac 补值 write variable\n")
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


def _canonical_bin_definition(schedule, entry):
    definitions = {item.identity: item for item in schedule.definitions}
    binding = entry.bin_binding
    if binding.kind is BinBindingKind.DIRECT:
        return definitions[entry.definition_id], binding
    if binding.kind is BinBindingKind.DEFINITION_REFERENCE:
        return definitions[binding.definition_id], binding
    raise ValueError(f"unsupported canonical bin binding: {binding.kind!r}")


def _canonical_hardware_software_bins(f, schedule):
    direct_entries = tuple(
        entry for entry in schedule.entries
        if entry.bin_binding.kind is BinBindingKind.DIRECT
        and entry.placement == "BOOKED"
    )
    for prefix, attr in (("hw_", "hardware_bin"), ("sw_", "software_bin")):
        f.write(("HW_BIN_DEF" if prefix == "hw_" else "SW_BIN_DEF")
                + "\n{\n    all_pass                              = 1;\n")
        emitted = set()
        for entry in direct_entries:
            definition, binding = _canonical_bin_definition(schedule, entry)
            if definition.identity in emitted:
                continue
            rendered_name = definition.render_name + " " * max(
                0, 35 - len(definition.render_name)
            )
            f.write(
                f"    {prefix}{rendered_name}=!{getattr(binding, attr)};\n"
            )
            emitted.add(definition.identity)
        f.write("\n\n    fail_last_item_test                   =!255;\n}\n\n\n\n")


def _canonical_test_pro(schedule):
    emitted = set()
    for entry in schedule.entries:
        if entry.placement != "BOOKED":
            continue
        if entry.identity in emitted:
            continue
        definition, _binding = _canonical_bin_definition(schedule, entry)
        item = ("//" if not entry.enabled else "") + entry.render_name
        bin_name = definition.render_name
        item_field = item + " " * max(0, 34 - len(item))
        hw_field = " " * 23 + ": #C(hw_" + bin_name + " " * max(0, 35 - len(bin_name))
        sw_field = bin_name + " " * max(0, 35 - len(bin_name))
        G.f.write(f"    {item_field}?{hw_field},sw_{sw_field});\n")
        emitted.add(entry.identity)


def Hw_Sw_Bin(code_name, f, *, canonical_schedule=None):
    if canonical_schedule is not None:
        _canonical_hardware_software_bins(f, canonical_schedule)
        return
    trash = []
    # //////////////////////////////////////////////item 分bin 写入start//////////////////////////////////////////////
    f.write("HW_BIN_DEF\n{\n    all_pass                              = 1;\n")

    for j in range(len(G.col("FLOW", "item"))):
        s = G.col("FLOW", "item")
        s[j] = generated_flow_item_name(G.FLOW, j)
        if len(s[j]) < 40:
            s[j] += " " * (35 - len(s[j]))
        if G.col("FLOW", "CP NO")[j] == code_name[G.i].split("_")[-1]:
            if s[j].title() + G.col("FLOW", "CP NO")[j] not in trash:
                f.write("    " + "hw_" + s[j].title() + "=!" + str(G.col("FLOW", "Hbin")[j]) + ";" + "\n")
                trash.append(s[j].title() + G.col("FLOW", "CP NO")[j])
    f.write("\n\n    fail_last_item_test                   =!255;\n")
    f.write("}" + "\n" * 4)
    trash.clear()
    f.write("SW_BIN_DEF\n{\n    all_pass                              = 1;\n")
    for j in range(len(G.col("FLOW", "item"))):
        s = G.col("FLOW", "item")
        s[j] = generated_flow_item_name(G.FLOW, j)
        if len(s[j]) < 40:
            s[j] += " " * (35 - len(s[j]))
        if G.col("FLOW", "CP NO")[j] == code_name[G.i].split("_")[-1]:
            if s[j].title() + G.col("FLOW", "CP NO")[j] not in trash:
                f.write("    " + "sw_" + s[j].title() + "=!" + str(G.col("FLOW", "Sbin")[j]) + ";" + "\n")
                trash.append(s[j].title() + G.col("FLOW", "CP NO")[j])
    f.write("\n\n    fail_last_item_test                   =!255;\n")
    f.write("}" + "\n" * 4)


def TEST_PRO(code_name, trim_specs=None, *, canonical_schedule=None):
    G.f.write("last_item_test()\n{\n")
    G.f.write('    printf("last item test finished !!");\n')
    G.f.write("}\n\n")
    G.f.write("TEST_PRO{\n  BEFORE_TEST: test_start;\n")
    if canonical_schedule is not None:
        _canonical_test_pro(canonical_schedule)
        G.f.write(
            "    last_item_test                    ?#C(all_pass,all_pass)  : #C(fail_last_item_test                   ,fail_last_item_test                   );\n"
        )
        G.f.write("AFTER_TEST: test_end;\n\n")
        G.f.write("}\n")
        return
    w = []
    b = []
    q = []
    trash = []
    if trim_specs is None:
        if G.compiled_adapter is None:
            raise RuntimeError("compiled adapter must be installed before rendering")
        trim_specs = G.compiled_adapter.trim_specs
    for j in range(len(G.col("FLOW", "item"))):
        from program_gen.platforms.chroma.comp_writer import is_comp_row, package_cases
        if is_comp_row(j):
            pat_dir = G.OUT_DIR + "\\" + code_name[G.i] + "\\pat"
            if not package_cases(j, pat_dir):
                continue
        # 2026-07-05 用户裁决：FLOW.item 灰色标记（G.flow_row_flag=="comment_out"）表示
        # 这个测试项在 TEST_PRO 调度表里整行注释掉——跟 Bisection=="both_m" 时给 DacLoop
        # 变体加 "//" 是同一约定（"//" 出现在行首后，同一行剩余的 "?...:#C(...)" 全部失效）。
        row_commented = G.flow_row_flag(j) == "comment_out"
        generated_item = generated_flow_item_name(G.FLOW, j)
        trim_spec = trim_specs.get(j)
        if trim_spec is not None:
            for variant in trim_spec.search.variants:
                if variant.kind == "FULL_SCAN":
                    scheduled_item = generated_item.split("Trim")[0].title() + "Dac_Loop"
                else:
                    scheduled_item = generated_item.title()
                commented = row_commented or not variant.scheduled
                w.append(("//" if commented else "") + scheduled_item)
                q.append(generated_item.title())
                b.append(G.col("FLOW", "CP NO")[j])
        else:
            w.append(("//" if row_commented else "") + generated_item.title())
            q.append(generated_item.title())
            b.append(G.col("FLOW", "CP NO")[j])
        if trim_spec is None and (G.col("FLOW", "Bisection")[j] == "both" or G.col("FLOW", "Bisection")[j] == "both_m"):
            if G.col("FLOW", "Bisection")[j] == "both_m" or row_commented:
                w.append("//"+generated_item.split("Trim")[0].title() + "Dac_Loop")
            else:
                w.append(generated_item.split("Trim")[0].title() + "Dac_Loop")
            q.append(generated_item.title())
            b.append(G.col("FLOW", "CP NO")[j])

    for j in range(len(w)):
        s = w[j]
        o = q[j]
        v = q[j]

        if len(w[j]) < 40:
            s += " " * (34 - len(w[j]))
            v += " " * (35 - len(q[j]))
            o = " " * 23 + ": #C(hw_" + o + " " * (35 - len(q[j]))
        if b[j] == code_name[G.i].split("_")[-1]:
            if s + b[j] not in trash:
                G.f.write("    " + s + "?" + o + "," + "sw_" + v + ");" + "\n")
                trash.append(s + b[j])
    # OTP_READ debug 项接入 TEST_PRO 末尾；HW/SW bin 复用当前 CP 的 Pgm_CpXId_Read（用户裁决 2026-06-24）
    cpid = "Pgm_Cp" + code_name[G.i].split("_")[-1][-1] + "Id_Read"
    G.f.write("    OTP_Read" + " " * (34 - len("OTP_Read")) + "?" + " " * 23 + ": #C(hw_" + cpid
              + " " * (35 - len(cpid)) + "," + "sw_" + cpid + " " * (35 - len(cpid)) + ");\n")
    # NM_Data_Read debug 项接入 TEST_PRO（无条件，HW/SW bin 同复用 Pgm_CpXId_Read）
    G.f.write("    NM_Data_Read" + " " * (34 - len("NM_Data_Read")) + "?" + " " * 23 + ": #C(hw_" + cpid
              + " " * (35 - len(cpid)) + "," + "sw_" + cpid + " " * (35 - len(cpid)) + ");\n")
    G.f.write(
        "    last_item_test                    ?#C(all_pass,all_pass)  : #C(fail_last_item_test                   ,fail_last_item_test                   );\n")
    G.f.write("AFTER_TEST: test_end;\n\n")
    G.f.write("}\n")


def _dc_group_helper_write(code_name, f):
    """F2（DC扫描族）管脚组运行时循环用的辅助函数（2026-07-13 用户提供新写法，
    见 temp/DC/Chroma 示例代码）：`GetPinbyName` 封装 Chroma 内置
    `GetPinChannel`/`GetPGChannel`，按字符串名字（如 "DC1_pins"）在运行时反查
    该 `PIN_GROUP` 的通道数组，`dc_scan_writer.py` 的 `_dc_group_loop` 靠这个
    在 `.pln` 里写一个紧凑的 `for` 循环（不用像原来那样按管脚组数在 Python 侧
    展开成 N 段重复代码）。只在该 CP 的 FLOW 里真的有 `DC_SCAN_ITEMS` 测试项
    时才写这段（Chroma only，不需要的产品不必背这几行）。"""
    flow_item = G.col("FLOW", "item")
    flow_cp = G.col("FLOW", "CP NO")
    cp_no = code_name[G.i].split("_")[-1]
    if not any(item in DC_SCAN_ITEMS and cp == cp_no for item, cp in zip(flow_item, flow_cp)):
        return
    # 2026-07-13 用户裁决：原样照抄示例（temp/DC/Chroma 示例代码），声明用
    # 混合大小写 MT_Group_Pins/MT_Group_PinsCnt，不要自己"统一大小写"——
    # 用户已经真实编译验证过这份代码，调用处（RELAY_ON 等）用全大写
    # MT_GROUP_PINS 是示例原文本来就有的写法，不是笔误。
    f.write(
        "int *MT_Group_Pins,MT_Group_PinsCnt=0;\n"
        "int GetPinbyName(char *name)\n"
        "{\n"
        "  MT_Group_PinsCnt = GetPinChannel(name,MT_Group_Pins);\n"
        "  if(MT_Group_PinsCnt == -1) MT_Group_PinsCnt = GetPGChannel(name,MT_Group_Pins);\n"
        "  return MT_Group_PinsCnt;\n"
        "}\n\n"
    )


def _has_sram_cap(cp_no):
    """本 CP 是否有 SRAM capture 行（UNIT=cap 且 cap_cfg pattern 段=SRAM）。"""
    flow_cp = G.col("FLOW", "CP NO")
    flow_unit = G.col("FLOW", "UNIT")
    flow_cap = G.col("FLOW", "cap_cfg")
    for k in range(len(flow_cp)):
        if flow_cp[k] == cp_no and str(flow_unit[k]).strip().lower() == "cap" \
                and str(flow_cap[k]).strip().split("-")[0].upper() == "SRAM":
            return True
    return False


def _read_sram_write(code_name, f):
    """Read_SRAM(address) 全局函数：SWD 读 SRAM 一个字（2026-07-16 用户提供
    temp/ADC/SRAM_函数.txt 的改地址算法 + capture 读取补全）。模板 sram_cpature.pat 是
    手工种子（copy_file 拷入程序 pat/），运行时 WRITE_PAT_MEM 改 addr（低 16 位地址）+
    parity（popcount+1 取奇偶），JUDGE_PAT 跑、READ_CAPTURE_MEM_BLOCK 读回 32 bit
    （LSB first 拼、跳 8=don't care）存 sram_data[SOCKET]（多工位各一份）。SET_CAPTURE
    由调用方在外面开关（用户裁决）。只在该 CP 有 UNIT=cap + cap_cfg=SRAM 行时写。"""
    cp_no = code_name[G.i].split("_")[-1]
    if not _has_sram_cap(cp_no):
        return
    swd = G.col("VERSION", "SWD PIN")[G.i]
    f.write("int sram_data[MAX_SITE];\n")
    f.write("void Read_SRAM(int address)\n{\n")
    f.write("  int cnta=0, parity=0, temp_sram[64];\n\n")
    f.write("  SET_CAPTURE_MEM_MODE(" + swd + ", PEL_K, ON, 32K);\n\n")
    f.write("  cnta=0; for(int x=address;x;x&=x-1) cnta++; parity=(cnta+1)&1;\n")
    f.write("  TEMP = address;\n")
    f.write("  for(J=0;J<=15;J++){ BIT[J]=0; BIT[J]=TEMP%2; TEMP=TEMP/2; }\n")
    # 非 run-pattern 指令（WRITE_PAT_MEM/READ_CAPTURE）用 SOCKET，须包在 SOCKET_INC 里
    # 提供上下文（2026-07-16 用户裁决）；JUDGE_PAT（run pattern）留在外面全工位跑一次。
    f.write("  SOCKET_INC(FRZ_OFF)\n  {\n")
    f.write("    for(J=15;J>=0;J--)\n    {\n")
    f.write('      if(BIT[J]==0) WRITE_PAT_MEM(SOCKET, ' + swd + ', sram_cpature:addr+J, ,"0");\n')
    f.write('      else WRITE_PAT_MEM(SOCKET, ' + swd + ', sram_cpature:addr+J, ,"1");\n')
    f.write("    }\n")
    f.write('    if(parity==0) WRITE_PAT_MEM(SOCKET, ' + swd + ', sram_cpature:parity, ,"0");\n')
    f.write('    else WRITE_PAT_MEM(SOCKET, ' + swd + ', sram_cpature:parity, ,"1");\n')
    f.write("  }\n")
    f.write("  TEST_NUM++;\n")
    f.write('  TEST_NO(TEST_NUM); DATALOG_MSG="sram_cpature";\n')
    f.write("  JUDGE_PAT(sram_cpature,__sram_cpature);\n")
    f.write("  SOCKET_INC(FRZ_OFF)\n  {\n")
    f.write("    READ_CAPTURE_MEM_BLOCK(SOCKET, " + swd + ", 0, 31, temp_sram);\n")
    f.write("    sram_data[SOCKET]=0;\n")
    f.write("    for(J=0;J<32;J++) if(temp_sram[J]!=8) sram_data[SOCKET] += temp_sram[J]<<J;\n")
    f.write("  }\n\n")
    f.write("  SET_CAPTURE_MEM_MODE(" + swd + ", PEL_K, OFF, 32K);\n")
    f.write("}\n\n")


def _power_vihl_on_write(f, cp_no, vccpinnames):
    """DC_VIHVIL_Test（VIL/VIH 阈值测试）用的 `POWER_VIHL_ON` 自定义函数
    （2026-07-14，见 .Codex/handoffs/2026-07-07-analog-test-family-
    classification-decision.md）——参考真实老产品 `temp/fast/
    V_PY2113V1C_....pln:398` 的写法，但两处按用户裁决改成本项目通用机制：
    ① 电源轨改用本项目已有的 `vccpinnames`（`VCC_pin_rebuild`/
    `vcc_rails_str` 同源，跟 `POWER_ON`/`POWER_Shmoo_ON` 用同一个变量），
    不写死参考程序里的 `VBAT`/`VCC`/`VREF` 三个固定轨名；
    ② `PIN_MODE(<CLK PIN>, RZ, ...)` 改成 `NRZ`（VIL/VIH 测试要把 SCLK 管脚
    当普通 GPIO 驱动/读取，不能停在 RZ 触发模式——跟 `_keil_step_write` 的
    HL 分支"触发管脚撞上 CLK PIN 时先切回 NRZ"是同一条道理）。结构基本照抄
    `POWER_Shmoo_ON`（同样先 `RELAY_ON`+`FORCE_V_MLDPS`+blanket NRZ，只是
    `SET_LEVELN` 换成 VIH/VIL 阈值电平：VOL=33%、VOH=67%、VIL=45%、
    VIH=55%、VT=50%）。只在该 CP 真有 `DC_VIHVIL_Test` 行时才写。"""
    flow_item = G.col("FLOW", "item")
    flow_cp = G.col("FLOW", "CP NO")
    if not any(item == "DC_VIHVIL_Test" and cp == cp_no for item, cp in zip(flow_item, flow_cp)):
        return
    f.write("POWER_VIHL_ON(double vccVolt)\n{\n")
    f.write("   RELAY_ON(IO_ALLPINS, PDCL, 2mS);\n")
    f.write("   FORCE_V_MLDPS(" + vccpinnames + ", vccVolt,@6V,@500mA,200mA,NORM,ON,2mS);\n\n")
    f.write("   PIN_MODE(IO_ALLPINS,NRZ, EDGE, ENABLE, IO_NRZ, OFF);\n")
    f.write("   PIN_MODE(      " + G.col("VERSION", "CLK PIN")[G.i] + ", NRZ, EDGE, ENABLE, IO_NRZ, OFF);\n\n")
    f.write(
        "   SET_LEVELN(VIHL_LVL, IO_ALLPINS, vccVolt*0.33, vccVolt*0.67, vccVolt*0.45, vccVolt*0.55, 0uA, 0uA, vccVolt*0.5, , );\n\n")
    f.write("   LEVELS(VIHL_LVL, 3mS);\n")
    f.write("   WAIT(10mS);\n")
    f.write("}\n\n")


def start_up_write(code_name, f):
    build_uid_startup = _build_uid_startup_plan(code_name[G.i].split("_")[-1])
    # //////////////////////////////////////////////start up 写入start//////////////////////////////////////////////
    f.write("START_UP()\n{\n")
    f.write(
        "   SET_LEVELN(RST_LVL, IO_ALLPINS, 0.0V, 0.0V, 0.0V, 0.0V, 0.0mA, 0.0mA, 0.0V,, );\n   LEVELS(RST_LVL, 3mS);\n   WAIT(20mS);\n")
    for j in range(0, 4):
        f.write("   RATEN(" + list(G.fclk_ts.values())[j] + "," + list(G.fclk_ts.keys())[j] + ");\n")
        f.write("   MARKERN(" + list(G.fclk_ts.values())[
            j] + ", IO_ALLPINS,            0nS,            0nS, , 0nS, 0nS, " + list(G.fclk_ts.keys())[
                    j] + " * 0.5," + list(G.fclk_ts.keys())[j] + ");\n")
        f.write(
            "   MARKERN(" + list(G.fclk_ts.values())[j] + ",       " + G.col("VERSION", "CLK PIN")[G.i] + ", " +
            list(G.fclk_ts.keys())[j] + "*0.25, " + list(G.fclk_ts.keys())[j] + "*0.75" + ", , 0nS, 0nS, " +
            list(G.fclk_ts.keys())[j] + " * 0.5," + list(G.fclk_ts.keys())[j] + ");\n\n")
    # TS3（FSCLK_FORCE）：外灌时钟 pattern 降级号位不在 G.fclk_ts 的 4 个固定 timeplate 里，
    # 上面 range(0,4) 循环覆盖不到——只有 pln_file_created 声明了 TIME FSCLK_FORCE（同一
    # clock_ts3_half_period_ns 条件），这里必须补上对应的 RATEN/MARKERN，否则 <pin>_clkloop
    # 降级 pattern 的 *X*TS3 引用不到周期/驱动沿（2026-07-22 修：TS3 有 TIME 却漏 RATEN/MARKERN，
    # 上机 pattern 外灌 32.768KHz 失败）。格式照 TS1，把 IO_ALLPINS 在拍首(0nS)驱动=clkloop 每拍
    # 保持 *0*/*1* 电平所需。
    if clock_ts3_half_period_ns(G.col("VERSION", "CP num")[G.i]) is not None:
        _clk_pin = G.col("VERSION", "CLK PIN")[G.i]
        f.write("   RATEN(TS3,FSCLK_FORCE);\n")
        f.write("   MARKERN(TS3, IO_ALLPINS,            0nS,            0nS, , 0nS, 0nS, FSCLK_FORCE * 0.5,FSCLK_FORCE);\n")
        f.write("   MARKERN(TS3,       " + _clk_pin + ", FSCLK_FORCE*0.25, FSCLK_FORCE*0.75, , 0nS, 0nS, FSCLK_FORCE * 0.5,FSCLK_FORCE);\n\n")
    f.write("\n")
    for j in range(0, 6):
        if j >= 3 and code_name[G.i].split("_")[-1] == "CP3":
            break
        if j == 4 and code_name[G.i].split("_")[-1] == "CP2":
            continue
        f.write("   SET_LEVELN(" + list(G.lvl_vcc.keys())[j] + ", IO_ALLPINS, 0V, " + list(G.lvl_vcc.values())[
            j] + ", " + list(G.lvl_vcc.values())[j] + "*0.45, " + list(G.lvl_vcc.values())[
                    j] + "*0.55, 0uA, 0uA, " + list(G.lvl_vcc.values())[j] + "*0.5, , );\n")
        if j < 3:
            f.write(
                "   SET_LEVELN(" + list(G.lvl_vcc.keys())[j] + ",         TP, 0V, " + list(G.lvl_vcc.values())[
                    j] + ", 0.3V, 0.8V, 0uA, 0uA, " + list(G.lvl_vcc.values())[j] + "*0.5, , );\n\n")
        else:
            f.write(
                "   SET_LEVELN(" + list(G.lvl_vcc.keys())[j] + ", TP, 0V, " + list(G.lvl_vcc.values())[
                    j] + ", " + list(G.lvl_vcc.values())[j] + "*0.35, " + list(G.lvl_vcc.values())[
                    j] + "*0.5 , 0uA, 0uA, " + list(G.lvl_vcc.values())[j] + "*0.5, , );\n\n")
    f.write('   LOAD_PAT("./PAT/pin_pat.ppo");\n')
    if build_uid_startup is not None:
        f.write('   LOAD_ID_FLAG = 1; //BUILDUID startup cache pending\n')
    f.write("}\n\n")
    # //////////////////////////////////////////////start up 写入end/////////////////////////////////////////////////
    _dc_group_helper_write(code_name, f)
    _read_sram_write(code_name, f)
    # //////////////////////////////////////////////test start 写入start//////////////////////////////////////////////
    f.write("test_start()\n{\n")
    f.write("   for(I=0;I<MAX_SITE;I++)\n   {\n      X_CO[I]=0;\n      Y_CO[I]=0;\n   }\n\n")
    f.write("   READ_PROBER_XY(X_CO,Y_CO);\n\n")
    f.write("   //Y_CO[0]=100;\n")
    # VT margin 使能判定：与 S100 一致，按晶圆分区坐标算 VTEN_FLAG（阈值 57/67/30/29）
    f.write("   if((Y_CO[MAX_SITE-1]>57 && Y_CO[MAX_SITE-1]<67) && X_CO[0]<30)VTEN_FLAG=1;\n")
    f.write("   else if((Y_CO[0]>57 && Y_CO[0]<67) && X_CO[0]>29)VTEN_FLAG=1;\n")
    f.write("   else\n   {VTEN_FLAG=0;}\n")
    f.write("   //VTEN_FLAG=1;\n\n")
    f.write("   SHOW_TEST_TIME(LIST_TEST_TIME);\n\n")
    if build_uid_startup is not None:
        f.write("   ///////////////////////////wafer infor///////////////////////////////\n\n")
        f.write(
            "   if(LOAD_ID_FLAG==1)\n   {\n      READ_WAFER_ID (WAFERID, LOT_ID);\n" + '      printf("WAFER ID = %s , LOT ID = %s(%XH %XH %XH %XH %XH %XH %XH)' + r"\n" + '",WAFERID,LOT_ID,LOT_ID[0],LOT_ID[1],LOT_ID[2],LOT_ID[3],LOT_ID[4],LOT_ID[5],LOT_ID[6]);\n\n')
        f.write(
            "       if(strlen(WAFERID)<10)\n       {\n      " + '    INPUT_BOX("Not found WAFER ID!' + r"\n" + '1. Enter ID and Press OK.' + r"\n+"'2. Press Cancel ande ID will be all 0xFF.' + r"\n" + ')","%s %s", WAFERID , LOT_ID );\n')
        f.write(
            '          printf("Manual INPUT WAFER ID = %s , LOT ID = %s(%XH %XH %XH %XH %XH %XH %XH)' + r"\n" + '",WAFERID,LOT_ID,LOT_ID[0],LOT_ID[1],LOT_ID[2],LOT_ID[3],LOT_ID[4],LOT_ID[5],LOT_ID[6]);\n       }\n')
        f.write(
            "       if(strlen(WAFERID)>10) WAFER_SLOT = ((int)WAFERID[8]-48)*10+((int)WAFERID[9]-48); //WAFERID example AP12972-23-D2\n")
        f.write(
            "       else\n       {\n          WAFER_SLOT = 0xFF;\n          for(I=0;I<7;I++) LOT_ID[I]=0xFF;\n          ABORT_TEST_PLN();\n       }\n")
        f.write("	   if((WAFER_SLOT<1)||(WAFER_SLOT>25))ABORT_TEST_PLN();\n")
        f.write(
            '       printf("Slot No = %d' + r"\n" + '",WAFER_SLOT);\n       fflush(stdout); \n       LOAD_ID_FLAG = 0;\n   }\n\n')
    f.write("}\n\n")

    # //////////////////////////////////////////////test start 写入end//////////////////////////////////////////////
    codenum = ""
    vccpin = []
    vccpinnames = ""
    if code_name[G.i].split("_")[-1] == "CP2":
        codenum = "CP1"
    else:
        codenum = code_name[G.i].split("_")[-1]
    vccpin = VCC_pin_rebuild(codenum)
    for v in range(len(vccpin)):
        if len(vccpin) == 1:
            vccpinnames += vccpin[v]
        elif v != len(vccpin) - 1:
            vccpinnames += vccpin[v] + "+"
        else:
            vccpinnames += vccpin[v]

    # //////////////////////////////////////////////test start 写入start////////////////////////////////////////////
    f.write("test_end()\n{\n")
    f.write(
        "   LEVELS(RST_LVL,3mS);\n   PIN_MODE(IO_ALLPINS,NRZ,EDGE,ENABLE,IO_NRZ,OFF);\n")

    f.write("   FORCE_V_MLDPS(" + vccpinnames + ",0V,@6V,@500mA,200mA,,ON,2mS);\n")
    f.write("   WAIT(5mS);\n")
    f.write("   FORCE_V_MLDPS(" + vccpinnames + ",0V,@6V,@500mA,200mA,,OFF,2mS);\n")
    f.write("   RELAY_OFF(IO_ALLPINS,PDCL,2mS);\n")
    f.write("}\n\n")
    # //////////////////////////////////////////////test start 写入end/////////////////////////////////////////////

    # //////////////////////////////////////////////release 写入start////////////////////////////////////////////
    f.write("RELEASE()\n{\n")
    f.write(
        "   LEVELS(RST_LVL,3mS);\n   PIN_MODE(IO_ALLPINS,NRZ,EDGE,ENABLE,IO_NRZ,OFF);\n")
    f.write("   FORCE_V_MLDPS(" + vccpinnames + ",0V,@6V,@500mA,200mA,,ON,2mS);\n")
    f.write("   WAIT(5mS);\n")
    f.write("   FORCE_V_MLDPS(" + vccpinnames + ",0V,@6V,@500mA,200mA,,OFF,2mS);\n")
    f.write("   RELAY_OFF(IO_ALLPINS,PDCL,2mS);\n")
    f.write("}\n\n")
    # //////////////////////////////////////////////release 写入end/////////////////////////////////////////////

    # //////////////////////////////////////////////power_on 写入start////////////////////////////////////////////
    cp_no = code_name[G.i].split("_")[-1]
    has_kp = cp_has_kp_relay(cp_no)
    f.write("POWER_ON(double vccVolt)\n{\n")
    if (cp_no == "CP1" or cp_no == "CP2") and has_kp:
        f.write("   SET_CBIT(KP, ON, 2mS);\n")
    f.write(
        "   RELAY_ON(IO_ALLPINS, PDCL, 2mS);\n")
    f.write("   FORCE_V_MLDPS(" + vccpinnames + ", vccVolt,@6V,@500mA,200mA,NORM,ON,2mS);\n\n")
    f.write("   PIN_MODE(IO_ALLPINS,NRZ, EDGE, ENABLE, IO_NRZ, OFF);\n")
    f.write("   PIN_MODE(      " + G.col("VERSION", "CLK PIN")[G.i] + ", RZ, EDGE, ENABLE, IO_NRZ, OFF);\n\n")
    f.write("   if(vccVolt==VCC_MIN)\n   {\n")
    f.write("      LEVELS(MIN_LVL, 3mS);\n")
    f.write("   }\n")
    f.write("   else if(vccVolt==VCC_MAX)\n   {\n")
    f.write("      LEVELS(MAX_LVL, 3mS);\n")
    f.write("   }\n")
    f.write("   else\n   {\n")
    f.write("      LEVELS(TYP_LVL, 3mS);\n")
    f.write("   }\n   WAIT(10mS);\n\n")
    f.write("}\n\n")
    # //////////////////////////////////////////////power_on 写入end/////////////////////////////////////////////

    # //////////////////////////////////////////////power_shmoo_on 写入start////////////////////////////////////////////
    f.write("POWER_Shmoo_ON(double vccVolt)\n{\n")
    if (cp_no == "CP1" or cp_no == "CP2") and has_kp:
        f.write("   SET_CBIT(KP, ON, 2mS);\n")
    f.write("   LEVELS(RST_LVL, 3mS);\n")
    f.write("   RELAY_ON(IO_ALLPINS, PDCL, 2mS);\n")
    f.write("   FORCE_V_MLDPS(" + vccpinnames + ", vccVolt,@6V,@500mA,200mA,NORM,ON,2mS);\n\n")
    f.write("   PIN_MODE(IO_ALLPINS,NRZ, EDGE, ENABLE, IO_NRZ, OFF);\n")
    f.write("   PIN_MODE(      " + G.col("VERSION", "CLK PIN")[G.i] + ", RZ, EDGE, ENABLE, IO_NRZ, OFF);\n\n")
    f.write(
        "   SET_LEVELN(SHMOO_LVL, IO_ALLPINS, 0.0V, vccVolt, vccVolt*0.45, vccVolt*0.55, 0uA, 0uA, vccVolt*0.5, , );\n\n")
    f.write("   LEVELS(SHMOO_LVL, 3mS);\n")
    f.write("   WAIT(10mS);\n")
    f.write("}\n\n")
    # //////////////////////////////////////////////power_shmoo_on 写入end/////////////////////////////////////////////

    _power_vihl_on_write(f, cp_no, vccpinnames)

    # //////////////////////////////////////////////power_off 写入start////////////////////////////////////////////
    f.write("POWER_OFF()\n{\n")
    f.write("   LEVELS(RST_LVL,3mS);\n   PIN_MODE(IO_ALLPINS,NRZ,EDGE,ENABLE,IO_NRZ,OFF);\n")
    f.write("   FORCE_V_MLDPS(" + vccpinnames + ",0V,@6V,@500mA,200mA,,ON,2mS);\n")
    f.write("   WAIT(5mS);\n")
    f.write("   FORCE_V_MLDPS(" + vccpinnames + ",0V,@6V,@500mA,200mA,,OFF,2mS);\n")
    f.write("   RELAY_OFF(IO_ALLPINS,PDCL,2mS);\n")
    if (cp_no == "CP1" or cp_no == "CP2") and has_kp:
        f.write("   SET_CBIT(KP, OFF, 2mS);\n")
    f.write("}\n\n")
    # //////////////////////////////////////////////power_off 写入end/////////////////////////////////////////////

    # //////////////////////////////////////////////fail_site_down 写入start////////////////////////////////////////////
    f.write("POWER_DOWN_FAIL_SITE_X()\n{\n")
    f.write("   LEVELS(RST_LVL,3mS);\n   PIN_MODE(IO_ALLPINS,NRZ,EDGE,ENABLE,IO_NRZ,OFF);\n")
    f.write("   FORCE_V_MLDPS(" + vccpinnames + ",0V,@6V,@500mA,200mA,,ON,2mS);\n")
    f.write("   WAIT(5mS);\n")
    f.write("   FORCE_V_MLDPS(" + vccpinnames + ",0V,@6V,@500mA,200mA,,OFF,2mS);\n")
    f.write("   RELAY_OFF(IO_ALLPINS,PDCL,2mS);\n")
    if (cp_no == "CP1" or cp_no == "CP2") and has_kp:
        f.write("   SET_CBIT(KP, OFF, 2mS);\n")
    f.write("}\n\n")
    # //////////////////////////////////////////////fail_site_down 写入end/////////////////////////////////////////////
    f.write(
        "//////////////////////////////////////////////////////////////////\n//\n"
        + "//           Sub Flow\n//\n//////////////////////////////////////////////////////////////////\n\n")
