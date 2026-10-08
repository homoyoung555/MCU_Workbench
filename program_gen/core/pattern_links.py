"""Workbook-carried Pattern Link records."""

from __future__ import annotations

from io import BytesIO
import json
import re
from collections.abc import Mapping
from zipfile import BadZipFile, ZipFile, ZipInfo


PATTERN_LINKS_PART = "mcu/pattern-links.json"
_KEYS = {"cp", "item", "phase", "role", "platform", "original", "pattern"}
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_PLATFORMS = {"shared", "chroma", "s100"}


def validate_pattern_links(records: list[dict]) -> list[dict]:
    if not isinstance(records, list) or len(records) > 10000:
        raise ValueError("Pattern Link 必须是对象数组")
    result, seen = [], set()
    for index, record in enumerate(records):
        if not isinstance(record, Mapping) or set(record) != _KEYS:
            raise ValueError(f"Pattern Link[{index}] 键必须精确为 cp,item,phase,role,platform,original,pattern")
        values = {}
        for key in _KEYS:
            value = record[key]
            if not isinstance(value, str) or not value or len(value) > 256:
                raise ValueError(f"Pattern Link[{index}].{key} 必须是非空字符串")
            if any(ord(char) < 32 or ord(char) == 127 for char in value):
                raise ValueError(f"Pattern Link[{index}].{key} 含无效控制字符")
            values[key] = value
        if values["platform"] not in _PLATFORMS:
            raise ValueError(f"Pattern Link[{index}].platform 必须是 shared/chroma/s100")
        for key in ("original", "pattern"):
            if not _IDENTIFIER.fullmatch(values[key]):
                raise ValueError(f"Pattern Link[{index}].{key} 不是合法 Pattern 标识符")
        unique = (values["cp"], values["platform"], values["original"])
        if unique in seen:
            raise ValueError("同一 CP、platform、original 不能重复")
        seen.add(unique)
        result.append(values)
    return result


def read_pattern_links(raw: bytes) -> list[dict]:
    try:
        with ZipFile(BytesIO(raw)) as archive:
            entries = [entry for entry in archive.infolist() if entry.filename == PATTERN_LINKS_PART]
            if not entries:
                return []
            if len(entries) != 1:
                raise ValueError(f"{PATTERN_LINKS_PART} 不能重复出现")
            if entries[0].file_size > 1024 * 1024:
                raise ValueError(f"{PATTERN_LINKS_PART} 不能超过 1 MiB")
            encoded = archive.read(entries[0])
    except BadZipFile as exc:
        raise ValueError("工作簿不是可读取的 OOXML ZIP") from exc
    try:
        document = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{PATTERN_LINKS_PART} 不是有效 UTF-8 JSON") from exc
    return validate_pattern_links(document)


def patch_pattern_links(raw: bytes, records: list[dict]) -> bytes:
    records = validate_pattern_links(records)
    result = BytesIO()
    try:
        with ZipFile(BytesIO(raw)) as source, ZipFile(result, "w") as output:
            output.comment = source.comment
            entries = [entry for entry in source.infolist() if entry.filename == PATTERN_LINKS_PART]
            if len(entries) > 1:
                raise ValueError(f"{PATTERN_LINKS_PART} 不能重复出现")
            for entry in source.infolist():
                if entry.filename == PATTERN_LINKS_PART:
                    continue
                output.writestr(entry, source.read(entry))
            payload = json.dumps(records, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
            if len(payload) > 1024 * 1024:
                raise ValueError("Pattern Link JSON 不能超过 1 MiB")
            output.writestr(ZipInfo(PATTERN_LINKS_PART), payload)
    except BadZipFile as exc:
        raise ValueError("工作簿不是可读取的 OOXML ZIP") from exc
    return result.getvalue()
