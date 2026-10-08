"""Pure dual-platform renderer for compiled Flash Label plans."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

from program_gen.core.flash_compare_plan import (
    DataKind, FlashComparePass, FlashComparePatternPlan, Operation, PageData, Scope,
)
from program_gen.core.flash_compare_renderer import FlashPageExecutionRenderer
from program_gen.core.flash_label_plan import (
    FlashLabelGenerationPlan, FlashLabelPagePlan, FlashLabelSpan, FlashLabelWordPlan,
)


@dataclass(frozen=True, slots=True)
class FlashLabelArtifact:
    pattern_name: str
    relative_path: str
    content: bytes
    source_identity: str


@dataclass(frozen=True, slots=True)
class FlashLabelGenerationResult:
    platform: str
    plan_identity: str
    artifacts: tuple[FlashLabelArtifact, ...]


def render_flash_label_plan(
    plan: FlashLabelGenerationPlan, platform: str
) -> FlashLabelGenerationResult:
    if not isinstance(plan, FlashLabelGenerationPlan):
        raise TypeError("renderer expects FlashLabelGenerationPlan")
    platform = str(platform).strip().casefold()
    if platform not in ("chroma", "s100"):
        raise ValueError("platform must be chroma or s100")
    artifacts = []
    uid_page = next(page for page in plan.pages if page.name.casefold() == "uid")
    for page in plan.pages:
        artifacts.append(_render_artifact(
            plan, page, platform, "erase", page.names.erase_pattern
        ))
        if page.names.program_pattern is not None:
            artifacts.append(_render_artifact(
                plan, page, platform, "program", page.names.program_pattern
            ))
        if page.names.read_pattern is not None:
            artifacts.append(_render_artifact(
                plan, page, platform, "read", page.names.read_pattern
            ))
        if page.names.capture_pattern is not None:
            artifacts.append(_render_artifact(
                plan, page, platform, "capture", page.names.capture_pattern
            ))
    for variant in plan.uid_variants:
        page = _override_page(
            uid_page, variant.word_overrides, variant.identity_labels
        )
        if variant.names.program_pattern is not None:
            artifacts.append(_render_artifact(
                plan, page, platform, "program", variant.names.program_pattern
            ))
        if variant.names.read_pattern is not None:
            artifacts.append(_render_artifact(
                plan, page, platform, "read", variant.names.read_pattern
            ))
        if variant.names.check_pattern is not None:
            artifacts.append(_render_artifact(
                plan, page, platform, "check", variant.names.check_pattern,
                check_mask=variant.check_mask,
            ))
    names = [artifact.pattern_name for artifact in artifacts]
    if len(names) != len(set(names)):
        raise ValueError("duplicate Flash Label output identity")
    return FlashLabelGenerationResult(platform, plan.identity, tuple(artifacts))


def _render_artifact(plan, page, platform, role, name, check_mask=None):
    operation = {
        "erase": Operation.ERASE,
        "program": Operation.PROGRAM,
        "read": Operation.READ,
        "capture": Operation.READ,
        "check": Operation.READ,
    }[role]
    payload = b"".join(word.value.to_bytes(4, "big") for word in page.words)
    data = None if operation is Operation.ERASE else PageData(DataKind.CUSTOM, payload)
    item = FlashComparePass(
        logical_bank=0, bank_bits="01", axa=1, ra=page.ra,
        stages=(role,), data=data,
    )
    execution = FlashComparePatternPlan(
        output_identity=name,
        facts=plan.facts,
        scope=Scope.PAGE,
        operation=operation,
        passes=(item,),
        program_groups_per_page=plan.facts.page_bytes * 8 // plan.facts.program_bits,
        read_groups_per_page=plan.facts.page_bytes * 8 // plan.facts.read_bits,
        ecc_cycles=plan.facts.ecc_cycles,
        comp_flag_bits="",
    )
    renderer = _FlashLabelRenderer(
        execution, platform, plan.facts.hardware, page, role, check_mask
    )
    content = renderer.render().encode("ascii")
    extension = ".pat" if platform == "chroma" else ".sd"
    relative = f"pat/{name}{extension}" if platform == "chroma" else f"{name}{extension}"
    digest = hashlib.sha256(content).hexdigest().upper()
    return FlashLabelArtifact(
        name, relative, content,
        f"flash-label:{plan.identity}:{name}:{platform}:sha256:{digest}",
    )


class _FlashLabelRenderer(FlashPageExecutionRenderer):
    def __init__(self, plan, platform, hardware, page, role, check_mask):
        super().__init__(plan, platform, hardware)
        self.page = page
        self.role = role
        self.check_mask = check_mask
        self.trigger = role in ("program", "read", "capture") and page.has_labels
        self.vector_column = _s100_vector_column(page, role) if platform == "s100" else 6

    def _head(self):
        pins = f"{self.hardware.clk_pin}, {self.hardware.swd_pin}, NRST"
        if self.platform == "chroma":
            return (
                'SET_DEC_FILE "pin.dec"\n\nHEADER\n\n' + pins
                + f";\n\nSPM_PATTERN({self.plan.output_identity}) {{\n\n"
            )
        if self.trigger:
            pins += ", TRIGPIN"
        start = "START:"
        return (
            "HEAD[PIN_NAME]:\n\n" + pins + ";\n\nEND_HEAD;\n\n@@PATTERN_DEFINE\n\n"
            + " " * (self.vector_column - len(start))
            + start + "011" + ("1" if self.trigger else "") + ";\n"
        )

    def _v(self, bits, command="", *, trigger=1):
        if self.platform == "chroma":
            return "      *" + bits + "*" + (command or ";")
        suffix = str(trigger) if self.trigger else ""
        return " " * self.vector_column + bits + suffix + ";" + command

    def _tail(self):
        if self.platform == "chroma":
            return super()._tail()
        suffix = "1" if self.trigger else ""
        end = "END:"
        return (
            " " * (self.vector_column - len(end))
            + f"{end}011{suffix};\n\n@@END_PATTERN_DEFINE "
        )

    def _program_groups(self, data):
        out = []
        for group in _word_groups(self.page.words, self.plan.facts.program_bits):
            out.extend((
                self._v("111") + "\n", self._v("110") + "// 1 bit strobe\n",
                self._v("111", "RPT 2;") + "// Cmd[3:0]=1001 write data\n",
                self._v("101", "RPT 2;") + "\n", self._v("111") + "\n",
            ))
            if self.plan.ecc_cycles:
                out.append(self._v("101", f"RPT {self.plan.ecc_cycles};") + "// ECC program\n")
            out.append(self._emit_group(group, "program"))
        return "".join(out)

    def _read_groups(self, data):
        out = []
        for group in _word_groups(self.page.words, self.plan.facts.read_bits):
            out.extend((self._v("111") + "\n", self._v("1L1") + "\n"))
            if self.plan.ecc_cycles:
                out.append(self._v("1X1", f"RPT {self.plan.ecc_cycles};") + "// ECC read\n")
            out.append(self._emit_group(group, self.role))
        return "".join(out)

    def _emit_group(self, words, role):
        out = []
        for word_index, word in words:
            bits = f"{word.value:032b}"
            labels = {span.msb_index: span for span in word.labels}
            endings = {span.msb_index + span.width - 1: span for span in word.labels}
            for index, bit in enumerate(bits):
                span = labels.get(index)
                end = endings.get(index)
                if role == "program":
                    symbol = bit
                elif role == "read":
                    symbol = "H" if bit == "1" else "L"
                elif role == "capture":
                    if _covered(word.labels, index):
                        symbol = "K" if self.platform == "chroma" else "L"
                    else:
                        symbol = "X"
                elif role == "check":
                    keep = self.check_mask is not None and word_index == 5 and (
                        self.check_mask & (1 << (31 - index))
                    )
                    symbol = ("H" if bit == "1" else "L") if keep else "X"
                else:
                    raise ValueError(role)
                prefix = ""
                if span is not None and role in ("program", "read"):
                    label_range = span.write if role == "program" else span.read
                    prefix = (
                        label_range.chroma_start if self.platform == "chroma"
                        else label_range.s100_start
                    ) + ":"
                if (
                    end is not None
                    and role in ("program", "read")
                    and self.platform == "s100"
                ):
                    label_range = end.write if role == "program" else end.read
                    prefix = label_range.s100_end + ":"
                trigger = 0 if _covered(word.labels, index) and role in ("program", "read", "capture") else 1
                command = "PTN_TRIG;" if role == "capture" and trigger == 0 and self.platform == "s100" else ""
                line = self._v("1" + symbol + "1", command, trigger=trigger)
                if prefix:
                    if self.platform == "chroma":
                        line = "      " + prefix + "\n" + line
                    else:
                        line = " " * (self.vector_column - len(prefix)) + prefix + line.lstrip()
                if index == 0:
                    value = f"{word.value:08X}"
                    line += (
                        f" // ADDR_MAP {self.page.name} Word[{word_index:02d}] = "
                        f"32'h{value[:4]}_{value[4:]}"
                    )
                out.append(line + "\n")
        return "".join(out)


def _s100_vector_column(page, role):
    labels = ["START:", "END:"]
    if role in ("program", "read"):
        for word in page.words:
            for span in word.labels:
                label_range = span.write if role == "program" else span.read
                labels.extend((label_range.s100_start + ":", label_range.s100_end + ":"))
    return max(6, *(len(label) for label in labels))


def _word_groups(words, command_bits):
    count = command_bits // 32
    return tuple(
        tuple(reversed(tuple(enumerate(words[offset:offset + count], start=offset))))
        for offset in range(0, len(words), count)
    )


def _covered(spans, index):
    return any(span.msb_index <= index < span.msb_index + span.width for span in spans)


def _override_page(page, overrides, identity_labels=()):
    values = dict(overrides)
    labels = dict(identity_labels)
    words = tuple(
        FlashLabelWordPlan(
            values.get(index, word.value), word.data_type,
            word.labels + labels.get(index, ()),
        )
        for index, word in enumerate(page.words)
    )
    return FlashLabelPagePlan(page.name, page.ra, words, page.names)


__all__ = [
    "FlashLabelArtifact", "FlashLabelGenerationResult", "render_flash_label_plan",
]
