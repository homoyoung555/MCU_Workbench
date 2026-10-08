# 功能项测试族（OPA/COMP/DAC/PVD/ADC/FREQ）的 sweep 表 + IOMUX 拓扑解析。
#
# 背景与设计：见 `.Codex/handoffs/2026-07-23-analog-item-sheet-schema-draft.html`（v0.3）。
# 分工——OPA/COMP/DAC 继续由 IOMUX 提供引脚↔角色拓扑；ADC 的通道、管脚、force、limit
# 收口到独立 ADC sheet（旧母本无 ADC sheet 时兼容 IOMUX）；每个功能 item 的 sweep 表保存
# 测试参数。本模块把这些数据解析成结构化形式，供两平台 writer 与 preflight 共用。
#
# 放仓库根目录（同 fb_map.py，跟 program_gen/、preflight/ 平级）：preflight 明确"不 import
# 生成器"，但要复用本解析逻辑做校验；根目录让两边平级 import，不产生耦合。本模块只吃传入
# 的 openpyxl `wb`、返回纯数据，不 import program_gen、不碰生成/校验流程。
#
# 硬约束（同 fb_map）：老母本没有 IOMUX / sweep 表时，对应解析返回空，调用方按"功能整体
# 跳过"处理，绝不报错——老母本必须照常能跑。
#
# 【搭结构阶段 · 2026-07-23】IOMUX 角色反查（OPA/COMP/DAC）+ 取值/限值记法解析已实现并可
# 用真实 IOMUX 测；sweep 表读取按规范列定义搭好（母本暂无这些 sheet，返回空）。**内部参考
# （Vrefcmp/TS_VIN 等）在 IOMUX 里怎么填、叫什么，待用户给名单**（§8①）——当前按"INT_ 前缀
# 或非标准角色名"识别为内部源、标 is_internal，名单确定后收紧 _INTERNAL_REF 识别即可。
import re

from program_gen.core.input_normalization import worksheet_by_name

IOMUX_SHEET = "IOMUX"
SWEEP_SHEETS = ("OPA", "COMP", "DAC", "PVD", "ADC", "FREQ")

# 每张 sweep 表的规范列（规范 v0.3 §3；实际读取按表头名匹配、缺列不报错由校验层管）
SWEEP_COLUMNS = {
    # OPA：INP0/INP1、INN0/INN1 两套 mux 力值（对上 S100 golden 两趟测量）+ 显式 down/up 限值
    # （非 ±容差）。FOLLOW/PGA 两 INP 都填→两趟；DIFF inp1 空→只 INP0 一趟+灌 INN0。
    "OPA": ("mode", "step", "inp0_force", "inp1_force", "inn0_force", "inn1_force",
            "down_limit", "target", "up_limit"),
    "COMP": ("comp", "mode", "case", "inp", "inp_force", "inn", "inn_force",
             "expect", "down_limit", "up_limit", "step"),
    # DAC：一行一个 mode×code；down/up 支持 FLOW limit 的百分比、±偏移、绝对值三种写法。
    # 理论 target 由 code/FLOW.target×FLOW.Vcc 算出；step 当前保留、不参与生成。
    "DAC": ("mode", "step", "code", "down_limit", "up_limit"),
    # PVD（欠压中断阈值四点法，2026-07-24）：每 case 两行 up/down（上升沿/下降沿阈值），
    # 各带 min/typ/max（datasheet 规格）+ limit（内缩量 guard，逐行独立）+ expect（该沿穿过
    # 后的比较状态 HH/LL）+ step（keil 逐 case 进入码，本产品=case 号）。
    "PVD": ("case", "up/down", "min", "typ", "max", "limit", "expect", "step"),
    # ADC：按 ADC1/ADC2 分组，一行一个 CH；pin 由 ADC+CH 到 IOMUX.ADC 反查。
    # ADC 列允许只在分组首行填写，后续空白继承；force 为激励电压，limit 为码域对称容差。
    "ADC": ("adc", "ch", "step", "force", "limit"),
    # FREQ：CP3 功能频率族。FREQ 列按 FLOW.item 分组并允许空白向下继承；mode 是原
    # FLOW.sub（同时用于派生 SWD 配置图形名），force 可填 PD0:32MHz 或 /；限值复用
    # FLOW calc_limit 的百分比、带符号偏移、绝对值三种写法。
    "FREQ": ("freq", "source", "mul", "div", "step", "down_limit", "up_limit"),
}


# ------------------------------------------------------------------ pin 名归一化
def normalize_pin(raw):
    """IOMUX pin 名（`PA01` / `PC13-TAMPER-WKUP` / `PY00-NRST`）→ pin.dec 短名（`PA1`/`PC13`/
    `PY0`）：去 `-后缀`、端口字母后去前导 0。非 Pxx 格式（内部伪 pin 如 `INT_BUFOUT`）原样返回。
    与 chroma/adc_writer._iomux_short + _normalize_pin 等价，此处独立一份避免 import 生成器。"""
    base = str(raw).split("-")[0].strip()
    m = re.match(r"(P[A-FY])0*(\d+)$", base, re.I)
    return (m.group(1).upper() + m.group(2)) if m else base


# ------------------------------------------------------------------ IOMUX 角色反查
# 角色标签正则（IOMUX 的 OPA/COMP 列单元格值）：
_ROLE_INX_RE = re.compile(r"(OPA|COMP)(\d+)_V(INP|INN)(\d+)$", re.I)  # OPA2_VINP0 / COMP1_VINN0
_ROLE_OUT_RE = re.compile(r"(OPA|COMP)(\d+)_VOUT$", re.I)             # OPA1_VOUT / COMP1_VOUT
_SHARED_INN_RE = re.compile(r"COMP(\d+)_VINN(\d*)$", re.I)          # COMP1234_VINN3（多比较器共用负输入）
_DAC_OUT_RE = re.compile(r"DAC_OUT(\d*)$", re.I)                       # DAC_OUT / DAC_OUT1 / DAC_OUT2

# 内部参考识别（占位）：INT_ 前缀，或 OPA/COMP 列里非上述标准角色格式的具名值。
# 待用户给正式名单后，把明确的内部参考名（Vrefcmp/TS_VIN/...）在此收紧。
_INTERNAL_PREFIX_RE = re.compile(r"^INT[_-]", re.I)


