"""经验证 SWD 工具的无副作用协议子集。

常量/位编码分别来自 ``SWD_PAT/SWD.py`` 与
``swd_commander/execution/s100/{compiler,chip_db}.py``；此处不导入旧脚本，
因此不会执行其 ``chdir``、交互输入或文件输出。
"""
from base64 import b85decode


def _constant(encoded):
    return b85decode(encoded).decode("utf-8")


# Exact PT104/M4 reset sequences copied from the two verified generators.
CHROMA_M4_CORE = _constant(
    "ASy61F)AQbQ!zUVASy92F)BL>ASy92F)AQZP*fl{Ffcm`ASy92F)BL>ASy92F)BL>ASy92Fe)HYP*fl>Ffcm`ASy92F)AQZP*fl{Ffcm`ASy91F)BL>ASy92F)AQZP*fl^I|?8wF)%SIAW~3NATm1&ASy92F)AQZP*fl^I|?8wF)%SIAW~3NATm1&ASy92F)AQZP*fl>Ffcm`ASy92F)AQZP*fl?I|?8wF)%SIAW~3NATm1&ASy92F)BL>ASy91F)BL>ASy92F)BL>ASy91F)AQZP*fl?I|?8wF)=YJI|?8wF)%SII|?8wF)=YJI|?8wF-S2gI|?8wF-$QkAW~3NATm1&ASy9PF)AQZP*fl@I|?8wF-$QkI|?8wF-S2gAW~3NATv7(ASy9TF)AQZP*fl@I|?8wF-S2gI|?8wF-$QkI|?8wF-S2gI|?8wF-$QkAW~3NAUHb;ASy9PF)BL>ASy9TF)BL>ASy9PF)AQZP*fl@I|?8wF-$QkI|?8wF-S2gI|?8wF-$QkI|?8wF-S2gI|?8wF-$QkAW~3NATv7(ASy9fF)BL>ASy91F)BL>ASy91F)AQZP*fl_GCK+&DlsrIDmw}wDlsuJDmw}wDlsrIDj-r&R3I`t3Lq*mF)=DT3Lq*mFfl4S3Lq*mF)=DT3Lq*mFfl4S3Lq*mF)=DT3Lq*mNHHoq3Lq*mOff1TQczSNGCK+&Dlu3wDmw}wDlsrIDj-r&R3I`rI|?8wF)=YJI|?8wF)%SII|?8wF)=YJI|?8wF)%SIAW~3NAT>2R3Lq*mF)=DT3Lq*mFfl41QczSNGdl_(DlsuJDj-r&R3I`t3Lq*mFfl4S3Lq*mF)=DT3Lq*mNHHoq3Lq*mOff1TQczSNGCK+&Dlu3wDmw}wDlsrIDj-r&R3JDvI|="
)
S100_M4_CORE = _constant(
    "AX8L9QdBxHF)=Ya3Lr5tF)=#|ATcp9F*{OFR3JAnFgpq$F)=YQI|?8%F)=Ya3Lr5tFflt)P*fl>Ffcm`ATcp9F*{OFR3JAnFgpq$F)%SPI|?8%F)=YaQczSNG&>3)F)%SPJ5o?oATm1&ATcp9F*{OFR3J1v3Lr5sF)=$*P*fl?I|?8%F)=YaQczSNF)%PY3Lr5tF)=$*P*fl?I|?8%FflPZQczSNGCK+&F)=YQI|?8%FflPZ3Lr5tF)=#|ATcm8F*{OFR3I`t3Lr5tF)=#|ATcm8F*^z%F)=YQI|?8%NHH-x3Lr5|F)=$*P*fl?I|?8%NHH-xQczSNGdl_(F-$QrI|?8%NHH-xQczSNGdl_(F-$QrJ5o?oATv7(ATdZWF*^z%F-$QrI|?8%NHH-x3Lr5|F)=$*P*fl|I|?8%NHH-x3Lr5|F)=#|ATdZWF*{OFR3I}u3Lr5|F)=#|ATdZWF*^z%F-$QrI|?8%NHH-x3Lr5|F)=$*P*fl@I|?8%STQj>3Lr5sF)=#|ATcm8F*{OFR3J4nI|?8%FflPZ3Lr5tF)=#|ATcm8F*{OFR3I`t3Lr5tF)=#|ATcm8F*^z%F)=YQI|?8%FflPZ3Lr5tF)=#|ATdZWF*^z%F-$QrJ5o?oATm1&ATd}mF*^z%F)%SPJ5o?oATl{S3Lr5tF)=#|ATcm8F*^z%F)=YQI|?8%FflPZQczSNH8nd5ATcp9F*^z%F)%SPJ5o?oATv7(ATcp9F*{OFR3I`t3Lr5sF)=#|ATcp9F*^z%F-S2nI|?8%OffM#QczSNGCK+&F<3D%I|?8%FflPZQczSNI5#^A"
)


