# 运行时共享状态（原 S100 pattern.py 的模块级全局变量，机械迁移，不改语义）。
# 各功能模块通过 `from program_gen import state as G` 显式访问。
import os

import pandas as pd

from program_gen.core.input_normalization import normalize_flow_table
from program_gen.workbook import WorkbookModel, WorkbookReader

# ---- 静态初始状态（原样保留原 pattern.py 顶部定义） ----
set_vposp_name = []

epr_pattern_dict = {"erase": "111", "pgm": "222", "read": "333"}
flash_mode_dic = {}
opr_mode_dic = {}
addr = []
data = []
name = []
item = []
pinname = []
dict_1 = {}
dict_F0 = {}
dict_F1 = {}
num = 0
vref = []
FLAG = 0
Lbale_s = 0
size = []
site = []
a = []
s = []
x = []
F0_C = []
F1_C = []
F0_R = []
F1_R = []
trash = []
exegesis = []
pass_main = []
main_variable = []
pattern_name = ""
function_name = ""
nm_pattern_name = ""
CP32bit_data = ""
code_name = []
df_variable = pd.DataFrame
pin_dec = []
relay_j = []  # dec_file_created 本轮 cyc 里被判定为 relay（XY 坐标为空）的 G.pinname 下标
fclk_ts = {"FSCLK_TYP": "TS1", "FSCLK_500K": "TS2", "FSCLK_ERASE": "TS5", "FSCLK_PGM": "TS6"}
# lvl_vcc 的 TYP_LVL 两平台取值不同（S100: _C_VCC_TYP / Chroma: VCC_TYP），init() 按平台设置
_LVL_VCC = {
    "s100": {"MIN_LVL": "VCC_MIN", "TYP_LVL": "_C_VCC_TYP", "MAX_LVL": "VCC_MAX", "PDR_MIN_LVL": "VCC_PDR_MIN",
             "PDR_TAR_LVL": "VCC_PDR_TAR", "PDR_MAX_LVL": "VCC_PDR_MAX"},
    "chroma": {"MIN_LVL": "VCC_MIN", "TYP_LVL": "VCC_TYP", "MAX_LVL": "VCC_MAX", "PDR_MIN_LVL": "VCC_PDR_MIN",
               "PDR_TAR_LVL": "VCC_PDR_TAR", "PDR_MAX_LVL": "VCC_PDR_MAX"},
}
lvl_vcc = _LVL_VCC["s100"]

uid_variable_1 = ["LOT_ID", "WAFER_SLOT", "X_CO", "Y_CO", "TESTING_HOUS_ID", "CP_VERNO", "CP1_VERSION", "CP2_VERSION"]
uid_variable_2 = ["PROJECT_NAME", "PROJECT_VERSION", "year", "month", "CRC8"]
open_name = ""

j = 1

# ---- init() 填充的路径与 Excel 数据 ----
BASE_DIR = None      # 输入根（test_data / pat_temp / fbist_pattern）
OUT_DIR = None       # 输出根（各程序文件夹）：生产=BASE_DIR；实验室=BASE_DIR/LAB/<平台>
path = None
path2 = None
wb = None
ws = None
wc = None
VERSION = None
FLOW = None
ADDR_MAP = None
PIN_DEC_128 = None
KP_RELAY = None
NM_PATTERN = None
FLASH_EPR = None
PATTERN = None

# ---- 主流程运行时共享 ----
platform = "s100"   # 当前目标平台（init() 设置），core 的平台渲染依据
i = 0            # 当前 CP 序号（原全局循环索引）
f = None         # 当前 .prg 文件句柄（原顶层 with 的全局句柄）
flash_epr_pattern = None
product_compilation = None
compiled_adapter = None

# ---- Excel 列缓存 ----
# 原代码大量在循环体内写 list(G.<表>["<列>"])，每次访问都把整列重新转一遍 list
# （PIN DEC 近 3000 行时是性能灾难）。col() 把转换结果缓存，返回副本以防调用方
# 就地修改（如 fbist_pattern_created 改写 name[i]）污染缓存。
# 前提：8 个 sheet 的 DataFrame 在 init 之后只读（全库无列赋值，已核查）。
_col_cache = {}


def col(sheet, column):
    """等价于 list(G.<sheet>[column])，带缓存；返回副本。"""
    key = (sheet, column)
    cached = _col_cache.get(key)
    if cached is None:
        cached = list(globals()[sheet][column])
        _col_cache[key] = cached
    return list(cached)


def flow_row_flag(row):
    """按 FLOW.item 列（col B）单元格背景色识别人工标记（2026-07-05 用户裁决，Chroma 用）：
    绿色 RGB FF92D050 = 该测试项强制置 PASS（参考 temp/temp_swd_cp3.pln 用户样例，函数
    末尾追加 SOCKET_INC(FRZ_OFF){PLAN_RESULT_MS[SOCKET]=PASS;}）；主题灰色（Excel"白色，
    文字 1，深色 25%"一类填色，theme=0 且 tint=-0.5）= 该测试项在 TEST_PRO 调度表里整行
    注释掉，不参与调度。row 是 FLOW 数据区 0-indexed 行号（对应 G.col("FLOW", ...)[row]），
    Excel 实际行号是 row+2（第 1 行是表头）。未染色或染了其它颜色都返回 None。"""
    fg = ws["B"][row + 1].fill.fgColor
    if fg.type == "rgb" and fg.rgb == "FF92D050":
        return "force_pass"
    if fg.type == "theme" and fg.theme == 0 and abs(fg.tint - (-0.5)) < 1e-6:
        return "comment_out"
    return None