def _iomux_subheader_cols(ws):
    """IOMUX 第 2 行子表头（第 1 行是 analog/test/additional 分组）→ {名(小写): 列号}。"""
    hdr = {}
    for c in range(1, ws.max_column + 1):
        v = ws.cell(2, c).value
        if v is not None:
            hdr[str(v).strip().lower()] = c
    return hdr


def build_iomux_roles(wb):
    """解析 IOMUX 的 OPA/COMP/DAC 列，返回 dict：
      {
        "roles": {(family, inst, kind, idx): pin_short},  # family∈{"OPA","COMP"}, kind∈{"INP","INN","OUT"}
        "shared_inn": {("COMP", comp_inst): pin_short},   # COMP<digits>_VINN 共用负输入，展开到每个 comp 号
        "dac_out": {idx_or_0: pin_short},                 # DAC_OUT→0 / DAC_OUT1→1 / DAC_OUT2→2
        "internal": {name_upper: pin_raw},                # 内部参考伪 pin（占位识别，待名单）
      }
    kind=OUT 时 idx 恒 0。IOMUX 不存在 → 全空。"""
    out = {"roles": {}, "shared_inn": {}, "dac_out": {}, "internal": {}}
    ws = worksheet_by_name(wb, IOMUX_SHEET, required=False)
    if ws is None:
        return out
    hdr = _iomux_subheader_cols(ws)
    opa_col, comp_col, dac_col = hdr.get("opa"), hdr.get("comp"), hdr.get("dac")

    for r in range(3, ws.max_row + 1):
        pin_raw = ws.cell(r, 1).value
        if pin_raw is None or not str(pin_raw).strip():
            continue
        pin_raw = str(pin_raw).strip()
        pin_short = normalize_pin(pin_raw)
        internal = bool(_INTERNAL_PREFIX_RE.match(pin_raw))

        for col in (opa_col, comp_col):
            if col is None:
                continue
            cell = ws.cell(r, col).value
            if cell is None or not str(cell).strip():
                continue
            for part in str(cell).split("/"):
                label = part.strip()
                if not label:
                    continue
                # 共享标签必须先判；否则 COMP1234_VINN3 会被普通角色误读成“第 1234 个比较器”。
                m = _SHARED_INN_RE.fullmatch(label)
                if m and len(m.group(1)) > 1:
                    idx = int(m.group(2) or 0)
                    for d in m.group(1):
                        out["roles"][("COMP", int(d), "INN", idx)] = pin_short
                    continue
                m = _ROLE_INX_RE.fullmatch(label)
                if m:
                    fam, inst, kind, idx = m.group(1).upper(), int(m.group(2)), m.group(3).upper(), int(m.group(4))
                    out["roles"][(fam, inst, kind, idx)] = pin_short
                    continue
                m = _ROLE_OUT_RE.fullmatch(label)
                if m:
                    fam, inst = m.group(1).upper(), int(m.group(2))
                    out["roles"][(fam, inst, "OUT", 0)] = pin_short
                    continue
                m = _SHARED_INN_RE.fullmatch(label)
                if m:
                    idx = int(m.group(2) or 0)
                    for d in m.group(1):
                        out["roles"][("COMP", int(d), "INN", idx)] = pin_short
                    continue
                # 非标准角色格式的具名值 → 当内部参考（占位；待名单收紧）
                out["internal"][label.upper()] = pin_raw

        if dac_col is not None:
            cell = ws.cell(r, dac_col).value
            if cell is not None and str(cell).strip():
                m = _DAC_OUT_RE.match(str(cell).strip())
                if m:
                    idx = int(m.group(1)) if m.group(1) else 0
                    out["dac_out"][idx] = pin_short

        # 内部参考伪 pin（INT_ 前缀）：登记名字（去前缀）→ 便于 sweep 表按名引用、标内部源
        if internal:
            name = re.sub(r"^INT[_-]", "", pin_raw, flags=re.I).strip().upper()
            if name:
                out["internal"].setdefault(name, pin_raw)
    return out


def resolve_pin(roles_index, family, inst, kind, idx):
    """(family, inst, kind, idx) → 真实短 pin 名；查不到抛 KeyError（调用方决定报错文案）。
    kind=INN 且逐比较器 VINN<idx> 查不到时，回退共用负输入（COMP<digits>_VINN）。"""
    key = (family.upper(), int(inst), kind.upper(), int(idx))
    if key in roles_index["roles"]:
        return roles_index["roles"][key]
    if kind.upper() == "INN":
        sk = (family.upper(), int(inst))
        if sk in roles_index["shared_inn"]:
            return roles_index["shared_inn"][sk]
    raise KeyError("IOMUX 无角色 %s%s_V%s%s" % (family.upper(), inst, kind.upper(), idx))


def opa_group_specs(roles_index, real_pins):
    """OPA 三组规格（两平台共用）：[(组名, 出针子集[list], IOMUX全集[list]), ...]，
    组名 OPA_INP0_pins / OPA_INN_pins / OPA_OUT_pins。全集用于注释/参考。

    **出针子集按"可用实例"过滤**（用户裁决 2026-07-23）：一个 OPA 实例只有 **INP0 与 OUT
    都出针** 才算可用——否则该 OPA 的输出没有对应输入激励、量测无意义（如某母本 OPA1 的
    OUT 出了针但 INP0 没出，该 OUT 不能进 OPA_OUT_pins）。各组只取可用实例的脚，保证
    输入组⇄输出组按实例一一对应、同属一个 OPA。INN0 只在可用实例里也出针时才计入。
    real_pins 传本程序实际出针的短名集合（Chroma 读 pin.dec PIN_LIST / S100 读 dc_io_pins）。"""
    insts = sorted(set(inst for (fam, inst, _k, _i) in roles_index["roles"] if fam == "OPA"))
    usable = [inst for inst in insts
              if roles_index["roles"].get(("OPA", inst, "INP", 0)) in real_pins
              and roles_index["roles"].get(("OPA", inst, "OUT", 0)) in real_pins]
    specs = []
    for name, kind, idx in (("OPA_INP0_pins", "INP", 0), ("OPA_INN_pins", "INN", 0),
                            ("OPA_OUT_pins", "OUT", 0)):
        full = role_group_pins(roles_index, "OPA", kind, idx)
        probed = []
        for inst in usable:
            p = roles_index["roles"].get(("OPA", inst, kind, idx))
            if p in real_pins and p not in probed:
                probed.append(p)
        specs.append((name, probed, full))
    return specs


