"""Pure contribution assembly and staging-only artifact materialization.

This module deliberately knows neither platform output directories nor legacy
generator globals.  Render adapters contribute bytes and logical identities;
the assembler closes that graph into a deterministic manifest before the
materializer is allowed to touch an explicitly prepared staging directory.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from typing import ClassVar, Iterable, Mapping


MANIFEST_SCHEMA = "v13.render-manifest/1"
MANIFEST_FILENAME = ".render-manifest.json"


class RenderPlanError(ValueError):
    """A contribution graph or staging request violates the render contract."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def _as_bytes(content: bytes | bytearray | str) -> bytes:
    if isinstance(content, bytes):
        return content
    if isinstance(content, bytearray):
        return bytes(content)
    if isinstance(content, str):
        return content.encode("utf-8")
    raise TypeError("artifact content must be bytes, bytearray, or str")


@dataclass(frozen=True)
class TargetKey:
    platform: str
    cp: str
    variant: str
    program_name: str

    def __post_init__(self) -> None:
        for field_name in ("platform", "cp", "variant", "program_name"):
            if not str(getattr(self, field_name)).strip():
                raise RenderPlanError(
                    "RP.TARGET.INVALID", f"target {field_name} cannot be empty"
                )
        _safe_relative_path(self.program_name)

    @property
    def identity(self) -> str:
        return ":".join((self.platform, self.cp, self.variant, self.program_name))


@dataclass(frozen=True)
class SectionFragment:
    artifact_path: str
    section: str
    identity: str
    content: bytes | str
    order: int = 0
    depends_on: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "content", _as_bytes(self.content))
        object.__setattr__(self, "depends_on", tuple(self.depends_on))


@dataclass(frozen=True)
class ResourceRequest:
    logical_identity: str
    relative_path: str
    content: bytes | str
    spec_identity: str = ""
    source_identity: str = ""
    purpose: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "content", _as_bytes(self.content))


@dataclass(frozen=True)
class ResourceRequirement:
    logical_identity: str
    relative_path: str
    spec_identity: str
    purpose: str = ""


@dataclass(frozen=True)
class RenderSymbolRef:
    namespace: str
    semantic_key: str

    @property
    def identity(self) -> str:
        return f"{self.namespace}.{self.semantic_key}"


@dataclass(frozen=True)
class SymbolProvision:
    ref: RenderSymbolRef
    rendered_name: str
    value_type: str
    bit_width: int | None
    scope: str


@dataclass(frozen=True)
class SymbolRequirement:
    ref: RenderSymbolRef
    value_type: str
    bit_width: int | None
    scope: str


@dataclass(frozen=True)
class TestDefinitionContribution:
    __test__: ClassVar[bool] = False
    identity: str
    typed_kind: str
    owner_id: str


@dataclass(frozen=True)
class ScheduleEntryContribution:
    identity: str
    definition_identity: str
    ordinal: int
    enabled: bool


@dataclass(frozen=True)
class LifecycleAction:
    """One platform-rendered action owned by a typed kind lifecycle hook."""

    hook: str
    identity: str
    content: str
    order: int = 0

    def __post_init__(self) -> None:
        hook = str(self.hook).strip().upper()
        identity = str(self.identity).strip()
        content = str(self.content)
        if not hook:
            raise RenderPlanError(
                "RP.LIFECYCLE.HOOK_MISSING", "lifecycle hook cannot be empty"
            )
        if not identity:
            raise RenderPlanError(
                "RP.LIFECYCLE.IDENTITY_MISSING", "lifecycle action cannot be unnamed"
            )
        if not content:
            raise RenderPlanError(
                "RP.LIFECYCLE.CONTENT_MISSING",
                f"lifecycle action {identity!r} cannot be empty",
            )
        object.__setattr__(self, "hook", hook)
        object.__setattr__(self, "identity", identity)
        object.__setattr__(self, "content", content)


