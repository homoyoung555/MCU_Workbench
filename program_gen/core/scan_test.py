"""Typed facts and immutable converted artifacts for SCAN and MBIST FLOW rows."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from program_gen.render_plan import ResourceRequest
import re

import pandas as pd

from program_gen.flow_kinds import FlowOperation


class ScanTestCompileError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class ScanTestPlan:
    row: int
    cp: str
    item: str
    typed_kind: str
    power_profile: str
    provenance: object

    @property
    def excel_rows(self) -> tuple[int, ...]:
        return (self.row + 2,)

    @property
    def effective_recipe(self) -> tuple[str, ...]:
        return (self.typed_kind,)


@dataclass(frozen=True, slots=True)
class ScanArtifact:
    platform: str
    kind: str
    logical_name: str
    content: bytes

    def __post_init__(self) -> None:
        platform = str(self.platform).strip().casefold()
        kind = str(self.kind).strip().casefold()
        name = str(self.logical_name).strip()
        if platform not in {"chroma", "s100"}:
            raise ScanTestCompileError("SCAN.ARTIFACT.PLATFORM", repr(self.platform))
        if kind not in {"pattern", "timing", "code"}:
            raise ScanTestCompileError("SCAN.ARTIFACT.KIND", repr(self.kind))
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ScanTestCompileError("SCAN.ARTIFACT.LOGICAL_NAME", repr(name))
        object.__setattr__(self, "platform", platform)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "logical_name", name)
        object.__setattr__(self, "content", bytes(self.content))


@dataclass(frozen=True, slots=True)
class ScanArtifactBinding:
    cp: str
    item: str
    typed_kind: str
    configuration_fingerprint: str
    artifacts: tuple[ScanArtifact, ...]

    def __post_init__(self) -> None:
        cp = str(self.cp).strip().upper()
        item = str(self.item).strip()
        kind = str(self.typed_kind).strip().upper()
        fingerprint = str(self.configuration_fingerprint).strip()
        artifacts = tuple(self.artifacts)
        if not cp or not item or kind not in {"VERIFY_SCAN", "VERIFY_MBIST"}:
            raise ScanTestCompileError("SCAN.BINDING.IDENTITY", f"{cp}/{item}/{kind}")
        if not fingerprint:
            raise ScanTestCompileError("SCAN.BINDING.FINGERPRINT_MISSING", item)
        if not artifacts or any(not isinstance(value, ScanArtifact) for value in artifacts):
            raise ScanTestCompileError("SCAN.BINDING.ARTIFACTS_MISSING", item)
        keys = {(value.platform, value.kind, value.logical_name.casefold()) for value in artifacts}
        if len(keys) != len(artifacts):
            raise ScanTestCompileError("SCAN.BINDING.ARTIFACT_DUPLICATE", item)
        object.__setattr__(self, "cp", cp)
        object.__setattr__(self, "item", item)
        object.__setattr__(self, "typed_kind", kind)
        object.__setattr__(self, "configuration_fingerprint", fingerprint)
        object.__setattr__(self, "artifacts", artifacts)

    def artifact(self, platform: str, kind: str, logical_name: str) -> ScanArtifact:
        key = (str(platform).casefold(), str(kind).casefold(), str(logical_name).casefold())
        for artifact in self.artifacts:
            if (artifact.platform, artifact.kind, artifact.logical_name.casefold()) == key:
                return artifact
        raise ValueError(f"SCAN.BINDING.ARTIFACT_MISSING: {self.item}/{key[0]}/{key[1]}/{logical_name}")

    def artifacts_for(self, platform: str, kind: str) -> tuple[ScanArtifact, ...]:
        return tuple(value for value in self.artifacts if value.platform == str(platform).casefold() and value.kind == str(kind).casefold())


@dataclass(frozen=True, slots=True)
class ScanBindingSet:
    bindings: tuple[ScanArtifactBinding, ...]

    def __post_init__(self) -> None:
        bindings = tuple(self.bindings)
        keys = {(b.cp.casefold(), b.item.casefold(), b.typed_kind.casefold()) for b in bindings}
        if len(keys) != len(bindings):
            raise ScanTestCompileError("SCAN.BINDING.DUPLICATE", "duplicate FLOW association")
        object.__setattr__(self, "bindings", bindings)

    def require(self, plan: ScanTestPlan, target) -> ScanArtifactBinding:
        key = (plan.cp.casefold(), plan.item.casefold(), plan.typed_kind.casefold())
        binding = next((value for value in self.bindings if (value.cp.casefold(), value.item.casefold(), value.typed_kind.casefold()) == key), None)
        if binding is None:
            raise ValueError(f"SCAN.BINDING.MISSING: {plan.cp}/{plan.item}/{plan.typed_kind}")
        platform = str(target.platform).casefold()
        patterns = binding.artifacts_for(platform, "pattern")
        names = {artifact.logical_name.casefold() for artifact in patterns}
        if not names or any(not binding.artifacts_for(platform, kind) for kind in ("timing", "code")):
            raise ValueError(f"SCAN.BINDING.MISSING: {plan.cp}/{plan.item}/{platform}")
        for name in names:
            binding.artifact(platform, "timing", name)
            binding.artifact(platform, "code", name)
        return binding


class ScanArtifactProducer:
    """Overlay explicitly associated converted Patterns on a normal producer."""

    def __init__(self, bindings: ScanBindingSet, fallback, *, s100_timing_indices=None) -> None:
        self._bindings = bindings
        self._fallback = fallback
        self._s100_timing_indices = {} if s100_timing_indices is None else dict(s100_timing_indices)

    def for_target(self, facts):
        bind = getattr(self._fallback, "for_target", None)
        producer = ScanArtifactProducer(
            self._bindings, bind(facts) if callable(bind) else self._fallback,
            s100_timing_indices=self._s100_timing_indices,
        )
        producer._validate_target_patterns(facts)
        return producer

    def prepare_s100_timing(self, fragments):
        indices = {}
        prepared = []
        prepared_by_resource = {}
        next_index = 1
        for fragment in fragments:
            key = str(fragment.logical_identity)
            if key in indices:
                raise ValueError(f"SCAN.S100.TIMING_DUPLICATE: {key}")
            source_text = bytes(fragment.content).decode("utf-8", errors="strict")
            resource_key = (
                str(fragment.relative_path).casefold(), str(fragment.spec_identity)
            )
            previous = prepared_by_resource.get(resource_key)
            if previous is not None:
                previous_text, previous_indices = previous
                if previous_text != source_text:
                    raise ValueError(
                        f"SCAN.S100.TIMING_CONFLICT: {fragment.relative_path}; "
                        "同名关联必须使用同一冻结转换成品"
                    )
                indices[key] = previous_indices
                continue
            source_indices = tuple(int(value) for value in re.findall(r"(?m)^\s*@@AC_SET_(\d+)\s*$", source_text))
            end_indices = tuple(int(value) for value in re.findall(r"(?m)^\s*@@END_AC_SET_(\d+)\s*$", source_text))
            if (
                not source_indices
                or len(source_indices) != len(set(source_indices))
                or set(source_indices) != set(end_indices)
            ):
                raise ValueError(f"SCAN.S100.TIMING_INVALID: {key}")
            mapping = {source: index for index, source in enumerate(source_indices, start=next_index)}
            def replace(match):
                suffix, source = match.group(1), int(match.group(2))
                return f"@@{suffix or ''}AC_SET_{mapping[source]}"
            text = re.sub(r"@@(END_)?AC_SET_(\d+)(?!\d)", replace, source_text)
            indices[key] = mapping
            next_index += len(source_indices)
            prepared_by_resource[resource_key] = (source_text, mapping)
            prepared.append(ResourceRequest(
                fragment.logical_identity, fragment.relative_path, text.encode("utf-8"),
                fragment.spec_identity, fragment.source_identity, fragment.purpose,
            ))
        return ScanArtifactProducer(
            self._bindings, self._fallback, s100_timing_indices=indices
        ), tuple(prepared)

    def produce(self, requirement):
        parts = str(requirement.logical_identity).split(":", 5)
        if len(parts) != 6 or parts[0] != "scan":
            return self._fallback.produce(requirement)
        _prefix, cp, item, typed_kind, platform, logical_name = parts
        binding = next((value for value in self._bindings.bindings if (
            value.cp.casefold(), value.item.casefold(), value.typed_kind.casefold()
        ) == (cp.casefold(), item.casefold(), typed_kind.casefold())), None)
        if binding is None:
            raise ValueError(f"SCAN.BINDING.MISSING: {cp}/{item}/{typed_kind}")
        artifact = binding.artifact(platform, "pattern", logical_name)
        content = artifact.content
        indices = self._s100_timing_indices.get(str(requirement.logical_identity))
        if platform == "s100" and indices is not None:
            def replace(match):
                source = int(match.group(1))
                if source not in indices:
                    raise ValueError(f"SCAN.S100.TIMING_UNMAPPED: {requirement.logical_identity}:G2_{source}")
                return f"G2_{indices[source]}".encode("ascii")
            content = re.sub(rb"\bG2_(\d+)\b", replace, content)
        return ResourceRequest(
            requirement.logical_identity, requirement.relative_path, content,
            requirement.spec_identity,
            f"scan-binding:{binding.configuration_fingerprint}:{platform}:{logical_name}",
            requirement.purpose,
        )

    def write_region(self, pattern_name):
        return self._fallback.write_region(pattern_name)

    def timing_sets(self, requirements):
        scan_requirements = tuple(
            requirement for requirement in requirements
            if str(requirement.logical_identity).startswith("scan:")
        )
        seed_requirements = tuple(
            requirement for requirement in requirements
            if requirement not in scan_requirements
        )
        names = {
            name.decode("ascii")
            for requirement in scan_requirements
            for name in re.findall(
                rb"\bTIMING_SET\s+(G\d+_\d+)\s*;", self.produce(requirement).content
            )
        }
        if seed_requirements:
            names.update(self._fallback.timing_sets(seed_requirements))
        return tuple(sorted(name for name in names if not name.startswith("G2_")))

    def _validate_target_patterns(self, facts) -> None:
        platform = str(getattr(facts, "platform", "")).casefold()
        cp = str(getattr(facts, "cp", "")).casefold()
        known = {str(pin.name).casefold() for pin in getattr(facts, "pins", ())}
        known.add("trigpin")
        by_name = {}
        for binding in self._bindings.bindings:
            if binding.cp.casefold() != cp:
                continue
            for artifact in (value for value in binding.artifacts if value.platform == platform):
                key = (artifact.logical_name.casefold(), artifact.kind)
                previous = by_name.get(key)
                if previous is not None and previous.content != artifact.content:
                    code = (
                        "SCAN.BINDING.PATTERN_CONFLICT"
                        if artifact.kind == "pattern"
                        else "SCAN.BINDING.ARTIFACT_CONFLICT"
                    )
                    raise ValueError(f"{code}: {artifact.logical_name}/{artifact.kind}")
                by_name[key] = artifact
        for (_name, kind), artifact in by_name.items():
            if kind != "pattern":
                continue
            pins = _pattern_pins(platform, artifact.content)
            unknown = next((pin for pin in pins if pin.casefold() not in known), None)
            if unknown is not None:
                raise ValueError(
                    f"SCAN.PIN.UNDECLARED: {artifact.logical_name}:{unknown}; "
                    "请按目标CP适配"
                )


def compile_scan_test_plans(
    operations: tuple[FlowOperation, ...], flow: pd.DataFrame
) -> Mapping[int, ScanTestPlan]:
    plans: dict[int, ScanTestPlan] = {}
    for operation in operations:
        if operation.typed_kind not in {"VERIFY_SCAN", "VERIFY_MBIST"}:
            continue
        power = str(flow.iloc[operation.row].get("Vcc", "")).strip().upper()
        if not power:
            raise ScanTestCompileError("SCAN.POWER.MISSING", f"FLOW row {operation.row + 2}")
        plans[operation.row] = ScanTestPlan(
            operation.row, operation.cp, operation.item, operation.typed_kind,
            power, operation.provenance,
        )
    return MappingProxyType(plans)


def _pattern_pins(platform: str, content: bytes) -> tuple[str, ...]:
    text = content.decode("utf-8", errors="strict")
    if platform == "chroma":
        match = re.search(r"\bHEADER\s*\r?\n(.*?)(?:\r?\n){2}", text, re.S)
        if match is None:
            raise ValueError("SCAN.PIN.HEADER_MISSING")
        values = match.group(1).replace("\n", " ").replace(";", "").split(",")
    else:
        match = re.search(r"HEAD\[PIN_NAME\]:\s*\r?\n(.*?)\r?\nEND_HEAD;", text, re.S)
        if match is None:
            raise ValueError("SCAN.PIN.HEADER_MISSING")
        values = re.split(r"[,\r\n]", match.group(1))
    return tuple(value.strip().rstrip(";") for value in values if value.strip().rstrip(";"))


__all__ = [
    "ScanArtifact", "ScanArtifactBinding", "ScanArtifactProducer", "ScanBindingSet", "ScanTestCompileError",
    "ScanTestPlan", "compile_scan_test_plans",
]
