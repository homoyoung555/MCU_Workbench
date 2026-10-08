# FB MAP sheet 解析：寄存器地址 <-> 字段名 <-> 位段 的权威反查表。
#
# 背景：`pattern.addr`/`FLASH_EPR.addr` 目前是人工对照硬件寄存器文档手填的 7bit 地址，
# 跟同一行 description/configs 里的字段名是两份独立手填数据，容易对不齐（历史上已经
# 抓到过 flash_pattern_label_created 写反、item 拼写不一致这类"填两遍总有一遍错"的真
# bug）。用户新增的 `FB MAP` sheet 是寄存器地址(col A,十进制) -> 寄存器分组名(col B) ->
# 按位铺开的字段名(col C..R, 表头是 bit15..bit0) 的权威表，本模块把它解析成
# "字段名(归一化后) -> [(addr, bit_hi, bit_lo, 寄存器名), ...]" 的反查表，供后续校验/
# 自动映射使用（本模块本身不接入任何生成/校验流程，纯解析）。
#
# 放在仓库根目录（跟 program_gen/、preflight/ 平级）而不是 program_gen/core/ 下：
# preflight/rules.py 明确"不 import 生成器"，但 Phase 2 的校验规则要复用这份解析逻辑；
# 放根目录让 program_gen 和 preflight 都能平级 import，不产生任何一方对另一方的依赖
# （跟 tools/check_master.py 一样，靠 sys.path 插入根目录来 import 平级包）。
#
# 只支持新版母本（有 FB MAP sheet）；旧母本没有这张表时 build_index_from_workbook 返回
# 空 dict，调用方按"功能整体跳过"处理，不得报错——这是硬约束（老母本必须照常能跑）。
import re

SHEET_NAME = "FB MAP"

# 占位/保留位说明（"不可读写"/"可读写"），不是真实字段名，解析时跳过
_RESERVED_MARK_RE = re.compile(r"不可读写|可读写")

# 字段名里的位宽标注 [3:0] / <3:0>，以及中文括注（如 "（只读）"/"(只读)"），归一化时去掉
_BIT_RANGE_RE = re.compile(r"[\[<].*?[\]>]")
_PAREN_RE = re.compile(r"[（(].*?[）)]")


def _piece_own_width(piece):
    """从字段名自带的 [hi:lo]/<hi:lo> 标注算位宽；没有标注返回 None。"""
    m = _BIT_RANGE_RE.search(piece)
    if not m:
        return None
    inner = m.group(0)[1:-1]
    if ":" not in inner:
        return None
    try:
        h, l = inner.split(":")
        return int(h.strip()) - int(l.strip()) + 1
    except ValueError:
        return None


def normalize_field_name(raw):
    """字段名归一化：去掉位宽标注/中文括注/首尾逗号空格，转大写，作为反查表 key。"""
    name = str(raw)
    name = _BIT_RANGE_RE.sub("", name)
    name = _PAREN_RE.sub("", name)
    name = name.strip().strip(",").strip()
    return name.upper()


def build_index_from_workbook(wb):
    """解析 wb["FB MAP"]（若存在），返回 {归一化字段名: [(addr, bit_hi, bit_lo, 寄存器名), ...]}。

    wb 是保留 merged_cells 的只读 WorkbookModel facade。母本没有 FB MAP sheet 时返回 {}。
    """
    if SHEET_NAME not in wb.sheetnames:
        return {}
    ws = wb[SHEET_NAME]

    merge_lookup = {}
    for mc in ws.merged_cells.ranges:
        for row in range(mc.min_row, mc.max_row + 1):
            for col in range(mc.min_col, mc.max_col + 1):
                merge_lookup[(row, col)] = mc

    # 表头第 1 行：col 3..18 是 bit15..bit0（addr[6:0]/分类/默认值 三列不参与位映射）
    max_col = ws.max_column
    bit_cols = [c for c in range(3, max_col + 1)
                if isinstance(ws.cell(row=1, column=c).value, (int, float))]
    bitmap = {c: int(ws.cell(row=1, column=c).value) for c in bit_cols}

    index = {}
    last_addr = None
    last_reg_name = None
    for r in range(2, ws.max_row + 1):
        addr_cell = ws.cell(row=r, column=1).value
        if addr_cell is not None:
            last_addr = int(str(addr_cell).strip())
        reg_cell = ws.cell(row=r, column=2).value
        # 分类(寄存器名)列跟位字段列一样会纵向合并（如 B18:B48 全是 "FLASH"），非合并区左上角
        # 的单元格读出来是 None，要沿用上一行的值，不能按"本行为空就是没有寄存器名"处理。
        if reg_cell is not None:
            last_reg_name = str(reg_cell).strip()
        reg_name = last_reg_name

        for col in bit_cols:
            v = ws.cell(row=r, column=col).value
            if v is None:
                continue
            mc = merge_lookup.get((r, col))
            c0, c1 = (mc.min_col, mc.max_col) if mc else (col, col)
            hi, lo = bitmap.get(c0), bitmap.get(c1)
            if hi is None or lo is None:
                continue
            if last_addr is None:
                continue

            pieces = [p.strip() for p in str(v).split(",")
                      if p.strip() and not _RESERVED_MARK_RE.search(p)]
            # 有的合并单元格把多个同级字段挤在一格里，逗号分隔（如
            # "ADC2_CMP_OP[3:0],ADC2_IREF_TRIM[3:0]" 共占整格 8 位，各占 4 位）。
            # 每个 piece 自带的 [hi:lo]/<hi:lo> 标注就是它自己的位宽，如果所有 piece
            # 都带宽度标注且总和正好等于整格位宽，按顺序从高位往低位切分；否则
            # （单 piece，或宽度信息不全/对不上）退化为整格区间都给它。
            widths = [_piece_own_width(p) for p in pieces]
            if len(pieces) > 1 and all(w is not None for w in widths) and sum(widths) == hi - lo + 1:
                cursor = hi
                for piece, w in zip(pieces, widths):
                    p_hi, p_lo = cursor, cursor - w + 1
                    cursor = p_lo - 1
                    key = normalize_field_name(piece)
                    if key:
                        index.setdefault(key, []).append((last_addr, p_hi, p_lo, reg_name))
            else:
                for piece in pieces:
                    key = normalize_field_name(piece)
                    if key:
                        index.setdefault(key, []).append((last_addr, hi, lo, reg_name))

    return index


