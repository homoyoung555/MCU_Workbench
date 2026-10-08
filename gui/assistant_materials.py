"""Read-only evidence reconciliation for imported SWD register materials."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping


def reconcile_materials(materials_state, rows, db=None):
    """Return deterministic evidence for imported facts relevant to ``rows``.

    Imported material never overrides the bundled EncodingDB.  A source is only
    accepted after its concrete address and field facts agree with that DB.
    """
    if not isinstance(materials_state, Mapping) or not isinstance(rows, list):
        raise ValueError("资料状态和 SWD 行必须有效")
    if db is None:
        from swd_authoring import EncodingDB
        db = EncodingDB("py32f420")

    row_addresses = _row_addresses(rows)
    candidates, identities = _bundled_registers(db)
    row_candidates = {address: candidates.get(address, ()) for address in row_addresses}
    sources, materials = _sources(materials_state)
    relevant = [item for item in sources if _relevant(item, row_addresses, row_candidates, identities)]
    active = _active_sources(relevant, materials_state)

    checked = []
    for source in active:
        source_address = _address(source["address"])
        identities_here = row_candidates.get(source_address, ())
        identity = _source_identity(source, identities)
        if not identities_here:
            # The same named register at another address is a material claim
            # about this row and must not be treated as harmless background.
            if identity in {item["identity"] for values in row_candidates.values() for item in values}:
                raise ValueError(f"资料来源 {source['id']} 的寄存器地址与内置资料矛盾")
            continue
        candidate = next((item for item in identities_here if item["identity"] == identity), None)
        if candidate is None:
            raise ValueError(f"资料来源 {source['id']} 的寄存器身份或地址与内置资料矛盾")
        _check_source(source, candidate)
        checked.append({
            "sourceId": source["id"],
            "materialId": source["materialId"],
            "identity": identity,
            "address": _address_text(source_address),
            "fieldCount": len(source["fields"]),
            "factsDigest": _digest({key: source.get(key) for key in
                                     ("address", "peripheral", "name", "resetValue", "access", "fields")}),
        })

    checked.sort(key=lambda item: (item["address"], item["identity"], item["sourceId"]))
    version = materials_state.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"[0-9a-f]{64}", version):
        version = _digest(materials_state)
    return {
        "schemaVersion": 1,
        "materialVersion": version,
        "knowledgeVersion": db.knowledge_version(),
        "scope": "reconciled" if checked else "bundled_only",
        "checkedSources": checked,
        "checkedAddresses": [_address_text(address) for address in sorted(row_addresses)],
    }


def _row_addresses(rows):
    result = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("SWD 行必须是对象")
        if row.get("addr") not in (None, ""):
            result.add(_address(row["addr"]))
    return result


def _bundled_registers(db):
    fieldmap = db._load_fieldmap()  # EncodingDB owns the bundled read-only snapshot.
    addresses = db._addresses or {}
    by_address, identities = {}, {}
    for peripheral, registers in fieldmap.items():
        for register, fields in registers.items():
            for instance, raw_address in (addresses.get(peripheral, {}).get(register, {}) or {}).items():
                address = _address(raw_address)
                identity = f"{str(instance).upper()}.{str(register).upper()}"
                item = {"identity": identity, "fields": {name: db.field(instance, register, name) for name in fields}}
                by_address.setdefault(address, []).append(item)
                identities[identity] = item
    for values in by_address.values():
        values.sort(key=lambda item: item["identity"])
    return by_address, identities


def _sources(state):
    materials = state.get("materials")
    registers = state.get("registers")
    if not isinstance(materials, list) or not isinstance(registers, list):
        raise ValueError("资料状态缺少完整 materials/registers")
    material_ids = {item.get("id") for item in materials if isinstance(item, Mapping) and isinstance(item.get("id"), str)}
    result, source_ids = [], set()
    for register in registers:
        if not isinstance(register, Mapping) or not isinstance(register.get("sources"), list):
            raise ValueError("资料寄存器来源无效")
        listed_address = _address(register.get("address"))
        for source in register["sources"]:
            if not isinstance(source, Mapping):
                raise ValueError("资料来源无效")
            source_id, material_id = source.get("id"), source.get("materialId")
            if not isinstance(source_id, str) or not source_id or source_id in source_ids:
                raise ValueError("资料来源标识无效")
            if not isinstance(material_id, str) or material_id not in material_ids:
                raise ValueError("资料来源缺少可核验的原始资料")
            source_address = _address(source.get("address"))
            if source_address != listed_address:
                raise ValueError("资料来源地址与资料库索引不一致")
            item = dict(source)
            item["address"] = source_address
            result.append(item)
            source_ids.add(source_id)
    return result, material_ids


def _relevant(source, row_addresses, row_candidates, identities):
    address = source["address"]
    if address in row_addresses:
        return True
    identity = _source_identity(source, identities)
    return identity in {item["identity"] for values in row_candidates.values() for item in values}


def _active_sources(relevant, state):
    by_id = {source["id"]: source for source in relevant}
    conflicts = state.get("conflicts", [])
    confirmations = state.get("confirmations", {})
    if not isinstance(conflicts, list) or not isinstance(confirmations, Mapping):
        raise ValueError("资料冲突状态无效")
    blocked, selected = set(), set()
    for conflict in conflicts:
        if not isinstance(conflict, Mapping) or not isinstance(conflict.get("sourceIds"), list):
            raise ValueError("资料冲突记录无效")
        source_ids = set(conflict["sourceIds"])
        if not source_ids & set(by_id):
            continue
        confirmation = confirmations.get(conflict.get("id"))
        selected_id = confirmation.get("sourceId") if isinstance(confirmation, Mapping) else None
        if not isinstance(selected_id, str) or selected_id not in source_ids:
            raise ValueError(f"相关资料冲突 {conflict.get('id', '')} 未选择来源")
        if selected_id not in by_id:
            raise ValueError(f"相关资料冲突 {conflict.get('id', '')} 选择了无关来源")
        blocked.update(source_ids - {selected_id})
        selected.add(selected_id)
    if blocked & selected:
        raise ValueError('同一相关资料的来源选择互相矛盾，暂不支持跨来源拼接字段裁决')
    return [source for source in relevant if source["id"] not in blocked]


def _source_identity(source, known):
    peripheral = str(source.get("peripheral") or "").upper()
    name = str(source.get("name") or "").upper()
    if peripheral and name.startswith(peripheral + "_"):
        name = name[len(peripheral) + 1:]
    direct = f"{peripheral}.{name}" if peripheral else name
    if direct in known:
        return direct
    if not peripheral:
        return next((identity for identity in known if identity.replace(".", "_") == name), direct)
    return direct


def _check_source(source, candidate):
    fields = source.get("fields")
    if not isinstance(fields, list) or not fields:
        raise ValueError(f"资料来源 {source['id']} 缺少可核验的字段证据")
    expected = candidate["fields"]
    for field in fields:
        if not isinstance(field, Mapping) or not isinstance(field.get("name"), str):
            raise ValueError(f"资料来源 {source['id']} 的字段证据无效")
        info = expected.get(field["name"].upper())
        if info is None:
            raise ValueError(f"资料来源 {source['id']} 的字段与内置资料矛盾")
        position, width = _field_range(field)
        if (position, width) != (info.get("pos"), info.get("width")):
            raise ValueError(f"资料来源 {source['id']} 的字段 {field['name']} 位段与内置资料矛盾")
        # SVD register access is a default; an explicit field value overrides it.
        given_access = _access(field.get("access") or source.get("access"))
        if given_access is not None and given_access != _access(info.get("access")):
            raise ValueError(f"资料来源 {source['id']} 的字段 {field['name']} 访问与内置资料矛盾")
        given_reset = _number(field.get("resetValue"))
        if field.get("resetValue") not in (None, "") and given_reset is None:
            raise ValueError(f"资料来源 {source['id']} 的字段 {field['name']} 复位值无法核验")
        expected_reset = _number(info.get("reset"))
        if given_reset is not None and (expected_reset is None or given_reset != expected_reset):
            raise ValueError(f"资料来源 {source['id']} 的字段 {field['name']} 复位值与内置资料矛盾")
    if source.get("resetValue") not in (None, ""):
        given_reset = _number(source["resetValue"])
        expected_reset = _register_reset(expected)
        if given_reset is None or expected_reset is None:
            raise ValueError(f"资料来源 {source['id']} 的寄存器复位值缺少可核验证据")
        if given_reset != expected_reset:
            raise ValueError(f"资料来源 {source['id']} 的寄存器复位值与内置资料矛盾")


def _field_range(field):
    bits = field.get("bits")
    if isinstance(bits, str):
        match = re.fullmatch(r"\[(\d+)(?::(\d+))?\]", bits.strip())
        if match:
            high, low = int(match.group(1)), int(match.group(2) or match.group(1))
            if high >= low:
                return low, high - low + 1
    offset, width = field.get("bitOffset"), field.get("bitWidth")
    if type(offset) is int and type(width) is int and offset >= 0 and width > 0:
        return offset, width
    raise ValueError("资料字段缺少可核验位段")


def _register_reset(fields):
    word = 0
    for info in fields.values():
        reset = _number(info.get("reset"))
        if reset is None:
            return None
        word |= (reset & ((1 << info["width"]) - 1)) << info["pos"]
    return word & 0xFFFFFFFF


def _access(value):
    if value in (None, ""):
        return None
    compact = re.sub(r"[^a-z]", "", str(value).lower())
    return {"readonly": "RO", "ro": "RO", "read": "RO", "r": "RO",
            "readwrite": "RW", "rw": "RW", "writeonly": "WO", "wo": "WO",
            "write": "WO", "w": "WO"}.get(compact, compact.upper())


def _number(value):
    if type(value) is int and value >= 0:
        return value
    if not isinstance(value, str):
        return None
    text = value.strip().replace("_", "")
    if not text:
        return None
    try:
        if re.fullmatch(r"0[xX][0-9a-fA-F]+", text):
            return int(text, 16)
        if re.search(r"[xXzZ]", text):
            return None
        match = re.fullmatch(r"\d+'([bBoOdDhH])([0-9a-fA-F]+)", text)
        if match:
            return int(match.group(2), {"b": 2, "o": 8, "d": 10, "h": 16}[match.group(1).lower()])
        return int(text, 10)
    except ValueError:
        return None


def _address(value):
    if type(value) is int and 0 <= value <= 0xFFFFFFFF:
        return value
    if isinstance(value, str) and re.fullmatch(r"0[xX][0-9a-fA-F]{1,8}", value.strip()):
        return int(value, 16)
    raise ValueError("SWD 或资料地址无效")


def _address_text(value):
    return f"0x{value:08x}"


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
