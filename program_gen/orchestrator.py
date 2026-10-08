"""Single-compilation, request-level generation orchestration.

The orchestrator owns ordering and request gates, not workbook reading,
business compilation, platform rendering, validation internals, or fixed-path
promotion.  Those operations are injected through their public contracts.  A
private legacy renderer can therefore be removed without changing this module
once every target has a native staging renderer returning ``ArtifactSet``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Callable

from .publisher import (
    PublishResult,
    PublishStatus,
    ValidatedGenerationRequest,
    ValidatedTarget,
)
from .render_plan import ArtifactSet, TargetKey
from .validation import ValidationCommand, ValidationResult


class OrchestrationError(ValueError):
    """A request cannot safely fan out from the supplied compilation."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


class OrchestrationStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    RENDER_FAILED = "RENDER_FAILED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    PUBLISH_FAILED = "PUBLISH_FAILED"


@dataclass(frozen=True)
class GenerationTarget:
    key: TargetKey
    staging_directory: Path
    final_directory: Path
    validation_command: ValidationCommand

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "staging_directory", Path(self.staging_directory).resolve()
        )
        object.__setattr__(
            self, "final_directory", Path(self.final_directory).resolve()
        )


@dataclass(frozen=True)
class GenerationRequest:
    compilation_identity: str
    output_root: Path
    targets: tuple[GenerationTarget, ...]
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        if not str(self.compilation_identity).strip():
            raise OrchestrationError(
                "OR.REQUEST.COMPILATION_IDENTITY_MISSING",
                "generation request must bind one ProductCompilation identity",
            )
        root = Path(self.output_root).resolve()
        targets = tuple(sorted(tuple(self.targets), key=_target_order))
        if not targets:
            raise OrchestrationError(
                "OR.REQUEST.EMPTY", "generation request has no explicit targets"
            )
        seen = set()
        canonical_targets = []
        for target in targets:
            key = target.key.identity.casefold()
            if key in seen:
                raise OrchestrationError(
                    "OR.REQUEST.TARGET_DUPLICATE",
                    f"generation target is duplicated: {target.key.identity}",
                )
            seen.add(key)
            staging = _relative_to_root(root, target.staging_directory, target.key)
            final = _relative_to_root(root, target.final_directory, target.key)
            if staging.casefold() == final.casefold():
                raise OrchestrationError(
                    "OR.REQUEST.TARGET_PATH_CONFLICT",
                    f"target staging and final paths are identical: {target.key.identity}",
                )
            canonical_targets.append({
                "target": {
                    "platform": target.key.platform,
                    "cp": target.key.cp,
                    "variant": target.key.variant,
                    "program_name": target.key.program_name,
                },
                "staging": staging,
                "final": final,
                "tool_identity": target.validation_command.tool_identity,
                "command": target.validation_command.command,
            })
        payload = {
            "schema": "v13.generation-request/1",
            "compilation_identity": self.compilation_identity,
            "targets": canonical_targets,
        }
        object.__setattr__(self, "output_root", root)
        object.__setattr__(self, "targets", targets)
        object.__setattr__(self, "identity", _hash_json(payload))


@dataclass(frozen=True)
class TargetRenderContext:
    request_identity: str
    compilation_identity: str
    target: TargetKey
    staging_directory: Path


@dataclass(frozen=True)
class TargetOrchestrationResult:
    target: TargetKey
    manifest_identity: str | None
    validation_identity: str | None
    validation_passed: bool
    error: str | None


@dataclass(frozen=True)
class OrchestrationResult:
    request_identity: str
    compilation_identity: str
    status: OrchestrationStatus
    targets: tuple[TargetOrchestrationResult, ...]
    publisher_result: PublishResult | None
    error: str | None
    identity: str

    @property
    def published(self) -> bool:
        return self.status is OrchestrationStatus.PUBLISHED


StagingRenderer = Callable[[object, TargetRenderContext], ArtifactSet]


