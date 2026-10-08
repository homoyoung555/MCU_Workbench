"""Read-only staging validation and reproducible external-tool evidence.

The validator accepts the public ``ArtifactSet`` produced by materialization.
It has no formal-output path and performs no writes: an injected/default runner
is invoked with the staging root as its working directory, and the complete
artifact closure is checked both before and after that invocation.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Callable

from .render_plan import (
    ArtifactSet,
    MANIFEST_FILENAME,
    MANIFEST_SCHEMA,
    MaterializedArtifact,
    TargetKey,
)


class TargetValidationError(ValueError):
    """The validation command itself is not an explicit, executable contract."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class ValidationCommand:
    tool_identity: str
    command: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "command", tuple(str(item) for item in self.command))
        if not self.tool_identity.strip():
            raise TargetValidationError(
                "TV.COMMAND.TOOL_IDENTITY_MISSING",
                "external validation requires an explicit tool identity",
            )
        if not self.command or any(not item for item in self.command):
            raise TargetValidationError(
                "TV.COMMAND.EMPTY", "external validation requires a complete command"
            )


@dataclass(frozen=True)
class ValidationDiagnostic:
    code: str
    message: str
    phase: str
    blocking: bool = True


@dataclass(frozen=True)
class CompilerEvidence:
    exit_code: int
    stdout: bytes
    stderr: bytes
    stdout_sha256: str
    stderr_sha256: str
    log_sha256: str


@dataclass(frozen=True)
class ValidationResult:
    target: TargetKey
    tool_identity: str
    command: tuple[str, ...]
    manifest_identity: str
    pre_closure_identity: str
    post_closure_identity: str | None
    compiler: CompilerEvidence | None
    diagnostics: tuple[ValidationDiagnostic, ...]
    passed: bool
    identity: str


@dataclass(frozen=True)
class _Inspection:
    diagnostics: tuple[ValidationDiagnostic, ...]
    closure_identity: str


Runner = Callable[[tuple[str, ...], Path], object]