def role_group_pins(roles_index, family, kind, idx):
    """收集所有实例在 (family, kind, idx) 上的引脚，按实例号升序 → [pin_short, ...]。
    用于 OPA 那种"整组 force/测"：如 OPA_INP0 组 = 所有 OPAn 的 VINP0 脚。查无→[]。"""
    fam, kind, idx = family.upper(), kind.upper(), int(idx)
    got = [(inst, pin) for (f, inst, k, i), pin in roles_index["roles"].items()
           if f == fam and k == kind and i == idx]
    return [p for _, p in sorted(got)]


# ------------------------------------------------------------------ 取值 / 限值记法解析
_VOLT_ABS_RE = re.compile(r"^([+-]?\d*\.?\d+)\s*(mV|V)?$", re.I)      # 1.65V / 75mV / 0V / 0 / -0.1
_VOLT_REL_MUL_RE = re.compile(r"^([+-]?\d*\.?\d+)\s*\*?\s*VCC$", re.I)  # 0.5VCC / 0.5*VCC
_VOLT_REL_OFF_RE = re.compile(r"^VCC\s*([+-]\s*\d*\.?\d+)?$", re.I)     # VCC / VCC-0.1 / VCC+0.1


def parse_value(cell):
    """sweep 表里 force/驱动电压取值 → 结构化（不算成数字：VCC 相对值是运行时常量，留给
    writer 按平台格式化）：
      {"kind":"rel_mul","factor":float}     # 0.5VCC        → vcc*factor
      {"kind":"rel_off","offset":float}     # VCC / VCC-0.1 → vcc + offset（VCC 本身 offset=0）
      {"kind":"abs","value":float,"unit":"V"}  # 1.65V/75mV/0V/0 → 统一折算成 V 值
      {"kind":"ref","name":str}             # 具名内部参考（Vrefcmp/TS_VIN…）
      {"kind":"blank"}                       # 空 = 该项不 force
    """
    s = "" if cell is None else str(cell).strip()
    if not s or s == "/":
        return {"kind": "blank"}
    m = _VOLT_REL_MUL_RE.match(s)
    if m:
        return {"kind": "rel_mul", "factor": float(m.group(1))}
    m = _VOLT_REL_OFF_RE.match(s)
    if m:
        off = m.group(1)
        return {"kind": "rel_off", "offset": float(off.replace(" ", "")) if off else 0.0}
    m = _VOLT_ABS_RE.match(s)
    if m:
        val = float(m.group(1))
        unit = (m.group(2) or "V").upper()
        if unit == "MV":
            val, unit = val / 1000.0, "V"
        return {"kind": "abs", "value": round(val, 6), "unit": "V"}
    return {"kind": "ref", "name": s}          # 非数值、非 VCC → 当具名内部参考


_LIM_TOL_RE = re.compile(r"^±\s*(\d*\.?\d+)\s*(mV|V|LSB)?$", re.I)   # ±20mV / ±16LSB / ±0.02
_LIM_RANGE_RE = re.compile(r"^([+-]?\d*\.?\d+)\s*(mV|V)?\s*~\s*([+-]?\d*\.?\d+)\s*(mV|V)?$", re.I)  # 1.5V~2.6V


def parse_limit(cell):
    """卡控 → 结构化：
      {"kind":"tol","value":float,"unit":"V"|"LSB"}   # ±20mV / ±16LSB（对称容差，围绕 target）
      {"kind":"range","low":float,"high":float}       # 1.5V~2.6V（绝对上下限）
      {"kind":"blank"}
    tol 的 V/mV 统一折算成 V；LSB 保留（ADC 码域）。"""
    s = "" if cell is None else str(cell).strip()
    if not s or s == "/":
        return {"kind": "blank"}
    m = _LIM_TOL_RE.match(s)
    if m:
        val = float(m.group(1))
        unit = (m.group(2) or "V").upper()
        if unit == "MV":
            val, unit = val / 1000.0, "V"
        return {"kind": "tol", "value": round(val, 6), "unit": unit}
    m = _LIM_RANGE_RE.match(s)
    if m:
        def _v(x, u):
            x = float(x)
            return x / 1000.0 if (u or "").upper() == "MV" else x
        return {"kind": "range", "low": round(_v(m.group(1), m.group(2)), 6),
                "high": round(_v(m.group(3), m.group(4)), 6)}
    return {"kind": "range", "low": None, "high": None, "raw": s}   # 未识别，保留原文供校验报错


# ------------------------------------------------------------------ FLOW.step 模板切分
def split_flow_step_template(flow_step):
    """FLOW.step 模板按 `X` 标记切分（规范 §5.2）→ (prefix, suffix)：
      prefix = X 之前的 token 串（上电后发一次的共用段）
      suffix = X 之后的 token 串（逐元素循环之后发一次，通常空）
    逐元素的 sheet.step 填在 X 位置（循环体内）。容错（防静默 bug）：
      无 X → prefix=整串、suffix=""（X 视为在末尾）；空串/"/" → ("","")。
    按 '-' 分隔的 token 定位 X，不匹配 token 内部的字母 X。"""
    s = "" if flow_step is None else str(flow_step).strip()
    if not s or s == "/":
        return "", ""
    toks = s.split("-")
    if "X" in toks:
        i = toks.index("X")
        return "-".join(toks[:i]), "-".join(toks[i + 1:])
    return s, ""          # 无 X → 全 prefix，X 隐含在末尾


