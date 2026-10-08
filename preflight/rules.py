# A–F 确定性检查规则。每个 check_* 接收 (reader, findings) 往 findings 追加 Finding。
# 纯确定性、无 LLM、不 import 生成器（fb_map 是仓库根目录的中立解析模块，双方平级
# import，见 fb_map.py 头部注释，不算"import 生成器"）。
import re

import fb_map
import pandas as pd
from flow_recipe import (
    FlowCompileError, compile_flow, compile_recipe_program,
    compile_result_export_plan_set, parse_recipe,
)
from program_gen.core.addr_map import AddrMapCompileError, compile_addr_map_catalog
from program_gen.core.default_commit import compile_default_commit_bindings
from program_gen.core.persistence_recipe import PersistenceCompileError, compile_persistence_plan
from program_gen.core.commit_shmoo import CommitShmooPlanError, compile_commit_shmoo_plans

from . import schema as S
from .report import Finding, ERROR, WARN

# ---- 字符卫生用字符集 ----
# 全角/中文标点 + 全角 ASCII 变体(U+FF01–FF5E) + 表意空格(U+3000) + CJK 标点 + 弯引号
_ZERO_WIDTH = {"​", "﻿", "‎", "‏", "⁠"}
_NBSP = {" ", "　"}                         # 不间断空格 / 表意空格


def _fullwidth_chars(s):
    bad = []
    for ch in s:
        o = ord(ch)
        if 0xFF01 <= o <= 0xFF5E:          # 全角 ASCII（％（）－＋ 等）
            bad.append(ch)
        elif 0x3000 <= o <= 0x303F:        # CJK 标点（，。；：「」 等）+ 表意空格
            bad.append(ch)
        elif ch in ("‘", "’", "“", "”"):  # 弯引号
            bad.append(ch)
    return bad


# ============ A 字符卫生 ============
# 强类型列(生成器严格解析)里出问题 → ERROR；宽松列(母本已证明容忍) → WARN。隐形字符永远 WARN+。
def check_char_hygiene(reader, findings):
    for sheet, cols in S.CONSUMED.items():
        if not reader.has_sheet(sheet):
            continue
        for col in cols:
            freetext = S.is_freetext(sheet, col)
            strict = S.spec_for(sheet, col) is not None     # 强类型=严格解析列
            sev = ERROR if strict else WARN
            for cell in reader.column_cells(sheet, col):
                if cell.value is None or not isinstance(cell.value, str):
                    continue
                v = cell.value
                # 隐形字符（永远可疑）
                zw = [c for c in v if c in _ZERO_WIDTH]
                if zw:
                    findings.append(Finding(sheet, cell.coord, "A 字符卫生", sev,
                        f"含隐形字符(零宽/BOM) U+{ord(zw[0]):04X}", "删掉该不可见字符"))
                # 首尾空格（含全角/不间断空格）
                if v != v.strip() or any(c in _NBSP for c in (v[:1] + v[-1:])):
                    space_sev = WARN if S.normalizes_outer_spaces(sheet, col) else sev
                    findings.append(Finding(sheet, cell.coord, "A 字符卫生", space_sev,
                        f"首尾有空格: {v!r}", "去掉首尾空格"))
                # 内部不间断/表意空格
                elif any(c in _NBSP for c in v.strip()):
                    findings.append(Finding(sheet, cell.coord, "A 字符卫生", sev,
                        "含全角/不间断空格", "换成普通半角空格或删除"))
                # 全角字符（自由文本列允许中文，跳过）
                if not freetext:
                    fw = _fullwidth_chars(v)
                    if fw:
                        findings.append(Finding(sheet, cell.coord, "A 字符卫生", sev,
                            f"含全角/中文符号 {''.join(sorted(set(fw)))!r}",
                            "改成半角（如 ％→% ，（→( ）"))


