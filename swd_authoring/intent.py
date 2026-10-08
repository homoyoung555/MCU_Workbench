"""Intent layer — the JSON ⇄ Directive seam between the LLM and the composer.

The request-time LLM (WA-HA collapsed, e.g. MiniMax) emits a JSON object; this
module turns it into a `ComposeRequest` the composer can compile, and — more
importantly — VALIDATES it against the knowledge base so an LLM hallucination
(non-existent register field, illegal value, unknown HAL symbol, pin with no
such AF) is caught deterministically before it ever reaches a register write.

Two validation tiers:
  1. schema  — kind is known, required fields present (no KB needed)
  2. semantic — placement exists in L0, value fits the field width / sem table,
                L1 symbol resolves, pin has the requested AF (needs EncodingDB)

This is the architectural guard: the LLM does only semantics; everything it
outputs is re-checked by deterministic code + the KB.

JSON shape (one ComposeRequest):
  {
    "name": "MCO_PA4_HSI_8M",
    "chip": "py32f420",
    "directives": [
      {"kind": "check_ready", "peri": "RCC", "reg": "CR", "field": "HSIRDY"},
      {"kind": "field_value", "peri": "RCC", "reg": "CFGR1",
       "field": "MCO2SEL", "value": "0b0010"},
      ...
    ]
  }
`value` accepts an int or a string ("0b0010" / "0x10" / "2").
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import fields as _dc_fields
from typing import Any, Optional

from .composer import ComposeRequest, Directive

# required fields per kind (schema tier)
REQUIRED: dict[str, list[str]] = {
    "clk_enable": ["periph"],
    "enable_bit": ["peri", "reg", "field"],
    "field_symbol": ["symbol"],
    "field_value": ["peri", "reg", "field", "value"],
    "pin_config": ["pin", "func"],
    "check_ready": ["peri", "reg", "field"],
    "wait": ["us"],
    "write_reg": ["peri", "reg", "value"],
    "analog_pin": ["pin"],
}
KINDS = set(REQUIRED)
DIRECTIVE_FIELDS = {f.name for f in _dc_fields(Directive)}
_INT_FIELDS = {"value", "us", "phase"}
_DEFAULTS = Directive(kind="_")


@dataclass
class Issue:
    """A validation finding. `index` is 1-based directive number, -1 = whole."""
    index: int
    level: str          # "error" | "warning"
    message: str
    code: str = ""      # "" | "completeness" — agent-self-fixable structural gap

    def __str__(self) -> str:
        where = "request" if self.index < 0 else f"directive #{self.index}"
        return f"[{self.level}] {where}: {self.message}"


# ---- coercion / loading ------------------------------------------------------

def _coerce_int(v: Any) -> Optional[int]:
    if isinstance(v, bool):
        raise ValueError('boolean is not an integer configuration value')
    if v is None:
        return None
    if isinstance(v, int):
        return v
    s = str(v).strip()
    if not s:
        return None
    return int(s, 0)            # 0b.. / 0x.. / 0o.. / decimal


def directive_from_dict(d: dict) -> Directive:
    """Build a Directive from a JSON object. Unknown keys are ignored here
    (the validator reports them); int-like fields are coerced."""
    if not isinstance(d, dict):
        raise ValueError("directive must be a JSON object")
    kw: dict[str, Any] = {}
    for k, v in d.items():
        if k not in DIRECTIVE_FIELDS:
            continue
        if k not in _INT_FIELDS and not isinstance(v, str):
            raise ValueError(f'{k} must be a string')
        kw[k] = _coerce_int(v) if k in _INT_FIELDS else v
    if not kw.get("kind"):
        raise ValueError("directive missing 'kind'")
    return Directive(**kw)


def request_from_json(data: dict) -> ComposeRequest:
    """Build a ComposeRequest from a JSON object (no validation)."""
    if not isinstance(data, dict):
        raise ValueError("request must be a JSON object")
    raw = data.get("directives", [])
    if not isinstance(raw, list):
        raise ValueError("'directives' must be a list")
    return ComposeRequest(
        name=str(data.get("name", "unnamed")),
        chip=str(data.get("chip", "py32f420")),
        directives=[directive_from_dict(x) for x in raw])


def directive_to_dict(d: Directive) -> dict:
    """Inverse: emit a minimal JSON object (only non-default fields)."""
    out = {"kind": d.kind}
    for f in sorted(DIRECTIVE_FIELDS):
        if f == "kind":
            continue
        v = getattr(d, f)
        if v not in (None, "") and v != getattr(_DEFAULTS, f):
            out[f] = v
    return out


# ---- validation --------------------------------------------------------------

_PIN_PORT = re.compile(r"^P([A-Z])\d{1,2}$", re.IGNORECASE)

# 有 clk_enable 宏、但参考语料(人工 oracle)里配置时不需显式门控的外设。
# COMP:CSR 经总线即可访问,对账语料 COMP1/COMP2 均不配 COMPEN 仍 EXACT。
_CLK_GATE_OPTIONAL = {"COMP"}
_WRITABLE_ACCESS = {"RW", "W"}


def _writable(info, value):
    access = str(info.get('access', '')).upper()
    # RS is set-only: do not claim that writing zero clears an enable/status bit.
    return access in _WRITABLE_ACCESS or (access == 'RS' and value == 1)


def _clk_completeness(directives: list[Directive], db: Any) -> list[Issue]:
    """List-level lint: a peripheral whose functional registers are configured
    but whose clock is never enabled. Catches the common omission (agent forgets
    clk_enable). Self-skips peripherals with no clock gate — EXTI / DBGMCU / IWDG
    / RTC etc. raise from db.clk_enable, so they never warn — and RCC clock-tree
    writes (which gate nothing of their own)."""
    enabled = {(d.periph or "").upper() for d in directives if d.kind == "clk_enable"}
    configured: dict[str, int] = {}
    for i, d in enumerate(directives, 1):
        if d.kind in ("clk_enable", "check_ready", "wait"):
            continue
        if d.kind == "pin_config":
            m = _PIN_PORT.match((d.pin or "").strip())
            key = ("GPIO" + m.group(1).upper()) if m else ""
        else:
            key = (d.instance or d.peri or "").upper()
        if key and key not in configured:
            configured[key] = i
    out: list[Issue] = []
    for key, idx in configured.items():
        if key in ("", "RCC") or key in _CLK_GATE_OPTIONAL:
            continue
        try:
            db.clk_enable(key)          # raises if the peripheral has no gate
        except (KeyError, ValueError):
            continue
        if key not in enabled:
            out.append(Issue(idx, "warning",
                             f"配置了 {key} 的寄存器但缺 clk_enable {key}"
                             f"(外设时钟未使能)", code="completeness"))
    return out


def _routing_companion_need(d: Directive, db: Any) -> set[tuple[str, str]]:
    """The (register, field) coordinates a routing-symbol directive REQUIRES be
    configured, from two data sources (union):
      ① family naming convention (db.companion_conventions) — derived, no
         per-symbol curation: a symbol landing on a 'route'-named field requires
         the same register's 'enable'-named sibling field.
      ② per-symbol override (db.companion_writes) — curated exceptions only,
         when the convention mis-fires; default empty.
    NO field name lives in code: the convention patterns and exceptions are all
    KB data, so a new chip inherits the family convention block verbatim."""
    need: set[tuple[str, str]] = set()
    if d.kind != "field_symbol" or not d.symbol:
        return need
    placements = db.encode(d.symbol)
    # ① convention-derived
    for c in db.companion_conventions():
        route_pat, en_pat = c.get("route_field"), c.get("enable_field")
        if not route_pat or not en_pat:
            continue
        for p in placements:
            if not re.search(route_pat, p.field, re.I):
                continue
            try:
                siblings = db.register_fields(p.peripheral, p.register)
            except (KeyError, ValueError):
                continue
            for sib in siblings:
                if re.search(en_pat, sib, re.I):
                    need.add((p.register.upper(), sib.upper()))
    # ② per-symbol override
    for comp in db.companion_writes(d.symbol):
        need |= db.companion_field(comp)
    return need


def _routing_completeness(directives: list[Directive], db: Any) -> list[Issue]:
    """List-level lint: an external-routing symbol is configured but its required
    companion field (e.g. DAC output-enable) is never touched by any directive.

    The requirement is data-derived (see _routing_companion_need) — a family
    naming convention plus per-symbol exceptions, NO field name in code. A chip
    that names the enable field differently or lacks it is handled by the
    convention regex / absence of a match alone. Checks the field is touched AT
    ALL, not its value: buffer on/off is the agent's semantic choice, and the
    meter is the value oracle (this is the inner/static oracle, best-effort)."""
    touched: set[tuple[str, str]] = set()      # (register, field) this list writes
    for d in directives:
        if d.kind in ("enable_bit", "field_value", "check_ready") and d.reg and d.field:
            touched.add((d.reg.upper(), d.field.upper()))
        elif d.kind == "field_symbol" and d.symbol:
            for p in db.encode(d.symbol):
                touched.add((p.register.upper(), p.field.upper()))
        elif d.kind == "write_reg" and d.reg:
            touched.add((d.reg.upper(), "*"))   # whole-word write covers the reg
    out: list[Issue] = []
    for i, d in enumerate(directives, 1):
        for (r, f) in sorted(_routing_companion_need(d, db)):
            if (r, f) not in touched and (r, "*") not in touched:
                out.append(Issue(i, "warning",
                                 f"配了外接路由 {d.symbol},但配套使能 {r}.{f} "
                                 f"没有任何 directive 配置——外接输出会不稳",
                                 code="completeness"))
    return out


def validate(directives: list[Directive], db: Any = None) -> list[Issue]:
    """Schema (+ semantic if `db` given) validation. Returns all findings."""
    issues: list[Issue] = []
    for i, d in enumerate(directives, 1):
        if not isinstance(d, Directive) or any(not isinstance(getattr(d, key), str) for key in DIRECTIVE_FIELDS - _INT_FIELDS):
            issues.append(Issue(i, 'error', 'invalid directive field types'))
            continue
        if any(getattr(d, key) is not None and type(getattr(d, key)) is not int for key in _INT_FIELDS):
            issues.append(Issue(i, 'error', 'configuration numbers must be integers'))
            continue
        if d.kind not in KINDS:
            issues.append(Issue(i, "error",
                                f"unknown kind {d.kind!r}; valid: {sorted(KINDS)}"))
            continue
        missing = [f for f in REQUIRED[d.kind]
                   if getattr(d, f) in (None, "")]
        if missing:
            issues.append(Issue(i, "error",
                                f"{d.kind} requires {missing}"))
            continue
        if d.phase is not None:
            issues.append(Issue(i, 'error', 'custom phase boundaries are not yet supported', 'unsupported_phase'))
            continue
        if db is not None:
            issues.extend(_semantic_issues(i, d, db))
    if db is not None and not has_errors(issues):
        issues.extend(_clk_completeness(directives, db))
        issues.extend(_routing_completeness(directives, db))
        if not has_errors(issues):
            issues.extend(_resolved_issues(directives, db))
        issues.extend(_ready_dependencies(directives))
    return issues


def _semantic_issues(i: int, d: Directive, db: Any) -> list[Issue]:
    out: list[Issue] = []
    try:
        if d.kind == "clk_enable":
            db.clk_enable(d.periph)
        elif d.kind in ("enable_bit", "check_ready"):
            info = db.field(d.peri, d.reg, d.field)
            if d.instance and d.instance.upper() not in {k.upper() for k in info.get("addresses", {})}:
                out.append(Issue(i, "error", f"unknown instance {d.instance!r} for {d.peri}.{d.reg}"))
            elif d.kind == "enable_bit" and not _writable(info, 1 if d.value is None else d.value):
                out.append(Issue(i, "error", f"{d.peri}.{d.reg}.{d.field} is not writable ({info.get('access', 'UNKNOWN')})"))
            if d.kind == 'enable_bit' and d.value is not None and (type(d.value) is not int or not 0 <= d.value < (1 << info['width'])):
                out.append(Issue(i, 'error', f'value {d.value} exceeds {d.field} width'))
            if d.kind == 'check_ready' and str(info.get('access', '')).upper() in {'', 'W', 'WO'}:
                out.append(Issue(i, 'error', 'comparison requires confirmed readable access'))
        elif d.kind == "field_value":
            info = db.field(d.peri, d.reg, d.field)
            access = str(info.get("access", "")).upper()
            if not _writable(info, d.value):
                out.append(Issue(i, "error",
                                 f"{d.peri}.{d.reg}.{d.field} is not writable ({access or 'UNKNOWN'})"))
            elif d.value is not None and not 0 <= d.value < (1 << info["width"]):
                out.append(Issue(i, "error",
                                 f"value {d.value} exceeds {d.field} "
                                 f"width {info['width']}"))
            else:
                sem = info.get("sem") or {}
                if sem and d.value is not None:
                    key = format(d.value, f"0{info['width']}b")
                    if key not in sem and str(d.value) not in sem:
                        out.append(Issue(i, "warning",
                                         f"value {d.value} not a documented "
                                         f"{d.field} encoding (sem table)"))
        elif d.kind == "field_symbol":
            pls = [p for p in db.encode(d.symbol)
                   if not d.reg or p.register.upper() == d.reg.upper()]
            if not pls:
                out.append(Issue(i, "error",
                                 f"symbol {d.symbol!r} not found in L1"
                                 + (f" for {d.reg}" if d.reg else "")))
        elif d.kind == "pin_config":
            if db.pin_af(d.pin, d.func) is None:
                out.append(Issue(i, "error",
                                 f"{d.pin} has no AF for {d.func!r}"))
        elif d.kind == "write_reg":
            db.register_fields(d.peri, d.reg)        # KB knows the register
            if d.value is not None and not 0 <= d.value <= 0xFFFFFFFF:
                out.append(Issue(i, "error",
                                 f"value {d.value} out of 32-bit range"))
            elif (d.peri.upper() == "GPIOA" or (d.peri.upper() == "GPIO" and d.instance.upper() == "GPIOA")) and d.reg.upper() == "MODER":
                out.append(Issue(i, "error",
                                 "raw GPIOA.MODER write can alter protected SWD pins PA13/PA14"))
            else:
                access = {str(db.field(d.peri, d.reg, f).get("access", "")).upper()
                          for f in db.register_fields(d.peri, d.reg)}
                if access not in ({"W"}, {"RW"}):
                    out.append(Issue(i, "error",
                                     f"raw {d.peri}.{d.reg} access is unconfirmed or special: {sorted(access)}"))
        elif d.kind == "wait" and (d.us is None or d.us < 0):
            out.append(Issue(i, "error", "wait duration must be non-negative"))
        elif d.kind == "analog_pin":
            ana = db.pin_analog(d.pin)               # pin exists; has analog role?
            if not any(ana.values()):
                out.append(Issue(i, "warning",
                                 f"{d.pin} 在 iomux 没有模拟功能(analog 块全空)"))
    except (KeyError, ValueError) as e:
        out.append(Issue(i, "error", f"{d.kind}: {e}"))
    return out


def _resolved_issues(directives: list[Directive], db: Any) -> list[Issue]:
    """Validate actual resolver output so symbols, aliases and injected GPIO agree.

    Resolver calls are pure; they never aggregate or recursively validate.
    Reject boundaries the legacy aggregator cannot preserve instead of merging them.
    """
    from .composer import Composer
    compiler = Composer(db.chip, db=db)
    seen, stages, raw_addresses = {}, {}, set()
    segment, out = 0, []
    gpio_addresses = {compiler._reg_addr('GPIOA', reg) for reg in ('MODER', 'OTYPER', 'OSPEEDR', 'PUPDR', 'ODR', 'BSRR', 'AFRL', 'AFRH')}
    for i, directive in enumerate(directives, 1):
        try:
            writes, rows = compiler._resolve(directive, i)
            for write in writes:
                if type(write.value) is not int or not 0 <= write.value < (1 << write.width):
                    raise ValueError(f'value outside {write.width}-bit field')
                fields = [db.field(write.peri, write.reg, name) for name in db.register_fields(write.peri, write.reg)]
                matches = [info for info in fields if info['pos'] == write.pos and info['width'] == write.width]
                if len(matches) == 1 and not matches[0].get('access'):
                    matches[0] = dict(matches[0], access=db.reviewed_access(write.addr, write.pos, write.width))
                if len(matches) != 1 or not _writable(matches[0], write.value):
                    raise ValueError(f'{write.peri}.{write.reg} field access is not writable or unconfirmed')
                if write.addr in gpio_addresses:
                    name = matches[0]['field']
                    if re.search(r'(?:13|14)$', name):
                        raise ValueError('write touches protected SWD pins PA13/PA14')
                stage = (segment, write.phase)
                if write.addr in raw_addresses or (write.addr in stages and stages[write.addr] != stage):
                    raise ValueError('register writes cross an unsupported sequence/phase boundary')
                stages[write.addr] = stage
                mask = ((1 << write.width) - 1) << write.pos
                value = write.value << write.pos
                old_mask, old_value = seen.get(write.addr, (0, 0))
                if (old_value ^ value) & old_mask & mask:
                    raise ValueError('conflicting writes to the same resolved field')
                seen[write.addr] = (old_mask | mask, (old_value & ~mask) | value)
            for row in rows:
                if row.type == 'W':
                    if row.addr in gpio_addresses:
                        raise ValueError('raw write touches protected SWD GPIO port')
                    if row.addr in stages:
                        raise ValueError('raw and field writes share an unsupported sequence boundary')
                    raw_addresses.add(row.addr)
            if rows:
                segment += 1
        except (KeyError, ValueError, TypeError) as error:
            out.append(Issue(i, 'error', str(error), 'resolved_semantics'))
    return out


def _ready_dependencies(directives: list[Directive]) -> list[Issue]:
    """Known peripheral-ready checks need their enable write before the read."""
    out: list[Issue] = []
    for i, d in enumerate(directives, 1):
        if not (d.kind == "check_ready" and re.fullmatch(r'ADC[12]?', d.peri.upper()) and d.field.upper() == "ADRDY"):
            continue
        instance = d.instance.upper() or (d.peri.upper() if d.peri.upper() != 'ADC' else 'ADC1')
        enabled = any(prev.kind in {"enable_bit", "field_value"} and re.fullmatch(r'ADC[12]?', prev.peri.upper())
                      and (prev.value == 1 or prev.kind == 'enable_bit' and prev.value is None)
                      and (prev.instance.upper() or (prev.peri.upper() if prev.peri.upper() != 'ADC' else 'ADC1')) == instance
                      and prev.reg.upper() == "CR" and prev.field.upper() == "ADEN"
                      for prev in directives[:i - 1])
        if not enabled:
            out.append(Issue(i, "error", "ADC ADRDY requires a preceding ADCx.CR.ADEN"))
    return out


def has_errors(issues: list[Issue]) -> bool:
    return any(x.level == "error" for x in issues)


def validate_request(data: dict, db: Any = None
                     ) -> tuple[Optional[ComposeRequest], list[Issue]]:
    """End-to-end entry for an LLM-emitted request JSON: parse + validate.

    Returns (request, issues). `request` is None only on a malformed envelope;
    semantic errors still return the request so the caller can inspect it.
    Build a default EncodingDB from the request's chip if `db` is omitted.
    """
    if not isinstance(data, dict):
        return None, [Issue(-1, "error", "request must be a JSON object")]
    try:
        req = request_from_json(data)
    except (ValueError, TypeError) as e:
        return None, [Issue(-1, "error", f"malformed request: {e}")]
    if db is None:
        from .encoding import EncodingDB
        db = EncodingDB(req.chip)
    if req.chip != db.chip or req.chip != 'py32f420':
        return req, [Issue(-1, 'error', 'request chip does not match the supported knowledge snapshot')]
    issues = validate(req.directives, db)
    if not req.directives:
        issues.append(Issue(-1, 'error', 'request must contain at least one directive'))
    if set(data) - {'name', 'chip', 'directives'}:
        issues.append(Issue(-1, 'error', 'unknown request properties'))
    for j, raw in enumerate(data.get("directives", []), 1):
        if isinstance(raw, dict):
            unknown = set(raw) - DIRECTIVE_FIELDS
            if unknown:
                issues.append(Issue(j, "error",
                                    f"unknown fields ignored: {sorted(unknown)}"))
    return req, issues
