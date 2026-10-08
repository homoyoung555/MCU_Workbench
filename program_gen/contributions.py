"""Compile target-neutral product plans into target-bound business contracts.

This registry is the single fan-out point for business families whose typed
plans are already closed.  It does not provide platform source bytes; platform
render adapters close the declared body, helper, and resource requirements.
"""

from __future__ import annotations

from program_gen.compiler import ProductCompilation
from program_gen.core.os_contribution import compile_os_contribution
from program_gen.core.pdr_contribution import compile_pdr_contribution
from program_gen.core.pdr_verify_contribution import (
    compile_pdr_verify_contribution,
)
from program_gen.core.otp_program import PagePatternPlan
from program_gen.core.persistence_contribution import (
    compile_persistence_id_contribution,
)
from program_gen.core.standard_trim_contribution import (
    compile_standard_trim_contribution,
)
from program_gen.core.shmoo_contribution import compile_shmoo_contribution
from program_gen.render_plan import ProgramContribution, TargetKey


_FORMAL_CP2_STANDARD_ID_FLOW_ROW = 166
_FORMAL_CP2_STANDARD_ID_UID_PATTERNS = (
    PagePatternPlan(
        page="uid",
        erase_pattern="fbist_page_erase_uid",
        program_pattern="fbist_page_prog_cp2_id",
        read_pattern="fbist_page_read_cp2_id",
        is_uid=True,
    ),
)


class BusinessContributionError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def compile_business_contributions(
    compilation: ProductCompilation,
    target: TargetKey,
) -> tuple[ProgramContribution, ...]:
    """Project every currently closed business plan for one explicit target."""
    compilation.require_success()
    platform = target.platform.strip().casefold()
    if platform not in ("chroma", "s100"):
        raise BusinessContributionError(
            "BC.TARGET.PLATFORM",
            f"unsupported contribution target platform {target.platform!r}",
        )
    try:
        cp_plan = compilation.for_cp(target.cp)
    except KeyError as error:
        raise BusinessContributionError(
            "BC.TARGET.CP",
            f"product compilation has no target CP {target.cp!r}",
        ) from error
    schedule = cp_plan.canonical_schedule
    if schedule is None:
        raise BusinessContributionError(
            "BC.SCHEDULE.MISSING",
            f"target CP {target.cp!r} has no canonical schedule",
        )

    assert compilation.plan is not None
    catalogs = compilation.plan.catalogs
    cp_key = cp_plan.cp.casefold()
    contributions: list[ProgramContribution] = []

    for _row, spec in sorted(catalogs.trim_specs.items()):
        if spec.cp.casefold() == cp_key:
            contributions.append(
                compile_standard_trim_contribution(
                    spec,
                    target,
                    schedule,
                    resource_closure=cp_plan.resources.identities,
                )
            )
    for _row, plan in sorted(catalogs.dedicated_trim_plans.items()):
        if plan.cp.casefold() == cp_key:
            contributions.append(compile_pdr_contribution(plan, target, schedule))
    pdr_verify_plans = getattr(catalogs, "pdr_verify_plans", {})
    for _row, plan in sorted(pdr_verify_plans.get(platform, {}).items()):
        if plan.cp.casefold() == cp_key:
            contributions.append(
                compile_pdr_verify_contribution(plan, target, schedule)
            )
    for _row, plan in sorted(catalogs.os_plans[platform].items()):
        if plan.cp.casefold() == cp_key:
            contributions.append(compile_os_contribution(plan, target, cp_plan))
    for _row, plan in sorted(catalogs.shmoo_plans.items()):
        if plan.cp.casefold() == cp_key:
            contributions.append(
                compile_shmoo_contribution(plan, target, schedule)
            )
    if cp_key == "cp2":
        id_plan = catalogs.id_plans.for_row(_FORMAL_CP2_STANDARD_ID_FLOW_ROW)
        persistence_plan = catalogs.persistence.for_row(
            _FORMAL_CP2_STANDARD_ID_FLOW_ROW
        )
        if id_plan is not None and persistence_plan is not None:
            contributions.append(compile_persistence_id_contribution(
                target,
                schedule,
                id_plan,
                persistence_plan,
                _FORMAL_CP2_STANDARD_ID_UID_PATTERNS,
            ))

    ordinal_by_identity = {
        entry.identity.casefold(): ordinal
        for ordinal, entry in enumerate(schedule.entries)
    }
    return tuple(sorted(
        contributions,
        key=lambda contribution: (
            min(
                (
                    ordinal_by_identity[entry.identity.casefold()]
                    for entry in contribution.schedule_entries
                ),
                default=-1,
            ),
            contribution.identity.casefold(),
            contribution.identity,
        ),
    ))
