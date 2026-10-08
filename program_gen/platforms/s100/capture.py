# S100 平台：通用 capture（2026-07-21 移植自 chroma/capture.py）。
#
# 目前只服务 **SRAM capture**（`UNIT=cap` 且 `cap_cfg` pattern 段=SRAM）：逐字
# `Read_SRAM(base+I*4)`（全局函数在 s100/startup.py 生成，读固定 32bit）+ `JUDGE_VARIABLE`。
# ADC 的 capture 走 s100/adc_writer.py 的 IOMUX 专用机制，不走这里。


def parse_cap_cfg(cap_cfg):
    """cap_cfg `pattern-base-bit-位宽`（- 分隔四段）→ (cap_pattern, base, total_bits, bits_per_data)。
    同 chroma/capture.py:parse_cap_cfg（S100 SRAM 只用 base/total_bits/bpd，pattern 段=SRAM）：
      base='/'→None（否则 int(...,0) 支持 0X 十六进制）；bit='/'→None；位宽=必填整数。
    SRAM：`SRAM-0X3000-256-32` → cap_pattern=SRAM、base=0x3000、total_bits=256、bpd=32、
    count=total_bits//bpd=8。"""
    parts = [p.strip() for p in str(cap_cfg).split("-")]
    if len(parts) != 4:
        raise ValueError("cap_cfg 格式应为 'pattern-base-bit-位宽'（- 分隔四段），实际 '"
                         + str(cap_cfg) + "'")
    pat_seg, base_seg, bit_seg, width_seg = parts
    cap_pattern = pat_seg
    base = None if base_seg == "/" else int(base_seg, 0)
    total_bits = None if bit_seg == "/" else int(bit_seg)
    bits_per_data = int(width_seg)
    return cap_pattern, base, total_bits, bits_per_data


def capture_sram_write(f, base, entries, uniform, banner, indent="\t\t"):
    """SRAM capture 判定（S100 idiom，参考用户给的 TK_S100.txt + adc_writer）：逐数
    `Read_SRAM(base+I*4)`（读回 + 汇编进 `GBX[1+1024*T_SOCKET]` 都在 Read_SRAM 内）+
    `C_COMPARE(GBX2, UP_LIMIT, DOWN_LIMIT, LOG_ALIAS=<字面>)`（S100 无 JUDGE_VARIABLE；
    C_COMPARE 内部逐工位判、字面 LOG_ALIAS 无需 SET_CSV_LOG_ALIAS 注册，见 _emit_dps_meas）。
    地址 base 用十六进制。两种布局：
      uniform=True（单行统一 limit）→ 展开 count 次、编号字面 alias（`<stem>_0..n-1`），banner=整段横幅；
      uniform=False（多行逐数 limit）→ 每数展开、各自 sub 横幅 + 字面 alias。"""
    sp = indent
    if uniform:
        low, high, alias0 = entries[0]
        stem = alias0.rsplit("_", 1)[0]
        n = len(entries)
        f.write(sp + "////////////////" + str(banner).lower() + "////////////////\n")
        for k in range(n):
            f.write(sp + "Read_SRAM(" + hex(base + k * 4).upper() + ");\n")
            f.write(sp + "C_COMPARE(GBX2, UP_LIMIT=" + str(high) + ", DOWN_LIMIT="
                    + str(low) + ",LOG_ALIAS=" + stem + "_" + str(k) + ");\n\n")
    else:
        for i, (low, high, alias) in enumerate(entries):
            f.write(sp + "////////////////" + str(alias).lower() + "////////////////\n")
            f.write(sp + "Read_SRAM(" + hex(base + i * 4).upper() + ");\n")
            f.write(sp + "C_COMPARE(GBX2, UP_LIMIT=" + str(high) + ", DOWN_LIMIT="
                    + str(low) + ",LOG_ALIAS=" + str(alias) + ");\n\n")
