# flash 操作序列生成与 FLASH_EPR 配置解析（平台无关逻辑）。
# 平台输出差异（向量行语法、时序集名称）收口在 _vec/_ts/_label_vec 三个渲染函数里：
#   S100  : <空格><pins><pattern_end><cmd>     时序集 TIMING_SET G1_x;
#   Chroma: <空格>*<pins>*<cmd 或 ;>           时序集 TS1/TS5/TS6;（pattern_end 不参与）
import fb_map
from program_gen import state as G
from program_gen.core.encoding import bin8_to_hex, hex_to_Rbin_32bit, hex_to_Wbin_32bit

_TS_NAMES = {
    "s100": {"erase": "TIMING_SET G1_4;", "pgm": "TIMING_SET G1_5;", "normal": "TIMING_SET G1_1;"},
    "chroma": {"erase": "TS5;", "pgm": "TS6;", "normal": "TS1;"},
}


def _ts(kind):
    return _TS_NAMES[G.platform][kind]


def _vec(bits, space, pattern_end, cmd=""):
    if G.platform == "chroma":
        return space * " " + "*" + bits + "*" + (cmd if cmd else ";")
    return space * " " + bits + pattern_end + cmd


def _label_vec(label, bits, space, pattern_end):
    # 带跳转标签的向量行；Chroma 的标签习惯独占一行。
    # Chroma 用「裸标签 + 偏移」定位字段（如 .pln 里 flash_op0_w_p+15-J），不需要
    # S100 的首/尾锚点对：
    #   起始锚点 *_st: → 去掉 _st 后缀，作为唯一裸标签（flash_op0_w_p:）
    #   终止锚点 *_sp: → Chroma 无人引用，退化为无标签的纯向量行
    # S100 路径保持不变（.sd 仍输出 _st/_sp 成对锚点，逐字节一致）。
    if G.platform == "chroma":
        name = label.rstrip()
        if name.endswith("_sp:"):
            return _vec(bits, space, pattern_end)
        if name.endswith("_st:"):
            label = name[:-len("_st:")] + ":"
        return (space - len(label)) * " " + label + "\n" + _vec(bits, space, pattern_end)
    return (space - len(label)) * " " + label + bits + pattern_end


