from __future__ import annotations

import ast
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from io import StringIO
import unittest
from unittest.mock import MagicMock, patch

import main as cli_main


class MainGenerationServiceTests(unittest.TestCase):
    def test_workspace_supplies_inputs_outputs_and_master_outside_source(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "V1.4_WORKSPACE"
            master = workspace / "input" / "workbook" / "formal.xlsx"
            master.parent.mkdir(parents=True)
            master.write_bytes(b"fixture")
            workbook = object()
            compilation = SimpleNamespace(is_valid=True)
            result = SimpleNamespace(
                published=True,
                status=SimpleNamespace(value="PUBLISHED"),
                request_identity="REQUEST:WORKSPACE",
                targets=(),
                error=None,
            )
            reader = MagicMock()
            reader.read.return_value = workbook
            compiler = MagicMock()
            compiler.compile.return_value = compilation
            service = MagicMock()
            service.execute.return_value = result

            with (
                patch.object(cli_main, "WorkbookReader", return_value=reader),
                patch.object(cli_main, "ProductCompiler", return_value=compiler),
                patch.object(cli_main, "GenerationService", return_value=service),
            ):
                exit_code = cli_main.main([
                    "--platform", "chroma",
                    "--workspace", str(workspace),
                    "--master", "formal.xlsx",
                    "--skip-check",
                    "--allow-stub-publication",
                ])

            self.assertEqual(exit_code, 0)
            reader.read.assert_called_once_with(str(master.resolve()))
            _workbook, _compilation, roots = service.execute.call_args.args[:3]
            self.assertEqual(roots.output_root, (workspace / "outputs").resolve())
            self.assertEqual(roots.chroma, (workspace / "outputs" / "chroma").resolve())
            self.assertEqual(roots.s100, (workspace / "outputs" / "s100").resolve())
            self.assertEqual(
                service.execute.call_args.kwargs["platform_roots"],
                {
                    "chroma": (workspace / "input" / "chroma").resolve(),
                    "s100": (workspace / "input" / "s100").resolve(),
                },
            )
            self.assertTrue(
                service.execute.call_args.kwargs["allow_stub_publication"]
            )

    def test_default_selection_uses_generation_service_without_platform_run(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "V1.4_WORKSPACE"
            master = workspace / "input" / "workbook" / "formal.xlsx"
            master.parent.mkdir(parents=True)
            master.write_bytes(b"fixture")
            workbook = object()
            compilation = SimpleNamespace(is_valid=True)
            result = SimpleNamespace(
                published=True,
                status=SimpleNamespace(value="PUBLISHED"),
                request_identity="REQUEST:TEST",
                targets=(),
                error=None,
            )
            reader = MagicMock()
            reader.read.return_value = workbook
            compiler = MagicMock()
            compiler.compile.return_value = compilation
            service = MagicMock()
            service.execute.return_value = result

            with (
                patch.object(cli_main, "WorkbookReader", create=True, return_value=reader),
                patch.object(cli_main, "ProductCompiler", create=True, return_value=compiler),
                patch.object(cli_main, "GenerationService", create=True, return_value=service),
            ):
                exit_code = cli_main.main([
                    "--platform", "s100",
                    "--workspace", str(workspace),
                    "--master", "formal.xlsx",
                    "--skip-check",
                ])

            self.assertEqual(exit_code, 0)
            reader.read.assert_called_once_with(str(master.resolve()))
            compiler.compile.assert_called_once_with(workbook)
            service.execute.assert_called_once()
            _workbook, _compilation, roots = service.execute.call_args.args[:3]
            self.assertIs(_workbook, workbook)
            self.assertIs(_compilation, compilation)
            self.assertEqual(roots.output_root, (workspace / "outputs").resolve())
            self.assertEqual(roots.chroma, (workspace / "outputs" / "chroma").resolve())
            self.assertEqual(roots.s100, (workspace / "outputs" / "s100").resolve())
            self.assertEqual(
                service.execute.call_args.kwargs["platforms"], ("s100",)
            )
            self.assertEqual(
                service.execute.call_args.kwargs["cps"], ("CP1", "CP2", "CP3")
            )
            self.assertEqual(
                service.execute.call_args.kwargs["variants"], ("lab", "production")
            )

    def test_custom_base_preserves_other_default_root_and_reports_failed_targets(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "custom-workspace"
            master = workspace / "input" / "workbook" / "formal.xlsx"
            master.parent.mkdir(parents=True)
            master.write_bytes(b"fixture")
            workbook = object()
            compilation = SimpleNamespace(is_valid=True)
            target = SimpleNamespace(
                target=SimpleNamespace(identity="chroma:CP2:lab:V_TEST_CP2"),
                validation_passed=False,
                manifest_identity="MANIFEST:CP2",
                validation_identity=None,
                error="validation blocked",
            )
            result = SimpleNamespace(
                published=False,
                status=SimpleNamespace(value="VALIDATION_FAILED"),
                request_identity="REQUEST:FAILED",
                targets=(target,),
                error="one target blocked publication",
            )
            reader = MagicMock()
            reader.read.return_value = workbook
            compiler = MagicMock()
            compiler.compile.return_value = compilation
            service = MagicMock()
            service.execute.return_value = result

            with (
                patch.object(cli_main, "WorkbookReader", create=True, return_value=reader),
                patch.object(cli_main, "ProductCompiler", create=True, return_value=compiler),
                patch.object(cli_main, "GenerationService", create=True, return_value=service),
                patch("sys.stdout", new_callable=StringIO) as stdout,
            ):
                exit_code = cli_main.main([
                    "--platform", "chroma",
                    "--workspace", str(workspace),
                    "--master", "formal.xlsx",
                    "--cp", "CP2",
                    "--variant", "lab",
                    "--skip-check",
                ])

            self.assertEqual(exit_code, 1)
            _workbook, _compilation, roots = service.execute.call_args.args[:3]
            self.assertEqual(roots.output_root, (workspace / "outputs").resolve())
            self.assertEqual(roots.chroma, (workspace / "outputs" / "chroma").resolve())
            self.assertEqual(roots.s100, (workspace / "outputs" / "s100").resolve())
            self.assertEqual(
                service.execute.call_args.kwargs["platform_roots"],
                {
                    "chroma": (workspace / "input" / "chroma").resolve(),
                    "s100": (workspace / "input" / "s100").resolve(),
                },
            )
            self.assertEqual(
                service.execute.call_args.kwargs["platforms"], ("chroma",)
            )
            self.assertEqual(service.execute.call_args.kwargs["cps"], ("CP2",))
            self.assertEqual(service.execute.call_args.kwargs["variants"], ("lab",))
            self.assertIn("status=VALIDATION_FAILED", stdout.getvalue())
            self.assertIn("chroma:CP2:lab:V_TEST_CP2", stdout.getvalue())
            self.assertIn("validation blocked", stdout.getvalue())

    def test_skip_check_cannot_send_an_invalid_compilation_to_service(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "V1.4_WORKSPACE"
            master = workspace / "input" / "workbook" / "invalid.xlsx"
            master.parent.mkdir(parents=True)
            master.write_bytes(b"fixture")
            workbook = object()
            compilation = SimpleNamespace(is_valid=False)
            reader = MagicMock()
            reader.read.return_value = workbook
            compiler = MagicMock()
            compiler.compile.return_value = compilation
            service = MagicMock()

            with (
                patch.object(cli_main, "WorkbookReader", create=True, return_value=reader),
                patch.object(cli_main, "ProductCompiler", create=True, return_value=compiler),
                patch.object(cli_main, "GenerationService", create=True, return_value=service),
                patch("preflight.check_master") as check_master,
                patch("sys.stdout", new_callable=StringIO) as stdout,
            ):
                exit_code = cli_main.main([
                    "--platform", "s100",
                    "--workspace", str(workspace),
                    "--master", "invalid.xlsx",
                    "--skip-check",
                ])

            self.assertEqual(exit_code, 2)
            check_master.assert_called_once_with(compilation, verbose=True)
            service.execute.assert_not_called()
            self.assertIn("不能绕过编译错误", stdout.getvalue())

    def test_entrypoint_has_no_direct_platform_main_route(self):
        source_path = Path(cli_main.__file__).resolve()
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }

        self.assertNotIn("program_gen.platforms.chroma.main", imports)
        self.assertNotIn("program_gen.platforms.s100.main", imports)
        self.assertFalse(any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "run"
            for node in ast.walk(tree)
        ))


if __name__ == "__main__":
    unittest.main()