# ============ B 结构 ============
def check_structure(reader, findings):
    # B1 缺列：消费列必须存在
    for sheet, cols in S.CONSUMED.items():
        if not reader.has_sheet(sheet):
            findings.append(Finding(sheet, "", "B 结构", ERROR, "缺少 sheet", "母本缺这张表"))
            continue
        hm = reader.header_map(sheet)
        for col in cols:
            if col not in hm:
                if sheet == "FLOW" and col == "Recipe":
                    continue
                findings.append(Finding(sheet, "", "B 结构", ERROR,
                    f"缺少列 '{col}'（生成器要用）", "补上该列表头"))
    # B2 FLOW 数据区中间空行：item 空但同行别的列有数据 → 迭代错位
    if reader.has_sheet("FLOW") and "item" in reader.header_map("FLOW"):
        watch = [c for c in ("CP NO", "type", "mode", "target") if c in reader.header_map("FLOW")]
        for rec in reader.row_values("FLOW", ["item"] + watch):
            it = rec["item"]
            if it.is_blank and any(not rec[c].is_blank for c in watch):
                findings.append(Finding("FLOW", f"row {it.row}", "B 结构", ERROR,
                    "数据区中间空 item 行（其它列有值）", "删掉空行或补 item 名"))


# ============ C 类型/格式 ============
_NUM_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)$")
_DIGITAL_COMPARE_RE = re.compile(r"^[HL]+$", re.IGNORECASE)
_LIMIT_PCT_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)\s*%$")     # 50% / 0.8%
_LIMIT_SIGNED_RE = re.compile(r"^[+-](\d+\.?\d*|\.\d+)$")        # +0.5 / -0.09（带号偏移）
_LIMIT_PLAIN_RE = re.compile(r"^(\d+\.?\d*|\.\d+)$")             # 1.0（纯数字=绝对，无号）


def check_types(reader, findings):
    # FLOW.target 例外：UNIT=="pat" 的行，target 不是数值目标而是比较 pattern 后缀
    # （如 "HH"/"LL"/"LH"，见 chroma/writers.py:_keil_step_write 的 T token "UNIT==pat"
    # 分支，用户裁决 2026-07-03）——按行号收集，只放行这些行，其余行 target 仍强制数值。
    pat_unit_rows = set()
    if reader.has_sheet("FLOW") and "UNIT" in reader.header_map("FLOW"):
        for cell in reader.column_cells("FLOW", "UNIT"):
            if cell.text.strip().lower() == "pat":
                pat_unit_rows.add(cell.row)

    # Native firmware rows declare comparison through Recipe=...JUDGE and keep
    # UNIT empty.  Their H/L target is a digital expectation, not a number.
    native_compare_rows = set()
    native_compare_columns = {"mode", "Recipe", "target"}
    if (
        reader.has_sheet("FLOW")
        and native_compare_columns.issubset(reader.header_map("FLOW"))
    ):
        for rec in reader.row_values("FLOW", sorted(native_compare_columns)):
            recipe_modules = {
                token.strip().split("(", 1)[0]
                for token in re.split(r"[-\r\n]+", rec["Recipe"].text.upper())
                if token.strip()
            }
            if (
                rec["mode"].text.strip().lower() == "keil"
                and "JUDGE" in recipe_modules
                and _DIGITAL_COMPARE_RE.fullmatch(rec["target"].text.strip())
            ):
                native_compare_rows.add(rec["target"].row)

    # 功能族把 FLOW.low/high 当“参数来自独立 sweep sheet”的哨兵，而非真正 limit。
    # OPA/PVD/FREQ 的 FLOW.target 也是哨兵；ADC/DAC 的 target 仍是必须校验的满量程码数。
    sweep_rows = {}
    if reader.has_sheet("FLOW") and "FV/FI" in reader.header_map("FLOW"):
        for rec in reader.row_values("FLOW", ["FV/FI"]):
            cell = rec["FV/FI"]
            family = cell.text.strip().upper()
            if family.startswith("ADC") or family in {"OPA", "COMP", "DAC", "PVD", "FREQ"}:
                sweep_rows[cell.row] = family

    for (sheet, col), spec in S.TYPED.items():
        if not reader.has_sheet(sheet) or col not in reader.header_map(sheet):
            continue
        typ = spec["type"]
        slash_ok = spec.get("slash_ok", False)
        required = spec.get("required", False)
        for cell in reader.column_cells(sheet, col):
            raw = cell.text.strip()
            # 空值
            if cell.is_blank:
                if required:
                    findings.append(Finding(sheet, cell.coord, "B 结构", ERROR,
                        f"'{col}' 必填却为空", "补上值"))
                continue
            if slash_ok and raw == "/":
                continue
            if sheet == "FLOW" and col in ("low_range(%)", "high_range(%)") \
                    and cell.row in sweep_rows:
                continue
            if (sheet, col) == ("FLOW", "target") \
                    and sweep_rows.get(cell.row) in ("OPA", "COMP", "PVD", "FREQ"):
                continue
            if (sheet, col) == ("FLOW", "target") and cell.row in (
                pat_unit_rows | native_compare_rows
            ):
                continue  # 数字比较H/L串不是数值目标
            # C1 位串必须文本格式（数字格式会丢前导0/导致生成器崩）
            if typ == S.BITSTRING:
                if cell.dtype == "n":
                    findings.append(Finding(sheet, cell.coord, "C1 类型", ERROR,
                        f"位串 '{raw}' 被存成了数字格式", "把单元格设为文本格式后重输（保前导0）"))
            elif typ == S.NUMBER:
                if not _NUM_RE.match(raw):
                    findings.append(Finding(sheet, cell.coord, "C2 类型", ERROR,
                        f"应为数值，实为 {raw!r}", "改成纯数字" + ("（或 /）" if slash_ok else "")))
            elif typ == S.LIMIT:
                if not (_LIMIT_PCT_RE.match(raw) or _LIMIT_SIGNED_RE.match(raw) or _LIMIT_PLAIN_RE.match(raw)):
                    findings.append(Finding(sheet, cell.coord, "C3 类型", ERROR,
                        f"limit 格式非法: {raw!r}", "须为 带%/带±号/纯数字 三选一（百分比别漏 %）"))
            elif typ == S.ENUM:
                allowed = spec["enum"]
                ok = (raw.lower() in [v.lower() for v in allowed]) if spec.get("ci") else (raw in allowed)
                if not ok:
                    findings.append(Finding(sheet, cell.coord, "D 取值", ERROR,
                        f"'{raw}' 不在允许集 {allowed}", f"改成 {allowed} 之一"))
            elif typ == S.PIN:
                # 管脚名：非空 token（更强的"必须在 PIN DEC 定义"留作后续）
                if " " in raw:
                    findings.append(Finding(sheet, cell.coord, "C 类型", WARN,
                        f"管脚名含空格: {raw!r}", "确认管脚名"))


