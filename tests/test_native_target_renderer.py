from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from program_gen.compiler import ProductCompiler
from program_gen.generation_service import GenerationService
from program_gen.legacy_target_renderer import LegacyTargetRenderer
from program_gen.native_target_renderer import NativeTargetRenderer
from program_gen.publisher import PublishResult, PublishStatus
from program_gen.request_factory import GenerationRoots
from program_gen.workbook import WorkbookReader
from tests.workspace_paths import FORMAL_MASTER, S100_SEED_ROOT


class NativeTargetRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()

    def test_explicit_native_target_is_materialized_but_stubs_block_publication(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "outputs"
            roots = GenerationRoots(
                output,
                output / "Chroma_program",
                output / "S100_program",
            )
            publisher = _Publisher()
            validator = _Validator()

            with patch.object(
                LegacyTargetRenderer,
                "__call__",
                side_effect=AssertionError("native renderer fell back to legacy"),
            ):
                result = GenerationService(
                    renderer_factory=NativeTargetRenderer,
                    validator=validator,
                    publisher=publisher,
                ).execute(
                    self.workbook,
                    self.compilation,
                    roots,
                    tools_root=Path(__file__).resolve().parents[1] / "tools",
                    platform_roots={"s100": S100_SEED_ROOT},
                    platforms=("s100",),
                    cps=("CP1",),
                    variants=("lab",),
                )

            self.assertFalse(result.published)
            self.assertEqual(len(result.targets), 1)
            target = result.targets[0].target
            staging = (
                roots.s100 / "LAB" / "S100"
                / f".{target.program_name}.stage-{self.compilation.identity[:12].lower()}"
            )
            self.assertTrue((staging / f"{target.program_name}.prg").is_file())
            self.assertTrue((staging / ".render-manifest.json").is_file())
            self.assertEqual(len(validator.calls), 1)
            self.assertEqual(len(validator.calls[0].release_blockers), 5)
            self.assertIn("OR.RELEASE.STUB_BLOCKED", result.targets[0].error)
            self.assertEqual(publisher.requests, [])


class _Validator:
    def __init__(self) -> None:
        self.calls = []

    def validate(self, artifacts, _command):
        self.calls.append(artifacts)
        return SimpleNamespace(
            target=artifacts.target,
            passed=True,
            identity=f"VALID:{artifacts.manifest_identity}",
        )


class _Publisher:
    def __init__(self) -> None:
        self.requests = []

    def publish(self, request):
        self.requests.append(request)
        return PublishResult(
            PublishStatus.PUBLISHED,
            Path("unused-journal"),
            tuple(target.target_id for target in request.targets),
        )


if __name__ == "__main__":
    unittest.main()
