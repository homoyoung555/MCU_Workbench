from pathlib import Path
import os
import tempfile
import unittest

from tools.s100_compiler import _pre, _scan, build_env, compiler_home_alias, needs_bcc_home_alias


class S100CompilerPathTests(unittest.TestCase):
    def test_scan_reports_vendor_unknown_diagnostics(self):
        output = "sample.PRG 42 : Unknown 'value[index]' !\nErrors : 1\nWarnings : 0"

        errors, warnings, detail = _scan(output)

        self.assertEqual((errors, warnings), (1, 0))
        self.assertEqual(detail, ["sample.PRG 42 : Unknown 'value[index]' !"])

    def test_portable_root_layout_is_preferred_when_both_layouts_exist(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            for prefix in (home, home / "app"):
                (prefix / "S100").mkdir(parents=True)
                (prefix / "S100" / "YT5100_Pre.exe").touch()
                (prefix / "BCB6" / "Bin").mkdir(parents=True)
                (prefix / "BCB6" / "Bin" / "bcc32.exe").touch()

            env = build_env(str(home))

            self.assertEqual(_pre(str(home)), str(home / "S100" / "YT5100_Pre.exe"))
            self.assertEqual(env["PATH"].split(os.pathsep)[0], str(home / "S100"))

    def test_long_bcc_config_uses_and_releases_a_subst_drive(self):
        calls = []

        def run(command, **kwargs):
            calls.append((tuple(command), kwargs))

        home = r"D:\Code\04_Chroma_MCU_program\V1.3_TEST\S100_Compiler"
        self.assertTrue(needs_bcc_home_alias(home))
        with compiler_home_alias(
            home,
            run=run,
            drive_exists=lambda _drive: False,
        ) as alias:
            self.assertEqual(alias, "Z:\\")
        self.assertEqual(calls[0][0], ("subst", "Z:", home))
        self.assertEqual(calls[-1][0], ("subst", "Z:", "/d"))

    def test_short_home_needs_no_external_mapping(self):
        calls = []
        with compiler_home_alias(
            "S:\\",
            run=lambda *args, **kwargs: calls.append((args, kwargs)),
            drive_exists=lambda _drive: False,
        ) as alias:
            self.assertEqual(alias, "S:\\")
        self.assertEqual(calls, [])

    def test_build_env_exposes_s100_child_tools_before_launching_yt5100(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / "app" / "BCB6" / "Bin").mkdir(parents=True)
            (home / "app" / "S100").mkdir(parents=True)

            env = build_env(str(home))

        path_entries = env["PATH"].split(os.pathsep)
        self.assertEqual(path_entries[0], str(home / "app" / "S100"))
        self.assertEqual(path_entries[1], str(home / "app" / "BCB6" / "Bin"))


if __name__ == "__main__":
    unittest.main()