class GenerationOrchestrator:
    """Fan one immutable compilation through every explicit request target."""

    def __init__(
        self,
        *,
        staging_renderer,
        validator,
        publisher,
        allow_stub_publication: bool = False,
    ):
        if not callable(staging_renderer):
            raise TypeError("staging_renderer must be callable")
        if not callable(getattr(validator, "validate", None)):
            raise TypeError("validator must expose validate(artifact_set, command)")
        if not callable(getattr(publisher, "publish", None)):
            raise TypeError("publisher must expose publish(validated_request)")
        self._render: StagingRenderer = staging_renderer
        self._validator = validator
        self._publisher = publisher
        self._allow_stub_publication = bool(allow_stub_publication)

    def execute(self, request: GenerationRequest, compilation) -> OrchestrationResult:
        self._gate_compilation(request, compilation)
        outcomes: list[TargetOrchestrationResult] = []
        validated: list[tuple[GenerationTarget, ArtifactSet, ValidationResult]] = []
        render_failed = False
        validation_failed = False

        for target in request.targets:
            context = TargetRenderContext(
                request_identity=request.identity,
                compilation_identity=request.compilation_identity,
                target=target.key,
                staging_directory=target.staging_directory,
            )
            try:
                artifact_set = self._render(compilation, context)
                self._gate_render_result(target, artifact_set)
            except Exception as error:
                render_failed = True
                outcomes.append(TargetOrchestrationResult(
                    target=target.key,
                    manifest_identity=None,
                    validation_identity=None,
                    validation_passed=False,
                    error=_error_text(error),
                ))
                continue

            try:
                validation = self._validator.validate(
                    artifact_set, target.validation_command
                )
                self._gate_validation_result(target, validation)
            except Exception as error:
                validation_failed = True
                outcomes.append(TargetOrchestrationResult(
                    target=target.key,
                    manifest_identity=artifact_set.manifest_identity,
                    validation_identity=None,
                    validation_passed=False,
                    error=_error_text(error),
                ))
                continue

            passed = bool(validation.passed)
            release_blockers = tuple(artifact_set.release_blockers)
            blocking_release_items = tuple(
                blocker
                for blocker in release_blockers
                if not (
                    self._allow_stub_publication
                    and blocker.startswith("STUB:")
                )
            )
            release_error = None
            if passed and blocking_release_items:
                passed = False
                release_error = (
                    "OR.RELEASE.STUB_BLOCKED: validated target contains "
                    f"{len(blocking_release_items)} release blocker(s); "
                    f"first={blocking_release_items[0]}"
                )
            validation_failed = validation_failed or not passed
            outcomes.append(TargetOrchestrationResult(
                target=target.key,
                manifest_identity=artifact_set.manifest_identity,
                validation_identity=str(validation.identity),
                validation_passed=passed,
                error=(
                    None if passed else release_error
                    or "OR.VALIDATION.BLOCKED: target validation failed"
                ),
            ))
            validated.append((target, artifact_set, validation))

        ordered_outcomes = tuple(sorted(outcomes, key=lambda item: _key_order(item.target)))
        if render_failed:
            return self._result(
                request,
                OrchestrationStatus.RENDER_FAILED,
                ordered_outcomes,
                publisher_result=None,
                error="one or more staging render callbacks failed",
            )
        if validation_failed or len(validated) != len(request.targets):
            return self._result(
                request,
                OrchestrationStatus.VALIDATION_FAILED,
                ordered_outcomes,
                publisher_result=None,
                error="one or more target validations blocked publication",
            )

        # The publisher request does not exist until every target has passed.
        publish_request = ValidatedGenerationRequest(
            request_id=request.identity,
            output_root=request.output_root,
            targets=tuple(
                ValidatedTarget(
                    target_id=target.key.identity,
                    staging_directory=target.staging_directory,
                    final_directory=target.final_directory,
                    validation_passed=True,
                )
                for target, _artifacts, _validation in validated
            ),
        )
        try:
            publisher_result = self._publisher.publish(publish_request)
        except Exception as error:
            return self._result(
                request,
                OrchestrationStatus.PUBLISH_FAILED,
                ordered_outcomes,
                publisher_result=None,
                error=_error_text(error),
            )
        if publisher_result.status is not PublishStatus.PUBLISHED:
            return self._result(
                request,
                OrchestrationStatus.PUBLISH_FAILED,
                ordered_outcomes,
                publisher_result=publisher_result,
                error=f"publisher returned {publisher_result.status.value}",
            )
        return self._result(
            request,
            OrchestrationStatus.PUBLISHED,
            ordered_outcomes,
            publisher_result=publisher_result,
            error=None,
        )

    @staticmethod
    def _gate_compilation(request: GenerationRequest, compilation) -> None:
        identity = str(getattr(compilation, "identity", ""))
        if identity != request.compilation_identity:
            raise OrchestrationError(
                "OR.COMPILATION.IDENTITY_MISMATCH",
                "request and supplied ProductCompilation identities differ",
            )
        if not bool(getattr(compilation, "is_valid", False)):
            raise OrchestrationError(
                "OR.COMPILATION.INVALID",
                "ProductCompilation contains blocking diagnostics",
            )
        cp_plans = getattr(compilation, "cp_plans", {})
        available = {str(cp).strip().casefold() for cp in cp_plans}
        missing = tuple(
            target.key.cp
            for target in request.targets
            if target.key.cp.strip().casefold() not in available
        )
        if missing:
            raise OrchestrationError(
                "OR.COMPILATION.CP_MISSING",
                f"ProductCompilation does not contain target CP {missing[0]}",
            )

    @staticmethod
    def _gate_render_result(
        target: GenerationTarget, artifact_set: ArtifactSet
    ) -> None:
        if not isinstance(artifact_set, ArtifactSet):
            raise OrchestrationError(
                "OR.RENDER.PUBLIC_ARTIFACT_SET_REQUIRED",
                "staging renderer must return render_plan.ArtifactSet",
            )
        if artifact_set.target != target.key:
            raise OrchestrationError(
                "OR.RENDER.TARGET_MISMATCH",
                "staging renderer returned artifacts for a different target",
            )
        if Path(artifact_set.root).resolve() != target.staging_directory:
            raise OrchestrationError(
                "OR.RENDER.STAGING_MISMATCH",
                "staging renderer returned a different staging root",
            )

    @staticmethod
    def _gate_validation_result(target: GenerationTarget, validation) -> None:
        if getattr(validation, "target", None) != target.key:
            raise OrchestrationError(
                "OR.VALIDATION.TARGET_MISMATCH",
                "validator returned evidence for a different target",
            )
        if not hasattr(validation, "passed") or not hasattr(validation, "identity"):
            raise OrchestrationError(
                "OR.VALIDATION.RESULT_INVALID",
                "validator result lacks passed or identity evidence",
            )

    @staticmethod
    def _result(
        request: GenerationRequest,
        status: OrchestrationStatus,
        targets: tuple[TargetOrchestrationResult, ...],
        *,
        publisher_result: PublishResult | None,
        error: str | None,
    ) -> OrchestrationResult:
        payload = {
            "request_identity": request.identity,
            "compilation_identity": request.compilation_identity,
            "status": status.value,
            "targets": [
                {
                    "target": item.target.identity,
                    "manifest_identity": item.manifest_identity,
                    "validation_identity": item.validation_identity,
                    "validation_passed": item.validation_passed,
                    "error": item.error,
                }
                for item in targets
            ],
            "publisher_status": (
                None if publisher_result is None else publisher_result.status.value
            ),
            "error": error,
        }
        return OrchestrationResult(
            request_identity=request.identity,
            compilation_identity=request.compilation_identity,
            status=status,
            targets=targets,
            publisher_result=publisher_result,
            error=error,
            identity=_hash_json(payload),
        )


def _target_order(target: GenerationTarget) -> tuple:
    return _key_order(target.key)


def _key_order(target: TargetKey) -> tuple:
    return (
        target.platform.casefold(),
        target.cp.casefold(),
        target.variant.casefold(),
        target.program_name.casefold(),
        target.identity,
    )


def _relative_to_root(root: Path, path: Path, target: TargetKey) -> str:
    try:
        relative = Path(path).resolve().relative_to(root)
    except ValueError as error:
        raise OrchestrationError(
            "OR.REQUEST.TARGET_OUT_OF_ROOT",
            f"target path escapes output root: {target.identity}",
        ) from error
    if not relative.parts:
        raise OrchestrationError(
            "OR.REQUEST.TARGET_OUT_OF_ROOT",
            f"target cannot replace output root: {target.identity}",
        )
    return relative.as_posix()


def _error_text(error: Exception) -> str:
    return f"{type(error).__name__}: {error}"


def _hash_json(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()
