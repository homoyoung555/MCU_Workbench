from __future__ import annotations

from tests.workspace_paths import FORMAL_MASTER as EXTERNAL_FORMAL_MASTER

import ast
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from program_gen.compiler import ProductCompiler
from program_gen.generation_service import GenerationService
from program_gen.publisher import PublishResult, PublishStatus
from program_gen.render_plan import ArtifactSet
from program_gen.request_factory import GenerationRoots
from program_gen.workbook import WorkbookReader


ROOT = Path(__file__).resolve().parents[1]
FORMAL_MASTER = EXTERNAL_FORMAL_MASTER


class GenerationServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()

    def test_fans_one_compilation_out_to_the_formal_nine_target_request(self):
        renderer_factory = _RendererFactory()
        validator = _Validator()
        publisher = _Publisher()
        with TemporaryDirectory() as temp:
            root = Path(temp)
            roots = GenerationRoots(
                root,
                root / "Chroma_program",
                root / "S100_program",
            )

            result = GenerationService(
                renderer_factory=renderer_factory,
                validator=validator,
                publisher=publisher,
            ).execute(
                self.workbook,
                self.compilation,
                roots,
                tools_root=ROOT / "tools",
                platform_roots={
                    "chroma": root / "legacy-chroma",
                    "s100": root / "legacy-s100",
                },
            )

        self.assertTrue(result.published)
        self.assertEqual(len(renderer_factory.contexts), 9)
        self.assertEqual(len(validator.calls), 9)
        self.assertEqual(len(publisher.requests), 1)
        self.assertIs(renderer_factory.workbook, self.workbook)
        self.assertTrue(all(
            compilation is self.compilation
            for compilation in renderer_factory.compilations
        ))
        self.assertEqual(
            {(context.target.platform, context.target.cp, context.target.variant)
             for context in renderer_factory.contexts},
            {
                *(('chroma', cp, 'lab') for cp in ('CP1', 'CP2', 'CP3')),
                *(('chroma', cp, 'production') for cp in ('CP1', 'CP2', 'CP3')),
                *(('s100', cp, 'lab') for cp in ('CP1', 'CP2', 'CP3')),
            },
        )

    def test_default_renderer_is_native(self):
        renderer_factory = _RendererFactory()
        validator = _Validator()
        publisher = _Publisher()
        with TemporaryDirectory() as temp, patch(
            "program_gen.generation_service.NativeTargetRenderer",
            renderer_factory,
        ):
            root = Path(temp)
            result = GenerationService(
                validator=validator,
                publisher=publisher,
            ).execute(
                self.workbook,
                self.compilation,
                GenerationRoots(root, root / "chroma", root / "s100"),
                tools_root=ROOT / "tools",
                platform_roots={
                    "chroma": root / "input-chroma",
                    "s100": root / "input-s100",
                },
            )

        self.assertTrue(result.published)
        self.assertEqual(len(renderer_factory.contexts), 9)

    def test_any_validation_failure_audits_the_matrix_but_never_publishes(self):
        renderer_factory = _RendererFactory()
        validator = _Validator(fail_cp="CP2")
        publisher = _Publisher()
        with TemporaryDirectory() as temp:
            root = Path(temp)
            roots = GenerationRoots(
                root,
                root / "Chroma_program",
                root / "S100_program",
            )

            result = GenerationService(
                renderer_factory=renderer_factory,
                validator=validator,
                publisher=publisher,
            ).execute(
                self.workbook,
                self.compilation,
                roots,
                tools_root=ROOT / "tools",
                platform_roots={"chroma": root / "legacy-chroma", "s100": root / "legacy-s100"},
            )

        self.assertFalse(result.published)
        self.assertEqual(len(renderer_factory.contexts), 9)
        self.assertEqual(len(validator.calls), 9)
        self.assertEqual(publisher.requests, [])
        self.assertEqual(
            tuple(item.validation_passed for item in result.targets if item.target.cp == "CP2"),
            (False, False, False),
        )

    def test_service_never_re_reads_or_recompiles_the_supplied_public_models(self):
        source_path = ROOT / "program_gen" / "generation_service.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported_modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        imported_modules.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )

        self.assertNotIn("program_gen.compiler", imported_modules)
        self.assertNotIn("program_gen.workbook", imported_modules)
        self.assertFalse(any(
            module.startswith("program_gen.platforms") for module in imported_modules
        ))


class _RendererFactory:
    def __init__(self) -> None:
        self.workbook = None
        self.platform_roots = None
        self.contexts = []
        self.compilations = []

    def __call__(self, workbook, platform_roots):
        self.workbook = workbook
        self.platform_roots = platform_roots

        def render(compilation, context):
            self.compilations.append(compilation)
            self.contexts.append(context)
            return ArtifactSet(
                context.target,
                context.staging_directory,
                (),
                f"MANIFEST:{context.target.identity}",
            )

        return render


class _Validator:
    def __init__(self, *, fail_cp: str | None = None) -> None:
        self.fail_cp = fail_cp
        self.calls = []

    def validate(self, artifacts, command):
        self.calls.append((artifacts, command))
        return SimpleNamespace(
            target=artifacts.target,
            passed=artifacts.target.cp != self.fail_cp,
            identity=(
                f"VALID:{artifacts.target.cp != self.fail_cp}:{artifacts.target.identity}"
            ),
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
