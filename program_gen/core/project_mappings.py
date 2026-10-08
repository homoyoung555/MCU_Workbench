"""Workbook-carried physical storage bindings for TRIM and VERIFY results."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import json
from typing import Iterable, Mapping
from zipfile import BadZipFile, ZipFile

from program_gen.core.logical_item import logical_item_key


MAPPINGS_PART = "mcu/mappings.json"


class ProjectMappingsError(ValueError):
    """The workbook mapping part is malformed or conflicts with typed facts."""


@dataclass(frozen=True, slots=True)
class StorageTarget:
    page: str
    register: str
    field: str


@dataclass(frozen=True, slots=True)
class StorageMapping:
    """One logical producer and its intentional physical target set.

    An empty target tuple suppresses legacy name-derived mapping: it is the
    persisted representation of an explicit unlink action.
    """

    item: str
    targets: tuple[StorageTarget, ...]


@dataclass(frozen=True, slots=True)
class TrimStorageMapping:
    """v1/v2 compatibility shape; v3 APIs return :class:`StorageMapping`."""

    item: str
    page: str
    register: str
    field: str


def parse_storage_mappings(records: Iterable[Mapping[str, object]], name: str) -> tuple[StorageMapping, ...]:
    if not isinstance(records, (list, tuple)):
        raise ProjectMappingsError(f"{name} 必须是对象数组")
    if len(records) > 1000:
        raise ProjectMappingsError(f"{name} 最多允许 1000 条记录")
    parsed, seen = [], set()
    for index, record in enumerate(records):
        if not isinstance(record, Mapping) or set(record) != {"item", "targets"}:
            raise ProjectMappingsError(f"{name}[{index}] 只能包含 item, targets")
        item = _string(record.get("item"), f"{name}[{index}].item")
        key = logical_item_key(item)
        if key in seen:
            raise ProjectMappingsError(f"{name} 的逻辑项重复：{item}")
        seen.add(key)
        raw_targets = record.get("targets")
        if not isinstance(raw_targets, list):
            raise ProjectMappingsError(f"{name}[{index}].targets 必须是数组")
        targets, target_seen = [], set()
        for target_index, target in enumerate(raw_targets):
            if not isinstance(target, Mapping) or set(target) != {"page", "register", "field"}:
                raise ProjectMappingsError(f"{name}[{index}].targets[{target_index}] 只能包含 field, page, register")
            value = StorageTarget(*(
                _string(target.get(part), f"{name}[{index}].targets[{target_index}].{part}")
                for part in ("page", "register", "field")
            ))
            target_key = tuple(getattr(value, part).casefold() for part in ("page", "register", "field"))
            if target_key in target_seen:
                raise ProjectMappingsError(f"{name}[{index}] 的物理目标重复")
            target_seen.add(target_key)
            targets.append(value)
        parsed.append(StorageMapping(item, tuple(targets)))
    return tuple(parsed)


def parse_trim_storage_mappings(records: Iterable[Mapping[str, object]]) -> tuple[TrimStorageMapping, ...]:
    """Parse the former v2 flat shape for compatibility-only callers."""
    return _parse_v2(records, "trimStorage")


def read_storage_mappings(raw: bytes) -> tuple[StorageMapping, ...]:
    return _read_document(raw)[0]


def read_verify_storage_mappings(raw: bytes) -> tuple[StorageMapping, ...]:
    return _read_document(raw)[1]


def _read_document(raw: bytes) -> tuple[tuple[StorageMapping, ...], tuple[StorageMapping, ...]]:
    try:
        with ZipFile(BytesIO(raw)) as archive:
            entries = tuple(entry for entry in archive.infolist() if entry.filename == MAPPINGS_PART)
            if not entries:
                return (), ()
            if len(entries) != 1:
                raise ProjectMappingsError(f"{MAPPINGS_PART} 不能重复出现")
            if entries[0].file_size > 1024 * 1024:
                raise ProjectMappingsError(f"{MAPPINGS_PART} 不能超过 1 MiB")
            encoded = archive.read(entries[0])
    except BadZipFile as exc:
        raise ProjectMappingsError("工作簿不是可读取的 OOXML ZIP") from exc
    try:
        document = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectMappingsError(f"{MAPPINGS_PART} 不是有效 UTF-8 JSON") from exc
    if not isinstance(document, Mapping) or type(document.get("version")) is not int:
        raise ProjectMappingsError(f"{MAPPINGS_PART} 需要受支持的 version")
    version = document["version"]
    if version == 3 and set(document) == {"version", "trimStorage", "verifyStorage"}:
        return parse_storage_mappings(document["trimStorage"], "trimStorage"), parse_storage_mappings(document["verifyStorage"], "verifyStorage")
    if version == 2 and set(document) == {"version", "trimStorage"}:
        return _group_flat(_parse_v2(document["trimStorage"], "trimStorage")), ()
    if version == 1 and set(document) == {"version", "trimStorage"}:
        return _group_flat(_migrate_v1_trim_storage_mappings(document["trimStorage"])), ()
    raise ProjectMappingsError(f"{MAPPINGS_PART} 需要 version=1、version=2 或 version=3")


def _string(value: object, context: str) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > 256
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ProjectMappingsError(f"{context} 必须是非空字符串")
    return value.strip()


def _parse_v2(records, name: str) -> tuple[TrimStorageMapping, ...]:
    if not isinstance(records, list):
        raise ProjectMappingsError(f"{name} 必须是对象数组")
    mappings = []
    for index, record in enumerate(records):
        if not isinstance(record, Mapping) or set(record) != {"item", "page", "register", "field"}:
            raise ProjectMappingsError(f"{name}[{index}] 只能包含 field, item, page, register")
        mappings.append(TrimStorageMapping(*(
            _string(record.get(part), f"{name}[{index}].{part}")
            for part in ("item", "page", "register", "field")
        )))
    return tuple(mappings)


def _migrate_v1_trim_storage_mappings(records) -> tuple[TrimStorageMapping, ...]:
    if not isinstance(records, list):
        raise ProjectMappingsError("mcu/mappings.json.trimStorage 必须是数组")
    per_item, order = {}, []
    for index, record in enumerate(records):
        if not isinstance(record, Mapping) or set(record) != {"cp", "item", "page", "register", "field"}:
            raise ProjectMappingsError(f"trimStorage[{index}] 只能包含 cp, field, item, page, register")
        values = {part: _string(record.get(part), f"trimStorage[{index}].{part}")
                  for part in ("cp", "item", "page", "register", "field")}
        key = logical_item_key(values["item"])
        if key not in per_item:
            per_item[key], order = {}, order + [key]
        per_item[key].setdefault(values["cp"].casefold(), []).append(values)
    promoted = []
    for key in order:
        target_sets = {frozenset((entry["page"].casefold(), entry["register"].casefold(), entry["field"].casefold()) for entry in entries) for entries in per_item[key].values()}
        if len(target_sets) != 1:
            raise ProjectMappingsError(f"旧 trimStorage 的 {key} 在不同 CP 选择了不同目标，无法提升为全局映射")
        for entry in next(iter(per_item[key].values())):
            mapping = TrimStorageMapping(entry["item"], entry["page"], entry["register"], entry["field"])
            if mapping not in promoted:
                promoted.append(mapping)
    return tuple(promoted)


def _group_flat(records: Iterable[TrimStorageMapping]) -> tuple[StorageMapping, ...]:
    grouped, order = {}, []
    for record in records:
        key = logical_item_key(record.item)
        if key not in grouped:
            grouped[key], order = [record.item], order + [key]
        grouped[key].append(StorageTarget(record.page, record.register, record.field))
    return tuple(StorageMapping(grouped[key][0], tuple(grouped[key][1:])) for key in order)


def normalize_storage_mappings(records: Iterable[object]) -> tuple[StorageMapping, ...]:
    records = tuple(records)
    if not records or isinstance(records[0], StorageMapping):
        return tuple(records)
    if isinstance(records[0], TrimStorageMapping):
        return _group_flat(records)
    raise TypeError("storage mappings 必须是 StorageMapping 或 TrimStorageMapping")


def validate_storage_mapping_records(kind: str, records, catalog, sources) -> tuple[StorageMapping, ...]:
    """Fast renderer-free validation for one draft click.

    ``sources`` supplies already compiled producers with ``item``, ``cp`` and
    ``required_bits`` attributes. Full compilation additionally validates FLOW
    legacy ownership and explicit COMMIT assignments.
    """
    kind = str(kind).strip().casefold()
    if kind not in ("trim", "verify"):
        raise ProjectMappingsError("存储映射类型只能是 trim 或 verify")
    records = normalize_storage_mappings(records)
    source_by_item = {}
    for source in sources:
        source_by_item.setdefault(logical_item_key(source.item), []).append(source)
    occupied = {}
    for record in records:
        matching = source_by_item.get(logical_item_key(record.item), ())
        if not matching:
            raise ProjectMappingsError(f"{kind.upper()} 存储映射 {record.item} 没有可持久化的已编译来源")
        seen_targets = set()
        for target in record.targets:
            target_key = tuple(getattr(target, part).casefold() for part in ("page", "register", "field"))
            if target_key in seen_targets:
                raise ProjectMappingsError(f"{kind.upper()} 存储映射 {record.item} 的物理目标重复")
            seen_targets.add(target_key)
            try:
                field = catalog.resolve_storage_field(target.page, target.register, target.field)
            except Exception as exc:
                raise ProjectMappingsError(f"{kind.upper()} 存储映射 {record.item} 的 page/register/field 不一致") from exc
            required = max(int(source.required_bits) for source in matching)
            if field.width < required:
                raise ProjectMappingsError(f"{kind.upper()} 存储映射 {record.item} 的字段 {field.name} 宽度 {field.width} 小于所需位宽 {required}")
            unsupported = sorted({str(source.cp).upper() for source in matching if not field.register_layout.applies_to(source.cp)})
            if unsupported:
                raise ProjectMappingsError(f"{kind.upper()} 存储映射 {record.item} 的字段 {field.name} 不适用于 {'、'.join(unsupported)}")
            key, interval = (field.page.casefold(), field.register.casefold()), (field.lsb, field.lsb + field.width)
            for old_interval, owner in occupied.get(key, ()):
                if owner != logical_item_key(record.item) and max(interval[0], old_interval[0]) < min(interval[1], old_interval[1]):
                    raise ProjectMappingsError(f"{kind.upper()} 存储字段重叠：{record.item} 与 {owner}")
            occupied.setdefault(key, []).append((interval, logical_item_key(record.item)))
    return records


def verify_storage_sources(flow, exports_by_row) -> tuple[object, ...]:
    """Persistable VERIFY measurement producers from compiled EXPORT facts."""
    from types import SimpleNamespace

    result = []
    for export in exports_by_row.values():
        if export.source_kind != "MEASUREMENT":
            continue
        required_bits = {"BCD16_MV": 16, "ADC12_3V3": 12}.get(export.format.upper())
        if required_bits is None:
            continue
        result.append(SimpleNamespace(
            item=export.item,
            cp=str(flow.loc[export.flow_row_index].get("CP NO", "")).strip(),
            required_bits=required_bits,
            symbol=export.symbol,
            flow_row_index=export.flow_row_index,
        ))
    return tuple(result)


def validate_storage_role_occupancy(catalog) -> None:
    """Reject a physical bit range claimed by different TRIM/VERIFY owners."""
    occupied = []
    for kind, records in (("trim", catalog.trim_storage_mappings), ("verify", catalog.verify_storage_mappings)):
        for record in records:
            for field in catalog.selected_storage_fields(kind, record.item) or ():
                physical = (field.page.casefold(), field.register.casefold())
                interval = (field.lsb, field.lsb + field.width)
                owner = (kind, logical_item_key(record.item))
                for old_physical, old_interval, old_owner in occupied:
                    if physical == old_physical and owner != old_owner and max(interval[0], old_interval[0]) < min(interval[1], old_interval[1]):
                        raise ProjectMappingsError(
                            f"存储字段重叠：{kind.upper()} {record.item} 与 {old_owner[0].upper()} {old_owner[1]}"
                        )
                occupied.append((physical, interval, owner))


def validate_storage_flow_occupancy(flow, catalog) -> None:
    """Check explicit targets against every remaining legacy TRIM/VERIFY owner."""
    from program_gen.core.trim_data import trim_data_reference_matches

    occupied = []
    for _row, record in flow.iterrows():
        kind = str(record.get("type", "")).strip().casefold()
        if kind not in ("trim", "verify"):
            continue
        item, cp = str(record.get("item", "")).strip(), str(record.get("CP NO", "")).strip()
        selected = catalog.selected_storage_fields(kind, item)
        explicit = selected is not None
        if selected is None:
            if kind == "trim":
                fields = tuple(field for field in catalog.fields
                               if field.register_layout.applies_to(cp)
                               and trim_data_reference_matches(item, field.name))
            else:
                expected = (logical_item_key(item) + "_verify").casefold()
                fields = tuple(field for field in catalog.fields
                               if field.register_layout.applies_to(cp) and field.name.casefold() == expected)
        else:
            fields = tuple(field for field in selected if field.register_layout.applies_to(cp))
        owner = (kind, logical_item_key(item))
        for field in fields:
            physical, interval = (field.page.casefold(), field.register.casefold()), (field.lsb, field.lsb + field.width)
            for old_physical, old_interval, old_owner, old_explicit in occupied:
                if (explicit or old_explicit) and physical == old_physical and owner != old_owner and max(interval[0], old_interval[0]) < min(interval[1], old_interval[1]):
                    raise ProjectMappingsError(
                        f"存储字段重叠：{kind.upper()} {item} 与 {old_owner[0].upper()} {old_owner[1]}"
                    )
            occupied.append((physical, interval, owner, explicit))


def validate_storage_explicit_commits(catalog, trim_specs, verify_sources, recipe_rows) -> None:
    """An explicit COMMIT may not bypass an enabled physical mapping."""
    source_sets = (
        ("trim", catalog.trim_storage_mappings, {
            logical_item_key(spec.item): {str(spec.dac_final_symbol).casefold()}
            for spec in trim_specs.values()
        }),
        ("verify", catalog.verify_storage_mappings, _symbols_by_item(verify_sources)),
    )
    for kind, records, symbols_by_item in source_sets:
        for record in records:
            selected = catalog.selected_storage_fields(kind, record.item) or ()
            symbols = symbols_by_item.get(logical_item_key(record.item), set())
            selected_ids = {_physical_field_id(field) for field in selected}
            for executable in recipe_rows.values():
                assignments = tuple(assignment for call in executable.operations if call.name == "COMMIT"
                                    for assignment in call.assignments)
                consumed_ids = set()
                for assignment in assignments:
                    actual_ids = _assignment_physical_ids(catalog, assignment.field)
                    if actual_ids & selected_ids and (
                        assignment.value.kind != "VARIABLE" or assignment.value.token.casefold() not in symbols
                    ):
                        raise ProjectMappingsError(
                            f"COMMIT 已将字段 {assignment.field} 绑定到其他值，不能同时作为 {record.item} 的存储目标"
                        )
                    if assignment.value.kind == "VARIABLE" and assignment.value.token.casefold() in symbols:
                        consumed_ids.update(actual_ids)
                if consumed_ids and consumed_ids != selected_ids:
                    raise ProjectMappingsError(
                        f"COMMIT 使用 {record.item} 的结果时必须同时写入全部选定存储字段"
                    )


def _symbols_by_item(sources) -> dict[str, set[str]]:
    result = {}
    for source in sources:
        result.setdefault(logical_item_key(source.item), set()).add(str(source.symbol).casefold())
    return result


def _physical_field_id(field) -> tuple[str, str, int, int]:
    return field.page.casefold(), field.register.casefold(), field.lsb, field.width


def _assignment_physical_ids(catalog, name: str) -> set[tuple[str, str, int, int]]:
    """Resolve COMMIT spellings to actual intervals, including CP-map aliases."""
    try:
        fields = catalog.resolve_fields(name)
    except Exception:
        fields = ()
    if not fields:
        fields = tuple(field for field in catalog.storage_fields
                       if field.name.casefold() == str(name).casefold())
    return {_physical_field_id(field) for field in fields}


def validate_trim_storage_mappings(mappings, flow, catalog, trim_specs, recipe_rows):
    """Compatibility wrapper for callers that still pass the v2 flat shape."""
    from types import SimpleNamespace
    sources = tuple(SimpleNamespace(
        item=spec.item,
        cp=spec.cp,
        required_bits=max(spec.search.search_bits, getattr(getattr(spec, "dac", None), "field_width", 0)),
    ) for spec in trim_specs.values())
    groups = normalize_storage_mappings(mappings)
    validate_storage_mapping_records("trim", groups, catalog, sources)
    _validate_trim_legacy_ownership(groups, flow, catalog)
    _validate_trim_explicit_commits(groups, catalog, trim_specs, recipe_rows)
    return tuple(mappings)


def _validate_trim_legacy_ownership(groups, flow, catalog) -> None:
    from program_gen.core.trim_data import trim_data_reference_matches

    mapped = {logical_item_key(group.item): group for group in groups}
    occupied = []
    for _row, record in flow.iterrows():
        if str(record.get("type", "")).strip().casefold() != "trim":
            continue
        item, cp = str(record.get("item", "")).strip(), str(record.get("CP NO", "")).strip()
        key = logical_item_key(item)
        fields = (catalog.selected_storage_fields("trim", item) if key in mapped else tuple(
            field for field in catalog.fields
            if field.register_layout.applies_to(cp) and trim_data_reference_matches(item, field.name)
        )) or ()
        for field in fields:
            interval = (field.lsb, field.lsb + field.width)
            physical = (field.page.casefold(), field.register.casefold())
            for old_physical, old_interval, old_owner in occupied:
                if physical == old_physical and old_owner != key and max(interval[0], old_interval[0]) < min(interval[1], old_interval[1]):
                    raise ProjectMappingsError(f"TRIM 存储字段重叠：{item} 与 {old_owner}")
            occupied.append((physical, interval, key))


def _validate_trim_explicit_commits(groups, catalog, trim_specs, recipe_rows) -> None:
    for group in groups:
        selected = catalog.selected_storage_fields("trim", group.item) or ()
        fields = {field.name.casefold() for field in selected}
        symbols = {str(spec.dac_final_symbol).casefold() for spec in trim_specs.values()
                   if logical_item_key(spec.item) == logical_item_key(group.item)}
        for executable in recipe_rows.values():
            assignments = tuple(assignment for call in executable.operations if call.name == "COMMIT"
                                for assignment in call.assignments)
            consumed = {assignment.field.casefold() for assignment in assignments
                        if assignment.value.kind == "VARIABLE" and assignment.value.token.casefold() in symbols}
            for assignment in assignments:
                if assignment.field.casefold() in fields and (assignment.value.kind != "VARIABLE" or assignment.value.token.casefold() not in symbols):
                    raise ProjectMappingsError(f"COMMIT 已将字段 {assignment.field} 绑定到其他值")
            if consumed and consumed != fields:
                raise ProjectMappingsError(f"COMMIT 使用 {group.item} 的 DAC_FINAL 时必须同时写入全部选定存储字段")


__all__ = [
    "MAPPINGS_PART", "ProjectMappingsError", "StorageMapping", "StorageTarget", "TrimStorageMapping",
    "normalize_storage_mappings", "parse_storage_mappings", "parse_trim_storage_mappings",
    "read_storage_mappings", "read_verify_storage_mappings", "validate_storage_mapping_records",
    "validate_storage_role_occupancy", "verify_storage_sources",
    "validate_storage_flow_occupancy",
    "validate_storage_explicit_commits",
    "validate_trim_storage_mappings",
]