def flash_test_pattern_created(pattern_dic):
    """生成 fbist_bulk_*/fbist_page_epr_* 等 flash 测试向量文件（NM_PATTERN 表驱动）。

    数据体（00/FF/PCKB/NCKB 棋盘格）按 program bit/read bit 分块；ecc 列非 0 时追加
    ECC 编程/读取拍。文件框架按平台渲染（S100 .sd / Chroma .pat），向量体走 _vec。
    """
    chroma = G.platform == "chroma"
    pattern_end = ";"
    sp = 6

    def V(bits, cmd=""):
        return _vec(bits, sp, pattern_end, cmd)

    page_word = G.col("VERSION", "page word")[0]
    bank_list = []
    if (G.col("FLASH_EPR", "ecc")[0] != 0):
        ecc_n = str(G.col("FLASH_EPR", "ecc")[0])
        if chroma:
            ecc_pgm_flag = "*101*RPT " + ecc_n + ";// ECC program\n"
            ecc_read_flag = "*1X1*RPT " + ecc_n + ";// ECC read\n"
        else:
            ecc_pgm_flag = "101;RPT "+ecc_n+";// ECC program\n"
            ecc_read_flag = "1X1"+"RPT "+ecc_n+";// ECC read\n"
    else:
        ecc_pgm_flag = "\n"
        ecc_read_flag = "\n"

    write_head = ("\n" + V("111") + "\n" + V("110") + "// 1 bit strobe\n"
                  + V("111", "RPT 2;") + "// mode[3:0]=1001 write data\n"
                  + V("101", "RPT 2;") + "\n" + V("111") + "\n\n"
                  + (6) * " " + ecc_pgm_flag)
    read_head_1l = ("\n" + V("111") + "\n" + V("1L1") + "\n"
                    + (6) * " " + ecc_read_flag)
    write_read_dic = {"0":"L","1":"H"}
    program_bit = G.col("VERSION", "program bit")[0]
    read_bit = G.col("VERSION", "read bit")[0]
    for cyc in pattern_dic.keys():
        used_list = cyc.split(" ")
        write_data = ""
        write_data_e = ""
        read_data = ""
        if G.col("VERSION", "bank")[0] == "single":
            bank_list = ["01"]
        elif G.col("VERSION", "bank")[0] == "double":
            if used_list[0] == "page":
                bank_list = ["01"]
            else:
                bank_list = ["01","10"]

        if used_list[2] == "00":
            for i in range(0,int((page_word*32)/program_bit)):
                write_data+=write_head
                for j in range(0,int(program_bit/32)):
                    write_data+=V("101","RPT 32;")+"\n"+V("101")+"\n"
            for i in range(0,int((page_word*32)/read_bit)):
                read_data+=read_head_1l
                for j in range(0,int(read_bit/32)):
                    read_data += V("1L1","RPT 32;")+"\n"
                read_mode="1"

        elif used_list[2] == "FF":
            for i in range(0,int((page_word*32)/program_bit)):
                write_data+=write_head
                for j in range(0,int(program_bit/32)):
                    write_data+=V("111","RPT 32;")+"\n"+V("111")+"\n"
            for i in range(0,int((page_word*32)/read_bit)):
                read_data+=read_head_1l
                for j in range(0,int(read_bit/32)):
                    read_data += V("1H1","RPT 32;")+"\n"
                read_mode = "1"
        elif used_list[2] == "PCKB" or used_list[2] == "NCKB":
            read_mode = "0"
            total_bits = page_word * 32
            program_count = total_bits // program_bit  # 计算总写入次数
            data_format = int(G.flash_mode_dic["PCKB"].split(" ")[0])  # 数据格式（如8）
            data_format_bits = data_format * 8  # 数据格式对应的bit数
            pckb_bit = G.flash_mode_dic["PCKB"].split(" ")[2]
            nckb_bit = G.flash_mode_dic["NCKB"].split(" ")[2]

            for i in range(program_count):
                # 每program_bit添加一次write_head
                write_data += write_head
                write_data_e += write_head

                start_bit = i * program_bit
                write_head_bits = program_bit
                total_blocks = write_head_bits // data_format_bits

                # 当total_blocks <= 1时，直接输出一个完整的RPT，不需要拆分
                if total_blocks <= 1:
                    mode_index = (start_bit // data_format_bits) % 2
                    rpt_length = program_bit if total_blocks == 0 else data_format_bits

                    if mode_index == 0:
                        write_data += V("1"+pckb_bit+"1","RPT "+str(rpt_length)+";")+"\n"
                        write_data_e += V("1"+nckb_bit+"1","RPT "+str(rpt_length)+";")+"\n"
                    else:
                        write_data += V("1"+nckb_bit+"1","RPT "+str(rpt_length)+";")+"\n"
                        write_data_e += V("1"+pckb_bit+"1","RPT "+str(rpt_length)+";")+"\n"

                    # 为每个write head添加一个结束行
                    if mode_index == 0:
                        write_data += V("1"+pckb_bit+"1")+"\n"
                        write_data_e += V("1"+nckb_bit+"1")+"\n"
                    else:
                        write_data += V("1"+nckb_bit+"1")+"\n"
                        write_data_e += V("1"+pckb_bit+"1")+"\n"
                else:
                    # 倒序处理每个data_format_bits块，实现高位先行
                    for block in range(total_blocks - 1, -1, -1):
                        block_bit = start_bit + block * data_format_bits
                        mode_index = (block_bit // data_format_bits) % 2

                        if mode_index == 0:
                            write_data += V("1"+pckb_bit+"1","RPT "+str(data_format_bits)+";")+"\n"
                            write_data_e += V("1"+nckb_bit+"1","RPT "+str(data_format_bits)+";")+"\n"
                        else:
                            write_data += V("1"+nckb_bit+"1","RPT "+str(data_format_bits)+";")+"\n"
                            write_data_e += V("1"+pckb_bit+"1","RPT "+str(data_format_bits)+";")+"\n"

                    # 结束行使用第一个块的模式（高位先行）
                    first_block_bit = start_bit + (total_blocks - 1) * data_format_bits
                    first_mode_index = (first_block_bit // data_format_bits) % 2

                    if first_mode_index == 0:
                        write_data += V("1"+pckb_bit+"1")+"\n"
                        write_data_e += V("1"+nckb_bit+"1")+"\n"
                    else:
                        write_data += V("1"+nckb_bit+"1")+"\n"
                        write_data_e += V("1"+pckb_bit+"1")+"\n"

            # Read部分：逐页顺序读回（用户确认 2026-06-11）。结构与 00/FF 读对齐：
            # 每 read_bit 一个读节拍（read_head_1l），节拍内 32-bit 字高位组先行
            # （同 read_cyc 的置换规则）；期望值按棋盘格相位逐段给出，NCKB 整体反相。
            if used_list[2] == "PCKB":
                phase_bits = (pckb_bit, nckb_bit)
            else:
                phase_bits = (nckb_bit, pckb_bit)
            read_total_bits = page_word * 32
            words_per_burst = int(read_bit) // 32
            for i in range(0, int(read_total_bits / read_bit)):
                read_data += read_head_1l
                for w in range(words_per_burst):
                    # 组内倒序：高 32 bit 字先读
                    word_index = i * words_per_burst + (words_per_burst - 1 - w)
                    seg = 0
                    while seg < 32:
                        bit_pos = word_index * 32 + seg
                        run = min(32 - seg, data_format_bits - bit_pos % data_format_bits)
                        val = phase_bits[(bit_pos // data_format_bits) % 2]
                        read_data += V("1" + write_read_dic[val] + "1", "RPT " + str(run) + ";") + "\n"
                        seg += run

        erase_head = ""
        program_head = []
        program_end = []
        read_head = []
        ra = ""
        ra_list = []
        axa = ""
        read_mode = ""
        comp_num = ""
        ext = ".pat" if chroma else ".sd"
        with open(G.BASE_DIR + "\\pat_temp\\" + pattern_dic[cyc] + ext, 'w') as f:
            if chroma:
                f.write('SET_DEC_FILE "pin.dec"\n\nHEADER\n\n'+G.col("VERSION", "CLK PIN")[0]+", "+G.col("VERSION", "SWD PIN")[0]+', NRST;\n\nSPM_PATTERN(' + pattern_dic[cyc] + ') {\n\n')
                f.write(V("011", _ts("normal")) + "\n")
            else:
                f.write('HEAD[PIN_NAME]:\n\n' + G.col("VERSION", "CLK PIN")[0] + ', ' + G.col("VERSION", "SWD PIN")[0] + ', NRST;\n\nEND_HEAD;\n\n@@PATTERN_DEFINE\n\n')
                f.write(((6) - len("START:")) * " " + "START:" + "011" + pattern_end + "\n")
            f.write(V("011", "RPT 1000;") + "\n")
            if used_list[1] == "erase":
                if used_list[2] == "1st" or used_list[2] == "NM":
                    ra = "0"
                    axa = "0"
                    pe_label = 1
                elif used_list[2] == "all":
                    ra = "0"
                    axa = "1"
                    pe_label = 0
                erase_head = flash_erase(6,";",ra,axa,used_list[0],pe_label)
                f.write(erase_head)

            elif used_list[1] == "program":
                if used_list[0] == "bulk":
                    if used_list[3] == "NM":
                        ra = "0"
                        axa = "0"
                        pe_label = 0
                        if used_list[2] == "00" or used_list[2] == "FF":
                            # 用户规则(2026-06-11)：00/FF 的 bulk NM program 与棋盘格
                            # 同构，按奇偶页两遍写（ra=1 再 ra=0），数据两遍相同
                            bulk_mode = "bulk"
                            ra = "1"
                            program_head, program_end = flash_program(6, ";" ,ra, axa, used_list[0],bulk_mode, pe_label)
                            for i in range(len(bank_list)):
                                f.write(program_head[i])
                                f.write(write_data)
                                f.write(program_end[i])
                            ra = "0"
                            program_head, program_end = flash_program(6, ";" ,ra, axa, used_list[0],bulk_mode, pe_label)
                            for i in range(len(bank_list)):
                                f.write(program_head[i])
                                f.write(write_data)
                                f.write(program_end[i])
                        else:
                            bulk_mode = "bulk"
                            ra = "1"
                            program_head, program_end = flash_program(6, ";" ,ra, axa, used_list[0],bulk_mode, pe_label)
                            for i in range(len(bank_list)):
                                f.write(program_head[i])
                                if used_list[2] == "PCKB":
                                    f.write(write_data)
                                else:
                                    f.write(write_data_e)
                                f.write(program_end[i])
                            ra = "0"
                            program_head, program_end = flash_program(6, ";" ,ra, axa, used_list[0],bulk_mode, pe_label)
                            for i in range(len(bank_list)):
                                f.write(program_head[i])
                                if used_list[2] == "PCKB":
                                    f.write(write_data_e)
                                else:
                                    f.write(write_data)
                                f.write(program_end[i])
                    elif used_list[3] == "all":
                        ra = "0"
                        axa = "1"
                        pe_label = 0
                        bulk_mode = "bulk0"
                        program_head, program_end = flash_program(6, ";", ra, axa, used_list[0],bulk_mode,  pe_label)
                        for i in range(len(bank_list)):
                            f.write(program_head[i])
                            if used_list[2] == "PCKB":
                                f.write(write_data_e)
                            else:
                                f.write(write_data)
                            f.write(program_end[i])

                elif used_list[0] == "page":
                    if used_list[3] == "1st":
                        ra = "0"
                        axa = "0"
                        pe_label = 1
                        program_head, program_end = flash_program(6, ";", ra, axa, used_list[0], "page", pe_label)

                        for i in range(len(bank_list)):
                            f.write(program_head[i])
                            if used_list[2] == "PCKB":
                                f.write(write_data_e)
                            else:
                                f.write(write_data)
                            f.write(program_end[i])
                    else:
                        for j in range(0,G.flash_mode_dic["NM"]):
                            ra_list.append(str(bin(int(str(j),16))[2:]))
                            axa = "0"
                            pe_label = 0
                            program_head, program_end = flash_program(6, ";", ra_list[j], axa, used_list[0],"page",pe_label)

                            for i in range(len(bank_list)):
                                f.write(program_head[i])
                                if used_list[2] == "PCKB":
                                    f.write(write_data_e)
                                else:
                                    f.write(write_data)
                                f.write(program_end[i])
            elif used_list[1] == "read":
                read_head = flash_read(6,";",ra,axa,used_list[0],str(used_list[0]+used_list[2]).lower(),read_mode,G.flash_mode_dic["NM"],read_close=True)
                for i in range(len(bank_list)):
                    f.write(read_head[i])

            elif used_list[1] == "repair":
                f.write(flash_repair_head(6, ";", used_list[2], used_list[3]))

            elif used_list[1] == "epr":
                if used_list[2] != "Random":
                    for j in range(0, G.flash_mode_dic["boot loader"]):
                        ra_list.append(str(bin(int(str(j), 16))[2:]))
                        axa = "0"
                        erase_head = flash_erase(6, ";", ra_list[j], axa, used_list[0],pe_label)
                        program_head, program_end = flash_program(6, ";", ra_list[j], axa, used_list[0],"page",pe_label)
                        read_head = flash_read(6, ";", ra_list[j], axa, used_list[0], str(used_list[0]+used_list[2]).lower(),read_mode,G.flash_mode_dic["boot loader"])
                        f.write(erase_head)
                        f.write(program_head[0])
                        # NCKB 写反相数据（与 bulk 分支的相位选择一致）
                        if used_list[2] == "NCKB":
                            f.write(write_data_e)
                        else:
                            f.write(write_data)
                        f.write(program_end[0])
                        f.write(read_head[0])
                        f.write(read_data)


            if used_list[1] != "read":
                # read 的收尾已由 _comp_flag_tail(read_close) 对齐 golden（末位 111），
                # 不再追加这个全局 101；其余操作（erase/program/epr/repair）维持 101 收尾。
                f.write(V("101") + "\n")

            if chroma:
                f.write((6) * " " + "*011*STOP;\n\n}")
            else:
                f.write((6 - len("END:")) * " " + "END:" + "011" + pattern_end + "\n\n@@END_PATTERN_DEFINE ")


def fbist_mode_pattern_created():
    """生成进入/退出 fbist 模式的向量文件（enter/exit_fbist_mode.sd|.pat）。

    序列来自 FLASH_EPR 的 fbist_mode/fbist_cmd 列（flash_mode_dic["enter"/"exit"]，
    形如 A5_94_DA 的三个串行字节），逐位写在第二列（SWD），第三列（NRST）按字节区分。
    S100 渲染为 .sd（6 空格缩进、START/END 标签），Chroma 渲染为 .pat（2 空格、SPM 框架）。
    """
    chroma = G.platform == "chroma"
    sp = 2 if chroma else 6
    for kind, warm in (("enter", "RPT 10;"), ("exit", "RPT 4;")):
        words = G.flash_mode_dic[kind].split("_")
        # 三个串行字节的 NRST 列取值与首行注释（与原 S100 实现一致）
        nrst_cols = ["0", "1", "0"] if kind == "enter" else ["0", "0", "0"]
        comments = ["//" + words[0] + "H " + kind + " fbist mode",
                    "//" + words[1] + "H", "//" + words[2] + "H"]
        ext = ".pat" if chroma else ".sd"
        with open(G.BASE_DIR + "\\pat_temp\\" + kind + "_fbist_mode" + ext, 'w') as f:
            if chroma:
                f.write('SET_DEC_FILE "pin.dec"\n\nHEADER\n\nPA14, PA13, NRST;\n\nSPM_PATTERN('
                        + kind + '_fbist_mode) {\n\n')
                f.write(sp * " " + "*011*TS1;\n")
            else:
                f.write('HEAD[PIN_NAME]:\n\n' + G.col("VERSION", "CLK PIN")[0] + ', '
                        + G.col("VERSION", "SWD PIN")[0] + ', NRST;\n\nEND_HEAD;\n\n@@PATTERN_DEFINE\n\n')
                f.write((sp - len("START:")) * " " + "START:" + "011;" + "\n")
            f.write(_vec("011", sp, ";", "RPT 100;") + "\n")
            f.write(_vec("011", sp, ";", "RPT 100;") + "\n")
            f.write(_vec("011", sp, ";", "RPT 100;") + "\n")
            f.write(_vec("011", sp, ";", "RPT 100;") + "\n")
            f.write(_vec("011", sp, ";", "RPT 1000;") + "\n")
            f.write(_vec("011", sp, ";", "RPT 1000;") + "\n")
            f.write(_vec("111", sp, ";", warm) + "\n")
            for w in range(3):
                f.write("\n")
                bits32 = hex_to_Wbin_32bit(words[w])
                for j in range(24, 32):
                    cmt = comments[w] if j == 24 else ""
                    f.write(_vec("1" + bits32[j] + nrst_cols[w], sp, ";") + cmt + "\n")
            f.write("\n")
            f.write(_vec("111", sp, ";", "RPT 1000;") + "\n")
            f.write(_vec("111", sp, ";") + "\n")
            if chroma:
                f.write(sp * " " + "*011*STOP;\n\n}")
            else:
                f.write((sp - len("END:")) * " " + "END:" + "011;" + "\n\n@@END_PATTERN_DEFINE ")


def epr_pattern_capture(type_flag, page_flag):
    epr_pattern_dict = {"erase": "111", "pgm": "222", "read": "333"}
    if type_flag == "capture":
        epr_pattern_dict["erase"] = "111"
        epr_pattern_dict["pgm"] = "222"
        epr_pattern_dict["read"] = page_flag + "_capture"
    if type_flag == "check":
        epr_pattern_dict["erase"] = "111"
        epr_pattern_dict["pgm"] = "222"
        epr_pattern_dict["read"] = "fbist_page_check_" + page_flag

    if type_flag == "normal":
        if "id" in page_flag:
            epr_pattern_dict["erase"] = "fbist_page_erase_uid"
        else:
            epr_pattern_dict["erase"] = "fbist_page_erase_" + page_flag
        epr_pattern_dict["pgm"] = "fbist_page_prog_" + page_flag
        epr_pattern_dict["read"] = "fbist_page_read_" + page_flag

    return epr_pattern_dict


def flash_pattern_dic_created():
    flash_epr_pattern = {}

    # Phase 3（FB MAP addr 自动映射）：addr 列留空时从 configs 里的字段名反查 FB MAP 推导；
    # 填了的话仍沿用手填值，但跟 FB MAP 交叉核对，不一致直接抛错终止生成。老母本没有
    # FB MAP sheet 时 _fb_map_index 是空 dict，fb_map.resolve_addr 对空索引"手填非空就直接
    # 沿用、不校验"，行为完全不变。
    _fb_map_index = fb_map.build_index_from_workbook(G.wb)

    for j in range(len(G.col("FLASH_EPR", "addr"))):
        if type(G.col("FLASH_EPR", "configs")[j]) != float:
            parsed = fb_map.parse_epr_configs(G.col("FLASH_EPR", "configs")[j])
            field_names = [name for name, off, width in parsed]
            resolved_addr, _ = fb_map.resolve_addr(
                G.col("FLASH_EPR", "addr")[j], field_names, _fb_map_index)
            addr_dec = int(resolved_addr, 2)

            # 括号留空的字段（用户裁决 2026-07-03）：offset/width 全自动从 FB MAP 取，
            # 不能再表达"故意比 FB MAP 窄"这类写法——需要窄位宽时必须继续手填括号。
            configs = []
            for name, off, width in parsed:
                if off is None:
                    off, width = fb_map.resolve_field_width(name, addr_dec, _fb_map_index)
                configs.append([name, off, width])

            # 累加而非覆盖：母本可能把同一地址下的字段拆成好几行分别填（每行一个字段），
            # 用户裁决 2026-07-03——同一 addr 出现多次时，各行字段要合并成一份完整列表，
            # 不能让后一行覆盖掉前一行已经收集的字段。
            flash_epr_pattern.setdefault(resolved_addr, []).extend(configs)
    return flash_epr_pattern


def flash_mode_value_get():
    mode_temp_dic={}
    for j in range(len(G.col("FLASH_EPR", "mode"))):
        mode_temp_dic[G.col("FLASH_EPR", "Description")[j]] = G.col("FLASH_EPR", "mode")[j]
    for j in range(len(G.col("FLASH_EPR", "opr_value"))):
        if type(G.col("FLASH_EPR", "opr_value")[j]) != float:
            mode_temp_dic[G.col("FLASH_EPR", "opr_mode")[j]] = G.col("FLASH_EPR", "opr_value")[j]
    for j in range(len(G.col("FLASH_EPR", "space"))):
        if type(G.col("FLASH_EPR", "space")[j]) != float:
            mode_temp_dic[G.col("FLASH_EPR", "space")[j]] = G.col("FLASH_EPR", "page_num")[j]
    for j in range(len(G.col("FLASH_EPR", "chessboard_mode"))):
        if type(G.col("FLASH_EPR", "chessboard_mode")[j]) != float:
            mode_temp_dic[G.col("FLASH_EPR", "chessboard_mode")[j]] = G.col("FLASH_EPR", "chessboard_data")[j]
    # fbist_mode/fbist_cmd 为新版表格列；旧版 Excel（Chroma 暂用）无此列时跳过
    if "fbist_mode" in G.FLASH_EPR.columns:
        for j in range(len(G.col("FLASH_EPR", "fbist_mode"))):
            if type(G.col("FLASH_EPR", "fbist_mode")[j]) != float:
                mode_temp_dic[G.col("FLASH_EPR", "fbist_mode")[j]] = G.col("FLASH_EPR", "fbist_cmd")[j]
    # print(mode_temp_dic)
    return  mode_temp_dic


def flash_pattern_get():
    mode_temp_dic={}
    for j in range(len(G.col("NM_PATTERN", "used"))):
        mode_temp_dic[G.col("NM_PATTERN", "used")[j]] = G.col("NM_PATTERN", "Pattern name")[j].split(".")[0]

    # print(mode_temp_dic)
    return  mode_temp_dic


# 写入逻辑（跟踪是否有显式输入）
def write_values(flash_epr_pattern,**kwargs):
    flash_fbist_addr = []
    flash_fbist_value = []
    flash_fbist_comment = []

    # 处理每个寄存器
    for bin_addr, fields_list in flash_epr_pattern.items():
        reg_value = 0
        # 标记该寄存器是否有显式输入（任何字段被传入）
        has_explicit_input = any(field[0] in kwargs for field in fields_list)
        comment_parts = []

        for field in fields_list:
            field_name, bit_offset, bit_width = field

            if field_name in kwargs:
                binary_input = kwargs[field_name]
                # 验证二进制合法性
                if not all(c in '01' for c in binary_input):
                    raise ValueError(f"字段{field_name}输入不是合法二进制：{binary_input}")

                # 处理位宽
                if len(binary_input) < bit_width:
                    padded = binary_input.zfill(bit_width)
                else:
                    padded = binary_input[-bit_width:]

                # 计算字段值并组合
                field_value = int(padded, 2)
                reg_value |= (field_value << bit_offset)
                # 格式：字段名[起始位:结束位] = 位宽B值
                display_value = binary_input if binary_input else "0"
                end_bit = bit_offset + bit_width - 1
                comment_parts.append(f"{field_name}[{bit_offset}:{end_bit}] = {bit_width}B{display_value}")

        value_16bit = reg_value & 0xFFFF
        # 只有当有显式输入时才打印（无论值是否为0）
        if has_explicit_input:
            flash_fbist_addr.append(bin_addr)
            flash_fbist_value.append(bin(value_16bit)[2:].zfill(16))
            flash_fbist_comment.append(", ".join(comment_parts))

    return flash_fbist_addr, flash_fbist_value, flash_fbist_comment


class FlashRegisterPlanner:
    """在单个 Flash pattern 内按实际地址合成寄存器整字写入。"""

    def __init__(self, flash_epr_pattern, initial_values):
        self.flash_epr_pattern = flash_epr_pattern
        self.values = dict(initial_values)
        self._dirty_registers = []
        self._last_emitted = {}

    def stage(self, **updates):
        self.values.update(updates)
        updated_fields = set(updates)
        for bin_addr, fields_list in self.flash_epr_pattern.items():
            if any(field[0] in updated_fields for field in fields_list):
                if bin_addr not in self._dirty_registers:
                    self._dirty_registers.append(bin_addr)

    def flush(self):
        addrs, values, comments = [], [], []
        for bin_addr in self._dirty_registers:
            fields_list = self.flash_epr_pattern[bin_addr]
            field_names = [field[0] for field in fields_list]
            missing = [name for name in field_names if name not in self.values]
            if missing:
                raise ValueError(
                    "Flash 寄存器镜像缺少字段初值："
                    + ", ".join(missing)
                    + " (地址 " + str(bin_addr) + ")"
                )
            register_values = {name: self.values[name] for name in field_names}
            reg_addrs, reg_values, reg_comments = write_values(
                {bin_addr: fields_list}, **register_values)
            if reg_values and self._last_emitted.get(bin_addr) != reg_values[0]:
                addrs.extend(reg_addrs)
                values.extend(reg_values)
                comments.extend(reg_comments)
                self._last_emitted[bin_addr] = reg_values[0]
        self._dirty_registers.clear()
        return addrs, values, comments


def _flash_bank_register_planner():
    return FlashRegisterPlanner(
        G.flash_epr_pattern,
        {
            "BANK_EN": "00",
            "BANK_SEL": "00",
            "OPR_SEL": G.flash_mode_dic["pre"],
        },
    )


def _flash_has_ecc_on():
    return any(
        field[0] == "ECC_ON"
        for fields_list in G.flash_epr_pattern.values()
        for field in fields_list
    )


def _flash_ecc_on_required():
    if not _flash_has_ecc_on():
        return False
    try:
        return float(G.col("FLASH_EPR", "ecc")[0]) != 0
    except (TypeError, ValueError):
        return False


def _stage_flash_bank_config(bank_register, **updates):
    """暂存 BANK 配置；ECC_ON 存在且启用 ECC 时紧跟 BANK_SEL 打开。"""
    bank_register.stage(**updates)
    if _flash_has_ecc_on():
        bank_register.stage(ECC_ON="1" if _flash_ecc_on_required() else "0")


def fold_binary(binary_str,space,pattern_end,comment=""):
    # 检查输入是否为合法二进制字符串
    if not all(c in '01' for c in binary_str):
        raise ValueError("输入必须是仅包含0和1的二进制字符串")

    if not binary_str:  # 处理空输入
        return ""

    # 生成头部注释（包含原始输入数据）
    bit_length = len(binary_str)
    if bit_length == 16:
        # 16位时转换为十六进制
        hex_value = hex(int(binary_str, 2))[2:].upper().zfill(4)   # 去掉0x前缀并大写
        header_comment = f"//data = 0x{hex_value}"
        if comment:
            header_comment += f", {comment}"
    else:
        # 非16位时显示带0b的二进制
        header_comment = f"//addr = 0b{binary_str}"
        if comment:
            header_comment += f", {comment}"

    # 分组：记录连续相同的bit及其长度
    groups = []
    current_bit = binary_str[0]
    count = 1

    for bit in binary_str[1:]:
        if bit == current_bit:
            count += 1
        else:
            groups.append((current_bit, count))
            current_bit = bit
            count = 1
    # 添加最后一组
    groups.append((current_bit, count))

    # 生成折叠后的字符串
    result_lines = []
    # 第一行添加头部注释
    first_bit, first_length = groups[0]
    if first_length == 1:
        result_lines.append(_vec(f"1{first_bit}1", space, pattern_end)+f"{header_comment}")
    else:
        result_lines.append(_vec(f"1{first_bit}1", space, pattern_end, f"RPT {first_length};")+f"{header_comment}")

    # 处理剩余组
    for bit, length in groups[1:]:
        if length == 1:
            result_lines.append(_vec(f"1{bit}1", space, pattern_end))
        else:
            result_lines.append(_vec(f"1{bit}1", space, pattern_end, f"RPT {length};"))
    if bit_length == 16:
        result_lines.append(_vec(f"1{groups[-1][0]}1", space, pattern_end))
    # 用换行连接所有行，并在末尾加一个换行
    return '\n'.join(result_lines) + '\n'


def SEQ_1230(head,mode,space,pattern_end,opr_sel,pe_label,bank_sel):
    # bank_sel=="10" 时为第二个 bank（pe_2）；"01"（double 第一 bank）与 "00"（single）均为 pe_1
    if bank_sel == "10":
        pe_temp = "pe_2:"
    else:
        pe_temp = "pe_1:"

    def V(bits, cmd=""):
        return _vec(bits, space, pattern_end, cmd)

    m = "1" + mode[-1] + "1"
    fbist_head =("\n" + V("110") + "// 1 bit strobe\n"
                 + V("111") + "// PA13=1, write register\n"
                 )
    seq_list = ["01","10","10","10","11","00"]
    pe_list = ["0","0","1","0","0","0"]
    wait_79 = "\n"+V(m)+"\n"+V("110")+"\n"+V("111","RPT 2;")+"\n"+V("101","RPT 79;")+"\n\n"
    wait_24 = "\n"+V(m)+"\n"+V("110")+"\n"+V("111","RPT 2;")+"\n"+V("101","RPT 24;")+"\n\n"
    wait_350 = "\n"+V(m)+"\n"+V("111","RPT 350;")+"\n\n"
    wait_19 = "\n"+V(m)+"\n"+V("110")+"\n"+V("111","RPT 2;")+"\n"+V("101","RPT 19;")+"\n\n"
    wait_54 = "\n"+V(m)+"\n"+V("110")+"\n"+V("111","RPT 2;")+"\n"+V("101","RPT 54;")+"\n\n"

    def op_wait(ts_kind, rpt, with_label):
        # golden 确认：慢时钟等待严格 rpt 拍，TS 切换拍之间不夹多余单拍
        head_part = _label_vec(pe_temp, m, space, pattern_end) if with_label else V(m)
        return ("\n" + head_part + "\n" + "\n"
                + V(m, _ts(ts_kind)) + "\n"
                + V(m, f"RPT {rpt};") + "\n"
                + V(m, _ts("normal")) + "\n")

    if opr_sel == "pre":
        wait_list = [wait_79, wait_24,
                     "\n"+V(m)+"\n"+V(m,"RPT 1000;")+"\n\n",
                     wait_350, wait_19, wait_54,]
    elif opr_sel == "erase" and pe_label == 1:
        wait_list = [wait_79, wait_24,
                     op_wait("erase", 12500, with_label=True),
                     wait_350, wait_19, wait_54,]
    elif opr_sel == "erase":
        wait_list = [wait_79, wait_24,
                     op_wait("erase", 12500, with_label=False),
                     wait_350, wait_19, wait_54,]
    elif opr_sel == "program" and pe_label == 1:
        wait_list = [wait_79, wait_24,
                     op_wait("pgm", 7500, with_label=True),
                     wait_350, wait_19, wait_54,]
    elif opr_sel == "program":
        wait_list = [wait_79, wait_24,
                     op_wait("pgm", 7500, with_label=False),
                     wait_350, wait_19, wait_54,]

    for i in range(len(seq_list)):
        flash_fbist_addr, flash_fbist_value, flash_fbist_comment = write_values(G.flash_epr_pattern, PE=pe_list[i],SEQ=seq_list[i],MODE=mode)
        for j in range(len(flash_fbist_addr)):
            head+=fbist_head
            head+=fold_binary(flash_fbist_addr[j],space,pattern_end)
            head += fold_binary(flash_fbist_value[j], space, pattern_end, flash_fbist_comment[j])
        head+=wait_list[i]

    flash_fbist_addr, flash_fbist_value, flash_fbist_comment = write_values(G.flash_epr_pattern, PE=pe_list[i], SEQ=seq_list[i], MODE=G.flash_mode_dic["normal mode"])
    for j in range(len(flash_fbist_addr)):
        head += fbist_head
        head += fold_binary(flash_fbist_addr[j], space, pattern_end)
        head += fold_binary(flash_fbist_value[j], space, pattern_end, flash_fbist_comment[j])
    nm = "1" + G.flash_mode_dic["normal mode"][-1] + "1"
    head += "\n"+V(nm)+"\n"+V("110")+"\n"+V("111","RPT 2;")+"\n"+V("101","RPT 3;")+"\n"+V("1X1")+"\n\n"

    return head


def flash_erase(space,pattern_end,ra,axa,mode,pe_label):
    if G.col("VERSION", "bank")[0] == "single":
        # 单 bank：寄存器值沿用旧 Chroma 行为（新版表格才定义 BANK_SEL/BANK_EN 字段，
        # 旧表格无这些字段时 write_values 会忽略，取值不影响产物）
        bank_sel_list = ["00"]
        bank_en_list = ["00"]
    elif  G.col("VERSION", "bank")[0] == "double":
        if mode == "page":
            bank_sel_list = ["01"]
            bank_en_list = ["01"]
        else:
            bank_sel_list = ["01","10"]
            bank_en_list = ["01","10"]

    def V(bits, cmd=""):
        return _vec(bits, space, pattern_end, cmd)

    fbist_head =("\n" + V("110") + "// 1 bit strobe\n"
                 + V("111") + "// PA13=1, write register\n")
    erase_head = ""
    if mode == "bulk":
        flash_mode_pre = G.flash_mode_dic["bulk program all pages"]
        flash_mode_erase = G.flash_mode_dic["bulk erase"]
    elif mode == "page":
        flash_mode_pre = G.flash_mode_dic["program page"]
        flash_mode_erase = G.flash_mode_dic["erase page"]

    # [DEBUG 测试] page 擦除的 OPR 命令 RED 对齐 golden（=0，与读自洽）；bulk 维持 1。
    red_e = "0" if mode == "page" else "1"
    bank_register = _flash_bank_register_planner()

    for i in range(len(bank_sel_list)):
        if mode == "bulk" and i == 0:
            # golden(erase_nm，用户裁决 2026-06-11)：文件起始 2 拍空闲
            erase_head += V("111","RPT 2;") + "\n"
        flash_fbist_addr, flash_fbist_value, flash_fbist_comment = write_values(G.flash_epr_pattern, PE="0",SEQ="00",MODE=G.flash_mode_dic["normal mode"])
        for j in range(len(flash_fbist_addr)):
            erase_head += fbist_head
            erase_head += fold_binary(flash_fbist_addr[j],space,pattern_end)
            erase_head += fold_binary(flash_fbist_value[j], space, pattern_end, flash_fbist_comment[j])

        # BANK 字段先暂存；按 FLASH_EPR 的实际地址在本配置阶段合成。
        bank_register.stage(BANK_EN=bank_en_list[i])
        _stage_flash_bank_config(
            bank_register,
            OPR_SEL=G.flash_mode_dic["pre"], BANK_SEL=bank_sel_list[i],
            RED0_EN=red_e, RED1_EN=red_e, RED2_EN=red_e, RED3_EN=red_e,
        )
        flash_fbist_addr, flash_fbist_value, flash_fbist_comment = bank_register.flush()
        for j in range(len(flash_fbist_addr)):
            erase_head += fbist_head
            erase_head += fold_binary(flash_fbist_addr[j],space,pattern_end)
            erase_head += fold_binary(flash_fbist_value[j], space, pattern_end, flash_fbist_comment[j])

        flash_fbist_addr, flash_fbist_value, flash_fbist_comment = write_values(G.flash_epr_pattern, AXA=axa,CA="0", PA="0", RA=ra)
        for j in range(len(flash_fbist_addr)):
            erase_head += fbist_head
            erase_head += fold_binary(flash_fbist_addr[j],space,pattern_end)
            erase_head += fold_binary(flash_fbist_value[j], space, pattern_end, flash_fbist_comment[j])

        flash_fbist_addr, flash_fbist_value, flash_fbist_comment = write_values(G.flash_epr_pattern, PE="0",SEQ="00",MODE=G.flash_mode_dic["PEP"])
        for j in range(len(flash_fbist_addr)):
            erase_head += fbist_head
            erase_head += fold_binary(flash_fbist_addr[j],space,pattern_end)
            erase_head += fold_binary(flash_fbist_value[j], space, pattern_end, flash_fbist_comment[j])

        erase_head = SEQ_1230(erase_head,flash_mode_pre,space,pattern_end,"pre",pe_label,bank_en_list[i])

        _stage_flash_bank_config(
            bank_register,
            OPR_SEL=G.flash_mode_dic["erase"], BANK_SEL=bank_sel_list[i],
            RED0_EN=red_e, RED1_EN=red_e, RED2_EN=red_e, RED3_EN=red_e,
        )
        flash_fbist_addr, flash_fbist_value, flash_fbist_comment = bank_register.flush()
        for j in range(len(flash_fbist_addr)):
            erase_head += fbist_head
            erase_head += fold_binary(flash_fbist_addr[j],space,pattern_end)
            erase_head += fold_binary(flash_fbist_value[j], space, pattern_end, flash_fbist_comment[j])

        erase_head = SEQ_1230(erase_head, flash_mode_erase, space, pattern_end,"erase",pe_label,bank_en_list[i])

        flash_fbist_addr, flash_fbist_value, flash_fbist_comment = write_values(G.flash_epr_pattern, PE="0",SEQ="00",MODE=G.flash_mode_dic["clear page latches"])
        for j in range(len(flash_fbist_addr)):
            erase_head += fbist_head
            erase_head += fold_binary(flash_fbist_addr[j],space,pattern_end)
            erase_head += fold_binary(flash_fbist_value[j], space, pattern_end, flash_fbist_comment[j])
        nm = "1" + G.flash_mode_dic["normal mode"][-1] + "1"
        erase_head += V(nm)+"\n"+V("110")+"\n"+V("111","RPT 11;")+"\n"
        flash_fbist_addr, flash_fbist_value, flash_fbist_comment = write_values(G.flash_epr_pattern, PE="0",SEQ="00",MODE=G.flash_mode_dic["normal mode"])
        for j in range(len(flash_fbist_addr)):
            erase_head += fbist_head
            erase_head += fold_binary(flash_fbist_addr[j],space,pattern_end)
            erase_head += fold_binary(flash_fbist_value[j], space, pattern_end, flash_fbist_comment[j])
    return erase_head


def flash_program(space,pattern_end,ra,axa,mode,bulk_mode,pe_label):
    if G.col("VERSION", "bank")[0] == "single":
        # 单 bank：同 flash_erase 的说明
        bank_sel_list = ["01"]
        bank_en_list = ["01"]
    elif  G.col("VERSION", "bank")[0] == "double":
        if mode == "page":
            bank_sel_list = ["01"]
            bank_en_list = ["01"]
        else:
            bank_sel_list = ["01","10"]
            bank_en_list = ["01","10"]

    def V(bits, cmd=""):
        return _vec(bits, space, pattern_end, cmd)

    fbist_head =("\n" + V("110") + "// 1 bit strobe\n"
                + V("111") + "// PA13=1, write register\n")

    program_head = ["",""]
    program_end = ["",""]
    if bulk_mode == "bulk":
        flash_mode_program = G.flash_mode_dic["bulk program even/odd pages"]
    if bulk_mode == "bulk0":
        flash_mode_program = G.flash_mode_dic["bulk program all pages"]
    elif bulk_mode == "page":
        flash_mode_program = G.flash_mode_dic["program page"]

    # [DEBUG 测试] 原逻辑 page/bulk0 用 RED=1；但 golden 页程序 OPR 命令是 RED=0（与读自洽）。
    # 暂改：page 程序 RED=0 对齐 golden；bulk0 维持 1；bulk EO 本就 0。
    red = "1" if bulk_mode == "bulk0" else "0"
    bank_register = _flash_bank_register_planner()
    for i in range(len(bank_sel_list)):
        _stage_flash_bank_config(
            bank_register,
            BANK_EN=bank_en_list[i],
            OPR_SEL=G.flash_mode_dic["program"],
            BANK_SEL=bank_sel_list[i],
            RED0_EN=red, RED1_EN=red, RED2_EN=red, RED3_EN=red,
        )
        flash_fbist_addr, flash_fbist_value, flash_fbist_comment = bank_register.flush()
        for j in range(len(flash_fbist_addr)):
            program_head[i]+=fbist_head
            program_head[i]+=fold_binary(flash_fbist_addr[j],space,pattern_end)
            program_head[i] += fold_binary(flash_fbist_value[j], space, pattern_end, flash_fbist_comment[j])

        flash_fbist_addr, flash_fbist_value, flash_fbist_comment = write_values(G.flash_epr_pattern, PE="0",SEQ="00",MODE=G.flash_mode_dic["normal mode"])
        for j in range(len(flash_fbist_addr)):
            program_head[i] += fbist_head
            program_head[i] += fold_binary(flash_fbist_addr[j],space,pattern_end)
            program_head[i] += fold_binary(flash_fbist_value[j], space, pattern_end, flash_fbist_comment[j])

        flash_fbist_addr, flash_fbist_value, flash_fbist_comment = write_values(G.flash_epr_pattern, AXA=axa,CA="0", PA="0", RA=ra)
        for j in range(len(flash_fbist_addr)):
            program_head[i]+=fbist_head
            program_head[i]+=fold_binary(flash_fbist_addr[j],space,pattern_end)
            program_head[i] += fold_binary(flash_fbist_value[j], space, pattern_end, flash_fbist_comment[j])

        # 0x24 为整字写入：bulk-all 模式的 bank 配置写需保留 OPR_SEL=program（golden），
        # EO 模式 golden 此处不带 OPR_SEL（pulse 前的 program_end 写会重新建立）
        if bulk_mode == "bulk0":
            _stage_flash_bank_config(
                bank_register,
                OPR_SEL=G.flash_mode_dic["program"], BANK_SEL=bank_sel_list[i],
                RED0_EN=red, RED1_EN=red, RED2_EN=red, RED3_EN=red,
            )
        else:
            _stage_flash_bank_config(
                bank_register,
                BANK_SEL=bank_sel_list[i],
                RED0_EN=red, RED1_EN=red, RED2_EN=red, RED3_EN=red,
            )
        flash_fbist_addr, flash_fbist_value, flash_fbist_comment = bank_register.flush()
        for j in range(len(flash_fbist_addr)):
            program_head[i]+=fbist_head
            program_head[i]+=fold_binary(flash_fbist_addr[j],space,pattern_end)
            program_head[i] += fold_binary(flash_fbist_value[j], space, pattern_end, flash_fbist_comment[j])

        flash_fbist_addr, flash_fbist_value, flash_fbist_comment = write_values(G.flash_epr_pattern, PE="0",SEQ="00",MODE=G.flash_mode_dic["clear page latches"])
        for j in range(len(flash_fbist_addr)):
            program_head[i] += fbist_head
            program_head[i] += fold_binary(flash_fbist_addr[j],space,pattern_end)
            program_head[i] += fold_binary(flash_fbist_value[j], space, pattern_end, flash_fbist_comment[j])
        nm = "1" + G.flash_mode_dic["normal mode"][-1] + "1"
        program_head[i] += V(nm)+"\n"+V("110")+"\n"+V("111","RPT 11;")+"\n"
        flash_fbist_addr, flash_fbist_value, flash_fbist_comment = write_values(G.flash_epr_pattern, PE="0",SEQ="00",MODE=G.flash_mode_dic["normal mode"])
        for j in range(len(flash_fbist_addr)):
            program_head[i] += fbist_head
            program_head[i] += fold_binary(flash_fbist_addr[j],space,pattern_end)
            program_head[i] += fold_binary(flash_fbist_value[j], space, pattern_end, flash_fbist_comment[j])

        flash_fbist_addr, flash_fbist_value, flash_fbist_comment = write_values(G.flash_epr_pattern, PE="0",SEQ="00",MODE=G.flash_mode_dic["write page latches"])
        for j in range(len(flash_fbist_addr)):
            program_head[i] += fbist_head
            program_head[i] += fold_binary(flash_fbist_addr[j],space,pattern_end)
            program_head[i] += fold_binary(flash_fbist_value[j], space, pattern_end, flash_fbist_comment[j])

        wpl = "1" + G.flash_mode_dic["write page latches"][-1] + "1"
        program_head[i] += V(wpl)+"\n"+V("100")+"\n"+V("111","RPT 2;")+"\n"+V("101","RPT 4;")+"\n"

        _stage_flash_bank_config(
            bank_register,
            OPR_SEL=G.flash_mode_dic["program"], BANK_SEL=bank_sel_list[i],
            RED0_EN=red, RED1_EN=red, RED2_EN=red, RED3_EN=red,
        )
        flash_fbist_addr, flash_fbist_value, flash_fbist_comment = bank_register.flush()
        for j in range(len(flash_fbist_addr)):
            program_end[i]+=fbist_head
            program_end[i]+=fold_binary(flash_fbist_addr[j],space,pattern_end)
            program_end[i] += fold_binary(flash_fbist_value[j], space, pattern_end, flash_fbist_comment[j])

        program_end[i] = SEQ_1230(program_end[i], flash_mode_program, space, pattern_end,"program",pe_label,bank_en_list[i])

        flash_fbist_addr, flash_fbist_value, flash_fbist_comment = write_values(G.flash_epr_pattern, PE="0",SEQ="00",MODE=G.flash_mode_dic["normal mode"])
        for j in range(len(flash_fbist_addr)):
            program_end[i] += fbist_head
            program_end[i] += fold_binary(flash_fbist_addr[j],space,pattern_end)
            program_end[i] += fold_binary(flash_fbist_value[j], space, pattern_end, flash_fbist_comment[j])
    return program_head,program_end


def _comp_flag_tail(V, read_close=False):
    """read_compare/repair 的结果标志期望：按 FLASH_EPR 的 comp_data 列
    （十六进制，如 0x5A=PASS 序列）逐位生成（MSB 先行，1=H/0=L）。
    read_close=True（bulk read 末尾）：收尾对齐 golden（1L1 1L1 1X0 + 111RPT3 + 111 111）；
    否则（repair 等）维持旧的 3 拍 1X1。不同产品取值不同；旧表格无该列时维持原硬编码波形。"""
    comp_flag_value = G.col("FLASH_EPR", "comp_flag")[0] if "comp_flag" in G.FLASH_EPR.columns else "no"
    if str(comp_flag_value).lower() != "yes":
        return ""
    comp_data_value = str(G.col("FLASH_EPR", "comp_data")[0]) if "comp_data" in G.FLASH_EPR.columns else "nan"
    if comp_data_value not in ("nan", ""):
        flag_bits = bin(int(comp_data_value, 16))[2:].zfill(8)
        out = "\n"
        for k in range(8):
            out += V("1" + ("H" if flag_bits[k] == "1" else "L") + "1") + "\n"
            if k == 3:
                out += "\n"
        if read_close:
            out += ("\n"+V("1L1")+"\n"+V("1L1")+"\n"+V("1X0")+"\n"
                    +V("111","RPT 3;")+"\n"+V("111")+"\n\n"+V("111")+"\n\n")
        else:
            out += "\n"+V("1X1")+"\n"+V("1X1")+"\n"+V("1X1")+"\n\n"
        return out
    return ("\n"+V("1L1")+"\n"+V("1L1")+"\n"
            +V("1H1")+"\n"+V("1H1")+"\n\n"
            +V("1H1")+"\n"+V("1L1")+"\n"
            +V("1H1")+"\n"+V("1L1")+"\n\n"+V("1X1")+"\n"
            +V("1X1")+"\n"+V("1X1")+"\n\n")


def flash_repair_head(space, pattern_end, data_mode, bank):
    """repair（Cmd[3:0]=1010）单 bank 序列，NM_PATTERN 表驱动
    （used = "bulk repair <00|FF|PCKB|NCKB> <bank0|bank1>"）。

    repair 测试流程尚未固化：FLOW/writers 暂不引用这些 pattern，仅生成文件备用。
    结构为 bulk read 的变体：normal mode 最先写、RED=1111（repair 操作冗余区）；
    COMP 配置与 bulk read 同映射；PASS 序列 = comp_data 列（0x5A，用户确认）。
    """
    read_bit = G.col("VERSION", "read bit")[0]

    def V(bits, cmd=""):
        return _vec(bits, space, pattern_end, cmd)

    fbist_head = ("\n" + V("110") + "// 1 bit strobe\n"
                  + V("111") + "// PA13=1, write register\n")

    if G.col("VERSION", "bank")[0] == "double":
        read_ack = int((int(G.flash_mode_dic["NM"]) * G.flash_mode_dic["PAGE_BYTES"] * 4) / read_bit)
    else:
        read_ack = int((int(G.flash_mode_dic["NM"]) * G.flash_mode_dic["PAGE_BYTES"] * 8) / read_bit)

    comp_map = {  # 与 flash_read 的 bulk 数据模式映射一致
        "00": ("0", "00000000"),
        "FF": ("0", "11111111"),
        "PCKB": ("1", "11111111"),
        "NCKB": ("1", "00000000"),
    }
    comp_mode, comp_data = comp_map[data_mode]
    i = 1 if bank == "bank1" else 0
    bank_en = ["01", "10"][i]
    bank_sel = ["01", "10"][i]
    bank_register = _flash_bank_register_planner()

    head = ""
    if i > 0:
        # golden：bank1 起始 2 拍空闲
        head += V("111", "RPT 2;") + "\n"
    for kwargs in [dict(PE="0", SEQ="00", MODE=G.flash_mode_dic["normal mode"])]:
        a, v, c = write_values(G.flash_epr_pattern, **kwargs)
        for j in range(len(a)):
            head += fbist_head
            head += fold_binary(a[j], space, pattern_end)
            head += fold_binary(v[j], space, pattern_end, c[j])
    _stage_flash_bank_config(
        bank_register,
        BANK_EN=bank_en, BANK_SEL=bank_sel,
        RED0_EN="1", RED1_EN="1", RED2_EN="1", RED3_EN="1",
    )
    a, v, c = bank_register.flush()
    for j in range(len(a)):
        head += fbist_head
        head += fold_binary(a[j], space, pattern_end)
        head += fold_binary(v[j], space, pattern_end, c[j])
    for kwargs in [dict(AXA="0", CA="0", PA="0", RA="0"),
                   dict(READ_MODE="0", COMP_MODE=comp_mode, COMP_DATA=comp_data,
                        COMPARE_NUMBER=str(bin(read_ack)[2:]))]:
        a, v, c = write_values(G.flash_epr_pattern, **kwargs)
        for j in range(len(a)):
            head += fbist_head
            head += fold_binary(a[j], space, pattern_end)
            head += fold_binary(v[j], space, pattern_end, c[j])
    # repair 命令：strobe + wr + Cmd[3:0]=1010
    head += ("\n" + V("100") + "\n"
             + V("111") + "\n"
             + V("111") + "// Cmd[3:0]=1010 repair_mode\n"
             + V("101") + "\n" + V("111") + "\n" + V("101") + "\n"
             + V("1X1") + "\n"
             + V("1L1", "RPT " + str(read_ack * 2) + ";") + "\n")
    head += _comp_flag_tail(V)
    return head


def _otp_ra_value(value_16bit, space, pattern_end, comment=""):
    """OTP_READ 专用：渲染 RA 寄存器（16 位，RA 在低 8 位）的数据拍。
    高 8 位（value_16bit[0:8]，MSB 优先）保持折叠写 0；低 8 位（RA[7:0]）逐位展开
    （不 RPT 折叠），并在首位（RA[7]，最先写入）打 `addr:` 裸标签，供测试项
    write_pat_mem(otp_read:addr+7-j, ...) 逐位写 8 位页地址。"""
    high = value_16bit[:8]   # bit15..bit8（非 RA 字段，全 0）
    low = value_16bit[8:]    # bit7..bit0 = RA[7]..RA[0]
    out = ""
    # 高 8 位折叠（沿用 fold_binary 的分组思路，但不带头部注释）
    groups = []
    cur, cnt = high[0], 1
    for b in high[1:]:
        if b == cur:
            cnt += 1
        else:
            groups.append((cur, cnt)); cur, cnt = b, 1
    groups.append((cur, cnt))
    first = True
    for bit, length in groups:
        cmd = ("RPT " + str(length) + ";") if length > 1 else ""
        line = _vec("1" + bit + "1", space, pattern_end, cmd)
        if first:
            line += "//data = RA[15:8] = 0b" + high + (", " + comment if comment else "")
            first = False
        out += line + "\n"
    # 低 8 位逐位（RA[7]..RA[0]，MSB 先行 → 偏移 0=RA[7], 7=RA[0]）。
    # Chroma：单 `addr:` 裸标签 + 偏移寻址（otp_read:addr+7-j）。
    # S100：LOGIC_WRITE_PATTERN_MEMORY 需首/尾两标签——START2(RA[7]) / END2(RA[0])
    #       （单一标签同名会报错，用户裁决 2026-06-24）。
    chroma = G.platform == "chroma"
    # S100 的这 8 拍由 LOGIC_WRITE_PATTERN_MEMORY 改写地址，不能产生 capture trigger。
    # Chroma 没有 TRIGPIN 列，保持原 pattern_end。
    ra_pattern_end = pattern_end if chroma else "0;"
    last = len(low) - 1
    for idx, bit in enumerate(low):
        ra_n = 7 - idx
        if chroma:
            lab = "addr:" if idx == 0 else None
        else:
            lab = "START2:" if idx == 0 else ("END2:" if idx == last else None)
        if lab:
            out += _label_vec(lab, "1" + bit + "1", space, ra_pattern_end) + "//RA[" + str(ra_n) + "]\n"
        else:
            out += _vec("1" + bit + "1", space, ra_pattern_end) + "//RA[" + str(ra_n) + "]\n"
    return out


def _ra_reg_addr():
    """RA 字段所在寄存器的地址（从母本 FLASH_EPR 动态查，不写死）——各产品寄存器地址分配
    不同（如 golden RA=0011110，本产品 RA=0011111），硬编码会导致 otp 分支永远不命中。"""
    for bin_addr, fields_list in G.flash_epr_pattern.items():
        if any(field[0] == "RA" for field in fields_list):
            return bin_addr
    return None


def flash_read(space, pattern_end, ra, axa, mode,data_mode,read_mode,comp_num,read_close=False,otp=False,nm_capture=False):
    # nm_capture=True：NM_Data_Read debug 项专用（仅 chroma 调用）。复用 bulk 读的全部寄存器
    # 配置（bank_en/bank_sel/RA/read_mode=连续读/comp），但把「读命令+1L1 compare+comp_flag」
    # 换成「连续读命令(Cmd=1000)+硬件 capture 循环(1K1 + SETX/JNZ)」：每 bank 预读 1 组
    # (read_bit 位)，再 SETX{bank}=(read_ack-1) 跑 LOOP{bank}，每轮读 1 组、JNZ{bank} 回跳，
    # 共 read_ack 组/bank（read_ack=NM*PAGE_BYTES*4/read_bit）。与 temp 样本 nm_read.pat 同构，
    # 循环计数(SETX)=read_ack-1，2026-07-03 用户上机实测坐实（原 read_ack-2 会导致 loop
    # 次数比 capture 抓的 bit 数少 1 组，机台报错）。
    # otp=True：OTP_READ debug 项专用。RA 字段所在寄存器（地址由 _ra_reg_addr() 动态查）的
    # 低 8 位改为「`addr:` 裸标签 + 8 个逐位写 0 的拍」（不 RPT 折叠），其余高位保持折叠写 0，
    # 使测试项能 write_pat_mem(otp_read:addr+7-j, ...) 逐位写入 8 位页地址。
    chroma = G.platform == "chroma"
    read_bit= G.col("VERSION", "read bit")[0]
    if G.col("VERSION", "bank")[0] == "single":
        # 单 bank：同 flash_erase 的说明
        bank_sel_list = ["01"]
        bank_en_list = ["01"]
        read_ack = int(((int(comp_num)*G.flash_mode_dic["PAGE_BYTES"]*8)/read_bit))
    elif  G.col("VERSION", "bank")[0] == "double":
        # 每个bank读取一半NM的数据
        read_ack = int(((int(comp_num)*G.flash_mode_dic["PAGE_BYTES"]*4)/read_bit))
        if mode == "page":
            bank_sel_list = ["01"]
            bank_en_list = ["01"]
        else:
            bank_sel_list = ["01","10"]
            bank_en_list = ["01","10"]

    def V(bits, cmd=""):
        return _vec(bits, space, pattern_end, cmd)

    fbist_head =("\n" + V("110") + "// 1 bit strobe\n"
                 + V("111") + "// PA13=1, write register\n")
    otp_capture_start_pending = False

    def next_fbist_head():
        """在 OTP 动态 RA 写入之后，为真正的读流程标出 S100 capture 起点。"""
        nonlocal otp_capture_start_pending
        if otp and not chroma and otp_capture_start_pending:
            otp_capture_start_pending = False
            return ("\n" + _label_vec("START1:", "110", space, pattern_end)
                    + "// 1 bit strobe\n" + V("111") + "// PA13=1, write register\n")
        return fbist_head
    comp_data = ""
    comp_mode = ""
    read_head= ["",""]
    if mode == "page" or data_mode == "bulk00" or data_mode == "bulknckb":
        comp_data = "00000000"
        if mode == "page" or data_mode == "bulk00":
            comp_mode = "0"
        elif data_mode == "bulknckb":
            comp_mode = "1"
    elif data_mode == "bulkff" or data_mode == "bulkpckb":
        comp_data = "11111111"
        if data_mode == "bulkff":
            comp_mode = "0"
        elif data_mode == "bulkpckb":
            comp_mode = "1"

    bank_register = _flash_bank_register_planner()
    for i in range(len(bank_sel_list)):
        if mode == "page":
            # page 读维持原顺序（normal mode 先写，未经 golden 验证不动）；
            # bulk 顺序按上机 golden：配置全部写完、读命令之前才写 normal mode
            flash_fbist_addr, flash_fbist_value, flash_fbist_comment = write_values(G.flash_epr_pattern, PE="0",SEQ="00",MODE=G.flash_mode_dic["normal mode"])
            for j in range(len(flash_fbist_addr)):
                read_head[i] += next_fbist_head()
                read_head[i] += fold_binary(flash_fbist_addr[j],space,pattern_end)
                read_head[i] += fold_binary(flash_fbist_value[j], space, pattern_end, flash_fbist_comment[j])
        else:
            # golden：每个 bank 起始 111 空闲 10 拍，bank 之间另有 011 间隔 100 拍
            if i > 0:
                read_head[i] += V("011","RPT 100;") + "\n"
            read_head[i] += V("111","RPT 10;") + "\n"

        _stage_flash_bank_config(
            bank_register,
            BANK_EN=bank_en_list[i], BANK_SEL=bank_sel_list[i],
            RED0_EN="0", RED1_EN="0", RED2_EN="0", RED3_EN="0",
        )
        flash_fbist_addr, flash_fbist_value, flash_fbist_comment = bank_register.flush()
        for j in range(len(flash_fbist_addr)):
            read_head[i]+=next_fbist_head()
            read_head[i]+=fold_binary(flash_fbist_addr[j],space,pattern_end)
            read_head[i] += fold_binary(flash_fbist_value[j], space, pattern_end, flash_fbist_comment[j])

        flash_fbist_addr, flash_fbist_value, flash_fbist_comment = write_values(G.flash_epr_pattern, AXA=axa,CA="0", PA="0", RA=ra)
        ra_reg_addr = _ra_reg_addr() if otp else None
        for j in range(len(flash_fbist_addr)):
            read_head[i]+=next_fbist_head()
            read_head[i]+=fold_binary(flash_fbist_addr[j],space,pattern_end)
            # OTP：RA 字段所在寄存器（地址动态查，见 _ra_reg_addr）低 8 位改为「addr: 标签 + 8 个逐位 0 拍」
            if otp and flash_fbist_addr[j] == ra_reg_addr:
                read_head[i] += _otp_ra_value(flash_fbist_value[j], space, pattern_end, flash_fbist_comment[j])
                otp_capture_start_pending = True
            else:
                read_head[i] += fold_binary(flash_fbist_value[j], space, pattern_end, flash_fbist_comment[j])

        if mode == "bulk":
            # Bulk compare 需要在 RA 后配置 COMP_ECC：全 1 数据/正棋盘格置 1，
            # 全 0 数据/反棋盘格置 0。位宽由 FLASH_EPR 的 COMP_ECC 定义决定。
            comp_ecc = "11111111" if data_mode in ("bulkff", "bulkpckb") else "00000000"
            flash_fbist_addr, flash_fbist_value, flash_fbist_comment = write_values(
                G.flash_epr_pattern, COMP_ECC=comp_ecc)
            for j in range(len(flash_fbist_addr)):
                read_head[i] += next_fbist_head()
                read_head[i] += fold_binary(flash_fbist_addr[j], space, pattern_end)
                read_head[i] += fold_binary(flash_fbist_value[j], space, pattern_end, flash_fbist_comment[j])

        if nm_capture:
            # NM capture=连续读，不写 COMPARE_NUMBER（比较计数寄存器）——对齐两平台 golden 连续读逻辑：
            # 只写 READ_MODE=1(连续)/COMP_MODE=0/COMP_DATA；读满整片靠 chroma 硬件 SETX 循环
            # 或 s100 C 端逐页 START2/END2，而非比较计数。否则 read FSM 会按比较计数跑、错位。
            flash_fbist_addr, flash_fbist_value, flash_fbist_comment = write_values(G.flash_epr_pattern, READ_MODE=read_mode, COMP_MODE=comp_mode, COMP_DATA=comp_data)
        else:
            flash_fbist_addr, flash_fbist_value, flash_fbist_comment = write_values(G.flash_epr_pattern, READ_MODE=read_mode,COMP_MODE=comp_mode, COMP_DATA=comp_data, COMPARE_NUMBER=str(bin(read_ack)[2:]))
        for j in range(len(flash_fbist_addr)):
            read_head[i]+=next_fbist_head()
            read_head[i]+=fold_binary(flash_fbist_addr[j],space,pattern_end)
            read_head[i] += fold_binary(flash_fbist_value[j], space, pattern_end, flash_fbist_comment[j])

        if mode != "page":
            # golden：normal read mode 写在所有配置之后、读命令之前(read 专属顺序)
            flash_fbist_addr, flash_fbist_value, flash_fbist_comment = write_values(G.flash_epr_pattern, PE="0",SEQ="00",MODE=G.flash_mode_dic["normal mode"])
            for j in range(len(flash_fbist_addr)):
                read_head[i] += next_fbist_head()
                read_head[i] += fold_binary(flash_fbist_addr[j],space,pattern_end)
                read_head[i] += fold_binary(flash_fbist_value[j], space, pattern_end, flash_fbist_comment[j])

        if nm_capture:
            # 连续读命令（Cmd=1000，同 page 风格）
            read_head[i] += (V("100")+"\n"+V("111","RPT 2;//Cmd[3:0]=1000 read_mode")+"\n"
                             +V("101","RPT 3;")+"\n"+V("1X1")+"\n")
            # chroma：读命令后接硬件 capture 循环（1K1 + SETX/JNZ）。
            # s100：仅到读命令为止，capture(1H10) + START2/END2 由 nm_read_pattern_created 追加。
            if G.platform == "chroma":
                ecc_read = (V("1X1", "RPT " + str(G.col("FLASH_EPR", "ecc")[0]) + ";// ECC read") + "\n"
                            if G.col("FLASH_EPR", "ecc")[0] != 0 else "")
                wpr = read_bit // 32                 # 每个读分几个 32-bit 字（64→2）
                setx = read_ack - 1                  # 预读1组 + 循环共 read_ack 组；2026-07-03
                                                      # 用户上机实测坐实：SETX 计数=read_ack-1
                                                      # （原 read_ack-2 会导致 pattern 内 loop
                                                      # 次数比 capture 抓的 bit 数少 1 组，读回
                                                      # 数据错位/机台报错，已修正）
                # 预读 1 组（read_bit 位 = wpr 个 32 拍字；末字末拍挂 SETX{bank}）
                read_head[i] += ecc_read
                for w in range(wpr):
                    if w < wpr - 1:
                        read_head[i] += V("1K1", "RPT 32;//pre data[" + str(w) + "]") + "\n"
                    else:
                        read_head[i] += (V("1K1", "RPT 30;") + "\n" + V("1K1") + "\n"
                                         + V("1K1", "SETX" + str(i) + " " + str(setx)
                                            + ";//" + str(read_ack) + " reads/bank") + "\n")
                # 硬件循环体（每轮读 1 组；末拍 JNZ{bank} 回跳）
                read_head[i] += "LOOP" + str(i) + ":\n" + V("111") + "\n" + V("1X1") + "\n" + ecc_read
                for w in range(wpr):
                    if w < wpr - 1:
                        read_head[i] += V("1K1", "RPT 32;//data[" + str(w) + "]") + "\n"
                    else:
                        read_head[i] += (V("1K1", "RPT 30;") + "\n" + V("1K1") + "\n"
                                         + V("1K1", "JNZ" + str(i) + " LOOP" + str(i) + ";") + "\n")
        elif mode == "page":
            read_head[i] += (V("100")+"\n"+V("111","RPT 2;//Cmd[3:0]=1000 read_mode")+"\n"
                             +V("101","RPT 3;")+"\n"+V("1X1")+"\n\n")
        else:
            # 该系数需要根据数字设计更改
            rpt_value = read_ack * 2
            max_rpt = 65535
            if rpt_value <= max_rpt:
                read_head[i] += (V("100")+"\n"+V("111","RPT 3;//Cmd[3:0]=1101 read_compare_mode")+"\n"
                                 +V("101")+"\n"+V("111")+"\n"
                                 +V("1X1")+"\n"+V("1L1","RPT "+str(rpt_value)+";")+"\n")

            else:
                n = (rpt_value + max_rpt - 1) // max_rpt
                each_rpt = rpt_value // n
                remainder = rpt_value % n
                read_head[i] += (V("100")+"\n"+V("111","RPT 3;//Cmd[3:0]=1101 read_compare_mode")+"\n"
                                 +V("101")+"\n"+V("111")+"\n"+V("1X1")+"\n")
                for split_idx in range(n):
                    current_rpt = each_rpt + (1 if split_idx < remainder else 0)
                    read_head[i] += (V("1L1","RPT "+str(current_rpt)+";")+"\n")

            # comp_flag判断：结果标志期望（read_compare/repair 共用），见 _comp_flag_tail
            read_head[i] += _comp_flag_tail(V, read_close=read_close)
    return read_head


def flash_pattern_label_created(output_num):
    """生成 fbist_page_erase/prog/read/check_* 与 *_capture 标签向量文件（ADDR_MAP 表驱动）。

    页内字序由 read/prog 位宽折算（read_cyc/prog_cyc），数据取 ADDR_MAP 的 CP Data[31:0]
    列；data type 为 lable 的字带跳转标签（*_st:/*_sp:），uid 页另派生 cp1/cp2/cp3/bake
    系列 pattern。S100 渲染 .sd（lable pattern 带 TRIGPIN 第四引脚，pattern_end "0;" 为
    capture 触发列）；Chroma 渲染 .pat（SPM 框架，capture 列由 .pln 运行时改写故 _vec
    忽略 pattern_end）。逻辑与 S100 原实现逐字节一致。
    """
    chroma = G.platform == "chroma"
    ext = ".pat" if chroma else ".sd"
    pattern_end = ";"

    def V(bits, sp, cmd=""):
        return _vec(bits, sp, pattern_end, cmd)

    def LV(nsp, label, bits):
        # nsp 为原 S100 标签行的前导空格数（表达式原样传入）；_label_vec 以
        # "列宽-标签长" 计算缩进，故此处回传 nsp+len(label) 还原同一空格数
        return _label_vec(label, bits, nsp + len(label), pattern_end)

    def file_head(f, name, trig=False):
        # 文件头：S100 HEAD[PIN_NAME] 框架（lable pattern 多一个 TRIGPIN 引脚）；
        # Chroma SET_DEC_FILE + SPM_PATTERN 框架（固定三引脚）
        if chroma:
            f.write('SET_DEC_FILE "pin.dec"\n\nHEADER\n\n' + G.col("VERSION", "CLK PIN")[0] + ", "
                    + G.col("VERSION", "SWD PIN")[0] + ', NRST;\n\nSPM_PATTERN(' + name + ') {\n\n')
        else:
            f.write('HEAD[PIN_NAME]:\n\n' + G.col("VERSION", "CLK PIN")[0] + ', ' + G.col("VERSION", "SWD PIN")[0]
                    + (', NRST, TRIGPIN;' if trig else ', NRST;') + '\n\nEND_HEAD;\n\n@@PATTERN_DEFINE\n\n')

    def file_start(f, n):
        # 起始两拍：S100 为 START 标签行 + RPT 100；Chroma 为 TS1 行 + RPT 100
        if chroma:
            f.write(_vec("011", n, ";", _ts("normal")) + "\n")
        else:
            f.write((n - len("START:")) * " " + "START:" + "011" + pattern_end + "\n")
        f.write(V("011", n, "RPT 100;") + "\n")

    def file_tail(f, n):
        f.write(V("101", n) + "\n")
        if chroma:
            f.write(n * " " + "*011*STOP;\n\n}")
        else:
            f.write((n - len("END:")) * " " + "END:" + "011" + pattern_end + "\n\n@@END_PATTERN_DEFINE ")

    def ecc_flags(vector_end, space_rpt=True):
        # ECC 编程/读取拍；space_rpt=False 对应原 S100 uid read 分支 "RPT" 无空格写法（原样保留）
        if G.col("FLASH_EPR", "ecc")[0] != 0:
            rpt = "RPT " if space_rpt else "RPT"
            if chroma:
                return ("*101*" + rpt + str(G.col("FLASH_EPR", "ecc")[0]) + ";// ECC program\n",
                        "*1X1*" + rpt + str(G.col("FLASH_EPR", "ecc")[0]) + ";// ECC read\n")
            return ("101" + vector_end + rpt + str(G.col("FLASH_EPR", "ecc")[0]) + ";// ECC program\n",
                    "1X1" + vector_end + rpt + str(G.col("FLASH_EPR", "ecc")[0]) + ";// ECC read\n")
        return ("\n", "\n")

    def capture_run(f, count, comment):
        # capture 拍：S100 逐拍 1L1+PTN_TRIG（额外引脚列由 pattern_end="0;" 置 0 触发）；
        # Chroma 用 K 位折叠为一行（*1K1*RPT n;），由 .pln 运行时按 label+位移取数
        if chroma:
            f.write(V("1K1", 6, "RPT " + str(count) + ";") + comment + "\n")
        else:
            for index in range(0, count):
                f.write(V("1L1", 6, "PTN_TRIG;") + (comment if index == 0 else "") + "\n")

    addr_map_item=[]
    read_cyc = []
    prog_cyc = []
    page_word = G.col("VERSION", "page word")[0]
    read_bit = output_num
    prog_output_num = G.col("VERSION", "program bit")[0]
    group_size = output_num // 32
    prog_group_size = prog_output_num // 32

    for i in range(0,page_word):
        read_cyc.append((i // group_size) * group_size + (group_size - 1 - (i % group_size)))
        prog_cyc.append((i // prog_group_size) * prog_group_size + (prog_group_size - 1 - (i % prog_group_size)))
    for z in range(len(G.col("ADDR_MAP", "Word No."))):
        if G.col("ADDR_MAP", "Word No.")[z] not in addr_map_item:
            addr_map_item.append(G.col("ADDR_MAP", "Word No.")[z])
    label_count_temp = []
    label_count_dic = {}
    for cyc in range(len(addr_map_item)):
        label_count_temp.clear()
        if addr_map_item[cyc] != "uid":
            for i in range(0 + page_word*cyc, page_word + page_word*cyc):
                if G.col("ADDR_MAP", "data type")[i] == "lable":
                    if "反码" in G.col("ADDR_MAP", "bit[31:16]")[i]:
                        try:
                            label_count_temp.append(G.col("ADDR_MAP", "bit[15:0]")[i].split("[")[0])
                        except:
                            label_count_temp.append(G.col("ADDR_MAP", "bit[15:0]")[i])
                    else:
                        try:
                            label_count_temp.append(G.col("ADDR_MAP", "bit[15:0]")[i].split("[")[0])
                        except:
                            label_count_temp.append(G.col("ADDR_MAP", "bit[15:0]")[i])
                    label_count_temp.append(G.col("ADDR_MAP", "bit[15:0]")[i].split("[")[0])

            try:
                label_count_dic[addr_map_item[cyc]] = len(max(label_count_temp, key=lambda s: len(s)))
            except:
                label_count_dic[addr_map_item[cyc]] = 0

        else:
            for i in range(0 + page_word*cyc, page_word + page_word*cyc):
                if G.col("ADDR_MAP", "data type")[i] == "lable":
                    if "反码" in G.col("ADDR_MAP", "bit[31:16]")[i]:
                        try:
                            label_count_temp.append(G.col("ADDR_MAP", "bit[15:0]")[i].split("[")[0].split("Verify")[0])

                        except:
                            label_count_temp.append(G.col("ADDR_MAP", "bit[15:0]")[i])

                    elif "bit[31:16]的反码" in G.col("ADDR_MAP", "bit[15:0]")[i]:

                        try:
                            label_count_temp.append(G.col("ADDR_MAP", "bit[31:16]")[i].split("[")[0].split("Verify")[0])
                        except:
                            label_count_temp.append(G.col("ADDR_MAP", "bit[31:16]")[i])

                    else:
                        try:
                            label_count_temp.append(G.col("ADDR_MAP", "bit[15:0]")[i].split("[")[0].split("Verify")[0])
                        except:
                            label_count_temp.append(G.col("ADDR_MAP", "bit[15:0]")[i])


            try:
                label_count_dic[addr_map_item[cyc]] = len(max(label_count_temp, key=lambda s: len(s)))
            except:
                label_count_dic[addr_map_item[cyc]] = 0
    if label_count_dic["uid"] <=18 :
        label_count_dic["uid"]=18

    # print(lable_count_dic)

    data_num = 0
    # erase
    for cyc in range(len(addr_map_item)):
        ra_binary_str = bin(int(G.col("ADDR_MAP", "SM Address")[0 + page_word * cyc].split(";")[0].split("=")[1], 16))[2:]

        with open(G.BASE_DIR + "\\pat_temp\\fbist_page_erase_" + addr_map_item[cyc] + ext, 'w') as f:
            file_head(f, "fbist_page_erase_" + addr_map_item[cyc])
            pattern_end = ";"

            file_start(f, 6)
            erase_head = flash_erase(6, pattern_end,ra_binary_str, "1", "page",0)
            f.write(erase_head)
            file_tail(f, 6)

#prog
    for cyc in range(len(addr_map_item)):
        ra_binary_str = bin(int(G.col("ADDR_MAP", "SM Address")[0 + page_word * cyc].split(";")[0].split("=")[1], 16))[2:]
        if addr_map_item[cyc] != "uid":
            with open(G.BASE_DIR + "\\pat_temp\\fbist_page_prog_" + addr_map_item[cyc] + ext, 'w') as f:
                if "lable" in G.col("ADDR_MAP", "data type")[page_word*cyc:page_word*(cyc+1)]:
                    file_head(f, "fbist_page_prog_" + addr_map_item[cyc], trig=True)
                    pattern_end = "1;"
                else:
                    file_head(f, "fbist_page_prog_" + addr_map_item[cyc])
                    pattern_end = ";"
                # ECC 行与该页的 HEADER 使用相同的向量尾：带 TRIGPIN 的 label 页必须补第 4 位 `1`。
                ecc_pgm_flag, ecc_read_flag = ecc_flags(
                    "1;" if "lable" in G.col("ADDR_MAP", "data type")[page_word*cyc:page_word*(cyc+1)] else ";"
                )
                # prog_title =
                read_title = "\n*111*;\n*1L1*;\n\n"
                file_start(f, label_count_dic[addr_map_item[cyc]]+8)
                program_head, program_end = flash_program((label_count_dic[addr_map_item[cyc]] + 8), pattern_end,
                                                          ra_binary_str, "1", "page","page",0)
                f.write(program_head[0])
                f.write("\n"+ V("111", label_count_dic[addr_map_item[cyc]]+8) + "\n"
                + V("110", label_count_dic[addr_map_item[cyc]]+8) + "// 1 bit strobe\n"
                + V("111", label_count_dic[addr_map_item[cyc]]+8, "RPT 2;") + "// mode[3:0]=1001 write data\n"
                + V("101", label_count_dic[addr_map_item[cyc]]+8, "RPT 2;") + "\n"
                + V("111", label_count_dic[addr_map_item[cyc]]+8) + "\n\n"
                +(label_count_dic[addr_map_item[cyc]]+8) * " " +ecc_pgm_flag)
                for i in range(0, page_word):
                    if i != 0 and i % prog_group_size == 0:
                        f.write("\n"+ V("111", label_count_dic[addr_map_item[cyc]]+8) + "\n"
                + V("110", label_count_dic[addr_map_item[cyc]]+8) + "// 1 bit strobe\n"
                + V("111", label_count_dic[addr_map_item[cyc]]+8, "RPT 2;") + "// mode[3:0]=1001 write data\n"
                + V("101", label_count_dic[addr_map_item[cyc]]+8, "RPT 2;") + "\n"
                + V("111", label_count_dic[addr_map_item[cyc]]+8) + "\n\n"
                +(label_count_dic[addr_map_item[cyc]]+8) * " " +ecc_pgm_flag)

                    f.write((label_count_dic[addr_map_item[cyc]]+8) * " " + "//" + "wdata[" + str(prog_cyc[i]) + "]=" + str(G.col("ADDR_MAP", "CP Data[31:0]")[prog_cyc[i]+page_word*cyc]) + "\n")
                    if G.col("ADDR_MAP", "data type")[prog_cyc[i]+page_word*cyc] != "lable":
                        if G.col("ADDR_MAP", "CP Data[31:0]")[prog_cyc[i]+page_word*cyc] == "32'hFFFF_FFFF":
                            f.write(V("111", label_count_dic[addr_map_item[cyc]]+8, "RPT 32;") + "\n")
                        elif G.col("ADDR_MAP", "CP Data[31:0]")[prog_cyc[i]+page_word*cyc] == "32'h0000_FFFF":
                            f.write(V("101", label_count_dic[addr_map_item[cyc]]+8, "RPT 16;") + "\n")
                            f.write(V("111", label_count_dic[addr_map_item[cyc]]+8, "RPT 16;") + "\n")
                        elif G.col("ADDR_MAP", "CP Data[31:0]")[prog_cyc[i]+page_word*cyc] == "32'hFFFF_0000":
                            f.write(V("111", label_count_dic[addr_map_item[cyc]]+8, "RPT 16;") + "\n")
                            f.write(V("101", label_count_dic[addr_map_item[cyc]]+8, "RPT 16;") + "\n")
                        elif G.col("ADDR_MAP", "CP Data[31:0]")[prog_cyc[i]+page_word*cyc] == "32'h0000_0000":
                            f.write(V("101", label_count_dic[addr_map_item[cyc]]+8, "RPT 32;") + "\n")
                        else:
                            wbits = hex_to_Wbin_32bit(G.col("ADDR_MAP", "CP Data[31:0]")[prog_cyc[i]+page_word*cyc].split("h")[1])
                            for j in range(len(wbits)):
                                f.write(V("1" + wbits[j] + "1", label_count_dic[addr_map_item[cyc]]+8) + "\n")

                                if (j+1) %4 ==0 and j!=0:
                                    f.write("\n")
                    else:
                        wbits = hex_to_Wbin_32bit(G.col("ADDR_MAP", "CP Data[31:0]")[prog_cyc[i]+page_word*cyc].split("h")[1])
                        for j in range(len(wbits)):
                            if "反码" in G.col("ADDR_MAP", "bit[31:16]")[prog_cyc[i]+page_word*cyc]:
                                if j == 0:
                                    pattern_end = "0;"
                                    try:
                                        f.write(LV((label_count_dic[addr_map_item[cyc]])-len(G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].split("[")[0]),
                                                G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].split("[")[0].lower() + "_w_n_st:",
                                                "1" + wbits[j] + "1") + "\n")

                                    except:
                                        f.write(LV((label_count_dic[addr_map_item[cyc]])-len(G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc]),
                                                G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].split("[")[0].lower() + "_w_n_st:",
                                                "1" + wbits[j] + "1") + "\n")

                                elif j == 15:
                                    try:
                                        f.write(LV((label_count_dic[addr_map_item[cyc]])-len(G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].split("[")[0]),
                                                G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].split("[")[0].lower() + "_w_n_sp:",
                                                "1" + wbits[j] + "1") + "\n")

                                    except:
                                        f.write(LV((label_count_dic[addr_map_item[cyc]])-len(G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc]),
                                                G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].split("[")[0].lower() + "_w_n_sp:",
                                                "1" + wbits[j] + "1") + "\n")

                                elif j == 16:
                                    try:
                                        f.write(LV((label_count_dic[addr_map_item[cyc]])-len(G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].split("[")[0]),
                                                G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].split("[")[0].lower() + "_w_p_st:",
                                                "1" + wbits[j] + "1") + "\n")

                                    except:
                                        f.write(LV((label_count_dic[addr_map_item[cyc]])-len(G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc]),
                                                G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].split("[")[0].lower() + "_w_p_st:",
                                                "1" + wbits[j] + "1") + "\n")

                                elif j == 31:
                                    try:
                                        f.write(LV((label_count_dic[addr_map_item[cyc]])-len(G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].split("[")[0]),
                                                G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].split("[")[0].lower() + "_w_p_sp:",
                                                "1" + wbits[j] + "1") + "\n")

                                    except:
                                        f.write(LV((label_count_dic[addr_map_item[cyc]])-len(G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc]),
                                                G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].split("[")[0].lower() + "_w_p_sp:",
                                                "1" + wbits[j] + "1") + "\n")
                                    pattern_end = "1;"
                                else:
                                    f.write(V("1" + wbits[j] + "1", label_count_dic[addr_map_item[cyc]]+8) + "\n")


                            else:
                                if j == 16:
                                    pattern_end = "0;"
                                    try:
                                        f.write(LV((label_count_dic[addr_map_item[cyc]]+2)-len(G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].split("[")[0]),
                                                G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].split("[")[0].lower() + "_w_st:",
                                                "1" + wbits[j] + "1") + "\n")

                                    except:
                                        f.write(LV((label_count_dic[addr_map_item[cyc]]+2)-len(G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc]),
                                                G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].lower() + "_w_st:",
                                                "1" + wbits[j] + "1") + "\n")

                                elif j == 31:
                                    try:
                                        f.write(LV((label_count_dic[addr_map_item[cyc]]+2)-len(G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].split("[")[0]),
                                                G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].split("[")[0].lower() + "_w_sp:",
                                                "1" + wbits[j] + "1") + "\n")

                                    except:
                                        f.write(LV((label_count_dic[addr_map_item[cyc]]+2)-len(G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc]),
                                                G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].lower() + "_w_sp:",
                                                "1" + wbits[j] + "1") + "\n")
                                    pattern_end = "1;"
                                else:
                                    f.write(V("1" + wbits[j] + "1", label_count_dic[addr_map_item[cyc]]+8) + "\n")

                            if (j + 1) % 16 == 0 and j != 0:
                                f.write("\n")
                        pattern_end = "1;"
                f.write(program_end[0])
                file_tail(f, label_count_dic[addr_map_item[cyc]]+8)

        else:
            uid_pattern_item = {"cp1_id":"65FF_FFFF","cp2_id":"65BA_78FF","cp3_id":"65BA_78BA","cp1_bake_id":"65BA_FFFF","cp2_bake_id":"65BA_78BA"}
            for u in uid_pattern_item.keys():
                with open(G.BASE_DIR + "\\pat_temp\\fbist_page_prog_" + u + ext, 'w') as f:
                    if "lable" in G.col("ADDR_MAP", "data type")[page_word*cyc:page_word*(cyc+1)]:
                        file_head(f, "fbist_page_prog_" + u, trig=True)
                        pattern_end = "1;"

                    else:
                        file_head(f, "fbist_page_prog_" + u)
                        pattern_end = ";"
                    ecc_pgm_flag, ecc_read_flag = ecc_flags(pattern_end)
                    # prog_title =
                    read_title = "\n*111*;\n*1L1*;\n\n"

                    file_start(f, label_count_dic[addr_map_item[cyc]] + 4)
                    program_head, program_end = flash_program((label_count_dic[addr_map_item[cyc]] + 4), pattern_end,
                                                              ra_binary_str, "1", "page","page",0)
                    f.write(program_head[0])
                    f.write("\n" + V("111", label_count_dic[addr_map_item[cyc]] + 4) + "\n"
                            + V("110", label_count_dic[addr_map_item[cyc]] + 4) + "// 1 bit strobe\n"
                            + V("111", label_count_dic[addr_map_item[cyc]] + 8, "RPT 2;") + "// mode[3:0]=1001 write data\n"
                            + V("101", label_count_dic[addr_map_item[cyc]] + 4, "RPT 2;") + "\n"
                            + V("111", label_count_dic[addr_map_item[cyc]] + 4) + "\n\n"
                            +(label_count_dic[addr_map_item[cyc]]+4) * " " +ecc_pgm_flag)

                    for i in range(0, page_word):
                        if i != 0 and i % prog_group_size == 0:
                            f.write(V("111", label_count_dic[addr_map_item[cyc]] + 4) + "\n"
                                    + V("110", label_count_dic[addr_map_item[cyc]] + 4) + "// 1 bit strobe\n"
                                    + V("111", label_count_dic[addr_map_item[cyc]] + 4, "RPT 2;") + "// mode[3:0]=1001 write data\n"
                                    + V("101", label_count_dic[addr_map_item[cyc]] + 4, "RPT 2;") + "\n"
                                    + V("111", label_count_dic[addr_map_item[cyc]] + 4) + "\n\n"
                                    +(label_count_dic[addr_map_item[cyc]]+4) * " " +ecc_pgm_flag)
                        if prog_cyc[i]+page_word*cyc == 5 + page_word * cyc:
                            f.write((label_count_dic[addr_map_item[cyc]] + 4) * " " +"//" + "wdata[" + str(prog_cyc[i]) + "]=0x" + str(uid_pattern_item[u]) + "\n")
                        elif u=="cp3_id" and prog_cyc[i]+page_word*cyc == 6 + page_word*cyc:
                            f.write((label_count_dic[addr_map_item[cyc]] + 4) * " " +"//" + "wdata[" + str(prog_cyc[i]) + "]=0x" + str("9AFF_FFFF") + "\n")
                        elif u=="cp3_id" and prog_cyc[i]+page_word*cyc == 3+ page_word*cyc:
                            f.write((label_count_dic[addr_map_item[cyc]] + 4) * " " +"//" + "wdata[" + str(prog_cyc[i]) + "]=0x" + str("FFFF_FF78") + "\n")

                        else:
                            f.write((label_count_dic[addr_map_item[cyc]] + 4) * " " +"//"+"wdata["+str(prog_cyc[i])+"]=0x"+str(G.col("ADDR_MAP", "CP Data[31:0]")[prog_cyc[i]+page_word*cyc].split("h")[1])+"\n")
                        if G.col("ADDR_MAP", "data type")[prog_cyc[i]+page_word*cyc] != "lable":
                            if u == "cp3_id":
                                if prog_cyc[i]+page_word*cyc == 0 + page_word * cyc:
                                    pattern_end="0;"
                                    wbits = hex_to_Wbin_32bit(G.col("ADDR_MAP", "CP Data[31:0]")[prog_cyc[i]+page_word*cyc].split("h")[1])
                                    for j in range(len(wbits)):
                                        if j == 0:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("lot_number_w0"), "lot_number_w0_st:",
                                                    "1" + wbits[j] + "1") + "\n")
                                        elif j == 31:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("lot_number_w0"), "lot_number_w0_sp:",
                                                    "1" + wbits[j] + "1") + "\n")
                                            pattern_end = "1;"
                                        else:
                                            f.write(V("1" + wbits[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) + "\n")
                                        if (j + 1) % 16 == 0 and j != 0:
                                            f.write("\n")

                                elif prog_cyc[i]+page_word*cyc == 1 + page_word * cyc:
                                    pattern_end="0;"
                                    wbits = hex_to_Wbin_32bit(G.col("ADDR_MAP", "CP Data[31:0]")[prog_cyc[i]+page_word*cyc].split("h")[1])
                                    for j in range(len(wbits)):
                                        if j == 0:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("lot_number_w1"), "lot_number_w1_st:",
                                                    "1" + wbits[j] + "1") + "\n")
                                        elif j == 23:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("lot_number_w1"), "lot_number_w1_sp:",
                                                    "1" + wbits[j] + "1") + "\n")
                                        elif j == 24:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("slot_number_w"), "slot_number_w_st:",
                                                    "1" + wbits[j] + "1") + "\n")
                                        elif j == 31:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("slot_number_w"), "slot_number_w_sp:",
                                                    "1" + wbits[j] + "1") + "\n")
                                            pattern_end = "1;"
                                        else:
                                            f.write(V("1" + wbits[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) + "\n")
                                        if (j + 1) % 16 == 0 and j != 0:
                                            f.write("\n")

                                elif prog_cyc[i]+page_word*cyc == 2 + page_word * cyc:
                                    pattern_end = "0;"
                                    wbits = hex_to_Wbin_32bit(G.col("ADDR_MAP", "CP Data[31:0]")[prog_cyc[i]+page_word*cyc].split("h")[1])
                                    for j in range(len(wbits)):
                                        if j == 0:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("xy_coor_w"), "xy_coor_w_st:",
                                                    "1" + wbits[j] + "1") + "\n")
                                        elif j == 7:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("xy_coor_w"), "xy_coor_w_sp:",
                                                    "1" + wbits[j] + "1") + "\n")
                                        elif j == 8:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("x_coor_w"), "x_coor_w_st:",
                                                    "1" + wbits[j] + "1") + "\n")
                                        elif j == 15:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("x_coor_w"), "x_coor_w_sp:",
                                                    "1" + wbits[j] + "1") + "\n")
                                        elif j == 16:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("y_coor_w"), "y_coor_w_st:",
                                                    "1" + wbits[j] + "1") + "\n")
                                        elif j == 23:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("y_coor_w"), "y_coor_w_sp:",
                                                    "1" + wbits[j] + "1") + "\n")
                                        elif j == 24:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("year_month_w"), "year_month_w_st:",
                                                    "1" + wbits[j] + "1") + "\n")
                                        elif j == 31:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("year_month_w"), "year_month_w_sp:",
                                                    "1" + wbits[j] + "1") + "\n")
                                            pattern_end = "1;"
                                        else:
                                            f.write(V("1" + wbits[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) + "\n")
                                        if (j + 1) % 16 == 0 and j != 0:
                                            f.write("\n")

                                elif prog_cyc[i]+page_word*cyc == 3 + page_word * cyc:
                                    pattern_end = "0;"
                                    wbits = hex_to_Wbin_32bit(G.col("ADDR_MAP", "CP Data[31:0]")[prog_cyc[i]+page_word*cyc].split("h")[1])
                                    for j in range(len(wbits)):
                                        if j == 0:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("testing_house_id_w"), "testing_house_id_w_st:",
                                                    "1" + hex_to_Wbin_32bit("FFFF_FF78")[j] + "1") + "\n")
                                        elif j == 7:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("testing_house_id_w"), "testing_house_id_w_sp:",
                                                    "1" + hex_to_Wbin_32bit("FFFF_FF78")[j] + "1") + "\n")
                                        elif j == 8:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("cp_ver_no_w"), "cp_ver_no_w_st:",
                                                    "1" + hex_to_Wbin_32bit("FFFF_FF78")[j] + "1") + "\n")
                                        elif j == 15:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("cp_ver_no_w"), "cp_ver_no_w_sp:",
                                                    "1" + hex_to_Wbin_32bit("FFFF_FF78")[j] + "1") + "\n")
                                        elif j == 16:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("crc_8_w"), "crc_8_w_st:",
                                                    "1" + hex_to_Wbin_32bit("FFFF_FF78")[j] + "1") + "\n")
                                        elif j == 23:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("crc_8_w"), "crc_8_w_sp:",
                                                    "1" + hex_to_Wbin_32bit("FFFF_FF78")[j] + "1") + "\n")
                                            pattern_end = "1;"
                                        else:
                                            f.write(V("1" + hex_to_Wbin_32bit("FFFF_FF78")[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) + "\n")

                                        if (j + 1) % 16 == 0 and j != 0:
                                            f.write("\n")

                                elif prog_cyc[i]+page_word*cyc == 4 + page_word * cyc:
                                    pattern_end = "0;"
                                    wbits = hex_to_Wbin_32bit(G.col("ADDR_MAP", "CP Data[31:0]")[prog_cyc[i]+page_word*cyc].split("h")[1])
                                    for j in range(len(wbits)):
                                        if j == 0:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("cp1_ver_w"), "cp1_ver_w_st:",
                                                    "1" + wbits[j] + "1") + "\n")
                                        elif j == 7:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("cp1_ver_w"), "cp1_ver_w_sp:",
                                                    "1" + wbits[j] + "1") + "\n")
                                        elif j == 8:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("cp2_ver_w"), "cp2_ver_w_st:",
                                                    "1" + wbits[j] + "1") + "\n")
                                        elif j == 15:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("cp2_ver_w"), "cp2_ver_w_sp:",
                                                    "1" + wbits[j] + "1") + "\n")
                                            pattern_end = "1;"
                                        else:
                                            f.write(V("1" + wbits[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) + "\n")
                                        if (j + 1) % 16 == 0 and j != 0:
                                            f.write("\n")

                                elif prog_cyc[i]+page_word*cyc == 5 + page_word * cyc:
                                    wbits = hex_to_Wbin_32bit(G.col("ADDR_MAP", "CP Data[31:0]")[prog_cyc[i]+page_word*cyc].split("h")[1])
                                    for j in range(len(wbits)):
                                        if j == 0:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("cp12_id_w"), "cp12_id_w_st:",
                                                    "1" + hex_to_Wbin_32bit(uid_pattern_item[u])[j] + "1") +"//"+ str(bin8_to_hex(str(hex_to_Wbin_32bit(uid_pattern_item[u])[j:j+8])))+"\n")
                                        elif j == 31:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("cp12_id_w"), "cp12_id_w_sp:",
                                                    "1" + hex_to_Wbin_32bit(uid_pattern_item[u])[j] + "1") + "\n")
                                        elif (j) % 8 == 0:
                                            f.write(V("1" + hex_to_Wbin_32bit(uid_pattern_item[u])[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) +"//"+ str(bin8_to_hex(str(hex_to_Wbin_32bit(uid_pattern_item[u])[j:j+8])))+"\n")
                                        else:
                                            f.write(V("1" + hex_to_Wbin_32bit(uid_pattern_item[u])[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) + "\n")
                                        if (j + 1) % 8 == 0 and j != 0:
                                            f.write("\n")
                                elif prog_cyc[i]+page_word*cyc == 6 + page_word * cyc:
                                    wbits = hex_to_Wbin_32bit(G.col("ADDR_MAP", "CP Data[31:0]")[prog_cyc[i]+page_word*cyc].split("h")[1])
                                    for j in range(len(wbits)):
                                        if j == 0:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("cp34_id_w"), "cp34_id_w_st:",
                                                    "1" + hex_to_Wbin_32bit("9AFF_FFFF")[j] + "1") + "//" + str(bin8_to_hex(str(hex_to_Wbin_32bit("9AFF_FFFF")[j:j + 8]))) + "\n")
                                        elif j == 31:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("cp34_id_w"), "cp34_id_w_sp:",
                                                    "1" + hex_to_Wbin_32bit("9AFF_FFFF")[j] + "1") + "\n")
                                        elif (j) % 8 == 0:
                                            f.write(V("1" + hex_to_Wbin_32bit("9AFF_FFFF")[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) + "//" + str(bin8_to_hex(str(hex_to_Wbin_32bit("9AFF_FFFF")[j:j + 8]))) + "\n")
                                        else:
                                            f.write(V("1" + hex_to_Wbin_32bit("9AFF_FFFF")[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) + "\n")

                                        if (j + 1) % 8 == 0 and j != 0:
                                            f.write("\n")
                                elif prog_cyc[i]+page_word*cyc == 15 + page_word * cyc:
                                    pattern_end = "0;"
                                    wbits = hex_to_Wbin_32bit(G.col("ADDR_MAP", "CP Data[31:0]")[prog_cyc[i]+page_word*cyc].split("h")[1])
                                    for j in range(len(wbits)):
                                        if j == 0:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("project_w_n"), "project_w_n_st:",
                                                    "1" + wbits[j] + "1") + "\n")
                                        elif j == 15:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("project_w_n"), "project_w_n_sp:",
                                                    "1" + wbits[j] + "1") + "\n")
                                        elif j == 16:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("project_w_p"), "project_w_p_st:",
                                                    "1" + wbits[j] + "1") + "\n")
                                        elif j == 31:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("project_w_p"), "project_w_p_sp:",
                                                    "1" + wbits[j] + "1") + "\n")
                                            pattern_end = "1;"
                                        else:
                                            f.write(V("1" + wbits[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) + "\n")

                                        if (j + 1) % 16 == 0 and j != 0:
                                            f.write("\n")

                                elif G.col("ADDR_MAP", "CP Data[31:0]")[prog_cyc[i]+page_word*cyc] == "32'hFFFF_FFFF":
                                    f.write(V("111", label_count_dic[addr_map_item[cyc]] + 4, "RPT 32;") + "\n")
                                elif G.col("ADDR_MAP", "CP Data[31:0]")[prog_cyc[i]+page_word*cyc] == "32'h0000_FFFF":
                                    f.write(V("101", label_count_dic[addr_map_item[cyc]] + 4, "RPT 16;") + "\n")
                                    f.write(V("111", label_count_dic[addr_map_item[cyc]] + 4, "RPT 16;") + "\n")
                                elif G.col("ADDR_MAP", "CP Data[31:0]")[prog_cyc[i]+page_word*cyc] == "32'hFFFF_0000":
                                    f.write(V("111", label_count_dic[addr_map_item[cyc]] + 4, "RPT 16;") + "\n")
                                    f.write(V("101", label_count_dic[addr_map_item[cyc]] + 4, "RPT 16;") + "\n")
                                elif G.col("ADDR_MAP", "CP Data[31:0]")[prog_cyc[i]+page_word*cyc] == "32'h0000_0000":
                                    f.write(V("101", label_count_dic[addr_map_item[cyc]] + 4, "RPT 32;") + "\n")
                                else:
                                    wbits = hex_to_Wbin_32bit(G.col("ADDR_MAP", "CP Data[31:0]")[prog_cyc[i]+page_word*cyc].split("h")[1])
                                    for j in range(len(wbits)):
                                        f.write(V("1" + wbits[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) + "\n")
                                        if (j+1) %4 ==0 and j!=0:
                                            f.write("\n")

                            else:
                                if prog_cyc[i]+page_word*cyc == 5 + page_word * cyc:
                                    wbits = hex_to_Wbin_32bit(G.col("ADDR_MAP", "CP Data[31:0]")[prog_cyc[i]+page_word*cyc].split("h")[1])
                                    for j in range(len(wbits)):
                                        if j == 0:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("cp12_id_w"), "cp12_id_w_st:",
                                                    "1" + hex_to_Wbin_32bit(uid_pattern_item[u])[j] + "1") +"//"+str(bin8_to_hex(str(hex_to_Wbin_32bit(uid_pattern_item[u])[j:j+8])))+"\n")

                                        elif j == 31:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("cp12_id_w"), "cp12_id_w_sp:",
                                                    "1" + hex_to_Wbin_32bit(uid_pattern_item[u])[j] + "1") + "\n")

                                        elif (j) % 8 == 0:
                                            f.write(V("1" + hex_to_Wbin_32bit(uid_pattern_item[u])[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) +"//"+str(bin8_to_hex(str(hex_to_Wbin_32bit(uid_pattern_item[u])[j:j+8])))+"\n")

                                        else:
                                            f.write(V("1" + hex_to_Wbin_32bit(uid_pattern_item[u])[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) + "\n")

                                        if (j + 1) % 8 == 0 and j != 0:
                                            f.write("\n")
                                elif G.col("ADDR_MAP", "CP Data[31:0]")[prog_cyc[i]+page_word*cyc] == "32'hFFFF_FFFF":
                                    f.write(V("111", label_count_dic[addr_map_item[cyc]] + 4, "RPT 32;") + "\n")
                                elif G.col("ADDR_MAP", "CP Data[31:0]")[prog_cyc[i]+page_word*cyc] == "32'h0000_FFFF":
                                    f.write(V("101", label_count_dic[addr_map_item[cyc]] + 4, "RPT 16;") + "\n")
                                    f.write(V("111", label_count_dic[addr_map_item[cyc]] + 4, "RPT 16;") + "\n")
                                elif G.col("ADDR_MAP", "CP Data[31:0]")[prog_cyc[i]+page_word*cyc] == "32'hFFFF_0000":
                                    f.write(V("111", label_count_dic[addr_map_item[cyc]] + 4, "RPT 16;") + "\n")
                                    f.write(V("101", label_count_dic[addr_map_item[cyc]] + 4, "RPT 16;") + "\n")
                                elif G.col("ADDR_MAP", "CP Data[31:0]")[prog_cyc[i]+page_word*cyc] == "32'h0000_0000":
                                    f.write(V("101", label_count_dic[addr_map_item[cyc]] + 4, "RPT 32;") + "\n")
                                else:
                                    wbits = hex_to_Wbin_32bit(G.col("ADDR_MAP", "CP Data[31:0]")[prog_cyc[i]+page_word*cyc].split("h")[1])
                                    for j in range(len(wbits)):
                                        f.write(V("1" + wbits[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) + "\n")

                                        if (j+1) %4 ==0 and j!=0:
                                            f.write("\n")
                        else:
                            pattern_end = "0;"
                            wbits = hex_to_Wbin_32bit(G.col("ADDR_MAP", "CP Data[31:0]")[prog_cyc[i]+page_word*cyc].split("h")[1])
                            for j in range(len(wbits)):
                                if "反码" in G.col("ADDR_MAP", "bit[31:16]")[prog_cyc[i]+page_word*cyc]:

                                    if j == 0:
                                        try:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0])-3,
                                                    G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0].lower() + "w_n_st:",
                                                    "1" + wbits[j] + "1") + "\n")
                                        except:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc])-3,
                                                    G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].lower() + "w_n_st:",
                                                    "1" + wbits[j] + "1") + "\n")
                                    elif j == 15:
                                        try:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0])-3,
                                                    G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0].lower() + "w_n_sp:",
                                                    "1" + wbits[j] + "1") + "\n")
                                        except:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc])-3,
                                                    G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].lower() + "w_n_sp:",
                                                    "1" + wbits[j] + "1") + "\n")
                                    elif j == 16:
                                        try:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0])-3,
                                                    G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0].lower() + "w_p_st:",
                                                    "1" + wbits[j] + "1") + "\n")
                                        except:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc])-3,
                                                    G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].lower() + "w_p_st:",
                                                    "1" + wbits[j] + "1") + "\n")
                                    elif j == 31:
                                        try:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0])-3,
                                                    G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0].lower() + "w_p_sp:",
                                                    "1" + wbits[j] + "1") + "\n")
                                        except:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc])-3,
                                                    G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].lower() + "w_p_sp:",
                                                    "1" + wbits[j] + "1") + "\n")
                                    else:

                                        f.write(V("1" + wbits[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) + "\n")

                                elif "bit[31:16]的反码" in G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc]:
                                    if j == 0:
                                        try:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[31:16]")[prog_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0])-3,
                                                    G.col("ADDR_MAP", "bit[31:16]")[prog_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0].lower() + "w_p_st:",
                                                    "1" + wbits[j] + "1") + "\n")
                                        except:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[31:16]")[prog_cyc[i]+page_word*cyc])-3,
                                                    G.col("ADDR_MAP", "bit[31:16]")[prog_cyc[i]+page_word*cyc].lower() + "w_p_st:",
                                                    "1" + wbits[j] + "1") + "\n")
                                    elif j == 15:
                                        try:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[31:16]")[prog_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0])-3,
                                                    G.col("ADDR_MAP", "bit[31:16]")[prog_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0].lower() + "w_p_sp:",
                                                    "1" + wbits[j] + "1") + "\n")
                                        except:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[31:16]")[prog_cyc[i]+page_word*cyc])-3,
                                                    G.col("ADDR_MAP", "bit[31:16]")[prog_cyc[i]+page_word*cyc].lower() + "w_p_sp:",
                                                    "1" + wbits[j] + "1") + "\n")

                                    elif j == 16:
                                        try:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[31:16]")[prog_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0])-3,
                                                    G.col("ADDR_MAP", "bit[31:16]")[prog_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0].lower() + "w_n_st:",
                                                    "1" + wbits[j] + "1") + "\n")

                                        except:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[31:16]")[prog_cyc[i]+page_word*cyc])-3,
                                                    G.col("ADDR_MAP", "bit[31:16]")[prog_cyc[i]+page_word*cyc].lower() + "w_n_st:",
                                                    "1" + wbits[j] + "1") + "\n")

                                    elif j == 31:
                                        try:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[31:16]")[prog_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0])-3,
                                                    G.col("ADDR_MAP", "bit[31:16]")[prog_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0].lower() + "w_n_sp:",
                                                    "1" + wbits[j] + "1") + "\n")

                                        except:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[31:16]")[prog_cyc[i]+page_word*cyc])-3,
                                                    G.col("ADDR_MAP", "bit[31:16]")[prog_cyc[i]+page_word*cyc].lower() + "w_n_sp:",
                                                    "1" + wbits[j] + "1") + "\n")
                                    else:
                                        f.write(V("1" + wbits[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) + "\n")

                                else:
                                    if j == 16:
                                        try:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0])-1,
                                                    G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0].lower() + "w_st:",
                                                    "1" + wbits[j] + "1") + "\n")
                                        except:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc])-1,
                                                    G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].lower() + "w_st:",
                                                    "1" + wbits[j] + "1") + "\n")

                                    elif j == 31:
                                        try:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0])-1,
                                                    G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0].lower() + "w_sp:",
                                                    "1" + wbits[j] + "1") + "\n")
                                        except:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc])-1,
                                                    G.col("ADDR_MAP", "bit[15:0]")[prog_cyc[i]+page_word*cyc].lower() + "w_sp:",
                                                    "1" + wbits[j] + "1") + "\n")
                                    else:
                                        f.write(V("1" + wbits[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) + "\n")
                                if (j + 1) % 16 == 0 and j != 0:
                                    f.write("\n")
                        f.write("\n")
                        pattern_end = "1;"
                    f.write(program_end[0])
                    file_tail(f, label_count_dic[addr_map_item[cyc]] + 4)

#read
    for cyc in range(len(addr_map_item)):
        ra_binary_str = bin(int(G.col("ADDR_MAP", "SM Address")[0 + page_word * cyc].split(";")[0].split("=")[1], 16))[2:]
        if addr_map_item[cyc] != "uid":
            with open(G.BASE_DIR + "\\pat_temp\\fbist_page_read_" + addr_map_item[cyc] + ext, 'w') as f:
                if "lable" in G.col("ADDR_MAP", "data type")[page_word*cyc:page_word*(cyc+1)]:
                    file_head(f, "fbist_page_read_" + addr_map_item[cyc], trig=True)
                    pattern_end = "1;"
                else:
                    file_head(f, "fbist_page_read_" + addr_map_item[cyc])
                    pattern_end = ";"
                file_start(f, label_count_dic[addr_map_item[cyc]] + 8)
                read_head = flash_read((label_count_dic[addr_map_item[cyc]] + 8), pattern_end,
                                                          ra_binary_str, "1", "page","0","1","0")
                f.write(read_head[0])

                ecc_pgm_flag, ecc_read_flag = ecc_flags(pattern_end)

                # for i in range(0 + page_word*cyc,32 + page_word*cyc):
                for i in range(0 , page_word ):
                    if i != 0 and i % group_size == 0:
                        f.write(V("111", label_count_dic[addr_map_item[cyc]] + 8) + "\n"+
                                V("1X1", label_count_dic[addr_map_item[cyc]] + 8) + "\n"
                                +(label_count_dic[addr_map_item[cyc]] + 8) * " " +ecc_read_flag)
                    elif i == 0:
                        f.write((label_count_dic[addr_map_item[cyc]] + 8) * " " + ecc_read_flag)
                    f.write((label_count_dic[addr_map_item[cyc]] + 8) * " " + "//" + "rdata[" + str(read_cyc[i]) + "]=" + str(G.col("ADDR_MAP", "CP Data[31:0]")[read_cyc[i]+page_word*cyc]) + "\n")
                    if G.col("ADDR_MAP", "data type")[read_cyc[i]+page_word*cyc] != "lable":
                        if G.col("ADDR_MAP", "CP Data[31:0]")[read_cyc[i]+page_word*cyc] == "32'hFFFF_FFFF":
                            f.write(V("1H1", label_count_dic[addr_map_item[cyc]] + 8, "RPT 32;") + "\n")
                        elif G.col("ADDR_MAP", "CP Data[31:0]")[read_cyc[i]+page_word*cyc] == "32'h0000_FFFF":
                            f.write(V("1L1", label_count_dic[addr_map_item[cyc]] + 8, "RPT 16;") + "\n")
                            f.write(V("1H1", label_count_dic[addr_map_item[cyc]] + 8, "RPT 16;") + "\n")
                        elif G.col("ADDR_MAP", "CP Data[31:0]")[read_cyc[i]+page_word*cyc] == "32'hFFFF_0000":
                            f.write(V("1H1", label_count_dic[addr_map_item[cyc]] + 8, "RPT 16;") + "\n")
                            f.write(V("1L1", label_count_dic[addr_map_item[cyc]] + 8, "RPT 16;") + "\n")
                        elif G.col("ADDR_MAP", "CP Data[31:0]")[read_cyc[i]+page_word*cyc] == "32'h0000_0000":
                            f.write(V("1L1", label_count_dic[addr_map_item[cyc]] + 8, "RPT 32;") + "\n")
                        else:
                            rbits = hex_to_Rbin_32bit(G.col("ADDR_MAP", "CP Data[31:0]")[read_cyc[i]+page_word*cyc].split("h")[1])
                            for j in range(len(rbits)):
                                f.write(V("1" + rbits[j] + "1", label_count_dic[addr_map_item[cyc]] + 8) + "\n")
                                if (j+1) %4 ==0 and j!=0:
                                    f.write("\n")
                    else:

                        rbits = hex_to_Rbin_32bit(G.col("ADDR_MAP", "CP Data[31:0]")[read_cyc[i]+page_word*cyc].split("h")[1])
                        for j in range(len(rbits)):
                            if "反码" in G.col("ADDR_MAP", "bit[31:16]")[read_cyc[i]+page_word*cyc]:
                                if j == 0:
                                    pattern_end = "0;"
                                    try:
                                        # f.write(list(ADDR_MAP["bit[15:0]"])[read_cyc[i]+page_word*cyc].split("[")[0].lower() + "_r_n:\n")
                                        f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].split("[")[0]),
                                                G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].split("[")[0].lower() + "_r_n_st:",
                                                "1" + rbits[j] + "1") + "\n")


                                    except:

                                        f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc]),
                                                G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].lower() + "_r_n_st:",
                                                "1" + rbits[j] + "1") + "\n")

                                elif j == 15:
                                    try:
                                        # f.write(list(ADDR_MAP["bit[15:0]"])[read_cyc[i]+page_word*cyc].split("[")[0].lower() + "_r_n:\n")
                                        f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].split("[")[0]),
                                                G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].split("[")[0].lower() + "_r_n_sp:",
                                                "1" + rbits[j] + "1") + "\n")


                                    except:

                                        f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc]),
                                                G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].lower() + "_r_n_sp:",
                                                "1" + rbits[j] + "1") + "\n")

                                elif j == 16:
                                    try:
                                        f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].split("[")[0]),
                                                G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].split("[")[0].lower() + "_r_p_st:",
                                                "1" + rbits[j] + "1") + "\n")


                                    except:

                                        f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc]),
                                                G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].lower() + "_r_p_st:",
                                                "1" + rbits[j] + "1") + "\n")

                                elif j == 31:
                                    try:
                                        f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].split("[")[0]),
                                                G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].split("[")[0].lower() + "_r_p_sp:",
                                                "1" + rbits[j] + "1") + "\n")



                                    except:

                                        f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc]),
                                                G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].lower() + "_r_p_sp:",
                                                "1" + rbits[j] + "1") + "\n")
                                    pattern_end = "1;"
                                else:
                                    f.write(V("1" + rbits[j] + "1", label_count_dic[addr_map_item[cyc]] + 8) + "\n")

                            else:
                                if j == 16:
                                    pattern_end = "0;"
                                    try:
                                        f.write(LV((label_count_dic[addr_map_item[cyc]]+2) - len(G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].split("[")[0]),
                                                G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].split("[")[0].lower() + "_r_st:",
                                                "1" + rbits[j] + "1") + "\n")

                                    except:
                                        f.write(LV((label_count_dic[addr_map_item[cyc]]+2) - len(G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc]),
                                                G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].lower() + "_r_st:",
                                                "1" + rbits[j] + "1") + "\n")

                                elif j == 31:
                                    try:
                                        f.write(LV((label_count_dic[addr_map_item[cyc]]+2) - len(G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].split("[")[0]),
                                                G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].split("[")[0].lower() + "_r_sp:",
                                                "1" + rbits[j] + "1") + "\n")

                                    except:
                                        f.write(LV((label_count_dic[addr_map_item[cyc]]+2) - len(G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc]),
                                                G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].lower() + "_r_sp:",
                                                "1" + rbits[j] + "1") + "\n")
                                    pattern_end = "1;"

                                else:
                                    f.write(V("1" + rbits[j] + "1", label_count_dic[addr_map_item[cyc]] + 8) + "\n")
                            if (j + 1) % 16 == 0 and j != 0:
                                f.write("\n")
                        pattern_end = "1;"
                    f.write("\n")

                file_tail(f, label_count_dic[addr_map_item[cyc]] + 8)
        else:
            uid_pattern_item = {"cp1_id":"65FF_FFFF","cp2_id":"65BA_78FF","cp3_id":"65BA_78BA","cp1_bake_id":"65BA_FFFF","cp2_bake_id":"65BA_78BA"}
            for u in uid_pattern_item.keys():
                with open(G.BASE_DIR + "\\pat_temp\\fbist_page_read_" + u + ext, 'w') as f:
                    if "lable" in G.col("ADDR_MAP", "data type")[page_word*cyc:page_word*(cyc+1)]:
                        file_head(f, "fbist_page_read_" + u, trig=True)
                        pattern_end = "1;"

                    else:
                        file_head(f, "fbist_page_read_" + u)
                        pattern_end = ";"

                    file_start(f, label_count_dic[addr_map_item[cyc]] + 4)
                    read_head = flash_read((label_count_dic[addr_map_item[cyc]] + 4), pattern_end,
                                           ra_binary_str, "1", "page","0", "1", "0")
                    f.write(read_head[0])
                    ecc_pgm_flag, ecc_read_flag = ecc_flags(pattern_end)

                    for i in range(0 , page_word ):
                        if i != 0 and i % group_size == 0:
                            f.write(V("111", label_count_dic[addr_map_item[cyc]] + 4) + "\n" +
                                    V("1X1", label_count_dic[addr_map_item[cyc]] + 4) + "\n"
                                    +(label_count_dic[addr_map_item[cyc]] + 4) * " " +ecc_read_flag)
                        elif i == 0:
                            f.write((label_count_dic[addr_map_item[cyc]] + 4) * " " + ecc_read_flag)
                        if read_cyc[i]+page_word*cyc == 5 + page_word*cyc:
                            f.write((label_count_dic[addr_map_item[cyc]] + 4) * " " + "//" + "rdata[" + str(read_cyc[i]) + "]=0x" + str(uid_pattern_item[u]) + "\n")

                        elif u=="cp3_id" and read_cyc[i]+page_word*cyc == 6 + page_word*cyc:
                            f.write((label_count_dic[addr_map_item[cyc]] + 4) * " " + "//" + "rdata[" + str(read_cyc[i]) + "]=0x" + str("9AFF_FFFF") + "\n")

                        elif u=="cp3_id" and read_cyc[i]+page_word*cyc == 3 + page_word*cyc:
                            f.write((label_count_dic[addr_map_item[cyc]] + 4) * " " + "//" + "rdata[" + str(read_cyc[i]) + "]=0x" + str("FFFF_FF78") + "\n")
                        else:
                            f.write((label_count_dic[addr_map_item[cyc]] + 4) * " " + "//" + "rdata[" + str(read_cyc[i]) + "]=0x" + str(G.col("ADDR_MAP", "CP Data[31:0]")[read_cyc[i]+page_word*cyc].split("h")[1]) + "\n")

                        if G.col("ADDR_MAP", "data type")[read_cyc[i]+page_word*cyc] != "lable":
                            if u == "cp3_id":
                                if read_cyc[i]+page_word*cyc == 0 + page_word*cyc:
                                    pattern_end = "0;"
                                    rbits = hex_to_Rbin_32bit(G.col("ADDR_MAP", "CP Data[31:0]")[read_cyc[i]+page_word*cyc].split("h")[1])
                                    for j in range(len(rbits)):
                                        if j == 0:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("lot_number_r0"), "lot_number_r0_st:",
                                                    "1" + rbits[j] + "1") + "\n")
                                        elif j == 31:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("lot_number_r0"), "lot_number_r0_sp:",
                                                    "1" + rbits[j] + "1") + "\n")
                                        else:
                                            f.write(V("1" + rbits[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) + "\n")
                                        if (j + 1) % 16 == 0 and j != 0:
                                            f.write("\n")
                                    pattern_end = "1;"
                                elif read_cyc[i]+page_word*cyc == 1 + page_word*cyc:
                                    pattern_end = "0;"
                                    rbits = hex_to_Rbin_32bit(G.col("ADDR_MAP", "CP Data[31:0]")[read_cyc[i]+page_word*cyc].split("h")[1])
                                    for j in range(len(rbits)):
                                        if j == 0:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("lot_number_r1"), "lot_number_r1_st:",
                                                    "1" + rbits[j] + "1") + "\n")
                                        elif j == 23:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("lot_number_r1"), "lot_number_r1_sp:",
                                                    "1" + rbits[j] + "1") + "\n")
                                        elif j == 24:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("slot_number_r"), "slot_number_r_st:",
                                                    "1" + rbits[j] + "1") + "\n")
                                        elif j == 31:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("slot_number_r"), "slot_number_r_sp:",
                                                    "1" + rbits[j] + "1") + "\n")
                                            pattern_end = "1;"
                                        else:
                                            f.write(V("1" + rbits[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) + "\n")

                                        if (j + 1) % 16 == 0 and j != 0:
                                            f.write("\n")


                                elif read_cyc[i]+page_word*cyc == 2 + page_word*cyc:
                                    pattern_end = "0;"
                                    rbits = hex_to_Rbin_32bit(G.col("ADDR_MAP", "CP Data[31:0]")[read_cyc[i]+page_word*cyc].split("h")[1])
                                    for j in range(len(rbits)):
                                        if j == 0:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("xy_coor_r"), "xy_coor_r_st:",
                                                    "1" + rbits[j] + "1") + "\n")
                                        elif j == 7:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("xy_coor_r"), "xy_coor_r_sp:",
                                                    "1" + rbits[j] + "1") + "\n")
                                        elif j == 8:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("x_coor_r"), "x_coor_r_st:",
                                                    "1" + rbits[j] + "1") + "\n")
                                        elif j == 15:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("x_coor_r"), "x_coor_r_sp:",
                                                    "1" + rbits[j] + "1") + "\n")
                                        elif j == 16:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("y_coor_r"), "y_coor_r_st:",
                                                    "1" + rbits[j] + "1") + "\n")
                                        elif j == 23:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("y_coor_r"), "y_coor_r_sp:",
                                                    "1" + rbits[j] + "1") + "\n")
                                        elif j == 24:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("year_month_r"), "year_month_r_st:",
                                                    "1" + rbits[j] + "1") + "\n")
                                        elif j == 31:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("year_month_r"), "year_month_r_sp:",
                                                    "1" + rbits[j] + "1") + "\n")
                                            pattern_end = "1;"
                                        else:
                                            f.write(V("1" + rbits[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) + "\n")

                                        if (j + 1) % 16 == 0 and j != 0:
                                            f.write("\n")

                                elif read_cyc[i]+page_word*cyc == 3 + page_word*cyc:
                                    pattern_end = "0;"
                                    rbits = hex_to_Rbin_32bit(G.col("ADDR_MAP", "CP Data[31:0]")[read_cyc[i]+page_word*cyc].split("h")[1])
                                    for j in range(len(rbits)):
                                        if j == 0:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("testing_house_id_r"), "testing_house_id_r_st:",
                                                    "1" + hex_to_Rbin_32bit("FFFF_FF78")[j] + "1") + "\n")
                                        elif j == 7:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("testing_house_id_r"), "testing_house_id_r_sp:",
                                                    "1" + hex_to_Rbin_32bit("FFFF_FF78")[j] + "1") + "\n")
                                        elif j == 8:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("cp_ver_no_r"), "cp_ver_no_r_st:",
                                                    "1" + hex_to_Rbin_32bit("FFFF_FF78")[j] + "1") + "\n")
                                        elif j == 15:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("cp_ver_no_r"), "cp_ver_no_r_sp:",
                                                    "1" + hex_to_Rbin_32bit("FFFF_FF78")[j] + "1") + "\n")
                                        elif j == 16:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("crc_8_r"), "crc_8_r_st:",
                                                    "1" + hex_to_Rbin_32bit("FFFF_FF78")[j] + "1") + "\n")
                                        elif j == 23:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("crc_8_r"), "crc_8_r_sp:",
                                                    "1" + hex_to_Rbin_32bit("FFFF_FF78")[j] + "1") + "\n")
                                            pattern_end = "1;"

                                        else:
                                            f.write(V("1" + hex_to_Rbin_32bit("FFFF_FF78")[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) + "\n")
                                        if (j + 1) % 16 == 0 and j != 0:
                                            f.write("\n")

                                elif read_cyc[i]+page_word*cyc == 4 + page_word*cyc:
                                    pattern_end = "0;"
                                    rbits = hex_to_Rbin_32bit(G.col("ADDR_MAP", "CP Data[31:0]")[read_cyc[i]+page_word*cyc].split("h")[1])
                                    for j in range(len(rbits)):
                                        if j == 0:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("cp1_ver_r"), "cp1_ver_r_st:",
                                                    "1" + rbits[j] + "1") + "\n")
                                        elif j == 7:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("cp1_ver_r"), "cp1_ver_r_sp:",
                                                    "1" + rbits[j] + "1") + "\n")
                                        elif j == 8:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("cp2_ver_r"), "cp2_ver_r_st:",
                                                    "1" + rbits[j] + "1") + "\n")
                                        elif j == 15:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("cp2_ver_r"), "cp2_ver_r_sp:",
                                                    "1" + rbits[j] + "1") + "\n")
                                            pattern_end = "1;"
                                        else:
                                            f.write(V("1" + rbits[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) + "\n")
                                        if (j + 1) % 16 == 0 and j != 0:
                                            f.write("\n")

                                elif read_cyc[i]+page_word*cyc == 5 + page_word*cyc:
                                    rbits = hex_to_Rbin_32bit(G.col("ADDR_MAP", "CP Data[31:0]")[read_cyc[i]+page_word*cyc].split("h")[1])
                                    for j in range(len(rbits)):
                                        if j == 0:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("cp12_id_r"), "cp12_id_r_st:",
                                                    "1" + hex_to_Rbin_32bit(uid_pattern_item[u])[j] + "1") +"//"+str(bin8_to_hex(str(hex_to_Wbin_32bit(uid_pattern_item[u])[j:j+8])))+"\n")
                                        elif j == 31:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("cp12_id_r"), "cp12_id_r_sp:",
                                                    "1" + hex_to_Rbin_32bit(uid_pattern_item[u])[j] + "1") + "\n")
                                        elif (j) % 8 == 0:
                                            f.write(V("1" + hex_to_Rbin_32bit(uid_pattern_item[u])[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) +"//"+str(bin8_to_hex(str(hex_to_Wbin_32bit(uid_pattern_item[u])[j:j+8])))+"\n")
                                        else:
                                            f.write(V("1" + hex_to_Rbin_32bit(uid_pattern_item[u])[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) + "\n")

                                        if (j + 1) % 8 == 0 and j != 0:
                                            f.write("\n")

                                elif read_cyc[i]+page_word*cyc == 6 + page_word*cyc:
                                    rbits = hex_to_Rbin_32bit(G.col("ADDR_MAP", "CP Data[31:0]")[read_cyc[i]+page_word*cyc].split("h")[1])
                                    for j in range(len(rbits)):
                                        if j == 0:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("cp34_id_r"), "cp34_id_r_st:",
                                                    "1" + hex_to_Rbin_32bit("9AFF_FFFF")[j] + "1") + "//" + str(
                                                bin8_to_hex(str(hex_to_Wbin_32bit("9AFF_FFFF")[j:j + 8]))) + "\n")
                                        elif j == 31:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("cp34_id_r"), "cp34_id_r_sp:",
                                                    "1" + hex_to_Rbin_32bit("9AFF_FFFF")[j] + "1") + "\n")
                                        elif (j) % 8 == 0:
                                            f.write(V("1" + hex_to_Rbin_32bit("9AFF_FFFF")[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) + "//" + str(
                                                bin8_to_hex(str(hex_to_Wbin_32bit("9AFF_FFFF")[j:j + 8]))) + "\n")
                                        else:
                                            f.write(V("1" + hex_to_Rbin_32bit("9AFF_FFFF")[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) + "\n")
                                        if (j + 1) % 8 == 0 and j != 0:
                                            f.write("\n")
                                elif read_cyc[i]+page_word*cyc == 15 + page_word*cyc:
                                    pattern_end = "0;"
                                    rbits = hex_to_Rbin_32bit(G.col("ADDR_MAP", "CP Data[31:0]")[read_cyc[i]+page_word*cyc].split("h")[1])
                                    for j in range(len(rbits)):
                                        if j == 0:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("project_r_n"), "project_r_n_st:",
                                                    "1" + rbits[j] + "1") + "\n")
                                        elif j == 15:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("project_r_n"), "project_r_n_sp:",
                                                    "1" + rbits[j] + "1") + "\n")
                                        elif j == 16:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("project_r_p"), "project_r_p_st:",
                                                    "1" + rbits[j] + "1") + "\n")
                                        elif j == 31:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("project_r_p"), "project_r_p_sp:",
                                                    "1" + rbits[j] + "1") + "\n")
                                            pattern_end = "1;"
                                        else:
                                            f.write(V("1" + rbits[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) + "\n")

                                        if (j + 1) % 16 == 0 and j != 0:
                                            f.write("\n")

                                elif G.col("ADDR_MAP", "CP Data[31:0]")[read_cyc[i]+page_word*cyc] == "32'hFFFF_FFFF":
                                    f.write(V("1H1", label_count_dic[addr_map_item[cyc]] + 4, "RPT 32;") + "\n")
                                elif G.col("ADDR_MAP", "CP Data[31:0]")[read_cyc[i]+page_word*cyc] == "32'h0000_FFFF":
                                    f.write(V("1L1", label_count_dic[addr_map_item[cyc]] + 4, "RPT 16;") + "\n")
                                    f.write(V("1H1", label_count_dic[addr_map_item[cyc]] + 4, "RPT 16;") + "\n")

                                elif G.col("ADDR_MAP", "CP Data[31:0]")[read_cyc[i]+page_word*cyc] == "32'hFFFF_0000":
                                    f.write(V("1H1", label_count_dic[addr_map_item[cyc]] + 4, "RPT 16;") + "\n")
                                    f.write(V("1L1", label_count_dic[addr_map_item[cyc]] + 4, "RPT 16;") + "\n")
                                elif G.col("ADDR_MAP", "CP Data[31:0]")[read_cyc[i]+page_word*cyc] == "32'h0000_0000":
                                    f.write(V("1L1", label_count_dic[addr_map_item[cyc]] + 4, "RPT 32;") + "\n")
                                else:
                                    rbits = hex_to_Rbin_32bit(G.col("ADDR_MAP", "CP Data[31:0]")[read_cyc[i]+page_word*cyc].split("h")[1])
                                    for j in range(len(rbits)):
                                        f.write(V("1" + rbits[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) + "\n")
                                        if (j+1) %4 ==0 and j!=0:
                                            f.write("\n")

                            else:
                                if read_cyc[i]+page_word*cyc == 5 + page_word*cyc:
                                    rbits = hex_to_Rbin_32bit(G.col("ADDR_MAP", "CP Data[31:0]")[read_cyc[i]+page_word*cyc].split("h")[1])
                                    for j in range(len(rbits)):
                                        if j == 0:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("cp12_id_r"), "cp12_id_r_st:",
                                                    "1" + hex_to_Rbin_32bit(uid_pattern_item[u])[j] + "1") +"//"+str(bin8_to_hex(str(hex_to_Wbin_32bit(uid_pattern_item[u])[j:j+8])))+"\n")
                                        elif j == 31:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len("cp12_id_r"), "cp12_id_r_sp:",
                                                    "1" + hex_to_Rbin_32bit(uid_pattern_item[u])[j] + "1") + "\n")
                                        elif (j) % 8 == 0:
                                            f.write(V("1" + hex_to_Rbin_32bit(uid_pattern_item[u])[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) +"//"+str(bin8_to_hex(str(hex_to_Wbin_32bit(uid_pattern_item[u])[j:j+8])))+"\n")
                                        else:
                                            f.write(V("1" + hex_to_Rbin_32bit(uid_pattern_item[u])[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) + "\n")
                                        if (j + 1) % 8 == 0 and j != 0:
                                            f.write("\n")
                                elif G.col("ADDR_MAP", "CP Data[31:0]")[read_cyc[i]+page_word*cyc] == "32'hFFFF_FFFF":
                                    f.write(V("1H1", label_count_dic[addr_map_item[cyc]] + 4, "RPT 32;") + "\n")
                                elif G.col("ADDR_MAP", "CP Data[31:0]")[read_cyc[i]+page_word*cyc] == "32'h0000_FFFF":
                                    f.write(V("1L1", label_count_dic[addr_map_item[cyc]] + 4, "RPT 16;") + "\n")
                                    f.write(V("1H1", label_count_dic[addr_map_item[cyc]] + 4, "RPT 16;") + "\n")
                                elif G.col("ADDR_MAP", "CP Data[31:0]")[read_cyc[i]+page_word*cyc] == "32'hFFFF_0000":
                                    f.write(V("1H1", label_count_dic[addr_map_item[cyc]] + 4, "RPT 16;") + "\n")
                                    f.write(V("1L1", label_count_dic[addr_map_item[cyc]] + 4, "RPT 16;") + "\n")
                                elif G.col("ADDR_MAP", "CP Data[31:0]")[read_cyc[i]+page_word*cyc] == "32'h0000_0000":
                                    f.write(V("1L1", label_count_dic[addr_map_item[cyc]] + 4, "RPT 32;") + "\n")
                                else:
                                    rbits = hex_to_Rbin_32bit(G.col("ADDR_MAP", "CP Data[31:0]")[read_cyc[i]+page_word*cyc].split("h")[1])
                                    for j in range(len(rbits)):
                                        f.write(V("1" + rbits[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) + "\n")

                                        if (j+1) %4 ==0 and j!=0:
                                            f.write("\n")
                        else:
                            pattern_end = "0;"
                            rbits = hex_to_Rbin_32bit(G.col("ADDR_MAP", "CP Data[31:0]")[read_cyc[i]+page_word*cyc].split("h")[1])
                            for j in range(len(rbits)):
                                if "反码" in G.col("ADDR_MAP", "bit[31:16]")[read_cyc[i]+page_word*cyc]:
                                    if j == 0:
                                        try:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0])-3,
                                                    G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0].lower()+"r_n_st:",
                                                    "1" + rbits[j] + "1") + "\n")
                                        except:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc])-3,
                                                    G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].lower()+"r_n_st:",
                                                    "1" + rbits[j] + "1") + "\n")
                                    elif j == 15:
                                        try:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0])-3,
                                                    G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0].lower()+"r_n_sp:",
                                                    "1" + rbits[j] + "1") + "\n")
                                        except:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc])-3,
                                                    G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].lower()+"r_n_sp:",
                                                    "1" + rbits[j] + "1") + "\n")
                                    elif j == 16:
                                        try:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0])-3,
                                                    G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0].lower()+"r_p_st:",
                                                    "1" + rbits[j] + "1") + "\n")

                                        except:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc])-3,
                                                    G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].lower()+"r_p_st:",
                                                    "1" + rbits[j] + "1") + "\n")
                                    elif j == 31:
                                        try:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0])-3,
                                                    G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0].lower()+"r_p_sp:",
                                                    "1" + rbits[j] + "1") + "\n")

                                        except:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc])-3,
                                                    G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].lower()+"r_p_sp:",
                                                    "1" + rbits[j] + "1") + "\n")

                                    else:
                                        f.write(V("1" + rbits[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) + "\n")
                                elif "bit[31:16]的反码" in G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc]:
                                    if j == 0:
                                        try:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[31:16]")[read_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0])-3,
                                                    G.col("ADDR_MAP", "bit[31:16]")[read_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0].lower()+"r_p_st:",
                                                    "1" + rbits[j] + "1") + "\n")

                                        except:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[31:16]")[read_cyc[i]+page_word*cyc])-3,
                                                    G.col("ADDR_MAP", "bit[31:16]")[read_cyc[i]+page_word*cyc].lower()+"r_p_st:",
                                                    "1" + rbits[j] + "1") + "\n")
                                    elif j == 15:
                                        try:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[31:16]")[read_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0])-3,
                                                    G.col("ADDR_MAP", "bit[31:16]")[read_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0].lower()+"r_p_sp:",
                                                    "1" + rbits[j] + "1") + "\n")

                                        except:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[31:16]")[read_cyc[i]+page_word*cyc])-3,
                                                    G.col("ADDR_MAP", "bit[31:16]")[read_cyc[i]+page_word*cyc].lower()+"r_p_sp:",
                                                    "1" + rbits[j] + "1") + "\n")
                                    elif j == 16:
                                        try:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[31:16]")[read_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0])-3,
                                                    G.col("ADDR_MAP", "bit[31:16]")[read_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0].lower()+"r_n_st:",
                                                    "1" + rbits[j] + "1") + "\n")
                                        except:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[31:16]")[read_cyc[i]+page_word*cyc])-3,
                                                    G.col("ADDR_MAP", "bit[31:16]")[read_cyc[i]+page_word*cyc].lower()+"r_n_st:",
                                                    "1" + rbits[j] + "1") + "\n")
                                    elif j == 31:
                                        try:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[31:16]")[read_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0])-3,
                                                    G.col("ADDR_MAP", "bit[31:16]")[read_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0].lower()+"r_n_sp:",
                                                    "1" + rbits[j] + "1") + "\n")
                                        except:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[31:16]")[read_cyc[i]+page_word*cyc])-3,
                                                    G.col("ADDR_MAP", "bit[31:16]")[read_cyc[i]+page_word*cyc].lower()+"r_n_sp:",
                                                    "1" + rbits[j] + "1") + "\n")
                                    else:
                                        f.write(V("1" + rbits[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) + "\n")
                                else:
                                    # 2026-07-03 修：j==16/31 本该跟 program 侧（line 1761-1782）对称取
                                    # bit[15:0]（真实待打标签字段，如 "Hsi_8M_Trim[15:0]"）打标签；这里原写
                                    # 反成 bit[31:16]，当该半字是纯常量占位（如 "0X0000"，母本用户裁决 2026-
                                    # 07-03：此类高16bit 就该写 0，数据本身没问题）时，会把常量字符串当成
                                    # 标签名（如 "0x0000r_st:"），CRAFT 标签不能数字开头，编译报 unmatch。
                                    if j == 16:
                                        try:

                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0])-1,
                                                    G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0].lower()+"r_st:",
                                                    "1" + rbits[j] + "1") + "\n")

                                        except:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc])-1,
                                                    G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].lower()+"r_st:",
                                                    "1" + rbits[j] + "1") + "\n")
                                    elif j == 31:
                                        try:

                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0])-1,
                                                    G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].split("[")[0].split("Verify")[0].lower()+"r_sp:",
                                                    "1" + rbits[j] + "1") + "\n")

                                        except:
                                            f.write(LV((label_count_dic[addr_map_item[cyc]]) - len(G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc])-1,
                                                    G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i]+page_word*cyc].lower()+"r_sp:",
                                                    "1" + rbits[j] + "1") + "\n")
                                    else:
                                        f.write(V("1" + rbits[j] + "1", label_count_dic[addr_map_item[cyc]] + 4) + "\n")
                                if (j + 1) % 16 == 0 and j != 0:
                                    f.write("\n")
                        f.write("\n")
                        data_num +=1
                        pattern_end = "1;"
                    file_tail(f, label_count_dic[addr_map_item[cyc]] + 4)
