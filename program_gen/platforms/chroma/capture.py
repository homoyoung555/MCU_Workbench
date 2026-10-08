# Chroma 平台：通用 capture 生成（2026-07-16 用户裁决）。
#
# 服务"等宽拼数据"这一种 capture 模式（capture 一串 bit，每 N 位 LSB-first 拼一个
# 整数，跳过 8=don't care）。OTP_Read/NM_Data_Read 那种不规则拼法固定写死、不走这里。
#
# FLOW 触发：UNIT=="cap"；参数来自 cap_cfg 列，格式 "pattern-bit-位宽"（- 分隔）：
#   pattern 段：'/' + mode=swd → 自动派生 <产品名>_<stem>_capture（stem 同 swd：有 sub
#              用 sub、无 sub 用 item，去掉最后一个下划线段/单段原样）；否则用填的字面名。
#   bit 段：'/' → 总 bit 由族路提供（如 ADC 从 IOMUX 通道数×位宽 算）；否则用填的整数。
#   位宽段：每个数据几位（如 ADC 16）。
#
# 判定各测试项不同（ADC 用 (force/VCC)*分辨率±容差、别的 vs limit），由调用方以
# judge_body 字符串传入（capture_unpack_write 只管 capture 读取 + 等宽解包框架）。


def parse_cap_cfg(cap_cfg, product, stem):
    """cap_cfg "pattern-base-bit-位宽"（- 分隔四段）→ (cap_pattern, base, total_bits, bits_per_data)。
    各段 '/' 语义：
      pattern='/' → 派生 <产品名>_<stem>_capture（否则用字面名，如 SRAM）；
      base='/'    → 无基址（ADC-DR 模式不用；SRAM 模式填 0X3000 这种，int(...,0) 解析）；
      bit='/'     → 总 bit 由族路提供（如 ADC 从 IOMUX 通道数×位宽）；
      位宽        → 每数据位数（必填整数）。"""
    parts = [p.strip() for p in str(cap_cfg).split("-")]
    if len(parts) != 4:
        raise ValueError("cap_cfg 格式应为 'pattern-base-bit-位宽'（- 分隔四段），实际 '"
                         + str(cap_cfg) + "'")
    pat_seg, base_seg, bit_seg, width_seg = parts
    cap_pattern = (product + "_" + stem + "_capture") if pat_seg == "/" else pat_seg
    base = None if base_seg == "/" else int(base_seg, 0)
    total_bits = None if bit_seg == "/" else int(bit_seg)
    bits_per_data = int(width_seg)
    return cap_pattern, base, total_bits, bits_per_data


def capture_unpack_write(f, cap_pin, cap_pattern, total_bits, bits_per_data,
                         data_var, judge_body, indent="      "):
    """生成 capture 读取 + 等宽解包框架（不含外层 SOCKET_INC 块、data_var 声明、
    前置激励——都由调用方负责）：
      SET_CAPTURE_MEM_MODE ON → CAP pattern link → READ_CAPTURE_MEM_BLOCK →
      for K { data_var[SOCKET][K] = 每 bits_per_data 位 LSB-first 拼值（跳 8）;
              <judge_body> } → SET_CAPTURE_MEM_MODE OFF。
    total_bits 必须已知（族路算好）；temp_cap_data 由调用方在函数级声明。
    judge_body：循环体内每通道判定 C 代码（引用 K / data_var[SOCKET][K]），需自带缩进。"""
    if total_bits is None:
        raise ValueError("capture_unpack_write: total_bits 未提供（cap_cfg bit 段为 '/' 时"
                         "须由族路按数据源算好，如 ADC=IOMUX 通道数×位宽）")
    n = total_bits // bits_per_data
    bpd = str(bits_per_data)
    sp = indent
    f.write(sp + "SET_CAPTURE_MEM_MODE(" + cap_pin + ", PEL_K, ON, 32K);\n\n")
    f.write(sp + "TEST_NUM++;\n")
    f.write(sp + 'TEST_NO(TEST_NUM); DATALOG_MSG="' + cap_pattern + '";\n')
    f.write(sp + "JUDGE_PAT(" + cap_pattern + ",__" + cap_pattern + ");\n\n")
    f.write(sp + "READ_CAPTURE_MEM_BLOCK(SOCKET, " + cap_pin + ", 0, " + str(total_bits - 1)
            + ", temp_cap_data);// " + bpd + " bit = 1 data\n\n")
    f.write(sp + "for(K=0;K<" + str(n) + ";K++)\n" + sp + "{\n")
    f.write(sp + "  " + data_var + "[SOCKET][K]= 0;\n")
    f.write(sp + "  for(J=0;J<" + bpd + ";J++)\n" + sp + "  {\n")
    f.write(sp + "    if(temp_cap_data[" + bpd + "*K+J]!=8) " + data_var
            + "[SOCKET][K] += temp_cap_data[" + bpd + "*K+J]<<(J);\n")
    f.write(sp + "  }\n\n")
    f.write(judge_body)
    f.write(sp + "}\n\n")
    f.write(sp + "SET_CAPTURE_MEM_MODE(" + cap_pin + ", PEL_K, OFF, 32K);\n")


def capture_sram_write(f, base, entries, uniform, banner, indent="  "):
    """SRAM capture 判定（2026-07-16，SET_CAPTURE 已移进 Read_SRAM 内，这里只管逐数
    Read_SRAM(base+I*4) + JUDGE_VARIABLE）。地址 base 用十六进制、判定各自 SOCKET_INC
    包（多工位，同 ADC）。两种布局：
      uniform=True（单行统一 limit）→ for 循环 + sprintf 编号 alias，banner=整段横幅名；
      uniform=False（多行逐数 limit）→ 每数展开、各自 sub 横幅注释 + 字面 alias。
    Read_SRAM 全局函数由 startup._read_sram_write 生成、sram_cpature.pat 是手工种子。"""
    sp = indent
    if uniform:
        low, high, alias0 = entries[0]
        stem = alias0.rsplit("_", 1)[0]
        n = len(entries)
        f.write(sp + "////////////////" + str(banner).lower() + "////////////////\n")
        f.write(sp + "char sram_log[48];\n")
        f.write(sp + "for(I=0;I<" + str(n) + ";I++)\n" + sp + "{\n")
        f.write(sp + "  Read_SRAM(" + hex(base).upper() + "+I*4);\n\n")
        f.write(sp + "  SOCKET_INC(FRZ_OFF)\n" + sp + "  {\n")
        f.write(sp + '    sprintf(sram_log,"' + stem + '_%d",I);\n')
        f.write(sp + "    JUDGE_VARIABLE(SOCKET, sram_data[SOCKET], " + str(low) + ", "
                + str(high) + ", sram_log);\n")
        f.write(sp + "  }\n" + sp + "}\n\n")
    else:
        for i, (low, high, alias) in enumerate(entries):
            f.write(sp + "////////////////" + str(alias).lower() + "////////////////\n")
            f.write(sp + "Read_SRAM(" + hex(base + i * 4).upper() + ");\n\n")
            f.write(sp + "SOCKET_INC(FRZ_OFF)\n" + sp + "{\n")
            f.write(sp + "  JUDGE_VARIABLE(SOCKET, sram_data[SOCKET], " + str(low) + ", "
                    + str(high) + ', "' + str(alias) + '");\n')
            f.write(sp + "}\n\n")