_CHROMA = {
    "tar": " *111* RPT 2;\n *101*;\n *111*;\n *101* RPT 3;\n *111*;\n *1H1*;\n *1L1* RPT 2;\n *1X1*;\n *101*;\n",
    "csw": " *111* RPT 2;\n *101* RPT 3;\n *111*;\n *101*;\n *111*;\n *1H1*;\n *1L1* RPT 2;\n *1X1*;\n *101*;\n",
    "drw": " *111* RPT 2;\n *101*;\n *111* RPT 3;\n *101*;\n *111*;\n *1H1*;\n *1L1* RPT 2;\n *1X1*;\n *101*;\n",
    "read": " *111* RPT 5;\n *101* RPT 2;\n *111*;\n *1H1*;\n *1X1* RPT 35;\n *1X1*;\n *101* RPT 2;\n *111*;\n *101*;\n *111* RPT 4;\n *101*;\n *111*;\n *1H1*;\n *1L1* RPT 2;\n",
}
# Preserve the S100 source constants and its vector/instruction separators.
_S100 = {
    "tar": " 1111;RPT 2;\n 1011;\n 1111;\n 1011;RPT 3;\n 1111;\n 1H11;\n 1L11;RPT 2;\n 1X11;\n 1011;\n",
    "csw": " 1111;RPT 2;\n 1011;RPT 3;\n 1111;\n 1011;\n 1111;\n 1H11;\n 1L11;RPT 2;\n 1X11;\n 1011;\n",
    "drw": " 1111;RPT 2;\n 1011;\n 1111;RPT 3;\n 1011;\n 1111;\n 1H11;\n 1L11;RPT 2;\n 1X11;\n 1011;\n",
    "read": " 1111;RPT 5;\n 1011;RPT 2;\n 1111;\n 1H11;\n 1X11;RPT 35;\n 1X11;\n 1011;RPT 2;\n 1111;\n 1011;\n 1111;RPT 4;\n 1011;\n 1111;\n 1H11;\n 1L11;RPT 2;\n",
}


def constants(platform):
    if platform == "chroma":
        return _CHROMA, CHROMA_M4_CORE
    if platform == "s100":
        return _S100, S100_M4_CORE
    raise ValueError(f"不支持的平台：{platform}")


def _line(platform, first, value, suffix=""):
    if platform == "chroma":
        return f" *1{value}1*;{suffix}\n"
    return f" 1{value}11;{suffix}\n"


def data_bits(value, platform, mode):
    """Old helper semantics, including LSB-first C_L checks and MSB-first CAP."""
    number = int(str(value), 16)
    bits = f"{number:032b}"
    bits = bits if mode == "cap" else bits[::-1]
    output = []
    for index, bit in enumerate(bits):
        if mode == "write": marker = bit
        elif mode == "read": marker = "H" if bit == "1" else "L"
        elif mode == "cap": marker = "K" if bit == "1" and platform == "chroma" else ("H" if bit == "1" else "X")
        elif mode == "high": marker = "H" if bit == "1" else "X"
        elif mode == "low": marker = "L" if bit == "0" else "X"
        else: raise ValueError(mode)
        comment = f"//{value}" if index == 0 else ""
        if mode == "cap" and bit == "1" and platform == "s100":
            output.append(f" 1H10;PTN_TRIG;{comment}\n")
        else:
            output.append(_line(platform, index == 0, marker, comment))
    if mode == "write":
        parity = "1" if bits.count("1") % 2 else "0"
        output.append(_line(platform, False, parity, "//Parity"))
        output.append((" *101* RPT 3;\n" if platform == "chroma" else " 1011;RPT 3;\n"))
    else:
        output.append(_line(platform, False, "X", "//Parity"))
        output.append(_line(platform, False, "X"))
    return "".join(output)


def command(addr, register, operation, platform):
    bits = f"{int(str(addr), 16):04b}"
    values = ["1", "1" if register == "AP" else "0", "1" if operation == "R" else "0", *bits[:2]]
    parity = str(sum(value == "1" for value in values[1:]) % 2)
    parity_line = " 1011;//Parity\n" if platform == "chroma" and parity == "0" else _line(platform, False, parity, "//Parity")
    lines = [(_line(platform, False, "1")), *(_line(platform, False, value) for value in values[1:]), parity_line]
    return "".join(lines) + (_line(platform, False, "0") + _line(platform, False, "1") + (_line(platform, False, "H") + _line(platform, False, "L", "RPT 2;") + _line(platform, False, "X") + _line(platform, False, "0")))


def bit_operation(value, shift, reset):
    text = str(value).strip().upper()
    number = int(text, 0) if text.startswith(("0X", "0B")) else int(text)
    width = len(text) - 2 if text.startswith("0B") else (len(text) - 2) * 4 if text.startswith("0X") else max(number.bit_length(), 1)
    base = str(reset).strip().upper().removeprefix("0X")
    if len(base) != 8: raise ValueError(f"Reset值 {reset} 不是八位十六进制数")
    position = int(shift)
    return f"{(int(base, 16) & ~(((1 << width) - 1) << position) | (number << position)) & 0xFFFFFFFF:08X}"