#check
    for cyc in range(len(addr_map_item)):
        ra_binary_str = bin(int(G.col("ADDR_MAP", "SM Address")[0 + page_word*cyc].split(";")[0].split("=")[1], 16))[2:]
        if addr_map_item[cyc] == "uid":
            uid_pattern_item = {"cp1_id": "65FF_FFFF", "cp2_id": "65BA_78FF", "cp1_bake_id": "65BA_FFFF",
                                "cp2_bake_id": "65BA_78BA"}
            # check_cp<n>_id / check_cp<n>_bake_id 用来判断"该芯片是否已经跑过 CP<n>
            # （的正常/bake 路径）"，但被检查的这个字（pass id flag，cp12_id_ 标签）
            # 是 CP1/CP2/CP3 共用的同一个物理字，后续 CP 还会继续覆写剩余字节——
            # CP2 写 65BA78FF(正常)/65BAFFFF(CP1 bake)，CP3 最终统一写成 65BA78BA。
            # 如果整字精确比对，芯片一旦跑过更后面的 CP，这条 check 就会因为字节已被
            # 改写而失效（用户实测坐实）。只比对"后续 CP 确定不会再改"的高位字节，
            # 其余置 X（don't care）：cp1_id 只认 byte0(0x65)，cp2_id 认
            # byte0-2(0x65BA78)，cp1_bake_id 认 byte0-1(0x65BA)（第 3 字节 78/FF 是
            # 区分正常/bake 路径的关键位，但会被 CP3 统一覆写成 78，所以连同第 4 字节
            # 一起置 X）。cp2_bake_id(0x65BA78BA) 跟 CP3 正常完成后的终值完全一样、
            # 之后没有 CP4 会再改，维持整字精确比对不变。
            uid_pattern_check_keep_bytes = {"cp1_id": 1, "cp2_id": 3, "cp1_bake_id": 2}
            for u in uid_pattern_item.keys():
                with open(G.BASE_DIR + "\\pat_temp\\fbist_page_check_" + u + ext, 'w') as f:

                    file_head(f, "fbist_page_check_" + u)
                    pattern_end = ";"
                    # check UID 的 HEADER 固定为三引脚；不能复用上一份带 TRIGPIN
                    # pattern 遗留的 ECC 向量尾，否则会生成 4-bit 的 1X11。
                    _ecc_pgm_flag, ecc_read_flag = ecc_flags(pattern_end)
                    file_start(f, 6)
                    read_head = flash_read(6, pattern_end,
                                           ra_binary_str, "1", "page","0", "1", "0")
                    f.write(read_head[0])
                    for i in range(0, page_word):
                        if i != 0 and i % group_size == 0:
                            f.write(V("111", 6) + "\n" +
                                    V("1X1", 6) + "\n"
                                    + (6) * " " + ecc_read_flag)
                        elif i ==0:
                            f.write((6) * " " + ecc_read_flag)
                        if read_cyc[i] + page_word*cyc == 5 + page_word*cyc:
                            f.write((6) * " " + "//" + "rdata[" + str(read_cyc[i]) + "]=0x" + str(uid_pattern_item[u]) + "\n")
                        elif u == "cp3_id" and read_cyc[i] + page_word*cyc == 6 + page_word*cyc:
                            f.write((6) * " " + "//" + "rdata[" + str(read_cyc[i]) + "]=0x" + str("9AFF_FFFF") + "\n")
                        elif u == "cp3_id" and read_cyc[i] + page_word*cyc == 3 + page_word*cyc:
                            f.write((6) * " " + "//" + "rdata[" + str(read_cyc[i]) + "]=0x" + str("FFFF_FF78") + "\n")
                        else:
                            f.write((6) * " " + "//" + "rdata[" + str(read_cyc[i]) + "]=0x" + str(G.col("ADDR_MAP", "CP Data[31:0]")[read_cyc[i] + page_word*cyc].split("h")[1]) + "\n")

                        if read_cyc[i] + page_word * cyc == 5 + page_word * cyc:
                            rbits = hex_to_Rbin_32bit(
                                    G.col("ADDR_MAP", "CP Data[31:0]")[read_cyc[i] + page_word*cyc].split("h")[1])
                            uid_rbits = hex_to_Rbin_32bit(uid_pattern_item[u])
                            keep_bytes = uid_pattern_check_keep_bytes.get(u)
                            if keep_bytes is not None:
                                uid_rbits = uid_rbits[:keep_bytes * 8] + "X" * (32 - keep_bytes * 8)
                            uid_wbits = hex_to_Wbin_32bit(uid_pattern_item[u])
                            for j in range(len(rbits)):
                                if (j) % 8 == 0 and j != 31:
                                    f.write(V("1" + uid_rbits[j] + "1", 6) + "//" + str(
                                        bin8_to_hex(str(uid_wbits[j:j + 8]))) + "\n")
                                else:
                                    f.write(V("1" + uid_rbits[j] + "1", 6) + "\n")
                                if (j + 1) % 8 == 0 and j != 0:
                                    f.write("\n")
                        else:
                            f.write(V("1X1", 6, "RPT 32;") + "\n")

                        f.write("\n")
                        data_num += 1
                    file_tail(f, label_count_dic[addr_map_item[cyc]])