# ------------------------------------------------------------------ sweep 表读取
def read_sweep_sheet(wb, sheet, required=False):
    """读一张 sweep 表（OPA/COMP/DAC/PVD/ADC）→ [ {列名: 单元格值(str/None), "_row": 行号}, ... ]。
    表头在第 1 行；数据行从第 2 行起，整行空则跳过。表不存在返回 []（老母本照常跑）。
    只做"按表头名取值"的机械读取，取值/限值的记法解析由调用方按需调 parse_value/parse_limit，
    引脚反查由 resolve_pin——本函数不解释语义，保持薄。"""
    ws = worksheet_by_name(wb, sheet, required=False)
    if ws is None and str(sheet).strip().upper() == "COMP":
        ws = worksheet_by_name(wb, "CMP", required=False)  # 兼容 2026-07-23 草案名
    if ws is None:
        if required:
            raise ValueError(f"FLOW 已引用 {sheet} 族，但母本缺少 {sheet} sheet")
        return []
    header = {}
    for c in range(1, ws.max_column + 1):
        v = ws.cell(1, c).value
        if v is not None and str(v).strip():
            header[str(v).strip().lower()] = c
    rows = []
    for r in range(2, ws.max_row + 1):
        rec = {}
        any_val = False
        for name, c in header.items():
            v = ws.cell(r, c).value
            if v is not None and str(v).strip() != "":
                any_val = True
            rec[name] = None if v is None else str(v).strip()
        if any_val:
            rec["_row"] = r
            rows.append(rec)
    if required and not rows:
        raise ValueError(f"FLOW 已引用 {sheet} 族，但 {sheet} sheet 没有有效数据行")
    return rows


# ------------------------------------------------------------------ COMP 比较器族
_COMP_NAME_RE = re.compile(r"^COMP(\d+)$", re.I)
_COMP_ROLE_RE = re.compile(r"^COMP(\d+)_V(INP|INN)(\d+)$", re.I)
_COMP_MODES = {"NORM", "WINDOW12", "WINDOW34", "OPACMP"}


def _comp_source(roles, comp_num, kind, raw, row):
    """COMP sheet 的 inp/inn 单元格 → {internal, role, pin}。

    常规写 mux 下标（0/1/2...）；特殊 Window 拓扑可写完整角色 COMP2_VINP1；
    内部源写 INT:DAC1 / INT:DAC2 / INT:TS / INT:VREF，不参与 ATE force。
    """
    text = "" if raw is None else str(raw).strip()
    if not text or text == "/":
        raise ValueError(f"COMP sheet 第 {row} 行 {kind.lower()} 不能为空")
    if text.upper().startswith("INT:"):
        name = text.split(":", 1)[1].strip().upper()
        if not name:
            raise ValueError(f"COMP sheet 第 {row} 行内部源 {text!r} 缺少名称")
        return {"internal": True, "role": "INT:" + name, "pin": None}
    if text.isdigit():
        inst, role_kind, idx = comp_num, kind, int(text)
        role = f"COMP{inst}_V{role_kind}{idx}"
    else:
        match = _COMP_ROLE_RE.fullmatch(text)
        if not match or match.group(2).upper() != kind:
            raise ValueError(
                f"COMP sheet 第 {row} 行 {kind.lower()}={text!r}；"
                f"应写 mux 下标、完整 COMPn_V{kind}x 或 INT:<source>"
            )
        inst, role_kind, idx = int(match.group(1)), match.group(2).upper(), int(match.group(3))
        role = f"COMP{inst}_V{role_kind}{idx}"
    try:
        pin = resolve_pin(roles, "COMP", inst, role_kind, idx)
    except KeyError as exc:
        raise ValueError(f"COMP sheet 第 {row} 行的 {role} 在 IOMUX 找不到 pin") from exc
    return {"internal": str(pin).upper().startswith("INT_"), "role": role, "pin": pin}


def comp_cases(wb, required=False):
    """COMP sheet → 两平台共用的规范 case 列表。

    COMP/mode 可向下继承；case/输入/force/expect/step 必须逐测量点显式填写。
    同一 comp+mode+case 可重复，以表达同一配置下不同 force/expect 测量点。
    """
    rows = read_sweep_sheet(wb, "COMP", required=required)
    if not rows:
        return []
    roles = build_iomux_roles(wb)
    current_comp = current_mode = None
    cases, config_signature = [], {}
    seen_rows = set()
    for rec in rows:
        row = rec["_row"]
        raw_comp = str(rec.get("comp") or "").strip()
        raw_mode = str(rec.get("mode") or "").strip()
        if raw_comp:
            match = _COMP_NAME_RE.fullmatch(raw_comp)
            if not match:
                raise ValueError(f"COMP sheet 第 {row} 行 COMP={raw_comp!r}，应写 COMP1/COMP2...")
            current_comp = int(match.group(1))
        if raw_mode:
            current_mode = raw_mode.upper()
            if current_mode not in _COMP_MODES:
                raise ValueError(
                    f"COMP sheet 第 {row} 行 mode={raw_mode!r}；支持 " + ", ".join(sorted(_COMP_MODES))
                )
        if current_comp is None or current_mode is None:
            raise ValueError(f"COMP sheet 第 {row} 行 COMP/mode 为空，且上方没有可继承分组")

        case = str(rec.get("case") or "").strip()
        expect = str(rec.get("expect") or "").strip().upper()
        step = str(rec.get("step") or "").strip()
        if not case:
            raise ValueError(f"COMP sheet 第 {row} 行 case 不能为空")
        if expect not in {"H", "L"}:
            raise ValueError(f"COMP sheet 第 {row} 行 expect={expect!r}，只支持 H/L")
        if not step or step == "/":
            raise ValueError(f"COMP sheet 第 {row} 行 step 不能为空（SWD 会忽略，Keil 使用）")

        inp = _comp_source(roles, current_comp, "INP", rec.get("inp"), row)
        inn = _comp_source(roles, current_comp, "INN", rec.get("inn"), row)
        inp_force = str(rec.get("inp_force") or "").strip()
        inn_force = str(rec.get("inn_force") or "").strip()
        for label, source, force in (("inp", inp, inp_force), ("inn", inn, inn_force)):
            blank = not force or force == "/"
            if blank:
                detail = "内部源的理论参考电压" if source["internal"] else "外部 pin 的激励电压"
                raise ValueError(f"COMP sheet 第 {row} 行 {label} 是{'内部源' if source['internal'] else '外部 pin'}，"
                                 f"{label}_force 必须填写{detail}")
            if not blank and parse_value(force)["kind"] == "ref":
                raise ValueError(f"COMP sheet 第 {row} 行 {label}_force={force!r} 不是支持的电压写法")

        config_key = (current_comp, current_mode, case.casefold())
        signature = (inp["role"], inn["role"], step)
        old = config_signature.setdefault(config_key, signature)
        if old != signature:
            raise ValueError(
                f"COMP sheet 第 {row} 行与同一配置 COMP{current_comp}/{current_mode}/{case} 的"
                " inp/inn/step 不一致"
            )
        duplicate = (config_key, inp_force, inn_force, expect,
                     str(rec.get("down_limit") or "").strip(), str(rec.get("up_limit") or "").strip())
        if duplicate in seen_rows:
            raise ValueError(f"COMP sheet 第 {row} 行与上方测量点完全重复")
        seen_rows.add(duplicate)
        try:
            out_pin = resolve_pin(roles, "COMP", current_comp, "OUT", 0)
        except KeyError as exc:
            raise ValueError(f"COMP{current_comp}_VOUT 在 IOMUX 找不到 pin") from exc
        cases.append({
            "comp": current_comp, "mode": current_mode, "case": case, "step": step,
            "inp": inp, "inp_force": inp_force, "inn": inn, "inn_force": inn_force,
            "out_pin": out_pin, "expect": expect,
            "down_limit": str(rec.get("down_limit") or "").strip(),
            "up_limit": str(rec.get("up_limit") or "").strip(), "_row": row,
        })
    if required and not cases:
        raise ValueError("FLOW 已引用 COMP 族，但 COMP sheet 没有可生成的有效 case")
    return cases


