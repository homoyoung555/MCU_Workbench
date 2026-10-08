"""Public native assembly imports must work in either fresh-process order."""
from pathlib import Path
import subprocess
import sys
import unittest


class NativeRegistryImportTests(unittest.TestCase):
    def check_order(self, first):
        script = (
            f"import {first}\n"
            "from program_gen.registered_typed_kinds import NATIVE_TYPED_KIND_REGISTRY\n"
            "from program_gen.platform_program import build_native_target_plan\n"
            "from program_gen.platform_program import native_target\n"
            "assert native_target.NATIVE_TYPED_KIND_REGISTRY is NATIVE_TYPED_KIND_REGISTRY\n"
            "assert callable(build_native_target_plan)\n"
        )
        result = subprocess.run(
            [sys.executable, '-c', script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, encoding='utf-8', timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_registry_can_be_imported_first(self):
        self.check_order('program_gen.registered_typed_kinds')

    def test_platform_can_be_imported_first(self):
        self.check_order('program_gen.platform_program')