@dataclass(frozen=True)
class ProgramContribution:
    identity: str
    target: TargetKey
    sections: tuple[SectionFragment, ...] = ()
    resources: tuple[ResourceRequest, ...] = ()
    timing_fragments: tuple[ResourceRequest, ...] = ()
    resource_requires: tuple[ResourceRequirement, ...] = ()
    provides: tuple[SymbolProvision, ...] = ()
    requires: tuple[SymbolRequirement, ...] = ()
    definitions: tuple[TestDefinitionContribution, ...] = ()
    schedule_entries: tuple[ScheduleEntryContribution, ...] = ()
    lifecycle_actions: tuple[LifecycleAction, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "sections", tuple(self.sections))
        object.__setattr__(self, "resources", tuple(self.resources))
        object.__setattr__(self, "timing_fragments", tuple(self.timing_fragments))
        object.__setattr__(self, "resource_requires", tuple(self.resource_requires))
        object.__setattr__(self, "provides", tuple(self.provides))
        object.__setattr__(self, "requires", tuple(self.requires))
        object.__setattr__(self, "definitions", tuple(self.definitions))
        object.__setattr__(self, "schedule_entries", tuple(self.schedule_entries))
        object.__setattr__(self, "lifecycle_actions", tuple(self.lifecycle_actions))


@dataclass(frozen=True)
class ArtifactPlan:
    relative_path: str
    content: bytes | str
    kind: str
    owners: tuple[str, ...]
    release_blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "content", _as_bytes(self.content))
        object.__setattr__(self, "owners", tuple(self.owners))
        object.__setattr__(self, "release_blockers", tuple(self.release_blockers))

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest().upper()

    @property
    def size(self) -> int:
        return len(self.content)


@dataclass(frozen=True)
class RenderPlan:
    target: TargetKey
    target_relative_root: str
    artifacts: tuple[ArtifactPlan, ...]
    manifest_json: str
    identity: str

    @classmethod
    def from_artifacts(
        cls, target: TargetKey, artifacts: Iterable[ArtifactPlan]
    ) -> "RenderPlan":
        frozen = tuple(sorted(
            tuple(artifacts),
            key=lambda item: (
                str(item.relative_path).replace("\\", "/").casefold(),
                str(item.relative_path).replace("\\", "/"),
                item.kind,
                item.sha256,
                item.owners,
                item.release_blockers,
            ),
        ))
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "target": {
                "platform": target.platform,
                "cp": target.cp,
                "variant": target.variant,
                "program_name": target.program_name,
            },
            "artifacts": [
                {
                    "path": item.relative_path,
                    "kind": item.kind,
                    "size": item.size,
                    "sha256": item.sha256,
                    "owners": list(item.owners),
                    **({
                        "release_blockers": list(item.release_blockers),
                    } if item.release_blockers else {}),
                }
                for item in frozen
            ],
        }
        manifest_json = json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        identity = hashlib.sha256(manifest_json.encode("utf-8")).hexdigest().upper()
        return cls(target, target.program_name, frozen, manifest_json, identity)

    def artifact(self, relative_path: str) -> ArtifactPlan:
        for artifact in self.artifacts:
            if artifact.relative_path == relative_path:
                return artifact
        raise KeyError(relative_path)

    @property
    def release_blockers(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(
            blocker
            for artifact in self.artifacts
            for blocker in artifact.release_blockers
        ))


@dataclass(frozen=True)
class MaterializedArtifact:
    relative_path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class ArtifactSet:
    target: TargetKey
    root: Path
    artifacts: tuple[MaterializedArtifact, ...]
    manifest_identity: str
    release_blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "release_blockers", tuple(self.release_blockers))


