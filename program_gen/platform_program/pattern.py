"""Reusable typed PatternProducer seam for complete platform programs."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Protocol

from program_gen.render_plan import ResourceRequest, ResourceRequirement


class PatternProducer(Protocol):
    def produce(self, requirement: ResourceRequirement) -> ResourceRequest:
        ...

    def write_region(self, pattern_name: str) -> "PatternWriteRegion":
        ...

    def timing_sets(self, requirements) -> tuple[str, ...]:
        ...


@dataclass(frozen=True, slots=True)
class PatternWriteRegion:
    base_label: str
    start_label: str
    end_label: str


class WorkspacePatternProducer:
    """Current adapter: select formal workspace input by typed relative path."""

    def __init__(self, platform_input_root: str | Path, *, _facts=None) -> None:
        self._root = Path(platform_input_root).resolve()
        self._facts = _facts

    def for_target(self, facts) -> "WorkspacePatternProducer":
        """Bind target facts used by compatibility projections at the adapter edge."""
        return WorkspacePatternProducer(self._root, _facts=facts)

    def produce(self, requirement: ResourceRequirement) -> ResourceRequest:
        filename = Path(requirement.relative_path).name
        source = self._root / "pat_temp" / filename
        if not source.is_file():
            if _is_firmware_download(requirement):
                return _firmware_download_stub(requirement, self._facts)
            if _is_adc_swd(requirement):
                return _adc_swd_stub(requirement, self._facts)
            if _is_dc_swd(requirement):
                return _dc_swd_stub(requirement, self._facts)
            if _is_vih_vil_swd(requirement):
                return _vih_vil_swd_stub(requirement, self._facts)
            if _is_freq_swd(requirement):
                return _freq_swd_stub(requirement, self._facts)
            if _is_opa_swd(requirement):
                return _opa_swd_stub(requirement, self._facts)
            if _is_dac_swd(requirement):
                return _dac_swd_stub(requirement, self._facts)
            if _is_sram_capture(requirement):
                return _sram_capture_stub(requirement, self._facts)
            raise ValueError(
                f"STN.PATTERN.MISSING: {requirement.logical_identity} -> {source}"
            )
        content = source.read_bytes()
        if (
            _is_firmware_download(requirement)
            and _is_legacy_firmware_stub(content)
        ):
            return _firmware_download_stub(requirement, self._facts)
        if _is_adc_swd(requirement) and _is_legacy_firmware_stub(content):
            return _adc_swd_stub(requirement, self._facts)
        if _is_vih_vil_swd(requirement) and _is_legacy_vih_vil_stub(content):
            return _vih_vil_swd_stub(requirement, self._facts)
        if _is_freq_swd(requirement) and _is_legacy_freq_stub(content):
            return _freq_swd_stub(requirement, self._facts)
        if _is_opa_swd(requirement) and _is_legacy_firmware_stub(content):
            return _opa_swd_stub(requirement, self._facts)
        if _is_dac_swd(requirement) and _is_legacy_firmware_stub(content):
            return _dac_swd_stub(requirement, self._facts)
        digest = hashlib.sha256(content).hexdigest().upper()
        content, projection = self._project_chroma_clock_header(content)
        return ResourceRequest(
            logical_identity=requirement.logical_identity,
            relative_path=requirement.relative_path,
            content=content,
            spec_identity=requirement.spec_identity,
            source_identity=(
                f"workspace-input:{filename}:sha256:{digest}{projection}"
            ),
            purpose=requirement.purpose,
        )

    def _project_chroma_clock_header(self, content: bytes) -> tuple[bytes, str]:
        facts = self._facts
        if facts is None or str(facts.platform).casefold() != "chroma":
            return content, ""
        clock = str(facts.clk_pin).strip()
        swd = str(facts.swd_pin).strip()
        legacy_clock = "PA14"
        if not clock or clock.casefold() == legacy_clock.casefold():
            return content, ""
        text = content.decode("gbk", errors="strict")
        pattern = re.compile(
            rf"(\bHEADER\s*\r?\n(?:[ \t]*\r?\n)?[ \t]*)"
            rf"{re.escape(legacy_clock)}"
            rf"([ \t]*,[ \t]*{re.escape(swd)}[ \t]*,[ \t]*NRST[ \t]*;)"
        )
        projected, count = pattern.subn(rf"\g<1>{clock}\g<2>", text)
        if count == 0:
            return content, ""
        return (
            projected.encode("gbk"),
            f":header-clock:{legacy_clock}->{clock}",
        )

    def write_region(self, pattern_name: str) -> PatternWriteRegion:
        suffix = ".pat" if (self._root / "pat_temp" / f"{pattern_name}.pat").is_file() else ".sd"
        source = self._root / "pat_temp" / f"{pattern_name}{suffix}"
        if not source.is_file():
            raise ValueError(f"STN.PATTERN.MISSING: write region -> {source}")
        text = source.read_text(encoding="gbk", errors="strict")
        if suffix == ".pat":
            bases = re.findall(
                r"^\s*([A-Za-z_][A-Za-z0-9_]*_data)\s*:", text, re.M
            )
            if len(bases) != 1:
                raise ValueError(
                    f"STN.PATTERN.WRITE_REGION: {pattern_name!r} has {len(bases)} base labels"
                )
            return PatternWriteRegion(bases[0], bases[0], bases[0])
        starts = re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*_data_st)\s*:", text, re.M)
        if len(starts) != 1:
            raise ValueError(
                f"STN.PATTERN.WRITE_REGION: {pattern_name!r} has {len(starts)} start labels"
            )
        start = starts[0]
        prefix = start[:-2]
        end = prefix + "sp"
        if not re.search(rf"^\s*{re.escape(end)}\s*:", text, re.M):
            raise ValueError(
                f"STN.PATTERN.WRITE_REGION: {pattern_name!r} lacks {end!r}"
            )
        return PatternWriteRegion(prefix[:-1], start, end)

    def timing_sets(self, requirements) -> tuple[str, ...]:
        names = set()
        for requirement in requirements:
            source = self._root / "pat_temp" / Path(requirement.relative_path).name
            if not source.is_file() and (
                _is_firmware_download(requirement)
                or _is_adc_swd(requirement)
                or _is_dc_swd(requirement)
                or _is_vih_vil_swd(requirement)
                or _is_freq_swd(requirement)
                or _is_opa_swd(requirement)
                or _is_dac_swd(requirement)
                or _is_sram_capture(requirement)
            ):
                continue
            content = source.read_bytes()
            if (
                _is_firmware_download(requirement)
                and _is_legacy_firmware_stub(content)
            ):
                continue
            if _is_freq_swd(requirement) and _is_legacy_freq_stub(content):
                continue
            text = content.decode("gbk", errors="strict")
            names.update(re.findall(r"\bTIMING_SET\s+(G\d+_\d+)\s*;", text))
        return tuple(sorted(names))


def _is_firmware_download(requirement: ResourceRequirement) -> bool:
    return str(requirement.purpose).strip().casefold().startswith(
        "firmware download"
    )


def _is_adc_swd(requirement: ResourceRequirement) -> bool:
    return str(requirement.purpose).strip().casefold().startswith("adc swd")


def _is_sram_capture(requirement: ResourceRequirement) -> bool:
    return str(requirement.purpose).strip().casefold().startswith("sram_capture")


def _is_dc_swd(requirement: ResourceRequirement) -> bool:
    return str(requirement.purpose).strip().casefold().startswith("dc swd")


def _is_vih_vil_swd(requirement: ResourceRequirement) -> bool:
    return str(requirement.purpose).strip().casefold().startswith("vih/vil swd")


def _is_freq_swd(requirement: ResourceRequirement) -> bool:
    return str(requirement.purpose).strip().casefold().startswith("freq swd")


def _is_opa_swd(requirement: ResourceRequirement) -> bool:
    return str(requirement.purpose).strip().casefold().startswith("opa swd")


def _is_dac_swd(requirement: ResourceRequirement) -> bool:
    return str(requirement.purpose).strip().casefold().startswith("dac swd")


def _is_legacy_firmware_stub(content: bytes) -> bool:
    return hashlib.sha256(content).hexdigest().upper() == (
        "6F775C23E44ACC0A74F046CFE88754E48D9F4E7ED94DC656F7FFBE6E4A23EB54"
    ) or b"placeholder stub" in content.lower()


def _is_legacy_vih_vil_stub(content: bytes) -> bool:
    lowered = content.lower()
    return _is_legacy_firmware_stub(content) or (
        b"wait 100us" in lowered and b"rpt 1000" in lowered
    )


def _is_legacy_freq_stub(content: bytes) -> bool:
    lowered = content.lower()
    return _is_legacy_firmware_stub(content) or b"no real freq configuration vector" in lowered


def _firmware_download_stub(requirement: ResourceRequirement, facts) -> ResourceRequest:
    platform = str(getattr(facts, "platform", "")).strip().casefold()
    pattern_name = Path(requirement.relative_path).stem
    clk_pin = str(getattr(facts, "clk_pin", "")).strip()
    swd_pin = str(getattr(facts, "swd_pin", "")).strip()
    if platform == "chroma" and clk_pin and swd_pin:
        content = (
            'SET_DEC_FILE "pin.dec"\n\nHEADER\n\n'
            f"{clk_pin}, {swd_pin}, NRST;\n\n"
            f"SPM_PATTERN({pattern_name}) {{\n\n"
            "  *011*TS1;\n"
            "  *011*RPT 100;\n"
            "  *111*;// STUB: no firmware download vector\n"
            "  *111*RPT 1000;// wait 100us\n"
            "  *011*STOP;\n"
            "}\n"
        ).encode("ascii")
    elif platform == "s100" and clk_pin and swd_pin:
        content = (
            "HEAD[PIN_NAME]:\n\n"
            f"{clk_pin}, {swd_pin}, NRST;\n\n"
            "END_HEAD;\n\n@@PATTERN_DEFINE\n\n"
            "START:011;\n"
            "      011;RPT 100;\n"
            "      111;// STUB: no firmware download vector\n"
            "      111;RPT 1000;// wait 100us\n"
            "  END:011;\n\n@@END_PATTERN_DEFINE\n"
        ).encode("ascii")
    else:
        raise ValueError(
            "FW.DOWNLOAD.STUB.FACTS_INVALID: firmware download fallback "
            "requires bound chroma/s100 platform facts with CLK and SWD pins"
        )
    digest = hashlib.sha256(content).hexdigest().upper()
    return ResourceRequest(
        logical_identity=requirement.logical_identity,
        relative_path=requirement.relative_path,
        content=content,
        spec_identity=requirement.spec_identity,
        source_identity=(
            f"generated:{platform}:firmware-download:STUB:sha256:{digest}"
        ),
        purpose=(
            "STUB firmware download Pattern; structural compile only, "
            "not real firmware coverage"
        ),
    )


def _adc_swd_stub(requirement: ResourceRequirement, facts) -> ResourceRequest:
    """Emit a compiler-valid placeholder until real ADC SWD vectors arrive."""
    platform = str(getattr(facts, "platform", "")).strip().casefold()
    pattern_name = Path(requirement.relative_path).stem
    clk_pin = str(getattr(facts, "clk_pin", "")).strip()
    swd_pin = str(getattr(facts, "swd_pin", "")).strip()
    if platform == "chroma" and clk_pin and swd_pin:
        content = (
            'SET_DEC_FILE "pin.dec"\n\nHEADER\n\n'
            f"{clk_pin}, {swd_pin}, NRST;\n\n"
            f"SPM_PATTERN({pattern_name}) {{\n\n"
            "  *011*TS1;\n"
            "  *011*RPT 100;\n"
            "  *111*;// STUB: no real ADC SWD vector\n"
            "  *111*RPT 400;\n"
            "  *011*STOP;\n"
            "}\n"
        ).encode("ascii")
    elif platform == "s100" and clk_pin and swd_pin:
        content = (
            "HEAD[PIN_NAME]:\n\n"
            f"{clk_pin}, {swd_pin}, NRST;\n\n"
            "END_HEAD;\n\n@@PATTERN_DEFINE\n\n"
            "START:011;\n"
            "      011;RPT 100;\n"
            "      111;// STUB: no real ADC SWD vector\n"
            "      111;RPT 400;\n"
            "  END:011;\n\n@@END_PATTERN_DEFINE\n"
        ).encode("ascii")
    else:
        raise ValueError(
            "ADC.SWD.STUB.FACTS_INVALID: placeholder requires bound "
            "chroma/s100 facts with CLK and SWD pins"
        )
    digest = hashlib.sha256(content).hexdigest().upper()
    return ResourceRequest(
        requirement.logical_identity,
        requirement.relative_path,
        content,
        requirement.spec_identity,
        f"generated:{platform}:adc-swd:STUB:sha256:{digest}",
        "STUB ADC SWD Pattern; structural compile only, not real ADC coverage",
    )


def _dc_swd_stub(requirement: ResourceRequirement, facts) -> ResourceRequest:
    """Emit a compiler-valid DC configuration placeholder with STUB provenance."""
    platform = str(getattr(facts, "platform", "")).strip().casefold()
    pattern_name = Path(requirement.relative_path).stem
    clk_pin = str(getattr(facts, "clk_pin", "")).strip()
    swd_pin = str(getattr(facts, "swd_pin", "")).strip()
    if platform == "chroma" and clk_pin and swd_pin:
        content = (
            'SET_DEC_FILE "pin.dec"\n\nHEADER\n\n'
            f"{clk_pin}, {swd_pin}, NRST;\n\n"
            f"SPM_PATTERN({pattern_name}) {{\n\n"
            "  *011*TS1;\n  *011*RPT 100;\n"
            "  *111*;// STUB: no real DC SWD configuration\n"
            "  *111*RPT 400;\n  *011*STOP;\n}\n"
        ).encode("ascii")
    elif platform == "s100" and clk_pin and swd_pin:
        content = (
            "HEAD[PIN_NAME]:\n\n"
            f"{clk_pin}, {swd_pin}, NRST;\n\nEND_HEAD;\n\n"
            "@@PATTERN_DEFINE\n\nSTART:011;\n      011;RPT 100;\n"
            "      111;// STUB: no real DC SWD configuration\n"
            "      111;RPT 400;\n  END:011;\n\n@@END_PATTERN_DEFINE\n"
        ).encode("ascii")
    else:
        raise ValueError(
            "DC.SWD.STUB.FACTS_INVALID: placeholder requires bound "
            "chroma/s100 facts with CLK and SWD pins"
        )
    digest = hashlib.sha256(content).hexdigest().upper()
    return ResourceRequest(
        requirement.logical_identity,
        requirement.relative_path,
        content,
        requirement.spec_identity,
        f"generated:{platform}:dc-swd:STUB:sha256:{digest}",
        "STUB DC SWD Pattern; structural compile only, not real DC coverage",
    )


def _vih_vil_swd_stub(requirement: ResourceRequirement, facts) -> ResourceRequest:
    """Emit a structural placeholder for external VIH/VIL SWD vectors."""
    platform = str(getattr(facts, "platform", "")).strip().casefold()
    pattern_name = Path(requirement.relative_path).stem
    clk_pin = str(getattr(facts, "clk_pin", "")).strip()
    swd_pin = str(getattr(facts, "swd_pin", "")).strip()
    if platform == "chroma" and clk_pin and swd_pin:
        content = (
            'SET_DEC_FILE "pin.dec"\n\nHEADER\n\n'
            f"{clk_pin}, {swd_pin}, NRST;\n\n"
            f"SPM_PATTERN({pattern_name}) {{\n\n"
            "  *011*TS1;\n  *011*RPT 100;\n"
            "  *111*;// STUB: no real VIH/VIL SWD vector\n"
            "  *111*RPT 400;\n  *011*STOP;\n}\n"
        ).encode("ascii")
    elif platform == "s100" and clk_pin and swd_pin:
        content = (
            "HEAD[PIN_NAME]:\n\n"
            f"{clk_pin}, {swd_pin}, NRST;\n\nEND_HEAD;\n\n"
            "@@PATTERN_DEFINE\n\nSTART:011;\n      011;RPT 100;\n"
            "      111;// STUB: no real VIH/VIL SWD vector\n"
            "      111;RPT 400;\n  END:011;\n\n@@END_PATTERN_DEFINE\n"
        ).encode("ascii")
    else:
        raise ValueError(
            "VIHVIL.SWD.STUB.FACTS_INVALID: placeholder requires bound "
            "chroma/s100 facts with CLK and SWD pins"
        )
    digest = hashlib.sha256(content).hexdigest().upper()
    return ResourceRequest(
        requirement.logical_identity, requirement.relative_path, content,
        requirement.spec_identity,
        f"generated:{platform}:vih-vil-swd:STUB:sha256:{digest}",
        "STUB VIH/VIL SWD Pattern; structural compile only, not real coverage",
    )


def _freq_swd_stub(requirement: ResourceRequirement, facts) -> ResourceRequest:
    """Emit a compiler-valid placeholder for unavailable FREQ configuration vectors."""
    platform = str(getattr(facts, "platform", "")).strip().casefold()
    pattern_name = Path(requirement.relative_path).stem
    clk_pin = str(getattr(facts, "clk_pin", "")).strip()
    swd_pin = str(getattr(facts, "swd_pin", "")).strip()
    if platform == "chroma" and clk_pin and swd_pin:
        content = (
            'SET_DEC_FILE "pin.dec"\n\nHEADER\n\n'
            f"{clk_pin}, {swd_pin}, NRST;\n\n"
            f"SPM_PATTERN({pattern_name}) {{\n\n"
            "  *011*TS1;\n  *011*RPT 100;\n"
            "  *111*;// STUB: no real FREQ configuration vector\n"
            "  *111*RPT 400;\n  *011*STOP;\n}\n"
        ).encode("ascii")
    elif platform == "s100" and clk_pin and swd_pin:
        content = (
            "HEAD[PIN_NAME]:\n\n"
            f"{clk_pin}, {swd_pin}, NRST;\n\nEND_HEAD;\n\n"
            "@@PATTERN_DEFINE\n\nSTART:011;\n      011;RPT 100;\n"
            "      111;// STUB: no real FREQ configuration vector\n"
            "      111;RPT 400;\n  END:011;\n\n@@END_PATTERN_DEFINE\n"
        ).encode("ascii")
    else:
        raise ValueError(
            "FREQ.SWD.STUB.FACTS_INVALID: placeholder requires bound "
            "chroma/s100 facts with CLK and SWD pins"
        )
    digest = hashlib.sha256(content).hexdigest().upper()
    return ResourceRequest(
        requirement.logical_identity, requirement.relative_path, content,
        requirement.spec_identity,
        f"generated:{platform}:freq-swd:STUB:sha256:{digest}",
        "STUB FREQ SWD Pattern; structural compile only, not real FREQ coverage",
    )


def _opa_swd_stub(requirement: ResourceRequirement, facts) -> ResourceRequest:
    platform=str(getattr(facts,"platform","")).strip().casefold(); pattern=Path(requirement.relative_path).stem
    clk=str(getattr(facts,"clk_pin","")).strip(); swd=str(getattr(facts,"swd_pin","")).strip()
    if platform=="chroma" and clk and swd:
        content=('SET_DEC_FILE "pin.dec"\n\nHEADER\n\n'+f'{clk}, {swd}, NRST;\n\nSPM_PATTERN({pattern}) {{\n\n  *011*TS1;\n  *111*;// STUB: no real OPA SWD configuration vector\n  *111*RPT 400;\n  *011*STOP;\n}}\n').encode("ascii")
    elif platform=="s100" and clk and swd:
        content=("HEAD[PIN_NAME]:\n\n"+f"{clk}, {swd}, NRST;\n\nEND_HEAD;\n\n@@PATTERN_DEFINE\n\nSTART:011;\n      111;// STUB: no real OPA SWD configuration vector\n      111;RPT 400;\n  END:011;\n\n@@END_PATTERN_DEFINE\n").encode("ascii")
    else: raise ValueError("OPA.SWD.STUB.FACTS_INVALID")
    digest=hashlib.sha256(content).hexdigest().upper()
    return ResourceRequest(requirement.logical_identity,requirement.relative_path,content,requirement.spec_identity,f"generated:{platform}:opa-swd:STUB:sha256:{digest}","STUB OPA SWD Pattern; structural compile only, not real OPA coverage")


def _dac_swd_stub(requirement: ResourceRequirement, facts) -> ResourceRequest:
    platform=str(getattr(facts,"platform","")).strip().casefold(); pattern=Path(requirement.relative_path).stem
    clk=str(getattr(facts,"clk_pin","")).strip(); swd=str(getattr(facts,"swd_pin","")).strip()
    if platform=="chroma" and clk and swd:
        content=('SET_DEC_FILE "pin.dec"\n\nHEADER\n\n'+f'{clk}, {swd}, NRST;\n\nSPM_PATTERN({pattern}) {{\n\n  *011*TS1;\n  *111*;// STUB: no real DAC SWD configuration vector\n  *111*RPT 400;\n  *011*STOP;\n}}\n').encode("ascii")
    elif platform=="s100" and clk and swd:
        content=("HEAD[PIN_NAME]:\n\n"+f"{clk}, {swd}, NRST;\n\nEND_HEAD;\n\n@@PATTERN_DEFINE\n\nSTART:011;\n      111;// STUB: no real DAC SWD configuration vector\n      111;RPT 400;\n  END:011;\n\n@@END_PATTERN_DEFINE\n").encode("ascii")
    else: raise ValueError("DAC.SWD.STUB.FACTS_INVALID")
    digest=hashlib.sha256(content).hexdigest().upper()
    return ResourceRequest(requirement.logical_identity,requirement.relative_path,content,requirement.spec_identity,f"generated:{platform}:dac-swd:STUB:sha256:{digest}","STUB DAC SWD Pattern; structural compile only, not real DAC coverage")


def _sram_capture_stub(requirement: ResourceRequirement, facts) -> ResourceRequest:
    """Emit the Chroma SRAM_CAPTURE labels when no qualified seed exists."""
    platform = str(getattr(facts, "platform", "")).strip().casefold()
    pattern_name = Path(requirement.relative_path).stem
    swd_pin = str(getattr(facts, "swd_pin", "")).strip()
    if platform != "chroma" or not swd_pin:
        raise ValueError(
            "SRAM_CAPTURE.STUB.FACTS_INVALID: placeholder requires bound "
            "Chroma facts with SWD pin"
        )
    address_vectors = "\n".join("  *X*;" for _ in range(15))
    capture_vectors = "\n".join("  *K*;" for _ in range(32))
    content = (
        'SET_DEC_FILE "pin.dec"\n\nHEADER\n\n'
        f"{swd_pin};\n\nSPM_PATTERN({pattern_name}) {{\n\n"
        "START:\n  *X*TS1;\n"
        "addr:\n  *X*;// STUB: 16-bit address window starts here\n"
        f"{address_vectors}\n"
        "parity:\n  *X*;// STUB: parity write location\n"
        "  *X*;// STUB: no real SRAM read transaction\n"
        f"{capture_vectors}\n"
        "END:\n  *X*STOP;\n}\n"
    ).encode("ascii")
    digest = hashlib.sha256(content).hexdigest().upper()
    return ResourceRequest(
        requirement.logical_identity,
        requirement.relative_path,
        content,
        requirement.spec_identity,
        f"generated:{platform}:sram-capture:STUB:sha256:{digest}",
        "STUB SRAM_CAPTURE Pattern; structural compile only, not real capture coverage",
    )


class GeneratedPatternProducer:
    """Overlay generated pattern bundles on an optional fallback producer."""

    def __init__(self, *results, fallback: PatternProducer | None = None) -> None:
        from program_gen.core.fbist_pattern_plan import (
            FbistPatternGenerationResult,
        )
        from program_gen.core.flash_compare_renderer import (
            FlashCompareGenerationResult,
        )
        from program_gen.core.flash_label_renderer import FlashLabelGenerationResult

        valid_types = (
            FbistPatternGenerationResult, FlashCompareGenerationResult,
            FlashLabelGenerationResult,
        )
        if not results or any(not isinstance(result, valid_types) for result in results):
            raise TypeError(
                "GeneratedPatternProducer expects generated pattern result bundles"
            )
        platforms = {str(result.platform).strip().casefold() for result in results}
        if len(platforms) != 1:
            raise ValueError("PATTERN.GENERATED_PLATFORM_MISMATCH")
        self._results = tuple(results)
        self._by_name = {}
        for result in results:
            for artifact in result.artifacts:
                if artifact.pattern_name in self._by_name:
                    raise ValueError(
                        f"PATTERN.GENERATED_DUPLICATE: {artifact.pattern_name}"
                    )
                self._by_name[artifact.pattern_name] = artifact
        self._fallback = fallback

    @classmethod
    def from_compilation(
        cls, compilation, platform: str, *, fallback: PatternProducer | None = None
    ) -> "GeneratedPatternProducer":
        platform = str(platform).strip().casefold()
        if platform == "chroma":
            from program_gen.platforms.chroma.fbist_pattern_generator import (
                generate_fbist_patterns,
            )
        elif platform == "s100":
            from program_gen.platforms.s100.fbist_pattern_generator import (
                generate_fbist_patterns,
            )
        else:
            raise ValueError("platform must be chroma or s100")
        from program_gen.core.flash_compare_renderer import render_flash_compare_plans
        from program_gen.core.flash_label_renderer import render_flash_label_plan

        fbist = generate_fbist_patterns(compilation.pattern_compilation)
        flash = render_flash_compare_plans(
            compilation.flash_compare_compilation.require_complete().plans,
            platform,
        )
        flash_labels = render_flash_label_plan(compilation.flash_label_plan, platform)
        return cls(fbist, flash, flash_labels, fallback=fallback)

    def for_target(self, facts) -> "GeneratedPatternProducer":
        fallback = self._fallback
        bind_target = getattr(fallback, "for_target", None)
        if callable(bind_target):
            fallback = bind_target(facts)
        return GeneratedPatternProducer(*self._results, fallback=fallback)

    def produce(self, requirement: ResourceRequirement) -> ResourceRequest:
        filename = Path(requirement.relative_path).name
        name = Path(filename).stem
        artifact = self._by_name.get(name)
        if artifact is None:
            if self._fallback is not None:
                return self._fallback.produce(requirement)
            raise ValueError(
                f"FBIST.PATTERN.MISSING: {requirement.logical_identity} -> {name}"
            )
        return ResourceRequest(
            logical_identity=requirement.logical_identity,
            relative_path=requirement.relative_path,
            content=artifact.content,
            spec_identity=requirement.spec_identity,
            source_identity=artifact.source_identity,
            purpose=requirement.purpose,
        )

    def write_region(self, pattern_name: str) -> PatternWriteRegion:
        artifact = self._by_name.get(pattern_name)
        if artifact is None:
            if self._fallback is not None:
                return self._fallback.write_region(pattern_name)
            raise ValueError(
                f"FBIST.PATTERN.MISSING: write region -> {pattern_name}"
            )
        text = artifact.content.decode("ascii")
        if pattern_name.endswith(".pat") or artifact.relative_path.endswith(".pat"):
            bases = re.findall(
                r"^\s*([A-Za-z_][A-Za-z0-9_]*_data)\s*:", text, re.M
            )
            if len(bases) != 1:
                raise ValueError(
                    f"FBIST.PATTERN.WRITE_REGION: {pattern_name!r} has "
                    f"{len(bases)} base labels"
                )
            return PatternWriteRegion(bases[0], bases[0], bases[0])
        starts = re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*_data_st)\s*:", text, re.M)
        if len(starts) != 1:
            raise ValueError(
                f"FBIST.PATTERN.WRITE_REGION: {pattern_name!r} has "
                f"{len(starts)} start labels"
            )
        start = starts[0]
        prefix = start[:-2]
        end = prefix + "sp"
        if not re.search(rf"^\s*{re.escape(end)}\s*:", text, re.M):
            raise ValueError(
                f"FBIST.PATTERN.WRITE_REGION: {pattern_name!r} lacks {end!r}"
            )
        return PatternWriteRegion(prefix[:-1], start, end)

    def timing_sets(self, requirements) -> tuple[str, ...]:
        names = set()
        for requirement in requirements:
            artifact = self._by_name.get(Path(requirement.relative_path).stem)
            if artifact is not None:
                names.update(re.findall(
                    r"\bTIMING_SET\s+(G\d+_\d+)\s*;",
                    artifact.content.decode("ascii"),
                ))
        fallback_requirements = tuple(
            requirement for requirement in requirements
            if Path(requirement.relative_path).stem not in self._by_name
        )
        if self._fallback is not None and fallback_requirements:
            names.update(self._fallback.timing_sets(fallback_requirements))
        return tuple(sorted(names))


__all__ = [
    "GeneratedPatternProducer",
    "PatternProducer",
    "PatternWriteRegion",
    "WorkspacePatternProducer",
]