def resolve_addr(raw_addr, field_names, index, width=7):
    """Phase 3：生成期判定/推导一行 pattern.addr / FLASH_EPR.addr。

    raw_addr：母本手填值（位串字符串）或空（None/NaN，pandas 空单元格读作 float）。
    field_names：该行 description/configs 里出现的字段名（未归一化，原样传入即可）。
    index：build_index_from_workbook 的返回值；为空 dict（老母本
    无 FB MAP sheet）时功能整体跳过——手填非空直接沿用、手填为空则无法推导只能报错
    （老母本不会走到这条路径，因为它们的 addr 从来都是手填的）。

    **逐字段校验，不是"任一字段对上就算过"**：同一行常见多个字段（如
    "bank_sel[1:0]=..\\nmco_sel[3:0]=..\\nmco_pre[3:0]=.."），若其中一个字段名手误、
    但其它字段恰好都指向手填的 addr，"只要有一个字段对上"这种聚合判定会漏掉那一个
    写错的字段——必须对每个能在 FB MAP 查到的字段单独核对，任何一个跟 addr 不一致
    都算错（这正是 2026-07-03 探索阶段抓到的 bank_sel/bank_en 那类真实分歧的形状）。

    返回 (addr_str, derived)：derived=True 表示 addr 是从 FB MAP 推导出来的（母本原本
    留空）。手填与 FB MAP 冲突 / 留空但无法唯一确定 时抛 ValueError，让生成在这一步
    就停下——好过悄悄用错的 addr 生成出能编译但语义错的向量。
    """
    per_field = {}   # 字段名(原样) -> FB MAP 里查到的候选 addr 集合（查不到的字段不入表）
    for name in field_names:
        hits = index.get(normalize_field_name(name))
        if hits:
            per_field[name] = {a for a, hi, lo, r in hits}

    blank = raw_addr is None or isinstance(raw_addr, float)
    if blank:
        if not per_field:
            raise ValueError(
                f"addr 留空，且字段 {field_names} 都在 FB MAP 里查不到，无法自动推导："
                "要么手填 addr，要么把字段名改成跟 FB MAP 一致、或补全 FB MAP")
        common = None
        for hits in per_field.values():
            common = set(hits) if common is None else (common & hits)
        if common and len(common) == 1:
            return format(next(iter(common)), f"0{width}b"), True
        detail = ", ".join(f"{n}->{sorted(h)}" for n, h in per_field.items())
        raise ValueError(
            f"addr 留空，但这些字段在 FB MAP 里对应的地址不一致或无法唯一确定（{detail}），"
            "无法自动推导，请手填 addr")

    raw_addr = str(raw_addr).strip()
    if raw_addr == "/" or not all(c in "01" for c in raw_addr):
        return raw_addr, False  # "/" 占位或非法位串：另有 preflight C1/slash 规则管，这里不重复校验
    if not per_field:
        return raw_addr, False  # FB MAP 无索引/这些字段一个都查不到，没法校验，沿用手填值
    addr_dec = int(raw_addr, 2)
    mismatches = [(n, sorted(h)) for n, h in per_field.items() if addr_dec not in h]
    if mismatches:
        detail = "; ".join(f"{n} 应在 addr {h}" for n, h in mismatches)
        raise ValueError(
            f"addr={raw_addr}({addr_dec})，但字段 {detail}（与 FB MAP 不一致），请核对母本数据")
    return raw_addr, False


