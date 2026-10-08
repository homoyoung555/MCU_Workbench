"""
内部表示 (Intermediate Representation) 数据结构。

把 WGL 解析成纯数据对象，再由 emitter 生成 .pat 文件。
"""

from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional


@dataclass
class Signal:
    """WGL signal 段中的一个引脚定义。"""
    name: str                # 完整名 如 "PAD_PA_15" (已展开 bus index)
    direction: str           # 'input' / 'output' / 'bidir'


@dataclass
class ScanChain:
    """WGL scanchain 段定义的一条 scan 链。"""
    name: str                # 例 "edt_top_channel1_chain"
    scan_in_pin: str         # 例 "PAD_PA_8"   (链入口)
    scan_out_pin: str        # 例 "PAD_PA_10"  (链出口)
    length: int              # 链中 cell 数量（决定 shift cycle 数）


@dataclass
class Timeplate:
    """timeplate (WFT) 定义，只关心名字。"""
    name_wgl: str            # 例 "_default_WFT_"
    name_pat: str            # 例 "default_WFT"   (去首尾下划线)
    period_ns: float         # 例 40.0


class WGLVector:
    """pattern 体内一个 vector 子句。

    用 __slots__ 而非 dataclass: 百万级实例时显著降内存、加快属性访问;
    非 scan 拍不分配 scan_inputs/scan_outputs 空 dict(惰性, 仅 scan 拍创建)。
    """
    __slots__ = ('wft', 'chars', 'is_scan', 'scan_inputs', 'scan_outputs',
                 'src_line', 'repeat', 'label')

    def __init__(self, wft: str, chars: str, is_scan: bool = False,
                 scan_inputs: Optional[Dict[str, str]] = None,
                 scan_outputs: Optional[Dict[str, str]] = None,
                 src_line: int = 0, repeat: int = 1,
                 label: Optional[str] = None):
        self.wft = wft                  # WFT 名 (WGL 原名,如 "_default_WFT_")
        self.chars = chars              # pattern 头声明长度的字符串
        self.is_scan = is_scan
        # 非 scan 拍这两项保持 None(不分配 dict); scan 拍由解析器填入
        self.scan_inputs = scan_inputs    # chain_name → 输入串
        self.scan_outputs = scan_outputs  # chain_name → 期望输出串
        self.src_line = src_line          # 源文件行号(调试用)
        self.repeat = repeat              # WGL "repeat N vector(...)" → 该拍重复 N 次
        self.label = label                # 识别到的标记 label (如 M_Iddq_1); None=无


@dataclass
class WGLPattern:
    """整个 WGL pattern。"""
    name: str                              # 例 "Chain_Scan_test"
    pin_list: List[Tuple[str, str]] = field(default_factory=list)
    # ↑ [(pin_name, direction)],  direction ∈ {'', 'I', 'O'}
    # 例: [('VCORE_RDY_OPT_1',''), ('PAD_PA_15','I'), ..., ('PAD_PA_15','O'), ...]
    vectors: List[WGLVector] = field(default_factory=list)


@dataclass
class WGLDesign:
    """整个 WGL 文件的解析结果。"""
    signals: List[Signal] = field(default_factory=list)
    # signal 段顺序保留 → .pat HEADER 顺序
    scanchains: Dict[str, ScanChain] = field(default_factory=dict)
    timeplates: Dict[str, Timeplate] = field(default_factory=dict)
    # WGL 原名 → Timeplate 对象
    scanstates: Dict[str, str] = field(default_factory=dict)
    # scanstate 变量名 → 字符串值 (如 Iedt_top_channel1_sts000000_000002 → "0000...")
    pattern: Optional[WGLPattern] = None
    # 元数据 (从 WGL 头注释提取)
    source_filename: str = ""
    creation_date: str = ""


# ---------- 用于 emitter 的辅助函数 ----------

def wft_name_strip(wgl_name: str) -> str:
    """WGL WFT 名 → .pat WFT 名：去掉首尾下划线"""
    return wgl_name.strip("_")
