# 母本输入契约（单一真相源）。
#
# 范围 = 生成器**实际消费**的 (sheet, 列)（CONSUMED，从 program_gen 里所有 G.col("S","C") 扒出）。
# 未被消费的列(如 ADDR_MAP 的 CPU Address/Contents/备注、PIN DEC 的 X/Y/Con、NM_pattern 的 No)
# 一律跳过——按用户裁决"用到才查"。
#
# 默认治理：每个消费列都过 A(字符卫生)。强类型(bitstring/limit/enum/pin/...)只**叠加**在
# 要紧列上(TYPED)，其余只过 A + 非空(除非允许 `/` 占位)。
#
# sheet 名用母本真实名(openpyxl 所见)，不是 G 的归一化名。

# ---- 类型常量 ----
TEXT      = "text"        # 自由文本（仍过 A）
TOKEN     = "token"       # 单个词/标识（过 A + 非空，不强约束取值）
NUMBER    = "number"      # 数值（可带单位/符号，见 rules）
LIMIT     = "limit"       # FLOW low/high：calc_limit 三写法（%/±/纯数字）
BITSTRING = "bitstring"   # 只含 0/1 的位串，**必须文本格式存储**(C1)
ENUM      = "enum"        # 固定取值集
PIN       = "pin"         # 管脚名
SLASH     = "/"           # 允许的占位值(N/A)

# ---- 消费列（lint 范围）：sheet 真实名 -> set(列) ----
CONSUMED = {
    "VERSION": {"CP num", "Program Name", "tester", "read bit", "program bit", "page word",
                "bank", "CLK PIN", "SWD PIN", "NRST PIN", "GET PIN", "pdr min", "pdr target",
                "pdr max", "vcc min", "vcc typ", "vcc max", "erase time(ms)", "program time(ms)",
                "VTE target", "VTP target", "VTE bake target", "VTP bake target", "CP spec",
                "CP ver high", "CP ver low", "project name", "project ver",
                "vpose", "vnege", "vposp", "vnegp"},
    "FLOW": {"CP NO", "item", "sub", "relay", "type", "Recipe", "OTP", "UID", "PUMP", "mode", "DAC bit", "step",
             "LINE", "Bisection", "PE", "FV/FI", "meas pin", "low_range(%)", "target",
             "high_range(%)", "UNIT", "Hbin", "Sbin", "Vcc"},
    "ADDR_MAP": {"Word No.", "SM Address", "line", "bit[31:16]", "bit[15:0]", "data type",
                 "CP Data[31:0]", "description", "CP addr map"},
    "FLASH_EPR": {"addr", "configs", "Description", "mode", "opr_mode", "opr_value", "space",
                  "page_num", "chessboard_mode", "chessboard_data", "fbist_mode", "fbist_cmd",
                  "comp_flag", "comp_data", "ecc"},
    "pattern": {"item", "addr", "description", "pattern"},
    "NM_pattern": {"used", "Pattern name"},
    "KP RELAY": {"F0 Channel", "KP RELAY F0", "F1 Channel", "KP RELAY F1"},
    "PIN DEC": {"CP NO", "Pad No.:", "Trace", "E/C(Pad Name)", "Site"},
    "PIN DEC SINGEL": {"TESTER", "Pad No.:", "Trace", "E/C(Pad Name)", "Site"},
}