def parse_epr_configs(text):
    """解析 FLASH_EPR.configs 一格文本：每行一个字段，`NAME(offset,width)` 手填，或裸 `NAME`
    （不写括号）——括号留空表示 offset/width 交给 FB MAP 全自动确定（用户裁决
    2026-07-03：写了括号=手填优先、仍跟 FB MAP 交叉核对；不写括号=完全自动，取 FB MAP
    在该字段解析出的 addr 下的完整位段，不能再表达"故意比 FB MAP 窄"这种写法，需要
    这种写法时必须继续手填括号）。

    返回 [(name, offset_or_None, width_or_None), ...]，offset/width 为 None 表示括号留空。
    """
    out = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if "(" in line:
            try:
                name = line.split("(")[0].strip()
                off = int(line.split("(")[1].split(",")[0])
                width = int(line.split("(")[1].split(",")[1].split(")")[0])
            except (IndexError, ValueError):
                continue
            out.append((name, off, width))
        else:
            out.append((line, None, None))
    return out


def resolve_field_span(name, addr_dec, index, context=""):
    """给字段名 + 已确定的 addr（十进制），从 FB MAP 反查它的位段 (bit_hi, bit_lo)。
    `resolve_field_width`（FLASH_EPR 括号留空）和 pattern.description 缺省"起始位,"
    前缀（2026-07-03 新增）共用这份查找逻辑。要求该字段在 FB MAP 里对应这个 addr
    下有且只有一条位段记录，否则抛 ValueError（跟 resolve_addr 一个原则：推导不出
    来就该在这一步就停下，不要带着猜出来的值继续生成）。

    context：错误信息里区分"括号留空"/"起始位缺省"等场景的措辞，不传则用通用措辞。
    """
    ctx = context or "缺省信息"
    hits = index.get(normalize_field_name(name))
    if not hits:
        raise ValueError(
            f"字段 {name} {ctx}，但在 FB MAP 里查不到，无法自动获取位段：要么手填、要么补全 FB MAP")
    matches = {(hi, lo) for a, hi, lo, r in hits if a == addr_dec}
    if not matches:
        raise ValueError(
            f"字段 {name} {ctx}，但 FB MAP 里没有它在 addr={addr_dec} 下的记录，无法自动获取位段")
    if len(matches) > 1:
        raise ValueError(
            f"字段 {name} {ctx}，但 FB MAP 里在 addr={addr_dec} 下有多条不同位段 "
            f"{sorted(matches)}，无法唯一确定，请手填")
    return next(iter(matches))


def resolve_field_width(name, addr_dec, index):
    """给字段名 + 已确定的 addr（十进制），从 FB MAP 反查 (offset, width)。
    `parse_epr_configs` 括号留空的字段用这个补全。"""
    hi, lo = resolve_field_span(name, addr_dec, index, context="括号留空")
    return lo, hi - lo + 1


def parse_pattern_description(text):
    """解析 pattern.description 一格文本：每行 `起始位,字段名=值`（起始位手填）或裸
    `字段名=值`（起始位交给 FB MAP 全自动确定，用户裁决 2026-07-03："起始位,"前缀
    留空表示完全自动，取 FB MAP 里该字段在解析出的 addr 下的最高位）。

    返回 [(name, hi_or_None, lo_or_None), ...]，hi/lo 为 None 表示起始位缺省。手填时
    按字段名自带的 `[hi:lo]`/`<hi:lo>` 位宽标注算宽度（没有就用值本身的位数），跟
    `core/encoding.py:value_to_binary` 的算法一致（不是重新发明一套解析规则）。
    """
    out = []
    for line in text.split("\n"):
        line = line.strip()
        if not line or "=" not in line:
            continue
        left, value = line.split("=", 1)
        left = left.strip()
        if "," in left:
            pos_part, name = left.split(",", 1)
            pos_part = pos_part.strip()
            if pos_part.lstrip("-").isdigit():
                start = int(pos_part)
                name = name.strip()
                width = _piece_own_width(name) or len(value.strip())
                out.append((name, start, start - width + 1))
                continue
        out.append((left, None, None))
    return out


def resolve_field_start_bit(name, addr_dec, index):
    """给字段名 + 已确定的 addr（十进制），从 FB MAP 反查它在寄存器里的起始位（bit_hi）。
    pattern.description 缺省"起始位,"前缀（裸 `NAME=值`，不写 `N,NAME=值`）的字段用
    这个补全——`value_to_binary` 要的"起始位"就是字段的最高位 bit_hi（同一份数据
    格式里 `4,BG_TC_TRIM[4:0]=xxxxx` 的 4 正是该字段 bit[4:0] 的最高位）。
    """
    hi, _lo = resolve_field_span(name, addr_dec, index, context="起始位缺省")
    return hi