# ============ D 跨表/一致性 ============
def check_cross_ref(reader, findings):
    # item 名"大小写/空格变体"探测：归一化(lower+strip)相同但原文不同 → 疑似 typo
    seen = {}    # norm -> {raw: 首次出现位置}
    for sheet, col in S.ITEM_NAME_COLUMNS:
        if not reader.has_sheet(sheet) or col not in reader.header_map(sheet):
            continue
        for cell in reader.column_cells(sheet, col):
            if cell.is_blank:
                continue
            raw = cell.text
            norm = raw.strip().lower()
            seen.setdefault(norm, {}).setdefault(raw, f"{sheet}!{cell.coord}")
    for norm, variants in seen.items():
        if len(variants) > 1:
            vs = list(variants.items())
            where = "; ".join(f"{r!r}@{loc}" for r, loc in vs)
            # 2026-07-03 WARN→ERROR（用户裁决）：两次真实踩坑（VregSetOp/VregStOp、
            # MR_Trim/Mr_Trim）都证明这不是误报——item 名跨表大小写不一致会让
            # trim_item_write 等按精确字符串匹配的 writer 静默跳过整个测试项（外围
            # 声明/TEST_PRO 调度表照常生成，函数体却是空的），本地生成/编译都不报错，
            # 直到上机或人工比对才暴露，代价远高于误报风险。
            findings.append(Finding(vs[0][1].split("!")[0], vs[0][1].split("!")[1],
                "D 一致性", ERROR,
                f"item 名疑似拼写不一致(大小写/空格): {where}", "统一成同一拼写"))


# ============ E 位段重叠 ============
_PAT_FIELD_RE = re.compile(r"^\s*(\d+)\s*,\s*([^=]+?)\s*=\s*([01xX]+)\s*$")


def _spans_pat(text):
    spans = []
    for line in text.split("\n"):
        m = _PAT_FIELD_RE.match(line)
        if not m:
            continue
        start, name, value = int(m.group(1)), m.group(2).strip(), m.group(3)
        br = re.search(r"\[(\d+)\s*:\s*(\d+)\]", name)
        width = (int(br.group(1)) - int(br.group(2)) + 1) if br else len(value)
        spans.append((name, start, start - width + 1))
    return spans