#capture
    for cyc in range(len(addr_map_item)):
        ra_binary_str = bin(int(G.col("ADDR_MAP", "SM Address")[0 + page_word*cyc].split(";")[0].split("=")[1], 16))[2:]
        if "lable" in G.col("ADDR_MAP", "data type")[page_word*cyc:page_word*(cyc+1)]:
            with open(G.BASE_DIR + "\\pat_temp\\" + addr_map_item[cyc] + "_capture" + ext, 'w') as f:
                if "lable" in G.col("ADDR_MAP", "data type")[page_word*cyc:page_word*(cyc+1)]:
                    file_head(f, addr_map_item[cyc] + "_capture", trig=True)
                    pattern_end = "1;"
                    _ecc_pgm_flag, ecc_read_flag = ecc_flags(pattern_end)

                file_start(f, 6)
                read_head = flash_read(6, pattern_end,
                                       ra_binary_str, "1", "page","0", "1", "0")
                f.write(read_head[0])
                for i in range(0, page_word):
                    if i != 0 and i % group_size == 0:
                        f.write(V("111", 6) + "\n" +
                                V("1X1", 6) + "\n"
                                + (6) * " " + ecc_read_flag)
                    elif i ==0:
                        f.write((6) * " " + ecc_read_flag)

                    f.write((6) * " " + "//" + "rdata[" + str(read_cyc[i]) + "]=0x" + str(
                        G.col("ADDR_MAP", "CP Data[31:0]")[read_cyc[i] + page_word*cyc].split("h")[1]) + "\n")

                    if G.col("ADDR_MAP", "data type")[read_cyc[i] + page_word*cyc] == "lable":
                        if "反码" in G.col("ADDR_MAP", "bit[31:16]")[read_cyc[i] + page_word*cyc]:
                            pattern_end="0;"
                            capture_run(f, 32, "//"+G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i] + page_word*cyc].lower())
                            pattern_end = "1;"
                        elif "bit[31:16]的反码" in G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i] + page_word*cyc]:
                            pattern_end = "0;"
                            capture_run(f, 32, "//"+G.col("ADDR_MAP", "bit[31:16]")[read_cyc[i] + page_word*cyc].lower())
                            pattern_end = "1;"
                        else:
                            try:
                                temp = G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i] + page_word*cyc].split("[")[0]

                                f.write(V("1X1", 6, "RPT 16;") + "\n")
                                pattern_end = "0;"
                                capture_run(f, 16, "//"+G.col("ADDR_MAP", "bit[15:0]")[read_cyc[i] + page_word*cyc].lower())
                                pattern_end = "1;"
                            except:
                                pattern_end = "0;"
                                capture_run(f, 16, "//"+G.col("ADDR_MAP", "bit[31:16]")[read_cyc[i] + page_word*cyc].lower())
                                pattern_end = "1;"
                                f.write("*1X1*RPT 16;\n")
                    else:
                        f.write(V("1X1", 6, "RPT 32;") + "\n")

                    data_num += 1
                file_tail(f, label_count_dic[addr_map_item[cyc]])


