from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from program_gen.workspace import WorkspaceLayout, WorkspaceLayoutError


class WorkspaceLayoutTests(unittest.TestCase):
    def test_scaffold_keeps_runtime_data_outside_the_source_tree(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "V1.4"
            workspace = root / "V1.4_WORKSPACE"
            source.mkdir()

            layout = WorkspaceLayout(workspace, source_root=source)
            layout.create()

            self.assertEqual(layout.workbook_root, workspace / "input" / "workbook")
            self.assertEqual(layout.platform_input("chroma"), workspace / "input" / "chroma")
            self.assertEqual(layout.platform_input("s100"), workspace / "input" / "s100")
            self.assertEqual(layout.platform_output("chroma"), workspace / "outputs" / "chroma")
            self.assertEqual(layout.platform_output("s100"), workspace / "outputs" / "s100")
            self.assertEqual(layout.toolchain("chroma"), workspace / "toolchains" / "chroma")
            self.assertEqual(layout.toolchain("s100"), workspace / "toolchains" / "s100")
            self.assertTrue(all(path.is_dir() for path in layout.managed_directories))
            self.assertFalse(any(path.is_relative_to(source) for path in layout.managed_directories))

    def test_rejects_a_workspace_that_contains_or_is_contained_by_source(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "V1.4"
            source.mkdir()
            for workspace in (source, source / "runtime", root):
                with self.subTest(workspace=workspace):
                    with self.assertRaisesRegex(
                        WorkspaceLayoutError, "WS.ROOT.OVERLAPS_SOURCE"
                    ):
                        WorkspaceLayout(workspace, source_root=source)

    def test_master_selection_is_explicit_and_deterministic(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "V1.4"
            source.mkdir()
            layout = WorkspaceLayout(root / "V1.4_WORKSPACE", source_root=source)
            layout.create()
            (layout.workbook_root / "b.xlsx").write_bytes(b"b")
            (layout.workbook_root / "a.xlsm").write_bytes(b"a")
            (layout.workbook_root / "~$lock.xlsx").write_bytes(b"lock")

            self.assertEqual(layout.find_master(), layout.workbook_root / "a.xlsm")
            self.assertEqual(layout.find_master("b.xlsx"), layout.workbook_root / "b.xlsx")


if __name__ == "__main__":
    unittest.main()