def _spans_epr(text):
    spans = []
    for line in text.split("\n"):
        try:
            name = line.split("(")[0].strip()
            off = int(line.split("(")[1].split(",")[0])
            width = int(line.split("(")[1].split(",")[1].split(")")[0])
            spans.append((name, off + width - 1, off))
        except (IndexError, ValueError):
            continue
    return spans


def check_bitfields(reader, findings):
    parsers = {"pat": _spans_pat, "epr": _spans_epr}
    for sheet, col, style in S.BITFIELD_SOURCES:
        if not reader.has_sheet(sheet) or col not in reader.header_map(sheet):
            continue
        parse = parsers[style]
        for cell in reader.column_cells(sheet, col):
            if not isinstance(cell.value, str):
                continue
            spans = parse(cell.value)
            for a in range(len(spans)):
                for b in range(a + 1, len(spans)):
                    n1, h1, l1 = spans[a]
                    n2, h2, l2 = spans[b]
                    if not (h1 < l2 or h2 < l1):
                        findings.append(Finding(sheet, cell.coord, "E 位段重叠", ERROR,
                            f"字段 {n1}(bit{h1}..{l1}) 与 {n2}(bit{h2}..{l2}) 重叠",
                            "改位段定义避免重叠"))


# ============ F FB MAP 映射校验（只读校验，2026-07-03 引入） ============
# 母本新增 `FB MAP` sheet 后（寄存器 addr <-> 字段名 <-> 位段的权威表），交叉核对
# pattern.description / FLASH_EPR.configs 里手填的 addr、位宽跟 FB MAP 是否一致；
# addr 留空的行则核对字段名能否在 FB MAP 里唯一确定地址（Phase 3 生成器 `fb_map.
# resolve_addr` 就是靠这个推导 addr 的，推导不出来会在生成时直接抛 ValueError 中止，
# 这里用同一份逻辑提前在生成前抓出来，报告到具体单元格，不用等生成期崩溃）。
# addr 已填时的不一致仍只 WARN、不升 ERROR：探索阶段已经在真实母本上验证过至少 2 处
# 分歧（RA 位宽 8 vs 9、BANK_SEL/BANK_EN 地址混淆），在用户确认哪边对之前贸然 ERROR
# 会拦住合法生成——跟 check_cross_ref 的 item 拼写规则当年 WARN→ERROR 分两步走是
# 同一节奏，需要先跑一段时间证明"不是母本一贯的正常写法"才能升级。
# addr 留空时推导不出来 = ERROR：这种情况生成必定崩溃（Phase 3 resolve_addr 会抛
# ValueError），不是"风格问题"而是"肯定生成不出来"，没有 WARN 的空间。
# 老母本没有 FB MAP sheet（WorkbookModel index 为空 dict）时整条规则跳过，
# 不影响老母本校验结果——这是硬约束，见 fb_map.py 头部注释。
#
# pattern 与 FLASH_EPR 分两个函数处理（不再共用一份泛型循环）：FLASH_EPR 的 configs
# 现在支持字段括号留空、offset/width 全自动从 FB MAP 取（用户裁决 2026-07-03），
# 这需要用 `fb_map.parse_epr_configs`（保留裸字段名）而不是 `_spans_epr`（会静默丢弃
# 没括号的行）；pattern.description 没有这个"括号可留空"的概念，字段位置永远由行内
# 文本自带，逻辑不变，继续用 `_spans_pat`。


def _fb_map_missing_field_findings(sheet, coord, field_names, index):
    """字段名能否在 FB MAP 查到——独立于 addr 推导/核对，即使这一行其它字段让 addr
    仍能顺利推导出来（resolve_addr 会忽略查不到的字段，不当它是拦路的），查不到的
    字段名本身也值得让用户知道（可能是命名跟 FB MAP 不一致，也可能是这个字段本就
    不在 FB MAP 覆盖范围内，不代表数据错，只是提示）。"""
    out = []
    for name in field_names:
        if not index.get(fb_map.normalize_field_name(name)):
            out.append(Finding(sheet, coord, "F FB MAP 映射", WARN,
                f"字段 {name} 在 FB MAP 里查不到（命名/后缀跟 FB MAP 不一致，或本就不在 FB MAP 覆盖范围内）",
                "确认字段名是否要跟 FB MAP 对齐；如果本就不在 FB MAP 里可以忽略"))
    return out


