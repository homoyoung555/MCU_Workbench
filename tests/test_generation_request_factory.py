from __future__ import annotations

from tests.workspace_paths import FORMAL_MASTER as EXTERNAL_FORMAL_MASTER

from pathlib import Path
import tempfile
import unittest

from program_gen.compiler import ProductCompiler
from program_gen.request_factory import GenerationRoots, build_generation_request
from program_gen.workbook import WorkbookReader


ROOT = Path(__file__).resolve().parents[1]
FORMAL_MASTER = EXTERNAL_FORMAL_MASTER


class GenerationRequestFactoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workbook = WorkbookReader().read(FORMAL_MASTER)
        cls.compilation = ProductCompiler().compile(cls.workbook).require_success()

    def test_formal_master_expands_to_the_exact_nine_supported_targets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request = build_generation_request(
                self.compilation,
                self.workbook,
                GenerationRoots(root, root / "Chroma_program", root / "S100_program"),
                tools_root=ROOT / "tools",
            )

        keys = tuple(target.key for target in request.targets)
        self.assertEqual(len(keys), 9)
        self.assertEqual(
            {(key.platform, key.cp, key.variant) for key in keys},
            {
                *(('chroma', cp, 'lab') for cp in ('CP1', 'CP2', 'CP3')),
                *(('chroma', cp, 'production') for cp in ('CP1', 'CP2', 'CP3')),
                *(('s100', cp, 'lab') for cp in ('CP1', 'CP2', 'CP3')),
            },
        )
        self.assertTrue(all(target.staging_directory.parent == target.final_directory.parent
                            for target in request.targets))

    def test_filters_are_explicit_and_do_not_create_inapplicable_production(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            roots = GenerationRoots(root, root / "Chroma_program", root / "S100_program")
            request = build_generation_request(
                self.compilation,
                self.workbook,
                roots,
                tools_root=ROOT / "tools",
                platforms=("s100",),
                cps=("CP2",),
                variants=("lab", "production"),
            )

        self.assertEqual(len(request.targets), 1)
        self.assertEqual(request.targets[0].key.platform, "s100")
        self.assertEqual(request.targets[0].key.cp, "CP2")
        self.assertEqual(request.targets[0].key.variant, "lab")

    def test_external_toolchains_are_passed_explicitly_to_validation_wrappers(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request = build_generation_request(
                self.compilation,
                self.workbook,
                GenerationRoots(
                    root / "outputs",
                    root / "outputs" / "chroma",
                    root / "outputs" / "s100",
                ),
                tools_root=ROOT / "tools",
                toolchain_roots={
                    "chroma": root / "toolchains" / "chroma",
                    "s100": root / "toolchains" / "s100",
                },
                platforms=("chroma", "s100"),
                cps=("CP1",),
                variants=("lab",),
            )

        commands = {
            target.key.platform: target.validation_command.command
            for target in request.targets
        }
        self.assertIn("--craft-home", commands["chroma"])
        self.assertIn(str((root / "toolchains" / "chroma").resolve()), commands["chroma"])
        self.assertIn("--home", commands["s100"])
        self.assertIn(str((root / "toolchains" / "s100").resolve()), commands["s100"])


if __name__ == "__main__":
    unittest.main()
