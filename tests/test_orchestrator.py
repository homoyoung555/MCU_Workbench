from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from program_gen.orchestrator import (
    GenerationOrchestrator,
    GenerationRequest,
    GenerationTarget,
    OrchestrationError,
    OrchestrationStatus,
)
from program_gen.publisher import PublishResult, PublishStatus
from program_gen.render_plan import ArtifactSet, TargetKey
from program_gen.validation import ValidationCommand


def _target(
    root: Path, platform: str, cp: str, variant: str, program_name: str
) -> GenerationTarget:
    key = TargetKey(platform, cp, variant, program_name)
    parent = root / platform.casefold() / cp.casefold() / variant.casefold()
    parent.mkdir(parents=True, exist_ok=True)
    staging = parent / f".{program_name}.staging"
    staging.mkdir()
    final = parent / program_name
    return GenerationTarget(
        key=key,
        staging_directory=staging,
        final_directory=final,
        validation_command=ValidationCommand(
            f"{platform.casefold()}-compiler:v1",
            (f"{platform.casefold()}-compiler", program_name),
        ),
    )


class _Compilation:
    def __init__(self, identity="COMPILATION-A", valid=True):
        self.identity = identity
        self.is_valid = valid
        self.cp_plans = {"CP1": object(), "CP2": object(), "CP3": object()}


class _Publisher:
    def __init__(self):
        self.requests = []

    def publish(self, request):
        self.requests.append(request)
        return PublishResult(
            PublishStatus.PUBLISHED,
            Path("unused-journal"),
            tuple(target.target_id for target in request.targets),
        )