def _check_pattern_fb_map(reader, findings, index):
    # 用 fb_map.parse_pattern_description（保留裸字段名），不再用 _spans_pat——后者会
    # 静默丢弃没有"起始位,"前缀的行，字段名会漏（跟 FLASH_EPR 的 _spans_epr/
    # parse_epr_configs 同一个坑，2026-07-03 一起补）。
    sheet, addr_col, field_col = "pattern", "addr", "description"
    if not reader.has_sheet(sheet):
        return
    hm = reader.header_map(sheet)
    if addr_col not in hm or field_col not in hm:
        return
    addr_by_row = {c.row: c for c in reader.column_cells(sheet, addr_col)}
    for cell in reader.column_cells(sheet, field_col):
        if not isinstance(cell.value, str):
            continue
        parsed = fb_map.parse_pattern_description(cell.value)
        if not parsed:
            continue  # 非标准格式（32'hXXXX、reuse dac 的裸项名等），没有字段可核对
        field_names = [name for name, hi, lo in parsed]
        addr_cell = addr_by_row.get(cell.row)
        coord = addr_cell.coord if addr_cell is not None else cell.coord
        blank = addr_cell is None or addr_cell.is_blank
        raw_addr = None if blank else str(addr_cell.value).strip()

        findings.extend(_fb_map_missing_field_findings(sheet, coord, field_names, index))

        if not blank and (raw_addr == "/" or not all(c in "01" for c in raw_addr)):
            continue  # 非法/占位位串另有 C1 规则报，这里不重复报

        try:
            resolved_addr, _derived = fb_map.resolve_addr(raw_addr, field_names, index)
        except ValueError as e:
            findings.append(Finding(sheet, coord, "F FB MAP 映射", ERROR if blank else WARN, str(e),
                "字段名改成跟 FB MAP 一致、或补全 FB MAP、或手填 addr" if blank
                else "核对 FB MAP 与手填 addr 哪个对，确认后再统一"))
            continue

        # 起始位手填的字段：跟 FB MAP 交叉核对（WARN，不一致不代表谁一定错）。起始位
        # 缺省的字段：完全靠 FB MAP 推导，推导不出来是 ERROR——这跟 addr 是否留空是
        # 两个独立维度，addr 已填的行里同样可能有缺省起始位的字段，同样会在生成期崩。
        addr_dec = int(resolved_addr, 2)
        for name, hi, lo in parsed:
            if hi is not None:
                hits = index.get(fb_map.normalize_field_name(name))
                if not hits:
                    continue  # FB MAP 没这个字段（省略后缀/非位段名等），不报，避免噪音
                fb_hi, fb_lo = next((h, l) for a, h, l, r in hits if a == addr_dec)
                if (hi, lo) != (fb_hi, fb_lo):
                    findings.append(Finding(sheet, coord, "F FB MAP 映射", WARN,
                        f"字段 {name} 手填位段 bit[{hi}:{lo}] 与 FB MAP bit[{fb_hi}:{fb_lo}] 不一致",
                        "核对位宽定义，确认手填还是 FB MAP 有一方错"))
            else:
                try:
                    fb_map.resolve_field_start_bit(name, addr_dec, index)
                except ValueError as e:
                    findings.append(Finding(sheet, coord, "F FB MAP 映射", ERROR, str(e),
                        "手填起始位，或补全 FB MAP 让这个字段能在这个 addr 下唯一确定位段"))


