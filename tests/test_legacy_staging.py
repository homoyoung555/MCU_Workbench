from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from program_gen.legacy_staging import (
    InputRoots,
    LegacyStagingError,
    LegacyStagingRenderAdapter,
)
from program_gen.render_plan import TargetKey


TARGET = TargetKey("s100", "CP1", "lab", "V_TEST_CP1")


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    paths = (root,) if root.is_file() else tuple(
        sorted((item for item in root.rglob("*") if item.is_file()), key=str)
    )
    for path in paths:
        relative = path.name if root.is_file() else path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest().upper()


class LegacyStagingRenderAdapterTests(unittest.TestCase):
    def test_runs_in_a_fresh_staging_copy_and_returns_selected_target_sha(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            seed = root / "seed"
            code = root / "inputs" / "code"
            fbist = root / "inputs" / "fbist_pattern"
            pat_temp = root / "inputs" / "pat_temp"
            workbook = root / "inputs" / "program.xlsx"
            staging = root / "request-private-staging"
            _write(seed / "platform.ini", b"seed\r\n")
            _write(code / "firmware.hex", b"code\r\n")
            _write(fbist / "enter.sd", b"fbist\r\n")
            _write(pat_temp / "shared.sd", b"pattern\r\n")
            _write(workbook, b"workbook-bytes")
            inputs = InputRoots(seed, code, fbist, pat_temp, workbook)
            source_sha_before = tuple(
                _tree_sha256(path)
                for path in (seed, code, fbist, pat_temp, workbook)
            )

            def runner(base_dir: Path) -> None:
                self.assertEqual(base_dir, staging.resolve())
                self.assertEqual((base_dir / "platform.ini").read_bytes(), b"seed\r\n")
                self.assertEqual(
                    (base_dir / "code" / "firmware.hex").read_bytes(), b"code\r\n"
                )
                self.assertEqual(
                    (base_dir / "fbist_pattern" / "enter.sd").read_bytes(),
                    b"fbist\r\n",
                )
                self.assertEqual(
                    (base_dir / "pat_temp" / "shared.sd").read_bytes(),
                    b"pattern\r\n",
                )
                self.assertEqual(
                    (base_dir / "test_data" / workbook.name).read_bytes(),
                    b"workbook-bytes",
                )
                target = base_dir / "LAB" / "S100" / TARGET.program_name
                _write(target / "main.prg", b"PROGRAM\r\n")
                _write(target / "patterns" / "enter.sd", b"VECTOR\r\n")

            result = LegacyStagingRenderAdapter(runner).render(
                inputs=inputs,
                staging=staging,
                target=TARGET,
            )

            self.assertEqual(result.target, TARGET)
            self.assertEqual(
                result.target_relative_root, "LAB/S100/V_TEST_CP1"
            )
            self.assertEqual(
                tuple(item.relative_path for item in result.artifacts),
                ("main.prg", "patterns/enter.sd"),
            )
            self.assertEqual(
                result.artifact("main.prg").sha256,
                hashlib.sha256(b"PROGRAM\r\n").hexdigest().upper(),
            )
            self.assertFalse((staging / ".render-manifest.json").exists())
            self.assertEqual(
                tuple(
                    _tree_sha256(path)
                    for path in (seed, code, fbist, pat_temp, workbook)
                ),
                source_sha_before,
            )

    def test_explicit_resource_roots_replace_seed_copies(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            seed = root / "seed"
            code = root / "inputs" / "code"
            fbist = root / "inputs" / "fbist_pattern"
            pat_temp = root / "inputs" / "pat_temp"
            workbook = root / "inputs" / "program.xlsx"
            staging = root / "staging"
            _write(seed / "code" / "stale.hex", b"stale")
            _write(seed / "fbist_pattern" / "stale.sd", b"stale")
            _write(seed / "pat_temp" / "stale.sd", b"stale")
            _write(code / "current.hex", b"current-code")
            _write(fbist / "current.sd", b"current-fbist")
            _write(pat_temp / "current.sd", b"current-pattern")
            _write(workbook, b"workbook")

            def runner(base_dir: Path) -> None:
                self.assertFalse((base_dir / "code" / "stale.hex").exists())
                self.assertFalse(
                    (base_dir / "fbist_pattern" / "stale.sd").exists()
                )
                self.assertFalse((base_dir / "pat_temp" / "stale.sd").exists())
                self.assertTrue((base_dir / "code" / "current.hex").is_file())
                self.assertTrue(
                    (base_dir / "fbist_pattern" / "current.sd").is_file()
                )
                self.assertTrue((base_dir / "pat_temp" / "current.sd").is_file())
                (base_dir / "LAB" / "S100" / TARGET.program_name).mkdir(
                    parents=True
                )

            LegacyStagingRenderAdapter(runner).render(
                inputs=InputRoots(seed, code, fbist, pat_temp, workbook),
                staging=staging,
                target=TARGET,
            )

    def test_reports_only_the_selected_production_target(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            seed = root / "seed"
            code = root / "inputs" / "code"
            fbist = root / "inputs" / "fbist_pattern"
            pat_temp = root / "inputs" / "pat_temp"
            workbook = root / "inputs" / "program.xlsx"
            staging = root / "staging"
            for directory in (seed, code, fbist, pat_temp):
                directory.mkdir(parents=True, exist_ok=True)
            _write(workbook, b"workbook")
            selected = TargetKey("chroma", "CP2", "production", "V_PROD_CP2")

            def runner(base_dir: Path) -> None:
                _write(base_dir / selected.program_name / "main.pln", b"selected")
                _write(base_dir / "V_OTHER_CP1" / "main.pln", b"other-production")
                _write(
                    base_dir / "LAB" / "CHROMA" / "V_LAB_CP2" / "main.pln",
                    b"other-lab",
                )

            result = LegacyStagingRenderAdapter(runner).render(
                inputs=InputRoots(seed, code, fbist, pat_temp, workbook),
                staging=staging,
                target=selected,
            )

            self.assertEqual(result.target_relative_root, "V_PROD_CP2")
            self.assertEqual(
                tuple(item.relative_path for item in result.artifacts),
                ("main.pln",),
            )
            self.assertEqual(
                result.artifact("main.pln").sha256,
                hashlib.sha256(b"selected").hexdigest().upper(),
            )

    def test_rejects_an_existing_or_nonempty_staging_before_runner(self):
        for nonempty, code in (
            (False, "LS.STAGING.EXISTS"),
            (True, "LS.STAGING.NOT_EMPTY"),
        ):
            with self.subTest(nonempty=nonempty), TemporaryDirectory() as temp:
                root = Path(temp)
                seed = root / "seed"
                code_root = root / "inputs" / "code"
                fbist = root / "inputs" / "fbist_pattern"
                pat_temp = root / "inputs" / "pat_temp"
                workbook = root / "inputs" / "program.xlsx"
                staging = root / "staging"
                for directory in (seed, code_root, fbist, pat_temp, staging):
                    directory.mkdir(parents=True, exist_ok=True)
                _write(workbook, b"workbook")
                if nonempty:
                    _write(staging / "prior-output.prg", b"must-survive")

                def runner(_base_dir: Path) -> None:
                    self.fail("runner must not be called for an unsafe staging path")

                with self.assertRaisesRegex(LegacyStagingError, code):
                    LegacyStagingRenderAdapter(runner).render(
                        inputs=InputRoots(
                            seed, code_root, fbist, pat_temp, workbook
                        ),
                        staging=staging,
                        target=TARGET,
                    )
                if nonempty:
                    self.assertEqual(
                        (staging / "prior-output.prg").read_bytes(), b"must-survive"
                    )

    def test_rejects_a_missing_selected_target_directory(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            seed = root / "seed"
            code = root / "inputs" / "code"
            fbist = root / "inputs" / "fbist_pattern"
            pat_temp = root / "inputs" / "pat_temp"
            workbook = root / "inputs" / "program.xlsx"
            staging = root / "staging"
            for directory in (seed, code, fbist, pat_temp):
                directory.mkdir(parents=True, exist_ok=True)
            _write(workbook, b"workbook")

            with self.assertRaisesRegex(
                LegacyStagingError, "LS.TARGET.MISSING"
            ):
                LegacyStagingRenderAdapter(lambda _base_dir: None).render(
                    inputs=InputRoots(seed, code, fbist, pat_temp, workbook),
                    staging=staging,
                    target=TARGET,
                )

    def test_rejects_a_symlink_in_any_input_tree(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            seed = root / "seed"
            code = root / "inputs" / "code"
            fbist = root / "inputs" / "fbist_pattern"
            pat_temp = root / "inputs" / "pat_temp"
            workbook = root / "inputs" / "program.xlsx"
            staging = root / "staging"
            outside = root / "outside"
            for directory in (seed, code, fbist, pat_temp, outside):
                directory.mkdir(parents=True, exist_ok=True)
            _write(workbook, b"workbook")
            _write(outside / "secret.sd", b"outside")
            try:
                (seed / "linked").symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink creation is unavailable: {exc}")

            def runner(base_dir: Path) -> None:
                (base_dir / "LAB" / "S100" / TARGET.program_name).mkdir(
                    parents=True
                )

            with self.assertRaisesRegex(
                LegacyStagingError, "LS.INPUT.SYMLINK"
            ):
                LegacyStagingRenderAdapter(runner).render(
                    inputs=InputRoots(seed, code, fbist, pat_temp, workbook),
                    staging=staging,
                    target=TARGET,
                )
            self.assertFalse(staging.exists())

    def test_rejects_an_input_root_reached_through_a_symlink_parent(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            seed = root / "seed"
            actual_inputs = root / "actual-inputs"
            code = actual_inputs / "code"
            fbist = actual_inputs / "fbist_pattern"
            pat_temp = actual_inputs / "pat_temp"
            workbook = actual_inputs / "program.xlsx"
            staging = root / "staging"
            for directory in (seed, code, fbist, pat_temp):
                directory.mkdir(parents=True, exist_ok=True)
            _write(workbook, b"workbook")
            linked_inputs = root / "linked-inputs"
            try:
                linked_inputs.symlink_to(actual_inputs, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink creation is unavailable: {exc}")

            def runner(base_dir: Path) -> None:
                (base_dir / "LAB" / "S100" / TARGET.program_name).mkdir(
                    parents=True
                )

            with self.assertRaisesRegex(
                LegacyStagingError, "LS.INPUT.SYMLINK"
            ):
                LegacyStagingRenderAdapter(runner).render(
                    inputs=InputRoots(
                        seed,
                        linked_inputs / "code",
                        fbist,
                        pat_temp,
                        workbook,
                    ),
                    staging=staging,
                    target=TARGET,
                )
            self.assertFalse(staging.exists())

    def test_rejects_a_staging_path_with_a_symlink_at_or_above_it(self):
        for link_is_parent in (False, True):
            with self.subTest(link_is_parent=link_is_parent), TemporaryDirectory() as temp:
                root = Path(temp)
                seed = root / "seed"
                code = root / "inputs" / "code"
                fbist = root / "inputs" / "fbist_pattern"
                pat_temp = root / "inputs" / "pat_temp"
                workbook = root / "inputs" / "program.xlsx"
                outside = root / "outside"
                for directory in (seed, code, fbist, pat_temp, outside):
                    directory.mkdir(parents=True, exist_ok=True)
                _write(workbook, b"workbook")
                link = root / "linked-staging"
                try:
                    link.symlink_to(outside, target_is_directory=True)
                except OSError as exc:
                    self.skipTest(f"symlink creation is unavailable: {exc}")
                staging = link / "child" if link_is_parent else link

                def runner(_base_dir: Path) -> None:
                    self.fail("runner must not be called through a staging symlink")

                with self.assertRaisesRegex(
                    LegacyStagingError, "LS.STAGING.SYMLINK"
                ):
                    LegacyStagingRenderAdapter(runner).render(
                        inputs=InputRoots(
                            seed, code, fbist, pat_temp, workbook
                        ),
                        staging=staging,
                        target=TARGET,
                    )
                self.assertEqual(tuple(outside.iterdir()), ())

    def test_rejects_a_generated_target_symlink(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            seed = root / "seed"
            code = root / "inputs" / "code"
            fbist = root / "inputs" / "fbist_pattern"
            pat_temp = root / "inputs" / "pat_temp"
            workbook = root / "inputs" / "program.xlsx"
            staging = root / "staging"
            outside = root / "outside-target"
            for directory in (seed, code, fbist, pat_temp, outside):
                directory.mkdir(parents=True, exist_ok=True)
            _write(workbook, b"workbook")
            _write(outside / "escaped.prg", b"outside")

            def runner(base_dir: Path) -> None:
                parent = base_dir / "LAB" / "S100"
                parent.mkdir(parents=True)
                try:
                    (parent / TARGET.program_name).symlink_to(
                        outside, target_is_directory=True
                    )
                except OSError as exc:
                    self.skipTest(f"symlink creation is unavailable: {exc}")

            with self.assertRaisesRegex(
                LegacyStagingError, "LS.TARGET.SYMLINK"
            ):
                LegacyStagingRenderAdapter(runner).render(
                    inputs=InputRoots(seed, code, fbist, pat_temp, workbook),
                    staging=staging,
                    target=TARGET,
                )
            self.assertEqual((outside / "escaped.prg").read_bytes(), b"outside")

    def test_rejects_a_target_key_that_can_escape_the_staging_tree(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            seed = root / "seed"
            code = root / "inputs" / "code"
            fbist = root / "inputs" / "fbist_pattern"
            pat_temp = root / "inputs" / "pat_temp"
            workbook = root / "inputs" / "program.xlsx"
            staging = root / "staging"
            for directory in (seed, code, fbist, pat_temp):
                directory.mkdir(parents=True, exist_ok=True)
            _write(workbook, b"workbook")
            unsafe_target = TargetKey("../outside", "CP1", "lab", "V_TEST_CP1")

            def runner(_base_dir: Path) -> None:
                self.fail("runner must not be called for an unsafe TargetKey")

            with self.assertRaisesRegex(
                LegacyStagingError, "LS.TARGET.PATH_ESCAPE"
            ):
                LegacyStagingRenderAdapter(runner).render(
                    inputs=InputRoots(seed, code, fbist, pat_temp, workbook),
                    staging=staging,
                    target=unsafe_target,
                )
            self.assertFalse(staging.exists())

    def test_rejects_staging_inside_an_input_root(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            seed = root / "seed"
            code = root / "inputs" / "code"
            fbist = root / "inputs" / "fbist_pattern"
            pat_temp = root / "inputs" / "pat_temp"
            workbook = root / "inputs" / "program.xlsx"
            staging = seed / "request-staging"
            for directory in (seed, code, fbist, pat_temp):
                directory.mkdir(parents=True, exist_ok=True)
            _write(seed / "platform.ini", b"seed")
            _write(workbook, b"workbook")
            seed_sha_before = _tree_sha256(seed)

            def runner(_base_dir: Path) -> None:
                self.fail("runner must not be called for overlapping paths")

            with self.assertRaisesRegex(
                LegacyStagingError, "LS.STAGING.OVERLAPS_INPUT"
            ):
                LegacyStagingRenderAdapter(runner).render(
                    inputs=InputRoots(seed, code, fbist, pat_temp, workbook),
                    staging=staging,
                    target=TARGET,
                )
            self.assertFalse(staging.exists())
            self.assertEqual(_tree_sha256(seed), seed_sha_before)


if __name__ == "__main__":
    unittest.main()