# ------------------------------------------------------------------ FREQ 功能频率族
_FREQ_UNITS = {"HZ": "Hz", "KHZ": "KHz", "MHZ": "MHz"}
_FREQ_UNIT_HZ = {"": 1.0, "K": 1e3, "M": 1e6, "G": 1e9}
_FREQ_SOURCE_RE = re.compile(
    r"^(?P<family>[A-Za-z][A-Za-z0-9]*)_(?P<number>\d+(?:P\d+)?)(?P<scale>[KMG]?)(?:HZ)?$",
    re.I,
)
_FREQ_EXTERNAL_IOMUX_ROLE = {
    "HSE": "OSC_IN",
    "LSE": "OSC32_IN",
}


def _freq_compact_number(value):
    return ("%g" % float(value)).upper()


def _freq_factor(value, label, row):
    text = "" if value is None else str(value).strip()
    if text == "/":
        return 1.0
    try:
        result = float(text)
    except (TypeError, ValueError):
        raise ValueError(f"FREQ sheet 第 {row} 行 {label}={value!r} 不是数值或 /") from None
    if result <= 0:
        raise ValueError(f"FREQ sheet 第 {row} 行 {label} 必须大于 0")
    return result


def _freq_output_value(target_hz):
    """Hz 值转为便于 ATE 阅读的工程单位，数值保持在常用量级。"""
    if target_hz >= 1e6:
        return round(target_hz / 1e6, 12), "MHz"
    if target_hz >= 1e3:
        return round(target_hz / 1e3, 12), "KHz"
    return round(target_hz, 12), "Hz"


def _freq_role_key(value):
    """IOMUX 时钟角色归一化：忽略大小写及常见分隔符，但不做子串相似匹配。"""
    return re.sub(r"[^A-Za-z0-9]+", "", str(value)).upper()


def _freq_iomux_pin(wb, role):
    """按 IOMUX 时钟角色反查 pin；OSC_IN/OSCIN/OSC-IN/OSC IN 等价。"""
    ws = worksheet_by_name(wb, IOMUX_SHEET, required=False)
    if ws is None:
        raise ValueError(f"FREQ source 需要 IOMUX 的 {role} 映射，但母本没有 IOMUX sheet")
    matches = []
    wanted = _freq_role_key(role)
    for r in range(3, ws.max_row + 1):
        pin_raw = ws.cell(r, 1).value
        if pin_raw is None or not str(pin_raw).strip():
            continue
        for c in range(2, ws.max_column + 1):
            raw = ws.cell(r, c).value
            if raw is None:
                continue
            roles = [_freq_role_key(part) for part in str(raw).split("/")]
            if wanted in roles:
                matches.append(normalize_pin(pin_raw))
                break
    matches = list(dict.fromkeys(matches))
    if not matches:
        raise ValueError(f"FREQ source 需要 IOMUX 的 {role} 映射，但没有找到对应 pin")
    if len(matches) > 1:
        raise ValueError(f"IOMUX 的 {role} 同时映射到多个 pin: {', '.join(matches)}")
    return matches[0]


def _freq_new_case(wb, group, values, row):
    source = str(values["source"]).strip().upper()
    match = _FREQ_SOURCE_RE.fullmatch(source)
    if not match:
        raise ValueError(
            f"FREQ sheet 第 {row} 行 source={values['source']!r} 无法解析；"
            "应类似 HSI_8M 或 HSE_32M"
        )
    family = match.group("family").upper()
    source_number = match.group("number").upper()
    source_value = float(source_number.replace("P", "."))
    scale = match.group("scale").upper()
    source_hz = source_value * _FREQ_UNIT_HZ[scale]
    mul = _freq_factor(values["mul"], "mul", row)
    div = _freq_factor(values["div"], "div", row)
    target, unit = _freq_output_value(source_hz * mul / div)

    if group.casefold().startswith("pll"):
        pattern = "PLL_" + family + source_number.replace("P", "")
        mode = pattern + "_PLLX" + _freq_compact_number(mul)
    elif family in _FREQ_EXTERNAL_IOMUX_ROLE:
        pattern = family
        mode = family + "_Check"
    else:
        pattern = source
        mode = source + "_Check"

    force = "/"
    role = _FREQ_EXTERNAL_IOMUX_ROLE.get(family)
    if role:
        pin = _freq_iomux_pin(wb, role)
        source_unit = {"": "Hz", "K": "KHz", "M": "MHz", "G": "GHz"}[scale]
        force = f"{pin}:{_freq_compact_number(source_value)}{source_unit}"

    return {
        "freq": group,
        "source": source,
        "mul": mul,
        "div": div,
        "step": str(values.get("step") or "/").strip(),
        "mode": mode,
        "pattern": pattern,
        "force": force,
        "target": target,
        "down_limit": str(values["down_limit"]).strip(),
        "up_limit": str(values["up_limit"]).strip(),
        "unit": unit,
        "_row": row,
    }


