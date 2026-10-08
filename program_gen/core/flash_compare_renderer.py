"""Pure Chroma/S100 renderer for immutable Flash compare plans."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

from program_gen.core.flash_compare_plan import (
    DataKind,
    FlashComparePatternPlan,
    FlashHardwareFacts,
    Operation,
    Scope,
    serialize_command_groups,
)


@dataclass(frozen=True)
class FlashCompareArtifact:
    pattern_name: str
    relative_path: str
    content: bytes
    source_identity: str


@dataclass(frozen=True)
class FlashCompareGenerationResult:
    platform: str
    plan_identity: str
    artifacts: tuple[FlashCompareArtifact, ...]


def render_flash_compare_plan(
    plan: FlashComparePatternPlan, platform: str
) -> FlashCompareGenerationResult:
    """Render without workbook, global state, filesystem or GUI access."""
    if not isinstance(plan, FlashComparePatternPlan):
        raise TypeError("renderer expects FlashComparePatternPlan")
    platform = str(platform).strip().casefold()
    if platform not in ("chroma", "s100"):
        raise ValueError("platform must be chroma or s100")
    hardware = plan.facts.hardware
    if not isinstance(hardware, FlashHardwareFacts):
        raise ValueError("plan facts do not contain compiled FlashHardwareFacts")
    renderer = FlashPageExecutionRenderer(plan, platform, hardware)
    content = renderer.render().encode("ascii")
    extension = ".pat" if platform == "chroma" else ".sd"
    relative = (
        f"pat/{plan.output_identity}{extension}"
        if platform == "chroma"
        else f"{plan.output_identity}{extension}"
    )
    digest = hashlib.sha256(content).hexdigest().upper()
    artifact = FlashCompareArtifact(
        pattern_name=plan.output_identity,
        relative_path=relative,
        content=content,
        source_identity=f"flash-compare:{plan.identity}:{platform}:sha256:{digest}",
    )
    return FlashCompareGenerationResult(platform, plan.identity, (artifact,))


def render_flash_compare_plans(
    plans, platform: str
) -> FlashCompareGenerationResult:
    """Render an ordered plan set and return one immutable artifact bundle."""
    artifacts = []
    identities = set()
    plan_ids = []
    normalized_platform = str(platform).strip().casefold()
    for plan in plans:
        if plan.output_identity in identities:
            raise ValueError(f"duplicate Flash output identity: {plan.output_identity!r}")
        identities.add(plan.output_identity)
        result = render_flash_compare_plan(plan, normalized_platform)
        artifacts.extend(result.artifacts)
        plan_ids.append(plan.identity)
    bundle_identity = hashlib.sha256("\n".join(plan_ids).encode("ascii")).hexdigest().upper()
    return FlashCompareGenerationResult(
        normalized_platform, bundle_identity, tuple(artifacts)
    )


class FlashPageExecutionRenderer:
    """Shared Page/Bulk hardware execution engine used by Flash renderers."""
    def __init__(self, plan, platform, hardware):
        self.plan = plan
        self.platform = platform
        self.hardware = hardware
        self.values = {
            field.name: "0" * field.bit_width
            for register in hardware.registers
            for field in register.fields
        }
        self.last_bank_en = None
        self.last_bank_config = None
        self._validate_register_contract()

    def render(self):
        out = [self._head()]
        if self.platform == "chroma":
            out.append(self._v("011", self._ts("normal")) + "\n")
        out.append(self._v("011", "RPT 1000;") + "\n")
        if self.plan.scope is Scope.BULK and self.plan.operation is Operation.ERASE:
            out.append(self._v("111", "RPT 2;") + "\n")
        for pass_index, item in enumerate(self.plan.passes):
            if self.plan.operation is Operation.ERASE:
                out.append(self._erase(item))
            elif self.plan.operation is Operation.PROGRAM:
                out.append(self._program(item))
            elif self.plan.operation is Operation.READ:
                out.append(self._read(item, pass_index=pass_index))
            elif self.plan.operation is Operation.REPAIR:
                out.append(self._repair(item))
            elif self.plan.operation is Operation.EPR:
                self._reset_bank_cache()
                out.append(self._erase(item))
                self._reset_bank_cache()
                out.append(self._program(item))
                self._reset_bank_cache()
                out.append(self._read(item, pass_index=pass_index))
            else:
                raise ValueError(f"unsupported operation: {self.plan.operation.value}")
        if self.plan.operation is not Operation.READ:
            out.append(self._v("101") + "\n")
        out.append(self._tail())
        return "".join(out)

    def _erase(self, item):
        bulk = self.plan.scope is Scope.BULK
        red = "1" if bulk else "0"
        program_mode = (
            self.hardware.modes.program_bulk_all if bulk else self.hardware.modes.program_page
        )
        erase_mode = self.hardware.modes.erase_bulk if bulk else self.hardware.modes.erase_page
        return "".join((
            self._mode(self.hardware.modes.normal),
            self._bank(item.bank_bits, self.hardware.opr.pre, red, enable_first=True),
            self._address(item.axa, item.ra),
            self._mode(self.hardware.modes.pep),
            self._seq(program_mode, "pre"),
            self._bank(item.bank_bits, self.hardware.opr.erase, red, enable_first=True),
            self._seq(erase_mode, "erase"),
            self._mode(self.hardware.modes.clear_latches),
            self._mode_handshake(self.hardware.modes.normal, 11),
            self._mode(self.hardware.modes.normal),
        ))

    def _program(self, item):
        bulk = self.plan.scope is Scope.BULK
        all_pages = bulk and len(self.plan.passes) == self.plan.facts.bank_count
        red = "1" if all_pages else "0"
        if not bulk:
            program_mode = self.hardware.modes.program_page
        elif all_pages:
            program_mode = self.hardware.modes.program_bulk_all
        else:
            program_mode = self.hardware.modes.program_bulk_even_odd
        return "".join((
            self._bank(item.bank_bits, self.hardware.opr.program, red),
            self._mode(self.hardware.modes.normal),
            self._address(item.axa, item.ra),
            self._bank(item.bank_bits, self.hardware.opr.program, red),
            self._mode(self.hardware.modes.clear_latches),
            self._mode_handshake(self.hardware.modes.normal, 11),
            self._mode(self.hardware.modes.normal),
            self._mode(self.hardware.modes.write_latches),
            self._write_latch_handshake(),
            self._program_groups(item.data),
            self._bank(item.bank_bits, self.hardware.opr.program, red),
            self._seq(program_mode, "program"),
            self._mode(self.hardware.modes.normal),
        ))

    def _read(self, item, pass_index):
        page = self.plan.scope is Scope.PAGE
        kind = item.data.kind
        comp_mode, comp_data = _compare_config(kind)
        compare_number = 0 if page else item.compare_number
        command = "1000" if page else "1101"
        out = []
        if page:
            out.append(self._mode(self.hardware.modes.normal))
        else:
            if pass_index:
                out.append(self._v("011", "RPT 100;") + "\n")
            out.append(self._v("111", "RPT 10;") + "\n")
        out.extend([
            self._bank(item.bank_bits, self.hardware.opr.pre, "0"),
            self._address(item.axa, item.ra),
            self._write({
                "READ_MODE": "1" if page else "0",
                "ADDR_MODE": "0",
                "COMP_MODE": "0" if page else comp_mode,
                "COMP_DATA": "0" if page else comp_data,
                "COMPARE_NUMBER": format(compare_number, "b"),
            }),
        ])
        if not page:
            out.append(self._mode(self.hardware.modes.normal))
        out.append(self._command(command))
        if page:
            out.append(self._read_groups(item.data))
        else:
            out.append(self._v("1L1", f"RPT {compare_number * 2};") + "\n")
            out.append(self._compare_flag(read_close=True))
        return "".join(out)

    def _repair(self, item):
        comp_mode, comp_data = _compare_config(item.data.kind)
        out = []
        if item.logical_bank:
            out.append(self._v("111", "RPT 2;") + "\n")
        out.extend((
            self._mode(self.hardware.modes.normal),
            self._bank(item.bank_bits, self.hardware.opr.pre, "1"),
            self._address(item.axa, item.ra),
            self._write({
                "READ_MODE": "0",
                "ADDR_MODE": "0",
                "COMP_MODE": comp_mode,
                "COMP_DATA": comp_data,
                "COMPARE_NUMBER": format(item.compare_number, "b"),
            }),
            self._repair_command(),
            self._v("1L1", f"RPT {item.compare_number * 2};") + "\n",
            self._compare_flag(read_close=False),
        ))
        return "".join(out)

    def _repair_command(self):
        return "".join((
            self._v("100") + "\n",
            self._v("111") + "\n",
            self._v("111") + "// Cmd[3:0]=1010 repair mode\n",
            self._v("101") + "\n",
            self._v("111") + "\n",
            self._v("101") + "\n",
            self._v("1X1") + "\n",
        ))

    def _program_groups(self, data):
        groups = serialize_command_groups(data, self.plan.facts, self.plan.facts.program_bits)
        out = []
        for bits in groups:
            out.extend((
                self._v("111") + "\n",
                self._v("110") + "// 1 bit strobe\n",
                self._v("111", "RPT 2;") + "// Cmd[3:0]=1001 write data\n",
                self._v("101", "RPT 2;") + "\n",
                self._v("111") + "\n",
            ))
            if self.plan.ecc_cycles:
                out.append(self._v("101", f"RPT {self.plan.ecc_cycles};") + "// ECC program\n")
            out.append(self._serial_bits(bits))
            out.append(self._v("1" + bits[-1] + "1") + "\n")
        return "".join(out)

    def _read_groups(self, data):
        groups = serialize_command_groups(data, self.plan.facts, self.plan.facts.read_bits)
        out = []
        for bits in groups:
            out.extend((self._v("111") + "\n", self._v("1L1") + "\n"))
            if self.plan.ecc_cycles:
                out.append(self._v("1X1", f"RPT {self.plan.ecc_cycles};") + "// ECC read\n")
            expected = "".join("H" if bit == "1" else "L" for bit in bits)
            out.append(self._serial_words(expected))
        return "".join(out)

    def _command(self, bits):
        if bits == "1000":
            return "".join((
                self._v("100") + "\n",
                self._v("111", "RPT 2;// Cmd[3:0]=1000 read mode") + "\n",
                self._v("101", "RPT 3;") + "\n",
                self._v("1X1") + "\n",
            ))
        if bits == "1101":
            return "".join((
                self._v("100") + "\n",
                self._v("111", "RPT 3;// Cmd[3:0]=1101 read compare mode") + "\n",
                self._v("101") + "\n", self._v("111") + "\n",
                self._v("1X1") + "\n",
            ))
        out = [self._v("100") + "\n"]
        for index, bit in enumerate(bits):
            comment = f"// Cmd[3:0]={bits}\n" if index == 0 else "\n"
            out.append(self._v("1" + bit + "1") + comment)
        out.append(self._v("1X1") + "\n")
        return "".join(out)

    def _seq(self, mode, role):
        waits = {
            "pre": (79, 24, 1000, 350, 19, 54),
            "erase": (79, 24, 12500, 350, 19, 54),
            "program": (79, 24, 7500, 350, 19, 54),
        }[role]
        seq = ("01", "10", "10", "10", "11", "00")
        pe = ("0", "0", "1", "0", "0", "0")
        out = []
        for index in range(6):
            out.append(self._write({"PE": pe[index], "SEQ": seq[index], "MODE": mode}))
            m = "1" + mode[-1] + "1"
            if index in (0, 1, 4, 5):
                out.extend((
                    self._v(m) + "\n", self._v("110") + "\n",
                    self._v("111", "RPT 2;") + "\n",
                    self._v("101", f"RPT {waits[index]};") + "\n",
                ))
            elif index == 3:
                out.extend((self._v(m) + "\n", self._v("111", f"RPT {waits[index]};") + "\n"))
            elif role == "pre":
                out.extend((self._v(m) + "\n", self._v(m, f"RPT {waits[index]};") + "\n"))
            else:
                timing = self._ts("erase" if role == "erase" else "program")
                boundary = self.plan.operation_boundary_label
                first = (
                    self._label_v(boundary, m)
                    if boundary and self.plan.operation.value == role
                    else self._v(m)
                )
                out.extend((
                    first + "\n", self._v(m, timing) + "\n",
                    self._v(m, f"RPT {waits[index]};") + "\n",
                    self._v(m, self._ts("normal")) + "\n",
                ))
        out.extend((
            self._mode(self.hardware.modes.normal),
            self._mode_handshake(self.hardware.modes.normal, 2, read_ack=True),
        ))
        return "".join(out)

    def _mode(self, mode):
        return self._write({"PE": "0", "SEQ": "00", "MODE": mode})

    def _address(self, axa, ra):
        return self._write({"AXA": str(axa), "CA": "0", "PA": "0", "RA": format(ra, "b")})

    def _bank(self, bank_bits, opr, red, enable_first=False):
        bank_enable = ""
        if bank_bits != self.last_bank_en:
            bank_enable = self._write({"BANK_EN": bank_bits})
            self.last_bank_en = bank_bits
        config_values = (bank_bits, opr, red)
        config = ""
        if config_values != self.last_bank_config:
            config = self._write({
                "BANK_SEL": bank_bits,
                "OPR_SEL": opr,
                "RED0_EN": red,
                "RED1_EN": red,
                "RED2_EN": red,
                "RED3_EN": red,
            })
            self.last_bank_config = config_values
        return bank_enable + config if enable_first else config + bank_enable

    def _mode_handshake(self, mode, repeat, read_ack=False):
        out = (
            self._v("1" + mode[-1] + "1") + "\n"
            + self._v("110") + "\n"
            + self._v("111", f"RPT {repeat};") + "\n"
        )
        if read_ack:
            out += self._v("101", "RPT 3;") + "\n" + self._v("1X1") + "\n"
        return out

    def _write_latch_handshake(self):
        mode = self.hardware.modes.write_latches
        return "".join((
            self._v("1" + mode[-1] + "1") + "\n",
            self._v("100") + "\n",
            self._v("111", "RPT 2;") + "\n",
            self._v("101", "RPT 4;") + "\n",
        ))

    def _write(self, updates):
        unknown = set(updates) - self.values.keys()
        # Optional fields differ between product revisions; only BANK_EN may be
        # absent on a legacy single-bank contract.
        if unknown - {"BANK_EN"}:
            raise ValueError("Flash register contract lacks fields: " + ", ".join(sorted(unknown)))
        updates = {name: value for name, value in updates.items() if name in self.values}
        self.values.update({
            name: _fit_bits(value, len(self.values[name]), name)
            for name, value in updates.items()
        })
        out = []
        for register in self.hardware.registers:
            if not any(field.name in updates for field in register.fields):
                continue
            value = 0
            comments = []
            for field in register.fields:
                bits = self.values[field.name]
                value |= int(bits, 2) << field.bit_offset
                if field.name in updates:
                    comments.append(f"{field.name}={bits}")
            out.extend((
                self._v("110") + "// 1 bit strobe\n",
                self._v("111") + "// write FLASH_EPR register\n",
                self._fold(register.addr_bits, "addr") + "\n",
                self._fold(format(value, "016b"), ", ".join(comments)) + "\n",
            ))
        return "".join(out)

    def _fold(self, bits, comment):
        lines = []
        for bit, count in _runs(bits):
            command = f"RPT {count};" if count > 1 else ""
            line = self._v("1" + bit + "1", command)
            if not lines:
                line += "// " + comment
            lines.append(line)
        if len(bits) == 16:
            lines.append(self._v("1" + bits[-1] + "1"))
        return "\n".join(lines)

    def _serial_bits(self, bits):
        return "".join(
            self._v("1" + bit + "1", f"RPT {count};") + "\n"
            for bit, count in _runs(bits)
        )

    def _serial_words(self, bits):
        return "".join(
            self._serial_bits(bits[index:index + 32])
            for index in range(0, len(bits), 32)
        )

    def _reset_bank_cache(self):
        self.last_bank_en = None
        self.last_bank_config = None

    def _compare_flag(self, read_close):
        if not self.plan.comp_flag_bits:
            return ""
        out = "".join(
            self._v("1" + ("H" if bit == "1" else "L") + "1") + "\n"
            for bit in self.plan.comp_flag_bits
        )
        if read_close:
            out += "".join((
                self._v("1L1") + "\n", self._v("1L1") + "\n",
                self._v("1X0") + "\n", self._v("111", "RPT 3;") + "\n",
                self._v("111") + "\n", self._v("111") + "\n",
            ))
        else:
            out += (self._v("1X1") + "\n") * 3
        return out

    def _v(self, bits, command=""):
        if self.platform == "chroma":
            return "      *" + bits + "*" + (command or ";")
        return "      " + bits + ";" + command

    def _label_v(self, label, bits):
        if self.platform == "chroma":
            return f" {label}:\n" + self._v(bits)
        return f" {label}:{bits};"

    def _ts(self, kind):
        if self.platform == "chroma":
            return {"normal": "TS1;", "erase": "TS5;", "program": "TS6;"}[kind]
        return {
            "normal": "TIMING_SET G1_1;",
            "erase": "TIMING_SET G1_4;",
            "program": "TIMING_SET G1_5;",
        }[kind]

    def _head(self):
        pins = f"{self.hardware.clk_pin}, {self.hardware.swd_pin}, NRST;"
        if self.platform == "chroma":
            return (
                'SET_DEC_FILE "pin.dec"\n\nHEADER\n\n' + pins
                + f"\n\nSPM_PATTERN({self.plan.output_identity}) {{\n\n"
            )
        return "HEAD[PIN_NAME]:\n\n" + pins + "\n\nEND_HEAD;\n\n@@PATTERN_DEFINE\n\nSTART:011;\n"

    def _tail(self):
        if self.platform == "chroma":
            return "      *011*STOP;\n\n}"
        return "END:011;\n\n@@END_PATTERN_DEFINE "

    def _validate_register_contract(self):
        required = {
            "RA", "AXA", "CA", "PA", "PE", "SEQ", "MODE", "READ_MODE",
            "ADDR_MODE", "COMP_MODE", "COMP_DATA", "COMPARE_NUMBER",
            "RED0_EN", "RED1_EN", "RED2_EN", "RED3_EN", "OPR_SEL", "BANK_SEL",
        }
        missing = required - self.values.keys()
        if missing:
            raise ValueError("Flash register contract lacks fields: " + ", ".join(sorted(missing)))


def _fit_bits(value, width, name):
    text = str(value).strip()
    if not text or any(bit not in "01" for bit in text):
        raise ValueError(f"{name} is not a binary value: {value!r}")
    if len(text) > width:
        raise ValueError(f"{name} value {text!r} exceeds {width} bits")
    return text.zfill(width)


def _compare_config(kind):
    return {
        DataKind.ZERO: ("0", "00000000"),
        DataKind.ONE: ("0", "11111111"),
        DataKind.PCKB: ("1", "11111111"),
        DataKind.NCKB: ("1", "00000000"),
        DataKind.CUSTOM: ("0", "00000000"),
    }[kind]


def _runs(bits):
    start = 0
    for index in range(1, len(bits) + 1):
        if index == len(bits) or bits[index] != bits[start]:
            yield bits[start], index - start
            start = index


__all__ = [
    "FlashCompareArtifact", "FlashCompareGenerationResult", "FlashPageExecutionRenderer",
    "render_flash_compare_plan", "render_flash_compare_plans",
]
