from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from program_gen.legacy_target_renderer import LegacyTargetRenderer
from program_gen.orchestrator import TargetRenderContext
from program_gen.render_plan import ArtifactSet, TargetKey


class LegacyTargetRendererTests(unittest.TestCase):
    def test_private_legacy_work_tree_returns_public_closed_artifact_set(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            platform_root = root / "Chroma_program"
            for name in ("code", "fbist_pattern", "pat_temp"):
                directory = platform_root / name
                directory.mkdir(parents=True)
                (directory / f"{name}.seed").write_bytes(name.encode())
            staging = platform_root / "LAB" / "CHROMA" / ".stage"
            staging.parent.mkdir(parents=True)
            target = TargetKey("chroma", "CP1", "lab", "V_TEST_CP1")
            workbook = object()
            compilation = SimpleNamespace(identity="COMPILATION", is_valid=True)
            calls = []

            def runner(platform, base_dir, supplied_compilation, supplied_workbook, cp, variant):
                calls.append((platform, supplied_compilation, supplied_workbook, cp, variant))
                self.assertNotEqual(base_dir, platform_root)
                output = base_dir / "LAB" / "CHROMA" / target.program_name
                (output / "pat").mkdir(parents=True)
                (output / f"{target.program_name}.pln").write_bytes(b"PROGRAM\r\n")
                (output / "pat" / "a.pat").write_bytes(b"PATTERN\r\n")
                (base_dir / "code" / "code.seed").write_bytes(b"mutated scratch")

            renderer = LegacyTargetRenderer(
                workbook,
                {"chroma": platform_root},
                runner=runner,
            )
            result = renderer(
                compilation,
                TargetRenderContext("REQUEST", "COMPILATION", target, staging),
            )

            self.assertIsInstance(result, ArtifactSet)
            self.assertEqual(result.root, staging.resolve())
            self.assertEqual(
                tuple(item.relative_path for item in result.artifacts),
                ("pat/a.pat", f"{target.program_name}.pln"),
            )
            self.assertTrue((staging / ".render-manifest.json").is_file())
            self.assertEqual((platform_root / "code" / "code.seed").read_bytes(), b"code")
            self.assertEqual(calls, [("chroma", compilation, workbook, "CP1", "lab")])
            self.assertFalse(any("legacy-work" in item.name for item in staging.parent.iterdir()))


if __name__ == "__main__":
    unittest.main()
