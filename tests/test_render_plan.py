from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from program_gen.render_plan import (
    ArtifactMaterializer,
    ArtifactPlan,
    ProgramAssembler,
    ProgramContribution,
    RenderPlan,
    RenderPlanError,
    ResourceRequest,
    ResourceRequirement,
    RenderSymbolRef,
    SymbolProvision,
    SymbolRequirement,
    SectionFragment,
    ScheduleEntryContribution,
    TargetKey,
    TestDefinitionContribution,
)


TARGET = TargetKey("s100", "CP1", "lab", "V_TEST_CP1")


class ProgramAssemblerTests(unittest.TestCase):
    def test_metadata_only_definition_and_schedule_do_not_materialize_artifacts(self):
        definition = TestDefinitionContribution(
            identity="DEF:CP1:trim:Pdr_Trim:(9,)",
            typed_kind="PDR_TRIM",
            owner_id="pdr:cp1:row7",
        )
        schedule = ScheduleEntryContribution(
            identity="SCHEDULE:DEF:CP1:trim:Pdr_Trim:(9,)",
            definition_identity=definition.identity,
            ordinal=7,
            enabled=True,
        )
        contribution = ProgramContribution(
            identity="pdr:cp1:row7",
            target=TARGET,
            definitions=(definition,),
            schedule_entries=(schedule,),
        )

        plan = ProgramAssembler().assemble(TARGET, (contribution,))

        self.assertEqual(plan.artifacts, ())

    def test_schedule_requires_a_known_definition(self):
        contribution = ProgramContribution(
            identity="schedule-only",
            target=TARGET,
            schedule_entries=(ScheduleEntryContribution(
                identity="SCHEDULE:missing",
                definition_identity="DEF:missing",
                ordinal=1,
                enabled=True,
            ),),
        )

        with self.assertRaisesRegex(RenderPlanError, "RP.SCHEDULE.DEFINITION_MISSING"):
            ProgramAssembler().assemble(TARGET, (contribution,))

    def test_definition_identity_conflicts_are_blocking(self):
        left = ProgramContribution(
            identity="left",
            target=TARGET,
            definitions=(TestDefinitionContribution("DEF:pdr", "PDR_TRIM", "left"),),
        )
        right = ProgramContribution(
            identity="right",
            target=TARGET,
            definitions=(TestDefinitionContribution("DEF:pdr", "STANDARD_TRIM", "right"),),
        )

        with self.assertRaisesRegex(RenderPlanError, "RP.DEFINITION.CONFLICT"):
            ProgramAssembler().assemble(TARGET, (left, right))

    def test_definition_identity_has_exactly_one_owner(self):
        definition = TestDefinitionContribution("DEF:pdr", "PDR_TRIM", "pdr-owner")
        left = ProgramContribution(
            identity="left", target=TARGET, definitions=(definition,)
        )
        right = ProgramContribution(
            identity="right", target=TARGET, definitions=(definition,)
        )

        with self.assertRaisesRegex(RenderPlanError, "RP.DEFINITION.DUPLICATE"):
            ProgramAssembler().assemble(TARGET, (left, right))

    def test_definition_and_schedule_require_stable_identities(self):
        missing_definition = ProgramContribution(
            identity="missing-definition-id",
            target=TARGET,
            definitions=(TestDefinitionContribution("", "PDR_TRIM", "owner"),),
        )
        with self.assertRaisesRegex(RenderPlanError, "RP.DEFINITION.IDENTITY_MISSING"):
            ProgramAssembler().assemble(TARGET, (missing_definition,))

        definition = TestDefinitionContribution("DEF:pdr", "PDR_TRIM", "owner")
        missing_schedule = ProgramContribution(
            identity="missing-schedule-id",
            target=TARGET,
            definitions=(definition,),
            schedule_entries=(ScheduleEntryContribution(
                "", definition.identity, 7, True
            ),),
        )
        with self.assertRaisesRegex(RenderPlanError, "RP.SCHEDULE.IDENTITY_MISSING"):
            ProgramAssembler().assemble(TARGET, (missing_schedule,))

    def test_schedule_identity_conflicts_are_blocking(self):
        definition = TestDefinitionContribution("DEF:pdr", "PDR_TRIM", "pdr")
        left = ProgramContribution(
            identity="left",
            target=TARGET,
            definitions=(definition,),
            schedule_entries=(ScheduleEntryContribution(
                "SCHEDULE:pdr", definition.identity, 1, True
            ),),
        )
        right = ProgramContribution(
            identity="right",
            target=TARGET,
            schedule_entries=(ScheduleEntryContribution(
                "SCHEDULE:pdr", definition.identity, 2, True
            ),),
        )

        with self.assertRaisesRegex(RenderPlanError, "RP.SCHEDULE.CONFLICT"):
            ProgramAssembler().assemble(TARGET, (left, right))

    def test_schedule_ordinal_conflicts_are_blocking(self):
        first = TestDefinitionContribution("DEF:first", "PDR_TRIM", "first")
        second = TestDefinitionContribution("DEF:second", "PDR_TRIM", "second")
        contribution = ProgramContribution(
            identity="two-schedules",
            target=TARGET,
            definitions=(first, second),
            schedule_entries=(
                ScheduleEntryContribution("SCHEDULE:first", first.identity, 7, True),
                ScheduleEntryContribution("SCHEDULE:second", second.identity, 7, True),
            ),
        )

        with self.assertRaisesRegex(RenderPlanError, "RP.SCHEDULE.ORDINAL_CONFLICT"):
            ProgramAssembler().assemble(TARGET, (contribution,))

    def test_resource_requirements_close_against_deduplicated_providers(self):
        requirement = ResourceRequirement(
            logical_identity="pattern:enter_fbist_mode",
            relative_path="enter_fbist_mode.sd",
            spec_identity="v13.pattern:enter_fbist_mode:s100:1",
            purpose="PDR enter",
        )
        consumer = ProgramContribution(
            identity="consumer",
            target=TARGET,
            resource_requires=(requirement,),
        )
        provider = ResourceRequest(
            logical_identity=requirement.logical_identity,
            relative_path=requirement.relative_path,
            content=b"PATTERN\r\n",
            spec_identity=requirement.spec_identity,
            source_identity="seed:enter_fbist_mode.sd:ABC",
            purpose="shared FBIST enter",
        )
        first_provider = ProgramContribution(
            identity="provider:first", target=TARGET, resources=(provider,)
        )
        second_provider = ProgramContribution(
            identity="provider:second", target=TARGET,
            resources=(ResourceRequest(
                provider.logical_identity,
                provider.relative_path,
                provider.content,
                provider.spec_identity,
                provider.source_identity,
                "same provider through another feature",
            ),),
        )

        plan = ProgramAssembler().assemble(
            TARGET, (consumer, first_provider, second_provider)
        )

        self.assertEqual(
            tuple(artifact.relative_path for artifact in plan.artifacts),
            ("enter_fbist_mode.sd",),
        )

    def test_resource_requirement_without_provider_is_blocking(self):
        consumer = ProgramContribution(
            identity="consumer",
            target=TARGET,
            resource_requires=(ResourceRequirement(
                "pattern:read_status_mode",
                "read_status_mode.sd",
                "v13.pattern:read_status_mode:s100:1",
            ),),
        )

        with self.assertRaisesRegex(RenderPlanError, "RP.RESOURCE.MISSING"):
            ProgramAssembler().assemble(TARGET, (consumer,))

    def test_resource_requirement_spec_mismatch_is_blocking(self):
        consumer = ProgramContribution(
            identity="consumer",
            target=TARGET,
            resource_requires=(ResourceRequirement(
                "pattern:read_status_mode",
                "read_status_mode.sd",
                "v13.pattern:read_status_mode:s100:2",
            ),),
        )
        provider = ProgramContribution(
            identity="provider",
            target=TARGET,
            resources=(ResourceRequest(
                "pattern:read_status_mode",
                "read_status_mode.sd",
                b"PATTERN",
                "v13.pattern:read_status_mode:s100:1",
                "generated:read_status_mode:ABC",
            ),),
        )

        with self.assertRaisesRegex(RenderPlanError, "RP.RESOURCE.CONTRACT_MISMATCH"):
            ProgramAssembler().assemble(TARGET, (consumer, provider))

    def test_empty_feature_set_still_emits_the_required_platform_skeleton(self):
        skeleton = SectionFragment(
            "program/main.prg", "SKELETON", "skeleton:main", b"PROGRAM\nEND\n"
        )
        plan = ProgramAssembler(
            section_order=("SKELETON",), required_skeleton=(skeleton,)
        ).assemble(TARGET, ())

        self.assertEqual(plan.artifact("program/main.prg").content, b"PROGRAM\nEND\n")

    def test_symbol_graph_is_closed_before_artifacts_exist(self):
        ref = RenderSymbolRef("RESULT", "ADC_FINAL")
        provider = ProgramContribution(
            identity="provider",
            target=TARGET,
            provides=(SymbolProvision(ref, "REG_ADC_FINAL", "INT", 16, "SITE"),),
        )
        consumer = ProgramContribution(
            identity="consumer",
            target=TARGET,
            requires=(SymbolRequirement(ref, "INT", 16, "SITE"),),
        )

        ProgramAssembler().assemble(TARGET, (provider, consumer))
        with self.assertRaisesRegex(RenderPlanError, "RP.SYMBOL.MISSING"):
            ProgramAssembler().assemble(TARGET, (consumer,))

        wrong_width = ProgramContribution(
            identity="wrong-width",
            target=TARGET,
            requires=(SymbolRequirement(ref, "INT", 8, "SITE"),),
        )
        with self.assertRaisesRegex(RenderPlanError, "RP.SYMBOL.CONTRACT_MISMATCH"):
            ProgramAssembler().assemble(TARGET, (provider, wrong_width))

        conflicting = ProgramContribution(
            identity="conflicting",
            target=TARGET,
            provides=(SymbolProvision(ref, "REG_ADC_FINAL", "FLOAT", 32, "SITE"),),
        )
        with self.assertRaisesRegex(RenderPlanError, "RP.SYMBOL.CONFLICT"):
            ProgramAssembler().assemble(TARGET, (provider, conflicting))

    def test_contributions_close_into_a_deterministic_render_plan(self):
        body = ProgramContribution(
            identity="test:adc",
            target=TARGET,
            sections=(
                SectionFragment(
                    artifact_path="program/main.prg",
                    section="TESTS",
                    identity="test:adc:body",
                    content=b"test adc\n",
                    order=20,
                ),
            ),
            resources=(
                ResourceRequest(
                    logical_identity="pattern:adc",
                    relative_path="patterns/adc.pat",
                    content=b"PATTERN\r\n",
                    spec_identity="ADC:v1",
                    source_identity="workbook:pattern!A2",
                    purpose="shared ADC support",
                ),
            ),
        )
        support = ProgramContribution(
            identity="support:adc",
            target=TARGET,
            sections=(
                SectionFragment(
                    artifact_path="program/main.prg",
                    section="HELPERS",
                    identity="helper:adc",
                    content=b"helper adc\n",
                    order=10,
                ),
                SectionFragment(
                    artifact_path="program/main.prg",
                    section="FLOW",
                    identity="flow:adc",
                    content=b"run adc\n",
                    order=30,
                    depends_on=("test:adc:body",),
                ),
            ),
            # An identical request is one logical resource, not a second file.
            resources=(
                ResourceRequest(
                    logical_identity="pattern:adc",
                    relative_path="patterns/adc.pat",
                    content=b"PATTERN\r\n",
                    spec_identity="ADC:v1",
                    source_identity="workbook:pattern!A2",
                    purpose="ADC test",
                ),
            ),
        )
        assembler = ProgramAssembler(
            section_order=("DECLARATIONS", "HELPERS", "TESTS", "FLOW")
        )

        first = assembler.assemble(TARGET, (body, support))
        second = assembler.assemble(TARGET, (support, body))

        self.assertEqual(first, second)
        self.assertEqual(first.target, TARGET)
        self.assertEqual(first.target_relative_root, "V_TEST_CP1")
        self.assertEqual(
            tuple(artifact.relative_path for artifact in first.artifacts),
            ("patterns/adc.pat", "program/main.prg"),
        )
        self.assertEqual(first.artifact("program/main.prg").content, b"helper adc\ntest adc\nrun adc\n")
        self.assertEqual(first.artifact("patterns/adc.pat").owners, ("pattern:adc",))
        manifest = json.loads(first.manifest_json)
        self.assertEqual(manifest["schema"], "v13.render-manifest/1")
        self.assertEqual(manifest["artifacts"][0]["path"], "patterns/adc.pat")
        self.assertEqual(
            first.identity,
            hashlib.sha256(first.manifest_json.encode("utf-8")).hexdigest().upper(),
        )

    def test_dependency_and_identity_conflicts_fail_before_materialization(self):
        assembler = ProgramAssembler(section_order=("HELPERS", "TESTS"))
        missing = ProgramContribution(
            identity="missing",
            target=TARGET,
            sections=(
                SectionFragment(
                    "main.prg", "TESTS", "test:a", b"A", depends_on=("helper:a",)
                ),
            ),
        )
        with self.assertRaisesRegex(RenderPlanError, "RP.FRAGMENT.DEPENDENCY_MISSING"):
            assembler.assemble(TARGET, (missing,))

        conflict_a = ProgramContribution(
            identity="a", target=TARGET,
            sections=(SectionFragment("main.prg", "TESTS", "test:a", b"A"),),
        )
        conflict_b = ProgramContribution(
            identity="b", target=TARGET,
            sections=(SectionFragment("main.prg", "TESTS", "test:a", b"B"),),
        )
        with self.assertRaisesRegex(RenderPlanError, "RP.FRAGMENT.CONFLICT"):
            assembler.assemble(TARGET, (conflict_a, conflict_b))

        resource_a = ProgramContribution(
            identity="resource-a", target=TARGET,
            resources=(ResourceRequest("pattern:a", "a.pat", b"A", "v1", "source:a"),),
        )
        resource_b = ProgramContribution(
            identity="resource-b", target=TARGET,
            resources=(ResourceRequest("pattern:a", "a.pat", b"B", "v2", "source:b"),),
        )
        with self.assertRaisesRegex(RenderPlanError, "RP.RESOURCE.CONFLICT"):
            assembler.assemble(TARGET, (resource_a, resource_b))

        wrong_target = ProgramContribution(
            identity="wrong-target",
            target=TargetKey("chroma", "CP1", "lab", "V_TEST_CP1"),
        )
        with self.assertRaisesRegex(RenderPlanError, "RP.TARGET.MISMATCH"):
            assembler.assemble(TARGET, (wrong_target,))


