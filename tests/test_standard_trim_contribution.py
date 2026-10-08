from __future__ import annotations

from tests.workspace_paths import FORMAL_MASTER as EXTERNAL_FORMAL_MASTER

from dataclasses import replace
from pathlib import Path
import unittest

from pattern_bundle import PatternField
from program_gen.compiler import ProductCompiler
from program_gen.core.schedule_plan import (
    BinBinding,
    BinBindingKind,
    CanonicalScheduleDefinition,
    CanonicalScheduleEntry,
    CanonicalSchedulePlan,
)
from program_gen.core.standard_trim_contribution import (
    StandardTrimContributionError,
    compile_standard_trim_contribution,
)
from program_gen.core.trim_spec import (
    DacBinding,
    MeasurementPlan,
    SearchPlan,
    SearchVariant,
    TrimProtocolPlan,
    TrimOperation,
    TrimSpec,
)
from program_gen.render_plan import (
    ProgramAssembler,
    ProgramContribution,
    RenderSymbolRef,
    ResourceRequest,
    ResourceRequirement,
    ScheduleEntryContribution,
    SymbolProvision,
    SymbolRequirement,
    TargetKey,
    TestDefinitionContribution,
)
from program_gen.workbook import WorkbookReader


S100_TARGET = TargetKey("s100", "CP1", "lab", "V_TEST_CP1")
CHROMA_TARGET = TargetKey("chroma", "CP1", "lab", "V_TEST_CP1")
FORMAL_MASTER = (
    EXTERNAL_FORMAL_MASTER
)