class ProgramAssembler:
    """Merge structured contributions into a closed, deterministic render plan."""

    def __init__(
        self,
        *,
        section_order: tuple[str, ...] = (),
        required_skeleton: tuple[SectionFragment, ...] = (),
    ):
        self._section_rank = {
            name.casefold(): index for index, name in enumerate(section_order)
        }
        self._required_skeleton = tuple(required_skeleton)

    def assemble(
        self, target: TargetKey, contributions: Iterable[ProgramContribution]
    ) -> RenderPlan:
        contributions = tuple(contributions)
        mismatched = tuple(
            item.identity for item in contributions if item.target != target
        )
        if mismatched:
            raise RenderPlanError(
                "RP.TARGET.MISMATCH",
                f"contributions belong to a different target: {mismatched[0]!r}",
            )
        if self._required_skeleton:
            contributions += (ProgramContribution(
                identity="platform:required-skeleton",
                target=target,
                sections=self._required_skeleton,
            ),)
        self._validate_contribution_identities(contributions)
        self._close_test_plan(contributions)
        self._close_symbols(contributions)
        fragments = self._close_fragments(contributions)
        resources = self._close_resources(contributions)

        artifacts: list[ArtifactPlan] = []
        by_path: dict[str, list[SectionFragment]] = {}
        for fragment in fragments:
            path = _safe_relative_path(fragment.artifact_path)
            by_path.setdefault(path, []).append(fragment)
        for path, selected in by_path.items():
            ordered = self._order_fragments(tuple(selected), fragments)
            artifacts.append(ArtifactPlan(
                relative_path=path,
                content=b"".join(item.content for item in ordered),
                kind="PROGRAM",
                owners=tuple(item.identity for item in ordered),
            ))
        for resource in resources:
            artifacts.append(ArtifactPlan(
                relative_path=_safe_relative_path(resource.relative_path),
                content=resource.content,
                kind="RESOURCE",
                owners=(resource.logical_identity,),
                release_blockers=_resource_release_blockers(resource),
            ))

        return RenderPlan.from_artifacts(
            target, _coalesce_artifacts(tuple(artifacts))
        )

    @staticmethod
    def _close_test_plan(
        contributions: tuple[ProgramContribution, ...]
    ) -> None:
        definitions: dict[str, TestDefinitionContribution] = {}
        for contribution in contributions:
            for definition in contribution.definitions:
                if not definition.identity.strip():
                    raise RenderPlanError(
                        "RP.DEFINITION.IDENTITY_MISSING",
                        f"contribution {contribution.identity!r} has an unnamed definition",
                    )
                key = definition.identity.casefold()
                previous = definitions.get(key)
                if previous is not None:
                    if previous == definition:
                        raise RenderPlanError(
                            "RP.DEFINITION.DUPLICATE",
                            f"definition {definition.identity!r} has more than one owner",
                        )
                    raise RenderPlanError(
                        "RP.DEFINITION.CONFLICT",
                        f"definition {definition.identity!r} has conflicting declarations",
                    )
                definitions[key] = definition
        schedules: dict[str, ScheduleEntryContribution] = {}
        schedule_ordinals: dict[int, ScheduleEntryContribution] = {}
        for contribution in contributions:
            for entry in contribution.schedule_entries:
                if not entry.identity.strip():
                    raise RenderPlanError(
                        "RP.SCHEDULE.IDENTITY_MISSING",
                        f"contribution {contribution.identity!r} has an unnamed schedule",
                    )
                key = entry.identity.casefold()
                previous = schedules.get(key)
                if previous is not None and previous != entry:
                    raise RenderPlanError(
                        "RP.SCHEDULE.CONFLICT",
                        f"schedule {entry.identity!r} has conflicting declarations",
                    )
                if entry.definition_identity.casefold() not in definitions:
                    raise RenderPlanError(
                        "RP.SCHEDULE.DEFINITION_MISSING",
                        f"schedule {entry.identity!r} references unknown "
                        f"definition {entry.definition_identity!r}",
                    )
                previous_ordinal = schedule_ordinals.get(entry.ordinal)
                if (
                    previous_ordinal is not None
                    and previous_ordinal.identity.casefold() != entry.identity.casefold()
                ):
                    raise RenderPlanError(
                        "RP.SCHEDULE.ORDINAL_CONFLICT",
                        f"schedule ordinal {entry.ordinal!r} is claimed by both "
                        f"{previous_ordinal.identity!r} and {entry.identity!r}",
                    )
                schedules[key] = entry
                schedule_ordinals[entry.ordinal] = entry

    @staticmethod
    def _close_symbols(
        contributions: tuple[ProgramContribution, ...]
    ) -> Mapping[str, SymbolProvision]:
        provisions: dict[str, SymbolProvision] = {}
        rendered_names: dict[str, RenderSymbolRef] = {}
        for contribution in contributions:
            for provision in contribution.provides:
                key = provision.ref.identity.casefold()
                previous = provisions.get(key)
                if previous is not None and previous != provision:
                    raise RenderPlanError(
                        "RP.SYMBOL.CONFLICT",
                        f"symbol {provision.ref.identity!r} has conflicting definitions",
                    )
                rendered_key = provision.rendered_name.casefold()
                previous_ref = rendered_names.get(rendered_key)
                if previous_ref is not None and previous_ref != provision.ref:
                    raise RenderPlanError(
                        "RP.SYMBOL.RENDERED_NAME_CONFLICT",
                        f"rendered symbol {provision.rendered_name!r} is not unique",
                    )
                provisions[key] = provision
                rendered_names[rendered_key] = provision.ref
        for contribution in contributions:
            for requirement in contribution.requires:
                provision = provisions.get(requirement.ref.identity.casefold())
                if provision is None:
                    raise RenderPlanError(
                        "RP.SYMBOL.MISSING",
                        f"symbol {requirement.ref.identity!r} has no provider",
                    )
                expected = (
                    requirement.value_type.casefold(),
                    requirement.bit_width,
                    requirement.scope.casefold(),
                )
                actual = (
                    provision.value_type.casefold(),
                    provision.bit_width,
                    provision.scope.casefold(),
                )
                if expected != actual:
                    raise RenderPlanError(
                        "RP.SYMBOL.CONTRACT_MISMATCH",
                        f"symbol {requirement.ref.identity!r} contract differs from its provider",
                    )
        return provisions

    @staticmethod
    def _validate_contribution_identities(
        contributions: tuple[ProgramContribution, ...]
    ) -> None:
        seen: dict[str, ProgramContribution] = {}
        for contribution in contributions:
            if not contribution.identity:
                raise RenderPlanError(
                    "RP.CONTRIBUTION.IDENTITY_MISSING",
                    "every contribution requires a stable identity",
                )
            previous = seen.get(contribution.identity.casefold())
            if previous is not None and previous != contribution:
                raise RenderPlanError(
                    "RP.CONTRIBUTION.CONFLICT",
                    f"contribution {contribution.identity!r} has conflicting payloads",
                )
            seen[contribution.identity.casefold()] = contribution

    @staticmethod
    def _close_fragments(
        contributions: tuple[ProgramContribution, ...]
    ) -> tuple[SectionFragment, ...]:
        by_identity: dict[str, SectionFragment] = {}
        for contribution in contributions:
            for fragment in contribution.sections:
                if not fragment.identity:
                    raise RenderPlanError(
                        "RP.FRAGMENT.IDENTITY_MISSING",
                        f"contribution {contribution.identity!r} has an unnamed fragment",
                    )
                key = fragment.identity.casefold()
                previous = by_identity.get(key)
                if previous is not None and previous != fragment:
                    raise RenderPlanError(
                        "RP.FRAGMENT.CONFLICT",
                        f"fragment {fragment.identity!r} has conflicting payloads",
                    )
                by_identity[key] = fragment
        for fragment in by_identity.values():
            for dependency in fragment.depends_on:
                if dependency.casefold() not in by_identity:
                    raise RenderPlanError(
                        "RP.FRAGMENT.DEPENDENCY_MISSING",
                        f"fragment {fragment.identity!r} depends on unknown {dependency!r}",
                    )
        return tuple(by_identity.values())

    @staticmethod
    def _close_resources(
        contributions: tuple[ProgramContribution, ...]
    ) -> tuple[ResourceRequest, ...]:
        by_identity: dict[str, ResourceRequest] = {}
        for contribution in contributions:
            for resource in contribution.resources:
                if not resource.logical_identity:
                    raise RenderPlanError(
                        "RP.RESOURCE.IDENTITY_MISSING",
                        f"contribution {contribution.identity!r} has an unnamed resource",
                    )
                if not resource.spec_identity or not resource.source_identity:
                    raise RenderPlanError(
                        "RP.RESOURCE.PROVENANCE_MISSING",
                        f"resource {resource.logical_identity!r} requires spec and source identity",
                    )
                key = resource.logical_identity.casefold()
                previous = by_identity.get(key)
                if previous is not None and _resource_contract(previous) != _resource_contract(resource):
                    raise RenderPlanError(
                        "RP.RESOURCE.CONFLICT",
                        f"resource {resource.logical_identity!r} has conflicting requests",
                    )
                by_identity[key] = resource
        for contribution in contributions:
            for requirement in contribution.resource_requires:
                provider = by_identity.get(requirement.logical_identity.casefold())
                if provider is None:
                    raise RenderPlanError(
                        "RP.RESOURCE.MISSING",
                        f"resource {requirement.logical_identity!r} has no provider",
                    )
                expected = (
                    _safe_relative_path(requirement.relative_path),
                    requirement.spec_identity,
                )
                actual = (
                    _safe_relative_path(provider.relative_path),
                    provider.spec_identity,
                )
                if expected != actual:
                    raise RenderPlanError(
                        "RP.RESOURCE.CONTRACT_MISMATCH",
                        f"resource {requirement.logical_identity!r} contract differs "
                        "from its provider",
                    )
        return tuple(by_identity.values())

    def _order_fragments(
        self,
        selected: tuple[SectionFragment, ...],
        all_fragments: tuple[SectionFragment, ...],
    ) -> tuple[SectionFragment, ...]:
        selected_ids = {item.identity.casefold() for item in selected}
        by_id = {item.identity.casefold(): item for item in all_fragments}
        emitted: set[str] = set()
        visiting: set[str] = set()
        result: list[SectionFragment] = []

        def priority(item: SectionFragment) -> tuple:
            return (
                self._section_rank.get(item.section.casefold(), len(self._section_rank)),
                item.section.casefold(),
                item.order,
                item.identity.casefold(),
                item.identity,
            )

        def visit(item: SectionFragment) -> None:
            key = item.identity.casefold()
            if key in emitted:
                return
            if key in visiting:
                raise RenderPlanError(
                    "RP.FRAGMENT.DEPENDENCY_CYCLE",
                    f"fragment dependency cycle includes {item.identity!r}",
                )
            visiting.add(key)
            for dependency in sorted(item.depends_on, key=str.casefold):
                dependency_key = dependency.casefold()
                if dependency_key in selected_ids:
                    visit(by_id[dependency_key])
            visiting.remove(key)
            emitted.add(key)
            result.append(item)

        for item in sorted(selected, key=priority):
            visit(item)
        return tuple(result)