def otp_read_pattern_created():
    """生成 OTP_READ debug 项的单个 pattern：pat_temp/otp_read.<ext>
    （chroma=.pat / s100=.sd）。结构 = file_head + file_start + flash_read(otp=True 的
    页读设置，RA 低 8 位带 addr 裸标签) + capture 读区（按 byte_count 推的字数）+ file_tail。

    capture 读区：每 read_bit 位为一组 = 读触发拍 + 数据捕获拍 + 间隔拍。
      - chroma：读触发 *1L1*，捕获 *1K1*RPT 32（read_bit/32 行），间隔 *111*
      - s100  ：读触发 1L11（第4列 TRIGPIN=1），捕获 1H10 RPT <read_bit>（第4列=0 触发
                capture），间隔 1111；最后一组用 1X11 收尾（对齐已上机验证样本）
    byte_count = page word × 4（每 32-bit 字 4 字节）= PAGE_BYTES（产品母本驱动）。
    """
    chroma = G.platform == "chroma"
    ext = ".pat" if chroma else ".sd"
    pattern_end = ";" if chroma else "1;"   # s100 lable pattern 第4列 TRIGPIN=1
    sp = 6

    def file_head(f):
        if chroma:
            f.write('SET_DEC_FILE "pin.dec"\n\nHEADER\n\n' + G.col("VERSION", "CLK PIN")[0] + ", "
                    + G.col("VERSION", "SWD PIN")[0] + ', NRST;\n\nSPM_PATTERN(otp_read) {\n\n')
        else:
            f.write('HEAD[PIN_NAME]:\n\n' + G.col("VERSION", "CLK PIN")[0] + ', ' + G.col("VERSION", "SWD PIN")[0]
                    + ', NRST, TRIGPIN;\n\nEND_HEAD;\n\n@@PATTERN_DEFINE\n\n')

    def file_start(f):
        if chroma:
            f.write(_vec("011", sp, ";", _ts("normal")) + "\n")
        else:
            f.write((sp - len("START:")) * " " + "START:" + "011" + pattern_end + "\n")
        f.write(_vec("011", sp, pattern_end, "RPT 100;") + "\n")

    def file_tail(f):
        f.write(_vec("101", sp, pattern_end) + "\n")
        if chroma:
            f.write(sp * " " + "*011*STOP;\n\n}")
        else:
            f.write((sp - len("END:")) * " " + "END:" + "011" + pattern_end + "\n\n@@END_PATTERN_DEFINE ")

    read_bit = G.col("VERSION", "read bit")[0]
    page_word = G.col("VERSION", "page word")[0]
    byte_count = page_word * 4          # = PAGE_BYTES（每字 4 字节）
    total_bits = byte_count * 8
    group_count = total_bits // read_bit

    # 任取一页 RA 作占位（实际地址由测试项 write_pat_mem 经 addr 标签逐位改写）
    ra0 = bin(int(G.col("ADDR_MAP", "SM Address")[0].split(";")[0].split("=")[1], 16))[2:]

    with open(G.BASE_DIR + "\\pat_temp\\otp_read" + ext, 'w') as f:
        file_head(f)
        file_start(f)
        # 读设置（page 模式，otp=True 给 RA 低 8 位加 addr 标签）；末尾止于读命令 1X1
        read_head = flash_read(sp, pattern_end, ra0, "1", "page", "0", "1", "0", otp=True)
        f.write(read_head[0])

        # capture 读区——与 fbist_page_read 读结构同构（用户裁决 2026-06-24，原结构跑 fail）：
        # 逐字 capture（每 32-bit 字 chroma `*1K1*RPT 32`、s100 逐拍 1L1+TRIGPIN=0 触发），
        # 每 words_per_group(=read_bit/32) 字之间插 `111`+`1X1` 分隔；每组数据前追加
        # 非 capture 的 ECC read（首组紧接读命令，ECC 本身不带 PTN_TRIG/K）。
        words_per_group = read_bit // 32
        ecc_read = (_vec("1X1", sp, pattern_end, "RPT " + str(G.col("FLASH_EPR", "ecc")[0]) + ";// ECC read") + "\n"
                    if G.col("FLASH_EPR", "ecc")[0] != 0 else "")
        for i in range(page_word):
            if i != 0 and i % words_per_group == 0:
                f.write(_vec("111", sp, pattern_end) + "\n")
                f.write(_vec("1X1", sp, pattern_end) + "\n")
            if i % words_per_group == 0:
                f.write(ecc_read)
            if chroma:
                f.write(_vec("1K1", sp, pattern_end, "RPT 32;") + "//data[" + str(i) + "]\n")
            else:
                for c in range(32):
                    f.write(_vec("1L1", sp, "0;", "PTN_TRIG;") + ("//capture data[" + str(i) + "]" if c == 0 else "") + "\n")
        file_tail(f)