def freq_cases(wb, item=None):
    """独立 FREQ sheet → 频率测试档位。

    标准表头：FREQ/mode/force/target/down_limit/up_limit/unit。FREQ 列按测试族
    （FLOW.item）分组，分组首行填写，后续空白向下继承。item 传入时只返回同名组，
    大小写不敏感；表不存在返回 []，保证旧母本继续走 FLOW 多行路径。
    """
    ws = worksheet_by_name(wb, "FREQ", required=False)
    if ws is None:
        return []
    header = {}
    for c in range(1, ws.max_column + 1):
        value = ws.cell(1, c).value
        if value is not None and str(value).strip():
            header[str(value).strip().lower()] = c
    new_names = SWEEP_COLUMNS["FREQ"]
    new_names_without_step = tuple(name for name in new_names if name != "step")
    legacy_names = ("freq", "mode", "force", "target", "down_limit", "up_limit", "unit")
    new_schema = all(name in header for name in new_names_without_step)
    legacy_schema = all(name in header for name in legacy_names)
    if not new_schema and not legacy_schema:
        expected = new_names if "source" in header else legacy_names
        missing = [name for name in expected if name not in header]
        raise ValueError(
            "FREQ sheet 缺少列: " + ", ".join(missing)
            + "；新表头为 FREQ/source/mul/div/down_limit/up_limit"
        )
    names = tuple(name for name in new_names if name in header) if new_schema else legacy_names
    columns = {name: header[name] for name in names}

    current_group = None
    seen = set()
    rows = []
    for r in range(2, ws.max_row + 1):
        values = {name: ws.cell(r, col).value for name, col in columns.items()}
        if new_schema and "step" not in values:
            values["step"] = "/"
        if not any(v is not None and str(v).strip() for v in values.values()):
            continue
        group_cell = values["freq"]
        if group_cell is not None and str(group_cell).strip():
            current_group = str(group_cell).strip()
        if not current_group:
            raise ValueError(f"FREQ sheet 第 {r} 行缺少 FREQ 分组名，且上方没有可继承的分组")

        required = (
            ("source", "mul", "div", "down_limit", "up_limit")
            if new_schema else
            ("mode", "target", "down_limit", "up_limit", "unit")
        )
        missing_values = [
            name for name in required
            if values[name] is None or not str(values[name]).strip()
        ]
        if missing_values:
            raise ValueError(
                f"FREQ sheet 第 {r} 行缺少值: " + ", ".join(missing_values)
            )

        if new_schema:
            row_data = _freq_new_case(wb, current_group, values, r)
            duplicate_label = row_data["source"]
            key = (
                current_group.casefold(),
                row_data["source"].casefold(),
                row_data["mul"],
                row_data["div"],
            )
        else:
            mode = str(values["mode"]).strip()
            duplicate_label = mode
            key = (current_group.casefold(), mode.casefold())
        if key in seen:
            raise ValueError(
                f"FREQ sheet 第 {r} 行 {current_group}/{duplicate_label} 重复"
            )
        seen.add(key)
        if new_schema:
            rows.append(row_data)
            continue
        try:
            target = float(values["target"])
        except (TypeError, ValueError):
            raise ValueError(
                f"FREQ sheet 第 {r} 行 target={values['target']!r} 不是数值"
            ) from None
        if target <= 0:
            raise ValueError(f"FREQ sheet 第 {r} 行 target 必须大于 0")
        unit_raw = str(values["unit"]).strip().upper()
        if unit_raw not in _FREQ_UNITS:
            raise ValueError(
                f"FREQ sheet 第 {r} 行 unit={values['unit']!r}，只支持 Hz/KHz/MHz"
            )
        force = "/" if values["force"] is None or not str(values["force"]).strip() else str(values["force"]).strip()
        rows.append({
            "freq": current_group,
            "mode": mode,
            "pattern": "_".join(mode.split("_")[:-1]) if "_" in mode else mode,
            "step": "/",
            "force": force,
            "target": target,
            "down_limit": str(values["down_limit"]).strip(),
            "up_limit": str(values["up_limit"]).strip(),
            "unit": _FREQ_UNITS[unit_raw],
            "_row": r,
        })

    if item is None:
        return rows
    wanted = str(item).strip().casefold()
    return [row for row in rows if row["freq"].casefold() == wanted]


# ------------------------------------------------------------------ ADC 通道表
_ADC_CH_RE = re.compile(r"ADC(12|\d+)_IN(\d+)$", re.I)


def _adc_iomux_pin_index(wb):
    """IOMUX.ADC → {(adc_num, ch): pin_raw}；ADC12_INx 同时展开给 ADC1/ADC2。"""
    ws = worksheet_by_name(wb, IOMUX_SHEET, required=False)
    if ws is None:
        raise ValueError("ADC sheet 需要 IOMUX sheet 的 ADC 映射列来反查 pin")
    adc_col = _iomux_subheader_cols(ws).get("adc")
    if adc_col is None:
        raise ValueError("ADC sheet 需要 IOMUX 第 2 行保留 ADC 映射列")
    index = {}
    for r in range(3, ws.max_row + 1):
        raw = ws.cell(r, adc_col).value
        if raw is None or not str(raw).strip():
            continue
        pin_raw = str(ws.cell(r, 1).value or "").strip()
        for part in str(raw).split("/"):
            match = _ADC_CH_RE.fullmatch(part.strip())
            if not match:
                continue
            adc_nums = (1, 2) if match.group(1) == "12" else (int(match.group(1)),)
            channel = int(match.group(2))
            for adc_num in adc_nums:
                key = (adc_num, channel)
                if key in index:
                    raise ValueError(
                        f"IOMUX ADC 映射重复: ADC{adc_num} CH{channel} "
                        f"同时对应 {index[key]!r} 和 {pin_raw!r}"
                    )
                index[key] = pin_raw
    return index