def nm_patterns(*used_keys):
    """按 NM_pattern 表行序返回 used 列匹配 used_keys 的 Pattern name（去扩展名）。

    取代散落在各 writer 里的 `for u in range(len(used)): if used[u] == ...`
    线性扫描；多个 key 时保持表格行序（与原扫描的输出顺序一致）。"""
    used = col("NM_PATTERN", "used")
    names = col("NM_PATTERN", "Pattern name")
    return [str(names[u]).split(".")[0] for u in range(len(used)) if used[u] in used_keys]


def _resolve_master_path(base_dir, master=None):
    """Resolve the one workbook used by the legacy projection."""
    base = os.path.abspath(base_dir or os.getcwd())
    shared = os.path.join(os.path.dirname(base), "test_data")
    test_data = shared if os.path.isdir(shared) else os.path.join(base, "test_data")
    if master and os.path.isabs(master):
        candidate = os.path.abspath(master)
    elif master:
        candidate = os.path.join(test_data, master)
    else:
        candidates = [
            os.path.join(test_data, name)
            for name in sorted(os.listdir(test_data))
            if not name.startswith("~$") and name.casefold().endswith((".xlsx", ".xlsm"))
        ] if os.path.isdir(test_data) else []
        if not candidates:
            raise FileNotFoundError(f"test_data 下没有可用母本: {test_data}")
        candidate = candidates[0]
    if not os.path.isfile(candidate):
        raise FileNotFoundError(f"母本不存在: {candidate}")
    return candidate


def load_workbook_model(base_dir=None, master=None):
    """Compatibility entry for direct platform callers; reads exactly once."""
    return WorkbookReader().read(_resolve_master_path(base_dir, master))


def init(base_dir=None, platform="s100", mode="production", master=None,
         workbook_model=None):
    """Install a target-private legacy projection of one WorkbookModel.

    mode="production"：多 site 量产程序，读 "PIN DEC"，输出根=BASE_DIR；
    mode="lab"：单 site 实验室程序，读 "PIN DEC SINGEL"（按 TESTER==platform 过滤），
                输出根=BASE_DIR/LAB/<平台>。
    workbook_model：由统一入口预先读取的 Canonical WorkbookModel。直接调用平台 run 时
            兼容地按 master 读取一次，再由 LAB/Production 共同消费同一模型。"""
    global BASE_DIR, OUT_DIR, path, path2, wb, ws, wc, lvl_vcc
    global VERSION, FLOW, ADDR_MAP, PIN_DEC_128, KP_RELAY, NM_PATTERN, FLASH_EPR, PATTERN
    global product_compilation, compiled_adapter
    lvl_vcc = _LVL_VCC[platform]
    globals()["platform"] = platform
    _col_cache.clear()
    product_compilation = None
    compiled_adapter = None
    BASE_DIR = os.path.abspath(base_dir or os.getcwd())
    # Excel 单一母本：优先用上级目录的共享 test_data（两平台读同一份），
    # 不存在时回退到平台目录内的 test_data（兼容旧布局/自定义 base_dir）
    shared = os.path.join(os.path.dirname(BASE_DIR), "test_data")
    path = shared if os.path.isdir(shared) else BASE_DIR + "\\test_data"
    path2 = BASE_DIR + "\\fbist_pattern"

    model = workbook_model or load_workbook_model(BASE_DIR, master)
    if not isinstance(model, WorkbookModel):
        raise TypeError("workbook_model must be a WorkbookModel")
    wb = model
    ws = model["FLOW"]
    wc = model["pattern"]
    sheets = {title: model.dataframe(title) for title in model.sheetnames}
    VERSION = sheets["VERSION"]
    FLOW = normalize_flow_table(sheets["FLOW"])
    FLOW.attrs["common_dac_dependencies"] = tuple(
        str(FLOW.iloc[row]["item"]).strip()
        for row in range(len(FLOW))
        if ws["B"][row + 1].fill.fgColor.type == "rgb"
        and ws["B"][row + 1].fill.fgColor.rgb == "FFFFFF00"
    )
    ADDR_MAP = sheets["ADDR_MAP"]
    KP_RELAY = sheets["KP RELAY"]
    NM_PATTERN = sheets["NM_pattern"]
    FLASH_EPR = sheets["FLASH_EPR"]
    PATTERN = sheets["pattern"]
    if mode == "lab":
        singel = sheets["PIN DEC SINGEL"]
        lab_rows = singel[singel["TESTER"].astype(str).str.strip().str.lower()
                          == platform].copy()
        cp_nums = []
        for c in VERSION["CP num"]:
            if c not in cp_nums:
                cp_nums.append(c)
        parts = []
        for cp in cp_nums:
            rows = lab_rows.copy()
            rows["CP NO"] = cp
            parts.append(rows)
        PIN_DEC_128 = pd.concat(parts, ignore_index=True)
        OUT_DIR = BASE_DIR + "\\LAB\\" + platform.upper()
    else:
        PIN_DEC_128 = sheets["PIN DEC"]
        OUT_DIR = BASE_DIR