def nm_read_pattern_created():
    """生成 NM_Data_Read debug 项的 capture pattern：pat_temp/nm_read.pat（**仅 chroma**）。
    结构 = file_head + file_start + flash_read(nm_capture=True：bulk 双 bank 读设置 + 硬件
    capture 循环) + file_tail。读 mode=连续读(read_mode=1)、comp_mode=0、RA=0 从首页起；
    每 bank 用 SETX{bank}/JNZ{bank} 硬件循环读满 read_ack 组（=NM*PAGE_BYTES*4/read_bit）。
    fbist 进入态由测试项 nm_read_write 另跑 enter_fbist_mode（对齐 otp_read 做法，**与样本
    nm_read.pat 把 enter 内联不同**）。
    **S100**：每 bank 一个 `fbist_capture_nm_bank<i>.sd`——START..END1=配置+读命令+整页
    capture(cap=page_byte*8/read_bit 组 `1H10;RPT read_bit`)、START2..END2=后续页 capture
    (无配置，连续读)，测试项 C 软件循环逐页跑 START2/END2。结构仿样本 fbist_capture_nm_bank0.sd
    （**非逐字节**，flash_read 设置位不与样本完全一致），**待上机核实**。
    循环计数(chroma SETX=read_ack-1)见 flash_read nm_capture 分支，2026-07-03 用户上机实测坐实。"""
    sp = 6
    if G.platform == "chroma":
        with open(G.BASE_DIR + "\\pat_temp\\nm_read.pat", 'w') as f:
            f.write('SET_DEC_FILE "pin.dec"\n\nHEADER\n\n' + G.col("VERSION", "CLK PIN")[0] + ", "
                    + G.col("VERSION", "SWD PIN")[0] + ', NRST;\n\nSPM_PATTERN(nm_read) {\n\n')
            f.write(_vec("011", sp, ";", _ts("normal")) + "\n")
            f.write(_vec("011", sp, ";", "RPT 100;") + "\n")
            # bulk 双 bank 读设置 + 硬件 capture 循环（read_head[0]=bank0、[1]=bank1）
            read_head = flash_read(sp, ";", "0", "0", "bulk", "bulk00", "1",
                                   G.flash_mode_dic["NM"], nm_capture=True)
            for seg in read_head:
                f.write(seg)
            f.write(_vec("101", sp, ";") + "\n")
            f.write(sp * " " + "*011*STOP;\n\n}")
        return

    # ---- S100：每 bank 一个 fbist_capture_nm_bank<i>.sd ----
    read_bit = int(G.col("VERSION", "read bit")[0])
    page_byte = G.flash_mode_dic["PAGE_BYTES"]
    cap = page_byte * 8 // read_bit                    # 每页 capture 组数（256*8/64=32）
    # flash_read 的 read_head 恒为 2 元素 ["",""]，单 bank 只填 [0]、[1] 留空——滤掉空段，
    # 否则单 bank 会多生成一个无配置的废 fbist_capture_nm_bank1.sd。
    read_head = [h for h in flash_read(sp, "1;", "0", "0", "bulk", "bulk00", "1",
                                       G.flash_mode_dic["NM"], nm_capture=True) if h.strip()]

    def cap_vec(lbl=""):                                # 1H10;RPT read_bit（capture 一组）
        body = "1H10;RPT " + str(read_bit) + ";\n"
        return ((sp - len(lbl)) * " " + lbl + body) if lbl else (sp * " " + body)
    idle = _vec("111", sp, "1;") + "\n"                # 1111;
    arm = _vec("1X1", sp, "1;") + "\n"                 # 1X11;
    ecc_read = (_vec("1X1", sp, "1;", "RPT " + str(G.col("FLASH_EPR", "ecc")[0]) + ";// ECC read") + "\n"
                if G.col("FLASH_EPR", "ecc")[0] != 0 else "")

    for i in range(len(read_head)):
        with open(G.BASE_DIR + "\\pat_temp\\fbist_capture_nm_bank" + str(i) + ".sd", 'w') as f:
            f.write('HEAD[PIN_NAME]:\n\n' + G.col("VERSION", "CLK PIN")[0] + ', '
                    + G.col("VERSION", "SWD PIN")[0] + ', NRST, TRIGPIN;\n\nEND_HEAD;\n\n@@PATTERN_DEFINE\n\n')
            f.write((sp - len("START:")) * " " + "START:" + "0111;\n")
            f.write(_vec("011", sp, "1;", "RPT 100;") + "\n")
            f.write(read_head[i])                       # 配置 + 读命令（末尾 arm 1X11）
            # 首页 capture：组1紧接读命令的 arm，组2..cap 各 idle+arm+capture，末组挂 END1
            f.write(ecc_read + cap_vec())
            for g in range(1, cap):
                f.write(idle + arm + ecc_read + cap_vec("END1:" if g == cap - 1 else ""))
            # 后续页 capture：START2 标签在组1的 idle 上，末组挂 END2
            for g in range(cap):
                lead = ((sp - len("START2:")) * " " + "START2:" + "1111;\n") if g == 0 else idle
                f.write(lead + arm + ecc_read + cap_vec("END2:" if g == cap - 1 else ""))
            # 收尾
            f.write(arm + _vec("1X0", sp, "1;") + "\n" + _vec("111", sp, "1;", "RPT 2;") + "\n"
                    + _vec("011", sp, "1;") + "\n")
            f.write((sp - len("END:")) * " " + "END:XXXX;\n\n@@END_PATTERN_DEFINE ")