class TargetValidator:
    """Validate one closed target without knowing or mutating formal outputs."""

    def __init__(self, *, runner: Runner | None = None):
        self._runner = runner or self._run_subprocess

    def validate(
        self, artifacts: ArtifactSet, command: ValidationCommand
    ) -> ValidationResult:
        pre = self._inspect(artifacts, phase="PRE_COMPILE")
        diagnostics = list(pre.diagnostics)
        if diagnostics:
            return self._result(
                artifacts,
                command,
                pre_closure_identity=pre.closure_identity,
                post_closure_identity=None,
                compiler=None,
                diagnostics=tuple(diagnostics),
            )

        compiler = None
        post = None
        try:
            with tempfile.TemporaryDirectory(
                prefix="v13-target-validation-", ignore_cleanup_errors=True
            ) as temp:
                # Both platform wrappers resolve the primary project from the
                # containing directory name, so the isolated copy must retain
                # the declared program identity instead of using a generic
                # sandbox basename such as ``target``.
                compile_root = Path(temp) / artifacts.target.program_name
                shutil.copytree(artifacts.root, compile_root)
                try:
                    completed = self._runner(command.command, compile_root)
                    compiler = self._compiler_evidence(completed)
                except Exception as error:
                    diagnostics.append(ValidationDiagnostic(
                        "TV.COMPILER.EXECUTION_ERROR",
                        f"{type(error).__name__}: {error}",
                        "COMPILE",
                    ))
                post = self._inspect(
                    artifacts,
                    phase="POST_COMPILE",
                    root_override=compile_root,
                    allow_extra=True,
                )
        except OSError as error:
            diagnostics.append(ValidationDiagnostic(
                "TV.COMPILER.SANDBOX_ERROR",
                f"{type(error).__name__}: {error}",
                "COMPILE",
            ))
        if post is None:
            post = _Inspection((), pre.closure_identity)
        diagnostics.extend(post.diagnostics)
        if compiler is not None and compiler.exit_code != 0:
            diagnostics.append(ValidationDiagnostic(
                "TV.COMPILER.NONZERO_EXIT",
                f"external compiler exited with code {compiler.exit_code}",
                "COMPILE",
            ))
        return self._result(
            artifacts,
            command,
            pre_closure_identity=pre.closure_identity,
            post_closure_identity=post.closure_identity,
            compiler=compiler,
            diagnostics=tuple(diagnostics),
        )

    def _inspect(
        self,
        artifacts: ArtifactSet,
        *,
        phase: str,
        root_override: Path | None = None,
        allow_extra: bool = False,
    ) -> _Inspection:
        diagnostics: list[ValidationDiagnostic] = []
        root = Path(artifacts.root if root_override is None else root_override)
        if not root.exists() or not root.is_dir() or root.is_symlink():
            diagnostics.append(ValidationDiagnostic(
                "TV.STAGING.INVALID",
                "artifact root is not a real staging directory",
                phase,
            ))
            return _Inspection(tuple(diagnostics), _hash_json({"invalid": True}))

        expected: dict[str, MaterializedArtifact] = {}
        expected_case: dict[str, str] = {}
        for artifact in artifacts.artifacts:
            try:
                path = _safe_relative_path(artifact.relative_path)
            except TargetValidationError as error:
                diagnostics.append(ValidationDiagnostic(error.code, str(error), phase))
                continue
            case_key = path.casefold()
            previous = expected_case.get(case_key)
            if previous is not None and previous != path:
                diagnostics.append(ValidationDiagnostic(
                    "TV.ARTIFACT.WINDOWS_COLLISION",
                    f"expected paths collide on Windows: {previous!r}, {path!r}",
                    phase,
                ))
            expected_case[case_key] = path
            if path in expected and expected[path] != artifact:
                diagnostics.append(ValidationDiagnostic(
                    "TV.ARTIFACT.CONFLICT",
                    f"expected artifact {path!r} has conflicting metadata",
                    phase,
                ))
            expected[path] = artifact

        actual: dict[str, tuple[int, str]] = {}
        actual_case: dict[str, str] = {}
        try:
            entries = sorted(
                root.rglob("*"),
                key=lambda item: item.relative_to(root).as_posix().casefold(),
            )
            for entry in entries:
                relative = entry.relative_to(root).as_posix()
                if entry.is_symlink():
                    diagnostics.append(ValidationDiagnostic(
                        "TV.FILE_SET.SYMLINK",
                        f"staging contains a symlink: {relative!r}",
                        phase,
                    ))
                    continue
                if not entry.is_file():
                    continue
                case_key = relative.casefold()
                previous = actual_case.get(case_key)
                if previous is not None and previous != relative:
                    diagnostics.append(ValidationDiagnostic(
                        "TV.FILE_SET.WINDOWS_COLLISION",
                        f"staging paths collide on Windows: {previous!r}, {relative!r}",
                        phase,
                    ))
                actual_case[case_key] = relative
                content = entry.read_bytes()
                actual[relative] = (len(content), _sha256(content))
        except OSError as error:
            diagnostics.append(ValidationDiagnostic(
                "TV.STAGING.READ_ERROR",
                f"staging cannot be read completely: {type(error).__name__}: {error}",
                phase,
            ))

        expected_paths = set(expected) | {MANIFEST_FILENAME}
        actual_paths = set(actual)
        for path in sorted(expected_paths - actual_paths, key=str.casefold):
            diagnostics.append(ValidationDiagnostic(
                "TV.FILE_SET.MISSING", f"expected file is missing: {path!r}", phase
            ))
        if not allow_extra:
            for path in sorted(actual_paths - expected_paths, key=str.casefold):
                diagnostics.append(ValidationDiagnostic(
                    "TV.FILE_SET.EXTRA", f"unmanifested file is present: {path!r}", phase
                ))

        for path, expected_artifact in sorted(
            expected.items(), key=lambda item: item[0].casefold()
        ):
            current = actual.get(path)
            if current is None:
                continue
            size, digest = current
            if size != expected_artifact.size:
                diagnostics.append(ValidationDiagnostic(
                    "TV.ARTIFACT.SIZE_MISMATCH",
                    f"artifact size drifted: {path!r}",
                    phase,
                ))
            if digest.upper() != expected_artifact.sha256.upper():
                diagnostics.append(ValidationDiagnostic(
                    "TV.ARTIFACT.HASH_MISMATCH",
                    f"artifact content hash drifted: {path!r}",
                    phase,
                ))

        manifest_bytes = None
        manifest_path = root / MANIFEST_FILENAME
        if manifest_path.is_file() and not manifest_path.is_symlink():
            try:
                manifest_bytes = manifest_path.read_bytes()
            except OSError as error:
                diagnostics.append(ValidationDiagnostic(
                    "TV.MANIFEST.READ_ERROR",
                    f"manifest cannot be read: {type(error).__name__}: {error}",
                    phase,
                ))
        if manifest_bytes is not None:
            manifest_digest = _sha256(manifest_bytes)
            if manifest_digest.upper() != artifacts.manifest_identity.upper():
                diagnostics.append(ValidationDiagnostic(
                    "TV.MANIFEST.IDENTITY_MISMATCH",
                    "manifest hash does not match the materialized ArtifactSet identity",
                    phase,
                ))
            self._validate_manifest(
                artifacts, expected, manifest_bytes, diagnostics, phase
            )

        closure = {
            "manifest_identity": artifacts.manifest_identity,
            "files": [
                {"path": path, "size": size, "sha256": digest}
                for path, (size, digest) in sorted(
                    (
                        item for item in actual.items()
                        if not allow_extra or item[0] in expected_paths
                    ),
                    key=lambda item: item[0].casefold(),
                )
            ],
        }
        return _Inspection(tuple(diagnostics), _hash_json(closure))

    @staticmethod
    def _validate_manifest(
        artifacts: ArtifactSet,
        expected: dict[str, MaterializedArtifact],
        manifest_bytes: bytes,
        diagnostics: list[ValidationDiagnostic],
        phase: str,
    ) -> None:
        try:
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            diagnostics.append(ValidationDiagnostic(
                "TV.MANIFEST.INVALID_JSON",
                f"manifest is not canonical readable JSON: {type(error).__name__}: {error}",
                phase,
            ))
            return
        if manifest.get("schema") != MANIFEST_SCHEMA:
            diagnostics.append(ValidationDiagnostic(
                "TV.MANIFEST.SCHEMA_MISMATCH",
                "manifest schema is not supported",
                phase,
            ))
        target = manifest.get("target")
        expected_target = {
            "platform": artifacts.target.platform,
            "cp": artifacts.target.cp,
            "variant": artifacts.target.variant,
            "program_name": artifacts.target.program_name,
        }
        if target != expected_target:
            diagnostics.append(ValidationDiagnostic(
                "TV.MANIFEST.TARGET_MISMATCH",
                "manifest target does not match the ArtifactSet target",
                phase,
            ))
        rows = manifest.get("artifacts")
        if not isinstance(rows, list):
            diagnostics.append(ValidationDiagnostic(
                "TV.MANIFEST.ARTIFACT_SET_MISMATCH",
                "manifest artifact collection is missing",
                phase,
            ))
            return
        projected = []
        for row in rows:
            if not isinstance(row, dict):
                projected.append(None)
                continue
            projected.append({
                "path": row.get("path"),
                "size": row.get("size"),
                "sha256": row.get("sha256"),
            })
        expected_projection = [
            {"path": path, "size": item.size, "sha256": item.sha256}
            for path, item in sorted(expected.items(), key=lambda pair: pair[0].casefold())
        ]
        if projected != expected_projection:
            diagnostics.append(ValidationDiagnostic(
                "TV.MANIFEST.ARTIFACT_SET_MISMATCH",
                "manifest artifact rows do not match the materialized ArtifactSet",
                phase,
            ))

    @staticmethod
    def _compiler_evidence(completed: object) -> CompilerEvidence:
        exit_code = int(getattr(completed, "returncode"))
        stdout = _as_bytes(getattr(completed, "stdout", b""))
        stderr = _as_bytes(getattr(completed, "stderr", b""))
        stdout_sha = _sha256(stdout)
        stderr_sha = _sha256(stderr)
        log_sha = _hash_json({
            "exit_code": exit_code,
            "stdout_sha256": stdout_sha,
            "stderr_sha256": stderr_sha,
        })
        return CompilerEvidence(
            exit_code,
            stdout,
            stderr,
            stdout_sha,
            stderr_sha,
            log_sha,
        )

    @staticmethod
    def _result(
        artifacts: ArtifactSet,
        command: ValidationCommand,
        *,
        pre_closure_identity: str,
        post_closure_identity: str | None,
        compiler: CompilerEvidence | None,
        diagnostics: tuple[ValidationDiagnostic, ...],
    ) -> ValidationResult:
        passed = not any(item.blocking for item in diagnostics)
        payload = {
            "target": artifacts.target.identity,
            "tool_identity": command.tool_identity,
            "command": command.command,
            "manifest_identity": artifacts.manifest_identity,
            "pre_closure_identity": pre_closure_identity,
            "post_closure_identity": post_closure_identity,
            "compiler": None if compiler is None else {
                "exit_code": compiler.exit_code,
                "stdout_sha256": compiler.stdout_sha256,
                "stderr_sha256": compiler.stderr_sha256,
                "log_sha256": compiler.log_sha256,
            },
            "diagnostics": [
                {
                    "code": item.code,
                    "message": item.message,
                    "phase": item.phase,
                    "blocking": item.blocking,
                }
                for item in diagnostics
            ],
            "passed": passed,
        }
        return ValidationResult(
            target=artifacts.target,
            tool_identity=command.tool_identity,
            command=command.command,
            manifest_identity=artifacts.manifest_identity,
            pre_closure_identity=pre_closure_identity,
            post_closure_identity=post_closure_identity,
            compiler=compiler,
            diagnostics=diagnostics,
            passed=passed,
            identity=_hash_json(payload),
        )

    @staticmethod
    def _run_subprocess(command: tuple[str, ...], cwd: Path):
        return subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            check=False,
        )


def _safe_relative_path(value: str) -> str:
    raw = str(value)
    slash = raw.replace("\\", "/")
    if (
        not slash
        or slash.startswith("/")
        or re.match(r"^[A-Za-z]:", slash)
        or any(part in ("", ".", "..") for part in slash.split("/"))
    ):
        raise TargetValidationError(
            "TV.ARTIFACT.UNSAFE_PATH", f"artifact path is unsafe: {raw!r}"
        )
    return slash


def _as_bytes(value: bytes | bytearray | str | None) -> bytes:
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("utf-8")
    raise TypeError("compiler stdout/stderr must be bytes, str, bytearray, or None")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def _hash_json(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256(encoded)
