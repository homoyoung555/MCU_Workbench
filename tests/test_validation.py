from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from program_gen.render_plan import (
    ArtifactMaterializer,
    ArtifactPlan,
    RenderPlan,
    TargetKey,
)
from program_gen.validation import (
    TargetValidator,
    ValidationCommand,
)


TARGET = TargetKey("Chroma", "CP1", "LAB", "V_DEMO_CP1")


def _artifact_set(parent: Path):
    staging = parent / "staging"
    staging.mkdir()
    plan = RenderPlan.from_artifacts(
        TARGET,
        (
            ArtifactPlan("program/main.prg", b"PROGRAM\r\n", "PROGRAM", ("main",)),
            ArtifactPlan("patterns/a.pat", b"PATTERN\r\n", "RESOURCE", ("a",)),
        ),
    )
    return ArtifactMaterializer().materialize(plan, staging)


class TargetValidatorTests(unittest.TestCase):
    def test_validation_is_deterministic_and_compiler_runs_in_private_copy(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            artifacts = _artifact_set(root)
            formal = root / "formal"
            formal.mkdir()
            sentinel = formal / "must-not-change.txt"
            sentinel.write_bytes(b"formal")
            invocations = []

            def runner(command, cwd):
                invocations.append((command, cwd))
                self.assertNotEqual(cwd, artifacts.root)
                self.assertEqual(cwd.name, TARGET.program_name)
                self.assertEqual(
                    (cwd / "program" / "main.prg").read_bytes(), b"PROGRAM\r\n"
                )
                self.assertEqual(sentinel.read_bytes(), b"formal")
                return SimpleNamespace(returncode=0, stdout=b"compile ok\r\n", stderr=b"")

            command = ValidationCommand(
                tool_identity="chroma-draft:2026.08",
                command=("draft.exe", "-p", "program/main.prg"),
            )
            validator = TargetValidator(runner=runner)

            first = validator.validate(artifacts, command)
            second = validator.validate(artifacts, command)

            self.assertTrue(first.passed)
            self.assertEqual(first, second)
            self.assertEqual(first.identity, second.identity)
            self.assertEqual(first.tool_identity, "chroma-draft:2026.08")
            self.assertEqual(first.compiler.exit_code, 0)
            self.assertEqual(first.compiler.stdout, b"compile ok\r\n")
            self.assertEqual(len(first.compiler.log_sha256), 64)
            self.assertEqual(sentinel.read_bytes(), b"formal")
            self.assertEqual(len(invocations), 2)
            with self.assertRaises(FrozenInstanceError):
                first.passed = False

    def test_extra_or_missing_file_blocks_before_the_compiler_runs(self):
        for mutation, expected_code in (
            ("extra", "TV.FILE_SET.EXTRA"),
            ("missing", "TV.FILE_SET.MISSING"),
        ):
            with self.subTest(mutation=mutation), TemporaryDirectory() as temp:
                artifacts = _artifact_set(Path(temp))
                if mutation == "extra":
                    (artifacts.root / "stale.cache").write_bytes(b"stale")
                else:
                    (artifacts.root / "patterns" / "a.pat").unlink()
                called = False

                def runner(command, cwd):
                    nonlocal called
                    called = True
                    return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

                result = TargetValidator(runner=runner).validate(
                    artifacts, ValidationCommand("tool:v1", ("compiler",))
                )

                self.assertFalse(result.passed)
                self.assertIn(expected_code, tuple(item.code for item in result.diagnostics))
                self.assertFalse(called)

    def test_manifest_or_artifact_hash_drift_is_blocking(self):
        for mutation, expected_code in (
            ("manifest", "TV.MANIFEST.IDENTITY_MISMATCH"),
            ("artifact", "TV.ARTIFACT.HASH_MISMATCH"),
        ):
            with self.subTest(mutation=mutation), TemporaryDirectory() as temp:
                artifacts = _artifact_set(Path(temp))
                if mutation == "manifest":
                    manifest = artifacts.root / ".render-manifest.json"
                    manifest.write_bytes(manifest.read_bytes() + b" ")
                else:
                    (artifacts.root / "program" / "main.prg").write_bytes(b"DRIFT")

                result = TargetValidator(
                    runner=lambda command, cwd: self.fail("compiler must be gated")
                ).validate(artifacts, ValidationCommand("tool:v1", ("compiler",)))

                self.assertFalse(result.passed)
                self.assertIn(expected_code, tuple(item.code for item in result.diagnostics))

    def test_nonzero_exit_captures_immutable_tool_evidence_and_blocks(self):
        with TemporaryDirectory() as temp:
            artifacts = _artifact_set(Path(temp))

            result = TargetValidator(
                runner=lambda command, cwd: SimpleNamespace(
                    returncode=7,
                    stdout="ordinary output\n",
                    stderr="compile failed\n",
                )
            ).validate(
                artifacts,
                ValidationCommand("s100-compiler:5.4", ("s100cc", "program/main.prg")),
            )

            self.assertFalse(result.passed)
            self.assertIn(
                "TV.COMPILER.NONZERO_EXIT",
                tuple(item.code for item in result.diagnostics),
            )
            self.assertEqual(result.compiler.exit_code, 7)
            self.assertEqual(result.compiler.stdout, b"ordinary output\n")
            self.assertEqual(result.compiler.stderr, b"compile failed\n")
            self.assertEqual(len(result.compiler.stdout_sha256), 64)
            self.assertEqual(len(result.compiler.stderr_sha256), 64)
            self.assertEqual(len(result.compiler.log_sha256), 64)

    def test_compiler_derived_files_are_isolated_but_source_mutation_is_blocking(self):
        with TemporaryDirectory() as temp:
            artifacts = _artifact_set(Path(temp))

            def derived_runner(command, cwd):
                (cwd / "compiler.cache").write_bytes(b"derived")
                return SimpleNamespace(returncode=0, stdout=b"ok", stderr=b"")

            derived = TargetValidator(runner=derived_runner).validate(
                artifacts, ValidationCommand("tool:v1", ("compiler",))
            )
            self.assertTrue(derived.passed)
            self.assertFalse((artifacts.root / "compiler.cache").exists())

            def mutating_runner(command, cwd):
                (cwd / "program" / "main.prg").write_bytes(b"modified")
                return SimpleNamespace(returncode=0, stdout=b"ok", stderr=b"")

            modified = TargetValidator(runner=mutating_runner).validate(
                artifacts, ValidationCommand("tool:v1", ("compiler",))
            )
            self.assertFalse(modified.passed)
            self.assertIn(
                "TV.ARTIFACT.HASH_MISMATCH",
                tuple(item.code for item in modified.diagnostics),
            )
            self.assertEqual(
                (artifacts.root / "program" / "main.prg").read_bytes(), b"PROGRAM\r\n"
            )


if __name__ == "__main__":
    unittest.main()