class GenerationOrchestratorTests(unittest.TestCase):
    def test_one_compilation_fans_out_in_deterministic_target_order_then_publishes(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            cp2 = _target(root, "S100", "CP2", "LAB", "V_DEMO_CP2")
            cp1 = _target(root, "Chroma", "CP1", "Production", "V_DEMO_CP1")
            forward = GenerationRequest("COMPILATION-A", root, (cp2, cp1))
            reverse = GenerationRequest("COMPILATION-A", root, (cp1, cp2))
            self.assertEqual(forward, reverse)
            self.assertEqual(forward.identity, reverse.identity)
            self.assertEqual(
                tuple(target.key.identity for target in forward.targets),
                (
                    "Chroma:CP1:Production:V_DEMO_CP1",
                    "S100:CP2:LAB:V_DEMO_CP2",
                ),
            )

            compilation = _Compilation()
            render_calls = []

            def render(received_compilation, context):
                render_calls.append((received_compilation, context))
                return ArtifactSet(
                    context.target,
                    context.staging_directory.resolve(),
                    (),
                    f"MANIFEST:{context.target.identity}",
                )

            class Validator:
                def __init__(self):
                    self.calls = []

                def validate(self, artifacts, command):
                    self.calls.append((artifacts, command))
                    return SimpleNamespace(
                        target=artifacts.target,
                        passed=True,
                        identity=f"VALID:{artifacts.target.identity}",
                    )

            validator = Validator()
            publisher = _Publisher()

            result = GenerationOrchestrator(
                staging_renderer=render,
                validator=validator,
                publisher=publisher,
            ).execute(forward, compilation)

            self.assertEqual(result.status, OrchestrationStatus.PUBLISHED)
            self.assertTrue(result.published)
            self.assertEqual(result.request_identity, forward.identity)
            self.assertEqual(len(render_calls), 2)
            self.assertTrue(all(item[0] is compilation for item in render_calls))
            self.assertTrue(
                all(item[1].request_identity == forward.identity for item in render_calls)
            )
            self.assertEqual(len(validator.calls), 2)
            self.assertEqual(len(publisher.requests), 1)
            published_request = publisher.requests[0]
            self.assertEqual(published_request.request_id, forward.identity)
            self.assertEqual(
                tuple(target.target_id for target in published_request.targets),
                tuple(target.key.identity for target in forward.targets),
            )
            self.assertTrue(
                all(target.validation_passed for target in published_request.targets)
            )

    def test_any_render_failure_blocks_publisher_but_other_targets_are_still_audited(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            cp1 = _target(root, "Chroma", "CP1", "LAB", "V_DEMO_CP1")
            cp2 = _target(root, "S100", "CP2", "LAB", "V_DEMO_CP2")
            request = GenerationRequest("COMPILATION-A", root, (cp1, cp2))
            rendered = []

            def render(compilation, context):
                rendered.append(context.target.identity)
                if context.target.cp == "CP1":
                    raise RuntimeError("injected render failure")
                return ArtifactSet(
                    context.target,
                    context.staging_directory.resolve(),
                    (),
                    "MANIFEST-CP2",
                )

            class Validator:
                def __init__(self):
                    self.calls = []

                def validate(self, artifacts, command):
                    self.calls.append(artifacts.target.identity)
                    return SimpleNamespace(
                        target=artifacts.target, passed=True, identity="VALID-CP2"
                    )

            validator = Validator()
            publisher = _Publisher()

            result = GenerationOrchestrator(
                staging_renderer=render,
                validator=validator,
                publisher=publisher,
            ).execute(request, _Compilation())

            self.assertEqual(result.status, OrchestrationStatus.RENDER_FAILED)
            self.assertFalse(result.published)
            self.assertEqual(len(rendered), 2)
            self.assertEqual(validator.calls, ["S100:CP2:LAB:V_DEMO_CP2"])
            self.assertEqual(publisher.requests, [])
            self.assertEqual(
                tuple(item.target.identity for item in result.targets),
                tuple(target.key.identity for target in request.targets),
            )

    def test_any_validation_failure_blocks_request_level_publication(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            cp1 = _target(root, "Chroma", "CP1", "LAB", "V_DEMO_CP1")
            cp2 = _target(root, "S100", "CP2", "LAB", "V_DEMO_CP2")
            request = GenerationRequest("COMPILATION-A", root, (cp1, cp2))

            def render(compilation, context):
                return ArtifactSet(
                    context.target,
                    context.staging_directory.resolve(),
                    (),
                    f"MANIFEST:{context.target.identity}",
                )

            class Validator:
                def validate(self, artifacts, command):
                    passed = artifacts.target.cp != "CP2"
                    return SimpleNamespace(
                        target=artifacts.target,
                        passed=passed,
                        identity=f"VALID:{passed}:{artifacts.target.identity}",
                    )

            publisher = _Publisher()
            result = GenerationOrchestrator(
                staging_renderer=render,
                validator=Validator(),
                publisher=publisher,
            ).execute(request, _Compilation())

            self.assertEqual(result.status, OrchestrationStatus.VALIDATION_FAILED)
            self.assertFalse(result.published)
            self.assertEqual(publisher.requests, [])
            self.assertEqual(
                tuple(item.validation_passed for item in result.targets),
                (True, False),
            )

    def test_release_blockers_are_validated_but_never_published(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            target = _target(root, "S100", "CP1", "LAB", "V_DEMO_CP1")
            request = GenerationRequest("COMPILATION-A", root, (target,))
            validation_calls = []

            def render(_compilation, context):
                return ArtifactSet(
                    context.target,
                    context.staging_directory.resolve(),
                    (),
                    "MANIFEST:STUB",
                    ("STUB:pattern:firmware:firmware.sd",),
                )

            class Validator:
                def validate(self, artifacts, _command):
                    validation_calls.append(artifacts.target.identity)
                    return SimpleNamespace(
                        target=artifacts.target,
                        passed=True,
                        identity="VALID:STRUCTURAL",
                    )

            publisher = _Publisher()
            result = GenerationOrchestrator(
                staging_renderer=render,
                validator=Validator(),
                publisher=publisher,
            ).execute(request, _Compilation())

            self.assertEqual(validation_calls, [target.key.identity])
            self.assertEqual(result.status, OrchestrationStatus.VALIDATION_FAILED)
            self.assertFalse(result.targets[0].validation_passed)
            self.assertIn("OR.RELEASE.STUB_BLOCKED", result.targets[0].error)
            self.assertEqual(publisher.requests, [])

    def test_explicit_stub_waiver_publishes_only_stub_blockers(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            target = _target(root, "S100", "CP1", "LAB", "V_DEMO_CP1")
            request = GenerationRequest("COMPILATION-A", root, (target,))

            def render(_compilation, context):
                return ArtifactSet(
                    context.target,
                    context.staging_directory.resolve(),
                    (),
                    "MANIFEST:STUB",
                    ("STUB:pattern:firmware:firmware.sd",),
                )

            class Validator:
                def validate(self, artifacts, _command):
                    return SimpleNamespace(
                        target=artifacts.target,
                        passed=True,
                        identity="VALID:STRUCTURAL",
                    )

            publisher = _Publisher()
            result = GenerationOrchestrator(
                staging_renderer=render,
                validator=Validator(),
                publisher=publisher,
                allow_stub_publication=True,
            ).execute(request, _Compilation())

            self.assertTrue(result.published)
            self.assertTrue(result.targets[0].validation_passed)
            self.assertEqual(len(publisher.requests), 1)

    def test_stub_waiver_does_not_bypass_other_release_blockers(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            target = _target(root, "S100", "CP1", "LAB", "V_DEMO_CP1")
            request = GenerationRequest("COMPILATION-A", root, (target,))

            def render(_compilation, context):
                return ArtifactSet(
                    context.target,
                    context.staging_directory.resolve(),
                    (),
                    "MANIFEST:BLOCKED",
                    ("SECURITY:unsigned-resource",),
                )

            class Validator:
                def validate(self, artifacts, _command):
                    return SimpleNamespace(
                        target=artifacts.target,
                        passed=True,
                        identity="VALID:STRUCTURAL",
                    )

            publisher = _Publisher()
            result = GenerationOrchestrator(
                staging_renderer=render,
                validator=Validator(),
                publisher=publisher,
                allow_stub_publication=True,
            ).execute(request, _Compilation())

            self.assertFalse(result.published)
            self.assertEqual(publisher.requests, [])

    def test_compilation_identity_and_cp_membership_are_gated_before_render(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            target = _target(root, "Chroma", "CP1", "LAB", "V_DEMO_CP1")
            render_calls = []
            orchestrator = GenerationOrchestrator(
                staging_renderer=lambda compilation, context: render_calls.append(context),
                validator=SimpleNamespace(validate=lambda artifacts, command: None),
                publisher=_Publisher(),
            )

            with self.assertRaisesRegex(OrchestrationError, "OR.COMPILATION.IDENTITY_MISMATCH"):
                orchestrator.execute(
                    GenerationRequest("EXPECTED", root, (target,)),
                    _Compilation(identity="ACTUAL"),
                )
            missing_cp = _Compilation()
            missing_cp.cp_plans = {"CP2": object()}
            with self.assertRaisesRegex(OrchestrationError, "OR.COMPILATION.CP_MISSING"):
                orchestrator.execute(
                    GenerationRequest("COMPILATION-A", root, (target,)),
                    missing_cp,
                )
            self.assertEqual(render_calls, [])

    def test_orchestrator_has_no_dependency_on_the_private_legacy_adapter(self):
        source = (
            Path(__file__).resolve().parents[1] / "program_gen" / "orchestrator.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("legacy_staging", source)
        self.assertNotIn("LegacyStagingRenderAdapter", source)


if __name__ == "__main__":
    unittest.main()