def _check_flash_epr_fb_map(reader, findings, index):
    sheet, addr_col, field_col = "FLASH_EPR", "addr", "configs"
    if not reader.has_sheet(sheet):
        return
    hm = reader.header_map(sheet)
    if addr_col not in hm or field_col not in hm:
        return
    addr_by_row = {c.row: c for c in reader.column_cells(sheet, addr_col)}
    for cell in reader.column_cells(sheet, field_col):
        if not isinstance(cell.value, str):
            continue
        parsed = fb_map.parse_epr_configs(cell.value)
        if not parsed:
            continue
        field_names = [name for name, off, width in parsed]
        addr_cell = addr_by_row.get(cell.row)
        coord = addr_cell.coord if addr_cell is not None else cell.coord
        blank = addr_cell is None or addr_cell.is_blank
        raw_addr = None if blank else str(addr_cell.value).strip()

        findings.extend(_fb_map_missing_field_findings(sheet, coord, field_names, index))

        if not blank and (raw_addr == "/" or not all(c in "01" for c in raw_addr)):
            continue  # 非法/占位位串另有 C1 规则报，这里不重复报

        try:
            resolved_addr, _derived = fb_map.resolve_addr(raw_addr, field_names, index)
        except ValueError as e:
            findings.append(Finding(sheet, coord, "F FB MAP 映射", ERROR if blank else WARN, str(e),
                "字段名改成跟 FB MAP 一致、或补全 FB MAP、或手填 addr" if blank
                else "核对 FB MAP 与手填 addr 哪个对，确认后再统一"))
            continue

        # 括号带 (offset,width) 的字段：手填优先，跟 FB MAP 交叉核对（WARN，不一致不代表
        # 谁一定错，见 RA/HSI_ABS_TRIMCR_VDDK 那类已知分歧）。括号留空的字段：offset/width
        # 完全靠 FB MAP 推导，推导不出来是 ERROR——这跟 addr 是否留空是两回事，addr 已填
        # 时这一行同样可能有留空括号的字段，同样会在生成期崩，必须一起查。
        addr_dec = int(resolved_addr, 2)
        for name, off, width in parsed:
            if off is not None:
                hits = index.get(fb_map.normalize_field_name(name))
                if not hits:
                    continue  # FB MAP 没这个字段，不报，避免噪音（上面已经报过"查不到"）
                fb_hi, fb_lo = next((h, l) for a, h, l, r in hits if a == addr_dec)
                hi, lo = off + width - 1, off
                if (hi, lo) != (fb_hi, fb_lo):
                    findings.append(Finding(sheet, coord, "F FB MAP 映射", WARN,
                        f"字段 {name} 手填位段 bit[{hi}:{lo}] 与 FB MAP bit[{fb_hi}:{fb_lo}] 不一致",
                        "核对位宽定义，确认手填还是 FB MAP 有一方错"))
            else:
                try:
                    fb_map.resolve_field_width(name, addr_dec, index)
                except ValueError as e:
                    findings.append(Finding(sheet, coord, "F FB MAP 映射", ERROR, str(e),
                        "手填 (offset,width)，或补全 FB MAP 让这个字段能在这个 addr 下唯一确定位段"))


def check_fb_map_mapping(reader, findings):
    if not reader.has_sheet(fb_map.SHEET_NAME):
        return
    # The WorkbookModel facade preserves merged ranges, so preflight must use
    # the already-loaded request snapshot and never reopen reader.path.
    index = fb_map.build_index_from_workbook(reader.wb)
    if not index:
        return
    _check_pattern_fb_map(reader, findings, index)
    _check_flash_epr_fb_map(reader, findings, index)


def check_family_modes(reader, findings):
    """PVD has no SWD implementation; fail before generation instead of falling through."""
    if not reader.has_sheet("FLOW"):
        return
    hm = reader.header_map("FLOW")
    if "FV/FI" not in hm or "mode" not in hm:
        return
    for rec in reader.row_values("FLOW", ["FV/FI", "mode"]):
        if rec["FV/FI"].text.strip().upper() != "PVD":
            continue
        if rec["mode"].text.strip().lower() != "keil":
            findings.append(Finding(
                "FLOW", rec["mode"].coord, "D 取值", ERROR,
                "PVD 仅支持 mode=keil，SWD 无法实现",
                "把该行 mode 改为 keil",
            ))


