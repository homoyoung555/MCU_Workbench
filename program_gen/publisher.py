"""Request-level transactional promotion for fixed legacy output paths.

The publisher uses same-volume directory renames plus a recovery journal.  It
provides rollback/recovery semantics across several fixed target directories;
it intentionally does not claim that several independent renames are one
instantaneous filesystem transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import os
from pathlib import Path
import re
import shutil
from typing import Callable


JOURNAL_SCHEMA = "v13.legacy-publish-journal/1"


class PublisherError(ValueError):
    """The request cannot safely enter its first publication rename."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


class PublishStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    ROLLED_BACK = "ROLLED_BACK"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


@dataclass(frozen=True)
class ValidatedTarget:
    target_id: str
    staging_directory: Path
    final_directory: Path
    validation_passed: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "staging_directory", Path(self.staging_directory))
        object.__setattr__(self, "final_directory", Path(self.final_directory))


@dataclass(frozen=True)
class ValidatedGenerationRequest:
    request_id: str
    output_root: Path
    targets: tuple[ValidatedTarget, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_root", Path(self.output_root))
        object.__setattr__(self, "targets", tuple(self.targets))

    def require_all_targets_validated(self) -> None:
        failed = tuple(
            target.target_id for target in self.targets if not target.validation_passed
        )
        if failed:
            raise PublisherError(
                "PUB.REQUEST.TARGET_NOT_VALIDATED",
                f"request has targets that did not pass validation: {', '.join(failed)}",
            )


@dataclass(frozen=True)
class PublishResult:
    status: PublishStatus
    journal_path: Path
    published_targets: tuple[str, ...]
    error: str | None = None
    rollback_errors: tuple[str, ...] = ()

    @property
    def recovery_required(self) -> bool:
        return self.status is PublishStatus.RECOVERY_REQUIRED


@dataclass
class _TargetTransaction:
    target: ValidatedTarget
    final: Path
    staging: Path
    backup: Path
    had_final: bool
    final_to_backup: bool = False
    staging_to_final: bool = False


class TransactionalLegacyPublisher:
    """Promote one validated request with journalled reverse-order rollback."""

    def __init__(
        self,
        *,
        rename: Callable[[Path, Path], None] | None = None,
        remove_tree: Callable[[Path], None] | None = None,
    ):
        self._rename = rename or os.replace
        self._remove_tree = remove_tree or shutil.rmtree

    def publish(self, request: ValidatedGenerationRequest) -> PublishResult:
        request.require_all_targets_validated()
        transactions, journal_path = self._preflight(request)
        journal = self._journal(request, transactions, status="PREPARED")
        self._write_journal(journal_path, journal)

        try:
            for transaction in transactions:
                if transaction.had_final:
                    self._rename(transaction.final, transaction.backup)
                    transaction.final_to_backup = True
                    self._record(journal_path, journal, transactions, "PROMOTING")
                self._rename(transaction.staging, transaction.final)
                transaction.staging_to_final = True
                self._record(journal_path, journal, transactions, "PROMOTING")
        except Exception as error:
            return self._rollback(
                journal_path, journal, transactions, promotion_error=error
            )

        cleanup_errors = []
        for transaction in transactions:
            if transaction.backup.exists():
                try:
                    self._remove_tree(transaction.backup)
                except Exception as error:
                    cleanup_errors.append(
                        f"cleanup {transaction.backup}: {type(error).__name__}: {error}"
                    )
        if cleanup_errors:
            journal["status"] = PublishStatus.RECOVERY_REQUIRED.value
            journal["rollback_errors"] = cleanup_errors
            self._write_journal(journal_path, journal)
            return PublishResult(
                PublishStatus.RECOVERY_REQUIRED,
                journal_path,
                tuple(item.target.target_id for item in transactions),
                error="published targets require backup cleanup",
                rollback_errors=tuple(cleanup_errors),
            )

        journal["status"] = PublishStatus.PUBLISHED.value
        self._write_journal(journal_path, journal)
        journal_path.unlink()
        return PublishResult(
            PublishStatus.PUBLISHED,
            journal_path,
            tuple(item.target.target_id for item in transactions),
        )

    def recover(self, journal_path: str | Path) -> PublishResult:
        """Restore all-old after an interrupted promotion, using disk truth.

        Recovery deliberately does not trust the last persisted booleans: a
        process may die after a directory rename and before the next journal
        fsync.  The sibling final/staging/backup presence is therefore the
        authoritative state machine.
        """
        path = Path(journal_path).resolve()
        if not path.is_file() or path.is_symlink():
            raise PublisherError(
                "PUB.RECOVERY.JOURNAL_INVALID", f"journal is unavailable: {path}"
            )
        journal = json.loads(path.read_text(encoding="utf-8"))
        if journal.get("schema") != JOURNAL_SCHEMA:
            raise PublisherError(
                "PUB.RECOVERY.SCHEMA_INVALID", "journal schema is not supported"
            )
        records = tuple(journal.get("targets") or ())
        errors = []
        journal["status"] = "RECOVERING"
        self._write_journal(path, journal)
        for record in reversed(records):
            target_id = str(record.get("target_id", ""))
            staging = Path(record["staging"]).resolve()
            final = Path(record["final"]).resolve()
            backup = Path(record["backup"]).resolve()
            try:
                for endpoint in (staging, final, backup):
                    endpoint.relative_to(path.parent)
                    if endpoint.is_symlink():
                        raise PublisherError(
                            "PUB.RECOVERY.SYMLINK",
                            f"recovery endpoint is a symlink: {endpoint}",
                        )
                if backup.exists():
                    if final.exists():
                        if staging.exists():
                            raise PublisherError(
                                "PUB.RECOVERY.AMBIGUOUS",
                                f"{target_id} has final, staging, and backup",
                            )
                        self._rename(final, staging)
                    self._rename(backup, final)
                elif bool(record.get("had_final")):
                    if not final.exists():
                        raise PublisherError(
                            "PUB.RECOVERY.OLD_FINAL_MISSING",
                            f"old final cannot be recovered for {target_id}",
                        )
                elif final.exists() and not staging.exists():
                    self._rename(final, staging)
                elif final.exists() and staging.exists():
                    raise PublisherError(
                        "PUB.RECOVERY.AMBIGUOUS",
                        f"new target {target_id} exists in final and staging",
                    )
            except Exception as error:
                errors.append(f"recover {target_id}: {type(error).__name__}: {error}")
        if errors:
            journal["status"] = PublishStatus.RECOVERY_REQUIRED.value
            journal["rollback_errors"] = errors
            self._write_journal(path, journal)
            return PublishResult(
                PublishStatus.RECOVERY_REQUIRED,
                path,
                (),
                error="interrupted publication recovery failed",
                rollback_errors=tuple(errors),
            )
        path.unlink()
        return PublishResult(PublishStatus.ROLLED_BACK, path, ())

    def _preflight(
        self, request: ValidatedGenerationRequest
    ) -> tuple[tuple[_TargetTransaction, ...], Path]:
        if not request.targets:
            raise PublisherError("PUB.REQUEST.EMPTY", "request has no targets")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", request.request_id):
            raise PublisherError(
                "PUB.REQUEST.INVALID_ID",
                f"request id is not filesystem-safe: {request.request_id!r}",
            )

        root = request.output_root.resolve()
        if not root.exists() or not root.is_dir() or root.is_symlink():
            raise PublisherError(
                "PUB.ROOT.INVALID", f"output root is not a real directory: {root}"
            )
        identities: set[str] = set()
        resolved: list[tuple[ValidatedTarget, Path, Path]] = []
        for target in request.targets:
            target_key = target.target_id.casefold()
            if not target.target_id or target_key in identities:
                raise PublisherError(
                    "PUB.TARGET.IDENTITY_CONFLICT",
                    f"target identity is empty or duplicated: {target.target_id!r}",
                )
            identities.add(target_key)
            staging = target.staging_directory.resolve()
            final = target.final_directory.resolve()
            self._require_inside(root, staging, target.target_id)
            self._require_inside(root, final, target.target_id)
            resolved.append((target, staging, final))

        self._reject_final_overlaps(tuple(final for _, _, final in resolved))

        endpoints: list[tuple[str, Path]] = []
        transactions = []
        for target, staging, final in resolved:
            if staging.parent != final.parent:
                raise PublisherError(
                    "PUB.TARGET.NOT_SIBLING_STAGING",
                    f"target {target.target_id!r} staging must be a sibling of final",
                )
            if staging.anchor.casefold() != final.anchor.casefold():
                raise PublisherError(
                    "PUB.TARGET.CROSS_VOLUME",
                    f"target {target.target_id!r} staging and final are on different volumes",
                )
            if not staging.exists() or not staging.is_dir() or staging.is_symlink():
                raise PublisherError(
                    "PUB.TARGET.INVALID_STAGING",
                    f"target {target.target_id!r} staging is not a real directory",
                )
            if final.is_symlink():
                raise PublisherError(
                    "PUB.TARGET.FINAL_SYMLINK",
                    f"target {target.target_id!r} final cannot be a symlink",
                )
            if not final.parent.exists() or not final.parent.is_dir():
                raise PublisherError(
                    "PUB.TARGET.INVALID_PARENT",
                    f"target {target.target_id!r} final parent is unavailable",
                )
            backup = final.with_name(f".{final.name}.backup-{request.request_id}")
            if backup.exists():
                raise PublisherError(
                    "PUB.TARGET.BACKUP_EXISTS",
                    f"recovery backup already exists: {backup}",
                )
            endpoints.extend((("staging", staging), ("final", final), ("backup", backup)))
            transactions.append(_TargetTransaction(
                target=target,
                final=final,
                staging=staging,
                backup=backup,
                had_final=final.exists(),
            ))

        self._reject_endpoint_overlaps(tuple(endpoints))
        journal_path = root / f".v13-publish-{request.request_id}.journal.json"
        if journal_path.exists() or journal_path.with_suffix(".tmp").exists():
            raise PublisherError(
                "PUB.REQUEST.JOURNAL_EXISTS",
                f"publication journal already exists: {journal_path}",
            )
        return tuple(transactions), journal_path

    @staticmethod
    def _require_inside(root: Path, path: Path, target_id: str) -> None:
        try:
            relative = path.relative_to(root)
        except ValueError as error:
            raise PublisherError(
                "PUB.TARGET.OUT_OF_ROOT",
                f"target {target_id!r} path escapes output root: {path}",
            ) from error
        if not relative.parts:
            raise PublisherError(
                "PUB.TARGET.OUT_OF_ROOT",
                f"target {target_id!r} cannot replace the output root itself",
            )

    @staticmethod
    def _reject_final_overlaps(finals: tuple[Path, ...]) -> None:
        for index, left in enumerate(finals):
            for right in finals[index + 1 :]:
                if _overlaps(left, right):
                    raise PublisherError(
                        "PUB.TARGET.FINAL_OVERLAP",
                        f"target final directories overlap: {left} and {right}",
                    )

    @staticmethod
    def _reject_endpoint_overlaps(endpoints: tuple[tuple[str, Path], ...]) -> None:
        for index, (left_kind, left) in enumerate(endpoints):
            for right_kind, right in endpoints[index + 1 :]:
                if _overlaps(left, right):
                    raise PublisherError(
                        "PUB.TARGET.PATH_OVERLAP",
                        f"{left_kind} {left} overlaps {right_kind} {right}",
                    )

    @staticmethod
    def _journal(
        request: ValidatedGenerationRequest,
        transactions: tuple[_TargetTransaction, ...],
        *,
        status: str,
    ) -> dict:
        return {
            "schema": JOURNAL_SCHEMA,
            "request_id": request.request_id,
            "status": status,
            "promotion_error": None,
            "rollback_errors": [],
            "targets": TransactionalLegacyPublisher._target_records(transactions),
        }

    def _record(
        self,
        journal_path: Path,
        journal: dict,
        transactions: tuple[_TargetTransaction, ...],
        status: str,
    ) -> None:
        journal["status"] = status
        journal["targets"] = self._target_records(transactions)
        self._write_journal(journal_path, journal)

    @staticmethod
    def _target_records(
        transactions: tuple[_TargetTransaction, ...]
    ) -> list[dict]:
        return [
            {
                "target_id": item.target.target_id,
                "staging": str(item.staging),
                "final": str(item.final),
                "backup": str(item.backup),
                "had_final": item.had_final,
                "final_to_backup": item.final_to_backup,
                "staging_to_final": item.staging_to_final,
            }
            for item in transactions
        ]

    @staticmethod
    def _write_journal(path: Path, journal: dict) -> None:
        temporary = path.with_suffix(".tmp")
        encoded = json.dumps(
            journal,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with temporary.open("w", encoding="utf-8", newline="") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)

    def _rollback(
        self,
        journal_path: Path,
        journal: dict,
        transactions: tuple[_TargetTransaction, ...],
        *,
        promotion_error: Exception,
    ) -> PublishResult:
        rollback_errors = []
        for transaction in reversed(transactions):
            if transaction.staging_to_final:
                try:
                    self._rename(transaction.final, transaction.staging)
                    transaction.staging_to_final = False
                except Exception as error:
                    rollback_errors.append(
                        f"restore staging {transaction.target.target_id}: "
                        f"{type(error).__name__}: {error}"
                    )
            if transaction.final_to_backup:
                try:
                    self._rename(transaction.backup, transaction.final)
                    transaction.final_to_backup = False
                except Exception as error:
                    rollback_errors.append(
                        f"restore final {transaction.target.target_id}: "
                        f"{type(error).__name__}: {error}"
                    )

        error_text = f"{type(promotion_error).__name__}: {promotion_error}"
        journal["promotion_error"] = error_text
        journal["rollback_errors"] = rollback_errors
        if rollback_errors:
            self._record(
                journal_path,
                journal,
                transactions,
                PublishStatus.RECOVERY_REQUIRED.value,
            )
            return PublishResult(
                PublishStatus.RECOVERY_REQUIRED,
                journal_path,
                (),
                error=error_text,
                rollback_errors=tuple(rollback_errors),
            )

        self._record(
            journal_path,
            journal,
            transactions,
            PublishStatus.ROLLED_BACK.value,
        )
        journal_path.unlink()
        return PublishResult(
            PublishStatus.ROLLED_BACK,
            journal_path,
            (),
            error=error_text,
        )


def _overlaps(left: Path, right: Path) -> bool:
    left_parts = tuple(part.casefold() for part in left.parts)
    right_parts = tuple(part.casefold() for part in right.parts)
    shorter = min(len(left_parts), len(right_parts))
    return left_parts[:shorter] == right_parts[:shorter]