class ArtifactMaterializer:
    """Write a validated render plan into an existing empty staging directory."""

    def __init__(self, *, replace=os.replace):
        self._replace = replace

    def materialize(self, plan: RenderPlan, staging: str | Path) -> ArtifactSet:
        staging_path = Path(staging)
        if not staging_path.exists():
            raise RenderPlanError(
                "RP.STAGING.MISSING",
                f"staging directory does not exist: {staging_path}",
            )
        if not staging_path.is_dir():
            raise RenderPlanError(
                "RP.STAGING.NOT_DIRECTORY", f"staging path is not a directory: {staging_path}"
            )
        if staging_path.is_symlink():
            raise RenderPlanError(
                "RP.STAGING.SYMLINK", f"staging directory cannot be a symlink: {staging_path}"
            )
        if any(staging_path.iterdir()):
            raise RenderPlanError(
                "RP.STAGING.NOT_EMPTY", f"staging directory is not empty: {staging_path}"
            )

        # Complete validation happens before the first mkdir/write.
        artifacts = _coalesce_artifacts(plan.artifacts)
        for artifact in artifacts:
            if artifact.relative_path == MANIFEST_FILENAME:
                raise RenderPlanError(
                    "RP.PATH.RESERVED", f"{MANIFEST_FILENAME!r} is reserved for the render manifest"
                )

        materialized = []
        for ordinal, artifact in enumerate(artifacts):
            target = staging_path.joinpath(*artifact.relative_path.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.tmp-{ordinal:06d}")
            with temporary.open("xb") as stream:
                stream.write(artifact.content)
                stream.flush()
                os.fsync(stream.fileno())
            written_hash = hashlib.sha256(temporary.read_bytes()).hexdigest().upper()
            if written_hash != artifact.sha256:
                raise RenderPlanError(
                    "RP.MATERIALIZE.HASH_MISMATCH",
                    f"artifact {artifact.relative_path!r} failed write verification",
                )
            self._replace(temporary, target)
            materialized.append(MaterializedArtifact(
                artifact.relative_path, written_hash, artifact.size
            ))
        manifest_target = staging_path / MANIFEST_FILENAME
        manifest_temporary = staging_path / f"{MANIFEST_FILENAME}.tmp"
        manifest_temporary.write_text(plan.manifest_json, encoding="utf-8", newline="")
        self._replace(manifest_temporary, manifest_target)
        return ArtifactSet(
            target=plan.target,
            root=staging_path.resolve(),
            artifacts=tuple(materialized),
            manifest_identity=plan.identity,
            release_blockers=plan.release_blockers,
        )


def _safe_relative_path(value: str) -> str:
    raw = str(value)
    if not raw or not raw.strip():
        raise RenderPlanError("RP.PATH.EMPTY", "artifact path cannot be empty")
    slash = raw.replace("\\", "/")
    if (
        slash.startswith("/")
        or slash.startswith("//")
        or re.match(r"^[A-Za-z]:", slash)
    ):
        raise RenderPlanError("RP.PATH.ABSOLUTE", f"absolute path is forbidden: {raw!r}")
    parts = slash.split("/")
    if any(part == ".." for part in parts):
        raise RenderPlanError("RP.PATH.TRAVERSAL", f"parent traversal is forbidden: {raw!r}")
    if any(part in ("", ".") for part in parts):
        raise RenderPlanError("RP.PATH.INVALID", f"path is not canonical: {raw!r}")
    return "/".join(parts)


def _coalesce_artifacts(
    artifacts: tuple[ArtifactPlan, ...]
) -> tuple[ArtifactPlan, ...]:
    by_exact_path: dict[str, ArtifactPlan] = {}
    windows_paths: dict[str, str] = {}
    for artifact in artifacts:
        path = _safe_relative_path(artifact.relative_path)
        canonical = ArtifactPlan(
            path,
            artifact.content,
            artifact.kind,
            artifact.owners,
            artifact.release_blockers,
        )
        windows_key = path.casefold()
        previous_spelling = windows_paths.get(windows_key)
        if previous_spelling is not None and previous_spelling != path:
            raise RenderPlanError(
                "RP.PATH.WINDOWS_COLLISION",
                f"paths {previous_spelling!r} and {path!r} collide on Windows",
            )
        windows_paths[windows_key] = path
        previous = by_exact_path.get(path)
        if previous is None:
            by_exact_path[path] = canonical
            continue
        if previous.content != canonical.content or previous.kind != canonical.kind:
            raise RenderPlanError(
                "RP.ARTIFACT.CONTENT_CONFLICT",
                f"artifact {path!r} has conflicting content or kind",
            )
        owners = tuple(dict.fromkeys(previous.owners + canonical.owners))
        blockers = tuple(dict.fromkeys(
            previous.release_blockers + canonical.release_blockers
        ))
        by_exact_path[path] = ArtifactPlan(
            path, previous.content, previous.kind, owners, blockers
        )
    return tuple(by_exact_path.values())


def _resource_contract(resource: ResourceRequest) -> tuple:
    """Fields that establish resource identity; consumer prose is not one."""
    return (
        _safe_relative_path(resource.relative_path),
        resource.content,
        resource.spec_identity,
        resource.source_identity,
    )


def _resource_release_blockers(resource: ResourceRequest) -> tuple[str, ...]:
    source = str(resource.source_identity).upper()
    purpose = str(resource.purpose).strip().upper()
    if ":STUB:" not in source and not purpose.startswith("STUB "):
        return ()
    return (
        f"STUB:{resource.logical_identity}:{_safe_relative_path(resource.relative_path)}",
    )