class ArtifactMaterializerTests(unittest.TestCase):
    def test_stub_provenance_survives_materialization_as_release_blocker(self):
        contribution = ProgramContribution(
            identity="stub-provider",
            target=TARGET,
            resources=(ResourceRequest(
                "pattern:adc-swd",
                "adc-swd.sd",
                b"STUB PATTERN",
                "v13.pattern/1:s100:adc-swd",
                "generated:s100:adc-swd:STUB:sha256:ABC",
                "STUB ADC SWD Pattern; structural compile only",
            ),),
        )
        plan = ProgramAssembler().assemble(TARGET, (contribution,))

        self.assertEqual(
            plan.release_blockers,
            ("STUB:pattern:adc-swd:adc-swd.sd",),
        )
        manifest = json.loads(plan.manifest_json)
        self.assertEqual(
            manifest["artifacts"][0]["release_blockers"],
            ["STUB:pattern:adc-swd:adc-swd.sd"],
        )
        with TemporaryDirectory() as temp:
            staging = Path(temp) / "staging"
            staging.mkdir()
            result = ArtifactMaterializer().materialize(plan, staging)

        self.assertEqual(result.release_blockers, plan.release_blockers)

    def test_materializer_writes_only_an_explicit_empty_staging_directory(self):
        artifact = ArtifactPlan(
            relative_path="nested/program.prg",
            content=b"program\r\n",
            kind="PROGRAM",
            owners=("program",),
        )
        plan = RenderPlan.from_artifacts(TARGET, (artifact,))

        with TemporaryDirectory() as temp:
            parent = Path(temp)
            staging = parent / "staging"
            staging.mkdir()

            result = ArtifactMaterializer().materialize(plan, staging)

            self.assertEqual(result.root, staging.resolve())
            self.assertEqual(result.target, TARGET)
            self.assertEqual(result.manifest_identity, plan.identity)
            self.assertEqual((staging / "nested" / "program.prg").read_bytes(), b"program\r\n")
            self.assertEqual(
                (staging / ".render-manifest.json").read_text(encoding="utf-8"),
                plan.manifest_json,
            )

            with self.assertRaisesRegex(RenderPlanError, "RP.STAGING.NOT_EMPTY"):
                ArtifactMaterializer().materialize(plan, staging)
            with self.assertRaisesRegex(RenderPlanError, "RP.STAGING.MISSING"):
                ArtifactMaterializer().materialize(plan, parent / "not-created")

    def test_each_artifact_is_hash_verified_and_renamed_from_a_private_temp(self):
        artifact = ArtifactPlan("program.prg", b"program", "PROGRAM", ("p",))
        plan = RenderPlan.from_artifacts(TARGET, (artifact,))
        replacements = []

        def replace(source, destination):
            replacements.append((Path(source).name, Path(destination).name))
            Path(source).replace(destination)

        with TemporaryDirectory() as temp:
            staging = Path(temp) / "staging"
            staging.mkdir()
            result = ArtifactMaterializer(replace=replace).materialize(plan, staging)

        self.assertEqual(result.artifacts[0].sha256, artifact.sha256)
        self.assertTrue(replacements[0][0].startswith(".program.prg.tmp-"))
        self.assertEqual(replacements[0][1], "program.prg")

    def test_materializer_rejects_unsafe_or_conflicting_paths_before_any_write(self):
        unsafe_paths = (
            "/absolute/file.prg",
            "C:\\formal\\file.prg",
            "..\\formal\\file.prg",
            "safe/../formal/file.prg",
        )
        for relative_path in unsafe_paths:
            with self.subTest(relative_path=relative_path), TemporaryDirectory() as temp:
                staging = Path(temp) / "staging"
                staging.mkdir()
                plan = RenderPlan.from_artifacts(TARGET, (
                    ArtifactPlan(relative_path, b"x", "RESOURCE", ("x",)),
                ))

                with self.assertRaisesRegex(RenderPlanError, "RP.PATH"):
                    ArtifactMaterializer().materialize(plan, staging)

                self.assertEqual(tuple(staging.iterdir()), ())

        collisions = (
            (
                ArtifactPlan("Patterns/A.pat", b"x", "RESOURCE", ("a",)),
                ArtifactPlan("patterns/a.PAT", b"x", "RESOURCE", ("a",)),
                "RP.PATH.WINDOWS_COLLISION",
            ),
            (
                ArtifactPlan("patterns/a.pat", b"x", "RESOURCE", ("a",)),
                ArtifactPlan("patterns/a.pat", b"y", "RESOURCE", ("b",)),
                "RP.ARTIFACT.CONTENT_CONFLICT",
            ),
        )
        for left, right, code in collisions:
            with self.subTest(code=code), TemporaryDirectory() as temp:
                staging = Path(temp) / "staging"
                staging.mkdir()
                plan = RenderPlan.from_artifacts(TARGET, (left, right))

                with self.assertRaisesRegex(RenderPlanError, code):
                    ArtifactMaterializer().materialize(plan, staging)

                self.assertEqual(tuple(staging.iterdir()), ())


if __name__ == "__main__":
    unittest.main()