def _adc_sheet_rows(wb):
    """独立 ADC sheet（ADC/CH/force/limit）→ 带反查 pin 的旧 writer 标准记录。"""
    ws = worksheet_by_name(wb, "ADC")
    header = {}
    for c in range(1, ws.max_column + 1):
        value = ws.cell(1, c).value
        if value is not None and str(value).strip():
            header[str(value).strip().lower()] = c
    ch_col = next(
        (header[name] for name in ("ch", "channel", "chanel") if name in header),
        None,
    )
    columns = {
        "adc": header.get("adc"),
        "ch": ch_col,
        "force": header.get("force"),
        "limit": header.get("limit"),
    }
    missing = [name.upper() if name == "ch" else name for name, col in columns.items() if col is None]
    if missing:
        raise ValueError(
            "ADC sheet 缺少列: " + ", ".join(missing)
            + "；标准表头为 ADC/CH/force/limit"
        )

    pin_index = _adc_iomux_pin_index(wb)
    rows = []
    current_adc = None
    seen_channels = set()
    force_by_pin = {}
    for r in range(2, ws.max_row + 1):
        adc_cell = ws.cell(r, columns["adc"]).value
        ch_cell = ws.cell(r, columns["ch"]).value
        force_cell = ws.cell(r, columns["force"]).value
        limit_cell = ws.cell(r, columns["limit"]).value
        values = (adc_cell, ch_cell, force_cell, limit_cell)
        if not any(value is not None and str(value).strip() for value in values):
            continue
        if adc_cell is not None and str(adc_cell).strip():
            match = re.fullmatch(r"ADC(\d+)", str(adc_cell).strip(), re.I)
            if not match:
                raise ValueError(f"ADC sheet 第 {r} 行 ADC={adc_cell!r}，应写 ADC1/ADC2")
            current_adc = int(match.group(1))
        if current_adc is None:
            raise ValueError(f"ADC sheet 第 {r} 行 ADC 为空，且上方没有可继承的 ADC 分组")

        missing_values = [
            name for name, value in (("CH", ch_cell), ("force", force_cell), ("limit", limit_cell))
            if value is None or not str(value).strip()
        ]
        if missing_values:
            raise ValueError(f"ADC sheet 第 {r} 行缺少值: {', '.join(missing_values)}")
        ch_text = str(ch_cell).strip()
        if not re.fullmatch(r"\d+", ch_text):
            raise ValueError(f"ADC sheet 第 {r} 行 CH={ch_cell!r}，应为非负整数")
        channel = int(ch_text)
        key = (current_adc, channel)
        if key in seen_channels:
            raise ValueError(f"ADC sheet 第 {r} 行重复配置 ADC{current_adc} CH{channel}")
        seen_channels.add(key)
        pin_raw = pin_index.get(key)
        if pin_raw is None:
            raise ValueError(
                f"ADC{current_adc} CH{channel} 在 IOMUX ADC 列找不到对应 pin"
            )

        force_num = float(str(force_cell).strip())
        force_key = (current_adc, normalize_pin(pin_raw).upper())
        previous_force = force_by_pin.get(force_key)
        if previous_force is not None and abs(previous_force - force_num) > 1e-12:
            raise ValueError(
                f"ADC{current_adc} 的 {pin_raw} 被多个 CH 共用，但 force 不一致: "
                f"{previous_force:g} 与 {force_num:g}"
            )
        force_by_pin[force_key] = force_num
        rows.append({
            "pin": pin_raw,
            "adc": f"ADC{current_adc}_IN{channel}",
            "force": force_cell,
            "limit": limit_cell,
            "_row": r,
            "_source": "ADC",
        })
    return rows


def _legacy_iomux_adc_rows(wb):
    """旧母本 IOMUX 的 ADC/ADC FORCE/ADC LIMIT 三列 → 标准记录。"""
    ws = worksheet_by_name(wb, IOMUX_SHEET, required=False)
    if ws is None:
        return []
    header = _iomux_subheader_cols(ws)
    columns = {
        "pin": 1,
        "adc": header.get("adc"),
        "force": header.get("adc force"),
        "limit": header.get("adc limit"),
    }
    if any(col is None for col in columns.values()):
        return []
    rows = []
    for r in range(3, ws.max_row + 1):
        adc = ws.cell(r, columns["adc"]).value
        if adc is None or not str(adc).strip():
            continue
        rows.append({
            name: ws.cell(r, col).value for name, col in columns.items()
        } | {"_row": r, "_source": "IOMUX"})
    return rows


def adc_source_rows(wb):
    """ADC 通道数据入口：有独立 ADC sheet 时按 ADC+CH 反查 IOMUX pin，否则兼容旧 IOMUX。"""
    return _adc_sheet_rows(wb) if worksheet_by_name(wb, "ADC", required=False) else _legacy_iomux_adc_rows(wb)


def adc_step(wb, adc_num):
    """Return the per-ADC Keil step from the independent ADC sheet.

    The value may be filled only once in an ADC group; blank rows inherit it.
    Old ADC sheets without a step column remain valid for SWD generation.
    """
    ws = worksheet_by_name(wb, "ADC", required=False)
    if ws is None:
        return ""
    header = {
        str(ws.cell(1, c).value).strip().lower(): c
        for c in range(1, ws.max_column + 1)
        if ws.cell(1, c).value is not None and str(ws.cell(1, c).value).strip()
    }
    adc_col = header.get("adc")
    step_col = header.get("step")
    if adc_col is None or step_col is None:
        return ""
    current_adc = None
    found = []
    for r in range(2, ws.max_row + 1):
        raw_adc = ws.cell(r, adc_col).value
        if raw_adc is not None and str(raw_adc).strip():
            match = re.fullmatch(r"ADC(\d+)", str(raw_adc).strip(), re.I)
            if not match:
                continue
            current_adc = int(match.group(1))
        if current_adc != int(adc_num):
            continue
        raw_step = ws.cell(r, step_col).value
        if raw_step is not None and str(raw_step).strip() and str(raw_step).strip() != "/":
            found.append((r, str(raw_step).strip()))
    if len(found) > 1:
        raise ValueError(
            f"ADC{adc_num} 的 step 只能在分组首行填写一次，实际出现在 "
            + ", ".join(str(row) for row, _ in found)
        )
    return found[0][1] if found else ""


# ------------------------------------------------------------------ PVD 四点序列
def _pvd_num(cell):
    """PVD 表数值单元格 → float；'/'/空/非数值 → None。"""
    v = parse_value(cell)
    return v["value"] if v["kind"] == "abs" else None


def _opp_state(state):
    """比较状态取反（H<->L 逐字符）：HH<->LL、HL<->LH。PVD 四点里"未变"那两点的期望
    = 对应沿"已变"期望的反状态（起点/穿越后互为反态）。"""
    return "".join("L" if c == "H" else "H" for c in state.upper())