# ---- 强类型叠加：(sheet, 列) -> spec ----
# spec: {"type":..., "enum":[...], "slash_ok":bool}
# 强类型列 = 生成器**严格解析/匹配**的列：这些列里全角/空格/格式错 → ERROR（会破坏生成）。
# 未列入的消费列 = 生成器宽松对待（已被"母本能跑通"证明容忍）：全角/空格只 WARN。
# 注意：ADDR_MAP 的 bit[31:16]/bit[15:0]/CP Data/description 等是**字段表达式/文档**列
# （`{HSE_FILT_TRIM[2:0],...}`、`32'h..`），生成器宽松——不列入强类型，避免误报。
TYPED = {
    ("VERSION", "tester"):        {"type": ENUM, "enum": ["s100", "chroma"], "ci": True},  # 生成器 .lower() 比较
    ("VERSION", "bank"):          {"type": ENUM, "enum": ["single", "double"]},
    ("VERSION", "CP num"):        {"type": ENUM, "enum": ["CP1", "CP2", "CP3"]},
    ("VERSION", "read bit"):      {"type": NUMBER},
    ("VERSION", "program bit"):   {"type": NUMBER},
    ("VERSION", "page word"):     {"type": NUMBER},
    ("VERSION", "CLK PIN"):       {"type": PIN},
    ("VERSION", "SWD PIN"):       {"type": PIN},
    ("VERSION", "NRST PIN"):      {"type": PIN},

    ("FLOW", "CP NO"):            {"type": ENUM, "enum": ["CP1", "CP2", "CP3"]},
    ("FLOW", "item"):             {"type": TOKEN},   # 拼写/大小写一致见 cross_ref
    ("FLOW", "sub"):              {"type": TOKEN, "slash_ok": True},
    ("FLOW", "relay"):            {"type": TOKEN, "slash_ok": True},
    ("FLOW", "type"):             {"type": ENUM, "enum": ["VT", "data", "id", "main", "margin", "os", "read", "shmoo", "trim", "uid", "verify", "wake", "write"], "ci": True, "slash_ok": True},
    ("FLOW", "mode"):             {"type": ENUM, "enum": ["fbist", "hex", "keil", "mbist", "scan", "swd"], "ci": True, "slash_ok": True},
    ("FLOW", "OTP"):              {"type": ENUM, "enum": ["no", "yes"], "ci": True, "slash_ok": True},
    ("FLOW", "UID"):              {"type": ENUM, "enum": ["no", "yes"], "ci": True, "slash_ok": True},
    ("FLOW", "PUMP"):             {"type": ENUM, "enum": ["no", "yes"], "ci": True, "slash_ok": True},
    ("FLOW", "PE"):               {"type": ENUM, "enum": ["erase", "no", "program"], "ci": True, "slash_ok": True},
    ("FLOW", "Bisection"):        {"type": ENUM, "enum": ["both", "both_m", "no", "yes"], "ci": True, "slash_ok": True},
    ("FLOW", "UNIT"):             {"type": ENUM, "enum": ["A", "mA", "uA", "nA", "V", "mV", "Hz", "KHz", "MHz", "GHz", "cap", "pat"], "ci": True, "slash_ok": True},
    ("FLOW", "Vcc"):              {"type": TOKEN, "slash_ok": True},
    ("FLOW", "DAC bit"):          {"type": NUMBER, "slash_ok": True},
    ("FLOW", "step"):             {"type": TOKEN, "slash_ok": True},   # DAC 序列 "8,9,10,.."，非标量
    ("FLOW", "Hbin"):             {"type": NUMBER, "slash_ok": True},
    ("FLOW", "Sbin"):             {"type": NUMBER, "slash_ok": True},
    ("FLOW", "low_range(%)"):     {"type": LIMIT, "slash_ok": True},
    ("FLOW", "high_range(%)"):    {"type": LIMIT, "slash_ok": True},
    ("FLOW", "target"):           {"type": NUMBER, "slash_ok": True},
    ("FLOW", "meas pin"):         {"type": PIN, "slash_ok": True},

    ("pattern", "item"):          {"type": TOKEN},
    ("pattern", "addr"):          {"type": BITSTRING, "slash_ok": True},   # C1：必须文本格式

    ("FLASH_EPR", "page_num"):    {"type": NUMBER, "slash_ok": True},
    ("FLASH_EPR", "ecc"):         {"type": NUMBER, "slash_ok": True},
}

# ---- 位段重叠检查的数据源（E 类）----
# (sheet, 列, 解析风格)：'pat'='start,name[h:l]=val' / 'epr'='name(off,width)'
BITFIELD_SOURCES = [
    ("pattern", "description", "pat"),
    ("FLASH_EPR", "configs", "epr"),
]

# ---- 跨表/一致性规则（D 类）----
# item 拼写一致：把 FLOW.item 与 pattern.item 收集起来，按"去后缀归一化"分组，
# 同一归一名出现多种拼写 → 疑似 typo（His/Hsi、VregSetOp/VregStOp）。规则实现见 rules.cross_ref。
ITEM_NAME_COLUMNS = [("FLOW", "item"), ("pattern", "item")]

# 这些列在生成器输入边界会 strip + canonicalize；首尾普通空格只提示，不阻断。
NORMALIZED_FLOW_COLUMNS = {"type", "mode", "OTP", "UID", "PUMP", "PE", "Bisection", "UNIT"}


# 自由文本列：允许中文/全角（描述类）。这些列只查"首尾空格 + 隐形字符"，**不**报全角。
# 其余消费列里出现全角字符一律 ERROR（会破坏数值/标识解析）。
FREETEXT = {
    ("pattern", "description"),
    ("ADDR_MAP", "description"), ("ADDR_MAP", "CP addr map"), ("ADDR_MAP", "line"),
    ("FLASH_EPR", "Description"),
    ("VERSION", "Program Name"), ("VERSION", "project name"),
}


def is_freetext(sheet, col):
    return (sheet, col) in FREETEXT


def normalizes_outer_spaces(sheet, col):
    return sheet == "FLOW" and col in NORMALIZED_FLOW_COLUMNS


def in_scope(sheet, col):
    return col in CONSUMED.get(sheet, ())


def spec_for(sheet, col):
    """该列的强类型 spec；没有则 None（只过 A + 非空判断由 rules 决定）。"""
    return TYPED.get((sheet, col))