def read_status_mode_created():
    """生成 read_status_mode pattern（替换原手工种子空壳）。
    数据源：pattern sheet 中 pattern=="read_status_mode" 行——addr 列=CMD[3:0]（如 "1011"），
    description 列=32 位期望值（"32'hXXXXXXXX"）。结构（对齐 temp 同产品 .sd 参考）：
    进入等待 → 1 bit strobe + 写寄存器 → 串行写 4 位 CMD（PA13/SWD 位，MSB 先行）→
    读 32 位按期望值逐位 H/L 比对（MSB 先行，每 4 位空行分组）→ 等待 → 结束。
    数据/CMD 位放向量第 2 位（SWD PIN=PA13）；s100 第 4 列 TRIGPIN=1（pattern_end="1;"）。"""
    chroma = G.platform == "chroma"
    ext = ".pat" if chroma else ".sd"
    pattern_end = ";" if chroma else "1;"
    sp = 6

    def V(bits3, cmd=""):
        return _vec(bits3, sp, pattern_end, cmd)

    # 从 pattern sheet 取 CMD 与 32 位期望值
    pat_col = G.col("PATTERN", "pattern")
    addr_col = G.col("PATTERN", "addr")
    desc_col = G.col("PATTERN", "description")
    cmd_bits, exp_hex = "", ""
    for i in range(len(pat_col)):
        if str(pat_col[i]).strip().lower() == "read_status_mode":
            cmd_bits = str(addr_col[i]).strip()
            d = str(desc_col[i])
            exp_hex = (d.split("h")[-1] if "h" in d else d).replace("_", "").strip()
            break
    if not cmd_bits or not exp_hex:
        return  # 母本未配置则不生成（保留原种子）
    exp_bits = bin(int(exp_hex, 16))[2:].zfill(32)   # MSB 先行

    with open(G.BASE_DIR + "\\pat_temp\\read_status_mode" + ext, 'w') as f:
        # 文件头
        if chroma:
            f.write('SET_DEC_FILE "pin.dec"\n\nHEADER\n\n' + G.col("VERSION", "CLK PIN")[0] + ", "
                    + G.col("VERSION", "SWD PIN")[0] + ', NRST;\n\nSPM_PATTERN(read_status_mode) {\n\n')
            f.write(_vec("011", sp, ";", _ts("normal")) + "\n")
        else:
            f.write('HEAD[PIN_NAME]:\n\n' + G.col("VERSION", "CLK PIN")[0] + ', ' + G.col("VERSION", "SWD PIN")[0]
                    + ', NRST, TRIGPIN;\n\nEND_HEAD;\n\n@@PATTERN_DEFINE\n\n')
            f.write((sp - len("START:")) * " " + "START:" + "011" + pattern_end + "\n")
        f.write(V("011", "RPT 100;") + "\n\n")
        # 进入等待
        f.write(V("111") + "\n" + V("111", "RPT 50;// wait 50 us") + "\n" + V("111") + "\n\n")
        # 1 bit strobe + 写寄存器 + 串行写 4 位 CMD（PA13 位，MSB 先行）
        f.write(V("111") + "\n" + V("111") + "\n")
        # 注释拼在 V() 之后（V 自带分号；chroma 若把注释当 cmd 会顶掉分号导致语法错）
        f.write(V("110") + "// 1 bit strobe\n")
        f.write(V("111") + "// PA13=1, write register\n")
        for k, b in enumerate(cmd_bits):
            f.write(V("1" + b + "1") + (("//" + str(len(cmd_bits)) + "bits addr" + cmd_bits) if k == 0 else "") + "\n")
        f.write("\n")
        # 读 32 位：期望 1→H、0→L（PA13 位），MSB 先行，每 4 位空行分组
        for k in range(32):
            lh = "H" if exp_bits[k] == "1" else "L"
            f.write(V("1" + lh + "1") + ("//32bits data" if k == 0 else "") + "\n")
            if (k + 1) % 4 == 0:
                f.write("\n")
        # 结束等待 + 收尾
        f.write(V("111") + "\n" + V("111", "RPT 1000;// wait 100 us") + "\n" + V("111") + "\n")
        if chroma:
            f.write(sp * " " + "*011*STOP;\n\n}")
        else:
            f.write((sp - len("END:")) * " " + "END:" + "011" + pattern_end + "\n\n@@END_PATTERN_DEFINE ")
