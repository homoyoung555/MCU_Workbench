from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
import unittest

from program_gen.core.dedicated_trim import DedicatedTrimPlan
from program_gen.core.pdr_contribution import (
    PdrContributionError,
    compile_pdr_contribution,
)
from program_gen.core.schedule_plan import (
    BinBinding,
    BinBindingKind,
    CanonicalScheduleDefinition,
    CanonicalScheduleEntry,
    CanonicalSchedulePlan,
)
from program_gen.diagnostics import WorkbookProvenance
from program_gen.render_plan import (
    ProgramAssembler,
    ProgramContribution,
    RenderPlanError,
    RenderSymbolRef,
    ResourceRequest,
    ResourceRequirement,
    ScheduleEntryContribution,
    SymbolProvision,
    SymbolRequirement,
    TargetKey,
    TestDefinitionContribution,
)


S100_TARGET = TargetKey("s100", "CP1", "lab", "V_TEST_CP1")
CHROMA_TARGET = TargetKey("chroma", "CP1", "lab", "V_TEST_CP1")


class PdrContributionTests(unittest.TestCase):
    def test_contribution_consumes_canonical_definition_identity(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "program_gen" / "core" / "pdr_contribution.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn('f"DEF:', source)
        self.assertNotIn('f"SCHEDULE:', source)

    def test_compiles_typed_metadata_symbols_and_resources_without_tester_text(self):
        contribution = _compile(S100_TARGET)
        definition_identity = "DEF:CP1:trim:Pdr_Trim:(9,)"

        self.assertEqual(contribution.target, S100_TARGET)
        self.assertEqual(contribution.sections, ())
        self.assertEqual(contribution.resources, ())
        self.assertEqual(
            contribution.definitions,
            (TestDefinitionContribution(
                definition_identity,
                "PDR_TRIM",
                contribution.identity,
            ),),
        )
        self.assertEqual(
            contribution.schedule_entries,
            (ScheduleEntryContribution(
                f"SCHEDULE:{definition_identity}",
                definition_identity,
                0,
                True,
            ),),
        )
        self.assertEqual(
            contribution.provides,
            (SymbolProvision(
                RenderSymbolRef("RESULT", "PDR_DAC_FINAL"),
                "PDR_DAC_FINAL",
                "INT",
                4,
                "SITE",
            ),),
        )
        self.assertEqual(
            contribution.requires,
            (
                SymbolRequirement(
                    RenderSymbolRef("HELPER", "set_pdr_trim_data"),
                    "CALLABLE",
                    None,
                    "TARGET",
                ),
                SymbolRequirement(
                    RenderSymbolRef(
                        "TEST_BODY", f"s100:SCHEDULE:{definition_identity}"
                    ),
                    "SECTION",
                    None,
                    "TARGET",
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
                    f"PDR_TRIM {role} pattern",
                )
                for role, name in (
                    ("enter", "enter_fbist_mode"),
                    ("set", "set_all_final_vposp"),
                    ("dac", "set_pdr_dac"),
                    ("read", "read_status_mode"),
                    ("exit", "exit_fbist_mode"),
                )
            ),
        )

    def test_maps_resource_and_body_contracts_to_each_platform(self):
        definition_identity = "DEF:CP1:trim:Pdr_Trim:(9,)"
        for target, prefix, extension in (
            (S100_TARGET, "", ".sd"),
            (CHROMA_TARGET, "pat/", ".pat"),
        ):
            with self.subTest(platform=target.platform):
                contribution = _compile(target)
                self.assertEqual(
                    tuple(item.relative_path for item in contribution.resource_requires),
                    tuple(
                        f"{prefix}{name}{extension}"
                        for name in (
                            "enter_fbist_mode",
                            "set_all_final_vposp",
                            "set_pdr_dac",
                            "read_status_mode",
                            "exit_fbist_mode",
                        )
                    ),
                )
                self.assertTrue(all(
                    f":{target.platform}:" in item.spec_identity
                    for item in contribution.resource_requires
                ))
                body_requirement = next(
                    item for item in contribution.requires
                    if item.ref.namespace == "TEST_BODY"
                )
                self.assertEqual(
                    body_requirement.ref.semantic_key,
                    f"{target.platform}:SCHEDULE:{definition_identity}",
                )

    def test_shared_pattern_spec_identity_does_not_encode_the_pdr_consumer_role(self):
        contribution = _compile(S100_TARGET)

        self.assertEqual(
            tuple(item.spec_identity for item in contribution.resource_requires),
            tuple(
                f"v13.pattern/1:s100:{name}"
                for name in (
                    "enter_fbist_mode",
                    "set_all_final_vposp",
                    "set_pdr_dac",
                    "read_status_mode",
                    "exit_fbist_mode",
                )
            ),
        )

    def test_compiled_metadata_and_resource_contracts_are_immutable(self):
        contribution = _compile(S100_TARGET)

        with self.assertRaises(FrozenInstanceError):
            contribution.definitions[0].typed_kind = "STANDARD_TRIM"
        with self.assertRaises(FrozenInstanceError):
            contribution.schedule_entries[0].enabled = False
        with self.assertRaises(FrozenInstanceError):
            contribution.resource_requires[0].relative_path = "other.sd"

    def test_refuses_to_guess_a_pdr_contribution_for_bor(self):
        with self.assertRaisesRegex(PdrContributionError, "PC.PLAN.UNSUPPORTED.*Bor_Trim"):
            _compile(S100_TARGET, item="Bor_Trim")

    def test_rejects_a_target_for_a_different_cp(self):
        wrong_cp = TargetKey("s100", "CP2", "lab", "V_TEST_CP2")

        with self.assertRaisesRegex(PdrContributionError, "PC.TARGET.CP_MISMATCH"):
            _compile(wrong_cp)

    def test_rejects_an_unregistered_platform(self):
        target = TargetKey("unknown", "CP1", "lab", "V_TEST_CP1")

        with self.assertRaisesRegex(PdrContributionError, "PC.TARGET.PLATFORM"):
            _compile(target)

    def test_requires_the_frozen_pdr_protocol_contract(self):
        cases = (
            ({"effective_recipe": ("ENTER",)}, "PC.PLAN.RECIPE"),
            ({"search_variant": "BISECTION"}, "PC.PLAN.SEARCH"),
            ({"dac_bits": 5}, "PC.PLAN.DAC_BITS"),
        )
        for updates, code in cases:
            with self.subTest(code=code), self.assertRaisesRegex(
                PdrContributionError, code
            ):
                _compile(S100_TARGET, **updates)

    def test_assembler_closes_pdr_against_platform_body_helper_and_resources(self):
        contribution = _compile(S100_TARGET)
        support = _support_for(contribution)

        render_plan = ProgramAssembler().assemble(
            S100_TARGET, (contribution, support)
        )

        self.assertEqual(
            tuple(artifact.relative_path for artifact in render_plan.artifacts),
            tuple(sorted(
                item.relative_path for item in contribution.resource_requires
            )),
        )

    def test_assembler_rejects_conflicting_pdr_symbol_and_resource_providers(self):
        contribution = _compile(S100_TARGET)
        support = _support_for(contribution)
        result = contribution.provides[0]
        symbol_conflict = ProgramContribution(
            identity="conflict:symbol",
            target=S100_TARGET,
            provides=(SymbolProvision(
                result.ref,
                result.rendered_name,
                result.value_type,
                5,
                result.scope,
            ),),
        )
        with self.assertRaisesRegex(RenderPlanError, "RP.SYMBOL.CONFLICT"):
            ProgramAssembler().assemble(
                S100_TARGET, (contribution, support, symbol_conflict)
            )

        first_resource = support.resources[0]
        resource_conflict = ProgramContribution(
            identity="conflict:resource",
            target=S100_TARGET,
            resources=(ResourceRequest(
                first_resource.logical_identity,
                first_resource.relative_path,
                b"different pattern",
                first_resource.spec_identity + ":different",
                "seed:different",
            ),),
        )
        with self.assertRaisesRegex(RenderPlanError, "RP.RESOURCE.CONFLICT"):
            ProgramAssembler().assemble(
                S100_TARGET, (contribution, support, resource_conflict)
            )


def _pdr_plan(**updates) -> DedicatedTrimPlan:
    values = {
        "flow_row_index": 7,
        "cp": "CP1",
        "item": "Pdr_Trim",
        "typed_kind": "PDR_TRIM",
        "effective_recipe": ("PDR_TRIM",),
        "search_variant": "PDR_STATUS_TRANSITION",
        "dac_bits": 4,
        "search_codes": (8, 9, 10, 11, 12, 13, 14, 15, 0, 1, 2, 3, 4, 5, 6, 7),
        "initial_vcc": "VCC_TYP",
        "relay": None,
        "test_number": 1650,
        "pdr_min_voltage": "2.31",
        "pdr_target_voltage": "2.37",
        "pdr_max_voltage": "2.43",
        "dac_pattern_name": "set_pdr_dac",
        "helper_name": "set_pdr_trim_data",
        "write_pin": "PA13",
        "provenance": WorkbookProvenance(
            "FLOW", "A9", "workbook-id", "SOURCE-SHA"
        ),
    }
    values.update(updates)
    return DedicatedTrimPlan(**values)


def _compile(target: TargetKey, **updates) -> ProgramContribution:
    plan = _pdr_plan(**updates)
    definition_identity = "DEF:CP1:trim:Pdr_Trim:(9,)"
    schedule = CanonicalSchedulePlan(
        cp=plan.cp,
        definitions=(CanonicalScheduleDefinition(
            definition_identity,
            plan.cp,
            plan.item,
            plan.item,
            (plan.flow_row_index + 2,),
        ),),
        entries=(CanonicalScheduleEntry(
            f"SCHEDULE:{definition_identity}",
            definition_identity,
            plan.flow_row_index,
            0,
            None,
            plan.item,
            True,
            False,
            BinBinding(BinBindingKind.DIRECT, "1", "1"),
        ),),
    )
    return compile_pdr_contribution(plan, target, schedule)


def _support_for(contribution) -> ProgramContribution:
    symbol_providers = tuple(
        SymbolProvision(
            requirement.ref,
            "set_pdr_trim_data"
            if requirement.ref.namespace == "HELPER"
            else f"pdr_body_{contribution.target.platform}",
            requirement.value_type,
            requirement.bit_width,
            requirement.scope,
        )
        for requirement in contribution.requires
    )
    resource_providers = tuple(
        ResourceRequest(
            requirement.logical_identity,
            requirement.relative_path,
            f"provider bytes for {requirement.logical_identity}",
            requirement.spec_identity,
            f"seed:{requirement.logical_identity}:ABC",
            requirement.purpose,
        )
        for requirement in contribution.resource_requires
    )
    return ProgramContribution(
        identity=f"support:{contribution.target.identity}",
        target=contribution.target,
        provides=symbol_providers,
        resources=resource_providers,
    )


if __name__ == "__main__":
    unittest.main()
