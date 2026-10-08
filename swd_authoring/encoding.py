"""EncodingDB — query facade over the encoding_v2 knowledge base (五件套).

One object, six questions (B2 promotion batch, HANDOFF_PROMOTION §二):

    db = EncodingDB("py32f420")
    db.field("RCC", "CR", "HSION")     # L0: pos/width/mask/addr/reset/sem
    db.encode("RCC_MCOSOURCE_HSI")     # symbol -> placements (FE/MFE unified)
    db.unit("RCC_OscInitTypeDef", "HSICalibrationValue")  # config-unit view
    db.clk_enable("GPIOA")             # clock enable (reg/bit/addr)
    db.pin_af("PA04", "MCO2")          # iomux: AF number or None
    db.conventions()                   # symbol -> raw / abs / mfe

Data sources (all lazy-loaded, read-only):
    cache/encoding_v2/<chip>/fieldmap.json          L0 + v1 metadata
    cache/encoding_v2/<chip>/<peri>_encoding.json   L1 FE/MFE/numeric/units
    cache/encoding_v2/<chip>/clock_control.json     __HAL_RCC_* macros
    cache/encoding_v2/<chip>/coverage_report.json   per-unit status (optional)
    data/chips/<chip>/iomux.json                    per-pin AF table

Convention logic mirrors experiments/init_ir/lib/encoding_db_bridge.py
(the ABS-vs-RAW decision is a property of the SYMBOL, decided globally per
peripheral — ADC_DMAACCESSMODE lesson). The bridge stays untouched in its
sandbox; this is the src-side home of that knowledge.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any

PACKAGE_DATA = Path(__file__).resolve().parent / "data"
CACHE_ROOT = PACKAGE_DATA / "cache"
DATA_ROOT = PACKAGE_DATA / "chips"


@dataclass(frozen=True)
class Placement:
    """One register-field landing of a symbol (an MFE yields several)."""
    peripheral: str
    register: str
    field: str
    bit_offset: int
    bit_width: int
    value: int | None            # in-field value (right-shifted)
    abs_value: int | None        # pre-shifted value (MFE: whole-symbol word)
    symbol: str
    kind: str                    # "fe" | "mfe"
    convention: str              # "raw" | "abs" | "mfe"
    init_struct: str | None
    init_struct_field: str | None
    confidence: str | None
    description: str = ""


class EncodingDB:
    """Read-only query facade; safe to share, caches everything it touches."""

    def __init__(self, chip: str = "py32f420",
                 products_dir: Path | None = None,
                 data_dir: Path | None = None,
                 reset_supplements: list[dict] | None = None):
        self.chip = chip
        self._products = Path(products_dir) if products_dir else CACHE_ROOT / chip
        self._data = Path(data_dir) if data_dir else DATA_ROOT / chip
        self._fieldmap: dict | None = None
        self._addresses: dict | None = None
        self._encodings: dict[str, dict] = {}      # peri(lower) -> file dict
        self._all_loaded = False
        self._clock: dict | None = None
        self._iomux: dict | None = None
        self._analog_routing: dict | None = None
        self._coverage: dict | None = None
        self._symbol_index: dict[str, list[Placement]] | None = None
        self._conventions: dict[str, str] | None = None
        self._runtime_values: dict = {}
        self._doc_defects: list = []
        self._reset_supplements = self._validate_reset_supplements(reset_supplements or [])

    def knowledge_version(self) -> str:
        """Digest of the local data snapshot used by this DB instance."""
        import hashlib
        digest = hashlib.sha256()
        for path in sorted(self._products.glob("*.json")):
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
        for path in (self._data / "iomux.json", self._data / "analog_routing.json"):
            if path.exists():
                digest.update(path.name.encode())
                digest.update(path.read_bytes())
        if self._reset_supplements:
            digest.update(b"reset_supplements")
            digest.update(json.dumps(self._reset_supplements, ensure_ascii=False,
                                     sort_keys=True, separators=(',', ':')).encode())
        return digest.hexdigest()

    def _validate_reset_supplements(self, supplements: list[dict]) -> dict[int, dict]:
        if not isinstance(supplements, list):
            raise ValueError('reset_supplements must be a list')
        checked: dict[int, dict] = {}
        for supplement in supplements:
            if not isinstance(supplement, dict):
                raise ValueError('reset supplement must be an object')
            address, value = supplement.get('address'), supplement.get('value')
            peripheral, register = supplement.get('peripheral'), supplement.get('register')
            source, confirmed_at = supplement.get('source'), supplement.get('confirmedAt')
            if (type(address) is not int or type(value) is not int
                    or not 0 <= address <= 0xFFFFFFFF or not 0 <= value <= 0xFFFFFFFF):
                raise ValueError('reset supplement address and value must be 32-bit unsigned integers')
            if not isinstance(peripheral, str) or not isinstance(register, str):
                raise ValueError('reset supplement peripheral and register must be strings')
            if not isinstance(source, str) or not source.strip():
                raise ValueError('reset supplement source must be non-empty')
            if not isinstance(confirmed_at, str):
                raise ValueError('reset supplement confirmedAt must be a string')
            typ = self._peri_type(peripheral)
            reg = register.upper()
            addrs = (self._addresses or {}).get(typ, {}).get(reg, {})
            instance = peripheral.upper()
            if instance not in addrs or int(addrs[instance], 16) != address:
                raise ValueError(f'reset supplement address does not match {peripheral}.{reg}')
            if address in checked:
                raise ValueError(f'duplicate reset supplement for 0x{address:08X}')
            known_word, known_mask = 0, 0
            for info in self._fieldmap[typ][reg].values():
                reset = self._parse_reset(info.get('reset'))
                if reset is None:
                    continue
                mask = ((1 << info['width']) - 1) << info['pos']
                known_word |= (reset << info['pos']) & mask
                known_mask |= mask
            if value & known_mask != known_word:
                raise ValueError(f'reset supplement conflicts with known reset bits for {peripheral}.{reg}')
            checked[address] = {'address': address, 'peripheral': instance, 'register': reg,
                                'value': value, 'source': source, 'confirmedAt': confirmed_at}
        return checked

    def reviewed_access(self, address: int, pos: int, width: int) -> str:
        """Narrow, sourced supplements; never guess access for unknown fields."""
        path = self._products / 'reviewed_access.json'
        if not path.exists():
            return ''
        record = json.loads(path.read_text(encoding='utf-8'))
        for item in record['fields']:
            if (item['address'], item['pos'], item['width']) == (address, pos, width):
                return item['access']
        return ''

    # ---- loading ------------------------------------------------------------

    def _read(self, name: str) -> dict:
        path = self._products / name
        if not path.exists():
            raise FileNotFoundError(
                f"encoding_v2 product missing: {path} — run "
                f"`python -m swd_commander.data.encoding_v2.run_all` first")
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_fieldmap(self) -> dict:
        if self._fieldmap is None:
            d = self._read("fieldmap.json")
            self._fieldmap = d["peripherals"]
            self._addresses = d.get("register_addresses", {})
            self._runtime_values = d.get("runtime_values", {})
            self._doc_defects = d.get("doc_defects", [])
        return self._fieldmap

    def _load_encoding(self, peri: str) -> dict | None:
        key = peri.lower()
        if key not in self._encodings:
            path = self._products / f"{key}_encoding.json"
            self._encodings[key] = (
                json.loads(path.read_text(encoding="utf-8"))
                if path.exists() else None)
        return self._encodings[key]

    def _load_all_encodings(self) -> dict[str, dict]:
        if not self._all_loaded:
            for p in sorted(self._products.glob("*_encoding.json")):
                self._load_encoding(p.name[:-len("_encoding.json")])
            self._all_loaded = True
        return {k: v for k, v in self._encodings.items() if v is not None}

    def _load_clock(self) -> dict:
        if self._clock is None:
            self._clock = self._read("clock_control.json")
        return self._clock

    def _load_iomux(self) -> dict:
        if self._iomux is None:
            path = self._data / "iomux.json"
            if not path.exists():
                raise FileNotFoundError(f"iomux table missing: {path}")
            self._iomux = json.loads(path.read_text(encoding="utf-8"))
        return self._iomux

    def _load_analog_routing(self) -> dict:
        """符号→隐含模拟引脚 的策展元数据(可选,缺文件则空)。纯数据,
        让 composer 不必硬编码外设语义就能补模拟引脚。"""
        if self._analog_routing is None:
            path = self._data / "analog_routing.json"
            self._analog_routing = (
                json.loads(path.read_text(encoding="utf-8")) if path.exists() else {})
        return self._analog_routing

    def analog_routing_pin(self, symbol: str) -> str | None:
        """若某符号表示"把模拟外设引到外部引脚",返回它隐含的模拟功能名
        (iomux analog 名,如 'DAC_OUT1'),否则 None。composer 用它通用地决定
        是否给外接引脚补 analog 模式——配 analog_pin(返回值) 取到具体引脚。"""
        m = (self._load_analog_routing().get("symbol_implies_analog_pin") or {})
        return m.get(symbol)

    def companion_writes(self, symbol: str) -> list[str]:
        """若某外接路由符号隐含"还必须配置某些伴随字段",返回这些伴随 L1 符号
        (如 DAC 外接路由隐含必须配输出使能);否则空。纯数据驱动:换芯片/无使能
        字段只改 analog_routing.json,字段名不进代码。lint 据此判"配了路由却漏使能"。"""
        m = (self._load_analog_routing().get("symbol_implies_companion_writes") or {})
        return list(m.get(symbol, ()))

    def enable_fields(self) -> list[str]:
        """家族级:外设功能使能位的字段名正则(config-then-enable)。composer 据此
        把使能位拆成单独后置一次写。不含 RCC(时钟/振荡器使能另有时序相位)。缺则空。"""
        return list(self._load_analog_routing().get("enable_fields") or ())

    def readback_ignore_regs(self) -> list[str]:
        """家族级:回读应跳过的寄存器名正则(写触发/键/自清,如 EGR/KR/SWTRIG)。
        回读 oracle 据此跳过,避免对"写后不回读"的寄存器报假阴。缺则空。"""
        return list(self._load_analog_routing().get("readback_ignore_regs") or ())

    def companion_conventions(self) -> list[dict]:
        """家族级命名约定:[{route_field, enable_field, note}](正则,大小写不敏感)。
        lint 据此通用推导"落在路由字段的符号 → 同寄存器使能字段须被配",换同族
        芯片整块照抄即可、无需逐符号策展。缺文件/缺键则空。"""
        return list(self._load_analog_routing().get("companion_conventions") or ())

    def companion_field(self, symbol: str) -> set[tuple[str, str]]:
        """把一个伴随符号解析成它落在的 (寄存器, 字段) 坐标集合(均大写)。
        lint 用它判"这个字段有没有被任一 directive 配过"。未知符号→空集。"""
        return {(p.register.upper(), p.field.upper()) for p in self.encode(symbol)}

    def _load_coverage(self) -> dict | None:
        if self._coverage is None:
            path = self._products / "coverage_report.json"
            self._coverage = (json.loads(path.read_text(encoding="utf-8"))
                              if path.exists() else {})
        return self._coverage or None

    # ---- L0: field ------------------------------------------------------------

    _RE_INSTANCE = re.compile(r"^([A-Z]+?)\d+(?:_\w+)?$")   # TIM2 / ADC1_COMMON
    _RE_GPIO_INST = re.compile(r"^(GPIO)[A-Z]$")            # GPIOA

    def _peri_type(self, peri: str) -> str:
        """Normalize an instance name (GPIOA/TIM2) to its CMSIS type."""
        fm = self._load_fieldmap()
        p = peri.upper()
        if p in fm:
            return p
        m = self._RE_GPIO_INST.match(p)
        if m and m.group(1) in fm:
            return m.group(1)
        m = self._RE_INSTANCE.match(p)
        if m and m.group(1) in fm:
            return m.group(1)
        raise KeyError(f"unknown peripheral {peri!r} for chip {self.chip}")

    @staticmethod
    def _parse_reset(s) -> int | None:
        """registers.xlsx reset strings: '1', '0', \"2'b00\", \"9'h100\"...
        (CJK quotes already normalized at build time)."""
        if s in (None, ""):
            return None
        m = re.match(r"(\d+)'([bh])([0-9a-fA-FxX]+)$", str(s).strip())
        if m:
            txt = m.group(3).replace("x", "0").replace("X", "0")
            try:
                return int(txt, 2 if m.group(2) == "b" else 16)
            except ValueError:        # malformed source, e.g. "1'b9" (KB defect)
                return None
        try:
            return int(str(s), 0)
        except ValueError:
            return None

    def reset_word(self, peri: str, reg: str, address: int | None = None) -> tuple[int, list[str]]:
        """Synthesize a register's reset word from per-field L0 reset values.

        Returns (word, missing) — `missing` lists fields with no reset value
        in the KB (new-product chip: often a documentation defect). The
        composer uses this as the base for whole-word writes so SWD/debug
        default bits (e.g. PA13/14 AF on MODER) survive a full-word write.
        """
        typ = self._peri_type(peri)
        fm = self._load_fieldmap()
        regd = fm.get(typ, {}).get(reg.upper())
        if regd is None:
            raise KeyError(f"{typ}.{reg.upper()} not in L0 fieldmap")
        word, missing = 0, []
        for fld, info in regd.items():
            rv = self._parse_reset(info.get("reset"))
            if rv is None:
                missing.append(fld)
                continue
            word |= (rv & ((1 << info["width"]) - 1)) << info["pos"]
        supplement = self._reset_supplements.get(address)
        if supplement and supplement['peripheral'] == self.register_instance(typ, reg, address):
            remaining = []
            for fld in missing:
                info = regd[fld]
                mask = ((1 << info['width']) - 1) << info['pos']
                word = (word & ~mask) | (supplement['value'] & mask)
            missing = remaining
        return word & 0xFFFFFFFF, missing

    def register_instance(self, peri: str, reg: str, address: int) -> str:
        """Resolve the concrete register instance at an address."""
        typ = self._peri_type(peri)
        for instance, known_address in (self._addresses or {}).get(typ, {}).get(reg.upper(), {}).items():
            if int(known_address, 16) == address:
                return instance
        raise KeyError(f'no {typ}.{reg.upper()} register at 0x{address:08X}')

    def reset_source(self, address: int) -> str | None:
        """Confirmation source for an address-scoped reset supplement, if any."""
        supplement = self._reset_supplements.get(address)
        return supplement['source'] if supplement else None

    def register_fields(self, peri: str, reg: str) -> list[str]:
        """All L0 field names of one register (bit order, LSB first).
        KeyError if the register is unknown."""
        typ = self._peri_type(peri)
        fm = self._load_fieldmap()
        try:
            fields = fm[typ][reg.upper()]
        except KeyError:
            raise KeyError(f"{typ}.{reg.upper()} not in L0 fieldmap") from None
        return sorted(fields, key=lambda f: fields[f]["pos"])

    def field(self, peri: str, reg: str, fld: str) -> dict:
        """L0 lookup: position/width/mask + v1 metadata (addr/reset/sem)."""
        typ = self._peri_type(peri)
        fm = self._load_fieldmap()
        try:
            info = fm[typ][reg.upper()][fld.upper()]
        except KeyError:
            raise KeyError(
                f"{typ}.{reg.upper()}.{fld.upper()} not in L0 fieldmap") from None
        addrs = (self._addresses or {}).get(typ, {}).get(reg.upper(), {})
        out = {"peripheral": typ, "register": reg.upper(), "field": fld.upper(),
               **info, "addresses": addrs}
        # convenience: the single address when unambiguous, or the requested
        # instance's (field("GPIOA", ...) -> GPIOA's MODER address)
        inst = peri.upper()
        if inst in addrs:
            out["address"] = addrs[inst]
        elif len(addrs) == 1:
            out["address"] = next(iter(addrs.values()))
        address = out.get('address')
        if address is not None and int(address, 16) in self._reset_supplements:
            out['resetSupplement'] = dict(self._reset_supplements[int(address, 16)])
            if self._parse_reset(info.get('reset')) is None:
                out['reset'] = (out['resetSupplement']['value'] >> info['pos']) & ((1 << info['width']) - 1)
        return out

    # ---- L1: encode -----------------------------------------------------------

    def search(self, query: str, peripheral: str = '', limit: int = 40) -> dict:
        """Bounded discovery over source names and descriptions, with source facts."""
        if not isinstance(query, str) or not isinstance(peripheral, str) or len(query) > 100:
            raise ValueError('知识查询参数无效')
        needle = query.strip().casefold()
        kind = self._peri_type(peripheral) if peripheral else ''
        matches = []
        for peri, registers in self._load_fieldmap().items():
            if kind and peri != kind:
                continue
            for register, fields in registers.items():
                for field, info in fields.items():
                    if needle in (peri + '.' + register + '.' + field + ' ' + str(info)).casefold():
                        matches.append((peripheral or peri, register, field))
        return {'fields': [self.field(*item) for item in matches[:limit]],
                'total': len(matches), 'truncated': len(matches) > limit,
                'knowledgeVersion': self.knowledge_version(), 'source': 'bundled'}

    @staticmethod
    def _split_field_keys(data: dict) -> set[tuple]:
        counts: dict[tuple, int] = {}
        for fe in data.get("field_encodings", []):
            key = (fe.get("init_struct"), fe.get("init_struct_field"))
            if key == (None, None):
                continue
            counts[key] = counts.get(key, 0) + 1
        return {k for k, n in counts.items() if n >= 2}

    def _build_symbol_index(self) -> dict[str, list[Placement]]:
        if self._symbol_index is not None:
            return self._symbol_index
        index: dict[str, list[Placement]] = {}
        conventions: dict[str, str] = {}
        for data in self._load_all_encodings().values():
            split = self._split_field_keys(data)
            abs_syms = {enc["symbol"]
                        for fe in data.get("field_encodings", [])
                        if (fe.get("init_struct"),
                            fe.get("init_struct_field")) in split
                        for enc in fe.get("encodings", [])}
            for fe in data.get("field_encodings", []):
                for enc in fe.get("encodings", []):
                    sym = enc["symbol"]
                    conv = "abs" if sym in abs_syms else "raw"
                    abs_val = enc.get("abs_value")
                    if abs_val is None and enc.get("value") is not None:
                        abs_val = int(enc["value"]) << int(fe["bit_offset"])
                    index.setdefault(sym, []).append(Placement(
                        peripheral=fe["peripheral"], register=fe["register"],
                        field=fe["field"], bit_offset=fe["bit_offset"],
                        bit_width=fe["bit_width"],
                        value=enc.get("value"), abs_value=abs_val,
                        symbol=sym, kind="fe", convention=conv,
                        init_struct=fe.get("init_struct"),
                        init_struct_field=fe.get("init_struct_field"),
                        confidence=fe.get("confidence"),
                        description=enc.get("description", "")))
                    conventions[sym] = conv
            for mfe in data.get("multi_field_encodings", []):
                sym = mfe["symbol"]
                for f in mfe.get("fields", []):
                    index.setdefault(sym, []).append(Placement(
                        peripheral=mfe["peripheral"], register=f["register"],
                        field=f["field"], bit_offset=f["bit_offset"],
                        bit_width=f["bit_width"],
                        value=f.get("value"), abs_value=mfe.get("abs_value"),
                        symbol=sym, kind="mfe", convention="mfe",
                        init_struct=mfe.get("init_struct"),
                        init_struct_field=mfe.get("init_struct_field"),
                        confidence=mfe.get("confidence"),
                        description=mfe.get("description", "")))
                conventions[sym] = "mfe"
        self._symbol_index = index
        self._conventions = conventions
        return index

    def encode(self, symbol: str) -> list[Placement]:
        """Symbol -> all its register-field landings (FE and MFE unified).

        An MFE symbol returns one Placement per touched field, all carrying
        the same whole-symbol `abs_value`. Empty list = unknown symbol.
        """
        return list(self._build_symbol_index().get(symbol, ()))

    def conventions(self) -> dict[str, str]:
        """symbol -> "raw" / "abs" / "mfe" (bridge's value convention, global)."""
        self._build_symbol_index()
        return dict(self._conventions or {})

    def encodings_for(self, peri: str, reg: str, fld: str) -> list[Placement]:
        """Placement-keyed L1 lookup: all named encodings landing on one
        register field (the inverse of encode()). Empty list = no L1 entry."""
        typ = self._peri_type(peri)
        r, f = reg.upper(), fld.upper()
        out = [p for pls in self._build_symbol_index().values() for p in pls
               if p.peripheral == typ and p.register.upper() == r
               and p.field.upper() == f]
        out.sort(key=lambda p: (p.value is None, p.value, p.symbol))
        return out

    # ---- config-unit view ------------------------------------------------------

    def unit(self, struct_or_fn: str, field: str) -> dict:
        """Config-unit view: everything known about (init struct/fn, field).

        Returns {struct, field, kind, type, status, placements, numerics};
        `status` comes from coverage_report.json when present (covered /
        numeric_range / selector / ... — the attribution side of the
        entry-or-attribution ledger).
        """
        out: dict[str, Any] = {"struct": struct_or_fn, "field": field,
                               "kind": None, "type": None, "status": None,
                               "placements": [], "numerics": []}
        for data in self._load_all_encodings().values():
            for cu in data.get("config_units", []) or []:
                if cu.get("struct") == struct_or_fn and cu.get("field") == field:
                    out["kind"] = cu.get("kind")
                    out["type"] = cu.get("type")
            for nf in data.get("numeric_fields", []) or []:
                if (nf.get("init_struct") == struct_or_fn
                        and nf.get("init_struct_field") == field):
                    out["numerics"].append(dict(nf))
        for pl in self._build_symbol_index().values():
            for p in pl:
                if p.init_struct == struct_or_fn and p.init_struct_field == field:
                    out["placements"].append(p)
        cov = self._load_coverage()
        if cov:
            for p in cov.get("peripherals", []):
                for f in p.get("fields", []):
                    if f.get("struct") == struct_or_fn and f.get("field") == field:
                        out["status"] = f.get("status")
        return out

    def units_search(self, keyword: str) -> list[dict]:
        """Keyword search over config units (struct/field/ref names,
        case-insensitive substring) — the discoverability path when the
        exact InitTypeDef field name is unknown (DAC_OutputBuffer lesson:
        the ST-generic name doesn't exist on this chip, the real unit is
        DAC_ExtOutputConfTypeDef.DAC_OutputMode)."""
        kw = keyword.lower()
        out = []
        for data in self._load_all_encodings().values():
            for cu in data.get("config_units", []) or []:
                hay = " ".join(str(cu.get(k, "")) for k in
                               ("struct", "field", "ref")).lower()
                if kw in hay:
                    out.append({"peripheral": data.get("peripheral"), **cu})
        return out

    # ---- curated runtime knowledge ---------------------------------------------

    def runtime_values(self) -> dict:
        """Curated runtime-value addresses (e.g. HSI factory-trim ROM family)
        from metadata_overrides — values a static vector reads at run time."""
        self._load_fieldmap()
        return dict(self._runtime_values)

    def doc_defects(self) -> list[dict]:
        """The documentation-defect ledger (new-product chip: every source is
        incomplete; corpus-attested holes are reported here for the chip team)."""
        self._load_fieldmap()
        return list(self._doc_defects)

    # ---- clock enable ------------------------------------------------------------

    def clk_enable(self, periph: str) -> dict:
        """Clock-enable bit for a peripheral INSTANCE name (GPIOA, TIM1...).

        Returns {register, field, pos, mask, address?}; KeyError if the
        __HAL_RCC_<periph>_CLK_ENABLE macro family doesn't know it.
        """
        table = self._load_clock().get("clk_enable", {})
        key = periph.upper()
        if key not in table:
            raise KeyError(
                f"no clock-enable macro for {periph!r}; known: "
                f"{sorted(table)[:8]}... ({len(table)} total)")
        return dict(table[key])

    # ---- iomux ---------------------------------------------------------------

    _RE_PIN = re.compile(r"^P([A-Z])(\d{1,2})$")

    def pin_af(self, pin: str, func: str) -> int | None:
        """AF number for (pin, function), e.g. ("PA04", "MCO2") -> 0.

        Pin accepts PA4 / PA04. Function matches an alternate-function name
        exactly first, then as a whole word inside compound names
        (e.g. "TIM1_CH1" matches func="TIM1_CH1" but not func="CH1").
        None = this pin has no such function (check another pin or the
        full table via pin_functions()).
        """
        entry = self._pin_entry(pin)
        if entry is None:
            raise KeyError(f"pin {pin!r} not in iomux table")
        afs = entry.get("alternate_functions") or {}
        f = func.upper()
        for af, name in afs.items():
            if name and name.upper() == f:
                return int(af[2:])
        for af, name in afs.items():
            if name and f in re.split(r"[/,\s]+", name.upper()):
                return int(af[2:])
        return None

    def pin_functions(self, pin: str) -> dict:
        """Full iomux row for a pin: alternate_functions / analog / additional."""
        entry = self._pin_entry(pin)
        if entry is None:
            raise KeyError(f"pin {pin!r} not in iomux table")
        return entry

    def pin_analog(self, pin: str) -> dict:
        """Analog functions of a pin (the iomux 'analog' block), e.g. PA4 ->
        {'adc':'ADC2_IN11','dac':'DAC_OUT1','comp':'COMP3_VINP1','opa':'OPA3_VINN1','vref':None}.
        Analog functions are NOT alternate functions — the pin is driven in
        MODER=analog, no AF number; pin_af() won't find them."""
        entry = self._pin_entry(pin)
        if entry is None:
            raise KeyError(f"pin {pin!r} not in iomux table")
        return entry.get("analog") or {}

    def analog_pin(self, func: str) -> str | None:
        """Reverse: which pin carries an analog function. `func` matches any
        analog value (e.g. 'DAC_OUT1', 'ADC2_IN11', 'COMP3_VINP1', 'OPA3_VINN1').
        Returns the pin name normalized as PA4 (no leading zero), or None.
        Composer uses this to know which pin to put in analog mode when an
        analog peripheral routes to an external pin."""
        f = func.upper()
        for port in (self._load_iomux().get("ports", {}) or {}).values():
            for p in (port.get("pins") or []):
                for v in (p.get("analog") or {}).values():
                    if v and v.upper() == f:
                        m = self._RE_PIN.match((p.get("pin_name") or "").upper())
                        return f"P{m.group(1)}{int(m.group(2))}" if m else p.get("pin_name")
        return None

    def _pin_entry(self, pin: str) -> dict | None:
        m = self._RE_PIN.match(pin.upper().strip())
        if not m:
            raise ValueError(f"bad pin name {pin!r} (expect PA4 / PA04)")
        port, num = m.group(1), int(m.group(2))
        want = f"P{port}{num:02d}"
        ports = self._load_iomux().get("ports", {})
        for p in (ports.get(f"Port{port}", {}) or {}).get("pins", []) or []:
            name = (p.get("pin_name") or "").upper()
            if name == want or name.startswith(want + "-"):
                return p
        return None
