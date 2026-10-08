"""Platform-neutral plans for loading and physically programming OTP pages."""

from dataclasses import dataclass, replace
import re
from typing import Iterable, Tuple

from program_gen.core.page_image import FieldTarget
from program_gen.core.commit_module import CommitPatternTarget
from program_gen.core.flash_label_plan import FlashLabelSpan
from program_gen.core.run_pattern import PatternResourceRef, PatternSpan, RunPatternPlan


class OtpProgramPlanError(ValueError):
    """A persistence plan cannot preserve the agreed physical workflow."""


@dataclass(frozen=True)
class PagePatternPlan:
    """Pattern identities a platform adapter needs for one physical page."""

    page: str
    erase_pattern: str
    program_pattern: str
    read_pattern: str
    is_uid: bool = False


@dataclass(frozen=True)
class OtpExecutionStep:
    action: str
    run: RunPatternPlan
    site_scope: str = "TARGET_SITES"


@dataclass(frozen=True)
class PageProgramOperation:
    patterns: PagePatternPlan
    steps: Tuple[OtpExecutionStep, ...]

    @property
    def actions(self) -> Tuple[str, ...]:
        return tuple(step.action for step in self.steps)


@dataclass(frozen=True)
class PgmOtpPlan:
    page_operations: Tuple[PageProgramOperation, ...]


@dataclass(frozen=True, slots=True)
class PgmOtpModulePlan:
    """One executable PGMOTP session for a registered Recipe Module."""

    cp: str
    power_profile: str
    enter_fbist_mode: RunPatternPlan
    set_all_final_vposp: RunPatternPlan
    page_program: PgmOtpPlan


@dataclass(frozen=True)
class PagePatternLoadOperation:
    patterns: PagePatternPlan
    pattern_updates: Tuple[str, ...] = (
        "PROGRAM_PATTERN",
        "READ_COMPARE_PATTERN",
    )


@dataclass(frozen=True)
class LoadMapWordWrite:
    """Explicit full-word Page Image override and its Program/Compare targets."""

    page: str
    word_index: int
    value: int
    program_pattern: str
    read_pattern: str
    labels: Tuple[FlashLabelSpan, ...]


@dataclass(frozen=True)
class LoadMapPlan:
    image_source: str
    page_operations: Tuple[PagePatternLoadOperation, ...]
    runs_pattern: bool = False
    targets: tuple[object, ...] = ()
    swd_pin: str = ""
    cp: str = ""
    word_writes: Tuple[LoadMapWordWrite, ...] = ()
    field_values: tuple[object, ...] = ()

    @property
    def target_pages(self) -> Tuple[str, ...]:
        return tuple(operation.patterns.page for operation in self.page_operations)


def compile_load_map_plan(
    pages: Tuple[PagePatternPlan, ...],
    *,
    image_source: str,
) -> LoadMapPlan:
    return LoadMapPlan(
        image_source=str(image_source).strip().upper(),
        page_operations=tuple(PagePatternLoadOperation(page) for page in pages),
    )


def compile_load_map_module_plan(
    pages, catalog, flash_labels, *, cp, swd_pin, image_source, word_writes=(),
    registers=None,
) -> LoadMapPlan:
    """Bind selected REG images and explicit word overrides to shared labels."""
    page_keys = {page.page.casefold() for page in pages}
    targets = []
    for register in catalog.registers if registers is None else registers:
        if register.page.casefold() not in page_keys or not register.applies_to(cp):
            continue
        binding = flash_labels.bind_register(register.page, register.register, cp)
        targets.append(CommitPatternTarget(
            register.page, register.register, f"REG_{register.register.upper()}",
            binding.program_pattern, binding.read_pattern, binding.spans,
        ))
    for write in word_writes:
        if write.page.casefold() not in page_keys or not 0 <= write.value <= 0xFFFFFFFF:
            raise OtpProgramPlanError("LOADMAP.WORD_WRITE.INVALID")
        if not write.labels or any(label.width != 32 for label in write.labels):
            raise OtpProgramPlanError("LOADMAP.WORD_WRITE.LABEL_INVALID")
    return replace(
        compile_load_map_plan(tuple(pages), image_source=image_source),
        targets=tuple(targets), swd_pin=swd_pin, cp=cp,
        word_writes=tuple(word_writes),
    )