def check_flow_recipe(reader, findings):
    """Validate Recipe syntax and FLOW grouping through the shared compiler seam."""
    required = ("CP NO", "item", "type", "sub", "Recipe")
    if not reader.has_sheet("FLOW"):
        return
    headers = reader.header_map("FLOW")
    if "Recipe" not in headers:
        findings.append(Finding(
            "FLOW", "", "G Recipe", WARN,
            "缺少 Recipe 列：将按 legacy writer 语义生成",
            "仅在迁移到显式 Recipe 流程时新增该列并逐行填写",
        ))
        return
    if any(column not in headers for column in required):
        return  # check_structure reports missing columns once.

    rows = []
    indices = []
    blank_cells = []
    for record in reader.row_values("FLOW", required):
        if record["item"].is_blank:
            continue
        recipe_cell = record["Recipe"]
        recipe_value = recipe_cell.value
        if recipe_cell.is_blank:
            blank_cells.append(recipe_cell)
            recipe_value = "JUDGE"  # structure-only placeholder during migration
        else:
            try:
                parse_recipe(recipe_value)
            except FlowCompileError as exc:
                findings.append(Finding(
                    "FLOW", recipe_cell.coord, "G Recipe", ERROR, str(exc),
                    "使用 '-' 或单元格内换行分隔模块；参数目前只能是二进制位置参数",
                ))
                recipe_value = "JUDGE"  # keep validating row identity/grouping

        rows.append({column: record[column].value for column in required})
        rows[-1]["Recipe"] = recipe_value
        indices.append(record["item"].row - 2)

    if blank_cells:
        findings.append(Finding(
            "FLOW", blank_cells[0].coord, "G Recipe", WARN,
            f"Recipe 迁移尚未完成：{len(blank_cells)} 行为空",
            "在接入新版生成路径前补齐；旧母本缺少 Recipe 列仍会被结构检查阻断",
        ))

    if not rows:
        return
    frame = pd.DataFrame(rows, index=indices)
    try:
        compile_flow(frame)
    except FlowCompileError as exc:
        message = str(exc)
        match = re.search(r"FLOW row (\d+)", message)
        coord = f"row {match.group(1)}" if match else ""
        findings.append(Finding(
            "FLOW", coord, "G Recipe", ERROR, message,
            "确保 CP+item+type+sub 唯一，并让同一 CP 的 item+type 行连续排列",
        ))


_PERSISTENCE_MODULES = frozenset({
    "BUILDMAP", "READOTPMAP", "LOADMAP", "SETVPOSP", "NMLOOP",
    "CHECKOTP", "COMMIT", "PGMOTP", "BUILDUID",
})


def check_persistence_recipe(reader, findings):
    """Compile page-oriented Recipe chains before either writer runs."""
    if not reader.has_sheet("FLOW") or not reader.has_sheet("ADDR_MAP"):
        return
    try:
        flow = reader.frame("FLOW")
        addr_map = reader.frame("ADDR_MAP")
    except AttributeError:
        flow_headers = tuple(reader.header_map("FLOW"))
        addr_headers = tuple(reader.header_map("ADDR_MAP"))
        flow = pd.DataFrame([
            {key: value.value for key, value in record.items()}
            for record in reader.row_values("FLOW", flow_headers)
        ])
        addr_map = pd.DataFrame([
            {key: value.value for key, value in record.items()}
            for record in reader.row_values("ADDR_MAP", addr_headers)
        ])
    if "Recipe" not in flow.columns:
        return
    selected = flow.loc[
        flow["Recipe"].fillna("").astype(str).str.upper().map(
            lambda value: any(module in value for module in _PERSISTENCE_MODULES)
        )
    ].copy()
    if selected.empty:
        return
    if "mode" not in selected.columns:
        selected["mode"] = "fbist"
    pattern = pd.DataFrame(columns=("item", "addr", "description", "pattern"))
    try:
        catalog = compile_addr_map_catalog(addr_map)
        program = compile_recipe_program(selected, pattern)
        executable_rows = {
            row.flow.excel_row - 2: row
            for function in program.functions for row in function.rows
        }
        rows_by_cp = {}
        for function in program.functions:
            rows_by_cp.setdefault(function.key.cp, []).extend(function.rows)
        for cp, cp_rows in rows_by_cp.items():
            # Page Image / loaded Pattern are CP-flow state.  Compiling each
            # generated function independently would reject legitimate chains
            # such as Memory_Wakeup.BUILDMAP -> Trimdata_Write_Read.LOADMAP.
            ordered_rows = tuple(sorted(cp_rows, key=lambda row: row.flow.excel_row))
            pages = tuple(
                page for page in catalog.pages
                if any(register.applies_to(cp) and register.page == page
                       for register in catalog.registers)
            )
            row_pages = {row.flow.excel_row: pages for row in ordered_rows}
            export_plans = compile_result_export_plan_set(
                flow, executable_rows, cp
            )
            export_symbols = {
                plan.flow_row_index: plan.symbol for plan in export_plans.plans
            }
            bindings_by_index = compile_default_commit_bindings(
                flow, executable_rows, catalog, export_symbols=export_symbols
            )
            row_bindings = {
                excel_row: bindings_by_index.get(excel_row - 2, ())
                for excel_row in row_pages
            }
            compile_persistence_plan(
                ordered_rows, catalog, node_default_pages=row_pages,
                node_default_bindings=row_bindings,
            )
        # Persistent Shmoo has additional first-version constraints (one range,
        # STEP for every field, and per-step width).  Preflight must exercise
        # the same compiler as main so these do not surface only at generation.
        compile_commit_shmoo_plans(flow, executable_rows, catalog)
    except (FlowCompileError, AddrMapCompileError, PersistenceCompileError,
            CommitShmooPlanError) as exc:
        message = str(exc)
        match = re.search(r"FLOW row (\d+)", message)
        findings.append(Finding(
            "FLOW", f"row {match.group(1)}" if match else "", "G Recipe",
            ERROR, message,
            "补齐显式生产模块，或调整 Recipe 顺序；生成器不会自动插入页面动作",
        ))


