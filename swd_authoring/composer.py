"""Composer engine — Directive list -> ordered, sourced pattern rows.

Pure and deterministic: every value comes from EncodingDB, every row carries
its DB provenance. No hardware, no LLM, no network.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .encoding import EncodingDB

# ---- ordering phases (pattern.xlsx summary col A written rules) --------------
#   "时钟配置必须在最前面" / "GPIO MODE 选择必须在最后配置"
# Clock bring-up is sequenced finely so a PLL chain orders correctly:
# osc on -> osc ready -> PLL config -> PLL on -> PLL ready -> clock mux.
PHASE_CLK_ENABLE = 0     # 外设/GPIO 时钟使能(xxxENR)
PHASE_OSC_ON = 1         # 振荡器开启(RCC.CR: HSION/HSEON/LSION)
PHASE_OSC_READY = 2      # 振荡器就绪校验(C_H on HSIRDY/HSERDY...)
PHASE_PLL_CONFIG = 3     # PLL 配置(RCC.PLLCFGR*: 源/倍频)— 必须先于 PLLON
PHASE_PLL_ON = 4         # PLL 开启(RCC.CR: PLLON)
PHASE_PLL_READY = 5      # PLL 就绪校验(C_H on PLLRDY)
PHASE_CLK_MUX = 6        # 系统时钟选择/分频/MCO(RCC.CFGR*)
PHASE_PERIPH = 7         # 外设功能寄存器(DAC/OPA/ADC ...)
PHASE_GPIO = 8           # GPIO 非 MODE 配置(AFR/OTYPER/OSPEEDR/PUPDR)
PHASE_GPIO_MODE = 9      # GPIO MODER(规则:最后)
PHASE_ENABLE = 10        # 外设功能使能位(config-then-enable:配置全写完才使能,见 enable_fields)

_PIN = re.compile(r"^P([A-Z])(\d{1,2})$", re.IGNORECASE)


@dataclass
class Directive:
    """One declarative configuration intent. `kind` selects the resolver."""
    kind: str                       # see Composer._RESOLVERS
    periph: str = ""                # instance for clk_enable (GPIOA, DAC...)
    peri: str = ""                  # CMSIS type for field ops (RCC, GPIO...)
    instance: str = ""              # instance for multi-instance field ops (COMP2, OPA3...)
    reg: str = ""
    field: str = ""
    symbol: str = ""                # L1 symbol (encode)
    value: Optional[int] = None     # explicit in-field value (sem-only fields)
    pin: str = ""                   # PA4 / PA04
    func: str = ""                  # iomux function (MCO2, SPI1_NSS...)
    speed: str = "GPIO_SPEED_FREQ_VERY_HIGH"
    pull: str = "GPIO_NOPULL"
    mode: str = "GPIO_MODE_AF_PP"
    us: int = 0
    note: str = ""
    phase: Optional[int] = None     # override inferred phase


@dataclass
class ComposeRequest:
    name: str
    directives: list[Directive] = field(default_factory=list)
    chip: str = "py32f420"


@dataclass
class PatternRow:
    type: str                       # W / C_H / C_L / us / ms
    addr: Optional[int]
    data: Optional[int]
    desc: str
    sources: list[str] = field(default_factory=list)
    phase: int = PHASE_PERIPH
    mask: Optional[int] = None       # 真正写入的配置位(不含 reset 补位);回读只比这些位

    @property
    def addr_hex(self) -> str:
        return "" if self.addr is None else f"0x{self.addr:08X}"

    @property
    def data_hex(self) -> str:
        return "" if self.data is None else f"0x{self.data:08X}"


@dataclass
class ComposeResult:
    name: str
    rows: list[PatternRow]
    warnings: list[str] = field(default_factory=list)
    missing_resets: list[dict] = field(default_factory=list)

    def to_table(self) -> str:
        lines = [f"# {self.name}",
                 f"{'addr':<12} {'data':<12} {'op':<4} desc"]
        for r in self.rows:
            lines.append(f"{r.addr_hex:<12} {r.data_hex:<12} {r.type:<4} "
                         f"{r.desc}")
        if self.warnings:
            lines.append("# warnings: " + "; ".join(self.warnings))
        return "\n".join(lines)


# internal field write before per-register aggregation
@dataclass
class _FieldWrite:
    peri: str
    reg: str
    addr: int
    pos: int
    width: int
    value: int
    phase: int
    source: str
    label: str
    field: str = ""                 # 字段名(用于识别使能位,config-then-enable 拆分)
    seq: int = 0                    # authoring order (directive index), for sort


class Composer:
    def __init__(self, chip: str = "py32f420", db: EncodingDB | None = None):
        self.chip = chip
        self.db = db or EncodingDB(chip)

    # ---- public ----------------------------------------------------------------

    def compile(self, req: ComposeRequest) -> ComposeResult:
        from .intent import validate, has_errors
        if req.chip != self.chip or self.db.chip != self.chip:
            raise ValueError('request, compiler and knowledge chip must match')
        issues = validate(req.directives, self.db)
        if has_errors(issues):
            raise ValueError('; '.join(str(issue) for issue in issues if issue.level == 'error'))
        writes: list[_FieldWrite] = []
        rows: list[PatternRow] = []      # standalone rows (verify/wait)
        warnings: list[str] = [str(issue) for issue in issues]
        seq = 0
        for d in req.directives:
            seq += 1
            try:
                fw, standalone = self._resolve(d, seq)
            except (KeyError, ValueError) as e:
                raise ValueError(f"directive #{seq} ({d.kind}): {e}") from e
            writes.extend(fw)
            rows.extend(standalone)

        agg_rows, agg_warn, missing_resets = self._aggregate(writes)
        warnings.extend(agg_warn)
        rows.extend(agg_rows)
        rows.sort(key=lambda r: (r.phase, r._seq))   # stable within phase
        return ComposeResult(req.name, rows, warnings, missing_resets)

    # ---- resolvers -------------------------------------------------------------

    def _resolve(self, d: Directive, seq: int):
        fn = getattr(self, f"_r_{d.kind}", None)
        if fn is None:
            raise ValueError(f"unknown directive kind {d.kind!r}")
        return fn(d, seq)

    def _r_clk_enable(self, d: Directive, seq: int):
        e = self.db.clk_enable(d.periph)
        addr = int(e["address"], 16)
        fw = _FieldWrite(
            peri="RCC", reg=e["register"], addr=addr, pos=e["pos"],
            width=1, value=1,
            phase=d.phase if d.phase is not None else PHASE_CLK_ENABLE,
            source=f"clk_enable({d.periph})->RCC.{e['register']}.{e['field']}",
            label=f"{d.periph} 时钟使能", field=e["field"], seq=seq)
        return [fw], []

    def _r_enable_bit(self, d: Directive, seq: int):
        """Set a named 1-bit enable (RCC.CR HSION/PLLON, OPA.CSR OPAEN...)."""
        info = self.db.field(d.peri, d.reg, d.field)
        addr = self._addr_of(info, d.peri, d.instance)
        fw = _FieldWrite(
            peri=self.db._peri_type(d.peri), reg=d.reg.upper(),
            addr=addr, pos=info["pos"], width=info["width"],
            value=1 if d.value is None else d.value,
            phase=d.phase if d.phase is not None
            else self._infer_phase(d.peri, d.reg, d.field),
            source=f"L0:{d.peri}.{d.reg}.{d.field}@bit{info['pos']}",
            label=d.note or f"{d.field} 置位", field=d.field, seq=seq)
        return [fw], []

    def _r_field_symbol(self, d: Directive, seq: int):
        """Set a field via an L1 symbol (encode resolves register+value)."""
        pls = [p for p in self.db.encode(d.symbol)
               if not d.reg or p.register.upper() == d.reg.upper()]
        if not pls:
            raise ValueError(f"symbol {d.symbol!r} not in L1"
                             + (f" for {d.reg}" if d.reg else ""))
        out = []
        for p in pls:
            if d.peri and self.db._peri_type(d.peri) != p.peripheral:
                raise ValueError(f'symbol {d.symbol} belongs to {p.peripheral}, not {d.peri}')
            instance = d.instance or (d.peri if d.peri and d.peri.upper() != p.peripheral else '')
            addr = self._reg_addr(p.peripheral, p.register, instance)
            out.append(_FieldWrite(
                peri=p.peripheral, reg=p.register, addr=addr,
                pos=p.bit_offset, width=p.bit_width, value=p.value,
                phase=d.phase if d.phase is not None
                else self._infer_phase(p.peripheral, p.register, p.field),
                source=f"L1:{d.symbol}->{p.register}.{p.field}={p.value}",
                label=d.note or d.symbol, field=p.field, seq=seq))
        # 通用规则(数据驱动,无外设特判):若此符号在 KB 标了"外接模拟引脚",
        # 自动补该引脚 analog 模式 + 端口时钟。DAC/OPA 等差异全在 analog_routing.json。
        func = self.db.analog_routing_pin(d.symbol)
        if func:
            pin = self.db.analog_pin(func)
            if pin:
                out.extend(self._analog_pin_writes(pin, seq, f"{func}外接→{pin}模拟"))
        return out, []

    def _r_field_value(self, d: Directive, seq: int):
        """Set a field to an explicit in-field value (sem-only fields like
        MCO2SEL/MCO2PRE that carry no L1 symbol). Value is justified by the
        L0 sem table, recorded in the source string."""
        info = self.db.field(d.peri, d.reg, d.field)
        if d.value is None:
            raise ValueError("field_value needs value")
        if d.value >= (1 << info["width"]):
            raise ValueError(f"value {d.value} exceeds {d.field} width")
        addr = self._addr_of(info, d.peri, d.instance)
        sem = (info.get("sem") or {})
        key = format(d.value, f"0{info['width']}b")
        sem_txt = sem.get(key, sem.get(str(d.value)))
        if sem_txt is None:                      # data registers carry no sem
            sem_txt = "numeric" if not sem else "?"
        fw = _FieldWrite(
            peri=self.db._peri_type(d.peri), reg=d.reg.upper(), addr=addr,
            pos=info["pos"], width=info["width"], value=d.value,
            phase=d.phase if d.phase is not None
            else self._infer_phase(d.peri, d.reg, d.field),
            source=f"L0sem:{d.peri}.{d.reg}.{d.field}={d.value}({sem_txt})",
            label=d.note or f"{d.field}={sem_txt}", field=d.field, seq=seq)
        return [fw], []

    def _r_pin_config(self, d: Directive, seq: int):
        """Expand a pin into AF + MODER/OTYPER/OSPEEDR/PUPDR writes."""
        port, n = self._pin_parts(d.pin)
        gpio = f"GPIO{port}"
        out = []
        # AF number from iomux
        af = self.db.pin_af(d.pin, d.func)
        if af is None:
            raise ValueError(f"{d.pin} has no AF for {d.func!r}")
        afr = "AFRL" if n < 8 else "AFRH"
        af_info = self.db.field(gpio, afr, f"AFSEL{n}")
        out.append(_FieldWrite(
            peri="GPIO", reg=afr, addr=self._addr_of(af_info, gpio),
            pos=af_info["pos"], width=af_info["width"], value=af,
            phase=PHASE_GPIO,
            source=f"iomux:{d.pin}+{d.func}=AF{af}",
            label=f"{d.pin} AF{af}={d.func}", seq=seq))
        # MODER (last), OTYPER, OSPEEDR, PUPDR — values from GPIO L1 symbols
        mode_v = self._sym_on(d.mode, "MODER")
        otype_v = self._sym_on(d.mode, "OTYPER") or 0
        speed_v = self._sym_on(d.speed, "OSPEEDR")
        pull_v = self._sym_on(d.pull, "PUPDR")
        for reg, fld_pat, val, sym, ph in [
            ("OTYPER", f"OT{n}", otype_v, d.mode, PHASE_GPIO),
            ("OSPEEDR", f"OSPEED{n}", speed_v, d.speed, PHASE_GPIO),
            ("PUPDR", f"PUPD{n}", pull_v, d.pull, PHASE_GPIO),
            ("MODER", f"MODE{n}", mode_v, d.mode, PHASE_GPIO_MODE),
        ]:
            info = self.db.field(gpio, reg, fld_pat)
            out.append(_FieldWrite(
                peri="GPIO", reg=reg, addr=self._addr_of(info, gpio),
                pos=info["pos"], width=info["width"], value=val,
                phase=ph, source=f"L1:{sym}->{reg}={val}",
                label=f"{d.pin} {reg}", seq=seq))
        return out, []

    def _r_check_ready(self, d: Directive, seq: int):
        """C_H verify that a ready bit is high."""
        info = self.db.field(d.peri, d.reg, d.field)
        addr = self._addr_of(info, d.peri, d.instance)
        mask = ((1 << info["width"]) - 1) << info["pos"]
        ready_phase = (PHASE_ENABLE + 1 if self.db._peri_type(d.peri) != 'RCC'
                       else PHASE_PLL_READY if "PLL" in d.field.upper()
                       else PHASE_OSC_READY)
        row = PatternRow(
            type="C_H", addr=addr, data=mask,
            desc=d.note or f"单次检查 {d.field} 就绪（非轮询）",
            sources=[f"L0:{d.peri}.{d.reg}.{d.field}@bit{info['pos']}"],
            phase=d.phase if d.phase is not None else ready_phase,
            mask=mask)
        row._seq = seq
        return [], [row]

    def _r_wait(self, d: Directive, seq: int):
        row = PatternRow(type="us", addr=None, data=d.us,
                         desc=d.note or f"延时 {d.us}us", sources=["timing"],
                         phase=d.phase if d.phase is not None else PHASE_PERIPH)
        row._seq = seq
        return [], [row]

    def _r_write_reg(self, d: Directive, seq: int):
        """Write a literal full-word value to a register — un-aggregated and
        order-preserving. For command/key registers that take a *sequence* of
        distinct writes to one address (IWDG.KR unlock→start→feed, RTC.WPR) and
        for full-width operands that aren't bit-fields (DMA CPAR/CMAR address).
        Bypasses field-merge so repeated same-address writes stay separate."""
        if d.value is None:
            raise ValueError("write_reg needs value")
        if not 0 <= d.value <= 0xFFFFFFFF:
            raise ValueError(f"value {d.value} out of 32-bit range")
        addr = self._reg_addr(d.peri, d.reg, d.instance)
        row = PatternRow(
            type="W", addr=addr, data=d.value,
            desc=d.note or f"{d.reg} <- 0x{d.value:08X}",
            sources=[f"raw:{d.peri}.{d.reg}=0x{d.value:08X}"],
            phase=d.phase if d.phase is not None
            else self._infer_phase(d.peri, d.reg),
            mask=0xFFFFFFFF)        # 整字面值有意 → 全字比对
        row._seq = seq
        return [], [row]

    def _analog_pin_writes(self, pin: str, seq: int, note: str = ""):
        """模拟引脚自包含写:端口时钟使能 + MODER=analog(0b11)。供 analog_pin
        directive 与 field_symbol 的模拟路由自动补全共用。带时钟使能,fresh 态也能写 MODER。"""
        port, n = self._pin_parts(pin)
        gpio = f"GPIO{port}"
        e = self.db.clk_enable(gpio)
        info = self.db.field(gpio, "MODER", f"MODE{n}")
        return [
            _FieldWrite(peri="RCC", reg=e["register"], addr=int(e["address"], 16),
                        pos=e["pos"], width=1, value=1, phase=PHASE_CLK_ENABLE,
                        source=f"clk_enable({gpio})->RCC.{e['register']}.{e['field']}",
                        label=f"{gpio} 时钟使能", field=e["field"], seq=seq),
            _FieldWrite(peri="GPIO", reg="MODER", addr=self._addr_of(info, gpio),
                        pos=info["pos"], width=info["width"], value=3,
                        phase=PHASE_GPIO_MODE,
                        source=f"analog:{pin}->{gpio}.MODER.MODE{n}=analog",
                        label=note or f"{pin} 模拟模式", field=f"MODE{n}", seq=seq),
        ]

    def _r_analog_pin(self, d: Directive, seq: int):
        """Put a pin in analog mode (MODER=0b11) + enable its port clock. Required
        for DAC/ADC/OPA/COMP external analog I/O — without it the GPIO digital
        structure fights the analog signal and the output is unstable (silicon-
        confirmed on DAC PA4). Analog-only: no AFR/OTYPER/OSPEEDR/PUPDR."""
        return self._analog_pin_writes(d.pin, seq, d.note), []

    # ---- aggregation -----------------------------------------------------------

    def _enable_field_patterns(self):
        """家族级使能位字段正则(数据驱动,缓存)。"""
        if not hasattr(self, "_en_pats"):
            self._en_pats = [re.compile(p, re.I) for p in self.db.enable_fields()]
        return self._en_pats

    @staticmethod
    def _apply(base: int, ws: list, base_source: str = '') -> tuple[int, list, int]:
        """把一组 _FieldWrite 叠加到 base 上,返回 (word, sources, mask)。
        mask = 这组真正写入的位的并集(不含 base reset 补位)——回读只比这些位。"""
        word = base
        srcs = [base_source or f"base=L0reset(0x{base:08X})"]
        mask = 0
        for w in ws:
            fmask = ((1 << w.width) - 1) << w.pos
            word = (word & ~fmask) | ((w.value << w.pos) & fmask)
            mask |= fmask
            srcs.append(w.source)
        return word, srcs, mask

    def _aggregate(self, writes: list[_FieldWrite]):
        by_addr: dict[int, list[_FieldWrite]] = {}
        for w in writes:
            by_addr.setdefault(w.addr, []).append(w)
        en_pats = self._enable_field_patterns()
        rows, warnings, missing_resets = [], [], []
        for addr, group in by_addr.items():
            g0 = group[0]
            base, missing = self.db.reset_word(g0.peri, g0.reg, addr)
            reset_source = self.db.reset_source(addr)
            base_source = (f"base=confirmed_reset({reset_source},0x{base:08X})"
                           if reset_source else '')
            if missing:
                warnings.append(
                    f"{g0.peri}.{g0.reg}: no reset value for {missing} "
                    f"(doc defect) — base bits assumed 0")
                missing_resets.append({'address': addr,
                                       'peripheral': self.db.register_instance(g0.peri, g0.reg, addr),
                                       'register': g0.reg.upper(), 'fields': missing})
            # 识别使能位(config-then-enable):非 RCC + 字段名匹配 enable_fields
            is_rcc = g0.peri.upper() == "RCC"
            enable_ws, config_ws = [], []
            for w in group:
                if (not is_rcc) and w.field and any(p.search(w.field) for p in en_pats):
                    enable_ws.append(w)
                else:
                    config_ws.append(w)

            if enable_ws and config_ws:
                # 同寄存器既有配置又有使能 → 拆两步:配置(使能位留 reset)先,使能后置
                cfg_word, cfg_srcs, cfg_mask = self._apply(base, config_ws, base_source)
                full_word, _, en_mask = self._apply(cfg_word, enable_ws)
                cfg_phase = max([PHASE_CLK_ENABLE] + [w.phase for w in config_ws])
                r1 = PatternRow(
                    type="W", addr=addr, data=cfg_word & 0xFFFFFFFF,
                    desc=" + ".join(dict.fromkeys(w.label for w in config_ws)),
                    sources=cfg_srcs, phase=cfg_phase, mask=cfg_mask)
                r1._seq = min(w.seq for w in config_ws)
                r2 = PatternRow(
                    type="W", addr=addr, data=full_word & 0xFFFFFFFF,
                    desc=" + ".join(dict.fromkeys(w.label for w in enable_ws)) + "(使能后置)",
                    sources=[f"after-config=0x{cfg_word:08X}"]
                            + [w.source for w in enable_ws],
                    phase=PHASE_ENABLE, mask=en_mask)
                r2._seq = max(w.seq for w in group)
                rows += [r1, r2]
            else:
                # 仅配置 / 仅使能 / RCC → 单字写;仅使能则延后到 PHASE_ENABLE
                word, srcs, mask = self._apply(base, group, base_source)
                phase = (PHASE_ENABLE if enable_ws
                         else max([PHASE_CLK_ENABLE] + [w.phase for w in group]))
                row = PatternRow(
                    type="W", addr=addr, data=word & 0xFFFFFFFF,
                    desc=" + ".join(dict.fromkeys(w.label for w in group)),
                    sources=srcs, phase=phase, mask=mask)
                row._seq = (max(w.seq for w in group) if enable_ws
                            else min(w.seq for w in group))
                rows.append(row)
        return rows, warnings, missing_resets

    # ---- helpers ---------------------------------------------------------------

    def _pin_parts(self, pin: str):
        m = _PIN.match(pin.strip())
        if not m:
            raise ValueError(f"bad pin {pin!r}")
        return m.group(1).upper(), int(m.group(2))

    def _addr_of(self, info: dict, peri: str, instance: str = "") -> int:
        addrs = info.get("addresses") or {}
        if instance:                    # explicit instance must resolve exactly
            for k, v in addrs.items():
                if k.upper() == instance.upper():
                    return int(v, 16)
            raise ValueError(f"instance {instance!r} not among {list(addrs)} "
                             f"for {peri}.{info.get('register')}")
        a = info.get("address")
        if a is None:
            a = addrs.get(peri.upper()) or (next(iter(addrs.values()), None))
        if a is None:
            raise ValueError(f"no address for {peri}.{info.get('register')}")
        return int(a, 16)

    def _reg_addr(self, peri: str, reg: str, instance: str = "") -> int:
        fld = self.db.register_fields(peri, reg)[0]
        return self._addr_of(self.db.field(peri, reg, fld), peri, instance)

    def _sym_on(self, symbol: str, reg: str) -> int:
        for p in self.db.encode(symbol):
            if p.register.upper() == reg.upper() and p.value is not None:
                return p.value
        return 0

    @staticmethod
    def _infer_phase(peri: str, reg: str, fld: str = "") -> int:
        peri, reg, fld = peri.upper(), reg.upper(), fld.upper()
        if peri == "GPIO":
            return PHASE_GPIO_MODE if reg == "MODER" else PHASE_GPIO
        # PWR.CR1.DBP unlocks backup-domain writes — must precede RCC.BDCR
        if peri == "PWR" and reg == "CR1" and fld == "DBP":
            return PHASE_CLK_ENABLE
        if peri == "RCC":
            if reg.endswith("ENR") or reg.endswith("RSTR"):
                return PHASE_CLK_ENABLE
            if reg == "CR":
                # PLLON must follow PLL config; oscillators go up first
                return PHASE_PLL_ON if "PLL" in fld else PHASE_OSC_ON
            if reg.startswith("PLLCFGR"):
                return PHASE_PLL_CONFIG
            if reg == "BDCR":          # LSE/LSI backup-domain oscillators
                return PHASE_OSC_READY if fld.endswith("RDY") else PHASE_OSC_ON
            return PHASE_CLK_MUX        # CFGR* system-clock mux / MCO
        return PHASE_PERIPH


# PatternRow needs a sort key set by the engine; give it a default.
PatternRow._seq = 0