def compile_pgm_otp_plan(
    pages: Tuple[PagePatternPlan, ...],
    *,
    timing_profile: str = "TS_5MHZ",
    reerase_uid_on_failure: bool = True,
) -> PgmOtpPlan:
    page_operations = []
    for patterns in pages:
        steps = [
            OtpExecutionStep("ERASE", _run(patterns.erase_pattern, timing_profile)),
            OtpExecutionStep("PROGRAM", _run(patterns.program_pattern, timing_profile)),
            OtpExecutionStep("READ_CHECK", _run(patterns.read_pattern, timing_profile)),
        ]
        if patterns.is_uid and reerase_uid_on_failure:
            steps.append(OtpExecutionStep(
                "RE_ERASE",
                _run(patterns.erase_pattern, timing_profile),
                site_scope="FAILED_SITES",
            ))
        page_operations.append(PageProgramOperation(patterns, tuple(steps)))
    return PgmOtpPlan(tuple(page_operations))


def compile_pgm_otp_module_plan(
    pages: Tuple[PagePatternPlan, ...],
    *,
    cp: str,
    power_profile: str,
    timing_profile: str = "TS_5MHZ",
    reerase_uid_on_failure: bool = True,
) -> PgmOtpModulePlan:
    """Bind the page protocol to one power/FBIST/VPOSP execution session."""
    normalized_cp = str(cp).strip().upper()
    if not re.fullmatch(r"CP\d+", normalized_cp):
        raise OtpProgramPlanError(f"PGMOTP.CP.INVALID: {cp!r}")
    profile = str(power_profile).strip().upper()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", profile):
        raise OtpProgramPlanError(f"PGMOTP.VCC.INVALID: {power_profile!r}")
    selected = tuple(pages)
    if not selected:
        raise OtpProgramPlanError("PGMOTP.PAGE_SCOPE.EMPTY")
    uid_count = sum(pattern.is_uid for pattern in selected)
    if uid_count > 1:
        raise OtpProgramPlanError("PGMOTP.PAGE_SCOPE.MULTIPLE_UID_UNSUPPORTED")
    return PgmOtpModulePlan(
        normalized_cp,
        profile,
        _run("enter_fbist_mode", timing_profile),
        _run("set_all_final_vposp", timing_profile),
        compile_pgm_otp_plan(
            selected, timing_profile=timing_profile,
            reerase_uid_on_failure=reerase_uid_on_failure,
        ),
    )


def _run(name: str, timing_profile: str) -> RunPatternPlan:
    return RunPatternPlan(
        PatternResourceRef(str(name).strip(), f"pattern:{str(name).strip()}", ("START", "END")),
        PatternSpan.full(),
        timing_profile,
    )


@dataclass(frozen=True)
class TrimdataWriteReadPlan:
    recipe: Tuple[str, ...]
    load_map: LoadMapPlan
    pgm_otp: PgmOtpPlan


def compile_cp1_trimdata_write_read_plan(
    field_targets: Iterable[FieldTarget],
    pattern_catalog: Iterable[PagePatternPlan],
    *,
    page_image_source: str = "BUILDMAP",
    recipe: Tuple[str, ...] = ("LOADMAP", "PGMOTP"),
) -> TrimdataWriteReadPlan:
    normalized_recipe = tuple(str(module).strip().upper() for module in recipe)
    required_recipe = ("LOADMAP", "PGMOTP")
    if normalized_recipe != required_recipe:
        raise OtpProgramPlanError(
            "CP1 Trimdata_Write_Read Recipe must be LOADMAP -> PGMOTP; "
            "SETVPOSP remains an explicit external module"
        )
    normalized_source = str(page_image_source).strip().upper()
    if normalized_source != "BUILDMAP":
        raise OtpProgramPlanError(
            "CP1 Trimdata_Write_Read LOADMAP requires a BUILDMAP Page Image"
        )
    patterns_by_page = {patterns.page: patterns for patterns in pattern_catalog}
    target_page_names = tuple(dict.fromkeys(target.page for target in field_targets))
    missing_pages = tuple(page for page in target_page_names if page not in patterns_by_page)
    if missing_pages:
        raise OtpProgramPlanError(
            "missing pattern plan for target page(s): " + ", ".join(missing_pages)
        )
    target_pages = tuple(patterns_by_page[page] for page in target_page_names)
    return TrimdataWriteReadPlan(
        recipe=required_recipe,
        load_map=compile_load_map_plan(target_pages, image_source=normalized_source),
        pgm_otp=compile_pgm_otp_plan(target_pages),
    )