def _pvd_row_is_grey(ws, excel_row):
    """PVD 表某 Excel 行是否灰格——沿用 FLOW `state.flow_row_flag` 约定（主题灰
    theme=0 且 tint=-0.5 = 注释掉/不测，用户裁决 2026-07-24"采用 FLOW 逻辑"）。
    检查 case 列(A)单元格填色。"""
    fg = ws.cell(excel_row, 1).fill.fgColor
    return fg.type == "theme" and fg.theme == 0 and abs((fg.tint or 0) - (-0.5)) < 1e-6


def pvd_cases(wb, required=False):
    """PVD 表 → 每个有效 case 的四点电压/期望序列（两平台共用）。返回
      [ {"case": str, "step": str, "points": [(volt_str, expect_lower), x4]}, ... ]，
    按 case 升序。无 PVD 表 / 全跳过 → []（老母本照常跑）。

    每 case 两行（up=上升沿阈值 / down=下降沿阈值），各带 min/max/limit/expect。四点各用
    自己那一行的 limit（"内缩量"guard，逐行独立——上升/下降可不同），按"高压起点 → 降 →
    降 → 升 → 升"单调顺序（迟滞让 flag 有记忆，必须连续单调走）：
      P1 = down.max - down.limit → 未变，expect = 反(down.expect)
      P2 = down.min + down.limit → 已变，expect = down.expect
      P3 = up.min   + up.limit   → 未变，expect = 反(up.expect)
      P4 = up.max   - up.limit   → 已变，expect = up.expect
    极性（HH/LL 谁代表告警）由母本 expect 列决定，不写死——PVD（欠压中断，固件把 PVDO
    镜像到比较管脚）与 BOR（欠压复位）极性相反（用户裁决 2026-07-24）。跳过规则：整 case
    缺阈值数据（如本产品 case0 全 '/'）或灰格（FLOW 约定）→ 不测。"""
    rows = read_sweep_sheet(wb, "PVD", required=required)
    if not rows:
        return []
    ws = worksheet_by_name(wb, "PVD")
    by_case = {}
    for r in rows:
        key = str(r.get("case") or "").strip()
        by_case.setdefault(key, {})[str(r.get("up/down") or "").strip().lower()] = r

    def _ck(k):
        try:
            return (0, float(k))
        except ValueError:
            return (1, k)

    cases = []
    for key in sorted(by_case, key=_ck):
        pair = by_case[key]
        up, down = pair.get("up"), pair.get("down")
        if not up or not down:
            continue
        if _pvd_row_is_grey(ws, up["_row"]) or _pvd_row_is_grey(ws, down["_row"]):
            continue
        d_min, d_max, d_g = _pvd_num(down.get("min")), _pvd_num(down.get("max")), _pvd_num(down.get("limit"))
        u_min, u_max, u_g = _pvd_num(up.get("min")), _pvd_num(up.get("max")), _pvd_num(up.get("limit"))
        d_exp = str(down.get("expect") or "").strip().upper()
        u_exp = str(up.get("expect") or "").strip().upper()
        if None in (d_min, d_max, d_g, u_min, u_max, u_g) or not d_exp or not u_exp:
            continue          # 缺阈值（case0 全 '/'）→ 跳过
        pts = [
            (d_max - d_g, _opp_state(d_exp)),
            (d_min + d_g, d_exp),
            (u_min + u_g, _opp_state(u_exp)),
            (u_max - u_g, u_exp),
        ]
        cases.append({
            "case": key,
            "step": str(down.get("step") or up.get("step") or "").strip(),
            "points": [("%g" % round(v, 4), st.lower()) for v, st in pts],
        })
    if required and not cases:
        raise ValueError("FLOW 已引用 PVD 族，但 PVD sheet 没有可生成的有效 case")
    return cases


def pvd_compare_states(wb):
    """PVD 四点用到的比较状态集合（大写，如 {"HH","LL"}），供 compare pattern 生成。"""
    return sorted({st.upper() for c in pvd_cases(wb) for _, st in c["points"]})


# ------------------------------------------------------------------ DAC code 扫描
def dac_pins(roles_index, real_pins):
    """DAC 输出脚：IOMUX `DAC` 列全部 `DAC_OUT`/`DAC_OUT1`/`DAC_OUT2` 脚 ∩ 本程序实际出针脚
    （用户裁决 2026-07-24：同 OPA 可用实例过滤，须确认 pin 在 pinmap 出针，否则量测无意义），
    按实例号(0/1/2)升序 → [pin_short, ...]。real_pins 传本程序出针短名集合（Chroma 读 pin.dec
    PIN_LIST / S100 读 dc_io_pins）。"""
    return [p for _idx, p in sorted(roles_index["dac_out"].items()) if p in real_pins]


def _dac_code_token(cell, excel_row):
    """DAC code → 无 0x 前缀的大写十六进制 token，供 Pattern 名与限值计算共用。"""
    token = str(cell or "").strip().upper()
    if token.startswith("0X"):
        token = token[2:]
    if not token or not re.fullmatch(r"[0-9A-F]+", token):
        raise ValueError(f"DAC sheet 第 {excel_row} 行 code={cell!r} 不是十六进制码")
    return token


def dac_cases(wb, required=False):
    """DAC 表 → 逐 mode 的 code 序列（两平台共用）。返回
      [ {"mode": str, "codes": [(code, step, down, up), ...]}, ... ]，mode 按母本首次出现序、
    codes 按母本行序。code 接受 `001`/`0x001`，返回时统一为 `001`，避免 0x 混入 Pattern 名。
    down/up 保留母本字面串，writer 再按 FLOW limit 三种写法计算。空/缺表 → []。"""
    rows = read_sweep_sheet(wb, "DAC", required=required)
    if not rows:
        return []
    order, by_mode = [], {}
    for r in rows:
        mode = str(r.get("mode") or "").strip()
        raw_code = str(r.get("code") or "").strip()
        if not mode or not raw_code or mode == "/" or raw_code == "/":
            continue
        code = _dac_code_token(raw_code, r["_row"])
        step = str(r.get("step") or "/").strip()
        dn = str(r.get("down_limit") or "").strip()
        up = str(r.get("up_limit") or "").strip()
        if mode not in by_mode:
            by_mode[mode] = []
            order.append(mode)
        by_mode[mode].append((code, step, dn, up))
    cases = [{"mode": m, "codes": by_mode[m]} for m in order]
    if required and not cases:
        raise ValueError("FLOW 已引用 DAC 族，但 DAC sheet 没有可生成的 mode/code")
    return cases
