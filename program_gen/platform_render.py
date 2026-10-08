"""Native renderer seam: turn typed business plans into platform source fragments.

This is the layer the handoff names as the missing producer.  It keeps the
core contribution graph as a pure business projection (``sections=()``) and
adds, at the render layer, the SectionFragments a platform needs to emit real
tester source.  No global ``G`` state, no cwd, no filesystem writes.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pandas as pd

from program_gen.core.dedicated_trim import DedicatedTrimPlan
from program_gen.core.os_plan import OsPlan
from program_gen.core.os_contribution import compile_os_contribution
from program_gen.core.pdr_contribution import compile_pdr_contribution
from program_gen.core.pdr_verify import PdrVerifyPlan
from program_gen.core.pdr_verify_contribution import compile_pdr_verify_contribution
from program_gen.core.standard_trim_contribution import (
    compile_standard_trim_contribution,
)
from program_gen.core.trim_spec import TrimSpec
from program_gen.render_plan import (
    ProgramAssembler,
    ProgramContribution,
    RenderPlan,
    ResourceRequest,
    RenderSymbolRef,
    SectionFragment,
    SymbolProvision,
    TargetKey,
)


@dataclass(frozen=True, slots=True)
class PdrVerifyRenderContext:
    """Per-CP render inputs that used to be read from the global workbook."""

    power_rails: tuple[str, ...]
    reject_bin: int | None = None


@dataclass(frozen=True, slots=True)
class OsRenderContext:
    """Per-CP render inputs the Chroma OS body used to read from global state.

    ``kp_relay`` mirrors ``cp_has_kp_relay``; ``power_pins`` mirrors
    ``VCC_pin_rebuild`` (one representative pad per DPS channel);
    ``force_rails`` mirrors ``vcc_rails_str`` (the CP2→CP1 fallback join);
    ``site_groups`` mirrors the even/odd SOCKET_SET grouping from PIN_DEC Site.
    """

    kp_relay: bool
    power_pins: tuple[str, ...]
    force_rails: str
    site_groups: tuple[tuple[tuple[int, ...], str], ...]


def resolve_os_context(pin_dec: pd.DataFrame, cp: str) -> OsRenderContext:
    """Build the full OS render context for one CP from a PIN DEC projection."""
    power_pins = resolve_power_rails(pin_dec, cp)
    force_cp = "CP1" if cp == "CP2" else cp
    force_rails = "+".join(resolve_power_rails(pin_dec, force_cp))
    return OsRenderContext(
        kp_relay=resolve_kp_relay(pin_dec, cp),
        power_pins=power_pins,
        force_rails=force_rails,
        site_groups=resolve_site_groups(pin_dec, cp),
    )


@dataclass(frozen=True, slots=True)
class PdrTrimRenderContext:
    """Legacy adapter carries only platform rails; PDR facts live in the plan."""

    power_rails: str


@dataclass(frozen=True, slots=True)
class StandardTrimRenderContext:
    """Target facts needed to render one STANDARD_TRIM definition."""

    test_number: int
    relay: str


def resolve_pdr_trim_context(
    pin_dec: pd.DataFrame, plan: DedicatedTrimPlan
) -> PdrTrimRenderContext:
    """Project platform power rails without rereading PDR workbook semantics."""
    power_rails = "+".join(resolve_power_rails(pin_dec, plan.cp))
    return PdrTrimRenderContext(power_rails=power_rails)


def resolve_standard_trim_context(
    workbook,
    pin_dec: pd.DataFrame,
    spec: TrimSpec,
) -> StandardTrimRenderContext:
    """Resolve TEST_NUM and an actually declared relay for one target."""
    flow = workbook.dataframe("FLOW")
    relay = str(flow.iloc[spec.flow_row_index].get("relay", "/")).strip()
    if relay != "/":
        declared = any(
            str(pin_dec.iloc[index]["CP NO"]).strip() == spec.cp
            and str(pin_dec.iloc[index]["E/C(Pad Name)"]).strip() == relay
            for index in range(len(pin_dec))
        )
        if not declared:
            relay = "/"
    return StandardTrimRenderContext(
        test_number=resolve_trim_test_number(workbook, spec.cp, spec.item),
        relay=relay,
    )


def resolve_pin_dec(
    workbook, variant: str, platform: str
) -> pd.DataFrame:
    """Return the lab/production PIN DEC projection legacy ``G.PIN_DEC_128`` used.

    * lab → ``PIN DEC SINGEL`` filtered by TESTER==platform, then replicated per
      CP (``CP NO`` column rewritten to each CP num), so every CP shares the
      single-site pin list.
    * production → ``PIN DEC`` (multi-site) unchanged.
    """
    variant = str(variant).strip().casefold()
    if variant == "lab":
        singel = workbook.dataframe("PIN DEC SINGEL")
        lab_rows = singel[
            singel["TESTER"].astype(str).str.strip().str.lower()
            == str(platform).casefold()
        ].copy()
        version = workbook.dataframe("VERSION")
        cp_nums: list = []
        for cp in version["CP num"]:
            if cp not in cp_nums:
                cp_nums.append(cp)
        parts = []
        for cp in cp_nums:
            rows = lab_rows.copy()
            rows["CP NO"] = cp
            parts.append(rows)
        return pd.concat(parts, ignore_index=True)
    if variant == "production":
        return workbook.dataframe("PIN DEC")
    raise ValueError(f"unsupported PIN DEC variant {variant!r}")


def resolve_kp_relay(pin_dec: pd.DataFrame, cp: str) -> bool:
    """Whether this CP declares a KP relay row (mirrors ``cp_has_kp_relay``)."""
    pin_cp = pin_dec["CP NO"]
    pin_trace = pin_dec["Trace"]
    pin_site = pin_dec["Site"]
    sites = {
        pin_site.iloc[u]
        for u in range(len(pin_cp))
        if str(pin_cp.iloc[u]).strip() == str(cp).strip()
    }
    if cp not in ("CP1", "CP2"):
        return False
    if len(sites) == 1:
        return True
    return cp == "CP1" and any(
        str(pin_cp.iloc[u]).strip() == str(cp).strip()
        and ("F0" in str(pin_trace.iloc[u]) or "F1" in str(pin_trace.iloc[u]))
        for u in range(len(pin_cp))
    )


def resolve_site_groups(
    pin_dec: pd.DataFrame, cp: str
) -> tuple[tuple[tuple[int, ...], str], ...]:
    """Even/odd site groups for the SOCKET_SET power-rail OS block."""
    pin_cp = pin_dec["CP NO"]
    pin_site = pin_dec["Site"]
    all_sites = sorted(
        {
            int(pin_site.iloc[u]) - 1
            for u in range(len(pin_cp))
            if str(pin_cp.iloc[u]).strip() == str(cp).strip()
        }
    )
    return (
        (tuple(s for s in all_sites if s % 2 == 0), "F0/S0"),
        (tuple(s for s in all_sites if s % 2 == 1), "F1/S1"),
    )


def resolve_trim_test_number(workbook, cp: str, item: str) -> int:
    """Return the Chroma TEST_NUM for a trim item from PATTERN-sheet ordering.

    Mirrors ``pattern_testitem_merge_rname``: the name list is the PATTERN-sheet
    sequence of non-os/shmoo items for this CP; TEST_NUM = (index + 1) * 50.
    """
    pattern = workbook.dataframe("pattern")
    flow = workbook.dataframe("FLOW")
    pattern_item = pattern["item"]
    pattern_pattern = pattern["pattern"]
    flow_type = flow["type"]
    flow_cp = flow["CP NO"]
    flow_item = flow["item"]
    name: list = []
    function_name = ""
    for j in range(len(pattern_item)):
        if isinstance(pattern_item[j], str):
            function_name = pattern_item[j]
        if isinstance(pattern_pattern[j], str) and pattern_pattern[j] != "reuse dac":
            for z in range(len(flow_type)):
                if flow_cp[z] == cp and flow_type[z] not in ("os", "shmoo"):
                    if flow_item[z] == function_name:
                        name.append(function_name)
    return (name.index(item) + 1) * 50


def resolve_power_rails(pin_dec: pd.DataFrame, cp: str) -> tuple[str, ...]:
    """Extract the power rails a CP forces, from the PIN_DEC table.

    Replicates the historical ``VCC_pin_rebuild`` predicate without global
    state: CP match, single-site, pad name contains ``V``, trace is not GND,
    de-duplicated by trace and excluding ``VDDD``.
    """
    pin_cp = pin_dec["CP NO"]
    pin_site = pin_dec["Site"]
    pin_trace = pin_dec["Trace"]
    pin_pad = pin_dec["E/C(Pad Name)"]
    rail: dict = {}
    order: list = []
    for index in range(len(pin_site)):
        if (
            str(pin_cp.iloc[index]).strip() == str(cp).strip()
            and pin_site.iloc[index] == 1
            and "V" in str(pin_pad.iloc[index]).upper()
            and "GND" not in str(pin_trace.iloc[index]).upper()
        ):
            trace = pin_trace.iloc[index]
            if trace not in rail:
                rail[trace] = pin_pad.iloc[index]
                order.append(trace)
    return tuple(
        rail[trace] for trace in order if str(rail[trace]).upper() != "VDDD"
    )


def render_pdr_verify_section(
    plan: PdrVerifyPlan,
    target: TargetKey,
    schedule,
    *,
    context: PdrVerifyRenderContext,
) -> SectionFragment:
    """Render one PDR_VERIFY definition as a platform source fragment.

    The canonical schedule supplies definition identity, ordinal, and the S100
    hardware bin; the typed plan supplies the business body; the render context
    supplies platform pin/profile facts (power rails) that the core plan must
    not own.
    """
    contribution = compile_pdr_verify_contribution(plan, target, schedule)
    definition_identity = contribution.definitions[0].identity
    ordinal = contribution.schedule_entries[0].ordinal

    # The S100 REJECT_BIN is the scheduled item's hardware bin, owned by the
    # canonical schedule rather than the business plan.
    entry = next(
        entry
        for entry in schedule.entries
        if entry.definition_id.casefold() == definition_identity.casefold()
    )
    reject_bin = (
        context.reject_bin
        if context.reject_bin is not None
        else entry.bin_binding.hardware_bin
    )

    platform = target.platform.casefold()
    if platform == "chroma":
        from program_gen.platforms.chroma.pdr_verify_renderer import (
            render_pdr_verify_body,
        )

        body = render_pdr_verify_body(
            plan, power_rails=context.power_rails, test_number=(plan.row + 1) * 100
        )
        artifact_path = f"{target.program_name}.pln"
    elif platform == "s100":
        from program_gen.platforms.s100.pdr_verify_renderer import (
            render_pdr_verify_body,
        )

        body = render_pdr_verify_body(
            plan, power_rails=context.power_rails, reject_bin=reject_bin
        )
        artifact_path = f"{target.program_name}.prg"
    else:
        raise ValueError(f"unsupported PDR_VERIFY target platform {target.platform!r}")

    return SectionFragment(
        artifact_path=artifact_path,
        section="TESTS",
        identity=f"pdr-verify:{target.identity}:{definition_identity}:body",
        content=body,
        order=ordinal,
    )


def render_os_section(
    plan: OsPlan,
    target: TargetKey,
    cp_plan,
    *,
    context: OsRenderContext,
) -> SectionFragment:
    """Render one OS definition as a Chroma source fragment."""
    contribution = compile_os_contribution(plan, target, cp_plan)
    definition_identity = contribution.definitions[0].identity
    ordinal = contribution.schedule_entries[0].ordinal

    platform = target.platform.casefold()
    if platform == "chroma":
        from program_gen.platforms.chroma.os_renderer import render_os_body

        body = render_os_body(
            plan, context=context, test_number=(plan.row + 1) * 100
        )
        artifact_path = f"{target.program_name}.pln"
    elif platform == "s100":
        from program_gen.platforms.s100.os_renderer import render_os_body

        entry = next(
            entry
            for entry in cp_plan.canonical_schedule.entries
            if entry.definition_id.casefold() == definition_identity.casefold()
        )
        body = render_os_body(
            plan,
            power_pins=context.power_pins,
            reject_bin=entry.bin_binding.hardware_bin,
        )
        artifact_path = f"{target.program_name}.prg"
    else:
        raise ValueError(f"unsupported OS target platform {target.platform!r}")

    return SectionFragment(
        artifact_path=artifact_path,
        section="TESTS",
        identity=f"os:{target.identity}:{definition_identity}:body",
        content=body,
        order=ordinal,
    )


def render_pdr_trim_section(
    plan: DedicatedTrimPlan,
    target: TargetKey,
    cp_plan,
    *,
    context: PdrTrimRenderContext,
) -> SectionFragment:
    """Render one PDR_TRIM definition as a Chroma source fragment."""
    contribution = compile_pdr_contribution(plan, target, cp_plan.canonical_schedule)
    definition_identity = contribution.definitions[0].identity
    ordinal = contribution.schedule_entries[0].ordinal

    from program_gen.platforms.chroma.pdr_trim_renderer import render_pdr_trim_body

    body = render_pdr_trim_body(
        plan,
        power_rails=context.power_rails,
    )
    return SectionFragment(
        artifact_path=f"{target.program_name}.pln",
        section="TESTS",
        identity=f"pdr-trim:{target.identity}:{definition_identity}:body",
        content=body,
        order=ordinal,
    )


def render_standard_trim_sections(
    spec: TrimSpec,
    target: TargetKey,
    schedule,
    *,
    context: StandardTrimRenderContext,
    resource_closure: tuple[str, ...],
) -> tuple[SectionFragment, ...]:
    """Render every canonical STANDARD_TRIM variant for one definition."""
    if target.platform.casefold() != "chroma":
        raise ValueError(
            f"unsupported STANDARD_TRIM renderer platform {target.platform!r}"
        )
    contribution = compile_standard_trim_contribution(
        spec, target, schedule, resource_closure=resource_closure
    )
    definition_identity = contribution.definitions[0].identity
    schedule_entries = {
        entry.identity.casefold(): entry for entry in contribution.schedule_entries
    }
    canonical_entries = tuple(
        entry for entry in schedule.entries
        if entry.definition_id.casefold() == definition_identity.casefold()
    )
    if len(canonical_entries) != len(schedule_entries):
        raise ValueError(
            f"STANDARD_TRIM {spec.item!r} canonical variant count changed during render"
        )

    from program_gen.platforms.chroma.standard_trim_renderer import (
        render_standard_trim_body,
    )

    fragments = []
    for entry in canonical_entries:
        projected = schedule_entries[entry.identity.casefold()]
        body = render_standard_trim_body(
            spec,
            variant=entry.variant,
            test_number=context.test_number,
            relay=context.relay,
        )
        fragments.append(SectionFragment(
            artifact_path=f"{target.program_name}.pln",
            section="TESTS",
            identity=(
                f"standard-trim:{target.identity}:{entry.identity}:body"
            ),
            content=body,
            order=projected.ordinal,
        ))
    return tuple(fragments)


def resolve_pattern_resource(
    logical_identity: str, platform: str, seed_root: Path
) -> ResourceRequest:
    """Load a pattern's committed seed bytes for one platform target.

    ``logical_identity`` is the plan-owned name (``pattern:enter_fbist_mode``).
    The emitted relative path and spec identity must match the core
    contribution's ``resource_requires`` contract so the Assembler closes it.
    """
    name = logical_identity.rsplit(":", 1)[-1]
    platform = platform.casefold()
    if platform == "chroma":
        extension, prefix = ".pat", "pat/"
    elif platform == "s100":
        extension, prefix = ".sd", ""
    else:
        raise ValueError(f"unsupported pattern platform {platform!r}")

    seed = seed_root / "pat_temp" / f"{name}{extension}"
    if not seed.is_file():
        raise ValueError(f"pattern seed missing: {seed}")
    content = seed.read_bytes()
    return ResourceRequest(
        logical_identity=logical_identity,
        relative_path=f"{prefix}{name}{extension}",
        content=content,
        spec_identity=f"v13.pattern/1:{platform}:{name}",
        source_identity=f"seed:{platform}/pat_temp/{name}{extension}",
        purpose="PDR_VERIFY pattern",
    )


# Section ordering for each platform's physical program file.  Ordering here
# controls where body fragments land relative to the required skeleton.
CHROMA_SECTION_ORDER = ("HEADER", "GLOBALS", "STARTUP", "TESTS", "FLOW")
S100_SECTION_ORDER = ("HEADER", "GLOBALS", "TESTS", "FLOW")


def chroma_fixed_skeleton(
    golden_pln: Path, program_name: str
) -> tuple[SectionFragment, ...]:
    """Return the Chroma fixed header + declaration seed as skeleton fragments.

    Transition seed: extracts the byte-exact committed prefix from a golden PLN
    so the skeleton contract stays honest until the renderer generates it from
    the workbook VERSION/pin data itself.  Two layers, two sections:

    * ``HEADER`` — the truly fixed prefix (includes + base globals) that ends
      where the first business-owned global (``TIME FSCLK_ERASE``) begins.
    * ``GLOBALS`` — the business declaration seed (trim/OTP register globals and
      HW/SW bin definitions) that the declaration renderer will eventually
      generate from the typed ``RuntimeStateGroup``; it ends at ``START_UP()``.
    """
    lines = golden_pln.read_bytes().decode("gbk", errors="replace").splitlines()
    header_end = next(
        index for index, line in enumerate(lines) if line.startswith("TIME FSCLK_ERASE")
    )
    globals_end = next(
        index for index, line in enumerate(lines) if line.startswith("START_UP()")
    )
    header = "\n".join(lines[:header_end]) + "\n"
    globals_text = "\n".join(lines[header_end:globals_end]) + "\n"
    return (
        SectionFragment(
            f"{program_name}.pln",
            "HEADER",
            "skeleton:chroma:header",
            header,
            order=0,
        ),
        SectionFragment(
            f"{program_name}.pln",
            "GLOBALS",
            "skeleton:chroma:globals",
            globals_text,
            order=1,
        ),
    )


class PlatformRenderPlanner:
    """Render one target into a closed ``RenderPlan``.

    This is the deep module the handoff names as the missing producer.  The
    caller supplies a compiled product, one target, and the PIN_DEC table, and
    receives a fully closed RenderPlan; the planner owns the per-family fan-out
    (typed plan → body SectionFragment → pattern resources), the platform
    skeleton/section ordering, and assembly.  It never reads the workbook, the
    global ``G`` state, or the cwd.
    """

    def __init__(
        self,
        *,
        section_order: tuple[str, ...] = ("TESTS",),
        skeleton: tuple[SectionFragment, ...] = (),
        seed_root: str | Path,
    ) -> None:
        self._section_order = tuple(section_order)
        self._skeleton = tuple(skeleton)
        self._seed_root = Path(seed_root)
        # Family renderer registry: the copy-paste seam for the next business
        # family.  Migrating OS/STANDARD_TRIM/FBIST_VERIFY means adding one
        # entry here plus one ``_render_<family>`` method that mirrors
        # ``_render_pdr_verify``.
        self._family_renderers = {
            "pdr_verify": self._render_pdr_verify,
            "os": self._render_os,
            "pdr_trim": self._render_pdr_trim,
            "standard_trim": self._render_standard_trim,
        }

    @property
    def families(self) -> tuple[str, ...]:
        """The business families this planner currently renders (read-only)."""
        return tuple(self._family_renderers)

    def plan(
        self, compilation, target: TargetKey, workbook
    ) -> RenderPlan:
        platform = target.platform.casefold()
        cp = target.cp
        cp_plan = compilation.for_cp(cp)
        pin_dec = resolve_pin_dec(workbook, target.variant, target.platform)

        contributions: list[ProgramContribution] = []
        for renderer in self._family_renderers.values():
            contributions.extend(
                renderer(compilation, target, cp_plan, pin_dec, workbook, platform, cp)
            )

        contributions.append(_platform_runtime_support(target, contributions))

        assembler = ProgramAssembler(
            section_order=self._section_order,
            required_skeleton=self._skeleton,
        )
        return assembler.assemble(target, contributions)

    def _render_pdr_verify(
        self, compilation, target, cp_plan, pin_dec, workbook, platform, cp
    ) -> list[ProgramContribution]:
        contributions: list[ProgramContribution] = []
        schedule = cp_plan.canonical_schedule
        context = PdrVerifyRenderContext(
            power_rails=resolve_power_rails(pin_dec, cp)
        )
        catalogs = compilation.plan.catalogs
        for _row, plan in sorted(catalogs.pdr_verify_plans[platform].items()):
            if plan.cp.casefold() != cp.casefold():
                continue
            contribution = compile_pdr_verify_contribution(plan, target, schedule)
            section = render_pdr_verify_section(plan, target, schedule, context=context)
            resources = tuple(
                resolve_pattern_resource(
                    requirement.logical_identity, platform, self._seed_root
                )
                for requirement in contribution.resource_requires
            )
            contribution = replace(
                contribution, sections=(section,), resources=resources
            )
            contributions.append(contribution)
        return contributions

    def _render_os(
        self, compilation, target, cp_plan, pin_dec, workbook, platform, cp
    ) -> list[ProgramContribution]:
        contributions: list[ProgramContribution] = []
        context = resolve_os_context(pin_dec, cp)
        catalogs = compilation.plan.catalogs
        for _row, plan in sorted(catalogs.os_plans[platform].items()):
            if plan.cp.casefold() != cp.casefold():
                continue
            contribution = compile_os_contribution(plan, target, cp_plan)
            section = render_os_section(plan, target, cp_plan, context=context)
            contribution = replace(contribution, sections=(section,))
            contributions.append(contribution)
        return contributions

    def _render_pdr_trim(
        self, compilation, target, cp_plan, pin_dec, workbook, platform, cp
    ) -> list[ProgramContribution]:
        contributions: list[ProgramContribution] = []
        if platform != "chroma":
            return contributions
        catalogs = compilation.plan.catalogs
        for _row, plan in sorted(catalogs.dedicated_trim_plans.items()):
            if plan.cp.casefold() != cp.casefold():
                continue
            context = resolve_pdr_trim_context(pin_dec, plan)
            contribution = compile_pdr_contribution(plan, target, cp_plan.canonical_schedule)
            section = render_pdr_trim_section(plan, target, cp_plan, context=context)
            resources = tuple(
                resolve_pattern_resource(
                    requirement.logical_identity, platform, self._seed_root
                )
                for requirement in contribution.resource_requires
            )
            contribution = replace(
                contribution, sections=(section,), resources=resources
            )
            contributions.append(contribution)
        return contributions

    def _render_standard_trim(
        self, compilation, target, cp_plan, pin_dec, workbook, platform, cp
    ) -> list[ProgramContribution]:
        if platform != "chroma":
            return []
        contributions: list[ProgramContribution] = []
        schedule = cp_plan.canonical_schedule
        catalogs = compilation.plan.catalogs
        for _row, spec in sorted(catalogs.trim_specs.items()):
            if spec.cp.casefold() != cp.casefold():
                continue
            contribution = compile_standard_trim_contribution(
                spec,
                target,
                schedule,
                resource_closure=cp_plan.resources.identities,
            )
            context = resolve_standard_trim_context(workbook, pin_dec, spec)
            sections = render_standard_trim_sections(
                spec,
                target,
                schedule,
                context=context,
                resource_closure=cp_plan.resources.identities,
            )
            resources = tuple(
                resolve_pattern_resource(
                    requirement.logical_identity, platform, self._seed_root
                )
                for requirement in contribution.resource_requires
            )
            body_provisions = tuple(
                SymbolProvision(
                    RenderSymbolRef("TEST_BODY", f"{platform}:{entry.identity}"),
                    entry.render_name,
                    "SECTION",
                    None,
                    "TARGET",
                )
                for entry in schedule.entries
                if any(
                    projected.identity.casefold() == entry.identity.casefold()
                    for projected in contribution.schedule_entries
                )
            )
            contributions.append(replace(
                contribution,
                sections=sections,
                resources=resources,
                provides=contribution.provides + body_provisions,
            ))
        return contributions


def _platform_runtime_support(
    target: TargetKey, contributions: list[ProgramContribution]
) -> ProgramContribution:
    """Provide the runtime symbols every business contribution requires.

    The rendered names are deliberately semantic placeholders; the platform
    symbol table assigns the concrete identifiers at a later render step.  What
    matters here is that the Assembler can close the symbol graph.
    """
    provided = {
        provision.ref.identity.casefold()
        for contribution in contributions
        for provision in contribution.provides
    }
    provides: list[SymbolProvision] = []
    for contribution in contributions:
        for requirement in contribution.requires:
            key = requirement.ref.identity.casefold()
            if key in provided:
                continue
            provided.add(key)
            provides.append(
                SymbolProvision(
                    requirement.ref,
                    f"runtime:{requirement.ref.identity}",
                    requirement.value_type,
                    requirement.bit_width,
                    requirement.scope,
                )
            )
    return ProgramContribution(
        identity=f"platform:runtime:{target.identity}",
        target=target,
        provides=tuple(provides),
    )
