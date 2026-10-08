from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from program_gen.publisher import (
    PublishStatus,
    PublisherError,
    TransactionalLegacyPublisher,
    ValidatedGenerationRequest,
    ValidatedTarget,
)


def _tree(path: Path, files: dict[str, bytes]) -> None:
    path.mkdir()
    for relative_path, content in files.items():
        target = path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


class TransactionalLegacyPublisherTests(unittest.TestCase):
    def test_crash_journal_can_be_recovered_idempotently_to_all_old(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            final = root / "final"
            staging = root / "staging"
            _tree(final, {"value.txt": b"old"})
            _tree(staging, {"value.txt": b"new"})
            request = ValidatedGenerationRequest(
                "crash",
                root,
                (ValidatedTarget("a", staging, final, True),),
            )

            def crash_after_backup(source: Path, target: Path) -> None:
                os.replace(source, target)
                if source.name == "final":
                    raise KeyboardInterrupt("simulated process death")

            publisher = TransactionalLegacyPublisher(rename=crash_after_backup)
            with self.assertRaises(KeyboardInterrupt):
                publisher.publish(request)

            journal = root / ".v13-publish-crash.journal.json"
            self.assertTrue(journal.exists())
            result = TransactionalLegacyPublisher().recover(journal)

            self.assertEqual(result.status, PublishStatus.ROLLED_BACK)
            self.assertEqual((final / "value.txt").read_bytes(), b"old")
            self.assertEqual((staging / "value.txt").read_bytes(), b"new")
            self.assertFalse(journal.exists())
    def test_one_failed_target_blocks_the_entire_request_before_any_rename(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            final_a = root / "final-a"
            final_b = root / "final-b"
            stage_a = root / "stage-a"
            stage_b = root / "stage-b"
            _tree(final_a, {"old.txt": b"old-a"})
            _tree(final_b, {"old.txt": b"old-b"})
            _tree(stage_a, {"new.txt": b"new-a"})
            _tree(stage_b, {"new.txt": b"new-b"})
            request = ValidatedGenerationRequest(
                request_id="gate",
                output_root=root,
                targets=(
                    ValidatedTarget("a", stage_a, final_a, validation_passed=True),
                    ValidatedTarget("b", stage_b, final_b, validation_passed=False),
                ),
            )
            renames = []

            with self.assertRaisesRegex(PublisherError, "PUB.REQUEST.TARGET_NOT_VALIDATED"):
                TransactionalLegacyPublisher(
                    rename=lambda source, target: renames.append((source, target))
                ).publish(request)

            self.assertEqual(renames, [])
            self.assertEqual((final_a / "old.txt").read_bytes(), b"old-a")
            self.assertEqual((final_b / "old.txt").read_bytes(), b"old-b")
            self.assertFalse(any(root.glob("*.journal.json")))

    def test_success_replaces_whole_directories_and_removes_stale_files(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            final_a = root / "final-a"
            final_b = root / "final-b"
            stage_a = root / "stage-a"
            stage_b = root / "stage-b"
            _tree(final_a, {"stale.txt": b"stale", "keep.txt": b"old"})
            _tree(final_b, {"stale.txt": b"stale"})
            _tree(stage_a, {"keep.txt": b"new"})
            _tree(stage_b, {"only-new.txt": b"new"})
            request = ValidatedGenerationRequest(
                "success",
                root,
                (
                    ValidatedTarget("a", stage_a, final_a, True),
                    ValidatedTarget("b", stage_b, final_b, True),
                ),
            )

            result = TransactionalLegacyPublisher().publish(request)

            self.assertEqual(result.status, PublishStatus.PUBLISHED)
            self.assertFalse(result.recovery_required)
            self.assertEqual((final_a / "keep.txt").read_bytes(), b"new")
            self.assertFalse((final_a / "stale.txt").exists())
            self.assertEqual((final_b / "only-new.txt").read_bytes(), b"new")
            self.assertFalse(stage_a.exists())
            self.assertFalse(stage_b.exists())
            self.assertFalse(result.journal_path.exists())
            self.assertFalse(any(root.glob("*.backup-*")))

    def test_injected_rename_failure_rolls_back_targets_in_reverse_order(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            final_a = root / "final-a"
            final_b = root / "final-b"
            stage_a = root / "stage-a"
            stage_b = root / "stage-b"
            _tree(final_a, {"value.txt": b"old-a"})
            _tree(final_b, {"value.txt": b"old-b"})
            _tree(stage_a, {"value.txt": b"new-a"})
            _tree(stage_b, {"value.txt": b"new-b"})
            request = ValidatedGenerationRequest(
                "rollback",
                root,
                (
                    ValidatedTarget("a", stage_a, final_a, True),
                    ValidatedTarget("b", stage_b, final_b, True),
                ),
            )
            calls: list[tuple[str, str]] = []
            failed = False

            def rename(source: Path, target: Path) -> None:
                nonlocal failed
                calls.append((source.name, target.name))
                if source.name == "stage-b" and target.name == "final-b" and not failed:
                    failed = True
                    raise OSError("injected promotion failure")
                os.replace(source, target)

            result = TransactionalLegacyPublisher(rename=rename).publish(request)

            self.assertEqual(result.status, PublishStatus.ROLLED_BACK)
            self.assertFalse(result.recovery_required)
            self.assertEqual((final_a / "value.txt").read_bytes(), b"old-a")
            self.assertEqual((final_b / "value.txt").read_bytes(), b"old-b")
            self.assertEqual((stage_a / "value.txt").read_bytes(), b"new-a")
            self.assertEqual((stage_b / "value.txt").read_bytes(), b"new-b")
            self.assertFalse(result.journal_path.exists())
            # B is restored first; A's newly published directory then its backup.
            self.assertEqual(
                calls[-3:],
                [
                    (f".final-b.backup-rollback", "final-b"),
                    ("final-a", "stage-a"),
                    (f".final-a.backup-rollback", "final-a"),
                ],
            )

    def test_rollback_failure_keeps_journal_and_backup_for_recovery(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            final_a = root / "final-a"
            final_b = root / "final-b"
            stage_a = root / "stage-a"
            stage_b = root / "stage-b"
            _tree(final_a, {"value.txt": b"old-a"})
            _tree(final_b, {"value.txt": b"old-b"})
            _tree(stage_a, {"value.txt": b"new-a"})
            _tree(stage_b, {"value.txt": b"new-b"})
            request = ValidatedGenerationRequest(
                "recovery",
                root,
                (
                    ValidatedTarget("a", stage_a, final_a, True),
                    ValidatedTarget("b", stage_b, final_b, True),
                ),
            )

            def rename(source: Path, target: Path) -> None:
                if source.name == "stage-b" and target.name == "final-b":
                    raise OSError("promotion failure")
                if source.name == ".final-b.backup-recovery" and target.name == "final-b":
                    raise OSError("rollback failure")
                os.replace(source, target)

            result = TransactionalLegacyPublisher(rename=rename).publish(request)

            self.assertEqual(result.status, PublishStatus.RECOVERY_REQUIRED)
            self.assertTrue(result.recovery_required)
            self.assertTrue(result.journal_path.exists())
            journal = json.loads(result.journal_path.read_text(encoding="utf-8"))
            self.assertEqual(journal["status"], "RECOVERY_REQUIRED")
            self.assertTrue(journal["rollback_errors"])
            backup_b = root / ".final-b.backup-recovery"
            self.assertEqual((backup_b / "value.txt").read_bytes(), b"old-b")
            self.assertEqual((final_a / "value.txt").read_bytes(), b"old-a")

    def test_preflight_rejects_overlapping_or_out_of_root_targets(self):
        with TemporaryDirectory() as temp, TemporaryDirectory() as outside_temp:
            root = Path(temp)
            stage_a = root / "stage-a"
            final_a = root / "formal"
            stage_b = root / "stage-b"
            final_b = final_a / "nested"
            _tree(stage_a, {"x": b"x"})
            _tree(stage_b, {"x": b"x"})
            overlap = ValidatedGenerationRequest(
                "overlap",
                root,
                (
                    ValidatedTarget("a", stage_a, final_a, True),
                    ValidatedTarget("b", stage_b, final_b, True),
                ),
            )
            with self.assertRaisesRegex(PublisherError, "PUB.TARGET.FINAL_OVERLAP"):
                TransactionalLegacyPublisher().publish(overlap)

            outside_stage = Path(outside_temp) / "stage"
            outside_final = Path(outside_temp) / "final"
            _tree(outside_stage, {"x": b"x"})
            outside = ValidatedGenerationRequest(
                "outside",
                root,
                (ValidatedTarget("outside", outside_stage, outside_final, True),),
            )
            with self.assertRaisesRegex(PublisherError, "PUB.TARGET.OUT_OF_ROOT"):
                TransactionalLegacyPublisher().publish(outside)


if __name__ == "__main__":
    unittest.main()