def _logical_item_key(value):
    text = re.sub(r"\[[^\]]+\]\s*$", "", str(value).strip())
    text = re.sub(r"_?(?:trim|verify)$", "", text, flags=re.IGNORECASE)
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def check_logical_item_linkage(reader, findings):
    """拦截残留角色后缀的链接，以及找不到 trim 来源的显式依赖。"""
    if not reader.has_sheet("FLOW"):
        return
    flow_headers = reader.header_map("FLOW")
    required = ("item", "type", "Recipe")
    if any(column not in flow_headers for column in required):
        return

    trim_items = {}
    flow_records = list(reader.row_values("FLOW", required))
    for record in flow_records:
        if record["type"].text.strip().casefold() != "trim":
            continue
        key = _logical_item_key(record["item"].text)
        if key:
            trim_items.setdefault(key, record["item"].text.strip())

    if reader.has_sheet("ADDR_MAP") and "CP addr map" in reader.header_map("ADDR_MAP"):
        for cell in reader.column_cells("ADDR_MAP", "CP addr map"):
            if not isinstance(cell.value, str):
                continue
            for token in re.findall(r"([A-Za-z][A-Za-z0-9_]*)\s*\[", cell.value):
                if not re.search(r"_(?:Trim|Verify)$", token, flags=re.IGNORECASE):
                    continue
                key = _logical_item_key(token)
                if key in {"pdr", "bor"} or key not in trim_items:
                    continue
                findings.append(Finding(
                    "ADDR_MAP", cell.coord, "H Logical Item", ERROR,
                    f"CP addr map 仍使用角色后缀：{token!r}",
                    f"改为逻辑 item {trim_items[key]!r}；Trim/Verify 只表示执行角色",
                ))
                break

    depend_re = re.compile(r"\bDEPEND\s*\(\s*([^()]+?)\s*\)", re.IGNORECASE)
    for record in flow_records:
        for dependency in depend_re.findall(record["Recipe"].text):
            if _logical_item_key(dependency) in trim_items:
                continue
            findings.append(Finding(
                "FLOW", record["Recipe"].coord, "H Logical Item", ERROR,
                f"DEPEND 目标 {dependency!r} 没有对应的 trim 来源",
                "使用 FLOW 中已定义 trim 行的逻辑 item 名称",
            ))


INPUT_CHECKS = [
    check_char_hygiene,
    check_structure,
    check_types,
    check_cross_ref,
    check_bitfields,
    check_fb_map_mapping,
    check_family_modes,
    check_logical_item_linkage,
]

# Kept for direct rule-level compatibility tests.  The formal generation path
# uses INPUT_CHECKS through ProductCompiler and never invokes the two compiler-
# backed rules below a second time.
ALL_CHECKS = INPUT_CHECKS + [check_flow_recipe, check_persistence_recipe]