class StandardTrimContributionTests(unittest.TestCase):
    def test_module_has_no_workbook_global_or_resource_provider_boundary(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "program_gen"
            / "core"
            / "standard_trim_contribution.py"
        ).read_text(encoding="utf-8")

        for forbidden in (
            'f"DEF:',
            'f"SCHEDULE:',
            "program_gen import state",
            "WorkbookReader",
            "pandas",
            "openpyxl",
            "ResourceRequest",
            "source_identity",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_projects_canonical_definition_and_all_trim_variants_without_text(self):
        spec = _trim_spec()
        schedule = _schedule(spec)

        contribution = compile_standard_trim_contribution(
            spec, S100_TARGET, schedule, resource_closure=_closure(spec)
        )

        definition = schedule.definitions[0]
        self.assertEqual(contribution.target, S100_TARGET)
        self.assertEqual(contribution.sections, ())
        self.assertEqual(contribution.resources, ())
        self.assertEqual(
            contribution.definitions,
            (TestDefinitionContribution(
                definition.identity,
                "STANDARD_TRIM",
                contribution.identity,
            ),),
        )
        self.assertEqual(
            contribution.schedule_entries,
            tuple(
                ScheduleEntryContribution(
                    entry.identity,
                    definition.identity,
                    index,
                    entry.enabled,
                )
                for index, entry in enumerate(schedule.entries)
            ),
        )

    def test_declares_result_own_helper_variant_bodies_and_pattern_consumption(self):
        spec = _trim_spec()
        schedule = _schedule(spec)

        contribution = compile_standard_trim_contribution(
            spec, S100_TARGET, schedule, resource_closure=_closure(spec)
        )

        self.assertEqual(
            contribution.provides,
            (SymbolProvision(
                RenderSymbolRef("RESULT", spec.dac_final_symbol),
                spec.dac_final_symbol,
                "INT",
                spec.dac.field_width,
                "SITE",
            ),),
        )
        self.assertEqual(
            contribution.requires,
            (
                SymbolRequirement(
                    RenderSymbolRef("HELPER", "set_vref0p8_abs_trim_data"),
                    "CALLABLE",
                    None,
                    "TARGET",
                ),
                *(
                    SymbolRequirement(
                        RenderSymbolRef(
                            "TEST_BODY", f"s100:{entry.identity}"
                        ),
                        "SECTION",
                        None,
                        "TARGET",
                    )
                    for entry in schedule.entries
                ),
            ),
        )
        self.assertEqual(
            contribution.resource_requires,
            tuple(
                ResourceRequirement(
                    f"pattern:{name}",
                    f"{name}.sd",
                    f"v13.pattern/1:s100:{name}",
                    "STANDARD_TRIM pattern",
                )
                for name in (
                    "enter_fbist_mode",
                    "enter_vref0p8_abs",
                    "set_iref1u_dac",
                    "set_vref0p8_abs_dac",
                    "exit_fbist_mode",
                )
            ),
        )

    def test_rejects_target_and_canonical_schedule_cp_mismatches(self):
        spec = _trim_spec()
        schedule = _schedule(spec)
        cases = (
            (
                TargetKey("s100", "CP2", "lab", "V_TEST_CP2"),
                schedule,
                "SC.TARGET.CP_MISMATCH",
            ),
            (
                S100_TARGET,
                CanonicalSchedulePlan(
                    "CP2", schedule.definitions, schedule.entries
                ),
                "SC.SCHEDULE.CP_MISMATCH",
            ),
        )
        for target, candidate_schedule, code in cases:
            with self.subTest(code=code), self.assertRaisesRegex(
                StandardTrimContributionError, code
            ):
                compile_standard_trim_contribution(
                    spec, target, candidate_schedule,
                    resource_closure=_closure(spec),
                )

    def test_refuses_to_project_pdr_or_bor_as_standard_trim(self):
        for item in ("Pdr_Trim", "Bor_Trim"):
            spec = _trim_spec(item=item)
            with self.subTest(item=item), self.assertRaisesRegex(
                StandardTrimContributionError, "SC.SPEC.DEDICATED_TRIM"
            ):
                compile_standard_trim_contribution(
                    spec, S100_TARGET, _schedule(spec),
                    resource_closure=_closure(spec),
                )

    def test_rejects_a_canonical_schedule_with_different_trim_variants(self):
        spec = _trim_spec()
        schedule = _schedule(spec)
        wrong_entry = replace(schedule.entries[1], variant="UNKNOWN")
        wrong_schedule = CanonicalSchedulePlan(
            schedule.cp,
            schedule.definitions,
            (schedule.entries[0], wrong_entry),
        )

        with self.assertRaisesRegex(
            StandardTrimContributionError, "SC.SCHEDULE.VARIANTS"
        ):
            compile_standard_trim_contribution(
                spec, S100_TARGET, wrong_schedule,
                resource_closure=_closure(spec),
            )

    def test_rejects_an_unregistered_target_platform(self):
        spec = _trim_spec()
        target = TargetKey("unknown", "CP1", "lab", "V_TEST_CP1")

        with self.assertRaisesRegex(
            StandardTrimContributionError, "SC.TARGET.PLATFORM"
        ):
            compile_standard_trim_contribution(
                spec, target, _schedule(spec), resource_closure=_closure(spec)
            )

    def test_contribution_closes_in_assembler_with_all_declared_variants(self):
        contribution = compile_standard_trim_contribution(
            _trim_spec(),
            S100_TARGET,
            _schedule(_trim_spec()),
            resource_closure=_closure(_trim_spec()),
        )
        support = _support_for(contribution)

        render_plan = ProgramAssembler().assemble(
            S100_TARGET, (contribution, support)
        )

        self.assertEqual(
            tuple(artifact.relative_path for artifact in render_plan.artifacts),
            tuple(sorted(
                requirement.relative_path
                for requirement in contribution.resource_requires
            )),
        )

    def test_formal_master_projects_one_cp1_trim_to_chroma_and_s100_contracts(self):
        compilation = ProductCompiler().compile(
            WorkbookReader().read(FORMAL_MASTER)
        ).require_success()
        spec = compilation.plan.catalogs.trim_specs[1]
        schedule = compilation.for_cp("CP1").canonical_schedule
        definition = next(
            definition
            for definition in schedule.definitions
            if definition.source_rows == (spec.flow_row_index + 2,)
        )
        canonical_entries = tuple(
            entry
            for entry in schedule.entries
            if entry.definition_id == definition.identity
        )
        canonical_ordinals = tuple(
            ordinal
            for ordinal, entry in enumerate(schedule.entries)
            if entry.definition_id == definition.identity
        )
        expected_patterns = (
            "enter_fbist_mode",
            "enter_vref0p8_tc",
            "set_vref0p8_abs_dac",
            "set_iref1u_dac",
            "set_vref0p8_tc_dac",
            "exit_fbist_mode",
        )

        for target, prefix, extension in (
            (CHROMA_TARGET, "pat/", ".pat"),
            (S100_TARGET, "", ".sd"),
        ):
            with self.subTest(platform=target.platform):
                contribution = compile_standard_trim_contribution(
                    spec, target, schedule, resource_closure=_closure(spec)
                )
                self.assertEqual(
                    contribution.definitions[0].identity,
                    definition.identity,
                )
                self.assertEqual(
                    tuple(entry.identity for entry in contribution.schedule_entries),
                    tuple(entry.identity for entry in canonical_entries),
                )
                self.assertEqual(
                    tuple(entry.ordinal for entry in contribution.schedule_entries),
                    canonical_ordinals,
                )
                self.assertEqual(
                    tuple(
                        requirement.relative_path
                        for requirement in contribution.resource_requires
                    ),
                    tuple(
                        f"{prefix}{name}{extension}"
                        for name in expected_patterns
                    ),
                )
                self.assertEqual(contribution.sections, ())
                self.assertEqual(contribution.resources, ())


def _trim_spec(**updates) -> TrimSpec:
    values = {
        "flow_row_index": 1,
        "cp": "CP1",
        "item": "Vref0p8_ABS",
        "mode": "fbist",
        "protocol": TrimProtocolPlan("enter_fbist_mode", "exit_fbist_mode"),
        "vcc": "VCC_TYP",
        "trim_tar_reference": None,
        "operations": (
            TrimOperation("ENTER", reference="enter_vref0p8_abs"),
            TrimOperation(
                "DEPEND",
                reference="set_iref1u_dac",
                value_source="DAC_FINAL",
                value="Iref1u",
                field_width=4,
                source_symbol="IREF1U_DAC_FINAL",
                helper_name="set_iref1u_trim_data",
            ),
            TrimOperation("TRIM", reference="set_vref0p8_abs_dac"),
            TrimOperation("JUDGE", reference="exit_fbist_mode"),
        ),
        "search": SearchPlan(
            search_bits=4,
            codes=tuple(range(16)),
            domain_source="FULL_RANGE",
            variants=(
                SearchVariant("BISECTION", True),
                SearchVariant("FULL_SCAN", False),
            ),
            per_point_actions=(
                TrimOperation(
                    "SET_DAC",
                    reference="set_vref0p8_abs_dac",
                    scope="EACH_SEARCH_POINT",
                ),
                TrimOperation("MEASURE", scope="EACH_SEARCH_POINT"),
            ),
        ),
        "dac": DacBinding(
            pattern_name="set_vref0p8_abs_dac",
            helper_name="set_vref0p8_abs_trim_data",
            field=PatternField(3, 0, "VREF[3:0]", "0000", True),
            field_width=4,
            default_value="0000",
        ),
        "measurement": MeasurementPlan(
            "VOLTAGE", "V", "VREF", "0uA", 0.8, -2, 2,
            None, None, None, None
        ),
        "dependencies": ("Iref1u",),
        "adjust": None,
        "dac_final_symbol": "VREF0P8_ABS_DAC_FINAL",
        "relay": None,
        "test_number": 50,
    }
    values.update(updates)
    return TrimSpec(**values)


def _schedule(spec: TrimSpec) -> CanonicalSchedulePlan:
    definition = CanonicalScheduleDefinition(
        "canonical-definition-id",
        spec.cp,
        spec.item,
        "Vref0P8_Abs_Trim",
        (spec.flow_row_index + 2,),
    )
    entries = tuple(
        CanonicalScheduleEntry(
            identity=f"opaque-schedule-id-{index}",
            definition_id=definition.identity,
            flow_order=17,
            variant_order=index,
            variant=variant.kind,
            render_name=(
                "Vref0P8_Abs_Trim"
                if variant.kind == "BISECTION"
                else "Vref0P8_Abs_Dac_Loop"
            ),
            enabled=variant.scheduled,
            force_pass=False,
            bin_binding=BinBinding(BinBindingKind.DIRECT, "1", "2"),
        )
        for index, variant in enumerate(spec.search.variants)
    )
    return CanonicalSchedulePlan(spec.cp, (definition,), entries)


def _closure(spec: TrimSpec) -> tuple[str, ...]:
    """The CP-style resource closure one recipe declares (platform-neutral)."""
    names = [spec.dac.pattern_name]
    names.extend(operation.reference for operation in spec.operations
                 if operation.reference)
    names.extend((spec.protocol.enter_pattern, spec.protocol.exit_pattern))
    return tuple(dict.fromkeys(name for name in names if name))


def _support_for(contribution: ProgramContribution) -> ProgramContribution:
    return ProgramContribution(
        identity=f"support:{contribution.target.identity}",
        target=contribution.target,
        provides=tuple(
            SymbolProvision(
                requirement.ref,
                requirement.ref.semantic_key,
                requirement.value_type,
                requirement.bit_width,
                requirement.scope,
            )
            for requirement in contribution.requires
        ),
        resources=tuple(
            ResourceRequest(
                requirement.logical_identity,
                requirement.relative_path,
                f"provider bytes for {requirement.logical_identity}",
                requirement.spec_identity,
                f"seed:{requirement.logical_identity}:ABC",
                requirement.purpose,
            )
            for requirement in contribution.resource_requires
        ),
    )


if __name__ == "__main__":
    unittest.main()
